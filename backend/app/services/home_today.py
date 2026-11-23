"""Home (Today): the numbers behind the boxes and lists on the dashboard's first screen.

Every number comes from the same code the linked page uses, so Home never disagrees with it:
  money_in_today / to_collect / orders_pending -> services/orders._cards (Orders & payments cards)
  new_enquiries_today / won_month              -> routes/inbound_leads._count (Inbound leads page)
  hot_waiting / waiting list / hot bar         -> SQL get_inbox_chats + get_inbox_counts (Chats)
  callbacks_today                              -> follow_up_jobs, cadence callback (Scheduled calls)
  ads_today                                    -> services/growth.build_ad_performance (Ad Spend card)
  quotes_open                                  -> services/order_quotes._expired (quote rules)
  low_stock                                    -> catalogue stock rules (catalog/money.ts isLow)
  bookings_today / todays_bookings             -> services/bookings (live bookings today, IST, the person's own columns)
  target_month                                 -> services/sales_target (Settings > Target & profit)
  profit_month                                 -> services/reports_money.compute (Reports > Money, this month so far)
  expenses_today                               -> cash_expenses rows of today (Expenses page)
  feedback_week / todays_feedback              -> customer_feedback rows (Customers > Feedback)

Each source runs on its own: one that fails is logged and left out, never a 500.
Who sees what: _has_permission AND "the client uses it" (see _gates).
"""
import logging
import time
from datetime import datetime, timedelta, timezone

from app.dependencies.tenant import _has_permission

logger = logging.getLogger(__name__)

# The only working boxes, in DEFAULT PRIORITY ORDER.
BOX_KEYS = (
    "money_in_today", "new_enquiries_today", "hot_waiting", "to_collect", "callbacks_today",
    "orders_pending", "ads_today", "quotes_open", "won_month", "target_month", "bookings_today", "low_stock",
    "profit_month", "expenses_today", "feedback_week",
)
LIST_KEYS = ("waiting", "low_stock", "todays_bookings", "todays_feedback")
MAX_BOXES = 12
DEFAULT_COUNT = 6

HREF = {
    "money_in_today": "/dashboard/deals", "to_collect": "/dashboard/deals",
    "orders_pending": "/dashboard/deals", "quotes_open": "/dashboard/deals",
    "new_enquiries_today": "/dashboard/inbound-leads", "won_month": "/dashboard/inbound-leads",
    "hot_waiting": "/dashboard/conversations", "callbacks_today": "/dashboard/telecalling/scheduled",
    "ads_today": "/dashboard/meta-ads", "low_stock": "/dashboard/catalog",
    "target_month": "/dashboard/settings/target", "bookings_today": "/dashboard/bookings",
    "profit_month": "/dashboard/analytics?tab=money", "expenses_today": "/dashboard/expenses",
    "feedback_week": "/dashboard/leads?tab=feedback",
}

_FAILED = object()


def _safe(name: str, fn, default=_FAILED):
    """Run one source; a failure is logged and becomes `default`."""
    try:
        return fn()
    except Exception as e:
        logger.warning("home today: %s failed: %s", name, e)
        return default


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


# ───────────────────────────────────────────────────────────── time

def _times(now: datetime) -> dict:
    from app.services.orders import IST
    ist = now.astimezone(IST)
    today = ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "now": now,
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "month": today.replace(day=1),
    }


# ───────────────────────────────────────────────────────────── 7-day series (sparklines)

SERIES_DAYS = 7


def _series_start(t: dict) -> datetime:
    """IST midnight of the oldest of the 7 days (today included as the last one)."""
    return t["today"] - timedelta(days=SERIES_DAYS - 1)


def _day_counts(stamps, t: dict) -> list[int]:
    """7 per-IST-day counts, oldest first, last = today. Stamps outside the 7 days are ignored."""
    from app.services.customer_feedback import _parse
    from app.services.orders import IST
    start = _series_start(t).date()
    out = [0] * SERIES_DAYS
    for ts in stamps:
        moment = _parse(ts)
        if not moment:
            continue
        i = (moment.astimezone(IST).date() - start).days
        if 0 <= i < SERIES_DAYS:
            out[i] += 1
    return out


