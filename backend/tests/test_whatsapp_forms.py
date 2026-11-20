"""WhatsApp Forms (services/whatsapp_forms.py): the form built from Services, the signed
flow_token, the package menu that becomes a form, and a submission applied through the same
guarded executors as the chat flow (so prices, staleness and duplicates behave the same)."""
import asyncio
import json
from unittest.mock import patch

import pytest

from app.services import deal_actions, deal_engine, deal_turn, intake, meta_cloud, whatsapp_forms as wf
from tests.fake_supabase import FakeSupabase
from tests.test_deal_actions import World

TENANT, LEAD, PHONE = "tenant-1", "lead-1", "+916369781582"

CONFIG = {
    "enabled": True,
    "collect_with": "form",
    "service_noun": "consultation",
    "gst_percent": 18,
    "fields": [
        {"key": "name", "label": "Full name", "type": "text"},
        {"key": "birth_date", "label": "Date of birth", "type": "date"},
        {"key": "gender", "label": "Gender", "type": "choice", "options": ["Female", "Male"]},
    ],
    "packages": [
        {"key": "one_question", "name": "One Question", "amount_paise": 100, "description": "A simple question"},
        {"key": "detailed", "name": "Detailed Question", "amount_paise": 0, "options": [
            {"key": "one_year", "name": "1 Year", "amount_paise": 99900, "addons": [
                {"key": "remedies", "name": "Remedies PDF", "amount_paise": 19900},
                {"key": "call", "name": "15-min call", "amount_paise": 49900},
            ]},
            {"key": "two_years", "name": "2 Years", "amount_paise": 179900},
            {"key": "gone", "name": "Old offer", "amount_paise": 500, "active": False},
        ]},
    ],
}


def _screens(flow):
    return {s["id"]: s for s in flow["screens"]}


def _footer_targets(node) -> set[str]:
    return wf._navigate_targets(node)


# ── the form built from Services ──────────────────────────────────────────────

