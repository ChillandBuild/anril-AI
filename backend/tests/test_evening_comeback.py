"""v9.2 #26: Evening summary and Come-back offer."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase  # noqa: E402

from app.services import comeback_offer as co, evening_summary as ev  # noqa: E402

T = "t1"
NOW = datetime(2026, 11, 23, 14, 30, tzinfo=timezone.utc)          # 8 PM IST
DAYTIME = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)        # 11:30 AM IST
OK = {"messages": [{"id": "wamid.1"}]}


def _tpl(db, name, status="APPROVED", body="Hi {{1}}, {{2}} code {{3}} till {{4}}"):
    return db.add("message_templates", tenant_id=T, name=name, status=status, meta_waba_id="w1", language="en",
                  body_text=body)


def _base() -> FakeSupabase:
    db = FakeSupabase()
    db.add("tenants", id=T, name="Sri Stores", contact_phone="98765 43210")
    return db


def _waba():
    return patch("app.services.call_details_share.get_setting", return_value="w1")


# ───────────────────────────────────────────────────────────── evening summary

def test_rupees_use_indian_grouping():
    assert [ev.rupees_text(p) for p in (0, 12_345_00, 123_456_00, 12_34_56_700)] == ["0", "12,345", "1,23,456", "12,34,567"]


def test_rupees_under_one_rupee_keep_the_paise():
    # Same rule as the other money helpers: whole rupees when exact, two decimals when not.
    assert [ev.rupees_text(p) for p in (50, 99, 12_345_50, 100_00_050)] == ["0.50", "0.99", "12,345.50", "1,00,000.50"]
    assert ev.template_values("S", {"money_paise": 50})[4] == "Money in today: ₹0.50."


def test_values_with_and_without_money():
    v = ev.template_values("Sri Stores", {"chats": 24, "new_leads": 6, "orders": 3, "money_paise": 12_450_00})
    assert v == ["Sri Stores", "24", "6", "3", "Money in today: ₹12,450."]
    v = ev.template_values("Sri Stores", {"chats": 0, "new_leads": 0, "orders": 0, "money_paise": 0})
    assert v[4] == "No payments today."
    assert len(v) == 5 and ev.TEMPLATE_BODY.count("{{") == 5


def test_build_summary_counts_only_today_and_this_business():
    db = _base()
    today, yday = "2026-11-23T05:00:00+00:00", "2026-11-22T05:00:00+00:00"
    for lead, at in (("a", today), ("a", today), ("b", today), ("c", yday)):
        db.add("messages", tenant_id=T, lead_id=lead, direction="inbound", created_at=at)
    db.add("messages", tenant_id="t2", lead_id="z", direction="inbound", created_at=today)
    db.add("messages", tenant_id=T, lead_id="a", direction="outbound", created_at=today)
    db.add("leads", tenant_id=T, created_at=today)
    db.add("leads", tenant_id=T, created_at=yday)
    db.add("deals", tenant_id=T, stage="won", won_at=today)
    db.add("deals", tenant_id=T, stage="quoted", won_at=None)
    db.add("deal_payments", tenant_id=T, amount_paise=500_00, paid_at=today)
    db.add("deal_payments", tenant_id=T, amount_paise=250_00, paid_at=yday)
    s = ev.build_summary(db, T, NOW)
    assert s == {"chats": 2, "new_leads": 1, "orders": 1, "money_paise": 500_00}


def test_off_by_default_and_waiting_note():
    db = _base()
    s = ev.get_settings(db, T)
    assert s["on"] is False and s["waiting_for_approval"] is True and s["note"] == "Waiting for WhatsApp to approve"
    _tpl(db, ev.TEMPLATE_NAME)
    s = ev.get_settings(db, T)
    assert s["waiting_for_approval"] is False and s["note"] is None
    assert ev.save_on(db, T, True)["on"] is True


def test_skips_when_template_not_approved_or_setting_off():
    db = _base()
    ev.save_on(db, T, True)
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(return_value=OK)) as send:
        assert ev.send_evening_summaries(db, NOW) == 0                    # no template yet
        _tpl(db, ev.TEMPLATE_NAME, status="PENDING")
        assert ev.send_evening_summaries(db, NOW) == 0
        send.assert_not_called()
    db2 = _base()
    _tpl(db2, ev.TEMPLATE_NAME)
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(return_value=OK)) as send:
        assert ev.send_evening_summaries(db2, NOW) == 0                    # off
        send.assert_not_called()


def test_sends_once_a_day_to_the_owner_number():
    db = _base()
    _tpl(db, ev.TEMPLATE_NAME)
    ev.save_on(db, T, True)
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(return_value=OK)) as send:
        assert ev.send_evening_summaries(db, NOW) == 1
        assert ev.send_evening_summaries(db, NOW) == 0                    # a retry the same day sends nothing
        assert ev.send_evening_summaries(db, NOW + timedelta(days=1)) == 1
    first = send.call_args_list[0]
    assert first.args[0] == "+919876543210" and first.args[1] == ev.TEMPLATE_NAME
    assert first.kwargs["skip_blocked_check"] is True and first.kwargs["tenant_id"] == T
    params = [p["text"] for p in first.kwargs["components"][0]["parameters"]]
    assert params[0] == "Sri Stores" and len(params) == 5


def test_failed_send_is_not_recorded_so_it_can_retry():
    db = _base()
    _tpl(db, ev.TEMPLATE_NAME)
    ev.save_on(db, T, True)
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(side_effect=RuntimeError("no"))):
        assert ev.send_evening_summaries(db, NOW) == 0
    assert "last_sent_on" not in json.loads(db.rows("app_settings")[0]["value"])


def test_no_owner_number_means_no_send():
    db = FakeSupabase()
    db.add("tenants", id=T, name="Sri Stores", contact_phone=None)
    _tpl(db, ev.TEMPLATE_NAME)
    ev.save_on(db, T, True)
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(return_value=OK)) as send:
        assert ev.send_evening_summaries(db, NOW) == 0
        send.assert_not_called()


# ───────────────────────────────────────────────────────────── come-back offer

def _customer(db, lid, *, bought_days_ago=90, **lead):
    lead.setdefault("opt_in_source", "whatsapp_chat")
    db.add("leads", id=lid, tenant_id=T, name=f"Priya {lid}", phone=f"+91900000000{lid[-1]}", **lead)
    if bought_days_ago is not None:
        db.add("deals", tenant_id=T, lead_id=lid, stage="won",
               won_at=(DAYTIME - timedelta(days=bought_days_ago)).isoformat())


def _ready() -> FakeSupabase:
    db = _base()
    _tpl(db, "comeback_hello")
    co.save_settings(db, T, on=True, template_name="comeback_hello", offer="10% off", code="BACK10",
                     ends_on="2026-12-31", now=DAYTIME)
    return db


def test_off_by_default_and_cost_note():
    s = co.get_settings(_base(), T)
    assert s["on"] is False and "0.86" in s["cost_note"]


def test_cannot_turn_on_without_an_approved_template_or_offer():
    db = _base()
    for kw in (dict(template_name=None), dict(template_name="nope"), dict(template_name="p", offer="")):
        _tpl(db, "p", status="PENDING")
        args = dict(on=True, template_name="p", offer="10% off", code="", ends_on=None, now=DAYTIME)
        args.update(kw)
        try:
            co.save_settings(db, T, **args)
        except ValueError as e:
            assert str(e)
        else:
            raise AssertionError(kw)
    _tpl(db, "good")
    for bad in (dict(code="bad code!"), dict(ends_on="2026-01-01"), dict(ends_on="not a date"), dict(offer="x" * 201)):
        args = dict(on=True, template_name="good", offer="10% off", code="", ends_on=None, now=DAYTIME)
        args.update(bad)
        try:
            co.save_settings(db, T, **args)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert co.save_settings(db, T, on=False, template_name=None, offer="", code="", ends_on=None)["on"] is False


def test_who_gets_an_offer():
    db = _ready()
    _customer(db, "l1", bought_days_ago=90)                    # yes
    _customer(db, "l2", bought_days_ago=30)                    # bought recently
    _customer(db, "l3", bought_days_ago=None)                  # never bought
    _customer(db, "l4", opted_out=True)                        # Said stop
    _customer(db, "l5", blocked_at="2026-01-01T00:00:00+00:00")
    _customer(db, "l6", do_not_call=True)
    _customer(db, "l7")                                        # unhappy
    db.add("customer_feedback", tenant_id=T, lead_id="l7", stars=2)
    _customer(db, "l8")                                        # got one 10 days ago
    db.add("comeback_offer_sends", tenant_id=T, lead_id="l8", status="sent", created_at=(DAYTIME - timedelta(days=10)).isoformat())
    _customer(db, "l9")                                        # got one 45 days ago: eligible again
    db.add("comeback_offer_sends", tenant_id=T, lead_id="l9", status="sent", created_at=(DAYTIME - timedelta(days=45)).isoformat())
    _customer(db, "la")                                        # bought long ago AND again 20 days ago
    db.add("deals", tenant_id=T, lead_id="la", stage="won", won_at=(DAYTIME - timedelta(days=20)).isoformat())
    db.add("leads", id="lb", tenant_id="t2", name="Other", phone="+919111111111")      # another business
    db.add("deals", tenant_id="t2", lead_id="lb", stage="won", won_at=(DAYTIME - timedelta(days=90)).isoformat())
    assert {l["id"] for l in co.find_candidates(db, T, DAYTIME)} == {"l1", "l9"}


def test_failed_attempt_blocks_a_week_not_the_month():
    db = _ready()
    _customer(db, "l1")
    _customer(db, "l2")
    db.add("comeback_offer_sends", tenant_id=T, lead_id="l1", status="failed", created_at=(DAYTIME - timedelta(days=1)).isoformat())
    db.add("comeback_offer_sends", tenant_id=T, lead_id="l2", status="failed", created_at=(DAYTIME - timedelta(days=8)).isoformat())
    assert [l["id"] for l in co.find_candidates(db, T, DAYTIME)] == ["l2"]


def test_bad_numbers_do_not_starve_everyone_else():
    db = _ready()
    for i in range(3):
        _customer(db, f"b{i}", bought_days_ago=300)             # oldest purchases, numbers Meta rejects
    _customer(db, "g1", bought_days_ago=70)
    with _waba(), patch.object(co, "MAX_PER_BUSINESS_PER_RUN", 3), \
            patch("app.services.meta_cloud.send_template_message", new=AsyncMock(side_effect=RuntimeError("bad number"))):
        assert co.send_comeback_offers(db, DAYTIME) == 0
    ok = AsyncMock(return_value=OK)
    with _waba(), patch.object(co, "MAX_PER_BUSINESS_PER_RUN", 3), patch("app.services.meta_cloud.send_template_message", new=ok):
        assert co.send_comeback_offers(db, DAYTIME + timedelta(days=1)) == 1     # the good lead, not the 3 bad ones again
    assert [r["lead_id"] for r in db.rows("comeback_offer_sends") if r["status"] == "sent"] == ["g1"]


def test_timeout_after_send_keeps_the_claim_so_no_double_send():
    import httpx
    db = _ready()
    _customer(db, "l1")
    with _waba(), patch("app.services.meta_cloud.send_template_message",
                        new=AsyncMock(side_effect=httpx.ReadTimeout("slow"))):
        assert co.send_comeback_offers(db, DAYTIME) == 0
    assert db.rows("comeback_offer_sends")[0]["status"] == "sending"           # unknown outcome: stays "recent"
    assert co.find_candidates(db, T, DAYTIME + timedelta(days=20)) == []
    assert co.find_candidates(db, T, DAYTIME + timedelta(days=31))[0]["id"] == "l1"


def test_leads_without_an_opt_in_source_are_skipped():
    db = _ready()
    _customer(db, "l1")
    _customer(db, "l2", opt_in_source=None)
    _customer(db, "l3", opt_in_source="  ")
    assert [l["id"] for l in co.find_candidates(db, T, DAYTIME)] == ["l1"]


class _Cap1000:
    """Like PostgREST: no request returns more than 1000 rows, whatever .limit() says."""
    def __enter__(self):
        from fake_supabase import _Query
        self.q, self.orig = _Query, _Query.execute

        def capped(query):
            res = self.orig(query)
            if isinstance(res.data, list):
                res.data = res.data[:1000]
            return res
        _Query.execute = capped
        return self

    def __exit__(self, *a):
        self.q.execute = self.orig


def test_comeback_sees_the_latest_purchase_past_1000_rows():
    db = _ready()
    _customer(db, "l1", bought_days_ago=90)
    for i in range(1005):                                      # 1005 other won deals (other leads) sit between
        db.add("deals", tenant_id=T, lead_id=f"x{i}", stage="won", won_at=(DAYTIME - timedelta(days=5)).isoformat())
    db.add("deals", tenant_id=T, lead_id="l1", stage="won", won_at=(DAYTIME - timedelta(days=10)).isoformat())
    with _Cap1000():
        assert co.find_candidates(db, T, DAYTIME) == []        # l1 bought 10 days ago: no offer


def test_comeback_sees_every_recent_send_past_1000_rows():
    db = _ready()
    _customer(db, "l1")
    for i in range(1005):
        db.add("comeback_offer_sends", tenant_id=T, lead_id=f"x{i}", status="sent", created_at=(DAYTIME - timedelta(days=3)).isoformat())
    db.add("comeback_offer_sends", tenant_id=T, lead_id="l1", status="sent", created_at=(DAYTIME - timedelta(days=3)).isoformat())
    with _Cap1000():
        assert co.find_candidates(db, T, DAYTIME) == []


def test_evening_summary_counts_past_1000_rows():
    db = _base()
    today = "2026-11-23T05:00:00+00:00"
    for i in range(1005):
        db.add("messages", tenant_id=T, lead_id=f"c{i}", direction="inbound", created_at=today)
        db.add("leads", tenant_id=T, created_at=today)
        db.add("deals", tenant_id=T, stage="won", won_at=today)
        db.add("deal_payments", tenant_id=T, amount_paise=100, paid_at=today)
    with _Cap1000():
        assert ev.build_summary(db, T, NOW) == {"chats": 1005, "new_leads": 1005, "orders": 1005, "money_paise": 100_500}


def test_evening_money_is_net_of_refunds():
    db = _base()
    today, yday = "2026-11-23T05:00:00+00:00", "2026-11-22T05:00:00+00:00"
    db.add("deal_payments", tenant_id=T, amount_paise=500_00, paid_at=today)
    db.add("deal_refunds", tenant_id=T, amount_paise=120_00, status="done", created_at=today)
    db.add("deal_refunds", tenant_id=T, amount_paise=50_00, status="failed", created_at=today)     # never paid out
    db.add("deal_refunds", tenant_id=T, amount_paise=70_00, status="done", created_at=yday)        # another day
    db.add("deal_refunds", tenant_id="t2", amount_paise=99_00, status="done", created_at=today)    # another business
    assert ev.build_summary(db, T, NOW)["money_paise"] == 380_00
    db.add("deal_refunds", tenant_id=T, amount_paise=380_00, status="done", created_at=today)
    assert ev.build_summary(db, T, NOW)["money_paise"] == 0     # fully refunded day reads "No payments today."


def test_sends_logs_and_never_twice_in_30_days():
    db = _ready()
    _customer(db, "l1")
    _customer(db, "l2", bought_days_ago=120)
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(return_value=OK)) as send:
        assert co.send_comeback_offers(db, DAYTIME) == 2
        assert co.send_comeback_offers(db, DAYTIME + timedelta(hours=1)) == 0
        assert co.send_comeback_offers(db, DAYTIME + timedelta(days=29)) == 0
        assert send.call_count == 2
    assert {r["status"] for r in db.rows("comeback_offer_sends")} == {"sent"}
    first = send.call_args_list[0]
    texts = [p["text"] for p in first.kwargs["components"][0]["parameters"]]
    assert texts[1:4] == ["10% off", "BACK10", "2026-12-31"] and first.kwargs["tenant_id"] == T
    assert len(db.rows("messages")) == 2                       # the chat shows what went out


def test_failed_send_is_logged_as_failed():
    db = _ready()
    _customer(db, "l1")
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(side_effect=RuntimeError("blocked"))):
        assert co.send_comeback_offers(db, DAYTIME) == 0
    row = db.rows("comeback_offer_sends")[0]
    assert row["status"] == "failed" and "blocked" in row["error"]


def test_nothing_goes_out_off_hours_when_off_unapproved_or_ended():
    db = _ready()
    _customer(db, "l1")
    with _waba(), patch("app.services.meta_cloud.send_template_message", new=AsyncMock(return_value=OK)) as send:
        assert co.send_comeback_offers(db, datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)) == 0     # 10:30 PM IST
        assert co.send_comeback_offers(db, datetime(2027, 1, 5, 6, 0, tzinfo=timezone.utc)) == 0        # after the end date
        db.rows("message_templates")[0]["status"] = "PAUSED"
        assert co.send_comeback_offers(db, DAYTIME) == 0
        db.rows("message_templates")[0]["status"] = "APPROVED"
        co.set_on(db, T, False)
        assert co.send_comeback_offers(db, DAYTIME) == 0
        send.assert_not_called()


def test_cap_per_run():
    db = _ready()
    for i in range(5):
        _customer(db, f"m{i}")
    with _waba(), patch.object(co, "MAX_PER_BUSINESS_PER_RUN", 3), \
            patch("app.services.meta_cloud.send_template_message", new=AsyncMock(return_value=OK)):
        assert co.send_comeback_offers(db, DAYTIME) == 3
