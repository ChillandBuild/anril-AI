"""v9.2 Mark Booked (a chat's "Book a visit", no Bookings calendar): the visit time read from the chat,
and the confirmation sent on WhatsApp.

The guess is one small model call over the last chat lines, told today's IST date so "Monday 4 mani"
becomes a real date. It is only a suggestion the teammate can change. The confirmation goes as plain
text inside WhatsApp's 24-hour window only (there is no booking row here for the booking template).
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MAX_AHEAD_DAYS = 120

_PROMPT = """Today is {today} (India time). A customer is chatting with a business. Did the customer say
when they will come for a visit / meeting? If yes, give that date and time; if they gave only a day,
use 11:00. Copy their words that say it (up to 12 words). If they did not say a time, answer
{{"at": null, "quote": null}}.

Chat (oldest first):
{chat}

Answer with JSON only: {{"at": "YYYY-MM-DDTHH:MM", "quote": "<their words>"}}"""


def parse_guess(text: str, now: datetime) -> dict:
    """{"at": ISO in IST | None, "quote"}. A time in the past or too far ahead is dropped."""
    empty = {"at": None, "quote": None}
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return empty
    try:
        data = json.loads(match.group(0))
        at = datetime.strptime(str(data.get("at") or ""), "%Y-%m-%dT%H:%M").replace(tzinfo=IST)
    except (ValueError, TypeError, AttributeError):
        return empty
    if at <= now or at > now + timedelta(days=MAX_AHEAD_DAYS):
        return empty
    quote = data.get("quote")
    quote = " ".join(quote.split())[:120] if isinstance(quote, str) and quote.strip() else None
    return {"at": at.isoformat(), "quote": quote}


def _chat(rows: list[dict]) -> str:
    lines = []
    for r in reversed(rows):  # newest first in, oldest first out
        text = " ".join((r.get("content") or "").split())[:300]
        if text:
            lines.append(f"{'Customer' if r.get('direction') == 'inbound' else 'Business'}: {text}")
    return "\n".join(lines[-14:])


async def guess(db, tenant_id: str, lead_id: str, *, llm=None, now: datetime | None = None) -> dict:
    """The visit time the customer gave in the chat, or {"at": None, "quote": None}. Never raises."""
    import asyncio
    now = now or datetime.now(IST)
    try:
        rows = (await asyncio.to_thread(lambda: db.table("messages").select("direction,content")
                                        .eq("tenant_id", tenant_id).eq("lead_id", lead_id)
                                        .order("created_at", desc=True).limit(20).execute())).data or []
        if not any(r.get("direction") == "inbound" and (r.get("content") or "").strip() for r in rows):
            return {"at": None, "quote": None}
        prompt = _PROMPT.format(today=now.astimezone(IST).strftime("%A %d %B %Y, %H:%M"), chat=_chat(rows))
        if llm is None:
            from app.services.ai_reply import _llm_chat
            text = await _llm_chat([{"role": "user", "content": prompt}], max_tokens=100, tenant_id=tenant_id,
                                   purpose="visit_time_guess", temperature=0.0)
        else:
            text = await llm(prompt)
        return parse_guess(text, now)
    except Exception:
        logger.warning("Visit time guess failed for lead %s", lead_id, exc_info=True)
        return {"at": None, "quote": None}


def confirmation_text(name: str | None, business: str | None, booked_for: str) -> str:
    from app.services.booking_messages import _first_name, clean_text, when_text
    shop = clean_text(business, 60)
    return (f"Hi {_first_name(name)}, your visit{f' to {shop}' if shop else ''} is booked for {when_text(booked_for)}. "
            "See you then! Reply here if you need to change it.")


async def send_confirmation(db, tenant_id: str, lead_id: str, booked_for: str) -> dict:
    """{"sent": bool, "reason": str}. Plain text in the 24-hour window; never raises."""
    try:
        from app.services.booking_messages import _deliver, _io
        lead = (await _io(lambda: db.table("leads").select("id,name,phone").eq("id", lead_id)
                          .eq("tenant_id", tenant_id).limit(1).execute())).data or []
        if not lead:
            return {"sent": False, "reason": "no_phone"}
        tenant = (await _io(lambda: db.table("tenants").select("name").eq("id", tenant_id)
                            .limit(1).execute())).data or [{}]
        text = confirmation_text(lead[0].get("name"), tenant[0].get("name"), booked_for)
        b = {"id": f"visit:{lead_id}", "lead_id": lead_id, "phone": lead[0].get("phone"), "source": "chat"}
        sid, reason = await _deliver(db, tenant_id, b, text=text, template_key="update", values=[], text_only=True)
        return {"sent": bool(sid), "reason": reason}
    except Exception:
        logger.warning("Visit confirmation failed for lead %s", lead_id, exc_info=True)
        return {"sent": False, "reason": "send_failed"}
