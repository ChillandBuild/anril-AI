"""Deals: one row per sale attempt, from every source (AI chat, intake form,
call, walk-in, manual, marketplaces). See
docs/superpowers/specs/2026-09-25-deals-crm-design.md and 204_deals.sql.

This module is the ONLY place that moves a deal between stages or touches
stock, so the rules live in one spot:
  - money is deal_payments rows (migration 294); a deal is WON only when paid in full,
    and mark_won records whatever was still due, so every paid deal's money is counted;
  - stock deducts on WON only, and a won deal later marked lost returns it;
  - a line with a size/colour (variant_id) moves that size's stock, and the item total with it;
  - prices are snapshotted onto deal_items when written, never re-read live;
  - a stock problem never fails a sale -- the money is real regardless of what
    the ledger says, so callers get stock_warnings instead of an error.
"""
import logging
from datetime import datetime, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

STAGES = ("quoted", "awaiting_payment", "won", "lost")
SOURCES = ("whatsapp", "form", "call", "walk_in", "manual", "indiamart", "justdial")
PAYMENT_METHODS = ("razorpay", "cash", "upi", "card", "bank_transfer", "other")
LOW_STOCK_THRESHOLD = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_deal_number(db, tenant_id: str) -> int:
    """next_deal_number returns a scalar; PostgREST may hand it back bare or
    wrapped in a list/row depending on client version -- accept all three."""
    data = db.rpc("next_deal_number", {"p_tenant_id": tenant_id}).execute().data
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        data = next(iter(data.values()), None)
    if data is None:
        raise DealError("Couldn't allocate a deal number")
    return int(data)


def format_deal_number(n: int) -> str:
    return f"D-{n:04d}"


def _rupees(amount_paise: int) -> str:
    """Same convention as intake._rupees: whole rupees when exact."""
    if amount_paise % 100 == 0:
        return f"₹{amount_paise // 100:,}"
    return f"₹{amount_paise / 100:,.2f}"


def quote_summary_block(lines: list[dict], total_paise: int) -> str:
    """Rendered in Python, never by the LLM: these are prices the customer
    will be held to, and a hallucinated figure is a real liability."""
    rows = [f"• {li['name']} x{li['qty']} — {_rupees(li['line_total_paise'])}" for li in lines]
    rows.append(f"Total: {_rupees(total_paise)}")
    return "\n".join(rows)


def get_deal_tenant_id(deal_id: str, db=None) -> str | None:
    """Which tenant owns a deal, so the Razorpay webhook can verify the
    signature against that tenant's secret. Safe before the payload is
    trusted: a forged id is a miss or another tenant's id, and the HMAC check
    against that tenant's real secret still fails."""
    db = db or get_supabase()
    res = db.table("deals").select("tenant_id").eq("id", deal_id).maybe_single().execute()
    if not res or not res.data:
        return None
    return res.data["tenant_id"]


# ---------------------------------------------------------------- stock

def adjust_stock(
    tenant_id: str,
    item_id: str,
    delta: int,
    reason: str,
    *,
    note: str | None = None,
    created_by: str | None = None,
    deal_id: str | None = None,
    place_id: str | None = None,
    first_place_id: str | None = None,
    batch_id: str | None = None,
    deal_item_id: str | None = None,
    new_batch: dict | None = None,
    db=None,
) -> dict:
    """Thin wrapper over apply_stock_movement (204_deals.sql, per place since 304), which changes
    the count and logs the movement in one statement. No place = the business's bill place."""
    db = db or get_supabase()
    params = {
        "p_tenant_id": tenant_id,
        "p_item_id": item_id,
        "p_delta": delta,
        "p_reason": reason,
        "p_deal_id": deal_id,
        "p_note": note,
        "p_created_by": created_by,
    }
    if place_id:
        params["p_place_id"] = place_id
    elif first_place_id:  # start here, then the other places (309)
        params["p_first_place"] = first_place_id
    if batch_id:  # this batch exactly (310)
        params["p_batch_id"] = batch_id
    if deal_item_id:  # remember which batches this bill line took
        params["p_deal_item_id"] = deal_item_id
    if new_batch:  # stock in: batch no., expiry, cost, supplier
        params["p_new_batch"] = new_batch
    res = db.rpc("apply_stock_movement", params).execute()
    row = (res.data or [{}])[0] if isinstance(res.data, list) else (res.data or {})
    return {
        "ok": bool(row.get("ok")),
        "tracked": bool(row.get("tracked")),
        "quantity_after": row.get("quantity_after"),
    }


