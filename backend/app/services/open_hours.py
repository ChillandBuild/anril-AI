"""v9.2 #59 + #92 Open hours: one setting, read by everything that needs to know when the shop is open.

Stored in app_settings (key open_hours, JSON):
    {"hours": {"0": [["10:00", "20:00"]], ..., "5": [["10:00", "20:00"]]}, "national_holidays": true}
0 = Monday, the same shape as a booking column's working hours (booking_setup.normalize_hours checks it).
A day left out is a closed day. Nothing saved = "not set": nothing below changes behaviour.

Who reads it:
- the AI agent's prompt (prompt_block): open now or not, today's hours, when it next opens, so a
  "are you open on Sunday?" or "can I come now?" is answered from fact;
- bookings (limit_hours / closed_on): customers and the AI are only offered times inside these hours;
- the after-hours message (after_hours.py): the team is "out" whenever the shop is closed.
The Description shows it read-only; Settings › Open hours and setup step 3 edit it."""
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import booking_setup as bsetup

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
KEY = "open_hours"
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# The three national holidays every business in India closes for (dates never move).
NATIONAL_HOLIDAYS = {(1, 26): "Republic Day", (8, 15): "Independence Day", (10, 2): "Gandhi Jayanti"}


class OpenHoursError(Exception):
    status = 422


def _blank() -> dict:
    return {"set": False, "hours": {}, "national_holidays": True}


def clean(raw: object) -> dict:
    """Lenient read of the stored value; bad blocks are dropped rather than failing a reply."""
    src = raw if isinstance(raw, dict) else {}
    hours = {str(d): [[f"{a // 60:02d}:{a % 60:02d}", f"{b // 60:02d}:{b % 60:02d}"] for a, b in blocks]
             for d, blocks in bsetup.hours_minutes(src.get("hours")).items()}
    return {"set": True, "hours": hours, "national_holidays": src.get("national_holidays") is not False}


def validate(raw: dict) -> dict:
    try:
        hours = bsetup.normalize_hours(raw.get("hours") or {})
    except bsetup.BookingError as e:
        raise OpenHoursError(str(e).replace("Working hours", "Open hours"))
    if not hours:
        raise OpenHoursError("Switch on at least one day you are open.")
    return {"set": True, "hours": hours, "national_holidays": raw.get("national_holidays") is not False}


