"""T27 learning rules: what the base learns from real questions. Pure functions, no I/O.

Two things are learned from the question log (topic and passage ids only, never a person or an answer):
1. A shortcut: 3 similar book questions that all scored the same passage 3 -> next time, look at that
   passage first and skip the full search. The judge still checks it, so a wrong shortcut costs one lookup.
2. A gap: a topic asked 5+ times in 30 days that no document answered (basis "own") -> shown to the owner.

Worked example. Karthik, Meena and Arun ask about Sade Sati in other words. Each log row lists
best=[{"document_id": "book3", "page_from": 88, "page_to": 88, "score": 3}]. group_questions puts them in one
group (cosine 0.88 or more), shortcut_for_group returns a shortcut to book3 p. 88. Tomorrow's question lands
near it: nearest_shortcut finds it, the judge scores the page, after_use records the hit or miss.

Rows are plain dicts already parsed by the store. The database-facing functions live lower in this file.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from math import sqrt

from app.companion import memory_embed
from app.companion.kb import store_search
from app.companion.kb.types import KbResult

logger = logging.getLogger(__name__)

GROUP_SIMILARITY = 0.88
SHORTCUT_MIN_QUESTIONS = 3
SHORTCUT_SCORE = 3
MAX_SHORTCUT_RANGES = 3
GAP_MIN_ASKS = 5
GAP_WINDOW_DAYS = 30
RETIRE_MISSES = 3
LOG_KEEP_DAYS = 90

_DOC_BASES = ("primary", "book")


# ---- small helpers ----

def cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Cosine similarity, 0.0 when either vector is empty, the lengths differ or a vector is all zeros."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _parse_time(value) -> datetime | None:
    """ISO string to an aware datetime. A naive time counts as UTC; junk gives None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_LATEST = datetime.max.replace(tzinfo=timezone.utc)


def _oldest_first(rows: list[dict]) -> list[dict]:
    """A sorted copy. A row with an unreadable time goes last, so it is never the group centre by accident."""
    return sorted(rows, key=lambda r: _parse_time(r.get("created_at")) or _LATEST)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _best_match(embedding, embedding_model, rows: list[dict], threshold: float) -> dict | None:
    """The most similar row with the same embedding model at or above threshold (first wins a tie)."""
    if not embedding:
        return None
    best, best_sim = None, threshold
    for row in rows:
        if row.get("embedding_model") != embedding_model:
            continue
        sim = cosine(embedding, row.get("embedding"))
        if sim >= best_sim and (best is None or sim > best_sim):
            best, best_sim = row, sim
    return best


# ---- grouping ----

def group_questions(rows: list[dict], threshold: float = GROUP_SIMILARITY) -> list[list[dict]]:
    """Group questions by meaning, per companion and embedding model (vectors of different models
    are not comparable). A row joins the first group whose FIRST row it matches, so a chain of
    slightly drifting questions cannot stretch one group across different topics."""
    buckets: dict[tuple, list[list[dict]]] = {}
    for row in _oldest_first([r for r in rows if r.get("embedding")]):
        groups = buckets.setdefault((row.get("companion_id"), row.get("embedding_model")), [])
        for group in groups:
            if cosine(group[0]["embedding"], row["embedding"]) >= threshold:
                group.append(row)
                break
        else:
            groups.append([row])
    return [g for groups in buckets.values() for g in groups]


# ---- shortcuts ----

def _strong_passages(row: dict) -> list[tuple]:
    """The distinct (document_id, page_from, page_to) of this row that scored SHORTCUT_SCORE or more.
    Entries that are not well formed are skipped, never raised on."""
    best = row.get("best")
    if not isinstance(best, list):
        return []
    found: list[tuple] = []
    for item in best:
        if not isinstance(item, dict):
            continue
        doc, start, end, score = (item.get("document_id"), item.get("page_from"),
                                  item.get("page_to"), item.get("score"))
        if not isinstance(doc, str) or not doc or not _is_int(start) or not _is_int(end):
            continue
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score < SHORTCUT_SCORE:
            continue
        if (doc, start, end) not in found:
            found.append((doc, start, end))
    return found


