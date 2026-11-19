"""Operator lead search and lead chat thread: validation, tenant isolation, paging."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.system_admin import get_system_admin

TENANT = "11111111-1111-1111-1111-111111111111"
LEAD = "22222222-2222-2222-2222-222222222222"
LEAD_ROW = {
    "id": LEAD, "name": "Meena", "phone": "+919876543210", "segment": "B", "score": 40,
    "source": "whatsapp", "created_at": "2026-11-01T00:00:00+00:00",
}


def chain(data):
    """A query chain where every builder step returns itself and execute() gives `data`."""
    c = MagicMock()
    for step in ("select", "eq", "is_", "ilike", "order", "limit", "lt", "maybe_single"):
        getattr(c, step).return_value = c
    c.execute.return_value = MagicMock(data=data)
    return c


def make_db(tables: dict):
    """tables: name -> chain. A table not listed raises, so an unexpected read fails the test."""
    db = MagicMock()
    used = []

    def table(name):
        used.append(name)
        if name not in tables:
            raise AssertionError(f"unexpected table {name}")
        return tables[name]

    db.table.side_effect = table
    db.used = used
    return db


def eq_pairs(c):
    return [tuple(call.args) for call in c.eq.call_args_list]


class LeadSearchTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def url(self, tenant=TENANT):
        return f"/api/v1/operator/clients/{tenant}/leads/search"

    @patch("app.routes.operator_leads.get_supabase")
    def test_bad_characters_are_rejected_before_the_database(self, mock_db):
        for bad in [",", "a,b", "(x)", "ab*", "50%", 'a"b', "a_b", "x);drop", "name,phone.eq.1", "a\\b"]:
            r = self.client.get(self.url(), params={"q": bad})
            self.assertEqual(r.status_code, 400, bad)
        mock_db.assert_not_called()

    @patch("app.routes.operator_leads.get_supabase")
    def test_length_rules(self, mock_db):
        for q in ["", " ", "a", " a ", "x" * 61]:
            self.assertEqual(self.client.get(self.url(), params={"q": q}).status_code, 400, repr(q))
        mock_db.assert_not_called()

    @patch("app.routes.operator_leads.get_supabase")
    def test_digit_query_filters_on_phone(self, mock_db):
        leads = chain([LEAD_ROW])
        mock_db.return_value = make_db({"leads": leads})
        r = self.client.get(self.url(), params={"q": "+91 98765"})
        self.assertEqual(r.status_code, 200)
        leads.ilike.assert_called_once_with("phone", "%9198765%")
        body = r.json()
        self.assertEqual(body["query"], "+91 98765")
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["leads"][0]["phone"], "+919876543210")  # not masked
        self.assertEqual(set(body["leads"][0]), {"id", "name", "phone", "segment", "score", "source", "created_at"})

    @patch("app.routes.operator_leads.get_supabase")
    def test_name_query_filters_on_name(self, mock_db):
        leads = chain([LEAD_ROW])
        mock_db.return_value = make_db({"leads": leads})
        self.assertEqual(self.client.get(self.url(), params={"q": "Meena"}).status_code, 200)
        leads.ilike.assert_called_once_with("name", "%Meena%")

    @patch("app.routes.operator_leads.get_supabase")
    def test_short_digits_and_mixed_text_search_the_name(self, mock_db):
        for q, expected in [("123", "%123%"), ("Room 12345", "%Room 12345%")]:
            leads = chain([])
            mock_db.return_value = make_db({"leads": leads})
            self.assertEqual(self.client.get(self.url(), params={"q": q}).status_code, 200)
            leads.ilike.assert_called_once_with("name", expected)

    @patch("app.routes.operator_leads.get_supabase")
    def test_non_latin_names_are_allowed(self, mock_db):
        leads = chain([])
        mock_db.return_value = make_db({"leads": leads})
        for q in ["மீனா", "O'Brien-Smith Jr."]:
            self.assertEqual(self.client.get(self.url(), params={"q": q}).status_code, 200, q)

    @patch("app.routes.operator_leads.get_supabase")
    def test_limit_is_capped_and_defaults_to_10(self, mock_db):
        leads = chain([])
        mock_db.return_value = make_db({"leads": leads})
        self.client.get(self.url(), params={"q": "Meena", "limit": 500})
        leads.limit.assert_called_with(25)
        self.client.get(self.url(), params={"q": "Meena"})
        leads.limit.assert_called_with(10)
        self.client.get(self.url(), params={"q": "Meena", "limit": 0})
        leads.limit.assert_called_with(1)

    @patch("app.routes.operator_leads.get_supabase")
    def test_always_filtered_by_tenant_and_not_deleted(self, mock_db):
        leads = chain([])
        mock_db.return_value = make_db({"leads": leads})
        for q in ["Meena", "98765432"]:
            leads.reset_mock()
            self.client.get(self.url(), params={"q": q})
            self.assertIn(("tenant_id", TENANT), eq_pairs(leads))
            leads.is_.assert_called_once_with("deleted_at", "null")
            self.assertEqual(leads.or_.call_count, 0)

    @patch("app.routes.operator_leads.get_supabase")
    def test_not_a_uuid_is_404(self, mock_db):
        self.assertEqual(self.client.get(self.url("not-a-uuid"), params={"q": "Meena"}).status_code, 404)
        mock_db.assert_not_called()


class LeadThreadTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def url(self, tenant=TENANT, lead=LEAD):
        return f"/api/v1/operator/clients/{tenant}/leads/{lead}/thread"

    @staticmethod
    def msg(i, content="hi"):
        return {
            "id": f"m{i}", "created_at": f"2026-11-01T10:{59 - i:02d}:00+00:00", "direction": "inbound",
            "channel": "whatsapp", "is_ai_generated": False, "sent_by_name": None, "media_type": None,
            "content": content,
        }

    @patch("app.routes.operator_leads.get_supabase")
    def test_lead_of_another_client_is_404_and_messages_are_never_read(self, mock_db):
        leads = chain(None)
        db = make_db({"leads": leads})  # a read of "messages" raises
        mock_db.return_value = db
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["detail"], "Lead not found")
        self.assertNotIn("messages", db.used)
        pairs = eq_pairs(leads)
        self.assertIn(("id", LEAD), pairs)
        self.assertIn(("tenant_id", TENANT), pairs)

    @patch("app.routes.operator_leads.get_supabase")
    def test_lookup_returning_none_outright_is_404(self, mock_db):
        leads = chain(None)
        leads.execute.return_value = None
        mock_db.return_value = make_db({"leads": leads})
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    @patch("app.routes.operator_leads.get_supabase")
    def test_non_uuid_ids_are_404(self, mock_db):
        for t, l in [("nope", LEAD), (TENANT, "nope"), ("1", "2")]:
            self.assertEqual(self.client.get(self.url(t, l)).status_code, 404)
        mock_db.assert_not_called()

    @patch("app.routes.operator_leads.get_supabase")
    def test_long_message_is_cut_at_4000_and_marked(self, mock_db):
        msgs = chain([self.msg(0, "x" * 5000), self.msg(1, "y" * 4000), self.msg(2, "short")])
        mock_db.return_value = make_db({"leads": chain(LEAD_ROW), "messages": msgs})
        body = self.client.get(self.url()).json()
        m0, m1, m2 = body["messages"]
        self.assertEqual(len(m0["content"]), 4000)
        self.assertTrue(m0["truncated"])
        self.assertEqual(len(m1["content"]), 4000)
        self.assertNotIn("truncated", m1)
        self.assertNotIn("truncated", m2)
        self.assertEqual(body["lead"], LEAD_ROW)

    @patch("app.routes.operator_leads.get_supabase")
    def test_next_before_only_on_a_full_page(self, mock_db):
        rows = [self.msg(i) for i in range(3)]
        msgs = chain(rows)
        mock_db.return_value = make_db({"leads": chain(LEAD_ROW), "messages": msgs})
        full = self.client.get(self.url(), params={"limit": 3}).json()
        self.assertEqual(full["next_before"], rows[-1]["created_at"])
        short = self.client.get(self.url(), params={"limit": 4}).json()
        self.assertIsNone(short["next_before"])
        msgs.execute.return_value = MagicMock(data=[])
        empty = self.client.get(self.url()).json()
        self.assertEqual(empty["messages"], [])
        self.assertIsNone(empty["next_before"])

    @patch("app.routes.operator_leads.get_supabase")
    def test_messages_filtered_by_tenant_and_lead_newest_first(self, mock_db):
        msgs = chain([])
        mock_db.return_value = make_db({"leads": chain(LEAD_ROW), "messages": msgs})
        self.client.get(self.url())
        pairs = eq_pairs(msgs)
        self.assertIn(("tenant_id", TENANT), pairs)
        self.assertIn(("lead_id", LEAD), pairs)
        msgs.order.assert_called_with("created_at", desc=True)
        msgs.limit.assert_called_with(50)
        msgs.lt.assert_not_called()

    @patch("app.routes.operator_leads.get_supabase")
    def test_limit_cap_and_before_cursor(self, mock_db):
        msgs = chain([])
        mock_db.return_value = make_db({"leads": chain(LEAD_ROW), "messages": msgs})
        self.client.get(self.url(), params={"limit": 1000, "before": "2026-11-01T10:00:00+00:00"})
        msgs.limit.assert_called_with(100)
        msgs.lt.assert_called_once_with("created_at", "2026-11-01T10:00:00+00:00")

    @patch("app.routes.operator_leads.get_supabase")
    def test_bad_before_is_400(self, mock_db):
        msgs = chain([])
        mock_db.return_value = make_db({"leads": chain(LEAD_ROW), "messages": msgs})
        r = self.client.get(self.url(), params={"before": "yesterday,eq.1"})
        self.assertEqual(r.status_code, 400)
        msgs.lt.assert_not_called()


class NoAdminTests(unittest.TestCase):
    def test_without_the_admin_override_the_endpoints_refuse(self):
        app.dependency_overrides.clear()
        client = TestClient(app)
        base = f"/api/v1/operator/clients/{TENANT}/leads"
        for path in (f"{base}/search?q=Meena", f"{base}/{LEAD}/thread"):
            self.assertIn(client.get(path).status_code, (401, 403), path)


if __name__ == "__main__":
    unittest.main()
