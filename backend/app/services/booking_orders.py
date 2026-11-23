"""Bookings ↔ Orders (v9.2 #19). The only place a booking touches money.

A booking never handles money itself. It makes a normal order through the existing order code
(services/deals.py, Keerthi's), so payments, Razorpay, the payment webhook, refunds and bills all
work exactly as they do for any other order:

  * advance on a booking  -> create_deal(quoted) with the service's catalogue item as the one line,
                             then send_payment_link(amount=advance). The Razorpay webhook records the
                             payment on that deal as usual; bookings read `advance_paid` from it.
  * "Came"                -> the booking's order if it has one, else a new order for the service.
                             Staff finish the bill on the order page (collect the rest / mark paid).

Nothing here edits deals.py; it only calls its public functions.
"""
from __future__ import annotations

import logging

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# The booking's "came from" -> the order's source (deals.SOURCES).
_DEAL_SOURCE = {"link": "form", "chat": "whatsapp", "ai": "whatsapp", "phone": "call", "walk_in": "walk_in"}


class BookingOrderError(Exception):
    """Plain-words reason the order could not be made; safe to show."""


def advance_due(tenant_id: str, service: dict, no_shows: int, no_show_limit: int) -> int:
    """The advance this booking must pay, in paise.

    The service's own advance wins. Otherwise a customer with `no_show_limit` or more no-shows pays
    the business's advance rule (My business › Payments & advance), or 50% when that rule is "none".
    """
    price = int(service.get("price_paise") or 0)
    own = int(service.get("advance_paise") or 0)
    if own > 0:
        return min(own, price) if price > 0 else own
    if no_shows < no_show_limit or price <= 0:
        return 0
    from app.services.order_quotes import advance_for, advance_rule

    amount = advance_for(price, advance_rule(tenant_id))
    return amount if amount > 0 else round(price / 2)


async def _new_order(tenant_id: str, booking: dict, service: dict, *, created_by: str | None, db) -> dict:
    from app.services import deals

    if not booking.get("lead_id"):
        raise BookingOrderError("This booking has no customer to bill")
    if not service.get("catalog_item_id"):
        raise BookingOrderError("This service is not in the catalogue yet; save it again on Services & timings")
    number = f"BK-{int(booking['number']):04d}"
    try:
        return await deals.create_deal(
            tenant_id,
            booking["lead_id"],
            [{"catalog_item_id": service["catalog_item_id"], "qty": 1}],
            _DEAL_SOURCE.get(booking.get("source") or "", "manual"),
            "quoted",
            notes=f"Booking {number}",
            created_by=created_by,
            db=db,
        )
    except deals.DealError as e:
        raise BookingOrderError(str(e)) from e


async def create_advance_order(tenant_id: str, booking: dict, service: dict, amount_paise: int, *,
                               send_whatsapp_message: bool = False, created_by: str | None = None,
                               db=None) -> dict:
    """Make the order for a booking's advance and a Razorpay link for just the advance.

    Returns {"deal_id", "payment_url", "message_sent"} and stores deal_id + advance_paise on the
    booking. The caller decides the booking status (held / booked).
    """
    from app.services import deals

    db = db or get_supabase()
    if amount_paise <= 0:
        raise BookingOrderError("No advance is needed")
    deal = await _new_order(tenant_id, booking, service, created_by=created_by, db=db)
    total = int(deal.get("total_paise") or 0)
    amount = min(int(amount_paise), total) if total > 0 else int(amount_paise)
    try:
        sent = await deals.send_payment_link(
            tenant_id, deal["id"], send_whatsapp_message=send_whatsapp_message, amount_paise=amount, db=db
        )
    except deals.DealError as e:
        raise BookingOrderError(str(e)) from e
    db.table("bookings").update({"deal_id": deal["id"], "advance_paise": amount}).eq("id", booking["id"]).eq(
        "tenant_id", tenant_id
    ).execute()
    return {"deal_id": deal["id"], "payment_url": sent.get("payment_link"), "message_sent": bool(sent.get("message_sent"))}


def advance_paid(tenant_id: str, booking: dict, db=None) -> bool:
    """True when the booking's order has collected at least the advance (refunds taken off)."""
    if not booking.get("deal_id"):
        return int(booking.get("advance_paise") or 0) == 0
    db = db or get_supabase()
    row = (
        db.table("deals").select("paid_paise, refunded_paise, stage")
        .eq("id", booking["deal_id"]).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not row:
        return False
    paid = int(row[0].get("paid_paise") or 0) - int(row[0].get("refunded_paise") or 0)
    return paid >= int(booking.get("advance_paise") or 0) > 0 or row[0].get("stage") == "won"


def advance_paid_many(tenant_id: str, bookings: list[dict], db=None) -> dict[str, bool]:
    """advance_paid for many bookings with ONE deals read (Day / Week boards). {booking_id: bool}."""
    out: dict[str, bool] = {}
    deal_ids = sorted({b["deal_id"] for b in bookings if b.get("deal_id")})
    deals_by_id: dict[str, dict] = {}
    if deal_ids:
        db = db or get_supabase()
        for i in range(0, len(deal_ids), 100):
            rows = (
                db.table("deals").select("id, paid_paise, refunded_paise, stage")
                .eq("tenant_id", tenant_id).in_("id", deal_ids[i:i + 100]).execute()
            ).data or []
            deals_by_id.update({r["id"]: r for r in rows})
    for b in bookings:
        advance = int(b.get("advance_paise") or 0)
        if not b.get("deal_id"):
            out[b["id"]] = advance == 0
            continue
        row = deals_by_id.get(b["deal_id"])
        if not row:
            out[b["id"]] = False
            continue
        paid = int(row.get("paid_paise") or 0) - int(row.get("refunded_paise") or 0)
        out[b["id"]] = (paid >= advance > 0) or row.get("stage") == "won"
    return out


def release_unpaid_order(tenant_id: str, booking: dict, db=None) -> None:
    """A held slot whose advance was never paid: close its open order as lost. Never raises."""
    if not booking.get("deal_id"):
        return
    try:
        from app.services import deals

        deals.mark_lost(tenant_id, booking["deal_id"], "Booking advance not paid in time",
                        only_from=("quoted", "awaiting_payment"), db=db or get_supabase())
    except Exception as e:  # the booking is released either way
        logger.warning("booking %s: could not close unpaid order %s: %s", booking.get("id"), booking.get("deal_id"), e)


async def order_for_came(tenant_id: str, booking: dict, service: dict, *, created_by: str | None = None,
                         db=None) -> str:
    """'Came' -> the order to finish the bill on: the booking's own order, else a new one."""
    db = db or get_supabase()
    if booking.get("deal_id"):
        return booking["deal_id"]
    deal = await _new_order(tenant_id, booking, service, created_by=created_by, db=db)
    db.table("bookings").update({"deal_id": deal["id"]}).eq("id", booking["id"]).eq("tenant_id", tenant_id).execute()
    return deal["id"]
