"""WhatsApp > Numbers: Main or Standby only (Extra removed, migration 348), Make main moves the default
sender, which number does what."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.routes import numbers as number_routes
from app.services import outbound_router
from tests.fake_supabase import FakeSupabase

T = "t1"
MAIN, STANDBY, OTHER = ("11111111-1111-4111-8111-11111111111" + c for c in "123")


class NumberRolesTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        for nid, role, meta in ((MAIN, "primary", "m1"), (STANDBY, "standby", "m2"), (OTHER, "standby", "m3")):
            self.db.add("phone_numbers", id=nid, tenant_id=T, role=role, status="active", meta_phone_number_id=meta,
                        meta_status="CONNECTED", paused_outbound=False, quality_rating="green")
        self.db.add("app_settings", tenant_id=T, key="meta_phone_number_id", value="m1")
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_id] = lambda: T
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "owner", "user_id": "u1", "permissions": []}
        for target in ("get_supabase",):
            p = patch.object(number_routes, target, return_value=self.db)
            p.start()
            self.addCleanup(p.stop)
        p = patch("app.services.failover.invalidate_cache", create=True)
        p.start()
        self.addCleanup(p.stop)
        p = patch("app.config_dynamic.invalidate_cache")
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(number_routes, "get_unlocked_number_ids", return_value={MAIN, STANDBY, OTHER})
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def role(self, nid):
        return next(r for r in self.db.rows("phone_numbers") if r["id"] == nid)["role"]

    def test_make_main_moves_the_default_sender(self):
        res = self.client.patch(f"/api/v1/numbers/{STANDBY}", json={"role": "primary"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual((self.role(MAIN), self.role(STANDBY)), ("standby", "primary"))
        setting = next(r for r in self.db.rows("app_settings") if r["key"] == "meta_phone_number_id")
        self.assertEqual(setting["value"], "m2")

    def test_roles_are_main_or_standby_and_main_cannot_be_demoted_directly(self):
        self.assertEqual(self.client.patch(f"/api/v1/numbers/{STANDBY}", json={"role": "boss"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/v1/numbers/{STANDBY}", json={"role": "extra"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/v1/numbers/{MAIN}", json={"role": "standby"}).status_code, 400)
        self.assertEqual(self.role(STANDBY), "standby")

    def test_list_says_which_number_does_what(self):
        with patch.object(number_routes, "load_usage", side_effect=Exception("no rpc")):
            body = self.client.get("/api/v1/numbers/").json()
        self.assertEqual(body["jobs"]["main_id"], MAIN)
        self.assertEqual(body["jobs"]["default_sender_id"], MAIN)
        self.assertEqual(set(body["jobs"]["reach_ids"]), {MAIN, STANDBY, OTHER})
        self.assertEqual(set(body["jobs"]["picks"]), {"alerts", "otp", "reach"})
        self.assertIn("reach_block", body["data"][0])
        self.assertIn("send_block", body["data"][0])

    def test_campaigns_use_main_first_then_every_standby(self):
        rows = [r for r in self.db.rows("phone_numbers")]
        with patch.object(outbound_router, "can_broadcast", return_value=True), \
             patch.object(outbound_router, "broadcast_cap", return_value=100), \
             patch.object(outbound_router, "portfolio_limit", return_value=1000):
            picked = outbound_router._eligible(rows, {}, {MAIN, STANDBY, OTHER}, outbound_router.Usage())
        self.assertEqual(picked[0]["id"], MAIN)
        self.assertEqual({r["id"] for r in picked}, {MAIN, STANDBY, OTHER})


if __name__ == "__main__":
    unittest.main()
