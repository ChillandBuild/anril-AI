"""v9.2 #26 Automations: everything that runs by itself, from every module, in one list.

collect_automations() reads each module's own tables and settings; list_automations() adds the paused state
(automation_pauses, see template_pauses.py). set_automation_on() flips the ones that have a switch here."""
import logging

from app.services import comeback_offer, evening_summary
from app.services.automation_store import read_setting, template_status_of

logger = logging.getLogger(__name__)

PAUSE_STATUSES = ("REJECTED", "PAUSED", "DISABLED")
STATUS_WORDS = {
    "REJECTED": "WhatsApp turned this message down",
    "PAUSED": "WhatsApp paused this message",
    "DISABLED": "WhatsApp turned this message off",
}

HREFS = {
    "auto_message": "/dashboard/auto-messages",
    "scheduled_template": "/dashboard/scheduled-templates",
    "reengagement": "/dashboard/settings/follow-ups",
    "feedback": "/dashboard/leads?tab=feedback",
    "evening_summary": "/dashboard/automations",
    "comeback_offer": "/dashboard/automations",
    "balance_reminders": "/dashboard/settings/payments",
    "fee_reminders": "/dashboard/catalog/courses",
    "booking_reminders": "/dashboard/bookings",
    "back_in_stock": "/dashboard/catalog",
}


OWN_PAGE_KEYS = ("balance_reminders", "fee_reminders", "booking_reminders", "back_in_stock")  # switched on their own pages


def _humanise(key: str) -> str:
    return (key or "").replace("_", " ").strip().capitalize() or "Auto message"


def _safe(label: str, fn) -> list[dict]:
    try:
        return fn()
    except Exception as e:                       # a table that is missing or a read that fails: that part shows nothing
        logger.warning(f"automations: {label} not read: {e}")
        return []


def _auto_messages(db, tenant_id: str) -> list[dict]:
    from app.services.auto_messages import BUILTIN_EVENTS
    rules = db.table("auto_message_rules").select("id, event, template_id, enabled").eq("tenant_id", tenant_id).execute().data or []
    if not rules:
        return []
    labels = {e["key"]: e["label"] for e in BUILTIN_EVENTS}
    for r in _safe("custom events", lambda: db.table("auto_message_events").select("key, label").eq("tenant_id", tenant_id).execute().data or []):
        labels[r["key"]] = r["label"]
    tids = sorted({r["template_id"] for r in rules if r.get("template_id")})
    tpl = {}
    if tids:
        tpl = {t["id"]: t for t in db.table("message_templates").select("id, name, status").eq("tenant_id", tenant_id).in_("id", tids).execute().data or []}
    out = []
    for r in rules:
        t = tpl.get(r.get("template_id")) or {}
        out.append({
            "key": f"auto_message:{r['id']}", "name": f"Auto message: {labels.get(r['event'], _humanise(r['event']))}",
            "kind": "auto_message", "on": bool(r.get("enabled")), "template_name": t.get("name"),
            "template_status": (t.get("status") or "PENDING").upper() if t else None,
            "href": HREFS["auto_message"], "switchable": True, "note": None,
        })
    return out


def _scheduled(db, tenant_id: str) -> list[dict]:
    rows = (
        db.table("scheduled_template_sends").select("id").eq("tenant_id", tenant_id).eq("status", "scheduled")
        .limit(1000).execute().data or []
    )
    return [{
        "key": "scheduled_templates", "name": "Messages your team scheduled", "kind": "scheduled_template", "on": True,
        "template_name": None, "template_status": None, "href": HREFS["scheduled_template"], "switchable": False,
        "note": f"{len(rows)} waiting to go out" if rows else "Nothing waiting",
    }]


def _reengagement(db, tenant_id: str) -> list[dict]:
    steps = (
        db.table("reengagement_steps").select("id, type, delay_hours, message_type, template_name")
        .eq("tenant_id", tenant_id).order("delay_hours").execute().data or []
    )
    out = []
    for s in steps:
        hours = int(s.get("delay_hours") or 0)
        wait = f"{hours // 24} day{'s' if hours // 24 != 1 else ''}" if hours >= 24 and hours % 24 == 0 else f"{hours} hours"
        who = "a broadcast" if s.get("type") == "broadcast" else "a chat"
        name = s.get("template_name") if s.get("message_type") == "template" else None
        label = (f"Follow-up {wait} after a campaign reply with no order" if s.get("type") == "campaign_reply"
                 else f"Follow-up {wait} after {who} goes quiet")
        out.append({
            "key": f"reengagement:{s['id']}", "name": label, "kind": "reengagement",
            "on": True, "template_name": name, "template_status": template_status_of(db, tenant_id, name) if name else None,
            "href": HREFS["reengagement"], "switchable": False, "note": None,
        })
    return out