def adjust_variant_stock(
    tenant_id: str,
    variant_id: str,
    delta: int,
    reason: str,
    *,
    note: str | None = None,
    created_by: str | None = None,
    deal_id: str | None = None,
    place_id: str | None = None,
    first_place_id: str | None = None,
    batch_id: str | None = None,
    deal_item_id: str | None = None,
    new_batch: dict | None = None,
    db=None,
) -> dict:
    """apply_variant_stock_movement (294, per place since 304): one size/colour's stock and the item
    total, logged. No place = the business's bill place."""
    db = db or get_supabase()
    params = {
        "p_tenant_id": tenant_id,
        "p_variant_id": variant_id,
        "p_delta": delta,
        "p_reason": reason,
        "p_deal_id": deal_id,
        "p_note": note,
        "p_created_by": created_by,
    }
    if place_id:
        params["p_place_id"] = place_id
    elif first_place_id:  # start here, then the other places (309)
        params["p_first_place"] = first_place_id
    if batch_id:  # this batch exactly (310)
        params["p_batch_id"] = batch_id
    if deal_item_id:  # remember which batches this bill line took
        params["p_deal_item_id"] = deal_item_id
    if new_batch:  # stock in: batch no., expiry, cost, supplier
        params["p_new_batch"] = new_batch
    res = db.rpc("apply_variant_stock_movement", params).execute()
    row = (res.data or [{}])[0] if isinstance(res.data, list) else (res.data or {})
    return {"ok": bool(row.get("ok")), "tracked": True, "quantity_after": row.get("quantity_after")}


def held_quantities(tenant_id: str, item_ids: list[str], db=None) -> dict[str, int]:
    """Units promised to customers who have a payment link but haven't paid:
    sum of qty on awaiting_payment deals. Computed, never stored, so it can't
    drift when a link expires or is paid. One inner-joined query filtered in
    Python -- passing deal or item id lists would blow the URL length limit
    for a busy tenant."""
    if not item_ids:
        return {}
    db = db or get_supabase()
    wanted = set(item_ids)
    rows = (
        db.table("deal_items")
        .select("catalog_item_id, qty, deals!inner(stage)")
        .eq("tenant_id", tenant_id)
        .eq("deals.stage", "awaiting_payment")
        .limit(5000)
        .execute()
    ).data or []
    held: dict[str, int] = {}
    for r in rows:
        item_id = r.get("catalog_item_id")
        if item_id in wanted:
            held[item_id] = held.get(item_id, 0) + (r.get("qty") or 0)
    return held


def _deduct_for_deal(tenant_id: str, deal_id: str, created_by: str | None, db, *, direction: int) -> list[dict]:
    """direction=-1 sells (reason 'sale'), +1 returns (reason 'return').
    Returns warnings for lines whose stock couldn't be moved."""
    items = (
        db.table("deal_items")
        .select("id, catalog_item_id, variant_id, name, qty, batch_id")
        .eq("deal_id", deal_id)
        .eq("tenant_id", tenant_id)
        .execute()
    ).data or []
    warnings: list[dict] = []
    taken: dict[str, dict[str, int]] = {}  # returns go back into the batches each line took (310)
    if direction > 0 and items:
        try:
            for p in (db.table("deal_item_batches").select("deal_item_id, batch_id, quantity").eq("tenant_id", tenant_id)
                      .in_("deal_item_id", [i["id"] for i in items if i.get("id")]).execute().data or []):
                line = taken.setdefault(p["deal_item_id"], {})
                line[p["batch_id"]] = line.get(p["batch_id"], 0) + int(p["quantity"])
        except Exception:
            logger.warning("Couldn't read the batches deal %s took; returning stock without them", deal_id)
    reason = "sale" if direction < 0 else "return"
    first_place = None  # counter bills: the bill place; online orders: where they are packed
    if items:
        try:
            deal = (db.table("deals").select("channel, place_id").eq("id", deal_id).eq("tenant_id", tenant_id)
                    .limit(1).execute()).data or []
            if deal and isinstance(deal[0].get("place_id"), str):  # a counter bill made by staff of a place
                first_place = deal[0]["place_id"]
            elif not deal or deal[0].get("channel") != "store":
                from app.services.stock_places import online_first_place
                first_place = online_first_place(db, tenant_id)
        except Exception:
            logger.warning("Couldn't pick the stock place for deal %s; using the bill place", deal_id)
    for item in items:
        if not item.get("catalog_item_id"):
            continue
        try:
            move = adjust_variant_stock if item.get("variant_id") else adjust_stock
            target = item.get("variant_id") or item["catalog_item_id"]
            common = {"deal_id": deal_id, "created_by": created_by, "first_place_id": first_place,
                      "deal_item_id": item.get("id"), "db": db}
            left = int(item["qty"])
            result = {"ok": True, "quantity_after": None}
            if direction > 0:  # back into the same batches first
                for batch_id, qty in (taken.get(item.get("id") or "") or {}).items():
                    back = min(qty, left)
                    if back > 0 and move(tenant_id, target, back, reason, batch_id=batch_id, **common)["ok"]:
                        left -= back
            elif item.get("batch_id"):  # the batch staff chose on the bill
                result = move(tenant_id, target, -left, reason, batch_id=item["batch_id"], **common)
                left = 0 if result["ok"] else left
            if left > 0:
                result = move(tenant_id, target, direction * left, reason, **common)
            if not result["ok"]:
                warnings.append({
                    "catalog_item_id": item["catalog_item_id"],
                    "name": item["name"],
                    "available": result["quantity_after"],
                })
        except Exception as e:
            logger.warning(f"Stock {reason} failed for deal {deal_id}, item {item['catalog_item_id']}: {e}")
            warnings.append({"catalog_item_id": item["catalog_item_id"], "name": item["name"], "available": None})
    return warnings


