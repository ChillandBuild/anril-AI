"""Bookings engine (v9.2 #19): slot maths, rules, one-per-day / overlap error mapping, "any" column,
create / move / cancel / came / no-show and the lead mirror. The DB is FakeSupabase plus the three
constraints the real table has; WhatsApp messages and money go through mocks."""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_supabase import FakeSupabase, _Query
from app.services import booking_setup as bsetup
from app.services import bookings as bk
from app.services.booking_setup import BookingError

T1, T2 = "t1", "t2"
IST = bk.IST
# Monday 23 Nov 2026, 09:30 IST
NOW = datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc)
HOURS = {str(d): [["10:00", "13:00"], ["16:00", "20:00"]] for d in range(7)}


def ist(day: str, hhmm: str) -> datetime:
    """A UTC datetime for an Indian-time wall clock."""
    h, m = hhmm.split(":")
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, int(h), int(m), tzinfo=IST).astimezone(timezone.utc)


# ── a FakeSupabase that enforces the bookings table's three constraints ─────

class _BookingsQuery(_Query):
    def execute(self):
        if self.name == "bookings" and self.op in ("insert", "update"):
            rows = self.db.rows("bookings")
            if self.op == "insert":
                candidates = [(dict(self.payload), None)]
            else:
                candidates = [({**r, **self.payload}, r) for r in self._matching()]
            for new, old in candidates:
                self._check(new, old, [r for r in rows if r is not old])
        return super().execute()

    @staticmethod
    def _check(new: dict, old, others: list[dict]) -> None:
        live = ("held", "booked", "came")
        if new.get("status", "booked") in live:
            for r in others:
                if r.get("status") not in live:
                    continue
                if r["resource_id"] == new["resource_id"] and bk.parse_ts(r["start_at"]) < bk.parse_ts(new["block_end_at"]) \
                        and bk.parse_ts(new["start_at"]) < bk.parse_ts(r["block_end_at"]):
                    raise Exception('{"code":"23P01","message":"conflicting key value violates exclusion constraint \\"bookings_no_overlap\\""}')
                if new.get("day_guard", True) and r.get("day_guard", True) and \
                        (r["tenant_id"], r["phone"], r["booking_date"]) == (new["tenant_id"], new["phone"], new["booking_date"]):
                    raise Exception('{"code":"23505","message":"duplicate key value violates unique constraint \\"uq_bookings_phone_day\\""}')
        for r in others:
            if r["tenant_id"] == new["tenant_id"] and r["number"] == new["number"]:
                raise Exception('{"code":"23505","message":"duplicate key value violates unique constraint \\"uq_bookings_number\\""}')


class BookingsDB(FakeSupabase):
    def table(self, name):
        return _BookingsQuery(self, name) if name == "bookings" else _Query(self, name)


def make_db() -> BookingsDB:
    d = BookingsDB()
    d.add("tenants", id=T1, name="Glow Salon")
    d.add("leads", id="10000000-0000-4000-8000-000000000001", tenant_id=T1, name="Priya", phone="+919876543210", booked_at=None, booked_for=None)
    d.add("booking_resources", id="2e000000-0000-4000-8000-000000000001", tenant_id=T1, name="Ravi", kind="person", user_id="u-ravi", hours=HOURS,
          active=True, sort=0)
    d.add("booking_resources", id="2e000000-0000-4000-8000-000000000002", tenant_id=T1, name="Chair 2", kind="chair", user_id=None,
          hours={str(i): [["10:00", "13:00"]] for i in range(7)}, active=True, sort=1)
    d.add("booking_services", id="5e000000-0000-4000-8000-000000000001", tenant_id=T1, name="Reading", duration_min=30, price_paise=50000,
          advance_paise=0, gap_after_min=0, active=True, sort=0, catalog_item_id="c0000000-0000-4000-8000-000000000001")
    d.add("booking_services", id="5e000000-0000-4000-8000-000000000002", tenant_id=T1, name="Cut", duration_min=60, price_paise=80000,
          advance_paise=20000, gap_after_min=15, active=True, sort=1, catalog_item_id="c0000000-0000-4000-8000-000000000002")
    for s in ("5e000000-0000-4000-8000-000000000001", "5e000000-0000-4000-8000-000000000002"):
        for r in ("2e000000-0000-4000-8000-000000000001", "2e000000-0000-4000-8000-000000000002"):
            d.add("booking_service_resources", service_id=s, resource_id=r, tenant_id=T1)
    d.add("phone_numbers", tenant_id=T1, number="+919000000001", role="primary", status="active")
    return d


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(bk, "_now", lambda: NOW)
    monkeypatch.setattr(bsetup, "now_utc", lambda: NOW)


@pytest.fixture
def msgs(monkeypatch):
    """b0000000-0000-4000-8000-000000000002's WhatsApp messages, the bell and the lead helper: recorded, never sent."""
    from app.services import booking_messages as bm
    m = MagicMock()
    m.send_confirmation = AsyncMock(return_value=True)
    m.send_moved = AsyncMock(return_value=True)
    m.send_cancelled = AsyncMock(return_value=True)
    monkeypatch.setattr(bm, "send_confirmation", m.send_confirmation)
    monkeypatch.setattr(bm, "send_moved", m.send_moved)
    monkeypatch.setattr(bm, "send_cancelled", m.send_cancelled)
    monkeypatch.setattr(bm, "ring_bell", m.ring_bell)
    monkeypatch.setattr("app.services.inbound_lead.create_inbound_lead", lambda *a, **k: "10000000-0000-4000-8000-000000000001")
    return m


