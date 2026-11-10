import csv
import io
import logging
import re
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role, require_owner
from app.services.assignment import add_upload_pending, assign_upload_batch, get_telecalling_config
from app.services.assignment_rules import get_channel_rules
from app.services.call_wrapup import CLOSED_LEAD_STATUSES
from app.services.segmentation import new_lead_score_and_segment

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_owner)])

PHONE_RE = re.compile(r"[^\d+]")


def _normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    digits_only = PHONE_RE.sub("", raw.strip())
    if not digits_only:
        return None

    digits_only = digits_only.lstrip("+").lstrip("0")

    if len(digits_only) == 10 and digits_only[0] in "6789":
        return f"+91{digits_only}"

    if len(digits_only) == 12 and digits_only.startswith("91") and digits_only[2] in "6789":
        return f"+{digits_only}"

    if raw.strip().startswith("+"):
        result = f"+{digits_only}"
        if 8 <= len(digits_only) <= 15:
            return result
        return None

    if 8 <= len(digits_only) <= 15:
        return f"+{digits_only}"
    return None


@router.post("/upload")
async def upload_telecalling_contacts(
    file: UploadFile = File(...),
    segment_override: str | None = Form(None),
    ctx: dict = Depends(require_owner),
):
    tenant_id = ctx["tenant_id"]

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    if segment_override and segment_override not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=400, detail="segment_override must be A/B/C/D")

    raw_bytes = await file.read()
    raw = raw_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "phone" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(status_code=400, detail="CSV must contain a 'phone' column")

    db = get_supabase()
    initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
    fieldmap = {f.strip().lower(): f for f in reader.fieldnames}

    rows_by_phone: dict[str, dict] = {}
    for row in reader:
        phone = _normalize_phone(row.get(fieldmap.get("phone", "phone"), ""))
        if not phone:
            continue
        name_key = fieldmap.get("name")
        rows_by_phone[phone] = {
            "phone": phone,
            "name": (row.get(name_key) or "").strip() or None if name_key else None,
            "source": "upload",
            "score": initial_score,
            "segment": segment_override or initial_segment,
            "tenant_id": tenant_id,
        }

    if not rows_by_phone:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV")

    phones = list(rows_by_phone.keys())

    existing = (
        db.table("leads")
        .select("phone")
        .in_("phone", phones)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .execute()
    )
    existing_set = {r["phone"] for r in (existing.data or [])}

    soft_deleted = (
        db.table("leads")
        .select("phone,id")
        .in_("phone", phones)
        .eq("tenant_id", tenant_id)
        .not_.is_("deleted_at", "null")
        .execute()
    )
    if soft_deleted.data:
        soft_deleted_phones = [r["phone"] for r in soft_deleted.data]
        db.table("leads").update({"deleted_at": None, "ai_enabled": True}).in_("phone", soft_deleted_phones).eq("tenant_id", tenant_id).execute()
        for phone in soft_deleted_phones:
            existing_set.discard(phone)

    to_insert = [rows_by_phone[p] for p in phones if p not in existing_set]
    inserted = 0
    inserted_ids: list[str] = []
    for i in range(0, len(to_insert), 100):
        batch = to_insert[i : i + 100]
        result = db.table("leads").insert(batch).execute()
        for lead in (result.data or []):
            inserted += 1
            inserted_ids.append(lead["id"])

    all_upload_phones = list(rows_by_phone.keys())
    all_leads = (
        db.table("leads")
        .select("id,phone,name,assigned_to,do_not_call,call_status,converted_at")
        .in_("phone", all_upload_phones)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .execute()
    )
    lead_by_phone: dict[str, dict] = {}
    for ld in (all_leads.data or []):
        lead_by_phone[ld["phone"]] = ld

    # Closed leads (converted, DNC, unreachable, ...) are never handed to a telecaller again.
    unassigned_ids = [
        ld["id"] for ld in lead_by_phone.values()
        if not ld.get("assigned_to")
        and not ld.get("do_not_call")
        and ld.get("call_status") not in CLOSED_LEAD_STATUSES
        and not ld.get("converted_at")
    ]

    cfg = get_telecalling_config(tenant_id)
    upload_rule = get_channel_rules(cfg)["upload"]

    # Map all caller IDs to names (for capturing existing assignments in the snapshot)
    all_callers_res = db.table("callers").select("id,name").eq("tenant_id", tenant_id).execute()
    all_caller_map = {c["id"]: c["name"] for c in (all_callers_res.data or [])}

    assignments: list[dict] = []
    # Telecalling or the upload row off: nothing is assigned.
    if not cfg.get("enabled") or not upload_rule.get("enabled"):
        pass
    elif upload_rule.get("mode") == "pull":
        if unassigned_ids:
            add_upload_pending(db, tenant_id, unassigned_ids)
    else:
        # One pass for the whole file: callers and turn order read once, one summary notification each.
        assignments, still_pending = assign_upload_batch(db, tenant_id, unassigned_ids, cfg)
        if still_pending:
            add_upload_pending(db, tenant_id, still_pending)

    assignment_map = {a["lead_id"]: a for a in assignments}

    snapshot: list[dict] = []
    for phone in all_upload_phones:
        ld = lead_by_phone.get(phone)
        if not ld:
            continue
        a = assignment_map.get(ld["id"])
        if a:
            caller_id = a["caller_id"]
            caller_name = a["caller_name"]
        else:
            caller_id = ld.get("assigned_to")
            caller_name = all_caller_map.get(caller_id) if caller_id else None

        snapshot.append({
            "lead_id": ld["id"],
            "phone": phone,
            "name": ld.get("name"),
            "caller_id": caller_id,
            "caller_name": caller_name,
        })

    csv_path: str | None = None
    try:
        storage_filename = f"{tenant_id}/telecalling/{uuid.uuid4().hex[:8]}_{file.filename}"
        db.storage.from_("broadcast-csvs").upload(storage_filename, raw_bytes, {"content-type": "text/csv"})
        csv_path = storage_filename
    except Exception:
        logger.exception("Failed to upload telecalling CSV to storage")

    batch_row = {
        "tenant_id": tenant_id,
        "file_name": file.filename,
        "total_contacts": len(phones),
        "inserted": inserted,
        "duplicates": len(existing_set),
        "assigned": len(assignments),
        "segment_override": segment_override,
        "assignment_snapshot": snapshot,
        "csv_storage_path": csv_path,
    }
    batch_result = db.table("telecalling_upload_batches").insert(batch_row).execute()
    batch_id = batch_result.data[0]["id"] if batch_result.data else None

    return {
        "batch_id": batch_id,
        "total": len(phones),
        "inserted": inserted,
        "duplicates": len(existing_set),
        "assigned": len(assignments),
    }


