"""Database + storage access for the Anril Agents knowledge base (migration 257).

The ONLY module that touches companion_kb_collections, companion_kb_documents, companion_kb_pages,
companion_kb_chunks, companion_kb_chunk_questions and the companion-kb-documents bucket.

The backend talks to Supabase with the service-role key, which bypasses RLS, so tenant isolation is
enforced here: every function takes tenant_id first and every query filters on it. The one
exception is list_processing_documents (the reading job looks across all businesses); each row it
returns carries its own tenant_id, which the caller passes back into every other call.

supabase-py is synchronous, so each call runs in asyncio.to_thread. Plain dicts in and out.
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.companion.kb.pages import strip_invisible
from app.db.supabase import get_supabase
from app.services.embeddings import to_pgvector
from app.services.pagination import fetch_all_rows

logger = logging.getLogger(__name__)

BUCKET = "companion-kb-documents"

_COLLECTIONS = "companion_kb_collections"
_DOCUMENTS = "companion_kb_documents"
_PAGES = "companion_kb_pages"
_CHUNKS = "companion_kb_chunks"
_QUESTIONS = "companion_kb_chunk_questions"

_NAME_MAX = 80
_TITLE_MAX = 200
_ERROR_MAX = 500
_HEADING_MAX = 500
_INSERT_BATCH = 500
_CHUNK_BATCH = 200

_PAGE_STATUSES = ("ok", "failed", "pending")
_DOCUMENT_FIELDS = ("title", "status", "error", "text_layer_trusted", "page_count", "storage_path", "size_bytes",
                    "crashed_passes")
# Everything except the 768 numbers and the generated search column: callers never need them.
_CHUNK_COLUMNS = ("id, tenant_id, document_id, collection_id, tier, seq, heading_path, text, "
                  "page_from, page_to, embedding_model, signposts_at, created_at")
_PAGE_COLUMNS = "id, tenant_id, document_id, page_no, status, method, attempts, char_count, error, updated_at"


class CollectionNameTaken(ValueError):
    """This business already has a collection with that name."""


class CollectionNotFound(LookupError):
    """The collection does not exist, or belongs to another business."""


class DocumentExists(ValueError):
    """A book with this id is already registered (the same upload registered twice)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "23505" or "23505" in str(exc) or "duplicate key" in str(exc)


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not 1 <= len(cleaned) <= _NAME_MAX:
        raise ValueError(f"A collection name needs 1 to {_NAME_MAX} characters")
    return cleaned


def _short(value: str | None, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) else value


def _clean_text(value: str | None) -> str | None:
    """Postgres refuses a text value that holds a NUL character, and OCR or an odd file can
    produce one. Without this, one such page would fail its whole book on every pass, forever.
    Invisible zero-width marks go too, so word search matches what people type."""
    return strip_invisible(value.replace("\x00", "")) if isinstance(value, str) else value


async def _run(build):
    """Run one supabase-py query off the event loop; return its rows (never None)."""
    return (await asyncio.to_thread(lambda: build().execute())).data or []


# --- collections ------------------------------------------------------------------------------------

async def _name_taken(tenant_id: str, name: str, *, except_id: str | None = None) -> bool:
    rows = await _run(lambda: get_supabase().table(_COLLECTIONS).select("id")
                      .eq("tenant_id", tenant_id).eq("name", name))
    return any(r["id"] != except_id for r in rows)


async def create_collection(tenant_id: str, name: str) -> dict:
    """Make a collection. Raises CollectionNameTaken when this business already uses the name."""
    name = _clean_name(name)
    if await _name_taken(tenant_id, name):
        raise CollectionNameTaken(f'A collection named "{name}" already exists')
    try:
        rows = await _run(lambda: get_supabase().table(_COLLECTIONS)
                          .insert({"tenant_id": tenant_id, "name": name}))
    except Exception as exc:  # two requests at once: the UNIQUE (tenant_id, name) rule decides
        if _is_unique_violation(exc):
            raise CollectionNameTaken(f'A collection named "{name}" already exists') from exc
        raise
    return rows[0]


