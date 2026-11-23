# backend/tests/test_template_ai.py
"""Write with AI on the Templates page: its own key, masked, and a draft that saves nothing."""
import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.services import template_ai


def _gemini_reply(obj) -> dict:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}], "usage": {}}


GOOD = {
    "name": "Payment Due Reminder!",
    "category": "UTILITY",
    "header_text": "Payment due {{1}}",
    "body_text": "Hi {{1}}, your balance of ₹{{2}} is due. Tap below to pay.",
    "footer_text": "Reply STOP to stop",
    "buttons": [
        {"type": "URL", "text": "Pay now", "url": "http://not-https.example"},
        {"type": "QUICK_REPLY", "text": "Pay now"},
        {"type": "PHONE_NUMBER", "text": "Call us", "phone": "12"},
        {"type": "OTP", "text": "nope"},
    ],
}


class _FakeClient:
    """Stands in for httpx.AsyncClient; `handler(method, url, headers)` returns the response or raises."""

    handler = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        return type(self).handler("POST", url, headers)

    async def get(self, url, headers=None, params=None):
        return type(self).handler("GET", url, headers)


def test_mask_key_never_shows_the_whole_key():
    key = "AIzaSyA1234567890abcdefXYZ"
    masked = template_ai.mask_key(key)
    assert masked.startswith("AIza") and masked.endswith("fXYZ")
    assert "1234567890" not in masked
    assert template_ai.mask_key("short") == "•••••"
    assert template_ai.mask_key(None) == ""


def test_key_is_stored_as_a_secret():
    from app.config_dynamic import SECRET_SETTING_KEYS

    assert template_ai.TEMPLATE_AI_KEY in SECRET_SETTING_KEYS


def test_clean_draft_makes_the_ai_output_safe_for_the_builder():
    d = template_ai.clean_draft(GOOD, language="ta", category=None)
    assert d["name"] == "payment_due_reminder"
    assert d["category"] == "UTILITY"
    assert d["language"] == "ta"
    assert d["header_text"] == "Payment due"  # no variables in the header
    # non-https link replaced, duplicate text dropped, made-up phone and unknown type dropped
    assert d["buttons"] == [{"type": "URL", "text": "Pay now", "url": "https://example.com"}]


def test_clean_draft_keeps_the_owners_category_and_refuses_an_empty_body():
    assert template_ai.clean_draft(GOOD, language="en", category="MARKETING")["category"] == "MARKETING"
    with pytest.raises(ValueError):
        template_ai.clean_draft({**GOOD, "body_text": "  "}, language="en", category=None)


@pytest.mark.asyncio
async def test_draft_retries_once_when_meta_would_refuse_the_body():
    bad = {**GOOD, "body_text": "{{1}}, your balance is due {{2}}"}
    ask = AsyncMock(side_effect=[json.dumps(bad), "```json\n" + json.dumps(GOOD) + "\n```"])
    with patch.object(template_ai, "_ask", ask):
        d = await template_ai.draft_template(api_key="k" * 30, idea="payment reminder", category=None, language="en", tenant_id="t1")
    assert ask.await_count == 2
    assert "Meta would refuse" in ask.await_args_list[1].args[1][-1]["content"]
    assert d["problems"] == []
    assert d["body_text"].startswith("Hi {{1}}")


@pytest.mark.asyncio
async def test_draft_uses_the_template_key_not_the_main_gemini_key():
    seen = {}

    def handler(method, url, headers):
        seen["key"] = headers["x-goog-api-key"]
        return httpx.Response(200, json=_gemini_reply(GOOD), request=httpx.Request(method, url))

    _FakeClient.handler = staticmethod(handler)
    with patch.object(template_ai.httpx, "AsyncClient", _FakeClient), patch.object(template_ai, "_record"), \
         patch("app.config_dynamic.get_setting", side_effect=AssertionError("must not read other settings")):
        await template_ai.draft_template(api_key="template-key-123456789", idea="pay reminder", category=None, language="en", tenant_id="t1")
    assert seen["key"] == "template-key-123456789"


@pytest.mark.asyncio
async def test_a_rejected_key_is_explained_and_not_logged(caplog):
    def handler(method, url, headers):
        req = httpx.Request(method, url)
        raise httpx.HTTPStatusError("bad", request=req, response=httpx.Response(400, text="API key not valid", request=req))

    _FakeClient.handler = staticmethod(handler)
    secret = "AIzaSySECRETSECRETSECRET99"
    with patch.object(template_ai.httpx, "AsyncClient", _FakeClient), caplog.at_level("DEBUG"):
        with pytest.raises(template_ai.TemplateAiError) as e:
            await template_ai.check_key(secret)
    assert "didn't accept this AI key" in str(e.value)
    assert secret not in caplog.text


