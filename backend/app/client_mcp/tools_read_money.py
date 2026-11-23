"""Ask tools: reports, Meta Ads, orders and payments, purchases. Read-only.

Most of these call the same read the matching Anril page calls, with the client fixed by the
sign-in (wrapper.tenant_id) instead of coming from an argument. Route handlers are called with
EVERY parameter by keyword (a parameter left out would arrive as a Depends(...) / Query(...)
object); the analytics handlers are async, so each runs inside asyncio.run in this worker thread.

Money: every amount ending in _paise is paise (100 paise = 1 rupee). Reports amounts called
spend / cost per lead are rupees, as the Reports page stores them.

Nothing here writes, sends, enqueues or makes a file. Answers are built so no key, token,
payment link or bill link can appear in them (see _clean).
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp.tools_client import _check_days
from app.client_mcp.wrapper import client_tool, tenant_id
from app.db.supabase import ReadOnlyViolation, get_supabase
from app.routes import analytics, instant_forms
from app.services import day_closing, growth, payments_overview as payments_page, purchases
from app.services import sales_target as sales_target_service
from app.services import google_ads_report
from app.services import orders as orders_service
from app.services.analytics_compare import PRESETS

logger = logging.getLogger(__name__)

MAX_PAGE = 50
_IST = timezone(timedelta(hours=5, minutes=30))
# A key that holds a secret, a signed link, a payment link or a bill link is dropped from rows
# that come straight from a table (select "*").
_SECRET_KEY = re.compile(
    r"(token|secret|password|signature|api_?key|authorization|signed|(^|_)url($|_)|storage_path"
    r"|payment_link|access_key|bill_link)",
    re.I,
)


def _clean(value):
    """The same data without any key that could hold a secret or a link that works as one."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not _SECRET_KEY.search(str(k))}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _run(coroutine):
    """Run an async route handler to the end. This runs in a worker thread (no loop is running)."""
    return asyncio.run(coroutine)


def _limit(limit: int) -> int:
    if not 1 <= limit <= MAX_PAGE:
        raise ToolError(f"limit must be between 1 and {MAX_PAGE}.")
    return limit


def _today_ist():
    return datetime.now(timezone.utc).astimezone(_IST).date()


def _window(days: int) -> tuple[str, str]:
    """The last `days` Indian days, today included, as 2026-11-01 dates (start, end)."""
    _check_days(days)
    end = _today_ist()
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


def _both_or_neither(from_date: str, to_date: str, max_days: int = 92) -> tuple[str | None, str | None]:
    start, end = (from_date or "").strip(), (to_date or "").strip()
    if bool(start) != bool(end):
        raise ToolError("Give both from_date and to_date (2026-11-01), or neither.")
    if start:
        try:
            first, last = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
        except ValueError:
            raise ToolError("Dates must look like 2026-11-01.")
        if last < first:
            raise ToolError("to_date is before from_date.")
        if (last - first).days >= max_days:
            raise ToolError(f"Ask for at most {max_days} days at a time.")
    return (start or None, end or None)


def _cap(rows: list, limit: int = MAX_PAGE) -> dict:
    return {"rows": rows[:limit], "total": len(rows), "more": len(rows) > limit}


def _part(name: str, fn):
    """One part of a combined answer. A part that fails on its own says so; the rest still answer."""
    try:
        return fn()
    except ReadOnlyViolation:
        raise
    except ToolError:
        raise
    except Exception as exc:
        logger.warning("client mcp money tool: %s unavailable: %s", name, exc)
        return {"unavailable": True, "note": f"{name} could not be loaded right now."}


# ── reports ──────────────────────────────────────────────────────────────────

@client_tool(title="Reports overview")
def reports_overview(days: int = 30) -> dict:
    """The Reports overview: new leads per day, messages per day (inbound, outbound, AI, human),
    segments, channels, the lead funnel, response times, converted leads and ad spend. Reports
    keeps three windows, so days 1 is today, 2 to 7 is the last 7 days and 8 or more is the last
    30 days (at most 366 is accepted); `range_used` says which one answered. For a longer or
    exact period use reports_compare. Ad spend and cost per lead are in rupees."""
    _check_days(days)
    window = "today" if days <= 1 else "7d" if days <= 7 else "30d"
    data = _run(analytics.overview_analytics(tenant_id=tenant_id(), range=window))
    out = {"range_used": window, **data}
    if days not in (1, 7, 30):
        out["note"] = f"Reports shows today, 7 days or 30 days only, so {window} was used for days={days}."
    return out


