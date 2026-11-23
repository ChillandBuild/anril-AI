"""Reports: Overview, Campaigns, the people behind a number, the CSV file, the monthly bells."""
import csv
import io
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from reports_seed import PERIOD, T1, T2, MissingTables, at, seed, seed_money
from fake_supabase import FakeSupabase
from app.services import reports_campaigns, reports_csv, reports_monthly, reports_overview, reports_people
from app.services.reports_common import Flags

ALL, ORDERS_ONLY, NONE = Flags(True, True), Flags(True, False), Flags(False, False)
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_held(monkeypatch):
    monkeypatch.setattr("app.services.deals_reports.held_quantities", lambda *a, **k: {})


@pytest.fixture
def db():
    d = seed_money(seed(FakeSupabase()))
    d.add("call_logs", tenant_id=T1, lead_id="L1", caller_id="c1", manual_status="connected", created_at="2026-10-16T01:00:00+00:00")
    d.add("customer_feedback", tenant_id=T1, lead_id="L2", phone="919000000002", stars=2, status="answered", reason="Late", answered_at=at(13))
    return d


# ── Overview ────────────────────────────────────────────────────────────────

def test_overview_numbers(db):
    numbers, _ = reports_overview.compute(db, T1, PERIOD, ALL)
    assert numbers["first_chats"] == 4 and numbers["hot"] == 2 and numbers["paid"] == 2 and numbers["orders"] == 2
    assert numbers["sales_paise"] == 150_000 and numbers["new_buyers"] == 1
    assert numbers["ad_spend_paise"] == 750_000 and numbers["cost_per_chat_paise"] == 375_000


def test_overview_cards_follow_what_the_business_uses():
    numbers = {"first_chats": 4, "hot": 2, "paid": 2, "sales_paise": 150_000, "new_buyers": 1, "calls": 3, "cost_per_chat_paise": 10, "bookings": 2}
    before = {"first_chats": 1}
    everything = {"orders": True, "calls": True, "ads": True, "bookings": True}
    cards = reports_overview.build_cards(numbers, before, everything, ALL)
    assert len(cards) == 6 and cards[0]["key"] == "sales_paise" and cards[0]["kind"] == "paise"
    chats = next(c for c in cards if c["key"] == "first_chats")
    assert chats["value"] == 4 and chats["before"] == 1 and chats["people"] == {"metric": "new_chats"}
    plain = reports_overview.build_cards(numbers, None, {"orders": False, "calls": False, "ads": False, "bookings": False}, ALL)
    assert [c["key"] for c in plain] == ["first_chats", "hot", "new_buyers"] and "before" not in plain[0]
    no_money = reports_overview.build_cards(numbers, None, everything, NONE)
    assert all(c["kind"] != "paise" for c in no_money)


def test_hot_not_called_in_24_hours(db):
    assert reports_overview.hot_not_called(db, T1, NOW) == 1  # L1 was called this morning, L3 was not


def test_waiting_for_payment_and_unhappy_and_unmarked(db):
    assert reports_overview.waiting_for_payment(db, T1) == (1, 20_000)
    assert reports_overview.unhappy_open(db, T1) == 1
    # L1 and L5-type buyers are marked; L2, L3, L4 have no result yet
    assert sorted(reports_overview.unmarked_lead_ids(db, T1, PERIOD)) == ["L2", "L3", "L4"]


def test_todo_picks_the_three_biggest_and_skips_zeros(db):
    items = reports_overview.todo_items(db, T1, ALL, NOW)
    assert len(items) == 3 and items[0] == {"text": "2 items running low", "count": 2, "href": "/dashboard/catalog"}
    assert {i["href"] for i in items} <= {"/dashboard/telecalling", "/dashboard/deals", "/dashboard/catalog", "/dashboard/leads?tab=feedback"}
    waiting = next(i for i in items if i["href"] == "/dashboard/deals")
    assert waiting["text"] == "1 order waiting for payment, ₹200 to collect"
    assert "₹" not in reports_overview.todo_items(db, T1, NONE, NOW)[1]["text"] + reports_overview.todo_items(db, T1, NONE, NOW)[2]["text"]
    assert reports_overview.todo_items(FakeSupabase(), T1, ALL, NOW) == []


