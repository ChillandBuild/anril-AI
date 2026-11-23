import logging
import re
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, get_tenant_and_role, get_tenant_id, require_permission
from app.dependencies.auth import get_current_user
from app.services.notification_config import (
    get_notification_config,
    save_notification_config,
    _NOTIFICATION_CONFIG_DEFAULT,
)

logger = logging.getLogger(__name__)
router = APIRouter()
require_settings_read = require_permission("settings.view")
require_settings_manage = require_permission("settings.manage")

_VALID_AUDIENCE = {"telecallers_and_admin", "telecallers_only", "admin_only", "specific"}
_VALID_SEGMENTS = {"A", "B", "C", "D"}


class QuietHours(BaseModel):
    enabled: bool = False
    start_hour: int = Field(22, ge=0, le=23)
    end_hour: int = Field(8, ge=0, le=23)


class WhatsAppNotificationConfig(BaseModel):
    enabled: bool = False
    recipient_phones: list[str] = []
    template_id: str | None = None
    target_segments: list[str] = ["A"]
    delay_minutes: int = Field(5, ge=0, le=1440)

    @field_validator("recipient_phones")
    @classmethod
    def _validate_phones(cls, v: list[str]) -> list[str]:
        pattern = re.compile(r"^\+[1-9]\d{6,14}$")
        for phone in v:
            if not pattern.match(phone):
                raise ValueError(f"Invalid E.164 phone number: {phone}")
        return v

    @field_validator("target_segments")
    @classmethod
    def _validate_segments(cls, v: list[str]) -> list[str]:
        invalid = set(v) - _VALID_SEGMENTS
        if invalid:
            raise ValueError(f"Invalid segment(s): {sorted(invalid)}")
        return v


class WhatsAppEscalationConfig(WhatsAppNotificationConfig):
    """Same shape and validation as the segment-change block, but fired on
    handover creation. Shorter default delay — an unclaimed escalation is
    more urgent than a segment promotion."""
    delay_minutes: int = Field(3, ge=0, le=1440)


class NotificationConfigIn(BaseModel):
    push_enabled: bool = True
    events: dict[str, bool] = {}
    claimable_threshold_minutes: int = Field(15, ge=1, le=120)
    claimable_audience: str = "telecallers_and_admin"
    claimable_caller_ids: list[str] = []
    quiet_hours: QuietHours = QuietHours()
    whatsapp_notifications: WhatsAppNotificationConfig = WhatsAppNotificationConfig()
    whatsapp_escalation_notifications: WhatsAppEscalationConfig = WhatsAppEscalationConfig()

# Alert types that carry order/payment money information. Only the owner or someone with deals.view
# gets them. Keep in step with the "money" category in frontend/components/bell/alertKinds.ts.
MONEY_ALERT_TYPES = (
    "deal_double_payment",
    "intake_double_payment",
    "intake_paid",
    "quote_accepted",
    "day_closing",
    "purchase_order",
)

_READ_WINDOW_DAYS = 7
_INCLUDE_READ_LIMIT = 100


@router.get("/")
async def list_notifications(
    include_read: bool = False,
    ctx: dict = Depends(get_tenant_and_role),
    user: dict = Depends(get_current_user)
):
    """Fetch notifications for the current user.

    Default: unread only (max 50). Money alerts are left out for people without deals.view. `?include_read=true`: every unread alert plus the read ones from
    the last 7 days, newest first (max 100).
    """
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    query = (
        db.table("app_notifications")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("user_id", user["user_id"])
    )
    if not _has_permission(ctx, "deals.view"):
        query = query.not_.in_("type", list(MONEY_ALERT_TYPES))
    if include_read:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_READ_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Unread alerts always show (even older than 7 days); read ones only inside the window.
        query = query.or_(f"is_read.eq.false,created_at.gte.{cutoff}").order("created_at", desc=True).limit(_INCLUDE_READ_LIMIT)
    else:
        query = query.eq("is_read", False).order("created_at", desc=True).limit(50)
    rows = query.execute()

    return {"data": rows.data or []}