def _feedback(db, tenant_id: str) -> list[dict]:
    from app.services import customer_feedback as cf
    on = (read_value(db, tenant_id, cf.ON_KEY) or "").strip().lower() == "true"
    return [{
        "key": "feedback_ask", "name": "Ask for stars after an order or a visit", "kind": "feedback", "on": on,
        "template_name": cf.TEMPLATE_NAME, "template_status": template_status_of(db, tenant_id, cf.TEMPLATE_NAME),
        "href": HREFS["feedback"], "switchable": True, "note": None,
    }]


def read_value(db, tenant_id: str, key: str) -> str | None:
    try:
        row = db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", key).maybe_single().execute()
        return (row.data or {}).get("value") if row else None
    except Exception as e:
        logger.warning(f"automations: setting {key} not read: {e}")
        return None


def _evening(db, tenant_id: str) -> list[dict]:
    s = evening_summary.get_settings(db, tenant_id)
    return [{
        "key": "evening_summary", "name": "Evening summary to the owner, 8 PM", "kind": "evening_summary", "on": s["on"],
        "template_name": evening_summary.TEMPLATE_NAME, "template_status": s["template_status"],
        "href": HREFS["evening_summary"], "switchable": True, "note": s["note"],
    }]


def _comeback(db, tenant_id: str) -> list[dict]:
    s = comeback_offer.get_settings(db, tenant_id)
    return [{
        "key": "comeback_offer", "name": "Come-back offer for customers who stopped buying", "kind": "comeback_offer",
        "on": s["on"], "template_name": s["template_name"], "template_status": s["template_status"],
        "href": HREFS["comeback_offer"], "switchable": True, "note": s["cost_note"],
    }]


def _has_rows(db, tenant_id: str, table: str) -> bool:
    return bool(db.table(table).select("tenant_id").eq("tenant_id", tenant_id).limit(1).execute().data)


def _own_page(key: str, name: str, kind: str, on: bool, template_name: str | None, status: str | None, note: str | None) -> dict:
    """A reminder that is switched on its own page: shown here with its state and a link, no switch of its own.
    The template is named only while it is on, so a WhatsApp pause on it is raised (and the owner told) only for live ones."""
    return {"key": key, "name": name, "kind": kind, "on": on, "template_name": template_name if on else None,
            "template_status": status if on else None, "href": HREFS[key], "switchable": False, "note": note}


def _balance_reminders(db, tenant_id: str) -> list[dict]:
    from app.services import orders
    name = orders.ORDER_TEMPLATES["reminder"]["name"]
    on = orders.balance_reminders_on(db, tenant_id)
    if on and not _has_rows(db, tenant_id, "deals"):
        return []                                     # no orders yet: nothing to remind about
    return [_own_page("balance_reminders", "Reminders for money still to pay on an order", "balance_reminders", on, name,
                      template_status_of(db, tenant_id, name), "Day 1, 3 and 7 after a payment link. Switch it in Settings > Payments.")]


def _fee_reminders(db, tenant_id: str) -> list[dict]:
    from app.services import fee_plans
    on = fee_plans.reminders_on(tenant_id)
    if not on and not _has_rows(db, tenant_id, "fee_plans"):
        return []                                     # a business with no course fees has nothing to list
    name = fee_plans.FEE_TEMPLATE["name"]
    return [_own_page("fee_reminders", "Course fee reminders", "fee_reminders", on, name,
                      fee_plans.template_status(db, tenant_id), "Sent before each fee is due. Switch it on the Courses page.")]


