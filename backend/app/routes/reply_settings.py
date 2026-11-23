"""v9.2 #157 Replies and handover settings: the after-hours message.
View = settings.view, edit = settings.manage (same as the other Settings pages)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import after_hours

router = APIRouter()
require_settings_read = require_permission("settings.view")
require_settings_manage = require_permission("settings.manage")


class AfterHoursIn(BaseModel):
    enabled: bool = False
    open: str = Field("09:00", max_length=5)
    close: str = Field("21:00", max_length=5)
    message: str = Field("", max_length=2000)


@router.get("/after-hours")
def get_after_hours(ctx: dict = Depends(require_settings_read)):
    return {**after_hours.read(get_supabase(), ctx["tenant_id"]), "max_chars": after_hours.MAX_MESSAGE}


@router.put("/after-hours")
def put_after_hours(body: AfterHoursIn, ctx: dict = Depends(require_settings_manage)):
    try:
        cfg = after_hours.save(get_supabase(), ctx["tenant_id"], body.model_dump())
    except after_hours.AfterHoursError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {**cfg, "max_chars": after_hours.MAX_MESSAGE}
