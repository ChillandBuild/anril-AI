"""Bookings API (v9.2 #19): permissions, money visibility, column scoping, the staff actions, the
customer's public link, templates setup, plus the Home list and global search that read bookings.
DB = FakeSupabase with the bookings table's constraints; WhatsApp messages and Razorpay are mocks."""
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.routes import bookings as routes
from app.services import booking_setup as bsetup
from app.services import bookings as bk
from test_bookings_engine import HOURS, NOW, T1, T2, BookingsDB, ist, make_db

TOKEN = "tok_live_123"
OWNER = {"tenant_id": T1, "user_id": "u-owner", "role": "owner", "permissions": []}
MANAGER = {"tenant_id": T1, "user_id": "u-mgr", "role": "caller", "permissions": ["bookings.manage"]}
MANAGER_MONEY = {**MANAGER, "permissions": ["bookings.manage", "deals.view"]}
RAVI = {"tenant_id": T1, "user_id": "u-ravi", "role": "caller", "permissions": ["bookings.view"]}
VIEWER = {"tenant_id": T1, "user_id": "u-view", "role": "caller", "permissions": ["bookings.view"]}
NOBODY = {"tenant_id": T1, "user_id": "u-x", "role": "caller", "permissions": ["leads.view"]}
SLOT = ist("2026-11-24", "10:00").isoformat()


@pytest.fixture
def env(monkeypatch):
    db = make_db()
    db.add("booking_settings", tenant_id=T1, link_on=True, link_token=TOKEN, days_ahead=14, min_notice_min=60,
           cancel_cutoff_min=180, one_per_day=True, no_show_limit=2)
    from app.services import booking_messages as bm
    m = MagicMock()
    for name in ("send_confirmation", "send_moved", "send_cancelled"):
        setattr(m, name, AsyncMock(return_value=True))
        monkeypatch.setattr(bm, name, getattr(m, name))
    m.confirm_if_ready = AsyncMock(return_value={})
    m.confirm_if_paid = m.confirm_if_ready
    monkeypatch.setattr(bm, "confirm_if_ready", m.confirm_if_ready)
    monkeypatch.setattr(bm, "confirm_if_paid", m.confirm_if_ready)
    monkeypatch.setattr(bsetup, "_embed_item", lambda *a, **k: None)
    monkeypatch.setattr(bm, "ring_bell", m.ring_bell)
    monkeypatch.setattr(bm, "_now", lambda: NOW)
    monkeypatch.setattr("app.services.inbound_lead.create_inbound_lead", lambda *a, **k: "10000000-0000-4000-8000-000000000001")
    monkeypatch.setattr(bk, "_now", lambda: NOW)
    monkeypatch.setattr(bsetup, "now_utc", lambda: NOW)
    for lim, (n, w) in ((routes._ip_limiter, (60, 60)), (routes._token_post_limiter, (600, 60)),
                        (routes._status_ip_limiter, (240, 60)), (routes._status_id_limiter, (120, 60))):
        lim.__init__(n, w)
    routes._ip_holds.clear()
    with patch("app.routes.bookings.get_supabase", return_value=db):
        client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        try:
            yield type("Env", (), {"db": db, "msgs": m, "client": client})
        finally:
            app.dependency_overrides.clear()


def as_(env, ctx):
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    return env.client


def add_booking(db, **kw):
    start = kw.pop("start", ist("2026-11-24", "10:00"))
    row = dict(id="b0000000-0000-4000-8000-000000000001", tenant_id=T1, number=1, phone="+919876543210", customer_name="Priya", lead_id="10000000-0000-4000-8000-000000000001",
               service_id="5e000000-0000-4000-8000-000000000001", resource_id="2e000000-0000-4000-8000-000000000001", start_at=bk.iso(start), end_at=bk.iso(start + timedelta(minutes=30)),
               block_end_at=None, booking_date=bk.ist_date(start).isoformat(), status="booked", source="phone",
               advance_paise=0, deal_id=None, moved_count=0)
    row.update(kw)
    row["block_end_at"] = row["block_end_at"] or row["end_at"]
    return db.add("bookings", **row)


# ═══════════════════════════ permissions ═══════════════════════════

STAFF_GETS = ["/api/v1/bookings/setup", "/api/v1/bookings/day", "/api/v1/bookings/week",
              "/api/v1/bookings/free-days?service_id=5e000000-0000-4000-8000-000000000001", "/api/v1/bookings/history?phone=9876543210",
              f"/api/v1/bookings/free?service_id=5e000000-0000-4000-8000-000000000001&date=2026-11-24"]


@pytest.mark.parametrize("url", STAFF_GETS)
def test_reading_needs_bookings_view(env, url):
    assert as_(env, NOBODY).get(url).status_code == 403
    assert as_(env, VIEWER).get(url).status_code == 200


def test_manage_implies_view(env):
    assert as_(env, MANAGER).get("/api/v1/bookings/day").status_code == 200


@pytest.mark.parametrize("method,url,body", [
    ("put", "/api/v1/bookings/settings", {"days_ahead": 7}),
    ("post", "/api/v1/bookings/settings/new-link", None),
    ("post", "/api/v1/bookings/services", {"name": "X", "duration_min": 30}),
    ("patch", "/api/v1/bookings/services/5e000000-0000-4000-8000-000000000001", {"name": "Y"}),
    ("delete", "/api/v1/bookings/services/5e000000-0000-4000-8000-000000000001", None),
    ("post", "/api/v1/bookings/resources", {"name": "Z"}),
    ("patch", "/api/v1/bookings/resources/2e000000-0000-4000-8000-000000000001", {"name": "Z"}),
    ("delete", "/api/v1/bookings/resources/2e000000-0000-4000-8000-000000000001", None),
    ("post", "/api/v1/bookings/resources/2e000000-0000-4000-8000-000000000001/leave", {"from_date": "2026-12-01"}),
    ("delete", "/api/v1/bookings/leave/abc", None),
    ("post", "/api/v1/bookings/templates/setup", None),
    ("post", "/api/v1/bookings", {"service_id": "5e000000-0000-4000-8000-000000000001", "start_at": SLOT, "phone": "9876543210"}),
    ("post", "/api/v1/bookings/b0000000-0000-4000-8000-000000000001/move", {"start_at": SLOT}),
    ("post", "/api/v1/bookings/b0000000-0000-4000-8000-000000000001/cancel", None),
])
def test_changing_things_needs_bookings_manage(env, method, url, body):
    res = getattr(as_(env, VIEWER), method)(url, **({"json": body} if body is not None else {}))
    assert res.status_code == 403
    assert "Permission required" in res.json()["detail"]


# ═══════════════════════════ setup + money ═══════════════════════════

