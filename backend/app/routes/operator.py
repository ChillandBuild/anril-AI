import logging
import secrets
from typing import Literal
from uuid import UUID
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.supabase import get_supabase
from app.dependencies.auth import get_current_user
from app.dependencies.system_admin import get_system_admin
from app.services.assignment import get_telecalling_config, save_telecalling_config
from app.services.audit_log import record_audit_event
from app.services.call_wrapup import connect_rate as wrapup_connect_rate
from app.services.deal_settings import (
    DEAL_IDLE_CLOSE_DAYS_KEY,
    clamp_deal_idle_close_days,
    validate_deal_idle_close_days,
)
from app.services.entitlements import compute_period_key, get_billing_period
from app.services import private_send as private_send_svc
from app.services.token_pricing import estimate_cost, get_rates, upsert_rate
from app.services.subscription_requests import approve_request, reject_request
from app.services.rbac import ensure_default_roles, is_telecaller_role, normalize_permissions
from app.utils.db_retry import execute_with_retry

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/me")
def operator_me(user: dict = Depends(get_current_user)):
    """Verify the caller is a system admin. No tenant required."""
    db = get_supabase()
    result = (
        db.table("system_admins")
        .select("user_id")
        .eq("user_id", user["user_id"])
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=403, detail="Access denied.")
    return {"is_system_admin": True, "user_id": user["user_id"]}


_SERVICE_CATALOG: dict[str, list[str]] = {
    "whatsapp_only":         ["whatsapp"],
    "telecalling_only":      ["telecalling"],
    "combined":              ["whatsapp", "telecalling"],
    "whatsapp_instagram":    ["whatsapp", "instagram"],
    "whatsapp_facebook":     ["whatsapp", "facebook"],
    "whatsapp_telegram":    ["whatsapp", "telegram"],
    "omnichannel":           ["whatsapp", "instagram", "facebook", "telegram"],
    "omnichannel_telecalling": ["whatsapp", "instagram", "facebook", "telegram", "telecalling"],
}

_SETTING_KEYS: list[tuple[str, bool]] = [
    ("meta_phone_number_id", False), ("meta_access_token", True),
    ("meta_waba_id", False), ("meta_webhook_verify_token", True),
    ("meta_app_secret", True),
    ("telecmi_app_id", False), ("telecmi_user_id", False), ("telecmi_secret", True),
    ("telecmi_callerid", False), ("telecmi_webhook_secret", True), ("telecmi_recording_base_url", False),
    ("sarvam_api_key", True), ("groq_api_key", True),
    ("gemini_api_key", True), ("openai_api_key", True),
    ("jina_api_key", True),
    ("ai_reply_model", False),
    ("telegram_bot_token", True),
    ("instagram_page_id", False), ("instagram_access_token", True),
    ("facebook_page_id", False), ("facebook_access_token", True),
    ("ai_auto_reply_enabled", False),
    ("ai_voice_reply_enabled", False),
    ("ai_voice_reply_speaker", False),
    ("ai_media_recommendations_enabled", False),
    ("catalog_ai_max_images_ceiling", False),
]


class CreateClientPayload(BaseModel):
    company_name: str
    business_type: str
    contact_name: str
    contact_phone: str
    billing_region: str | None = None
    email: EmailStr
    password: str


class UpdateFeaturesPayload(BaseModel):
    features: list[str] | None = None


@router.patch("/clients/{tenant_id}/features")
def update_features(tenant_id: str, payload: UpdateFeaturesPayload, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()

    features: list[str] | None = None
    if payload.features is None:
        raise HTTPException(status_code=400, detail="Provide 'features'")

    update: dict = {}
    # Upload is a separately-purchasable SKU (bulk_lead_upload) unrelated to the
    # telecalling_sim/telecalling_telecmi bundle, so it's excluded from this
    # cascade — the master "telecalling" switch only bundles dialer/scheduled/notes.
    tc_bundle_subs = {"telecalling.dialer", "telecalling.scheduled", "telecalling.notes"}
    features = list(payload.features)
    if "telecalling" in features and not (set(features) & tc_bundle_subs):
        features.extend(tc_bundle_subs)
    if "telecalling" not in features:
        features = [f for f in features if f not in tc_bundle_subs]
    update["enabled_features"] = features

    result = db.table("tenants").update(update).eq("id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Tenant not found")
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.features_updated",
        target_type="tenant",
        target_id=tenant_id,
        metadata={"features": features},
    )
    return {"tenant_id": tenant_id, "enabled_features": features or []}


@router.post("/clients/{tenant_id}/reset-password")
async def reset_password(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    owner = (
        db.table("tenant_users")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("role", "owner")
        .maybe_single()
        .execute()
    )
    if not owner.data:
        raise HTTPException(status_code=404, detail="No owner found for this tenant")
    temp_pw = "Anril@" + secrets.token_urlsafe(10)
    db.auth.admin.update_user_by_id(owner.data["user_id"], {"password": temp_pw})
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.password_reset",
        target_type="tenant_owner",
        target_id=owner.data["user_id"],
        metadata={"tenant_id": tenant_id},
    )
    return {"temp_password": temp_pw}


