"""Signed partner sends: AstroTamil's Django backend sends an approved template
(by its 6-digit Aira ID) or free text to its app users from the tenant's number."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routes.intake import public_router

app = FastAPI()
app.include_router(public_router, prefix="/api/v1/intake")
client = TestClient(app)

TENANT = "0f897915-2d34-4b67-8d69-f83f52e4fb6c"
SECRET = "bridge-secret"
PNID = "pnid-primary"
UNAUTHORIZED = {"error": "Unauthorized", "code": "unauthorized"}
TEMPLATE_URL = "/api/v1/intake/partner/send-template"
TEXT_URL = "/api/v1/intake/partner/send-text"

APPROVED = {
    "name": "question_received",
    "language": "ta",
    "status": "APPROVED",
    "body_text": "Hi {{1}}, your question {{2}} was received.",
    "header_text": None,
    "buttons": [],
}


def _signed(body: dict, secret: str = SECRET) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-astro-signature": f"sha256={sig}", "content-type": "application/json"}


def _db(template=None, lead=None, inbound_pnid=None):
    db = MagicMock()
    templates = MagicMock()
    templates.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[template] if template else [])
    )
    phones = MagicMock()
    phones.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"meta_phone_number_id": PNID}])
    )
    leads = MagicMock()
    leads.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        MagicMock(data=lead) if lead else None
    )
    # The lead's last inbound number (none stored -> the primary is used).
    leads.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"last_inbound_phone_number_id": inbound_pnid}] if inbound_pnid else [])
    )
    messages = MagicMock()
    settings = MagicMock()  # no partner_send_mode saved: the account sends by template ID
    settings.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    tables = {
        "message_templates": templates, "phone_numbers": phones, "leads": leads, "messages": messages,
        "app_settings": settings,
    }
    db.table.side_effect = lambda name: tables[name]
    db.messages = messages
    return db


def _post(url, body, db, secret=SECRET, send=None, send_text=None, header_name=None):
    raw, headers = _signed(body)
    if header_name:  # sign under a different header name (canonical vs legacy)
        headers = {header_name: headers.pop("x-astro-signature"), **headers}
    send = send or AsyncMock(return_value={"messages": [{"id": "wamid.T1"}]})
    send_text = send_text or AsyncMock(return_value="wamid.X1")
    with patch("app.routes.intake.astro_bridge.get_bridge_secret", return_value=secret), \
         patch("app.db.supabase.get_supabase", return_value=db), \
         patch("app.services.meta_cloud.send_template_message", send), \
         patch("app.services.ai_reply.send_whatsapp", send_text):
        res = client.post(url, content=raw, headers=headers)
    return res, send, send_text


def _template_body(**over):
    body = {"tenant_id": TENANT, "template_code": "407940", "phone": "919876543210",
            "variables": ["Rajan", "#5412"], "reference": "question:5412"}
    body.update(over)
    return body


# ------------------------------------------------------------------ auth

def test_missing_signature_is_401():
    with patch("app.routes.intake.astro_bridge.get_bridge_secret", return_value=SECRET):
        res = client.post(TEMPLATE_URL, json=_template_body())
    assert res.status_code == 401
    assert res.json() == UNAUTHORIZED


def test_bad_signature_is_401():
    raw, _ = _signed(_template_body())
    with patch("app.routes.intake.astro_bridge.get_bridge_secret", return_value=SECRET), \
         patch("app.services.meta_cloud.send_template_message", AsyncMock()) as send:
        res = client.post(TEMPLATE_URL, content=raw,
                          headers={"x-astro-signature": "sha256=" + "0" * 64, "content-type": "application/json"})
    assert res.status_code == 401
    assert res.json() == UNAUTHORIZED
    send.assert_not_awaited()


def test_unknown_tenant_gets_the_same_401():
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), secret=None)
    assert res.status_code == 401
    assert res.json() == UNAUTHORIZED
    send.assert_not_awaited()


def test_missing_tenant_never_reads_a_secret():
    """An empty id would resolve to the default tenant's secret in get_setting."""
    body = _template_body()
    del body["tenant_id"]
    raw, headers = _signed(body)
    with patch("app.routes.intake.astro_bridge.get_bridge_secret") as get_secret:
        res = client.post(TEMPLATE_URL, content=raw, headers=headers)
    assert res.status_code == 401
    assert res.json() == UNAUTHORIZED
    get_secret.assert_not_called()


