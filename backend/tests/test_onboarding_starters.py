"""Tests for POST /api/v1/onboarding/apply-starter -- the zero-AI-calls
fallback for a brand-new self-serve tenant.

A starter now writes only the business description: how the assistant behaves is
the platform-wide master prompt, which onboarding must never touch. Covers the
clobber guard (refuse to overwrite a tenant's own description unless force=true,
without mistaking a blank one for a customised one).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_owner_tenant_id

STARTER_ROW = {
    "key": "coaching",
    "business_description": "Starter business description.",
}


def _table_mock(starter_row=STARTER_ROW):
    """A get_supabase() stand-in shaped for apply_starter's vertical_starters read
    plus save_setting's own db.table("app_settings").upsert() call."""
    db = MagicMock()

    def table(name):
        tbl = MagicMock()
        if name == "vertical_starters":
            tbl.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                MagicMock(data=starter_row)
            )
        elif name == "app_settings":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            tbl.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        return tbl

    db.table.side_effect = table
    return db


class ApplyStarterRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_owner_tenant_id] = lambda: "tenant-1"  # onboarding writes are owner only

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.routes.onboarding.get_setting", return_value=None)
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_applies_cleanly_to_a_fresh_tenant(self, mock_get_db, mock_save, mock_get_setting):
        mock_get_db.return_value = _table_mock()

        res = self.client.post("/api/v1/onboarding/apply-starter", json={"key": "coaching"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"applied": "coaching"})
        mock_save.assert_called_once_with("business_description", "Starter business description.", tenant_id="tenant-1")

    @patch("app.routes.onboarding.get_setting", return_value=None)
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_never_writes_a_per_tenant_master_prompt(self, mock_get_db, mock_save, mock_get_setting):
        """The master prompt is platform-wide -- a starter must not create a tenant copy."""
        db = _table_mock()
        mock_get_db.return_value = db

        res = self.client.post("/api/v1/onboarding/apply-starter", json={"key": "coaching"})

        self.assertEqual(res.status_code, 200)
        touched = {c.args[0] for c in db.table.call_args_list if c.args}
        self.assertNotIn("ai_prompts", touched)

    @patch("app.routes.onboarding.get_setting", return_value="This tenant's own description.")
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_refuses_to_clobber_a_customised_description_without_force(self, mock_get_db, mock_save, mock_get_setting):
        mock_get_db.return_value = _table_mock()

        res = self.client.post("/api/v1/onboarding/apply-starter", json={"key": "coaching"})

        self.assertEqual(res.status_code, 409)
        self.assertTrue(res.json()["detail"]["would_overwrite"]["business_description"])
        mock_save.assert_not_called()

    @patch("app.routes.onboarding.get_setting", return_value="This tenant's own description.")
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_force_overwrites_a_customised_description(self, mock_get_db, mock_save, mock_get_setting):
        mock_get_db.return_value = _table_mock()

        res = self.client.post("/api/v1/onboarding/apply-starter", json={"key": "coaching", "force": True})

        self.assertEqual(res.status_code, 200)
        mock_save.assert_called_once()

    @patch("app.routes.onboarding.get_setting", return_value="  ")
    @patch("app.routes.onboarding.save_setting")
    @patch("app.routes.onboarding.get_supabase")
    def test_whitespace_only_description_does_not_count_as_customised(self, mock_get_db, mock_save, mock_get_setting):
        mock_get_db.return_value = _table_mock()

        res = self.client.post("/api/v1/onboarding/apply-starter", json={"key": "coaching"})

        self.assertEqual(res.status_code, 200)

    @patch("app.routes.onboarding.get_setting", return_value=None)
    @patch("app.routes.onboarding.get_supabase")
    def test_unknown_starter_key_is_404(self, mock_get_db, mock_get_setting):
        mock_get_db.return_value = _table_mock(starter_row=None)

        res = self.client.post("/api/v1/onboarding/apply-starter", json={"key": "not-a-real-key"})

        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
