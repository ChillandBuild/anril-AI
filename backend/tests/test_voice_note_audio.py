"""v9.2 Chats: play a customer's WhatsApp voice note from the chat (fetched from Meta on Play)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import media as media_routes
from tests.fake_supabase import FakeSupabase

T = "t1"
LEAD = "11111111-1111-4111-8111-111111111111"
MSG = "22222222-2222-4222-8222-222222222222"
TEXT = "33333333-3333-4333-8333-333333333333"
URL = f"/api/v1/leads/{LEAD}/messages/{MSG}/audio"


class VoiceNoteAudioTests(unittest.TestCase):
    def setUp(self):
        db = FakeSupabase()
        db.add("leads", id=LEAD, tenant_id=T, assigned_to="c1", deleted_at=None)
        db.add("messages", id=MSG, lead_id=LEAD, tenant_id=T, media_type="audio", media_url="meta:M123")
        db.add("messages", id=TEXT, lead_id=LEAD, tenant_id=T, media_type=None, media_url=None)
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.as_role("owner")
        p = patch.object(media_routes, "get_supabase", return_value=db)
        p.start()
        self.addCleanup(p.stop)
        self.download = AsyncMock(return_value=(b"OggS-bytes", "audio/ogg", "https://x"))
        d = patch.object(media_routes, "download_media_from_meta", self.download)
        d.start()
        self.addCleanup(d.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def as_role(self, role, permissions=(), caller_id=None, tenant=T):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": tenant, "role": role, "user_id": "u1", "caller_id": caller_id, "permissions": list(permissions)}

    def test_plays_the_voice_note_from_whatsapp(self):
        res = self.client.get(URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"OggS-bytes")
        self.assertTrue(res.headers["content-type"].startswith("audio/ogg"))
        self.download.assert_awaited_once_with("M123", tenant_id=T)

    def test_expired_on_whatsapp_says_so(self):
        self.download.side_effect = HTTPException(status_code=404, detail="gone")
        res = self.client.get(URL)
        self.assertEqual(res.status_code, 410)
        self.assertIn("30 days", res.json()["detail"])

    def test_not_a_voice_note_is_404(self):
        self.assertEqual(self.client.get(f"/api/v1/leads/{LEAD}/messages/{TEXT}/audio").status_code, 404)

    def test_other_business_and_other_telecaller_get_404(self):
        self.as_role("owner", tenant="t2")
        self.assertEqual(self.client.get(URL).status_code, 404)
        self.as_role("caller", permissions=["conversations.view"], caller_id="c9")
        self.assertEqual(self.client.get(URL).status_code, 404)
        self.as_role("caller", permissions=["conversations.view"], caller_id="c1")
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_needs_conversations_view(self):
        self.as_role("manager", permissions=["leads.view"])
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.download.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
