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


def test_bulk9_secret_in_body_is_accepted_and_stripped():
    """Bulk9 dropped the custom header on live callbacks, so the registered body carries it."""
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret), \
         patch.object(sms_webhooks, "get_supabase"), \
         patch.object(sms_webhooks.sms_delivery, "handle_callback", return_value={"status": "ok"}) as handle:
        r = client.post(f"/webhook/bulk9/{T}", json={"anril_secret": "s3cret", "request_id": "SAbc", "status": "Delivered",
                                                      "failure_reason": "@{{failure_reason}}", "udf1": "{{udf1}}", "mobile": ""})
    assert r.status_code == 200
    item = handle.call_args.args[2]
    assert item == {"request_id": "SAbc", "status": "Delivered"}  # secret, unfilled and empty values gone


def test_bulk9_wrong_body_secret_or_empty_body_is_401():
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret), \
         patch.object(sms_webhooks.sms_delivery, "handle_callback") as handle:
        assert client.post(f"/webhook/bulk9/{T}", json={"anril_secret": "nope", "status": "Delivered"}).status_code == 401
        # One item without the secret fails the whole list.
        assert client.post(f"/webhook/bulk9/{T}", json=[{"anril_secret": "s3cret"}, {"status": "Failed"}]).status_code == 401
        # What Bulk9 sent on 2026-11-04: no body, no header.
        assert client.post(f"/webhook/bulk9/{T}", content=b"").status_code == 401
        assert client.post(f"/webhook/bulk9/{T}", json={"anril_secret": ["s3cret"]}).status_code == 401
    handle.assert_not_called()


def test_bulk9_header_secret_with_bad_json_is_400():
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret):
        r = client.post(f"/webhook/bulk9/{T}", content=b"not json",
                        headers={"X-Anril-Webhook-Secret": "s3cret", "content-type": "application/json"})
    assert r.status_code == 400


def test_otp_webhook_accepts_body_secret():
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret), \
         patch.object(sms_webhooks, "get_supabase"), \
         patch.object(sms_webhooks.sms_delivery, "handle_otp_callback", return_value={"status": "ok"}) as handle:
        r = client.post(f"/webhook/bulk9/{T}/otp", json={"anril_secret": "s3cret", "request_id": "SOtp1", "status": "Delivered"})
    assert r.status_code == 200 and "anril_secret" not in handle.call_args.args[2]


def test_registered_webhook_has_a_body_template_with_the_secret():
    import json
    from app.services import bulk9_client
    body = bulk9_client._webhook_body("sms", "https://example.test/webhook/bulk9/x", "s3cret")
    tpl = json.loads(body["payload"])
    assert tpl["anril_secret"] == "s3cret"
    assert tpl["request_id"] == "@{{request_id}}" and tpl["udf1"] == "@{{udf1}}" and tpl["status"] == "@{{status}}"
    assert body["headers"] == {"X-Anril-Webhook-Secret": "s3cret"} and body["template"] == "custom"


def test_send_reply_is_kept_small():
    from app.services.sms_campaigns import send_reply
    assert send_reply({"return": True, "request_id": "SAbc"}) == {"return": True, "request_id": "SAbc"}
    assert send_reply({"x": "y" * 5000})["truncated"] is True


def test_bulk9_lone_surrogate_secret_is_401_not_500():
    with patch.object(sms_webhooks, "get_setting", side_effect=_secret):
        r = client.post(f"/webhook/bulk9/{T}", content=b'{"anril_secret": "\\ud800"}',
                        headers={"content-type": "application/json"})
    assert r.status_code == 401
