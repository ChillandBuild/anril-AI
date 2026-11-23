"""Orders & payments, round 3: Day closing (services/day_closing.py), the thank-you + Google
review message, the middle step's name, part refund by items, and the advance-rule note."""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import day_closing as dc
from app.services import order_refunds as refunds
from app.services import orders
from tests.test_order_quotes_refunds import Fake
from tests.test_orders import T

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    db = Fake()
    db.add("catalog_items", id="kurti", tenant_id=T, name="Cotton kurti", item_type="product", price_paise=65000,
           gst_rate=5, stock_quantity=10, status="ready")
    db.add("leads", id="L1", tenant_id=T, name="Divya M", phone="+919840011111", deleted_at=None)
    return db


def _at(hours_ago: float = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _deal(db, did, **extra):
    row = {"id": did, "tenant_id": T, "deal_number": 1, "stage": "won", "channel": "store", "total_paise": 195000,
           "paid_paise": 0, "refunded_paise": 0, "lead_id": "L1", "handover": "pickup", "delivery_status": "working",
           "created_at": _at(30)}
    row.update(extra)
    db.rows("deals").append(row)
    return row


# ── Day closing ─────────────────────────────────────────────────────────────────

def _early_today() -> str:
    return datetime.combine(TODAY, datetime.min.time(), IST).replace(minute=1).isoformat()


def _today_money(db):
    _deal(db, "a")
    _deal(db, "b")
    for deal, amount, method in (("a", 895000, "cash"), ("b", 980000, "upi"), ("a", 310000, "card")):
        db.rows("deal_payments").append({"tenant_id": T, "deal_id": deal, "amount_paise": amount, "method": method, "paid_at": _early_today()})
    db.rows("deal_payments").append({"tenant_id": T, "deal_id": "b", "amount_paise": 5000, "method": "cash",
                                     "paid_at": _at(48)})  # another day
    db.rows("deal_refunds").append({"tenant_id": T, "deal_id": "a", "amount_paise": 95000, "method": "cash",
                                    "status": "done", "created_at": _early_today()})
    db.rows("day_closings").append({"tenant_id": T, "day": (TODAY - timedelta(days=1)).isoformat(), "counted_paise": 200000})


def test_should_be_is_opening_plus_cash_sales_less_cash_refunds_and_spent(db):
    _today_money(db)
    dc.add_expense(db, T, TODAY, "Tea & food", 35000, "Meena", "u1")
    dc.add_expense(db, T, TODAY, "Transport", 120000, "Bala", "u1")
    s = dc.summary(db, T, TODAY)
    assert s["money_in"] == {"paise": 2185000, "bills": 2, "average_paise": 1092500}
    assert [(m["label"], m["paise"]) for m in s["methods"]] == [("Cash", 895000), ("UPI", 980000), ("Card", 310000)]
    assert s["refunds"]["items"] == [{"name": "Divya", "method": "Cash", "paise": 95000}]
    d = s["drawer"]
    assert (d["opening_paise"], d["opening_from"]) == (200000, "yesterday")  # yesterday's count
    assert d["expected_paise"] == 200000 + 895000 - 95000 - 155000


def test_closing_saves_the_count_and_rings_the_owner_when_short(db):
    _today_money(db)
    db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
    with patch("app.services.notify.notify_user") as bell:
        out = dc.close_day(db, T, TODAY, opening_paise=200000, counted_paise=980000, note=None, user_id="u1")
    assert out["difference_paise"] == 980000 - (200000 + 895000 - 95000)
    saved = next(r for r in db.rows("day_closings") if r["day"] == TODAY.isoformat())
    assert (saved["counted_paise"], saved["closed_by"]) == (980000, "u1")
    assert "short" in bell.call_args.args[3]
    with patch("app.services.notify.notify_user") as bell:
        dc.close_day(db, T, TODAY, opening_paise=200000, counted_paise=1000000, note=None, user_id="u1")
    bell.assert_not_called()  # matched: no bell
    assert dc.summary(db, T, TODAY)["drawer"]["opening_from"] == "closing"


def test_a_future_day_or_an_empty_expense_is_refused(db):
    with pytest.raises(orders.OrderError):
        dc.parse_day((TODAY + timedelta(days=1)).isoformat())
    with pytest.raises(orders.OrderError):
        dc.add_expense(db, T, TODAY, "  ", 100, None, None)


def test_running_low_lists_sizes_and_items_with_two_or_fewer(db):
    db.add("catalog_items", id="saree", tenant_id=T, name="Kanchi pattu", item_type="product", stock_quantity=1, status="ready")
    db.add("catalog_item_variants", id="v1", tenant_id=T, catalog_item_id="saree", size="M", colour="Red", stock_quantity=1)
    db.add("catalog_items", id="gown", tenant_id=T, name="Party wear gown", item_type="product", stock_quantity=2, status="ready")
    assert dc.running_low(db, T) == [{"name": "Kanchi pattu Red · M", "left": 1}, {"name": "Party wear gown", "left": 2}]


# ── thank you + Google review, middle step name ─────────────────────────────────

def test_delivered_message_thanks_and_asks_for_a_review_when_the_link_is_set(db):
    deal = _deal(db, "d1", deal_number=47)
    with patch.object(orders, "order_settings", return_value={"working_label": "Stitching", "google_review_link": "https://g.page/r/demo"}):
        text, values = orders.compose(db, T, deal, "delivered")
    assert "Thank you for choosing" in text and "picked up" in text and "https://g.page/r/demo" in text
    assert values[4] == "https://g.page/r/demo"
    with patch.object(orders, "order_settings", return_value={"working_label": "Working on it", "google_review_link": ""}):
        text, _ = orders.compose(db, T, deal, "delivered")
    assert "review" not in text


def test_settings_keep_the_review_link_https_only(db):
    with pytest.raises(orders.OrderError):
        orders.save_order_settings(db, T, {"working_label": "Stitching", "google_review_link": "javascript:alert(1)"})
    with patch("app.config_dynamic.invalidate_cache"):
        saved = orders.save_order_settings(db, T, {"working_label": "  Stitching ", "google_review_link": "https://g.page/r/x"})
    assert saved == {"working_label": "Stitching", "google_review_link": "https://g.page/r/x"}


def test_goes_out_next_lists_the_step_messages_then_reminders():
    pickup = {"stage": "awaiting_payment", "handover": "pickup", "delivery_status": "working", "total_paise": 100, "paid_paise": 30,
              "reminders_from": datetime.now(timezone.utc).isoformat(), "reminders_sent": 0}
    kinds = [u["kind"] for u in orders._upcoming(pickup)]
    assert kinds == ["ready", "delivered", "reminder"]
    courier = {**pickup, "stage": "won", "handover": "courier", "delivery_status": "ready"}
    assert [u["kind"] for u in orders._upcoming(courier)] == ["shipped", "delivered"]
    assert orders._upcoming({**pickup, "delivery_status": "delivered", "stage": "won"}) == []


# ── part refund by items ────────────────────────────────────────────────────────

def test_part_refund_puts_the_picked_pieces_back_and_not_twice(db):
    _deal(db, "o1", deal_number=45)
    line = db.add("deal_items", tenant_id=T, deal_id="o1", catalog_item_id="kurti", variant_id=None, name="Cotton kurti", qty=3)
    db.table("deal_payments").insert({"tenant_id": T, "deal_id": "o1", "amount_paise": 195000, "method": "cash", "paid_at": _at()}).execute()
    with patch.object(orders, "notify", AsyncMock(return_value={"sent": True})):
        run(refunds.refund(db, T, "o1", mode="part", amount_paise=65000, method="cash", reason="Damaged",
                           items=[{"deal_item_id": line["id"], "qty": 1}]))
        assert db.rows("catalog_items")[0]["stock_quantity"] == 11
        assert refunds.returnable_items(db, T, "o1") == {line["id"]: 2}
        with pytest.raises(orders.OrderError, match="More pieces"):
            run(refunds.refund(db, T, "o1", mode="part", amount_paise=65000, method="cash", reason="Damaged",
                               items=[{"deal_item_id": line["id"], "qty": 3}]))
    row = db.rows("deal_refunds")[0]
    assert row["items"] == [{"deal_item_id": line["id"], "qty": 1}] and row["restocked"] is True
    assert db.rows("deals")[0]["stage"] == "won"  # a part refund keeps the order


# ── advance-rule note ───────────────────────────────────────────────────────────

def test_new_bill_notes_when_staff_change_the_shop_advance(db):
    rule = {"kind": "percent", "value": 30, "min_total_paise": 0}
    with patch("app.services.order_quotes.advance_rule", return_value=rule), \
         patch.object(orders, "notify", AsyncMock(return_value={"sent": False})), \
         patch("app.services.inbound_lead.create_inbound_lead", return_value="L1"):
        out = run(orders.create_bill(db, T, {"mode": "later", "phone": "9840011111", "items": [{"catalog_item_id": "kurti", "qty": 10}],
                                             "method": "cash", "advance_paise": 100000}, user_id="u1"))
        same = run(orders.create_bill(db, T, {"mode": "later", "phone": "9840011111", "items": [{"catalog_item_id": "kurti", "qty": 10}],
                                              "method": "cash", "advance_paise": 195000}, user_id="u1"))
    assert out["order"]["advance_note"] == "Advance rule 30% (₹1,950). Staff changed it to ₹1,000 for this order."
    assert same["order"]["advance_note"] is None
    assert any(a.get("action") == "order.advance_changed" for a in db.rows("app_audit_logs"))


def test_new_bill_refuses_a_changed_advance_when_the_owner_locked_it(db):
    rule = {"kind": "percent", "value": 30, "min_total_paise": 0}
    bill = {"mode": "later", "phone": "9840011111", "items": [{"catalog_item_id": "kurti", "qty": 10}], "method": "cash"}
    with patch("app.services.order_quotes.advance_rule", return_value=rule), \
         patch.object(orders, "notify", AsyncMock(return_value={"sent": False})), \
         patch("app.services.inbound_lead.create_inbound_lead", return_value="L1"):
        with pytest.raises(orders.OrderError, match="owner set one advance rule"):
            run(orders.create_bill(db, T, {**bill, "advance_paise": 100000}, user_id="u1", may_change_advance=False))
        ok = run(orders.create_bill(db, T, {**bill, "advance_paise": 195000}, user_id="u1", may_change_advance=False))
    assert ok["order"]["advance_note"] is None
