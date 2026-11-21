"""Undo an upload (owner only), the upload history for a Team leader, and the history CSV download rule.

"Undo upload" removes only the people THIS upload added who nobody has touched. Anything in doubt stays.
"""
import csv
import io
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from tests.fake_supabase import FakeSupabase

BATCH_AT = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
iso = lambda dt: dt.isoformat()
JUST_BEFORE = iso(BATCH_AT - timedelta(minutes=1))
LONG_BEFORE = iso(BATCH_AT - timedelta(days=30))

OWNER = {"tenant_id": "t1", "role": "owner", "user_id": "owner-1", "caller_id": None, "permissions": []}
LEADER = {"tenant_id": "t1", "role": "caller", "user_id": "lead-1", "caller_id": "c1",
          "permissions": ["telecalling.upload.view", "telecalling.upload"]}


def lead(db, lid, created=JUST_BEFORE, **extra):
    row = {"id": lid, "tenant_id": "t1", "name": lid, "phone": "+91" + lid, "source": "upload", "created_at": created,
           "deleted_at": None, "ai_enabled": True, "call_status": "new"}
    row.update(extra)
    db.rows("leads").append(row)


def snap(lid, caller="c1", new=True):
    row = {"lead_id": lid, "phone": "+91" + lid, "name": lid, "caller_id": caller, "caller_name": caller.upper()}
    if new is not None:
        row["new"] = new
    return row


class UploadUndoTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.patch = patch("app.routes.telecalling_upload.get_supabase", return_value=self.db)
        self.patch.start()
        self.ctx = dict(OWNER)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        self.client = TestClient(app)

        # One upload, "Nov fair.xlsx": 7 leads in the file.
        lead(self.db, "fresh")                                   # new, nobody touched it
        lead(self.db, "called")                                  # new, but called
        lead(self.db, "messaged")                                # new, but messaged
        lead(self.db, "quoted")                                  # new, has a deal
        lead(self.db, "scheduled")                               # new, has a follow-up job
        lead(self.db, "old", created=LONG_BEFORE, source="whatsapp")   # was already a customer
        lead(self.db, "wrapped", call_status="callback")         # new, but its status moved on
        self.db.rows("call_logs").append({"id": "cl1", "tenant_id": "t1", "lead_id": "called"})
        self.db.rows("messages").append({"id": "m1", "tenant_id": "t1", "lead_id": "messaged"})
        self.db.rows("deals").append({"id": "d1", "tenant_id": "t1", "lead_id": "quoted"})
        self.db.rows("follow_up_jobs").append({"id": "f1", "tenant_id": "t1", "lead_id": "scheduled"})
        self.db.rows("tenant_users").append({"user_id": "owner-1", "tenant_id": "t1", "full_name": "Prem"})
        self.snapshot = [snap(i) for i in ("fresh", "called", "messaged", "quoted", "scheduled", "wrapped")] + [snap("old", new=False)]
        self.db.rows("telecalling_upload_batches").append({
            "id": "00000000-0000-0000-0000-0000000000a1", "tenant_id": "t1", "file_name": "Nov fair.xlsx", "total_contacts": 7, "inserted": 6, "duplicates": 1,
            "assigned": 7, "created_at": iso(BATCH_AT), "assignment_snapshot": self.snapshot,
        })

    def tearDown(self):
        app.dependency_overrides.clear()
        self.patch.stop()

    def _lead(self, lid):
        return next(r for r in self.db.rows("leads") if r["id"] == lid)

    def _batch(self, bid="00000000-0000-0000-0000-0000000000a1"):
        return next(r for r in self.db.rows("telecalling_upload_batches") if r["id"] == bid)

    # ── the rule ─────────────────────────────────────────────────────────────

    def test_preview_counts_what_goes_and_what_stays(self):
        res = self.client.get("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo-preview")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual((body["will_remove"], body["will_keep"]), (1, 6))
        self.assertEqual(body["keep_reasons"], {"existing": 1, "touched": 5, "unsure": 0})
        self.assertIsNone(self._lead("fresh")["deleted_at"])  # a preview changes nothing

    def test_undo_removes_only_new_and_uncalled_people(self):
        res = self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["removed"], 1)
        self.assertEqual(res.json()["kept"], 6)
        self.assertIsNotNone(self._lead("fresh")["deleted_at"])
        self.assertFalse(self._lead("fresh")["ai_enabled"])
        for stays in ("called", "messaged", "quoted", "scheduled", "old", "wrapped"):
            self.assertIsNone(self._lead(stays)["deleted_at"], stays)

    def test_undo_records_who_when_how_many_and_writes_the_activity_log(self):
        self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo")
        batch = self._batch()
        self.assertIsNotNone(batch["undone_at"])
        self.assertEqual((batch["undone_by"], batch["undone_count"]), ("owner-1", 1))
        audit = self.db.rows("app_audit_logs")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "telecalling_upload.undone")
        self.assertEqual(audit[0]["actor_user_id"], "owner-1")
        self.assertEqual(audit[0]["metadata"]["file_name"], "Nov fair.xlsx")
        self.assertEqual((audit[0]["metadata"]["removed"], audit[0]["metadata"]["kept"]), (1, 6))

    def test_a_second_undo_is_refused_with_409(self):
        self.assertEqual(self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").status_code, 200)
        again = self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.client.get("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo-preview").status_code, 409)
        self.assertEqual(len(self.db.rows("app_audit_logs")), 1)

    def test_a_lead_that_was_called_after_the_preview_is_not_removed(self):
        self.db.rows("call_logs").append({"id": "cl2", "tenant_id": "t1", "lead_id": "fresh"})
        self.assertEqual(self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").json()["removed"], 0)
        self.assertIsNone(self._lead("fresh")["deleted_at"])

    def test_a_lead_with_a_note_or_in_a_broadcast_stays(self):
        self.db.rows("lead_notes").append({"id": "n1", "tenant_id": "t1", "lead_id": "fresh"})
        self.assertEqual(self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").json()["removed"], 0)

    def test_a_lead_marked_new_but_created_outside_the_upload_window_stays(self):
        self._lead("fresh")["created_at"] = LONG_BEFORE
        self.assertEqual(self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").json()["removed"], 0)

    def test_removed_people_leave_the_pending_queue(self):
        with patch("app.routes.telecalling_upload.remove_upload_pending") as drop:
            self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo")
        self.assertEqual(drop.call_args.args[2], ["fresh"])

    # ── older batches (no "new" flag in the snapshot) ────────────────────────

    def _legacy_batch(self, inserted):
        batch = self._batch()
        batch["assignment_snapshot"] = [snap(i, new=None) for i in ("fresh", "called", "old")]
        batch["inserted"] = inserted

    def test_an_older_batch_uses_the_time_window_and_source(self):
        self._legacy_batch(inserted=2)
        body = self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").json()
        self.assertEqual(body["removed"], 1)  # fresh goes; called has a call; old is outside the window
        self.assertIsNone(self._lead("old")["deleted_at"])

    def test_an_older_batch_that_matches_more_leads_than_it_inserted_removes_nothing(self):
        self._legacy_batch(inserted=1)  # fresh + called both look new, only 1 was inserted: can't tell which
        body = self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").json()
        self.assertEqual(body["removed"], 0)
        self.assertIsNone(self._lead("fresh")["deleted_at"])

    # ── who and where ────────────────────────────────────────────────────────

    def test_only_the_owner_can_undo_or_preview(self):
        self.ctx = dict(LEADER)
        self.assertEqual(self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo-preview").status_code, 403)
        self.ctx = {**OWNER, "role": "caller", "permissions": ["telecalling.upload"]}
        self.assertEqual(self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo").status_code, 403)
        self.assertIsNone(self._lead("fresh")["deleted_at"])

    def test_another_clients_batch_is_not_found(self):
        self.db.rows("telecalling_upload_batches").append({
            "id": "00000000-0000-0000-0000-0000000000a3", "tenant_id": "t2", "file_name": "x.csv", "created_at": iso(BATCH_AT), "assignment_snapshot": [snap("fresh")],
        })
        self.assertEqual(self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a3/undo").status_code, 404)
        self.assertIsNone(self._lead("fresh")["deleted_at"])

    def test_nothing_is_removed_when_the_undo_cannot_be_recorded(self):
        # Migration 307 not applied: the batch has no undone_* columns, so the update is refused.
        real = self.db.table

        def table(name):
            q = real(name)
            if name == "telecalling_upload_batches":
                original = q.update

                def update(payload):
                    if "undone_at" in payload:
                        raise Exception('column "undone_at" of relation "telecalling_upload_batches" does not exist')
                    return original(payload)
                q.update = update
            return q
        self.db.table = table
        res = self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo")
        self.assertEqual(res.status_code, 503)
        self.assertIsNone(self._lead("fresh")["deleted_at"])

    def test_nothing_is_removed_when_the_calls_cannot_be_checked(self):
        real = self.db.table

        def table(name):
            if name == "call_logs":
                raise Exception("db down")
            return real(name)
        self.db.table = table
        res = self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo")
        self.assertEqual(res.status_code, 503)
        self.assertIsNone(self._lead("fresh")["deleted_at"])
        self.assertIsNone(self._batch()["undone_at"] if "undone_at" in self._batch() else None)

    def test_the_new_flag_is_written_for_leads_this_upload_creates(self):
        src = (Path(__file__).resolve().parents[1] / "app" / "routes" / "telecalling_upload.py").read_text()
        self.assertIn('"new": str(ld["id"]) in inserted_id_set', src)

    # ── the history list ─────────────────────────────────────────────────────

    def test_history_shows_undone_by_name_and_the_undo_button_flag(self):
        before = self.client.get("/api/v1/telecalling-upload/history").json()
        self.assertTrue(before[0]["can_undo"])
        self.client.post("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/undo")
        after = self.client.get("/api/v1/telecalling-upload/history").json()[0]
        self.assertFalse(after["can_undo"])
        self.assertEqual((after["undone_by_name"], after["undone_count"]), ("Prem", 1))

    def test_a_team_leader_sees_only_their_teams_rows_and_never_an_undo_button(self):
        self.db.rows("telecalling_upload_batches").append({
            "id": "00000000-0000-0000-0000-0000000000a2", "tenant_id": "t1", "file_name": "Other team.csv", "created_at": iso(BATCH_AT - timedelta(days=1)),
            "assignment_snapshot": [snap("x", caller="c9")], "assigned": 1,
        })
        self.ctx = dict(LEADER)
        with patch("app.routes.telecalling_upload.is_team_leader", return_value=True), \
             patch("app.routes.telecalling_upload.scoped_caller_ids", return_value={"c1"}):
            rows = self.client.get("/api/v1/telecalling-upload/history").json()
        self.assertEqual([r["id"] for r in rows], ["00000000-0000-0000-0000-0000000000a1"])
        self.assertEqual({r["caller_id"] for r in rows[0]["assignment_snapshot"]}, {"c1"})
        self.assertEqual(rows[0]["assigned"], 7)
        self.assertFalse(rows[0]["can_undo"])

    def test_someone_who_is_not_a_team_leader_still_cannot_open_the_history(self):
        self.ctx = dict(LEADER)
        with patch("app.routes.telecalling_upload.is_team_leader", return_value=False):
            self.assertEqual(self.client.get("/api/v1/telecalling-upload/history").status_code, 403)

    # ── download rule on the history CSV ─────────────────────────────────────

    def test_history_csv_needs_leads_download_and_writes_the_activity_log(self):
        self.ctx = {**LEADER, "permissions": ["telecalling.upload.view"]}
        with patch("app.routes.telecalling_upload.is_team_leader", return_value=True), \
             patch("app.routes.telecalling_upload.scoped_caller_ids", return_value={"c1"}):
            denied = self.client.get("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/csv")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"], "You don't have permission to download lists.")
        self.assertEqual(self.db.rows("app_audit_logs"), [])

        self.ctx = dict(OWNER)
        ok = self.client.get("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/csv")
        self.assertEqual(ok.status_code, 200, ok.text)
        audit = self.db.rows("app_audit_logs")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "leads.download")
        self.assertEqual(audit[0]["metadata"]["list"], "Upload assignments: Nov fair.xlsx")
        self.assertEqual(audit[0]["metadata"]["rows"], 7)

    def test_a_team_leader_with_download_gets_only_their_teams_rows(self):
        self._batch()["assignment_snapshot"] = [snap("fresh", "c1"), snap("called", "c9")]
        self.ctx = {**LEADER, "permissions": ["telecalling.upload.view", "leads.download"]}
        with patch("app.routes.telecalling_upload.is_team_leader", return_value=True), \
             patch("app.routes.telecalling_upload.scoped_caller_ids", return_value={"c1"}):
            res = self.client.get("/api/v1/telecalling-upload/history/00000000-0000-0000-0000-0000000000a1/csv")
        self.assertEqual(res.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(res.text)))
        self.assertEqual([r["lead_id"] for r in rows], ["fresh"])


if __name__ == "__main__":
    unittest.main()
