"""Connect with Razorpay: the state is single-use, tenant-bound and short-lived; one Razorpay
account maps to one workspace; a refresh that loses a race to another worker uses the
winner's tokens instead of overwriting them; and an OAuth token beats pasted keys."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import razorpay_oauth as ro
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
TOKENS = {
    "access_token": "acc-new", "refresh_token": "ref-new", "public_token": "rzp_test_oauth_x",
    "expires_in": 7862400, "razorpay_account_id": "acc_Dhk2qDbmu6FwZH", "token_type": "Bearer",
}


@pytest.fixture(autouse=True)
def _partner_app(monkeypatch):
    monkeypatch.setattr(ro.env_settings, "razorpay_oauth_client_id", "cid")
    monkeypatch.setattr(ro.env_settings, "razorpay_oauth_client_secret", "csecret")
    monkeypatch.setattr(ro.env_settings, "razorpay_oauth_redirect_uri", "https://app.test/dashboard/settings/razorpay-callback")
    monkeypatch.setattr(ro.env_settings, "razorpay_oauth_webhook_secret", "whsec")
    monkeypatch.setattr(ro.env_settings, "razorpay_oauth_mode", "test")
    monkeypatch.setattr(ro, "_invalidate", lambda: None)


def _settings(db, tenant_id):
    return {r["key"]: r for r in db.rows("app_settings") if r["tenant_id"] == tenant_id}


def _stored_state(db, tenant_id):
    return _settings(db, tenant_id)[ro.KEY_STATE]["value"]


def test_start_builds_consent_url_and_stores_secret_state():
    db = FakeSupabase()
    url = ro.start(db, T1)
    q = parse_qs(urlparse(url).query)
    assert url.startswith(ro.AUTHORIZE_URL)
    assert q["client_id"] == ["cid"] and q["response_type"] == ["code"] and q["scope"] == ["read_write"]
    assert q["redirect_uri"] == ["https://app.test/dashboard/settings/razorpay-callback"]
    assert q["state"] == [_stored_state(db, T1)]
    assert _settings(db, T1)[ro.KEY_STATE]["is_secret"] is True


def test_start_without_partner_app_is_a_clear_503(monkeypatch):
    monkeypatch.setattr(ro.env_settings, "razorpay_oauth_client_id", None)
    with pytest.raises(ro.RazorpayOAuthError) as e:
        ro.start(FakeSupabase(), T1)
    assert e.value.status == 503


@pytest.mark.asyncio
async def test_complete_stores_tokens_and_burns_the_state():
    db = FakeSupabase()
    ro.start(db, T1)
    state = _stored_state(db, T1)
    with patch.object(ro, "_token_request", AsyncMock(return_value=TOKENS)) as tok:
        out = await ro.complete(db, T1, "code-1", state)
    assert out == {"account_id": "acc_Dhk2qDbmu6FwZH"}
    body = tok.await_args.args[0]
    assert body["grant_type"] == "authorization_code" and body["code"] == "code-1" and body["mode"] == "test"
    rows = _settings(db, T1)
    assert rows[ro.KEY_ACCESS]["value"] == "acc-new" and rows[ro.KEY_ACCESS]["is_secret"] is True
    assert rows[ro.KEY_REFRESH]["is_secret"] is True
    assert rows[ro.KEY_ACCOUNT]["is_secret"] is False
    assert ro.KEY_STATE not in rows
    # A replay of the same callback URL can't reuse the state.
    with pytest.raises(ro.RazorpayOAuthError):
        await ro.complete(db, T1, "code-1", state)


@pytest.mark.asyncio
async def test_complete_rejects_wrong_or_other_tenants_state():
    db = FakeSupabase()
    ro.start(db, T1)
    ro.start(db, T2)
    t1_state = _stored_state(db, T1)
    tok = AsyncMock(return_value=TOKENS)
    with patch.object(ro, "_token_request", tok):
        with pytest.raises(ro.RazorpayOAuthError):
            await ro.complete(db, T2, "code", t1_state)
        with pytest.raises(ro.RazorpayOAuthError):
            await ro.complete(db, T1, "code", "guessed")
    tok.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_rejects_expired_state():
    db = FakeSupabase()
    ro.start(db, T1)
    state = _stored_state(db, T1)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _settings(db, T1)[ro.KEY_STATE_EXPIRES]["value"] = past
    with patch.object(ro, "_token_request", AsyncMock(return_value=TOKENS)) as tok:
        with pytest.raises(ro.RazorpayOAuthError):
            await ro.complete(db, T1, "code", state)
    tok.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_already_linked_elsewhere_is_rejected_without_revoking_the_owners_grant():
    db = FakeSupabase()
    db.add("app_settings", tenant_id=T2, key=ro.KEY_ACCOUNT, value="acc_Dhk2qDbmu6FwZH", is_secret=False)
    ro.start(db, T1)
    revoke = AsyncMock(return_value=True)
    with patch.object(ro, "_token_request", AsyncMock(return_value=TOKENS)), patch.object(ro, "_revoke_quietly", revoke):
        with pytest.raises(ro.RazorpayOAuthError) as e:
            await ro.complete(db, T1, "code", _stored_state(db, T1))
    assert e.value.status == 409
    revoke.assert_not_awaited()
    assert ro.KEY_ACCESS not in _settings(db, T1)


def _connected(db, tenant_id=T1, *, days_left=60, refresh="ref-old"):
    expires = (datetime.now(timezone.utc) + timedelta(days=days_left)).isoformat()
    for key, value in ((ro.KEY_ACCESS, "acc-old"), (ro.KEY_REFRESH, refresh), (ro.KEY_EXPIRES, expires),
                       (ro.KEY_ACCOUNT, "acc_Dhk2qDbmu6FwZH")):
        db.add("app_settings", tenant_id=tenant_id, key=key, value=value, is_secret=key in ro.SECRET_KEYS)


@pytest.mark.asyncio
async def test_fresh_token_is_used_without_refresh():
    db = FakeSupabase()
    _connected(db)
    with patch.object(ro, "get_supabase", return_value=db), patch.object(ro, "_token_request", AsyncMock()) as tok:
        assert await ro.get_access_token(T1) == "acc-old"
    tok.assert_not_awaited()


@pytest.mark.asyncio
async def test_not_connected_returns_none():
    db = FakeSupabase()
    with patch.object(ro, "get_supabase", return_value=db):
        assert await ro.get_access_token(T1) is None
        assert await ro.get_access_token(None) is None


@pytest.mark.asyncio
async def test_token_near_expiry_is_refreshed_and_rotated():
    db = FakeSupabase()
    _connected(db, days_left=3)
    new = {**TOKENS, "access_token": "acc-2", "refresh_token": "ref-2"}
    with patch.object(ro, "get_supabase", return_value=db), patch.object(ro, "_token_request", AsyncMock(return_value=new)) as tok:
        assert await ro.get_access_token(T1) == "acc-2"
    assert tok.await_args.args[0] == {"grant_type": "refresh_token", "refresh_token": "ref-old"}
    rows = _settings(db, T1)
    assert rows[ro.KEY_REFRESH]["value"] == "ref-2" and rows[ro.KEY_ACCESS]["value"] == "acc-2"


@pytest.mark.asyncio
async def test_refresh_that_loses_the_race_uses_the_winners_tokens():
    """Both workers read ref-old; the other worker stores ref-win first. Razorpay rejects our
    now-dead refresh token, and we must use the winner's access token, not fail or overwrite."""
    db = FakeSupabase()
    _connected(db, days_left=3)

    async def rejected(_body):
        _settings(db, T1)[ro.KEY_REFRESH]["value"] = "ref-win"
        _settings(db, T1)[ro.KEY_ACCESS]["value"] = "acc-win"
        raise ro.RazorpayOAuthError("rejected", status=502)

    with patch.object(ro, "_token_request", rejected):
        assert await ro.refresh_access_token(db, T1) == "acc-win"
    assert _settings(db, T1)[ro.KEY_REFRESH]["value"] == "ref-win"


