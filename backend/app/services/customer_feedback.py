"""Customers > Feedback: ask for stars after an order or a visit, and handle the answer (v9.2 Batch H, #17).

How it runs:
  * every 15 minutes `ask_due_feedback` sends the star message (the `feedback_ask` template, five quick
    replies) to people whose order was delivered, or whose booking was kept, 24-72 hours ago;
  * a tap comes back through `handle_feedback_button` (payload fb:<stars>:<feedback_id>);
  * after a 1-3 star tap the customer's next message is taken as the reason (`handle_feedback_text`).

The ask is automatic, so it follows Settings > Auto-Reply (the AI Replies master switch) and every
"do not message" rule. Taps and replies are the customer's own conversation, so they are not gated.
Public functions here never raise.
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
TEMPLATE_NAME = "feedback_ask"
TEMPLATE_BODY = "Hi {{1}}, how was your {{2}} with {{3}}? Tap a star."
TEMPLATE_EXAMPLES = ["Priya", "order", "Sri Stores"]
STAR_BUTTONS = ["⭐ 1", "⭐⭐ 2", "⭐⭐⭐ 3", "⭐⭐⭐⭐ 4", "⭐⭐⭐⭐⭐ 5"]
COST_PER_MESSAGE_RUPEES = 0.8631

ON_KEY, OFFER_KEY = "feedback_on", "feedback_offer"
OFFER_MAX = 200
REASON_MAX = 500
SEND_HOURS_IST = (10, 20)          # asks go out from 10 AM until 8 PM IST
ASK_AFTER, ASK_UNTIL = timedelta(hours=24), timedelta(hours=72)
REPEAT_GAP = timedelta(days=30)    # one ask per phone per 30 days
MAX_PER_TENANT = 200
REASON_WINDOW = timedelta(hours=24)
UNHAPPY_MAX = 3
BELL_TYPE = "feedback_unhappy"
FEEDBACK_URL = "/dashboard/leads?tab=feedback"

_PAYLOAD = re.compile(r"^fb:([1-5]):([A-Za-z0-9\-]{1,64})$")


async def _io(fn, *args, **kwargs):
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


def _first_name(name: str | None) -> str:
    from app.services.booking_messages import clean_text
    return (clean_text(name, 40).split(" ") or [""])[0] or "there"


# ───────────────────────────────────────────────────────────── settings

def is_on(tenant_id: str) -> bool:
    from app.config_dynamic import get_setting
    return (get_setting(ON_KEY, fallback="false", tenant_id=tenant_id) or "").strip().lower() == "true"


def offer_text(tenant_id: str) -> str:
    from app.config_dynamic import get_setting
    return (get_setting(OFFER_KEY, fallback="", tenant_id=tenant_id) or "").strip()[:OFFER_MAX]


def review_link(tenant_id: str) -> str:
    """The Google review link from the Orders settings (read only)."""
    try:
        from app.services.orders import order_settings
        return order_settings(tenant_id).get("google_review_link") or ""
    except Exception as e:
        logger.warning("feedback: review link not read: %s", e)
        return ""


def save_settings(db, tenant_id: str, on: bool, offer: str | None) -> dict:
    """Save the two switches. Raises ValueError (plain words) when the offer is too long."""
    from app.config_dynamic import invalidate_cache
    offer_clean = " ".join(str(offer or "").split())
    if len(offer_clean) > OFFER_MAX:
        raise ValueError(f"Keep the offer under {OFFER_MAX} letters.")
    for key, value in ((ON_KEY, "true" if on else "false"), (OFFER_KEY, offer_clean)):
        db.table("app_settings").upsert({
            "tenant_id": tenant_id, "key": key, "value": value, "is_secret": False, "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()
        invalidate_cache(key)
    return {"on": on, "offer": offer_clean}


# ───────────────────────────────────────────────────────────── the template

def _template_row(db, tenant_id: str) -> dict | None:
    from app.config_dynamic import get_setting
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    rows = (db.table("message_templates").select("name, status, meta_waba_id, body_text, language")
            .eq("tenant_id", tenant_id).eq("name", TEMPLATE_NAME).execute()).data or []
    for r in rows:
        if not waba_id or r.get("meta_waba_id") == waba_id:
            return r
    return None


def template_status(db, tenant_id: str) -> str | None:
    """PENDING / APPROVED / REJECTED, or None when it was never set up."""
    try:
        row = _template_row(db, tenant_id)
    except Exception as e:
        logger.warning("feedback: template status not read: %s", e)
        return None
    return ((row.get("status") or "PENDING").upper()) if row else None


async def submit_template(db, tenant_id: str, ctx: dict | None = None) -> dict:
    """Submit feedback_ask to Meta through the Templates page's own path (marketing, English).
    Returns {"template_status": ..., "problems": [str]}."""
    from fastapi import HTTPException
    from app.routes.templates import Button, CreateTemplate, create_template

    problems: list[str] = []
    if template_status(db, tenant_id) in (None, "REJECTED"):
        try:
            await create_template(
                CreateTemplate(name=TEMPLATE_NAME, category="MARKETING", language="en", body_text=TEMPLATE_BODY,
                               body_examples=TEMPLATE_EXAMPLES,
                               buttons=[Button(type="QUICK_REPLY", text=t) for t in STAR_BUTTONS]),
                tenant_id=tenant_id, _ctx=ctx or {},
            )
        except HTTPException as e:
            problems.append(str(e.detail))
        except Exception as e:
            logger.warning("feedback: template did not submit: %s", e)
            problems.append("The star message could not be sent to WhatsApp. Please try again.")
    return {"template_status": template_status(db, tenant_id), "problems": problems}


# ───────────────────────────────────────────────────────────── sending

def _lead_row(db, tenant_id: str, lead_id: str | None, phone: str | None) -> dict:
    cols = "id, name, phone, opted_out, last_inbound_at, blocked_at, whatsapp_undeliverable"
    if lead_id:
        rows = (db.table("leads").select(cols).eq("id", lead_id).eq("tenant_id", tenant_id)
                .is_("deleted_at", "null").limit(1).execute()).data or []
        if rows:
            return rows[0]
    if phone:
        from app.services.reach_audience import _spellings, phone_key
        key = phone_key(phone)
        spellings = list(dict.fromkeys([phone] + (_spellings([key]) if key else [])))
        rows = (db.table("leads").select(cols).eq("tenant_id", tenant_id).in_("phone", spellings)
                .is_("deleted_at", "null").execute()).data or []
        if rows:
            # Any copy of this number that said stop wins, so a duplicate lead can't let the ask through.
            return next((r for r in rows if r.get("opted_out")), rows[0])
    return {}


async def _save_to_chat(db, tenant_id: str, lead_id: str | None, sid: str | None, content: str) -> None:
    if not (lead_id and sid):
        return
    try:
        await _io(lambda: db.table("messages").insert({
            "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
            "content": content, "is_ai_generated": False, "meta_message_id": sid,
        }).execute())
    except Exception as e:  # the customer already has it
        logger.warning("feedback: sent but not saved to the chat: %s", e)


async def _send_ask(db, tenant_id: str, phone: str, lead_id: str | None, values: list[str],
                    feedback_id: str) -> tuple[str | None, str]:
    """The star message: always the template (the five buttons only exist there). Returns (id, error)."""
    from app.services.call_details_share import _approved_templates, render_template
    from app.services.meta_cloud import send_template_message

    approved = await _io(_approved_templates, db, tenant_id)
    template = next((t for t in approved if t.get("name") == TEMPLATE_NAME), None)
    if not template:
        return None, "The star message is not approved yet"
    vals = [" ".join(str(v).split()) or "-" for v in values]
    components = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in vals]}]
    for n in range(1, 6):
        components.append({"type": "button", "sub_type": "quick_reply", "index": str(n - 1),
                           "parameters": [{"type": "payload", "payload": f"fb:{n}:{feedback_id}"}]})
    try:
        resp = await send_template_message(phone, template["name"], template.get("language") or "en",
                                           components=components, tenant_id=tenant_id)
    except Exception as e:
        return None, str(e)[:300] or "WhatsApp refused the message"
    sid = ((resp or {}).get("messages") or [{}])[0].get("id")
    if not sid:
        return None, "WhatsApp did not accept the message"
    await _save_to_chat(db, tenant_id, lead_id, sid, render_template(template.get("body_text") or TEMPLATE_BODY, vals))
    return sid, ""


async def _say(db, tenant_id: str, lead_id: str | None, phone: str, text: str) -> bool:
    """Free text to a customer who has just written to us (inside the 24 hours). Never raises."""
    try:
        lead = await _io(_lead_row, db, tenant_id, lead_id, phone)
        from app.services import blocked_guard
        if lead.get("blocked_at") or await blocked_guard.is_blocked(tenant_id, phone):
            return False
        from app.services.ai_reply import send_whatsapp
        sid = await send_whatsapp(phone, text, tenant_id=tenant_id)
        await _save_to_chat(db, tenant_id, lead.get("id") or lead_id, sid, text)
        return bool(sid)
    except Exception as e:
        logger.warning("feedback: reply not sent: %s", e)
        return False


# ───────────────────────────────────────────────────────────── the ask job

def _business_name(db, tenant_id: str) -> str:
    rows = db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute().data or []
    return ((rows[0].get("name") if rows else "") or "").strip() or "us"


def _caller_names(db, tenant_id: str, ids: set) -> dict:
    if not ids:
        return {}
    rows = db.table("callers").select("id, name").eq("tenant_id", tenant_id).in_("id", list(ids)).execute().data or []
    return {str(r["id"]): (r.get("name") or "").strip() or None for r in rows}


def _candidates(db, tenant_id: str, now: datetime) -> list[dict]:
    """Delivered orders and kept bookings 24-72 h old, not yet asked. Each:
    {kind, deal_id|booking_id, lead_id, phone, name, what, staff_name, staff_user_id, booking}."""
    lo, hi = _iso(now - ASK_UNTIL), _iso(now - ASK_AFTER)
    out: list[dict] = []

    deals = (db.table("deals").select("id, lead_id, sold_by, stage").eq("tenant_id", tenant_id)
             .gte("delivered_at", lo).lte("delivered_at", hi).limit(500).execute()).data or []
    deals = [d for d in deals if d.get("lead_id") and d.get("stage") != "lost"]
    if deals:
        done = {str(r["deal_id"]) for r in (db.table("customer_feedback").select("deal_id").eq("tenant_id", tenant_id)
                .in_("deal_id", [d["id"] for d in deals]).execute()).data or []}
        names = _caller_names(db, tenant_id, {str(d["sold_by"]) for d in deals if d.get("sold_by")})
        for d in deals:
            if str(d["id"]) in done:
                continue
            out.append({"kind": "order", "deal_id": d["id"], "lead_id": d["lead_id"], "phone": None,
                        "what": "order", "staff_name": names.get(str(d.get("sold_by"))), "staff_user_id": None})

    bookings = (db.table("bookings").select("id, lead_id, phone, customer_name, service_id, resource_id, "
                                            "source, phone_checked")
                .eq("tenant_id", tenant_id).eq("status", "came")
                .gte("came_at", lo).lte("came_at", hi).limit(500).execute()).data or []
    if bookings:
        done = {str(r["booking_id"]) for r in (db.table("customer_feedback").select("booking_id")
                .eq("tenant_id", tenant_id).in_("booking_id", [b["id"] for b in bookings]).execute()).data or []}
        from app.services.booking_messages import phone_ok
        for b in bookings:
            if str(b["id"]) in done or not phone_ok(b):
                continue
            svc = (db.table("booking_services").select("name").eq("id", b.get("service_id"))
                   .eq("tenant_id", tenant_id).limit(1).execute()).data or []
            res = (db.table("booking_resources").select("name, user_id").eq("id", b.get("resource_id"))
                   .eq("tenant_id", tenant_id).limit(1).execute()).data or []
            out.append({"kind": "booking", "booking_id": b["id"], "lead_id": b.get("lead_id"),
                        "phone": b.get("phone"), "name": b.get("customer_name"),
                        "what": (svc[0]["name"] if svc else "") or "visit",
                        "staff_name": (res[0].get("name") if res else None) or None,
                        "staff_user_id": res[0].get("user_id") if res else None})
    return out


async def _ask_one(db, tenant_id: str, c: dict, business: str, now: datetime, asked_phones: set) -> bool:
    """Guards, then insert the row first (a unique index means never twice), then send."""
    lead = await _io(_lead_row, db, tenant_id, c.get("lead_id"), c.get("phone"))
    if not lead:
        return False  # no live customer row: we cannot check Said stop, so we never ask
    phone = lead.get("phone") or c.get("phone")
    from app.services.automation_guards import lead_blocks_automated_outbound
    if lead_blocks_automated_outbound({**lead, "phone": phone}):
        return False
    from app.services import blocked_guard
    if await blocked_guard.is_blocked(tenant_id, phone):
        return False
    if phone in asked_phones:
        return False
    row = {"tenant_id": tenant_id, "lead_id": lead.get("id") or c.get("lead_id"), "phone": phone,
           "kind": c["kind"], "deal_id": c.get("deal_id"), "booking_id": c.get("booking_id"),
           "staff_user_id": c.get("staff_user_id"), "staff_name": (c.get("staff_name") or None),
           "status": "asked", "asked_at": _iso(now)}
    try:
        saved = (await _io(lambda: db.table("customer_feedback").insert(row).execute())).data or []
    except Exception as e:
        if "23505" not in str(e):  # 23505 = already asked for this order or booking
            logger.warning("feedback: could not save the ask: %s", e)
        return False
    if not saved:
        return False
    fid = str(saved[0]["id"])
    asked_phones.add(phone)
    name = lead.get("name") or c.get("name")
    sid, error = await _send_ask(db, tenant_id, phone, row["lead_id"],
                                 [_first_name(name), c["what"], business], fid)
    patch = {"ask_message_id": sid} if sid else {"status": "failed", "error": (error or "not sent")[:300]}
    try:
        await _io(lambda: db.table("customer_feedback").update(patch).eq("id", fid)
                  .eq("tenant_id", tenant_id).execute())
    except Exception as e:
        logger.warning("feedback %s: status not saved: %s", fid, e)
    return bool(sid)


async def ask_due_feedback(now: datetime | None = None) -> int:
    """Job, every 15 minutes. 10 AM-8 PM IST only. Returns how many star messages went out."""
    try:
        now = now or _now()
        if not (SEND_HOURS_IST[0] <= now.astimezone(IST).hour < SEND_HOURS_IST[1]):
            return 0
        db = get_supabase()
        tenants = (await _io(lambda: db.table("app_settings").select("tenant_id").eq("key", ON_KEY)
                             .eq("value", "true").limit(1000).execute())).data or []
    except Exception as e:
        logger.warning("feedback: ask job could not start: %s", e)
        return 0
    sent = 0
    for t in tenants:
        tenant_id = str(t["tenant_id"])
        try:
            sent += await _ask_tenant(db, tenant_id, now)
        except Exception as e:
            logger.warning("feedback: ask job failed for %s: %s", tenant_id, e)
    return sent


async def _ask_tenant(db, tenant_id: str, now: datetime) -> int:
    from app.services.automation_guards import master_switch_on
    if not master_switch_on(tenant_id):          # Settings > Auto-Reply: AI Replies off = nothing automatic
        return 0
    if await _io(template_status, db, tenant_id) != "APPROVED":
        return 0
    from app.config_dynamic import get_setting
    if not (get_setting("meta_phone_number_id", tenant_id=tenant_id) and get_setting("meta_access_token", tenant_id=tenant_id)):
        return 0
    cands = await _io(_candidates, db, tenant_id, now)
    if not cands:
        return 0
    recent = (await _io(lambda: db.table("customer_feedback").select("phone").eq("tenant_id", tenant_id)
                        .neq("status", "failed").gte("asked_at", _iso(now - REPEAT_GAP))
                        .limit(5000).execute())).data or []
    asked_phones = {r["phone"] for r in recent}
    business = await _io(_business_name, db, tenant_id)
    sent = tried = 0
    for c in cands:
        if tried >= MAX_PER_TENANT:
            break
        before = len(asked_phones)
        try:
            if await _ask_one(db, tenant_id, c, business, now, asked_phones):
                sent += 1
        except Exception as e:
            logger.warning("feedback: one ask failed: %s", e)
        if len(asked_phones) > before:
            tried += 1
    return sent


# ───────────────────────────────────────────────────────────── bells

def _bell_recipients(db, tenant_id: str) -> list[str]:
    """Owners and people who can manage customers."""
    ids: list[str] = []
    try:
        users = db.table("tenant_users").select("user_id, role, role_id").eq("tenant_id", tenant_id).execute().data or []
        roles = db.table("tenant_roles").select("id, permissions").eq("tenant_id", tenant_id).execute().data or []
        managers = {r["id"] for r in roles if "leads.manage" in (r.get("permissions") or [])}
        for u in users:
            if u.get("role") == "owner" or u.get("role_id") in managers:
                ids.append(str(u["user_id"]))
    except Exception as e:
        logger.warning("feedback bell: could not list who to tell: %s", e)
    return ids


def _bell_url(feedback_id: str) -> str:
    return f"{FEEDBACK_URL}&fb={feedback_id}"


def _bell_text(stars: int, name: str, reason: str | None = None) -> str:
    text = f"⭐ {stars} from {name}"
    return f"{text}: {reason}" if reason else text


def _ring_unhappy(db, tenant_id: str, row: dict, stars: int) -> None:
    """Bell + push to the owners. Never raises."""
    try:
        from app.services.notify import notify_user
        lead = _lead_row(db, tenant_id, row.get("lead_id"), row.get("phone"))
        who = _first_name(lead.get("name")) if lead.get("name") else (row.get("phone") or "a customer")
        for uid in _bell_recipients(db, tenant_id):
            notify_user(tenant_id, uid, BELL_TYPE, "Unhappy customer", _bell_text(stars, who),
                        db=db, push_url=_bell_url(str(row["id"])))
    except Exception as e:
        logger.warning("feedback %s: bell failed: %s", row.get("id"), e)


def _update_bell(db, tenant_id: str, row: dict, stars: int, reason: str) -> None:
    """Put the customer's reason into the bell the owners already have. Never raises."""
    try:
        lead = _lead_row(db, tenant_id, row.get("lead_id"), row.get("phone"))
        who = _first_name(lead.get("name")) if lead.get("name") else (row.get("phone") or "a customer")
        db.table("app_notifications").update({"message": _bell_text(stars, who, reason[:200])}).eq(
            "tenant_id", tenant_id).eq("type", BELL_TYPE).eq("url", _bell_url(str(row["id"]))).execute()
    except Exception as e:
        logger.warning("feedback %s: bell not updated: %s", row.get("id"), e)


