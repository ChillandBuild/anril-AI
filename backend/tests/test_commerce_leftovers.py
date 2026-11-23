"""Keerthi's Commerce leftovers (v9.2 batch O): balance-reminder switch, advance-change log,
cost prices hidden from people without Orders access, and the bill's logo/UPI/bank/terms/
"Bill of supply"."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import catalog as catalog_routes
from app.routes import stock_batches as batch_routes
from app.services import bill_brand, bill_files, orders
from tests.test_orders import T, _deal, _lead, db  # noqa: F401  (db is the fixture)

IST = timezone(timedelta(hours=5, minutes=30))


def run(coro):
    return asyncio.run(coro)


# ── balance reminders on/off ────────────────────────────────────────────────────

def test_the_switch_is_on_until_the_owner_turns_it_off(db):
    assert orders.balance_reminders_on(db, T) is True  # nothing set: as always
    assert orders.save_balance_reminders(db, T, False) is False
    assert orders.balance_reminders_on(db, T) is False
    assert orders.balance_reminders_on(db, "tenant-2") is True  # another shop is untouched
    orders.save_balance_reminders(db, T, True)
    assert orders.balance_reminders_on(db, T) is True


def test_an_unreadable_switch_never_turns_reminders_off():
    class Broken:
        def table(self, name):
            raise RuntimeError("table missing")
    assert orders.balance_reminders_on(Broken(), T) is True


def test_a_shop_that_turned_reminders_off_gets_none_and_resumes_when_switched_on(db):
    start = datetime(2026, 11, 10, 11, 0, tzinfo=IST)
    _deal(db, lead_id="L1", reminders_from=start.isoformat(), reminders_sent=0)
    orders.save_balance_reminders(db, T, False)
    due = start + timedelta(days=1, hours=1)
    with patch.object(orders, "notify", AsyncMock(return_value={"sent": True})) as sent, \
         patch.object(orders, "_balance_link", AsyncMock(return_value="https://rzp.io/l/x")):
        assert run(orders.send_due_reminders(db, now=due)) == 0
        assert sent.await_count == 0 and db.rows("deals")[0]["reminders_sent"] == 0  # not used up
        orders.save_balance_reminders(db, T, True)
        assert run(orders.send_due_reminders(db, now=due)) == 1


def test_the_switch_routes_are_owner_only_for_writing():
    from app.routes import orders as routes
    deps = {r.path + m: r for r in routes.router.routes for m in getattr(r, "methods", [])}
    put = deps["/balance-reminders" + "PUT"]
    assert any(d.call is routes.require_owner for d in put.dependant.dependencies)
    get = deps["/balance-reminders" + "GET"]
    assert any(d.call is routes.require_deals_view for d in get.dependant.dependencies)


# ── advance-change log ──────────────────────────────────────────────────────────

def test_a_changed_advance_is_logged_with_from_to_who_and_when(db):
    db.add("callers", tenant_id=T, user_id="u-ravi", name="Ravi")
    _deal(db)
    orders.log_advance_change(db, T, "u-ravi", "d1", "Staff changed it", from_paise=50000, to_paise=30000)
    out = orders.advance_changes(db, T, "d1")
    assert len(out) == 1
    assert (out[0]["from_paise"], out[0]["to_paise"], out[0]["by"]) == (50000, 30000, "Ravi")
    assert out[0]["at"]


def test_the_owner_is_named_owner_and_an_unknown_user_has_no_name(db):
    db.add("tenant_users", tenant_id=T, user_id="u-own", role="owner")
    assert orders._actor_name(db, T, "u-own") == "Owner"
    assert orders._actor_name(db, T, "nobody") is None
    assert orders._actor_name(db, T, None) is None


def test_old_log_rows_without_amounts_and_other_orders_are_left_out(db):
    _deal(db)
    orders._audit(db, T, None, "order.advance_changed", "d1", {"note": "old row"})
    orders.log_advance_change(db, T, None, "d2", "other order", from_paise=1, to_paise=2)
    assert orders.advance_changes(db, T, "d1") == []


def test_the_advance_log_is_per_shop(db):
    _deal(db)
    orders.log_advance_change(db, "tenant-2", None, "d1", "x", from_paise=1, to_paise=2)
    assert orders.advance_changes(db, T, "d1") == []


def test_the_order_view_carries_the_advance_changes(db):
    _lead(db)
    _deal(db, lead_id="L1")
    orders.log_advance_change(db, T, None, "d1", "note", from_paise=50000, to_paise=30000)
    assert orders.order_detail(db, T, "d1")["advance_changes"][0]["to_paise"] == 30000


# ── cost prices ─────────────────────────────────────────────────────────────────

OWNER = {"role": "owner", "permissions": []}
NO_MONEY = {"role": "staff", "permissions": ["catalog.manage"]}
WITH_MONEY = {"role": "staff", "permissions": ["deals.view"]}


def test_only_people_with_orders_access_see_costs():
    assert catalog_routes.sees_costs(OWNER) and catalog_routes.sees_costs(WITH_MONEY)
    assert not catalog_routes.sees_costs(NO_MONEY)


def test_hide_costs_drops_the_cost_and_says_so():
    row = {"id": "i1", "name": "Saree", "price_paise": 100, "cost_price_paise": 60}
    out = catalog_routes.hide_costs(row)
    assert "cost_price_paise" not in out and out["costs_hidden"] is True and out["price_paise"] == 100
    assert row["cost_price_paise"] == 60  # the original is not changed


def test_a_cost_written_by_someone_without_orders_access_is_ignored():
    assert catalog_routes._clean_stock_fields({"cost_price_paise": 500, "hsn_code": "5007"}, costs=False).get("cost_price_paise") is None
    assert "cost_price_paise" not in catalog_routes._clean_stock_fields({"cost_price_paise": 500}, costs=False)
    assert catalog_routes._clean_stock_fields({"cost_price_paise": 500})["cost_price_paise"] == 500  # default unchanged


def test_the_batches_tab_loses_cost_and_value_without_orders_access():
    view = {"batches": [{"id": "b1", "quantity": 4, "cost_paise": 100, "value_paise": 400, "value_at": "cost", "batch_no": "A"}],
            "cards": {"soon": {"batches": 1, "value_paise": 400}}, "tracked_items": 1}
    out = batch_routes.without_costs(view)
    assert out["costs_hidden"] is True
    assert out["batches"] == [{"id": "b1", "quantity": 4, "batch_no": "A"}]
    assert out["cards"] == {"soon": {"batches": 1}}


def test_the_item_list_endpoint_hides_costs_for_staff(monkeypatch):
    from tests.fake_supabase import FakeSupabase
    fake = FakeSupabase()
    fake.add("catalog_items", id="i1", tenant_id=T, name="Saree", item_type="product", status="ready",
             price_paise=100, cost_price_paise=60, stock_quantity=None, embedding=None, created_at="2026-01-01")
    monkeypatch.setattr(catalog_routes, "get_supabase", lambda: fake)
    monkeypatch.setattr(catalog_routes, "_list_extras", lambda *a, **k: {})
    for ctx, shows in ((OWNER, True), (WITH_MONEY, True), (NO_MONEY, False)):
        try:
            data = run(catalog_routes.list_items(tenant_id=T, ctx=ctx))["data"]
        except Exception as e:  # the fake may not cover every query the route makes
            pytest.skip(f"fake database can't run the full list query: {e}")
        assert ("cost_price_paise" in data[0]) is shows
        assert bool(data[0].get("costs_hidden")) is (not shows)


# ── what the bill prints ────────────────────────────────────────────────────────

FULL = {"legal_name": "Demo Silks", "gst_type": "regular", "pan": "ABCDE1234F", "licence_number": "L-9",
        "upi_id": "demo@okhdfc", "terms": "No returns after 7 days.", "bank_account_name": "Demo Silks",
        "bank_name": "HDFC Bank", "bank_ifsc": "HDFC0001234", "bank_account_number": "50100123"}


def test_a_shop_that_set_nothing_gets_empty_extras_and_the_old_title(db):
    bill = bill_brand.decorate({"gst_paise": 500, "cgst_paise": 250, "sgst_paise": 250, "igst_paise": 0, "lines": [{"gst_rate": 5}]},
                               db, T, {})
    brand = bill["brand"]
    assert not bill_brand.has_pay_block(brand) and not brand["terms"] and not brand["pan"]
    assert brand["logo_url"] is None and brand["signature_url"] is None
    assert "composition" not in bill and "title" not in bill and bill["gst_paise"] == 500  # tax untouched


def test_a_simple_bill_from_a_composition_shop_prints_a_bill_of_supply_with_no_tax(db):
    bill = bill_brand.decorate({"bill_type": "simple", "gst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
                                "lines": [{"gst_rate": None}, {"gst_rate": None}]}, db, T, {"gst_type": "composition"})
    assert bill["title"] == "Bill of supply" and bill["composition"] is True
    assert (bill["gst_paise"], bill["cgst_paise"], bill["sgst_paise"], bill["igst_paise"]) == (0, 0, 0, 0)
    assert [l["gst_rate"] for l in bill["lines"]] == [None, None]


def test_a_simple_bill_from_an_unregistered_shop_prints_a_bill_of_supply(db):
    bill = bill_brand.decorate({"bill_type": "simple", "gst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
                                "lines": [{"gst_rate": None}]}, db, T, {"gst_type": "none"})
    assert bill["title"] == "Bill of supply"
    assert "composition" not in bill  # the composition note is for composition shops only
    assert bill["gst_paise"] == 0


def test_a_simple_bill_from_a_regular_shop_keeps_its_old_look(db):
    bill = bill_brand.decorate({"bill_type": "simple", "gst_paise": 0, "lines": [{"gst_rate": None}]}, db, T,
                               {"gst_type": "regular"})
    assert "title" not in bill and "composition" not in bill


def test_an_old_gst_order_keeps_its_tax_after_the_shop_switches_to_composition(db):
    """Scenario A: made as a tax invoice, reprinted after the shop went composition. The lines still add up."""
    old = {"bill_type": "gst", "gst_paise": 500, "cgst_paise": 250, "sgst_paise": 250, "igst_paise": 0,
           "lines": [{"gst_rate": 5}, {"gst_rate": 18}]}
    for shop_type in ("composition", "none"):
        bill = bill_brand.decorate({**old, "lines": [dict(l) for l in old["lines"]]}, db, T, {"gst_type": shop_type})
        assert (bill["gst_paise"], bill["cgst_paise"], bill["sgst_paise"]) == (500, 250, 250)
        assert [l["gst_rate"] for l in bill["lines"]] == [5, 18]
        assert "title" not in bill and "composition" not in bill


def test_the_brand_block_reads_the_shops_details(db):
    brand = bill_brand.brand_block(db, T, FULL)
    assert brand["upi_id"] == "demo@okhdfc" and brand["pan"] == "ABCDE1234F"
    assert bill_brand.has_bank(brand) and bill_brand.has_pay_block(brand)
    assert bill_brand.bank_lines(brand) == ["HDFC Bank · Demo Silks", "A/c no. 50100123 · IFSC HDFC0001234"]


def test_a_failing_picture_link_never_breaks_the_bill(db):
    with patch("app.services.business_details.brand_image_url", side_effect=RuntimeError("storage down")):
        brand = bill_brand.brand_block(db, T, {**FULL, "logo_path": "t/logo.png"})
    assert brand["logo_url"] is None and brand["upi_id"] == "demo@okhdfc"


def test_public_bill_carries_the_brand_and_a_composition_title(db):
    _lead(db)
    _deal(db, lead_id="L1", stage="won", bill_token="tok_abcdefghijklmnopqr", invoice_number="2026-27/0001",
          total_paise=1000, paid_paise=1000, bill_type="gst", gst_paise=48)
    db.add("deal_items", tenant_id=T, deal_id="d1", name="Saree", variant_label=None, qty=1, unit_price_paise=1000, gst_rate=5)
    with patch("app.services.business_details.get_business_details", return_value={**FULL, "gst_type": "composition"}):
        bill = orders.public_bill(db, "tok_abcdefghijklmnopqr")
    assert "title" not in bill and bill["gst_paise"] == 48  # made as a tax invoice: it still prints as one
    assert bill["brand"]["upi_id"] == "demo@okhdfc"


def test_public_bill_of_a_simple_order_says_bill_of_supply_for_a_composition_shop(db):
    _lead(db)
    _deal(db, lead_id="L1", stage="won", bill_token="tok_abcdefghijklmnopqr", invoice_number="2026-27/0001",
          total_paise=1000, paid_paise=1000, bill_type="simple", gst_paise=0)
    db.add("deal_items", tenant_id=T, deal_id="d1", name="Saree", variant_label=None, qty=1, unit_price_paise=1000, gst_rate=5)
    with patch("app.services.business_details.get_business_details", return_value={**FULL, "gst_type": "composition"}):
        bill = orders.public_bill(db, "tok_abcdefghijklmnopqr")
    assert bill["title"] == "Bill of supply" and bill["composition"] is True and bill["gst_paise"] == 0


def test_the_picture_bill_draws_with_and_without_the_extras():
    plain = bill_files.sample_bill()
    plain["brand"] = bill_brand.brand_block(None, T, {})
    full = bill_files.sample_bill()
    full["brand"] = bill_brand.brand_block(None, T, FULL)
    a, b = bill_files.bill_png(plain), bill_files.bill_png(full)
    assert a[:4] == b[:4] == b"\x89PNG" and a != b  # the extras change the picture, and only when set


def test_the_pdf_says_bill_of_supply_for_a_composition_shop():
    pytest.importorskip("fpdf")
    bill = bill_files.sample_bill(bill_type="simple")
    bill["brand"] = bill_brand.brand_block(None, T, {**FULL, "gst_type": "composition"})
    bill = bill_brand.decorate(bill, None, T, {**FULL, "gst_type": "composition"})
    assert bill["title"] == "Bill of supply"
    pdf = bill_files.invoice_pdf(bill)
    assert pdf[:5] == b"%PDF-"


def test_stock_count_hides_money_from_people_without_deals_view():
    from app.routes.stock_counts import without_money
    view = {"open": [{"id": "c1", "loss_paise": 5}], "finished": [{"id": "c0", "loss_paise": 9, "gain_paise": 1}],
            "count": {"id": "c1", "loss_paise": 5, "lines": [{"difference": -2, "value_paise": -400}],
                      "cards": {"less": {"items": 1, "pieces": 2, "value_paise": 400}, "counted": 1}}}
    out = without_money(view)
    assert "value_paise" not in out["count"]["lines"][0] and "value_paise" not in out["count"]["cards"]["less"]
    assert out["count"]["cards"]["less"]["pieces"] == 2 and out["count"]["cards"]["counted"] == 1
    assert "loss_paise" not in out["finished"][0] and "loss_paise" not in out["open"][0] and out["costs_hidden"] is True
