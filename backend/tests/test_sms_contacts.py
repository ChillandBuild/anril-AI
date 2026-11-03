"""SMS address book: file/paste parsing, saving, search, groups, and tenant isolation.

The SQL functions (sms_contacts_upsert etc.) are replaced by python stand-ins on FakeSupabase.
"""
import io
from unittest.mock import patch

import pytest
from fastapi import HTTPException, UploadFile

from app.routes import sms_contacts as routes
from app.services import sms_campaigns as camp, sms_contacts as svc
from tests.fake_supabase import FakeSupabase, _Query

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"
CTX_A = {"tenant_id": A, "user_id": "ua"}
CTX_B = {"tenant_id": B, "user_id": "ub"}


class _GroupMissing(Exception):
    code = "P0002"


def _install_rpcs(db: FakeSupabase) -> None:
    def group_ok(tenant, gid):
        return any(g["id"] == gid and g["tenant_id"] == tenant for g in db.rows("sms_contact_groups"))

    def upsert(p):
        t, g = p["p_tenant"], p["p_group"]
        if g is not None and not group_ok(t, g):
            raise _GroupMissing("group not found")
        ins = upd = 0
        for r in p["p_rows"]:
            cur = next((c for c in db.rows("sms_contacts") if c["tenant_id"] == t and c["phone"] == r["phone"]), None)
            if cur:
                cur["name"] = r.get("name") or cur["name"]
                cur["fields"] = {**cur["fields"], **(r.get("fields") or {})}
                if g and g not in cur["group_ids"]:
                    cur["group_ids"] = cur["group_ids"] + [g]
                if p["p_consent_source"]:
                    cur["promo_consent_at"] = "now"
                    cur["promo_consent_source"] = p["p_consent_source"]
                upd += 1
            else:
                db.add("sms_contacts", tenant_id=t, phone=r["phone"], name=r.get("name"), fields=r.get("fields") or {},
                       group_ids=[g] if g else [], promo_consent_at="now" if p["p_consent_source"] else None,
                       promo_consent_source=p["p_consent_source"])
                ins += 1
        return [{"inserted": ins, "updated": upd}]

    def set_group(p):
        t, g = p["p_tenant"], p["p_group"]
        if not group_ok(t, g):
            raise _GroupMissing("group not found")
        n = 0
        for c in db.rows("sms_contacts"):
            if c["tenant_id"] != t or c["id"] not in p["p_ids"]:
                continue
            if p["p_add"] and g not in c["group_ids"]:
                c["group_ids"] = c["group_ids"] + [g]
                n += 1
            elif not p["p_add"] and g in c["group_ids"]:
                c["group_ids"] = [x for x in c["group_ids"] if x != g]
                n += 1
        return n

    def group_delete(p):
        t, g = p["p_tenant"], p["p_group"]
        if not group_ok(t, g):
            return -1
        db.tables["sms_contact_groups"] = [x for x in db.rows("sms_contact_groups") if x["id"] != g]
        n = 0
        if p["p_with_contacts"]:
            gone = [c for c in db.rows("sms_contacts") if c["tenant_id"] == t and c["group_ids"] == [g]]
            n = len(gone)
            db.tables["sms_contacts"] = [c for c in db.rows("sms_contacts") if c not in gone]
        for c in db.rows("sms_contacts"):
            if c["tenant_id"] == t and g in c["group_ids"]:
                c["group_ids"] = [x for x in c["group_ids"] if x != g]
        return n

    def counts(p):
        return [{"group_id": g["id"], "contacts": sum(1 for c in db.rows("sms_contacts")
                                                      if c["tenant_id"] == p["p_tenant"] and g["id"] in c["group_ids"])}
                for g in db.rows("sms_contact_groups") if g["tenant_id"] == p["p_tenant"]]

    db.rpc_handlers.update({"sms_contacts_upsert": upsert, "sms_contacts_set_group": set_group,
                            "sms_group_delete": group_delete, "sms_contact_group_counts": counts})


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    _install_rpcs(fake)
    original = _Query.or_

    def or_with_ilike(self, filter_string):
        """The fake's or_ has no ilike; this test-local wrapper adds case-insensitive contains."""
        if "ilike" not in filter_string:
            return original(self, filter_string)
        clauses = [c.split(".", 2) for c in filter_string.split(",")]
        self.filters.append(lambda r: any(
            (r.get(col) is not None) and v.strip("%").lower() in str(r.get(col)).lower() for col, _, v in clauses))
        return self

    monkeypatch.setattr(_Query, "or_", or_with_ilike)
    with patch.object(routes, "get_supabase", lambda: fake):
        yield fake