def test_overview_report_shape(db):
    out = reports_overview.report(db, T1, PERIOD, True, ALL, now=NOW)
    assert set(out) >= {"period", "before", "in_short", "todo", "cards", "target", "unmarked_chats"}
    assert out["unmarked_chats"] == {"count": 3, "href": "/dashboard/inbound-leads?result=none"}
    assert set(out["target"]) == {"this_month", "cost_coverage"} and out["before"]["first_chats"] == 1
    assert out["in_short"] == "4 new chats, up 3 from before; 2 people paid, ₹1,500."


def test_overview_report_hides_money_but_keeps_the_rest(db):
    out = reports_overview.report(db, T1, PERIOD, True, NONE, now=NOW)
    assert out["money_hidden"] is True and "sales_paise" not in out["period"] and "ad_spend_paise" not in out["period"]
    assert "target_paise" not in out["target"]["this_month"] and out["period"]["first_chats"] == 4
    assert "₹" not in json.dumps(out["todo"]) and "₹" not in out["in_short"]


def test_overview_survives_missing_tables():
    db = seed(MissingTables("call_logs", "customer_feedback", "bookings"))
    out = reports_overview.report(db, T1, PERIOD, False, ALL, now=NOW)
    assert out["period"]["first_chats"] == 4 and "calls" not in out["period"] and out["before"] is None


# ── Campaigns ───────────────────────────────────────────────────────────────

def seed_campaign(db):
    hist = [{"broadcast_id": "b1", "timestamp": at(12), "template_name": "Diwali offer", "sent": 3, "delivered": 3, "opened": 2},
            {"broadcast_id": "b0", "timestamp": at(2), "template_name": "Old one", "sent": 9}]
    db.add("app_settings", tenant_id=T1, key="broadcast_history", value=json.dumps(hist))
    db.add("app_settings", tenant_id=T2, key="broadcast_history", value=json.dumps([{"broadcast_id": "bx", "timestamp": at(12), "sent": 99}]))
    for lead, sentiment, opted in (("L1", "positive", None), ("L2", "negative", at(13)), ("L5", None, None)):
        db.add("broadcast_recipients", tenant_id=T1, broadcast_id="b1", lead_id=lead, send_status="sent", created_at=at(12),
               reply_sentiment=sentiment, opted_out_at=opted, phone="91900000000")
    return db


def test_read_history_and_campaigns_in_the_days():
    db = seed_campaign(FakeSupabase())
    history = reports_campaigns.read_history(db, T1)
    assert [h["broadcast_id"] for h in history] == ["b1", "b0"]
    assert [h["broadcast_id"] for h in reports_campaigns.campaigns_in(history, PERIOD)] == ["b1"]
    assert reports_campaigns.read_history(FakeSupabase(), T1) == []
    bad = FakeSupabase()
    bad.add("app_settings", tenant_id=T1, key="broadcast_history", value="not json")
    assert reports_campaigns.read_history(bad, T1) == []


def test_recipient_counts_replied_and_said_stop():
    assert reports_campaigns.recipient_counts(seed_campaign(FakeSupabase()), T1, ["b1"]) == {"b1": {"replied": 2, "said_stop": 1}}


def test_campaign_report_with_paid_within_7_days(db):
    seed_campaign(db)
    numbers, extras = reports_campaigns.compute(db, T1, PERIOD, ALL)
    row = extras["rows"][0]
    assert (row["id"], row["name"], row["sent"], row["delivered"], row["read"]) == ("b1", "Diwali offer", 3, 3, 2)
    assert (row["replied"], row["said_stop"]) == (2, 1)
    assert row["paid"] == 2 and row["paid_paise"] == 168_000  # Asha paid the day of the send, Esha 2 days after
    assert numbers["campaigns"] == 1 and numbers["sent"] == 3 and numbers["paid"] == 2


def test_campaign_paid_people_and_hidden_rupees(db):
    seed_campaign(db)
    assert sorted(reports_campaigns.paid_lead_ids(db, T1, "b1")) == ["L1", "L5"]
    assert reports_campaigns.paid_lead_ids(db, T1, "nope") == []
    _, extras = reports_campaigns.compute(db, T1, PERIOD, NONE)
    assert extras["rows"][0]["paid_paise"] is None


def test_campaigns_in_short():
    assert reports_campaigns.in_short({"campaigns": 0}, None) == "No campaigns were sent in these days."
    assert reports_campaigns.in_short({"campaigns": 2, "sent": 10, "replied": 3, "paid": 1}, None) == \
        "2 campaigns sent to 10 people; 3 replied; 1 paid within 7 days."


