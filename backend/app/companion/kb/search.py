"""kb-search: find the passages of a character's books that answer one chat message.

Flow (T13), with the shortcut step of T28:

    rewrite  -> small talk? stop here, nothing is searched
    embed    -> english query, tamil query and the topic, in ONE call
    step A   -> main resource (tier 1): top 8 candidates, plus the pages of the nearest learned
                shortcut. The judge scores them all in one call. Keep up to 3 that pass.
    shortcut -> no main-resource passage passed, but a shortcut page did: keep it, skip step B
    step B   -> other books (tier 2): top 20 candidates, judge, keep up to 4
    else     -> no passages (the reply says so, or uses the character's own reasoning)

Worked example. Priya asks Guru "7th house la sani irundha kalyanam late aaguma?". Step A finds
the main resource's page 12, the judge gives it 3, the result is that one passage and step B never
runs. Divya asks "sadesati epo mudiyum?": the main resource has nothing, the shortcut "Sade Sati ->
Book 3 p. 88" is near her topic, the judge gives page 88 a 3, step B is skipped.
The trap: "ashtama sani na enna?" also lands near that shortcut, the judge gives page 88 a 1, the
page is dropped and step B runs as if there were no shortcut.

The main resource wins by order, not by a score bonus. A passage is never used without the judge.
search() never raises: a broken embedding or judge call gives KbResult(failed=True), no passages.
Only counts are logged here, never the message, the queries or the topic.
"""
import asyncio
import logging

from app.companion import memory_embed, playground
from app.companion.kb import judge as kb_judge
from app.companion.kb import learning, rewrite as kb_rewrite, store_search
from app.companion.kb.types import KbResult, Passage

logger = logging.getLogger(__name__)

TIER_MAIN, TIER_BOOKS = 1, 2
STEP_A_CANDIDATES, STEP_A_KEEP = 8, 3
STEP_B_CANDIDATES, STEP_B_KEEP = 20, 4
SHORTCUT_PASSAGES = 4       # at most this many passages of a shortcut's pages join step A's judge call
SEARCH_TIMEOUT_SECONDS = 20.0   # the whole search (rewrite, embed, both judge steps). A slow model must not hold the reply
RRF_K = 60                  # the usual constant: rank 1 in a list is worth 1/61

# The SQL function returns one row per (passage, list). The English and the Tamil meaning lists
# count as ONE list here (best of the two), so meaning does not get two votes against words.
_LIST_OF = {"vector_en": "meaning", "vector_ta": "meaning", "words": "words", "trigram": "trigram",
            "question": "question"}


def _passage(row: dict, score: int = 0) -> Passage:
    return Passage(id=row["id"], document_id=row["document_id"], document_title=row.get("document_title") or "",
                   tier=int(row.get("tier") or TIER_BOOKS), heading_path=row.get("heading_path") or "",
                   text=row.get("text") or "", page_from=row["page_from"], page_to=row["page_to"], score=score)


def fuse(rows: list[dict], count: int) -> list[Passage]:
    """Reciprocal rank fusion. Each list ranks its passages best first; a passage earns
    1 / (60 + rank) from every list it is in; the top `count` by total are returned.
    Example: page 12 is rank 1 for meaning and rank 2 for words -> 1/61 + 1/62, ahead of a passage
    that is rank 1 in one list only (1/61)."""
    lists: dict[str, dict[str, float]] = {}
    by_id: dict[str, dict] = {}
    for row in rows:
        name = _LIST_OF.get(row.get("source"))
        if name is None:
            continue
        by_id.setdefault(row["id"], row)
        best = lists.setdefault(name, {})
        best[row["id"]] = max(best.get(row["id"], float("-inf")), float(row.get("score") or 0.0))
    total: dict[str, float] = {}
    for best in lists.values():
        ranked = sorted(best, key=lambda i: (-best[i], i))
        for rank, chunk_id in enumerate(ranked, start=1):
            total[chunk_id] = total.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    order = sorted(total, key=lambda i: (-total[i], i))
    ov = playground.current()
    if ov is not None:   # the Playground shows each passage's meaning score
        meaning = lists.get("meaning", {})
        for i in order[:count]:
            ov.kb_scores[i] = {"meaning": meaning.get(i), "rrf": total[i]}
    return [_passage(by_id[i]) for i in order[:count]]


