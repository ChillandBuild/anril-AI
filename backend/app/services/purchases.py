"""Purchases & suppliers (Commerce mockup; migration 307).

Suppliers, purchase orders (PO-0001...) sent on WhatsApp with Confirm / Change date buttons,
stock-ins (with or without a PO) that move good pieces into stock at a place and set the cost
price, damaged pieces kept aside, and supplier payments. What a business owes a supplier =
its stock-in bills - its payments."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

PO_CONFIRM = "po_confirm:"
PO_DATE = "po_date:"
TEMPLATE = {
    "name": "anril_purchase_order",
    "body": ("Vanakkam {{1}}, purchase order {{2}} from {{3}}: {{4}}. Need by {{5}}. "
             "Please tap Confirm, or Change date if that day doesn't work."),
    "examples": ["Murugan", "PO-0043", "Demo Silks", "Kanchi pattu Red XL x 4, Soft silk Green x 10", "20 Nov"],
    "buttons": ["Confirm", "Change date"],
}
DAMAGED_ACTIONS = ("replace", "less_on_bill", "discount")
PAY_METHODS = ("cash", "upi", "bank", "cheque")
REMIND_AFTER = timedelta(days=2)
SOLD_DAYS = 30


class PurchaseError(ValueError):
    """Something staff can fix; routes turn it into a 400."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def po_number(n: int) -> str:
    return f"PO-{int(n):04d}"


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def _rupees(paise: int) -> str:
    from app.services.deals import _rupees as r

    return r(int(paise or 0))


def _gst(paise: int, rate) -> int:
    return int(round(int(paise) * float(rate or 0) / 100))


