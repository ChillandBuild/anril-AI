"""Orders & payments: quotes with Accept (services/order_quotes.py) and refunds
(services/order_refunds.py), on the fake database from test_orders."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import order_quotes as quotes
from app.services import order_refunds as refunds
from app.services import orders
from tests.test_orders import OrdersFake, T

IST = timezone(timedelta(hours=5, minutes=30))
DEAL = "11111111-2222-3333-4444-555555555555"


class Fake(OrdersFake):
    """Plus migration 295's trigger: deals.refunded_paise = sum of refunds not failed."""

    def table(self, name):
        q = super().table(name)
        if name == "deal_refunds":
            run = q.execute

            def execute():
                res = run()
                for d in self.rows("deals"):
                    d["refunded_paise"] = sum(int(r["amount_paise"]) for r in self.rows("deal_refunds")
                                              if r["deal_id"] == d["id"] and r.get("status") != "failed")
                return res
            q.execute = execute
        return q


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    db = Fake()
    db.add("catalog_items", id="saree", tenant_id=T, name="Cotton saree", item_type="product", price_paise=62000,
           gst_rate=5, stock_quantity=200, status="ready")
    db.add("leads", id="L1", tenant_id=T, name="Suresh K", phone="+919840277889", deleted_at=None)
    return db


def _quote(db, **extra):
    row = {"id": DEAL, "tenant_id": T, "deal_number": 52, "stage": "quoted", "source": "manual", "channel": "online",
           "total_paise": 11400000, "paid_paise": 0, "refunded_paise": 0, "lead_id": "L1", "advance_paise": 3420000,
           "ready_in_days": 10, "quote_sent_at": datetime.now(timezone.utc).isoformat(),
           "quote_valid_until": (datetime.now(IST).date() + timedelta(days=1)).isoformat(), "bill_token": "t" * 22,
           "created_at": datetime.now(timezone.utc).isoformat()}
    row.update(extra)
    db.rows("deals").append(row)
    return row


# ── advance rule ────────────────────────────────────────────────────────────────

def test_advance_rule_percent_fixed_threshold_and_none():
    assert quotes.advance_for(11400000, {"kind": "percent", "value": 30}) == 3420000
    assert quotes.advance_for(240000, {"kind": "fixed", "value": 1000}) == 100000
    assert quotes.advance_for(50000, {"kind": "fixed", "value": 1000}) == 50000  # never more than the total
    assert quotes.advance_for(400000, {"kind": "percent", "value": 30, "min_total_paise": 500000}) == 0
    assert quotes.advance_for(400000, {"kind": "none", "value": 0}) == 0


# ── make and send ───────────────────────────────────────────────────────────────

def test_a_quote_is_saved_with_the_shop_rule_and_sent_with_accept_buttons(db):
    with patch.object(quotes, "advance_rule", return_value={"kind": "percent", "value": 30, "min_total_paise": 0}), \
         patch.object(orders, "notify", AsyncMock(return_value={"sent": True})) as sent:
        out = run(quotes.create_quote(db, T, {"lead_id": "L1", "items": [{"catalog_item_id": "saree", "qty": 100}],
                                              "discount_paise": 200000, "ready_in_days": 10}))
    deal = db.rows("deals")[0]
    assert (deal["stage"], deal["total_paise"], deal["advance_paise"]) == ("quoted", 6000000, 1800000)
    assert deal["quote_sent_at"] and deal["bill_token"]
    assert out["order"]["payment"] == "quote"
    kind = sent.await_args.args[3]
    buttons = sent.await_args.kwargs["buttons"]
    assert kind == "quote" and [b["title"] for b in buttons] == ["Accept quote", "Ask a question"]
    assert buttons[0]["id"] == f"quote_accept:{deal['id']}"


def test_a_past_valid_date_is_refused(db):
    with pytest.raises(orders.OrderError):
        run(quotes.create_quote(db, T, {"lead_id": "L1", "items": [{"catalog_item_id": "saree"}], "valid_until": "2020-01-01"}))


# ── accept ──────────────────────────────────────────────────────────────────────