@client_tool(title="Lead funnel")
def reports_funnel() -> dict:
    """The lead funnel across all time: total leads, leads by segment (A hot to D not interested)
    and by source, leads this week, average score, and how long hot leads have been waiting."""
    return _run(analytics.funnel_analytics(tenant_id=tenant_id()))


@client_tool(title="Compare two periods")
def reports_compare(preset: str = "last_7d", compare_to_previous: bool = True,
                    start: str = "", end: str = "") -> dict:
    """One period of the Reports compare page, with the change against the period before it.
    preset is one of today, yesterday, this_week, last_week, this_month, last_month, last_7d,
    last_14d, last_30d or custom (custom needs start and end as 2026-11-01, Indian days).
    compare_to_previous false returns the period alone. Ad spend is in rupees."""
    if preset not in PRESETS:
        raise ToolError("preset must be one of: " + ", ".join(PRESETS) + ".")
    if preset == "custom" and not (start.strip() and end.strip()):
        raise ToolError("custom needs both start and end (2026-11-01).")
    return _run(analytics.compare_analytics(
        preset=preset, start=start.strip() or None, end=end.strip() or None,
        comparison="previous" if compare_to_previous else "off",
        comparison_start=None, comparison_end=None, tenant_id=tenant_id(),
    ))


@client_tool(title="Template performance")
def reports_templates(days: int = 30) -> dict:
    """How each WhatsApp broadcast template did over the last `days` Indian days (default 30,
    at most 366): sent, read, replied and hot leads. At most 50 templates are returned."""
    start, end = _window(days)
    data = _run(analytics.template_performance(
        range="7d", start=start, end=end, calendar_timezone="Asia/Kolkata", tenant_id=tenant_id(),
    ))
    return {"from": start, "to": end, **_cap(data.get("data") or [])}


@client_tool(title="Telecalling report")
def reports_telecalling(from_date: str = "", to_date: str = "") -> dict:
    """The Reports telecalling page: calls, connect rate, outcomes, talk and idle time and each
    telecaller's numbers (the owner's own calls are left out, as in Anril). Give from_date and
    to_date as 2026-11-01 (Indian days, at most 92 days) or neither for today."""
    start, end = _both_or_neither(from_date, to_date)
    ctx = {"tenant_id": tenant_id(), "role": "owner", "permissions": []}  # the owner sees every team
    return _run(analytics.telecalling_analytics(from_date=start, to_date=end, ctx=ctx))


# ── ads ──────────────────────────────────────────────────────────────────────

@client_tool(title="Meta and Google ads")
def meta_ads(days: int = 30, month: str = "") -> dict:
    """How ads are doing: leads and budget advice per campaign (ad_performance, spend in rupees),
    new inbound leads organic versus ad (the last `days` Indian days, default 30, at most 92),
    Google Ads campaigns for one month (month as 2026-11, default this month; amounts in paise),
    and Meta instant forms (form leads, template sent, replied) over the same `days`. Live Meta
    spend is not included. Each part says so if it could not be loaded."""
    if days > 92:
        raise ToolError("days can be at most 92 for ads.")
    start, end = _window(days)
    tenant = tenant_id()
    try:
        month_key = google_ads_report.parse_month(month or None)
    except google_ads_report.ReportError as exc:
        raise ToolError(str(exc))

    def campaigns() -> dict:
        data = growth.build_ad_performance(tenant_id=tenant, db=get_supabase())
        rows = data.get("campaigns") or []
        return {"totals": data.get("totals"), "campaigns": rows[:MAX_PAGE], "more": len(rows) > MAX_PAGE}

    def inbound() -> dict:
        return _run(analytics.inbound_analytics(
            range="7d", start=start, end=end, calendar_timezone="Asia/Kolkata", tenant_id=tenant,
        ))

    def google() -> dict:
        data = google_ads_report.campaign_rows(get_supabase(), tenant, month_key, show_money=True)
        return {**data, "rows": (data.get("rows") or [])[:MAX_PAGE]}

    def forms() -> dict:
        return _instant_forms(tenant, start, end)

    return {
        "ad_performance": _part("Ad performance", campaigns),
        "inbound_leads": _part("Inbound leads", inbound),
        "google_ads": _part("Google Ads", google),
        "instant_forms": _part("Instant forms", forms),
        "window": {"from": start, "to": end, "google_month": month_key},
    }


