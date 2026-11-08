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
MAX_FAILURES = 6                    # retried after 1, 2, 4, 8, 16 min: gives up after ~half an hour
LOOKBACK = timedelta(days=7)        # a pair idle longer than this has nothing new to sweep
SETTLE = timedelta(minutes=2)       # a lone user message waits this long for the reply to land

# (companion_id, end_user_id) → (failures in a row, don't retry before). In-process: a restart
# just retries sooner.
_failures: dict[tuple[str, str], tuple[int, datetime]] = {}


def _ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _due_pairs(now: datetime) -> list[tuple[dict, str, str | None, str]]:
    """(character, end_user_id, watermark, last_message_at) for pairs with something new, oldest
    activity first across every character, at most MAX_PAIRS. Pairs backing off are left out."""
    since = (now - LOOKBACK).isoformat()
    due: list[tuple[dict, str, str | None, str]] = []
    for companion in await store.level2_companions():
        tenant_id, companion_id = companion["tenant_id"], companion["id"]
        marks = await store.memory_watermarks(tenant_id, companion_id)
        latest: dict[str, str] = {}
        for conv in await store.active_conversations(tenant_id, companion_id, since):
            latest[conv["end_user_id"]] = conv["last_message_at"]
        for end_user_id, last_at in latest.items():
            mark = marks.get(end_user_id)
            backoff = _failures.get((companion_id, end_user_id))
            if backoff and backoff[1] > now:
                continue
            if mark is None or _ts(last_at) > _ts(mark):
                due.append((companion, end_user_id, mark, last_at))
    due.sort(key=lambda d: _ts(d[3]))
    return due[:MAX_PAIRS]


async def _sweep_pair(companion: dict, end_user_id: str, mark: str | None, last_at: str,
                      now: datetime) -> str:
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    messages = await store.messages_after(tenant_id, companion_id, end_user_id, mark, MAX_MESSAGES)
    if not messages:
        # The conversation's clock (app server) is ahead of the messages' (database): move the
        # watermark up to it, or the pair stays "due" every tick and crowds out the others.
        await store.set_watermark(tenant_id, companion_id, end_user_id, last_at)
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
        done = await memory_card.extract_and_apply(tenant_id, companion, end_user_id, messages)
    except Exception as exc:
        tries = _failures.get(key, (0, now))[0] + 1
        _failures[key] = (tries, now + timedelta(minutes=2 ** (tries - 1)))
        if tries < MAX_FAILURES:
            logger.warning("companion %s: memory sweep failed for %s, try %d (%s)",
                           companion_id, end_user_id, tries, type(exc).__name__)
            return "failed"
        logger.warning("companion %s: memory sweep gave up on %d message(s) for %s after %d tries (%s)",
                       companion_id, len(messages), end_user_id, MAX_FAILURES, type(exc).__name__)
        _failures.pop(key, None)
        await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
        return "gave_up"
    _failures.pop(key, None)
    if done is None:
        return "forgotten"  # 'forget me' ran during the AI call: write nothing, not even a watermark
    await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
    return "ok"


async def run_memory_sweep(now: datetime | None = None) -> dict[str, int]:
    """One tick. Returns counts per outcome (ok, failed, gave_up, waiting, skipped, forgotten)."""
    now = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    for companion, end_user_id, mark, last_at in await _due_pairs(now):
        try:
            outcome = await _sweep_pair(companion, end_user_id, mark, last_at, now)
        except Exception as exc:  # a DB error on one pair must not stop the others
            logger.warning("companion %s: memory sweep error (%s)", companion["id"], type(exc).__name__)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    if counts:
        logger.info("companion memory sweep: %s", counts)
    return counts