async def _embed(tenant_id: str, rw: kb_rewrite.Rewrite) -> tuple:
    """(english vector, tamil vector, topic vector), each None when it could not be made. One call.
    When the Tamil query is the same text as the English one (the rewrite fell back to the message
    as typed) it is embedded once."""
    has_tamil = bool(rw.tamil_query) and rw.tamil_query != rw.english_query
    texts = [rw.english_query] + ([rw.tamil_query] if has_tamil else []) + ([rw.topic_query] if rw.topic_query else [])
    vectors = list(await memory_embed.embed(texts, "query", tenant_id, retries=False))
    vectors += [None] * (len(texts) - len(vectors))
    english = vectors[0]
    return english, vectors[1] if has_tamil else english, vectors[-1] if rw.topic_query else None


async def candidates(tenant_id: str, collection_id: str, tier: int, rw: kb_rewrite.Rewrite, count: int,
                     *, vectors: tuple | None = None) -> list[Passage]:
    """The fused candidate list for one tier, before the judge (the eval runner measures this).
    vectors is what _embed returned; left out, the queries are embedded here."""
    english, tamil, _ = vectors if vectors is not None else await _embed(tenant_id, rw)
    rows = await store_search.match_chunks(
        tenant_id, collection_id, tier, model=memory_embed.MODEL, embedding_en=english, embedding_ta=tamil,
        query_en=rw.english_query, query_ta=rw.tamil_query, terms=rw.key_terms, count=count)
    return fuse(rows, count)


async def _shortcut(tenant_id: str, collection_id: str, companion_id: str | None, topic_vector,
                    skip_ids: set[str]) -> tuple[dict | None, list[Passage]]:
    """The nearest active shortcut for this topic and the passages on its pages. A shortcut into a
    book that is no longer in the character's collection is not used."""
    if not companion_id or not topic_vector:
        return None, []
    shortcuts = await store_search.active_shortcuts(tenant_id, companion_id)
    shortcut = learning.nearest_shortcut(topic_vector, memory_embed.MODEL, shortcuts)
    if not shortcut:
        return None, []
    rows = await store_search.chunks_for_pages(tenant_id, shortcut["document_id"], shortcut.get("pages") or [])
    passages = [_passage(r) for r in rows if r.get("collection_id") == collection_id and r["id"] not in skip_ids]
    if not passages:
        return None, []
    return shortcut, passages[:SHORTCUT_PASSAGES]


def _passing(passages: list[Passage], scores: list[int | None], keep: int) -> list[Passage]:
    """The passages at the pass mark, best score first (search order breaks a tie), at most `keep`.
    A None score means the judge was switched off (Playground only): the passage passes, score 0."""
    ov = playground.current()
    mark = ov.judge_min if ov is not None and ov.judge_min is not None else kb_judge.PASS_MARK
    keep = ov.results if ov is not None and ov.results else keep
    marked = [Passage(**{**p.__dict__, "score": s or 0}) for p, s in zip(passages, scores) if s is None or s >= mark]
    return sorted(marked, key=lambda p: -p.score)[:keep]


async def _judge(tenant_id: str, question: str, passages: list[Passage]) -> list[int | None] | None:
    """The judge's 0-3 marks, or a None per passage when the Playground switched the judge off."""
    ov = playground.current()
    if ov is not None and not ov.rerank:
        return [None] * len(passages)
    return await kb_judge.judge(tenant_id, question, [p.__dict__ for p in passages])


def _record(step: str, passages: list[Passage], scores: list[int | None], kept: list[Passage]) -> None:
    """Playground only: every passage the judge looked at, kept or dropped."""
    ov = playground.current()
    if ov is None:
        return
    kept_ids = {p.id for p in kept}
    for p, s in zip(passages, scores):
        ov.kb_candidates.append({
            "id": p.id, "document": p.document_title, "page_from": p.page_from, "page_to": p.page_to,
            "heading_path": p.heading_path, "text": p.text, "tier": p.tier, "step": step,
            "score": s, "meaning": (ov.kb_scores.get(p.id) or {}).get("meaning"), "kept": p.id in kept_ids})


