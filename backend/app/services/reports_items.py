"""Reports > Items & orders: what sold, what is running low, orders by stage.

Sold = lines of paid orders (stage won) in the days. Low stock and the open stages (quote sent, waiting for
payment) are as of today, not for the days.
"""
from app.services.reports_common import Flags, Period, chunks, money, paged, plural, safe, sentence
from app.services.reports_data import sales_before_gst, won_deals

STAGE_LABELS = {"quoted": "Quote sent", "awaiting_payment": "Waiting for payment", "won": "Paid", "lost": "Lost"}


def top_items(db, tenant_id: str, deal_ids: list[str], limit: int = 10) -> tuple[list[dict], int]:
    items: dict[str, dict] = {}
    qty_total = 0
    for part in chunks(deal_ids):
        for line in paged(lambda part=part: db.table("deal_items").select("id,deal_id,name,qty,line_total_paise")
                          .eq("tenant_id", tenant_id).in_("deal_id", part)):
            row = items.setdefault(line["name"], {"name": line["name"], "qty": 0, "sales_paise": 0})
            row["qty"] += int(line.get("qty") or 0)
            row["sales_paise"] += int(line.get("line_total_paise") or 0)
            qty_total += int(line.get("qty") or 0)
    ranked = sorted(items.values(), key=lambda i: (-i["sales_paise"], -i["qty"], i["name"]))
    return ranked[:limit], qty_total


def low_stock(db, tenant_id: str) -> list[dict]:
    from app.services.deals_reports import _low_stock
    rows = safe(lambda: _low_stock(db, tenant_id), [], "low stock")
    return [{"name": r["name"], "left": int(r["stock_quantity"]) - int(r.get("held_quantity") or 0)} for r in rows]


def orders_by_stage(db, tenant_id: str, period: Period, won: list[dict]) -> list[dict]:
    open_rows = paged(lambda: db.table("deals").select("id,stage,total_paise").eq("tenant_id", tenant_id)
                      .in_("stage", ["quoted", "awaiting_payment"]))
    lost = paged(lambda: db.table("deals").select("id,total_paise").eq("tenant_id", tenant_id).eq("stage", "lost")
                 .gte("lost_at", period.start_iso).lt("lost_at", period.end_iso))
    out = []
    for stage in ("quoted", "awaiting_payment"):
        mine = [r for r in open_rows if r["stage"] == stage]
        out.append({"stage": stage, "label": STAGE_LABELS[stage], "count": len(mine),
                    "total_paise": sum(int(r.get("total_paise") or 0) for r in mine)})
    out.append({"stage": "won", "label": STAGE_LABELS["won"], "count": len(won),
                "total_paise": sum(int(d.get("total_paise") or 0) for d in won)})
    out.append({"stage": "lost", "label": STAGE_LABELS["lost"], "count": len(lost),
                "total_paise": sum(int(r.get("total_paise") or 0) for r in lost)})
    return out


def compute(db, tenant_id: str, period: Period, flags: Flags) -> tuple[dict, dict]:
    won = won_deals(db, tenant_id, period)
    top, items_sold = top_items(db, tenant_id, [d["id"] for d in won])
    stages = orders_by_stage(db, tenant_id, period, won)
    numbers = {"orders": len(won), "items_sold": items_sold, "sales_paise": sum(sales_before_gst(d) for d in won),
               "orders_lost": next(s["count"] for s in stages if s["stage"] == "lost")}
    return numbers, {"top_items": top, "low_stock": low_stock(db, tenant_id), "orders_by_stage": stages}


def in_short(numbers: dict, before: dict | None) -> str:
    parts = []
    if numbers.get("orders"):
        text = f"{plural(numbers['orders'], 'order')} paid"
        if numbers.get("sales_paise"):
            text += f", {money(numbers['sales_paise'])}"
        parts.append(text)
    if numbers.get("items_sold"):
        parts.append(f"{plural(numbers['items_sold'], 'item')} sold")
    return sentence(parts, "No paid orders in these days.")
