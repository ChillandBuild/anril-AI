"""Excel upload of templates: the strict sample layout, POST /bulk/check, /bulk/recheck, /bulk/submit, GET /bulk/sample."""
import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from fake_supabase import FakeSupabase

T1 = str(uuid.UUID(int=1))


def header():
    from app.services.template_bulk import COLUMNS

    return [t for t, _ in COLUMNS]


def row(name="festival_offer", type_="Marketing", language="English", header_text="", header_example="",
        body="Hi {{1}}, flat {{2}} off this week at our shop.", examples=("Priya", "20%"), footer="Aira",
        buttons=(("Link", "Shop now", "https://example.com/shop"),)):
    ex = list(examples) + [""] * (5 - len(examples))
    btn = [c for b in buttons for c in b] + [""] * (3 * (3 - len(buttons)))
    return [name, type_, language, header_text, header_example, body, *ex, footer, *btn]


def xlsx(rows, titles=None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(titles if titles is not None else header())
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def check(rows, existing=()):
    from app.services import template_bulk

    return template_bulk.check_rows(template_bulk.parse_workbook(xlsx(rows)), list(existing))


def fields(verdict):
    return {i["field"] for i in verdict["issues"]}


# ── the strict layout ─────────────────────────────────────────────────────────

def test_good_row_is_ready_and_builds_the_single_template_payload():
    from app.services import template_bulk

    [v] = check([row(header_text="Diwali offer", buttons=(("Link", "Shop now", "https://example.com/shop"), ("Call", "Call us", "+91 98765 43210"), ("Quick reply", "Not now", "")))])
    assert v["status"] == "ready", v["problems"]
    assert template_bulk.to_payload(v) == {
        "name": "festival_offer", "category": "MARKETING", "language": "en",
        "body_text": "Hi {{1}}, flat {{2}} off this week at our shop.", "body_examples": ["Priya", "20%"],
        "header_text": "Diwali offer", "footer_text": "Aira",
        "buttons": [
            {"type": "URL", "text": "Shop now", "url": "https://example.com/shop"},
            {"type": "PHONE_NUMBER", "text": "Call us", "phone": "9876543210", "country": "+91"},
            {"type": "QUICK_REPLY", "text": "Not now"},
        ],
    }


def test_a_moved_renamed_or_extra_column_stops_the_upload():
    from app.services import template_bulk

    swapped = header()
    swapped[3], swapped[5] = swapped[5], swapped[3]
    with pytest.raises(template_bulk.BulkFileError, match="Column D must be 'Header'"):
        template_bulk.parse_workbook(xlsx([row()], swapped))
    old = ["name", "type", "language", "message", "sample values", "footer", "button text", "button link"]
    with pytest.raises(template_bulk.BulkFileError, match="Column A must be 'Template name'"):
        template_bulk.parse_workbook(xlsx([row()], old))
    with pytest.raises(template_bulk.BulkFileError, match="isn't in the sample file"):
        template_bulk.parse_workbook(xlsx([row() + ["x"]], header() + ["Notes"]))
    # case and spacing don't matter
    assert template_bulk.parse_workbook(xlsx([row()], [t.upper().replace(" ", "  ") for t in header()]))


def test_parse_refuses_more_than_50_rows_and_non_excel():
    from app.services import template_bulk

    with pytest.raises(template_bulk.BulkFileError, match="at most 50"):
        template_bulk.parse_workbook(xlsx([row(name=f"n_{i}") for i in range(51)]))
    with pytest.raises(template_bulk.BulkFileError, match="Excel"):
        template_bulk.parse_workbook(b"name,type\nx,y\n")


def test_required_fields_and_each_missing_example_point_at_their_field():
    [v] = check([row(name="", type_="", language="", body="Hi {{1}} and {{2}}, welcome to the shop.", examples=("Priya",))])
    assert v["status"] == "need_fix"
    assert {"name", "type", "language", "example_2"} <= fields(v)
    assert "{{2}} has no example" in v["problems"]


def test_header_rules():
    [v] = check([row(header_text="Offer {{1}} 🎉")])
    assert "header" in fields(v) and "header_example" in fields(v)
    [ok] = check([row(header_text="Offer for {{1}}", header_example="Priya")])
    assert ok["status"] == "ready"


def test_body_rules_are_the_builders():
    [start] = check([row(body="{{1}}, your order is ready.", examples=("Priya",))])
    assert any("start" in p for p in start["problems"])
    [six] = check([row(body="Hi {{1}} {{2}} {{3}} {{4}} {{5}} {{6}} there.", examples=("a", "b", "c", "d", "e"))])
    assert any("builder" in p for p in six["problems"])


def test_button_rules():
    bad = check([
        row(name="a_one", buttons=(("Website", "Shop", "http://example.com"),)),
        row(name="a_two", buttons=(("Call", "Call", "12345"),)),
        row(name="a_three", buttons=(("Quick reply", "Yes", ""), ("Link", "Shop", "https://example.com"), ("Quick reply", "No", ""))),
        row(name="a_four", buttons=(("Quick reply", "Yes", ""), ("Quick reply", "yes", ""))),
        row(name="a_five", buttons=(("Button", "Yes", ""),)),
        row(name="a_six", buttons=(("Link", "Shop", "https://example.com/{{1}}"),)),
    ])
    assert all(v["status"] == "need_fix" for v in bad), [v["problems"] for v in bad]
    assert "country code" in " ".join(bad[1]["problems"])
    assert "next to each other" in " ".join(bad[2]["problems"])
    assert "same text" in " ".join(bad[3]["problems"])
    assert "Link, Call or Quick reply" in " ".join(bad[4]["problems"])
    assert "builder" in " ".join(bad[5]["problems"])


def test_otp_type_goes_to_the_builder_and_existing_is_skipped():
    [otp] = check([row(type_="Authentication")])
    assert "builder" in " ".join(otp["problems"])
    [v] = check([row()], existing=[{"name": "festival_offer", "language": "en", "body_text": "x"}])
    assert v["status"] == "exists"


def test_duplicates_inside_the_file_and_same_words_as_an_existing_template():
    a, b = check([row(), row()])
    assert a["status"] == "ready" and "Same name and language as row 2." in b["problems"]
    [twin] = check([row(name="new_name")], existing=[{"name": "old", "language": "en",
                                                       "body_text": "Hi {{1}}, flat {{2}} off this week at our shop.", "footer_text": "Aira"}])
    assert "body" in fields(twin)


def test_edited_rows_are_rechecked_without_a_new_upload():
    from app.services import template_bulk

    [v] = check([row(name="Bad Name")])
    assert v["status"] == "need_fix"
    edited = {**v, "name": "bad_name"}  # what the review screen sends back
    [again] = template_bulk.check_rows([edited], [])
    assert again["status"] == "ready" and again["type"] == "MARKETING" and again["language"] == "en"


def test_row_numbers_match_the_spreadsheet_and_blank_rows_are_skipped():
    from app.services import template_bulk

    rows = template_bulk.parse_workbook(xlsx([row(), [""] * 21, row(name="second_one")]))
    assert [r["row"] for r in rows] == [2, 4]


def test_sample_file_has_the_exact_columns_dropdowns_and_ready_examples():
    from app.services import template_bulk

    content = template_bulk.sample_workbook()
    wb = load_workbook(io.BytesIO(content))
    ws = wb["Templates"]
    assert [c.value for c in ws[1]] == header()
    assert {str(dv.formula1) for dv in ws.data_validations.dataValidation} >= {'"Marketing,Utility"', '"Link,Call,Quick reply"'}
    assert "How to fill" in wb.sheetnames
    verdicts = template_bulk.check_rows(template_bulk.parse_workbook(content), [])
    assert [v["status"] for v in verdicts] == ["ready", "ready"]


# ── the routes ───────────────────────────────────────────────────────────────

@pytest.fixture
def api():
    from app.dependencies.auth import get_current_user
    from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
    from app.main import app

    db = FakeSupabase()
    state = {"perms": ["templates.manage"]}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
    app.dependency_overrides[get_tenant_id] = lambda: T1
    app.dependency_overrides[get_tenant_and_role] = lambda: {
        "tenant_id": T1, "role": "caller", "permissions": state["perms"], "user_id": "u",
    }
    with patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.get_setting", lambda k, **kw: "waba-1" if k == "meta_waba_id" else None):
        yield TestClient(app), db, state
    app.dependency_overrides.clear()


def upload(client, content: bytes, name="t.xlsx"):
    return client.post("/api/v1/templates/bulk/check", files={"file": (name, content, "application/octet-stream")})


def test_check_route_counts(api):
    client, db, _ = api
    db.add("message_templates", tenant_id=T1, name="already_here", language="en", body_text="x",
           meta_template_id="m1", meta_waba_id="waba-1", status="APPROVED")
    res = upload(client, xlsx([row(), row(name="Bad Name"), row(name="already_here")]))
    assert res.status_code == 200
    body = res.json()
    assert body["counts"] == {"ready": 1, "need_fix": 1, "exists": 1, "update": 0}
    assert [r["status"] for r in body["rows"]] == ["ready", "need_fix", "exists"]
    assert body["rows"][1]["issues"][0]["field"] == "name"


def test_check_route_422s(api):
    client, _, _ = api
    assert upload(client, b"a,b\n1,2\n", "t.csv").status_code == 422
    assert upload(client, xlsx([row()], ["name", "type"])).status_code == 422


def test_recheck_and_sample_routes(api):
    client, _, _ = api
    [v] = check([row(name="Bad Name")])
    res = client.post("/api/v1/templates/bulk/recheck", json={"rows": [{**v, "name": "good_name"}]})
    assert res.status_code == 200 and res.json()["rows"][0]["status"] == "ready"
    sample = client.get("/api/v1/templates/bulk/sample")
    assert sample.status_code == 200 and sample.content[:2] == b"PK"  # an .xlsx is a zip


def test_bulk_routes_need_templates_manage(api):
    client, _, state = api
    state["perms"] = ["templates.view"]
    assert upload(client, xlsx([row()])).status_code == 403
    assert client.post("/api/v1/templates/bulk/submit", json={"rows": []}).status_code == 403
    assert client.post("/api/v1/templates/bulk/recheck", json={"rows": []}).status_code == 403
    assert client.get("/api/v1/templates/bulk/sample").status_code == 403


def test_submit_uses_the_single_create_path_and_reports_each_row(api):
    client, db, _ = api
    rows = check([row(header_text="Diwali offer"),
                  row(name="second_one", type_="Utility", body="Your order is ready at the shop today.", examples=(), footer="", buttons=()),
                  row(name="Bad Name")])
    sent = []

    async def fake_submit(**kw):
        sent.append(kw)
        if kw["name"] == "second_one":
            raise HTTPException(status_code=400, detail='{"error": {"error_user_msg": "Meta says no"}}')
        return {"id": f"meta-{kw['name']}"}

    with patch("app.routes.templates.submit_template", side_effect=fake_submit), \
         patch("app.routes.templates.create_template_record", wraps=__import__("app.routes.templates", fromlist=["x"]).create_template_record) as shared:
        res = client.post("/api/v1/templates/bulk/submit", json={"rows": rows})
    assert res.status_code == 200
    assert shared.call_count == 2  # the bad row never reaches it
    results = res.json()["results"]
    assert [r["status"] for r in results] == ["sent", "refused", "skipped"]
    assert "Meta didn't accept the template: Meta says no" in results[1]["reason"]
    first = sent[0]
    assert first["waba_id"] == "waba-1" and first["category"] == "MARKETING" and first["language"] == "en"
    assert first["body_examples"] == ["Priya", "20%"] and first["footer_text"] == "Aira"
    assert first["header_text"] == "Diwali offer"
    assert first["buttons"][0]["type"] == "URL" and first["buttons"][0]["url"] == "https://example.com/shop"
    saved = db.rows("message_templates")
    assert [r["name"] for r in saved] == ["festival_offer"] and saved[0]["status"] == "PENDING"


def test_submit_rechecks_rows_it_is_given(api):
    client, _, _ = api
    forged = {"row": 1, "name": "Not Valid", "type": "MARKETING", "language": "en", "body": "Hello {{1}} there friend", "examples": []}
    with patch("app.routes.templates.submit_template", new=AsyncMock()) as meta:
        res = client.post("/api/v1/templates/bulk/submit", json={"rows": [forged]})
    assert res.json()["results"][0]["status"] == "skipped"
    meta.assert_not_called()


def test_submit_over_50_rows_is_422(api):
    client, _, _ = api
    assert client.post("/api/v1/templates/bulk/submit", json={"rows": [{}] * 51}).status_code == 422


def test_single_create_is_a_thin_wrapper_over_the_shared_helper():
    import inspect

    from app.routes import templates

    assert "create_template_record(payload, tenant_id)" in inspect.getsource(templates.create_template)


# ── update an existing template ───────────────────────────────────────────────

def _exists(status="APPROVED", category="MARKETING"):
    return [{"id": "tpl-1", "name": "festival_offer", "language": "en", "body_text": "old", "status": status,
             "category": category, "meta_template_id": "m-1"}]


def _run_submit(rows, existing, update=None):
    import asyncio

    from app.services import template_bulk

    created = AsyncMock()
    results = asyncio.run(template_bulk.submit_rows(rows, existing, created, update))
    return results, created


def test_exists_row_carries_existing_id():
    [v] = check([row()], existing=_exists())
    assert v["status"] == "exists"
    assert (v["existing_id"], v["existing_status"], v["existing_type"]) == ("tpl-1", "APPROVED", "MARKETING")


def test_update_action_validates_like_a_new_row():
    from app.services import template_bulk

    rows = template_bulk.parse_workbook(xlsx([row(examples=("Priya",)), row(name="festival_offer")]))
    bad = {**rows[0], "action": "update"}
    [v] = template_bulk.check_rows([bad], _exists())
    assert v["status"] == "need_fix" and "example_2" in fields(v)
    ok = {**rows[1], "action": "update"}
    [v2] = template_bulk.check_rows([ok], _exists())
    assert v2["status"] == "update" and v2["existing_id"] == "tpl-1" and not v2["issues"]


def _update_rows(**kw):
    from app.services import template_bulk

    [r] = template_bulk.parse_workbook(xlsx([row(**kw)]))
    return [{**r, "action": "update"}]


def test_submit_update_calls_update_not_create():
    update = AsyncMock(return_value={})
    results, created = _run_submit(_update_rows(), _exists(), update)
    assert results[0]["status"] == "updated"
    created.assert_not_called()
    eid, payload = update.call_args.args
    assert eid == "tpl-1"
    assert payload["body_text"].startswith("Hi {{1}}") and payload["body_examples"] == ["Priya", "20%"]
    assert not {"name", "language", "category"} & set(payload)


def test_submit_update_refused_while_pending():
    update = AsyncMock()
    results, _ = _run_submit(_update_rows(), _exists(status="PENDING"), update)
    assert results[0]["status"] == "refused"
    assert results[0]["reason"] == "Meta is still reviewing this template, so it can't be changed yet."
    update.assert_not_called()


def test_submit_update_keeps_type_with_note():
    update = AsyncMock(return_value={})
    results, _ = _run_submit(_update_rows(type_="Utility"), _exists(category="MARKETING"), update)
    assert results[0]["status"] == "updated"
    assert results[0]["note"] == "Type stays MARKETING: Meta doesn't let a template change type."
    update.assert_called_once()


def test_update_row_with_blank_footer_header_buttons_sends_explicit_clears():
    update = AsyncMock(return_value={})
    rows = _update_rows(footer="", buttons=())
    _run_submit(rows, _exists(), update)
    payload = update.call_args.args[1]
    assert payload["footer_text"] == "" and payload["header_text"] == "" and payload["buttons"] == []


def test_update_keeps_media_header_with_note():
    update = AsyncMock(return_value={})
    existing = [{**_exists()[0], "header_media_type": "IMAGE"}]
    results, _ = _run_submit(_update_rows(header_text="Ignored"), existing, update)
    assert "header_text" not in update.call_args.args[1]
    assert results[0]["status"] == "updated"
    assert "Picture/video header kept: change it in Create Template." in results[0]["note"]
