"""Manual Dial "Before you call": phone matching, the check rows, and the /dial-check route."""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.services.call_rules import DEFAULT_RULES, IST, mask_phone
from app.services.dial_check import build_checks, phone_variants
from tests.test_telecmi_initiate_call import APP_SECRET, TENANT_ID

STORED = "+919843120123"
RULES = {**DEFAULT_RULES, "calling_hours_on": True, "calling_start": "09:00", "calling_end": "21:00"}


def _build(**kw):
    args = dict(lead=None, rules=RULES, role="owner", calls_today=0, last_call_at=None,
                limit_reached=False, now=datetime(2026, 11, 28, 16, 10, tzinfo=IST))
    args.update(kw)
    return build_checks(**args)


def _row(checks, key):
    return next((c for c in checks if c["key"] == key), None)


class _Result:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.in_filter, self.payload = db, table, "select", None, None

    def select(self, *a, **k): return self
    def eq(self, *a): return self
    def gte(self, *a): return self
    def order(self, *a, **k): return self
    def limit(self, *a): return self
    def maybe_single(self): return self

    def in_(self, col, values):
        self.in_filter = (col, values)
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op = "update"
        return self

    def execute(self):
        self.db.ops.append((self.table, self.op, self.payload))
        if self.op == "insert":
            return _Result([{"id": "new-id"}])
        if self.op == "update":
            return _Result([])
        rows = self.db.rows.get(self.table)
        if self.in_filter:
            col, values = self.in_filter
            return _Result([r for r in (rows or []) if r.get(col) in values])
        return _Result(rows)


class _DB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.ops = []

    def table(self, name):
        return _Q(self, name)


class BuildChecksTests(unittest.TestCase):
    def test_phone_variants_adds_india_forms(self):
        self.assertEqual(phone_variants("98431 20123"), ["98431 20123", "+919843120123", "919843120123", "9843120123"])
        v = phone_variants("+919843120123")
        self.assertEqual(v[0], "+919843120123")
        self.assertIn("9843120123", v)
        self.assertEqual(phone_variants("123"), ["123"])

    def test_phone_variants_drops_unsafe_raw_text(self):
        v = phone_variants("98431,20123)")
        self.assertEqual(v, ["+919843120123", "919843120123", "9843120123"])
        self.assertFalse([x for x in v if "," in x or ")" in x])

    def test_build_checks_said_stop_blocks(self):
        checks, reason = _build(lead={"opted_out": True})
        self.assertEqual(_row(checks, "said_stop")["state"], "blocked")
        self.assertEqual(_row(checks, "said_stop")["detail"], "On Said stop")
        self.assertEqual(reason, "This customer is on Said stop, so they can't be called")

    def test_build_checks_dnd_is_never_ok(self):
        for lead in (None, {"opted_out": True}, {"do_not_call": True}):
            row = _row(_build(lead=lead)[0], "dnd")
            self.assertEqual((row["state"], row["detail"]), ("not_checked", "Not checked"))

    def test_outside_hours_blocks_caller_but_warns_owner(self):
        late = datetime(2026, 11, 28, 22, 30, tzinfo=IST)
        checks, reason = _build(role="caller", now=late)
        self.assertEqual(_row(checks, "hours")["state"], "blocked")
        self.assertEqual(reason, "Calling hours are 9 AM to 9 PM")
        checks, reason = _build(role="owner", now=late)
        self.assertEqual(_row(checks, "hours")["state"], "warn")
        self.assertIsNone(reason)

    def test_inside_hours_row_shows_the_time(self):
        row = _row(_build()[0], "hours")
        self.assertEqual((row["label"], row["state"], row["detail"]), ("Calling hours 9 AM – 9 PM", "ok", "4:10 PM"))

    def test_daily_limit_row_only_for_caller(self):
        self.assertIsNone(_row(_build(role="owner", rules={**RULES, "daily_limit_on": True})[0], "daily_limit"))
        checks, reason = _build(role="caller", rules={**RULES, "daily_limit_on": True}, limit_reached=True)
        self.assertEqual(_row(checks, "daily_limit")["state"], "blocked")
        self.assertEqual(reason, "Daily call limit reached")

    def test_called_today_row_only_when_called(self):
        self.assertIsNone(_row(_build(calls_today=0)[0], "called_today"))
        row = _row(_build(calls_today=2, last_call_at=datetime(2026, 11, 28, 11, 20, tzinfo=IST))[0], "called_today")
        self.assertEqual(row["label"], "Called 2 times today already")
        self.assertEqual(row["state"], "warn")
        self.assertEqual(row["detail"], "Last: 11:20 AM")


