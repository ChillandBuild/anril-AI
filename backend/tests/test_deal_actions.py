"""Executors for the AI-native deal engine (services/deal_actions.py).

The session store, Razorpay and the handover helper are replaced with in-memory fakes:
the point is to prove the GUARDRAILS (what code refuses no matter what the model asks).
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import deal_actions, deal_engine, intake

LEAD, TENANT, PHONE = "lead-1", "tenant-1", "+910000000000"

CONFIG = {
    "enabled": True,
    "service_noun": "consultation",
    "fields": [
        {"key": "name", "label": "Full name", "type": "text"},
        {"key": "birth_date", "label": "Date of birth", "type": "date"},
    ],
    "packages": [
        {"key": "one_question", "name": "One Question", "amount_paise": 4900, "button_label": "49 Rs"},
        {"key": "detailed", "name": "Detailed Question", "amount_paise": 9900, "button_label": "99Rs",
         "addons": [{"key": "report", "name": "Written report", "amount_paise": 2000}]},
        {"key": "marriage", "name": "Marriage Compatibility", "amount_paise": 9900, "button_label": "Marriage 99Rs"},
    ],
}
NO_DETAILS_CONFIG = {**CONFIG, "fields": []}


def _in(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


class World:
    """In-memory session store + recorded side effects."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.links: list[dict] = []
        self.handovers: list[str] = []
        self.cancelled: list[str] = []  # Razorpay plink ids we asked to cancel, in order
        self.events: list[str] = []
        self.cancel_ok = True
        self.pay_during_link = False  # the customer pays the OLD link while a new one is being made

    def install(self, stack_patches):
        w = self

        def get_active(lead_id, tenant_id, db):
            rows = [s for s in w.sessions.values() if s["status"] in intake._ACTIVE_STATUSES]
            return rows[-1] if rows else None

        def create(lead_id, tenant_id, db):
            sid = f"s{len(w.sessions) + 1}"
            w.sessions[sid] = {
                "id": sid, "lead_id": lead_id, "tenant_id": tenant_id, "status": "offer_pending",
                "collected_data": {}, "skipped_fields": [], "package_path": [], "selected_addons": None,
            }
            return w.sessions[sid]

        def update(session_id, patch_, db, unless_status=None):
            if unless_status and w.sessions[session_id]["status"] == unless_status:
                return False
            w.events.append("update")
            w.sessions[session_id].update(patch_)
            return True

        async def cancel(plink_id, tenant_id=None):
            w.events.append("cancel")
            w.cancelled.append(plink_id)
            return w.cancel_ok

        async def link(**kw):
            w.links.append(kw)
            if w.pay_during_link:
                for sess in w.sessions.values():
                    sess["status"] = "paid"
            return {
                "payment_link_url": f"https://rzp.io/l/{len(w.links)}",
                "razorpay_payment_link_id": f"plink_{len(w.links)}",
                "payment_link_expires_at": _in(hours=24),
            }

        def handover(lead_id, reason, tenant_id, assigned_to, db):
            w.handovers.append(reason)

        for module, name, fn in [
            (intake, "_get_active_session", get_active),
            (intake, "_create_session", create),
            (intake, "_update_session", update),
            (intake, "create_payment_link", link),
            (intake, "cancel_payment_link", cancel),
            (intake, "adopt_lead_name", lambda *a, **k: None),
        ]:
            stack_patches.append(patch.object(module, name, fn))
        import app.services.ai_reply as ai_reply
        stack_patches.append(patch.object(ai_reply, "_trigger_chat_escalation", handover))


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


def call(name, **args):
    return {"function": {"name": name, "arguments": json.dumps(args)}}


def run(calls, config=CONFIG, last_assistant_text=""):
    ctx = deal_actions.DealContext(config=config, db=object(), lead_id=LEAD, tenant_id=TENANT, phone=PHONE)
    return asyncio.run(deal_actions.apply_tool_calls(calls, ctx, last_assistant_text=last_assistant_text))


class TestSelectOffering:
    def test_unknown_key_is_refused(self, world):
        out = run([call("select_offering", key="nope")])
        assert out.refusals and not world.sessions

    def test_creates_session_with_price_snapshot_and_collecting_status(self, world):
        out = run([call("select_offering", key="one_question")])
        s = next(iter(world.sessions.values()))
        assert not out.refusals
        assert s["package_key"] == "one_question" and s["package_amount_paise"] == 4900
        assert s["total_amount_paise"] == 4900 and s["status"] == "collecting"

    def test_no_required_details_goes_straight_to_ready(self, world):
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        assert next(iter(world.sessions.values()))["status"] == "awaiting_confirmation"

    def test_offering_with_addons_refuses_until_addon_keys_given(self, world):
        out = run([call("select_offering", key="detailed")])
        assert out.refusals and not world.sessions

    def test_addon_total_is_computed_by_code(self, world):
        run([call("select_offering", key="detailed", addon_keys=["report"])])
        assert next(iter(world.sessions.values()))["total_amount_paise"] == 11900

    def test_unknown_addon_is_refused(self, world):
        out = run([call("select_offering", key="detailed", addon_keys=["free-gift"])])
        assert out.refusals and not world.sessions

    def test_paid_session_cannot_be_reselected(self, world):
        run([call("select_offering", key="one_question")])
        next(iter(world.sessions.values()))["status"] = "paid"
        out = run([call("select_offering", key="marriage")])
        assert out.refusals
        assert next(iter(world.sessions.values()))["package_key"] == "one_question"

    def test_changing_package_clears_the_old_link(self, world):
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        run([call("select_offering", key="marriage")], NO_DETAILS_CONFIG)
        s = next(iter(world.sessions.values()))
        assert s["package_key"] == "marriage" and s.get("payment_link") is None
        assert s["status"] == "awaiting_confirmation"


