"""Meta Instant Forms: answers, template blanks, dedupe, and the webhook hook.

Run with:
    cd backend && PYTHONUTF8=1 python -m pytest tests/test_meta_lead_forms.py -q
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, Request

from app.services import meta_lead_forms as svc
from app.services.inbound_leads_logic import lead_origin
from tests.fake_supabase import FakeSupabase

TENANT = "tenant-1"
PAGE = "111"


def _meta_time(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _lead(leadgen_id="900", age=timedelta(minutes=1), phone="9876543210", form_id="555"):
    field_data = [
        {"name": "full_name", "values": ["Priya Raman"]},
        {"name": "email", "values": ["priya@example.com"]},
        {"name": "which_city?", "values": ["Chennai"]},
    ]
    if phone is not None:
        field_data.append({"name": "phone_number", "values": [phone]})
    return {
        "id": leadgen_id, "created_time": _meta_time(age), "form_id": form_id, "field_data": field_data,
        "ad_id": "42", "ad_name": "Loan ad", "is_organic": False,
    }


# ── answers and contact ─────────────────────────────────────────────────────


def test_answers_map_joins_multi_choice_and_skips_junk():
    answers = svc.answers_map([
        {"name": "full_name", "values": ["Priya"]},
        {"name": "services", "values": ["Loan", " Insurance "]},
        {"values": ["no name"]},
        "not-a-dict",
    ])
    assert answers == {"full_name": "Priya", "services": "Loan, Insurance"}


def test_contact_from_first_and_last_name():
    contact = svc.contact_from_answers({"first_name": "Ravi", "last_name": "K", "phone_number": "+919800000000"})
    assert contact == {"name": "Ravi K", "phone": "+919800000000", "email": ""}


# ── template blanks ─────────────────────────────────────────────────────────


def test_template_values_follow_the_mapping():
    mapping = [
        {"source": "field", "field": "first_name"},
        {"source": "field", "field": "which_city?"},
        {"source": "text", "text": "Anril Loans"},
    ]
    values = svc.template_values(mapping, 3, {"which_city?": "Chennai"}, "Priya Raman")
    assert values == ["Priya", "Chennai", "Anril Loans"]


def test_template_values_never_empty():
    # No mapping: blank 1 is the first name, others get a dash. Meta rejects empty values.
    assert svc.template_values([], 2, {}, None) == ["there", "-"]
    assert svc.template_values([{"source": "field", "field": "missing"}], 1, {}, "Ravi") == ["there"]


# ── storing ─────────────────────────────────────────────────────────────────


def _db():
    db = FakeSupabase()
    db.add("meta_lead_forms", tenant_id=TENANT, form_id="555", name="Home loan", template_id=None,
           template_variables=[], questions=[])
    return db


def test_fresh_lead_is_stored_once_and_added_to_leads():
    db = _db()
    with patch("app.services.meta_lead_forms._attach_to_lead", return_value="lead-1") as attach:
        first = svc.store_lead(db, TENANT, PAGE, _lead(), received_via="webhook")
        again = svc.store_lead(db, TENANT, PAGE, _lead(), received_via="catch_up")
    assert first["template_status"] == "pending"
    assert first["lead_id"] == "lead-1"
    assert first["phone"] == "+919876543210"
    assert again is None  # Meta retry / catch-up: no second row, no second lead
    assert attach.call_count == 1
    assert len(db.rows("meta_form_leads")) == 1


def test_imported_and_old_leads_stay_off_leads_and_get_no_template():
    db = _db()
    with patch("app.services.meta_lead_forms._attach_to_lead") as attach:
        imported = svc.store_lead(db, TENANT, PAGE, _lead("901"), received_via="import")
        late = svc.store_lead(db, TENANT, PAGE, _lead("902", age=timedelta(days=2)), received_via="catch_up")
    assert imported["template_status"] == "skipped_old"
    assert late["template_status"] == "skipped_old"
    attach.assert_not_called()


def test_fresh_lead_without_phone_is_kept_but_not_messaged():
    db = _db()
    with patch("app.services.meta_lead_forms._attach_to_lead") as attach:
        row = svc.store_lead(db, TENANT, PAGE, _lead("903", phone=None), received_via="webhook")
    assert row["template_status"] == "no_phone"
    attach.assert_not_called()


# ── sending ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_template_is_claimed_so_it_sends_once():
    db = _db()
    db.rows("meta_lead_forms")[0]["template_id"] = "tpl-1"
    row = db.add("meta_form_leads", tenant_id=TENANT, form_id="555", phone="+919876543210", name="Priya",
                  answers=[], lead_id=None, template_status="pending")
    template = {"id": "tpl-1", "name": "welcome", "language": "en", "body_text": "Hi {{1}}"}
    send = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})
    with patch("app.services.meta_lead_forms.sendable_templates", return_value=[template]), \
         patch("app.services.meta_cloud.send_template_message", send):
        assert await svc.send_form_template(db, TENANT, row["id"]) == "sent"
        assert await svc.send_form_template(db, TENANT, row["id"]) == "skipped"
    send.assert_awaited_once()
    assert send.await_args.kwargs["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "Priya"}]},
    ]
    assert db.rows("meta_form_leads")[0]["template_message_id"] == "wamid.1"


@pytest.mark.asyncio
async def test_image_header_template_sends_its_saved_image():
    db = _db()
    db.rows("meta_lead_forms")[0]["template_id"] = "tpl-img"
    row = db.add("meta_form_leads", tenant_id=TENANT, form_id="555", phone="+919876543210", name="Priya Raman",
                  answers=[], lead_id="lead-1", template_status="pending")
    template = {
        "id": "tpl-img", "name": "offer", "language": "en", "body_text": "Hi {{1}}, here is our offer",
        "header_media_type": "IMAGE", "header_media_url": "https://cdn.example.com/offer.jpg",
    }
    send = AsyncMock(return_value={"messages": [{"id": "wamid.2"}]})
    with patch("app.services.meta_lead_forms.sendable_templates", return_value=[template]), \
         patch("app.services.meta_cloud.send_template_message", send):
        assert await svc.send_form_template(db, TENANT, row["id"]) == "sent"
    components = send.await_args.kwargs["components"]
    assert components[0] == {
        "type": "header", "parameters": [{"type": "image", "image": {"link": "https://cdn.example.com/offer.jpg"}}],
    }
    assert components[-1] == {"type": "body", "parameters": [{"type": "text", "text": "Priya"}]}
    logged = db.rows("messages")[0]
    assert logged["content"] == "[Template: offer]"  # broadcast-style: hidden from Conversations until a reply


def test_media_template_without_saved_file_is_not_offered():
    db = FakeSupabase()
    db.add("message_templates", id="a", tenant_id=TENANT, status="APPROVED", meta_waba_id="w1", body_text="Hi")
    db.add("message_templates", id="b", tenant_id=TENANT, status="APPROVED", meta_waba_id="w1",
           header_media_type="VIDEO", header_media_url="https://cdn.example.com/v.mp4")
    db.add("message_templates", id="c", tenant_id=TENANT, status="APPROVED", meta_waba_id="w1",
           header_media_type="IMAGE", header_media_url=None)
    db.add("message_templates", id="d", tenant_id=TENANT, status="PENDING", meta_waba_id="w1")
    db.add("message_templates", id="e", tenant_id=TENANT, status="APPROVED", meta_waba_id="old-number")
    with patch("app.services.meta_lead_forms.get_setting", return_value="w1"):
        ids = [t["id"] for t in svc.sendable_templates(db, TENANT)]
    assert ids == ["a", "b"]


@pytest.mark.asyncio
async def test_meta_refusal_is_saved_in_plain_words():
    from fastapi import HTTPException

    db = _db()
    db.rows("meta_lead_forms")[0]["template_id"] = "tpl-1"
    row = db.add("meta_form_leads", tenant_id=TENANT, form_id="555", phone="+919876543210", name="Priya",
                  answers=[], template_status="pending")
    template = {"id": "tpl-1", "name": "welcome", "body_text": "Hi"}
    refusal = HTTPException(status_code=400, detail=json.dumps({"error": {"message": "(#132001) Template name does not exist"}}))
    with patch("app.services.meta_lead_forms.sendable_templates", return_value=[template]), \
         patch("app.services.meta_cloud.send_template_message", AsyncMock(side_effect=refusal)):
        assert await svc.send_form_template(db, TENANT, row["id"]) == "failed"
    assert db.rows("meta_form_leads")[0]["template_error"] == "WhatsApp didn't send it: (#132001) Template name does not exist"


@pytest.mark.asyncio
async def test_no_template_chosen_marks_the_row():
    db = _db()
    row = db.add("meta_form_leads", tenant_id=TENANT, form_id="555", phone="+919876543210",
                  answers=[], template_status="pending")
    assert await svc.send_form_template(db, TENANT, row["id"]) == "no_template"


# ── webhook ─────────────────────────────────────────────────────────────────


def _leadgen_request(page_id: str):
    payload = {
        "object": "page",
        "entry": [{"id": page_id, "time": 1, "changes": [
            {"field": "leadgen", "value": {"leadgen_id": "900", "page_id": page_id, "form_id": "555"}},
        ]}],
    }
    request = MagicMock(spec=Request)
    request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
    return request


@pytest.mark.asyncio
async def test_webhook_queues_leadgen_for_the_owning_tenant():
    from app.routes.facebook import facebook_webhook
    background = MagicMock(spec=BackgroundTasks)
    with patch("app.routes.facebook.verify_meta_signature", return_value=True), \
         patch("app.routes.facebook.resolve_tenant_for_page", return_value=TENANT), \
         patch("app.routes.facebook.get_supabase", return_value=MagicMock()):
        result = await facebook_webhook(TENANT, _leadgen_request(PAGE), background)
    assert result == {"status": "ok"}
    background.add_task.assert_called_once()
    assert background.add_task.call_args.args[1:] == (TENANT, PAGE, {"leadgen_id": "900", "page_id": PAGE, "form_id": "555"})


@pytest.mark.asyncio
async def test_webhook_ignores_leadgen_for_a_page_nobody_registered():
    from app.routes.facebook import facebook_webhook
    background = MagicMock(spec=BackgroundTasks)
    with patch("app.routes.facebook.verify_meta_signature", return_value=True), \
         patch("app.routes.facebook.resolve_tenant_for_page", return_value=None), \
         patch("app.routes.facebook.get_supabase", return_value=MagicMock()):
        await facebook_webhook(TENANT, _leadgen_request("999"), background)
    background.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_rejects_unsigned_leadgen():
    from app.routes.facebook import facebook_webhook
    background = MagicMock(spec=BackgroundTasks)
    with patch("app.routes.facebook.verify_meta_signature", return_value=False):
        response = await facebook_webhook(TENANT, _leadgen_request(PAGE), background)
    assert response.status_code == 403
    background.add_task.assert_not_called()


# ── origin ──────────────────────────────────────────────────────────────────


def test_instant_form_leads_count_as_ad_leads():
    assert lead_origin({"source": "meta_form"}) == "ad"
    assert lead_origin({"source": "whatsapp"}) == "organic"


# ── which ads use each form ─────────────────────────────────────────────────


def _ads_page():
    # Shapes as Meta returned them for kelir (2026-11-09): a dynamic-creative ad
    # carries the form in asset_feed_spec, a single-video ad in object_story_spec.
    return {"data": [
        {"name": "Star Reel", "effective_status": "CAMPAIGN_PAUSED", "creative": {"object_story_spec": {
            "video_data": {"call_to_action": {"value": {"lead_gen_form_id": "222"}}}}}},
        {"name": "New Leads ad", "effective_status": "ACTIVE", "creative": {"asset_feed_spec": {
            "call_to_actions": [{"value": {"lead_gen_form_id": "111"}}]}}},
        {"name": "Second ad", "effective_status": "ACTIVE", "creative": {"object_story_spec": {
            "link_data": {"call_to_action": {"value": {"lead_gen_form_id": "222"}}}}}},
        {"name": "Traffic ad", "effective_status": "ACTIVE", "creative": {"object_story_spec": {
            "link_data": {"call_to_action": {"value": {"link": "https://x"}}}}}},
    ]}


def test_ads_by_form_reads_both_creative_shapes_and_lists_active_first():
    svc._ADS_BY_FORM_CACHE.clear()
    with patch("app.services.meta_lead_forms._get_ads_credentials", return_value=("tok", "act_1")), \
         patch("app.services.meta_lead_forms._get", return_value=_ads_page()):
        result = svc.ads_by_form(MagicMock(), TENANT)
    assert result == {"111": ["New Leads ad"], "222": ["Second ad", "Star Reel"]}


def test_ads_by_form_is_empty_when_meta_fails_or_no_ad_account():
    svc._ADS_BY_FORM_CACHE.clear()
    with patch("app.services.meta_lead_forms._get_ads_credentials", return_value=None):
        assert svc.ads_by_form(MagicMock(), TENANT) == {}
    with patch("app.services.meta_lead_forms._get_ads_credentials", return_value=("tok", "act_1")), \
         patch("app.services.meta_lead_forms._get", side_effect=svc.InstantFormsError("boom")):
        assert svc.ads_by_form(MagicMock(), TENANT) == {}


# ── lead downloads ──────────────────────────────────────────────────────────

_FORMS = {"555": {"form_id": "555", "name": "Host form", "questions": [
    {"key": "which_city?"}, {"key": "email"}, {"key": "full_name"}, {"key": "phone_number"},
]}}


def _rows(text: str) -> list[list[str]]:
    import csv
    import io
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:])))


def test_leads_csv_matches_ads_manager_layout():
    lead = {**_lead(), "created_time": "2026-11-08T18:08:25+0000", "adset_id": "7", "adset_name": "Set",
            "campaign_id": "8", "campaign_name": "Camp", "platform": "ig"}
    header, row = _rows(svc.leads_csv([lead], _FORMS))
    assert header == svc.EXPORT_COLUMNS + ["which_city?", "email", "full_name", "phone_number"]
    assert header[:10] == ["id", "created_time", "ad_id", "ad_name", "adset_id", "adset_name",
                           "campaign_id", "campaign_name", "form_id", "form_name"]
    assert row[:12] == ["l:900", "2026-11-08T23:38:25+05:30", "ag:42", "Loan ad", "as:7", "Set",
                        "c:8", "Camp", "f:555", "Host form", "false", "ig"]
    assert row[12:] == ["Chennai", "priya@example.com", "Priya Raman", "p:9876543210"]


def test_leads_csv_keeps_answers_missing_from_the_saved_form():
    lead = _lead()
    lead["field_data"].append({"name": "new_question", "values": ["yes"]})
    header, row = _rows(svc.leads_csv([lead], _FORMS))
    assert header[-1] == "new_question" and row[-1] == "yes"


def test_node_leads_follows_pages_and_stops_at_the_start_date():
    since = datetime.now(timezone.utc) - timedelta(days=3)
    first = {"data": [_lead("1", timedelta(hours=1))], "paging": {"next": "https://next"}}
    second = {"data": [_lead("2", timedelta(days=2)), _lead("3", timedelta(days=5))], "paging": {"next": "https://more"}}
    with patch("app.services.meta_lead_forms._get", return_value=first), \
         patch("app.services.meta_lead_forms._get_url", return_value=second) as nxt:
        leads = svc._node_leads("tok", "555", since)
    assert [lead["id"] for lead in leads] == ["1", "2"]
    assert nxt.call_count == 1


def test_form_download_says_how_to_fix_access_when_meta_hides_the_leads():
    def fake_get(path, token, params=None):
        return {"data": []} if path.endswith("/leads") else {"leads_count": 108}
    with patch("app.services.meta_lead_forms.page_credentials", return_value=(PAGE, "tok")), \
         patch("app.services.meta_lead_forms._get", side_effect=fake_get):
        with pytest.raises(svc.InstantFormsError, match="108 leads.*Leads access"):
            svc.form_leads_csv(MagicMock(), TENANT, "555")


def test_form_download_reads_live_from_meta():
    db = FakeSupabase()
    db.tables["meta_lead_forms"] = [{"tenant_id": TENANT, **_FORMS["555"]}]
    with patch("app.services.meta_lead_forms.page_credentials", return_value=(PAGE, "tok")), \
         patch("app.services.meta_lead_forms._get", return_value={"data": [_lead("1"), _lead("2")]}):
        _, *rows = _rows(svc.form_leads_csv(db, TENANT, "555"))
    assert [row[0] for row in rows] == ["l:1", "l:2"]
    assert all(row[9] == "Host form" for row in rows)


def test_ads_download_merges_ads_newest_first_and_explains_an_empty_result():
    since = datetime.now(timezone.utc) - timedelta(days=30)
    until = datetime.now(timezone.utc) + timedelta(days=1)
    pages = {"10/leads": {"data": [_lead("old", timedelta(days=2))]},
             "11/leads": {"data": [_lead("new", timedelta(hours=1))]}}
    with patch("app.services.meta_lead_forms._get_ads_credentials", return_value=("tok", "act_1")), \
         patch("app.services.meta_lead_forms._get", side_effect=lambda p, t, q=None: pages[p]):
        _, *rows = _rows(svc.ads_leads_csv(MagicMock(), TENANT, ["10", "11"], since, until))
    assert [row[0] for row in rows] == ["l:new", "l:old"]
    with patch("app.services.meta_lead_forms._get_ads_credentials", return_value=("tok", "act_1")), \
         patch("app.services.meta_lead_forms._get", return_value={"data": []}):
        with pytest.raises(svc.InstantFormsError, match="no leads"):
            svc.ads_leads_csv(MagicMock(), TENANT, ["10"], since, until)


def test_lead_history_names_each_forms_past_ads_newest_first():
    from app.routes.instant_forms import _lead_history_by_form
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"form_id": "1", "meta_created_at": "2026-11-09T10:00:00+00:00", "ad_name": "New Leads ad"},
        {"form_id": "1", "meta_created_at": "2026-11-08T10:00:00+00:00", "ad_name": "Old ad"},
        {"form_id": "1", "meta_created_at": "2026-11-07T10:00:00+00:00", "ad_name": "New Leads ad"},
        {"form_id": "2", "meta_created_at": "2026-11-06T10:00:00+00:00", "ad_name": None},
    ]
    last, ads = _lead_history_by_form(db, TENANT)
    assert last == {"1": "2026-11-09T10:00:00+00:00", "2": "2026-11-06T10:00:00+00:00"}
    assert ads == {"1": ["New Leads ad", "Old ad"]}
