"""Reach results: "Paid within 7 days" per campaign (services/reach_results.py), on the fake database."""
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.reach_results import paid_within_window
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
SENT = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 30, tzinfo=timezone.utc)


def at(days=0, hours=0) -> str:
    return (SENT + timedelta(days=days, hours=hours)).isoformat()


class PaidWithinWindowTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.campaign = [{"broadcast_id": "b1", "sent_at": SENT.isoformat()}]

    def lead(self, lead_id, phone, tenant=T1):
        self.db.rows("leads").append({"id": lead_id, "tenant_id": tenant, "phone": phone})

    def recipient(self, lead_id, phone, broadcast="b1", sent_at=None, tenant=T1, status="sent"):
        self.db.rows("broadcast_recipients").append({
            "id": str(uuid.uuid4()), "tenant_id": tenant, "broadcast_id": broadcast, "lead_id": lead_id,
            "phone": phone, "send_status": status, "created_at": sent_at or SENT.isoformat()})

    def deal(self, lead_id, paise, won_at, stage="won", tenant=T1, created_at=None):
        self.db.rows("deals").append({
            "id": str(uuid.uuid4()), "tenant_id": tenant, "lead_id": lead_id, "stage": stage,
            "total_paise": paise, "won_at": won_at, "created_at": created_at or won_at})

    def run_it(self, include_amount=True, campaigns=None):
        return paid_within_window(self.db, T1, campaigns or self.campaign, include_amount=include_amount, now=NOW)

    def test_counts_a_person_once_with_their_first_order_only(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001")
        self.deal("L1", 150000, at(days=1))       # first order: this one counts, Rs 1,500
        self.deal("L1", 999900, at(days=2))       # second order: ignored
        out = self.run_it()["b1"]
        self.assertEqual((out["paid_count"], out["paid_amount_inr"]), (1, 1500))

    def test_an_order_outside_seven_days_is_excluded(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001")
        self.deal("L1", 100000, at(days=7, hours=1))     # just after the window
        self.deal("L1", 200000, at(hours=-1))             # before the send
        out = self.run_it()["b1"]
        self.assertEqual((out["paid_count"], out["paid_amount_inr"]), (0, 0))

    def test_the_last_hour_of_the_window_still_counts(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001")
        self.deal("L1", 50000, at(days=6, hours=23))
        self.assertEqual(self.run_it()["b1"]["paid_count"], 1)

    def test_only_paid_orders_count_not_quotes_or_lost(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001")
        self.deal("L1", 100000, at(days=1), stage="quoted")
        self.deal("L1", 100000, at(days=1), stage="lost")
        self.assertEqual(self.run_it()["b1"]["paid_count"], 0)

    def test_a_deal_with_no_won_at_falls_back_to_created_at(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001")
        self.deal("L1", 70000, None, created_at=at(days=2))
        out = self.run_it()["b1"]
        self.assertEqual((out["paid_count"], out["paid_amount_inr"]), (1, 700))

    def test_each_person_window_starts_at_their_own_send_time(self):
        # The campaign ran over two days: L2 was sent to a day later than the history stamp.
        for lead_id, phone in (("L1", "+919000000001"), ("L2", "+919000000002")):
            self.lead(lead_id, phone)
        self.recipient("L1", "+919000000001")
        self.recipient("L2", "+919000000002", sent_at=at(days=1))
        self.deal("L1", 10000, at(days=7, hours=2))       # outside L1's window
        self.deal("L2", 20000, at(days=7, hours=2))       # inside L2's (sent a day later)
        out = self.run_it()["b1"]
        self.assertEqual((out["paid_count"], out["paid_amount_inr"]), (1, 200))

    def test_money_is_hidden_without_deals_view_but_the_count_stays(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001")
        self.deal("L1", 150000, at(days=1))
        out = self.run_it(include_amount=False)["b1"]
        self.assertEqual(out["paid_count"], 1)
        self.assertIsNone(out["paid_amount_inr"])

    def test_nothing_is_attributed_across_tenants(self):
        self.lead("L1", "+919000000001")
        self.lead("X1", "+919000000001", tenant=T2)
        self.recipient("L1", "+919000000001")
        self.recipient("X1", "+919000000001", tenant=T2)
        self.deal("X1", 500000, at(days=1), tenant=T2)             # tenant-2's sale to the same phone
        self.assertEqual(self.run_it()["b1"]["paid_count"], 0)

    def test_only_people_who_were_sent_to_count(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001", status="failed")
        self.deal("L1", 100000, at(days=1))
        self.assertEqual(self.run_it()["b1"]["paid_count"], 0)

    def test_an_uploaded_contact_without_a_lead_id_is_matched_by_phone(self):
        self.lead("L1", "+919000000001")
        self.recipient(None, "+919000000001")
        self.deal("L1", 100000, at(days=3))
        self.assertEqual(self.run_it()["b1"]["paid_count"], 1)

    def test_two_campaigns_are_judged_separately(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001", broadcast="b1")
        self.recipient("L1", "+919000000001", broadcast="b2", sent_at=at(days=20))
        self.deal("L1", 100000, at(days=2))                        # inside b1's window only
        campaigns = self.campaign + [{"broadcast_id": "b2", "sent_at": at(days=20)}]
        out = self.run_it(campaigns=campaigns)
        self.assertEqual((out["b1"]["paid_count"], out["b2"]["paid_count"]), (1, 0))

    def test_the_window_is_marked_open_while_the_seven_days_are_running(self):
        out = paid_within_window(self.db, T1, self.campaign, include_amount=True, now=SENT + timedelta(days=3))
        self.assertTrue(out["b1"]["paid_window_open"])
        self.assertFalse(self.run_it()["b1"]["paid_window_open"])

    def test_no_orders_at_all_is_zero_without_further_lookups(self):
        self.lead("L1", "+919000000001")
        self.recipient("L1", "+919000000001")
        self.assertEqual(self.run_it()["b1"]["paid_count"], 0)


if __name__ == "__main__":
    unittest.main()
