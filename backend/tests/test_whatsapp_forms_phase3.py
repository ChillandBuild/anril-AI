"""WhatsApp Forms Phase 3: when a form goes out by itself (AI rule, the ad they came from, the
broadcast they answered), the "Open form" template button and its per-customer token, and the
form's numbers."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import deal_actions, deal_turn, meta_cloud
from app.services import whatsapp_form_reach as reach
from app.services import whatsapp_forms as wf
from tests.fake_supabase import FakeSupabase
from tests.test_whatsapp_forms import PHONE, TENANT
from tests.test_whatsapp_forms_phase2 import _design

LEAD = "11111111-0000-0000-0000-000000000001"
D_ALL, D_ONE, D_CAST = (f"22222222-0000-0000-0000-00000000000{i}" for i in (1, 2, 3))


def _publish(db, design):
    flow, answer_map = wf.build_custom_flow(design)
    return db.table("whatsapp_forms").insert({
        "tenant_id": TENANT, "kind": "custom", "design_id": design["id"], "name": design["name"],
        "status": "published", "meta_flow_id": f"flow-{design['id'][-1]}", "source_hash": wf.source_hash(flow),
        "definition": flow, "answer_map": answer_map,
    }).execute().data[0]


@pytest.fixture
def db():
    db = FakeSupabase()
    db.table("tenants").insert({"id": TENANT, "enabled_features": [wf.FEATURE_KEY]}).execute()
    db.table("leads").insert({"id": LEAD, "tenant_id": TENANT, "phone": PHONE}).execute()
    designs = [
        _design(id=D_ALL, name="Any ad", triggers={"ads": {"enabled": True, "ad_ids": [], "timing": "after"}}),
        _design(id=D_ONE, name="Diwali ad", triggers={"ads": {"enabled": True, "ad_ids": ["555"], "timing": "instead"}}),
        _design(id=D_CAST, name="Offer reply", triggers={
            "broadcasts": {"enabled": True, "templates": ["diwali_offer"], "timing": "instead"},
            "ai": {"enabled": True, "when": "when they ask for a site visit"}}),
    ]
    for d in designs:
        db.table("whatsapp_form_designs").insert({**d, "tenant_id": TENANT, "archived": False}).execute()
        _publish(db, d)
    return db


# ── rules ─────────────────────────────────────────────────────────────────────

class TestRules:
    def test_unknown_parts_are_dropped_and_defaults_filled(self):
        t = reach.clean_triggers({"ads": {"enabled": 1, "timing": "never"}, "junk": True})
        assert t["ads"] == {"enabled": True, "ad_ids": [], "timing": "instead"}
        assert set(t) == {"ai", "ads", "broadcasts"}

    @pytest.mark.parametrize("raw, message", [
        ({"ai": {"enabled": True, "when": "  "}}, "Tell Anril when"),
        ({"ai": {"enabled": True, "when": "x" * 301}}, "at most 300"),
        ({"ads": {"enabled": True, "ad_ids": ["abc"]}}, "isn't a Meta ad"),
        ({"broadcasts": {"enabled": True, "templates": []}}, "at least one broadcast"),
    ])
    def test_rules_that_cant_work_are_refused_in_plain_words(self, raw, message):
        assert any(message in p for p in reach.trigger_problems(raw))

    def test_the_rule_can_be_written_in_tamil(self):
        assert reach.trigger_problems({"ai": {"enabled": True, "when": "வீடு பார்க்க வர விரும்பும்போது"}}) == []


# ── incoming chats ────────────────────────────────────────────────────────────

class TestInboundMatch:
    def test_an_ad_rule_naming_this_ad_beats_the_every_ad_rule(self, db):
        match = reach.inbound_match(db, TENANT, LEAD, ad_id="555", context_wamid=None)
        assert match["design"]["id"] == D_ONE and match["timing"] == "instead" and match["via"] == "ad"

    def test_any_other_ad_gets_the_every_ad_form(self, db):
        match = reach.inbound_match(db, TENANT, LEAD, ad_id="999", context_wamid=None)
        assert match["design"]["id"] == D_ALL and match["timing"] == "after"

    def test_a_reply_to_that_broadcast_gets_its_form(self, db):
        db.table("messages").insert({"tenant_id": TENANT, "lead_id": LEAD, "direction": "outbound",
                                     "content": "[Template: diwali_offer]", "meta_message_id": "wamid.cast"}).execute()
        match = reach.inbound_match(db, TENANT, LEAD, ad_id=None, context_wamid="wamid.cast")
        assert match["design"]["id"] == D_CAST and match["via"] == "broadcast"

    def test_a_reply_to_another_broadcast_gets_nothing(self, db):
        db.table("messages").insert({"tenant_id": TENANT, "lead_id": LEAD, "direction": "outbound",
                                     "content": "[Template: welcome]", "meta_message_id": "wamid.other"}).execute()
        assert reach.inbound_match(db, TENANT, LEAD, ad_id=None, context_wamid="wamid.other") is None

    def _sent(self, db, content, ago, wamid=None):
        db.table("messages").insert({"tenant_id": TENANT, "lead_id": LEAD, "direction": "outbound", "content": content,
                                     "meta_message_id": wamid,
                                     "created_at": (datetime.now(timezone.utc) - ago).isoformat()}).execute()

    def test_a_typed_reply_soon_after_the_broadcast_gets_its_form(self, db):
        self._sent(db, "[Template: diwali_offer]", timedelta(days=2))
        match = reach.inbound_match(db, TENANT, LEAD, ad_id=None, context_wamid=None)
        assert match["design"]["id"] == D_CAST and match["via"] == "broadcast"

    def test_a_typed_reply_after_three_days_gets_nothing(self, db):
        self._sent(db, "[Template: diwali_offer]", timedelta(days=3, minutes=1))
        assert reach.inbound_match(db, TENANT, LEAD, ad_id=None, context_wamid=None) is None

    def test_a_typed_message_after_the_chat_moved_on_gets_nothing(self, db):
        self._sent(db, "[Template: diwali_offer]", timedelta(hours=5))
        self._sent(db, "Our price is 500 rupees", timedelta(hours=4))
        assert reach.inbound_match(db, TENANT, LEAD, ad_id=None, context_wamid=None) is None

    def test_a_typed_message_with_no_broadcast_gets_nothing(self, db):
        assert reach.inbound_match(db, TENANT, LEAD, ad_id=None, context_wamid=None) is None

    def test_not_sent_twice_within_a_week(self, db):
        db.table("whatsapp_form_sends").insert({"tenant_id": TENANT, "design_id": D_ONE, "lead_id": LEAD, "via": "ad",
                                                "send_id": "a" * 12,
                                                "created_at": datetime.now(timezone.utc).isoformat()}).execute()
        match = reach.inbound_match(db, TENANT, LEAD, ad_id="555", context_wamid=None)
        assert match["design"]["id"] == D_ALL  # the next rule that applies

    def test_unpublished_changes_or_switched_off_means_no_form(self, db):
        for row in db.rows("whatsapp_form_designs"):
            row["fields"][0]["label"] = "Changed"
        assert reach.inbound_match(db, TENANT, LEAD, ad_id="555", context_wamid=None) is None
        db.rows("tenants")[0]["enabled_features"] = []
        assert reach.inbound_match(db, TENANT, LEAD, ad_id="555", context_wamid=None) is None

    def test_sending_logs_it_in_the_chat_and_the_forms_numbers(self, db, monkeypatch):
        async def fake_flow(**kwargs):
            return {"messages": [{"id": "wamid.f"}]}

        monkeypatch.setattr(meta_cloud, "send_flow_message", fake_flow)
        match = reach.inbound_match(db, TENANT, LEAD, ad_id="555", context_wamid=None)
        asyncio.run(reach.send_match(db, TENANT, LEAD, PHONE, match))
        assert db.rows("messages")[-1]["meta_message_id"] == "wamid.f"
        assert reach.stats(db, TENANT, D_ONE) == {"sent": 1, "submitted": 0, "paid": None}
        assert db.rows("whatsapp_form_sends")[-1]["via"] == "ad"


# ── the AI ────────────────────────────────────────────────────────────────────

class TestAiSendsForms:
    def test_only_forms_with_the_ai_rule_are_offered_with_their_rule(self, db):
        tool = reach.ai_tool(reach.ai_forms(db, TENANT))
        assert tool["function"]["parameters"]["properties"]["form_id"]["enum"] == [D_CAST]
        assert "when they ask for a site visit" in tool["function"]["description"]

    def test_no_ai_forms_means_no_tool(self):
        assert reach.ai_tool([]) is None

    def _ctx(self, db):
        return deal_actions.DealContext(config={}, db=db, lead_id=LEAD, tenant_id=TENANT, phone=PHONE,
                                        buttons_enabled=True)

    def test_the_ai_can_send_an_allowed_form(self, db):
        outcome = asyncio.run(deal_actions.apply_tool_calls(
            [{"function": {"name": "send_form", "arguments": f'{{"form_id": "{D_CAST}"}}'}}], self._ctx(db)))
        assert outcome.refusals == () and outcome.menu["kind"] == "form" and outcome.menu["design_id"] == D_CAST

    def test_the_ai_cannot_send_a_form_without_the_rule(self, db):
        outcome = asyncio.run(deal_actions.apply_tool_calls(
            [{"function": {"name": "send_form", "arguments": f'{{"form_id": "{D_ALL}"}}'}}], self._ctx(db)))
        assert outcome.menu is None and "not one of the forms" in outcome.refusals[0]

    def test_the_ais_form_goes_out_under_its_words(self, db, monkeypatch):
        sent = {}

        async def fake_flow(**kwargs):
            sent.update(kwargs)
            return {"messages": [{"id": "wamid.ai"}]}

        monkeypatch.setattr(meta_cloud, "send_flow_message", fake_flow)
        monkeypatch.setattr(deal_turn, "_db", lambda: db)
        menu = {"kind": "form", "design_id": D_CAST, "cta": "x", "options": []}
        sid, tappable = asyncio.run(deal_turn.send_menu(PHONE, "Fill this to book a visit 👇", menu, tenant_id=TENANT))
        assert (sid, tappable) == ("wamid.ai", True) and sent["body_text"] == "Fill this to book a visit 👇"
        assert db.rows("whatsapp_form_sends")[-1]["via"] == "ai"
        assert deal_turn.menu_record("Fill", menu, tappable=True).endswith("]")


# ── template "Open form" button ───────────────────────────────────────────────

class TestTemplateButton:
    def test_meta_gets_a_flow_button_grouped_with_the_call_to_actions(self):
        buttons = meta_cloud._build_button_components(
            [{"type": "QUICK_REPLY", "text": "Stop"}, {"type": "FLOW", "text": "Book now", "flow_id": "77",
                                                       "navigate_screen": "QUESTIONS_A"}], 10, "MARKETING")
        flow = next(b for b in buttons if b["type"] == "FLOW")
        assert flow == {"type": "FLOW", "text": "Book now", "flow_id": "77", "navigate_screen": "QUESTIONS_A",
                        "flow_action": "navigate"}
        assert [b["type"] for b in reach.group_buttons([{"type": "QUICK_REPLY"}, {"type": "FLOW"}])] == ["FLOW", "QUICK_REPLY"]

    def test_every_template_send_gets_a_token_for_that_customer(self, db):
        db.table("message_templates").insert({"tenant_id": TENANT, "name": "diwali_offer", "buttons": [
            {"type": "URL", "text": "Shop"}, {"type": "FLOW", "text": "Book", "flow_id": "flow-3"}]}).execute()
        component = reach.template_flow_component(db, TENANT, "diwali_offer", PHONE, [])
        assert component["sub_type"] == "flow" and component["index"] == "1"
        token = component["parameters"][0]["action"]["flow_token"]
        version = next(v for v in db.rows("whatsapp_forms") if v["meta_flow_id"] == "flow-3")
        assert wf.verify_token(token, TENANT, PHONE) == version["id"]
        assert wf.verify_token(token, TENANT, "+919999999999") is None
        assert db.rows("whatsapp_form_sends")[-1]["via"] == "template"

    def test_templates_without_a_form_or_already_tokened_are_left_alone(self, db):
        db.table("message_templates").insert({"tenant_id": TENANT, "name": "plain", "buttons": [{"type": "URL"}]}).execute()
        assert reach.template_flow_component(db, TENANT, "plain", PHONE, []) is None
        assert reach.template_flow_component(db, TENANT, "x", PHONE, [{"type": "button", "sub_type": "flow"}]) is None

    def test_a_replaced_version_stays_open_while_a_template_uses_it(self, db, monkeypatch):
        deprecated = []

        async def fake_deprecate(tenant_id, flow_id):
            deprecated.append(flow_id)

        monkeypatch.setattr(wf, "_deprecate", fake_deprecate)
        db.table("message_templates").insert({"tenant_id": TENANT, "name": "t", "buttons": [
            {"type": "FLOW", "flow_id": "flow-3"}]}).execute()
        asyncio.run(wf.retire_design(db, TENANT, D_CAST))
        asyncio.run(wf.retire_design(db, TENANT, D_ALL))
        assert deprecated == ["flow-1"]  # flow-3 is still opened by the approved template

    def test_template_button_must_point_at_a_live_form(self, db):
        with pytest.raises(wf.FormBuildError, match="Publish"):
            reach.resolve_form_button(db, TENANT, "services")
        pinned = reach.resolve_form_button(db, TENANT, D_CAST)
        assert pinned["flow_id"] == "flow-3" and pinned["navigate_screen"] == "QUESTIONS_A"


def test_numbers_count_submissions_not_rejected_ones(db):
    version = next(v for v in db.rows("whatsapp_forms") if v["design_id"] == D_CAST)
    for i, outcome in enumerate(["saved", "saved", "rejected"]):
        db.table("whatsapp_form_responses").insert({"tenant_id": TENANT, "form_id": version["id"], "lead_id": LEAD,
                                                    "meta_message_id": f"m{i}", "answers": {},
                                                    "outcome": outcome}).execute()
    assert reach.stats(db, TENANT, D_CAST)["submitted"] == 2
