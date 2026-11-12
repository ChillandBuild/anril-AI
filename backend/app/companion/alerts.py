"""Operator-bell alerts for companion memory (the `incidents` table, read by GET /operator/alerts and by
the owner's own incident list). One alert per business per kind per day, never one per person:
"Guru could not save memories" is about the AI provider or the key, which the platform team fixes.
The one exception is a failed owner delete (companion_memory_delete_incomplete): every one is saved.

Kinds:
  companion_memory_parked            the note-writer failed 3 nights running; chats are parked and retried
  companion_memory_parked_dead       a parked range is still unread after 30 tries; kept on record
  companion_memory_cleanup_gave_up   the cleanup after an owner delete failed 6 times (it keeps trying)
  companion_memory_delete_incomplete an owner delete could not clean the saved chat
  companion_memory_fact_ceiling      a person reached the fact ceiling; new facts are not saved
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.companion import store

logger = logging.getLogger(__name__)

EVERY = timedelta(hours=24)


async def alert(tenant_id: str, kind: str, message: str, *, dedupe: bool = True) -> None:
    """Never raises and never blocks a memory run on a failed insert.
    dedupe=False: every call is saved. Used for a failed owner delete, where each one is a different
    person whose words may still be in the chat (Priya's at 10:00 must not hide Divya's at 11:00)."""
    def _q():
        db = store.get_supabase()
        since = (datetime.now(timezone.utc) - EVERY).isoformat()
        recent = dedupe and (db.table("incidents").select("id").eq("tenant_id", tenant_id).eq("type", kind)
                             .gte("created_at", since).limit(1).execute().data)
        if recent:
            return
        db.table("incidents").insert({"tenant_id": tenant_id, "type": kind, "detail": {"message": message},
                                      "created_at": datetime.now(timezone.utc).isoformat()}).execute()
    try:
        await asyncio.to_thread(_q)
    except Exception as exc:
        logger.warning("companion alert %s could not be saved (%s)", kind, type(exc).__name__)
