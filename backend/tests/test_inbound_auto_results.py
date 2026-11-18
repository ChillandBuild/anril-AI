"""Inbound leads results Anril sets by itself (stopped replying, unmarked bookings), Undo,
and the renamable result steps. Fake database; the SQL rule function is stubbed."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.services import inbound_auto_results as auto
from tests.fake_supabase import FakeSupabase

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)  # 8:30 PM IST


def _lead(db, lid, tenant="tenant-1", **extra):
    row = {"id": lid, "tenant_id": tenant, "name": lid, "phone": "+91" + lid, "deleted_at": None,
           "lost_at": None, "booked_at": None, "converted_at": None, "lost_auto": False}
    row.update(extra)
    db.rows("leads").append(row)
    return row


class StoppedReplyingTests(unittest.TestCase):
    def test_marks_what_the_rule_returns_but_rechecks_each_lead(self):
        db = FakeSupabase()
        quiet = _lead(db, "quiet")
        booked_meanwhile = _lead(db, "booked", booked_at=NOW.isoformat())
        calls = []

        def rpc(name, params):
            calls.append((name, params))
            rows = [{"lead_id": "quiet", "tenant_id": "tenant-1"}, {"lead_id": "booked", "tenant_id": "tenant-1"}]
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows if len(calls) == 1 else []))

        db.rpc = rpc
        self.assertEqual(auto.mark_stopped_replying(db, now=NOW), 1)
        self.assertEqual(calls[0][0], "stopped_replying_leads")
        self.assertEqual(calls[0][1]["p_cutoff"], (NOW - timedelta(days=3)).isoformat())
        self.assertEqual((quiet["lost_reason"], quiet["lost_auto"]), ("Stopped replying", True))
        self.assertIsNone(booked_meanwhile["lost_at"])


class UnmarkedBookingsTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        today_7pm_ist = datetime(2026, 11, 18, 13, 30, tzinfo=timezone.utc).isoformat()
        _lead(self.db, "priya", booked_at=NOW.isoformat(), booked_for=today_7pm_ist)
        _lead(self.db, "arun", booked_at=NOW.isoformat(), booked_for=today_7pm_ist)
        _lead(self.db, "paid", booked_at=NOW.isoformat(), booked_for=today_7pm_ist)
        _lead(self.db, "tomorrow", booked_at=NOW.isoformat(), booked_for=(NOW + timedelta(days=1)).isoformat())
        _lead(self.db, "lost", booked_for=today_7pm_ist, lost_at=NOW.isoformat())
        self.db.rows("deals").append({"id": "d1", "tenant_id": "tenant-1", "lead_id": "paid", "stage": "won"})
        self.db.rows("tenant_users").append({"tenant_id": "tenant-1", "user_id": "owner-1", "role": "owner"})
        self.db.rows("tenant_users").append({"tenant_id": "tenant-1", "user_id": "staff-1", "role": "caller"})

    def test_one_bell_per_owner_listing_only_unmarked_bookings(self):
        with patch("app.services.notification_config.push_allowed", return_value=False):
            self.assertEqual(auto.remind_unmarked_bookings(self.db, now=NOW), 1)
            # The database stamps created_at with now(); the fake uses a fixed clock.
            self.db.rows("app_notifications")[0]["created_at"] = NOW.isoformat()
            self.assertEqual(auto.remind_unmarked_bookings(self.db, now=NOW), 0)  # once a day
        bells = self.db.rows("app_notifications")
        self.assertEqual(len(bells), 1)
        self.assertEqual(bells[0]["user_id"], "owner-1")
        self.assertEqual(bells[0]["title"], "2 bookings today not marked yet")
        self.assertIn("priya", bells[0]["message"])
        self.assertNotIn("paid", bells[0]["message"].split(".")[0])


class _Routes(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.patches = [patch(f"app.routes.{m}.get_supabase", return_value=self.db) for m in ("chat_actions", "inbound_leads")]
        for p in self.patches:
            p.start()
        self.ctx = {"tenant_id": "tenant-1", "role": "owner", "user_id": "u1", "permissions": []}
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_tenant_id] = lambda: "tenant-1"
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()


class UndoTests(_Routes):
    def test_undo_of_an_automatic_lost_is_remembered(self):
        lead = _lead(self.db, "11111111-1111-1111-1111-111111111111", lost_at=NOW.isoformat(),
                     lost_reason="Stopped replying", lost_auto=True)
        res = self.client.delete(f"/api/v1/chats/{lead['id']}/not-buying")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(lead["lost_at"])
        self.assertFalse(lead["lost_auto"])
        self.assertIsNotNone(lead["auto_lost_dismissed_at"])

    def test_a_person_marking_not_buying_is_never_auto(self):
        lead = _lead(self.db, "22222222-2222-2222-2222-222222222222", lost_auto=True)
        self.client.put(f"/api/v1/chats/{lead['id']}/not-buying", json={"reason": "Price too high"})
        self.assertFalse(lead["lost_auto"])
        self.assertNotIn("auto_lost_dismissed_at", lead)


class ResultLabelsTests(_Routes):
    def test_defaults_then_owner_renames(self):
        with patch("app.config_dynamic.get_setting", return_value=None):
            self.assertEqual(self.client.get("/api/v1/inbound-leads/result-labels").json(),
                             {"booked": "Booked", "paid": "Came / Paid", "lost": "Lost"})
        res = self.client.put("/api/v1/inbound-leads/result-labels",
                              json={"booked": " Site visit  booked ", "paid": "Advance paid", "lost": "Lost"})
        self.assertEqual(res.status_code, 200, res.text)
        stored = self.db.rows("app_settings")[-1]
        self.assertEqual(stored["key"], "inbound_result_labels")
        self.assertIn("Site visit booked", stored["value"])

    def test_names_must_differ_and_only_the_owner_renames(self):
        res = self.client.put("/api/v1/inbound-leads/result-labels", json={"booked": "Done", "paid": "done", "lost": "Lost"})
        self.assertEqual(res.status_code, 400)
        self.ctx = {"tenant_id": "tenant-1", "role": "caller", "user_id": "u2", "permissions": []}
        res = self.client.put("/api/v1/inbound-leads/result-labels", json={"booked": "A", "paid": "B", "lost": "C"})
        self.assertEqual(res.status_code, 403)
