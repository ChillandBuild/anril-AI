"""Chats page actions (migration 272): shared seen, Booked / Not buying, teaching the
Anril AI from a teammate's reply, and Record payment's deal lines."""
import asyncio
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
from app.routes import chat_actions
from app.routes.deals import record_payment_lines
from app.services import ai_teach, teach
from tests.fake_supabase import FakeSupabase


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.as_role("owner")
        db = self.db = FakeSupabase()
        db.add("leads", id="11111111-1111-1111-1111-111111111111", tenant_id="t1", deleted_at=None,
               lost_at="2026-10-01T00:00:00+00:00", lost_reason="Price", booked_at=None)
        db.add("leads", id="22222222-2222-2222-2222-222222222222", tenant_id="t2", deleted_at=None)
        p = patch.object(chat_actions, "get_supabase", return_value=db)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def as_role(self, role, permissions=("conversations.view", "conversations.reply")):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t1", "role": role, "user_id": "u1", "caller_id": None, "permissions": list(permissions),
        }

    LEAD = "11111111-1111-1111-1111-111111111111"
    OTHER_TENANT_LEAD = "22222222-2222-2222-2222-222222222222"

    def lead(self):
        return next(r for r in self.db.rows("leads") if r["id"] == self.LEAD)


class LeadActionTests(_Base):
    def test_seen_stamps_the_chat_for_the_whole_team(self):
        self.assertEqual(self.client.post(f"/api/v1/chats/{self.LEAD}/seen").status_code, 200)
        self.assertTrue(self.lead()["team_seen_at"])

    def test_booking_clears_not_buying(self):
        res = self.client.put(f"/api/v1/chats/{self.LEAD}/booking",
                              json={"booked_for": "2026-11-20T10:00:00Z", "note": " Saturday visit "})
        self.assertEqual(res.status_code, 200, res.text)
        lead = self.lead()
        self.assertTrue(lead["booked_at"])
        self.assertEqual(lead["booking_note"], "Saturday visit")
        self.assertIsNone(lead["lost_at"])
        self.assertIsNone(lead["lost_reason"])

    def test_not_buying_clears_booking(self):
        self.client.put(f"/api/v1/chats/{self.LEAD}/booking", json={})
        res = self.client.put(f"/api/v1/chats/{self.LEAD}/not-buying", json={"reason": "Bought elsewhere"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.lead()["lost_reason"], "Bought elsewhere")
        self.assertIsNone(self.lead()["booked_at"])

    def test_not_buying_reason_in_own_words_is_trimmed_and_capped(self):
        res = self.client.put(f"/api/v1/chats/{self.LEAD}/not-buying", json={"reason": "  Wants   a   cheaper\n option  "})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.lead()["lost_reason"], "Wants a cheaper option")
        self.client.put(f"/api/v1/chats/{self.LEAD}/not-buying", json={"reason": "x" * 500})
        self.assertEqual(self.lead()["lost_reason"], "x" * 120)
        self.assertEqual(self.client.put(f"/api/v1/chats/{self.LEAD}/not-buying", json={"reason": "   "}).status_code, 422)
        self.assertEqual(self.lead()["lost_reason"], "x" * 120)  # a blank one saved nothing

    def test_another_business_chat_is_not_found(self):
        res = self.client.put(f"/api/v1/chats/{self.OTHER_TENANT_LEAD}/not-buying", json={"reason": "x"})
        self.assertEqual(res.status_code, 404)

    def test_read_only_teammates_cannot_change_the_result(self):
        self.as_role("caller", permissions=("conversations.view",))
        self.assertEqual(self.client.put(f"/api/v1/chats/{self.LEAD}/booking", json={}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/chats/{self.LEAD}/seen").status_code, 200)


class TeachTests(_Base):
    def add_chat(self):
        for direction, content, by in [
            ("inbound", "Hi, bridal saree venum", None),
            ("outbound", "Idho red silk bridal sarees", None),
            ("inbound", "Discount kidaikkuma?", None),
            ("outbound", "Kavitha, bridal sarees-ku 5% discount tharom. 15,000 -> 14,250", "u1"),
        ]:
            self.db.add("messages", tenant_id="t1", lead_id=self.LEAD, direction=direction, content=content,
                        is_ai_generated=direction == "outbound" and by is None, media_type=None, sent_by_user_id=by)

    def test_suggestion_reads_the_teammate_reply_and_the_question_before_it(self):
        self.add_chat()
        fake = AsyncMock(return_value={"when": "someone asks for a discount on bridal sarees", "say": "5% discount irukku"})
        with patch.object(teach, "suggest", fake):
            res = self.client.get(f"/api/v1/chats/{self.LEAD}/teach-suggestion")
        self.assertEqual(res.status_code, 200, res.text)
        question, reply = fake.call_args.args
        self.assertEqual(question, "Discount kidaikkuma?")
        self.assertIn("5% discount tharom", reply)
        self.assertEqual(res.json()["suggestion"]["say"], "5% discount irukku")

    def test_only_the_owner_can_teach(self):
        self.as_role("manager")
        self.assertEqual(self.client.get(f"/api/v1/chats/{self.LEAD}/teach-suggestion").status_code, 403)
        self.assertEqual(self.client.post("/api/v1/chats/teach", json={"when": "x y z", "say": "y"}).status_code, 403)

    def test_a_suggestion_with_an_invented_number_is_dropped(self):
        llm = AsyncMock(return_value='{"when": "someone asks for a discount", "say": "10% discount irukku"}')
        with patch("app.services.ai_reply._llm_chat", llm):
            got = asyncio.run(teach.suggest("Discount?", "5% discount tharom", tenant_id="t1"))
        self.assertIsNone(got)
        llm = AsyncMock(return_value='```json\n{"when": "someone asks for a discount", "say": "5% discount irukku"}\n```')
        with patch("app.services.ai_reply._llm_chat", llm):
            got = asyncio.run(teach.suggest("Discount?", "5% discount tharom", tenant_id="t1"))
        self.assertEqual(got, {"when": "someone asks for a discount", "say": "5% discount irukku"})

    def test_saving_adds_one_line_under_your_job_until_migration_311_is_applied(self):
        """Old path, kept as the fallback while ai_teach_items does not exist yet."""
        saved = {}
        desc = "ABOUT US\nWe sell sarees.\n\nYOUR JOB IN EVERY CONVERSATION\n- Be warm."
        with patch.object(ai_teach, "save_item", side_effect=ai_teach.TableMissing()), \
             patch.object(teach, "get_setting", return_value=desc), \
             patch.object(chat_actions, "save_description", side_effect=lambda db, t, text, reason, uid: saved.update(text=text, reason=reason)), \
             patch("app.routes.ai_tune.queue_rubric_for_description"), \
             patch("app.services.consistency.run_check_safely"):
            res = self.client.post("/api/v1/chats/teach", json={
                "when": "someone asks for a discount on bridal sarees.", "say": "Bridal sarees-ku  5% discount irukku"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(saved["reason"], "edit")
        self.assertIn("YOUR JOB IN EVERY CONVERSATION\n- Be warm.\n- When someone asks for a discount on bridal sarees, "
                      "say: Bridal sarees-ku 5% discount irukku", saved["text"])
        self.assertIn("ABOUT US\nWe sell sarees.", saved["text"])

    def test_a_full_description_refuses_instead_of_overflowing(self):
        full = "YOUR JOB IN EVERY CONVERSATION\n" + "word " * 699
        with patch.object(ai_teach, "save_item", side_effect=ai_teach.TableMissing()), \
             patch.object(teach, "get_setting", return_value=full), \
             patch.object(chat_actions, "save_description") as save:
            res = self.client.post("/api/v1/chats/teach", json={"when": "someone asks a thing", "say": "answer here"})
        self.assertEqual(res.status_code, 422)
        save.assert_not_called()


class RecordPaymentLineTests(unittest.TestCase):
    def test_no_product_is_one_payment_line(self):
        self.assertEqual(record_payment_lines(245000, []), [{"name": "Payment", "qty": 1, "unit_price_paise": 245000}])

    def test_products_add_up_to_the_typed_amount(self):
        items = [{"id": "a", "name": "Green silk saree", "price_paise": 200000},
                 {"id": "b", "name": "Blouse stitching", "price_paise": 50000}]
        lines = record_payment_lines(245000, items)
        self.assertEqual([li["unit_price_paise"] for li in lines], [200000, 45000])
        self.assertEqual(sum(li["unit_price_paise"] for li in lines), 245000)
        self.assertEqual([li["catalog_item_id"] for li in lines], ["a", "b"])

    def test_amount_below_the_other_products_is_refused(self):
        items = [{"id": "a", "name": "Saree", "price_paise": 200000}, {"id": "b", "name": "Blouse", "price_paise": 500}]
        with self.assertRaises(HTTPException):
            record_payment_lines(100000, items)


if __name__ == "__main__":
    unittest.main()
