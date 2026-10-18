import hmac
import json
import logging
import math
import re
from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID
import httpx
from fastapi import Depends, Query
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app.config import settings
from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, get_tenant_and_role, require_permission
from app.services.call_scorer import finalize_call_score
from app.services.call_ai_pipeline import queue_call_ai, retry_call_ai, run_call_ai
from app.services.call_marking import mark_crm_update
from app.services.call_alerts import EVALUATION_ALERT_TYPES
from app.services.call_evaluation import strip_evaluation
from app.services.call_transcript import mask_transcript, mask_transcripts
from app.services.entitlements import meter, check_quota
from app.services.call_wrapup import (
    WrapupError, as_aware, cloud_never_connected, consecutive_no_connects, validate_wrapup, wrapup_context,
)
from app.services.deals import DealError
from app.services.wrapup_apply import apply_wrapup
from app.services.telecmi_client import initiate_click2call
from app.services.assignment import get_telecalling_config, record_assignment_event
from app.services.segmentation import new_lead_score_and_segment
from app.services.attendance import mark_activity_today


logger = logging.getLogger(__name__)
router = APIRouter()

# What a call card needs: score, group, talk metrics, processing stage, summary and
# the masked transcript preview (the full transcript never leaves the backend).
CALL_CARD_FIELDS = (
    "id,created_at,duration_seconds,status,outcome,manual_status,next_action_at,provider,score,score_status,"
    "evaluation,ai_summary,ai_status,ai_error,recording_url,transcript,"
    "call_group,talk_share,interruption_count,interruptions_per_5min,score_final,ai_call_status,"
    "lead_id,caller_id"
)
public_router = APIRouter()  # No auth — TeleCMI calls these directly

# Wrap-up v2 (spec 2026-09-27). Kept equal to services/call_wrapup.py by test_call_wrapup_routes.
ConnectValue = Literal["connected", "not_picked", "busy", "switched_off"]
OutcomeValue = Literal[
    "interested_booked", "interested_needs_time", "maybe_later", "call_later", "converted",
    "not_interested", "disqualified", "wrong_number", "language_barrier", "do_not_call",
]
ReasonValue = Literal["price", "already_bought", "no_need", "other", "never_enquired", "not_a_fit", "not_decision_maker"]
LanguageValue = Literal["tamil", "english", "hindi", "telugu", "malayalam", "kannada", "other"]

_MESSAGE_LEAD_SOURCES = {"whatsapp", "instagram", "facebook", "telegram", "indiamart", "justdial"}
_SEGMENT_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


def _require_dialer_permission(ctx: dict) -> None:
    if ctx.get("role") == "owner" or "telecalling.dialer" in (ctx.get("permissions") or []):
        return
    raise HTTPException(status_code=403, detail="Permission required: telecalling.dialer")


def _timestamp_sort_value(value: str | None) -> float:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def _is_message_priority_lead(lead: dict, last_inbound_map: dict[str, str] | None = None) -> bool:
    source = (lead.get("source") or "").lower()
    return source in _MESSAGE_LEAD_SOURCES or bool((last_inbound_map or {}).get(lead.get("id")))


def _call_queue_sort_key(lead: dict, last_call_map: dict[str, str], last_inbound_map: dict[str, str]):
    last_call_time = last_call_map.get(lead["id"])
    activity_time = last_inbound_map.get(lead["id"]) or lead.get("assigned_at") or lead.get("created_at")
    return (
        0 if _is_message_priority_lead(lead, last_inbound_map) else 1,
        _SEGMENT_RANK.get(lead.get("segment"), 9),
        -(lead.get("score") or 0),
        0 if last_call_time is None else 1,
        _timestamp_sort_value(last_call_time),
        -_timestamp_sort_value(activity_time),
    )


class InitiateCall(BaseModel):
    lead_id: UUID | None = None
    phone: str | None = None      # manual dial — provide either lead_id or phone
    caller_id: UUID | None = None
    callback_job_id: UUID | None = None


class SendToMobilePayload(BaseModel):
    lead_id: UUID
    caller_id: UUID | None = None



class WrapupProduct(BaseModel):
    catalog_item_id: str = Field(min_length=1, max_length=64)
    qty: int = Field(1, ge=1, le=1000)


class WrapupIn(BaseModel):
    manual_status: ConnectValue
    outcome: OutcomeValue | None = None
    notes: str | None = Field(None, max_length=2000)
    next_action_at: datetime | None = None
    reason: ReasonValue | None = None
    preferred_language: LanguageValue | None = None
    stop_messages: bool = False
    products: list[WrapupProduct] = Field(default_factory=list, max_length=20)
    amount_paise: int | None = Field(None, ge=100, le=10_000_000_000)
    manual_started_at: datetime | None = None
    manual_ended_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0, le=24 * 60 * 60)


class SimCallEntry(BaseModel):
    phone_number: str            # CallLog.Calls.NUMBER
    call_type: int               # CallLog.Calls.TYPE — 1=incoming, 2=outgoing, 3=missed
    timestamp: int               # CallLog.Calls.DATE — epoch milliseconds (phone clock)
    duration: int                # CallLog.Calls.DURATION — seconds, 0 if not answered
    entry_id: str                # CallLog.Calls._ID — dedup key, stored in call_logs.call_sid


class SimCdrPayload(BaseModel):
    calls: list[SimCallEntry] = Field(default_factory=list)