def run(coro):
    return asyncio.run(coro)


def book(db, **kw):
    args = dict(service_id="5e000000-0000-4000-8000-000000000001", resource_id="2e000000-0000-4000-8000-000000000001", start_at=ist("2026-11-24", "10:00").isoformat(),
                phone="9876543210", customer_name="Priya", source="phone")
    args.update(kw)
    return run(bk.create_booking(db, T1, **args))


# ═══════════════════════════ pure slot maths ═══════════════════════════

SERVICE = {"duration_min": 30, "gap_after_min": 0}
MONDAY = date(2026, 11, 23)
EARLY = datetime(2026, 1, 1, tzinfo=timezone.utc)


def starts(slots):
    return [s.astimezone(IST).strftime("%H:%M") for s in slots]


def test_slots_stay_inside_working_blocks():
    got = starts(bk.slots_for_day(HOURS, SERVICE, MONDAY, earliest=EARLY, live=[]))
    assert got[:3] == ["10:00", "10:15", "10:30"]
    assert "12:30" in got and "12:45" not in got          # 12:30 + 30 min ends exactly at 13:00
    assert not any("13:00" <= t < "16:00" for t in got)    # the break between the two blocks
    assert got[-1] == "19:30"


def test_long_service_last_start_is_end_minus_duration():
    got = starts(bk.slots_for_day({"0": [["10:00", "13:00"]]}, {"duration_min": 60, "gap_after_min": 0}, MONDAY,
                                   earliest=EARLY, live=[]))
    assert got[-1] == "12:00"


def test_day_off_has_no_slots():
    assert bk.slots_for_day({"1": [["10:00", "13:00"]]}, SERVICE, MONDAY, earliest=EARLY, live=[]) == []
    assert bk.slots_for_day({}, SERVICE, MONDAY, earliest=EARLY, live=[]) == []


def test_leave_day_has_no_slots():
    assert bk.slots_for_day(HOURS, SERVICE, MONDAY, earliest=EARLY, live=[], on_leave=True) == []


def test_gap_after_is_kept_free():
    # A 30-minute booking at 11:00 that holds 15 minutes after it: it blocks 11:00-11:45.
    live = [(ist("2026-11-23", "11:00"), ist("2026-11-23", "11:45"))]
    got = starts(bk.slots_for_day({"0": [["10:00", "13:00"]]}, {"duration_min": 30, "gap_after_min": 15}, MONDAY,
                                  earliest=EARLY, live=live))
    # the new booking's own 15-minute gap must also stay clear of the 11:00 booking
    assert "10:00" in got and "10:15" in got
    assert "10:30" not in got      # 10:30 + 30 + 15 = 11:15 touches 11:00
    assert "11:30" not in got and "11:45" in got


def test_a_slot_ending_exactly_when_a_booking_starts_is_fine():
    live = [(ist("2026-11-23", "11:00"), ist("2026-11-23", "11:30"))]
    got = starts(bk.slots_for_day({"0": [["10:00", "13:00"]]}, SERVICE, MONDAY, earliest=EARLY, live=live))
    assert "10:30" in got and "10:45" not in got and "11:30" in got


def test_earliest_cuts_off_the_past_and_too_soon():
    got = starts(bk.slots_for_day(HOURS, SERVICE, MONDAY, earliest=ist("2026-11-23", "10:30"), live=[]))
    assert got[0] == "10:30"


def test_hours_not_on_the_grid_start_on_the_next_quarter():
    got = starts(bk.slots_for_day({"0": [["10:10", "11:00"]]}, SERVICE, MONDAY, earliest=EARLY, live=[]))
    assert got == ["10:15", "10:30"]


def test_indian_time_decides_the_day():
    late = datetime(2026, 11, 23, 19, 0, tzinfo=timezone.utc)   # 00:30 IST on the 24th
    assert bk.ist_date(late) == date(2026, 11, 24)
    assert bk.ist_date(datetime(2026, 11, 23, 18, 29, tzinfo=timezone.utc)) == date(2026, 11, 23)  # 23:59 IST
    assert bk.parse_ts("2026-11-24T10:00:00").isoformat() == "2026-11-24T04:30:00+00:00"   # no zone = IST
    assert bk.parse_ts("2026-11-24T10:00:00Z").isoformat() == "2026-11-24T10:00:00+00:00"
    with pytest.raises(BookingError):
        bk.parse_ts("tomorrow")


def test_free_ranges_subtract_bookings_and_the_past():
    live = [(ist("2026-11-23", "11:00"), ist("2026-11-23", "12:00"))]
    got = [(a.astimezone(IST).strftime("%H:%M"), b.astimezone(IST).strftime("%H:%M")) for a, b in
           bk.free_ranges({"0": [["10:00", "13:00"]]}, MONDAY, earliest=ist("2026-11-23", "10:30"), live=live)]
    assert got == [("10:30", "11:00"), ("12:00", "13:00")]
    assert bk.free_ranges(HOURS, MONDAY, earliest=EARLY, live=[], on_leave=True) == []


def test_booking_codes():
    assert bk.code_for(12) == "BK-0012"
    assert bk.floor_step(datetime(2026, 11, 23, 4, 7, tzinfo=timezone.utc)).astimezone(IST).strftime("%H:%M") == "09:30"


# ── hours validation ────────────────────────────────────────────────────────

