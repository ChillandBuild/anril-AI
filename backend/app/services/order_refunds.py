"""Orders & payments > Cancel or refund. Owner, or a role with "deals.refund".

  cancel  -- nothing was paid: the order is just closed (lost).
  full    -- everything still held goes back; the order is closed and its stock returns
             (stock only ever moved if it was won).
  part    -- an amount goes back; the order stays as it is.

Money goes back by Razorpay (against the order's own link payments, newest first, never more
than was paid that way), or by cash / UPI / bank, recorded as given. Every refund row lowers
deals.refunded_paise' total (trigger, migration 295), so Money in, Meta Ads Earned and the
order page all net it out. A refund on a GST invoice gets a credit note number per financial
year ("CN/2026-27/0001"). The customer gets a WhatsApp ("refund started, 5-7 days" or "given
back by cash"), or a Share on WhatsApp link when it can't be sent.
"""
import logging

from app.services import deals as deals_service
from app.services import orders
from app.services.orders import IST, OrderError, _now, _rpc_int, fiscal_year

logger = logging.getLogger(__name__)

REASONS = ("Customer changed mind", "Wrong size / colour", "Damaged", "Late delivery", "Out of stock", "Other")
METHODS = ("razorpay", "cash", "upi", "bank_transfer")


def can_refund(ctx: dict) -> bool:
    return ctx.get("role") == "owner" or "deals.refund" in (ctx.get("permissions") or [])


def _credit_note(db, tenant_id: str) -> str | None:
    try:
        fy = fiscal_year(_now())
        n = _rpc_int(db.rpc("next_invoice_number", {"p_tenant_id": tenant_id, "p_fy": f"CN/{fy}"}).execute().data)
        return f"CN/{fy}/{n:04d}" if n else None
    except Exception as e:
        logger.warning(f"Credit note number failed for tenant {tenant_id}: {e}")
        return None


def _razorpay_payments(db, tenant_id: str, deal_id: str) -> list[dict]:
    """The order's link payments with what is still refundable on each, newest first."""
    paid = (
        db.table("deal_payments").select("razorpay_payment_id, amount_paise, paid_at").eq("tenant_id", tenant_id)
        .eq("deal_id", deal_id).eq("method", "razorpay").not_.is_("razorpay_payment_id", "null").execute()
    ).data or []
    back = (
        db.table("deal_refunds").select("razorpay_payment_id, amount_paise").eq("tenant_id", tenant_id)
        .eq("deal_id", deal_id).eq("method", "razorpay").neq("status", "failed").execute()
    ).data or []
    used: dict[str, int] = {}
    for r in back:
        used[r.get("razorpay_payment_id")] = used.get(r.get("razorpay_payment_id"), 0) + int(r["amount_paise"])
    out = []
    for p in sorted(paid, key=lambda p: str(p.get("paid_at") or ""), reverse=True):
        left = int(p["amount_paise"]) - used.get(p["razorpay_payment_id"], 0)
        if left > 0:
            out.append({"id": p["razorpay_payment_id"], "left": left})
    return out


def returnable_items(db, tenant_id: str, deal_id: str) -> dict[str, int]:
    """deal_item_id -> how many of it can still go back on the shelf (qty less earlier part refunds)."""
    lines = (
        db.table("deal_items").select("id, qty").eq("deal_id", deal_id).eq("tenant_id", tenant_id).execute()
    ).data or []
    back = (
        db.table("deal_refunds").select("items").eq("deal_id", deal_id).eq("tenant_id", tenant_id)
        .neq("status", "failed").execute()
    ).data or []
    used: dict[str, int] = {}
    for r in back:
        for it in r.get("items") or []:
            used[it.get("deal_item_id")] = used.get(it.get("deal_item_id"), 0) + int(it.get("qty") or 0)
    return {line["id"]: max(int(line["qty"]) - used.get(line["id"], 0), 0) for line in lines}


def _restock(db, tenant_id: str, deal_id: str, picked: list[dict], user_id: str | None) -> list[dict]:
    """Put the picked pieces back on the shelf (each line's own size/colour)."""
    if not picked:
        return []
    ids = [p["deal_item_id"] for p in picked]
    lines = {
        r["id"]: r for r in (
            db.table("deal_items").select("id, catalog_item_id, variant_id, name").eq("deal_id", deal_id)
            .eq("tenant_id", tenant_id).in_("id", ids).execute()
        ).data or []
    }
    warnings = []
    for p in picked:
        line = lines.get(p["deal_item_id"]) or {}
        if not line.get("catalog_item_id"):
            continue
        move = deals_service.adjust_variant_stock if line.get("variant_id") else deals_service.adjust_stock
        try:
            move(tenant_id, line.get("variant_id") or line["catalog_item_id"], int(p["qty"]), "return",
                 deal_id=deal_id, created_by=user_id, note="Part refund", db=db)
        except Exception as e:
            logger.warning(f"Refund restock of {line.get('name')} on {deal_id} failed: {e}")
            warnings.append(line.get("name"))
    return warnings