def _paged_stamps(make_query, column: str) -> list:
    """Every `column` value of a query a page at a time (Supabase caps a response at 1000 rows)."""
    from app.services.sales_target import _paged
    return [r.get(column) for r in _paged(make_query, column)]


# Home polls every 2 min per tab; a sparkline does not need that freshness, so each series is reused for a while.
SERIES_TTL_SECONDS = 600
_SERIES_CACHE: dict[tuple, tuple[float, list[int]]] = {}


def _with_series(box: dict, name: str, fn, tenant_id: str | None = None, day=None) -> dict:
    """Adds box["series"] when it can be worked out; a failure is logged and the box stays as it was."""
    key = (tenant_id, name, str(day)) if tenant_id else None
    hit = _SERIES_CACHE.get(key) if key else None
    if hit and time.monotonic() - hit[0] < SERIES_TTL_SECONDS:
        box["series"] = list(hit[1])
        return box
    got = _safe(name, fn, None)
    if got is not None:
        box["series"] = got
        if key:
            _SERIES_CACHE[key] = (time.monotonic(), list(got))
    return box


def _money_series(db, tenant_id: str, t: dict) -> list[int]:
    """Money in per IST day (payments received less refunds given), the target box's own rule."""
    from app.services.sales_target import money_in_by_day
    by_day = money_in_by_day(db, tenant_id, _series_start(t), t["tomorrow"])
    start = _series_start(t).date()
    return [by_day.get((start + timedelta(days=i)).isoformat(), 0) for i in range(SERIES_DAYS)]


# ───────────────────────────────────────────────────────────── gates (allowed AND used)

def _count_one(db, table: str, tenant_id: str, **eq) -> bool:
    q = db.table(table).select("id").eq("tenant_id", tenant_id)
    for k, v in eq.items():
        q = q.eq(k, v)
    return bool(q.limit(1).execute().data)


def _tenant_features(db, tenant_id: str) -> set:
    rows = db.table("tenants").select("enabled_features").eq("id", tenant_id).limit(1).execute().data or []
    return set((rows[0].get("enabled_features") if rows else None) or [])


def _callbacks_feature_on(features: set) -> bool:
    """Same rule as the Call IQ menu: a client with telecalling sub-features needs the scheduled one;
    a client on the plain SIM / Tele-CMI bundle has every page."""
    if "callbacks" in features or "telecalling.scheduled" in features:
        return True
    if any(f.startswith("telecalling.") for f in features):
        return False
    return "telecalling_sim" in features or "telecalling_telecmi" in features


def _gates(db, ctx: dict, tenant_id: str) -> dict:
    """box key -> True when this person may see it AND the client uses it."""
    gates: dict[str, bool] = {k: False for k in BOX_KEYS}

    if _has_permission(ctx, "deals.view"):
        has_deals = _safe("gate deals", lambda: _count_one(db, "deals", tenant_id), False)
        for k in ("money_in_today", "to_collect", "orders_pending", "quotes_open"):
            gates[k] = bool(has_deals)

    if _has_permission(ctx, "catalog.view"):
        def low_set():
            rows = (
                db.table("catalog_items").select("id").eq("tenant_id", tenant_id)
                .not_.is_("low_stock_at", "null").limit(1).execute().data
            )
            return bool(rows)
        gates["low_stock"] = bool(_safe("gate catalog", low_set, False))

    needs_features = _has_permission(ctx, "inbound_leads.view") or (
        _has_permission(ctx, "telecalling.scheduled.view") or _has_permission(ctx, "telecalling.scheduled")
    )
    features = _safe("gate features", lambda: _tenant_features(db, tenant_id), None) if needs_features else None
    if features is not None:
        if _has_permission(ctx, "inbound_leads.view") and "inbound_messaging" in features:
            gates["new_enquiries_today"] = gates["won_month"] = True
        scheduled_ok = _has_permission(ctx, "telecalling.scheduled.view") or _has_permission(ctx, "telecalling.scheduled")
        if scheduled_ok and _callbacks_feature_on(features):
            gates["callbacks_today"] = True

    if _has_permission(ctx, "bookings.view"):
        # the client uses bookings once it has set up a service people can book
        gates["bookings_today"] = bool(_safe(
            "gate bookings", lambda: _count_one(db, "booking_services", tenant_id, active=True), False))

    # Profit: the Reports > Money rule (see orders AND see purchases), and the shop has sold something.
    if _has_permission(ctx, "deals.view") and _has_permission(ctx, "purchases.view"):
        gates["profit_month"] = bool(_safe("gate profit", lambda: _count_one(db, "deals", tenant_id), False))

    # Expenses: the shop has written down at least one expense (a missing table reads as "no").
    if _has_permission(ctx, "purchases.view"):
        gates["expenses_today"] = bool(_safe("gate expenses", lambda: _count_one(db, "cash_expenses", tenant_id), False))

    # Feedback: Customers > Feedback is switched on for this shop.
    if _has_permission(ctx, "leads.view"):
        from app.services import customer_feedback as fb
        gates["feedback_week"] = bool(_safe("gate feedback", lambda: fb.is_on(tenant_id), False))

    if _has_permission(ctx, "conversations.view"):
        gates["hot_waiting"] = True
    # ads_today is gated by analytics.view here; "the client has ad data" is decided when it is computed.
    if _has_permission(ctx, "analytics.view"):
        gates["ads_today"] = True
    return gates


