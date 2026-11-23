"""v9.2 #26: quiet time default (9 PM to 9 AM for businesses that never chose) and the alert list."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase  # noqa: E402

from app.services import alert_catalog, notification_config as nc  # noqa: E402


def _db(blob: dict | None = None) -> FakeSupabase:
    db = FakeSupabase()
    if blob is not None:
        db.add("app_settings", tenant_id="t1", key="notification_config", value=json.dumps(blob))
    return db


def _at_ist_hour(hour: int):
    """Patch the clock push_allowed reads so it is `hour` o'clock in India."""
    utc = datetime(2026, 11, 23, hour, 0, tzinfo=timezone.utc) - nc.timedelta(hours=5, minutes=30)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc if tz else utc.replace(tzinfo=None)

    return patch.object(nc, "datetime", FakeDT)


def test_never_saved_means_quiet_time_on_21_to_9():
    cfg = nc.get_notification_config("t1", db=_db())
    assert cfg["quiet_hours_unsaved"] is True
    q = nc.effective_quiet_hours(cfg)
    assert (q["enabled"], q["start_hour"], q["end_hour"]) == (True, 21, 9)


def test_settings_saved_without_quiet_time_still_get_the_default():
    cfg = nc.get_notification_config("t1", db=_db({"push_enabled": True}))
    assert cfg["quiet_hours_unsaved"] is True
    assert nc.effective_quiet_hours(cfg)["enabled"] is True


def test_saved_choice_is_untouched():
    off = nc.get_notification_config("t1", db=_db({"quiet_hours": {"enabled": False, "start_hour": 22, "end_hour": 8}}))
    assert off["quiet_hours_unsaved"] is False
    assert nc.effective_quiet_hours(off)["enabled"] is False
    mine = nc.get_notification_config("t1", db=_db({"quiet_hours": {"enabled": True, "start_hour": 23, "end_hour": 7}}))
    q = nc.effective_quiet_hours(mine)
    assert (q["enabled"], q["start_hour"], q["end_hour"]) == (True, 23, 7)


def test_unreadable_settings_do_not_turn_quiet_time_on():
    class Broken:
        def table(self, *_):
            raise RuntimeError("down")
    cfg = nc.get_notification_config("t1", db=Broken())
    assert not cfg.get("quiet_hours_unsaved")


def test_only_money_handover_and_disconnected_come_through():
    for ok in ("handover_new", "intake_paid", "refund_done", "payment_received", "number_disconnected"):
        assert nc.allowed_in_quiet_time(ok), ok
    for blocked in ("lead_replied", "callback_due", "batch_expiry", "feedback_unhappy", "", "anything_else"):
        assert not nc.allowed_in_quiet_time(blocked), blocked


def test_push_blocked_at_night_by_default_except_allowed_types():
    db = _db()
    with _at_ist_hour(22):
        assert nc.push_allowed("t1", "lead_replied", db=db) is False
        assert nc.push_allowed("t1", "handover_new", db=db) is True
        assert nc.push_allowed("t1", "intake_paid", db=db) is True
    with _at_ist_hour(8):
        assert nc.push_allowed("t1", "lead_replied", db=db) is False
    with _at_ist_hour(9):
        assert nc.push_allowed("t1", "lead_replied", db=db) is True
    with _at_ist_hour(14):
        assert nc.push_allowed("t1", "lead_replied", db=db) is True


def test_push_at_night_for_a_business_that_turned_quiet_time_off():
    db = _db({"quiet_hours": {"enabled": False, "start_hour": 22, "end_hour": 8}})
    with _at_ist_hour(23):
        assert nc.push_allowed("t1", "lead_replied", db=db) is True


def test_turning_one_alert_off_does_not_save_the_default_as_a_choice():
    db = _db()
    alert_catalog.set_alert(db, "t1", "batch_expiry", False)
    stored = json.loads(db.rows("app_settings")[0]["value"])
    assert "quiet_hours" not in stored                      # still "never chose"
    assert stored["events"]["batch_expiry"] is False
    assert nc.get_notification_config("t1", db=db)["quiet_hours_unsaved"] is True


def test_saving_quiet_time_makes_it_the_owners_choice():
    db = _db()
    view = alert_catalog.set_quiet_time(db, "t1", True, 22, 7)
    assert (view["start_hour"], view["end_hour"], view["is_default"]) == (22, 7, False)
    cfg = nc.get_notification_config("t1", db=db)
    assert cfg["quiet_hours_unsaved"] is False
    assert nc.effective_quiet_hours(cfg)["start_hour"] == 22
    view = alert_catalog.set_quiet_time(db, "t1", False, 22, 7)
    assert view["on"] is False


def test_quiet_time_rejects_bad_hours():
    db = _db()
    for args in ((True, 9, 9), (True, 25, 9), (True, 9, -1)):
        try:
            alert_catalog.set_quiet_time(db, "t1", *args)
        except ValueError:
            continue
        raise AssertionError(f"accepted {args}")


def test_alert_list_shape_and_toggle():
    db = _db()
    data = alert_catalog.list_alerts(db, "t1")
    by_key = {a["key"]: a for a in data["alerts"]}
    assert by_key["handover_new"]["on"] is True
    assert by_key["handover_new"]["comes_through_in_quiet_time"] is True
    assert by_key["batch_expiry"]["comes_through_in_quiet_time"] is False
    assert {"key", "label", "who", "how", "on"} <= set(by_key["intake_paid"])
    assert data["quiet_time"]["on"] is True and data["quiet_time"]["is_default"] is True
    got = alert_catalog.set_alert(db, "t1", "batch_expiry", False, ["owner", "team"])
    assert got["on"] is False and got["who"] == ["owner", "team"]
    again = {a["key"]: a for a in alert_catalog.list_alerts(db, "t1")["alerts"]}
    assert again["batch_expiry"]["on"] is False and again["batch_expiry"]["who"] == ["owner", "team"]
    assert nc.push_allowed("t1", "batch_expiry", db=db) is False


def test_set_alert_rejects_unknown_key_and_bad_who():
    db = _db()
    for key, who, exc in (("nope", None, KeyError), ("batch_expiry", ["wizard"], ValueError), ("batch_expiry", [], ValueError)):
        try:
            alert_catalog.set_alert(db, "t1", key, True, who)
        except exc:
            continue
        raise AssertionError((key, who))


def test_every_catalog_key_is_a_known_event_so_the_old_form_keeps_it():
    assert set(alert_catalog.alert_keys()) <= set(nc._NOTIFICATION_CONFIG_DEFAULT["events"])
