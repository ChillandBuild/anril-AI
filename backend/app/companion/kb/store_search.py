"""Database access for knowledge-base search and learning (migrations 258 and 260).

With kb/store.py, the only module that touches the companion_kb tables. This one holds the search
function call, the question log, the learned shortcuts and the gap list.

Same safety pattern as kb/store.py: the service-role key bypasses RLS, so every function takes
tenant_id first and every query filters on it. Two exceptions, both for the nightly job, which
looks across all businesses: tenants_with_questions and delete_questions_before.
Neither brings log rows back: one returns ids only, the other a count.

Worked example. Guru (tenant A) is asked about Sade Sati three times; each time add_question saves
{"topic": "How long does Sade Sati last?", "basis": "book", "best": [{"document_id": "book3",
"page_from": 88, "page_to": 88, "score": 3}]}. No person, no message text. The nightly job reads
them with list_questions, and add_shortcut saves "this topic -> Book 3, p. 88".

supabase-py is synchronous, so each call runs in asyncio.to_thread. Plain dicts in and out;
embeddings come back as list[float].
"""
import asyncio
from datetime import datetime, timezone

from app.db.supabase import get_supabase
from app.services.embeddings import to_pgvector
from app.services.pagination import fetch_all_rows

_DOCUMENTS = "companion_kb_documents"
_CHUNKS = "companion_kb_chunks"
_LOG = "companion_kb_question_log"
_SHORTCUTS = "companion_kb_shortcuts"
_GAPS = "companion_kb_gaps"
_COMPANIONS = "companions"

_TOPIC_MAX = 500
_BASES = ("primary", "book", "own")
_SHORTCUT_STATUSES = ("active", "retired", "removed_by_owner")
_GAP_STATUSES = ("open", "dismissed", "covered")
_SHORTCUT_PATCH = ("uses", "misses_in_row", "status")
_GAP_PATCH = ("ask_count", "last_asked_at", "status")
_CHUNK_COLUMNS = "id, document_id, collection_id, tier, seq, heading_path, text, page_from, page_to"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(build):
    """Run one supabase-py query off the event loop; return its rows (never None)."""
    return (await asyncio.to_thread(lambda: build().execute())).data or []