class TestSaveDetails:
    def test_needs_a_selected_offering_first(self, world):
        out = run([call("save_details", fields={"name": "Ravi"})])
        assert out.refusals

    def test_saves_known_keys_and_ignores_unknown(self, world):
        run([call("select_offering", key="one_question")])
        out = run([call("save_details", fields={"name": " Ravi ", "shoe_size": "9"})])
        s = next(iter(world.sessions.values()))
        assert s["collected_data"] == {"name": "Ravi"} and not out.refusals

    def test_only_unknown_keys_is_refused(self, world):
        run([call("select_offering", key="one_question")])
        assert run([call("save_details", fields={"shoe_size": "9"})]).refusals

    def test_status_flips_to_ready_when_last_detail_arrives(self, world):
        run([call("select_offering", key="one_question")])
        run([call("save_details", fields={"name": "Ravi"})])
        s = next(iter(world.sessions.values()))
        assert s["status"] == "collecting"
        run([call("save_details", fields={"birth_date": "12-03-1994"})])
        assert s["status"] == "awaiting_confirmation"

    def test_choice_field_rejects_value_not_in_options(self, world):
        config = {**CONFIG, "fields": [{"key": "plan", "label": "Plan", "type": "choice", "options": ["Gold", "Silver"]}]}
        run([call("select_offering", key="one_question")], config)
        assert run([call("save_details", fields={"plan": "Bronze"})], config).refusals
        assert not run([call("save_details", fields={"plan": "gold"})], config).refusals


class TestImpossibleDates:
    def test_date_that_cannot_exist_is_refused(self, world):
        run([call("select_offering", key="one_question")])
        out = run([call("save_details", fields={"name": "Ravi", "birth_date": "31-02-1995"})])
        s = next(iter(world.sessions.values()))
        assert s["collected_data"] == {"name": "Ravi"} and "birth_date" in out.refusals[0]

    def test_month_name_impossible_date_is_refused(self, world):
        run([call("select_offering", key="one_question")])
        assert run([call("save_details", fields={"birth_date": "30 February 1990"})]).refusals

    def test_real_dates_in_many_shapes_are_accepted(self, world):
        run([call("select_offering", key="one_question")])
        for value in ("12-03-1994", "12/3/94", "29-02-2000", "12 March 1994", "4 june 1996", "around 1995"):
            assert not run([call("save_details", fields={"birth_date": value})]).refusals, value

    def test_leap_day_in_a_non_leap_year_is_refused(self, world):
        run([call("select_offering", key="one_question")])
        assert run([call("save_details", fields={"birth_date": "29-02-2001"})]).refusals


class TestSkipDetail:
    def test_skipped_detail_counts_as_done(self, world):
        run([call("select_offering", key="one_question")])
        run([call("save_details", fields={"name": "Ravi"})])
        run([call("skip_detail", key="birth_date", reason="does not know")])
        s = next(iter(world.sessions.values()))
        assert s["skipped_fields"] == ["birth_date"] and s["status"] == "awaiting_confirmation"

    def test_unknown_field_is_refused(self, world):
        run([call("select_offering", key="one_question")])
        assert run([call("skip_detail", key="shoe_size")]).refusals


class TestPriceChangedWhileAway:
    """The business changed the price after the customer agreed (they picked it, or got a link).
    Dearer: no link until the customer says yes to the new price. Cheaper: just the new price."""

    def _agreed_at(self, world, paise):
        run([call("select_offering", key="one_question")])
        run([call("save_details", fields={"name": "Ravi", "birth_date": "12-03-1994"})])
        next(iter(world.sessions.values()))["total_amount_paise"] = paise  # what they agreed to then

    def test_a_price_rise_needs_the_customers_yes_before_a_link(self, world):
        self._agreed_at(world, 100)  # agreed at ₹1, price now ₹49
        out = run([call("create_payment_link")])
        assert out.refusals and "₹49" in out.refusals[0] and not world.links
        out = run([call("create_payment_link", customer_agreed_new_price=True)])
        assert not out.refusals and world.links[0]["amount_paise"] == 4900

    def test_a_price_drop_just_uses_the_lower_price(self, world):
        self._agreed_at(world, 9900)  # agreed at ₹99, price now ₹49
        out = run([call("create_payment_link")])
        assert not out.refusals and world.links[0]["amount_paise"] == 4900

    def test_deal_state_tells_the_ai_which_way_the_price_moved(self):
        session = {"package_key": "one_question", "package_name": "One Question", "status": "collecting",
                   "total_amount_paise": 100, "collected_data": {}}
        assert "₹1" in deal_engine.deal_state_block(CONFIG, session) and "yes" in deal_engine.deal_state_block(CONFIG, session)
        cheaper = deal_engine.deal_state_block(CONFIG, {**session, "total_amount_paise": 9900})
        assert "cheaper" in cheaper


class TestCreatePaymentLink:
    def test_refused_without_a_selection(self, world):
        out = run([call("create_payment_link")])
        assert out.refusals and not world.links and out.payment_link is None

    def test_refused_while_details_are_missing(self, world):
        run([call("select_offering", key="one_question")])
        run([call("save_details", fields={"name": "Ravi"})])
        out = run([call("create_payment_link")])
        assert out.refusals and "birth_date" in out.refusals[0] and not world.links

    def test_link_created_from_session_amount_never_from_model(self, world):
        run([call("select_offering", key="one_question")])
        run([call("save_details", fields={"name": "Ravi", "birth_date": "12-03-1994"})])
        out = run([call("create_payment_link", amount=1)])
        assert out.payment_link == "https://rzp.io/l/1" and not out.refusals
        assert world.links[0]["amount_paise"] == 4900
        s = next(iter(world.sessions.values()))
        assert s["status"] == "awaiting_payment" and s["payment_link"] == out.payment_link
        assert s["amount_paise"] == 4900

    def test_select_save_and_link_in_one_turn(self, world):
        out = run([
            call("select_offering", key="one_question"),
            call("save_details", fields={"name": "Ravi", "birth_date": "12-03-1994"}),
            call("create_payment_link"),
        ])
        assert out.payment_link and not out.refusals

    def test_existing_link_is_reused_not_recreated(self, world):
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        first = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        second = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert first.payment_link == second.payment_link and len(world.links) == 1

    def test_paid_session_gets_no_new_link(self, world):
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        next(iter(world.sessions.values()))["status"] = "paid"
        out = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.refusals and not world.links

    def test_razorpay_failure_brings_in_a_person(self, world, monkeypatch):
        async def broken(**kw):
            raise RuntimeError("Razorpay payment link creation failed: 401")

        monkeypatch.setattr(intake, "create_payment_link", broken)
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        out = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.handover and world.handovers and "payment link" in world.handovers[0].lower()
        assert out.payment_link is None and out.refusals

    def test_a_failed_link_is_not_retried_in_the_same_turn(self, world, monkeypatch):
        attempts = []

        async def broken(**kw):
            attempts.append(kw)
            raise RuntimeError("401")

        monkeypatch.setattr(intake, "create_payment_link", broken)
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        run([call("create_payment_link"), call("create_payment_link")], NO_DETAILS_CONFIG)
        assert len(attempts) == 1

    def test_customer_name_falls_back_to_phone(self, world):
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert world.links[0]["customer_name"] == PHONE


