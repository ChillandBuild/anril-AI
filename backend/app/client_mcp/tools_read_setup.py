"""Ask tools: numbers, calling setup, scripts, call review, website connection, SMS and OTP.

Read-only: the wrapper runs each with the database locked against writes. Every query starts
from wrapper.tenant_id(). Where an existing page would call Meta, Bulk9 or TeleCMI over the
network (live SMS balance, DLT lists, Meta charges, Instant forms status), these tools read
what Anril has already stored instead. Nothing here returns a key, token, secret, password or
OTP code: rows are built from allowed fields and then passed through _clean().
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone

from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp import leads as lead_lookup
from app.client_mcp.wrapper import client_tool, tenant_id
from app.db.supabase import get_supabase
from app.services import calling_overview, meta_charges, number_health, otp as otp_svc
from app.services import otp_overview as otp_overview_svc
from app.services import qr_links, sms_campaigns as camp, sms_setup, whatsapp_forms
from app.services import call_teams
from app.services.assignment import get_telecalling_config
from app.services.assignment_rules import get_channel_rules
from app.services.intake import get_intake_config
from app.services.numbers_pool import get_unlocked_number_ids, numbers_pool_limit
from app.services.webhook_health import get_webhook_health

MAX_PAGE = 50
_IST = timezone(timedelta(hours=5, minutes=30))

# Field names that are never returned, whatever table they come from.
_SECRET_PARTS = (
    "secret", "token", "password", "passwd", "hash", "credential", "signature", "authorization",
    "api_key", "apikey", "access_key", "private_key", "developer_key", "signing_key", "key_prefix",
)
_SECRET_NAMES = {"key", "code", "otp", "code_masked", "otp_code", "encrypted_code", "code_enc", "pin"}


def _is_secret(name) -> bool:
    low = str(name).lower()
    return low in _SECRET_NAMES or any(part in low for part in _SECRET_PARTS)


def _clean(value):
    """A copy of `value` with every secret-looking field dropped, at any depth."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not _is_secret(k)}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _clip(text, size: int = 1500):
    if isinstance(text, str) and len(text) > size:
        return text[:size] + "…"
    return text


def _check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_PAGE:
        raise ToolError(f"limit must be between 1 and {MAX_PAGE}.")
    return limit


def _rows(query) -> list[dict]:
    return query.execute().data or []


def _setting_value(db, tenant: str, key: str):
    rows = _rows(db.table("app_settings").select("value").eq("tenant_id", tenant).eq("key", key).limit(1))
    return rows[0].get("value") if rows else None


def _has_setting(db, tenant: str, key: str) -> bool:
    """Whether a setting is filled in. The value itself is never returned."""
    return bool(_setting_value(db, tenant, key))


def _feature_on(db, tenant: str, feature: str) -> bool:
    rows = _rows(db.table("tenants").select("enabled_features").eq("id", tenant).limit(1))
    return feature in ((rows[0].get("enabled_features") if rows else None) or [])


def _mask_phone(phone) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    return "+" + "*" * max(len(digits) - 4, 0) + digits[-4:] if digits else ""


# ── numbers ───────────────────────────────────────────────────────────────────

_NUMBER_FIELDS = (
    "id", "number", "display_name", "role", "status", "quality_rating", "messaging_tier",
    "paused_outbound", "meta_status", "meta_code_verification", "created_at",
)
_VOICE_FIELDS = (
    "id", "number", "display_name", "provider", "status", "pickup_rate", "calls_today",
    "spam_score", "is_primary",
)


@client_tool(title="Phone numbers")
def phone_numbers() -> dict:
    """Your WhatsApp numbers (role, status, Meta quality and daily limit, warm-up state, whether
    each is locked by your plan) and your calling numbers. No tokens or keys."""
    db, tenant = get_supabase(), tenant_id()
    rows = _rows(
        db.table("phone_numbers").select("*").eq("tenant_id", tenant)
        .order("role").order("quality_rating").limit(MAX_PAGE)
    )
    now = datetime.now(timezone.utc)
    unlocked = get_unlocked_number_ids(db, tenant)
    active = [r for r in rows if r.get("status") != "archived"]
    whatsapp = []
    for r in rows:
        item = {k: r.get(k) for k in _NUMBER_FIELDS}
        item["locked"] = r.get("status") != "archived" and r.get("id") not in unlocked
        item["health"] = number_health.health(r, now)
        whatsapp.append(item)
    voice = _rows(
        db.table("voice_numbers").select("*").eq("tenant_id", tenant).neq("status", "archived")
        .order("spam_score").order("pickup_rate", desc=True).limit(MAX_PAGE)
    )
    return _clean({
        "whatsapp_numbers": whatsapp,
        "numbers_pool": {
            "limit": numbers_pool_limit(db, tenant), "used": len(active),
            "meta_daily_limit": number_health.portfolio_limit(active),
        },
        "calling_numbers": [{k: r.get(k) for k in _VOICE_FIELDS} for r in voice],
    })


