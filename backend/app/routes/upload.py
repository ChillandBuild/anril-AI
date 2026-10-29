import asyncio
import csv
import io
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services.ai_reply import send_whatsapp
from app.services.delivery_status import nearest_record, nearest_status, parse_ts
from app.services.gemini_client import gemini_extract_contacts_csv
from app.services.growth import get_or_create_campaign, record_stage_event, sync_follow_up_jobs
from app.services.meta_cloud import send_template_message
from app.services.broadcast_executor import next_send_time
from app.services.outbound_router import SenderPicker, get_best_number
from app.services.template_params import body_parameters, template_status
from app.services.segmentation import new_lead_score_and_segment

logger = logging.getLogger(__name__)
require_outbound_read = require_permission("outbound_leads.view")
require_outbound_manage = require_permission("outbound_leads.manage")

router = APIRouter(dependencies=[Depends(require_outbound_read)])

PHONE_RE = re.compile(r"[^\d+]")


def _normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    digits_only = PHONE_RE.sub("", raw.strip())
    if not digits_only:
        return None

    # Strip + and leading zeros
    digits_only = digits_only.lstrip("+").lstrip("0")

    # Indian 10-digit mobile: starts with 6/7/8/9, auto-add +91
    if len(digits_only) == 10 and digits_only[0] in "6789":
        return f"+91{digits_only}"

    # Already has 91 prefix (12 digits): 919876543210 → +919876543210
    if len(digits_only) == 12 and digits_only.startswith("91") and digits_only[2] in "6789":
        return f"+{digits_only}"

    # Has explicit + or other country code — keep as-is
    if raw.strip().startswith("+"):
        result = f"+{digits_only}"
        if 8 <= len(digits_only) <= 15:
            return result
        return None

    # Fallback: add + and validate length
    if 8 <= len(digits_only) <= 15:
        return f"+{digits_only}"
    return None


def _clean_text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


# Meta error codes that recur across broadcasts — mapped before keyword matching.
_META_CODE_REASONS: dict[int, str] = {
    131058: "test_template_only",       # hello_world etc. — only from Public Test Numbers
    131049: "ecosystem_cap",            # per-user marketing cap (async; not a send-time fail)
    131047: "re_engagement_required",   # 24h window closed, needs template
    131030: "recipient_not_allowed",    # number not in dev/test allow-list
    131026: "undeliverable",            # no WhatsApp / cannot receive
    133010: "number_not_registered",    # sender number not registered on Cloud API
    190:    "token_invalid",            # OAuth token expired/invalid
    200:    "permission_denied",        # token missing whatsapp permission
    10:     "permission_denied",
    100:    "bad_request",              # malformed param / object id
}


def _meta_error_code(error_msg: str) -> int | None:
    """Pull the numeric Meta error code out of a raw error string / JSON blob."""
    if not error_msg:
        return None
    m = re.search(r'"code"\s*:\s*(\d+)', error_msg) or re.search(r"\(#(\d+)\)", error_msg)
    return int(m.group(1)) if m else None


def _meta_error_detail(error_msg: str) -> str:
    """Human-readable Meta error for the failed CSV — '(#code) message', else trimmed raw."""
    if not error_msg:
        return ""
    msg = None
    m = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', error_msg)
    if m:
        msg = m.group(1).encode().decode("unicode_escape")
    if not msg:
        msg = error_msg.strip()
    msg = re.sub(r"^\d{3}:\s*", "", msg)  # strip leading "400: " from HTTPException str
    return msg[:300]


def _map_meta_error(error_msg: str) -> str:
    """Map Meta API error message to a short failure reason code."""
    code = _meta_error_code(error_msg)
    if code in _META_CODE_REASONS:
        return _META_CODE_REASONS[code]
    error_lower = (error_msg or "").lower()
    if "invalid_phone" in error_lower or "invalid phone" in error_lower or ("phone number" in error_lower and "invalid" in error_lower):
        return "invalid_number"
    if "not_found" in error_lower or ("recipient" in error_lower and "not" in error_lower):
        return "recipient_not_found"
    if "rate" in error_lower and "limit" in error_lower:
        return "rate_limit"
    if "template" in error_lower and "paused" in error_lower:
        return "template_paused"
    if "template" in error_lower and "rejected" in error_lower:
        return "template_rejected"
    if "parameter" in error_lower or "param" in error_lower:
        return "template_params_invalid"
    if "message" in error_lower and "not sent" in error_lower:
        return "message_not_sent"
    if "blocked" in error_lower:
        return "user_blocked"
    if "undeliverable" in error_lower or "undelivered" in error_lower:
        return "undeliverable"
    if "session" in error_lower and "expired" in error_lower:
        return "session_expired"
    if "unsupported" in error_lower and "message" in error_lower:
        return "unsupported_message"
    return "api_error"


def _to_float(value: str | None) -> float | None:
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid numeric value: {text}")


def _value_for(row: dict, fieldmap: dict[str, str], key: str, fallback: str | None = None) -> str | None:
    csv_key = fieldmap.get(key)
    if csv_key:
        return _clean_text(row.get(csv_key))
    return _clean_text(fallback)


@router.post("/leads")
async def upload_leads(
    file: UploadFile = File(...),
    campaign_message: str | None = Form(None),
    segment_override: str | None = Form(None),
    platform: str | None = Form(None),
    campaign_name: str | None = Form(None),
    external_campaign_id: str | None = Form(None),
    ad_set_name: str | None = Form(None),
    external_ad_set_id: str | None = Form(None),
    ad_name: str | None = Form(None),
    external_ad_id: str | None = Form(None),
    utm_source: str | None = Form(None),
    utm_campaign: str | None = Form(None),
    utm_content: str | None = Form(None),
    spend_inr: str | None = Form(None),
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    if segment_override and segment_override not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=400, detail="segment_override must be A/B/C/D")

    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "phone" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(status_code=400, detail="CSV must contain a 'phone' column")

    db = get_supabase()
    initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
    fieldmap = {f.strip().lower(): f for f in reader.fieldnames}
    rows_by_phone: dict[str, dict] = {}
    campaign_cache: dict[tuple[str | None, str | None, str | None, float | None], dict | None] = {}
    spend_default = _to_float(spend_inr)
    for row in reader:
        phone = _normalize_phone(row.get(fieldmap.get("phone", "phone"), ""))
        if not phone:
            continue
        name_key = fieldmap.get("name")
        row_platform = _value_for(row, fieldmap, "platform", platform)
        row_campaign_name = _value_for(row, fieldmap, "campaign_name", campaign_name)
        row_external_campaign_id = _value_for(row, fieldmap, "external_campaign_id", external_campaign_id)
        row_ad_set_name = _value_for(row, fieldmap, "ad_set_name", ad_set_name)
        row_external_ad_set_id = _value_for(row, fieldmap, "external_ad_set_id", external_ad_set_id)
        row_ad_name = _value_for(row, fieldmap, "ad_name", ad_name)
        row_external_ad_id = _value_for(row, fieldmap, "external_ad_id", external_ad_id)
        row_utm_source = _value_for(row, fieldmap, "utm_source", utm_source)
        row_utm_campaign = _value_for(row, fieldmap, "utm_campaign", utm_campaign)
        row_utm_content = _value_for(row, fieldmap, "utm_content", utm_content)
        row_spend = _to_float(_value_for(row, fieldmap, "spend_inr", spend_inr)) if fieldmap.get("spend_inr") else spend_default

        payload = {
            "phone": phone,
            "name": (row.get(name_key) or "").strip() or None if name_key else None,
            "source": "upload",
            "score": initial_score,
            "segment": segment_override or initial_segment,
            "tenant_id": tenant_id,
        }
        campaign_key = (row_platform, row_campaign_name, row_external_campaign_id, row_spend)
        campaign = None
        if any(campaign_key[:3]):
            if campaign_key not in campaign_cache:
                campaign_cache[campaign_key] = get_or_create_campaign(
                    db,
                    platform=row_platform,
                    campaign_name=row_campaign_name,
                    external_campaign_id=row_external_campaign_id,
                    spend_inr=row_spend,
                    tenant_id=tenant_id,
                )
            campaign = campaign_cache[campaign_key]
        if campaign:
            payload.update(
                {
                    "ad_campaign_id": campaign["id"],
                    "ad_set_name": row_ad_set_name,
                    "external_ad_set_id": row_external_ad_set_id,
                    "ad_name": row_ad_name,
                    "external_ad_id": row_external_ad_id,
                    "utm_source": row_utm_source,
                    "utm_campaign": row_utm_campaign,
                    "utm_content": row_utm_content,
                }
            )
        rows_by_phone[phone] = payload

    if not rows_by_phone:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV")

    phones = list(rows_by_phone.keys())
    existing = db.table("leads").select("phone").in_("phone", phones).eq("tenant_id", tenant_id).is_("deleted_at", "null").execute()
    existing_set = {r["phone"] for r in (existing.data or [])}

    soft_deleted = db.table("leads").select("phone,id").in_("phone", phones).eq("tenant_id", tenant_id).not_.is_("deleted_at", "null").execute()
    if soft_deleted.data:
        soft_deleted_phones = [r["phone"] for r in soft_deleted.data]
        db.table("leads").update({"deleted_at": None, "ai_enabled": True}).in_("phone", soft_deleted_phones).eq("tenant_id", tenant_id).execute()
        for phone in soft_deleted_phones:
            if phone in existing_set:
                existing_set.remove(phone)

    to_insert = [rows_by_phone[p] for p in phones if p not in existing_set]
    inserted = 0
    attributed = 0
    for i in range(0, len(to_insert), 100):
        batch = to_insert[i : i + 100]
        result = db.table("leads").insert(batch).execute()
        inserted += len(result.data or [])
        for lead in (result.data or []):
            if lead.get("ad_campaign_id"):
                attributed += 1
            record_stage_event(
                lead["id"],
                to_segment=lead.get("segment") or "C",
                event_type="created",
                metadata={"source": "upload"},
                tenant_id=lead.get("tenant_id") or tenant_id,
                db=db,
            )
            sync_follow_up_jobs(
                lead["id"],
                segment=lead.get("segment"),
                phone=lead.get("phone"),
                converted_at=lead.get("converted_at"),
                ai_enabled=lead.get("ai_enabled", True),
                reason="upload",
                tenant_id=lead.get("tenant_id") or tenant_id,
                db=db,
            )

    sent = 0
    failed = 0
    if campaign_message:
        for phone in phones:
            sid = await send_whatsapp(phone, campaign_message, tenant_id=tenant_id)
            if sid:
                sent += 1
                lead = db.table("leads").select("id").eq("phone", phone).eq("tenant_id", tenant_id).limit(1).execute()
                if lead.data:
                    db.table("messages").insert({
                        "lead_id": lead.data[0]["id"],
                        "tenant_id": tenant_id,
                        "direction": "outbound",
                        "channel": "whatsapp",
                        "content": campaign_message,
                        "is_ai_generated": False,
                        "meta_message_id": sid,
                    }).execute()
            else:
                failed += 1

    return {
        "total": len(phones),
        "inserted": inserted,
        "skipped": len(phones) - inserted,
        "attributed": min(attributed, inserted),
        "campaign_sent": sent,
        "campaign_failed": failed,
    }


_OPTIN_MAP = {
    "click_to_wa_ad": ("marketing", True),
    "website_form": ("marketing", True),
    "offline_event": ("utility", True),
    "previous_enquiry": ("utility", True),
    "imported": ("utility", True),
    "manual": ("blocked", False),
}

_OPTIN_MESSAGES = {
    "marketing": "Leads from this source can receive WhatsApp marketing templates.",
    "utility": "Leads from this source can receive WhatsApp utility templates.",
    "blocked": "Leads without explicit consent cannot receive WhatsApp messages. Use call-only outreach.",
}


class OptInRequest(BaseModel):
    opt_in_source: str


class BulkLeadItem(BaseModel):
    phone: str
    name: Optional[str] = None
    opt_in_source: Optional[str] = None
    extra_cols: dict[str, str] = {}  # all CSV columns keyed by header name


class BulkSendRequest(BaseModel):
    leads: list[BulkLeadItem]
    template_name: str
    schedule_type: str
    schedule_at: Optional[str] = None
    drip_days: Optional[int] = None
    drip_send_time: Optional[str] = None  # HH:MM in IST, e.g. "10:00"
    csv_file_url: Optional[str] = None
    csv_file_path: Optional[str] = None
    csv_file_name: Optional[str] = None
    variable_mapping: list[str] = []  # ordered CSV column names for {{1}}, {{2}}, ...
    tag_id: Optional[str] = None  # broadcast tag for per-product interest tracking
    exclude_negative_replies: bool = False  # skip leads who previously rejected a broadcast
    include_opted_out: bool = False  # send to opted-out leads if True


class RiskAuditRequest(BaseModel):
    leads: list[BulkLeadItem]
    tag_id: Optional[str] = None


def _validate_csv_storage_path(path: str, tenant_id: str) -> str:
    clean_path = path.strip().lstrip("/")
    if not clean_path or not clean_path.startswith(f"{tenant_id}/"):
        raise HTTPException(status_code=403, detail="CSV path is outside this tenant")
    return clean_path