@pytest.mark.asyncio
async def test_refresh_where_both_calls_succeed_does_not_overwrite_the_winner():
    db = FakeSupabase()
    _connected(db, days_left=3)

    async def both_succeed(_body):
        _settings(db, T1)[ro.KEY_REFRESH]["value"] = "ref-win"
        _settings(db, T1)[ro.KEY_ACCESS]["value"] = "acc-win"
        return {**TOKENS, "access_token": "acc-lose", "refresh_token": "ref-lose"}

    with patch.object(ro, "_token_request", both_succeed):
        assert await ro.refresh_access_token(db, T1) == "acc-win"
    assert _settings(db, T1)[ro.KEY_REFRESH]["value"] == "ref-win"


@pytest.mark.asyncio
async def test_failed_refresh_of_an_expired_token_raises():
    db = FakeSupabase()
    _connected(db, days_left=-1)
    with patch.object(ro, "get_supabase", return_value=db), \
         patch.object(ro, "_token_request", AsyncMock(side_effect=ro.RazorpayOAuthError("no", 502))):
        with pytest.raises(RuntimeError, match="reconnect Razorpay"):
            await ro.get_access_token(T1)


@pytest.mark.asyncio
async def test_failed_refresh_of_a_still_valid_token_keeps_using_it():
    db = FakeSupabase()
    _connected(db, days_left=3)
    with patch.object(ro, "get_supabase", return_value=db), \
         patch.object(ro, "_token_request", AsyncMock(side_effect=ro.RazorpayOAuthError("no", 502))):
        assert await ro.get_access_token(T1) == "acc-old"


