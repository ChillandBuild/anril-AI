"""Customers > Feedback (services/customer_feedback.py, routes/customer_feedback.py).
Everything outside is faked: the database (FakeSupabase), WhatsApp, the bell, the settings."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.routes import customer_feedback as routes
from app.services import customer_feedback as fb
from tests import fake_supabase
from tests.fake_supabase import FakeSupabase

T1, T2 = "t-1", "t-2"
PHONE = "+919876543210"
IST = fb.IST
NOW = datetime(2026, 11, 23, 11, 0, tzinfo=IST).astimezone(timezone.utc)   # Monday 11 AM IST


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def run(coro):
    return asyncio.run(coro)


class World:
    def __init__(self):
        self.db = FakeSupabase()
        self.sent: list[tuple] = []
        self.bells: list[dict] = []
        self.blocked = False
        self.ai_on = True
        self.settings = {"meta_waba_id": "waba-1", "meta_phone_number_id": "pn-1", "meta_access_token": "tok",
                         "feedback_on": "true"}
        self.db.add("app_settings", tenant_id=T1, key="feedback_on", value="true")
        self.db.add("tenants", id=T1, name="Glow Salon")
        self.db.add("leads", id="lead-1", tenant_id=T1, phone=PHONE, name="Priya Raman", opted_out=False,
                    blocked_at=None, whatsapp_undeliverable=False, last_inbound_at=iso(NOW - timedelta(hours=1)))
        self.db.add("callers", id="c-1", tenant_id=T1, name="Anita")
        self.db.add("tenant_users", tenant_id=T1, user_id="u-owner", role="owner", role_id=None)
        self.db.add("tenant_users", tenant_id=T1, user_id="u-view", role="member", role_id="r-view")
        self.db.add("tenant_roles", id="r-view", tenant_id=T1, permissions=["leads.view"])

    def approve(self):
        self.db.add("message_templates", tenant_id=T1, name=fb.TEMPLATE_NAME, status="APPROVED", meta_waba_id="waba-1",
                    body_text=fb.TEMPLATE_BODY, language="en", header_media_type=None)

    def order(self, **kw) -> dict:
        row = dict(id="d-1", tenant_id=T1, lead_id="lead-1", stage="won", sold_by="c-1",
                   delivered_at=iso(NOW - timedelta(hours=30)))
        row.update(kw)
        return self.db.add("deals", **row)

    def booking(self, **kw) -> dict:
        row = dict(id="bk-1", tenant_id=T1, lead_id="lead-1", phone=PHONE, customer_name="Priya Raman",
                   service_id="svc-1", resource_id="res-1", status="came", source="staff", phone_checked=True,
                   came_at=iso(NOW - timedelta(hours=30)))
        row.update(kw)
        self.db.add("booking_services", id="svc-1", tenant_id=T1, name="Haircut")
        self.db.add("booking_resources", id="res-1", tenant_id=T1, name="Ravi", user_id="u-ravi")
        return self.db.add("bookings", **row)

    def feedback(self, **kw) -> dict:
        row = dict(tenant_id=T1, lead_id="lead-1", phone=PHONE, kind="order", deal_id=None, booking_id=None,
                   status="asked", asked_at=iso(NOW - timedelta(hours=2)), stars=None, answered_at=None,
                   reason=None, staff_name=None)
        row.update(kw)
        return self.db.add("customer_feedback", **row)

    def row(self, fid) -> dict:
        return next(r for r in self.db.rows("customer_feedback") if r["id"] == fid)


@pytest.fixture
def w(monkeypatch):
    world = World()
    monkeypatch.setattr(fb, "_now", lambda: NOW)
    monkeypatch.setitem(fake_supabase._UNIQUE, "customer_feedback", [("deal_id",), ("booking_id",)])

    def get_setting(key, fallback=None, tenant_id=None):
        return world.settings.get(key, fallback)

    monkeypatch.setattr("app.config_dynamic.get_setting", get_setting)
    monkeypatch.setattr("app.services.call_details_share.get_setting", get_setting)
    monkeypatch.setattr("app.services.automation_guards.master_switch_on", lambda t: world.ai_on)
    monkeypatch.setattr("app.services.orders.order_settings",
                        lambda t: {"google_review_link": "https://g.page/r/glow"})
    monkeypatch.setattr(fb, "get_supabase", lambda: world.db)
    monkeypatch.setattr(routes, "get_supabase", lambda: world.db)

    async def is_blocked(tenant_id, value, channel="whatsapp"):
        return world.blocked

    monkeypatch.setattr("app.services.blocked_guard.is_blocked", is_blocked)

    async def send_whatsapp(phone, text, tenant_id=None, **kw):
        world.sent.append(("text", phone, text))
        return "wamid.TEXT"

    async def send_template(phone, name, lang="en", components=None, tenant_id=None, **kw):
        world.sent.append(("template", phone, name, components))
        return {"messages": [{"id": "wamid.TPL"}]}

    monkeypatch.setattr("app.services.ai_reply.send_whatsapp", send_whatsapp)
    monkeypatch.setattr("app.services.meta_cloud.send_template_message", send_template)

    def notify_user(tenant_id, user_id, type, title, message, **kw):
        world.bells.append({"tenant": tenant_id, "user": user_id, "type": type, "message": message,
                            "url": kw.get("push_url")})
        world.db.add("app_notifications", tenant_id=tenant_id, user_id=user_id, type=type, message=message,
                     url=kw.get("push_url"))

    monkeypatch.setattr("app.services.notify.notify_user", notify_user)
    return world


# ── the ask job ─────────────────────────────────────────────────────────────

def test_asks_a_delivered_order_once_with_star_payloads(w):
    w.approve()
    w.order()
    assert run(fb.ask_due_feedback(NOW)) == 1
    assert run(fb.ask_due_feedback(NOW)) == 0                      # never twice
    row = w.db.rows("customer_feedback")[0]
    assert (row["kind"], row["deal_id"], row["status"], row["staff_name"], row["phone"]) == (
        "order", "d-1", "asked", "Anita", PHONE)
    assert row["ask_message_id"] == "wamid.TPL"
    kind, phone, name, components = w.sent[0]
    assert (kind, phone, name) == ("template", PHONE, "feedback_ask")
    body = components[0]["parameters"]
    assert [p["text"] for p in body] == ["Priya", "order", "Glow Salon"]
    payloads = [c["parameters"][0]["payload"] for c in components[1:]]
    assert payloads == [f"fb:{n}:{row['id']}" for n in range(1, 6)]
    assert [c["index"] for c in components[1:]] == ["0", "1", "2", "3", "4"]


def test_asks_a_kept_booking_with_the_column_name_as_staff(w):
    w.approve()
    w.booking()
    assert run(fb.ask_due_feedback(NOW)) == 1
    row = w.db.rows("customer_feedback")[0]
    assert (row["kind"], row["booking_id"], row["staff_name"], row["staff_user_id"]) == (
        "booking", "bk-1", "Ravi", "u-ravi")
    assert w.sent[0][3][0]["parameters"][1]["text"] == "Haircut"


@pytest.mark.parametrize("hour,expected", [(9, 0), (10, 1), (19, 1), (20, 0)])
def test_only_between_10_and_8_ist(w, hour, expected):
    w.approve()
    w.order()
    at = datetime(2026, 11, 23, hour, 30, tzinfo=IST).astimezone(timezone.utc)
    assert run(fb.ask_due_feedback(at)) == expected
    assert len(w.sent) == expected


@pytest.mark.parametrize("hours,expected", [(10, 0), (23, 0), (25, 1), (71, 1), (80, 0)])
def test_only_24_to_72_hours_after_delivery(w, hours, expected):
    w.approve()
    w.order(delivered_at=iso(NOW - timedelta(hours=hours)))
    assert run(fb.ask_due_feedback(NOW)) == expected


def test_nothing_goes_when_switched_off_or_template_not_approved(w):
    w.order()
    assert run(fb.ask_due_feedback(NOW)) == 0                      # template never approved
    w.approve()
    w.db.rows("app_settings")[0]["value"] = "false"
    assert run(fb.ask_due_feedback(NOW)) == 0                      # feedback_on off
    w.db.rows("app_settings")[0]["value"] = "true"
    w.ai_on = False
    assert run(fb.ask_due_feedback(NOW)) == 0                      # Auto-Reply master switch off
    assert w.sent == []


@pytest.mark.parametrize("patch", [
    {"opted_out": True}, {"blocked_at": "2026-11-01T00:00:00+00:00"}, {"whatsapp_undeliverable": True},
])
def test_skips_people_who_must_not_be_messaged(w, patch):
    w.approve()
    w.order()
    w.db.rows("leads")[0].update(patch)
    assert run(fb.ask_due_feedback(NOW)) == 0
    assert w.db.rows("customer_feedback") == []


def test_skips_a_blocked_number_and_walk_in_orders(w):
    w.approve()
    w.order(id="d-2", lead_id=None)
    w.blocked = True
    w.order()
    assert run(fb.ask_due_feedback(NOW)) == 0


def test_one_ask_per_phone_per_30_days(w):
    w.approve()
    w.feedback(kind="order", deal_id="old", asked_at=iso(NOW - timedelta(days=10)), status="answered", stars=5)
    w.order()
    assert run(fb.ask_due_feedback(NOW)) == 0
    w.db.rows("customer_feedback")[0]["asked_at"] = iso(NOW - timedelta(days=40))
    assert run(fb.ask_due_feedback(NOW)) == 1


def test_two_orders_same_phone_one_ask(w):
    w.approve()
    w.order()
    w.order(id="d-2")
    assert run(fb.ask_due_feedback(NOW)) == 1
    assert len(w.db.rows("customer_feedback")) == 1


def test_other_tenants_are_not_asked_and_do_not_leak(w):
    w.approve()
    w.db.add("leads", id="lead-9", tenant_id=T2, phone="+919000000001", name="X", opted_out=False)
    w.db.add("deals", id="d-9", tenant_id=T2, lead_id="lead-9", stage="won",
             delivered_at=iso(NOW - timedelta(hours=30)))
    assert run(fb.ask_due_feedback(NOW)) == 0                      # T2 never turned it on


def test_failed_send_is_marked_failed_and_not_retried(w, monkeypatch):
    w.approve()
    w.order()

    async def boom(*a, **k):
        raise RuntimeError("131049 healthy ecosystem")

    monkeypatch.setattr("app.services.meta_cloud.send_template_message", boom)
    assert run(fb.ask_due_feedback(NOW)) == 0
    row = w.db.rows("customer_feedback")[0]
    assert row["status"] == "failed" and "131049" in row["error"]
    assert run(fb.ask_due_feedback(NOW)) == 0
    assert len(w.db.rows("customer_feedback")) == 1


def test_max_200_per_tenant_per_run(w, monkeypatch):
    w.approve()
    monkeypatch.setattr(fb, "MAX_PER_TENANT", 2)
    for i in range(5):
        phone = f"+91900000000{i}"
        w.db.add("leads", id=f"l{i}", tenant_id=T1, phone=phone, name=f"P{i}", opted_out=False, blocked_at=None,
                 whatsapp_undeliverable=False)
        w.order(id=f"d{i}", lead_id=f"l{i}")
    assert run(fb.ask_due_feedback(NOW)) == 2


# ── taps ────────────────────────────────────────────────────────────────────

def tap(w, n, fid, phone=PHONE, tenant=T1):
    return run(fb.handle_feedback_button(w.db, tenant, "lead-1", phone, f"fb:{n}:{fid}"))


def test_five_stars_thanks_with_review_link_and_offer(w):
    f = w.feedback()
    w.settings["feedback_offer"] = "10% off, code THANKS10"
    assert tap(w, 5, f["id"]) is True
    row = w.row(f["id"])
    assert (row["stars"], row["status"]) == (5, "answered") and row["answered_at"]
    text = w.sent[0][2]
    assert "Priya" in text and "https://g.page/r/glow" in text and "THANKS10" in text
    assert w.bells == []


def test_one_to_three_stars_asks_what_went_wrong_and_rings_owners_only(w):
    f = w.feedback()
    assert tap(w, 2, f["id"]) is True
    assert w.sent[0][2] == "Sorry to hear that. What went wrong?"
    assert [b["user"] for b in w.bells] == ["u-owner"]
    assert w.bells[0]["message"] == "⭐ 2 from Priya"
    assert w.bells[0]["url"].startswith("/dashboard/leads?tab=feedback")


def test_same_tap_twice_sends_nothing_new_and_later_tap_changes_stars(w):
    f = w.feedback()
    tap(w, 4, f["id"])
    assert tap(w, 4, f["id"]) is True
    assert len(w.sent) == 1
    first_answered = w.row(f["id"])["answered_at"]
    assert tap(w, 2, f["id"]) is True
    row = w.row(f["id"])
    assert row["stars"] == 2 and row["answered_at"] == first_answered


def test_a_fixed_one_does_not_change(w):
    f = w.feedback(status="fixed", stars=2, answered_at=iso(NOW))
    assert tap(w, 5, f["id"]) is True
    assert w.row(f["id"])["stars"] == 2 and w.sent == []


def test_wrong_phone_wrong_tenant_or_bad_payload_is_not_handled(w):
    f = w.feedback()
    assert tap(w, 5, f["id"], phone="+919111111111") is False
    assert tap(w, 5, f["id"], tenant=T2) is False
    assert run(fb.handle_feedback_button(w.db, T1, None, PHONE, "bk_yes:1")) is False
    assert run(fb.handle_feedback_button(w.db, T1, None, PHONE, "fb:9:" + f["id"])) is False
    assert run(fb.handle_feedback_button(w.db, T1, None, PHONE, f"fb:5:nope")) is False
    assert w.row(f["id"])["stars"] is None and w.sent == []


# ── the reason ──────────────────────────────────────────────────────────────

def test_next_message_after_low_stars_is_the_reason_and_updates_the_bell(w):
    f = w.feedback()
    tap(w, 1, f["id"])
    assert run(fb.handle_feedback_text(w.db, T1, "lead-1", PHONE, "Delivery  was\nvery late")) is True
    assert w.row(f["id"])["reason"] == "Delivery was very late"
    assert w.sent[-1][2] == "Thank you, we'll look into it."
    assert w.db.rows("app_notifications")[0]["message"] == "⭐ 1 from Priya: Delivery was very late"
    # a second message is a normal chat: reason already saved
    assert run(fb.handle_feedback_text(w.db, T1, "lead-1", PHONE, "hello?")) is False


def test_a_question_after_low_stars_is_saved_but_the_ai_answers_it(w):
    f = w.feedback()
    tap(w, 2, f["id"])
    sent_before = len(w.sent)
    assert run(fb.handle_feedback_text(w.db, T1, "lead-1", PHONE, "Where is my refund?")) is False
    assert w.row(f["id"])["reason"] == "Where is my refund?"
    assert len(w.sent) == sent_before  # no canned thank-you; the normal AI reply answers the question


def test_a_changed_star_tap_is_saved_quietly(w):
    f = w.feedback()
    tap(w, 5, f["id"])
    sent_before, bells_before = len(w.sent), len(w.db.rows("app_notifications"))
    assert tap(w, 1, f["id"]) is True
    assert w.row(f["id"])["stars"] == 1
    assert len(w.sent) == sent_before and len(w.db.rows("app_notifications")) == bells_before


def test_reason_is_capped_at_500(w):
    f = w.feedback()
    tap(w, 3, f["id"])
    run(fb.handle_feedback_text(w.db, T1, "lead-1", PHONE, "x" * 900))
    assert len(w.row(f["id"])["reason"]) == 500


def test_text_is_not_a_reason_for_happy_old_or_other_people(w):
    happy = w.feedback(deal_id="d-1")
    tap(w, 5, happy["id"])
    assert run(fb.handle_feedback_text(w.db, T1, "lead-1", PHONE, "great")) is False
    sad = w.feedback(deal_id="d-2")
    tap(w, 2, sad["id"])
    w.row(sad["id"])["answered_at"] = iso(NOW - timedelta(hours=25))
    assert run(fb.handle_feedback_text(w.db, T1, "lead-1", PHONE, "slow")) is False
    assert run(fb.handle_feedback_text(w.db, T2, "lead-1", PHONE, "slow")) is False
    assert w.row(sad["id"])["reason"] is None


# ── settings + results routes ───────────────────────────────────────────────

def ctx(**kw):
    return {"tenant_id": T1, "user_id": "u-owner", "role": "owner", **kw}


def test_settings_roundtrip_and_offer_limit(w):
    w.db.rows("app_settings").clear()
    fb.save_settings(w.db, T1, True, "  10%   off  ")
    saved = {r["key"]: r["value"] for r in w.db.rows("app_settings")}
    assert saved == {"feedback_on": "true", "feedback_offer": "10% off"}
    with pytest.raises(ValueError):
        fb.save_settings(w.db, T1, True, "x" * 201)
    out = run(routes.get_settings(ctx()))
    assert out["cost_per_message_rupees"] == 0.8631 and out["review_link"] == "https://g.page/r/glow"
    assert out["template_status"] is None and out["on"] is True


def test_template_status_values(w):
    assert fb.template_status(w.db, T1) is None
    w.db.add("message_templates", tenant_id=T1, name="feedback_ask", status="pending", meta_waba_id="waba-1")
    assert fb.template_status(w.db, T1) == "PENDING"


def test_results_numbers_reasons_staff_and_open_list(w):
    def answered(i, stars, staff, reason=None, status="answered", tenant=T1):
        return w.feedback(tenant_id=tenant, deal_id=f"x{i}", stars=stars, staff_name=staff, reason=reason,
                          status=status, answered_at=iso(NOW - timedelta(hours=i)),
                          asked_at=iso(NOW - timedelta(days=1)))

    answered(1, 5, "Anita")
    answered(2, 4, "Anita")
    answered(3, 2, "Ravi", "Delivery was late and rude staff")
    answered(4, 1, "Ravi", "Late delivery", status="fixed")
    answered(5, 3, None, "Late again")
    w.feedback(deal_id="x6", asked_at=iso(NOW - timedelta(days=1)))                # asked, not answered
    w.feedback(deal_id="x7", status="failed", asked_at=iso(NOW - timedelta(days=1)))  # never reached them
    answered(8, 1, "Z", "other shop", tenant=T2)
    out = run(routes.results("2026-11-20", "2026-11-23", ctx()))
    assert (out["asked"], out["answered"], out["answered_pct"]) == (6, 5, 83.3)
    assert out["average"] == 3.0
    assert {r["id"] for r in out["unhappy_open"]} == {r["id"] for r in w.db.rows("customer_feedback")
                                                       if r["stars"] in (2, 3) and r["tenant_id"] == T1}
    assert out["unhappy_open"][0]["name"] == "Priya Raman"
    assert out["reasons"][0] == {"text": "late", "count": 3}
    assert out["by_staff"] == [{"staff_name": "Anita", "avg": 4.5, "count": 2},
                               {"staff_name": "Ravi", "avg": 1.5, "count": 2}]
    assert len(out["recent"]) == 5 and out["recent"][0]["stars"] == 5


def test_results_default_period_empty_and_bad_dates(w):
    out = run(routes.results(None, None, ctx()))
    assert out["asked"] == 0 and out["average"] is None and out["recent"] == []
    from fastapi import HTTPException
    for bad in (("nope", None), ("2026-11-23", "2026-11-01"), ("2020-01-01", "2026-11-01")):
        with pytest.raises(HTTPException) as e:
            run(routes.results(bad[0], bad[1], ctx()))
        assert e.value.status_code == 400


def test_reasons_grouping_handles_tamil_and_skips_filler():
    got = routes.group_reasons(["The delivery was late", "late late delivery", "தாமதம் ஆனது", "தாமதம்"])
    assert got[0] == {"text": "delivery", "count": 2} or got[0]["count"] == 2
    texts = {g["text"] for g in got}
    assert "late" in texts and "தாமதம்" in texts and "the" not in texts


def test_mark_fixed(w):
    from fastapi import HTTPException
    f = w.feedback(stars=2, status="answered", answered_at=iso(NOW))
    out = run(routes.mark_fixed(f["id"], ctx(user_id="u-9")))
    row = w.row(f["id"])
    assert out["status"] == "fixed" and row["status"] == "fixed" and row["fixed_by"] == "u-9" and row["fixed_at"]
    assert run(routes.mark_fixed(f["id"], ctx()))["status"] == "fixed"            # twice is fine
    other = w.feedback(tenant_id=T2, deal_id="o", stars=1, status="answered")
    asked = w.feedback(deal_id="q")
    for bad in (other["id"], "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(HTTPException) as e:
            run(routes.mark_fixed(bad, ctx()))
        assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        run(routes.mark_fixed(asked["id"], ctx()))
    assert e.value.status_code == 400
    assert w.row(other["id"])["status"] == "answered"


def test_lead_lookup_by_phone_matches_both_spellings_and_prefers_said_stop():
    from tests.fake_supabase import FakeSupabase
    from app.services import customer_feedback as cfb
    db = FakeSupabase()
    db.add("leads", id="L1", tenant_id="t1", phone="919876500001", opted_out=None, deleted_at=None)
    db.add("leads", id="L2", tenant_id="t1", phone="+919876500001", opted_out=True, deleted_at=None)
    assert cfb._lead_row(db, "t1", None, "+919876500001")["id"] == "L2"
    assert cfb._lead_row(db, "t1", None, "+910000000000") == {}
    assert cfb._lead_row(db, "t2", None, "+919876500001") == {}
