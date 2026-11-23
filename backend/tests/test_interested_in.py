"""Customers > "Interested in" (GET/PUT /api/v1/leads/{id}/interested-in) on the fake database."""
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
from app.services import interested_in
from tests.fake_supabase import FakeSupabase


def U(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "anril-interest:" + name))


OWNER = {"tenant_id": "tenant-1", "role": "owner", "user_id": "user-1", "permissions": []}
VIEWER = {"tenant_id": "tenant-1", "role": "member", "user_id": "user-2", "permissions": ["leads.view"]}
CALLER = {"tenant_id": "tenant-1", "role": "caller", "user_id": "user-3", "caller_id": "caller-1",
          "permissions": ["leads.view", "leads.manage"]}


class InterestedInTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.lead = U("lead")
        self.db.rows("leads").extend([
            {"id": self.lead, "tenant_id": "tenant-1", "deleted_at": None, "assigned_to": "caller-1",
             "interested_item_ids": []},
            {"id": U("lead-other-caller"), "tenant_id": "tenant-1", "deleted_at": None, "assigned_to": "caller-2"},
            {"id": U("lead-t2"), "tenant_id": "tenant-2", "deleted_at": None},
        ])
        self.db.rows("catalog_items").extend([
            {"id": U("ring"), "tenant_id": "tenant-1", "name": "Gold ring"},
            {"id": U("chain"), "tenant_id": "tenant-1", "name": "Chain"},
            {"id": U("t2-item"), "tenant_id": "tenant-2", "name": "Other shop item"},
        ])
        self.patches = [patch("app.routes.leads.get_supabase", return_value=self.db)]
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

    def _url(self, lead=None):
        return f"/api/v1/leads/{lead or self.lead}/interested-in"

    def test_save_then_read_keeps_names_and_order(self):
        res = self.client.put(self._url(), json={"item_ids": [U("chain"), U("ring")]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual([i["name"] for i in res.json()["items"]], ["Chain", "Gold ring"])
        got = self.client.get(self._url()).json()["items"]
        self.assertEqual([i["id"] for i in got], [U("chain"), U("ring")])

    def test_other_business_items_and_junk_are_dropped(self):
        res = self.client.put(self._url(), json={"item_ids": [U("t2-item"), U("ring"), U("ring")]})
        self.assertEqual([i["id"] for i in res.json()["items"]], [U("ring")])
        self.assertEqual(self.db.rows("leads")[0]["interested_item_ids"], [U("ring")])

    def test_an_id_that_is_not_a_uuid_is_422(self):
        res = self.client.put(self._url(), json={"item_ids": ["nope", U("ring")]})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(self.db.rows("leads")[0]["interested_item_ids"], [])

    def test_other_business_lead_is_404(self):
        self.assertEqual(self.client.get(self._url(U("lead-t2"))).status_code, 404)
        self.assertEqual(self.client.put(self._url(U("lead-t2")), json={"item_ids": []}).status_code, 404)

    def test_view_only_can_read_but_not_change(self):
        self.ctx = VIEWER
        self.assertEqual(self.client.get(self._url()).status_code, 200)
        self.assertEqual(self.client.put(self._url(), json={"item_ids": [U("ring")]}).status_code, 403)

    def test_telecaller_only_reaches_own_leads(self):
        self.ctx = CALLER
        self.assertEqual(self.client.get(self._url()).status_code, 200)
        self.assertEqual(self.client.get(self._url(U("lead-other-caller"))).status_code, 404)

    def test_too_many_items_is_422(self):
        res = self.client.put(self._url(), json={"item_ids": [str(i) for i in range(11)]})
        self.assertEqual(res.status_code, 422)

    def test_prompt_line_collapses_newlines_and_caps_names(self):
        self.db.rows("catalog_items")[0]["name"] = "Gold\n\nring   " + "x" * 200
        self.db.rows("leads")[0]["interested_item_ids"] = [U("ring")]
        line = interested_in.prompt_line(self.db, "tenant-1", self.lead)
        self.assertNotIn("\n", line)
        self.assertLessEqual(len(line.split(", ")[0]), len("Interested in: ") + 80)

    def test_prompt_line_is_one_short_fact(self):
        self.db.rows("leads")[0]["interested_item_ids"] = [U("ring"), U("chain")]
        self.assertEqual(interested_in.prompt_line(self.db, "tenant-1", self.lead), "Interested in: Gold ring, Chain")
        self.assertEqual(interested_in.prompt_line(self.db, "tenant-2", self.lead), "")

    def test_read_is_empty_when_column_missing(self):
        class Broken:
            def table(self, *_):
                raise RuntimeError("column does not exist")
        self.assertEqual(interested_in.items_for(Broken(), "tenant-1", self.lead), [])


if __name__ == "__main__":
    unittest.main()
