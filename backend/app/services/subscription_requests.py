import logging
from datetime import date, datetime, timezone

from app.services.entitlements import USAGE_METRICS, add_one_month, get_billing_period, resolve_entitlements

logger = logging.getLogger(__name__)


def _parse_cycle_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw[:10])


def _proration_factor(subscription_row: dict | None, today: date | None = None) -> float:
    """Fraction of the active billing cycle still remaining for add-on charges."""
    if not subscription_row or subscription_row.get("status") != "active":
        return 1.0

    period_start = _parse_cycle_date(subscription_row.get("period_start"))
    period_end = _parse_cycle_date(subscription_row.get("period_end"))
    if not period_start or not period_end or period_end <= period_start:
        return 1.0

    today = today or datetime.now(timezone.utc).date()
    if today <= period_start:
        return 1.0
    if today >= period_end:
        return 0.0

    cycle_days = max((period_end - period_start).days, 1)
    remaining_days = max((period_end - today).days, 0)
    return remaining_days / cycle_days


def _monthly_price_for_item(catalog_row: dict, quantity: int, existing_quantity: int = 0) -> float:
    """
    Price the marginal units being requested right now.

    Flat-priced SKUs (a nonzero `monthly_price`) always cost the full
    `monthly_price` — quantity on those is just a 0/1 toggle (e.g. inbound
    messaging, telecalling_sim/telecmi). Pure quantity SKUs (`monthly_price
    == 0`, e.g. numbers_pool, telecaller_seats) bill only units beyond
    `included_qty`, netting out `existing_quantity` so a top-up request
    doesn't re-charge for an included unit a prior request already covered.
    """
    monthly_price = float(catalog_row.get("monthly_price") or 0)
    if monthly_price > 0:
        return monthly_price
    unit_price = catalog_row.get("unit_price")
    if unit_price is None:
        return 0.0
    included_qty = catalog_row.get("included_qty")
    if included_qty is None:
        already_billable = existing_quantity
        new_billable = existing_quantity + quantity
    else:
        already_billable = max(0, existing_quantity - included_qty)
        new_billable = max(0, (existing_quantity + quantity) - included_qty)
    return float(unit_price) * (new_billable - already_billable)


# Set per client by the operator (their own screens), never bought through a cart request. Checked here, not
# only in the route: a tenant owner can insert a subscription_requests row directly (RLS allows owners), and
# approving one with "agent_replies" (catalog price 0) would hand out free replies (security review 23 Nov).
OPERATOR_ONLY_FEATURES = frozenset({"private_send", "agent_replies"})


def _without_operator_only(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("feature_key") not in OPERATOR_ONLY_FEATURES]