def shortcut_for_group(group: list[dict]) -> dict | None:
    """A shortcut for a group, or None. Needs SHORTCUT_MIN_QUESTIONS document-answered rows that
    each scored the same passage 3. Only where the answer is gets saved, never the answer text."""
    ordered = _oldest_first(group)
    if not ordered:
        return None
    counts: dict[tuple, int] = {}
    for row in ordered:
        if row.get("basis") not in _DOC_BASES:
            continue
        for key in _strong_passages(row):
            counts[key] = counts.get(key, 0) + 1
    shared = {k: n for k, n in counts.items() if n >= SHORTCUT_MIN_QUESTIONS}
    if not shared:
        return None
    head = max(shared, key=shared.get)
    # Same book only: one shortcut points at one document.
    extra = sorted((k for k in shared if k != head and k[0] == head[0]), key=lambda k: -shared[k])
    chosen = [head] + extra[:MAX_SHORTCUT_RANGES - 1]
    first = ordered[0]
    return {
        "companion_id": first.get("companion_id"),
        "topic": first.get("topic"),
        "embedding": first.get("embedding"),
        "embedding_model": first.get("embedding_model"),
        "document_id": head[0],
        "pages": [{"page_from": k[1], "page_to": k[2]} for k in chosen],
    }


def is_known_topic(embedding: list[float] | None, embedding_model: str | None, rows: list[dict],
                   threshold: float = GROUP_SIMILARITY) -> bool:
    """True when a shortcut or gap of ANY status already covers this topic. Counting retired and
    owner-removed rows is what stops a topic the owner deleted from being learned again."""
    return _best_match(embedding, embedding_model, rows, threshold) is not None


def nearest_shortcut(embedding: list[float] | None, embedding_model: str | None, shortcuts: list[dict],
                     threshold: float = GROUP_SIMILARITY) -> dict | None:
    """The closest ACTIVE shortcut for a new question, or None."""
    return _best_match(embedding, embedding_model, [s for s in shortcuts if s.get("status") == "active"],
                       threshold)


def after_use(shortcut: dict, hit: bool) -> dict:
    """The patch to save after a shortcut's passage was judged. A hit resets the miss streak; the
    RETIRE_MISSES-th miss in a row retires it."""
    if hit:
        return {"uses": (shortcut.get("uses") or 0) + 1, "misses_in_row": 0}
    misses = (shortcut.get("misses_in_row") or 0) + 1
    patch = {"misses_in_row": misses}
    if misses >= RETIRE_MISSES:
        patch["status"] = "retired"
    return patch


# ---- gaps ----

def _own_in_window(group: list[dict], now: datetime) -> list[dict]:
    """Own-reasoning rows created in the last GAP_WINDOW_DAYS (day 30 counts, day 31 does not)."""
    cutoff = now - timedelta(days=GAP_WINDOW_DAYS)
    return [r for r in group
            if r.get("basis") == "own" and (_parse_time(r.get("created_at")) or cutoff - timedelta(days=1)) >= cutoff]


def _newest(rows: list[dict]) -> datetime:
    return max(_parse_time(r.get("created_at")) for r in rows)


def gap_for_group(group: list[dict], now: datetime) -> dict | None:
    """A gap for a group, or None. Needs GAP_MIN_ASKS own-reasoning questions inside the window."""
    asks = _own_in_window(group, now)
    if len(asks) < GAP_MIN_ASKS:
        return None
    first = _oldest_first(group)[0]
    return {
        "companion_id": first.get("companion_id"),
        "topic": first.get("topic"),
        "embedding": first.get("embedding"),
        "embedding_model": first.get("embedding_model"),
        "ask_count": len(asks),
        "last_asked_at": _newest(asks).isoformat(),
    }


# ---- nightly plan ----

def _for_companion(rows: list[dict], companion_id) -> list[dict]:
    return [r for r in rows if r.get("companion_id") == companion_id]


def _is_covered(g: dict, questions: list[dict], threshold: float = GROUP_SIMILARITY) -> bool:
    """An open gap is covered once a similar question asked after the gap's last ask was answered
    from a document (the owner's typed answer, or a book)."""
    since = _parse_time(g.get("last_asked_at"))
    for row in questions:
        if row.get("basis") not in _DOC_BASES or row.get("companion_id") != g.get("companion_id"):
            continue
        if row.get("embedding_model") != g.get("embedding_model"):
            continue
        asked = _parse_time(row.get("created_at"))
        if asked is None or (since is not None and asked <= since):
            continue
        if cosine(g.get("embedding"), row.get("embedding")) >= threshold:
            return True
    return False


