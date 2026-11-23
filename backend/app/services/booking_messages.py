"""Bookings: WhatsApp messages, reminders and the background jobs (v9.2 #19).

What the customer hears, and when:
  * a booking is made / moved / cancelled  -> one plain message (text inside WhatsApp's 24-hour window,
    else the approved "anril_booking_update" template, else nothing and it is logged);
  * the day before (20-28 h away, sent 9 AM-8 PM IST) and 2 hours before -> "anril_booking_reminder"
    with two quick replies, "Yes, coming" / "Cancel" (payloads bk_yes:<id> / bk_cancel:<id>);
  * the customer's replies come back through handle_booking_code / _button / _reaction (the planner
    wires them into routes/webhook.py).

Every public send here returns a bool and never raises: the booking change it follows has already
happened. Money is never touched here except releasing an unpaid hold (services/booking_orders.py).
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
LIVE = ("held", "booked", "came")
DEFAULT_CUTOFF_MIN = 180
CODE_ONLY_MAX = 40            # a message this short with a code in it is "just the code"
REMINDER_HOURS_IST = (9, 20)          # day-before reminder only from 9 AM until 8 PM IST
REMINDER_2H_WINDOW = (timedelta(hours=1, minutes=45), timedelta(hours=2, minutes=15))
DAY_WINDOW = (timedelta(hours=20), timedelta(hours=28))
MIN_BEFORE = timedelta(hours=2, minutes=15)  # a day-before reminder never lands inside the 2 h one
CALL_NOW_AFTER = timedelta(minutes=60)
QUIET_FROM, QUIET_TO = 22, 7   # no 2-hour reminder from 10 PM until 7 AM IST
YES_TITLE, CANCEL_TITLE = "Yes, coming", "Cancel"
YES_PREFIX, CANCEL_PREFIX = "bk_yes:", "bk_cancel:"

# The two utility templates the owner submits once (Bookings > Booking link > Set up booking messages).
BOOKING_TEMPLATES = {
    "update": {
        "name": "anril_booking_update",
        "body": "Hi {{1}}, your {{2}} booking is on {{3}} with {{4}}. Code {{5}}.",
        "examples": ["Priya", "Reading", "Thu 28 Nov, 4:00 PM", "Ravi", "BK-0012"],
    },
    "reminder": {
        "name": "anril_booking_reminder",
        "body": "Reminder: {{1}}, your {{2}} booking is {{3}} with {{4}}.",
        "examples": ["Priya", "Reading", "tomorrow, Thu 28 Nov, 4:00 PM", "Ravi"],
        "buttons": [YES_TITLE, CANCEL_TITLE],
    },
}

_ID = r"[A-Za-z0-9\-]{1,64}"
_CODE_RE = re.compile(r"\bbk[\s\-#:]*0*(\d{1,6})\b", re.I)
_SKIN_TONES = "\U0001F3FB\U0001F3FC\U0001F3FD\U0001F3FE\U0001F3FF️"


async def _io(fn, *args, **kwargs):
    """Run a blocking database call off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def booking_code(number) -> str:
    return f"BK-{int(number or 0):04d}"


def when_text(start_at) -> str:
    """IST, plain: 'Thu 28 Nov, 4:00 PM'."""
    d = _parse(start_at)
    if not d:
        return ""
    d = d.astimezone(IST)
    hour = d.hour % 12 or 12
    return f"{d:%a} {d.day} {d:%b}, {hour}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def clean_text(value: str | None, limit: int = 120) -> str:
    """A customer-supplied value made safe to put in a message: invisible and zero-width characters
    removed, control characters and line breaks turned into spaces, whitespace collapsed."""
    out = []
    for ch in str(value or ""):
        cat = unicodedata.category(ch)
        if cat == "Cf":
            continue                       # zero-width space/joiner, bidi marks, BOM ...
        out.append(" " if cat in ("Cc", "Zl", "Zp") else ch)
    return " ".join("".join(out).split())[:limit]


def _first_name(name: str | None) -> str:
    return (clean_text(name, 40).split(" ") or [""])[0] or "there"


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


def phone_ok(b: dict) -> bool:
    """False only for a link (website) booking whose number nobody has confirmed yet."""
    return bool(b.get("phone_checked")) or b.get("source") != "link"


def _hours_words(minutes: int) -> str:
    if minutes % 60 == 0:
        h = minutes // 60
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{minutes} minutes"


# ───────────────────────────────────────────────────────────── templates

def _template_rows(db, tenant_id: str) -> dict:
    from app.config_dynamic import get_setting
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    names = [t["name"] for t in BOOKING_TEMPLATES.values()]
    rows = (
        db.table("message_templates").select("name, status, meta_waba_id").eq("tenant_id", tenant_id)
        .in_("name", names).execute()
    ).data or []
    return {r["name"]: r for r in rows if not waba_id or r.get("meta_waba_id") == waba_id}


def templates_status(db, tenant_id: str) -> dict:
    """{"update": status|None, "reminder": status|None}. None = never submitted."""
    by_name = _template_rows(db, tenant_id)
    out = {}
    for key, t in BOOKING_TEMPLATES.items():
        row = by_name.get(t["name"])
        out[key] = ((row.get("status") or "PENDING").upper()) if row else None
    return out


