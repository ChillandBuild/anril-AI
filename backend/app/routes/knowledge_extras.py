"""v9.2 #168 Knowledge base: a website link the AI learns from, and "Undo last change".

Both reuse what is already there: the website text goes through the same pipeline as an uploaded file
(knowledge_documents, then Auto-Sort, review, chunks and embeddings), and "Undo last change" restores through
the same restore route as the History screen (knowledge_versions). Needs knowledge.manage (the owner has it)."""
import logging
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.routes.auto_messages import _SlidingWindow
from app.services import web_fetch
from app.services.knowledge_service import process_document

logger = logging.getLogger(__name__)
router = APIRouter()
require_knowledge_manage = require_permission("knowledge.manage")

# Each link is a fetch from our server: 20 per business per hour is far more than anyone adds by hand.
_link_limiter = _SlidingWindow(20, 3600)


class WebsiteIn(BaseModel):
    url: str = Field("", max_length=web_fetch.MAX_URL_CHARS)


def _doc_name(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return f"{parts.hostname}{path}"[:120]


@router.post("/add-website")
async def add_website(
    body: WebsiteIn,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
    ctx: dict = Depends(require_knowledge_manage),
):
    if not _link_limiter.allow(tenant_id):
        raise HTTPException(status_code=429, detail="You've added a lot of links. Please try again in an hour.")
    try:
        url, title, text = await web_fetch.fetch_page_text(body.url)
    except web_fetch.WebFetchError as e:
        raise HTTPException(status_code=422, detail=str(e))

    name = _doc_name(url)
    content = (f"Source: {url}\n" + (f"Page title: {title}\n" if title else "") + "\n" + text).encode("utf-8")
    db = get_supabase()
    res = db.table("knowledge_documents").insert({
        "tenant_id": tenant_id,
        "name": name,
        "file_type": "text/plain",
        "size_bytes": len(content),
        "status": "processing",
        "campaign_tag_id": None,
        "storage_path": None,
    }).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Couldn't save that link. Please try again.")
    doc = res.data[0]
    background_tasks.add_task(
        process_document,
        document_id=doc["id"],
        tenant_id=tenant_id,
        file_content=content,
        filename=f"{name.replace('/', '_')}.txt",
        mime_type="text/plain",
        campaign_tag_id=None,
        replaces_document_id=None,
        user_id=ctx.get("user_id"),
    )
    return doc


# ---------------------------------------------------------------- undo last change

def _chain_query(db, tenant_id: str, row: dict):
    q = db.table("knowledge_versions").select("id,kind,document_id,content,reason,created_at").eq("tenant_id", tenant_id).eq("kind", row["kind"])
    return q.eq("document_id", row["document_id"]) if row.get("document_id") else q.is_("document_id", "null")


def last_change(db, tenant_id: str) -> dict | None:
    """The newest real change (not the first "baseline" snapshot) and the version just before it, which is
    what "Undo" puts back. None when there is nothing to undo."""
    latest_rows = (
        db.table("knowledge_versions").select("id,kind,document_id,content,reason,created_at")
        .eq("tenant_id", tenant_id).neq("reason", "baseline").order("created_at", desc=True).limit(1).execute().data
    ) or []
    if not latest_rows:
        return None
    latest = latest_rows[0]
    older = (
        _chain_query(db, tenant_id, latest).lt("created_at", latest["created_at"])
        .order("created_at", desc=True).limit(1).execute().data
    ) or []
    if not older:
        return None
    previous = older[0]
    label = "Description"
    if latest["kind"] == "facts":
        doc = (db.table("knowledge_documents").select("name").eq("id", latest["document_id"]).eq("tenant_id", tenant_id)
               .limit(1).execute().data) or []
        if not doc:
            return None  # the file is gone, so there is nothing to put back
        label = doc[0].get("name") or "a file"
    return {"version_id": previous["id"], "kind": latest["kind"], "label": label, "changed_at": latest["created_at"]}


@router.get("/undo-last")
async def undo_last_preview(tenant_id: str = Depends(get_tenant_id), _ctx: dict = Depends(require_knowledge_manage)):
    change = last_change(get_supabase(), tenant_id)
    if not change:
        return {"available": False}
    return {"available": True, "version_id": str(change["version_id"]), "kind": change["kind"], "label": change["label"], "changed_at": change["changed_at"]}


class UndoIn(BaseModel):
    version_id: str


@router.post("/undo-last")
async def undo_last(
    background_tasks: BackgroundTasks,
    body: UndoIn | None = None,
    tenant_id: str = Depends(get_tenant_id),
    ctx: dict = Depends(require_knowledge_manage),
):
    """Puts back what was there before the newest change. If `version_id` is sent it must still be that
    version (someone may have changed something since the screen loaded): otherwise nothing is touched."""
    from app.routes import knowledge as knowledge_routes

    change = last_change(get_supabase(), tenant_id)
    if not change:
        raise HTTPException(status_code=404, detail="There's nothing to undo.")
    if body and body.version_id:
        try:
            wanted = str(UUID(body.version_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="That change is no longer the latest.")
        if wanted != str(change["version_id"]):
            raise HTTPException(status_code=409, detail="Something changed since you opened this. Refresh and look again.")
    result = await knowledge_routes.restore_version(
        UUID(str(change["version_id"])), background_tasks, tenant_id=tenant_id, ctx=ctx
    )
    return {**result, "label": change["label"]}
