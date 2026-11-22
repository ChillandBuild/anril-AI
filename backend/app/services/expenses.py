"""Expenses (plan: docs/plans/commerce-stock-plan.md, "The rest"; migration 313).

What the business spends, so profit is real. Typed expenses live in cash_expenses (Day closing's table;
its drawer counts only method 'cash'). Rent, salary… repeat by themselves on their day each month.
Added by themselves (not stored twice): purchases from Stock in and supplier payments (shown, but they are
not an expense in profit: stock bought becomes "cost of items sold" when it sells), Meta ads spend, the
Anril plan, and stock loss from counts.

Real profit (month) = sales (before GST) − refunds − cost of items sold − expenses.
"""
from __future__ import annotations

import calendar
import io
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
CATEGORIES = {"rent": "Rent", "salary": "Salary", "electricity": "Electricity", "transport": "Transport",
              "food": "Tea & food", "packing": "Packing & courier", "other": "Other"}
METHODS = {"cash": "Cash", "upi": "UPI", "bank": "Bank", "card": "Card"}
MAX_AMOUNT = 10_000_000_00  # ₹1 crore
BILL_BUCKET = "expense-bills"
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class ExpenseError(ValueError):
    """A plain-words problem the dashboard shows as is (routes turn it into a 400)."""


def today() -> date:
    return datetime.now(IST).date()


def month_bounds(month: str | None) -> tuple[date, date]:
    """('2026-11') → (1 Nov, 1 Dec). Default: this month."""
    if month and re.fullmatch(r"\d{4}-\d{2}", month):
        y, m = int(month[:4]), int(month[5:])
        if 1 <= m <= 12 and 2000 <= y <= 2100:
            start = date(y, m, 1)
            return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    t = today()
    start = t.replace(day=1)
    return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def _ist_iso(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=IST).isoformat()


def _amount(value) -> int:
    try:
        paise = int(value)
    except (TypeError, ValueError):
        raise ExpenseError("Type the amount.")
    if not 0 < paise <= MAX_AMOUNT:
        raise ExpenseError("Type the amount.")
    return paise


# ── typed expenses ───────────────────────────────────────────────────────────


def add(db, tenant_id: str, data: dict, user_id: str | None) -> dict:
    category = data.get("category") if data.get("category") in CATEGORIES else "other"
    method = data.get("method") if data.get("method") in METHODS else "cash"
    label = " ".join(str(data.get("label") or "").split())[:80] or CATEGORIES[category]
    try:
        day = date.fromisoformat(str(data.get("day"))[:10]) if data.get("day") else today()
    except ValueError:
        raise ExpenseError("Pick the date.")
    if day > today():
        raise ExpenseError("The date can't be in the future.")
    if method == "cash" and day < today() and (db.table("day_closings").select("id").eq("tenant_id", tenant_id)
                                                 .eq("day", day.isoformat()).limit(1).execute().data):
        raise ExpenseError("That day is already closed in Day closing: pick UPI / bank, or today's date.")
    return db.table("cash_expenses").insert({
        "tenant_id": tenant_id, "day": day.isoformat(), "label": label, "amount_paise": _amount(data.get("amount_paise")),
        "category": category, "method": method, "spent_by": " ".join(str(data.get("spent_by") or "").split())[:60] or None,
        "created_by": user_id,
    }).execute().data[0]


def _own_today(row: dict, user_id: str | None) -> bool:
    return bool(user_id) and row.get("created_by") == user_id and str(row.get("day")) == today().isoformat()


def delete(db, tenant_id: str, expense_id: str, *, user_id: str | None = None, manager: bool = True) -> None:
    """Managers (purchases.manage) delete any; a cashier only what they typed today."""
    if not _UUID.fullmatch(str(expense_id)):
        raise ExpenseError("That expense isn't there any more.")
    rows = (db.table("cash_expenses").select("bill_path, created_by, day").eq("id", expense_id).eq("tenant_id", tenant_id)
            .limit(1).execute().data or [])
    if not rows:
        raise ExpenseError("That expense isn't there any more.")
    if not manager and not _own_today(rows[0], user_id):
        raise ExpenseError("You can delete only what you added today.")
    db.table("cash_expenses").delete().eq("id", expense_id).eq("tenant_id", tenant_id).execute()
    if rows[0].get("bill_path"):
        try:
            db.storage.from_(BILL_BUCKET).remove([rows[0]["bill_path"]])
        except Exception:
            logger.warning("Couldn't remove the bill photo of expense %s", expense_id)


