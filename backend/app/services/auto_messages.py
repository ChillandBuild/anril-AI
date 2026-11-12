"""Auto-Messages: a customer's number + an event arrives (website form, API
call) and the tenant's approved template for that event goes out at once.
See docs/designs/auto-messages.md.

Owner decision 2026-10-08: one engine, every message instant, no checks. There is no
opt-out skip, no 24-hour duplicate skip, no quiet hours and no per-rule wait
(auto_message_rules.delay_minutes stays in the table but is never read).

Flow: parse -> lead (create_inbound_lead) -> the event's rule -> auto_message_sends row
(queued, send_at = now) -> sent inline. The scheduler (process_due_sends) only picks up
a row the inline send never finished, as a retry path. Every outcome, including "no rule",
is a row in auto_message_sends so the owner can see why someone got nothing.
"""
import logging
import re
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Built-in events live in code; a tenant's own events live in auto_message_events (migration 221).
BUILTIN_EVENTS = (
    {"key": "interested", "label": "Interested",
     "description": "Someone shows interest, for example fills in your website form."},
    {"key": "signed_up", "label": "Signed up",
     "description": "Someone creates an account or registers."},
    {"key": "purchased", "label": "Purchased",
     "description": "Someone pays or places an order."},
)
EVENTS = tuple(e["key"] for e in BUILTIN_EVENTS)
EVENT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
MAX_EVENT_KEY_LEN = 40
MAX_CUSTOM_EVENTS = 20
# 'store' stays valid for the one historical shop-counter row (CHECKs still allow it).
SOURCES = ("website", "api", "store")
_OPT_IN_SOURCE = {"website": "website_form", "api": "api", "store": "offline_event"}

# India has no daylight saving, so a fixed +05:30 offset is exact (and needs no tz database).
# Used for the owner's "this month" window, not for any send timing.
IST = timezone(timedelta(hours=5, minutes=30))

_EVENT_ALIASES = {
    "interested": "interested", "interest": "interested", "enquiry": "interested", "inquiry": "interested",
    "lead": "interested", "enquired": "interested",
    "signed_up": "signed_up", "signup": "signed_up", "sign_up": "signed_up", "register": "signed_up",
    "registered": "signed_up", "registration": "signed_up",
    "purchased": "purchased", "purchase": "purchased", "order": "purchased", "order_placed": "purchased",
    "bought": "purchased", "paid": "purchased", "sale": "purchased",
}
_PHONE_KEYS = ("phone", "mobile", "phone_number", "mobile_number", "whatsapp", "whatsapp_number", "contact", "number")
_NAME_KEYS = ("name", "full_name", "customer_name", "your_name")
_URL_KEYS = ("page_url", "url", "link")
_EVENT_KEYS = ("event", "type", "trigger")
_RESERVED = set(_PHONE_KEYS + _NAME_KEYS + _URL_KEYS + _EVENT_KEYS + ("first_name", "last_name"))
MAX_EXTRA_KEYS = 20
_MAX_FIELD_CHARS = 200

VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
# Anything that looks like a link. Names and extra fields come from a
# public form, so a link there would be sent inside the tenant's own template.
_LINK_RE = re.compile(
    r"(https?://|www\.|\b[a-z0-9-]+\.(com|in|net|org|io|co|xyz|link|ly|me|info|biz|app|site|online|shop|top|club|live)\b)",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
STUCK_AFTER = timedelta(minutes=15)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _text(value) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value).strip()[:_MAX_FIELD_CHARS]


def _first(payload: dict, keys: tuple) -> str:
    lowered = {str(k).strip().lower(): v for k, v in payload.items()}
    for key in keys:
        val = _text(lowered.get(key))
        if val:
            return val
    return ""


def normalize_event(raw: str | None) -> str | None:
    """Built-in aliases map to their key; anything else that is shaped like an event key
    (lowercased, trimmed) is returned as is; None when it can't be a key. Same contract as
    the plug-in (sdk/spec/vectors/normalize.json). Whether a non-built-in key exists for the
    tenant is resolve_event's job, so a typo never sends the wrong template."""
    if not raw:
        return "interested"
    alias = _EVENT_ALIASES.get(_NON_ALNUM.sub("_", raw.strip().lower()).strip("_"))
    if alias:
        return alias
    key = raw.strip().lower()
    return key if EVENT_KEY_RE.match(key) else None


