"""v9.2: Replies you like. A 👍 on an AI reply in Chats (or a typed example) teaches the AI agent a style."""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import ai_teach as routes
from app.services import ai_teach
from tests.fake_supabase import FakeSupabase

T = "t1"
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=ai_teach.IST)


def _msg(db, mid, direction, content, at, ai=False, tenant=T, lead="L1"):
    db.add("messages", id=mid, tenant_id=tenant, lead_id=lead, direction=direction, content=content,
           is_ai_generated=ai, created_at=f"2026-11-23T10:{at:02d}:00+00:00")


class _Base(unittest.TestCase):
    def setUp(self):
        ai_teach.clear_cache()
        self.db = FakeSupabase()
        _msg(self.db, "m0", "outbound", "Vanakkam!", 0, ai=True)
        _msg(self.db, "m1", "inbound", "Photo", 1)
        _msg(self.db, "m2", "inbound", "anuppunga", 2)
        _msg(self.db, "m3", "outbound", "Idho 3 colours 😊 Endha colour pidichirukku?", 3, ai=True)
        _msg(self.db, "m4", "outbound", "Sent by Karthik", 4, ai=False)
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.as_role("owner")
        p = patch.object(routes, "get_supabase", return_value=self.db)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()
        ai_teach.clear_cache()

    def as_role(self, role, permissions=(), tenant=T):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": tenant, "role": role, "user_id": "u1", "caller_id": None, "permissions": list(permissions)}

    def liked(self):
        return [r for r in self.db.rows("ai_teach_items") if r["kind"] == "liked"]


class LikeTests(_Base):
    def test_like_saves_the_reply_with_the_customer_messages_before_it(self):
        res = self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"})
        self.assertEqual(res.status_code, 200, res.text)
        [row] = self.liked()
        self.assertEqual(row["prompt"], "Photo / anuppunga")
        self.assertEqual(row["reply"], "Idho 3 colours 😊 Endha colour pidichirukku?")
        self.assertEqual((row["source"], row["message_id"]), ("chat", "m3"))

    def test_liking_twice_keeps_one_row(self):
        self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"})
        self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"})
        self.assertEqual(len(self.liked()), 1)

    def test_team_messages_customer_messages_and_other_businesses_are_refused(self):
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m4"}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m1"}).status_code, 422)
        _msg(self.db, "x1", "outbound", "Other shop", 5, ai=True, tenant="t2")
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "x1"}).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "nope"}).status_code, 404)
        self.assertEqual(self.liked(), [])

    def test_a_reply_with_no_customer_message_before_it_is_refused(self):
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m0"}).status_code, 422)

    def test_a_telecaller_only_likes_replies_on_their_own_customers(self):
        self.db.add("leads", id="L1", tenant_id=T, assigned_to="c1")
        self.as_role("caller", permissions=["knowledge.manage"])
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": T, "role": "caller", "user_id": "u1", "caller_id": "c2", "permissions": ["knowledge.manage"]}
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"}).status_code, 404)
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": T, "role": "caller", "user_id": "u1", "caller_id": "c1", "permissions": ["knowledge.manage"]}
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"}).status_code, 200)

    def test_needs_knowledge_manage(self):
        self.as_role("manager", permissions=["knowledge.view", "conversations.view"])
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"}).status_code, 403)
        self.as_role("manager", permissions=["knowledge.manage"])
        self.assertEqual(self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"}).status_code, 200)

    def test_marks_and_unlike(self):
        self.client.post("/api/v1/ai-teach/liked", json={"message_id": "m3"})
        res = self.client.get("/api/v1/ai-teach/liked/marks", params={"message_ids": "m0,m3"})
        self.assertEqual(res.json(), {"liked": ["m3"]})
        self.assertEqual(self.client.delete("/api/v1/ai-teach/liked/m3").status_code, 200)
        self.assertEqual(self.liked(), [])

    def test_fifty_is_the_most(self):
        for i in range(ai_teach.MAX_LIKED_SAVED):
            ai_teach.save_item(self.db, T, "liked", f"question {i}", f"reply {i}")
        res = self.client.post("/api/v1/ai-teach/items", json={"kind": "liked", "prompt": "one more", "reply": "x"})
        self.assertEqual(res.status_code, 422)
        self.assertIn("50", res.json()["detail"])


class PromptTests(_Base):
    def test_prompt_holds_the_ten_newest_as_style_only(self):
        for i in range(12):  # updated_at is the database's now(); the fake needs it given
            self.db.add("ai_teach_items", id=f"i{i}", tenant_id=T, kind="liked", prompt=f"question {i}",
                        reply=f"reply {i}", match_key=f"question {i}", source="manual",
                        updated_at=f"2026-11-23T10:{i:02d}:00+00:00")
        block = ai_teach.prompt_block(self.db, T, NOW)
        self.assertIn("REPLIES THE OWNER LIKED", block)
        self.assertIn("Style only", block)
        self.assertIn("- Customer: question 11\n  Reply: reply 11", block)
        self.assertEqual(block.count("- Customer:"), ai_teach.MAX_LIKED_PROMPT)
        self.assertNotIn("question 0", block)

    def test_no_examples_no_block(self):
        self.assertNotIn("REPLIES THE OWNER LIKED", ai_teach.prompt_block(self.db, T, NOW))


if __name__ == "__main__":
    unittest.main()
