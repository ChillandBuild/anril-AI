"""Settings > Connections: Meta's charges and limits, how the team calls, and the Reach weekly number
(read by everyone who can see Settings, saved only by settings.manage)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import require_any_permission, require_permission
from app.services.audit_log import record_audit_event
from app.services import calling_overview, meta_charges, reach_audience

# Plain `def` handlers: FastAPI runs them in a threadpool, so the blocking Supabase and Meta
# calls never stall the event loop.

router = APIRouter()

_SETTINGS_VIEW = require_any_permission("settings.view", "settings.manage")
_SETTINGS_MANAGE = require_permission("settings.manage")


class ReachLimitUpdate(BaseModel):
    weekly_limit: int = Field(ge=reach_audience.MIN_WEEKLY_LIMIT, le=reach_audience.MAX_WEEKLY_LIMIT)


@router.get("/meta-charges")
def get_meta_charges(ctx: dict = Depends(_SETTINGS_VIEW)):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    return {
        "charges": meta_charges.get_charges(tenant_id),
        "ai_replies": meta_charges.ai_replies(db, tenant_id),
        "daily_limit": meta_charges.daily_limit(db, tenant_id),
    }


@router.get("/calling")
def get_calling(ctx: dict = Depends(_SETTINGS_VIEW)):
    return calling_overview.overview(get_supabase(), ctx["tenant_id"])


@router.get("/reach-limit")
def get_reach_limit(ctx: dict = Depends(_SETTINGS_VIEW)):
    return {
        "weekly_limit": reach_audience.weekly_limit(get_supabase(), ctx["tenant_id"]),
        "default": reach_audience.DEFAULT_WEEKLY_LIMIT,
        "min": reach_audience.MIN_WEEKLY_LIMIT,
        "max": reach_audience.MAX_WEEKLY_LIMIT,
    }


@router.put("/reach-limit")
def put_reach_limit(body: ReachLimitUpdate, ctx: dict = Depends(_SETTINGS_MANAGE), user: dict = Depends(get_current_user)):
    db = get_supabase()
    saved = reach_audience.save_weekly_limit(db, ctx["tenant_id"], body.weekly_limit)
    record_audit_event(
        db,
        tenant_id=ctx["tenant_id"],
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.updated",
        target_type="app_settings",
        target_id=ctx["tenant_id"],
        metadata={"updated_keys": ["reach_weekly_limit"]},
    )
    return {"weekly_limit": saved}