# ---------------------------------------------------------------- lines

class DealError(ValueError):
    """A caller mistake (unknown item, missing price) -- routes turn it into a 400."""


def _resolve_lines(tenant_id: str, lines: list[dict], db) -> list[dict]:
    """Fill missing price / GST from the real catalog row (tenant-scoped), so
    a caller -- including the AI tool handler -- can never invent a price."""
    item_ids = [li["catalog_item_id"] for li in lines if li.get("catalog_item_id")]
    variant_ids = [li["variant_id"] for li in lines if li.get("variant_id")]
    variants: dict[str, dict] = {}
    if variant_ids:
        rows = (
            db.table("catalog_item_variants")
            .select("id, catalog_item_id, size, colour, price_paise")
            .eq("tenant_id", tenant_id)
            .in_("id", variant_ids)
            .execute()
        ).data or []
        variants = {r["id"]: r for r in rows}
    catalog: dict[str, dict] = {}
    if item_ids:
        rows = (
            db.table("catalog_items")
            .select("id, name, price_paise, gst_rate, tracks_batches")
            .eq("tenant_id", tenant_id)
            .in_("id", item_ids)
            .execute()
        ).data or []
        catalog = {r["id"]: r for r in rows}

    resolved = []
    for li in lines:
        qty = int(li.get("qty") or 1)
        if qty < 1:
            raise DealError("Quantity must be at least 1")
        item_id = li.get("catalog_item_id")
        item = catalog.get(item_id) if item_id else None
        if item_id and not item:
            raise DealError("Product not found")
        variant = None
        if li.get("variant_id"):
            variant = variants.get(li["variant_id"])
            if not variant or variant["catalog_item_id"] != item_id:
                raise DealError("That size or colour isn't on this product")
        name = (li.get("name") or (item or {}).get("name") or "").strip()
        if not name:
            raise DealError("Each line needs a product name")
        price = li.get("unit_price_paise")
        from_catalog = price is None
        if price is None and variant and variant.get("price_paise") is not None:
            price = variant["price_paise"]
        if price is None and item:
            price = item.get("price_paise")
        if price is None:
            raise DealError(f"No price for {name}")
        batch_extra: dict = {}
        if item and item.get("tracks_batches") is True:  # Batches & expiry (310)
            from app.services import stock_batches as sb
            wanted = li.get("batch_id") or None
            sale, batch = sb.sale_price(db, tenant_id, item_id, (variant or {}).get("id"), int(price), wanted)
            if wanted and not batch:
                raise DealError(f"That batch of {name} can't be sold (expired or none left). Pick another.")
            if wanted and int(batch.get("quantity") or 0) < qty:
                raise DealError(f"That batch of {name} has only {batch['quantity']}. Lower the quantity or pick another batch.")
            if from_catalog:
                price = sale
            if wanted:
                batch_extra = {"batch_id": wanted}
        if price < 0:
            raise DealError("Price must not be negative")
        gst = li.get("gst_rate")
        if gst is None and item:
            gst = item.get("gst_rate")
        extra = {"variant_id": variant["id"], "variant_label": variant_label(variant)} if variant else {}
        resolved.append({
            **extra,
            **batch_extra,
            "catalog_item_id": item_id,
            "name": name,
            "qty": qty,
            "unit_price_paise": int(price),
            "gst_rate": float(gst) if gst is not None else None,
            "line_total_paise": int(price) * qty,
        })
    if not resolved:
        raise DealError("A deal needs at least one item")
    return resolved


def variant_label(variant: dict) -> str:
    """"Red · M"; just "M" or "Red" when the item has only one of them."""
    return " · ".join(v for v in (variant.get("colour"), variant.get("size")) if v)


def _deal_total(tenant_id: str, lines: list[dict], db) -> int:
    """What the customer pays. When the tenant's prices EXCLUDE GST, the tax is
    added on top here, so the payment link charges the right amount; line
    totals stay pre-tax for the export's taxable-value column."""
    subtotal = sum(li["line_total_paise"] for li in lines)
    from app.services.business_details import charges_gst, prices_include_gst
    if prices_include_gst(tenant_id, db) or not charges_gst(tenant_id, db):
        return subtotal
    tax = sum(round(li["line_total_paise"] * li["gst_rate"] / 100) for li in lines if li.get("gst_rate"))
    return subtotal + tax


