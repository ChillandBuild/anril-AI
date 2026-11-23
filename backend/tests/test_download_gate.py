"""The "Download lists" rule: owner always, everyone else needs leads.download; every download is logged."""
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
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.services.download_gate import DOWNLOAD_DENIED, can_download, require_download
from tests.fake_supabase import FakeSupabase
from fastapi import HTTPException

DENIED = "You don't have permission to download lists."
ago = lambda hours: (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

OWNER = {"tenant_id": "t1", "role": "owner", "user_id": "owner-1", "caller_id": None, "permissions": []}
STAFF = {"tenant_id": "t1", "role": "caller", "user_id": "staff-1", "caller_id": None,
         "permissions": ["leads.view", "analytics.view", "team.manage"]}
STAFF_WITH = {**STAFF, "permissions": STAFF["permissions"] + ["leads.download"]}


class GateUnitTests(unittest.TestCase):
    def test_owner_always_passes_and_others_need_the_permission(self):
        self.assertTrue(can_download(OWNER))
        self.assertFalse(can_download(STAFF))
        self.assertTrue(can_download(STAFF_WITH))
        self.assertEqual(DOWNLOAD_DENIED, DENIED)
        with self.assertRaises(HTTPException) as cm:
            require_download(STAFF)
        self.assertEqual((cm.exception.status_code, cm.exception.detail), (403, DENIED))
        self.assertIs(require_download(OWNER), OWNER)

    def test_manage_style_permissions_do_not_grant_download(self):
        self.assertFalse(can_download({**STAFF, "permissions": ["leads.manage", "settings.manage", "team.manage"]}))


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.db.rpc = lambda name, params: type("R", (), {"execute": lambda s: type("D", (), {"data": []})()})()
        self.ctx = dict(OWNER)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_tenant_id] = lambda: "t1"
        self.client = TestClient(app)
        self.patches = []

    def start(self, target):
        p = patch(target, return_value=self.db)
        p.start()
        self.patches.append(p)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()

    def audit(self):
        return [r for r in self.db.rows("app_audit_logs") if r.get("action") == "leads.download"]


class InboundExportTests(_Base):
    def setUp(self):
        super().setUp()
        self.start("app.routes.inbound_leads.get_supabase")
        for lid, seg in (("priya", "A"), ("meena", "B")):
            self.db.rows("leads").append({
                "id": lid, "tenant_id": "t1", "name": lid, "phone": "+91" + lid, "source": "whatsapp", "segment": seg,
                "score": 10, "created_at": ago(48), "deleted_at": None, "ad_campaign_id": None, "ai_enabled": True,
                "last_inbound_at": ago(2),
            })

    def test_without_leads_download_it_is_403_and_nothing_is_logged(self):
        self.ctx = dict(STAFF)
        res = self.client.get("/api/v1/inbound-leads/export")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], DENIED)
        self.assertEqual(self.audit(), [])

    def test_with_leads_download_it_is_200_and_logged_with_list_rows_and_filters(self):
        self.ctx = dict(STAFF_WITH)
        res = self.client.get("/api/v1/inbound-leads/export", params={"search": "pri", "result": "none"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual([r["name"] for r in csv.DictReader(io.StringIO(res.content.decode("utf-8-sig")))], ["priya"])
        rows = self.audit()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor_user_id"], "staff-1")
        meta = rows[0]["metadata"]
        self.assertEqual((meta["list"], meta["rows"]), ("Inbound leads", 1))
        self.assertEqual(meta["filters"], {"search": "pri", "result": "none"})  # unused filters are dropped

    def test_the_owner_downloads_without_being_given_the_permission(self):
        res = self.client.get("/api/v1/inbound-leads/export")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.audit()[0]["metadata"]["rows"], 2)

    def test_the_list_itself_is_not_gated(self):
        self.ctx = dict(STAFF)
        self.assertEqual(self.client.get("/api/v1/inbound-leads/").status_code, 200)


class CallLogExportTests(_Base):
    def setUp(self):
        super().setUp()
        self.start("app.routes.analytics.get_supabase")
        self.db.rows("call_logs").append({
            "id": "cl1", "tenant_id": "t1", "created_at": ago(5), "caller_id": "c1", "duration_seconds": 90,
            "outcome": "converted", "score": 80.0, "score_status": "scored",
        })
        p = patch("app.routes.analytics.get_telecalling_config", return_value={"calling_provider": "telecmi"})
        p.start()
        self.patches.append(p)

    def test_403_without_the_permission(self):
        self.ctx = dict(STAFF)
        res = self.client.get("/api/v1/analytics/telecalling/export")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], DENIED)
        self.assertEqual(self.audit(), [])

    def test_200_and_logged_with_the_permission(self):
        self.ctx = dict(STAFF_WITH)
        res = self.client.get("/api/v1/analytics/telecalling/export")
        self.assertEqual(res.status_code, 200, res.text)
        meta = self.audit()[0]["metadata"]
        self.assertEqual((meta["list"], meta["rows"]), ("Call log (last 90 days)", 1))
        self.assertEqual(meta["filters"], {"days": 90})


class AssignmentLogCsvTests(_Base):
    def setUp(self):
        super().setUp()
        self.start("app.routes.assignment_log.get_supabase")
        self.db.rows("lead_stage_events").append({
            "id": "e1", "tenant_id": "t1", "lead_id": "l1", "to_segment": "A", "event_type": "assigned",
            "metadata": {"caller_id": "c1", "caller_name": "Anitha"}, "created_at": ago(1),
        })
        self.db.rows("leads").append({"id": "l1", "tenant_id": "t1", "name": "Ravi K", "phone": "+911"})

    def test_the_owner_downloads_it_and_it_is_logged(self):
        res = self.client.get("/api/v1/assignment-log", params={"format": "csv", "segment": "A"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(list(csv.DictReader(io.StringIO(res.text)))[0]["lead_name"], "Ravi K")
        meta = self.audit()[0]["metadata"]
        self.assertEqual((meta["list"], meta["rows"], meta["filters"]), ("Assignment log", 1, {"segment": "A"}))

    def test_a_non_owner_needs_the_download_permission_too(self):
        self.ctx = dict(STAFF)  # can see the page (team.manage) but may not download
        self.assertEqual(self.client.get("/api/v1/assignment-log", params={"format": "csv"}).status_code, 403)
        self.assertEqual(self.audit(), [])
        self.ctx = dict(STAFF_WITH)
        self.assertEqual(self.client.get("/api/v1/assignment-log", params={"format": "csv"}).status_code, 200)
        self.assertEqual(self.audit()[0]["metadata"]["rows"], 1)


if __name__ == "__main__":
    unittest.main()