def test_setup_shape_and_link(env):
    res = as_(env, OWNER).get("/api/v1/bookings/setup")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"settings", "link_url", "services", "resources", "leave", "team", "my_resource_id",
                         "can_manage", "templates"}
    assert body["link_url"].endswith(f"/book/{TOKEN}")
    assert body["can_manage"] is True and body["my_resource_id"] is None
    assert [r["name"] for r in body["resources"]] == ["Ravi", "Chair 2"]
    assert set(body["resources"][0]) >= {"id", "name", "kind", "user_id", "hours", "active", "sort", "service_ids"}
    assert set(body["templates"]) == {"update", "reminder"}


def test_money_only_for_deals_view(env):
    with_money = as_(env, MANAGER_MONEY).get("/api/v1/bookings/setup").json()["services"]
    without = as_(env, MANAGER).get("/api/v1/bookings/setup").json()["services"]
    assert all("price_paise" in s and "advance_paise" in s for s in with_money)
    assert all("price_paise" not in s and "advance_paise" not in s for s in without)
    assert as_(env, OWNER).get("/api/v1/bookings/setup").json()["services"][0]["price_paise"] == 50000


def test_a_manager_without_deals_view_cannot_set_prices(env):
    res = as_(env, MANAGER).patch("/api/v1/bookings/services/5e000000-0000-4000-8000-000000000001", json={"name": "Reading+", "price_paise": 1})
    assert res.status_code == 200 and "price_paise" not in res.json()
    svc = [s for s in env.db.rows("booking_services") if s["id"] == "5e000000-0000-4000-8000-000000000001"][0]
    assert svc["name"] == "Reading+" and svc["price_paise"] == 50000
    res = as_(env, MANAGER_MONEY).patch("/api/v1/bookings/services/5e000000-0000-4000-8000-000000000001", json={"price_paise": 60000})
    assert res.json()["price_paise"] == 60000


def test_settings_update_and_validation(env):
    c = as_(env, MANAGER)
    ok = c.put("/api/v1/bookings/settings", json={"days_ahead": 21, "one_per_day": True})
    assert ok.status_code == 200 and ok.json()["settings"]["days_ahead"] == 21
    assert c.put("/api/v1/bookings/settings", json={"days_ahead": 0}).status_code in (400, 422)


def test_new_link_changes_the_token_and_kills_the_old_one(env):
    first = as_(env, OWNER).get(f"/api/v1/public/bookings/{TOKEN}")
    assert first.status_code == 200
    new = as_(env, OWNER).post("/api/v1/bookings/settings/new-link").json()["link_url"]
    token = new.rsplit("/", 1)[1]
    assert token != TOKEN
    assert env.client.get(f"/api/v1/public/bookings/{TOKEN}").status_code == 404
    assert env.client.get(f"/api/v1/public/bookings/{token}").status_code == 200


def test_service_and_resource_crud(env):
    c = as_(env, OWNER)
    made = c.post("/api/v1/bookings/services", json={"name": "Facial", "duration_min": 45, "price_paise": 90000,
                                                      "resource_ids": ["2e000000-0000-4000-8000-000000000001"]})
    assert made.status_code == 200, made.text
    sid = made.json()["id"]
    assert made.json()["resource_ids"] == ["2e000000-0000-4000-8000-000000000001"]
    assert c.delete(f"/api/v1/bookings/services/{sid}").json()["active"] is False
    res = c.post("/api/v1/bookings/resources", json={"name": "Chair 3", "kind": "chair", "hours": HOURS})
    assert res.status_code == 200 and res.json()["kind"] == "chair"
    assert c.post("/api/v1/bookings/resources", json={"name": "Bad", "hours": {"0": [["12:00", "10:00"]]}}).status_code == 400
    assert c.post("/api/v1/bookings/resources", json={"name": "Bad", "kind": "tent"}).status_code == 422


def test_a_column_with_upcoming_bookings_cannot_be_deleted(env):
    add_booking(env.db)
    res = as_(env, OWNER).delete("/api/v1/bookings/resources/2e000000-0000-4000-8000-000000000001")
    assert res.status_code == 400 and "upcoming" in res.json()["detail"].lower()


def test_leave_add_and_delete(env):
    c = as_(env, OWNER)
    made = c.post("/api/v1/bookings/resources/2e000000-0000-4000-8000-000000000002/leave", json={"from_date": "2026-12-01", "to_date": "2026-12-03"})
    assert made.status_code == 200, made.text
    assert c.delete(f"/api/v1/bookings/leave/{made.json()['id']}").json() == {"ok": True}
    assert not env.db.rows("booking_leave")


def test_templates_setup_needs_both_permissions_and_returns_b2s_answer(env):
    url = "/api/v1/bookings/templates/setup"
    assert as_(env, MANAGER).post(url).status_code == 403          # bookings.manage only
    only_templates = {**MANAGER, "permissions": ["templates.manage"]}
    assert as_(env, only_templates).post(url).status_code == 403   # templates.manage only
    both = {**MANAGER, "permissions": ["bookings.manage", "templates.manage"]}
    answer = {"templates": {"update": "pending", "reminder": "pending"}, "problems": []}
    with patch("app.services.booking_messages.submit_templates", new=AsyncMock(return_value=answer)) as sub:
        res = as_(env, both).post(url)
    assert res.status_code == 200 and res.json() == answer
    assert sub.await_args.args[1] == T1 and sub.await_args.args[2]["user_id"] == "u-mgr"


# ═══════════════════════════ the boards ═══════════════════════════

def test_day_board_shape_and_free_ranges(env):
    add_booking(env.db)
    body = as_(env, MANAGER).get("/api/v1/bookings/day?date=2026-11-24").json()
    assert set(body) == {"date", "resources", "bookings", "free"}
    assert body["date"] == "2026-11-24" and len(body["resources"]) == 2
    b = body["bookings"][0]
    assert set(b) >= {"id", "number", "code", "status", "start_at", "end_at", "block_end_at", "service_name",
                      "resource_id", "customer_name", "phone", "lead_id", "advance_needed", "advance_paid",
                      "deal_id", "confirmed_at", "call_now", "note"}
    assert b["code"] == "BK-0001" and b["service_name"] == "Reading"
    assert "advance_paise" not in b                          # no deals.view
    r1_free = body["free"]["2e000000-0000-4000-8000-000000000001"]
    assert r1_free[0][0] == bk.iso(ist("2026-11-24", "10:30"))   # 10:00-10:30 is taken
    assert body["free"]["2e000000-0000-4000-8000-000000000002"][0] == [bk.iso(ist("2026-11-24", "10:00")), bk.iso(ist("2026-11-24", "13:00"))]


def test_day_board_advance_amount_only_with_deals_view(env):
    add_booking(env.db, advance_paise=20000)
    rich = as_(env, {**OWNER}).get("/api/v1/bookings/day?date=2026-11-24").json()["bookings"][0]
    poor = as_(env, MANAGER).get("/api/v1/bookings/day?date=2026-11-24").json()["bookings"][0]
    assert rich["advance_paise"] == 20000 and "advance_paise" not in poor
    assert poor["advance_needed"] is True                      # the fact is visible, the money is not


