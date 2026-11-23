"""POST /calls/initiate with the Call IQ rules: calling hours, daily limit, and SIM or cloud per person."""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.services import call_rules
from test_telecmi_initiate_call import FakeDB, TENANT_ID, LEAD_ID, CALLER_ID, APP_SECRET

LEAD = {"phone": "+919342012824", "name": "Asha", "do_not_call": False}
CALLER = {"phone": "+919000000000", "telecmi_agent_id": "5133_1", "telecmi_agent_password": None}


def _ist(h):
    return datetime(2026, 11, 23, h, 0, tzinfo=call_rules.IST)


class InitiateRulesTests(unittest.TestCase):
    provider = "telecmi"

    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        self.role("caller")
        self.addCleanup(app.dependency_overrides.clear)
        self.hour = 12
        self.provider = "telecmi"
        settings_map = {"telecmi_secret": APP_SECRET, "telecmi_callerid": "+911203203937"}
        for p in [
            patch("app.routes.calls.check_quota", return_value=True),
            patch("app.routes.calls.get_telecalling_config", side_effect=lambda *a, **k: {"calling_provider": self.provider}),
            patch("app.routes.calls.get_setting", side_effect=lambda key, **kw: settings_map.get(key)),
            patch("app.routes.calls.new_lead_score_and_segment", return_value=(50, "C")),
            patch("app.routes.calls.mark_activity_today"),
            patch.object(call_rules, "now_ist", side_effect=lambda now=None: _ist(self.hour)),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def role(self, role):
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": TENANT_ID, "role": role, "permissions": ["telecalling.dialer"], "caller_id": CALLER_ID,
        }

    def post(self, rows):
        db = FakeDB(rows)
        with patch("app.routes.calls.get_supabase", return_value=db), patch(
            "app.routes.calls.initiate_click2call", return_value={"code": 200, "request_id": "r1"}
        ) as click:
            res = self.client.post("/api/v1/calls/initiate", json={"lead_id": LEAD_ID, "caller_id": CALLER_ID})
        return res, click

    def test_telecaller_blocked_outside_calling_hours(self):
        self.hour = 22
        res, click = self.post({"leads": LEAD, "callers": CALLER})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"], "Calling hours are 9 AM to 9 PM")
        click.assert_not_called()

    def test_telecaller_may_dial_inside_hours(self):
        res, click = self.post({"leads": LEAD, "callers": CALLER})
        self.assertEqual(res.status_code, 200)
        click.assert_called_once()

    def test_owner_may_dial_at_night(self):
        self.role("owner")
        self.hour = 23
        res, click = self.post({"leads": LEAD, "callers": CALLER})
        self.assertEqual(res.status_code, 200)
        click.assert_called_once()

    def test_daily_limit_blocks_telecaller(self):
        rules = {"app_settings": {"value": json.dumps({"daily_limit_on": True, "daily_limit": 3})}}
        with patch.object(call_rules, "calls_made_today", return_value=3):
            res, click = self.post({"leads": LEAD, "callers": CALLER, **rules})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"], "Daily call limit reached")
        click.assert_not_called()

    def test_do_not_call_still_blocked(self):
        res, click = self.post({"leads": {**LEAD, "do_not_call": True}, "callers": CALLER})
        self.assertEqual(res.status_code, 400)
        click.assert_not_called()

    def test_person_on_sim_uses_sim_even_when_business_is_cloud(self):
        res, click = self.post({"leads": LEAD, "callers": {**CALLER, "calling_mode": "sim"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["provider"], "sim_basic")
        click.assert_not_called()

    def test_person_on_cloud_uses_cloud_even_when_business_is_sim(self):
        self.provider = "sim_basic"
        res, click = self.post({"leads": LEAD, "callers": {**CALLER, "calling_mode": "cloud"}})
        self.assertEqual(res.status_code, 200)
        click.assert_called_once()

    def test_business_default_follows_business(self):
        self.provider = "sim_basic"
        res, click = self.post({"leads": LEAD, "callers": {**CALLER, "calling_mode": "business_default"}})
        self.assertEqual(res.json()["provider"], "sim_basic")
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TelecallerIsAlwaysThemselfTests(unittest.TestCase):
    """Review fix: a telecaller can't use another person's daily limit or calling mode by sending their id."""

    def test_pre_dial_and_mode_use_the_signed_in_caller(self):
        client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": TENANT_ID, "role": "caller", "permissions": ["telecalling.dialer"], "caller_id": CALLER_ID,
        }
        self.addCleanup(app.dependency_overrides.clear)
        seen = {}

        def block(db, tenant_id, *, role, caller_id, now=None):
            seen["block"] = caller_id
            return "Daily call limit reached"

        with patch("app.routes.calls.check_quota", return_value=True), \
             patch("app.routes.calls.get_telecalling_config", return_value={"calling_provider": "sim_basic"}), \
             patch("app.routes.calls.get_setting", return_value=None), \
             patch("app.routes.calls.effective_calling_mode", side_effect=lambda db, t, cid, **k: seen.setdefault("mode", cid) and "sim_basic"), \
             patch("app.routes.calls.pre_dial_block", side_effect=block), \
             patch("app.routes.calls.get_supabase", return_value=FakeDB({})):
            res = client.post("/api/v1/calls/initiate",
                              json={"lead_id": LEAD_ID, "caller_id": "11111111-1111-1111-1111-111111111111"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(seen, {"block": CALLER_ID, "mode": CALLER_ID})
