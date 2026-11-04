"""DLT Setup and Add credit (docs/plans/2026-11-03-sms-redesign.md): entities and sender IDs a
client submitted, and SMS credit requests. Routes: app/routes/sms.py
(client) and app/routes/operator_sms.py (operator).

Bulk9 has no entity list and lists only approved senders, so a submitted entity or sender reads
"Submitted" until the same ID shows up in Bulk9's approved lists, then "Approved".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.sms_campaigns import SmsError

logger = logging.getLogger(__name__)

MAX_OPEN_CREDIT_REQUESTS = 3
ALERT_DEDUP_MINUTES = 60
CREDIT_CAP_MESSAGE = "You already have 3 requests waiting. Your account manager will add the credit soon."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- operator bell

def alert(db, tenant_id: str, kind: str, message: str, *, dedup_key: str | None = None) -> None:
    """An operator-bell alert (incidents; the bell shows the last 48 hours). Never blocks the caller.
    With dedup_key, a second alert for the same tenant, kind and key within an hour is skipped."""
    detail: dict[str, Any] = {"message": message}
    try:
        if dedup_key:
            detail["key"] = dedup_key
            since = (datetime.now(timezone.utc) - timedelta(minutes=ALERT_DEDUP_MINUTES)).isoformat()
            recent = (db.table("incidents").select("detail").eq("tenant_id", tenant_id).eq("type", kind)
                      .gte("created_at", since).limit(50).execute()).data or []
            if any((r.get("detail") or {}).get("key") == dedup_key for r in recent):
                return
        db.table("incidents").insert({"tenant_id": tenant_id, "type": kind, "detail": detail,
                                      "created_at": _now()}).execute()
    except Exception:
        logger.exception("sms_setup: operator alert %s failed", kind)


def _tenant_name(db, tenant_id: str) -> str:
    rows = (db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute()).data or []
    return (rows[0].get("name") if rows else None) or "A client"


# ---------------------------------------------------------------- submissions

def record_submission(db, tenant_id: str, user_id: str | None, *, kind: str, entity_id: str,
                      entity_name: str | None = None, sender_id: str | None = None) -> None:
    """Remember what the client submitted (a resubmit of the same ID is a no-op)."""
    q = (db.table("sms_dlt_submissions").select("id").eq("tenant_id", tenant_id).eq("kind", kind)
         .eq("entity_id", entity_id))
    q = q.eq("sender_id", sender_id) if sender_id else q.is_("sender_id", "null")
    if (q.limit(1).execute()).data:
        return
    try:
        db.table("sms_dlt_submissions").insert({
            "tenant_id": tenant_id, "kind": kind, "entity_id": entity_id, "entity_name": entity_name,
            "sender_id": sender_id, "created_by": user_id,
        }).execute()
    except Exception:
        # The submission already reached Bulk9; a lost race on the unique index is harmless.
        logger.warning("sms_setup: recording a %s submission failed", kind, exc_info=True)


def _submissions(db, tenant_id: str, kind: str) -> list[dict]:
    return (db.table("sms_dlt_submissions").select("*").eq("tenant_id", tenant_id).eq("kind", kind)
            .order("created_at", desc=True).execute()).data or []


def entities(db, tenant_id: str, approved_senders: list[dict]) -> list[dict]:
    """Every entity the client has: submitted from Anril, or seen on an approved sender/template."""
    templates = (db.table("sms_templates").select("entity_id,entity_name,status,created_at")
                 .eq("tenant_id", tenant_id).execute()).data or []
    approved: dict[str, str | None] = {}
    for r in approved_senders:
        if r.get("entity_id"):
            approved.setdefault(str(r["entity_id"]), r.get("entity_name"))
    for r in templates:
        if r.get("entity_id") and r.get("status") == "ready":
            approved.setdefault(str(r["entity_id"]), r.get("entity_name"))
    out: dict[str, dict] = {}
    for s in _submissions(db, tenant_id, "entity"):
        eid = s["entity_id"]
        out[eid] = {"entity_id": eid, "entity_name": s.get("entity_name") or approved.get(eid),
                    "status": "approved" if eid in approved else "submitted", "at": s.get("created_at")}
    for eid, name in approved.items():
        out.setdefault(eid, {"entity_id": eid, "entity_name": name, "status": "approved", "at": None})
    return sorted(out.values(), key=lambda e: str(e["at"] or ""), reverse=True)


def senders(db, tenant_id: str, approved_senders: list[dict]) -> list[dict]:
    """Approved senders from Bulk9 plus the client's submitted ones not approved yet."""
    seen = {(str(r.get("sender_id")).upper(), str(r.get("entity_id"))) for r in approved_senders}
    out = [{**r, "status": "approved", "at": None} for r in approved_senders]
    for s in _submissions(db, tenant_id, "sender"):
        if (s["sender_id"], s["entity_id"]) in seen:
            continue
        seen.add((s["sender_id"], s["entity_id"]))
        out.append({"sender_id": s["sender_id"], "entity_id": s["entity_id"], "entity_name": None,
                    "status": "submitted", "at": s.get("created_at")})
    return out