def test_day_board_defaults_to_today_and_rejects_bad_dates(env):
    assert as_(env, OWNER).get("/api/v1/bookings/day").json()["date"] == "2026-11-23"
    assert as_(env, OWNER).get("/api/v1/bookings/day?date=soon").status_code == 400


def test_cancelled_bookings_do_not_show_on_the_board(env):
    add_booking(env.db, status="cancelled")
    assert as_(env, OWNER).get("/api/v1/bookings/day?date=2026-11-24").json()["bookings"] == []


def test_week_board_groups_by_day_starting_monday(env):
    add_booking(env.db)
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", start=ist("2026-11-27", "11:00"))
    body = as_(env, OWNER).get("/api/v1/bookings/week?start=2026-11-25").json()
    assert body["start"] == "2026-11-23" and [d["date"] for d in body["days"]][0] == "2026-11-23" and len(body["days"]) == 7
    by_day = {d["date"]: [b["id"] for b in d["bookings"]] for d in body["days"]}
    assert by_day["2026-11-24"] == ["b0000000-0000-4000-8000-000000000001"] and by_day["2026-11-27"] == ["b0000000-0000-4000-8000-000000000002"] and by_day["2026-11-23"] == []


def test_a_linked_staff_member_sees_only_their_own_column(env):
    add_booking(env.db)                                               # on R1 (Ravi)
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", resource_id="2e000000-0000-4000-8000-000000000002")
    ravi = as_(env, RAVI).get("/api/v1/bookings/day?date=2026-11-24").json()
    assert [r["id"] for r in ravi["resources"]] == ["2e000000-0000-4000-8000-000000000001"] and [b["id"] for b in ravi["bookings"]] == ["b0000000-0000-4000-8000-000000000001"]
    assert set(ravi["free"]) == {"2e000000-0000-4000-8000-000000000001"}
    seen = as_(env, VIEWER).get("/api/v1/bookings/day?date=2026-11-24").json()      # not linked: sees all
    assert [r["id"] for r in seen["resources"]] == ["2e000000-0000-4000-8000-000000000001", "2e000000-0000-4000-8000-000000000002"]
    setup = as_(env, RAVI).get("/api/v1/bookings/setup").json()
    assert setup["my_resource_id"] == "2e000000-0000-4000-8000-000000000001" and setup["can_manage"] is False and setup["team"] == []
    assert [r["id"] for r in setup["resources"]] == ["2e000000-0000-4000-8000-000000000001"]


def test_free_times_and_days(env):
    c = as_(env, OWNER)
    times = c.get("/api/v1/bookings/free?service_id=5e000000-0000-4000-8000-000000000001&resource_id=any&date=2026-11-24").json()["times"]
    assert times[0] == {"start_at": bk.iso(ist("2026-11-24", "10:00")), "resource_id": "2e000000-0000-4000-8000-000000000001", "resource_name": "Ravi"} \
        or set(times[0]) >= {"start_at", "resource_id"}
    days = c.get("/api/v1/bookings/free-days?service_id=5e000000-0000-4000-8000-000000000001").json()["dates"]
    assert days[0] == "2026-11-23" and "2026-12-07" in days
    assert c.get("/api/v1/bookings/free?service_id=nope&date=2026-11-24").status_code == 404


def test_history_counts_and_advance_flag(env):
    add_booking(env.db, status="no_show")
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, status="no_show", start=ist("2026-11-20", "10:00"))
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000003", number=3, status="cancelled", start=ist("2026-11-18", "10:00"))
    out = as_(env, OWNER).get("/api/v1/bookings/history?phone=9876543210").json()
    assert out == {"bookings_count": 2, "no_shows": 2, "advance_needed": True}
    assert as_(env, OWNER).get("/api/v1/bookings/history?phone=12").status_code == 400


# ═══════════════════════════ staff actions ═══════════════════════════

def test_create_booking_returns_the_board_shape(env):
    res = as_(env, MANAGER).post("/api/v1/bookings", json={"service_id": "5e000000-0000-4000-8000-000000000001", "resource_id": "2e000000-0000-4000-8000-000000000001", "start_at": SLOT,
                                                            "phone": "98765 43210", "customer_name": "Priya"})
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["code"] == "BK-0001" and b["status"] == "booked" and b["phone"] == "+919876543210"
    env.msgs.send_confirmation.assert_awaited_once()


def test_create_booking_errors_are_plain_409s(env):
    c = as_(env, MANAGER)
    body = {"service_id": "5e000000-0000-4000-8000-000000000001", "resource_id": "2e000000-0000-4000-8000-000000000001", "start_at": SLOT, "phone": "9876543210"}
    assert c.post("/api/v1/bookings", json=body).status_code == 200
    again = c.post("/api/v1/bookings", json={**body, "start_at": ist("2026-11-24", "11:00").isoformat()})
    assert again.status_code == 409 and "already has a booking" in again.json()["detail"]
    clash = c.post("/api/v1/bookings", json={**body, "phone": "9876500002"})
    assert clash.status_code == 409 and "taken" in clash.json()["detail"]
    assert c.post("/api/v1/bookings", json={**body, "source": "web"}).status_code == 422


def test_staff_advance_link_failure_still_books_and_reports(env):
    from app.services import booking_orders as bo
    with patch.object(bo, "create_advance_order", new=AsyncMock(side_effect=bo.BookingOrderError("no catalogue item"))):
        res = as_(env, MANAGER).post("/api/v1/bookings", json={
            "service_id": "5e000000-0000-4000-8000-000000000002", "resource_id": "2e000000-0000-4000-8000-000000000001", "start_at": SLOT, "phone": "9876543210", "send_advance_link": True})
    assert res.status_code == 200 and res.json()["status"] == "booked" and res.json()["advance_error"] == "no catalogue item"


def test_move_and_cancel(env):
    add_booking(env.db)
    c = as_(env, MANAGER)
    moved = c.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/move", json={"start_at": ist("2026-11-24", "11:00").isoformat()})
    assert moved.status_code == 200 and moved.json()["start_at"] == bk.iso(ist("2026-11-24", "11:00"))
    env.msgs.send_moved.assert_awaited_once()
    assert env.db.rows("bookings")[0]["moved_count"] == 1
    gone = c.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/cancel", json={"reason": "Customer asked"})
    assert gone.status_code == 200 and gone.json()["status"] == "cancelled"
    assert env.msgs.send_cancelled.await_args.kwargs == {"reason": "Customer asked"}
    assert c.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/cancel").status_code == 400       # already cancelled
    assert c.post("/api/v1/bookings/nope/cancel").status_code == 404


def test_move_into_a_taken_time_is_409(env):
    add_booking(env.db)
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", start=ist("2026-11-24", "11:00"))
    res = as_(env, MANAGER).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000002/move", json={"start_at": SLOT})
    assert res.status_code == 409 and "taken" in res.json()["detail"]


def test_another_business_cannot_touch_a_booking(env):
    add_booking(env.db)
    other = {"tenant_id": T2, "user_id": "u-o", "role": "owner", "permissions": []}
    assert as_(env, other).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/cancel").status_code == 404


