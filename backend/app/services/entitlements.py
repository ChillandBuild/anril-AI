import calendar
import logging
from supabase import Client
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

USAGE_METRICS = (
    "message_sent", "ai_reply", "call_minute", "team_seat_active",
    "storage_gb", "ai_call_summary", "ai_call_scoring", "phone_number",
    "ai_speech_to_text", "ai_text_to_speech", "agent_reply",
)


def add_one_month(d: date) -> date:
    """Same day next month, clamped to the shorter month's last day (e.g.
    Jan 31 -> Feb 28/29) — how a billing cycle anchored to a purchase date
    advances (approved 2026-07-04 -> renews 2026-08-04)."""
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def compute_period_key(period_start_raw: str | None, period_end_raw: str | None) -> str:
    """
    Pure calculation of the current billing-period key from a tenant's
    anchored `period_start`/`period_end` — no DB writes. Tenants with no
    anchor yet (pre-existing/grandfathered, or never approved) fall back to
    a plain calendar-month key.
    """
    if not period_start_raw or not period_end_raw:
        return datetime.now(timezone.utc).strftime("%Y-%m")
    period_start = date.fromisoformat(period_start_raw)
    period_end = date.fromisoformat(period_end_raw)
    today = datetime.now(timezone.utc).date()
    while today >= period_end:
        period_start, period_end = period_end, add_one_month(period_end)
    return period_start.isoformat()


def get_billing_period(db: Client, tenant_id: str) -> str:
    """
    Return the tenant's current billing-period key, rolling the cycle
    forward and resetting usage counters (fresh `included` from current
    entitlements, `used` back to 0) if the anchored `period_end` has
    passed. Cycles are anchored to the tenant's subscription approval date
    rather than the calendar month — set once at first approval in
    `subscription_requests.approve_request` and advanced lazily here on
    read/write rather than via a scheduled job, so there's no missed-cron
    risk. Safe to call from single-tenant, mutation-tolerant paths (quota
    checks, usage metering, the client's own `/me`); bulk/list views should
    use the pure `compute_period_key` instead to avoid write side effects.
    """
    sub = db.table("tenant_subscriptions").select("period_start, period_end").eq(
        "tenant_id", tenant_id
    ).maybe_single().execute()
    row = sub.data if sub else None
    period_start_raw = (row or {}).get("period_start")
    period_end_raw = (row or {}).get("period_end")

    key = compute_period_key(period_start_raw, period_end_raw)
    if not period_start_raw or key == period_start_raw:
        return key

    # Rolled forward — persist the new anchor and reset counters for the
    # new cycle using fresh entitlement quotas.
    period_end = add_one_month(date.fromisoformat(key))
    db.table("tenant_subscriptions").update({
        "period_start": key,
        "period_end": period_end.isoformat(),
    }).eq("tenant_id", tenant_id).execute()

    ent = resolve_entitlements(db, tenant_id)
    for metric in USAGE_METRICS:
        db.table("tenant_usage_counters").upsert({
            "tenant_id": tenant_id,
            "period": key,
            "metric": metric,
            "used": 0,
            "included": ent["quotas"].get(metric, 0),
        }, on_conflict="tenant_id,period,metric").execute()

    return key


def resolve_entitlements(db: Client, tenant_id: str) -> dict:
    """
    Build a tenant's entitlements from their purchased line items
    (`tenant_subscription_items`), not a single assigned plan.

    Each purchased item enables itself plus everything in its catalog
    row's `depends_on` list. Metered items contribute
    `included_qty * quantity` to the returned quotas, keyed by the
    catalog row's `usage_metric`.

    Returns {'features': list, 'quotas': dict}
    """
    items_res = db.table("tenant_subscription_items").select("feature_key, quantity").eq("tenant_id", tenant_id).execute()
    items = items_res.data or []
    if not items:
        return {"features": [], "quotas": {}}

    catalog_res = db.table("feature_catalog").select("feature_key, depends_on, usage_metric, included_qty").execute()
    catalog_by_key = {row["feature_key"]: row for row in (catalog_res.data or [])}

    features: set[str] = set()
    quotas: dict[str, int] = {}

    for item in items:
        feature_key = item["feature_key"]
        quantity = item.get("quantity") or 1
        features.add(feature_key)

        catalog_row = catalog_by_key.get(feature_key)
        if not catalog_row:
            continue

        for dep in (catalog_row.get("depends_on") or []):
            features.add(dep)

        metric = catalog_row.get("usage_metric")
        if metric:
            included_qty = catalog_row.get("included_qty") or 0
            quotas[metric] = quotas.get(metric, 0) + (included_qty * quantity)

    return {"features": sorted(features), "quotas": quotas}


def check_feature_enabled(
    db: Client,
    tenant_id: str,
    feature_key: str,
) -> bool:
    """Check if a feature is enabled for a tenant via purchased items."""
    ent = resolve_entitlements(db, tenant_id)
    return feature_key in ent["features"]


