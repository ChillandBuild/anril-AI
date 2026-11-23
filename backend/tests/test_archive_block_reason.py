"""v9.2 Chats > Archived: Archive and Block keep the typed "Why"; undoing clears it."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import leads as lead_routes
from tests.fake_supabase import FakeSupabase

T = "t1"
LEAD = "11111111-1111-4111-8111-111111111111"


class ArchiveBlockReasonTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.db.add("leads", id=LEAD, tenant_id=T, archived_at=None, blocked_at=None, ai_enabled=True, deleted_at=None)
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": T, "role": "owner", "user_id": "u1", "caller_id": None, "permissions": []}
        for target, value in (("get_supabase", self.db), ("actor_name", "Karthik")):
            p = patch.object(lead_routes, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(lead_routes, "_close_handovers_for_blocked")
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def lead(self):
        return next(r for r in self.db.rows("leads") if r["id"] == LEAD)

    def test_archive_keeps_the_typed_why_and_move_back_clears_it(self):
        res = self.client.patch(f"/api/v1/leads/{LEAD}/archive", json={"reason": "  Not   now "})
        self.assertEqual(res.status_code, 200)
        self.assertEqual((self.lead()["archived_reason"], self.lead()["archived_by_name"]), ("Not now", "Karthik"))
        self.client.patch(f"/api/v1/leads/{LEAD}/archive")
        self.assertIsNone(self.lead()["archived_at"])
        self.assertIsNone(self.lead()["archived_reason"])

    def test_archive_with_no_body_still_works(self):
        self.assertEqual(self.client.patch(f"/api/v1/leads/{LEAD}/archive").status_code, 200)
        self.assertIsNotNone(self.lead()["archived_at"])
        self.assertIsNone(self.lead()["archived_reason"])

    def test_block_keeps_the_reason_and_unblock_clears_it(self):
        self.client.patch(f"/api/v1/leads/{LEAD}/block", json={"reason": "Spam links"})
        self.assertEqual(self.lead()["blocked_reason"], "Spam links")
        self.assertFalse(self.lead()["ai_enabled"])
        self.client.patch(f"/api/v1/leads/{LEAD}/block")
        self.assertIsNone(self.lead()["blocked_reason"])

    def test_a_too_long_why_is_refused(self):
        res = self.client.patch(f"/api/v1/leads/{LEAD}/block", json={"reason": "x" * 121})
        self.assertEqual(res.status_code, 422)
        self.assertIsNone(self.lead()["blocked_at"])


if __name__ == "__main__":
    unittest.main()