def derive_event_key(label: str | None) -> str | None:
    """The code a developer sends, built from the name an owner typed: lowercase,
    spaces and hyphens become "_", other characters are dropped, repeats collapse.
    None when nothing valid is left (must start with a letter, 2-40 characters)."""
    text = re.sub(r"[\s-]+", "_", (label or "").strip().lower())
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")[:MAX_EVENT_KEY_LEN].strip("_")
    return text if EVENT_KEY_RE.match(text) else None


def is_reserved_event_key(key: str) -> bool:
    """A built-in key or one of its aliases: a custom event may never shadow these."""
    return key in _EVENT_ALIASES


_EVENT_FIELDS = ("id", "key", "label", "description", "created_at")


def public_event(row: dict) -> dict:
    return {k: row.get(k) for k in _EVENT_FIELDS}


def list_custom_events(db, tenant_id: str) -> list[dict]:
    rows = (
        db.table("auto_message_events").select(", ".join(_EVENT_FIELDS))
        .eq("tenant_id", tenant_id).order("created_at").execute()
    ).data or []
    return [public_event(r) for r in rows]


def find_custom_event(db, tenant_id: str, key: str) -> dict | None:
    rows = (
        db.table("auto_message_events").select("id, key, label, description, created_at")
        .eq("tenant_id", tenant_id).eq("key", key).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def resolve_event(db, tenant_id: str, raw: str | None) -> str | None:
    """The event key to use, or None for an event this tenant doesn't have: a built-in
    (with today's aliases) or the exact key of one of the tenant's own events; never guessed."""
    event = normalize_event(raw)
    if event is None or event in EVENTS:
        return event
    return event if find_custom_event(db, tenant_id, event) else None


def event_label(db, tenant_id: str, event: str) -> str:
    if event in _EVENT_LABEL:
        return _EVENT_LABEL[event]
    custom = find_custom_event(db, tenant_id, event)
    return (custom or {}).get("label") or event


def is_valid_event_key(db, tenant_id: str, key: str) -> bool:
    """Exact canonical key (no aliases): what a rule or a usage report may name."""
    return key in EVENTS or bool(EVENT_KEY_RE.match(key) and find_custom_event(db, tenant_id, key))


def parse_payload(payload: dict) -> dict:
    """Flat JSON / form fields from a website form, Zapier, Pabbly or a billing
    app. Field names vary by tool, so the common spellings are all accepted;
    anything else scalar is kept as `extra` (usable as a template variable)."""
    name = _first(payload, _NAME_KEYS)
    if not name:
        name = " ".join(p for p in (_first(payload, ("first_name",)), _first(payload, ("last_name",))) if p)
    extra = {}
    for key, value in payload.items():
        k = str(key).strip().lower()
        if k in _RESERVED or k.startswith("_") or not _text(value):
            continue
        if len(extra) >= MAX_EXTRA_KEYS:
            break
        extra[k[:50]] = _text(value)
    return {
        "phone": _first(payload, _PHONE_KEYS),
        "name": name,
        "event_raw": _first(payload, _EVENT_KEYS),
        "page_url": _first(payload, _URL_KEYS),
        "extra": extra,
    }


def pick_rule(db, tenant_id: str, event: str) -> dict | None:
    rows = (
        db.table("auto_message_rules").select("*")
        .eq("tenant_id", tenant_id).eq("event", event).eq("enabled", True).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def sent_event_keys(db, tenant_id: str) -> set[str]:
    """Events with at least one sent message, in one query (a SQL function, migration 221,
    because a plain select would stop at the PostgREST row cap)."""
    data = db.rpc("auto_message_sent_events", {"p_tenant": tenant_id}).execute().data or []
    return {(row if isinstance(row, str) else (row or {}).get("event")) for row in data} - {None}


def approved_template_ids(db, tenant_id: str, template_ids: list[str]) -> set[str]:
    if not template_ids:
        return set()
    rows = (
        db.table("message_templates").select("id, status")
        .eq("tenant_id", tenant_id).in_("id", sorted(set(template_ids))).execute()
    ).data or []
    return {r["id"] for r in rows if (r.get("status") or "").upper() == "APPROVED"}


def month_bounds_ist(now: datetime) -> tuple[datetime, datetime]:
    """[start, end) of the calendar month containing `now`, in IST, as UTC datetimes."""
    local = now.astimezone(IST)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    following = (start + timedelta(days=32)).replace(day=1)
    return start.astimezone(timezone.utc), following.astimezone(timezone.utc)


def month_summary(db, tenant_id: str, now: datetime) -> dict:
    start, end = month_bounds_ist(now)
    counts = {}
    for status in ("sent", "failed", "skipped"):
        counts[status] = (
            db.table("auto_message_sends").select("id", count="exact")
            .eq("tenant_id", tenant_id).eq("status", status)
            .gte("created_at", start.isoformat()).lt("created_at", end.isoformat())
            .limit(1).execute()
        ).count or 0
    return counts


def _add_note(db, tenant_id: str, lead_id: str, content: str) -> None:
    try:
        db.table("lead_notes").insert({
            "lead_id": lead_id, "tenant_id": tenant_id, "content": content, "is_pinned": False, "structured": False,
        }).execute()
    except Exception as e:
        logger.warning(f"auto_messages: note insert failed for lead {lead_id}: {e}")


_EVENT_LABEL = {e["key"]: e["label"] for e in BUILTIN_EVENTS}
_SOURCE_LABEL = {"website": "website form", "api": "API", "store": "shop counter"}  # store: historical rows


async def handle_event(tenant_id: str, source: str, data: dict, db=None) -> dict:
    """data = parse_payload() output.
    Returns {"status": "ok"|"ignored", ...}. Never raises for a send failure:
    the send row records it."""
    from app.routes.upload import _normalize_phone
    from app.services.inbound_lead import create_inbound_lead

    db = db or get_supabase()
    event = resolve_event(db, tenant_id, data.get("event_raw"))
    if not event:
        return {"status": "ignored", "detail": f"unknown event {data.get('event_raw')!r}"}
    phone = _normalize_phone(data.get("phone") or "")
    if not phone:
        return {"status": "ignored", "detail": "missing or invalid phone"}

    lead_id = create_inbound_lead(
        tenant_id, phone, source, name=data.get("name") or None,
        opt_in_source=_OPT_IN_SOURCE[source], db=db,
    )
    if not lead_id:
        return {"status": "ignored", "detail": "missing or invalid phone"}

    _add_note(db, tenant_id, lead_id, f"{event_label(db, tenant_id, event)} (via {_SOURCE_LABEL[source]})")

    rule = pick_rule(db, tenant_id, event)
    row = {
        "tenant_id": tenant_id, "lead_id": lead_id, "phone": phone, "name": data.get("name") or None,
        "event": event, "source": source,
        "extra": {**(data.get("extra") or {}), **({"page_url": data["page_url"]} if data.get("page_url") else {})},
    }
    if not rule:
        row.update(status="skipped", reason="no_rule")
    else:
        row.update(status="queued", rule_id=rule["id"], template_id=rule["template_id"], send_at=_utcnow().isoformat())

    inserted = db.table("auto_message_sends").insert(row).execute().data or []
    send = inserted[0] if inserted else row
    if send.get("status") == "queued" and send.get("id"):
        await send_one(db, send)
        refreshed = (
            db.table("auto_message_sends").select("status, reason").eq("id", send["id"]).limit(1).execute()
        ).data or []
        if refreshed:
            send.update(refreshed[0])
    return {
        "status": "ok", "lead_id": lead_id, "event": event, "message_status": send.get("status"), "reason": send.get("reason"),
    }


# ---------------------------------------------------------------- sending

def _clean(value) -> str:
    """Meta rejects text parameters with newlines, tabs or long runs of spaces."""
    return _WS_RE.sub(" ", str(value or "")).strip()[:500]


# Customer-supplied sources: a link in any of these is dropped (the fallback is used instead).
_UNTRUSTED = {"first_name", "full_name", "extra"}


def _resolve(spec: dict | None, ctx: dict, default_source: str) -> str:
    spec = spec or {"source": default_source}
    source = spec.get("source") or default_source
    if source == "text":
        value = spec.get("value") or ""
    elif source == "extra":
        value = (ctx.get("extra") or {}).get((spec.get("key") or "").strip().lower(), "")
    else:
        value = ctx.get(source) or ""
    value = _clean(value)
    if source in _UNTRUSTED and _LINK_RE.search(value):
        value = ""
    return value or _clean(spec.get("fallback")) or "-"


def build_components(template: dict, rule: dict, ctx: dict) -> list[dict]:
    """Body variables in {{n}} order from rule.variables (default: first name),
    the template's own image/video/document header, a {{1}} header text (the
    customer's first name), and the suffix of a dynamic URL button."""
    components: list[dict] = []

    media_type = (template.get("header_media_type") or "").upper()
    if media_type in ("IMAGE", "VIDEO", "DOCUMENT"):
        link = template.get("header_media_url")
        if link:
            components.append({"type": "header", "parameters": [{"type": media_type.lower(), media_type.lower(): {"link": link}}]})
    elif VAR_RE.search(template.get("header_text") or ""):
        text = _resolve({"source": "first_name", "fallback": "there"}, ctx, "first_name")
        components.append({"type": "header", "parameters": [{"type": "text", "text": text}]})

    var_count = len(set(VAR_RE.findall(template.get("body_text") or "")))
    if var_count:
        specs = list(rule.get("variables") or [])
        params = []
        for i in range(var_count):
            spec = specs[i] if i < len(specs) else None
            params.append({"type": "text", "text": _resolve(spec, ctx, "first_name" if i == 0 else "text")})
        components.append({"type": "body", "parameters": params})

    for index, btn in enumerate(template.get("buttons") or []):
        if (btn.get("type") or "").upper() == "URL" and VAR_RE.search(btn.get("url") or ""):
            # The suffix is pasted into the template's URL, so it must be URL-safe.
            suffix = quote(_resolve(rule.get("button_param"), ctx, "text"), safe="/?=&-_.~")
            components.append({
                "type": "button", "sub_type": "url", "index": str(index),
                "parameters": [{"type": "text", "text": suffix}],
            })
    return components


def _finish(db, send_id: str, status: str, reason: str | None = None) -> None:
    patch: dict = {"status": status, "reason": (reason or None) and reason[:300]}
    if status == "sent":
        patch["sent_at"] = datetime.now(timezone.utc).isoformat()
    db.table("auto_message_sends").update(patch).eq("id", send_id).execute()


async def send_one(db, send: dict) -> bool:
    """Claims a queued row (queued -> sending, so two runs never double-send),
    then sends. Final status: sent | failed | skipped, with a reason. No opt-out or
    quiet-hours check: a claimed row always goes out unless its rule or template is gone."""
    claimed = (
        db.table("auto_message_sends").update({"status": "sending"})
        .eq("id", send["id"]).eq("status", "queued").execute()
    ).data or []
    if not claimed:
        return False
    tenant_id = send["tenant_id"]

    from app.services.automation_guards import master_switch_on
    if not master_switch_on(tenant_id):
        _finish(db, send["id"], "skipped", "ai_auto_reply_off")
        return False

    lead = None
    if send.get("lead_id"):
        rows = (
            db.table("leads").select("id, name")
            .eq("id", send["lead_id"]).eq("tenant_id", tenant_id).limit(1).execute()
        ).data or []
        lead = rows[0] if rows else None

    rule_rows = []
    if send.get("rule_id"):
        rule_rows = (
            db.table("auto_message_rules").select("*").eq("id", send["rule_id"]).eq("tenant_id", tenant_id)
            .limit(1).execute()
        ).data or []
    if not rule_rows or not rule_rows[0].get("enabled"):
        _finish(db, send["id"], "skipped", "rule_removed_or_off")
        return False
    rule = rule_rows[0]

    template_rows = (
        db.table("message_templates")
        .select("name, language, category, body_text, status, header_media_type, header_media_url, header_text, buttons")
        .eq("id", rule["template_id"]).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not template_rows or (template_rows[0].get("status") or "").upper() != "APPROVED":
        _finish(db, send["id"], "failed", "template_not_approved")
        return False
    template = template_rows[0]

    full_name = (send.get("name") or (lead or {}).get("name") or "").strip()
    extra = dict(send.get("extra") or {})
    ctx = {
        "first_name": full_name.split(" ")[0] if full_name else "",
        "full_name": full_name,
        "page_url": extra.get("page_url", ""),
        "phone": send.get("phone") or "",
        "extra": extra,
    }

    try:
        from app.services.meta_cloud import send_template_message
        res = await send_template_message(
            send["phone"], template["name"], template.get("language") or "en",
            components=build_components(template, rule, ctx), tenant_id=tenant_id,
        )
    except Exception as e:
        detail = getattr(e, "detail", None) or str(e)
        logger.warning(f"auto_messages: send {send['id']} failed for tenant {tenant_id}: {detail}")
        _finish(db, send["id"], "failed", str(detail))
        return False

    _finish(db, send["id"], "sent")
    if send.get("lead_id"):
        try:
            sid = ((res or {}).get("messages") or [{}])[0].get("id")
            db.table("messages").insert({
                "lead_id": send["lead_id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
                "content": f"[Auto-message: {template['name']}]", "is_ai_generated": False,
                "meta_message_id": sid or "", "reply_source": "automation",
            }).execute()
        except Exception as e:
            logger.warning(f"auto_messages: message log insert failed for send {send['id']}: {e}")
    return True


# ---------------------------------------------------------------- preview

PREVIEW_FIRST_NAME = "Priya"
_META_CODE_RE = re.compile(r'"code"\s*:\s*(\d+)')
_META_MESSAGE_RE = re.compile(r'"message"\s*:\s*"([^"]+)"')
_PLAIN_META_FAILURES = {
    "131026": "WhatsApp couldn't deliver to this number. Check that it is on WhatsApp.",
    "131030": "This number isn't on your WhatsApp test list yet.",
    "131056": "WhatsApp is slowing this account down. Try again in a minute.",
    "130429": "WhatsApp is slowing this account down. Try again in a minute.",
    "132000": "The template and its values don't match. Check the message's variables.",
    "132001": "WhatsApp can't find this template. It may have been deleted.",
    "132005": "The template and its values don't match. Check the message's variables.",
    "132012": "The template and its values don't match. Check the message's variables.",
    "190": "Your WhatsApp connection has expired. Reconnect it in Settings.",
}


def _plain_failure(detail) -> str:
    text = str(detail or "")
    code = _META_CODE_RE.search(text)
    if code and code.group(1) in _PLAIN_META_FAILURES:
        return _PLAIN_META_FAILURES[code.group(1)]
    message = _META_MESSAGE_RE.search(text)
    return f"WhatsApp refused it: {message.group(1)[:150]}" if message else "WhatsApp could not send this message."


def sample_context(rule: dict, phone: str) -> dict:
    """Believable values for a preview: first name Priya, and every app field the rule
    reads shows its own name (order_id -> "order_id"), so the owner sees where it lands."""
    specs = list(rule.get("variables") or []) + ([rule["button_param"]] if rule.get("button_param") else [])
    extra = {(s.get("key") or "").strip().lower(): (s.get("key") or "sample").strip()
             for s in specs if s.get("source") == "extra" and (s.get("key") or "").strip()}
    return {
        "first_name": PREVIEW_FIRST_NAME, "full_name": PREVIEW_FIRST_NAME,
        "page_url": "https://example.com/page", "phone": phone, "extra": extra,
    }


async def send_preview(db, tenant_id: str, rule: dict, phone: str) -> dict:
    """Sends the rule's template to `phone` with sample values. Writes no lead, no
    send-log row and no message: it is only a look at what customers will get."""
    rows = (
        db.table("message_templates")
        .select("name, language, category, body_text, status, header_media_type, header_media_url, header_text, buttons")
        .eq("id", rule["template_id"]).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows or (rows[0].get("status") or "").upper() != "APPROVED":
        return {"status": "failed", "reason": "Meta has not approved this template, so it can't be sent."}
    template = rows[0]
    try:
        from app.services.meta_cloud import send_template_message
        await send_template_message(
            phone, template["name"], template.get("language") or "en",
            components=build_components(template, rule, sample_context(rule, phone)), tenant_id=tenant_id,
        )
    except Exception as e:
        detail = getattr(e, "detail", None)  # an HTTPException from Meta; anything else is a crash
        if detail is None:
            logger.error(f"auto_messages: preview crashed for tenant {tenant_id}: {e}")
            return {"status": "failed", "reason": "Something went wrong sending the preview. Try again."}
        logger.warning(f"auto_messages: preview failed for tenant {tenant_id}: {detail}")
        return {"status": "failed", "reason": _plain_failure(detail)}
    return {"status": "sent", "reason": None}


async def process_due_sends(limit: int = 50) -> int:
    """Scheduler job, a retry path: send queued rows the inline send never finished. Rows left in
    'sending' by a crash mid-send are marked failed, never re-sent: Meta may
    already have delivered them."""
    db = get_supabase()
    stuck_before = (_utcnow() - STUCK_AFTER).isoformat()
    db.table("auto_message_sends").update({"status": "failed", "reason": "interrupted"})         .eq("status", "sending").lt("send_at", stuck_before).execute()
    now = _utcnow().isoformat()
    due = (
        db.table("auto_message_sends").select("*").eq("status", "queued").lte("send_at", now)
        .order("send_at").limit(limit).execute()
    ).data or []
    sent = 0
    for row in due:
        try:
            if await send_one(db, row):
                sent += 1
        except Exception as e:
            logger.error(f"auto_messages: unexpected error on send {row.get('id')}: {e}")
    return sent
