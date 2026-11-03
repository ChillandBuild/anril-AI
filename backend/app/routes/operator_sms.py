"""Operator-only Bulk9 connection and template request management."""
from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.config import settings as env_settings
from app.config_dynamic import SECRET_SETTING_KEYS, get_setting, invalidate_cache
from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin
from app.services import bulk9_client
from app.services.audit_log import record_audit_event
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout
from app.routes.sms import signed_url
from app.services import sms_setup
from app.services.sms_campaigns import SmsError

logger = logging.getLogger(__name__)
router = APIRouter()
_RENDER_BASE_URL = "https://aira-ai-5tfr.onrender.com"
_REQUEST_FIELDS = "id,tenant_id,wording,template_type,status,reason,created_at,updated_at"


def _tenant_id(raw: str) -> str:
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        raise HTTPException(status_code=404, detail="Client not found")


def _tenant(db, tenant_id: str) -> None:
    rows = db.table("tenants").select("id").eq("id", tenant_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Client not found")


def _put(db, tenant_id: str, key: str, value: str | None) -> None:
    db.table("app_settings").upsert(
        {"key": key, "value": value, "tenant_id": tenant_id, "is_secret": key in SECRET_SETTING_KEYS},
        on_conflict="key,tenant_id",
    ).execute()
    invalidate_cache(key)


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value[:4]}••••••••{value[-4:]}" if len(value) > 10 else "••••••••"


def _audit(db, admin: dict, tenant_id: str, action: str) -> None:
    record_audit_event(db, tenant_id=tenant_id, actor_user_id=admin.get("user_id"), actor_role="system_admin",
                       action=action, target_type="tenant", target_id=tenant_id, metadata={})


CHECKLIST_KEYS = ("dlt", "pe_tm", "sender")


def _checklist(tenant_id: str) -> dict:
    try:
        raw = json.loads(get_setting("sms_checklist", tenant_id=tenant_id) or "{}")
    except ValueError:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    return {k: bool(raw.get(k)) for k in CHECKLIST_KEYS}


async def _state(db, tenant_id: str) -> dict:
    _tenant(db, tenant_id)
    key = get_setting("bulk9_api_key", tenant_id=tenant_id)
    sms_count = None
    if key:
        try:
            sms_count = (await bulk9_client.wallet(key))["sms_count"]
        except (Bulk9Error, Bulk9Timeout):
            pass  # the panel still loads; the count just shows as unknown
    return {
        "connected": bool(key),
        "key_masked": _mask(key),
        "webhook_registered": bool(key) and get_setting("bulk9_webhook_registered", tenant_id=tenant_id) == "true",
        "webhook_error": get_setting("bulk9_webhook_error", tenant_id=tenant_id) or None,
        "sms_count": sms_count,
        "checklist": _checklist(tenant_id),
    }


def _webhooks(response: dict) -> list[dict]:
    rows = response.get("data", response.get("webhooks"))
    if isinstance(rows, dict):
        rows = rows.get("webhooks")
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("url") or row.get("id") is None for row in rows):
        raise Bulk9Error("Unexpected webhook list response")
    return rows


async def _upsert_webhook(api_key: str, url: str, secret: str, **service) -> None:
    """Create the webhook for `url`, or update the existing one and drop duplicates."""
    rows = _webhooks(await bulk9_client.list_sms_webhooks(api_key, **service))
    matches = [row for row in rows if row["url"].rstrip("/") == url]
    if matches:
        await bulk9_client.update_sms_webhook(api_key, matches[0]["id"], url=url, secret=secret, **service)
        for duplicate in matches[1:]:
            await bulk9_client.delete_sms_webhook(api_key, duplicate["id"], **service)
    else:
        await bulk9_client.create_sms_webhook(api_key, url=url, secret=secret, **service)


async def _register_webhook(db, tenant_id: str, api_key: str) -> bool:
    base = (env_settings.public_base_url or _RENDER_BASE_URL).rstrip("/")
    url = f"{base}/webhook/bulk9/{tenant_id}"
    secret = get_setting("bulk9_webhook_secret", tenant_id=tenant_id)
    if not secret:
        # Reserve once so a provider-accepted timeout can be recovered without rotating authentication.
        secret = secrets.token_urlsafe(32)
        _put(db, tenant_id, "bulk9_webhook_secret", secret)
    _put(db, tenant_id, "bulk9_webhook_registered", "false")
    _put(db, tenant_id, "bulk9_webhook_error", "Webhook setup has not been confirmed. Retry setup to check Bulk9.")
    try:
        await _upsert_webhook(api_key, url, secret)
        # OTP delivery reports (Delivered / Failed in OTP history) come on their own webhook.
        await _upsert_webhook(api_key, f"{url}/otp", secret, service="otp")
    except (Bulk9Error, Bulk9Timeout) as exc:
        logger.warning("SMS webhook setup failed for %s (%s)", tenant_id, type(exc).__name__)
        error = ("Bulk9 did not confirm webhook setup. Retry to check the existing callback."
                 if isinstance(exc, Bulk9Timeout) else "Bulk9 webhook setup failed. Check the connection and retry.")
        _put(db, tenant_id, "bulk9_webhook_error", error)
        return False
    _put(db, tenant_id, "bulk9_webhook_registered", "true")
    _put(db, tenant_id, "bulk9_webhook_error", None)
    return True


