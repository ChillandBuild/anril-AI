"""Owner routes for the Anril Agents knowledge base (dashboard login, companions.manage).

Worked example: AstroTamil's owner opens the collection "Astrology books" and adds "Book 7.pdf" (62 MB).
  POST /uploads {name: "Book 7.pdf", size_bytes: 65011712}  -> 413 "Book 7.pdf is 62 MB. The limit is 50 MB."
  POST /uploads {name: "Book 7.pdf", size_bytes: 41943040}  -> {draft_id, upload_url, ...}; the browser
       sends the file straight to storage, into <tenant>/<draft_id>/original.pdf
  POST /documents {draft_id, collection_id, tier: 2}        -> the book, status "processing"

The business is ALWAYS ctx["tenant_id"], never the body, query or path. Another business's id
answers 404, exactly like an id that does not exist. Responses go through the _*_out shapers, so
tenant_id, storage paths and embeddings never leave. Logs carry ids and counts only.
"""
import inspect
import logging
import math
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.companion import store as companion_store
from app.companion.kb import filetypes, ingest, store as kb_store, store_search
from app.companion.kb.filetypes import MAX_BYTES     # the ONE place this limit lives (50 MB)
from app.dependencies.tenant import require_permission
from app.routes.auto_messages import _SlidingWindow

logger = logging.getLogger(__name__)
router = APIRouter()
require_companions_manage = require_permission("companions.manage")

_MB = 1024 * 1024
# Retry re-reads the failed pages through OCR, which costs AI money every time. 3 a day per book is
# plenty for a real fix (add the key, press Retry) and stops a stuck button or a script.
# In-process: the count starts again when the server restarts and is per worker.
RETRIES_PER_DAY = 3
_retry_limiter = _SlidingWindow(RETRIES_PER_DAY, 24 * 3600)
_RETRY_LIMIT_SENTENCE = (f"This book was retried {RETRIES_PER_DAY} times in the last 24 hours. "
                         "Try again tomorrow, or upload a different copy of the file.")
_LIST_DEFAULT, _LIST_MAX = 100, 200

_NO_COLLECTION = "Collection not found"
_NO_BOOK = "Book not found"
_NO_SHORTCUT = "Shortcut not found"
_NO_GAP = "Question not found"
_NAME_TAKEN = "You already have a collection with that name"


# --- request bodies -----------------------------------------------------------------------------------

class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CollectionIn(_Body):
    name: str = Field(min_length=1, max_length=80)


class UploadIn(_Body):
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=10 ** 12)


class DocumentIn(_Body):
    draft_id: UUID
    collection_id: UUID
    tier: Literal[1, 2]
    title: str | None = Field(None, max_length=200)


class DocumentPatch(_Body):
    tier: Literal[1, 2] | None = None
    title: str | None = Field(None, min_length=1, max_length=200)


class FromSalesIn(_Body):
    sales_document_id: UUID
    collection_id: UUID
    tier: Literal[1, 2]


class AnswerIn(_Body):
    answer: str = Field(min_length=1, max_length=4000)


# --- response shapes (a whitelist: a new database column never leaks by accident) ---------------------

def _pick(row: dict, keys: tuple[str, ...]) -> dict:
    return {k: row.get(k) for k in keys}


def _collection_out(row: dict) -> dict:
    return {**_pick(row, ("id", "name", "created_at", "updated_at")),
            "book_count": row.get("book_count") or 0, "page_count": row.get("page_count") or 0,
            "pages_ok": row.get("pages_ok") or 0,
            "read_by": [_pick(c, ("id", "name")) for c in row.get("read_by") or []]}


def _document_out(row: dict) -> dict:
    return {**_pick(row, ("id", "collection_id", "title", "file_type", "tier", "status", "source", "error",
                          "created_at", "updated_at")),
            "collection_name": row.get("collection_name") or "",
            "size_bytes": row.get("size_bytes") or 0, "page_count": row.get("page_count") or 0,
            "pages_ok": row.get("pages_ok") or 0, "pages_failed": row.get("pages_failed") or 0,
            "pages_pending": row.get("pages_pending") or 0, "failed_pages": row.get("failed_pages") or []}


