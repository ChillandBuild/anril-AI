import logging
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services.meta_cloud import get_number_health
from app.services.number_health import health, is_meta_connected, portfolio_limit
from app.services.outbound_router import Usage, load_usage
from app.services.number_sync import sync_one_number, sync_tenant_numbers
from app.services.numbers_pool import get_unlocked_number_ids, numbers_pool_limit

logger = logging.getLogger(__name__)
require_numbers_read = require_permission("numbers.view")
require_numbers_manage = require_permission("numbers.manage")

router = APIRouter(dependencies=[Depends(require_numbers_read)])


class CreatePhoneNumber(BaseModel):
    provider: str = "meta_cloud"
    number: str
    display_name: str
    meta_phone_number_id: str | None = None


class UpdatePhoneNumber(BaseModel):
    # No display_name: Meta owns it (`verified_name`), and both sync paths
    # overwrite the row, so a rename here would silently revert. Changing the
    # name customers see is a Meta review flow -- see subsystem-notes.md.
    role: str | None = None
    status: str | None = None
    paused_outbound: bool | None = None
    warm_up_day: int | None = None


_numbers_pool_limit = numbers_pool_limit

# Must match phone_numbers_status_check in supabase/migrations/009_phone_numbers_incidents.sql
_VALID_PHONE_NUMBER_STATUSES = frozenset({"active", "warming", "restricted", "archived"})
# Roles a person can pick (migration 346). Extra: replies to whoever writes, but no campaigns and
# never takes over from Main. "archived" is set by the system only.
_PICKABLE_ROLES = frozenset({"primary", "standby", "extra"})


@router.get("/")
async def list_phone_numbers(tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    result = (
        db.table("phone_numbers")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("role")
        .order("quality_rating")
        .execute()
    )
    return _pool_response(db, tenant_id, result.data or [])


def _usage_or_empty(db, tenant_id: str) -> Usage:
    try:
        return load_usage(db, tenant_id)
    except Exception as e:
        logger.warning(f"messaging limit usage unavailable for tenant {tenant_id}: {e}")
        return Usage()


def _health(row: dict, now: datetime, usage: Usage) -> dict:
    # sent_24h: Meta's measure -- people sent to outside their 24h window, last 24 hours.
    return {**health(row, now), "sent_24h": usage.per_number.get(row["id"], 0)}


def _pool_response(db, tenant_id: str, rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    unlocked_ids = get_unlocked_number_ids(db, tenant_id)
    usage = _usage_or_empty(db, tenant_id)
    data = [
        {
            **row,
            "locked": row.get("status") != "archived" and row["id"] not in unlocked_ids,
            "health": _health(row, now, usage),
        }
        for row in rows
    ]
    active_rows = [r for r in rows if r.get("status") != "archived"]
    return {
        "jobs": _jobs(db, tenant_id, active_rows),
        "data": data,
        "numbers_pool": {
            "limit": numbers_pool_limit(db, tenant_id),
            "used": len(active_rows),
            # Meta's one limit for the whole business, and how much of it the last 24h used.
            "meta_limit": portfolio_limit(active_rows),
            "meta_sent_24h": usage.total,
        },
    }


def _jobs(db, tenant_id: str, rows: list[dict]) -> dict:
    """Which number does what today, as the senders actually work (read only):
    replies go from the number the customer wrote to; Reach uses Main first, then Standby numbers
    with room (never Extra); OTP, bills, order updates and alerts use the default sender."""
    try:
        got = (db.table("app_settings").select("value").eq("tenant_id", tenant_id)
               .eq("key", "meta_phone_number_id").limit(1).execute().data or [])
        default_meta = got[0].get("value") if got else None
    except Exception:
        default_meta = None
    default_row = next((r for r in rows if default_meta and r.get("meta_phone_number_id") == default_meta), None)
    main = next((r for r in rows if r.get("role") == "primary"), None)
    return {
        "default_sender_id": default_row["id"] if default_row else None,
        "main_id": main["id"] if main else None,
        "reach_ids": [r["id"] for r in rows if r.get("role") in ("primary", "standby") and not r.get("paused_outbound")],
    }


@router.post("/")
async def create_phone_number(
    payload: CreatePhoneNumber,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_numbers_manage),
):
    if payload.provider != "meta_cloud":
        raise HTTPException(status_code=400, detail="Only meta_cloud provider is supported")
    db = get_supabase()

    number_limit = _numbers_pool_limit(db, tenant_id)
    current = db.table("phone_numbers").select("id", count="exact").eq("tenant_id", tenant_id).execute().count or 0
    if current >= number_limit:
        raise HTTPException(
            status_code=400,
            detail=f"Phone number limit reached ({current}/{number_limit}). Request more numbers from Subscriptions.",
        )

    insert_data = {
        "provider": payload.provider,
        "number": payload.number.strip(),
        "display_name": payload.display_name.strip(),
        "role": "standby",
        "status": "warming",
        "warm_up_day": 0,
        "paused_outbound": False,
        "tenant_id": tenant_id,
    }
    if payload.meta_phone_number_id is not None:
        insert_data["meta_phone_number_id"] = payload.meta_phone_number_id
    result = db.table("phone_numbers").insert(insert_data).execute()
    return result.data[0]


@router.post("/sync-from-meta")
async def sync_all_numbers_from_meta(
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_numbers_manage),
):
    """Pull every number registered on the tenant's Meta WABA into
    phone_numbers -- regardless of numbers_pool quota. Numbers beyond quota
    land locked (role=standby, never auto-primary), not rejected."""
    db = get_supabase()
    try:
        synced, failed = await sync_tenant_numbers(db, tenant_id, source="manual_sync")
    except ValueError:
        raise HTTPException(status_code=400, detail="Connect Meta WhatsApp (meta_waba_id) in Settings first")

    rows = (
        db.table("phone_numbers")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("role")
        .order("quality_rating")
        .execute()
        .data
        or []
    )
    return {**_pool_response(db, tenant_id, rows), "synced": synced, "failed": failed}


