"""Commerce > Orders & payments (services/orders.py, the payment rules in services/deals.py,
routes/orders.py and the sizes x colours grid in routes/catalog.py), on the fake database.
The SQL functions and the deal_payments -> deals.paid_paise trigger are stood in below."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import deals as deals_service
from app.services import orders
from tests.fake_supabase import FakeSupabase

T = "tenant-1"
KURTI = "11111111-2222-3333-4444-555555555555"


class OrdersFake(FakeSupabase):
    """FakeSupabase plus migration 294's SQL: invoice and deal counters, both stock functions,
    and the trigger that keeps deals.paid_paise = sum(deal_payments)."""

    def __init__(self):
        super().__init__()
        self._deal_no = 1040
        self._invoice: dict = {}
        self.rpc_handlers.update({
            "next_deal_number": self._next_deal,
            "next_invoice_number": self._next_invoice,
            "apply_stock_movement": self._item_move,
            "apply_variant_stock_movement": self._variant_move,
        })

    def _next_deal(self, p):
        self._deal_no += 1
        return self._deal_no

    def _next_invoice(self, p):
        key = (p["p_tenant_id"], p["p_fy"])
        self._invoice[key] = self._invoice.get(key, 0) + 1
        return self._invoice[key]

    def _item_move(self, p):
        item = next((i for i in self.rows("catalog_items") if i["id"] == p["p_item_id"]), None)
        if not item or item.get("stock_quantity") is None:
            return [{"ok": bool(item), "tracked": False, "quantity_after": None}]
        after = item["stock_quantity"] + p["p_delta"]
        if after < 0:
            return [{"ok": False, "tracked": True, "quantity_after": item["stock_quantity"]}]
        item["stock_quantity"] = after
        self.rows("stock_movements").append({"catalog_item_id": item["id"], "delta": p["p_delta"], "reason": p["p_reason"]})
        return [{"ok": True, "tracked": True, "quantity_after": after}]

    def _variant_move(self, p):
        v = next((r for r in self.rows("catalog_item_variants") if r["id"] == p["p_variant_id"]), None)
        if not v or v["stock_quantity"] + p["p_delta"] < 0:
            return [{"ok": False, "quantity_after": v["stock_quantity"] if v else None, "item_quantity_after": None}]
        v["stock_quantity"] += p["p_delta"]
        item = next(i for i in self.rows("catalog_items") if i["id"] == v["catalog_item_id"])
        item["stock_quantity"] = sum(r["stock_quantity"] for r in self.rows("catalog_item_variants")
                                     if r["catalog_item_id"] == item["id"])
        self.rows("stock_movements").append({"catalog_item_id": item["id"], "variant_id": v["id"],
                                             "delta": p["p_delta"], "reason": p["p_reason"]})
        return [{"ok": True, "quantity_after": v["stock_quantity"], "item_quantity_after": item["stock_quantity"]}]

    def table(self, name):
        q = super().table(name)
        if name == "deal_payments":
            run = q.execute

            def execute():
                res = run()
                for d in self.rows("deals"):
                    d["paid_paise"] = sum(int(x["amount_paise"]) for x in self.rows("deal_payments") if x["deal_id"] == d["id"])
                return res
            q.execute = execute
        return q


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    db = OrdersFake()
    db.add("catalog_items", id="saree", tenant_id=T, name="Kanchi pattu", item_type="product", price_paise=890000,
           gst_rate=5, stock_quantity=None, status="ready")
    db.add("catalog_items", id="stitch", tenant_id=T, name="Blouse stitching", item_type="service", price_paise=160000,
           gst_rate=5, stock_quantity=None, status="ready")
    db.add("catalog_item_variants", id="red-m", tenant_id=T, catalog_item_id="saree", size="M", colour="Red",
           stock_quantity=1, price_paise=None, sort_order=0)
    db.add("catalog_item_variants", id="red-l", tenant_id=T, catalog_item_id="saree", size="L", colour="Red",
           stock_quantity=3, price_paise=None, sort_order=1)
    db.rows("catalog_items")[0]["stock_quantity"] = 4
    db.add("callers", id="ravi", tenant_id=T, name="Ravi", active=True)
    return db


@pytest.fixture(autouse=True)
def quiet_lead_creation():
    def make_lead(tenant_id, phone, source, *, name=None, opt_in_source=None, db=None, **_):
        digits = "".join(c for c in phone if c.isdigit())[-10:]
        if len(digits) < 10:
            return None
        existing = next((l for l in db.rows("leads") if l.get("phone") == "+91" + digits), None)
        if existing:
            return existing["id"]
        return db.add("leads", id=f"lead-{digits}", tenant_id=tenant_id, phone="+91" + digits, name=None,
                      source=source, deleted_at=None)["id"]
    with patch("app.services.inbound_lead.create_inbound_lead", side_effect=make_lead):
        yield


def _deal(db, **extra):
    row = {"id": "d1", "tenant_id": T, "deal_number": 1, "stage": "awaiting_payment", "source": "manual",
           "channel": "online", "total_paise": 240000, "paid_paise": 0, "lead_id": None, "handover": None,
           "delivery_status": "none", "created_at": datetime.now(timezone.utc).isoformat()}
    row.update(extra)
    db.rows("deals").append(row)
    return row


# ── bill maths ──────────────────────────────────────────────────────────────────

def test_discount_is_spread_and_gst_is_inside_the_price():
    lines = [{"unit_price_paise": 890000, "qty": 1, "gst_rate": 5}, {"unit_price_paise": 160000, "qty": 1, "gst_rate": 5}]
    bill = orders.compute_bill(lines, discount_paise=50000, include_gst=True, bill_type="gst")
    assert bill["subtotal_paise"] == 1050000
    assert [li["discount_paise"] for li in bill["lines"]] == [42380, 7620]
    assert bill["total_paise"] == 1000000
    assert bill["gst_paise"] == sum(li["gst_paise"] for li in bill["lines"]) == 47619


def test_gst_on_top_and_simple_bill():
    lines = [{"unit_price_paise": 100000, "qty": 2, "gst_rate": 12}]
    assert orders.compute_bill(lines, discount_paise=0, include_gst=False, bill_type="gst")["total_paise"] == 224000
    simple = orders.compute_bill(lines, discount_paise=0, include_gst=False, bill_type="simple")
    assert (simple["total_paise"], simple["gst_paise"]) == (200000, 0)


def test_igst_only_for_another_state():
    assert orders.gst_split("33ABCDE1234F1Z5", "29ABCDE1234F1Z5", 1000)["igst_paise"] == 1000
    assert orders.gst_split("33ABCDE1234F1Z5", "33XYZDE1234F1Z5", 1001) == {"igst_paise": 0, "cgst_paise": 501, "sgst_paise": 500}
    assert orders.gst_split("33ABCDE1234F1Z5", None, 1000)["cgst_paise"] == 500


def test_financial_year_turns_in_april():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert orders.fiscal_year(datetime(2027, 3, 31, 23, 0, tzinfo=ist)) == "2026-27"
    assert orders.fiscal_year(datetime(2027, 4, 1, 0, 30, tzinfo=ist)) == "2027-28"


# ── payments ────────────────────────────────────────────────────────────────────

def test_advance_then_balance_wins_once_and_numbers_the_invoice(db):
    _deal(db)
    first = deals_service.record_payment(T, "d1", 100000, "cash", db=db)
    assert (first["status"], first["won"]) == ("recorded", False)
    deal = db.rows("deals")[0]
    assert (deal["stage"], deal["paid_paise"], orders.payment_state(deal)) == ("awaiting_payment", 100000, "advance")
    assert deal["invoice_number"].endswith("/0001") and deal["bill_token"]
    assert deals_service.record_payment(T, "d1", 200000, "upi", db=db)["status"] == "over"
    done = deals_service.record_payment(T, "d1", 140000, "upi", db=db)
    assert (done["status"], done["won"]) == ("recorded", True)
    assert [p["amount_paise"] for p in db.rows("deal_payments")] == [100000, 140000]
    assert deal["stage"] == "won" and deal["invoice_number"].endswith("/0001")
    assert deals_service.record_payment(T, "d1", 100, "cash", db=db)["status"] == "over"


def test_a_retried_razorpay_payment_counts_once_and_a_lost_order_takes_nothing(db):
    _deal(db)
    assert deals_service.record_payment(T, "d1", 50000, "razorpay", razorpay_payment_id="pay_1", db=db)["status"] == "recorded"
    assert deals_service.record_payment(T, "d1", 50000, "razorpay", razorpay_payment_id="pay_1", db=db)["status"] == "duplicate"
    assert len(db.rows("deal_payments")) == 1
    _deal(db, id="d2", stage="lost")
    assert deals_service.record_payment(T, "d2", 50000, "cash", db=db)["status"] == "closed"


def test_mark_won_records_only_what_was_left(db):
    _deal(db)
    deals_service.record_payment(T, "d1", 100000, "cash", db=db)
    deals_service.mark_won(T, "d1", payment_method="cash", db=db)
    assert [(p["amount_paise"], p["kind"]) for p in db.rows("deal_payments")] == [(100000, "advance"), (140000, "balance")]


# ── New bill ────────────────────────────────────────────────────────────────────

def _bill(db, **data):
    base = {"mode": "now", "items": [{"catalog_item_id": "saree", "variant_id": "red-m", "qty": 1}],
            "method": "cash", "bill_type": "gst", "discount_paise": 0}
    base.update(data)
    with patch.object(orders, "notify", AsyncMock(return_value={"sent": False, "reason": "no_phone"})) as sent:
        out = run(orders.create_bill(db, T, base, user_id="u1"))
    return out, sent


def test_taking_it_now_is_paid_takes_that_size_off_the_shelf_and_numbers_the_bill(db):
    out, sent = _bill(db, phone="98400 12345", name="Priya", sold_by="ravi")
    order = out["order"]
    assert (order["payment"], order["delivery"], order["channel"]) == ("paid", "taken", "store")
    assert order["invoice_number"].endswith("/0001")
    variant = next(v for v in db.rows("catalog_item_variants") if v["id"] == "red-m")
    assert variant["stock_quantity"] == 0 and db.rows("catalog_items")[0]["stock_quantity"] == 3
    assert db.rows("deal_items")[0]["variant_label"] == "Red · M"
    lead = db.rows("leads")[0]
    assert (lead["source"], lead["name"]) == ("store", "Priya")
    assert sent.await_args.args[3] == "bill"
    assert out["stock_short"] == []


def test_walk_in_with_no_number_still_counts_and_sends_nothing(db):
    out, sent = _bill(db)
    assert out["order"]["customer"]["lead_id"] is None and out["order"]["customer"]["came_from"] == "Walk-in"
    assert out["order"]["payment"] == "paid"
    sent.assert_not_awaited()
    with pytest.raises(orders.OrderError):
        _bill(db, method="link")  # a link needs a phone


def test_deliver_later_with_an_advance_waits_for_the_balance(db):
    out, _ = _bill(db, mode="later", phone="9840012345", advance_paise=300000, method="upi",
                   items=[{"catalog_item_id": "stitch", "qty": 1}, {"catalog_item_id": "saree", "variant_id": "red-l", "qty": 1}])
    order = out["order"]
    assert (order["payment"], order["next_action"], order["delivery"]) == ("advance", "collect", "working")
    assert order["balance_paise"] == 1050000 - 300000
    assert next(v for v in db.rows("catalog_item_variants") if v["id"] == "red-l")["stock_quantity"] == 3  # not yet
    with pytest.raises(orders.OrderError):
        _bill(db, mode="later", advance_paise=99999999)


def test_a_bad_gstin_or_a_stranger_teammate_is_refused(db):
    with pytest.raises(orders.OrderError):
        _bill(db, gstin="12345")
    with pytest.raises(orders.OrderError):
        _bill(db, sold_by="someone-else")


# ── what the list shows ─────────────────────────────────────────────────────────

def test_only_orders_with_something_to_hand_over_need_packing():
    service = {"stage": "won", "paid_paise": 100, "handover": None, "deal_items": [{"catalog_items": {"item_type": "service"}}]}
    product = {"stage": "won", "paid_paise": 100, "handover": None, "deal_items": [{"catalog_items": {"item_type": "product"}}]}
    shipped = {"stage": "won", "paid_paise": 100, "handover": "courier", "delivery_status": "shipped"}
    taken = {"stage": "won", "paid_paise": 100, "handover": "taken"}
    assert [orders.needs_packing(d) for d in (service, product, shipped, taken)] == [False, True, False, False]
    assert orders.next_action({**product}) == "ready"
    assert orders.next_action({"stage": "won", "paid_paise": 1, "handover": "courier"}) == "tracking"
    assert orders.next_action({"stage": "awaiting_payment", "paid_paise": 0}) == "remind"


def test_list_counts_chips_and_money_in(db):
    _deal(db, id="a", stage="awaiting_payment", paid_paise=0)
    _deal(db, id="b", stage="awaiting_payment", paid_paise=100000)
    _deal(db, id="c", stage="won", paid_paise=240000, gst_paise=11429, bill_type="gst")
    _deal(db, id="d", stage="lost")
    db.rows("deal_payments").extend([
        {"tenant_id": T, "deal_id": "b", "amount_paise": 100000, "paid_at": datetime.now(timezone.utc).isoformat()},
        {"tenant_id": T, "deal_id": "c", "amount_paise": 240000, "paid_at": datetime.now(timezone.utc).isoformat()},
    ])
    out = orders.list_orders(db, T, chip="advance")
    assert [r["id"] for r in out["data"]] == ["b"]
    assert out["counts"]["all"] == 4 and out["counts"]["waiting"] == 1 and out["counts"]["cancelled"] == 1
    assert out["cards"]["money_in"]["paise"] == 340000
    assert out["cards"]["to_collect"] == {"paise": 240000 + 140000, "orders": 2, "reminders_on": 0}
    assert out["cards"]["gst"] == {"paise": 11429, "bills": 1}


# ── WhatsApp to the customer ────────────────────────────────────────────────────

def _lead(db, inbound_hours_ago=None):
    at = (datetime.now(timezone.utc) - timedelta(hours=inbound_hours_ago)).isoformat() if inbound_hours_ago is not None else None
    return db.add("leads", id="L1", tenant_id=T, name="Revathi M", phone="+919840012345", opted_out=False,
                  last_inbound_at=at, deleted_at=None)


def _connected(key, fallback=None, tenant_id=None):
    return "x" if key in ("meta_phone_number_id", "meta_access_token", "meta_waba_id") else fallback


def test_inside_24_hours_a_normal_message_goes_and_is_listed(db):
    _lead(db, inbound_hours_ago=2)
    _deal(db, lead_id="L1", stage="awaiting_payment", paid_paise=100000, handover="pickup", bill_token="t" * 22)
    with patch("app.config_dynamic.get_setting", side_effect=_connected), \
         patch("app.services.ai_reply.send_whatsapp", AsyncMock(return_value="wamid.1")) as send:
        out = run(orders.notify(db, T, "d1", "ready", pay_link="https://rzp.io/l/x"))
    assert (out["sent"], out["via"]) == (True, "text")
    assert "ready for pickup" in send.await_args.args[1] and "₹1,400" in send.await_args.args[1]
    assert db.rows("deal_messages")[0]["kind"] == "ready" and db.rows("messages")[0]["meta_message_id"] == "wamid.1"


def test_outside_24_hours_with_no_template_staff_get_a_share_link(db):
    _lead(db, inbound_hours_ago=48)
    _deal(db, lead_id="L1")
    with patch("app.config_dynamic.get_setting", side_effect=_connected), \
         patch("app.services.call_details_share._approved_templates", return_value=[]):
        out = run(orders.notify(db, T, "d1", "reminder"))
    assert (out["sent"], out["reason"]) == (False, "outside_24h_no_template")
    assert out["share_url"].startswith("https://wa.me/919840012345?text=")
    assert db.rows("deal_messages") == []


def test_outside_24_hours_the_approved_order_template_goes(db):
    _lead(db, inbound_hours_ago=48)
    _deal(db, lead_id="L1")
    template = {"id": "tpl", "name": "anril_payment_reminder", "body_text": orders.ORDER_TEMPLATES["reminder"]["body"]}
    with patch("app.config_dynamic.get_setting", side_effect=_connected), \
         patch("app.services.call_details_share._approved_templates", return_value=[template]), \
         patch("app.services.meta_cloud.send_template_message", AsyncMock(return_value={"messages": [{"id": "wamid.2"}]})) as tpl:
        out = run(orders.notify(db, T, "d1", "reminder", pay_link="https://rzp.io/l/x"))
    assert (out["sent"], out["via"]) == (True, "template")
    assert tpl.await_args.args[1] == "anril_payment_reminder"
    values = [p["text"] for p in tpl.await_args.kwargs["components"][0]["parameters"]]
    assert values[0] == "Revathi" and values[2] == "₹2,400" and values[4] == "https://rzp.io/l/x"
    assert len(tpl.await_args.kwargs["components"]) == 1  # no buttons on a reminder


def test_the_quote_template_carries_accept_and_ask_payloads(db):
    _lead(db, inbound_hours_ago=48)
    _deal(db, lead_id="L1", stage="quoted")
    template = {"id": "tq", "name": "anril_order_quote", "body_text": orders.ORDER_TEMPLATES["quote"]["body"]}
    buttons = [{"id": "quote_accept:d1", "title": "Accept quote"}, {"id": "quote_ask:d1", "title": "Ask a question"}]
    with patch("app.config_dynamic.get_setting", side_effect=_connected),          patch("app.services.call_details_share._approved_templates", return_value=[template]),          patch("app.services.meta_cloud.send_template_message", AsyncMock(return_value={"messages": [{"id": "wamid.3"}]})) as tpl:
        out = run(orders.notify(db, T, "d1", "quote", buttons=buttons))
    assert out["sent"]
    sent_buttons = tpl.await_args.kwargs["components"][1:]
    assert [b["parameters"][0]["payload"] for b in sent_buttons] == ["quote_accept:d1", "quote_ask:d1"]
    assert [b["index"] for b in sent_buttons] == ["0", "1"]


# ── reminders ───────────────────────────────────────────────────────────────────

def test_reminders_go_on_day_1_3_7_in_shop_hours_and_stop_when_paid(db):
    ist = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 11, 10, 11, 0, tzinfo=ist)
    _deal(db, lead_id="L1", reminders_from=start.isoformat(), reminders_sent=0)
    with patch.object(orders, "notify", AsyncMock(return_value={"sent": True})) as sent, \
         patch.object(orders, "_balance_link", AsyncMock(return_value="https://rzp.io/l/x")):
        assert run(orders.send_due_reminders(db, now=start + timedelta(hours=20))) == 0   # not a day yet
        assert run(orders.send_due_reminders(db, now=start + timedelta(days=1, hours=1))) == 1
        assert run(orders.send_due_reminders(db, now=start + timedelta(days=1, hours=2))) == 0  # next is day 3
        late_night = datetime(2026, 11, 13, 22, 0, tzinfo=ist)
        assert run(orders.send_due_reminders(db, now=late_night)) == 0
        db.rows("deals")[0]["stage"] = "won"
        assert run(orders.send_due_reminders(db, now=start + timedelta(days=3, hours=1))) == 0
    assert db.rows("deals")[0]["reminders_sent"] == 1
    assert sent.await_count == 1


# ── the customer's bill page ────────────────────────────────────────────────────

def test_public_bill_by_token_shows_the_bill_and_hides_the_number(db):
    _lead(db)
    _deal(db, lead_id="L1", bill_token="tok_abcdefghijklmnopqr", invoice_number="2026-27/0042", total_paise=105000,
          gst_paise=5000, discount_paise=0, bill_type="gst", buyer_gstin=None)
    db.add("deal_items", tenant_id=T, deal_id="d1", name="Kanchi pattu", variant_label="Red · M", qty=1,
           unit_price_paise=105000, gst_rate=5)
    bill = orders.public_bill(db, "tok_abcdefghijklmnopqr")
    assert bill["invoice_number"] == "2026-27/0042"
    assert bill["customer"]["phone"] == "98•• ••345"
    assert (bill["cgst_paise"], bill["sgst_paise"]) == (2500, 2500)
    assert orders.public_bill(db, "nope") is None
    assert orders.public_bill(db, "x" * 22) is None


# ── the Razorpay webhook: an advance link adds an advance ───────────────────────

def test_an_advance_link_paid_records_the_advance_and_says_the_balance(db):
    from app.routes.intake import _handle_deal_payment_event
    _lead(db)
    _deal(db, lead_id="L1", payment_link="https://rzp.io/l/x", razorpay_payment_link_id="plink_1")
    paid = {"payload": {"payment": {"entity": {"id": "pay_9", "amount": 100000}}}}
    send = AsyncMock()
    with patch("app.services.deals.get_supabase", return_value=db), \
         patch("app.routes.intake.get_supabase", return_value=db), \
         patch("app.routes.intake.send_whatsapp", send):
        out = run(_handle_deal_payment_event(paid, "payment_link.paid", "d1", T))
        again = run(_handle_deal_payment_event(paid, "payment_link.paid", "d1", T))
    deal = db.rows("deals")[0]
    assert out == {"status": "ok"} and again["status"] == "ignored"
    assert (deal["stage"], deal["paid_paise"]) == ("awaiting_payment", 100000)
    assert "Balance ₹1,400" in send.await_args_list[0].args[1]
    assert send.await_count == 1


# ── sizes x colours grid ────────────────────────────────────────────────────────

def test_the_grid_makes_each_size_and_the_item_total_follows(db):
    from fastapi.testclient import TestClient
    from app.dependencies.auth import get_current_user
    from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
    from app.main import app
    db.add("catalog_items", id=KURTI, tenant_id=T, name="Cotton kurti", item_type="product", stock_quantity=6, status="ready")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_id] = lambda: T
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "owner", "user_id": "u1", "permissions": []}
    try:
        with patch("app.routes.catalog.get_supabase", return_value=db), patch("app.services.deals.get_supabase", return_value=db):
            client = TestClient(app)
            res = client.put(f"/api/v1/catalog/items/{KURTI}/variants", json={
                "sizes": ["S", "M", "m"], "colours": ["Blue"],
                "cells": [{"size": "S", "colour": "Blue", "stock": 2}, {"size": "M", "colour": "Blue", "stock": 5}],
            })
            assert res.status_code == 200, res.text
            assert res.json()["sizes"] == ["S", "M"]
            kurti = next(i for i in db.rows("catalog_items") if i["id"] == KURTI)
            assert kurti["stock_quantity"] == 7
            # The single number can't be changed any more: the grid owns it.
            assert client.post(f"/api/v1/catalog/items/{KURTI}/stock", json={"reason": "restock", "delta": 1}).status_code == 400
            res = client.put(f"/api/v1/catalog/items/{KURTI}/variants", json={
                "sizes": ["M"], "colours": ["Blue"], "cells": [{"size": "M", "colour": "Blue", "stock": 5}]})
            assert res.status_code == 200
            assert [v["size"] for v in res.json()["variants"]] == ["M"]
            assert kurti["stock_quantity"] == 5
    finally:
        app.dependency_overrides.clear()
