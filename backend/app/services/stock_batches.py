"""Batches & expiry (plan: docs/plans/commerce-stock-plan.md, "Part 5 in detail"; migration 310).

A batch item's stock at a place is always the sum of its active batches (the SQL stock functions keep
it so). Selling takes the batch marked Sell first, then the earliest expiry, never an expired one;
a bill line can name its batch. A batch's discount % lowers the price while it is the one being sold.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SOON_DAYS = 30
LATER_DAYS = 90
MAX_DISCOUNT = 90
NO_BATCH = "No batch no."
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class BatchError(ValueError):
    """A plain-words problem the dashboard shows as is (routes turn it into a 400)."""


def today() -> date:
    return datetime.now(IST).date()


def _date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def bucket(expiry, now: date | None = None) -> str:
    """expired | soon (≤30 days) | later (31–90) | fine (later, or no expiry)."""
    exp = _date(expiry)
    now = now or today()
    if exp is None:
        return "fine"
    if exp < now:
        return "expired"
    if exp <= now + timedelta(days=SOON_DAYS):
        return "soon"
    if exp <= now + timedelta(days=LATER_DAYS):
        return "later"
    return "fine"


def label(batch: dict) -> str:
    """'Batch PC2307 · Exp 30 Nov 2026' (or 'No batch no.'), for bills and lists."""
    no = (batch.get("batch_no") or "").strip()
    parts = [f"Batch {no}" if no else NO_BATCH]
    exp = _date(batch.get("expiry_date"))
    if exp:
        parts.append(f"Exp {exp.day} {exp.strftime('%b %Y')}")
    return " · ".join(parts)


def sellable(batch: dict, now: date | None = None) -> bool:
    return batch.get("status", "active") == "active" and int(batch.get("quantity") or 0) > 0 \
        and bucket(batch.get("expiry_date"), now) != "expired"


def pick_order(batch: dict) -> tuple:
    """The order selling takes batches in (place order aside): Sell first, then earliest expiry."""
    exp = _date(batch.get("expiry_date"))
    return (not batch.get("sell_first"), exp or date.max, str(batch.get("created_at") or ""))


# ── switching on / off ───────────────────────────────────────────────────────


def set_tracking(db, tenant_id: str, item_id: str, on: bool) -> None:
    if not _UUID.fullmatch(str(item_id)):
        raise BatchError("Item not found.")
    if not db.rpc("set_batch_tracking", {"p_tenant_id": tenant_id, "p_item": item_id, "p_on": bool(on)}).execute().data:
        raise BatchError("Item not found.")


# ── reading ──────────────────────────────────────────────────────────────────


def item_batches(db, tenant_id: str, item_id: str, variant_id: str | None = None) -> list[dict]:
    """Active batches of one item (or one size/colour) with stock, in the order selling takes them."""
    q = (db.table("stock_batches").select("id, variant_id, place_id, batch_no, expiry_date, quantity, discount_pct, "
                                          "sell_first, status, created_at")
         .eq("tenant_id", tenant_id).eq("catalog_item_id", item_id).eq("status", "active").gt("quantity", 0))
    if variant_id:
        q = q.eq("variant_id", variant_id)
    rows = q.limit(500).execute().data or []
    now = today()
    return sorted(({**r, "label": label(r), "bucket": bucket(r.get("expiry_date"), now)} for r in rows), key=pick_order)


def _by_place(db, tenant_id: str, batches: list[dict]) -> list[dict]:
    """The order a bill takes batches in, as the SQL does: the bill place first, then the other places
    (their order), and inside a place Sell first, then earliest expiry."""
    if len({b["place_id"] for b in batches}) < 2:
        return batches
    places = (db.table("stock_places").select("id, bills_from, sort_order").eq("tenant_id", tenant_id)
              .eq("archived", False).execute().data or [])
    rank = {p["id"]: (not p.get("bills_from"), int(p.get("sort_order") or 0)) for p in places}
    return sorted(batches, key=lambda b: (rank.get(b["place_id"], (True, 999)), pick_order(b)))


def sale_price(db, tenant_id: str, item_id: str, variant_id: str | None, base_paise: int,
               batch_id: str | None = None) -> tuple[int, dict | None]:
    """The price for one more sale: the base price, less the discount of the batch that would be sold
    (the chosen one, else the one a bill takes first). (price, batch or None)."""
    batches = [b for b in item_batches(db, tenant_id, item_id, variant_id) if sellable(b)]
    if variant_id is None:
        batches = [b for b in batches if not b.get("variant_id")]
    batches = _by_place(db, tenant_id, batches)
    chosen = next((b for b in batches if b["id"] == batch_id), None) if batch_id else (batches[0] if batches else None)
    if not chosen or not chosen.get("discount_pct"):
        return base_paise, chosen
    return round(base_paise * (100 - int(chosen["discount_pct"])) / 100), chosen


def bill_line_batches(db, tenant_id: str, deal_item_ids: list[str]) -> dict[str, str]:
    """{deal item id: 'Batch PC2307 · Exp 30 Nov 2026, Batch …'} for what each bill line took."""
    if not deal_item_ids:
        return {}
    picks = (db.table("deal_item_batches").select("deal_item_id, batch_id, quantity").eq("tenant_id", tenant_id)
             .in_("deal_item_id", deal_item_ids).limit(2000).execute().data or [])
    net: dict[tuple[str, str], int] = {}
    for p in picks:
        key = (p["deal_item_id"], p["batch_id"])
        net[key] = net.get(key, 0) + int(p["quantity"])
    batch_ids = list({b for (_, b), q in net.items() if q > 0})
    if not batch_ids:
        return {}
    batches = {b["id"]: b for b in (db.table("stock_batches").select("id, batch_no, expiry_date").eq("tenant_id", tenant_id)
                                    .in_("id", batch_ids).execute().data or [])}
    out: dict[str, list[str]] = {}
    for (item_id, batch_id), qty in net.items():
        if qty > 0 and batch_id in batches:
            out.setdefault(item_id, []).append(label(batches[batch_id]))
    return {k: ", ".join(dict.fromkeys(v)) for k, v in out.items()}


def overview(db, tenant_id: str) -> dict:
    """The Batches & expiry tab: every active batch with stock, its bucket, value at cost, supplier."""
    rows = (db.table("stock_batches").select("id, catalog_item_id, variant_id, place_id, batch_no, expiry_date, quantity, "
                                             "cost_paise, supplier_id, discount_pct, sell_first, created_at")
            .eq("tenant_id", tenant_id).eq("status", "active").gt("quantity", 0).limit(20000).execute().data or [])
    items = {i["id"]: i for i in (db.table("catalog_items").select("id, name, price_paise").eq("tenant_id", tenant_id)
                                  .eq("tracks_batches", True).limit(5000).execute().data or [])}
    variant_ids = list({r["variant_id"] for r in rows if r.get("variant_id")})
    variants = {v["id"]: v for v in (db.table("catalog_item_variants").select("id, size, colour, price_paise")
                                     .eq("tenant_id", tenant_id).in_("id", variant_ids).execute().data or [])} if variant_ids else {}
    sups = {s["id"]: s["name"] for s in (db.table("suppliers").select("id, name").eq("tenant_id", tenant_id)
                                         .limit(1000).execute().data or [])}
    places = {p["id"]: p["name"] for p in (db.table("stock_places").select("id, name").eq("tenant_id", tenant_id)
                                           .execute().data or [])}
    now = today()
    out = []
    for r in rows:
        item = items.get(r["catalog_item_id"])
        if not item:  # batches switched off for this item
            continue
        v = variants.get(r.get("variant_id") or "")
        vlabel = " · ".join(x for x in ((v or {}).get("colour"), (v or {}).get("size")) if x)
        b = bucket(r.get("expiry_date"), now)
        cost = r.get("cost_paise")
        price = (v or {}).get("price_paise") or item.get("price_paise")
        out.append({
            **r, "name": item["name"], "variant_label": vlabel, "bucket": b,
            "value_paise": int(r["quantity"]) * int(cost if cost is not None else (price or 0)),
            "value_at": "cost" if cost is not None else "price",
            "supplier": sups.get(r.get("supplier_id") or ""), "place": places.get(r["place_id"]),
            "returnable": bool(r.get("supplier_id")) and b in ("soon", "later"),
        })
    order = {"expired": 0, "soon": 1, "later": 2, "fine": 3}
    out.sort(key=lambda r: (order[r["bucket"]], r.get("expiry_date") or "9999", r["name"].lower()))
    cards = {k: {"batches": 0, "value_paise": 0} for k in ("expired", "soon", "later", "fine", "returnable")}
    for r in out:
        for key in (r["bucket"], "returnable") if r["returnable"] else (r["bucket"],):
            cards[key]["batches"] += 1
            cards[key]["value_paise"] += r["value_paise"]
    return {"batches": out, "cards": cards, "tracked_items": len(items), "today": now.isoformat(),
            "suppliers": sorted({r["supplier"] for r in out if r.get("supplier")})}


def expiring_summary(db, tenant_id: str) -> dict:
    """For the bell and Day closing: expired and ≤30-day batches (count, pieces, top names)."""
    rows = (db.table("stock_batches").select("catalog_item_id, batch_no, expiry_date, quantity")
            .eq("tenant_id", tenant_id).eq("status", "active").gt("quantity", 0).not_.is_("expiry_date", "null")
            .lte("expiry_date", (today() + timedelta(days=SOON_DAYS)).isoformat()).limit(5000).execute().data or [])
    if not rows:
        return {"expired": 0, "soon": 0, "names": []}
    names = {i["id"]: i["name"] for i in (db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id)
                                          .in_("id", list({r["catalog_item_id"] for r in rows})).execute().data or [])}
    now = today()
    expired = [r for r in rows if bucket(r["expiry_date"], now) == "expired"]
    soon = [r for r in rows if bucket(r["expiry_date"], now) == "soon"]
    ordered = sorted(rows, key=lambda r: r["expiry_date"])
    return {"expired": len(expired), "soon": len(soon),
            "names": list(dict.fromkeys(names.get(r["catalog_item_id"], "") for r in ordered if names.get(r["catalog_item_id"])))[:5]}


# ── actions ──────────────────────────────────────────────────────────────────


def _batch(db, tenant_id: str, batch_id: str) -> dict:
    if not _UUID.fullmatch(str(batch_id)):
        raise BatchError("That batch isn't there any more.")
    rows = (db.table("stock_batches").select("*").eq("id", batch_id).eq("tenant_id", tenant_id).eq("status", "active")
            .limit(1).execute().data or [])
    if not rows:
        raise BatchError("That batch isn't there any more.")
    return rows[0]


def set_discount(db, tenant_id: str, batch_id: str, pct) -> dict:
    try:
        pct = int(pct)
    except (TypeError, ValueError):
        raise BatchError("The discount must be a whole number.")
    if not 0 <= pct <= MAX_DISCOUNT:
        raise BatchError(f"The discount can be 0 to {MAX_DISCOUNT}%.")
    b = _batch(db, tenant_id, batch_id)
    if pct and bucket(b.get("expiry_date")) == "expired":
        raise BatchError("This batch has expired: it can't be sold, so remove it instead.")
    db.table("stock_batches").update({"discount_pct": pct}).eq("id", batch_id).eq("tenant_id", tenant_id).execute()
    return {**b, "discount_pct": pct}


def set_sell_first(db, tenant_id: str, batch_id: str, on: bool) -> dict:
    b = _batch(db, tenant_id, batch_id)
    if on and bucket(b.get("expiry_date")) == "expired":
        raise BatchError("This batch has expired: it can't be sold, so remove it instead.")
    db.table("stock_batches").update({"sell_first": bool(on)}).eq("id", batch_id).eq("tenant_id", tenant_id).execute()
    return {**b, "sell_first": bool(on)}


def _qty(b: dict, qty) -> int:
    if qty is None:
        return int(b["quantity"])
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise BatchError("The quantity must be a whole number.")
    if not 1 <= qty <= int(b["quantity"]):
        raise BatchError(f"This batch has {b['quantity']}.")
    return qty


def write_off(db, tenant_id: str, batch_id: str, qty=None, *, user_id: str | None = None, note: str | None = None) -> int:
    """Remove (expired or damaged) pieces: stock out with reason write_off; the batch closes at 0."""
    from app.services.deals import adjust_stock, adjust_variant_stock

    b = _batch(db, tenant_id, batch_id)
    qty = _qty(b, qty)
    text = (note or "").strip()[:200] or f"Removed: {label(b)}"
    if b.get("variant_id"):
        res = adjust_variant_stock(tenant_id, b["variant_id"], -qty, "write_off", note=text, created_by=user_id,
                                   batch_id=batch_id, db=db)
    else:
        res = adjust_stock(tenant_id, b["catalog_item_id"], -qty, "write_off", note=text, created_by=user_id,
                           batch_id=batch_id, db=db)
    if not res["ok"]:
        raise BatchError("Couldn't remove it: the stock changed. Refresh and try again.")
    if qty == int(b["quantity"]):
        db.table("stock_batches").update({"status": "written_off"}).eq("id", batch_id).eq("tenant_id", tenant_id) \
            .eq("quantity", 0).execute()
    return qty


def return_to_supplier(db, tenant_id: str, batch_id: str, qty=None, *, user_id: str | None = None,
                       note: str | None = None) -> dict:
    b = _batch(db, tenant_id, batch_id)
    if not b.get("supplier_id"):
        raise BatchError("This batch has no supplier. Add stock through Purchases → Stock in to know who it came from.")
    qty = _qty(b, qty)
    try:
        amount = db.rpc("return_batch_to_supplier", {
            "p_tenant_id": tenant_id, "p_batch": batch_id, "p_qty": qty, "p_user": user_id,
            "p_note": (note or "").strip()[:300] or f"Returned to supplier: {label(b)}",
        }).execute().data
    except Exception as e:
        if "batch_return" in str(e):
            raise BatchError("Couldn't return it: the stock changed. Refresh and try again.")
        raise
    return {"quantity": qty, "credit_paise": int(amount or 0)}


# ── the daily bell ───────────────────────────────────────────────────────────


def ring_expiry_bells(db=None) -> int:
    """One bell a day per owner of each business with expired or ≤30-day batches. Returns how many sent."""
    from app.db.supabase import get_supabase
    from app.services.notify import notify_user

    db = db or get_supabase()
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    soon = (today() + timedelta(days=SOON_DAYS)).isoformat()
    tenants = {r["tenant_id"] for r in (db.table("stock_batches").select("tenant_id").eq("status", "active")
                                        .gt("quantity", 0).not_.is_("expiry_date", "null").lte("expiry_date", soon)
                                        .limit(20000).execute().data or [])}
    sent = 0
    for tenant_id in tenants:
        s = expiring_summary(db, tenant_id)
        if not (s["expired"] or s["soon"]):
            continue
        parts = []
        if s["expired"]:
            parts.append(f"{s['expired']} expired")
        if s["soon"]:
            parts.append(f"{s['soon']} expiring in {SOON_DAYS} days")
        title = f"Batches: {' · '.join(parts)}"
        message = (f"{', '.join(s['names'])}. Remove expired ones, sell first or return the rest to the supplier "
                   "in Catalogue → Batches & expiry.")
        owners = (db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner")
                  .execute().data or [])
        for o in owners:
            already = (db.table("app_notifications").select("id").eq("tenant_id", tenant_id)
                       .eq("user_id", o["user_id"]).eq("type", "batch_expiry").gte("created_at", start)
                       .limit(1).execute().data)
            if already:
                continue
            notify_user(tenant_id, o["user_id"], "batch_expiry", title, message, db=db,
                        push_url="/dashboard/catalog?tab=batches")
            sent += 1
    return sent


def ai_offers(db, tenant_id: str, item_ids: list[str]) -> dict[str, int]:
    """{item id: discount %} where the batch the next sale takes (items without sizes) has a discount.
    Read only: the AI reply path never writes."""
    if not item_ids:
        return {}
    rows = (db.table("stock_batches").select("catalog_item_id, variant_id, expiry_date, quantity, discount_pct, "
                                             "sell_first, status, created_at")
            .eq("tenant_id", tenant_id).in_("catalog_item_id", item_ids).eq("status", "active").gt("quantity", 0)
            .is_("variant_id", "null").limit(5000).execute().data or [])
    now = today()
    first: dict[str, dict] = {}
    for r in sorted((r for r in rows if sellable(r, now)), key=pick_order):
        first.setdefault(r["catalog_item_id"], r)
    return {k: int(v["discount_pct"]) for k, v in first.items() if v.get("discount_pct")}