def _create_csv_signed_url(db, path: str, expires_in: int = 300) -> str | None:
    result = db.storage.from_("broadcast-csvs").create_signed_url(path, expires_in)
    if isinstance(result, dict):
        return (
            result.get("signedURL")
            or result.get("signedUrl")
            or result.get("signed_url")
            or result.get("url")
        )
    return (
        getattr(result, "signed_url", None)
        or getattr(result, "signedURL", None)
        or getattr(result, "url", None)
    )


def _insert_scheduled_broadcast(db, record: dict) -> None:
    try:
        db.table("scheduled_broadcasts").insert(record).execute()
    except Exception as exc:
        if "csv_file_path" not in record or "csv_file_path" not in str(exc):
            raise
        fallback = dict(record)
        fallback.pop("csv_file_path", None)
        db.table("scheduled_broadcasts").insert(fallback).execute()


def _insert_scheduled_broadcasts(db, records: list[dict]) -> None:
    try:
        db.table("scheduled_broadcasts").insert(records).execute()
    except Exception as exc:
        if not records or "csv_file_path" not in records[0] or "csv_file_path" not in str(exc):
            raise
        fallback = []
        for record in records:
            clean_record = dict(record)
            clean_record.pop("csv_file_path", None)
            fallback.append(clean_record)
        db.table("scheduled_broadcasts").insert(fallback).execute()


@router.post("/parse")
async def parse_csv(file: UploadFile = File(...), tenant_id: str = Depends(get_tenant_id)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    raw_bytes = await file.read()
    raw = raw_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    columns = [f.strip() for f in reader.fieldnames]
    suggested_mapping: dict[str, str | None] = {"name": None, "phone": None, "email": None, "course": None}
    for col in columns:
        col_lower = col.lower()
        for key in suggested_mapping:
            if key in col_lower and suggested_mapping[key] is None:
                suggested_mapping[key] = col

    db = get_supabase()
    existing_resp = db.table("leads").select("phone").eq("tenant_id", tenant_id).is_("deleted_at", "null").execute()
    existing_phones = {r["phone"] for r in (existing_resp.data or []) if r.get("phone")}

    rows = list(reader)
    total_rows = len(rows)
    duplicate_count = 0
    preview: list[dict] = []

    phone_col = suggested_mapping.get("phone")
    for row in rows:
        raw_phone = row.get(phone_col, "") if phone_col else ""
        normalized = _normalize_phone(raw_phone or "")
        if normalized and normalized in existing_phones:
            duplicate_count += 1
        if len(preview) < 5:
            preview.append({k.strip(): v for k, v in row.items()})

    csv_file_url = None
    csv_file_path = None
    csv_file_name = file.filename
    try:
        import uuid
        safe_filename = file.filename.replace(" ", "_") if file.filename else "upload.csv"
        storage_path = f"{tenant_id}/{uuid.uuid4().hex[:8]}_{safe_filename}"
        db.storage.from_("broadcast-csvs").upload(storage_path, raw_bytes, {"content-type": "text/csv"})
        csv_file_path = storage_path
        csv_file_url = _create_csv_signed_url(db, storage_path)
    except Exception as storage_err:
        logger.exception("Failed to upload CSV to storage")

    return {
        "columns": columns,
        "suggested_mapping": suggested_mapping,
        "total_rows": total_rows,
        "duplicate_count": duplicate_count,
        "preview": preview,
        "csv_file_url": csv_file_url,
        "csv_file_path": csv_file_path,
        "csv_file_name": csv_file_name,
    }


_SCAN_EXTENSIONS = (".jpg", ".jpeg", ".png", ".pdf")


@router.post("/scan")
async def scan_contacts(file: UploadFile = File(...), tenant_id: str = Depends(get_tenant_id)):
    """OCR a photographed/scanned notebook page (or PDF) of names and phone numbers
    into CSV text, so the client can hand it straight into the existing /parse ->
    upload pipeline unchanged. Extraction-only -- never inserts a lead, so this stays
    at the router's base require_outbound_read level; the actual insert routes
    (/leads, telecalling-upload/upload) keep their own stricter permission checks."""
    filename = (file.filename or "").lower()
    content_type = file.content_type or ""
    if not filename.endswith(_SCAN_EXTENSIONS) and not (content_type.startswith("image/") or content_type == "application/pdf"):
        raise HTTPException(status_code=400, detail="File must be a .jpg, .png, or .pdf scan")

    raw_bytes = await file.read()
    mime_type = "application/pdf" if filename.endswith(".pdf") or content_type == "application/pdf" else (content_type or "image/jpeg")

    try:
        raw_csv = await asyncio.to_thread(gemini_extract_contacts_csv, raw_bytes, mime_type, tenant_id=tenant_id)
    except Exception:
        logger.exception("Failed to OCR contact scan")
        raise HTTPException(status_code=502, detail="Could not read this scan. Try a clearer photo.")

    cleaned = raw_csv.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned).strip()

    reader = csv.DictReader(io.StringIO(cleaned))
    if not reader.fieldnames or "phone" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(status_code=422, detail="Could not find any phone numbers in this scan")

    fieldmap = {f.strip().lower(): f for f in reader.fieldnames}
    phone_col = fieldmap.get("phone", "phone")
    name_col = fieldmap.get("name")

    rows: list[dict] = []
    for row in reader:
        normalized = _normalize_phone(row.get(phone_col, "") or "")
        if not normalized:
            continue
        name = (row.get(name_col) or "").strip() if name_col else ""
        rows.append({"name": name, "phone": normalized})

    if not rows:
        raise HTTPException(status_code=422, detail="Could not find any valid phone numbers in this scan")

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["name", "phone"])
    writer.writeheader()
    writer.writerows(rows)

    return {"csv_text": out.getvalue(), "rows_found": len(rows)}


@router.get("/csv-signed-url")
async def get_csv_signed_url(
    path: str = Query(..., description="Tenant-scoped broadcast CSV storage path"),
    tenant_id: str = Depends(get_tenant_id),
):
    db = get_supabase()
    storage_path = _validate_csv_storage_path(path, tenant_id)
    signed_url = _create_csv_signed_url(db, storage_path)
    if not signed_url:
        raise HTTPException(status_code=404, detail="CSV file is not available")
    return {"url": signed_url, "expires_in": 300}


@router.post("/validate-optin")
async def validate_optin(body: OptInRequest):
    source = (body.opt_in_source or "").strip().lower()
    template_type, allowed = _OPTIN_MAP.get(source, ("blocked", False))
    return {
        "allowed": allowed,
        "template_type": template_type,
        "message": _OPTIN_MESSAGES.get(template_type, "Unknown opt-in source."),
    }


@router.post("/risk-audit")
async def risk_audit(body: RiskAuditRequest, tenant_id: str = Depends(get_tenant_id)):
    """Return risk counts for a set of leads before a broadcast is confirmed."""
    db = get_supabase()
    all_phones = [_normalize_phone(l.phone or "") for l in body.leads if _normalize_phone(l.phone or "")]

    negative_reply_count = 0
    high_no_reply_count = 0
    opted_out_count = 0
    tag_opted_out_count = 0

    if all_phones:
        neg_rows = (
            db.table("leads")
            .select("phone")
            .in_("phone", all_phones)
            .eq("tenant_id", tenant_id)
            .not_.is_("broadcast_negative_reply_at", "null")
            .execute()
        )
        negative_reply_count = len(neg_rows.data or [])

        no_reply_rows = (
            db.table("leads")
            .select("phone")
            .in_("phone", all_phones)
            .eq("tenant_id", tenant_id)
            .gte("outbound_no_reply_count", 2)
            .is_("broadcast_negative_reply_at", "null")
            .execute()
        )
        high_no_reply_count = len(no_reply_rows.data or [])

        opt_rows = (
            db.table("leads")
            .select("phone")
            .in_("phone", all_phones)
            .eq("tenant_id", tenant_id)
            .eq("opted_out", True)
            .execute()
        )
        globally_opted_out_phones: set[str] = {r["phone"] for r in (opt_rows.data or []) if r.get("phone")}
        opted_out_count = len(globally_opted_out_phones)

        tag_opted_out_phones: set[str] = set()
        try:
            if body.tag_id:
                tag_rows = (
                    db.table("lead_tag_opt_outs")
                    .select("leads!inner(phone)")
                    .eq("tenant_id", tenant_id)
                    .eq("tag_id", body.tag_id)
                    .in_("leads.phone", all_phones)
                    .execute()
                )
                tag_opted_out_phones = {r["leads"]["phone"] for r in (tag_rows.data or []) if r.get("leads")}
            glob_rows = (
                db.table("lead_tag_opt_outs")
                .select("leads!inner(phone)")
                .eq("tenant_id", tenant_id)
                .is_("tag_id", "null")
                .in_("leads.phone", all_phones)
                .execute()
            )
            for r in (glob_rows.data or []):
                if r.get("leads"):
                    tag_opted_out_phones.add(r["leads"]["phone"])
        except Exception as e:
            logger.warning(f"risk_audit per-tag opt-out lookup failed: {e}")
        tag_opted_out_count = len(tag_opted_out_phones)

        total_opted_out_count = len(tag_opted_out_phones | globally_opted_out_phones)
    else:
        total_opted_out_count = 0

    total = len(all_phones)
    safe_count = total - negative_reply_count - high_no_reply_count - total_opted_out_count

    return {
        "total": total,
        "negative_reply_count": negative_reply_count,
        "high_no_reply_count": high_no_reply_count,
        "opted_out_count": opted_out_count,
        "tag_opted_out_count": tag_opted_out_count,
        "total_opted_out_count": total_opted_out_count,
        "safe_count": max(0, safe_count),
    }