@router.get("/clients/{tenant_id}/sms")
async def get_sms(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    return await _state(get_supabase(), _tenant_id(tenant_id))


class KeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=200)

    @field_validator("api_key", mode="before")
    @classmethod
    def strip_key(cls, value):
        return value.strip() if isinstance(value, str) else value


@router.put("/clients/{tenant_id}/sms/key")
async def save_key(tenant_id: str, body: KeyIn, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    try:
        await bulk9_client.wallet(body.api_key)
    except (Bulk9Error, Bulk9Timeout):
        raise HTTPException(status_code=400, detail="Bulk9 could not validate this key. Check the key and retry.")
    _put(db, tid, "bulk9_api_key", body.api_key)
    _audit(db, admin, tid, "operator.sms_key_saved")
    await _register_webhook(db, tid, body.api_key)
    return await _state(db, tid)


class ChecklistIn(BaseModel):
    dlt: bool
    pe_tm: bool
    sender: bool


@router.put("/clients/{tenant_id}/sms/checklist")
async def save_checklist(tenant_id: str, body: ChecklistIn, admin: dict = Depends(get_system_admin)):
    """The client's setup steps Bulk9 has no API for. PE–TM gates sending (routes/sms.py)."""
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    _put(db, tid, "sms_checklist", json.dumps(body.model_dump()))
    _audit(db, admin, tid, "operator.sms_checklist_saved")
    return await _state(db, tid)


@router.post("/clients/{tenant_id}/sms/webhook")
async def reregister_webhook(tenant_id: str, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    key = get_setting("bulk9_api_key", tenant_id=tid)
    if not key:
        raise HTTPException(status_code=409, detail="Save the client's Bulk9 key first")
    if await _register_webhook(db, tid, key):
        _audit(db, admin, tid, "operator.sms_webhook_registered")
    return await _state(db, tid)


@router.get("/clients/{tenant_id}/sms/template-requests")
async def list_template_requests(tenant_id: str, page: int = Query(default=1, ge=1),
                                 limit: int = Query(default=50, ge=1, le=100),
                                 _admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    result = (db.table("sms_template_requests").select(_REQUEST_FIELDS, count="exact").eq("tenant_id", tid)
              .order("created_at", desc=True).range((page - 1) * limit, page * limit - 1).execute())
    return {"items": result.data or [], "total": result.count or 0, "page": page, "limit": limit}


class RequestUpdateIn(BaseModel):
    status: Literal["in_progress", "ready", "rejected"]
    reason: str | None = Field(default=None, max_length=500)


@router.patch("/clients/{tenant_id}/sms/template-requests/{request_id}")
async def update_template_request(tenant_id: str, request_id: str, body: RequestUpdateIn,
                                  admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    reason = (body.reason or "").strip() or None
    if body.status == "rejected" and not reason:
        raise HTTPException(status_code=400, detail="Give a reason when rejecting")
    result = (db.table("sms_template_requests")
              .update({"status": body.status, "reason": reason, "updated_at": datetime.now(timezone.utc).isoformat()})
              .eq("id", _tenant_id(request_id)).eq("tenant_id", tid).execute())
    if not result.data:
        raise HTTPException(status_code=404, detail="Request not found")
    _audit(db, admin, tid, "operator.sms_template_request_updated")
    return {"item": {key: result.data[0].get(key) for key in _REQUEST_FIELDS.split(",")}}


# ---------------------------------------------------------------- PE-TM binding + credit requests

PROOF_URL_SECONDS = 600


def _setup_call(fn, *args):
    try:
        return fn(*args)
    except SmsError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("/clients/{tenant_id}/sms/pe-tm")
async def list_pe_tm(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    """Each entity's binding request, with a 10-minute link to the client's screenshot."""
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    return {"items": [{**sms_setup.public_pe_tm(r), "proof_url": _proof_url(db, r["proof_path"])}
                      for r in sms_setup.pe_tm_rows(db, tid)]}


def _proof_url(db, path: str) -> str | None:
    try:
        return signed_url(db, path, PROOF_URL_SECONDS)
    except HTTPException:  # one missing file must not hide the other rows
        return None


@router.post("/clients/{tenant_id}/sms/pe-tm/{row_id}/approve")
async def approve_pe_tm(tenant_id: str, row_id: str, admin: dict = Depends(get_system_admin)):
    """TM approval done in the reseller panel; the client can now do the final approval."""
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    row = _setup_call(sms_setup.approve_tm, db, tid, _tenant_id(row_id), admin.get("user_id"))
    _audit(db, admin, tid, "operator.sms_pe_tm_approved")
    return {"item": sms_setup.public_pe_tm(row)}


@router.get("/sms/credit-requests")
async def list_credit_requests(status: Literal["open"] = "open", _admin: dict = Depends(get_system_admin)):
    return {"items": sms_setup.open_credit_requests(get_supabase())}


class CreditDoneIn(BaseModel):
    status: Literal["done", "cancelled"] = "done"


@router.post("/sms/credit-requests/{request_id}/done")
async def finish_credit_request(request_id: str, body: CreditDoneIn, admin: dict = Depends(get_system_admin)):
    """Credit added in the reseller panel (done) or not (cancelled)."""
    db = get_supabase()
    row = _setup_call(sms_setup.finish_credit, db, _tenant_id(request_id), admin.get("user_id"), body.status)
    _audit(db, admin, row["tenant_id"], f"operator.sms_credit_{row['status']}")
    return {"item": sms_setup.public_credit(row)}
