import hashlib
import hmac
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import payment_razorpay as pr


@pytest.fixture(autouse=True)
def _not_connected_via_oauth(monkeypatch):
    """These tests cover the pasted-keys path; OAuth tokens are tests/test_razorpay_oauth*.py."""
    monkeypatch.setattr(pr.razorpay_oauth, "get_access_token", AsyncMock(return_value=None))


def test_get_key_id_raises_when_not_configured():
    with patch.object(pr, "get_setting", return_value=None):
        with pytest.raises(RuntimeError, match="razorpay_key_id"):
            pr._get_key_id(tenant_id="t-1")


def test_verify_webhook_signature_accepts_matching_hmac():
    with patch.object(pr, "get_setting", return_value="whsec_test"):
        body = b'{"event":"payment_link.paid"}'
        sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
        assert pr.verify_webhook_signature(body, sig) is True


def test_verify_webhook_signature_rejects_mismatched_hmac():
    with patch.object(pr, "get_setting", return_value="whsec_test"):
        assert pr.verify_webhook_signature(b"{}", "deadbeef") is False


def test_verify_webhook_signature_checks_the_given_tenants_own_secret():
    with patch.object(pr, "get_setting", return_value="whsec_test") as get_setting:
        body = b'{"event":"payment_link.paid"}'
        sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
        assert pr.verify_webhook_signature(body, sig, tenant_id="tenant-astro-tamil") is True
    get_setting.assert_called_once_with("razorpay_webhook_secret", tenant_id="tenant-astro-tamil")


@pytest.mark.asyncio
async def test_create_payment_link_returns_url_and_id():
    fake_resp = MagicMock()
    fake_resp.is_success = True
    fake_resp.json.return_value = {"short_url": "https://rzp.io/abc", "id": "plink_123"}

    fake_client = AsyncMock()
    fake_client.post.return_value = fake_resp
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch.object(pr, "get_setting", side_effect=["key_id", "key_secret"]), \
         patch("httpx.AsyncClient", return_value=fake_client):
        result = await pr.create_payment_link(
            idempotency_key="booking:session-1:payment_link",
            notes={"booking_id": "session-1", "booking_ref": "EH-ABC123"},
            amount_paise=2900,
            customer_name="Priya",
            customer_phone="+919876543210",
            description="Consultation — Priya (EH-ABC123)",
            tenant_id="t-1",
        )
    sent_payload = fake_client.post.call_args.kwargs["json"]
    expires_at = result.pop("payment_link_expires_at")
    assert result == {"payment_link_url": "https://rzp.io/abc", "razorpay_payment_link_id": "plink_123"}
    assert datetime.fromisoformat(expires_at) == datetime.fromtimestamp(sent_payload["expire_by"], tz=timezone.utc)
    assert sent_payload["notes"] == {"booking_id": "session-1", "booking_ref": "EH-ABC123"}
    sent_headers = fake_client.post.call_args.kwargs["headers"]
    assert sent_headers["X-Razorpay-Idempotency-Key"] == "booking:session-1:payment_link"


@pytest.mark.asyncio
async def test_create_payment_link_raises_on_failed_response():
    fake_resp = MagicMock()
    fake_resp.is_success = False
    fake_resp.status_code = 400
    fake_resp.text = "bad request"

    fake_client = AsyncMock()
    fake_client.post.return_value = fake_resp
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch.object(pr, "get_setting", side_effect=["key_id", "key_secret"]), \
         patch("httpx.AsyncClient", return_value=fake_client):
        with pytest.raises(RuntimeError, match="Razorpay payment link creation failed"):
            await pr.create_payment_link(
                idempotency_key="booking:session-1:payment_link",
                notes={"booking_id": "session-1", "booking_ref": "EH-ABC123"},
                amount_paise=2900,
                customer_name="Priya", customer_phone="+919876543210",
                description="x", tenant_id="t-1",
            )


def _fake_client(resp=None, error=None):
    client = AsyncMock()
    if error:
        client.post.side_effect = error
    else:
        client.post.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    return client


@pytest.mark.asyncio
async def test_cancel_payment_link_posts_to_the_cancel_endpoint_with_tenant_credentials():
    client = _fake_client(MagicMock(is_success=True))
    with patch.object(pr, "get_setting", side_effect=["key_id", "key_secret"]) as get_setting, \
         patch("httpx.AsyncClient", return_value=client):
        assert await pr.cancel_payment_link("plink_old", "t-1") is True
    assert client.post.call_args.args[0].endswith("/payment_links/plink_old/cancel")
    assert [c.kwargs for c in get_setting.call_args_list] == [{"tenant_id": "t-1"}, {"tenant_id": "t-1"}]


@pytest.mark.asyncio
async def test_cancel_payment_link_returns_false_when_razorpay_refuses_an_already_paid_link():
    resp = MagicMock(is_success=False, status_code=400, text="cannot cancel a paid link")
    with patch.object(pr, "get_setting", side_effect=["key_id", "key_secret"]), \
         patch("httpx.AsyncClient", return_value=_fake_client(resp)):
        assert await pr.cancel_payment_link("plink_paid", "t-1") is False


@pytest.mark.asyncio
async def test_cancel_payment_link_never_raises_on_network_or_config_errors():
    with patch.object(pr, "get_setting", side_effect=["key_id", "key_secret"]), \
         patch("httpx.AsyncClient", return_value=_fake_client(error=RuntimeError("timeout"))):
        assert await pr.cancel_payment_link("plink_x", "t-1") is False
    with patch.object(pr, "get_setting", return_value=None):
        assert await pr.cancel_payment_link("plink_x", "t-1") is False


@pytest.mark.asyncio
async def test_cancel_payment_link_without_an_id_does_nothing():
    with patch("httpx.AsyncClient") as client:
        assert await pr.cancel_payment_link("", "t-1") is False
    client.assert_not_called()
