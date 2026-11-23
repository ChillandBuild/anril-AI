"""Reach routes and send loop with a Customers group or an uploaded list, on the fake database:
the confirm preview, group sends reusing the pipeline, the monthly-limit / blocked skips,
the History numbers (skipped, paid within 7 days) and permissions."""
import asyncio
import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.config import settings
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.routes import upload
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
OWNER = {"tenant_id": T1, "role": "owner", "user_id": "u1", "permissions": []}
REACH_ONLY = {"tenant_id": T1, "role": "staff", "user_id": "u2", "permissions": ["outbound_leads.manage"]}
REACH_AND_DEALS = {**REACH_ONLY, "permissions": ["outbound_leads.manage", "leads.view", "deals.view"]}


def U(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "anril-reach-pipe:" + name))


def now_iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def day_time_iso(days: int, hour_ist: int = 11) -> str:
    """`days` from today at `hour_ist` India time: a schedule time inside 9 AM-9 PM whatever the clock says."""
    ist = timezone(timedelta(hours=5, minutes=30))
    day = datetime.now(ist).date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour_ist, 0, tzinfo=ist).isoformat()


class _Picker:
    def __init__(self, tenant_id):
        self.sent = []

    def next(self):
        return {"id": "n1", "meta_phone_number_id": "pn1"}

    async def record_sent(self, sender):
        pass

    def numbers_used_label(self):
        return "+910000000000"


class ReachBase(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.group = U("group")
        self.db.rows("customer_groups").append({"id": self.group, "tenant_id": T1, "name": "Insta Hot", "kind": "picked"})
        self.db.rows("customer_groups").append({"id": U("theirs"), "tenant_id": T2, "name": "Theirs", "kind": "picked"})

        def lead(name, phone, **extra):
            self.db.rows("leads").append({
                "id": U(name), "tenant_id": T1, "name": name, "phone": phone, "source": "whatsapp",
                "opt_in_source": "website", "created_at": "2026-01-01T00:00:00+00:00", "deleted_at": None,
                "opted_out": None, "whatsapp_undeliverable": None, **extra})
            self.db.rows("customer_group_members").append({"group_id": self.group, "lead_id": U(name), "tenant_id": T1})

        lead("ann", "+919000000001")
        lead("bob", "+919000000002", opted_out=True)
        lead("cat", "+919000000003", opt_in_source=None)
        lead("dev", "+919000000004", blocked_at="2026-11-01")
        lead("eli", "+919000000005")
        lead("fay", "+919000000006")
        # eli already got two Reach campaigns this month.
        for b in ("b1", "b2"):
            self.db.rows("broadcast_recipients").append({
                "id": str(uuid.uuid4()), "tenant_id": T1, "broadcast_id": b, "phone": "+919000000005",
                "send_status": "sent", "created_at": now_iso(seconds=-5)})
        self.ctx = OWNER
        self.patches = [patch("app.routes.upload.get_supabase", return_value=self.db)]
        for p in self.patches:
            p.start()
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_tenant_id] = lambda: T1
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()


class PreviewTests(ReachBase):
    def post(self, body):
        return self.client.post("/api/v1/upload/reach-preview", json=body)

    def test_group_preview_lists_who_is_left_out_and_the_cost(self):
        with patch.object(settings, "meta_marketing_rate_inr", 0.8631):
            res = self.post({"group_id": self.group})
        self.assertEqual(res.status_code, 200, res.text)
        b = res.json()
        self.assertEqual(b["audience"], "group")
        self.assertEqual(b["group"]["name"], "Insta Hot")
        self.assertEqual((b["in_audience"], b["said_stop"], b["no_opt_in"], b["blocked"], b["over_cap"], b["will_get"]),
                         (6, 1, 1, 1, 1, 2))
        self.assertEqual(b["monthly_limit"], 2)
        self.assertEqual((b["rate_inr"], b["cost_inr"]), (0.8631, round(2 * 0.8631, 2)))
        # Every person is in exactly one bucket.
        self.assertEqual(b["in_audience"], sum(b[k] for k in
                         ("said_stop", "no_opt_in", "no_number", "blocked", "negative_reply", "over_cap", "will_get")))

    def test_uploaded_list_preview_applies_the_same_cap_and_blocked_rules(self):
        leads = [{"phone": p, "opt_in_source": "website"} for p in ("+919000000005", "+919000000004", "+919777777777")]
        b = self.post({"leads": leads}).json()
        self.assertEqual((b["audience"], b["over_cap"], b["blocked"], b["will_get"]), ("list", 1, 1, 1))

    def test_another_tenants_group_is_not_found(self):
        self.assertEqual(self.post({"group_id": U("theirs")}).status_code, 404)

    def test_a_group_needs_customers_access(self):
        self.ctx = REACH_ONLY
        res = self.post({"group_id": self.group})
        self.assertEqual(res.status_code, 403)
        self.assertIn("Customers", res.json()["detail"])
        self.ctx = REACH_AND_DEALS
        self.assertEqual(self.post({"group_id": self.group}).status_code, 200)


