"""Engage > Inbound leads list, counts and download (/api/v1/inbound-leads) on the fake database.

tenant-1 is the caller's; tenant-2 must never show. Results follow Chats' inbox order:
Came / Paid (converted or a won order) > Lost > Booked > none. Waiting = their message is the latest.
"""
import csv
import io
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from tests.fake_supabase import FakeSupabase

NOW = datetime.now(timezone.utc)
ago = lambda hours: (NOW - timedelta(hours=hours)).isoformat()


class InboundLeadsListTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.db.rpc = lambda name, params: type("R", (), {"execute": lambda s: type("D", (), {"data": []})()})()

        def lead(lid, **extra):
            row = {"id": lid, "tenant_id": "tenant-1", "name": lid, "phone": "+91" + lid, "source": "whatsapp",
                   "segment": "C", "score": 10, "created_at": ago(48), "deleted_at": None, "ad_campaign_id": None,
                   "ai_enabled": True, "last_inbound_at": None}
            row.update(extra)
            self.db.rows("leads").append(row)

        def msg(lid, hours, direction, ai=False, content="hi"):
            self.db.rows("messages").append({"id": f"{lid}-{hours}-{direction}", "tenant_id": "tenant-1", "lead_id": lid,
                                             "created_at": ago(hours), "direction": direction,
                                             "is_ai_generated": ai, "content": content})

        lead("priya", segment="A", booked_at=ago(5), booked_for=ago(-48), assigned_to="k1", last_inbound_at=ago(2),
             collected_data={"Business name": "Priya Boutique", "City": "Coimbatore"})
        msg("priya", 3, "outbound", ai=True)
        msg("priya", 2, "inbound", content="Saturday 11 AM visit varen")
        lead("suresh", segment="A", lost_at=ago(30), last_inbound_at=ago(20))
        msg("suresh", 20, "inbound")
        msg("suresh", 19, "outbound")
        self.db.rows("deals").append({"id": "d1", "tenant_id": "tenant-1", "lead_id": "suresh", "stage": "won",
                                      "total_paise": 450000, "deal_number": 1042, "won_at": ago(10)})
        lead("divya", segment="C", lost_at=ago(10), lost_reason="Just looking", last_inbound_at=ago(40))
        msg("divya", 40, "inbound")
        msg("divya", 39, "outbound")
        lead("meena", segment="B", last_inbound_at=ago(1), ai_enabled=False)
        msg("meena", 1, "inbound", content="Tamil-la reply pannuma?")
        lead("upload", source="upload", segment="A")
        lead("other", tenant_id="tenant-2", segment="A", last_inbound_at=ago(1))

        self.db.rows("callers").append({"id": "k1", "tenant_id": "tenant-1", "name": "Karthik"})
        self.patch = patch("app.routes.inbound_leads.get_supabase", return_value=self.db)
        self.patch.start()
        app.dependency_overrides[get_tenant_id] = lambda: "tenant-1"
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "tenant-1", "role": "owner", "user_id": "u1", "permissions": []}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.patch.stop()

    def _list(self, **params):
        res = self.client.get("/api/v1/inbound-leads/", params=params)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_rows_carry_result_reply_handler_and_form_details(self):
        rows = {r["id"]: r for r in self._list()["data"]}
        self.assertEqual(set(rows), {"priya", "suresh", "divya", "meena"})  # no upload, no other tenant
        priya = rows["priya"]
        self.assertEqual(priya["result"], "booked")
        self.assertEqual(priya["handled_by"], {"kind": "person", "name": "Karthik", "needs_you": False})
        self.assertEqual(priya["last_message"]["content"], "Saturday 11 AM visit varen")
        self.assertEqual(priya["waiting_since"], ago(2)[:13] + priya["waiting_since"][13:])
        self.assertEqual((priya["business"], priya["city"]), ("Priya Boutique", "Coimbatore"))
        self.assertEqual(rows["suresh"]["result"], "paid")  # a won order beats Lost
        self.assertEqual(rows["suresh"]["order"]["number"], 1042)
        self.assertIsNone(rows["suresh"]["waiting_since"])
        self.assertEqual(rows["divya"]["result"], "lost")
        self.assertEqual(rows["meena"]["handled_by"]["kind"], "nobody")  # AI off, nobody assigned
        self.assertIsNone(rows["meena"]["business"])

    def test_result_and_waiting_filters(self):
        ids = lambda **p: sorted(r["id"] for r in self._list(**p)["data"])
        self.assertEqual(ids(result="paid"), ["suresh"])
        self.assertEqual(ids(result="lost"), ["divya"])
        self.assertEqual(ids(result="booked"), ["priya"])
        self.assertEqual(ids(result="none"), ["meena"])
        self.assertEqual(ids(waiting="true"), ["meena", "priya"])
        self.assertEqual(ids(search="boutique"), [])  # search is name / phone / ad, not form answers
        self.assertEqual(ids(search="mee"), ["meena"])

    def test_waiting_sort_puts_the_longest_wait_first(self):
        rows = self._list(sort="waiting")["data"]
        self.assertEqual([r["id"] for r in rows[:2]], ["priya", "meena"])

    def test_summary_counts_each_chip_group_without_its_own_filter(self):
        res = self.client.get("/api/v1/inbound-leads/summary", params={"segment": "A"})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["segments"], {"A": 2, "B": 1, "C": 1, "D": 0})
        self.assertEqual(body["results"], {"booked": 1, "paid": 1, "lost": 0})  # within Hot
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["waiting"], 1)  # Hot and waiting: priya
        self.assertEqual(body["booked_or_paid"], 2)

    def test_export_matches_the_list_and_has_the_new_columns(self):
        res = self.client.get("/api/v1/inbound-leads/export", params={"result": "paid"})
        self.assertEqual(res.status_code, 200, res.text)
        rows = list(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
        self.assertEqual([r["name"] for r in rows], ["suresh"])
        for column in ("business", "city", "result", "booking_date", "handled_by", "last_message_date"):
            self.assertIn(column, rows[0])
        self.assertEqual(rows[0]["result"], "Came / Paid")

    def test_one_ad_filter_keeps_the_people_who_messaged_from_that_ad(self):
        for lid, ad in (("priya", "111"), ("suresh", "111"), ("suresh", "222"), ("meena", "222")):
            self.db.rows("lead_meta_ad_attributions").append({"tenant_id": "tenant-1", "lead_id": lid, "meta_ad_id": ad})
        data = self._list(meta_ad_id="111")
        self.assertEqual({r["id"] for r in data["data"]}, {"priya", "suresh"})
        self.assertEqual(data["total"], 2)
        summary = self.client.get("/api/v1/inbound-leads/summary", params={"meta_ad_id": "222"}).json()
        self.assertEqual((summary["total"], summary["results"]["paid"]), (2, 1))
        # Meta ad ids are digits only; anything else is refused before it reaches a query.
        self.assertEqual(self.client.get("/api/v1/inbound-leads/", params={"meta_ad_id": "1,2"}).status_code, 422)

    def test_tag_filter_matches_ignoring_case_and_stays_in_the_tenant(self):
        for lid, tag, tenant in (("priya", "VIP", "tenant-1"), ("meena", "VIP", "tenant-1"), ("suresh", "Wedding", "tenant-1"),
                                 ("other", "VIP", "tenant-2")):
            self.db.rows("lead_tags").append({"tenant_id": tenant, "lead_id": lid, "tag": tag})
        ids = lambda **p: sorted(r["id"] for r in self._list(**p)["data"])
        self.assertEqual(ids(tag="vip"), ["meena", "priya"])
        self.assertEqual(ids(tag="  Wedding "), ["suresh"])
        self.assertEqual(ids(tag="nobody-has-this"), [])  # an unused tag matches nobody, not everybody
        self.assertEqual(self._list(tag="VIP")["total"], 2)
        summary = self.client.get("/api/v1/inbound-leads/summary", params={"tag": "VIP"}).json()
        self.assertEqual(summary["segments"], {"A": 1, "B": 1, "C": 0, "D": 0})
        self.assertEqual(self.client.get("/api/v1/inbound-leads/", params={"tag": "x" * 31}).status_code, 422)

    def test_ads_list_is_one_per_meta_ad_and_names_campaigns_only_for_twins(self):
        self.db.rows("ad_campaigns").extend([
            {"id": "c1", "tenant_id": "tenant-1", "campaign_name": "Diwali"},
            {"id": "c2", "tenant_id": "tenant-1", "campaign_name": "Pongal"},
        ])
        for meta_id, label, campaign, channels in (
            ("1", "Free reading", "c1", ["whatsapp"]), ("1", "Free reading", "c1", ["whatsapp"]),
            ("2", "Free reading", "c2", ["whatsapp"]), ("3", "Astro offer", "c1", ["instagram"]),
            ("4", "Website ad", "c1", []),
        ):
            self.db.rows("ad_creatives").append({"tenant_id": "tenant-1", "meta_ad_id": meta_id, "creative_label": label,
                                                 "campaign_id": campaign, "messaging_channels": channels})
        self.db.rows("ad_creatives").append({"tenant_id": "tenant-2", "meta_ad_id": "9", "creative_label": "Theirs",
                                             "campaign_id": None, "messaging_channels": ["whatsapp"]})
        ads = self.client.get("/api/v1/inbound-leads/ads").json()["data"]
        self.assertEqual(ads, [
            {"meta_ad_id": "3", "name": "Astro offer"},
            {"meta_ad_id": "1", "name": "Free reading · Diwali"},
            {"meta_ad_id": "2", "name": "Free reading · Pongal"},
        ])


class InboundInsightsMoneyTests(InboundLeadsListTests):
    """v9.2: the Wants column, the What they want / Why lost tabs, and today's money cards."""

    def test_rows_say_what_they_want(self):
        for r in self.db.rows("leads"):
            if r["id"] == "meena":
                r["collected_data"] = {"wants": "Silk saree"}
        rows = {r["id"]: r for r in self._list()["data"]}
        self.assertEqual(rows["meena"]["wants"], "Silk saree")
        self.assertIsNone(rows["divya"]["wants"])

    def test_insights_group_wants_and_lost_reasons(self):
        for r in self.db.rows("leads"):
            if r["id"] in ("priya", "meena"):
                r["collected_data"] = {"wants": " silk  saree " if r["id"] == "priya" else "Silk saree"}
            if r["id"] == "suresh":
                r["lost_reason"] = "Just looking · came twice"
            if r["id"] == "divya":
                r["lost_reason"] = "Just looking · wants cotton"
        res = self.client.get("/api/v1/inbound-leads/insights")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["wants"], [{"text": "silk saree", "count": 2, "hot": 1}])
        # suresh paid later, so only divya counts as lost (the note after " · " is grouped away)
        self.assertEqual(body["lost"], [{"text": "Just looking", "count": 1}])
        self.assertEqual((body["with_wants"], body["lost_total"]), (2, 1))

    def test_money_today_splits_link_and_store(self):
        today = NOW.isoformat()
        self.db.rows("deal_payments").extend([
            {"tenant_id": "tenant-1", "amount_paise": 245000, "method": "razorpay", "paid_at": today},
            {"tenant_id": "tenant-1", "amount_paise": 85000, "method": "cash", "paid_at": today},
            {"tenant_id": "tenant-1", "amount_paise": 99900, "method": "cash", "paid_at": ago(72)},
            {"tenant_id": "tenant-2", "amount_paise": 1, "method": "cash", "paid_at": today},
        ])
        self.db.rows("deals").append({"id": "d2", "tenant_id": "tenant-1", "lead_id": "meena", "channel": "store",
                                      "created_at": today, "stage": "won"})
        res = self.client.get("/api/v1/inbound-leads/money-today")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual((body["link_paid_paise"], body["link_payments"]), (245000, 1))
        self.assertEqual((body["store_paid_paise"], body["money_in_paise"]), (85000, 330000))
        self.assertEqual((body["store_orders"], body["store_matched"], body["store_new"]), (1, 1, 0))

    def test_money_today_needs_deals_view(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "tenant-1", "role": "member", "user_id": "u2", "permissions": ["leads.view"]}
        self.assertEqual(self.client.get("/api/v1/inbound-leads/money-today").status_code, 403)