async def get_collection(tenant_id: str, collection_id: str) -> dict | None:
    rows = await _run(lambda: get_supabase().table(_COLLECTIONS).select("*")
                      .eq("tenant_id", tenant_id).eq("id", collection_id).limit(1))
    return rows[0] if rows else None


async def collection_belongs_to_tenant(tenant_id: str, collection_id: str) -> bool:
    return await get_collection(tenant_id, collection_id) is not None


async def list_collections(tenant_id: str) -> list[dict]:
    """Every collection of the business, by name, each with book_count, page_count, pages_ok and
    read_by ([{id, name}] of the characters that read it)."""
    collections = await _run(lambda: get_supabase().table(_COLLECTIONS).select("*")
                             .eq("tenant_id", tenant_id).order("name"))
    if not collections:
        return []
    documents = await list_documents(tenant_id)
    companions = await _run(lambda: get_supabase().table("companions")
                            .select("id, name, knowledge_collection_id")
                            .eq("tenant_id", tenant_id).not_.is_("knowledge_collection_id", "null"))
    out = []
    for collection in collections:
        books = [d for d in documents if d["collection_id"] == collection["id"]]
        out.append({
            **collection,
            "book_count": len(books),
            "page_count": sum(d.get("page_count") or 0 for d in books),
            "pages_ok": sum(d["pages_ok"] for d in books),
            "read_by": sorted(({"id": c["id"], "name": c.get("name") or ""} for c in companions
                               if c.get("knowledge_collection_id") == collection["id"]),
                              key=lambda c: c["name"]),
        })
    return out


async def rename_collection(tenant_id: str, collection_id: str, name: str) -> dict | None:
    """None when the collection is not this business's. Raises CollectionNameTaken on a duplicate."""
    name = _clean_name(name)
    if not await collection_belongs_to_tenant(tenant_id, collection_id):
        return None
    if await _name_taken(tenant_id, name, except_id=collection_id):
        raise CollectionNameTaken(f'A collection named "{name}" already exists')
    try:
        rows = await _run(lambda: get_supabase().table(_COLLECTIONS)
                          .update({"name": name, "updated_at": _now()})
                          .eq("tenant_id", tenant_id).eq("id", collection_id))
    except Exception as exc:
        if _is_unique_violation(exc):
            raise CollectionNameTaken(f'A collection named "{name}" already exists') from exc
        raise
    return rows[0] if rows else None


async def delete_collection(tenant_id: str, collection_id: str) -> bool:
    """False when it still has books, or is not this business's. Characters that read it are
    left with no collection (ON DELETE SET NULL)."""
    if not await collection_belongs_to_tenant(tenant_id, collection_id):
        return False
    books = await _run(lambda: get_supabase().table(_DOCUMENTS).select("id")
                       .eq("tenant_id", tenant_id).eq("collection_id", collection_id).limit(1))
    if books:
        return False
    try:
        rows = await _run(lambda: get_supabase().table(_COLLECTIONS).delete()
                          .eq("tenant_id", tenant_id).eq("id", collection_id))
    except Exception as exc:  # a book registered between the check and the delete (RESTRICT)
        if "23503" in str(exc) or getattr(exc, "code", None) == "23503":
            return False
        raise
    return bool(rows)


# --- documents --------------------------------------------------------------------------------------

async def create_document(tenant_id: str, collection_id: str, *, title: str, file_type: str,
                          size_bytes: int = 0, tier: int = 2, storage_path: str | None = None,
                          source: str = "upload", source_document_id: str | None = None,
                          document_id: str | None = None) -> dict:
    """Register a book (status processing, no pages yet). Raises CollectionNotFound when the
    collection is not this business's, DocumentExists when the id is already a book.
    document_id may be chosen first, so the file can be uploaded to its folder before the row
    exists."""
    if tier not in (1, 2):
        raise ValueError("tier must be 1 (main resource) or 2 (book)")
    if not await collection_belongs_to_tenant(tenant_id, collection_id):
        raise CollectionNotFound("Collection not found")
    row = {
        "tenant_id": tenant_id, "collection_id": collection_id,
        "title": ((title or "").strip() or "Untitled")[:_TITLE_MAX],
        "file_type": file_type, "size_bytes": size_bytes, "tier": tier, "storage_path": storage_path,
        "source": source, "source_document_id": source_document_id,
        "status": "processing", "page_count": 0, "text_layer_trusted": None, "error": None,
        "crashed_passes": 0, "updated_at": _now(),
    }
    if document_id:
        row["id"] = document_id
    try:
        return (await _run(lambda: get_supabase().table(_DOCUMENTS).insert(row)))[0]
    except Exception as exc:  # the same draft registered twice at once: the primary key decides
        if _is_unique_violation(exc):
            raise DocumentExists("This file is already added") from exc
        raise


