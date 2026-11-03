"""Operator connection and callback retries keep credentials tenant scoped."""
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from app.routes import operator_sms
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
KEY = "live_key_abcdefghijklmnop"
ADMIN = {"user_id": "prem"}
URL = f"https://anril.example/webhook/bulk9/{T}"


def _db():
    db = FakeSupabase()
    db.add("tenants", id=T, name="Astro Tamil", enabled_features=["sms"])
    return db


def _settings_from(db):
    def get(key, tenant_id=None):
        assert tenant_id is not None, "Never use tenant settings for the trusted webhook host"
        return next((r["value"] for r in db.rows("app_settings")
                     if r["key"] == key and r.get("tenant_id") == tenant_id), None)
    return get


def _patches(db, hooks=None, otp_hooks=None):
    stack = ExitStack()
    for name, value in (("get_supabase", lambda: db), ("get_setting", _settings_from(db)),
                        ("invalidate_cache", lambda *a: None), ("record_audit_event", lambda *a, **k: None)):
        stack.enter_context(patch.object(operator_sms, name, value))
    stack.enter_context(patch.object(operator_sms.env_settings, "public_base_url", "https://anril.example/"))
    stack.enter_context(patch.object(operator_sms.bulk9_client, "wallet", AsyncMock(return_value={"wallet": 900, "sms_count": 50})))
    async def list_hooks(_key, service="sms"):
        return {"data": (otp_hooks if service == "otp" else hooks) or []}
    stack.enter_context(patch.object(operator_sms.bulk9_client, "list_sms_webhooks", AsyncMock(side_effect=list_hooks)))
    for name in ("create_sms_webhook", "update_sms_webhook", "delete_sms_webhook"):
        stack.enter_context(patch.object(operator_sms.bulk9_client, name, AsyncMock(return_value={"status": "success"}), create=True))
    return stack


@pytest.mark.asyncio
async def test_minimal_state_does_not_infer_registration_from_secret():
    db = _db()
    db.add("app_settings", tenant_id=T, key="bulk9_webhook_secret", value="old-secret")
    with _patches(db):
        state = await operator_sms.get_sms(T, ADMIN)
    assert state == {"connected": False, "key_masked": None, "webhook_registered": False, "webhook_error": None,
                     "sms_count": None, "checklist": {"dlt": False, "pe_tm": False, "sender": False}}


@pytest.mark.asyncio
async def test_rejected_key_is_not_saved():
    db = _db()
    with _patches(db), patch.object(operator_sms.bulk9_client, "wallet", AsyncMock(side_effect=Bulk9Error("Invalid key"))):
        with pytest.raises(HTTPException) as exc:
            await operator_sms.save_key(T, operator_sms.KeyIn(api_key=KEY), ADMIN)
    assert exc.value.status_code == 400
    assert db.rows("app_settings") == []


@pytest.mark.asyncio
async def test_good_key_uses_trusted_host_and_never_echoes_secrets():
    db = _db()
    with _patches(db):
        out = await operator_sms.save_key(T, operator_sms.KeyIn(api_key=KEY), ADMIN)
        calls = operator_sms.bulk9_client.create_sms_webhook.await_args_list
    saved = {r["key"]: r for r in db.rows("app_settings")}
    secret = saved["bulk9_webhook_secret"]["value"]
    assert saved["bulk9_api_key"]["is_secret"] and saved["bulk9_webhook_secret"]["is_secret"]
    assert [c.kwargs for c in calls] == [{"url": URL, "secret": secret},
                                         {"url": f"{URL}/otp", "secret": secret, "service": "otp"}]
    assert KEY not in json.dumps(out) and secret not in json.dumps(out)
    assert out == {"connected": True, "key_masked": "live••••••••mnop", "webhook_registered": True, "webhook_error": None,
                   "sms_count": 50, "checklist": {"dlt": False, "pe_tm": False, "sender": False}}


@pytest.mark.asyncio
async def test_retry_updates_existing_callback_without_secret_rotation_or_duplicates():
    db = _db()
    db.add("app_settings", tenant_id=T, key="bulk9_api_key", value=KEY)
    db.add("app_settings", tenant_id=T, key="bulk9_webhook_secret", value="same-secret")
    hooks = [{"id": 11, "url": URL}, {"id": 12, "url": URL}, {"id": 99, "url": "https://other.example/hook"}]
    with _patches(db, hooks, otp_hooks=[{"id": 21, "url": f"{URL}/otp"}]):
        out = await operator_sms.reregister_webhook(T, ADMIN)
        operator_sms.bulk9_client.create_sms_webhook.assert_not_awaited()
        assert [c.args for c in operator_sms.bulk9_client.update_sms_webhook.await_args_list] == [(KEY, 11), (KEY, 21)]
        operator_sms.bulk9_client.update_sms_webhook.assert_awaited_with(
            KEY, 21, url=f"{URL}/otp", secret="same-secret", service="otp")
        operator_sms.bulk9_client.delete_sms_webhook.assert_awaited_once_with(KEY, 12)
    assert out["webhook_registered"]
    assert _settings_from(db)("bulk9_webhook_secret", T) == "same-secret"