async def _execute_immediate_send(
    *,
    tenant_id: str,
    broadcast_id: str,
    broadcast_timestamp: datetime,
    body: "BulkSendRequest",
    eligible: list,
    rejected: list,
    invalid_leads: list,
    all_phones: list,
    phone_to_lead_id: dict,
    phone_to_lead_name: dict,
    all_opted_out_phones: set,
    tag_opted_out_phones: set,
    globally_opted_out_phones: set,
    negative_reply_phones: set,
    tpl_body: str,
    tpl_lang: str,
    _has_fail_reason: bool,
) -> None:
    """Background worker for an immediate 'Send Now' broadcast. bulk_send() has already
    returned {"status": "queued", ...} to the client by the time this runs — progress is
    polled via GET /broadcast/{id}/progress, and Stop hits POST /broadcast/{id}/abort."""
    db = get_supabase()
    sent = 0
    failed = 0
    opted_out_skipped = 0
    recipient_rows = []
    aborted = False
    deferred_leads: list = []
    picker = SenderPicker(tenant_id)
    idx = 0

    try:
        for idx, lead in enumerate(eligible):
            if idx % 5 == 0:
                try:
                    row_now = (
                        db.table("scheduled_broadcasts")
                        .select("abort_requested")
                        .eq("id", broadcast_id)
                        .maybe_single()
                        .execute()
                    )
                    if row_now and row_now.data and row_now.data.get("abort_requested"):
                        aborted = True
                        break
                    db.table("scheduled_broadcasts").update({
                        "result": json.dumps({
                            "sent": sent, "failed": failed,
                            "opted_out_skipped": opted_out_skipped, "total": len(eligible),
                        }),
                    }).eq("id", broadcast_id).execute()
                except Exception:
                    pass

            phone = _normalize_phone(lead.phone or "")
            if not phone:
                continue

            lead_id = phone_to_lead_id.get(phone)
            lead_name = phone_to_lead_name.get(phone)

            if phone in all_opted_out_phones and not body.include_opted_out:
                opted_out_skipped += 1
                row = {
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": lead_id,
                    "phone": phone,
                    "name": lead_name,
                    "send_status": "opted_out_skip",
                    "tag_id": body.tag_id,
                }
                if _has_fail_reason:
                    if phone in tag_opted_out_phones and phone not in globally_opted_out_phones:
                        row["fail_reason"] = "tag_opted_out"
                    elif phone in globally_opted_out_phones and phone not in tag_opted_out_phones:
                        row["fail_reason"] = "globally_opted_out"
                    else:
                        row["fail_reason"] = "opted_out"
                recipient_rows.append(row)
                if phone in globally_opted_out_phones:
                    logger.info(f"Bulk-send skipped globally-opted-out lead (id={lead_id})")
                else:
                    logger.info(f"Bulk-send skipped tag-opted-out lead (id={lead_id}) for tag {body.tag_id}")
                continue

            if phone in negative_reply_phones:
                failed += 1
                row = {
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": lead_id,
                    "phone": phone,
                    "name": lead_name,
                    "send_status": "opted_out_skip",
                    "tag_id": body.tag_id,
                }
                if _has_fail_reason:
                    row["fail_reason"] = "negative_reply_excluded"
                recipient_rows.append(row)
                logger.info(f"Bulk-send skipped negative-reply lead {phone}")
                continue

            sender = picker.next()
            if sender is None:
                # Every number is at today's cap, or none may broadcast (Red
                # with no standby): the rest goes out tomorrow morning.
                deferred_leads = eligible[idx:]
                break

            try:
                components: list[dict] = []
                params = body_parameters(tpl_body, body.variable_mapping, lead.extra_cols, _clean_text(lead.name))
                if params:
                    components = [{"type": "body", "parameters": params}]

                send_result = await send_template_message(
                    to_number=phone,
                    template_name=body.template_name,
                    lang_code=tpl_lang,
                    components=components,
                    phone_number_id=sender.get("meta_phone_number_id"),
                    tenant_id=tenant_id,
                )
                await picker.record_sent(sender)
                sent += 1

                meta_msg_id: str | None = None
                try:
                    meta_msg_id = send_result.get("messages", [{}])[0].get("id")
                except Exception:
                    pass

                recipient_rows.append({
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": lead_id,
                    "phone": phone,
                    "name": lead_name,
                    "send_status": "sent",
                    "tag_id": body.tag_id,
                    "meta_message_id": meta_msg_id,
                    "extra_cols": (lead.extra_cols or None),
                })

                if lead_id:
                    try:
                        msg_row = {
                            "lead_id": lead_id,
                            "tenant_id": tenant_id,
                            "direction": "outbound",
                            "channel": "whatsapp",
                            "content": f"[Template: {body.template_name}]",
                            "is_ai_generated": False,
                        }
                        if meta_msg_id:
                            msg_row["meta_message_id"] = meta_msg_id
                        db.table("messages").insert(msg_row).execute()
                    except Exception as db_err:
                        logger.error(f"messages insert failed for {phone}: {db_err}")
            except Exception as e:
                fail_reason = _map_meta_error(str(e))
                logger.error(f"Bulk-send failed for {phone}: {e}")
                failed += 1
                row = {
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": lead_id,
                    "phone": phone,
                    "name": lead_name,
                    "send_status": "failed",
                    "tag_id": body.tag_id,
                }
                if _has_fail_reason:
                    row["fail_reason"] = fail_reason
                row["fail_detail"] = _meta_error_detail(str(e))
                recipient_rows.append(row)

        if aborted:
            for skipped_lead in eligible[idx:]:
                phone = _normalize_phone(skipped_lead.phone or "")
                recipient_rows.append({
                    "tenant_id": tenant_id,
                    "broadcast_id": broadcast_id,
                    "lead_id": phone_to_lead_id.get(phone),
                    "phone": phone,
                    "name": phone_to_lead_name.get(phone),
                    "send_status": "aborted_skip",
                    "tag_id": body.tag_id,
                })

        # Track invalid phone numbers separately so they appear in failed CSV
        for inv_lead in invalid_leads:
            raw_phone = (inv_lead.phone or "").strip()
            if not raw_phone:
                raw_phone = "N/A"
            row = {
                "tenant_id": tenant_id,
                "broadcast_id": broadcast_id,
                "lead_id": None,
                "phone": raw_phone,
                "name": _clean_text(inv_lead.name),
                "send_status": "failed",
                "tag_id": body.tag_id,
            }
            if _has_fail_reason:
                row["fail_reason"] = "invalid_number"
            recipient_rows.append(row)
            failed += 1

        for rej_lead in rejected:
            phone = _normalize_phone(rej_lead.phone or "")
            if not phone:
                continue
            lead_id = phone_to_lead_id.get(phone)
            if not lead_id:
                continue
            lead_name = phone_to_lead_name.get(phone)
            row = {
                "tenant_id": tenant_id,
                "broadcast_id": broadcast_id,
                "lead_id": lead_id,
                "phone": phone,
                "name": lead_name,
                "send_status": "rejected",
                "tag_id": body.tag_id,
            }
            if _has_fail_reason:
                row["fail_reason"] = "opt_in_source_missing"
            recipient_rows.append(row)

        if recipient_rows:
            for i in range(0, len(recipient_rows), 100):
                batch = recipient_rows[i:i+100]
                try:
                    db.table("broadcast_recipients").insert(batch).execute()
                except Exception as br_err:
                    logger.error(f"broadcast_recipients insert failed: {br_err}")

            if sent > 0:
                initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
                bls_rows = [
                    {
                        "tenant_id": tenant_id,
                        "broadcast_id": broadcast_id,
                        "lead_id": r["lead_id"],
                        "tag_id": body.tag_id,
                        "score": initial_score,
                        "segment": initial_segment,
                        "arc_score": initial_score,
                        "arc_message_count": 0,
                        "broadcast_sent_at": broadcast_timestamp.isoformat(),
                    }
                    for r in recipient_rows
                    if r.get("send_status") == "sent" and r.get("lead_id")
                ]
                if bls_rows:
                    for i in range(0, len(bls_rows), 100):
                        try:
                            db.table("broadcast_lead_scores").upsert(
                                bls_rows[i:i+100],
                                on_conflict="broadcast_id,lead_id",
                            ).execute()
                        except Exception as bls_err:
                            logger.error(f"broadcast_lead_scores seed failed: {bls_err}")

        if deferred_leads:
            try:
                _insert_scheduled_broadcast(db, {
                    "tenant_id": tenant_id,
                    "template_name": body.template_name,
                    "schedule_type": "scheduled",
                    "fire_at": next_send_time(tenant_id).isoformat(),
                    "leads_json": [l.model_dump() for l in deferred_leads],
                    "recipient_count": len(deferred_leads),
                    "variable_mapping": body.variable_mapping,
                    "opt_in_source": _clean_text(deferred_leads[0].opt_in_source) or "unknown",
                    "csv_file_url": body.csv_file_url,
                    "csv_file_path": body.csv_file_path,
                    "csv_file_name": body.csv_file_name,
                })
                logger.info(f"Immediate broadcast {broadcast_id}: {len(deferred_leads)} lead(s) deferred to tomorrow")
            except Exception:
                logger.exception(f"Immediate broadcast {broadcast_id}: deferring the rest failed")

        lead_ids = [phone_to_lead_id.get(p) for p in all_phones if phone_to_lead_id.get(p)]
        delivered_count = 0
        opened_count = 0

        if lead_ids:
            try:
                window_start = (broadcast_timestamp - timedelta(minutes=2)).isoformat()
                window_end = (broadcast_timestamp + timedelta(minutes=10)).isoformat()

                delivered_rows = db.table("messages") \
                    .select("id") \
                    .in_("lead_id", lead_ids) \
                    .eq("direction", "outbound") \
                    .eq("delivery_status", "delivered") \
                    .gte("created_at", window_start) \
                    .lte("created_at", window_end) \
                    .execute()
                delivered_count = len(delivered_rows.data or [])

                opened_rows = db.table("messages") \
                    .select("id") \
                    .in_("lead_id", lead_ids) \
                    .eq("direction", "outbound") \
                    .eq("delivery_status", "read") \
                    .gte("created_at", window_start) \
                    .lte("created_at", window_end) \
                    .execute()
                opened_count = len(opened_rows.data or [])
            except Exception as e:
                logger.error(f"Failed to query delivery status: {e}")

        total_failed = failed + len(rejected)
        try:
            history_key = "broadcast_history"
            existing = (
                db.table("app_settings")
                .select("value")
                .eq("tenant_id", tenant_id)
                .eq("key", history_key)
                .maybe_single()
                .execute()
            )

            history: list[dict] = []
            if existing and existing.data and existing.data.get("value"):
                try:
                    history = json.loads(existing.data["value"])
                except Exception:
                    history = []

            opt_in_src = _clean_text(eligible[0].opt_in_source) if eligible else "unknown"

            history.insert(0, {
                "broadcast_id": broadcast_id,
                "timestamp": broadcast_timestamp.isoformat(),
                "template_name": body.template_name,
                "opt_in_source": opt_in_src or "unknown",
                "sent": sent,
                "delivered": delivered_count,
                "opened": opened_count,
                "failed": total_failed,
                "total_leads": len(eligible),
                "number_used": picker.numbers_used_label(),
                "csv_file_url": body.csv_file_url,
                "csv_file_path": body.csv_file_path,
                "csv_file_name": body.csv_file_name,
                "tag_id": body.tag_id,
            })
            history = history[:50]

            db.table("app_settings").upsert({
                "tenant_id": tenant_id,
                "key": history_key,
                "value": json.dumps(history),
            }, on_conflict="tenant_id,key").execute()
        except Exception:
            logger.exception("broadcast_history save failed")

        final_status = "aborted" if aborted else "done"
        db.table("scheduled_broadcasts").update({
            "status": final_status,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "result": json.dumps({
                "sent": sent,
                "failed": total_failed,
                "opted_out_skipped": opted_out_skipped,
                "number_used": picker.numbers_used_label(),
                "total": len(eligible),
                "deferred_to_tomorrow": len(deferred_leads),
            }),
        }).eq("id", broadcast_id).execute()
        logger.info(f"Immediate broadcast {broadcast_id}: sent={sent} failed={total_failed} aborted={aborted}")

    except Exception as exc:
        logger.exception(f"Immediate broadcast {broadcast_id} crashed: {exc}")
        try:
            db.table("scheduled_broadcasts").update({
                "status": "failed",
                "error": str(exc)[:500],
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", broadcast_id).execute()
        except Exception:
            pass


@router.post("/bulk-send")
async def bulk_send(
    body: BulkSendRequest,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    broadcast_id = str(uuid.uuid4())
    broadcast_timestamp = datetime.now(timezone.utc)

    # Only a template Meta has approved right now -- not one under review after
    # an edit, rejected or paused -- for sending now or scheduling.
    tpl_status = template_status(get_supabase(), tenant_id, body.template_name)
    if tpl_status != "APPROVED":
        raise HTTPException(
            status_code=400,
            detail=(f"{body.template_name} is waiting for Meta's review, so it can't be sent yet."
                    if tpl_status == "PENDING" else
                    f"{body.template_name} isn't approved by Meta ({(tpl_status or 'not found').title()}), so it can't be sent."),
        )

    eligible = []
    rejected = []
    invalid_leads = []
    for lead in body.leads:
        source = (lead.opt_in_source or "").strip().lower()
        if not source or source == "manual":
            rejected.append(lead)
        else:
            eligible.append(lead)

    seen_phones: set[str] = set()
    deduped: list[BulkLeadItem] = []
    for lead in eligible:
        p = _normalize_phone(lead.phone or "")
        if p and p not in seen_phones:
            seen_phones.add(p)
            deduped.append(lead)
    eligible = deduped

    if not eligible:
        raise HTTPException(status_code=400, detail="No eligible leads")

    db = get_supabase()

    # ── Exclude leads who previously rejected a broadcast ────────────────────
    if body.exclude_negative_replies:
        _all_phones_pre = [_normalize_phone(l.phone or "") for l in eligible if _normalize_phone(l.phone or "")]
        if _all_phones_pre:
            _neg = (
                db.table("leads")
                .select("phone")
                .in_("phone", _all_phones_pre)
                .eq("tenant_id", tenant_id)
                .not_.is_("broadcast_negative_reply_at", "null")
                .execute()
            )
            _neg_phones = {r["phone"] for r in (_neg.data or [])}
            eligible = [l for l in eligible if _normalize_phone(l.phone or "") not in _neg_phones]
        if not eligible:
            raise HTTPException(status_code=400, detail="No eligible leads after negative-reply exclusion")

    # ── Scheduled / Drip: store and return early ─────────────────────────────
    if body.schedule_type in ("scheduled", "drip"):
        leads_payload = [l.model_dump() for l in eligible]
        opt_in_src = _clean_text(eligible[0].opt_in_source) if eligible else "unknown"

        if body.schedule_type == "scheduled" and body.schedule_at:
            try:
                fire_at = datetime.fromisoformat(body.schedule_at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid schedule_at format")
            _insert_scheduled_broadcast(db, {
                "tenant_id": tenant_id,
                "template_name": body.template_name,
                "schedule_type": "scheduled",
                "fire_at": fire_at.isoformat(),
                "leads_json": leads_payload,
                "variable_mapping": body.variable_mapping,
                "opt_in_source": opt_in_src,
                "csv_file_url": body.csv_file_url,
                "csv_file_path": body.csv_file_path,
                "csv_file_name": body.csv_file_name,
                "created_by": _ctx.get("user_id"),
                "recipient_count": len(leads_payload),
            })
            return {"status": "scheduled", "fire_at": fire_at.isoformat(), "total": len(eligible)}

        if body.schedule_type == "drip" and body.drip_days and body.drip_days > 0:
            days = body.drip_days
            batch_size = max(1, -(-len(eligible) // days))  # ceiling division
            now = datetime.now(timezone.utc)
            ist_offset = timedelta(hours=5, minutes=30)
            now_ist = now + ist_offset

            def _drip_fire_at(day_index: int) -> str:
                if body.drip_send_time:
                    h, m = map(int, body.drip_send_time.split(":"))
                    target_ist_date = (now_ist + timedelta(days=day_index)).date()
                    naive_ist = datetime(target_ist_date.year, target_ist_date.month, target_ist_date.day, h, m)
                    utc_dt = naive_ist - ist_offset
                    return utc_dt.replace(tzinfo=timezone.utc).isoformat()
                return (now + timedelta(days=day_index)).isoformat()

            records = []
            drip_group_id = str(uuid.uuid4())  # the daily rows of one drip share this id
            for i in range(days):
                batch = eligible[i * batch_size:(i + 1) * batch_size]
                if not batch:
                    break
                records.append({
                    "tenant_id": tenant_id,
                    "template_name": body.template_name,
                    "schedule_type": "drip",
                    "fire_at": _drip_fire_at(i),
                    "leads_json": [l.model_dump() for l in batch],
                    "variable_mapping": body.variable_mapping,
                    "opt_in_source": opt_in_src,
                    "csv_file_url": body.csv_file_url,
                    "csv_file_path": body.csv_file_path,
                    "csv_file_name": body.csv_file_name,
                    "created_by": _ctx.get("user_id"),
                    "drip_group_id": drip_group_id,
                    "recipient_count": len(batch),
                })
            if records:
                _insert_scheduled_broadcasts(db, records)
            return {"status": "drip_scheduled", "batches": len(records), "total": len(eligible)}

        raise HTTPException(status_code=400, detail="schedule_at required for scheduled type, drip_days required for drip")
    # ─────────────────────────────────────────────────────────────────────────

    if await get_best_number(tenant_id) is None:
        raise HTTPException(
            status_code=503,
            detail="No number can send broadcasts right now: today's limit is used up, or your primary is Red. Add a standby number, or schedule this for tomorrow.",
        )

    # Download original CSV, add broadcast_id column, re-upload
    csv_download_url = body.csv_file_url
    if body.csv_file_path:
        try:
            csv_download_url = _create_csv_signed_url(db, _validate_csv_storage_path(body.csv_file_path, tenant_id)) or csv_download_url
        except HTTPException:
            raise
        except Exception as signed_err:
            logger.warning(f"Failed to create signed URL for CSV path {body.csv_file_path}: {signed_err}")

    if csv_download_url:
        try:
            import httpx
            csv_resp = httpx.get(csv_download_url, timeout=30)
            if csv_resp.status_code == 200:
                raw_csv = csv_resp.text
                csv_reader = csv.DictReader(io.StringIO(raw_csv))
                if csv_reader.fieldnames:
                    output = io.StringIO()
                    new_fieldnames = list(csv_reader.fieldnames) + ["broadcast_id"]
                    writer = csv.DictWriter(output, fieldnames=new_fieldnames)
                    writer.writeheader()
                    for row in csv_reader:
                        row["broadcast_id"] = broadcast_id
                        writer.writerow(row)
                    modified_csv_bytes = output.getvalue().encode("utf-8")
                    safe_filename = (body.csv_file_name or "broadcast.csv").replace(" ", "_")
                    storage_path = f"{tenant_id}/{broadcast_id[:8]}_{safe_filename}"
                    db.storage.from_("broadcast-csvs").upload(storage_path, modified_csv_bytes, {"content-type": "text/csv"})
                    body.csv_file_path = storage_path
                    body.csv_file_url = _create_csv_signed_url(db, storage_path) or body.csv_file_url
                    logger.info(f"Modified CSV uploaded with broadcast_id column: {storage_path}")
        except Exception as csv_err:
            logger.error(f"Failed to add broadcast_id to CSV: {csv_err}")

    # Every recipient's score/segment is deliberately reset to the tenant's
    # default, existing lead or not: a broadcast is often a pitch for a
    # DIFFERENT product from the same company, so it's a fresh pitch, not a
    # status update on the same conversation. (AUDIT-2026-09.md finding C5
    # tried to protect existing leads' scores here and was reverted by
    # explicit user decision for exactly this reason -- do not reintroduce
    # without checking with the user first.)
    initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
    upsert_rows = []
    for lead in eligible:
        phone = _normalize_phone(lead.phone or "")
        if not phone:
            invalid_leads.append(lead)
            continue
        upsert_rows.append({
            "phone": phone,
            "name": _clean_text(lead.name),
            "source": "upload",
            "score": initial_score,
            "segment": initial_segment,
            "tenant_id": tenant_id,
        })

    for lead in rejected:
        phone = _normalize_phone(lead.phone or "")
        if not phone:
            continue
        existing = [r for r in upsert_rows if r["phone"] == phone]
        if not existing:
            upsert_rows.append({
                "phone": phone,
                "name": _clean_text(lead.name),
                "source": "upload",
                "score": initial_score,
                "segment": initial_segment,
                "tenant_id": tenant_id,
            })

    if upsert_rows:
        db.table("leads").upsert(upsert_rows, on_conflict="tenant_id,phone").execute()
        batch_opt_in_source = _clean_text(eligible[0].opt_in_source) if eligible else "imported"
        batch_phones = [r["phone"] for r in upsert_rows]
        db.table("leads") \
            .update({"opt_in_source": batch_opt_in_source or "imported"}) \
            .in_("phone", batch_phones) \
            .eq("tenant_id", tenant_id) \
            .is_("opt_in_source", "null") \
            .execute()

    all_phones = [_normalize_phone(l.phone or "") for l in eligible + rejected + invalid_leads if _normalize_phone(l.phone or "")]
    lead_rows = db.table("leads").select("id,phone,name").in_("phone", all_phones).eq("tenant_id", tenant_id).execute()
    phone_to_lead_id = {r["phone"]: r["id"] for r in (lead_rows.data or [])}
    phone_to_lead_name = {r["phone"]: r.get("name") for r in (lead_rows.data or [])}

    tag_opted_out_phones: set[str] = set()
    globally_opted_out_phones: set[str] = set()
    if all_phones and body.tag_id:
        try:
            rows = (
                db.table("lead_tag_opt_outs")
                .select("leads!inner(phone)")
                .eq("tenant_id", tenant_id)
                .eq("tag_id", body.tag_id)
                .in_("leads.phone", all_phones)
                .execute()
            )
            tag_opted_out_phones = {r["leads"]["phone"] for r in (rows.data or []) if r.get("leads")}
        except Exception as e:
            logger.warning(f"Per-tag opt-out lookup failed: {e}")

    if all_phones:
        try:
            rows = (
                db.table("lead_tag_opt_outs")
                .select("leads!inner(phone)")
                .eq("tenant_id", tenant_id)
                .is_("tag_id", "null")
                .in_("leads.phone", all_phones)
                .execute()
            )
            for r in (rows.data or []):
                if r.get("leads"):
                    tag_opted_out_phones.add(r["leads"]["phone"])
        except Exception as e:
            logger.warning(f"Global tag opt-out lookup failed: {e}")

    if all_phones:
        try:
            rows = (
                db.table("leads")
                .select("phone")
                .in_("phone", all_phones)
                .eq("tenant_id", tenant_id)
                .eq("opted_out", True)
                .execute()
            )
            globally_opted_out_phones = {r["phone"] for r in (rows.data or []) if r.get("phone")}
        except Exception as e:
            logger.warning(f"Global opted-out lead lookup failed: {e}")

    all_opted_out_phones = tag_opted_out_phones | globally_opted_out_phones

    negative_reply_phones: set[str] = set()
    if all_phones and body.exclude_negative_replies:
        neg_rows = (
            db.table("leads")
            .select("phone")
            .in_("phone", all_phones)
            .eq("tenant_id", tenant_id)
            .not_.is_("broadcast_negative_reply_at", "null")
            .execute()
        )
        negative_reply_phones = {r["phone"] for r in (neg_rows.data or [])}

    # Fetch template metadata
    tpl_lang = "en"
    tpl_body = ""
    tpl_row = (
        db.table("message_templates")
        .select("language,body_text")
        .eq("name", body.template_name)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if tpl_row.data:
        tpl_lang = tpl_row.data[0].get("language") or "en"
        tpl_body = tpl_row.data[0].get("body_text") or ""

    # Check if fail_reason column exists (migration 058 may not be applied yet)
    _has_fail_reason = False
    try:
        db.table("broadcast_recipients").select("fail_reason").limit(1).execute()
        _has_fail_reason = True
    except Exception:
        pass

    # Tracking row created up front (status='running') so /broadcast/{id}/progress and
    # /abort work from the first poll — the actual sends happen in a background task
    # below, started AFTER this request already has something to return.
    opt_in_src = _clean_text(eligible[0].opt_in_source) if eligible else "unknown"
    try:
        _insert_scheduled_broadcast(db, {
            "id": broadcast_id,
            "tenant_id": tenant_id,
            "template_name": body.template_name,
            "schedule_type": "scheduled",
            "fire_at": broadcast_timestamp.isoformat(),
            "status": "running",
            "leads_json": [],
            "variable_mapping": body.variable_mapping,
            "opt_in_source": opt_in_src or "unknown",
            "csv_file_url": body.csv_file_url,
            "csv_file_path": body.csv_file_path,
            "csv_file_name": body.csv_file_name,
            "tag_id": body.tag_id,
        })
    except Exception as sb_err:
        logger.error(f"scheduled_broadcasts tracking row insert failed: {sb_err}")

    asyncio.create_task(_execute_immediate_send(
        tenant_id=tenant_id,
        broadcast_id=broadcast_id,
        broadcast_timestamp=broadcast_timestamp,
        body=body,
        eligible=eligible,
        rejected=rejected,
        invalid_leads=invalid_leads,
        all_phones=all_phones,
        phone_to_lead_id=phone_to_lead_id,
        phone_to_lead_name=phone_to_lead_name,
        all_opted_out_phones=all_opted_out_phones,
        tag_opted_out_phones=tag_opted_out_phones,
        globally_opted_out_phones=globally_opted_out_phones,
        negative_reply_phones=negative_reply_phones,
        tpl_body=tpl_body,
        tpl_lang=tpl_lang,
        _has_fail_reason=_has_fail_reason,
    ))

    return {
        "status": "queued",
        "broadcast_id": broadcast_id,
        "total": len(eligible),
    }


class TestSendRequest(BaseModel):
    phone: str
    template_name: str
    variable_sample: Optional[dict[str, str]] = None  # {{1}}, {{2}}... sample values


class ReactivateOptOutRequest(BaseModel):
    lead_id: str
    tag_id: Optional[str] = None  # present = undo a per-tag opt-out; absent = undo global opt-out


class UpdateScheduledBroadcastRequest(BaseModel):
    template_name: Optional[str] = None
    fire_at: Optional[str] = None


@router.get("/broadcast/{broadcast_id}/progress")
async def get_broadcast_progress(broadcast_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Poll target for an in-flight 'Send Now' broadcast — status + live counts."""
    db = get_supabase()
    row = (
        db.table("scheduled_broadcasts")
        .select("status,result,error")
        .eq("id", broadcast_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not row or not row.data:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    result = row.data.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = None

    return {
        "status": row.data.get("status"),
        "error": row.data.get("error"),
        **(result or {}),
    }


@router.post("/broadcast/{broadcast_id}/abort")
async def abort_broadcast(
    broadcast_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Stop an in-flight 'Send Now' broadcast between leads. Already-sent leads stay sent."""
    db = get_supabase()
    res = (
        db.table("scheduled_broadcasts")
        .update({"abort_requested": True})
        .eq("id", broadcast_id)
        .eq("tenant_id", tenant_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=400, detail="Broadcast is not running (already finished, or not found)")
    return {"status": "abort_requested"}


@router.get("/scheduled")
async def list_scheduled_broadcasts(tenant_id: str = Depends(get_tenant_id)):
    """Pending Scheduled/Drip broadcasts that haven't fired yet."""
    db = get_supabase()
    rows = (
        db.table("scheduled_broadcasts")
        .select("id,template_name,schedule_type,fire_at,created_at,tag_id")
        .eq("tenant_id", tenant_id)
        .eq("status", "pending")
        .order("fire_at")
        .execute()
    )
    data = rows.data or []

    # Group drip batches (same template, created together) so the UI can show one
    # "drip campaign" row instead of N identical-looking rows.
    tag_ids = list({r["tag_id"] for r in data if r.get("tag_id")})
    tag_names: dict[str, str] = {}
    if tag_ids:
        tag_rows = db.table("broadcast_tags").select("id,name").in_("id", tag_ids).eq("tenant_id", tenant_id).execute()
        tag_names = {r["id"]: r["name"] for r in (tag_rows.data or [])}

    for r in data:
        r["tag_name"] = tag_names.get(r.get("tag_id"))

    return {"data": data}


@router.patch("/scheduled/{broadcast_id}")
async def update_scheduled_broadcast(
    broadcast_id: str,
    body: UpdateScheduledBroadcastRequest,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Edit a pending scheduled/drip broadcast's template or fire time before it goes out."""
    db = get_supabase()
    update: dict = {}
    if body.template_name:
        update["template_name"] = body.template_name
    if body.fire_at:
        try:
            fire_at = datetime.fromisoformat(body.fire_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid fire_at format")
        update["fire_at"] = fire_at.isoformat()
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")

    res = (
        db.table("scheduled_broadcasts")
        .update(update)
        .eq("id", broadcast_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "pending")
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=400, detail="Broadcast is not pending (already sent, cancelled, or not found)")
    return {"status": "updated"}


@router.post("/scheduled/{broadcast_id}/cancel")
async def cancel_scheduled_broadcast(
    broadcast_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Cancel a pending scheduled/drip broadcast before it fires."""
    db = get_supabase()
    res = (
        db.table("scheduled_broadcasts")
        .update({"status": "cancelled"})
        .eq("id", broadcast_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "pending")
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=400, detail="Broadcast is not pending (already sent, cancelled, or not found)")
    return {"status": "cancelled"}


@router.delete("/history/{broadcast_id}")
async def delete_history_entry(
    broadcast_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Remove one entry from the Broadcast History list (does not touch sent messages/leads)."""
    db = get_supabase()
    existing = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "broadcast_history")
        .maybe_single()
        .execute()
    )
    history: list[dict] = []
    if existing and existing.data and existing.data.get("value"):
        try:
            history = json.loads(existing.data["value"])
        except Exception:
            history = []

    before = len(history)
    history = [h for h in history if h.get("broadcast_id") != broadcast_id]
    if len(history) == before:
        raise HTTPException(status_code=404, detail="History entry not found")

    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": "broadcast_history",
        "value": json.dumps(history),
    }, on_conflict="tenant_id,key").execute()
    return {"status": "deleted"}


@router.get("/opted-out")
async def list_opted_out_leads(tenant_id: str = Depends(get_tenant_id)):
    """Every lead currently excluded from broadcasts by an opt-out — global (STOP reply,
    account-wide) or per-tag (STOP reply scoped to one product/tag's broadcasts)."""
    db = get_supabase()

    global_rows = (
        db.table("leads")
        .select("id,phone,name,opted_out_at")
        .eq("tenant_id", tenant_id)
        .eq("opted_out", True)
        .order("opted_out_at", desc=True)
        .limit(500)
        .execute()
    )
    global_out = [
        {
            "lead_id": r["id"], "phone": r.get("phone"), "name": r.get("name"),
            "opted_out_at": r.get("opted_out_at"), "scope": "global", "tag_id": None, "tag_name": None,
        }
        for r in (global_rows.data or [])
    ]

    tag_rows = (
        db.table("lead_tag_opt_outs")
        .select("lead_id,tag_id,opted_out_at,leads!inner(phone,name),broadcast_tags(name)")
        .eq("tenant_id", tenant_id)
        .not_.is_("tag_id", "null")
        .order("opted_out_at", desc=True)
        .limit(500)
        .execute()
    )
    tag_out = [
        {
            "lead_id": r["lead_id"],
            "phone": (r.get("leads") or {}).get("phone"),
            "name": (r.get("leads") or {}).get("name"),
            "opted_out_at": r.get("opted_out_at"),
            "scope": "tag",
            "tag_id": r.get("tag_id"),
            "tag_name": (r.get("broadcast_tags") or {}).get("name"),
        }
        for r in (tag_rows.data or [])
    ]

    return {"data": global_out + tag_out}


@router.post("/opted-out/reactivate")
async def reactivate_opted_out_lead(
    body: ReactivateOptOutRequest,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Manually undo an opt-out so the lead is eligible for broadcasts again.
    Only do this with the lead's actual re-consent — WhatsApp policy still applies."""
    db = get_supabase()
    if body.tag_id:
        db.table("lead_tag_opt_outs") \
            .delete() \
            .eq("tenant_id", tenant_id) \
            .eq("lead_id", body.lead_id) \
            .eq("tag_id", body.tag_id) \
            .execute()
    else:
        db.table("leads") \
            .update({"opted_out": False, "opted_out_at": None}) \
            .eq("tenant_id", tenant_id) \
            .eq("id", body.lead_id) \
            .execute()
    logger.info(f"Opt-out manually reactivated: lead={body.lead_id} tag={body.tag_id} tenant={tenant_id}")
    return {"status": "reactivated"}


@router.post("/test-send")
async def test_send(
    body: TestSendRequest,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Send one template message to a single number before dispatching to a full list.
    Does not touch leads, broadcast_recipients, or history — a pure dry-run send."""
    phone = _normalize_phone(body.phone or "")
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    db = get_supabase()
    tpl_row = (
        db.table("message_templates")
        .select("language,body_text")
        .eq("name", body.template_name)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not tpl_row.data:
        raise HTTPException(status_code=404, detail="Template not found")
    tpl_lang = tpl_row.data[0].get("language") or "en"
    tpl_body = tpl_row.data[0].get("body_text") or ""

    components: list[dict] = []
    if re.search(r"\{\{\d+\}\}", tpl_body):
        var_count = len(set(re.findall(r"\{\{(\d+)\}\}", tpl_body)))
        sample = body.variable_sample or {}
        params = [
            {"type": "text", "text": sample.get(str(i), "Test")}
            for i in range(1, var_count + 1)
        ]
        components = [{"type": "body", "parameters": params}]

    try:
        await send_template_message(
            to_number=phone,
            template_name=body.template_name,
            lang_code=tpl_lang,
            components=components,
            tenant_id=tenant_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=_meta_error_detail(str(e)) or str(e))

    return {"status": "sent", "phone": phone}


# --- Single source of truth for broadcast outcomes ---
# Both the dashboard counter (/history/refresh) and the failed-CSV download
# (/failed-csv) classify recipients here, so the numbers can never drift.


def _classify_broadcast_outcomes(
    db,
    tenant_id: str,
    broadcast_id: str,
    broadcast_timestamp_iso: str,
) -> dict:
    """
    Classify every recipient of one broadcast into sent / delivered / opened / failed
    using a single rule set.

    Returns:
        {
            "found": bool,            # False when this broadcast has no recipient rows
            "counts": {"sent", "delivered", "opened", "failed", "total"},
            "failures": list[dict],   # one row per failure, ready for CSV writer
        }

    Rules (top to bottom, first match wins):
      1. send_status in {failed, rejected}             -> failed (send error)
      2. broadcast_recipients.opted_out_at IS NOT NULL  -> failed (per-broadcast opt-out event)
      3. send_status == opted_out_skip                  -> failed (opted out at send time)
      4. messages.delivery_status == failed in window   -> failed (delivery failure)
      5. messages.delivery_status == read               -> opened (+delivered +sent)
      6. messages.delivery_status == delivered          -> delivered (+sent)
      7. everything else                                -> sent
      8. fallback: lead.opted_out_at >= recipient.created_at -> failed (webhook missed update)

    Rule 4 (legacy "lead currently opted_out=True" fallback) is intentionally NOT a rule —
    it caused cross-broadcast contamination (a lead opted out in broadcast N would falsely
    appear in broadcast N+1's failed CSV). Rules 2 and 3 are the primary opt-out paths.
    Rule 8 is a time-scoped recovery for the rare case where the webhook's
    broadcast_recipients update didn't persist; it scopes to broadcasts sent BEFORE the
    opt-out (leads.opted_out_at >= recipient.created_at) so a later opt-out cannot leak
    into an earlier broadcast's CSV.
    """
    # Check fail_reason column exists (migration 058 compat)
    has_fail_reason = True
    try:
        db.table("broadcast_recipients").select("fail_reason").limit(1).execute()
    except Exception:
        has_fail_reason = False

    # Check opted_out_at column exists (migration 085 compat)
    has_opted_out_at = True
    try:
        db.table("broadcast_recipients").select("opted_out_at").limit(1).execute()
    except Exception:
        has_opted_out_at = False

    # Check fail_detail column exists (migration 105 compat)
    has_fail_detail = True
    try:
        db.table("broadcast_recipients").select("fail_detail").limit(1).execute()
    except Exception:
        has_fail_detail = False

    base_cols = "lead_id, phone, name, send_status, created_at"
    select_cols = base_cols
    if has_fail_reason:
        select_cols += ", fail_reason"
    if has_fail_detail:
        select_cols += ", fail_detail"
    if has_opted_out_at:
        select_cols += ", opted_out_at"
    recipients_resp = db.table("broadcast_recipients") \
        .select(select_cols) \
        .eq("tenant_id", tenant_id) \
        .eq("broadcast_id", broadcast_id) \
        .execute()
    recipients = recipients_resp.data or []
    if not recipients:
        return {
            "found": False,
            "counts": {"sent": 0, "delivered": 0, "opened": 0, "failed": 0, "total": 0},
            "failures": [],
        }

    lead_ids = [r["lead_id"] for r in recipients if r.get("lead_id")]

    # Lead opt-out map (id -> opted_out_at)
    opted_out_map: dict[str, str | None] = {}
    if lead_ids:
        try:
            opted_rows = db.table("leads") \
                .select("id, opted_out_at") \
                .in_("id", lead_ids) \
                .eq("opted_out", True) \
                .execute()
            for row in (opted_rows.data or []):
                opted_out_map[row["id"]] = row.get("opted_out_at")
        except Exception as e:
            logger.warning(f"Classifier opt-out lookup failed: {e}")

    # For opted-out leads, find the SINGLE broadcast that owns the opt-out: the most
    # recent send at/before the opt-out time (across ALL the lead's broadcasts, any
    # send_status — the owning row may already be opted_out_skip). Scopes the Rule 8
    # fallback so a later opt-out never contaminates an earlier broadcast's CSV.
    owning_send_at: dict[str, datetime] = {}
    oo_lead_ids = [lid for lid, oo in opted_out_map.items() if oo]
    if oo_lead_ids:
        try:
            all_oo_rows = (
                db.table("broadcast_recipients")
                .select("lead_id, created_at")
                .eq("tenant_id", tenant_id)
                .in_("lead_id", oo_lead_ids)
                .execute()
            )
            for row in (all_oo_rows.data or []):
                lid = row.get("lead_id")
                cat = row.get("created_at")
                oo_at = opted_out_map.get(lid)
                if not lid or not cat or not oo_at:
                    continue
                try:
                    cat_dt = datetime.fromisoformat(cat.replace("Z", "+00:00"))
                    oo_dt = datetime.fromisoformat(oo_at.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
                if cat_dt <= oo_dt and (lid not in owning_send_at or cat_dt > owning_send_at[lid]):
                    owning_send_at[lid] = cat_dt
        except Exception as e:
            logger.warning(f"Classifier owning-broadcast lookup failed: {e}")

    # Delivery status per lead, attributed to THIS broadcast by the outbound
    # message NEAREST in time to the send. Picking by highest priority let an
    # adjacent broadcast's "sent" mask this broadcast's "failed". See
    # services/delivery_status.nearest_record.
    msg_status_by_lead: dict[str, str] = {}
    msg_error_by_lead: dict[str, tuple[int | None, str | None]] = {}
    try:
        ts_dt = datetime.fromisoformat(broadcast_timestamp_iso.replace("Z", "+00:00"))
        window_start = (ts_dt - timedelta(minutes=2)).isoformat()
        window_end = (ts_dt + timedelta(minutes=10)).isoformat()
        if lead_ids:
            # Try to fetch error columns (migration 061); fall back if not yet applied
            select_cols = "lead_id, delivery_status, created_at, delivery_error_code, delivery_error_title"
            try:
                msg_rows = db.table("messages") \
                    .select(select_cols) \
                    .in_("lead_id", lead_ids) \
                    .eq("direction", "outbound") \
                    .gte("created_at", window_start) \
                    .lte("created_at", window_end) \
                    .execute()
            except Exception:
                msg_rows = db.table("messages") \
                    .select("lead_id, delivery_status, created_at") \
                    .in_("lead_id", lead_ids) \
                    .eq("direction", "outbound") \
                    .gte("created_at", window_start) \
                    .lte("created_at", window_end) \
                    .execute()
            # Group all in-window outbound messages per lead, then pick the nearest.
            recs_by_lead: dict[str, list[tuple]] = {}
            for msg in (msg_rows.data or []):
                lid = msg.get("lead_id")
                status = msg.get("delivery_status")
                mts = parse_ts(msg.get("created_at"))
                if not lid or not status or mts is None:
                    continue
                recs_by_lead.setdefault(lid, []).append(
                    (mts, status, msg.get("delivery_error_code"), msg.get("delivery_error_title"))
                )
            for lid, recs in recs_by_lead.items():
                nearest = nearest_record(recs, ts_dt)
                if not nearest:
                    continue
                msg_status_by_lead[lid] = nearest[1]
                if nearest[1] == "failed":
                    code, title = nearest[2], nearest[3]
                    if code is not None or title:
                        msg_error_by_lead[lid] = (code, title)
    except Exception as e:
        logger.warning(f"Classifier delivery-status lookup failed: {e}")

    sent = delivered = opened = failed = opted_out = 0
    failures: list[dict] = []
    seen_phones: set[str] = set()

    for r in recipients:
        phone = r.get("phone") or ""
        name = r.get("name") or ""
        send_status = r.get("send_status") or ""
        lead_id = r.get("lead_id")

        reason: str | None = None
        fail_reason: str | None = None
        opted_out_at: str | None = None

        if send_status in ("failed", "rejected"):
            reason = send_status
            fail_reason = r.get("fail_reason") or "api_error"
        elif r.get("opted_out_at"):
            reason = "not_interested"
            fail_reason = r.get("fail_reason") or "opted_out"
            opted_out_at = r.get("opted_out_at")
        elif send_status == "opted_out_skip":
            row_fail_reason = r.get("fail_reason") or "opted_out"
            if row_fail_reason == "negative_reply_excluded":
                reason = "failed"
                fail_reason = row_fail_reason
            else:
                reason = "not_interested"
                fail_reason = row_fail_reason
                opted_out_at = opted_out_map.get(lead_id)
        elif lead_id and lead_id in opted_out_map and r.get("created_at") and opted_out_map[lead_id]:
            # Rule 8 (scoped fallback): the per-broadcast row wasn't stamped (Rules 2/3
            # didn't fire) but leads.opted_out is set. Attribute the opt-out to ONLY the
            # single owning broadcast (most recent send at/before the opt-out). Every
            # broadcast is an independent block — a later opt-out must not rewrite an
            # earlier broadcast, so an earlier send stays in its own segment CSV.
            own = owning_send_at.get(lead_id)
            try:
                br_dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                br_dt = None
            if own is not None and br_dt is not None and br_dt == own:
                reason = "not_interested"
                fail_reason = "opted_out"
                opted_out_at = opted_out_map[lead_id]
        # Rule 4 (legacy leads.opted_out fallback) removed: per-broadcast opted_out_at
        # (Rule 2) and send-time skip (Rule 3) cover all opt-out cases; reading the
        # global leads.opted_out flag here caused cross-broadcast contamination when
        # a prior broadcast's opt-out leaked into a later broadcast's CSV.
        if reason is None:
            delivery = msg_status_by_lead.get(lead_id) if lead_id else None
            if delivery == "failed":
                reason = "failed"
                err = msg_error_by_lead.get(lead_id)
                if err:
                    code, title = err
                    code_part = str(code) if code is not None else ""
                    title_part = title or ""
                    if code_part and title_part:
                        fail_reason = f"delivery_failed:{code_part}:{title_part}"
                    elif code_part:
                        fail_reason = f"delivery_failed:{code_part}"
                    elif title_part:
                        fail_reason = f"delivery_failed:{title_part}"
                    else:
                        fail_reason = "delivery_failed"
                else:
                    fail_reason = "delivery_failed"
            elif delivery == "read":
                sent += 1
                delivered += 1
                opened += 1
                continue
            elif delivery == "delivered":
                sent += 1
                delivered += 1
                continue
            else:
                sent += 1
                continue

        if reason == "not_interested":
            opted_out += 1
        else:
            failed += 1
        if phone and phone not in seen_phones:
            seen_phones.add(phone)
            failures.append({
                "lead_id": lead_id or "",
                "phone": phone,
                "name": name,
                "reason": reason,
                "fail_reason": fail_reason or "",
                "fail_detail": r.get("fail_detail") or "",
                "opted_out_at": opted_out_at or "",
            })

    if failures:
        sample = [{"reason": f["reason"], "fail_reason": f["fail_reason"]} for f in failures[:3]]
        logger.info(f"Classifier for broadcast {broadcast_id}: {len(failures)} non-sent outcomes — sample: {sample}")

    return {
        "found": True,
        "counts": {"sent": sent, "delivered": delivered, "opened": opened, "failed": failed, "opted_out": opted_out, "total": len(recipients)},
        "failures": failures,
    }


@router.get("/failed-csv")
async def get_failed_csv(
    broadcast_id: str = Query(..., description="Broadcast UUID to generate failed CSV for"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate a CSV of failed contacts for a broadcast."""
    db = get_supabase()

    # Look up broadcast timestamp from history for time-window queries / fallback
    broadcast_timestamp: str | None = None
    try:
        history_row = db.table("app_settings") \
            .select("value") \
            .eq("tenant_id", tenant_id) \
            .eq("key", "broadcast_history") \
            .maybe_single() \
            .execute()
        if history_row and history_row.data and history_row.data.get("value"):
            history = json.loads(history_row.data["value"])
            for record in history:
                if record.get("broadcast_id") == broadcast_id:
                    broadcast_timestamp = record.get("timestamp")
                    break
    except Exception:
        pass
    if not broadcast_timestamp:
        broadcast_timestamp = datetime.now(timezone.utc).isoformat()

    outcome = _classify_broadcast_outcomes(db, tenant_id, broadcast_id, broadcast_timestamp)

    if not outcome["found"]:
        # Fallback for broadcasts sent before migration 038 (no broadcast_recipients rows)
        # Look up the broadcast timestamp from history and find failed messages in that window
        try:
            history_row = db.table("app_settings") \
                .select("value") \
                .eq("tenant_id", tenant_id) \
                .eq("key", "broadcast_history") \
                .maybe_single() \
                .execute()
            broadcast_ts = None
            if history_row and history_row.data:
                history = json.loads(history_row.data["value"] or "[]")
                for record in history:
                    if record.get("broadcast_id") == broadcast_id:
                        broadcast_ts = record.get("timestamp")
                        break
            if broadcast_ts:
                # Get outbound messages sent within 10 minutes of broadcast start with failed delivery
                from datetime import timedelta
                ts_dt = datetime.fromisoformat(broadcast_ts.replace("Z", "+00:00"))
                window_end = (ts_dt + timedelta(minutes=10)).isoformat()
                failed_msgs = db.table("messages") \
                    .select("lead_id, created_at") \
                    .eq("tenant_id", tenant_id) \
                    .eq("direction", "outbound") \
                    .eq("delivery_status", "failed") \
                    .gte("created_at", broadcast_ts) \
                    .lte("created_at", window_end) \
                    .execute()
                if failed_msgs.data:
                    lead_ids_fb = [r["lead_id"] for r in failed_msgs.data if r.get("lead_id")]
                    leads_fb = db.table("leads").select("id,phone,name").in_("id", lead_ids_fb).eq("tenant_id", tenant_id).execute()
                    output = io.StringIO()
                    writer = csv.DictWriter(output, fieldnames=["phone", "name", "reason", "fail_reason", "fail_detail", "broadcast_id", "broadcast_timestamp"])
                    writer.writeheader()
                    for lead in (leads_fb.data or []):
                        writer.writerow({"phone": lead.get("phone", ""), "name": lead.get("name", ""), "reason": "failed", "fail_reason": "delivery_failed", "fail_detail": "", "broadcast_id": broadcast_id, "broadcast_timestamp": broadcast_ts})
                    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=failed_{broadcast_id[:8]}.csv"})
        except Exception as e:
            logger.warning(f"Fallback failed-csv lookup failed: {e}")
        # Return empty CSV instead of 404 JSON
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["phone", "name", "reason", "fail_reason", "fail_detail", "broadcast_id", "broadcast_timestamp"])
        writer.writeheader()
        return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=failed_{broadcast_id[:8]}.csv"})

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["phone", "name", "reason", "fail_reason", "fail_detail", "broadcast_id", "broadcast_timestamp"],
    )
    writer.writeheader()
    for row in outcome["failures"]:
        if row.get("reason") == "not_interested":
            continue
        writer.writerow({
            "phone": row.get("phone", ""),
            "name": row.get("name", ""),
            "reason": row.get("reason", "failed"),
            "fail_reason": row.get("fail_reason", ""),
            "fail_detail": row.get("fail_detail", ""),
            "broadcast_id": broadcast_id,
            "broadcast_timestamp": broadcast_timestamp,
        })
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=failed_{broadcast_id[:8]}.csv"},
    )


@router.get("/history")
async def get_broadcast_history(tenant_id: str = Depends(get_tenant_id)):
    """Return the last 50 broadcast records with per-broadcast hot/warm/cold counts."""
    db = get_supabase()
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "broadcast_history")
        .maybe_single()
        .execute()
    )
    history: list[dict] = []
    if row and row.data and row.data.get("value"):
        try:
            history = json.loads(row.data["value"])
        except Exception:
            history = []

    # Enrich with hot/warm/cold from broadcast_lead_scores + reply_sentiment from broadcast_recipients
    broadcast_ids = [h["broadcast_id"] for h in history if h.get("broadcast_id")]
    if broadcast_ids:
        try:
            sb_tag_rows = (
                db.table("scheduled_broadcasts")
                .select("id,tag_id")
                .eq("tenant_id", tenant_id)
                .in_("id", broadcast_ids)
                .execute()
                .data or []
            )
            tag_by_broadcast = {row["id"]: row.get("tag_id") for row in sb_tag_rows if row.get("id") and row.get("tag_id")}
            for h in history:
                if h.get("broadcast_id") in tag_by_broadcast:
                    h["tag_id"] = h.get("tag_id") or tag_by_broadcast[h["broadcast_id"]]

            tag_ids = list({h.get("tag_id") for h in history if h.get("tag_id")})
            if tag_ids:
                tag_rows = (
                    db.table("broadcast_tags")
                    .select("id,name")
                    .eq("tenant_id", tenant_id)
                    .in_("id", tag_ids)
                    .execute()
                    .data or []
                )
                tag_names = {row["id"]: row.get("name") for row in tag_rows if row.get("id")}
                for h in history:
                    tag_name = tag_names.get(h.get("tag_id"))
                    if tag_name:
                        h["tag_name"] = tag_name
        except Exception:
            pass

        try:
            score_rows = (
                db.table("broadcast_lead_scores")
                .select("broadcast_id,segment")
                .eq("tenant_id", tenant_id)
                .in_("broadcast_id", broadcast_ids)
                .execute()
                .data or []
            )
            hot_map: dict[str, int] = {}
            warm_map: dict[str, int] = {}
            cold_map: dict[str, int] = {}
            for sr in score_rows:
                bid = sr["broadcast_id"]
                seg = sr.get("segment", "C")
                if seg == "A":
                    hot_map[bid] = hot_map.get(bid, 0) + 1
                elif seg == "B":
                    warm_map[bid] = warm_map.get(bid, 0) + 1
                else:
                    cold_map[bid] = cold_map.get(bid, 0) + 1
            for h in history:
                bid = h.get("broadcast_id", "")
                h["hot"]  = hot_map.get(bid, 0)
                h["warm"] = warm_map.get(bid, 0)
                h["cold"] = cold_map.get(bid, 0)
        except Exception:
            pass

        try:
            sentiment_rows = (
                db.table("broadcast_recipients")
                .select("broadcast_id,reply_sentiment")
                .eq("tenant_id", tenant_id)
                .in_("broadcast_id", broadcast_ids)
                .not_.is_("reply_sentiment", "null")
                .execute()
                .data or []
            )
            pos_map: dict[str, int] = {}
            neg_map: dict[str, int] = {}
            neu_map: dict[str, int] = {}
            for sr in sentiment_rows:
                bid = sr["broadcast_id"]
                s = sr.get("reply_sentiment")
                if s == "positive":
                    pos_map[bid] = pos_map.get(bid, 0) + 1
                elif s == "negative":
                    neg_map[bid] = neg_map.get(bid, 0) + 1
                elif s == "neutral":
                    neu_map[bid] = neu_map.get(bid, 0) + 1
            for h in history:
                bid = h.get("broadcast_id", "")
                h["replied_positive"] = pos_map.get(bid, 0)
                h["replied_negative"] = neg_map.get(bid, 0)
                h["replied_neutral"]  = neu_map.get(bid, 0)
        except Exception:
            pass

    return {"data": history}


@router.patch("/clear-negative-reply")
async def clear_negative_reply(
    body: RiskAuditRequest,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Clear broadcast_negative_reply_at for a list of leads (re-include them in future broadcasts)."""
    db = get_supabase()
    all_phones = [_normalize_phone(l.phone or "") for l in body.leads if _normalize_phone(l.phone or "")]
    if not all_phones:
        return {"cleared": 0}
    db.table("leads").update({"broadcast_negative_reply_at": None}).in_("phone", all_phones).eq("tenant_id", tenant_id).execute()
    return {"cleared": len(all_phones)}


@router.get("/broadcast-scores-csv")
async def download_broadcast_scores_csv(
    broadcast_id: str = Query(..., description="Broadcast UUID"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Download per-lead interest CSV for a specific broadcast (product-specific scoring)."""
    db = get_supabase()

    score_rows = (
        db.table("broadcast_lead_scores")
        .select("lead_id,score,segment,arc_score,last_inbound_at,broadcast_sent_at")
        .eq("tenant_id", tenant_id)
        .eq("broadcast_id", broadcast_id)
        .execute()
        .data or []
    )

    lead_ids = [r["lead_id"] for r in score_rows if r.get("lead_id")]
    lead_map: dict[str, dict] = {}
    if lead_ids:
        leads = db.table("leads").select("id,name,phone").in_("id", lead_ids).execute()
        lead_map = {l["id"]: l for l in (leads.data or [])}

    # Resolve broadcast template name
    broadcast_name = broadcast_id[:8]
    try:
        br_row = (
            db.table("scheduled_broadcasts")
            .select("template_name")
            .eq("id", broadcast_id)
            .maybe_single()
            .execute()
        )
        if br_row and br_row.data:
            broadcast_name = br_row.data.get("template_name") or broadcast_name
    except Exception:
        pass

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "Name", "Phone", "Score", "Segment", "Arc Score",
        "Last Reply At", "Broadcast Sent At",
    ])
    writer.writeheader()
    for r in score_rows:
        lead = lead_map.get(r.get("lead_id", ""), {})
        seg = r.get("segment", "C")
        writer.writerow({
            "Name": lead.get("name", ""),
            "Phone": lead.get("phone", ""),
            "Score": r.get("score", 5),
            "Segment": seg,
            "Arc Score": r.get("arc_score", 5),
            "Last Reply At": r.get("last_inbound_at") or "",
            "Broadcast Sent At": r.get("broadcast_sent_at") or "",
        })

    safe_name = broadcast_name.replace(" ", "_").lower()
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=broadcast_{safe_name}_{date_str}.csv"},
    )


@router.get("/history-csv")
async def download_broadcast_history_csv(tenant_id: str = Depends(get_tenant_id)):
    """Download full broadcast history as CSV."""
    db = get_supabase()
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "broadcast_history")
        .maybe_single()
        .execute()
    )
    history: list[dict] = []
    if row and row.data and row.data.get("value"):
        try:
            history = json.loads(row.data["value"])
        except Exception:
            history = []

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "broadcast_id", "timestamp", "template_name", "number_used",
        "total_leads", "sent", "delivered", "opened", "failed",
    ])
    writer.writeheader()
    for record in history:
        writer.writerow({
            "broadcast_id": record.get("broadcast_id", ""),
            "timestamp": record.get("timestamp", ""),
            "template_name": record.get("template_name", ""),
            "number_used": record.get("number_used", ""),
            "total_leads": record.get("total_leads", 0),
            "sent": record.get("sent", 0),
            "delivered": record.get("delivered", 0),
            "opened": record.get("opened", 0),
            "failed": record.get("failed", 0),
        })

    from datetime import datetime
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=broadcast_history_{date_str}.csv"},
    )


