"""Anril Setup (v9.2 #23): Couldn't answer grouping, answering, thumbs-down, report card, scoring view."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import ai_setup as routes
from app.services import ai_setup_report as svc
from app.services import ai_teach
from app.services.brain.handovers import classify_reason
from app.services.deal_turn import TEAM_CLAIM_REASON
from tests.fake_supabase import FakeSupabase

T = "t1"
NOW = datetime.now(timezone.utc)


def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


class _Base(unittest.TestCase):
    def setUp(self):
        ai_teach.clear_cache()
        self.db = FakeSupabase()
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.as_role("owner")
        p = patch.object(routes, "get_supabase", return_value=self.db)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()
        ai_teach.clear_cache()

    def as_role(self, role, permissions=(), tenant=T, caller_id=None):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": tenant, "role": role, "user_id": "u1", "caller_id": caller_id,
            "permissions": list(permissions)}

    def gap(self, hid, lead, question, hours_ago, tenant=T, **extra):
        """A knowledge-gap handover plus the customer's message just before it."""
        self.db.add("messages", id=f"m-{hid}", tenant_id=tenant, lead_id=lead, direction="inbound",
                    content=question, created_at=ago(hours_ago + 0.01))
        return self.db.add("chat_handovers", id=hid, tenant_id=tenant, lead_id=lead,
                           reason=TEAM_CLAIM_REASON, opened_at=ago(hours_ago), **extra)


class GroupingTests(_Base):
    def test_same_question_in_different_case_and_punctuation_is_one_group(self):
        self.gap("h1", "l1", "Do you have size 42?", 5)
        self.gap("h2", "l2", "do you have SIZE 42", 3)
        self.gap("h3", "l3", "Is it open on Sunday", 2)
        out = svc.couldnt_answer(self.db, T, 30)
        self.assertEqual([g["count"] for g in out], [2, 1])
        self.assertEqual(out[0]["question"], "do you have SIZE 42")  # the newest wording
        self.assertEqual(sorted(out[0]["sample_lead_ids"]), ["l1", "l2"])

    def test_other_handover_reasons_and_other_tenants_are_left_out(self):
        self.gap("h1", "l1", "Price?", 4)
        self.gap("h9", "l9", "Secret", 4, tenant="t2")
        self.db.add("messages", id="mx", tenant_id=T, lead_id="l5", direction="inbound", content="Talk to a person",
                    created_at=ago(4))
        self.db.add("chat_handovers", id="hx", tenant_id=T, lead_id="l5", reason="User requested a human agent",
                    opened_at=ago(3.9))
        self.assertEqual(classify_reason("User requested a human agent"), "asked_for_human")
        out = svc.couldnt_answer(self.db, T, 30)
        self.assertEqual([g["question"] for g in out], ["Price?"])

    def test_old_handovers_outside_the_period_are_left_out(self):
        self.gap("h1", "l1", "Old question", 24 * 40)
        self.assertEqual(svc.couldnt_answer(self.db, T, 30), [])
        self.assertEqual(len(svc.couldnt_answer(self.db, T, 90)), 1)

    def test_answered_handovers_do_not_show(self):
        self.gap("h1", "l1", "Delivery charge?", 5, answered_at=ago(1))
        self.assertEqual(svc.couldnt_answer(self.db, T, 30), [])

    def test_hides_lead_ids_without_conversations_permission(self):
        self.gap("h1", "l1", "Price?", 4)
        out = svc.couldnt_answer(self.db, T, 30, show_leads=False)
        self.assertEqual(out[0]["sample_lead_ids"], [])

    def test_caller_sees_only_their_handovers(self):
        self.gap("h1", "l1", "Mine", 4, assigned_to="c1")
        self.gap("h2", "l2", "Not mine", 4, assigned_to="c2")
        out = svc.couldnt_answer(self.db, T, 30, caller_id="c1")
        self.assertEqual([g["question"] for g in out], ["Mine"])

    def test_question_comes_from_the_message_before_the_handover_not_after(self):
        self.gap("h1", "l1", "First question", 6)
        self.db.add("messages", id="late", tenant_id=T, lead_id="l1", direction="inbound", content="Later chat",
                    created_at=ago(1))
        out = svc.couldnt_answer(self.db, T, 30)
        self.assertEqual(out[0]["question"], "First question")

    def test_group_questions_pure_orders_by_count_then_newest(self):
        rows = [{"id": "a", "lead_id": "l1", "opened_at": ago(9)}, {"id": "b", "lead_id": "l2", "opened_at": ago(1)},
                {"id": "c", "lead_id": "l3", "opened_at": ago(2)}]
        out = svc.group_questions(rows, {"a": "X?", "b": "Y?", "c": "y"})
        self.assertEqual([g["count"] for g in out], [2, 1])
        self.assertEqual(out[0]["key"], "y")