def _charges_gst(tenant_id: str, db) -> bool:
    from app.services.business_details import charges_gst
    return charges_gst(tenant_id, db)


def _insert_items(tenant_id: str, deal_id: str, lines: list[dict], db) -> list[dict]:
    rows = [{**li, "deal_id": deal_id, "tenant_id": tenant_id} for li in lines]
    return db.table("deal_items").insert(rows).execute().data or []


# ---------------------------------------------------------------- create

async def create_deal(
    tenant_id: str,
    lead_id: str,
    lines: list[dict],
    source: str,
    stage: str = "quoted",
    *,
    payment_method: str | None = None,
    notes: str | None = None,
    created_by: str | None = None,
    intake_session_id: str | None = None,
    send_link: bool = False,
    advance_paise: int | None = None,
    advance_by_rule: bool = False,
    db=None,
) -> dict:
    """Create a deal with its lines. stage='won' deducts stock now;
    send_link=True creates the Razorpay link and moves it to awaiting_payment
    (and messages the customer on WhatsApp)."""
    db = db or get_supabase()
    if source not in SOURCES:
        raise DealError(f"Unknown source {source}")
    if stage not in STAGES or stage == "lost":
        raise DealError(f"A new deal can't start as {stage}")
    if payment_method and payment_method not in PAYMENT_METHODS:
        raise DealError(f"Unknown payment method {payment_method}")

    resolved = _resolve_lines(tenant_id, lines, db)
    row = {
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "deal_number": _next_deal_number(db, tenant_id),
        "stage": "quoted" if stage == "awaiting_payment" else stage,
        "source": source,
        "total_paise": _deal_total(tenant_id, resolved, db),
        "payment_method": payment_method,
        "notes": notes,
        "created_by": created_by,
        "intake_session_id": intake_session_id,
    }
    if not _charges_gst(tenant_id, db):
        row["bill_type"] = "simple"  # composition / unregistered: the order is born a Bill of supply (no tax)
    if stage == "won":
        row["won_at"] = _now_iso()
        row["payment_method"] = payment_method or "cash"
    link_amount = None
    if advance_by_rule and stage == "awaiting_payment":  # each item's own advance rule, else the shop's (315)
        from app.services.order_quotes import order_advance
        advance_paise = order_advance(db, tenant_id, resolved, row["total_paise"])
    if advance_paise is not None and stage == "awaiting_payment" and 0 < int(advance_paise) < row["total_paise"]:
        # the link asks only the advance; the rest is paid later (like a staff quote's advance)
        link_amount = int(advance_paise)
        row["advance_paise"] = link_amount
    deal = db.table("deals").insert(row).execute().data[0]
    items = _insert_items(tenant_id, deal["id"], resolved, db)

    result = {"deal": deal, "items": items, "payment_link": None, "message_sent": False, "stock_warnings": []}
    if stage == "won":
        result["stock_warnings"] = _deduct_for_deal(tenant_id, deal["id"], created_by, db, direction=-1)
    elif stage == "awaiting_payment" or send_link:
        # The AI's send_quote tool passes send_link=False: the link goes out in
        # its own reply text, so a second WhatsApp message would duplicate it.
        link = await send_payment_link(tenant_id, deal["id"], send_whatsapp_message=send_link, amount_paise=link_amount,
                                       db=db)
        result["payment_link"] = link["payment_link"]
        result["message_sent"] = link["message_sent"]
        result["deal"] = {**deal, **link.get("deal_patch", {})}
    return result


# ---------------------------------------------------------------- payment link

def _link_is_live(deal: dict) -> bool:
    """The shared liveness rule (deal_engine.link_is_live) applied to a deal row: awaiting
    payment, a stored link, not about to expire. A deal row keeps no separate link amount --
    its link is always made for total_paise and re-made whenever that moves -- so the amount
    check compares total_paise with itself."""
    from app.services import deal_engine
    view = {
        "status": deal_engine.AWAITING_PAYMENT_STATUS if deal.get("stage") == "awaiting_payment" else deal.get("stage"),
        "payment_link": deal.get("payment_link"),
        "amount_paise": deal.get("total_paise"),
        "payment_link_expires_at": deal.get("link_expires_at"),
    }
    return deal_engine.link_is_live(view, deal.get("total_paise"))


async def _cancel_replaced_link(before: dict, new_plink_id: str | None) -> bool:
    """Best-effort cancel of the deal's previous Razorpay link, after the new one is stored.
    Skips when there was no link, it is the same link, or it already expired. Never raises."""
    try:
        from app.services import deal_engine
        old = before.get("razorpay_payment_link_id")
        if not old or old == new_plink_id or not before.get("payment_link"):
            return False
        expires_at = deal_engine.parse_time(before.get("link_expires_at"))
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            return False
        from app.services.payment_razorpay import cancel_payment_link
        return await cancel_payment_link(old, before["tenant_id"])
    except Exception as e:
        logger.warning(f"Deal {before.get('id')}: cancelling the old payment link failed: {e}")
        return False


