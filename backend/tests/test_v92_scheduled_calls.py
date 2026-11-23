"""Item 233: schedule a call for any lead, move a scheduled call, kept-on-time figure."""
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

T = "t1"
OWNER = {"tenant_id": T, "role": "owner", "user_id": "o", "caller_id": None, "permissions": []}
CALLER = {"tenant_id": T, "role": "caller", "user_id": "u1", "caller_id": "c1", "permissions": []}


def soon(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class ScheduledCallsTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        base = dict(tenant_id=T, assigned_to="c1", do_not_call=False, opted_out=False, call_status="new", converted_at=None)
        self.db.add("leads", id="l1", name="Priya", phone="+919800000001", **base)
        self.db.add("leads", id="l-dnc", phone="+919800000002", **{**base, "do_not_call": True})
        self.db.add("leads", id="l-won", phone="+919800000003", **{**base, "call_status": "converted"})
        self.db.add("leads", id="l-other", tenant_id="t2", phone="+919800000004", assigned_to="x", do_not_call=False,
                    opted_out=False, call_status="new", converted_at=None)
        self.ctx = dict(OWNER)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        p = patch("app.routes.follow_ups.get_supabase", return_value=self.db)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def post(self, lead, when=None, note="asked to ring back"):
        return self.client.post("/api/v1/follow-ups/callback", json={"lead_id": lead, "scheduled_for": when or soon(), "note": note})

    def test_schedule_for_any_lead_saves_the_why(self):
        res = self.post("l1")
        self.assertEqual(res.status_code, 200, res.text)
        job = self.db.rows("follow_up_jobs")[0]
        self.assertEqual((job["message_preview"], job["cadence"], job["tenant_id"]), ("asked to ring back", "callback", T))
        self.assertEqual(self.db.rows("leads")[0]["call_status"], "callback")

    def test_refuses_past_time_other_tenant_and_uncallable_leads(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.assertEqual(self.post("l1", past).status_code, 400)
        self.assertEqual(self.post("l1", "tomorrow").status_code, 400)
        self.assertEqual(self.post("l-other").status_code, 404)
        self.assertEqual(self.post("l-dnc").status_code, 400)
        self.assertEqual(self.db.rows("follow_up_jobs"), [])

    def test_a_converted_customer_keeps_their_status(self):
        self.assertEqual(self.post("l-won").status_code, 200)
        self.assertEqual(next(r for r in self.db.rows("leads") if r["id"] == "l-won")["call_status"], "converted")

    def test_move_a_scheduled_call(self):
        job = self.db.add("follow_up_jobs", tenant_id=T, lead_id="l1", cadence="callback", status="pending", scheduled_for=soon(1))
        new = soon(5)
        res = self.client.patch(f"/api/v1/follow-ups/callback/{job['id']}/reschedule", json={"scheduled_for": new})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.db.rows("follow_up_jobs")[0]["scheduled_for"], new)
        bad = self.client.patch(f"/api/v1/follow-ups/callback/{job['id']}/reschedule", json={"scheduled_for": "2020-01-01T00:00:00+00:00"})
        self.assertEqual(bad.status_code, 400)

    def test_a_telecaller_cannot_move_someone_elses_call(self):
        self.db.rows("leads")[0]["assigned_to"] = "c2"
        job = self.db.add("follow_up_jobs", tenant_id=T, lead_id="l1", cadence="callback", status="pending", scheduled_for=soon(1))
        self.ctx.update(CALLER)
        res = self.client.patch(f"/api/v1/follow-ups/callback/{job['id']}/reschedule", json={"scheduled_for": soon(4)})
        self.assertEqual(res.status_code, 403)

    def test_a_plain_telecaller_only_schedules_marks_and_counts_their_own(self):
        self.db.add("leads", id="l-theirs", tenant_id=T, name="X", phone="+919800000009", assigned_to="c2", do_not_call=False,
                    opted_out=False, call_status="new", converted_at=None)
        self.ctx.update(CALLER)
        self.assertEqual(self.post("l-theirs").status_code, 403)
        self.assertEqual(self.post("l1").status_code, 200)
        theirs = self.db.add("follow_up_jobs", tenant_id=T, lead_id="l-theirs", cadence="callback", status="pending", scheduled_for=soon(1))
        done = self.client.patch(f"/api/v1/follow-ups/callback/{theirs['id']}/done")
        self.assertEqual(done.status_code, 403)
        self.assertEqual(self.db.rows("follow_up_jobs")[-1]["status"], "pending")
        # the stats count only this telecaller's calls
        at = datetime.now(timezone.utc) - timedelta(days=2)
        self.db.add("follow_up_jobs", tenant_id=T, lead_id="l-theirs", cadence="callback", status="sent", scheduled_for=at.isoformat())
        self.db.add("follow_up_jobs", tenant_id=T, lead_id="l1", cadence="callback", status="sent", scheduled_for=at.isoformat())
        self.assertEqual(self.client.get("/api/v1/follow-ups/callbacks/stats").json()["due"], 1)

    def test_moving_a_call_for_a_customer_who_said_stop_is_refused(self):
        job = self.db.add("follow_up_jobs", tenant_id=T, lead_id="l-dnc", cadence="callback", status="pending", scheduled_for=soon(1))
        res = self.client.patch(f"/api/v1/follow-ups/callback/{job['id']}/reschedule", json={"scheduled_for": soon(4)})
        self.assertEqual(res.status_code, 400)

    def test_a_time_without_a_zone_is_indian_time(self):
        from app.routes.follow_ups import _future_or_400
        naive = (datetime.now(timezone.utc) + timedelta(hours=3)).astimezone(timezone(timedelta(hours=5, minutes=30))).replace(tzinfo=None)
        saved = _future_or_400(naive.isoformat())
        self.assertAlmostEqual(datetime.fromisoformat(saved).timestamp(), (datetime.now(timezone.utc) + timedelta(hours=3)).timestamp(), delta=5)

    def test_stats_endpoint_returns_the_figure(self):
        at = datetime.now(timezone.utc) - timedelta(days=2)
        job = self.db.add("follow_up_jobs", tenant_id=T, lead_id="l1", cadence="callback", status="sent", scheduled_for=at.isoformat())
        self.db.add("call_logs", tenant_id=T, follow_up_job_id=job["id"], created_at=(at + timedelta(minutes=2)).isoformat())
        body = self.client.get("/api/v1/follow-ups/callbacks/stats").json()
        self.assertEqual((body["kept"], body["due"], body["percent"]), (1, 1, 100))


if __name__ == "__main__":
    unittest.main()