def test_came_makes_the_order_and_returns_its_link(env):
    add_booking(env.db, start=ist("2026-11-23", "09:00"))
    with patch("app.services.booking_orders.order_for_came", new=AsyncMock(return_value="d0000000-0000-4000-8000-000000000001")):
        res = as_(env, MANAGER_MONEY).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/came")
    assert res.status_code == 200
    assert res.json() == {"deal_id": "d0000000-0000-4000-8000-000000000001", "href": "/dashboard/deals/orders/d0000000-0000-4000-8000-000000000001", "order_error": None}
    assert env.db.rows("bookings")[0]["status"] == "came"


def test_came_when_the_order_cannot_be_made_still_marks_came(env):
    add_booking(env.db)
    from app.services import booking_orders as bo
    with patch.object(bo, "order_for_came", new=AsyncMock(side_effect=bo.BookingOrderError("no catalogue item"))):
        res = as_(env, MANAGER).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/came")
    assert res.json() == {"deal_id": None, "href": None, "order_error": "no catalogue item"}
    assert env.db.rows("bookings")[0]["status"] == "came"


def test_no_show_only_after_the_start_time(env):
    add_booking(env.db)                                                  # tomorrow
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", start=ist("2026-11-23", "09:00"))   # 30 min ago
    c = as_(env, MANAGER)
    early = c.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/no-show")
    assert early.status_code == 400 and "not started" in early.json()["detail"]
    ok = c.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000002/no-show")
    assert ok.status_code == 200 and ok.json()["status"] == "no_show"


def test_came_and_no_show_for_the_linked_staff_member_on_their_own_column_only(env):
    add_booking(env.db, start=ist("2026-11-23", "09:00"))                              # R1, Ravi's
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", resource_id="2e000000-0000-4000-8000-000000000002", start=ist("2026-11-23", "09:00"))
    ravi = as_(env, RAVI)
    with patch("app.services.booking_orders.order_for_came", new=AsyncMock(return_value="d0000000-0000-4000-8000-000000000001")):
        assert ravi.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/came").status_code == 200
    assert ravi.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000002/no-show").status_code == 403
    assert ravi.post("/api/v1/bookings/b0000000-0000-4000-8000-000000000002/came").status_code == 403
    # a view-only person who is not linked to any column is read-only
    assert as_(env, VIEWER).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000002/no-show").status_code == 403
    # a manager can do it on any column
    assert as_(env, MANAGER).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000002/no-show").status_code == 200


# ═══════════════════════════ the customer's public link ═══════════════════════════

P = f"/api/v1/public/bookings/{TOKEN}"


def test_public_page_needs_no_login_and_shows_no_staff_internals(env):
    res = env.client.get(P)                       # no tenant override at all
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert set(body) == {"business_name", "business_phone", "services", "resources", "rules"}
    assert body["business_name"] == "Glow Salon" and body["business_phone"] == "+919000000001"
    assert body["rules"] == {"days_ahead": 14, "cancel_cutoff_min": 180}
    assert {s["name"] for s in body["services"]} == {"Reading", "Cut"}
    assert set(body["resources"][0]) == {"id", "name", "kind", "service_ids"}      # no user_id, no hours
    assert "tenant_id" not in res.text and "u-ravi" not in res.text


def test_public_page_unknown_token_or_link_off_are_the_same_404(env):
    assert env.client.get("/api/v1/public/bookings/nope").status_code == 404
    env.db.rows("booking_settings")[0]["link_on"] = False
    off = env.client.get(P)
    assert off.status_code == 404 and off.json() == env.client.get("/api/v1/public/bookings/nope").json()


def test_public_page_business_phone_is_null_without_a_number(env):
    env.db.rows("phone_numbers").clear()
    assert env.client.get(P).json()["business_phone"] is None


def test_public_days_and_times_follow_the_customer_rules(env):
    days = env.client.get(f"{P}/days?service_id=5e000000-0000-4000-8000-000000000001").json()["dates"]
    assert days[0] == "2026-11-23" and days[-1] == "2026-12-07"
    times = env.client.get(f"{P}/times?service_id=5e000000-0000-4000-8000-000000000001&date=2026-11-23").json()["times"]
    assert times[0]["start_at"] == bk.iso(ist("2026-11-23", "10:30"))       # 60 min notice from 09:30
    assert env.client.get(f"{P}/times?service_id=5e000000-0000-4000-8000-000000000001&date=2026-12-30").json()["times"] == []
    assert env.client.get(f"{P}/times?service_id=nope&date=2026-11-23").status_code == 404
    assert env.client.get(f"{P}/times?service_id=5e000000-0000-4000-8000-000000000001&date=xx").status_code == 400


BODY = {"service_id": "5e000000-0000-4000-8000-000000000001", "resource_id": "2e000000-0000-4000-8000-000000000001", "start_at": SLOT, "phone": "9876543210", "name": "Priya"}


def test_public_booking_without_advance_is_still_held_until_the_phone_is_proved(env):
    res = env.client.post(P, json=BODY)
    assert res.status_code == 200, res.text
    b = res.json()
    assert set(b) == {"id", "code", "status", "start_at", "service_name", "resource_name", "advance_paise",
                      "payment_url", "hold_until", "whatsapp_url", "phone_checked"}
    assert b["status"] == "held" and b["phone_checked"] is False and b["payment_url"] is None
    assert b["hold_until"] == bk.iso(NOW.replace(minute=NOW.minute + 15))
    assert b["code"] == "BK-0001" and b["service_name"] == "Reading" and b["resource_name"] == "Ravi"
    assert b["whatsapp_url"].startswith("https://wa.me/919000000001?text=") and "BK-0001" in b["whatsapp_url"]
    env.msgs.send_confirmation.assert_not_awaited()                            # S1: nothing goes to an unproved number
    env.msgs.ring_bell.assert_not_called()                                     # S1: no booking_new bell either
    row = env.db.rows("bookings")[0]
    assert row["source"] == "link" and row["status"] == "held" and row["phone_checked"] is False


def test_public_booking_with_advance_is_held_for_15_minutes_with_a_pay_link(env):
    from app.services import booking_orders as bo
    made = AsyncMock(return_value={"deal_id": "d0000000-0000-4000-8000-000000000001", "payment_url": "https://rzp.io/x", "advance": 20000})
    with patch.object(bo, "create_advance_order", new=made):
        res = env.client.post(P, json={**BODY, "service_id": "5e000000-0000-4000-8000-000000000002"})
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["status"] == "held" and b["payment_url"] == "https://rzp.io/x" and b["advance_paise"] == 20000
    assert b["hold_until"] == bk.iso(NOW.replace(minute=NOW.minute + 15))
    assert made.await_args.kwargs["send_whatsapp_message"] is False
    env.msgs.send_confirmation.assert_not_awaited()                            # confirmed only once paid AND proved
    assert env.db.rows("bookings")[0]["advance_paise"] == 20000                # S3: set on the row from the start