def test_hours_validation():
    ok = bsetup.normalize_hours({"0": [["09:00", "13:00"], ["16:00", "20:00"]], "1": []})
    assert ok == {"0": [["09:00", "13:00"], ["16:00", "20:00"]]}
    for bad in ({"0": [["10:00", "10:00"]]}, {"0": [["12:00", "10:00"]]},
                {"0": [["10:00", "14:00"], ["13:00", "15:00"]]},
                {"0": [["10:00", "11:00"], ["12:00", "13:00"], ["14:00", "15:00"]]},
                {"7": [["10:00", "11:00"]]}, {"0": [["10am", "11:00"]]}, {"0": "10-11"}, []):
        with pytest.raises(BookingError):
            bsetup.normalize_hours(bad)


# ═══════════════════════════ rules: window and free times ═══════════════════════════

RULES = {"days_ahead": 14, "min_notice_min": 60, "cancel_cutoff_min": 180, "one_per_day": True, "no_show_limit": 2}
SVC = {"id": "5e000000-0000-4000-8000-000000000001", "duration_min": 30, "gap_after_min": 0, "resource_ids": ["2e000000-0000-4000-8000-000000000001", "2e000000-0000-4000-8000-000000000002"]}


def test_customers_cannot_book_inside_the_notice_time():
    db = make_db()
    today = date(2026, 11, 23)  # now = 09:30 IST, notice 60 min -> first start 10:30
    times = bk.times_for_day(db, T1, SVC, "2e000000-0000-4000-8000-000000000001", today, RULES, staff=False)
    assert bk.parse_ts(times[0]["start_at"]) == ist("2026-11-23", "10:30")


def test_staff_can_book_from_the_current_quarter_hour():
    db = make_db()
    times = bk.times_for_day(db, T1, SVC, "2e000000-0000-4000-8000-000000000001", date(2026, 11, 23), RULES, staff=True)
    assert bk.parse_ts(times[0]["start_at"]) == ist("2026-11-23", "10:00")


def test_days_ahead_limit_for_customers_not_for_staff():
    db = make_db()
    last_ok, too_far = date(2026, 11, 23) + timedelta(days=14), date(2026, 11, 23) + timedelta(days=15)
    assert bk.times_for_day(db, T1, SVC, "2e000000-0000-4000-8000-000000000001", last_ok, RULES, staff=False)
    assert bk.times_for_day(db, T1, SVC, "2e000000-0000-4000-8000-000000000001", too_far, RULES, staff=False) == []
    assert bk.times_for_day(db, T1, SVC, "2e000000-0000-4000-8000-000000000001", too_far, RULES, staff=True)


def test_free_days_lists_only_days_with_times_and_skips_leave():
    db = make_db()
    db.add("booking_leave", tenant_id=T1, resource_id="2e000000-0000-4000-8000-000000000001", from_date="2026-11-25", to_date="2026-11-26")
    db.add("booking_leave", tenant_id=T1, resource_id="2e000000-0000-4000-8000-000000000002", from_date="2026-11-25", to_date="2026-11-26")
    days = bk.days_with_times(db, T1, SVC, "any", RULES, staff=False)
    assert "2026-11-24" in days and "2026-11-25" not in days and "2026-11-26" not in days
    assert days[-1] == "2026-12-07" and "2026-12-08" not in days


def test_any_lists_each_time_once_with_the_first_free_column():
    db = make_db()
    db.add("bookings", id="b0000000-0000-4000-8000-000000000000", tenant_id=T1, number=1, phone="+911", service_id="5e000000-0000-4000-8000-000000000001", resource_id="2e000000-0000-4000-8000-000000000001",
           start_at=bk.iso(ist("2026-11-24", "10:00")), end_at=bk.iso(ist("2026-11-24", "10:30")),
           block_end_at=bk.iso(ist("2026-11-24", "10:30")), booking_date="2026-11-24", status="booked")
    times = {t["start_at"]: t for t in bk.times_for_day(db, T1, SVC, "any", date(2026, 11, 24), RULES, staff=False)}
    assert times[bk.iso(ist("2026-11-24", "10:00"))]["resource_id"] == "2e000000-0000-4000-8000-000000000002"   # Ravi is busy, Chair 2 is free
    assert times[bk.iso(ist("2026-11-24", "10:30"))]["resource_id"] == "2e000000-0000-4000-8000-000000000001"
    assert len(times) == len(set(times))


def test_a_column_that_does_not_do_the_service_is_not_offered():
    db = make_db()
    svc = {**SVC, "resource_ids": ["2e000000-0000-4000-8000-000000000002"]}
    assert {t["resource_id"] for t in bk.times_for_day(db, T1, svc, "any", date(2026, 11, 24), RULES, staff=False)} == {"2e000000-0000-4000-8000-000000000002"}
    assert bk.times_for_day(db, T1, svc, "2e000000-0000-4000-8000-000000000001", date(2026, 11, 24), RULES, staff=False) == []


# ═══════════════════════════ who sees which column ═══════════════════════════

RES = [{"id": "2e000000-0000-4000-8000-000000000001", "user_id": "u-ravi"}, {"id": "2e000000-0000-4000-8000-000000000002", "user_id": None}]


def _ctx(perms, uid="u9", role="staff"):
    return {"tenant_id": T1, "user_id": uid, "role": role, "permissions": perms}