# ───────────────────────────────────────────────────────────── customer replies

def _same_phone(a: str | None, b: str | None) -> bool:
    from app.services.booking_messages import _same_phone as same
    return same(a, b)


async def handle_feedback_button(db, tenant_id: str, lead_id: str | None, phone: str, payload: str) -> bool:
    """A tap on the star message: payload fb:<stars>:<id>. True = handled (the AI must not see it)."""
    try:
        m = _PAYLOAD.match((payload or "").strip())
        if not m or not phone:
            return False
        stars, fid = int(m.group(1)), m.group(2)
        rows = (await _io(lambda: db.table("customer_feedback").select("*").eq("id", fid)
                          .eq("tenant_id", tenant_id).limit(1).execute())).data or []
        if not rows or not _same_phone(rows[0].get("phone"), phone):
            return False
        row = rows[0]
        if row.get("status") == "fixed":
            return True                              # the owner already closed it; the tap changes nothing
        previous = row.get("stars")
        if previous == stars:
            return True                              # the same tap delivered twice
        now = _now()
        if previous is None:                         # first tap wins; a double tap lands on the branch below
            res = await _io(lambda: db.table("customer_feedback").update({
                "stars": stars, "status": "answered", "answered_at": _iso(now),
            }).eq("id", fid).eq("tenant_id", tenant_id).is_("stars", "null").execute())
            if not (res.data or []):
                return True
        else:                                        # a later tap changes the stars, never the first time
            res = await _io(lambda: db.table("customer_feedback").update({"stars": stars})
                            .eq("id", fid).eq("tenant_id", tenant_id).neq("status", "fixed").execute())
            if not (res.data or []):
                return True
            # A changed tap is saved quietly: no second reply, no second bell, so re-tapping can't spam
            # the customer or ring the owner again and again.
            return True
        lead_id = lead_id or row.get("lead_id")
        if stars > UNHAPPY_MAX:
            await _say(db, tenant_id, lead_id, phone, await _io(_thanks_text, db, tenant_id, row))
        else:
            await _say(db, tenant_id, lead_id, phone, "Sorry to hear that. What went wrong?")
            await _io(_ring_unhappy, db, tenant_id, row, stars)
        return True
    except Exception as e:
        logger.warning("feedback button handler failed: %s", e)
        return False


