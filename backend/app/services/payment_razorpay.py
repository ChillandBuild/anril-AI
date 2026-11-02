# backend/app/services/payment_razorpay.py
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config_dynamic import get_setting
from app.services import razorpay_oauth

logger = logging.getLogger(__name__)

_RAZORPAY_BASE = "https://api.razorpay.com/v1"

# A link with no expire_by never dies on Razorpay's side -- only the 48h
# intake_sessions staleness sweep (intake.py:_STALE_SESSION_HOURS) ever touched
# the session, and it left the link itself payable forever. 24h matches
# WhatsApp's own free-form messaging window (Hard Invariant 3): a link that
# outlives the window is one the lead can no longer be nudged about with plain
# text anyway, so there's no reason to keep it alive past that point. The 48h
# session sweep stays as the backstop for a missed/unsubscribed expiry webhook.
_LINK_EXPIRE_SECONDS = 24 * 60 * 60


def _get_key_id(tenant_id: str | None = None) -> str:
    v = get_setting("razorpay_key_id", tenant_id=tenant_id)
    if not v:
        raise RuntimeError("razorpay_key_id not configured in app settings")
    return v


def _get_key_secret(tenant_id: str | None = None) -> str:
    v = get_setting("razorpay_key_secret", tenant_id=tenant_id)
    if not v:
        raise RuntimeError("razorpay_key_secret not configured in app settings")
    return v


async def _auth_kwargs(tenant_id: str | None, *, force_refresh: bool = False) -> dict[str, Any]:
    """httpx auth for this tenant: the OAuth Bearer token when connected through Connect with
    Razorpay (it wins over pasted keys), otherwise Basic auth with the pasted key id/secret."""
    token = await razorpay_oauth.get_access_token(tenant_id, force_refresh=force_refresh)
    if token:
        return {"headers": {"Authorization": f"Bearer {token}"}}
    return {"auth": (_get_key_id(tenant_id), _get_key_secret(tenant_id))}


async def _post(tenant_id: str | None, path: str, *, json: dict | None = None,
                headers: dict[str, str] | None = None) -> httpx.Response:
    """POST to the Razorpay API as this tenant. A 401 on an OAuth token (revoked early, or
    expired between our check and the call) gets one forced refresh and one retry; a 401 on
    pasted keys is final. The retry is safe: Razorpay created nothing on a 401."""
    auth = await _auth_kwargs(tenant_id)
    for attempt in range(2):
        async with httpx.AsyncClient(auth=auth.get("auth"), timeout=15.0) as client:
            resp = await client.post(
                f"{_RAZORPAY_BASE}{path}", json=json, headers={**(headers or {}), **auth.get("headers", {})},
            )
        if resp.status_code != 401 or "auth" in auth or attempt:
            return resp
        auth = await _auth_kwargs(tenant_id, force_refresh=True)
    return resp


def _get_webhook_secret(tenant_id: str | None = None) -> str:
    v = get_setting("razorpay_webhook_secret", tenant_id=tenant_id)
    if not v:
        raise RuntimeError("razorpay_webhook_secret not configured in app settings")
    return v


async def create_payment_link(
    idempotency_key: str,
    notes: dict[str, str],
    amount_paise: int,
    customer_name: str,
    customer_phone: str,
    description: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a Razorpay Payment Link and return the short URL.

    `notes` and `idempotency_key` are caller-supplied rather than a fixed
    booking_id/booking_ref shape -- the webhook resolves what got paid purely
    from `notes` (see razorpay_webhook in routes/intake.py), so a second kind
    of payment (a quote, not an intake booking) needs its own notes key
    (`deal_id`, not `booking_id`) to avoid the webhook conflating the two.
    idempotency_key must stay unique per payable thing, e.g.
    f"booking:{session_id}:payment_link" or f"deal:{deal_id}:payment_link".

    Returns dict with keys:
      - payment_link_url: str
      - razorpay_payment_link_id: str
      - payment_link_expires_at: str (ISO-8601 UTC; when Razorpay stops accepting payment)
    """
    expire_by = int(time.time()) + _LINK_EXPIRE_SECONDS

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "description": description,
        "customer": {
            "name": customer_name,
            "contact": customer_phone,
        },
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "notes": notes,
        # No callback_url: delivery is WhatsApp, not a browser redirect flow --
        # there is nothing to redirect back to, and the payment receipt is
        # already sent from the payment_link.paid webhook handler.
        "expire_by": expire_by,
    }

    resp = await _post(
        tenant_id, "/payment_links", json=payload,
        headers={"X-Razorpay-Idempotency-Key": idempotency_key},
    )

    if not resp.is_success:
        raise RuntimeError(
            f"Razorpay payment link creation failed: {resp.status_code} {resp.text}"
        )

    data = resp.json()
    return {
        "payment_link_url": data["short_url"],
        "razorpay_payment_link_id": data["id"],
        # Razorpay replays the ORIGINAL response for a reused idempotency key, so trust the
        # expiry it reports over the one we just computed.
        "payment_link_expires_at": datetime.fromtimestamp(
            data.get("expire_by") or expire_by, tz=timezone.utc
        ).isoformat(),
    }


async def cancel_payment_link(plink_id: str, tenant_id: str) -> bool:
    """Best-effort cancel of a Razorpay Payment Link so a replaced link can't be paid.

    Never raises: True only when Razorpay confirmed the cancel. Razorpay refuses to cancel a
    link that is already paid (or expired/cancelled); that comes back False too, and the
    paid webhook is what decides the outcome -- callers must treat False as "carry on",
    never as a reason to undo the replacement link."""
    if not plink_id:
        return False
    if not tenant_id:
        # Required, and never blank: a missing tenant would resolve to the default tenant's keys.
        logger.warning(f"Razorpay cancel of {plink_id} skipped: no tenant_id")
        return False
    try:
        resp = await _post(tenant_id, f"/payment_links/{plink_id}/cancel")
    except Exception as e:
        logger.warning(f"Razorpay cancel of {plink_id} failed: {type(e).__name__}: {e}")
        return False
    if not resp.is_success:
        logger.warning(f"Razorpay cancel of {plink_id} refused: {resp.status_code} (likely already paid or closed)")
        return False
    return True


def verify_webhook_signature(raw_body: bytes, received_signature: str, tenant_id: str | None = None) -> bool:
    """Verify Razorpay webhook payload using HMAC-SHA256.

    tenant_id must be the tenant that owns this payment, not omitted -- every
    tenant configures its own razorpay_webhook_secret, and omitting tenant_id
    checks against the bootstrapping default tenant's secret instead, which
    silently rejects every real tenant's webhook."""
    try:
        secret = _get_webhook_secret(tenant_id)
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received_signature)
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False