def _upload(text: str | bytes, name="people.csv") -> UploadFile:
    data = text.encode() if isinstance(text, str) else text
    return UploadFile(file=io.BytesIO(data), filename=name)


async def _do_upload(text, ctx=CTX_A, name="people.csv", **form):
    args = dict(group_id=None, group_name=None, phone_column=None, name_column=None, consent="false")
    return await routes.upload_contacts(_upload(text, name), **{**args, **form}, ctx=ctx)


# ---------------------------------------------------------------- parsing

def test_header_detection_finds_phone_and_name_columns():
    assert svc.detect_columns(["Customer Name", "Mobile No", "City"]) == ("Mobile No", "Customer Name")
    assert svc.detect_columns(["id", "Phone", "name"]) == ("Phone", "name")
    # "Contact Name" is a name, not the phone column
    assert svc.detect_columns(["Contact Name", "Number"]) == ("Number", "Contact Name")
    assert svc.detect_columns(["a", "b"]) == (None, None)


def test_normalization_skip_reasons_and_duplicates():
    csv_text = "name,mobile\nRavi,+91 98765 43210\nAsha,0091 9123456780\nBad,12345\nDup,9876543210\n,\nTom,5876543210\n"
    headers, rows = svc.read_table(csv_text.encode(), "x.csv")
    contacts, skipped = svc.build_contacts(headers, rows, None, None)
    assert [c["phone"] for c in contacts] == ["9876543210", "9123456780"]
    assert [(s["row"], s["reason"]) for s in skipped] == [
        (4, svc.R_NOT_INDIAN), (5, svc.R_DUPLICATE), (6, svc.R_EMPTY), (7, svc.R_NOT_INDIAN)]


def test_extra_columns_are_cleaned_capped_and_empty_ones_dropped():
    cols = ",".join(f"c{i}" for i in range(25))
    vals = ",".join(["a|b "] + [""] + ["x" * 300] + ["v"] * 22)
    headers, rows = svc.read_table(f"mobile,{cols}\n9876543210,{vals}\n".encode(), "x.csv")
    contacts, _ = svc.build_contacts(headers, rows, None, None)
    fields = contacts[0]["fields"]
    assert fields["c0"] == "ab" and "c1" not in fields and len(fields["c2"]) == 200
    assert len(fields) <= svc.MAX_EXTRA_COLUMNS and "c24" not in fields


def test_xlsx_numbers_stored_as_floats_still_parse():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Phone"])
    ws.append(["Ravi", 9876543210.0])
    buf = io.BytesIO()
    wb.save(buf)
    headers, rows = svc.read_table(buf.getvalue(), "x.xlsx")
    contacts, skipped = svc.build_contacts(headers, rows, None, None)
    assert contacts[0]["phone"] == "9876543210" and not skipped


def test_chosen_column_must_exist_and_missing_phone_column_is_explained():
    headers, rows = svc.read_table(b"a,b\n1,2\n", "x.csv")
    with pytest.raises(camp.SmsError, match="phone number column"):
        svc.build_contacts(headers, rows, None, None)
    with pytest.raises(camp.SmsError, match="not in this file"):
        svc.build_contacts(headers, rows, "zzz", None)


def test_more_than_50000_rows_refused():
    body = "mobile\n" + "9876543210\n" * (svc.MAX_ROWS + 1)
    with pytest.raises(camp.SmsError, match="50,000"):
        svc.read_table(body.encode(), "x.csv")
    ok = "mobile\n" + "9876543210\n" * svc.MAX_ROWS
    assert len(svc.read_table(ok.encode(), "x.csv")[1]) == svc.MAX_ROWS


def test_too_many_columns_refused_and_short_rows_stay_narrow():
    # A huge header used to pad every row to its width: 50k rows x 1M columns ran the server out of memory.
    wide = "mobile," + ",".join(f"c{i}" for i in range(svc.MAX_COLUMNS)) + "\n9876543210\n"
    with pytest.raises(camp.SmsError, match=f"{svc.MAX_COLUMNS} columns"):
        svc.read_table(wide.encode(), "x.csv")
    headers, rows = svc.read_table(b"mobile\n9876543210,a,b,c\n", "x.csv")
    assert rows == [["9876543210"]]


def test_wide_xlsx_rows_are_cut_while_reading():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Phone"])
    ws.cell(row=2, column=1, value="9876543210")
    ws.cell(row=2, column=5000, value="far away")
    buf = io.BytesIO()
    wb.save(buf)
    with patch.object(svc, "MAX_COLUMNS", 3):
        raw = svc._read_xlsx(buf.getvalue())
    assert max(len(r) for r in raw) == 4