def _booking_reminders(db, tenant_id: str) -> list[dict]:
    from app.services import booking_messages
    if not (_has_rows(db, tenant_id, "booking_settings") or _has_rows(db, tenant_id, "bookings")):
        return []
    name = booking_messages.BOOKING_TEMPLATES["reminder"]["name"]
    status = template_status_of(db, tenant_id, name)
    on = status == "APPROVED"
    return [_own_page("booking_reminders", "Booking reminders", "booking_reminders", on, name, status,
                      "Sent the day before and 2 hours before a booking." if on
                      else "Starts by itself once the booking messages are approved by WhatsApp. Set them up in Bookings.")]


def _back_in_stock(db, tenant_id: str) -> list[dict]:
    from app.services import stock_asks
    name = stock_asks.TEMPLATE_NAME
    status = template_status_of(db, tenant_id, name)
    if status is None and not _has_rows(db, tenant_id, "stock_waitlist"):
        return []
    on = status == "APPROVED"
    return [_own_page("back_in_stock", "Back-in-stock message", "back_in_stock", on, name, status,
                      "Goes to people who asked when you mark an item back in stock." if on
                      else "Needs the back-in-stock message approved by WhatsApp. Set it up in Catalogue.")]


def collect_automations(db, tenant_id: str) -> list[dict]:
    """Every automation of the business with its template and on/off, before the paused state is added."""
    out: list[dict] = []
    for label, fn in (("auto messages", _auto_messages), ("scheduled messages", _scheduled),
                      ("follow-ups", _reengagement), ("feedback", _feedback),
                      ("evening summary", _evening), ("come-back offer", _comeback),
                      ("balance reminders", _balance_reminders), ("fee reminders", _fee_reminders),
                      ("booking reminders", _booking_reminders), ("back in stock", _back_in_stock)):
        out += _safe(label, lambda fn=fn: fn(db, tenant_id))
    return out


def list_automations(db, tenant_id: str) -> list[dict]:
    from app.services.template_pauses import open_pauses
    pauses = open_pauses(db, tenant_id)
    out = []
    for a in collect_automations(db, tenant_id):
        a = dict(a)
        pause = pauses.get(a["key"])
        status = a.get("template_status")
        reason = None
        if pause:
            reason = pause["reason"]
        elif status in PAUSE_STATUSES:
            # Not paused by Anril yet (the news came before this version) but the message cannot go out.
            reason = f"{STATUS_WORDS[status]}, so this waits"
        a["paused_reason"] = reason
        a["paused"] = bool(reason)
        out.append(a)
    return out


# ───────────────────────────────────────────────────────────── switches

class NotSwitchable(Exception):
    pass


def set_automation_on(db, tenant_id: str, key: str, on: bool) -> None:
    """Turn one automation on or off. Raises NotSwitchable (switch it on its own page) or LookupError (no such one)."""
    from datetime import datetime, timezone
    if key.startswith("auto_message:"):
        rid = key.split(":", 1)[1]
        rows = db.table("auto_message_rules").select("id").eq("id", rid).eq("tenant_id", tenant_id).limit(1).execute().data or []
        if not rows:
            raise LookupError(key)
        db.table("auto_message_rules").update({"enabled": bool(on), "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", rid).eq("tenant_id", tenant_id).execute()
    elif key == "feedback_ask":
        from app.config_dynamic import invalidate_cache
        from app.services import customer_feedback as cf
        db.table("app_settings").upsert({
            "tenant_id": tenant_id, "key": cf.ON_KEY, "value": "true" if on else "false", "is_secret": False,
            "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()
        invalidate_cache(cf.ON_KEY)
    elif key == "evening_summary":
        evening_summary.save_on(db, tenant_id, on)
    elif key == "comeback_offer":
        comeback_offer.set_on(db, tenant_id, on)
    elif key in OWN_PAGE_KEYS or key == "scheduled_templates" or key.startswith("reengagement:"):
        raise NotSwitchable(key)
    else:
        raise LookupError(key)


def force_off(db, tenant_id: str, key: str) -> None:
    """Switch off without the checks that turning ON has (used when a template is paused)."""
    if key == "comeback_offer":
        from app.services.automation_store import write_setting
        s = read_setting(db, tenant_id, comeback_offer.SETTING_KEY)
        s["on"] = False
        write_setting(db, tenant_id, comeback_offer.SETTING_KEY, s)
    else:
        set_automation_on(db, tenant_id, key, False)
