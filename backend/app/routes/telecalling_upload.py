import csv
import io
import logging
import re
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, get_tenant_and_role, require_owner
from app.services.assignment import add_upload_pending, assign_upload_batch, get_telecalling_config, remove_upload_pending
from app.services.assignment_rules import get_channel_rules
from app.services.audit_log import record_audit_event
from app.services.call_rules import phone_mask_for
from app.services.reports_common import chunks, paged
from app.services.call_team_scope import is_team_leader, scoped_caller_ids
from app.services.call_wrapup import CLOSED_LEAD_STATUSES
from app.services.download_gate import log_download, require_download
from app.services.segmentation import new_lead_score_and_segment
from app.services.upload_taken_out import csv_text, reason_for_existing, results_for, summarize

logger = logging.getLogger(__name__)
# No router-wide gate: uploading and undoing are owner-only (require_owner on each), the history list
# is for the owner or a Team leader (who sees only their own team's rows), downloads also need leads.download.
router = APIRouter()

PHONE_RE = re.compile(r"[^\d+]")
HISTORY_COLUMNS = ("id,tenant_id,file_name,total_contacts,inserted,duplicates,assigned,segment_override,"
                   "assignment_snapshot,created_at,undone_at,undone_by,undone_count")


def _attachment(filename: str) -> dict:
    """Content-Disposition that survives non-English file names: an ASCII fallback plus the UTF-8 name."""
    clean = filename.replace("\r", "").replace("\n", "").replace('"', "")
    ascii_name = clean.encode("ascii", "ignore").decode().strip() or "download.csv"
    if not ascii_name.lower().endswith(".csv"):
        ascii_name += ".csv"
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(clean)}"}


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
    taken_out: list[dict] = []   # rows this upload left out, with why (item 234)
    row_of_phone: dict[str, int] = {}
    for row_no, row in enumerate(reader, start=2):   # row 1 is the header
        raw_phone = row.get(fieldmap.get("phone", "phone"), "")
        phone = _normalize_phone(raw_phone)
        name_key = fieldmap.get("name")
        row_name = ((row.get(name_key) or "").strip() or None) if name_key else None
        if not phone:
            taken_out.append({"row": row_no, "phone": (raw_phone or "").strip()[:30], "name": row_name, "reason": "bad_number"})
            continue
        if phone in rows_by_phone:
            # The last copy is the one used, so the earlier (discarded) copy is what was taken out.
            earlier = row_of_phone[phone]
            taken_out.append({"row": earlier, "phone": phone, "name": rows_by_phone[phone].get("name"), "reason": "duplicate"})
        row_of_phone[phone] = row_no
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
        .select("id,phone,name,assigned_to,do_not_call,opted_out,call_status,converted_at")
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
        and not ld.get("opted_out")
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

    inserted_id_set = {str(i) for i in inserted_ids}
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
            # True only for a lead THIS upload created: "Undo upload" removes exactly these (and only
            # while nobody has called or messaged them). Older batches have no such flag.
            "new": str(ld["id"]) in inserted_id_set,
        })

    # Known people the upload left alone (said stop, already a customer, closed, already with a telecaller).
    for phone in all_upload_phones:
        ld = lead_by_phone.get(phone)
        if not ld:
            continue
        reason = reason_for_existing(ld, is_new=str(ld["id"]) in inserted_id_set)
        if reason:
            taken_out.append({"row": row_of_phone.get(phone), "phone": phone, "name": ld.get("name") or rows_by_phone[phone].get("name"), "reason": reason})
    taken_out.sort(key=lambda r: (r.get("row") or 0))
    stored_taken_out, taken_out_counts = summarize(taken_out)

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
    try:
        batch_result = db.table("telecalling_upload_batches").insert(
            {**batch_row, "taken_out": stored_taken_out, "taken_out_counts": taken_out_counts}).execute()
    except Exception as e:  # migration 334 not applied yet: save the batch without the taken-out list
        logger.warning("upload batch saved without taken_out (migration 334 missing?): %s", e)
        batch_result = db.table("telecalling_upload_batches").insert(batch_row).execute()
    batch_id = batch_result.data[0]["id"] if batch_result.data else None

    return {
        "batch_id": batch_id,
        "total": len(phones),
        "inserted": inserted,
        "duplicates": len(existing_set),
        "assigned": len(assignments),
        "taken_out": sum(taken_out_counts.values()),
    }




