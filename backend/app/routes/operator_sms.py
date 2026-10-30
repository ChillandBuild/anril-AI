# backend/app/routes/operator_sms.py
"""Operator console → client → SMS (Prem only, get_system_admin). Mounted under
/api/v1/operator. Contract: docs/plans/2026-10-30-sms-api-contract.md § Operator API.

Saving the client's key also registers Anril's delivery webhook in that client's Bulk9 account,
with a fresh per-tenant secret. Keys are never returned, only masked.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings as env_settings
from app.config_dynamic import SECRET_SETTING_KEYS, get_setting, invalidate_cache
from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin
from app.services import bulk9_client, bulk9_reseller, sms_billing
from app.services.audit_log import record_audit_event
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout

logger = logging.getLogger(__name__)

router = APIRouter()

_RENDER_BASE_URL = "https://aira-ai-5tfr.onrender.com"
LOW_STOCK_THRESHOLD = int(os.environ.get("SMS_LOW_STOCK_THRESHOLD", "5000"))
_CHECKLIST_KEYS = ("dlt", "pe_tm", "sender")


def _tenant_id(raw: str) -> str:
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        raise HTTPException(status_code=404, detail="Client not found")


def _tenant(db, tenant_id: str) -> dict:
    rows = db.table("tenants").select("id, name, enabled_features").eq("id", tenant_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Client not found")
    return rows[0]


def _put(db, tenant_id: str, key: str, value: str | None) -> None:
    """Unlike config_dynamic.save_setting (which logs and carries on), a failed write here must
    fail the request: the operator would otherwise believe a key was saved."""
    db.table("app_settings").upsert(
        {"key": key, "value": value, "tenant_id": tenant_id, "is_secret": key in SECRET_SETTING_KEYS},
        on_conflict="key,tenant_id",
    ).execute()
    invalidate_cache(key)


def _mask(v: str | None) -> str | None:
    if not v:
        return None
    return f"{v[:4]}••••••••{v[-4:]}" if len(v) > 10 else "••••••••"


def _checklist(tenant_id: str) -> dict:
    try:
        raw = json.loads(get_setting("sms_checklist", tenant_id=tenant_id) or "{}")
    except ValueError:
        raw = {}
    return {k: bool(raw.get(k)) for k in _CHECKLIST_KEYS}


def _bulk9_error(exc: Exception) -> HTTPException:
    if isinstance(exc, bulk9_reseller.InsufficientResellerStock):
        return HTTPException(status_code=409, detail=f"Not enough SMS in your Bulk9 stock: {exc}")
    if isinstance(exc, bulk9_reseller.ResellerNotConfigured):
        return HTTPException(status_code=409, detail="BULK9_RESELLER_KEY is not set on the server")
    if isinstance(exc, Bulk9Timeout):
        return HTTPException(status_code=504, detail="Bulk9 did not answer. Check Bulk9 before retrying.")
    return HTTPException(status_code=502, detail=f"Bulk9: {exc}")


def _audit(db, admin: dict, tenant_id: str, action: str, metadata: dict | None = None) -> None:
    record_audit_event(db, tenant_id=tenant_id, actor_user_id=admin.get("user_id"), actor_role="system_admin",
                       action=action, target_type="tenant", target_id=tenant_id, metadata=metadata or {})


async def _state(db, tenant_id: str) -> dict:
    tenant = _tenant(db, tenant_id)
    key = get_setting("bulk9_api_key", tenant_id=tenant_id)
    balance, balance_error = None, None
    if key:
        try:
            w = await bulk9_client.wallet(key)
            balance = {"wallet": float(w.get("wallet") or 0), "sms_count": int(float(w.get("sms_count") or 0))}
        except (Bulk9Error, Bulk9Timeout) as exc:
            balance_error = str(exc)
    ledger = (db.table("sms_ledger").select("*").eq("tenant_id", tenant_id)
              .order("created_at", desc=True).limit(100).execute().data or [])
    requests = (db.table("sms_template_requests").select("*").eq("tenant_id", tenant_id)
                .order("created_at", desc=True).limit(100).execute().data or [])
    payments = (db.table("sms_payments").select("id, amount_paise, sms_count, status, error, created_at, paid_at, credited_at")
                .eq("tenant_id", tenant_id).order("created_at", desc=True).limit(50).execute().data or [])
    rate = sms_billing.buy_rate(tenant_id)
    return {
        "enabled": "sms" in (tenant.get("enabled_features") or []),
        "connected": bool(key),
        "key_masked": _mask(key),
        "bulk9_username": get_setting("bulk9_username", tenant_id=tenant_id),
        "webhook_registered": bool(get_setting("bulk9_webhook_secret", tenant_id=tenant_id)),
        "price_per_sms": float(sms_billing.price_per_sms(tenant_id)),
        "buy_rate": float(rate) if rate is not None else None,
        "checklist": _checklist(tenant_id),
        "support_contact": get_setting("sms_support_contact", tenant_id=tenant_id),
        "balance": balance,
        "balance_error": balance_error,
        "ledger": ledger,
        "template_requests": requests,
        "payments": [{**p, "amount_rupees": p["amount_paise"] / 100} for p in payments],
        "profit": sms_billing.profit(db, tenant_id),
    }


async def _register_webhook(db, tenant_id: str, api_key: str) -> None:
    base = (get_setting("public_base_url") or env_settings.public_base_url or _RENDER_BASE_URL).rstrip("/")
    secret = secrets.token_urlsafe(32)
    await bulk9_client.create_sms_webhook(api_key, url=f"{base}/webhook/bulk9/{tenant_id}", secret=secret)
    _put(db, tenant_id, "bulk9_webhook_secret", secret)


# ---------------------------------------------------------------- routes

@router.get("/clients/{tenant_id}/sms")
async def get_sms(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    return await _state(get_supabase(), _tenant_id(tenant_id))


class AccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=100)
    email: str | None = None
    mobile: str | None = None


@router.post("/clients/{tenant_id}/sms/account")
async def create_account(tenant_id: str, body: AccountIn, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    if get_setting("bulk9_username", tenant_id=tid):
        raise HTTPException(status_code=409, detail="This client already has a Bulk9 account linked")
    try:
        await bulk9_reseller.create_user(name=body.name, username=body.username, email=body.email, mobile=body.mobile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _bulk9_error(exc)
    _put(db, tid, "bulk9_username", body.username)
    _audit(db, admin, tid, "operator.sms_account_created", {"username": body.username})
    return await _state(db, tid)


class KeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=200)


@router.put("/clients/{tenant_id}/sms/key")
async def save_key(tenant_id: str, body: KeyIn, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    key = body.api_key.strip()
    try:
        await bulk9_client.wallet(key)  # proves the key works before saving it
    except (Bulk9Error, Bulk9Timeout) as exc:
        raise HTTPException(status_code=400, detail=f"Bulk9 rejected this key: {exc}")
    _put(db, tid, "bulk9_api_key", key)
    _audit(db, admin, tid, "operator.sms_key_saved", {"key": "***redacted***"})
    try:
        await _register_webhook(db, tid, key)
    except (Bulk9Error, Bulk9Timeout) as exc:
        logger.warning("SMS webhook registration failed for %s: %s", tid, exc)
    return await _state(db, tid)


@router.post("/clients/{tenant_id}/sms/webhook")
async def reregister_webhook(tenant_id: str, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    key = get_setting("bulk9_api_key", tenant_id=tid)
    if not key:
        raise HTTPException(status_code=409, detail="Save the client's Bulk9 key first")
    try:
        await _register_webhook(db, tid, key)
    except Exception as exc:
        raise _bulk9_error(exc)
    _audit(db, admin, tid, "operator.sms_webhook_registered")
    return await _state(db, tid)


class SettingsIn(BaseModel):
    bulk9_username: str | None = Field(default=None, min_length=3, max_length=40)
    price_per_sms: Decimal | None = Field(default=None, gt=0, le=10)
    buy_rate: Decimal | None = Field(default=None, gt=0, le=10)
    checklist: dict[str, bool] | None = None
    support_contact: str | None = Field(default=None, max_length=200)


@router.patch("/clients/{tenant_id}/sms/settings")
async def update_settings(tenant_id: str, body: SettingsIn, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    changed: list[str] = []
    if body.bulk9_username is not None:
        try:
            bulk9_reseller._check_username(body.bulk9_username)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _put(db, tid, "bulk9_username", body.bulk9_username)
        changed.append("bulk9_username")
    if body.price_per_sms is not None:
        _put(db, tid, "sms_price_per_sms", str(body.price_per_sms))
        changed.append("price_per_sms")
    if body.buy_rate is not None:
        _put(db, tid, "sms_buy_rate", str(body.buy_rate))
        changed.append("buy_rate")
    if body.checklist is not None:
        merged = {**_checklist(tid), **{k: bool(v) for k, v in body.checklist.items() if k in _CHECKLIST_KEYS}}
        _put(db, tid, "sms_checklist", json.dumps(merged))
        changed.append("checklist")
    if body.support_contact is not None:
        _put(db, tid, "sms_support_contact", body.support_contact.strip())
        changed.append("support_contact")
    _audit(db, admin, tid, "operator.sms_settings_updated", {"fields": changed})
    return await _state(db, tid)


async def _set_enabled(db, admin: dict, tid: str, enabled: bool) -> dict:
    tenant = _tenant(db, tid)
    username = get_setting("bulk9_username", tenant_id=tid)
    if username:
        try:
            await (bulk9_reseller.enable_user if enabled else bulk9_reseller.disable_user)(username)
        except Exception as exc:
            raise _bulk9_error(exc)
    features = [f for f in (tenant.get("enabled_features") or []) if f != "sms"]
    if enabled:
        features.append("sms")
    db.table("tenants").update({"enabled_features": features}).eq("id", tid).execute()
    _audit(db, admin, tid, "operator.sms_enabled" if enabled else "operator.sms_disabled")
    return await _state(db, tid)


@router.post("/clients/{tenant_id}/sms/enable")
async def enable_sms(tenant_id: str, admin: dict = Depends(get_system_admin)):
    return await _set_enabled(get_supabase(), admin, _tenant_id(tenant_id), True)


@router.post("/clients/{tenant_id}/sms/disable")
async def disable_sms(tenant_id: str, admin: dict = Depends(get_system_admin)):
    return await _set_enabled(get_supabase(), admin, _tenant_id(tenant_id), False)


class CreditIn(BaseModel):
    kind: Literal["manual_credit", "bonus"]
    sms_count: int = Field(gt=0, le=10_000_000)
    price_per_sms: Decimal | None = Field(default=None, gt=0, le=10)
    expiry_date: date | None = None
    note: str | None = Field(default=None, max_length=300)


@router.post("/clients/{tenant_id}/sms/credit")
async def add_credit(tenant_id: str, body: CreditIn, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    if body.expiry_date and body.expiry_date < datetime.now(timezone.utc).date():
        raise HTTPException(status_code=400, detail="Expiry date is in the past")
    try:
        await sms_billing.manual_credit(db, tid, kind=body.kind, sms_count=body.sms_count, price=body.price_per_sms,
                                        expiry_date=body.expiry_date, note=body.note, actor=admin.get("user_id"))
    except Exception as exc:
        raise _bulk9_error(exc)
    _audit(db, admin, tid, "operator.sms_credit_added", {"kind": body.kind, "sms_count": body.sms_count})
    return await _state(db, tid)


class DebitIn(BaseModel):
    sms_count: int = Field(gt=0, le=10_000_000)
    note: str | None = Field(default=None, max_length=300)


@router.post("/clients/{tenant_id}/sms/debit")
async def debit_credit(tenant_id: str, body: DebitIn, admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    _tenant(db, tid)
    try:
        await sms_billing.manual_debit(db, tid, sms_count=body.sms_count, note=body.note, actor=admin.get("user_id"))
    except Exception as exc:
        raise _bulk9_error(exc)
    _audit(db, admin, tid, "operator.sms_credit_debited", {"sms_count": body.sms_count})
    return await _state(db, tid)


_STUCK_PAID = timedelta(minutes=10)


class RequestUpdateIn(BaseModel):
    status: Literal["in_progress", "ready", "rejected"]
    reason: str | None = Field(default=None, max_length=500)


@router.patch("/clients/{tenant_id}/sms/template-requests/{request_id}")
async def update_template_request(tenant_id: str, request_id: str, body: RequestUpdateIn,
                                  admin: dict = Depends(get_system_admin)):
    tid, db = _tenant_id(tenant_id), get_supabase()
    if body.status == "rejected" and not (body.reason or "").strip():
        raise HTTPException(status_code=400, detail="Give a reason when rejecting")
    res = (db.table("sms_template_requests")
           .update({"status": body.status, "reason": body.reason, "updated_at": datetime.now(timezone.utc).isoformat()})
           .eq("id", _tenant_id(request_id)).eq("tenant_id", tid).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="Request not found")
    return await _state(db, tid)


@router.post("/clients/{tenant_id}/sms/payments/{payment_id}/retry-credit")
async def retry_credit(tenant_id: str, payment_id: str, admin: dict = Depends(get_system_admin)):
    """A paid recharge whose Bulk9 credit failed. The operator confirms in Bulk9 first that it
    really wasn't added (a timeout may have landed), then retries here."""
    tid, db, pid = _tenant_id(tenant_id), get_supabase(), _tenant_id(payment_id)
    claim = (db.table("sms_payments").update({"status": "paid"})
             .eq("id", pid).eq("tenant_id", tid).eq("status", "credit_failed").execute())
    if not claim.data:
        # A paid row stuck for 10+ minutes means the server stopped between the claim and the
        # credit (Razorpay's retry is then a duplicate). Re-claim it by bumping paid_at.
        rows = (db.table("sms_payments").select("*").eq("id", pid).eq("tenant_id", tid)
                .eq("status", "paid").lte("paid_at", (datetime.now(timezone.utc) - _STUCK_PAID).isoformat())
                .limit(1).execute().data or [])
        if rows:
            claim = (db.table("sms_payments").update({"paid_at": datetime.now(timezone.utc).isoformat()})
                     .eq("id", pid).eq("status", "paid").eq("paid_at", rows[0]["paid_at"]).execute())
    if not claim.data:
        raise HTTPException(status_code=409, detail="Only a payment whose credit failed (or is stuck as paid) can be retried")
    ok = await sms_billing.credit_payment(db, claim.data[0])
    _audit(db, admin, tid, "operator.sms_recharge_retried", {"payment_id": payment_id, "ok": ok})
    return await _state(db, tid)


async def stock() -> dict:
    try:
        bal = await bulk9_reseller.reseller_balance()
    except Exception as exc:
        return {"sms_count": None, "sms_balance": None, "threshold": LOW_STOCK_THRESHOLD, "low": False,
                "error": str(_bulk9_error(exc).detail)}
    count = int(float(bal.get("sms_count") or 0))
    return {"sms_count": count, "sms_balance": float(bal.get("sms_balance") or 0),
            "threshold": LOW_STOCK_THRESHOLD, "low": count < LOW_STOCK_THRESHOLD, "error": None}


@router.get("/sms/stock")
async def get_stock(_admin: dict = Depends(get_system_admin)):
    return await stock()


async def low_stock_check() -> None:
    """Daily scheduler job: shout in the logs (Render alerts on ERROR) when Prem's own SMS
    stock is low, before a client's recharge fails on it."""
    s = await stock()
    if s["low"]:
        logger.error("SMS reseller stock low: %s SMS left (threshold %s). Recharge Bulk9.",
                     s["sms_count"], LOW_STOCK_THRESHOLD)
