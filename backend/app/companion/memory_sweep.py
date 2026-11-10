"""Card-engine memory runs: the nightly card sweep (02:00 IST), the hourly diary job, the search backfill.

Night sweep: every (character, person) pair with Level 2 memory and messages newer than its watermark,
oldest activity first, at most MAX_PAIRS. Messages go to the card in chunks of CHUNK, one AI call each,
at most MAX_CHUNKS per pair; the watermark moves after every good chunk. A failed chunk stops the pair
and counts a failed night; the MAX_FAILED_NIGHTS-th in a row moves the watermark past it.
Every chunk read is also indexed for long-term search (memory_search), and a "forget" answer runs the
forget-that cleanup (memory_forget).
Same-day mode ("day", memory_refresh.py): the same step, plus the "earlier today" recap. Messages from
before the person's local midnight go to the card only, never into today's recap.
Diary job (hourly): closes every finished local day of each pair active in the last DIARY_CATCHUP days,
reading ALL that day's messages (in parts of DIARY_MESSAGES). A failure is retried next hour; a day that
still fails after DIARY_CATCHUP days is skipped so it can't block later days.
Every run claims the pair first (claim_memory_pair), so two processes never work on one pair.
Fact, recap, diary and message text are never logged.
"""
import asyncio
import logging
import time as clock
from datetime import date, datetime, timedelta, timezone

from app.companion import memory_card, memory_search, store

logger = logging.getLogger(__name__)

DIARY_MESSAGES = 80                 # messages per diary part (one AI call each)
DIARY_MAX_PARTS = 15                # 1,200 messages: a longer day keeps its last 1,200
DIARY_MIN_USER_MESSAGES = 3         # a "hi" / "ok" day writes no diary line
DIARY_KEEP = timedelta(days=90)     # older diary lines are pruned (their search pieces stay)
DIARY_CATCHUP = 3                   # days looked back each hour; a day failing this long is skipped
DIARY_CONCURRENCY = 8
JOB_BUDGET = 50 * 60                # seconds; leftovers go next hour
EMBED_FILL_PER_TENANT = 50          # search pieces without a vector re-embedded per business per hour

MAX_PAIRS = 500                     # the rest go first the next night (oldest activity first)
CHUNK = 40                          # messages per AI call
MAX_CHUNKS = 5                      # per pair per night: 200 messages
MAX_FAILED_NIGHTS = 3               # then the watermark moves on so one bad chat can't block the pair
LOOKBACK = timedelta(days=14)       # a pair idle longer than this has nothing new to sweep
SETTLE = timedelta(minutes=2)       # a lone user message waits this long for the reply to land
CLAIM_SECONDS = 900                 # a crashed run frees its pair after this
DAY_RETRY = timedelta(minutes=30)   # a failed same-day refresh waits this long


def _ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def zone_of(companion: dict, end_user_id: str):
    return memory_card.zone_for(companion, await store.person_timezone(companion["tenant_id"], end_user_id))


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