class TestLinkFreshness:
    """A stored link is resent only while it is live AND still the current price."""

    def _first_link(self, world, config=NO_DETAILS_CONFIG, key="one_question", **args):
        run([call("select_offering", key=key, **args)], config)
        out = run([call("create_payment_link")], config)
        return out, next(iter(world.sessions.values()))

    def test_expired_link_is_replaced_with_a_new_one(self, world):
        first, s = self._first_link(world)
        s["payment_link_expires_at"] = _in(hours=-1)
        out = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.payment_link != first.payment_link and len(world.links) == 2
        assert s["payment_link"] == out.payment_link and s["status"] == "awaiting_payment"
        assert datetime.fromisoformat(s["payment_link_expires_at"]) > datetime.now(timezone.utc)

    def test_paid_while_regenerating_is_not_reopened(self, world):
        _, s = self._first_link(world)
        s["payment_link_expires_at"] = _in(hours=-1)
        world.pay_during_link = True
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert s["status"] == "paid"

    def test_a_link_made_after_the_session_got_paid_is_cancelled_and_not_sent(self, world):
        _, s = self._first_link(world)
        s["payment_link_expires_at"] = _in(hours=-1)
        world.pay_during_link = True
        out = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.payment_link is None
        assert world.cancelled == ["plink_2"]  # the NEW link, never stored, is killed
        assert any("already paid" in r for r in out.refusals)

    def test_link_about_to_expire_is_replaced(self, world):
        _, s = self._first_link(world)
        s["payment_link_expires_at"] = _in(seconds=30)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert len(world.links) == 2

    def test_live_link_at_the_same_price_is_resent_without_calling_razorpay(self, world):
        first, s = self._first_link(world)
        assert s["payment_link_expires_at"]
        out = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.payment_link == first.payment_link and len(world.links) == 1

    def test_live_link_at_a_stale_price_is_replaced_and_amounts_refreshed(self, world):
        first, s = self._first_link(world)
        cheap = {**NO_DETAILS_CONFIG, "packages": [{**NO_DETAILS_CONFIG["packages"][0], "amount_paise": 100},
                                                    *NO_DETAILS_CONFIG["packages"][1:]]}
        out = run([call("create_payment_link")], cheap)
        assert out.payment_link != first.payment_link and world.links[-1]["amount_paise"] == 100
        assert s["amount_paise"] == 100 and s["total_amount_paise"] == 100 and s["package_amount_paise"] == 100

    def test_stale_addon_price_is_replaced_too(self, world):
        _, s = self._first_link(world, key="detailed", addon_keys=["report"])
        assert s["total_amount_paise"] == 11900
        pricier = {**NO_DETAILS_CONFIG, "packages": [
            NO_DETAILS_CONFIG["packages"][0],
            {**NO_DETAILS_CONFIG["packages"][1], "addons": [{"key": "report", "name": "Written report", "amount_paise": 3000}]},
            NO_DETAILS_CONFIG["packages"][2],
        ]}
        assert run([call("create_payment_link")], pricier).refusals  # a rise needs their yes first
        run([call("create_payment_link", customer_agreed_new_price=True)], pricier)
        assert world.links[-1]["amount_paise"] == 12900 and s["total_amount_paise"] == 12900
        assert s["package_amount_paise"] == 9900

    def test_legacy_row_without_an_expiry_is_regenerated(self, world):
        _, s = self._first_link(world)
        s["payment_link_expires_at"] = None
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert len(world.links) == 2

    def test_regeneration_uses_a_different_idempotency_key(self, world):
        _, s = self._first_link(world)
        s["payment_link_expires_at"] = _in(hours=-1)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        first_key, second_key = (l["idempotency_key"] for l in world.links)
        assert first_key != second_key and second_key.endswith(":payment_link")

    def test_removed_package_gets_no_link(self, world):
        _, s = self._first_link(world)
        s["payment_link_expires_at"] = _in(hours=-1)
        gone = {**NO_DETAILS_CONFIG, "packages": NO_DETAILS_CONFIG["packages"][1:]}
        out = run([call("create_payment_link")], gone)
        assert out.refusals and out.payment_link is None and len(world.links) == 1

    def test_deactivated_package_gets_no_link_even_with_a_live_link(self, world):
        _, s = self._first_link(world)
        off = {**NO_DETAILS_CONFIG, "packages": [{**NO_DETAILS_CONFIG["packages"][0], "active": False},
                                                  *NO_DETAILS_CONFIG["packages"][1:]]}
        out = run([call("create_payment_link")], off)
        assert out.refusals and out.payment_link is None and len(world.links) == 1

    def test_package_now_free_gets_no_link(self, world):
        self._first_link(world)
        free = {**NO_DETAILS_CONFIG, "packages": [{**NO_DETAILS_CONFIG["packages"][0], "amount_paise": 0},
                                                   *NO_DETAILS_CONFIG["packages"][1:]]}
        out = run([call("create_payment_link")], free)
        assert out.refusals and out.payment_link is None and len(world.links) == 1


