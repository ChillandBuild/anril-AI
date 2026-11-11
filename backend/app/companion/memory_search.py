"""Long-term memory search (migration 256): old chat, diary lines and closed facts the card can't hold.

Written: the night sweep and same-day refresh index the messages they just read (windows of WINDOW
messages, both sides, OVERLAP shared with the window before); the diary job indexes each new line;
closing a fact indexes it ("Lived in Chennai (until Mar 2026)"). A one-time backfill indexes old history.
Read, on every Level 2 reply (in parallel with the card and the knowledge lookup):
  embed the person's message plus their 2 before it → top CANDIDATES by vector and by trigram
  (Tanglish spellings: "romba" / "rombha") → fused with RRF → only pieces above a similarity floor →
  pieces the prompt already shows are dropped → at most MAX_HITS, at most BLOCK_CAP characters.
Example (June, Karthik): "Bruno epdi irukan nu nenaikkiringa?" finds the 12 Mar window
"my dog Bruno got sick, vet said 2 weeks rest", though Bruno never made the 60-fact card.
Scope follows the card: character scope searches this character's pieces; business scope every
character's of this business. Text is never logged.
"""
import asyncio
import logging
from datetime import date

from app.companion import memory_card, memory_embed, playground, store

logger = logging.getLogger(__name__)

WINDOW = 8
OVERLAP = 2
MSG_CAP = 500           # characters per message inside a stored window
CANDIDATES = 20         # per half (vector, trigram)
MAX_HITS = 5
BLOCK_CAP = 1200
HIT_CAP = 350           # characters per hit in the prompt
RRF_K = 60
# Floors (bake-off 2026-11-11, 81 search queries + 30 no-answer asks, en/ta/ta-en): a piece is kept only
# if one half is this sure. Gemini 0.70 keeps 77% of right pieces and lets 10% of no-answer asks through.
VECTOR_FLOOR = 0.70
TRIGRAM_FLOOR = 0.47
# How the trigram half joins the ranking (set by the bake-off): "hybrid" = every trigram candidate
# adds to RRF; "gated" = only trigram candidates at or above TRIGRAM_FLOOR do (exact names and numbers
# still help, weak word overlap can't push the right piece down); "vector" = trigram is ignored.
# Bake-off: vector 0.882, gated 0.876 (same hit@5 in every language), hybrid 0.833. Gated, because when
# the query embedding fails or times out it still finds exact names and numbers; "vector" would find nothing.
FUSION = "gated"
QUERY_EMBED_SECONDS = 2.0   # a slow embedding API costs the reply at most this; trigram still runs
MIN_TRIGRAM_WORDS = 2       # "ok" / "hi" would match any window holding that word
HEADER = "From earlier conversations (old, dated; the card above wins if they disagree):"


def _line(m: dict) -> str:
    """One stored line. Long digit runs become [number]; a message naming a secret (OTP, password,
    Aadhaar...) is left out entirely, like the card and the diary do."""
    who = "Person" if m["role"] == "user" else "Character"
    text = memory_card._unfenced(m["content"])[:MSG_CAP]
    if memory_card._SECRET_WORDS.search(text):
        return f"{who}: (private detail left out)"
    return f"{who}: {memory_card.redact(text)}"


def _trigram_query(message: str) -> str:
    words = [w for w in message.split() if any(ch.isalnum() for ch in w)]
    return message[:500] if len(words) >= MIN_TRIGRAM_WORDS else ""


def windows(messages: list[dict], before: list[dict]) -> list[list[dict]]:
    """Windows of WINDOW messages stepping WINDOW - OVERLAP, over `before` (the OVERLAP messages
    already indexed) + `messages`; only windows holding at least one new message."""
    seq = before[-OVERLAP:] + messages
    new_ids = {m["id"] for m in messages}
    out, step = [], WINDOW - OVERLAP
    for start in range(0, max(len(seq) - OVERLAP, 1), step):
        win = seq[start:start + WINDOW]
        if any(m["id"] in new_ids for m in win):
            out.append(win)
    return out


async def index_messages(tenant_id: str, companion_id: str, end_user_id: str, messages: list[dict],
                         zone) -> int:
    """Stores the search windows for messages a memory run just read. Returns the count."""
    if not messages:
        return 0
    before = await store.messages_before(tenant_id, companion_id, end_user_id, messages[0]["created_at"],
                                         OVERLAP)
    wins = windows(messages, before)
    texts = ["\n".join(_line(m) for m in w) for w in wins]
    vectors = await memory_embed.embed(texts, "document", tenant_id)
    rows = [{"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
             "kind": "messages", "source_key": str(w[0]["id"]),
             "day": memory_card.local_day_of(w[0]["created_at"], zone).isoformat(),
             "text": t[:4000], "embedding": _vec(v)} for w, t, v in zip(wins, texts, vectors)]
    await store.upsert_chunks(rows)
    return len(rows)


async def index_diary(tenant_id: str, companion_id: str, end_user_id: str, day: str, text: str) -> None:
    [vector] = await memory_embed.embed([text], "document", tenant_id)
    await store.upsert_chunks([{"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
                                "kind": "diary", "source_key": day, "day": day, "text": text,
                                "embedding": _vec(vector)}])


