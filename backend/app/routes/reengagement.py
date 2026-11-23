import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services.template_params import template_status

logger = logging.getLogger(__name__)
router = APIRouter()
require_leads_view = require_permission("leads.view")
require_leads_manage = require_permission("leads.manage")


class ReengagementStepCreate(BaseModel):
    type: str  # 'broadcast' or 'inbound'
    broadcast_id: str | None = None
    delay_hours: int
    target_segments: list[str]
    target_sources: list[str] | None = None  # None/empty = all sources
    message_type: str  # 'freeform' or 'template'
    message_content: str | None = None
    template_name: str | None = None
    template_variables: list[str] | None = None
    fallback_template_name: str | None = None
    fallback_template_variables: list[str] | None = None
    # Only people in this Customers group (customer_groups.id). None = everybody the other rules pick.
    target_group_id: str | None = None


class ReengagementStepUpdate(BaseModel):
    delay_hours: int
    target_segments: list[str]
    target_sources: list[str] | None = None
    message_type: str
    message_content: str | None = None
    template_name: str | None = None
    template_variables: list[str] | None = None
    fallback_template_name: str | None = None
    fallback_template_variables: list[str] | None = None
    # Left out = keep what is saved; null = back to everybody; an id = only that group.
    target_group_id: str | None = None


@router.get("/steps")
def list_steps(
    type: str | None = None,
    broadcast_id: str | None = None,
    ctx: dict = Depends(require_leads_view),
):
    db = get_supabase()
    q = db.table("reengagement_steps").select("*").eq("tenant_id", ctx["tenant_id"])
    if type:
        q = q.eq("type", type)
    if broadcast_id:
        q = q.eq("broadcast_id", broadcast_id)
    
    rows = q.order("delay_hours").execute()
    return {"data": rows.data or []}


VALID_SOURCES = {"organic", "meta_ads", "csv", "telegram", "instagram", "facebook"}


MAX_DELAY_HOURS = 720  # 30 days
DAY_STEP_HOURS = 24    # from here on WhatsApp only allows an approved template
DAY_STEP_MESSAGE = "After 24 hours WhatsApp only allows an approved template. Pick one."


def _validate_step_fields(
    delay_hours: int,
    message_type: str,
    target_sources: list[str] | None,
    *,
    db=None,
    tenant_id: str | None = None,
    template_name: str | None = None,
) -> None:
    if message_type not in ("freeform", "template"):
        raise HTTPException(status_code=400, detail="Invalid message type")
    if delay_hours <= 0:
        raise HTTPException(status_code=400, detail="delay_hours must be positive")
    if delay_hours > MAX_DELAY_HOURS:
        raise HTTPException(status_code=400, detail="A follow-up can wait at most 30 days (720 hours)")
    if target_sources and not set(target_sources).issubset(VALID_SOURCES):
        raise HTTPException(status_code=400, detail="Invalid source in target_sources")
    if delay_hours >= DAY_STEP_HOURS:
        # Past the 24-hour window only an approved template may go out.
        if message_type != "template" or not (template_name or "").strip():
            raise HTTPException(status_code=400, detail=DAY_STEP_MESSAGE)
        if db is not None and tenant_id and template_status(db, tenant_id, template_name.strip()) != "APPROVED":
            raise HTTPException(status_code=400, detail=DAY_STEP_MESSAGE)


GROUP_NOT_YOURS = "Pick one of your own groups"
GROUP_COLUMN_MISSING = "Sending a follow-up to one group is not switched on yet"


def _check_group(db, tenant_id: str, group_id: str | None) -> str | None:
    """The group id when it is one of this tenant's groups, else a 400. None stays None."""
    if not group_id:
        return None
    try:
        gid = str(UUID(str(group_id)))
    except ValueError:
        raise HTTPException(status_code=400, detail=GROUP_NOT_YOURS)
    rows = (db.table("customer_groups").select("id").eq("id", gid).eq("tenant_id", tenant_id)
            .limit(1).execute()).data or []
    if not rows:
        raise HTTPException(status_code=400, detail=GROUP_NOT_YOURS)
    return gid