# ───────────────────────────────────────────────────────────── commerce boxes

def _orders_cards(db, tenant_id: str, t: dict) -> dict:
    """The Orders page cards: money in for TODAY (IST), to collect / to pack over the page's own
    default period (last 30 days), so Home equals what Orders & payments shows."""
    from app.services import orders as o
    since_month = o._since(30)
    deals = (
        db.table("deals").select(o.ORDER_SELECT).eq("tenant_id", tenant_id)
        .gte("created_at", since_month.isoformat()).order("created_at", desc=True).limit(1000).execute().data or []
    )
    return o._cards(db, tenant_id, deals, t["today"], None, t["now"])


def _box_money_in(cards: dict) -> dict:
    m = cards["money_in"]
    return {"value": int(m["paise"]), "unit": "paise", "sub": f"{_plural(int(m['orders']), 'order', 'orders')} paid"}


def _box_to_collect(cards: dict) -> dict:
    c = cards["to_collect"]
    return {"value": int(c["paise"]), "unit": "paise", "sub": f"from {_plural(int(c['orders']), 'order', 'orders')}"}


def _box_orders_pending(cards: dict) -> dict:
    p = cards["to_pack"]
    late = int(p.get("over_2_days") or 0)
    return {"value": int(p["orders"]), "unit": "count", "sub": f"{late} over 2 days" if late else "to pack or ship"}


def _box_quotes_open(db, tenant_id: str, t: dict) -> dict:
    """Quotes sent, not accepted (stage quoted) and not past their valid-till day."""
    from app.services.deals import _rupees
    from app.services.order_quotes import _expired
    rows = (
        db.table("deals").select("id, total_paise, quote_valid_until").eq("tenant_id", tenant_id)
        .eq("stage", "quoted").not_.is_("quote_sent_at", "null").limit(1000).execute().data or []
    )
    live = [r for r in rows if not _expired(r)]
    worth = sum(int(r.get("total_paise") or 0) for r in live)
    return {"value": len(live), "unit": "count", "sub": f"worth {_rupees(worth)}" if live else "none waiting"}


# ───────────────────────────────────────────────────────────── leads boxes

def _inbound_counts(db, tenant_id: str, t: dict) -> tuple[int, int]:
    """(new today, of them Hot): the Inbound leads page's own filters, created since IST midnight."""
    from app.routes.inbound_leads import InboundFilters, _count
    since = t["today"].isoformat()
    return (
        _count(db, tenant_id, InboundFilters(date_from=since)),
        _count(db, tenant_id, InboundFilters(date_from=since, segment="A")),
    )


def _new_enquiries_series(db, tenant_id: str, t: dict) -> list[int]:
    """The same filters as today's count, one IST day each for the last 7 days."""
    from app.routes.inbound_leads import InboundFilters, _leads_query
    since = _series_start(t).isoformat()
    stamps = _paged_stamps(
        lambda: _leads_query(db, "id, created_at", tenant_id, InboundFilters(date_from=since)), "created_at")
    return _day_counts(stamps, t)


