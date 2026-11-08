"""Our own permanent copy of template header media.

A template with an IMAGE/VIDEO/DOCUMENT header must send a link to the file on
every message, and Meta must be able to download it. Neither link Meta gives us
lasts:
  - sync-from-meta gets a signed scontent.whatsapp.net URL that expires (oe=);
  - an in-app upload gets a resumable-upload handle ("4::..."), not a URL at all.
So the file is copied into the public template-media bucket and that bucket's
URL is what message_templates.header_media_url holds.
"""
import hashlib
import logging
import mimetypes
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

BUCKET = "template-media"
MAX_BYTES = 20 * 1024 * 1024
MEDIA_TYPES = ("IMAGE", "VIDEO", "DOCUMENT")
# Only Meta's own CDNs: the URL comes from Meta's API, but never let a stored
# value make the server fetch an arbitrary address.
_META_HOST_SUFFIXES = (".whatsapp.net", ".fbcdn.net")
_PUBLIC_MARKER = f"/storage/v1/object/public/{BUCKET}/"


def is_ours(url: Optional[str]) -> bool:
    return bool(url) and _PUBLIC_MARKER in url


def _path_in_bucket(url: str) -> str:
    return url.split(_PUBLIC_MARKER, 1)[1].split("?", 1)[0]


def _ext(content_type: str) -> str:
    return mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""


def _store(db, path: str, data: bytes, content_type: str) -> str:
    bucket = db.storage.from_(BUCKET)
    bucket.upload(path, data, {"content-type": content_type, "upsert": "true"})
    return bucket.get_public_url(path)


def _handle_key(handle: str) -> str:
    return hashlib.sha256(handle.encode()).hexdigest()[:32]


def _is_meta_cdn(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host.endswith(s) for s in _META_HOST_SUFFIXES)


async def copy_from_meta(db, tenant_id: str, template_name: str, url: str) -> Optional[str]:
    """Download Meta's example file and store it; returns our URL, or None if it
    couldn't be copied (expired link, not a Meta CDN, too big, storage down).
    Content-addressed, so re-syncing the same file keeps the same URL."""
    if not _is_meta_cdn(url):
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.warning("template media %s: Meta returned %s", template_name, resp.status_code)
                    return None
                content_type = resp.headers.get("content-type", "application/octet-stream")
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        logger.warning("template media %s: over %s bytes, not copied", template_name, MAX_BYTES)
                        return None
                    chunks.append(chunk)
        data = b"".join(chunks)
        digest = hashlib.sha256(data).hexdigest()[:16]
        return _store(db, f"{tenant_id}/{template_name}-{digest}{_ext(content_type)}", data, content_type)
    except Exception as e:
        logger.warning("template media %s: couldn't copy from Meta: %s", template_name, e)
        return None


def save_upload(db, tenant_id: str, handle: str, data: bytes, content_type: str) -> None:
    """Keep the file behind a Meta upload handle so create/edit can store a real link."""
    try:
        _store(db, f"{tenant_id}/uploads/{_handle_key(handle)}{_ext(content_type)}", data, content_type)
    except Exception as e:
        logger.warning("template media: couldn't keep uploaded file: %s", e)


def link_for(db, tenant_id: str, value: Optional[str]) -> Optional[str]:
    """What to store as header_media_url for a value from the create/edit form:
    a Meta upload handle becomes our copy's URL; anything else is unchanged."""
    if not value or value.startswith("http"):
        return value
    key = _handle_key(value)
    try:
        bucket = db.storage.from_(BUCKET)
        for item in bucket.list(f"{tenant_id}/uploads", {"search": key}) or []:
            if (item.get("name") or "").startswith(key):
                return bucket.get_public_url(f"{tenant_id}/uploads/{item['name']}")
    except Exception as e:
        logger.warning("template media: couldn't look up uploaded file: %s", e)
    return value


def read_ours(db, url: str) -> tuple[bytes, str]:
    """The bytes and content type of a file we stored (for re-uploading to Meta)."""
    path = _path_in_bucket(url)
    data = db.storage.from_(BUCKET).download(path)
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return data, content_type
