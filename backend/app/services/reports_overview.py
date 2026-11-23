"""Reports > Overview: the target bar, up to 3 things to do, six number cards, and the "chats not marked" pill.

Cards depend on what the business uses: orders -> sales and paid; calls -> calls; ads -> cost per chat;
bookings -> bookings; always chats, hot and new customers. Things to do are picked by rule from real
counts (the three biggest, zeros skipped); no AI is involved.
"""
from datetime import datetime, timedelta, timezone

from app.services.reports_common import Flags, Period, build_report, chunks, count_phrase, finish, money, paged, plural, safe, sentence
from app.services import reports_money
from app.services.reports_data import (
    booking_count, buyers_split, call_numbers, is_hot, modules_in_use, new_chats, won_deals, sales_before_gst,
)

UNHAPPY_MAX = 3  # same line as services/customer_feedback.UNHAPPY_MAX


def compute(db, tenant_id: str, period: Period, flags: Flags) -> tuple[dict, dict]:
    chats = new_chats(db, tenant_id, period)
    deals = won_deals(db, tenant_id, period)
    split = buyers_split(db, tenant_id, period, deals)
    numbers: dict = {
        "first_chats": len(chats), "hot": sum(1 for c in chats if is_hot(c)),
        "orders": len(deals), "paid": len(split["buyer_ids"]), "new_buyers": len(split["new_ids"]),
        "sales_paise": sum(sales_before_gst(d) for d in deals),
    }
    calls = safe(lambda: call_numbers(db, tenant_id, period), None, "calls")
    if calls:
        numbers["calls"] = calls["calls"]
        numbers["connected_calls"] = calls["connected_calls"]
    bookings = booking_count(db, tenant_id, period)
    if bookings is not None:
        numbers["bookings"] = bookings
    if flags.sees_money:
        from app.services import reports_ads
        ad, _ = safe(lambda: reports_ads.compute(db, tenant_id, period, flags), ({}, {}), "ads")
        if ad.get("spend_paise"):
            numbers["ad_spend_paise"] = ad["spend_paise"]
            numbers["cost_per_chat_paise"] = ad.get("cost_per_chat_paise")
    if flags.sees_profit:  # purchases.view AND deals.view: the Reports > Money formula, so both pages agree
        got = safe(lambda: reports_money.profit_for(db, tenant_id, period, numbers["sales_paise"]), None, "profit")
        if got is not None:
            numbers["profit_paise"] = got
    return numbers, {}


# ── the cards ─────────────────────────────────────────────────────────────────

def _card(key: str, label: str, numbers: dict, before: dict | None, kind: str = "count", **extra) -> dict | None:
    if key not in numbers:
        return None
    card = {"key": key, "label": label, "value": numbers.get(key), "kind": kind, **extra}
    if before is not None:
        card["before"] = before.get(key)
    return card


def build_cards(numbers: dict, before: dict | None, modules: dict, flags: Flags) -> list[dict]:
    """Six cards by what the business uses (fewer when it uses little)."""
    wanted: list[dict | None] = []
    if modules.get("orders") and flags.sees_money:
        wanted.append(_card("sales_paise", "Sales", numbers, before, "paise", href="/dashboard/analytics?tab=money"))
    if modules.get("orders") and flags.sees_profit:
        # An estimate: sales less refunds, the catalogue cost price of what sold, and expenses.
        wanted.append(_card("profit_paise", "Estimated profit", numbers, before, "paise", href="/dashboard/analytics?tab=money", estimate=True))
    if modules.get("orders"):
        wanted.append(_card("paid", "People who paid", numbers, before, people={"metric": "paid"}))
    wanted.append(_card("first_chats", "New chats", numbers, before, people={"metric": "new_chats"}))
    wanted.append(_card("hot", "Hot chats", numbers, before, people={"metric": "hot"}))
    if modules.get("calls"):
        wanted.append(_card("calls", "Calls made", numbers, before))
    if modules.get("ads") and flags.sees_money:
        wanted.append(_card("cost_per_chat_paise", "Ad cost per chat", numbers, before, "paise", href="/dashboard/analytics?tab=ads"))
    if modules.get("bookings"):
        wanted.append(_card("bookings", "Bookings", numbers, before, href="/dashboard/bookings"))
    wanted.append(_card("new_buyers", "New customers", numbers, before, people={"metric": "bought_new"}))
    cards = [c for c in wanted if c]
    return cards[:7] if any(c["key"] == "profit_paise" for c in cards) else cards[:6]


# ── things to do (as of now) ──────────────────────────────────────────────────

def hot_not_called(db, tenant_id: str, now: datetime) -> int:
    hot = paged(lambda: db.table("leads").select("id").eq("tenant_id", tenant_id).is_("deleted_at", "null")
                .eq("segment", "A").is_("converted_at", "null").is_("lost_at", "null"))
    if not hot:
        return 0
    since = (now - timedelta(hours=24)).isoformat()
    called: set[str] = set()
    for part in chunks([h["id"] for h in hot]):
        called |= {r["lead_id"] for r in paged(lambda part=part: db.table("call_logs").select("id,lead_id")
                                                .eq("tenant_id", tenant_id).in_("lead_id", part).gte("created_at", since))
                   if r.get("lead_id")}
    return sum(1 for h in hot if h["id"] not in called)