async def submit_templates(db, tenant_id: str, ctx: dict | None = None) -> dict:
    """Submit the missing or rejected booking templates to Meta (utility, English), through the
    Templates page's own path. Returns {"templates": templates_status, "problems": [str]}."""
    from fastapi import HTTPException
    from app.routes.templates import Button, CreateTemplate, create_template

    status = templates_status(db, tenant_id)
    problems: list[str] = []
    for key, spec in BOOKING_TEMPLATES.items():
        if status.get(key) not in (None, "REJECTED"):
            continue
        try:
            buttons = [Button(type="QUICK_REPLY", text=t) for t in spec.get("buttons", [])]
            await create_template(
                CreateTemplate(name=spec["name"], category="UTILITY", language="en", body_text=spec["body"],
                               body_examples=spec["examples"], buttons=buttons or None),
                tenant_id=tenant_id, _ctx=ctx or {},
            )
        except HTTPException as e:
            problems.append(f"{spec['name']}: {e.detail}")
        except Exception as e:
            logger.warning("booking templates: %s did not submit: %s", spec["name"], e)
            problems.append(f"{spec['name']}: could not be sent to WhatsApp")
    from app.services import property_visit_messages as pvm
    await pvm.submit_templates(db, tenant_id, ctx, problems)  # property businesses only
    return {"templates": templates_status(db, tenant_id), "problems": problems}


# ───────────────────────────────────────────────────────────── loading

def _load(db, tenant_id: str, booking_id: str) -> dict | None:
    """The booking with service_name, resource_name, resource_user_id, business_name filled in."""
    rows = (
        db.table("bookings").select("*").eq("id", booking_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows:
        return None
    b = dict(rows[0])
    return _decorate(db, tenant_id, b)


def _decorate(db, tenant_id: str, b: dict) -> dict:
    svc = (db.table("booking_services").select("name").eq("id", b.get("service_id")).eq("tenant_id", tenant_id)
           .limit(1).execute()).data or []
    res = (db.table("booking_resources").select("name, user_id").eq("id", b.get("resource_id"))
           .eq("tenant_id", tenant_id).limit(1).execute()).data or []
    ten = db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute().data or []
    b["service_name"] = (svc[0]["name"] if svc else "") or "visit"
    b["resource_name"] = (res[0]["name"] if res else "") or "us"
    b["resource_user_id"] = res[0].get("user_id") if res else None
    b["business_name"] = ((ten[0].get("name") if ten else "") or "").strip()
    return b


def _lead_for(db, tenant_id: str, b: dict) -> dict:
    cols = "id, name, phone, opted_out, last_inbound_at, blocked_at"
    if b.get("lead_id"):
        rows = (db.table("leads").select(cols).eq("id", b["lead_id"]).eq("tenant_id", tenant_id)
                .is_("deleted_at", "null").limit(1).execute()).data or []
        if rows:
            return rows[0]
    if b.get("phone"):
        rows = (db.table("leads").select(cols).eq("tenant_id", tenant_id).eq("phone", b["phone"])
                .is_("deleted_at", "null").limit(1).execute()).data or []
        if rows:
            return rows[0]
    return {}


def _cutoff_min(db, tenant_id: str) -> int:
    try:
        rows = (db.table("booking_settings").select("cancel_cutoff_min").eq("tenant_id", tenant_id)
                .limit(1).execute()).data or []
        if rows and rows[0].get("cancel_cutoff_min") is not None:
            return int(rows[0]["cancel_cutoff_min"])
    except Exception:
        pass
    return DEFAULT_CUTOFF_MIN


# ───────────────────────────────────────────────────────────── delivery

async def _deliver(db, tenant_id: str, b: dict, *, text: str, template_key: str, values: list[str],
                   buttons: list[dict] | None = None, payloads: list[str] | None = None,
                   text_only: bool = False) -> tuple[str | None, str]:
    """Send one message. Returns (Meta message id | None, reason). reason is "" on success, else
    one of blocked, opted_out, no_phone, whatsapp_not_connected, outside_24h_no_template."""
    phone = b.get("phone")
    if not phone:
        return None, "no_phone"
    if not phone_ok(b):
        # A website booking nobody has proved the number for: the number may not be theirs.
        return None, "phone_not_checked"
    lead = await _io(_lead_for, db, tenant_id, b)
    from app.services import blocked_guard
    if lead.get("blocked_at") or await blocked_guard.is_blocked(tenant_id, phone):
        logger.info("booking %s: message not sent, the person is blocked", b.get("id"))
        return None, "blocked"
    if lead.get("opted_out"):
        return None, "opted_out"
    from app.config_dynamic import get_setting
    connected = await _io(lambda: bool(get_setting("meta_phone_number_id", tenant_id=tenant_id)
                                       and get_setting("meta_access_token", tenant_id=tenant_id)))
    if not connected:
        return None, "whatsapp_not_connected"
    from app.services.call_details_share import window_open

    sid, content = None, text
    if window_open(lead.get("last_inbound_at"), _now()):
        try:
            if buttons:
                from app.services.meta_cloud import send_interactive_buttons
                resp = await send_interactive_buttons(phone, text[:1024], buttons, tenant_id=tenant_id)
                sid = ((resp or {}).get("messages") or [{}])[0].get("id")
            else:
                from app.services.ai_reply import send_whatsapp
                sid = await send_whatsapp(phone, text, tenant_id=tenant_id)
        except Exception as e:  # fall through to the template
            logger.warning("booking %s: in-window send failed, trying the template: %s", b.get("id"), e)
            sid = None
    if not sid and not text_only:
        sid, content = await _send_template(db, tenant_id, phone, template_key, values, payloads)
    if not sid:
        return None, "outside_24h_no_template"
    if lead.get("id"):
        try:
            await _io(lambda: db.table("messages").insert({
                "lead_id": lead["id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
                "content": content, "is_ai_generated": False, "meta_message_id": sid,
            }).execute())
        except Exception as e:  # the customer already has it
            logger.warning("booking %s: sent but not saved to the chat: %s", b.get("id"), e)
    return sid, ""


async def _send_template(db, tenant_id: str, phone: str, key: str, values: list[str],
                         payloads: list[str] | None) -> tuple[str | None, str]:
    from app.services.call_details_share import _approved_templates, render_template
    from app.services.meta_cloud import send_template_message

    # key: a BOOKING_TEMPLATES key, or the name of a site-visit template (services/property_visit_messages.py)
    wanted = BOOKING_TEMPLATES[key]["name"] if key in BOOKING_TEMPLATES else key
    approved = await _io(_approved_templates, db, tenant_id)
    template = next((t for t in approved if t.get("name") == wanted), None)
    if not template:
        return None, ""
    vals = [_one_line(v) or "-" for v in values]
    components = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in vals]}]
    for index, payload in enumerate(payloads or []):
        components.append({"type": "button", "sub_type": "quick_reply", "index": str(index),
                           "parameters": [{"type": "payload", "payload": payload}]})
    resp = await send_template_message(phone, template["name"], template.get("language") or "en",
                                       components=components, tenant_id=tenant_id)
    sid = ((resp or {}).get("messages") or [{}])[0].get("id")
    return sid, render_template(template.get("body_text"), vals)


