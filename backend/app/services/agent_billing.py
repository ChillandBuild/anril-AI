"""Agents billing: each business's 'Agent replies' item (migration 342) and its usage this cycle.

The operator sets a client's included replies and monthly price (set_plan). Every finished agent reply adds 1
to the 'agent_reply' counter (companion_public._after_response -> entitlements.add_usage). Track only: going
over the included replies never blocks a reply; the client sees the overage on Agents -> Usage (usage()).

Worked example: set_plan(db, astro, 10000, 3000) -> item agent_replies, quantity 10000 at Rs 0.30 each,
this cycle's counter included 10000. After 10,420 replies usage() says used 10420, over 420.
"""
from datetime import date, datetime, timezone

from app.services.entitlements import add_one_month, get_billing_period

FEATURE_KEY = "agent_replies"
METRIC = "agent_reply"
MAX_INCLUDED = 10_000_000
MAX_PRICE = 10_000_000


class PlanError(ValueError):
    pass


def _item(db, tenant_id: str) -> dict | None:
    res = (db.table("tenant_subscription_items").select("quantity, unit_price_snapshot")
           .eq("tenant_id", tenant_id).eq("feature_key", FEATURE_KEY).maybe_single().execute())
    return res.data if res else None


def _plan(item: dict | None) -> dict | None:
    """{"included": 10000, "monthly_price": 3000.0}, or None when the client has no agent plan."""
    if not item or not item.get("quantity"):
        return None
    quantity = int(item["quantity"])
    return {"included": quantity, "monthly_price": round(quantity * float(item.get("unit_price_snapshot") or 0), 2)}


def _set_mrr(db, tenant_id: str) -> None:
    """Same sum as subscription_requests.approve_request: every item's quantity x unit price."""
    items = db.table("tenant_subscription_items").select("quantity, unit_price_snapshot").eq(
        "tenant_id", tenant_id).execute().data or []
    mrr = sum((r.get("quantity") or 0) * float(r.get("unit_price_snapshot") or 0) for r in items)
    db.table("tenant_subscriptions").update({"mrr": mrr}).eq("tenant_id", tenant_id).execute()


def set_plan(db, tenant_id: str, included: int, monthly_price: float) -> dict | None:
    """The operator's setting. included 0 removes the item (the counter keeps counting, with nothing
    included). This cycle's counter takes the new included at once; `used` is never touched.
    Returns the new plan (see _plan)."""
    if not 0 <= included <= MAX_INCLUDED:
        raise PlanError(f"Included replies must be between 0 and {MAX_INCLUDED:,}")
    if not 0 <= monthly_price <= MAX_PRICE:
        raise PlanError("Enter a monthly price of 0 or more")
    if included == 0:
        db.table("tenant_subscription_items").delete().eq("tenant_id", tenant_id).eq(
            "feature_key", FEATURE_KEY).execute()
    else:
        db.table("tenant_subscription_items").upsert({
            "tenant_id": tenant_id, "feature_key": FEATURE_KEY, "quantity": included,
            "unit_price_snapshot": monthly_price / included, "package_id": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="tenant_id,feature_key").execute()
    period = get_billing_period(db, tenant_id)
    db.table("tenant_usage_counters").upsert(
        {"tenant_id": tenant_id, "period": period, "metric": METRIC, "included": included},
        on_conflict="tenant_id,period,metric").execute()
    _set_mrr(db, tenant_id)
    return _plan(_item(db, tenant_id))


def _period_end(db, tenant_id: str, period: str) -> str | None:
    """The day this cycle ends: the subscription's period_end, else (calendar-month key "2026-11")
    the first of next month."""
    sub = db.table("tenant_subscriptions").select("period_end").eq("tenant_id", tenant_id).maybe_single().execute()
    end = ((sub.data if sub else None) or {}).get("period_end")
    if end:
        return str(end)[:10]
    try:
        return add_one_month(date.fromisoformat(f"{period}-01")).isoformat() if len(period) == 7 else None
    except ValueError:
        return None


def usage(db, tenant_id: str) -> dict:
    """This cycle for Agents -> Usage: {"period_start", "period_end", "used", "included", "over",
    "plan": {"included", "monthly_price"} | None}. Reads the plan from the item (the counter's `included`
    may be from before an operator change)."""
    period = get_billing_period(db, tenant_id)
    res = (db.table("tenant_usage_counters").select("used").eq("tenant_id", tenant_id)
           .eq("period", period).eq("metric", METRIC).maybe_single().execute())
    used = int(float(((res.data if res else None) or {}).get("used") or 0))
    plan = _plan(_item(db, tenant_id))
    included = plan["included"] if plan else 0
    start = f"{period}-01" if len(period) == 7 else period
    return {"period_start": start, "period_end": _period_end(db, tenant_id, period), "used": used,
            "included": included, "over": max(0, used - included) if plan else 0, "plan": plan}