GST_CONFIG = {**NO_DETAILS_CONFIG, "gst_percent": 18}


class TestGstOnLinks:
    """gst_percent is added at payment; the session total stays the pre-GST subtotal."""

    def _link(self, world, config=GST_CONFIG, key="one_question", **args):
        run([call("select_offering", key=key, **args)], config)
        out = run([call("create_payment_link")], config)
        return out, next(iter(world.sessions.values()))

    def test_link_charges_subtotal_plus_gst_and_records_the_split(self, world):
        out, s = self._link(world)
        assert out.payment_link and world.links[0]["amount_paise"] == 5782
        assert s["amount_paise"] == 5782 and s["gst_percent"] == 18 and s["gst_amount_paise"] == 882
        assert s["total_amount_paise"] == 4900 and s["package_amount_paise"] == 4900

    def test_description_shows_the_breakdown(self, world):
        self._link(world)
        assert "18% GST" in world.links[0]["description"]

    def test_addons_are_taxed_with_the_package(self, world):
        self._link(world, key="detailed", addon_keys=["report"])
        assert world.links[0]["amount_paise"] == round(11900 * 1.18)

    def test_gst_off_charges_the_subtotal_and_records_zero_gst(self, world):
        _, s = self._link(world, config=NO_DETAILS_CONFIG)
        assert world.links[0]["amount_paise"] == 4900 and "GST" not in world.links[0]["description"]
        assert s["amount_paise"] == 4900 and s["gst_amount_paise"] == 0

    def test_live_gst_link_is_reused_not_seen_as_stale(self, world):
        first, _ = self._link(world)
        again = run([call("create_payment_link")], GST_CONFIG)
        assert again.payment_link == first.payment_link and len(world.links) == 1

    def test_changing_the_gst_rate_replaces_the_live_link(self, world):
        first, s = self._link(world)
        out = run([call("create_payment_link")], {**GST_CONFIG, "gst_percent": 5})
        assert out.payment_link != first.payment_link
        assert world.links[-1]["amount_paise"] == 5145 and s["gst_percent"] == 5

    def test_selecting_another_offering_clears_the_gst_snapshot(self, world):
        _, s = self._link(world)
        run([call("select_offering", key="marriage")], GST_CONFIG)
        assert s["payment_link"] is None and s["amount_paise"] is None
        assert s["gst_percent"] is None and s["gst_amount_paise"] is None


class TestGstInThePrompt:
    def test_current_charge_adds_gst_to_the_subtotal(self):
        from app.services import deal_engine
        session = {"package_key": "one_question"}
        assert deal_engine.current_prices(GST_CONFIG, session) == (4900, 4900)
        assert deal_engine.current_charge(GST_CONFIG, session) == 5782
        assert deal_engine.current_charge(NO_DETAILS_CONFIG, session) == 4900

    def test_gst_inclusive_totals_are_allowed_prices(self):
        from app.services import deal_engine
        assert 57.82 in deal_engine.allowed_prices(GST_CONFIG)
        assert 49.0 in deal_engine.allowed_prices(GST_CONFIG)
        assert 57.82 not in deal_engine.allowed_prices(NO_DETAILS_CONFIG)
        assert deal_engine.unknown_prices("Your total is ₹140.42", GST_CONFIG, "") == []  # 119 + 18%

    def test_prompt_says_listed_prices_exclude_gst_only_when_set(self):
        from app.services import deal_engine
        on = deal_engine.deal_prompt(GST_CONFIG, None)
        off = deal_engine.deal_prompt(NO_DETAILS_CONFIG, None)
        assert "exclude 18% GST" in on and "GST" not in off

    def test_offering_list_keeps_the_listed_price_not_the_gst_total(self):
        from app.services import deal_engine
        block = deal_engine.offerings_block(GST_CONFIG)
        assert "₹49 " in block and "₹57.82" not in block

    def test_link_is_live_compares_against_the_gst_inclusive_charge(self):
        from app.services import deal_engine
        session = {"status": "awaiting_payment", "payment_link": "https://x", "amount_paise": 5782,
                   "payment_link_expires_at": _in(hours=24)}
        assert deal_engine.link_is_live(session, 5782)
        assert not deal_engine.link_is_live(session, 4900)

    def test_deal_state_shows_link_live_with_gst_charge(self):
        from app.services import deal_engine
        session = {"package_key": "one_question", "package_name": "One Question", "status": "awaiting_payment",
                   "payment_link": "https://x", "amount_paise": 5782, "total_amount_paise": 4900,
                   "payment_link_expires_at": _in(hours=24), "collected_data": {}}
        block = deal_engine.deal_state_block(GST_CONFIG, session)
        assert "link sent (₹57.82), not paid yet" in block
        assert "Offering: One Question — ₹49" in block


class TestShowOptions:
    def test_three_top_level_packages_become_a_list(self, world):
        out = run([call("show_options", of="packages")])
        assert out.menu["kind"] == "list"
        assert out.menu["options"] == ["49 Rs", "99Rs", "Marriage 99Rs"]

    def test_only_one_menu_per_turn(self, world):
        out = run([call("show_options", of="packages"), call("show_options", of="packages")])
        assert out.menu and len(out.refusals) == 1

    def test_same_menu_as_the_previous_message_is_refused(self, world):
        previous = "Pick one\n\n[49 Rs]  [99Rs]  [Marriage 99Rs]"
        out = run([call("show_options", of="packages")], last_assistant_text=previous)
        assert out.menu is None and out.refusals and "just shown" in out.refusals[0]

    def test_a_different_menu_is_allowed_after_a_menu(self, world):
        previous = "Pick one\n\n[Gold]  [Silver]"
        assert run([call("show_options", of="packages")], last_assistant_text=previous).menu

    def test_single_option_is_refused(self, world):
        config = {**CONFIG, "packages": CONFIG["packages"][:1]}
        assert run([call("show_options", of="packages")], config).refusals

    def test_addons_menu_includes_no_thanks(self, world):
        run([call("select_offering", key="detailed", addon_keys=["report"])])
        out = run([call("show_options", of="addons", under="detailed")])
        assert out.menu and "No thanks" in out.menu["options"]

    def test_addons_menu_refused_when_offering_has_none(self, world):
        assert run([call("show_options", of="addons", under="one_question")]).refusals


