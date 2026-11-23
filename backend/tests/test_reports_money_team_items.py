"""Reports: Money (and the accountant file), Service & team, Items & orders."""
import io
from datetime import date

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

from reports_seed import PERIOD, T1, T2, MissingTables, at, seed, seed_money
from fake_supabase import FakeSupabase
from app.services import reports_items, reports_money, reports_team
from app.services.reports_common import Flags, Period

ALL, ORDERS_ONLY, NONE = Flags(True, True), Flags(True, False), Flags(False, False)


@pytest.fixture
def db():
    return seed_money(seed(FakeSupabase()))


# ── Money ───────────────────────────────────────────────────────────────────

def test_money_for_picked_days_works_out_profit_for_exactly_those_days(db):
    numbers, extras = reports_money.compute(db, T1, PERIOD, ALL)
    assert numbers["sales_paise"] == 150_000 and numbers["orders"] == 2 and numbers["refunds_paise"] == 5_000
    assert numbers["gst_collected_paise"] == 18_000
    assert numbers["cost_paise"] == 40_000  # 2 sold x 200 rupees
    assert numbers["expenses_paise"] == 7_000 + 50_000  # typed expense + Meta ads
    assert numbers["profit_paise"] == 150_000 - 5_000 - 40_000 - 57_000
    assert numbers["gst_paid_paise"] == 9_000 and numbers["gst_to_pay_paise"] == 9_000
    assert numbers["cash_short_paise"] == 2_500
    assert extras["scope"] == "range" and "plan fee" in extras["scope_note"]


def test_money_for_whole_months_uses_the_expenses_pages_own_numbers(db, monkeypatch):
    seen = []

    def fake_view(_db, tenant, month):
        seen.append(month)
        return {"profit": {"cogs_paise": 11_000, "expenses_paise": 22_000}}
    monkeypatch.setattr("app.services.expenses.month_view", fake_view)
    numbers, extras = reports_money.compute(db, T1, Period(date(2026, 10, 1), date(2026, 10, 31)), ALL)
    assert seen == ["2026-10"] and extras["scope"] == "month" and extras["scope_label"] == "October 2026"
    assert (numbers["cost_paise"], numbers["expenses_paise"]) == (11_000, 22_000)


def test_money_without_profit_permission_computes_no_profit(db):
    numbers, extras = reports_money.compute(db, T1, PERIOD, ORDERS_ONLY)
    assert "profit_paise" not in numbers and "scope" not in extras and numbers["sales_paise"] == 150_000


def test_as_of_today_still_to_collect_and_supplier_dues(db):
    assert reports_money.as_of_today(db, T1, ALL) == {"still_to_collect_paise": 20_000, "owed_to_suppliers_paise": 40_000}
    assert reports_money.as_of_today(db, T1, ORDERS_ONLY) == {"still_to_collect_paise": 20_000}


def test_money_report_hides_everything_without_the_order_permission(db):
    out = reports_money.report(db, T1, PERIOD, True, NONE)
    assert out["money_hidden"] is True and out["period"] == {} and out["before"] is None


def test_money_report_for_owner_has_before_and_plain_sentence(db):
    out = reports_money.report(db, T1, PERIOD, True, ALL)
    assert out["period"]["profit_paise"] == 48_000 and out["period"]["still_to_collect_paise"] == 20_000
    assert out["before"]["sales_paise"] == 20_000 and out["before"]["still_to_collect_paise"] is None
    assert out["in_short"] == "₹1,500 sales, up ₹1,300 from before; ₹480 profit; ₹200 still to collect."
    assert out["has_cost_prices"] is True and out["cost_coverage"] == {"with_cost": 1, "total": 3}


def test_money_report_orders_only_leaves_profit_keys_out(db):
    out = reports_money.report(db, T1, PERIOD, False, ORDERS_ONLY)
    assert out["profit_hidden"] is True
    for key in ("profit_paise", "cost_paise", "expenses_paise", "gst_paid_paise", "owed_to_suppliers_paise"):
        assert key not in out["period"]
    assert out["period"]["sales_paise"] == 150_000 and "profit" not in out["in_short"]


def test_money_in_short_reports_a_loss():
    assert reports_money.in_short({"sales_paise": 100_000, "profit_paise": -25_000}, None) == "₹1,000 sales; ₹250 loss."
    assert reports_money.in_short({}, None) == "No money figures to show for these days."


def test_month_period_and_bad_months():
    key, p = reports_money.month_period("2026-02")
    assert key == "2026-02" and (p.start, p.end) == (date(2026, 2, 1), date(2026, 2, 28))
    assert reports_money.month_period(None)[0] <= date.today().strftime("%Y-%m")
    for bad in ("2026-13", "26-10", "october"):
        with pytest.raises(HTTPException) as e:
            reports_money.month_period(bad)
        assert e.value.status_code == 400


