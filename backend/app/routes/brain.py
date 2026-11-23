"""Anril Brain for the client dashboard: GET /api/v1/brain and GET /api/v1/brain/count
(services/brain). Read-only; both need brain.view."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase

from app.dependencies.tenant import require_permission
from app.services.brain import brain_count, build_brain

router = APIRouter()
require_read = require_permission("brain.view")
require_settings = require_permission("settings.manage")


@router.get("")
def get_brain(ctx: dict = Depends(require_read)):
    return build_brain(ctx["tenant_id"], role=ctx.get("role"), permissions=ctx.get("permissions") or [])


@router.get("/count")
def get_count(ctx: dict = Depends(require_read)):
    return brain_count(ctx["tenant_id"])


@router.get("/overview")
def get_overview(ctx: dict = Depends(require_read)):
    """The top of Anril Brain: knows-%, who the AI agent is, goals, Never do, recent changes."""
    from app.services import brain_overview
    return brain_overview.overview(get_supabase(), ctx["tenant_id"])


class GoalsIn(BaseModel):
    goals: list[str] = Field(default_factory=list, max_length=4)


@router.put("/goals")
def put_goals(body: GoalsIn, ctx: dict = Depends(require_settings)):
    """Goal of every chat: one or two, in order. The AI agent reads it from the next message."""
    from app.services import brain_overview
    try:
        return {"goals": brain_overview.save_goals(ctx["tenant_id"], body.goals)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
