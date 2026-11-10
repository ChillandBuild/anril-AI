"""The nightly memory sweep for the card engine, 02:00 IST.

During the day the character reads the recent messages (history_messages), so the card only has to
cover older days. Each night: every (character, person) pair with Level 2 memory and messages newer
than its watermark, oldest activity first, at most MAX_PAIRS. Messages go to the card in chunks of
CHUNK, one AI call each, at most MAX_CHUNKS per pair; the watermark moves after every good chunk.
A failed chunk stops the pair for tonight and counts a failed night in companion_memory_state; the
MAX_FAILED_NIGHTS-th in a row moves the watermark past it.
Then the diary pass: every pair that chatted on the last finished IST day gets one diary line
(from the day's recap plus the messages it doesn't cover) and its recap is cleared.
Fact, recap, diary and message text are never logged.
"""
import logging
from datetime import date, datetime, time, timedelta, timezone

from app.companion import memory_card, store

logger = logging.getLogger(__name__)

DIARY_MESSAGES = 80                 # a diary reads at most the day's last 80 messages (beyond the recap)
DIARY_MIN_USER_MESSAGES = 3         # a "hi" / "ok" day writes no diary line
DIARY_KEEP = timedelta(days=90)     # older diary lines are pruned

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
                      now: datetime, mode: str = "night") -> str:
    """mode "night": the 02:00 sweep. mode "day": the same-day refresh (memory_refresh.py), which also
    rewrites the pair's "earlier today" recap after each chunk; a failed day run counts no failed night."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    outcome: str | None = None
    recap: str | None = None
    if mode == "day":
        today = memory_card.ist_today(now).isoformat()
        current = await store.get_recap(tenant_id, companion_id, end_user_id)
        recap = current["text"] if current and current.get("day") == today else ""
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
            new_recap = None
            try:
                # Only the card engine is built; a character set to 'mem0' uses the card until it lands.
                if recap is None:
                    done = await memory_card.extract_and_apply(tenant_id, companion, end_user_id, messages)
                else:
                    done, new_recap = await memory_card.extract_day(tenant_id, companion, end_user_id,
                                                                    messages, recap)
            except Exception as exc:
                if mode == "day":
                    logger.warning("companion %s: same-day memory refresh failed for %s (%s)",
                                   companion_id, end_user_id, type(exc).__name__)
                    return "failed"  # the nightly sweep still reads these messages
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
            new_recap = None
            outcome = outcome or "skipped"  # nothing the person said, so nothing to learn
        await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
        if new_recap:
            recap = new_recap
            await store.set_recap(tenant_id, companion_id, end_user_id, new_recap,
                                  memory_card.ist_today(now).isoformat(), newest["created_at"])
        mark, failures = newest["created_at"], 0
        if len(messages) < CHUNK:
            break
    return outcome or "skipped"


def _ist_midnight_utc(day: date) -> str:
    return datetime.combine(day, time.min, tzinfo=memory_card.IST).astimezone(timezone.utc).isoformat()


async def _close_day(companion: dict, end_user_id: str, day: date) -> str:
    """Writes the diary line for one finished IST day of this pair and clears the day's recap.
    Input: the recap (when it is that day's) plus the day's messages it doesn't cover yet; with no
    recap, the day's messages, written only if the person sent at least DIARY_MIN_USER_MESSAGES."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    key = day.isoformat()
    recap = await store.get_recap(tenant_id, companion_id, end_user_id)
    day_recap = recap if recap and recap.get("day") == key else None
    if await store.has_diary(tenant_id, companion_id, end_user_id, key):
        outcome = "diary_skipped"
    else:
        start = (day_recap or {}).get("through") or _ist_midnight_utc(day)
        messages = await store.messages_between(tenant_id, companion_id, end_user_id, start,
                                                _ist_midnight_utc(day + timedelta(days=1)), DIARY_MESSAGES)
        users = sum(m["role"] == "user" for m in messages)
        if not day_recap and users < DIARY_MIN_USER_MESSAGES:
            outcome = "diary_skipped"
        else:
            line = await memory_card.write_diary(tenant_id, companion, end_user_id, day,
                                                 (day_recap or {}).get("text"), messages)
            newest_id = messages[-1].get("id") if messages else None
            if newest_id and not await store.message_exists(tenant_id, newest_id):
                return "forgotten"  # 'forget me' ran during the AI call
            if not newest_id and not await store.get_recap(tenant_id, companion_id, end_user_id):
                return "forgotten"  # recap-only day, and 'forget me' wiped the recap during the call
            if line:
                await store.upsert_diary(tenant_id, companion_id, end_user_id, key, line)
            outcome = "diary" if line else "diary_skipped"
    if recap and (recap.get("day") or "") <= key:
        await store.clear_recap(tenant_id, companion_id, end_user_id)  # its day is over
    await store.prune_diary(tenant_id, companion_id, end_user_id, (day - DIARY_KEEP).isoformat())
    return outcome


async def _diary_pass(now: datetime) -> dict[str, int]:
    """After the card sweep: every pair that chatted on the last finished IST day gets its diary line.
    Driven by conversations, not watermarks, so a day the same-day refresh already read is still closed."""
    day = memory_card.ist_today(now) - timedelta(days=1)
    since = _ist_midnight_utc(day)
    counts: dict[str, int] = {}
    for companion in await store.level2_companions():
        tenant_id, companion_id = companion["tenant_id"], companion["id"]
        seen: set[str] = set()
        for conv in await store.active_conversations(tenant_id, companion_id, since):
            end_user_id = conv["end_user_id"]
            if end_user_id in seen:
                continue
            seen.add(end_user_id)
            try:
                outcome = await _close_day(companion, end_user_id, day)
            except Exception as exc:  # one pair's failure must not stop the others; retried never
                logger.warning("companion %s: diary failed for %s (%s)", companion_id, end_user_id,
                               type(exc).__name__)
                outcome = "diary_failed"
            if outcome != "diary_skipped":
                counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def run_memory_sweep(now: datetime | None = None) -> dict[str, int]:
    """One night. Returns counts per pair outcome (ok, failed, gave_up, waiting, skipped, forgotten),
    plus diary / diary_failed for the diary pass (skipped diary days are not counted)."""
    now = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    for companion, end_user_id, mark, failures, last_at in await _due_pairs(now):
        try:
            outcome = await _sweep_pair(companion, end_user_id, mark, failures, last_at, now)
        except Exception as exc:  # a DB error on one pair must not stop the others
            logger.warning("companion %s: memory sweep error (%s)", companion["id"], type(exc).__name__)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    try:
        for outcome, n in (await _diary_pass(now)).items():
            counts[outcome] = counts.get(outcome, 0) + n
    except Exception as exc:
        logger.warning("companion memory sweep: diary pass error (%s)", type(exc).__name__)
    if counts:
        logger.info("companion memory sweep: %s", counts)
    return counts
