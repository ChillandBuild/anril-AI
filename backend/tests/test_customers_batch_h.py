"""Batch H, Customers backend: list filters (only / came_from / tag), tags on rows, Send to calling,
the customer page's new events, Said stop with Don't call, and follow-ups aimed at a group.
In-memory fake database; tenant-1 is the caller's, tenant-2 must never be reached."""
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
from tests.fake_supabase import FakeSupabase


def U(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "anril-batch-h:" + name))


NOW = datetime.now(timezone.utc)
ago = lambda days: (NOW - timedelta(days=days)).isoformat()
OWNER = {"tenant_id": "tenant-1", "role": "owner", "user_id": "user-1", "permissions": []}
VIEWER = {"tenant_id": "tenant-1", "role": "member", "user_id": "user-2", "permissions": ["leads.view"]}


def _lead(db, name, tenant_id="tenant-1", **extra):
    row = {"id": U(name), "tenant_id": tenant_id, "name": name, "phone": "+9198765" + str(abs(hash(name)) % 100000).zfill(5),
           "created_at": ago(30), "deleted_at": None, "opted_out": None, "whatsapp_undeliverable": None,
           "segment": "C", "source": "whatsapp"}
    row.update(extra)
    db.rows("leads").append(row)
    return row


class _Base(unittest.TestCase):
    modules = ("leads", "customer_groups", "said_stop", "customer_profile", "reengagement", "lead_tags")

    def setUp(self):
        self.db = FakeSupabase()
        self.patches = [patch(f"app.routes.{m}.get_supabase", return_value=self.db) for m in self.modules]
        self.patches.append(patch("app.routes.said_stop.actor_name", return_value="Meena"))
        for p in self.patches:
            p.start()
        self.ctx = OWNER
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        app.dependency_overrides[get_current_user] = lambda: {"user_id": self.ctx["user_id"]}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in self.patches:
            p.stop()

    def names(self, query: str) -> list[str]:
        res = self.client.get("/api/v1/leads/?" + query)
        self.assertEqual(res.status_code, 200, res.text)
        return sorted(r["name"] for r in res.json()["data"])


class ListFilterTests(_Base):
    def setUp(self):
        super().setUp()
        _lead(self.db, "never")
        _lead(self.db, "paid", converted_at=ago(5))
        _lead(self.db, "won")
        self.db.rows("deals").append({"id": "d1", "tenant_id": "tenant-1", "lead_id": U("won"), "stage": "won",
                                      "total_paise": 100, "won_at": ago(3)})
        _lead(self.db, "lost")
        self.db.rows("deals").append({"id": "d2", "tenant_id": "tenant-1", "lead_id": U("lost"), "stage": "lost"})
        _lead(self.db, "scanner", qr_link_id=U("qr1"), source="qr")
        _lead(self.db, "form", source="meta_form")
        _lead(self.db, "upl", source="upload")
        _lead(self.db, "gads", ad_campaign_id=U("gc"))
        _lead(self.db, "mads", ad_campaign_id=U("mc"))
        self.db.rows("ad_campaigns").append({"id": U("gc"), "tenant_id": "tenant-1", "platform": "google"})
        self.db.rows("ad_campaigns").append({"id": U("mc"), "tenant_id": "tenant-1", "platform": "facebook"})
        _lead(self.db, "other", tenant_id="tenant-2")

    def test_only_leads_is_people_who_never_bought(self):
        got = self.names("only=leads&limit=200")
        self.assertNotIn("paid", got)
        self.assertNotIn("won", got)
        self.assertIn("never", got)
        self.assertIn("lost", got)  # a lost deal is not a purchase
        self.assertNotIn("other", got)

    def test_only_rejects_other_values(self):
        self.assertEqual(self.client.get("/api/v1/leads/?only=buyers").status_code, 422)

    def test_came_from_choices(self):
        self.assertEqual(self.names("came_from=qr"), ["scanner"])
        self.assertEqual(self.names("came_from=instant_form"), ["form"])
        self.assertEqual(self.names("came_from=upload"), ["upl"])
        self.assertEqual(self.names("came_from=google_ads"), ["gads"])
        self.assertEqual(self.names("came_from=meta_ad"), ["mads"])

    def test_google_ads_with_no_google_campaigns_matches_nobody(self):
        self.db.tables["ad_campaigns"] = []
        self.assertEqual(self.names("came_from=google_ads"), [])

    def test_came_from_unknown_is_a_plain_400(self):
        res = self.client.get("/api/v1/leads/?came_from=moon")
        self.assertEqual(res.status_code, 400)
        self.assertIn("came from", res.json()["detail"])

    def test_came_from_works_with_the_existing_filters(self):
        self.assertEqual(self.names("came_from=upload&segment=C"), ["upl"])
        self.assertEqual(self.names("came_from=upload&segment=A"), [])
        self.assertEqual(self.names("came_from=upload&only=leads"), ["upl"])

    def test_tag_filter_ignores_case_and_tenant_and_rows_carry_tags(self):
        self.db.add("lead_tags", tenant_id="tenant-1", lead_id=U("never"), tag="VIP")
        self.db.add("lead_tags", tenant_id="tenant-1", lead_id=U("never"), tag="Bridal")
        self.db.add("lead_tags", tenant_id="tenant-2", lead_id=U("other"), tag="VIP")
        self.assertEqual(self.names("tag=vip"), ["never"])
        self.assertEqual(self.names("tag=nothing"), [])
        rows = self.client.get("/api/v1/leads/?limit=200").json()["data"]
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(sorted(by_name["never"]["tags"]), ["Bridal", "VIP"])
        self.assertEqual(by_name["paid"]["tags"], [])

    def test_existing_filters_still_work(self):
        self.assertIn("paid", self.names("buyer=true&limit=200"))
        self.assertNotIn("never", self.names("buyer=true&limit=200"))
        self.assertEqual(self.names("segment=A"), [])


