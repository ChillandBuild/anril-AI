"""Per-tenant deal-lifecycle settings (decision D1, .agents/decisions/log.md 2026-09-30).

deal_idle_close_days: how many idle days before the sweep closes an unpaid deal.
Stored in app_settings as a string; every reader goes through here so the bounds and the
default live in one place."""
import math
from typing import Any, Optional

from app.config_dynamic import get_setting, get_setting_strict

DEAL_IDLE_CLOSE_DAYS_KEY = "deal_idle_close_days"
DEAL_IDLE_CLOSE_DAYS_MIN = 2
DEAL_IDLE_CLOSE_DAYS_MAX = 90
DEAL_IDLE_CLOSE_DAYS_DEFAULT = 30


def _parse_whole_days(raw: Any) -> Optional[int]:
    """A whole number of days from an int or a numeric string; None for anything else."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if not isinstance(raw, (str, float)):
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number)


def clamp_deal_idle_close_days(raw: Any) -> int:
    """Tolerant read: missing or unparseable -> 30; out of range -> pulled into 2-90."""
    days = _parse_whole_days(raw)
    if days is None:
        return DEAL_IDLE_CLOSE_DAYS_DEFAULT
    return max(DEAL_IDLE_CLOSE_DAYS_MIN, min(DEAL_IDLE_CLOSE_DAYS_MAX, days))


def validate_deal_idle_close_days(raw: Any) -> int:
    """Strict write check for the operator PATCH: a whole number of days in 2-90, else ValueError."""
    message = f"{DEAL_IDLE_CLOSE_DAYS_KEY} must be a whole number of days between {DEAL_IDLE_CLOSE_DAYS_MIN} and {DEAL_IDLE_CLOSE_DAYS_MAX}"
    if isinstance(raw, bool):
        raise ValueError(message)
    text = str(raw).strip()
    try:
        days = int(text)
    except ValueError:
        raise ValueError(message) from None
    if not DEAL_IDLE_CLOSE_DAYS_MIN <= days <= DEAL_IDLE_CLOSE_DAYS_MAX:
        raise ValueError(message)
    return days


def get_deal_idle_close_days(tenant_id: str) -> int:
    """Idle-close window for one tenant, in days (get_setting's 60s cache applies)."""
    return clamp_deal_idle_close_days(get_setting(DEAL_IDLE_CLOSE_DAYS_KEY, tenant_id=tenant_id))


def read_deal_idle_close_days(tenant_id: str) -> int:
    """Same value as get_deal_idle_close_days, but a failed settings read raises
    config_dynamic.SettingReadError instead of returning the 30-day default. A key that is simply
    unset is still 30. The idle sweep uses this so an outage never closes a 90-day tenant's
    deals early."""
    return clamp_deal_idle_close_days(get_setting_strict(DEAL_IDLE_CLOSE_DAYS_KEY, tenant_id=tenant_id))