def _box_new_enquiries(db, tenant_id: str, t: dict) -> dict:
    total, hot = _inbound_counts(db, tenant_id, t)
    box = {"value": total, "unit": "count", "sub": f"{hot} Hot"}
    return _with_series(box, "new enquiries series", lambda: _new_enquiries_series(db, tenant_id, t), tenant_id, t["today"])


def _box_won_month(db, tenant_id: str, t: dict) -> dict:
    """Inbound leads marked converted (bought) since the 1st, IST."""
    from app.routes.inbound_leads import InboundFilters, _leads_query
    res = (
        _leads_query(db, "id", tenant_id, InboundFilters(), count="exact")
        .gte("converted_at", t["month"].isoformat()).limit(1).execute()
    )
    box = {"value": res.count or 0, "unit": "count", "sub": "bought this month"}
    return _with_series(box, "won series", lambda: _won_series(db, tenant_id, t), tenant_id, t["today"])


def _won_series(db, tenant_id: str, t: dict) -> list[int]:
    """Leads marked converted on each of the last 7 IST days (a daily count, not month to date)."""
    from app.routes.inbound_leads import InboundFilters, _leads_query
    since = _series_start(t).isoformat()
    stamps = _paged_stamps(
        lambda: _leads_query(db, "id, converted_at", tenant_id, InboundFilters()).gte("converted_at", since),
        "converted_at")
    return _day_counts(stamps, t)


def _box_callbacks(db, tenant_id: str, t: dict) -> dict:
    """Pending call-backs due today, IST (the Scheduled calls board's rows)."""
    res = (
        db.table("follow_up_jobs").select("id", count="exact").eq("tenant_id", tenant_id)
        .eq("cadence", "callback").eq("status", "pending")
        .gte("scheduled_for", t["today"].isoformat()).lt("scheduled_for", t["tomorrow"].isoformat())
        .limit(1).execute()
    )
    box = {"value": res.count or 0, "unit": "count", "sub": "calls to make today"}
    return _with_series(box, "callbacks series", lambda: _callbacks_series(db, tenant_id, t), tenant_id, t["today"])


def _callbacks_series(db, tenant_id: str, t: dict) -> list[int]:
    """Call-backs scheduled for each of the last 7 IST days, any status (pending or done)."""
    stamps = _paged_stamps(
        lambda: (
            db.table("follow_up_jobs").select("id, scheduled_for").eq("tenant_id", tenant_id)
            .eq("cadence", "callback")
            .gte("scheduled_for", _series_start(t).isoformat()).lt("scheduled_for", t["tomorrow"].isoformat())
        ),
        "scheduled_for")
    return _day_counts(stamps, t)


def _box_ads(db, tenant_id: str) -> dict | None:
    """Same numbers as the Ad Spend card. None when no ad campaign is connected."""
    from app.services.growth import build_ad_performance
    totals = build_ad_performance(tenant_id=tenant_id, db=db).get("totals") or {}
    campaigns = int(totals.get("campaigns") or 0)
    if campaigns <= 0:
        return None
    return {"value": int(totals.get("tracked_leads_today") or 0), "unit": "count",
            "sub": f"leads from ads, {_plural(campaigns, 'campaign', 'campaigns')}"}


# ───────────────────────────────────────────────────────────── chats (Needs you)

def _inbox_params(ctx: dict, segments: str | None = None) -> dict:
    """The Chats page's own filter params (so Home counts what the tab counts)."""
    from app.routes.conversations import _filter_params
    return _filter_params(
        ctx, q=None, channels=None, segments=segments, results=None, came_from=None,
        handled_by=None, waiting=None, since=None, tag_id=None,
    )


def _needs_you_rows(db, ctx: dict, limit: int, segments: str | None = None) -> list[dict]:
    """Needs-you chats (inbox_group 0), longest waiting first, with name/segment/phone attached."""
    params = _inbox_params(ctx, segments)
    params.update({"p_limit": limit, "p_offset": 0, "p_view": "needs_you"})
    rows = [r for r in (db.rpc("get_inbox_chats", params).execute().data or [])
            if r.get("lead_id") and r.get("inbox_group") == 0]
    if not rows:
        return []
    leads = (
        db.table("leads").select("id, name, phone, segment").in_("id", [r["lead_id"] for r in rows])
        .eq("tenant_id", ctx["tenant_id"]).is_("deleted_at", "null").execute().data or []
    )
    by_id = {l["id"]: l for l in leads}
    out = []
    for r in rows:
        lead = by_id.get(r["lead_id"])
        if not lead:
            continue
        since = r.get("waiting_since") or r.get("last_reply_at")
        if not since:
            continue
        out.append({
            "lead_id": r["lead_id"], "name": lead.get("name") or lead.get("phone"),
            "segment": lead.get("segment"), "phone": lead.get("phone"),
            "last_message": (r.get("last_message_content") or "")[:140] or None, "waiting_since": since,
        })
    return out


