"""Settings > Connections: the weekly Reach number, read and saved per client (GET/PUT /connections/reach-limit)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
OWNER = {"tenant_id": T1, "role": "owner", "user_id": "u1", "permissions": []}
SETTINGS_MANAGER = {"tenant_id": T1, "role": "staff", "user_id": "u2", "permissions": ["settings.manage"]}
VIEW_ONLY = {"tenant_id": T1, "role": "staff", "user_id": "u3", "permissions": ["settings.view"]}

URL = "/api/v1/connections/reach-limit"


class ReachLimitSettingTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.ctx = OWNER
        self.patches = [patch("app.routes.connections_overview.get_supabase", return_value=self.db)]
        for p in self.patches:
            p.start()
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_tenant_id] = lambda: self.ctx["tenant_id"]
        app.dependency_overrides[get_current_user] = lambda: {"user_id": self.ctx["user_id"]}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()

    def test_get_returns_two_by_default(self):
        res = self.client.get(URL)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"weekly_limit": 2, "default": 2, "min": 1, "max": 50})

    def test_put_saves_and_get_reads_it_back(self):
        res = self.client.put(URL, json={"weekly_limit": 5})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"weekly_limit": 5})
        self.assertEqual(self.client.get(URL).json()["weekly_limit"], 5)

    def test_put_rejects_0_and_51(self):
        for value in (0, 51):
            res = self.client.put(URL, json={"weekly_limit": value})
            self.assertEqual(res.status_code, 422, (value, res.text))

    def test_put_records_one_audit_event_and_a_422_records_none(self):
        with patch("app.routes.connections_overview.record_audit_event") as audit:
            self.assertEqual(self.client.put(URL, json={"weekly_limit": 0}).status_code, 422)
            audit.assert_not_called()
            self.assertEqual(self.client.put(URL, json={"weekly_limit": 4}).status_code, 200)
        audit.assert_called_once()
        kwargs = audit.call_args.kwargs
        self.assertEqual(kwargs["tenant_id"], T1)
        self.assertEqual(kwargs["actor_user_id"], "u1")
        self.assertEqual(kwargs["action"], "settings.updated")
        self.assertEqual(kwargs["metadata"], {"updated_keys": ["reach_weekly_limit"]})

    def test_put_needs_settings_manage(self):
        self.ctx = VIEW_ONLY
        res = self.client.put(URL, json={"weekly_limit": 5})
        self.assertEqual(res.status_code, 403, res.text)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_settings_manager_can_save(self):
        self.ctx = SETTINGS_MANAGER
        self.assertEqual(self.client.put(URL, json={"weekly_limit": 7}).status_code, 200)

    def test_one_tenant_never_sees_anothers_number(self):
        self.ctx = {**OWNER, "tenant_id": T2}
        self.assertEqual(self.client.put(URL, json={"weekly_limit": 9}).status_code, 200)
        self.ctx = OWNER
        self.assertEqual(self.client.get(URL).json()["weekly_limit"], 2)


if __name__ == "__main__":
    unittest.main()
