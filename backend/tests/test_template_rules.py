# backend/tests/test_template_rules.py
"""Meta's template rules, enforced before a template is sent for review."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from app.services import template_rules as rules
from app.services.meta_cloud import build_core_components, _build_button_components


# ── body ─────────────────────────────────────────────────────────────────────

def test_clean_body_has_no_problems():
    assert rules.body_problems("Hi {{1}}, your visit is on {{2}}. See you!") == []


def test_body_with_no_variables_has_no_problems():
    assert rules.body_problems("vanakkam thanks bye.") == []


@pytest.mark.parametrize("text, expected", [
    ("{{1}} is your code today", "start"),
    ("Your code is {{1}}", "end"),
    ("Hi {{1}}, see you on {{3}} today", "no gaps"),
    ("Hi {{name}}, see you today", "isn't a numbered variable"),
    ("Hi {{1}, see you today", "missing a brace"),
])
def test_body_rule_violations(text, expected):
    assert any(expected in p for p in rules.body_problems(text))


# ── header, footer, url ──────────────────────────────────────────────────────

def test_header_allows_one_variable_only():
    assert rules.header_problems("Hi {{1}}") == []
    assert rules.header_problems("Hi {{1}} and {{2}}") == ["The header can hold only one variable."]


def test_footer_cannot_hold_variables():
    assert rules.footer_problems("Aira Clinic") == []
    assert rules.footer_problems("From {{1}}") == ["The footer can't contain variables."]


@pytest.mark.parametrize("url, ok", [
    ("https://aira.clinic/book", True),
    ("https://aira.clinic/book/{{1}}", True),
    ("http://aira.clinic", False),
    ("https://aira.clinic/{{1}}/book", False),
    ("https://aira.clinic/{{1}}/{{2}}", False),
])
def test_url_rules(url, ok):
    assert (rules.url_problems(url) == []) is ok


# ── samples ──────────────────────────────────────────────────────────────────

def test_samples_are_returned_in_variable_order():
    assert rules.samples_for("Hi {{1}} on {{2}}.", ["Priya", "14 Oct"], "message body") == ["Priya", "14 Oct"]


def test_missing_sample_names_the_variable():
    with pytest.raises(ValueError, match=r"\{\{2\}\} in the message body"):
        rules.samples_for("Hi {{1}} on {{2}}.", ["Priya", "  "], "message body")


def test_url_example_is_full_link_with_sample():
    assert rules.url_with_sample("https://a.co/b/{{1}}", "AB12") == "https://a.co/b/AB12"
    assert rules.url_with_sample("https://a.co/b", None) == "https://a.co/b"
    with pytest.raises(ValueError):
        rules.url_with_sample("https://a.co/b/{{1}}", "")


# ── Meta payload uses the client's samples, never invented ones ──────────────

def test_core_components_use_client_samples():
    comps = build_core_components(
        "Hi {{1}}, see you on {{2}}.", ["Priya", "14 Oct"],
        header_text="Hello {{1}}", header_example="Priya",
        footer_text="Aira Clinic",
    )
    body = next(c for c in comps if c["type"] == "BODY")
    header = next(c for c in comps if c["type"] == "HEADER")
    assert body["example"] == {"body_text": [["Priya", "14 Oct"]]}
    assert header["example"] == {"header_text": ["Priya"]}
    assert "Sample text" not in str(comps) and "Rajan Kumar" not in str(comps)


def test_core_components_refuse_missing_header_sample():
    with pytest.raises(ValueError, match="header"):
        build_core_components("Hi there, welcome.", None, header_text="Hello {{1}}")


def test_url_button_example_uses_sample():
    out = _build_button_components(
        [{"type": "URL", "text": "Book", "url": "https://a.co/book/{{1}}", "url_example": "X9"}], 10
    )
    assert out[0]["example"] == ["https://a.co/book/X9"]


# ── create route refuses before contacting Meta ──────────────────────────────

def _db(rows_by_body=None):
    """Name lookups find nothing; the duplicate-wording lookup finds rows_by_body."""
    db = MagicMock()

    def second_eq(field, _value):
        chain = MagicMock()
        chain.execute.return_value.data = (rows_by_body or []) if field == "body_text" else []
        return chain

    db.table.return_value.select.return_value.eq.return_value.eq.side_effect = second_eq
    db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "row-1"}]
    return db


@pytest.mark.asyncio
async def test_create_refuses_missing_sample_without_calling_meta():
    from app.routes.templates import create_template, CreateTemplate

    payload = CreateTemplate(name="visit", category="UTILITY", body_text="Hi {{1}}, see you soon.")
    submit = MagicMock()
    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=_db()), \
         patch("app.routes.templates.submit_template", submit):
        with pytest.raises(HTTPException) as exc:
            await create_template(payload, tenant_id="t1")
    assert exc.value.status_code == 400
    assert "{{1}}" in exc.value.detail
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_create_refuses_footer_variable_and_bad_link():
    from app.routes.templates import create_template, CreateTemplate, Button

    payload = CreateTemplate(
        name="visit", category="UTILITY", body_text="Hi there, see you soon.",
        footer_text="From {{1}}",
        buttons=[Button(type="URL", text="Book", url="https://a.co/{{1}}/x", url_example="7")],
    )
    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=_db()):
        with pytest.raises(HTTPException) as exc:
            await create_template(payload, tenant_id="t1")
    assert "footer" in exc.value.detail and "very end of the link" in exc.value.detail


@pytest.mark.asyncio
async def test_create_passes_samples_to_meta():
    from app.routes.templates import create_template, CreateTemplate

    payload = CreateTemplate(
        name="visit", category="UTILITY", body_text="Hi {{1}}, see you soon.", body_examples=["Priya"]
    )
    captured = {}

    async def fake_submit(**kwargs):
        captured.update(kwargs)
        return {"id": "meta-1"}

    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=_db()), \
         patch("app.routes.templates.submit_template", side_effect=fake_submit):
        await create_template(payload, tenant_id="t1")
    assert captured["body_examples"] == ["Priya"]


@pytest.mark.asyncio
async def test_create_refuses_duplicate_body_and_footer():
    from app.routes.templates import create_template, CreateTemplate

    twin = {"name": "old_visit", "footer_text": "Aira", "meta_template_id": "m1", "meta_waba_id": "waba-1"}
    payload = CreateTemplate(
        name="visit", category="UTILITY", body_text="See you soon at the clinic.", footer_text="Aira"
    )
    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=_db([twin])), \
         patch("app.routes.templates.submit_template") as submit:
        with pytest.raises(HTTPException) as exc:
            await create_template(payload, tenant_id="t1")
    assert exc.value.status_code == 409 and "old_visit" in exc.value.detail
    submit.assert_not_called()


# ── delete: Meta first, keep the template when Meta refuses ──────────────────

def _delete_db(row):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [row] if row else []
    return db


@pytest.mark.asyncio
async def test_delete_keeps_template_when_meta_delete_fails():
    from app.routes.templates import delete_template

    db = _delete_db({"name": "visit", "meta_template_id": "m-1", "meta_waba_id": "waba-1"})
    failing = MagicMock(side_effect=HTTPException(status_code=500, detail='{"error":{"message":"Service unavailable"}}'))

    async def fail(**kwargs):
        failing(**kwargs)

    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.delete_template_from_meta", side_effect=fail):
        with pytest.raises(HTTPException) as exc:
            await delete_template("row-1", tenant_id="t1")
    assert exc.value.status_code == 502
    assert "try again" in exc.value.detail
    db.table.return_value.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_removes_only_this_language_on_meta_then_locally():
    from app.routes.templates import delete_template

    db = _delete_db({"name": "visit", "meta_template_id": "m-1", "meta_waba_id": "waba-1"})
    calls = []

    async def ok(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.delete_template_from_meta", side_effect=ok):
        assert await delete_template("row-1", tenant_id="t1") == {"deleted": True}
    assert calls[0]["hsm_id"] == "m-1" and calls[0]["template_name"] == "visit"
    db.table.return_value.delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_treats_already_gone_on_meta_as_success():
    from app.routes.templates import delete_template

    db = _delete_db({"name": "visit", "meta_template_id": "m-1", "meta_waba_id": "waba-1"})

    async def gone(**kwargs):
        raise HTTPException(status_code=400, detail='{"error":{"message":"Message template not found","code":100}}')

    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.delete_template_from_meta", side_effect=gone):
        assert await delete_template("row-1", tenant_id="t1") == {"deleted": True}
    db.table.return_value.delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_local_only_template_skips_meta():
    from app.routes.templates import delete_template

    db = _delete_db({"name": "draft", "meta_template_id": None, "meta_waba_id": None})
    meta = MagicMock()
    with patch("app.routes.templates.get_setting", return_value="waba-1"), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.delete_template_from_meta", meta):
        assert await delete_template("row-1", tenant_id="t1") == {"deleted": True}
    meta.assert_not_called()
    db.table.return_value.delete.assert_called_once()


# ── media header upload uses Aira's own Meta app when the client has none ────

@pytest.mark.asyncio
async def test_media_upload_falls_back_to_platform_app_id():
    from app.routes import templates

    upload = MagicMock()
    file = MagicMock()
    file.content_type = "image/png"

    async def read():
        return b"png-bytes"

    async def fake_upload(**kwargs):
        upload(**kwargs)
        return "4::handle"

    file.read = read
    settings = {"meta_access_token": "tok"}
    with patch("app.routes.templates.get_setting", side_effect=lambda k, **kw: settings.get(k)), \
         patch.object(templates.env_settings, "meta_app_id", "aira-app", create=True), \
         patch("app.routes.templates.upload_media_for_template", side_effect=fake_upload), \
         patch("app.routes.templates.get_supabase", return_value=MagicMock()), \
         patch.object(templates.template_media, "save_upload") as save_upload:
        out = await templates.upload_template_media(file=file, tenant_id="t1")
    assert out == {"header_handle": "4::handle"}
    assert upload.call_args.kwargs["app_id"] == "aira-app"
    # Our own copy is kept so the template stores a link Meta can fetch at send time.
    assert save_upload.call_args.args[1:] == ("t1", "4::handle", b"png-bytes", "image/png")


@pytest.mark.asyncio
async def test_media_upload_prefers_clients_own_app_id():
    from app.routes import templates

    captured = {}
    file = MagicMock()
    file.content_type = "video/mp4"

    async def read():
        return b"mp4"

    async def fake_upload(**kwargs):
        captured.update(kwargs)
        return "4::h"

    file.read = read
    settings = {"meta_access_token": "tok", "meta_app_id": "client-app"}
    with patch("app.routes.templates.get_setting", side_effect=lambda k, **kw: settings.get(k)), \
         patch.object(templates.env_settings, "meta_app_id", "aira-app", create=True), \
         patch("app.routes.templates.upload_media_for_template", side_effect=fake_upload), \
         patch("app.routes.templates.get_supabase", return_value=MagicMock()), \
         patch.object(templates.template_media, "save_upload"):
        await templates.upload_template_media(file=file, tenant_id="t1")
    assert captured["app_id"] == "client-app"