class TestHandover:
    def test_opens_a_handover_and_flags_the_outcome(self, world):
        out = run([call("hand_to_human", reason="lead says they paid")])
        assert out.handover and world.handovers == ["lead says they paid"]


class TestRobustness:
    def test_unknown_tool_is_ignored(self, world):
        out = run([call("send_quick_reply_block", block_name="x")])
        assert not out.refusals and not out.menu and not out.handover

    def test_malformed_arguments_are_refused_not_raised(self, world):
        out = run([{"function": {"name": "select_offering", "arguments": "{not json"}}])
        assert out.refusals


# ---------------------------------------------------------------- products

CATALOG = {
    "sku-runner": {"id": "sku-runner", "name": "Runner X", "item_type": "product", "price_paise": 249900, "stock_quantity": 5},
    "sku-sandal": {"id": "sku-sandal", "name": "Comfort Sandal", "item_type": "product", "price_paise": 99900, "stock_quantity": 0},
    "svc-fit": {"id": "svc-fit", "name": "Fitting session", "item_type": "service", "price_paise": None, "stock_quantity": None},
}


class Shop:
    def __init__(self, monkeypatch, held=None, existing=None):
        from app.services import deals
        self.created: list[dict] = []
        self.quoted: list[dict] = []
        self.existing = existing or []

        async def create_deal(tenant_id, lead_id, lines, source, stage="quoted", **kw):
            self.created.append({"lines": lines, "stage": stage, **kw})
            total = sum(CATALOG[line["catalog_item_id"]]["price_paise"] * line["qty"] for line in lines)
            items = [{"name": line["name"], "qty": line["qty"],
                      "line_total_paise": CATALOG[line["catalog_item_id"]]["price_paise"] * line["qty"]} for line in lines]
            return {"deal": {"id": f"d{len(self.created)}", "total_paise": total}, "items": items,
                    "payment_link": f"https://rzp.io/l/deal{len(self.created)}"}

        monkeypatch.setattr(deals, "create_deal", create_deal)
        monkeypatch.setattr(deals, "held_quantities", lambda tenant_id, ids, db=None: dict(held or {}))
        monkeypatch.setattr(deals, "upsert_quoted_deal", lambda tenant_id, lead_id, line, db=None: self.quoted.append(line))
        monkeypatch.setattr(deal_actions, "_open_awaiting_deals", lambda ctx: list(self.existing))


def run_shop(calls, max_images=3):
    ctx = deal_actions.DealContext(config={}, db=object(), lead_id=LEAD, tenant_id=TENANT, phone=PHONE,
                                   catalog=CATALOG, max_images=max_images)
    return asyncio.run(deal_actions.apply_tool_calls(calls, ctx))


class TestRecommendItem:
    def test_known_item_is_queued_for_its_photo_and_quoted(self, monkeypatch):
        shop = Shop(monkeypatch)
        out = run_shop([call("recommend_catalog_item", item_id="sku-runner")])
        assert out.image_item_ids == ("sku-runner",) and not out.refusals
        assert shop.quoted and shop.quoted[0]["catalog_item_id"] == "sku-runner"

    def test_out_of_stock_is_refused(self, monkeypatch):
        Shop(monkeypatch)
        out = run_shop([call("recommend_catalog_item", item_id="sku-sandal")])
        assert out.image_item_ids == () and "out of stock" in out.refusals[0].lower()

    def test_unknown_item_is_refused(self, monkeypatch):
        Shop(monkeypatch)
        assert run_shop([call("recommend_catalog_item", item_id="nope")]).refusals

    def test_unpriced_item_gets_a_photo_but_no_quoted_deal(self, monkeypatch):
        shop = Shop(monkeypatch)
        out = run_shop([call("recommend_catalog_item", item_id="svc-fit")])
        assert out.image_item_ids == ("svc-fit",) and not shop.quoted

    def test_same_item_twice_is_one_photo(self, monkeypatch):
        Shop(monkeypatch)
        out = run_shop([call("recommend_catalog_item", item_id="sku-runner")] * 2)
        assert out.image_item_ids == ("sku-runner",)