def submit_request(db, tenant_id: str, requested_items: list[dict], package_id: str | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
    """
    Create a subscription_requests row for a cart submission (first-time
    onboarding or a later top-up ask) and flip the tenant into
    pending_approval. `requested_items` is [{"feature_key": str, "quantity": int}].
    Operator-only items are dropped (OPERATOR_ONLY_FEATURES).
    """
    requested_items = _without_operator_only(requested_items)
    feature_keys = [i["feature_key"] for i in requested_items]
    catalog_res = db.table("feature_catalog").select(
        "feature_key, monthly_price, unit_price, included_qty"
    ).in_("feature_key", feature_keys).execute()
    catalog_by_key = {row["feature_key"]: row for row in (catalog_res.data or [])}

    existing_res = db.table("tenant_subscription_items").select("feature_key, quantity").eq(
        "tenant_id", tenant_id
    ).in_("feature_key", feature_keys).execute()
    existing_qty_by_key = {row["feature_key"]: row.get("quantity") or 0 for row in (existing_res.data or [])}

    total_amount = 0.0
    priced_items = []
    for item in requested_items:
        catalog_row = catalog_by_key.get(item["feature_key"], {})
        quantity = item.get("quantity") or 1
        existing_quantity = existing_qty_by_key.get(item["feature_key"], 0)
        monthly_price = _monthly_price_for_item(catalog_row, quantity, existing_quantity)
        priced_items.append({**item, "quantity": quantity, "monthly_amount": monthly_price})

    existing = db.table("tenant_subscriptions").select("status, period_start, period_end").eq("tenant_id", tenant_id).maybe_single().execute()
    # maybe_single().execute() returns None outright (not an object with
    # `.data = None`) on zero rows — the norm for a brand-new tenant
    # submitting their very first cart, so this must not touch `.data`
    # before checking `existing` itself.
    existing_status = (existing.data or {}).get("status") if existing else None
    is_initial = existing_status != "active"

    if is_initial and start_date and end_date:
        s_date = date.fromisoformat(start_date)
        e_date = date.fromisoformat(end_date)
        duration_days = max(1, (e_date - s_date).days)
        proration = duration_days / 30.0
    else:
        proration = _proration_factor(existing.data if existing else None)

    for item in priced_items:
        monthly_price = item.pop("monthly_amount")
        line_total = monthly_price * proration if (is_initial and start_date and end_date) else (monthly_price if is_initial else monthly_price * proration)
        item["monthly_amount"] = monthly_price
        item["line_total"] = line_total
        item["proration_factor"] = proration
        total_amount += line_total

    inserted = db.table("subscription_requests").insert({
        "tenant_id": tenant_id,
        "status": "submitted",
        "requested_items": priced_items,
        "package_id": package_id,
        "total_amount": total_amount,
        "is_initial": is_initial,
        "start_date": start_date,
        "end_date": end_date,
    }).execute()

    # Only the tenant's *first* request gates the dashboard behind the
    # Subscriptions cart. A top-up from an already-active tenant (e.g.
    # requesting one more phone number) must leave status alone — the rest
    # of the dashboard, including whatever they already purchased, keeps
    # working while this specific request is pending; only the new item
    # itself stays locked (enforced at the action point via
    # get_purchased_quantity/check_quota) until an admin approves it.
    if is_initial:
        db.table("tenant_subscriptions").upsert({
            "tenant_id": tenant_id,
            "status": "pending_approval",
        }, on_conflict="tenant_id").execute()

    request_row = inserted.data[0] if inserted.data else {}
    return {**request_row, "total_amount": total_amount}


def approve_request(db, request_id: str, reviewer_user_id: str) -> dict:
    """
    Approve a pending request: upsert tenant_subscription_items (incrementing
    quantity on an existing feature_key row rather than duplicating),
    recompute entitlements/usage/mrr, and activate the subscription.
    """
    req = db.table("subscription_requests").select(
        "id, tenant_id, requested_items, package_id, total_amount, is_initial, start_date, end_date"
    ).eq("id", request_id).maybe_single().execute()
    if not req or not req.data:
        raise ValueError(f"subscription_request {request_id} not found")

    tenant_id = req.data["tenant_id"]
    package_id = req.data.get("package_id")
    requested_items = _without_operator_only(req.data.get("requested_items") or [])   # see OPERATOR_ONLY_FEATURES
    is_initial = req.data.get("is_initial", True)
    start_date = req.data.get("start_date")
    end_date = req.data.get("end_date")

    feature_keys = [item["feature_key"] for item in requested_items]
    catalog_res = db.table("feature_catalog").select(
        "feature_key, monthly_price, unit_price, included_qty"
    ).in_("feature_key", feature_keys).execute()
    catalog_by_key = {row["feature_key"]: row for row in (catalog_res.data or [])}

    for item in requested_items:
        feature_key = item["feature_key"]
        quantity = item.get("quantity") or 1

        existing = db.table("tenant_subscription_items").select("quantity").eq(
            "tenant_id", tenant_id
        ).eq("feature_key", feature_key).maybe_single().execute()
        # maybe_single().execute() returns None (not a response) on zero rows,
        # which is the norm for an initial subscription with no items yet.
        existing_quantity = (existing.data or {}).get("quantity") if existing else 0
        new_quantity = quantity + (existing_quantity or 0)

        # Recompute a blended per-unit rate from the final total quantity
        # (rather than trusting the request's marginal `line_total`) so that
        # `quantity * unit_price_snapshot` always equals the tenant's true
        # ongoing cost for this line, however many top-ups it took to get
        # there — e.g. numbers_pool at qty=2 with included_qty=1 always
        # blends to (unit_price * 1) / 2 per unit, regardless of whether the
        # 2nd number was bought in this request or a prior one.
        catalog_row = catalog_by_key.get(feature_key, {})
        monthly_price = float(catalog_row.get("monthly_price") or 0)
        if monthly_price > 0:
            unit_price_snapshot = monthly_price
        else:
            unit_price = catalog_row.get("unit_price")
            included_qty = catalog_row.get("included_qty")
            if unit_price is not None and new_quantity > 0:
                billable_units = new_quantity if included_qty is None else max(0, new_quantity - included_qty)
                billable_total = float(unit_price) * billable_units
                unit_price_snapshot = billable_total / new_quantity
            else:
                unit_price_snapshot = 0.0

        db.table("tenant_subscription_items").upsert({
            "tenant_id": tenant_id,
            "feature_key": feature_key,
            "quantity": new_quantity,
            "unit_price_snapshot": unit_price_snapshot,
            "package_id": package_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="tenant_id,feature_key").execute()

    sync_client_toggles(db, tenant_id)
    ent = resolve_entitlements(db, tenant_id)

    # First-ever approval anchors the billing cycle to today (e.g. approved
    # 2026-07-04 -> renews 2026-08-04, not reset on the calendar month
    # boundary). A later top-up approval just uses whatever cycle is
    # currently active — rolling it forward first if it's already lapsed —
    # and only raises `included` for the remaining current cycle; it must
    # not reset `used`, since the tenant's existing purchases (and the
    # usage they've already run up this cycle) keep working unaffected by
    # the new item being approved.
    subscription_update: dict = {"status": "active"}
    if is_initial:
        if start_date and end_date:
            period = start_date
            subscription_update["period_start"] = start_date
            subscription_update["period_end"] = end_date
        else:
            today = datetime.now(timezone.utc).date()
            period = today.isoformat()
            subscription_update["period_start"] = period
            subscription_update["period_end"] = add_one_month(today).isoformat()
    else:
        period = get_billing_period(db, tenant_id)

    for metric in USAGE_METRICS:
        included = ent["quotas"].get(metric, 0)
        db.table("tenant_usage_counters").upsert({
            "tenant_id": tenant_id,
            "period": period,
            "metric": metric,
            "included": included,
        }, on_conflict="tenant_id,period,metric").execute()

    all_items = db.table("tenant_subscription_items").select("quantity, unit_price_snapshot").eq("tenant_id", tenant_id).execute()
    mrr = sum((r.get("quantity") or 0) * (r.get("unit_price_snapshot") or 0) for r in (all_items.data or []))
    subscription_update["mrr"] = mrr

    db.table("tenant_subscriptions").update(subscription_update).eq("tenant_id", tenant_id).execute()

    updated = db.table("subscription_requests").update({
        "status": "approved",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": reviewer_user_id,
    }).eq("id", request_id).execute()

    return updated.data[0] if updated.data else {"id": request_id, "status": "approved"}


def reject_request(db, request_id: str, reviewer_user_id: str, reason: str) -> dict:
    """Reject a pending request. Does not touch tenant_subscription_items."""
    updated = db.table("subscription_requests").update({
        "status": "rejected",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": reviewer_user_id,
        "rejection_reason": reason,
    }).eq("id", request_id).execute()

    return updated.data[0] if updated.data else {"id": request_id, "status": "rejected"}


def sync_client_toggles(db, tenant_id: str) -> None:
    """
    Synchronize client features and calling provider based on active subscription items.
    """
    ent = resolve_entitlements(db, tenant_id)
    features_to_enable = set(ent.get("features") or [])

    tenant_res = db.table("tenants").select("enabled_features").eq("id", tenant_id).maybe_single().execute()
    if not tenant_res or not tenant_res.data:
        logger.error(f"Tenant {tenant_id} not found in sync_client_toggles")
        return

    old_enabled_features = set(tenant_res.data.get("enabled_features") or [])

    catalog_res = db.table("feature_catalog").select("feature_key, depends_on").execute()
    billing_derived = set()
    for row in (catalog_res.data or []):
        billing_derived.add(row["feature_key"])
        for dep in (row.get("depends_on") or []):
            billing_derived.add(dep)

    new_features = (old_enabled_features - billing_derived) | features_to_enable

    db.table("tenants").update({"enabled_features": sorted(list(new_features))}).eq("id", tenant_id).execute()

    items_res = db.table("tenant_subscription_items").select("feature_key").eq("tenant_id", tenant_id).execute()
    active_keys = {row["feature_key"] for row in (items_res.data or [])}

    sim_active = "telecalling_sim" in active_keys
    telecmi_active = "telecalling_telecmi" in active_keys

    from app.services.assignment import get_telecalling_config, save_telecalling_config

    if sim_active or telecmi_active:
        cfg = get_telecalling_config(tenant_id, db=db)
        if sim_active and not telecmi_active:
            cfg["calling_provider"] = "sim_basic"
            save_telecalling_config(tenant_id, cfg, db=db)
        elif telecmi_active and not sim_active:
            cfg["calling_provider"] = "telecmi"
            save_telecalling_config(tenant_id, cfg, db=db)
        elif sim_active and telecmi_active:
            logger.warning(f"Both telecalling_sim and telecalling_telecmi active for tenant {tenant_id}, defaulting to telecmi")
            cfg["calling_provider"] = "telecmi"
            save_telecalling_config(tenant_id, cfg, db=db)