@router.post("/steps")
def create_step(
    payload: ReengagementStepCreate,
    ctx: dict = Depends(require_leads_manage),
):
    if payload.type not in ("broadcast", "inbound"):
        raise HTTPException(status_code=400, detail="Invalid step type")
    if payload.type == "broadcast" and not payload.broadcast_id:
        raise HTTPException(status_code=400, detail="broadcast_id is required for broadcast steps")
    db = get_supabase()
    _validate_step_fields(
        payload.delay_hours, payload.message_type, payload.target_sources,
        db=db, tenant_id=ctx["tenant_id"], template_name=payload.template_name,
    )
    row = {
        "tenant_id": ctx["tenant_id"],
        "type": payload.type,
        "broadcast_id": payload.broadcast_id,
        "delay_hours": payload.delay_hours,
        "target_segments": payload.target_segments,
        "target_sources": payload.target_sources or None,
        "message_type": payload.message_type,
        "message_content": payload.message_content,
        "template_name": payload.template_name,
        "template_variables": payload.template_variables,
        "fallback_template_name": payload.fallback_template_name,
        "fallback_template_variables": payload.fallback_template_variables,
    }
    group_id = _check_group(db, ctx["tenant_id"], payload.target_group_id)
    if group_id:
        row["target_group_id"] = group_id  # only sent when set, so a database without the column behaves as before
    try:
        res = db.table("reengagement_steps").insert(row).execute()
    except Exception as e:
        if group_id and "target_group_id" in str(e):
            raise HTTPException(status_code=400, detail=GROUP_COLUMN_MISSING)
        raise
    return res.data[0] if res.data else {}


@router.patch("/steps/{step_id}")
def update_step(
    step_id: str,
    payload: ReengagementStepUpdate,
    ctx: dict = Depends(require_leads_manage),
):
    db = get_supabase()
    _validate_step_fields(
        payload.delay_hours, payload.message_type, payload.target_sources,
        db=db, tenant_id=ctx["tenant_id"], template_name=payload.template_name,
    )
    row = {
        "delay_hours": payload.delay_hours,
        "target_segments": payload.target_segments,
        "target_sources": payload.target_sources or None,
        "message_type": payload.message_type,
        "message_content": payload.message_content,
        "template_name": payload.template_name,
        "template_variables": payload.template_variables,
        "fallback_template_name": payload.fallback_template_name,
        "fallback_template_variables": payload.fallback_template_variables,
    }
    sets_group = "target_group_id" in payload.model_fields_set
    group_id = _check_group(db, ctx["tenant_id"], payload.target_group_id) if sets_group else None
    if sets_group and (group_id or payload.target_group_id is None):
        row["target_group_id"] = group_id
    try:
        result = (
            db.table("reengagement_steps")
            .update(row)
            .eq("id", step_id)
            .eq("tenant_id", ctx["tenant_id"])
            .execute()
        )
    except Exception as e:
        if "target_group_id" not in row or "target_group_id" not in str(e):
            raise
        if group_id:
            raise HTTPException(status_code=400, detail=GROUP_COLUMN_MISSING)
        # "Everybody" asked on a database without the column: nothing to clear, save the rest.
        row.pop("target_group_id")
        result = (db.table("reengagement_steps").update(row).eq("id", step_id)
                  .eq("tenant_id", ctx["tenant_id"]).execute())
    if not result.data:
        raise HTTPException(status_code=404, detail="Step not found")
    return result.data[0]


@router.get("/logs")
def list_logs(
    step_id: str | None = None,
    ctx: dict = Depends(require_leads_view),
):
    db = get_supabase()

    def _read(columns: str):
        q = db.table("reengagement_logs").select(columns).eq("tenant_id", ctx["tenant_id"])
        if step_id:
            q = q.eq("step_id", step_id)
        return q.order("sent_at", desc=True).limit(500).execute()

    try:
        rows = _read("id, step_id, lead_id, status, reason, sent_at, leads(name, phone, segment)")
    except Exception as e:
        # Migration 311 (the reason column) may not be applied yet.
        logger.warning(f"reengagement logs: reading without reason ({e})")
        rows = _read("id, step_id, lead_id, status, sent_at, leads(name, phone, segment)")
    return {"data": rows.data or []}


@router.post("/trigger-now")
async def trigger_now(ctx: dict = Depends(require_leads_manage)):
    from app.services.reengagement_service import process_due_reengagements
    fired = await process_due_reengagements()
    return {"fired": fired}


@router.delete("/steps/{step_id}")
def delete_step(
    step_id: str,
    ctx: dict = Depends(require_leads_manage),
):
    db = get_supabase()
    result = db.table("reengagement_steps").delete().eq("id", step_id).eq("tenant_id", ctx["tenant_id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Step not found")
    return {"success": True}
