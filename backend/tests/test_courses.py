"""Courses & batches (services/courses.py, routes/courses.py): seats, the full-batch rule, enrolling with a fee plan,
the waitlist, the demo class and the AI's block."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routes import courses as routes
from app.services import courses as svc
from tests.fake_supabase import _UNIQUE, FakeSupabase

T = "tenant-1"
_UNIQUE["batch_waitlist"] = [("batch_id", "phone")]


@pytest.fixture(autouse=True)
def _fresh():
    svc.clear_cache()


def world(seats=2, fee=900000, status="open"):
    db = FakeSupabase()
    db.add("catalog_items", id="00000000-0000-0000-0000-0000000000c1", tenant_id=T, name="Python", item_type="course", price_paise=0)
    db.add("catalog_items", id="S1", tenant_id=T, name="Haircut", item_type="service")
    db.add("course_batches", id="00000000-0000-0000-0000-0000000000b1", tenant_id=T, course_item_id="00000000-0000-0000-0000-0000000000c1", name="Weekend", starts_on="2026-12-06",
           timing_text="Sat 10-12", mode="both", seats_total=seats, fee_paise=fee, teacher_name="Anu", status=status)
    return db


def enrol_row(db, n, *, paid=None, stage="quoted", status="active", batch="00000000-0000-0000-0000-0000000000b1"):
    db.add("leads", id=f"L{n}", tenant_id=T, name=f"S{n}", phone=f"+91900000000{n}")
    db.add("deals", id=f"D{n}", tenant_id=T, lead_id=f"L{n}", deal_number=n, stage=stage, total_paise=900000,
           paid_paise=paid or 0)
    db.add("batch_enrolments", id=f"00000000-0000-0000-0000-0000000000e{n}", tenant_id=T, batch_id=batch, lead_id=f"L{n}", deal_id=f"D{n}",
           status=status, phone=f"+91900000000{n}")


# ── seats ────────────────────────────────────────────────────────────────────────

def test_seats_filled_are_paid_or_won_orders_only():
    db = world(seats=5)
    enrol_row(db, 1, paid=300000, stage="awaiting_payment")
    enrol_row(db, 2, stage="won", paid=900000)
    enrol_row(db, 3)                                   # enrolled, nothing paid yet
    enrol_row(db, 4, stage="lost")                     # cancelled order
    enrol_row(db, 5, paid=100, status="dropped")       # dropped
    c = svc.seat_counts(db, T, ["00000000-0000-0000-0000-0000000000b1"])["00000000-0000-0000-0000-0000000000b1"]
    assert (c["filled"], c["waiting"]) == (2, 1)
    s = svc.shape_batch(db.rows("course_batches")[0], c, show_money=True)
    assert s["seats_left"] == 3 and s["status"] == "open"


def test_a_batch_is_full_when_paid_plus_waiting_reach_the_seats_and_closed_stays_closed():
    db = world(seats=2)
    enrol_row(db, 1, paid=1)
    enrol_row(db, 2)
    detail = svc.list_courses(db, T, show_money=True)[0]["batches"][0]
    assert detail["status"] == "full" and detail["seats_left"] == 1
    db.rows("course_batches")[0]["status"] = "closed"
    assert svc.list_courses(db, T, show_money=True)[0]["batches"][0]["status"] == "closed"


def test_money_is_left_out_without_deals_view_and_services_are_not_courses():
    db = world()
    out = svc.list_courses(db, T, show_money=False)
    assert [c["name"] for c in out] == ["Python"]
    assert "fee_paise" not in out[0]["batches"][0] and "price_paise" not in out[0]


# ── courses and batches ──────────────────────────────────────────────────────────

def test_create_course_and_batch_validate_plainly():
    db = FakeSupabase()
    item = svc.create_course(db, T, {"name": "  Tally  ", "price_paise": 500000})
    assert db.rows("catalog_items")[0]["item_type"] == "course" and item["name"] == "Tally"
    with pytest.raises(svc.CourseError):
        svc.create_course(db, T, {"name": " "})
    b = svc.create_batch(db, T, item["id"], {"name": "Morning", "starts_on": "2026-12-06", "mode": "online",
                                             "seats_total": 12, "fee_paise": 700000}, allow_fee=True)
    assert b["seats_total"] == 12 and b["fee_paise"] == 700000 and b["tenant_id"] == T
    with pytest.raises(svc.CourseError, match="Mode"):
        svc.create_batch(db, T, item["id"], {"name": "x", "mode": "sideways"}, allow_fee=True)
    with pytest.raises(svc.CourseError, match="date"):
        svc.create_batch(db, T, item["id"], {"name": "x", "starts_on": "soon"}, allow_fee=True)
    # a person without money access cannot set the fee
    b2 = svc.create_batch(db, T, item["id"], {"name": "Eve", "fee_paise": 1}, allow_fee=False)
    assert not b2.get("fee_paise")


def test_other_tenants_course_and_batch_are_not_found():
    db = world()
    with pytest.raises(svc.CourseError) as e:
        svc.create_batch(db, "tenant-2", "00000000-0000-0000-0000-0000000000c1", {"name": "x"}, allow_fee=True)
    assert e.value.status_code == 404
    with pytest.raises(svc.CourseError):
        svc.get_batch(db, "tenant-2", "00000000-0000-0000-0000-0000000000b1")
    with pytest.raises(svc.CourseError):
        svc.get_batch(db, T, "not-a-uuid")


def test_next_open_batch_skips_full_and_closed_ones():
    db = world(seats=1)
    enrol_row(db, 1, paid=1)
    db.add("course_batches", id="00000000-0000-0000-0000-0000000000b2", tenant_id=T, course_item_id="00000000-0000-0000-0000-0000000000c1", name="Closed", starts_on="2026-12-10", seats_total=5, status="closed")
    assert svc.next_open_batch(db, T, "00000000-0000-0000-0000-0000000000b1") is None
    db.add("course_batches", id="00000000-0000-0000-0000-0000000000b3", tenant_id=T, course_item_id="00000000-0000-0000-0000-0000000000c1", name="Evening", starts_on="2026-12-20", seats_total=5, fee_paise=1, status="open")
    assert svc.next_open_batch(db, T, "00000000-0000-0000-0000-0000000000b1")["id"] == "00000000-0000-0000-0000-0000000000b3"


# ── enrol, drop, waitlist ────────────────────────────────────────────────────────

async def _create_deal(tenant_id, lead_id, lines, source, stage="quoted", **kw):
    db = kw["db"]
    deal = db.add("deals", tenant_id=tenant_id, lead_id=lead_id, deal_number=len(db.rows("deals")) + 1, stage="quoted",
                  total_paise=lines[0]["unit_price_paise"], paid_paise=0)
    return {"deal": deal, "items": []}


def enrol(db, deal_maker=None, **kw):
    kw.setdefault("phone", "98765 43210")
    kw.setdefault("name", "Ravi")
    with patch("app.services.deals.create_deal", deal_maker or _create_deal), \
            patch("app.services.inbound_lead.create_inbound_lead", return_value="L-new") as lead:
        db.add("leads", id="L-new", tenant_id=T, phone="+919876543210")
        out = asyncio.run(svc.enrol_student(db, T, "00000000-0000-0000-0000-0000000000b1", **kw))
    return out, lead


def test_enrol_makes_the_order_the_enrolment_and_a_one_part_plan():
    db = world()
    out, lead = enrol(db, parent_phone="98111 11111")
    assert lead.call_args.args[:3] == (T, "+919876543210", "manual")
    e = db.rows("batch_enrolments")[0]
    assert e["deal_id"] == out["deal_id"] and e["parent_phone"] == "+919811111111" and e["status"] == "active"
    plan = db.rows("fee_plans")[0]
    assert plan["parts"] == [{"due_on": "2026-12-06", "amount_paise": 900000}]
    assert db.rows("deals")[0]["total_paise"] == 900000


def test_enrol_with_three_instalments_adds_up_to_the_fee():
    db = world()
    enrol(db, instalments=3, first_due_on="2026-12-01")
    parts = db.rows("fee_plans")[0]["parts"]
    assert len(parts) == 3 and sum(p["amount_paise"] for p in parts) == 900000


def test_enrol_refuses_a_full_batch_a_missing_fee_a_repeat_and_a_bad_plan():
    db = world(seats=1)
    enrol_row(db, 1, paid=1)
    with pytest.raises(svc.CourseError, match="full") as e:
        enrol(db)
    assert e.value.status_code == 409
    assert not db.rows("fee_plans")
    no_fee = world(fee=0)
    with pytest.raises(svc.CourseError, match="fee"):
        enrol(no_fee)
    again = world()
    enrol(again)
    with pytest.raises(svc.CourseError, match="already"):
        enrol(again)
    bad = world()
    with patch("app.services.deals.mark_lost") as lost, pytest.raises(svc.CourseError, match="add up"):
        enrol(bad, parts=[{"due_on": "2026-12-06", "amount_paise": 5}])
    lost.assert_called_once()
    assert bad.rows("batch_enrolments") == []


def test_dropping_frees_the_seat_and_cancels_only_an_unpaid_order():
    db = world()
    enrol_row(db, 1)
    enrol_row(db, 2, paid=300000, stage="awaiting_payment")
    with patch("app.services.deals.mark_lost", return_value={"deal": {}}) as lost:
        assert svc.drop_enrolment(db, T, "00000000-0000-0000-0000-0000000000e1")["order_cancelled"] is True
        assert svc.drop_enrolment(db, T, "00000000-0000-0000-0000-0000000000e2")["order_cancelled"] is False
    lost.assert_called_once()
    assert {e["id"]: e["status"] for e in db.rows("batch_enrolments")} == {"00000000-0000-0000-0000-0000000000e1": "dropped", "00000000-0000-0000-0000-0000000000e2": "dropped"}
    with pytest.raises(svc.CourseError):
        svc.drop_enrolment(db, T, "00000000-0000-0000-0000-0000000000e1")


def test_waitlist_is_once_per_number_and_listed_on_the_batch():
    db = world()
    a = svc.join_waitlist(db, T, "00000000-0000-0000-0000-0000000000b1", "98765 43210", "Ravi")
    b = svc.join_waitlist(db, T, "00000000-0000-0000-0000-0000000000b1", "+919876543210")
    assert a["id"] == b["id"] and len(db.rows("batch_waitlist")) == 1
    with pytest.raises(svc.CourseError):
        svc.join_waitlist(db, T, "00000000-0000-0000-0000-0000000000b1", "abc")
    detail = svc.batch_detail(db, T, "00000000-0000-0000-0000-0000000000b1", show_money=False)
    assert detail["waitlist"][0]["phone"] == "+919876543210" and detail["batch"]["waitlist_count"] == 1
    svc.leave_waitlist(db, T, a["id"])
    assert db.rows("batch_waitlist") == []


def test_a_telecaller_sees_only_their_own_students_and_no_waitlist():
    db = world(seats=9)
    enrol_row(db, 1, paid=1)
    enrol_row(db, 2, paid=1)
    db.rows("leads")[0]["assigned_to"] = "caller-1"
    svc.join_waitlist(db, T, "00000000-0000-0000-0000-0000000000b1", "9876543210")
    d = svc.batch_detail(db, T, "00000000-0000-0000-0000-0000000000b1", show_money=False, caller_id="caller-1")
    assert [s["id"] for s in d["students"]] == ["00000000-0000-0000-0000-0000000000e1"] and d["waitlist"] == [] and "fee_plan" not in d["students"][0]


# ── demo class and the AI block ──────────────────────────────────────────────────

def test_demo_class_is_made_once_through_bookings():
    db = FakeSupabase()
    db.add("booking_resources", id="R1", tenant_id=T, name="Anu", active=True)
    with patch("app.services.booking_setup.create_service", return_value={"id": "SV1"}) as create, \
            patch("app.services.booking_setup.list_resources", return_value=[{"id": "R1"}]):
        first = svc.ensure_demo_service(db, T)
        assert first == {"service_id": "SV1", "created": True, "has_staff": True}
        assert create.call_args.args[2]["name"] == "Demo class" and create.call_args.args[2]["price_paise"] == 0
        db.add("booking_services", id="SV1", tenant_id=T, name="Demo class", active=True)
        assert svc.ensure_demo_service(db, T) == {"service_id": "SV1", "created": False}
        assert create.call_count == 1


def test_prompt_block_lists_batches_with_the_rules_and_is_empty_without_any():
    assert svc.prompt_block(FakeSupabase(), T) == ""
    svc.clear_cache()
    db = world(seats=2, fee=1250000)
    enrol_row(db, 1, paid=1)
    db.add("course_batches", id="00000000-0000-0000-0000-0000000000b9", tenant_id=T, course_item_id="00000000-0000-0000-0000-0000000000c1", name="Old", status="closed", seats_total=5)
    block = svc.prompt_block(db, T)
    assert "Python - Weekend" in block and "starts 6 Dec 2026" in block and "Sat 10-12" in block
    assert "1 seats left" in block and "₹12,500" in block and "teacher Anu" in block and "Old" not in block
    assert "next open batch" in block and "demo class" not in block.lower()
    db.add("booking_services", id="SV1", tenant_id=T, name="Demo class", active=True, sort=0)
    db.add("booking_settings", tenant_id=T, link_token="tok123", link_on=True)
    svc.clear_cache()
    assert "free demo class" in svc.prompt_block(db, T) and "/book/tok123" in svc.prompt_block(db, T)


def test_prompt_block_says_full_and_never_raises():
    db = world(seats=1)
    enrol_row(db, 1, paid=1)
    assert "FULL" in svc.prompt_block(db, T)
    svc.clear_cache()

    class Broken:
        def table(self, *_):
            raise RuntimeError("no such table")
    assert svc.prompt_block(Broken(), T) == ""


# ── routes ───────────────────────────────────────────────────────────────────────

def test_list_route_strips_money_without_deals_view():
    db = world()
    with patch.object(routes, "get_supabase", return_value=db):
        plain = routes.list_courses({"tenant_id": T, "role": "staff", "permissions": ["catalog.view"]})
        owner = routes.list_courses({"tenant_id": T, "role": "owner"})
    assert plain["can_see_money"] is False and "fee_paise" not in plain["courses"][0]["batches"][0]
    assert owner["courses"][0]["batches"][0]["fee_paise"] == 900000


def test_route_turns_a_plain_error_into_an_http_error():
    db = world()
    with patch.object(routes, "get_supabase", return_value=db):
        with pytest.raises(HTTPException) as e:
            routes.batch_detail("00000000-0000-0000-0000-000000000000", {"tenant_id": T, "role": "owner"})
    assert e.value.status_code == 404 and e.value.detail == "Batch not found"


# ── review fixes ─────────────────────────────────────────────────────────────────

BATCH = "00000000-0000-0000-0000-0000000000b1"


def test_enrol_splits_the_orders_real_total_when_gst_sits_on_top_of_the_fee():
    # 3. a GST-exclusive business: the order is fee + 18%, the plan must add up to the ORDER, not the batch fee.
    async def with_gst(tenant_id, lead_id, lines, source, stage="quoted", **kw):
        db = kw["db"]
        deal = db.add("deals", tenant_id=tenant_id, lead_id=lead_id, deal_number=1, stage="quoted",
                      total_paise=int(lines[0]["unit_price_paise"] * 1.18), paid_paise=0)
        return {"deal": deal, "items": []}

    db = world(fee=900000)
    enrol(db, deal_maker=with_gst, instalments=3, first_due_on="2026-12-01")
    parts = db.rows("fee_plans")[0]["parts"]
    assert sum(p["amount_paise"] for p in parts) == 1062000 and len(parts) == 3
    assert len(db.rows("batch_enrolments")) == 1


def test_two_people_racing_for_the_last_seat_only_one_keeps_it():
    # 5. both passed the seats check; after the insert the later one is over the seats and is rolled back.
    db = world(seats=1)
    enrol_row(db, 1)  # already holds the only seat (enrolled, unpaid)
    zeros = {BATCH: {"filled": 0, "waiting": 0, "waitlist": 0}}
    with patch.object(svc, "seat_counts", return_value=zeros), \
            patch("app.services.deals.mark_lost") as lost, pytest.raises(svc.CourseError, match="just filled up") as e:
        enrol(db)
    assert e.value.status_code == 409
    lost.assert_called_once()
    assert [r["lead_id"] for r in db.rows("batch_enrolments")] == ["L1"] and db.rows("fee_plans") == []


def test_the_earlier_enrolment_keeps_its_seat_when_a_later_one_is_checked():
    db = world(seats=1)
    enrol_row(db, 1)
    batch = db.rows("course_batches")[0]
    assert svc._over_seats(db, T, batch, "00000000-0000-0000-0000-0000000000e1") is False
    enrol_row(db, 2)
    assert svc._over_seats(db, T, batch, "00000000-0000-0000-0000-0000000000e2") is True


def test_enrolling_twice_in_a_race_says_already_in_this_batch_not_a_server_error():
    # 12. the unique index fires on the insert (the earlier duplicate check did not see the other row).
    _UNIQUE["batch_enrolments"] = [("batch_id", "phone")]
    try:
        db = world(seats=5)
        enrol_row(db, 1)
        db.rows("batch_enrolments")[0]["phone"] = "+919876543210"
        with patch("app.services.deals.mark_lost") as lost, pytest.raises(svc.CourseError, match="already") as e:
            enrol(db)
    finally:
        _UNIQUE.pop("batch_enrolments", None)
    assert e.value.status_code == 409
    lost.assert_called_once()


def test_dropping_a_student_who_paid_keeps_the_order_and_reports_the_money():
    # 6. paid money: never cancel; say how much so the page can tell the owner to refund from the order.
    db = world()
    enrol_row(db, 1, paid=300000, stage="awaiting_payment")
    with patch("app.services.deals.mark_lost") as lost:
        out = svc.drop_enrolment(db, T, "00000000-0000-0000-0000-0000000000e1")
    assert out == {"dropped": True, "order_cancelled": False, "paid_paise": 300000}
    lost.assert_not_called()


def test_drop_reads_the_order_again_right_before_cancelling():
    db = world()
    enrol_row(db, 1)  # unpaid when the page was opened
    original = svc.drop_enrolment

    # money lands between the page load and the drop
    db.rows("deals")[0]["paid_paise"] = 100000
    with patch("app.services.deals.mark_lost") as lost:
        out = original(db, T, "00000000-0000-0000-0000-0000000000e1")
    assert out["order_cancelled"] is False and out["paid_paise"] == 100000
    lost.assert_not_called()


def test_a_caller_without_a_caller_id_sees_no_students():
    # 8. fail closed: role caller and no caller_id is an empty id, which matches no lead.
    assert routes._caller({"role": "caller", "caller_id": None}) == ""
    assert routes._caller({"role": "caller", "caller_id": "c-1"}) == "c-1"
    assert routes._caller({"role": "owner"}) is None
    db = world(seats=9)
    enrol_row(db, 1, paid=1)
    db.rows("leads")[0]["assigned_to"] = "caller-1"
    d = svc.batch_detail(db, T, BATCH, show_money=False, caller_id=routes._caller({"role": "caller", "caller_id": None}))
    assert d["students"] == [] and d["waitlist"] == []
    assert len(svc.batch_detail(db, T, BATCH, show_money=False)["students"]) == 1


def test_seat_counts_reads_every_enrolment_past_the_1000_row_cap():
    db = world(seats=5000)
    for n in range(1, 1201):
        db.add("batch_enrolments", id=f"e{n}", tenant_id=T, batch_id=BATCH, lead_id=f"L{n}", deal_id=None,
               status="active", phone=f"+91{n}")
    assert svc.seat_counts(db, T, [BATCH])[BATCH]["waiting"] == 1200
