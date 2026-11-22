"""Engage > Auto-Messages > Sent: every message that went out by itself, and the ones that didn't.

One newest-first list merged from four logs, all tenant-scoped:
  auto_message_sends     "When something happens" messages (label = the event)
  scheduled_template_sends  one-time sends (label "One-time send . <template>")
  silence_nudge_jobs     quick AI nudges inside 24 hours ("Quick nudge")
  reengagement_logs      follow-up steps ("Follow-up . Day 3" / "Follow-up . 2 hrs")

Status per row: delivered | read | sent | not_sent | will_retry. A "sent" row is upgraded to
delivered / read / not_sent (a failure Meta reported afterwards, with its reason) only when
it can be tied to exactly ONE messages row: same person, same text, same sender kind, within
two minutes of the send, and no other log row competing for that message. None of the four
logs stores the message id, so this is the tightest exact link there is; when it is not
unique the row simply stays "sent". Nothing is guessed.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services.growth import IST_OFFSET
from app.services.send_reasons import explain

logger = logging.getLogger(__name__)
router = APIRouter()
require_auto_messages_view = require_permission("auto_messages.view")

PER_SOURCE_CAP = 500
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
_BATCH = 100
_LINK_WINDOW = timedelta(seconds=120)

_BUILTIN_EVENT_LABEL = {"interested": "Interested", "signed_up": "Signed up", "purchased": "Purchased"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(raw) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _chunks(values: list, size: int = _BATCH):
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _safe(name: str, fn):
    """Run one source's read; a failing or not-yet-migrated source is left out, never a 500."""
    try:
        return fn()
    except Exception as e:
        logger.warning(f"auto-messages sent: {name} unavailable ({e})")
        return []


# ---------------------------------------------------------------- sources

def _read_auto_sends(db, tenant_id: str, since: str) -> list[dict]:
    rows = (
        db.table("auto_message_sends")
        .select("id, lead_id, phone, name, event, template_id, status, reason, send_at, sent_at, created_at")
        .eq("tenant_id", tenant_id).gte("created_at", since)
        .order("created_at", desc=True).limit(PER_SOURCE_CAP).execute().data or []
    )
    event_labels = dict(_BUILTIN_EVENT_LABEL)
    try:
        for e in db.table("auto_message_events").select("key, label").eq("tenant_id", tenant_id).execute().data or []:
            event_labels[e["key"]] = e.get("label") or e["key"]
    except Exception as e:
        logger.warning(f"auto-messages sent: custom events unavailable ({e})")
    template_ids = list({r["template_id"] for r in rows if r.get("template_id")})
    templates: dict[str, str] = {}
    for batch in _chunks(template_ids):
        for t in db.table("message_templates").select("id, name").eq("tenant_id", tenant_id).in_("id", batch).execute().data or []:
            templates[t["id"]] = t["name"]
    out = []
    for r in rows:
        status = {"sent": "sent", "failed": "not_sent", "skipped": "not_sent"}.get(r.get("status"), "will_retry")
        event = r.get("event")
        tname = templates.get(r.get("template_id"))
        out.append({
            "source": "auto_message", "id": r["id"], "lead_id": r.get("lead_id"),
            "name": r.get("name"), "phone": r.get("phone"),
            "label": event_labels.get(event, (event or "").replace("_", " ").capitalize()) if event else "Sent by your app",
            "at": r.get("sent_at") or r.get("send_at") or r.get("created_at"),
            "sent_at": r.get("sent_at"), "status": status, "raw_reason": r.get("reason"),
            "match": {"content": f"[Auto-message: {tname}]" if tname else None, "reply_source": "automation"},
        })
    return out


def _read_scheduled(db, tenant_id: str, since: str) -> list[dict]:
    rows = (
        db.table("scheduled_template_sends")
        .select("id, lead_id, template_name, content, status, reason, send_at, sent_at, created_at")
        .eq("tenant_id", tenant_id).in_("status", ["sent", "failed", "skipped"]).gte("send_at", since)
        .order("send_at", desc=True).limit(PER_SOURCE_CAP).execute().data or []
    )
    return [{
        "source": "scheduled_template", "id": r["id"], "lead_id": r.get("lead_id"),
        "label": f"One-time send · {r.get('template_name') or 'template'}",
        "at": r.get("sent_at") or r.get("send_at"), "sent_at": r.get("sent_at"),
        "status": "sent" if r.get("status") == "sent" else "not_sent", "raw_reason": r.get("reason"),
        "match": {"content": r.get("content"), "reply_source": None},
    } for r in rows]


