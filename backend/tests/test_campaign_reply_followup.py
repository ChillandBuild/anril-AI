"""Follow-up trigger "campaign reply, no order" (services/campaign_reply_followup.py + the engine)."""
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import campaign_reply_followup as crf
from app.services import reengagement_service as rs
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
NOW = datetime(2026, 11, 24, 6, 30, tzinfo=timezone.utc)  # Tuesday 12:00 IST
STEP_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "step"))
BROADCAST = str(uuid.uuid5(uuid.NAMESPACE_URL, "broadcast"))


def U(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "crf:" + name))


def ago(days=0.0, hours=0.0):
    return (NOW - timedelta(days=days, hours=hours)).isoformat()


class _Picker:
    def __init__(self, _tenant):
        pass

    def next(self, prefer_meta_id=None):
        return {"id": "n1", "meta_phone_number_id": "pn1"}


def _lead(db, name, **extra):
    row = {"id": U(name), "tenant_id": T1, "name": name, "phone": "+91" + name, "segment": "B", "source": "organic",
           "opted_out": None, "blocked_at": None, "converted_at": None, "whatsapp_undeliverable": None,
           "last_inbound_at": ago(days=2), "last_inbound_phone_number_id": "pn1", "ad_campaign_id": None}
    row.update(extra)
    db.rows("leads").append(row)
    return row["id"]


def _sent(db, lead_id, days_ago, broadcast=BROADCAST, tenant=T1):
    db.add("broadcast_recipients", tenant_id=tenant, broadcast_id=broadcast, lead_id=lead_id,
           send_status="sent", created_at=ago(days=days_ago))


def _reply(db, lead_id, days_ago, tenant=T1):
    db.add("messages", tenant_id=tenant, lead_id=lead_id, direction="inbound", content="hi", created_at=ago(days=days_ago))


def _step(**over):
    step = {"id": STEP_ID, "tenant_id": T1, "type": "campaign_reply", "broadcast_id": None, "delay_hours": 48,
            "target_segments": ["A", "B", "C"], "target_sources": None, "message_type": "template",
            "template_name": "nudge", "template_variables": ["name"], "fallback_template_name": None,
            "fallback_template_variables": None, "message_content": None}
    step.update(over)
    return step


class DueTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()

    def due(self, step=None):
        return crf.due_lead_ids(self.db, T1, step or _step(), NOW)

    def test_replied_and_no_order_is_due_after_the_wait(self):
        a = _lead(self.db, "a")
        _sent(self.db, a, 5)
        _reply(self.db, a, 4)  # replied 4 days ago, waited 2 days
        self.assertEqual(self.due(), [a])

    def test_people_already_logged_for_the_step_are_skipped_before_the_scans(self):
        a, b = _lead(self.db, "a"), _lead(self.db, "b")
        for lead in (a, b):
            _sent(self.db, lead, 5)
            _reply(self.db, lead, 4)
        self.db.add("reengagement_logs", step_id=STEP_ID, lead_id=a, status="sent")
        seen = []
        real = crf._paged

        def spy(make_query, what):
            seen.append(what)
            return real(make_query, what)

        with patch.object(crf, "_paged", spy):
            self.assertEqual(self.due(), [b])
        self.assertEqual(seen[0], "reengagement_logs")  # read first

    def test_not_due_before_the_wait_is_over(self):
        a = _lead(self.db, "a")
        _sent(self.db, a, 3)
        _reply(self.db, a, 1)
        self.assertEqual(self.due(), [])

    def test_no_reply_means_not_due(self):
        a = _lead(self.db, "a")
        _sent(self.db, a, 6)
        self.assertEqual(self.due(), [])

    def test_a_reply_long_after_the_campaign_is_not_a_reply_to_it(self):
        a = _lead(self.db, "a")
        _sent(self.db, a, 12)
        _reply(self.db, a, 6)  # 6 days after, window is 3
        self.assertEqual(self.due(), [])

    def test_an_order_since_the_campaign_removes_them(self):
        a, b = _lead(self.db, "a"), _lead(self.db, "b")
        for lead in (a, b):
            _sent(self.db, lead, 5)
            _reply(self.db, lead, 4)
        self.db.add("deals", tenant_id=T1, lead_id=a, stage="won", created_at=ago(days=3))
        self.db.add("deals", tenant_id=T1, lead_id=b, stage="quoted", created_at=ago(days=3))  # a quote is not an order
        self.assertEqual(self.due(), [b])

    def test_an_old_order_before_the_campaign_does_not_count(self):
        a = _lead(self.db, "a")
        _sent(self.db, a, 5)
        _reply(self.db, a, 4)
        self.db.add("deals", tenant_id=T1, lead_id=a, stage="won", created_at=ago(days=40))
        self.assertEqual(self.due(), [a])

    def test_old_replies_are_not_chased(self):
        a = _lead(self.db, "a")
        _sent(self.db, a, 60)
        _reply(self.db, a, 59)  # due 57 days ago
        self.assertEqual(self.due(), [])

    def test_a_named_campaign_only_counts_its_own_replies(self):
        a, b = _lead(self.db, "a"), _lead(self.db, "b")
        _sent(self.db, a, 5, broadcast=BROADCAST)
        _sent(self.db, b, 5, broadcast="other")
        _reply(self.db, a, 4)
        _reply(self.db, b, 4)
        self.assertEqual(self.due(_step(broadcast_id=BROADCAST)), [a])
        self.assertEqual(sorted(self.due()), sorted([a, b]))

    def test_other_business_rows_are_never_read(self):
        x = U("x")
        self.db.rows("leads").append({"id": x, "tenant_id": T2})
        _sent(self.db, x, 5, tenant=T2)
        _reply(self.db, x, 4, tenant=T2)
        self.assertEqual(self.due(), [])


class EngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.db.rows("reengagement_steps").append(_step())
        self.send = AsyncMock(return_value={"messages": [{"id": "wamid"}]})
        self.patches = [
            patch.object(rs, "get_supabase", return_value=self.db),
            patch.object(rs, "utcnow", return_value=NOW),
            patch.object(rs, "SenderPicker", _Picker),
            patch.object(rs, "template_status", return_value="APPROVED"),
            patch.object(rs, "ai_replies_allowed", return_value=True),
            patch.object(rs, "send_template_message", self.send),
        ]
        for p in self.patches:
            p.start()
        rs._NO_SENDER_UNTIL.clear()
        rs._CAMPAIGN_REPLY_SCANNED.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _due_person(self, name, **extra):
        lead = _lead(self.db, name, **extra)
        _sent(self.db, lead, 5)
        _reply(self.db, lead, 4)
        return lead

    async def test_sends_the_template_once_and_logs_it(self):
        a = self._due_person("a")
        self.assertEqual(await rs.process_due_reengagements(), 1)
        self.assertEqual(self.send.await_args.kwargs["template_name"], "nudge")
        self.assertEqual([r["lead_id"] for r in self.db.rows("reengagement_logs")], [a])
        self.assertEqual(await rs.process_due_reengagements(), 0)  # looked at only every 10 minutes
        rs._CAMPAIGN_REPLY_SCANNED.clear()
        self.assertEqual(await rs.process_due_reengagements(), 0)  # never twice for the same step

    async def test_the_scan_waits_ten_minutes_between_looks(self):
        self._due_person("a")
        later = NOW + timedelta(minutes=11)
        rs._CAMPAIGN_REPLY_SCANNED[STEP_ID] = NOW - timedelta(minutes=2)
        self.assertEqual(await rs.process_due_reengagements(), 0)  # too soon: not even read
        self.send.assert_not_awaited()
        rs._CAMPAIGN_REPLY_SCANNED[STEP_ID] = NOW - timedelta(minutes=11)
        self.assertEqual(await rs.process_due_reengagements(), 1)

    async def test_skips_opted_out_blocked_and_converted(self):
        self._due_person("stop", opted_out=True)
        self._due_person("blocked", blocked_at=ago(days=1))
        self._due_person("bought", converted_at=ago(days=1))
        self._due_person("nophone", phone=None)
        ok = self._due_person("ok")
        self.assertEqual(await rs.process_due_reengagements(), 1)
        self.assertEqual([r["lead_id"] for r in self.db.rows("reengagement_logs")], [ok])

    async def test_step_segments_and_sources_still_apply(self):
        self.db.rows("reengagement_steps")[0].update(target_segments=["A"], target_sources=["meta_ads"])
        self._due_person("b-organic")  # segment B, organic
        self.assertEqual(await rs.process_due_reengagements(), 0)

    async def test_nothing_goes_out_at_night_or_on_sunday(self):
        self._due_person("a")
        for moment in (datetime(2026, 11, 24, 17, 0, tzinfo=timezone.utc),  # 22:30 IST
                       datetime(2026, 11, 29, 6, 30, tzinfo=timezone.utc)):  # Sunday
            with patch.object(rs, "utcnow", return_value=moment):
                self.assertEqual(await rs.process_due_reengagements(), 0)
        self.send.assert_not_awaited()

    async def test_a_template_that_is_not_approved_sends_nothing(self):
        self._due_person("a")
        with patch.object(rs, "template_status", return_value="PENDING"):
            self.assertEqual(await rs.process_due_reengagements(), 0)
        self.assertEqual(self.db.rows("reengagement_logs"), [])

    async def test_a_step_under_one_day_never_fires(self):
        self.db.rows("reengagement_steps")[0]["delay_hours"] = 12
        self._due_person("a")
        self.assertEqual(await rs.process_due_reengagements(), 0)


class StepRouteTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.p = patch("app.routes.reengagement.get_supabase", return_value=self.db)
        self.p.start()
        self.p2 = patch("app.routes.reengagement.template_status", return_value="APPROVED")
        self.p2.start()
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": T1, "role": "owner", "user_id": "u", "permissions": []}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.p.stop()
        self.p2.stop()

    def _body(self, **over):
        body = {"type": "campaign_reply", "delay_hours": 72, "target_segments": ["A", "B"],
                "message_type": "template", "template_name": "nudge"}
        body.update(over)
        return body

    def test_create_a_campaign_reply_step(self):
        res = self.client.post("/api/v1/reengagement/steps", json=self._body())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.db.rows("reengagement_steps")[0]["type"], "campaign_reply")
        self.assertEqual(self.db.rows("reengagement_steps")[0]["tenant_id"], T1)

    def test_under_a_day_is_refused_and_so_is_freeform(self):
        self.assertEqual(self.client.post("/api/v1/reengagement/steps", json=self._body(delay_hours=12)).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/reengagement/steps",
                                          json=self._body(message_type="freeform", template_name=None)).status_code, 400)

    def test_an_unknown_type_is_still_refused(self):
        self.assertEqual(self.client.post("/api/v1/reengagement/steps", json=self._body(type="price_asked")).status_code, 400)

    def test_edit_cannot_shorten_it_below_a_day(self):
        step = self.client.post("/api/v1/reengagement/steps", json=self._body()).json()
        res = self.client.patch(f"/api/v1/reengagement/steps/{step['id']}", json={
            "delay_hours": 6, "target_segments": ["A"], "message_type": "template", "template_name": "nudge"})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