def test_visibility_rules():
    assert [r["id"] for r in bk.visible_resources(_ctx([], role="owner"), RES)] == ["2e000000-0000-4000-8000-000000000001", "2e000000-0000-4000-8000-000000000002"]
    assert [r["id"] for r in bk.visible_resources(_ctx(["bookings.manage"]), RES)] == ["2e000000-0000-4000-8000-000000000001", "2e000000-0000-4000-8000-000000000002"]
    assert [r["id"] for r in bk.visible_resources(_ctx(["bookings.view"], uid="u-ravi"), RES)] == ["2e000000-0000-4000-8000-000000000001"]
    assert [r["id"] for r in bk.visible_resources(_ctx(["bookings.view"]), RES)] == ["2e000000-0000-4000-8000-000000000001", "2e000000-0000-4000-8000-000000000002"]   # no column: all, read-only
    assert [r["id"] for r in bk.visible_resources(_ctx(["bookings.manage"], uid="u-ravi"), RES)] == ["2e000000-0000-4000-8000-000000000001", "2e000000-0000-4000-8000-000000000002"]
    assert bk.only_own_column(_ctx(["bookings.view"], uid="u-ravi"), RES) == "2e000000-0000-4000-8000-000000000001"
    assert bk.only_own_column(_ctx(["bookings.view"]), RES) is None
    assert bk.can_act_on(_ctx(["bookings.view"], uid="u-ravi"), RES[0])
    assert not bk.can_act_on(_ctx(["bookings.view"], uid="u-ravi"), RES[1])
    assert bk.can_act_on(_ctx(["bookings.manage"]), RES[1])


# ═══════════════════════════ create ═══════════════════════════

def test_staff_booking_is_booked_at_once_and_sends_the_confirmation(msgs):
    db = make_db()
    row, info = book(db)
    assert row["status"] == "booked" and row["number"] == 1 and bk.code_for(row["number"]) == "BK-0001"
    assert row["phone"] == "+919876543210" and row["resource_id"] == "2e000000-0000-4000-8000-000000000001"
    assert row["booking_date"] == "2026-11-24" and row["hold_until"] is None
    assert bk.parse_ts(row["end_at"]) - bk.parse_ts(row["start_at"]) == timedelta(minutes=30)
    msgs.send_confirmation.assert_awaited_once()
    assert info["payment_url"] is None


def test_numbers_count_up_per_business(msgs):
    db = make_db()
    a, _ = book(db)
    b, _ = book(db, phone="9876500001", start_at=ist("2026-11-24", "11:00").isoformat())
    assert (a["number"], b["number"]) == (1, 2)


def test_second_booking_same_phone_same_day_is_refused(msgs):
    db = make_db()
    book(db)
    with pytest.raises(BookingError) as e:
        book(db, start_at=ist("2026-11-24", "11:00").isoformat())
    assert e.value.status_code == 409 and "already has a booking" in e.value.message


def _one_per_day(db, on: bool):
    db.add("booking_settings", tenant_id=T1, one_per_day=on, days_ahead=14, min_notice_min=60,
           cancel_cutoff_min=180, no_show_limit=2, link_on=True, link_token="tok")


def test_one_per_day_off_allows_a_second_booking_that_day(msgs):
    db = make_db()
    _one_per_day(db, False)
    first, _ = book(db)
    second, _ = book(db, start_at=ist("2026-11-24", "11:00").isoformat())
    assert second["number"] == 2 and second["status"] == "booked"
    assert first["day_guard"] is False and second["day_guard"] is False


def test_one_per_day_on_stamps_day_guard_true_and_still_refuses(msgs):
    db = make_db()
    _one_per_day(db, True)
    first, _ = book(db)
    assert first["day_guard"] is True
    with pytest.raises(BookingError) as e:
        book(db, start_at=ist("2026-11-24", "11:00").isoformat())
    assert e.value.status_code == 409 and "already has a booking" in e.value.message


def test_moving_onto_a_day_with_the_same_phone_follows_the_switch(msgs):
    for on in (True, False):
        db = make_db()
        _one_per_day(db, on)
        db.add("bookings", id="b0000000-0000-4000-8000-000000000001", tenant_id=T1, number=1, phone="+919876543210", service_id="5e000000-0000-4000-8000-000000000001", resource_id="2e000000-0000-4000-8000-000000000001",
               start_at=bk.iso(ist("2026-11-24", "10:00")), end_at=bk.iso(ist("2026-11-24", "10:30")),
               block_end_at=bk.iso(ist("2026-11-24", "10:30")), booking_date="2026-11-24", status="booked", day_guard=on)
        db.add("bookings", id="b0000000-0000-4000-8000-000000000002", tenant_id=T1, number=2, phone="+919876543210", service_id="5e000000-0000-4000-8000-000000000001", resource_id="2e000000-0000-4000-8000-000000000001",
               start_at=bk.iso(ist("2026-11-25", "10:00")), end_at=bk.iso(ist("2026-11-25", "10:30")),
               block_end_at=bk.iso(ist("2026-11-25", "10:30")), booking_date="2026-11-25", status="booked", day_guard=on)
        move = bk.move_booking(db, T1, "b0000000-0000-4000-8000-000000000002", ist("2026-11-24", "11:00").isoformat())
        if on:
            with pytest.raises(BookingError) as e:
                run(move)
            assert "already has a booking" in e.value.message
        else:
            moved = run(move)
            assert moved["booking_date"] == "2026-11-24" and moved["day_guard"] is False


