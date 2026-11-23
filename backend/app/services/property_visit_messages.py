"""Property site visits (v9.2 screen 215): the visit reminder that carries the executive's phone, and
the "liked it, thinking" loan-help follow-up two days later.

Both ride on the Bookings messages (services/booking_messages.py): the same guards (no phone, number not
proved, blocked, opted out), the same 24-hour rule (free text inside it, an approved template outside it).
Each new WhatsApp template is used only once Meta has APPROVED it. Until then the existing booking reminder
goes out exactly as before, and the loan follow-up is simply not sent.

Data: bookings.visit_outcome / visit_outcome_at / loan_followup_due_at / loan_followup_sent_at (migration 336,
nullable). Code tolerates the migration not being applied.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Submitted only for property businesses, with the booking templates (Bookings > Set up booking messages).
SITE_VISIT_TEMPLATES = {
    "site_visit_reminder": {
        "name": "site_visit_reminder",
        "category": "UTILITY",
        "body": ("Hi {{1}}, a reminder from {{2}}: your site visit to {{3}} is {{4}}. "
                 "{{5}} if you need directions."),
        "examples": ["Priya", "Sri Builders", "Green Meadows Villa 12", "tomorrow, Thu 28 Nov, 4:00 PM",
                     "Call Ravi on +919876543210"],
        "buttons": ["Yes, coming", "Cancel"],
    },
    "loan_help_followup": {
        "name": "loan_help_followup",
        "category": "MARKETING",
        "body": ("Hi {{1}}, thank you for visiting {{2}}. If you are still thinking it over, {{3}} can help "
                 "you with a home loan. Reply to this message and we will arrange a call."),
        "examples": ["Priya", "Green Meadows Villa 12", "Sri Builders"],
    },
}

OUTCOMES = ("liked_thinking", "not_interested", "ready_to_book")
OUTCOME_LABEL = {"liked_thinking": "Liked it, thinking", "not_interested": "Not interested",
                 "ready_to_book": "Ready to book"}
LOAN_FOLLOWUP_AFTER = timedelta(days=2)
LOAN_FOLLOWUP_EXPIRES = timedelta(days=5)   # a follow-up that could not go (template not approved) is dropped after this
SEND_HOURS_IST = (10, 20)                   # the loan message goes only 10 AM - 8 PM IST


def is_site_visit(service_name: str | None) -> bool:
    from app.services.properties import VISIT_SERVICE_NAME
    return (service_name or "").strip().lower() == VISIT_SERVICE_NAME.lower()


def is_property_business(db, tenant_id: str) -> bool:
    """A real-estate business, or one that already has the "Site visit" service."""
    from app.services import properties
    try:
        rows = db.table("tenants").select("business_type").eq("id", tenant_id).limit(1).execute().data or []
        if properties.business_kind((rows[0] or {}).get("business_type") if rows else None) == "real_estate":
            return True
    except Exception as e:
        logger.info("site visit templates: business type unavailable: %s", e)
    try:
        return bool(properties.site_visit_service(db, tenant_id, create=False))
    except Exception:
        return False


def templates_status(db, tenant_id: str) -> dict:
    """{"site_visit_reminder": status|None, "loan_help_followup": status|None}. None = never submitted."""
    from app.config_dynamic import get_setting
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    names = [t["name"] for t in SITE_VISIT_TEMPLATES.values()]
    rows = (db.table("message_templates").select("name, status, meta_waba_id").eq("tenant_id", tenant_id)
            .in_("name", names).execute().data or [])
    by_name = {r["name"]: r for r in rows if not waba_id or r.get("meta_waba_id") == waba_id}
    return {n: ((by_name[n].get("status") or "PENDING").upper() if n in by_name else None) for n in names}


async def submit_templates(db, tenant_id: str, ctx: dict | None, problems: list[str]) -> None:
    """Submit the missing or rejected site-visit templates (property businesses only). Problems are appended."""
    import asyncio
    from fastapi import HTTPException
    from app.routes.templates import Button, CreateTemplate, create_template

    if not await asyncio.to_thread(is_property_business, db, tenant_id):
        return
    status = await asyncio.to_thread(templates_status, db, tenant_id)
    for name, spec in SITE_VISIT_TEMPLATES.items():
        if status.get(name) not in (None, "REJECTED"):
            continue
        try:
            buttons = [Button(type="QUICK_REPLY", text=t) for t in spec.get("buttons", [])]
            await create_template(
                CreateTemplate(name=name, category=spec["category"], language="en", body_text=spec["body"],
                               body_examples=spec["examples"], buttons=buttons or None),
                tenant_id=tenant_id, _ctx=ctx or {},
            )
        except HTTPException as e:
            problems.append(f"{name}: {e.detail}")
        except Exception as e:
            logger.warning("site visit templates: %s did not submit: %s", name, e)
            problems.append(f"{name}: could not be sent to WhatsApp")


def approved(db, tenant_id: str, name: str) -> bool:
    from app.services.call_details_share import _approved_templates
    return any(t.get("name") == name for t in _approved_templates(db, tenant_id))


# ── who and where ───────────────────────────────────────────────────────────

def _phone_text(raw: str | None) -> str | None:
    from app.services.booking_messages import _international
    digits = _international(raw)
    return f"+{digits}" if digits else None


def executive_contact(db, tenant_id: str, b: dict) -> str | None:
    """"Call Ravi on +919876543210": the staff member the visit is with and their own phone (the team
    record). Without one, "Call us on +91..." with the business's main WhatsApp number. None when no number
    is known at all."""
    phone = None
    name = (b.get("resource_name") or "").strip()
    uid = b.get("resource_user_id")
    if uid:
        try:
            rows = (db.table("callers").select("phone").eq("user_id", uid).eq("tenant_id", tenant_id)
                    .limit(1).execute().data or [])
            phone = _phone_text(rows[0].get("phone")) if rows else None
        except Exception as e:
            logger.info("site visit: executive phone unavailable: %s", e)
    if phone and name and name.lower() != "us":
        return f"Call {name} on {phone}"
    if not phone:
        from app.services.bookings import main_number
        phone = _phone_text(main_number(db, tenant_id))
    return f"Call us on {phone}" if phone else None


def property_name(db, tenant_id: str, booking_id: str) -> str | None:
    try:
        link = (db.table("property_visits").select("property_item_id").eq("tenant_id", tenant_id)
                .eq("booking_id", booking_id).limit(1).execute().data or [])
        if not link:
            return None
        item = (db.table("catalog_items").select("name").eq("tenant_id", tenant_id)
                .eq("id", link[0]["property_item_id"]).limit(1).execute().data or [])
        return ((item[0].get("name") or "").strip() or None) if item else None
    except Exception as e:
        logger.info("site visit: property name unavailable: %s", e)
        return None


def reminder_plan(db, tenant_id: str, b: dict, label: str, first_name: str) -> dict | None:
    """For a site-visit booking: {"contact": the contact line ("Call Ravi on +91..."), "values": the five
    template values, "template": "site_visit_reminder" if Meta approved it, else None}. None for any other
    booking."""
    if not is_site_visit(b.get("service_name")):
        return None
    contact = executive_contact(db, tenant_id, b)
    where = property_name(db, tenant_id, b["id"]) or "the site"
    values = [first_name, b.get("business_name") or "us", where, label, contact or ""]
    use_template = bool(contact) and approved(db, tenant_id, "site_visit_reminder")
    return {"contact": contact, "values": values, "template": "site_visit_reminder" if use_template else None}


# ── recording the outcome ───────────────────────────────────────────────────

class OutcomeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def record_outcome(db, tenant_id: str, booking_id: str, outcome: str, now: datetime) -> dict:
    """Save how a site visit went. "Liked it, thinking" also schedules the loan-help follow-up for 2 days
    later (once); changing the answer later cancels one that has not gone yet."""
    from app.services import bookings as bk
    if outcome not in OUTCOMES:
        raise OutcomeError("Pick one of: " + ", ".join(OUTCOME_LABEL.values()))
    booking = bk.get_booking(db, tenant_id, booking_id)
    svc = (db.table("booking_services").select("name").eq("id", booking.get("service_id"))
           .eq("tenant_id", tenant_id).limit(1).execute().data or [])
    if not svc or not is_site_visit(svc[0].get("name")):
        raise OutcomeError("This is not a site visit", 404)
    if booking.get("status") != "came":
        raise OutcomeError("Mark the visit as came first")
    patch = {"visit_outcome": outcome, "visit_outcome_at": now.isoformat()}
    if outcome == "liked_thinking":
        if not booking.get("loan_followup_due_at"):
            patch["loan_followup_due_at"] = (now + LOAN_FOLLOWUP_AFTER).isoformat()
    elif not booking.get("loan_followup_sent_at"):
        patch["loan_followup_due_at"] = None
    try:
        db.table("bookings").update(patch).eq("id", booking_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.warning("site visit outcome not saved (migration 336 applied?): %s", e)
        raise OutcomeError("This needs a quick update on our side; try again later.", 503)
    return {"visit_outcome": outcome, "loan_followup_due_at": patch.get("loan_followup_due_at",
                                                                         booking.get("loan_followup_due_at"))}


# ── the follow-up sweep ─────────────────────────────────────────────────────

def _in_send_hours(now: datetime) -> bool:
    from app.services.booking_messages import IST
    return SEND_HOURS_IST[0] <= now.astimezone(IST).hour < SEND_HOURS_IST[1]


def _lead_row(db, tenant_id: str, b: dict) -> dict:
    cols = "id, name, phone, opted_out, last_inbound_at, blocked_at, opt_in_source"
    if b.get("lead_id"):
        rows = (db.table("leads").select(cols).eq("id", b["lead_id"]).eq("tenant_id", tenant_id)
                .is_("deleted_at", "null").limit(1).execute().data or [])
        if rows:
            return rows[0]
    if b.get("phone"):
        rows = (db.table("leads").select(cols).eq("tenant_id", tenant_id).eq("phone", b["phone"])
                .is_("deleted_at", "null").limit(1).execute().data or [])
        if rows:
            return rows[0]
    return {}


def _tag_opted_out(db, tenant_id: str, lead_id: str) -> bool:
    """Said stop to a broadcast tag (or to all broadcasts). Any such row means no marketing message."""
    try:
        return bool(db.table("lead_tag_opt_outs").select("id").eq("tenant_id", tenant_id)
                    .eq("lead_id", lead_id).limit(1).execute().data)
    except Exception as e:  # table missing: treated like every other marketing send does
        logger.info("loan follow-up: tag opt-outs unavailable: %s", e)
        return False


def marketing_ok(db, tenant_id: str, lead: dict) -> bool:
    """The loan template is a MARKETING message: only to an existing lead who is not opted out, not blocked,
    not tag-opted-out, and has a recorded opt-in (opt_in_source set and not "manual")."""
    if not lead.get("id") or lead.get("opted_out") or lead.get("blocked_at"):
        return False
    source = (lead.get("opt_in_source") or "").strip().lower()
    if not source or source == "manual":
        return False
    return not _tag_opted_out(db, tenant_id, lead["id"])


async def send_loan_followups(db=None, now: datetime | None = None) -> int:
    """Every 15 minutes. Sends the loan-help message to people who "liked it, thinking" 2 days ago. Returns how
    many went out. Free text inside the 24-hour window. Outside it only the approved loan_help_followup
    template, and only to someone with a recorded opt-in; a booking that cannot be sent either way is not
    touched (template not approved yet) or closed for good (no opt-in, opted out, blocked)."""
    import asyncio
    from app.db.supabase import get_supabase
    from app.services import blocked_guard
    from app.services import booking_messages as bm
    from app.services.call_details_share import window_open

    db = db or get_supabase()
    now = now or bm._now()
    if not _in_send_hours(now):
        return 0
    try:
        rows = await asyncio.to_thread(lambda: (
            db.table("bookings").select("*").eq("status", "came").eq("visit_outcome", "liked_thinking")
            .is_("loan_followup_sent_at", "null").lte("loan_followup_due_at", now.isoformat())
            .gte("loan_followup_due_at", (now - LOAN_FOLLOWUP_EXPIRES).isoformat())
            .order("loan_followup_due_at").limit(500).execute().data or []))
    except Exception as e:  # migration 336 not applied yet
        logger.info("loan follow-up: not ready: %s", e)
        return 0

    def patch(b: dict, tenant_id: str, values: dict) -> None:
        db.table("bookings").update(values).eq("id", b["id"]).eq("tenant_id", tenant_id).execute()

    sent = 0
    for b in rows:
        tenant_id = str(b["tenant_id"])
        if not bm.phone_ok(b):
            continue
        claimed = False
        try:
            lead = await asyncio.to_thread(_lead_row, db, tenant_id, b)
            blocked = bool(lead.get("blocked_at")) or (bool(b.get("phone")) and await blocked_guard.is_blocked(tenant_id, b["phone"]))
            if not lead.get("id") or lead.get("opted_out") or blocked:
                await asyncio.to_thread(patch, b, tenant_id, {"loan_followup_due_at": None})  # never to this person
                continue
            in_window = window_open(lead.get("last_inbound_at"), now)
            template_ready = await asyncio.to_thread(marketing_ok, db, tenant_id, lead) and \
                await asyncio.to_thread(approved, db, tenant_id, "loan_help_followup")
            if not in_window:
                if not await asyncio.to_thread(marketing_ok, db, tenant_id, lead):
                    await asyncio.to_thread(patch, b, tenant_id, {"loan_followup_due_at": None})  # no opt-in: close it
                    continue
                if not template_ready:
                    continue  # template not approved yet: leave it for a later tick, nothing claimed
            claimed = bool(await asyncio.to_thread(lambda: (
                db.table("bookings").update({"loan_followup_sent_at": now.isoformat()})
                .eq("id", b["id"]).eq("tenant_id", tenant_id).is_("loan_followup_sent_at", "null").execute().data)))
            if not claimed:
                continue
            full = await asyncio.to_thread(bm._decorate, db, tenant_id, dict(b))
            name = bm._first_name(full.get("customer_name"))
            where = await asyncio.to_thread(property_name, db, tenant_id, b["id"]) or "the site"
            business = full.get("business_name") or "us"
            text = (f"Hi {name}, thank you for visiting {where}. If you are still thinking it over, "
                    f"{business} can help you with a home loan. Reply here and we will arrange a call.")
            # Inside the window it is free text; the template is never a fallback unless it is allowed.
            sid, why = await bm._deliver(db, tenant_id, full, text=text, template_key="loan_help_followup",
                                         values=[name, where, business], text_only=not template_ready)
            if not sid:
                await asyncio.to_thread(patch, b, tenant_id, {"loan_followup_sent_at": None})
                claimed = False
                if why in ("blocked", "opted_out"):
                    await asyncio.to_thread(patch, b, tenant_id, {"loan_followup_due_at": None})
                logger.info("booking %s: loan follow-up not sent (%s)", b["id"], why)
                continue
            sent += 1
        except Exception as e:
            logger.warning("booking %s: loan follow-up failed: %s", b.get("id"), e)
            if claimed:
                try:
                    await asyncio.to_thread(patch, b, tenant_id, {"loan_followup_sent_at": None})
                except Exception:
                    pass
    return sent
