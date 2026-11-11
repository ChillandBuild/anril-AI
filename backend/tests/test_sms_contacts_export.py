"""Group CSV export (route in app/routes/sms_contacts.py)."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

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


@pytest.mark.asyncio
async def test_export_neutralises_formulas_in_header_cells(db):
    g = _group(db)
    _contact(db, "9876543210", [g], "Ravi", {'=HYPERLINK("http://evil/")': "x"})
    resp = await routes.export_group(g, ctx=CTX_A)
    assert _lines(resp)[0].startswith("Name,Mobile,\"'=HYPERLINK")