def test_a_held_slot_with_no_way_to_pay_is_cancelled_and_answered_503(env):
    from app.services import booking_orders as bo
    for boom in (bo.BookingOrderError("x"), RuntimeError("razorpay down")):      # MED-4 / S3: ANY exception
        env.db.rows("bookings").clear()
        with patch.object(bo, "create_advance_order", new=AsyncMock(side_effect=boom)):
            res = env.client.post(P, json={**BODY, "service_id": "5e000000-0000-4000-8000-000000000002", "phone": "9876543210"})
        assert res.status_code == 503 and res.json()["detail"] == "Couldn't make the payment link, please try again"
        row = env.db.rows("bookings")[0]
        assert row["status"] == "cancelled" and row["cancel_reason"] == "Could not make the payment link"


def test_public_booking_errors(env):
    assert env.client.post(P, json=BODY).status_code == 200
    second_same_day = env.client.post(P, json={**BODY, "start_at": ist("2026-11-24", "11:00").isoformat()})
    assert second_same_day.status_code == 409 and second_same_day.json()["detail"] == bk.PUBLIC_CANT_BOOK
    taken = env.client.post(P, json={**BODY, "phone": "9876500002"})
    assert taken.status_code == 409 and "taken" in taken.json()["detail"]
    too_soon = env.client.post(P, json={**BODY, "phone": "9876500003", "start_at": ist("2026-11-23", "10:00").isoformat()})
    assert too_soon.status_code == 409
    assert env.client.post(P, json={**BODY, "name": ""}).status_code == 422
    assert env.client.post(f"/api/v1/public/bookings/nope", json=BODY).status_code == 404


def test_public_status_page_fields(env):
    add_booking(env.db, status="held", hold_until=bk.iso(NOW.replace(minute=NOW.minute + 10)), advance_paise=20000,
                deal_id="d0000000-0000-4000-8000-000000000001", phone_checked=False)
    env.db.add("deals", id="d0000000-0000-4000-8000-000000000001", tenant_id=T1, payment_link="https://rzp.io/x", paid_paise=0, refunded_paise=0, stage="quoted")
    res = env.client.get(f"{P}/booking/b0000000-0000-4000-8000-000000000001")
    assert res.status_code == 200
    b = res.json()
    assert set(b) == {"code", "status", "start_at", "service_id", "resource_id", "service_name", "resource_name",
                      "duration_min", "advance_paise", "advance_paid", "payment_url", "hold_until", "can_change",
                      "whatsapp_url", "business_phone", "phone_checked", "moves_left"}
    assert b["status"] == "held" and b["service_id"] == "5e000000-0000-4000-8000-000000000001" and b["resource_id"] == "2e000000-0000-4000-8000-000000000001" and b["duration_min"] == 30
    assert b["hold_until"] and b["payment_url"] == "https://rzp.io/x" and b["business_phone"] == "+919000000001"
    assert b["can_change"] is True and b["advance_paid"] is False
    assert b["phone_checked"] is False and b["moves_left"] == 3
    assert "phone" not in b and "customer_name" not in b and "tenant_id" not in b
    env.msgs.confirm_if_ready.assert_awaited_once()                            # a held booking goes to B2's flip


def test_public_status_booked_has_null_hold_until_and_unknown_id_is_404(env):
    add_booking(env.db, hold_until=bk.iso(NOW))
    b = env.client.get(f"{P}/booking/b0000000-0000-4000-8000-000000000001").json()
    assert b["hold_until"] is None and b["payment_url"] is None
    assert env.client.get(f"{P}/booking/nope").status_code == 404
    assert env.client.get(f"{P}/booking/{'x' * 80}").status_code == 404


def test_public_cannot_see_another_business_booking(env):
    env.db.add("booking_settings", tenant_id=T2, link_on=True, link_token="other_tok", days_ahead=14,
               min_notice_min=60, cancel_cutoff_min=180, one_per_day=True, no_show_limit=2)
    add_booking(env.db)                                                       # belongs to T1
    assert env.client.get(f"/api/v1/public/bookings/other_tok/booking/b0000000-0000-4000-8000-000000000001").status_code == 404
    assert env.client.post(f"/api/v1/public/bookings/other_tok/booking/b0000000-0000-4000-8000-000000000001/cancel").status_code == 404


def test_public_cancel_and_cutoff(env):
    add_booking(env.db)
    res = env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000001/cancel")
    assert res.status_code == 200 and res.json() == {"status": "cancelled"}
    env.msgs.ring_bell.assert_called_once()                                    # staff are told
    env.msgs.send_cancelled.assert_not_awaited()                               # the customer did it themselves
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", start=ist("2026-11-23", "11:00"))   # 90 min away, cutoff 180
    late = env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000002/cancel")
    assert late.status_code == 403 and "call the business" in late.json()["detail"]
    assert env.db.rows("bookings")[1]["status"] == "booked"


def test_public_move_and_cutoff(env):
    add_booking(env.db)
    res = env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000001/move", json={"start_at": ist("2026-11-24", "11:00").isoformat()})
    assert res.status_code == 200 and res.json()["start_at"] == bk.iso(ist("2026-11-24", "11:00"))
    assert res.json()["code"] == "BK-0001"
    env.msgs.send_moved.assert_awaited_once()
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", start=ist("2026-11-23", "11:00"))
    late = env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000002/move", json={"start_at": ist("2026-11-24", "12:00").isoformat()})
    assert late.status_code == 403
    taken = env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000001/move", json={"start_at": ist("2026-11-23", "09:00").isoformat()})
    assert taken.status_code in (409, 400)


def test_public_customer_cannot_cancel_a_finished_booking(env):
    add_booking(env.db, status="came")
    assert env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000001/cancel").status_code == 400


def test_public_rate_limits_ip_60_get_token_only_counts_posts_status_has_its_own(env):
    codes = [env.client.get(P).status_code for _ in range(62)]
    assert codes[:60] == [200] * 60 and codes[60] == 429                       # S5: 60 per minute per IP
    last = env.client.get(P)
    assert last.status_code == 429 and last.headers["retry-after"] == "60"
    # HIGH-2: the status page has its own buckets, so the exhausted ones above do not stop it
    add_booking(env.db)
    assert env.client.get(f"{P}/booking/b0000000-0000-4000-8000-000000000001").status_code == 200


def test_status_polling_uses_its_own_bucket_and_never_spends_the_others(env):
    add_booking(env.db)
    url = f"{P}/booking/b0000000-0000-4000-8000-000000000001"
    codes = [env.client.get(url).status_code for _ in range(122)]
    assert codes[:120] == [200] * 120 and codes[120] == 429                    # 120 per booking id per minute
    assert env.client.get(P).status_code == 200                                # the page itself is unaffected
    assert env.client.get(f"{P}/days?service_id={BODY['service_id']}").status_code == 200


