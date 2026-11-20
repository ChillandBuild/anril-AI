"""WhatsApp Forms Phase 2: every text editable (English, Tamil script, Tanglish), the client's own
forms (Catalogue → Forms), their answers on the lead, and sending one from a chat."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services import form_texts, intake
from app.services import whatsapp_forms as wf
from tests.fake_supabase import FakeSupabase
from tests.test_whatsapp_forms import CONFIG, PHONE, TENANT

LEAD = "11111111-0000-0000-0000-000000000001"


# ── texts ─────────────────────────────────────────────────────────────────────

class TestTexts:
    @pytest.mark.parametrize("language", form_texts.LANGUAGES)
    def test_every_language_has_every_text_within_whatsapps_limits(self, language):
        preset = form_texts.PRESETS[language]
        assert set(preset) == set(form_texts.LIMITS)
        assert form_texts.problems({"language": language, "texts": preset}) == []

    def test_an_edit_wins_over_the_language_and_blank_falls_back(self):
        texts = form_texts.resolve({"language": "ta", "texts": {"submit": "  அனுப்பு  ", "continue": "  "}})
        assert texts["submit"] == "அனுப்பு"
        assert texts["continue"] == form_texts.PRESETS["ta"]["continue"]

    def test_unknown_language_reads_as_english(self):
        assert form_texts.resolve({"language": "fr"})["submit"] == form_texts.PRESETS["en"]["submit"]

    @pytest.mark.parametrize("texts, message", [
        ({"cta": "x" * 31}, "at most 30"),
        ({"pay_button": "Pay now please {amount}"}, "amount filled in"),
        ({"cta": "Book 📅"}, "emoji"),
        ({"nope": "x"}, "Unknown text"),
    ])
    def test_edits_whatsapp_cant_show_are_refused_in_plain_words(self, texts, message):
        assert any(message in p for p in form_texts.problems({"language": "en", "texts": texts}))

    def test_tamil_services_form_shows_tamil_everywhere(self):
        flow, answer_map = wf.build_intake_flow({**CONFIG, "form_texts": {"language": "ta"}})
        ta = form_texts.PRESETS["ta"]
        first = flow["screens"][0]
        assert first["title"] == ta["title_choose"]
        assert first["layout"]["children"][0]["label"] == ta["choose_label"]
        confirm = flow["screens"][-1]["layout"]["children"]
        assert confirm[0]["text"] == ta["confirm_note"] and confirm[1]["label"] == ta["consent"]
        assert confirm[2]["label"] == ta["submit"]
        assert answer_map["consent_wording"] == ta["consent"]

    def test_a_texts_change_publishes_a_new_version(self):
        en, _ = wf.build_intake_flow(CONFIG)
        edited, _ = wf.build_intake_flow({**CONFIG, "form_texts": {"language": "en", "texts": {"submit": "Book now"}}})
        assert wf.source_hash(en) != wf.source_hash(edited)

    def test_payment_confirmation_uses_the_clients_words(self):
        session = {"package_path": [{"name": "Detailed"}], "amount_paise": 117882, "gst_amount_paise": 17982,
                   "selected_addons": []}
        text, label = wf._confirmation(session, form_texts.resolve({"language": "tanglish"}))
        amount = wf.deal_engine._rupees(117882)
        assert f"Total: {amount}" in text and "GST serthu" in text
        assert label == f"Pay {amount}"
        _, ta_label = wf._confirmation(session, form_texts.resolve({"language": "ta"}))
        assert ta_label == f"{amount} செலுத்த"

    def test_summary_names_come_from_the_form_version_when_services_changed(self):
        _, answer_map = wf.build_intake_flow(CONFIG)
        _, path = wf._choice_path({}, {"p1": "detailed", "p2": "one_year"}, answer_map["names"])
        assert path == ["Detailed Question", "1 Year"]


# ── starters ──────────────────────────────────────────────────────────────────

class TestStarters:
    @pytest.mark.parametrize("language", form_texts.LANGUAGES)
    @pytest.mark.parametrize("name", list(form_texts.STARTERS))
    def test_every_starter_builds_in_every_language(self, name, language):
        design = form_texts.starter(name, language)
        assert wf.design_problems(design) == []
        flow, answer_map = wf.build_custom_flow(design)
        assert flow["screens"][-1]["id"] == wf.SCREEN_CONFIRM
        assert len(answer_map["fields"]) == len(design["fields"])


# ── the client's own forms ────────────────────────────────────────────────────

def _design(**over):
    design = {
        "id": "22222222-0000-0000-0000-000000000001", "name": "Site visit", "language": "tanglish", "texts": {},
        "fields": [
            {"key": "full_name", "type": "text", "label": "Unga peyar", "required": True, "options": []},
            {"key": "email", "type": "email", "label": "Email", "required": False, "options": []},
            {"key": "budget", "type": "dropdown", "label": "Budget", "required": True,
             "options": ["₹20L-30L", "₹30L-50L", "₹50L+"]},
            {"key": "bhk", "type": "single", "label": "Evvalavu BHK?", "required": True, "options": ["1", "2", "3"]},
            {"key": "visit", "type": "date", "label": "Visit date", "required": True, "options": []},
            {"key": "amenities", "type": "multi", "label": "Amenities", "required": False,
             "options": ["Parking", "Lift", "Gym"]},
            {"key": "notes", "type": "long_text", "label": "Vera edhavadhu?", "required": False, "options": []},
        ],
    }
    design.update(over)
    return design


class TestCustomFlow:
    def test_screen_ids_are_letters_and_underscores_only(self):
        """Meta: 'Property id should only consist of alphabets and underscores' (found validating live)."""
        import re
        flow, _ = wf.build_custom_flow(_design(fields=_design()["fields"] * 1))
        assert all(re.fullmatch(r"[A-Za-z_]+", s["id"]) for s in flow["screens"])

    def test_questions_are_split_into_screens_and_routed_in_order(self):
        flow, _ = wf.build_custom_flow(_design())
        assert [s["id"] for s in flow["screens"]] == ["QUESTIONS_A", "QUESTIONS_B", "CONFIRM"]
        assert flow["routing_model"] == {"QUESTIONS_A": ["QUESTIONS_B"], "QUESTIONS_B": ["CONFIRM"], "CONFIRM": []}

    def test_each_type_becomes_the_right_whatsapp_input(self):
        flow, _ = wf.build_custom_flow(_design())
        kinds = {c["name"]: (c["type"], c.get("input-type"), c["required"])
                 for s in flow["screens"] for c in s["layout"]["children"] if "name" in c}
        assert kinds["f_full_name"] == ("TextInput", "text", True)
        assert kinds["f_email"] == ("TextInput", "email", False)
        assert kinds["f_budget"][0] == "Dropdown" and kinds["f_bhk"][0] == "RadioButtonsGroup"
        assert kinds["f_visit"][0] == "DatePicker" and kinds["f_amenities"][0] == "CheckboxGroup"
        assert kinds["f_notes"][0] == "TextArea"

    def test_earlier_answers_travel_to_the_last_screen(self):
        flow, _ = wf.build_custom_flow(_design())
        second, confirm = flow["screens"][1], flow["screens"][2]
        assert second["data"]["f_amenities"] if "f_amenities" in second["data"] else True
        assert confirm["data"]["f_amenities"]["type"] == "array" and confirm["data"]["f_full_name"]["type"] == "string"
        complete = confirm["layout"]["children"][-1]["on-click-action"]["payload"]
        assert set(complete) == {f"f_{f['key']}" for f in _design()["fields"]} | {"consent_offers"}

    def test_the_forms_language_and_edits_are_on_every_screen(self):
        flow, _ = wf.build_custom_flow(_design(texts={"submit": "Anuppunga"}))
        tl = form_texts.PRESETS["tanglish"]
        assert flow["screens"][0]["title"] == tl["title_details"]
        assert flow["screens"][-1]["layout"]["children"][-1]["label"] == "Anuppunga"

    @pytest.mark.parametrize("field, message", [
        ({"key": "a", "type": "text", "label": "x" * 21, "options": []}, "too long"),
        ({"key": "a", "type": "single", "label": "Pick", "options": ["Only one"]}, "at least 2 options"),
        ({"key": "a", "type": "dropdown", "label": "Pick", "options": ["A", "a"]}, "same option twice"),
        ({"key": "A B", "type": "text", "label": "Name", "options": []}, "invalid key"),
        ({"key": "a", "type": "signature", "label": "Sign", "options": []}, "question type"),
    ])
    def test_questions_whatsapp_cant_show_are_refused(self, field, message):
        assert any(message in p for p in wf.design_problems(_design(fields=[field])))


# ── answers, sending ──────────────────────────────────────────────────────────

@pytest.fixture
def shop(monkeypatch):
    db = FakeSupabase()
    db.table("tenants").insert({"id": TENANT, "enabled_features": [wf.FEATURE_KEY]}).execute()
    db.table("leads").insert({"id": LEAD, "tenant_id": TENANT, "phone": PHONE, "name": None,
                              "collected_data": {}}).execute()
    design = _design(texts={"thank_you": "Romba nandri! Seekiram call pannuvom."})
    db.table("whatsapp_form_designs").insert({**design, "tenant_id": TENANT, "archived": False}).execute()
    flow, answer_map = wf.build_custom_flow(design)
    form = db.table("whatsapp_forms").insert({
        "tenant_id": TENANT, "kind": "custom", "design_id": design["id"], "name": design["name"],
        "status": "published", "meta_flow_id": "777", "source_hash": wf.source_hash(flow),
        "definition": flow, "answer_map": answer_map,
    }).execute().data[0]
    sent: list = []

    async def fake_send(phone, text, **kwargs):
        sent.append(text)
        return "wamid.out"

    import app.services.ai_reply as ai_reply
    monkeypatch.setattr(ai_reply, "send_whatsapp", fake_send)
    from app.services import automation_guards
    monkeypatch.setattr(automation_guards, "ai_replies_allowed_for_lead", lambda *a, **k: True)
    monkeypatch.setattr(intake, "note_lead_message", lambda *a, **k: None)
    return db, design, form, sent


def _answers(form_id, **over):
    answers = {"flow_token": wf.make_token(TENANT, PHONE, form_id, "a1b2c3d4e5f6"), "f_full_name": "Meena",
               "f_budget": wf._slug("₹30L-50L"), "f_bhk": "2", "f_visit": "2026-12-01",
               "f_amenities": ["parking", "gym"], "consent_offers": False}
    answers.update(over)
    return json.dumps(answers)


def _submit(db, raw, mid="wamid.in1"):
    return asyncio.run(wf.handle_submission(db, tenant_id=TENANT, lead_id=LEAD, phone=PHONE, raw=raw,
                                            meta_message_id=mid))


class TestCustomAnswers:
    def test_answers_land_on_the_lead_with_a_note_consent_and_thanks(self, shop):
        db, _, form, sent = shop
        assert _submit(db, _answers(form["id"])) == "handled"
        lead = db.rows("leads")[0]
        saved = lead["collected_data"]["whatsapp_forms"][0]["answers"]
        assert saved == {"Unga peyar": "Meena", "Budget": "₹30L-50L", "Evvalavu BHK?": "2",
                         "Visit date": "2026-12-01", "Amenities": "Parking, Gym"}
        assert lead["name"] == "Meena"
        assert "📝 Site visit" in db.rows("lead_notes")[0]["content"]
        assert sent == ["Romba nandri! Seekiram call pannuvom."]
        assert db.rows("whatsapp_form_responses")[0]["outcome"] == "saved"
        offers = next(c for c in db.rows("lead_consents") if c["scope"] == "offers")
        assert offers["granted"] is False and offers["wording"] == form_texts.PRESETS["tanglish"]["consent"]

    def test_the_same_form_submitted_twice_is_saved_once(self, shop):
        db, _, form, sent = shop
        assert _submit(db, _answers(form["id"]), mid="wamid.a") == "handled"
        assert _submit(db, _answers(form["id"]), mid="wamid.b") == "ignored"
        assert len(sent) == 1

    def test_lead_card_reads_like_the_form(self, shop):
        db, _, form, _ = shop
        _submit(db, _answers(form["id"]))
        card = wf.lead_answers(db, TENANT, LEAD)[0]
        assert card["form_name"] == "Site visit" and card["kind"] == "custom"
        assert {"label": "Amenities", "value": "Parking, Gym"} in card["answers"]

    def test_summary_line_for_the_inbox(self, shop):
        db, _, form, _ = shop
        text = wf.summary_text(db, TENANT, PHONE, _answers(form["id"]))
        assert text.startswith("📝 Site visit") and "Budget: ₹30L-50L" in text


class TestSendFromChat:
    def _inbound(self, db, hours_ago):
        at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        db.table("messages").insert({"tenant_id": TENANT, "lead_id": LEAD, "direction": "inbound",
                                     "content": "hi", "created_at": at}).execute()

    def test_sends_inside_the_24_hour_window_with_the_forms_own_words(self, shop, monkeypatch):
        db, design, _, _ = shop
        self._inbound(db, 2)
        sent = {}

        async def fake_flow(**kwargs):
            sent.update(kwargs)
            return {"messages": [{"id": "wamid.form"}]}

        from app.services import meta_cloud
        monkeypatch.setattr(meta_cloud, "send_flow_message", fake_flow)
        assert asyncio.run(wf.send_design_to_lead(db, TENANT, design["id"], LEAD)) == "wamid.form"
        tl = form_texts.PRESETS["tanglish"]
        assert sent["flow_cta"] == tl["form_cta"] and sent["body_text"] == tl["intro"]
        assert sent["first_screen"] == "QUESTIONS_A"
        assert db.rows("messages")[-1]["content"] == wf.form_record(tl["intro"], tl["form_cta"])

    def test_outside_the_window_says_why(self, shop):
        db, design, _, _ = shop
        self._inbound(db, 30)
        with pytest.raises(wf.FormBuildError, match="24 hours"):
            asyncio.run(wf.send_design_to_lead(db, TENANT, design["id"], LEAD))

    def test_unpublished_changes_must_be_published_first(self, shop):
        db, design, _, _ = shop
        self._inbound(db, 1)
        db.rows("whatsapp_form_designs")[0]["fields"][0]["label"] = "Peyar"  # a change customers would see
        with pytest.raises(wf.FormBuildError, match="Publish"):
            asyncio.run(wf.send_design_to_lead(db, TENANT, design["id"], LEAD))


class TestReviewFixes:
    def test_two_questions_with_the_same_words_are_refused(self):
        fields = [{"key": "a", "type": "text", "label": "Name", "options": []},
                  {"key": "b", "type": "text", "label": "name ", "options": []}]
        assert any("Two questions both say" in p for p in wf.design_problems(_design(fields=fields)))

    def test_switched_off_custom_form_is_not_applied(self, shop):
        db, _, form, sent = shop
        db.rows("tenants")[0]["enabled_features"] = []
        assert _submit(db, _answers(form["id"])) == "continue"
        assert sent == [] and not db.rows("leads")[0]["collected_data"]


def test_auto_reply_off_saves_answers_but_sends_no_thank_you(shop, monkeypatch):
    from app.services import automation_guards
    db, _, form, sent = shop
    monkeypatch.setattr(automation_guards, "ai_replies_allowed_for_lead", lambda *a, **k: False)
    assert _submit(db, _answers(form["id"])) == "handled"
    assert sent == [] and db.rows("leads")[0]["collected_data"]["whatsapp_forms"]
    assert db.rows("whatsapp_form_responses")[0]["outcome"] == "saved"
