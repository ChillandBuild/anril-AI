"""Reach confirm step: "This is an offer" creates an ai_offers row once the campaign is sent or scheduled."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ai_teach
from tests import test_reach_pipeline as rp


def end_in(days: int) -> str:
    return (datetime.now(ai_teach.IST).date() + timedelta(days=days)).isoformat()


class ReachOfferTests(rp.ReachBase):
    def setUp(self):
        super().setUp()
        ai_teach.clear_cache()
        self.addCleanup(ai_teach.clear_cache)

    def send(self, **extra):
        body = {"leads": [], "template_name": "diwali", "schedule_type": "now", "group_id": self.group, **extra}
        with patch("app.routes.upload.template_status", return_value="APPROVED"), \
                patch("app.routes.upload.get_best_number", new=AsyncMock(return_value={"id": "n1"})), \
                patch("app.routes.upload._execute_immediate_send", new=AsyncMock()):
            return self.client.post("/api/v1/upload/bulk-send", json=body)

    def test_send_without_the_offer_box_creates_nothing(self):
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.db.rows("ai_offers"), [])

    def test_send_now_with_an_offer_creates_it_linked_to_the_campaign(self):
        res = self.send(offer={"title": "Diwali sale", "ends_on": end_in(7), "details": "20% off silks"})
        self.assertEqual(res.status_code, 200, res.text)
        row = self.db.rows("ai_offers")[0]
        self.assertEqual((row["title"], row["source"], row["tenant_id"], row["ends_on"]),
                         ("Diwali sale", "reach", rp.T1, end_in(7)))
        self.assertEqual(row["broadcast_ref"], res.json()["broadcast_id"])

    def test_scheduled_send_with_an_offer_creates_it(self):
        res = self.send(schedule_type="scheduled", schedule_at=rp.now_iso(days=1),
                        offer={"title": "Weekend sale", "ends_on": end_in(9)})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.db.rows("ai_offers")[0]["broadcast_ref"], self.db.rows("scheduled_broadcasts")[0]["id"])

    def test_a_bad_offer_date_is_refused_before_anything_is_sent(self):
        with patch("app.routes.upload._execute_immediate_send", new=AsyncMock()):
            res = self.send(offer={"title": "Sale", "ends_on": "not a date"})
        self.assertEqual(res.status_code, 422, res.text)
        self.assertIn("Offer:", res.json()["detail"])
        self.assertEqual(self.db.rows("ai_offers"), [])
        self.assertEqual(self.db.rows("scheduled_broadcasts"), [])

    def test_a_scheduled_offer_starts_the_day_the_campaign_goes_out(self):
        res = self.send(schedule_type="scheduled", schedule_at=rp.now_iso(days=3),
                        offer={"title": "Weekend sale", "ends_on": end_in(9)})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.db.rows("ai_offers")[0]["starts_on"], end_in(3))

    def test_an_offer_ending_before_the_scheduled_send_is_refused(self):
        res = self.send(schedule_type="scheduled", schedule_at=rp.now_iso(days=5),
                        offer={"title": "Weekend sale", "ends_on": end_in(2)})
        self.assertEqual(res.status_code, 422, res.text)
        self.assertEqual(self.db.rows("scheduled_broadcasts"), [])

    def test_someone_who_cannot_teach_the_ai_cannot_add_an_offer(self):
        with patch("app.routes.upload._has_permission", side_effect=lambda ctx, p: p != "knowledge.manage"):
            res = self.send(offer={"title": "Sale", "ends_on": end_in(3)})
        self.assertEqual(res.status_code, 403, res.text)
        self.assertEqual(self.db.rows("ai_offers"), [])

    def test_a_refused_send_creates_no_offer(self):
        res = self.send(group_id=rp.U("theirs"), offer={"title": "Sale", "ends_on": end_in(3)})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.db.rows("ai_offers"), [])


if __name__ == "__main__":
    unittest.main()
