import json
import logging
from datetime import datetime, timezone, timedelta
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _get_recycle_config(tenant_id: str) -> dict:
    db = get_supabase()
    try:
        row = (
            db.table("app_settings")
            .select("value")
            .eq("tenant_id", tenant_id)
            .eq("key", "telecalling_config")
            .maybe_single()
            .execute()
        )
        if row and row.data:
            cfg = json.loads(row.data.get("value") or "{}")
            return {
                "enabled": cfg.get("recycle_enabled", False),
                "delay_hours": cfg.get("recycle_delay_hours", 4),
                "max_retries": cfg.get("recycle_max_retries", 3),
                "start_hour": cfg.get("recycle_start_hour", 9),
                "end_hour": cfg.get("recycle_end_hour", 18),
                "max_call_attempts": cfg.get("max_call_attempts", 4),
            }
    except Exception as e:
        logger.warning(f"Error reading recycle config for tenant {tenant_id}: {e}")
    return {"enabled": False}


def recycle_leads_for_tenant(tenant_id: str) -> int:
    db = get_supabase()
    config = _get_recycle_config(tenant_id)

    if not config.get("enabled"):
        return 0

    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    current_hour = now_ist.hour

    start_hour = config.get("start_hour", 9)
    end_hour = config.get("end_hour", 18)

    if current_hour < start_hour or current_hour >= end_hour:
        return 0

    delay_hours = config.get("delay_hours", 4)
    max_retries = config.get("max_retries", 3)
    max_call_attempts = config.get("max_call_attempts", 4)
    cutoff_time = (now_utc - timedelta(hours=delay_hours)).isoformat()

    leads_query = (
        db.table("leads")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("call_status", "trying")
        .is_("converted_at", "null")
        .is_("deleted_at", "null")
        .neq("do_not_call", True)
        .or_("opted_out.is.null,opted_out.eq.false")  # Said stop: no calls either
        .limit(200)
        .execute()
    )

    leads = leads_query.data or []
    recycled_count = 0

    for lead in leads:
        lead_id = lead["id"]

        last_call = (
            db.table("call_logs")
            .select("outcome, created_at")
            .eq("lead_id", lead_id)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not last_call.data:
            continue

        last_call_data = last_call.data[0]
        last_outcome = last_call_data.get("outcome")
        last_created_at = last_call_data.get("created_at")

        # Tap 2 exists only for connected calls: any outcome means someone already reached this lead.
        if last_outcome is not None:
            continue

        if last_created_at and last_created_at > cutoff_time:
            continue

        total_calls = (
            db.table("call_logs")
            .select("id", count="exact")
            .eq("lead_id", lead_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )

        total_attempts = total_calls.count or 0

        if total_attempts >= max_call_attempts or total_attempts >= max_retries:
            continue

        db.table("leads").update({
            "call_status": "new",
            "assigned_to": None,
        }).eq("id", lead_id).eq("tenant_id", tenant_id).execute()

        recycled_count += 1

    return recycled_count


def recycle_all_tenants() -> int:
    db = get_supabase()

    result = (
        db.table("app_settings")
        .select("tenant_id")
        .eq("key", "telecalling_config")
        .execute()
    )

    tenant_ids = list(set([row["tenant_id"] for row in (result.data or [])]))

    total_recycled = 0
    for tenant_id in tenant_ids:
        try:
            count = recycle_leads_for_tenant(tenant_id)
            total_recycled += count
        except Exception as e:
            logger.error(f"Error recycling leads for tenant {tenant_id}: {e}")

    return total_recycled
