import asyncio
import logging
import io
from uuid import UUID
import pdfplumber
from docx import Document as DocxDocument
from pptx import Presentation
import pandas as pd
from app.db.supabase import get_supabase
from app.config import settings

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 50_000

# Private Supabase Storage bucket holding each document's original upload.
DOCS_BUCKET = "knowledge-documents"

# Chunking: ~1500 chars (~400-450 tokens) stays under Jina's per-input limit and
# keeps each chunk semantically tight. 200-char overlap preserves cross-boundary context.
_CHUNK_CHARS = 1500
_CHUNK_OVERLAP = 200
_MATCH_COUNT = 5


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping windows, preferring paragraph/sentence boundaries."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= _CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + _CHUNK_CHARS, n)
        if end < n:
            window = text[start:end]
            for sep in ("\n\n", "\n", ". "):
                idx = window.rfind(sep)
                if idx > _CHUNK_CHARS // 2:
                    end = start + idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - _CHUNK_OVERLAP, start + 1)
    return chunks


async def _index_chunks(
    document_id: UUID, tenant_id: str, text: str, db, campaign_tag_id: str | None = None
) -> int:
    """Chunk → embed → replace this document's chunks. Returns chunk count."""
    from app.services.embeddings import embed_texts, to_pgvector

    chunks = _chunk_text(text)
    if not chunks:
        return 0
    embeddings = await embed_texts(chunks, input_type="document", tenant_id=tenant_id)
    if len(embeddings) != len(chunks):
        raise ValueError(f"Embedding count {len(embeddings)} != chunk count {len(chunks)}")

    db.table("knowledge_chunks").delete().eq("document_id", str(document_id)).eq("tenant_id", tenant_id).execute()
    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        db.rpc(
            "insert_knowledge_chunk",
            {
                "p_tenant_id": tenant_id,
                "p_document_id": str(document_id),
                "p_chunk_index": idx,
                "p_content": chunk,
                "p_embedding": to_pgvector(emb),
                "p_campaign_tag_id": campaign_tag_id,
            },
        ).execute()
    return len(chunks)

from app.services.gemini_client import gemini_extract_document_text


def extract_text_from_file(file_content: bytes, filename: str, mime_type: str, tenant_id: str | None = None) -> str:
    file_obj = io.BytesIO(file_content)
    text = ""
    try:
        if mime_type == "application/pdf" or filename.endswith(".pdf"):
            with pdfplumber.open(file_obj) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)

            if not text.strip():
                # Scanned PDF with no real text layer -- pdfplumber has no OCR capability
                # and returns empty. Gemini takes the PDF directly and OCRs it.
                text = gemini_extract_document_text(file_content, "application/pdf", tenant_id=tenant_id)

        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or filename.endswith(".docx"):
            doc = DocxDocument(file_obj)
            text = "\n".join(p.text for p in doc.paragraphs)

        elif mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation" or filename.endswith(".pptx"):
            prs = Presentation(file_obj)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"

        elif mime_type == "text/csv" or filename.endswith(".csv"):
            df = pd.read_csv(file_obj)
            text = df.to_string()

        elif mime_type in ("application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") or filename.endswith((".xls", ".xlsx")):
            df = pd.read_excel(file_obj)
            text = df.to_string()

        elif mime_type.startswith("image/"):
            text = gemini_extract_document_text(file_content, mime_type, tenant_id=tenant_id)

        elif mime_type == "text/plain" or filename.endswith(".txt"):
            text = file_content.decode("utf-8")

        else:
            try:
                text = file_content.decode("utf-8")
            except Exception:
                text = ""

    except Exception as e:
        logger.error(f"Text extraction failed for {filename}: {e}")
        raise ValueError(f"Could not extract text from {filename}: {e}")

    # PDF/Office extraction can yield embedded NUL bytes (corrupt glyph mappings,
    # scanned/malformed PDFs). Postgres text/JSON cannot represent a NUL byte --
    # PostgREST's JSON encoder rejects it with "unsupported Unicode escape sequence"
    # (22P05), failing the whole document. Strip before any DB write.
    return text.replace("\x00", "").strip()


