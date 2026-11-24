# backend/tests/test_template_ai.py
"""Write with AI inside Create Template: three different drafts on a key Anril sets per client."""
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
SECOND = {**GOOD, "name": "payment_due_reminder", "body_text": "Hello {{1}}! A quick note: ₹{{2}} is pending. Thank you."}
THIRD = {**GOOD, "name": "pay_balance_now", "body_text": "Pay your balance of ₹{{1}} today and you're all set."}
BAD = {**GOOD, "body_text": "{{1}}, your balance is due {{2}}"}


class _FakeClient:
    """Stands in for httpx.AsyncClient; `handler(method, url, headers, json)` returns the response or raises."""

    handler = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        return type(self).handler("POST", url, headers, json)


def _draft_kwargs(**over):
    return {"api_key": "template-key-123456789", "idea": "payment reminder", "category": None, "language": "en",
            "style": "friendly", "goal": "clicks", "business_description": None, "tenant_id": "t1", **over}


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


def test_three_drafts_each_with_its_own_approach_name_and_meta_check():
    raw = "```json\n" + json.dumps({"drafts": [GOOD, SECOND, BAD]}) + "\n```"
    drafts = template_ai._parse_drafts(raw, language="en", category=None)
    assert [d["approach"] for d in drafts] == ["Short and direct", "Warm and personal", "Offer or benefit first"]
    assert len({d["name"] for d in drafts}) == 3  # same name twice would collide on submit
    assert drafts[0]["problems"] == [] and drafts[1]["problems"] == []
    assert any("start" in p for p in drafts[2]["problems"])


@pytest.mark.asyncio
async def test_a_broken_draft_gets_one_fix_and_the_better_version_is_kept():
    first = json.dumps({"drafts": [GOOD, SECOND, BAD]})
    second = json.dumps({"drafts": [BAD, SECOND, THIRD]})  # draft 1 got worse, draft 3 got fixed
    ask = AsyncMock(side_effect=[first, second])
    with patch.object(template_ai, "_ask", ask):
        drafts = await template_ai.draft_templates(**_draft_kwargs())
    assert ask.await_count == 2
    assert "Draft 3:" in ask.await_args_list[1].args[1][-1]["content"]
    assert [d["problems"] for d in drafts] == [[], [], []]
    assert drafts[0]["body_text"] == GOOD["body_text"]
    assert drafts[2]["body_text"] == THIRD["body_text"]


@pytest.mark.asyncio
async def test_the_request_carries_style_goal_language_and_what_the_business_is():
    seen = {}

    def handler(method, url, headers, body):
        seen["key"] = headers["x-goog-api-key"]
        seen["text"] = json.dumps(body, ensure_ascii=False)
        return httpx.Response(200, json=_gemini_reply({"drafts": [GOOD, SECOND, THIRD]}), request=httpx.Request(method, url))

    _FakeClient.handler = staticmethod(handler)
    with patch.object(template_ai.httpx, "AsyncClient", _FakeClient), patch.object(template_ai, "_record"), \
         patch("app.config_dynamic.get_setting", side_effect=AssertionError("must not read other settings")):
        drafts = await template_ai.draft_templates(**_draft_kwargs(
            language="ta", style="festive", goal="replies", business_description="Silk saree shop in Kanchipuram",
        ))
    assert len(drafts) == 3
    assert seen["key"] == "template-key-123456789"
    assert "Silk saree shop in Kanchipuram" in seen["text"]
    assert "Tamil" in seen["text"]
    assert template_ai.STYLES["festive"] in seen["text"]
    assert template_ai.GOALS["replies"] in seen["text"]


