"""Anril AI, the client connector (docs/specs/anril-client-mcp.md): who may use it, the owner's
connection (table tenant_mcp_connections) and the daily sending cap (table claude_send_days).
Migration 303."""
from datetime import datetime, timedelta, timezone

from app.config import settings

FEATURE = "claude"                 # the tenants.enabled_features key the operator switches on
CAP_KEY = "claude_daily_send_cap"  # app_settings, per client; the owner can change it
DEFAULT_DAILY_CAP = 500
MAX_DAILY_CAP = 10_000
TABLE = "tenant_mcp_connections"
_COLUMNS = "id, tenant_id, user_id, client_id, label, status, created_at, last_used_at, revoked_at"
_IST = timezone(timedelta(hours=5, minutes=30))

# Why a login cannot use the connector -> what the person is told.
REFUSALS = {
    "no_client": "This login does not belong to an Anril client.",
    "many_clients": "This login belongs to more than one client, which Anril AI does not support yet.",
    "not_owner": "Only the owner of the account can connect Anril AI.",
    "suspended": "This account is suspended.",
    "not_enabled": "Anril AI is not switched on for this account. Ask your Anril account manager.",
}


class CapReached(Exception):
    """Sending `wanted` more messages would pass today's cap."""

    def __init__(self, cap: int, sent: int, wanted: int) -> None:
        super().__init__(f"daily cap {cap} reached ({sent} sent, {wanted} wanted)")
        self.cap, self.sent, self.wanted = cap, sent, wanted


def _rows(result) -> list[dict]:
    return (result.data if result else None) or []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approved_client_ids() -> frozenset[str]:
    """The OAuth apps allowed at /client/mcp. The admin app is never one of them."""
    ids = {part.strip() for part in (settings.mcp_client_oauth_client_ids or "").split(",") if part.strip()}
    ids.discard(settings.mcp_oauth_client_id or "")
    return frozenset(ids)


def owner_seat(db, user_id: str) -> tuple[dict | None, str | None]:
    """(seat, None) when this login is the owner of exactly one client that is active and has
    the connector switched on; otherwise (None, a REFUSALS key)."""
    memberships = _rows(db.table("tenant_users").select("tenant_id, role").eq("user_id", user_id).limit(2).execute())
    if not memberships:
        return None, "no_client"
    if len(memberships) > 1:
        return None, "many_clients"
    if memberships[0].get("role") != "owner":
        return None, "not_owner"
    tenant_id = str(memberships[0]["tenant_id"])
    tenants = _rows(
        db.table("tenants").select("id, name, status, enabled_features").eq("id", tenant_id).limit(1).execute()
    )
    if not tenants:
        return None, "no_client"
    if tenants[0].get("status") == "suspended":
        return None, "suspended"
    if FEATURE not in (tenants[0].get("enabled_features") or []):
        return None, "not_enabled"
    return {"tenant_id": tenant_id, "tenant_name": tenants[0].get("name") or "", "user_id": str(user_id)}, None


# ── the owner's connection ────────────────────────────────────────────────────

def find_active(db, tenant_id: str, user_id: str, client_id: str) -> dict | None:
    rows = _rows(
        db.table(TABLE).select(_COLUMNS)
        .eq("tenant_id", tenant_id).eq("user_id", user_id).eq("client_id", client_id).eq("status", "active")
        .limit(1).execute()
    )
    return rows[0] if rows else None


def for_tenant(db, tenant_id: str) -> list[dict]:
    """This client's connections, newest first (the Settings page lists them)."""
    return _rows(
        db.table(TABLE).select(_COLUMNS).eq("tenant_id", tenant_id).order("created_at", desc=True).limit(20).execute()
    )


def activate(db, tenant_id: str, user_id: str, client_id: str, label: str | None) -> dict:
    rows = _rows(
        db.table(TABLE).upsert(
            {
                "tenant_id": tenant_id, "user_id": user_id, "client_id": client_id,
                "label": (label or "Claude app")[:80], "status": "active", "revoked_at": None,
            },
            on_conflict="tenant_id,user_id,client_id",
        ).execute()
    )
    if not rows:
        raise RuntimeError("connection was not saved")
    return rows[0]


def revoke_all(db, tenant_id: str) -> int:
    """The owner's off switch: the very next tool call from any app is refused."""
    rows = _rows(
        db.table(TABLE).update({"status": "revoked", "revoked_at": _now()})
        .eq("tenant_id", tenant_id).eq("status", "active").execute()
    )
    return len(rows)


def touch(db, connection_id: str) -> None:
    db.table(TABLE).update({"last_used_at": _now()}).eq("id", connection_id).execute()


# ── the daily sending cap ─────────────────────────────────────────────────────

def ist_day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(_IST).date().isoformat()


def daily_cap(db, tenant_id: str) -> int:
    rows = _rows(
        db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", CAP_KEY).limit(1).execute()
    )
    try:
        cap = int(rows[0]["value"])
    except (IndexError, KeyError, TypeError, ValueError):
        return DEFAULT_DAILY_CAP
    return max(0, min(cap, MAX_DAILY_CAP))


def set_daily_cap(db, tenant_id: str, cap: int) -> int:
    cap = max(0, min(int(cap), MAX_DAILY_CAP))
    db.table("app_settings").upsert(
        {"tenant_id": tenant_id, "key": CAP_KEY, "value": str(cap)}, on_conflict="tenant_id,key",
    ).execute()
    return cap


def sent_today(db, tenant_id: str, now: datetime | None = None) -> int:
    rows = _rows(
        db.table("claude_send_days").select("sent").eq("tenant_id", tenant_id).eq("day", ist_day(now)).limit(1).execute()
    )
    return int(rows[0]["sent"]) if rows else 0


def reserve_sends(db, tenant_id: str, count: int, now: datetime | None = None) -> int:
    """Book `count` customer messages against today's cap BEFORE sending them. Returns the
    day's new total. Raises CapReached, with nothing booked, when they do not fit. The check
    and the add are one database statement (claude_reserve_sends), so two sends at the same
    moment cannot both slip under the cap."""
    if count <= 0:
        raise ValueError("count must be positive")
    cap = daily_cap(db, tenant_id)
    total = db.rpc("claude_reserve_sends", {
        "p_tenant_id": tenant_id, "p_day": ist_day(now), "p_count": count, "p_cap": cap,
    }).execute().data
    if total is None:
        raise CapReached(cap, sent_today(db, tenant_id, now), count)
    return int(total)


def release_sends(db, tenant_id: str, count: int, now: datetime | None = None) -> None:
    """Give back messages that were booked but never left."""
    if count > 0:
        db.rpc("claude_release_sends", {"p_tenant_id": tenant_id, "p_day": ist_day(now), "p_count": count}).execute()
