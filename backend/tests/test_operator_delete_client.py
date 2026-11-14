"""Tests for DELETE /operator/clients/{id} -- the "Delete Client Forever" button.

Regression: knowledge_versions, knowledge_reviews and employee_todos point at
tenants with a no-cascade foreign key but were missing from _ALL_TENANT_TABLES,
so the final tenants delete was refused (500 "Internal server error") after
everything else had already been wiped -- leaving a half-deleted client whose
login accounts could no longer be found on retry."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.system_admin import get_system_admin

# Tables with a no-cascade tenant_id FK in the live DB (checked 2026-11-14).
# Every one must be cleared before the tenants row can go.
BLOCKING_TABLES = {
    "caller_attendance_overrides", "employee_todos", "leads", "messages",
    "call_logs", "callers", "phone_numbers", "lead_notes", "follow_up_jobs",
    "segment_templates", "app_settings", "incidents", "message_templates",
    "lead_stage_events", "knowledge_documents", "broadcast_recipients",
    "voice_numbers", "ad_campaigns", "bot_flows", "broadcast_failed_contacts",
    "caller_status_logs", "meta_templates", "whatsapp_insights_snapshots",
    "conversations", "knowledge_versions", "knowledge_reviews",
}


class OperatorDeleteClientTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def _mock_db(self, mock_get_db, blocking_tables=BLOCKING_TABLES):
        """A fake DB that refuses the tenants delete while any blocking table
        has not been cleared -- like Postgres' foreign-key check."""
        db = MagicMock()
        cleared: list[str] = []
        tables: dict = {}

        def table(name):
            if name in tables:
                return tables[name]
            tbl = MagicMock()
            if name == "tenants":
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
                    "id": "tenant-1", "name": "Acme",
                }

                def tenants_delete_execute():
                    missing = sorted(set(blocking_tables) - set(cleared))
                    if missing:
                        raise Exception(
                            'update or delete on table "tenants" violates foreign key constraint '
                            f'"{missing[0]}_tenant_id_fkey" on table "{missing[0]}"'
                        )
                    return MagicMock(data=[{"id": "tenant-1"}])

                tbl.delete.return_value.eq.return_value.execute.side_effect = tenants_delete_execute
            else:
                if name == "tenant_users":
                    tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                        {"user_id": "owner-1"},
                    ]
                if name == "callers":
                    tbl.select.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = [
                        {"user_id": "caller-1"},
                    ]

                def make_execute(n):
                    def _execute():
                        cleared.append(n)
                        return MagicMock(data=[])
                    return _execute

                tbl.delete.return_value.eq.return_value.execute.side_effect = make_execute(name)
            tables[name] = tbl
            return tbl

        db.table.side_effect = table
        mock_get_db.return_value = db
        return db, cleared

    @patch("app.routes.operator.get_supabase")
    def test_delete_clears_every_blocking_table_and_succeeds(self, mock_get_db):
        db, cleared = self._mock_db(mock_get_db)

        res = self.client.delete("/api/v1/operator/clients/tenant-1")

        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"deleted": True, "tenant_name": "Acme"})
        self.assertTrue(BLOCKING_TABLES <= set(cleared), sorted(BLOCKING_TABLES - set(cleared)))
        deleted_users = {c.args[0] for c in db.auth.admin.delete_user.call_args_list}
        self.assertEqual(deleted_users, {"owner-1", "caller-1"})

    @patch("app.routes.operator.get_supabase")
    def test_blocked_delete_names_the_table_and_still_removes_logins(self, mock_get_db):
        """If a future table is forgotten, the operator sees which one -- not a
        bare "Internal server error" -- and the login accounts are still removed,
        because after the wipe there is no way left to find them."""
        db, _ = self._mock_db(mock_get_db, blocking_tables=BLOCKING_TABLES | {"some_new_table"})

        res = self.client.delete("/api/v1/operator/clients/tenant-1")

        self.assertEqual(res.status_code, 409)
        self.assertIn("some_new_table", res.json()["detail"])
        deleted_users = {c.args[0] for c in db.auth.admin.delete_user.call_args_list}
        self.assertEqual(deleted_users, {"owner-1", "caller-1"})


if __name__ == "__main__":
    unittest.main()