async def _after_extract(companion: dict, end_user_id: str, messages: list[dict], result, zone,
                         today: date) -> None:
    """Search indexing and forget-that for one good chunk. Failures here never fail the run:
    the card is already written, and the hourly job re-embeds pieces stored without a vector."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    try:
        await memory_search.index_messages(tenant_id, companion_id, end_user_id, messages, zone)
        await memory_search.index_facts(tenant_id, companion_id, end_user_id, result.closed, today)
        await memory_search.drop_facts(tenant_id, end_user_id, result.deleted)
    except Exception as exc:
        logger.warning("companion %s: search indexing failed for %s (%s)", companion_id, end_user_id,
                       type(exc).__name__)
    if result.forget:
        from app.companion import memory_forget
        try:
            await memory_forget.forget_or_queue(tenant_id, companion_id, end_user_id, result.forget, today)
        except Exception as exc:  # a DB error; forget_or_queue itself queues AI failures
            logger.warning("companion %s: forget-that cleanup failed for %s (%s)", companion_id, end_user_id,
                           type(exc).__name__)


async def _sweep_pair(companion: dict, end_user_id: str, mark: str | None, failures: int, last_at: str,
                      now: datetime, mode: str = "night", zone=None) -> str:
    """mode "night": the 02:00 IST sweep. mode "day": the same-day refresh; a failed day run counts no
    failed night and sets day_retry_after. Both modes feed messages from the person's own today into the
    "earlier today" recap: 02:00 IST is mid-afternoon in Toronto, and those messages must not skip it."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    zone = zone or await zone_of(companion, end_user_id)
    today = memory_card.local_today(now, zone)
    midnight = memory_card.local_midnight_utc(today, zone)
    outcome: str | None = None
    recap: str | None = None
    current = await store.get_recap(tenant_id, companion_id, end_user_id)
    recap = current["text"] if current and current.get("day") == today.isoformat() else ""
    for _ in range(MAX_CHUNKS):
        messages = await store.messages_after(tenant_id, companion_id, end_user_id, mark, CHUNK)
        if not messages:
            if outcome is None:
                # The conversation's clock (app server) is ahead of the messages' (database): move
                # the watermark up to it, or the pair stays "due" every night.
                await store.set_watermark(tenant_id, companion_id, end_user_id, last_at)
                return "skipped"
            break
        full = len(messages) == CHUNK
        day_chunk = _ts(messages[0]["created_at"]) >= _ts(midnight)
        if not day_chunk and _ts(messages[-1]["created_at"]) >= _ts(midnight):
            # Yesterday's tail: card only, and it never reaches today's recap.
            messages = [m for m in messages if _ts(m["created_at"]) < _ts(midnight)]
            full = True  # today's messages follow in the next chunk
        newest = messages[-1]
        if newest["role"] == "user" and now - _ts(newest["created_at"]) < SETTLE and not full:
            return outcome or "waiting"  # the reply is probably still being written
        new_recap = None
        if any(m["role"] == "user" for m in messages):
            try:
                result = await memory_card.extract(tenant_id, companion, end_user_id, messages,
                                                   recap if day_chunk else None, today=today)
            except Exception as exc:
                if mode == "day":
                    logger.warning("companion %s: same-day memory refresh failed for %s (%s)",
                                   companion_id, end_user_id, type(exc).__name__)
                    await store.update_state(tenant_id, companion_id, end_user_id,
                                             {"day_retry_after": (now + DAY_RETRY).isoformat()})
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
            if result.done is None:
                return "forgotten"  # 'forget me' ran during the AI call: write nothing, not even a watermark
            new_recap = result.recap
            await _after_extract(companion, end_user_id, messages, result, zone, today)
            outcome = "ok"
        else:
            outcome = outcome or "skipped"  # nothing the person said, so nothing to learn
        await store.set_watermark(tenant_id, companion_id, end_user_id, newest["created_at"])
        if new_recap:
            recap = new_recap
            await store.set_recap(tenant_id, companion_id, end_user_id, new_recap, today.isoformat(),
                                  newest["created_at"])
        mark, failures = newest["created_at"], 0
        if not full:
            break
    return outcome or "skipped"


