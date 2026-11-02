"""The Scheduled templates page: list, change in bulk, and download a broadcast's file."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, get_tenant_and_role
from app.services import scheduled_overview as overview
from app.services import scheduled_templates
from app.services.call_details_share import ShareError

router = APIRouter()

# Templates: the same rights that schedule or change one from a chat. Broadcasts: the Outbound Leads rights.
_TEMPLATE_PERMISSIONS = ("telecalling.dialer", "conversations.reply", "leads.manage")


def _can_templates(ctx: dict) -> bool:
    return any(_has_permission(ctx, p) for p in _TEMPLATE_PERMISSIONS)


def _can_see_broadcasts(ctx: dict) -> bool:
    return _has_permission(ctx, "outbound_leads.view")


def _can_change_broadcasts(ctx: dict) -> bool:
    return _has_permission(ctx, "outbound_leads.manage")


def _caller_id(ctx: dict) -> str | None:
    """A caller sees and changes only messages for leads assigned to them, as on the Leads page."""
    return ctx["caller_id"] if ctx.get("role") == "caller" and ctx.get("caller_id") else None


def require_overview(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    if _can_templates(ctx) or _can_see_broadcasts(ctx):
        return ctx
    raise HTTPException(status_code=403, detail="Permission required: leads.manage or outbound_leads.view")


class BulkIn(BaseModel):
    action: str = Field(..., pattern="^(cancel|restore|reschedule)$")
    template_ids: list[UUID] = Field(default_factory=list, max_length=500)
    broadcast_ids: list[UUID] = Field(default_factory=list, max_length=100)
    send_at: datetime | None = None


@router.get("")
def get_overview(ctx: dict = Depends(require_overview)):
    now = datetime.now(timezone.utc)
    db, tenant_id = get_supabase(), ctx["tenant_id"]
    see_templates, see_broadcasts = _can_templates(ctx), _can_see_broadcasts(ctx)
    return {
        "templates": overview.list_templates(db, tenant_id, now, _caller_id(ctx)) if see_templates else [],
        "broadcasts": overview.list_broadcasts(db, tenant_id, now) if see_broadcasts else [],
        "can_change_templates": see_templates,
        "can_change_broadcasts": _can_change_broadcasts(ctx),
    }


@router.post("/bulk")
def bulk(payload: BulkIn, ctx: dict = Depends(require_overview)):
    if not (payload.template_ids or payload.broadcast_ids):
        raise HTTPException(status_code=400, detail="Pick at least one message.")
    try:
        return overview.apply_bulk(
            get_supabase(), ctx["tenant_id"], payload.action, [str(i) for i in payload.template_ids],
            [str(i) for i in payload.broadcast_ids], payload.send_at, _can_templates(ctx), _can_change_broadcasts(ctx),
            datetime.now(timezone.utc), _caller_id(ctx),
        )
    except ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/broadcasts/{broadcast_id}/file")
def broadcast_file(broadcast_id: UUID, ctx: dict = Depends(require_overview)):
    if not _can_see_broadcasts(ctx):
        raise HTTPException(status_code=403, detail="Permission required: outbound_leads.view")
    try:
        return overview.file_link(get_supabase(), ctx["tenant_id"], str(broadcast_id))
    except scheduled_templates.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))
