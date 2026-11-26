"""Home (Today): who sees which box, the defaults, the Edit Today layout rules, and that one
failing source never breaks the answer. Sources are stubbed; the DB is a small recorder."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import home_today as h


class _Q:
    """Any query chain; execute() answers from the table's configured rows (or raises)."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.ops = []

    def __getattr__(self, name):
        def call(*a, **k):
            self.ops.append((name, a, k))
            return self
        return call

    @property
    def not_(self):
        return self

    def execute(self):
        err = self.db.errors.get(self.table)
        if err:
            raise err
        if self.ops and self.ops[0][0] in ("upsert", "delete"):
            self.db.writes.append((self.table, self.ops[0]))
        rows = self.db.rows.get(self.table, [])
        return MagicMock(data=rows, count=len(rows))


class FakeDB:
    def __init__(self, rows=None, errors=None):
        self.rows = rows or {}
        self.errors = errors or {}
        self.writes = []
        self.rpc_calls = []

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _Q(self, "rpc:" + name)


ALL_BOXES_DB = {
    "deals": [{"id": "d1"}],
    "catalog_items": [{"id": "c1"}],
    "booking_services": [{"id": "s1"}],
    "cash_expenses": [{"id": "e1"}],
    "tenants": [{"enabled_features": ["inbound_messaging", "telecalling.scheduled"]}],
}


def _ctx(role="owner", permissions=()):
    return {"tenant_id": "t1", "user_id": "u1", "role": role, "caller_id": None, "permissions": list(permissions)}


@pytest.fixture
def stub_sources(monkeypatch):
    cards = {
        "money_in": {"paise": 2465000, "orders": 8, "refunded_paise": 0},
        "to_collect": {"paise": 500000, "orders": 3, "reminders_on": 0},
        "to_pack": {"orders": 4, "over_2_days": 1},
        "gst": {"paise": 0, "bills": 0},
    }
    monkeypatch.setattr(h, "_orders_cards", lambda db, tid, t: cards)
    box = lambda v: {"value": v, "unit": "count", "sub": "x"}
    monkeypatch.setattr(h, "_box_quotes_open", lambda db, tid, t: box(2))
    monkeypatch.setattr(h, "_box_new_enquiries", lambda db, tid, t: box(23))
    monkeypatch.setattr(h, "_box_won_month", lambda db, tid, t: box(5))
    monkeypatch.setattr(h, "_box_callbacks", lambda db, tid, t: box(7))
    monkeypatch.setattr(h, "_box_ads", lambda db, tid: box(9))
    monkeypatch.setattr(h, "_box_profit", lambda db, ctx, t: {"value": 4800000, "unit": "paise", "sub": "Nov so far"})
    monkeypatch.setattr(h, "_box_expenses_today", lambda db, tid, t: {"value": 120000, "unit": "paise", "sub": "3 expenses"})
    monkeypatch.setattr(h, "_feedback", lambda db, ctx, t: {
        "box": {"value": 4.3, "unit": "stars", "sub": "12 answered \u00b7 2 unhappy open"},
        "list": {"total": 1, "items": [{"id": "f1", "lead_id": "l1", "name": "Arun", "stars": 5, "reason": None}]}})
    monkeypatch.setattr("app.services.customer_feedback.is_on", lambda tid: True)
    monkeypatch.setattr(h, "_waiting_list", lambda db, ctx: {"total": 7, "items": [{"lead_id": "l1"}]})
    bar = {"lead_id": "l1", "name": "Arun", "waiting_since": "2026-11-21T04:00:00+00:00",
           "last_message": "price?", "phone": "+9199"}
    monkeypatch.setattr(h, "_hot", lambda db, ctx: (2, bar))
    monkeypatch.setattr(h, "_low_stock", lambda db, tid: {"total": 2, "items": [
        {"item_id": "c1", "name": "Ring", "stock": 0, "low_stock_at": 3}]})


def test_owner_sees_all_in_priority_order_and_defaults_are_first_six(stub_sources):
    out = h.compute_today(FakeDB(ALL_BOXES_DB), _ctx())
    assert out["available"] == list(h.BOX_KEYS)
    assert out["defaults"] == list(h.BOX_KEYS[:6])
    assert set(out["boxes"]) == set(h.BOX_KEYS)
    assert out["boxes"]["money_in_today"] == {
        "value": 2465000, "unit": "paise", "sub": "8 orders paid", "href": "/dashboard/deals"}
    assert out["boxes"]["to_collect"]["value"] == 500000
    assert out["boxes"]["orders_pending"]["value"] == 4
    assert out["hot_bar"]["name"] == "Arun"
    assert out["waiting"]["total"] == 7
    assert out["low_stock"]["total"] == 2


def test_role_without_deals_view_gets_no_commerce_boxes(stub_sources):
    ctx = _ctx("staff", ["dashboard.view", "conversations.view", "catalog.view"])
    out = h.compute_today(FakeDB(ALL_BOXES_DB), ctx)
    for k in ("money_in_today", "to_collect", "orders_pending", "quotes_open"):
        assert k not in out["available"] and k not in out["boxes"]
    assert "hot_waiting" in out["available"] and "low_stock" in out["available"]


