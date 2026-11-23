"""v9.2 #59 + #92 open hours: one setting read by the AI prompt, customer booking times and the after-hours message."""
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.routes import reply_settings
from app.services import after_hours, open_hours
from app.services import bookings as bk
from fake_supabase import FakeSupabase
from test_bookings_engine import NOW, T1, ist, make_db

T = "t1"
IST = open_hours.IST
MON_SAT = {str(d): [["10:00", "20:00"]] for d in range(6)}  # Sunday closed


def _at(day: str, h: int, m: int = 0) -> datetime:
    y, mo, d = map(int, day.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=IST)


def _saved(db=None, hours=None, holidays=True):
    db = db or FakeSupabase()
    open_hours.save(db, T, {"hours": MON_SAT if hours is None else hours, "national_holidays": holidays})
    return db


# ── the setting ─────────────────────────────────────────────────────────────

def test_not_set_changes_nothing():
    db = FakeSupabase()
    cfg = open_hours.read(db, T)
    assert cfg["set"] is False and open_hours.summary(cfg) == ""
    assert open_hours.prompt_block(db, T, _at("2026-11-29", 12)) == ""
    assert open_hours.closed_on(cfg, date(2026, 11, 29)) is False
    assert open_hours.limit_hours({"0": [["08:00", "22:00"]]}, cfg) == {"0": [["08:00", "22:00"]]}


def test_validation_refuses_bad_hours_and_no_open_day():
    for bad in ({"hours": {}}, {"hours": {"7": [["10:00", "20:00"]]}}, {"hours": {"0": [["20:00", "10:00"]]}},
                {"hours": {"0": [["10am", "8pm"]]}}):
        with pytest.raises(open_hours.OpenHoursError):
            open_hours.validate(bad)


def test_summary_groups_days_in_plain_words():
    cfg = open_hours.read(_saved(), T)
    assert open_hours.summary(cfg) == "Mon–Sat, 10 AM–8 PM"
    split = open_hours.read(_saved(hours={**{str(d): [["09:30", "18:00"]] for d in range(5)},
                                          "5": [["10:00", "14:00"]]}), T)
    assert open_hours.summary(split) == "Mon–Fri, 9:30 AM–6 PM · Sat, 10 AM–2 PM"
    gap = open_hours.read(_saved(hours={"0": [["10:00", "13:00"], ["16:00", "24:00"]], "2": [["10:00", "13:00"], ["16:00", "24:00"]]}), T)
    assert open_hours.summary(gap) == "Mon, 10 AM–1 PM, 4 PM–12 midnight · Wed, 10 AM–1 PM, 4 PM–12 midnight"


@pytest.mark.parametrize("when, open_now, line", [
    (_at("2026-11-23", 12), True, "Open now, until 8 PM"),                                  # Monday noon
    (_at("2026-11-23", 9, 30), False, "Closed right now. Opens today at 10 AM"),
    (_at("2026-11-23", 20, 0), False, "Closed right now. Opens tomorrow (Tuesday) at 10 AM"),
    (_at("2026-11-29", 12), False, "Closed today (Sunday). Opens tomorrow (Monday) at 10 AM"),
    # 15 Aug 2026 is a Saturday and Sunday is closed too, so it next opens on Monday 17 Aug.
    (_at("2026-08-15", 12), False, "Closed today (Independence Day). Opens Monday 17 Aug at 10 AM"),
])
def test_open_now_and_next_open(when, open_now, line):
    cfg = open_hours.read(_saved(), T)
    assert open_hours.is_open(cfg, when) is open_now
    assert open_hours.status_line(cfg, when) == line


def test_national_holidays_can_be_switched_off():
    cfg = open_hours.read(_saved(holidays=False), T)
    assert open_hours.is_open(cfg, _at("2026-01-26", 12)) is True  # a Monday
    cfg_on = open_hours.read(_saved(), T)
    assert open_hours.is_open(cfg_on, _at("2026-01-26", 12)) is False


