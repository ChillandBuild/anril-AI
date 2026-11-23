"""v9.2 #21 Call IQ leave: open leads move round robin to free telecallers; routes; /initiate pre-dial checks."""
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.services import caller_leave as cl

NOW = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)  # 11:30 IST, 23 Nov 2026


class _Res:
    def __init__(self, data=None):
        self.data = data


class _Q:
    """Just enough of the query builder: remembers eq / in_ filters, applies them to update, returns rows on select."""

    def __init__(self, db, table):
        self.db, self.t, self.op, self.payload, self.eq_, self.in_f = db, table, "select", None, {}, None
        self.single = False

    def select(self, *a, **k):
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def insert(self, p):
        self.op, self.payload = "insert", p
        return self

    def eq(self, c, v):
        self.eq_[c] = v
        return self

    def in_(self, c, vals):
        self.in_f = (c, set(vals))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        rows = self.db.rows.setdefault(self.t, [])
        if self.op == "insert":
            self.db.inserted.setdefault(self.t, []).extend(self.payload if isinstance(self.payload, list) else [self.payload])
            return _Res([])
        hit = [r for r in rows if all(r.get(k) == v for k, v in self.eq_.items() if k != "tenant_id")]
        if self.in_f:
            hit = [r for r in hit if r.get(self.in_f[0]) in self.in_f[1]]
        if self.op == "update":
            for r in hit:
                r.update(self.payload)
            return _Res([dict(r) for r in hit])
        if self.single:
            return _Res(hit[0] if hit else None)
        return _Res([dict(r) for r in hit])


class DB:
    def __init__(self, rows):
        self.rows, self.inserted = rows, {}

    def table(self, name):
        return _Q(self, name)


def _world():
    return DB({
        "callers": [
            {"id": "a", "name": "Asha", "leave_from": None, "leave_to": None},
            {"id": "b", "name": "Bala", "leave_from": None, "leave_to": None},
            {"id": "c", "name": "Chitra", "leave_from": "2026-11-20", "leave_to": "2026-11-25"},  # also on leave
            {"id": "d", "name": "Dev", "leave_from": None, "leave_to": None},
        ],
        "leads": [{"id": f"l{i}", "assigned_to": "a", "segment": "B", "score": 50, "call_status": "new"} for i in range(5)],
    })


def _pool(db, tenant_id):
    return [{"id": r["id"], "name": r["name"]} for r in db.rows["callers"]]


class MoveLeadsTests(unittest.TestCase):
    def _move(self, db):
        with patch("app.services.assignment.eligible_callers", side_effect=_pool), \
             patch.object(cl, "_open_lead_rows", side_effect=lambda d, t, cid: [r for r in d.rows["leads"] if r["assigned_to"] == cid]):
            return cl.move_leads_of_caller_on_leave(db, "t", "a", NOW)

    def test_round_robin_skips_person_on_leave_and_self(self):
        db = _world()
        out = self._move(db)
        self.assertEqual(out["moved"], 5)
        self.assertEqual(sorted(out["to"], key=lambda x: x["name"]), [{"name": "Bala", "count": 3}, {"name": "Dev", "count": 2}])
        owners = {r["assigned_to"] for r in db.rows["leads"]}
        self.assertEqual(owners, {"b", "d"})

    def test_each_move_is_in_the_assignment_log(self):
        db = _world()
        self._move(db)
        events = db.inserted["lead_stage_events"]
        self.assertEqual(len(events), 5)
        self.assertEqual({e["event_type"] for e in events}, {"reassigned"})
        meta = events[0]["metadata"]
        self.assertEqual((meta["reason"], meta["method"], meta["prev_caller_id"], meta["prev_caller_name"]),
                         ("moved_for_leave", "leave", "a", "Asha"))

    def test_marks_leave_handled(self):
        db = _world()
        self._move(db)
        self.assertIsNotNone(next(r for r in db.rows["callers"] if r["id"] == "a")["leave_leads_moved_at"])

    def test_nobody_free_keeps_leads(self):
        db = _world()
        db.rows["callers"] = [r for r in db.rows["callers"] if r["id"] in ("a", "c")]
        out = self._move(db)
        self.assertEqual((out["moved"], out["no_one_free"]), (0, True))
        self.assertEqual({r["assigned_to"] for r in db.rows["leads"]}, {"a"})

    def test_lead_claimed_meanwhile_is_not_moved(self):
        db = _world()
        db.rows["leads"][0]["assigned_to"] = "z"  # someone else took it
        with patch("app.services.assignment.eligible_callers", side_effect=_pool), \
             patch.object(cl, "_open_lead_rows", return_value=[dict(r) for r in db.rows["leads"]]):
            out = cl.move_leads_of_caller_on_leave(db, "t", "a", NOW)
        self.assertEqual(out["moved"], 4)
        self.assertEqual(db.rows["leads"][0]["assigned_to"], "z")