def test_non_json_is_400():
    res = client.post(TEMPLATE_URL, content=b"not json",
                      headers={"x-astro-signature": "sha256=x", "content-type": "application/json"})
    assert res.status_code == 400
    assert res.json() == {"error": "Invalid JSON", "code": "invalid_json"}


def test_text_route_checks_the_signature_too():
    raw, _ = _signed({"tenant_id": TENANT, "phone": "9876543210", "text": "hi"}, secret="wrong")
    with patch("app.routes.intake.astro_bridge.get_bridge_secret", return_value=SECRET):
        res = client.post(TEXT_URL, content=raw,
                          headers={"x-astro-signature": "sha256=abc", "content-type": "application/json"})
    assert res.status_code == 401
    assert res.json() == UNAUTHORIZED


def test_legacy_prefix_serves_the_same_route():
    legacy = FastAPI()
    legacy.include_router(public_router, prefix="/api/v1/expert-handoff")
    with patch("app.routes.intake.astro_bridge.get_bridge_secret", return_value=SECRET):
        res = TestClient(legacy).post("/api/v1/expert-handoff/partner/send-template", json=_template_body())
    assert res.status_code == 401


# ------------------------------------------------------------------ send-template

def test_template_happy_path():
    db = _db(APPROVED)
    res, send, _ = _post(TEMPLATE_URL, _template_body(), db)
    assert res.status_code == 200
    assert res.json() == {
        "ok": True, "message_id": "wamid.T1",
        "template": {"code": "407940", "name": "question_received", "language": "ta"},
    }
    send.assert_awaited_once_with(
        to_number="+919876543210",
        template_name="question_received",
        lang_code="ta",
        components=[{"type": "body", "parameters": [
            {"type": "text", "text": "Rajan"}, {"type": "text", "text": "#5412"},
        ]}],
        tenant_id=TENANT,
        phone_number_id=PNID,
    )


def test_send_goes_from_the_number_the_lead_messaged_not_the_primary():
    """After a failover the primary changes, but the lead's chat is with the
    number they messaged -- the reply must come from that one."""
    db = _db(APPROVED, inbound_pnid="pnid-old-red")
    res, send, _ = _post(TEMPLATE_URL, _template_body(), db)
    assert res.status_code == 200
    assert send.await_args.kwargs["phone_number_id"] == "pnid-old-red"


def test_the_canonical_header_name_is_accepted():
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), header_name="x-aira-signature")
    assert res.status_code == 200, res.text
    send.assert_awaited_once()


def test_the_anril_header_name_is_accepted():
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), header_name="x-anril-signature")
    assert res.status_code == 200, res.text
    send.assert_awaited_once()


def test_a_bad_signature_under_the_anril_name_is_401():
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), secret="other", header_name="x-anril-signature")
    assert res.status_code == 401
    send.assert_not_awaited()


def test_the_legacy_header_name_still_works():
    # AstroTamil's Django signs under the original name; _signed() uses it by default.
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), header_name="x-astro-signature")
    assert res.status_code == 200, res.text
    send.assert_awaited_once()


def test_a_bad_signature_under_the_canonical_name_is_401():
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), secret="other", header_name="x-aira-signature")
    assert res.status_code == 401
    send.assert_not_awaited()


def test_template_lookup_is_tenant_scoped():
    db = _db(APPROVED)
    _post(TEMPLATE_URL, _template_body(), db)
    chain = db.table("message_templates").select.return_value
    chain.eq.assert_called_once_with("tenant_id", TENANT)
    chain.eq.return_value.eq.assert_called_once_with("short_code", "407940")