class GroupSendTests(ReachBase):
    def send(self, **extra):
        body = {"leads": [], "template_name": "diwali", "schedule_type": "now", "group_id": self.group, **extra}
        with patch("app.routes.upload.template_status", return_value="APPROVED"), \
                patch("app.routes.upload.get_best_number", new=AsyncMock(return_value={"id": "n1"})), \
                patch("app.routes.upload._execute_immediate_send", new=AsyncMock()) as run:
            res = self.client.post("/api/v1/upload/bulk-send", json=body)
        return res, run

    def test_group_people_go_through_the_same_pipeline_without_a_lead_upsert(self):
        before = json.dumps(self.db.rows("leads"), sort_keys=True)
        res, run = self.send()
        self.assertEqual(res.status_code, 200, res.text)
        kw = run.call_args.kwargs
        # Opted in only (ann, dev, eli, fay); said-stop bob and no-opt-in cat are left out up front.
        self.assertEqual({l.phone for l in kw["eligible"]},
                         {"+919000000001", "+919000000004", "+919000000005", "+919000000006"})
        self.assertEqual(kw["rejected"], [])
        self.assertEqual(kw["phone_to_lead_id"]["+919000000001"], U("ann"))
        self.assertEqual(kw["blocked_keys"], {"919000000004"})
        self.assertEqual(kw["monthly_limit_keys"], {"919000000005"})
        self.assertEqual(kw["body"].csv_file_name, "Group: Insta Hot")
        self.assertFalse(kw["body"].include_opted_out)
        # Customers keep their source, name and score: nothing was re-saved as an "upload".
        self.assertEqual(json.dumps(self.db.rows("leads"), sort_keys=True), before)

    def test_the_browser_cannot_slip_extra_people_into_a_group_send(self):
        res, run = self.send(leads=[{"phone": "+919888888888", "opt_in_source": "website"}])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("+919888888888", {l.phone for l in run.call_args.kwargs["eligible"]})

    def test_another_tenants_group_is_refused(self):
        res, run = self.send(group_id=U("theirs"))
        self.assertEqual(res.status_code, 404)
        run.assert_not_called()

    def test_a_scheduled_group_send_keeps_the_group_label_and_people(self):
        res, _ = self.send(schedule_type="scheduled", schedule_at=day_time_iso(1))
        self.assertEqual(res.status_code, 200, res.text)
        row = self.db.rows("scheduled_broadcasts")[0]
        self.assertEqual(row["csv_file_name"], "Group: Insta Hot")
        self.assertEqual(len(row["leads_json"]), 4)


