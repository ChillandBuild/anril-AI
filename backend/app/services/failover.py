"""Primary-number failover. Rules live in number_health; this module writes.

When a number turns Red it starts resting: status=restricted, rested_since=now.
It keeps answering chats (replies go out from the number the customer
messaged) but sends no broadcasts. If it was primary, the best standby that
Meta reports CONNECTED takes over -- even mid warm-up, with its broadcasts
capped. With no such standby, broadcasts pause until one is added or the Red
number recovers (7 days rested + Green, see number_health.recovered).
"""
import logging
from datetime import datetime, timezone

from app.db.supabase import get_supabase
from app.services.number_health import is_resting, map_quality, standby_candidates
from app.services.numbers_pool import get_unlocked_number_ids

logger = logging.getLogger(__name__)



def set_default_sender(db, tenant_id: str, meta_phone_number_id: str | None) -> None:
    """The Main number is the default sender: OTP codes, bills, order updates and alerts (any send
    that names no number). Replies still go from the number the customer wrote to."""
    if not meta_phone_number_id:
        return
    db.table("app_settings").upsert(
        {"key": "meta_phone_number_id", "value": meta_phone_number_id, "tenant_id": tenant_id, "is_secret": False},
        on_conflict="tenant_id,key",
    ).execute()
    from app.config_dynamic import invalidate_cache
    invalidate_cache("meta_phone_number_id")

def _insert_incident(db, payload: dict) -> None:
    try:
        db.table("incidents").insert(payload).execute()
    except Exception as e:
        logger.warning(f"failover: incident insert failed ({payload.get('type')}): {e}")


async def handle_quality_red(phone_number_id: str, source: str = "meta_webhook") -> None:
    db = get_supabase()

    old_row = db.table("phone_numbers").select("*").eq("id", phone_number_id).limit(1).execute()
    if not old_row.data:
        logger.warning(f"handle_quality_red: no phone_number row found for id={phone_number_id}")
        return

    row = old_row.data[0]
    tenant_id = row.get("tenant_id")
    if not tenant_id:
        logger.warning(f"handle_quality_red: missing tenant_id for phone_number id={phone_number_id}")
        return

    if not is_resting(row):
        db.table("phone_numbers").update({
            "status": "restricted",
            "rested_since": datetime.now(timezone.utc).isoformat(),
            "quality_rating": "red",
        }).eq("id", phone_number_id).eq("tenant_id", tenant_id).execute()
        logger.info(f"handle_quality_red: number id={phone_number_id} is resting")
        _insert_incident(db, {
            "type": "quality_red",
            "tenant_id": tenant_id,
            "phone_number_id": phone_number_id,
            "detail": {"number": row.get("number"), "source": source},
        })

    if row.get("role") == "primary":
        promoted = await ensure_healthy_primary(tenant_id)
        if promoted is None:
            _insert_incident(db, {
                "type": "quality_red",
                "tenant_id": tenant_id,
                "phone_number_id": phone_number_id,
                "detail": {"message": "no_standby_available", "source": source},
            })


async def ensure_healthy_primary(tenant_id: str) -> dict | None:
    """If the primary is resting (Red), hand primary to the best standby.
    Returns the promoted row, or None when no switch happened. Safe to call
    repeatedly -- the syncs call it so a standby that becomes ready later
    still takes over."""
    db = get_supabase()
    rows = (
        db.table("phone_numbers")
        .select("*")
        .eq("tenant_id", tenant_id)
        .neq("status", "archived")
        .execute()
        .data
        or []
    )
    primary = next((r for r in rows if r.get("role") == "primary"), None)
    if primary is None or not is_resting(primary):
        return None

    candidates = standby_candidates(rows, primary["id"], get_unlocked_number_ids(db, tenant_id))
    if not candidates:
        logger.warning(f"ensure_healthy_primary: no standby ready for tenant {tenant_id}")
        return None

    new_number = candidates[0]
    db.table("phone_numbers").update({"role": "standby"}).eq("id", primary["id"]).eq("tenant_id", tenant_id).execute()
    db.table("phone_numbers").update({"role": "primary"}).eq("id", new_number["id"]).eq("tenant_id", tenant_id).execute()
    logger.info(f"ensure_healthy_primary: {new_number['id']} took over from {primary['id']} (tenant {tenant_id})")

    # The tenant-wide default sender (used when a send names no number).
    set_default_sender(db, tenant_id, new_number.get("meta_phone_number_id"))

    detail = {"old_number_id": primary["id"], "new_number_id": new_number["id"]}
    _insert_incident(db, {"type": "failover", "tenant_id": tenant_id, "phone_number_id": primary["id"], "detail": detail})
    _insert_incident(db, {"type": "standby_promoted", "tenant_id": tenant_id, "phone_number_id": new_number["id"], "detail": detail})
    return {**new_number, "role": "primary"}


async def handle_quality_yellow(phone_number_id: str) -> None:
    db = get_supabase()

    existing = db.table("phone_numbers").select("tenant_id").eq("id", phone_number_id).limit(1).execute()
    tenant_id = (existing.data or [{}])[0].get("tenant_id")

    db.table("phone_numbers").update({"quality_rating": "yellow"}).eq("id", phone_number_id).execute()
    logger.info(f"handle_quality_yellow: marked number id={phone_number_id} as yellow")

    incident_payload = {
        "type": "quality_yellow",
        "phone_number_id": phone_number_id,
        "detail": {},
    }
    if tenant_id:
        incident_payload["tenant_id"] = tenant_id
    _insert_incident(db, incident_payload)


def set_portfolio_limit(tenant_id: str, tier: int) -> None:
    """Meta's limit belongs to the business portfolio, so a new one applies to
    every number the tenant has."""
    db = get_supabase()
    db.table("phone_numbers").update({"messaging_tier": tier}).eq("tenant_id", tenant_id).neq("status", "archived").execute()
    logger.info(f"set_portfolio_limit: tenant {tenant_id} -> {tier}")


async def update_number_quality(
    meta_phone_number_id: str,
    quality_rating: str,
    messaging_tier: int | None = None,
) -> str | None:
    db = get_supabase()

    existing = (
        db.table("phone_numbers")
        .select("id")
        .eq("meta_phone_number_id", meta_phone_number_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        logger.warning(f"update_number_quality: no row for meta_phone_number_id={meta_phone_number_id}")
        return None

    row_id = existing.data[0]["id"]
    updates: dict = {}
    # A webhook without a rating (a limit-only change) leaves the stored rating
    # alone; UNKNOWN (no rating yet) is stored as NULL, never guessed.
    if quality_rating:
        updates["quality_rating"] = map_quality(quality_rating)
    if messaging_tier is not None:
        updates["messaging_tier"] = messaging_tier

    if updates:
        db.table("phone_numbers").update(updates).eq("id", row_id).execute()
    logger.info(f"update_number_quality: id={row_id} quality={quality_rating} tier={messaging_tier}")
    return row_id