def test_period_text():
    assert reports_money._period_text(PERIOD) == "10 Oct 2026 to 16 Oct 2026"


def test_accountant_file_sheets_and_rows(db, monkeypatch):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Summary"
    for name in ("Sales", "Purchases", "Expenses"):
        wb.create_sheet(name)
    buf = io.BytesIO()
    wb.save(buf)
    monkeypatch.setattr("app.services.expenses.month_excel", lambda _d, _t, _m: (buf.getvalue(), "x.xlsx"))
    content, name = reports_money.accountant_excel(db, T1, "2026-10")
    assert name == "anril-2026-10-for-accountant.xlsx"
    book = load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["Summary", "Sales B2B", "Sales B2C", "Credit notes", "Purchases", "Expenses", "Payment split"]
    b2b = list(book["Sales B2B"].values)
    assert b2b[0][0] == "Date" and len(b2b) == 2 and b2b[1][1] == "INV-1" and b2b[1][4] == "33AAAAA0000A1Z5"
    assert b2b[1][5:8] == (1180.0, 180.0, 1000.0)
    b2c = list(book["Sales B2C"].values)
    assert len(b2c) == 3 and b2c[2][1] == "INV-2" and b2c[2][8] == "Cash"  # D0 (4 Oct) is in the month too
    credit = list(book["Credit notes"].values)
    assert credit[1][1] == "CN-1" and credit[1][2] == "INV-1" and credit[1][4] == 50.0
    split = {r[0]: r[1:] for r in book["Payment split"].values}
    assert split["UPI"] == (1180.0, 50.0, 1130.0) and split["Cash"] == (500.0, 0.0, 500.0)
    assert split["Total"] == (1680.0, 50.0, 1630.0)


def test_accountant_file_defuses_formula_names(db, monkeypatch):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Summary"
    buf = io.BytesIO()
    wb.save(buf)
    monkeypatch.setattr("app.services.expenses.month_excel", lambda _d, _t, _m: (buf.getvalue(), "x.xlsx"))
    db.rows("deals")[2].update(customer_name='=HYPERLINK("http://evil")')  # D2, a B2C sale
    book = load_workbook(io.BytesIO(reports_money.accountant_excel(db, T1, "2026-10")[0]))
    assert list(book["Sales B2C"].values)[2][2].startswith("'=")


def test_fill_writes_header_and_rows():
    from openpyxl import Workbook
    ws = Workbook().active
    reports_money._fill(ws, ["A", "B"], [[1, 2]])
    assert [list(r) for r in ws.values] == [["A", "B"], [1, 2]] and ws["A1"].font.bold
    assert reports_money._rupees(12345) == 123.45 and reports_money._rupees(None) == 0


# ── Service & team ──────────────────────────────────────────────────────────

def seed_team(db):
    db.rpc_handlers["analytics_response_times_split"] = lambda p: [
        {"who": "ai", "answered": 30, "p50_seconds": 12, "p90_seconds": 40},
        {"who": "staff", "answered": 8, "p50_seconds": 300, "p90_seconds": 900}]
    db.add("chat_handovers", tenant_id=T1, lead_id="L2", opened_at=at(12))
    db.add("chat_handovers", tenant_id=T1, lead_id="L2", opened_at=at(13))  # same person twice counts once
    db.add("chat_handovers", tenant_id=T2, lead_id="X1", opened_at=at(12))
    for stars, staff in ((5, "Ravi"), (2, "Ravi"), (4, "Meena")):
        db.add("customer_feedback", tenant_id=T1, stars=stars, staff_name=staff, answered_at=at(13), status="answered")
    db.add("callers", id="c1", tenant_id=T1, name="Meena")
    db.add("call_logs", tenant_id=T1, caller_id="c1", manual_status="connected", outcome="converted", duration_seconds=120, created_at=at(12))
    return db


def test_reply_times_split_and_missing_function():
    db = seed_team(FakeSupabase())
    out = reports_team.reply_times(db, T1, PERIOD)
    assert out["ai"]["p50_seconds"] == 12 and out["staff"]["p90_seconds"] == 900
    assert reports_team.reply_times(FakeSupabase(), T1, PERIOD) is None  # database function not there yet


def test_sales_by_person_names_the_ai_agent_and_callers():
    db = seed_team(seed(FakeSupabase()))
    from app.services.reports_data import won_deals
    rows = reports_team.sales_by_person(db, T1, won_deals(db, T1, PERIOD))
    assert {r["name"]: (r["count"], r["sales_paise"]) for r in rows} == {"AI agent": (1, 100_000), "Meena": (1, 50_000)}


def test_sales_by_person_falls_back_to_user_then_not_recorded():
    db = FakeSupabase()
    db.add("tenant_users", tenant_id=T1, user_id="u9", full_name="Kavi")
    rows = reports_team.sales_by_person(db, T1, [
        {"created_by": "u9", "total_paise": 100, "gst_paise": 0}, {"total_paise": 50, "gst_paise": 0}])
    assert {r["name"] for r in rows} == {"Kavi", "Not recorded"}