async def process_document(
    document_id: UUID,
    tenant_id: str,
    file_content: bytes,
    filename: str,
    mime_type: str,
    campaign_tag_id: str | None = None,
    replaces_document_id: str | None = None,
    user_id: str | None = None,
):
    """Extract the text, then hand off to Knowledge Auto-Sort. Nothing is indexed here
    any more: the document waits as 'review_pending' until the client approves the
    sort, and only its FACTS are ever chunked (see knowledge_sort.py for why)."""
    db = get_supabase()
    try:
        text = await asyncio.to_thread(extract_text_from_file, file_content, filename, mime_type, tenant_id)
        if not text:
            raise ValueError("No text could be extracted from the file.")
        db.table("knowledge_documents").update({
            "source_text": text[:_MAX_TEXT_CHARS],
            "sort_state": "sorting",
        }).eq("id", str(document_id)).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.error(f"Document processing failed for {document_id}: {e}")
        db.table("knowledge_documents").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", str(document_id)).eq("tenant_id", tenant_id).execute()
        return

    from app.services.knowledge_sort import sort_document

    await sort_document(
        tenant_id=tenant_id,
        document_id=str(document_id),
        user_id=user_id,
        replaces_document_id=replaces_document_id,
    )


def _full_text_context(tenant_id: str, db, campaign_tag_id: str | None = None) -> str:
    """Legacy full-text injection — used as the embedding-failure fallback.
    Campaign-scoped to match RPC semantics: when campaign_tag_id is set, only that
    campaign's docs + global (untagged) docs; when None, all docs (unchanged)."""
    q = (
        db.table("knowledge_documents")
        .select("name,full_text")
        .eq("tenant_id", tenant_id)
        .eq("status", "indexed")
    )
    if campaign_tag_id:
        q = q.or_(f"campaign_tag_id.eq.{campaign_tag_id},campaign_tag_id.is.null")
    res = q.execute()
    parts = [
        f"=== {doc['name']} ===\n{doc['full_text']}"
        for doc in (res.data or [])
        if doc.get("full_text")
    ]
    return _cap_fallback("\n\n".join(parts))


# The fallback pastes whole documents into the prompt. Uncapped, a tenant with many
# large files sent up to ~50k characters per document on every retrieval miss.
_FALLBACK_MAX_CHARS = 12_000


def _cap_fallback(text: str) -> str:
    if len(text) <= _FALLBACK_MAX_CHARS:
        return text
    logger.warning("Full-text fallback truncated from %d to %d chars", len(text), _FALLBACK_MAX_CHARS)
    return text[:_FALLBACK_MAX_CHARS]


def _format_excerpts(rows: list[dict]) -> str:
    return "\n\n".join(f"=== excerpt {i + 1} ===\n{r['content']}" for i, r in enumerate(rows))


async def _semantic_search(
    db, tenant_id: str, query: str, campaign_tag_id: str | None = None, match_count: int = _MATCH_COUNT
) -> list[dict]:
    """Vector similarity via Jina embeddings + match_knowledge_chunks RPC."""
    from app.services.embeddings import embed_query, to_pgvector

    q_emb = await embed_query(query, tenant_id=tenant_id)
    res = db.rpc(
        "match_knowledge_chunks",
        {
            "query_embedding": to_pgvector(q_emb),
            "p_tenant_id": tenant_id,
            "match_count": match_count,
            "p_campaign_tag_id": campaign_tag_id,
        },
    ).execute()
    return res.data or []


SEARCH_MAX = 20


async def search_chunks(
    tenant_id: str, query: str, campaign_tag_id: str | None = None, limit: int = _MATCH_COUNT
) -> list[dict]:
    """Public semantic search for the Agents Playground "Search" tab: the chunks a character
    would read, best first, each with its similarity and document name. Same tenant filter and
    tag scope as replies (tagged chunks plus untagged ones). No full-text fallback here: the
    owner wants to see what matched, not the whole knowledge base. Raises on embedding errors."""
    db = get_supabase()
    rows = await _semantic_search(db, tenant_id, query, campaign_tag_id, max(1, min(limit, SEARCH_MAX)))
    doc_ids = list({r["document_id"] for r in rows if r.get("document_id")})
    names: dict[str, str] = {}
    if doc_ids:
        docs = (db.table("knowledge_documents").select("id, name")
                .eq("tenant_id", tenant_id).in_("id", doc_ids).execute().data or [])
        names = {d["id"]: d.get("name") for d in docs}
    return [
        {"content": r.get("content") or "", "similarity": r.get("similarity"),
         "document_name": names.get(r.get("document_id"))}
        for r in rows
    ]


