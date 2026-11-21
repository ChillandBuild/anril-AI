"""Call-back reminders: a push 10 minutes before, and a late alert 15 minutes after (once each, staff only)."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import callback_notifications as cn
from tests.fake_supabase import FakeSupabase

NOW = datetime(2026, 11, 21, 5, 30, 0, tzinfo=timezone.utc)  # 11:00 IST
iso = lambda dt: dt.isoformat()
at = lambda minutes: iso(NOW + timedelta(minutes=minutes))


def make_db():
    db = FakeSupabase()
    db.rows("callers").append({"id": "c1", "tenant_id": "t1", "name": "Anitha", "user_id": "u-anitha", "team_id": "team1"})
    db.rows("leads").append({"id": "l1", "tenant_id": "t1", "name": "Ravi K", "assigned_to": "c1", "deleted_at": None})
    db.rows("tenant_users").extend([
        {"tenant_id": "t1", "user_id": "u-owner", "role": "owner"},
        {"tenant_id": "t1", "user_id": "u-anitha", "role": "caller"},
    ])
    return db


def job(db, when, jid="j1", **extra):
    row = {"id": jid, "tenant_id": "t1", "lead_id": "l1", "cadence": "callback", "status": "pending",
           "scheduled_for": when, "reminder_notified_at": None, "late_alerted_at": None}
    row.update(extra)
    db.rows("follow_up_jobs").append(row)
    return row


class CallReminderTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.sent = []
        self.p = patch.object(cn, "notify_user", side_effect=lambda *a, **k: self.sent.append((a[1], a[2], a[4], k.get("push_url"))))
        self.p.start()
        cn._warned_missing_columns = False

    def tearDown(self):
        self.p.stop()

    def run_steps(self, now=NOW):
        return cn._run_reminder_steps(self.db, "t1", now, iso(now))

    # ── 10 minutes before ────────────────────────────────────────────────────

    def test_reminder_fires_once_for_a_call_back_in_8_minutes(self):
        job(self.db, at(8))
        self.assertEqual(self.run_steps(), (1, 0))
        self.assertEqual(len(self.sent), 1)
        user, kind, message, url = self.sent[0]
        self.assertEqual((user, kind), ("u-anitha", "callback_reminder"))
        self.assertIn("Ravi K", message)
        self.assertEqual(url, "/dashboard/telecalling/scheduled")
        self.assertIsNotNone(self.db.rows("follow_up_jobs")[0]["reminder_notified_at"])
        self.assertEqual(self.run_steps(), (0, 0))  # the next minute: silent
        self.assertEqual(len(self.sent), 1)

    def test_no_reminder_yet_for_a_call_back_20_minutes_away_or_already_past(self):
        job(self.db, at(20), "far")
        job(self.db, at(-1), "past")
        self.assertEqual(self.run_steps(), (0, 0))
        self.assertEqual(self.sent, [])

    def test_reminder_goes_only_to_the_assigned_telecaller_and_skips_unassigned_or_deleted(self):
        job(self.db, at(5), "a")
        self.db.rows("leads").append({"id": "l2", "tenant_id": "t1", "name": "Nobody", "assigned_to": None, "deleted_at": None})
        self.db.rows("leads").append({"id": "l3", "tenant_id": "t1", "name": "Gone", "assigned_to": "c1", "deleted_at": "2026-11-01T00:00:00+00:00"})
        job(self.db, at(5), "b", lead_id="l2")
        job(self.db, at(5), "c", lead_id="l3")
        self.run_steps()
        self.assertEqual([s[0] for s in self.sent], ["u-anitha"])

    def test_the_time_in_the_message_is_ist(self):
        job(self.db, at(8))  # 11:08 IST
        self.run_steps()
        self.assertIn("11:08", self.sent[0][2])

    # ── 15 minutes late ──────────────────────────────────────────────────────

    def test_late_alert_goes_to_the_team_leader_not_the_owner(self):
        self.db.rows("call_team_leaders").append({"team_id": "team1", "tenant_id": "t1", "user_id": "u-leader"})
        job(self.db, at(-16))
        self.assertEqual(self.run_steps(), (0, 1))
        self.assertEqual([(s[0], s[1]) for s in self.sent], [("u-leader", "callback_late")])
        self.assertEqual(self.sent[0][2], "Anitha is 16 min late on a call-back to Ravi K (10:44)")
        self.assertEqual(self.sent[0][3], "/dashboard/telecalling/scheduled")

    def test_late_alert_goes_to_every_leader_of_the_team(self):
        self.db.rows("call_team_leaders").extend([
            {"team_id": "team1", "tenant_id": "t1", "user_id": "u-l1"},
            {"team_id": "team1", "tenant_id": "t1", "user_id": "u-l2"},
        ])
        job(self.db, at(-15))
        self.run_steps()
        self.assertEqual(sorted(s[0] for s in self.sent), ["u-l1", "u-l2"])

    def test_late_alert_goes_to_the_owner_when_the_team_has_no_leader(self):
        job(self.db, at(-20))
        self.run_steps()
        self.assertEqual([(s[0], s[1]) for s in self.sent], [("u-owner", "callback_late")])

    def test_late_alert_goes_to_the_owner_when_the_telecaller_has_no_team(self):
        self.db.rows("callers")[0]["team_id"] = None
        job(self.db, at(-20))
        self.run_steps()
        self.assertEqual([s[0] for s in self.sent], ["u-owner"])

    def test_late_alert_fires_once(self):
        job(self.db, at(-20))
        self.assertEqual(self.run_steps(), (0, 1))
        self.assertEqual(self.run_steps(now=NOW + timedelta(minutes=1)), (0, 0))
        self.assertEqual(len(self.sent), 1)
        self.assertIsNotNone(self.db.rows("follow_up_jobs")[0]["late_alerted_at"])

    def test_not_late_yet_done_or_ancient_call_backs_are_left_alone(self):
        job(self.db, at(-10), "not-yet-15")
        job(self.db, at(-30), "done", status="done")
        job(self.db, at(-60 * 24), "old-backlog")
        self.assertEqual(self.run_steps(), (0, 0))
        self.assertEqual(self.sent, [])

    def test_the_telecaller_never_gets_their_own_late_alert(self):
        self.db.rows("call_team_leaders").append({"team_id": "team1", "tenant_id": "t1", "user_id": "u-anitha"})
        job(self.db, at(-20))
        self.run_steps()
        self.assertEqual([s[0] for s in self.sent], ["u-owner"])

    def test_a_call_back_with_no_assigned_telecaller_is_skipped(self):
        self.db.rows("leads").append({"id": "l2", "tenant_id": "t1", "name": "X", "assigned_to": None, "deleted_at": None})
        job(self.db, at(-20), lead_id="l2")
        self.assertEqual(self.run_steps(), (0, 0))

    def test_only_staff_are_ever_notified(self):
        # Every recipient is a user id; the lead (a customer) has none. Nothing here can message a phone number.
        self.db.rows("call_team_leaders").append({"team_id": "team1", "tenant_id": "t1", "user_id": "u-leader"})
        job(self.db, at(5), "a")
        job(self.db, at(-20), "b")
        self.run_steps()
        self.assertTrue(all(s[0].startswith("u-") for s in self.sent))

    # ── never raises ─────────────────────────────────────────────────────────

    def test_missing_columns_skip_both_steps_with_one_warning(self):
        real = self.db.table

        def table(name):
            if name == "follow_up_jobs":
                raise Exception('column follow_up_jobs.reminder_notified_at does not exist')
            return real(name)
        self.db.table = table
        with self.assertLogs(cn.logger, level="WARNING") as logs:
            self.assertEqual(self.run_steps(), (0, 0))
            self.assertEqual(self.run_steps(), (0, 0))
        self.assertEqual(len([r for r in logs.records if "migration 307" in r.getMessage()]), 1)

    def test_any_other_error_does_not_raise(self):
        self.db.table = lambda name: (_ for _ in ()).throw(Exception("db down"))
        self.assertEqual(self.run_steps(), (0, 0))

    def test_a_failing_push_does_not_stop_the_other_call_backs(self):
        job(self.db, at(5), "a")
        self.db.rows("leads").append({"id": "l9", "tenant_id": "t1", "name": "Second", "assigned_to": "c1", "deleted_at": None})
        job(self.db, at(6), "b", lead_id="l9")
        calls = []

        def flaky(*a, **k):
            calls.append(a[4])
            if len(calls) == 1:
                raise RuntimeError("push service down")
        with patch.object(cn, "notify_user", side_effect=flaky):
            self.assertEqual(self.run_steps(), (1, 0))
        self.assertEqual(len(calls), 2)


class SchedulerJobTests(unittest.TestCase):
    """The scheduler entry point still does its old work and adds the new steps."""

    def test_the_job_runs_the_new_steps_and_keeps_its_return_shape(self):
        db = make_db()
        db.rows("app_settings").append({"tenant_id": "t1", "key": "telecalling_config", "value": json.dumps({"enabled": True})})
        job(db, iso(datetime.now(timezone.utc) + timedelta(minutes=5)))
        sent = []
        with patch.object(cn, "get_supabase", return_value=db), \
             patch.object(cn, "get_notification_config", return_value={"claimable_threshold_minutes": 15, "claimable_audience": "telecallers_and_admin"}), \
             patch.object(cn, "notify_callback_claimable"), \
             patch.object(cn, "notify_user", side_effect=lambda *a, **k: sent.append(a[2])):
            result = cn.process_callback_notifications()
        self.assertEqual(set(result), {"due", "claimable"})
        self.assertEqual(sent, ["callback_reminder"])


if __name__ == "__main__":
    unittest.main()
