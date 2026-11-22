"""A read-only picture of how a tenant's team calls: SIM or cloud, who is ready, and the team
rules. Nothing here changes a setting; the rules are edited in Call IQ > Team."""
import logging
from datetime import datetime, timedelta, timezone

from app.services.assignment import get_telecalling_config

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_DAILY_TARGET = 50  # same default callers.py uses for a caller with no target of their own
DEFAULT_SHIFT_START = 9
DEFAULT_SHIFT_END = 19
INDIVIDUAL_HOURS_TEXT = "Each person has their own hours"


def provider_name(config: dict) -> str:
    """telecmi (the default) -> "cloud", sim_basic -> "sim"."""
    return "sim" if (config or {}).get("calling_provider", "telecmi") == "sim_basic" else "cloud"


def hour_text(hour: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12} {suffix}"


def _hour(value, default: int) -> int:
    """A stored hour, or the default when it is null, missing or not a number (0 is a real hour)."""
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return default
    return hour if 0 <= hour <= 23 else default


def calling_hours(config: dict) -> str:
    config = config or {}
    if config.get("shift_mode", "common") == "individual":
        return INDIVIDUAL_HOURS_TEXT
    start = _hour(config.get("shift_start_hour"), DEFAULT_SHIFT_START)
    end = _hour(config.get("shift_end_hour"), DEFAULT_SHIFT_END)
    return f"{hour_text(start)} to {hour_text(end)}"


def daily_target(config: dict) -> int:
    targets = (config or {}).get("targets")
    if not isinstance(targets, dict):
        targets = {}
    try:
        return int(targets.get("daily_calls", DEFAULT_DAILY_TARGET))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_TARGET


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def last_seen_text(value, now: datetime | None = None) -> str | None:
    """"10:02 AM" for today (IST), "12 Nov, 10:02 AM" for an earlier day."""
    seen = _parse(value)
    if seen is None:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    seen = seen.astimezone(_IST)
    today = (now or datetime.now(timezone.utc)).astimezone(_IST).date()
    clock = f"{seen.hour % 12 or 12}:{seen.minute:02d} {'AM' if seen.hour < 12 else 'PM'}"
    return clock if seen.date() == today else f"{seen.day} {seen.strftime('%b')}, {clock}"


def person_status(caller: dict, provider: str, now: datetime | None = None) -> dict:
    name = (caller.get("name") or "").strip() or "Unnamed"
    if provider == "sim":
        version, seen = caller.get("app_version"), last_seen_text(caller.get("last_sync_at"), now)
        if version is None and not caller.get("last_sync_at"):
            return {"name": name, "ready": False, "detail": "Phone app not connected yet"}
        parts = ["Phone app connected"]
        if version is not None:
            parts.append(f"app version {version}")
        if seen:
            parts.append(f"last seen {seen}")
        return {"name": name, "ready": True, "detail": " · ".join(parts)}
    if (caller.get("telecmi_agent_id") or "").strip():
        return {"name": name, "ready": True, "detail": "Cloud login set"}
    return {"name": name, "ready": False, "detail": "Cloud login not set"}


def overview(db, tenant_id: str, now: datetime | None = None) -> dict:
    """provider, the active callers with ready/not ready, and the team rules."""
    available = True
    try:
        config = get_telecalling_config(tenant_id, db=db)
    except Exception:
        # Without the setting we can't tell SIM from cloud, so say so rather than guess "cloud".
        logger.warning("calling_overview: could not read calling settings for tenant %s", tenant_id, exc_info=True)
        config, available = {}, False
    provider = provider_name(config)

    try:
        callers = (
            db.table("callers")
            .select("id, name, app_version, last_sync_at, telecmi_agent_id")
            .eq("tenant_id", tenant_id).eq("active", True).execute()
        ).data or []
    except Exception:
        logger.warning("calling_overview: could not read callers for tenant %s", tenant_id, exc_info=True)
        callers, available = [], False

    people = [person_status(c, provider, now) for c in sorted(callers, key=lambda c: (c.get("name") or "").lower())]
    return {
        "available": available,
        "provider": provider,
        "people": people,
        "rules": {
            "daily_target_calls": daily_target(config),
            "calling_hours": calling_hours(config),
        },
    }