# ───────────────────────────────────────────────────────────── the three updates

def _update_values(b: dict, when_label: str) -> list[str]:
    return [_first_name(b.get("customer_name")), b["service_name"], when_label, b["resource_name"],
            booking_code(b.get("number"))]


def confirmation_text(b: dict) -> str:
    name, code = _first_name(b.get("customer_name")), booking_code(b.get("number"))
    if b.get("status") == "held":
        return (f"Hi {name}, we are holding your {b['service_name']} slot on {when_text(b['start_at'])} "
                f"with {b['resource_name']}. It is confirmed once the advance is paid. Code {code}.")
    return (f"Hi {name}, your {b['service_name']} booking is confirmed for {when_text(b['start_at'])} "
            f"with {b['resource_name']}. Code {code}. Reply here if you need to change it.")


async def send_confirmation(db, tenant_id: str, booking_id: str) -> bool:
    return await _send_update(db, tenant_id, booking_id, "confirmed")


async def send_moved(db, tenant_id: str, booking_id: str) -> bool:
    return await _send_update(db, tenant_id, booking_id, "moved")


async def send_cancelled(db, tenant_id: str, booking_id: str, reason: str | None = None) -> bool:
    return await _send_update(db, tenant_id, booking_id, "cancelled", reason=reason)


async def _send_update(db, tenant_id: str, booking_id: str, kind: str, *, reason: str | None = None) -> bool:
    try:
        b = await _io(_load, db, tenant_id, booking_id)
        if not b:
            return False
        name, code = _first_name(b.get("customer_name")), booking_code(b.get("number"))
        when = when_text(b["start_at"])
        if kind == "confirmed":
            text, label = confirmation_text(b), when
        elif kind == "moved":
            text = (f"Hi {name}, your {b['service_name']} booking {code} is moved to {when} "
                    f"with {b['resource_name']}.")
            label = f"{when} (new time)"
        else:
            text = f"Hi {name}, your {b['service_name']} booking {code} for {when} is cancelled."
            if reason:
                text += f" {reason.strip().rstrip('.')}."
            text += " Reply here to book another time."
            label = f"{when} (cancelled)"
        # A held slot is not confirmed yet: text only, inside the window, never the "booking is on" template.
        sid, why = await _deliver(db, tenant_id, b, text=text, template_key="update",
                                  values=_update_values(b, label), text_only=b.get("status") == "held")
        if not sid:
            logger.info("booking %s: %s message not sent (%s)", booking_id, kind, why)
        return bool(sid)
    except Exception as e:
        logger.warning("booking %s: %s message failed: %s", booking_id, kind, e)
        return False


# ───────────────────────────────────────────────────────────── bells + lead mirror

