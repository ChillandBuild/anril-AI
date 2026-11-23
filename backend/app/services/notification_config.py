import json
import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# v9.2 #26 Quiet time: a business that never saved a quiet-time choice is quiet 9 PM to 9 AM (IST).
# A business that saved one (on or off, any hours) keeps it exactly. get_notification_config marks the
# never-saved case with quiet_hours_unsaved=True and effective_quiet_hours() applies this default.
QUIET_TIME_DEFAULT: dict = {"enabled": True, "start_hour": 21, "end_hour": 9}

# The only alerts that still come through during quiet time: money coming in or going out, "the AI agent
# needs a person" (a handover) and "your WhatsApp number is disconnected".
QUIET_TIME_ALLOWED_TYPES: frozenset[str] = frozenset({
    "intake_paid", "intake_double_payment", "deal_double_payment", "payment_received",
    "refund_done", "refund_issued",
    "handover_new",
    "number_disconnected", "whatsapp_disconnected",
})


def allowed_in_quiet_time(alert_type: str) -> bool:
    """True when this kind of alert may still come through during quiet time."""
    return (alert_type or "") in QUIET_TIME_ALLOWED_TYPES


_NOTIFICATION_CONFIG_DEFAULT: dict = {
    "push_enabled": True,
    "events": {
        "callback_due": True,
        "callback_claimable": True,
        "callback_taken_over": True,
        "lead_assigned": True,
        "lead_replied": True,
        "handover_new": True,
        "intake_trigger_failed": True,
        # v9.2 #26: the other alerts listed on Settings > Alerts. All on until the owner turns one off.
        "intake_paid": True,
        "intake_double_payment": True,
        "deal_double_payment": True,
        "quote_accepted": True,
        "purchase_order": True,
        "day_closing": True,
        "batch_expiry": True,
        "sms_low_balance": True,
        "booking_new": True,
        "booking_cancelled": True,
        "feedback_unhappy": True,
        "call_alerts_summary": True,
        "scheduled_template_failed": True,
        "number_disconnected": True,
        "template_paused": True,
    },
    "claimable_threshold_minutes": 15,
    "claimable_audience": "telecallers_and_admin",
    "claimable_caller_ids": [],
    "quiet_hours": {"enabled": False, "start_hour": 22, "end_hour": 8},
    "whatsapp_notifications": {
        "enabled": False,
        "recipient_phones": [],
        "template_id": None,
        "target_segments": ["A"],
        "delay_minutes": 5,
    },
    # Fired when a chat handover is created, not when a segment changes.
    # Shorter default delay: an unclaimed escalation is more urgent.
    "whatsapp_escalation_notifications": {
        "enabled": False,
        "recipient_phones": [],
        "template_id": None,
        "target_segments": ["A"],
        "delay_minutes": 3,
    },
}


def get_notification_config(tenant_id: str, db=None) -> dict:
    """Return notification_config from app_settings, deep-merged with defaults."""
    db = db or get_supabase()
    merged = {
        **_NOTIFICATION_CONFIG_DEFAULT,
        "events": dict(_NOTIFICATION_CONFIG_DEFAULT["events"]),
        "quiet_hours": dict(_NOTIFICATION_CONFIG_DEFAULT["quiet_hours"]),
        "whatsapp_notifications": dict(_NOTIFICATION_CONFIG_DEFAULT["whatsapp_notifications"]),
        "whatsapp_escalation_notifications": dict(
            _NOTIFICATION_CONFIG_DEFAULT["whatsapp_escalation_notifications"]
        ),
    }
    try:
        row = (
            db.table("app_settings")
            .select("value")
            .eq("tenant_id", tenant_id)
            .eq("key", "notification_config")
            .maybe_single()
            .execute()
        )
        saved_quiet = False
        if row and row.data:
            stored = json.loads(row.data["value"])
            if isinstance(stored, dict):
                saved_quiet = isinstance(stored.get("quiet_hours"), dict)
                merged["events"] = {**merged["events"], **(stored.get("events") or {})}
                merged["quiet_hours"] = {**merged["quiet_hours"], **(stored.get("quiet_hours") or {})}
                merged["whatsapp_notifications"] = {**merged["whatsapp_notifications"], **(stored.get("whatsapp_notifications") or {})}
                merged["whatsapp_escalation_notifications"] = {
                    **merged["whatsapp_escalation_notifications"],
                    **(stored.get("whatsapp_escalation_notifications") or {}),
                }
                for k in ("push_enabled", "claimable_threshold_minutes", "claimable_audience", "claimable_caller_ids"):
                    if k in stored:
                        merged[k] = stored[k]
        # The settings were read fine and carry no quiet-time choice: the new default applies.
        merged["quiet_hours_unsaved"] = not saved_quiet
    except Exception as e:
        logger.warning(f"get_notification_config failed for {tenant_id}: {e}")
    return merged


def save_notification_config(tenant_id: str, config: dict, db=None) -> None:
    """Persist notification_config to app_settings."""
    # quiet_hours_unsaved is a read-time marker, never stored. While it is set the owner has made no quiet-time
    # choice, so the default quiet_hours block is left out too (saving it would turn a default into a "choice").
    unsaved = bool(config.get("quiet_hours_unsaved"))
    config = {k: v for k, v in config.items() if k != "quiet_hours_unsaved" and not (unsaved and k == "quiet_hours")}
    db = db or get_supabase()
    db.table("app_settings").upsert(
        {
            "key": "notification_config",
            "value": json.dumps(config),
            "tenant_id": tenant_id,
            "is_secret": False,
        },
        on_conflict="tenant_id,key",
    ).execute()


def effective_quiet_hours(cfg: dict) -> dict:
    """The quiet-time window that really applies: the saved one, or the default when none was ever saved."""
    if cfg.get("quiet_hours_unsaved"):
        return dict(QUIET_TIME_DEFAULT)
    return cfg.get("quiet_hours") or {}


def _in_quiet_hours(quiet: dict, ist_hour: int) -> bool:
    """True if ist_hour falls inside the configured quiet window. Handles midnight wrap."""
    if not quiet.get("enabled"):
        return False
    start = quiet.get("start_hour", 22)
    end = quiet.get("end_hour", 8)
    if start == end:
        return False
    if start < end:
        return start <= ist_hour < end
    return ist_hour >= start or ist_hour < end


def push_allowed(tenant_id: str, event_type: str, *, db=None) -> bool:
    """Whether a web push for this event type may be delivered right now.

    Gates on master switch, per-event toggle (unknown types default allowed),
    and quiet hours (IST). In-app notifications are NEVER gated by this.
    """
    # Fail open: if the config can't be read/evaluated, allow the push rather
    # than silently dropping it — push is best-effort and the in-app row is
    # already written regardless.
    try:
        cfg = get_notification_config(tenant_id, db=db)
        if not cfg.get("push_enabled"):
            return False
        if not cfg.get("events", {}).get(event_type, True):
            return False
        quiet = effective_quiet_hours(cfg)
        if quiet.get("enabled") and not allowed_in_quiet_time(event_type):
            ist_hour = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).hour
            if _in_quiet_hours(quiet, ist_hour):
                return False
        return True
    except Exception as e:
        logger.warning(f"push_allowed check failed for {tenant_id}/{event_type}: {e}")
        return True
