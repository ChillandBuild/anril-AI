"""Orders & payments > Day closing: today's money against the cash drawer.

    Should be = opening cash + cash sales − cash refunds − cash spent

Money in is grouped by how it was paid (cash / UPI / card / WhatsApp link / bank); bills are
the orders that got money today. Cash spent is typed here (cash_expenses, migration 296) until
the Expenses tab exists. Closing saves one row per day (day_closings; closing again replaces it),
writes the activity log, and rings the owners' bell when the drawer is short or over. The day
is the IST calendar day.
"""
import csv
import io
import logging
from datetime import date, datetime, time, timedelta

from app.services.orders import IST, METHOD_LABELS, OrderError, _now, _rupees

logger = logging.getLogger(__name__)

METHOD_ORDER = ("cash", "upi", "card", "razorpay", "bank_transfer", "other")
LOW_STOCK = 2


def _bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time.min, IST)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def parse_day(text: str | None) -> date:
    today = _now().astimezone(IST).date()
    if not text:
        return today
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise OrderError("Pick a day")
    if day > today:
        raise OrderError("That day hasn't happened yet")
    return day


def summary(db, tenant_id: str, day: date) -> dict:
    start, end = _bounds(day)
    payments = (
        db.table("deal_payments").select("amount_paise, method, deal_id").eq("tenant_id", tenant_id)
        .gte("paid_at", start).lt("paid_at", end).limit(10000).execute()
    ).data or []
    refunds = (
        db.table("deal_refunds").select("amount_paise, method, deal_id, reason").eq("tenant_id", tenant_id)
        .neq("status", "failed").gte("created_at", start).lt("created_at", end).limit(5000).execute()
    ).data or []
    expenses = (
        db.table("cash_expenses").select("id, label, amount_paise, spent_by, created_at").eq("tenant_id", tenant_id)
        .eq("day", day.isoformat()).eq("method", "cash").order("created_at").execute()  # the drawer: cash only (313)
    ).data or []
    closed = (
        db.table("day_closings").select("*").eq("tenant_id", tenant_id).eq("day", day.isoformat()).limit(1).execute()
    ).data or []
    previous = (
        db.table("day_closings").select("counted_paise, day").eq("tenant_id", tenant_id)
        .lt("day", day.isoformat()).order("day", desc=True).limit(1).execute()
    ).data or []

    by_method: dict[str, dict] = {}
    for p in payments:
        m = p.get("method") if p.get("method") in METHOD_ORDER else "other"
        row = by_method.setdefault(m, {"method": m, "label": METHOD_LABELS.get(m, "Other"), "paise": 0, "orders": set()})
        row["paise"] += int(p["amount_paise"])
        row["orders"].add(p["deal_id"])
    methods = [
        {**by_method[m], "orders": len(by_method[m]["orders"])} for m in METHOD_ORDER if m in by_method
    ]
    money_in = sum(int(p["amount_paise"]) for p in payments)
    bills = len({p["deal_id"] for p in payments})

    # Who the refunds were for ("1 · Divya, cash").
    names: dict[str, str] = {}
    deal_ids = sorted({r["deal_id"] for r in refunds})
    if deal_ids:
        deals = db.table("deals").select("id, lead_id, customer_name").eq("tenant_id", tenant_id).in_("id", deal_ids).execute().data or []
        lead_ids = sorted({d["lead_id"] for d in deals if d.get("lead_id")})
        leads = {}
        if lead_ids:
            leads = {l["id"]: l.get("name") for l in db.table("leads").select("id, name").eq("tenant_id", tenant_id).in_("id", lead_ids).execute().data or []}
        for d in deals:
            names[d["id"]] = (leads.get(d.get("lead_id")) or d.get("customer_name") or "Walk-in").split(" ")[0]

    cash_sales = by_method.get("cash", {}).get("paise", 0)
    cash_refunds = sum(int(r["amount_paise"]) for r in refunds if r["method"] == "cash")
    cash_spent = sum(int(e["amount_paise"]) for e in expenses)
    row = closed[0] if closed else None
    opening = int(row["opening_paise"]) if row else int(previous[0]["counted_paise"]) if previous else 0
    return {
        "day": day.isoformat(),
        "money_in": {"paise": money_in, "bills": bills, "average_paise": money_in // bills if bills else 0},
        "methods": methods,
        "refunds": {
            "paise": sum(int(r["amount_paise"]) for r in refunds),
            "items": [{"name": names.get(r["deal_id"], "Customer"), "method": METHOD_LABELS.get(r["method"], "Other"),
                       "paise": int(r["amount_paise"])} for r in refunds],
        },
        "expenses": {"paise": cash_spent, "items": expenses},
        "drawer": {
            "opening_paise": opening, "opening_from": "closing" if row else ("yesterday" if previous else "none"),
            "cash_sales_paise": cash_sales, "cash_refunds_paise": cash_refunds, "cash_expenses_paise": cash_spent,
            "expected_paise": opening + cash_sales - cash_refunds - cash_spent,
        },
        "closed": row,
        "running_low": running_low(db, tenant_id),
        "expiring": _expiring(db, tenant_id),
    }


def _expiring(db, tenant_id: str) -> dict:
    """Batches & expiry: expired and ≤30-day batches (never breaks the day's summary)."""
    try:
        from app.services.stock_batches import expiring_summary
        return expiring_summary(db, tenant_id)
    except Exception:
        logger.warning("Couldn't read expiring batches for tenant %s", tenant_id)
        return {"expired": 0, "soon": 0, "names": []}


def running_low(db, tenant_id: str, limit: int = 8) -> list[dict]:
    """Sizes/colours and plain items with 2 or fewer left (out of stock first)."""
    from app.services.deals import variant_label
    out = []
    variants = (
        db.table("catalog_item_variants").select("catalog_item_id, size, colour, stock_quantity").eq("tenant_id", tenant_id)
        .lte("stock_quantity", LOW_STOCK).limit(200).execute()
    ).data or []
    item_ids = sorted({v["catalog_item_id"] for v in variants})
    names = {}
    if item_ids:
        names = {i["id"]: i["name"] for i in db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id)
                 .in_("id", item_ids).eq("status", "ready").execute().data or []}
    for v in variants:
        if v["catalog_item_id"] in names:
            out.append({"name": f"{names[v['catalog_item_id']]} {variant_label(v)}".strip(), "left": v["stock_quantity"]})
    with_variants = set(item_ids)
    plain = (
        db.table("catalog_items").select("id, name, stock_quantity").eq("tenant_id", tenant_id).eq("status", "ready")
        .not_.is_("stock_quantity", "null").lte("stock_quantity", LOW_STOCK).limit(200).execute()
    ).data or []
    out += [{"name": i["name"], "left": i["stock_quantity"]} for i in plain if i["id"] not in with_variants]
    out.sort(key=lambda x: (x["left"], x["name"]))
    return out[:limit]