async def get_document(tenant_id: str, document_id: str) -> dict | None:
    rows = await _run(lambda: get_supabase().table(_DOCUMENTS).select("*")
                      .eq("tenant_id", tenant_id).eq("id", document_id).limit(1))
    return rows[0] if rows else None


async def list_documents(tenant_id: str, collection_id: str | None = None) -> list[dict]:
    """Books of the business (of one collection when given), newest first, each with pages_ok,
    pages_failed, pages_pending, failed_pages (sorted page numbers) and collection_name."""
    def build():
        query = get_supabase().table(_DOCUMENTS).select("*").eq("tenant_id", tenant_id)
        if collection_id:
            query = query.eq("collection_id", collection_id)
        return query.order("created_at", desc=True).order("id")

    documents = await fetch_all_rows(build)
    if not documents:
        return []
    ids = [d["id"] for d in documents]
    # Only the unread pages are fetched: ok = page_count - pending - failed. A 320-page book that
    # is fully read costs 0 page rows here.
    unread = await fetch_all_rows(
        lambda: get_supabase().table(_PAGES).select("document_id, page_no, status")
        .eq("tenant_id", tenant_id).in_("document_id", ids).in_("status", ["pending", "failed"])
        .order("document_id").order("page_no"))
    names = {c["id"]: c["name"] for c in await _run(
        lambda: get_supabase().table(_COLLECTIONS).select("id, name").eq("tenant_id", tenant_id))}
    for document in documents:
        mine = [p for p in unread if p["document_id"] == document["id"]]
        failed = sorted(p["page_no"] for p in mine if p["status"] == "failed")
        pending = sum(1 for p in mine if p["status"] == "pending")
        document["failed_pages"] = failed
        document["pages_failed"] = len(failed)
        document["pages_pending"] = pending
        document["pages_ok"] = max((document.get("page_count") or 0) - len(failed) - pending, 0)
        document["collection_name"] = names.get(document["collection_id"], "")
    return documents


async def list_processing_documents(limit: int = 20) -> list[dict]:
    """Unfinished books, the one touched longest ago first, across ALL businesses: the only
    function here with no tenant filter (the every-minute reading job has no business in hand).
    Each row carries its own tenant_id; the job passes that into every other call.
    Ordered by updated_at, not created_at: every pass touches its book, so a book that keeps
    failing moves to the back and can never hide newer books behind the limit."""
    return await _run(lambda: get_supabase().table(_DOCUMENTS).select("*")
                      .eq("status", "processing").order("updated_at").limit(limit))


async def update_document(tenant_id: str, document_id: str, **fields) -> dict | None:
    """Change title, status, error, text_layer_trusted, page_count, storage_path, size_bytes or
    crashed_passes. Any other field is refused (tier goes through set_tier, which also moves the
    passages)."""
    unknown = set(fields) - set(_DOCUMENT_FIELDS)
    if unknown:
        raise ValueError(f"Not updatable: {', '.join(sorted(unknown))}")
    if "title" in fields:
        fields["title"] = ((fields["title"] or "").strip() or "Untitled")[:_TITLE_MAX]
    if "error" in fields:
        fields["error"] = _short(fields["error"], _ERROR_MAX)
    rows = await _run(lambda: get_supabase().table(_DOCUMENTS).update({**fields, "updated_at": _now()})
                      .eq("tenant_id", tenant_id).eq("id", document_id))
    return rows[0] if rows else None