def bell_recipients(db, tenant_id: str, resource_user_id: str | None = None) -> list[str]:
    """Owners, people with bookings.manage, and the column's own person."""
    ids: list[str] = []
    try:
        users = (db.table("tenant_users").select("user_id, role, role_id").eq("tenant_id", tenant_id)
                 .execute()).data or []
        roles = (db.table("tenant_roles").select("id, permissions").eq("tenant_id", tenant_id)
                 .execute()).data or []
        managers = {r["id"] for r in roles if "bookings.manage" in (r.get("permissions") or [])}
        for u in users:
            if u.get("role") == "owner" or u.get("role_id") in managers:
                ids.append(str(u["user_id"]))
    except Exception as e:
        logger.warning("booking bell: could not list who to tell: %s", e)
    if resource_user_id and str(resource_user_id) not in ids:
        ids.append(str(resource_user_id))
    return ids


def ring_bell(db, tenant_id: str, b: dict, kind: str, title: str, message: str) -> None:
    """Never raises. url opens that day with the booking's sheet."""
    try:
        from app.services.notify import notify_user
        day = (_parse(b.get("start_at")) or _now()).astimezone(IST).date().isoformat()
        url = f"/dashboard/bookings?date={day}&booking={b['id']}"
        for uid in bell_recipients(db, tenant_id, b.get("resource_user_id")):
            notify_user(tenant_id, uid, kind, title, message, db=db, push_url=url)
    except Exception as e:
        logger.warning("booking %s: bell %s failed: %s", b.get("id"), kind, e)


def _who(b: dict) -> str:
    return clean_text(b.get("customer_name")) or clean_text(b.get("phone")) or "A customer"


def recompute_lead_mirror(db, tenant_id: str, lead_id: str | None) -> None:
    """leads.booked_for = the lead's next live booking start, or null. Never touches booked_at / lost / converted."""
    if not lead_id:
        return
    try:
        rows = (db.table("bookings").select("start_at, status").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
                .in_("status", ["held", "booked"]).gt("start_at", _iso(_now())).order("start_at")
                .limit(1).execute()).data or []
        db.table("leads").update({"booked_for": rows[0]["start_at"] if rows else None}).eq("id", lead_id).eq(
            "tenant_id", tenant_id).execute()
    except Exception as e:
        logger.warning("booking: lead mirror for %s failed: %s", lead_id, e)


# ───────────────────────────────────────────────────────────── customer replies

def _international(raw: str | None) -> str | None:
    """Full international digits for a number, or None when it cannot be trusted.
    An explicit "+" means the country code was typed: if normalising changed it (a "+9876543210"
    turned into +91 9876543210) the number is not treated as that Indian one."""
    from app.routes.upload import _normalize_phone
    n = _normalize_phone(raw or "")
    if not n:
        return None
    digits = n.lstrip("+")
    if (raw or "").strip().startswith("+") and re.sub(r"\D", "", raw) != digits:
        return None
    return digits


def _same_phone(a: str | None, b: str | None) -> bool:
    na, nb = _international(a), _international(b)
    return bool(na) and na == nb


def _find_live_by_number(db, tenant_id: str, phone: str, number: int) -> dict | None:
    rows = (db.table("bookings").select("*").eq("tenant_id", tenant_id).eq("number", number)
            .in_("status", ["held", "booked"]).limit(1).execute()).data or []
    if rows and _same_phone(rows[0].get("phone"), phone):
        return rows[0]
    return None


async def handle_booking_code(db, tenant_id: str, lead_id: str | None, phone: str, text: str) -> bool:
    """Inbound text with "BK-0012" (or "bk 12") for a live booking of THIS phone: mark the phone
    checked, link the chat's lead if empty, send the confirmation (now inside the 24 h window)."""
    try:
        m = _CODE_RE.search(text or "")
        if not m or not phone:
            return False
        b = _find_live_by_number(db, tenant_id, phone, int(m.group(1)))
        if not b:
            return False
        patch: dict = {"phone_checked": True}
        if lead_id and not b.get("lead_id"):
            patch["lead_id"] = lead_id
        db.table("bookings").update(patch).eq("id", b["id"]).eq("tenant_id", tenant_id).execute()
        b = {**b, **patch}
        # A held website booking may now be complete: paid (or no advance) + number confirmed.
        was_held = b.get("status") == "held"
        if was_held:
            b = await confirm_if_ready(db, tenant_id, b)
        flipped = was_held and b.get("status") == "booked"  # confirm_if_ready already told them
        # Only a message that is about the code gets a reply and ends the chat flow. A long
        # message that merely mentions it ("is BK-12 still free on Friday, and also...") is the AI's.
        clean = (text or "").strip()
        if len(clean) > CODE_ONLY_MAX and "booking code" not in clean.lower():
            return False
        if b.get("status") == "held":
            # Number confirmed, advance still to pay.
            amount = _rupees(int(b.get("advance_paise") or 0))
            await _reply(db, tenant_id, b, f"Thanks \u2014 your number is confirmed. Pay the {amount} advance "
                                           "on the booking page to keep the time.")
        elif not flipped:
            await send_confirmation(db, tenant_id, b["id"])
        return True
    except Exception as e:
        logger.warning("booking code handler failed: %s", e)
        return False


def _parse_payload(payload: str | None) -> tuple[str, str] | None:
    p = (payload or "").strip()
    for prefix, kind in ((YES_PREFIX, "yes"), (CANCEL_PREFIX, "cancel")):
        if p.startswith(prefix):
            rest = p[len(prefix):]
            if re.fullmatch(_ID, rest):
                return kind, rest
    return None


