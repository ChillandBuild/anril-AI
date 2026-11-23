"""v9.2 #80 "Let the Anril team do it" on first setup step 2 (the catalogue).

One OPEN request per business per kind (a partial unique index backs this up). The Anril team sees open
requests on the Operator Console home, does the work, and marks the request done. Nothing is sent to anyone
here: the team contacts the owner on WhatsApp themselves."""
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

KINDS = ("catalogue",)
TABLE = "setup_help_requests"


class SetupHelpNotReady(Exception):
    """The table does not exist yet (migration 332 not applied)."""


def _is_missing(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("42p01", "pgrst205", "does not exist", "schema cache", "could not find the table"))


def _public(row: dict) -> dict[str, Any]:
    return {"id": row["id"], "kind": row["kind"], "status": row["status"], "created_at": row.get("created_at")}


def open_request(db, tenant_id: str, kind: str) -> dict | None:
    try:
        rows = (db.table(TABLE).select("id,kind,status,created_at").eq("tenant_id", tenant_id)
                .eq("kind", kind).eq("status", "open").limit(1).execute()).data or []
    except Exception as e:  # noqa: BLE001
        if _is_missing(e):
            raise SetupHelpNotReady() from e
        raise
    return rows[0] if rows else None


def request_help(db, tenant_id: str, user_id: str | None, kind: str = "catalogue") -> dict:
    """Create the request, or return the one already open. Safe to call twice (double click, two tabs)."""
    existing = open_request(db, tenant_id, kind)
    if existing:
        return {**_public(existing), "already": True}
    try:
        row = db.table(TABLE).insert({
            "tenant_id": tenant_id, "kind": kind, "status": "open", "requested_by": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute().data[0]
    except Exception as e:  # noqa: BLE001
        if _is_missing(e):
            raise SetupHelpNotReady() from e
        # Two clicks at once: the unique index refused the second insert, so read the winner.
        existing = open_request(db, tenant_id, kind)
        if existing:
            return {**_public(existing), "already": True}
        raise
    return {**_public(row), "already": False}


def list_open(db, limit: int = 100) -> list[dict]:
    """For the Operator Console: every business's open requests, newest first, with the business name."""
    try:
        rows = (db.table(TABLE).select("id,tenant_id,kind,status,created_at").eq("status", "open")
                .order("created_at", desc=True).limit(limit).execute()).data or []
    except Exception as e:  # noqa: BLE001  migration 332 not applied yet: nothing could have been requested
        logger.warning("setup_help: could not list requests (%s)", type(e).__name__)
        return []
    names: dict[str, str | None] = {}
    ids = list({r["tenant_id"] for r in rows})
    if ids:
        for t in (db.table("tenants").select("id,name").in_("id", ids).execute()).data or []:
            names[t["id"]] = t.get("name")
    return [{**_public(r), "tenant_id": r["tenant_id"], "tenant_name": names.get(r["tenant_id"])} for r in rows]


def finish(db, request_id: str, admin_user_id: str | None, status: str) -> dict | None:
    res = (db.table(TABLE).update({"status": status, "done_at": datetime.now(timezone.utc).isoformat(), "done_by": admin_user_id})
           .eq("id", request_id).eq("status", "open").execute()).data or []
    return res[0] if res else None