def test_template_without_variables_sends_no_components():
    tpl = dict(APPROVED, body_text="Your question was received.")
    res, send, _ = _post(TEMPLATE_URL, _template_body(variables=None), _db(tpl))
    assert res.status_code == 200
    assert send.await_args.kwargs["components"] is None


def test_template_not_found_is_404():
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(None))
    assert res.status_code == 404
    assert res.json()["code"] == "template_not_found"
    assert res.json()["ok"] is False
    assert res.json()["error"] == "No template with Anril ID 407940"
    send.assert_not_awaited()


def test_pending_template_is_409():
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(dict(APPROVED, status="PENDING")))
    assert res.status_code == 409
    assert res.json() == {"ok": False, "code": "template_not_approved", "error": "Template status is PENDING"}
    send.assert_not_awaited()


def test_variable_count_mismatch_is_400():
    res, send, _ = _post(TEMPLATE_URL, _template_body(variables=["Rajan"]), _db(APPROVED))
    assert res.status_code == 400
    assert res.json() == {"ok": False, "code": "variables_mismatch", "error": "Template expects 2 variable(s), got 1"}
    send.assert_not_awaited()


def test_extra_variables_are_dropped_to_the_template_count():
    # The partner always sends its fixed set ({{1}} name, {{2}} service) without
    # knowing how many placeholders the template uses — extras are not an error.
    tpl = dict(APPROVED, body_text="Hi {{1}}, your astrologer has replied.")
    res, send, _ = _post(TEMPLATE_URL, _template_body(variables=["Rajan", "Free Question"]), _db(tpl))
    assert res.status_code == 200
    assert send.await_args.kwargs["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "Rajan"}]},
    ]


def test_variables_sent_to_a_template_without_placeholders_are_ignored():
    tpl = dict(APPROVED, body_text="Your astrologer has replied.")
    res, send, _ = _post(TEMPLATE_URL, _template_body(variables=["Rajan", "Free Question"]), _db(tpl))
    assert res.status_code == 200
    assert send.await_args.kwargs["components"] is None


def test_header_variable_template_is_unsupported():
    tpl = dict(APPROVED, header_text="Hello {{1}}")
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(tpl))
    assert res.status_code == 400
    assert res.json()["code"] == "unsupported_template"
    send.assert_not_awaited()


def test_dynamic_url_button_template_is_unsupported():
    tpl = dict(APPROVED, buttons=[{"type": "URL", "text": "Open", "url": "https://x.in/q/{{1}}"}])
    res, send, _ = _post(TEMPLATE_URL, _template_body(), _db(tpl))
    assert res.status_code == 400
    assert res.json()["code"] == "unsupported_template"
    send.assert_not_awaited()


def test_static_url_button_is_fine():
    tpl = dict(APPROVED, buttons=[{"type": "URL", "text": "Open", "url": "https://x.in/app"}])
    res, _, _ = _post(TEMPLATE_URL, _template_body(), _db(tpl))
    assert res.status_code == 200


def test_invalid_phone_is_400():
    res, send, _ = _post(TEMPLATE_URL, _template_body(phone="12345"), _db(APPROVED))
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_phone"
    send.assert_not_awaited()


def test_foreign_number_without_plus_is_sent():
    res, send, _ = _post(TEMPLATE_URL, _template_body(phone="94771234567"), _db(APPROVED))
    assert res.status_code == 200
    assert send.await_args.kwargs["to_number"] == "+94771234567"


def test_meta_rejection_is_502():
    send = AsyncMock(side_effect=HTTPException(status_code=400, detail='{"error":"131026"}'))
    res, _, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), send=send)
    assert res.status_code == 502
    assert res.json() == {"ok": False, "code": "meta_error", "error": '{"error":"131026"}'}


def test_unexpected_send_error_is_502():
    send = AsyncMock(side_effect=RuntimeError("timeout"))
    res, _, _ = _post(TEMPLATE_URL, _template_body(), _db(APPROVED), send=send)
    assert res.status_code == 502
    assert res.json()["error"] == "timeout"


