"""Bulk9 callbacks require the tenant secret and a bounded request body."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import sms_webhooks

T = "11111111-1111-1111-1111-111111111111"
app = FastAPI()
app.include_router(sms_webhooks.router)
client = TestClient(app)


def _secret(key, tenant_id=None):
    return "s3cret" if key == "bulk9_webhook_secret" and tenant_id == T else None


def test_bulk9_wrong_or_missing_secret_is_401():
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret), \
         patch.object(sms_webhooks.sms_delivery, "handle_callback") as handle:
        assert client.post(f"/webhook/bulk9/{T}", json={"status": "Delivered"}).status_code == 401
        r = client.post(f"/webhook/bulk9/{T}", json={}, headers={"X-Anril-Webhook-Secret": "nope"})
        assert r.status_code == 401
    handle.assert_not_called()


def test_bulk9_tenant_without_secret_is_401():
    other = "22222222-2222-2222-2222-222222222222"
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret):
        r = client.post(f"/webhook/bulk9/{other}", json={}, headers={"X-Anril-Webhook-Secret": "s3cret"})
    assert r.status_code == 401


def test_bulk9_bad_tenant_id_is_404():
    assert client.post("/webhook/bulk9/not-a-uuid", json={}).status_code == 404


def test_bulk9_accepts_a_list_and_uses_the_url_tenant():
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret), \
         patch.object(sms_webhooks, "get_supabase"), \
         patch.object(sms_webhooks.sms_delivery, "handle_callback", return_value={"status": "ok"}) as handle:
        r = client.post(f"/webhook/bulk9/{T}", json=[{"status": "Delivered", "tenant_id": "evil"}, {"status": "Failed"}],
                        headers={"X-Anril-Webhook-Secret": "s3cret"})
    assert r.status_code == 200 and r.json()["processed"] == 2
    assert all(c.args[1] == T for c in handle.call_args_list)


def test_bulk9_oversized_body_is_413():
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret):
        r = client.post(f"/webhook/bulk9/{T}", content=b"[" + b"1," * 40000 + b"1]",
                        headers={"X-Anril-Webhook-Secret": "s3cret", "content-type": "application/json"})
    assert r.status_code == 413


def test_sms_recharge_webhook_is_removed():
    assert client.post("/webhook/razorpay-sms", json={}).status_code == 404


def test_bulk9_rejects_oversized_stream_without_content_length():
    from starlette.requests import Request
    import asyncio
    chunks = iter([b"x" * 40000, b"x" * 40000, b"x" * 40000])
    read = []

    async def receive():
        chunk = next(chunks)
        read.append(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [
        (b"x-anril-webhook-secret", b"s3cret")], "query_string": b""}, receive)
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret):
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as error:
            asyncio.run(sms_webhooks.bulk9_delivery_webhook(T, request))
    assert error.value.status_code == 413
    assert len(read) == 2