def _instant_forms(tenant: str, date_from: str, date_to: str) -> dict:
    """The Instant forms overview without its two live calls to Meta (ad names and spend)."""
    db = get_supabase()
    _, _, lo, hi = instant_forms._range(date_from, date_to)
    forms = (
        db.table("meta_lead_forms").select("form_id,name,status,meta_created_at,template_id,questions")
        .eq("tenant_id", tenant).order("meta_created_at", desc=True).limit(200).execute()
    ).data or []
    rows = instant_forms._rows_in_range(db, tenant, lo, hi)
    replied = instant_forms._replied_lead_ids(db, tenant, rows)
    by_form: dict[str, list[dict]] = {}
    for row in rows:
        by_form.setdefault(row["form_id"], []).append(row)
    listed = [
        {
            "form_id": f["form_id"], "name": f.get("name") or "Untitled form", "status": f.get("status"),
            "created_at": f.get("meta_created_at"), "questions": len(f.get("questions") or []),
            **{k: v for k, v in instant_forms._stats(by_form.get(f["form_id"], []), replied, None).items()
               if k not in ("spend", "cost_per_lead")},
        }
        for f in forms
    ]
    totals = {k: v for k, v in instant_forms._stats(rows, replied, None).items() if k not in ("spend", "cost_per_lead")}
    return {"from": date_from, "to": date_to, "totals": totals, **{"forms": listed[:MAX_PAGE], "more": len(listed) > MAX_PAGE}}


# ── orders and money ─────────────────────────────────────────────────────────

@client_tool(title="Orders")
def orders(status: str = "", limit: int = 50, days: int = 30) -> dict:
    """Orders created in the last `days` days (default 30, at most 366), newest first, with the
    money cards (money in, to collect, to pack, GST), the count in each status, today's day
    closing and the order settings. status filters the list: waiting (nothing paid), advance
    (part paid), paid, pack (to pack), quote, cancelled; empty means all. limit is at most 50.
    All amounts are in paise (100 paise = 1 rupee). Each row has the `id` order_details needs."""
    _limit(limit)
    _check_days(days)
    chip = (status or "all").strip().lower()
    if chip not in orders_service.CHIPS:
        raise ToolError("status must be one of: " + ", ".join(orders_service.CHIPS) + " (or empty for all).")
    db, tenant = get_supabase(), tenant_id()
    page = orders_service.list_orders(db, tenant, chip=chip, channel=None, days=days, q=None)
    rows = page.get("data") or []
    return {
        "orders": rows[:limit], "shown": min(len(rows), limit), "matching": len(rows), "more": len(rows) > limit,
        "counts": page.get("counts"), "cards": page.get("cards"),
        "day_closing_today": _clean(_part("Day closing", lambda: day_closing.summary(db, tenant, day_closing.parse_day(None)))),
        "settings": _part("Order settings", lambda: orders_service.order_settings(tenant)),
    }


@client_tool(title="One order")
def order_details(order_id: str) -> dict:
    """One order: customer, items, what was paid and refunded, the balance and delivery state.
    order_id is the `id` from the orders tool. Amounts are in paise. Bill and payment links are
    never shown."""
    try:
        deal_id = str(uuid.UUID(str(order_id).strip()))
    except ValueError:
        raise ToolError("No order with that id in your account.")
    db, tenant = get_supabase(), tenant_id()
    res = db.table("deals").select("*").eq("id", deal_id).eq("tenant_id", tenant).maybe_single().execute()
    deal = res.data if res else None
    if not deal:
        raise ToolError("No order with that id in your account.")
    items = (
        db.table("deal_items")
        .select("id, name, qty, variant_label, unit_price_paise, gst_rate, line_total_paise")
        .eq("deal_id", deal_id).eq("tenant_id", tenant).order("created_at").limit(200).execute()
    ).data or []
    payments = (
        db.table("deal_payments").select("id, amount_paise, method, kind, paid_at, note")
        .eq("deal_id", deal_id).eq("tenant_id", tenant).order("paid_at").limit(200).execute()
    ).data or []
    refunds = (
        db.table("deal_refunds").select("id, amount_paise, method, reason, status, credit_note_number, created_at")
        .eq("deal_id", deal_id).eq("tenant_id", tenant).order("created_at").limit(200).execute()
    ).data or []
    lead = {}
    if deal.get("lead_id"):
        found = (
            db.table("leads").select("id, name, phone, source, segment")
            .eq("id", deal["lead_id"]).eq("tenant_id", tenant).maybe_single().execute()
        )
        lead = (found.data if found else None) or {}
    summary = orders_service.order_row({**deal, "leads": lead, "deal_items": items, "deal_payments": payments})
    keep = ("stage", "source", "discount_paise", "gst_paise", "bill_type", "notes", "ready_by", "ready_at",
            "shipped_at", "delivered_at", "won_at", "lost_reason", "invoice_issued_at", "advance_paise")
    return _clean({
        **summary,
        **{k: deal.get(k) for k in keep},
        "items_full": items,
        "payments": payments,
        "refunds": refunds,
        "customer_segment": lead.get("segment"),
    })