async def set_tier(tenant_id: str, document_id: str, tier: int) -> dict | None:
    """1 = main resource, 2 = book. The passages carry a copy of the tier, so they move too."""
    if tier not in (1, 2):
        raise ValueError("tier must be 1 (main resource) or 2 (book)")
    rows = await _run(lambda: get_supabase().table(_DOCUMENTS).update({"tier": tier, "updated_at": _now()})
                      .eq("tenant_id", tenant_id).eq("id", document_id))
    if not rows:
        return None
    await _run(lambda: get_supabase().table(_CHUNKS).update({"tier": tier})
               .eq("tenant_id", tenant_id).eq("document_id", document_id))
    return rows[0]


async def delete_document(tenant_id: str, document_id: str) -> bool:
    """Delete the book, its pages, passages and signpost questions (database cascade), then its
    stored file. A file that cannot be removed is logged and left; the book is still gone."""
    document = await get_document(tenant_id, document_id)
    if not document:
        return False
    await _run(lambda: get_supabase().table(_DOCUMENTS).delete()
               .eq("tenant_id", tenant_id).eq("id", document_id))
    path = document.get("storage_path")
    # Only ever remove inside this business's own folder, whatever the row says.
    if path and path.startswith(f"{tenant_id}/") and not await remove_file(path):
        logger.warning("companion kb: file left in storage after delete: document=%s", document_id)
    return True


# --- pages (the ledger) -----------------------------------------------------------------------------

async def set_page_count(tenant_id: str, document_id: str, page_count: int) -> int:
    """Write the page count and make sure rows 1..page_count exist (new ones pending). Safe to
    call twice: existing rows are left alone. Returns how many rows were added."""
    if page_count < 0:
        raise ValueError("page_count cannot be negative")
    if not await get_document(tenant_id, document_id):
        return 0
    existing = {p["page_no"] for p in await fetch_all_rows(
        lambda: get_supabase().table(_PAGES).select("page_no")
        .eq("tenant_id", tenant_id).eq("document_id", document_id).order("page_no"))}
    now = _now()
    missing = [{"tenant_id": tenant_id, "document_id": document_id, "page_no": n, "status": "pending",
                "method": None, "attempts": 0, "char_count": 0, "text": None, "error": None,
                "updated_at": now}
               for n in range(1, page_count + 1) if n not in existing]
    for start in range(0, len(missing), _INSERT_BATCH):
        batch = missing[start:start + _INSERT_BATCH]
        await _run(lambda b=batch: get_supabase().table(_PAGES).insert(b))
    await _run(lambda: get_supabase().table(_DOCUMENTS).update({"page_count": page_count, "updated_at": now})
               .eq("tenant_id", tenant_id).eq("id", document_id))
    return len(missing)


async def list_pages(tenant_id: str, document_id: str, *, with_text: bool = False) -> list[dict]:
    """The ledger of one book in page order. The page text is left out unless asked for."""
    rows = await fetch_all_rows(
        lambda: get_supabase().table(_PAGES).select("*" if with_text else _PAGE_COLUMNS)
        .eq("tenant_id", tenant_id).eq("document_id", document_id).order("page_no"))
    if not with_text:
        for row in rows:
            row.pop("text", None)
    return rows


async def get_page(tenant_id: str, document_id: str, page_no: int) -> dict | None:
    rows = await _run(lambda: get_supabase().table(_PAGES).select("*").eq("tenant_id", tenant_id)
                      .eq("document_id", document_id).eq("page_no", page_no).limit(1))
    return rows[0] if rows else None


async def pending_pages(tenant_id: str, document_id: str, limit: int = 50) -> list[int]:
    """The next unread page numbers, lowest first."""
    rows = await _run(lambda: get_supabase().table(_PAGES).select("page_no").eq("tenant_id", tenant_id)
                      .eq("document_id", document_id).eq("status", "pending").order("page_no").limit(limit))
    return [r["page_no"] for r in rows]


async def save_page(tenant_id: str, document_id: str, page_no: int, *, status: str,
                    method: str | None = None, text: str | None = None,
                    error: str | None = None) -> dict | None:
    """Record one reading attempt of a page: ok (with its text), failed (with the error), or
    pending (try again next run). Every call counts as one attempt."""
    if status not in _PAGE_STATUSES:
        raise ValueError(f"status must be one of {_PAGE_STATUSES}")
    page = await get_page(tenant_id, document_id, page_no)
    if not page:
        return None
    text = _clean_text(text)
    payload = {"status": status, "method": method, "text": text, "char_count": len(text or ""),
               "error": _short(error, _ERROR_MAX), "attempts": (page.get("attempts") or 0) + 1,
               "updated_at": _now()}
    rows = await _run(lambda: get_supabase().table(_PAGES).update(payload).eq("tenant_id", tenant_id)
                      .eq("document_id", document_id).eq("page_no", page_no))
    return rows[0] if rows else None