def test_accept_makes_the_order_sends_the_advance_link_and_rings_the_owner(db):
    _quote(db)
    db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
    with patch("app.services.deals.send_payment_link", AsyncMock(return_value={"payment_link": "https://rzp.io/l/q"})) as link, \
         patch.object(orders, "notify", AsyncMock(return_value={"sent": True})) as sent, \
         patch("app.services.notify.notify_user") as bell:
        out = run(quotes.accept_quote(db, T, DEAL, via="whatsapp"))
        again = run(quotes.accept_quote(db, T, DEAL, via="page"))
    deal = db.rows("deals")[0]
    assert out["status"] == "accepted" and out["payment_link"] == "https://rzp.io/l/q"
    assert (deal["stage"], deal["delivery_status"]) == ("awaiting_payment", "working") and deal["ready_by"]
    assert link.await_args.kwargs["amount_paise"] == 3420000
    assert sent.await_args.args[3] == "confirmed"
    assert "accepted quote D-0052" in bell.call_args.args[3]
    assert again["status"] == "already" and link.await_count == 1


def test_an_expired_quote_is_not_accepted_and_someone_elses_button_does_nothing(db):
    _quote(db, quote_valid_until="2020-01-01")
    with patch.object(quotes, "_say", AsyncMock()) as said:
        assert run(quotes.accept_from_chat(db, T, "L1", DEAL))["status"] == "expired"
        assert "expired" in said.await_args.args[3]
        assert run(quotes.accept_from_chat(db, T, "someone-else", DEAL))["status"] == "closed"
    assert db.rows("deals")[0]["stage"] == "quoted"


def test_button_ids_only_carry_a_deal_id():
    assert quotes.deal_from_button(f"quote_accept:{DEAL}") == DEAL
    assert quotes.deal_from_button(f"quote_ask:{DEAL}") is None
    assert quotes.deal_from_button("quote_accept:x; drop") is None
    assert quotes.deal_from_button("") is None


def test_a_quote_gets_one_reminder_after_2_days_and_expires_after_its_date(db):
    now = datetime.now(timezone.utc)
    _quote(db, quote_sent_at=(now - timedelta(days=3)).isoformat())
    _quote(db, id="old", quote_valid_until="2020-01-01")
    with patch.object(orders, "notify", AsyncMock(return_value={"sent": True})) as sent:
        first = run(quotes.sweep_quotes(db, now))
        second = run(quotes.sweep_quotes(db, now))
    assert first == {"reminded": 1, "expired": 1} and second["reminded"] == 0
    assert sent.await_args.args[3] == "quote_reminder"
    old = next(d for d in db.rows("deals") if d["id"] == "old")
    assert (old["stage"], old["lost_reason"]) == ("lost", "Quote expired")


# ── refunds ─────────────────────────────────────────────────────────────────────

def _paid(db, **extra):
    row = {"id": "o1", "tenant_id": T, "deal_number": 48, "stage": "won", "source": "walk_in", "channel": "store",
           "total_paise": 420000, "paid_paise": 0, "refunded_paise": 0, "lead_id": "L1", "bill_type": "gst",
           "invoice_number": "2026-27/0048", "created_at": datetime.now(timezone.utc).isoformat()}
    row.update(extra)
    db.rows("deals").append(row)
    db.add("deal_items", tenant_id=T, deal_id="o1", catalog_item_id="saree", variant_id=None, name="Cotton saree", qty=1)
    return row


def _pay(db, amount, method="cash", rzp=None, deal="o1"):
    db.table("deal_payments").insert({"tenant_id": T, "deal_id": deal, "amount_paise": amount, "method": method,
                                      "razorpay_payment_id": rzp, "paid_at": datetime.now(timezone.utc).isoformat()}).execute()


def _refund(db, **kw):
    with patch.object(orders, "notify", AsyncMock(return_value={"sent": True})) as sent:
        out = run(refunds.refund(db, T, "o1", **kw))
    return out, sent


def test_cancel_needs_nothing_paid(db):
    _paid(db, stage="awaiting_payment")
    out, _ = _refund(db, mode="cancel", amount_paise=None, method=None, reason="Customer changed mind")
    assert out["cancelled"] and db.rows("deals")[0]["stage"] == "lost"
    db.rows("deals").clear()
    _paid(db, stage="awaiting_payment")
    _pay(db, 100000)
    with pytest.raises(orders.OrderError, match="Full refund"):
        _refund(db, mode="cancel", amount_paise=None, method=None, reason="x")