@router.patch("/read")
async def mark_all_notifications_read(
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(get_current_user)
):
    """Mark all unread notifications as read for the current user."""
    db = get_supabase()
    db.table("app_notifications").update({"is_read": True}).eq("tenant_id", tenant_id).eq("user_id", user["user_id"]).eq("is_read", False).execute()
    return {"success": True}


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: dict = Depends(get_current_user)
):
    """Mark a specific notification as read."""
    db = get_supabase()

    row = (
        db.table("app_notifications")
        .update({"is_read": True})
        .eq("id", notification_id)
        .eq("tenant_id", tenant_id)
        .eq("user_id", user["user_id"])
        .execute()
    )
    
    return {"success": True, "data": row.data[0] if row.data else None}

@router.get("/pool")
async def list_pool_items(
    tenant_id: str = Depends(get_tenant_id),
):
    """Currently-actionable shared-pool items for the claim banner.

    Reflects live state (not stale notifications): pending unassigned handovers.
    Returns at most 20.
    """
    db = get_supabase()
    items: list[dict] = []
    try:
        handovers = (
            db.table("chat_handovers")
            .select("id, lead_id, reason, opened_at, leads(name)")
            .eq("tenant_id", tenant_id)
            .eq("status", "pending")
            .is_("assigned_to", "null")
            .order("opened_at", desc=True)
            .limit(20)
            .execute()
        )
        for h in (handovers.data or []):
            lead = h.get("leads") or {}
            items.append({
                "kind": "handover",
                "id": h["id"],
                "lead_id": h["lead_id"],
                "lead_name": lead.get("name") if isinstance(lead, dict) else None,
                "reason": h.get("reason"),
                "created_at": h.get("opened_at"),
            })
    except Exception as e:
        logger.warning(f"pool handovers fetch failed (transient?): {e}")

    return {"data": items}


@router.get("/config")
async def get_config(ctx: dict = Depends(require_settings_read)):
    cfg = get_notification_config(ctx["tenant_id"])
    # v9.2 #26: show the quiet time that really applies (9 PM-9 AM when the owner never chose), so saving
    # this older form keeps it rather than quietly switching quiet time off.
    from app.services.notification_config import effective_quiet_hours
    cfg["quiet_hours"] = {**(cfg.get("quiet_hours") or {}), **effective_quiet_hours(cfg)}
    return cfg


@router.put("/config")
async def update_config(payload: NotificationConfigIn, ctx: dict = Depends(require_settings_manage)):
    if payload.claimable_audience not in _VALID_AUDIENCE:
        raise HTTPException(status_code=422, detail="Invalid claimable_audience")
    # Whitelist event keys to the known set; ignore unknown keys.
    allowed_events = set(_NOTIFICATION_CONFIG_DEFAULT["events"].keys())
    events = {k: bool(v) for k, v in payload.events.items() if k in allowed_events}
    # caller_ids only meaningful for the "specific" audience; store [] otherwise.
    caller_ids = (
        [str(c) for c in payload.claimable_caller_ids]
        if payload.claimable_audience == "specific" else []
    )
    config = {
        "push_enabled": payload.push_enabled,
        "events": {**_NOTIFICATION_CONFIG_DEFAULT["events"], **events},
        "claimable_threshold_minutes": payload.claimable_threshold_minutes,
        "claimable_audience": payload.claimable_audience,
        "claimable_caller_ids": caller_ids,
        "quiet_hours": payload.quiet_hours.model_dump(),
        "whatsapp_notifications": payload.whatsapp_notifications.model_dump(),
        "whatsapp_escalation_notifications": payload.whatsapp_escalation_notifications.model_dump(),
    }
    save_notification_config(ctx["tenant_id"], config)
    return config