class TestSendQuote:
    def test_quote_uses_catalog_prices_and_returns_summary_with_link(self, monkeypatch):
        shop = Shop(monkeypatch)
        out = run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2])])
        assert shop.created[0]["stage"] == "awaiting_payment" and shop.created[0]["send_link"] is False
        assert "Runner X" in out.quote_text and "https://rzp.io/l/deal1" in out.quote_text
        assert "4,998" in out.quote_text or "4998" in out.quote_text

    def test_not_enough_stock_is_refused(self, monkeypatch):
        shop = Shop(monkeypatch, held={"sku-runner": 4})
        out = run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2])])
        assert out.refusals and not shop.created and out.quote_text is None

    def test_unpriced_or_unknown_items_are_refused(self, monkeypatch):
        shop = Shop(monkeypatch)
        out = run_shop([call("send_quote", item_ids=["svc-fit", "nope"])])
        assert out.refusals and not shop.created

    def test_zero_or_negative_quantity_is_refused(self, monkeypatch):
        shop = Shop(monkeypatch)
        out = run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[0])])
        assert out.refusals and not shop.created

    def test_same_open_quote_reuses_the_existing_link(self, monkeypatch):
        existing = [{"id": "d9", "stage": "awaiting_payment", "payment_link": "https://rzp.io/l/old",
                     "total_paise": 499800, "link_expires_at": _in(hours=10),
                     "items": [{"catalog_item_id": "sku-runner", "qty": 2, "name": "Runner X", "line_total_paise": 499800}]}]
        shop = Shop(monkeypatch, existing=existing)
        out = run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2])])
        assert not shop.created and "https://rzp.io/l/old" in out.quote_text

    def test_same_open_quote_with_a_dead_link_gets_a_fresh_link_not_the_dead_one(self, monkeypatch):
        from app.services import deals
        dead = [{"id": "d9", "stage": "awaiting_payment", "payment_link": "https://rzp.io/l/old",
                 "total_paise": 499800, "link_expires_at": _in(hours=-1),
                 "items": [{"catalog_item_id": "sku-runner", "qty": 2, "name": "Runner X", "line_total_paise": 499800}]}]
        shop = Shop(monkeypatch, existing=dead)
        regenerated = []

        async def send_payment_link(tenant_id, deal_id, *, send_whatsapp_message=True, amount_paise=None, db=None):
            regenerated.append((tenant_id, deal_id, send_whatsapp_message))
            return {"payment_link": "https://rzp.io/l/fresh", "message_sent": False}

        monkeypatch.setattr(deals, "send_payment_link", send_payment_link)
        out = run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2])])
        assert regenerated == [(TENANT, "d9", False)] and not shop.created
        assert "https://rzp.io/l/fresh" in out.quote_text and "l/old" not in out.quote_text

    def test_a_dead_link_that_cannot_be_regenerated_brings_in_a_person(self, monkeypatch):
        from app.services import deals
        dead = [{"id": "d9", "stage": "awaiting_payment", "payment_link": "https://rzp.io/l/old",
                 "total_paise": 499800, "link_expires_at": None,
                 "items": [{"catalog_item_id": "sku-runner", "qty": 2, "name": "Runner X", "line_total_paise": 499800}]}]
        Shop(monkeypatch, existing=dead)
        opened = []

        async def broken(*a, **k):
            raise RuntimeError("401")

        monkeypatch.setattr(deals, "send_payment_link", broken)
        monkeypatch.setattr(deal_actions, "open_handover", lambda ctx, reason: opened.append(reason))
        out = run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2])])
        assert out.handover and opened and out.quote_text is None

    def test_quote_failure_brings_in_a_person(self, monkeypatch):
        from app.services import deals
        Shop(monkeypatch)
        opened = []

        async def broken(*a, **k):
            raise RuntimeError("401")

        monkeypatch.setattr(deals, "create_deal", broken)
        monkeypatch.setattr(deal_actions, "open_handover", lambda ctx, reason: opened.append(reason))
        out = run_shop([call("send_quote", item_ids=["sku-runner"])])
        assert out.handover and opened and out.quote_text is None

    def test_only_one_quote_per_turn(self, monkeypatch):
        shop = Shop(monkeypatch)
        out = run_shop([call("send_quote", item_ids=["sku-runner"])] * 2)
        assert len(shop.created) == 1 and len(out.refusals) == 1


class TestPaymentConcernBlocksLinks:
    def test_no_package_link_while_they_say_they_paid(self, world):
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        ctx = deal_actions.DealContext(config=NO_DETAILS_CONFIG, db=object(), lead_id=LEAD, tenant_id=TENANT,
                                       phone=PHONE, payment_concern=True)
        out = asyncio.run(deal_actions.apply_tool_calls([call("create_payment_link")], ctx))
        assert out.payment_link is None and out.refusals and not world.links

    def test_no_product_quote_while_they_say_they_paid(self, monkeypatch):
        shop = Shop(monkeypatch)
        ctx = deal_actions.DealContext(config={}, db=object(), lead_id=LEAD, tenant_id=TENANT, phone=PHONE,
                                       catalog=CATALOG, payment_concern=True)
        out = asyncio.run(deal_actions.apply_tool_calls([call("send_quote", item_ids=["sku-runner"])], ctx))
        assert out.quote_text is None and out.refusals and not shop.created


