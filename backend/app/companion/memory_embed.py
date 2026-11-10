"""Embeddings for companion long-term memory search (companion_memory_chunks.embedding, vector(768)).

Two providers, picked by the bake-off in backend/evals/companion_memory/ (decisions log 2026-11-11):
- "gemini": Gemini Embedding 2 with the tenant's gemini_api_key. No task parameter: the text carries
  it ("task: search result | query: …" for a question, "title: none | text: …" for a stored piece).
- "jina": jina-embeddings-v5-text-small with the tenant's jina_api_key (task retrieval.query/passage).
Both give 768 dimensions. Changing MODEL means re-embedding every chunk (the backfill job does it).
A failed call returns None for those texts; the chunk is stored without a vector and the trigram
half of the search still finds it; the hourly job fills the vector in later. Text is never logged.
"""
import asyncio
import logging

import httpx

from app.config_dynamic import require_tenant_setting

logger = logging.getLogger(__name__)

MODEL = "gemini"            # bake-off 2026-11-11: gemini 0.882 vs jina 0.816 (best fusion each)
DIM = 768
_GEMINI_MODEL = "gemini-embedding-2"
_GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_MODEL}:batchEmbedContents"
_JINA_MODEL = "jina-embeddings-v5-text-small"
_JINA_URL = "https://api.jina.ai/v1/embeddings"
_BATCH = 50
_RETRY_DELAYS = (0.0, 1.0, 3.0)
_slots = asyncio.Semaphore(4)   # per process, so a backfill can't starve the reply path's queries


class MemoryEmbedError(RuntimeError):
    pass


def _gemini_text(text: str, kind: str) -> str:
    return f"task: search result | query: {text}" if kind == "query" else f"title: none | text: {text}"


async def _post(url: str, headers: dict, payload: dict, retries: bool = True) -> dict:
    resp = None
    for delay in (_RETRY_DELAYS if retries else _RETRY_DELAYS[:1]):
        if delay:
            await asyncio.sleep(delay)
        async with _slots:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (429, 500, 502, 503, 504):
            break
    if resp is None or resp.status_code != 200:
        raise MemoryEmbedError(f"embedding HTTP {resp.status_code if resp is not None else 'none'}")
    return resp.json() or {}


async def _gemini(texts: list[str], kind: str, tenant_id: str, retries: bool = True) -> list[list[float]]:
    key = require_tenant_setting("gemini_api_key", tenant_id)
    payload = {"requests": [{"model": f"models/{_GEMINI_MODEL}",
                             "content": {"parts": [{"text": _gemini_text(t, kind)}]},
                             "outputDimensionality": DIM} for t in texts]}
    data = await _post(_GEMINI_URL, {"x-goog-api-key": key, "Content-Type": "application/json"}, payload, retries)
    return [e.get("values") or [] for e in data.get("embeddings") or []]


async def _jina(texts: list[str], kind: str, tenant_id: str, retries: bool = True) -> list[list[float]]:
    key = require_tenant_setting("jina_api_key", tenant_id)
    payload = {"model": _JINA_MODEL, "task": "retrieval.query" if kind == "query" else "retrieval.passage",
               "dimensions": DIM, "input": texts}
    data = await _post(_JINA_URL, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                       payload, retries)
    return [r.get("embedding") or [] for r in sorted(data.get("data") or [], key=lambda r: r.get("index", 0))]


async def embed(texts: list[str], kind: str, tenant_id: str, model: str | None = None,
                retries: bool = True) -> list[list[float] | None]:
    """kind "query" or "document". One vector (or None on failure) per input text, same order.
    retries=False (the reply path): one attempt, so a struggling API fails fast."""
    call = _jina if (model or MODEL) == "jina" else _gemini
    out: list[list[float] | None] = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i:i + _BATCH]
        try:
            vectors = await call(batch, kind, tenant_id, retries)
            if len(vectors) != len(batch) or any(len(v) != DIM for v in vectors):
                raise MemoryEmbedError("wrong shape")
            out.extend(vectors)
        except Exception as exc:
            logger.warning("companion memory: embedding failed for %d text(s) (%s)", len(batch),
                           type(exc).__name__)
            out.extend([None] * len(batch))
    return out