def test_stars_by_person_average_and_count():
    db = seed_team(FakeSupabase())
    rows = reports_team.stars_by_person(db, T1, PERIOD)
    assert rows == [{"name": "Meena", "avg": 4.0, "count": 1}, {"name": "Ravi", "avg": 3.5, "count": 2}]
    assert reports_team.stars_by_person(MissingTables("customer_feedback"), T1, PERIOD) == []


def test_passed_on_counts_people_once_and_only_this_shop():
    assert reports_team.passed_on_lead_ids(seed_team(FakeSupabase()), T1, PERIOD) == ["L2"]


def test_team_report_numbers():
    db = seed_team(seed(FakeSupabase()))
    numbers, extras = reports_team.compute(db, T1, PERIOD, ALL)
    assert numbers["chats"] == 4 and numbers["passed_to_person"] == 1 and numbers["handled_by_ai_alone"] == 3
    assert numbers["ai_reply_p50_seconds"] == 12 and numbers["staff_reply_p50_seconds"] == 300
    assert numbers["average_stars"] == 3.7 and numbers["stars_given"] == 3
    assert numbers["calls"] == 1 and numbers["connected_calls"] == 1 and extras["handled"] == {"by_ai_alone": 3, "passed_to_person": 1}


def test_team_report_survives_missing_migration_320():
    db = seed(MissingTables("customer_feedback", "chat_handovers", "analytics_response_times_split"))
    numbers, extras = reports_team.compute(db, T1, PERIOD, ALL)
    assert numbers["ai_reply_p50_seconds"] is None and numbers["average_stars"] is None
    assert numbers["passed_to_person"] == 0 and extras["reply_times"] is None and extras["stars_by_person"] == []


def test_team_in_short():
    text = reports_team.in_short({"chats": 4, "handled_by_ai_alone": 3, "ai_reply_p50_seconds": 12,
                                  "staff_reply_p50_seconds": 300, "calls": 5}, None)
    assert text == "The AI agent handled 3 of 4 new chats alone; it usually answers in 12s; your team in 5m 0s; 5 calls made."
    assert reports_team._secs(59) == "59s" and reports_team._secs(125) == "2m 5s"
    assert reports_team.in_short({}, None) == "No chats or calls in these days."


# ── Items & orders ──────────────────────────────────────────────────────────

@pytest.fixture
def held_none(monkeypatch):
    monkeypatch.setattr("app.services.deals_reports.held_quantities", lambda *a, **k: {})


def test_top_items_by_rupees(db):
    top, qty = reports_items.top_items(db, T1, ["D1", "D2"])
    assert [(i["name"], i["qty"], i["sales_paise"]) for i in top] == [("Rice 5kg", 2, 118_000), ("Oil", 1, 50_000)] and qty == 3
    assert reports_items.top_items(db, T1, []) == ([], 0)


def test_low_stock_counts_what_is_really_left(db, held_none):
    assert reports_items.low_stock(db, T1) == [{"name": "Salt", "left": 1}, {"name": "Rice 5kg", "left": 2}]


def test_low_stock_missing_table_is_empty():
    assert reports_items.low_stock(MissingTables("catalog_items"), T1) == []


def test_orders_by_stage(db):
    from app.services.reports_data import won_deals
    stages = {s["stage"]: s for s in reports_items.orders_by_stage(db, T1, PERIOD, won_deals(db, T1, PERIOD))}
    assert stages["quoted"]["count"] == 1 and stages["awaiting_payment"]["total_paise"] == 30_000
    assert stages["won"]["count"] == 2 and stages["lost"]["count"] == 1 and stages["won"]["label"] == "Paid"


def test_items_report_and_sentence(db, held_none):
    numbers, extras = reports_items.compute(db, T1, PERIOD, ALL)
    assert numbers == {"orders": 2, "items_sold": 3, "sales_paise": 150_000, "orders_lost": 1}
    assert len(extras["top_items"]) == 2 and len(extras["low_stock"]) == 2
    assert reports_items.in_short(numbers, None) == "2 orders paid, ₹1,500; 3 items sold."
    assert reports_items.in_short({}, None) == "No paid orders in these days."


def test_ai_alone_ignores_handovers_of_older_customers():
    db = seed_team(seed(FakeSupabase()))
    for n in range(5):  # handovers in the period for people who did not start chatting in it
        db.add("chat_handovers", tenant_id=T1, lead_id=f"OLD{n}", opened_at=at(12))
    numbers, _ = reports_team.compute(db, T1, PERIOD, ALL)
    assert numbers["chats"] == 4 and numbers["handled_by_ai_alone"] == 3
    assert numbers["passed_to_person"] == 6
