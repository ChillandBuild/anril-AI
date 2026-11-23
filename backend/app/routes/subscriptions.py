import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role, require_permission
from app.services.entitlements import add_one_month, get_billing_period
from datetime import date
from app.services.subscription_requests import OPERATOR_ONLY_FEATURES, submit_request

logger = logging.getLogger(__name__)
router = APIRouter()
require_subscription_manage = require_permission("subscription.manage")

# Switched on by the operator only (licence + tier set in the operator console),
# so clients never see them in the cart or request them.


@router.get("/catalog")
def get_catalog(ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()
    catalog = db.table("feature_catalog").select(
        "feature_key, display_name, category, monthly_price, unit_price, included_qty, usage_metric"
    ).order("sort_order").execute()
    packages = db.table("plans").select(
        "id, name, monthly_price, feature_keys, discount_percent"
    ).eq("active", True).order("created_at").execute()
    visible = [row for row in (catalog.data or []) if row.get("feature_key") not in OPERATOR_ONLY_FEATURES]
    return {"catalog": visible, "packages": packages.data or []}


@router.get("/me")
def get_my_subscription(ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    sub = db.table("tenant_subscriptions").select(
        "status, mrr, period_start, period_end"
    ).eq("tenant_id", tenant_id).maybe_single().execute()
    items = db.table("tenant_subscription_items").select("feature_key, quantity, unit_price_snapshot").eq("tenant_id", tenant_id).execute()

    # Rolls the tenant's anchored cycle forward (and resets usage) if it's
    # lapsed, so a client who hasn't opened the app in a while still sees
    # an up-to-date cycle rather than a stale, long-expired one.
    period = get_billing_period(db, tenant_id)
    usage = db.table("tenant_usage_counters").select("metric, used, included, hard_cap").eq("tenant_id", tenant_id).eq("period", period).execute()

    pending = db.table("subscription_requests").select(
        "id, requested_items, total_amount, submitted_at, status, rejection_reason, start_date, end_date"
    ).eq("tenant_id", tenant_id).order("submitted_at", desc=True).limit(1).execute()
    latest_request = (pending.data or [None])[0]

    # `maybe_single().execute()` returns None outright (not an object with
    # `.data = None`) when zero rows match — the normal case for a tenant
    # that's never had a tenant_subscriptions row at all (e.g. created but
    # never submitted a cart). Guard against that before touching `.data`.
    sub_data = (sub.data if sub else None) or {}
    # `period` reflects any rollover get_billing_period just performed, so
    # derive the returned cycle dates from it rather than the `sub_data`
    # snapshot fetched before that rollover, which would otherwise show a
    # stale (already-lapsed) end date for one request after a rollover.
    has_anchor = bool(sub_data.get("period_start"))
    return {
        "status": sub_data.get("status", "none"),
        "mrr": sub_data.get("mrr", 0),
        "period_start": period if has_anchor else None,
        "period_end": add_one_month(date.fromisoformat(period)).isoformat() if has_anchor else None,
        "items": items.data or [],
        "usage": usage.data or [],
        "latest_request": latest_request,
    }


class SubmitItem(BaseModel):
    feature_key: str
    quantity: int = 1


class SubmitRequestPayload(BaseModel):
    package_id: str | None = None
    items: list[SubmitItem]
    start_date: str | None = None
    end_date: str | None = None


@router.post("/requests")
def create_subscription_request(payload: SubmitRequestPayload, ctx: dict = Depends(require_subscription_manage)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    if any(item.feature_key in OPERATOR_ONLY_FEATURES for item in payload.items):
        raise HTTPException(status_code=400, detail="This feature is set up by your Anril contact")

    db = get_supabase()
    result = submit_request(
        db,
        ctx["tenant_id"],
        requested_items=[item.model_dump() for item in payload.items],
        package_id=payload.package_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return {"data": result}
