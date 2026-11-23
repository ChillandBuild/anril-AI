"""Customers > Groups routes (/api/v1/customer-groups) on the in-memory fake database.

Two tenants: tenant-1 is the caller's, tenant-2 owns a group and leads the caller must
never reach. Routes are reached through TestClient with the tenant context overridden.
"""
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.routes import customer_groups as groups_routes
from tests.fake_supabase import FakeSupabase

def U(name: str) -> str:
    """A stable UUID for a readable test name (the routes accept only real UUIDs)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "anril-test:" + name))

OWNER = {"tenant_id": "tenant-1", "role": "owner", "user_id": "user-1", "permissions": []}
CALLER = {"tenant_id": "tenant-1", "role": "caller", "user_id": "user-2", "permissions": ["leads.view"]}


def _lead(db, lead_id, tenant_id="tenant-1", deleted=False):
    db.rows("leads").append({"id": lead_id, "tenant_id": tenant_id, "name": lead_id,
                             "created_at": "2026-01-01T00:00:00+00:00",
                             "phone": "+91" + lead_id, "deleted_at": "2026-01-01" if deleted else None,
                             "opted_out": None, "whatsapp_undeliverable": None})


class CustomerGroupsRouteTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        _lead(self.db, U("lead-own-1"))
        _lead(self.db, U("lead-own-2"))
        _lead(self.db, U("lead-own-deleted"), deleted=True)
        _lead(self.db, U("lead-other"), tenant_id="tenant-2")
        self.other_group = {"id": U("group-other"), "tenant_id": "tenant-2", "name": "Other tenant",
                            "kind": "picked", "created_at": "2026-01-01T00:00:00"}
        self.db.rows("customer_groups").append(self.other_group)

        self.patches = [patch("app.routes.customer_groups.get_supabase", return_value=self.db)]
        for p in self.patches:
            p.start()
        self.ctx = OWNER
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()

    def _create(self, name):
        return self.client.post("/api/v1/customer-groups", json={"name": name})

    def test_create_returns_a_picked_group_with_no_members(self):
        res = self._create("  Wedding enquiries  ")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["name"], "Wedding enquiries")
        self.assertEqual(body["kind"], "picked")
        self.assertEqual(body["member_count"], 0)
        self.assertIn("id", body)
        self.assertIn("created_at", body)
        stored = self.db.rows("customer_groups")[-1]
        self.assertEqual(stored["tenant_id"], "tenant-1")
        self.assertEqual(stored["created_by"], "user-1")

    def test_duplicate_name_is_409_ignoring_case_and_spaces(self):
        self.assertEqual(self._create("Wedding").status_code, 200)
        res = self._create("  wedding ")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"], "A group with this name already exists")

    def test_name_must_be_1_to_80_characters_after_trimming(self):
        self.assertEqual(self._create("   ").status_code, 422)
        self.assertEqual(self._create("x" * 81).status_code, 422)
        self.assertEqual(self._create("x" * 80).status_code, 200)

    def test_list_is_newest_first_and_counts_only_live_members(self):
        first = self._create("First").json()
        second = self._create("Second").json()
        self.client.post(f"/api/v1/customer-groups/{second['id']}/members",
                         json={"lead_ids": [U("lead-own-1"), U("lead-own-deleted")]})
        res = self.client.get("/api/v1/customer-groups")
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertEqual([r["name"] for r in rows], ["Second", "First"])
        self.assertEqual(rows[0]["member_count"], 1)
        self.assertEqual(rows[1]["member_count"], 0)
        self.assertEqual(rows[1]["id"], first["id"])
        self.assertEqual(set(rows[0]), {"id", "name", "kind", "rule", "rule_text", "member_count", "stop_count", "made_by", "created_at",
                                       "spend_hidden", "used_by"})

    def test_one_failing_count_does_not_break_the_list(self):
        self._create("Fine")
        bad = self._create("Broken").json()
        real = groups_routes._count

        def flaky(db, ctx, gid, opted_out_only):
            if gid == bad["id"]:
                raise RuntimeError("function total_spent_paise does not exist")
            return real(db, ctx, gid, opted_out_only)

        with patch.object(groups_routes, "_count", flaky):
            res = self.client.get("/api/v1/customer-groups")
        self.assertEqual(res.status_code, 200)
        by_name = {r["name"]: r for r in res.json()}
        self.assertTrue(by_name["Broken"]["count_unknown"])
        self.assertNotIn("count_unknown", by_name["Fine"])

    def test_rename_follows_the_same_duplicate_rule(self):
        self._create("Alpha")
        beta = self._create("Beta").json()
        res = self.client.patch(f"/api/v1/customer-groups/{beta['id']}", json={"name": "alpha"})
        self.assertEqual(res.status_code, 409)
        res = self.client.patch(f"/api/v1/customer-groups/{beta['id']}", json={"name": "Gamma"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "Gamma")

    def test_add_members_takes_only_own_live_leads(self):
        group = self._create("Picked").json()
        res = self.client.post(f"/api/v1/customer-groups/{group['id']}/members",
                               json={"lead_ids": [U("lead-own-1"), U("lead-other"), U("lead-own-deleted"), "not-a-uuid"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"added": 1})
        members = [(m["group_id"], m["lead_id"]) for m in self.db.rows("customer_group_members")]
        self.assertEqual(members, [(group["id"], U("lead-own-1"))])

    def test_adding_the_same_lead_twice_keeps_one_row(self):
        group = self._create("Picked").json()
        url = f"/api/v1/customer-groups/{group['id']}/members"
        self.client.post(url, json={"lead_ids": [U("lead-own-1")]})
        self.client.post(url, json={"lead_ids": [U("lead-own-1"), U("lead-own-2")]})
        self.assertEqual(len(self.db.rows("customer_group_members")), 2)

    def test_remove_members_returns_how_many_went(self):
        group = self._create("Picked").json()
        url = f"/api/v1/customer-groups/{group['id']}/members"
        self.client.post(url, json={"lead_ids": [U("lead-own-1"), U("lead-own-2")]})
        res = self.client.request("DELETE", url, json={"lead_ids": [U("lead-own-1"), U("lead-other")]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"removed": 1})
        self.assertEqual([m["lead_id"] for m in self.db.rows("customer_group_members")], [U("lead-own-2")])

    def test_another_tenants_group_is_404_everywhere(self):
        url = f"/api/v1/customer-groups/{U('group-other')}"
        self.assertEqual(self.client.patch(url, json={"name": "Stolen"}).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(self.client.post(f"{url}/members", json={"lead_ids": [U("lead-own-1")]}).status_code, 404)
        self.assertEqual(self.client.request("DELETE", f"{url}/members", json={"lead_ids": [U("lead-own-1")]}).status_code, 404)
        self.assertEqual(self.db.rows("customer_group_members"), [])
        self.assertEqual(self.other_group["name"], "Other tenant")

    def test_rule_group_refuses_hand_added_members(self):
        self.db.rows("customer_groups").append({"id": U("group-rule"), "tenant_id": "tenant-1", "name": "Rule",
                                                "kind": "rule", "rule": {"segment": "A"}})
        res = self.client.post(f"/api/v1/customer-groups/{U('group-rule')}/members", json={"lead_ids": [U("lead-own-1")]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], "This group fills itself")

    def test_caller_can_list_but_not_change_groups(self):
        self._create("Owned by owner")
        self.ctx = CALLER
        self.assertEqual(self.client.get("/api/v1/customer-groups").status_code, 200)
        self.assertEqual(self._create("Mine").status_code, 403)


class LeadsCustomerFieldsTests(unittest.TestCase):
    """The list and the summary, over one small book of leads."""

    def setUp(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        ago = lambda days: (now - timedelta(days=days)).isoformat()
        self.db = FakeSupabase()
        for lead_id in (U("L1"), U("L2"), U("L3"), U("L4")):
            _lead(self.db, lead_id)
        self.db.rows("leads")[0]["ad_name"] = "Diwali Reel"
        self.db.rows("leads")[1]["converted_at"] = ago(200)
        self.db.rows("leads")[2]["booked_at"] = ago(1)
        _lead(self.db, U("L5"))
        self.db.rows("leads")[-1]["opted_out"] = True
        _lead(self.db, U("L6"), deleted=True)
        _lead(self.db, U("T2"), tenant_id="tenant-2")
        self.db.rows("leads")[-1]["converted_at"] = ago(1)

        deal = lambda i, lead, stage, total, won_at, tenant="tenant-1": self.db.rows("deals").append(
            {"id": f"d{i}", "tenant_id": tenant, "lead_id": lead, "stage": stage, "total_paise": total, "won_at": won_at})
        deal(1, U("L1"), "won", 50000, ago(10))
        deal(2, U("L1"), "won", 30000, ago(5))
        deal(3, U("L3"), "won", 10000, ago(1))
        deal(4, U("L4"), "lost", 99999, ago(1))
        deal(5, U("T2"), "won", 1, ago(1), tenant="tenant-2")

        self.db.rows("customer_groups").append({"id": U("g1"), "tenant_id": "tenant-1", "name": "Wedding",
                                               "kind": "picked"})
        self.db.rows("customer_group_members").append({"group_id": U("g1"), "lead_id": U("L1"), "tenant_id": "tenant-1"})

        self.patches = [patch("app.routes.leads.get_supabase", return_value=self.db)]
        for p in self.patches:
            p.start()
        app.dependency_overrides[get_tenant_and_role] = lambda: OWNER
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()

    def test_summary_counts_buyers_repeat_quiet_and_said_stop(self):
        res = self.client.get("/api/v1/leads/summary")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {
            "people": 4,          # L1 L2 L3 L4 (L5 said stop, L6 deleted, T2 another tenant)
            "leads": 1,           # L4
            "buyers": 3,          # L1 won twice, L2 converted, L3 booked and won once
            "repeat_buyers": 1,   # L1
            "spent_paise": 90000,  # 50000 + 30000 + 10000; the lost deal is not spent
            "not_back_90": 1,     # L2: last purchase 200 days ago
            "said_stop": 1,       # L5
        })

    def test_summary_applies_the_same_filters_as_the_list(self):
        res = self.client.get("/api/v1/leads/summary", params={"buyer": "true"})
        self.assertEqual(res.json()["people"], 3)
        self.assertEqual(res.json()["leads"], 0)
        res = self.client.get("/api/v1/leads/summary", params={"buyer": "false"})
        self.assertEqual(res.json()["people"], 1)
        self.assertEqual(res.json()["buyers"], 0)

    def test_list_adds_buyer_spend_groups_and_activity(self):
        res = self.client.get("/api/v1/leads/", params={"limit": 200})
        self.assertEqual(res.status_code, 200, res.text)
        by_id = {row["id"]: row for row in res.json()["data"]}
        l1 = by_id[U("L1")]
        self.assertTrue(l1["is_buyer"])
        self.assertEqual(l1["spent_paise"], 80000)
        self.assertEqual(l1["groups"], [{"id": U("g1"), "name": "Wedding"}])
        self.assertIsNone(l1["broadcast_score"])
        self.assertFalse(by_id[U("L4")]["is_buyer"])
        self.assertEqual(by_id[U("L4")]["spent_paise"], 0)
        self.assertEqual(by_id[U("L4")]["groups"], [])
        self.assertEqual(by_id[U("L4")]["last_activity_at"], by_id[U("L4")]["created_at"])

    def test_list_filters_by_group_and_by_buyer(self):
        res = self.client.get("/api/v1/leads/", params={"group_id": U("g1")})
        self.assertEqual([r["id"] for r in res.json()["data"]], [U("L1")])
        res = self.client.get("/api/v1/leads/", params={"group_id": "not-a-uuid"})
        self.assertEqual(res.json()["total"], 0)
        res = self.client.get("/api/v1/leads/", params={"buyer": "true"})
        self.assertEqual(res.json()["total"], 3)

    def test_export_csv_has_the_customer_columns_and_filters(self):
        import csv
        import io

        res = self.client.get("/api/v1/leads/export", params={"buyer": "true"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["content-disposition"], "attachment; filename=leads_all.csv")
        rows = list(csv.DictReader(io.StringIO(res.text)))
        self.assertEqual(list(rows[0].keys()), ["Name", "Phone", "Status", "Interest", "Came from", "Ad",
                                                "Assigned to", "Spent", "Groups", "Added", "Last message"])
        by_name = {r["Name"]: r for r in rows}
        self.assertEqual(set(by_name), {U("L1"), U("L2"), U("L3")})
        self.assertEqual(by_name[U("L1")]["Status"], "Buyer")
        self.assertEqual(by_name[U("L1")]["Spent"], "800.00")
        self.assertEqual(by_name[U("L1")]["Groups"], "Wedding")
        self.assertEqual(by_name[U("L1")]["Ad"], "Diwali Reel")
        self.assertEqual(by_name[U("L2")]["Groups"], "")

    def test_export_of_non_owner_is_refused(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "tenant-1", "role": "caller",
                                                                 "user_id": "user-2", "permissions": []}
        self.assertEqual(self.client.get("/api/v1/leads/export").status_code, 403)

    def test_search_reaches_people_through_ad_campaign_and_broadcast_names(self):
        self.db.rows("ad_campaigns").append({"id": "camp-1", "tenant_id": "tenant-1", "campaign_name": "Winter Sale"})
        self.db.rows("leads")[1]["ad_campaign_id"] = "camp-1"  # L2
        self.db.rows("scheduled_broadcasts").append({"id": "b1", "tenant_id": "tenant-1", "template_name": "festive_offer"})
        self.db.rows("broadcast_recipients").append({"tenant_id": "tenant-1", "broadcast_id": "b1",
                                                     "lead_id": U("L3"), "send_status": "sent"})
        self.db.rows("broadcast_recipients").append({"tenant_id": "tenant-1", "broadcast_id": "b1",
                                                     "lead_id": U("L4"), "send_status": "failed"})

        ids = lambda term: sorted(r["id"] for r in self.client.get("/api/v1/leads/", params={"search": term}).json()["data"])
        self.assertEqual(ids("Diwali"), [U("L1")])     # ad name
        self.assertEqual(ids("winter"), [U("L2")])     # ad campaign name
        self.assertEqual(ids("festive"), [U("L3")])    # sent broadcast; the failed send does not count
        self.assertEqual(ids(U("L4")), [U("L4")])         # plain name match still works

    def test_repeat_and_quiet_cards_filter_the_list_and_the_summary(self):
        # L1: two won deals, last 5 days ago (repeat, not quiet). L2: converted 200 days ago
        # (quiet). L3: booked yesterday (neither). Same rules as the summary's card numbers.
        ids = lambda bought: sorted(r["id"] for r in self.client.get("/api/v1/leads/", params={"bought": bought}).json()["data"])
        self.assertEqual(ids("repeat"), [U("L1")])
        self.assertEqual(ids("quiet"), [U("L2")])
        summary = self.client.get("/api/v1/leads/summary", params={"bought": "repeat"}).json()
        self.assertEqual((summary["people"], summary["repeat_buyers"]), (1, 1))
        summary = self.client.get("/api/v1/leads/summary", params={"bought": "quiet"}).json()
        self.assertEqual((summary["people"], summary["not_back_90"]), (1, 1))
        self.assertEqual(self.client.get("/api/v1/leads/", params={"bought": "other"}).status_code, 422)

    def test_broadcast_picker_filters_in_the_database(self):
        # Source → Broadcast is an inner embed on broadcast_recipients, not an id list in the
        # URL (PostgREST refuses ~1000 ids). Another tenant's recipient row never counts.
        for lead, tenant in ((U("L2"), "tenant-1"), (U("L3"), "tenant-1"), (U("L4"), "tenant-2")):
            self.db.rows("broadcast_recipients").append({"tenant_id": tenant, "broadcast_id": "b9",
                                                         "lead_id": lead, "send_status": "sent",
                                                         "created_at": "2026-11-01T00:00:00Z"})
        res = self.client.get("/api/v1/leads/", params={"source_filter": "broadcast", "broadcast_id": "b9"})
        self.assertEqual(sorted(r["id"] for r in res.json()["data"]), sorted([U("L2"), U("L3")]))
        self.assertNotIn("broadcast_recipients", res.json()["data"][0])
        res = self.client.get("/api/v1/leads/", params={"source_filter": "broadcast", "broadcast_id": "nope"})
        self.assertEqual(res.json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
