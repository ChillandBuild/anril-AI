"""Reports: the HTTP endpoints, who may open them, and the downloads."""
import csv
import io

import pytest
from fastapi.testclient import TestClient

from reports_seed import T1, seed, seed_money
from fake_supabase import FakeSupabase
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app

Q = "from=2026-10-10&to=2026-10-16"


def ctx(role="owner", permissions=()):
    return {"tenant_id": T1, "user_id": "u1", "role": role, "caller_id": None, "permissions": list(permissions)}


@pytest.fixture
def client(monkeypatch):
    db = seed_money(seed(FakeSupabase()))
    monkeypatch.setattr("app.routes.reports.get_supabase", lambda: db)
    monkeypatch.setattr("app.services.deals_reports.held_quantities", lambda *a, **k: {})
    monkeypatch.setattr("app.routes.reports.log_download", lambda *a, **k: None)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    holder = {"ctx": ctx()}
    app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]
    c = TestClient(app)
    c.holder = holder
    yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize("tab", ["overview", "money", "customers", "ads", "team", "items", "campaigns"])
def test_every_tab_answers_the_common_shape(client, tab):
    r = client.get(f"/api/v1/reports/{tab}?{Q}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"period", "before", "in_short"} <= set(body) and isinstance(body["in_short"], str) and body["before"] is not None


def test_compare_off_gives_no_before(client):
    assert client.get(f"/api/v1/reports/customers?{Q}&compare=off").json()["before"] is None


def test_bad_dates_and_compare_are_plain_400s(client):
    for query in ("from=bad&to=2026-10-16", "from=2026-10-16&to=2026-10-10", f"{Q}&compare=sideways"):
        r = client.get(f"/api/v1/reports/customers?{query}")
        assert r.status_code == 400 and r.json()["detail"]


def test_no_days_means_last_30(client):
    assert client.get("/api/v1/reports/customers").status_code == 200


def test_without_analytics_view_every_report_is_403(client):
    client.holder["ctx"] = ctx("staff", [])
    for path in ("overview", "money", "ads.csv", "people?metric=hot"):
        assert client.get(f"/api/v1/reports/{path}&{Q}" if "?" in path else f"/api/v1/reports/{path}?{Q}").status_code == 403


def test_analytics_only_person_gets_no_rupees(client):
    client.holder["ctx"] = ctx("staff", ["analytics.view"])
    money = client.get(f"/api/v1/reports/money?{Q}").json()
    assert money["money_hidden"] is True and money["period"] == {}
    ads = client.get(f"/api/v1/reports/ads?{Q}").json()
    assert ads["money_hidden"] is True and "spend_paise" not in ads["rows"][0] and ads["rows"][0]["chats"] >= 0
    assert "₹" not in client.get(f"/api/v1/reports/overview?{Q}").text


def test_orders_viewer_sees_sales_not_profit(client):
    client.holder["ctx"] = ctx("staff", ["analytics.view", "deals.view"])
    body = client.get(f"/api/v1/reports/money?{Q}").json()
    assert body["profit_hidden"] is True and body["period"]["sales_paise"] == 150_000 and "profit_paise" not in body["period"]


def test_people_endpoint(client):
    body = client.get(f"/api/v1/reports/people?metric=hot&{Q}").json()
    assert body["count"] == 2 and {p["name"] for p in body["people"]} == {"Asha", "Chitra"} and body["capped"] is False
    assert client.get(f"/api/v1/reports/people?metric=nope&{Q}").status_code == 400
    assert client.get(f"/api/v1/reports/people?metric=ad_chats&id=camp-m&{Q}").json()["people"][0]["name"] == "Asha"
    assert client.get(f"/api/v1/reports/people?{Q}").status_code == 422  # metric is required


def test_people_needs_leads_view_and_a_caller_sees_only_their_own(client, monkeypatch):
    client.holder["ctx"] = ctx("staff", ["analytics.view"])  # names and phones need "See leads"
    assert client.get(f"/api/v1/reports/people?metric=hot&{Q}").status_code == 403
    client.holder["ctx"] = {**ctx("caller", ["analytics.view", "leads.view"]), "caller_id": None}
    body = client.get(f"/api/v1/reports/people?metric=hot&{Q}").json()
    assert body["people"] == []  # a telecaller with no caller id is given nobody


def test_csv_downloads(client):
    r = client.get(f"/api/v1/reports/ads.csv?{Q}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="report-ads.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "In short" and ["Rows"] in rows
    for tab in ("overview", "customers", "team", "items", "campaigns"):
        assert client.get(f"/api/v1/reports/{tab}.csv?{Q}").status_code == 200
    assert client.get(f"/api/v1/reports/money.csv?{Q}").status_code == 404  # Money has the accountant file instead


def test_csv_needs_the_download_permission(client):
    client.holder["ctx"] = ctx("staff", ["analytics.view"])
    r = client.get(f"/api/v1/reports/customers.csv?{Q}")
    assert r.status_code == 403 and "download" in r.json()["detail"].lower()
    client.holder["ctx"] = ctx("staff", ["analytics.view", "leads.download"])
    assert client.get(f"/api/v1/reports/customers.csv?{Q}").status_code == 200


def test_csv_for_a_person_without_money_has_no_rupee_columns(client):
    client.holder["ctx"] = ctx("staff", ["analytics.view", "leads.download"])
    text = client.get(f"/api/v1/reports/ads.csv?{Q}").text
    assert "rupees" not in text


def test_accountant_file_needs_purchases_view_and_deals_view(client, monkeypatch):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Summary"
    buf = io.BytesIO()
    wb.save(buf)
    monkeypatch.setattr("app.services.expenses.month_excel", lambda *a: (buf.getvalue(), "x.xlsx"))
    r = client.get("/api/v1/reports/money/accountant.xlsx?month=2026-10")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    assert 'filename="anril-2026-10-for-accountant.xlsx"' in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"
    assert client.get("/api/v1/reports/money/accountant.xlsx?month=October").status_code == 400
    client.holder["ctx"] = ctx("staff", ["analytics.view", "deals.view"])
    assert client.get("/api/v1/reports/money/accountant.xlsx?month=2026-10").status_code == 403
    client.holder["ctx"] = ctx("staff", ["purchases.view"])  # sales rupees need deals.view too
    assert client.get("/api/v1/reports/money/accountant.xlsx?month=2026-10").status_code == 403
    client.holder["ctx"] = ctx("staff", ["purchases.view", "deals.view"])
    assert client.get("/api/v1/reports/money/accountant.xlsx?month=2026-10").status_code == 200
