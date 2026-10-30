# backend/app/routes/sms_webhooks.py
"""Public webhooks for SMS: Bulk9 delivery callbacks and Anril's own Razorpay recharges.

Bulk9 signs nothing, so each tenant gets its own random secret, sent by Bulk9 in the
X-Anril-Webhook-Secret header (configured when the operator saves the client's key). The tenant
comes from the URL and is only trusted after that secret matches — never from the payload.
"""
from __future__ import annotations

import hmac
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.services import sms_billing, sms_delivery

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_BODY = 64 * 1024


def _too_big(request: Request) -> bool:
    try:
        return int(request.headers.get("content-length") or 0) > _MAX_BODY
    except ValueError:
        return True


@router.post("/webhook/bulk9/{tenant_id}")
async def bulk9_delivery_webhook(tenant_id: str, request: Request):
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
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    items = payload if isinstance(payload, list) else [payload]
    db = get_supabase()
    results = [sms_delivery.handle_callback(db, tenant_id, p) for p in items[:500] if isinstance(p, dict)]
    return {"status": "ok", "processed": len(results)}


@router.post("/webhook/razorpay-sms")
async def razorpay_sms_webhook(request: Request):
    if _too_big(request):
        raise HTTPException(status_code=413, detail="Payload too large")
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="Payload too large")
    if not sms_billing.verify_webhook(raw, request.headers.get("x-razorpay-signature", "")):
        logger.warning("SMS Razorpay webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    return await sms_billing.handle_razorpay_event(get_supabase(), payload)