def waiting_for_payment(db, tenant_id: str) -> tuple[int, int]:
    rows = paged(lambda: db.table("deals").select("id,total_paise,paid_paise").eq("tenant_id", tenant_id).eq("stage", "awaiting_payment"))
    return len(rows), sum(max(int(r.get("total_paise") or 0) - int(r.get("paid_paise") or 0), 0) for r in rows)


def unhappy_open(db, tenant_id: str) -> int:
    return len(paged(lambda: db.table("customer_feedback").select("id").eq("tenant_id", tenant_id)
                     .eq("status", "answered").lte("stars", UNHAPPY_MAX)))


def unmarked_lead_ids(db, tenant_id: str, period: Period) -> list[str]:
    """New chats of the days with no result step yet (not paid, lost or booked; no paid order)."""
    chats = [c for c in new_chats(db, tenant_id, period)
             if not (c.get("converted_at") or c.get("lost_at") or c.get("booked_at"))]
    if not chats:
        return []
    paid: set[str] = set()
    for part in chunks([c["id"] for c in chats]):
        paid |= {r["lead_id"] for r in paged(lambda part=part: db.table("deals").select("id,lead_id")
                                              .eq("tenant_id", tenant_id).eq("stage", "won").in_("lead_id", part))
                 if r.get("lead_id")}
    return [c["id"] for c in chats if c["id"] not in paid]


def todo_items(db, tenant_id: str, flags: Flags, now: datetime) -> list[dict]:
    from app.services import reports_items
    candidates: list[dict] = []
    n = safe(lambda: hot_not_called(db, tenant_id, now), 0, "hot chats")
    if n:
        candidates.append({"text": f"{plural(n, 'hot chat')} not called in the last 24 hours", "count": n, "href": "/dashboard/telecalling"})
    count, left = safe(lambda: waiting_for_payment(db, tenant_id), (0, 0), "orders waiting")
    if count:
        text = f"{plural(count, 'order')} waiting for payment"
        if flags.sees_money and left:
            text += f", {money(left)} to collect"
        candidates.append({"text": text, "count": count, "href": "/dashboard/deals"})
    low = safe(lambda: reports_items.low_stock(db, tenant_id), [], "low stock")
    if low:
        candidates.append({"text": f"{plural(len(low), 'item')} running low", "count": len(low), "href": "/dashboard/catalog"})
    unhappy = safe(lambda: unhappy_open(db, tenant_id), 0, "unhappy feedback")
    if unhappy:
        candidates.append({"text": f"{plural(unhappy, 'unhappy customer')} still to sort out", "count": unhappy, "href": "/dashboard/leads?tab=feedback"})
    return sorted(candidates, key=lambda c: -c["count"])[:3]


def _profit_this_month(db, tenant_id: str, period: Period, numbers: dict, now: datetime) -> dict | None:
    """The estimated profit of this IST month so far, next to the target (same formula as Home's profit box).
    When the picked days already are the 1st to today, the figure computed for them is reused."""
    from app.services.reports_common import IST, resolve_period
    today = now.astimezone(IST).date()
    first = today.replace(day=1)
    if period.start == first and period.end == today and numbers.get("profit_paise") is not None:
        profit = int(numbers["profit_paise"])
    else:
        month = resolve_period(first.isoformat(), today.isoformat())
        sales = sum(sales_before_gst(d) for d in won_deals(db, tenant_id, month))
        profit = reports_money.profit_for(db, tenant_id, month, sales)
    return {"profit_paise": profit, "month": today.strftime("%Y-%m")}


def report(db, tenant_id: str, period: Period, compare: bool, flags: Flags, now: datetime | None = None) -> dict:
    from app.services import sales_target
    now = now or datetime.now(timezone.utc)
    payload = build_report(compute, db, tenant_id, period, compare, flags)
    modules = modules_in_use(db, tenant_id)
    payload["cards"] = build_cards(payload["period"], payload["before"], modules, flags)
    payload["todo"] = todo_items(db, tenant_id, flags, now)
    payload["target"] = safe(lambda: sales_target.overview(db, tenant_id, now, sees_money=flags.sees_money), None, "target")
    if payload["target"]:  # the page needs only this month and the cost-price count
        payload["target"] = {"this_month": payload["target"]["this_month"], "cost_coverage": payload["target"].get("cost_coverage")}
        if flags.sees_profit:
            payload["target"]["profit_this_month"] = safe(lambda: _profit_this_month(db, tenant_id, period, payload["period"], now), None, "month profit")
    unmarked = safe(lambda: len(unmarked_lead_ids(db, tenant_id, period)), 0, "unmarked chats")
    payload["unmarked_chats"] = {"count": unmarked, "href": "/dashboard/inbound-leads?result=none"}
    payload["period"]["unmarked_chats"] = unmarked
    payload = finish(payload, flags)
    payload["in_short"] = in_short(payload["period"], payload["before"])
    return payload


def in_short(numbers: dict, before: dict | None) -> str:
    b = before or {}
    parts = [count_phrase(numbers.get("first_chats"), b.get("first_chats"), "new chat")]
    if numbers.get("paid"):
        text = f"{plural(numbers['paid'], 'person', 'people')} paid"
        if numbers.get("sales_paise"):
            text += f", {money(numbers['sales_paise'])}"
        parts.append(text)
    return sentence(parts, "No new chats in these days.")
