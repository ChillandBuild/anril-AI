"""Operator Console → MCP: the admin connector (see, allow, switch off) and each client's connector.

System admins only. These are the Console's own endpoints; the MCP tools never call them.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin
from app.services import client_claude, mcp_connections
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


# ── the client connectors (one switch per client) ─────────────────────────────

def _client_public_url() -> str:
    from app.client_mcp.server import public_url  # imported here: the MCP package loads only when used

    return public_url()


def _rows(result) -> list[dict]:
    # The real database library can answer None; read through it, like client_claude does.
    return (result.data if result else None) or []


def _clamped_cap(value) -> int:
    """Same clamp as client_claude.daily_cap, applied to a value already read."""
    try:
        return max(0, min(int(value), client_claude.MAX_DAILY_CAP))
    except (TypeError, ValueError):
        return client_claude.DEFAULT_DAILY_CAP


def _connection_facts(rows: list[dict]) -> dict[str, dict]:
    """tenant_id -> {connected_at, last_used_at} from the active connection rows."""
    facts: dict[str, dict] = {}
    for row in rows:
        fact = facts.setdefault(str(row["tenant_id"]), {"connected_at": None, "last_used_at": None})
        for field in ("connected_at", "last_used_at"):
            value = row.get("created_at" if field == "connected_at" else field)
            if value and (fact[field] is None or value > fact[field]):
                fact[field] = value
    return facts


@router.get("/mcp/clients")
def mcp_clients(_admin: dict = Depends(get_system_admin)):
    """Every client with its connector switch, connection state, today's sends and cap.
    Four queries in all, joined here, so the list stays one round trip however many clients."""
    db = get_supabase()
    tenants = _rows(db.table("tenants").select("id, name, status, enabled_features").execute())
    active = _rows(
        db.table(client_claude.TABLE).select("tenant_id, created_at, last_used_at").eq("status", "active").execute()
    )
    sent = _rows(db.table("claude_send_days").select("tenant_id, sent").eq("day", client_claude.ist_day()).execute())
    caps = _rows(db.table("app_settings").select("tenant_id, value").eq("key", client_claude.CAP_KEY).execute())
    facts = _connection_facts(active)
    sent_by = {str(r["tenant_id"]): int(r["sent"] or 0) for r in sent}
    cap_by = {str(r["tenant_id"]): _clamped_cap(r.get("value")) for r in caps}
    clients = []
    for t in sorted(tenants, key=lambda t: (t.get("name") or "").lower()):
        tid = str(t["id"])
        fact = facts.get(tid)
        clients.append({
            "tenant_id": tid,
            "name": t.get("name") or "",
            "status": t.get("status"),
            "on": client_claude.FEATURE in (t.get("enabled_features") or []),
            "connected": fact is not None,
            "connected_at": fact["connected_at"] if fact else None,
            "last_used_at": fact["last_used_at"] if fact else None,
            "sent_today": sent_by.get(tid, 0),
            "daily_cap": cap_by.get(tid, client_claude.DEFAULT_DAILY_CAP),
        })
    return {
        "enabled": settings.mcp_client_enabled,
        "mcp_url": _client_public_url(),
        "default_daily_cap": client_claude.DEFAULT_DAILY_CAP,
        "clients": clients,
    }


class ClientSwitchBody(BaseModel):
    on: bool


@router.put("/mcp/clients/{tenant_id}")
def switch_client_connector(tenant_id: str, body: ClientSwitchBody, admin: dict = Depends(get_system_admin)):
    """Switch one client's connector on or off. Touches only the "claude" feature key, so it cannot
    wipe the other features the way PATCH /clients/{id}/features (which replaces the list) can.
    Off needs no connection revoked: the connector re-checks the key on every request."""
    db = get_supabase()
    rows = _rows(db.table("tenants").select("id, enabled_features").eq("id", tenant_id).limit(1).execute())
    if not rows:
        raise HTTPException(status_code=404, detail="Tenant not found")
    current = list(rows[0].get("enabled_features") or [])
    if body.on:
        features = current if client_claude.FEATURE in current else current + [client_claude.FEATURE]
    else:
        features = [f for f in current if f != client_claude.FEATURE]
    if features != current:
        db.table("tenants").update({"enabled_features": features}).eq("id", tenant_id).execute()
        record_audit_event(
            db, tenant_id=tenant_id, actor_user_id=admin.get("user_id"), actor_role="system_admin",
            action="operator.features_updated", target_type="tenant", target_id=tenant_id,
            metadata={"features": features, "changed": {client_claude.FEATURE: body.on}},
        )
    return {"tenant_id": tenant_id, "on": body.on}
