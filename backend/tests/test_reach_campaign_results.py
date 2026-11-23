"""Reach: no scheduling between 9 PM and 9 AM India time, and one campaign's results
(back per Re 1, said stop, who paid), on the fake database."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.dependencies.tenant import get_tenant_id
from app.main import app
from tests import test_reach_pipeline as rp
from tests.test_reach_pipeline import OWNER, REACH_ONLY, T1, T2, U

IST = timezone(timedelta(hours=5, minutes=30))


def at_ist(hour: int, minute: int = 0, days: int = 1) -> str:
    day = datetime.now(IST).date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST).isoformat()


class ScheduleHoursTests(rp.ReachBase):
    def send(self, **extra):
        body = {"leads": [], "template_name": "diwali", "group_id": self.group, **extra}
        with patch("app.routes.upload.template_status", return_value="APPROVED"), \
                patch("app.routes.upload.get_best_number", new=AsyncMock(return_value={"id": "n1"})), \
                patch("app.routes.upload._execute_immediate_send", new=AsyncMock()) as run:
            return self.client.post("/api/v1/upload/bulk-send", json=body), run

    def scheduled(self, iso):
        return self.send(schedule_type="scheduled", schedule_at=iso)[0]

    def test_night_times_are_refused_with_a_plain_message(self):
        for hour, minute in ((21, 0), (22, 30), (23, 59), (0, 0), (3, 15), (8, 59)):
            res = self.scheduled(at_ist(hour, minute))
            self.assertEqual(res.status_code, 400, (hour, minute))
            self.assertIn("between 9 AM and 9 PM India time", res.json()["detail"])
        self.assertEqual(self.db.rows("scheduled_broadcasts"), [])

    def test_day_times_go_through_including_both_edges(self):
        for hour, minute in ((9, 0), (12, 0), (20, 59)):
            self.assertEqual(self.scheduled(at_ist(hour, minute)).status_code, 200, (hour, minute))
        self.assertEqual(len(self.db.rows("scheduled_broadcasts")), 3)

    def test_the_hour_is_judged_in_india_time_not_utc(self):
        # 22:00 IST is 16:30 UTC (day time in UTC); 08:00 IST is 02:30 UTC.
        self.assertEqual(self.scheduled(at_ist(22)).status_code, 400)
        self.assertEqual(self.scheduled(datetime.fromisoformat(at_ist(10)).astimezone(timezone.utc).isoformat()).status_code, 200)

    def test_sending_now_is_not_held_to_the_hours(self):
        with patch("app.routes.upload.datetime") as fake_dt:
            fake_dt.now.return_value = datetime(2026, 11, 24, 18, 0, tzinfo=timezone.utc)  # 23:30 IST
            fake_dt.fromisoformat.side_effect = datetime.fromisoformat
            res, run = self.send(schedule_type="now")
        self.assertEqual(res.status_code, 200, res.text)

    def test_a_drip_send_time_at_night_is_refused_a_day_time_is_fine(self):
        night = self.send(schedule_type="drip", drip_days=2, drip_send_time="22:00")[0]
        self.assertEqual(night.status_code, 400)
        self.assertIn("9 AM and 9 PM", night.json()["detail"])
        self.assertEqual(self.db.rows("scheduled_broadcasts"), [])
        ok = self.send(schedule_type="drip", drip_days=2, drip_send_time="10:30")[0]
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_a_drip_with_no_send_time_is_left_alone(self):
        res = self.send(schedule_type="drip", drip_days=2)[0]
        self.assertEqual(res.status_code, 200, res.text)


class CampaignResultsTests(rp.ReachBase):
    def setUp(self):
        super().setUp()
        self.sent_at = datetime.now(timezone.utc) - timedelta(days=2)
        self.db.rows("app_settings").append({"tenant_id": T1, "key": "broadcast_history", "value": json.dumps([
            {"broadcast_id": "h1", "timestamp": self.sent_at.isoformat(), "template_name": "t", "sent": 10},
            {"broadcast_id": "h0", "timestamp": self.sent_at.isoformat(), "template_name": "t", "sent": 0},
        ])})
        for i, name in enumerate(("ann", "bob", "eli")):
            self.db.rows("broadcast_recipients").append({
                "id": f"r{i}", "tenant_id": T1, "broadcast_id": "h1", "lead_id": U(name), "phone": f"+91900000000{i}",
                "send_status": "sent", "created_at": self.sent_at.isoformat(),
                "opted_out_at": self.sent_at.isoformat() if name == "bob" else None})
        # a stop on another campaign and another tenant's row must not count
        self.db.rows("broadcast_recipients").append({
            "id": "x1", "tenant_id": T1, "broadcast_id": "other", "lead_id": U("fay"), "phone": "+919000000006",
            "send_status": "sent", "created_at": self.sent_at.isoformat(), "opted_out_at": self.sent_at.isoformat()})
        self.db.rows("broadcast_recipients").append({
            "id": "x2", "tenant_id": T2, "broadcast_id": "h1", "lead_id": "z", "phone": "+919000000099",
            "send_status": "sent", "created_at": self.sent_at.isoformat(), "opted_out_at": self.sent_at.isoformat()})
        self.deal("d1", "ann", 4150000, days=1)
        self.deal("d2", "eli", 100000, days=3)

    def deal(self, did, lead, paise, days):
        when = (self.sent_at + timedelta(days=days)).isoformat()
        self.db.rows("deals").append({"id": did, "tenant_id": T1, "lead_id": U(lead), "stage": "won",
                                      "total_paise": paise, "won_at": when, "created_at": when})

    def results(self, bid="h1"):
        return self.client.get(f"/api/v1/upload/broadcast/{bid}/results")

    def test_an_owner_gets_the_money_the_stop_count_and_who_paid(self):
        res = self.results()
        self.assertEqual(res.status_code, 200, res.text)
        out = res.json()
        cost = round(10 * settings.meta_marketing_rate_inr, 2)
        self.assertEqual((out["sent"], out["said_stop"], out["paid_count"]), (10, 1, 2))
        self.assertEqual(out["paid_amount_inr"], 42500)
        self.assertEqual(out["cost_inr"], cost)
        self.assertEqual(out["back_per_rupee"], round(42500 / cost, 2))
        self.assertEqual([(p["name"], p["paid_inr"]) for p in out["paid_people"]], [("ann", 41500), ("eli", 1000)])
        self.assertEqual(out["paid_people"][0]["phone"], "+919000000001")

    def test_without_deals_view_there_are_no_rupees_anywhere(self):
        self.ctx = {**REACH_ONLY, "permissions": ["outbound_leads.view"]}
        out = self.results().json()
        self.assertEqual((out["paid_count"], out["said_stop"], len(out["paid_people"])), (2, 1, 2))
        for key in ("paid_amount_inr", "cost_inr", "rate_inr", "back_per_rupee"):
            self.assertNotIn(key, out)
        self.assertTrue(all("paid_inr" not in p for p in out["paid_people"]))

    def test_a_campaign_nobody_paid_for_has_an_empty_list_and_no_ratio(self):
        self.db.rows("deals").clear()
        out = self.results().json()
        self.assertEqual((out["paid_count"], out["paid_people"], out["back_per_rupee"]), (0, [], 0.0))

    def test_zero_sent_means_no_ratio(self):
        out = self.results("h0").json()
        self.assertEqual((out["sent"], out["cost_inr"], out["back_per_rupee"]), (0, 0.0, None))

    def test_another_tenants_or_unknown_campaign_is_a_404(self):
        self.assertEqual(self.results("nope").status_code, 404)
        # tenant 2 asking for tenant 1's campaign id gets nothing: the history is read per tenant
        app.dependency_overrides[get_tenant_id] = lambda: T2
        self.assertEqual(self.results("h1").status_code, 404)

    def test_the_history_list_carries_said_stop_and_the_ratio(self):
        rows = {h["broadcast_id"]: h for h in self.client.get("/api/v1/upload/history").json()["data"]}
        self.assertEqual(rows["h1"]["said_stop"], 1)
        self.assertEqual(rows["h1"]["back_per_rupee"], round(42500 / round(10 * settings.meta_marketing_rate_inr, 2), 2))
        self.ctx = {**REACH_ONLY, "permissions": ["outbound_leads.view"]}
        rows = {h["broadcast_id"]: h for h in self.client.get("/api/v1/upload/history").json()["data"]}
        self.assertEqual(rows["h1"]["said_stop"], 1)
        self.assertNotIn("back_per_rupee", rows["h1"])


if __name__ == "__main__":
    unittest.main()