def _read_nudges(db, tenant_id: str, since: str) -> list[dict]:
    rows = (
        db.table("silence_nudge_jobs")
        .select("id, lead_id, status, skip_reason, message_preview, fire_at, sent_at, step_index")
        .eq("tenant_id", tenant_id).in_("status", ["sent", "skipped", "failed"]).gte("fire_at", since)
        .order("fire_at", desc=True).limit(PER_SOURCE_CAP).execute().data or []
    )
    return [{
        "source": "silence_nudge", "id": r["id"], "lead_id": r.get("lead_id"), "label": "Quick nudge",
        "at": r.get("sent_at") or r.get("fire_at"), "sent_at": r.get("sent_at"),
        "status": "sent" if r.get("status") == "sent" else "not_sent", "raw_reason": r.get("skip_reason"),
        "match": {"content": r.get("message_preview"), "reply_source": "silence_nudge"},
    } for r in rows]


def _read_followups(db, tenant_id: str, since: str) -> list[dict]:
    def _logs(columns: str):
        return (
            db.table("reengagement_logs").select(columns)
            .eq("tenant_id", tenant_id).gte("sent_at", since)
            .order("sent_at", desc=True).limit(PER_SOURCE_CAP).execute().data or []
        )
    try:
        rows = _logs("id, step_id, lead_id, status, reason, sent_at")
    except Exception as e:
        logger.warning(f"auto-messages sent: follow-up reasons unavailable ({e})")
        rows = _logs("id, step_id, lead_id, status, sent_at")
    step_ids = list({r["step_id"] for r in rows if r.get("step_id")})
    steps: dict[str, dict] = {}
    for batch in _chunks(step_ids):
        for s in (
            db.table("reengagement_steps")
            .select("id, delay_hours, message_type, message_content, template_name, fallback_template_name")
            .eq("tenant_id", tenant_id).in_("id", batch).execute().data or []
        ):
            steps[s["id"]] = s
    out = []
    for r in rows:
        step = steps.get(r.get("step_id")) or {}
        hours = int(step.get("delay_hours") or 0)
        label = f"Follow-up · Day {hours // 24}" if hours >= 24 and hours % 24 == 0 else f"Follow-up · {hours} hrs"
        if r.get("status") == "sent_fallback":
            content = f"[Template Broadcast: {step.get('fallback_template_name')}]" if step.get("fallback_template_name") else None
        elif step.get("message_type") == "template":
            content = f"[Template Broadcast: {step.get('template_name')}]" if step.get("template_name") else None
        else:
            content = step.get("message_content") or ""
        raw = r.get("reason") or ("skipped_window" if r.get("status") == "skipped_window" else None)
        out.append({
            "source": "follow_up", "id": r["id"], "lead_id": r.get("lead_id"), "label": label if step else "Follow-up",
            "at": r.get("sent_at"), "sent_at": r.get("sent_at"),
            "status": "sent" if r.get("status") in ("sent", "sent_fallback") else "not_sent", "raw_reason": raw,
            "match": {"content": content, "reply_source": "reengagement"},
        })
    return out


# ---------------------------------------------------------------- people + delivery

def _fill_people(db, tenant_id: str, rows: list[dict]) -> None:
    lead_ids = list({r["lead_id"] for r in rows if r.get("lead_id") and not (r.get("name") and r.get("phone"))})
    leads: dict[str, dict] = {}
    for batch in _chunks(lead_ids):
        for l in db.table("leads").select("id, name, phone").eq("tenant_id", tenant_id).in_("id", batch).execute().data or []:
            leads[l["id"]] = l
    for r in rows:
        lead = leads.get(r.get("lead_id")) or {}
        r["name"] = r.get("name") or lead.get("name")
        r["phone"] = r.get("phone") or lead.get("phone")


def _read_messages(db, tenant_id: str, lead_ids: list[str], since: datetime) -> list[dict]:
    out: list[dict] = []
    for batch in _chunks(lead_ids, 25):
        def _q(columns: str):
            return (
                db.table("messages").select(columns)
                .eq("tenant_id", tenant_id).eq("direction", "outbound")
                .in_("lead_id", batch).gte("created_at", since.isoformat()).limit(1000).execute().data or []
            )
        try:
            out += _q("id, lead_id, content, reply_source, created_at, delivery_status, delivery_error_code, delivery_error_title")
        except Exception as e:
            logger.warning(f"auto-messages sent: delivery error columns unavailable ({e})")
            out += _q("id, lead_id, content, reply_source, created_at, delivery_status")
    return out