class SendLoopTests(ReachBase):
    def run_send(self, leads):
        body = upload.BulkSendRequest(leads=leads, template_name="diwali", schedule_type="now")
        phones = [l.phone for l in leads]
        blocked, over = upload.reach_audience.send_time_skips(self.db, T1, phones, exclude_broadcast_id="live")
        self.db.rows("scheduled_broadcasts").append({"id": "live", "tenant_id": T1, "status": "running"})
        send = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})
        with patch("app.routes.upload.send_template_message", new=send), \
                patch("app.routes.upload.SenderPicker", _Picker), \
                patch("app.routes.upload.new_lead_score_and_segment", return_value=(10, "C")):
            asyncio.run(upload._execute_immediate_send(
                tenant_id=T1, broadcast_id="live", broadcast_timestamp=datetime.now(timezone.utc), body=body,
                eligible=leads, rejected=[], invalid_leads=[], all_phones=phones,
                phone_to_lead_id={l.phone: None for l in leads}, phone_to_lead_name={},
                all_opted_out_phones=set(), tag_opted_out_phones=set(), globally_opted_out_phones=set(),
                negative_reply_phones=set(), tpl_body="", tpl_lang="en", tpl_header={}, _has_fail_reason=True,
                blocked_keys=blocked, monthly_limit_keys=over))
        return send

    def test_capped_and_blocked_people_are_skipped_not_sent_and_not_failed(self):
        leads = [upload.BulkLeadItem(phone=p, opt_in_source="website")
                 for p in ("+919000000001", "+919000000004", "+919000000005")]
        send = self.run_send(leads)
        self.assertEqual([c.kwargs["to_number"] for c in send.call_args_list], ["+919000000001"])
        rows = {r["phone"]: r for r in self.db.rows("broadcast_recipients") if r["broadcast_id"] == "live"}
        self.assertEqual(rows["+919000000001"]["send_status"], "sent")
        self.assertEqual((rows["+919000000005"]["send_status"], rows["+919000000005"]["fail_reason"]),
                         ("opted_out_skip", "monthly_limit"))
        self.assertEqual(rows["+919000000004"]["fail_reason"], "blocked")
        result = json.loads(self.db.rows("scheduled_broadcasts")[0]["result"])
        self.assertEqual((result["sent"], result["failed"], result["skipped_monthly_limit"], result["skipped_blocked"]),
                         (1, 0, 1, 1))
        entry = json.loads(next(r for r in self.db.rows("app_settings") if r["key"] == "broadcast_history")["value"])[0]
        self.assertEqual((entry["sent"], entry["failed"], entry["skipped_monthly_limit"], entry["skipped_blocked"]),
                         (1, 0, 1, 1))

    def test_the_classifier_counts_skips_apart_from_failures_and_opt_outs(self):
        self.run_send([upload.BulkLeadItem(phone=p, opt_in_source="website")
                       for p in ("+919000000001", "+919000000004", "+919000000005")])
        out = upload._classify_broadcast_outcomes(self.db, T1, "live", now_iso())
        c = out["counts"]
        self.assertEqual((c["sent"], c["failed"], c["opted_out"], c["skipped_monthly_limit"], c["skipped_blocked"]),
                         (1, 0, 0, 1, 1))
        self.assertEqual(out["failures"], [])


class HistoryTests(ReachBase):
    def setUp(self):
        super().setUp()
        sent_at = datetime.now(timezone.utc) - timedelta(days=2)
        self.db.rows("app_settings").append({"tenant_id": T1, "key": "broadcast_history", "value": json.dumps([
            {"broadcast_id": "h1", "timestamp": sent_at.isoformat(), "template_name": "t", "sent": 3,
             "csv_file_name": "Group: Insta Hot"},
            {"broadcast_id": "h2", "timestamp": sent_at.isoformat(), "template_name": "t", "sent": 0},
        ])})
        self.db.rows("broadcast_recipients").append({
            "id": "r1", "tenant_id": T1, "broadcast_id": "h1", "lead_id": U("ann"), "phone": "+919000000001",
            "send_status": "sent", "created_at": sent_at.isoformat()})
        self.db.rows("deals").append({
            "id": "d1", "tenant_id": T1, "lead_id": U("ann"), "stage": "won", "total_paise": 4150000,
            "won_at": (sent_at + timedelta(days=1)).isoformat(), "created_at": sent_at.isoformat()})

    def history(self):
        return {h["broadcast_id"]: h for h in self.client.get("/api/v1/upload/history").json()["data"]}

    def test_an_owner_sees_the_count_and_the_rupees(self):
        h = self.history()["h1"]
        self.assertEqual((h["paid_count"], h["paid_amount_inr"], h["paid_window_open"]), (1, 41500, True))
        self.assertEqual((h["audience_type"], h["group_name"]), ("group", "Insta Hot"))
        self.assertNotIn("paid_count", self.history()["h2"])   # nothing was sent: no figure

    def test_without_deals_view_only_the_count_is_returned(self):
        self.ctx = {**REACH_ONLY, "permissions": ["outbound_leads.view"]}
        h = self.history()["h1"]
        self.assertEqual(h["paid_count"], 1)
        self.assertNotIn("paid_amount_inr", h)

    def test_with_deals_view_the_rupees_are_returned(self):
        self.ctx = {**REACH_ONLY, "permissions": ["outbound_leads.view", "deals.view"]}
        self.assertEqual(self.history()["h1"]["paid_amount_inr"], 41500)

    def test_a_direct_call_from_the_operator_console_still_works(self):
        out = asyncio.run(upload.get_broadcast_history(tenant_id=T1))
        self.assertEqual(len(out["data"]), 2)
        self.assertNotIn("paid_count", out["data"][0])


if __name__ == "__main__":
    unittest.main()