def test_no_conversations_view_means_no_waiting_no_hot_bar(stub_sources):
    ctx = _ctx("staff", ["dashboard.view", "deals.view"])
    out = h.compute_today(FakeDB(ALL_BOXES_DB), ctx)
    assert out["waiting"] is None and out["hot_bar"] is None
    assert "hot_waiting" not in out["available"]
    assert "money_in_today" in out["available"]


def test_manage_implies_view(stub_sources):
    out = h.compute_today(FakeDB(ALL_BOXES_DB), _ctx("staff", ["deals.manage"]))
    assert "money_in_today" in out["available"]


def test_client_that_does_not_use_a_module_gets_no_box(stub_sources):
    db = FakeDB({"deals": [], "catalog_items": [], "tenants": [{"enabled_features": []}]})
    out = h.compute_today(db, _ctx())
    for k in ("money_in_today", "to_collect", "orders_pending", "quotes_open", "low_stock",
              "new_enquiries_today", "won_month", "callbacks_today"):
        assert k not in out["available"]
    assert out["low_stock"] is None
    assert "hot_waiting" in out["available"]


def test_callbacks_follow_the_call_iq_feature_rule():
    assert h._callbacks_feature_on({"callbacks"})
    assert h._callbacks_feature_on({"telecalling.scheduled", "telecalling.dialer"})
    assert not h._callbacks_feature_on({"telecalling.dialer"})
    assert h._callbacks_feature_on({"telecalling_sim"})
    assert not h._callbacks_feature_on(set())


def test_defaults_cap_at_six_and_can_be_fewer(stub_sources):
    out = h.compute_today(FakeDB({"deals": [], "tenants": [{"enabled_features": []}]}), _ctx("staff", ["dashboard.view", "conversations.view"]))
    assert out["available"] == ["hot_waiting"]
    assert out["defaults"] == ["hot_waiting"]