async def ok_pages_text(tenant_id: str, document_id: str) -> list[tuple[int, str]]:
    """(page number, text) of every page that was read, in page order."""
    rows = await fetch_all_rows(
        lambda: get_supabase().table(_PAGES).select("page_no, text").eq("tenant_id", tenant_id)
        .eq("document_id", document_id).eq("status", "ok").order("page_no"), page_size=200)
    return [(r["page_no"], r.get("text") or "") for r in rows]


async def requeue_failed_pages(tenant_id: str, document_id: str) -> int:
    """Retry: every failed page goes back to pending with a fresh attempt count (its last error
    stays visible until it is read again), and the book goes back to processing with a fresh
    crashed-pass count. Returns how many pages were queued."""
    rows = await _run(lambda: get_supabase().table(_PAGES)
                      .update({"status": "pending", "attempts": 0, "updated_at": _now()})
                      .eq("tenant_id", tenant_id).eq("document_id", document_id).eq("status", "failed"))
    if rows:
        await update_document(tenant_id, document_id, status="processing", error=None, crashed_passes=0)
    return len(rows)


# --- passages ---------------------------------------------------------------------------------------

def _without_vectors(rows: list[dict]) -> list[dict]:
    for row in rows:
        row.pop("embedding", None)
        row.pop("tsv", None)
    return rows


async def replace_chunks(tenant_id: str, document_id: str, chunks: list[dict]) -> list[dict]:
    """Swap the book's passages for a new set (delete, then insert). Each chunk is
    {heading_path, text, page_from, page_to}; tenant, book, collection, tier and seq 0..n-1 are
    added here. Old signpost questions go with the old passages. Returns the new rows."""
    document = await get_document(tenant_id, document_id)
    if not document:
        return []
    await _run(lambda: get_supabase().table(_CHUNKS).delete()
               .eq("tenant_id", tenant_id).eq("document_id", document_id))
    rows = [{"tenant_id": tenant_id, "document_id": document_id,
             "collection_id": document["collection_id"], "tier": document["tier"], "seq": seq,
             "heading_path": _clean_text(chunk.get("heading_path") or "")[:_HEADING_MAX],
             "text": _clean_text(chunk["text"]), "page_from": chunk["page_from"], "page_to": chunk["page_to"]}
            for seq, chunk in enumerate(chunks)]
    inserted: list[dict] = []
    for start in range(0, len(rows), _CHUNK_BATCH):
        batch = rows[start:start + _CHUNK_BATCH]
        inserted.extend(await _run(lambda b=batch: get_supabase().table(_CHUNKS).insert(b)))
    return _without_vectors(inserted)


async def list_chunks(tenant_id: str, document_id: str) -> list[dict]:
    """The book's passages in reading order, without the embedding numbers."""
    return _without_vectors(await fetch_all_rows(
        lambda: get_supabase().table(_CHUNKS).select(_CHUNK_COLUMNS)
        .eq("tenant_id", tenant_id).eq("document_id", document_id).order("seq"), page_size=200))


async def get_chunks(tenant_id: str, chunk_ids: list[str]) -> list[dict]:
    """Passages by id, in the order asked. Ids of another business are simply not returned."""
    if not chunk_ids:
        return []
    rows = _without_vectors(await _run(lambda: get_supabase().table(_CHUNKS).select(_CHUNK_COLUMNS)
                                       .eq("tenant_id", tenant_id).in_("id", list(chunk_ids))))
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]


async def chunks_missing_embedding(tenant_id: str, document_id: str, limit: int = 100) -> list[dict]:
    return _without_vectors(await _run(
        lambda: get_supabase().table(_CHUNKS).select(_CHUNK_COLUMNS).eq("tenant_id", tenant_id)
        .eq("document_id", document_id).is_("embedding", "null").order("seq").limit(limit)))