def attach_bill(db, tenant_id: str, expense_id: str, content: bytes, mime: str, *, user_id: str | None = None,
                manager: bool = True) -> str:
    """A photo / PDF of the bill, kept privately with the expense."""
    if not _UUID.fullmatch(str(expense_id)):
        raise ExpenseError("That expense isn't there any more.")
    ext = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}.get(mime)
    if not ext:
        raise ExpenseError("Add a photo (JPG or PNG) or a PDF of the bill.")
    if not content or len(content) > 8 * 1024 * 1024:
        raise ExpenseError("The bill must be under 8 MB.")
    head = content[:8]
    if (ext == "pdf" and not head.startswith(b"%PDF")) or (ext == "png" and not head.startswith(b"\x89PNG")) \
            or (ext == "jpg" and not head.startswith(b"\xff\xd8")):
        raise ExpenseError("That file isn't a real photo or PDF.")
    row = (db.table("cash_expenses").select("id, created_by, day").eq("id", expense_id).eq("tenant_id", tenant_id)
           .limit(1).execute().data or [])
    if not row:
        raise ExpenseError("That expense isn't there any more.")
    if not manager and not _own_today(row[0], user_id):
        raise ExpenseError("You can add a bill only to what you added today.")
    path = f"{tenant_id}/{expense_id}.{ext}"
    db.storage.from_(BILL_BUCKET).upload(path, content, {"content-type": mime, "upsert": "true"})
    db.table("cash_expenses").update({"bill_path": path}).eq("id", expense_id).eq("tenant_id", tenant_id).execute()
    return path


def bill_url(db, tenant_id: str, expense_id: str) -> str:
    rows = (db.table("cash_expenses").select("bill_path").eq("id", expense_id).eq("tenant_id", tenant_id)
            .limit(1).execute().data or []) if _UUID.fullmatch(str(expense_id)) else []
    if not rows or not rows[0].get("bill_path"):
        raise ExpenseError("No bill photo on this expense.")
    signed = db.storage.from_(BILL_BUCKET).create_signed_url(rows[0]["bill_path"], 300)
    return signed.get("signedURL") or signed.get("signedUrl") or ""


# ── repeats (rent, salary…) ──────────────────────────────────────────────────


def save_repeat(db, tenant_id: str, data: dict, user_id: str | None, repeat_id: str | None = None) -> dict:
    category = data.get("category") if data.get("category") in CATEGORIES else "other"
    try:
        day = int(data.get("day_of_month"))
    except (TypeError, ValueError):
        raise ExpenseError("Pick the day of the month.")
    if not 1 <= day <= 31:
        raise ExpenseError("Pick the day of the month.")
    fields = {"category": category, "label": " ".join(str(data.get("label") or "").split())[:80] or CATEGORIES[category],
              "amount_paise": _amount(data.get("amount_paise")),
              "method": data.get("method") if data.get("method") in METHODS else "bank", "day_of_month": day,
              "active": data.get("active", True) is not False}
    if repeat_id:
        if not _UUID.fullmatch(str(repeat_id)):
            raise ExpenseError("That repeat isn't there any more.")
        rows = db.table("expense_repeats").update(fields).eq("id", repeat_id).eq("tenant_id", tenant_id).execute().data
        if not rows:
            raise ExpenseError("That repeat isn't there any more.")
        return rows[0]
    row = db.table("expense_repeats").insert({**fields, "tenant_id": tenant_id, "created_by": user_id}).execute().data[0]
    run_repeats(db, tenant_id=tenant_id)  # this month's, if its day has passed
    return row


def _due_day(day_of_month: int, month_start: date) -> date:
    last = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start.replace(day=min(day_of_month, last))


def run_repeats(db=None, now: date | None = None, tenant_id: str | None = None) -> int:
    """Add each active repeat on its day (the daily job; safe to run twice). Only ON the day, so a month's
    entry the owner deleted doesn't come back the next morning; a repeat saved after its day this month is
    added once when it is saved (tenant_id given)."""
    from app.db.supabase import get_supabase

    db = db or get_supabase()
    now = now or today()
    month = now.replace(day=1)
    q = db.table("expense_repeats").select("*").eq("active", True)
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    added = 0
    for r in q.limit(10000).execute().data or []:
        due = _due_day(int(r["day_of_month"]), month)
        if due > now or (tenant_id is None and due != now):
            continue
        if db.table("cash_expenses").select("id").eq("repeat_id", r["id"]).eq("repeat_month", month.isoformat()) \
                .limit(1).execute().data:
            continue
        try:
            db.table("cash_expenses").insert({
                "tenant_id": r["tenant_id"], "day": due.isoformat(), "label": r["label"], "amount_paise": r["amount_paise"],
                "category": r["category"], "method": r["method"], "repeat_id": r["id"], "repeat_month": month.isoformat(),
            }).execute()
            added += 1
        except Exception as e:  # added at the same moment by another run
            if "23505" not in str(e) and "duplicate" not in str(e).lower():
                raise
    return added