def _date(value, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise PurchaseError(f"{field}: pick a date")


# ── suppliers ─────────────────────────────────────────────────────────────────


def _gstin(value) -> str | None:
    text = re.sub(r"\s", "", str(value or "")).upper()
    if not text:
        return None
    if not re.fullmatch(r"\d{2}[A-Z0-9]{13}", text):
        raise PurchaseError("A GSTIN is 15 letters and numbers, like 33ABCDE1234F1Z5")
    return text


def _phone(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    if len(digits) == 10:
        digits = "91" + digits
    if not 11 <= len(digits) <= 15:
        raise PurchaseError("Check the phone number")
    return digits


def save_supplier(db, tenant_id: str, data: dict, supplier_id: str | None = None) -> dict:
    name = _one_line(data.get("name"))[:120]
    if not name:
        raise PurchaseError("Give the supplier a name")
    row = {"name": name, "phone": _phone(data.get("phone")), "city": _one_line(data.get("city"))[:60] or None,
           "gstin": _gstin(data.get("gstin")), "supplies": _one_line(data.get("supplies"))[:200] or None}
    try:
        if supplier_id:
            out = db.table("suppliers").update(row).eq("id", supplier_id).eq("tenant_id", tenant_id).execute().data
            if not out:
                raise PurchaseError("Supplier not found")
            return out[0]
        return (db.table("suppliers").insert({**row, "tenant_id": tenant_id}).execute().data or [{}])[0]
    except PurchaseError:
        raise
    except Exception as exc:
        if "23505" in str(exc) or "duplicate key" in str(exc).lower():
            raise PurchaseError(f"You already have a supplier called {name}")
        raise


def _supplier(db, tenant_id: str, supplier_id: str) -> dict:
    rows = db.table("suppliers").select("*").eq("id", supplier_id).eq("tenant_id", tenant_id).limit(1).execute().data
    if not rows:
        raise PurchaseError("Supplier not found")
    return rows[0]


def suppliers_view(db, tenant_id: str, now: datetime | None = None) -> dict:
    """Suppliers with bought this month, what is owed and when it is due."""
    now = now or _now()
    today = now.astimezone(IST).date()
    month_start = today.replace(day=1).isoformat()
    sups = (db.table("suppliers").select("*").eq("tenant_id", tenant_id).eq("archived", False).order("name")
            .limit(1000).execute().data or [])
    bills = (db.table("stock_ins").select("id, supplier_id, bill_date, total_paise, due_date, pay_status")
             .eq("tenant_id", tenant_id).not_.is_("supplier_id", "null").limit(20000).execute().data or [])
    pays = (db.table("supplier_payments").select("supplier_id, amount_paise").eq("tenant_id", tenant_id)
            .limit(20000).execute().data or [])
    paid: dict[str, int] = {}
    for p in pays:
        paid[p["supplier_id"]] = paid.get(p["supplier_id"], 0) + int(p["amount_paise"])
    rows = []
    for s in sups:
        mine = [b for b in bills if b["supplier_id"] == s["id"]]
        billed = sum(int(b["total_paise"]) for b in mine)
        owe = max(0, billed - paid.get(s["id"], 0))
        month = sum(int(b["total_paise"]) for b in mine if str(b["bill_date"]) >= month_start)
        due = None
        if owe:
            # Oldest unpaid bills first: the first due date not covered by payments.
            left = paid.get(s["id"], 0)
            for b in sorted(mine, key=lambda b: str(b["bill_date"])):
                if left >= int(b["total_paise"]):
                    left -= int(b["total_paise"])
                    continue
                due = b.get("due_date")
                break
        overdue = (today - date.fromisoformat(str(due))).days if due and date.fromisoformat(str(due)) < today else 0
        rows.append({**s, "bought_this_month_paise": month, "owe_paise": owe, "due_date": due, "overdue_days": overdue})
    return {
        "suppliers": rows,
        "bought_this_month_paise": sum(r["bought_this_month_paise"] for r in rows),
        "bought_from": sum(1 for r in rows if r["bought_this_month_paise"]),
        "owe_paise": sum(r["owe_paise"] for r in rows),
        "owe_to": sum(1 for r in rows if r["owe_paise"]),
    }


def record_payment(db, tenant_id: str, supplier_id: str, data: dict, user_id: str | None) -> dict:
    _supplier(db, tenant_id, supplier_id)
    try:
        amount = int(data.get("amount_paise"))
    except (TypeError, ValueError):
        raise PurchaseError("Enter the amount paid")
    if amount <= 0:
        raise PurchaseError("Enter the amount paid")
    method = data.get("method") or "upi"
    if method not in PAY_METHODS:
        raise PurchaseError("Pick cash, UPI, bank or cheque")
    return (db.table("supplier_payments").insert({
        "tenant_id": tenant_id, "supplier_id": supplier_id, "amount_paise": amount, "method": method,
        "paid_on": _date(data.get("paid_on"), "Paid on") or _now().astimezone(IST).date().isoformat(),
        "note": _one_line(data.get("note"))[:200] or None, "created_by": user_id,
        "stock_in_id": _own_stock_in(db, tenant_id, supplier_id, data.get("stock_in_id")),
    }).execute().data or [{}])[0]


def _own_stock_in(db, tenant_id: str, supplier_id: str, stock_in_id) -> str | None:
    if not stock_in_id:
        return None
    rows = (db.table("stock_ins").select("id").eq("id", str(stock_in_id)).eq("tenant_id", tenant_id)
            .eq("supplier_id", supplier_id).limit(1).execute().data or [])
    if not rows:
        raise PurchaseError("That bill isn't this supplier's")
    return rows[0]["id"]


# ── items, places, cost ───────────────────────────────────────────────────────


def _resolve_line(db, tenant_id: str, line: dict) -> tuple[dict, dict | None, str]:
    from app.services.deals import variant_label

    item_id = str(line.get("catalog_item_id") or "")
    items = (db.table("catalog_items").select("id, name, stock_quantity, gst_rate, cost_price_paise")
             .eq("id", item_id).eq("tenant_id", tenant_id).limit(1).execute().data) if item_id else None
    if not items:
        raise PurchaseError("Pick the item for every line")
    variant = None
    if line.get("variant_id"):
        rows = (db.table("catalog_item_variants").select("id, size, colour").eq("id", line["variant_id"])
                .eq("catalog_item_id", item_id).eq("tenant_id", tenant_id).limit(1).execute().data)
        if not rows:
            raise PurchaseError(f"{items[0]['name']}: that size or colour isn't on the item")
        variant = rows[0]
    elif (db.table("catalog_item_variants").select("id").eq("catalog_item_id", item_id).eq("tenant_id", tenant_id)
          .limit(1).execute().data):
        raise PurchaseError(f"{items[0]['name']} has sizes and colours: pick one")
    label = items[0]["name"] + (f" · {variant_label(variant)}" if variant else "")
    return items[0], variant, label


def _place(db, tenant_id: str, place_id: str | None) -> str:
    if place_id:
        rows = (db.table("stock_places").select("id").eq("id", place_id).eq("tenant_id", tenant_id)
                .eq("archived", False).limit(1).execute().data)
        if not rows:
            raise PurchaseError("Pick where the stock goes")
        return place_id
    return db.rpc("default_stock_place", {"p_tenant_id": tenant_id}).execute().data


def _int(value, field: str, low: int = 0, high: int = 1_000_000) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        raise PurchaseError(f"{field} must be a whole number")
    if n < low or n > high:
        raise PurchaseError(f"{field} must be {low} or more")
    return n


def _rate(value) -> float:
    try:
        rate = float(value or 0)
    except (TypeError, ValueError):
        raise PurchaseError("GST must be a number")
    if rate not in (0, 0.25, 3, 5, 12, 18, 28, 40):
        raise PurchaseError("GST is 0, 0.25, 3, 5, 12, 18, 28 or 40%")
    return rate


# ── stock in ──────────────────────────────────────────────────────────────────


def stock_in(db, tenant_id: str, data: dict, user_id: str | None) -> dict:
    """Save what came: good pieces go into stock at the place (and damaged ones kept to sell at a
    discount); the cost price becomes this bill's; a PO's lines count what came; the payment is
    recorded. Returns the stock-in with what happened."""
    from app.services.deals import adjust_stock, adjust_variant_stock

    request_id = str(data.get("request_id") or "") or None
    if request_id:
        if not re.fullmatch(r"[0-9a-f-]{36}", request_id):
            raise PurchaseError("Reload the page and save again")
        done = (db.table("stock_ins").select("*").eq("tenant_id", tenant_id).eq("request_id", request_id)
                .limit(1).execute().data or [])
        if done:  # a double click or a retry: the first one already counted
            return {**done[0], "pieces_in": 0, "damaged_aside": 0, "waiting": [], "repeat": True}
    supplier_id = data.get("supplier_id") or None
    if supplier_id:
        supplier = _supplier(db, tenant_id, supplier_id)
    elif _one_line(data.get("supplier_name")):
        supplier = save_supplier(db, tenant_id, {"name": data.get("supplier_name"), "gstin": data.get("supplier_gstin")})
        supplier_id = supplier["id"]
    else:
        supplier = None
    po, po_lines = None, {}
    if data.get("purchase_order_id"):
        po = _po(db, tenant_id, data["purchase_order_id"])
        if po["status"] in ("cancelled", "received"):
            raise PurchaseError("This purchase order is already closed")
        supplier_id = supplier_id or po["supplier_id"]
        po_lines = {line["id"]: line for line in _po_lines(db, tenant_id, po["id"])}
    place_id = _place(db, tenant_id, data.get("place_id"))
    raw_lines = [li for li in data.get("lines") or [] if isinstance(li, dict)]
    lines = []
    for raw in raw_lines:
        good = _int(raw.get("qty_good"), "Good pieces")
        damaged = _int(raw.get("qty_damaged"), "Damaged pieces")
        if good + damaged == 0:
            continue
        item, variant, label = _resolve_line(db, tenant_id, raw)
        action = raw.get("damaged_action") or None
        if damaged and action not in DAMAGED_ACTIONS:
            raise PurchaseError(f"{label}: pick what to do with the damaged pieces")
        po_line = po_lines.get(raw.get("purchase_order_line_id")) if raw.get("purchase_order_line_id") else None
        if raw.get("purchase_order_line_id") and (
                not po_line or po_line["catalog_item_id"] != item["id"]
                or (po_line.get("variant_id") or None) != (variant["id"] if variant else None)):
            raise PurchaseError(f"{label} isn't on this purchase order")
        cost = _int(raw.get("unit_cost_paise"), "Cost each", 0, 10**10)
        lines.append({"item": item, "variant": variant, "label": label, "good": good, "damaged": damaged,
                      "action": action if damaged else None, "cost": cost, "rate": _rate(raw.get("gst_rate")),
                      "po_line": po_line})
    if not lines:
        raise PurchaseError("Add at least one item that came")
    # What is paid for: good pieces, plus damaged ones kept to sell at a discount.
    billed = [(li, li["good"] + (li["damaged"] if li["action"] == "discount" else 0)) for li in lines]
    items_paise = sum(li["cost"] * qty for li, qty in billed)
    gst_paise = sum(_gst(li["cost"] * qty, li["rate"]) for li, qty in billed)
    total = items_paise + gst_paise
    pay_status = data.get("pay_status") or "later"
    if pay_status not in ("paid", "part", "later"):
        raise PurchaseError("Pick paid in full, part paid or pay later")
    paid_now = total if pay_status == "paid" else (_int(data.get("paid_paise"), "Paid", 0, 10**12) if pay_status == "part" else 0)
    if pay_status == "part" and not 0 < paid_now < total:
        raise PurchaseError("Part paid: enter less than the bill total")
    if paid_now and not supplier_id:
        raise PurchaseError("Pick the supplier you paid")
    row = (db.table("stock_ins").insert({
        "tenant_id": tenant_id, "supplier_id": supplier_id, "purchase_order_id": po["id"] if po else None,
        "bill_no": _one_line(data.get("bill_no"))[:40] or None,
        "bill_date": _date(data.get("bill_date"), "Date") or _now().astimezone(IST).date().isoformat(),
        "supplier_gstin": _gstin(data.get("supplier_gstin")) or (supplier or {}).get("gstin"),
        "place_id": place_id, "received_by": _one_line(data.get("received_by"))[:60] or None,
        "items_paise": items_paise, "gst_paise": gst_paise, "total_paise": total, "pay_status": pay_status,
        "due_date": _date(data.get("due_date"), "Due date") if pay_status != "paid" else None,
        "request_id": request_id, "created_by": user_id,
    }).execute().data or [{}])[0]
    note = f"Stock in {row.get('bill_no') or ''}".strip() + (f" · {po_number(po['number'])}" if po else "")
    pieces = 0
    for li, _ in billed:
        db.table("stock_in_lines").insert({
            "tenant_id": tenant_id, "stock_in_id": row["id"],
            "purchase_order_line_id": li["po_line"]["id"] if li["po_line"] else None,
            "catalog_item_id": li["item"]["id"], "variant_id": li["variant"]["id"] if li["variant"] else None,
            "label": li["label"], "qty_good": li["good"], "qty_damaged": li["damaged"],
            "damaged_action": li["action"], "unit_cost_paise": li["cost"], "gst_rate": li["rate"],
        }).execute()
        into_stock = li["good"] + (li["damaged"] if li["action"] == "discount" else 0)
        if into_stock:
            if li["variant"]:
                adjust_variant_stock(tenant_id, li["variant"]["id"], into_stock, "restock", note=note,
                                     created_by=user_id, place_id=place_id, db=db)
                db.table("catalog_item_variants").update({"cost_price_paise": li["cost"]}) \
                    .eq("id", li["variant"]["id"]).eq("tenant_id", tenant_id).execute()
            else:
                if li["item"].get("stock_quantity") is None:  # starts being tracked
                    db.table("catalog_items").update({"stock_quantity": 0}).eq("id", li["item"]["id"]) \
                        .eq("tenant_id", tenant_id).is_("stock_quantity", "null").execute()
                adjust_stock(tenant_id, li["item"]["id"], into_stock, "restock", note=note, created_by=user_id,
                             place_id=place_id, db=db)
            db.table("catalog_items").update({"cost_price_paise": li["cost"]}).eq("id", li["item"]["id"]) \
                .eq("tenant_id", tenant_id).execute()
            pieces += into_stock
        if li["po_line"] and li["good"]:
            db.rpc("add_po_line_received", {"p_tenant_id": tenant_id, "p_line_id": li["po_line"]["id"],
                                            "p_qty": li["good"]}).execute()
    db.table("stock_ins").update({"applied_at": _now().isoformat()}).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
    if po:
        _refresh_po_status(db, tenant_id, po["id"])
    if paid_now:
        record_payment(db, tenant_id, supplier_id, {"amount_paise": paid_now, "method": data.get("pay_method") or "upi",
                                                    "stock_in_id": row["id"], "paid_on": row["bill_date"]}, user_id)
    waiting = _waiting_for(db, tenant_id, [(li["item"]["id"], li["variant"]["id"] if li["variant"] else None)
                                           for li, qty in billed if qty])
    return {**row, "pieces_in": pieces, "damaged_aside": sum(li["damaged"] for li in lines if li["action"] != "discount"),
            "waiting": waiting}


def _waiting_for(db, tenant_id: str, keys: list[tuple[str, str | None]]) -> list[dict]:
    """People waiting for a back-in-stock message for what just came (Asked but out of stock)."""
    if not keys:
        return []
    rows = (db.table("stock_waitlist").select("catalog_item_id, variant_id").eq("tenant_id", tenant_id)
            .is_("closed_at", "null").eq("wants_message", True)
            .in_("catalog_item_id", list({k[0] for k in keys})).limit(5000).execute().data or [])
    wanted = set(keys)
    counts: dict[tuple, int] = {}
    for r in rows:
        key = (r["catalog_item_id"], r.get("variant_id"))
        if key in wanted:
            counts[key] = counts.get(key, 0) + 1
    return [{"catalog_item_id": k[0], "variant_id": k[1], "people": n} for k, n in counts.items()]


def stock_in_history(db, tenant_id: str, limit: int = 100) -> list[dict]:
    rows = (db.table("stock_ins").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True)
            .limit(limit).execute().data or [])
    sups = {s["id"]: s["name"] for s in (db.table("suppliers").select("id, name").eq("tenant_id", tenant_id)
                                          .limit(2000).execute().data or [])}
    return [{**r, "supplier_name": sups.get(r.get("supplier_id"))} for r in rows]


# ── purchase orders ───────────────────────────────────────────────────────────


def _po(db, tenant_id: str, po_id: str) -> dict:
    rows = db.table("purchase_orders").select("*").eq("id", po_id).eq("tenant_id", tenant_id).limit(1).execute().data
    if not rows:
        raise PurchaseError("Purchase order not found")
    return rows[0]


def _po_lines(db, tenant_id: str, po_id: str) -> list[dict]:
    return (db.table("purchase_order_lines").select("*").eq("purchase_order_id", po_id).eq("tenant_id", tenant_id)
            .execute().data or [])


def _refresh_po_status(db, tenant_id: str, po_id: str) -> None:
    lines = _po_lines(db, tenant_id, po_id)
    got = sum(min(int(li["qty_received"]), int(li["qty_ordered"])) for li in lines)
    want = sum(int(li["qty_ordered"]) for li in lines)
    status = "received" if got >= want else ("part_received" if got else None)
    if status:
        db.table("purchase_orders").update({"status": status}).eq("id", po_id).eq("tenant_id", tenant_id).execute()


def save_po(db, tenant_id: str, data: dict, user_id: str | None, po_id: str | None = None) -> dict:
    supplier = _supplier(db, tenant_id, str(data.get("supplier_id") or ""))
    lines = []
    for raw in data.get("lines") or []:
        if not isinstance(raw, dict):
            continue
        qty = _int(raw.get("qty"), "Order quantity")
        if not qty:
            continue
        item, variant, label = _resolve_line(db, tenant_id, raw)
        lines.append({"catalog_item_id": item["id"], "variant_id": variant["id"] if variant else None, "label": label,
                      "qty_ordered": qty, "unit_cost_paise": _int(raw.get("unit_cost_paise"), "Cost", 0, 10**10),
                      "gst_rate": _rate(raw.get("gst_rate"))})
    if not lines:
        raise PurchaseError("Add at least one item to order")
    items_paise = sum(li["unit_cost_paise"] * li["qty_ordered"] for li in lines)
    gst_paise = sum(_gst(li["unit_cost_paise"] * li["qty_ordered"], li["gst_rate"]) for li in lines)
    head = {"supplier_id": supplier["id"], "need_by": _date(data.get("need_by"), "Need by"),
            "place_id": _place(db, tenant_id, data.get("place_id")), "note": _one_line(data.get("note"))[:300] or None,
            "items_paise": items_paise, "gst_paise": gst_paise}
    if po_id:
        po = _po(db, tenant_id, po_id)
        if po["status"] != "draft":
            raise PurchaseError("A sent purchase order can't be changed. Make a new one.")
        db.table("purchase_orders").update(head).eq("id", po_id).eq("tenant_id", tenant_id).execute()
        db.table("purchase_order_lines").delete().eq("purchase_order_id", po_id).eq("tenant_id", tenant_id).execute()
    else:
        number = db.rpc("next_po_number", {"p_tenant_id": tenant_id}).execute().data
        po = (db.table("purchase_orders").insert({**head, "tenant_id": tenant_id, "number": int(number),
                                                   "created_by": user_id}).execute().data or [{}])[0]
        po_id = po["id"]
    for li in lines:
        db.table("purchase_order_lines").insert({**li, "tenant_id": tenant_id, "purchase_order_id": po_id}).execute()
    return po_view(db, tenant_id, po_id)


def po_view(db, tenant_id: str, po_id: str) -> dict:
    po = _po(db, tenant_id, po_id)
    supplier = _supplier(db, tenant_id, po["supplier_id"])
    lines = _po_lines(db, tenant_id, po_id)
    return {**po, "po_number": po_number(po["number"]), "supplier": supplier, "lines": lines,
            "total_paise": int(po["items_paise"]) + int(po["gst_paise"]),
            "message": po_message(db, tenant_id, po, supplier, lines)}


def po_message(db, tenant_id: str, po: dict, supplier: dict, lines: list[dict]) -> dict:
    from app.services.orders import _first_name, _shop_name

    items = ", ".join(f"{li['label']} x {li['qty_ordered']}" for li in lines)
    need_by = date.fromisoformat(str(po["need_by"])).strftime("%d %b").lstrip("0") if po.get("need_by") else "as soon as you can"
    values = [_first_name(supplier.get("name")), po_number(po["number"]), _shop_name(db, tenant_id), items[:700], need_by]
    text = (f"Vanakkam {values[0]}, purchase order {values[1]} from {values[2]}:\n"
            + "\n".join(f"• {li['label']} × {li['qty_ordered']}" for li in lines)
            + f"\nNeed by: {values[4]}\nPlease confirm, or tell us if the date doesn't work.")
    return {"text": text, "values": [_one_line(v) for v in values]}


def suggestions(db, tenant_id: str, now: datetime | None = None) -> list[dict]:
    """Items to reorder: at or below the alert level, or out while selling. Suggested = enough for
    the next 30 days from the last 30 days' sales, minus stock and what is already on order."""
    now = now or _now()
    since = (now - timedelta(days=SOLD_DAYS)).isoformat()
    items = (db.table("catalog_items").select("id, name, stock_quantity, low_stock_at, cost_price_paise, gst_rate")
             .eq("tenant_id", tenant_id).not_.is_("stock_quantity", "null").limit(5000).execute().data or [])
    variants = (db.table("catalog_item_variants").select("id, catalog_item_id, size, colour, stock_quantity, cost_price_paise")
                .eq("tenant_id", tenant_id).limit(20000).execute().data or [])
    sales = (db.table("stock_movements").select("catalog_item_id, variant_id, delta").eq("tenant_id", tenant_id)
             .eq("reason", "sale").gte("created_at", since).limit(50000).execute().data or [])
    open_pos = [p["id"] for p in (db.table("purchase_orders").select("id").eq("tenant_id", tenant_id)
                                  .in_("status", ["draft", "sent", "confirmed", "part_received"]).limit(1000).execute().data or [])]
    on_order_rows = (db.table("purchase_order_lines").select("catalog_item_id, variant_id, qty_ordered, qty_received")
                     .eq("tenant_id", tenant_id).in_("purchase_order_id", open_pos or ["00000000-0000-0000-0000-000000000000"])
                     .limit(20000).execute().data or [])
    sold: dict[tuple, int] = {}
    for s in sales:
        key = (s["catalog_item_id"], s.get("variant_id"))
        sold[key] = sold.get(key, 0) - int(s["delta"])
    on_order: dict[tuple, int] = {}
    for li in on_order_rows:
        key = (li["catalog_item_id"], li.get("variant_id"))
        on_order[key] = on_order.get(key, 0) + max(0, int(li["qty_ordered"]) - int(li["qty_received"]))
    by_item: dict[str, list[dict]] = {}
    for v in variants:
        by_item.setdefault(v["catalog_item_id"], []).append(v)
    from app.services.deals import variant_label

    out = []
    for item in items:
        rows = [(v, (item["id"], v["id"]), v["stock_quantity"], v.get("cost_price_paise")) for v in by_item.get(item["id"], [])] \
            or [(None, (item["id"], None), item["stock_quantity"], None)]
        alert = item.get("low_stock_at")
        for variant, key, stock, vcost in rows:
            sold30 = sold.get(key, 0)
            coming = on_order.get(key, 0)
            low = (alert is not None and stock <= alert) or (stock == 0 and sold30 > 0)
            suggested = max(0, sold30 - stock - coming)
            if not low or (not suggested and coming):
                continue
            out.append({
                "catalog_item_id": item["id"], "variant_id": key[1], "name": item["name"],
                "variant_label": variant_label(variant) if variant else None, "stock": stock, "sold_30d": sold30,
                "on_order": coming, "suggested": suggested or max(1, (alert or 0) + 1 - stock),
                "last_cost_paise": vcost or item.get("cost_price_paise"), "gst_rate": float(item.get("gst_rate") or 0),
            })
    out.sort(key=lambda r: (r["stock"], -r["sold_30d"], r["name"].lower()))
    return out


def pos_view(db, tenant_id: str, now: datetime | None = None) -> dict:
    now = now or _now()
    today = now.astimezone(IST).date()
    week_end = today + timedelta(days=7)
    month_start = today.replace(day=1).isoformat()
    pos = (db.table("purchase_orders").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True)
           .limit(300).execute().data or [])
    sups = {s["id"]: s for s in (db.table("suppliers").select("id, name, phone").eq("tenant_id", tenant_id)
                                 .limit(2000).execute().data or [])}
    lines = (db.table("purchase_order_lines").select("purchase_order_id, label, qty_ordered, qty_received")
             .eq("tenant_id", tenant_id).in_("purchase_order_id", [p["id"] for p in pos] or ["00000000-0000-0000-0000-000000000000"])
             .limit(20000).execute().data or [])
    by_po: dict[str, list[dict]] = {}
    for li in lines:
        by_po.setdefault(li["purchase_order_id"], []).append(li)
    rows, open_n, open_paise, coming, late = [], 0, 0, [], []
    for p in pos:
        mine = by_po.get(p["id"], [])
        is_open = p["status"] in ("sent", "confirmed", "part_received")
        need = date.fromisoformat(str(p["need_by"])) if p.get("need_by") else None
        late_days = (today - need).days if is_open and need and need < today else 0
        if is_open:
            open_n += 1
            open_paise += int(p["items_paise"]) + int(p["gst_paise"])
            if need and today <= need <= week_end:
                coming.append(sups.get(p["supplier_id"], {}).get("name"))
            if late_days:
                late.append((sups.get(p["supplier_id"], {}).get("name"), late_days))
        rows.append({
            **p, "po_number": po_number(p["number"]), "supplier_name": sups.get(p["supplier_id"], {}).get("name"),
            "items_text": " · ".join(f"{li['label']} {li['qty_ordered']}" for li in mine),
            "ordered": sum(int(li["qty_ordered"]) for li in mine),
            "received": sum(min(int(li["qty_received"]), int(li["qty_ordered"])) for li in mine),
            "total_paise": int(p["items_paise"]) + int(p["gst_paise"]), "late_days": late_days,
        })
    damaged = (db.table("stock_in_lines").select("qty_damaged, unit_cost_paise, damaged_action, stock_in_id")
               .eq("tenant_id", tenant_id).gt("qty_damaged", 0).limit(5000).execute().data or [])
    month_ins = {s["id"] for s in (db.table("stock_ins").select("id").eq("tenant_id", tenant_id)
                                   .gte("bill_date", month_start).limit(5000).execute().data or [])}
    damaged = [d for d in damaged if d["stock_in_id"] in month_ins]
    short = sum(max(0, int(li["qty_ordered"]) - int(li["qty_received"])) for p in rows if p["status"] == "part_received"
                for li in by_po.get(p["id"], []))
    reorder = suggestions(db, tenant_id, now)
    return {
        "orders": rows,
        "open": {"count": open_n, "paise": open_paise},
        "coming_this_week": {"count": len(coming), "suppliers": [c for c in coming if c]},
        "late": {"count": len(late), "first": late[0] if late else None},
        "to_reorder": {"count": len(reorder), "names": [r["name"] + (f" {r['variant_label']}" if r["variant_label"] else "")
                                                         for r in reorder[:6]]},
        "short_or_damaged": {"pieces": sum(int(d["qty_damaged"]) for d in damaged) + short,
                             "claim_paise": sum(int(d["qty_damaged"]) * int(d["unit_cost_paise"]) for d in damaged
                                                if d["damaged_action"] in ("replace", "less_on_bill"))},
    }