def _keyword_search(
    db, tenant_id: str, query: str, campaign_tag_id: str | None = None
) -> list[dict]:
    """Postgres full-text + trigram match — no external API, language-agnostic tokens."""
    res = db.rpc(
        "keyword_match_chunks",
        {
            "p_query": query,
            "p_tenant_id": tenant_id,
            "match_count": _MATCH_COUNT,
            "p_campaign_tag_id": campaign_tag_id,
        },
    ).execute()
    return res.data or []


def _rrf_merge(lists: list[list[dict]], top_n: int, k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion: blend ranked result lists by content, best-first."""
    scores: dict[str, float] = {}
    keep: dict[str, dict] = {}
    for lst in lists:
        for rank, row in enumerate(lst):
            key = row.get("content") or ""
            if not key:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            keep[key] = row
    ordered = sorted(scores, key=lambda c: scores[c], reverse=True)[:top_n]
    return [keep[c] for c in ordered]


async def get_knowledge_context(
    tenant_id: str, query: str | None = None, campaign_tag_id: str | None = None
) -> str:
    """
    Retrieve the most relevant knowledge-base excerpts for this tenant's message.

    Retrieval mode is per-tenant via the `kb_retrieval_mode` setting:
      - "semantic" (default): Jina vector search — meaning-based, multilingual.
      - "keyword": Postgres full-text/trigram — exact tokens, no embedding API.
      - "hybrid": both, fused with Reciprocal Rank Fusion.

    Always falls back to full-text injection when the query is empty, retrieval errors,
    or nothing matches — North Star: a provider hiccup must never blank the knowledge base.
    """
    db = get_supabase()
    if not query or not query.strip():
        try:
            return _full_text_context(tenant_id, db, campaign_tag_id)
        except Exception as e:
            logger.error(f"Knowledge full-text fetch failed: {e}")
            return ""

    from app.config_dynamic import get_setting

    mode = (get_setting("kb_retrieval_mode", fallback="semantic", tenant_id=tenant_id) or "semantic").lower()

    rows: list[dict] = []
    try:
        if mode == "keyword":
            rows = _keyword_search(db, tenant_id, query, campaign_tag_id)
        elif mode == "hybrid":
            sem: list[dict] = []
            kw: list[dict] = []
            try:
                sem = await _semantic_search(db, tenant_id, query, campaign_tag_id)
            except Exception as e:
                logger.warning(f"Hybrid: semantic leg failed for tenant {tenant_id}: {e}")
            try:
                kw = _keyword_search(db, tenant_id, query, campaign_tag_id)
            except Exception as e:
                logger.warning(f"Hybrid: keyword leg failed for tenant {tenant_id}: {e}")
            rows = _rrf_merge([sem, kw], _MATCH_COUNT)
        else:
            rows = await _semantic_search(db, tenant_id, query, campaign_tag_id)
    except Exception as e:
        logger.warning(f"KB retrieval ({mode}) failed for tenant {tenant_id}: {e}. Falling back to full-text.")

    if rows:
        return _format_excerpts(rows)
    logger.info(f"No chunks matched ({mode}) for tenant {tenant_id} — falling back to full-text injection")

    try:
        return _full_text_context(tenant_id, db, campaign_tag_id)
    except Exception as e:
        logger.error(f"Knowledge full-text fallback failed: {e}")
        return ""


async def reindex_tenant(tenant_id: str) -> dict:
    """Re-chunk + embed every indexed document for a tenant (backfill for pre-RAG docs)."""
    db = get_supabase()
    res = (
        db.table("knowledge_documents")
        .select("id,full_text,campaign_tag_id")
        .eq("tenant_id", tenant_id)
        .eq("status", "indexed")
        .execute()
    )
    docs = res.data or []
    total_chunks = 0
    reindexed = 0
    for doc in docs:
        text = doc.get("full_text")
        if not text:
            continue
        try:
            total_chunks += await _index_chunks(
                UUID(doc["id"]), tenant_id, text, db, campaign_tag_id=doc.get("campaign_tag_id")
            )
            reindexed += 1
        except Exception as e:
            logger.error(f"Reindex failed for document {doc['id']}: {e}")
    return {"documents_reindexed": reindexed, "chunks_embedded": total_chunks}
