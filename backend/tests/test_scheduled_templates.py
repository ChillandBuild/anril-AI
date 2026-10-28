"""Schedule a template: pick a time instead of sending a template straight away (migration 235)."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import lead_details_share as share_route
from app.routes import leads as leads_route
from app.services import call_details_share as share
from app.services import scheduled_templates as sched
from tests.test_call_details_share import NOW, _Base

TABLE = sched.TABLE
LEAD = "11111111-1111-1111-1111-111111111111"
PHONE = "+919800000009"


def at(**delta) -> datetime:
    return NOW + timedelta(**delta)


class _Sched(_Base):
    def setUp(self):
        super().setUp()
        self.db.add("leads", id=LEAD, tenant_id="t1", name="Asha Menon", phone=PHONE, opted_out=False, last_inbound_at=None)
        self.notify = MagicMock()
        for patcher in (
            patch.object(sched, "get_supabase", return_value=self.db),
            patch.object(sched, "utcnow", return_value=NOW),
            patch("app.services.notify.notify_user", self.notify),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def schedule(self, send_at=None, template_id="tpl-2", variables=("Asha", "see you soon"), lead_id=LEAD):
        return sched.schedule_template(self.db, "t1", "u1", lead_id, template_id, list(variables), send_at or at(hours=3), now=NOW)

    def row(self, schedule_id):
        return next(r for r in self.db.rows(TABLE) if r["id"] == schedule_id)

    def add_row(self, **fields):
        base = dict(tenant_id="t1", lead_id=LEAD, template_id="tpl-2", template_name="promo", variables=["Asha", "soon"],
                    content="Hi Asha soon", send_at=(NOW - timedelta(minutes=1)).isoformat(), status="scheduled",
                    created_by="u1")
        return self.db.add(TABLE, **{**base, **fields}) or self.db.rows(TABLE)[-1]


class ScheduleTests(_Sched):
    def test_stores_the_rendered_text_and_the_time_in_utc(self):
        ist = timezone(timedelta(hours=5, minutes=30))
        made = self.schedule(send_at=at(hours=3).astimezone(ist))
        stored = self.row(made["id"])
        self.assertEqual(stored["status"], "scheduled")
        self.assertEqual(stored["content"], "Hi Asha see you soon")
        self.assertEqual(stored["template_name"], "promo")
        self.assertEqual(stored["variables"], ["Asha", "see you soon"])
        self.assertEqual(stored["send_at"], at(hours=3).isoformat())
        self.assertEqual(stored["created_by"], "u1")
        self.send_template.assert_not_awaited()

    def test_time_must_be_between_five_minutes_and_thirty_days_ahead(self):
        for send_at, message in (
            (at(minutes=4), "Pick a time at least 5 minutes from now."),
            (at(minutes=-30), "Pick a time at least 5 minutes from now."),
            (at(days=31), "Scheduling goes up to 30 days ahead."),
            (datetime(2026, 9, 28, 10, 0), "Pick a date and time."),
        ):
            with self.subTest(send_at=send_at):
                with self.assertRaises(share.ShareError) as err:
                    self.schedule(send_at=send_at)
                self.assertEqual(str(err.exception), message)
        self.assertEqual(self.db.rows(TABLE), [])
        self.schedule(send_at=at(minutes=5))
        self.schedule(send_at=at(days=30))

    def test_refuses_what_could_never_be_sent(self):
        with self.assertRaises(share.ShareError):
            self.schedule(template_id="tpl-3")  # not approved
        with self.assertRaises(share.ShareError) as blank:
            self.schedule(variables=("Asha",))
        self.assertEqual(str(blank.exception), "Fill every blank in the template.")
        self.db.rows("leads")[-1]["opted_out"] = True
        with self.assertRaises(share.ShareError):
            self.schedule()
        with self.assertRaises(sched.NotFound):
            self.schedule(lead_id="22222222-2222-2222-2222-222222222222")
        self.assertEqual(self.db.rows(TABLE), [])

    def test_a_lead_holds_at_most_ten_waiting_messages(self):
        for i in range(10):
            self.schedule(send_at=at(hours=3, minutes=i))
        with self.assertRaises(share.ShareError) as err:
            self.schedule()
        self.assertIn("10 messages", str(err.exception))


class ListTests(_Sched):
    def test_shows_waiting_messages_and_recent_problems_only(self):
        waiting = self.schedule(send_at=at(hours=2))["id"]
        self.add_row(id="recent-fail", status="failed", reason="Template not approved", send_at=at(hours=-5).isoformat())
        self.add_row(id="old-fail", status="failed", send_at=at(days=-3).isoformat())
        self.add_row(id="done", status="sent", send_at=at(hours=-6).isoformat())
        self.add_row(id="gone", status="cancelled", send_at=at(hours=6).isoformat())
        self.add_row(id="elsewhere", tenant_id="t2", send_at=at(hours=1).isoformat())
        ids = [r["id"] for r in sched.list_for_lead(self.db, "t1", LEAD, now=NOW)]
        self.assertEqual(ids, ["recent-fail", waiting])

    def test_a_pile_of_old_failures_never_hides_a_waiting_message(self):
        for i in range(60):
            self.add_row(id=f"old-{i}", status="failed", send_at=at(days=-10, minutes=i).isoformat())
        waiting = self.schedule(send_at=at(hours=2))["id"]
        self.assertEqual([r["id"] for r in sched.list_for_lead(self.db, "t1", LEAD, now=NOW)], [waiting])


class CancelRestoreRescheduleTests(_Sched):
    def test_cancel_then_undo(self):
        made = self.schedule()["id"]
        self.assertEqual(sched.cancel(self.db, "t1", made, now=NOW)["status"], "cancelled")
        self.assertEqual(self.row(made)["status"], "cancelled")
        self.assertEqual(sched.restore(self.db, "t1", made, now=NOW)["status"], "scheduled")
        self.assertIsNone(self.row(made)["cancelled_at"])

    def test_undo_is_refused_once_the_send_time_has_passed(self):
        made = self.add_row(status="cancelled", send_at=(NOW - timedelta(seconds=5)).isoformat())["id"]
        with self.assertRaises(share.ShareError) as err:
            sched.restore(self.db, "t1", made, now=NOW)
        self.assertEqual(str(err.exception), "Too late to undo: its send time has passed.")

    def test_cannot_cancel_what_is_already_out_or_gone(self):
        sent = self.add_row(status="sent")["id"]
        sending = self.add_row(status="sending")["id"]
        cancelled = self.add_row(status="cancelled")["id"]
        for sid, message in ((sent, "It has already been sent."), (sending, "It is being sent right now."),
                             (cancelled, "It was already cancelled.")):
            with self.subTest(sid=sid), self.assertRaises(share.ShareError) as err:
                sched.cancel(self.db, "t1", sid, now=NOW)
            self.assertEqual(str(err.exception), message)
        with self.assertRaises(sched.NotFound):
            sched.cancel(self.db, "t1", "nope", now=NOW)

    def test_another_tenant_cannot_touch_it(self):
        made = self.schedule()["id"]
        with self.assertRaises(sched.NotFound):
            sched.cancel(self.db, "t2", made, now=NOW)
        with self.assertRaises(sched.NotFound):
            sched.reschedule(self.db, "t2", made, at(hours=5), now=NOW)
        self.assertEqual(self.row(made)["status"], "scheduled")

    def test_change_time_validates_and_keeps_the_rest(self):
        made = self.schedule()["id"]
        sched.reschedule(self.db, "t1", made, at(hours=9), now=NOW)
        self.assertEqual(self.row(made)["send_at"], at(hours=9).isoformat())
        self.assertEqual(self.row(made)["status"], "scheduled")
        with self.assertRaises(share.ShareError):
            sched.reschedule(self.db, "t1", made, at(minutes=1), now=NOW)
        self.assertEqual(self.row(made)["send_at"], at(hours=9).isoformat())


class SendDueTests(_Sched):
    async def test_sends_what_is_due_and_logs_it_in_the_chat(self):
        due = self.add_row(id="due", variables=["Asha", "soon"])["id"]
        later = self.add_row(id="later", send_at=at(hours=2).isoformat())["id"]
        cancelled = self.add_row(id="cancelled", status="cancelled")["id"]
        self.assertEqual(await sched.process_due(), 1)
        self.assertEqual(self.send_template.await_args.args, (PHONE, "promo", "en"))
        self.assertEqual(self.row(due)["status"], "sent")
        self.assertIsNotNone(self.row(due)["sent_at"])
        self.assertEqual(self.row(later)["status"], "scheduled")
        self.assertEqual(self.row(cancelled)["status"], "cancelled")
        chat = self.db.rows("messages")
        self.assertEqual([(m["lead_id"], m["content"], m["meta_message_id"], m["direction"]) for m in chat],
                         [(LEAD, "Hi Asha soon", "wamid.2", "outbound")])

    async def test_a_row_is_never_sent_twice(self):
        row = self.add_row(id="once")
        self.assertTrue(await sched.send_one(self.db, dict(row)))
        self.assertFalse(await sched.send_one(self.db, dict(row)))
        self.assertEqual(self.send_template.await_count, 1)
        self.assertEqual(len(self.db.rows("messages")), 1)

    async def test_a_customer_who_opted_out_in_the_meantime_is_skipped(self):
        self.db.rows("leads")[-1]["opted_out"] = True
        made = self.add_row(id="optout")["id"]
        self.assertEqual(await sched.process_due(), 0)
        self.assertEqual((self.row(made)["status"], self.row(made)["reason"]), ("skipped", "The customer opted out."))
        self.send_template.assert_not_awaited()
        self.notify.assert_not_called()

    async def test_a_removed_lead_is_skipped(self):
        made = self.add_row(id="gone", lead_id="33333333-3333-3333-3333-333333333333")["id"]
        await sched.process_due()
        self.assertEqual((self.row(made)["status"], self.row(made)["reason"]), ("skipped", "The lead was removed."))

    async def test_a_template_that_is_no_longer_approved_fails_and_tells_who_scheduled_it(self):
        made = self.add_row(id="stale", template_id="tpl-3", template_name="pending_one", variables=[])["id"]
        self.assertEqual(await sched.process_due(), 0)
        self.assertEqual(self.row(made)["status"], "failed")
        self.assertEqual(self.row(made)["reason"], "That template isn't approved for this WhatsApp number.")
        args = self.notify.call_args
        self.assertEqual(args.args[:3], ("t1", "u1", "scheduled_template_failed"))
        self.assertIn("Asha Menon", args.args[4])
        self.assertEqual(self.db.rows("messages"), [])

    async def test_whatsapp_refusing_the_send_fails_it_in_plain_words(self):
        self.send_template.side_effect = HTTPException(status_code=502, detail='{"error": {"code": 131026, "message": "x"}}')
        made = self.add_row(id="refused")["id"]
        await sched.process_due()
        self.assertEqual(self.row(made)["status"], "failed")
        self.assertEqual(self.row(made)["reason"], "WhatsApp couldn't deliver to this number. Check that it is on WhatsApp.")
        self.notify.assert_called_once()
        self.assertEqual(self.db.rows("messages"), [])

    async def test_a_row_stuck_sending_is_failed_not_resent(self):
        stuck = self.add_row(id="stuck", status="sending", claimed_at=(NOW - timedelta(minutes=20)).isoformat())["id"]
        fresh = self.add_row(id="fresh", status="sending", claimed_at=(NOW - timedelta(minutes=2)).isoformat())["id"]
        await sched.process_due()
        self.assertEqual(self.row(stuck)["status"], "failed")
        self.assertEqual(self.row(stuck)["reason"], sched.INTERRUPTED)
        self.assertEqual(self.row(fresh)["status"], "sending")
        self.send_template.assert_not_awaited()
        # nobody can tell whether the customer got it, so whoever scheduled it is told to look
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.args[:3], ("t1", "u1", "scheduled_template_failed"))
        self.assertIn(sched.INTERRUPTED, self.notify.call_args.args[4])


class RouteTests(_Sched):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.ctx = {"tenant_id": "t1", "role": "caller", "user_id": "u1", "permissions": ["conversations.reply"]}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        for module in (share_route, leads_route):
            patcher = patch.object(module, "get_supabase", return_value=self.db)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def body(self, **over):
        return {"template_id": "tpl-2", "variables": ["Asha", "see you soon"], "send_at": at(hours=3).isoformat(), **over}

    def test_schedule_list_cancel_undo_and_change_time(self):
        url = f"/api/v1/leads/{LEAD}/scheduled-templates"
        made = self.client.post(url, json=self.body())
        self.assertEqual(made.status_code, 200, made.text)
        sid = made.json()["id"]
        self.assertEqual(self.client.get(url).json()["items"][0]["content"], "Hi Asha see you soon")
        moved = self.client.patch(f"/api/v1/leads/scheduled-templates/{sid}", json={"send_at": at(hours=6).isoformat()})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(self.client.post(f"/api/v1/leads/scheduled-templates/{sid}/cancel").json()["status"], "cancelled")
        self.assertEqual(self.client.get(url).json()["items"], [])
        self.assertEqual(self.client.post(f"/api/v1/leads/scheduled-templates/{sid}/restore").json()["status"], "scheduled")
        again = self.client.post(f"/api/v1/leads/scheduled-templates/{sid}/cancel")
        self.assertEqual(again.status_code, 200)
        twice = self.client.post(f"/api/v1/leads/scheduled-templates/{sid}/cancel")
        self.assertEqual((twice.status_code, twice.json()["detail"]), (400, "It was already cancelled."))

    def test_problems_come_back_as_400_and_404(self):
        url = f"/api/v1/leads/{LEAD}/scheduled-templates"
        soon = self.client.post(url, json=self.body(send_at=at(minutes=1).isoformat()))
        self.assertEqual((soon.status_code, soon.json()["detail"]), (400, "Pick a time at least 5 minutes from now."))
        naive = self.client.post(url, json=self.body(send_at="2026-09-28T10:00:00"))
        self.assertEqual((naive.status_code, naive.json()["detail"]), (400, "Pick a date and time."))
        unknown = self.client.post("/api/v1/leads/22222222-2222-2222-2222-222222222222/scheduled-templates", json=self.body())
        self.assertEqual(unknown.status_code, 404)
        missing = self.client.post("/api/v1/leads/scheduled-templates/44444444-4444-4444-4444-444444444444/cancel")
        self.assertEqual(missing.status_code, 404)

    def test_needs_the_same_right_as_sending(self):
        self.ctx["permissions"] = ["leads.view"]
        url = f"/api/v1/leads/{LEAD}/scheduled-templates"
        self.assertEqual(self.client.post(url, json=self.body()).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/leads/scheduled-templates/44444444-4444-4444-4444-444444444444/cancel").status_code, 403)

    def test_new_message_form_schedules_to_a_new_number_and_creates_the_lead(self):
        self.ctx["permissions"] = ["leads.manage"]
        res = self.client.post("/api/v1/leads/compose/schedule", json={
            "phone": "+91 98111 12222", "name": "Ravi", **self.body(variables=["Ravi", "see you soon"]),
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["phone"], "+919811112222")
        lead = next(r for r in self.db.rows("leads") if r["phone"] == "+919811112222")
        self.assertEqual(lead["name"], "Ravi")
        stored = self.db.rows(TABLE)[-1]
        self.assertEqual((stored["lead_id"], stored["content"], stored["status"]), (lead["id"], "Hi Ravi see you soon", "scheduled"))
        self.send_template.assert_not_awaited()

    def test_new_message_form_reuses_an_existing_lead(self):
        self.ctx["permissions"] = ["leads.manage"]
        before = len(self.db.rows("leads"))
        res = self.client.post("/api/v1/leads/compose/schedule", json={"phone": PHONE, **self.body()})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(self.db.rows("leads")), before)
        self.assertEqual(self.db.rows(TABLE)[-1]["lead_id"], LEAD)

    def test_new_message_form_leaves_no_lead_behind_when_the_request_is_bad(self):
        self.ctx["permissions"] = ["leads.manage"]
        before = len(self.db.rows("leads"))
        for over in ({"send_at": at(minutes=1).isoformat()}, {"variables": ["only one"]}, {"template_id": "tpl-3"}):
            with self.subTest(over=over):
                res = self.client.post("/api/v1/leads/compose/schedule", json={"phone": "+919822223333", **self.body(**over)})
                self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(len(self.db.rows("leads")), before)
        self.assertEqual(self.db.rows(TABLE), [])

    def test_new_message_form_leaves_no_lead_behind_when_whatsapp_is_not_connected(self):
        self.ctx["permissions"] = ["leads.manage"]
        self.settings.pop("meta_access_token")
        before = len(self.db.rows("leads"))
        res = self.client.post("/api/v1/leads/compose/schedule", json={"phone": "+919833334444", **self.body()})
        self.assertEqual((res.status_code, res.json()["detail"]), (400, "WhatsApp isn't connected. Connect it in Settings first."))
        self.assertEqual(len(self.db.rows("leads")), before)
        self.assertEqual(self.db.rows(TABLE), [])

    def test_new_message_form_needs_leads_manage(self):
        self.ctx["permissions"] = ["conversations.reply"]
        res = self.client.post("/api/v1/leads/compose/schedule", json={"phone": PHONE, **self.body()})
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
