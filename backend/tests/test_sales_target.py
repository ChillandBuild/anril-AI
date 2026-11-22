"""My business > Target & profit: suggested maths, owner-only save + validation, this month's
target (override), cost coverage, and the Home "Target this month" box for each kind of person."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import home_today, sales_target as st
from app.services.orders import IST
from fake_supabase import FakeSupabase

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=IST)
T1, T2 = "t1", "t2"


def ist(y, m, d, h=12):
    return datetime(y, m, d, h, 0, tzinfo=IST).isoformat()


def rupees(r):
    return r * 100


def _ctx(role="owner", permissions=(), tenant=T1):
    return {"tenant_id": tenant, "user_id": "u1", "role": role, "caller_id": None, "permissions": list(permissions)}


def _pay(db, tenant, amount_rupees, when):
    db.add("deal_payments", tenant_id=tenant, amount_paise=rupees(amount_rupees), paid_at=when)


def _set_target(db, tenant=T1, **value):
    db.add("app_settings", tenant_id=tenant, key="sales_target", value=json.dumps(value))


@pytest.fixture
def db():
    return FakeSupabase()


@pytest.fixture
def three_months(db):
    _pay(db, T1, 180_000, ist(2026, 8, 10))
    _pay(db, T1, 180_000, ist(2026, 9, 10))
    _pay(db, T1, 180_000, ist(2026, 10, 10))
    return db


# ───────────────────────────────────────────────────────────── suggestion

def test_suggested_is_average_plus_ten_percent_rounded_up_to_a_thousand():
    # 1,80,000 average x 1.1 = 1,98,000, already a whole thousand
    assert st.suggest_paise([rupees(180_000)] * 3) == rupees(198_000)
    # 1,75,000 x 1.1 = 1,92,500 -> up to 1,93,000
    assert st.suggest_paise([rupees(175_000)] * 3) == rupees(193_000)
    # 1,86,364 average x 1.1 = 2,05,000.4 -> rounds UP to 2,06,000
    assert st.suggest_paise([rupees(186_364)] * 3) == rupees(206_000)
    # exact multiple stays put: 100,000 x 1.1 = 110,000
    assert st.suggest_paise([rupees(100_000)]) == rupees(110_000)


def test_suggested_uses_only_months_that_had_money_in():
    assert st.suggest_paise([0, rupees(100_000), rupees(100_000)]) == rupees(110_000)
    assert st.suggest_paise([0, 0, rupees(50_000)]) == rupees(55_000)


def test_suggested_is_none_with_no_money_in():
    assert st.suggest_paise([0, 0, 0]) is None
    assert st.suggest_paise([]) is None


def test_suggested_never_rounds_down_to_zero():
    assert st.suggest_paise([1]) == rupees(1000)


def test_last_full_months_skip_this_month_and_cross_the_year():
    got = [st.month_key(s) for s in st.last_full_months(datetime(2026, 1, 15, tzinfo=IST))]
    assert got == ["2025-10", "2025-11", "2025-12"]


def test_indian_rupees_grouping():
    assert st.indian_rupees(rupees(200_000)) == "₹2,00,000"
    assert st.indian_rupees(rupees(186_000)) == "₹1,86,000"
    assert st.indian_rupees(rupees(999)) == "₹999"
    assert st.indian_rupees(rupees(12_34_56_789)) == "₹12,34,56,789"
    assert st.indian_rupees(150) == "₹1.50"


# ───────────────────────────────────────────────────────────── overview

def test_overview_suggestion_last3_and_this_month(three_months):
    _pay(three_months, T1, 93_000, ist(2026, 11, 5))
    _set_target(three_months, monthly_paise=rupees(100_000), months={}, show_team=False)
    out = st.overview(three_months, T1, NOW)
    assert out["suggested_paise"] == rupees(198_000)
    assert [m["month"] for m in out["last3"]] == ["2026-08", "2026-09", "2026-10"]
    assert all(m["money_in_paise"] == rupees(180_000) for m in out["last3"])
    assert out["this_month"] == {"month": "2026-11", "target_paise": rupees(100_000),
                                 "money_in_paise": rupees(93_000), "pct": 93}


def test_money_in_nets_refunds_but_not_failed_ones(db):
    _pay(db, T1, 10_000, ist(2026, 11, 3))
    db.add("deal_refunds", tenant_id=T1, amount_paise=rupees(1_000), created_at=ist(2026, 11, 4), status="done")
    db.add("deal_refunds", tenant_id=T1, amount_paise=rupees(5_000), created_at=ist(2026, 11, 4), status="failed")
    assert st.money_in_by_month(db, T1, datetime(2026, 11, 1, tzinfo=IST)) == {"2026-11": rupees(9_000)}


def test_payment_just_after_midnight_ist_counts_to_the_new_month(db):
    # 00:10 IST on 1 Nov is still 31 Oct in UTC
    db.add("deal_payments", tenant_id=T1, amount_paise=100, paid_at="2026-10-31T18:40:00+00:00")
    assert st.money_in_by_month(db, T1, datetime(2026, 10, 1, tzinfo=IST)) == {"2026-11": 100}


def test_month_override_beats_the_every_month_target(db):
    _set_target(db, monthly_paise=rupees(100_000), months={"2026-11": rupees(250_000)}, show_team=False)
    assert st.overview(db, T1, NOW)["this_month"]["target_paise"] == rupees(250_000)
    assert st.target_for_month({"monthly_paise": 5, "months": {"2026-12": 9}}, "2026-11") == 5
    assert st.target_for_month({"monthly_paise": None, "months": {}}, "2026-11") is None


def test_no_target_means_pct_none(db):
    out = st.overview(db, T1, NOW)
    assert out["this_month"]["target_paise"] is None and out["this_month"]["pct"] is None
    assert out["suggested_paise"] is None and out["monthly_paise"] is None and out["show_team"] is False


def test_cost_coverage_counts_items_with_a_cost(db):
    db.add("catalog_items", tenant_id=T1, name="A", cost_price_paise=500)
    db.add("catalog_items", tenant_id=T1, name="B", cost_price_paise=None)
    db.add("catalog_items", tenant_id=T1, name="C", cost_price_paise=0)
    db.add("catalog_items", tenant_id=T2, name="other shop", cost_price_paise=9)
    assert st.cost_coverage(db, T1) == {"with_cost": 2, "total": 3}


def test_cost_coverage_none_when_catalogue_cannot_be_read():
    class Broken:
        def table(self, name):
            raise RuntimeError("relation does not exist")
    assert st.cost_coverage(Broken(), T1) is None


def test_missing_settings_row_or_garbage_reads_as_no_target(db):
    assert st.read_target(db, T1) == {"monthly_paise": None, "months": {}, "show_team": False}
    db.add("app_settings", tenant_id=T1, key="sales_target", value="{not json")
    assert st.read_target(db, T1)["monthly_paise"] is None


def test_overview_survives_money_tables_failing(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no table")
    monkeypatch.setattr(st, "money_in_by_month", boom)
    _set_target(db, monthly_paise=rupees(1000), months={}, show_team=False)
    out = st.overview(db, T1, NOW)
    assert out["suggested_paise"] is None and out["this_month"]["money_in_paise"] is None
    assert out["this_month"]["target_paise"] == rupees(1000)


def test_tenant_isolation_for_money_and_target(db):
    _pay(db, T2, 99_999, ist(2026, 11, 2))
    _set_target(db, tenant=T2, monthly_paise=rupees(5), months={}, show_team=True)
    out = st.overview(db, T1, NOW)
    assert out["monthly_paise"] is None and out["show_team"] is False
    assert out["this_month"]["money_in_paise"] == 0


# ───────────────────────────────────────────────────────────── validation + save

@pytest.mark.parametrize("bad", [
    {"monthly_paise": -1},
    {"monthly_paise": 10**12 + 1},
    {"monthly_paise": 5, "months": {"2026-13": 5}},
    {"monthly_paise": 5, "months": {"26-11": 5}},
    {"monthly_paise": 5, "months": {"2026-11": -5}},
    {"monthly_paise": 5, "months": {"2026-11": 10**12 + 1}},
    {"monthly_paise": 5, "months": {f"{2000 + i // 12}-{i % 12 + 1:02d}": 1 for i in range(25)}},
])
def test_validate_rejects(bad):
    with pytest.raises(st.TargetError):
        st.validate(bad)


def test_validate_accepts_limits_and_blank():
    assert st.validate({"monthly_paise": None})["monthly_paise"] is None
    assert st.validate({"monthly_paise": 10**12, "months": {"2026-01": 0}, "show_team": 1}) == {
        "monthly_paise": 10**12, "months": {"2026-01": 0}, "show_team": True}
    months = {f"{2000 + i // 12}-{i % 12 + 1:02d}": 1 for i in range(24)}
    assert len(st.validate({"months": months})["months"]) == 24


def test_save_writes_only_this_tenants_row(db):
    st.save_target(db, T1, {"monthly_paise": rupees(2000), "months": {"2026-12": rupees(3000)}, "show_team": True}, NOW)
    rows = db.rows("app_settings")
    assert len(rows) == 1 and rows[0]["tenant_id"] == T1 and rows[0]["key"] == "sales_target"
    assert json.loads(rows[0]["value"]) == {"monthly_paise": rupees(2000), "months": {"2026-12": rupees(3000)}, "show_team": True}
    assert st.read_target(db, T2)["monthly_paise"] is None


# ───────────────────────────────────────────────────────────── routes

@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr("app.routes.my_business.get_supabase", lambda: db)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    holder = {"ctx": _ctx()}
    app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]
    c = TestClient(app)
    c.holder = holder
    yield c
    app.dependency_overrides.clear()


def test_put_target_owner_saves_and_returns_overview(client, db):
    r = client.put("/api/v1/my-business/target", json={"monthly_paise": rupees(200_000), "months": {}, "show_team": True})
    assert r.status_code == 200
    assert r.json()["monthly_paise"] == rupees(200_000) and r.json()["show_team"] is True
    assert client.get("/api/v1/my-business/target").json()["monthly_paise"] == rupees(200_000)


def test_put_target_is_owner_only_even_with_settings_manage(client, db):
    client.holder["ctx"] = _ctx("staff", ["settings.manage"])
    r = client.put("/api/v1/my-business/target", json={"monthly_paise": 5})
    assert r.status_code == 403 and r.json()["detail"] == "Only the owner can set the target."
    assert db.rows("app_settings") == []


def test_put_target_validation_is_a_plain_400(client):
    r = client.put("/api/v1/my-business/target", json={"monthly_paise": -5})
    assert r.status_code == 400 and "below zero" in r.json()["detail"]
    r = client.put("/api/v1/my-business/target", json={"months": {"nope": 5}})
    assert r.status_code == 400


def test_get_target_needs_settings_view_or_manage(client):
    client.holder["ctx"] = _ctx("staff", ["deals.view"])
    assert client.get("/api/v1/my-business/target").status_code == 403
    client.holder["ctx"] = _ctx("staff", ["settings.view"])
    assert client.get("/api/v1/my-business/target").status_code == 200
    client.holder["ctx"] = _ctx("staff", ["settings.manage"])
    assert client.get("/api/v1/my-business/target").status_code == 200


def test_get_target_other_tenant_sees_nothing(client, db):
    _set_target(db, tenant=T2, monthly_paise=rupees(77), months={}, show_team=True)
    assert client.get("/api/v1/my-business/target").json()["monthly_paise"] is None


# ───────────────────────────────────────────────────────────── Home box

def test_home_box_owner_sees_money_and_percent(db):
    _pay(db, T1, 186_000, ist(2026, 11, 3))
    _set_target(db, monthly_paise=rupees(200_000), months={}, show_team=False)
    box = st.home_box(db, _ctx(), NOW)
    assert box == {"value": rupees(186_000), "unit": "paise", "sub": "of ₹2,00,000 · 93%",
                   "href": "/dashboard/settings/target"}


def test_home_box_deals_view_sees_money_without_a_settings_link(db):
    _pay(db, T1, 186_000, ist(2026, 11, 3))
    _set_target(db, monthly_paise=rupees(200_000), months={}, show_team=False)
    box = st.home_box(db, _ctx("staff", ["dashboard.view", "deals.view"]), NOW)
    assert box["unit"] == "paise" and box["value"] == rupees(186_000) and box["href"] == "/dashboard"


def test_home_box_team_sees_only_a_percent_and_only_when_shown(db):
    _pay(db, T1, 186_000, ist(2026, 11, 3))
    staff = _ctx("staff", ["dashboard.view"])
    _set_target(db, monthly_paise=rupees(200_000), months={}, show_team=True)
    box = st.home_box(db, staff, NOW)
    assert box["unit"] == "percent" and box["value"] == 93 and box["sub"] == "of target"
    assert "186" not in json.dumps(box) and "200" not in json.dumps(box)

    db.tables["app_settings"].clear()
    _set_target(db, monthly_paise=rupees(200_000), months={}, show_team=False)
    assert st.home_box(db, staff, NOW) is None


def test_home_box_no_target_owner_gets_set_a_target_others_nothing(db):
    owner = st.home_box(db, _ctx(), NOW)
    assert owner["unit"] == "set_target" and owner["href"] == "/dashboard/settings/target"
    assert st.home_box(db, _ctx("staff", ["dashboard.view", "deals.view"]), NOW) is None
    _set_target(db, tenant=T2, monthly_paise=rupees(1), months={}, show_team=True)
    assert st.home_box(db, _ctx("staff", ["dashboard.view"]), NOW) is None


def test_home_box_uses_this_months_override(db):
    _pay(db, T1, 50_000, ist(2026, 11, 3))
    _set_target(db, monthly_paise=rupees(100_000), months={"2026-11": rupees(200_000)}, show_team=False)
    assert st.home_box(db, _ctx(), NOW)["sub"] == "of ₹2,00,000 · 25%"


def test_home_box_ignores_other_months_and_other_tenants_money(db):
    _pay(db, T1, 99_000, ist(2026, 10, 30))
    _pay(db, T2, 99_000, ist(2026, 11, 3))
    _set_target(db, monthly_paise=rupees(100_000), months={}, show_team=False)
    assert st.home_box(db, _ctx(), NOW)["value"] == 0


def test_compute_today_puts_target_box_in_available_for_owner_and_hides_for_team(db, monkeypatch):
    for name in ("_orders_cards", "_waiting_list", "_hot", "_low_stock"):
        monkeypatch.setattr(home_today, name, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")))
    _pay(db, T1, 186_000, ist(2026, 11, 3))
    _set_target(db, monthly_paise=rupees(200_000), months={}, show_team=False)
    owner = home_today.compute_today(db, _ctx(), NOW.astimezone(timezone.utc))
    assert "target_month" in owner["available"]
    assert owner["boxes"]["target_month"]["sub"] == "of ₹2,00,000 · 93%"
    team = home_today.compute_today(db, _ctx("staff", ["dashboard.view"]), NOW.astimezone(timezone.utc))
    assert "target_month" not in team["available"] and "target_month" not in team["boxes"]


def test_a_failing_target_source_does_not_break_home(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(st, "home_box", boom)
    for name in ("_orders_cards", "_waiting_list", "_hot", "_low_stock"):
        monkeypatch.setattr(home_today, name, boom)
    out = home_today.compute_today(db, _ctx(), NOW.astimezone(timezone.utc))
    assert "target_month" not in out["available"]


# ───────────────────────────────────────────────────────────── review fixes

def _old_months(n):
    return {f"{2000 + i // 12}-{i % 12 + 1:02d}": 1 for i in range(n)}


def test_save_drops_months_before_this_month_so_the_cap_never_locks_the_owner_out(db):
    months = {**_old_months(30), "2026-10": 5, "2026-11": 7, "2026-12": 9}
    st.save_target(db, T1, {"monthly_paise": 1, "months": months, "show_team": False}, NOW)
    assert json.loads(db.rows("app_settings")[0]["value"])["months"] == {"2026-11": 7, "2026-12": 9}


def test_still_more_than_24_current_or_future_months_is_refused(db):
    months = {f"{2027 + i // 12}-{i % 12 + 1:02d}": 1 for i in range(25)}
    with pytest.raises(st.TargetError):
        st.save_target(db, T1, {"months": months}, NOW)


def test_reading_old_data_self_heals_even_past_24_old_months(db):
    _set_target(db, monthly_paise=5, months={**_old_months(30), "2026-12": 9}, show_team=False)
    got = st.read_target(db, T1, NOW)
    assert got["monthly_paise"] == 5 and got["months"] == {"2026-12": 9}


def test_overview_without_orders_view_has_no_rupees_but_keeps_target_and_pct(db):
    _pay(db, T1, 93_000, ist(2026, 11, 5))
    _pay(db, T1, 100_000, ist(2026, 10, 5))
    _set_target(db, monthly_paise=rupees(100_000), months={}, show_team=True)
    out = st.overview(db, T1, NOW, sees_money=False)
    assert out["suggested_paise"] is None
    assert all(m["money_in_paise"] is None for m in out["last3"])
    assert out["this_month"]["money_in_paise"] is None
    assert out["this_month"]["target_paise"] == rupees(100_000) and out["this_month"]["pct"] == 93
    assert "93000" not in json.dumps(out) and str(rupees(93_000)) not in json.dumps(out)


def test_route_hides_money_unless_owner_or_deals_view(client, db):
    _pay(db, T1, 50_000, ist(2026, 11, 5))
    _set_target(db, monthly_paise=rupees(100_000), months={}, show_team=False)
    client.holder["ctx"] = _ctx("staff", ["settings.view"])
    out = client.get("/api/v1/my-business/target").json()
    assert out["suggested_paise"] is None and out["this_month"]["money_in_paise"] is None
    assert all(m["money_in_paise"] is None for m in out["last3"])
    client.holder["ctx"] = _ctx("staff", ["settings.view", "deals.view"])
    assert client.get("/api/v1/my-business/target").json()["this_month"]["money_in_paise"] is not None
    client.holder["ctx"] = _ctx()
    assert client.get("/api/v1/my-business/target").json()["this_month"]["money_in_paise"] is not None


def test_home_box_href_only_sends_money_viewers_to_the_target_page(db):
    _set_target(db, monthly_paise=rupees(100_000), months={}, show_team=True)
    assert st.home_box(db, _ctx("staff", ["dashboard.view", "settings.view"]), NOW)["href"] == "/dashboard"
    assert st.home_box(db, _ctx("staff", ["dashboard.view", "deals.view", "settings.view"]), NOW)["href"] == "/dashboard/settings/target"
    assert st.home_box(db, _ctx(), NOW)["href"] == "/dashboard/settings/target"


def test_paged_orders_by_column_then_id_and_warns_at_the_cap(db, caplog):
    class Spy:
        def __init__(self):
            self.orders, self.pages = [], 0
        def order(self, col, **k):
            self.orders.append(col)
            return self
        def range(self, a, b):
            return self
        def execute(self):
            self.pages += 1
            from types import SimpleNamespace
            return SimpleNamespace(data=[{"id": i} for i in range(st.PAGE)])
    spy = Spy()
    with caplog.at_level("WARNING"):
        rows = st._paged(lambda: spy, "paid_at")
    assert spy.orders[:2] == ["paid_at", "id"]
    assert spy.pages == st.MAX_PAGES and len(rows) == st.MAX_PAGES * st.PAGE
    assert "stopped at" in caplog.text