def cancel_po(db, tenant_id: str, po_id: str) -> None:
    po = _po(db, tenant_id, po_id)
    if po["status"] in ("received", "cancelled"):
        raise PurchaseError("This purchase order is already closed")
    db.table("purchase_orders").update({"status": "cancelled"}).eq("id", po_id).eq("tenant_id", tenant_id).execute()


def share_url(phone: str | None, text: str) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return f"https://wa.me/{digits}?text={quote(text)}" if digits else None


def template_status(db, tenant_id: str) -> str:
    from app.config_dynamic import get_setting

    waba = get_setting("meta_waba_id", tenant_id=tenant_id)
    rows = (db.table("message_templates").select("status, meta_waba_id").eq("tenant_id", tenant_id)
            .eq("name", TEMPLATE["name"]).execute().data or [])
    rows = [r for r in rows if not waba or r.get("meta_waba_id") == waba]
    if any((r.get("status") or "").upper() == "APPROVED" for r in rows):
        return "APPROVED"
    return (rows[0].get("status") or "PENDING").upper() if rows else "MISSING"


async def send_po(db, tenant_id: str, po_id: str, user_id: str | None) -> dict:
    """Send the PO to the supplier on WhatsApp (team-triggered): with Confirm / Change date buttons
    inside 24 hours or by the approved template; otherwise a wa.me link to send from the phone."""
    from app.config_dynamic import get_setting
    from app.services.call_details_share import window_open

    view = po_view(db, tenant_id, po_id)
    if view["status"] not in ("draft", "sent"):
        raise PurchaseError("This purchase order was already sent and answered")
    phone = view["supplier"].get("phone")
    text, values = view["message"]["text"], view["message"]["values"]
    result = {"sent": False, "via": None, "share_url": share_url(phone, text), "reason": None}
    sid, via = None, None
    if not phone:
        result["reason"] = "no_phone"
    elif get_setting("meta_phone_number_id", tenant_id=tenant_id) and get_setting("meta_access_token", tenant_id=tenant_id):
        lead = (db.table("leads").select("id, last_inbound_at").eq("tenant_id", tenant_id).eq("phone", phone)
                .limit(1).execute().data or [{}])[0]
        buttons = [{"id": f"{PO_CONFIRM}{po_id}", "title": "Confirm"}, {"id": f"{PO_DATE}{po_id}", "title": "Change date"}]
        try:
            if window_open(lead.get("last_inbound_at"), _now()):
                from app.services.meta_cloud import send_interactive_buttons

                resp = await send_interactive_buttons(phone, text[:1024], buttons, tenant_id=tenant_id)
                sid, via = ((resp or {}).get("messages") or [{}])[0].get("id"), "text"
            else:
                from app.services.orders import _send_order_template

                tpl = (db.table("message_templates").select("*").eq("tenant_id", tenant_id).eq("name", TEMPLATE["name"])
                       .eq("status", "APPROVED").limit(1).execute().data or [None])[0]
                if tpl:
                    sid, _ = await _send_order_template(db, tenant_id, phone, tpl, values, [b["id"] for b in buttons])
                    via = "template"
                else:
                    result["reason"] = "outside_24h_no_template"
        except Exception as exc:
            logger.warning("PO %s to supplier failed: %s", po_id, exc)
            result["reason"] = "send_failed"
    else:
        result["reason"] = "whatsapp_not_connected"
    if sid:
        result.update({"sent": True, "via": via})
    db.table("purchase_orders").update({"status": "sent", "sent_at": _now().isoformat(), "sent_via": via or "share"}) \
        .eq("id", po_id).eq("tenant_id", tenant_id).execute()
    return result


