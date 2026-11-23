import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, get_tenant_and_role

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateNote(BaseModel):
    content: str
    call_log_id: str | None = None
    is_pinned: bool = False
    structured: dict = {}
    tags: list[str] = []


class UpdateNote(BaseModel):
    content: str | None = None
    is_pinned: bool | None = None
    structured: dict | None = None
    tags: list[str] | None = None


@router.get("/all")
async def all_notes(ctx: dict = Depends(get_tenant_and_role)):
    """Returns every note for the tenant, joined with lead info. Callers only see notes for their assigned leads."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    result = (
        db.table("lead_notes")
        .select("*, leads(id, name, phone, segment, score, assigned_to)")
        .eq("tenant_id", tenant_id)
        .order("is_pinned", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    rows = result.data or []
    if ctx.get("role") == "caller" and ctx.get("caller_id"):
        rows = [r for r in rows if (r.get("leads") or {}).get("assigned_to") == ctx["caller_id"]]
    return {"data": rows}


@router.get("/leads-with-activity")
async def leads_with_activity(ctx: dict = Depends(get_tenant_and_role)):
    """Returns leads that have at least one note or call log. Callers only see their assigned leads."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    notes_res = db.table("lead_notes").select("lead_id").eq("tenant_id", tenant_id).execute()
    calls_res = db.table("call_logs").select("lead_id").eq("tenant_id", tenant_id).not_.is_("lead_id", "null").execute()

    lead_ids = list(
        {r["lead_id"] for r in (notes_res.data or [])} |
        {r["lead_id"] for r in (calls_res.data or []) if r.get("lead_id")}
    )
    if not lead_ids:
        return {"data": []}

    query = (
        db.table("leads")
        .select("id, name, phone, score, segment, assigned_to, created_at")
        .in_("id", lead_ids)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .neq("opted_out", True)
        .neq("whatsapp_undeliverable", True)
    )
    if ctx.get("role") == "caller" and ctx.get("caller_id"):
        query = query.eq("assigned_to", ctx["caller_id"])

    result = query.order("segment").order("last_inbound_at", desc=True, nullsfirst=False).order("created_at", desc=True).execute()
    return {"data": result.data or []}


@router.get("/{lead_id}")
async def get_lead_notes(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    result = (
        db.table("lead_notes")
        .select("*")
        .eq("lead_id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .order("is_pinned", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    rows = result.data or []
    pinned = [r for r in rows if r.get("is_pinned")]
    notes = [r for r in rows if not r.get("is_pinned")]
    return {"pinned": pinned, "notes": notes}


def _require_own_row(db, table: str, row_id: str, tenant_id: str, not_found: str) -> None:
    try:
        rows = db.table(table).select("id").eq("id", row_id).eq("tenant_id", tenant_id).limit(1).execute().data
    except Exception:  # a malformed id makes PostgREST 400
        rows = None
    if not rows:
        raise HTTPException(status_code=404, detail=not_found)


@router.post("/{lead_id}")
async def create_lead_note(lead_id: UUID, payload: CreateNote, ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    # The lead and call come from the request: both must be this tenant's, or the note
    # would sit on another business's lead (and reach its call scoring prompt).
    _require_own_row(db, "leads", str(lead_id), tenant_id, "Lead not found")
    if payload.call_log_id is not None:
        _require_own_row(db, "call_logs", str(payload.call_log_id), tenant_id, "Call not found")
    insert_data = {
        "lead_id": str(lead_id),
        "tenant_id": tenant_id,
        "content": payload.content,
        "is_pinned": payload.is_pinned,
        "structured": payload.structured,
    }
    if payload.tags:
        insert_data["tags"] = payload.tags
    # The author is whoever is signed in (never the request body); Call Review filters notes by it.
    if ctx.get("caller_id"):
        insert_data["caller_id"] = ctx["caller_id"]
    if payload.call_log_id is not None:
        insert_data["call_log_id"] = payload.call_log_id

    try:
        result = db.table("lead_notes").insert(insert_data).execute()
    except Exception as e:
        # PostgREST schema cache may not have refreshed for the 'tags' column yet
        if "PGRST204" in str(e) and "tags" in insert_data:
            logger.warning("PostgREST schema cache missing 'tags' column — retrying without tags")
            insert_data.pop("tags", None)
            result = db.table("lead_notes").insert(insert_data).execute()
        else:
            raise
    if not result.data:
        raise HTTPException(status_code=500, detail="Note created but no data returned")
    return result.data[0]


@router.patch("/note/{note_id}")
async def update_lead_note(note_id: UUID, payload: UpdateNote, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    updates = {}
    if payload.content is not None:
        updates["content"] = payload.content
    if payload.is_pinned is not None:
        updates["is_pinned"] = payload.is_pinned
    if payload.structured is not None:
        updates["structured"] = payload.structured
    if payload.tags is not None:
        updates["tags"] = payload.tags
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    try:
        result = db.table("lead_notes").update(updates).eq("id", str(note_id)).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        if "PGRST204" in str(e) and "tags" in updates:
            logger.warning("PostgREST schema cache missing 'tags' column — retrying update without tags")
            updates.pop("tags", None)
            if not updates:
                raise HTTPException(status_code=400, detail="Tags column not available yet")
            result = db.table("lead_notes").update(updates).eq("id", str(note_id)).eq("tenant_id", tenant_id).execute()
        else:
            raise
    if not result.data:
        raise HTTPException(status_code=404, detail="Note not found")
    return result.data[0]


@router.delete("/note/{note_id}")
async def delete_lead_note(note_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    result = db.table("lead_notes").delete().eq("id", str(note_id)).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True}