async def index_facts(tenant_id: str, companion_id: str, end_user_id: str, facts: list[dict],
                      today: date) -> None:
    """Closed facts, as the card would show them ("Lived in Chennai (until Mar 2026)")."""
    if not facts:
        return
    texts = [memory_card._fact_line({**f, "status": "closed"}) for f in facts]
    vectors = await memory_embed.embed(texts, "document", tenant_id)
    rows = [{"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
             "kind": "fact", "source_key": str(f["id"]),
             "day": (memory_card._norm_date(f.get("valid_to")) or today.isoformat()),
             "text": t, "embedding": _vec(v)} for f, t, v in zip(facts, texts, vectors)]
    await store.upsert_chunks(rows)


async def drop_facts(tenant_id: str, end_user_id: str, fact_ids: list[str]) -> None:
    await store.delete_chunks(tenant_id, end_user_id, kind="fact", source_keys=[str(i) for i in fact_ids])


def _vec(vector):
    from app.services.embeddings import to_pgvector
    return to_pgvector(vector) if vector else None


async def scope_companions(tenant_id: str, companion_id: str) -> list[str]:
    if await store.get_memory_scope(tenant_id) == "business":
        return [str(c["id"]) for c in await store.list_companions(tenant_id)] or [companion_id]
    return [companion_id]


def fuse(rows: list[dict]) -> list[dict]:
    """RRF over the 'vector' and 'trigram' lists (trigram as FUSION says); a piece passes if either
    counted half clears its floor.
    Best first, each with its best vector and trigram score."""
    by_id: dict[str, dict] = {}
    for source in ("vector", "trigram"):
        ranked = sorted((r for r in rows if r.get("source") == source
                         and (source == "vector" or FUSION == "hybrid"
                              or (FUSION == "gated" and float(r["score"]) >= TRIGRAM_FLOOR))),
                        key=lambda r: -float(r["score"]))
        for rank, r in enumerate(ranked, 1):
            hit = by_id.setdefault(str(r["id"]), {**{k: r[k] for k in ("id", "kind", "day", "text")},
                                                  "companion_id": r.get("companion_id"),
                                                  "rrf": 0.0, "vector": 0.0, "trigram": 0.0})
            hit["rrf"] += 1.0 / (RRF_K + rank)
            hit[source] = max(hit[source], float(r["score"]))
    ov = playground.current()
    floor = ov.memory_floor if ov is not None and ov.memory_floor is not None else VECTOR_FLOOR
    passed = [h for h in by_id.values() if h["vector"] >= floor or h["trigram"] >= TRIGRAM_FLOOR]
    if ov is not None:   # the Playground also shows what fell below the floor
        kept = {h["id"] for h in passed}
        ov.memory_candidates[:] = [{**h, "kept": h["id"] in kept}
                                   for h in sorted(by_id.values(), key=lambda h: -h["rrf"])]
    return sorted(passed, key=lambda h: -h["rrf"])


async def search(tenant_id: str, companion_id: str, end_user_id: str, message: str, *,
                 today: date | None = None, model: str | None = None, with_recent: bool = True) -> list[dict]:
    """Fused hits for this message ([] on any error: a reply never waits on a broken search).
    with_recent=False searches the text alone (the Playground's Search tab and the agentic tool,
    whose query is already the question)."""
    try:
        before = []
        if with_recent:
            recent = await store.recent_messages(tenant_id, companion_id, end_user_id, limit=4)
            before = [m["content"] for m in recent if m["role"] == "user"][-2:]
        query = "\n".join(before + [message])
        companions = await scope_companions(tenant_id, companion_id)
        try:
            [vector] = await asyncio.wait_for(memory_embed.embed([query], "query", tenant_id, model=model,
                                                                 retries=False), QUERY_EMBED_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("companion %s: memory search embedding timed out", companion_id)
            vector = None
        trigram = _trigram_query(message)
        if vector is None and not trigram:
            return []
        rows = await store.match_chunks(tenant_id, companions, end_user_id, vector, trigram, CANDIDATES)
        hits = fuse(rows)
        playground.note(f"Memories: {len(rows)} candidates, {len(hits)} passed the floor")
        return hits
    except Exception as exc:
        logger.warning("companion %s: memory search failed (%s)", companion_id, type(exc).__name__)
        return []


def _max_hits() -> int:
    ov = playground.current()
    return ov.results if ov is not None and ov.results else MAX_HITS


def _full_date(value) -> str:
    """'2026-03-01' → '1 Mar 2026' (old pieces need the year)."""
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    return f"{memory_card._day_label(d.isoformat())} {d.year}"


def _hit_text(hit: dict) -> str:
    """A message window shows only what the person said; diary and fact pieces show as they are."""
    if hit["kind"] == "messages":
        said = [line[len("Person: "):] for line in hit["text"].splitlines() if line.startswith("Person: ")]
        text = " / ".join(said)
    else:
        text = hit["text"]
    text = " ".join(text.split())
    return text if len(text) <= HIT_CAP else text[:HIT_CAP - 1].rstrip() + "…"


def render_hits(hits: list[dict], *, shown: str = "", today: date | None = None) -> str:
    """The prompt block, or "" when nothing passed. Today's chat is left to the recap and the window;
    a diary line or fact the prompt already shows is not repeated."""
    lines: list[str] = []
    for hit in hits:
        if today and hit["kind"] == "messages" and str(hit.get("day"))[:10] == today.isoformat():
            continue
        if hit["kind"] in ("diary", "fact") and hit["text"] in shown:
            continue
        text = _hit_text(hit)
        if not text:
            continue
        line = f"- {_full_date(hit.get('day'))}: {text}"
        if len("\n".join([HEADER] + lines + [line])) > BLOCK_CAP:
            break
        lines.append(line)
        if len(lines) == _max_hits():
            break
    return "\n".join([HEADER] + lines) if lines else ""