class LeaveStateTests(unittest.TestCase):
    def test_on_leave_dates_are_inclusive(self):
        c = {"leave_from": "2026-11-20", "leave_to": "2026-11-23"}
        self.assertTrue(cl.on_leave(c, date(2026, 11, 20)))
        self.assertTrue(cl.on_leave(c, date(2026, 11, 23)))
        self.assertFalse(cl.on_leave(c, date(2026, 11, 24)))
        self.assertFalse(cl.on_leave({}, date(2026, 11, 23)))

    def test_leave_starting_later_does_not_move_yet(self):
        db = _world()
        out = cl.start_leave(db, "t", "a", date(2026, 12, 1), date(2026, 12, 5), "  wedding ", NOW)
        self.assertTrue(out["starts_later"])
        a = db.rows["callers"][0]
        self.assertEqual((a["leave_from"], a["leave_reason"]), ("2026-12-01", "wedding"))
        self.assertEqual({r["assigned_to"] for r in db.rows["leads"]}, {"a"})

    def test_leave_starting_today_moves_now(self):
        db = _world()
        with patch.object(cl, "move_leads_of_caller_on_leave", return_value={"moved": 5, "to": [], "no_one_free": False}) as mv:
            out = cl.start_leave(db, "t", "a", date(2026, 11, 23), date(2026, 11, 24), None, NOW)
        mv.assert_called_once()
        self.assertEqual(out["moved"], 5)
        self.assertFalse(out["starts_later"])

    def test_end_leave_clears_everything(self):
        db = _world()
        cl.end_leave(db, "t", "c")
        c = db.rows["callers"][2]
        self.assertEqual((c["leave_from"], c["leave_to"], c["leave_reason"]), (None, None, None))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t", "role": "owner"}
        self.addCleanup(app.dependency_overrides.clear)
        self.db = _world()
        p = patch("app.routes.call_iq_settings.get_supabase", return_value=self.db)
        p.start()
        self.addCleanup(p.stop)
        self.cid = "11111111-1111-1111-1111-111111111111"
        self.db.rows["callers"][0]["id"] = self.cid

    def test_leave_needs_team_manage(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t", "role": "caller", "permissions": ["settings.manage"]}
        r = self.client.post(f"/api/v1/call-iq-settings/callers/{self.cid}/leave", json={"from": "2026-12-01", "to": "2026-12-02"})
        self.assertEqual(r.status_code, 403)

    def test_leave_end_before_start_is_refused(self):
        r = self.client.post(f"/api/v1/call-iq-settings/callers/{self.cid}/leave", json={"from": "2099-12-05", "to": "2099-12-02"})
        self.assertEqual(r.status_code, 422)

    def test_unknown_caller_is_404(self):
        r = self.client.post("/api/v1/call-iq-settings/callers/22222222-2222-2222-2222-222222222222/leave",
                             json={"from": "2099-12-01", "to": "2099-12-02"})
        self.assertEqual(r.status_code, 404)

    def test_future_leave_saved(self):
        r = self.client.post(f"/api/v1/call-iq-settings/callers/{self.cid}/leave",
                             json={"from": "2099-12-01", "to": "2099-12-02", "reason": "trip"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["starts_later"])

    def test_delete_leave(self):
        r = self.client.delete(f"/api/v1/call-iq-settings/callers/{self.cid}/leave")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["on_leave"])

    def test_mode_save_and_bad_value(self):
        ok = self.client.put(f"/api/v1/call-iq-settings/callers/{self.cid}/mode", json={"mode": "sim"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.db.rows["callers"][0]["calling_mode"], "sim")
        bad = self.client.put(f"/api/v1/call-iq-settings/callers/{self.cid}/mode", json={"mode": "pigeon"})
        self.assertEqual(bad.status_code, 422)

    def test_rules_put_rejects_bad_hours(self):
        body = {"calling_hours_on": True, "calling_start": "21:00", "calling_end": "09:00", "daily_limit_on": False,
                "daily_limit": 100, "break_limit_minutes": 30, "hide_numbers_for_callers": False}
        r = self.client.put("/api/v1/call-iq-settings/rules", json=body)
        self.assertEqual(r.status_code, 422)
        self.assertIn("end after", r.json()["detail"])

    def test_rules_get_defaults_and_put_saves(self):
        self.db.rows["app_settings"] = []
        got = self.client.get("/api/v1/call-iq-settings/rules")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["calling_start"], "09:00")
        body = {**got.json(), "hide_numbers_for_callers": True, "daily_limit_on": True, "daily_limit": 40}
        with patch("app.services.call_rules.save_rules", side_effect=lambda db, t, r: r) as save:
            put = self.client.put("/api/v1/call-iq-settings/rules", json=body)
        self.assertEqual(put.status_code, 200)
        self.assertTrue(save.call_args.args[2]["hide_numbers_for_callers"])


if __name__ == "__main__":
    unittest.main()
