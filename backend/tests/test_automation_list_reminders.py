"""v9.2 #53: the Automations list also shows balance, course-fee and booking reminders and back-in-stock (only real ones)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase  # noqa: E402

from app.services import automation_list, template_pauses  # noqa: E402

T = "t1"


def _by_key(db) -> dict:
    return {a["key"]: a for a in automation_list.list_automations(db, T)}


def test_empty_business_lists_none_of_the_four():
    items = _by_key(FakeSupabase())
    assert not {"balance_reminders", "fee_reminders", "booking_reminders", "back_in_stock"} & set(items)


def test_balance_reminders_listed_once_there_are_orders_and_follow_the_switch():
    db = FakeSupabase()
    db.add("deals", id="d1", tenant_id=T)
    row = _by_key(db)["balance_reminders"]
    assert row["on"] is True and row["switchable"] is False and row["href"] == "/dashboard/settings/payments"
    assert row["template_name"] == "anril_payment_reminder"
    db.add("app_settings", tenant_id=T, key="balance_reminders", value="off")
    off = _by_key(db)["balance_reminders"]
    assert off["on"] is False and off["template_name"] is None


def test_booking_reminders_on_only_when_template_approved():
    db = FakeSupabase()
    db.add("booking_settings", tenant_id=T)
    assert _by_key(db)["booking_reminders"]["on"] is False
    db.add("message_templates", id="m1", tenant_id=T, name="anril_booking_reminder", status="APPROVED")
    row = _by_key(db)["booking_reminders"]
    assert row["on"] is True and row["href"] == "/dashboard/bookings" and row["template_status"] == "APPROVED"


def test_back_in_stock_listed_with_waitlist_or_template():
    db = FakeSupabase()
    db.add("stock_waitlist", id="w1", tenant_id=T)
    assert _by_key(db)["back_in_stock"]["on"] is False
    db.add("message_templates", id="m2", tenant_id=T, name="anril_back_in_stock", status="APPROVED")
    assert _by_key(db)["back_in_stock"]["on"] is True


def test_other_business_rows_do_not_leak():
    db = FakeSupabase()
    db.add("booking_settings", tenant_id="t2")
    db.add("stock_waitlist", id="w9", tenant_id="t2")
    items = _by_key(db)
    assert "booking_reminders" not in items and "back_in_stock" not in items


def test_new_rows_cannot_be_switched_here():
    for key in automation_list.OWN_PAGE_KEYS:
        try:
            automation_list.set_automation_on(FakeSupabase(), T, key, True)
        except automation_list.NotSwitchable:
            continue
        raise AssertionError(key)


def test_turned_down_booking_template_pauses_the_row_and_tells_the_owner():
    db = FakeSupabase()
    db.add("booking_settings", tenant_id=T)
    db.add("message_templates", id="m1", tenant_id=T, name="anril_booking_reminder", status="APPROVED")
    db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
    with patch("app.services.notify.notify_user") as bell:
        n = template_pauses.on_template_status_change(db, T, "anril_booking_reminder", "REJECTED")
    assert n == 1 and bell.called
    assert _by_key(db)["booking_reminders"]["paused"] is True
