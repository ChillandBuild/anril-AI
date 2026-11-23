"""v9.2 AI report card: vs last week, team reply time, chats by result, chats to look at."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ai_setup_report as rep
from tests.fake_supabase import FakeSupabase

T = "t1"
NOW = datetime.now(timezone.utc)
iso = lambda d: d.isoformat()


class ChatResultTests(unittest.TestCase):
    def test_order_of_results(self):
        h = {"L5"}
        self.assertEqual(rep.chat_result({"id": "L1", "converted_at": "x"}, h, NOW), "paid")
        self.assertEqual(rep.chat_result({"id": "L2", "booked_at": "x"}, h, NOW), "booked")
        self.assertEqual(rep.chat_result({"id": "L3", "lost_at": "x"}, h, NOW), "lost")
        self.assertEqual(rep.chat_result({"id": "L5"}, h, NOW), "passed")
        self.assertEqual(rep.chat_result({"id": "L6", "last_inbound_at": iso(NOW - timedelta(days=3))}, h, NOW), "quiet")
        self.assertEqual(rep.chat_result({"id": "L7", "last_inbound_at": iso(NOW - timedelta(hours=3))}, h, NOW), "talking")


class CardTests(unittest.TestCase):
    def test_card_has_the_new_parts(self):
        db = FakeSupabase()
        db.add("leads", id="L1", tenant_id=T, name="Meena", converted_at=None, won_deal_count=0, lost_at=None,
               booked_at=None, last_inbound_at=iso(NOW - timedelta(hours=1)))
        db.add("messages", id="m1", tenant_id=T, lead_id="L1", is_ai_generated=True, direction="outbound",
               created_at=iso(NOW - timedelta(hours=2)), reply_source=None)
        db.add("chat_handovers", id="h1", tenant_id=T, lead_id="L1", status="resolved",
               opened_at=iso(NOW - timedelta(hours=3)), answered_at=iso(NOW - timedelta(hours=3) + timedelta(minutes=40)), reason="x")
        db.add("ai_reply_feedback", tenant_id=T, lead_id="L1", reason="wrong", note="said COD", created_at=iso(NOW - timedelta(hours=1)))
        with patch.object(rep, "_handled", return_value={"chats": 10, "handled_by_aira": 7, "handed_over": 1, "knowledge_gaps": 0}), \
             patch.object(rep, "couldnt_answer", return_value=[]), \
             patch.object(rep, "_ai_revenue", return_value=500000), patch.object(rep, "_ai_paid_count", return_value=2):
            card = rep.report_card(db, T, 7, sees_money=True)
        self.assertEqual(card["previous"]["handled_alone_pct"], 70)
        self.assertEqual(card["previous"]["revenue_from_ai_paise"], 500000)
        self.assertEqual(card["team_reply_min"], 40)
        self.assertEqual(card["results"]["passed"], 1)
        self.assertEqual(card["paid_orders_by_ai"], 2)
        kinds = [p["kind"] for p in card["look_at"]]
        self.assertEqual(kinds, ["wrong", "slow"])
        self.assertEqual(card["look_at"][0]["name"], "Meena")

    def test_money_stays_hidden(self):
        with patch.object(rep, "_handled", return_value={"chats": 0}), patch.object(rep, "couldnt_answer", return_value=[]):
            card = rep.report_card(FakeSupabase(), T, 7, sees_money=False)
        self.assertNotIn("revenue_from_ai_paise", card["previous"])
        self.assertNotIn("paid_orders_by_ai", card)


if __name__ == "__main__":
    unittest.main()