# ── routes ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_draft_without_a_key_says_where_to_add_it():
    from app.routes.templates import TemplateAiDraftPayload, ai_draft_template

    with patch("app.routes.templates.get_setting", return_value=None):
        with pytest.raises(HTTPException) as e:
            await ai_draft_template(TemplateAiDraftPayload(idea="remind about payment due"), tenant_id="t1", _ctx={})
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "template_ai_key_missing"


@pytest.mark.asyncio
async def test_ai_draft_reads_only_the_template_key_and_saves_nothing():
    from app.routes.templates import TemplateAiDraftPayload, ai_draft_template

    reads = []

    def fake_setting(key, **kw):
        reads.append((key, kw.get("tenant_id")))
        return "template-key-123456789" if key == template_ai.TEMPLATE_AI_KEY else None

    db = MagicMock()
    draft = AsyncMock(return_value={"name": "x", "body_text": "Hi {{1}}, thanks.", "problems": []})
    with patch("app.routes.templates.get_setting", side_effect=fake_setting), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch.object(template_ai, "draft_template", draft):
        out = await ai_draft_template(TemplateAiDraftPayload(idea="thank customers", language="ta"), tenant_id="t1", _ctx={})
    assert out["name"] == "x"
    assert reads == [(template_ai.TEMPLATE_AI_KEY, "t1")]
    assert draft.await_args.kwargs["api_key"] == "template-key-123456789"
    db.table.assert_not_called()


@pytest.mark.asyncio
async def test_ai_draft_refuses_authentication_and_unknown_languages():
    from app.routes.templates import TemplateAiDraftPayload, ai_draft_template

    with pytest.raises(HTTPException) as e:
        await ai_draft_template(TemplateAiDraftPayload(idea="send the login code", category="AUTHENTICATION"), tenant_id="t1", _ctx={})
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        await ai_draft_template(TemplateAiDraftPayload(idea="send the login code", language="xx"), tenant_id="t1", _ctx={})


@pytest.mark.asyncio
async def test_saving_the_key_checks_it_stores_it_secret_and_returns_it_masked():
    from app.routes.templates import TemplateAiKeyPayload, set_template_ai_key

    key = "AIzaSyA1234567890abcdefXYZ"
    db = MagicMock()
    with patch.object(template_ai, "check_key", AsyncMock()) as check, \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.get_setting", return_value=key):
        out = await set_template_ai_key(TemplateAiKeyPayload(api_key=f"  {key} "), tenant_id="t1", _ctx={})
    check.assert_awaited_once_with(key)
    row = db.table.return_value.upsert.call_args.args[0]
    assert row == {"tenant_id": "t1", "key": "template_ai_api_key", "value": key, "is_secret": True, "updated_at": "now()"}
    assert out["is_set"] is True and key not in json.dumps(out)


@pytest.mark.asyncio
async def test_a_key_google_refuses_is_not_saved():
    from app.routes.templates import TemplateAiKeyPayload, set_template_ai_key

    db = MagicMock()
    with patch.object(template_ai, "check_key", AsyncMock(side_effect=template_ai.TemplateAiError("nope", 400))), \
         patch("app.routes.templates.get_supabase", return_value=db):
        with pytest.raises(HTTPException) as e:
            await set_template_ai_key(TemplateAiKeyPayload(api_key="AIzaSyA1234567890abcdefXYZ"), tenant_id="t1", _ctx={})
    assert e.value.status_code == 400
    db.table.assert_not_called()


def test_key_routes_need_templates_manage():
    from app.routes import templates

    for path, method in (("/ai-key", "GET"), ("/ai-key", "PUT"), ("/ai-key", "DELETE"), ("/ai-draft", "POST")):
        route = next(r for r in templates.router.routes if r.path == path and method in r.methods)
        deps = [d.call for d in route.dependant.dependencies]
        assert templates.require_templates_manage in deps, path


def test_general_settings_route_cannot_write_the_key():
    from app.routes import app_settings

    assert '"template_ai_api_key" in payload.updates' in inspect.getsource(app_settings.update_settings)