def test_token_bucket_counts_only_posts(env):
    for _ in range(50):
        env.client.get(P)
    assert routes._token_post_limiter._hits.get(TOKEN) is None                 # GETs never touch it
    env.client.post(P, json={**BODY, "phone": "123"})
    assert len(routes._token_post_limiter._hits[TOKEN]) == 1


# ═══════════════════════════ Home: bookings_today box + todays_bookings list ═══════════════════════════

def _home(env, ctx):
    from app.services import home_today as h
    return h.compute_today(env.db, ctx, now=NOW)


def test_home_list_shape_is_exactly_what_the_screen_reads(env):
    add_booking(env.db, start=ist("2026-11-23", "11:00"))
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", customer_name=None, resource_id="2e000000-0000-4000-8000-000000000002", start=ist("2026-11-23", "12:00"))
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000003", number=3, phone="+912", status="came", start=ist("2026-11-23", "09:00"))
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000004", number=4, phone="+913", start=ist("2026-11-24", "10:00"))      # tomorrow
    out = _home(env, OWNER)
    assert "bookings_today" in out["available"]
    assert out["boxes"]["bookings_today"]["value"] == 3 and out["boxes"]["bookings_today"]["sub"] == "1 came · 0 didn't come"
    assert out["boxes"]["bookings_today"]["unit"] == "count" and out["boxes"]["bookings_today"]["href"] == "/dashboard/bookings"
    lst = out["todays_bookings"]
    assert set(lst) == {"total", "items"} and lst["total"] == 2
    assert [i["id"] for i in lst["items"]] == ["b0000000-0000-4000-8000-000000000001", "b0000000-0000-4000-8000-000000000002"]
    assert set(lst["items"][0]) == {"id", "start_at", "status", "customer_name", "service_name", "resource_name"}
    assert lst["items"][0] == {"id": "b0000000-0000-4000-8000-000000000001", "start_at": bk.iso(ist("2026-11-23", "11:00")), "status": "booked",
                               "customer_name": "Priya", "service_name": "Reading", "resource_name": "Ravi"}
    assert lst["items"][1]["customer_name"] == "+911" and lst["items"][1]["resource_name"] == "Chair 2"


def test_home_list_is_the_next_ten_only_and_skips_finished_slots(env):
    for i in range(12):
        add_booking(env.db, id=f"B{i}", number=i + 1, phone=f"+91{i:03d}", resource_id="2e000000-0000-4000-8000-000000000002" if i % 2 else "2e000000-0000-4000-8000-000000000001",
                    start=ist("2026-11-23", "13:00") + timedelta(minutes=15 * i))
    add_booking(env.db, id="OLD", number=99, phone="+91999", start=ist("2026-11-23", "08:00"))   # already over
    lst = _home(env, OWNER)["todays_bookings"]
    assert lst["total"] == 12 and len(lst["items"]) == 10 and "OLD" not in [i["id"] for i in lst["items"]]


def test_home_bookings_need_bookings_view_and_a_service_set_up(env):
    add_booking(env.db, start=ist("2026-11-23", "11:00"))
    nobody = _home(env, {**NOBODY})
    assert "bookings_today" not in nobody["available"] and nobody["todays_bookings"] is None
    env.db.rows("booking_services").clear()
    owner = _home(env, OWNER)
    assert "bookings_today" not in owner["available"] and owner["todays_bookings"] is None


def test_home_bookings_are_column_scoped_for_a_linked_person(env):
    add_booking(env.db, start=ist("2026-11-23", "11:00"))                          # R1 Ravi
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", resource_id="2e000000-0000-4000-8000-000000000002", start=ist("2026-11-23", "12:00"))
    out = _home(env, RAVI)
    assert out["boxes"]["bookings_today"]["value"] == 1
    assert [i["id"] for i in out["todays_bookings"]["items"]] == ["b0000000-0000-4000-8000-000000000001"]


def test_home_never_leaks_another_business(env):
    env.db.add("booking_services", id="SX", tenant_id=T2, name="Other", duration_min=30, price_paise=0,
               advance_paise=0, gap_after_min=0, active=True, sort=0)
    add_booking(env.db, tenant_id=T2, start=ist("2026-11-23", "11:00"))
    other = {"tenant_id": T2, "user_id": "u-o", "role": "owner", "permissions": []}
    assert _home(env, other)["todays_bookings"] in (None, {"total": 0, "items": []})
    assert _home(env, OWNER)["todays_bookings"] == {"total": 0, "items": []}


# ═══════════════════════════ Move picker: exclude_booking_id ═══════════════════════════

def test_free_times_can_ignore_the_bookings_own_slot_when_moving(env):
    add_booking(env.db)                                                  # R1, 10:00-10:30
    c = as_(env, MANAGER)
    base = "/api/v1/bookings/free?service_id=5e000000-0000-4000-8000-000000000001&resource_id=2e000000-0000-4000-8000-000000000001&date=2026-11-24"
    starts = lambda r: [t["start_at"] for t in r.json()["times"]]
    own = bk.iso(ist("2026-11-24", "10:00"))
    assert own not in starts(c.get(base))                                  # its own slot looks taken
    mine = c.get(base + "&exclude_booking_id=b0000000-0000-4000-8000-000000000001")
    assert mine.status_code == 200 and own in starts(mine)                  # ...but is offered for the move
    assert bk.iso(ist("2026-11-24", "10:15")) in starts(mine)               # an overlap with its own slot


def test_free_days_accept_exclude_booking_id(env):
    add_booking(env.db)
    c = as_(env, MANAGER)
    res = c.get("/api/v1/bookings/free-days?service_id=5e000000-0000-4000-8000-000000000001&resource_id=2e000000-0000-4000-8000-000000000001&exclude_booking_id=b0000000-0000-4000-8000-000000000001")
    assert res.status_code == 200 and "2026-11-24" in res.json()["dates"]


def test_exclude_booking_id_must_be_this_businesses_booking(env):
    env.db.add("bookings", id="BX", tenant_id=T2, number=1, phone="+911", service_id="5e000000-0000-4000-8000-000000000001", resource_id="2e000000-0000-4000-8000-000000000001",
               start_at=SLOT, end_at=SLOT, block_end_at=SLOT, booking_date="2026-11-24", status="booked")
    c = as_(env, MANAGER)
    base = "/api/v1/bookings/free?service_id=5e000000-0000-4000-8000-000000000001&date=2026-11-24&exclude_booking_id="
    assert c.get(base + "BX").status_code == 404                           # another business's
    assert c.get(base + "nope").status_code == 404
    assert c.get(base + "x" * 80).status_code in (404, 422)
    assert c.get("/api/v1/bookings/free-days?service_id=5e000000-0000-4000-8000-000000000001&exclude_booking_id=BX").status_code == 404


def test_day_and_week_carry_the_dates_the_screens_compare_against(env):
    day = as_(env, OWNER).get("/api/v1/bookings/day?date=2026-11-25").json()
    assert day["date"] == "2026-11-25"
    week = as_(env, OWNER).get("/api/v1/bookings/week?start=2026-11-25").json()
    assert week["start"] == "2026-11-23" and week["days"][0]["date"] == "2026-11-23"