def get_purchased_quantity(db: Client, tenant_id: str, feature_key: str) -> int:
    """Total quantity purchased for a feature_key. 0 if never purchased."""
    rows = (
        db.table("tenant_subscription_items")
        .select("quantity")
        .eq("tenant_id", tenant_id)
        .eq("feature_key", feature_key)
        .execute()
    )
    return sum((r.get("quantity") or 0) for r in (rows.data or []))


def check_quota(
    db: Client,
    tenant_id: str,
    metric: str,
    delta: int = 1,
) -> bool:
    """
    Hard-cap check: True if this delta stays within the tenant's included
    quota for `metric` this period, False otherwise. Pure read — does NOT
    mutate `tenant_usage_counters`. Callers must call `increment_usage()`
    (or `meter()`) themselves after the guarded action succeeds.

    During the current unlimited phase, included quotas are informational only.
    Only an explicit hard_cap can block usage.
    """
    period = get_billing_period(db, tenant_id)

    period_res = db.table("tenant_usage_counters").select(
        "used, included, hard_cap"
    ).eq("tenant_id", tenant_id).eq("period", period).eq("metric", metric).maybe_single().execute()

    row = (period_res.data if period_res else None) or {}
    used = row.get("used") or 0
    included = row.get("included") or 0
    hard_cap = row.get("hard_cap")

    if hard_cap is not None:
        return (used + delta) <= hard_cap

    return True


def increment_usage(
    db: Client,
    tenant_id: str,
    metric: str,
    delta: int = 1,
) -> dict:
    """
    Increment a metered counter and return status.
    Returns {'used': int, 'included': int, 'over_cap': bool, 'warning': bool}
    """
    period = get_billing_period(db, tenant_id)

    counter_res = db.table("tenant_usage_counters").select("used, included, hard_cap").eq(
        "tenant_id", tenant_id
    ).eq("period", period).eq("metric", metric).maybe_single().execute()

    # maybe_single().execute() returns None (not an empty response) when no row exists yet.
    current = (counter_res.data if counter_res else None) or {"used": 0, "included": 0, "hard_cap": None}
    used = (current.get("used") or 0) + delta
    included = current.get("included") or 0
    hard_cap = current.get("hard_cap")

    over_cap = False
    warning = False

    if hard_cap is not None:
        over_cap = used > hard_cap
        if included > 0:
            warning = used >= included * 0.8 and used < included
    elif included > 0:
        # Old included quotas are retained for reporting only while usage is unlimited.
        warning = False

    db.table("tenant_usage_counters").upsert({
        "tenant_id": tenant_id,
        "period": period,
        "metric": metric,
        "used": used,
        "included": included,
        "hard_cap": hard_cap,
    }, on_conflict="tenant_id,period,metric").execute()

    return {
        "used": used,
        "included": included,
        "over_cap": over_cap,
        "warning": warning,
    }


# (tenant_id, period, metric) rows add_usage already saw exist, so it skips resolving `included` again.
# Per process; a restart only costs one extra resolve per business.
_COUNTER_SEEN: set[tuple[str, str, str]] = set()


def add_usage(db, tenant_id: str, metric: str, delta: int = 1) -> None:
    """Atomic +delta on this period's counter (RPC add_usage, migration 342), for busy metrics where
    meter()'s read-then-write would lose counts (an agent answering several people a second).
    The first call of a period also writes `included` from the plan. TRACK-ONLY, never raises.
    Example: Astro Tamil's 3,421st agent reply this cycle -> used 3420 -> 3421."""
    if not tenant_id or delta <= 0:
        return
    try:
        period = get_billing_period(db, tenant_id)
        seen = (tenant_id, period, metric)
        included = 0 if seen in _COUNTER_SEEN else resolve_entitlements(db, tenant_id)["quotas"].get(metric, 0)
        db.rpc("add_usage", {"p_tenant": tenant_id, "p_period": period, "p_metric": metric,
                             "p_delta": delta, "p_included": int(included)}).execute()
        _COUNTER_SEEN.add(seen)
    except Exception as e:
        logger.warning(f"usage add failed (tenant={tenant_id}, metric={metric}): {e}")


def meter(db, tenant_id: str, metric: str, delta: int = 1) -> None:
    """Best-effort, non-blocking usage metering. Never raises.

    TRACK-ONLY: this must never block, cap, delay, or break a send/reply/call.
    Callers must not branch on this function's return value for gating.
    Pair with `check_quota()` (called BEFORE the action) for hard enforcement.
    """
    if not tenant_id or delta <= 0:
        return
    try:
        increment_usage(db, tenant_id, metric, delta)
    except Exception as e:
        logger.warning(f"metering failed (tenant={tenant_id}, metric={metric}): {e}")