@client_tool(title="Purchase orders")
def purchase_orders(limit: int = 50) -> dict:
    """Purchases: your purchase orders to suppliers (newest first, with status, what is open and
    late and what to reorder), the items suggested for reordering, and the latest stock-in
    bills. limit (at most 50) caps each list. Amounts are in paise."""
    _limit(limit)
    db, tenant = get_supabase(), tenant_id()
    view = purchases.pos_view(db, tenant)
    orders_list = view.get("orders") or []
    suggestions = purchases.suggestions(db, tenant)
    bills = purchases.stock_in_history(db, tenant, limit=limit)
    return _clean({
        "summary": {k: v for k, v in view.items() if k != "orders"},
        "purchase_orders": orders_list[:limit], "purchase_orders_total": len(orders_list),
        "reorder_suggestions": suggestions[:limit], "reorder_total": len(suggestions),
        "stock_in_latest": bills[:limit],
    })


@client_tool(title="Suppliers")
def suppliers() -> dict:
    """Your suppliers with what you bought from each this month, what you owe each, the next due
    date and how many days overdue, plus the totals and how many items are low on stock. Up to
    50 suppliers. Amounts are in paise."""
    db, tenant = get_supabase(), tenant_id()
    view = purchases.suppliers_view(db, tenant)
    rows = [
        {k: s.get(k) for k in ("id", "name", "phone", "city", "gstin", "supplies", "bought_this_month_paise",
                               "owe_paise", "due_date", "overdue_days")}
        for s in view.get("suppliers") or []
    ]
    return {
        "suppliers": rows[:MAX_PAGE], "suppliers_total": len(rows), "more": len(rows) > MAX_PAGE,
        "totals": {k: v for k, v in view.items() if k != "suppliers"},
        "low_stock": len(purchases.suggestions(db, tenant)),
    }


@client_tool(title="Payments")
def payments_overview() -> dict:
    """Money received and still to collect, as My business shows it: the last 30 days' money in
    (after refunds), what customers still owe, the 20 newest payments, who may refund, when
    balance reminders go out and which ways of paying are ready (Razorpay connected or not).
    Amounts are in paise."""
    db, tenant = get_supabase(), tenant_id()
    page = payments_page.overview(db, tenant)
    cards = orders_service.list_orders(db, tenant, chip="all", channel=None, days=30, q=None).get("cards") or {}
    recent = (
        db.table("deal_payments").select("id, deal_id, amount_paise, method, kind, paid_at")
        .eq("tenant_id", tenant).order("paid_at", desc=True).limit(20).execute()
    ).data or []
    deal_ids = sorted({p["deal_id"] for p in recent if p.get("deal_id")})
    numbers = {}
    if deal_ids:
        numbers = {
            d["id"]: orders_service.order_label(d)
            for d in (db.table("deals").select("id, deal_number").eq("tenant_id", tenant).in_("id", deal_ids).execute()).data or []
        }
    return _clean({
        "last_30_days": {"money_in": cards.get("money_in"), "to_collect": cards.get("to_collect")},
        "recent_payments": [
            {**{k: p.get(k) for k in ("id", "amount_paise", "method", "kind", "paid_at")},
             "order": numbers.get(p.get("deal_id")), "order_id": p.get("deal_id")}
            for p in recent
        ],
        "refund_who": page.get("refund_who"),
        "balance_reminders": page.get("balance_reminders"),
        "ways_to_pay": page.get("ways_to_pay"),
    })


@client_tool(title="Sales target")
def sales_target() -> dict:
    """The monthly sales target and progress from My business: the target for this month, money in
    so far and the percent reached, a suggested target from the last 3 months, those 3 months'
    money in, and whether the target is shown to the team. Amounts are in paise."""
    # The owner sees money, so sees_money is True.
    return _clean(sales_target_service.overview(get_supabase(), tenant_id(), sees_money=True))
