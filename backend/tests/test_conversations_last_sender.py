"""GET /api/v1/conversations: who sent each lead's last message, the Chats-page extras
(why it needs you, what they want, unread), and every filter going into the SQL function
(migration 272) so `total` and paging count exactly what the tab shows."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import conversations as conv_route
from tests.fake_supabase import FakeSupabase


def _owner():
    return {"tenant_id": "t1", "role": "owner", "user_id": "u1", "permissions": []}


class LastSenderTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = _owner
        db = self.db = FakeSupabase()
        for lid in ("ai", "human", "customer"):
            db.add("leads", id=lid, tenant_id="t1", deleted_at=None, archived_at=None, blocked_at=None,
                   escalation_reason=None)
        msgs = [
            ("ai", "inbound", False, "2026-10-10T09:00:00+00:00"),
            ("ai", "outbound", True, "2026-10-10T09:01:00+00:00"),
            ("human", "inbound", False, "2026-10-10T10:00:00+00:00"),
            ("human", "outbound", False, "2026-10-10T10:05:00+00:00"),
            ("customer", "outbound", True, "2026-10-10T08:00:00+00:00"),
            ("customer", "inbound", False, "2026-10-10T08:30:00+00:00"),
            ("ai", "inbound", False, "2026-10-10T09:00:00+00:00"),
        ]
        for lid, direction, ai, at in msgs:
            db.add("messages", tenant_id="t1", lead_id=lid, direction=direction, is_ai_generated=ai, created_at=at)
        db.add("messages", tenant_id="t2", lead_id="human", direction="outbound", is_ai_generated=True,
               created_at="2026-10-10T11:00:00+00:00")  # another business: must not count
        last = {"ai": "2026-10-10T09:01:00+00:00", "human": "2026-10-10T10:05:00+00:00", "customer": "2026-10-10T08:30:00+00:00"}
        db.rpc_handlers["get_inbox_chats"] = lambda params: [
            {"lead_id": lid, "last_reply_at": at, "last_message_content": "x", "total": 3,
             "inbox_group": 0 if lid == "customer" else 1, "waiting_since": None,
             "unread_count": 2 if lid == "customer" else 0}
            for lid, at in last.items()
        ]
        for p in (patch.object(conv_route, "get_supabase", return_value=db),
                  patch.object(conv_route, "get_setting", return_value="true")):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_each_row_reports_who_sent_the_last_message(self):
        res = self.client.get("/api/v1/conversations")
        self.assertEqual(res.status_code, 200, res.text)
        got = {l["id"]: (l["last_message_direction"], l["last_message_is_ai"]) for l in res.json()["leads"]}
        self.assertEqual(got, {
            "ai": ("outbound", True),
            "human": ("outbound", False),
            "customer": ("inbound", False),
        })

    def test_lookup_failure_leaves_the_sender_unknown_not_wrong(self):
        with patch.object(conv_route, "_last_message_senders", return_value={}):
            res = self.client.get("/api/v1/conversations")
        self.assertTrue(all(l["last_message_direction"] is None and l["last_message_is_ai"] is None for l in res.json()["leads"]))

    def test_row_carries_why_it_needs_you_what_they_want_and_unread(self):
        self.db.add("chat_handovers", tenant_id="t1", lead_id="customer", status="pending",
                    reason="Customer asked for a discount", opened_at="2026-10-10T08:31:00+00:00")
        self.db.add("chat_handovers", tenant_id="t1", lead_id="ai", status="resolved",
                    reason="old, already handled", opened_at="2026-10-09T08:31:00+00:00")
        self.db.add("deals", id="d1", tenant_id="t1", lead_id="customer", total_paise=1500000, stage="quoted",
                    created_at="2026-10-10T08:40:00+00:00")
        self.db.add("deals", id="d0", tenant_id="t1", lead_id="human", total_paise=99, stage="lost",
                    created_at="2026-10-10T08:40:00+00:00")
        self.db.add("deal_items", tenant_id="t1", deal_id="d1", name="Bridal saree")
        rows = {l["id"]: l for l in self.client.get("/api/v1/conversations").json()["leads"]}
        self.assertEqual(rows["customer"]["needs_reason"], "Customer asked for a discount")
        self.assertEqual(rows["customer"]["wants"], {"items": "Bridal saree", "total_paise": 1500000, "stage": "quoted"})
        self.assertEqual(rows["customer"]["unread_count"], 2)
        self.assertEqual(rows["customer"]["inbox_group"], 0)
        self.assertIsNone(rows["ai"]["needs_reason"])   # a resolved handover is not a reason
        self.assertIsNone(rows["human"]["wants"])       # a lost deal is not what they want


class FilterTests(unittest.TestCase):
    """Every tab and filter goes to the SQL function -- never applied after paging."""

    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.db = FakeSupabase()
        self.calls = []

        def handler(params):
            self.calls.append(params)
            return []
        self.db.rpc_handlers["get_inbox_chats"] = handler
        self.db.rpc_handlers["get_inbox_counts"] = lambda params: (self.calls.append(params) or {"needs_you": 3})
        self.ai_master = "true"
        for p in (patch.object(conv_route, "get_supabase", return_value=self.db),
                  patch.object(conv_route, "get_setting", side_effect=lambda *a, **k: self.ai_master)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def as_role(self, role, caller_id=None):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t1", "role": role, "user_id": "u1", "caller_id": caller_id, "permissions": ["conversations.view"],
        }

    def test_tab_page_and_filters_go_to_the_sql_function(self):
        self.as_role("owner")
        res = self.client.get(
            "/api/v1/conversations?view=ai_handling&limit=20&offset=40&q=%20ravi%20"
            "&channels=whatsapp,instagram&segments=A,B&results=paid,lost&came_from=meta_ads"
            "&handled_by=ai,nobody,6f1c6c3e-2a52-4c1f-9d62-1a4b7c0e9f10&waiting=unread,over_1h"
            "&since=2026-10-01T00:00:00Z&tag_id=0b7a6f5e-0f2e-4a0e-9b2c-55a1f0c9d0aa"
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.calls[-1], {
            "p_tenant_id": "t1", "p_limit": 20, "p_offset": 40, "p_view": "ai_handling", "p_search": "ravi",
            "p_caller_id": None, "p_ai_master": True,
            "p_channels": ["whatsapp", "instagram"], "p_segments": ["A", "B"], "p_results": ["paid", "lost"],
            "p_came_from": ["meta_ads"], "p_handled_by": ["ai", "nobody", "6f1c6c3e-2a52-4c1f-9d62-1a4b7c0e9f10"],
            "p_waiting": ["unread", "over_1h"], "p_since": "2026-10-01T00:00:00+00:00",
            "p_tag_id": "0b7a6f5e-0f2e-4a0e-9b2c-55a1f0c9d0aa",
        })

    def test_old_folder_names_still_map_to_tabs(self):
        self.as_role("owner")
        self.client.get("/api/v1/conversations?folder=blocked")
        self.assertEqual(self.calls[-1]["p_view"], "blocked")
        self.client.get("/api/v1/conversations")
        self.assertEqual(self.calls[-1]["p_view"], "inbox")  # plain newest-first, not waiting-first
        self.client.get("/api/v1/conversations?view=inbox")
        self.assertEqual(self.calls[-1]["p_view"], "inbox")

    def test_unknown_filter_values_are_rejected_not_ignored(self):
        self.as_role("owner")
        for qs in ("channels=sms", "segments=Z", "results=maybe", "came_from=tv", "waiting=soon",
                   "handled_by=karthik", "view=everything", "view=needs_you"):
            self.assertEqual(self.client.get(f"/api/v1/conversations?{qs}").status_code, 400, qs)

    def test_callers_are_limited_in_sql_not_after_paging(self):
        self.as_role("caller", caller_id="c9")
        self.client.get("/api/v1/conversations")
        self.assertEqual(self.calls[-1]["p_caller_id"], "c9")

    def test_account_ai_switch_off_means_nothing_is_ai_handling(self):
        self.as_role("owner")
        self.ai_master = "false"
        self.client.get("/api/v1/conversations?view=ai_handling")
        self.assertIs(self.calls[-1]["p_ai_master"], False)

    def test_counts_use_the_same_filters(self):
        self.as_role("owner")
        res = self.client.get("/api/v1/conversations/counts?view=archived&segments=A&waiting=unread")
        self.assertEqual(res.json(), {"needs_you": 3})
        params = self.calls[-1]
        self.assertEqual((params["p_view"], params["p_segments"], params["p_waiting"]), ("archived", ["A"], ["unread"]))
        self.assertNotIn("p_limit", params)


if __name__ == "__main__":
    unittest.main()