def test_no_message_id_is_502():
    send = AsyncMock(return_value={"messages": []})
    db = _db(APPROVED, lead={"id": "lead-1"})
    res, _, _ = _post(TEMPLATE_URL, _template_body(), db, send=send)
    assert res.status_code == 502
    assert res.json()["error"] == "no message id"
    db.messages.insert.assert_not_called()


def test_existing_lead_gets_the_send_in_its_chat():
    db = _db(APPROVED, lead={"id": "lead-1"})
    res, _, _ = _post(TEMPLATE_URL, _template_body(), db)
    assert res.status_code == 200
    db.table("leads").select.return_value.eq.assert_any_call("tenant_id", TENANT)
    db.table("leads").select.return_value.eq.return_value.eq.assert_any_call("phone", "+919876543210")
    db.messages.insert.assert_called_once_with({
        "lead_id": "lead-1",
        "tenant_id": TENANT,
        "direction": "outbound",
        "channel": "whatsapp",
        "content": "Hi Rajan, your question #5412 was received.",
        "is_ai_generated": False,
        "meta_message_id": "wamid.T1",
        "reply_source": "automation",
        "delivery_status": "sent",
    })


def test_unknown_number_is_sent_but_never_becomes_a_lead():
    db = _db(APPROVED, lead=None)
    res, send, _ = _post(TEMPLATE_URL, _template_body(), db)
    assert res.status_code == 200
    send.assert_awaited_once()
    db.messages.insert.assert_not_called()


def test_a_failing_chat_log_never_fails_the_send():
    db = _db(APPROVED, lead={"id": "lead-1"})
    db.messages.insert.side_effect = RuntimeError("23514")
    res, _, _ = _post(TEMPLATE_URL, _template_body(), db)
    assert res.status_code == 200
    assert res.json()["message_id"] == "wamid.T1"


# ------------------------------------------------------------------ send-text

def _text_body(**over):
    body = {"tenant_id": TENANT, "phone": "+919876543210", "text": "  Your answer is ready  ", "reference": "q:1"}
    body.update(over)
    return body


def test_text_happy_path():
    db = _db(lead={"id": "lead-1"})
    res, _, send_text = _post(TEXT_URL, _text_body(), db)
    assert res.status_code == 200
    assert res.json() == {"ok": True, "message_id": "wamid.X1"}
    send_text.assert_awaited_once_with("+919876543210", "Your answer is ready", tenant_id=TENANT, phone_number_id=PNID)
    assert db.messages.insert.call_args[0][0]["content"] == "Your answer is ready"
    assert db.messages.insert.call_args[0][0]["meta_message_id"] == "wamid.X1"


def test_empty_text_is_400():
    res, _, send_text = _post(TEXT_URL, _text_body(text="   "), _db())
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_request"
    send_text.assert_not_awaited()


def test_overlong_text_is_400():
    res, _, send_text = _post(TEXT_URL, _text_body(text="a" * 4097), _db())
    assert res.status_code == 400
    send_text.assert_not_awaited()


def test_text_invalid_phone_is_400():
    res, _, _ = _post(TEXT_URL, _text_body(phone="abc"), _db())
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_phone"


def test_text_send_failure_is_502():
    """Outside the 24h window Meta refuses free text; send_whatsapp returns None."""
    with patch("app.services.ai_reply.get_last_send_error", return_value="Re-engagement message"):
        res, _, _ = _post(TEXT_URL, _text_body(), _db(), send_text=AsyncMock(return_value=None))
    assert res.status_code == 502
    assert res.json() == {"ok": False, "code": "meta_error", "error": "Re-engagement message"}


def test_text_send_exception_is_502():
    res, _, _ = _post(TEXT_URL, _text_body(), _db(), send_text=AsyncMock(side_effect=RuntimeError("boom")))
    assert res.status_code == 502
    assert res.json()["code"] == "meta_error"