@router.post("/send-to-mobile")
async def send_lead_to_mobile(payload: SendToMobilePayload, ctx: dict = Depends(get_tenant_and_role)):
    _require_dialer_permission(ctx)
    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    lead = (
        db.table("leads")
        .select("id,name,phone")
        .eq("id", str(payload.lead_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not lead.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    target_user_id = ctx.get("user_id")
    target_caller_id = str(payload.caller_id) if payload.caller_id else ctx.get("caller_id")
    if payload.caller_id:
        caller = (
            db.table("callers")
            .select("user_id")
            .eq("id", str(payload.caller_id))
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        target_user_id = (caller.data or {}).get("user_id")
        if not target_user_id:
            raise HTTPException(status_code=404, detail="Selected caller has no mobile login user")
    if not target_user_id:
        raise HTTPException(status_code=401, detail="Missing mobile target user")

    subscription_count = 0
    if target_user_id:
        try:
            subs = (
                db.table("push_subscriptions")
                .select("id", count="exact")
                .eq("tenant_id", tenant_id)
                .eq("user_id", target_user_id)
                .execute()
            )
            subscription_count = subs.count or 0
        except Exception:
            subscription_count = 0

    from app.services.notify import notify_user

    lead_name = lead.data.get("name") or lead.data.get("phone") or "Lead"
    push_url = f"/dashboard/telecalling?lead_id={payload.lead_id}"
    notify_user(
        tenant_id,
        target_user_id,
        "sim_call_handoff",
        "Open lead on mobile",
        f"Call '{lead_name}' from your SIM phone. [lead_id:{payload.lead_id}]",
        db=db,
        push_url=push_url,
    )
    return {
        "sent": True,
        "lead_id": str(payload.lead_id),
        "caller_id": target_caller_id,
        "push_url": push_url,
        "push_configured": bool(settings.vapid_public_key and settings.vapid_private_key),
        "subscription_count": subscription_count,
    }


@router.post("/initiate")
async def initiate_call(payload: InitiateCall, ctx: dict = Depends(get_tenant_and_role)):
    _require_dialer_permission(ctx)
    tenant_id = ctx["tenant_id"]
    role = ctx.get("role")
    cfg = get_telecalling_config(tenant_id)
    calling_provider = cfg.get("calling_provider", "telecmi")

    if not check_quota(get_supabase(), tenant_id, "call_minute"):
        raise HTTPException(
            status_code=403,
            detail="Call minute quota reached. Request more from Settings → Subscription.",
        )

    # App secret is required for Cloud Telephony click-to-call and recording playback.
    telecmi_secret = get_setting("telecmi_secret", tenant_id=tenant_id)
    if calling_provider == "telecmi" and not telecmi_secret:
        raise HTTPException(status_code=400, detail="Cloud Telephony App Secret not configured. Set it in Settings → Telecalling.")

    if not payload.lead_id and not payload.phone:
        raise HTTPException(status_code=400, detail="Provide either lead_id or phone")

    db = get_supabase()

    matched_lead_id: str | None = None
    matched_lead_name: str | None = None

    if payload.lead_id:
        lead = db.table("leads").select("phone,name,do_not_call").eq("id", str(payload.lead_id)).eq("tenant_id", tenant_id).maybe_single().execute()
        if not lead.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        if lead.data.get("do_not_call"):
            raise HTTPException(status_code=400, detail="Lead is on Do Not Call")
        lead_phone = lead.data["phone"]
        matched_lead_id = str(payload.lead_id)
        matched_lead_name = lead.data.get("name")
    else:
        lead_phone = payload.phone
        # try to find a lead by phone so live notes can be linked
        match = db.table("leads").select("id,name,do_not_call").eq("phone", lead_phone).eq("tenant_id", tenant_id).maybe_single().execute()
        if match and match.data:
            if match.data.get("do_not_call"):
                raise HTTPException(status_code=400, detail="Lead is on Do Not Call")
            matched_lead_id = match.data["id"]
            matched_lead_name = match.data.get("name")
        else:
            # auto-create a minimal lead so notes can always be saved
            try:
                initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
                new_lead = db.table("leads").insert({
                    "phone": lead_phone,
                    "source": "manual",
                    "score": initial_score,
                    "segment": initial_segment,
                    "tenant_id": tenant_id,
                    "call_status": "trying",
                }).execute()
                if new_lead.data:
                    matched_lead_id = new_lead.data[0]["id"]
                    matched_lead_name = None
            except Exception as e:
                logger.warning(f"Auto-create lead failed for {lead_phone}: {e}")

    # Resolve caller's phone + TeleCMI agent credentials from the callers table
    caller_telecmi_agent_id: str | None = None
    caller_telecmi_agent_password: str | None = None
    caller_phone: str | None = None
    if payload.caller_id:
        caller = db.table("callers").select("phone,telecmi_agent_id,telecmi_agent_password").eq("id", str(payload.caller_id)).eq("tenant_id", tenant_id).maybe_single().execute()
        if caller.data:
            caller_phone = caller.data.get("phone")
            caller_telecmi_agent_id = caller.data.get("telecmi_agent_id") or None
            caller_telecmi_agent_password = caller.data.get("telecmi_agent_password") or None
    if role != "owner" and not caller_phone:
        raise HTTPException(status_code=400, detail="Caller has no phone number configured")

    if payload.caller_id:
        try:
            mark_activity_today(db, str(payload.caller_id), tenant_id)
        except Exception as e:
            logger.warning(f"Failed to mark caller activity for attendance: {e}")

    log_insert = db.table("call_logs").insert({
        "lead_id": matched_lead_id,
        "caller_id": str(payload.caller_id) if payload.caller_id else None,
        "status": "sim_started" if calling_provider == "sim_basic" else "initiated",
        "tenant_id": tenant_id,
        "follow_up_job_id": str(payload.callback_job_id) if payload.callback_job_id else None,
        "provider": calling_provider,
        "feedback_source": "manual" if calling_provider == "sim_basic" else "automatic",
        "manual_started_at": datetime.now(timezone.utc).isoformat() if calling_provider == "sim_basic" else None,
    }).execute()
    call_log_id = log_insert.data[0]["id"]

    if calling_provider == "sim_basic":
        if matched_lead_id:
            db.table("leads").update({"call_status": "trying"}).eq("id", matched_lead_id).eq("tenant_id", tenant_id).execute()
        return {
            "call_log_id": call_log_id,
            "call_sid": "",
            "status": "sim_started",
            "provider": "sim_basic",
            "lead_id": matched_lead_id,
            "lead_name": matched_lead_name,
            "phone": lead_phone,
        }

    # Resolve TeleCMI Agent ID: caller's own → owner's → global setting.
    # CHUB Admin API connects the agent's user_id first (via followme mobile),
    # then bridges the customer number.
    effective_agent_id = caller_telecmi_agent_id
    if not effective_agent_id:
        owner_member = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").maybe_single().execute()
        if owner_member.data:
            owner_caller = db.table("callers").select("telecmi_agent_id").eq("user_id", owner_member.data["user_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
            if owner_caller.data:
                effective_agent_id = owner_caller.data.get("telecmi_agent_id")
    if not effective_agent_id:
        effective_agent_id = get_setting("telecmi_user_id", tenant_id=tenant_id)
    if not effective_agent_id:
        raise HTTPException(status_code=400, detail="No Cloud Telephony User ID found. Set User ID on the caller in the Team page.")

    telecmi_callerid = get_setting("telecmi_callerid", tenant_id=tenant_id) or caller_phone
    if not telecmi_callerid:
        raise HTTPException(status_code=400, detail="No Caller ID configured. Set Caller ID in Settings → Telecalling.")

    try:
        result = await initiate_click2call(
            agent_id=effective_agent_id,
            secret=telecmi_secret,
            to=lead_phone,
            callerid=telecmi_callerid,
            custom=str(call_log_id),
            followme=True,
            webrtc=False,
        )
        request_id = result.get("request_id", "")
    except HTTPException:
        raise
    except Exception as e:
        err_msg = str(e).replace(telecmi_secret, "***") if telecmi_secret else str(e)
        logger.error(f"TeleCMI call failed: {err_msg}")
        db.table("call_logs").update({"status": "failed"}).eq("id", call_log_id).execute()
        # 424, not 502: the frontend treats 502/503/504 as "our server is down"
        # and replaces this detail with a generic restart message.
        raise HTTPException(status_code=424, detail=f"Cloud Telephony call failed: {err_msg}")

    db.table("call_logs").update({"call_sid": request_id}).eq("id", call_log_id).execute()
    return {
        "call_log_id": call_log_id,
        "call_sid": request_id,
        "status": "initiated",
        "provider": "telecmi",
        "lead_id": matched_lead_id,
        "lead_name": matched_lead_name,
        "phone": lead_phone,
    }


# ── TeleCMI CDR Webhook ──────────────────────────────────────────────
# TeleCMI sends JSON CDR to this endpoint after a call completes.
# Configure this URL in your TeleCMI dashboard → SETTINGS → WEBHOOKS.
# URL: https://YOUR-RENDER-URL.onrender.com/api/v1/calls/telecmi-cdr/{tenant_id}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _verify_telecmi_webhook_secret(request: Request, tenant_id: str | None = None) -> bool:
    configured_secret = get_setting("telecmi_webhook_secret", tenant_id=tenant_id)
    received_secret = request.query_params.get("webhook_secret")
    if not configured_secret or not received_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    if not hmac.compare_digest(received_secret, configured_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    return True


def _extract_call_log_id(cdr: dict) -> str | None:
    """Pull a usable call_log_id out of a TeleCMI CDR.

    click2call metadata is echoed back under `extra_params` as a JSON *string*
    (`'{"call_log_id":"<uuid>"}'`), not as the bare value, and `custom` is a
    separate field entirely. Both are checked, in either string-JSON, dict or
    bare-UUID form. Anything that isn't a UUID is rejected so PostgREST never
    receives a malformed id (it 400s, which crashes maybe_single).
    """
    for key in ("extra_params", "custom"):
        raw = cdr.get(key)
        if not raw:
            continue
        candidates: list[object] = []
        if isinstance(raw, dict):
            candidates.append(raw.get("call_log_id"))
        elif isinstance(raw, str):
            val = raw.strip()
            if val.lower() in {"", "none", "null", "aira_ai_call"}:
                continue
            if val.startswith("{"):
                try:
                    parsed = json.loads(val)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    candidates.append(parsed.get("call_log_id"))
            else:
                candidates.append(val)
        for candidate in candidates:
            if isinstance(candidate, str) and _UUID_RE.match(candidate.strip()):
                return candidate.strip()
    return None


def _match_call_log_by_request_id(cdr: dict) -> str | None:
    """Fall back to the click2call request_id, stored on the log as call_sid."""
    request_id = cdr.get("request_id")
    if not request_id or not isinstance(request_id, str):
        return None
    row = (
        get_supabase()
        .table("call_logs")
        .select("id")
        .eq("call_sid", request_id.strip())
        .maybe_single()
        .execute()
    )
    return row.data["id"] if row and row.data else None


@public_router.post("/telecmi-cdr/{path_tenant_id}")
@public_router.post("/telecmi-cdr")
async def telecmi_cdr(request: Request, background_tasks: BackgroundTasks, path_tenant_id: str | None = None):
    """Receive Call Detail Record (CDR) from TeleCMI."""
    try:
        cdr = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    tenant_id = path_tenant_id or request.query_params.get("tenant_id")
    if not tenant_id:
        call_log_id = _extract_call_log_id(cdr)
        if call_log_id:
            db = get_supabase()
            call_log = db.table("call_logs").select("tenant_id").eq("id", call_log_id).maybe_single().execute()
            if call_log and call_log.data:
                tenant_id = call_log.data.get("tenant_id")

    _verify_telecmi_webhook_secret(request, tenant_id=tenant_id)
    logger.info(f"TeleCMI CDR received: {cdr}")

    status = cdr.get("status")
    call_log_id = _extract_call_log_id(cdr) or _match_call_log_by_request_id(cdr)

    # CHUB sends TWO CDRs per outbound click2call, both carrying the same
    # request_id/extra_params (docs: outgoing-answered, outgoing-missed):
    #   leg 'a' = the agent leg  (`to` is the AGENT's number, `answeredsec`
    #             counts from when the agent picked up, so it includes the
    #             customer's ring time — it is NOT the talk time)
    #   leg 'b' = the customer leg (authoritative for status/duration, and the
    #             only leg that carries `record`/`filename`)
    # Treating both as the whole call made the final status depend on arrival
    # order and metered every call twice. Leg B (or a CDR with no leg at all,
    # e.g. inbound) is authoritative; leg A is only used to detect that the
    # agent never answered.
    leg = str(cdr.get("leg") or "").strip().lower()

    if not call_log_id:
        logger.warning(f"TeleCMI CDR missing/invalid call_log_id, ignoring: {cdr}")
        return {"ok": True}

    db = get_supabase()

    log_row = (
        db.table("call_logs")
        .select("id,caller_id,lead_id,tenant_id,status,duration_seconds")
        .eq("id", call_log_id)
        .maybe_single()
        .execute()
    )
    if not log_row or not log_row.data:
        logger.warning(f"TeleCMI CDR: no call_log found for id={call_log_id}")
        return {"ok": True}

    call_log_id = log_row.data["id"]
    current_status = log_row.data.get("status")

    # Leg A: the agent leg. A 'missed' here means the agent never picked up, so
    # the customer was never dialled — this is the real "user missed" signal
    # (CHUB has no `user_missed` status). Anything else on leg A is progress
    # information only: recording the agent's own answer as the call outcome
    # would mark calls completed that the customer never took.
    if leg == "a":
        if status == "missed" and current_status != "completed":
            logger.info(f"TeleCMI CDR leg A missed: agent never answered call {call_log_id}")
            db.table("call_logs").update({"status": "no_answer"}).eq("id", call_log_id).execute()
            finalize_call_score(db, call_log_id)
        else:
            logger.info(f"TeleCMI CDR leg A ignored (status={status}) for call {call_log_id}")
        return {"ok": True}

    # If call_log has no lead linked, try to match/create one from the dialed
    # number. Only safe on leg B — on leg A `to` is the agent's own number.
    # `leads.phone` is stored as '+91XXXXXXXXXX', so the raw CDR number
    # ('919342012824') must be normalized or it never matches and every CDR
    # silently creates a duplicate lead.
    if not log_row.data.get("lead_id"):
        raw_dialed = cdr.get("to") or cdr.get("customer_number") or cdr.get("did")
        dialed = _normalize_sim_phone(str(raw_dialed)) if raw_dialed else None
        tenant_id = log_row.data.get("tenant_id")
        if dialed and tenant_id:
            match = db.table("leads").select("id").eq("phone", dialed).eq("tenant_id", tenant_id).maybe_single().execute()
            if match and match.data:
                resolved_lead_id = match.data["id"]
            else:
                try:
                    initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
                    new_lead = db.table("leads").insert({
                        "phone": dialed, "source": "manual", "score": initial_score,
                        "segment": initial_segment, "tenant_id": tenant_id,
                        "call_status": "trying",
                    }).execute()
                    resolved_lead_id = new_lead.data[0]["id"] if new_lead.data else None
                except Exception as e:
                    logger.warning(f"CDR: auto-create lead failed for {dialed}: {e}")
                    resolved_lead_id = None
            if resolved_lead_id:
                db.table("call_logs").update({"lead_id": resolved_lead_id}).eq("id", call_log_id).execute()
                log_row.data["lead_id"] = resolved_lead_id
                logger.info(f"CDR: linked call {call_log_id} to lead {resolved_lead_id} via phone {dialed}")

    updates: dict = {}

    # Documented CHUB CDR statuses are "answered" and "missed" only (there is no
    # `user_missed` — the agent-never-answered case is leg A 'missed', handled above).
    if status == "answered":
        updates["status"] = "completed"
        # `answeredsec` is the webhook CDR field; `billedsec` is its name in the
        # pull-report APIs. (There is no `bilsec` — that was a typo'd fallback.)
        answered_sec = cdr.get("answeredsec")
        if answered_sec is None:
            answered_sec = cdr.get("billedsec")
        if answered_sec is not None:
            try:
                updates["duration_seconds"] = int(answered_sec)
            except (ValueError, TypeError):
                pass
    elif status in ("missed", "no_answer"):
        updates["status"] = "no_answer"
    else:
        updates["status"] = "failed"

    if updates:
        db.table("call_logs").update(updates).eq("id", call_log_id).execute()

    # CHUB only ever sends `filename` (+ `record`) on the leg B CDR — there is no
    # record_url/recording_url field in the API. Queued after the duration is
    # stored, because the pipeline reads it to decide whether to score. A
    # redelivered CDR doesn't re-queue a recording that's already in progress.
    recording_filename = cdr.get("filename")
    if recording_filename and updates.get("status") == "completed":
        existing = (
            db.table("call_logs").select("ai_status,recording_filename").eq("id", call_log_id).maybe_single().execute()
        )
        existing_row = (existing.data if existing else None) or {}
        if existing_row.get("recording_filename") != recording_filename or not existing_row.get("ai_status"):
            queue_call_ai(db, call_log_id, recording_filename)
            appid = cdr.get("appid") or cdr.get("app_id")
            background_tasks.add_task(run_call_ai, call_log_id, str(appid) if appid else None)

    # Track-only usage metering: TeleCMI-provider calls only (never the SIM path,
    # which uses the client's own SIM and isn't billed per-minute). Best-effort —
    # never blocks/caps the webhook response.
    # `duration_seconds` already being set means this call was metered by an
    # earlier delivery of this same CDR (TeleCMI retries), so skip it.
    already_metered = bool(log_row.data.get("duration_seconds"))
    if not already_metered and updates.get("status") == "completed" and updates.get("duration_seconds"):
        _tenant_id_for_meter = log_row.data.get("tenant_id")
        if _tenant_id_for_meter:
            meter(db, _tenant_id_for_meter, "call_minute", math.ceil(updates["duration_seconds"] / 60))

    if updates.get("status") in ("completed", "no_answer"):
        row = log_row.data
        finalize_call_score(db, call_log_id)

        # Target achievement milestone check
        if updates.get("status") == "completed" and row.get("caller_id") and row.get("tenant_id"):
            try:
                from datetime import datetime, timezone
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                achieved_res = (
                    db.table("call_logs")
                    .select("id", count="exact")
                    .eq("caller_id", row["caller_id"])
                    .eq("tenant_id", row["tenant_id"])
                    .eq("status", "completed")
                    .gte("created_at", today_start)
                    .execute()
                )
                achieved = achieved_res.count or 0
                
                from app.services.assignment import get_telecalling_config
                cfg = get_telecalling_config(row["tenant_id"])
                targets = cfg.get("targets") or {}
                target = targets.get(str(row["caller_id"])) or targets.get(row["caller_id"]) or targets.get("daily_calls", 50)
                
                if achieved == target:
                    caller_res = db.table("callers").select("user_id, name").eq("id", row["caller_id"]).maybe_single().execute()
                    if caller_res.data and caller_res.data.get("user_id"):
                        from app.services.notify import notify_user
                        notify_user(
                            row["tenant_id"],
                            caller_res.data["user_id"],
                            "milestone_achieved",
                            "Milestone Achieved! 🎉",
                            f"Congratulations {caller_res.data['name']}! You have achieved your daily target of {target} calls today.",
                            db=db,
                        )
            except Exception as milestone_err:
                logger.warning(f"Failed to verify milestone target completed: {milestone_err}")

    return {"ok": True}


# ── SIM-based Call Tracking (Android sync app) ────────────────────────
# The Anril Sync APK reads the phone's native call log and POSTs new entries
# here in batches, authenticated by a per-caller sync_token. No cloud
# telephony involved — calls are placed on the caller's own SIM.

def _normalize_sim_phone(phone: str) -> str:
    """Normalize an Android call-log number to the '+91XXXXXXXXXX' format
    leads.phone is actually stored in, so '.eq("phone", ...)' lookups match.

    Strips everything but digits, drops a leading '91' country code when the
    remaining number is 12 digits, then re-adds '+91' once the number is a
    bare 10 digits — so '+91 98765 43210', '9198765 43210' and '9876543210'
    all normalize to '+919876543210'. The Android client mirrors this exact
    logic (CallLogReader.kt normalizePhone) so the on-device lead-number
    filter and this server-side lookup agree on the same canonical form.
    """
    digits = re.sub(r"[^\d]", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 10:
        return f"+91{digits}"
    return digits


def _sim_status_from_type(call_type: int, duration: int) -> tuple[str, str | None]:
    """Map an Android CallLog type + duration to (status, disposition). Never an outcome:
    tap 2 of the wrap-up is the telecaller's."""
    # 2 = outgoing, 1 = incoming, 3 = missed (rejected/blocked/voicemail → failed)
    if call_type in (1, 2) and duration > 0:
        return "completed", "answered"
    if call_type == 2 and duration == 0:
        return "no_answer", "no_answer"
    if call_type == 3:
        return "no_answer", "no_answer"
    return "failed", None


# Calls created before this instant never owe feedback (gate go-live cutoff).
FEEDBACK_GATE_SINCE = "2026-09-24T00:00:00+00:00"

# PostgREST caps a select at 1000 rows; page so big tenants aren't silently truncated.
_LEAD_NUMBERS_PAGE = 1000

_SIM_DIRECTION_BY_TYPE = {1: "incoming", 2: "outgoing", 3: "missed"}


def _sim_direction(call_type: int) -> str | None:
    """Map an Android CallLog type to call_logs.direction (None if unknown)."""
    return _SIM_DIRECTION_BY_TYPE.get(call_type)


def _parse_app_version(request: Request) -> int | None:
    """Anril Sync build number from the X-App-Version header (None if absent/garbled)."""
    raw = request.headers.get("X-App-Version")
    if raw and raw.isdigit():
        return int(raw)
    return None


def _touch_caller_sync(db, caller_id: str, app_version: int | None = None) -> None:
    """Heartbeat for the owner's sync/version warnings. Never fails a sync."""
    updates: dict = {"last_sync_at": datetime.now(timezone.utc).isoformat()}
    if app_version is not None:
        updates["app_version"] = app_version
    try:
        db.table("callers").update(updates).eq("id", caller_id).execute()
    except Exception as e:
        logger.warning(f"sim sync heartbeat failed for caller {caller_id}: {e}")


# version.json sits next to the APK in the public app-releases bucket and is the
# single source of truth for "what is the latest Anril Sync build".
_SIM_APP_VERSION_URL = f"{settings.supabase_url}/storage/v1/object/public/app-releases/version.json"
_SIM_APP_VERSION_TTL_S = 600
_sim_app_version_cache: dict = {"at": 0.0, "value": None}


async def _latest_sim_app_version() -> int | None:
    """Latest published Anril Sync versionCode, cached; None if unreachable."""
    import time
    now = time.monotonic()
    # at == 0.0 means never fetched. monotonic() can itself be under the TTL right after boot.
    if _sim_app_version_cache["at"] and now - _sim_app_version_cache["at"] < _SIM_APP_VERSION_TTL_S:
        return _sim_app_version_cache["value"]
    value = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(_SIM_APP_VERSION_URL)
            res.raise_for_status()
            code = res.json().get("versionCode")
            value = int(code) if isinstance(code, int) else None
    except Exception as e:
        logger.warning(f"could not read Anril Sync version.json: {e}")
    _sim_app_version_cache.update(at=now, value=value)
    return value


def _resolve_sim_caller(request: Request) -> dict:
    """Authenticate a SIM sync request via the X-Sync-Token header.

    Returns the caller row {id, tenant_id} or raises 401. The token is a
    per-caller secret minted by POST /callers/{id}/sync-token.
    """
    token = request.headers.get("X-Sync-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing sync token")
    db = get_supabase()
    caller = (
        db.table("callers")
        .select("id,tenant_id,active")
        .eq("sync_token", token)
        .maybe_single()
        .execute()
    )
    if not caller or not caller.data or not caller.data.get("active"):
        raise HTTPException(status_code=401, detail="Invalid sync token")
    return caller.data


@public_router.post("/sim-cdr")
async def sim_cdr(payload: SimCdrPayload, request: Request, background_tasks: BackgroundTasks):
    """Ingest a batch of native call-log entries from the Anril Sync APK.

    Idempotent: each entry is deduped on (caller_id, call_sid=entry_id) so
    re-syncs and WorkManager retries never create duplicate call_logs.
    """
    caller = _resolve_sim_caller(request)
    caller_id = caller["id"]
    tenant_id = caller["tenant_id"]
    db = get_supabase()
    _touch_caller_sync(db, caller_id, _parse_app_version(request))

    results: list[dict] = []
    for entry in payload.calls:
        try:
            results.append(_ingest_sim_call(db, caller_id, tenant_id, entry))
        except Exception as e:
            logger.warning(f"sim-cdr: failed to ingest entry {entry.entry_id}: {e}")
            results.append({"entry_id": entry.entry_id, "error": "ingest_failed"})

    synced = sum(1 for r in results if r.get("call_log_id"))
    return {"synced": synced, "received": len(payload.calls), "results": results}


@public_router.get("/sim-lead-numbers")
async def sim_lead_numbers(request: Request):
    """Return the tenant's lead phone numbers for on-device filtering.

    The APK fetches this set and only uploads call-log entries whose number is
    in it — so personal calls never leave the phone. Covers every lead in the
    tenant (not just the caller's assigned ones) so a call to an unassigned or
    pool lead is still tracked and owes feedback. Numbers are normalized the
    same way the ingest path normalizes them, so the device can compare directly.
    Also the Anril Sync heartbeat: the APK calls this on every run.
    """
    caller = _resolve_sim_caller(request)
    caller_id = caller["id"]
    tenant_id = caller["tenant_id"]
    db = get_supabase()
    _touch_caller_sync(db, caller_id, _parse_app_version(request))

    phones: list[str] = []
    start = 0
    while True:
        page = (
            db.table("leads")
            .select("phone")
            .eq("tenant_id", tenant_id)
            .is_("deleted_at", "null")
            .not_.is_("phone", "null")
            .order("id")
            .range(start, start + _LEAD_NUMBERS_PAGE - 1)
            .execute()
        ).data or []
        phones.extend(r.get("phone") or "" for r in page)
        if len(page) < _LEAD_NUMBERS_PAGE:
            break
        start += _LEAD_NUMBERS_PAGE
    numbers = sorted({n for p in phones if (n := _normalize_sim_phone(p))})
    return {"numbers": numbers, "count": len(numbers)}


# How far back to look for a PWA-created "sim_started" row to enrich. The PWA
# writes the row at dial time, moments before the call — a 12h window safely
# covers a shift without matching stale rows from previous days.
_SIM_ENRICH_WINDOW_HOURS = 12


def _ingest_sim_call(db, caller_id: str, tenant_id: str, entry: "SimCallEntry") -> dict:
    """Record one native call-log entry, enriching a PWA-created row if present.

    The PWA (the reliable baseline) creates a `sim_started` row when the caller
    taps "Call". This APK path is best-effort: it COMPLETES that row with the
    real duration/disposition (and later, the recording) instead of inserting a
    duplicate. If no pending row exists — e.g. the caller dialled straight from
    contacts, or the PWA call wasn't logged — it creates a fresh row so the call
    is still tracked.
    """
    # 1. Idempotency — already synced this exact call-log entry? Return as-is.
    existing = (
        db.table("call_logs")
        .select("id,lead_id")
        .eq("caller_id", caller_id)
        .eq("call_sid", entry.entry_id)
        .eq("provider", "sim_basic")
        .maybe_single()
        .execute()
    )
    if existing and existing.data:
        return {
            "entry_id": entry.entry_id,
            "call_log_id": existing.data["id"],
            "lead_id": existing.data.get("lead_id"),
            "deduped": True,
        }

    # 2. Resolve / auto-create the lead by normalized phone.
    dialed = _normalize_sim_phone(entry.phone_number)
    lead_id = None
    lead_name = None
    is_new_lead = False
    if dialed:
        match = (
            db.table("leads")
            .select("id,name")
            .eq("phone", dialed)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if match and match.data:
            lead_id = match.data["id"]
            lead_name = match.data.get("name")
        else:
            initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
            new_lead = db.table("leads").insert({
                "phone": dialed, "source": "manual", "score": initial_score,
                "segment": initial_segment, "tenant_id": tenant_id,
                "call_status": "trying",
            }).execute()
            if new_lead.data:
                lead_id = new_lead.data[0]["id"]
                is_new_lead = True

    status, disposition = _sim_status_from_type(entry.call_type, entry.duration)
    call_dt = datetime.fromtimestamp(entry.timestamp / 1000, tz=timezone.utc)

    # 3. Reconcile: find a recent PWA-created row for this caller+lead to
    #    enrich with the APK's real data, regardless of whether the wrap-up
    #    form has already been submitted. Ordering must not matter — a
    #    telecaller can finish wrap-up before or after the APK syncs, and
    #    either way there should be exactly one row per call. The only gate
    #    is `call_sid IS NULL`: once a row has a call_sid, dedup (step 1)
    #    already owns it, so it's not a candidate to re-enrich.
    pending_id = None
    if lead_id:
        window_start = (call_dt - timedelta(hours=_SIM_ENRICH_WINDOW_HOURS)).isoformat()
        pending = (
            db.table("call_logs")
            .select("id")
            .eq("caller_id", caller_id)
            .eq("lead_id", lead_id)
            .eq("provider", "sim_basic")
            .is_("call_sid", "null")
            .gte("created_at", window_start)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if pending and pending.data:
            pending_id = pending.data[0]["id"]

    # 4a. Enrich the existing PWA row, or 4b. create a fresh one.
    # `updates` only ever carries "hard facts" the APK measured directly
    # (call_sid, status, disposition, duration). It must NEVER include an
    # outcome, notes, or manual_started_at/ended_at — those are always
    # human-owned via the wrap-up form, whether it ran before or after this.
    updates: dict = {
        "call_sid": entry.entry_id,
        "status": status,
        "disposition": disposition,
        "duration_seconds": entry.duration,
        "direction": _sim_direction(entry.call_type),
    }

    if pending_id:
        db.table("call_logs").update(updates).eq("id", pending_id).execute()
        call_log_id = pending_id
        action = "enriched"
    else:
        row = {
            "lead_id": lead_id,
            "caller_id": caller_id,
            "tenant_id": tenant_id,
            "provider": "sim_basic",
            "feedback_source": "automatic",
            "created_at": call_dt.isoformat(),
            **updates,
        }
        inserted = db.table("call_logs").insert(row).execute()
        call_log_id = inserted.data[0]["id"] if inserted.data else None
        action = "created"

    return {
        "entry_id": entry.entry_id,
        "call_log_id": call_log_id,
        "lead_id": lead_id,
        "lead_name": lead_name,
        "is_new_lead": is_new_lead,
        "action": action,
        "deduped": False,
    }


# ── TeleCMI Live Events Webhook ───────────────────────────────────────
# Optional: receive real-time call status events (started, answered, hangup)

@public_router.post("/telecmi-events")
async def telecmi_live_events(request: Request):
    """Receive live call events from TeleCMI (optional — for real-time UI updates)."""
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    tenant_id = request.query_params.get("tenant_id")
    if not tenant_id:
        request_id = event.get("request_id")
        if request_id:
            db = get_supabase()
            call_log = db.table("call_logs").select("tenant_id").eq("call_sid", request_id).maybe_single().execute()
            if call_log and call_log.data:
                tenant_id = call_log.data.get("tenant_id")

    _verify_telecmi_webhook_secret(request, tenant_id=tenant_id)
    status = event.get("status")
    request_id = event.get("request_id")
    leg = str(event.get("leg") or "").strip().lower()
    logger.info(f"TeleCMI event: status={status}, leg={leg or '-'}, request_id={request_id}")

    # Live events also fire per leg (docs: live-outgoing-out-*), so leg A's
    # 'hangup' arrives while the customer leg may still be up — and previously
    # flipped the log to "completed". Only the customer leg drives UI state.
    if leg == "a":
        return {"ok": True}

    if request_id:
        db = get_supabase()
        # Documented live-event statuses: started, ringing, answered, hangup,
        # waiting. These are progress signals only — the terminal status comes
        # from the CDR, which knows the real duration and recording. Never write
        # a terminal status here or a late 'hangup' overwrites a CDR's no_answer.
        log_status = None
        if status in ("started", "ringing"):
            log_status = "initiated"
        elif status == "answered":
            log_status = "in_progress"

        if log_status:
            (
                db.table("call_logs")
                .update({"status": log_status})
                .eq("call_sid", request_id)
                .in_("status", ["initiated", "in_progress"])
                .execute()
            )

    return {"ok": True}


# ── Outcome & Other Endpoints ────────────────────────────────────────

async def mark_crm_update_task(call_log_id: str) -> None:
    try:
        await mark_crm_update(get_supabase(), call_log_id)
    except Exception as e:
        logger.error(f"CRM check failed for call {call_log_id}: {e}")


@router.patch("/{call_log_id}/outcome")
async def set_outcome(call_log_id: str, payload: WrapupIn, background_tasks: BackgroundTasks, ctx: dict = Depends(get_tenant_and_role)):
    """Save the two-tap wrap-up (v2). Rules: services/call_wrapup.py; writes: services/wrapup_apply.py."""
    db = get_supabase()
    log = (
        db.table("call_logs")
        .select("caller_id,duration_seconds,lead_id,follow_up_job_id,provider,status,outcome")
        .eq("id", call_log_id)
        .eq("tenant_id", ctx["tenant_id"])
        .maybe_single()
        .execute()
    )
    if not log or not log.data:
        raise HTTPException(status_code=404, detail="Call log not found")
    row = log.data
    is_telecmi = row.get("provider") == "telecmi"
    now = datetime.now(timezone.utc)
    next_at = as_aware(payload.next_action_at) if payload.next_action_at else None
    try:
        validate_wrapup(
            never_connected=is_telecmi and cloud_never_connected(row),
            manual_status=payload.manual_status, outcome=payload.outcome, notes=payload.notes,
            next_action_at=next_at, reason=payload.reason, preferred_language=payload.preferred_language,
            has_products=bool(payload.products), amount_paise=payload.amount_paise, now=now,
        )
    except WrapupError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # TeleCMI's measured talk time decides scoring; a typed-in duration must never override it.
    log_extra: dict = {}
    if not is_telecmi:
        if payload.duration_seconds is not None:
            log_extra["duration_seconds"] = payload.duration_seconds
        if payload.manual_started_at is not None:
            log_extra["manual_started_at"] = payload.manual_started_at.isoformat()
        if payload.manual_ended_at is not None:
            log_extra["manual_ended_at"] = payload.manual_ended_at.isoformat()
    wrapup = {
        "manual_status": payload.manual_status, "outcome": payload.outcome, "notes": payload.notes,
        "next_action_at": next_at, "reason": payload.reason, "preferred_language": payload.preferred_language,
        "stop_messages": payload.stop_messages, "products": [p.model_dump() for p in payload.products],
        "amount_paise": payload.amount_paise,
    }
    try:
        result = await apply_wrapup(
            db, tenant_id=ctx["tenant_id"], user_id=ctx.get("user_id"), caller_id=ctx.get("caller_id"),
            call_log_id=call_log_id, log=row, wrapup=wrapup, log_extra=log_extra, now=now,
        )
    except DealError as e:
        raise HTTPException(status_code=400, detail=str(e))

    scoring = finalize_call_score(db, call_log_id)
    if is_telecmi:
        background_tasks.add_task(mark_crm_update_task, call_log_id)
    response = {
        "call_log_id": call_log_id,
        "manual_status": payload.manual_status,
        "outcome": payload.outcome,
        "call_status": result["call_status"],
        "next_action_at": result["next_action_at"],
        "deal_id": result["deal_id"],
    }
    # SIM clients get no evaluation at all -- gated on the tenant's own
    # calling_provider, same as every other route, not on whether this
    # particular call happened to get scored.
    is_sim = get_telecalling_config(ctx["tenant_id"], db=db).get("calling_provider", "telecmi") == "sim_basic"
    if not is_sim:
        response["score"] = (scoring or {}).get("score")
        response["score_status"] = (scoring or {}).get("score_status")
    return response


@router.get("/stats-today")
async def stats_today(ctx: dict = Depends(get_tenant_and_role)):
    from datetime import datetime, timezone
    db = get_supabase()
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    result = db.table("call_logs").select("id,outcome").eq("tenant_id", ctx["tenant_id"]).gte("created_at", today).execute()
    logs = result.data or []
    return {
        "calls_today": len(logs),
        "conversions_today": sum(1 for l in logs if l.get("outcome") == "converted"),
    }


@router.get("/recent")
async def recent_calls(
    limit: int = Query(20, ge=1, le=50),
    caller_id: str | None = Query(None),
    ctx: dict = Depends(get_tenant_and_role),
):
    """Latest calls across all leads — the dialer's Recent tab.

    Per-lead history already exists (`/leads/{id}/call-logs`); this answers the
    other question a telecaller has ("what did I call today?") without leaving
    the dialer. A caller only ever sees their own calls, whatever they ask for.
    """
    db = get_supabase()
    query = (
        db.table("call_logs")
        .select(
            f"{CALL_CARD_FIELDS},leads(name,phone),callers(name)"
        )
        .eq("tenant_id", ctx["tenant_id"])
    )
    if ctx.get("role") == "caller" and ctx.get("caller_id"):
        query = query.eq("caller_id", ctx["caller_id"])
    elif caller_id:
        query = query.eq("caller_id", caller_id)
    rows = query.order("created_at", desc=True).limit(limit).execute()
    is_sim = get_telecalling_config(ctx["tenant_id"], db=db).get("calling_provider", "telecmi") == "sim_basic"
    return {"data": strip_evaluation(mask_transcripts(rows.data), is_sim)}


@router.get("/recent-by-leads")
async def recent_by_leads(lead_ids: str = Query(..., description="Comma-separated lead UUIDs, max 50"), ctx: dict = Depends(get_tenant_and_role)):
    ids = [i.strip() for i in lead_ids.split(",") if i.strip()][:50]
    if not ids:
        return {}
    db = get_supabase()
    rows = (
        db.table("call_logs")
        .select("lead_id,created_at")
        .in_("lead_id", ids)
        .eq("tenant_id", ctx["tenant_id"])
        .order("created_at", desc=True)
        .execute()
    )
    seen: dict[str, str] = {}
    for row in rows.data or []:
        lid = row["lead_id"]
        if lid not in seen:
            seen[lid] = row["created_at"]
    return seen


@router.get("/alerts")
async def list_call_alerts(
    type: str | None = Query(None),
    caller_id: UUID | None = Query(None),
    seen: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    ctx: dict = Depends(require_permission("team.manage")),
):
    """The admin's Needs-attention list. SIM clients get no evaluation at all --
    the scoring-derived alert types (rude, wrong_info, etc.) never show for them,
    only the operational ones (language_barrier, lead_source_quality)."""
    db = get_supabase()
    is_sim = get_telecalling_config(ctx["tenant_id"], db=db).get("calling_provider", "telecmi") == "sim_basic"
    query = (
        db.table("call_alerts")
        .select("id,type,quote,detail,created_at,seen_at,caller_id,call_log_id,callers(name),"
                "call_logs(id,created_at,duration_seconds,lead_id,leads(name,phone))", count="exact")
        .eq("tenant_id", ctx["tenant_id"])
    )
    query = query.not_.is_("seen_at", "null") if seen else query.is_("seen_at", "null")
    if is_sim:
        query = query.not_.in_("type", list(EVALUATION_ALERT_TYPES))
    if type:
        query = query.eq("type", type)
    if caller_id:
        query = query.eq("caller_id", str(caller_id))
    offset = (page - 1) * limit
    rows = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"data": rows.data or [], "total": rows.count or 0, "page": page, "limit": limit}


@router.get("/alerts/count")
async def count_call_alerts(ctx: dict = Depends(require_permission("team.manage"))):
    db = get_supabase()
    is_sim = get_telecalling_config(ctx["tenant_id"], db=db).get("calling_provider", "telecmi") == "sim_basic"
    query = db.table("call_alerts").select("id", count="exact").eq("tenant_id", ctx["tenant_id"]).is_("seen_at", "null")
    if is_sim:
        query = query.not_.in_("type", list(EVALUATION_ALERT_TYPES))
    res = query.limit(1).execute()
    return {"count": res.count or 0}


@router.post("/alerts/{alert_id}/seen")
async def mark_call_alert_seen(alert_id: UUID, ctx: dict = Depends(require_permission("team.manage"))):
    db = get_supabase()
    res = (
        db.table("call_alerts")
        .update({"seen_at": datetime.now(timezone.utc).isoformat(), "seen_by": ctx.get("user_id")})
        .eq("id", str(alert_id)).eq("tenant_id", ctx["tenant_id"]).execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Alert not found")
    return res.data[0]


@router.post("/{call_log_id}/retry-ai")
async def retry_ai(call_log_id: UUID, background_tasks: BackgroundTasks, ctx: dict = Depends(get_tenant_and_role)):
    """Re-run transcription + scoring for a call whose processing failed.
    SIM clients get no evaluation at all -- this route doesn't exist for them."""
    db = get_supabase()
    if get_telecalling_config(ctx["tenant_id"], db=db).get("calling_provider", "telecmi") == "sim_basic":
        raise HTTPException(status_code=404, detail="Not available for this client")
    if not retry_call_ai(db, str(call_log_id), ctx["tenant_id"]):
        raise HTTPException(status_code=404, detail="This call has no failed processing to retry")
    finalize_call_score(db, str(call_log_id))
    background_tasks.add_task(run_call_ai, str(call_log_id))
    return {"ok": True}


@router.get("/next-lead")
async def next_lead(
    caller_id: UUID | None = Query(None),
    ctx: dict = Depends(get_tenant_and_role)
):
    _require_dialer_permission(ctx)
    tenant_id = ctx["tenant_id"]
    resolved_caller_id = str(caller_id) if caller_id else ctx.get("caller_id")
    if not resolved_caller_id:
        raise HTTPException(status_code=400, detail="caller_id is required")

    db = get_supabase()

    # 1. Fetch telecalling config segments
    cfg = get_telecalling_config(tenant_id)
    if not cfg.get("enabled"):
        raise HTTPException(status_code=404, detail="Telecalling is not enabled")
    segments = cfg.get("segments", ["A"])

    # 1b. Shift-hour gate — reject if caller is outside their shift
    shift_mode = cfg.get("shift_mode", "common")
    common_start = cfg.get("shift_start_hour", 9)
    common_end = cfg.get("shift_end_hour", 19)
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    current_hour = now_ist.hour
    caller_row = (
        db.table("callers")
        .select("shift_start_hour,shift_end_hour")
        .eq("id", resolved_caller_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if caller_row and caller_row.data:
        if shift_mode == "individual":
            s_h = caller_row.data.get("shift_start_hour")
            e_h = caller_row.data.get("shift_end_hour")
            s_h = s_h if s_h is not None else common_start
            e_h = e_h if e_h is not None else common_end
        else:
            s_h, e_h = common_start, common_end
        if s_h <= e_h:
            in_shift = s_h <= current_hour < e_h
        else:
            in_shift = current_hour >= s_h or current_hour < e_h
        if not in_shift:
            return {"lead": None, "reason": "outside_shift_hours"}

    # 2. Pull unassigned hot leads in telecalling_config.segments (default ['A']), not D, not converted, sorted by score desc.
    unassigned_res = (
        db.table("leads")
        .select("*")
        .eq("tenant_id", tenant_id)
        .is_("assigned_to", "null")
        .in_("segment", segments)
        .neq("segment", "D")
        .is_("converted_at", "null")
        .is_("deleted_at", "null")
        .neq("do_not_call", True)
        .neq("call_status", "converted")
        .neq("call_status", "not_interested")
        .neq("call_status", "dnc")
        .neq("call_status", "disqualified")
        .neq("call_status", "unreachable")
        .order("segment")
        .order("last_inbound_at", desc=True, nullsfirst=False)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )

    if unassigned_res.data:
        candidate_ids = [lead["id"] for lead in unassigned_res.data]
        inbound_res = (
            db.table("messages")
            .select("lead_id, created_at")
            .eq("tenant_id", tenant_id)
            .in_("lead_id", candidate_ids)
            .eq("direction", "inbound")
            .order("created_at", desc=True)
            .execute()
        )
        last_inbound_map = {}
        for msg in (inbound_res.data or []):
            lid = msg["lead_id"]
            if lid not in last_inbound_map:
                last_inbound_map[lid] = msg["created_at"]

        candidates = sorted(unassigned_res.data, key=lambda lead: _call_queue_sort_key(lead, {}, last_inbound_map))
        caller_name = None
        caller_res = db.table("callers").select("name").eq("id", resolved_caller_id).eq("tenant_id", tenant_id).maybe_single().execute()
        if caller_res and caller_res.data:
            caller_name = caller_res.data.get("name")

        # Atomic claim: only assign if the lead is STILL unassigned. Guards
        # against two callers pulling the same lead at the same instant — the
        # loser's update matches 0 rows, so we try the next candidate.
        for lead in candidates:
            claim = (
                db.table("leads")
                .update({
                    "assigned_to": resolved_caller_id,
                    "assigned_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", lead["id"])
                .eq("tenant_id", tenant_id)
                .is_("assigned_to", "null")
                .execute()
            )
            if claim.data:
                record_assignment_event(
                    lead_id=lead["id"],
                    tenant_id=tenant_id,
                    segment=lead.get("segment"),
                    caller_id=resolved_caller_id,
                    caller_name=caller_name,
                    reason="call_next",
                    method="pull",
                    score=lead.get("score"),
                    matched_segments=segments,
                    db=db,
                )
                return {**claim.data[0], "_source": "pool"}

    # 3. Fall back to caller's own assigned leads, sorted by least-recently-called
    assigned_res = (
        db.table("leads")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("assigned_to", resolved_caller_id)
        .neq("segment", "D")
        .is_("converted_at", "null")
        .is_("deleted_at", "null")
        .neq("do_not_call", True)
        .neq("call_status", "converted")
        .neq("call_status", "dnc")
        .neq("call_status", "disqualified")
        .neq("call_status", "unreachable")
        .execute()
    )

    leads_list = assigned_res.data or []
    if not leads_list:
        raise HTTPException(status_code=404, detail="No leads in pool or queue")

    lead_ids = [lead["id"] for lead in leads_list]
    inbound_res = (
        db.table("messages")
        .select("lead_id, created_at")
        .eq("tenant_id", tenant_id)
        .in_("lead_id", lead_ids)
        .eq("direction", "inbound")
        .order("created_at", desc=True)
        .execute()
    )

    last_inbound_map = {}
    for msg in (inbound_res.data or []):
        lid = msg["lead_id"]
        if lid not in last_inbound_map:
            last_inbound_map[lid] = msg["created_at"]

    logs_res = (
        db.table("call_logs")
        .select("lead_id, created_at")
        .eq("tenant_id", tenant_id)
        .in_("lead_id", lead_ids)
        .order("created_at", desc=True)
        .execute()
    )

    last_call_map = {}
    for log in (logs_res.data or []):
        lid = log["lead_id"]
        if lid not in last_call_map:
            last_call_map[lid] = log["created_at"]

    leads_list.sort(key=lambda lead: _call_queue_sort_key(lead, last_call_map, last_inbound_map))
    return {**leads_list[0], "_source": "queue"}


@router.get("/assignment-mode")
async def get_assignment_mode(ctx: dict = Depends(get_tenant_and_role)):
    cfg = get_telecalling_config(ctx["tenant_id"])
    return {
        "mode": cfg.get("assignment_mode", "push"),
        "enabled": cfg.get("enabled", False),
        "calling_provider": cfg.get("calling_provider", "telecmi"),
    }


@router.get("/pending-wrapups")
async def get_pending_wrapups(ctx: dict = Depends(get_tenant_and_role)):
    """Calls still owing human feedback.

    SIM calls owe feedback until a human submits an outcome (`feedback_at`) or the
    owner dismisses them — the Anril Sync upload auto-fills disposition/outcome, so
    those columns can't tell us. Other providers keep the original rule.
    """
    tenant_id = ctx["tenant_id"]
    caller_id = ctx.get("caller_id")
    db = get_supabase()

    sim_q = (
        db.table("call_logs")
        .select("*, leads(name, phone)")
        .eq("tenant_id", tenant_id)
        .eq("provider", "sim_basic")
        .is_("feedback_at", "null")
        .is_("feedback_dismissed_at", "null")
        .not_.is_("lead_id", "null")
        .gte("created_at", FEEDBACK_GATE_SINCE)
    )
    other_q = (
        db.table("call_logs")
        .select("*, leads(name, phone)")
        .eq("tenant_id", tenant_id)
        .neq("provider", "sim_basic")
        .eq("status", "completed")
        .is_("manual_status", "null")
        .is_("outcome", "null")
        .is_("disposition", "null")
    )
    if caller_id:
        sim_q = sim_q.eq("caller_id", caller_id)
        other_q = other_q.eq("caller_id", caller_id)

    rows = (sim_q.execute().data or []) + (other_q.execute().data or [])
    is_sim = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi") == "sim_basic"
    return strip_evaluation(mask_transcripts(sorted(rows, key=lambda r: r.get("created_at") or "")), is_sim)


@router.get("/pending-wrapups/summary")
async def pending_wrapups_summary(ctx: dict = Depends(get_tenant_and_role)):
    """Owner view: per-telecaller pending-feedback count + Anril Sync heartbeat."""
    if ctx.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner only")
    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    pending = (
        db.table("call_logs")
        .select("caller_id")
        .eq("tenant_id", tenant_id)
        .eq("provider", "sim_basic")
        .is_("feedback_at", "null")
        .is_("feedback_dismissed_at", "null")
        .not_.is_("lead_id", "null")
        .not_.is_("caller_id", "null")
        .gte("created_at", FEEDBACK_GATE_SINCE)
        .execute()
    ).data or []
    counts: dict[str, int] = {}
    for r in pending:
        counts[r["caller_id"]] = counts.get(r["caller_id"], 0) + 1

    callers = (
        db.table("callers")
        .select("id,name,last_sync_at,sync_token,app_version")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
        .execute()
    ).data or []
    latest_version = await _latest_sim_app_version()
    return [
        {
            "caller_id": c["id"],
            "name": c.get("name"),
            "pending_count": counts.get(c["id"], 0),
            "last_sync_at": c.get("last_sync_at"),
            "has_sync_token": bool(c.get("sync_token")),
            "app_version": c.get("app_version"),
            "latest_app_version": latest_version,
        }
        for c in callers
    ]


@router.get("/wrapup-context")
async def get_wrapup_context(
    lead_id: UUID | None = Query(None),
    call_log_id: UUID | None = Query(None),
    ctx: dict = Depends(get_tenant_and_role),
):
    """What the wrap-up form needs up front: the cloud pre-fill of tap 1 and the retry suggestions."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    row = None
    if call_log_id:
        rows = (
            db.table("call_logs").select("id,provider,status,duration_seconds,lead_id")
            .eq("id", str(call_log_id)).eq("tenant_id", tenant_id).limit(1).execute()
        ).data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Call log not found")
        row = rows[0]
    lead = str(lead_id) if lead_id else (row or {}).get("lead_id")
    failed_before = 0
    # Only meaningful once there's a concrete call to count consecutive failures *before* —
    # a bare lead_id (no call logged yet) has no anchor to exclude, so it stays 0.
    if call_log_id and lead:
        history = (
            db.table("call_logs").select("id,manual_status,status,created_at")
            .eq("lead_id", lead).eq("tenant_id", tenant_id)
            .order("created_at", desc=True).limit(20).execute()
        ).data or []
        current = str(call_log_id)
        failed_before = consecutive_no_connects([r for r in history if r["id"] != current])
    return wrapup_context(row, failed_before, datetime.now(timezone.utc))


class DismissFeedback(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/{call_log_id}/dismiss-feedback")
async def dismiss_feedback(call_log_id: str, payload: DismissFeedback, ctx: dict = Depends(get_tenant_and_role)):
    """Owner clears a call from a telecaller's pending list (wrong number, personal call…)."""
    if ctx.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner only")
    db = get_supabase()
    result = (
        db.table("call_logs")
        .update({
            "feedback_dismissed_at": datetime.now(timezone.utc).isoformat(),
            "feedback_dismissed_by": str(ctx.get("user_id") or ""),
            "feedback_dismiss_reason": payload.reason.strip(),
        })
        .eq("id", call_log_id)
        .eq("tenant_id", ctx["tenant_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Call log not found")
    return {"dismissed": True}


@router.get("/{call_log_id}")
async def get_call_log(call_log_id: UUID, ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()
    result = (
        db.table("call_logs")
        .select("*")
        .eq("id", str(call_log_id))
        .eq("tenant_id", ctx["tenant_id"])
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Call log not found")
    is_sim = get_telecalling_config(ctx["tenant_id"], db=db).get("calling_provider", "telecmi") == "sim_basic"
    return strip_evaluation(mask_transcript(result.data), is_sim)


@router.delete("/{call_log_id}")
async def delete_call_log(call_log_id: str, ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()
    result = db.table("call_logs").delete().eq("id", call_log_id).eq("tenant_id", ctx["tenant_id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Call log not found")
    return {"deleted": True}