async def _reply(db, tenant_id: str, b: dict, text: str) -> None:
    try:
        full = _decorate(db, tenant_id, dict(b))
        await _deliver(db, tenant_id, full, text=text, template_key="update", values=[], text_only=True)
    except Exception as e:
        logger.warning("booking %s: reply not sent: %s", b.get("id"), e)


def _already_confirmed(b: dict) -> bool:
    """They already said yes to the latest reminder (or before any was sent). Meta delivers some
    webhooks twice: a repeat must not send "Thank you" again. A yes from before the newest reminder
    does not count, so a new tap on the 2-hour reminder is still taken."""
    said = _parse(b.get("confirmed_at"))
    if said is None:
        return False
    last = max((t for t in (_parse(b.get("reminder_day_sent_at")), _parse(b.get("reminder_2h_sent_at"))) if t),
               default=None)
    return last is None or said >= last


def _confirm(db, tenant_id: str, b: dict) -> None:
    db.table("bookings").update({"confirmed_at": _iso(_now()), "call_now_at": None, "phone_checked": True}).eq(
        "id", b["id"]).eq("tenant_id", tenant_id).execute()


async def handle_booking_button(db, tenant_id: str, phone: str, payload: str) -> bool:
    """Quick reply on a reminder: bk_yes:<id> or bk_cancel:<id>. The phone must be the booking's."""
    try:
        parsed = _parse_payload(payload)
        if not parsed:
            return False
        kind, booking_id = parsed
        rows = (db.table("bookings").select("*").eq("id", booking_id).eq("tenant_id", tenant_id)
                .limit(1).execute()).data or []
        if not rows or not _same_phone(rows[0].get("phone"), phone):
            return False
        b = rows[0]
        if b.get("status") not in ("held", "booked"):
            await _reply(db, tenant_id, b, "That booking is no longer active. Reply here and we will help.")
            return True
        if kind == "yes":
            if _already_confirmed(b):
                return True
            _confirm(db, tenant_id, b)
            await _reply(db, tenant_id, b, "Thank you, see you then.")
            return True
        return await _customer_cancel(db, tenant_id, b)
    except Exception as e:
        logger.warning("booking button handler failed: %s", e)
        return False


async def _customer_cancel(db, tenant_id: str, b: dict) -> bool:
    cutoff = _cutoff_min(db, tenant_id)
    start = _parse(b.get("start_at"))
    if start is None or start - _now() < timedelta(minutes=cutoff):
        await _reply(db, tenant_id, b, f"It's less than {_hours_words(cutoff)} away, please call us.")
        return True
    now = _now()
    res = db.table("bookings").update({
        "status": "cancelled", "cancelled_at": _iso(now), "cancelled_by": "customer",
        "cancel_reason": "Cancelled by the customer on WhatsApp", "updated_at": _iso(now),
    }).eq("id", b["id"]).eq("tenant_id", tenant_id).in_("status", ["held", "booked"]).execute()
    if not (res.data or []):
        return True
    from app.services.booking_orders import release_unpaid_order
    if b.get("status") == "held":
        release_unpaid_order(tenant_id, b, db)
    recompute_lead_mirror(db, tenant_id, b.get("lead_id"))
    full = _decorate(db, tenant_id, dict(b))
    ring_bell(db, tenant_id, full, "booking_cancelled", "Booking cancelled",
              f"{_who(full)} cancelled {full['service_name']} on {when_text(b['start_at'])}.")
    await send_cancelled(db, tenant_id, b["id"])
    return True


def is_thumbs_up(emoji: str | None) -> bool:
    e = (emoji or "").strip()
    return bool(e) and e.strip(_SKIN_TONES) == "\U0001F44D"


async def handle_booking_reaction(db, tenant_id: str, phone: str, reacted_wamid: str, emoji: str) -> bool:
    """A thumbs-up on a booking's reminder message counts as "Yes, coming"."""
    try:
        if not is_thumbs_up(emoji) or not reacted_wamid:
            return False
        rows = (db.table("bookings").select("*").eq("tenant_id", tenant_id).eq("reminder_wamid", reacted_wamid)
                .limit(1).execute()).data or []
        if not rows or not _same_phone(rows[0].get("phone"), phone):
            return False
        b = rows[0]
        if b.get("status") not in ("held", "booked"):
            return False
        if _already_confirmed(b):
            return True  # a repeat of the same reaction
        _confirm(db, tenant_id, b)
        await _reply(db, tenant_id, b, "Thank you, see you then.")
        return True
    except Exception as e:
        logger.warning("booking reaction handler failed: %s", e)
        return False


# ───────────────────────────────────────────────────────────── held slots

