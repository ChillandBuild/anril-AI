# backend/app/routes/sms_webhooks.py
"""Bulk9 delivery callbacks authenticated with a per-tenant header secret.

Bulk9 signs nothing, so each tenant gets its own random secret, sent by Bulk9 in the
X-Anril-Webhook-Secret header (configured when the operator saves the client's key). The tenant
comes from the URL and is only trusted after that secret matches — never from the payload.
"""
from __future__ import annotations

import hmac
import json
import logging
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


async def _authenticated_items(tenant_id: str, request: Request) -> tuple[str, list]:
    """(tenant_id, payload items) once the tenant's secret matches; HTTP errors otherwise."""
    try:
        tenant_id = str(uuid.UUID(tenant_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    expected = get_setting("bulk9_webhook_secret", tenant_id=tenant_id) or ""
    given = request.headers.get("x-anril-webhook-secret", "")
    if not expected or not hmac.compare_digest(expected.encode(), given.encode()):
        logger.warning("Bulk9 webhook: bad secret for tenant %s", tenant_id)
        raise HTTPException(status_code=401, detail="Unauthorized")
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
        raise HTTPException(status_code=400, detail="Invalid JSON")
    items = payload if isinstance(payload, list) else [payload]
    return tenant_id, [p for p in items[:500] if isinstance(p, dict)]


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
