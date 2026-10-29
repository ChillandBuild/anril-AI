"""Lead page: Send details on WhatsApp (call wrap-up v2 spec §5)."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role, require_any_permission
from app.services import scheduled_templates
from app.services.call_details_share import ShareError, send_details, share_context

router = APIRouter()

# Changing a scheduled message needs the same right as sending one, from either place it can be made.
require_schedule_manage = require_any_permission("telecalling.dialer", "conversations.reply", "leads.manage")


def require_share_permission(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    permissions = set(ctx.get("permissions") or [])
    if ctx.get("role") == "owner" or permissions & {"telecalling.dialer", "conversations.reply"}:
        return ctx
    raise HTTPException(status_code=403, detail="Permission required: telecalling.dialer")


class SendDetailsIn(BaseModel):
    text: str | None = Field(None, max_length=4096)
    template_id: str | None = Field(None, max_length=64)
    variables: list[str] = Field(default_factory=list, max_length=20)


@router.get("/{lead_id}/send-details")
def get_send_details(lead_id: UUID, ctx: dict = Depends(require_share_permission)):
    context = share_context(get_supabase(), ctx["tenant_id"], str(lead_id), now=datetime.now(timezone.utc))
    if context is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return context


@router.post("/{lead_id}/send-details")
async def post_send_details(lead_id: UUID, payload: SendDetailsIn, ctx: dict = Depends(require_share_permission)):
    if (payload.text is None) == (payload.template_id is None):
        raise HTTPException(status_code=400, detail="Send either a message or a template")
    try:
        return await send_details(
            get_supabase(), ctx["tenant_id"], str(lead_id), text=payload.text, template_id=payload.template_id,
            variables=payload.variables, now=datetime.now(timezone.utc),
        )
    except ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------- scheduled templates

class ScheduleIn(BaseModel):
    template_id: str = Field(..., max_length=64)
    variables: list[str] = Field(default_factory=list, max_length=20)
    send_at: datetime
    # Set by Leads when it schedules the same template for several leads at once, so the Scheduled
    # templates page can show them as one batch.
    batch_id: UUID | None = None
    batch_label: str | None = Field(None, max_length=80)


class RescheduleIn(BaseModel):
    send_at: datetime


def _scheduled(action, *args, **kwargs):
    """Runs a scheduled_templates call and turns its refusals into 404 / 400."""
    try:
        return action(*args, **kwargs)
    except scheduled_templates.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{lead_id}/scheduled-templates")
def list_scheduled_templates(lead_id: UUID, ctx: dict = Depends(require_share_permission)):
    return {"items": scheduled_templates.list_for_lead(get_supabase(), ctx["tenant_id"], str(lead_id))}


@router.post("/{lead_id}/scheduled-templates")
def create_scheduled_template(lead_id: UUID, payload: ScheduleIn, ctx: dict = Depends(require_share_permission)):
    return _scheduled(
        scheduled_templates.schedule_template, get_supabase(), ctx["tenant_id"], ctx.get("user_id"), str(lead_id),
        payload.template_id, payload.variables, payload.send_at,
        batch_id=str(payload.batch_id) if payload.batch_id else None, batch_label=payload.batch_label,
    )


@router.patch("/scheduled-templates/{schedule_id}")
def reschedule_template(schedule_id: UUID, payload: RescheduleIn, ctx: dict = Depends(require_schedule_manage)):
    return _scheduled(scheduled_templates.reschedule, get_supabase(), ctx["tenant_id"], str(schedule_id), payload.send_at)


@router.post("/scheduled-templates/{schedule_id}/cancel")
def cancel_scheduled_template(schedule_id: UUID, ctx: dict = Depends(require_schedule_manage)):
    return _scheduled(scheduled_templates.cancel, get_supabase(), ctx["tenant_id"], str(schedule_id))


@router.post("/scheduled-templates/{schedule_id}/restore")
def restore_scheduled_template(schedule_id: UUID, ctx: dict = Depends(require_schedule_manage)):
    return _scheduled(scheduled_templates.restore, get_supabase(), ctx["tenant_id"], str(schedule_id))