async def confirm_if_ready(db, tenant_id: str, booking: dict) -> dict:
    """A held booking becomes booked once BOTH are true: the advance is paid (or none was due) and
    the number is confirmed (the customer sent their BK code on WhatsApp; staff-made bookings count
    as confirmed). Only the run that wins the held -> booked update tells the customer and rings
    booking_new. Returns the booking as it stands. Never raises."""
    try:
        if booking.get("status") != "held" or not phone_ok(booking):
            return booking
        from app.services.booking_orders import advance_paid
        if not await _io(advance_paid, tenant_id, booking, db):
            return booking
        res = await _io(lambda: (db.table("bookings").update({"status": "booked", "hold_until": None,
                                                              "updated_at": _iso(_now())})
                                 .eq("id", booking["id"]).eq("tenant_id", tenant_id).eq("status", "held")
                                 .execute()))
        if not (res.data or []):
            rows = await _io(lambda: (db.table("bookings").select("*").eq("id", booking["id"])
                                      .eq("tenant_id", tenant_id).limit(1).execute()).data or [])
            return rows[0] if rows else booking
        await _announce_booked(db, tenant_id, res.data[0])
        return res.data[0]
    except Exception as e:
        logger.warning("booking %s: confirm_if_ready failed: %s", booking.get("id"), e)
        return booking


confirm_if_paid = confirm_if_ready   # the old name keeps working


HOLD_GRACE = timedelta(minutes=2)       # a slow payment webhook is given this long before a hold is released
LATE_PAID_LOOKBACK = timedelta(hours=48)
RELEASE_REASON = "Advance not paid in time"


def _is_slot_taken(e: Exception) -> bool:
    msg = str(e)
    return "23P01" in msg or "23505" in msg or "bookings_no_overlap" in msg or "uq_bookings_phone_day" in msg


def _net_paid(db, tenant_id: str, booking: dict) -> int:
    """Paise the booking's order has collected, refunds taken off. 0 when it has no order."""
    if not booking.get("deal_id"):
        return 0
    rows = (db.table("deals").select("paid_paise, refunded_paise").eq("id", booking["deal_id"])
            .eq("tenant_id", tenant_id).limit(1).execute()).data or []
    if not rows:
        return 0
    return int(rows[0].get("paid_paise") or 0) - int(rows[0].get("refunded_paise") or 0)


def _rupees(paise: int) -> str:
    return f"\u20b9{paise // 100}" if paise % 100 == 0 else f"\u20b9{paise / 100:.2f}"


def _late_payment_bell(db, tenant_id: str, b: dict, net: int) -> None:
    """The customer paid after the hold ended and the slot is gone: staff call to rebook or refund.
    call_now_at on the (cancelled) booking is the "already rung" marker, so this rings once."""
    full = _decorate(db, tenant_id, dict(b))
    ring_bell(db, tenant_id, full, "booking_call_now", "Paid after the hold ended",
              f"{_first_name(full.get('customer_name'))} paid {_rupees(net)} after the hold ended "
              "\u2014 call to rebook or refund")
    db.table("bookings").update({"call_now_at": _iso(_now())}).eq("id", b["id"]).eq("tenant_id", tenant_id).execute()


def _try_rebook(db, tenant_id: str, b: dict) -> bool:
    """Put a just-cancelled hold back to booked. False when the slot was taken in between."""
    try:
        res = (db.table("bookings").update({
            "status": "booked", "hold_until": None, "cancelled_at": None, "cancelled_by": None,
            "cancel_reason": None, "updated_at": _iso(_now()),
        }).eq("id", b["id"]).eq("tenant_id", tenant_id).eq("status", "cancelled").execute())
        return bool(res.data)
    except Exception as e:
        if _is_slot_taken(e):
            return False
        raise


async def _announce_booked(db, tenant_id: str, b: dict) -> None:
    """A hold has just become booked. Number confirmed (or not a website booking): tell the customer
    and ring booking_new. Website booking with an unconfirmed number: say nothing to that number,
    ring staff to call it, and mark the booking call-now."""
    full = await _io(_decorate, db, tenant_id, dict(b))
    if phone_ok(b):
        await send_confirmation(db, tenant_id, b["id"])
        await _io(ring_bell, db, tenant_id, full, "booking_new", "New booking",
                  f"{_who(full)}, {full['service_name']} on {when_text(b['start_at'])}.")
        return
    paid = int(b.get("advance_paise") or 0) > 0
    await _io(ring_bell, db, tenant_id, full, "booking_call_now",
              "Number not confirmed",
              f"{_who(full)}, {full['service_name']} on {when_text(b['start_at'])}: "
              + ("Paid but number not confirmed" if paid else "Number not confirmed") + " \u2014 call to confirm")
    await _io(lambda: db.table("bookings").update({"call_now_at": _iso(_now())}).eq("id", b["id"])
              .eq("tenant_id", tenant_id).execute())


async def _release_one(db, tenant_id: str, b: dict, now: datetime) -> bool:
    from app.services.booking_orders import advance_paid, release_unpaid_order
    if await _io(advance_paid, tenant_id, b, db):
        res = await _io(lambda: db.table("bookings").update({"status": "booked", "hold_until": None,
                                                             "updated_at": _iso(now)})
                        .eq("id", b["id"]).eq("status", "held").execute())
        if res.data:
            await _announce_booked(db, tenant_id, {**b, "status": "booked"})
            return True
        return False
    res = await _io(lambda: db.table("bookings").update({
        "status": "cancelled", "cancelled_at": _iso(now), "cancelled_by": "system",
        "cancel_reason": RELEASE_REASON, "updated_at": _iso(now),
    }).eq("id", b["id"]).eq("status", "held").execute())
    if not res.data:
        return False
    await _io(release_unpaid_order, tenant_id, b, db)
    # The payment can land in the instant between the check above and the release.
    if await _io(advance_paid, tenant_id, b, db):
        if await _io(_try_rebook, db, tenant_id, b):
            await _announce_booked(db, tenant_id, {**b, "status": "booked"})
            return True
        await _io(_late_payment_bell, db, tenant_id, b, await _io(_net_paid, db, tenant_id, b))
        return True
    await _io(recompute_lead_mirror, db, tenant_id, b.get("lead_id"))
    await send_cancelled(db, tenant_id, b["id"], "The advance was not paid in time")
    return True