class AnswerTests(_Base):
    def test_answer_saves_to_teach_and_marks_handovers(self):
        self.gap("h1", "l1", "Delivery charge?", 5)
        self.gap("h2", "l2", "delivery charge", 3)
        self.gap("h3", "l3", "Open Sunday?", 3)
        res = self.client.post("/api/v1/ai-setup/couldnt-answer/answer",
                               json={"question": "Delivery charge?", "answer": "Free above 500 rupees."})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["marked_answered"], 2)
        items = ai_teach.list_items(self.db, T, "answer")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "couldnt_answer")
        done = {r["id"]: r.get("answered_at") for r in self.db.rows("chat_handovers")}
        self.assertTrue(done["h1"] and done["h2"])
        self.assertFalse(done.get("h3"))
        left = self.client.get("/api/v1/ai-setup/couldnt-answer?period=30d").json()["questions"]
        self.assertEqual([q["question"] for q in left], ["Open Sunday?"])

    def test_answering_the_same_question_twice_is_one_teach_row(self):
        for text in ("First", "Second"):
            self.client.post("/api/v1/ai-setup/couldnt-answer/answer", json={"question": "Price?", "answer": text})
        self.assertEqual(len(ai_teach.list_items(self.db, T, "answer")), 1)

    def test_empty_answer_is_refused_in_plain_words(self):
        res = self.client.post("/api/v1/ai-setup/couldnt-answer/answer", json={"question": "Price?", "answer": " "})
        self.assertEqual(res.status_code, 422)
        self.assertIn("answer", res.json()["detail"])

    def test_answering_needs_knowledge_manage(self):
        self.as_role("staff", ["knowledge.view"])
        res = self.client.post("/api/v1/ai-setup/couldnt-answer/answer", json={"question": "Q?", "answer": "A"})
        self.assertEqual(res.status_code, 403)

    def test_viewing_needs_knowledge_view(self):
        self.as_role("staff", ["leads.view"])
        self.assertEqual(self.client.get("/api/v1/ai-setup/couldnt-answer").status_code, 403)

    def test_bad_period_is_a_400(self):
        self.assertEqual(self.client.get("/api/v1/ai-setup/couldnt-answer?period=forever").status_code, 400)
        self.assertEqual(self.client.get("/api/v1/ai-setup/report-card?period=400d").status_code, 400)


