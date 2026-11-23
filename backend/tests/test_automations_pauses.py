"""v9.2 #26: automation list and "a paused or turned-down template pauses everything using it"."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase  # noqa: E402

from app.services import automation_list, template_pauses  # noqa: E402

T = "t1"


def _seed() -> FakeSupabase:
    db = FakeSupabase()
    db.add("message_templates", id="tpl-a", tenant_id=T, name="thanks_order", status="APPROVED")
    db.add("message_templates", id="tpl-b", tenant_id=T, name="other_one", status="APPROVED")
    db.add("message_templates", id="tpl-fb", tenant_id=T, name="feedback_ask", status="APPROVED")
    db.add("auto_message_rules", id="r1", tenant_id=T, event="purchased", template_id="tpl-a", enabled=True)
    db.add("auto_message_rules", id="r2", tenant_id=T, event="interested", template_id="tpl-b", enabled=True)
    db.add("reengagement_steps", id="s1", tenant_id=T, type="inbound", delay_hours=48, message_type="template",
           template_name="thanks_order")
    db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
    db.add("app_settings", tenant_id=T, key="feedback_on", value="true")
    return db


def _by_key(db) -> dict:
    return {a["key"]: a for a in automation_list.list_automations(db, T)}


def test_list_has_every_kind_with_the_contract_fields():
    items = _by_key(_seed())
    kinds = {a["kind"] for a in items.values()}
    assert kinds == {"auto_message", "scheduled_template", "reengagement", "feedback", "evening_summary", "comeback_offer"}
    r1 = items["auto_message:r1"]
    for f in ("key", "name", "kind", "on", "template_name", "template_status", "paused_reason", "href"):
        assert f in r1
    assert (r1["template_name"], r1["template_status"], r1["on"], r1["paused_reason"]) == ("thanks_order", "APPROVED", True, None)
    assert items["feedback_ask"]["on"] is True
    assert items["evening_summary"]["on"] is False and items["comeback_offer"]["on"] is False   # off by default


def test_list_is_tenant_scoped():
    db = _seed()
    db.add("auto_message_rules", id="other", tenant_id="t2", event="purchased", template_id="x", enabled=True)
    assert "auto_message:other" not in _by_key(db)


def test_rejected_template_pauses_everything_that_uses_it():
    db = _seed()
    with patch("app.services.notify.notify_user") as bell:
        n = template_pauses.on_template_status_change(db, T, "thanks_order", "REJECTED")
    assert n == 2                                            # the auto message and the follow-up step
    items = _by_key(db)
    assert items["auto_message:r1"]["on"] is False and items["auto_message:r1"]["paused_reason"]
    assert items["reengagement:s1"]["paused"] is True        # no switch here: shown paused, sender already waits
    assert items["auto_message:r2"]["paused_reason"] is None and items["auto_message:r2"]["on"] is True
    bell.assert_called_once()
    assert bell.call_args.args[1] == "owner-1" and bell.call_args.args[2] == "template_paused"


def test_pausing_twice_changes_nothing_more():
    db = _seed()
    with patch("app.services.notify.notify_user") as bell:
        assert template_pauses.on_template_status_change(db, T, "thanks_order", "PAUSED") == 2
        assert template_pauses.on_template_status_change(db, T, "thanks_order", "PAUSED") == 0
    assert bell.call_count == 1


def test_approved_again_resumes_only_what_was_paused_by_us():
    db = _seed()
    # The owner switched r2 off by hand before the template trouble; it must stay off afterwards.
    automation_list.set_automation_on(db, T, "auto_message:r2", False)
    db.rows("auto_message_rules")[1]["template_id"] = "tpl-a"      # r2 now also uses thanks_order
    with patch("app.services.notify.notify_user"):
        assert template_pauses.on_template_status_change(db, T, "thanks_order", "DISABLED") == 2   # r1 + step; r2 was off
    assert _by_key(db)["auto_message:r1"]["on"] is False
    assert template_pauses.on_template_status_change(db, T, "thanks_order", "APPROVED") == 2
    items = _by_key(db)
    assert items["auto_message:r1"]["on"] is True and items["auto_message:r1"]["paused_reason"] is None
    assert items["auto_message:r2"]["on"] is False                # the owner's own off stays
    assert items["reengagement:s1"]["paused"] is False


def test_other_statuses_and_other_templates_change_nothing():
    db = _seed()
    for status in ("PENDING", "IN_APPEAL", "", "PENDING_DELETION"):
        assert template_pauses.on_template_status_change(db, T, "thanks_order", status) == 0
    assert template_pauses.on_template_status_change(db, T, "no_such_template", "REJECTED") == 0
    assert template_pauses.on_template_status_change(db, "t2", "thanks_order", "REJECTED") == 0
    assert _by_key(db)["auto_message:r1"]["on"] is True


def test_approved_without_a_pause_changes_nothing():
    assert template_pauses.on_template_status_change(_seed(), T, "thanks_order", "APPROVED") == 0


def test_feedback_ask_is_paused_and_resumed():
    db = _seed()
    with patch("app.services.notify.notify_user"), patch("app.config_dynamic.invalidate_cache"):
        assert template_pauses.on_template_status_change(db, T, "feedback_ask", "REJECTED") == 1
        assert _by_key(db)["feedback_ask"]["on"] is False
        assert template_pauses.on_template_status_change(db, T, "feedback_ask", "APPROVED") == 1
    assert _by_key(db)["feedback_ask"]["on"] is True


def test_pause_failure_never_raises():
    class Broken:
        def table(self, *_):
            raise RuntimeError("db down")
    assert template_pauses.on_template_status_change(Broken(), T, "thanks_order", "REJECTED") == 0


def test_list_flags_a_rejected_template_even_without_a_pause_record():
    db = _seed()
    db.rows("message_templates")[0]["status"] = "REJECTED"
    assert _by_key(db)["auto_message:r1"]["paused_reason"]


def test_toggle_helpers():
    db = _seed()
    automation_list.set_automation_on(db, T, "auto_message:r1", False)
    assert _by_key(db)["auto_message:r1"]["on"] is False
    for key, exc in (("scheduled_templates", automation_list.NotSwitchable), ("reengagement:s1", automation_list.NotSwitchable),
                     ("auto_message:nope", LookupError), ("whatever", LookupError)):
        try:
            automation_list.set_automation_on(db, T, key, True)
        except exc:
            continue
        raise AssertionError(key)
    # another business's rule cannot be switched from here
    db.add("auto_message_rules", id="x", tenant_id="t2", event="purchased", template_id="z", enabled=True)
    try:
        automation_list.set_automation_on(db, T, "auto_message:x", False)
    except LookupError:
        pass
    else:
        raise AssertionError("crossed tenants")
    assert [r for r in db.rows("auto_message_rules") if r["id"] == "x"][0]["enabled"] is True