def _needs_you_count(db, ctx: dict, segments: str | None = None) -> int:
    params = _inbox_params(ctx, segments)
    params["p_view"] = "needs_you"
    data = db.rpc("get_inbox_counts", params).execute().data or {}
    return int(data.get("needs_you") or 0)


def _waiting_list(db, ctx: dict) -> dict:
    items = _needs_you_rows(db, ctx, 6)
    return {
        "total": _needs_you_count(db, ctx),
        "items": [{k: i[k] for k in ("lead_id", "name", "segment", "last_message", "waiting_since")} for i in items],
    }


def _hot(db, ctx: dict) -> tuple[int, dict | None]:
    """(Hot chats needing you, the longest-waiting one as the red bar)."""
    count = _needs_you_count(db, ctx, "A")
    if not count:
        return 0, None
    rows = _needs_you_rows(db, ctx, 1, "A")
    bar = None
    if rows:
        r = rows[0]
        bar = {k: r[k] for k in ("lead_id", "name", "waiting_since", "last_message", "phone")}
    return count, bar


# ───────────────────────────────────────────────────────────── catalogue stock

def _low_stock(db, tenant_id: str) -> dict:
    """Tracked products at or below their alert level (5 when none set), out of stock included,
    available = stock minus pieces held on unpaid links (catalog/money.ts isLow)."""
    from app.services.deals import LOW_STOCK_THRESHOLD, held_quantities
    rows = (
        db.table("catalog_items").select("id, name, stock_quantity, low_stock_at, item_type")
        .eq("tenant_id", tenant_id).not_.is_("stock_quantity", "null").limit(2000).execute().data or []
    )
    rows = [r for r in rows if r.get("item_type", "product") == "product"]
    held = held_quantities(tenant_id, [r["id"] for r in rows], db)
    low = []
    for r in rows:
        available = int(r["stock_quantity"]) - held.get(r["id"], 0)
        level = r.get("low_stock_at")
        if available <= (LOW_STOCK_THRESHOLD if level is None else int(level)):
            low.append({"item_id": r["id"], "name": r["name"], "stock": max(available, 0), "low_stock_at": level})
    low.sort(key=lambda i: (i["stock"], i["name"] or ""))
    return {"total": len(low), "items": low[:5]}


def _box_low_stock(stock: dict) -> dict:
    out = sum(1 for i in stock["items"] if i["stock"] == 0)
    return {"value": stock["total"], "unit": "count", "sub": f"{out} out of stock" if out else "running low"}


# ───────────────────────────────────────────────────────────── bookings

def _bookings_today(db, ctx: dict, t: dict) -> dict:
    """Today's bookings (IST) in the columns this person may see: the box + the next 10 on the list."""
    from app.services import booking_setup as bsetup
    from app.services import bookings as bk
    tenant_id = ctx["tenant_id"]
    columns = bk.scoped_columns(db, ctx)
    names = {r["id"]: r["name"] for r in columns}
    day = t["today"].date()
    rows = bk.bookings_on(db, tenant_id, day, day, list(names))
    live = [r for r in rows if r["status"] in ("held", "booked", "came")]
    came = sum(1 for r in rows if r["status"] == "came")
    missed = sum(1 for r in rows if r["status"] == "no_show")
    sub = f"{came} came · {missed} didn't come"
    services = bk.service_map(db, tenant_id)
    now = t["now"]
    upcoming = [r for r in rows if r["status"] in ("held", "booked") and bk.parse_ts(r["end_at"]) >= now]
    items = [{
        "id": r["id"], "start_at": r["start_at"], "status": r["status"], "customer_name": r.get("customer_name") or r.get("phone"),
        "service_name": (services.get(r["service_id"]) or {}).get("name"), "resource_name": names.get(r["resource_id"]),
    } for r in upcoming[:10]]
    return {"box": {"value": len(live), "unit": "count", "sub": sub},
            "list": {"total": len(upcoming), "items": items}}


