"""Teach & offers: shared Q&A list, offers with end dates, the prompt block, the API."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import ai_teach as routes
from app.routes import chat_actions
from app.services import ai_teach
from tests.fake_supabase import FakeSupabase

IST = ai_teach.IST
NOW = datetime(2026, 11, 22, 10, 0, tzinfo=IST)     # a Sunday
T = "t1"


def day(offset: int) -> str:
    return (NOW.date() + timedelta(days=offset)).isoformat()


class _Base(unittest.TestCase):
    def setUp(self):
        ai_teach.clear_cache()
        self.db = FakeSupabase()
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.as_role("owner")
        for mod in (routes, chat_actions):
            p = patch.object(mod, "get_supabase", return_value=self.db)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()
        ai_teach.clear_cache()

    def as_role(self, role, permissions=(), tenant="t1"):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": tenant, "role": role, "user_id": "u1", "caller_id": None, "permissions": list(permissions)}


class MatchKeyAndDedupeTests(_Base):
    def test_match_key_ignores_case_punctuation_and_spaces(self):
        self.assertEqual(ai_teach.match_key("  Do you  deliver, to Chennai?? "), "do you deliver to chennai")

    def test_same_question_from_chat_and_couldnt_answer_is_one_row_taught_twice(self):
        ai_teach.save_item(self.db, T, "answer", "Do you deliver to Chennai?", "Yes, 2 days", source="chat")
        ai_teach.save_item(self.db, T, "answer", "do you deliver to chennai", "Yes, in 2 days", source="couldnt_answer")
        rows = self.db.rows("ai_teach_items")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["times_taught"], 2)
        self.assertEqual(rows[0]["reply"], "Yes, in 2 days")

    def test_words_and_answers_do_not_clash(self):
        ai_teach.save_item(self.db, T, "answer", "pattu", "silk answer")
        ai_teach.save_item(self.db, T, "word", "pattu", "silk saree")
        self.assertEqual(len(self.db.rows("ai_teach_items")), 2)

    def test_chat_teach_writes_the_table_not_the_description(self):
        with patch.object(chat_actions, "save_description") as save:
            res = self.client.post("/api/v1/chats/teach", json={
                "when": "someone asks for a discount on bridal sarees", "say": "5% discount irukku"})
        self.assertEqual(res.status_code, 200, res.text)
        save.assert_not_called()
        row = self.db.rows("ai_teach_items")[0]
        self.assertEqual((row["kind"], row["source"], row["tenant_id"]), ("answer", "chat", T))
        self.assertEqual(row["reply"], "5% discount irukku")

    def test_chat_teach_falls_back_to_description_when_table_missing(self):
        with patch.object(ai_teach, "save_item", side_effect=ai_teach.TableMissing()), \
             patch.object(chat_actions.teach, "get_setting", return_value="YOUR JOB IN EVERY CONVERSATION\n- Be warm."), \
             patch.object(chat_actions, "save_description") as save, \
             patch("app.routes.ai_tune.queue_rubric_for_description"), \
             patch("app.services.consistency.run_check_safely"):
            res = self.client.post("/api/v1/chats/teach", json={"when": "someone asks a thing", "say": "answer here"})
        self.assertEqual(res.status_code, 200, res.text)
        save.assert_called_once()


class OfferRuleTests(_Base):
    def make(self, **kw):
        base = dict(title="Diwali sale", details=None, starts_on=None, ends_on=day(5))
        base.update(kw)
        return ai_teach.create_offer(self.db, T, base["title"], base["details"], base["starts_on"],
                                     base["ends_on"], now=NOW)

    def test_end_date_is_required(self):
        with self.assertRaisesRegex(ai_teach.TeachError, "end"):
            self.make(ends_on=None)

    def test_end_not_before_start(self):
        with self.assertRaisesRegex(ai_teach.TeachError, "before"):
            self.make(starts_on=day(3), ends_on=day(2))

    def test_at_most_365_days(self):
        self.make(ends_on=day(365))
        with self.assertRaisesRegex(ai_teach.TeachError, "365"):
            self.make(ends_on=day(366))

    def test_default_start_is_today_ist(self):
        self.assertEqual(self.make()["starts_on"], "2026-11-22")

    def test_end_now_stops_yesterday_for_a_running_offer_and_deletes_one_that_never_ran(self):
        running = self.make(starts_on=day(-3), ends_on=day(2))
        out = ai_teach.end_offer(self.db, T, running["id"], now=NOW)
        self.assertFalse(out["deleted"])
        self.assertEqual(next(r for r in self.db.rows("ai_offers") if r["id"] == running["id"])["ends_on"], day(-1))
        fresh = self.make()    # starts today
        self.assertTrue(ai_teach.end_offer(self.db, T, fresh["id"], now=NOW)["deleted"])
        self.assertTrue(next(r for r in self.db.rows("ai_offers") if r["id"] == fresh["id"])["deleted_at"])

    def test_list_shows_live_upcoming_and_recent_ended_only(self):
        self.make(title="live")
        self.make(title="soon", starts_on=day(4), ends_on=day(8))
        self.db.add("ai_offers", tenant_id=T, title="old", details=None, starts_on=day(-20), ends_on=day(-10), deleted_at=None)
        self.db.add("ai_offers", tenant_id=T, title="ancient", details=None, starts_on=day(-200), ends_on=day(-100), deleted_at=None)
        self.db.add("ai_offers", tenant_id="t2", title="theirs", details=None, starts_on=day(-1), ends_on=day(3), deleted_at=None)
        got = ai_teach.list_offers(self.db, T, now=NOW)
        self.assertEqual([(o["title"], o["status"]) for o in got], [("live", "live"), ("soon", "upcoming"), ("old", "ended")])


class PromptBlockTests(_Base):
    def block(self, now=NOW):
        ai_teach.clear_cache()
        return ai_teach.prompt_block(self.db, T, now)

    def test_empty_tenant_gets_only_the_today_line(self):
        self.assertEqual(self.block(), "\n\nTODAY: Sunday 22 November 2026 (India time).")

    def test_offers_only_while_live_ist_boundary(self):
        self.db.add("ai_offers", tenant_id=T, title="Ends today", details="10% off", starts_on=day(-2), ends_on=day(0), deleted_at=None)
        self.db.add("ai_offers", tenant_id=T, title="Ended", details=None, starts_on=day(-9), ends_on=day(-1), deleted_at=None)
        self.db.add("ai_offers", tenant_id=T, title="Future", details=None, starts_on=day(1), ends_on=day(4), deleted_at=None)
        self.db.add("ai_offers", tenant_id=T, title="Deleted", details=None, starts_on=day(-1), ends_on=day(4), deleted_at="x")
        text = self.block()
        self.assertIn("OFFERS ON NOW (mention only these; never invent offers or dates):", text)
        self.assertIn("- Ends today: 10% off (ends 22 November 2026)", text)
        for gone in ("Ended", "Future", "Deleted"):
            self.assertNotIn(f"- {gone}", text)
        # 00:30 IST on the 23rd is still the 22nd in UTC; the offer that ended on the 22nd must be gone.
        late = datetime(2026, 11, 23, 0, 30, tzinfo=IST)
        self.assertNotIn("Ends today", self.block(late))

    def test_answers_and_words_present_only_when_rows_exist(self):
        ai_teach.save_item(self.db, T, "answer", "Do you deliver?", "Yes, all India")
        ai_teach.save_item(self.db, T, "word", "pattu", "silk saree")
        text = self.block()
        self.assertIn("ANSWERS THE OWNER TAUGHT YOU (use these exact facts when a customer asks something similar):\n"
                      "- Do you deliver? -> Yes, all India", text)
        self.assertIn("WORDS THIS SHOP USES:\n- pattu = silk saree", text)
        self.assertNotIn("OFFERS ON NOW", text)

    def test_other_tenant_rows_never_appear(self):
        ai_teach.save_item(self.db, "t2", "answer", "secret q", "secret a")
        self.assertNotIn("secret", self.block())

    def test_caps(self):
        for i in range(70):
            self.db.add("ai_teach_items", tenant_id=T, kind="answer", prompt=f"q{i}", reply="a", match_key=f"q{i}",
                        updated_at=f"2026-01-01T00:00:{i:02d}")
        self.assertEqual(self.block().count("\n- q"), 60)
        ai_teach.clear_cache()
        self.db.tables["ai_teach_items"] = []
        for i in range(10):
            self.db.add("ai_teach_items", tenant_id=T, kind="answer", prompt=f"q{i}", reply="x" * 900, match_key=f"q{i}",
                        updated_at=f"2026-01-01T00:00:{i:02d}")
        text = self.block()
        self.assertLessEqual(len(text.split("ANSWERS THE OWNER TAUGHT YOU")[1]), 2700)
        self.assertEqual(text.count("\n- q"), 2)

    def test_newest_answer_comes_first(self):
        self.db.add("ai_teach_items", tenant_id=T, kind="answer", prompt="old", reply="a", match_key="old", updated_at="2026-01-01")
        self.db.add("ai_teach_items", tenant_id=T, kind="answer", prompt="new", reply="b", match_key="new", updated_at="2026-02-01")
        text = self.block()
        self.assertLess(text.index("- new ->"), text.index("- old ->"))

    def test_read_error_adds_only_today(self):
        with patch.object(self.db, "table", side_effect=RuntimeError("boom")):
            self.assertEqual(self.block(), "\n\nTODAY: Sunday 22 November 2026 (India time).")

    def test_cached_for_a_minute_then_cleared_by_a_write(self):
        self.block()
        self.db.add("ai_teach_items", tenant_id=T, kind="word", prompt="x", reply="y", match_key="x")
        self.assertNotIn("WORDS", ai_teach.prompt_block(self.db, T, NOW))
        ai_teach.save_item(self.db, T, "word", "z", "w")
        self.assertIn("WORDS", ai_teach.prompt_block(self.db, T, NOW))


class ApiTests(_Base):
    def test_view_permissions(self):
        self.as_role("caller", ["knowledge.view"])
        self.assertEqual(self.client.get("/api/v1/ai-teach/items").status_code, 200)
        self.as_role("caller", ["brain.view"])
        self.assertEqual(self.client.get("/api/v1/ai-teach/offers").status_code, 200)
        self.as_role("caller", ["conversations.view"])
        self.assertEqual(self.client.get("/api/v1/ai-teach/items").status_code, 403)

    def test_edit_needs_knowledge_manage(self):
        self.as_role("caller", ["knowledge.view", "brain.view"])
        self.assertEqual(self.client.post("/api/v1/ai-teach/items", json={"prompt": "a", "reply": "b"}).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/ai-teach/offers", json={"title": "a", "ends_on": day(2)}).status_code, 403)
        self.as_role("caller", ["knowledge.manage"])
        self.assertEqual(self.client.post("/api/v1/ai-teach/items", json={"prompt": "a", "reply": "b"}).status_code, 200)

    def test_item_crud_and_tenant_scope(self):
        made = self.client.post("/api/v1/ai-teach/items", json={"kind": "answer", "prompt": "Open Sunday?", "reply": "Yes 10-6"}).json()
        got = self.client.get("/api/v1/ai-teach/items?kind=answer").json()
        self.assertEqual([g["id"] for g in got], [made["id"]])
        self.assertEqual(self.client.patch(f"/api/v1/ai-teach/items/{made['id']}", json={"reply": "Yes 10-7"}).json()["reply"], "Yes 10-7")
        self.as_role("owner", tenant="t2")
        self.assertEqual(self.client.get("/api/v1/ai-teach/items").json(), [])
        self.assertEqual(self.client.patch(f"/api/v1/ai-teach/items/{made['id']}", json={"reply": "x"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/ai-teach/items/{made['id']}").status_code, 404)
        self.as_role("owner")
        self.assertEqual(self.client.delete(f"/api/v1/ai-teach/items/{made['id']}").status_code, 200)

    def test_editing_into_an_existing_question_is_refused(self):
        self.client.post("/api/v1/ai-teach/items", json={"prompt": "one", "reply": "a"})
        two = self.client.post("/api/v1/ai-teach/items", json={"prompt": "two", "reply": "b"}).json()
        res = self.client.patch(f"/api/v1/ai-teach/items/{two['id']}", json={"prompt": "One!"})
        self.assertEqual(res.status_code, 422)
        self.assertIn("already", res.json()["detail"])

    def test_validation_messages_are_plain_text(self):
        res = self.client.post("/api/v1/ai-teach/items", json={"prompt": " ", "reply": "b"})
        self.assertEqual((res.status_code, res.json()["detail"]), (422, "Write the question first."))
        res = self.client.post("/api/v1/ai-teach/offers", json={"title": "x"})
        self.assertEqual((res.status_code, res.json()["detail"]), (422, "Pick the date this offer ends."))

    def test_offer_api_flow_and_tenant_scope(self):
        end = (datetime.now(IST).date() + timedelta(days=5)).isoformat()
        made = self.client.post("/api/v1/ai-teach/offers", json={"title": "Sale", "ends_on": end}).json()
        self.assertEqual(self.client.get("/api/v1/ai-teach/offers").json()[0]["status"], "live")
        self.as_role("owner", tenant="t2")
        self.assertEqual(self.client.get("/api/v1/ai-teach/offers").json(), [])
        self.assertEqual(self.client.post(f"/api/v1/ai-teach/offers/{made['id']}/end").status_code, 404)
        self.as_role("owner")
        self.assertEqual(self.client.delete(f"/api/v1/ai-teach/offers/{made['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/ai-teach/offers").json(), [])

    def test_table_missing_reads_empty_writes_503(self):
        def boom(*a, **k):
            raise Exception('relation "public.ai_teach_items" does not exist (42P01)')
        with patch.object(self.db, "table", side_effect=boom):
            self.assertEqual(self.client.get("/api/v1/ai-teach/items").json(), [])
            self.assertEqual(self.client.get("/api/v1/ai-teach/offers").json(), [])
            res = self.client.post("/api/v1/ai-teach/items", json={"prompt": "a", "reply": "b"})
            self.assertEqual((res.status_code, res.json()["detail"]), (503, "Teach & offers not ready"))
            res = self.client.post("/api/v1/ai-teach/offers", json={"title": "a", "ends_on": day(3)})
            self.assertEqual(res.status_code, 503)


if __name__ == "__main__":
    unittest.main()