def test_full_cash_refund_closes_the_order_puts_stock_back_and_makes_a_credit_note(db):
    _paid(db)
    _pay(db, 420000)
    out, sent = _refund(db, mode="full", amount_paise=None, method="cash", reason="Wrong size / colour")
    deal = db.rows("deals")[0]
    assert (deal["stage"], deal["refunded_paise"]) == ("lost", 420000)
    assert deal["lost_reason"] == "Refunded · Wrong size / colour"
    assert out["credit_note"].startswith("CN/") and out["credit_note"].endswith("/0001")
    assert db.rows("catalog_items")[0]["stock_quantity"] == 201  # the piece came back
    assert db.rows("deal_refunds")[0]["restocked"] is True
    assert sent.await_args.args[3] == "refund" and sent.await_args.kwargs["extra"]["_refund"]["method"] == "cash"
    assert orders.order_row(deal)["payment_note"] == "Refunded ₹4,200"


def test_part_refund_keeps_the_order_and_never_goes_over_what_was_paid(db):
    _paid(db, stage="awaiting_payment")
    _pay(db, 300000, method="upi")
    out, _ = _refund(db, mode="part", amount_paise=50000, method="upi", reason="Damaged")
    deal = db.rows("deals")[0]
    assert (deal["stage"], deal["refunded_paise"], out["cancelled"]) == ("awaiting_payment", 50000, False)
    with pytest.raises(orders.OrderError, match="Only ₹2,500"):
        _refund(db, mode="part", amount_paise=260000, method="cash", reason="Other")


def test_razorpay_refund_goes_against_the_link_payments_and_not_beyond(db):
    _paid(db)
    _pay(db, 300000, method="razorpay", rzp="pay_A")
    _pay(db, 120000, method="cash")
    with patch("app.services.payment_razorpay.create_refund", AsyncMock(return_value={"id": "rfnd_1", "status": "processed"})) as rz:
        with pytest.raises(orders.OrderError, match="Only ₹3,000 was paid by link"):
            _refund(db, mode="full", amount_paise=None, method="razorpay", reason="Late delivery")
        out, _ = _refund(db, mode="part", amount_paise=200000, method="razorpay", reason="Late delivery")
    assert rz.await_args.args[:2] == ("pay_A", 200000)
    row = db.rows("deal_refunds")[0]
    assert (row["razorpay_refund_id"], row["status"], row["method"]) == ("rfnd_1", "done", "razorpay")
    assert out["cancelled"] is False


def test_only_the_owner_or_refund_permission_can_refund():
    assert refunds.can_refund({"role": "owner"})
    assert refunds.can_refund({"role": "caller", "permissions": ["deals.refund"]})
    assert not refunds.can_refund({"role": "caller", "permissions": ["deals.manage"]})


def test_money_in_takes_refunds_off(db):
    _paid(db)
    _pay(db, 420000)
    _refund(db, mode="part", amount_paise=20000, method="cash", reason="Damaged")
    db.rows("deal_refunds")[0]["created_at"] = datetime.now(timezone.utc).isoformat()  # the fake's clock is fixed
    cards = orders.list_orders(db, T)["cards"]
    assert (cards["money_in"]["paise"], cards["money_in"]["refunded_paise"]) == (400000, 20000)


# ── the WhatsApp Accept button reaches accept_from_chat, not the AI ─────────────

def test_the_accept_button_confirms_the_quote_instead_of_an_ai_reply():
    from unittest.mock import MagicMock
    from app.routes import webhook
    reply = AsyncMock()
    accepted = AsyncMock(return_value={"status": "accepted"})
    with patch("app.db.supabase.get_supabase", return_value=MagicMock()), \
         patch("app.services.conversation_state.get_or_create_state", return_value={"message_count": 0}), \
         patch("app.services.automation_guards.ai_replies_allowed_for_lead", return_value=False), \
         patch("app.services.ai_reply.record_tamil_lock_request"), \
         patch("app.services.order_quotes.accept_from_chat", accepted), \
         patch("app.services.purchases.supplier_by_phone", return_value=None), \
         patch("app.services.ai_reply.generate_reply", reply):
        run(webhook._process_inbound_message_background(
            lead_id="L1", tenant_id=T, phone="+919840277889", body="Accept quote", msg_type="button",
            interactive_id=f"quote_accept:{DEAL}"))
        assert accepted.await_args.args[1:] == (T, "L1", DEAL)  # runs even with auto-reply off
        reply.assert_not_awaited()
        run(webhook._process_inbound_message_background(
            lead_id="L1", tenant_id=T, phone="+919840277889", body="Ask a question", msg_type="button",
            interactive_id=f"quote_ask:{DEAL}"))
    assert accepted.await_count == 1 and reply.await_count == 1  # Ask goes to the AI as a normal message
