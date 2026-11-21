"""Home (Today): the numbers behind the boxes and lists on the dashboard's first screen.

Every number comes from the same code the linked page uses, so Home never disagrees with it:
  money_in_today / to_collect / orders_pending -> services/orders._cards (Orders & payments cards)
  new_enquiries_today / won_month              -> routes/inbound_leads._count (Inbound leads page)
  hot_waiting / waiting list / hot bar         -> SQL get_inbox_chats + get_inbox_counts (Chats)
  callbacks_today                              -> follow_up_jobs, cadence callback (Scheduled calls)
  ads_today                                    -> services/growth.build_ad_performance (Ad Spend card)
  quotes_open                                  -> services/order_quotes._expired (quote rules)
  low_stock                                    -> catalogue stock rules (catalog/money.ts isLow)

Each source runs on its own: one that fails is logged and left out, never a 500.
Who sees what: _has_permission AND "the client uses it" (see _gates).
"""
import logging
from datetime import datetime, timedelta

from app.dependencies.tenant import _has_permission

logger = logging.getLogger(__name__)

# The only working boxes, in DEFAULT PRIORITY ORDER.
BOX_KEYS = (
    "money_in_today", "new_enquiries_today", "hot_waiting", "to_collect", "callbacks_today",
    "orders_pending", "ads_today", "quotes_open", "won_month", "low_stock",
)
LIST_KEYS = ("waiting", "low_stock")
MAX_BOXES = 12
DEFAULT_COUNT = 6

HREF = {
    "money_in_today": "/dashboard/deals", "to_collect": "/dashboard/deals",
    "orders_pending": "/dashboard/deals", "quotes_open": "/dashboard/deals",
    "new_enquiries_today": "/dashboard/inbound-leads", "won_month": "/dashboard/inbound-leads",
    "hot_waiting": "/dashboard/conversations", "callbacks_today": "/dashboard/telecalling/scheduled",
    "ads_today": "/dashboard/meta-ads", "low_stock": "/dashboard/catalog",
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


def _box_new_enquiries(db, tenant_id: str, t: dict) -> dict:
    total, hot = _inbound_counts(db, tenant_id, t)
    return {"value": total, "unit": "count", "sub": f"{hot} Hot"}


def _box_won_month(db, tenant_id: str, t: dict) -> dict:
    """Inbound leads marked converted (bought) since the 1st, IST."""
    from app.routes.inbound_leads import InboundFilters, _leads_query
    res = (
        _leads_query(db, "id", tenant_id, InboundFilters(), count="exact")
        .gte("converted_at", t["month"].isoformat()).limit(1).execute()
    )
    return {"value": res.count or 0, "unit": "count", "sub": "bought this month"}


def _box_callbacks(db, tenant_id: str, t: dict) -> dict:
    """Pending call-backs due today, IST (the Scheduled calls board's rows)."""
    res = (
        db.table("follow_up_jobs").select("id", count="exact").eq("tenant_id", tenant_id)
        .eq("cadence", "callback").eq("status", "pending")
        .gte("scheduled_for", t["today"].isoformat()).lt("scheduled_for", t["tomorrow"].isoformat())
        .limit(1).execute()
    )
    return {"value": res.count or 0, "unit": "count", "sub": "calls to make today"}


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
    items = _needs_you_rows(db, ctx, 3)
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


# ───────────────────────────────────────────────────────────── the whole answer

def compute_today(db, ctx: dict, now: datetime | None = None) -> dict:
    """available / defaults / boxes / hot_bar / waiting / low_stock for this person."""
    from app.services.orders import _now
    tenant_id = ctx["tenant_id"]
    t = _times(now or _now())
    gates = _gates(db, ctx, tenant_id)
    boxes: dict[str, dict] = {}
    hot_bar = waiting = low_stock = None

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

    if gates["low_stock"]:
        got = _safe("low stock", lambda: _low_stock(db, tenant_id))
        if got is not _FAILED:
            low_stock = got
            boxes["low_stock"] = _box_low_stock(got)

    available = [k for k in BOX_KEYS if k in boxes]
    for k in available:
        boxes[k]["href"] = HREF[k]
    return {
        "available": available,
        "defaults": available[:DEFAULT_COUNT],
        "boxes": boxes,
        "hot_bar": hot_bar,
        "waiting": waiting,
        "low_stock": low_stock,
    }
