"""DLT Setup (entities, senders, PE-TM binding) and Add credit: client and operator routes."""
import io
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.routes import operator_sms, sms
from app.services import sms_setup
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
CTX = {"tenant_id": T, "api_key": "k", "user_id": "33333333-3333-3333-3333-333333333333"}
ADMIN = {"user_id": "44444444-4444-4444-4444-444444444444"}
ENTITY = "1201160000000012345"


def _db():
    db = FakeSupabase()
    db.add("tenants", id=T, name="Astro Tamil", enabled_features=["sms"])
    db.add("tenants", id=OTHER, name="Other Co", enabled_features=["sms"])
    db.storage = MagicMock()
    db.storage.from_.return_value.create_signed_url.return_value = {"signedURL": "https://signed/x"}
    return db


def _settings(db):
    def get(key, tenant_id=None):
        return next((r["value"] for r in db.rows("app_settings")
                     if r["key"] == key and r.get("tenant_id") == tenant_id), None)
    return get


def _patches(db):
    stack = ExitStack()
    for mod in (sms, operator_sms):
        stack.enter_context(patch.object(mod, "get_supabase", lambda: db))
        stack.enter_context(patch.object(mod, "get_setting", _settings(db)))
    stack.enter_context(patch.object(operator_sms, "record_audit_event", lambda *a, **k: None))
    return stack


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.7\n%..."


def _file(name="proof.png", data=PNG):
    return UploadFile(file=io.BytesIO(data), filename=name)


def _alerts(db, kind):
    return [r for r in db.rows("incidents") if r["type"] == kind]


# ---------------------------------------------------------------- submissions + DLT Manager

@pytest.mark.asyncio
async def test_submitted_entity_shows_as_submitted_until_bulk9_lists_it():
    db = _db()
    add = AsyncMock(return_value={"message": "ok"})
    body = sms.EntityBody(entity_name=" Astro Tamil ", entity_id=f" {ENTITY} ")
    with _patches(db), patch.object(sms.bulk9_client, "add_entity", add), \
            patch.object(sms.bulk9_client, "list_dlt", AsyncMock(return_value={"data": []})):
        await sms.dlt_entity(body, ctx=CTX)
        await sms.dlt_entity(body, ctx=CTX)  # resubmit
        out = await sms.dlt_entities(ctx=CTX)
    # No proof files any more (Bulk9's own form has none); nothing is stored.
    add.assert_awaited_with("k", entity_name="Astro Tamil", entity_id=ENTITY)
    db.storage.from_.return_value.upload.assert_not_called()
    assert len(db.rows("sms_dlt_submissions")) == 1
    assert [(e["entity_id"], e["entity_name"], e["status"]) for e in out["entities"]] == \
        [(ENTITY, "Astro Tamil", "submitted")]

    approved = {"data": [{"sender_id": "ASTROT", "entity_id": ENTITY, "entity_name": "Astro Tamil"}]}
    with _patches(db), patch.object(sms.bulk9_client, "list_dlt", AsyncMock(return_value=approved)):
        out = await sms.dlt_entities(ctx=CTX)
    assert out["entities"][0]["status"] == "approved"
    assert out["senders"] == [{"sender_id": "ASTROT", "entity_id": ENTITY, "entity_name": "Astro Tamil",
                               "status": "approved", "at": None}]


@pytest.mark.asyncio
async def test_bulk9_refusing_an_entity_without_proofs_shows_its_message():
    db = _db()
    with _patches(db), patch.object(sms.bulk9_client, "add_entity",
                                    AsyncMock(side_effect=sms.Bulk9Error("screenshot_links is required"))):
        with pytest.raises(HTTPException) as e:
            await sms.dlt_entity(sms.EntityBody(entity_name="X", entity_id=ENTITY), ctx=CTX)
    assert "screenshot_links is required" in str(e.value.detail) and db.rows("sms_dlt_submissions") == []


@pytest.mark.asyncio
async def test_add_entity_sends_no_screenshot_links():
    request = AsyncMock(return_value={})
    with patch.object(sms.bulk9_client, "_request", request):
        await sms.bulk9_client.add_entity("k", entity_name="Astro Tamil", entity_id=ENTITY)
    assert request.await_args.kwargs["json"] == {"entity_name": "Astro Tamil", "entity_id": ENTITY}


@pytest.mark.asyncio
async def test_submitted_sender_listed_until_approved_and_other_tenants_hidden():
    db = _db()
    db.add("sms_dlt_submissions", tenant_id=OTHER, kind="sender", entity_id=ENTITY, sender_id="OTHERS")
    with _patches(db), patch.object(sms.bulk9_client, "add_sender", AsyncMock(return_value={})), \
            patch.object(sms.bulk9_client, "list_dlt", AsyncMock(return_value={"data": []})):
        await sms.dlt_sender(sms.SenderBody(entity_id=ENTITY, sender_id="astrot"), ctx=CTX)
        out = await sms.dlt_entities(ctx=CTX)
    assert [(s["sender_id"], s["status"]) for s in out["senders"]] == [("ASTROT", "submitted")]


@pytest.mark.asyncio
async def test_bulk9_refusal_records_nothing():
    db = _db()
    with _patches(db), patch.object(sms.bulk9_client, "add_sender",
                                    AsyncMock(side_effect=sms.Bulk9Error("Invalid entity"))):
        with pytest.raises(HTTPException):
            await sms.dlt_sender(sms.SenderBody(entity_id=ENTITY, sender_id="ASTROT"), ctx=CTX)
    assert db.rows("sms_dlt_submissions") == []


