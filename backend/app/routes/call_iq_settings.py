"""v9.2 #21 Call IQ: leave, per-person SIM/cloud, calling hours and daily limit, break limit, hide numbers. Built by agent I-B."""
import logging
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services.call_teams import assert_caller_in_scope
from app.services import caller_leave, call_rules

logger = logging.getLogger(__name__)
router = APIRouter()

_VIEW = require_permission("settings.view")
_MANAGE = require_permission("settings.manage")
_TEAM_MANAGE = require_permission("team.manage")


class RulesBody(BaseModel):
    calling_hours_on: bool
    calling_start: str
    calling_end: str
    daily_limit_on: bool
    daily_limit: int
    break_limit_minutes: int
    hide_numbers_for_callers: bool


class ModeBody(BaseModel):
    mode: Literal["business_default", "sim", "cloud"]


class LeaveBody(BaseModel):
    from_: date = Field(alias="from")
    to: date
    reason: str | None = Field(default=None, max_length=200)

    model_config = {"populate_by_name": True}


@router.get("/rules")
async def get_rules(ctx: dict = Depends(_VIEW)):
    return call_rules.get_rules(get_supabase(), ctx["tenant_id"])


@router.put("/rules")
async def put_rules(body: RulesBody, ctx: dict = Depends(_MANAGE)):
    raw = body.model_dump()
    problem = call_rules.validate_rules(raw)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    return call_rules.save_rules(get_supabase(), ctx["tenant_id"], raw)


def _own_caller(db, tenant_id: str, caller_id: UUID) -> dict:
    res = (
        db.table("callers").select("id,name").eq("id", str(caller_id)).eq("tenant_id", tenant_id)
        .maybe_single().execute()
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Telecaller not found")
    return res.data


@router.get("/callers")
async def list_callers(ctx: dict = Depends(_VIEW)):
    """Each telecaller with how they call (their own choice and what it means today) and any leave."""
    from app.services.assignment import get_telecalling_config

    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    business = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi")
    today = caller_leave.today_ist()
    try:
        rows = (
            db.table("callers")
            .select("id,name,status,calling_mode,leave_from,leave_to,leave_reason")
            .eq("tenant_id", tenant_id).eq("active", True).order("name").execute()
        ).data or []
    except Exception as e:  # migration 321 not applied yet
        logger.warning("call rules callers list fell back (columns missing?): %s", e)
        rows = (
            db.table("callers").select("id,name,status").eq("tenant_id", tenant_id).eq("active", True)
            .order("name").execute()
        ).data or []
    out = []
    for r in rows:
        mode = r.get("calling_mode") or "business_default"
        provider = "sim_basic" if mode == "sim" else "telecmi" if mode == "cloud" else ("sim_basic" if business == "sim_basic" else "telecmi")
        out.append({
            "id": r["id"],
            "name": r.get("name"),
            "status": r.get("status"),
            "calling_mode": mode,
            "effective_mode": "sim" if provider == "sim_basic" else "cloud",
            "leave_from": r.get("leave_from"),
            "leave_to": r.get("leave_to"),
            "leave_reason": r.get("leave_reason"),
            "on_leave": caller_leave.on_leave(r, today),
        })
    return {"business_mode": "sim" if business == "sim_basic" else "cloud", "callers": out}


@router.put("/callers/{caller_id}/mode")
async def set_mode(caller_id: UUID, body: ModeBody, ctx: dict = Depends(_MANAGE)):
    db = get_supabase()
    _own_caller(db, ctx["tenant_id"], caller_id)
    try:
        db.table("callers").update({"calling_mode": body.mode}).eq("id", str(caller_id)).eq("tenant_id", ctx["tenant_id"]).execute()
    except Exception as e:
        logger.warning("could not save calling mode: %s", e)
        raise HTTPException(status_code=503, detail="This setting is not ready yet. Please try again in a few minutes.")
    return {"caller_id": str(caller_id), "calling_mode": body.mode}


@router.post("/callers/{caller_id}/leave")
async def start_leave(caller_id: UUID, body: LeaveBody, ctx: dict = Depends(_TEAM_MANAGE)):
    if body.to < body.from_:
        raise HTTPException(status_code=422, detail="The last day of leave can't be before the first day.")
    if body.to < caller_leave.today_ist():
        raise HTTPException(status_code=422, detail="That leave has already ended.")
    db = get_supabase()
    _own_caller(db, ctx["tenant_id"], caller_id)
    assert_caller_in_scope(db, ctx, str(caller_id))  # a Team leader: own team only
    try:
        return caller_leave.start_leave(db, ctx["tenant_id"], str(caller_id), body.from_, body.to, body.reason)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("could not start leave: %s", e)
        raise HTTPException(status_code=503, detail="Leave is not ready yet. Please try again in a few minutes.")


@router.delete("/callers/{caller_id}/leave")
async def end_leave(caller_id: UUID, ctx: dict = Depends(_TEAM_MANAGE)):
    db = get_supabase()
    _own_caller(db, ctx["tenant_id"], caller_id)
    assert_caller_in_scope(db, ctx, str(caller_id))  # a Team leader: own team only
    try:
        caller_leave.end_leave(db, ctx["tenant_id"], str(caller_id))
    except Exception as e:
        logger.warning("could not end leave: %s", e)
        raise HTTPException(status_code=503, detail="Leave is not ready yet. Please try again in a few minutes.")
    return {"caller_id": str(caller_id), "on_leave": False}