def add_expense(db, tenant_id: str, day: date, label: str, amount_paise: int, spent_by: str | None,
                user_id: str | None) -> dict:
    label = " ".join((label or "").split())[:80]
    if not label:
        raise OrderError("What was the cash spent on?")
    if amount_paise <= 0:
        raise OrderError("Type the amount")
    rows = db.table("cash_expenses").insert({
        "tenant_id": tenant_id, "day": day.isoformat(), "label": label, "amount_paise": int(amount_paise),
        "spent_by": (spent_by or "").strip()[:60] or None, "created_by": user_id, "method": "cash",
    }).execute().data or []
    return rows[0] if rows else {}


def delete_expense(db, tenant_id: str, expense_id: str) -> None:
    db.table("cash_expenses").delete().eq("id", expense_id).eq("tenant_id", tenant_id).execute()


def close_day(db, tenant_id: str, day: date, *, opening_paise: int, counted_paise: int, note: str | None,
              user_id: str | None, user_role: str | None = None) -> dict:
    if opening_paise < 0 or counted_paise < 0:
        raise OrderError("Amounts can't be below zero")
    s = summary(db, tenant_id, day)
    d = s["drawer"]
    expected = int(opening_paise) + d["cash_sales_paise"] - d["cash_refunds_paise"] - d["cash_expenses_paise"]
    difference = int(counted_paise) - expected
    row = {
        "tenant_id": tenant_id, "day": day.isoformat(), "opening_paise": int(opening_paise),
        "cash_sales_paise": d["cash_sales_paise"], "cash_refunds_paise": d["cash_refunds_paise"],
        "cash_expenses_paise": d["cash_expenses_paise"], "expected_paise": expected,
        "counted_paise": int(counted_paise), "difference_paise": difference,
        "note": (note or "").strip()[:300] or None, "closed_by": user_id, "closed_at": _now().isoformat(),
    }
    db.table("day_closings").upsert(row, on_conflict="tenant_id,day").execute()
    try:
        from app.services.audit_log import record_audit_event
        record_audit_event(db, tenant_id=tenant_id, actor_user_id=user_id, actor_role=user_role,
                           action="day.closed", target_type="day_closing", target_id=day.isoformat(),
                           metadata={k: row[k] for k in ("opening_paise", "expected_paise", "counted_paise", "difference_paise")})
    except Exception as e:
        logger.warning(f"Day closing audit failed for {tenant_id} {day}: {e}")
    if difference:
        _ring_owners(db, tenant_id, day, difference)
    return {**summary(db, tenant_id, day), "difference_paise": difference}