@pytest.mark.asyncio
async def test_odd_ids_bulk9_accepted_are_not_recorded():
    """The table only takes digits for entity IDs; a format Bulk9 allowed must not break the add."""
    db = _db()
    with _patches(db), patch.object(sms.bulk9_client, "add_entity", AsyncMock(return_value={})):
        res = await sms.dlt_entity(sms.EntityBody(entity_name="X", entity_id="ABC-1"), ctx=CTX)
    assert res["ok"] and db.rows("sms_dlt_submissions") == []


@pytest.mark.asyncio
async def test_manager_still_lists_submissions_when_bulk9_is_down():
    db = _db()
    db.add("sms_dlt_submissions", tenant_id=T, kind="entity", entity_id=ENTITY, entity_name="Astro Tamil")
    with _patches(db), patch.object(sms.bulk9_client, "list_dlt", AsyncMock(side_effect=sms.Bulk9Timeout())):
        out = await sms.dlt_entities(ctx=CTX)
    assert out["entities"][0]["status"] == "submitted" and out["error"]


# ---------------------------------------------------------------- removed: PE-TM, template requests, checklist

@pytest.mark.asyncio
async def test_status_has_no_pe_tm_gate_fields():
    db = _db()
    with _patches(db):
        out = await sms.status(ctx=CTX)
    assert "checklist" not in out and "pe_tm_info" not in out


def test_pe_tm_and_template_request_routes_are_gone():
    paths = {route.path for route in sms.router.routes}
    assert not {p for p in paths if "pe-tm" in p or "template-requests" in p}


# ---------------------------------------------------------------- Add credit

@pytest.mark.asyncio
async def test_credit_request_alerts_the_operator_and_caps_open_requests():
    db = _db()
    with _patches(db):
        for _ in range(3):
            await sms.credit_request(sms.CreditBody(amount=5000, note="  Diwali blast "), ctx=CTX)
        with pytest.raises(HTTPException) as e:
            await sms.credit_request(sms.CreditBody(amount=500), ctx=CTX)
        assert e.value.status_code == 409
        mine = await sms.credit_list(ctx=CTX)
        assert [r["amount"] for r in mine["items"]] == [5000.0] * 3 and mine["items"][0]["note"] == "Diwali blast"
        assert "Astro Tamil asked for ₹5,000.00 SMS credit: Diwali blast" == \
            _alerts(db, "sms_credit_request")[0]["detail"]["message"]

        open_ = await operator_sms.list_credit_requests(status="open", _admin=ADMIN)
        assert open_["items"][0]["tenant_name"] == "Astro Tamil"
        await operator_sms.finish_credit_request(open_["items"][0]["id"], operator_sms.CreditDoneIn(), ADMIN)
        await sms.credit_request(sms.CreditBody(amount=500), ctx=CTX)  # a slot freed up
    assert sorted(r["status"] for r in db.rows("sms_credit_requests")) == ["done", "open", "open", "open"]


def test_credit_amount_bounds():
    with pytest.raises(ValueError):
        sms.CreditBody(amount=99)
    with pytest.raises(ValueError):
        sms.CreditBody(amount=1_000_001)


@pytest.mark.asyncio
async def test_finishing_a_request_twice_keeps_the_first_outcome():
    db = _db()
    r = db.add("sms_credit_requests", tenant_id=T, amount=500, status="cancelled")
    with _patches(db):
        out = await operator_sms.finish_credit_request(r["id"], operator_sms.CreditDoneIn(), ADMIN)
    assert out["item"]["status"] == "cancelled"


# ---------------------------------------------------------------- hardening (deferred LOW items)

@pytest.mark.asyncio
@pytest.mark.parametrize("name,data", [
    ("proof.png", b"MZ\x90\x00 an exe renamed"),
    ("proof.jpg", PNG),
    ("proof.pdf", b"<html>not a pdf</html>"),
])
async def test_a_file_must_start_with_the_bytes_its_type_promises(name, data):
    db = _db()
    with _patches(db):
        with pytest.raises(HTTPException) as e:
            await sms._save_upload(db, T, _file(name, data), {"png", "jpg", "jpeg", "pdf"})
    assert e.value.status_code == 422 and "isn't a real" in e.value.detail
    db.storage.from_.return_value.upload.assert_not_called()


@pytest.mark.asyncio
async def test_real_png_jpg_and_pdf_are_accepted():
    db = _db()
    with _patches(db):
        for name, data in (("a.png", PNG), ("b.jpeg", b"\xff\xd8\xff\xe0rest"), ("c.pdf", PDF)):
            await sms._save_upload(db, T, _file(name, data), {"png", "jpg", "jpeg", "pdf"})
    assert db.storage.from_.return_value.upload.call_count == 3


@pytest.mark.asyncio
async def test_the_databases_credit_cap_is_a_409_not_a_500():
    """Two requests at the same moment both pass the count; the DB trigger (migration 244) refuses one."""
    db = _db()
    real_table = db.table

    def table(name):
        t = real_table(name)
        if name == "sms_credit_requests":
            def insert(*a, **k):
                raise Exception({"message": "sms_credit_cap: 3 open credit requests", "code": "P0001"})
            t.insert = insert
        return t

    with _patches(db), patch.object(db, "table", table):
        with pytest.raises(HTTPException) as e:
            await sms.credit_request(sms.CreditBody(amount=500), ctx=CTX)
    assert e.value.status_code == 409 and "3 requests waiting" in e.value.detail
    assert _alerts(db, "sms_credit_request") == []
