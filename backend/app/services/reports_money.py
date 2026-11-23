"""Reports > Money, and the accountant's Excel file.

Sales = paid orders (stage won, by paid day) before GST. Profit = sales - refunds - cost of items sold
- expenses. For whole months it is the Expenses page's own number (services/expenses.month_view, read
only), so the two pages never disagree. For other days it is worked out for exactly those days and
the plan fee and stock loss (monthly things) are left out; the response says which ("scope").
"Still to collect" and "owed to suppliers" are as of today, not for the days.
"""
import io
import re
from datetime import date, timedelta

from fastapi import HTTPException

from app.services.reports_common import (
    Flags, Period, build_report, finish, money, paged, safe, safe_cell, sentence, today_ist, vs_before,
)
from app.services.reports_data import sales_before_gst, won_deals

METHOD_LABELS = {"cash": "Cash", "upi": "UPI", "card": "Card", "razorpay": "Razorpay (online)",
                 "bank_transfer": "Bank transfer", "other": "Other"}


def _period_text(period: Period) -> str:
    return f"{period.start.strftime('%d %b %Y')} to {period.end.strftime('%d %b %Y')}"


def _profit_parts(db, tenant_id: str, period: Period) -> tuple[int, int, str, str]:
    """(cost of items sold, expenses, scope, scope_label) for the days."""
    from app.services import expenses as ex
    months = period.whole_months()
    if months:
        cost = exp = 0
        for m in months:
            view = ex.month_view(db, tenant_id, m)
            cost += int(view["profit"]["cogs_paise"])
            exp += int(view["profit"]["expenses_paise"])
        label = date.fromisoformat(months[0] + "-01").strftime("%B %Y")
        if len(months) > 1:
            label += " to " + date.fromisoformat(months[-1] + "-01").strftime("%B %Y")
        return cost, exp, "month", label
    end_excl = period.end_excl_day
    cost = ex._cost_of_items_sold(db, tenant_id, period.start, end_excl)
    typed = paged(lambda: db.table("cash_expenses").select("id,amount_paise").eq("tenant_id", tenant_id)
                  .gte("day", period.start.isoformat()).lt("day", end_excl.isoformat()))
    exp = sum(int(r["amount_paise"]) for r in typed) + ex._meta_ads_paise(db, tenant_id, period.start, end_excl)
    return cost, exp, "range", _period_text(period)


def compute(db, tenant_id: str, period: Period, flags: Flags) -> tuple[dict, dict]:
    deals = won_deals(db, tenant_id, period)
    sales = sum(sales_before_gst(d) for d in deals)
    refunds = sum(int(r["amount_paise"]) for r in paged(
        lambda: db.table("deal_refunds").select("id,amount_paise").eq("tenant_id", tenant_id).neq("status", "failed")
        .gte("created_at", period.start_iso).lt("created_at", period.end_iso)))
    numbers: dict = {"sales_paise": sales, "orders": len(deals), "refunds_paise": refunds,
                     "gst_collected_paise": sum(int(d.get("gst_paise") or 0) for d in deals)}
    extras: dict = {}
    if flags.sees_profit:
        cost, expenses, scope, label = _profit_parts(db, tenant_id, period)
        numbers.update({"cost_paise": cost, "expenses_paise": expenses,
                        "profit_paise": sales - refunds - cost - expenses})
        extras["scope"] = scope
        extras["scope_label"] = label
        if scope == "range":
            extras["scope_note"] = "For picked days the plan fee and stock loss are not counted; pick whole months to include them."
        gst_paid = sum(int(r.get("gst_paise") or 0) for r in safe(lambda: paged(
            lambda: db.table("stock_ins").select("id,gst_paise").eq("tenant_id", tenant_id)
            .gte("bill_date", period.start.isoformat()).lt("bill_date", period.end_excl_day.isoformat())), [], "purchase GST"))
        numbers["gst_paid_paise"] = gst_paid
        numbers["gst_to_pay_paise"] = numbers["gst_collected_paise"] - gst_paid
    closings = safe(lambda: paged(lambda: db.table("day_closings").select("id,difference_paise").eq("tenant_id", tenant_id)
                                  .gte("day", period.start.isoformat()).lt("day", period.end_excl_day.isoformat())),
                    [], "day closing")
    numbers["cash_short_paise"] = sum(-int(r.get("difference_paise") or 0) for r in closings if int(r.get("difference_paise") or 0) < 0)
    return numbers, extras


