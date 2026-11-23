"""v9.2 #26 Settings > Alerts: every alert the app can raise, who gets it and how, and the on/off switch.

The on/off switch of an alert is notification_config["events"][key] (the same switch the push gate reads).
Who gets it is recorded per business in app_settings "alert_recipients" (a separate key, so the older
Settings > Notifications form cannot wipe it when it saves). Quiet time lives in notification_config too.
"""
import json
import logging

from fastapi import HTTPException

from app.services.notification_config import (
    QUIET_TIME_DEFAULT,
    effective_quiet_hours,
    get_notification_config,
    save_notification_config,
    allowed_in_quiet_time,
    invalidate_policy_cache,
    is_always_on,
)

logger = logging.getLogger(__name__)

RECIPIENTS_KEY = "alert_recipients"

# Who can receive an alert. "owner" = the business owner, "team" = everyone who can see that area,
# "assigned" = the person the customer / lead / call belongs to.
WHO_CHOICES = ("owner", "team", "assigned")
WHO_LABELS = {"owner": "Owner", "team": "Whole team", "assigned": "The person it belongs to"}

# key = the alert type the app raises (app_notifications.type). how: bell always; push = phone/computer pop-up;
# whatsapp = a WhatsApp message to the owner's alert numbers (Settings > Alerts, WhatsApp section).
_CATALOG: tuple[dict, ...] = (
    {"key": "handover_new", "label": "The AI agent needs a person", "area": "Chats", "who": ["team"], "how": ["bell", "push", "whatsapp"]},
    {"key": "handover_unanswered", "label": "Nobody replied 15 minutes after a handover", "area": "Chats", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "lead_replied", "label": "A customer wrote back", "area": "Chats", "who": ["assigned"], "how": ["bell", "push"]},
    {"key": "hot_lead_waiting", "label": "A hot customer has waited 30 minutes for a reply", "area": "Chats", "who": ["owner", "assigned"], "how": ["bell", "push"]},
    {"key": "lead_assigned", "label": "A customer was given to you", "area": "Customers", "who": ["assigned"], "how": ["bell", "push"]},
    {"key": "callback_due", "label": "A call-back is due", "area": "Calling", "who": ["assigned"], "how": ["bell", "push"]},
    {"key": "callback_claimable", "label": "A call-back is waiting for someone", "area": "Calling", "who": ["team"], "how": ["bell", "push"]},
    {"key": "callback_taken_over", "label": "Someone took over your call-back", "area": "Calling", "who": ["assigned"], "how": ["bell", "push"]},
    {"key": "call_alerts_summary", "label": "Yesterday's calls need attention", "area": "Calling", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "intake_paid", "label": "A payment came in", "area": "Money", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "intake_double_payment", "label": "A customer paid twice (form)", "area": "Money", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "deal_double_payment", "label": "A customer paid twice (order)", "area": "Money", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "refund_done", "label": "A refund was given", "area": "Money", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "quote_accepted", "label": "A customer accepted a quote", "area": "Orders", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "day_closing", "label": "Cash does not match at day closing", "area": "Orders", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "purchase_order", "label": "A purchase order needs you", "area": "Purchases", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "batch_expiry", "label": "Stock is about to expire", "area": "Stock", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "stock_low", "label": "An item is running low (under 3 left)", "area": "Stock", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "booking_new", "label": "A new booking", "area": "Bookings", "who": ["team"], "how": ["bell", "push"]},
    {"key": "booking_cancelled", "label": "A booking was cancelled", "area": "Bookings", "who": ["team"], "how": ["bell", "push"]},
    {"key": "feedback_unhappy", "label": "An unhappy customer", "area": "Feedback", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "sms_low_balance", "label": "SMS balance is low", "area": "SMS", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "scheduled_template_failed", "label": "A scheduled message was not sent", "area": "Messages", "who": ["assigned"], "how": ["bell", "push"]},
    {"key": "intake_trigger_failed", "label": "A paid form had a problem", "area": "Forms", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "template_paused", "label": "WhatsApp paused or turned down a message template", "area": "Messages", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "number_disconnected", "label": "Your WhatsApp number is disconnected", "area": "WhatsApp", "who": ["owner"], "how": ["bell", "push"]},
    {"key": "campaign_paused", "label": "A campaign was stopped (too many said stop)", "area": "Messages", "who": ["owner"], "how": ["bell", "push"]},
)

_BY_KEY = {a["key"]: a for a in _CATALOG}


def who_is_fixed(key: str) -> bool:
    """Alerts about one person's own work (their customer wrote back, their call-back is due) always go to that
    person, and "number disconnected" always goes to the owner and whoever manages numbers: the senders pick the
    people, so a "who gets it" choice could only drop them. These rows show who gets it, but it cannot be changed."""
    a = _BY_KEY.get(key)
    return bool(a) and (list(a["who"]) == ["assigned"] or key == "number_disconnected")


def alert_keys() -> list[str]:
    return [a["key"] for a in _CATALOG]