async def run_claimed(companion: dict, end_user_id: str, seconds: int, work) -> str:
    """Runs `work()` only while this process holds the pair; "busy" when another run has it."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    if not await store.claim_pair(tenant_id, companion_id, end_user_id, seconds):
        return "busy"
    try:
        return await work()
    finally:
        try:
            await store.release_pair(tenant_id, companion_id, end_user_id)
        except Exception as exc:  # the claim runs out by itself
            logger.warning("companion %s: memory claim not released (%s)", companion_id, type(exc).__name__)


async def _sweep_fresh(companion: dict, end_user_id: str, last_at: str, now: datetime) -> str:
    """The night run for one pair, from its state as it is now that we hold it (a same-day refresh
    may have moved the watermark since the list of due pairs was read)."""
    state = await store.get_state(companion["tenant_id"], companion["id"], end_user_id)
    mark = state.get("last_message_at")
    if mark and _ts(mark) >= _ts(last_at):
        return "skipped"
    return await _sweep_pair(companion, end_user_id, mark, state.get("failures") or 0, last_at, now)


async def run_memory_sweep(now: datetime | None = None) -> dict[str, int]:
    """One night of card sweeping. Returns counts per pair outcome
    (ok, failed, gave_up, waiting, skipped, forgotten, busy). Diary lines are the hourly job's."""
    now = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    for companion, end_user_id, _mark, _failures, last_at in await _due_pairs(now):
        try:
            outcome = await run_claimed(
                companion, end_user_id, CLAIM_SECONDS,
                lambda c=companion, e=end_user_id, la=last_at: _sweep_fresh(c, e, la, now))
        except Exception as exc:  # a DB error on one pair must not stop the others
            logger.warning("companion %s: memory sweep error (%s)", companion["id"], type(exc).__name__)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    if counts:
        logger.info("companion memory sweep: %s", counts)
    return counts


# --- the hourly diary job ---------------------------------------------------------------------

async def _day_messages(tenant_id: str, companion_id: str, end_user_id: str, day: date, zone) -> list[dict]:
    """Every message of the person's local `day` (oldest first; at most the last parts' worth)."""
    start = memory_card.local_midnight_utc(day, zone)
    end = memory_card.local_midnight_utc(day + timedelta(days=1), zone)
    out: list[dict] = []
    while True:
        page = await store.messages_page(tenant_id, companion_id, end_user_id, start, end, DIARY_MESSAGES)
        out.extend(page)
        if len(page) < DIARY_MESSAGES:
            break
        start = page[-1]["created_at"]
    return out[-DIARY_MESSAGES * DIARY_MAX_PARTS:]


async def _close_day(companion: dict, end_user_id: str, day: date, zone) -> str:
    """Writes the diary line for one finished local day of this pair: all the day's messages, in parts
    of DIARY_MESSAGES (one note each, then one call joins the notes). Skipped when a line exists or the
    person sent fewer than DIARY_MIN_USER_MESSAGES. Raises MemoryExtractionError when an AI call fails."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    key = day.isoformat()
    if await store.has_diary(tenant_id, companion_id, end_user_id, key):
        return "diary_skipped"
    messages = await _day_messages(tenant_id, companion_id, end_user_id, day, zone)
    if sum(m["role"] == "user" for m in messages) < DIARY_MIN_USER_MESSAGES:
        return "diary_skipped"
    parts = [messages[i:i + DIARY_MESSAGES] for i in range(0, len(messages), DIARY_MESSAGES)]
    if len(parts) == 1:
        line = await memory_card.write_diary(tenant_id, companion, day, messages=messages)
    else:
        notes = []
        for i, part in enumerate(parts, 1):
            note = await memory_card.write_diary(tenant_id, companion, day, messages=part,
                                                 part=f"part {i} of {len(parts)}")
            if note:
                notes.append(note)
        line = await memory_card.write_diary(tenant_id, companion, day, notes=notes) if notes else None
    if not await store.message_exists(tenant_id, messages[-1]["id"]):
        return "forgotten"  # 'forget me' ran during the AI calls
    if not line:
        return "diary_skipped"
    await store.upsert_diary(tenant_id, companion_id, end_user_id, key, line)
    try:
        await memory_search.index_diary(tenant_id, companion_id, end_user_id, key, line)
    except Exception as exc:
        logger.warning("companion %s: diary search indexing failed (%s)", companion_id, type(exc).__name__)
    return "diary"


async def _diary_pair(companion: dict, end_user_id: str, now: datetime) -> list[str]:
    """Closes this pair's finished days after diary_through, oldest first. One outcome per day tried."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    zone = await zone_of(companion, end_user_id)
    today = memory_card.local_today(now, zone)
    state = await store.get_state(tenant_id, companion_id, end_user_id)
    through = state.get("diary_through")
    day = today - timedelta(days=DIARY_CATCHUP)
    if through:
        day = max(day, date.fromisoformat(str(through)[:10]) + timedelta(days=1))
    outcomes: list[str] = []
    while day < today:
        try:
            outcome = await _close_day(companion, end_user_id, day, zone)
        except Exception as exc:
            if (today - day).days < DIARY_CATCHUP:
                logger.warning("companion %s: diary failed for %s, retried next hour (%s)", companion_id,
                               end_user_id, type(exc).__name__)
                outcomes.append("diary_failed")
                break
            logger.warning("companion %s: diary gave up on a day for %s (%s)", companion_id, end_user_id,
                           type(exc).__name__)
            outcome = "diary_gave_up"
        if outcome == "forgotten":
            outcomes.append(outcome)
            return outcomes
        await store.update_state(tenant_id, companion_id, end_user_id, {"diary_through": day.isoformat()})
        outcomes.append(outcome)
        day += timedelta(days=1)
    recap = await store.get_recap(tenant_id, companion_id, end_user_id)
    if recap and (recap.get("day") or "") < today.isoformat():
        await store.clear_recap(tenant_id, companion_id, end_user_id)  # its day is over
    await store.prune_diary(tenant_id, companion_id, end_user_id, (today - DIARY_KEEP).isoformat())
    return outcomes