def _ring_owners(db, tenant_id: str, day: date, difference: int) -> None:
    try:
        from app.services.notify import notify_user
        owners = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").execute().data or []
        word = "short" if difference < 0 else "over"
        for o in owners:
            notify_user(tenant_id, o["user_id"], "day_closing",
                        f"Cash drawer {_rupees(abs(difference))} {word} on {day.strftime('%d %b')}",
                        "Saved with who closed the day. Open Day closing to see it.", db=db,
                        push_url=f"/dashboard/deals/day-closing?day={day.isoformat()}")
    except Exception as e:
        logger.warning(f"Day closing bell failed for {tenant_id}: {e}")


def export_csv(db, tenant_id: str, day: date) -> str:
    s = summary(db, tenant_id, day)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Day closing", s["day"]])
    w.writerow([])
    w.writerow(["Paid by", "Bills", "Amount (Rs)"])
    for m in s["methods"]:
        w.writerow([m["label"], m["orders"], m["paise"] / 100])
    w.writerow(["Money in", s["money_in"]["bills"], s["money_in"]["paise"] / 100])
    w.writerow([])
    w.writerow(["Refunds", "", s["refunds"]["paise"] / 100])
    for r in s["refunds"]["items"]:
        w.writerow([f"  {r['name']} ({r['method']})", "", r["paise"] / 100])
    w.writerow(["Cash spent", "", s["expenses"]["paise"] / 100])
    for e in s["expenses"]["items"]:
        w.writerow([f"  {e['label']}" + (f" ({e['spent_by']})" if e.get("spent_by") else ""), "", int(e["amount_paise"]) / 100])
    w.writerow([])
    d = s["drawer"]
    closed = s["closed"] or {}
    for label, value in (("Opening cash", closed.get("opening_paise", d["opening_paise"])), ("Cash sales", d["cash_sales_paise"]),
                         ("Cash refunds", -d["cash_refunds_paise"]), ("Cash spent", -d["cash_expenses_paise"]),
                         ("Should be", closed.get("expected_paise", d["expected_paise"]))):
        w.writerow([label, "", int(value) / 100])
    if closed:
        w.writerow(["Counted", "", int(closed["counted_paise"]) / 100])
        w.writerow(["Difference", "", int(closed["difference_paise"]) / 100])
    return out.getvalue()