def _link_delivery(db, tenant_id: str, rows: list[dict]) -> None:
    """Upgrade sent rows using the delivery status of the one message they exactly match."""
    todo = [r for r in rows if r["status"] == "sent" and r.get("lead_id") and r.get("sent_at")
            and r["match"].get("content") is not None]
    if not todo:
        return
    stamps = [d for d in (_parse(r["sent_at"]) for r in todo) if d]
    if not stamps:
        return
    messages = _safe("messages", lambda: _read_messages(
        db, tenant_id, list({r["lead_id"] for r in todo}), min(stamps) - _LINK_WINDOW))
    by_lead: dict[str, list[dict]] = {}
    for m in messages:
        by_lead.setdefault(m["lead_id"], []).append(m)

    candidates: dict[int, list[dict]] = {}
    claims: dict[str, int] = {}
    for idx, r in enumerate(todo):
        sent_at = _parse(r["sent_at"])
        if not sent_at:
            continue
        want_source = r["match"]["reply_source"]
        found = []
        for m in by_lead.get(r["lead_id"], []):
            created = _parse(m.get("created_at"))
            if not created or abs(created - sent_at) > _LINK_WINDOW:
                continue
            if (m.get("reply_source") or None) != want_source or (m.get("content") or "") != r["match"]["content"]:
                continue
            found.append(m)
        candidates[idx] = found
        for m in found:
            claims[m["id"]] = claims.get(m["id"], 0) + 1

    for idx, r in enumerate(todo):
        found = candidates.get(idx) or []
        if len(found) != 1 or claims.get(found[0]["id"]) != 1:
            continue
        m = found[0]
        r["message_id"] = m["id"]
        ds = (m.get("delivery_status") or "sent").lower()
        if ds in ("delivered", "read"):
            r["status"] = ds
        elif ds == "failed":
            r["status"] = "not_sent"
            r["raw_reason"] = None
            r["delivery_code"] = m.get("delivery_error_code")
            r["delivery_title"] = m.get("delivery_error_title")


# ---------------------------------------------------------------- shaping

def _action(row: dict, kind: str) -> dict:
    lead_id = row.get("lead_id")
    chat = f"/dashboard/conversations?lead={lead_id}" if lead_id else None
    if row["status"] == "will_retry" or (row["status"] == "not_sent" and kind == "retry"):
        return {"kind": "none", "label": "Nothing to do", "href": None}
    if row["status"] != "not_sent":
        return {"kind": "open_chat", "label": "Open chat", "href": chat}
    if kind == "undeliverable":
        # No endpoint marks a number wrong (WhatsApp's own failure report does it); open the lead to check the number.
        return {"kind": "open_lead", "label": "Open lead", "href": f"/dashboard/leads/{lead_id}" if lead_id else None}
    if kind == "template":
        return {"kind": "see_template", "label": "See template", "href": "/dashboard/templates"}
    if kind in ("stopped", "none"):
        return {"kind": "none", "label": "No action needed", "href": None}
    if kind == "window":
        return {"kind": "use_template", "label": "Use a template", "href": chat}
    return {"kind": "open_chat", "label": "Open chat", "href": chat}


def _shape(row: dict) -> dict:
    kind, why = "other", None
    if row["status"] == "not_sent":
        info = explain(row.get("raw_reason") or row.get("delivery_title"), code=row.get("delivery_code"))
        kind, why = info["kind"], info["text"]
    elif row["status"] == "will_retry":
        why = "Waiting to go out. It will be sent shortly."
    return {
        "source": row["source"], "lead_id": row.get("lead_id"), "name": row.get("name"), "phone": row.get("phone"),
        "label": row["label"], "at": row.get("at"), "status": row["status"], "why": why,
        "action": _action(row, kind), "message_id": row.get("message_id"),
    }


@router.get("/sent")
def list_sent(
    days: int = 7,
    only_not_sent: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    ctx: dict = Depends(require_auto_messages_view),
):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    days = 30 if days >= 30 else 7
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    now = _utcnow()
    since = (now - timedelta(days=days)).isoformat()

    rows: list[dict] = []
    for name, reader in (("auto_message_sends", _read_auto_sends), ("scheduled_template_sends", _read_scheduled),
                         ("silence_nudge_jobs", _read_nudges), ("reengagement_logs", _read_followups)):
        rows += _safe(name, lambda reader=reader: reader(db, tenant_id, since))
    rows = [r for r in rows if r.get("at")]
    rows.sort(key=lambda r: str(r["at"]), reverse=True)

    ist_today_start = ((now + IST_OFFSET).replace(hour=0, minute=0, second=0, microsecond=0) - IST_OFFSET).isoformat()

    def _is_today(r: dict) -> bool:
        at = _parse(r["at"])
        return bool(at and at.isoformat() >= ist_today_start)

    # Delivery lookups: everything when filtering to "not sent" (a send can fail afterwards),
    # otherwise today's rows (for the banner) and the rows on this page.
    if only_not_sent:
        _link_delivery(db, tenant_id, rows)
        rows = [r for r in rows if r["status"] == "not_sent"]
        page = rows[offset:offset + limit]
        today_not_sent = sum(1 for r in rows if _is_today(r))
    else:
        page = rows[offset:offset + limit]
        _link_delivery(db, tenant_id, list({id(r): r for r in [*[r for r in rows if _is_today(r)], *page]}.values()))
        today_not_sent = sum(1 for r in rows if r["status"] == "not_sent" and _is_today(r))

    _fill_people(db, tenant_id, page)
    return {
        "today_not_sent": today_not_sent,
        "total": len(rows),
        "has_more": offset + limit < len(rows),
        "rows": [_shape(r) for r in page],
    }