def as_of_today(db, tenant_id: str, flags: Flags) -> dict:
    """Numbers that are about right now, not about the picked days."""
    open_rows = paged(lambda: db.table("deals").select("id,total_paise,paid_paise").eq("tenant_id", tenant_id)
                      .eq("stage", "awaiting_payment"))
    out = {"still_to_collect_paise": sum(max(int(r.get("total_paise") or 0) - int(r.get("paid_paise") or 0), 0) for r in open_rows)}
    if flags.sees_profit:
        from app.services.purchases import suppliers_view
        view = safe(lambda: suppliers_view(db, tenant_id), None, "supplier dues")
        out["owed_to_suppliers_paise"] = int(view["owe_paise"]) if view else None
    return out


def in_short(numbers: dict, before: dict | None) -> str:
    b = before or {}
    parts = []
    if "sales_paise" in numbers:
        change = vs_before(numbers["sales_paise"], b.get("sales_paise"), "paise")
        parts.append(f"{money(numbers['sales_paise'])} sales" + (f", {change}" if change else ""))
    if "profit_paise" in numbers:
        word = "profit" if numbers["profit_paise"] >= 0 else "loss"
        parts.append(f"{money(abs(numbers['profit_paise']))} {word}")
    if numbers.get("still_to_collect_paise"):
        parts.append(f"{money(numbers['still_to_collect_paise'])} still to collect")
    return sentence(parts, "No money figures to show for these days.")


def report(db, tenant_id: str, period: Period, compare: bool, flags: Flags) -> dict:
    if not flags.sees_money:  # every figure here is rupees: nothing to show, nothing computed
        return {"period": {}, "before": None, "money_hidden": True,
                "in_short": "Money figures are for people who can see orders."}
    payload = build_report(compute, db, tenant_id, period, compare, flags)
    now = as_of_today(db, tenant_id, flags)
    payload["period"].update(now)
    if payload["before"] is not None:
        payload["before"].update({k: None for k in now})
    from app.services import sales_target
    coverage = safe(lambda: sales_target.cost_coverage(db, tenant_id), None, "cost prices")
    payload["cost_coverage"] = coverage
    payload["has_cost_prices"] = bool(coverage and coverage.get("with_cost")) if coverage is not None else None
    payload = finish(payload, flags, keep=("cost_coverage",))
    payload["in_short"] = in_short(payload["period"], payload["before"])
    return payload


# ── the accountant's file ─────────────────────────────────────────────────────

