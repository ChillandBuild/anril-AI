# backend/app/routes/sms_webhooks.py
"""Bulk9 delivery callbacks authenticated with a per-tenant secret.

Bulk9 signs nothing, so each tenant gets its own random secret. Bulk9's docs say custom headers
are forwarded, but live callbacks arrived without them (2026-11-04), so the secret also rides
inside the body template Anril registers (`anril_secret`). Either place is accepted; the field is
stripped before anything is stored. The tenant comes from the URL and is only trusted after the
secret matches — never from the payload.
"""
from __future__ import annotations

import hmac
import json
import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Request

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.services import sms_delivery

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_BODY = 64 * 1024


def _too_big(request: Request) -> bool:
    try:
        return int(request.headers.get("content-length") or 0) > _MAX_BODY
    except ValueError:
        return True


SECRET_FIELD = "anril_secret"
# A placeholder Bulk9 left unfilled ("@{{status}}" / "{{status}}") carries no information.
_UNFILLED = re.compile(r"^@?\{\{\s*[\w.]+\s*\}\}$")


def _matches(expected: str, given: object) -> bool:
    if not isinstance(given, str) or not given:
        return False
    # surrogatepass: a lone surrogate in JSON must give 401, not a 500.
    return hmac.compare_digest(expected.encode("utf-8", "surrogatepass"), given.encode("utf-8", "surrogatepass"))


def _clean(item: dict) -> dict:
    """Drop the secret and any empty or unfilled placeholder values."""
    return {k: v for k, v in item.items()
            if k != SECRET_FIELD and v != "" and not (isinstance(v, str) and _UNFILLED.match(v))}


async def _authenticated_items(tenant_id: str, request: Request) -> tuple[str, list]:
    """(tenant_id, payload items) once the tenant's secret matches; HTTP errors otherwise.
    The secret comes from the X-Anril-Webhook-Secret header or, failing that, from the
    `anril_secret` field of every item in the body."""
    try:
        tenant_id = str(uuid.UUID(tenant_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    if _too_big(request):
        raise HTTPException(status_code=413, detail="Payload too large")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > _MAX_BODY:
            raise HTTPException(status_code=413, detail="Payload too large")
        raw.extend(chunk)
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    items = payload if isinstance(payload, list) else [payload]
    items = [p for p in items[:500] if isinstance(p, dict)]

    expected = get_setting("bulk9_webhook_secret", tenant_id=tenant_id) or ""
    header_ok = bool(expected) and _matches(expected, request.headers.get("x-anril-webhook-secret", ""))
    body_ok = bool(expected) and bool(items) and all(_matches(expected, p.get(SECRET_FIELD)) for p in items)
    if not (header_ok or body_ok):
        logger.warning("Bulk9 webhook: bad secret for tenant %s", tenant_id)
        raise HTTPException(status_code=401, detail="Unauthorized")
    if payload is None:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    return tenant_id, [_clean(p) for p in items]


@router.post("/webhook/bulk9/{tenant_id}")
async def bulk9_delivery_webhook(tenant_id: str, request: Request):
    tenant_id, items = await _authenticated_items(tenant_id, request)
    db = get_supabase()
    results = [sms_delivery.handle_callback(db, tenant_id, p) for p in items]
    return {"status": "ok", "processed": len(results)}


@router.post("/webhook/bulk9/{tenant_id}/otp")
async def bulk9_otp_webhook(tenant_id: str, request: Request):
    """OTP delivery reports (same secret and payload as SMS); they fill OTP history."""
    tenant_id, items = await _authenticated_items(tenant_id, request)
    db = get_supabase()
    results = [sms_delivery.handle_otp_callback(db, tenant_id, p) for p in items]
    return {"status": "ok", "processed": len(results)}
