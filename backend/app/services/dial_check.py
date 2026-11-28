"""Manual Dial "Before you call" check: one phone match and the plain pass/fail rows the screen shows.

`find_lead_for_dial` is also what `POST /calls/initiate` uses, so a number typed as 9843120123 finds a
lead stored as +919843120123 and the Said stop / Do not call rules still hold.
"""
import re

from app.services.call_rules import clock_words, hours_message, now_ist, within_calling_hours

_LEAD_FIELDS = "id,name,phone,segment,do_not_call,opted_out,source,created_at,ad_campaign_id,qr_link_id"

_PLAIN_PHONE = re.compile(r"^[\d\s+\-]+$")

SAID_STOP_MESSAGE = "This customer is on Said stop, so they can't be called"
DO_NOT_CALL_MESSAGE = "Lead is on Do Not Call"
DAILY_LIMIT_MESSAGE = "Daily call limit reached"


def phone_variants(raw: str) -> list[str]:
    """The typed text, then +91XXXXXXXXXX, 91XXXXXXXXXX and XXXXXXXXXX (last 10 digits) when there are 10 or more."""
    raw = raw or ""
    # Only plain phone text goes into the database filter; anything else gets just the digit forms.
    out = [raw] if _PLAIN_PHONE.match(raw) else []
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 10:
        last10 = digits[-10:]
        out += [f"+91{last10}", f"91{last10}", last10]
    return list(dict.fromkeys(out))


def find_lead_for_dial(db, tenant_id: str, phone: str) -> dict | None:
    """The newest lead of this business whose number matches the typed one in any common spelling.

    The same number can exist as more than one lead (different spellings). The newest row is returned for
    linking the call, but opted_out / do_not_call are true if ANY matching row has them, so an older
    duplicate's Said stop still blocks the call.
    """
    variants = phone_variants(phone)
    if not variants:
        return None
    res = (
        db.table("leads").select(_LEAD_FIELDS)
        .eq("tenant_id", tenant_id).in_("phone", variants)
        .order("created_at", desc=True).limit(10).execute()
    )
    rows = (res.data if res else None) or []
    if not rows:
        return None
    return {
        **rows[0],
        "opted_out": any(r.get("opted_out") for r in rows),
        "do_not_call": any(r.get("do_not_call") for r in rows),
    }


def _clock(dt) -> str:
    t = now_ist(dt)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def build_checks(
    *, lead: dict | None, rules: dict, role: str | None, calls_today: int,
    last_call_at, limit_reached: bool, now,
) -> tuple[list[dict], str | None]:
    """(checks, blocked_reason). Pure: no database. blocked_reason is the first blocked row's message."""
    lead = lead or {}
    checks: list[dict] = []
    reasons: list[str | None] = []

    def add(key, label, state, detail=None, reason=None):
        checks.append({"key": key, "label": label, "state": state, "detail": detail})
        reasons.append(reason if state == "blocked" else None)

    stopped = bool(lead.get("opted_out"))
    add("said_stop", "Not on Said stop", "blocked" if stopped else "ok", "On Said stop" if stopped else None, SAID_STOP_MESSAGE)
    dnc = bool(lead.get("do_not_call"))
    add("do_not_call", "Not marked Do not call", "blocked" if dnc else "ok", "Marked Do not call" if dnc else None, DO_NOT_CALL_MESSAGE)
    add("dnd", "National DND list", "not_checked", "Not checked")

    if rules.get("calling_hours_on"):
        label = f"Calling hours {clock_words(rules['calling_start'])} – {clock_words(rules['calling_end'])}"
        if within_calling_hours(rules, now):
            add("hours", label, "ok", _clock(now))
        elif role == "caller":
            add("hours", label, "blocked", "Outside hours", hours_message(rules))
        else:
            add("hours", label, "warn", "Outside hours")

    if role == "caller" and rules.get("daily_limit_on"):
        add("daily_limit", "Daily call limit", "blocked" if limit_reached else "ok",
            "Reached" if limit_reached else None, DAILY_LIMIT_MESSAGE)

    if calls_today >= 1:
        label = f"Called {calls_today} time{'s' if calls_today != 1 else ''} today already"
        add("called_today", label, "warn", f"Last: {_clock(last_call_at)}" if last_call_at else None)

    return checks, next((r for r in reasons if r), None)