# ───────────────────────────────────────────────────────────── money: profit and expenses

def _box_profit(db, ctx: dict, t: dict) -> dict:
    """This month so far (IST, 1st to today): the Reports > Money formula itself, sales - refunds -
    cost of items sold - expenses. A loss is a negative number."""
    from app.services import reports_money
    from app.services.reports_common import flags_for, resolve_period
    period = resolve_period(t["month"].date().isoformat(), t["today"].date().isoformat())
    numbers, _ = reports_money.compute(db, ctx["tenant_id"], period, flags_for(ctx))
    return {"value": int(numbers["profit_paise"]), "unit": "paise", "sub": f"{t['today'].strftime('%b')} so far"}


def _box_expenses_today(db, tenant_id: str, t: dict) -> dict:
    """Expenses written down for today (IST): the Expenses page's own rows."""
    rows = (
        db.table("cash_expenses").select("id, amount_paise").eq("tenant_id", tenant_id)
        .eq("day", t["today"].date().isoformat()).limit(5000).execute().data or []
    )
    total = sum(int(r.get("amount_paise") or 0) for r in rows)
    return {"value": total, "unit": "paise", "sub": _plural(len(rows), "expense", "expenses")}


# ───────────────────────────────────────────────────────────── customer feedback

FEEDBACK_HREF = "/dashboard/leads?tab=feedback"
FEEDBACK_LIST_ROWS = 5
FEEDBACK_WEEK_DAYS = 7


def _feedback(db, ctx: dict, t: dict) -> dict:
    """The week box and today's list from the same rows. A telecaller counts only the people assigned to
    them (the Feedback page's own rule). Names come from leads, scoped to this client."""
    from app.routes.customer_feedback import _assigned_to_caller, _names
    from app.services import customer_feedback as fb
    tenant_id = ctx["tenant_id"]
    week_start = t["today"] - timedelta(days=FEEDBACK_WEEK_DAYS - 1)  # 7 IST days, today included
    week_from = week_start.astimezone(timezone.utc).isoformat()
    week = (
        db.table("customer_feedback").select("id, lead_id, stars, reason, answered_at").eq("tenant_id", tenant_id)
        .eq("status", "answered").not_.is_("stars", "null").gte("answered_at", week_from)
        .order("answered_at", desc=True).limit(5000).execute().data or []
    )
    unhappy = (
        db.table("customer_feedback").select("id, lead_id").eq("tenant_id", tenant_id)
        .eq("status", "answered").lte("stars", fb.UNHAPPY_MAX).limit(2000).execute().data or []
    )
    week = [r for r in week if _in_day(r.get("answered_at"), week_start, t["tomorrow"])]
    if ctx.get("role") == "caller":
        mine = _assigned_to_caller(db, ctx, [r.get("lead_id") for r in week + unhappy])
        week = [r for r in week if str(r.get("lead_id")) in mine]
        unhappy = [r for r in unhappy if str(r.get("lead_id")) in mine]
    stars = [int(r["stars"]) for r in week if r.get("stars")]
    average = round(sum(stars) / len(stars), 1) if stars else None
    box = {"value": average, "unit": "stars", "sub": f"{len(stars)} answered · {len(unhappy)} unhappy open"}

    # The database may send times in another UTC offset, so compare moments, not text.
    todays = sorted((r for r in week if _in_day(r.get("answered_at"), t["today"], t["tomorrow"])),
                    key=lambda r: _moment(r["answered_at"]), reverse=True)
    names = _names(db, tenant_id, todays[:FEEDBACK_LIST_ROWS])
    items = [{
        "id": r["id"], "lead_id": r.get("lead_id"), "name": names.get(str(r.get("lead_id"))) or None,
        "stars": int(r["stars"]), "reason": ((r.get("reason") or "").strip()[:140] or None),
    } for r in todays[:FEEDBACK_LIST_ROWS]]
    return {"box": box, "list": {"total": len(todays), "items": items}}


