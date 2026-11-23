"""v9.2 #24 The app's error page tells Anril support which page broke.

Only the error code (Next.js "digest") and the page path come in. No error text (it can hold names or numbers),
no query string, no body. Per business: 5 an hour, past that the report is dropped quietly (the page works the
same either way). The page also sends at most one per browser session. Rows are for the Anril team, in the
database and as one log line."""
import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id
from app.routes.auto_messages import _SlidingWindow

logger = logging.getLogger(__name__)
router = APIRouter()

_limiter = _SlidingWindow(5, 3600)
_DIGEST = re.compile(r"[^A-Za-z0-9_\-]")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class ErrorReportIn(BaseModel):
    digest: str | None = Field(None, max_length=200)
    path: str | None = Field(None, max_length=500)


def clean_path(raw: str | None) -> str | None:
    """The page, never the person: query string and hash dropped, ids in the path hidden."""
    if not raw:
        return None
    path = raw.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        return None
    path = _UUID.sub(":id", path)
    path = re.sub(r"/\d{4,}", "/:id", path)
    return path[:200]


def clean_digest(raw: str | None) -> str | None:
    text = _DIGEST.sub("", raw or "")[:80]
    return text or None


@router.post("")
def report_error(body: ErrorReportIn, tenant_id: str = Depends(get_tenant_id)):
    if not _limiter.allow(tenant_id):
        return {"ok": True}
    digest, path = clean_digest(body.digest), clean_path(body.path)
    logger.warning("client error report: tenant=%s digest=%r path=%r", tenant_id, digest, path)
    try:
        get_supabase().table("client_error_reports").insert({"tenant_id": tenant_id, "digest": digest, "path": path}).execute()
    except Exception as e:  # noqa: BLE001  the table may not exist yet: the log line above still has it
        logger.warning("client error report not stored (%s)", type(e).__name__)
    return {"ok": True}
