"""DLT Setup and Add credit (docs/plans/2026-11-03-sms-redesign.md): entities and sender IDs a
client submitted, PE-TM binding per entity, and SMS credit requests. Routes: app/routes/sms.py
(client) and app/routes/operator_sms.py (operator).

Bulk9 has no entity list and lists only approved senders, so a submitted entity or sender reads
"Submitted" until the same ID shows up in Bulk9's approved lists, then "Approved".
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config_dynamic import get_setting, invalidate_cache
from app.services.sms_campaigns import SmsError

logger = logging.getLogger(__name__)

MAX_OPEN_CREDIT_REQUESTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- operator bell

def alert(db, tenant_id: str, kind: str, message: str) -> None:
    """An operator-bell alert (incidents; the bell shows the last 48 hours). Never blocks the caller."""
    try:
        db.table("incidents").insert({"tenant_id": tenant_id, "type": kind, "detail": {"message": message}}).execute()
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


# ---------------------------------------------------------------- PE-TM binding

PE_TM_FIELDS = ("id", "entity_id", "tm_approved_at", "pe_confirmed_at", "created_at", "updated_at")


def public_pe_tm(r: dict) -> dict:
    return {k: r.get(k) for k in PE_TM_FIELDS}


def pe_tm_rows(db, tenant_id: str) -> list[dict]:
    return (db.table("sms_pe_tm").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True)
            .execute()).data or []


def _pe_tm_row(db, tenant_id: str, row_id: str) -> dict:
    rows = (db.table("sms_pe_tm").select("*").eq("tenant_id", tenant_id).eq("id", row_id).limit(1)
            .execute()).data or []
    if not rows:
        raise SmsError("Binding request not found.", 404)
    return rows[0]


def check_pe_tm_open(db, tenant_id: str, entity_id: str) -> list[dict]:
    """The entity's binding row (0 or 1); refuses once the binding is done."""
    existing = (db.table("sms_pe_tm").select("*").eq("tenant_id", tenant_id).eq("entity_id", entity_id)
                .limit(1).execute()).data or []
    if existing and existing[0].get("pe_confirmed_at"):
        raise SmsError("This entity's PE-TM binding is already done.", 409)
    return existing


def save_pe_tm_proof(db, tenant_id: str, entity_id: str, proof_path: str) -> dict:
    """A new or replaced screenshot for one entity. A replaced proof restarts the approval."""
    existing = check_pe_tm_open(db, tenant_id, entity_id)
    patch = {"proof_path": proof_path, "tm_approved_at": None, "tm_approved_by": None, "updated_at": _now()}
    if existing:
        row = (db.table("sms_pe_tm").update(patch).eq("id", existing[0]["id"]).eq("tenant_id", tenant_id)
               .execute()).data[0]
    else:
        row = (db.table("sms_pe_tm").insert({"tenant_id": tenant_id, "entity_id": entity_id, **patch})
               .execute()).data[0]
    alert(db, tenant_id, "sms_pe_tm_proof",
          f"{_tenant_name(db, tenant_id)} uploaded PE-TM proof for entity {entity_id}.")
    return row


def approve_tm(db, tenant_id: str, row_id: str, admin_id: str | None) -> dict:
    """Operator: the TM side approved the binding (after forwarding the proof in the reseller panel)."""
    row = _pe_tm_row(db, tenant_id, row_id)
    if row.get("tm_approved_at"):
        return row
    return (db.table("sms_pe_tm").update({"tm_approved_at": _now(), "tm_approved_by": admin_id, "updated_at": _now()})
            .eq("id", row_id).eq("tenant_id", tenant_id).execute()).data[0]


def confirm_pe(db, tenant_id: str, row_id: str, user_id: str | None) -> dict:
    """Client: did the final approval in the DLT portal. Turns sending on (checklist pe_tm)."""
    row = _pe_tm_row(db, tenant_id, row_id)
    if not row.get("tm_approved_at"):
        raise SmsError("Wait until your account manager marks the TM approval, then approve it in your DLT portal.", 409)
    if row.get("pe_confirmed_at"):
        # Already confirmed: leave the switch alone, so an operator who turned sending off stays in charge.
        return row
    row = (db.table("sms_pe_tm").update({"pe_confirmed_at": _now(), "pe_confirmed_by": user_id, "updated_at": _now()})
           .eq("id", row_id).eq("tenant_id", tenant_id).execute()).data[0]
    set_pe_tm_done(db, tenant_id)
    return row


def set_pe_tm_done(db, tenant_id: str) -> None:
    try:
        raw = json.loads(get_setting("sms_checklist", tenant_id=tenant_id) or "{}")
    except ValueError:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    if raw.get("pe_tm") is True:
        return
    raw["pe_tm"] = True
    db.table("app_settings").upsert(
        {"key": "sms_checklist", "value": json.dumps(raw), "tenant_id": tenant_id, "is_secret": False},
        on_conflict="key,tenant_id",
    ).execute()
    invalidate_cache("sms_checklist")


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
        raise SmsError("You already have 3 requests waiting. Your account manager will add the credit soon.", 409)
    note = (note or "").strip()[:300] or None
    row = (db.table("sms_credit_requests").insert({
        "tenant_id": tenant_id, "amount": round(float(amount), 2), "note": note, "status": "open",
        "requested_by": user_id,
    }).execute()).data[0]
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