@router.get("/history")
async def get_upload_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    ctx: dict = Depends(require_owner),
):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    offset = (page - 1) * limit
    result = (
        db.table("telecalling_upload_batches")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return result.data or []


@router.get("/history/{batch_id}/csv")
async def download_assignment_csv(
    batch_id: UUID,
    ctx: dict = Depends(require_owner),
):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    result = (
        db.table("telecalling_upload_batches")
        .select("assignment_snapshot,file_name,csv_storage_path")
        .eq("id", str(batch_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        raise HTTPException(status_code=404, detail="Batch not found")

    file_name = result.data.get("file_name") or "contacts.csv"
    csv_storage_path = result.data.get("csv_storage_path")
    snapshot = result.data.get("assignment_snapshot") or []

    # If the original raw CSV is stored, download and return it merged with caller names
    if csv_storage_path:
        try:
            file_bytes = db.storage.from_("broadcast-csvs").download(csv_storage_path)
            raw_text = file_bytes.decode("utf-8-sig", errors="replace")
            
            # Map phone numbers to caller names from the snapshot
            phone_to_caller: dict[str, str] = {}
            for item in snapshot:
                phone = item.get("phone")
                caller_name = item.get("caller_name")
                if phone and caller_name:
                    phone_to_caller[phone] = caller_name

            # Parse original CSV rows
            reader = csv.reader(io.StringIO(raw_text))
            rows = list(reader)

            if rows:
                headers = rows[0]
                phone_idx = -1
                for idx, h in enumerate(headers):
                    if h.strip().lower() == "phone":
                        phone_idx = idx
                        break

                headers.append("assigned_caller")

                for row in rows[1:]:
                    raw_phone = row[phone_idx] if phone_idx >= 0 and phone_idx < len(row) else ""
                    norm_phone = _normalize_phone(raw_phone)
                    caller_name = phone_to_caller.get(norm_phone or "") or "Unassigned"
                    row.append(caller_name)

                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerows(rows)

                csv_filename = f"assignments_{file_name}" if file_name else f"assignments_{batch_id}.csv"
                if not csv_filename.endswith(".csv"):
                    csv_filename += ".csv"

                return Response(
                    content=output.getvalue(),
                    media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={csv_filename}"},
                )
        except Exception:
            logger.exception("Failed to download or merge CSV from storage, falling back to assignment snapshot")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["phone", "name", "caller_name", "caller_id", "lead_id"])
    writer.writeheader()
    for row in snapshot:
        writer.writerow({
            "phone": row.get("phone", ""),
            "name": row.get("name", ""),
            "caller_name": row.get("caller_name", ""),
            "caller_id": row.get("caller_id", ""),
            "lead_id": row.get("lead_id", ""),
        })

    csv_filename = f"assignments_{file_name}" if file_name else f"assignments_{batch_id}.csv"
    if not csv_filename.endswith(".csv"):
        csv_filename += ".csv"

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={csv_filename}"},
    )