class TestAutoLinkWhenReady:
    def _run(self, calls, config, auto=True):
        ctx = deal_actions.DealContext(config=config, db=object(), lead_id=LEAD, tenant_id=TENANT, phone=PHONE)
        return asyncio.run(deal_actions.apply_tool_calls(calls, ctx, auto_link=auto))

    def test_choice_with_nothing_to_collect_gets_its_link_without_being_asked(self, world):
        out = self._run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        assert out.payment_link and world.links[0]["amount_paise"] == 4900

    def test_switching_package_gets_the_new_amounts_link(self, world):
        self._run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        out = self._run([call("select_offering", key="marriage")], NO_DETAILS_CONFIG)
        assert out.payment_link and world.links[-1]["amount_paise"] == 9900

    def test_last_detail_saved_gets_the_link(self, world):
        self._run([call("select_offering", key="one_question")], CONFIG)
        out = self._run([call("save_details", fields={"name": "Ravi", "birth_date": "12-03-1994"})], CONFIG)
        assert out.payment_link

    def test_nothing_when_details_are_still_missing(self, world):
        out = self._run([call("select_offering", key="one_question"), call("save_details", fields={"name": "R"})], CONFIG)
        assert out.payment_link is None and not world.links

    def test_not_during_detail_capture(self, world):
        out = self._run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG, auto=False)
        assert out.payment_link is None and not world.links

    def test_one_link_when_the_model_also_asked(self, world):
        out = self._run([call("select_offering", key="one_question"), call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.payment_link and len(world.links) == 1

    def test_no_auto_link_on_a_payment_concern(self, world):
        ctx = deal_actions.DealContext(config=NO_DETAILS_CONFIG, db=object(), lead_id=LEAD, tenant_id=TENANT,
                                       phone=PHONE, payment_concern=True)
        out = asyncio.run(deal_actions.apply_tool_calls([call("select_offering", key="one_question")], ctx, auto_link=True))
        assert out.payment_link is None and not world.links


class TestLinkCancel:
    """R2: a replaced link is cancelled on Razorpay, after the new one is stored, best effort."""

    def _first_link(self, world, key="one_question"):
        run([call("select_offering", key=key)], NO_DETAILS_CONFIG)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        return next(iter(world.sessions.values()))

    def test_link_creation_stores_the_razorpay_plink_id(self, world):
        s = self._first_link(world)
        assert s["razorpay_payment_link_id"] == "plink_1" and s["payment_link"] == "https://rzp.io/l/1"
        assert world.cancelled == []

    def test_regenerating_a_dead_price_link_cancels_the_old_plink_after_storing_the_new_one(self, world):
        s = self._first_link(world)
        cheaper = {**NO_DETAILS_CONFIG, "packages": [{**NO_DETAILS_CONFIG["packages"][0], "amount_paise": 100},
                                                     *NO_DETAILS_CONFIG["packages"][1:]]}
        world.events.clear()
        run([call("create_payment_link")], cheaper)
        assert world.cancelled == ["plink_1"]
        assert s["razorpay_payment_link_id"] == "plink_2"
        assert world.events == ["update", "cancel"]

    def test_a_failed_cancel_does_not_undo_the_new_link(self, world):
        s = self._first_link(world)
        world.cancel_ok = False
        s["payment_link_expires_at"] = _in(hours=10)
        s["amount_paise"] = 1  # price moved: the stored link is stale
        out = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.payment_link == "https://rzp.io/l/2" and s["razorpay_payment_link_id"] == "plink_2"
        assert world.cancelled == ["plink_1"]

    def test_a_live_link_is_reused_and_nothing_is_cancelled(self, world):
        self._first_link(world)
        out = run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert out.payment_link == "https://rzp.io/l/1" and world.cancelled == []

    def test_an_expired_link_needs_no_cancel_call(self, world):
        s = self._first_link(world)
        s["payment_link_expires_at"] = _in(hours=-1)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        assert world.cancelled == [] and s["razorpay_payment_link_id"] == "plink_2"

    def test_repointing_the_offering_cancels_the_old_plink(self, world):
        s = self._first_link(world)
        world.events.clear()
        run([call("select_offering", key="marriage")], CONFIG)
        assert world.cancelled == ["plink_1"]
        assert s["package_key"] == "marriage" and s["payment_link"] is None
        assert world.events[0] == "update" and world.events[-1] == "cancel"

    def test_reselecting_the_same_offering_keeps_the_link(self, world):
        self._first_link(world)
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        assert world.cancelled == []

    def test_relinking_after_a_repoint_uses_a_key_that_cannot_replay_the_cancelled_link(self, world):
        self._first_link(world)
        run([call("select_offering", key="marriage")], NO_DETAILS_CONFIG)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        run([call("select_offering", key="one_question")], NO_DETAILS_CONFIG)
        run([call("create_payment_link")], NO_DETAILS_CONFIG)
        keys = [l["idempotency_key"] for l in world.links]
        assert len(keys) == len(set(keys)) == 3


@pytest.mark.asyncio
async def test_send_quote_relinks_a_deal_whose_link_expired_instead_of_opening_a_second_deal():
    """D2: an expired link is cleared but the deal stays open in awaiting_payment."""
    from unittest.mock import AsyncMock, patch as _patch
    from app.services import deal_actions as da

    lines = [{"catalog_item_id": "c1", "qty": 1, "name": "Ring"}]
    expired = {"id": "d1", "payment_link": None, "total_paise": 5000, "link_expires_at": None,
               "items": [{"catalog_item_id": "c1", "qty": 1, "name": "Ring", "line_total_paise": 5000}]}
    ctx = da.DealContext(config={}, db=object(), lead_id="l", tenant_id="t", phone="+91",
                         catalog={"c1": {"name": "Ring", "price_paise": 5000, "stock_quantity": None}})
    relink = AsyncMock(return_value={"payment_link": "https://rzp.io/new"})
    create = AsyncMock()
    with _patch.object(da, "_open_awaiting_deals", return_value=[expired]), \
         _patch("app.services.deals.send_payment_link", relink), _patch("app.services.deals.create_deal", create):
        turn = da._Turn()
        assert await da._send_quote(ctx, {"item_ids": ["c1"], "quantities": [1]}, turn) is None
    relink.assert_awaited_once()
    create.assert_not_awaited()
    assert "https://rzp.io/new" in turn.quote_text


class TestPayFullInsteadOfAdvance:
    """A customer who is offered an advance can say "I will pay it all now": send_quote(pay_full=true)."""

    def test_a_new_quote_asks_the_advance_rule_by_default(self, monkeypatch):
        shop = Shop(monkeypatch)
        run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2])])
        assert shop.created[0]["advance_by_rule"] is True

    def test_pay_full_is_ignored_when_the_owner_switched_it_off(self, monkeypatch):
        from app.services import order_quotes
        monkeypatch.setattr(order_quotes, "advance_options", lambda t: {"staff_can_change": True, "ai_pay_full": False})
        shop = Shop(monkeypatch)
        run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2], pay_full=True)])
        assert shop.created[0]["advance_by_rule"] is True

    def test_pay_full_makes_a_new_quote_without_the_advance_rule(self, monkeypatch):
        shop = Shop(monkeypatch)
        out = run_shop([call("send_quote", item_ids=["sku-runner"], quantities=[2], pay_full=True)])
        assert shop.created[0]["advance_by_rule"] is False and "https://rzp.io/l/deal1" in out.quote_text

    def test_pay_full_on_an_open_advance_quote_swaps_in_a_full_amount_link(self, monkeypatch):
        from app.services import deals
        from tests.fake_supabase import FakeSupabase
        db = FakeSupabase()
        db.add("deals", id="d9", tenant_id=TENANT, advance_paise=100000, paid_paise=0,
               payment_link="https://rzp.io/l/advance", razorpay_payment_link_id="plink_adv", total_paise=499800)
        existing = [{"id": "d9", "stage": "awaiting_payment", "payment_link": "https://rzp.io/l/advance",
                     "total_paise": 499800, "advance_paise": 100000, "paid_paise": 0, "link_expires_at": _in(hours=10),
                     "items": [{"catalog_item_id": "sku-runner", "qty": 2, "name": "Runner X", "line_total_paise": 499800}]}]
        shop = Shop(monkeypatch, existing=existing)
        asked, cancelled = [], []

        async def send_payment_link(tenant_id, deal_id, *, send_whatsapp_message=True, amount_paise=None, db=None):
            row = db.rows("deals")[0]
            asked.append((amount_paise, row["advance_paise"], row["payment_link"]))
            return {"payment_link": "https://rzp.io/l/full", "message_sent": False,
                    "deal_patch": {"razorpay_payment_link_id": "plink_full"}}

        async def cancel(plink_id, tenant_id):
            cancelled.append(plink_id)
            return True

        import app.services.payment_razorpay as rzp
        monkeypatch.setattr(deals, "send_payment_link", send_payment_link)
        monkeypatch.setattr(rzp, "cancel_payment_link", cancel)
        ctx = deal_actions.DealContext(config={}, db=db, lead_id=LEAD, tenant_id=TENANT, phone=PHONE,
                                       catalog=CATALOG, max_images=3)
        out = asyncio.run(deal_actions.apply_tool_calls(
            [call("send_quote", item_ids=["sku-runner"], quantities=[2], pay_full=True)], ctx))
        assert not shop.created
        assert asked == [(None, 0, None)]  # no advance, no old link to reuse, whole balance
        assert cancelled == ["plink_adv"]
        assert "https://rzp.io/l/full" in out.quote_text and "advance" not in out.quote_text.lower()

    def test_a_failed_full_link_puts_the_advance_back(self, monkeypatch):
        from app.services import deals
        from tests.fake_supabase import FakeSupabase
        db = FakeSupabase()
        db.add("deals", id="d9", tenant_id=TENANT, advance_paise=100000, paid_paise=0,
               payment_link="https://rzp.io/l/advance", total_paise=499800)
        existing = [{"id": "d9", "stage": "awaiting_payment", "payment_link": "https://rzp.io/l/advance",
                     "total_paise": 499800, "advance_paise": 100000, "paid_paise": 0, "link_expires_at": _in(hours=10),
                     "items": [{"catalog_item_id": "sku-runner", "qty": 2, "name": "Runner X", "line_total_paise": 499800}]}]
        Shop(monkeypatch, existing=existing)

        async def broken(*a, **k):
            raise RuntimeError("401")

        monkeypatch.setattr(deals, "send_payment_link", broken)
        monkeypatch.setattr(deal_actions, "open_handover", lambda ctx, reason: None)
        ctx = deal_actions.DealContext(config={}, db=db, lead_id=LEAD, tenant_id=TENANT, phone=PHONE,
                                       catalog=CATALOG, max_images=3)
        out = asyncio.run(deal_actions.apply_tool_calls(
            [call("send_quote", item_ids=["sku-runner"], quantities=[2], pay_full=True)], ctx))
        row = db.rows("deals")[0]
        assert out.quote_text is None and row["advance_paise"] == 100000 and row["payment_link"] == "https://rzp.io/l/advance"


