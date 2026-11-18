"""Customers > Said stop, groups that fill themselves, and the customer page, on the
in-memory fake database. tenant-1 is the caller's; tenant-2 must never be reached.
"""
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import said_stop
from app.services.assignment import _lead_is_open
from tests.fake_supabase import FakeSupabase


def U(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "anril-test:" + name))


NOW = datetime.now(timezone.utc)
ago = lambda days: (NOW - timedelta(days=days)).isoformat()
OWNER = {"tenant_id": "tenant-1", "role": "owner", "user_id": "user-1", "permissions": []}
VIEWER = {"tenant_id": "tenant-1", "role": "member", "user_id": "user-2", "permissions": ["leads.view"]}


def _lead(db, name, tenant_id="tenant-1", **extra):
    row = {"id": U(name), "tenant_id": tenant_id, "name": name, "phone": "+91" + name,
           "created_at": ago(30), "deleted_at": None, "opted_out": None, "whatsapp_undeliverable": None,
           "segment": "C"}
    row.update(extra)
    db.rows("leads").append(row)
    return row


class _Base(unittest.TestCase):
    modules = ("leads", "customer_groups", "said_stop", "customer_profile")

    def setUp(self):
        self.db = FakeSupabase()
        self.patches = [patch(f"app.routes.{m}.get_supabase", return_value=self.db) for m in self.modules]
        self.patches.append(patch("app.routes.said_stop.actor_name", return_value="Meena"))
        for p in self.patches:
            p.start()
        self.ctx = OWNER
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_current_user] = lambda: {"user_id": self.ctx["user_id"]}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()


class SaidStopRouteTests(_Base):
    def setUp(self):
        super().setUp()
        _lead(self.db, "divya", opted_out=True, opted_out_at=ago(2), opted_out_source="stop_reply",
              opted_out_detail="diwali_offer")
        _lead(self.db, "sathya", opted_out=True, opted_out_at=ago(40))
        _lead(self.db, "priya")
        _lead(self.db, "other", tenant_id="tenant-2", opted_out=True, opted_out_at=ago(1))

    def test_list_is_newest_first_and_only_this_tenant(self):
        res = self.client.get("/api/v1/said-stop")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual([p["name"] for p in body["people"]], ["divya", "sathya"])
        self.assertEqual(body["people"][0]["source"], "stop_reply")
        self.assertEqual(body["people"][0]["detail"], "diwali_offer")
        self.assertIsNone(body["people"][1]["source"])  # before we tracked how
        self.assertEqual(body["summary"]["on_list"], 2)
        self.assertEqual(body["summary"]["this_week"], 1)
        self.assertEqual(body["summary"]["this_week_by_source"], {"stop_reply": 1})

    def test_stop_rate_is_none_when_nobody_was_messaged_and_a_percent_otherwise(self):
        self.assertIsNone(self.client.get("/api/v1/said-stop").json()["summary"]["stop_rate"])
        for i in range(4):
            self.db.rows("broadcast_recipients").append(
                {"id": f"r{i}", "tenant_id": "tenant-1", "lead_id": U(f"x{i}"), "created_at": ago(3)})
        self.db.rows("broadcast_recipients").append(
            {"id": "old", "tenant_id": "tenant-1", "lead_id": U("x9"), "created_at": ago(90)})
        summary = self.client.get("/api/v1/said-stop").json()["summary"]
        self.assertEqual(summary["messaged_in_window"], 4)
        self.assertEqual(summary["stopped_in_window"], 1)
        self.assertEqual(summary["stop_rate"], 25.0)

    def test_add_by_hand_records_staff_and_keeps_existing_reasons(self):
        res = self.client.post("/api/v1/said-stop/add", json={"lead_ids": [U("priya"), U("divya"), U("other")]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["added"], 1)
        rows = {r["name"]: r for r in self.db.rows("leads")}
        self.assertTrue(rows["priya"]["opted_out"])
        self.assertEqual(rows["priya"]["opted_out_source"], "staff")
        self.assertEqual(rows["priya"]["opted_out_detail"], "Meena")
        self.assertEqual(rows["priya"]["opted_out_by"], "user-1")
        self.assertEqual(rows["divya"]["opted_out_source"], "stop_reply")  # first reason wins
        self.assertEqual(rows["divya"]["opted_out_at"], self.db.rows("leads")[0]["opted_out_at"])

    def test_remove_by_hand_clears_reason_and_per_product_stops(self):
        self.db.rows("lead_tag_opt_outs").append({"id": "t1", "tenant_id": "tenant-1", "lead_id": U("divya"), "tag_id": "x"})
        self.db.rows("lead_tag_opt_outs").append({"id": "t2", "tenant_id": "tenant-2", "lead_id": U("other"), "tag_id": "x"})
        res = self.client.post("/api/v1/said-stop/remove", json={"lead_ids": [U("divya"), U("other")]})
        self.assertEqual(res.json()["removed"], 1)
        divya = next(r for r in self.db.rows("leads") if r["name"] == "divya")
        self.assertFalse(divya["opted_out"])
        self.assertIsNone(divya["opted_out_at"])
        self.assertIsNone(divya["opted_out_source"])
        self.assertEqual([r["id"] for r in self.db.rows("lead_tag_opt_outs")], ["t2"])
        other = next(r for r in self.db.rows("leads") if r["name"] == "other")
        self.assertTrue(other["opted_out"])

    def test_viewer_can_see_but_not_change(self):
        self.ctx = VIEWER
        self.assertEqual(self.client.get("/api/v1/said-stop").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/said-stop/add", json={"lead_ids": [U("priya")]}).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/said-stop/remove", json={"lead_ids": [U("divya")]}).status_code, 403)


