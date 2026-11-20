"""GET /api/v1/rbac/audit-log must be tenant-scoped (never leak another
tenant's rows), restricted to team/role actions only (not the full
app_audit_logs firehose -- settings changes, operator actions, etc. that
the same table also holds for this tenant), and gated by the same
roles.view/roles.manage permission as the rest of the Roles page."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role

CTX = {
    "tenant_id": "tenant-1",
    "role": "owner",
    "user_id": "owner-1",
    "caller_id": None,
    "permissions": ["roles.manage"],
}


class TestAuditLogEndpoint(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "owner-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: CTX

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.routes.rbac.get_supabase")
    def test_scopes_query_to_tenant_and_team_role_actions_only(self, mock_get_supabase):
        db = MagicMock()
        audit_tbl = MagicMock()
        chain = audit_tbl.select.return_value.eq.return_value.or_.return_value
        chain.order.return_value.range.return_value.execute.return_value = MagicMock(
            data=[{"id": "a1", "actor_user_id": "owner-1", "actor_role": "owner", "action": "team.member_deleted",
                   "target_type": "tenant_user", "target_id": "user-1", "metadata": {}, "created_at": "2026-08-08T00:00:00Z"}],
            count=1,
        )
        db.table.return_value = audit_tbl
        mock_get_supabase.return_value = db

        client = TestClient(app)
        resp = client.get("/api/v1/rbac/audit-log")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(len(body["data"]), 1)
        audit_tbl.select.return_value.eq.assert_called_with("tenant_id", "tenant-1")
        # Must not return the full app_audit_logs firehose for this tenant --
        # only team.* / role.* actions and what the Anril AI connector did (claude.*) belong there.
        audit_tbl.select.return_value.eq.return_value.or_.assert_called_once_with(
            "action.like.team.%,action.like.role.%,action.like.claude.%"
        )


if __name__ == "__main__":
    unittest.main()
