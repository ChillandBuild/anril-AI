"""Bookings: messages, customer replies, reminders and the background jobs (services/booking_messages.py).
Everything outside is faked: the database (FakeSupabase), WhatsApp, the bell and the order code."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import booking_messages as bm
from tests.fake_supabase import FakeSupabase

T1, T2 = "t-1", "t-2"
PHONE = "+919876543210"
IST = bm.IST
# Monday 23 Nov 2026, 10:00 AM IST
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=IST).astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def ist(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=IST).astimezone(timezone.utc)


def run(coro):
    return asyncio.run(coro)


class World:
    """db + what was sent + which bells rang."""

    def __init__(self):
        self.db = FakeSupabase()
        self.sent: list[tuple] = []
        self.bells: list[dict] = []
        self.blocked = False
        self.text_fails = False
        self.paid = False
        self.released: list[str] = []
        self.db.add("tenants", id=T1, name="Glow Salon")
        self.db.add("tenants", id=T2, name="Other")
        self.db.add("booking_services", id="svc-1", tenant_id=T1, name="Haircut")
        self.db.add("booking_resources", id="res-1", tenant_id=T1, name="Ravi", user_id="u-ravi")
        self.db.add("tenant_users", tenant_id=T1, user_id="u-owner", role="owner", role_id=None)
        self.db.add("tenant_users", tenant_id=T1, user_id="u-mgr", role="member", role_id="r-mgr")
        self.db.add("tenant_users", tenant_id=T1, user_id="u-view", role="member", role_id="r-view")
        self.db.add("tenant_roles", id="r-mgr", tenant_id=T1, permissions=["bookings.manage"])
        self.db.add("tenant_roles", id="r-view", tenant_id=T1, permissions=["bookings.view"])
        self.db.add("leads", id="lead-1", tenant_id=T1, phone=PHONE, name="Priya Raman",
                    last_inbound_at=iso(NOW - timedelta(hours=1)), opted_out=False, blocked_at=None)

    def booking(self, **kw) -> dict:
        row = dict(id="bk-1", tenant_id=T1, number=12, lead_id="lead-1", phone=PHONE, customer_name="Priya Raman",
                   service_id="svc-1", resource_id="res-1", start_at=iso(ist(23, 16)), end_at=iso(ist(23, 17)),
                   block_end_at=iso(ist(23, 17)), status="booked", phone_checked=False, deal_id=None,
                   advance_paise=0, hold_until=None, confirmed_at=None, reminder_day_sent_at=None,
                   reminder_2h_sent_at=None, reminder_wamid=None, call_now_at=None,
                   created_at=iso(NOW - timedelta(days=3)))
        row.update(kw)
        return self.db.add("bookings", **row)

    def window(self, open_: bool):
        lead = self.db.rows("leads")[0]
        lead["last_inbound_at"] = iso(NOW - timedelta(hours=1 if open_ else 30))

    def approve(self, *keys):
        for key in keys:
            spec = bm.BOOKING_TEMPLATES[key]
            self.db.add("message_templates", tenant_id=T1, name=spec["name"], status="APPROVED",
                        meta_waba_id="waba-1", body_text=spec["body"], language="en", header_media_type=None)

    def row(self, bid="bk-1") -> dict:
        return next(r for r in self.db.rows("bookings") if r["id"] == bid)


@pytest.fixture
def w(monkeypatch):
    world = World()
    monkeypatch.setattr(bm, "_now", lambda: NOW)

    def get_setting(key, fallback=None, tenant_id=None):
        return {"meta_waba_id": "waba-1", "meta_phone_number_id": "pn-1", "meta_access_token": "tok"}.get(key, fallback)

    monkeypatch.setattr("app.config_dynamic.get_setting", get_setting)
    monkeypatch.setattr("app.services.call_details_share.get_setting", get_setting)

    async def is_blocked(tenant_id, value, channel="whatsapp"):
        return world.blocked

    monkeypatch.setattr("app.services.blocked_guard.is_blocked", is_blocked)

    async def send_whatsapp(phone, text, tenant_id=None, **kw):
        if world.text_fails:
            return None
        world.sent.append(("text", phone, text))
        return "wamid.TEXT"

    async def send_buttons(phone, text, buttons, tenant_id=None, **kw):
        world.sent.append(("buttons", phone, text, buttons))
        return {"messages": [{"id": "wamid.BTN"}]}

    async def send_template(phone, name, lang="en", components=None, tenant_id=None, **kw):
        world.sent.append(("template", phone, name, components))
        return {"messages": [{"id": "wamid.TPL"}]}

    monkeypatch.setattr("app.services.ai_reply.send_whatsapp", send_whatsapp)
    monkeypatch.setattr("app.services.meta_cloud.send_interactive_buttons", send_buttons)
    monkeypatch.setattr("app.services.meta_cloud.send_template_message", send_template)

    def notify_user(tenant_id, user_id, type, title, message, **kw):
        world.bells.append({"tenant": tenant_id, "user": user_id, "type": type, "url": kw.get("push_url"),
                            "message": message})

    monkeypatch.setattr("app.services.notify.notify_user", notify_user)
    monkeypatch.setattr("app.services.booking_orders.advance_paid", lambda t, b, db=None: world.paid)
    monkeypatch.setattr("app.services.booking_orders.release_unpaid_order",
                        lambda t, b, db=None: world.released.append(b["id"]))
    return world


# ── formatting ──────────────────────────────────────────────────────────────

def test_when_text_is_ist_and_plain():
    assert bm.when_text(iso(datetime(2026, 11, 28, 16, 0, tzinfo=IST))) == "Sat 28 Nov, 4:00 PM"
    assert bm.when_text("2026-11-28T18:30:00+00:00") == "Sun 29 Nov, 12:00 AM"  # 00:00 IST next day
    assert bm.when_text(iso(datetime(2026, 11, 26, 12, 5, tzinfo=IST))) == "Thu 26 Nov, 12:05 PM"
    assert bm.booking_code(12) == "BK-0012"


# ── sends ───────────────────────────────────────────────────────────────────

def test_confirmation_text_inside_the_window(w):
    w.booking()
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is True
    kind, phone, text = w.sent[0]
    assert (kind, phone) == ("text", PHONE)
    assert "Priya" in text and "Haircut" in text and "Mon 23 Nov, 4:00 PM" in text and "Ravi" in text and "BK-0012" in text
    assert w.db.rows("messages")[0]["meta_message_id"] == "wamid.TEXT"  # saved to the chat


def test_confirmation_uses_template_when_window_closed(w):
    w.window(False)
    w.approve("update")
    w.booking()
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is True
    kind, _, name, components = w.sent[0]
    assert (kind, name) == ("template", "anril_booking_update")
    values = [p["text"] for p in components[0]["parameters"]]
    assert values == ["Priya", "Haircut", "Mon 23 Nov, 4:00 PM", "Ravi", "BK-0012"]


def test_confirmation_sends_nothing_when_closed_and_no_template(w):
    w.window(False)
    w.booking()
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is False
    assert w.sent == []


def test_unapproved_template_is_not_used(w):
    w.window(False)
    w.db.add("message_templates", tenant_id=T1, name="anril_booking_update", status="PENDING",
             meta_waba_id="waba-1", body_text="x", language="en", header_media_type=None)
    w.booking()
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is False


def test_blocked_person_gets_nothing(w):
    w.blocked = True
    w.booking()
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is False
    assert w.sent == []


def test_lead_blocked_flag_gets_nothing(w):
    w.db.rows("leads")[0]["blocked_at"] = "2026-11-01T00:00:00+00:00"
    w.booking()
    assert run(bm.send_cancelled(w.db, T1, "bk-1")) is False
    assert w.sent == []


def test_moved_and_cancelled_wording(w):
    w.booking()
    assert run(bm.send_moved(w.db, T1, "bk-1")) is True
    assert "moved to Mon 23 Nov, 4:00 PM" in w.sent[-1][2]
    assert run(bm.send_cancelled(w.db, T1, "bk-1", "The advance was not paid in time")) is True
    assert "is cancelled" in w.sent[-1][2] and "The advance was not paid in time." in w.sent[-1][2]


def test_template_labels_for_moved_and_cancelled(w):
    w.window(False)
    w.approve("update")
    w.booking()
    run(bm.send_moved(w.db, T1, "bk-1"))
    run(bm.send_cancelled(w.db, T1, "bk-1"))
    assert w.sent[0][3][0]["parameters"][2]["text"].endswith("(new time)")
    assert w.sent[1][3][0]["parameters"][2]["text"].endswith("(cancelled)")


def test_held_booking_confirmation_does_not_claim_confirmed(w):
    w.booking(status="held")
    run(bm.send_confirmation(w.db, T1, "bk-1"))
    assert "holding" in w.sent[0][2] and "confirmed for" not in w.sent[0][2]


def test_other_tenants_booking_is_not_found(w):
    w.booking()
    assert run(bm.send_confirmation(w.db, T2, "bk-1")) is False
    assert w.sent == []


def test_sends_never_raise(w):
    class Boom:
        def table(self, *a):
            raise RuntimeError("db down")

    assert run(bm.send_confirmation(Boom(), T1, "bk-1")) is False
    assert run(bm.send_moved(Boom(), T1, "bk-1")) is False
    assert run(bm.send_cancelled(Boom(), T1, "bk-1")) is False


# ── templates ───────────────────────────────────────────────────────────────

def test_template_specs():
    assert bm.BOOKING_TEMPLATES["update"]["name"] == "anril_booking_update"
    assert bm.BOOKING_TEMPLATES["update"]["body"] == "Hi {{1}}, your {{2}} booking is on {{3}} with {{4}}. Code {{5}}."
    assert bm.BOOKING_TEMPLATES["reminder"]["name"] == "anril_booking_reminder"
    assert bm.BOOKING_TEMPLATES["reminder"]["buttons"] == ["Yes, coming", "Cancel"]


def test_templates_status(w):
    assert bm.templates_status(w.db, T1) == {"update": None, "reminder": None}
    w.approve("update")
    w.db.add("message_templates", tenant_id=T1, name="anril_booking_reminder", status="rejected", meta_waba_id="waba-1")
    w.db.add("message_templates", tenant_id=T1, name="anril_booking_update", status="APPROVED", meta_waba_id="old-waba")
    assert bm.templates_status(w.db, T1) == {"update": "APPROVED", "reminder": "REJECTED"}


def test_submit_templates_sends_only_the_missing_ones(w, monkeypatch):
    w.approve("update")
    made = []

    async def create_template(body, tenant_id=None, _ctx=None):
        made.append(body)
        w.db.add("message_templates", tenant_id=T1, name=body.name, status="PENDING", meta_waba_id="waba-1")

    monkeypatch.setattr("app.routes.templates.create_template", create_template)
    out = run(bm.submit_templates(w.db, T1, {}))
    assert [m.name for m in made] == ["anril_booking_reminder"]
    assert made[0].category == "UTILITY" and [b.text for b in made[0].buttons] == ["Yes, coming", "Cancel"]
    assert out["problems"] == [] and out["templates"]["reminder"] == "PENDING"


def test_submit_templates_reports_problems(w, monkeypatch):
    from fastapi import HTTPException

    async def create_template(body, tenant_id=None, _ctx=None):
        raise HTTPException(400, "Meta said no")

    monkeypatch.setattr("app.routes.templates.create_template", create_template)
    out = run(bm.submit_templates(w.db, T1, {}))
    assert len(out["problems"]) == 2 and "Meta said no" in out["problems"][0]


def test_template_bodies_pass_metas_rules():
    from app.services.template_rules import body_problems
    for spec in bm.BOOKING_TEMPLATES.values():
        assert body_problems(spec["body"]) == []


# ── customer replies: the code ──────────────────────────────────────────────

@pytest.mark.parametrize("text", ["BK-0012", "my code is bk-0012 thanks", "bk 12", "Bk12", "BK-12"])
def test_code_in_a_message_confirms_and_marks_phone_checked(w, text):
    w.booking(lead_id=None)
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", "919876543210", text)) is True
    row = w.row()
    assert row["phone_checked"] is True and row["lead_id"] == "lead-1"
    assert "confirmed" in w.sent[0][2]


def test_code_keeps_an_existing_lead(w):
    w.booking(lead_id="lead-9")
    run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, "BK-0012"))
    assert w.row()["lead_id"] == "lead-9"


def test_code_from_another_phone_does_nothing(w):
    w.booking()
    assert run(bm.handle_booking_code(w.db, T1, "lead-2", "+919000000001", "BK-0012")) is False
    assert w.row()["phone_checked"] is False and w.sent == []


def test_code_in_another_tenant_does_nothing(w):
    w.booking()
    assert run(bm.handle_booking_code(w.db, T2, "lead-1", PHONE, "BK-0012")) is False


@pytest.mark.parametrize("status", ["cancelled", "no_show", "came"])
def test_code_for_a_finished_booking_does_nothing(w, status):
    w.booking(status=status)
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, "BK-0012")) is False


@pytest.mark.parametrize("text", ["hello", "", "bk", "BK-0099", "book 12", "my number is 9876"])
def test_no_code_or_unknown_code(w, text):
    w.booking()
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, text)) is False


def test_code_handler_never_raises():
    class Boom:
        def table(self, *a):
            raise RuntimeError("db down")

    assert run(bm.handle_booking_code(Boom(), T1, "l", PHONE, "BK-0012")) is False


# ── customer replies: buttons ───────────────────────────────────────────────

def test_yes_button_confirms_and_clears_call_now(w):
    w.booking(call_now_at=iso(NOW))
    assert run(bm.handle_booking_button(w.db, T1, "919876543210", "bk_yes:bk-1")) is True
    row = w.row()
    assert row["confirmed_at"] and row["call_now_at"] is None
    assert w.sent[-1][2] == "Thank you, see you then."


def test_button_from_the_wrong_phone_is_ignored(w):
    w.booking()
    assert run(bm.handle_booking_button(w.db, T1, "+919000000001", "bk_yes:bk-1")) is False
    assert w.row()["confirmed_at"] is None


def test_button_in_the_wrong_tenant_is_ignored(w):
    w.booking()
    assert run(bm.handle_booking_button(w.db, T2, PHONE, "bk_yes:bk-1")) is False


@pytest.mark.parametrize("payload", ["", "other", "bk_yes:", "bk_yes:../etc", "bk_maybe:bk-1", None])
def test_bad_payloads_are_not_ours(w, payload):
    w.booking()
    assert run(bm.handle_booking_button(w.db, T1, PHONE, payload)) is False


def test_button_on_a_finished_booking_says_so(w):
    w.booking(status="cancelled")
    assert run(bm.handle_booking_button(w.db, T1, PHONE, "bk_yes:bk-1")) is True
    assert w.row()["confirmed_at"] is None and "no longer active" in w.sent[-1][2]


def test_cancel_button_before_the_cutoff_cancels(w):
    w.booking(start_at=iso(NOW + timedelta(hours=5)), end_at=iso(NOW + timedelta(hours=6)),
              block_end_at=iso(NOW + timedelta(hours=6)))
    w.db.rows("leads")[0]["booked_for"] = iso(NOW + timedelta(hours=5))
    assert run(bm.handle_booking_button(w.db, T1, PHONE, "bk_cancel:bk-1")) is True
    row = w.row()
    assert row["status"] == "cancelled" and row["cancelled_by"] == "customer" and row["cancelled_at"]
    assert w.db.rows("leads")[0]["booked_for"] is None  # mirror recomputed
    assert [b["type"] for b in w.bells] == ["booking_cancelled"] * 3  # owner, manager, the column's person
    assert {b["user"] for b in w.bells} == {"u-owner", "u-mgr", "u-ravi"}
    assert all("/dashboard/bookings?date=" in b["url"] and "booking=bk-1" in b["url"] for b in w.bells)
    assert "is cancelled" in w.sent[-1][2]


def test_cancel_button_inside_the_cutoff_asks_them_to_call(w):
    w.booking(start_at=iso(NOW + timedelta(hours=2)), end_at=iso(NOW + timedelta(hours=3)),
              block_end_at=iso(NOW + timedelta(hours=3)))
    assert run(bm.handle_booking_button(w.db, T1, PHONE, "bk_cancel:bk-1")) is True
    assert w.row()["status"] == "booked" and w.bells == []
    assert w.sent[-1][2] == "It's less than 3 hours away, please call us."


def test_cutoff_comes_from_the_settings(w):
    w.db.add("booking_settings", tenant_id=T1, cancel_cutoff_min=60)
    w.booking(start_at=iso(NOW + timedelta(hours=2)), end_at=iso(NOW + timedelta(hours=3)),
              block_end_at=iso(NOW + timedelta(hours=3)))
    run(bm.handle_booking_button(w.db, T1, PHONE, "bk_cancel:bk-1"))
    assert w.row()["status"] == "cancelled"


def test_cancelling_a_held_booking_closes_its_unpaid_order(w):
    w.booking(status="held", deal_id="deal-1", start_at=iso(NOW + timedelta(hours=9)),
              end_at=iso(NOW + timedelta(hours=10)), block_end_at=iso(NOW + timedelta(hours=10)))
    run(bm.handle_booking_button(w.db, T1, PHONE, "bk_cancel:bk-1"))
    assert w.released == ["bk-1"]


def test_cancel_twice_rings_once(w):
    w.booking(start_at=iso(NOW + timedelta(hours=9)), end_at=iso(NOW + timedelta(hours=10)),
              block_end_at=iso(NOW + timedelta(hours=10)))
    run(bm.handle_booking_button(w.db, T1, PHONE, "bk_cancel:bk-1"))
    n = len(w.bells)
    run(bm.handle_booking_button(w.db, T1, PHONE, "bk_cancel:bk-1"))
    assert len(w.bells) == n


# ── customer replies: thumbs up ─────────────────────────────────────────────

@pytest.mark.parametrize("emoji", ["\U0001F44D", "\U0001F44D\U0001F3FD", "\U0001F44D\U0001F3FF", "\U0001F44D️"])
def test_thumbs_up_on_the_reminder_confirms(w, emoji):
    w.booking(reminder_wamid="wamid.R1")
    assert run(bm.handle_booking_reaction(w.db, T1, PHONE, "wamid.R1", emoji)) is True
    assert w.row()["confirmed_at"]


@pytest.mark.parametrize("emoji", ["❤️", "\U0001F44E", "", None])
def test_other_reactions_are_ignored(w, emoji):
    w.booking(reminder_wamid="wamid.R1")
    assert run(bm.handle_booking_reaction(w.db, T1, PHONE, "wamid.R1", emoji)) is False
    assert w.row()["confirmed_at"] is None


def test_thumbs_up_on_another_message_or_phone_or_tenant_is_ignored(w):
    w.booking(reminder_wamid="wamid.R1")
    assert run(bm.handle_booking_reaction(w.db, T1, PHONE, "wamid.OTHER", "\U0001F44D")) is False
    assert run(bm.handle_booking_reaction(w.db, T1, "+919000000001", "wamid.R1", "\U0001F44D")) is False
    assert run(bm.handle_booking_reaction(w.db, T2, PHONE, "wamid.R1", "\U0001F44D")) is False
    assert w.row()["confirmed_at"] is None


# ── held slots ──────────────────────────────────────────────────────────────

def test_release_holds_cancels_unpaid_and_books_paid(w):
    w.booking(id="unpaid", number=1, status="held", hold_until=iso(NOW - timedelta(minutes=3)), deal_id="d1",
              lead_id=None)
    w.booking(id="fresh", number=2, status="held", hold_until=iso(NOW + timedelta(minutes=5)),
              lead_id=None, start_at=iso(ist(24, 10)), end_at=iso(ist(24, 11)),
              block_end_at=iso(ist(24, 11)))
    assert run(bm.release_holds(w.db, NOW)) == 1
    unpaid = w.row("unpaid")
    assert unpaid["status"] == "cancelled" and unpaid["cancelled_by"] == "system"
    assert unpaid["cancel_reason"] == "Advance not paid in time"
    assert w.released == ["unpaid"] and w.row("fresh")["status"] == "held"

    w.paid = True
    w.db.rows("bookings")[1]["hold_until"] = iso(NOW - timedelta(minutes=3))
    assert run(bm.release_holds(w.db, NOW)) == 1
    assert w.row("fresh")["status"] == "booked" and w.row("fresh")["hold_until"] is None
    assert any("confirmed" in s[2] for s in w.sent if s[0] == "text")


def test_release_holds_skips_nothing_else(w):
    w.booking(status="booked", hold_until=iso(NOW - timedelta(minutes=1)))
    assert run(bm.release_holds(w.db, NOW)) == 0 and w.row()["status"] == "booked"


def test_release_holds_one_failure_does_not_stop_the_rest(w, monkeypatch):
    w.booking(id="a", number=1, status="held", hold_until=iso(NOW - timedelta(minutes=3)), phone="+919000000002")
    w.booking(id="b", number=2, status="held", hold_until=iso(NOW - timedelta(minutes=3)), phone="+919000000003",
              start_at=iso(ist(24, 10)), end_at=iso(ist(24, 11)), block_end_at=iso(ist(24, 11)))

    def paid(t, b, db=None):
        if b["id"] == "a":
            raise RuntimeError("deal lookup failed")
        return False

    monkeypatch.setattr("app.services.booking_orders.advance_paid", paid)
    assert run(bm.release_holds(w.db, NOW)) == 1
    assert w.row("a")["status"] == "held" and w.row("b")["status"] == "cancelled"


def test_confirm_if_paid(w):
    b = w.booking(status="held", hold_until=iso(NOW + timedelta(minutes=10)))
    assert run(bm.confirm_if_paid(w.db, T1, b))["status"] == "held"  # not paid yet
    w.paid = True
    out = run(bm.confirm_if_paid(w.db, T1, b))
    assert out["status"] == "booked" and w.row()["status"] == "booked" and w.row()["hold_until"] is None
    assert any("confirmed" in s[2] for s in w.sent)
    assert run(bm.confirm_if_paid(w.db, T1, out))["status"] == "booked"  # already booked: nothing more
    assert len(w.sent) == 1


def test_confirm_if_paid_never_raises(w, monkeypatch):
    monkeypatch.setattr("app.services.booking_orders.advance_paid", lambda *a, **k: 1 / 0)
    b = {"id": "x", "status": "held"}
    assert run(bm.confirm_if_paid(w.db, T1, b)) == b


# ── reminders: when ─────────────────────────────────────────────────────────

def _b(start, **kw):
    return {"status": "booked", "start_at": iso(start), "created_at": iso(NOW - timedelta(days=5)),
            "reminder_day_sent_at": None, "reminder_2h_sent_at": None, **kw}


@pytest.mark.parametrize("now_ist,start_ist,due", [
    ((23, 10), (24, 12), True),       # 26 h away, 10 AM
    ((23, 10), (24, 6), True),        # 20 h away, 10 AM: on the edge
    ((23, 10), (24, 15), False),      # 29 h away: not yet
    ((23, 8), (24, 11), False),       # 8 AM is too early
    ((23, 9), (24, 11), True),        # 9 AM sharp is allowed
    ((23, 19), (24, 21), True),       # 7 PM allowed (26 h)
    ((23, 20), (24, 22), False),      # 8 PM sharp is too late
    ((23, 22), (24, 23), False),      # night
])
def test_day_reminder_window_and_hours(now_ist, start_ist, due):
    now, start = ist(*now_ist), ist(*start_ist)
    assert bm.day_reminder_due(_b(start), now) is due


def test_day_reminder_edges_exact():
    now = ist(23, 10)
    assert bm.day_reminder_due(_b(now + timedelta(hours=28)), now)
    assert bm.day_reminder_due(_b(now + timedelta(hours=20)), now)
    assert not bm.day_reminder_due(_b(now + timedelta(hours=28, minutes=1)), now)


def test_day_reminder_waits_for_the_next_allowed_time_for_an_early_visit():
    start = ist(24, 2)  # 2 AM visit: its 20-28 h window was 2 AM-6 AM the day before
    assert not bm.day_reminder_due(_b(start), ist(23, 6))        # window, but too early to message
    assert not bm.day_reminder_due(_b(start), ist(23, 8, 55))
    assert bm.day_reminder_due(_b(start), ist(23, 9))            # first allowed time, 17 h before
    assert not bm.day_reminder_due(_b(start), ist(23, 21))       # past 8 PM: never at night
    assert not bm.day_reminder_due(_b(start), ist(24, 0, 30))    # inside the last 2 h 15 m: skip


def test_a_late_booking_gets_no_day_reminder():
    now = ist(23, 10)
    start = now + timedelta(hours=10)
    assert not bm.day_reminder_due(_b(start, created_at=iso(now - timedelta(hours=1))), now)


def test_day_reminder_only_once_and_only_when_booked():
    now = ist(23, 10)
    start = now + timedelta(hours=24)
    assert not bm.day_reminder_due(_b(start, reminder_day_sent_at=iso(now)), now)
    for status in ("held", "cancelled", "no_show", "came"):
        assert not bm.day_reminder_due(_b(start, status=status), now)


@pytest.mark.parametrize("minutes,due", [(104, False), (105, True), (120, True), (135, True), (136, False), (30, False)])
def test_two_hour_window(minutes, due):
    assert bm.two_hour_due(_b(NOW + timedelta(minutes=minutes)), NOW) is due


def test_two_hour_only_once():
    assert not bm.two_hour_due(_b(NOW + timedelta(hours=2), reminder_2h_sent_at=iso(NOW)), NOW)


# ── reminders: the job ──────────────────────────────────────────────────────

def _two_h(w, **kw):
    s = NOW + timedelta(hours=2)
    return w.booking(start_at=iso(s), end_at=iso(s + timedelta(hours=1)), block_end_at=iso(s + timedelta(hours=1)), **kw)


def test_two_hour_reminder_with_buttons_in_the_window(w):
    _two_h(w)
    assert run(bm.send_reminders(w.db, NOW)) == 1
    kind, phone, text, buttons = w.sent[0]
    assert kind == "buttons" and phone == PHONE and "Will you be there?" in text and "in about 2 hours" in text
    assert buttons == [{"id": "bk_yes:bk-1", "title": "Yes, coming"}, {"id": "bk_cancel:bk-1", "title": "Cancel"}]
    row = w.row()
    assert row["reminder_2h_sent_at"] and row["reminder_wamid"] == "wamid.BTN"
    assert run(bm.send_reminders(w.db, NOW)) == 0  # not twice


def test_day_reminder_uses_the_template_with_quick_reply_payloads(w):
    w.window(False)
    w.approve("reminder")
    s = NOW + timedelta(hours=26)  # Tue 12:00 IST
    w.booking(start_at=iso(s), end_at=iso(s + timedelta(hours=1)), block_end_at=iso(s + timedelta(hours=1)))
    assert run(bm.send_reminders(w.db, NOW)) == 1
    kind, _, name, comps = w.sent[0]
    assert (kind, name) == ("template", "anril_booking_reminder")
    assert [p["text"] for p in comps[0]["parameters"]] == ["Priya", "Haircut", "tomorrow, Tue 24 Nov, 12:00 PM", "Ravi"]
    assert [c["parameters"][0]["payload"] for c in comps[1:]] == ["bk_yes:bk-1", "bk_cancel:bk-1"]
    assert w.row()["reminder_day_sent_at"] and w.row()["reminder_wamid"] == "wamid.TPL"


def test_reminder_without_a_template_is_left_unsent_and_flagged_for_a_call(w):
    w.window(False)
    _two_h(w)
    assert run(bm.send_reminders(w.db, NOW)) == 0
    row = w.row()
    assert row["reminder_2h_sent_at"] is None and row["reminder_wamid"] is None and row["call_now_at"]
    assert [b["type"] for b in w.bells] == ["booking_call_now"] * 3
    run(bm.send_reminders(w.db, NOW))  # the next tick tries again, but rings only once
    assert len(w.bells) == 3


def test_blocked_person_gets_no_reminder_and_no_call_flag(w):
    w.blocked = True
    _two_h(w)
    assert run(bm.send_reminders(w.db, NOW)) == 0
    assert w.sent == [] and w.row()["call_now_at"] is None and w.bells == []


@pytest.mark.parametrize("status", ["cancelled", "no_show", "held", "came"])
def test_no_reminder_for_a_booking_that_is_not_booked(w, status):
    _two_h(w, status=status)
    assert run(bm.send_reminders(w.db, NOW)) == 0 and w.sent == []


def test_no_day_reminder_at_night(w):
    night = ist(23, 21)
    s = night + timedelta(hours=24)
    w.booking(start_at=iso(s), end_at=iso(s + timedelta(hours=1)), block_end_at=iso(s + timedelta(hours=1)))
    assert run(bm.send_reminders(w.db, night)) == 0 and w.sent == []


def test_today_wording_when_the_visit_is_the_same_day(w):
    now = ist(23, 9)
    s = ist(24, 2)  # the early visit shifted to 9 AM the day before: still "tomorrow"
    w.booking(start_at=iso(s), end_at=iso(s + timedelta(hours=1)), block_end_at=iso(s + timedelta(hours=1)))
    run(bm.send_reminders(w.db, now))
    assert "tomorrow, Tue 24 Nov, 2:00 AM" in w.sent[0][2]


def test_one_bad_booking_does_not_stop_the_others(w, monkeypatch):
    _two_h(w, id="a", number=1)
    _two_h(w, id="b", number=2, phone="+919000000009", lead_id=None)
    real = bm._send_reminder

    async def flaky(db, tenant_id, b, label):
        if b["id"] == "a":
            raise RuntimeError("boom")
        return await real(db, tenant_id, b, label)

    monkeypatch.setattr(bm, "_send_reminder", flaky)
    w.db.rows("leads").append({"id": "lead-9", "tenant_id": T1, "phone": "+919000000009", "name": "Z",
                               "last_inbound_at": iso(NOW - timedelta(hours=1)), "opted_out": False})
    assert run(bm.send_reminders(w.db, NOW)) == 1
    assert w.row("b")["reminder_2h_sent_at"] and w.row("a")["reminder_2h_sent_at"] is None


# ── call now ────────────────────────────────────────────────────────────────

def _awaiting(w, sent_min_ago=61, **kw):
    s = NOW + timedelta(hours=1)
    return w.booking(start_at=iso(s), end_at=iso(s + timedelta(hours=1)), block_end_at=iso(s + timedelta(hours=1)),
                     reminder_2h_sent_at=iso(NOW - timedelta(minutes=sent_min_ago)), **kw)


def test_call_now_flags_once_and_rings_once(w):
    _awaiting(w)
    assert bm.flag_call_now(w.db, NOW) == 1
    assert w.row()["call_now_at"]
    assert [b["type"] for b in w.bells] == ["booking_call_now"] * 3
    assert bm.flag_call_now(w.db, NOW) == 0 and len(w.bells) == 3


def test_call_now_waits_an_hour(w):
    _awaiting(w, sent_min_ago=59)
    assert bm.flag_call_now(w.db, NOW) == 0 and w.bells == []


def test_call_now_not_after_a_yes_since_the_reminder(w):
    _awaiting(w, confirmed_at=iso(NOW - timedelta(minutes=10)))
    assert bm.flag_call_now(w.db, NOW) == 0


def test_call_now_ignores_a_yes_from_before_the_reminder(w):
    _awaiting(w, confirmed_at=iso(NOW - timedelta(hours=20)))
    assert bm.flag_call_now(w.db, NOW) == 1


def test_call_now_not_once_the_visit_has_started_or_when_not_booked(w):
    s = NOW - timedelta(minutes=5)
    w.booking(id="past", number=1, start_at=iso(s), end_at=iso(s + timedelta(hours=1)),
              block_end_at=iso(s + timedelta(hours=1)), reminder_2h_sent_at=iso(NOW - timedelta(hours=3)))
    _awaiting(w, status="cancelled", id="gone", number=2)
    assert bm.flag_call_now(w.db, NOW) == 0


def test_call_now_without_a_two_hour_reminder_does_nothing(w):
    w.booking()
    assert bm.flag_call_now(w.db, NOW) == 0


def test_bell_goes_to_owner_managers_and_the_columns_person_only(w):
    _awaiting(w)
    bm.flag_call_now(w.db, NOW)
    assert {b["user"] for b in w.bells} == {"u-owner", "u-mgr", "u-ravi"}  # not the view-only user
    assert all(b["tenant"] == T1 for b in w.bells)


def test_the_task_functions_are_wired_in_the_queue():
    from app.queue import tasks
    assert tasks.RETRY_CLASS["booking-release-holds"] == "C"
    assert tasks.RETRY_CLASS["booking-reminders"] == "C"
    assert tasks.RETRY_CLASS["booking-call-now"] == "C"


# ── review fixes: held slots ────────────────────────────────────────────────

def test_a_hold_is_given_two_minutes_of_grace(w):
    w.booking(status="held", hold_until=iso(NOW - timedelta(minutes=1, seconds=30)))
    assert run(bm.release_holds(w.db, NOW)) == 0 and w.row()["status"] == "held"
    w.row()["hold_until"] = iso(NOW - timedelta(minutes=2, seconds=1))
    assert run(bm.release_holds(w.db, NOW)) == 1 and w.row()["status"] == "cancelled"


def _held_late(w, **kw):
    return w.booking(status="held", deal_id="d1", hold_until=iso(NOW - timedelta(minutes=5)), **kw)


def test_payment_landing_during_the_release_puts_the_booking_back(w, monkeypatch):
    _held_late(w)
    calls = iter([False, True])  # unpaid at the first look, paid at the re-check
    monkeypatch.setattr("app.services.booking_orders.advance_paid", lambda t, b, db=None: next(calls))
    assert run(bm.release_holds(w.db, NOW)) == 1
    row = w.row()
    assert row["status"] == "booked" and row["cancelled_by"] is None and row["cancel_reason"] is None
    assert any("confirmed" in s[2] for s in w.sent)
    assert {b["type"] for b in w.bells} == {"booking_new"}


def test_payment_landing_but_slot_retaken_rings_staff(w, monkeypatch):
    _held_late(w)
    w.db.add("deals", id="d1", tenant_id=T1, paid_paise=20000, refunded_paise=0)
    calls = iter([False, True])
    monkeypatch.setattr("app.services.booking_orders.advance_paid", lambda t, b, db=None: next(calls))
    monkeypatch.setattr(bm, "_try_rebook", lambda db, t, b: False)  # 23P01: someone took the time
    run(bm.release_holds(w.db, NOW))
    assert w.row()["status"] == "cancelled" and w.row()["call_now_at"]
    assert {b["type"] for b in w.bells} == {"booking_call_now"} and len(w.bells) == 3
    assert "Priya paid \u20b9200 after the hold ended" in w.bells[0]["message"]
    assert "call to rebook or refund" in w.bells[0]["message"]
    assert w.sent == []  # no "cancelled" message to someone who has paid


def test_try_rebook_maps_the_overlap_error_to_false(w):
    b = _held_late(w)

    class Boom:
        def table(self, *a):
            raise Exception("23P01 conflicting key value violates exclusion constraint bookings_no_overlap")

    assert bm._try_rebook(Boom(), T1, b) is False
    class Other(Boom):
        def table(self, *a):
            raise Exception("db down")
    with pytest.raises(Exception, match="db down"):
        bm._try_rebook(Other(), T1, b)


def _system_cancelled(w, hours_ago=5, **kw):
    fields = dict(status="cancelled", cancelled_by="system", cancel_reason="Advance not paid in time",
                  cancelled_at=iso(NOW - timedelta(hours=hours_ago)), deal_id="d1")
    return w.booking(**{**fields, **kw})


def test_late_payment_sweep_rings_once_per_booking(w):
    _system_cancelled(w)
    w.db.add("deals", id="d1", tenant_id=T1, paid_paise=20000, refunded_paise=0)
    run(bm.release_holds(w.db, NOW))
    assert len(w.bells) == 3 and w.bells[0]["type"] == "booking_call_now"
    assert "paid \u20b9200 after the hold ended" in w.bells[0]["message"]
    run(bm.release_holds(w.db, NOW))
    assert len(w.bells) == 3  # call_now_at is the "already rung" marker


@pytest.mark.parametrize("paid,refunded,hours,by,reason", [
    (0, 0, 5, "system", "Advance not paid in time"),           # never paid
    (20000, 20000, 5, "system", "Advance not paid in time"),   # refunded
    (20000, 0, 49, "system", "Advance not paid in time"),      # older than 48 h
    (20000, 0, 5, "staff", "Advance not paid in time"),        # not the system's release
    (20000, 0, 5, "system", "Asked to cancel"),                # another reason
])
def test_late_payment_sweep_leaves_the_rest_alone(w, paid, refunded, hours, by, reason):
    _system_cancelled(w, hours_ago=hours, cancelled_by=by, cancel_reason=reason)
    w.db.add("deals", id="d1", tenant_id=T1, paid_paise=paid, refunded_paise=refunded)
    run(bm.release_holds(w.db, NOW))
    assert w.bells == [] and w.row()["call_now_at"] is None


# ── review fixes: sending ───────────────────────────────────────────────────

def test_a_failing_buttons_send_falls_back_to_the_template(w, monkeypatch):
    w.approve("reminder")
    _two_h(w)

    async def boom(*a, **k):
        raise RuntimeError("meta 500")

    monkeypatch.setattr("app.services.meta_cloud.send_interactive_buttons", boom)
    assert run(bm.send_reminders(w.db, NOW)) == 1
    assert w.sent[0][0] == "template" and w.row()["reminder_wamid"] == "wamid.TPL"


def test_a_held_slot_never_gets_the_booking_is_on_template(w):
    w.window(False)
    w.approve("update")
    w.booking(status="held")
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is False and w.sent == []
    w.window(True)
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is True and w.sent[0][0] == "text"


def test_a_deleted_lead_is_not_used(w):
    w.db.rows("leads")[0]["deleted_at"] = "2026-11-01T00:00:00+00:00"
    w.booking()
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is False and w.sent == []


def test_reminder_is_claimed_before_it_is_sent(w, monkeypatch):
    _two_h(w)
    seen = {}
    real = bm._deliver

    async def spy(db, tenant_id, b, **kw):
        seen["claimed"] = w.row()["reminder_2h_sent_at"]
        return await real(db, tenant_id, b, **kw)

    monkeypatch.setattr(bm, "_deliver", spy)
    run(bm.send_reminders(w.db, NOW))
    assert seen["claimed"]


def test_a_run_that_loses_the_claim_sends_nothing(w, monkeypatch):
    _two_h(w)
    monkeypatch.setattr(bm, "_claim", lambda *a, **k: False)
    assert run(bm.send_reminders(w.db, NOW)) == 0 and w.sent == []


def test_claim_needs_the_booking_still_booked_and_the_column_empty(w):
    b = _two_h(w)
    assert bm._claim(w.db, T1, b, "reminder_2h_sent_at", iso(NOW)) is True
    assert bm._claim(w.db, T1, b, "reminder_2h_sent_at", iso(NOW)) is False  # already taken
    w.row()["status"] = "cancelled"
    w.row()["reminder_2h_sent_at"] = None
    assert bm._claim(w.db, T1, b, "reminder_2h_sent_at", iso(NOW)) is False  # cancelled meanwhile


def test_a_failed_send_gives_the_claim_back(w):
    w.window(False)  # no template: the send fails
    _two_h(w)
    run(bm.send_reminders(w.db, NOW))
    assert w.row()["reminder_2h_sent_at"] is None


def test_an_exception_while_sending_gives_the_claim_back(w, monkeypatch):
    _two_h(w)

    async def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(bm, "_send_reminder", boom)
    assert run(bm.send_reminders(w.db, NOW)) == 0
    assert w.row()["reminder_2h_sent_at"] is None


def test_reminders_go_out_in_start_order(w):
    s1, s2 = NOW + timedelta(hours=2, minutes=10), NOW + timedelta(hours=1, minutes=50)
    w.booking(id="late", number=1, start_at=iso(s1), end_at=iso(s1 + timedelta(hours=1)),
              block_end_at=iso(s1 + timedelta(hours=1)))
    w.db.rows("leads").append({"id": "lead-2", "tenant_id": T1, "phone": "+919000000002", "name": "Zed",
                               "last_inbound_at": iso(NOW - timedelta(hours=1)), "opted_out": False})
    w.booking(id="early", number=2, phone="+919000000002", lead_id="lead-2", start_at=iso(s2),
              end_at=iso(s2 + timedelta(hours=1)), block_end_at=iso(s2 + timedelta(hours=1)))
    run(bm.send_reminders(w.db, NOW))
    assert [s[1] for s in w.sent] == ["+919000000002", PHONE]


# ── review fixes: timing ────────────────────────────────────────────────────

def test_a_moved_booking_under_20_hours_away_gets_no_day_reminder():
    now = ist(23, 10)
    start = now + timedelta(hours=12)
    assert bm.day_reminder_due(_b(start), now)                      # unmoved: catch-up applies
    assert not bm.day_reminder_due(_b(start, moved_count=1), now)
    assert bm.day_reminder_due(_b(now + timedelta(hours=24), moved_count=1), now)  # still 20-28 h: normal


@pytest.mark.parametrize("now_ist,start_ist,due", [
    ((23, 8, 0), (23, 10, 0), True),     # ordinary: 2 h away at 8 AM
    ((23, 22, 0), (24, 0, 0), False),    # 10 PM: quiet
    ((23, 23, 30), (24, 1, 30), False),  # quiet
    ((24, 3, 0), (24, 5, 0), False),     # quiet
    ((24, 6, 50), (24, 9, 0), False),    # 6:50 is quiet even though 2 h 10 m away
    ((24, 7, 0), (24, 9, 0), True),      # 7 AM sharp, exactly 2 h
    ((24, 7, 0), (24, 8, 0), True),      # its moment (6 AM) was quiet: sent at 7 AM, 1 h ahead
    ((24, 7, 0), (24, 7, 40), True),     # 40 min ahead: still more than 30
    ((24, 7, 0), (24, 7, 30), False),    # exactly 30 min: skipped
    ((24, 7, 0), (24, 7, 20), False),
    ((23, 15, 0), (23, 16, 0), False),   # an ordinary booking 1 h away: its moment was not quiet
])
def test_two_hour_reminder_quiet_hours(now_ist, start_ist, due):
    assert bm.two_hour_due(_b(ist(*start_ist)), ist(*now_ist)) is due


def test_two_hour_catch_up_skips_a_booking_made_after_its_moment():
    now, start = ist(24, 7, 5), ist(24, 8, 30)
    assert bm.two_hour_due(_b(start), now)
    assert not bm.two_hour_due(_b(start, created_at=iso(ist(24, 6, 45))), now)


# ── review fixes: phones and codes ──────────────────────────────────────────

@pytest.mark.parametrize("a,b,same", [
    ("+919876543210", "919876543210", True),
    ("+91 98765 43210", "9876543210", True),
    ("+919876543210", "+9876543210", False),      # typed +98 (Iran), not +91
    ("+9876543210", "+9876543210", False),       # cannot be trusted either way
    ("+14155550123", "+14155550123", True),
    ("+14155550123", "+919876543210", False),
    ("", "+919876543210", False),
    (None, None, False),
])
def test_same_phone_compares_full_international_digits(a, b, same):
    assert bm._same_phone(a, b) is same


def test_a_long_message_with_a_code_only_checks_the_phone_quietly(w):
    w.booking(lead_id=None)
    text = "Hi, is BK-0012 still on for Monday afternoon? Also do you do beard trims?"
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, text)) is False
    row = w.row()
    assert row["phone_checked"] is True and row["lead_id"] == "lead-1"
    assert w.sent == []


def test_a_long_message_saying_booking_code_is_a_code_message(w):
    w.booking()
    text = "Hello, I booked online this morning and my booking code is BK-0012, please confirm it for me"
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, text)) is True
    assert "confirmed" in w.sent[0][2]


def test_a_message_of_exactly_forty_characters_still_counts(w):
    w.booking()
    text = "BK-0012 " + "a" * 32  # 40 characters
    assert len(text) == 40
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, text)) is True


def test_the_jobs_run_their_database_calls_off_the_event_loop(w):
    import threading
    main = threading.get_ident()
    seen = []
    real = w.db.table

    def spy(name):
        seen.append(threading.get_ident())
        return real(name)

    w.db.table = spy
    run(bm.release_holds(w.db, NOW))
    run(bm.send_reminders(w.db, NOW))
    assert seen and all(t != main for t in seen)


# ── website bookings: both conditions before "booked" ───────────────────────

def _link(w, **kw):
    fields = dict(status="held", source="link", phone_checked=False, advance_paise=20000, deal_id="d1",
                  hold_until=iso(NOW + timedelta(minutes=10)))
    return w.booking(**{**fields, **kw})


def test_confirm_if_ready_needs_the_advance_and_the_number(w):
    b = _link(w)
    assert run(bm.confirm_if_ready(w.db, T1, b))["status"] == "held"             # neither
    w.paid = True
    assert run(bm.confirm_if_ready(w.db, T1, b))["status"] == "held"             # paid, number unchecked
    assert w.sent == [] and w.bells == []
    w.paid = False
    w.row()["phone_checked"] = True
    assert run(bm.confirm_if_ready(w.db, T1, dict(w.row())))["status"] == "held"  # checked, unpaid
    assert w.sent == [] and w.bells == []


def test_confirm_if_ready_books_tells_and_rings_once(w):
    _link(w, phone_checked=True)
    w.paid = True
    out = run(bm.confirm_if_ready(w.db, T1, dict(w.row())))
    assert out["status"] == "booked" and w.row()["status"] == "booked" and w.row()["hold_until"] is None
    assert len(w.sent) == 1 and "confirmed" in w.sent[0][2]
    assert [b["type"] for b in w.bells] == ["booking_new"] * 3
    assert {b["user"] for b in w.bells} == {"u-owner", "u-mgr", "u-ravi"}
    again = run(bm.confirm_if_ready(w.db, T1, out))  # already booked: nothing more
    assert again["status"] == "booked" and len(w.sent) == 1 and len(w.bells) == 3


def test_losing_the_update_race_sends_and_rings_nothing(w):
    b = _link(w, phone_checked=True)
    w.paid = True
    w.row()["status"] = "cancelled"  # another run got there first
    out = run(bm.confirm_if_ready(w.db, T1, dict(b)))
    assert out["status"] == "cancelled" and w.sent == [] and w.bells == []


def test_staff_made_holds_need_no_phone_check(w):
    w.booking(status="held", source="phone", phone_checked=False, advance_paise=20000)
    w.paid = True
    assert run(bm.confirm_if_ready(w.db, T1, dict(w.row())))["status"] == "booked"


def test_confirm_if_paid_is_the_same_function():
    assert bm.confirm_if_paid is bm.confirm_if_ready


def test_code_on_a_held_booking_with_the_advance_unpaid_replies_with_what_to_do(w):
    _link(w)
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, "BK-0012")) is True
    assert w.row()["phone_checked"] is True and w.row()["status"] == "held"
    assert w.sent[0][0] == "text"
    assert w.sent[0][2] == ("Thanks \u2014 your number is confirmed. Pay the \u20b9200 advance "
                            "on the booking page to keep the time.")
    assert w.bells == []


def test_code_on_a_held_booking_already_paid_books_it_with_one_message(w):
    _link(w)
    w.paid = True
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, "BK-0012")) is True
    assert w.row()["status"] == "booked"
    assert len(w.sent) == 1 and "confirmed for" in w.sent[0][2]
    assert [b["type"] for b in w.bells] == ["booking_new"] * 3


def test_a_long_message_with_the_code_still_confirms_the_number_and_books(w):
    _link(w)
    w.paid = True
    text = "Hi, is BK-0012 still on for Monday afternoon? Also do you do beard trims?"
    assert run(bm.handle_booking_code(w.db, T1, "lead-1", PHONE, text)) is False  # the AI still answers
    assert w.row()["phone_checked"] is True and w.row()["status"] == "booked"


# ── website bookings: nothing goes to an unconfirmed number ─────────────────

@pytest.mark.parametrize("send", [bm.send_confirmation, bm.send_moved, bm.send_cancelled])
def test_no_message_to_an_unchecked_website_number(w, send):
    _link(w, status="booked")
    assert run(send(w.db, T1, "bk-1")) is False and w.sent == []
    w.row()["phone_checked"] = True
    assert run(send(w.db, T1, "bk-1")) is True


def test_other_sources_are_not_held_back(w):
    w.booking(source="phone", phone_checked=False)
    assert run(bm.send_confirmation(w.db, T1, "bk-1")) is True


def test_reminders_skip_an_unchecked_website_booking(w):
    _two_h(w, source="link", phone_checked=False)
    assert run(bm.send_reminders(w.db, NOW)) == 0
    assert w.sent == [] and w.bells == [] and w.row()["call_now_at"] is None
    assert w.row()["reminder_2h_sent_at"] is None


# ── release_holds with the number rule ──────────────────────────────────────

def _late(w, **kw):
    return _link(w, hold_until=iso(NOW - timedelta(minutes=5)), **kw)


def test_paid_but_number_unchecked_is_booked_silently_and_staff_are_told(w):
    _late(w)
    w.paid = True
    assert run(bm.release_holds(w.db, NOW)) == 1
    row = w.row()
    assert row["status"] == "booked" and row["call_now_at"]
    assert w.sent == []
    assert {b["type"] for b in w.bells} == {"booking_call_now"} and len(w.bells) == 3
    assert "Paid but number not confirmed \u2014 call to confirm" in w.bells[0]["message"]


def test_no_advance_due_but_number_unchecked_asks_staff_to_confirm_the_number(w):
    _late(w, advance_paise=0, deal_id=None)
    w.paid = True
    run(bm.release_holds(w.db, NOW))
    assert w.row()["status"] == "booked" and w.sent == []
    assert "Number not confirmed \u2014 call to confirm" in w.bells[0]["message"]
    assert "Paid but" not in w.bells[0]["message"]


def test_paid_and_number_checked_is_booked_with_a_confirmation(w):
    _late(w, phone_checked=True)
    w.paid = True
    run(bm.release_holds(w.db, NOW))
    assert w.row()["status"] == "booked" and "confirmed" in w.sent[0][2]
    assert {b["type"] for b in w.bells} == {"booking_new"}


def test_unpaid_website_hold_is_released_without_messaging_an_unchecked_number(w):
    _late(w)
    run(bm.release_holds(w.db, NOW))
    assert w.row()["status"] == "cancelled" and w.sent == []


def test_unpaid_hold_with_a_checked_number_still_gets_the_cancelled_message(w):
    _late(w, phone_checked=True)
    run(bm.release_holds(w.db, NOW))
    assert w.row()["status"] == "cancelled" and "is cancelled" in w.sent[0][2]


# ── replies are idempotent ──────────────────────────────────────────────────

def test_a_repeated_thumbs_up_gets_one_thank_you(w):
    w.booking(reminder_wamid="wamid.R1", reminder_2h_sent_at=iso(NOW - timedelta(minutes=30)))
    assert run(bm.handle_booking_reaction(w.db, T1, PHONE, "wamid.R1", "\U0001F44D")) is True
    first = w.row()["confirmed_at"]
    assert run(bm.handle_booking_reaction(w.db, T1, PHONE, "wamid.R1", "\U0001F44D")) is True
    assert w.row()["confirmed_at"] == first
    assert [s[2] for s in w.sent].count("Thank you, see you then.") == 1


def test_a_repeated_yes_button_gets_one_thank_you(w):
    w.booking()
    run(bm.handle_booking_button(w.db, T1, PHONE, "bk_yes:bk-1"))
    run(bm.handle_booking_button(w.db, T1, PHONE, "bk_yes:bk-1"))
    assert [s[2] for s in w.sent].count("Thank you, see you then.") == 1


def test_a_yes_to_a_newer_reminder_is_taken_even_after_an_earlier_yes(w):
    w.booking(confirmed_at=iso(NOW - timedelta(hours=20)), reminder_day_sent_at=iso(NOW - timedelta(hours=21)),
              reminder_2h_sent_at=iso(NOW - timedelta(minutes=5)), reminder_wamid="wamid.R2")
    assert run(bm.handle_booking_reaction(w.db, T1, PHONE, "wamid.R2", "\U0001F44D")) is True
    assert _parse_iso(w.row()["confirmed_at"]) > NOW - timedelta(minutes=1)
    assert w.sent[-1][2] == "Thank you, see you then."


def _parse_iso(v):
    return datetime.fromisoformat(v)


# ── customer-supplied text in messages ──────────────────────────────────────

@pytest.mark.parametrize("raw,clean", [
    ("Priya  Raman", "Priya Raman"),
    ("Priya\u200b\u200dRaman", "PriyaRaman"),
    ("Pri\nya\tRa\rman", "Pri ya Ra man"),
    ("\u202eevil\u202c", "evil"),
    ("  \ufeffAsha\x00\x07 ", "Asha"),
    ("a\u2028b\u2029c", "a b c"),
    ("", ""),
    (None, ""),
])
def test_clean_text(raw, clean):
    assert bm.clean_text(raw) == clean


def test_first_name_is_cleaned_and_short():
    assert bm._first_name("\u200b Priya\nRaman") == "Priya"
    assert bm._first_name("\u200b\u202e") == "there"
    assert len(bm._first_name("x" * 500)) == 40


def test_a_name_with_line_breaks_cannot_shape_the_message(w):
    w.booking(customer_name="Priya\n\nCLICK http://evil.example\u200b now")
    run(bm.send_confirmation(w.db, T1, "bk-1"))
    text = w.sent[0][2]
    assert "\n" not in text and "\u200b" not in text and text.startswith("Hi Priya,")


def test_template_values_and_bells_use_the_clean_name(w):
    w.window(False)
    w.approve("update")
    w.booking(customer_name="Priya\u200b\nRaman")
    run(bm.send_confirmation(w.db, T1, "bk-1"))
    assert w.sent[0][3][0]["parameters"][0]["text"] == "Priya"
    assert bm._who({"customer_name": "A\nB\u200b C"}) == "A B C"