def button_po(interactive_id: str | None) -> tuple[str, str] | None:
    """'po_confirm:<id>' / 'po_date:<id>' -> (action, po id)."""
    for prefix, action in ((PO_CONFIRM, "confirm"), (PO_DATE, "date")):
        if interactive_id and interactive_id.startswith(prefix):
            value = interactive_id[len(prefix):].strip()
            return (action, value) if len(value) == 36 else None
    return None


async def answer_from_supplier(db, tenant_id: str, phone: str, action: str, po_id: str) -> bool:
    """The supplier tapped Confirm / Change date. Only their own POs count (phone must match)."""
    from app.services.brain_digest import owner_user_ids
    from app.services.notify import notify_user

    rows = db.table("purchase_orders").select("*").eq("id", po_id).eq("tenant_id", tenant_id).limit(1).execute().data
    if not rows:
        return False
    po = rows[0]
    supplier = (db.table("suppliers").select("name, phone").eq("id", po["supplier_id"]).eq("tenant_id", tenant_id)
                .limit(1).execute().data or [{}])[0]
    if re.sub(r"\D", "", supplier.get("phone") or "")[-10:] != re.sub(r"\D", "", phone or "")[-10:]:
        return False
    number = po_number(po["number"])
    if action == "confirm":
        if po["status"] == "sent":
            db.table("purchase_orders").update({"status": "confirmed", "confirmed_at": _now().isoformat()}) \
                .eq("id", po_id).eq("tenant_id", tenant_id).execute()
        title, message = f"{supplier.get('name')} confirmed {number}", "Shown as Confirmed by supplier in Purchases."
    else:
        db.table("purchase_orders").update({"date_change_asked_at": _now().isoformat()}) \
            .eq("id", po_id).eq("tenant_id", tenant_id).execute()
        title, message = f"{supplier.get('name')} can't make the date for {number}", "Call them to agree a new date."
    for user_id in owner_user_ids(db, tenant_id):
        notify_user(tenant_id, user_id, "purchase_order", title, message, db=db, push_url="/dashboard/purchases")
    return True


