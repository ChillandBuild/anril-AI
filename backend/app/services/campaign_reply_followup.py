"""Follow-up trigger "campaign reply, no order" (reengagement_steps.type = 'campaign_reply').

Who is due: a person who got a Reach campaign (broadcast_recipients sent), wrote back within
3 days of it, and has placed no order (a deal in awaiting_payment or won) since the campaign
went out, once the step's wait (delay_hours, 24 or more) has passed since their reply.
If the step names one campaign (broadcast_id) only that campaign counts; otherwise any.

Only people whose due time fell in the last 14 days are picked, so switching a step on never
chases replies from months ago. The engine (reengagement_service) then applies the same
send rules as every other step: approved template outside 24h, 10:00-20:00 IST Mon-Sat, one
day-step a day, nothing for opted out, blocked, undeliverable or already converted people.
"""
import logging
from datetime import datetime, timedelta

from app.services.reports_common import MAX_PAGES, PAGE, paged

logger = logging.getLogger(__name__)

REPLY_WINDOW = timedelta(days=3)    # a reply counts as "to the campaign" within this long after it
CATCH_UP = timedelta(days=14)       # how long past its due time a person can still be picked
ORDER_STAGES = ["awaiting_payment", "won"]
_CHUNK = 200


def _ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _chunks(items: list[str]):
    for i in range(0, len(items), _CHUNK):
        yield items[i:i + _CHUNK]


def _paged(make_query, what: str) -> list[dict]:
    """paged(), plus a log line when it stopped at its page cap (the answer may be cut short)."""
    rows = paged(make_query)
    if len(rows) >= MAX_PAGES * PAGE:
        logger.warning("campaign_reply: %s hit the %s-row read cap; some people may be missed", what, MAX_PAGES * PAGE)
    return rows


def _handled_lead_ids(db, step_id) -> set[str]:
    """People this step has already been logged for (sent, failed or skipped): never due again."""
    if not step_id:
        return set()
    rows = _paged(lambda: db.table("reengagement_logs").select("id, lead_id").eq("step_id", step_id),
                  "reengagement_logs")
    return {str(r["lead_id"]) for r in rows if r.get("lead_id")}


def due_lead_ids(db, tenant_id: str, step: dict, now: datetime) -> list[str]:
    """Lead ids due for this step right now (not yet filtered by segment, source, group or send rules)."""
    delay = timedelta(hours=int(step.get("delay_hours") or 0))
    earliest_send = now - delay - REPLY_WINDOW - CATCH_UP
    latest_send = now - delay

    def sends_query():
        q = (db.table("broadcast_recipients").select("id, lead_id, created_at")
             .eq("tenant_id", tenant_id).eq("send_status", "sent")
             .gte("created_at", earliest_send.isoformat()).lte("created_at", latest_send.isoformat()))
        if step.get("broadcast_id"):
            q = q.eq("broadcast_id", step["broadcast_id"])
        return q

    sends: dict[str, list[datetime]] = {}
    handled = _handled_lead_ids(db, step.get("id"))  # first, so the big scans below skip them
    for rec in _paged(sends_query, "broadcast_recipients"):
        sent_at = _ts(rec.get("created_at"))
        lead_id = str(rec["lead_id"]) if rec.get("lead_id") else None
        if sent_at and lead_id and lead_id not in handled:
            sends.setdefault(lead_id, []).append(sent_at)
    if not sends:
        return []

    # earliest reply per person, with the campaign it answered
    replied: dict[str, tuple[datetime, datetime]] = {}  # lead -> (campaign sent_at, reply_at)
    for chunk in _chunks(list(sends)):
        inbound = _paged(lambda: (
            db.table("messages").select("id, lead_id, created_at")
            .eq("tenant_id", tenant_id).eq("direction", "inbound").in_("lead_id", chunk)
            .gte("created_at", earliest_send.isoformat()).lte("created_at", latest_send.isoformat())
        ), "messages")
        for m in inbound:
            lead_id, at = str(m["lead_id"]), _ts(m.get("created_at"))
            if not at:
                continue
            for sent_at in sends.get(lead_id, ()):
                if sent_at <= at <= sent_at + REPLY_WINDOW:
                    best = replied.get(lead_id)
                    if best is None or at < best[1]:
                        replied[lead_id] = (sent_at, at)
                    break
    due = {lid: pair for lid, pair in replied.items()
           if now - CATCH_UP <= pair[1] + delay <= now}
    if not due:
        return []

    # drop anyone with an order since that campaign
    ordered: set[str] = set()
    for chunk in _chunks(list(due)):
        deals = _paged(lambda: (
            db.table("deals").select("id, lead_id, created_at")
            .eq("tenant_id", tenant_id).in_("stage", ORDER_STAGES).in_("lead_id", chunk)
        ), "deals")
        for d in deals:
            lead_id, at = str(d["lead_id"]), _ts(d.get("created_at"))
            if at and lead_id in due and at >= due[lead_id][0]:
                ordered.add(lead_id)
    return [lid for lid in due if lid not in ordered]