async def _fill_embeddings() -> int:
    """Search pieces stored without a vector (the embedding call failed) get one now."""
    from app.companion import memory_embed

    # Per tenant, so a business whose key is broken (its rows never fill) can't hold every slot.
    filled = 0
    for tenant_id in dict.fromkeys(c["tenant_id"] for c in await store.level2_companions()):
        group = await store.chunks_missing_embedding(tenant_id, EMBED_FILL_PER_TENANT)
        if not group:
            continue
        vectors = await memory_embed.embed([r["text"] for r in group], "document", tenant_id)
        for r, v in zip(group, vectors):
            if v:
                await store.set_chunk_embedding(tenant_id, r["id"], v)
                filled += 1
    return filled


async def run_diary_job(now: datetime | None = None, budget_seconds: float = JOB_BUDGET) -> dict[str, int]:
    """Hourly: diary lines for every pair active in the last DIARY_CATCHUP days, DIARY_CONCURRENCY at a
    time, stopping new pairs after budget_seconds. Returns counts per day outcome."""
    now = now or datetime.now(timezone.utc)
    started = clock.monotonic()
    since = (now - timedelta(days=DIARY_CATCHUP + 1)).isoformat()
    pairs: list[tuple[dict, str]] = []
    for companion in await store.level2_companions():
        seen: set[str] = set()
        for conv in await store.active_conversations(companion["tenant_id"], companion["id"], since):
            if conv["end_user_id"] not in seen:
                seen.add(conv["end_user_id"])
                pairs.append((companion, conv["end_user_id"]))
    counts: dict[str, int] = {}
    slots = asyncio.Semaphore(DIARY_CONCURRENCY)

    async def one(companion: dict, end_user_id: str) -> None:
        async with slots:
            if clock.monotonic() - started > budget_seconds:
                counts["deferred"] = counts.get("deferred", 0) + 1
                return
            try:
                result = await run_claimed(companion, end_user_id, CLAIM_SECONDS * 2,
                                           lambda: _diary_pair(companion, end_user_id, now))
                outcomes = [result] if isinstance(result, str) else result
            except Exception as exc:  # one pair's failure must not stop the others
                logger.warning("companion %s: diary error (%s)", companion["id"], type(exc).__name__)
                outcomes = ["diary_failed"]
            for outcome in outcomes:
                if outcome != "diary_skipped":
                    counts[outcome] = counts.get(outcome, 0) + 1

    await asyncio.gather(*(one(c, e) for c, e in pairs))
    try:
        filled = await _fill_embeddings()
        if filled:
            counts["embedded"] = filled
    except Exception as exc:
        logger.warning("companion memory: embedding fill failed (%s)", type(exc).__name__)
    try:
        from app.companion import memory_forget
        retried = await memory_forget.run_pending()
        if retried.get("done"):
            counts["forgets_retried"] = retried["done"]
    except Exception as exc:
        logger.warning("companion memory: forget-that retries failed (%s)", type(exc).__name__)
    if counts:
        logger.info("companion diary job: %s", counts)
    return counts


