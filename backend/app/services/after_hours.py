"""v9.2 #157 After-hours message: what the AI tells a customer who is waiting for a person when nobody is in.

One small setting (app_settings key after_hours_config, JSON): on or off, when the team is in (open and close
times, India time) and the message. It only changes what the AI says to a customer who has been handed to a
person (the existing escalation prompt); it sends nothing by itself, so opt-outs and the 24 hour window
keep working exactly as before."""
import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
KEY = "after_hours_config"
MAX_MESSAGE = 300
DEFAULT = {"enabled": False, "open": "09:00", "close": "21:00", "message": ""}
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class AfterHoursError(Exception):
    status = 422


def clean(raw: object) -> dict:
    """Only known keys with sane values; anything odd falls back to the default for that key."""
    src = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT)
    out["enabled"] = src.get("enabled") is True
    for k in ("open", "close"):
        v = src.get(k)
        if isinstance(v, str) and _TIME.match(v):
            out[k] = v
    msg = src.get("message")
    out["message"] = re.sub(r"\s+", " ", msg).strip()[:MAX_MESSAGE] if isinstance(msg, str) else ""
    return out


def validate(raw: dict) -> dict:
    for k in ("open", "close"):
        if not isinstance(raw.get(k), str) or not _TIME.match(raw[k]):
            raise AfterHoursError("Choose the times as hours and minutes, like 09:00.")
    msg = re.sub(r"\s+", " ", raw.get("message") or "").strip()
    if len(msg) > MAX_MESSAGE:
        raise AfterHoursError(f"Keep the message under {MAX_MESSAGE} characters.")
    cfg = clean({**raw, "message": msg, "enabled": raw.get("enabled") is True})
    if cfg["enabled"] and not cfg["message"]:
        raise AfterHoursError("Write the message first, then switch it on.")
    return cfg


def read(db, tenant_id: str) -> dict:
    try:
        row = (db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", KEY)
               .maybe_single().execute())
        if row and isinstance(row.data, dict) and row.data.get("value"):
            return clean(json.loads(row.data["value"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("after_hours: could not read the setting for %s (%s)", tenant_id, type(e).__name__)
    return dict(DEFAULT)


def save(db, tenant_id: str, raw: dict) -> dict:
    cfg = validate(raw)
    db.table("app_settings").upsert(
        {"tenant_id": tenant_id, "key": KEY, "value": json.dumps(cfg), "is_secret": False}, on_conflict="key,tenant_id",
    ).execute()
    try:
        from app.config_dynamic import invalidate_cache
        invalidate_cache(KEY)
    except Exception:  # noqa: BLE001
        pass
    return cfg


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def is_after_hours(cfg: dict, now: datetime | None = None) -> bool:
    """True when the team is out. open == close means always in. Handles a night shift (open 18:00, close 02:00)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    o, c, t = _minutes(cfg["open"]), _minutes(cfg["close"]), now.hour * 60 + now.minute
    if o == c:
        return False
    inside = (o <= t < c) if o < c else (t >= o or t < c)
    return not inside


def prompt_line(db, tenant_id: str, now: datetime | None = None) -> str:
    """Added to the escalation prompt. "" when the setting is off, the team is in, or nothing could be read."""
    cfg = read(db, tenant_id)
    if not (cfg["enabled"] and cfg["message"]) or not is_after_hours(cfg, now):
        return ""
    return (
        f"AFTER HOURS: the team is out right now and is back at {cfg['open']} (India time). Tell the customer "
        f"this once, in their language, using the owner's message as the base: \"{cfg['message']}\". "
        "Do not promise a call or a time.\n"
    )