class TestBuildIntakeFlow:
    def test_screens_follow_the_package_tree(self):
        flow, _ = wf.build_intake_flow(CONFIG)
        assert [s["id"] for s in flow["screens"]] == ["PACKAGE", "OPTION", "ADDONS", "DETAILS", "CONFIRM"]
        assert flow["version"] == wf.FLOW_JSON_VERSION

    def test_every_jump_is_in_the_routing_model(self):
        """Phase 0 trap: a Footer inside If needs an explicit routing_model or the phone errors."""
        flow, _ = wf.build_intake_flow(CONFIG)
        screens = _screens(flow)
        for sid, screen in screens.items():
            assert set(flow["routing_model"][sid]) == _footer_targets(screen["layout"])
        assert flow["routing_model"]["PACKAGE"] == ["DETAILS", "OPTION"]
        assert flow["routing_model"]["OPTION"] == ["ADDONS", "DETAILS"]
        assert flow["routing_model"]["CONFIRM"] == []

    def test_one_level_package_skips_straight_to_details(self):
        flow, _ = wf.build_intake_flow(CONFIG)
        footer = _screens(flow)["PACKAGE"]["layout"]["children"][-1]
        assert footer["type"] == "If"
        assert footer["condition"] == "(${form.p1} == 'one_question')"
        assert footer["then"][0]["on-click-action"]["next"]["name"] == "DETAILS"
        assert footer["else"][0]["on-click-action"]["next"]["name"] == "OPTION"

    def test_add_ons_only_for_the_choice_that_has_them(self):
        flow, answer_map = wf.build_intake_flow(CONFIG)
        option_footer = _screens(flow)["OPTION"]["layout"]["children"][-1]
        assert option_footer["condition"] == "(${form.p2} == 'one_year')"
        switch = _screens(flow)["ADDONS"]["layout"]["children"][0]
        assert switch["value"] == "${data.p2}" and list(switch["cases"]) == ["one_year"]
        assert answer_map["addons"] == {"a_one_year": "one_year"}

    def test_inactive_options_are_not_shown(self):
        flow, _ = wf.build_intake_flow(CONFIG)
        radios = _screens(flow)["OPTION"]["layout"]["children"][0]["cases"]["detailed"][0]["data-source"]
        assert [o["id"] for o in radios] == ["one_year", "two_years"]

    def test_prices_are_shown_from_services(self):
        flow, _ = wf.build_intake_flow(CONFIG)
        first = _screens(flow)["PACKAGE"]["layout"]["children"][0]["data-source"][0]
        assert first["description"] == f"{deal_engine._rupees(100)} · A simple question"
        addon = _screens(flow)["ADDONS"]["layout"]["children"][0]["cases"]["one_year"][0]["data-source"][0]
        assert addon["description"].startswith("+")

    def test_details_map_to_native_inputs(self):
        flow, answer_map = wf.build_intake_flow(CONFIG)
        inputs = {c["name"]: c["type"] for c in _screens(flow)["DETAILS"]["layout"]["children"] if "name" in c}
        assert inputs == {"f_name": "TextInput", "f_birth_date": "DatePicker", "f_gender": "Dropdown"}
        assert answer_map["fields"]["f_gender"]["options"] == {"female": "Female", "male": "Male"}

    def test_offers_opt_in_is_optional_and_on_the_last_screen(self):
        flow, _ = wf.build_intake_flow(CONFIG)
        opt_in = next(c for c in _screens(flow)["CONFIRM"]["layout"]["children"] if c["type"] == "OptIn")
        assert opt_in["required"] is False and opt_in["name"] == "consent_offers"

    def test_simple_menu_without_details_goes_straight_to_confirm(self):
        flow, _ = wf.build_intake_flow({"packages": [
            {"key": "a", "name": "A", "amount_paise": 100}, {"key": "b", "name": "B", "amount_paise": 200},
        ], "fields": []})
        assert [s["id"] for s in flow["screens"]] == ["PACKAGE", "CONFIRM"]
        assert flow["routing_model"]["PACKAGE"] == ["CONFIRM"]
        assert _screens(flow)["PACKAGE"]["layout"]["children"][-1]["type"] == "Footer"

    @pytest.mark.parametrize("packages, message", [
        ([], "Add at least one active package"),
        ([{"key": f"k{i}", "name": f"P{i}", "amount_paise": 100} for i in range(21)], "at most 20"),
        ([{"key": "a", "name": "A", "options": [{"key": "b", "name": "B", "options": [
            {"key": "c", "name": "C", "amount_paise": 1}]}]}], "two levels"),
        ([{"key": "a", "name": "A", "amount_paise": 1}, {"key": "x", "name": "X", "options": [
            {"key": "a", "name": "A again", "amount_paise": 1}]}], "same key"),
        ([{"key": "it's", "name": "Quote", "amount_paise": 1}], "spaces or symbols"),
    ])
    def test_setups_a_form_cannot_show_are_refused_with_a_reason(self, packages, message):
        with pytest.raises(wf.FormBuildError, match=message):
            wf.build_intake_flow({"packages": packages, "fields": []})


# ── flow_token ────────────────────────────────────────────────────────────────

FORM_ID = "11111111-2222-3333-4444-555555555555"


class TestFlowToken:
    def test_round_trip_ignores_phone_formatting(self):
        token = wf.make_token(TENANT, "+91 63697 81582", FORM_ID)
        assert wf.verify_token(token, TENANT, "916369781582") == FORM_ID

    @pytest.mark.parametrize("tenant, phone", [("tenant-2", PHONE), (TENANT, "+919999999999")])
    def test_another_tenant_or_customer_is_rejected(self, tenant, phone):
        assert wf.verify_token(wf.make_token(TENANT, PHONE, FORM_ID), tenant, phone) is None

    @pytest.mark.parametrize("token", [
        "", "unused", f"wf1.{FORM_ID}.deadbeef", f"wf1.{FORM_ID}.abcdef123456.deadbeef",
        f"wf2.{FORM_ID}.abcdef123456.x", "wf1.not-a-uuid.abcdef123456.abc",
    ])
    def test_forged_tokens_are_rejected(self, token):
        assert wf.verify_token(token, TENANT, PHONE) is None

    def test_every_sent_form_gets_its_own_token(self):
        assert wf.make_token(TENANT, PHONE, FORM_ID) != wf.make_token(TENANT, PHONE, FORM_ID)

    def test_a_changed_send_id_breaks_the_signature(self):
        prefix, form_id, send_id, sig = wf.make_token(TENANT, PHONE, FORM_ID, "abcdef123456").split(".")
        assert wf.verify_token(f"{prefix}.{form_id}.abcdef654321.{sig}", TENANT, PHONE) is None


