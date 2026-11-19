"""Operator Console → Claude Access: see the connection, allow it, switch it off.

System admins only. These are the Console's own endpoints; the MCP tools never call them.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin
from app.services import mcp_connections
from app.services.audit_log import record_audit_event

router = APIRouter()

_IST = timezone(timedelta(hours=5, minutes=30))
_TOOL_CALL = "mcp.tool_call"


def _ist_midnight_utc(now: datetime | None = None) -> datetime:
    now_ist = (now or datetime.now(timezone.utc)).astimezone(_IST)
    return now_ist.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _public_url() -> str:
    from app.admin_mcp.server import public_url  # imported here: the MCP package loads only when used

    return public_url()


@router.get("/claude-access")
def claude_access(_admin: dict = Depends(get_system_admin)):
    """What the Claude Access page shows: the connection, today's call count, this week's most
    used tool and most read client, and the last three calls."""
    db = get_supabase()
    today = _ist_midnight_utc()
    week = (
        db.table("app_audit_logs")
        .select("id, tenant_id, target_id, metadata, created_at")
        .eq("action", _TOOL_CALL)
        .gte("created_at", (today - timedelta(days=6)).isoformat())
        .order("created_at", desc=True)
        .limit(1000)
        .execute()
    ).data or []
    tenant_ids = list({r["tenant_id"] for r in week if r.get("tenant_id")})
    names: dict[str, str] = {}
    if tenant_ids:
        tenants = db.table("tenants").select("id, name").in_("id", tenant_ids).execute()
        names = {t["id"]: t["name"] for t in (tenants.data or [])}
    tools = Counter(r["target_id"] for r in week if r.get("target_id"))
    clients = Counter(r["tenant_id"] for r in week if r.get("tenant_id"))
    top_client = clients.most_common(1)[0][0] if clients else None
    today_iso = today.isoformat()
    return {
        "enabled": settings.mcp_enabled,
        "mcp_url": _public_url(),
        "connection": mcp_connections.current(db),
        "calls_today": sum(1 for r in week if (r.get("created_at") or "") >= today_iso),
        "top_tool_week": tools.most_common(1)[0][0] if tools else None,
        "top_client_week": names.get(top_client) if top_client else None,
        "recent_calls": [
            {
                "id": r["id"],
                "created_at": r.get("created_at"),
                "tool": r.get("target_id"),
                "tenant_id": r.get("tenant_id"),
                "tenant_name": names.get(r.get("tenant_id") or "", None),
                "arguments": (r.get("metadata") or {}).get("arguments") or {},
            }
            for r in week[:3]
        ],
    }


class AllowBody(BaseModel):
    client_id: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=80)


@router.post("/claude-access/allow")
def allow_claude_access(body: AllowBody, admin: dict = Depends(get_system_admin)):
    """Called by the consent screen when the admin clicks Allow, before the OAuth approval.
    Only the one app registered as Claude (MCP_OAUTH_CLIENT_ID) can be allowed: a look-alike app
    with another id is refused here, before Supabase is told anything."""
    if not settings.mcp_oauth_client_id or body.client_id != settings.mcp_oauth_client_id:
        raise HTTPException(status_code=400, detail="This app is not the registered Claude connector")
    db = get_supabase()
    row = mcp_connections.activate(db, admin["user_id"], body.client_id, body.label)
    record_audit_event(
        db, tenant_id=None, actor_user_id=admin["user_id"], actor_role="system_admin",
        action="mcp.connection.allow", target_type="mcp_connection", target_id=row.get("id"),
        metadata={"client_id": body.client_id, "label": row.get("label")},
    )
    return {"connection": row}


@router.post("/claude-access/revoke")
def revoke_claude_access(admin: dict = Depends(get_system_admin)):
    """The off switch. The very next tool call is refused."""
    db = get_supabase()
    revoked = mcp_connections.revoke_all(db)
    record_audit_event(
        db, tenant_id=None, actor_user_id=admin["user_id"], actor_role="system_admin",
        action="mcp.connection.revoke", target_type="mcp_connection", target_id=None,
        metadata={"revoked": revoked},
    )
    return {"revoked": revoked, "connection": mcp_connections.current(db)}
