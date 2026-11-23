"""Anril AI (the client connector) as the dashboard sees it: the consent screen's questions,
Allow, the Settings page, the owner's off switch and the daily sending cap.

These are the dashboard's own endpoints, called with a normal dashboard login. The connector's
tools never call them. Spec: docs/specs/anril-client-mcp.md.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.db.supabase import get_supabase
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import require_owner
from app.services import client_claude
from app.services.audit_log import record_audit_event

logger = logging.getLogger(__name__)

router = APIRouter()

_RECENT = 10


def _public_url() -> str:
    from app.client_mcp.server import public_url  # imported here: the MCP package loads only when used

    return public_url()


@router.get("/consent-app")
def consent_app(authorization_id: str = Query(min_length=1, max_length=200)):
    """Which connector is this consent request for, before anyone has signed in to it?

    Supabase stamps a request with whichever login opens it first, and the consent page can hold two
    logins (the operator's and a client owner's). So it asks here first, then opens the request with
    the right one. Needs no login and says only "admin", "client" or "unknown": never an app id.
    """
    try:
        found = get_supabase().rpc("claude_authorization_client", {"p_authorization_id": authorization_id}).execute()
    except Exception:
        logger.exception("Consent app lookup failed")
        raise HTTPException(status_code=503, detail="Could not check this request")
    app_id = str(found.data) if found and found.data else ""
    if not app_id:
        return {"kind": "unknown"}
    if settings.mcp_oauth_client_id and app_id == settings.mcp_oauth_client_id:
        return {"kind": "admin"}
    if app_id in client_claude.approved_client_ids():
        return {"kind": "client"}
    return {"kind": "unknown"}


@router.get("/consent")
def consent_question(client_id: str, user: dict = Depends(get_current_user)):
    """The consent screen asks: which connector is this app, and may this login allow it?
    kind is "admin" (Prem's Operator connector), "client" (Anril AI) or "unknown"."""
    if settings.mcp_oauth_client_id and client_id == settings.mcp_oauth_client_id:
        return {"kind": "admin"}
    if client_id not in client_claude.approved_client_ids():
        return {"kind": "unknown"}
    db = get_supabase()
    seat, why = client_claude.owner_seat(db, user["user_id"])
    if not seat:
        return {"kind": "client", "can_allow": False, "why": client_claude.REFUSALS[why]}
    connection = client_claude.find_active(db, seat["tenant_id"], user["user_id"], client_id)
    return {
        "kind": "client", "can_allow": True, "business": seat["tenant_name"],
        "daily_cap": client_claude.daily_cap(db, seat["tenant_id"]),
        "connected": bool(connection),
    }


class AllowBody(BaseModel):
    client_id: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=80)


@router.post("/allow")
def allow(body: AllowBody, user: dict = Depends(get_current_user)):
    """Called by the consent screen when the owner clicks Allow, before the OAuth approval.
    Only an approved client app can be allowed, and only by the owner of a client that has the
    connector switched on: anything else is refused here, before Supabase is told anything."""
    if body.client_id not in client_claude.approved_client_ids():
        raise HTTPException(status_code=400, detail="This app is not an approved Anril AI connector")
    db = get_supabase()
    seat, why = client_claude.owner_seat(db, user["user_id"])
    if not seat:
        raise HTTPException(status_code=403, detail=client_claude.REFUSALS[why])
    row = client_claude.activate(db, seat["tenant_id"], user["user_id"], body.client_id, body.label)
    record_audit_event(
        db, tenant_id=seat["tenant_id"], actor_user_id=user["user_id"], actor_role="owner",
        action="claude.connection.allow", target_type="claude_connection", target_id=row.get("id"),
        metadata={"app": body.client_id, "label": row.get("label")},
    )
    return {"connection": row}


@router.get("")
def status(ctx: dict = Depends(require_owner)):
    """What Settings → Anril AI shows: whether it is switched on for this client, the address
    and app id to paste into Claude, who is connected, today's sending count and the cap, and
    the last few things done through it."""
    db, tenant_id = get_supabase(), ctx["tenant_id"]
    tenant = (db.table("tenants").select("enabled_features").eq("id", tenant_id).limit(1).execute().data or [{}])[0]
    apps = sorted(client_claude.approved_client_ids())
    recent = (
        db.table("app_audit_logs").select("id, action, target_id, metadata, created_at")
        .eq("tenant_id", tenant_id).like("action", "claude.%")
        .order("created_at", desc=True).limit(_RECENT * 3).execute()
    ).data or []
    return {
        "available": bool(settings.mcp_client_enabled and apps and client_claude.FEATURE in (tenant.get("enabled_features") or [])),
        "mcp_url": _public_url(),
        "oauth_client_id": apps[0] if apps else None,
        "connections": client_claude.for_tenant(db, tenant_id),
        "daily_cap": client_claude.daily_cap(db, tenant_id),
        "max_daily_cap": client_claude.MAX_DAILY_CAP,
        "sent_today": client_claude.sent_today(db, tenant_id),
        "recent": [
            {
                "id": r["id"], "created_at": r.get("created_at"), "action": r.get("action"), "tool": r.get("target_id"),
                "ok": (r.get("metadata") or {}).get("ok"), "arguments": (r.get("metadata") or {}).get("arguments") or {},
            }
            for r in recent if (r.get("metadata") or {}).get("stage") != "started"
        ][:_RECENT],
    }


@router.post("/revoke")
def revoke(ctx: dict = Depends(require_owner)):
    """The owner's off switch. The very next tool call is refused."""
    db = get_supabase()
    revoked = client_claude.revoke_all(db, ctx["tenant_id"])
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role="owner",
        action="claude.connection.revoke", target_type="claude_connection", target_id=None,
        metadata={"revoked": revoked},
    )
    return {"revoked": revoked, "connections": client_claude.for_tenant(db, ctx["tenant_id"])}


class CapBody(BaseModel):
    daily_cap: int = Field(ge=0, le=client_claude.MAX_DAILY_CAP)


@router.put("/cap")
def set_cap(body: CapBody, ctx: dict = Depends(require_owner)):
    """How many customer messages Anril AI may send for this client per day. 0 stops all sending."""
    db = get_supabase()
    before = client_claude.daily_cap(db, ctx["tenant_id"])
    cap = client_claude.set_daily_cap(db, ctx["tenant_id"], body.daily_cap)
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role="owner",
        action="claude.cap.change", target_type="claude_connection", target_id=None,
        metadata={"from": before, "to": cap},
    )
    return {"daily_cap": cap}
