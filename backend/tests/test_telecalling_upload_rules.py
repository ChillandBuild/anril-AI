"""POST /api/v1/telecalling-upload/upload follows the 'upload' row of the telecalling rules."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import require_owner
from tests.fake_supabase import FakeSupabase

URL = "/api/v1/telecalling-upload/upload"
TENANT = "tenant-1"

NEW_A = "+919876543210"
NEW_B = "+919876543211"
OPEN_EXISTING = "+919000000001"
DNC_EXISTING = "+919000000002"
CONVERTED_EXISTING = "+919000000003"
CLOSED_STATUS_EXISTING = "+919000000004"

CSV = (
    "phone,name\n"
    "9876543210,New A\n"
    "9876543211,New B\n"
    "9000000001,Open existing\n"
    "9000000002,Do not call\n"
    "9000000003,Converted\n"
    "9000000004,Wrong number\n"
).encode("utf-8")


def _cfg(enabled=True, upload=None):
    rules = {"upload": upload or {"enabled": True, "mode": "auto"}}
    return {"enabled": enabled, "segments": ["A"], "assignment_mode": "push", "channel_rules": rules}


class UploadRulesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.fake = FakeSupabase()
        self.fake.add("callers", id="caller-1", tenant_id=TENANT, name="Asha", active=True, user_id="u-2")
        # Existing leads: one open (unassigned), and four that must never be handed out again.
        self.fake.add("leads", id="lead-open", tenant_id=TENANT, phone=OPEN_EXISTING, assigned_to=None,
                      do_not_call=False, call_status="new", converted_at=None, deleted_at=None)
        self.fake.add("leads", id="lead-dnc", tenant_id=TENANT, phone=DNC_EXISTING, assigned_to=None,
                      do_not_call=True, call_status="new", converted_at=None, deleted_at=None)
        self.fake.add("leads", id="lead-converted", tenant_id=TENANT, phone=CONVERTED_EXISTING, assigned_to=None,
                      do_not_call=False, call_status="new", converted_at="2026-10-01T00:00:00+00:00", deleted_at=None)
        self.fake.add("leads", id="lead-wrong", tenant_id=TENANT, phone=CLOSED_STATUS_EXISTING, assigned_to=None,
                      do_not_call=False, call_status="wrong_number", converted_at=None, deleted_at=None)

        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[require_owner] = lambda: {
            "tenant_id": TENANT, "role": "owner", "user_id": "user-1", "permissions": [],
        }
        self.cfg = _cfg()
        # assign_upload_batch(db, tenant_id, lead_ids, cfg) -> (assignments, unplaced)
        self.assign = MagicMock(side_effect=lambda db, tid, ids, cfg: (
            [{"lead_id": i, "caller_id": "caller-1", "caller_name": "Asha"} for i in ids], [],
        ))
        self.add_pending = MagicMock()
        patches = [
            patch("app.routes.telecalling_upload.get_supabase", return_value=self.fake),
            patch("app.routes.telecalling_upload.get_telecalling_config", side_effect=lambda tid: self.cfg),
            patch("app.routes.telecalling_upload.new_lead_score_and_segment", return_value=(50, "A")),
            patch("app.routes.telecalling_upload.assign_upload_batch", self.assign),
            patch("app.routes.telecalling_upload.add_upload_pending", self.add_pending),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _upload(self):
        res = self.client.post(URL, files={"file": ("contacts.csv", CSV, "text/csv")})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _id_for(self, phone):
        return next(r["id"] for r in self.fake.rows("leads") if r["phone"] == phone)

    def _new_lead_ids(self):
        return {self._id_for(NEW_A), self._id_for(NEW_B)}

    def test_master_switch_off_assigns_nothing_and_remembers_nothing(self):
        self.cfg = _cfg(enabled=False)

        body = self._upload()

        self.assign.assert_not_called()
        self.add_pending.assert_not_called()
        self.assertEqual(body["assigned"], 0)
        self.assertEqual(body["inserted"], 2)

    def test_upload_row_off_assigns_nothing_and_remembers_nothing(self):
        self.cfg = _cfg(upload={"enabled": False, "mode": "auto"})

        body = self._upload()

        self.assign.assert_not_called()
        self.add_pending.assert_not_called()
        self.assertEqual(body["assigned"], 0)

    def test_pull_mode_remembers_the_new_leads_as_pending_without_assigning(self):
        self.cfg = _cfg(upload={"enabled": True, "mode": "pull"})

        body = self._upload()

        self.assign.assert_not_called()
        self.add_pending.assert_called_once()
        pending_ids = set(self.add_pending.call_args.args[2])
        self.assertEqual(pending_ids, self._new_lead_ids() | {"lead-open"})
        self.assertEqual(body["assigned"], 0)

    def test_auto_mode_assigns_the_whole_file_in_one_batch(self):
        body = self._upload()

        # One batch call for the whole file, not one call per lead.
        self.assign.assert_called_once()
        self.assertEqual(set(self.assign.call_args.args[2]), self._new_lead_ids() | {"lead-open"})
        self.add_pending.assert_not_called()
        self.assertEqual(body["assigned"], 3)

    def test_leads_nobody_can_take_yet_are_remembered_as_pending(self):
        self.cfg = _cfg(upload={"enabled": True, "mode": "available"})
        self.assign.side_effect = lambda db, tid, ids, cfg: (
            [{"lead_id": i, "caller_id": "caller-1", "caller_name": "Asha"} for i in ids if i != "lead-open"],
            ["lead-open"],
        )

        body = self._upload()

        self.add_pending.assert_called_once()
        self.assertEqual(self.add_pending.call_args.args[2], ["lead-open"])
        self.assertEqual(body["assigned"], 2)

    def test_closed_existing_leads_are_never_assigned(self):
        self._upload()

        assigned_ids = set(self.assign.call_args.args[2])
        for closed in ("lead-dnc", "lead-converted", "lead-wrong"):
            self.assertNotIn(closed, assigned_ids)

    def test_snapshot_records_the_caller_name_from_the_assignment(self):
        self._upload()

        batch = self.fake.rows("telecalling_upload_batches")[0]
        names = {row["lead_id"]: row["caller_name"] for row in batch["assignment_snapshot"]}
        self.assertEqual(names[self._id_for(NEW_A)], "Asha")


if __name__ == "__main__":
    unittest.main()
