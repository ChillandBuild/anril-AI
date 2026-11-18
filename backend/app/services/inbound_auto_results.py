"""Engage > Inbound leads: results Anril sets or asks about by itself.

1. mark_stopped_replying (hourly): "Lost · stopped replying" for a lead that never answered
   the business's last follow-up within STOPPED_REPLYING_DAYS. The rules live in the SQL
   function stopped_replying_leads (migration 284): no result yet, not on Said stop, nothing
   from them since, and the follow-up was the last one of its kind. Marked with
   lost_auto = true, so the list shows "auto" and Undo; Undo sets auto_lost_dismissed_at and the
   job never marks them again for a follow-up sent before that.
2. remind_unmarked_bookings (daily at CLOSING_HOUR_IST): a bell (and push) to each owner listing
   today's bookings still not marked Came / Paid or Lost. In-app only: a WhatsApp version
   needs an approved summary template, which no business has yet.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.services.notify import notify_user

logger = logging.getLogger(__name__)

STOPPED_REPLYING_DAYS = 3
STOPPED_REPLYING_REASON = "Stopped replying"
CLOSING_HOUR_IST = 20  # 8 PM, the brief's evening summary time
IST = timezone(timedelta(hours=5, minutes=30))
_BATCH = 500


def mark_stopped_replying(db=None, now: datetime | None = None) -> int:
    """Mark every lead the rules pick, in batches. Returns how many were marked."""
    db = db or get_supabase()
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=STOPPED_REPLYING_DAYS)).isoformat()
    marked = 0
    for _ in range(20):  # at most 10,000 a run; the next run picks up the rest
        rows = db.rpc("stopped_replying_leads", {"p_cutoff": cutoff, "p_limit": _BATCH}).execute().data or []
        if not rows:
            break
        by_tenant: dict[str, list[str]] = {}
        for r in rows:
            by_tenant.setdefault(str(r["tenant_id"]), []).append(str(r["lead_id"]))
        for tenant_id, ids in by_tenant.items():
            # The same conditions again in the update, so a person who replied or was marked
            # meanwhile is left alone.
            res = (db.table("leads").update({
                "lost_at": now.isoformat(),
                "lost_reason": STOPPED_REPLYING_REASON,
                "lost_auto": True,
            }).eq("tenant_id", tenant_id).in_("id", ids)
                .is_("lost_at", "null").is_("booked_at", "null").is_("converted_at", "null").execute())
            marked += len(res.data or [])
        if len(rows) < _BATCH:
            break
    if marked:
        logger.info(f"inbound auto results: {marked} leads marked Lost · stopped replying")
    return marked


def _today_ist_bounds(now: datetime) -> tuple[str, str]:
    day = now.astimezone(IST).date()
    start = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


def remind_unmarked_bookings(db=None, now: datetime | None = None) -> int:
    """One bell per owner per business with today's bookings still unmarked. Returns how many sent."""
    db = db or get_supabase()
    now = now or datetime.now(timezone.utc)
    start, end = _today_ist_bounds(now)
    rows = (db.table("leads").select("id,tenant_id,name,phone,booked_for")
            .gte("booked_for", start).lt("booked_for", end)
            .is_("lost_at", "null").is_("converted_at", "null").is_("deleted_at", "null")
            .limit(5000).execute()).data or []
    # A won order means they came / paid.
    if rows:
        won = set()
        ids = [r["id"] for r in rows]
        for i in range(0, len(ids), 200):
            for d in (db.table("deals").select("lead_id").in_("lead_id", ids[i:i + 200]).eq("stage", "won")
                      .execute()).data or []:
                won.add(d["lead_id"])
        rows = [r for r in rows if r["id"] not in won]
    by_tenant: dict[str, list[dict]] = {}
    for r in rows:
        by_tenant.setdefault(str(r["tenant_id"]), []).append(r)

    sent = 0
    for tenant_id, leads in by_tenant.items():
        owners = (db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner")
                  .execute()).data or []
        names = [(l.get("name") or l.get("phone") or "Someone").strip() for l in leads]
        shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
        count = len(leads)
        title = f"{count} booking{'s' if count != 1 else ''} today not marked yet"
        message = f"{shown}. Mark each one Came / Paid or Lost in Inbound leads, so your numbers stay right."
        for o in owners:
            already = (db.table("app_notifications").select("id").eq("tenant_id", tenant_id)
                       .eq("user_id", o["user_id"]).eq("type", "unmarked_bookings")
                       .gte("created_at", start).limit(1).execute()).data
            if already:
                continue
            notify_user(tenant_id, o["user_id"], "unmarked_bookings", title, message, db=db,
                        push_url="/dashboard/inbound-leads")
            sent += 1
    return sent