class SaidStopRulesTests(unittest.TestCase):
    def test_record_source_keeps_the_first_reason(self):
        db = FakeSupabase()
        _lead(db, "kumar", opted_out=True, opted_out_source=None)
        said_stop.record_source(db, "tenant-1", U("kumar"), "stop_reply", "diwali_offer")
        said_stop.record_source(db, "tenant-1", U("kumar"), "chat_ai", "not interested")
        row = db.rows("leads")[0]
        self.assertEqual((row["opted_out_source"], row["opted_out_detail"]), ("stop_reply", "diwali_offer"))

    def test_record_source_never_raises(self):
        class Broken:
            def table(self, _):
                raise RuntimeError("column opted_out_source does not exist")
        said_stop.record_source(Broken(), "tenant-1", U("x"), "call", "Arun")

    def test_said_stop_people_are_not_open_for_calls(self):
        self.assertFalse(_lead_is_open({"opted_out": True}))
        self.assertTrue(_lead_is_open({"opted_out": False}))
        self.assertTrue(said_stop.blocks_calls({"opted_out": True}))
        self.assertTrue(said_stop.blocks_calls({"do_not_call": True}))
        self.assertFalse(said_stop.blocks_calls({}))


class RuleGroupTests(_Base):
    def setUp(self):
        super().setUp()
        _lead(self.db, "hot-new", segment="A", created_at=ago(5))
        _lead(self.db, "hot-old", segment="A", created_at=ago(200))
        _lead(self.db, "warm-new", segment="B", created_at=ago(5))
        _lead(self.db, "hot-stopped", segment="A", created_at=ago(5), opted_out=True)
        _lead(self.db, "hot-other-tenant", tenant_id="tenant-2", segment="A", created_at=ago(5))

    def _create(self, rule, name="Hot this month"):
        return self.client.post("/api/v1/customer-groups", json={"name": name, "rule": rule})

    def _members(self, gid, **params):
        res = self.client.get("/api/v1/leads/", params={"group_id": gid, "limit": 50, **params})
        self.assertEqual(res.status_code, 200, res.text)
        return sorted(l["name"] for l in res.json()["data"])

    def test_rule_group_fills_itself_from_the_filters(self):
        res = self._create({"segment": "A", "added_days": 30})
        self.assertEqual(res.status_code, 200, res.text)
        group = res.json()
        self.assertEqual(group["kind"], "rule")
        self.assertEqual(group["rule"], {"segment": "A", "added_days": 30})
        self.assertEqual(group["member_count"], 2)  # hot-new + hot-stopped
        self.assertEqual(group["stop_count"], 1)
        self.assertIn("Hot", group["rule_text"])
        self.assertEqual(self._members(group["id"]), ["hot-new"])

        _lead(self.db, "hot-joined-later", segment="A", created_at=ago(1))
        self.assertEqual(self._members(group["id"]), ["hot-joined-later", "hot-new"])

    def test_page_filter_that_contradicts_the_rule_matches_nobody(self):
        gid = self._create({"segment": "A"}).json()["id"]
        self.assertEqual(self._members(gid, segment="B"), [])
        self.assertEqual(self._members(gid, segment="A"), ["hot-new", "hot-old"])

    def test_rule_can_be_changed_and_members_follow(self):
        gid = self._create({"segment": "A"}).json()["id"]
        res = self.client.put(f"/api/v1/customer-groups/{gid}/rule", json={"rule": {"segment": "B"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self._members(gid), ["warm-new"])

    def test_invalid_rules_are_refused(self):
        self.assertEqual(self._create({}).status_code, 422)
        self.assertEqual(self._create({"broadcast_id": U("b"), "source_filter": "meta_ads"}).status_code, 422)
        self.assertEqual(self._create({"segment": "A", "buyer": True}).status_code, 422)
        self.assertEqual(self._create({"added_days": 0}).status_code, 422)

    def test_picked_group_has_no_rule_and_rule_route_refuses_it(self):
        picked = self.client.post("/api/v1/customer-groups", json={"name": "Picked"}).json()
        self.assertEqual(picked["kind"], "picked")
        self.assertIsNone(picked["rule"])
        res = self.client.put(f"/api/v1/customer-groups/{picked['id']}/rule", json={"rule": {"segment": "A"}})
        self.assertEqual(res.status_code, 400)

    def test_another_tenants_rule_group_matches_nobody(self):
        self.db.rows("customer_groups").append({"id": U("g-other"), "tenant_id": "tenant-2", "name": "x",
                                               "kind": "rule", "rule": {"segment": "A"}})
        self.assertEqual(self._members(U("g-other")), [])


class CustomerProfileTests(_Base):
    def setUp(self):
        super().setUp()
        _lead(self.db, "priya", segment="A", score=82, source="whatsapp", ad_name="Wedding season", created_at=ago(200),
              booked_at=ago(8), booked_for=ago(6))
        _lead(self.db, "other", tenant_id="tenant-2")
        deal = lambda i, stage, total, **kw: self.db.rows("deals").append(
            {"id": f"d{i}", "tenant_id": "tenant-1", "lead_id": U("priya"), "stage": stage, "total_paise": total,
             "created_at": ago(kw.pop("days", 1)), "deal_number": i, **kw})
        deal(1, "won", 1050000, won_at=ago(6), source="walk_in", days=6)
        deal(2, "won", 245000, won_at=ago(80), days=80)
        deal(3, "awaiting_payment", 420000)
        deal(4, "lost", 190000, lost_at=ago(150), lost_reason="bought elsewhere", days=150)
        self.db.rows("deal_items").append({"id": "i1", "tenant_id": "tenant-1", "deal_id": "d1", "name": "Kanchi pattu", "qty": 1})
        for i, (days, direction, ai) in enumerate([(12, "inbound", False), (12, "outbound", True), (3, "inbound", False)]):
            self.db.rows("messages").append({"id": f"m{i}", "tenant_id": "tenant-1", "lead_id": U("priya"),
                                             "created_at": ago(days), "direction": direction, "channel": "whatsapp",
                                             "is_ai_generated": ai})
        self.db.rows("call_logs").append({"id": "c1", "tenant_id": "tenant-1", "lead_id": U("priya"),
                                          "created_at": ago(20), "outcome": "callback", "caller_id": "k1"})
        self.db.rows("callers").append({"id": "k1", "tenant_id": "tenant-1", "name": "Arun"})
        self.db.rows("customer_groups").append({"id": U("vip"), "tenant_id": "tenant-1", "name": "VIP", "kind": "picked"})
        self.db.rows("customer_group_members").append({"group_id": U("vip"), "lead_id": U("priya"), "tenant_id": "tenant-1"})
        self.db.rows("customer_groups").append({"id": U("hot"), "tenant_id": "tenant-1", "name": "Hot people",
                                               "kind": "rule", "rule": {"segment": "A"}})
        self.db.rows("customer_groups").append({"id": U("cold"), "tenant_id": "tenant-1", "name": "Cold people",
                                               "kind": "rule", "rule": {"segment": "C"}})

    def test_totals_timeline_and_groups(self):
        res = self.client.get(f"/api/v1/customer-profile/{U('priya')}")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["totals"]["spent_paise"], 1295000)
        self.assertEqual(body["totals"]["orders_won"], 2)
        self.assertEqual(body["totals"]["average_paise"], 647500)
        self.assertEqual(body["totals"]["to_pay_paise"], 420000)
        self.assertEqual(body["reached_on"]["chat_days"], {"whatsapp": 2})
        self.assertEqual(body["reached_on"]["calls"], 1)
        self.assertEqual(body["reached_on"]["store_bills"], 1)
        kinds = [e["kind"] for e in body["timeline"]]
        self.assertEqual(kinds[0], "order")  # the waiting order, 1 day ago
        self.assertIn("booking", kinds)
        self.assertIn("call", kinds)
        self.assertEqual(kinds[-1], "joined")
        won = next(e for e in body["timeline"] if e["kind"] == "order" and e["number"] == 1)
        self.assertEqual(won["items"], ["Kanchi pattu"])
        call = next(e for e in body["timeline"] if e["kind"] == "call")
        self.assertEqual(call["by"], "Arun")
        self.assertEqual([g["name"] for g in body["groups"]], ["Hot people", "VIP"])
        self.assertFalse(body["said_stop"]["on_list"])

    def test_another_tenants_customer_is_404(self):
        self.assertEqual(self.client.get(f"/api/v1/customer-profile/{U('other')}").status_code, 404)