def test_campaigns_with_no_history_is_empty_not_error():
    numbers, extras = reports_campaigns.compute(FakeSupabase(), T1, PERIOD, ALL)
    assert numbers["campaigns"] == 0 and extras["rows"] == []


# ── People ──────────────────────────────────────────────────────────────────

def names(rows):
    return sorted(r["name"] for r in rows)


def test_people_new_chats_hot_and_unmarked(db):
    p = lambda metric, **kw: reports_people.people(db, T1, metric, PERIOD, **kw)
    assert names(p("new_chats")) == ["Asha", "Bala", "Chitra", "Dev"]
    assert names(p("hot")) == ["Asha", "Chitra"]
    assert names(p("unmarked_chats")) == ["Bala", "Chitra", "Dev"]
    assert set(p("hot")[0]) == {"lead_id", "name", "phone", "detail"}


def test_people_buyers(db):
    p = lambda metric, **kw: reports_people.people(db, T1, metric, PERIOD, **kw)
    assert names(p("paid")) == ["Asha", "Esha"] and names(p("repeat")) == ["Esha"] and names(p("bought_new")) == ["Asha"]
    assert names(p("funnel_paid")) == ["Asha"]
    assert p("paid")[0]["detail"] == "Paid 1,180 rupees"
    assert p("paid", sees_money=False)[0]["detail"] == "Paid"


def test_people_came_from_and_ad_chats(db):
    assert names(reports_people.people(db, T1, "came_from", PERIOD, item_id="qr")) == ["Chitra"]
    assert names(reports_people.people(db, T1, "ad_chats", PERIOD, item_id="camp-m")) == ["Asha"]


def test_people_feedback_and_campaign_lists(db):
    seed_campaign(db)
    assert names(reports_people.people(db, T1, "feedback_unhappy", PERIOD)) == ["Bala"]
    assert reports_people.people(db, T1, "feedback_unhappy", PERIOD)[0]["detail"] == "2 stars: Late"
    assert names(reports_people.people(db, T1, "campaign_replied", PERIOD, item_id="b1")) == ["Asha", "Bala"]
    assert "Esha" in names(reports_people.people(db, T1, "campaign_paid", PERIOD, item_id="b1"))


def test_people_never_show_another_shop(db):
    for metric in ("new_chats", "hot", "unmarked_chats", "paid"):
        assert "Other shop" not in names(reports_people.people(db, T1, metric, PERIOD))
    assert names(reports_people.people(db, T2, "new_chats", PERIOD)) == ["Other shop"]


def test_people_bad_requests_are_plain_400s(db):
    for metric, item in (("nonsense", None), ("campaign_replied", None), ("ad_chats", None)):
        with pytest.raises(HTTPException) as e:
            reports_people.people(db, T1, metric, PERIOD, item_id=item)
        assert e.value.status_code == 400 and e.value.detail


def test_people_stops_at_500():
    db = FakeSupabase()
    for i in range(520):
        db.add("leads", id=f"n{i}", tenant_id=T1, source="whatsapp", created_at=at(11), segment="C", name=f"P{i}")
    assert len(reports_people.people(db, T1, "new_chats", PERIOD)) == 500
    assert len(reports_people._capped([{}] * 9)) == 9


def test_people_row_and_lookup_helpers(db):
    assert reports_people._row({"id": "L1", "name": "A", "phone": "1"}, "x") == {"lead_id": "L1", "name": "A", "phone": "1", "detail": "x"}
    assert set(reports_people._leads_by_id(db, T1, ["L1", "L2", "X1"])) == {"L1", "L2"}  # X1 is another shop's
    assert "unmarked_chats" in reports_people.METRICS


# ── CSV ─────────────────────────────────────────────────────────────────────

def rows_of(text):
    return list(csv.reader(io.StringIO(text)))


def test_csv_has_numbers_before_and_tables():
    report = {"in_short": "=SUM(1)", "period": {"sales_paise": 150_000, "orders": 2, "gone": None},
              "before": {"sales_paise": 20_000, "orders": 1},
              "rows": [{"id": "a", "name": "=cmd", "spend_paise": 50_000, "people": {"metric": "x"}, "href": "/x"}]}
    rows = rows_of(reports_csv.to_csv("ads", report))
    assert rows[0] == ["In short", "'=SUM(1)"]
    assert ["Number", "These days", "Days before"] in rows
    assert ["Sales (rupees)", "1500.0", "200.0"] in rows and ["Orders", "2", "1"] in rows
    assert rows[rows.index(["Rows"]) + 1] == ["Id", "Name", "Spend (rupees)"]
    assert rows[rows.index(["Rows"]) + 2] == ["a", "'=cmd", "500.0"]


