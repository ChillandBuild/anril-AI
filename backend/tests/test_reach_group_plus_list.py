"""v9.2 Reach: one campaign from a Customers group plus an uploaded list, each with its own consent."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import upload as routes

GROUP = {"group": {"id": "g1", "name": "Bought in 90 days", "kind": "manual"}, "members": 3, "stopped": 1, "no_whatsapp": 0,
         "people": [{"phone": "+919800000001", "name": "Priya", "opt_in_source": "customer", "opted_in": True},
                    {"phone": "+919800000002", "name": "Meena", "opt_in_source": "customer", "opted_in": True}]}


def body(**kw):
    base = {"leads": [], "template_name": "t", "schedule_type": "now"}
    return routes.BulkSendRequest(**{**base, **kw})


class MergeTests(unittest.TestCase):
    def test_group_plus_list_keeps_each_consent_and_names_both(self):
        b = body(group_id="g1", csv_file_name="expo.xlsx", csv_file_path="t1/expo.xlsx", include_opted_out=True,
                 leads=[{"phone": "+919800000009", "name": "Suresh", "opt_in_source": "expo_signup"},
                        {"phone": "+919800000002", "name": "Meena again", "opt_in_source": "manual"}])
        routes._merge_group_into(b, GROUP)
        self.assertEqual([l.phone for l in b.leads][:2], ["+919800000001", "+919800000002"])  # group first
        self.assertEqual(b.leads[2].opt_in_source, "expo_signup")
        self.assertEqual(b.csv_file_name, "Group: Bought in 90 days + expo.xlsx")
        self.assertEqual(b.csv_file_path, "t1/expo.xlsx")  # the uploaded file stays downloadable
        self.assertFalse(b.include_opted_out)  # said-stop people are never sent to

    def test_group_alone_is_unchanged(self):
        b = body(group_id="g1", csv_file_name="x.csv", csv_file_path="p")
        routes._merge_group_into(b, GROUP)
        self.assertEqual(len(b.leads), 2)
        self.assertEqual((b.csv_file_name, b.csv_file_path), ("Group: Bought in 90 days", None))


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t1", "role": "owner", "user_id": "u1", "permissions": []}

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_preview_counts_both(self):
        seen = {}

        def numbers(db, tenant_id, people, **kw):
            seen["people"] = people
            return {"total": 3, "invalid": 0, "no_opt_in": 0, "said_stop": 0, "negative_reply": 0, "blocked": 0,
                    "over_cap": 0, "will_get": 3, "weekly_limit": 2, "week_start": "2026-11-22", "week_end": "2026-11-28",
                    "over_limit_people": [], "rate_inr": 0.86, "cost_inr": 2.58}

        with patch.object(routes, "_resolve_group_or_http", return_value=GROUP), \
             patch.object(routes.reach_audience, "preview_numbers", side_effect=numbers), \
             patch.object(routes, "get_supabase"):
            res = self.client.post("/api/v1/upload/reach-preview", json={
                "group_id": "g1", "leads": [{"phone": "+919800000009", "opt_in_source": "expo_signup"}]})
        self.assertEqual(res.status_code, 200, res.text)
        out = res.json()
        self.assertEqual((out["audience"], out["from_list"], out["in_audience"], out["will_get"]), ("group+list", 1, 4, 3))
        self.assertEqual(len(seen["people"]), 3)


if __name__ == "__main__":
    unittest.main()
