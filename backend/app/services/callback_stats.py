"""Scheduled calls page: "kept on time" (v9.2 item 233).

A scheduled call (follow_up_jobs, cadence 'callback') is kept on time when a call linked to it was
made within 15 minutes of the scheduled time (15 minutes early up to 15 minutes late). Only calls that
were due in the last 30 days AND whose 15-minute window has already closed are counted, so a call due
in five minutes is never counted as missed. Calls that were superseded (cancelled by a later wrap-up)
are left out: nobody missed them. A call that was marked Done with no call linked to it counts as not kept.
"""
from datetime import datetime, timedelta, timezone

from app.services.reports_common import chunks, paged

WINDOW = timedelta(minutes=15)
DAYS = 30


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def on_time_counts(jobs: list[dict], calls: list[dict]) -> tuple[int, int]:
    """(kept, due). jobs: {id, scheduled_for}; calls: {follow_up_job_id, created_at}."""
    by_job: dict[str, list[datetime]] = {}
    for call in calls:
        at = _parse(call.get("created_at"))
        if at and call.get("follow_up_job_id"):
            by_job.setdefault(str(call["follow_up_job_id"]), []).append(at)
    kept = due = 0
    for job in jobs:
        when = _parse(job.get("scheduled_for"))
        if when is None:
            continue
        due += 1
        if any(abs(at - when) <= WINDOW for at in by_job.get(str(job["id"]), [])):
            kept += 1
    return kept, due


def kept_on_time(db, tenant_id: str, scope: set[str] | None, now: datetime | None = None) -> dict:
    """{kept, due, percent, days}. scope: the caller ids a Team leader may see (None = everyone).
    percent is None until at least one scheduled call has fallen due in the window."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=DAYS)).isoformat()
    until = (now - WINDOW).isoformat()
    jobs = paged(lambda: (
        db.table("follow_up_jobs").select("id,lead_id,scheduled_for,status").eq("tenant_id", tenant_id)
        .eq("cadence", "callback").in_("status", ["sent", "pending"])
        .gte("scheduled_for", since).lte("scheduled_for", until)
    ))
    if scope is not None:
        if not scope:
            jobs = []
        else:
            mine: set[str] = set()
            for part in chunks(sorted({j["lead_id"] for j in jobs})):
                for lead in db.table("leads").select("id,assigned_to").eq("tenant_id", tenant_id).in_("id", part).execute().data or []:
                    if str(lead.get("assigned_to")) in scope:
                        mine.add(lead["id"])
            jobs = [j for j in jobs if j["lead_id"] in mine]
    calls: list[dict] = []
    for part in chunks([j["id"] for j in jobs]):
        calls += (
            db.table("call_logs").select("follow_up_job_id,created_at").eq("tenant_id", tenant_id)
            .in_("follow_up_job_id", part).execute().data or []
        )
    kept, due = on_time_counts(jobs, calls)
    return {"kept": kept, "due": due, "percent": round(100 * kept / due) if due else None, "days": DAYS}
