"""v9.2 #21 Call IQ rules: calling hours, daily limit, break limit, hide numbers, SIM or cloud per person.

The business-wide rules are one JSON row in app_settings (key 'call_rules'); nothing here needs a table.
Per-person SIM/cloud lives on callers.calling_mode (migration 321). Every read falls back to the plain
defaults when the row or the column is missing, so a half-applied migration never breaks dialing.
Built by agent I-B.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
RULES_KEY = "call_rules"
MAX_DAILY_LIMIT = 1000
MAX_BREAK_MINUTES = 240

DEFAULT_RULES: dict = {
    "calling_hours_on": True,
    "calling_start": "09:00",
    "calling_end": "21:00",
    "daily_limit_on": False,
    "daily_limit": 100,
    "break_limit_minutes": 30,  # 0 = off
    "hide_numbers_for_callers": False,
}

CALLING_MODES = ("business_default", "sim", "cloud")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# ── time helpers ────────────────────────────────────────────────────────────

def now_ist(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(IST)


def ist_day_start_utc(now: datetime | None = None) -> datetime:
    """Midnight today in IST, as a UTC datetime."""
    ist = now_ist(now)
    return datetime(ist.year, ist.month, ist.day, tzinfo=IST).astimezone(timezone.utc)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def clock_words(hhmm: str) -> str:
    """'09:00' -> '9 AM', '21:30' -> '9:30 PM'."""
    h, m = (int(x) for x in hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12} {suffix}" if m == 0 else f"{h12}:{m:02d} {suffix}"


def hours_message(rules: dict) -> str:
    return f"Calling hours are {clock_words(rules['calling_start'])} to {clock_words(rules['calling_end'])}"


# ── the rules ───────────────────────────────────────────────────────────────

def clean_rules(raw: dict | None) -> dict:
    """The stored JSON merged over the defaults, every value forced into a safe shape. Never raises."""
    out = dict(DEFAULT_RULES)
    raw = raw if isinstance(raw, dict) else {}
    for key in ("calling_hours_on", "daily_limit_on", "hide_numbers_for_callers"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    for key in ("calling_start", "calling_end"):
        v = raw.get(key)
        if isinstance(v, str) and _TIME_RE.match(v):
            out[key] = v
    if _minutes(out["calling_end"]) <= _minutes(out["calling_start"]):
        out["calling_start"], out["calling_end"] = DEFAULT_RULES["calling_start"], DEFAULT_RULES["calling_end"]
    for key, hi, lo in (("daily_limit", MAX_DAILY_LIMIT, 1), ("break_limit_minutes", MAX_BREAK_MINUTES, 0)):
        v = raw.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            out[key] = v
    return out


def validate_rules(raw: dict) -> str | None:
    """A plain-English problem with a rules body someone is saving, or None when it is fine."""
    for key in ("calling_start", "calling_end"):
        v = raw.get(key)
        if not isinstance(v, str) or not _TIME_RE.match(v):
            return "Pick the calling hours as a time like 09:00."
    if _minutes(raw["calling_end"]) <= _minutes(raw["calling_start"]):
        return "Calling hours must end after they start."
    d = raw.get("daily_limit")
    if not isinstance(d, int) or isinstance(d, bool) or not 1 <= d <= MAX_DAILY_LIMIT:
        return f"The daily limit must be between 1 and {MAX_DAILY_LIMIT} calls."
    b = raw.get("break_limit_minutes")
    if not isinstance(b, int) or isinstance(b, bool) or not 0 <= b <= MAX_BREAK_MINUTES:
        return f"The break limit must be between 0 and {MAX_BREAK_MINUTES} minutes (0 switches it off)."
    return None


def get_rules(db, tenant_id: str) -> dict:
    try:
        row = (
            db.table("app_settings").select("value")
            .eq("tenant_id", tenant_id).eq("key", RULES_KEY).maybe_single().execute()
        )
        if row and row.data and row.data.get("value"):
            return clean_rules(json.loads(row.data["value"]))
    except Exception as e:
        logger.warning("call rules read failed for tenant %s, using defaults: %s", tenant_id, e)
    return dict(DEFAULT_RULES)


def save_rules(db, tenant_id: str, rules: dict) -> dict:
    cleaned = clean_rules(rules)
    db.table("app_settings").upsert(
        {"key": RULES_KEY, "value": json.dumps(cleaned), "tenant_id": tenant_id, "is_secret": False},
        on_conflict="tenant_id,key",
    ).execute()
    return cleaned


# ── hiding numbers ──────────────────────────────────────────────────────────

def mask_phone(phone: str) -> str:
    """'+919876543210' -> '98•••••210' (first 2 and last 3 digits). Short or empty numbers are fully hidden."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not digits:
        return ""
    if len(digits) <= 5:
        return "•" * len(digits)
    return digits[:2] + "•" * (len(digits) - 5) + digits[-3:]


def hides_numbers(db, tenant_id: str, ctx: dict) -> bool:
    """True when this person is a telecaller, the business hides numbers from telecallers, and this person
    calls through the cloud. On a SIM phone the phone's own dialer needs (and shows) the real number, so
    hiding it there would only stop the call."""
    if ctx.get("role") != "caller" or not bool(get_rules(db, tenant_id)["hide_numbers_for_callers"]):
        return False
    try:
        return effective_calling_mode(db, tenant_id, ctx.get("caller_id")) == "telecmi"
    except Exception:
        return True  # fail closed: the business hides numbers and we can't tell SIM from cloud


