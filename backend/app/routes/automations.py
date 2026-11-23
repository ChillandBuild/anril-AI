"""v9.2 #26 Alerts & automations: alert list, quiet time, automation list, evening summary, come-back offer. Built by agent K."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_any_permission, require_permission
from app.services import alert_catalog, automation_list, comeback_offer, evening_summary

logger = logging.getLogger(__name__)
router = APIRouter()

require_settings_read = require_permission("settings.view")
require_settings_manage = require_permission("settings.manage")
require_list_read = require_any_permission("settings.view", "templates.view")
require_toggle = require_any_permission("settings.manage", "templates.manage")


class AlertIn(BaseModel):
    on: bool
    who: list[str] | None = None


class QuietTimeIn(BaseModel):
    on: bool
    start_hour: int = Field(21, ge=0, le=23)
    end_hour: int = Field(9, ge=0, le=23)


class ToggleIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    on: bool


class EveningIn(BaseModel):
    on: bool


class ComebackIn(BaseModel):
    on: bool
    template_name: str | None = Field(None, max_length=120)
    offer: str = Field("", max_length=400)
    code: str = Field("", max_length=60)
    ends_on: str | None = Field(None, max_length=10)


# ───────────────────────────────────────────────────────────── alerts

@router.get("/alerts")
def get_alerts(ctx: dict = Depends(require_settings_read)):
    """Every alert: {key, label, area, who, how, on}, plus the quiet-time setting."""
    return alert_catalog.list_alerts(get_supabase(), ctx["tenant_id"])


@router.put("/alerts/{key}")
def put_alert(key: str, body: AlertIn, ctx: dict = Depends(require_settings_manage)):
    try:
        return alert_catalog.set_alert(get_supabase(), ctx["tenant_id"], key, body.on, body.who)
    except KeyError:
        raise HTTPException(status_code=404, detail="That alert does not exist.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.put("/quiet-time")
def put_quiet_time(body: QuietTimeIn, ctx: dict = Depends(require_settings_manage)):
    try:
        return alert_catalog.set_quiet_time(get_supabase(), ctx["tenant_id"], body.on, body.start_hour, body.end_hour)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ───────────────────────────────────────────────────────────── automations

@router.get("/list")
def get_automation_list(ctx: dict = Depends(require_list_read)):
    """Every automation: {key, name, kind, on, template_name, template_status, paused_reason, href, ...}."""
    items = automation_list.list_automations(get_supabase(), ctx["tenant_id"])
    return {"automations": items, "paused_count": sum(1 for a in items if a["paused"])}


@router.put("/toggle")
def toggle_automation(body: ToggleIn, ctx: dict = Depends(require_toggle)):
    db, tenant_id = get_supabase(), ctx["tenant_id"]
    if body.on:
        # A paused automation is switched back on only after its message is approved again.
        match = next((a for a in automation_list.list_automations(db, tenant_id) if a["key"] == body.key), None)
        if match and match["template_name"] and match["template_status"] != "APPROVED":
            raise HTTPException(status_code=409, detail="This message is not approved by WhatsApp yet.")
    try:
        automation_list.set_automation_on(db, tenant_id, body.key, body.on)
    except automation_list.NotSwitchable:
        raise HTTPException(status_code=422, detail="Switch this one on its own page.")
    except LookupError:
        raise HTTPException(status_code=404, detail="That automation does not exist.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "key": body.key, "on": body.on}


# ───────────────────────────────────────────────────────────── evening summary

@router.get("/evening-summary")
def get_evening_summary(ctx: dict = Depends(require_list_read)):
    return evening_summary.get_settings(get_supabase(), ctx["tenant_id"])


@router.put("/evening-summary")
def put_evening_summary(body: EveningIn, ctx: dict = Depends(require_toggle)):
    return evening_summary.save_on(get_supabase(), ctx["tenant_id"], body.on)


@router.post("/evening-summary/template")
async def submit_evening_template(ctx: dict = Depends(require_settings_manage)):
    """Send the evening-summary message to WhatsApp for approval."""
    return await evening_summary.submit_template(get_supabase(), ctx["tenant_id"])


# ───────────────────────────────────────────────────────────── come-back offer

@router.get("/comeback-offer")
def get_comeback_offer(ctx: dict = Depends(require_list_read)):
    db, tenant_id = get_supabase(), ctx["tenant_id"]
    return {**comeback_offer.get_settings(db, tenant_id), "approved_templates": comeback_offer.approved_templates(db, tenant_id)}


@router.put("/comeback-offer")
def put_comeback_offer(body: ComebackIn, ctx: dict = Depends(require_toggle)):
    db, tenant_id = get_supabase(), ctx["tenant_id"]
    try:
        saved = comeback_offer.save_settings(
            db, tenant_id, on=body.on, template_name=body.template_name, offer=body.offer, code=body.code,
            ends_on=body.ends_on,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {**saved, "approved_templates": comeback_offer.approved_templates(db, tenant_id)}