@pytest.mark.asyncio
async def test_timeout_is_unconfirmed_and_next_attempt_reuses_secret():
    db = _db()
    with _patches(db), patch.object(operator_sms.bulk9_client, "create_sms_webhook", AsyncMock(side_effect=Bulk9Timeout("timeout"))):
        out = await operator_sms.save_key(T, operator_sms.KeyIn(api_key=KEY), ADMIN)
    secret = _settings_from(db)("bulk9_webhook_secret", T)
    assert not out["webhook_registered"] and out["webhook_error"]
    with _patches(db, [{"id": 10, "url": URL}]):
        out = await operator_sms.reregister_webhook(T, ADMIN)
        operator_sms.bulk9_client.update_sms_webhook.assert_awaited_once_with(KEY, 10, url=URL, secret=secret)
    assert out["webhook_registered"] and out["webhook_error"] is None


@pytest.mark.asyncio
async def test_unknown_list_shape_does_not_create_another_callback():
    db = _db()
    db.add("app_settings", tenant_id=T, key="bulk9_api_key", value=KEY)
    with _patches(db), patch.object(operator_sms.bulk9_client, "list_sms_webhooks", AsyncMock(return_value={"message": "unexpected"})):
        out = await operator_sms.reregister_webhook(T, ADMIN)
        operator_sms.bulk9_client.create_sms_webhook.assert_not_awaited()
    assert not out["webhook_registered"] and out["webhook_error"]


@pytest.mark.asyncio
async def test_template_requests_are_tenant_scoped():
    db = _db()
    db.add("sms_template_requests", id=OTHER, tenant_id=T, status="requested", wording="Hello", reason=None)
    db.add("sms_template_requests", tenant_id=OTHER, status="requested", wording="Private")
    with _patches(db):
        result = await operator_sms.list_template_requests(T, page=1, limit=1, _admin=ADMIN)
        assert result["total"] == 1 and len(result["items"]) == 1
        result = await operator_sms.update_template_request(T, OTHER, operator_sms.RequestUpdateIn(status="ready"), ADMIN)
    assert result["item"]["status"] == "ready"
    assert db.rows("sms_template_requests")[1]["status"] == "requested"


def test_removed_reseller_routes_are_absent():
    assert {route.path for route in operator_sms.router.routes} == {
        "/clients/{tenant_id}/sms", "/clients/{tenant_id}/sms/key", "/clients/{tenant_id}/sms/webhook",
        "/clients/{tenant_id}/sms/checklist",
        "/clients/{tenant_id}/sms/template-requests", "/clients/{tenant_id}/sms/template-requests/{request_id}"}


@pytest.mark.asyncio
async def test_template_request_pagination_counts_all_and_rejects_cross_tenant_updates():
    db = _db()
    db.add("sms_template_requests", tenant_id=T, status="requested", wording="First")
    db.add("sms_template_requests", tenant_id=T, status="requested", wording="Second")
    db.add("sms_template_requests", id=OTHER, tenant_id=OTHER, status="requested", wording="Private")
    with _patches(db):
        result = await operator_sms.list_template_requests(T, page=2, limit=1, _admin=ADMIN)
        assert result["total"] == 2 and result["items"][0]["wording"] == "First"
        with pytest.raises(HTTPException) as error:
            await operator_sms.update_template_request(T, OTHER, operator_sms.RequestUpdateIn(status="ready"), ADMIN)
    assert error.value.status_code == 404
    assert db.rows("sms_template_requests")[2]["status"] == "requested"


@pytest.mark.asyncio
async def test_template_request_rejection_requires_a_reason():
    db = _db()
    with _patches(db), pytest.raises(HTTPException) as error:
        await operator_sms.update_template_request(T, OTHER, operator_sms.RequestUpdateIn(status="rejected", reason="  "), ADMIN)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_checklist_is_saved_audited_and_returned():
    db = _db()
    audits = []
    with _patches(db), patch.object(operator_sms, "record_audit_event", lambda *a, **k: audits.append(k["action"])):
        out = await operator_sms.save_checklist(T, operator_sms.ChecklistIn(dlt=True, pe_tm=True, sender=False), ADMIN)
    saved = {r["key"]: r for r in db.rows("app_settings") if r["tenant_id"] == T}
    assert json.loads(saved["sms_checklist"]["value"]) == {"dlt": True, "pe_tm": True, "sender": False}
    assert out["checklist"] == {"dlt": True, "pe_tm": True, "sender": False}
    assert audits == ["operator.sms_checklist_saved"]
