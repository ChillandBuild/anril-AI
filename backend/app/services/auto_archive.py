"""Daily tidy-up of the Chats Inbox (queue task auto-archive-idle, migration 274).

Chats with no message in or out for 30 days move to Archived by themselves, marked
archived_reason='idle_30d'. A chat that needs a person, is pinned, or is blocked is never
touched. The customer writing again brings it straight back (a trigger on messages)."""
import asyncio
import logging

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

IDLE_DAYS = 30


def _archive_idle(days: int) -> int:
    return int(get_supabase().rpc("auto_archive_idle_chats", {"p_days": days}).execute().data or 0)


async def archive_idle_chats(days: int = IDLE_DAYS) -> int:
    """One set-based update for every tenant. Run in a thread: a sync Supabase call on the
    event loop freezes every request while it runs."""
    archived = await asyncio.to_thread(_archive_idle, days)
    logger.info(f"auto-archive: {archived} chat(s) idle for {days}+ days moved to Archived")
    return archived