async def set_chunk_embedding(tenant_id: str, chunk_id: str, embedding: list[float], model: str) -> None:
    await _run(lambda: get_supabase().table(_CHUNKS)
               .update({"embedding": to_pgvector(embedding), "embedding_model": model})
               .eq("tenant_id", tenant_id).eq("id", chunk_id))


async def chunks_missing_signposts(tenant_id: str, document_id: str, limit: int = 20) -> list[dict]:
    """Main-resource passages (tier 1) whose signpost questions are not written yet."""
    return _without_vectors(await _run(
        lambda: get_supabase().table(_CHUNKS).select(_CHUNK_COLUMNS).eq("tenant_id", tenant_id)
        .eq("document_id", document_id).eq("tier", 1).is_("signposts_at", "null").order("seq").limit(limit)))


async def add_chunk_questions(tenant_id: str, chunk: dict, questions: list[dict]) -> int:
    """Save the signpost questions of one passage, then mark the passage done (also when the
    list is empty, so it is not asked for again). Each question is
    {question_en, question_ta, embedding, embedding_model}. The passage is looked up again by
    tenant + id: nothing in the chunk dict is trusted for scope. Returns how many were saved."""
    found = await get_chunks(tenant_id, [chunk["id"]])
    if not found:
        return 0
    real = found[0]
    rows = [{"tenant_id": tenant_id, "chunk_id": real["id"], "collection_id": real["collection_id"],
             "question_en": (q.get("question_en") or "")[:500],
             "question_ta": (q.get("question_ta") or "")[:500],
             "embedding": to_pgvector(q["embedding"]) if q.get("embedding") else None,
             "embedding_model": q.get("embedding_model")}
            for q in questions]
    if rows:
        await _run(lambda: get_supabase().table(_QUESTIONS).insert(rows))
    await _run(lambda: get_supabase().table(_CHUNKS).update({"signposts_at": _now()})
               .eq("tenant_id", tenant_id).eq("id", real["id"]))
    return len(rows)


# --- stored files -----------------------------------------------------------------------------------

def storage_path(tenant_id: str, document_id: str, file_type: str) -> str:
    """<tenant>/<document>/original.<ext>: a file always lives in its business's own folder."""
    ext = "".join(ch for ch in (file_type or "").lower() if ch.isalnum()) or "bin"
    return f"{tenant_id}/{document_id}/original.{ext}"


def _bucket():
    return get_supabase().storage.from_(BUCKET)


async def create_signed_upload(path: str) -> dict:
    """A short-lived link the browser sends the file to. Returns {signed_url, token, path}."""
    made = await asyncio.to_thread(lambda: _bucket().create_signed_upload_url(path))
    return {"signed_url": made.get("signed_url") or made.get("signedUrl"),
            "token": made.get("token"), "path": made.get("path") or path}


async def stored_file(tenant_id: str, document_id: str) -> dict | None:
    """The uploaded original of a book: {path, name, size_bytes}, or None when nothing arrived."""
    folder = f"{tenant_id}/{document_id}"
    items = await asyncio.to_thread(lambda: _bucket().list(folder)) or []
    for item in items:
        name = item.get("name") or ""
        if name.startswith("original."):
            size = (item.get("metadata") or {}).get("size") or 0
            return {"path": f"{folder}/{name}", "name": name, "size_bytes": int(size)}
    return None


_DOWNLOAD_LINK_SECONDS = 15 * 60     # a 300 MB book takes well under a minute on the server's network
_DOWNLOAD_PIECE = 1024 * 1024         # 1 MB at a time


def _http_client() -> httpx.AsyncClient:
    """The client download_file streams with. Tests swap it for one that serves the fake bucket."""
    return httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))