# ═══════════════════════════ review + security fixes (API level) ═══════════════════════════

def test_s8_link_url_only_for_managers(env):
    assert as_(env, MANAGER).get("/api/v1/bookings/setup").json()["link_url"].endswith(f"/book/{TOKEN}")
    assert as_(env, VIEWER).get("/api/v1/bookings/setup").json()["link_url"] is None
    assert as_(env, RAVI).get("/api/v1/bookings/setup").json()["link_url"] is None


def test_s9_team_rows_say_whether_the_person_can_see_bookings(env):
    env.db.add("tenant_users", tenant_id=T1, user_id="u-owner", full_name="Owner", role="owner")
    env.db.add("tenant_users", tenant_id=T1, user_id="u-ravi", full_name="Ravi", role="caller")
    with patch("app.services.rbac.resolve_permissions",
               side_effect=lambda db, tid, uid, role: {"permissions": ["bookings.view"] if uid == "u-ravi" else []}):
        team = {t["user_id"]: t for t in as_(env, MANAGER).get("/api/v1/bookings/setup").json()["team"]}
    assert team["u-owner"]["has_view"] is True and team["u-ravi"]["has_view"] is True
    env.db.add("tenant_users", tenant_id=T1, user_id="u-x", full_name="X", role="caller")
    with patch("app.services.rbac.resolve_permissions", return_value={"permissions": ["leads.view"]}):
        team = {t["user_id"]: t for t in as_(env, MANAGER).get("/api/v1/bookings/setup").json()["team"]}
    assert team["u-x"]["has_view"] is False


def test_the_board_shape_carries_source_and_phone_checked_everywhere(env):
    add_booking(env.db, phone_checked=True)
    c = as_(env, MANAGER)
    day = c.get("/api/v1/bookings/day?date=2026-11-24").json()["bookings"][0]
    week = [b for d in c.get("/api/v1/bookings/week?start=2026-11-23").json()["days"] for b in d["bookings"]][0]
    assert day["source"] == "phone" and day["phone_checked"] is True and week["source"] == "phone"
    made = c.post("/api/v1/bookings", json={"service_id": "5e000000-0000-4000-8000-000000000001",
                                            "resource_id": "2e000000-0000-4000-8000-000000000002", "start_at": SLOT,
                                            "phone": "9876500002", "customer_name": "Asha"}).json()
    assert made["source"] == "phone" and "phone_checked" in made
    moved = c.post(f"/api/v1/bookings/{made['id']}/move", json={"start_at": ist("2026-11-24", "11:00").isoformat()}).json()
    assert "source" in moved and "phone_checked" in moved


def test_s6_malformed_ids_never_give_a_500(env):
    c = as_(env, OWNER)
    assert c.get("/api/v1/bookings/free?service_id=nope&date=2026-11-24").status_code in (400, 404)
    assert c.get("/api/v1/bookings/free-days?service_id=nope").status_code in (400, 404)
    ok = "5e000000-0000-4000-8000-000000000001"
    assert c.get(f"/api/v1/bookings/free-days?service_id={ok}&exclude_booking_id=nope").status_code == 404
    assert c.post("/api/v1/bookings/nope/cancel").status_code == 404
    assert c.post("/api/v1/bookings/nope/came").status_code == 404
    assert c.post("/api/v1/bookings/nope/move", json={"start_at": SLOT}).status_code == 404
    assert c.patch("/api/v1/bookings/services/nope", json={"name": "x"}).status_code == 404
    assert c.patch("/api/v1/bookings/resources/nope", json={"name": "x"}).status_code == 404
    assert c.post("/api/v1/bookings", json={**BODY, "service_id": "nope", "customer_name": "P"}).status_code == 400
    # the customer's link
    assert env.client.post(P, json={**BODY, "service_id": "nope"}).status_code == 404
    assert env.client.post(P, json={**BODY, "resource_id": "nope"}).status_code == 400
    assert env.client.get(f"{P}/days?service_id={ok}&resource_id=nope").status_code == 400
    assert env.client.get(f"{P}/booking/nope").status_code == 404
    assert env.client.post(f"{P}/booking/nope/cancel").status_code == 404
    assert env.client.post(f"{P}/booking/nope/move", json={"start_at": SLOT}).status_code == 404


def test_s2_s4_public_phone_and_generic_errors_over_http(env):
    bad = env.client.post(P, json={**BODY, "phone": "12345"})
    assert bad.status_code == 400 and bad.json()["detail"] == "Please enter a 10-digit mobile number"
    assert env.client.post(P, json={**BODY, "name": "see http://x.co"}).status_code == 400
    assert env.client.post(P, json=BODY).status_code == 200
    same_day = env.client.post(P, json={**BODY, "start_at": ist("2026-11-24", "11:00").isoformat()})
    assert same_day.status_code == 409 and same_day.json()["detail"] == bk.PUBLIC_CANT_BOOK
    # staff still get the specific words for the same situation
    staff = as_(env, MANAGER).post("/api/v1/bookings", json={**BODY, "customer_name": "P",
                                   "start_at": ist("2026-11-24", "11:00").isoformat()})
    assert staff.status_code == 409 and "already has a booking" in staff.json()["detail"]


def test_s2_three_unchecked_holds_per_ip_then_429_with_whatsapp_in_the_words(env):
    times = ["10:00", "11:00", "12:00", "16:00"]
    codes = []
    for i, hhmm in enumerate(times):
        res = env.client.post(P, json={**BODY, "phone": f"98765000{i:02d}", "start_at": ist("2026-11-24", hhmm).isoformat()})
        codes.append(res.status_code)
    assert codes == [200, 200, 200, 429]
    assert res.json()["detail"] == "Too many bookings waiting — please confirm one on WhatsApp first"
    assert "whatsapp" in res.json()["detail"].lower()
    # once one is proved (no longer an unchecked hold) the address may book again
    row = env.db.rows("bookings")[0]
    row.update(status="booked", phone_checked=True, hold_until=None)
    again = env.client.post(P, json={**BODY, "phone": "9876500009", "start_at": ist("2026-11-24", "16:00").isoformat()})
    assert again.status_code == 200


def test_s1_status_route_asks_b2_to_flip_a_held_booking_and_returns_the_fresh_row(env):
    add_booking(env.db, status="held", phone_checked=False, hold_until=bk.iso(NOW + timedelta(minutes=10)))
    url = f"{P}/booking/b0000000-0000-4000-8000-000000000001"

    async def flip(db, tid, booking):                                    # what B2's confirm_if_ready does on success
        db.rows("bookings")[0].update(status="booked", phone_checked=True, hold_until=None)
        return db.rows("bookings")[0]
    env.msgs.confirm_if_ready.side_effect = flip
    b = env.client.get(url).json()
    assert env.msgs.confirm_if_ready.await_count == 1
    assert b["status"] == "booked" and b["phone_checked"] is True and b["hold_until"] is None
    env.client.get(url)
    assert env.msgs.confirm_if_ready.await_count == 1                    # a booked booking is not sent to B2 again