def month_period(month: str | None) -> tuple[str, Period]:
    """'2026-10' -> that whole month. No month = last month."""
    if not month:
        first_this = today_ist().replace(day=1)
        month = (first_this - timedelta(days=1)).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=400, detail="The month must look like 2026-10.")
    start = date(int(month[:4]), int(month[5:]), 1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return month, Period(start, end)


def _rupees(paise) -> float:
    return int(paise or 0) / 100


def _fill(ws, header: list[str], rows: list[list]) -> None:
    from openpyxl.styles import Font
    ws.append(header)
    for r in rows:
        ws.append(r)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(12, min(40, max(len(str(c.value or "")) for c in col) + 2))


def accountant_excel(db, tenant_id: str, month: str | None) -> tuple[bytes, str]:
    """One Excel file: Summary, Sales B2B, Sales B2C, Credit notes, Purchases, Expenses, Payment split.
    Summary, Purchases and Expenses come from the Expenses page's own file (services/expenses.month_excel)."""
    from openpyxl import load_workbook

    from app.services import expenses as ex
    month, period = month_period(month)
    content, _ = ex.month_excel(db, tenant_id, month)
    wb = load_workbook(io.BytesIO(content))
    if "Sales" in wb.sheetnames:
        del wb["Sales"]

    deals = won_deals(db, tenant_id, period)
    header = ["Date", "Invoice", "Customer", "Buyer business", "Buyer GSTIN", "Total (₹)", "GST (₹)", "Before GST (₹)", "Paid by"]

    def sale_row(d: dict) -> list:
        return [str(d.get("won_at") or "")[:10], safe_cell(d.get("invoice_number") or ""), safe_cell(d.get("customer_name") or ""),
                safe_cell(d.get("buyer_business") or ""), d.get("buyer_gstin") or "", _rupees(d.get("total_paise")),
                _rupees(d.get("gst_paise")), _rupees(sales_before_gst(d)), METHOD_LABELS.get(d.get("payment_method") or "", "")]

    b2b = [d for d in deals if d.get("bill_type") == "gst" and d.get("buyer_gstin")]
    b2b_ids = {d['id'] for d in b2b}
    b2c = [d for d in deals if d['id'] not in b2b_ids]
    _fill(wb.create_sheet("Sales B2B"), header, [sale_row(d) for d in sorted(b2b, key=lambda d: str(d.get("won_at")))])
    _fill(wb.create_sheet("Sales B2C"), header, [sale_row(d) for d in sorted(b2c, key=lambda d: str(d.get("won_at")))])

    refunds = paged(lambda: db.table("deal_refunds").select("id,deal_id,amount_paise,method,reason,credit_note_number,created_at")
                    .eq("tenant_id", tenant_id).neq("status", "failed")
                    .gte("created_at", period.start_iso).lt("created_at", period.end_iso))
    order_ids = sorted({r["deal_id"] for r in refunds if r.get("deal_id")})
    orders: dict[str, dict] = {}
    for i in range(0, len(order_ids), 150):
        for d in db.table("deals").select("id,invoice_number,customer_name,deal_number").eq("tenant_id", tenant_id) \
                .in_("id", order_ids[i:i + 150]).execute().data or []:
            orders[d["id"]] = d
    credit_rows = []
    for r in sorted(refunds, key=lambda r: str(r.get("created_at"))):
        o = orders.get(r.get("deal_id") or "", {})
        credit_rows.append([str(r.get("created_at") or "")[:10], safe_cell(r.get("credit_note_number") or ""),
                            safe_cell(o.get("invoice_number") or ""), safe_cell(o.get("customer_name") or ""),
                            _rupees(r.get("amount_paise")), METHOD_LABELS.get(r.get("method") or "", ""), safe_cell(r.get("reason") or "")])
    _fill(wb.create_sheet("Credit notes"), ["Date", "Credit note", "Invoice", "Customer", "Amount (₹)", "Paid back by", "Reason"], credit_rows)

    pays = paged(lambda: db.table("deal_payments").select("id,amount_paise,method").eq("tenant_id", tenant_id)
                 .gte("paid_at", period.start_iso).lt("paid_at", period.end_iso))
    got: dict[str, int] = {}
    back: dict[str, int] = {}
    for p in pays:
        got[p["method"]] = got.get(p["method"], 0) + int(p["amount_paise"])
    for r in refunds:
        back[r["method"]] = back.get(r["method"], 0) + int(r["amount_paise"])
    split = [[METHOD_LABELS.get(m, m), _rupees(got.get(m, 0)), _rupees(back.get(m, 0)), _rupees(got.get(m, 0) - back.get(m, 0))]
             for m in sorted(set(got) | set(back))]
    split.append(["Total", _rupees(sum(got.values())), _rupees(sum(back.values())), _rupees(sum(got.values()) - sum(back.values()))])
    _fill(wb.create_sheet("Payment split"), ["Paid by", "Received (₹)", "Paid back (₹)", "Net (₹)"], split)

    order = ["Summary", "Sales B2B", "Sales B2C", "Credit notes", "Purchases", "Expenses", "Payment split"]
    wb._sheets = [wb[n] for n in order if n in wb.sheetnames] + [s for s in wb._sheets if s.title not in order]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"anril-{month}-for-accountant.xlsx"