def test_xlsx_that_unzips_huge_is_refused():
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", b"0" * (2 * 1024 * 1024))
    with patch.object(svc, "MAX_XLSX_UNZIPPED", 1024 * 1024):
        with pytest.raises(camp.SmsError) as e:
            svc.read_table(buf.getvalue(), "x.xlsx")
    assert e.value.status == 413


def test_csv_cell_too_long_is_a_clean_error():
    big = b"mobile,note\n9876543210,\"" + b"x" * 200_000 + b"\"\n"
    with pytest.raises(camp.SmsError, match="could not read this CSV"):
        svc.read_table(big, "x.csv")


@pytest.mark.asyncio
async def test_file_over_10_mb_refused(db):
    big = b"mobile\n" + b"9" * (svc.MAX_BYTES + 10)
    with pytest.raises(HTTPException) as e:
        await _do_upload(big)
    assert e.value.status_code == 413
    with pytest.raises(camp.SmsError) as e2:
        svc.read_table(big, "x.csv")
    assert e2.value.status == 413


def test_paste_parsing():
    contacts, skipped = svc.parse_paste("9876543210\n\n9123456780, Asha Rao\nabc\n9876543210\n")
    assert contacts == [{"phone": "9876543210", "name": None, "fields": {}},
                        {"phone": "9123456780", "name": "Asha Rao", "fields": {}}]
    assert [(s["row"], s["reason"]) for s in skipped] == [(4, svc.R_NOT_INDIAN), (5, svc.R_DUPLICATE)]
    with pytest.raises(camp.SmsError, match="5,000"):
        svc.parse_paste("9876543210\n" * 5001)


# ---------------------------------------------------------------- upload, consent, paste

@pytest.mark.asyncio
async def test_preview_reports_columns_and_sample(db):
    out = await routes.upload_preview(_upload("Name,Mobile\n" + "Ravi,9876543210\n" * 8), CTX_A)
    assert out["columns"] == ["Name", "Mobile"] and out["phone_column"] == "Mobile" and out["name_column"] == "Name"
    assert len(out["sample"]) == 5 and out["row_count"] == 8


@pytest.mark.asyncio
async def test_upload_into_new_group_writes_consent_source(db):
    out = await _do_upload("Name,Mobile,City\nRavi,9876543210,Pune\nBad,1\n", group_name="Diwali", consent="true")
    assert (out["inserted"], out["updated"], out["skipped_count"]) == (1, 0, 1)
    assert out["skipped"] == [{"row": 3, "value": "1", "reason": svc.R_NOT_INDIAN}]
    row = db.rows("sms_contacts")[0]
    assert row["promo_consent_source"] == "upload:people.csv by ua" and row["fields"] == {"City": "Pune"}
    assert row["group_ids"] == [out["group_id"]] == [db.rows("sms_contact_groups")[0]["id"]]
    # the same group name (any case) is reused, and an existing contact is updated, not duplicated
    again = await _do_upload("Mobile\n9876543210\n", group_name="  diwali ")
    assert again["group_id"] == out["group_id"] and (again["inserted"], again["updated"]) == (0, 1)
    assert len(db.rows("sms_contact_groups")) == 1
    assert db.rows("sms_contacts")[0]["promo_consent_source"] == "upload:people.csv by ua"  # consent is never removed


@pytest.mark.asyncio
async def test_upload_without_consent_stores_no_consent(db):
    await _do_upload("Mobile\n9876543210\n")
    assert db.rows("sms_contacts")[0]["promo_consent_at"] is None


@pytest.mark.asyncio
async def test_paste_and_single_add_consent_sources(db):
    out = await routes.paste_contacts(routes.PasteBody(text="9876543210, Ravi\nnope", consent=True), CTX_A)
    assert (out["inserted"], out["skipped_count"]) == (1, 1)
    assert db.rows("sms_contacts")[0]["promo_consent_source"] == "paste by ua"
    c = await routes.add_contact(routes.ContactBody(phone="91 91234 56780", name="Asha", fields={"k": "v"}, consent=True), CTX_A)
    assert c["phone"] == "9123456780" and c["promo_consent"] is True and c["fields"] == {"k": "v"}
    assert [r for r in db.rows("sms_contacts") if r["phone"] == "9123456780"][0]["promo_consent_source"] == "manual by ua"
    c2 = await routes.add_contact(routes.ContactBody(phone="9000000001"), CTX_A)
    assert c2["promo_consent"] is False