def _refresh_delivered_opened_timewindow(db, record, tenant_id, window_start, window_end):
    """Update delivered/opened counts via time-window fallback (legacy/compat)."""
    delivered_rows = db.table("messages") \
        .select("id") \
        .eq("tenant_id", tenant_id) \
        .eq("direction", "outbound") \
        .eq("delivery_status", "delivered") \
        .gte("created_at", window_start) \
        .lte("created_at", window_end) \
        .execute()
    record["delivered"] = len(delivered_rows.data or [])
    
    opened_rows = db.table("messages") \
        .select("id") \
        .eq("tenant_id", tenant_id) \
        .eq("direction", "outbound") \
        .eq("delivery_status", "read") \
        .gte("created_at", window_start) \
        .lte("created_at", window_end) \
        .execute()
    record["opened"] = len(opened_rows.data or [])


@router.post("/history/refresh")
async def refresh_broadcast_metrics(
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_outbound_manage),
):
    """Re-query delivery status for all broadcasts and update history."""
    db = get_supabase()
    
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "broadcast_history")
        .maybe_single()
        .execute()
    )
    
    if not row or not row.data or not row.data.get("value"):
        return {"refreshed": 0}
    
    try:
        history = json.loads(row.data["value"])
    except Exception:
        return {"refreshed": 0}
    
    refreshed_count = 0
    
    for record in history:
        try:
            broadcast_id = record.get("broadcast_id")
            record_time = datetime.fromisoformat(record["timestamp"])
            window_start = (record_time - timedelta(minutes=2)).isoformat()
            window_end = (record_time + timedelta(minutes=10)).isoformat()
            
            if broadcast_id:
                outcome = _classify_broadcast_outcomes(db, tenant_id, broadcast_id, record["timestamp"])
                if outcome["found"]:
                    counts = outcome["counts"]
                    record["sent"] = counts["sent"]
                    record["delivered"] = counts["delivered"]
                    record["opened"] = counts["opened"]
                    record["failed"] = counts["failed"]
                else:
                    # broadcast_id exists but no recipients yet — fallback to time-window
                    _refresh_delivered_opened_timewindow(db, record, tenant_id, window_start, window_end)
            else:
                # Legacy record without broadcast_id — fallback to time-window
                _refresh_delivered_opened_timewindow(db, record, tenant_id, window_start, window_end)
            
            refreshed_count += 1
        except Exception as e:
            logger.error(f"Failed to refresh broadcast record: {e}")
            continue
    
    # Save updated history
    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": "broadcast_history",
        "value": json.dumps(history),
    }, on_conflict="tenant_id,key").execute()
    
    return {"refreshed": refreshed_count}


