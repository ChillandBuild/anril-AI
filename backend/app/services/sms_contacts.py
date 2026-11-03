"""SMS address book: parsing CSV / Excel / pasted numbers, saving through the sms_contacts_upsert
function, and the group helpers. Routes live in app/routes/sms_contacts.py.

Everything here is scoped by tenant_id. User-facing problems raise camp.SmsError (message + HTTP
status). Phone numbers are never logged.
"""
import csv
import io
import logging
import re
import uuid
from typing import Any

from app.services import sms_campaigns as camp

logger = logging.getLogger(__name__)

MAX_ROWS = 50_000
MAX_BYTES = 10 * 1024 * 1024
MAX_EXTRA_COLUMNS = 20
MAX_COLUMNS = 100  # a wider file is refused; rows are cut to this width while reading
MAX_XLSX_UNZIPPED = 100 * 1024 * 1024  # an .xlsx is a zip: refuse one that unpacks huge
MAX_CELL_CHARS = 200
MAX_PASTE_LINES = 5_000
CHUNK = 1_000
SKIPPED_SHOWN = 1_000
SAMPLE_ROWS = 5

R_NOT_INDIAN = "Not an Indian mobile number"
R_DUPLICATE = "Duplicate number in this file"
R_EMPTY = "Empty row"
GROUP_NOT_FOUND = "Group not found."
DUPLICATE_GROUP = "A group with this name already exists."

# Header keywords, strongest first.
_PHONE_WORDS = ("mobile", "phone", "number", "contact")
_NAME_WORDS = ("name",)


# ---------------------------------------------------------------- small helpers