def sweep_unanswered(db, now: datetime | None = None, limit: int = 200) -> int:
    """POs sent 2+ days ago with no answer: one bell to the owner to call the supplier."""
    from app.services.brain_digest import owner_user_ids
    from app.services.notify import notify_user

    now = now or _now()
    rows = (db.table("purchase_orders").select("id, tenant_id, number, supplier_id").eq("status", "sent")
            .is_("reminded_at", "null").lt("sent_at", (now - REMIND_AFTER).isoformat()).limit(limit).execute().data or [])
    for po in rows:
        sup = (db.table("suppliers").select("name").eq("id", po["supplier_id"]).limit(1).execute().data or [{}])[0]
        for user_id in owner_user_ids(db, po["tenant_id"]):
            notify_user(po["tenant_id"], user_id, "purchase_order", f"No reply on {po_number(po['number'])}",
                        f"{sup.get('name') or 'The supplier'} hasn't confirmed in 2 days. Give them a call.", db=db,
                        push_url="/dashboard/purchases")
        db.table("purchase_orders").update({"reminded_at": now.isoformat()}).eq("id", po["id"]).execute()
    return len(rows)


# ── reading a supplier bill photo ─────────────────────────────────────────────

BILL_INSTRUCTION = (
    "This is a supplier's bill (purchase invoice) from an Indian shop. Read it and answer with JSON only, no prose:\n"
    '{"supplier": str|null, "bill_no": str|null, "date": "YYYY-MM-DD"|null, "gstin": str|null, '
    '"lines": [{"name": str, "size": str|null, "colour": str|null, "qty": int, "unit_cost": number, "gst_rate": number|null}]}\n'
    "unit_cost is the price of ONE piece before GST, in rupees. Copy names as printed. Skip totals, tax and round-off rows."
)


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(match.group(0)) if match else {}
    except ValueError:
        return {}


