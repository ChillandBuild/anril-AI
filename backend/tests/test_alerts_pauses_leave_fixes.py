"""Logic-audit K fixes: alert saves never overwrite what they could not read, template-pause bells and
REINSTATED, leave stamped when nothing moved, the alerts list "who" matches delivery, break bell stamped first."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase  # noqa: E402

from app.services import alert_catalog, call_rules, caller_leave, notification_config as nc, template_pauses  # noqa: E402

T = "t1"


# ── 3. a settings read error must not turn into "save the defaults" ─────────

class _BlipDB(FakeSupabase):
    """Reads of app_settings fail; writes are recorded so the test can see none happened."""

    def __init__(self):
        super().__init__()
        self.writes = 0

    def table(self, name):
        if name == "app_settings":
            real = super().table(name)
            db = self

            class _Q:
                def __getattr__(self, attr):
                    if attr in ("upsert", "insert", "update"):
                        db.writes += 1
                    if attr in ("select", "maybe_single"):
                        raise RuntimeError("connection blip")
                    return getattr(real, attr)

            return _Q()
        return super().table(name)


def test_set_alert_aborts_when_settings_cannot_be_read():
    db = _BlipDB()
    with pytest.raises(HTTPException) as e:
        alert_catalog.set_alert(db, T, "batch_expiry", False)
    assert e.value.status_code == 503 and db.writes == 0


def test_set_alert_with_who_aborts_when_recipients_cannot_be_read():
    db = _BlipDB()
    with pytest.raises(HTTPException):
        alert_catalog.set_alert(db, T, "batch_expiry", True, ["team"])
    assert db.writes == 0


def test_set_quiet_time_aborts_when_settings_cannot_be_read():
    db = _BlipDB()
    with pytest.raises(HTTPException):
        alert_catalog.set_quiet_time(db, T, True, 22, 7)
    assert db.writes == 0


def test_strict_read_raises_but_default_read_still_falls_back():
    db = _BlipDB()
    with pytest.raises(RuntimeError):
        nc.get_notification_config(T, db=db, strict=True)
    assert nc.get_notification_config(T, db=db)["events"]   # non-strict: defaults, as before


def test_a_good_save_still_keeps_other_choices():
    db = FakeSupabase()
    db.add("app_settings", tenant_id=T, key="notification_config",
           value=json.dumps({"events": {"sms_low_balance": False}, "quiet_hours": {"enabled": True, "start_hour": 22, "end_hour": 6}}))
    alert_catalog.set_alert(db, T, "batch_expiry", False)
    stored = json.loads(db.rows("app_settings")[0]["value"])
    assert stored["events"]["sms_low_balance"] is False and stored["events"]["batch_expiry"] is False
    assert stored["quiet_hours"]["start_hour"] == 22


# ── 6. the list shows what delivery really does ─────────────────────────────

def test_alert_with_no_saved_choice_lists_team_because_delivery_reaches_everyone():
    db = FakeSupabase()
    row = next(a for a in alert_catalog.list_alerts(db, T)["alerts"] if a["key"] == "batch_expiry")
    assert nc.delivery_allowed(T, "some-caller", "batch_expiry", db=db) is True
    assert row["who"] == ["team"]


def test_saved_choice_and_fixed_rows_are_unchanged():
    db = FakeSupabase()
    alert_catalog.set_alert(db, T, "batch_expiry", True, ["owner"])
    alerts = {a["key"]: a for a in alert_catalog.list_alerts(db, T)["alerts"]}
    assert alerts["batch_expiry"]["who"] == ["owner"]
    assert alerts["lead_replied"]["who"] == ["assigned"]


# ── 4. template pauses ──────────────────────────────────────────────────────

def _seed() -> FakeSupabase:
    db = FakeSupabase()
    db.add("message_templates", id="tpl-a", tenant_id=T, name="thanks_order", status="APPROVED")
    db.add("auto_message_rules", id="r1", tenant_id=T, event="purchased", template_id="tpl-a", enabled=True)
    db.add("auto_message_rules", id="r2", tenant_id=T, event="interested", template_id="tpl-a", enabled=True)
    db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
    return db


def test_one_automation_failing_still_pauses_and_bells_the_rest():
    db = _seed()
    real = template_pauses.force_off
    calls = {"n": 0}

    def flaky(d, tenant, key):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("db blip")
        return real(d, tenant, key)

    with patch.object(template_pauses, "force_off", side_effect=flaky), \
         patch("app.services.notify.notify_user") as bell:
        n = template_pauses.on_template_status_change(db, T, "thanks_order", "REJECTED")
    assert n == 1
    assert len(db.rows("automation_pauses")) == 1
    bell.assert_called_once()                                  # the owner is told about the one that was paused


def test_open_pause_for_an_older_template_does_not_hide_a_new_rejection():
    db = _seed()
    db.add("automation_pauses", tenant_id=T, automation_key="auto_message:r1", automation_name="x",
           template_name="old_template", reason="Rejected", switched_off=True)
    with patch("app.services.notify.notify_user") as bell:
        n = template_pauses.on_template_status_change(db, T, "thanks_order", "REJECTED")
    assert n == 2
    assert any(r["template_name"] == "thanks_order" and r["automation_key"] == "auto_message:r1" for r in db.rows("automation_pauses"))
    bell.assert_called_once()


def test_same_template_retry_is_still_skipped():
    db = _seed()
    with patch("app.services.notify.notify_user"):
        assert template_pauses.on_template_status_change(db, T, "thanks_order", "REJECTED") == 2
        assert template_pauses.on_template_status_change(db, T, "thanks_order", "REJECTED") == 0


def test_reinstated_template_resumes_what_was_paused():
    db = _seed()
    with patch("app.services.notify.notify_user"):
        template_pauses.on_template_status_change(db, T, "thanks_order", "REJECTED")
        assert all(r["enabled"] is False for r in db.rows("auto_message_rules"))
        assert template_pauses.on_template_status_change(db, T, "thanks_order", "REINSTATED") == 2
    assert all(r["enabled"] is True for r in db.rows("auto_message_rules"))
    assert all(r.get("resumed_at") for r in db.rows("automation_pauses"))


# ── 5. leave with nothing to move is still stamped ──────────────────────────

NOW = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)


def test_leave_with_no_open_leads_is_stamped_so_it_is_not_rerun():
    db = FakeSupabase()
    db.add("callers", id="a", tenant_id=T, name="Asha", active=True, leave_from="2026-11-23", leave_to="2026-11-30", leave_leads_moved_at=None)
    db.add("callers", id="b", tenant_id=T, name="Bala", active=True)
    with patch("app.services.assignment.eligible_callers", return_value=[{"id": "a", "name": "Asha"}, {"id": "b", "name": "Bala"}]), \
         patch.object(caller_leave, "_open_lead_rows", return_value=[]):
        out = caller_leave.move_leads_of_caller_on_leave(db, T, "a", NOW)
    assert (out["moved"], out["no_one_free"]) == (0, False)
    assert next(r for r in db.rows("callers") if r["id"] == "a")["leave_leads_moved_at"]


def test_leave_with_nobody_free_is_not_stamped_so_it_retries():
    db = FakeSupabase()
    db.add("callers", id="a", tenant_id=T, name="Asha", active=True, leave_from="2026-11-23", leave_to="2026-11-30", leave_leads_moved_at=None)
    with patch("app.services.assignment.eligible_callers", return_value=[{"id": "a", "name": "Asha"}]):
        out = caller_leave.move_leads_of_caller_on_leave(db, T, "a", NOW)
    assert out["no_one_free"] is True
    assert next(r for r in db.rows("callers") if r["id"] == "a").get("leave_leads_moved_at") is None


# ── break limit: stamp before notifying ─────────────────────────────────────

def test_break_alert_is_stamped_before_notify_so_a_crash_cannot_repeat_it():
    db = FakeSupabase()
    db.add("callers", id="c1", tenant_id=T, name="Priya", status="break", active=True,
           status_changed_at=(NOW - timedelta(minutes=40)).isoformat(), break_alert_sent_at=None)
    with patch("app.services.call_alerts.admin_user_ids", return_value=["owner-1"]), \
         patch("app.services.notify.notify_user", side_effect=RuntimeError("push crashed")), \
         patch("app.services.caller_leave.start_due_leaves", return_value=0):
        call_rules.check_break_limits(db, NOW)
        first = db.rows("callers")[0]["break_alert_sent_at"]
        assert first                                            # stamped even though notify blew up
        with patch("app.services.notify.notify_user") as bell:
            assert call_rules.check_break_limits(db, NOW + timedelta(minutes=5)) == 0
        bell.assert_not_called()
