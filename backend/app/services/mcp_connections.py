"""Claude Access connections (table mcp_connections, migration 295).

One row per (admin user, OAuth client). A row is created when a system admin clicks Allow on
the consent screen and is the off switch: only an `active` row lets the admin MCP answer.
At most one row is active at a time.
"""
from datetime import datetime, timezone

TABLE = "mcp_connections"
_COLUMNS = "id, user_id, client_id, label, status, created_at, last_used_at, revoked_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(result) -> list[dict]:
    return (result.data if result else None) or []


def find_active(db, user_id: str, client_id: str) -> dict | None:
    rows = _rows(
        db.table(TABLE).select(_COLUMNS)
        .eq("user_id", user_id).eq("client_id", client_id).eq("status", "active")
        .limit(1).execute()
    )
    return rows[0] if rows else None


def current(db) -> dict | None:
    """The connection the Claude Access page shows: the active one, else the newest."""
    rows = _rows(db.table(TABLE).select(_COLUMNS).order("created_at", desc=True).limit(20).execute())
    for row in rows:
        if row.get("status") == "active":
            return row
    return rows[0] if rows else None


def activate(db, user_id: str, client_id: str, label: str | None) -> dict:
    """Switch this connection on and every other one off."""
    now = _now()
    db.table(TABLE).update({"status": "revoked", "revoked_at": now}).eq("status", "active").execute()
    rows = _rows(
        db.table(TABLE).upsert(
            {
                "user_id": user_id,
                "client_id": client_id,
                "label": (label or "Claude app")[:80],
                "status": "active",
                "revoked_at": None,
            },
            on_conflict="user_id,client_id",
        ).execute()
    )
    if not rows:
        raise RuntimeError("mcp connection was not saved")
    return rows[0]


def revoke_all(db) -> int:
    rows = _rows(
        db.table(TABLE).update({"status": "revoked", "revoked_at": _now()}).eq("status", "active").execute()
    )
    return len(rows)


def touch(db, connection_id: str) -> None:
    db.table(TABLE).update({"last_used_at": _now()}).eq("id", connection_id).execute()