# ── the month ────────────────────────────────────────────────────────────────


def _cost_of_items_sold(db, tenant_id: str, start: date, end: date) -> int:
    moves = (db.table("stock_movements").select("catalog_item_id, variant_id, delta, reason").eq("tenant_id", tenant_id)
             .in_("reason", ["sale", "return"]).gte("created_at", _ist_iso(start)).lt("created_at", _ist_iso(end))
             .limit(50000).execute().data or [])
    if not moves:
        return 0
    item_ids = list({m["catalog_item_id"] for m in moves})
    items = {r["id"]: int(r.get("cost_price_paise") or 0) for r in (
        db.table("catalog_items").select("id, cost_price_paise").eq("tenant_id", tenant_id).in_("id", item_ids).execute().data or [])}
    variant_ids = list({m["variant_id"] for m in moves if m.get("variant_id")})
    variants = {r["id"]: int(r.get("cost_price_paise") or 0) for r in (
        db.table("catalog_item_variants").select("id, cost_price_paise").eq("tenant_id", tenant_id).in_("id", variant_ids)
        .execute().data or [])} if variant_ids else {}
    return sum(-int(m["delta"]) * (variants.get(m.get("variant_id") or "") or items.get(m["catalog_item_id"], 0)) for m in moves)


def _meta_ads_paise(db, tenant_id: str, start: date, end: date) -> int:
    try:
        rows = (db.table("ad_insights_daily").select("spend").eq("tenant_id", tenant_id).gte("insight_date", start.isoformat())
                .lt("insight_date", end.isoformat()).limit(50000).execute().data or [])
    except Exception:
        return 0
    return round(sum(float(r.get("spend") or 0) for r in rows) * 100)


def _plan_paise(db, tenant_id: str) -> int:
    try:
        rows = db.table("tenant_subscriptions").select("status, mrr").eq("tenant_id", tenant_id).limit(1).execute().data or []
    except Exception:
        return 0
    row = rows[0] if rows else {}
    return round(float(row.get("mrr") or 0) * 100) if row.get("status") in ("active", "trialing", "past_due") else 0


def month_view(db, tenant_id: str, month: str | None = None) -> dict:
    from app.services.stock_counts import stock_loss

    start, end = month_bounds(month)
    typed = (db.table("cash_expenses").select("id, day, label, amount_paise, category, method, spent_by, bill_path, repeat_id, created_at")
             .eq("tenant_id", tenant_id).gte("day", start.isoformat()).lt("day", end.isoformat())
             .order("day", desc=True).limit(5000).execute().data or [])
    purchases = (db.table("stock_ins").select("total_paise").eq("tenant_id", tenant_id).gte("bill_date", start.isoformat())
                 .lt("bill_date", end.isoformat()).limit(20000).execute().data or [])
    supplier_paid = (db.table("supplier_payments").select("amount_paise").eq("tenant_id", tenant_id)
                     .gte("paid_on", start.isoformat()).lt("paid_on", end.isoformat()).limit(20000).execute().data or [])
    won = (db.table("deals").select("total_paise, gst_paise").eq("tenant_id", tenant_id).eq("stage", "won")
           .gte("won_at", _ist_iso(start)).lt("won_at", _ist_iso(end)).limit(50000).execute().data or [])
    refunds = (db.table("deal_refunds").select("amount_paise").eq("tenant_id", tenant_id).neq("status", "failed")
               .gte("created_at", _ist_iso(start)).lt("created_at", _ist_iso(end)).limit(20000).execute().data or [])
    repeats = (db.table("expense_repeats").select("*").eq("tenant_id", tenant_id).eq("active", True).order("day_of_month")
               .execute().data or [])
    ads = _meta_ads_paise(db, tenant_id, start, end)
    plan = _plan_paise(db, tenant_id)
    loss = stock_loss(db, tenant_id, _ist_iso(start), _ist_iso(end)) if start <= today() else 0
    auto = [r for r in (
        {"key": "purchases", "label": "Purchases (from Stock in)", "amount_paise": sum(int(p["total_paise"]) for p in purchases),
         "note": "becomes cost of items sold when it sells", "in_profit": False},
        {"key": "supplier_payments", "label": "Paid to suppliers", "amount_paise": sum(int(p["amount_paise"]) for p in supplier_paid),
         "note": "for stock you bought (Purchases)", "in_profit": False},
        {"key": "meta_ads", "label": "Meta ads", "amount_paise": ads, "note": "from your ad account", "in_profit": True},
        {"key": "plan", "label": "Anril plan", "amount_paise": plan, "note": "from Plan & bills", "in_profit": True},
        {"key": "stock_loss", "label": "Stock loss", "amount_paise": max(loss, 0), "note": "from stock counts", "in_profit": True},
    ) if r["amount_paise"]]
    typed_total = sum(int(r["amount_paise"]) for r in typed)
    expenses_total = typed_total + sum(r["amount_paise"] for r in auto if r["in_profit"])
    sales = sum(int(d.get("total_paise") or 0) - int(d.get("gst_paise") or 0) for d in won)
    refunded = sum(int(r["amount_paise"]) for r in refunds)
    cogs = _cost_of_items_sold(db, tenant_id, start, end)
    return {
        "month": start.strftime("%Y-%m"), "month_label": start.strftime("%B %Y"), "is_current": start <= today() < end,
        "expenses": [{**r, "category_label": CATEGORIES.get(r.get("category"), "Other"), "method_label": METHODS.get(r.get("method"), "Cash"),
                      "has_bill": bool(r.get("bill_path"))} for r in typed],
        "auto": auto, "repeats": repeats,
        "profit": {"sales_paise": sales, "refunds_paise": refunded, "cogs_paise": cogs, "expenses_paise": expenses_total,
                   "profit_paise": sales - refunded - cogs - expenses_total},
        "by_category": {k: sum(int(r["amount_paise"]) for r in typed if r.get("category") == k) for k in CATEGORIES},
    }