def test_a_taken_slot_is_a_409_with_taken_in_the_words(msgs):
    db = make_db()
    book(db)
    with pytest.raises(BookingError) as e:
        book(db, phone="9876500002")        # same column, same time
    assert e.value.status_code == 409 and "taken" in e.value.message


def test_database_overlap_race_is_mapped_to_taken(msgs, monkeypatch):
    """Two people pass the free check together; the exclusion constraint stops the second."""
    db = make_db()
    book(db)
    ravi = {"id": "2e000000-0000-4000-8000-000000000001", "name": "Ravi", "user_id": "u-ravi"}
    monkeypatch.setattr(bk, "_free_columns", lambda *a, **k: [ravi])      # both passed the free check together
    with pytest.raises(BookingError) as e:
        book(db, phone="9876500002")
    assert e.value.status_code == 409 and "taken" in e.value.message


def test_database_phone_day_race_is_mapped(msgs, monkeypatch):
    db = make_db()
    _one_per_day(db, True)
    book(db)
    monkeypatch.setattr(bk, "_phone_has_live", lambda *a, **k: False)
    with pytest.raises(BookingError) as e:
        book(db, resource_id="2e000000-0000-4000-8000-000000000002", start_at=ist("2026-11-24", "11:00").isoformat())
    assert e.value.status_code == 409 and "already has a booking" in e.value.message


def test_number_clash_retries_with_the_next_number(msgs, monkeypatch):
    db = make_db()
    book(db)
    nums = iter([1, 2])                      # first try collides with BK-0001
    monkeypatch.setattr(bk, "_next_number", lambda *a, **k: next(nums))
    row, _ = book(db, phone="9876500002", start_at=ist("2026-11-24", "11:00").isoformat())
    assert row["number"] == 2


def test_bad_inputs_are_plain_409s_or_400s(msgs):
    db = make_db()
    with pytest.raises(BookingError):
        book(db, phone="12")
    with pytest.raises(BookingError):
        book(db, start_at=ist("2026-11-24", "10:07").isoformat())       # not on a quarter hour
    with pytest.raises(BookingError):
        book(db, service_id="nope")
    with pytest.raises(BookingError):
        book(db, start_at=ist("2026-11-24", "13:00").isoformat())       # outside hours
    with pytest.raises(BookingError):
        book(db, source="web")


def test_any_column_takes_the_first_free_one(msgs):
    db = make_db()
    book(db, resource_id="any")
    row, _ = book(db, resource_id="any", phone="9876500002")
    assert row["resource_id"] == "2e000000-0000-4000-8000-000000000002"


def test_a_view_only_person_cannot_book_someone_elses_column(msgs):
    db = make_db()
    with pytest.raises(BookingError):
        book(db, resource_id="2e000000-0000-4000-8000-000000000002", allowed_resources=[{"id": "2e000000-0000-4000-8000-000000000001", "hours": HOURS}])


def test_a_known_lead_is_used_and_lead_gets_booked_at_and_booked_for(msgs, monkeypatch):
    from app.services import booking_messages as bm
    monkeypatch.setattr(bm, "_now", lambda: NOW)
    db = make_db()
    row, _ = book(db, lead_id="10000000-0000-4000-8000-000000000001")
    lead = db.rows("leads")[0]
    assert row["lead_id"] == "10000000-0000-4000-8000-000000000001" and lead["booked_at"] == bk.iso(NOW)
    assert lead["booked_for"] == row["start_at"]


def test_a_lead_from_another_business_is_not_used(msgs):
    db = make_db()
    db.add("leads", id="LX", tenant_id=T2, name="X", phone="+911")
    with pytest.raises(BookingError) as e:                                    # MED-8: a lead of another business is a 400
        book(db, lead_id="LX")
    assert e.value.status_code == 400


def test_link_booking_rings_the_bell_but_staff_booking_does_not(msgs):
    db = make_db()
    book(db)
    msgs.ring_bell.assert_not_called()
    book(db, source="link", phone="9876500002", start_at=ist("2026-11-24", "11:00").isoformat())
    msgs.ring_bell.assert_called_once()


# ═══════════════════════════ review fixes (HIGH / MED) ═══════════════════════════

R1 = "2e000000-0000-4000-8000-000000000001"
R2 = "2e000000-0000-4000-8000-000000000002"
S1 = "5e000000-0000-4000-8000-000000000001"
S2 = "5e000000-0000-4000-8000-000000000002"
LEAD1 = "10000000-0000-4000-8000-000000000001"


def _view_ctx(uid, perms=("bookings.view",)):
    return {"tenant_id": T1, "user_id": uid, "role": "caller", "permissions": list(perms)}


def test_high1_someone_linked_to_a_switched_off_column_sees_nothing_not_everything():
    db = make_db()
    db.rows("booking_resources")[0]["active"] = False                 # Ravi's column is off
    assert bk.scoped_columns(db, _view_ctx("u-ravi")) == []            # linked -> [] (never "all")
    assert [r["id"] for r in bk.scoped_columns(db, _view_ctx("u-view"))] == [R2]       # unlinked viewer: all active
    assert [r["id"] for r in bk.scoped_columns(db, _view_ctx("u-mgr", ("bookings.manage",)))] == [R2]


