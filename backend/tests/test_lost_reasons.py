"""v9.2 Mark Lost: reason chips per business and the AI agent's guess from the chat."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import chat_actions
from app.services import lost_reasons
from tests.fake_supabase import FakeSupabase

T = "t1"
LEAD = "11111111-1111-4111-8111-111111111111"


def _db(business_type="Real Estate", inbound="Romba costly, 40 L kulla dhaan mudiyum"):
    db = FakeSupabase()
    db.add("tenants", id=T, business_type=business_type)
    db.add("leads", id=LEAD, tenant_id=T, assigned_to="c1", deleted_at=None)
    db.add("messages", tenant_id=T, lead_id=LEAD, direction="outbound", content="3BHK at 52 L", created_at="2026-11-20T10:00:00Z")
    if inbound:
        db.add("messages", tenant_id=T, lead_id=LEAD, direction="inbound", content=inbound, created_at="2026-11-20T10:05:00Z")
    return db


class GuessTests(unittest.TestCase):
    def test_chips_follow_the_business(self):
        self.assertIn("Loan not approved", lost_reasons.choices_for("real_estate"))
        self.assertIn("Fee too high", lost_reasons.choices_for("education"))
        self.assertIn("Price too high", lost_reasons.choices_for(None))

    def test_guess_picks_a_chip_and_quotes_them(self):
        seen = {}

        async def llm(prompt):
            seen["prompt"] = prompt
            return 'Sure: {"reason": "budget too high", "quote": "Romba costly, 40 L kulla dhaan mudiyum"}'

        out = asyncio.run(lost_reasons.guess(_db(), T, LEAD, llm=llm))
        self.assertEqual(out["reason"], "Budget too high")
        self.assertEqual(out["quote"], "Romba costly, 40 L kulla dhaan mudiyum")
        self.assertIn("Loan not approved", out["choices"])
        chat = seen["prompt"].split("Chat (oldest first):")[1]
        self.assertLess(chat.index("Business: 3BHK"), chat.index("Customer: Romba"))

    def test_a_made_up_reason_or_bad_answer_gives_no_guess(self):
        for answer in ('{"reason": "Too far", "quote": "x"}', "no idea", "[1]", ""):
            with self.subTest(answer=answer):
                async def llm(_p, a=answer):
                    return a
                out = asyncio.run(lost_reasons.guess(_db(), T, LEAD, llm=llm))
                self.assertEqual((out["reason"], out["quote"]), (None, None))

    def test_no_customer_message_means_no_model_call(self):
        llm = AsyncMock()
        out = asyncio.run(lost_reasons.guess(_db(inbound=None), T, LEAD, llm=llm))
        llm.assert_not_awaited()
        self.assertIsNone(out["reason"])


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        p = patch.object(chat_actions, "get_supabase", return_value=_db())
        p.start()
        self.addCleanup(p.stop)
        g = patch.object(lost_reasons, "guess", new=AsyncMock(return_value={"choices": ["A"], "reason": "A", "quote": "q"}))
        self.guess = g.start()
        self.addCleanup(g.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def as_role(self, role, caller_id=None, tenant=T, permissions=("conversations.reply",)):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": tenant, "role": role, "user_id": "u1", "caller_id": caller_id, "permissions": list(permissions)}

    def test_owner_gets_the_guess(self):
        self.as_role("owner")
        res = self.client.get(f"/api/v1/chats/{LEAD}/lost-guess")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["reason"], "A")

    def test_other_business_or_other_telecaller_is_404(self):
        self.as_role("owner", tenant="t2")
        self.assertEqual(self.client.get(f"/api/v1/chats/{LEAD}/lost-guess").status_code, 404)
        self.as_role("caller", caller_id="c9")
        self.assertEqual(self.client.get(f"/api/v1/chats/{LEAD}/lost-guess").status_code, 404)
        self.guess.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