class FeedbackTests(_Base):
    def setUp(self):
        super().setUp()
        self.db.add("messages", id="ai1", tenant_id=T, lead_id="l1", direction="outbound", is_ai_generated=True,
                    content="Hello", created_at=ago(2))
        self.db.add("messages", id="hu1", tenant_id=T, lead_id="l1", direction="outbound", is_ai_generated=False,
                    content="Hi", created_at=ago(2))
        self.db.add("messages", id="other", tenant_id="t2", lead_id="l9", direction="outbound",
                    is_ai_generated=True, content="x", created_at=ago(2))

    def post(self, message_id="ai1", reason="wrong", **extra):
        return self.client.post("/api/v1/ai-setup/reply-feedback",
                                json={"message_id": message_id, "reason": reason, **extra})

    def test_thumbs_down_saved_with_lead_from_the_message(self):
        res = self.post(note="Wrong price")
        self.assertEqual(res.status_code, 200)
        row = self.db.rows("ai_reply_feedback")[0]
        self.assertEqual((row["lead_id"], row["reason"], row["created_by"]), ("l1", "wrong", "u1"))

    def test_second_click_by_same_person_changes_the_reason_not_adds_a_row(self):
        self.post(reason="wrong")
        self.post(reason="rude")
        rows = self.db.rows("ai_reply_feedback")
        self.assertEqual([r["reason"] for r in rows], ["rude"])

    def test_undo_removes_only_my_row(self):
        self.post()
        self.db.add("ai_reply_feedback", tenant_id=T, message_id="ai1", reason="wrong", created_by="u2")
        self.assertEqual(self.client.delete("/api/v1/ai-setup/reply-feedback/ai1").status_code, 200)
        self.assertEqual([r["created_by"] for r in self.db.rows("ai_reply_feedback")], ["u2"])

    def test_only_ai_replies_of_my_business_can_be_marked(self):
        self.assertEqual(self.post("hu1").status_code, 422)
        self.assertEqual(self.post("other").status_code, 404)
        self.assertEqual(self.post("missing").status_code, 404)

    def test_bad_reason_and_long_note_refused(self):
        self.assertEqual(self.post(reason="boring").status_code, 422)
        self.assertEqual(self.post(note="x" * 301).status_code, 422)

    def test_conversations_view_is_enough(self):
        self.as_role("staff", ["conversations.view"])
        self.assertEqual(self.post().status_code, 200)
        self.as_role("staff", ["leads.view"])
        self.assertEqual(self.post().status_code, 403)

    def test_caller_cannot_mark_a_reply_in_someone_elses_chat(self):
        self.db.add("leads", id="l1", tenant_id=T, assigned_to="c2")
        self.as_role("caller", ["conversations.view"], caller_id="c1")
        self.assertEqual(self.post().status_code, 404)


