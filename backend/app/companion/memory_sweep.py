"""The nightly memory sweep for the card engine, 02:00 IST (spec §3.2).

During the day the character reads the recent messages (history_messages), so the card only has to
cover older days. Each night: every (character, person) pair with Level 2 memory and messages newer
than its watermark, oldest activity first, at most MAX_PAIRS. Messages go to the card in chunks of
CHUNK, one AI call each, at most MAX_CHUNKS per pair; the watermark moves after every good chunk.
A failed chunk stops the pair for tonight and counts a failed night in companion_memory_state; the
MAX_FAILED_NIGHTS-th in a row moves the watermark past it. Fact and message text are never logged.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.companion import memory_card, store

logger = logging.getLogger(__name__)

MAX_PAIRS = 500                     # the rest go first the next night (oldest activity first)
CHUNK = 40                          # messages per AI call
MAX_CHUNKS = 5                      # per pair per night: 200 messages
MAX_FAILED_NIGHTS = 3               # then the watermark moves on so one bad chat can't block the pair
LOOKBACK = timedelta(days=14)       # a pair idle longer than this has nothing new to sweep
SETTLE = timedelta(minutes=2)       # a lone user message waits this long for the reply to land


def _ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _due_pairs(now: datetime) -> list[tuple[dict, str, str | None, int, str]]:
    """(character, end_user_id, watermark, failed nights, last_message_at) for pairs with something
    new, oldest activity first across every character, at most MAX_PAIRS."""
    since = (now - LOOKBACK).isoformat()
    due: list[tuple[dict, str, str | None, int, str]] = []
    for companion in await store.level2_companions():
        tenant_id, companion_id = companion["tenant_id"], companion["id"]
        states = await store.memory_states(tenant_id, companion_id)
        latest: dict[str, str] = {}
        for conv in await store.active_conversations(tenant_id, companion_id, since):
            latest[conv["end_user_id"]] = conv["last_message_at"]
        for end_user_id, last_at in latest.items():
            mark, failures = states.get(end_user_id, (None, 0))
            if mark is None or _ts(last_at) > _ts(mark):
                due.append((companion, end_user_id, mark, failures, last_at))
    due.sort(key=lambda d: _ts(d[4]))
    return due[:MAX_PAIRS]


async def _sweep_pair(companion: dict, end_user_id: str, mark: str | None, failures: int, last_at: str,
                      now: datetime) -> str:
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    outcome: str | None = None
    for _ in range(MAX_CHUNKS):
        messages = await store.messages_after(tenant_id, companion_id, end_user_id, mark, CHUNK)
        if not messages:
            if outcome is None:
                # The conversation's clock (app server) is ahead of the messages' (database): move
                # the watermark up to it, or the pair stays "due" every night.
                await store.set_watermark(tenant_id, companion_id, end_user_id, last_at)
                return "skipped"
            break
        newest = messages[-1]
        if newest["role"] == "user" and now - _ts(newest["created_at"]) < SETTLE and len(messages) < CHUNK:
            return outcome or "waiting"  # the reply is probably still being written; next night
        if any(m["role"] == "user" for m in messages):
            try:
                # Only the card engine is built; a character set to 'mem0' uses the card until it lands.
                done = await memory_card.extract_and_apply(tenant_id, companion, end_user_id, messages)
            except Exception as exc:
                failures += 1
                if failures < MAX_FAILED_NIGHTS:
                    logger.warning("companion %s: memory sweep failed for %s, night %d (%s)",
                                   companion_id, end_user_id, failures, type(exc).__name__)
                    await store.record_failure(tenant_id, companion_id, end_user_id, failures)
                    return "failed"
                logger.warning("companion %s: memory sweep gave up on %d message(s) for %s after %d nights (%s)",
                               companion_id, len(messages), end_user_id, failures, type(exc).__name__)
                await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
                return "gave_up"
            if done is None:
                return "forgotten"  # 'forget me' ran during the AI call: write nothing, not even a watermark
            outcome = "ok"
        else:
            outcome = outcome or "skipped"  # nothing the person said, so nothing to learn
        await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
        mark, failures = newest["created_at"], 0
        if len(messages) < CHUNK:
            break
    return outcome or "skipped"


async def run_memory_sweep(now: datetime | None = None) -> dict[str, int]:
    """One night. Returns counts per pair outcome (ok, failed, gave_up, waiting, skipped, forgotten)."""
    now = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    for companion, end_user_id, mark, failures, last_at in await _due_pairs(now):
        try:
            outcome = await _sweep_pair(companion, end_user_id, mark, failures, last_at, now)
        except Exception as exc:  # a DB error on one pair must not stop the others
            logger.warning("companion %s: memory sweep error (%s)", companion["id"], type(exc).__name__)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    if counts:
        logger.info("companion memory sweep: %s", counts)
    return counts
