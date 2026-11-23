"""Item 234: an upload remembers the rows it took out and why; history, results and the taken-out file."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, require_owner
from app.main import app
from tests.fake_supabase import FakeSupabase

T = "tenant-1"
OWNER = {"tenant_id": T, "role": "owner", "user_id": "user-1", "caller_id": None, "permissions": []}
CSV = (
    "phone,name\n"
    "9876543210,New A\n"
    "abc,Bad\n"
    "9876543210,New A again\n"
    "9000000002,Stopper\n"
    "9000000003,Customer\n"
    "9000000004,Held\n"
).encode()


class TakenOutTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.db.add("callers", id="c1", tenant_id=T, name="Asha", active=True, user_id="u2")
        base = dict(tenant_id=T, deleted_at=None, converted_at=None, do_not_call=False, call_status="new", assigned_to=None)
        self.db.add("leads", id="l-dnc", phone="+919000000002", **{**base, "do_not_call": True})
        self.db.add("leads", id="l-cust", phone="+919000000003", **{**base, "converted_at": "2026-10-01T00:00:00+00:00"})
        self.db.add("leads", id="l-held", phone="+919000000004", **{**base, "assigned_to": "c1"})
        self.ctx = dict(OWNER)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[require_owner] = lambda: self.ctx
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        self.client = TestClient(app)
        cfg = {"enabled": True, "segments": ["A"], "assignment_mode": "push", "channel_rules": {"upload": {"enabled": True, "mode": "auto"}}}
        for p in [
            patch("app.routes.telecalling_upload.get_supabase", return_value=self.db),
            patch("app.routes.telecalling_upload.get_telecalling_config", side_effect=lambda tid: cfg),
            patch("app.routes.telecalling_upload.new_lead_score_and_segment", return_value=(50, "A")),
            patch("app.routes.telecalling_upload.assign_upload_batch", MagicMock(side_effect=lambda db, t, ids, c: ([], []))),
            patch("app.routes.telecalling_upload.add_upload_pending", MagicMock()),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _upload(self):
        res = self.client.post("/api/v1/telecalling-upload/upload", files={"file": ("f.csv", CSV, "text/csv")})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_upload_saves_why_each_row_was_taken_out(self):
        body = self._upload()
        self.assertEqual(body["taken_out"], 5)
        batch = self.db.rows("telecalling_upload_batches")[0]
        reasons = {(r["row"], r["reason"]) for r in batch["taken_out"]}
        self.assertEqual(reasons, {(3, "bad_number"), (2, "duplicate"), (5, "said_stop"), (6, "already_customer"), (7, "already_with_caller")})
        self.assertEqual(batch["taken_out_counts"]["bad_number"], 1)

    def test_history_shows_counts_not_rows_and_dash_for_old_uploads(self):
        self._upload()
        self.db.add("telecalling_upload_batches", tenant_id=T, file_name="old.csv", total_contacts=1, inserted=1,
                    duplicates=0, assigned=0, assignment_snapshot=[], created_at="2020-01-01T00:00:00+00:00")
        rows = self.client.get("/api/v1/telecalling-upload/history").json()
        new = next(r for r in rows if r["file_name"] == "f.csv")
        old = next(r for r in rows if r["file_name"] == "old.csv")
        self.assertEqual(sum(new["taken_out_counts"].values()), 5)
        self.assertNotIn("taken_out", new)
        self.assertIsNone(old["taken_out_counts"])

    def test_taken_out_file_downloads_with_reasons_and_is_logged(self):
        self._upload()
        batch_id = self.db.rows("telecalling_upload_batches")[0]["id"]
        res = self.client.get(f"/api/v1/telecalling-upload/history/{batch_id}/taken-out")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Said stop", res.text)
        self.assertIn("Repeated in the file", res.text)
        self.assertEqual(len([r for r in self.db.rows("app_audit_logs") if r.get("action") == "leads.download"]), 1)

    def test_download_name_is_safe_for_non_english_file_names(self):
        self.db.add("telecalling_upload_batches", id="22222222-2222-4222-8222-222222222222", tenant_id=T,
                    file_name="தொடர்பு.csv", assignment_snapshot=[], taken_out=[{"row": 2, "phone": "1", "name": None, "reason": "bad_number"}])
        res = self.client.get("/api/v1/telecalling-upload/history/22222222-2222-4222-8222-222222222222/taken-out")
        self.assertEqual(res.status_code, 200, res.text)
        header = res.headers["content-disposition"]
        self.assertIn("filename*=UTF-8''", header)
        self.assertTrue(header.isascii())

    def test_history_does_not_pull_the_taken_out_list(self):
        self.db.add("telecalling_upload_batches", tenant_id=T, file_name="a.csv", assignment_snapshot=[],
                    taken_out=[{"row": 2}], taken_out_counts={"bad_number": 1}, created_at="2026-11-20T00:00:00+00:00")
        row = self.client.get("/api/v1/telecalling-upload/history").json()[0]
        self.assertNotIn("taken_out", row)
        self.assertEqual(row["taken_out_counts"], {"bad_number": 1})

    def test_no_file_for_an_old_upload_or_another_tenant(self):
        old = self.db.add("telecalling_upload_batches", tenant_id=T, file_name="old.csv", assignment_snapshot=[])
        other = self.db.add("telecalling_upload_batches", tenant_id="t2", file_name="x.csv", assignment_snapshot=[], taken_out=[])
        self.assertEqual(self.client.get(f"/api/v1/telecalling-upload/history/{old['id']}/taken-out").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/telecalling-upload/history/{other['id']}/taken-out").status_code, 404)

    def test_results_counts_calls_after_the_upload(self):
        self.db.add("telecalling_upload_batches", id="11111111-1111-4111-8111-111111111111", tenant_id=T, file_name="a.csv",
                    created_at="2026-11-20T00:00:00+00:00",
                    assignment_snapshot=[{"lead_id": "l-held", "caller_id": "c1"}, {"lead_id": "l-cust", "caller_id": "c1"}])
        self.db.add("call_logs", tenant_id=T, lead_id="l-held", created_at="2026-11-21T00:00:00+00:00", manual_status="connected", outcome="converted")
        self.db.add("call_logs", tenant_id=T, lead_id="l-cust", created_at="2026-11-19T00:00:00+00:00", manual_status="connected")
        res = self.client.get("/api/v1/telecalling-upload/history/results?batch_ids=11111111-1111-4111-8111-111111111111")
        self.assertEqual(res.json()["11111111-1111-4111-8111-111111111111"], {"called": 1, "reached": 1, "converted": 1})
        self.assertEqual(self.client.get("/api/v1/telecalling-upload/history/results?batch_ids=nope").status_code, 400)


if __name__ == "__main__":
    unittest.main()
