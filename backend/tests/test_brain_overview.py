"""v9.2 Anril Brain top: goals reach the prompt, knows-%, who the agent is, Never do, recent changes."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.services import brain_overview as bo
from tests.fake_supabase import FakeSupabase

DESC = """ABOUT US
Demo Silks, sarees in Coimbatore.
HOW TO SOUND
Friendly shop staff, short replies.
WHAT YOU MUST NEVER DO
- never give a price not in the Catalogue
- never promise a discount
"""


def settings(values):
    return lambda key, fallback=None, tenant_id=None: values.get(key, fallback)


class GoalsTests(unittest.TestCase):
    def test_one_or_two_known_goals_in_order(self):
        self.assertEqual(bo.clean_goals(["order", "callback", "order", "nope"]), ["order", "callback"])
        with self.assertRaises(ValueError):
            bo.clean_goals(["order", "visit", "callback"])

    def test_prompt_line(self):
        with patch.object(bo, "get_setting", settings({"ai_chat_goals": '["order", "callback"]'})):
            line = bo.goals_block("t1")
        self.assertIn("First, take the order", line)
        self.assertIn("Only if the customer says not now, get a call back", line)
        with patch.object(bo, "get_setting", settings({})):
            self.assertEqual(bo.goals_block("t1"), "")

    def test_the_base_prompt_carries_the_goal(self):
        from app.services import ai_reply
        with patch.object(bo, "get_setting", settings({"ai_chat_goals": '["visit"]'})), \
             patch.object(ai_reply, "get_master_prompt", return_value="MASTER"), \
             patch.object(ai_reply, "get_setting", settings({})), \
             patch.object(ai_reply, "_handover_line", return_value=""):
            prompt = ai_reply._build_base_prompt("whatsapp", "t1")
        self.assertIn("GOAL OF EVERY CHAT", prompt)
        self.assertLess(prompt.index("GOAL OF EVERY CHAT"), prompt.index("HANDOVER RULE"))


class OverviewTests(unittest.TestCase):
    def test_overview_reads_what_drives_replies(self):
        db = FakeSupabase()
        vals = {"business_description": DESC, "reply_language_mode": "tanglish", "ai_chat_goals": '["order"]'}
        with patch.object(bo, "get_setting", settings(vals)), \
             patch("app.services.business_profile.get_setting", settings(vals)), \
             patch("app.services.knowledge_versions.list_versions", return_value=[{"id": "v1", "reason": "edit", "created_at": "x"}]):
            out = bo.overview(db, "t1")
        self.assertEqual(out["who"]["talks_like"], "Friendly shop staff, short replies.")
        self.assertEqual(out["who"]["language"], "Tanglish")
        self.assertEqual(out["never"]["count"], 2)
        self.assertEqual(out["goals"], ["order"])
        self.assertTrue(0 < out["knows_pct"] < 100)
        self.assertIn("Products and prices", out["missing"])
        self.assertEqual(out["recent"][0]["reason"], "edit")


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_saving_goals_needs_settings_manage(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t1", "role": "member", "user_id": "u1", "permissions": ["brain.view"]}
        self.assertEqual(self.client.put("/api/v1/brain/goals", json={"goals": ["order"]}).status_code, 403)
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t1", "role": "owner", "user_id": "u1", "permissions": []}
        with patch.object(bo, "save_setting") as save, patch.object(bo, "invalidate_cache"):
            res = self.client.put("/api/v1/brain/goals", json={"goals": ["order", "callback"]})
        self.assertEqual(res.json(), {"goals": ["order", "callback"]})
        save.assert_called_once_with("ai_chat_goals", '["order", "callback"]', tenant_id="t1")
        self.assertEqual(self.client.put("/api/v1/brain/goals", json={"goals": ["a", "order", "visit", "callback"]}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