def match_lines(db, tenant_id: str, lines: list[dict]) -> list[dict]:
    """Match read lines to Catalogue items and sizes/colours by name; unmatched stay for staff."""
    from app.services.deals import variant_label

    items = db.table("catalog_items").select("id, name, gst_rate").eq("tenant_id", tenant_id).limit(5000).execute().data or []
    variants = (db.table("catalog_item_variants").select("id, catalog_item_id, size, colour").eq("tenant_id", tenant_id)
                .limit(20000).execute().data or [])

    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()

    out = []
    for raw in lines[:100]:
        name = norm(raw.get("name"))
        item = next((i for i in items if norm(i["name"]) == name), None) or \
            next((i for i in items if name and (norm(i["name"]) in name or name in norm(i["name"]))), None)
        variant = None
        if item:
            mine = [v for v in variants if v["catalog_item_id"] == item["id"]]
            size, colour = norm(raw.get("size")), norm(raw.get("colour"))
            variant = next((v for v in mine if norm(v.get("size")) == size and norm(v.get("colour")) == colour), None) or \
                next((v for v in mine if (size and norm(v.get("size")) == size) or (colour and norm(v.get("colour")) == colour)), None)
        try:
            qty = max(0, int(raw.get("qty") or 0))
            cost = max(0, int(round(float(raw.get("unit_cost") or 0) * 100)))
        except (TypeError, ValueError):
            qty, cost = 0, 0
        out.append({
            "read_name": _one_line(raw.get("name"))[:120], "catalog_item_id": item["id"] if item else None,
            "variant_id": variant["id"] if variant else None,
            "label": (item["name"] + (f" · {variant_label(variant)}" if variant else "")) if item else None,
            "qty_good": qty, "unit_cost_paise": cost,
            "gst_rate": raw.get("gst_rate") if raw.get("gst_rate") is not None else (item or {}).get("gst_rate") or 0,
        })
    return out