class ReportCardTests(_Base):
    def setUp(self):
        super().setUp()
        for i in range(4):  # 4 chats; 3 answered by the AI, one of those passed to a person
            self.db.add("messages", tenant_id=T, lead_id=f"l{i}", direction="inbound", content="hi", created_at=ago(5))
            if i < 3:
                self.db.add("messages", tenant_id=T, lead_id=f"l{i}", direction="outbound", is_ai_generated=True,
                            reply_source="ai", content="hello", created_at=ago(4))
        self.db.add("chat_handovers", tenant_id=T, lead_id="l0", reason=TEAM_CLAIM_REASON, opened_at=ago(3))
        self.db.add("messages", id="mq", tenant_id=T, lead_id="l0", direction="inbound", content="Is it waterproof?",
                    created_at=ago(3.01))

    def test_numbers(self):
        self.db.add("ai_reply_feedback", tenant_id=T, message_id="a", reason="wrong", created_by="u1", created_at=ago(2))
        self.db.add("ai_reply_feedback", tenant_id=T, message_id="b", reason="rude", created_by="u1", created_at=ago(2))
        self.db.add("ai_reply_feedback", tenant_id="t2", message_id="c", reason="wrong", created_by="u9", created_at=ago(2))
        card = self.client.get("/api/v1/ai-setup/report-card?period=30d").json()
        self.assertEqual(card["chats"], 4)
        self.assertEqual(card["passed_to_person"], 1)
        self.assertEqual(card["handled_alone_pct"], 50)  # 2 of 4 answered with no handover
        self.assertEqual(card["couldnt_answer"], 1)  # the one handover that was a missing answer
        self.assertEqual(card["wrong_answers"], 1)  # only "wrong"; rude/too long are tone, not wrong answers
        kinds = [f["kind"] for f in card["fix_these"]]
        self.assertEqual(kinds[:2], ["couldnt_answer", "wrong_answers"])
        self.assertIn("tone", kinds)
        first = card["fix_these"][0]
        self.assertTrue(first["href"].startswith("/dashboard/brain/couldnt-answer?question=Is%20it%20waterproof"))

    def test_money_only_with_deals_view(self):
        self.db.add("deals", tenant_id=T, stage="won", won_at=ago(2), total_paise=118000, gst_paise=18000,
                    sold_by_ai=True)
        self.db.add("deals", tenant_id=T, stage="won", won_at=ago(2), total_paise=50000, gst_paise=0,
                    sold_by_ai=False)
        card = self.client.get("/api/v1/ai-setup/report-card").json()
        self.assertEqual(card["revenue_from_ai_paise"], 100000)
        self.as_role("staff", ["knowledge.view"])
        card = self.client.get("/api/v1/ai-setup/report-card").json()
        self.assertNotIn("revenue_from_ai_paise", card)
        self.assertTrue(card["money_hidden"])

    def test_empty_business_has_no_percentage_and_no_crash(self):
        self.as_role("owner", tenant="t-empty")
        card = self.client.get("/api/v1/ai-setup/report-card").json()
        self.assertEqual((card["chats"], card["handled_alone_pct"], card["wrong_answers"]), (0, None, 0))
        self.assertEqual(card["couldnt_answer"], 0)
        self.assertEqual(card["fix_these"], [])

    def test_couldnt_answer_is_zero_when_the_counts_are_missing(self):
        with patch.object(svc, "_handled", return_value={"chats": 3, "handled_by_aira": 2, "handed_over": 1}):
            card = svc.report_card(self.db, T, 30, sees_money=False)
        self.assertEqual(card["couldnt_answer"], 0)

    def test_missing_feedback_table_does_not_crash(self):
        with patch.object(svc, "fetch_bounded", side_effect=Exception("42P01 relation does not exist")):
            card = svc.report_card(self.db, T, 30, sees_money=False)
        self.assertEqual(card["wrong_answers"], 0)

    def test_fix_these_is_empty_when_all_is_well_and_capped(self):
        self.assertEqual(svc.fix_these([], {}, 0), [])
        many = svc.fix_these([{"question": "q" * 200, "count": 3}] * 4, {"wrong": 2, "rude": 1}, 2)
        self.assertLessEqual(len(many), svc.FIX_CAP)
        self.assertIn("...", many[0]["text"])


class ScoringTests(_Base):
    def test_read_only_view_in_plain_words(self):
        body = self.client.get("/api/v1/ai-setup/scoring").json()
        self.assertTrue(body["read_only"])
        self.assertEqual(body["note"], "Editing comes later.")
        self.assertEqual([l["label"] for l in body["levels"]], ["Hot", "Warm", "Cold", "Not interested"])
        self.assertEqual([l["points"] for l in body["levels"]], ["8 to 10", "4 to 7", "1 to 3", "0"])
        self.assertIn("not interested", body["not_interested_words"])
        self.assertIn("don't contact", body["not_interested_words"])
        self.assertFalse(any("\\" in w for w in body["not_interested_words"]))

    def test_owner_own_examples_are_shown_under_the_right_level(self):
        rubric = "- Hot: asks for a quote; wants a site visit\n- Cold: just says hi"
        with patch("app.config_dynamic.get_setting", return_value=rubric):
            body = svc.scoring_view(T)
        by = {l["key"]: l["your_examples"] for l in body["levels"]}
        self.assertEqual(by["hot"], ["asks for a quote", "wants a site visit"])
        self.assertEqual(by["cold"], ["just says hi"])
        self.assertEqual(by["warm"], [])

    def test_old_numeric_rubric_is_converted(self):
        with patch("app.config_dynamic.get_setting", return_value="9-10: ready to pay\n7-8: asks details"):
            body = svc.scoring_view(T)
        by = {l["key"]: l["your_examples"] for l in body["levels"]}
        self.assertEqual(by["hot"], ["ready to pay"])
        self.assertEqual(by["warm"], ["asks details"])

    def test_needs_knowledge_view(self):
        self.as_role("staff", ["leads.view"])
        self.assertEqual(self.client.get("/api/v1/ai-setup/scoring").status_code, 403)


if __name__ == "__main__":
    unittest.main()