# ── package menu -> form ──────────────────────────────────────────────────────

class TestPackageMenuDetection:
    def test_package_menus_become_forms_add_on_and_detail_menus_do_not(self):
        assert wf._is_package_menu(CONFIG, {"offering_keys": ["one_question", "detailed"]})
        assert wf._is_package_menu(CONFIG, {"offering_keys": ["one_year", "two_years"]})
        assert not wf._is_package_menu(CONFIG, {"offering_keys": ["remedies", "call", "no_addons"]})
        assert not wf._is_package_menu(CONFIG, {"offering_keys": ["one_question"], "field_key": "gender"})
        assert not wf._is_package_menu(CONFIG, {"options": ["Yes", "No"]})


def _menu():
    return {"kind": "buttons", "options": ["One Question", "Detailed"], "offering_keys": ["one_question", "detailed"],
            "buttons": [{"id": "one_question", "title": "One Question"}, {"id": "detailed", "title": "Detailed"}]}


class TestSendMenu:
    def test_package_menu_goes_out_as_the_form(self, monkeypatch):
        sent = {}

        async def fake_flow(**kwargs):
            sent.update(kwargs)
            return {"messages": [{"id": "wamid.form"}]}

        monkeypatch.setattr(wf, "form_for_menu", lambda tenant_id, menu: {"id": FORM_ID, "meta_flow_id": "999"})
        monkeypatch.setattr(meta_cloud, "send_flow_message", fake_flow)
        menu = _menu()
        sid, tappable = asyncio.run(deal_turn.send_menu(PHONE, "Pick a package", menu, tenant_id=TENANT))
        assert (sid, tappable) == ("wamid.form", True)
        assert sent["flow_id"] == "999" and sent["first_screen"] == "PACKAGE"
        assert wf.verify_token(sent["flow_token"], TENANT, PHONE) == FORM_ID
        assert deal_turn.menu_record("Pick a package", menu, tappable=True) == wf.form_record("Pick a package")

    def test_form_failure_still_sends_the_buttons(self, monkeypatch):
        async def broken(**kwargs):
            raise RuntimeError("Meta refused")

        async def fake_buttons(**kwargs):
            return {"messages": [{"id": "wamid.buttons"}]}

        monkeypatch.setattr(wf, "form_for_menu", lambda tenant_id, menu: {"id": FORM_ID, "meta_flow_id": "999"})
        monkeypatch.setattr(meta_cloud, "send_flow_message", broken)
        monkeypatch.setattr(meta_cloud, "send_interactive_buttons", fake_buttons)
        menu = _menu()
        assert asyncio.run(deal_turn.send_menu(PHONE, "Pick", menu, tenant_id=TENANT)) == ("wamid.buttons", True)
        assert not menu.get("sent_as_form")

    def test_no_form_means_the_normal_menu(self, monkeypatch):
        async def fake_buttons(**kwargs):
            return {"messages": [{"id": "wamid.buttons"}]}

        monkeypatch.setattr(wf, "form_for_menu", lambda tenant_id, menu: None)
        monkeypatch.setattr(meta_cloud, "send_interactive_buttons", fake_buttons)
        assert asyncio.run(deal_turn.send_menu(PHONE, "Pick", _menu(), tenant_id=TENANT)) == ("wamid.buttons", True)


# ── a submitted form ──────────────────────────────────────────────────────────

@pytest.fixture
def world():
    w = World()
    patches: list = []
    w.install(patches)
    for p in patches:
        p.start()
    yield w
    for p in patches:
        p.stop()