# ---------------------------------------------------------------- Add credit

CREDIT_FIELDS = ("id", "amount", "note", "status", "created_at", "done_at")


def public_credit(r: dict) -> dict:
    out = {k: r.get(k) for k in CREDIT_FIELDS}
    out["amount"] = float(out["amount"]) if out["amount"] is not None else None
    return out


def credit_requests(db, tenant_id: str, limit: int = 20) -> list[dict]:
    return (db.table("sms_credit_requests").select("*").eq("tenant_id", tenant_id)
            .order("created_at", desc=True).limit(limit).execute()).data or []


def request_credit(db, tenant_id: str, user_id: str | None, amount: float, note: str | None) -> dict:
    open_rows = (db.table("sms_credit_requests").select("id").eq("tenant_id", tenant_id).eq("status", "open")
                 .execute()).data or []
    if len(open_rows) >= MAX_OPEN_CREDIT_REQUESTS:
        raise SmsError(CREDIT_CAP_MESSAGE, 409)
    note = (note or "").strip()[:300] or None
    try:
        row = (db.table("sms_credit_requests").insert({
            "tenant_id": tenant_id, "amount": round(float(amount), 2), "note": note, "status": "open",
            "requested_by": user_id,
        }).execute()).data[0]
    except Exception as e:
        # Two requests at once can both pass the count above; the trigger in migration 244 refuses one.
        if "sms_credit_cap" in str(e):
            raise SmsError(CREDIT_CAP_MESSAGE, 409) from e
        raise
    alert(db, tenant_id, "sms_credit_request",
          f"{_tenant_name(db, tenant_id)} asked for ₹{amount:,.2f} SMS credit" + (f": {note}" if note else "."))
    return row


def finish_credit(db, request_id: str, admin_id: str | None, status: str = "done") -> dict:
    """Operator: credit added (done) or not (cancelled). Only an open request changes."""
    rows = (db.table("sms_credit_requests").update({"status": status, "done_at": _now(), "done_by": admin_id})
            .eq("id", request_id).eq("status", "open").execute()).data or []
    if rows:
        return rows[0]
    found = (db.table("sms_credit_requests").select("*").eq("id", request_id).limit(1).execute()).data or []
    if not found:
        raise SmsError("Request not found.", 404)
    return found[0]


def open_credit_requests(db, limit: int = 100) -> list[dict[str, Any]]:
    rows = (db.table("sms_credit_requests").select("*").eq("status", "open")
            .order("created_at", desc=True).limit(limit).execute()).data or []
    names: dict[str, str] = {}
    ids = list({r["tenant_id"] for r in rows})
    if ids:
        for t in (db.table("tenants").select("id,name").in_("id", ids).execute()).data or []:
            names[t["id"]] = t.get("name")
    return [{**public_credit(r), "tenant_id": r["tenant_id"], "tenant_name": names.get(r["tenant_id"])}
            for r in rows]