# ── calling setup and scripts ─────────────────────────────────────────────────

@client_tool(title="Calling setup")
def calling_setup() -> dict:
    """How your team calls: SIM or cloud, whether telecalling is on, which leads go to callers
    and how (channel rules), the daily target and hours, who is ready to call, and the call teams."""
    db, tenant = get_supabase(), tenant_id()
    config = get_telecalling_config(tenant, db=db)
    overview = call_teams.teams_overview(db, tenant)
    return _clean({
        "telecalling": {**config, "channel_rules": get_channel_rules(config)},
        "who_is_ready": calling_overview.overview(db, tenant),
        "teams": [
            {
                "name": t.get("name"),
                "members": [m.get("name") for m in t.get("members") or []],
                "leaders": [m.get("name") for m in t.get("leaders") or []],
            }
            for t in overview.get("teams") or []
        ],
        "not_in_a_team": [m.get("name") for m in overview.get("unassigned") or []],
        "teams_ready": overview.get("ready"),
    })


@client_tool(title="Call scripts")
def call_scripts(script_id: str = "") -> dict:
    """Your call scripts (name, segment, whether default or active, number of steps). Pass
    script_id (an id from this list) to get one script with all its steps."""
    db, tenant = get_supabase(), tenant_id()
    if script_id:
        rows = _rows(
            db.table("call_scripts").select("*").eq("id", lead_lookup.as_uuid(script_id, "script_id"))
            .eq("tenant_id", tenant).limit(1)
        )
        if not rows:
            raise ToolError("No call script with that id in your account.")
        return {"script": _clean(rows[0])}
    rows = _rows(
        db.table("call_scripts").select("*").eq("tenant_id", tenant)
        .order("created_at", desc=True).limit(MAX_PAGE)
    )
    return {"scripts": [
        {
            "id": r.get("id"), "name": r.get("name"), "segment": r.get("segment"),
            "is_default": bool(r.get("is_default")), "active": r.get("active") is not False,
            "steps": len(r.get("steps") or []), "created_at": r.get("created_at"),
        }
        for r in rows
    ]}


# ── call review ───────────────────────────────────────────────────────────────

def _owner_ctx(tenant: str) -> dict:
    """The context the Call Review routes expect. Only the owner connects, so they see everyone."""
    return {"tenant_id": tenant, "role": "owner", "permissions": []}


def _drive(coro):
    """Run an async route handler that never awaits anything slow (tools run in a worker thread)."""
    return asyncio.run(coro)


def _call_card(call: dict) -> dict:
    # The route already turned the transcript into a first/last-line preview.
    card = {k: v for k, v in call.items() if k not in ("recording_url", "callers", "transcript", "ai_summary")}
    card["has_recording"] = bool(call.get("recording_url"))
    card["caller"] = (call.get("callers") or {}).get("name")
    card["summary"] = _clip(call.get("ai_summary"))
    return card


@client_tool(title="Call review")
def call_review(limit: int = 50, lead_id: str = "", days: int = 30) -> dict:
    """Telecaller call review for the last `days` (1 to 90, default 30): one row per lead with
    calls, connected calls, talk time, scores and notes, most recent first. Pass lead_id (from
    find_leads) to get that lead's call cards (score, summary, transcript preview) instead."""
    from app.routes import call_review as review

    _check_limit(limit)
    if not 1 <= days <= 90:
        raise ToolError("days must be between 1 and 90.")
    db, tenant = get_supabase(), tenant_id()
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=days + 1)
    if lead_id:
        lead = lead_lookup.own_lead(db, tenant, lead_id)  # a lead of another client is not found
        answer = _drive(review.review_lead_calls(
            lead_id=lead_lookup.as_uuid(lead["id"]), start=start.isoformat(), end=end.isoformat(),
            caller_id=None, ctx=_owner_ctx(tenant),
        ))
        return {"lead": lead_lookup.public(lead), "calls": [_call_card(c) for c in answer["data"][:limit]]}
    answer = _drive(review.review_leads(
        start=start.isoformat(), end=end.isoformat(), caller_id=None, ctx=_owner_ctx(tenant),
    ))
    data = answer["data"]
    return {
        "leads": _clean(data[:limit]), "more": len(data) > limit,
        "truncated": bool(answer.get("truncated")),
    }