def read(db, tenant_id: str) -> dict:
    try:
        row = (db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", KEY)
               .maybe_single().execute())
        if row and isinstance(row.data, dict) and row.data.get("value"):
            return clean(json.loads(row.data["value"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("open_hours: could not read the setting for %s (%s)", tenant_id, type(e).__name__)
    return _blank()


def save(db, tenant_id: str, raw: dict) -> dict:
    cfg = validate(raw)
    stored = {"hours": cfg["hours"], "national_holidays": cfg["national_holidays"]}
    db.table("app_settings").upsert(
        {"tenant_id": tenant_id, "key": KEY, "value": json.dumps(stored), "is_secret": False},
        on_conflict="key,tenant_id",
    ).execute()
    try:
        from app.config_dynamic import invalidate_cache
        invalidate_cache(KEY)
    except Exception:  # noqa: BLE001
        pass
    return cfg


# ── plain words ─────────────────────────────────────────────────────────────

def _clock(minutes: int) -> str:
    """630 -> '10:30 AM', 1200 -> '8 PM', 1440 -> '12 midnight'."""
    if minutes >= 1440:
        return "12 midnight"
    h, m = divmod(minutes, 60)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def _blocks_text(blocks: list[tuple[int, int]]) -> str:
    return ", ".join(f"{_clock(a)}–{_clock(b)}" for a, b in blocks)


def summary(cfg: dict) -> str:
    """'Mon–Sat, 10 AM–8 PM' / 'Mon–Fri, 9 AM–6 PM · Sat, 10 AM–2 PM' / '' when not set."""
    if not cfg.get("set"):
        return ""
    per_day = bsetup.hours_minutes(cfg.get("hours"))
    if not per_day:
        return "Closed every day"
    parts: list[tuple[list[int], str]] = []
    for d in range(7):
        text = _blocks_text(per_day[d]) if d in per_day else ""
        if parts and parts[-1][1] == text and parts[-1][0][-1] == d - 1:
            parts[-1][0].append(d)
        else:
            parts.append(([d], text))
    out = []
    for days, text in parts:
        if not text:
            continue
        label = DAY_SHORT[days[0]] if len(days) == 1 else f"{DAY_SHORT[days[0]]}–{DAY_SHORT[days[-1]]}"
        out.append(f"{label}, {text}")
    return " · ".join(out)


def holiday_name(cfg: dict, day: date) -> str:
    if not cfg.get("national_holidays", True):
        return ""
    return NATIONAL_HOLIDAYS.get((day.month, day.day), "")


def closed_on(cfg: dict, day: date) -> bool:
    """True when the shop is shut all day (closed weekday or a national holiday). Not set -> never."""
    if not cfg.get("set"):
        return False
    return bool(holiday_name(cfg, day)) or day.weekday() not in bsetup.hours_minutes(cfg.get("hours"))


def is_open(cfg: dict, now: datetime | None = None) -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    if not cfg.get("set") or closed_on(cfg, now.date()):
        return False
    t = now.hour * 60 + now.minute
    return any(a <= t < b for a, b in bsetup.hours_minutes(cfg.get("hours")).get(now.weekday(), []))


def next_open(cfg: dict, now: datetime | None = None) -> str:
    """'today at 4 PM' / 'tomorrow (Monday) at 10 AM' / 'Thursday at 10 AM' / '' if never."""
    now = (now or datetime.now(IST)).astimezone(IST)
    per_day = bsetup.hours_minutes(cfg.get("hours"))
    t = now.hour * 60 + now.minute
    for ahead in range(0, 15):
        day = now.date() + timedelta(days=ahead)
        if closed_on(cfg, day):
            continue
        for a, _b in per_day.get(day.weekday(), []):
            if ahead == 0 and a <= t:
                continue
            if ahead == 0:
                return f"today at {_clock(a)}"
            if ahead == 1:
                return f"tomorrow ({DAY_NAMES[day.weekday()]}) at {_clock(a)}"
            return f"{DAY_NAMES[day.weekday()]} {day.day} {day.strftime('%b')} at {_clock(a)}"
    return ""


def status_line(cfg: dict, now: datetime | None = None) -> str:
    """'Open now, until 8 PM' / 'Closed now. Opens today at 4 PM' / 'Closed today (Sunday). Opens …'."""
    now = (now or datetime.now(IST)).astimezone(IST)
    t = now.hour * 60 + now.minute
    if is_open(cfg, now):
        end = next(b for a, b in bsetup.hours_minutes(cfg["hours"])[now.weekday()] if a <= t < b)
        return f"Open now, until {_clock(end)}"
    when = next_open(cfg, now)
    holiday = holiday_name(cfg, now.date())
    if holiday:
        head = f"Closed today ({holiday})"
    elif closed_on(cfg, now.date()):
        head = f"Closed today ({DAY_NAMES[now.weekday()]})"
    else:
        head = "Closed right now"
    return f"{head}. Opens {when}" if when else head


def prompt_block(db, tenant_id: str, now: datetime | None = None) -> str:
    """The AI's facts about when the business is open. "" when not set (the AI then says nothing about hours
    it does not know). Never raises."""
    try:
        cfg = read(db, tenant_id)
        if not cfg.get("set"):
            return ""
        now = (now or datetime.now(IST)).astimezone(IST)
        per_day = bsetup.hours_minutes(cfg["hours"])
        week = "; ".join(
            f"{DAY_NAMES[d]} {_blocks_text(per_day[d])}" if d in per_day else f"{DAY_NAMES[d]} closed"
            for d in range(7)
        )
        holidays = (" Closed on 26 January, 15 August and 2 October." if cfg.get("national_holidays", True) else "")
        return (
            "\n\nOPEN HOURS (India time, set by the business; this is the only source for its hours):\n"
            f"{week}.{holidays}\n"
            f"It is now {now.strftime('%A %d %B, %I:%M %p')}. {status_line(cfg, now)}.\n"
            "If the customer wants to visit, call or come in, or asks if you are open, answer from these hours. "
            "If the shop is closed today or right now, say so plainly and say when it opens next. Never offer a "
            "visit or a time outside these hours. You can still answer questions and take an order in chat "
            "while the shop is closed.\n"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("open_hours: prompt block failed for %s (%s)", tenant_id, type(e).__name__)
        return ""


# ── bookings ────────────────────────────────────────────────────────────────

def limit_hours(resource_hours: dict, cfg: dict) -> dict:
    """A booking column's working hours cut to the shop's open hours (stored-hours shape).
    Shop hours not set -> the column's own hours, unchanged."""
    if not cfg.get("set"):
        return resource_hours or {}
    shop = bsetup.hours_minutes(cfg.get("hours"))
    out: dict[str, list[list[str]]] = {}
    for d, blocks in bsetup.hours_minutes(resource_hours).items():
        kept = []
        for a, b in blocks:
            for sa, sb in shop.get(d, []):
                lo, hi = max(a, sa), min(b, sb)
                if hi > lo:
                    kept.append((lo, hi))
        if kept:
            out[str(d)] = [[f"{a // 60:02d}:{a % 60:02d}", "24:00" if b >= 1440 else f"{b // 60:02d}:{b % 60:02d}"]
                           for a, b in sorted(kept)[:2]]
    return out