class _RouteBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": TENANT_ID, "role": "owner"}
        self.addCleanup(app.dependency_overrides.clear)

    def _patches(self, db):
        return [
            patch("app.routes.calls.get_supabase", return_value=db),
            patch("app.routes.calls.check_quota", return_value=True),
            patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "telecmi"}),
            patch("app.routes.calls.get_setting", side_effect=lambda key, **kw: APP_SECRET if key == "telecmi_secret" else None),
            patch("app.routes.calls.mark_activity_today"),
            patch("app.services.call_rules.get_rules", return_value=RULES),
            patch("app.routes.calls.effective_calling_mode", return_value="telecmi"),
            patch("app.services.google_ads_report.came_from_labels", return_value={}),
        ]

    def _run(self, db, fn, extra=()):
        ps = self._patches(db) + list(extra)
        for p in ps:
            p.start()
        try:
            return fn()
        finally:
            for p in reversed(ps):
                p.stop()


class RouteTests(_RouteBase):
    def test_initiate_refuses_said_stop_typed_without_country_code(self):
        db = _DB({"leads": [{"id": "l1", "phone": STORED, "name": "A", "opted_out": True, "do_not_call": False}]})
        with patch("app.routes.calls.initiate_click2call") as click:
            res = self._run(db, lambda: self.client.post("/api/v1/calls/initiate", json={"phone": "9843120123"}))
        self.assertEqual(res.status_code, 400)
        self.assertIn("Said stop", res.json()["detail"])
        click.assert_not_called()
        self.assertFalse([o for o in db.ops if o[0] == "leads" and o[1] == "insert"])

    def test_initiate_refuses_when_older_duplicate_is_said_stop(self):
        db = _DB({"leads": [
            {"id": "new", "phone": "9843120123", "name": "N", "created_at": "2026-11-02", "opted_out": False},
            {"id": "old", "phone": STORED, "name": "O", "created_at": "2026-01-01", "opted_out": True},
        ]})
        with patch("app.routes.calls.initiate_click2call") as click:
            res = self._run(db, lambda: self.client.post("/api/v1/calls/initiate", json={"phone": "9843120123"}))
        self.assertEqual(res.status_code, 400)
        self.assertIn("Said stop", res.json()["detail"])
        click.assert_not_called()

    def test_dial_check_blocks_when_older_duplicate_is_said_stop(self):
        db = _DB({"leads": [
            {"id": "new", "phone": "9843120123", "name": "N", "created_at": "2026-11-02", "opted_out": False},
            {"id": "old", "phone": STORED, "name": "O", "created_at": "2026-01-01", "opted_out": True},
        ]})
        res = self._run(db, lambda: self.client.get("/api/v1/calls/dial-check", params={"phone": "9843120123"}))
        body = res.json()
        self.assertEqual(body["customer"]["id"], "new")
        self.assertEqual(body["checks"][0]["state"], "blocked")
        self.assertFalse(body["can_call"])

    def test_dial_check_matches_typed_number_and_blocks(self):
        db = _DB({"leads": [{"id": "l1", "phone": STORED, "name": "A", "segment": "B", "opted_out": True}]})
        res = self._run(db, lambda: self.client.get("/api/v1/calls/dial-check", params={"phone": "9843120123"}))
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["customer"]["id"], "l1")
        self.assertFalse(body["can_call"])
        self.assertEqual(body["calling_from"], "office")
        self.assertIn("Said stop", body["blocked_reason"])

    def test_dial_check_unknown_number_has_no_customer(self):
        res = self._run(_DB({"leads": []}), lambda: self.client.get("/api/v1/calls/dial-check", params={"phone": "9000000000"}))
        body = res.json()
        self.assertIsNone(body["customer"])
        self.assertEqual(body["checks"][2]["key"], "dnd")

    def test_dial_check_503_when_lead_lookup_fails(self):
        res = self._run(
            _DB(), lambda: self.client.get("/api/v1/calls/dial-check", params={"phone": "9843120123"}),
            extra=[patch("app.routes.calls.find_lead_for_dial", side_effect=RuntimeError("db down"))],
        )
        self.assertEqual(res.status_code, 503)
        self.assertEqual(
            res.json()["detail"],
            "Couldn't check this number right now. The Call button still checks Said stop and Do not call.",
        )

    def test_dial_check_masks_phone_for_hidden_caller(self):
        db = _DB({"leads": [{"id": "l1", "phone": STORED, "name": "A", "segment": "B"}]})
        res = self._run(
            db, lambda: self.client.get("/api/v1/calls/dial-check", params={"phone": "9843120123"}),
            extra=[patch("app.services.call_rules.phone_mask_for", return_value=mask_phone)],
        )
        self.assertEqual(res.json()["customer"]["phone"], "98•••••123")


