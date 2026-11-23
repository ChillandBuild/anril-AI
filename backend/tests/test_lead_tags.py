"""Customers > tags: the rules (trim, 30 chars, 10 per person, VIP = vip) and the three routes,
on the in-memory fake database. tenant-1 is the caller's; tenant-2 must never be touched."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import lead_tags
from tests.fake_supabase import FakeSupabase

OWNER = {"tenant_id": "tenant-1", "role": "owner", "user_id": "user-1", "permissions": []}
VIEWER = {"tenant_id": "tenant-1", "role": "member", "user_id": "user-2", "permissions": ["leads.view"]}


def _lead(db, lid, tenant="tenant-1", **kw):
    db.rows("leads").append({"id": lid, "tenant_id": tenant, "name": lid, "phone": "+91" + lid, "deleted_at": None, **kw})


def _tag(db, lid, tag, tenant="tenant-1"):
    db.add("lead_tags", tenant_id=tenant, lead_id=lid, tag=tag)


def _tags(db, lid):
    return sorted(r["tag"] for r in db.rows("lead_tags") if r["lead_id"] == lid)


class CleanTagsTests(unittest.TestCase):
    def test_trims_dedupes_ignoring_case_keeps_first_spelling_and_drops_bad_ones(self):
        out = lead_tags.clean_tags(["  VIP ", "vip", "wedding   order", "", "   ", "x" * 31, "x" * 30, 5, None])
        self.assertEqual(out, ["VIP", "wedding order", "x" * 30])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        for lid in ("a", "b"):
            _lead(self.db, lid)
        _lead(self.db, "gone", deleted_at="2026-01-01")
        _lead(self.db, "x", tenant="tenant-2")

    def test_add_counts_new_pairs_only_and_never_touches_other_tenants_or_deleted_people(self):
        res = lead_tags.add_tags(self.db, "tenant-1", ["a", "b", "x", "gone"], ["VIP", "vip", "Bridal"])
        self.assertEqual(res, {"added": 4, "removed": 0, "skipped_limit": 0})
        self.assertEqual(_tags(self.db, "a"), ["Bridal", "VIP"])
        self.assertEqual(_tags(self.db, "x"), [])
        self.assertEqual(_tags(self.db, "gone"), [])
        # again: nothing new
        self.assertEqual(lead_tags.add_tags(self.db, "tenant-1", ["a"], ["vip"])["added"], 0)

    def test_a_tag_already_in_use_keeps_its_first_spelling_on_other_people(self):
        _tag(self.db, "a", "VIP")
        lead_tags.add_tags(self.db, "tenant-1", ["b"], ["vip"])
        self.assertEqual(_tags(self.db, "b"), ["VIP"])

    def test_ten_per_person_over_the_limit_is_skipped_and_counted(self):
        for i in range(9):
            _tag(self.db, "a", f"t{i}")
        res = lead_tags.add_tags(self.db, "tenant-1", ["a", "b"], ["one", "two"])
        self.assertEqual(res["skipped_limit"], 1)       # a takes "one" (10th) and skips "two"
        self.assertEqual(res["added"], 3)               # a: one;  b: one, two
        self.assertEqual(len(_tags(self.db, "a")), 10)
        self.assertEqual(_tags(self.db, "b"), ["one", "two"])

    def test_remove_ignores_case_and_other_tenants(self):
        _tag(self.db, "a", "VIP")
        _tag(self.db, "a", "Bridal")
        _tag(self.db, "x", "VIP", tenant="tenant-2")
        res = lead_tags.remove_tags(self.db, "tenant-1", ["a", "x"], ["vip"])
        self.assertEqual(res, {"added": 0, "removed": 1, "skipped_limit": 0})
        self.assertEqual(_tags(self.db, "a"), ["Bridal"])
        self.assertEqual(_tags(self.db, "x"), ["VIP"])

    def test_in_use_merges_case_and_counts_people(self):
        _tag(self.db, "a", "VIP")
        _tag(self.db, "b", "vip")
        _tag(self.db, "a", "Bridal")
        _tag(self.db, "x", "VIP", tenant="tenant-2")
        self.assertEqual(lead_tags.tags_in_use(self.db, "tenant-1"),
                         [{"tag": "VIP", "count": 2}, {"tag": "Bridal", "count": 1}])

    def test_spellings_match_ignoring_case_and_wildcard_characters_are_literal(self):
        _tag(self.db, "a", "VIP")
        _tag(self.db, "b", "vip")
        _tag(self.db, "a", "a_b")
        _tag(self.db, "b", "axb")
        self.assertEqual(sorted(lead_tags.tag_spellings(self.db, "tenant-1", " Vip ")), ["VIP", "vip"])
        self.assertEqual(lead_tags.tag_spellings(self.db, "tenant-1", "a_b"), ["a_b"])
        self.assertEqual(lead_tags.tag_spellings(self.db, "tenant-1", "nope"), [])

    def test_missing_table_never_raises(self):
        class Broken:
            def table(self, name):
                raise RuntimeError('relation "lead_tags" does not exist')

        self.assertEqual(lead_tags.tags_by_lead(Broken(), "t", ["a"]), {})
        self.assertEqual(lead_tags.tags_in_use(Broken(), "t"), [])
        self.assertEqual(lead_tags.tag_spellings(Broken(), "t", "vip"), [])
        self.assertEqual(lead_tags.remove_tags(Broken(), "t", ["a"], ["vip"])["removed"], 0)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        _lead(self.db, "a")
        _lead(self.db, "b")
        self.ctx = OWNER
        self.patch = patch("app.routes.lead_tags.get_supabase", return_value=self.db)
        self.patch.start()
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_current_user] = lambda: {"user_id": self.ctx["user_id"]}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.patch.stop()

    def test_add_list_remove_round_trip(self):
        res = self.client.post("/api/v1/lead-tags/add", json={"lead_ids": ["a", "b"], "tags": ["VIP"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"added": 2, "removed": 0, "skipped_limit": 0})
        self.assertEqual(self.db.rows("lead_tags")[0]["created_by"], "user-1")
        self.assertEqual(self.client.get("/api/v1/lead-tags").json(), {"tags": [{"tag": "VIP", "count": 2}]})
        res = self.client.post("/api/v1/lead-tags/remove", json={"lead_ids": ["a"], "tags": ["vip"]})
        self.assertEqual(res.json()["removed"], 1)
        self.assertEqual(self.client.get("/api/v1/lead-tags").json()["tags"][0]["count"], 1)

    def test_viewer_can_list_but_not_change(self):
        self.ctx = VIEWER
        self.assertEqual(self.client.get("/api/v1/lead-tags").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/lead-tags/add", json={"lead_ids": ["a"], "tags": ["x"]}).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/lead-tags/remove", json={"lead_ids": ["a"], "tags": ["x"]}).status_code, 403)

    def test_empty_lists_are_refused(self):
        self.assertEqual(self.client.post("/api/v1/lead-tags/add", json={"lead_ids": [], "tags": ["x"]}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/lead-tags/add", json={"lead_ids": ["a"], "tags": []}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
