"""Operator-only Bulk9 connection and template request management."""
from __future__ import annotations

import logging
import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.config import settings as env_settings
from app.config_dynamic import SECRET_SETTING_KEYS, get_setting, invalidate_cache
from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin
from app.services import bulk9_client
from app.services.audit_log import record_audit_event
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout
from app.services import sms_setup
from app.services.sms_campaigns import BATCH_SETTING, SmsError

logger = logging.getLogger(__name__)
router = APIRouter()
_RENDER_BASE_URL = "https://aira-ai-5tfr.onrender.com"


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
        "batch_send": (get_setting(BATCH_SETTING, tenant_id=tenant_id) or "").strip().lower() == "true",
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


class BatchIn(BaseModel):
    enabled: bool


@router.put("/clients/{tenant_id}/sms/batch")
async def set_batch_send(tenant_id: str, body: BatchIn, admin: dict = Depends(get_system_admin)):
    """Send this client's campaigns up to 50 SMS per Bulk9 call (/dev/custom) instead of one per call."""
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    _put(db, tid, BATCH_SETTING, "true" if body.enabled else "false")
    _audit(db, admin, tid, "operator.sms_batch_send_on" if body.enabled else "operator.sms_batch_send_off")
    return await _state(db, tid)


# ---------------------------------------------------------------- credit requests

def _setup_call(fn, *args):
    try:
        return fn(*args)
    except SmsError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


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