class SendToCallingTests(_Base):
    RESULT = {"added": 2, "already": 1, "said_stop": 0, "bought": 0, "closed": 0, "not_found": 0,
              "no_callers": False, "added_ids": ["x", "y"]}

    def test_bulk_passes_the_tenant_ids_and_reason(self):
        _lead(self.db, "a")
        with patch("app.services.customer_calling.send_to_calling", return_value=dict(self.RESULT)) as m:
            res = self.client.post("/api/v1/leads/send-to-calling", json={"lead_ids": [U("a")]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["added"], 2)
        args, kwargs = m.call_args
        self.assertEqual(args[1:], ("tenant-1", [U("a")]))
        self.assertEqual(kwargs, {"reason": "customers_bulk"})

    def test_bulk_needs_manage_and_a_list(self):
        self.ctx = VIEWER
        self.assertEqual(self.client.post("/api/v1/leads/send-to-calling", json={"lead_ids": [U("a")]}).status_code, 403)
        self.ctx = OWNER
        self.assertEqual(self.client.post("/api/v1/leads/send-to-calling", json={"lead_ids": []}).status_code, 422)

    def _group(self, kind="picked", **kw):
        self.db.rows("customer_groups").append({"id": U("g"), "tenant_id": "tenant-1", "name": "VIP", "kind": kind, **kw})

    def test_group_sends_its_members_and_adds_the_said_stop_ones(self):
        self._group()
        _lead(self.db, "m1", phone="+919876500001")
        _lead(self.db, "m2", phone="+919876500002")
        _lead(self.db, "stop", phone="+919876500003", opted_out=True)
        _lead(self.db, "nonmember", phone="+919876500004")
        for n in ("m1", "m2", "stop"):
            self.db.rows("customer_group_members").append({"group_id": U("g"), "lead_id": U(n), "tenant_id": "tenant-1"})
        with patch("app.services.customer_calling.send_to_calling", return_value=dict(self.RESULT)) as m:
            res = self.client.post(f"/api/v1/customer-groups/{U('g')}/send-to-calling")
        self.assertEqual(res.status_code, 200, res.text)
        # A picked group hands every member to send_to_calling, which counts the said-stop one itself.
        self.assertEqual(sorted(m.call_args[0][2]), sorted([U("m1"), U("m2"), U("stop")]))
        self.assertEqual(m.call_args[1], {"reason": "group", "group_id": U("g")})

    def test_group_members_with_no_whatsapp_still_go_to_calling(self):
        self._group()
        _lead(self.db, "wa", phone="+919876500001")
        _lead(self.db, "insta", phone=None, source="instagram")
        _lead(self.db, "bounced", phone="+919876500006", whatsapp_undeliverable=True)
        for n in ("wa", "insta", "bounced"):
            self.db.rows("customer_group_members").append({"group_id": U("g"), "lead_id": U(n), "tenant_id": "tenant-1"})
        with patch("app.services.customer_calling.send_to_calling", return_value=dict(self.RESULT)) as m:
            res = self.client.post(f"/api/v1/customer-groups/{U('g')}/send-to-calling")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(sorted(m.call_args[0][2]), sorted([U("wa"), U("insta"), U("bounced")]))

    def test_group_of_another_tenant_is_404_and_viewer_is_403(self):
        self.db.rows("customer_groups").append({"id": U("g2"), "tenant_id": "tenant-2", "name": "X", "kind": "picked"})
        self.assertEqual(self.client.post(f"/api/v1/customer-groups/{U('g2')}/send-to-calling").status_code, 404)
        self.ctx = VIEWER
        self.assertEqual(self.client.post(f"/api/v1/customer-groups/{U('g2')}/send-to-calling").status_code, 403)


class ProfileTests(_Base):
    def setUp(self):
        super().setUp()
        _lead(self.db, "priya")
        deal = {"id": "d1", "tenant_id": "tenant-1", "lead_id": U("priya"), "stage": "won", "total_paise": 500000,
                "won_at": ago(10), "created_at": ago(10), "deal_number": 7}
        self.db.rows("deals").append(deal)
        self.db.rows("deal_refunds").append({"id": "r1", "tenant_id": "tenant-1", "deal_id": "d1", "amount_paise": 50000,
                                             "method": "upi", "reason": "size", "status": "done", "created_at": ago(8),
                                             "created_by": "user-9"})
        self.db.rows("tenant_users").append({"tenant_id": "tenant-1", "user_id": "user-9", "full_name": "Meena"})
        self.db.rows("deal_refunds").append({"id": "r2", "tenant_id": "tenant-1", "deal_id": "d1", "amount_paise": 99,
                                             "method": "cash", "status": "failed", "created_at": ago(7)})
        self.db.rows("booking_services").append({"id": "s1", "tenant_id": "tenant-1", "name": "Haircut"})
        self.db.rows("booking_resources").append({"id": "p1", "tenant_id": "tenant-1", "name": "Ravi"})
        for i, (status, extra) in enumerate([("came", {"came_at": ago(20)}), ("no_show", {}),
                                             ("cancelled", {"cancelled_at": ago(4)}), ("booked", {})]):
            self.db.rows("bookings").append({"id": f"b{i}", "tenant_id": "tenant-1", "lead_id": U("priya"),
                                             "service_id": "s1", "resource_id": "p1", "start_at": ago(20 - i),
                                             "status": status, **extra})
        self.db.rows("customer_feedback").append({"id": "f1", "tenant_id": "tenant-1", "lead_id": U("priya"), "kind": "order",
                                                  "stars": 4, "reason": None, "staff_name": "Ravi", "asked_at": ago(6),
                                                  "answered_at": ago(5)})
        self.db.rows("customer_feedback").append({"id": "f2", "tenant_id": "tenant-1", "lead_id": U("priya"), "kind": "booking",
                                                  "stars": 2, "reason": "waited long", "asked_at": ago(3),
                                                  "answered_at": ago(2)})
        self.db.rows("customer_feedback").append({"id": "f3", "tenant_id": "tenant-1", "lead_id": U("priya"), "kind": "booking",
                                                  "stars": None, "asked_at": ago(1)})  # asked, not answered
        self.db.add("lead_tags", tenant_id="tenant-1", lead_id=U("priya"), tag="VIP")

    def get(self):
        res = self.client.get(f"/api/v1/customer-profile/{U('priya')}")
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_new_events_and_totals(self):
        body = self.get()
        kinds = [e["kind"] for e in body["timeline"]]
        self.assertEqual(kinds.count("refund"), 1)      # the failed one is not shown
        self.assertEqual(kinds.count("visit"), 1)
        self.assertEqual(kinds.count("no_show"), 1)
        self.assertEqual(kinds.count("booking"), 2)     # cancelled + booked
        self.assertEqual(kinds.count("feedback"), 2)    # only answered ones
        refund = next(e for e in body["timeline"] if e["kind"] == "refund")
        self.assertEqual((refund["amount_paise"], refund["method"], refund["number"], refund["by"]), (50000, "upi", 7, "Meena"))
        booked = next(e for e in body["timeline"] if e["kind"] == "booking" and e["status"] == "booked")
        self.assertEqual((booked["service"], booked["staff"]), ("Haircut", "Ravi"))
        self.assertTrue(booked["time"])
        visit = next(e for e in body["timeline"] if e["kind"] == "visit")
        self.assertEqual((visit["service"], visit["staff"], visit["status"]), ("Haircut", "Ravi", "came"))
        fb = next(e for e in body["timeline"] if e["kind"] == "feedback" and e["stars"] == 2)
        self.assertEqual(fb["reason"], "waited long")
        totals = body["totals"]
        self.assertEqual((totals["refunds_paise"], totals["visits"], totals["no_shows"], totals["avg_stars"]), (50000, 1, 1, 3.0))
        self.assertEqual(body["tags"], ["VIP"])
        self.assertEqual(body["lead"]["tags"], ["VIP"])

    def test_old_shapes_unchanged(self):
        body = self.get()
        for key in ("spent_paise", "orders_won", "average_paise", "last_bought_at", "to_pay_paise", "orders_waiting"):
            self.assertIn(key, body["totals"])
        order = next(e for e in body["timeline"] if e["kind"] == "order")
        self.assertEqual(order["number"], 7)

    def test_lead_level_booking_mark_shows_when_there_are_no_booking_rows(self):
        self.db.tables["bookings"] = []
        next(r for r in self.db.rows("leads") if r["name"] == "priya")["booked_at"] = ago(2)
        body = self.get()
        self.assertEqual([e["kind"] for e in body["timeline"]].count("booking"), 1)
        self.assertEqual(body["totals"]["visits"], 0)

    def test_missing_tables_are_skipped_not_fatal(self):
        real = self.db.table
        missing = {"deal_refunds", "bookings", "customer_feedback", "lead_tags"}

        def table(name):
            if name in missing:
                raise RuntimeError(f'relation "{name}" does not exist')
            return real(name)

        with patch.object(self.db, "table", side_effect=table):
            body = self.get()
        self.assertEqual(body["tags"], [])
        self.assertEqual((body["totals"]["refunds_paise"], body["totals"]["visits"], body["totals"]["avg_stars"]), (0, 0, None))
        kinds = {e["kind"] for e in body["timeline"]}
        self.assertFalse(kinds & {"refund", "visit", "no_show", "feedback"})

    def test_other_tenants_rows_are_not_shown(self):
        self.db.rows("customer_feedback").append({"id": "fx", "tenant_id": "tenant-2", "lead_id": U("priya"), "kind": "order",
                                                  "stars": 1, "answered_at": ago(1), "asked_at": ago(1)})
        self.assertEqual(self.get()["totals"]["avg_stars"], 3.0)


class SaidStopDoNotCallTests(_Base):
    def setUp(self):
        super().setUp()
        _lead(self.db, "stopper", opted_out=True, opted_out_at=ago(2), opted_out_source="stop_reply")
        _lead(self.db, "dncman", do_not_call=True)
        _lead(self.db, "both", opted_out=True, do_not_call=True, opted_out_at=ago(3), opted_out_source="call")
        _lead(self.db, "fine")
        _lead(self.db, "otherdnc", tenant_id="tenant-2", do_not_call=True)

    def test_list_includes_dont_call_people_once_with_their_label(self):
        body = self.client.get("/api/v1/said-stop").json()
        people = {p["name"]: p for p in body["people"]}
        self.assertEqual(sorted(people), ["both", "dncman", "stopper"])
        self.assertEqual(people["dncman"]["source"], "do_not_call")
        self.assertEqual(people["dncman"]["source_label"], "Don't call (from a call)")
        self.assertTrue(people["dncman"]["do_not_call"])
        self.assertEqual(people["both"]["source"], "call")        # a real stop keeps its own reason
        self.assertIsNone(people["both"]["source_label"])
        self.assertEqual(people["stopper"]["source"], "stop_reply")
        self.assertEqual(body["summary"]["on_list"], 3)

    def test_remove_clears_do_not_call_only_for_dont_call_people_and_only_for_this_tenant(self):
        res = self.client.post("/api/v1/said-stop/remove",
                               json={"lead_ids": [U("dncman"), U("both"), U("stopper"), U("fine"), U("otherdnc")]})
        self.assertEqual(res.json()["removed"], 3)
        rows = {r["name"]: r for r in self.db.rows("leads")}
        self.assertFalse(rows["dncman"]["do_not_call"])
        # Said stop AND "Don't call": the stop comes off, the caller's "Don't call" mark stays (separate flags).
        self.assertFalse(rows["both"]["opted_out"])
        self.assertTrue(rows["both"]["do_not_call"])
        self.assertTrue(rows["otherdnc"]["do_not_call"])
        people = self.client.get("/api/v1/said-stop").json()["people"]
        self.assertEqual([(p["name"], p["source"]) for p in people], [("both", "do_not_call")])
        # A second remove takes the "Don't call" mark off too.
        self.assertEqual(self.client.post("/api/v1/said-stop/remove", json={"lead_ids": [U("both")]}).json()["removed"], 1)
        self.assertFalse({r["name"]: r for r in self.db.rows("leads")}["both"]["do_not_call"])

    def test_blocking_rules_unchanged(self):
        from app.services import said_stop
        self.assertTrue(said_stop.blocks_calls({"do_not_call": True}))
        self.assertTrue(said_stop.blocks_calls({"opted_out": True}))
        self.assertFalse(said_stop.blocks_calls({}))

    def test_viewer_cannot_remove(self):
        self.ctx = VIEWER
        self.assertEqual(self.client.post("/api/v1/said-stop/remove", json={"lead_ids": [U("dncman")]}).status_code, 403)


class FollowUpGroupRouteTests(_Base):
    def setUp(self):
        super().setUp()
        self.db.rows("customer_groups").append({"id": U("g"), "tenant_id": "tenant-1", "name": "VIP", "kind": "picked"})
        self.db.rows("customer_groups").append({"id": U("gx"), "tenant_id": "tenant-2", "name": "Theirs", "kind": "picked"})

    def body(self, **kw):
        return {"type": "inbound", "delay_hours": 2, "target_segments": ["Hot"], "message_type": "freeform",
                "message_content": "hi", **kw}

    def test_create_with_own_group_saves_it(self):
        res = self.client.post("/api/v1/reengagement/steps", json=self.body(target_group_id=U("g")))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.db.rows("reengagement_steps")[0]["target_group_id"], U("g"))

    def test_create_with_another_tenants_or_junk_group_is_400(self):
        for gid in (U("gx"), "not-a-uuid", U("nobody")):
            res = self.client.post("/api/v1/reengagement/steps", json=self.body(target_group_id=gid))
            self.assertEqual(res.status_code, 400, gid)
            self.assertEqual(res.json()["detail"], "Pick one of your own groups")
        self.assertEqual(self.db.rows("reengagement_steps"), [])

    def test_create_without_group_does_not_send_the_column(self):
        self.client.post("/api/v1/reengagement/steps", json=self.body())
        self.assertNotIn("target_group_id", self.db.rows("reengagement_steps")[0])

    def _step(self):
        return self.db.add("reengagement_steps", tenant_id="tenant-1", type="inbound", delay_hours=2,
                           target_segments=["Hot"], message_type="freeform", message_content="hi", target_group_id=U("g"))

    def test_update_keeps_group_when_left_out_changes_it_and_clears_on_null(self):
        step = self._step()
        url = f"/api/v1/reengagement/steps/{step['id']}"
        base = {k: v for k, v in self.body().items() if k != "type"}
        self.assertEqual(self.client.patch(url, json=base).status_code, 200)
        self.assertEqual(self.db.rows("reengagement_steps")[0]["target_group_id"], U("g"))
        self.assertEqual(self.client.patch(url, json={**base, "target_group_id": U("gx")}).status_code, 400)
        self.assertEqual(self.db.rows("reengagement_steps")[0]["target_group_id"], U("g"))
        self.assertEqual(self.client.patch(url, json={**base, "target_group_id": None}).status_code, 200)
        self.assertIsNone(self.db.rows("reengagement_steps")[0]["target_group_id"])

    def test_missing_column_group_is_a_plain_400_and_null_still_saves(self):
        step = self.db.add("reengagement_steps", tenant_id="tenant-1", type="inbound", delay_hours=2,
                           target_segments=["Hot"], message_type="freeform", message_content="hi")
        real = self.db.table

        def table(name):
            q = real(name)
            if name == "reengagement_steps":
                for op in ("insert", "update"):
                    orig = getattr(q, op)

                    def wrapped(payload, orig=orig):
                        if "target_group_id" in payload:
                            raise Exception("column reengagement_steps.target_group_id does not exist")
                        return orig(payload)
                    setattr(q, op, wrapped)
            return q

        base = {k: v for k, v in self.body().items() if k != "type"}
        with patch.object(self.db, "table", side_effect=table):
            res = self.client.post("/api/v1/reengagement/steps", json=self.body(target_group_id=U("g")))
            self.assertEqual(res.status_code, 400)
            self.assertIn("not switched on", res.json()["detail"])
            ok = self.client.patch(f"/api/v1/reengagement/steps/{step['id']}", json={**base, "target_group_id": None})
            self.assertEqual(ok.status_code, 200, ok.text)

    def test_group_in_use_by_a_follow_up_cannot_be_deleted(self):
        self._step()
        res = self.client.delete(f"/api/v1/customer-groups/{U('g')}")
        self.assertEqual(res.status_code, 409)
        self.assertIn("auto-message", res.json()["detail"])
        self.assertEqual(len(self.db.rows("customer_groups")), 2)
        self.db.tables["reengagement_steps"] = []
        self.assertEqual(self.client.delete(f"/api/v1/customer-groups/{U('g')}").status_code, 200)


