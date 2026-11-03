"""SMS address book (prefix /api/v1/sms): contacts, CSV/Excel upload, pasted numbers, groups.

A client's own SMS numbers, separate from leads. Every query is scoped to the caller's tenant.
Reads need sms.view, writes sms.manage (neither needs the Bulk9 key). Logic lives in
app/services/sms_contacts.py.
"""
import csv
import io
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.routes.sms import _safe_filename, _sms_error, manage_no_key, view_no_key
from app.services import sms_campaigns as camp, sms_contacts as svc

router = APIRouter()

BAD_PHONE = "Enter a valid 10-digit Indian mobile number."
PARSE_CAP = 5_000


class ContactBody(BaseModel):
    phone: str
    name: Optional[str] = Field(None, max_length=200)
    fields: Optional[dict[str, str]] = None
    group_id: Optional[str] = None
    consent: bool = False


class PasteBody(BaseModel):
    text: str = Field(max_length=500_000)
    group_id: Optional[str] = None
    consent: bool = False


class IdsBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=1000)


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _run(fn, *args, **kwargs):
    """Call a service function, turning SmsError into an HTTP error."""
    try:
        return fn(*args, **kwargs)
    except camp.SmsError as e:
        raise _sms_error(e)


def _ids(body: IdsBody) -> list[str]:
    ids = [svc.as_uuid(i) for i in body.ids]
    if not all(ids):
        raise HTTPException(422, "One of the contact ids is not valid.")
    return ids


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    name = _safe_filename(file.filename)
    data = await file.read(svc.MAX_BYTES + 1)
    if len(data) > svc.MAX_BYTES:
        raise HTTPException(413, "This file is larger than 10 MB.")
    return data, name


def _csv_cell(v) -> str:
    s = "" if v is None else str(v)
    # Same rule as the messages export: a spreadsheet runs a cell starting with these as a formula.
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _group_contacts(db, tenant_id: str, group_id: str) -> list[dict]:
    rows, start = [], 0
    while True:
        page = (db.table("sms_contacts").select("*").eq("tenant_id", tenant_id)
                .contains("group_ids", [group_id]).order("id").range(start, start + svc.CHUNK - 1)
                .execute().data or [])
        rows += page
        if len(page) < svc.CHUNK:
            return rows
        start += svc.CHUNK


# ---------------------------------------------------------------- contacts

@router.get("/contacts")
async def list_contacts(search: str = Query("", max_length=100), group_id: Optional[str] = None,
                        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        ctx: dict = Depends(view_no_key)):
    return svc.list_contacts(get_supabase(), ctx["tenant_id"], search=search, group_id=group_id,
                             limit=limit, offset=offset)


@router.post("/contacts", status_code=201)
async def add_contact(body: ContactBody, ctx: dict = Depends(manage_no_key)):
    db, tenant = get_supabase(), ctx["tenant_id"]
    phone = camp.normalize_indian_mobile(body.phone)
    if not phone:
        raise HTTPException(422, BAD_PHONE)
    group_id = None
    if body.group_id:
        group_id = _run(svc.get_group, db, tenant, body.group_id)["id"]
    source = svc.consent_source("manual", ctx.get("user_id")) if body.consent else None
    row = {"phone": phone, "name": svc.clean_cell(body.name) or None, "fields": svc.clean_fields(body.fields)}
    _run(svc.save_contacts, db, tenant, [row], group_id, source)
    saved = (db.table("sms_contacts").select("*").eq("tenant_id", tenant).eq("phone", phone)
             .limit(1).execute().data or [])
    if not saved:
        raise HTTPException(500, "Could not save the contact. Please try again.")
    return svc.contact_json(saved[0])


@router.post("/contacts/paste")
async def paste_contacts(body: PasteBody, ctx: dict = Depends(manage_no_key)):
    source = svc.consent_source("paste", ctx.get("user_id")) if body.consent else None
    return await run_in_threadpool(_run, svc.import_paste, get_supabase(), ctx["tenant_id"], body.text,
                                   body.group_id or None, source)


@router.post("/contacts/upload/preview")
async def upload_preview(file: UploadFile = File(...), ctx: dict = Depends(manage_no_key)):
    data, name = await _read_upload(file)
    return await run_in_threadpool(_run, svc.preview, data, name)


@router.post("/contacts/upload")
async def upload_contacts(file: UploadFile = File(...), group_id: Optional[str] = Form(None),
                          group_name: Optional[str] = Form(None), phone_column: Optional[str] = Form(None),
                          name_column: Optional[str] = Form(None), consent: str = Form("false"),
                          ctx: dict = Depends(manage_no_key)):
    data, name = await _read_upload(file)
    source = (svc.consent_source("upload", ctx.get("user_id"), name)
              if consent.strip().lower() == "true" else None)
    return await run_in_threadpool(
        _run, svc.import_file, get_supabase(), ctx["tenant_id"], data, name,
        group_id=group_id or None, group_name=group_name, phone_column=phone_column or None,
        name_column=name_column or None, consent_source_text=source)