def _read_recipients(db, tenant_id: str, strict: bool = False) -> dict:
    """Who gets what, as saved. strict=True raises on a read error (write paths: never save over what we could not read)."""
    try:
        row = (
            db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", RECIPIENTS_KEY)
            .maybe_single().execute()
        )
        if row and row.data and row.data.get("value"):
            stored = json.loads(row.data["value"])
            if isinstance(stored, dict):
                return {k: [w for w in v if w in WHO_CHOICES] for k, v in stored.items() if isinstance(v, list)}
    except Exception as e:
        if strict:
            raise
        logger.warning(f"alerts: could not read who gets what for {tenant_id}: {e}")
    return {}


def _cannot_save(e: Exception, tenant_id: str) -> HTTPException:
    logger.warning(f"alerts: settings not read for {tenant_id}, nothing saved: {e}")
    return HTTPException(status_code=503, detail="Could not read your saved alert settings, so nothing was changed. Please try again.")


def quiet_time_view(cfg: dict) -> dict:
    """The quiet time the owner sees: on/off, hours, and whether it is just the default."""
    quiet = effective_quiet_hours(cfg)
    return {
        "on": bool(quiet.get("enabled")),
        "start_hour": int(quiet.get("start_hour", QUIET_TIME_DEFAULT["start_hour"])),
        "end_hour": int(quiet.get("end_hour", QUIET_TIME_DEFAULT["end_hour"])),
        "is_default": bool(cfg.get("quiet_hours_unsaved")),
        "still_comes_through": [a["label"] for a in _CATALOG if allowed_in_quiet_time(a["key"])],
    }


def list_alerts(db, tenant_id: str) -> dict:
    cfg = get_notification_config(tenant_id, db=db)
    events = cfg.get("events") or {}
    recipients = _read_recipients(db, tenant_id)
    push_on = bool(cfg.get("push_enabled", True))
    alerts = []
    for a in _CATALOG:
        how = [h for h in a["how"] if h != "push" or push_on]
        alerts.append({
            "key": a["key"],
            "label": a["label"],
            "area": a["area"],
            # With no saved choice delivery_allowed lets everyone the app addresses through, so the list says "team".
            "who": list(a["who"]) if who_is_fixed(a["key"]) else (recipients.get(a["key"]) or ["team"]),
            "who_fixed": who_is_fixed(a["key"]),
            "how": how,
            # An always-on alert shows as on and locked, whatever an older save says.
            "on": True if is_always_on(a["key"]) else bool(events.get(a["key"], True)),
            "locked": is_always_on(a["key"]),
            "comes_through_in_quiet_time": allowed_in_quiet_time(a["key"]),
        })
    return {"alerts": alerts, "quiet_time": quiet_time_view(cfg), "who_labels": WHO_LABELS}


def set_alert(db, tenant_id: str, key: str, on: bool, who: list[str] | None = None) -> dict:
    """Turn one alert on or off and, when `who` is given, change who gets it. Raises KeyError / ValueError."""
    if key not in _BY_KEY:
        raise KeyError(key)
    if not on and is_always_on(key):
        raise ValueError("This alert cannot be switched off. It is about money, a customer who needs a person, or a disconnected number.")
    if who is not None and not who_is_fixed(key):
        clean = [w for w in dict.fromkeys(who) if w in WHO_CHOICES]
        if not clean or len(clean) != len(set(who)):
            raise ValueError("Pick who should get this alert: the owner, the whole team, or the person it belongs to.")
        try:
            recipients = _read_recipients(db, tenant_id, strict=True)
        except Exception as e:
            raise _cannot_save(e, tenant_id)
        recipients[key] = clean
        db.table("app_settings").upsert(
            {"tenant_id": tenant_id, "key": RECIPIENTS_KEY, "value": json.dumps(recipients), "is_secret": False},
            on_conflict="tenant_id,key",
        ).execute()
        invalidate_policy_cache(tenant_id)
    try:
        cfg = get_notification_config(tenant_id, db=db, strict=True)
    except Exception as e:
        raise _cannot_save(e, tenant_id)
    cfg["events"] = {**(cfg.get("events") or {}), key: bool(on)}
    save_notification_config(tenant_id, cfg, db=db)
    invalidate_policy_cache(tenant_id)
    return next(a for a in list_alerts(db, tenant_id)["alerts"] if a["key"] == key)


def set_quiet_time(db, tenant_id: str, on: bool, start_hour: int, end_hour: int) -> dict:
    """Save the owner's own quiet-time choice (from then on it is theirs, not the default)."""
    for h in (start_hour, end_hour):
        if not isinstance(h, int) or isinstance(h, bool) or not 0 <= h <= 23:
            raise ValueError("Hours must be between 0 and 23.")
    if on and start_hour == end_hour:
        raise ValueError("Quiet time needs a start and an end that are different.")
    try:
        cfg = get_notification_config(tenant_id, db=db, strict=True)
    except Exception as e:
        raise _cannot_save(e, tenant_id)
    cfg["quiet_hours"] = {"enabled": bool(on), "start_hour": start_hour, "end_hour": end_hour}
    cfg["quiet_hours_unsaved"] = False
    save_notification_config(tenant_id, cfg, db=db)
    return quiet_time_view(cfg)