@router.get("/clients")
def list_clients(_admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    clients = db.table("tenants").select(
        "id, name, enabled_features, status, created_at"
    ).execute()
    result = []
    for c in (clients.data or []):
        try:
            owner = (
                db.table("tenant_users")
                .select("user_id")
                .eq("tenant_id", c["id"])
                .eq("role", "owner")
                .maybe_single()
                .execute()
            )
        except Exception:
            # A tenant with a malformed tenant_users state (e.g. more than
            # one "owner" row) must not take down the whole client list —
            # just show that tenant without an owner email.
            owner = None
        owner_email = None
        if owner and owner.data and owner.data.get("user_id"):
            try:
                user = db.auth.admin.get_user_by_id(owner.data["user_id"])
                owner_email = user.user.email if hasattr(user, "user") else None
            except Exception:
                pass
        result.append({
            "id": c["id"],
            "name": c["name"],
            "enabled_features": c.get("enabled_features", []) or [],
            "status": c.get("status", "active"),
            "created_at": c.get("created_at"),
            "owner_user_id": owner_email,
        })
    return {"data": result}


@router.post("/clients")
def create_client(payload: CreateClientPayload, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    
    # Create auth user
    user = db.auth.admin.create_user({
        "email": payload.email,
        "password": payload.password,
        "email_confirm": True,
    })
    user_id = user.user.id if hasattr(user, "user") else None
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create user")

    tenant_id = None
    try:
        # Create tenant
        tenant = db.table("tenants").insert({
            "name": payload.company_name,
            "status": "active",
            "business_type": payload.business_type,
            "contact_name": payload.contact_name,
            "contact_phone": payload.contact_phone,
            "billing_region": payload.billing_region,
        }).execute()
        tenant_id = tenant.data[0]["id"] if tenant.data else None

        # Create tenant user (owner)
        db.table("tenant_users").insert({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": "owner",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        # Seed app_settings
        db.table("app_settings").insert([
            {"tenant_id": tenant_id, "key": k, "value": None, "is_secret": s}
            for k, s in _SETTING_KEYS
        ]).execute()

        # No master prompt is seeded here. The master prompt is platform-wide: every
        # tenant reads the one row in platform_defaults at reply time, so there is
        # nothing per-tenant to copy.

        # No tenant_subscriptions row is created here — the new tenant starts
        # gated (status effectively "none") until they submit a subscription
        # cart from the client-facing Subscriptions page and an admin
        # approves it (see app/services/subscription_requests.py).

        # Seed default caller
        db.table("callers").insert({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "name": payload.contact_name,
            "active": True,
            "status": "active",
        }).execute()
    except Exception as e:
        logger.error(f"Tenant setup failed for user {user_id}, cleaning up: {e}")
        if tenant_id:
            # Best-effort: subscriptions/usage counters cascade via `on delete cascade`,
            # but tenant_users/app_settings/callers may not, so clean those up explicitly.
            try:
                db.table("tenants").delete().eq("id", tenant_id).execute()
            except Exception as cleanup_err:
                logger.error(f"Failed to delete orphaned tenant {tenant_id}: {cleanup_err}")
            try:
                db.table("tenant_users").delete().eq("tenant_id", tenant_id).execute()
            except Exception as cleanup_err:
                logger.error(f"Failed to delete orphaned tenant_users for {tenant_id}: {cleanup_err}")
            try:
                db.table("app_settings").delete().eq("tenant_id", tenant_id).execute()
            except Exception as cleanup_err:
                logger.error(f"Failed to delete orphaned app_settings for {tenant_id}: {cleanup_err}")
            try:
                db.table("callers").delete().eq("tenant_id", tenant_id).execute()
            except Exception as cleanup_err:
                logger.error(f"Failed to delete orphaned callers for {tenant_id}: {cleanup_err}")
        try:
            db.auth.admin.delete_user(user_id)
        except Exception as cleanup_err:
            logger.error(f"Failed to delete orphaned auth user {user_id}: {cleanup_err}")
        raise HTTPException(status_code=500, detail="Client setup failed; user account cleaned up.")

    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.client_created",
        target_type="tenant",
        target_id=tenant_id,
        metadata={
            "company_name": payload.company_name,
            "business_type": payload.business_type,
            "billing_region": payload.billing_region,
        },
    )

    return {"tenant_id": tenant_id, "user_id": user_id}


@router.get("/features/catalog")
def get_features_catalog(_admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    catalog = execute_with_retry(
        db.table("feature_catalog").select(
            "feature_key, display_name, category, pillar, monthly_price, unit_price, is_metered, usage_metric, included_qty"
        ).order("category").order("sort_order")
    )
    return {"data": catalog.data or []}


def compute_fleet_health(
    *,
    ai_usage: int,
    near_cap: bool,
    no_activity_14d: bool,
    token_expired: bool = False,
    channel_unhealthy: bool = False,
) -> str:
    """Pure, DB-free health scoring for a fleet client.

    Tiers (first match wins):
      - critical: ai_usage >= 100, or a messaging token has expired/is unset,
        or a configured channel is unhealthy.
      - warning: near_cap (ai_usage >= 80) or no activity in 14 days while active.
      - healthy: otherwise.
    """
    if ai_usage >= 100 or token_expired or channel_unhealthy:
        return "critical"
    if near_cap or no_activity_14d:
        return "warning"
    return "healthy"


_META_CHANNELS = {"whatsapp", "instagram", "facebook"}


def has_required_tokens(enabled_features: set, settings_keys: dict) -> bool:
    """Pure check: does this tenant have every token required by the
    messaging channels it has enabled?

    `settings_keys` maps app_settings key -> truthy-value-present bool, e.g.
    {"meta_access_token": True, "telegram_bot_token": False}. Meta-family
    channels (whatsapp/instagram/facebook) are all satisfied by
    `meta_access_token`; telegram needs its own `telegram_bot_token`.
    Channels outside this messaging set (e.g. telecalling) are ignored.
    """
    if enabled_features & _META_CHANNELS and not settings_keys.get("meta_access_token"):
        return False
    if "telegram" in enabled_features and not settings_keys.get("telegram_bot_token"):
        return False
    return True


def _build_fleet_rows(db) -> list[dict]:
    """Fetch and score every tenant's fleet-health row.

    Shared by `GET /fleet` (the Fleet Cockpit table) and `GET /alerts` (the
    operator alert center), so both surface the exact same signals instead of
    running the queries twice.
    """
    from datetime import timedelta

    tenants = db.table("tenants").select(
        "id, name, enabled_features, status, created_at"
    ).execute()

    tenant_ids = [t["id"] for t in (tenants.data or [])]

    subscriptions: dict = {}
    period_by_tenant: dict = {}
    if tenant_ids:
        subs = db.table("tenant_subscriptions").select(
            "tenant_id, mrr, period_start, period_end"
        ).in_("tenant_id", tenant_ids).execute()
        for s in (subs.data or []):
            subscriptions[s["tenant_id"]] = s
            # Pure calculation only (no rollover write) — this is a bulk list
            # view, so lazily resetting counters as a side effect of a GET
            # would be surprising; that happens on the tenant's own reads
            # (check_quota/increment_usage/`/me`) instead.
            period_by_tenant[s["tenant_id"]] = compute_period_key(s.get("period_start"), s.get("period_end"))

    counters_by_tenant: dict = {}
    if tenant_ids:
        distinct_periods = list(set(period_by_tenant.values())) or [datetime.now(timezone.utc).strftime("%Y-%m")]
        counters = db.table("tenant_usage_counters").select(
            "tenant_id, period, metric, used, included"
        ).in_("tenant_id", tenant_ids).in_("period", distinct_periods).execute()
        for c in (counters.data or []):
            tid = c["tenant_id"]
            if c["period"] != period_by_tenant.get(tid, c["period"]):
                continue
            if tid not in counters_by_tenant:
                counters_by_tenant[tid] = {}
            counters_by_tenant[tid][c["metric"]] = {
                "used": c["used"] or 0,
                "included": c["included"] or 0,
            }

    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    fourteen_days_ago = now - timedelta(days=14)

    # Fleet-wide token health: two bulk queries (not per-tenant), same batching
    # pattern as subscriptions/counters above. Per-channel health (as derived by
    # GET /clients/{tenant_id}/health) needs 4 queries per tenant and is deferred —
    # doing that for every fleet row would turn this endpoint into an N*4 fan-out.
    # channel_unhealthy is therefore always False here for now.
    token_incident_tenant_ids: set = set()
    tenant_settings_keys: dict = {}
    if tenant_ids:
        incident_cutoff = (now - timedelta(hours=48)).isoformat()
        incidents = db.table("incidents").select(
            "tenant_id"
        ).in_("tenant_id", tenant_ids).eq("type", "token_invalid").gte(
            "created_at", incident_cutoff
        ).execute()
        token_incident_tenant_ids = {i["tenant_id"] for i in (incidents.data or [])}

        settings_rows = db.table("app_settings").select(
            "tenant_id, key, value"
        ).in_("tenant_id", tenant_ids).in_(
            "key", ["meta_access_token", "telegram_bot_token"]
        ).execute()
        for r in (settings_rows.data or []):
            if r.get("value"):
                tenant_settings_keys.setdefault(r["tenant_id"], {})[r["key"]] = True

    msg_counts: dict = {}
    last_activity_by_tenant: dict = {}
    for tid in tenant_ids:
        count_res = db.table("messages").select(
            "id", count="exact"
        ).eq("tenant_id", tid).eq("direction", "outbound").gte("created_at", thirty_days_ago).execute()
        msg_counts[tid] = count_res.count or 0

        last_msg = db.table("messages").select(
            "created_at"
        ).eq("tenant_id", tid).order("created_at", desc=True).limit(1).execute()
        last_activity_by_tenant[tid] = (last_msg.data or [{}])[0].get("created_at")

    result = []
    for t in (tenants.data or []):
        tid = t["id"]
        ai_reply_counter = counters_by_tenant.get(tid, {}).get("ai_reply", {"used": 0, "included": 0})
        ai_used = ai_reply_counter.get("used", 0)
        ai_included = ai_reply_counter.get("included", 0)
        ai_usage = round(ai_used / ai_included * 100) if ai_included > 0 else 0
        sub = subscriptions.get(tid, {})
        mrr = sub.get("mrr", 0) or 0
        msgs = msg_counts.get(tid, 0)
        status = t.get("status", "active")
        last_activity = last_activity_by_tenant.get(tid)

        near_cap = ai_usage >= 80
        no_activity_14d = status == "active" and (
            last_activity is None
            or datetime.fromisoformat(last_activity.replace("Z", "+00:00")) < fourteen_days_ago
        )
        # Only flag a missing/expired messaging token when the client has WhatsApp
        # (or another messaging channel) enabled — tenants that never set one up
        # aren't "expired", they're simply not using it. Meta-family channels
        # (whatsapp/instagram/facebook) share meta_access_token; telegram has its
        # own telegram_bot_token — see has_required_tokens().
        enabled_features = set(t.get("enabled_features", []) or [])
        messaging_enabled = bool(enabled_features & {"whatsapp", "instagram", "facebook", "telegram"})
        token_expired = messaging_enabled and (
            tid in token_incident_tenant_ids
            or not has_required_tokens(enabled_features, tenant_settings_keys.get(tid, {}))
        )
        channel_unhealthy = False

        health = compute_fleet_health(
            ai_usage=ai_usage,
            near_cap=near_cap,
            no_activity_14d=no_activity_14d,
            token_expired=token_expired,
            channel_unhealthy=channel_unhealthy,
        )

        result.append({
            "id": tid,
            "name": t["name"],
            "enabled_features": t.get("enabled_features", []) or [],
            "status": status,
            "created_at": t.get("created_at"),
            "mrr": mrr,
            "messages_30d": msgs,
            "ai_usage": ai_usage,
            "health": health,
            "last_activity": last_activity,
            "near_cap": near_cap,
            "no_activity_14d": no_activity_14d,
            "token_expired": token_expired,
            "channel_unhealthy": channel_unhealthy,
        })

    return result


class PlanItem(BaseModel):
    feature_key: str
    quantity: int = 1


class PlanPayload(BaseModel):
    name: str
    discount_percent: float = 0
    items: list[PlanItem] = []


@router.get("/plans")
def list_plans(_admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    plans = db.table("plans").select(
        "id, name, monthly_price, feature_keys, discount_percent, active, created_at"
    ).eq("active", True).order("created_at").execute()
    return {"data": plans.data or []}


def _compute_package_price(db, items: list[dict], discount_percent: float) -> float:
    """
    Sum each item's price, then apply the package discount. Flat-priced SKUs
    always cost their full monthly_price regardless of quantity. Quantity-
    priced items (telecaller_seats, numbers_pool) have monthly_price=0 and
    bill only units beyond included_qty via unit_price — mirrors
    `_price_for_item` in subscription_requests.py (with no prior purchase to
    net out, since a package is a catalog template, not tied to a tenant) so
    a package's price never diverges from what an equivalent à la carte cart
    would total.
    """
    feature_keys = [i["feature_key"] for i in items]
    if not feature_keys:
        return 0.0
    catalog = db.table("feature_catalog").select("feature_key, monthly_price, unit_price, included_qty").in_("feature_key", feature_keys).execute()
    catalog_by_key = {row["feature_key"]: row for row in (catalog.data or [])}
    subtotal = 0.0
    for item in items:
        row = catalog_by_key.get(item["feature_key"], {})
        quantity = item.get("quantity", 1)
        monthly_price = float(row.get("monthly_price") or 0)
        if monthly_price > 0:
            subtotal += monthly_price
            continue
        unit_price = row.get("unit_price")
        if unit_price is None:
            continue
        included_qty = row.get("included_qty")
        billable_units = quantity if included_qty is None else max(0, quantity - included_qty)
        subtotal += float(unit_price) * billable_units
    return subtotal * (1 - discount_percent / 100)


@router.post("/plans")
def create_plan(payload: PlanPayload, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    items = [i.model_dump() for i in payload.items]
    price = _compute_package_price(db, items, payload.discount_percent)
    plan = db.table("plans").insert({
        "name": payload.name,
        "monthly_price": price,
        "feature_keys": items,
        "discount_percent": payload.discount_percent,
    }).execute()
    created = plan.data[0] if plan.data else None
    record_audit_event(
        db,
        tenant_id=None,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.plan_created",
        target_type="plan",
        target_id=created["id"] if created else None,
        metadata={"name": payload.name, "monthly_price": price},
    )
    return {"data": created}


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: str, payload: PlanPayload, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    existing = db.table("plans").select("id").eq("id", plan_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Plan not found")

    items = [i.model_dump() for i in payload.items]
    price = _compute_package_price(db, items, payload.discount_percent)
    plan = db.table("plans").update({
        "name": payload.name,
        "monthly_price": price,
        "feature_keys": items,
        "discount_percent": payload.discount_percent,
    }).eq("id", plan_id).execute()
    record_audit_event(
        db,
        tenant_id=None,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.plan_updated",
        target_type="plan",
        target_id=plan_id,
        metadata={"name": payload.name, "monthly_price": price},
    )
    return {"data": plan.data[0] if plan.data else None}


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    existing = db.table("plans").select("id, name").eq("id", plan_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Plan not found")

    db.table("plans").update({"active": False}).eq("id", plan_id).execute()
    record_audit_event(
        db,
        tenant_id=None,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.plan_deleted",
        target_type="plan",
        target_id=plan_id,
        metadata={"name": existing.data.get("name")},
    )
    return {"deleted": True, "plan_id": plan_id}


class CatalogPricingPayload(BaseModel):
    monthly_price: float | None = None
    unit_price: float | None = None
    included_qty: int | None = None


@router.patch("/catalog/{feature_key}")
def update_catalog_pricing(feature_key: str, payload: CatalogPricingPayload, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    existing = db.table("feature_catalog").select("feature_key").eq("feature_key", feature_key).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Catalog item not found")

    update = {
        key: getattr(payload, key)
        for key in payload.model_fields_set
        if key in {"monthly_price", "unit_price", "included_qty"}
    }
    result = db.table("feature_catalog").update(update).eq("feature_key", feature_key).execute()
    record_audit_event(
        db,
        tenant_id=None,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.catalog_pricing_updated",
        target_type="feature_catalog",
        target_id=feature_key,
        metadata=update,
    )
    return {"data": result.data[0] if result.data else None}


@router.get("/subscription-requests")
def list_subscription_requests(status: str | None = None, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    query = db.table("subscription_requests").select(
        "id, tenant_id, status, requested_items, package_id, total_amount, is_initial, payment_confirmed, submitted_at, start_date, end_date"
    ).order("submitted_at", desc=True)
    if status:
        query = query.eq("status", status)
    result = query.execute()
    rows = result.data or []

    tenant_ids = list({r["tenant_id"] for r in rows})
    names_by_id: dict[str, str] = {}
    if tenant_ids:
        tenants = db.table("tenants").select("id, name").in_("id", tenant_ids).execute()
        names_by_id = {t["id"]: t["name"] for t in (tenants.data or [])}

    for r in rows:
        r["tenant_name"] = names_by_id.get(r["tenant_id"], "Unknown")

    return {"data": rows}


class ReviewRequestPayload(BaseModel):
    action: Literal["approve", "reject"]
    payment_confirmed: bool = False
    rejection_reason: str | None = None


@router.patch("/subscription-requests/{request_id}")
def review_subscription_request(request_id: str, payload: ReviewRequestPayload, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()

    if payload.action == "approve":
        if not payload.payment_confirmed:
            raise HTTPException(status_code=400, detail="Confirm payment received before approving")
        result = approve_request(db, request_id, reviewer_user_id=_admin.get("user_id"))
    else:
        if not payload.rejection_reason:
            raise HTTPException(status_code=400, detail="A rejection reason is required")
        result = reject_request(db, request_id, reviewer_user_id=_admin.get("user_id"), reason=payload.rejection_reason)

    record_audit_event(
        db,
        tenant_id=None,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action=f"operator.subscription_request_{payload.action}d",
        target_type="subscription_request",
        target_id=request_id,
        metadata={"payment_confirmed": payload.payment_confirmed, "rejection_reason": payload.rejection_reason},
    )
    return {"data": result}


class UpdateStatusPayload(BaseModel):
    status: Literal["active", "suspended"]


class CallingProviderPayload(BaseModel):
    calling_provider: Literal["telecmi", "sim_basic"]


@router.patch("/clients/{tenant_id}/status")
def update_status(tenant_id: str, payload: UpdateStatusPayload, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    current = db.table("tenants").select("status").eq("id", tenant_id).maybe_single().execute()
    result = db.table("tenants").update({"status": payload.status}).eq("id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Tenant not found")
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.status_updated",
        target_type="tenant",
        target_id=tenant_id,
        metadata={"old_status": (current.data or {}).get("status"), "new_status": payload.status},
    )
    return {"tenant_id": tenant_id, "status": payload.status}


@router.get("/clients/{tenant_id}/calling-provider")
def get_calling_provider(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("id, enabled_features").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")
    cfg = get_telecalling_config(tenant_id)
    return {
        "tenant_id": tenant_id,
        "calling_provider": cfg.get("calling_provider", "telecmi"),
        "telecalling_enabled": "telecalling" in (tenant.data.get("enabled_features") or []),
    }


@router.patch("/clients/{tenant_id}/calling-provider")
def update_calling_provider(
    tenant_id: str,
    payload: CallingProviderPayload,
    _admin: dict = Depends(get_system_admin),
):
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    current = get_telecalling_config(tenant_id)
    old_provider = current.get("calling_provider", "telecmi")
    merged = {**current, "calling_provider": payload.calling_provider}
    save_telecalling_config(tenant_id, merged)
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.calling_provider_updated",
        target_type="tenant",
        target_id=tenant_id,
        metadata={"old_provider": old_provider, "new_provider": payload.calling_provider},
    )
    return {"tenant_id": tenant_id, "calling_provider": payload.calling_provider}


# ---------------------------------------------------------------- private send

class PrivateSendSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply_mode: Literal["client", "aira"] | None = None
    offline_grace_hours: int | None = Field(default=None, ge=1, le=72)
    monthly_cap: int | None = Field(default=None, ge=0)  # null clears the cap


def _require_tenant(db, tenant_id: str) -> None:
    rows = db.table("tenants").select("id").eq("id", tenant_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Tenant not found")


def _audit_private_send(db, admin: dict, tenant_id: str, action: str, target_id: str, metadata: dict) -> None:
    # Never put a key in here. The full key exists only in the create response.
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=admin.get("user_id"),
        actor_role="system_admin",
        action=action,
        target_type="private_send",
        target_id=target_id,
        metadata=metadata,
    )


@router.get("/clients/{tenant_id}/private-send")
def get_private_send(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    _require_tenant(db, tenant_id)
    return private_send_svc.operator_overview(db, tenant_id)


@router.post("/clients/{tenant_id}/private-send/keys")
def create_private_send_key(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    _require_tenant(db, tenant_id)
    try:
        created = private_send_svc.create_key(db, tenant_id)
    except private_send_svc.PrivateSendError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    _audit_private_send(
        db, _admin, tenant_id, "operator.private_send_key_created", created["id"],
        {"prefix": created["key_prefix"]},
    )
    return created


@router.delete("/clients/{tenant_id}/private-send/keys/{key_id}")
def revoke_private_send_key(tenant_id: str, key_id: UUID, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    try:
        private_send_svc.revoke_key(db, tenant_id, str(key_id))
    except private_send_svc.PrivateSendError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    _audit_private_send(db, _admin, tenant_id, "operator.private_send_key_revoked", str(key_id), {})
    return {"ok": True}


@router.patch("/clients/{tenant_id}/private-send/settings")
async def update_private_send_settings(
    tenant_id: str,
    payload: PrivateSendSettingsPayload,
    _admin: dict = Depends(get_system_admin),
):
    db = get_supabase()
    _require_tenant(db, tenant_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change")
    try:
        await private_send_svc.update_settings(db, tenant_id, changes)
    except private_send_svc.PrivateSendError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    _audit_private_send(db, _admin, tenant_id, "operator.private_send_settings_updated", tenant_id, changes)
    return private_send_svc.operator_overview(db, tenant_id)


@router.get("/clients/{tenant_id}/entitlements")
def get_client_entitlements(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    items = db.table("tenant_subscription_items").select(
        "feature_key, quantity, unit_price_snapshot"
    ).eq("tenant_id", tenant_id).execute()
    sub = db.table("tenant_subscriptions").select(
        "status, period_start, period_end"
    ).eq("tenant_id", tenant_id).maybe_single().execute()
    # maybe_single().execute() returns None outright (not an object with
    # `.data = None`) on zero rows — the norm for a tenant that's never
    # submitted a cart yet.
    sub_data = (sub.data if sub else None) or {}
    return {
        "data": {
            "items": items.data or [],
            "status": sub_data.get("status", "none"),
            "period_start": sub_data.get("period_start"),
            "period_end": sub_data.get("period_end"),
        }
    }


@router.get("/clients/{tenant_id}/usage")
def get_client_usage(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()

    period = get_billing_period(db, tenant_id)

    counters = db.table("tenant_usage_counters").select(
        "metric, used, included, hard_cap"
    ).eq("tenant_id", tenant_id).eq("period", period).execute()
    
    return {"data": counters.data or [], "period": period}


@router.get("/clients/{tenant_id}/token-usage")
def get_client_token_usage(
    tenant_id: str,
    range_days: int = 30,
    all_time: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
    _admin: dict = Depends(get_system_admin),
):
    """Per-tenant LLM token consumption (migration 142), broken down by feature
    and model plus a daily series for the trend chart. all_time=true skips the
    date filter entirely (range_days is then ignored). Small row volume per
    tenant (one row per day/purpose/provider/model) -- aggregated in Python
    rather than a dedicated SQL rollup. Estimated cost (migration 143's
    admin-set rate card) is None per row/group when no rate is configured for
    that (provider, model) -- never silently treated as ₹0.

    from_date/to_date (YYYY-MM-DD, both required together) select a custom,
    inclusive range and take priority over range_days/all_time -- same
    contract as the fleet endpoint's custom range."""
    db = get_supabase()

    query = db.table("tenant_token_usage").select(
        "usage_date, purpose, provider, model, calls, input_tokens, output_tokens"
    ).eq("tenant_id", tenant_id)

    if from_date and to_date:
        try:
            from_d = datetime.fromisoformat(from_date).date()
            to_d = datetime.fromisoformat(to_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date/to_date must be YYYY-MM-DD")
        if to_d < from_d:
            raise HTTPException(status_code=400, detail="to_date must be on or after from_date")
        query = query.gte("usage_date", from_d.isoformat()).lt("usage_date", (to_d + timedelta(days=1)).isoformat())
    elif not all_time:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=range_days)).date().isoformat()
        query = query.gte("usage_date", cutoff)

    rows = query.execute().data or []
    rates = get_rates(db)

    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0}
    by_feature: dict[str, dict] = {}
    by_model: dict[tuple[str, str], dict] = {}
    by_day: dict[str, dict] = {}
    unrated_models: set[tuple[str, str]] = set()
    any_unrated = False

    for r in rows:
        calls, in_tok, out_tok = r["calls"], r["input_tokens"], r["output_tokens"]
        row_cost = estimate_cost(rates, r["provider"], r["model"], in_tok, out_tok)
        if row_cost is None:
            unrated_models.add((r["provider"], r["model"]))
            any_unrated = True

        totals["calls"] += calls
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        if row_cost is not None:
            totals["estimated_cost"] += row_cost

        feat = by_feature.setdefault(r["purpose"], {"purpose": r["purpose"], "calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "has_unrated": False})
        feat["calls"] += calls
        feat["input_tokens"] += in_tok
        feat["output_tokens"] += out_tok
        if row_cost is not None:
            feat["estimated_cost"] += row_cost
        else:
            feat["has_unrated"] = True

        model_key = (r["provider"], r["model"])
        model_row = by_model.setdefault(model_key, {"provider": r["provider"], "model": r["model"], "calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "has_unrated": False})
        model_row["calls"] += calls
        model_row["input_tokens"] += in_tok
        model_row["output_tokens"] += out_tok
        if row_cost is not None:
            model_row["estimated_cost"] += row_cost
        else:
            model_row["has_unrated"] = True

        day = by_day.setdefault(r["usage_date"], {"date": r["usage_date"], "input_tokens": 0, "output_tokens": 0})
        day["input_tokens"] += in_tok
        day["output_tokens"] += out_tok

    return {
        "data": {
            "totals": {**totals, "has_unrated": any_unrated},
            "by_feature": sorted(by_feature.values(), key=lambda x: x["input_tokens"] + x["output_tokens"], reverse=True),
            "by_model": sorted(by_model.values(), key=lambda x: x["input_tokens"] + x["output_tokens"], reverse=True),
            "daily": sorted(by_day.values(), key=lambda x: x["date"]),
            "unrated_models": [{"provider": p, "model": m} for p, m in sorted(unrated_models)],
        },
        "range_days": None if (all_time or (from_date and to_date)) else range_days,
    }


class ProviderRateUpsert(BaseModel):
    provider: str
    model: str
    input_rate_per_1k_inr: float
    output_rate_per_1k_inr: float


@router.get("/provider-rates")
def list_provider_rates(_admin: dict = Depends(get_system_admin)):
    """Configured rates (migration 143) plus every (provider, model) pair ever
    recorded in tenant_token_usage that still has no rate -- the rate-
    management screen's todo list. DISTINCT is computed in Postgres (migration
    144's RPC), not via a plain SELECT + Python set(), to avoid silently
    missing pairs if the table grows past a REST page size."""
    db = get_supabase()
    configured = db.table("provider_model_rates").select(
        "provider, model, input_rate_per_1k_inr, output_rate_per_1k_inr, updated_at"
    ).execute().data or []
    configured_keys = {(r["provider"], r["model"]) for r in configured}

    seen = db.rpc("distinct_token_usage_pairs", {}).execute().data or []
    missing = sorted({(r["provider"], r["model"]) for r in seen} - configured_keys)

    return {
        "data": {
            "configured": configured,
            "missing": [{"provider": p, "model": m} for p, m in missing],
        }
    }


@router.put("/provider-rates")
def set_provider_rate(payload: ProviderRateUpsert, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    upsert_rate(db, payload.provider, payload.model, payload.input_rate_per_1k_inr, payload.output_rate_per_1k_inr)
    return {"data": {"status": "ok"}}


def _aggregate_token_rows(rows: list[dict], rates: dict) -> dict:
    """Shared aggregation core for the fleet endpoint -- run once on the
    current window and once on the prior window (for trend deltas)."""
    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "has_unrated": False}
    by_provider: dict[str, dict] = {}
    by_feature: dict[str, dict] = {}
    by_client: dict[str, dict] = {}
    by_day: dict[str, dict] = {}

    for r in rows:
        calls, in_tok, out_tok = r["calls"], r["input_tokens"], r["output_tokens"]
        cost = estimate_cost(rates, r["provider"], r["model"], in_tok, out_tok)

        totals["calls"] += calls
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        if cost is not None:
            totals["estimated_cost"] += cost
        else:
            totals["has_unrated"] = True

        for bucket, key in ((by_provider, r["provider"]), (by_feature, r["purpose"]), (by_client, r["tenant_id"])):
            entry = bucket.setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0, "has_unrated": False})
            entry["calls"] += calls
            entry["input_tokens"] += in_tok
            entry["output_tokens"] += out_tok
            if cost is not None:
                entry["estimated_cost"] += cost
            else:
                entry["has_unrated"] = True

        day = by_day.setdefault(r["usage_date"], {"date": r["usage_date"]})
        day[r["provider"]] = day.get(r["provider"], 0) + in_tok + out_tok

    return {
        "totals": totals,
        "by_provider": by_provider,
        "by_feature": by_feature,
        "by_client": by_client,
        "by_day": by_day,
    }


def _pct_trend(current: int, prior: int) -> float | None:
    """None when there's no meaningful baseline (all-time view, or the prior
    window had zero activity) -- a client that went from 0 to any usage isn't
    a "% increase," it's new, and dividing by zero would misrepresent that."""
    if prior <= 0:
        return None
    return round((current - prior) / prior * 100)


@router.get("/token-usage/fleet")
def get_fleet_token_usage(
    range_days: int = 90,
    all_time: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
    _admin: dict = Depends(get_system_admin),
):
    """Cross-tenant token/cost view (migration 142 aggregated across every
    tenant) -- the "who is costing me the most" leaderboard, since Anril funds
    every provider account rather than the tenant. Computes a trend by also
    aggregating the immediately-preceding, equal-length window; skipped
    entirely for all_time (no meaningful "prior all-time" baseline).

    from_date/to_date (YYYY-MM-DD, both required together) select a custom,
    inclusive range and take priority over range_days/all_time."""
    db = get_supabase()
    rates = get_rates(db)

    def fetch(gte_date: str | None, lt_date: str | None = None) -> list[dict]:
        q = db.table("tenant_token_usage").select(
            "tenant_id, usage_date, purpose, provider, model, calls, input_tokens, output_tokens"
        )
        if gte_date is not None:
            q = q.gte("usage_date", gte_date)
        if lt_date is not None:
            q = q.lt("usage_date", lt_date)
        return q.execute().data or []

    if from_date and to_date:
        try:
            from_d = datetime.fromisoformat(from_date).date()
            to_d = datetime.fromisoformat(to_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date/to_date must be YYYY-MM-DD")
        if to_d < from_d:
            raise HTTPException(status_code=400, detail="to_date must be on or after from_date")
        window_days = (to_d - from_d).days + 1
        rows = fetch(from_d.isoformat(), (to_d + timedelta(days=1)).isoformat())
        prior_from = from_d - timedelta(days=window_days)
        prior = _aggregate_token_rows(fetch(prior_from.isoformat(), from_d.isoformat()), rates)
    elif all_time:
        rows = fetch(None)
        prior = None
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=range_days)).date()
        prior_cutoff = cutoff - timedelta(days=range_days)
        rows = fetch(cutoff.isoformat())
        prior = _aggregate_token_rows(fetch(prior_cutoff.isoformat(), cutoff.isoformat()), rates)

    current = _aggregate_token_rows(rows, rates)

    tenant_ids = list(current["by_client"].keys())
    tenant_names: dict[str, str] = {}
    if tenant_ids:
        trows = db.table("tenants").select("id, name").in_("id", tenant_ids).execute().data or []
        tenant_names = {t["id"]: t["name"] for t in trows}

    total_clients_row = db.table("tenants").select("id", count="exact").execute()
    total_clients = total_clients_row.count or 0

    cur_total_tokens = current["totals"]["input_tokens"] + current["totals"]["output_tokens"]
    prior_total_tokens = (prior["totals"]["input_tokens"] + prior["totals"]["output_tokens"]) if prior else 0
    fleet_trend_pct = None if all_time else _pct_trend(cur_total_tokens, prior_total_tokens)

    leaderboard = []
    for tid, c in current["by_client"].items():
        cur_tok = c["input_tokens"] + c["output_tokens"]
        prior_c = prior["by_client"].get(tid) if prior else None
        prior_tok = (prior_c["input_tokens"] + prior_c["output_tokens"]) if prior_c else 0
        leaderboard.append({
            "tenant_id": tid,
            "tenant_name": tenant_names.get(tid, tid),
            "calls": c["calls"],
            "input_tokens": c["input_tokens"],
            "output_tokens": c["output_tokens"],
            "estimated_cost": c["estimated_cost"],
            "has_unrated": c["has_unrated"],
            "share_of_fleet": (cur_tok / cur_total_tokens) if cur_total_tokens > 0 else 0.0,
            "trend_pct": None if all_time else _pct_trend(cur_tok, prior_tok),
        })
    leaderboard.sort(key=lambda x: x["input_tokens"] + x["output_tokens"], reverse=True)

    return {
        "data": {
            "totals": {**current["totals"], "trend_pct": fleet_trend_pct},
            "active_clients": len(current["by_client"]),
            "total_clients": total_clients,
            "by_provider": sorted(
                [{"provider": p, **v} for p, v in current["by_provider"].items()],
                key=lambda x: x["input_tokens"] + x["output_tokens"], reverse=True,
            ),
            "by_feature": sorted(
                [{"purpose": p, **v} for p, v in current["by_feature"].items()],
                key=lambda x: x["input_tokens"] + x["output_tokens"], reverse=True,
            ),
            "daily": sorted(current["by_day"].values(), key=lambda x: x["date"]),
            "leaderboard": leaderboard,
        },
        "range_days": None if (all_time or (from_date and to_date)) else range_days,
    }


@router.get("/clients/{tenant_id}/overview")
def client_overview(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    from datetime import datetime, timezone, timedelta
    db = get_supabase()

    tenant = db.table("tenants").select("id, name, status, enabled_features, created_at, plan").eq("id", tenant_id).maybe_single().execute()
    if not tenant or not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    owner_row = (
        db.table("tenant_users")
        .select("user_id, created_at")
        .eq("tenant_id", tenant_id)
        .eq("role", "owner")
        .maybe_single()
        .execute()
    )
    owner_info: dict = {"user_id": None, "email": None, "created_at": None}
    if owner_row and owner_row.data:
        owner_info["user_id"] = owner_row.data["user_id"]
        owner_info["created_at"] = owner_row.data["created_at"]
        try:
            user = db.auth.admin.get_user_by_id(owner_row.data["user_id"])
            owner_info["email"] = user.user.email if hasattr(user, "user") else None
        except Exception:
            pass

    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    total_leads = db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).is_("deleted_at", "null").execute()
    active_leads = (
        db.table("leads").select("id", count="exact")
        .eq("tenant_id", tenant_id).is_("deleted_at", "null")
        .in_("segment", ["A", "B"])
        .execute()
    )
    msgs_sent = (
        db.table("messages").select("id", count="exact")
        .eq("tenant_id", tenant_id).eq("direction", "outbound")
        .gte("created_at", thirty_days_ago)
        .execute()
    )
    msgs_recv = (
        db.table("messages").select("id", count="exact")
        .eq("tenant_id", tenant_id).eq("direction", "inbound")
        .gte("created_at", thirty_days_ago)
        .execute()
    )
    team_count = db.table("callers").select("id", count="exact").eq("tenant_id", tenant_id).execute()

    last_msg = (
        db.table("messages").select("created_at")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True).limit(1).execute()
    )
    last_call = (
        db.table("call_logs").select("created_at")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True).limit(1).execute()
    )
    last_msg_ts = (last_msg.data or [{}])[0].get("created_at")
    last_call_ts = (last_call.data or [{}])[0].get("created_at")
    last_activity = max(filter(None, [last_msg_ts, last_call_ts]), default=None)

    return {
        "tenant": tenant.data,
        "owner": owner_info,
        "stats": {
            "total_leads": total_leads.count or 0,
            "active_leads": active_leads.count or 0,
            "messages_sent_30d": msgs_sent.count or 0,
            "messages_received_30d": msgs_recv.count or 0,
            "team_members": team_count.count or 0,
            "last_activity": last_activity,
        },
    }


class PromptTemplateUpdate(BaseModel):
    template: str


@router.get("/prompt-template")
def read_prompt_template(_admin: dict = Depends(get_system_admin)):
    from app.services.ai_reply import get_master_prompt
    return {"template": get_master_prompt()}


@router.put("/prompt-template")
def write_prompt_template(
    payload: PromptTemplateUpdate, _admin: dict = Depends(get_system_admin)
):
    """Edits the prompt every tenant runs on, live. There is no per-client copy to
    update afterwards -- replies pick this up as soon as the cache is invalidated."""
    db = get_supabase()
    db.table("platform_defaults").upsert(
        {"key": "default_master_prompt", "value": payload.template},
        on_conflict="key",
    ).execute()
    from app.services.ai_reply import invalidate_prompt_cache
    invalidate_prompt_cache()
    return {"template": payload.template}


@router.get("/clients/{tenant_id}/config")
def client_config(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("enabled_features").eq("id", tenant_id).maybe_single().execute()
    if not tenant or not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    settings_rows = execute_with_retry(
        db.table("app_settings")
        .select("key, value")
        .eq("tenant_id", tenant_id)
    )
    settings_map = {r["key"]: r["value"] for r in (settings_rows.data or [])}

    def cred_status(keys: list[str]) -> str:
        vals = [settings_map.get(k) for k in keys]
        non_null = [v for v in vals if v is not None and v != ""]
        if len(non_null) == len(keys):
            return "configured"
        if len(non_null) > 0:
            return "incomplete"
        return "not_configured"

    def float_setting(key: str, default: float) -> float:
        try:
            return float(settings_map.get(key) or default)
        except (TypeError, ValueError):
            return default

    usage_counters = []
    try:
        period = get_billing_period(db, tenant_id)
        usage_rows = (
            db.table("tenant_usage_counters")
            .select("metric, used, included, hard_cap")
            .eq("tenant_id", tenant_id)
            .eq("period", period)
            .execute()
        )
        usage_counters = usage_rows.data or []
    except Exception as e:
        logger.warning("Operator client config usage lookup failed for tenant %s: %s", tenant_id, e)
        from datetime import datetime, timezone
        period = datetime.now(timezone.utc).strftime("%Y-%m")
    usage_by_metric = {r["metric"]: r for r in usage_counters}

    # Platform-wide, read-only here: this is the same text for every client, shown so
    # an operator can see what the assistant is running on without leaving the page.
    from app.services.ai_reply import get_master_prompt
    master_prompt = get_master_prompt()

    return {
        "enabled_features": tenant.data["enabled_features"],
        "master_prompt": master_prompt,
        "business_description": settings_map.get("business_description") or "",
        "credentials_status": {
            "whatsapp": cred_status(["meta_phone_number_id", "meta_access_token", "meta_waba_id", "meta_webhook_verify_token"]),
            "telecalling": cred_status(["telecmi_app_id", "telecmi_secret", "telecmi_callerid"]),
            "ai": cred_status(["sarvam_api_key"]),
            "ai_sarvam": cred_status(["sarvam_api_key"]),
            "ai_gemini": cred_status(["gemini_api_key"]),
            "ai_openai": cred_status(["openai_api_key"]),
            "ai_groq": cred_status(["groq_api_key"]),
            "ai_jina": cred_status(["jina_api_key"]),
            "telegram": cred_status(["telegram_bot_token"]),
            "instagram": cred_status(["instagram_page_id", "instagram_access_token"]),
            "facebook": cred_status(["facebook_page_id", "facebook_access_token"]),
            "astro_bridge": cred_status(["astro_bridge_url", "astro_bridge_api_key", "astro_bridge_secret"]),
        },
        "settings": {
            # Backend gate (ai_reply.generate_reply) only disables on the literal string
            # "false" -- null/never-configured defaults to enabled. Mirror that exact
            # semantics here so the toggle never displays "Off" while replies are actually
            # still going out (live-confirmed 2026-07-17: a never-touched tenant had this
            # value stored as NULL, which a strict == "true" check rendered as Off).
            "ai_auto_reply_enabled": settings_map.get("ai_auto_reply_enabled") != "false",
            "ai_voice_reply_enabled": settings_map.get("ai_voice_reply_enabled") == "true",
            "ai_voice_reply_speaker": settings_map.get("ai_voice_reply_speaker") or "Kore",
            "ai_media_recommendations_enabled": settings_map.get("ai_media_recommendations_enabled") == "true",
            "catalog_ai_max_images_ceiling": float_setting("catalog_ai_max_images_ceiling", 5),
            "kb_retrieval_mode": settings_map.get("kb_retrieval_mode", "semantic") or "semantic",
            "ai_reply_model": settings_map.get("ai_reply_model"),
            "reply_language_mode": settings_map.get("reply_language_mode", "mirror") or "mirror",
            "deal_idle_close_days": clamp_deal_idle_close_days(settings_map.get(DEAL_IDLE_CLOSE_DAYS_KEY)),
        },
        "usage": {
            "period": period,
            "counters": usage_counters,
        },
        "voice_usage": {
            "speech_to_text": (usage_by_metric.get("ai_speech_to_text") or {}).get("used", 0) or 0,
            "text_to_speech": (usage_by_metric.get("ai_text_to_speech") or {}).get("used", 0) or 0,
        },
    }


class ClientConfigUpdate(BaseModel):
    settings: dict[str, str | bool] | None = None
    # Accepted only so a stale client gets a clear 400 instead of a silent no-op.
    master_prompt: str | None = None


@router.patch("/clients/{tenant_id}/config")
def update_client_config(
    tenant_id: str,
    payload: ClientConfigUpdate,
    _admin: dict = Depends(get_system_admin),
):
    if payload.master_prompt is not None:
        raise HTTPException(
            status_code=400,
            detail="The master prompt is platform-wide and cannot be set per client. "
                   "Edit it under Operator -> Master Prompt.",
        )
    if not payload.settings:
        raise HTTPException(status_code=400, detail="No settings to update")
    from app.services.razorpay_oauth import KEY_PREFIX as RAZORPAY_OAUTH_PREFIX
    if any(key.startswith(RAZORPAY_OAUTH_PREFIX) for key in payload.settings):
        # The account id routes the shared OAuth webhook; only the Connect flow may write it.
        raise HTTPException(status_code=400, detail="Razorpay connection details are set by Connect with Razorpay only.")

    # Validate the whole batch before writing anything, so one bad value can't leave
    # its siblings half-saved.
    normalized: dict[str, str | bool] = dict(payload.settings)
    if DEAL_IDLE_CLOSE_DAYS_KEY in normalized:
        try:
            days = validate_deal_idle_close_days(normalized[DEAL_IDLE_CLOSE_DAYS_KEY])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        normalized[DEAL_IDLE_CLOSE_DAYS_KEY] = str(days)

    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant or not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from app.config_dynamic import SECRET_SETTING_KEYS

    for key, value in normalized.items():
        db_val = str(value).lower() if isinstance(value, bool) else str(value)
        db.table("app_settings").upsert({
            "tenant_id": tenant_id,
            "key": key,
            "value": db_val,
            "is_secret": key in SECRET_SETTING_KEYS,
            "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()

    from app.config_dynamic import invalidate_cache
    invalidate_cache()

    redacted_settings = {
        key: ("***redacted***" if key in SECRET_SETTING_KEYS else value)
        for key, value in normalized.items()
    }
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action="operator.client_config.updated",
        target_type="app_settings",
        target_id=tenant_id,
        metadata={"settings": redacted_settings},
    )

    return {"status": "ok"}



@router.get("/clients/{tenant_id}/health")
def client_health(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    from datetime import datetime, timezone, timedelta
    db = get_supabase()

    tenant = db.table("tenants").select("id, enabled_features").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    channel_sources = {"whatsapp": "whatsapp", "instagram": "instagram", "facebook": "facebook", "telegram": "telegram"}
    channels: dict = {}
    for channel, source in channel_sources.items():
        last_inbound = (
            db.table("messages").select("created_at")
            .eq("tenant_id", tenant_id).eq("direction", "inbound").eq("channel", source)
            .order("created_at", desc=True).limit(1).execute()
        )
        last_ts = (last_inbound.data or [{}])[0].get("created_at")
        is_enabled = channel in (tenant.data.get("enabled_features") or [])
        channels[channel] = {
            "status": "healthy" if is_enabled and last_ts else ("not_configured" if not is_enabled else "unhealthy"),
            "last_inbound": last_ts,
        }

    token_incidents = (
        db.table("incidents").select("id")
        .eq("tenant_id", tenant_id).eq("type", "token_invalid")
        .order("created_at", desc=True).limit(1).execute()
    )
    settings_rows = db.table("app_settings").select("key, value").eq("tenant_id", tenant_id).in_("key", ["meta_access_token"]).execute()
    has_token = any(r["value"] for r in (settings_rows.data or []))
    token_status = "not_set"
    if has_token:
        token_status = "expired" if token_incidents.data else "valid"

    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    sent_7d = db.table("messages").select("id", count="exact").eq("tenant_id", tenant_id).eq("direction", "outbound").gte("created_at", seven_days_ago).execute()
    delivered_7d = (
        db.table("messages").select("id", count="exact")
        .eq("tenant_id", tenant_id).eq("direction", "outbound")
        .eq("delivery_status", "delivered")
        .gte("created_at", seven_days_ago).execute()
    )
    failed_7d = (
        db.table("messages").select("id", count="exact")
        .eq("tenant_id", tenant_id).eq("direction", "outbound")
        .eq("delivery_status", "failed")
        .gte("created_at", seven_days_ago).execute()
    )
    sent_count = sent_7d.count or 0
    delivered_count = delivered_7d.count or 0
    failed_count = failed_7d.count or 0
    success_rate = round((delivered_count / sent_count) * 100, 1) if sent_count > 0 else 0

    recent_errors = (
        db.table("messages").select("id, delivery_error_title, created_at")
        .eq("tenant_id", tenant_id).eq("delivery_status", "failed")
        .order("created_at", desc=True).limit(10).execute()
    )
    open_incidents = (
        db.table("incidents").select("id, type, detail, created_at")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True).limit(10).execute()
    )

    return {
        "channels": channels,
        "token_status": token_status,
        "delivery_7d": {
            "sent": sent_count,
            "delivered": delivered_count,
            "failed": failed_count,
            "success_rate": success_rate,
        },
        "recent_errors": [
            {"message_id": r["id"], "error": r.get("delivery_error_title"), "created_at": r["created_at"]}
            for r in (recent_errors.data or [])
        ],
        "open_incidents": [
            {
                "id": inc["id"],
                "type": inc.get("type", ""),
                "severity": (inc.get("detail") or {}).get("severity", "info"),
                "message": (inc.get("detail") or {}).get("message", inc.get("type", "")),
                "created_at": inc["created_at"],
            }
            for inc in (open_incidents.data or [])
        ],
    }


@router.get("/clients/{tenant_id}/team")
def client_team(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()

    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    owner_row = (
        db.table("tenant_users")
        .select("user_id, created_at")
        .eq("tenant_id", tenant_id)
        .eq("role", "owner")
        .maybe_single()
        .execute()
    )
    owner_info: dict = {"user_id": None, "email": None, "created_at": None}
    if owner_row.data:
        owner_info["user_id"] = owner_row.data["user_id"]
        owner_info["created_at"] = owner_row.data["created_at"]
        try:
            user = db.auth.admin.get_user_by_id(owner_row.data["user_id"])
            owner_info["email"] = user.user.email if hasattr(user, "user") else None
        except Exception:
            pass

    callers_rows = (
        db.table("callers")
        .select("id, name, active, shift_start_hour, shift_end_hour, user_id")
        .eq("tenant_id", tenant_id)
        .order("name")
        .execute()
    )

    tenant_users = (
        db.table("tenant_users")
        .select("user_id, role")
        .eq("tenant_id", tenant_id)
        .execute()
    )
    role_map = {r["user_id"]: r["role"] for r in (tenant_users.data or [])}

    from app.services.telecaller_performance import ist_month_bounds, period_stats

    calling_provider = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi")
    is_sim = calling_provider == "sim_basic"
    month_start, month_end = ist_month_bounds()
    month_stats = None if is_sim else period_stats(db, tenant_id, month_start, month_end)

    callers = []
    for c in (callers_rows.data or []):
        row = {
            "id": c["id"],
            "name": c["name"],
            "active": c["active"],
            "shift_start_hour": c.get("shift_start_hour"),
            "shift_end_hour": c.get("shift_end_hour"),
            "role": role_map.get(c.get("user_id"), "caller"),
        }
        # SIM clients get no evaluation: no avg score for their team either.
        if not is_sim:
            row["avg_score_month"] = (month_stats.get(str(c["id"])) or {}).get("avg_score")
        callers.append(row)

    return {"owner": owner_info, "callers": callers, "calling_provider": calling_provider}


@router.get("/clients/{tenant_id}/roles")
def client_roles(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    """Read-only operator view of a client's roles + role-assigned users.
    Actual role/permission editing stays exclusively on the client's own
    Roles page (`rbac.py`) -- this is visibility only, no impersonation."""
    db = get_supabase()

    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    ensure_default_roles(db, tenant_id)
    roles_res = db.table("tenant_roles").select("*").eq("tenant_id", tenant_id).order("name").execute()
    role_rows = roles_res.data or []
    role_by_id = {r["id"]: r for r in role_rows}

    members_res = (
        db.table("tenant_users")
        .select("user_id, role, role_id, full_name, created_at")
        .eq("tenant_id", tenant_id)
        .order("created_at")
        .execute()
    )

    roles = []
    for r in role_rows:
        permissions = normalize_permissions(r.get("permissions"))
        roles.append({
            "id": r["id"],
            "name": r["name"],
            "slug": r.get("slug"),
            "is_system_template": r.get("is_system_template", False),
            "is_telecaller": is_telecaller_role({**r, "permissions": permissions}),
            "permission_count": len(permissions),
        })

    users = []
    for m in (members_res.data or []):
        role_row = role_by_id.get(m.get("role_id"))
        users.append({
            "user_id": m["user_id"],
            "full_name": m.get("full_name"),
            "role": m.get("role"),
            "role_name": (role_row or {}).get("name") or ("Owner" if m.get("role") == "owner" else "Telecaller"),
            "created_at": m.get("created_at"),
        })

    return {"roles": roles, "users": users}


@router.delete("/clients/{tenant_id}/team/{caller_id}")
def delete_team_member(tenant_id: str, caller_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    caller = (
        db.table("callers")
        .select("id, name, user_id")
        .eq("id", caller_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not caller.data:
        raise HTTPException(status_code=404, detail="Team member not found")

    db.table("callers").delete().eq("id", caller_id).eq("tenant_id", tenant_id).execute()

    if caller.data.get("user_id"):
        db.table("tenant_users").delete().eq("user_id", caller.data["user_id"]).eq("tenant_id", tenant_id).eq("role", "caller").execute()

    return {"deleted": True, "name": caller.data["name"]}


@router.get("/clients/{tenant_id}/dashboard/inbox")
def client_dashboard_inbox(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    handovers = db.table("chat_handovers").select("id", count="exact").eq("tenant_id", tenant_id).eq("status", "pending").execute()

    convos = (
        db.table("conversations")
        .select("id, lead_id, channel, opened_at")
        .eq("tenant_id", tenant_id)
        .order("opened_at", desc=True)
        .limit(20)
        .execute()
    )

    lead_ids = [c["lead_id"] for c in (convos.data or []) if c.get("lead_id")]
    leads_map: dict = {}
    last_msg_map: dict = {}
    if lead_ids:
        leads = db.table("leads").select("id, name, phone").in_("id", lead_ids).execute()
        leads_map = {l["id"]: l for l in (leads.data or [])}
        msgs = (
            db.table("messages")
            .select("lead_id, content, created_at")
            .in_("lead_id", lead_ids)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .execute()
        )
        for m in (msgs.data or []):
            lid = m.get("lead_id")
            if lid and lid not in last_msg_map:
                last_msg_map[lid] = m

    conversations = []
    for c in (convos.data or []):
        lead = leads_map.get(c.get("lead_id"), {})
        msg = last_msg_map.get(c.get("lead_id"), {})
        conversations.append({
            "id": c["id"],
            "lead_id": c.get("lead_id"),
            "lead_name": lead.get("name", "Unknown"),
            "lead_phone": lead.get("phone"),
            "last_message": (msg.get("content") or "")[:80],
            "channel": c.get("channel", "whatsapp"),
            "last_message_at": msg.get("created_at") or c.get("opened_at"),
        })

    return {"handover_count": handovers.count or 0, "conversations": conversations}


@router.get("/clients/{tenant_id}/dashboard/leads")
def client_dashboard_leads(tenant_id: str, direction: str = "all", _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    base = db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).is_("deleted_at", "null")
    total = base.execute()
    seg_a = db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).is_("deleted_at", "null").eq("segment", "A").execute()
    seg_b = db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).is_("deleted_at", "null").eq("segment", "B").execute()
    seg_c = db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).is_("deleted_at", "null").eq("segment", "C").execute()
    seg_d = db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).is_("deleted_at", "null").eq("segment", "D").execute()

    q = db.table("leads").select("id, name, phone, segment, score, source, created_at, opt_in_source").eq("tenant_id", tenant_id).is_("deleted_at", "null")
    if direction == "inbound":
        q = q.in_("opt_in_source", ["organic", "meta_ads", "instagram", "facebook", "telegram"])
    elif direction == "outbound":
        q = q.eq("opt_in_source", "csv")
    recent = q.order("created_at", desc=True).limit(20).execute()

    return {
        "total": total.count or 0,
        "segments": {"A": seg_a.count or 0, "B": seg_b.count or 0, "C": seg_c.count or 0, "D": seg_d.count or 0},
        "recent": recent.data or [],
    }


@router.get("/clients/{tenant_id}/dashboard/templates")
def client_dashboard_templates(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    templates = (
        db.table("message_templates")
        .select("id, name, status, category, language, submitted_at")
        .eq("tenant_id", tenant_id)
        .order("submitted_at", desc=True)
        .execute()
    )
    raw = templates.data or []
    approved = sum(1 for t in raw if t.get("status") == "APPROVED")
    pending = sum(1 for t in raw if t.get("status") == "PENDING")
    data = [
        {**t, "updated_at": t.pop("submitted_at", None)}
        for t in raw
    ]

    return {"total": len(data), "approved": approved, "pending": pending, "templates": data}


@router.get("/clients/{tenant_id}/dashboard/numbers")
def client_dashboard_numbers(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    numbers = (
        db.table("phone_numbers")
        .select("id, number, display_name, quality_rating, status, messaging_tier")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .execute()
    )
    raw = numbers.data or []
    active = sum(1 for n in raw if n.get("status") == "active")
    data = [
        {
            "phone_number": n.get("number"),
            "display_name": n.get("display_name"),
            "quality_rating": (n.get("quality_rating") or "").upper() or None,
            "status": n.get("status"),
            "messaging_limit_tier": str(n.get("messaging_tier")) if n.get("messaging_tier") else None,
        }
        for n in raw
    ]

    return {"total": len(data), "active": active, "numbers": data}


@router.get("/clients/{tenant_id}/dashboard/knowledge")
def client_dashboard_knowledge(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    docs = (
        db.table("knowledge_documents")
        .select("id, name, file_type, created_at")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .execute()
    )
    total_chunks = db.table("knowledge_chunks").select("id", count="exact").eq("tenant_id", tenant_id).execute()

    doc_data = []
    for d in (docs.data or []):
        chunk_count = db.table("knowledge_chunks").select("id", count="exact").eq("document_id", d["id"]).execute()
        doc_data.append({"id": d["id"], "title": d.get("name", ""), "file_type": d.get("file_type", ""), "created_at": d.get("created_at"), "chunk_count": chunk_count.count or 0})

    return {"total_docs": len(docs.data or []), "total_chunks": total_chunks.count or 0, "documents": doc_data}


@router.get("/clients/{tenant_id}/dashboard/analytics")
def client_dashboard_analytics(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    from datetime import datetime, timezone, timedelta
    db = get_supabase()
    tenant = db.table("tenants").select("id, enabled_features").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    total_msgs = db.table("messages").select("id", count="exact").eq("tenant_id", tenant_id).gte("created_at", thirty_days_ago).execute()
    delivered = db.table("messages").select("id", count="exact").eq("tenant_id", tenant_id).eq("direction", "outbound").eq("delivery_status", "delivered").gte("created_at", thirty_days_ago).execute()
    sent = db.table("messages").select("id", count="exact").eq("tenant_id", tenant_id).eq("direction", "outbound").gte("created_at", thirty_days_ago).execute()
    avg_score_rows = db.table("leads").select("score").eq("tenant_id", tenant_id).is_("deleted_at", "null").not_.is_("score", "null").execute()

    sent_count = sent.count or 0
    delivered_count = delivered.count or 0
    delivery_rate = round((delivered_count / sent_count) * 100, 1) if sent_count > 0 else 0
    scores = [r["score"] for r in (avg_score_rows.data or []) if r.get("score") is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    result: dict = {
        "messages_30d": total_msgs.count or 0,
        "delivery_rate": delivery_rate,
        "avg_score": avg_score,
    }

    if "telecalling" in (tenant.data.get("enabled_features") or []):
        calls = (
            db.table("call_logs")
            .select("id,manual_status")
            .eq("tenant_id", tenant_id)
            .gte("created_at", thirty_days_ago)
            .execute()
        )
        call_rows = calls.data or []
        call_count = len(call_rows)
        result["total_calls"] = call_count
        result["connect_rate"] = round(wrapup_connect_rate(call_rows) * 100, 1)

    return result


@router.get("/clients/{tenant_id}/dashboard/daily-messages")
def client_dashboard_daily_messages(
    tenant_id: str,
    range_days: int = 7,
    all_time: bool = False,
    from_date: str | None = None,
    to_date: str | None = None,
    _admin: dict = Depends(get_system_admin),
):
    """Per-day inbound/outbound/AI-vs-human breakdown for one tenant, scoped by
    an operator-supplied tenant_id instead of the caller's own tenant.

    from_date/to_date (YYYY-MM-DD, both required together) select a custom,
    inclusive range and take priority over range_days/all_time -- same
    contract as get_client_token_usage."""
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    now = datetime.now(timezone.utc)
    if from_date and to_date:
        try:
            from_d = datetime.fromisoformat(from_date).date()
            to_d = datetime.fromisoformat(to_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date/to_date must be YYYY-MM-DD")
        if to_d < from_d:
            raise HTTPException(status_code=400, detail="to_date must be on or after from_date")
        window_start_dt = datetime.combine(from_d, datetime.min.time(), tzinfo=timezone.utc)
        days_iso = [(from_d + timedelta(days=i)).isoformat() for i in range((to_d - from_d).days + 1)]
    elif all_time:
        earliest = (
            db.table("messages")
            .select("created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at")
            .limit(1)
            .execute()
        )
        start_date = (
            datetime.fromisoformat(earliest.data[0]["created_at"].replace("Z", "+00:00")).date()
            if earliest.data else now.date()
        )
        window_start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        days_iso = [(start_date + timedelta(days=i)).isoformat() for i in range((now.date() - start_date).days + 1)]
    else:
        window_start_dt = now - timedelta(days=range_days)
        days_iso = [(now - timedelta(days=i)).date().isoformat() for i in range(range_days - 1, -1, -1)]

    msgs = (
        db.table("messages")
        .select("direction,is_ai_generated,created_at")
        .eq("tenant_id", tenant_id)
        .gte("created_at", window_start_dt.isoformat())
        .execute()
    ).data or []

    daily_map = {d: {"inbound": 0, "outbound": 0, "ai": 0, "human": 0} for d in days_iso}
    for m in msgs:
        day = (m.get("created_at") or "")[:10]
        if day not in daily_map:
            continue
        direction = m.get("direction")
        if direction == "inbound":
            daily_map[day]["inbound"] += 1
        elif direction == "outbound":
            daily_map[day]["outbound"] += 1
            if m.get("is_ai_generated"):
                daily_map[day]["ai"] += 1
            else:
                daily_map[day]["human"] += 1

    return {
        "daily_messages": [
            {"day": d, **daily_map[d]}
            for d in days_iso
        ],
    }


@router.get("/clients/{tenant_id}/dashboard/telecalling")
def client_dashboard_telecalling(tenant_id: str, section: str = "dialer", _admin: dict = Depends(get_system_admin)):
    from datetime import datetime, timezone, timedelta
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if section == "upload":
        raw_batches = (
            db.table("telecalling_upload_batches")
            .select("id, file_name, total_contacts, inserted, created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        total = db.table("telecalling_upload_batches").select("id", count="exact").eq("tenant_id", tenant_id).execute()
        batches = [
            {
                "id": b["id"],
                "file_name": b.get("file_name"),
                "lead_count": b.get("total_contacts", 0),
                "created_at": b.get("created_at"),
                "status": "completed" if b.get("inserted") is not None else "processing",
            }
            for b in (raw_batches.data or [])
        ]
        return {"total_batches": total.count or 0, "batches": batches}

    elif section == "dialer":
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
        calls_today = (
            db.table("call_logs")
            .select("id,manual_status")
            .eq("tenant_id", tenant_id)
            .gte("created_at", today)
            .execute()
        )
        recent_calls = (
            db.table("call_logs")
            .select("id, lead_id, caller_id, duration_seconds, disposition, manual_status, provider, feedback_source, created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        call_rows = calls_today.data or []
        call_count = len(call_rows)
        return {
            "calls_today": call_count,
            "connect_rate": round(wrapup_connect_rate(call_rows) * 100, 1),
            "recent_calls": recent_calls.data or [],
        }

    elif section == "scheduled":
        pending = (
            db.table("follow_up_jobs")
            .select("id, lead_id, scheduled_for, cadence, created_at")
            .eq("tenant_id", tenant_id)
            .eq("status", "pending")
            .order("scheduled_for")
            .limit(20)
            .execute()
        )
        total = db.table("follow_up_jobs").select("id", count="exact").eq("tenant_id", tenant_id).eq("status", "pending").execute()
        return {"pending_count": total.count or 0, "scheduled": pending.data or []}

    elif section == "notes":
        raw_notes = (
            db.table("lead_notes")
            .select("id, lead_id, caller_id, content, created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        total = db.table("lead_notes").select("id", count="exact").eq("tenant_id", tenant_id).execute()
        caller_ids = list({n["caller_id"] for n in (raw_notes.data or []) if n.get("caller_id")})
        callers_map: dict = {}
        if caller_ids:
            callers = db.table("callers").select("id, name").in_("id", caller_ids).execute()
            callers_map = {c["id"]: c.get("name") for c in (callers.data or [])}
        notes = [
            {
                "id": n["id"],
                "lead_id": n.get("lead_id"),
                "author_name": callers_map.get(n.get("caller_id")) if n.get("caller_id") else None,
                "note": n.get("content", ""),
                "created_at": n.get("created_at"),
            }
            for n in (raw_notes.data or [])
        ]
        return {"total_notes": total.count or 0, "notes": notes}

    raise HTTPException(status_code=400, detail="Invalid section. Use: upload, dialer, scheduled, notes")


_CLEAR_TABLES: dict[str, list[str]] = {
    "broadcasts": ["broadcast_recipients", "broadcast_lead_scores", "broadcast_failed_contacts", "scheduled_broadcasts"],
    "messages": ["messages"],
    "call_logs": ["call_logs"],
    "leads": [],
    "knowledge": ["knowledge_chunks", "knowledge_documents"],
    "analytics": ["whatsapp_insights_snapshots"],
    "tags": ["lead_tag_opt_outs", "broadcast_tags"],
    "telecalling_uploads": ["telecalling_upload_batches"],
}


@router.get("/clients/{tenant_id}/clear/{data_type}/count")
def clear_count(tenant_id: str, data_type: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    if data_type not in _CLEAR_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid data type: {data_type}")
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data_type == "leads":
        count = db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).is_("deleted_at", "null").execute()
        return {"count": count.count or 0, "detail": {"leads": count.count or 0}}

    detail: dict = {}
    total = 0
    for table in _CLEAR_TABLES[data_type]:
        c = db.table(table).select("id", count="exact").eq("tenant_id", tenant_id).execute()
        detail[table] = c.count or 0
        total += c.count or 0
    return {"count": total, "detail": detail}


@router.post("/clients/{tenant_id}/clear/{data_type}")
def clear_data(tenant_id: str, data_type: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    if data_type not in _CLEAR_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid data type: {data_type}")
    tenant = db.table("tenants").select("id, name").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data_type == "leads":
        for table in ("messages", "lead_notes", "chat_handovers", "follow_up_jobs",
                       "broadcast_recipients", "broadcast_lead_scores", "broadcast_failed_contacts",
                       "broadcast_tags", "scheduled_broadcasts"):
            try:
                db.table(table).delete().eq("tenant_id", tenant_id).execute()
            except Exception as e:
                logger.warning("clear leads: could not clear %s: %s", table, e)
        # Broadcast history is stored as a JSON blob in app_settings, not a
        # row-per-broadcast table -- clear it too so it doesn't reference
        # leads that no longer exist.
        try:
            db.table("app_settings").delete().eq("tenant_id", tenant_id).eq("key", "broadcast_history").execute()
        except Exception as e:
            logger.warning("clear leads: could not clear broadcast_history for tenant %s: %s", tenant_id, e)
        result = db.table("leads").delete().eq("tenant_id", tenant_id).execute()
        deleted = len(result.data or [])
    else:
        deleted = 0
        tables = _CLEAR_TABLES[data_type]
        for table in tables:
            try:
                result = db.table(table).delete().eq("tenant_id", tenant_id).execute()
                deleted += len(result.data or [])
            except Exception as e:
                logger.warning("clear %s: could not clear %s: %s", data_type, table, e)

    logger.warning("OPERATOR CLEAR %s: %d records deleted for tenant %s", data_type, deleted, tenant_id)
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=_admin.get("user_id"),
        actor_role="system_admin",
        action=f"operator.data_cleared:{data_type}",
        target_type="tenant",
        target_id=tenant_id,
        metadata={"data_type": data_type, "deleted_count": deleted, "tenant_name": tenant.data["name"]},
    )
    return {"deleted_count": deleted, "data_type": data_type}


def _parse_ts(value) -> datetime | None:
    """A datetime or an ISO string (PostgREST or isoformat) as an aware UTC datetime; None if unreadable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# A job is "not running" once it has gone this many of its own intervals without a success.
_NOT_RUNNING_INTERVALS = 3


def _build_scheduler_jobs(db, now) -> list[dict]:
    """Fetch each global APScheduler job's last-run status and 24h error count.

    Shared by `GET /scheduler-health` (the Scheduler page) and `GET /alerts`
    (the operator alert center), so both read the same signals instead of
    running the queries twice.
    """
    from datetime import timedelta
    from app.main import _scheduler, _scheduler_started_at, _last_success

    day_ago = (now - timedelta(hours=24)).isoformat()

    jobs_out = []
    for job in _scheduler.get_jobs():
        # scheduler_runs holds failures (successes before 2026-10-31 age out in 7 days);
        # this process's last success is in memory. The newer of the two is the last run.
        last = (
            db.table("scheduler_runs")
            .select("status, ran_at, lateness_ms, error")
            .eq("job_id", job.id)
            .order("ran_at", desc=True)
            .limit(1)
            .execute()
        )
        last_row = (last.data or [None])[0]
        ok = _last_success.get(job.id)
        last_success = ok["ran_at"] if ok else None
        if ok and (not last_row or _parse_ts(ok["ran_at"]) > _parse_ts(last_row["ran_at"])):
            last_row = {"status": "success", "ran_at": ok["ran_at"], "lateness_ms": ok["lateness_ms"], "error": None}
        interval = getattr(job.trigger, "interval", None)  # cron jobs have none
        errs = (
            db.table("scheduler_runs")
            .select("id", count="exact")
            .eq("job_id", job.id)
            .eq("status", "error")
            .gte("ran_at", day_ago)
            .execute()
        )
        jobs_out.append({
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "paused": job.next_run_time is None,
            "last_status": last_row["status"] if last_row else None,
            "last_run": last_row["ran_at"] if last_row else None,
            "last_lateness_ms": last_row["lateness_ms"] if last_row else None,
            "last_error": last_row["error"] if last_row else None,
            "errors_24h": errs.count or 0,
            "last_success": last_success,
            "interval_seconds": interval.total_seconds() if interval else None,
            # The newer of the last success and this process's start: a job with no success
            # since boot is judged from boot, never from a success in a previous deploy.
            "watch_from": max(
                (t for t in (_parse_ts(last_success), _scheduler_started_at) if t), default=None,
            ),
        })

    return jobs_out


@router.get("/scheduler-health")
def scheduler_health(_admin: dict = Depends(get_system_admin)):
    """System-wide APScheduler health: each global job's next run, last run
    status/lag, recent error count, plus recent failures. Operator-only —
    the jobs are platform-level (not per tenant)."""
    from datetime import datetime, timezone

    db = get_supabase()
    now = datetime.now(timezone.utc)

    jobs_out = _build_scheduler_jobs(db, now)

    recent_failures = (
        db.table("scheduler_runs")
        .select("job_id, status, ran_at, error")
        .in_("status", ["error", "missed"])
        .order("ran_at", desc=True)
        .limit(20)
        .execute()
    )
    return {
        "jobs": jobs_out,
        "recent_failures": recent_failures.data or [],
        "server_time": now.isoformat(),
    }


@router.post("/scheduler/{job_id}/toggle")
def toggle_scheduler_job(job_id: str, _admin: dict = Depends(get_system_admin)):
    """Pause a running job or resume a paused one. Operator-only."""
    from app.main import _scheduler

    job = _scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.next_run_time is None:
        _scheduler.resume_job(job_id)
        job = _scheduler.get_job(job_id)
        return {"id": job_id, "paused": False, "next_run": job.next_run_time.isoformat() if job.next_run_time else None}
    else:
        _scheduler.pause_job(job_id)
        return {"id": job_id, "paused": True, "next_run": None}


def _resolve_scheduler_run(job_id: str, job) -> dict:
    """Pure decision logic for `POST /scheduler/{job_id}/run`.

    Given the job_id requested and the APScheduler `Job` looked up for it
    (or `None` if unknown), decide whether the run can proceed. Raises the
    same `HTTPException`s the route returns so this can be unit-tested
    without a live scheduler. Does NOT mutate the job — the caller applies
    `job.modify(next_run_time=...)` only after this returns cleanly.
    """
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job.next_run_time is None:
        raise HTTPException(status_code=409, detail="Job is paused — resume it before running")
    return {"id": job_id}


@router.post("/scheduler/{job_id}/run")
def run_scheduler_job(job_id: str, _admin: dict = Depends(get_system_admin)):
    """Trigger an immediate run of a scheduled job without disturbing its
    regular schedule. Operator-only.

    Implementation note: this does NOT call the job function synchronously
    in the request thread. It nudges APScheduler's `next_run_time` to now,
    so the job runs ASAP on the scheduler's own executor; APScheduler then
    recomputes the next scheduled run from the job's trigger as usual.
    Paused jobs (`next_run_time is None`) are rejected rather than silently
    resumed, to keep Task 2's pause semantics intact.
    """
    from app.main import _scheduler

    job = _scheduler.get_job(job_id)
    _resolve_scheduler_run(job_id, job)

    job.modify(next_run_time=datetime.now(timezone.utc))
    job = _scheduler.get_job(job_id)

    logger.warning(
        "Manual scheduler run triggered job_id=%s admin_id=%s",
        job_id,
        _admin.get("user_id"),
    )
    # Scheduler jobs are platform-wide (no tenant_id), so this is skipped
    # rather than forcing a tenant scope onto record_audit_event; the
    # warning log above is the audit trail for this action.

    return {
        "id": job_id,
        "triggered": True,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }


@router.get("/system-health")
def system_health(_admin: dict = Depends(get_system_admin)):
    """Platform-level health: uptime, memory, Python version, last keep-alive ping."""
    import psutil, platform
    from datetime import datetime, timezone
    from app.main import _startup_time

    now = datetime.now(timezone.utc)
    uptime_seconds = (now - _startup_time).total_seconds()
    process = psutil.Process()
    mem = process.memory_info()

    return {
        "status": "healthy",
        "uptime_seconds": int(uptime_seconds),
        "uptime_human": _format_uptime(uptime_seconds),
        "memory_mb": round(mem.rss / (1024 * 1024), 1),
        "cpu_percent": process.cpu_percent(interval=0.1),
        "python_version": platform.python_version(),
        "server_time": now.isoformat(),
        "started_at": _startup_time.isoformat(),
    }


def _format_uptime(seconds: float) -> str:
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


_INCIDENT_SEVERITY: dict[str, str] = {
    "token_invalid": "critical",
}

_SEVERITY_RANK: dict[str, int] = {"critical": 0, "warning": 1, "info": 2}


def _job_not_running(job: dict, now: datetime) -> bool:
    """An interval job whose last success (or this process's start) is older than
    _NOT_RUNNING_INTERVALS of its interval. Cron jobs (no interval) are never judged."""
    interval = job.get("interval_seconds")
    since = _parse_ts(job.get("watch_from"))
    if not interval or since is None:
        return False
    return (now - since).total_seconds() > _NOT_RUNNING_INTERVALS * interval


def compute_alerts(
    *,
    fleet_rows: list[dict],
    scheduler_jobs: list[dict],
    incidents: list[dict],
    now: datetime,
) -> list[dict]:
    """Pure, DB-free aggregation of the operator alert center's signals.

    Takes already-fetched rows from the fleet cockpit (`_build_fleet_rows`),
    scheduler health (`_build_scheduler_jobs`), and the `incidents` table, and
    turns them into a single deduped, severity-sorted alert feed. No DB access
    here — every branch is exercisable directly, mirroring `compute_fleet_health`.

    Dedup: each alert gets a stable `id` derived from (source, tenant/job id,
    kind) — e.g. `fleet:token_expired:<tenant_id>` or `scheduler:failing:<job_id>`.
    Building the id this way means the same underlying problem (say, a tenant
    that is both `token_expired` and `near_cap`) naturally produces two
    *different* alerts (one per distinct problem) while a signal seen twice
    (e.g. re-fetched) collapses to one, by keying a dict on id before sorting.
    """
    alerts: dict[str, dict] = {}

    def add(alert: dict) -> None:
        # First write wins so priority ordering below (critical-producing
        # checks first) determines which title/detail survives a collision.
        alerts.setdefault(alert["id"], alert)

    # --- Fleet signals: expired tokens, AI cap, near-cap -------------------
    for row in fleet_rows:
        tenant_id = row.get("id")
        tenant_name = row.get("name")
        href = f"/operator/client/{tenant_id}" if tenant_id else None

        if row.get("token_expired"):
            add({
                "id": f"fleet:token_expired:{tenant_id}",
                "severity": "critical",
                "title": "Messaging token expired",
                "detail": f"{tenant_name} has an expired or missing messaging token.",
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "source": "fleet",
                "created_at": row.get("last_activity") or now.isoformat(),
                "href": href,
            })

        ai_usage = row.get("ai_usage", 0) or 0
        if ai_usage >= 100:
            add({
                "id": f"fleet:ai_cap:{tenant_id}",
                "severity": "critical",
                "title": "AI usage at or over cap",
                "detail": f"{tenant_name} is at {ai_usage}% of its AI reply quota.",
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "source": "fleet",
                "created_at": row.get("last_activity") or now.isoformat(),
                "href": href,
            })
        elif row.get("near_cap"):
            add({
                "id": f"fleet:near_cap:{tenant_id}",
                "severity": "warning",
                "title": "AI usage nearing cap",
                "detail": f"{tenant_name} is at {ai_usage}% of its AI reply quota.",
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "source": "fleet",
                "created_at": row.get("last_activity") or now.isoformat(),
                "href": href,
            })

    # --- Scheduler signals: failing / paused-critical jobs ------------------
    for job in scheduler_jobs:
        job_id = job.get("id")
        if job.get("errors_24h", 0) > 0 or job.get("last_status") == "error":
            add({
                "id": f"scheduler:failing:{job_id}",
                "severity": "critical",
                "title": f"Scheduler job failing: {job_id}",
                "detail": job.get("last_error") or f"{job.get('errors_24h', 0)} error(s) in the last 24h.",
                "tenant_id": None,
                "tenant_name": None,
                "source": "scheduler",
                "created_at": job.get("last_run") or now.isoformat(),
                "href": "/operator/scheduler",
            })
        elif not job.get("paused") and _job_not_running(job, now):
            add({
                "id": f"scheduler:not_running:{job_id}",
                "severity": "critical",
                "title": f"Scheduler job not running: {job_id}",
                "detail": (
                    f"No successful run in {_NOT_RUNNING_INTERVALS} of its intervals "
                    f"(last status: {job.get('last_status') or 'none'})."
                ),
                "tenant_id": None,
                "tenant_name": None,
                "source": "scheduler",
                "created_at": job.get("last_run") or now.isoformat(),
                "href": "/operator/scheduler",
            })
        elif job.get("paused"):
            add({
                "id": f"scheduler:paused:{job_id}",
                "severity": "warning",
                "title": f"Scheduler job paused: {job_id}",
                "detail": "This job is paused and will not run until resumed.",
                "tenant_id": None,
                "tenant_name": None,
                "source": "scheduler",
                "created_at": now.isoformat(),
                "href": "/operator/scheduler",
            })

    # --- Incident signals: recent open incidents ----------------------------
    for inc in incidents:
        inc_type = inc.get("type") or "incident"
        severity = _INCIDENT_SEVERITY.get(inc_type, "warning")
        tenant_id = inc.get("tenant_id")
        detail = inc.get("detail")
        message = None
        if isinstance(detail, dict):
            message = detail.get("message")
        # Fold the incident row's own (stable) primary key into the dedup id.
        # `create_token_incident` dedups token_invalid incidents per (tenant,
        # channel), so two distinct incidents for the same tenant on different
        # channels are two different DB rows with different ids — using only
        # (inc_type, tenant_id) here would collapse them into one alert and
        # silently drop the second. Keying on the row id keeps them distinct
        # while still collapsing the *same* incident re-fetched on a later
        # poll, since its id is stable across polls.
        add({
            "id": f"incident:{inc_type}:{tenant_id}:{inc.get('id')}",
            "severity": severity,
            "title": inc_type.replace("_", " ").capitalize(),
            "detail": message or f"Open incident for tenant {tenant_id}.",
            "tenant_id": tenant_id,
            "tenant_name": inc.get("tenant_name"),
            "source": "incident",
            "created_at": inc.get("created_at") or now.isoformat(),
            "href": f"/operator/client/{tenant_id}" if tenant_id else None,
        })

    return sorted(
        alerts.values(),
        key=lambda a: (_SEVERITY_RANK.get(a["severity"], 3), a.get("created_at") or ""),
    )


@router.get("/alerts")
def operator_alerts(_admin: dict = Depends(get_system_admin)):
    """Aggregated, deduped feed of active platform issues for the operator
    alert center (header bell). Reuses the same signal-gathering as the Fleet
    Cockpit and Scheduler pages rather than re-querying."""
    from datetime import datetime, timezone

    db = get_supabase()
    now = datetime.now(timezone.utc)

    try:
        fleet_rows = _build_fleet_rows(db)
        scheduler_jobs = _build_scheduler_jobs(db, now)

        tenant_names = {row["id"]: row["name"] for row in fleet_rows}
        alert_incident_cutoff = (now - timedelta(hours=48)).isoformat()
        incidents_res = (
            db.table("incidents")
            .select("id, tenant_id, type, detail, created_at")
            .gte("created_at", alert_incident_cutoff)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        incidents = [
            {**inc, "tenant_name": tenant_names.get(inc.get("tenant_id"))}
            for inc in (incidents_res.data or [])
        ]

        alerts = compute_alerts(
            fleet_rows=fleet_rows,
            scheduler_jobs=scheduler_jobs,
            incidents=incidents,
            now=now,
        )
    except Exception as e:
        logger.warning("Operator alerts lookup failed: %s", e)
        alerts = []
    return {"data": alerts}


@router.get("/audit-logs")
def list_audit_logs(
    page: int = 1,
    limit: int = 50,
    tenant_id: str | None = None,
    action: str | None = None,
    _admin: dict = Depends(get_system_admin),
):
    db = get_supabase()
    q = db.table("app_audit_logs").select(
        "id, tenant_id, actor_user_id, actor_role, action, target_type, target_id, metadata, created_at",
        count="exact",
    )
    # Global operator audit shows only developer/operator activity. Tenant-user
    # events are surfaced separately via the per-tenant audit view
    # (/clients/{tenant_id}/audit-logs), which reads the same table by tenant_id.
    q = q.eq("actor_role", "system_admin")
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    if action:
        q = q.ilike("action", f"%{action}%")
    offset = (page - 1) * limit
    result = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    tenant_ids = list({r["tenant_id"] for r in (result.data or []) if r.get("tenant_id")})
    tenant_names: dict[str, str] = {}
    if tenant_ids:
        tenants = db.table("tenants").select("id, name").in_("id", tenant_ids).execute()
        tenant_names = {t["id"]: t["name"] for t in (tenants.data or [])}

    logs = []
    for r in (result.data or []):
        logs.append({
            **r,
            "tenant_name": tenant_names.get(r.get("tenant_id", ""), "—"),
        })

    return {"data": logs, "total": result.count or 0, "page": page, "limit": limit}


_ALL_TENANT_TABLES = [
    "messages", "lead_notes", "chat_handovers", "follow_up_jobs",
    "broadcast_recipients", "broadcast_lead_scores", "broadcast_failed_contacts",
    "broadcast_tags", "scheduled_broadcasts", "lead_stage_events", "lead_tag_opt_outs",
    "lead_tag_interest", "lead_conversation_state", "automation_flow_runs",
    "automation_logs", "automation_pending_executions", "automation_steps", "automations",
    "bot_flows", "call_logs", "call_scripts", "caller_attendance_overrides",
    "caller_status_logs", "callers", "conversations",
    "incidents", "knowledge_chunks", "knowledge_documents", "message_templates",
    "meta_templates", "phone_number_quality_history", "phone_numbers",
    "reengagement_logs", "reengagement_steps", "segment_templates",
    "telecalling_upload_batches", "voice_numbers", "whatsapp_insights_snapshots",
    "ad_campaigns", "app_notifications",
    "app_audit_logs", "leads", "app_settings", "tenant_users",
]


@router.delete("/clients/{tenant_id}")
def delete_client(tenant_id: str, _admin: dict = Depends(get_system_admin)):
    db = get_supabase()
    tenant = db.table("tenants").select("id, name").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant_name = tenant.data["name"]

    owner_row = (
        db.table("tenant_users").select("user_id")
        .eq("tenant_id", tenant_id).eq("role", "owner")
        .maybe_single().execute()
    )
    caller_users = (
        db.table("callers").select("user_id")
        .eq("tenant_id", tenant_id)
        .not_.is_("user_id", "null")
        .execute()
    )
    user_ids_to_delete = []
    if owner_row.data and owner_row.data.get("user_id"):
        user_ids_to_delete.append(owner_row.data["user_id"])
    for c in (caller_users.data or []):
        if c.get("user_id"):
            user_ids_to_delete.append(c["user_id"])

    for table in _ALL_TENANT_TABLES:
        try:
            db.table(table).delete().eq("tenant_id", tenant_id).execute()
        except Exception as e:
            logger.warning("delete_client: could not clear %s: %s", table, e)

    db.table("tenants").delete().eq("id", tenant_id).execute()

    for uid in user_ids_to_delete:
        try:
            db.auth.admin.delete_user(uid)
        except Exception as e:
            logger.warning("delete_client: could not delete auth user %s: %s", uid, e)

    logger.warning("OPERATOR DELETE CLIENT: %s (%s) — all data purged", tenant_name, tenant_id)
    return {"deleted": True, "tenant_name": tenant_name}


@router.get("/clients/{tenant_id}/audit-logs")
def client_audit_logs(
    tenant_id: str,
    page: int = 1,
    limit: int = 50,
    date_from: str | None = None,
    date_to: str | None = None,
    _admin: dict = Depends(get_system_admin),
):
    db = get_supabase()
    tenant = db.table("tenants").select("id").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    q = db.table("app_audit_logs").select(
        "id, actor_user_id, actor_role, action, target_type, target_id, metadata, created_at",
        count="exact",
    ).eq("tenant_id", tenant_id)

    if date_from:
        q = q.gte("created_at", date_from)
    if date_to:
        q = q.lte("created_at", date_to + "T23:59:59.999Z")

    offset = (page - 1) * limit
    result = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    return {"data": result.data or [], "total": result.count or 0, "page": page, "limit": limit}


@router.get("/clients/{tenant_id}/audit-logs/csv")
def client_audit_logs_csv(
    tenant_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    _admin: dict = Depends(get_system_admin),
):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    db = get_supabase()
    tenant = db.table("tenants").select("id, name").eq("id", tenant_id).maybe_single().execute()
    if not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    q = db.table("app_audit_logs").select(
        "id, actor_user_id, actor_role, action, target_type, target_id, metadata, created_at",
    ).eq("tenant_id", tenant_id)

    if date_from:
        q = q.gte("created_at", date_from)
    if date_to:
        q = q.lte("created_at", date_to + "T23:59:59.999Z")

    result = q.order("created_at", desc=True).limit(5000).execute()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Time", "Action", "Actor Role", "Target Type", "Target ID", "Details"])
    for r in (result.data or []):
        meta = r.get("metadata") or {}
        details = "; ".join(f"{k}={v}" for k, v in meta.items() if v is not None and v != "********")
        writer.writerow([
            r.get("created_at", ""),
            r.get("action", ""),
            r.get("actor_role", ""),
            r.get("target_type", ""),
            r.get("target_id", ""),
            details,
        ])

    buf.seek(0)
    filename = f"audit-log-{tenant.data['name'].replace(' ', '_')}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