def _vector(value) -> list[float] | None:
    """pgvector comes back as the string "[0.1,0.2]"; the learning rules want list[float]."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return [float(x) for x in value.strip("[] ").split(",") if x.strip()]
        except ValueError:
            return None
    return [float(x) for x in value]


def _parsed(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["embedding"] = _vector(row.get("embedding"))
    return rows


def _topic(value) -> str:
    return (value or "").strip()[:_TOPIC_MAX].strip() if isinstance(value, str) else ""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _page_ranges(pages) -> list[dict]:
    """Well-formed {"page_from", "page_to"} ranges only; anything else is dropped."""
    out = []
    for item in pages if isinstance(pages, list) else []:
        if isinstance(item, dict) and _is_int(item.get("page_from")) and _is_int(item.get("page_to")):
            out.append({"page_from": item["page_from"], "page_to": item["page_to"]})
    return out


async def _companion_names(tenant_id: str, companion_ids: set[str] | None = None) -> dict[str, str]:
    rows = await _run(lambda: get_supabase().table(_COMPANIONS).select("id, name").eq("tenant_id", tenant_id))
    return {r["id"]: r.get("name") or "" for r in rows if companion_ids is None or r["id"] in companion_ids}


async def _owns_companion(tenant_id: str, companion_id: str) -> bool:
    return bool(await _run(lambda: get_supabase().table(_COMPANIONS).select("id")
                           .eq("tenant_id", tenant_id).eq("id", companion_id).limit(1)))


async def _document(tenant_id: str, document_id: str) -> dict | None:
    rows = await _run(lambda: get_supabase().table(_DOCUMENTS).select("id, title, tier, collection_id")
                      .eq("tenant_id", tenant_id).eq("id", document_id).limit(1))
    return rows[0] if rows else None


async def document_exists(tenant_id: str, document_id: str) -> bool:
    """True when this business still has the book (the nightly job drops log entries of deleted books)."""
    return await _document(tenant_id, document_id) is not None


# --- search -----------------------------------------------------------------------------------------

async def match_chunks(tenant_id: str, collection_id: str, tier: int, *, model: str,
                       embedding_en: list[float] | None, embedding_ta: list[float] | None,
                       query_en: str, query_ta: str, terms: list[str], count: int) -> list[dict]:
    """Calls match_companion_kb_chunks: candidate passages of ONE collection of ONE business for one
    tier. One row per (passage, list); the list name is in "source", so a passage can come back
    several times. The caller merges the lists by rank."""
    params = {
        "p_tenant": tenant_id, "p_collection": collection_id, "p_tier": tier, "p_model": model,
        "p_embedding_en": to_pgvector(embedding_en) if embedding_en else None,
        "p_embedding_ta": to_pgvector(embedding_ta) if embedding_ta else None,
        "p_query_en": query_en or "", "p_query_ta": query_ta or "",
        "p_terms": list(terms or []), "p_count": count,
    }
    return await _run(lambda: get_supabase().rpc("match_companion_kb_chunks", params))


async def chunks_for_pages(tenant_id: str, document_id: str, pages: list[dict]) -> list[dict]:
    """The book's passages that overlap any of the page ranges, in reading order, each with
    document_title, tier and collection_id. A shortcut remembers pages, not passage ids: re-reading a page gives
    its passages new ids. Example: pages [{"page_from": 88, "page_to": 88}] returns the passage
    that runs p. 87-88 and the one that runs p. 88-89."""
    ranges = _page_ranges(pages)
    document = await _document(tenant_id, document_id)
    if not ranges or not document:
        return []
    rows = await fetch_all_rows(
        lambda: get_supabase().table(_CHUNKS).select(_CHUNK_COLUMNS)
        .eq("tenant_id", tenant_id).eq("document_id", document_id).order("seq"), page_size=200)
    return [{**row, "document_title": document["title"], "tier": document["tier"]} for row in rows
            if any(row["page_from"] <= r["page_to"] and row["page_to"] >= r["page_from"] for r in ranges)]


# --- question log -----------------------------------------------------------------------------------

def _best(items) -> list[dict]:
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("document_id"), str):
            continue
        if not _is_int(item.get("page_from")) or not _is_int(item.get("page_to")):
            continue
        score = item.get("score")
        out.append({"document_id": item["document_id"], "page_from": item["page_from"],
                    "page_to": item["page_to"], "score": score if _is_int(score) else 0})
    return out


async def add_question(tenant_id: str, companion_id: str, *, topic: str, embedding: list[float] | None,
                       embedding_model: str | None, basis: str, best: list[dict]) -> dict | None:
    """One log row: the de-personalised topic and where the answer was. Never a person, never the
    message. Returns None (nothing written) for an empty topic, an unknown basis or a character of
    another business."""
    topic = _topic(topic)
    if not topic or basis not in _BASES or not await _owns_companion(tenant_id, companion_id):
        return None
    row = {"tenant_id": tenant_id, "companion_id": companion_id, "topic": topic,
           "embedding": to_pgvector(embedding) if embedding else None,
           "embedding_model": embedding_model if embedding else None, "basis": basis, "best": _best(best)}
    rows = await _run(lambda: get_supabase().table(_LOG).insert(row))
    return rows[0] if rows else None


async def list_questions(tenant_id: str, since_iso: str) -> list[dict]:
    """This business's log rows from since_iso on, oldest first. A row whose "best" names a book
    that was deleted since is still returned: the caller drops those entries."""
    return _parsed(await fetch_all_rows(
        lambda: get_supabase().table(_LOG).select("*").eq("tenant_id", tenant_id)
        .gte("created_at", since_iso).order("created_at").order("id"), page_size=200))


async def delete_questions_before(cutoff_iso: str) -> int:
    """The 90-day cleanup. ALL businesses on purpose: old rows go whoever owns them."""
    # returning="minimal": only the count comes back, not the deleted rows with their 768-number vectors.
    result = await asyncio.to_thread(lambda: get_supabase().table(_LOG).delete(count="exact", returning="minimal")
                                     .lt("created_at", cutoff_iso).execute())
    return result.count or 0


async def tenants_with_questions() -> list[str]:
    """Ids of the businesses that have log rows (all businesses: the nightly job's to-do list).
    One SQL function (migration 260) returns the distinct ids, so no log row crosses the wire."""
    rows = await _run(lambda: get_supabase().rpc("companion_kb_question_tenants", {}))
    return sorted({r["tenant_id"] for r in rows})


# --- shortcuts --------------------------------------------------------------------------------------

async def list_shortcuts(tenant_id: str, *, companion_id: str | None = None,
                         statuses: list[str] | None = None) -> list[dict]:
    def build():
        query = get_supabase().table(_SHORTCUTS).select("*").eq("tenant_id", tenant_id)
        if companion_id:
            query = query.eq("companion_id", companion_id)
        if statuses:
            query = query.in_("status", list(statuses))
        return query.order("created_at").order("id")

    return _parsed(await fetch_all_rows(build, page_size=200))


async def active_shortcuts(tenant_id: str, companion_id: str) -> list[dict]:
    return await list_shortcuts(tenant_id, companion_id=companion_id, statuses=["active"])


async def get_shortcut(tenant_id: str, shortcut_id: str) -> dict | None:
    rows = _parsed(await _run(lambda: get_supabase().table(_SHORTCUTS).select("*")
                              .eq("tenant_id", tenant_id).eq("id", shortcut_id).limit(1)))
    return rows[0] if rows else None


async def add_shortcut(tenant_id: str, row: dict) -> dict | None:
    """Save a learned shortcut. row is learning.shortcut_for_group's result:
    {companion_id, topic, embedding, embedding_model, document_id, pages}. Returns None when the
    character or the book is not this business's, or the row is not well formed."""
    topic, pages = _topic(row.get("topic")), _page_ranges(row.get("pages"))[:3]
    companion_id, document_id = row.get("companion_id"), row.get("document_id")
    if not topic or not pages or not companion_id or not document_id:
        return None
    if not await _owns_companion(tenant_id, companion_id) or not await _document(tenant_id, document_id):
        return None
    embedding = row.get("embedding")
    new = {"tenant_id": tenant_id, "companion_id": companion_id, "topic": topic,
           "embedding": to_pgvector(embedding) if embedding else None,
           "embedding_model": row.get("embedding_model") if embedding else None,
           "document_id": document_id, "pages": pages, "uses": 0, "misses_in_row": 0,
           "status": "active", "updated_at": _now()}
    rows = _parsed(await _run(lambda: get_supabase().table(_SHORTCUTS).insert(new)))
    return rows[0] if rows else None


async def update_shortcut(tenant_id: str, shortcut_id: str, patch: dict) -> dict | None:
    """Only uses, misses_in_row and status can change. None when the shortcut is not this business's."""
    fields = {k: v for k, v in (patch or {}).items() if k in _SHORTCUT_PATCH}
    if not fields or fields.get("status", "active") not in _SHORTCUT_STATUSES:
        return None
    fields["updated_at"] = _now()
    rows = _parsed(await _run(lambda: get_supabase().table(_SHORTCUTS).update(fields)
                              .eq("tenant_id", tenant_id).eq("id", shortcut_id)))
    return rows[0] if rows else None


async def shortcuts_for_collection(tenant_id: str, collection_id: str) -> list[dict]:
    """Active shortcuts into the books of one collection, most used first, for the owner's page:
    {id, topic, document_id, document_title, pages, uses, companion_id, companion_name, created_at}."""
    documents = await fetch_all_rows(
        lambda: get_supabase().table(_DOCUMENTS).select("id, title")
        .eq("tenant_id", tenant_id).eq("collection_id", collection_id).order("id"), page_size=200)
    titles = {d["id"]: d["title"] for d in documents}
    if not titles:
        return []
    rows = await fetch_all_rows(
        lambda: get_supabase().table(_SHORTCUTS).select("*").eq("tenant_id", tenant_id)
        .eq("status", "active").in_("document_id", list(titles)).order("created_at").order("id"),
        page_size=200)
    names = await _companion_names(tenant_id, {r["companion_id"] for r in rows})
    out = [{"id": r["id"], "topic": r["topic"], "document_id": r["document_id"],
            "document_title": titles[r["document_id"]], "pages": r.get("pages") or [],
            "uses": r.get("uses") or 0, "companion_id": r["companion_id"],
            "companion_name": names.get(r["companion_id"], ""), "created_at": r.get("created_at")}
           for r in rows]
    return sorted(out, key=lambda r: -r["uses"])


# --- gaps -------------------------------------------------------------------------------------------

async def list_gaps(tenant_id: str, *, companion_id: str | None = None,
                    statuses: list[str] | None = None) -> list[dict]:
    def build():
        query = get_supabase().table(_GAPS).select("*").eq("tenant_id", tenant_id)
        if companion_id:
            query = query.eq("companion_id", companion_id)
        if statuses:
            query = query.in_("status", list(statuses))
        return query.order("created_at").order("id")

    return _parsed(await fetch_all_rows(build, page_size=200))


async def get_gap(tenant_id: str, gap_id: str) -> dict | None:
    rows = _parsed(await _run(lambda: get_supabase().table(_GAPS).select("*")
                              .eq("tenant_id", tenant_id).eq("id", gap_id).limit(1)))
    return rows[0] if rows else None


async def add_gap(tenant_id: str, row: dict) -> dict | None:
    """Save a gap. row is learning.gap_for_group's result: {companion_id, topic, embedding,
    embedding_model, ask_count, last_asked_at}. None when the character is not this business's."""
    topic, companion_id = _topic(row.get("topic")), row.get("companion_id")
    if not topic or not companion_id or not await _owns_companion(tenant_id, companion_id):
        return None
    embedding = row.get("embedding")
    new = {"tenant_id": tenant_id, "companion_id": companion_id, "topic": topic,
           "embedding": to_pgvector(embedding) if embedding else None,
           "embedding_model": row.get("embedding_model") if embedding else None,
           "ask_count": row.get("ask_count") if _is_int(row.get("ask_count")) else 0,
           "last_asked_at": row.get("last_asked_at") or _now(), "status": "open", "updated_at": _now()}
    rows = _parsed(await _run(lambda: get_supabase().table(_GAPS).insert(new)))
    return rows[0] if rows else None


async def update_gap(tenant_id: str, gap_id: str, patch: dict) -> dict | None:
    """Only ask_count, last_asked_at and status can change. None when the gap is not this business's."""
    fields = {k: v for k, v in (patch or {}).items() if k in _GAP_PATCH}
    if not fields or fields.get("status", "open") not in _GAP_STATUSES:
        return None
    fields["updated_at"] = _now()
    rows = _parsed(await _run(lambda: get_supabase().table(_GAPS).update(fields)
                              .eq("tenant_id", tenant_id).eq("id", gap_id)))
    return rows[0] if rows else None


async def gaps_for_collection(tenant_id: str, collection_id: str) -> list[dict]:
    """Open gaps of the characters that read this collection, most asked first, for the owner's
    page: {id, topic, ask_count, last_asked_at, companion_id, companion_name}."""
    companions = await _run(lambda: get_supabase().table(_COMPANIONS).select("id, name")
                            .eq("tenant_id", tenant_id).eq("knowledge_collection_id", collection_id))
    names = {c["id"]: c.get("name") or "" for c in companions}
    if not names:
        return []
    rows = await fetch_all_rows(
        lambda: get_supabase().table(_GAPS).select("*").eq("tenant_id", tenant_id)
        .eq("status", "open").in_("companion_id", list(names)).order("created_at").order("id"),
        page_size=200)
    out = [{"id": r["id"], "topic": r["topic"], "ask_count": r.get("ask_count") or 0,
            "last_asked_at": r.get("last_asked_at"), "companion_id": r["companion_id"],
            "companion_name": names[r["companion_id"]]} for r in rows]
    return sorted(out, key=lambda r: -r["ask_count"])