async def download_file(path: str, dest_path: str) -> int:
    """Copy a stored file to a local path, 1 MB at a time. Returns its size in bytes.

    Streamed, not read whole: a 227 MB scanned book held in memory at once could run the server out of
    RAM. Example: "t1/d7/original.pdf" -> a short-lived signed link -> 227 pieces written to dest_path.
    A non-2xx answer or a broken connection raises, and the caller deletes the half-written file."""
    made = await asyncio.to_thread(lambda: _bucket().create_signed_url(path, _DOWNLOAD_LINK_SECONDS))
    url = made.get("signedURL") or made.get("signedUrl")
    if not url:
        raise RuntimeError("storage gave no download link")
    size = 0
    async with _http_client() as client, client.stream("GET", url) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as handle:
            async for piece in response.aiter_bytes(_DOWNLOAD_PIECE):
                handle.write(piece)
                size += len(piece)
    return size


async def upload_file(path: str, data: bytes, content_type: str) -> None:
    await asyncio.to_thread(lambda: _bucket().upload(
        path, data, {"content-type": content_type, "upsert": "true"}))


async def remove_file(path: str) -> bool:
    """True when the file is gone. A storage error is logged and reported as False, never raised."""
    try:
        await asyncio.to_thread(lambda: _bucket().remove([path]))
        return True
    except Exception as exc:
        logger.warning("companion kb: could not remove a stored file: %s", type(exc).__name__)
        return False


# --- added for ingest ---

async def find_document_by_source(tenant_id: str, collection_id: str, source: str, *,
                                  source_document_id: str | None = None) -> dict | None:
    """The oldest book of one collection with this source ("owner_answers" has one per collection).
    With source_document_id: the copy of that one Anril Sales document, if the collection has it."""
    def build():
        query = (get_supabase().table(_DOCUMENTS).select("*").eq("tenant_id", tenant_id)
                 .eq("collection_id", collection_id).eq("source", source))
        if source_document_id:
            query = query.eq("source_document_id", source_document_id)
        return query.order("created_at").limit(1)

    rows = await _run(build)
    return rows[0] if rows else None


async def add_chunk(tenant_id: str, document_id: str, *, heading_path: str, text: str,
                    page_from: int = 1, page_to: int = 1) -> dict | None:
    """Append ONE passage to a book and leave the others alone (replace_chunks swaps the whole
    book). seq continues after the last passage. None when the book is not this business's."""
    document = await get_document(tenant_id, document_id)
    if not document:
        return None
    last = await _run(lambda: get_supabase().table(_CHUNKS).select("seq").eq("tenant_id", tenant_id)
                      .eq("document_id", document_id).order("seq", desc=True).limit(1))
    row = {"tenant_id": tenant_id, "document_id": document_id, "collection_id": document["collection_id"],
           "tier": document["tier"], "seq": (last[0]["seq"] + 1) if last else 0,
           "heading_path": _clean_text(heading_path or "")[:_HEADING_MAX], "text": _clean_text(text),
           "page_from": page_from, "page_to": page_to}
    return _without_vectors(await _run(lambda: get_supabase().table(_CHUNKS).insert(row)))[0]


async def documents_with_unfinished_chunks(limit: int = 20, exclude_tenants=()) -> list[dict]:
    """[{tenant_id, document_id}] of books that have a passage without its embedding, or a
    main-resource passage without its signpost questions, in a fixed order (business, then book).
    Across ALL businesses, like list_processing_documents: the fill-in job has no business in
    hand, and each row carries its own tenant_id. Reads ids only, never passage text.

    exclude_tenants: businesses to leave out. The job passes the ones it just found it cannot fill
    (no AI key) and asks again, so their passages cannot fill the window and hide everyone else's."""
    skip = sorted({str(t) for t in exclude_tenants})

    def build(signposts: bool):
        query = get_supabase().table(_CHUNKS).select("tenant_id, document_id")
        query = query.eq("tier", 1).is_("signposts_at", "null") if signposts else query.is_("embedding", "null")
        if skip:
            query = query.not_.in_("tenant_id", skip)
        return query.order("tenant_id").order("document_id").limit(limit * 10)

    no_vector = await _run(lambda: build(False))
    no_signposts = await _run(lambda: build(True))
    seen: dict[tuple, dict] = {}
    for row in no_vector + no_signposts:
        seen.setdefault((row["tenant_id"], row["document_id"]),
                        {"tenant_id": row["tenant_id"], "document_id": row["document_id"]})
    return [seen[key] for key in sorted(seen)][:limit]
