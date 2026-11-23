"""v9.2 Mark Booked: the visit time read from the chat, and the WhatsApp confirmation."""
import asyncio
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import chat_actions
from app.services import visit_booking
from tests.fake_supabase import FakeSupabase

T = "t1"
LEAD = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=visit_booking.IST)  # a Saturday


def _db():
    db = FakeSupabase()
    db.add("tenants", id=T, name="Arun Real Estate")
    db.add("leads", id=LEAD, tenant_id=T, name="Arun Kumar", phone="+919876500001", assigned_to="c1", deleted_at=None)
    db.add("messages", tenant_id=T, lead_id=LEAD, direction="inbound", content="Monday 4 mani-ku vareen",
           created_at="2026-11-14T04:00:00Z")
    return db


class GuessTests(unittest.TestCase):
    def test_reads_the_time_they_gave(self):
        seen = {}

        async def llm(prompt):
            seen["prompt"] = prompt
            return '{"at": "2026-11-16T16:00", "quote": "Monday 4 mani-ku vareen"}'

        out = asyncio.run(visit_booking.guess(_db(), T, LEAD, llm=llm, now=NOW))
        self.assertEqual(out, {"at": "2026-11-16T16:00:00+05:30", "quote": "Monday 4 mani-ku vareen"})
        self.assertIn("Saturday 14 November 2026", seen["prompt"])

    def test_past_far_or_unreadable_times_are_dropped(self):
        for answer in ('{"at": "2026-11-01T10:00", "quote": "x"}', '{"at": "2027-12-01T10:00", "quote": "x"}',
                       '{"at": "Monday", "quote": "x"}', "no", '{"at": null, "quote": null}'):
            with self.subTest(answer=answer):
                self.assertEqual(visit_booking.parse_guess(answer, NOW), {"at": None, "quote": None})

    def test_confirmation_text(self):
        text = visit_booking.confirmation_text("Arun Kumar", "Arun Real Estate", "2026-11-16T10:30:00+00:00")
        self.assertEqual(text, "Hi Arun, your visit to Arun Real Estate is booked for Mon 16 Nov, 4:00 PM. "
                               "See you then! Reply here if you need to change it.")


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.db = _db()
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": T, "role": "owner", "user_id": "u1", "caller_id": None, "permissions": []}
        p = patch.object(chat_actions, "get_supabase", return_value=self.db)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_booking_with_confirmation_sends_it(self):
        send = AsyncMock(return_value={"sent": True, "reason": ""})
        with patch.object(visit_booking, "send_confirmation", send):
            res = self.client.put(f"/api/v1/chats/{LEAD}/booking",
                                  json={"booked_for": "2026-11-16T10:30:00Z", "send_confirmation": True})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["confirmation"], {"sent": True, "reason": ""})
        self.assertEqual(send.await_args.args[1:3], (T, LEAD))

    def test_booking_without_the_switch_sends_nothing(self):
        send = AsyncMock()
        with patch.object(visit_booking, "send_confirmation", send):
            res = self.client.put(f"/api/v1/chats/{LEAD}/booking", json={"booked_for": "2026-11-16T10:30:00Z"})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("confirmation", res.json())
        send.assert_not_awaited()

    def test_visit_guess_is_scoped(self):
        with patch.object(visit_booking, "guess", AsyncMock(return_value={"at": None, "quote": None})):
            self.assertEqual(self.client.get(f"/api/v1/chats/{LEAD}/visit-guess").status_code, 200)
            app.dependency_overrides[get_tenant_and_role] = lambda: {
                "tenant_id": T, "role": "caller", "user_id": "u2", "caller_id": "c9", "permissions": ["conversations.reply"]}
            self.assertEqual(self.client.get(f"/api/v1/chats/{LEAD}/visit-guess").status_code, 404)


if __name__ == "__main__":
    unittest.main()