@pytest.fixture
def shop(world, monkeypatch):
    db = FakeSupabase()
    db.table("tenants").insert({"id": TENANT, "enabled_features": [wf.FEATURE_KEY]}).execute()
    _, answer_map = wf.build_intake_flow(CONFIG)
    db.table("whatsapp_forms").insert({"id": FORM_ID, "tenant_id": TENANT, "kind": "intake", "status": "published",
                                       "meta_flow_id": "999", "answer_map": answer_map}).execute()
    links = []

    async def fake_send_link(phone, link, **kwargs):
        links.append(link)
        return "wamid.link", True

    monkeypatch.setattr(deal_turn, "build_context", lambda db_, t, l, p: deal_actions.DealContext(
        config=CONFIG, db=db_, lead_id=l, tenant_id=t, phone=p, offerings_enabled=True, buttons_enabled=True))
    monkeypatch.setattr(deal_turn, "send_link", fake_send_link)
    monkeypatch.setattr(intake, "note_lead_message", lambda *a, **k: None)
    monkeypatch.setattr(deal_actions, "_astro_connected", lambda ctx: False)
    monkeypatch.setattr(intake, "get_intake_config", lambda tenant_id, db=None: CONFIG)
    return db, world, links


SEND_ID = "abcdef123456"


def _answers(**over):
    answers = {
        "flow_token": wf.make_token(TENANT, PHONE, FORM_ID, SEND_ID), "p1": "detailed", "p2": "one_year",
        "a_one_year": ["remedies"], "f_name": "Prem", "f_birth_date": "2003-11-19", "f_gender": "male",
        "consent_offers": True,
    }
    answers.update(over)
    return json.dumps(answers)


def _submit(db, raw, mid="wamid.in1", phone=PHONE):
    return asyncio.run(wf.handle_submission(db, tenant_id=TENANT, lead_id=LEAD, phone=phone, raw=raw,
                                            meta_message_id=mid))


