"""v9.2 #80 "Let the Anril team do it" (first setup, catalogue step).

/api/v1/setup-help/...           the business asks (same permission as first setup: settings.manage)
/api/v1/operator/setup-help-requests/...   the Anril team reads and closes requests (system admins only)"""
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin
from app.dependencies.tenant import require_permission
from app.services import setup_help
from app.services.audit_log import record_audit_event

logger = logging.getLogger(__name__)
router = APIRouter()
operator_router = APIRouter()
require_settings_manage = require_permission("settings.manage")

NOT_READY = "This isn't ready yet. Please try again in a little while."


def _requested(row: dict | None) -> dict:
    return {"requested": bool(row), "requested_at": row.get("created_at") if row else None}


@router.get("/catalogue")
def catalogue_status(ctx: dict = Depends(require_settings_manage)):
    try:
        return _requested(setup_help.open_request(get_supabase(), ctx["tenant_id"], "catalogue"))
    except setup_help.SetupHelpNotReady:
        return _requested(None)  # nothing could have been requested yet


@router.post("/catalogue")
def catalogue_request(ctx: dict = Depends(require_settings_manage)):
    try:
        row = setup_help.request_help(get_supabase(), ctx["tenant_id"], ctx.get("user_id"), "catalogue")
    except setup_help.SetupHelpNotReady:
        raise HTTPException(status_code=503, detail=NOT_READY)
    return {"requested": True, "requested_at": row.get("created_at")}


@operator_router.get("/setup-help-requests")
def list_requests(_admin: dict = Depends(get_system_admin)):
    return {"items": setup_help.list_open(get_supabase())}


class DoneIn(BaseModel):
    status: Literal["done", "cancelled"] = "done"


@operator_router.post("/setup-help-requests/{request_id}/done")
def finish_request(request_id: str, body: DoneIn, admin: dict = Depends(get_system_admin)):
    try:
        rid = str(UUID(request_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Request not found")
    db = get_supabase()
    row = setup_help.finish(db, rid, admin.get("user_id"), body.status)
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    record_audit_event(db, tenant_id=row["tenant_id"], actor_user_id=admin.get("user_id"), actor_role="system_admin",
                       action=f"operator.setup_help_{row['status']}", target_type="tenant", target_id=row["tenant_id"], metadata={})
    return {"ok": True}
