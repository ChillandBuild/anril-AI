"""v9.2: details the AI agent saves from the chat (budget, what they want...), and the team's edits on the About panel."""
import asyncio
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
from app.services import lead_details
from tests.fake_supabase import FakeSupabase

T = "t1"
LEAD = "11111111-1111-4111-8111-111111111111"


def _db(business_type="Boutique", **lead) -> FakeSupabase:
    db = FakeSupabase()
    db.add("tenants", id=T, business_type=business_type)
    db.add("leads", **{"id": LEAD, "tenant_id": T, "collected_data": {}, "detail_sources": {}, "deleted_at": None,
                       "assigned_to": None, **lead})
    return db


def _lead(db) -> dict:
    return next(r for r in db.rows("leads") if r["id"] == LEAD)


class AiSaveTests(unittest.TestCase):
    def test_saves_known_fields_marked_from_chat(self):
        db = _db()
        self.assertTrue(lead_details.ai_save(db, T, LEAD, {"budget": " ₹15,000 ", "wants": "Bridal saree", "colour": "x"}))
        lead = _lead(db)
        self.assertEqual(lead["collected_data"], {"budget": "₹15,000", "wants": "Bridal saree"})
        self.assertEqual(lead["detail_sources"]["budget"]["by"], "ai")
        self.assertNotIn("colour", lead["collected_data"])  # not a known field

    def test_updates_its_own_value_when_the_customer_changes_their_mind(self):
        db = _db(collected_data={"budget": "₹15,000"}, detail_sources={"budget": {"by": "ai"}})
        lead_details.ai_save(db, T, LEAD, {"budget": "₹20,000"})
        self.assertEqual(_lead(db)["collected_data"]["budget"], "₹20,000")

    def test_never_writes_over_a_team_edit_a_cleared_one_or_a_form_answer(self):
        db = _db(collected_data={"budget": "₹10,000", "city": "Madurai"},
                 detail_sources={"budget": {"by": "staff", "name": "Karthik"},
                                 "wants": {"by": "staff", "cleared": True}})
        changed = lead_details.ai_save(db, T, LEAD, {"budget": "₹20,000", "city": "Coimbatore", "wants": "Saree"})
        self.assertFalse(changed)
        self.assertEqual(_lead(db)["collected_data"], {"budget": "₹10,000", "city": "Madurai"})

    def test_a_form_answer_of_any_shape_is_kept(self):
        db = _db(collected_data={"city": ["Coimbatore"]})
        self.assertFalse(lead_details.ai_save(db, T, LEAD, {"city": "Madurai"}))
        self.assertEqual(_lead(db)["collected_data"]["city"], ["Coimbatore"])

    def test_real_estate_fields_only_for_real_estate(self):
        db = _db()
        lead_details.ai_save(db, T, LEAD, {"bhk": "2BHK"})
        self.assertNotIn("bhk", _lead(db)["collected_data"])
        db = _db(business_type="Real Estate")
        lead_details.ai_save(db, T, LEAD, {"bhk": "2BHK", "needs_loan": "Yes"})
        self.assertEqual(_lead(db)["collected_data"], {"bhk": "2BHK", "needs_loan": "Yes"})

    def test_another_business_lead_is_left_alone(self):
        db = _db()
        self.assertFalse(lead_details.ai_save(db, "t2", LEAD, {"budget": "₹1"}))
        self.assertEqual(_lead(db)["collected_data"], {})