@pytest.mark.asyncio
async def test_a_refused_key_points_the_owner_to_anril_support_and_is_not_logged(caplog):
    def handler(method, url, headers, body):
        req = httpx.Request(method, url)
        raise httpx.HTTPStatusError("bad", request=req, response=httpx.Response(400, text="API key not valid", request=req))

    _FakeClient.handler = staticmethod(handler)
    secret = "AIzaSySECRETSECRETSECRET99"
    with patch.object(template_ai.httpx, "AsyncClient", _FakeClient), caplog.at_level("DEBUG"):
        with pytest.raises(template_ai.TemplateAiError) as e:
            await template_ai.draft_templates(**_draft_kwargs(api_key=secret))
    assert str(e.value) == template_ai.KEY_REFUSED_MESSAGE
    assert secret not in caplog.text


# ── routes ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_draft_when_switched_off_says_to_ask_anril():
    from app.routes.templates import TemplateAiDraftPayload, ai_draft_template

    with patch("app.routes.templates.get_setting", return_value=None):
        with pytest.raises(HTTPException) as e:
            await ai_draft_template(TemplateAiDraftPayload(idea="remind about payment due"), tenant_id="t1", _ctx={})
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "template_ai_off"
    assert "Anril support" in e.value.detail["message"]


@pytest.mark.asyncio
async def test_ai_draft_reads_this_tenants_key_and_description_and_saves_nothing():
    from app.routes.templates import TemplateAiDraftPayload, ai_draft_template

    reads = []

    def fake_setting(key, **kw):
        reads.append((key, kw.get("tenant_id")))
        return {"template_ai_api_key": "template-key-123456789", "business_description": "Saree shop"}.get(key)

    db = MagicMock()
    draft = AsyncMock(return_value=[{"name": "x", "body_text": "Hi {{1}}, thanks.", "problems": []}])
    with patch("app.routes.templates.get_setting", side_effect=fake_setting), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch.object(template_ai, "draft_templates", draft):
        out = await ai_draft_template(
            TemplateAiDraftPayload(idea="thank customers", language="ta", style="formal", goal="replies"), tenant_id="t1", _ctx={})
    assert out["drafts"][0]["name"] == "x"
    assert set(reads) == {("template_ai_api_key", "t1"), ("business_description", "t1")}
    kw = draft.await_args.kwargs
    assert (kw["api_key"], kw["business_description"], kw["style"], kw["goal"]) == ("template-key-123456789", "Saree shop", "formal", "replies")
    db.table.assert_not_called()


@pytest.mark.asyncio
async def test_ai_draft_refuses_authentication_unknown_languages_and_styles():
    from app.routes.templates import TemplateAiDraftPayload, ai_draft_template

    for payload in (
        TemplateAiDraftPayload(idea="send the login code", category="AUTHENTICATION"),
        TemplateAiDraftPayload(idea="send the login code", language="xx"),
        TemplateAiDraftPayload(idea="send the login code", style="poetic"),
        TemplateAiDraftPayload(idea="send the login code", goal="views"),
    ):
        with pytest.raises(HTTPException) as e:
            await ai_draft_template(payload, tenant_id="t1", _ctx={})
        assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_ai_status_says_only_whether_it_is_on():
    from app.routes.templates import template_ai_status

    with patch("app.routes.templates.get_setting", return_value="AIzaSyA1234567890abcdefXYZ"):
        out = await template_ai_status(tenant_id="t1", _ctx={})
    assert out == {"enabled": True}


def test_a_business_cannot_set_or_read_the_key():
    from app.routes import app_settings, templates

    paths = {(r.path, m) for r in templates.router.routes for m in r.methods}
    assert ("/ai-key", "PUT") not in paths and ("/ai-key", "DELETE") not in paths and ("/ai-key", "GET") not in paths
    for path, method in (("/ai-status", "GET"), ("/ai-draft", "POST")):
        route = next(r for r in templates.router.routes if r.path == path and method in r.methods)
        assert templates.require_templates_manage in [d.call for d in route.dependant.dependencies], path
    assert '"template_ai_api_key" in payload.updates' in inspect.getsource(app_settings.update_settings)


def test_operator_console_shows_whether_the_template_key_is_set():
    from app.routes import operator

    assert '"ai_template": cred_status(["template_ai_api_key"])' in inspect.getsource(operator.client_config)