def test_s7_the_public_move_route_stops_after_three_moves(env):
    add_booking(env.db, moved_count=3)
    res = env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000001/move",
                          json={"start_at": ist("2026-11-24", "11:00").isoformat()})
    assert res.status_code == 403 and res.json()["detail"] == "Please call the business to change it again"
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+919000000002", moved_count=2,
                start=ist("2026-11-25", "10:00"))
    ok = env.client.post(f"{P}/booking/b0000000-0000-4000-8000-000000000002/move",
                         json={"start_at": ist("2026-11-25", "11:00").isoformat()})
    assert ok.status_code == 200 and ok.json()["moves_left"] == 0


def test_med1_cancel_over_http_calls_release_unpaid_order(env):
    add_booking(env.db)
    with patch("app.services.booking_orders.release_unpaid_order") as release:
        assert as_(env, MANAGER).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/cancel").status_code == 200
    release.assert_called_once()


def test_med3_a_lost_race_over_http_is_409_with_the_refresh_words(env):
    add_booking(env.db)
    stale = dict(env.db.rows("bookings")[0])
    env.db.rows("bookings")[0]["status"] = "cancelled"
    with patch.object(bk, "get_booking", return_value=stale):
        res = as_(env, MANAGER).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/cancel")
    assert res.status_code == 409 and res.json()["detail"] == "This booking just changed — refresh"


def test_low_the_public_page_hides_services_nobody_can_do(env):
    env.db.add("booking_services", id="5e000000-0000-4000-8000-000000000003", tenant_id=T1, name="Orphan", duration_min=30,
               price_paise=100, advance_paise=0, gap_after_min=0, active=True, sort=2, catalog_item_id=None)
    names = [s["name"] for s in env.client.get(P).json()["services"]]
    assert "Orphan" not in names and "Reading" in names


def test_low_a_previous_day_booking_whose_gap_spills_over_shows_on_the_board(env):
    late = ist("2026-11-23", "23:50")
    add_booking(env.db, start=late, end_at=bk.iso(late + timedelta(minutes=5)), block_end_at=bk.iso(late + timedelta(minutes=40)),
                booking_date="2026-11-23")
    day = as_(env, MANAGER).get("/api/v1/bookings/day?date=2026-11-24").json()
    assert [b["id"] for b in day["bookings"]] == ["b0000000-0000-4000-8000-000000000001"]


def test_low_came_returns_the_order_link_only_to_people_who_may_see_money(env):
    add_booking(env.db, start=ist("2026-11-23", "09:00"))
    with patch("app.services.booking_orders.order_for_came", new=AsyncMock(return_value="d0000000-0000-4000-8000-000000000001")):
        res = as_(env, MANAGER).post("/api/v1/bookings/b0000000-0000-4000-8000-000000000001/came")
    assert res.status_code == 200 and res.json()["href"] is None
    assert res.json()["deal_id"] == "d0000000-0000-4000-8000-000000000001"


# ═══════════════════════════ the download (v9.2 #27) ═══════════════════════════

import csv as _csv
import io as _io

DOWNLOADER = {**MANAGER, "permissions": ["bookings.manage", "leads.download"]}
DOWNLOADER_MONEY = {**DOWNLOADER, "permissions": ["bookings.manage", "leads.download", "deals.view"]}
RAVI_DL = {**RAVI, "permissions": ["bookings.view", "leads.download"]}


def _export(env, ctx, qs=""):
    res = as_(env, ctx).get("/api/v1/bookings/export" + qs)
    rows = list(_csv.DictReader(_io.StringIO(res.content.decode("utf-8-sig")))) if res.status_code == 200 else None
    return res, rows


def test_export_needs_download_permission(env):
    add_booking(env.db)
    assert _export(env, MANAGER, "?start=2026-11-24")[0].status_code == 403
    assert _export(env, NOBODY, "?start=2026-11-24")[0].status_code == 403
    assert env.db.rows("app_audit_logs") == []


def test_export_day_columns_and_activity_log(env):
    add_booking(env.db, customer_name="=cmd|' /C calc'!A0", status="came")
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", start=ist("2026-11-25", "11:00"))
    res, rows = _export(env, DOWNLOADER, "?start=2026-11-24")
    assert res.status_code == 200 and res.headers["content-disposition"].endswith("bookings_2026-11-24.csv")
    assert len(rows) == 1 and rows[0]["code"] == "BK-0001" and rows[0]["status"] == "Came"
    assert rows[0]["date"] == "2026-11-24" and rows[0]["time"] == "10:00" and rows[0]["phone"] == '="+919876543210"'
    assert rows[0]["customer"].startswith("'=")                   # never runs as a formula
    assert "advance_amount_rupees" not in rows[0]                 # no deals.view
    log = [r for r in env.db.rows("app_audit_logs") if r.get("action") == "leads.download"]
    assert log[0]["metadata"]["list"] == "Bookings" and log[0]["metadata"]["rows"] == 1 and log[0]["tenant_id"] == T1


def test_export_week_range_and_bad_ranges(env):
    add_booking(env.db)
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", start=ist("2026-11-27", "11:00"))
    _, rows = _export(env, DOWNLOADER, "?start=2026-11-23&end=2026-11-29")
    assert [r["code"] for r in rows] == ["BK-0001", "BK-0002"]
    assert _export(env, DOWNLOADER, "?start=2026-11-29&end=2026-11-23")[0].status_code == 400
    assert _export(env, DOWNLOADER, "?start=2026-01-01&end=2026-12-31")[0].status_code == 400
    assert _export(env, DOWNLOADER, "?start=soon")[0].status_code == 400


def test_export_amount_only_with_deals_view_and_owner_sees_it(env):
    add_booking(env.db, advance_paise=20050)
    assert "advance_amount_rupees" not in _export(env, DOWNLOADER, "?start=2026-11-24")[1][0]
    assert _export(env, DOWNLOADER_MONEY, "?start=2026-11-24")[1][0]["advance_amount_rupees"] == "200.5"
    assert _export(env, OWNER, "?start=2026-11-24")[1][0]["advance_amount_rupees"] == "200.5"


def test_export_keeps_the_staff_members_column_scope_and_skips_cancelled(env):
    add_booking(env.db)                                               # R1 (Ravi)
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000002", number=2, phone="+911", resource_id="2e000000-0000-4000-8000-000000000002")
    add_booking(env.db, id="b0000000-0000-4000-8000-000000000003", number=3, phone="+912", status="cancelled")
    assert [r["code"] for r in _export(env, RAVI_DL, "?start=2026-11-24")[1]] == ["BK-0001"]
    assert [r["code"] for r in _export(env, OWNER, "?start=2026-11-24")[1]] == ["BK-0001", "BK-0002"]


def test_export_never_reads_another_business(env):
    add_booking(env.db, tenant_id=T2)
    assert _export(env, OWNER, "?start=2026-11-24")[1] == []