@router.post("/contacts/delete")
async def delete_contacts(body: IdsBody, ctx: dict = Depends(manage_no_key)):
    return {"deleted": svc.delete_contacts(get_supabase(), ctx["tenant_id"], _ids(body))}


@router.post("/contacts/groups/{group_id}/add")
async def add_to_group(group_id: str, body: IdsBody, ctx: dict = Depends(manage_no_key)):
    gid = svc.as_uuid(group_id)
    if not gid:
        raise HTTPException(404, svc.GROUP_NOT_FOUND)
    return {"changed": _run(svc.set_group, get_supabase(), ctx["tenant_id"], gid, _ids(body), True)}


@router.post("/contacts/groups/{group_id}/remove")
async def remove_from_group(group_id: str, body: IdsBody, ctx: dict = Depends(manage_no_key)):
    gid = svc.as_uuid(group_id)
    if not gid:
        raise HTTPException(404, svc.GROUP_NOT_FOUND)
    return {"changed": _run(svc.set_group, get_supabase(), ctx["tenant_id"], gid, _ids(body), False)}


# ---------------------------------------------------------------- groups

@router.get("/contact-groups")
async def list_groups(ctx: dict = Depends(view_no_key)):
    return {"groups": svc.list_groups(get_supabase(), ctx["tenant_id"])}


@router.post("/contact-groups", status_code=201)
async def create_group(body: GroupBody, ctx: dict = Depends(manage_no_key)):
    row = _run(svc.create_group, get_supabase(), ctx["tenant_id"], body.name)
    return {"id": row["id"], "name": row["name"], "contacts": 0, "created_at": row.get("created_at")}


@router.patch("/contact-groups/{group_id}")
async def rename_group(group_id: str, body: GroupBody, ctx: dict = Depends(manage_no_key)):
    row = _run(svc.rename_group, get_supabase(), ctx["tenant_id"], group_id, body.name)
    return {"id": row["id"], "name": row["name"], "created_at": row.get("created_at")}


@router.delete("/contact-groups/{group_id}")
async def delete_group(group_id: str, with_contacts: bool = False, ctx: dict = Depends(manage_no_key)):
    return {"deleted_contacts": _run(svc.delete_group, get_supabase(), ctx["tenant_id"], group_id, with_contacts)}


@router.get("/contact-groups/{group_id}/export.csv")
async def export_group(group_id: str, ctx: dict = Depends(view_no_key)):
    gid = svc.as_uuid(group_id)
    if not gid:
        raise HTTPException(422, "Group id is not valid.")
    db, tenant = get_supabase(), ctx["tenant_id"]
    group = _run(svc.get_group, db, tenant, gid)
    rows = await run_in_threadpool(_group_contacts, db, tenant, gid)
    keys = sorted({k for r in rows for k in (r.get("fields") or {})})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Mobile", *(_csv_cell(k) for k in keys), "Added"])
    for r in rows:
        fields = r.get("fields") or {}
        w.writerow([_csv_cell(r.get("name")), _csv_cell(r["phone"]), *(_csv_cell(fields.get(k)) for k in keys),
                    r.get("created_at") or ""])
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", group.get("name") or "")[:60].strip() or "group"
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'})


# ---------------------------------------------------------------- numbers from a file (no saving)

@router.post("/numbers/parse")
async def parse_numbers(file: UploadFile = File(...), phone_column: Optional[str] = Form(None),
                        ctx: dict = Depends(manage_no_key)):
    data, name = await _read_upload(file)

    def parse():
        headers, rows = svc.read_table(data, name)
        contacts, skipped = svc.build_contacts(headers, rows, phone_column or None, None)
        return contacts, skipped, phone_column or svc.detect_columns(headers)[0]

    try:
        contacts, skipped, chosen = await run_in_threadpool(parse)
    except camp.SmsError as e:
        # A bad file is a 400 here (the shared mapping would give 422).
        raise HTTPException(400 if e.status == 422 else e.status, str(e))
    numbers = [c["phone"] for c in contacts]  # build_contacts already de-duplicates, in file order
    if len(numbers) > PARSE_CAP:
        raise HTTPException(400, f"This file has {len(numbers):,} numbers. Send SMS takes up to {PARSE_CAP:,} from a "
                                 "file \u2014 save it to the Address Book as a group and pick the group instead.")
    return {"numbers": numbers, "total": len(numbers), "skipped": skipped[:svc.SKIPPED_SHOWN],
            "skipped_total": len(skipped), "phone_column": chosen}