# --- one-time search backfill -----------------------------------------------------------------

BACKFILL_PAGE = 48


async def _backfill_pair(companion: dict, end_user_id: str, mark: str | None) -> int:
    """Indexes this pair's history up to its watermark (newer messages are the sweep's)."""
    tenant_id, companion_id = companion["tenant_id"], companion["id"]
    zone = await zone_of(companion, end_user_id)
    # messages_page's end is exclusive: one microsecond past the watermark keeps the watermark's own message.
    end = (_ts(mark) + timedelta(microseconds=1)).isoformat() if mark else datetime.now(timezone.utc).isoformat()
    start, total = "1970-01-01T00:00:00+00:00", 0
    while True:
        page = await store.messages_page(tenant_id, companion_id, end_user_id, start, end, BACKFILL_PAGE)
        if not page:
            break
        total += await memory_search.index_messages(tenant_id, companion_id, end_user_id, page, zone)
        start = page[-1]["created_at"]
        if len(page) < BACKFILL_PAGE:
            break
    for row in await store.diary_since(tenant_id, companion_id, end_user_id, "1970-01-01"):
        await memory_search.index_diary(tenant_id, companion_id, end_user_id, str(row["day"])[:10], row["text"])
    closed = [f for f in await store.list_facts(tenant_id, end_user_id, companion_id) if f.get("status") == "closed"]
    await memory_search.index_facts(tenant_id, companion_id, end_user_id, closed,
                                    memory_card.local_today(None, zone))
    await store.update_state(tenant_id, companion_id, end_user_id,
                             {"search_backfilled_at": datetime.now(timezone.utc).isoformat()})
    return total


async def _backfill_claimed(companion: dict, end_user_id: str):
    """Inside the claim, so it can't race a run (or a forget-that) on the same pair."""
    state = await store.get_state(companion["tenant_id"], companion["id"], end_user_id)
    if state.get("search_backfilled_at"):
        return 0
    return await _backfill_pair(companion, end_user_id, state.get("last_message_at"))


async def run_search_backfill(budget_seconds: float = JOB_BUDGET) -> dict[str, int]:
    """One-time: every Level 2 pair not yet backfilled, newest activity first. Re-run until "left" is 0."""
    started = clock.monotonic()
    counts = {"pairs": 0, "windows": 0, "left": 0, "failed": 0}
    todo: list[tuple[str, dict, str, str | None]] = []
    for companion in await store.level2_companions():
        for row in await store.memory_states_full(companion["tenant_id"], companion["id"]):
            if not row.get("search_backfilled_at"):
                todo.append((str(row.get("updated_at") or ""), companion, row["end_user_id"],
                             row.get("last_message_at")))
    todo.sort(key=lambda t: t[0], reverse=True)
    for _, companion, end_user_id, _mark in todo:
        if clock.monotonic() - started > budget_seconds:
            counts["left"] += 1
            continue
        try:
            done = await run_claimed(companion, end_user_id, CLAIM_SECONDS,
                                     lambda c=companion, e=end_user_id: _backfill_claimed(c, e))
            if done == "busy":
                counts["left"] += 1
                continue
            counts["windows"] += done
            counts["pairs"] += 1
        except Exception as exc:
            logger.warning("companion %s: search backfill failed (%s)", companion["id"], type(exc).__name__)
            counts["failed"] += 1
    logger.info("companion search backfill: %s", counts)
    return counts
