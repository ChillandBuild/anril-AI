"""Group CSV export and the no-save number parser (routes in app/routes/sms_contacts.py)."""
import io
from unittest.mock import patch

import pytest
from fastapi import HTTPException, UploadFile

from app.routes import sms_contacts as routes
from tests.fake_supabase import FakeSupabase

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"
CTX_A = {"tenant_id": A, "user_id": "ua"}
CTX_B = {"tenant_id": B, "user_id": "ub"}


@pytest.fixture
def db():
    fake = FakeSupabase()
    with patch.object(routes, "get_supabase", lambda: fake):
        yield fake


def _group(db, tenant=A, name="VIP Clients"):
    return db.add("sms_contact_groups", tenant_id=tenant, name=name)["id"]


def _contact(db, phone, gids, name=None, fields=None, tenant=A):
    return db.add("sms_contacts", tenant_id=tenant, phone=phone, name=name, fields=fields or {}, group_ids=gids)


def _upload(text: str | bytes, name="nums.csv") -> UploadFile:
    data = text.encode() if isinstance(text, str) else text
    return UploadFile(file=io.BytesIO(data), filename=name)


def _lines(resp) -> list[str]:
    return resp.body.decode().splitlines()


# ---------------------------------------------------------------- export

@pytest.mark.asyncio
async def test_export_header_rows_extra_fields_and_only_this_group(db):
    g, other = _group(db), _group(db, name="Other")
    _contact(db, "9876543210", [g], "Ravi", {"city": "Chennai", "plan": "gold"})
    _contact(db, "9123456780", [g], "Asha", {"city": "Madurai"})
    _contact(db, "9000000001", [other], "Not in group")
    _contact(db, "9000000002", [], "No group")
    _contact(db, "9000000003", [g], "Other tenant", tenant=B)

    resp = await routes.export_group(g, ctx=CTX_A)
    lines = _lines(resp)
    assert lines[0] == "Name,Mobile,city,plan,Added"
    assert len(lines) == 3
    body = "\n".join(lines[1:])
    assert "Ravi,9876543210,Chennai,gold," in body
    assert "Asha,9123456780,Madurai,," in body
    assert "9000000001" not in body and "9000000002" not in body and "9000000003" not in body
    assert resp.media_type == "text/csv; charset=utf-8"
    assert resp.headers["content-disposition"] == 'attachment; filename="VIP Clients.csv"'


@pytest.mark.asyncio
async def test_export_neutralises_formulas(db):
    g = _group(db)
    _contact(db, "9876543210", [g], "=SUM(A1)", {"note": "@cmd", "x": "+1", "y": "-2"})
    lines = _lines(await routes.export_group(g, ctx=CTX_A))
    assert lines[0] == "Name,Mobile,note,x,y,Added"
    assert lines[1].startswith("'=SUM(A1),9876543210,'@cmd,'+1,'-2,")


@pytest.mark.asyncio
async def test_export_other_tenants_group_is_404(db):
    g = _group(db, tenant=B)
    _contact(db, "9876543210", [g], "Secret", tenant=B)
    with pytest.raises(HTTPException) as e:
        await routes.export_group(g, ctx=CTX_A)
    assert e.value.status_code == 404 and e.value.detail == "Group not found."


@pytest.mark.asyncio
async def test_export_bad_group_id_is_422(db):
    with pytest.raises(HTTPException) as e:
        await routes.export_group("not-a-uuid", ctx=CTX_A)
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_export_filename_is_sanitised_and_pages_past_1000(db):
    g = _group(db, name='../Bad"name\r\n!!')
    for i in range(1001):
        _contact(db, f"9{i:09d}", [g])
    resp = await routes.export_group(g, ctx=CTX_A)
    assert resp.headers["content-disposition"] == 'attachment; filename="Badname.csv"'
    assert len(_lines(resp)) == 1002
    g2 = _group(db, name="!!!")
    assert (await routes.export_group(g2, ctx=CTX_A)).headers["content-disposition"] == \
        'attachment; filename="group.csv"'


# ---------------------------------------------------------------- parse

@pytest.mark.asyncio
async def test_parse_returns_numbers_and_skipped_without_writing(db):
    text = "name,mobile,city\nRavi,+91 98765 43210,Chennai\nAsha,0091 9123456780,x\nBad,12345,y\nDup,9876543210,z\n"
    out = await routes.parse_numbers(_upload(text), phone_column=None, ctx=CTX_A)
    assert out["numbers"] == ["9876543210", "9123456780"]
    assert out["total"] == 2
    assert out["phone_column"] == "mobile"
    assert out["skipped_total"] == 2 and len(out["skipped"]) == 2
    assert {s["row"] for s in out["skipped"]} == {4, 5}
    assert db.tables == {}  # nothing was written (not even an empty table)


@pytest.mark.asyncio
async def test_parse_uses_chosen_phone_column(db):
    text = "mobile,alt\n9876543210,9123456780\n"
    out = await routes.parse_numbers(_upload(text), phone_column="alt", ctx=CTX_A)
    assert out["numbers"] == ["9123456780"] and out["phone_column"] == "alt"


@pytest.mark.asyncio
async def test_parse_over_5000_numbers_is_400(db):
    text = "mobile\n" + "\n".join(f"9{i:09d}" for i in range(5001)) + "\n"
    with pytest.raises(HTTPException) as e:
        await routes.parse_numbers(_upload(text), phone_column=None, ctx=CTX_A)
    assert e.value.status_code == 400
    assert e.value.detail == ("This file has 5,001 numbers. Send SMS takes up to 5,000 from a file — "
                              "save it to the Address Book as a group and pick the group instead.")


@pytest.mark.asyncio
async def test_parse_exactly_5000_is_ok(db):
    text = "mobile\n" + "\n".join(f"9{i:09d}" for i in range(5000)) + "\n"
    out = await routes.parse_numbers(_upload(text), phone_column=None, ctx=CTX_A)
    assert out["total"] == 5000


@pytest.mark.asyncio
async def test_parse_wrong_file_type_is_400(db):
    with pytest.raises(HTTPException) as e:
        await routes.parse_numbers(_upload("hello", "notes.txt"), phone_column=None, ctx=CTX_A)
    assert e.value.status_code == 400
    assert "csv" in e.value.detail


@pytest.mark.asyncio
async def test_parse_too_big_is_413(db):
    big = b"a" * (routes.svc.MAX_BYTES + 1)
    with pytest.raises(HTTPException) as e:
        await routes.parse_numbers(_upload(big, "big.csv"), phone_column=None, ctx=CTX_A)
    assert e.value.status_code == 413


@pytest.mark.asyncio
async def test_export_neutralises_formulas_in_header_cells(db):
    g = _group(db)
    _contact(db, "9876543210", [g], "Ravi", {'=HYPERLINK("http://evil/")': "x"})
    resp = await routes.export_group(g, ctx=CTX_A)
    assert _lines(resp)[0].startswith("Name,Mobile,\"'=HYPERLINK")