async def read_bill(db, tenant_id: str, content: bytes, mime_type: str) -> dict:
    from app.services.gemini_client import gemini_read_file

    try:
        text = await gemini_read_file(content, mime_type, BILL_INSTRUCTION, tenant_id=tenant_id, purpose="supplier_bill")
    except Exception as exc:
        logger.warning("Supplier bill read failed for tenant %s: %s", tenant_id, exc)
        raise PurchaseError("Couldn't read the bill. Try a clearer photo, or type it in.")
    data = _parse_json(text)
    supplier_name = _one_line(data.get("supplier"))[:120] or None
    sups = db.table("suppliers").select("id, name").eq("tenant_id", tenant_id).eq("archived", False).limit(2000).execute().data or []
    supplier = next((s for s in sups if supplier_name and s["name"].lower() == supplier_name.lower()), None)
    gstin = re.sub(r"\s", "", str(data.get("gstin") or "")).upper()
    return {
        "supplier_id": supplier["id"] if supplier else None, "supplier_name": supplier_name,
        "bill_no": _one_line(data.get("bill_no"))[:40] or None,
        "bill_date": data.get("date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("date") or "")) else None,
        "supplier_gstin": gstin if re.fullmatch(r"\d{2}[A-Z0-9]{13}", gstin) else None,
        "lines": match_lines(db, tenant_id, [li for li in data.get("lines") or [] if isinstance(li, dict)]),
    }


def options(db, tenant_id: str) -> dict:
    """What the Purchases forms pick from: items with sizes/colours and cost, places, suppliers."""
    from app.services.deals import variant_label

    items = (db.table("catalog_items").select("id, name, gst_rate, cost_price_paise, stock_quantity, item_type")
             .eq("tenant_id", tenant_id).order("name").limit(5000).execute().data or [])
    variants = (db.table("catalog_item_variants").select("id, catalog_item_id, size, colour, stock_quantity, cost_price_paise, sort_order")
                .eq("tenant_id", tenant_id).order("sort_order").limit(20000).execute().data or [])
    by_item: dict[str, list[dict]] = {}
    for v in variants:
        by_item.setdefault(v["catalog_item_id"], []).append(
            {"id": v["id"], "label": variant_label(v), "stock": v["stock_quantity"], "cost_price_paise": v.get("cost_price_paise")})
    places = (db.table("stock_places").select("id, name, kind, bills_from").eq("tenant_id", tenant_id).eq("archived", False)
              .order("sort_order").limit(100).execute().data or [])
    if not places:
        db.rpc("default_stock_place", {"p_tenant_id": tenant_id}).execute()
        places = (db.table("stock_places").select("id, name, kind, bills_from").eq("tenant_id", tenant_id)
                  .eq("archived", False).limit(100).execute().data or [])
    sups = (db.table("suppliers").select("id, name, phone, gstin").eq("tenant_id", tenant_id).eq("archived", False)
            .order("name").limit(2000).execute().data or [])
    return {
        "items": [{"id": i["id"], "name": i["name"], "gst_rate": float(i.get("gst_rate") or 0),
                   "cost_price_paise": i.get("cost_price_paise"), "stock": i.get("stock_quantity"),
                   "variants": by_item.get(i["id"], [])} for i in items if (i.get("item_type") or "product") == "product"],
        "places": places,
        "suppliers": sups,
    }


def supplier_by_phone(db, tenant_id: str, phone: str | None) -> dict | None:
    """The business's own supplier with this WhatsApp number (last 10 digits), if any."""
    digits = re.sub(r"\D", "", phone or "")[-10:]
    if len(digits) < 10:
        return None
    rows = (db.table("suppliers").select("id, name, phone").eq("tenant_id", tenant_id).eq("archived", False)
            .like("phone", f"%{digits}").limit(1).execute().data or [])
    return rows[0] if rows else None


def note_supplier_message(db, tenant_id: str, lead_id: str, supplier: dict) -> None:
    """A supplier wrote in: the AI must not answer them as a customer. The owner gets one bell
    (deduped while unread) to reply from the chat."""
    from app.services.brain_digest import owner_user_ids
    from app.services.notify import notify_user

    for user_id in owner_user_ids(db, tenant_id):
        notify_user(tenant_id, user_id, "supplier_message", f"{supplier['name']} sent a message",
                    f"Your supplier wrote on WhatsApp. Anril didn't reply; answer them from the chat. [lead_id:{lead_id}]",
                    db=db, dedupe_lead_id=lead_id, push_url=f"/dashboard/conversations?lead={lead_id}")