@pytest.mark.asyncio
async def test_single_add_bad_phone_and_missing_group(db):
    with pytest.raises(HTTPException) as e:
        await routes.add_contact(routes.ContactBody(phone="12345"), CTX_A)
    assert (e.value.status_code, e.value.detail) == (422, "Enter a valid 10-digit Indian mobile number.")
    with pytest.raises(HTTPException) as e:
        await routes.add_contact(routes.ContactBody(phone="9876543210", group_id=B), CTX_A)
    assert (e.value.status_code, e.value.detail) == (404, "Group not found.")


@pytest.mark.asyncio
async def test_upsert_group_missing_error_becomes_404(db):
    # The RPC itself raises P0002 (a group id that is valid-looking but not the tenant's)
    with pytest.raises(camp.SmsError) as e:
        svc.save_contacts(db, A, [{"phone": "9876543210", "name": None, "fields": {}}], B, None)
    assert (e.value.status, str(e.value)) == (404, "Group not found.")


# ---------------------------------------------------------------- list / search / filter

@pytest.mark.asyncio
async def test_list_search_and_group_filter(db):
    g = await routes.create_group(routes.GroupBody(name="VIP"), CTX_A)
    await routes.paste_contacts(routes.PasteBody(text="9876543210, Ravi Kumar\n9123456780, Asha"), CTX_A)
    await routes.paste_contacts(routes.PasteBody(text="9000000001, Tom", group_id=g["id"]), CTX_A)
    allc = await routes.list_contacts(ctx=CTX_A, search="", group_id=None, limit=50, offset=0)
    assert allc["total"] == 3
    by_name = await routes.list_contacts(ctx=CTX_A, search="rAVi", group_id=None, limit=50, offset=0)
    assert [c["name"] for c in by_name["items"]] == ["Ravi Kumar"]
    by_phone = await routes.list_contacts(ctx=CTX_A, search="91234", group_id=None, limit=50, offset=0)
    assert [c["phone"] for c in by_phone["items"]] == ["9123456780"]
    in_group = await routes.list_contacts(ctx=CTX_A, search="", group_id=g["id"], limit=50, offset=0)
    assert [c["name"] for c in in_group["items"]] == ["Tom"]
    page = await routes.list_contacts(ctx=CTX_A, search="", group_id=None, limit=2, offset=2)
    assert len(page["items"]) == 1 and page["total"] == 3
    assert set(allc["items"][0]) == {"id", "phone", "name", "fields", "group_ids", "promo_consent", "created_at"}


def test_search_filter_strips_postgrest_special_characters():
    flt = svc.search_filter('a,b(c)%*"d')
    assert flt == "name.ilike.%a b c d%"  # one clause; the user's text cannot add another
    assert svc.search_filter(" ,() ") is None
    assert svc.search_filter("98 76") == "name.ilike.%98 76%,phone.ilike.%9876%"


# ---------------------------------------------------------------- groups

@pytest.mark.asyncio
async def test_group_create_duplicate_rename_and_counts(db):
    g = await routes.create_group(routes.GroupBody(name="Diwali"), CTX_A)
    with pytest.raises(HTTPException) as e:
        await routes.create_group(routes.GroupBody(name=" diwali "), CTX_A)
    assert (e.value.status_code, e.value.detail) == (409, "A group with this name already exists.")
    other = await routes.create_group(routes.GroupBody(name="Holi"), CTX_A)
    with pytest.raises(HTTPException) as e:
        await routes.rename_group(other["id"], routes.GroupBody(name="DIWALI"), CTX_A)
    assert e.value.status_code == 409
    assert (await routes.rename_group(g["id"], routes.GroupBody(name="Diwali"), CTX_A))["name"] == "Diwali"  # own name is fine
    await routes.paste_contacts(routes.PasteBody(text="9876543210", group_id=g["id"]), CTX_A)
    groups = (await routes.list_groups(CTX_A))["groups"]
    assert [(x["name"], x["contacts"]) for x in groups] == [("Holi", 0), ("Diwali", 1)]  # newest first


