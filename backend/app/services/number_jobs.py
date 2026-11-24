"""Which number sends three jobs, as picked in WhatsApp > Numbers > "Which number does what".

Only three jobs can be pinned to a number: staff alerts, OTP codes and Reach campaigns. Everything
else follows the default rule (a reply goes from the number the customer wrote to; the rest from
Main). With nothing picked, a job is "Automatic":
  alerts, otp -> the default sender (Main, meta_phone_number_id)
  reach       -> Main first, then Standby numbers with room (outbound_router.SenderPicker)

A pick is stored as app_settings `sender_for_<job>` = phone_numbers.id, always read back against
this tenant's own rows, so it can never send from another business's number. A pick that stops
being usable falls back to Automatic instead of failing the send:
  alerts, otp -> the number is gone or no longer connected to Meta
  reach       -> the number may not broadcast right now (red, paused, not connected, locked, no
                 limit from Meta). A number that only ran out of today's cap stays picked: the rest
                 of the broadcast waits for it, the same as the daily-limit wait.
"""
import logging
from datetime import datetime

from app.config_dynamic import get_setting
from app.services.number_health import broadcast_cap, can_broadcast, is_meta_connected

logger = logging.getLogger(__name__)

SENDER_JOBS = ("alerts", "otp", "reach")


def setting_key(job: str) -> str:
    return f"sender_for_{job}"


def picked_number_id(tenant_id: str, job: str) -> str | None:
    return get_setting(setting_key(job), tenant_id=tenant_id) or None


def picked_row(db, tenant_id: str, job: str) -> dict | None:
    """The number picked for this job, if it is still one of this business's live numbers."""
    number_id = picked_number_id(tenant_id, job)
    if not number_id:
        return None
    rows = (
        db.table("phone_numbers").select("*")
        .eq("tenant_id", tenant_id).eq("id", number_id).neq("status", "archived")
        .limit(1).execute().data or []
    )
    return rows[0] if rows else None


def send_block_reason(row: dict) -> str | None:
    """Why a number can't send alerts or OTP codes; None when it can."""
    if row.get("status") == "archived":
        return "Removed"
    if not is_meta_connected(row) or not row.get("meta_phone_number_id"):
        return "Not connected to Meta"
    return None


def reach_block_reason(row: dict, now: datetime, unlocked_ids: set[str], used_today: int) -> str | None:
    """Why a number can't be picked for Reach right now; None when it can.
    Same rules as the campaign sender (number_health.can_broadcast), in plain words."""
    if row.get("status") == "archived":
        return "Removed"
    if not is_meta_connected(row):
        return "Not connected to Meta"
    if row["id"] not in unlocked_ids:
        return "Locked by your plan"
    if row.get("quality_rating") == "red":
        return "Rated red by Meta"
    if row.get("paused_outbound"):
        return "Paused"
    if row.get("status") not in ("active", "warming"):
        return "Resting after a red rating"
    cap = broadcast_cap(row, now)
    if cap is None:
        return "No daily limit from Meta yet"
    if used_today >= cap:
        return "Today's cap used"
    return None


def sender_for(db, tenant_id: str, job: str) -> str | None:
    """Meta phone_number_id to send `job` (alerts / otp) from; None = the default sender (Main).
    Never raises: a send must not fail because the pick couldn't be read."""
    try:
        row = picked_row(db, tenant_id, job)
    except Exception as e:
        logger.warning(f"sender_for({job}) unavailable for tenant {tenant_id}: {e}")
        return None
    if row and not send_block_reason(row):
        return row["meta_phone_number_id"]
    return None


def reach_pin(db, tenant_id: str, rows: list[dict], now: datetime, unlocked_ids: set[str]) -> dict | None:
    """The number Reach must use, or None for Automatic. Kept while the number may broadcast at
    all (its cap running out only makes the rest wait); dropped when it is red, paused, etc."""
    try:
        number_id = picked_number_id(tenant_id, "reach")
    except Exception as e:
        logger.warning(f"reach pick unavailable for tenant {tenant_id}: {e}")
        return None
    row = next((r for r in rows if number_id and r["id"] == number_id), None)
    if row and can_broadcast(row, now, unlocked_ids):
        return row
    return None