async def _search(tenant_id: str, collection_id: str, message: str, history: list[dict] | None,
                  companion_id: str | None, rewrite=None) -> KbResult:
    ov = playground.current()
    if ov is not None and not ov.rewrite:
        rw = kb_rewrite.fallback_rewrite(message)
    elif rewrite is not None:   # the engine's one rewrite for this reply, shared with memory search
        rw = await asyncio.shield(rewrite)
    else:
        rw = await kb_rewrite.rewrite(tenant_id, message, history)
    if ov is not None:
        ov.rewritten = None if not ov.rewrite else {
            "english": rw.english_query, "tamil": rw.tamil_query, "terms": list(rw.key_terms),
            "needs_docs": rw.needs_docs}
    if not rw.needs_docs:
        playground.note("Knowledge: small talk, nothing searched")
        return KbResult(needs_docs=False)

    vectors = await _embed(tenant_id, rw)
    english, tamil, topic_vector = vectors
    if english is None and tamil is None:
        logger.warning("companion kb: search stopped, no query embedding")
        return KbResult(failed=True)
    question = rw.english_query or message
    found = dict(topic=rw.topic_query, topic_embedding=tuple(topic_vector) if topic_vector else None)

    # Step A: the main resource, plus the shortcut's pages, in one judge call.
    main = await candidates(tenant_id, collection_id, TIER_MAIN, rw, STEP_A_CANDIDATES, vectors=vectors)
    shortcut, shortcut_passages = await _shortcut(tenant_id, collection_id, companion_id, topic_vector,
                                                  {p.id for p in main})
    judged = main + shortcut_passages
    scores = await _judge(tenant_id, question, judged)
    if scores is None:
        return KbResult(failed=True)
    kept_main = _passing(main, scores[:len(main)], STEP_A_KEEP)
    kept_shortcut = _passing(shortcut_passages, scores[len(main):], STEP_B_KEEP)
    _record("main", main, scores[:len(main)], kept_main)
    _record("shortcut", shortcut_passages, scores[len(main):], kept_shortcut)
    playground.note(f"Knowledge: main files {len(main)} candidates, kept {len(kept_main)}")
    tried = dict(shortcut_id=shortcut["id"] if shortcut else None, shortcut_hit=bool(kept_shortcut))
    logger.info("companion kb: step A candidates=%d kept=%d shortcut_passages=%d shortcut_kept=%d",
                len(main), len(kept_main), len(shortcut_passages), len(kept_shortcut))
    if kept_main or kept_shortcut:
        return KbResult(passages=tuple(kept_main or kept_shortcut), **found, **tried)

    # Step B: the other books. A shortcut passage the judge just turned down is not asked about again.
    turned_down = {p.id for p in shortcut_passages}
    books = [p for p in await candidates(tenant_id, collection_id, TIER_BOOKS, rw, STEP_B_CANDIDATES,
                                         vectors=vectors) if p.id not in turned_down]
    scores = await _judge(tenant_id, question, books)
    if scores is None:
        return KbResult(failed=True)
    kept = _passing(books, scores, STEP_B_KEEP)
    _record("books", books, scores, kept)
    playground.note(f"Knowledge: other files {len(books)} candidates, kept {len(kept)}")
    logger.info("companion kb: step B candidates=%d kept=%d", len(books), len(kept))
    return KbResult(passages=tuple(kept), **found, **tried)


async def search(tenant_id: str, collection_id: str, message: str, history: list[dict] | None = None,
                 *, companion_id: str | None = None, rewrite=None) -> KbResult:
    """The passages that answer `message` from one collection of one business. Never raises.
    companion_id switches on the learned shortcuts of that character.
    rewrite: a rewrite task the caller already started for this message (the engine shares one with
    memory search); left out, the rewrite call is made here.
    Slower than SEARCH_TIMEOUT_SECONDS counts as a failure: the reply goes on without passages."""
    try:
        return await asyncio.wait_for(_search(tenant_id, collection_id, message, history, companion_id, rewrite),
                                      SEARCH_TIMEOUT_SECONDS)
    except Exception as exc:        # includes TimeoutError
        logger.warning("companion kb: search failed tenant=%s collection=%s (%s)",
                       tenant_id, collection_id, type(exc).__name__)
        return KbResult(failed=True)