def _cell(value):
    """Text a spreadsheet must never run as a formula (a customer name like '=HYPERLINK(...)')."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def month_excel(db, tenant_id: str, month: str | None = None) -> tuple[bytes, str]:
    """One file for the accountant: summary, sales, purchases (GST), expenses."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    view = month_view(db, tenant_id, month)
    start, end = month_bounds(view["month"])
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    p = view["profit"]
    rows = [("Month", view["month_label"]), ("Sales (before GST)", p["sales_paise"] / 100), ("Refunds", -p["refunds_paise"] / 100),
            ("Cost of items sold", -p["cogs_paise"] / 100), ("Expenses (no purchases)", -p["expenses_paise"] / 100),
            ("Profit", p["profit_paise"] / 100)]
    for r in rows:
        ws.append(r)
    ws["A6"].font = ws["B6"].font = Font(bold=True)

    sales = wb.create_sheet("Sales")
    sales.append(["Date", "Invoice", "Customer", "Total (₹)", "GST (₹)", "Before GST (₹)"])
    for d in (db.table("deals").select("won_at, invoice_number, customer_name, total_paise, gst_paise").eq("tenant_id", tenant_id)
              .eq("stage", "won").gte("won_at", _ist_iso(start)).lt("won_at", _ist_iso(end)).order("won_at")
              .limit(50000).execute().data or []):
        total, gst = int(d.get("total_paise") or 0), int(d.get("gst_paise") or 0)
        sales.append([str(d.get("won_at") or "")[:10], _cell(d.get("invoice_number") or ""), _cell(d.get("customer_name") or ""),
                      total / 100, gst / 100, (total - gst) / 100])

    pur = wb.create_sheet("Purchases")
    pur.append(["Bill date", "Bill no.", "Supplier", "Supplier GSTIN", "Items (₹)", "GST paid (₹)", "Total (₹)"])
    sups = {s["id"]: s["name"] for s in (db.table("suppliers").select("id, name").eq("tenant_id", tenant_id).limit(2000).execute().data or [])}
    for s in (db.table("stock_ins").select("bill_date, bill_no, supplier_id, supplier_gstin, items_paise, gst_paise, total_paise")
              .eq("tenant_id", tenant_id).gte("bill_date", start.isoformat()).lt("bill_date", end.isoformat()).order("bill_date")
              .limit(20000).execute().data or []):
        pur.append([s["bill_date"], _cell(s.get("bill_no") or ""), _cell(sups.get(s.get("supplier_id") or "", "")), s.get("supplier_gstin") or "",
                    int(s.get("items_paise") or 0) / 100, int(s.get("gst_paise") or 0) / 100, int(s.get("total_paise") or 0) / 100])

    exp = wb.create_sheet("Expenses")
    exp.append(["Date", "Type", "What", "Paid by", "Amount (₹)"])
    for e in sorted(view["expenses"], key=lambda e: e["day"]):
        exp.append([e["day"], e["category_label"], _cell(e["label"]), e["method_label"], int(e["amount_paise"]) / 100])
    for a in view["auto"]:
        exp.append([view["month"], "Added by itself", a["label"], "", a["amount_paise"] / 100])
    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = max(12, min(40, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"anril-{view['month']}-for-accountant.xlsx"