# ── website, forms, QR and setup ──────────────────────────────────────────────

def _instant_forms(db, tenant: str) -> dict:
    """Meta lead forms as Anril has stored them. Meta itself is not asked."""
    connected = _has_setting(db, tenant, "facebook_page_id") and _has_setting(db, tenant, "facebook_access_token")
    forms = _rows(
        db.table("meta_lead_forms").select("form_id,name,status,meta_created_at,questions")
        .eq("tenant_id", tenant).order("meta_created_at", desc=True).limit(MAX_PAGE)
    )
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    counts: dict[str, int] = {}
    start = 0
    while start < 5000:
        page = _rows(
            db.table("meta_form_leads").select("form_id").eq("tenant_id", tenant)
            .gte("meta_created_at", since).order("id").range(start, start + 999)
        )
        for r in page:
            counts[r.get("form_id")] = counts.get(r.get("form_id"), 0) + 1
        if len(page) < 1000:
            break
        start += 1000
    return {
        "facebook_page_connected": connected,
        "forms": [
            {
                "form_id": f.get("form_id"), "name": f.get("name") or "Untitled form",
                "status": f.get("status"), "created_at": f.get("meta_created_at"),
                "questions": len(f.get("questions") or []), "leads_last_30_days": counts.get(f.get("form_id"), 0),
            }
            for f in forms
        ],
        "note": "From what Anril has stored. Live Meta status and ad spend are on the Instant forms page.",
    }


@client_tool(title="Connect your website")
def connect_website() -> dict:
    """How customers reach you from outside WhatsApp: your QR codes and links (with scans, chats
    and new customers), the WhatsApp form / intake setup, and your Meta lead forms."""
    db, tenant = get_supabase(), tenant_id()
    qr = qr_links.list_links(db, tenant, include_money=False)
    intake = get_intake_config(tenant, db=db)
    for key in ("fields", "packages"):
        intake[key] = (intake.get(key) or [])[:MAX_PAGE]
    return _clean({
        "qr_links": qr["items"][:MAX_PAGE],
        "qr_places": [p.get("name") for p in qr.get("places") or []][:MAX_PAGE],
        "intake_config": intake,
        "whatsapp_form": whatsapp_forms.intake_status(db, tenant),
        "instant_forms": _instant_forms(db, tenant),
    })


_CHANNEL_SETTINGS = {
    "whatsapp": ("meta_phone_number_id", "meta_access_token"),
    "instagram": ("instagram_access_token",),
    "facebook": ("facebook_page_id", "facebook_access_token"),
    "telegram": ("telegram_bot_token",),
    "meta_ads": ("meta_ads_access_token", "meta_ads_account_id"),
    "sms": ("bulk9_api_key",),
}


@client_tool(title="Setup status")
def setup_status() -> dict:
    """Is everything connected and working: which channels are connected (yes or no), when each
    channel last received a message, token problems in the last 48 hours, AI replies used this
    period, and your daily messaging limit."""
    db, tenant = get_supabase(), tenant_id()
    wanted = sorted({k for keys in _CHANNEL_SETTINGS.values() for k in keys})
    filled = {
        r.get("key") for r in _rows(
            db.table("app_settings").select("key,value").eq("tenant_id", tenant).in_("key", wanted)
        ) if r.get("value")
    }
    health = get_webhook_health(db, tenant)
    return _clean({
        "channels_connected": {
            name: all(k in filled for k in keys) for name, keys in _CHANNEL_SETTINGS.items()
        },
        "last_message_received": {ch: v.get("last_event") for ch, v in health["health"].items()},
        "connection_problems_48h": [
            {**a, "error": _clip(a.get("error"), 300)} for a in health["token_alerts"][:MAX_PAGE]
        ],
        "ai_replies": meta_charges.ai_replies(db, tenant),
        "daily_messaging_limit": meta_charges.daily_limit(db, tenant),
        "note": "Meta's monthly charges are on the Connections page; they need a live call to Meta.",
    })

# ── SMS ───────────────────────────────────────────────────────────────────────

_OTP_WORDS = re.compile(r"otp|one[- ]time|verification code|passcode|security code", re.I)


def _hide_codes(content):
    """A message that looks like a one-time code has its 4 to 8 digit numbers hidden."""
    if isinstance(content, str) and _OTP_WORDS.search(content):
        return re.sub(r"(?<!\d)\d{4,8}(?!\d)", "••••", content)
    return content


