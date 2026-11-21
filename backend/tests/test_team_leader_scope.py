"""A Team leader sees only their own team on every Call IQ endpoint; owner and other roles are unchanged."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fake_supabase import FakeSupabase
from team_fixture import (
    A1, A2, B1, LC, LEADER_CTX, MANAGER_CTX, OC, OWNER_CTX, T1, TELECALLER_CTX, U1, Harness, uid,
)

NOW = datetime.now(timezone.utc).isoformat()
TEAM_A = {LC, A1, A2}


class CallersAndTeamPageTests(unittest.TestCase):
    def test_callers_list_leader_sees_only_own_team(self):
        with Harness() as h:
            leader = h.as_(LEADER_CTX).get("/api/v1/callers/").json()
            owner = h.as_(OWNER_CTX).get("/api/v1/callers/").json()
        self.assertEqual({c["id"] for c in leader["data"]}, TEAM_A)
        self.assertIsNone(leader["admin_caller"])
        self.assertEqual({c["id"] for c in owner["data"]}, {LC, A1, A2, B1, U1})   # unchanged
        self.assertEqual(owner["admin_caller"]["id"], OC)
        self.assertEqual({c["id"]: c["team_name"] for c in owner["data"]}[B1], "Team B")

    def test_team_list_leader_sees_only_own_team_members(self):
        with Harness() as h:
            leader = h.as_(LEADER_CTX).get("/api/v1/team/").json()["data"]
            owner = h.as_(OWNER_CTX).get("/api/v1/team/").json()["data"]
        self.assertEqual({m["caller_profile"]["id"] for m in leader}, TEAM_A)
        self.assertGreater(len(owner), len(leader))
        self.assertIn(B1, {(m.get("caller_profile") or {}).get("id") for m in owner})

    def test_attendance_grid_is_scoped(self):
        with Harness() as h:
            leader = h.as_(LEADER_CTX).get("/api/v1/team/attendance").json()["data"]
            manager = h.as_(MANAGER_CTX).get("/api/v1/team/attendance").json()["data"]
        self.assertEqual({c["caller_id"] for c in leader["callers"]}, TEAM_A)
        self.assertEqual({c["caller_id"] for c in manager["callers"]}, {LC, A1, A2, B1, U1})
        self.assertEqual(set(leader["grid"]), TEAM_A)

    def test_caller_attendance_outside_team_is_403(self):
        with Harness() as h:
            c = h.as_(LEADER_CTX)
            self.assertEqual(c.get(f"/api/v1/team/attendance/{B1}").status_code, 403)
            self.assertEqual(c.get(f"/api/v1/team/attendance/{A1}").status_code, 200)
            self.assertEqual(h.as_(OWNER_CTX).get(f"/api/v1/team/attendance/{B1}").status_code, 200)

    def test_mark_attendance_only_inside_team(self):
        with Harness() as h:
            c = h.as_(LEADER_CTX)
            day = datetime.now(timezone.utc).date().isoformat()
            self.assertEqual(c.post(f"/api/v1/team/attendance/{B1}", json={"date": day, "status": "present"}).status_code, 403)
            self.assertEqual(c.post(f"/api/v1/team/attendance/{A1}", json={"date": day, "status": "present"}).status_code, 200)
            marked = {r["caller_id"] for r in h.db.rows("caller_attendance_overrides")}
            self.assertEqual(marked, {A1})

    def test_holiday_marks_only_the_leaders_team(self):
        with Harness() as h:
            day = datetime.now(timezone.utc).date().isoformat()
            r = h.as_(LEADER_CTX).post("/api/v1/team/attendance/holiday", json={"date": day})
            self.assertEqual(r.status_code, 200)
            self.assertEqual({x["caller_id"] for x in h.db.rows("caller_attendance_overrides")}, {A1, A2, LC})
            h.db.tables["caller_attendance_overrides"] = []
            h.as_(OWNER_CTX).post("/api/v1/team/attendance/holiday", json={"date": day})
            self.assertEqual({x["caller_id"] for x in h.db.rows("caller_attendance_overrides")}, {LC, A1, A2, B1, U1})

    def test_shift_hours_and_removing_people_are_not_for_leaders(self):
        with Harness() as h:
            c = h.as_(LEADER_CTX)
            self.assertEqual(c.patch("/api/v1/team/shift-config", json={"shift_mode": "common", "shift_start_hour": 9, "shift_end_hour": 18}).status_code, 403)
            self.assertEqual(c.patch(f"/api/v1/team/{B1}/shift", json={"shift_start_hour": 9, "shift_end_hour": 18}).status_code, 403)
            self.assertEqual(c.patch(f"/api/v1/team/{A1}/shift", json={"shift_start_hour": 9, "shift_end_hour": 18}).status_code, 200)
            self.assertEqual(c.delete(f"/api/v1/team/{uid(15)}").status_code, 403)

    def test_status_summary_timeline_and_logs(self):
        with Harness() as h:
            for path in ("status-summary", "timeline", "logs"):
                c = h.as_(LEADER_CTX)
                self.assertEqual(c.get(f"/api/v1/callers/{B1}/{path}").status_code, 403, path)
                self.assertEqual(c.get(f"/api/v1/callers/{A1}/{path}").status_code, 200, path)
                self.assertEqual(h.as_(OWNER_CTX).get(f"/api/v1/callers/{B1}/{path}").status_code, 200, path)
                # a manager with a custom role keeps today's answer: not allowed (owner-only)
                self.assertEqual(h.as_(MANAGER_CTX).get(f"/api/v1/callers/{A1}/{path}").status_code, 403, path)
                self.assertEqual(h.as_(TELECALLER_CTX).get(f"/api/v1/callers/{A1}/{path}").status_code, 403, path)


def _seed_calls(db):
    for i, cid in enumerate((A1, A1, A2, B1, B1, B1, U1)):
        db.add("call_logs", tenant_id=T1, caller_id=cid, created_at=NOW, duration_seconds=60, outcome="converted" if i == 0 else None,
               manual_status="connected", score_status="scored", score=50 + i, lead_id=None, status="completed")
    db.rpc_handlers["get_telecalling_all_time_stats"] = lambda p: {
        "avg_duration_seconds": 100, "outcome_breakdown": {"converted": 9},
        "caller_stats": {A1: {"total": 4, "converted": 2}, B1: {"total": 8, "converted": 1}},
    }


class AnalyticsScopeTests(unittest.TestCase):
    def test_telecalling_analytics_leader_sees_only_own_team(self):
        with Harness() as h:
            _seed_calls(h.db)
            leader = h.as_(LEADER_CTX).get("/api/v1/analytics/telecalling").json()
            owner = h.as_(OWNER_CTX).get("/api/v1/analytics/telecalling").json()
            manager = h.as_(MANAGER_CTX).get("/api/v1/analytics/telecalling").json()
        self.assertEqual({r["caller_id"] for r in leader["per_caller"]}, TEAM_A)
        self.assertEqual(leader["calls_today"], 3)                      # A1, A1, A2 only
        self.assertEqual(sum(leader["outcome_breakdown"].values()), 0)   # the whole-client RPC totals are dropped
        self.assertIsNone(leader["avg_duration_seconds"])
        self.assertEqual({r["caller_id"] for r in owner["per_caller"]}, {LC, A1, A2, B1, U1})
        self.assertEqual(owner["calls_today"], 7)
        self.assertEqual(owner["outcome_breakdown"]["converted"], 9)
        self.assertEqual(manager["calls_today"], 7)                      # custom role with analytics.view: unchanged
        conv = {r["caller_id"]: r["conversion_rate"] for r in leader["per_caller"]}
        self.assertEqual(conv[A1], 0.5)
        self.assertNotIn(B1, conv)

    def test_telecaller_without_team_permissions_is_refused(self):
        with Harness() as h:
            self.assertEqual(h.as_(TELECALLER_CTX).get("/api/v1/analytics/telecalling").status_code, 403)

    def test_qa_queue_and_caller_timeline(self):
        with Harness() as h:
            _seed_calls(h.db)
            c = h.as_(LEADER_CTX)
            rows = c.get("/api/v1/analytics/qa-queue", params={"limit": 50}).json()
            self.assertEqual({r["caller_id"] for r in rows["data"]}, {A1, A2})
            self.assertEqual(rows["total"], 3)
            self.assertEqual(c.get("/api/v1/analytics/qa-queue", params={"caller_id": B1}).status_code, 403)
            self.assertEqual(c.get("/api/v1/analytics/caller-timeline", params={"caller_id": B1}).status_code, 403)
            self.assertEqual(c.get("/api/v1/analytics/caller-timeline", params={"caller_id": A1}).status_code, 200)
            owner_rows = h.as_(OWNER_CTX).get("/api/v1/analytics/qa-queue", params={"limit": 50}).json()
            self.assertEqual(owner_rows["total"], 7)


class AlertsAndReviewScopeTests(unittest.TestCase):
    def _seed_alerts(self, db):
        self.alerts = {}
        for cid in (A1, B1):
            self.alerts[cid] = db.add("call_alerts", tenant_id=T1, caller_id=cid, type="rude", seen_at=None, created_at=NOW)["id"]

    def test_alerts_list_count_and_seen(self):
        with Harness() as h:
            self._seed_alerts(h.db)
            c = h.as_(LEADER_CTX)
            self.assertEqual({a["caller_id"] for a in c.get("/api/v1/calls/alerts").json()["data"]}, {A1})
            self.assertEqual(c.get("/api/v1/calls/alerts", params={"caller_id": B1}).status_code, 403)
            self.assertEqual(c.get("/api/v1/calls/alerts/count").json()["count"], 1)
            self.assertEqual(c.post(f"/api/v1/calls/alerts/{self.alerts[B1]}/seen").status_code, 404)
            self.assertEqual(c.post(f"/api/v1/calls/alerts/{self.alerts[A1]}/seen").status_code, 200)
            self.assertEqual(h.as_(OWNER_CTX).get("/api/v1/calls/alerts").json()["total"], 1)   # B1's is still open
            self.assertEqual(h.as_(OWNER_CTX).get("/api/v1/calls/alerts/count").json()["count"], 1)

    def test_call_review_lists(self):
        with Harness() as h:
            lead_a, lead_b = uid(70), uid(71)
            h.db.add("leads", id=lead_a, tenant_id=T1, name="Ravi", phone="+911", assigned_to=A1, deleted_at=None)
            h.db.add("leads", id=lead_b, tenant_id=T1, name="Sita", phone="+912", assigned_to=B1, deleted_at=None)
            for lead, cid in ((lead_a, A1), (lead_b, B1)):
                h.db.add("call_logs", tenant_id=T1, caller_id=cid, lead_id=lead, created_at="2026-10-02T10:00:00+00:00",
                         status="completed", duration_seconds=30)
            q = {"start": "2026-10-01T00:00:00+00:00", "end": "2026-10-03T00:00:00+00:00"}
            c = h.as_(LEADER_CTX)
            ids = {r["id"] for r in c.get("/api/v1/call-review/leads", params=q).json()["data"]}
            self.assertEqual(ids, {lead_a})
            self.assertEqual(c.get("/api/v1/call-review/leads", params={**q, "caller_id": B1}).status_code, 403)
            self.assertEqual(len(c.get(f"/api/v1/call-review/leads/{lead_b}/calls", params=q).json()["data"]), 0)
            self.assertEqual(len(c.get(f"/api/v1/call-review/leads/{lead_a}/calls", params=q).json()["data"]), 1)
            self.assertEqual(c.get(f"/api/v1/call-review/leads/{lead_b}/calls", params={**q, "caller_id": B1}).status_code, 403)
            owner_ids = {r["id"] for r in h.as_(OWNER_CTX).get("/api/v1/call-review/leads", params=q).json()["data"]}
            self.assertEqual(owner_ids, {lead_a, lead_b})


class CallbacksAndMoveLeadTests(unittest.TestCase):
    def _seed(self, db):
        self.lead_a, self.lead_b, self.lead_free = uid(80), uid(81), uid(82)
        for lead, owner in ((self.lead_a, A1), (self.lead_b, B1), (self.lead_free, None)):
            db.add("leads", id=lead, tenant_id=T1, name=f"L{lead[-2:]}", phone="+91", segment="warm", score=1, assigned_to=owner, deleted_at=None)
        self.jobs = {}
        for lead in (self.lead_a, self.lead_b):
            self.jobs[lead] = db.add("follow_up_jobs", tenant_id=T1, lead_id=lead, cadence="callback", status="pending",
                                     scheduled_for=NOW, message_preview="x", scheduled_by_caller_id=None)["id"]

    def test_scheduled_calls_board(self):
        with Harness() as h:
            self._seed(h.db)
            leader = h.as_(LEADER_CTX).get("/api/v1/follow-ups/callbacks/board").json()["data"]
            owner = h.as_(OWNER_CTX).get("/api/v1/follow-ups/callbacks/board").json()["data"]
            telecaller = h.as_(TELECALLER_CTX).get("/api/v1/follow-ups/callbacks/board").json()["data"]
        self.assertEqual({r["lead_id"] for r in leader}, {self.lead_a})
        self.assertEqual({r["lead_id"] for r in owner}, {self.lead_a, self.lead_b})
        self.assertEqual({r["lead_id"] for r in telecaller}, {self.lead_a, self.lead_b})   # other roles: unchanged

    def test_done_and_reschedule_only_inside_team(self):
        with Harness() as h:
            self._seed(h.db)
            c = h.as_(LEADER_CTX)
            self.assertEqual(c.patch(f"/api/v1/follow-ups/callback/{self.jobs[self.lead_b]}/done").status_code, 403)
            self.assertEqual(c.patch(f"/api/v1/follow-ups/callback/{self.jobs[self.lead_b]}/reschedule", json={"scheduled_for": NOW}).status_code, 403)
            self.assertEqual(c.patch(f"/api/v1/follow-ups/callback/{self.jobs[self.lead_a]}/done").status_code, 200)
            status = {j["lead_id"]: j["status"] for j in h.db.rows("follow_up_jobs")}
            self.assertEqual(status[self.lead_a], "sent")
            self.assertEqual(status[self.lead_b], "pending")

    def test_move_lead_only_between_team_callers(self):
        with Harness() as h:
            self._seed(h.db)
            lead = {l["id"]: l for l in h.db.rows("leads")}
            move = lambda lid, to: h.as_(LEADER_CTX).patch(f"/api/v1/leads/{lid}/assign", json={"caller_id": to})
            self.assertEqual(move(self.lead_a, A2).status_code, 200)             # A1 -> A2, both in team
            self.assertEqual(lead[self.lead_a]["assigned_to"], A2)
            self.assertEqual(move(self.lead_a, B1).status_code, 403)             # to another team
            self.assertEqual(move(self.lead_b, A1).status_code, 403)             # from another team
            self.assertEqual(move(self.lead_free, A1).status_code, 403)          # not held by the team
            self.assertEqual(move(self.lead_a, None).status_code, 403)           # unassign
            self.assertEqual(lead[self.lead_b]["assigned_to"], B1)

    def test_bulk_move_is_all_or_nothing(self):
        with Harness() as h:
            self._seed(h.db)
            lead = {l["id"]: l for l in h.db.rows("leads")}
            c = h.as_(LEADER_CTX)
            r = c.post("/api/v1/leads/bulk-assign", json={"lead_ids": [self.lead_a, self.lead_b], "caller_id": A2})
            self.assertEqual(r.status_code, 403)
            self.assertEqual(lead[self.lead_a]["assigned_to"], A1)               # nothing moved
            r = c.post("/api/v1/leads/bulk-assign", json={"lead_ids": [self.lead_a], "caller_id": A2})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(lead[self.lead_a]["assigned_to"], A2)

    def test_owner_can_move_anything_and_other_roles_stay_refused(self):
        with Harness() as h:
            self._seed(h.db)
            lead = {l["id"]: l for l in h.db.rows("leads")}
            self.assertEqual(h.as_(OWNER_CTX).patch(f"/api/v1/leads/{self.lead_b}/assign", json={"caller_id": A1}).status_code, 200)
            self.assertEqual(lead[self.lead_b]["assigned_to"], A1)
            r = h.as_(MANAGER_CTX).patch(f"/api/v1/leads/{self.lead_a}/assign", json={"caller_id": B1})
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "Owner only"))
            self.assertEqual(h.as_(TELECALLER_CTX).post("/api/v1/leads/bulk-assign", json={"lead_ids": [self.lead_a], "caller_id": B1}).status_code, 403)


class FailClosedTests(unittest.TestCase):
    def test_leader_with_stale_role_read_stays_limited(self):
        """If the role lookup blips, a person whose cached role is Team leader is NOT treated as 'sees everyone'."""
        from app.services import call_teams as svc

        class Blip(FakeSupabase):
            def table(self, name):
                if name == "tenant_roles":
                    raise Exception("connection reset")
                return super().table(name)
        from team_fixture import build_db
        db = Blip()
        db.tables = build_db().tables
        self.assertEqual(svc.caller_scope(db, LEADER_CTX), {LC})
        self.assertIsNone(svc.caller_scope(db, MANAGER_CTX))
        self.assertIsNone(svc.caller_scope(db, OWNER_CTX))


if __name__ == "__main__":
    unittest.main()
