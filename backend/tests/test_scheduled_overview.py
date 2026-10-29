"""The Scheduled templates page: one list of scheduled templates and broadcasts (migration 236)."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.services import call_details_share as share
from app.services import scheduled_overview as ov
from app.services import scheduled_templates as sched
from tests.fake_supabase import FakeSupabase

NOW = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)
TB, BC = sched.TABLE, ov.BROADCASTS


def at(**delta) -> str:
    return (NOW + timedelta(**delta)).isoformat()


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        for i, name in enumerate(("Arun", "Divya")):
            self.db.add("leads", id=f"l{i}", tenant_id="t1", name=name, phone=f"+9198000000{i}", source="whatsapp")
        self.db.add("leads", id="other", tenant_id="t2", name="Other", phone="+919", source="whatsapp")
        self.db.add("callers", tenant_id="t1", user_id="u-karthik", name="Karthik")
        self.db.add("tenant_users", tenant_id="t1", user_id="u-owner", role="owner")

    def template(self, lead="l0", status="scheduled", send_at=None, tenant="t1", **extra):
        row = dict(tenant_id=tenant, lead_id=lead, template_id="tpl", template_name="promo", variables=[], content="Hi",
                   send_at=send_at or at(days=1), status=status, created_by="u-karthik")
        return self.db.add(TB, **{**row, **extra})

    def broadcast(self, status="pending", fire_at=None, created=None, **extra):
        row = dict(tenant_id="t1", template_name="diwali", schedule_type="scheduled", fire_at=fire_at or at(days=1),
                   created_at=created or at(hours=-1), status=status, created_by="u-owner", recipient_count=100,
                   csv_file_name="leads.csv", csv_file_path="t1/ab_leads.csv", error=None, drip_group_id=None)
        return self.db.add(BC, **{**row, **extra})


class ListTemplateTests(_Base):
    def test_lists_waiting_and_recent_rows_with_the_lead_and_who_scheduled(self):
        self.template(batch_id="b1", batch_label="Hot leads")
        self.template(lead="l1", created_by="u-owner")
        self.template(status="sent", send_at=at(days=-2))
        self.template(status="cancelled", send_at=at(days=-30))  # too old
        self.template(lead="other", tenant="t2")  # another tenant
        rows = ov.list_templates(self.db, "t1", NOW)
        self.assertEqual(len(rows), 3)
        first = next(r for r in rows if r["batch_id"] == "b1")
        self.assertEqual((first["lead_name"], first["created_by_name"], first["batch_label"]), ("Arun", "Karthik", "Hot leads"))
        self.assertEqual(next(r for r in rows if r["lead_id"] == "l1")["created_by_name"], "Owner")
        self.assertNotIn("t2", [r["lead_phone"] for r in rows])

    def test_unknown_scheduler_is_named_plainly(self):
        self.template(created_by=None)
        self.assertEqual(ov.list_templates(self.db, "t1", NOW)[0]["created_by_name"], "Team member")


class ListBroadcastTests(_Base):
    def test_send_now_rows_are_not_shown_as_scheduled(self):
        self.broadcast(status="done", fire_at=at(hours=-1), created=at(hours=-1))
        self.broadcast(status="done", fire_at=at(hours=-5), created=at(days=-1))  # was set for later, then went out
        rows = ov.list_broadcasts(self.db, "t1", NOW)
        self.assertEqual([r["status"] for r in rows], ["sent"])

    def test_a_drip_is_one_row_with_the_days_and_total_recipients(self):
        for day in range(3):
            self.broadcast(schedule_type="drip", drip_group_id="g1", fire_at=at(days=day + 1), recipient_count=40 + day)
        self.broadcast()
        rows = ov.list_broadcasts(self.db, "t1", NOW)
        drip = next(r for r in rows if r["kind"] == "drip")
        self.assertEqual((drip["days"], drip["recipients"], len(drip["ids"])), (3, 123, 3))
        self.assertEqual(drip["send_at"], at(days=1))
        self.assertEqual(len(rows), 2)

    def test_file_name_and_who_scheduled(self):
        self.broadcast()
        row = ov.list_broadcasts(self.db, "t1", NOW)[0]
        self.assertEqual((row["file_name"], row["has_file"], row["created_by_name"]), ("leads.csv", True, "Owner"))
        self.assertNotIn("csv_file_path", row)

    def test_other_tenants_are_never_listed(self):
        self.broadcast(tenant_id="t2")
        self.assertEqual(ov.list_broadcasts(self.db, "t1", NOW), [])


class BroadcastChangeTests(_Base):
    def test_cancel_and_undo_cover_every_waiting_day_of_a_drip(self):
        days = [self.broadcast(schedule_type="drip", drip_group_id="g1", fire_at=at(days=d + 1)) for d in range(3)]
        self.assertEqual(ov.cancel_broadcast(self.db, "t1", days[0]["id"], NOW), 3)
        self.assertEqual({r["status"] for r in self.db.rows(BC)}, {"cancelled"})
        self.assertEqual(ov.restore_broadcast(self.db, "t1", days[0]["id"], NOW), 3)
        self.assertEqual({r["status"] for r in self.db.rows(BC)}, {"pending"})

    def test_undo_is_refused_once_the_time_has_passed(self):
        row = self.broadcast(status="cancelled", fire_at=at(minutes=-5))
        with self.assertRaises(share.ShareError):
            ov.restore_broadcast(self.db, "t1", row["id"], NOW)

    def test_moving_a_drip_keeps_the_gap_between_days(self):
        days = [self.broadcast(schedule_type="drip", drip_group_id="g1", fire_at=at(days=d + 1)) for d in range(3)]
        new_first = NOW + timedelta(days=5)
        self.assertEqual(ov.reschedule_broadcast(self.db, "t1", days[0]["id"], new_first, NOW), 3)
        fires = sorted(r["fire_at"] for r in self.db.rows(BC))
        self.assertEqual(fires, [(new_first + timedelta(days=d)).isoformat() for d in range(3)])

    def test_time_limits_match_templates(self):
        row = self.broadcast()
        for when in (NOW + timedelta(minutes=2), NOW + timedelta(days=31)):
            with self.assertRaises(share.ShareError):
                ov.reschedule_broadcast(self.db, "t1", row["id"], when, NOW)

    def test_another_tenants_broadcast_cannot_be_touched(self):
        row = self.broadcast(tenant_id="t2")
        with self.assertRaises(sched.NotFound):
            ov.cancel_broadcast(self.db, "t1", row["id"], NOW)
        self.assertEqual(self.db.rows(BC)[0]["status"], "pending")


class BulkTests(_Base):
    def test_each_row_succeeds_or_fails_on_its_own(self):
        ok = self.template()
        sent = self.template(status="sent", send_at=at(days=-1))
        with patch.object(sched, "utcnow", return_value=NOW):
            result = ov.apply_bulk(self.db, "t1", "cancel", [ok["id"], sent["id"]], [], None, True, True, NOW)
        self.assertEqual(result["done"], 1)
        self.assertEqual([f["id"] for f in result["failed"]], [sent["id"]])
        self.assertEqual(result["failed"][0]["reason"], "It has already been sent.")

    def test_reschedule_moves_a_whole_batch_to_one_time(self):
        rows = [self.template(lead=f"l{i}", batch_id="b1") for i in range(2)]
        when = NOW + timedelta(days=2)
        result = ov.apply_bulk(self.db, "t1", "reschedule", [r["id"] for r in rows], [], when, True, True, NOW)
        self.assertEqual(result["done"], 2)
        self.assertEqual({r["send_at"] for r in self.db.rows(TB)}, {when.isoformat()})

    def test_without_the_right_nothing_changes(self):
        row, bc = self.template(), self.broadcast()
        result = ov.apply_bulk(self.db, "t1", "cancel", [row["id"]], [bc["id"]], None, False, False, NOW)
        self.assertEqual(result["done"], 0)
        self.assertEqual(len(result["failed"]), 2)
        self.assertEqual((self.db.rows(TB)[0]["status"], self.db.rows(BC)[0]["status"]), ("scheduled", "pending"))

    def test_a_caller_sees_and_changes_only_their_assigned_leads(self):
        self.db.rows("leads")[0]["assigned_to"] = "c1"  # Arun is this caller's; Divya is not
        mine, theirs = self.template(lead="l0"), self.template(lead="l1")
        self.assertEqual([r["lead_id"] for r in ov.list_templates(self.db, "t1", NOW, caller_id="c1")], ["l0"])
        with patch.object(sched, "utcnow", return_value=NOW):
            result = ov.apply_bulk(self.db, "t1", "cancel", [mine["id"], theirs["id"]], [], None, True, True, NOW, caller_id="c1")
        self.assertEqual((result["done"], [f["id"] for f in result["failed"]]), (1, [theirs["id"]]))
        self.assertEqual(next(r for r in self.db.rows(TB) if r["id"] == theirs["id"])["status"], "scheduled")

    def test_reschedule_needs_a_time(self):
        with self.assertRaises(share.ShareError):
            ov.apply_bulk(self.db, "t1", "reschedule", [self.template()["id"]], [], None, True, True, NOW)


class FileLinkTests(_Base):
    def test_signed_link_with_the_original_name(self):
        row = self.broadcast()
        self.db.storage.from_.return_value.create_signed_url.return_value = {"signedURL": "https://x/signed"}
        link = ov.file_link(self.db, "t1", row["id"])
        self.assertEqual(link, {"url": "https://x/signed", "file_name": "leads.csv"})
        self.db.storage.from_.return_value.create_signed_url.assert_called_once_with("t1/ab_leads.csv", 300)

    def test_a_path_outside_the_tenant_is_never_signed(self):
        row = self.broadcast(csv_file_path="t2/secret.csv")
        with self.assertRaises(sched.NotFound):
            ov.file_link(self.db, "t1", row["id"])
        self.db.storage.from_.return_value.create_signed_url.assert_not_called()

    def test_a_path_that_climbs_out_of_the_tenant_folder_is_never_signed(self):
        row = self.broadcast(csv_file_path="t1/../t2/secret.csv")
        with self.assertRaises(sched.NotFound):
            ov.file_link(self.db, "t1", row["id"])
        self.db.storage.from_.return_value.create_signed_url.assert_not_called()

    def test_no_file_no_link(self):
        row = self.broadcast(csv_file_path=None)
        with self.assertRaises(sched.NotFound):
            ov.file_link(self.db, "t1", row["id"])


class BatchScheduleTests(unittest.TestCase):
    def test_batch_columns_are_written_only_when_given(self):
        db = FakeSupabase()
        db.add("leads", id="l0", tenant_id="t1", name="A", phone="+919800000000", opted_out=False)
        template = ({"id": "tpl", "name": "promo"}, ["x"], "Hi x")
        with patch.object(sched, "prepare_template", return_value=template), \
             patch.object(sched, "_whatsapp_ready", return_value=True):
            sched.schedule_template(db, "t1", "u1", "l0", "tpl", ["x"], NOW + timedelta(hours=2), now=NOW, batch_id="b1", batch_label=" Hot leads ")
            sched.schedule_template(db, "t1", "u1", "l0", "tpl", ["x"], NOW + timedelta(hours=3), now=NOW)
        first, second = db.rows(TB)
        self.assertEqual((first["batch_id"], first["batch_label"]), ("b1", "Hot leads"))
        self.assertNotIn("batch_id", second)


class RouteTests(_Base):
    def client(self, role="owner", permissions=()):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u-owner")
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t1", "role": role, "permissions": list(permissions), "user_id": "u-owner"}
        self.addCleanup(app.dependency_overrides.clear)
        patcher = patch("app.routes.scheduled_overview.get_supabase", return_value=self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(app)

    def test_owner_sees_both_lists(self):
        self.template()
        self.broadcast()
        body = self.client().get("/api/v1/scheduled-overview").json()
        self.assertEqual((len(body["templates"]), len(body["broadcasts"])), (1, 1))
        self.assertTrue(body["can_change_templates"] and body["can_change_broadcasts"])

    def test_a_caller_without_outbound_rights_sees_no_broadcasts(self):
        self.template()
        self.broadcast()
        body = self.client(role="member", permissions=["leads.manage"]).get("/api/v1/scheduled-overview").json()
        self.assertEqual((len(body["templates"]), body["broadcasts"]), (1, []))
        self.assertFalse(body["can_change_broadcasts"])

    def test_no_rights_no_page(self):
        res = self.client(role="member", permissions=["analytics.view"]).get("/api/v1/scheduled-overview")
        self.assertEqual(res.status_code, 403)

    def test_file_link_needs_outbound_view(self):
        row = self.broadcast()
        res = self.client(role="member", permissions=["leads.manage"]).get(f"/api/v1/scheduled-overview/broadcasts/{row['id']}/file")
        self.assertEqual(res.status_code, 403)

    def test_bulk_rejects_an_empty_pick_and_a_bad_action(self):
        client = self.client()
        self.assertEqual(client.post("/api/v1/scheduled-overview/bulk", json={"action": "cancel"}).status_code, 400)
        self.assertEqual(client.post("/api/v1/scheduled-overview/bulk", json={"action": "nuke", "template_ids": []}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
