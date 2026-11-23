"""v9.2 Reach: at 9 AM IST, tell the owner and admins how yesterday's campaigns did: sent, read, replied.

One bell (and phone push) per person per day: an alert of this type already sent today is not sent again,
so a re-run is harmless. A business that sent nothing yesterday hears nothing. Read comes from WhatsApp's
read receipts on the campaign message; replied = the person wrote to us after the campaign reached them.
A WhatsApp copy would need its own Meta-approved template (not done).
"""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
ALERT_TYPE = "campaign_summary"
_PAGE = 1000


def _bounds(now: datetime) -> tuple[str, str, str]:
    today = now.astimezone(IST).date()
    start = datetime(today.year, today.month, today.day, tzinfo=IST)
    y = start - timedelta(days=1)
    return y.astimezone(timezone.utc).isoformat(), start.astimezone(timezone.utc).isoformat(), start.astimezone(timezone.utc).isoformat()


def _paged(build) -> list[dict]:
    rows: list[dict] = []
    while True:
        page = build().range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows += page
        if len(page) < _PAGE:
            return rows


def tenant_numbers(db, tenant_id: str, recipients: list[dict]) -> dict:
    sent = [r for r in recipients if r.get("send_status") == "sent"]
    mids = [r["meta_message_id"] for r in sent if r.get("meta_message_id")]
    read = 0
    for i in range(0, len(mids), 200):
        read += sum(1 for m in (db.table("messages").select("delivery_status").eq("tenant_id", tenant_id)
                                .in_("meta_message_id", mids[i:i + 200]).execute().data or [])
                    if m.get("delivery_status") == "read")
    first_sent: dict[str, str] = {}
    for r in sent:
        if r.get("lead_id") and (r["lead_id"] not in first_sent or r["created_at"] < first_sent[r["lead_id"]]):
            first_sent[r["lead_id"]] = r["created_at"]
    replied = set()
    ids = list(first_sent)
    for i in range(0, len(ids), 200):
        for m in (db.table("messages").select("lead_id,created_at").eq("tenant_id", tenant_id).eq("direction", "inbound")
                  .in_("lead_id", ids[i:i + 200]).gte("created_at", min(first_sent.values())).execute().data or []):
            if m["created_at"] >= first_sent.get(m["lead_id"], "9999"):
                replied.add(m["lead_id"])
    return {"sent": len(sent), "read": read, "replied": len(replied)}


def send_morning_summaries(db=None, now: datetime | None = None) -> int:
    from app.services.call_alerts import admin_user_ids
    from app.services.notify import notify_user
    db = db or get_supabase()
    now = now or datetime.now(timezone.utc)
    start, end, today_start = _bounds(now)
    rows = _paged(lambda: db.table("broadcast_recipients").select("tenant_id,lead_id,send_status,meta_message_id,created_at")
                  .gte("created_at", start).lt("created_at", end).order("created_at"))
    by_tenant: dict[str, list[dict]] = {}
    for r in rows:
        by_tenant.setdefault(str(r["tenant_id"]), []).append(r)
    told = 0
    for tenant_id, recips in by_tenant.items():
        try:
            n = tenant_numbers(db, tenant_id, recips)
            if not n["sent"]:
                continue
            message = f"{n['sent']} sent · {n['read']} read · {n['replied']} replied. Open Reach for who paid."
            for uid in admin_user_ids(db, tenant_id):
                already = (db.table("app_notifications").select("id").eq("tenant_id", tenant_id).eq("user_id", uid)
                           .eq("type", ALERT_TYPE).gte("created_at", today_start).limit(1).execute().data)
                if already:
                    continue
                notify_user(tenant_id, uid, ALERT_TYPE, "Yesterday's campaigns", message, db=db,
                            push_url="/dashboard/outbound-leads?tab=history")
                told += 1
        except Exception as e:  # noqa: BLE001  one business must not stop the rest
            logger.warning("campaign morning summary failed for %s: %s", tenant_id, e)
    return told
