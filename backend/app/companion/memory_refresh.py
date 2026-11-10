"""Same-day memory refresh for Level 2 characters (card engine; 'mem0' falls back to it).

The character reads only its last history_messages messages, and the nightly sweep runs at 02:00
IST. So after each reply we check, in the background: has this person sent more messages than
history_messages since the watermark? If yes, the sweep's per-pair step runs now in "day" mode:
the card learns the new facts AND the pair's "earlier today" recap is rewritten.

Example: Karthik (history_messages 10) writes "Interview at Infosys 3 pm" at 09:00 and 11 messages
later the refresh runs; at 17:00 "It went okay" still finds the interview in "Earlier today".

At most one refresh per (character, person) at a time in this process. Never blocks the reply.
No text is logged.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.companion import memory_sweep, store

logger = logging.getLogger(__name__)

DEFAULT_HISTORY = 10

_running: set[tuple[str, str]] = set()
_tasks: set[asyncio.Task] = set()  # strong refs, so a running refresh isn't garbage-collected


def schedule(companion: dict, end_user_id: str) -> None:
    """Called after a reply is saved. Starts the background check unless one runs for this pair."""
    if (companion.get("memory_level") or 1) != 2:
        return
    key = (companion["id"], end_user_id)
    if key in _running:
        return
    _running.add(key)
    task = asyncio.get_running_loop().create_task(_refresh(companion, end_user_id))
    _tasks.add(task)
    task.add_done_callback(lambda t: (_tasks.discard(t), _running.discard(key)))


async def _refresh(companion: dict, end_user_id: str) -> str:
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    try:
        limit = companion.get("history_messages") or DEFAULT_HISTORY
        mark = await store.get_watermark(tenant_id, companion_id, end_user_id)
        unread = await store.messages_after(tenant_id, companion_id, end_user_id, mark, limit + 1)
        if len(unread) <= limit:
            return "not_needed"
        outcome = await memory_sweep._sweep_pair(companion, end_user_id, mark, 0, unread[-1]["created_at"],
                                                 datetime.now(timezone.utc), mode="day")
        logger.info("companion %s: same-day memory refresh %s", companion_id, outcome)
        return outcome
    except Exception as exc:
        logger.warning("companion %s: same-day memory refresh error (%s)", companion_id, type(exc).__name__)
        return "failed"