async def _sweep_late_payments(db, now: datetime) -> int:
    """Holds the system released in the last 48 h whose order is now paid: ring staff once each."""
    rows = await _io(lambda: (db.table("bookings").select("*").eq("status", "cancelled")
                              .eq("cancelled_by", "system").eq("cancel_reason", RELEASE_REASON)
                              .gte("cancelled_at", _iso(now - LATE_PAID_LOOKBACK)).is_("call_now_at", "null")
                              .limit(500).execute()).data or [])
    rung = 0
    for b in rows:
        try:
            if not b.get("deal_id"):
                continue
            net = await _io(_net_paid, db, str(b["tenant_id"]), b)
            if net > 0:
                await _io(_late_payment_bell, db, str(b["tenant_id"]), b, net)
                rung += 1
        except Exception as e:
            logger.warning("booking %s: late-payment sweep failed: %s", b.get("id"), e)
    return rung


async def release_holds(db=None, now: datetime | None = None) -> int:
    """Every minute. A hold past hold_until + 2 min: advance paid -> booked + confirmation;
    not paid -> cancelled by the system and its open order closed. If the money arrives in the
    instant of release the booking goes back to booked, or - when the slot was retaken - staff get a
    "call now" bell. The same run rings once for holds released in the last 48 h that were paid since.
    Returns how many holds it touched."""
    db = db or get_supabase()
    now = now or _now()
    rows = await _io(lambda: (db.table("bookings").select("*").eq("status", "held")
                              .lt("hold_until", _iso(now - HOLD_GRACE)).order("hold_until")
                              .limit(500).execute()).data or [])
    done = 0
    for b in rows:
        try:
            if await _release_one(db, str(b["tenant_id"]), b, now):
                done += 1
        except Exception as e:
            logger.warning("booking %s: release hold failed: %s", b.get("id"), e)
    try:
        await _sweep_late_payments(db, now)
    except Exception as e:
        logger.warning("booking: late-payment sweep failed: %s", e)
    return done


# ───────────────────────────────────────────────────────────── reminders

def day_reminder_due(b: dict, now: datetime) -> bool:
    """Day-before reminder: 20-28 h away and sent between 9 AM and 8 PM IST. A booking whose 20-28 h
    window fell outside those hours (a 2 AM visit) gets it at the next allowed time, but never
    inside the last 2 h 15 min. A booking made late (under 28 h ahead) is not given a day reminder,
    and neither is one that was moved to a time under 20 h away (the move message just told them)."""
    if b.get("reminder_day_sent_at") or b.get("status") != "booked":
        return False
    start = _parse(b.get("start_at"))
    if start is None:
        return False
    until = start - now
    lo, hi = DAY_WINDOW
    if not (REMINDER_HOURS_IST[0] <= now.astimezone(IST).hour < REMINDER_HOURS_IST[1]):
        return False
    if lo <= until <= hi:
        return True
    if MIN_BEFORE < until < lo:
        if int(b.get("moved_count") or 0) > 0:
            return False
        created = _parse(b.get("created_at"))
        return created is None or start - created > hi  # the window was missed, not skipped
    return False


def _quiet_hour(dt: datetime) -> bool:
    h = dt.astimezone(IST).hour
    return h >= QUIET_FROM or h < QUIET_TO


def two_hour_due(b: dict, now: datetime) -> bool:
    """2-hour reminder: 1h45-2h15 away, never between 10 PM and 7 AM IST. When its moment fell in
    those hours it goes at 7 AM instead, if the visit is still more than 30 min away."""
    if b.get("reminder_2h_sent_at") or b.get("status") != "booked":
        return False
    start = _parse(b.get("start_at"))
    if start is None or _quiet_hour(now):
        return False
    until = start - now
    lo, hi = REMINDER_2H_WINDOW
    if lo <= until <= hi:
        return True
    if timedelta(minutes=30) < until < lo and _quiet_hour(start - timedelta(hours=2)):
        created = _parse(b.get("created_at"))
        return created is None or created <= start - timedelta(hours=2)  # not one made after its moment
    return False


