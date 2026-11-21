"""GET /api/v1/callers/my-calls-today and GET /api/v1/callers/{id}/logs: SIM
clients get no evaluation at all -- their call-log rows must not carry
score/evaluation fields either."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_owner_tenant_id

CALLER_ID = "0761bbde-8626-42c3-963e-327f162ca37e"
_SCORED_ROW = {
    "id": "c1", "score": 82.0, "score_status": "scored", "score_final": True,
    "evaluation": {"checks": []}, "call_group": "real_conversation", "talk_share": 0.6,
    "interruption_count": 1, "interruptions_per_5min": 0.5,
}
_EVALUATION_FIELDS = ("score", "score_status", "score_final", "evaluation", "call_group", "talk_share",
                      "interruption_count", "interruptions_per_5min")


class MyCallsTodayGateTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t1", "role": "caller", "user_id": "user-1", "caller_id": CALLER_ID, "permissions": [],
        }

    def tearDown(self):
        app.dependency_overrides.clear()

    def _get(self, calling_provider):
        db = MagicMock()
        chain = db.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.order.return_value
        chain.execute.return_value = MagicMock(data=[dict(_SCORED_ROW)])
        with patch("app.routes.callers.get_supabase", return_value=db), \
             patch("app.routes.callers.get_telecalling_config", return_value={"calling_provider": calling_provider}):
            return self.client.get("/api/v1/callers/my-calls-today")

    def test_sim_has_no_evaluation_fields(self):
        row = self._get("sim_basic").json()["data"][0]
        for field in _EVALUATION_FIELDS:
            self.assertNotIn(field, row)

    def test_telecmi_is_unchanged(self):
        row = self._get("telecmi").json()["data"][0]
        self.assertEqual(row["score"], 82.0)


class CallerLogsGateTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t1", "role": "owner", "user_id": "user-1", "permissions": []}

    def tearDown(self):
        app.dependency_overrides.clear()

    def _get(self, calling_provider):
        db = MagicMock()
        chain = db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[dict(_SCORED_ROW)])
        with patch("app.routes.callers.get_supabase", return_value=db), \
             patch("app.routes.callers.get_telecalling_config", return_value={"calling_provider": calling_provider}):
            return self.client.get(f"/api/v1/callers/{CALLER_ID}/logs")

    def test_sim_has_no_evaluation_fields(self):
        row = self._get("sim_basic").json()["data"][0]
        for field in _EVALUATION_FIELDS:
            self.assertNotIn(field, row)

    def test_telecmi_is_unchanged(self):
        row = self._get("telecmi").json()["data"][0]
        self.assertEqual(row["score"], 82.0)


if __name__ == "__main__":
    unittest.main()