def plan_nightly(questions: list[dict], shortcuts: list[dict], gaps: list[dict], now: datetime) -> dict:
    """What the nightly run should write, as plain data. No database here; the caller applies it."""
    covered = {g["id"] for g in gaps if g.get("status") == "open" and g.get("embedding")
               and _is_covered(g, questions)}
    plan = {"new_shortcuts": [], "new_gaps": [], "gap_updates": [], "covered_gap_ids": sorted(covered)}
    updates: dict = {}
    for group in group_questions(questions):
        first = group[0]
        cid, model, centre = first.get("companion_id"), first.get("embedding_model"), first["embedding"]

        shortcut = shortcut_for_group(group)
        if shortcut and not is_known_topic(centre, model, _for_companion(shortcuts, cid)):
            plan["new_shortcuts"].append(shortcut)

        asks = _own_in_window(group, now)
        if not asks:
            continue
        known = _best_match(centre, model, _for_companion(gaps, cid), GROUP_SIMILARITY)
        if known is None:
            new_gap = gap_for_group(group, now)
            if new_gap:
                plan["new_gaps"].append(new_gap)
        elif known.get("status") == "open" and known["id"] not in covered:
            # The window moves every night, so the count is re-measured, not added to the old one.
            # Two groups close to one gap add up.
            old = updates.get(known["id"], {"ask_count": 0, "last_asked_at": None})
            newest = _newest(asks)
            last = max(filter(None, (_parse_time(old["last_asked_at"]), newest)))
            updates[known["id"]] = {"ask_count": old["ask_count"] + len(asks), "last_asked_at": last.isoformat()}
        # dismissed and covered gaps stay as they are: never re-opened

    for gap_id, upd in updates.items():
        row = next(g for g in gaps if g["id"] == gap_id)
        if upd["ask_count"] != row.get("ask_count") or _parse_time(upd["last_asked_at"]) != _parse_time(row.get("last_asked_at")):
            plan["gap_updates"].append({"id": gap_id, **upd})
    return plan


def log_cutoff(now: datetime) -> str:
    """Question-log rows older than this are deleted."""
    return (now - timedelta(days=LOG_KEEP_DAYS)).isoformat()


# ---- database-facing half: write the log after a reply, learn from it at night ----
# Everything above is pure. Below, the only I/O goes through kb/store_search.py. Nothing here may
# break or slow a reply: schedule_log runs after the reply is saved, and every function swallows
# its own errors. Only counts are logged, never a topic.

_tasks: set[asyncio.Task] = set()  # strong refs, so a running log write isn't garbage-collected


def schedule_log(tenant_id: str, companion_id: str, kb: KbResult, basis: str, sources: list[dict]) -> None:
    """Called after a reply is saved. Starts the log write in the background. Never raises.
    Small talk (basis "chat"), a failed search and a message with no safe topic are not logged."""
    try:
        if basis not in _DOC_BASES + ("own",) or kb is None or kb.failed or not (kb.topic or "").strip():
            return
        task = asyncio.get_running_loop().create_task(log_question(tenant_id, companion_id, kb, basis, sources))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception as exc:
        logger.warning("companion kb: could not schedule the question log (%s)", type(exc).__name__)


def _best_from(kb: KbResult, sources: list[dict]) -> list[dict]:
    """The passages the reply really used, as {document_id, page_from, page_to, score}. The judge's
    score comes from the search result, matched by passage id."""
    by_id = {p.id: p for p in kb.passages}
    best = []
    for source in sources or []:
        passage = by_id.get(source.get("chunk_id")) if isinstance(source, dict) else None
        if passage is not None:
            best.append({"document_id": passage.document_id, "page_from": passage.page_from,
                         "page_to": passage.page_to, "score": passage.score})
    return best