def _thanks_text(db, tenant_id: str, row: dict) -> str:
    lead = _lead_row(db, tenant_id, row.get("lead_id"), row.get("phone"))
    text = f"Thank you, {_first_name(lead.get('name'))}! We are so glad you liked it."
    link = review_link(tenant_id)
    if link:
        text += f"\nIf you have a minute, a Google review helps us a lot: {link}"
    offer = offer_text(tenant_id)
    if offer:
        text += f"\n{offer}"
    return text


async def handle_feedback_text(db, tenant_id: str, lead_id: str, phone: str, body: str) -> bool:
    """The customer's next message after a 1-3 star tap is the reason. False = not for us (normal AI reply)."""
    try:
        from app.services.booking_messages import clean_text
        reason = clean_text(body, REASON_MAX)
        if not reason or not (lead_id or phone):
            return False
        since = _iso(_now() - REASON_WINDOW)

        def find() -> dict | None:
            q = (db.table("customer_feedback").select("*").eq("tenant_id", tenant_id).eq("status", "answered")
                 .lte("stars", UNHAPPY_MAX).gte("answered_at", since).order("answered_at", desc=True))
            rows = (q.eq("lead_id", lead_id).limit(5).execute()).data if lead_id else []
            if not rows and phone:
                rows = (db.table("customer_feedback").select("*").eq("tenant_id", tenant_id)
                        .eq("status", "answered").lte("stars", UNHAPPY_MAX).gte("answered_at", since)
                        .eq("phone", phone).order("answered_at", desc=True).limit(5).execute()).data or []
            return next((r for r in rows or [] if not (r.get("reason") or "").strip()), None)

        row = await _io(find)
        if not row:
            return False
        res = await _io(lambda: db.table("customer_feedback").update({"reason": reason, "reason_at": _iso(_now())})
                        .eq("id", row["id"]).eq("tenant_id", tenant_id).is_("reason", "null").execute())
        if not (res.data or []):
            return False
        await _io(_update_bell, db, tenant_id, row, int(row["stars"]), reason)
        if "?" in reason:
            # "Where is my refund?" is saved as the reason (the owner sees it) but still needs a real answer,
            # so the AI replies instead of a canned thank-you.
            return False
        await _say(db, tenant_id, lead_id, phone, "Thank you, we'll look into it.")
        return True
    except Exception as e:
        logger.warning("feedback text handler failed: %s", e)
        return False