class TestSubmission:
    def test_choice_details_and_link_in_one_go(self, shop):
        db, world, links = shop
        assert _submit(db, _answers()) == "handled"
        session = next(iter(world.sessions.values()))
        assert session["package_key"] == "one_year"
        assert [a["key"] for a in session["selected_addons"]] == ["remedies"]
        assert session["collected_data"] == {"name": "Prem", "birth_date": "2003-11-19", "gender": "Male"}
        assert session["status"] == deal_engine.AWAITING_PAYMENT_STATUS
        assert len(world.links) == 1 and len(links) == 1
        assert links[0].url == "https://rzp.io/l/1"
        response = db.rows("whatsapp_form_responses")[0]
        assert response["outcome"] == "link_sent" and "flow_token" not in response["answers"]

    def test_amount_is_the_chat_flows_amount_to_the_paisa(self, shop):
        """Same choices through the AI's tools must charge exactly the same."""
        db, world, links = shop
        _submit(db, _answers())
        form_amount = world.links[0]["amount_paise"]
        subtotal = 99900 + 19900
        assert form_amount == subtotal + round(subtotal * 18 / 100)
        assert deal_engine._rupees(form_amount) in links[0].body

    @staticmethod
    def _reprice(monkeypatch, path, amount):
        repriced = json.loads(json.dumps(CONFIG))
        node = repriced["packages"]
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = amount
        monkeypatch.setattr(deal_turn, "build_context", lambda db_, t, l, p: deal_actions.DealContext(
            config=repriced, db=db_, lead_id=l, tenant_id=t, phone=p, offerings_enabled=True))
        monkeypatch.setattr(intake, "get_intake_config", lambda tenant_id, db=None: repriced)

    def test_a_lower_price_since_the_form_is_charged_at_todays_price(self, shop, monkeypatch):
        db, world, _ = shop
        self._reprice(monkeypatch, [1, "options", 1, "amount_paise"], 150000)
        assert _submit(db, _answers(p2="two_years", a_one_year=[])) == "handled"
        assert world.links[0]["amount_paise"] == 150000 + round(150000 * 18 / 100)

    def test_a_higher_price_since_the_form_goes_to_chat_never_charged_silently(self, shop, monkeypatch):
        """The chat flow asks before charging more; a form can't ask, so the AI takes over."""
        db, world, links = shop
        self._reprice(monkeypatch, [1, "options", 1, "amount_paise"], 250000)
        assert _submit(db, _answers(p2="two_years", a_one_year=[])) == "continue"
        assert world.links == [] and links == []

    def test_a_dearer_add_on_since_the_form_goes_to_chat(self, shop, monkeypatch):
        db, world, _ = shop
        self._reprice(monkeypatch, [1, "options", 0, "addons", 0, "amount_paise"], 29900)
        assert _submit(db, _answers()) == "continue"
        assert world.links == []

    def test_switched_back_to_chat_is_not_applied(self, shop, monkeypatch):
        db, world, _ = shop
        chat = {**CONFIG, "collect_with": "chat"}
        monkeypatch.setattr(deal_turn, "build_context", lambda db_, t, l, p: deal_actions.DealContext(
            config=chat, db=db_, lead_id=l, tenant_id=t, phone=p, offerings_enabled=True))
        assert _submit(db, _answers()) == "continue"
        assert world.sessions == {}

    def test_resubmitting_after_a_refused_detail_gets_an_answer(self, shop):
        """The first submission continued in chat; the same form again must not meet silence."""
        db, world, _ = shop
        assert _submit(db, _answers(p2="gone"), mid="wamid.first") == "continue"
        assert _submit(db, _answers(), mid="wamid.second") == "continue"

    def test_one_level_package_with_no_add_ons(self, shop):
        db, world, _ = shop
        assert _submit(db, _answers(p1="one_question", p2="none", a_one_year=[])) == "handled"
        assert next(iter(world.sessions.values()))["package_key"] == "one_question"

    def test_stale_choice_continues_in_chat_without_a_link(self, shop):
        db, world, links = shop
        assert _submit(db, _answers(p2="gone")) == "continue"
        assert world.links == [] and links == []
        assert db.rows("whatsapp_form_responses")[0]["outcome"] == "continued_in_chat"

    def test_forged_token_is_never_applied(self, shop):
        db, world, links = shop
        assert _submit(db, _answers(flow_token=f"wf1.{FORM_ID}.{SEND_ID}.0000")) == "continue"
        assert world.sessions == {} and links == []
        assert db.rows("whatsapp_form_responses")[0]["outcome"] == "rejected"

    def test_another_customers_form_is_never_applied(self, shop):
        db, world, _ = shop
        assert _submit(db, _answers(), phone="+919999999999") == "continue"
        assert world.sessions == {}

    def test_repeated_delivery_is_applied_once(self, shop):
        db, world, links = shop
        assert _submit(db, _answers()) == "handled"
        assert _submit(db, _answers()) == "ignored"
        assert len(world.links) == 1 and len(links) == 1

    def test_the_same_form_reopened_after_paying_cannot_book_again(self, shop):
        """A new Meta message id, but the same sent form: never a second booking or link."""
        db, world, links = shop
        assert _submit(db, _answers(), mid="wamid.first") == "handled"
        next(iter(world.sessions.values()))["status"] = deal_engine.PAID_STATUS
        assert _submit(db, _answers(), mid="wamid.second") == "ignored"
        assert len(world.sessions) == 1 and len(world.links) == 1

    def test_a_new_form_after_paying_is_a_new_booking(self, shop):
        db, world, _ = shop
        assert _submit(db, _answers(), mid="wamid.first") == "handled"
        next(iter(world.sessions.values()))["status"] = deal_engine.PAID_STATUS
        fresh = _answers(flow_token=wf.make_token(TENANT, PHONE, FORM_ID, "123456abcdef"))
        assert _submit(db, fresh, mid="wamid.second") == "handled"
        assert len(world.sessions) == 2 and len(world.links) == 2

    @pytest.mark.parametrize("ticked", [True, False])
    def test_consent_is_recorded_with_its_scope(self, shop, ticked):
        db, _, _ = shop
        _submit(db, _answers(consent_offers=ticked))
        consents = {c["scope"]: c for c in db.rows("lead_consents")}
        assert consents["replies"]["granted"] is True
        assert consents["offers"]["granted"] is ticked
        assert consents["offers"]["wording"] == wf.CONSENT_WORDING

    def test_summary_line_reads_like_the_booking(self, shop):
        db, _, _ = shop
        text = wf.summary_text(db, TENANT, PHONE, _answers())
        assert "Choice: Detailed Question › 1 Year" in text
        assert "Add-ons: Remedies PDF" in text and "Gender: Male" in text
        assert wf.summary_text(db, TENANT, PHONE, _answers(flow_token="x")) == "📝 Form submitted"


# ── publishing ────────────────────────────────────────────────────────────────