class ReadAndSaveTests(unittest.TestCase):
    def test_reads_the_chat_and_saves_what_the_model_found(self):
        db = _db()
        seen = {}

        async def fake_llm(prompt):
            seen["prompt"] = prompt
            return 'Here: {"budget": "₹15,000", "needed_by": "January", "made_up": "x"}'

        thread = [{"direction": "outbound", "content": "Budget evlo?"}, {"direction": "inbound", "content": "Hi"}]
        values = asyncio.run(lead_details.read_and_save(db, T, LEAD, thread, "15,000 kulla venum, Jan wedding",
                                                        llm=fake_llm))
        self.assertEqual(values, {"budget": "₹15,000", "needed_by": "January"})
        self.assertEqual(_lead(db)["collected_data"]["needed_by"], "January")
        # oldest first, ending with the customer's latest message
        chat = seen["prompt"].split("Chat (oldest first):")[1]
        self.assertLess(chat.index("Customer: Hi"), chat.index("Business: Budget evlo?"))
        self.assertTrue(chat.strip().endswith("Customer: 15,000 kulla venum, Jan wedding"))

    def test_bad_model_output_saves_nothing_and_never_raises(self):
        for answer in ("no json here", "[1, 2]", "{broken", ""):
            with self.subTest(answer=answer):
                db = _db()

                async def fake_llm(_prompt, a=answer):
                    return a

                self.assertEqual(asyncio.run(lead_details.read_and_save(db, T, LEAD, [], "hello", llm=fake_llm)), {})
                self.assertEqual(_lead(db)["collected_data"], {})

    def test_a_lone_emoji_is_not_read(self):
        with patch.object(lead_details, "read_and_save") as read:
            lead_details.save_in_background(_db(), T, LEAD, [], "👍")
        read.assert_not_called()


class DetailsRouteTests(unittest.TestCase):
    def setUp(self):
        self.db = _db(collected_data={"budget": "₹15,000", "company": "Acme"}, detail_sources={"budget": {"by": "ai"}})
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.as_role("owner")
        p = patch.object(lead_routes, "get_supabase", return_value=self.db)
        p.start()
        self.addCleanup(p.stop)
        a = patch.object(lead_routes, "actor_name", return_value="Karthik")
        a.start()
        self.addCleanup(a.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def as_role(self, role, permissions=(), caller_id=None, tenant=T):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": tenant, "role": role, "user_id": "u1", "caller_id": caller_id, "permissions": list(permissions)}

    def test_view_lists_values_with_who_set_them(self):
        res = self.client.get(f"/api/v1/leads/{LEAD}/details")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        by_key = {f["key"]: f for f in body["fields"]}
        self.assertEqual(by_key["budget"]["by"], "ai")
        self.assertEqual(by_key["company"]["by"], "form")
        self.assertEqual(body["fields"][0]["key"], "budget")  # known fields first
        self.assertIn("wants", [a["key"] for a in body["addable"]])
        self.assertNotIn("budget", [a["key"] for a in body["addable"]])

    def test_team_edit_is_kept_with_the_name_and_blocks_the_ai(self):
        res = self.client.patch(f"/api/v1/leads/{LEAD}/details", json={"key": "budget", "value": "₹12,000"})
        self.assertEqual(res.status_code, 200)
        field = next(f for f in res.json()["fields"] if f["key"] == "budget")
        self.assertEqual((field["value"], field["by"], field["name"]), ("₹12,000", "staff", "Karthik"))
        lead_details.ai_save(self.db, T, LEAD, {"budget": "₹99"})
        self.assertEqual(_lead(self.db)["collected_data"]["budget"], "₹12,000")

    def test_empty_value_clears_it(self):
        res = self.client.patch(f"/api/v1/leads/{LEAD}/details", json={"key": "budget", "value": "  "})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("budget", _lead(self.db)["collected_data"])

    def test_unknown_key_and_too_long_value_are_refused(self):
        self.assertEqual(self.client.patch(f"/api/v1/leads/{LEAD}/details",
                                           json={"key": "shoe_size", "value": "9"}).status_code, 422)
        self.assertEqual(self.client.patch(f"/api/v1/leads/{LEAD}/details",
                                           json={"key": "budget", "value": "x" * 121}).status_code, 422)

    def test_other_business_and_other_telecaller_get_404(self):
        self.as_role("owner", tenant="t2")
        self.assertEqual(self.client.get(f"/api/v1/leads/{LEAD}/details").status_code, 404)
        self.as_role("caller", permissions=["leads.view", "leads.manage"], caller_id="c9")
        self.assertEqual(self.client.get(f"/api/v1/leads/{LEAD}/details").status_code, 404)

    def test_editing_needs_leads_manage(self):
        self.as_role("manager", permissions=["leads.view"])
        self.assertEqual(self.client.get(f"/api/v1/leads/{LEAD}/details").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/v1/leads/{LEAD}/details",
                                           json={"key": "budget", "value": "1"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