def phone_mask_for(db, tenant_id: str, ctx: dict):
    """mask_phone when this viewer must see 98•••••210, else None. Every list or file that carries a lead's
    number uses this one check. It fails closed: a telecaller never sees full numbers because a check broke."""
    if ctx.get("role") != "caller":
        return None
    try:
        return mask_phone if hides_numbers(db, tenant_id, ctx) else None
    except Exception as e:
        logger.info("number hiding check failed for tenant %s, hiding: %s", tenant_id, e)
        return mask_phone


# ── SIM or cloud per person ─────────────────────────────────────────────────

def effective_calling_mode(db, tenant_id: str, caller_id: str | None, *, business_provider: str | None = None) -> str:
    """'telecmi' (cloud) or 'sim_basic' (own SIM) for one person.

    Their own choice wins; 'business_default' (or no person, or a missing column) follows the business
    calling_provider. `business_provider` lets a caller that already read the config skip a second read.
    """
    if caller_id:
        try:
            row = (
                db.table("callers").select("calling_mode")
                .eq("id", str(caller_id)).eq("tenant_id", tenant_id).maybe_single().execute()
            )
            mode = ((row.data if row else None) or {}).get("calling_mode")
            if mode == "sim":
                return "sim_basic"
            if mode == "cloud":
                return "telecmi"
        except Exception as e:
            logger.warning("calling_mode read failed for caller %s: %s", caller_id, e)
    if business_provider is None:
        from app.services.assignment import get_telecalling_config
        business_provider = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi")
    return "sim_basic" if business_provider == "sim_basic" else "telecmi"


# ── before a telecaller dials ───────────────────────────────────────────────

def calls_made_today(db, tenant_id: str, caller_id: str, now: datetime | None = None) -> int:
    res = (
        db.table("call_logs").select("id", count="exact")
        .eq("tenant_id", tenant_id).eq("caller_id", str(caller_id))
        .gte("created_at", ist_day_start_utc(now).isoformat()).execute()
    )
    return int(res.count if res.count is not None else len(res.data or []))


def pre_dial_block(db, tenant_id: str, *, role: str | None, caller_id: str | None, now: datetime | None = None) -> str | None:
    """The plain message to refuse a dial with, or None when the call may go ahead.

    Only a telecaller (role 'caller') is held to the hours and the daily limit; the owner and managers
    may always dial. A failed read never blocks a call.
    """
    if role != "caller":
        return None
    try:
        rules = get_rules(db, tenant_id)
        if rules["calling_hours_on"]:
            t = now_ist(now)
            minute = t.hour * 60 + t.minute
            if not _minutes(rules["calling_start"]) <= minute < _minutes(rules["calling_end"]):
                return hours_message(rules)
        if rules["daily_limit_on"] and caller_id:
            if calls_made_today(db, tenant_id, caller_id, now) >= rules["daily_limit"]:
                return "Daily call limit reached"
    except Exception as e:
        logger.warning("pre-dial rules check failed for tenant %s, letting the call through: %s", tenant_id, e)
    return None


# ── break limit (the planner schedules this every 5 minutes) ────────────────

def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def check_break_limits(db, now: datetime | None = None) -> int:
    """Tell the owner (bell) once per break when a telecaller passes the break limit. Returns how many alerts went out.

    Also starts any leave whose first day has arrived (start_due_leaves), so one schedule covers both.
    """
    from app.services.call_alerts import admin_user_ids
    from app.services.notify import notify_user

    now = now or datetime.now(timezone.utc)
    sent = 0
    try:
        rows = (
            db.table("callers").select("id,tenant_id,name,status_changed_at,break_alert_sent_at")
            .eq("status", "break").eq("active", True).execute()
        ).data or []
    except Exception as e:
        logger.warning("break limit check could not read callers: %s", e)
        rows = []
    rules_by_tenant: dict[str, dict] = {}
    for c in rows:
        tenant_id = c.get("tenant_id")
        started = _parse_ts(c.get("status_changed_at"))
        if not tenant_id or not started:
            continue
        if tenant_id not in rules_by_tenant:
            rules_by_tenant[tenant_id] = get_rules(db, tenant_id)
        limit = rules_by_tenant[tenant_id]["break_limit_minutes"]
        if limit <= 0:
            continue
        minutes = int((now - started).total_seconds() // 60)
        if minutes < limit:
            continue
        already = _parse_ts(c.get("break_alert_sent_at"))
        if already and already >= started:
            continue  # this break was already reported
        try:
            name = c.get("name") or "A telecaller"
            # Stamp first: if notifying crashes half way, the next 5-minute run must not bell this break again.
            db.table("callers").update({"break_alert_sent_at": now.isoformat()}).eq("id", c["id"]).eq("tenant_id", tenant_id).execute()
            for user_id in admin_user_ids(db, tenant_id):
                notify_user(
                    tenant_id, user_id, "break_too_long", "Long break",
                    f"{name} has been on break for {minutes} minutes (the limit is {limit}).",
                    db=db, push_url="/dashboard/telecalling",
                )
            sent += 1
        except Exception as e:
            logger.warning("break alert failed for caller %s: %s", c.get("id"), e)
    try:
        from app.services.caller_leave import start_due_leaves
        start_due_leaves(db, now)
    except Exception as e:
        logger.warning("start_due_leaves failed: %s", e)
    return sent