def test_med1_cancel_and_no_show_always_call_release_unpaid_order(msgs, monkeypatch):
    from app.services import booking_orders as bo
    release = MagicMock()
    monkeypatch.setattr(bo, "release_unpaid_order", release)
    db = make_db()
    row, _ = book(db)
    run(bk.cancel_booking(db, T1, row["id"], by="staff"))
    assert release.call_count == 1
    row2, _ = book(db, phone="9876500002", start_at=ist("2026-11-24", "11:00").isoformat())
    monkeypatch.setattr(bk, "_now", lambda: ist("2026-11-24", "12:00"))
    bk.mark_no_show(db, T1, row2["id"])
    assert release.call_count == 2


def test_med2_any_column_tries_the_next_free_column_when_the_first_is_taken_in_a_race(msgs, monkeypatch):
    db = make_db()
    book(db)                                                           # Ravi (R1) is busy at 10:00 tomorrow
    cols = [{"id": R1, "name": "Ravi"}, {"id": R2, "name": "Chair 2"}]
    monkeypatch.setattr(bk, "_free_columns", lambda *a, **k: cols)     # both looked free at the check
    row, info = book(db, resource_id="any", phone="9876500002")
    assert row["resource_id"] == R2 and info["resource"]["id"] == R2


def test_med3_came_again_reruns_the_order_only_when_there_is_no_deal(msgs, monkeypatch):
    from app.services import booking_orders as bo
    order = AsyncMock(side_effect=[bo.BookingOrderError("no item"), "d1"])
    monkeypatch.setattr(bo, "order_for_came", order)
    db = make_db()
    row, _ = book(db)
    first = run(bk.mark_came(db, T1, row["id"]))
    assert first["order_error"] == "no item" and db.rows("bookings")[0]["status"] == "came"
    again = run(bk.mark_came(db, T1, row["id"]))                       # came + no deal_id: try the order again
    assert again["deal_id"] == "d1" and order.await_count == 2
    db.rows("bookings")[0]["deal_id"] = "d1"
    with pytest.raises(BookingError):                                  # came with an order: nothing left to do
        run(bk.mark_came(db, T1, row["id"]))


def test_med3_a_lost_race_on_any_status_change_is_a_409_refresh(msgs, monkeypatch):
    db = make_db()
    row, _ = book(db)
    stale = dict(db.rows("bookings")[0])                               # what the loser read, still "booked"
    db.rows("bookings")[0]["status"] = "cancelled"                     # the winner already cancelled it
    monkeypatch.setattr(bk, "get_booking", lambda *a, **k: dict(stale))
    monkeypatch.setattr(bk, "_now", lambda: ist("2026-11-24", "12:00"))
    for call in (lambda: run(bk.mark_came(db, T1, row["id"])),
                 lambda: bk.mark_no_show(db, T1, row["id"]),
                 lambda: run(bk.cancel_booking(db, T1, row["id"])),
                 lambda: run(bk.move_booking(db, T1, row["id"], ist("2026-11-25", "10:00").isoformat(), R1))):
        with pytest.raises(BookingError) as e:
            call()
        assert e.value.status_code == 409 and e.value.message == "This booking just changed — refresh"


def test_med6_boards_page_past_1000_rows_in_order(monkeypatch):
    db = make_db()
    for i in range(1005):
        start = ist("2026-11-24", "10:00") + timedelta(minutes=i)
        db.add("bookings", id=f"b{i:05d}", tenant_id=T1, number=i + 1, phone=f"+9190000{i:05d}", resource_id=R1,
               service_id=S1, start_at=bk.iso(start), end_at=bk.iso(start), block_end_at=bk.iso(start),
               booking_date="2026-11-24", status="booked", day_guard=False)
    rows = bk.bookings_on(db, T1, date(2026, 11, 24), date(2026, 11, 24), [R1])
    assert len(rows) == 1005 and len({r["id"] for r in rows}) == 1005
    assert [r["start_at"] for r in rows] == sorted(r["start_at"] for r in rows)


def test_med6_shaping_a_list_reads_the_deals_once(monkeypatch):
    from app.services import booking_orders as bo
    many = MagicMock(return_value={"x1": True, "x2": False})
    monkeypatch.setattr(bo, "advance_paid_many", many)
    rows = [dict(id=f"x{i}", number=i, status="held", start_at="2026-11-24T04:30:00+00:00", end_at="x", block_end_at="x",
                 service_id=S1, resource_id=R1, advance_paise=100, deal_id=f"d{i}") for i in (1, 2)]
    out = bk.shape_many(make_db(), T1, rows, {}, show_money=True)
    assert many.call_count == 1
    assert [o["advance_paid"] for o in out] == [True, False]
    assert all("source" in o and "phone_checked" in o for o in out)    # the board shape carries both


def test_med8_new_leads_get_the_right_source_and_a_given_lead_must_match_the_phone(msgs, monkeypatch):
    seen = []
    monkeypatch.setattr("app.services.inbound_lead.create_inbound_lead",
                        lambda tid, phone, source, **k: seen.append(source) or LEAD1)
    db = make_db()
    for i, src in enumerate(("phone", "walk_in", "chat", "link")):
        book(db, source=src, phone=f"98765000{i:02d}", start_at=ist("2026-11-24", ["10:00", "11:00", "12:00", "16:00"][i]).isoformat())
    assert seen == ["manual", "manual", "whatsapp", "website"]
    with pytest.raises(BookingError) as e:                              # L1 is +919876543210, not this number
        book(db, lead_id=LEAD1, phone="9123456789", start_at=ist("2026-11-25", "10:00").isoformat())
    assert e.value.status_code == 400
    row, _ = book(db, lead_id=LEAD1, phone="9876543210", start_at=ist("2026-11-25", "11:00").isoformat())
    assert row["lead_id"] == LEAD1


