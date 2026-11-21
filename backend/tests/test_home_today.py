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
    assert set(body) == {"available", "defaults", "boxes", "hot_bar", "waiting", "low_stock"}


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
    # 10 real keys is the most a person can pick today, so 13 can only mean repeats or unknowns: still 422.
    assert client.put("/api/v1/home/layout", json={"boxes": [f"k{i}" for i in range(13)], "lists": {}}).status_code == 422


def test_put_saves_and_returns_the_get_shape(client, monkeypatch):
    db = FakeDB()
    _use_db(monkeypatch, db)
    res = client.put("/api/v1/home/layout", json={"boxes": ["to_collect", "money_in_today"], "lists": {"waiting": False}})
    assert res.status_code == 200
    assert res.json() == {"boxes": ["to_collect", "money_in_today"],
                          "lists": {"waiting": False, "low_stock": True}, "is_custom": True}
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