# ─── Tag-based CSV downloads ─────────────────────────────────────────────────

@router.get("/tag-csv")
async def download_tag_csv(
    tag_id: str = Query(..., description="Tag UUID to download CSV for"),
    segment: str = Query("", description="Filter by segment: A=hot, B=warm, C=cold, D=disqualified, empty=all"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Per-tag CSV grouped by broadcast.

    Normal segment exports include only successful sends from each broadcast under
    the tag. Segment filters use the lead's current segment so the tag section is
    live, while per-broadcast exports remain frozen to that broadcast.
    OPTED_OUT uses the same dedicated sheet format as broadcast-tag-csv.
    """
    db = get_supabase()
    seg_filter = segment.upper() if segment else ""

    br_broadcasts = (
        db.table("broadcast_recipients")
        .select("broadcast_id, created_at")
        .eq("tenant_id", tenant_id)
        .eq("tag_id", tag_id)
        .not_.is_("broadcast_id", "null")
        .order("created_at", desc=False)
        .execute()
    )

    seen_broadcasts: set[str] = set()
    ordered_broadcasts: list[dict] = []
    for row in (br_broadcasts.data or []):
        bid = row.get("broadcast_id", "")
        if bid and bid not in seen_broadcasts:
            seen_broadcasts.add(bid)
            ordered_broadcasts.append({"broadcast_id": bid, "created_at": row.get("created_at")})

    if not ordered_broadcasts:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["Name", "Phone", "Template", "Broadcast ID", "HOT", "WARM", "COLD"])
        writer.writeheader()
        return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tag_no_data.csv"})

    broadcast_ids = [b["broadcast_id"] for b in ordered_broadcasts]
    template_map: dict[str, str] = {}
    broadcast_created_at: dict[str, str] = {}
    try:
        sb_rows = (
            db.table("scheduled_broadcasts")
            .select("id, template_name, created_at")
            .in_("id", broadcast_ids)
            .execute()
        )
        for sb in (sb_rows.data or []):
            template_map[sb["id"]] = sb.get("template_name", sb["id"][:8])
            if sb.get("created_at"):
                broadcast_created_at[sb["id"]] = sb["created_at"]
    except Exception:
        pass

    output = io.StringIO()

    if seg_filter == "OPTED_OUT":
        writer = csv.DictWriter(
            output,
            fieldnames=["Name", "Phone", "Template", "From Broadcast ID", "Reason", "Opted Out At"],
        )
        writer.writeheader()

        for broadcast in ordered_broadcasts:
            bid = broadcast["broadcast_id"]
            template_name = template_map.get(bid, bid[:8])
            classify_ts = broadcast_created_at.get(bid) or broadcast.get("created_at") or datetime.now(timezone.utc).isoformat()
            outcome = _classify_broadcast_outcomes(db, tenant_id, bid, classify_ts)
            for row in (outcome.get("failures") or []):
                if row.get("reason") != "not_interested":
                    continue
                writer.writerow({
                    "Name": row.get("name", ""),
                    "Phone": row.get("phone", ""),
                    "Template": template_name,
                    "From Broadcast ID": bid,
                    "Reason": row.get("fail_reason") or "opted_out",
                    "Opted Out At": row.get("opted_out_at") or "",
                })
    else:
        writer = csv.DictWriter(output, fieldnames=["Name", "Phone", "Template", "Broadcast ID", "HOT", "WARM", "COLD"])
        writer.writeheader()

        for broadcast in ordered_broadcasts:
            bid = broadcast["broadcast_id"]
            template_name = template_map.get(bid, bid[:8])
            classify_ts = broadcast_created_at.get(bid) or broadcast.get("created_at") or datetime.now(timezone.utc).isoformat()
            outcome = _classify_broadcast_outcomes(db, tenant_id, bid, classify_ts)
            failed_lead_ids = {r.get("lead_id") for r in (outcome.get("failures") or []) if r.get("lead_id")}
            failed_phones = {r.get("phone") for r in (outcome.get("failures") or []) if r.get("phone")}

            recipients_resp = (
                db.table("broadcast_recipients")
                .select("lead_id, phone, name")
                .eq("tenant_id", tenant_id)
                .eq("tag_id", tag_id)
                .eq("broadcast_id", bid)
                .eq("send_status", "sent")
                .execute()
            )
            recipients = recipients_resp.data or []
            if not recipients:
                continue

            lead_ids = list({r["lead_id"] for r in recipients if r.get("lead_id")})

            current_segment_map: dict[str, str] = {}
            if lead_ids:
                cur_resp = db.table("leads").select("id,segment").in_("id", lead_ids).eq("tenant_id", tenant_id).execute()
                for lead in (cur_resp.data or []):
                    current_segment_map[lead["id"]] = lead.get("segment") or "C"

            seen_leads: set[str] = set()
            seen_phones: set[str] = set()
            for r in recipients:
                lead_id = r.get("lead_id") or ""
                phone = r.get("phone") or ""
                if lead_id and lead_id in seen_leads:
                    continue
                if not lead_id and phone and phone in seen_phones:
                    continue
                if lead_id:
                    seen_leads.add(lead_id)
                if phone:
                    seen_phones.add(phone)

                if (lead_id and lead_id in failed_lead_ids) or (phone and phone in failed_phones):
                    continue

                cur_seg = current_segment_map.get(lead_id, "C")
                if seg_filter:
                    if seg_filter in {"A", "B", "C", "D"} and cur_seg != seg_filter:
                        continue

                hot, warm, cold = _segment_to_flags(cur_seg)
                writer.writerow({
                    "Name": r.get("name") or "",
                    "Phone": phone,
                    "Template": template_name,
                    "Broadcast ID": bid,
                    "HOT": hot,
                    "WARM": warm,
                    "COLD": cold,
                })

    tag_name = "tag"
    try:
        tag_row = db.table("broadcast_tags").select("name").eq("id", tag_id).eq("tenant_id", tenant_id).maybe_single().execute()
        if tag_row and tag_row.data:
            tag_name = tag_row.data.get("name", "tag")
    except Exception:
        pass

    seg_label = segment.upper() if segment else "all"
    if seg_label == "D":
        seg_label = "disqualified"
    elif seg_label == "A":
        seg_label = "hot"
    elif seg_label == "B":
        seg_label = "warm"
    elif seg_label == "C":
        seg_label = "cold"
    elif seg_label == "OPTED_OUT":
        seg_label = "opted_out"
    safe_tag = tag_name.replace(" ", "_").lower()
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe_tag}_{seg_label}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
    )


def _collect_successful_tag_segment_rows(db, tenant_id: str, tags: list[dict]) -> list[dict]:
    """Rows for tag exports: successful sends only, bucketed by current lead segment."""
    seg_priority = {"A": 4, "B": 3, "C": 2, "D": 1}
    all_rows: list[dict] = []

    for tag in tags:
        tag_id = tag["id"]
        tag_name = tag.get("name", "unknown")

        br_broadcasts = (
            db.table("broadcast_recipients")
            .select("broadcast_id, created_at")
            .eq("tenant_id", tenant_id)
            .eq("tag_id", tag_id)
            .not_.is_("broadcast_id", "null")
            .order("created_at", desc=False)
            .execute()
        )

        seen_broadcasts: set[str] = set()
        ordered_broadcasts: list[dict] = []
        for row in (br_broadcasts.data or []):
            bid = row.get("broadcast_id", "")
            if bid and bid not in seen_broadcasts:
                seen_broadcasts.add(bid)
                ordered_broadcasts.append({"broadcast_id": bid, "created_at": row.get("created_at")})

        if not ordered_broadcasts:
            continue

        broadcast_ids = [b["broadcast_id"] for b in ordered_broadcasts]
        template_map: dict[str, str] = {}
        broadcast_created_at: dict[str, str] = {}
        try:
            sb_rows = (
                db.table("scheduled_broadcasts")
                .select("id, template_name, created_at")
                .in_("id", broadcast_ids)
                .execute()
            )
            for sb in (sb_rows.data or []):
                template_map[sb["id"]] = sb.get("template_name", sb["id"][:8])
                if sb.get("created_at"):
                    broadcast_created_at[sb["id"]] = sb["created_at"]
        except Exception:
            pass

        for broadcast in ordered_broadcasts:
            bid = broadcast["broadcast_id"]
            template_name = template_map.get(bid, bid[:8])
            classify_ts = broadcast_created_at.get(bid) or broadcast.get("created_at") or datetime.now(timezone.utc).isoformat()
            outcome = _classify_broadcast_outcomes(db, tenant_id, bid, classify_ts)
            failed_lead_ids = {r.get("lead_id") for r in (outcome.get("failures") or []) if r.get("lead_id")}
            failed_phones = {r.get("phone") for r in (outcome.get("failures") or []) if r.get("phone")}

            recipients_resp = (
                db.table("broadcast_recipients")
                .select("lead_id, phone, name")
                .eq("tenant_id", tenant_id)
                .eq("tag_id", tag_id)
                .eq("broadcast_id", bid)
                .eq("send_status", "sent")
                .execute()
            )
            recipients = recipients_resp.data or []
            if not recipients:
                continue

            lead_ids = list({r["lead_id"] for r in recipients if r.get("lead_id")})
            current_segment_map: dict[str, str] = {}
            if lead_ids:
                leads_resp = (
                    db.table("leads")
                    .select("id,segment")
                    .in_("id", lead_ids)
                    .eq("tenant_id", tenant_id)
                    .execute()
                )
                for lead in (leads_resp.data or []):
                    current_segment_map[lead["id"]] = lead.get("segment") or "C"

            seen_leads: set[str] = set()
            seen_phones: set[str] = set()
            for recipient in recipients:
                lead_id = recipient.get("lead_id") or ""
                phone = recipient.get("phone") or ""
                if lead_id and lead_id in seen_leads:
                    continue
                if not lead_id and phone and phone in seen_phones:
                    continue
                if lead_id:
                    seen_leads.add(lead_id)
                if phone:
                    seen_phones.add(phone)

                if (lead_id and lead_id in failed_lead_ids) or (phone and phone in failed_phones):
                    continue

                seg = current_segment_map.get(lead_id, "C")
                if seg not in seg_priority:
                    seg = "C"
                hot, warm, cold = _segment_to_flags(seg)
                all_rows.append({
                    "Name": recipient.get("name") or "",
                    "Phone": phone,
                    "Tag": tag_name,
                    "Template": template_name,
                    "Broadcast ID": bid,
                    "HOT": hot,
                    "WARM": warm,
                    "COLD": cold,
                    "_lead_id": lead_id,
                    "_tag_id": tag_id,
                    "_seg": seg,
                    "_seg_priority": seg_priority[seg],
                })

    return all_rows


@router.get("/all-tags-csv")
async def download_all_tags_csv(tenant_id: str = Depends(get_tenant_id)):
    """Download successful tag segment rows grouped by tag then broadcast."""
    db = get_supabase()

    tags_resp = db.table("broadcast_tags").select("id,name").eq("tenant_id", tenant_id).execute()
    tags = tags_resp.data or []
    if not tags:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["Name", "Phone", "Tag", "Template", "Broadcast ID", "HOT", "WARM", "COLD"])
        writer.writeheader()
        return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=all_tags_no_data.csv"})

    all_rows = _collect_successful_tag_segment_rows(db, tenant_id, tags)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Name", "Phone", "Tag", "Template", "Broadcast ID", "HOT", "WARM", "COLD"])
    writer.writeheader()

    for row in all_rows:
        writer.writerow({k: v for k, v in row.items() if not k.startswith("_")})

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=all_tags_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
    )


@router.get("/all-tags-combined")
async def download_all_tags_combined(
    mode: str = Query("all", description="all=concatenate all tags, cross=best-segment dedup per lead"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Combined CSV across all tags.

    mode=all: simple concatenation of all tags (no dedup).
    mode=cross: per-lead dedup — keeps only the row with the best segment (Hot > Warm > Cold > Disq).
    """
    db = get_supabase()

    tags_resp = db.table("broadcast_tags").select("id,name").eq("tenant_id", tenant_id).execute()
    tags = tags_resp.data or []
    if not tags:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["Name", "Phone", "Tag", "Template", "Broadcast ID", "HOT", "WARM", "COLD"])
        writer.writeheader()
        return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=all_tags_combined_no_data.csv"})

    SEG_PRIORITY = {"A": 4, "B": 3, "C": 2, "D": 1}

    # Collect all rows
    all_rows: list[dict] = []

    for tag in tags:
        tag_id = tag["id"]
        tag_name = tag.get("name", "unknown")

        br_broadcasts = (
            db.table("broadcast_recipients")
            .select("broadcast_id, created_at")
            .eq("tenant_id", tenant_id)
            .eq("tag_id", tag_id)
            .not_.is_("broadcast_id", "null")
            .order("created_at", desc=False)
            .execute()
        )

        seen_broadcasts: set[str] = set()
        ordered_broadcasts: list[dict] = []
        for row in (br_broadcasts.data or []):
            bid = row.get("broadcast_id", "")
            if bid and bid not in seen_broadcasts:
                seen_broadcasts.add(bid)
                ordered_broadcasts.append({"broadcast_id": bid})

        if not ordered_broadcasts:
            continue

        broadcast_ids = [b["broadcast_id"] for b in ordered_broadcasts]
        template_map: dict[str, str] = {}
        try:
            sb_rows = (
                db.table("scheduled_broadcasts")
                .select("id, template_name")
                .in_("id", broadcast_ids)
                .execute()
            )
            for sb in (sb_rows.data or []):
                template_map[sb["id"]] = sb.get("template_name", sb["id"][:8])
        except Exception:
            pass

        for broadcast in ordered_broadcasts:
            bid = broadcast["broadcast_id"]
            template_name = template_map.get(bid, bid[:8])

            recipients_resp = (
                db.table("broadcast_recipients")
                .select("lead_id, phone, name")
                .eq("tenant_id", tenant_id)
                .eq("broadcast_id", bid)
                .eq("send_status", "sent")
                .execute()
            )
            recipients = recipients_resp.data or []
            if not recipients:
                continue

            lead_ids = list({r["lead_id"] for r in recipients if r.get("lead_id")})

            segment_map: dict[str, str] = {}
            if lead_ids:
                bls_resp = (
                    db.table("broadcast_lead_scores")
                    .select("lead_id,segment")
                    .eq("broadcast_id", bid)
                    .in_("lead_id", lead_ids)
                    .execute()
                )
                segment_map = {r["lead_id"]: r.get("segment") or "C" for r in (bls_resp.data or [])}

            missing_ids = [lid for lid in lead_ids if lid not in segment_map]
            if missing_ids:
                leads_resp = db.table("leads").select("id,segment").in_("id", missing_ids).execute()
                for l in (leads_resp.data or []):
                    segment_map[l["id"]] = l.get("segment") or "C"

            seen_leads: set[str] = set()
            for r in recipients:
                lead_id = r.get("lead_id") or ""
                if lead_id in seen_leads:
                    continue
                seen_leads.add(lead_id)

                seg = segment_map.get(lead_id, "C")
                hot, warm, cold = _segment_to_flags(seg)

                all_rows.append({
                    "Name": r.get("name") or "",
                    "Phone": r.get("phone") or "",
                    "Tag": tag_name,
                    "Template": template_name,
                    "Broadcast ID": bid,
                    "HOT": hot,
                    "WARM": warm,
                    "COLD": cold,
                    "_lead_id": lead_id,
                    "_seg_priority": SEG_PRIORITY.get(seg.upper(), 1),
                })

    all_rows = _collect_successful_tag_segment_rows(db, tenant_id, tags)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Name", "Phone", "Tag", "Template", "Broadcast ID", "HOT", "WARM", "COLD"])
    writer.writeheader()

    if mode == "cross":
        # Best-segment dedup: per (phone, tag) keep highest priority segment
        # Actually per phone across all tags — keep only the best segment row per phone
        best_per_phone_tag: dict[tuple[str, str], dict] = {}
        for row in all_rows:
            key = (row["Phone"], row["_tag_id"])
            priority = row["_seg_priority"]
            current = best_per_phone_tag.get(key)
            if current is None or priority > current["_seg_priority"]:
                best_per_phone_tag[key] = row
            else:
                # Same priority — keep both (e.g., Hot in tag1 and Hot in tag2)
                pass

        # For cross-tag: group by phone, keep only the best segment row(s)
        # If a phone has Hot in tag1 and Cold in tag2, only show tag1
        # If a phone has Hot in tag1 and Hot in tag2, show both
        phone_best_priority: dict[str, int] = {}
        for row in best_per_phone_tag.values():
            phone = row["Phone"]
            priority = row["_seg_priority"]
            if phone not in phone_best_priority or priority > phone_best_priority[phone]:
                phone_best_priority[phone] = priority

        for row in best_per_phone_tag.values():
            if row["_seg_priority"] >= phone_best_priority[row["Phone"]]:
                clean = {k: v for k, v in row.items() if not k.startswith("_")}
                writer.writerow(clean)
    else:
        # mode=all: simple concatenation, no dedup
        for row in all_rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            writer.writerow(clean)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=all_tags_combined_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
    )