# ═══════════════════════════ security fixes S1 - S7 ═══════════════════════════

def pub(db, **kw):
    args = dict(source="link", public=True, phone="9876543210", customer_name="Priya")
    args.update(kw)
    return book(db, **args)


def test_s1_a_link_booking_is_always_held_unchecked_and_silent(msgs):
    db = make_db()
    row, info = pub(db)                                                # reading S1 has no advance at all
    assert row["status"] == "held" and row["phone_checked"] is False
    assert row["hold_until"] == bk.iso(NOW + timedelta(minutes=15))
    msgs.send_confirmation.assert_not_awaited()
    msgs.ring_bell.assert_not_called()
    assert db.rows("leads")[0]["booked_at"] is None                    # no lead mirror until it is really booked
    staff, _ = book(db, phone="9876500002", start_at=ist("2026-11-24", "11:00").isoformat())
    assert staff["status"] == "booked"                                  # staff bookings are unchanged
    msgs.send_confirmation.assert_awaited_once()


def test_s2_the_phone_must_be_an_indian_mobile(msgs):
    db = make_db()
    for bad in ("12345", "5876543210", "+14155550123", "98765432101", "abcdefghij"):
        with pytest.raises(BookingError) as e:
            pub(db, phone=bad)
        assert e.value.status_code == 400 and e.value.message == "Please enter a 10-digit mobile number"
    row, _ = pub(db, phone="+91 98765 43210")
    assert row["phone"] == "+919876543210"


def test_s2_at_most_two_upcoming_live_bookings_per_phone_with_the_generic_409(msgs):
    db = make_db()
    pub(db)
    pub(db, start_at=ist("2026-11-25", "10:00").isoformat())
    with pytest.raises(BookingError) as e:
        pub(db, start_at=ist("2026-11-26", "10:00").isoformat())
    assert e.value.status_code == 409 and e.value.message == bk.PUBLIC_CANT_BOOK
    other, _ = pub(db, phone="9876500002", start_at=ist("2026-11-26", "10:00").isoformat())   # another phone is fine
    assert other["status"] == "held"


def test_s2_twenty_unchecked_holds_per_business_then_429_that_mentions_whatsapp(msgs):
    db = make_db()
    for i in range(20):
        db.add("bookings", id=f"h{i}", tenant_id=T1, number=100 + i, phone=f"+9190000{i:05d}", resource_id=R2,
               service_id=S1, start_at=bk.iso(ist("2026-11-30", "10:00")), end_at=bk.iso(ist("2026-11-30", "10:30")),
               block_end_at=bk.iso(ist("2026-11-30", "10:30")), booking_date="2026-11-30", status="held",
               phone_checked=False, hold_until=bk.iso(NOW + timedelta(minutes=5)), day_guard=False)
    with pytest.raises(BookingError) as e:
        pub(db)
    assert e.value.status_code == 429
    assert e.value.message == "Too many bookings waiting — please confirm one on WhatsApp first"


def test_s2_names_are_cleaned_and_links_are_refused(msgs):
    assert bk.clean_public_name("  Pri\u200bya\u00a0  Sharma\x07 ") == "Priya Sharma"
    assert bk.clean_public_name("x" * 90) == "x" * 60
    for bad in ("visit http://evil.example", "www.evil.example", "a://b", "   ", "\u200b\u200b"):
        with pytest.raises(BookingError):
            bk.clean_public_name(bad)
    row, _ = pub(make_db(), customer_name="Pri\u200bya   Sharma")
    assert row["customer_name"] == "Priya Sharma"


def test_s3_the_held_row_carries_the_advance_from_the_start_and_any_error_cancels_it(msgs, monkeypatch):
    from app.services import booking_orders as bo
    db = make_db()
    seen = {}

    async def boom(tenant_id, booking, service, advance, **k):
        seen["row_advance"] = db.rows("bookings")[0]["advance_paise"]     # already on the row when the order starts
        raise RuntimeError("gateway down")
    monkeypatch.setattr(bo, "create_advance_order", boom)
    with pytest.raises(BookingError) as e:
        pub(db, service_id=S2)
    assert seen["row_advance"] == 20000
    assert e.value.status_code == 503 and e.value.message == "Couldn't make the payment link, please try again"
    row = db.rows("bookings")[0]
    assert row["status"] == "cancelled" and row["cancelled_by"] == "system"
    assert row["cancel_reason"] == "Could not make the payment link"


def test_s4_staff_get_the_specific_one_per_day_words_but_customers_get_the_generic_ones(msgs):
    db = make_db()
    book(db)
    with pytest.raises(BookingError) as staff:
        book(db, start_at=ist("2026-11-24", "11:00").isoformat())
    assert "already has a booking" in staff.value.message
    with pytest.raises(BookingError) as cust:
        pub(db, start_at=ist("2026-11-24", "11:00").isoformat())
    assert cust.value.status_code == 409 and cust.value.message == bk.PUBLIC_CANT_BOOK
    assert "booking" not in cust.value.message.lower().replace("can't book", "")