def clean_cell(value: Any) -> str:
    """A cell as short plain text: no '|' (it separates values in a message), trimmed, capped."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel stores 9876543210 as 9876543210.0
    return str(value).replace("|", "").strip()[:MAX_CELL_CHARS]


def clean_fields(fields: dict | None) -> dict[str, str]:
    """Extra columns for one contact: cleaned keys and values, empty values dropped, at most 20."""
    out: dict[str, str] = {}
    for k, v in (fields or {}).items():
        key, val = clean_cell(k), clean_cell(v)
        if key and val and key not in out:
            out[key] = val
        if len(out) >= MAX_EXTRA_COLUMNS:
            break
    return out


def as_uuid(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _is_group_missing(e: Exception) -> bool:
    return getattr(e, "code", None) == "P0002" or "P0002" in str(e)


def consent_source(kind: str, user_id: str | None, filename: str | None = None) -> str:
    who = user_id or "unknown"
    if kind == "upload":
        return f"upload:{filename or 'file'} by {who}"
    return f"{kind} by {who}"


# ---------------------------------------------------------------- reading a file

def _unique_headers(raw: list) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, h in enumerate(raw):
        name = clean_cell(h) or f"Column {i + 1}"
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return out


def _too_many() -> camp.SmsError:
    return camp.SmsError(f"A file can have at most {MAX_ROWS:,} rows. Split it and upload the parts one by one.")


def _read_csv(data: bytes) -> list[list[Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = []
    try:
        for row in csv.reader(io.StringIO(text), dialect):
            rows.append(row[:MAX_COLUMNS + 1])
            if len(rows) > MAX_ROWS + 1:
                raise _too_many()
    except csv.Error:
        raise camp.SmsError("We could not read this CSV file. Check that it is a plain .csv and try again.")
    return rows


def _read_xlsx(data: bytes) -> list[list[Any]]:
    import zipfile
    from openpyxl import load_workbook
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            unzipped = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile:
        raise camp.SmsError("We could not read this Excel file. Save it as .xlsx or .csv and try again.")
    if unzipped > MAX_XLSX_UNZIPPED:
        raise camp.SmsError("This Excel file is too large once opened. Save it as .csv and try again.", 413)
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise camp.SmsError("We could not read this Excel file. Save it as .xlsx or .csv and try again.")
    try:
        sheet = wb.worksheets[0]
        rows = []
        for row in sheet.iter_rows(max_col=MAX_COLUMNS + 1, values_only=True):
            rows.append(list(row))
            if len(rows) > MAX_ROWS + 1:
                raise _too_many()
    finally:
        wb.close()
    return rows


def read_table(data: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
    """(headers, data rows as lists of raw text). The first row of the file is the header."""
    if not data:
        raise camp.SmsError("This file is empty.")
    if len(data) > MAX_BYTES:
        raise camp.SmsError("This file is larger than 10 MB.", 413)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "csv":
        raw = _read_csv(data)
    elif ext == "xlsx":
        raw = _read_xlsx(data)
    else:
        raise camp.SmsError("Upload a .csv or .xlsx file.")
    # Skip blank lines above the header.
    while raw and not any(clean_cell(c) for c in raw[0]):
        raw.pop(0)
    if not raw:
        raise camp.SmsError("This file is empty.")
    header = list(raw[0])
    while header and not clean_cell(header[-1]):
        header.pop()  # Excel pads rows with empty cells
    if len(header) > MAX_COLUMNS:
        raise camp.SmsError(f"A file can have at most {MAX_COLUMNS} columns.")
    headers = _unique_headers(header)
    width = len(headers)
    body = []
    for row in raw[1:]:
        cells = [("" if c is None else (str(int(c)) if isinstance(c, float) and c.is_integer() else str(c)))
                 for c in row[:width]]
        cells += [""] * (width - len(cells))
        body.append(cells)
    if len(body) > MAX_ROWS:
        raise _too_many()
    return headers, body


def detect_columns(headers: list[str]) -> tuple[str | None, str | None]:
    """(phone column, name column) by header words. "Contact Name" is a name, not a phone."""
    lowered = [h.lower() for h in headers]
    phone = name = None
    for word in _PHONE_WORDS:
        for h, low in zip(headers, lowered):
            if word in low and "name" not in low:
                phone = h
                break
        if phone:
            break
    for word in _NAME_WORDS:
        for h, low in zip(headers, lowered):
            if word in low and h != phone:
                name = h
                break
        if name:
            break
    return phone, name


def preview(data: bytes, filename: str) -> dict:
    headers, rows = read_table(data, filename)
    phone, name = detect_columns(headers)
    return {"columns": headers, "phone_column": phone, "name_column": name,
            "sample": [[clean_cell(c) for c in r] for r in rows[:SAMPLE_ROWS]], "row_count": len(rows)}


# ---------------------------------------------------------------- turning rows into contacts

def build_contacts(headers: list[str], rows: list[list[str]], phone_column: str | None,
                   name_column: str | None) -> tuple[list[dict], list[dict]]:
    """(contacts [{phone, name, fields}], skipped [{row, value, reason}]). `row` is the line number in
    the file (the header is row 1). The first copy of a repeated number is kept."""
    auto_phone, auto_name = detect_columns(headers)
    phone_column = phone_column or auto_phone
    name_column = name_column or auto_name
    if not phone_column:
        raise camp.SmsError("We could not find the phone number column. Choose it from the list.")
    for chosen in (phone_column, name_column):
        if chosen and chosen not in headers:
            raise camp.SmsError(f"The column \"{chosen[:60]}\" is not in this file.")
    pi = headers.index(phone_column)
    ni = headers.index(name_column) if name_column else None
    extras = [(i, h) for i, h in enumerate(headers) if i != pi and i != ni][:MAX_EXTRA_COLUMNS]

    contacts, skipped, seen = [], [], set()
    for n, row in enumerate(rows, start=2):
        if not any(c.strip() for c in row):
            skipped.append({"row": n, "value": "", "reason": R_EMPTY})
            continue
        raw = row[pi].strip()
        phone = camp.normalize_indian_mobile(raw)
        if not phone:
            skipped.append({"row": n, "value": raw[:40], "reason": R_NOT_INDIAN})
        elif phone in seen:
            skipped.append({"row": n, "value": raw[:40], "reason": R_DUPLICATE})
        else:
            seen.add(phone)
            contacts.append({
                "phone": phone,
                "name": (clean_cell(row[ni]) or None) if ni is not None else None,
                "fields": clean_fields({h: row[i] for i, h in extras}),
            })
    return contacts, skipped


def parse_paste(text: str) -> tuple[list[dict], list[dict]]:
    """One contact per line: "9876543210" or "9876543210, Ravi". Blank lines are ignored."""
    lines = [(n, ln) for n, ln in enumerate((text or "").splitlines(), start=1) if ln.strip()]
    if not lines:
        raise camp.SmsError("Paste at least one number.")
    if len(lines) > MAX_PASTE_LINES:
        raise camp.SmsError(f"Paste at most {MAX_PASTE_LINES:,} lines at a time.")
    contacts, skipped, seen = [], [], set()
    for n, line in lines:
        parts = re.split(r"\s*[,\t]\s*", line.strip(), maxsplit=1)
        raw, name = parts[0], (parts[1] if len(parts) > 1 else "")
        phone = camp.normalize_indian_mobile(raw)
        if not phone:
            skipped.append({"row": n, "value": raw[:40], "reason": R_NOT_INDIAN})
        elif phone in seen:
            skipped.append({"row": n, "value": raw[:40], "reason": R_DUPLICATE})
        else:
            seen.add(phone)
            contacts.append({"phone": phone, "name": clean_cell(name) or None, "fields": {}})
    return contacts, skipped


# ---------------------------------------------------------------- saving

def save_contacts(db, tenant_id: str, contacts: list[dict], group_id: str | None,
                  consent_source_text: str | None) -> dict:
    """Upsert through the sms_contacts_upsert function in chunks of 1,000 -> {inserted, updated}."""
    inserted = updated = 0
    for i in range(0, len(contacts), CHUNK):
        try:
            res = db.rpc("sms_contacts_upsert", {
                "p_tenant": tenant_id, "p_rows": contacts[i:i + CHUNK],
                "p_group": group_id, "p_consent_source": consent_source_text}).execute()
        except Exception as e:
            if _is_group_missing(e):
                raise camp.SmsError(GROUP_NOT_FOUND, 404)
            logger.exception("sms contacts: upsert failed for tenant %s", tenant_id)
            raise camp.SmsError("Could not save the contacts. Some may have been saved; upload again to finish.", 500)
        row = (res.data[0] if isinstance(res.data, list) and res.data else res.data) or {}
        inserted += int(row.get("inserted") or 0)
        updated += int(row.get("updated") or 0)
    return {"inserted": inserted, "updated": updated}


def import_result(db, tenant_id: str, contacts: list[dict], skipped: list[dict], group_id: str | None,
                  consent_source_text: str | None) -> dict:
    saved = save_contacts(db, tenant_id, contacts, group_id, consent_source_text) if contacts else \
        {"inserted": 0, "updated": 0}
    return {**saved, "skipped_count": len(skipped), "skipped": skipped[:SKIPPED_SHOWN], "group_id": group_id}


def import_file(db, tenant_id: str, data: bytes, filename: str, *, group_id: str | None,
                group_name: str | None, phone_column: str | None, name_column: str | None,
                consent_source_text: str | None) -> dict:
    headers, rows = read_table(data, filename)
    contacts, skipped = build_contacts(headers, rows, phone_column, name_column)
    if group_id:
        get_group(db, tenant_id, group_id)
    elif group_name and group_name.strip():
        group_id = get_or_create_group(db, tenant_id, group_name)["id"]
    return import_result(db, tenant_id, contacts, skipped, group_id, consent_source_text)


def import_paste(db, tenant_id: str, text: str, group_id: str | None, consent_source_text: str | None) -> dict:
    contacts, skipped = parse_paste(text)
    if group_id:
        get_group(db, tenant_id, group_id)
    return import_result(db, tenant_id, contacts, skipped, group_id, consent_source_text)


def contact_json(row: dict) -> dict:
    return {"id": row["id"], "phone": row["phone"], "name": row.get("name"), "fields": row.get("fields") or {},
            "group_ids": row.get("group_ids") or [], "promo_consent": row.get("promo_consent_at") is not None,
            "created_at": row.get("created_at")}


def set_group(db, tenant_id: str, group_id: str, ids: list[str], add: bool) -> int:
    try:
        res = db.rpc("sms_contacts_set_group", {
            "p_tenant": tenant_id, "p_group": group_id, "p_ids": ids, "p_add": add}).execute()
    except Exception as e:
        if _is_group_missing(e):
            raise camp.SmsError(GROUP_NOT_FOUND, 404)
        raise
    return int(res.data or 0)


def delete_contacts(db, tenant_id: str, ids: list[str]) -> int:
    deleted = 0
    for i in range(0, len(ids), 200):  # ids ride in the URL: keep it short
        res = db.table("sms_contacts").delete().eq("tenant_id", tenant_id).in_("id", ids[i:i + 200]).execute()
        deleted += len(res.data or [])
    return deleted


# ---------------------------------------------------------------- groups

def _group_name(name: str) -> str:
    name = (name or "").strip()
    if not 1 <= len(name) <= 80:
        raise camp.SmsError("A group name must be 1 to 80 characters.")
    return name


def find_group_by_name(db, tenant_id: str, name: str, exclude_id: str | None = None) -> dict | None:
    wanted = name.strip().lower()
    rows = db.table("sms_contact_groups").select("*").eq("tenant_id", tenant_id).execute().data or []
    for r in rows:
        if r["id"] != exclude_id and (r.get("name") or "").strip().lower() == wanted:
            return r
    return None


def get_group(db, tenant_id: str, group_id: str) -> dict:
    gid = as_uuid(group_id)
    rows = (db.table("sms_contact_groups").select("*").eq("tenant_id", tenant_id).eq("id", gid)
            .limit(1).execute().data or []) if gid else []
    if not rows:
        raise camp.SmsError(GROUP_NOT_FOUND, 404)
    return rows[0]


def create_group(db, tenant_id: str, name: str) -> dict:
    name = _group_name(name)
    if find_group_by_name(db, tenant_id, name):
        raise camp.SmsError(DUPLICATE_GROUP, 409)
    try:
        row = db.table("sms_contact_groups").insert({"tenant_id": tenant_id, "name": name}).execute().data[0]
    except Exception:
        # Two people creating the same name at once: the unique index refuses the second.
        if find_group_by_name(db, tenant_id, name):
            raise camp.SmsError(DUPLICATE_GROUP, 409)
        raise
    return row


def get_or_create_group(db, tenant_id: str, name: str) -> dict:
    name = _group_name(name)
    return find_group_by_name(db, tenant_id, name) or create_group(db, tenant_id, name)


def rename_group(db, tenant_id: str, group_id: str, name: str) -> dict:
    name = _group_name(name)
    group = get_group(db, tenant_id, group_id)
    if find_group_by_name(db, tenant_id, name, exclude_id=group["id"]):
        raise camp.SmsError(DUPLICATE_GROUP, 409)
    db.table("sms_contact_groups").update({"name": name}).eq("tenant_id", tenant_id).eq("id", group["id"]).execute()
    return {**group, "name": name}


def list_groups(db, tenant_id: str) -> list[dict]:
    rows = (db.table("sms_contact_groups").select("*").eq("tenant_id", tenant_id)
            .order("created_at", desc=True).execute().data or [])
    counts = {c["group_id"]: int(c.get("contacts") or 0)
              for c in (db.rpc("sms_contact_group_counts", {"p_tenant": tenant_id}).execute().data or [])}
    return [{"id": r["id"], "name": r["name"], "contacts": counts.get(r["id"], 0), "created_at": r.get("created_at")}
            for r in rows]


def delete_group(db, tenant_id: str, group_id: str, with_contacts: bool) -> int:
    gid = as_uuid(group_id)
    if not gid:
        raise camp.SmsError(GROUP_NOT_FOUND, 404)
    res = db.rpc("sms_group_delete", {"p_tenant": tenant_id, "p_group": gid, "p_with_contacts": with_contacts}).execute()
    n = int(res.data if res.data is not None else -1)
    if n < 0:
        raise camp.SmsError(GROUP_NOT_FOUND, 404)
    return n


# ---------------------------------------------------------------- listing

def search_filter(search: str) -> str | None:
    """A PostgREST or_ filter for phone (digits) or name (contains), or None for an empty search.
    The user's text has , ( ) % * \\ and quotes removed so it cannot change the filter's shape."""
    text = " ".join(re.sub(r'[,()%*\\"]', " ", search or "").split())
    if not text:
        return None
    clauses = [f"name.ilike.%{text}%"]
    digits = re.sub(r"\D", "", text)
    if digits:
        clauses.append(f"phone.ilike.%{digits}%")
    return ",".join(clauses)


def list_contacts(db, tenant_id: str, *, search: str, group_id: str | None, limit: int, offset: int) -> dict:
    q = db.table("sms_contacts").select("*", count="exact").eq("tenant_id", tenant_id)
    if group_id:
        gid = as_uuid(group_id)
        if not gid:
            return {"items": [], "total": 0}
        q = q.contains("group_ids", [gid])
    flt = search_filter(search)
    if flt:
        q = q.or_(flt)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"items": [contact_json(r) for r in res.data or []], "total": res.count or 0}