def test_csv_without_before_and_label_helpers():
    rows = rows_of(reports_csv.to_csv("team", {"in_short": "x", "period": {"orders": 1}, "before": None}))
    assert ["Number", "These days"] in rows
    assert reports_csv.label("ai_reply_p50_seconds") == "Ai reply p50 (seconds)" and reports_csv._cell("k_paise", 250) == 2.5
    assert reports_csv._cell("k", None) == "" and reports_csv._cell("k", {"a": 1}) == ""


# ── Monthly bells ───────────────────────────────────────────────────────────

def bell_db():
    db = seed(FakeSupabase())
    db.add("tenants", id=T1, name="One")
    db.add("tenants", id=T2, name="Two")
    db.add("tenant_users", tenant_id=T1, user_id="owner1", role="owner")
    db.add("tenant_users", tenant_id=T1, user_id="staff1", role="staff")
    return db


@pytest.fixture
def bells(monkeypatch):
    rung = []
    monkeypatch.setattr("app.services.notify.notify_user",
                        lambda tenant, user, type, title, message, **kw: rung.append((tenant, user, title, message, kw.get("push_url"))))
    return rung


def _use(monkeypatch, db):
    monkeypatch.setattr(reports_monthly, "get_supabase", lambda: db)


def test_monthly_bell_goes_to_owners_once_a_month(monkeypatch, bells):
    db = bell_db()
    db.rows("deals")[:] = [d for d in db.rows("deals") if d.get("tenant_id") != T2]
    _use(monkeypatch, db)
    first = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
    assert reports_monthly.send_monthly_report_bells(first) == 1
    assert len(bells) == 1 and bells[0][1] == "owner1" and bells[0][2] == "Your report for October"
    assert "₹1,700 sales, 5 new customers" in bells[0][3] and bells[0][4] == "/dashboard/analytics?tab=overview&month=2026-10"
    assert reports_monthly.send_monthly_report_bells(first) == 0  # same month again: nothing
    assert reports_monthly.send_monthly_report_bells(datetime(2026, 11, 2, 4, 0, tzinfo=timezone.utc)) == 0
    assert len(bells) == 1


def test_monthly_bell_only_in_the_first_days_and_skips_quiet_shops(monkeypatch, bells):
    db = bell_db()
    _use(monkeypatch, db)
    assert reports_monthly.send_monthly_report_bells(datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)) == 0
    assert reports_monthly.send_monthly_report_bells(datetime(2026, 12, 1, 4, 0, tzinfo=timezone.utc)) == 0  # November was empty
    assert bells == []


def test_accountant_bell_on_the_fifth_once(monkeypatch, bells):
    db = bell_db()
    _use(monkeypatch, db)
    assert reports_monthly.send_accountant_file_bells(datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc)) == 0
    assert reports_monthly.send_accountant_file_bells(datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)) == 1
    assert bells[0][3] == "Last month's accountant file is ready." and bells[0][4].startswith("/dashboard/analytics?tab=money&accountant=1")
    assert reports_monthly.send_accountant_file_bells(datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)) == 0
    assert reports_monthly.send_accountant_file_bells(datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)) == 0


def test_bells_never_raise(monkeypatch):
    class Broken:
        def table(self, name):
            raise RuntimeError("database down")
    monkeypatch.setattr(reports_monthly, "get_supabase", lambda: Broken())
    assert reports_monthly.send_monthly_report_bells(datetime(2026, 11, 1, tzinfo=timezone.utc)) == 0
    assert reports_monthly.send_accountant_file_bells(datetime(2026, 11, 5, tzinfo=timezone.utc)) == 0


def test_monthly_helpers():
    db = bell_db()
    today, month, period, days = reports_monthly._last_month(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
    assert month == "2025-12" and days == 31 and period.start.isoformat() == "2025-12-01"
    assert reports_monthly._owners(db, T1) == ["owner1"] and set(reports_monthly._tenant_ids(db)) == {T1, T2}
    assert reports_monthly._claim(db, T1, "k", "2026-10") is True and reports_monthly._claim(db, T1, "k", "2026-10") is False
    assert reports_monthly._claim(db, T1, "k", "2026-11") is True
