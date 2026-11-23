"""v9.2 #29: refund done, stock running low, hot customer waiting. Each rings through notify_user, once where it says once."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase  # noqa: E402

from app.services import alert_events  # noqa: E402

T = "t1"
NOW = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


def _team() -> FakeSupabase:
    db = FakeSupabase()
    db.add("tenant_roles", id="r-money", tenant_id=T, permissions=["deals.view"])
    db.add("tenant_roles", id="r-plain", tenant_id=T, permissions=["leads.view"])
    db.add("tenant_users", tenant_id=T, user_id="owner", role="owner", role_id=None)
    db.add("tenant_users", tenant_id=T, user_id="admin", role="admin", role_id="r-plain")
    db.add("tenant_users", tenant_id=T, user_id="accounts", role="staff", role_id="r-money")
    db.add("tenant_users", tenant_id=T, user_id="sales", role="staff", role_id="r-plain")
    db.add("tenant_users", tenant_id="t2", user_id="stranger", role="owner", role_id=None)
    return db


def _told(bell) -> set[str]:
    return {c.args[1] for c in bell.call_args_list}


def test_refund_goes_only_to_money_viewers_not_the_giver():
    db = _team()
    with patch("app.services.notify.notify_user") as bell:
        n = alert_events.refund_done(db, T, deal_id="d1", deal_label="order D-1", amount_paise=250000,
                                     method="cash", reason="wrong size", by_user_id="owner")
    assert _told(bell) == {"accounts"} and n == 1
    assert bell.call_args.args[2] == "refund_done"
    assert "2,500" in bell.call_args.args[4] or "2500" in bell.call_args.args[4]


def test_stock_low_rings_owner_and_admins_once_a_day():
    db = _team()
    with patch("app.services.notify.notify_user") as bell:
        first = alert_events.stock_low(db, T, subject_id="item1", name="Cotton saree", quantity_after=2, now=NOW)
        again = alert_events.stock_low(db, T, subject_id="item1", name="Cotton saree", quantity_after=1, now=NOW)
        other = alert_events.stock_low(db, T, subject_id="item2", name="Silk saree", quantity_after=0, now=NOW)
        next_day = alert_events.stock_low(db, T, subject_id="item1", name="Cotton saree", quantity_after=1,
                                          now=NOW + timedelta(days=1))
    assert (first, again, other, next_day) == (2, 0, 2, 2)
    assert _told(bell) == {"owner", "admin"}


def test_stock_at_three_or_more_rings_nothing():
    db = _team()
    with patch("app.services.notify.notify_user") as bell:
        assert alert_events.stock_low(db, T, subject_id="i", name="X", quantity_after=3, now=NOW) == 0
    assert not bell.called


def test_stock_moved_ignores_adds_and_names_the_size():
    db = _team()
    db.add("catalog_items", id="i1", tenant_id=T, name="Kurta")
    db.add("catalog_item_variants", id="v1", tenant_id=T, catalog_item_id="i1", size="M", colour="Red")
    with patch("app.services.notify.notify_user") as bell:
        alert_events.stock_moved(db, T, item_id="i1", variant_id="v1", delta=5, quantity_after=2)
        assert not bell.called
        alert_events.stock_moved(db, T, item_id="i1", variant_id="v1", delta=-1, quantity_after=2)
    assert "Kurta (M · Red)" in bell.call_args.args[3]


def test_no_alert_when_the_once_a_day_table_cannot_be_written():
    db = _team()
    with patch("app.services.notify.notify_user") as bell, \
         patch.object(alert_events, "claim_once", wraps=alert_events.claim_once), \
         patch.object(db, "table", side_effect=RuntimeError("alert_fired missing")):
        assert alert_events.claim_once(db, T, "stock_low", "x", NOW) is False
    assert not bell.called


def _hot_db() -> FakeSupabase:
    db = _team()
    db.add("callers", id="c1", tenant_id=T, user_id="sales")
    since = (NOW - timedelta(minutes=45)).isoformat()
    db.add("leads", id="L1", tenant_id=T, name="Priya", segment="A", assigned_to="c1", last_inbound_at=since,
           deleted_at=None, converted_at=None, lost_at=None)
    return db


def test_hot_lead_waiting_rings_owner_and_assigned_person_once_per_day():
    db = _hot_db()
    since = NOW - timedelta(minutes=45)
    rows = [{"lead_id": "L1", "waiting_since": since.isoformat()}]
    with patch("app.services.home_today._needs_you_rows", return_value=rows), \
         patch("app.services.notify.notify_user") as bell:
        first = alert_events.sweep_hot_leads(db, NOW)
        second = alert_events.sweep_hot_leads(db, NOW)
    assert first == 2 and second == 0
    assert _told(bell) == {"owner", "sales"}
    assert bell.call_args.args[2] == "hot_lead_waiting"


def test_hot_lead_answered_or_too_fresh_is_quiet():
    db = _hot_db()
    with patch("app.services.home_today._needs_you_rows", return_value=[]), \
         patch("app.services.notify.notify_user") as bell:
        assert alert_events.sweep_hot_leads(db, NOW) == 0                      # no longer on "Needs you"
    fresh = [{"lead_id": "L1", "waiting_since": (NOW - timedelta(minutes=10)).isoformat()}]
    with patch("app.services.home_today._needs_you_rows", return_value=fresh), \
         patch("app.services.notify.notify_user") as bell2:
        assert alert_events.sweep_hot_leads(db, NOW) == 0
    assert not bell.called and not bell2.called


def test_already_rung_lead_costs_no_inbox_lookup_and_one_bad_lead_does_not_stop_the_rest():
    db = _hot_db()
    since = (NOW - timedelta(minutes=45)).isoformat()
    db.add("leads", id="L2", tenant_id=T, name="Ravi", segment="A", assigned_to=None, last_inbound_at=since,
           deleted_at=None, converted_at=None, lost_at=None)
    waiting = [{"lead_id": "L1", "waiting_since": since}, {"lead_id": "L2", "waiting_since": since}]
    with patch("app.services.home_today._needs_you_rows", return_value=waiting), \
         patch("app.services.notify.notify_user"):
        assert alert_events.sweep_hot_leads(db, NOW) == 3        # L1: owner + sales, L2: owner
    # Both rung today: the next sweep must not even ask the inbox.
    with patch("app.services.home_today._needs_you_rows", side_effect=AssertionError("inbox asked")) as inbox, \
         patch("app.services.notify.notify_user") as bell:
        assert alert_events.sweep_hot_leads(db, NOW) == 0
    assert not inbox.called and not bell.called
    # Forget today's rings; the first bell failing must not stop the rest.
    db.tables["alert_fired"].clear()
    calls = []

    def flaky(tenant_id, uid, *a, **k):
        calls.append(uid)
        if len(calls) == 1:
            raise RuntimeError("push down")
    with patch("app.services.home_today._needs_you_rows", return_value=waiting), \
         patch("app.services.notify.notify_user", side_effect=flaky):
        alert_events.sweep_hot_leads(db, NOW)
    assert len(calls) >= 2
