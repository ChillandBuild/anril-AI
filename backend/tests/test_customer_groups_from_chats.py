"""POST /api/v1/customer-groups/from-chats: Chats > Filter > "Save as a group".

The Chats list is served by the get_inbox_chats SQL function; here a python stand-in plays it
(honouring p_limit / p_offset) so we can check the endpoint collects EVERY match across pages,
scopes to the caller's tenant, and follows the same rules as the plain create route.
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
from app.routes import conversations as conv_route
from app.routes import customer_groups as groups_route
from tests.fake_supabase import FakeSupabase


def U(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "anril-test-from-chats:" + name))


OWNER = {"tenant_id": "tenant-1", "role": "owner", "user_id": "user-1", "permissions": []}
URL = "/api/v1/customer-groups/from-chats"


def _lead(db, lead_id, tenant_id="tenant-1", deleted=False):
    db.rows("leads").append({"id": lead_id, "tenant_id": tenant_id, "name": lead_id,
                             "created_at": "2026-01-01T00:00:00+00:00", "phone": "+91" + lead_id[:8],
                             "deleted_at": "2026-01-01" if deleted else None,
                             "opted_out": None, "whatsapp_undeliverable": None})


class FromChatsTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.rpc_calls: list[dict] = []
        self.matches: list[str] = []      # lead ids the "chat list" returns, in order
        self.fake_total: int | None = None  # force a bigger total than the ids returned

        def get_inbox_chats(params):
            self.rpc_calls.append(params)
            page = self.matches[params["p_offset"]: params["p_offset"] + params["p_limit"]]
            total = self.fake_total if self.fake_total is not None else len(self.matches)
            return [{"lead_id": lid, "total": total} for lid in page]
        self.db.rpc_handlers["get_inbox_chats"] = get_inbox_chats

        for p in (patch.object(groups_route, "get_supabase", return_value=self.db),
                  patch.object(conv_route, "get_setting", side_effect=lambda *a, **k: "true")):
            p.start()
            self.addCleanup(p.stop)
        self.ctx = OWNER
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        self.client = TestClient(app)
        self.addCleanup(app.dependency_overrides.clear)

    def _own(self, n, prefix="own"):
        ids = [U(f"{prefix}-{i}") for i in range(n)]
        for lid in ids:
            _lead(self.db, lid)
        return ids

    def _members(self, gid):
        return {m["lead_id"] for m in self.db.rows("customer_group_members") if m["group_id"] == gid}

    def test_saves_every_match_across_pages_as_a_picked_group(self):
        self.matches = self._own(450)  # three pages of 200
        res = self.client.post(URL, json={"name": "  Insta Hot – Nov ", "view": "ai_handling", "q": " ravi ",
                                           "channels": "instagram", "segments": "A"})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["name"], "Insta Hot – Nov")
        self.assertEqual(body["kind"], "picked")
        self.assertEqual(body["added"], 450)
        self.assertEqual(body["member_count"], 450)
        stored = self.db.rows("customer_groups")[-1]
        self.assertEqual((stored["tenant_id"], stored["kind"], stored["created_by"]), ("tenant-1", "picked", "user-1"))
        self.assertEqual(self._members(body["id"]), set(self.matches))
        self.assertTrue(all(m["tenant_id"] == "tenant-1" for m in self.db.rows("customer_group_members")))
        # Same filters as the list would send, every page, nothing but the offset changing.
        self.assertEqual([c["p_offset"] for c in self.rpc_calls], [0, 200, 400])
        first = self.rpc_calls[0]
        self.assertEqual((first["p_tenant_id"], first["p_view"], first["p_search"], first["p_channels"], first["p_segments"]),
                         ("tenant-1", "ai_handling", "ravi", ["instagram"], ["A"]))

    def test_each_tab_maps_to_its_own_sql_view(self):
        self.matches = self._own(1)
        for tab, sql in (("inbox", "needs_you"), ("ai_handling", "ai_handling"), ("archived", "archived"), ("blocked", "blocked")):
            self.rpc_calls.clear()
            res = self.client.post(URL, json={"name": f"From {tab}", "view": tab})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(self.rpc_calls[0]["p_view"], sql)

    def test_other_tenants_and_deleted_leads_never_get_in(self):
        mine = self._own(2)
        foreign = U("foreign")
        _lead(self.db, foreign, tenant_id="tenant-2")
        gone = U("gone")
        _lead(self.db, gone, deleted=True)
        self.matches = mine + [foreign, gone]
        res = self.client.post(URL, json={"name": "Scoped"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["added"], 2)
        self.assertEqual(self._members(res.json()["id"]), set(mine))
        self.assertEqual(self.rpc_calls[0]["p_tenant_id"], "tenant-1")

    def test_a_group_of_another_tenant_with_the_same_name_does_not_block(self):
        self.db.rows("customer_groups").append({"id": U("g-other"), "tenant_id": "tenant-2", "name": "Hot",
                                                "kind": "picked", "created_at": "2026-01-01T00:00:00"})
        self.matches = self._own(1)
        self.assertEqual(self.client.post(URL, json={"name": "Hot"}).status_code, 200)

    def test_duplicate_name_is_the_same_409_as_create_and_reads_no_chats(self):
        self.matches = self._own(2)
        self.assertEqual(self.client.post("/api/v1/customer-groups", json={"name": "Wedding"}).status_code, 200)
        res = self.client.post(URL, json={"name": "  wedding "})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"], "A group with this name already exists")
        self.assertEqual(self.rpc_calls, [])

    def test_leads_view_alone_cannot_save(self):
        self.matches = self._own(1)
        self.ctx = {"tenant_id": "tenant-1", "role": "caller", "user_id": "u2",
                    "permissions": ["leads.view", "conversations.view"]}
        res = self.client.post(URL, json={"name": "Nope"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.db.rows("customer_groups"), [])

    def test_leads_manage_without_chats_access_cannot_save(self):
        self.matches = self._own(1)
        self.ctx = {"tenant_id": "tenant-1", "role": "caller", "user_id": "u2", "permissions": ["leads.manage"]}
        res = self.client.post(URL, json={"name": "Nope"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.db.rows("customer_groups"), [])

    def test_leads_manage_and_chats_access_can_save_and_a_caller_only_gets_their_own_chats(self):
        self.matches = self._own(2)
        self.ctx = {"tenant_id": "tenant-1", "role": "caller", "user_id": "u2", "caller_id": "caller-9",
                    "permissions": ["leads.manage", "conversations.view"]}
        res = self.client.post(URL, json={"name": "Mine"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.rpc_calls[0]["p_caller_id"], "caller-9")

    def test_more_than_5000_is_refused_with_a_clear_message_and_creates_nothing(self):
        self.matches = self._own(3)
        self.fake_total = 5001
        res = self.client.post(URL, json={"name": "Too big"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("5,001 chats match", res.json()["detail"])
        self.assertIn("5,000", res.json()["detail"])
        self.assertEqual(self.db.rows("customer_groups"), [])

    def test_exactly_5000_is_allowed(self):
        self.matches = self._own(5000)
        res = self.client.post(URL, json={"name": "Max"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["added"], 5000)

    def test_no_matches_creates_no_empty_group(self):
        res = self.client.post(URL, json={"name": "Empty"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.db.rows("customer_groups"), [])

    def test_unknown_tab_or_filter_value_is_400(self):
        self.matches = self._own(1)
        self.assertEqual(self.client.post(URL, json={"name": "A", "view": "needs_you"}).status_code, 400)
        self.assertEqual(self.client.post(URL, json={"name": "B", "channels": "carrier-pigeon"}).status_code, 400)
        self.assertEqual(self.db.rows("customer_groups"), [])

    def test_a_failed_member_save_leaves_no_empty_group_behind(self):
        self.matches = self._own(2)
        real_table = self.db.table

        def table(name):
            if name == "customer_group_members":
                raise RuntimeError("db blip")
            return real_table(name)
        with patch.object(self.db, "table", side_effect=table):
            res = self.client.post(URL, json={"name": "Blip"})
        self.assertEqual(res.status_code, 500)
        self.assertEqual(self.db.rows("customer_groups"), [])


if __name__ == "__main__":
    unittest.main()
