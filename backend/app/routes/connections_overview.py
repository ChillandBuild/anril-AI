"""Read-only pages under Settings > Connections: Meta's charges and limits, and how the team calls."""
from fastapi import APIRouter, Depends

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_any_permission
from app.services import calling_overview, meta_charges

# Plain `def` handlers: FastAPI runs them in a threadpool, so the blocking Supabase and Meta
# calls never stall the event loop.

router = APIRouter()

_SETTINGS_VIEW = require_any_permission("settings.view", "settings.manage")


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
