"""Excel upload of templates: POST /templates/bulk/check and /bulk/submit."""
import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook

from fake_supabase import FakeSupabase

T1 = str(uuid.UUID(int=1))
HEADER = ["name", "type", "language", "message", "sample values", "footer", "button text", "button link"]


def xlsx(rows, header=HEADER) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


GOOD = ["festival_offer", "Marketing", "English", "Hi {{1}}, flat {{2}} off this week at our shop.", "Priya, 20%", "Aira", "Shop now", "https://example.com/shop"]


def check(rows, existing=()):
    from app.services import template_bulk

    return template_bulk.check_rows(template_bulk.parse_workbook(xlsx(rows)), list(existing))


# ── the rules ────────────────────────────────────────────────────────────────

def test_good_row_is_ready_and_builds_the_single_template_payload():
    from app.services import template_bulk

    (v,) = check([GOOD])
    assert v["status"] == "ready" and v["problems"] == []
    assert template_bulk.to_payload(v) == {
        "name": "festival_offer", "category": "MARKETING", "language": "en",
        "body_text": GOOD[3], "body_examples": ["Priya", "20%"], "footer_text": "Aira",
        "buttons": [{"type": "URL", "text": "Shop now", "url": "https://example.com/shop"}],
    }


def test_bad_name_says_what_to_use():
    (v,) = check([["Festival Offer!", *GOOD[1:]]])
    assert v["status"] == "need_fix"
    assert "Name: small letters, numbers and _ only -> festival_offer" in v["problems"]


def test_missing_sample_is_named():
    (v,) = check([[GOOD[0], "Utility", "English", "Hi {{1}}, flat {{2}} off this week at our shop.", "Priya", "", "", ""]])
    assert v["status"] == "need_fix" and "{{2}} has no sample" in v["problems"]


def test_unknown_language_type_and_empty_or_long_message():
    rows = check([
        [GOOD[0], "Marketing", "Klingon", "Hello there, welcome to our shop.", "", "", "", ""],
        ["b_name", "Promo", "English", "Hello there, welcome to our shop.", "", "", "", ""],
        ["c_name", "Marketing", "Tamil", "", "", "", "", ""],
        ["d_name", "Marketing", "Hindi", "x" * 1025, "", "", "", ""],
    ])
    assert any("Unknown language" in p for p in rows[0]["problems"])
    assert "Type must be Marketing or Utility." in rows[1]["problems"]
    assert "Message is empty." in rows[2]["problems"]
    assert any("too long" in p for p in rows[3]["problems"])
    assert all(r["status"] == "need_fix" for r in rows)


def test_same_rules_as_the_builder_variable_at_start_and_footer_variable():
    rows = check([
        ["a_name", "Utility", "English", "{{1}} your order is ready at the shop", "Priya", "", "", ""],
        ["b_name", "Utility", "English", "Your order is ready at the shop today.", "", "Thanks {{1}}", "", ""],
        ["c_name", "Utility", "English", "Your order is ready at the shop today.", "", "", "Open", "http://example.com"],
        ["d_name", "Utility", "English", "Your order is ready at the shop today.", "", "", "Open", ""],
    ])
    assert any("start" in p for p in rows[0]["problems"])
    assert "The footer can't contain variables." in rows[1]["problems"]
    assert "Website links must start with https://." in rows[2]["problems"]
    assert "A button needs both its text and its link." in rows[3]["problems"]


def test_link_with_a_variable_goes_to_the_builder():
    (v,) = check([["a_name", "Utility", "English", "Your order is ready at the shop today.", "", "", "Open", "https://a.co/{{1}}"]])
    assert v["status"] == "need_fix" and "Make this one in the builder." in " ".join(v["problems"])


def test_otp_type_goes_to_the_builder():
    (v,) = check([["a_name", "Authentication", "English", "Your code is here for you now", "", "", "", ""]])
    assert "Make this one in the builder." in " ".join(v["problems"])


def test_existing_name_and_language_is_skipped_not_updated():
    existing = [{"name": "festival_offer", "language": "en", "body_text": "old", "footer_text": None}]
    (v,) = check([GOOD], existing)
    assert v["status"] == "exists"


