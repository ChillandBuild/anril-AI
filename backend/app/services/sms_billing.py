# backend/app/services/sms_billing.py
"""SMS credit: recharges paid into ANRIL's own Razorpay account (not the client's — the
per-tenant Razorpay keys in app_settings are for the client's own customers), manual/bonus
credit from the operator console, and the ledger.

Recharge flow: client picks a pack → sms_payments row + Razorpay Payment Link → client pays →
/webhook/razorpay-sms (HMAC with SMS_RAZORPAY_WEBHOOK_SECRET) → claim created→paid once per
payment → Bulk9 reseller add-credit → credited + ledger row. If add-credit fails the row is
credit_failed and the operator retries from the console; a timed-out add-credit may still have
landed in Bulk9, so the error says to check before retrying.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

import httpx

from app.config_dynamic import get_setting
from app.services import bulk9_reseller
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout

logger = logging.getLogger(__name__)

PACKS_RUPEES = (500, 1000, 5000)
DEFAULT_PRICE = Decimal("0.25")
_RAZORPAY = "https://api.razorpay.com/v1"
_LINK_EXPIRE = timedelta(hours=24)
_MAX_OPEN_LINKS = 3
AMOUNT_MISMATCH = "Paid amount does not match the pack"


class BillingNotConfigured(RuntimeError):
    pass


def price_per_sms(tenant_id: str) -> Decimal:
    raw = get_setting("sms_price_per_sms", tenant_id=tenant_id)
    try:
        p = Decimal(str(raw)) if raw else DEFAULT_PRICE
    except InvalidOperation:
        p = DEFAULT_PRICE
    return p if p > 0 else DEFAULT_PRICE


def buy_rate(tenant_id: str) -> Decimal | None:
    raw = get_setting("sms_buy_rate", tenant_id=tenant_id)
    try:
        return Decimal(str(raw)) if raw else None
    except InvalidOperation:
        return None


def sms_for_amount(amount_rupees: int, price: Decimal) -> int:
    return int((Decimal(amount_rupees) / price).to_integral_value(rounding=ROUND_DOWN))


def packs(tenant_id: str) -> list[dict]:
    price = price_per_sms(tenant_id)
    return [{"amount_rupees": a, "sms_count": sms_for_amount(a, price), "price_per_sms": float(price)}
            for a in PACKS_RUPEES]


def _rzp_keys() -> tuple[str, str]:
    kid = os.environ.get("SMS_RAZORPAY_KEY_ID", "").strip()
    sec = os.environ.get("SMS_RAZORPAY_KEY_SECRET", "").strip()
    if not kid or not sec:
        raise BillingNotConfigured("SMS recharge is not set up yet")
    return kid, sec


def verify_webhook(raw_body: bytes, signature: str) -> bool:
    secret = os.environ.get("SMS_RAZORPAY_WEBHOOK_SECRET", "").strip()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _ledger(db, tenant_id: str, *, kind: str, sms_count: int, price: Decimal, reference: str | None,
            note: str | None, created_by: str | None, expiry_date: str | None = None) -> None:
    rate = buy_rate(tenant_id)
    db.table("sms_ledger").insert({
        "tenant_id": tenant_id, "kind": kind, "sms_count": sms_count,
        "price_per_sms": str(price), "buy_rate": str(rate) if rate is not None else None,
        "amount": str((price * sms_count).quantize(Decimal("0.01"))) if kind != "bonus" else "0",
        "expiry_date": expiry_date, "reference": reference, "note": note, "created_by": created_by,
    }).execute()


def _username(tenant_id: str) -> str:
    u = get_setting("bulk9_username", tenant_id=tenant_id)
    if not u:
        raise Bulk9Error("This client has no Bulk9 account linked")
    return u


# ---------------------------------------------------------------- recharge

async def create_recharge(db, tenant_id: str, *, amount_rupees: int, user_id: str | None,
                          customer_name: str | None = None) -> dict:
    if amount_rupees not in PACKS_RUPEES:
        raise ValueError("Pick one of the recharge packs")
    _username(tenant_id)  # fail before taking money for an account we can't credit
    kid, sec = _rzp_keys()
    price = price_per_sms(tenant_id)
    cost = buy_rate(tenant_id)
    if cost is not None and price < cost:
        logger.error("SMS price %s is below buy rate %s for tenant %s", price, cost, tenant_id)
        raise BillingNotConfigured("SMS recharge is not available right now. Please contact support.")
    since = (datetime.now(timezone.utc) - _LINK_EXPIRE).isoformat()
    open_links = (db.table("sms_payments").select("id").eq("tenant_id", tenant_id).eq("status", "created")
                  .gte("created_at", since).limit(_MAX_OPEN_LINKS).execute().data or [])
    if len(open_links) >= _MAX_OPEN_LINKS:
        raise ValueError("You already have unpaid recharge links. Pay one of those, or wait for them to expire.")
    count = sms_for_amount(amount_rupees, price)
    row = db.table("sms_payments").insert({
        "tenant_id": tenant_id, "amount_paise": amount_rupees * 100, "sms_count": count,
        "price_per_sms": str(price), "created_by": user_id,
    }).execute().data[0]
    body = {
        "amount": amount_rupees * 100, "currency": "INR", "accept_partial": False,
        "reference_id": row["id"],
        "description": f"Anril SMS recharge: {count} SMS",
        "expire_by": int((datetime.now(timezone.utc) + _LINK_EXPIRE).timestamp()),
        "reminder_enable": False,
        "notes": {"sms_payment_id": row["id"], "tenant_id": tenant_id},
    }
    if customer_name:
        body["customer"] = {"name": customer_name[:100]}
    async with httpx.AsyncClient(auth=(kid, sec), timeout=15.0) as client:
        resp = await client.post(f"{_RAZORPAY}/payment_links", json=body,
                                 headers={"X-Razorpay-Idempotency-Key": row["id"]})
    if resp.status_code >= 400:
        db.table("sms_payments").update({"status": "cancelled", "error": f"Razorpay HTTP {resp.status_code}"}) \
            .eq("id", row["id"]).execute()
        logger.error("SMS recharge link failed: HTTP %s", resp.status_code)
        raise BillingNotConfigured("Could not create the payment link. Please try again.")
    link = resp.json()
    db.table("sms_payments").update({"razorpay_link_id": link.get("id"), "short_url": link.get("short_url")}) \
        .eq("id", row["id"]).execute()
    return {"payment_id": row["id"], "short_url": link.get("short_url")}


async def handle_razorpay_event(db, payload: dict) -> dict:
    """Signature already verified. Only payment_link.paid / .expired / .cancelled matter."""
    event = payload.get("event", "")
    p = payload.get("payload") or {}
    link = (p.get("payment_link") or {}).get("entity") or {}
    payment = (p.get("payment") or {}).get("entity") or {}
    payment_id_ref = (link.get("notes") or {}).get("sms_payment_id") or link.get("reference_id")
    if not payment_id_ref:
        return {"status": "ignored"}
    rows = db.table("sms_payments").select("*").eq("id", payment_id_ref).limit(1).execute().data or []
    if not rows:
        return {"status": "ignored"}
    row = rows[0]
    if link.get("id") and row.get("razorpay_link_id") and link["id"] != row["razorpay_link_id"]:
        logger.warning("SMS recharge webhook: link id mismatch for %s", row["id"])
        return {"status": "ignored"}

    if event in ("payment_link.expired", "payment_link.cancelled"):
        db.table("sms_payments").update({"status": "expired" if event.endswith("expired") else "cancelled"}) \
            .eq("id", row["id"]).eq("status", "created").execute()
        return {"status": "ok"}
    if event != "payment_link.paid":
        return {"status": "ignored"}

    paid_paise = payment.get("amount") or link.get("amount_paid")
    if int(paid_paise or 0) != int(row["amount_paise"]):
        logger.error("SMS recharge %s: paid %s paise, expected %s", row["id"], paid_paise, row["amount_paise"])
        db.table("sms_payments").update({"status": "amount_mismatch", "error": AMOUNT_MISMATCH}) \
            .eq("id", row["id"]).eq("status", "created").execute()
        return {"status": "amount_mismatch"}

    # The claim: only the first delivery of this webhook moves created → paid and credits.
    claim = db.table("sms_payments").update({
        "status": "paid", "razorpay_payment_id": payment.get("id"),
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", row["id"]).eq("status", "created").execute()
    if not claim.data:
        return {"status": "duplicate"}
    await credit_payment(db, {**row, "razorpay_payment_id": payment.get("id")})
    return {"status": "ok"}


async def credit_payment(db, row: dict) -> bool:
    """Add a paid recharge's SMS in Bulk9. Used by the webhook and by the operator's retry
    (which first moves credit_failed → paid itself)."""
    tenant_id = row["tenant_id"]
    price = Decimal(str(row["price_per_sms"]))
    try:
        await bulk9_reseller.add_sms_credit(_username(tenant_id), sms_count=int(row["sms_count"]),
                                            price_per_sms=price)
    except Bulk9Timeout:
        _fail(db, row, "Bulk9 did not answer. Check the client's balance in Bulk9 before retrying.")
        return False
    except (Bulk9Error, bulk9_reseller.ResellerNotConfigured, ValueError) as exc:
        _fail(db, row, str(exc))
        return False
    db.table("sms_payments").update({"status": "credited", "error": None,
                                     "credited_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("id", row["id"]).eq("status", "paid").execute()
    _ledger(db, tenant_id, kind="recharge", sms_count=int(row["sms_count"]), price=price,
            reference=row.get("razorpay_payment_id") or row["id"], note=None, created_by=row.get("created_by"))
    return True


def _fail(db, row: dict, error: str) -> None:
    logger.error("SMS recharge %s not credited: %s", row["id"], error)
    db.table("sms_payments").update({"status": "credit_failed", "error": error[:300]}) \
        .eq("id", row["id"]).eq("status", "paid").execute()


# ---------------------------------------------------------------- operator credit

async def manual_credit(db, tenant_id: str, *, kind: str, sms_count: int, price: Decimal | None,
                        expiry_date: date | None, note: str | None, actor: str | None) -> None:
    if kind not in ("manual_credit", "bonus"):
        raise ValueError("kind must be manual_credit or bonus")
    p = price or price_per_sms(tenant_id)
    exp = expiry_date.isoformat() if expiry_date else None
    await bulk9_reseller.add_sms_credit(_username(tenant_id), sms_count=sms_count, price_per_sms=p,
                                        expiry_date=exp)
    _ledger(db, tenant_id, kind=kind, sms_count=sms_count, price=p, reference=None, note=note,
            created_by=actor, expiry_date=exp)


async def manual_debit(db, tenant_id: str, *, sms_count: int, note: str | None, actor: str | None) -> None:
    await bulk9_reseller.debit_sms_credit(_username(tenant_id), sms_count=sms_count)
    _ledger(db, tenant_id, kind="debit", sms_count=-sms_count, price=price_per_sms(tenant_id),
            reference=None, note=note, created_by=actor)


def profit(db, tenant_id: str) -> dict[str, Any]:
    """From what was actually charged per SMS (delivery data), not from credit sold."""
    rows = (db.table("sms_messages").select("sms_count, charged_amount, cost_amount")
            .eq("tenant_id", tenant_id).not_.is_("charged_amount", "null").limit(100000).execute().data or [])
    sold = sum(int(r.get("sms_count") or 0) for r in rows)
    revenue = sum(Decimal(str(r.get("charged_amount") or 0)) for r in rows)
    cost = sum(Decimal(str(r.get("cost_amount") or 0)) for r in rows)
    return {"sms_sold": sold, "revenue": float(revenue), "cost": float(cost), "profit": float(revenue - cost)}