def test_one_failing_source_is_left_out_not_a_500(stub_sources, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(h, "_box_callbacks", boom)
    monkeypatch.setattr(h, "_waiting_list", boom)
    monkeypatch.setattr(h, "_low_stock", boom)
    out = h.compute_today(FakeDB(ALL_BOXES_DB), _ctx())
    assert "callbacks_today" not in out["available"] and "callbacks_today" not in out["boxes"]
    assert out["waiting"] is None
    assert out["low_stock"] is None and "low_stock" not in out["available"]
    assert "money_in_today" in out["available"] and out["hot_bar"] is not None
    assert out["defaults"] == out["available"][:6]


def test_failing_orders_cards_drops_only_the_money_boxes(stub_sources, monkeypatch):
    monkeypatch.setattr(h, "_orders_cards", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    out = h.compute_today(FakeDB(ALL_BOXES_DB), _ctx())
    for k in ("money_in_today", "to_collect", "orders_pending"):
        assert k not in out["available"]
    assert "quotes_open" in out["available"]


def test_ads_box_absent_when_no_campaign_connected(stub_sources, monkeypatch):
    monkeypatch.setattr(h, "_box_ads", lambda db, tid: None)
    assert "ads_today" not in h.compute_today(FakeDB(ALL_BOXES_DB), _ctx())["available"]


# ───────────────────────────────────────────────────────────── routes

@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_and_role] = lambda: _ctx()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _use_db(monkeypatch, db):
    monkeypatch.setattr("app.routes.home.get_supabase", lambda: db)


def test_today_route_needs_dashboard_view(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_and_role] = lambda: _ctx("staff", ["deals.view"])
    try:
        assert TestClient(app).get("/api/v1/home/today").status_code == 403
        assert TestClient(app).get("/api/v1/home/layout").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_today_route_returns_the_contract_shape(client, monkeypatch, stub_sources):
    _use_db(monkeypatch, FakeDB(ALL_BOXES_DB))
    body = client.get("/api/v1/home/today").json()
    assert set(body) == {"available", "defaults", "boxes", "hot_bar", "waiting", "low_stock", "todays_bookings",
                         "todays_feedback"}


def test_layout_get_without_row_is_the_no_row_shape(client, monkeypatch):
    _use_db(monkeypatch, FakeDB({"home_layouts": []}))
    assert client.get("/api/v1/home/layout").json() == {"boxes": None, "lists": None, "is_custom": False}


def test_layout_get_with_row(client, monkeypatch):
    _use_db(monkeypatch, FakeDB({"home_layouts": [{"boxes": ["to_collect"], "lists": {"waiting": False, "low_stock": True}}]}))
    assert client.get("/api/v1/home/layout").json() == {
        "boxes": ["to_collect"], "lists": {"waiting": False, "low_stock": True}, "is_custom": True}


MISSING = Exception("Could not find the table 'public.home_layouts' in the schema cache (PGRST205)")


def test_missing_table_get_is_no_row_put_and_delete_are_503(client, monkeypatch):
    _use_db(monkeypatch, FakeDB(errors={"home_layouts": MISSING}))
    assert client.get("/api/v1/home/layout").json() == {"boxes": None, "lists": None, "is_custom": False}
    put = client.put("/api/v1/home/layout", json={"boxes": ["to_collect"], "lists": {"waiting": True, "low_stock": True}})
    assert put.status_code == 503 and put.json() == {"detail": "Home layouts not ready"}
    delete = client.delete("/api/v1/home/layout")
    assert delete.status_code == 503 and delete.json() == {"detail": "Home layouts not ready"}


@pytest.mark.parametrize("body", [
    {"boxes": ["nope"], "lists": {"waiting": True, "low_stock": True}},
    {"boxes": list(h.BOX_KEYS) + ["money_in_today"] + ["x1", "x2"], "lists": {}},
    {"boxes": ["to_collect", "to_collect"], "lists": {"waiting": True, "low_stock": True}},
    {"boxes": ["to_collect"], "lists": {"bookings": True}},
    {"boxes": "to_collect", "lists": {}},
])
def test_put_validation_is_422_and_writes_nothing(client, monkeypatch, body):
    db = FakeDB()
    _use_db(monkeypatch, db)
    assert client.put("/api/v1/home/layout", json=body).status_code == 422
    assert db.writes == []


def test_put_more_than_twelve_is_422(client, monkeypatch):
    _use_db(monkeypatch, FakeDB())
    # 13 unknown keys: still 422 (too many, and unknown).
    assert client.put("/api/v1/home/layout", json={"boxes": [f"k{i}" for i in range(13)], "lists": {}}).status_code == 422


def test_more_boxes_exist_than_one_person_can_turn_on(client, monkeypatch):
    """BOX_KEYS is now 15; MAX_BOXES (12) is how many a person turns on. 12 real keys save, 13 do not."""
    assert len(h.BOX_KEYS) > h.MAX_BOXES == 12
    db = FakeDB()
    _use_db(monkeypatch, db)
    ok = client.put("/api/v1/home/layout", json={"boxes": list(h.BOX_KEYS[:12]), "lists": {}})
    assert ok.status_code == 200 and len(ok.json()["boxes"]) == 12
    too_many = client.put("/api/v1/home/layout", json={"boxes": list(h.BOX_KEYS[:13]), "lists": {}})
    assert too_many.status_code == 422
    new = client.put("/api/v1/home/layout", json={"boxes": ["profit_month", "expenses_today", "feedback_week"],
                                                 "lists": {"todays_feedback": False}})
    assert new.status_code == 200 and new.json()["lists"]["todays_feedback"] is False


def test_put_saves_and_returns_the_get_shape(client, monkeypatch):
    db = FakeDB()
    _use_db(monkeypatch, db)
    res = client.put("/api/v1/home/layout", json={"boxes": ["to_collect", "money_in_today"], "lists": {"waiting": False}})
    assert res.status_code == 200
    assert res.json() == {"boxes": ["to_collect", "money_in_today"],
                          "lists": {"waiting": False, "low_stock": True, "todays_bookings": True, "todays_feedback": True},
                          "is_custom": True}
    table, (op, args, kwargs) = db.writes[0]
    assert table == "home_layouts" and op == "upsert"
    assert args[0]["tenant_id"] == "t1" and args[0]["user_id"] == "u1"
    assert kwargs == {"on_conflict": "tenant_id,user_id"}


def test_delete_returns_not_custom(client, monkeypatch):
    db = FakeDB()
    _use_db(monkeypatch, db)
    res = client.delete("/api/v1/home/layout")
    assert res.status_code == 200 and res.json() == {"boxes": None, "lists": None, "is_custom": False}
    assert db.writes and db.writes[0][1][0] == "delete"


# ───────────────────────────────────────────────────────────── real sources on a fake DB

def test_low_stock_uses_alert_level_default_five_and_held_stock():
    db = FakeDB({"catalog_items": [
        {"id": "a", "name": "Ring", "stock_quantity": 0, "low_stock_at": None, "item_type": "product"},
        {"id": "b", "name": "Chain", "stock_quantity": 4, "low_stock_at": 3, "item_type": "product"},
        {"id": "c", "name": "Bangle", "stock_quantity": 9, "low_stock_at": 10, "item_type": "product"},
        {"id": "d", "name": "Plenty", "stock_quantity": 50, "low_stock_at": None, "item_type": "product"},
        {"id": "e", "name": "Repair", "stock_quantity": 0, "low_stock_at": None, "item_type": "service"},
    ], "deal_items": []})
    out = h._low_stock(db, "t1")
    assert out["total"] == 2
    assert [i["name"] for i in out["items"]] == ["Ring", "Bangle"]
    assert out["items"][0]["stock"] == 0
    assert h._box_low_stock(out)["sub"] == "1 out of stock"


def test_quotes_open_skips_expired_ones():
    db = FakeDB({"deals": [
        {"id": "1", "total_paise": 100000, "quote_valid_until": None},
        {"id": "2", "total_paise": 50000, "quote_valid_until": "2000-01-01"},
        {"id": "3", "total_paise": 25000, "quote_valid_until": "2999-01-01"},
    ]})
    box = h._box_quotes_open(db, "t1", h._times(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
    assert box["value"] == 2 and box["sub"] == "worth \u20b91,250"


def test_needs_you_rows_keep_only_the_needs_you_group(monkeypatch):
    monkeypatch.setattr("app.routes.conversations.get_setting", lambda *a, **k: "true")
    db = FakeDB({
        "rpc:get_inbox_chats": [
            {"lead_id": "l1", "inbox_group": 0, "waiting_since": "2026-11-21T04:00:00+00:00",
             "last_reply_at": None, "last_message_content": "price?"},
            {"lead_id": "l2", "inbox_group": 1, "waiting_since": None, "last_reply_at": "2026-11-21T05:00:00+00:00",
             "last_message_content": "ok"},
        ],
        "leads": [{"id": "l1", "name": "Arun", "phone": "+91", "segment": "A"},
                  {"id": "l2", "name": "Bala", "phone": "+92", "segment": "B"}],
    })
    rows = h._needs_you_rows(db, _ctx(), 3, "A")
    assert [r["lead_id"] for r in rows] == ["l1"] and rows[0]["name"] == "Arun" and rows[0]["segment"] == "A"
    name, params = db.rpc_calls[0]
    assert name == "get_inbox_chats" and params["p_view"] == "needs_you" and params["p_segments"] == ["A"]
    assert params["p_tenant_id"] == "t1"


# ───────────────────────────────────────────────────────────── profit, expenses, feedback (gates)

def _db(**tables):
    base = {"deals": [{"id": "d1"}], "cash_expenses": [{"id": "e1"}], "tenants": [{"enabled_features": []}]}
    base.update(tables)
    return FakeDB(base)


@pytest.mark.parametrize("role,perms,shown", [
    ("owner", [], True),
    ("staff", ["deals.view", "purchases.view"], True),
    ("staff", ["deals.manage", "purchases.manage"], True),
    ("staff", ["deals.view"], False),
    ("staff", ["purchases.view"], False),
    ("staff", ["analytics.view"], False),
])
def test_profit_gate_is_orders_and_purchases(stub_sources, role, perms, shown):
    out = h.compute_today(_db(), _ctx(role, perms))
    assert ("profit_month" in out["available"]) is shown
    assert ("profit_month" in out["boxes"]) is shown
    if shown:
        assert out["boxes"]["profit_month"]["href"] == "/dashboard/analytics?tab=money"


def test_profit_hidden_when_the_shop_has_no_deals(stub_sources):
    out = h.compute_today(_db(deals=[]), _ctx())
    assert "profit_month" not in out["available"]


@pytest.mark.parametrize("role,perms,shown", [
    ("owner", [], True),
    ("staff", ["purchases.view"], True),
    ("staff", ["deals.view"], False),
])
def test_expenses_gate_is_purchases_view(stub_sources, role, perms, shown):
    out = h.compute_today(_db(), _ctx(role, perms))
    assert ("expenses_today" in out["boxes"]) is shown
    if shown:
        assert out["boxes"]["expenses_today"]["href"] == "/dashboard/expenses"


def test_expenses_hidden_until_the_shop_has_written_an_expense(stub_sources):
    assert "expenses_today" not in h.compute_today(_db(cash_expenses=[]), _ctx())["boxes"]


def test_missing_expenses_table_gives_no_box_and_nothing_else_breaks(stub_sources):
    db = FakeDB({"deals": [{"id": "d1"}], "tenants": [{"enabled_features": []}]},
                errors={"cash_expenses": Exception("Could not find the table 'public.cash_expenses' (PGRST205)")})
    out = h.compute_today(db, _ctx())
    assert "expenses_today" not in out["available"]
    assert "profit_month" in out["available"] and "money_in_today" in out["available"]


@pytest.mark.parametrize("role,perms,on,shown", [
    ("owner", [], True, True),
    ("staff", ["leads.view"], True, True),
    ("staff", ["leads.manage"], True, True),
    ("staff", ["leads.view"], False, False),
    ("staff", ["deals.view"], True, False),
])
def test_feedback_gate_is_leads_view_and_switch_on(stub_sources, monkeypatch, role, perms, on, shown):
    monkeypatch.setattr("app.services.customer_feedback.is_on", lambda tid: on)
    out = h.compute_today(_db(), _ctx(role, perms))
    assert ("feedback_week" in out["boxes"]) is shown
    assert (out["todays_feedback"] is not None) is shown
    if shown:
        assert out["boxes"]["feedback_week"]["href"] == "/dashboard/leads?tab=feedback"


def test_feedback_switch_unreadable_means_no_box_not_a_500(stub_sources, monkeypatch):
    def boom(tid):
        raise RuntimeError("settings down")
    monkeypatch.setattr("app.services.customer_feedback.is_on", boom)
    out = h.compute_today(_db(), _ctx())
    assert "feedback_week" not in out["available"] and out["todays_feedback"] is None
    assert "money_in_today" in out["available"]


def test_failing_new_sources_leave_only_themselves_out(stub_sources, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db hiccup")
    for name in ("_box_profit", "_box_expenses_today", "_feedback"):
        monkeypatch.setattr(h, name, boom)
    out = h.compute_today(_db(), _ctx())
    for k in ("profit_month", "expenses_today", "feedback_week"):
        assert k not in out["available"]
    assert out["todays_feedback"] is None
    assert "money_in_today" in out["available"] and out["defaults"] == out["available"][:6]


# ───────────────────────────────────────────────────────────── profit, expenses, feedback (values)

from datetime import datetime, timezone  # noqa: E402

from fake_supabase import FakeSupabase  # noqa: E402
from reports_seed import T1, seed, seed_money  # noqa: E402
from app.services import reports_money  # noqa: E402
from app.services.reports_common import Flags, Period  # noqa: E402
from datetime import date  # noqa: E402

UTC = timezone.utc
_REAL_FEEDBACK = h._feedback


def test_profit_box_equals_reports_money_for_this_month_so_far():
    """16 Oct 2026 afternoon IST: the box is the Reports > Money profit for 1 Oct to 16 Oct, same code."""
    db = seed_money(seed(FakeSupabase()))
    now = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    box = h._box_profit(db, _ctx(), h._times(now))
    report = reports_money.report(db, T1, Period(date(2026, 10, 1), date(2026, 10, 16)), False, Flags(True, True))
    assert box["value"] == report["period"]["profit_paise"] == 170_000 - 5_000 - 40_000 - 57_000  # 3 paid orders so far this month
    assert box["unit"] == "paise" and box["sub"] == "Oct so far"


def test_profit_box_uses_the_ist_day_to_pick_the_month(monkeypatch):
    seen = []

    def fake_compute(db, tenant_id, period, flags):
        seen.append((tenant_id, period.start, period.end, flags.sees_profit))
        return {"profit_paise": -250_000}, {}
    monkeypatch.setattr(reports_money, "compute", fake_compute)
    # 30 Nov 19:00 UTC is already 1 Dec 00:30 in India: a new month, and one day of it.
    box = h._box_profit(FakeDB(), _ctx(), h._times(datetime(2026, 11, 30, 19, 0, tzinfo=UTC)))
    assert seen == [("t1", date(2026, 12, 1), date(2026, 12, 1), True)]
    assert box == {"value": -250_000, "unit": "paise", "sub": "Dec so far"}
    # 30 Nov 18:00 UTC is 23:30 on 30 Nov in India: still November.
    seen.clear()
    box = h._box_profit(FakeDB(), _ctx(), h._times(datetime(2026, 11, 30, 18, 0, tzinfo=UTC)))
    assert seen[0][1:3] == (date(2026, 11, 1), date(2026, 11, 30)) and box["sub"] == "Nov so far"


def test_expenses_today_adds_up_todays_rows_in_this_client_only():
    db = FakeSupabase()
    db.add("cash_expenses", tenant_id="t1", day="2026-11-23", amount_paise=15_000, label="Tea")
    db.add("cash_expenses", tenant_id="t1", day="2026-11-23", amount_paise=35_000, label="Auto")
    db.add("cash_expenses", tenant_id="t1", day="2026-11-22", amount_paise=99_000, label="Yesterday")
    db.add("cash_expenses", tenant_id="t2", day="2026-11-23", amount_paise=77_000, label="Other shop")
    now = datetime(2026, 11, 23, 5, 0, tzinfo=UTC)
    assert h._box_expenses_today(db, "t1", h._times(now)) == {"value": 50_000, "unit": "paise", "sub": "2 expenses"}
    assert h._box_expenses_today(FakeSupabase(), "t1", h._times(now)) == {"value": 0, "unit": "paise", "sub": "0 expenses"}
    db.tables["cash_expenses"] = [r for r in db.rows("cash_expenses") if r["label"] == "Tea"]
    assert h._box_expenses_today(db, "t1", h._times(now))["sub"] == "1 expense"


def test_expenses_today_follows_the_ist_day_not_utc():
    db = FakeSupabase()
    db.add("cash_expenses", tenant_id="t1", day="2026-11-22", amount_paise=10_000, label="Late night")
    db.add("cash_expenses", tenant_id="t1", day="2026-11-23", amount_paise=20_000, label="Early")
    # 22 Nov 18:40 UTC is 23 Nov 00:10 in India.
    assert h._box_expenses_today(db, "t1", h._times(datetime(2026, 11, 22, 18, 40, tzinfo=UTC)))["value"] == 20_000
    # 22 Nov 18:20 UTC is 22 Nov 23:50 in India.
    assert h._box_expenses_today(db, "t1", h._times(datetime(2026, 11, 22, 18, 20, tzinfo=UTC)))["value"] == 10_000


def _fb(db, tenant, lead, stars, answered_at, status="answered", reason=None):
    db.add("customer_feedback", tenant_id=tenant, lead_id=lead, stars=stars, status=status,
           answered_at=answered_at, reason=reason, asked_at=answered_at)


def _feedback_db():
    db = FakeSupabase()
    for lead, name, caller in (("L1", "Asha", "c1"), ("L2", "Bala", "c2"), ("L3", "Chitra", "c1"), ("L4", "Devi", None)):
        db.add("leads", id=lead, tenant_id="t1", name=name, assigned_to=caller)
    db.add("leads", id="LX", tenant_id="t2", name="Other shop", assigned_to=None)
    # now = 23 Nov 2026, 10:00 IST (04:30 UTC)
    _fb(db, "t1", "L1", 5, "2026-11-23T03:00:00+00:00", reason="Great")          # today
    _fb(db, "t1", "L2", 2, "2026-11-23T02:00:00+00:00", reason="Late delivery")  # today, unhappy
    _fb(db, "t1", "L3", 4, "2026-11-20T06:00:00+00:00")                          # this week
    _fb(db, "t1", "L4", 3, "2026-11-01T06:00:00+00:00", reason="Old complaint")  # old, unhappy, still open
    _fb(db, "t1", "L1", 1, "2026-11-23T01:00:00+00:00", status="failed")        # not answered
    _fb(db, "t1", "L1", None, None, status="asked")                              # not answered
    _fb(db, "t2", "LX", 1, "2026-11-23T03:30:00+00:00")                          # another client
    return db


NOW = datetime(2026, 11, 23, 4, 30, tzinfo=UTC)


def test_feedback_box_and_list_for_the_owner():
    out = h._feedback(_feedback_db(), _ctx(), h._times(NOW))
    # stars in the week: 5, 2, 4 -> 3.7; unhappy open (answered, <= 3 stars, any date): L2 and L4
    assert out["box"] == {"value": 3.7, "unit": "stars", "sub": "3 answered · 2 unhappy open"}
    assert out["list"]["total"] == 2
    assert out["list"]["items"] == [
        {"id": out["list"]["items"][0]["id"], "lead_id": "L1", "name": "Asha", "stars": 5, "reason": "Great"},
        {"id": out["list"]["items"][1]["id"], "lead_id": "L2", "name": "Bala", "stars": 2, "reason": "Late delivery"},
    ]


def test_feedback_for_a_telecaller_counts_only_their_own_people():
    ctx = {**_ctx("caller", ["leads.view"]), "caller_id": "c1"}
    out = h._feedback(_feedback_db(), ctx, h._times(NOW))
    # c1 has L1 (5 stars today), L3 (4 stars this week) and L4 is nobody's; L4's old 3-star is not c1's
    assert out["box"] == {"value": 4.5, "unit": "stars", "sub": "2 answered · 0 unhappy open"}
    assert [i["lead_id"] for i in out["list"]["items"]] == ["L1"]
    other = {**_ctx("caller", ["leads.view"]), "caller_id": "c2"}
    got = h._feedback(_feedback_db(), other, h._times(NOW))
    assert got["box"]["sub"] == "1 answered · 1 unhappy open" and got["box"]["value"] == 2.0
    assert [i["name"] for i in got["list"]["items"]] == ["Bala"]


def test_feedback_telecaller_with_no_caller_id_sees_nothing():
    ctx = {**_ctx("caller", ["leads.view"]), "caller_id": None}
    out = h._feedback(_feedback_db(), ctx, h._times(NOW))
    assert out["box"] == {"value": None, "unit": "stars", "sub": "0 answered · 0 unhappy open"}
    assert out["list"] == {"total": 0, "items": []}


def test_feedback_never_reads_another_client():
    db = _feedback_db()
    out = h._feedback(db, _ctx(), h._times(NOW))
    assert all(i["lead_id"] != "LX" for i in out["list"]["items"])
    assert out["box"]["sub"].startswith("3 answered")


def test_feedback_list_is_newest_first_and_capped_at_five():
    db = FakeSupabase()
    for n in range(7):
        db.add("leads", id=f"L{n}", tenant_id="t1", name=f"P{n}", assigned_to=None)
        _fb(db, "t1", f"L{n}", 4, f"2026-11-23T0{n}:00:00+00:00")
    out = h._feedback(db, _ctx(), h._times(NOW))
    assert out["list"]["total"] == 7
    assert [i["lead_id"] for i in out["list"]["items"]] == ["L6", "L5", "L4", "L3", "L2"]


def test_feedback_day_and_week_edges_follow_ist():
    db = FakeSupabase()
    db.add("leads", id="L1", tenant_id="t1", name="Asha", assigned_to=None)
    # now: 23 Nov 00:10 IST (22 Nov 18:40 UTC). Today starts at 22 Nov 18:30 UTC.
    _fb(db, "t1", "L1", 5, "2026-11-22T18:35:00+00:00")   # 00:05 IST on the 23rd: today
    _fb(db, "t1", "L1", 1, "2026-11-22T18:20:00+00:00")   # 23:50 IST on the 22nd: yesterday
    # The week is 7 IST days, today included: it starts 17 Nov 00:00 IST = 16 Nov 18:30 UTC.
    _fb(db, "t1", "L1", 3, "2026-11-16T18:31:00+00:00")   # inside
    _fb(db, "t1", "L1", 3, "2026-11-16T18:29:00+00:00")   # one day too old
    out = h._feedback(db, _ctx(), h._times(datetime(2026, 11, 22, 18, 40, tzinfo=UTC)))
    assert [i["stars"] for i in out["list"]["items"]] == [5]
    # answered in the week: 5, 1, 3 -> 3.0. Unhappy open ignores dates: the 1 and both 3s.
    assert out["box"] == {"value": 3.0, "unit": "stars", "sub": "3 answered \u00b7 3 unhappy open"}


def test_feedback_with_no_answers_has_no_average_not_a_zero():
    out = h._feedback(FakeSupabase(), _ctx(), h._times(NOW))
    assert out["box"]["value"] is None and out["box"]["sub"] == "0 answered · 0 unhappy open"


def test_feedback_missing_table_gives_no_box_and_no_list(stub_sources, monkeypatch):
    monkeypatch.setattr(h, "_feedback", _REAL_FEEDBACK)
    db = FakeDB({"deals": []}, errors={"customer_feedback": Exception("PGRST205 could not find the table")})
    out = h.compute_today(db, _ctx())
    assert "feedback_week" not in out["boxes"] and out["todays_feedback"] is None


# ───────────────────────────────────────────────────────────── 7-day series (sparklines)
# NOW is 23 Nov 10:00 IST, so the 7 IST days are 17..23 Nov (oldest first, last = today).

def _lead(db, tenant, created_at, source="whatsapp", **extra):
    return db.add("leads", **{"tenant_id": tenant, "source": source, "created_at": created_at, "deleted_at": None, **extra})


def test_new_enquiries_series_buckets_per_ist_day_with_the_same_filters():
    db = FakeSupabase()
    _lead(db, "t1", "2026-11-23T08:00:00+05:30")                       # today
    _lead(db, "t1", "2026-11-23T00:10:00+05:30")                       # today, just after IST midnight
    _lead(db, "t1", "2026-11-22T23:50:00+05:30")                       # yesterday, just before midnight
    _lead(db, "t1", "2026-11-20T12:00:00+05:30")                       # 3 days ago
    _lead(db, "t1", "2026-11-17T00:00:00+05:30")                       # first day of the window
    _lead(db, "t1", "2026-11-16T23:59:00+05:30")                       # one minute too old
    _lead(db, "t2", "2026-11-23T08:00:00+05:30")                       # another client
    _lead(db, "t1", "2026-11-23T08:00:00+05:30", deleted_at="2026-11-23T09:00:00+05:30")  # deleted
    _lead(db, "t1", "2026-11-23T08:00:00+05:30", source="telecalling_upload")             # not an inbound source
    box = h._box_new_enquiries(db, "t1", h._times(NOW))
    assert box["series"] == [1, 0, 0, 1, 0, 1, 2]
    assert box["value"] == 2 and box["unit"] == "count"        # the existing fields are unchanged
    assert box["series"][-1] == box["value"]                   # last point = today's number


def test_new_enquiries_series_pages_past_the_thousand_row_cap():
    db = FakeSupabase()
    for _ in range(1205):
        _lead(db, "t1", "2026-11-23T08:00:00+05:30")
    assert h._new_enquiries_series(db, "t1", h._times(NOW)) == [0, 0, 0, 0, 0, 0, 1205]


def test_won_series_is_a_daily_count_not_month_to_date():
    db = FakeSupabase()
    _lead(db, "t1", "2026-10-01T10:00:00+05:30", converted_at="2026-11-23T11:00:00+05:30")   # old lead, won today
    _lead(db, "t1", "2026-11-22T10:00:00+05:30", converted_at="2026-11-22T11:00:00+05:30")
    _lead(db, "t1", "2026-11-22T10:00:00+05:30", converted_at="2026-11-22T15:00:00+05:30")
    _lead(db, "t1", "2026-11-05T10:00:00+05:30", converted_at="2026-11-05T11:00:00+05:30")   # this month, outside the 7 days
    _lead(db, "t1", "2026-11-18T10:00:00+05:30")                                              # not converted
    _lead(db, "t2", "2026-11-22T10:00:00+05:30", converted_at="2026-11-22T11:00:00+05:30")   # another client
    t = h._times(NOW)
    assert h._won_series(db, "t1", t) == [0, 0, 0, 0, 0, 2, 1]
    box = h._box_won_month(db, "t1", t)
    assert box["series"] == [0, 0, 0, 0, 0, 2, 1]
    assert box["value"] == 4 and box["sub"] == "bought this month"     # month-to-date value untouched


def test_callbacks_series_counts_any_status_for_the_scheduled_day():
    db = FakeSupabase()
    job = lambda tenant, when, status="pending", cadence="callback": db.add(
        "follow_up_jobs", tenant_id=tenant, cadence=cadence, status=status, scheduled_for=when)
    job("t1", "2026-11-23T16:00:00+05:30")                   # due later today
    job("t1", "2026-11-23T10:00:00+05:30", "done")           # done today: still counted
    job("t1", "2026-11-21T10:00:00+05:30", "done")
    job("t1", "2026-11-21T11:00:00+05:30", "pending")
    job("t1", "2026-11-24T00:00:00+05:30")                   # tomorrow: not in the window
    job("t1", "2026-11-16T23:00:00+05:30", "done")           # too old
    job("t1", "2026-11-22T10:00:00+05:30", cadence="welcome")  # not a call-back
    job("t2", "2026-11-22T10:00:00+05:30")                   # another client
    box = h._box_callbacks(db, "t1", h._times(NOW))
    assert box["series"] == [0, 0, 0, 0, 2, 0, 2]
    assert box["value"] == 1 and box["sub"] == "calls to make today"   # value still counts pending only


def test_money_series_is_per_day_payments_less_refunds_for_this_client_only():
    db = FakeSupabase()
    db.add("deal_payments", tenant_id="t1", amount_paise=100_000, paid_at="2026-11-23T09:00:00+05:30")
    db.add("deal_payments", tenant_id="t1", amount_paise=50_000, paid_at="2026-11-21T23:30:00+05:30")
    db.add("deal_payments", tenant_id="t1", amount_paise=70_000, paid_at="2026-11-21T00:30:00+05:30")
    db.add("deal_payments", tenant_id="t1", amount_paise=9_999, paid_at="2026-11-16T23:00:00+05:30")   # too old
    db.add("deal_payments", tenant_id="t2", amount_paise=8_888, paid_at="2026-11-23T09:00:00+05:30")   # another client
    db.add("deal_refunds", tenant_id="t1", amount_paise=30_000, status="done", created_at="2026-11-23T10:00:00+05:30")
    db.add("deal_refunds", tenant_id="t1", amount_paise=77_000, status="failed", created_at="2026-11-23T10:00:00+05:30")
    assert h._money_series(db, "t1", h._times(NOW)) == [0, 0, 0, 0, 120_000, 0, 70_000]


def _target_db(show_team=False):
    import json
    db = FakeSupabase()
    db.add("app_settings", tenant_id="t1", key="sales_target",
           value=json.dumps({"monthly_paise": 200_000_00, "months": {}, "show_team": show_team}))
    db.add("deal_payments", tenant_id="t1", amount_paise=100_000, paid_at="2026-11-22T09:00:00+05:30")
    db.add("deal_payments", tenant_id="t1", amount_paise=50_000, paid_at="2026-11-23T09:00:00+05:30")
    db.add("deals", tenant_id="t1")
    db.add("tenants", id="t1", enabled_features=[])
    return db


def test_target_box_gets_a_money_series_only_for_people_who_see_rupees(stub_sources):
    out = h.compute_today(_target_db(show_team=True), _ctx(), NOW)
    box = out["boxes"]["target_month"]
    assert box["unit"] == "paise" and box["value"] == 150_000
    assert box["series"] == [0, 0, 0, 0, 0, 100_000, 50_000]
    # a team member without Orders view: only the %, and no rupee series
    team = h.compute_today(_target_db(show_team=True), _ctx("staff", ["dashboard.view"]), NOW)
    assert team["boxes"]["target_month"]["unit"] == "percent"
    assert "series" not in team["boxes"]["target_month"]


def test_set_a_target_box_and_hot_waiting_have_no_series(stub_sources):
    out = h.compute_today(FakeDB(ALL_BOXES_DB), _ctx())
    assert out["boxes"]["target_month"]["unit"] == "set_target" and "series" not in out["boxes"]["target_month"]
    assert "series" not in out["boxes"]["hot_waiting"]


def test_a_failing_series_leaves_the_box_as_it_was(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db hiccup")
    db = FakeSupabase()
    _lead(db, "t1", "2026-11-23T08:00:00+05:30")
    monkeypatch.setattr(h, "_new_enquiries_series", boom)
    box = h._box_new_enquiries(db, "t1", h._times(NOW))
    assert box == {"value": 1, "unit": "count", "sub": "0 Hot"}


def test_series_is_reused_within_the_ttl_and_per_tenant():
    from app.services import home_today as ht

    calls = []

    def fn():
        calls.append(1)
        return [1, 2, 3, 4, 5, 6, 7]

    a = ht._with_series({}, "won series", fn, "t1", "2026-11-23")
    b = ht._with_series({}, "won series", fn, "t1", "2026-11-23")
    c = ht._with_series({}, "won series", fn, "t2", "2026-11-23")
    assert a["series"] == b["series"] == c["series"] == [1, 2, 3, 4, 5, 6, 7]
    assert len(calls) == 2  # t1 once, t2 once
    ht._with_series({}, "won series", fn, "t1", "2026-11-24")
    assert len(calls) == 3  # a new day is a new series


# ───────────────────────────────────────────── speed: the sources run side by side

SLOW_SOURCES = (
    "_orders_cards", "_box_quotes_open", "_box_new_enquiries", "_box_won_month", "_box_callbacks", "_box_ads",
    "_box_profit", "_box_expenses_today", "_feedback", "_waiting_list", "_hot", "_low_stock",
)


def _slow(fn, seconds=0.2):
    import time

    def slowed(*a, **k):
        time.sleep(seconds)
        return fn(*a, **k)
    return slowed


def test_sources_run_side_by_side_not_one_after_another(stub_sources, monkeypatch):
    """The bug: Home's Today call took about 6 s because every source waited for the one before it."""
    import time

    for name in SLOW_SOURCES:
        monkeypatch.setattr(h, name, _slow(getattr(h, name)))
    monkeypatch.setattr(h, "_count_one", _slow(h._count_one))  # the "does the client use it" checks

    start = time.perf_counter()
    out = h.compute_today(FakeDB(ALL_BOXES_DB), _ctx())
    took = time.perf_counter() - start

    # One after another this is 12 sources + 3 checks at 0.2 s each = 3 s. Side by side it is about 0.6 s.
    assert took < 1.5, f"Today took {took:.2f} s: the sources are running one after another"
    assert out["available"] == list(h.BOX_KEYS)
    assert out["waiting"]["total"] == 7 and out["low_stock"]["total"] == 2 and out["hot_bar"]["name"] == "Arun"


def test_a_source_still_sees_the_read_only_guard(stub_sources, monkeypatch):
    """Claude Access runs Today in read-only mode. The guard must reach a source wherever it runs."""
    from app.db.supabase import read_only

    seen = []

    def low_stock(db, tid):
        seen.append(read_only.get())
        return {"total": 0, "items": []}

    monkeypatch.setattr(h, "_low_stock", low_stock)
    token = read_only.set(True)
    try:
        h.compute_today(FakeDB(ALL_BOXES_DB), _ctx())
    finally:
        read_only.reset(token)
    assert seen == [True]


def test_profit_box_needs_orders_and_purchases_and_a_shop_that_has_sold(stub_sources):
    """Profit follows the same "has this shop sold anything" check as the order boxes."""
    sees_both = _ctx("staff", ["dashboard.view", "deals.view", "purchases.view"])
    assert "profit_month" in h.compute_today(FakeDB(ALL_BOXES_DB), sees_both)["available"]
    assert "profit_month" not in h.compute_today(FakeDB({**ALL_BOXES_DB, "deals": []}), sees_both)["available"]
    only_purchases = _ctx("staff", ["dashboard.view", "purchases.view"])
    assert "profit_month" not in h.compute_today(FakeDB(ALL_BOXES_DB), only_purchases)["available"]
