"""v9.2 #157 Replies and handover settings: the after-hours message. v9.2 #59/#92: the shop's open hours.
View = settings.view, edit = settings.manage (same as the other Settings pages)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import after_hours, open_hours

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


class OpenHoursIn(BaseModel):
    # {"0": [["10:00", "20:00"]], ...}; 0 = Monday, a day left out is closed. Checked in open_hours.validate.
    hours: dict[str, list[list[str]]] = Field(default_factory=dict)
    national_holidays: bool = True


def _open_hours_out(cfg: dict) -> dict:
    return {**cfg, "summary": open_hours.summary(cfg),
            "status": open_hours.status_line(cfg) if cfg.get("set") else ""}


@router.get("/open-hours")
def get_open_hours(ctx: dict = Depends(require_settings_read)):
    return _open_hours_out(open_hours.read(get_supabase(), ctx["tenant_id"]))


@router.put("/open-hours")
def put_open_hours(body: OpenHoursIn, ctx: dict = Depends(require_settings_manage)):
    if len(body.hours) > 7 or any(len(v) > 2 for v in body.hours.values()):
        raise HTTPException(status_code=422, detail="Use at most 2 time blocks a day")
    try:
        cfg = open_hours.save(get_supabase(), ctx["tenant_id"], body.model_dump())
    except open_hours.OpenHoursError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return _open_hours_out(cfg)
