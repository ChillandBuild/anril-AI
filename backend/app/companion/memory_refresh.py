"""Same-day memory refresh for Level 2 characters (card engine; 'mem0' falls back to it).

The character reads only its last history_messages messages, and the card sweep runs at 02:00 IST.
So after each reply we check, in the background: has this person's unread chat (since the watermark)
reached history_messages - 2 (at least 2)? Then the sweep's per-pair step runs now in "day" mode, before
any message slides out of the window: the card learns the new facts AND "earlier today" is rewritten.
A message asking to forget something ("forget that", "marandhudu", "மறந்துவிடு") runs it at once.
A failed run sets day_retry_after (30 min); no same-day retry before it, except to forget.

Example: Karthik (history_messages 10) writes "Interview at Infosys 3 pm" at 09:00; 8 messages later
the refresh runs; at 17:00 "It went okay" still finds the interview in "Earlier today".

One run per (character, person) across every process (claim_memory_pair). Never blocks the reply.
No text is logged.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from app.companion import memory_sweep, store

logger = logging.getLogger(__name__)

DEFAULT_HISTORY = 10
MIN_TRIGGER = 2
# "forget" in English, Tanglish spellings and Tamil script (மறந்துவிடு / மறந்துடு / மறக்க). Not the bare
# root மற: மறுநாள் ("next day") and மறுபடியும் ("again") would run an extra AI call on every such message.
FORGET_WORDS = re.compile(r"\bforget|mara[nm]?[dt]h?[uo]|marakk?a|மறந்|மறக்க", re.IGNORECASE)
FORGET_WAITS = (20.0, 60.0, 120.0)   # a forget request that finds the pair busy tries again after these

_tasks: set[asyncio.Task] = set()  # strong refs, so a running refresh isn't garbage-collected


def wants_forget(message: str | None) -> bool:
    return bool(message and FORGET_WORDS.search(message))


def trigger_at(history: int | None) -> int:
    return max(MIN_TRIGGER, (history or DEFAULT_HISTORY) - 2)


def schedule(companion: dict, end_user_id: str, user_message: str | None = None) -> None:
    """Called after a reply is saved. Starts the background check."""
    if (companion.get("memory_level") or 1) != 2:
        return
    task = asyncio.get_running_loop().create_task(_refresh(companion, end_user_id, wants_forget(user_message)))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _refresh(companion: dict, end_user_id: str, force: bool = False) -> str:
    """force: the person asked to forget something. It skips the cool-down and, if another run holds the
    pair, waits and tries again (that run may have started before the request arrived)."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    threshold = 1 if force else trigger_at(companion.get("history_messages"))
    try:
        for wait in (0.0, *FORGET_WAITS) if force else (0.0,):
            if wait:
                await asyncio.sleep(wait)
            now = datetime.now(timezone.utc)
            state = await store.get_state(tenant_id, companion_id, end_user_id)
            retry = state.get("day_retry_after")
            if not force and retry and memory_sweep._ts(str(retry)) > now:
                return "cooling_down"
            unread = await store.messages_after(tenant_id, companion_id, end_user_id,
                                                state.get("last_message_at"), threshold)
            if len(unread) < threshold:
                return "not_needed"
            outcome = await memory_sweep.run_claimed(
                companion, end_user_id, memory_sweep.CLAIM_SECONDS,
                lambda n=now: _claimed_refresh(companion, end_user_id, threshold, n))
            if outcome != "busy":
                break
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