async def refund(db, tenant_id: str, deal_id: str, *, mode: str, amount_paise: int | None, method: str | None,
                 reason: str, user_id: str | None = None, sender: dict | None = None,
                 items: list[dict] | None = None) -> dict:
    if mode not in ("cancel", "full", "part"):
        raise OrderError("Pick cancel, full refund or part refund")
    reason = (reason or "").strip()[:200]
    if not reason:
        raise OrderError("Pick why")
    deal = orders._load(db, tenant_id, deal_id)
    if deal["stage"] == "lost" and mode != "part":
        raise OrderError("This order is already cancelled")
    held = max(int(deal.get("paid_paise") or 0) - int(deal.get("refunded_paise") or 0), 0)

    if mode == "cancel":
        if held:
            raise OrderError(f"{orders._rupees(held)} was paid on this order: pick Full refund instead")
        if not deals_service.mark_lost(tenant_id, deal_id, reason, created_by=user_id, db=db):
            raise OrderError("This order is already cancelled")
        return {"refunds": [], "message": None, "cancelled": True}

    if held <= 0:
        raise OrderError("Nothing was paid on this order, so there is nothing to refund")
    amount = held if mode == "full" else int(amount_paise or 0)
    if amount <= 0:
        raise OrderError("Type the amount to give back")
    if amount > held:
        raise OrderError(f"Only {orders._rupees(held)} is left to refund on this order")
    if method not in METHODS:
        raise OrderError("Pick how the money goes back")
    picked: list[dict] = []
    if mode == "part" and items:
        left_by_line = returnable_items(db, tenant_id, deal_id)
        for it in items:
            line_id, qty = str(it.get("deal_item_id") or ""), int(it.get("qty") or 0)
            if qty <= 0:
                continue
            if line_id not in left_by_line:
                raise OrderError("That item isn't on this order")
            if qty > left_by_line[line_id]:
                raise OrderError("More pieces picked than are left to return on that item")
            picked.append({"deal_item_id": line_id, "qty": qty})

    credit_note = _credit_note(db, tenant_id) if deal.get("invoice_number") and deal.get("bill_type", "gst") == "gst" else None
    rows: list[dict] = []
    if method == "razorpay":
        sources = _razorpay_payments(db, tenant_id, deal_id)
        available = sum(s["left"] for s in sources)
        if amount > available:
            raise OrderError(
                f"Only {orders._rupees(available)} was paid by link and can go back through Razorpay. "
                "Refund the rest by cash or UPI." if available else "Nothing on this order was paid by link: pick cash or UPI.")
        from app.services.payment_razorpay import RefundError, create_refund
        left = amount
        for source in sources:
            if left <= 0:
                break
            part = min(left, source["left"])
            key = f"r:{deal_id[:8]}:{source['id'][-12:]}:{int(deal.get('refunded_paise') or 0) + amount - left}:{part}"
            try:
                made = await create_refund(source["id"], part, tenant_id, idempotency_key=key,
                                           notes={"deal_id": deal_id, "reason": reason})
            except RefundError as e:
                if rows:  # some went through: keep what happened, tell staff the rest failed
                    break
                raise OrderError(str(e))
            seen = (db.table("deal_refunds").select("id").eq("razorpay_refund_id", made["id"]).limit(1).execute()).data if made.get("id") else None
            if not seen:
                rows.append({"tenant_id": tenant_id, "deal_id": deal_id, "amount_paise": part, "method": "razorpay",
                             "reason": reason, "status": "done" if made["status"] == "processed" else "pending",
                             "razorpay_payment_id": source["id"], "razorpay_refund_id": made.get("id"),
                             "created_by": user_id})
            left -= part
    else:
        rows.append({"tenant_id": tenant_id, "deal_id": deal_id, "amount_paise": amount, "method": method,
                     "reason": reason, "status": "done", "created_by": user_id})
    if not rows:
        raise OrderError("That refund was already made")
    if credit_note:
        rows[0]["credit_note_number"] = credit_note
    given = sum(r["amount_paise"] for r in rows)
    closes = mode == "full" and given >= held
    if closes and deal["stage"] == "won":
        rows[0]["restocked"] = True
    # Picked pieces go back on the shelf only if they left it (stock moves when an order is won).
    restock_now = picked and deal["stage"] == "won"
    if picked:
        rows[0]["items"] = picked
        rows[0]["restocked"] = bool(restock_now)
    db.table("deal_refunds").insert(rows).execute()
    if restock_now:
        _restock(db, tenant_id, deal_id, picked, user_id)
    if closes and deal["stage"] != "lost":
        deals_service.mark_lost(tenant_id, deal_id, f"Refunded · {reason}", created_by=user_id, db=db)
    message = await orders.notify(db, tenant_id, deal_id, "refund", user_id=user_id, sender=sender,
                                  extra={"_refund": {"amount_paise": given, "method": method}})
    partial = given < amount
    return {"refunds": rows, "message": message, "cancelled": closes, "credit_note": credit_note,
            "short_paise": amount - given if partial else 0, "ist_date": _now().astimezone(IST).date().isoformat()}
