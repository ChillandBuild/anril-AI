"""The admin's "Needs attention" list for call scoring.

Every warning is one row (deduped per call+type). Only `rude` and `wrong_info`
push a notification straight away, at most one per telecaller per hour; the rest
wait in the list and in the 09:00 IST morning summary, so admins aren't flooded.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.services.notify import notify_user
from app.services.scoring_rules import (
    ALERT_RATE_LIMIT_PER_HOUR, LEAD_SOURCE_BAD_RATE, LEAD_SOURCE_MIN_CALLS,
)
from app.services.call_wrapup import LANGUAGE_LABEL

logger = logging.getLogger(__name__)

ALERT_TYPES = (
    "rude", "wrong_info", "crm_mismatch", "no_proof", "transcript_failed",
    "language_barrier", "lead_source_quality", "tracks_swapped",
)
INSTANT_TYPES = ("rude", "wrong_info")
# SIM clients get no evaluation at all: these types only ever come from call
# scoring, which never runs for them, so they're excluded from every alert
# read for a SIM tenant. language_barrier/lead_source_quality are operational
# (wrap-up and lead-quality signals, not call scoring) and stay for everyone.
EVALUATION_ALERT_TYPES = (
    "rude", "wrong_info", "crm_mismatch", "no_proof", "transcript_failed", "tracks_swapped",
)
ALERT_LABELS = {
    "rude": "Rude or dismissive on a call",
    "wrong_info": "Wrong product information",
    "crm_mismatch": "Wrap-up doesn't match the call",
    "no_proof": "Mark without proof",
    "transcript_failed": "Call couldn't be transcribed",
    "language_barrier": "Language barrier",
    "lead_source_quality": "Lead source giving bad numbers",
    "tracks_swapped": "Voice tracks may be swapped",
}


def admin_user_ids(db, tenant_id: str) -> list[str]:
    rows = db.table("tenant_users").select("user_id,role").eq("tenant_id", tenant_id).in_("role", ["owner", "admin"]).execute()
    return [r["user_id"] for r in (rows.data or []) if r.get("user_id")]


def _caller_name(db, caller_id: str | None) -> str:
    if not caller_id:
        return "A telecaller"
    res = db.table("callers").select("name").eq("id", caller_id).limit(1).execute()
    return ((res.data or [{}])[0]).get("name") or "A telecaller"


def raise_alert(
    db, *, tenant_id: str, type: str, call_log_id: str | None = None, caller_id: str | None = None,
    quote: str | None = None, detail: dict | None = None, now: datetime | None = None,
) -> bool:
    if type not in ALERT_TYPES:
        raise ValueError(f"unknown alert type {type}")
    now = now or datetime.now(timezone.utc)
    row = {
        "tenant_id": tenant_id, "call_log_id": call_log_id, "caller_id": caller_id, "type": type,
        "quote": quote, "detail": detail or {}, "created_at": now.isoformat(),
    }
    try:
        res = db.table("call_alerts").insert(row).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return False
        raise
    alert_id = (res.data or [{}])[0].get("id")

    if type in INSTANT_TYPES and caller_id:
        since = (now - timedelta(hours=1)).isoformat()
        recent = (
            db.table("call_alerts").select("id").eq("caller_id", caller_id)
            .in_("type", list(INSTANT_TYPES)).gte("notified_at", since).execute()
        ).data or []
        if len(recent) < ALERT_RATE_LIMIT_PER_HOUR:
            name = _caller_name(db, caller_id)
            for user_id in admin_user_ids(db, tenant_id):
                notify_user(tenant_id, user_id, f"call_alert_{type}", ALERT_LABELS[type],
                            f"{name}: {quote or ALERT_LABELS[type]}", db=db,
                            push_url="/dashboard/call-iq/evaluation#needs-attention")
            db.table("call_alerts").update({"notified_at": now.isoformat()}).eq("id", alert_id).execute()
    return True


def raise_reassign_alert(db, *, tenant_id: str, call_log_id: str, caller_id: str | None, language: str) -> None:
    """A 'Language barrier' wrap-up. Alerts are deduped per call+type, so if the AI already raised a
    language_barrier alert for this call, that row is rewritten with the language and shown again."""
    quote = (
        "Reassign to someone who speaks the customer's language" if language == "other"
        else f"Reassign to a {LANGUAGE_LABEL[language]} speaker"
    )
    detail = {"preferred_language": language, "source": "wrapup"}
    if raise_alert(db, tenant_id=tenant_id, type="language_barrier", call_log_id=call_log_id,
                   caller_id=caller_id, quote=quote, detail=detail):
        return
    (
        db.table("call_alerts")
        .update({"quote": quote, "detail": detail, "seen_at": None, "seen_by": None})
        .eq("call_log_id", call_log_id).eq("type", "language_barrier").eq("tenant_id", tenant_id)
        .execute()
    )


def lead_source_is_bad(total: int, bad: int) -> bool:
    return total >= LEAD_SOURCE_MIN_CALLS and bad / total >= LEAD_SOURCE_BAD_RATE


def _ist_calendar_day(day_start_iso: str) -> str:
    from app.services.telecaller_performance import IST_OFFSET

    start = datetime.fromisoformat(day_start_iso.replace("Z", "+00:00"))
    return (start + IST_OFFSET).date().isoformat()


def run_lead_source_check(db, tenant_id: str, day_start_iso: str, day_end_iso: str) -> int:
    """Raise one lead_source_quality alert per source that gave 30%+ wrong/never-enquired numbers."""
    day = _ist_calendar_day(day_start_iso)
    rows = (
        db.table("call_logs").select("call_group,evaluation,leads(source)")
        .eq("tenant_id", tenant_id).eq("provider", "telecmi")
        .in_("call_group", ["early_exit", "real_conversation"])
        .gte("created_at", day_start_iso).lt("created_at", day_end_iso).execute()
    ).data or []
    by_source: dict[str, list[int]] = {}
    for r in rows:
        source = ((r.get("leads") or {}).get("source")) or "unknown"
        early = (r.get("evaluation") or {}).get("early_exit_check") or {}
        bad = r.get("call_group") == "early_exit" and early.get("expected_crm") in ("wrong_number", "not_enquired")
        tally = by_source.setdefault(source, [0, 0])
        tally[0] += 1
        tally[1] += int(bad)
    raised = 0
    for source, (total, bad) in by_source.items():
        if lead_source_is_bad(total, bad):
            raise_alert(db, tenant_id=tenant_id, type="lead_source_quality",
                        quote=f"{source}: {bad} of {total} answered calls were wrong numbers or never enquired",
                        detail={"source": source, "total": total, "bad": bad, "day": day})
            raised += 1
    return raised


def send_morning_summaries(db, now: datetime | None = None) -> int:
    """One notification per tenant admin with yesterday's (IST) alert counts. Skips empty days."""
    from app.services.telecaller_performance import ist_day_bounds

    now = now or datetime.now(timezone.utc)
    start, end = ist_day_bounds(now - timedelta(days=1))
    tenants = {r["tenant_id"] for r in (db.table("call_logs").select("tenant_id").eq("provider", "telecmi").gte("created_at", start).lt("created_at", end).execute()).data or []}
    sent = 0
    for tenant_id in tenants:
        try:
            run_lead_source_check(db, tenant_id, start, end)
            alerts = (db.table("call_alerts").select("type").eq("tenant_id", tenant_id).gte("created_at", start).lt("created_at", end).execute()).data or []
            if not alerts:
                continue
            counts: dict[str, int] = {}
            for a in alerts:
                counts[a["type"]] = counts.get(a["type"], 0) + 1
            text = ", ".join(f"{n} {ALERT_LABELS[t].lower()}" for t, n in sorted(counts.items(), key=lambda kv: -kv[1]))
            for user_id in admin_user_ids(db, tenant_id):
                notify_user(tenant_id, user_id, "call_alerts_summary", "Yesterday's calls need attention",
                            f"{text}.", db=db, push_url="/dashboard/call-iq/evaluation#needs-attention")
                sent += 1
        except Exception as e:
            logger.error(f"Morning summary failed for tenant {tenant_id}: {e}")
    return sent