def _page_out(row: dict, *, with_text: bool = False) -> dict:
    out = _pick(row, ("page_no", "status", "method", "attempts", "char_count", "error", "updated_at"))
    if with_text:
        out["text"] = row.get("text")
    return out


def _passage_out(row: dict) -> dict:
    return _pick(row, ("id", "seq", "heading_path", "text", "page_from", "page_to", "tier"))


def _mb(size: int) -> str:
    """65011712 -> "62"; 52533657 -> "50.2" (rounded up, so a file over the limit never reads as 50)."""
    return f"{math.ceil(size / _MB * 10) / 10:g}"


def _too_big(what: str, size: int) -> str:
    return f"{what} is {_mb(size)} MB. The limit is {MAX_BYTES // _MB} MB."


# --- lookups shared by the routes ---------------------------------------------------------------------

async def _need_collection(tenant_id: str, collection_id: UUID) -> dict:
    row = await kb_store.get_collection(tenant_id, str(collection_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NO_COLLECTION)
    return row


async def _need_document(tenant_id: str, document_id: UUID) -> dict:
    row = await kb_store.get_document(tenant_id, str(document_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NO_BOOK)
    return row


async def _collection_view(tenant_id: str, collection_id: str) -> dict:
    """One collection with its counts (book_count, page_count, pages_ok, read_by)."""
    for row in await kb_store.list_collections(tenant_id):
        if row["id"] == collection_id:
            return _collection_out(row)
    raise HTTPException(status_code=404, detail=_NO_COLLECTION)


async def _document_view(tenant_id: str, document: dict) -> dict:
    """One book with its page counts and collection name."""
    for row in await kb_store.list_documents(tenant_id, document["collection_id"]):
        if row["id"] == document["id"]:
            return _document_out(row)
    raise HTTPException(status_code=404, detail=_NO_BOOK)


async def _schedule(tenant_id: str, document_id: str) -> None:
    """Ask the reading job to start now. If asking fails, the every-minute job still finds the book
    (it is status "processing"), so the owner's request is not failed for it."""
    try:
        result = ingest.schedule(tenant_id, document_id)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning("companion kb: could not schedule reading: document=%s (%s)",
                       document_id, type(exc).__name__)


# --- collections --------------------------------------------------------------------------------------

@router.get("/collections")
async def list_collections(ctx: dict = Depends(require_companions_manage)):
    return [_collection_out(row) for row in await kb_store.list_collections(ctx["tenant_id"])]


@router.post("/collections", status_code=201)
async def create_collection(payload: CollectionIn, ctx: dict = Depends(require_companions_manage)):
    try:
        row = await kb_store.create_collection(ctx["tenant_id"], payload.name)
    except kb_store.CollectionNameTaken:
        raise HTTPException(status_code=409, detail=_NAME_TAKEN)
    return _collection_out(row)


@router.patch("/collections/{collection_id}")
async def rename_collection(collection_id: UUID, payload: CollectionIn,
                            ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    try:
        row = await kb_store.rename_collection(tenant_id, str(collection_id), payload.name)
    except kb_store.CollectionNameTaken:
        raise HTTPException(status_code=409, detail=_NAME_TAKEN)
    if not row:
        raise HTTPException(status_code=404, detail=_NO_COLLECTION)
    return await _collection_view(tenant_id, str(collection_id))


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(collection_id: UUID, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    collection = await _need_collection(tenant_id, collection_id)
    books = len(await kb_store.list_documents(tenant_id, str(collection_id)))
    if books or not await kb_store.delete_collection(tenant_id, str(collection_id)):
        count = f"{books} book{'' if books == 1 else 's'}" if books else "books"
        raise HTTPException(status_code=409,
                            detail=f'"{collection["name"]}" still has {count}. Delete them first.')
    logger.info("companion kb: collection deleted: collection=%s", collection_id)
    return Response(status_code=204)


# --- upload ticket and limits (fixed paths: declared before /documents/{document_id}) ------------------

@router.get("/limits")
async def limits(ctx: dict = Depends(require_companions_manage)):
    return {"max_bytes": MAX_BYTES, "accepted_types": sorted(filetypes.ACCEPTED_TYPES)}


@router.post("/uploads")
async def create_upload(payload: UploadIn, ctx: dict = Depends(require_companions_manage)):
    """Step 1 of adding a book: check the type and size, then hand back a link the browser sends the
    file to. Nothing is written to the database here; the draft id becomes the book's id on register."""
    tenant_id = ctx["tenant_id"]
    try:
        file_type = filetypes.file_type_of(payload.name)
    except filetypes.UnsupportedFileType as exc:
        accepted = ", ".join(f".{t}" for t in sorted(filetypes.ACCEPTED_TYPES))
        raise HTTPException(status_code=400, detail=f"{exc} We accept: {accepted}.")
    if payload.size_bytes > MAX_BYTES:
        raise HTTPException(status_code=413, detail=_too_big(payload.name, payload.size_bytes))
    draft_id = str(uuid4())
    path = kb_store.storage_path(tenant_id, draft_id, file_type)
    try:
        signed = await kb_store.create_signed_upload(path)
    except Exception as exc:
        logger.warning("companion kb: could not make an upload link (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Uploading isn't available right now. Try again.")
    if not signed.get("signed_url"):
        raise HTTPException(status_code=502, detail="Uploading isn't available right now. Try again.")
    return {"draft_id": draft_id, "upload_url": signed["signed_url"], "token": signed.get("token"),
            "path": path, "file_type": file_type}


# --- Anril Sales documents (fixed paths again) --------------------------------------------------------

@router.get("/sales-documents")
async def list_sales_documents(ctx: dict = Depends(require_companions_manage)):
    """This business's Anril Sales documents that can be copied in. Read-only on the Sales side."""
    rows = await ingest.list_sales_documents(ctx["tenant_id"])
    return [_pick(row, ("id", "name", "file_type", "created_at")) for row in rows]


@router.post("/documents/from-sales", status_code=201)
async def add_from_sales(payload: FromSalesIn, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    await _need_collection(tenant_id, payload.collection_id)
    try:
        document = await ingest.copy_from_sales(tenant_id, str(payload.sales_document_id),
                                                str(payload.collection_id), payload.tier)
    except kb_store.CollectionNotFound:
        raise HTTPException(status_code=404, detail=_NO_COLLECTION)
    except LookupError:
        raise HTTPException(status_code=404, detail="That Anril Sales document was not found")
    except filetypes.UnsupportedFileType as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ingest.SalesFileTooBig as exc:
        raise HTTPException(status_code=413, detail=_too_big("This file", exc.size_bytes))
    except ingest.AlreadyCopied as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    logger.info("companion kb: book copied from Sales: document=%s", document["id"])
    return await _document_view(tenant_id, document)


# --- documents ----------------------------------------------------------------------------------------

@router.get("/documents")
async def list_documents(collection_id: UUID | None = None,
                         limit: int = Query(_LIST_DEFAULT, ge=1, le=_LIST_MAX),
                         ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    if collection_id:
        await _need_collection(tenant_id, collection_id)
    rows = await kb_store.list_documents(tenant_id, str(collection_id) if collection_id else None)
    return [_document_out(row) for row in rows[:limit]]


@router.post("/documents", status_code=201)
async def register_document(payload: DocumentIn, ctx: dict = Depends(require_companions_manage)):
    """Step 2 of adding a book: the file is in storage, now make the book. The path is rebuilt here
    from the business and the draft id (the browser never tells us where the file is), and the size
    is the real size in storage, not what the browser claimed."""
    tenant_id, draft_id = ctx["tenant_id"], str(payload.draft_id)
    await _need_collection(tenant_id, payload.collection_id)
    if await kb_store.get_document(tenant_id, draft_id):
        raise HTTPException(status_code=409, detail="This file is already added")
    stored = await kb_store.stored_file(tenant_id, draft_id)
    if not stored:
        raise HTTPException(status_code=400, detail="The file did not arrive. Upload it again.")
    try:
        file_type = filetypes.file_type_of(stored["name"])
    except filetypes.UnsupportedFileType as exc:
        await kb_store.remove_file(stored["path"])
        raise HTTPException(status_code=400, detail=str(exc))
    if stored["size_bytes"] > MAX_BYTES:
        await kb_store.remove_file(stored["path"])
        raise HTTPException(status_code=400, detail=_too_big("This file", stored["size_bytes"]))
    try:
        document = await kb_store.create_document(
            tenant_id, str(payload.collection_id), title=payload.title or "", file_type=file_type,
            size_bytes=stored["size_bytes"], tier=payload.tier, storage_path=stored["path"],
            source="upload", document_id=draft_id)
    except kb_store.CollectionNotFound:
        raise HTTPException(status_code=404, detail=_NO_COLLECTION)
    except kb_store.DocumentExists:                 # the same draft registered twice at once
        raise HTTPException(status_code=409, detail="This file is already added")
    await _schedule(tenant_id, document["id"])
    logger.info("companion kb: book registered: document=%s bytes=%s", document["id"], stored["size_bytes"])
    return await _document_view(tenant_id, document)


@router.get("/documents/{document_id}")
async def get_document(document_id: UUID, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    return await _document_view(tenant_id, await _need_document(tenant_id, document_id))


@router.patch("/documents/{document_id}")
async def update_document(document_id: UUID, payload: DocumentPatch,
                          ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    if payload.tier is None and payload.title is None:
        raise HTTPException(status_code=422, detail="Send a title or a tier to change")
    document = await _need_document(tenant_id, document_id)
    if payload.title is not None:
        await kb_store.update_document(tenant_id, document["id"], title=payload.title)
    if payload.tier is not None and payload.tier != document.get("tier"):
        await kb_store.set_tier(tenant_id, document["id"], payload.tier)
        await _schedule(tenant_id, document["id"])   # a new main resource needs its signpost questions
    return await _document_view(tenant_id, document)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: UUID, ctx: dict = Depends(require_companions_manage)):
    if not await kb_store.delete_document(ctx["tenant_id"], str(document_id)):
        raise HTTPException(status_code=404, detail=_NO_BOOK)
    logger.info("companion kb: book deleted: document=%s", document_id)
    return Response(status_code=204)


@router.post("/documents/{document_id}/retry")
async def retry_document(document_id: UUID, ctx: dict = Depends(require_companions_manage)):
    """Read the failed pages again. Pages that were read fine are left alone. At most
    RETRIES_PER_DAY times a day per book."""
    tenant_id = ctx["tenant_id"]
    document = await _need_document(tenant_id, document_id)     # first: another business's id is a 404
    if not _retry_limiter.allow(document["id"]):
        raise HTTPException(status_code=429, detail=_RETRY_LIMIT_SENTENCE)
    requeued = await kb_store.requeue_failed_pages(tenant_id, document["id"])
    if not requeued and document.get("status") == "failed":
        # The whole book failed before any page did (e.g. the file could not be opened): start over.
        await kb_store.update_document(tenant_id, document["id"], status="processing", error=None,
                                       crashed_passes=0)
    if requeued or document.get("status") == "failed":
        await _schedule(tenant_id, document["id"])
    logger.info("companion kb: retry: document=%s pages=%s", document["id"], requeued)
    return {"requeued": requeued}


@router.get("/documents/{document_id}/pages")
async def list_pages(document_id: UUID, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    document = await _need_document(tenant_id, document_id)
    return [_page_out(row) for row in await kb_store.list_pages(tenant_id, document["id"])]


@router.get("/documents/{document_id}/pages/{page_no}")
async def get_page(document_id: UUID, page_no: int = Path(ge=1, le=1_000_000),
                   ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    document = await _need_document(tenant_id, document_id)
    page = await kb_store.get_page(tenant_id, document["id"], page_no)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return _page_out(page, with_text=True)


@router.get("/documents/{document_id}/passages")
async def list_passages(document_id: UUID, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    document = await _need_document(tenant_id, document_id)
    return [_passage_out(row) for row in await kb_store.list_chunks(tenant_id, document["id"])]


# --- learned shortcuts --------------------------------------------------------------------------------

_SHORTCUT_KEYS = ("id", "topic", "document_id", "document_title", "pages", "uses", "companion_id",
                  "companion_name", "created_at")
_GAP_KEYS = ("id", "topic", "ask_count", "last_asked_at", "companion_id", "companion_name")


@router.get("/collections/{collection_id}/shortcuts")
async def list_shortcuts(collection_id: UUID, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    await _need_collection(tenant_id, collection_id)
    rows = await store_search.shortcuts_for_collection(tenant_id, str(collection_id))
    return [_pick(row, _SHORTCUT_KEYS) for row in rows]


@router.delete("/shortcuts/{shortcut_id}", status_code=204)
async def remove_shortcut(shortcut_id: UUID, ctx: dict = Depends(require_companions_manage)):
    """Marks the shortcut removed_by_owner. The row is kept, so the same topic is never learned again."""
    tenant_id = ctx["tenant_id"]
    if not await store_search.get_shortcut(tenant_id, str(shortcut_id)):
        raise HTTPException(status_code=404, detail=_NO_SHORTCUT)
    await store_search.update_shortcut(tenant_id, str(shortcut_id), {"status": "removed_by_owner"})
    logger.info("companion kb: shortcut removed by owner: shortcut=%s", shortcut_id)
    return Response(status_code=204)


# --- gaps (asked often, answered by no book) ----------------------------------------------------------

@router.get("/collections/{collection_id}/gaps")
async def list_gaps(collection_id: UUID, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    await _need_collection(tenant_id, collection_id)
    rows = await store_search.gaps_for_collection(tenant_id, str(collection_id))
    return [_pick(row, _GAP_KEYS) for row in rows]


async def _need_open_gap(tenant_id: str, gap_id: UUID) -> dict:
    gap = await store_search.get_gap(tenant_id, str(gap_id))
    if not gap:
        raise HTTPException(status_code=404, detail=_NO_GAP)
    if gap.get("status", "open") != "open":
        raise HTTPException(status_code=409, detail="This question was already answered or dismissed")
    return gap


@router.post("/gaps/{gap_id}/answer", status_code=204)
async def answer_gap(gap_id: UUID, payload: AnswerIn, ctx: dict = Depends(require_companions_manage)):
    """The owner types the answer. It is saved as a passage in the collection the gap's character
    reads, then the gap is marked covered. The answer text is never logged."""
    tenant_id = ctx["tenant_id"]
    gap = await _need_open_gap(tenant_id, gap_id)
    character = await companion_store.get_companion(tenant_id, gap["companion_id"])
    collection_id = (character or {}).get("knowledge_collection_id")
    if not collection_id or not await kb_store.collection_belongs_to_tenant(tenant_id, collection_id):
        raise HTTPException(status_code=409, detail="This character no longer reads a collection, so there "
                                                    "is nowhere to save the answer. Pick a collection for it first.")
    await ingest.add_owner_answer(tenant_id, collection_id, gap["topic"], payload.answer)
    await store_search.update_gap(tenant_id, gap["id"], {"status": "covered"})
    logger.info("companion kb: gap answered: gap=%s chars=%s", gap["id"], len(payload.answer))
    return Response(status_code=204)


@router.post("/gaps/{gap_id}/dismiss", status_code=204)
async def dismiss_gap(gap_id: UUID, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    gap = await _need_open_gap(tenant_id, gap_id)
    await store_search.update_gap(tenant_id, gap["id"], {"status": "dismissed"})
    logger.info("companion kb: gap dismissed: gap=%s", gap["id"])
    return Response(status_code=204)
