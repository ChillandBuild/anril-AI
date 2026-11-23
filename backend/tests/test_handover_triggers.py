"""v9.2 Replies & handover: angry / big order / photo reasons, the named person and the 15-minute backup."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.services import handover_alerts, handover_triggers as ht
from tests.fake_supabase import FakeSupabase

T = "t1"
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


class DetectTests(unittest.TestCase):
    def test_angry_words(self):
        for text in ("This is the worst service", "romba mosam", "you cheated me", "I want to complain", "மோசம்"):
            self.assertTrue(ht.angry(text), text)
        for text in ("Hi, price?", "worth it", "complimentary gift?"):
            self.assertFalse(ht.angry(text), text)

    def test_bulk_or_big_order(self):
        db = FakeSupabase()
        self.assertTrue(ht.big_order(db, T, "L1", "need 50 pcs for my shop", {}, NOW))
        self.assertFalse(ht.big_order(db, T, "L1", "need 2 pcs", {}, NOW))
        db.add("deals", tenant_id=T, lead_id="L1", total_paise=30_000_00, stage="awaiting_payment",
               created_at=(NOW - timedelta(minutes=2)).isoformat())
        self.assertTrue(ht.big_order(db, T, "L1", "ok", {}, NOW))
        self.assertFalse(ht.big_order(db, T, "L1", "ok", {"order_above_paise": 50_000_00}, NOW))

    def test_named_person_only_when_the_chat_has_no_owner(self):
        self.assertEqual(ht.first_owner({"handover_to": "k1"}, None), "k1")
        self.assertEqual(ht.first_owner({"handover_to": "k1"}, "r9"), "r9")
        self.assertIsNone(ht.first_owner({}, None))


class BackupTests(unittest.TestCase):
    def test_after_15_minutes_the_backup_gets_it(self):
        db = FakeSupabase()
        db.add("chat_handovers", id="h1", tenant_id=T, lead_id="L1", assigned_to="k1", status="pending",
               opened_at=(NOW - timedelta(minutes=20)).isoformat(), stale_alerted_at=None)
        db.add("callers", id="r2", tenant_id=T, user_id="u-ravi", active=True)
        told = []
        with patch("app.services.assignment.get_inbox_config", return_value={"handover_to": "k1", "backup_to": "r2"}), \
             patch("app.services.notify.notify_user", side_effect=lambda *a, **k: told.append(a[1])), \
             patch.object(handover_alerts, "_owner_ids", return_value=["u-owner"]):
            handover_alerts.sweep_stale_handovers(now=NOW, db=db)
        self.assertEqual(db.rows("chat_handovers")[0]["assigned_to"], "r2")
        self.assertIn("u-ravi", told)

    def test_a_chat_with_its_own_teammate_is_not_moved(self):
        db = FakeSupabase()
        db.add("chat_handovers", id="h1", tenant_id=T, lead_id="L1", assigned_to="z9", status="pending",
               opened_at=(NOW - timedelta(minutes=20)).isoformat(), stale_alerted_at=None)
        with patch("app.services.assignment.get_inbox_config", return_value={"handover_to": "k1", "backup_to": "r2"}), \
             patch("app.services.notify.notify_user"), patch.object(handover_alerts, "_owner_ids", return_value=[]):
            handover_alerts.sweep_stale_handovers(now=NOW, db=db)
        self.assertEqual(db.rows("chat_handovers")[0]["assigned_to"], "z9")


class ConfigRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "owner", "user_id": "u1", "permissions": []}

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_new_triggers_and_people_are_checked(self):
        db = FakeSupabase()
        db.add("callers", id="k1", tenant_id=T)
        saved = {}
        with patch("app.routes.app_settings.get_inbox_config", return_value={"triggers": ["C"]}), \
             patch("app.routes.app_settings.save_inbox_config", side_effect=lambda t, c: saved.update(c)), \
             patch("app.db.supabase.get_supabase", return_value=db):
            ok = self.client.patch("/api/v1/settings/inbox-config", json={"triggers": ["C", "G", "H", "I"], "handover_to": "k1", "order_above_paise": 2500000})
            bad = self.client.patch("/api/v1/settings/inbox-config", json={"handover_to": "stranger"})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual((saved["handover_to"], saved["order_above_paise"]), ("k1", 2500000))
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
