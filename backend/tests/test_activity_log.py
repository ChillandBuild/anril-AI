"""v9.2 #184 Activity log: discounts and new logins are written server-side; money rows only for people who
can see money; filters by person, type and date."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies.auth import get_current_user  # noqa: E402
from app.dependencies.tenant import get_tenant_and_role  # noqa: E402
from app.main import app  # noqa: E402
from app.services import login_log, orders  # noqa: E402

T = "t1"
UID = "11111111-2222-3333-4444-555555555555"


def _token(session_id="sess-1") -> str:
    return jwt.encode({"sub": UID, "session_id": session_id}, "x", algorithm="HS256")


def _audit_rows(db, action):
    return [r for r in db.table("app_audit_logs").select("*").eq("action", action).execute().data]


class TestDiscountAndLoginRows(unittest.TestCase):
    def setUp(self):
        login_log._SEEN.clear()

    def test_discount_is_logged_only_when_there_is_one(self):
        db = FakeSupabase()
        orders.log_discount(db, T, UID, "d1", discount_paise=0, subtotal_paise=100000)
        self.assertEqual(_audit_rows(db, "order.discount"), [])
        orders.log_discount(db, T, UID, "d1", discount_paise=50000, subtotal_paise=100000)
        rows = _audit_rows(db, "order.discount")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metadata"]["discount_paise"], 50000)
        self.assertEqual(rows[0]["target_id"], "d1")

    def test_login_written_once_per_session_from_the_verified_token(self):
        db = FakeSupabase()
        ctx = {"tenant_id": T, "user_id": UID, "role": "staff"}
        auth = "Bearer " + _token()
        headers = {"authorization": auth, "x-forwarded-for": "6.6.6.6, 1.2.3.4", "user-agent": "Chrome"}
        self.assertTrue(login_log.note_login(db, ctx, auth, headers, "10.0.0.1"))
        self.assertFalse(login_log.note_login(db, ctx, auth, headers, "10.0.0.1"))   # same session, another page
        login_log._SEEN.clear()                                                       # another worker process
        self.assertFalse(login_log.note_login(db, ctx, auth, headers, "10.0.0.1"))   # the table already has it
        rows = _audit_rows(db, "auth.login")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["actor_user_id"], rows[0]["target_id"]), (UID, "sess-1"))
        self.assertEqual(rows[0]["metadata"]["ip"], "1.2.3.4")
        auth2 = "Bearer " + _token("sess-2")                                          # a new sign-in is a new row
        self.assertTrue(login_log.note_login(db, ctx, auth2, {**headers, "authorization": auth2}, "10.0.0.1"))

    def test_ip_is_the_hop_our_proxy_added_and_a_failed_write_is_tried_again(self):
        db = FakeSupabase()
        ctx = {"tenant_id": T, "user_id": UID, "role": "staff"}
        auth = "Bearer " + _token("sess-9")
        headers = {"authorization": auth, "x-forwarded-for": "6.6.6.6, 1.2.3.4"}
        with patch("app.services.audit_log.write_audit_event", side_effect=RuntimeError("db down")):
            self.assertFalse(login_log.note_login(db, ctx, auth, headers, "10.0.0.1"))
        self.assertTrue(login_log.note_login(db, ctx, auth, headers, "10.0.0.1"))   # not remembered after the failure
        self.assertEqual(_audit_rows(db, "auth.login")[0]["metadata"]["ip"], "1.2.3.4")

    def test_log_discount_never_raises(self):
        orders.log_discount(FakeSupabase(), T, UID, "d1", discount_paise="abc", subtotal_paise=None)  # no exception

    def test_no_token_or_no_session_writes_nothing(self):
        db = FakeSupabase()
        ctx = {"tenant_id": T, "user_id": UID, "role": "staff"}
        self.assertFalse(login_log.note_login(db, ctx, None, {}, None))
        bare = "Bearer " + jwt.encode({"sub": UID}, "x", algorithm="HS256")
        self.assertFalse(login_log.note_login(db, ctx, bare, {}, None))
        self.assertEqual(_audit_rows(db, "auth.login"), [])


def test_refund_goes_in_the_activity_log_and_rings_the_bell():
    from app.services import order_refunds
    db = FakeSupabase()
    db.add("tenant_roles", id="r1", tenant_id=T, permissions=["deals.view"])
    db.add("tenant_users", tenant_id=T, user_id="acct", role="staff", role_id="r1")
    deal = {"id": "d1", "tenant_id": T, "order_no": 7}
    with patch("app.services.notify.notify_user") as bell:
        order_refunds._log_and_alert(db, T, deal, 150000, "cash", "wrong size", "part", UID, None)
    rows = _audit_rows(db, "order.refund")
    assert len(rows) == 1 and rows[0]["metadata"]["amount_paise"] == 150000 and rows[0]["actor_user_id"] == UID
    assert bell.call_args.args[1] == "acct"


def _client(ctx):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": ctx["user_id"]}
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    return TestClient(app)


def _db_with(rows=None):
    db = MagicMock()
    tbl = MagicMock()
    chain = tbl.select.return_value.eq.return_value.or_.return_value
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.order.return_value.range.return_value.execute.return_value = MagicMock(data=rows or [], count=len(rows or []))
    db.table.return_value = tbl
    return db, tbl, chain


class TestAuditLogFilters(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def _get(self, ctx, url, rows=None):
        db, tbl, chain = _db_with(rows)
        with patch("app.routes.rbac.get_supabase", return_value=db):
            resp = _client(ctx).get(url)
        return resp, tbl, chain

    def test_staff_without_deals_view_never_asks_for_money_rows(self):
        ctx = {"tenant_id": T, "role": "staff", "user_id": "u1", "permissions": ["roles.view"]}
        resp, tbl, _ = self._get(ctx, "/api/v1/rbac/audit-log")
        self.assertEqual(resp.status_code, 200)
        scope = tbl.select.return_value.eq.return_value.or_.call_args.args[0]
        self.assertNotIn("order.", scope)
        self.assertNotIn("claude", scope)
        self.assertIn("auth.login", scope)
        self.assertEqual(resp.json()["types"], ["team", "roles", "login"])

    def test_staff_asking_for_money_type_gets_nothing(self):
        ctx = {"tenant_id": T, "role": "staff", "user_id": "u1", "permissions": ["roles.view"]}
        resp, tbl, _ = self._get(ctx, "/api/v1/rbac/audit-log?type=money")
        self.assertEqual((resp.status_code, resp.json()["data"], resp.json()["total"]), (200, [], 0))
        tbl.select.assert_not_called()

    def test_deals_view_sees_money_rows_flagged(self):
        ctx = {"tenant_id": T, "role": "staff", "user_id": "u1", "permissions": ["roles.view", "deals.view"]}
        rows = [{"id": "a", "action": "order.refund", "metadata": {"amount_paise": 100}},
                {"id": "b", "action": "auth.login", "metadata": {}}]
        resp, _, _ = self._get(ctx, "/api/v1/rbac/audit-log", rows)
        self.assertEqual([r["money"] for r in resp.json()["data"]], [True, False])

    def test_person_type_and_dates_become_filters(self):
        ctx = {"tenant_id": T, "role": "owner", "user_id": "o1", "permissions": []}
        resp, tbl, chain = self._get(
            ctx, f"/api/v1/rbac/audit-log?person={UID}&type=login&date_from=2026-11-01&date_to=2026-11-23")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(tbl.select.return_value.eq.return_value.or_.call_args.args[0], "action.eq.auth.login")
        chain.eq.assert_called_with("actor_user_id", UID)
        chain.gte.assert_called_with("created_at", "2026-11-01")
        chain.lte.assert_called_with("created_at", "2026-11-23T23:59:59.999Z")

    def test_bad_input_is_refused_before_it_reaches_the_query(self):
        ctx = {"tenant_id": T, "role": "owner", "user_id": "o1", "permissions": []}
        for url in ("?type=everything", "?person=a,action.like.%25", "?date_from=yesterday"):
            resp, tbl, _ = self._get(ctx, "/api/v1/rbac/audit-log" + url)
            self.assertEqual(resp.status_code, 400, url)
            tbl.select.assert_not_called()


if __name__ == "__main__":
    unittest.main()