def test_s6_malformed_ids_are_404_or_400_never_a_crash(msgs):
    db = make_db()
    with pytest.raises(BookingError) as e:
        bk.get_booking(db, T1, "nope")
    assert e.value.status_code == 404
    with pytest.raises(BookingError) as e2:
        book(db, service_id="nope")
    assert e2.value.status_code == 400
    assert bsetup.get_service(db, T1, "nope") is None and bsetup.get_resource(db, T1, "nope") is None
    assert bk.resources_for(db, T1, {"resource_ids": [R1]}, "not-a-uuid") == []
    with pytest.raises(BookingError):
        book(db, lead_id="nope")


def test_s7_a_customer_may_move_three_times_staff_are_not_limited(msgs):
    db = make_db()
    row, _ = book(db, source="link")
    for n, hhmm in enumerate(("11:00", "12:00", "16:00")):
        moved = run(bk.move_booking(db, T1, row["id"], ist("2026-11-25", hhmm).isoformat(), R1, by="customer"))
        assert moved["moved_count"] == n + 1
    with pytest.raises(BookingError) as e:
        run(bk.move_booking(db, T1, row["id"], ist("2026-11-25", "17:00").isoformat(), R1, by="customer"))
    assert e.value.status_code == 403 and e.value.message == "Please call the business to change it again"
    run(bk.move_booking(db, T1, row["id"], ist("2026-11-25", "17:00").isoformat(), R1, by="staff"))


# ═══════════════════════════ MED-7: services and the catalogue ═══════════════════════════

@pytest.fixture
def embeds(monkeypatch):
    calls = []
    monkeypatch.setattr(bsetup, "_embed_item", lambda db, tid, item_id, name: calls.append((item_id, name)))
    return calls


def _items(db):
    return {r["id"]: r for r in db.rows("catalog_items")}


def test_med7_a_new_service_makes_a_ready_catalogue_item_and_indexes_it(embeds):
    db = make_db()
    row = bsetup.create_service(db, T1, {"name": "Facial", "duration_min": 45, "price_paise": 90000,
                                         "advance_paise": 10000, "resource_ids": [R1]})
    item = _items(db)[row["catalog_item_id"]]
    assert item["status"] == "ready" and item["item_type"] == "service" and item["price_paise"] == 90000
    assert embeds == [(row["catalog_item_id"], "Facial")]


def test_med7_editing_touches_only_name_and_price_and_never_resets_status(embeds):
    db = make_db()
    row = bsetup.create_service(db, T1, {"name": "Facial", "duration_min": 45, "price_paise": 90000})
    db.rows("catalog_items")[0].update(status="draft", description="kept")
    embeds.clear()
    bsetup.update_service(db, T1, row["id"], {"duration_min": 60})            # not name / price: catalogue untouched
    assert embeds == [] and _items(db)[row["catalog_item_id"]]["name"] == "Facial"
    bsetup.update_service(db, T1, row["id"], {"name": "Deep facial", "price_paise": 95000})
    item = _items(db)[row["catalog_item_id"]]
    assert (item["name"], item["price_paise"]) == ("Deep facial", 95000)
    assert item["status"] == "draft" and item["description"] == "kept"         # not forced back to ready
    assert embeds == [(row["catalog_item_id"], "Deep facial")]


def test_med7_bad_column_ids_are_refused_before_anything_is_written(embeds):
    db = make_db()
    before = (len(db.rows("booking_services")), len(db.rows("catalog_items")), len(db.rows("booking_service_resources")))
    for bad in (["nope"], [R1, "2e000000-0000-4000-8000-0000000000ff"]):
        with pytest.raises(BookingError):
            bsetup.create_service(db, T1, {"name": "Facial", "duration_min": 45, "price_paise": 100, "resource_ids": bad})
    assert before == (len(db.rows("booking_services")), len(db.rows("catalog_items")), len(db.rows("booking_service_resources")))


def test_med7_new_links_are_added_before_the_old_ones_are_removed(embeds):
    db = make_db()
    order = []
    db.table = lambda name, _r=db.table: spy_for(_r, name, order)
    db.rows("booking_service_resources")[:] = [l for l in db.rows("booking_service_resources")
                                               if l["service_id"] != S1 or l["resource_id"] == R1]   # S1 does only R1
    bsetup._set_service_resources(db, T1, service_id=S1, ids=[R2])                                    # swap R1 for R2
    assert order[0] == "insert" and "delete" in order
    assert [l["resource_id"] for l in db.rows("booking_service_resources") if l["service_id"] == S1] == [R2]


def spy_for(real, name, order):
    q = real(name)
    if name == "booking_service_resources":
        for op in ("insert", "delete"):
            orig = getattr(q, op)
            setattr(q, op, lambda *a, _o=orig, _n=op, **k: (order.append(_n), _o(*a, **k))[1])
    return q


def test_med7_booking_uses_the_catalogue_price_and_caps_the_advance_at_it(msgs, monkeypatch):
    from app.services import booking_orders as bo
    db = make_db()
    db.add("catalog_items", id="C2", tenant_id=T1, name="Cut", price_paise=15000, status="ready", item_type="service")
    db.rows("booking_services")[1]["catalog_item_id"] = "C2"          # the shop dropped the price to 150 rupees
    got = {}

    async def fake_order(tenant_id, booking, service, advance, **k):
        got.update(price=service["price_paise"], advance=advance)
        return {"deal_id": "d1", "payment_url": "https://p", "advance": advance}
    monkeypatch.setattr(bo, "create_advance_order", fake_order)
    row, info = pub(db, service_id=S2)
    assert got == {"price": 15000, "advance": 15000}                   # 20000 advance capped at the live 15000 price
    assert row["advance_paise"] == 15000