@pytest.fixture
def publisher(monkeypatch):
    db = FakeSupabase()
    db.table("tenants").insert({"id": TENANT, "enabled_features": [wf.FEATURE_KEY]}).execute()
    state = {"config": CONFIG, "published": [], "deprecated": []}
    monkeypatch.setattr(intake, "get_intake_config", lambda tenant_id, db=None: state["config"])

    async def fake_publish(tenant_id, name, flow):
        state["published"].append(name)
        if state.get("before_finish"):
            state.pop("before_finish")()
        return f"flow-{len(state['published'])}", "waba-1"

    async def fake_deprecate(tenant_id, flow_id):
        state["deprecated"].append(flow_id)

    monkeypatch.setattr(wf, "_publish", fake_publish)
    monkeypatch.setattr(wf, "_deprecate", fake_deprecate)
    return db, state


class TestPublishing:
    def test_a_save_publishes_once_and_an_unchanged_save_does_nothing(self, publisher):
        db, state = publisher
        first = asyncio.run(wf.sync_intake_form(TENANT, db=db))
        again = asyncio.run(wf.sync_intake_form(TENANT, db=db))
        assert first["status"] == "published" and again["id"] == first["id"]
        assert len(state["published"]) == 1

    def test_a_change_publishes_a_new_version_and_retires_the_old(self, publisher):
        db, state = publisher
        asyncio.run(wf.sync_intake_form(TENANT, db=db))
        state["config"] = {**CONFIG, "gst_percent": 0, "packages": CONFIG["packages"][:1]}
        asyncio.run(wf.sync_intake_form(TENANT, db=db))
        statuses = [r["status"] for r in db.rows("whatsapp_forms")]
        assert statuses == ["retired", "published"] and state["deprecated"] == ["flow-1"]

    def test_an_older_publish_finishing_last_never_replaces_the_newer_form(self, publisher):
        db, state = publisher

        def newer_save_meanwhile():
            db.table("whatsapp_forms").insert({"tenant_id": TENANT, "kind": "intake", "name": "Services form",
                                               "status": "published", "source_hash": "newer", "definition": {},
                                               "answer_map": {}}).execute()

        state["before_finish"] = newer_save_meanwhile
        settled = asyncio.run(wf.sync_intake_form(TENANT, db=db))
        rows = {r["source_hash"]: r for r in db.rows("whatsapp_forms")}
        assert settled["source_hash"] == "newer" and rows["newer"]["status"] == "published"
        older = next(r for h, r in rows.items() if h != "newer")
        assert older["status"] == "retired" and state["deprecated"] == ["flow-1"]

    def test_a_crash_while_publishing_is_shown_as_failed_not_a_spinner(self, publisher, monkeypatch):
        db, _ = publisher

        async def crash(*a, **k):
            raise KeyError("meta_access_token")

        monkeypatch.setattr(wf, "_publish", crash)
        row = asyncio.run(wf.sync_intake_form(TENANT, db=db))
        assert row["status"] == "failed" and "Try again" in row["last_error"]

    def test_a_publish_stuck_after_a_restart_reads_as_failed(self, publisher):
        db, _ = publisher
        db.table("whatsapp_forms").insert({"tenant_id": TENANT, "kind": "intake", "name": "Services form",
                                           "status": "publishing", "source_hash": "x", "definition": {},
                                           "answer_map": {}, "created_at": "2026-01-01T00:00:00+00:00"}).execute()
        status = wf.intake_status(db, TENANT)
        assert status["state"] == "failed" and status["error"]

    def test_only_a_form_matching_todays_services_is_sent(self, publisher):
        db, state = publisher
        menu = {"offering_keys": ["one_question", "detailed"]}
        asyncio.run(wf.sync_intake_form(TENANT, db=db))
        assert wf.form_for_menu(TENANT, menu, db=db)["status"] == "published"
        state["config"] = json.loads(json.dumps(CONFIG))
        state["config"]["packages"][0]["amount_paise"] = 900  # saved, new version not published yet
        assert wf.form_for_menu(TENANT, menu, db=db) is None

    def test_switched_off_means_no_form(self, publisher):
        db, _ = publisher
        asyncio.run(wf.sync_intake_form(TENANT, db=db))
        db.table("tenants").update({"enabled_features": []}).eq("id", TENANT).execute()
        assert wf.form_for_menu(TENANT, {"offering_keys": ["one_question"]}, db=db) is None
