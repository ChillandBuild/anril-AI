"""A teammate's chat reply records who sent it (migration 272), so the thread can
label it with their name instead of a generic "Sent by you"."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.routes import leads as leads_route
from app.services.actor import actor_name
from tests.fake_supabase import FakeSupabase

LEAD = "11111111-1111-1111-1111-111111111111"


class SenderNameTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.db = FakeSupabase()
        self.db.add("leads", id=LEAD, tenant_id="t1", phone="+919800000000", source="whatsapp")
        self.db.add("callers", id="c1", tenant_id="t1", name="Karthik")
        self.db.add("tenant_users", user_id="u1", tenant_id="t1", full_name="Ravi Kumar")
        for p in (patch.object(leads_route, "get_supabase", return_value=self.db),
                  patch.object(leads_route, "send_whatsapp", AsyncMock(return_value="wamid.1"))):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def as_user(self, caller_id):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t1", "role": "owner", "user_id": "u1", "caller_id": caller_id, "permissions": [],
        }

    def test_reply_carries_the_teammate_name(self):
        self.as_user("c1")
        res = self.client.post(f"/api/v1/leads/{LEAD}/send", json={"content": "5% discount tharom"})
        self.assertEqual(res.status_code, 200, res.text)
        msg = self.db.rows("messages")[-1]
        self.assertEqual((msg["sent_by_user_id"], msg["sent_by_name"]), ("u1", "Karthik"))

    def test_owner_without_a_caller_profile_uses_their_account_name(self):
        self.as_user(None)
        self.client.post(f"/api/v1/leads/{LEAD}/send", json={"content": "hi"})
        self.assertEqual(self.db.rows("messages")[-1]["sent_by_name"], "Ravi Kumar")

    def test_thread_reload_keeps_ticks_media_and_sender(self):
        """GET /messages used to drop every column outside the base model, so a reloaded
        thread lost its read ticks, media and AI source."""
        self.as_user("c1")
        self.db.add("messages", id="22222222-2222-2222-2222-222222222222", tenant_id="t1", lead_id=LEAD,
                    direction="outbound", channel="whatsapp", content="hi", is_ai_generated=False,
                    created_at="2026-11-16T10:00:00+00:00", delivery_status="read", media_type="image",
                    media_url="meta:1", reply_source=None, sent_by_user_id="33333333-3333-3333-3333-333333333333",
                    sent_by_name="Karthik")
        app.dependency_overrides[get_tenant_id] = lambda: "t1"
        res = self.client.get(f"/api/v1/leads/{LEAD}/messages")
        self.assertEqual(res.status_code, 200, res.text)
        msg = res.json()[-1]
        self.assertEqual((msg["delivery_status"], msg["media_type"], msg["sent_by_name"]), ("read", "image", "Karthik"))

    def test_unknown_name_is_none_not_a_crash(self):
        self.assertIsNone(actor_name(FakeSupabase(), {"user_id": "nobody", "tenant_id": "t1", "caller_id": None}))


if __name__ == "__main__":
    unittest.main()