# ── Who may open the upload history ─────────────────────────────────────────────

def history_viewer(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    """Owner (as always), or a Team leader with the upload-view permission (sees only their team)."""
    if ctx.get("role") == "owner":
        return ctx
    if (_has_permission(ctx, "telecalling.upload.view") or "telecalling.upload" in (ctx.get("permissions") or [])) \
            and is_team_leader(get_supabase(), ctx):
        return ctx
    raise HTTPException(status_code=403, detail="Organization owner privileges required.")


def _scope_snapshot(snapshot: list[dict], scoped: set[str] | None) -> list[dict]:
    """A Team leader sees only the rows given to their own callers."""
    if scoped is None:
        return snapshot
    return [r for r in snapshot if r.get("caller_id") and str(r["caller_id"]) in scoped]


def _user_names(db, tenant_id: str, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    try:
        rows = (
            db.table("tenant_users").select("user_id,full_name").eq("tenant_id", tenant_id)
            .in_("user_id", user_ids).execute().data or []
        )
        return {str(r["user_id"]): (r.get("full_name") or "").strip() for r in rows}
    except Exception as e:
        logger.warning("upload history: could not read names for undone_by (%s)", e)
        return {}


@router.get("/history")
async def get_upload_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    ctx: dict = Depends(history_viewer),
):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    offset = (page - 1) * limit
    scoped = scoped_caller_ids(db, ctx)  # None = owner / everyone; a set = a Team leader's own team
    is_owner = ctx.get("role") == "owner"

    def newest(columns: str):
        return db.table("telecalling_upload_batches").select(columns).eq("tenant_id", tenant_id).order("created_at", desc=True)

    # Columns are listed so the big taken_out list is never pulled for the history. Migration 334 adds the counts.
    def read(start: int, end: int) -> list[dict]:
        try:
            return newest(HISTORY_COLUMNS + ",taken_out_counts").range(start, end).execute().data or []
        except Exception as e:
            logger.info("upload history without taken_out_counts (migration 334 missing?): %s", e)
            return newest(HISTORY_COLUMNS).range(start, end).execute().data or []

    if scoped is None:
        rows = read(offset, offset + limit - 1)
    else:
        # Rows are filtered after reading, so scan the newest batches (not just one page) and slice.
        recent = read(0, 299)
        visible: list[dict] = []
        for row in recent:
            mine = _scope_snapshot(row.get("assignment_snapshot") or [], scoped)
            if not mine:
                continue
            visible.append({**row, "assignment_snapshot": mine, "assigned": len(mine)})
        rows = visible[offset: offset + limit]

    names = _user_names(db, tenant_id, sorted({str(r["undone_by"]) for r in rows if r.get("undone_by")}))
    for r in rows:
        # Rows taken out belong to no telecaller, so only the owner sees them. Uploads from before
        # migration 334 have no list: the page shows a dash (taken_out_counts is None).
        r.pop("taken_out", None)  # never sent to the page (the query does not read it either)
        counts = r.pop("taken_out_counts", None)
        r["taken_out_counts"] = counts if (is_owner and scoped is None) else None
        r["undone_by_name"] = names.get(str(r["undone_by"])) or "the owner" if r.get("undone_by") else None
        r["can_undo"] = bool(is_owner and not r.get("undone_at"))
    return rows


@router.get("/history/results")
async def upload_results(
    batch_ids: str = Query(..., description="comma-separated batch ids (the ones on screen)"),
    ctx: dict = Depends(history_viewer),
):
    """Per upload: how many of its people were called since, reached, and converted.
    Loaded separately from the list so the history opens fast. A Team leader sees their own team's rows."""
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    ids: list[str] = []
    for part in batch_ids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(str(UUID(part)))
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad batch id")
    ids = ids[:30]
    if not ids:
        return {}
    scoped = scoped_caller_ids(db, ctx)
    batches = (
        db.table("telecalling_upload_batches").select("id,created_at,assignment_snapshot")
        .eq("tenant_id", tenant_id).in_("id", ids).execute().data or []
    )
    out: dict[str, dict] = {}
    for b in batches:
        snap = _scope_snapshot(b.get("assignment_snapshot") or [], scoped)
        lead_ids = sorted({str(r["lead_id"]) for r in snap if r.get("lead_id")})
        calls: list[dict] = []
        for part in chunks(lead_ids):
            calls += paged(lambda part=part: (
                db.table("call_logs").select("id,lead_id,created_at,manual_status,duration_seconds,status,outcome")
                .eq("tenant_id", tenant_id).in_("lead_id", part).gte("created_at", b["created_at"])
            ))
        out[str(b["id"])] = results_for(set(lead_ids), calls, b["created_at"])
    return out


@router.get("/history/{batch_id}/taken-out")
async def download_taken_out_csv(batch_id: UUID, ctx: dict = Depends(history_viewer)):
    """What the upload left out and why, as a spreadsheet. Same download rule as the assignments file."""
    require_download(ctx)
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    if scoped_caller_ids(db, ctx) is not None:
        # Left-out rows belong to no telecaller, so a Team leader has nothing of their own here.
        raise HTTPException(status_code=403, detail="Only the owner can download the rows taken out.")
    try:
        rows = (
            db.table("telecalling_upload_batches").select("file_name,taken_out")
            .eq("id", str(batch_id)).eq("tenant_id", tenant_id).limit(1).execute().data or []
        )
    except Exception as e:  # migration 334 not applied yet
        logger.info("taken_out not readable yet: %s", e)
        rows = []
    if not rows or rows[0].get("taken_out") is None:
        raise HTTPException(status_code=404, detail="No list of taken-out rows was saved for this upload")
    taken = rows[0]["taken_out"] or []
    file_name = rows[0].get("file_name") or "contacts.csv"
    log_download(db, ctx, list_name=f"Upload rows taken out: {file_name}", row_count=len(taken),
                 filters={"batch_id": str(batch_id)})
    name = f"taken_out_{file_name}"
    if not name.endswith(".csv"):
        name += ".csv"
    return Response(
        content=csv_text(taken, mask=phone_mask_for(db, tenant_id, ctx)),
        media_type="text/csv",
        headers=_attachment(name),
    )


@router.get("/history/{batch_id}/csv")
async def download_assignment_csv(
    batch_id: UUID,
    ctx: dict = Depends(history_viewer),
):
    require_download(ctx)  # "Download lists": owner, or a role with leads.download
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
    scoped = scoped_caller_ids(db, ctx)
    snapshot = _scope_snapshot(result.data.get("assignment_snapshot") or [], scoped)
    if scoped is not None and not snapshot:
        raise HTTPException(status_code=404, detail="Batch not found")
    list_name = f"Upload assignments: {file_name}"
    filters = {"batch_id": str(batch_id), "own_team_only": scoped is not None}

    # If the original raw CSV is stored, download and return it merged with caller names
    # (owner view only: the raw file holds every row, so a Team leader gets the filtered snapshot below).
    if csv_storage_path and scoped is None:
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

                log_download(db, ctx, list_name=list_name, row_count=len(rows) - 1, filters=filters)
                return Response(
                    content=output.getvalue(),
                    media_type="text/csv",
                    headers=_attachment(csv_filename),
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

    log_download(db, ctx, list_name=list_name, row_count=len(snapshot), filters=filters)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers=_attachment(csv_filename),
    )


# ── Undo an upload (owner only) ─────────────────────────────────────────────────
#
# "Undo upload" takes back the people THIS upload added, but only the ones nobody has touched.
# It never deletes a customer who was in the system before, or anyone called, messaged, noted,
# quoted, or scheduled. When a lead is in any doubt it stays. The delete is the usual soft delete
# (leads.deleted_at), the same one the Leads page uses.
#
# "Created by this upload":
#   * new batches: the snapshot row says "new": true (written at upload time from the ids the insert
#     returned), AND the lead was created inside the upload's own time window;
#   * older batches (no "new" flag in the snapshot): created inside a tighter window just before the
#     batch row was saved, source "upload", and no more such leads than the batch's own "inserted"
#     count. If more match than were inserted, the batch is ambiguous and nothing is removed.

_EXACT_WINDOW = (timedelta(minutes=30), timedelta(minutes=2))   # (before, after) the batch row's created_at
_LEGACY_WINDOW = (timedelta(minutes=10), timedelta(minutes=1))
_ACTIVITY_TABLES = ("call_logs", "messages", "deals", "follow_up_jobs", "lead_notes", "broadcast_recipients")
_ID_CHUNK = 100
_PAGE = 1000


class _UndoUnavailable(Exception):
    """A read the undo depends on failed: remove nothing."""


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _leads_with_activity(db, lead_ids: list[str]) -> set[str]:
    """Lead ids that have any call, message, deal, follow-up, note or broadcast row. Reads every page,
    because a cut-off page would let a touched lead look untouched."""
    touched: set[str] = set()
    for table in _ACTIVITY_TABLES:
        for chunk in _chunks(lead_ids, _ID_CHUNK):
            offset = 0
            while True:
                rows = (
                    db.table(table).select("lead_id").in_("lead_id", chunk)
                    .range(offset, offset + _PAGE - 1).execute().data or []
                )
                touched.update(str(r["lead_id"]) for r in rows if r.get("lead_id"))
                if len(rows) < _PAGE:
                    break
                offset += _PAGE
    return touched


def _plan_undo(db, tenant_id: str, batch: dict) -> dict:
    """Decide, lead by lead, what the undo would remove. Pure reads. Raises _UndoUnavailable on a failed read."""
    snapshot = batch.get("assignment_snapshot") or []
    entries = {str(r["lead_id"]): r for r in snapshot if r.get("lead_id")}
    exact = bool(snapshot) and all("new" in r for r in snapshot)
    batch_at = _parse_ts(batch.get("created_at"))
    keep = {"existing": 0, "touched": 0, "unsure": 0}
    if not entries or batch_at is None:
        return {"remove_ids": [], "keep": keep, "kept": 0, "already_gone": 0}

    before, after = _EXACT_WINDOW if exact else _LEGACY_WINDOW
    lead_rows: list[dict] = []
    try:
        for chunk in _chunks(list(entries), _ID_CHUNK):
            lead_rows.extend(
                db.table("leads")
                .select("id,created_at,source,deleted_at,call_status,converted_at,booked_at,lost_at,"
                        "last_inbound_at,do_not_call,opted_out")
                .eq("tenant_id", tenant_id).in_("id", chunk).execute().data or []
            )
    except Exception as e:
        logger.error("undo upload: could not read leads (%s)", e)
        raise _UndoUnavailable() from e

    active = [r for r in lead_rows if not r.get("deleted_at")]
    already_gone = len(entries) - len(active)

    candidates: list[dict] = []
    for ld in active:
        entry = entries.get(str(ld["id"])) or {}
        made = _parse_ts(ld.get("created_at"))
        in_window = made is not None and batch_at - before <= made <= batch_at + after
        if exact:
            ours = entry.get("new") is True and in_window
        else:
            ours = in_window and ld.get("source") == "upload"
        if ours:
            candidates.append(ld)
        else:
            keep["existing"] += 1

    if not exact and len(candidates) > int(batch.get("inserted") or 0):
        # More leads look new than this upload inserted: can't tell which are ours. Keep all.
        keep["unsure"] += len(candidates)
        candidates = []

    untouched: list[dict] = []
    for ld in candidates:
        if (
            (ld.get("call_status") or "new") != "new"
            or ld.get("converted_at") or ld.get("booked_at") or ld.get("lost_at")
            or ld.get("last_inbound_at") or ld.get("do_not_call") or ld.get("opted_out")
        ):
            keep["touched"] += 1
        else:
            untouched.append(ld)

    try:
        touched_ids = _leads_with_activity(db, [str(ld["id"]) for ld in untouched])
    except Exception as e:
        logger.error("undo upload: could not check calls/messages (%s)", e)
        raise _UndoUnavailable() from e

    remove_ids = []
    for ld in untouched:
        if str(ld["id"]) in touched_ids:
            keep["touched"] += 1
        else:
            remove_ids.append(str(ld["id"]))
    return {"remove_ids": remove_ids, "keep": keep, "kept": sum(keep.values()), "already_gone": already_gone}


def _load_batch(db, tenant_id: str, batch_id: UUID) -> dict:
    res = (
        db.table("telecalling_upload_batches").select("*")
        .eq("id", str(batch_id)).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Batch not found")
    return res.data


def _undone_conflict(batch: dict) -> HTTPException:
    return HTTPException(status_code=409, detail="This upload was already undone.")


@router.get("/history/{batch_id}/undo-preview")
async def undo_upload_preview(batch_id: UUID, ctx: dict = Depends(require_owner)):
    """What "Undo upload" would do, for the confirm box: how many people it removes and how many stay."""
    db = get_supabase()
    batch = _load_batch(db, ctx["tenant_id"], batch_id)
    if batch.get("undone_at"):
        raise _undone_conflict(batch)
    try:
        plan = _plan_undo(db, ctx["tenant_id"], batch)
    except _UndoUnavailable:
        raise HTTPException(status_code=503, detail="Couldn't check this upload right now. Nothing was removed.")
    return {
        "file_name": batch.get("file_name"),
        "will_remove": len(plan["remove_ids"]),
        "will_keep": plan["kept"],
        "keep_reasons": plan["keep"],
    }


@router.post("/history/{batch_id}/undo")
async def undo_upload(batch_id: UUID, ctx: dict = Depends(require_owner)):
    """Owner only. Removes the people this upload added who nobody has touched; the rest stay."""
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    batch = _load_batch(db, tenant_id, batch_id)
    if batch.get("undone_at"):
        raise _undone_conflict(batch)
    try:
        plan = _plan_undo(db, tenant_id, batch)
    except _UndoUnavailable:
        raise HTTPException(status_code=503, detail="Couldn't check this upload right now. Nothing was removed.")

    now = datetime.now(timezone.utc).isoformat()
    # Claim the undo first (only one request can win it), so a second click or a double request gets a 409.
    try:
        claimed = (
            db.table("telecalling_upload_batches")
            .update({"undone_at": now, "undone_by": ctx.get("user_id"), "undone_count": 0})
            .eq("id", str(batch_id)).eq("tenant_id", tenant_id).is_("undone_at", "null").execute().data
        )
    except Exception as e:
        logger.warning("undo upload: could not record the undo (%s); is migration 307 applied?", e)
        raise HTTPException(status_code=503, detail="Undo isn't available yet. Nothing was removed.")
    if not claimed:
        raise _undone_conflict(batch)

    removed = 0
    try:
        for chunk in _chunks(plan["remove_ids"], _ID_CHUNK):
            done = (
                db.table("leads").update({"deleted_at": now, "ai_enabled": False})
                .eq("tenant_id", tenant_id).in_("id", chunk).is_("deleted_at", "null").execute().data or []
            )
            removed += len(done)
            try:
                remove_upload_pending(db, tenant_id, chunk)
            except Exception:
                logger.exception("undo upload: could not clear the pending queue")
    except Exception:
        logger.exception("undo upload: stopped after %s removed", removed)
        try:  # let the owner retry: leads already removed are skipped the next time
            db.table("telecalling_upload_batches").update(
                {"undone_at": None, "undone_by": None, "undone_count": None}
            ).eq("id", str(batch_id)).eq("tenant_id", tenant_id).execute()
        except Exception:
            logger.exception("undo upload: could not release the claim")
        raise HTTPException(status_code=500, detail=f"Undo stopped part way ({removed} removed). Try again.")

    try:
        db.table("telecalling_upload_batches").update({"undone_count": removed}).eq("id", str(batch_id)).eq("tenant_id", tenant_id).execute()
    except Exception:
        logger.exception("undo upload: could not save the removed count")
    record_audit_event(
        db, tenant_id=tenant_id, actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
        action="telecalling_upload.undone", target_type="telecalling_upload_batch", target_id=str(batch_id),
        metadata={"file_name": batch.get("file_name"), "removed": removed, "kept": plan["kept"], "kept_reasons": plan["keep"]},
    )
    return {"removed": removed, "kept": plan["kept"], "file_name": batch.get("file_name")}
