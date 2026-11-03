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
    stack.enter_context(patch.object(sms_setup, "get_setting", _settings(db)))
    stack.enter_context(patch.object(sms_setup, "invalidate_cache", lambda *a: None))
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


# ---------------------------------------------------------------- PE-TM

@pytest.mark.asyncio
async def test_status_carries_the_tm_to_bind_to():
    db = _db()
    with _patches(db):
        out = await sms.status(ctx=CTX)
    assert out["pe_tm_info"] == {"tm_name": "SID GROUPS PRIVATE LIMITED", "tm_id": "1702178720558766591"}


@pytest.mark.asyncio
async def test_pe_tm_full_flow_turns_sending_on():
    db = _db()
    db.add("app_settings", tenant_id=T, key="sms_checklist", value=json.dumps({"dlt": True, "sender": True}))
    with _patches(db):
        row = await sms.pe_tm_request(sms.PeTmBody(entity_id=f" {ENTITY} "), ctx=CTX)
        assert row["tm_approved_at"] is None and "proof_path" not in row
        assert db.rows("sms_pe_tm")[0]["proof_path"] == ""  # no screenshot: the client says they sent it
        msg = _alerts(db, "sms_pe_tm_proof")[0]["detail"]["message"]
        assert "sent the PE-TM binding request" in msg and ENTITY in msg
        db.storage.from_.return_value.upload.assert_not_called()

        with pytest.raises(HTTPException) as e:  # the client cannot confirm before the TM approval
            await sms.pe_tm_confirm(row["id"], ctx=CTX)
        assert e.value.status_code == 409

        listed = await operator_sms.list_pe_tm(T, ADMIN)
        assert listed["items"][0]["proof_url"] is None  # nothing to sign
        db.storage.from_.return_value.create_signed_url.assert_not_called()
        await operator_sms.approve_pe_tm(T, row["id"], ADMIN)
        done = await sms.pe_tm_confirm(row["id"], ctx=CTX)
    assert done["pe_confirmed_at"]
    assert json.loads(db.rows("app_settings")[0]["value"]) == {"dlt": True, "sender": True, "pe_tm": True}


@pytest.mark.asyncio
async def test_asking_again_keeps_one_row_never_undoes_a_tm_approval_and_a_done_binding_is_locked():
    db = _db()
    body = sms.PeTmBody(entity_id=ENTITY)
    with _patches(db):
        row = await sms.pe_tm_request(body, ctx=CTX)
        again = await sms.pe_tm_request(body, ctx=CTX)
        assert again["id"] == row["id"]
        await operator_sms.approve_pe_tm(T, row["id"], ADMIN)
        after = await sms.pe_tm_request(body, ctx=CTX)  # a double click after the approval
        assert after["tm_approved_at"]
        await sms.pe_tm_confirm(row["id"], ctx=CTX)
        with pytest.raises(HTTPException) as e:
            await sms.pe_tm_request(body, ctx=CTX)
    assert e.value.status_code == 409 and len(db.rows("sms_pe_tm")) == 1


@pytest.mark.asyncio
async def test_pe_tm_is_tenant_scoped_and_validated():
    db = _db()
    other = db.add("sms_pe_tm", tenant_id=OTHER, entity_id=ENTITY, proof_path=f"{OTHER}/x.png",
                   tm_approved_at="2026-11-03T00:00:00+00:00")
    with _patches(db):
        with pytest.raises(HTTPException) as e:
            await sms.pe_tm_confirm(other["id"], ctx=CTX)
        assert e.value.status_code == 404
        with pytest.raises(HTTPException) as e:
            await operator_sms.approve_pe_tm(T, other["id"], ADMIN)
        assert e.value.status_code == 404
        with pytest.raises(HTTPException) as e:
            await sms.pe_tm_request(sms.PeTmBody(entity_id="12ab"), ctx=CTX)
        assert e.value.status_code == 422
        assert (await sms.pe_tm_list(ctx=CTX))["items"] == []


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


# ---------------------------------------------------------------- security review fixes

@pytest.mark.asyncio
async def test_reconfirming_does_not_undo_the_operators_switch_off():
    db = _db()
    with _patches(db):
        row = await sms.pe_tm_request(sms.PeTmBody(entity_id=ENTITY), ctx=CTX)
        await operator_sms.approve_pe_tm(T, row["id"], ADMIN)
        await sms.pe_tm_confirm(row["id"], ctx=CTX)
        db.rows("app_settings")[0]["value"] = json.dumps({"pe_tm": False})  # operator turned sending off
        await sms.pe_tm_confirm(row["id"], ctx=CTX)
    assert json.loads(db.rows("app_settings")[0]["value"]) == {"pe_tm": False}


@pytest.mark.asyncio
async def test_one_unsignable_proof_does_not_break_the_operator_list():
    db = _db()
    db.add("sms_pe_tm", tenant_id=T, entity_id=ENTITY, proof_path=f"{T}/gone.png")
    db.storage.from_.return_value.create_signed_url.side_effect = RuntimeError("missing")
    with _patches(db):
        out = await operator_sms.list_pe_tm(T, ADMIN)
    assert out["items"][0]["proof_url"] is None


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
async def test_asking_again_within_an_hour_rings_the_bell_once_per_entity():
    db = _db()
    with _patches(db):
        for _ in range(3):
            await sms.pe_tm_request(sms.PeTmBody(entity_id=ENTITY), ctx=CTX)
        await sms.pe_tm_request(sms.PeTmBody(entity_id="1201160000000099999"), ctx=CTX)
        assert len(_alerts(db, "sms_pe_tm_proof")) == 2
        # An hour later the same entity rings again (the client is still waiting).
        for r in _alerts(db, "sms_pe_tm_proof"):
            r["created_at"] = "2026-01-01T00:00:00+00:00"
        await sms.pe_tm_request(sms.PeTmBody(entity_id=ENTITY), ctx=CTX)
    assert len(_alerts(db, "sms_pe_tm_proof")) == 3


@pytest.mark.asyncio
async def test_old_screenshot_rows_still_get_a_link_for_the_operator():
    db = _db()
    db.add("sms_pe_tm", tenant_id=T, entity_id=ENTITY, proof_path=f"{T}/old.png")
    with _patches(db):
        out = await operator_sms.list_pe_tm(T, ADMIN)
    assert out["items"][0]["proof_url"] == "https://signed/x"


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