@pytest.mark.asyncio
async def test_disconnect_revokes_both_tokens_and_clears_only_oauth_keys():
    db = FakeSupabase()
    _connected(db)
    db.add("app_settings", tenant_id=T1, key="razorpay_key_id", value="rzp_live_x", is_secret=False)
    revoke = AsyncMock(return_value=True)
    with patch.object(ro, "_revoke_quietly", revoke):
        await ro.disconnect(db, T1)
    assert {c.args for c in revoke.await_args_list} == {("acc-old", "access_token"), ("ref-old", "refresh_token")}
    assert set(_settings(db, T1)) == {"razorpay_key_id"}


def test_tenant_for_account_is_none_when_unknown_or_ambiguous():
    db = FakeSupabase()
    assert ro.tenant_for_account(db, "acc_x") is None
    db.add("app_settings", tenant_id=T1, key=ro.KEY_ACCOUNT, value="acc_x")
    assert ro.tenant_for_account(db, "acc_x") == T1
    db.add("app_settings", tenant_id=T2, key=ro.KEY_ACCOUNT, value="acc_x")
    assert ro.tenant_for_account(db, "acc_x") is None
    assert ro.tenant_for_account(db, None) is None


def test_app_webhook_signature():
    import hashlib
    import hmac
    body = b'{"event":"payment_link.paid"}'
    good = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    assert ro.verify_app_webhook(body, good) is True
    assert ro.verify_app_webhook(body, "0" * 64) is False
    assert ro.verify_app_webhook(body, "") is False


@pytest.mark.asyncio
async def test_junk_state_does_not_burn_a_pending_connect():
    db = FakeSupabase()
    ro.start(db, T1)
    state = _stored_state(db, T1)
    with patch.object(ro, "_token_request", AsyncMock(return_value=TOKENS)):
        with pytest.raises(ro.RazorpayOAuthError):
            await ro.complete(db, T1, "code", "planted-ünïcode")
        assert await ro.complete(db, T1, "code", state) == {"account_id": "acc_Dhk2qDbmu6FwZH"}


@pytest.mark.asyncio
async def test_missing_expires_in_does_not_mean_expired_now():
    db = FakeSupabase()
    ro.start(db, T1)
    tokens = {k: v for k, v in TOKENS.items() if k != "expires_in"}
    with patch.object(ro, "_token_request", AsyncMock(return_value=tokens)):
        await ro.complete(db, T1, "code", _stored_state(db, T1))
    expiry = datetime.fromisoformat(_settings(db, T1)[ro.KEY_EXPIRES]["value"])
    assert expiry - datetime.now(timezone.utc) > timedelta(days=7)


@pytest.mark.asyncio
async def test_refresh_after_a_mid_flight_disconnect_leaves_no_orphan_token():
    db = FakeSupabase()
    _connected(db, days_left=3)

    async def disconnect_meanwhile(_body):
        db.tables["app_settings"] = [r for r in db.rows("app_settings") if r["key"] == ro.KEY_REFRESH]
        return {**TOKENS, "access_token": "acc-2", "refresh_token": "ref-2"}

    with patch.object(ro, "_token_request", disconnect_meanwhile):
        await ro.refresh_access_token(db, T1)
    assert ro.KEY_ACCESS not in _settings(db, T1)


def test_connected_after_compares_the_connect_time_with_the_event_time():
    db = FakeSupabase()
    db.add("app_settings", tenant_id=T1, key=ro.KEY_ACCOUNT, value="acc_x", updated_at="2026-10-30T10:00:00+00:00")
    ten = int(datetime(2026, 10, 30, 10, tzinfo=timezone.utc).timestamp())
    assert ro.connected_after(db, T1, ten - 60) is True
    assert ro.connected_after(db, T1, ten + 60) is False
    assert ro.connected_after(db, T1, None) is False


def test_non_ascii_signature_is_rejected_not_a_crash():
    assert ro.verify_app_webhook(b"{}", "ü" * 64) is False
