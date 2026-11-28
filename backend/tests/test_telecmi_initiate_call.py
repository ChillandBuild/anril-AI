"""Behavioural tests for POST /calls/initiate on the TeleCMI (cloud) path.

Covers what actually has to be right for a call to connect: permission and
quota gating, Do-Not-Call, the agent-id and caller-id resolution chains, the
exact click2call arguments, persisting request_id as call_sid, and the failure
path (call_log marked failed, app secret never echoed into the HTTP error).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role

TENANT_ID = "tenant-1"
CALL_LOG_ID = "call-log-1"
LEAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CALLER_ID = "11111111-1111-1111-1111-111111111111"
APP_SECRET = "super-secret-app-key"


class _Result:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, rec, table):
        self.rec = rec
        self.table_name = table
        self.op = None
        self.payload = None
        self.filters = {}

    def select(self, *a, **k):
        self.op = "select"
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def maybe_single(self):
        return self

    def execute(self):
        self.rec.ops.append(
            {"table": self.table_name, "op": self.op, "payload": self.payload, "filters": dict(self.filters)}
        )
        if self.op == "select":
            return _Result(self.rec.rows.get(self.table_name))
        if self.op == "insert":
            return _Result([{"id": self.rec.insert_ids.get(self.table_name, "new-id")}])
        return _Result([])


class FakeDB:
    def __init__(self, rows=None):
        self.ops = []
        self.rows = rows or {}
        self.insert_ids = {"call_logs": CALL_LOG_ID, "leads": "new-lead-id"}

    def table(self, name):
        return _Query(self, name)

    def inserts_to(self, table):
        return [o["payload"] for o in self.ops if o["table"] == table and o["op"] == "insert"]

    def updates_to(self, table):
        return [o["payload"] for o in self.ops if o["table"] == table and o["op"] == "update"]


class InitiateCallTests(unittest.TestCase):
    """Owner role by default — the dialer permission gate is tested separately."""

    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": TENANT_ID, "role": "owner"}
        self.addCleanup(app.dependency_overrides.clear)

        self.settings_map = {
            "telecmi_secret": APP_SECRET,
            "telecmi_callerid": "+911203203937",
            "telecmi_user_id": None,
        }
        patches = [
            patch("app.routes.calls.check_quota", return_value=True),
            patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "telecmi"}),
            patch("app.routes.calls.get_setting", side_effect=lambda key, **kw: self.settings_map.get(key)),
            patch("app.routes.calls.new_lead_score_and_segment", return_value=(50, "C")),
            patch("app.routes.calls.mark_activity_today"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _post(self, db, body, click_result=None, click_error=None):
        kwargs = {"side_effect": click_error} if click_error else {"return_value": click_result}
        with patch("app.routes.calls.get_supabase", return_value=db), patch(
            "app.routes.calls.initiate_click2call", **kwargs
        ) as mock_click:
            res = self.client.post("/api/v1/calls/initiate", json=body)
        return res, mock_click

    # ── gating ────────────────────────────────────────────────────────

    def test_requires_lead_id_or_phone(self):
        res, _ = self._post(FakeDB(), {})
        self.assertEqual(res.status_code, 400)
        self.assertIn("lead_id or phone", res.json()["detail"])

    def test_missing_app_secret_is_rejected_before_dialing(self):
        self.settings_map["telecmi_secret"] = None
        res, mock_click = self._post(FakeDB(), {"phone": "+919342012824"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("App Secret", res.json()["detail"])
        mock_click.assert_not_called()

    def test_do_not_call_lead_is_never_dialled(self):
        db = FakeDB({"leads": {"phone": "+919342012824", "name": "X", "do_not_call": True}})
        res, mock_click = self._post(db, {"lead_id": LEAD_ID})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Do Not Call", res.json()["detail"])
        mock_click.assert_not_called()

    def test_dialer_permission_is_enforced_for_non_owners(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": TENANT_ID,
            "role": "telecaller",
            "permissions": [],
        }
        res, mock_click = self._post(FakeDB(), {"phone": "+919342012824"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("telecalling.dialer", res.json()["detail"])
        mock_click.assert_not_called()

    # ── the click2call arguments ──────────────────────────────────────

    def test_click2call_receives_documented_arguments(self):
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": "5133_33337312",
                            "telecmi_agent_password": None},
            }
        )
        res, mock_click = self._post(
            db,
            {"lead_id": LEAD_ID, "caller_id": CALLER_ID},
            click_result={"code": 200, "msg": "Call initiated", "request_id": "req-abc-123"},
        )
        self.assertEqual(res.status_code, 200)
        kwargs = mock_click.call_args.kwargs
        self.assertEqual(kwargs["agent_id"], "5133_33337312")
        self.assertEqual(kwargs["secret"], APP_SECRET)
        self.assertEqual(kwargs["to"], "+919342012824")
        self.assertEqual(kwargs["callerid"], "+911203203937")
        # Docs: WebRTC must be false when followme is true (call rings the
        # agent's mobile rather than a softphone).
        self.assertIs(kwargs["followme"], True)
        self.assertIs(kwargs["webrtc"], False)
        # extra_params carries the call_log_id so the CDR can be tied back.
        self.assertEqual(kwargs["custom"], CALL_LOG_ID)

    def test_agent_id_falls_back_to_global_setting(self):
        """Caller has no agent id of their own, and there is no owner row."""
        self.settings_map["telecmi_user_id"] = "9999_33337312"
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": None,
                            "telecmi_agent_password": None},
                "tenant_users": None,
            }
        )
        _, mock_click = self._post(
            db,
            {"lead_id": LEAD_ID, "caller_id": CALLER_ID},
            click_result={"code": 200, "request_id": "req-1"},
        )
        self.assertEqual(mock_click.call_args.kwargs["agent_id"], "9999_33337312")

    def test_no_agent_id_anywhere_is_a_clear_error(self):
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": None,
                            "telecmi_agent_password": None},
                "tenant_users": None,
            }
        )
        res, mock_click = self._post(db, {"lead_id": LEAD_ID, "caller_id": CALLER_ID})
        self.assertEqual(res.status_code, 400)
        self.assertIn("User ID", res.json()["detail"])
        mock_click.assert_not_called()

    def test_caller_phone_is_used_when_no_callerid_configured(self):
        self.settings_map["telecmi_callerid"] = None
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": "5133_33337312",
                            "telecmi_agent_password": None},
            }
        )
        _, mock_click = self._post(
            db,
            {"lead_id": LEAD_ID, "caller_id": CALLER_ID},
            click_result={"code": 200, "request_id": "req-1"},
        )
        self.assertEqual(mock_click.call_args.kwargs["callerid"], "+919000000000")

    # ── persistence ───────────────────────────────────────────────────

    def test_request_id_is_stored_as_call_sid(self):
        """The CDR webhook falls back to matching on call_sid, so this must persist."""
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": "5133_33337312",
                            "telecmi_agent_password": None},
            }
        )
        res, _ = self._post(
            db,
            {"lead_id": LEAD_ID, "caller_id": CALLER_ID},
            click_result={"code": 200, "request_id": "req-abc-123"},
        )
        self.assertEqual(res.json()["call_sid"], "req-abc-123")
        self.assertIn({"call_sid": "req-abc-123"}, db.updates_to("call_logs"))

    def test_call_log_is_tagged_with_the_telecmi_provider(self):
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": "5133_33337312",
                            "telecmi_agent_password": None},
            }
        )
        self._post(
            db,
            {"lead_id": LEAD_ID, "caller_id": CALLER_ID},
            click_result={"code": 200, "request_id": "req-1"},
        )
        row = db.inserts_to("call_logs")[0]
        self.assertEqual(row["provider"], "telecmi")
        self.assertEqual(row["status"], "initiated")
        self.assertEqual(row["feedback_source"], "automatic")

    # ── failure path ──────────────────────────────────────────────────

    def test_failed_dial_marks_the_call_log_failed(self):
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": "5133_33337312",
                            "telecmi_agent_password": None},
            }
        )
        res, _ = self._post(
            db,
            {"lead_id": LEAD_ID, "caller_id": CALLER_ID},
            click_error=RuntimeError("TeleCMI error (420): Follow-me calls are not allowed for this app"),
        )
        self.assertEqual(res.status_code, 424)
        self.assertIn({"status": "failed"}, db.updates_to("call_logs"))
        # The real provider message must reach the operator, not be swallowed.
        self.assertIn("Follow-me calls are not allowed", res.json()["detail"])

    def test_app_secret_is_never_echoed_in_the_error_response(self):
        db = FakeDB(
            {
                "leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False},
                "callers": {"phone": "+919000000000", "telecmi_agent_id": "5133_33337312",
                            "telecmi_agent_password": None},
            }
        )
        res, _ = self._post(
            db,
            {"lead_id": LEAD_ID, "caller_id": CALLER_ID},
            click_error=RuntimeError(f"upstream rejected secret={APP_SECRET}"),
        )
        self.assertEqual(res.status_code, 424)
        self.assertNotIn(APP_SECRET, res.text)
        self.assertIn("***", res.json()["detail"])

    # ── the SIM path must stay untouched ──────────────────────────────

    def test_sim_basic_never_calls_telecmi(self):
        with patch(
            "app.routes.calls.get_telecalling_config", return_value={"calling_provider": "sim_basic"}
        ):
            db = FakeDB({"leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False}})
            res, mock_click = self._post(db, {"lead_id": LEAD_ID})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["provider"], "sim_basic")
        self.assertEqual(res.json()["status"], "sim_started")
        mock_click.assert_not_called()

    # ── the Office number / My SIM choice on Manual Dial ───────────────

    def test_mode_sim_in_a_cloud_business_records_a_sim_call(self):
        db = FakeDB({"leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False}})
        res, mock_click = self._post(db, {"lead_id": LEAD_ID, "mode": "sim"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["provider"], "sim_basic")
        self.assertEqual(db.inserts_to("call_logs")[0]["provider"], "sim_basic")
        mock_click.assert_not_called()

    def test_mode_office_in_a_sim_business_goes_through_telecmi(self):
        with patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "sim_basic"}):
            db = FakeDB({"leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False}, "callers": {"phone": "+919000000001", "telecmi_agent_id": "agent-1", "telecmi_agent_password": "x"}})
            res, mock_click = self._post(db, {"lead_id": LEAD_ID, "caller_id": CALLER_ID, "mode": "office"}, click_result={"request_id": "req-1"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["provider"], "telecmi")
        mock_click.assert_called_once()

    def test_mode_office_without_app_secret_is_the_same_400(self):
        self.settings_map["telecmi_secret"] = None
        with patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "sim_basic"}):
            res, mock_click = self._post(FakeDB({"leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False}}), {"lead_id": LEAD_ID, "mode": "office"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("App Secret", res.json()["detail"])
        mock_click.assert_not_called()

    def test_mode_sim_still_refuses_do_not_call(self):
        db = FakeDB({"leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": True}})
        res, _ = self._post(db, {"lead_id": LEAD_ID, "mode": "sim"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(db.inserts_to("call_logs"), [])

    def test_hidden_number_caller_cannot_pick_sim(self):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": TENANT_ID, "role": "caller", "caller_id": CALLER_ID, "permissions": ["telecalling.dialer"],
        }
        db = FakeDB({"leads": {"phone": "+919342012824", "name": "Asha", "do_not_call": False}})
        with patch("app.routes.calls.hides_numbers", return_value=True):
            res, mock_click = self._post(db, {"lead_id": LEAD_ID, "mode": "sim"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "Your business hides numbers, so your calls go through the office number.")
        self.assertEqual(db.inserts_to("call_logs"), [])
        self.assertNotIn("9342012824", res.text)
        mock_click.assert_not_called()

    def test_unknown_mode_is_rejected(self):
        res, _ = self._post(FakeDB(), {"lead_id": LEAD_ID, "mode": "carrier-pigeon"})
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