def test_same_name_in_another_language_and_same_words_need_a_fix():
    existing = [{"name": "festival_offer", "language": "ta", "body_text": "old", "footer_text": None},
                {"name": "twin", "language": "en", "body_text": GOOD[3], "footer_text": "Aira"}]
    a, b = check([GOOD, ["new_name", *GOOD[1:]]], existing)
    assert a["status"] == "need_fix" and "another language" in " ".join(a["problems"])
    assert b["status"] == "need_fix" and "twin" in " ".join(b["problems"])


def test_duplicate_inside_the_file():
    a, b = check([GOOD, GOOD])
    assert a["status"] == "ready" and b["status"] == "need_fix" and "row 2" in " ".join(b["problems"])


def test_row_numbers_match_the_spreadsheet_and_blank_rows_are_skipped():
    rows = check([GOOD, [None] * 8, ["Bad Name", *GOOD[1:]]])
    assert [r["row"] for r in rows] == [2, 4]


# ── the file ─────────────────────────────────────────────────────────────────

def test_parse_refuses_more_than_50_rows_and_non_excel():
    from app.services import template_bulk

    with pytest.raises(template_bulk.BulkFileError, match="at most 50"):
        template_bulk.parse_workbook(xlsx([[f"n_{i}", *GOOD[1:]] for i in range(51)]))
    with pytest.raises(template_bulk.BulkFileError, match="Excel"):
        template_bulk.parse_workbook(b"name,type\nx,y\n")
    with pytest.raises(template_bulk.BulkFileError, match="column titles"):
        template_bulk.parse_workbook(xlsx([["a"]], header=["foo"]))


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
    res = upload(client, xlsx([GOOD, ["Bad Name", *GOOD[1:]], ["already_here", *GOOD[1:]]]))
    assert res.status_code == 200
    body = res.json()
    assert body["counts"] == {"ready": 1, "need_fix": 1, "exists": 1}
    assert [r["status"] for r in body["rows"]] == ["ready", "need_fix", "exists"]


def test_check_route_422s(api):
    client, _, _ = api
    assert upload(client, b"a,b\n1,2\n", "t.csv").status_code == 422
    assert upload(client, xlsx([[f"n_{i}", *GOOD[1:]] for i in range(51)])).status_code == 422


def test_check_and_submit_need_templates_manage(api):
    client, _, state = api
    state["perms"] = ["templates.view"]
    assert upload(client, xlsx([GOOD])).status_code == 403
    assert client.post("/api/v1/templates/bulk/submit", json={"rows": []}).status_code == 403


def test_submit_uses_the_single_create_path_and_reports_each_row(api):
    client, db, _ = api
    check_rows = check([GOOD, ["second_one", "Utility", "English", "Your order is ready at the shop today.", "", "", "", ""],
                        ["Bad Name", *GOOD[1:]]])
    sent = []

    async def fake_submit(**kw):
        sent.append(kw)
        if kw["name"] == "second_one":
            raise HTTPException(status_code=400, detail='{"error": {"error_user_msg": "Meta says no"}}')
        return {"id": f"meta-{kw['name']}"}

    with patch("app.routes.templates.submit_template", side_effect=fake_submit), \
         patch("app.routes.templates.create_template_record", wraps=__import__("app.routes.templates", fromlist=["x"]).create_template_record) as shared:
        res = client.post("/api/v1/templates/bulk/submit", json={"rows": check_rows})
    assert res.status_code == 200
    assert shared.call_count == 2  # the bad row never reaches it
    results = res.json()["results"]
    assert [r["status"] for r in results] == ["sent", "refused", "skipped"]
    assert "Meta didn't accept the template: Meta says no" in results[1]["reason"]
    assert res.json()["counts"] == {"sent": 1, "refused": 1, "skipped": 1}
    # same call Meta gets from POST /: samples, footer and the URL button
    first = sent[0]
    assert first["waba_id"] == "waba-1" and first["category"] == "MARKETING" and first["language"] == "en"
    assert first["body_examples"] == ["Priya", "20%"] and first["footer_text"] == "Aira"
    assert len(first["buttons"]) == 1 and first["buttons"][0]["type"] == "URL"
    assert first["buttons"][0]["url"] == "https://example.com/shop" and first["buttons"][0]["text"] == "Shop now"
    saved = db.rows("message_templates")
    assert [r["name"] for r in saved] == ["festival_offer"] and saved[0]["status"] == "PENDING"


def test_submit_rechecks_rows_it_is_given(api):
    client, db, _ = api
    forged = {"row": 1, "name": "Not Valid", "type": "MARKETING", "language": "en", "message": "Hello {{1}} there friend", "samples": []}
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