def _sms_status_counts(db, tenant: str, days: int = 7) -> dict:
    today = datetime.now(_IST).date()
    first = today - timedelta(days=days - 1)
    lo = datetime(first.year, first.month, first.day, tzinfo=_IST).isoformat()
    counts = {s: 0 for s in camp.STATUSES}
    start = 0
    while start < 20000:
        page = _rows(
            db.table("sms_messages").select("status,created_at").eq("tenant_id", tenant)
            .gte("created_at", lo).order("id").range(start, start + 999)
        )
        for r in page:
            if r.get("status") in counts:
                counts[r["status"]] += 1
        if len(page) < 1000:
            break
        start += 1000
    return {"from": first.isoformat(), "to": today.isoformat(), "by_status": counts, "total": sum(counts.values())}


@client_tool(title="SMS overview")
def sms_overview() -> dict:
    """Anril SMS: whether it is on and connected, the last stored SMS balance, your sender IDs
    and DLT entities, templates, the latest campaigns with delivery counts, and the last 7 days
    of messages by status. Never the developer key."""
    db, tenant = get_supabase(), tenant_id()
    enabled = _feature_on(db, tenant, "sms")
    connected = _has_setting(db, tenant, "bulk9_api_key")
    templates = _rows(
        db.table("sms_templates").select("*").eq("tenant_id", tenant)
        .order("created_at", desc=True).limit(MAX_PAGE)
    )
    status = {
        "enabled": enabled, "connected": connected,
        "templates_ready": any(t.get("status") == "ready" for t in templates),
        "support_contact": _setting_value(db, tenant, "sms_support_contact") or "",
    }
    if not enabled:
        return {"status": status, "note": "Anril SMS is not switched on for this account."}
    wallet = _rows(db.table("sms_wallet").select("*").eq("tenant_id", tenant).limit(1))
    approved = []
    seen = set()
    for t in templates:
        pair = (t.get("sender_id"), t.get("entity_id"))
        if t.get("status") == "ready" and t.get("sender_id") and pair not in seen:
            seen.add(pair)
            approved.append({"sender_id": pair[0], "entity_id": pair[1], "entity_name": t.get("entity_name")})
    campaigns = _rows(
        db.table("sms_campaigns").select("*").eq("tenant_id", tenant).is_("deleted_at", "null")
        .order("created_at", desc=True).limit(20)
    )
    synced = [t["last_synced_at"] for t in templates if t.get("last_synced_at")]
    return _clean({
        "status": status,
        "balance": {
            "sms_left": wallet[0].get("sms_count") if wallet else None,
            "checked_at": wallet[0].get("checked_at") if wallet else None,
            "note": "The last stored balance (refreshed about every 15 minutes), not a live check.",
        },
        "senders": sms_setup.senders(db, tenant, approved),
        "dlt_entities": sms_setup.entities(db, tenant, approved),
        "templates": [{k: t.get(k) for k in (
            "id", "message_id", "dlt_template_id", "sender_id", "entity_id", "entity_name", "message",
            "var_count", "template_type", "status", "last_synced_at")} for t in templates],
        "templates_last_synced_at": max(synced) if synced else None,
        "campaigns": camp.public_campaigns(db, tenant, campaigns),
        "last_7_days": _sms_status_counts(db, tenant),
    })


@client_tool(title="SMS messages")
def sms_messages(limit: int = 50) -> dict:
    """The newest SMS messages sent from your account (recipient, text, status, failure reason,
    when submitted and delivered), newest first. limit is at most 50."""
    _check_limit(limit)
    db, tenant = get_supabase(), tenant_id()
    res = (
        db.table("sms_messages").select("*", count="exact").eq("tenant_id", tenant)
        .order("created_at", desc=True).range(0, limit - 1).execute()
    )
    messages = camp.public_messages(db, tenant, res.data or [])
    for m in messages:
        m["content"] = _hide_codes(m.get("content"))
    return _clean({"messages": messages, "total": res.count or 0})

# ── OTP ───────────────────────────────────────────────────────────────────────

_OTP_SETTING_FIELDS = (
    "default_mode", "fallback_wait_seconds", "max_per_hour", "expiry_minutes", "code_length",
    "max_attempts", "sms_sender_id", "sms_message_id", "wa_template_name", "wa_template_language",
)