async def log_question(tenant_id: str, companion_id: str, kb: KbResult, basis: str, sources: list[dict]) -> None:
    """One log row for a question that needed the books, then the shortcut's hit or miss.
    Example: Divya's Sade Sati question, answered from Book 3 p. 88 through shortcut s1 -> row
    {topic "How long does Sade Sati last?", basis "book", best [{book3, 88, 88, 3}]} and s1 gets
    uses + 1. The message itself and the person are never written. Never raises."""
    try:
        if basis not in _DOC_BASES + ("own",) or kb.failed or not (kb.topic or "").strip():
            return
        embedding = list(kb.topic_embedding) if kb.topic_embedding else None
        if embedding is None:  # a turn resumed after an app tool lost the vector: make it again
            embedding = (await memory_embed.embed([kb.topic], "query", tenant_id) or [None])[0]
        await store_search.add_question(
            tenant_id, companion_id, topic=kb.topic, embedding=embedding, embedding_model=memory_embed.MODEL,
            basis=basis, best=_best_from(kb, sources) if basis in _DOC_BASES else [])
    except Exception as exc:
        logger.warning("companion kb: question log write failed (%s)", type(exc).__name__)
    try:
        if kb.shortcut_id:
            shortcut = await store_search.get_shortcut(tenant_id, kb.shortcut_id)
            if shortcut and shortcut.get("status") == "active":
                await store_search.update_shortcut(tenant_id, kb.shortcut_id, after_use(shortcut, kb.shortcut_hit))
    except Exception as exc:
        logger.warning("companion kb: shortcut outcome write failed (%s)", type(exc).__name__)


async def _learn_for_tenant(tenant_id: str, now: datetime) -> dict:
    """One business's nightly pass: read 30 days of questions, write what plan_nightly decides."""
    since = (now - timedelta(days=GAP_WINDOW_DAYS)).isoformat()
    questions = await store_search.list_questions(tenant_id, since)
    if not questions:
        return {"new_shortcuts": 0, "new_gaps": 0, "gap_updates": 0, "covered": 0}
    # A deleted book takes its shortcuts with it; its old log entries must not bring one back.
    cited = {b.get("document_id") for q in questions for b in q.get("best") or [] if isinstance(b, dict)}
    alive = set()
    for document_id in cited:
        if document_id and await store_search.document_exists(tenant_id, document_id):
            alive.add(document_id)
    for q in questions:
        q["best"] = [b for b in q.get("best") or [] if isinstance(b, dict) and b.get("document_id") in alive]

    plan = plan_nightly(questions, await store_search.list_shortcuts(tenant_id),
                        await store_search.list_gaps(tenant_id), now)
    done = {"new_shortcuts": 0, "new_gaps": 0, "gap_updates": 0, "covered": 0}
    for row in plan["new_shortcuts"]:
        done["new_shortcuts"] += bool(await store_search.add_shortcut(tenant_id, row))
    for row in plan["new_gaps"]:
        done["new_gaps"] += bool(await store_search.add_gap(tenant_id, row))
    for upd in plan["gap_updates"]:
        patch = {"ask_count": upd["ask_count"], "last_asked_at": upd["last_asked_at"]}
        done["gap_updates"] += bool(await store_search.update_gap(tenant_id, upd["id"], patch))
    for gap_id in plan["covered_gap_ids"]:
        done["covered"] += bool(await store_search.update_gap(tenant_id, gap_id, {"status": "covered"}))
    return done


async def run_nightly(now: datetime | None = None) -> dict:
    """The nightly learning job, for every business that has log rows. One business failing does
    not stop the others. Ends with the 90-day cleanup of the log. Returns counts. Never raises."""
    now = now or datetime.now(timezone.utc)
    totals = {"tenants": 0, "failed_tenants": 0, "new_shortcuts": 0, "new_gaps": 0, "gap_updates": 0,
              "covered": 0, "deleted_log_rows": 0}
    try:
        tenants = await store_search.tenants_with_questions()
    except Exception as exc:
        logger.warning("companion kb: nightly learning could not list businesses (%s)", type(exc).__name__)
        tenants = []
    for tenant_id in tenants:
        try:
            done = await _learn_for_tenant(tenant_id, now)
        except Exception as exc:
            totals["failed_tenants"] += 1
            logger.warning("companion kb: nightly learning failed for one business (%s)", type(exc).__name__)
            continue
        totals["tenants"] += 1
        for key, value in done.items():
            totals[key] += value
    try:
        totals["deleted_log_rows"] = await store_search.delete_questions_before(log_cutoff(now))
    except Exception as exc:
        logger.warning("companion kb: question log cleanup failed (%s)", type(exc).__name__)
    logger.info("companion kb: nightly learning %s", totals)
    return totals
