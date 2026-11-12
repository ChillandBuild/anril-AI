"""Same-day memory refresh for Level 2 characters (card engine; 'mem0' falls back to it).

The character reads only its last history_messages messages, and the card sweep runs at 02:00 IST.
So after each reply we check, in the background: has this person's unread chat (since the watermark)
reached history_messages - 2 (at least 2)? Then the sweep's per-pair step runs now in "day" mode, before
any message slides out of the window: the card learns the new facts AND "earlier today" is rewritten.
A failed run sets day_retry_after (30 min); no same-day retry before it.
Nothing a person types starts a deletion: "forget that" is an ordinary message here (Prem, 2026-11-11).

Example: Karthik (history_messages 10) writes "Interview at Infosys 3 pm" at 09:00; 8 messages later
the refresh runs; at 17:00 "It went okay" still finds the interview in "Earlier today".

One run per (character, person) across every process (claim_memory_pair). Never blocks the reply.
No text is logged.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.companion import memory_sweep, store

logger = logging.getLogger(__name__)

DEFAULT_HISTORY = 10
MIN_TRIGGER = 2

_tasks: set[asyncio.Task] = set()  # strong refs, so a running refresh isn't garbage-collected


def trigger_at(history: int | None) -> int:
    return max(MIN_TRIGGER, (history or DEFAULT_HISTORY) - 2)


def schedule(companion: dict, end_user_id: str) -> None:
    """Called after a reply is saved. Starts the background check."""
    if (companion.get("memory_level") or 1) != 2:
        return
    task = asyncio.get_running_loop().create_task(_refresh(companion, end_user_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _refresh(companion: dict, end_user_id: str) -> str:
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    threshold = trigger_at(companion.get("history_messages"))
    try:
        now = datetime.now(timezone.utc)
        state = await store.get_state(tenant_id, companion_id, end_user_id)
        retry = state.get("day_retry_after")
        if retry and memory_sweep._ts(str(retry)) > now:
            return "cooling_down"
        unread = await store.messages_after(tenant_id, companion_id, end_user_id,
                                            state.get("last_message_at"), threshold)
        if len(unread) < threshold:
            return "not_needed"
        outcome = await memory_sweep.run_claimed(
            companion, end_user_id, memory_sweep.CLAIM_SECONDS,
            lambda: _claimed_refresh(companion, end_user_id, threshold, now))
        logger.info("companion %s: same-day memory refresh %s", companion_id, outcome)
        return outcome
    except Exception as exc:
        logger.warning("companion %s: same-day memory refresh error (%s)", companion_id, type(exc).__name__)
        return "failed"


async def _claimed_refresh(companion: dict, end_user_id: str, threshold: int, now: datetime) -> str:
    """Inside the claim: the state again (another run may have read these messages meanwhile)."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    mark = (await store.get_state(tenant_id, companion_id, end_user_id)).get("last_message_at")
    unread = await store.messages_after(tenant_id, companion_id, end_user_id, mark, threshold)
    if len(unread) < threshold:
        return "not_needed"
    return await memory_sweep._sweep_pair(companion, end_user_id, mark, 0, unread[-1]["created_at"], now,
                                          mode="day")
