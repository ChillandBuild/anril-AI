"""Daily tidy-up of the Chats Inbox (queue task auto-archive-idle, migration 274).

Chats with no message in or out for 30 days move to Archived by themselves, marked
archived_reason='idle_30d'. A chat that needs a person, is pinned, or is blocked is never
touched. The customer writing again brings it straight back (a trigger on messages)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

IDLE_DAYS = 30


def _archive_idle(days: int) -> int:
    return int(get_supabase().rpc("auto_archive_idle_chats", {"p_days": days}).execute().data or 0)


DELIVERED_REASON = "order_delivered"
RECENT_INBOUND_MINUTES = 60
_OPEN_DELIVERY = ("working", "ready", "shipped")


def archive_after_delivery(db, tenant_id: str, lead_id: str | None, deal_id: str) -> bool:
    """Chats > Archived: an order marked Delivered moves its chat to Archived (archived_reason='order_delivered').

    Left alone when the chat is blocked, pinned, needs a person or is already archived; when the customer
    wrote in the last hour; or when they have another order still open (quoted, waiting for payment, or
    paid and not yet delivered). The customer writing again brings it back (trigger from migration 274).
    Never raises: the delivery has already been saved."""
    if not lead_id:
        return False
    try:
        lead = (
            db.table("leads")
            .select("id, archived_at, blocked_at, pinned_at, needs_human_attention, needs_human_intervention, last_inbound_at, deleted_at")
            .eq("id", lead_id).eq("tenant_id", tenant_id).maybe_single().execute()
        )
        row = (lead.data if lead else None) or {}
        if not row or row.get("deleted_at") or row.get("archived_at") or row.get("blocked_at") or row.get("pinned_at"):
            return False
        if row.get("needs_human_attention") or row.get("needs_human_intervention"):
            return False
        last_in = row.get("last_inbound_at")
        if last_in:
            when = datetime.fromisoformat(str(last_in).replace("Z", "+00:00"))
            if when > datetime.now(timezone.utc) - timedelta(minutes=RECENT_INBOUND_MINUTES):
                return False
        others = (
            db.table("deals").select("id, stage, delivery_status")
            .eq("tenant_id", tenant_id).eq("lead_id", lead_id).neq("id", deal_id).neq("stage", "lost")
            .limit(50).execute()
        ).data or []
        for d in others:
            if d.get("stage") in ("quoted", "awaiting_payment"):
                return False
            if d.get("stage") == "won" and d.get("delivery_status") in _OPEN_DELIVERY:
                return False
        db.table("leads").update(
            {"archived_at": datetime.now(timezone.utc).isoformat(), "archived_by_name": None, "archived_reason": DELIVERED_REASON}
        ).eq("id", lead_id).eq("tenant_id", tenant_id).is_("archived_at", "null").execute()
        return True
    except Exception:
        logger.exception("auto-archive after delivery failed for lead %s", lead_id)
        return False


async def archive_idle_chats(days: int = IDLE_DAYS) -> int:
    """One set-based update for every tenant. Run in a thread: a sync Supabase call on the
    event loop freezes every request while it runs."""
    archived = await asyncio.to_thread(_archive_idle, days)
    logger.info(f"auto-archive: {archived} chat(s) idle for {days}+ days moved to Archived")
    return archived