async def _send_reminder(db, tenant_id: str, b: dict, label: str) -> tuple[str | None, str]:
    full = await _io(_decorate, db, tenant_id, dict(b))
    name = _first_name(full.get("customer_name"))
    values = [name, full["service_name"], label, full["resource_name"]]
    template_key = "reminder"
    contact_line = ""
    from app.services import property_visit_messages as pvm
    visit = await _io(pvm.reminder_plan, db, tenant_id, full, label, name)
    if visit:  # a property site visit: the executive's phone is in the reminder
        if visit["contact"]:
            contact_line = f" {visit['contact']} if you need directions."
        if visit["template"]:  # Meta approved it; until then the booking reminder goes out as before
            template_key, values = visit["template"], visit["values"]
    text = (f"Reminder: {name}, your {full['service_name']} booking is {label} "
            f"with {full['resource_name']}.{contact_line} Will you be there?")
    payloads = [f"{YES_PREFIX}{b['id']}", f"{CANCEL_PREFIX}{b['id']}"]
    buttons = [{"id": payloads[0], "title": YES_TITLE}, {"id": payloads[1], "title": CANCEL_TITLE}]
    sid, why = await _deliver(db, tenant_id, full, text=text, template_key=template_key, values=values,
                              buttons=buttons, payloads=payloads)
    if not sid:
        logger.info("booking %s: reminder not sent (%s)", b["id"], why)
    return sid, why


def _call_now(db, tenant_id: str, b: dict, why: str) -> None:
    """Staff should phone this customer: set call_now_at and ring the bell, once."""
    if b.get("call_now_at"):
        return
    db.table("bookings").update({"call_now_at": _iso(_now())}).eq("id", b["id"]).eq("tenant_id", tenant_id).execute()
    b["call_now_at"] = _iso(_now())
    full = _decorate(db, tenant_id, dict(b))
    ring_bell(db, tenant_id, full, "booking_call_now", "Call this customer now",
              f"{_who(full)}, {full['service_name']} at {when_text(b['start_at'])}: {why}")


def _claim(db, tenant_id: str, b: dict, column: str, stamp: str) -> bool:
    """Mark the reminder sent BEFORE sending, so two overlapping runs never both send it. Only a
    still-booked booking whose column is still empty is claimed."""
    res = (db.table("bookings").update({column: stamp}).eq("id", b["id"]).eq("tenant_id", tenant_id)
           .eq("status", "booked").is_(column, "null").execute())
    return bool(res.data)


def _unclaim(db, tenant_id: str, b: dict, column: str) -> None:
    db.table("bookings").update({column: None}).eq("id", b["id"]).eq("tenant_id", tenant_id).execute()


async def send_reminders(db=None, now: datetime | None = None) -> int:
    """Every 5 minutes. Returns how many reminders went out. A reminder that cannot be sent
    (template not approved, WhatsApp down) is left unsent and the booking is flagged "call now"."""
    db = db or get_supabase()
    now = now or _now()
    rows = await _io(lambda: (db.table("bookings").select("*").eq("status", "booked").gt("start_at", _iso(now))
                              .lt("start_at", _iso(now + DAY_WINDOW[1] + timedelta(hours=1))).order("start_at")
                              .limit(2000).execute()).data or [])
    sent = 0
    for b in rows:
        tenant_id = str(b["tenant_id"])
        if not phone_ok(b):
            continue  # a website booking whose number nobody confirmed: no messages to that number
        for due, column, label in (
            (two_hour_due(b, now), "reminder_2h_sent_at", "in about 2 hours"),
            (day_reminder_due(b, now), "reminder_day_sent_at", None),
        ):
            if not due:
                continue
            claimed = False
            try:
                if not await _io(_claim, db, tenant_id, b, column, _iso(now)):
                    continue  # another run has it, or it is no longer booked
                claimed = True
                label = label or f"tomorrow, {when_text(b['start_at'])}"
                sid, why = await _send_reminder(db, tenant_id, b, label)
                if not sid:
                    await _io(_unclaim, db, tenant_id, b, column)
                    claimed = False
                    if why != "blocked":  # a blocked person is left alone
                        await _io(_call_now, db, tenant_id, b, "the reminder could not be sent")
                    continue
                await _io(lambda: db.table("bookings").update({"reminder_wamid": sid})
                          .eq("id", b["id"]).eq("tenant_id", tenant_id).execute())
                b[column] = _iso(now)
                sent += 1
            except Exception as e:
                logger.warning("booking %s: reminder failed: %s", b.get("id"), e)
                if claimed:
                    try:
                        await _io(_unclaim, db, tenant_id, b, column)
                    except Exception:
                        pass
    return sent


def flag_call_now(db=None, now: datetime | None = None) -> int:
    """Every 5 minutes. The 2-hour reminder went out over an hour ago, no "Yes, coming" since,
    and the visit is still ahead: flag it "call now" and ring the bell once."""
    db = db or get_supabase()
    now = now or _now()
    rows = (db.table("bookings").select("*").eq("status", "booked").is_("call_now_at", "null")
            .gt("start_at", _iso(now)).lte("reminder_2h_sent_at", _iso(now - CALL_NOW_AFTER))
            .limit(2000).execute()).data or []
    flagged = 0
    for b in rows:
        try:
            sent_at, said_yes = _parse(b.get("reminder_2h_sent_at")), _parse(b.get("confirmed_at"))
            if sent_at is None or (said_yes and said_yes >= sent_at):
                continue
            _call_now(db, str(b["tenant_id"]), b, "no answer to the 2-hour reminder")
            flagged += 1
        except Exception as e:
            logger.warning("booking %s: flag call-now failed: %s", b.get("id"), e)
    return flagged