def _moment(ts) -> datetime:
    from app.services.customer_feedback import _parse
    return _parse(ts) or datetime.min.replace(tzinfo=timezone.utc)


def _in_day(ts, start: datetime, end: datetime) -> bool:
    """True when the time is from `start` up to, not including, `end`."""
    from app.services.customer_feedback import _parse
    moment = _parse(ts)
    return bool(moment and start <= moment < end)


# ───────────────────────────────────────────────────────────── the whole answer

def compute_today(db, ctx: dict, now: datetime | None = None) -> dict:
    """available / defaults / boxes / hot_bar / waiting / low_stock / todays_bookings / todays_feedback for this person."""
    from app.services.orders import _now
    tenant_id = ctx["tenant_id"]
    t = _times(now or _now())
    gates = _gates(db, ctx, tenant_id)
    boxes: dict[str, dict] = {}
    hot_bar = waiting = low_stock = todays_feedback = None

    cards = None
    if any(gates[k] for k in ("money_in_today", "to_collect", "orders_pending")):
        got = _safe("orders cards", lambda: _orders_cards(db, tenant_id, t))
        cards = None if got is _FAILED else got
    if cards is not None:
        if gates["money_in_today"]:
            boxes["money_in_today"] = _box_money_in(cards)
        if gates["to_collect"]:
            boxes["to_collect"] = _box_to_collect(cards)
        if gates["orders_pending"]:
            boxes["orders_pending"] = _box_orders_pending(cards)

    singles = {
        "quotes_open": lambda: _box_quotes_open(db, tenant_id, t),
        "new_enquiries_today": lambda: _box_new_enquiries(db, tenant_id, t),
        "won_month": lambda: _box_won_month(db, tenant_id, t),
        "callbacks_today": lambda: _box_callbacks(db, tenant_id, t),
        "ads_today": lambda: _box_ads(db, tenant_id),
        "profit_month": lambda: _box_profit(db, ctx, t),
        "expenses_today": lambda: _box_expenses_today(db, tenant_id, t),
    }
    for key, fn in singles.items():
        if gates[key]:
            box = _safe(key, fn)
            if box is not _FAILED and box is not None:
                boxes[key] = box

    if _has_permission(ctx, "conversations.view"):
        got = _safe("waiting list", lambda: _waiting_list(db, ctx))
        waiting = None if got is _FAILED else got
        got = _safe("hot chats", lambda: _hot(db, ctx))
        if got is not _FAILED:
            hot_count, hot_bar = got
            if gates["hot_waiting"]:
                boxes["hot_waiting"] = {"value": hot_count, "unit": "count", "sub": "waiting for your reply"}

    # Target box: its own rule (who may see money vs only a %), decided in sales_target.home_box.
    from app.services import sales_target
    box = _safe("target", lambda: sales_target.home_box(db, ctx, t["now"]))
    if box is not _FAILED and box is not None:
        # a trend line only for people who see rupees (unit paise); the % view and "set a target" get none
        if box.get("unit") == "paise":
            _with_series(box, "target series", lambda: _money_series(db, tenant_id, t), tenant_id, t["today"])
        boxes["target_month"] = box

    todays_bookings = None
    if gates["bookings_today"]:
        got = _safe("bookings", lambda: _bookings_today(db, ctx, t))
        if got is not _FAILED:
            boxes["bookings_today"] = got["box"]
            todays_bookings = got["list"]

    if gates["feedback_week"]:
        got = _safe("feedback", lambda: _feedback(db, ctx, t))
        if got is not _FAILED:
            boxes["feedback_week"] = got["box"]
            todays_feedback = got["list"]

    if gates["low_stock"]:
        got = _safe("low stock", lambda: _low_stock(db, tenant_id))
        if got is not _FAILED:
            low_stock = got
            boxes["low_stock"] = _box_low_stock(got)

    available = [k for k in BOX_KEYS if k in boxes]
    for k in available:
        boxes[k].setdefault("href", HREF[k])
    return {
        "available": available,
        "defaults": available[:DEFAULT_COUNT],
        "boxes": boxes,
        "hot_bar": hot_bar,
        "waiting": waiting,
        "low_stock": low_stock,
        "todays_bookings": todays_bookings,
        "todays_feedback": todays_feedback,
    }