class _Scope:
    """Stands in for _filtered_leads_query: finds the lead only when it is in `ids`."""
    def __init__(self, ids):
        self.ids, self.want = ids, None

    def eq(self, _col, val):
        self.want = val
        return self

    def limit(self, *_a): return self

    def execute(self):
        return _Result([{"id": self.want}] if self.want in self.ids else [])


class CallerScopeTests(_RouteBase):
    def setUp(self):
        super().setUp()
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": TENANT_ID, "role": "caller", "caller_id": "c1", "permissions": ["telecalling.dialer"]}

    def _get(self, db, mask, ids):
        return self._run(
            db, lambda: self.client.get("/api/v1/calls/dial-check", params={"phone": "9843120123"}),
            extra=[
                patch("app.services.call_rules.phone_mask_for", return_value=mask),
                patch("app.routes.leads._filtered_leads_query", return_value=_Scope(ids)),
            ],
        )

    def test_hidden_numbers_give_no_customer_but_said_stop_still_blocks(self):
        db = _DB({"leads": [{"id": "l1", "phone": STORED, "name": "A", "opted_out": True}]})
        body = self._get(db, mask_phone, {"l1"}).json()
        self.assertIsNone(body["customer"])
        self.assertFalse(body["can_call"])
        self.assertIn("Said stop", body["blocked_reason"])

    def test_visible_numbers_but_not_my_lead_gives_no_customer(self):
        db = _DB({"leads": [{"id": "l1", "phone": STORED, "name": "A"}]})
        self.assertIsNone(self._get(db, None, set()).json()["customer"])

    def test_visible_numbers_and_my_lead_gives_customer(self):
        db = _DB({"leads": [{"id": "l1", "phone": STORED, "name": "A"}]})
        self.assertEqual(self._get(db, None, {"l1"}).json()["customer"]["id"], "l1")

    def test_owner_still_gets_customer(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": TENANT_ID, "role": "owner"}
        db = _DB({"leads": [{"id": "l1", "phone": STORED, "name": "A"}]})
        body = self._run(db, lambda: self.client.get("/api/v1/calls/dial-check", params={"phone": "9843120123"})).json()
        self.assertEqual(body["customer"]["id"], "l1")


if __name__ == "__main__":
    unittest.main()
