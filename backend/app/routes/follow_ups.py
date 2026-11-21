import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, get_tenant_and_role, require_owner
from app.dependencies.auth import get_current_user
from app.services.ai_reply import generate_reengagement_message, send_whatsapp
from app.services.growth import build_follow_up_summary, utcnow


class CallbackCreate(BaseModel):
    lead_id: str
    scheduled_for: str
    note: str | None = None


class CallbackReschedule(BaseModel):
    scheduled_for: str


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/summary")
async def summary(tenant_id: str = Depends(get_tenant_id)):
    return build_follow_up_summary(tenant_id)


@router.post("/run")
async def run_due_follow_ups(limit: int = Query(20, ge=1, le=100), ctx: dict = Depends(require_owner)):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    # ai_auto_reply_enabled is the master switch for every automated AI-authored outbound
    # message, not just inbound replies -- leave due jobs untouched (still "pending") so
    # they resume automatically once the client re-enables, rather than marking them
    # skipped/consumed.
    if get_setting("ai_auto_reply_enabled", fallback="true", tenant_id=tenant_id) == "false":
        return {
            "processed": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "summary": build_follow_up_summary(tenant_id, db=db),
        }

    now = utcnow().isoformat()
    jobs = (
        db.table("follow_up_jobs")
        .select("*")
        .eq("status", "pending")
        .neq("cadence", "callback")
        .eq("tenant_id", tenant_id)
        .lte("scheduled_for", now)
        .order("scheduled_for")
        .limit(limit)
        .execute()
        .data
        or []
    )

    processed = 0
    sent = 0
    failed = 0
    skipped = 0

    for job in jobs:
        processed += 1
        lead = (
            db.table("leads")
            .select("id,name,phone,segment,converted_at,ai_enabled,blocked_at")
            .eq("id", job["lead_id"])
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        lead_data = (lead and lead.data) or {}
        if (
            not lead_data
            or lead_data.get("converted_at")
            or not lead_data.get("ai_enabled", True)
            or not lead_data.get("phone")
            or lead_data.get("blocked_at")  # full block: a blocked person gets no follow-up
            or (lead_data.get("segment") or "D") not in {"A", "B"}
        ):
            db.table("follow_up_jobs").update(
                {
                    "status": "skipped",
                    "skip_reason": "Lead no longer eligible for automated re-engagement.",
                }
            ).eq("id", job["id"]).execute()
            skipped += 1
            continue

        try:
            message = await generate_reengagement_message(job["lead_id"], job["cadence"])
            sid = await send_whatsapp(lead_data["phone"], message, tenant_id=tenant_id)
            if not sid:
                raise RuntimeError("Channel send failed")
            db.table("messages").insert(
                {
                    "lead_id": job["lead_id"],
                    "tenant_id": tenant_id,
                    "direction": "outbound",
                    "channel": "whatsapp",
                    "content": message,
                    "is_ai_generated": True,
                    "meta_message_id": sid,
                }
            ).execute()
            db.table("follow_up_jobs").update(
                {
                    "status": "sent",
                    "sent_at": utcnow().isoformat(),
                    "message_preview": message,
                    "last_error": None,
                    "skip_reason": None,
                }
            ).eq("id", job["id"]).execute()
            sent += 1
        except Exception as exc:
            logger.error("Follow-up job %s failed: %s", job["id"], exc)
            db.table("follow_up_jobs").update(
                {
                    "status": "failed",
                    "last_error": str(exc),
                }
            ).eq("id", job["id"]).execute()
            failed += 1

    return {
        "processed": processed,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "summary": build_follow_up_summary(tenant_id, db=db),
    }


@router.post("/callback")
async def create_callback(payload: CallbackCreate, ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()
    row = db.table("follow_up_jobs").insert({
        "lead_id": payload.lead_id,
        "channel": "phone",
        "cadence": "callback",
        "status": "pending",
        "scheduled_for": payload.scheduled_for,
        "message_preview": payload.note,
        "scheduled_by_caller_id": ctx.get("caller_id"),
        "tenant_id": ctx["tenant_id"],
    }).execute()
    db.table("leads").update({"call_status": "callback"}).eq("id", payload.lead_id).eq("tenant_id", ctx["tenant_id"]).execute()
    return row.data[0] if row.data else {}


@router.get("/callbacks/today")
async def today_callbacks(tenant_id: str = Depends(get_tenant_id), current_user: dict = Depends(get_current_user)):
    db = get_supabase()
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    is_owner = False
    tenant_user = db.table("tenant_users").select("role").eq("user_id", current_user["user_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
    if tenant_user and tenant_user.data and tenant_user.data.get("role") == "owner":
        is_owner = True

    caller_id = None
    if not is_owner:
        caller = db.table("callers").select("id").eq("user_id", current_user["user_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        if caller and caller.data:
            caller_id = caller.data["id"]

    jobs = db.table("follow_up_jobs").select(
        "id,lead_id,scheduled_for,message_preview,status"
    ).eq("tenant_id", tenant_id).eq("cadence", "callback").eq("status", "pending").gte(
        "scheduled_for", day_start
    ).lte("scheduled_for", day_end).order("scheduled_for").execute()

    result = []
    for job in (jobs.data or []):
        lead = db.table("leads").select("id,name,phone,segment,assigned_to").eq(
            "id", job["lead_id"]
        ).eq("tenant_id", tenant_id).maybe_single().execute()
        lead_data = (lead and lead.data) or {}
        
        if not is_owner and lead_data.get("assigned_to") != caller_id:
            continue
            
        result.append({**job, "lead": lead_data})

    return {"data": result}


@router.get("/callbacks/all")
async def all_callbacks(tenant_id: str = Depends(get_tenant_id), current_user: dict = Depends(get_current_user)):
    """Return all pending callback jobs for the tenant, grouped for the scheduled calls page."""
    db = get_supabase()

    is_owner = False
    tenant_user = db.table("tenant_users").select("role").eq("user_id", current_user["user_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
    if tenant_user and tenant_user.data and tenant_user.data.get("role") == "owner":
        is_owner = True

    caller_id = None
    if not is_owner:
        caller = db.table("callers").select("id").eq("user_id", current_user["user_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        if caller and caller.data:
            caller_id = caller.data["id"]

    jobs = (
        db.table("follow_up_jobs")
        .select("id,lead_id,scheduled_for,message_preview,status")
        .eq("tenant_id", tenant_id)
        .eq("cadence", "callback")
        .eq("status", "pending")
        .order("scheduled_for")
        .limit(100)
        .execute()
    )

    result = []
    for job in (jobs.data or []):
        lead = (
            db.table("leads")
            .select("id,name,phone,segment,assigned_to")
            .eq("id", job["lead_id"])
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        lead_data = (lead and lead.data) or {}
        
        if not is_owner and lead_data.get("assigned_to") != caller_id:
            continue
            
        result.append({**job, "lead": lead_data})

    return {"data": result}


@router.get("/callbacks/board")
async def callbacks_board(ctx: dict = Depends(get_tenant_and_role)):
    """Return all pending callback jobs for the tenant, visible to both callers and owners."""
    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    jobs = (
        db.table("follow_up_jobs")
        .select("id,lead_id,scheduled_for,message_preview,status,scheduled_by_caller_id")
        .eq("tenant_id", tenant_id)
        .eq("cadence", "callback")
        .eq("status", "pending")
        .order("scheduled_for")
        .limit(100)
        .execute()
    )

    job_rows = jobs.data or []
    lead_ids = list({job["lead_id"] for job in job_rows})

    leads_by_id: dict = {}
    if lead_ids:
        leads_res = (
            db.table("leads")
            .select("id,name,phone,segment,assigned_to,score")
            .in_("id", lead_ids)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        leads_by_id = {row["id"]: row for row in (leads_res.data or [])}

    # Resolve both the assigned caller (for status) and the scheduling caller
    # (for "Scheduled by <name>") — they can be different people.
    caller_ids = list(
        {lead["assigned_to"] for lead in leads_by_id.values() if lead.get("assigned_to")}
        | {job["scheduled_by_caller_id"] for job in job_rows if job.get("scheduled_by_caller_id")}
    )

    callers_by_id: dict = {}
    if caller_ids:
        callers_res = (
            db.table("callers")
            .select("id,name,status")
            .in_("id", caller_ids)
            .execute()
        )
        callers_by_id = {row["id"]: row for row in (callers_res.data or [])}

    on_call_ids: set = set()
    if caller_ids:
        on_call_res = (
            db.table("call_logs")
            .select("caller_id")
            .eq("tenant_id", tenant_id)
            .in_("caller_id", caller_ids)
            .in_("status", ["initiated", "in_progress"])
            .execute()
        )
        on_call_ids = {row["caller_id"] for row in (on_call_res.data or [])}

    result = []
    for job in job_rows:
        lead_data = leads_by_id.get(job["lead_id"])
        if not lead_data:
            continue

        assigned_caller = None
        assigned_to = lead_data.get("assigned_to")
        if assigned_to and assigned_to in callers_by_id:
            caller_row = callers_by_id[assigned_to]
            assigned_caller = {
                "id": caller_row.get("id"),
                "name": caller_row.get("name"),
                "status": caller_row.get("status"),
                "is_on_call": assigned_to in on_call_ids,
            }

        scheduled_by = None
        scheduler_id = job.get("scheduled_by_caller_id")
        if scheduler_id and scheduler_id in callers_by_id:
            scheduled_by = {
                "id": scheduler_id,
                "name": callers_by_id[scheduler_id].get("name"),
            }

        result.append({
            **job,
            "lead": lead_data,
            "assigned_caller": assigned_caller,
            "scheduled_by": scheduled_by,
        })

    return {"data": result}


@router.patch("/callback/{job_id}/done")
async def mark_callback_done(job_id: str, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    db.table("follow_up_jobs").update({"status": "sent"}).eq("id", job_id).eq("tenant_id", tenant_id).execute()
    return {"success": True}


@router.patch("/callback/{job_id}/reschedule")
async def reschedule_callback(
    job_id: str,
    payload: CallbackReschedule,
    ctx: dict = Depends(get_tenant_and_role)
):
    tenant_id = ctx["tenant_id"]
    role = ctx.get("role")
    caller_id = ctx.get("caller_id")

    db = get_supabase()

    # 1. Verify job belongs to tenant
    job_res = (
        db.table("follow_up_jobs")
        .select("id, lead_id, tenant_id")
        .eq("id", job_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not job_res or not job_res.data:
        raise HTTPException(status_code=404, detail="Callback job not found")

    lead_id = job_res.data["lead_id"]

    # 2. If requester role is 'caller', verify that the lead's assigned_to matches the caller's caller_id.
    if role == "caller":
        if not caller_id:
            raise HTTPException(status_code=403, detail="Caller profile not found")
        # Fetch lead's assigned_to
        lead_res = (
            db.table("leads")
            .select("assigned_to")
            .eq("id", lead_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not lead_res or not lead_res.data or lead_res.data.get("assigned_to") != caller_id:
            raise HTTPException(status_code=403, detail="Lead is not assigned to you")

    # 3. Update scheduled_for and reset status to 'pending'
    update_res = (
        db.table("follow_up_jobs")
        .update({
            "scheduled_for": payload.scheduled_for,
            "status": "pending",
            "due_notified_at": None,
            "claimable_notified_at": None,
        })
        .eq("id", job_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return {"success": True, "data": update_res.data[0] if update_res.data else {}}



@router.get("/callbacks/today-completed")
async def today_completed_callbacks(tenant_id: str = Depends(get_tenant_id), current_user: dict = Depends(get_current_user)):
    """Return callbacks that were marked as done today."""
    db = get_supabase()
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    is_owner = False
    tenant_user = db.table("tenant_users").select("role").eq("user_id", current_user["user_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
    if tenant_user and tenant_user.data and tenant_user.data.get("role") == "owner":
        is_owner = True

    caller_id = None
    if not is_owner:
        caller = db.table("callers").select("id").eq("user_id", current_user["user_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        if caller and caller.data:
            caller_id = caller.data["id"]

    jobs = db.table("follow_up_jobs").select(
        "id,lead_id,scheduled_for,message_preview,status"
    ).eq("tenant_id", tenant_id).eq("cadence", "callback").eq("status", "sent").gte(
        "scheduled_for", day_start
    ).lte("scheduled_for", day_end).order("scheduled_for").execute()

    result = []
    for job in (jobs.data or []):
        lead = db.table("leads").select("id,name,phone,segment,assigned_to").eq(
            "id", job["lead_id"]
        ).eq("tenant_id", tenant_id).maybe_single().execute()
        lead_data = (lead and lead.data) or {}
        
        if not is_owner and lead_data.get("assigned_to") != caller_id:
            continue
            
        result.append({**job, "lead": lead_data})

    return {"data": result}