def _otp_history_row(row: dict) -> dict:
    """One code request as the History page shows it, minus the code and with the phone masked."""
    return {
        "otp_id": row.get("otp_id"), "phone": _mask_phone(row.get("phone")), "mode": row.get("mode"),
        "source": row.get("source"), "origin": row.get("origin"), "status": row.get("status"),
        "attempts": row.get("attempts"), "expires_at": row.get("expires_at"),
        "verified_at": row.get("verified_at"), "sms": row.get("sms"), "whatsapp": row.get("whatsapp"),
        "whatsapp_backup_sent": row.get("whatsapp_backup_sent"),
        "not_requested": row.get("not_requested"), "created_at": row.get("created_at"),
    }


def _otp_sources(sources: list[dict]) -> list[dict]:
    """Where codes come from, with API keys named only as 'Website or app key N'."""
    out, n = [], 0
    for s in sources:
        label = s.get("label")
        if str(s.get("key", "")).startswith("key:"):
            n += 1
            label = f"Website or app key {n}"
        out.append({"label": label, "sent": s.get("sent"), "used_pct": s.get("used_pct")})
    return out


def _otp_channels(db, tenant: str, cfg: dict) -> dict:
    sms_problem = None
    if not _feature_on(db, tenant, "sms"):
        sms_problem = "Anril SMS isn't switched on for this account."
    elif not _has_setting(db, tenant, "bulk9_api_key"):
        sms_problem = "Connect your SMS account first."
    elif not cfg.get("sms_sender_id") or not cfg.get("sms_message_id"):
        sms_problem = "Pick the SMS template the code goes in (OTP settings)."
    wa_problem = None
    if not (_has_setting(db, tenant, "meta_phone_number_id") and _has_setting(db, tenant, "meta_access_token")):
        wa_problem = "Connect your WhatsApp number first."
    elif not cfg.get("wa_template_name") or not cfg.get("wa_template_language"):
        wa_problem = "Pick an approved WhatsApp authentication template (OTP settings)."
    return {
        "sms": {"ready": sms_problem is None, "problem": sms_problem},
        "whatsapp": {"ready": wa_problem is None, "problem": wa_problem},
    }


@client_tool(title="OTP overview")
def otp_overview() -> dict:
    """Anril OTP: this month's codes (sent, used, by SMS and WhatsApp), where they come from, the
    last 7 days, health checks, settings, whether SMS and WhatsApp are ready, usable templates, and
    the 20 latest requests with the phone masked. Never a code or an API key value."""
    db, tenant = get_supabase(), tenant_id()
    otp_overview_svc._cache.pop(tenant, None)  # a stale copy must not hide a change
    overview = otp_overview_svc.overview(db, tenant)
    cfg = otp_svc.get_settings(db, tenant)
    keys = _rows(db.table("otp_api_keys").select("id,status,created_at").eq("tenant_id", tenant))
    active = [k for k in keys if k.get("status") == "active"]
    sms_templates = _rows(
        db.table("sms_templates").select("sender_id,message_id,message,var_count,status")
        .eq("tenant_id", tenant).eq("status", "ready").limit(MAX_PAGE)
    )
    wa_templates = _rows(
        db.table("message_templates").select("name,language,status,category,body_text")
        .eq("tenant_id", tenant).limit(200)
    )
    return _clean({
        "this_month": overview.get("month"),
        "in_short": overview.get("in_short"),
        "last_7_days": overview.get("daily_7"),
        "sources": _otp_sources(overview.get("sources") or []),
        "sms_balance": overview.get("balance"),
        "health": overview.get("health"),
        "last_7_days_totals": otp_svc.stats(db, tenant, 7),
        "settings": {k: cfg.get(k) for k in _OTP_SETTING_FIELDS},
        "website_status_updates_set": bool(cfg.get("status_webhook_url")),
        "channels": _otp_channels(db, tenant, cfg),
        "website_keys": {
            "has_active_key": bool(active),
            "active_count": len(active),
            "newest_created_at": max((k.get("created_at") or "" for k in active), default=None) or None,
        },
        "sms_templates_for_codes": [
            {"sender_id": t.get("sender_id"), "message_id": str(t.get("message_id")), "message": t.get("message")}
            for t in sms_templates if int(t.get("var_count") or 0) == 1
        ],
        "whatsapp_templates_for_codes": [
            {"name": t.get("name"), "language": t.get("language"), "status": t.get("status"),
             "body": t.get("body_text")}
            for t in wa_templates if str(t.get("category") or "").upper() == "AUTHENTICATION"
        ],
        "recent_requests": [_otp_history_row(r) for r in otp_svc.history(db, tenant, limit=20)],
    })
