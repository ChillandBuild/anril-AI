"""The OAuth partner app's webhook: signed with the app secret, routed by account_id, and a
payment whose notes name another tenant's deal is refused. Also: pasted keys stay the
fallback, a 401 on an OAuth token gets one refresh-and-retry, and the generic settings
PATCH can't write the OAuth keys."""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routes import intake
from app.services import payment_razorpay as pr
from app.services import razorpay_oauth as ro
from tests.fake_supabase import FakeSupabase


class _Req:
    def __init__(self, payload: dict, secret: str = "whsec", signature: str | None = None):
        self._body = json.dumps(payload).encode()
        sig = signature if signature is not None else hmac.new(secret.encode(), self._body, hashlib.sha256).hexdigest()
        self.headers = {"x-razorpay-signature": sig}

    async def body(self):
        return self._body

    async def json(self):
        return json.loads(self._body)


def _paid(account_id="acc_A", deal_id="d1"):
    return {
        "event": "payment_link.paid", "account_id": account_id,
        "payload": {"payment_link": {"entity": {"id": "plink_1", "notes": {"deal_id": deal_id}}},
                    "payment": {"entity": {"id": "pay_1"}}},
    }


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(ro.env_settings, "razorpay_oauth_webhook_secret", "whsec")
    monkeypatch.setattr(ro, "_invalidate", lambda: None)
    fake = FakeSupabase()
    fake.add("app_settings", tenant_id="t1", key=ro.KEY_ACCOUNT, value="acc_A")
    fake.add("app_settings", tenant_id="t1", key=ro.KEY_ACCESS, value="tok", is_secret=True)
    monkeypatch.setattr(intake, "get_supabase", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_bad_signature_is_rejected(db):
    with pytest.raises(HTTPException) as e:
        await intake.razorpay_oauth_webhook(_Req(_paid(), signature="0" * 64))
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_paid_event_routes_to_the_connected_tenant(db):
    handle = AsyncMock(return_value={"status": "ok"})
    with patch.object(intake, "_payment_note_tenant_id", return_value="t1"), \
         patch.object(intake, "_handle_deal_payment_event", handle):
        out = await intake.razorpay_oauth_webhook(_Req(_paid()))
    assert out == {"status": "ok"}
    assert handle.await_args.args[1:] == ("payment_link.paid", "d1", "t1")


@pytest.mark.asyncio
async def test_notes_naming_another_tenants_deal_are_refused(db):
    handle = AsyncMock()
    with patch.object(intake, "_payment_note_tenant_id", return_value="t2"), \
         patch.object(intake, "_handle_deal_payment_event", handle):
        with pytest.raises(HTTPException):
            await intake.razorpay_oauth_webhook(_Req(_paid()))
    handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_account_is_ignored(db):
    handle = AsyncMock()
    with patch.object(intake, "_handle_deal_payment_event", handle):
        out = await intake.razorpay_oauth_webhook(_Req(_paid(account_id="acc_unknown")))
    assert out["status"] == "ignored"
    handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_older_than_the_current_connection_is_ignored(db):
    """Our own disconnect's revoke, delivered after the tenant already reconnected."""
    with patch.object(intake.razorpay_oauth, "connected_after", return_value=True):
        out = await intake.razorpay_oauth_webhook(
            _Req({"event": "account.app.authorization_revoked", "account_id": "acc_A", "created_at": 1})
        )
    assert out["status"] == "ignored"
    assert [r for r in db.rows("app_settings") if r["key"] == ro.KEY_ACCESS]


@pytest.mark.asyncio
async def test_signed_non_object_body_is_a_400(db):
    with pytest.raises(HTTPException) as e:
        await intake.razorpay_oauth_webhook(_Req([1, 2]))
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_revoked_in_razorpay_clears_the_tenants_tokens(db):
    with patch.object(intake, "record_audit_event"):
        out = await intake.razorpay_oauth_webhook(
            _Req({"event": "account.app.authorization_revoked", "account_id": "acc_A", "contains": []})
        )
    assert out["status"] == "ok"
    assert not [r for r in db.rows("app_settings") if r["key"].startswith(ro.KEY_PREFIX)]


def _resp(status, body=None):
    r = MagicMock(status_code=status, is_success=200 <= status < 300)
    r.json.return_value = body or {}
    return r


def _client(*responses):
    client = AsyncMock()
    client.post.side_effect = list(responses)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    return client


@pytest.mark.asyncio
async def test_oauth_token_beats_pasted_keys():
    client = _client(_resp(200))
    with patch.object(pr.razorpay_oauth, "get_access_token", AsyncMock(return_value="tok")), \
         patch.object(pr, "get_setting") as keys, \
         patch("httpx.AsyncClient", return_value=client) as ctor:
        await pr._post("t1", "/payment_links/plink_1/cancel")
    assert ctor.call_args.kwargs["auth"] is None
    assert client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
    keys.assert_not_called()


@pytest.mark.asyncio
async def test_pasted_keys_are_the_fallback_and_a_401_is_final():
    client = _client(_resp(401))
    with patch.object(pr.razorpay_oauth, "get_access_token", AsyncMock(return_value=None)), \
         patch.object(pr, "get_setting", side_effect=["k", "s"]), \
         patch("httpx.AsyncClient", return_value=client) as ctor:
        resp = await pr._post("t1", "/payment_links")
    assert resp.status_code == 401
    assert ctor.call_args.kwargs["auth"] == ("k", "s")
    assert client.post.call_count == 1


@pytest.mark.asyncio
async def test_401_on_oauth_token_refreshes_once_and_retries():
    first, second = _client(_resp(401)), _client(_resp(200))
    get_token = AsyncMock(side_effect=["old", "new"])
    with patch.object(pr.razorpay_oauth, "get_access_token", get_token), \
         patch("httpx.AsyncClient", side_effect=[first, second]):
        resp = await pr._post("t1", "/payment_links", json={}, headers={"X-Razorpay-Idempotency-Key": "k"})
    assert resp.status_code == 200
    assert get_token.await_args_list[1].kwargs == {"force_refresh": True}
    retry_headers = second.post.call_args.kwargs["headers"]
    assert retry_headers["Authorization"] == "Bearer new" and retry_headers["X-Razorpay-Idempotency-Key"] == "k"


@pytest.mark.asyncio
async def test_settings_patch_cannot_write_oauth_keys():
    from app.routes.app_settings import SettingsUpdate, update_settings
    payload = SettingsUpdate(updates={"razorpay_oauth_account_id": "acc_victim"})
    with patch("app.routes.app_settings.get_supabase") as get_db:
        with pytest.raises(HTTPException) as e:
            await update_settings(payload, MagicMock(), {"tenant_id": "t1", "role": "owner"}, {"user_id": "u"})
    assert e.value.status_code == 400
    get_db.assert_not_called()


def test_operator_config_cannot_write_oauth_keys():
    from app.routes.operator import ClientConfigUpdate, update_client_config
    with patch("app.routes.operator.get_supabase") as get_db:
        with pytest.raises(HTTPException) as e:
            update_client_config("t1", ClientConfigUpdate(settings={"razorpay_oauth_account_id": "acc_x"}), {})
    assert e.value.status_code == 400
    get_db.assert_not_called()