def _segment_to_flags(segment: str | None) -> tuple[int, int, int]:
    """Return (HOT, WARM, COLD) flags. D (disqualified) → all zero."""
    s = (segment or "C").upper()
    if s == "A":
        return 1, 0, 0
    if s == "B":
        return 0, 1, 0
    if s == "C":
        return 0, 0, 1
    return 0, 0, 0  # D or unknown


@router.get("/broadcast-tag-csv")
async def download_broadcast_tag_csv(
    broadcast_id: str = Query(..., description="Broadcast UUID"),
    tag_id: str | None = Query(None, description="Tag UUID (optional, used for filename)"),
    segment: str = Query("", description="Filter by segment: A=hot, B=warm, C=cold, D=disqualified, empty=all"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Per-broadcast segment CSV. OPTED_OUT exports a dedicated opted-out sheet."""
    db = get_supabase()

    recipients_resp = (
        db.table("broadcast_recipients")
        .select("lead_id, phone, name, created_at")
        .eq("tenant_id", tenant_id)
        .eq("broadcast_id", broadcast_id)
        .eq("send_status", "sent")
        .execute()
    )
    recipients = recipients_resp.data or []

    template_name = broadcast_id[:8]
    broadcast_sent_at: str | None = None
    try:
        sb_resp = db.table("scheduled_broadcasts").select("template_name,created_at").eq("id", broadcast_id).maybe_single().execute()
        if sb_resp and sb_resp.data:
            template_name = sb_resp.data.get("template_name") or broadcast_id[:8]
            broadcast_sent_at = sb_resp.data.get("created_at")
    except Exception:
        pass

    # Derive broadcast window for delivery-failure check — fall back to earliest recipient timestamp
    if not broadcast_sent_at and recipients:
        try:
            broadcast_sent_at = min(r["created_at"] for r in recipients if r.get("created_at"))
        except Exception:
            pass

    seg_filter = segment.upper() if segment else ""

    if seg_filter == "OPTED_OUT":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["Name", "Phone", "Template", "From Broadcast ID", "Reason", "Opted Out At"],
        )
        writer.writeheader()

        classify_ts = broadcast_sent_at or datetime.now(timezone.utc).isoformat()
        outcome = _classify_broadcast_outcomes(db, tenant_id, broadcast_id, classify_ts)
        for row in (outcome.get("failures") or []):
            if row.get("reason") != "not_interested":
                continue
            writer.writerow({
                "Name": row.get("name", ""),
                "Phone": row.get("phone", ""),
                "Template": template_name,
                "From Broadcast ID": broadcast_id,
                "Reason": row.get("fail_reason") or "opted_out",
                "Opted Out At": row.get("opted_out_at") or "",
            })

        tag_name = "untagged"
        if tag_id:
            try:
                tag_row = db.table("broadcast_tags").select("name").eq("id", tag_id).eq("tenant_id", tenant_id).maybe_single().execute()
                if tag_row and tag_row.data:
                    tag_name = tag_row.data.get("name", "tag")
            except Exception:
                pass

        safe_tag = tag_name.replace(" ", "_").lower()
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=broadcast_{broadcast_id[:8]}_{safe_tag}_opted_out.csv"},
        )

    # Exclude leads whose THIS-broadcast message failed delivery. Attribute by the
    # message nearest the send (not "any failed in window"), so a failure in an
    # adjacent broadcast doesn't wrongly exclude this one. See services/delivery_status.
    delivery_failed_ids: set[str] = set()
    if broadcast_sent_at:
        try:
            _bcast_dt = datetime.fromisoformat(broadcast_sent_at.replace("Z", "+00:00"))
            _window_start = (_bcast_dt - timedelta(minutes=2)).isoformat()
            _window_end = (_bcast_dt + timedelta(minutes=10)).isoformat()
            _lead_ids_sent = [r["lead_id"] for r in recipients if r.get("lead_id")]
            if _lead_ids_sent:
                _msgs = (
                    db.table("messages")
                    .select("lead_id, delivery_status, created_at")
                    .in_("lead_id", _lead_ids_sent)
                    .eq("direction", "outbound")
                    .gte("created_at", _window_start)
                    .lte("created_at", _window_end)
                    .execute()
                )
                _recs_by_lead: dict[str, list[tuple]] = {}
                for _m in (_msgs.data or []):
                    _lid = _m.get("lead_id")
                    _st = _m.get("delivery_status")
                    _mts = parse_ts(_m.get("created_at"))
                    if _lid and _st and _mts is not None:
                        _recs_by_lead.setdefault(_lid, []).append((_mts, _st))
                delivery_failed_ids = {
                    lid for lid, recs in _recs_by_lead.items()
                    if nearest_status(recs, _bcast_dt) == "failed"
                }
        except Exception:
            pass

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Name", "Phone", "Template", "From Broadcast ID", "HOT", "WARM", "COLD"])
    writer.writeheader()

    if not recipients:
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=broadcast_{broadcast_id[:8]}_interests.csv"},
        )

    lead_ids = list({r["lead_id"] for r in recipients if r.get("lead_id")})

    segment_map: dict[str, str] = {}
    if lead_ids:
        bls_resp = (
            db.table("broadcast_lead_scores")
            .select("lead_id,segment")
            .eq("broadcast_id", broadcast_id)
            .in_("lead_id", lead_ids)
            .execute()
        )
        segment_map = {r["lead_id"]: r.get("segment") or "C" for r in (bls_resp.data or [])}

        missing_ids = [lid for lid in lead_ids if lid not in segment_map]
        if missing_ids:
            leads_resp = db.table("leads").select("id,segment").in_("id", missing_ids).eq("tenant_id", tenant_id).execute()
            for l in (leads_resp.data or []):
                segment_map[l["id"]] = l.get("segment") or "C"

    seen: set[str] = set()
    for r in recipients:
        lead_id = r.get("lead_id") or ""
        if lead_id in seen:
            continue
        seen.add(lead_id)
        if lead_id in delivery_failed_ids:
            continue
        seg = segment_map.get(lead_id, "C")
        hot, warm, cold = _segment_to_flags(seg)
        if seg_filter:
            if seg_filter == "A" and hot != 1:
                continue
            if seg_filter == "B" and warm != 1:
                continue
            if seg_filter == "C" and cold != 1:
                continue
            if seg_filter == "D" and (hot != 0 or warm != 0 or cold != 0):
                continue
        writer.writerow({
            "Name": r.get("name") or "",
            "Phone": r.get("phone") or "",
            "Template": template_name,
            "From Broadcast ID": broadcast_id,
            "HOT": hot,
            "WARM": warm,
            "COLD": cold,
        })

    tag_name = "untagged"
    if tag_id:
        try:
            tag_row = db.table("broadcast_tags").select("name").eq("id", tag_id).eq("tenant_id", tenant_id).maybe_single().execute()
            if tag_row and tag_row.data:
                tag_name = tag_row.data.get("name", "tag")
        except Exception:
            pass

    safe_tag = tag_name.replace(" ", "_").lower()
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=broadcast_{broadcast_id[:8]}_{safe_tag}_interests.csv"},
    )
