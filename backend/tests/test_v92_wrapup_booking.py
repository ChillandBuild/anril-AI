"""Item 136: "Interested, next step booked" makes a real booking (only when Bookings is set up)."""
import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase
from test_bookings_engine import NOW, T1, ist, make_db  # noqa: F401  (clock fixture comes from the import below)
from test_bookings_engine import clock, msgs  # noqa: F401
from app.services import wrapup_apply as wa
from app.services import wrapup_booking as wb
from app.services.booking_setup import BookingError

SVC = "5e000000-0000-4000-8000-000000000001"
LEAD = "10000000-0000-4000-8000-000000000001"


def run(coro):
    return asyncio.run(coro)


def visit(db, call_id="call-1", at=None, **kw):
    booking = {"service_id": SVC, "resource_id": "any", "start_at": (at or ist("2026-11-24", "10:00")).isoformat()}
    return run(wb.book_visit(db, T1, call_log_id=call_id, lead_id=LEAD, booking=booking, note="wants a cut", user_id="u1", **kw))


def test_options_enabled_only_when_a_service_has_a_column():
    db = make_db()
    out = wb.options(db, T1)
    assert out["enabled"] and {s["name"] for s in out["services"]} == {"Reading", "Cut"}
    assert wb.options(FakeSupabase(), T1) == {"enabled": False, "services": []}


def test_free_days_and_times_come_from_the_bookings_engine():
    db = make_db()
    assert "2026-11-24" in wb.free_days(db, T1, SVC)
    times = wb.free_times(db, T1, SVC, date(2026, 11, 24))
    assert times and {"start_at", "resource_id", "resource_name"} <= set(times[0])
    with pytest.raises(BookingError):
        wb.free_days(db, T1, "not-a-uuid")


def test_book_visit_makes_a_phone_booking_for_the_lead_and_remembers_it(msgs):
    db = make_db()
    db.add("call_logs", id="call-1", tenant_id=T1, lead_id=LEAD)
    booking_id = visit(db)
    row = next(r for r in db.rows("bookings") if r["id"] == booking_id)
    assert (row["source"], row["lead_id"], row["phone"]) == ("phone", LEAD, "+919876543210")
    assert db.rows("call_logs")[0]["booking_id"] == booking_id


def test_second_tap_does_not_book_twice(msgs):
    db = make_db()
    db.add("call_logs", id="call-1", tenant_id=T1, lead_id=LEAD)
    first = visit(db)
    assert visit(db) == first and len(db.rows("bookings")) == 1


def test_a_taken_time_or_same_day_second_booking_is_refused_in_plain_words(msgs):
    db = make_db()
    db.add("call_logs", id="call-1", tenant_id=T1, lead_id=LEAD)
    db.add("call_logs", id="call-2", tenant_id=T1, lead_id=LEAD)
    visit(db)
    with pytest.raises(BookingError):
        visit(db, call_id="call-2", at=ist("2026-11-24", "11:00"))  # same phone, same day
    assert len(db.rows("bookings")) == 1


def test_a_retry_after_the_booking_was_made_reuses_it(msgs):
    db = make_db()
    db.add("call_logs", id="call-1", tenant_id=T1, lead_id=LEAD)
    db.add("call_logs", id="call-2", tenant_id=T1, lead_id=LEAD)   # a different call row: the double-tap guard cannot help
    first = visit(db)
    assert visit(db, call_id="call-2") == first and len(db.rows("bookings")) == 1


def test_a_re_saved_wrapup_with_a_different_time_says_so(msgs):
    db = make_db()
    db.add("call_logs", id="call-1", tenant_id=T1, lead_id=LEAD)
    db.add("call_logs", id="call-2", tenant_id=T1, lead_id=LEAD)
    visit(db)
    with pytest.raises(BookingError) as e:
        visit(db, call_id="call-2", at=ist("2026-11-24", "11:00"))
    assert "already has a visit booked" in e.value.message and len(db.rows("bookings")) == 1


def test_a_lead_without_a_phone_cannot_be_booked(msgs):
    db = make_db()
    db.rows("leads")[0]["phone"] = None
    with pytest.raises(BookingError):
        visit(db)


def test_another_tenants_lead_is_not_found(msgs):
    db = make_db()
    db.rows("leads")[0]["tenant_id"] = "t9"
    with pytest.raises(BookingError):
        visit(db)


@pytest.mark.parametrize("outcome,expect_call", [("interested_booked", True), ("maybe_later", False)])
def test_apply_wrapup_books_only_for_next_step_booked(outcome, expect_call):
    db = FakeSupabase()
    db.add("leads", id="lead-1", tenant_id="t1", phone="+919800000001", assigned_to="c1", call_status="trying",
           do_not_call=False, opted_out=False, converted_at=None, ai_enabled=True, segment="B")
    db.add("call_logs", id="call-1", tenant_id="t1", lead_id="lead-1", caller_id="c1", status="completed",
           duration_seconds=60, provider="telecmi", follow_up_job_id=None, created_at="2026-09-27T08:00:00+00:00")
    book = AsyncMock(return_value="bk-1")
    mocks = {n: MagicMock() for n in ("sync_follow_up_jobs", "cancel_pending_follow_ups", "record_stage_event",
                                      "maybe_assign_lead", "raise_reassign_alert")}
    mocks["get_telecalling_config"] = MagicMock(return_value={"max_call_attempts": 4})
    wrapup = {"manual_status": "connected", "outcome": outcome, "notes": "ok", "next_action_at": datetime(2026, 9, 28, 4, 30, tzinfo=timezone.utc),
              "reason": None, "preferred_language": None, "stop_messages": False, "products": [], "amount_paise": None,
              "booking": {"service_id": SVC, "resource_id": "any", "start_at": "2026-09-28T04:30:00+00:00"}}
    with patch.object(wa, "book_visit", book), patch.multiple(wa, **mocks):
        log = db.rows("call_logs")[0]
        out = run(wa.apply_wrapup(db, tenant_id="t1", user_id="u", caller_id="c1", call_log_id="call-1", log=log,
                                  wrapup=wrapup, log_extra={}, now=datetime(2026, 9, 27, 8, 30, tzinfo=timezone.utc)))
    assert book.await_count == (1 if expect_call else 0)
    assert out.get("booking_id") == ("bk-1" if expect_call else None)


def test_wrapup_booking_endpoints(msgs):
    from fastapi.testclient import TestClient
    from app.dependencies.auth import get_current_user
    from app.dependencies.tenant import get_tenant_and_role
    from app.main import app
    db = make_db()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T1, "role": "caller", "user_id": "u", "caller_id": "c1", "permissions": []}
    try:
        with patch("app.routes.calls.get_supabase", return_value=db):
            c = TestClient(app)
            assert c.get("/api/v1/calls/wrapup-booking").json()["enabled"] is True
            assert "2026-11-24" in c.get(f"/api/v1/calls/wrapup-booking/days?service_id={SVC}").json()["dates"]
            assert c.get(f"/api/v1/calls/wrapup-booking/times?service_id={SVC}&date=2026-11-24").json()["times"]
            assert c.get("/api/v1/calls/wrapup-booking/days?service_id=bad").status_code == 404
            assert c.get(f"/api/v1/calls/wrapup-booking/times?service_id={SVC}&date=xx").status_code in (400, 422)
    finally:
        app.dependency_overrides.clear()
