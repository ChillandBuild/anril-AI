"""The every-minute memory sweep ("after every reply", spec §3.2).

Each tick: find up to 20 (character, person) pairs with Level 2 memory and messages newer than
their watermark, send at most 20 of those messages to the character's engine in one AI call, and
move the watermark on success. Replies never wait for this. Fact and message text are never logged.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.companion import memory_card, store

logger = logging.getLogger(__name__)

MAX_PAIRS = 20
MAX_MESSAGES = 20
MAX_FAILURES = 3
LOOKBACK = timedelta(days=7)        # a pair idle longer than this has nothing new to sweep
SETTLE = timedelta(minutes=2)       # a lone user message waits this long for the reply to land

_failures: dict[tuple[str, str], int] = {}  # (companion_id, end_user_id) → failures in a row


def _ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _due_pairs(now: datetime) -> list[tuple[dict, str, str | None]]:
    """(character, end_user_id, watermark) for pairs with something new, oldest activity first."""
    since = (now - LOOKBACK).isoformat()
    due: list[tuple[dict, str, str | None]] = []
    for companion in await store.level2_companions():
        tenant_id, companion_id = companion["tenant_id"], companion["id"]
        marks = await store.memory_watermarks(tenant_id, companion_id)
        latest: dict[str, str] = {}
        for conv in await store.active_conversations(tenant_id, companion_id, since):
            latest[conv["end_user_id"]] = conv["last_message_at"]
        for end_user_id, last_at in latest.items():
            mark = marks.get(end_user_id)
            if mark is None or _ts(last_at) > _ts(mark):
                due.append((companion, end_user_id, mark))
            if len(due) >= MAX_PAIRS:
                return due
    return due


async def _sweep_pair(companion: dict, end_user_id: str, mark: str | None, now: datetime) -> str:
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    messages = await store.messages_after(tenant_id, companion_id, end_user_id, mark, MAX_MESSAGES)
    if not messages:
        return "skipped"
    newest = messages[-1]
    if newest["role"] == "user" and now - _ts(newest["created_at"]) < SETTLE and len(messages) < MAX_MESSAGES:
        return "waiting"  # the reply is probably still being written; take both next tick
    if not any(m["role"] == "user" for m in messages):
        await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
        return "skipped"  # nothing the person said, so nothing to learn

    key = (companion_id, end_user_id)
    try:
        # Only the card engine is built; a character set to 'mem0' uses the card until it lands.
        await memory_card.extract_and_apply(tenant_id, companion, end_user_id, messages)
    except Exception as exc:
        _failures[key] = _failures.get(key, 0) + 1
        if _failures[key] < MAX_FAILURES:
            logger.warning("companion %s: memory sweep failed for %s, try %d (%s)",
                           companion_id, end_user_id, _failures[key], type(exc).__name__)
            return "failed"
        logger.warning("companion %s: memory sweep gave up on %d message(s) for %s after %d tries (%s)",
                       companion_id, len(messages), end_user_id, MAX_FAILURES, type(exc).__name__)
        _failures.pop(key, None)
        await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
        return "gave_up"
    _failures.pop(key, None)
    await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
    return "ok"


async def run_memory_sweep(now: datetime | None = None) -> dict[str, int]:
    """One tick. Returns counts per outcome (ok, failed, gave_up, waiting, skipped)."""
    now = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    for companion, end_user_id, mark in await _due_pairs(now):
        try:
            outcome = await _sweep_pair(companion, end_user_id, mark, now)
        except Exception as exc:  # a DB error on one pair must not stop the others
            logger.warning("companion %s: memory sweep error (%s)", companion["id"], type(exc).__name__)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    if counts:
        logger.info("companion memory sweep: %s", counts)
    return counts