def _lead_contact(tenant_id: str, lead_id: str, db) -> dict:
    res = db.table("leads").select("name, phone").eq("id", lead_id).eq("tenant_id", tenant_id).maybe_single().execute()
    return (res.data if res else None) or {}


def balance_paise(deal: dict) -> int:
    """What is still to collect on an order."""
    return max(int(deal.get("total_paise") or 0) - int(deal.get("paid_paise") or 0), 0)


async def send_payment_link(tenant_id: str, deal_id: str, *, send_whatsapp_message: bool = True,
                            amount_paise: int | None = None, db=None) -> dict:
    """Create the Razorpay link (notes.deal_id routes the webhook back here),
    move the deal to awaiting_payment, and optionally message the customer.
    The link charges what is still due (an advance link passes amount_paise).
    A freeform WhatsApp send fails outside the 24h window -- that is reported
    as message_sent=False with the link, so staff can share it themselves."""
    db = db or get_supabase()
    deal = (
        db.table("deals").select("*").eq("id", deal_id).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    if not deal or not deal.data:
        raise DealError("Deal not found")
    deal = deal.data
    if deal["stage"] in ("won", "lost"):
        raise DealError(f"Deal is already {deal['stage']}")
    items = (
        db.table("deal_items").select("name, qty, line_total_paise").eq("deal_id", deal_id).eq("tenant_id", tenant_id).execute()
    ).data or []
    contact = _lead_contact(tenant_id, deal["lead_id"], db) if deal.get("lead_id") else {}
    phone = contact.get("phone") or ""
    customer_name = contact.get("name") or deal.get("customer_name") or phone
    due = balance_paise(deal)
    amount = due if amount_paise is None else int(amount_paise)
    if amount <= 0 or amount > due:
        raise DealError("Nothing is left to pay on this order" if due <= 0 else "The amount is more than what is left to pay")

    # A live link is reused only while it is for the whole order and nothing is paid yet.
    live = _link_is_live(deal) and amount == due and not deal.get("paid_paise")
    if live:
        link, patch = {"payment_link_url": deal["payment_link"]}, {}
    else:
        from app.services.payment_razorpay import create_payment_link
        # Razorpay replays the original link for a repeated key, so the key carries the last
        # link's id (unique per link made) and the amount: a regenerate is never deduped to
        # the dead link.
        previous_plink = deal.get("razorpay_payment_link_id") or ""
        link = await create_payment_link(
            idempotency_key=f"deal:{deal_id}:{amount}:{deal.get('paid_paise') or 0}:{previous_plink}:payment_link",
            notes={"deal_id": deal_id},
            amount_paise=amount,
            customer_name=customer_name,
            customer_phone=phone,
            description=f"{format_deal_number(deal['deal_number'])} — " + ", ".join(i["name"] for i in items)[:200],
            tenant_id=tenant_id,
        )
        patch = {
            "stage": "awaiting_payment",
            "payment_link": link["payment_link_url"],
            "razorpay_payment_link_id": link.get("razorpay_payment_link_id"),
            # What Razorpay reports, not a guess: it is the time the customer sees.
            "link_expires_at": link.get("payment_link_expires_at"),
            # Payment reminders (day 1, 3, 7) count from the newest link.
            "reminders_from": _now_iso(),
            "reminders_sent": 0,
        }
        db.table("deals").update(patch).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
        await _cancel_replaced_link(deal, link.get("razorpay_payment_link_id"))

    message_sent = False
    if send_whatsapp_message and phone:
        from app.services.blocked_guard import is_blocked
        if await is_blocked(tenant_id, phone):
            # Full block: the link is made (staff can see it) but nothing is sent to a blocked person.
            logger.info(f"Deal {deal_id}: payment link not sent, the person is blocked")
            return {"payment_link": link["payment_link_url"], "message_sent": False, "deal_patch": patch}
        text = quote_summary_block(items, deal["total_paise"])
        if amount != deal["total_paise"]:
            text += f"\nTo pay now: {_rupees(amount)}"
        text += f"\n\nPay here: {link['payment_link_url']}"
        try:
            from app.services.ai_reply import send_whatsapp
            await send_whatsapp(phone, text, tenant_id=tenant_id)
            message_sent = True
        except Exception as e:
            logger.info(f"Deal {deal_id}: payment link WhatsApp send failed (likely outside 24h window): {e}")
    return {"payment_link": link["payment_link_url"], "message_sent": message_sent, "deal_patch": patch}


def expire_deal_link(tenant_id: str, deal_id: str, db=None) -> bool:
    """The deal's CURRENT payment link expired (blueprint D2): only the link dies. It is
    cleared (the razorpay id stays for audit and the next link's idempotency key) and the
    deal stays in awaiting_payment; the board shows a "link expired" tag and the customer
    gets a fresh link if they come back. False when the deal is not awaiting payment."""
    db = db or get_supabase()
    result = (
        db.table("deals")
        .update({"payment_link": None, "link_expires_at": None})
        .eq("id", deal_id)
        .eq("tenant_id", tenant_id)
        .eq("stage", "awaiting_payment")
        .execute()
    )
    return bool(result.data)


# ---------------------------------------------------------------- won / lost

def mark_won(
    tenant_id: str,
    deal_id: str,
    *,
    payment_method: str,
    razorpay_payment_id: str | None = None,
    created_by: str | None = None,
    db=None,
) -> dict | None:
    """The .neq("stage", "won") claim is the whole point: of two concurrent
    Razorpay retries, exactly one gets the row back and deducts stock; the
    other is a no-op. Returns None if unknown or already won."""
    db = db or get_supabase()
    if payment_method not in PAYMENT_METHODS:
        raise DealError(f"Unknown payment method {payment_method}")
    patch = {"stage": "won", "won_at": _now_iso(), "payment_method": payment_method, "lost_at": None, "lost_reason": None}
    if razorpay_payment_id:
        patch["razorpay_payment_id"] = razorpay_payment_id
    claimed = (
        db.table("deals").update(patch).eq("id", deal_id).eq("tenant_id", tenant_id).neq("stage", "won").execute()
    )
    if not claimed.data:
        return None
    deal = claimed.data[0]
    due = balance_paise(deal)
    if due > 0:
        # The sale stands even if this row fails (the money is real); it is logged loudly instead.
        try:
            _insert_payment(db, tenant_id, deal_id, due, payment_method,
                            kind="balance" if deal.get("paid_paise") else "full",
                            razorpay_payment_id=razorpay_payment_id, received_by=created_by)
        except Exception as e:
            logger.error(f"Deal {deal_id} won but its payment row failed: {e}")
        deal = {**deal, "paid_paise": int(deal.get("total_paise") or 0)}
    warnings = _deduct_for_deal(tenant_id, deal_id, created_by, db, direction=-1)
    # v9.2 P1: a paid order of a property takes its units off "units left" (once per order; never raises).
    from app.services import properties
    properties.on_deal_paid(db, tenant_id, deal_id)
    return {"deal": deal, "stock_warnings": warnings}


def _insert_payment(db, tenant_id: str, deal_id: str, amount_paise: int, method: str, *, kind: str = "payment",
                    razorpay_payment_id: str | None = None, received_by: str | None = None,
                    received_by_caller: str | None = None, note: str | None = None) -> bool:
    """One deal_payments row; deals.paid_paise follows by trigger. False when this Razorpay
    payment is already recorded (the unique index makes a retried webhook a no-op)."""
    row = {
        "tenant_id": tenant_id, "deal_id": deal_id, "amount_paise": int(amount_paise), "method": method,
        "kind": kind, "razorpay_payment_id": razorpay_payment_id or None, "received_by": received_by,
        "received_by_caller": received_by_caller, "note": note,
    }
    if razorpay_payment_id and _payment_seen(db, tenant_id, razorpay_payment_id):
        return False
    try:
        db.table("deal_payments").insert(row).execute()
    except Exception as e:
        if razorpay_payment_id and "duplicate" in str(e).lower():
            return False
        raise
    # The first payment gives the order its invoice number (online and shop share it).
    from app.services.orders import ensure_invoice
    ensure_invoice(db, tenant_id, deal_id)
    return True


def _payment_seen(db, tenant_id: str, razorpay_payment_id: str) -> bool:
    return bool((
        db.table("deal_payments").select("id").eq("tenant_id", tenant_id)
        .eq("razorpay_payment_id", razorpay_payment_id).limit(1).execute()
    ).data)


def record_payment(
    tenant_id: str,
    deal_id: str,
    amount_paise: int,
    method: str,
    *,
    razorpay_payment_id: str | None = None,
    received_by: str | None = None,
    received_by_caller: str | None = None,
    note: str | None = None,
    db=None,
) -> dict:
    """Money in on an order: an advance, a balance or all of it. When that pays it in full the
    order becomes won (stock moves, Came / Paid). status:
      "recorded"  -- saved; "won" says whether it finished the order
      "duplicate" -- this Razorpay payment was already recorded (a retried webhook)
      "over"      -- more than what is left (e.g. a link paid after staff took cash)
      "closed"    -- the order is lost (cancelled)"""
    db = db or get_supabase()
    if method not in PAYMENT_METHODS:
        raise DealError(f"Unknown payment method {method}")
    amount = int(amount_paise)
    if amount <= 0:
        raise DealError("The amount must be more than zero")
    res = db.table("deals").select("*").eq("id", deal_id).eq("tenant_id", tenant_id).maybe_single().execute()
    if not res or not res.data:
        raise DealError("Deal not found")
    deal = res.data
    none = {"won": False, "deal": deal, "stock_warnings": []}
    if razorpay_payment_id and _payment_seen(db, tenant_id, razorpay_payment_id):
        return {"status": "duplicate", **none}
    if deal["stage"] == "lost":
        return {"status": "closed", **none}
    due = balance_paise(deal)
    if deal["stage"] == "won" or amount > due:
        return {"status": "over", **none}
    if amount == due:
        won = mark_won(tenant_id, deal_id, payment_method=method, razorpay_payment_id=razorpay_payment_id,
                       created_by=received_by, db=db)
        if won is None:  # another payment finished it a moment ago
            return {"status": "over", **none}
        if received_by_caller or note:
            _tag_last_payment(db, tenant_id, deal_id, received_by_caller, note)
        return {"status": "recorded", "won": True, "deal": won["deal"], "stock_warnings": won["stock_warnings"]}
    kind = "advance" if not deal.get("paid_paise") else "payment"
    if not _insert_payment(db, tenant_id, deal_id, amount, method, kind=kind, razorpay_payment_id=razorpay_payment_id,
                           received_by=received_by, received_by_caller=received_by_caller, note=note):
        return {"status": "duplicate", **none}
    # The open link was for the old balance: it must not be paid on top of this.
    patch: dict = {"payment_link": None, "link_expires_at": None}
    if deal["stage"] == "quoted":
        patch["stage"] = "awaiting_payment"
    db.table("deals").update(patch).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
    deal = {**deal, **patch, "paid_paise": int(deal.get("paid_paise") or 0) + amount}
    return {"status": "recorded", "won": False, "deal": deal, "stock_warnings": [],
            "stale_link": res.data if res.data.get("payment_link") else None}


def _tag_last_payment(db, tenant_id: str, deal_id: str, caller_id: str | None, note: str | None) -> None:
    rows = (
        db.table("deal_payments").select("id").eq("tenant_id", tenant_id).eq("deal_id", deal_id)
        .order("created_at", desc=True).limit(1).execute()
    ).data or []
    if rows:
        db.table("deal_payments").update({"received_by_caller": caller_id, "note": note}).eq("id", rows[0]["id"]).eq("tenant_id", tenant_id).execute()


async def cancel_stale_link(deal: dict | None) -> None:
    """After a part payment the open link is for the old balance; cancel it (best effort)."""
    if deal and deal.get("razorpay_payment_link_id"):
        await _cancel_replaced_link(deal, None)


def mark_lost(
    tenant_id: str,
    deal_id: str,
    reason: str,
    *,
    created_by: str | None = None,
    only_from: tuple[str, ...] | None = None,
    db=None,
) -> dict | None:
    """A won deal marked lost is a refund/cancelled sale: its stock comes back.

    only_from limits which stages may move to lost (checked again in the claiming UPDATE, so a
    deal that becomes won between the read and the write is not lost either). Automatic callers
    such as the Razorpay webhook pass the open stages: a won deal is never lost by an event."""
    db = db or get_supabase()
    current = db.table("deals").select("stage").eq("id", deal_id).eq("tenant_id", tenant_id).maybe_single().execute()
    if not current or not current.data or current.data["stage"] == "lost":
        return None
    if only_from is not None and current.data["stage"] not in only_from:
        return None
    was_won = current.data["stage"] == "won"
    query = (
        db.table("deals")
        .update({"stage": "lost", "lost_at": _now_iso(), "lost_reason": (reason or "").strip() or None})
        .eq("id", deal_id)
        .eq("tenant_id", tenant_id)
        .neq("stage", "lost")
    )
    if only_from is not None:
        query = query.in_("stage", list(only_from))
    claimed = query.execute()
    if not claimed.data:
        return None
    warnings = _deduct_for_deal(tenant_id, deal_id, created_by, db, direction=1) if was_won else []
    return {"deal": claimed.data[0], "stock_warnings": warnings}


# ---------------------------------------------------------------- automatic writers

def upsert_quoted_deal(tenant_id: str, lead_id: str, line: dict, db=None) -> None:
    """The AI told this lead a real catalog price: keep ONE open quoted deal
    per lead (latest item wins) so the board shows the interest without a
    new card per message. Never raises -- it must not break the reply."""
    try:
        db = db or get_supabase()
        resolved = _resolve_lines(tenant_id, [line], db)
        total = _deal_total(tenant_id, resolved, db)
        open_quote = (
            db.table("deals")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("lead_id", lead_id)
            .eq("stage", "quoted")
            .eq("source", "whatsapp")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        if open_quote:
            deal_id = open_quote[0]["id"]
            db.table("deal_items").delete().eq("deal_id", deal_id).eq("tenant_id", tenant_id).execute()
            _insert_items(tenant_id, deal_id, resolved, db)
            db.table("deals").update({"total_paise": total}).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
            return
        deal = db.table("deals").insert({
            "tenant_id": tenant_id, "lead_id": lead_id, "deal_number": _next_deal_number(db, tenant_id),
            "stage": "quoted", "source": "whatsapp", "total_paise": total,
            **({"bill_type": "simple"} if not _charges_gst(tenant_id, db) else {}),
        }).execute().data[0]
        _insert_items(tenant_id, deal["id"], resolved, db)
    except Exception as e:
        logger.warning(f"upsert_quoted_deal failed for lead {lead_id}: {e}")


def _intake_gst(session: dict) -> tuple[float | None, int]:
    """(gst_percent, gst_amount_paise) for a session; (None, 0) when it has no GST.
    Columns are read with .get so sessions created before GST existed behave as before."""
    gst_paise = int(session.get("gst_amount_paise") or 0)
    if gst_paise <= 0:
        return None, 0
    percent = session.get("gst_percent")
    return (float(percent) if percent is not None else None), gst_paise


def _intake_subtotal(session: dict) -> int:
    """Pre-GST amount: total_amount_paise stays the subtotal; when it is missing,
    amount_paise is GST-inclusive, so take the GST back out."""
    _, gst_paise = _intake_gst(session)
    if session.get("total_amount_paise"):
        return int(session["total_amount_paise"])
    return max(int(session.get("amount_paise") or 0) - gst_paise, 0)


def _intake_lines(session: dict) -> list[dict]:
    gst_rate, _ = _intake_gst(session)
    rate = {"gst_rate": gst_rate} if gst_rate is not None else {}
    lines = []
    package_amount = session.get("package_amount_paise")
    if session.get("package_name") and package_amount is not None:
        lines.append({"name": session["package_name"], "qty": 1, "unit_price_paise": package_amount, **rate})
    for addon in session.get("selected_addons") or []:
        if addon.get("name") and addon.get("amount_paise") is not None:
            lines.append({"name": addon["name"], "qty": 1, "unit_price_paise": addon["amount_paise"], **rate})
    if not lines:
        amount = _intake_subtotal(session)
        if amount:
            lines.append({"name": session.get("package_name") or "Consultation", "qty": 1, "unit_price_paise": amount, **rate})
    return lines


def _intake_deal_total(session: dict, lines: list[dict]) -> int:
    """What the customer pays: the pre-GST subtotal plus the GST charged on the link."""
    _, gst_paise = _intake_gst(session)
    subtotal = _intake_subtotal(session) or sum(li["line_total_paise"] for li in lines)
    return subtotal + gst_paise


def sync_intake_session(session: dict, db=None, lost_reason: str | None = None) -> None:
    """Mirror the intake (form) flow onto its deal, keyed by intake_session_id.
    The intake state machine stays the source of truth for the conversation;
    this only keeps the Deals board and sales export complete. Never raises."""
    try:
        db = db or get_supabase()
        status = session.get("status")
        if status not in ("awaiting_payment", "paid", "cancelled"):
            return
        tenant_id = session["tenant_id"]
        existing = (
            db.table("deals").select("id, stage").eq("intake_session_id", session["id"]).eq("tenant_id", tenant_id).limit(1).execute()
        ).data or []

        if status == "awaiting_payment":
            lines = _resolve_lines(tenant_id, _intake_lines(session), db) if _intake_lines(session) else []
            if not lines:
                return
            total = _intake_deal_total(session, lines)
            fields = {
                "stage": "awaiting_payment", "total_paise": total, "payment_link": session.get("payment_link"),
                "razorpay_payment_link_id": session.get("razorpay_payment_link_id"),
                "link_expires_at": session.get("payment_link_expires_at"),
            }
            if existing:
                deal_id = existing[0]["id"]
                if existing[0]["stage"] == "won":
                    return
                db.table("deals").update({**fields, "lost_at": None, "lost_reason": None}).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
                db.table("deal_items").delete().eq("deal_id", deal_id).eq("tenant_id", tenant_id).execute()
            else:
                deal_id = db.table("deals").insert({
                    **fields, "tenant_id": tenant_id, "lead_id": session["lead_id"],
                    "deal_number": _next_deal_number(db, tenant_id),
                    "source": "form", "intake_session_id": session["id"],
                }).execute().data[0]["id"]
            _insert_items(tenant_id, deal_id, lines, db)
            return

        if not existing:
            return
        deal_id = existing[0]["id"]
        if status == "paid":
            mark_won(tenant_id, deal_id, payment_method="razorpay",
                     razorpay_payment_id=session.get("razorpay_payment_id"), db=db)
        elif status == "cancelled" and existing[0]["stage"] != "won":
            mark_lost(tenant_id, deal_id, lost_reason or "Link expired or cancelled", db=db)
    except Exception as e:
        logger.warning(f"sync_intake_session failed for session {session.get('id')}: {e}")