class FollowUpGroupRunTests(unittest.IsolatedAsyncioTestCase):
    """process_due_reengagements: a step with a group only reaches members of that group."""

    def setUp(self):
        self.db = FakeSupabase()
        for n, seg in (("in1", "Hot"), ("in2", "Hot"), ("out", "Hot"), ("coldmember", "Cold")):
            _lead(self.db, n, segment=seg, last_inbound_at=ago(3), phone="+9198765" + str(len(n)) + "0001")
        self.db.rows("customer_groups").append({"id": U("g"), "tenant_id": "tenant-1", "name": "VIP", "kind": "picked"})
        for n in ("in1", "in2", "coldmember"):
            self.db.rows("customer_group_members").append({"group_id": U("g"), "lead_id": U(n), "tenant_id": "tenant-1"})

    def step(self, **kw):
        row = {"tenant_id": "tenant-1", "type": "inbound", "delay_hours": 2, "target_segments": ["Hot"],
               "message_type": "freeform", "message_content": "hi", **kw}
        return self.db.add("reengagement_steps", **row)

    async def run_it(self):
        from app.services import reengagement_service as svc
        send = AsyncMock(return_value=True)
        with patch.object(svc, "get_supabase", return_value=self.db), patch.object(svc, "_send_reengagement", new=send):
            count = await svc.process_due_reengagements()
        return count, sorted(c.args[2]["name"] for c in send.await_args_list)

    async def test_without_group_everyone_matching_gets_it_as_before(self):
        self.step()
        count, names = await self.run_it()
        self.assertEqual(names, ["in1", "in2", "out"])

    async def test_picked_group_limits_the_step(self):
        self.step(target_group_id=U("g"))
        count, names = await self.run_it()
        self.assertEqual(names, ["in1", "in2"])  # not "out" (not a member), not coldmember (wrong segment)

    async def test_rule_group_limits_the_step(self):
        self.db.rows("customer_groups").append({"id": U("rg"), "tenant_id": "tenant-1", "name": "Hot", "kind": "rule",
                                               "rule": {"segment": "A"}})
        _lead(self.db, "arule", segment="A", last_inbound_at=ago(3), phone="+919876511111")
        self.db.rows("leads")[-1]["segment"] = "A"
        self.step(target_group_id=U("rg"), target_segments=["A"])
        count, names = await self.run_it()
        self.assertEqual(names, ["arule"])

    async def test_missing_or_unreadable_group_sends_nothing(self):
        self.step(target_group_id=U("gone"))
        self.assertEqual((await self.run_it())[1], [])
        self.db.tables["reengagement_steps"] = []
        self.step(target_group_id=U("g"))
        from app.services import reach_audience
        with patch.object(reach_audience, "resolve_group", side_effect=RuntimeError("db down")):
            self.assertEqual((await self.run_it())[1], [])

    async def test_group_is_worked_out_once_per_run(self):
        self.step(target_group_id=U("g"))
        self.step(target_group_id=U("g"), delay_hours=3)
        from app.services import reach_audience
        real = reach_audience.resolve_group
        with patch.object(reach_audience, "resolve_group", side_effect=real) as spy:
            await self.run_it()
        self.assertEqual(spy.call_count, 1)

    async def test_other_tenants_group_id_matches_nobody(self):
        self.db.rows("customer_groups").append({"id": U("gx"), "tenant_id": "tenant-2", "name": "Theirs", "kind": "picked"})
        self.db.rows("customer_group_members").append({"group_id": U("gx"), "lead_id": U("out"), "tenant_id": "tenant-2"})
        self.step(target_group_id=U("gx"))
        self.assertEqual((await self.run_it())[1], [])