@router.patch("/{number_id}")
async def update_phone_number(
    number_id: UUID,
    payload: UpdatePhoneNumber,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_numbers_manage),
):
    if payload.role is not None and payload.role not in _PICKABLE_ROLES:
        raise HTTPException(status_code=400, detail="A number can be Main, Standby or Extra.")
    if payload.status is not None and payload.status not in _VALID_PHONE_NUMBER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{payload.status}'. Must be one of: {', '.join(sorted(_VALID_PHONE_NUMBER_STATUSES))}.",
        )

    db = get_supabase()
    if payload.role in ("standby", "extra"):
        current = (db.table("phone_numbers").select("role").eq("id", str(number_id)).eq("tenant_id", tenant_id)
                   .limit(1).execute().data or [])
        if current and current[0].get("role") == "primary":
            raise HTTPException(status_code=400, detail="This is your Main number. Make another number Main first.")
    updates = {}
    if payload.role is not None:
        updates["role"] = payload.role
    if payload.status is not None:
        updates["status"] = payload.status
    if payload.paused_outbound is not None:
        updates["paused_outbound"] = payload.paused_outbound
    if payload.warm_up_day is not None:
        updates["warm_up_day"] = payload.warm_up_day
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Setting role="primary" is always allowed -- it's the unlock mechanism
    # itself (the primary slot is always guaranteed). Any other attempt to
    # activate a currently-locked number (flip to active, or resume outbound)
    # is blocked until the client either sets it primary or upgrades.
    attempting_activation = payload.status == "active" or payload.paused_outbound is False
    if attempting_activation and payload.role != "primary":
        unlocked_ids = get_unlocked_number_ids(db, tenant_id)
        if str(number_id) not in unlocked_ids:
            raise HTTPException(
                status_code=400,
                detail="This number is locked by your numbers pool quota. Set it as primary or upgrade in Subscriptions to activate it.",
            )

    if payload.role == "primary":
        target = db.table("phone_numbers").select("meta_status,meta_phone_number_id").eq("id", str(number_id)).eq("tenant_id", tenant_id).limit(1).execute().data
        if target and not is_meta_connected(target[0]):
            raise HTTPException(
                status_code=400,
                detail="Meta hasn't verified this number yet. Finish verification in WhatsApp Manager, then Sync.",
            )
        # Ensure exclusive primary logic: demote all other primary numbers to standby
        db.table("phone_numbers").update({"role": "standby"}).eq("tenant_id", tenant_id).eq("role", "primary").execute()
        
    result = db.table("phone_numbers").update(updates).eq("id", str(number_id)).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Phone number not found")
    if payload.role == "primary" and target:
        # Make main by hand moves the default sender too, the same as an automatic takeover does.
        from app.services.failover import set_default_sender
        set_default_sender(db, tenant_id, target[0].get("meta_phone_number_id"))
    return result.data[0]


@router.post("/{number_id}/sync-meta")
async def sync_number_from_meta(
    number_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_numbers_manage),
):
    db = get_supabase()
    row_result = (
        db.table("phone_numbers")
        .select("*")
        .eq("id", str(number_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Phone number not found")
    row = row_result.data[0]

    meta_pid = row.get("meta_phone_number_id")
    if not meta_pid:
        raise HTTPException(status_code=400, detail="No Meta phone number ID set for this number")

    merged = await sync_one_number(db, row, source="manual_sync")
    return {**merged, "health": _health(merged, datetime.now(timezone.utc), _usage_or_empty(db, tenant_id))}


@router.get("/{number_id}/meta-health")
async def get_number_meta_health(
    number_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
):
    """Meta's live explanation for a number's quality (reasons, sending state,
    notes). Read-only -- nothing is written."""
    db = get_supabase()
    row_result = (
        db.table("phone_numbers")
        .select("meta_phone_number_id")
        .eq("id", str(number_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=404, detail="Phone number not found")
    meta_pid = row_result.data[0].get("meta_phone_number_id")
    if not meta_pid:
        raise HTTPException(status_code=400, detail="No Meta phone number ID set for this number")
    return await get_number_health(phone_number_id=meta_pid, tenant_id=tenant_id)


@router.delete("/{number_id}")
async def delete_phone_number(
    number_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_numbers_manage),
):
    """Hard delete a phone number. FK on incidents.phone_number_id is ON
    DELETE SET NULL so historical incidents stay intact, just lose the ref."""
    db = get_supabase()
    active_result = (
        db.table("phone_numbers")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("status", "active")
        .execute()
    )
    active_ids = [row["id"] for row in (active_result.data or [])]
    if len(active_ids) == 1 and active_ids[0] == str(number_id):
        raise HTTPException(status_code=400, detail="Cannot delete last active number")
    result = (
        db.table("phone_numbers")
        .delete()
        .eq("id", str(number_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Phone number not found")
    return {"deleted": True}