@pytest.mark.asyncio
async def test_add_and_remove_contacts_from_group(db):
    g = await routes.create_group(routes.GroupBody(name="VIP"), CTX_A)
    await routes.paste_contacts(routes.PasteBody(text="9876543210\n9123456780"), CTX_A)
    ids = [c["id"] for c in db.rows("sms_contacts")]
    assert (await routes.add_to_group(g["id"], routes.IdsBody(ids=ids), CTX_A)) == {"changed": 2}
    assert (await routes.add_to_group(g["id"], routes.IdsBody(ids=ids), CTX_A)) == {"changed": 0}
    assert (await routes.remove_from_group(g["id"], routes.IdsBody(ids=ids[:1]), CTX_A)) == {"changed": 1}
    with pytest.raises(HTTPException) as e:
        await routes.add_to_group("not-a-uuid", routes.IdsBody(ids=ids), CTX_A)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_group_keeps_or_deletes_its_contacts(db):
    keep = await routes.create_group(routes.GroupBody(name="Keep"), CTX_A)
    drop = await routes.create_group(routes.GroupBody(name="Drop"), CTX_A)
    other = await routes.create_group(routes.GroupBody(name="Other"), CTX_A)
    await routes.paste_contacts(routes.PasteBody(text="9876543210", group_id=keep["id"]), CTX_A)
    await routes.paste_contacts(routes.PasteBody(text="9123456780", group_id=drop["id"]), CTX_A)
    await routes.paste_contacts(routes.PasteBody(text="9000000001", group_id=drop["id"]), CTX_A)
    await routes.paste_contacts(routes.PasteBody(text="9000000001", group_id=other["id"]), CTX_A)  # in two groups
    assert await routes.delete_group(keep["id"], False, CTX_A) == {"deleted_contacts": 0}
    assert len(db.rows("sms_contacts")) == 3 and db.rows("sms_contacts")[0]["group_ids"] == []
    assert await routes.delete_group(drop["id"], True, CTX_A) == {"deleted_contacts": 1}
    left = {c["phone"]: c["group_ids"] for c in db.rows("sms_contacts")}
    assert set(left) == {"9876543210", "9000000001"} and left["9000000001"] == [other["id"]]
    with pytest.raises(HTTPException) as e:
        await routes.delete_group(drop["id"], False, CTX_A)
    assert (e.value.status_code, e.value.detail) == (404, "Group not found.")


# ---------------------------------------------------------------- tenant isolation

@pytest.mark.asyncio
async def test_tenant_cannot_touch_another_tenants_contacts_or_groups(db):
    gb = await routes.create_group(routes.GroupBody(name="B list"), CTX_B)
    await routes.paste_contacts(routes.PasteBody(text="9876543210, Bee", group_id=gb["id"]), CTX_B)
    b_contact = db.rows("sms_contacts")[0]
    # list: A sees nothing, whatever the filter
    for kw in ({}, {"search": "bee"}, {"group_id": gb["id"]}):
        out = await routes.list_contacts(ctx=CTX_A, **{"search": "", "group_id": None, "limit": 50, "offset": 0, **kw})
        assert out == {"items": [], "total": 0}
    assert (await routes.list_groups(CTX_A))["groups"] == []
    # delete contacts
    assert await routes.delete_contacts(routes.IdsBody(ids=[b_contact["id"]]), CTX_A) == {"deleted": 0}
    assert len(db.rows("sms_contacts")) == 1
    # regroup: A cannot add B's contact to A's group, nor use B's group
    ga = await routes.create_group(routes.GroupBody(name="A list"), CTX_A)
    assert await routes.add_to_group(ga["id"], routes.IdsBody(ids=[b_contact["id"]]), CTX_A) == {"changed": 0}
    assert b_contact["group_ids"] == [gb["id"]]
    for fn in (routes.add_to_group, routes.remove_from_group):
        with pytest.raises(HTTPException) as e:
            await fn(gb["id"], routes.IdsBody(ids=[b_contact["id"]]), CTX_A)
        assert e.value.status_code == 404
    # rename / delete B's group
    with pytest.raises(HTTPException) as e:
        await routes.rename_group(gb["id"], routes.GroupBody(name="hijacked"), CTX_A)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await routes.delete_group(gb["id"], True, CTX_A)
    assert e.value.status_code == 404
    assert [g["name"] for g in db.rows("sms_contact_groups")] == ["B list", "A list"] and len(db.rows("sms_contacts")) == 1
    # upload into / paste into B's group
    with pytest.raises(HTTPException) as e:
        await _do_upload("Mobile\n9111111111\n", group_id=gb["id"])
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await routes.paste_contacts(routes.PasteBody(text="9111111111", group_id=gb["id"]), CTX_A)
    assert e.value.status_code == 404
    # the same phone in two tenants is two separate contacts
    await routes.paste_contacts(routes.PasteBody(text="9876543210, Ay"), CTX_A)
    assert sorted((c["tenant_id"], c["name"]) for c in db.rows("sms_contacts")) == [(A, "Ay"), (B, "Bee")]