def test_prompt_block_gives_the_week_and_today():
    db = _saved()
    block = open_hours.prompt_block(db, T, _at("2026-11-29", 11))
    assert "OPEN HOURS" in block and "Sunday closed" in block and "Monday 10 AM–8 PM" in block
    assert "Closed today (Sunday). Opens tomorrow (Monday) at 10 AM" in block
    assert "26 January" in block
    assert open_hours.prompt_block(db, "t2", _at("2026-11-29", 11)) == ""  # another business


def test_limit_hours_cuts_a_column_to_shop_hours():
    cfg = open_hours.read(_saved(), T)
    col = {"0": [["08:00", "13:00"], ["16:00", "22:00"]], "6": [["10:00", "18:00"]]}
    assert open_hours.limit_hours(col, cfg) == {"0": [["10:00", "13:00"], ["16:00", "20:00"]]}


# ── routes ──────────────────────────────────────────────────────────────────

def _client(db, monkeypatch, permissions=(), role="owner"):
    monkeypatch.setattr(reply_settings, "get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(reply_settings.router, prefix="/x")
    ctx = {"tenant_id": T, "role": role, "user_id": "u1", "caller_id": None, "permissions": list(permissions)}
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    app.dependency_overrides[get_tenant_id] = lambda: T
    return TestClient(app)


def test_routes_save_and_read_with_permissions(monkeypatch):
    db = FakeSupabase()
    owner = _client(db, monkeypatch)
    assert owner.get("/x/open-hours").json()["set"] is False
    res = owner.put("/x/open-hours", json={"hours": MON_SAT, "national_holidays": True})
    assert res.status_code == 200, res.text
    assert res.json()["summary"] == "Mon–Sat, 10 AM–8 PM" and res.json()["status"]
    assert owner.get("/x/open-hours").json()["hours"]["0"] == [["10:00", "20:00"]]
    assert owner.put("/x/open-hours", json={"hours": {}}).status_code == 422
    assert owner.put("/x/open-hours", json={"hours": {"0": [["10:00", "11:00"]] * 3}}).status_code == 422
    viewer = _client(db, monkeypatch, permissions=["settings.view"], role="agent")
    assert viewer.get("/x/open-hours").status_code == 200
    assert viewer.put("/x/open-hours", json={"hours": MON_SAT}).status_code == 403


# ── after-hours uses open hours ─────────────────────────────────────────────

def test_after_hours_follows_open_hours_once_set():
    db = FakeSupabase()
    after_hours.save(db, T, {"enabled": True, "open": "09:00", "close": "21:00", "message": "We reply at 10."})
    sunday_noon = _at("2026-11-29", 12)
    assert after_hours.prompt_line(db, T, sunday_noon) == ""          # old pair: 09-21, so "in"
    _saved(db)
    line = after_hours.prompt_line(db, T, sunday_noon)
    assert "AFTER HOURS" in line and "tomorrow (Monday) at 10 AM" in line
    assert after_hours.prompt_line(db, T, _at("2026-11-30", 12)) == ""  # Monday noon: open


# ── customer booking times ──────────────────────────────────────────────────

def test_customer_times_stay_inside_open_hours_staff_keep_column_hours():
    db = make_db()  # columns work 10-13 and 16-20 every day; NOW is Monday 23 Nov 09:30 IST
    open_hours.save(db, T1, {"hours": {str(d): [["11:00", "18:00"]] for d in range(6)}})
    svc = db.tables["booking_services"][0]
    cols = [r for r in db.tables["booking_resources"] if r["id"] == "2e000000-0000-4000-8000-000000000001"]
    rules = {"min_notice_min": 0, "days_ahead": 14}
    tue, sun = date(2026, 11, 24), date(2026, 11, 29)
    cust = bk.free_times(db, T1, svc, cols, [tue, sun], rules, staff=False, now=NOW)
    starts = [s for s, _r in cust[tue]]
    assert starts and min(starts) == ist("2026-11-24", "11:00") and max(starts) == ist("2026-11-24", "17:30")
    assert all(not (ist("2026-11-24", "13:00") <= s < ist("2026-11-24", "16:00")) for s in starts)
    assert cust[sun] == []                                            # shop closed on Sunday
    staff = bk.free_times(db, T1, svc, cols, [tue, sun], rules, staff=True, now=NOW)
    assert min(s for s, _r in staff[tue]) == ist("2026-11-24", "10:00") and staff[sun]