class TestPayFullNeverLeavesTwoLinks:
    def test_an_advance_link_that_will_not_cancel_is_kept_and_the_full_link_taken_back(self, monkeypatch):
        from app.services import deals
        import app.services.payment_razorpay as rzp
        from tests.fake_supabase import FakeSupabase
        db = FakeSupabase()
        db.add("deals", id="d9", tenant_id=TENANT, advance_paise=100000, paid_paise=0,
               payment_link="https://rzp.io/l/advance", razorpay_payment_link_id="plink_adv", total_paise=499800,
               link_expires_at=_in(hours=10))
        existing = [{"id": "d9", "stage": "awaiting_payment", "payment_link": "https://rzp.io/l/advance",
                     "total_paise": 499800, "advance_paise": 100000, "paid_paise": 0, "link_expires_at": _in(hours=10),
                     "items": [{"catalog_item_id": "sku-runner", "qty": 2, "name": "Runner X", "line_total_paise": 499800}]}]
        Shop(monkeypatch, existing=existing)
        cancelled = []

        async def send_payment_link(tenant_id, deal_id, *, send_whatsapp_message=True, amount_paise=None, db=None):
            db.table("deals").update({"payment_link": "https://rzp.io/l/full", "razorpay_payment_link_id": "plink_full"}) \
                .eq("id", deal_id).execute()
            return {"payment_link": "https://rzp.io/l/full", "message_sent": False,
                    "deal_patch": {"razorpay_payment_link_id": "plink_full"}}

        async def cancel(plink_id, tenant_id):
            cancelled.append(plink_id)
            return plink_id != "plink_adv"  # Razorpay refuses to cancel the advance link

        monkeypatch.setattr(deals, "send_payment_link", send_payment_link)
        monkeypatch.setattr(rzp, "cancel_payment_link", cancel)
        ctx = deal_actions.DealContext(config={}, db=db, lead_id=LEAD, tenant_id=TENANT, phone=PHONE,
                                       catalog=CATALOG, max_images=3)
        out = asyncio.run(deal_actions.apply_tool_calls(
            [call("send_quote", item_ids=["sku-runner"], quantities=[2], pay_full=True)], ctx))
        row = db.rows("deals")[0]
        assert cancelled == ["plink_adv", "plink_full"]
        assert row["payment_link"] == "https://rzp.io/l/advance" and row["razorpay_payment_link_id"] == "plink_adv"
        assert row["advance_paise"] == 100000
        assert "https://rzp.io/l/full" not in (out.quote_text or "")
        # The kept link asks only the advance, so the text must say so (not "Pay here" next to the full total).
        assert "Pay the advance here: https://rzp.io/l/advance" in (out.quote_text or "")
