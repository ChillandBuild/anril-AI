"""Tests for GET /api/v1/calls/recent — the dialer's Recent tab.

Per-lead history already exists; this one answers "what did I call today?"
across leads. Two things matter: a caller may only ever see their own calls,
and the route must not be shadowed by the `/{call_log_id}` catch-all.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role

ROW = {
    "id": "call-1",
    "created_at": "2026-09-19T08:03:07+00:00",
    "duration_seconds": 177,
    "status": "completed",
    "outcome": "interested_needs_time",
    "score": 7.5,
    "evaluation": {"overall_score": 7.6},
    "ai_summary": {"brief": "Discussed pricing."},
    "recording_url": "https://storage.test/call-1.wav",
    "transcript": "hello",
    "lead_id": "lead-1",
    "caller_id": "caller-1",
    "leads": {"name": "Keerthi", "phone": "+916369781582"},
    "callers": {"name": "Prem Kannan"},
}


class RecentCallsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def _as(self, role: str, caller_id: str | None = None):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "tenant-1", "role": role, "caller_id": caller_id, "permissions": [],
        }

    def _mock_db(self, mock_get_db, rows=(ROW,)):
        db = MagicMock()
        base = db.table.return_value.select.return_value.eq.return_value
        # no caller filter
        base.order.return_value.limit.return_value.execute.return_value = MagicMock(data=list(rows))
        # with caller filter
        base.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=list(rows))
        mock_get_db.return_value = db
        return db, base

    @patch("app.routes.calls.get_supabase")
    def test_returns_calls_under_data_with_lead_and_caller_names(self, mock_get_db):
        self._as("owner")
        self._mock_db(mock_get_db)

        res = self.client.get("/api/v1/calls/recent")

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["leads"]["name"], "Keerthi")
        self.assertEqual(body["data"][0]["callers"]["name"], "Prem Kannan")

    @patch("app.routes.calls.get_supabase")
    def test_route_is_not_shadowed_by_the_call_log_id_route(self, mock_get_db):
        """`/recent` must resolve before `/{call_log_id}`, else it 404s."""
        self._as("owner")
        self._mock_db(mock_get_db)

        self.assertEqual(self.client.get("/api/v1/calls/recent").status_code, 200)

    @patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "telecmi"})
    @patch("app.routes.calls.get_supabase")
    def test_a_caller_only_sees_their_own_calls(self, mock_get_db, _cfg):
        self._as("caller", caller_id="caller-1")
        _, base = self._mock_db(mock_get_db)

        self.client.get("/api/v1/calls/recent?caller_id=someone-else")

        base.eq.assert_any_call("caller_id", "caller-1")  # later calls read the number-hiding rules

    @patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "telecmi"})
    @patch("app.routes.calls.get_supabase")
    def test_an_admin_can_filter_by_caller(self, mock_get_db, _cfg):
        self._as("owner")
        _, base = self._mock_db(mock_get_db)

        self.client.get("/api/v1/calls/recent?caller_id=caller-2")

        base.eq.assert_called_with("caller_id", "caller-2")

    @patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "telecmi"})
    @patch("app.routes.calls.get_supabase")
    def test_an_admin_without_a_caller_filter_sees_every_caller(self, mock_get_db, _cfg):
        self._as("owner")
        _, base = self._mock_db(mock_get_db)

        self.client.get("/api/v1/calls/recent")

        base.eq.assert_not_called()
        base.order.assert_called_with("created_at", desc=True)

    @patch("app.routes.calls.get_supabase")
    def test_limit_is_passed_through_and_bounded(self, mock_get_db):
        self._as("owner")
        _, base = self._mock_db(mock_get_db)

        self.client.get("/api/v1/calls/recent?limit=5")
        base.order.return_value.limit.assert_called_with(5)

        self.assertEqual(self.client.get("/api/v1/calls/recent?limit=0").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/calls/recent?limit=51").status_code, 422)

    @patch("app.routes.calls.get_supabase")
    def test_no_calls_returns_an_empty_list(self, mock_get_db):
        self._as("owner")
        self._mock_db(mock_get_db, rows=())

        self.assertEqual(self.client.get("/api/v1/calls/recent").json()["data"], [])

    @patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "sim_basic"})
    @patch("app.routes.calls.get_supabase")
    def test_sim_tenant_has_no_evaluation_fields(self, mock_get_db, _cfg):
        self._as("owner")
        self._mock_db(mock_get_db)

        row = self.client.get("/api/v1/calls/recent").json()["data"][0]

        for field in ("score", "score_status", "score_final", "evaluation", "call_group", "talk_share",
                      "interruption_count", "interruptions_per_5min"):
            self.assertNotIn(field, row)

    @patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "telecmi"})
    @patch("app.routes.calls.get_supabase")
    def test_telecmi_tenant_keeps_evaluation_fields(self, mock_get_db, _cfg):
        self._as("owner")
        self._mock_db(mock_get_db)

        row = self.client.get("/api/v1/calls/recent").json()["data"][0]

        self.assertEqual(row["score"], 7.5)
        self.assertEqual(row["evaluation"], {"overall_score": 7.6})


if __name__ == "__main__":
    unittest.main()
