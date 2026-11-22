"""Bookings ↔ Orders (services/booking_orders.py): advances and "Came" go through the normal order code."""
import asyncio
from unittest.mock import MagicMock

import pytest

from app.services import booking_orders as bo
from app.services import deals


def _db(rows=None):
    db = MagicMock()
    q = db.table.return_value
    for name in ("select", "update", "eq", "limit"):
        getattr(q, name).return_value = q
    q.execute.return_value = MagicMock(data=rows or [])
    return db


BOOKING = {"id": "b1", "number": 12, "lead_id": "L1", "source": "link", "advance_paise": 0, "deal_id": None}
SERVICE = {"catalog_item_id": "C1", "price_paise": 50000, "advance_paise": 0}


def test_service_own_advance_wins():
    assert bo.advance_due("t", {**SERVICE, "advance_paise": 20000}, no_shows=0, no_show_limit=2) == 20000


def test_own_advance_never_more_than_price():
    assert bo.advance_due("t", {**SERVICE, "advance_paise": 90000}, no_shows=0, no_show_limit=2) == 50000


def test_no_advance_below_no_show_limit():
    assert bo.advance_due("t", SERVICE, no_shows=1, no_show_limit=2) == 0


def test_after_no_shows_uses_business_rule(monkeypatch):
    from app.services import order_quotes
    monkeypatch.setattr(order_quotes, "advance_rule", lambda t: {"kind": "percent", "value": 30, "min_total_paise": 0})
    assert bo.advance_due("t", SERVICE, no_shows=2, no_show_limit=2) == 15000


def test_after_no_shows_rule_none_means_half(monkeypatch):
    from app.services import order_quotes
    monkeypatch.setattr(order_quotes, "advance_rule", lambda t: {"kind": "none", "value": 0, "min_total_paise": 0})
    assert bo.advance_due("t", SERVICE, no_shows=3, no_show_limit=2) == 25000


def test_free_service_never_asks_advance():
    assert bo.advance_due("t", {**SERVICE, "price_paise": 0}, no_shows=5, no_show_limit=2) == 0


def test_advance_order_uses_catalogue_line_and_advance_link(monkeypatch):
    calls = {}

    async def fake_create(tenant_id, lead_id, lines, source, stage="quoted", **kw):
        calls["create"] = (tenant_id, lead_id, lines, source, stage, kw.get("notes"))
        return {"id": "D1", "total_paise": 50000}

    async def fake_link(tenant_id, deal_id, *, send_whatsapp_message=True, amount_paise=None, db=None):
        calls["link"] = (deal_id, send_whatsapp_message, amount_paise)
        return {"payment_link": "https://rzp.io/x", "message_sent": False}

    monkeypatch.setattr(deals, "create_deal", fake_create)
    monkeypatch.setattr(deals, "send_payment_link", fake_link)
    db = _db()
    out = asyncio.run(bo.create_advance_order("t", BOOKING, SERVICE, 20000, db=db))
    assert out == {"deal_id": "D1", "payment_url": "https://rzp.io/x", "message_sent": False}
    assert calls["create"] == ("t", "L1", [{"catalog_item_id": "C1", "qty": 1}], "form", "quoted", "Booking BK-0012")
    assert calls["link"] == ("D1", False, 20000)
    db.table.return_value.update.assert_called_with({"deal_id": "D1", "advance_paise": 20000})


def test_advance_order_needs_customer_and_catalogue_item():
    with pytest.raises(bo.BookingOrderError):
        asyncio.run(bo.create_advance_order("t", {**BOOKING, "lead_id": None}, SERVICE, 100, db=_db()))
    with pytest.raises(bo.BookingOrderError):
        asyncio.run(bo.create_advance_order("t", BOOKING, {**SERVICE, "catalog_item_id": None}, 100, db=_db()))
    with pytest.raises(bo.BookingOrderError):
        asyncio.run(bo.create_advance_order("t", BOOKING, SERVICE, 0, db=_db()))


def test_deal_error_becomes_plain_booking_error(monkeypatch):
    async def boom(*a, **k):
        raise deals.DealError("Product not found")

    monkeypatch.setattr(deals, "create_deal", boom)
    with pytest.raises(bo.BookingOrderError, match="Product not found"):
        asyncio.run(bo.create_advance_order("t", BOOKING, SERVICE, 100, db=_db()))


def test_advance_paid_reads_the_order():
    b = {**BOOKING, "deal_id": "D1", "advance_paise": 20000}
    assert bo.advance_paid("t", b, db=_db([{"paid_paise": 20000, "refunded_paise": 0, "stage": "awaiting_payment"}]))
    assert not bo.advance_paid("t", b, db=_db([{"paid_paise": 20000, "refunded_paise": 5000, "stage": "awaiting_payment"}]))
    assert not bo.advance_paid("t", b, db=_db([]))
    assert bo.advance_paid("t", {**BOOKING, "advance_paise": 0}, db=_db())


def test_came_reuses_the_booking_order(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("must not make a second order")

    monkeypatch.setattr(deals, "create_deal", never)
    assert asyncio.run(bo.order_for_came("t", {**BOOKING, "deal_id": "D9"}, SERVICE, db=_db())) == "D9"


def test_came_makes_an_order_when_none(monkeypatch):
    async def fake_create(tenant_id, lead_id, lines, source, stage="quoted", **kw):
        return {"id": "D2", "total_paise": 50000}

    monkeypatch.setattr(deals, "create_deal", fake_create)
    db = _db()
    assert asyncio.run(bo.order_for_came("t", {**BOOKING, "source": "walk_in"}, SERVICE, db=db)) == "D2"
    db.table.return_value.update.assert_called_with({"deal_id": "D2"})


def test_release_closes_only_open_orders_and_never_raises(monkeypatch):
    seen = {}

    def fake_lost(tenant_id, deal_id, reason, *, only_from=None, db=None, **kw):
        seen["args"] = (deal_id, only_from)
        raise RuntimeError("db down")

    monkeypatch.setattr(deals, "mark_lost", fake_lost)
    bo.release_unpaid_order("t", {**BOOKING, "deal_id": "D1"}, db=_db())
    assert seen["args"] == ("D1", ("quoted", "awaiting_payment"))
    bo.release_unpaid_order("t", BOOKING, db=_db())  # no order: nothing to do


def test_advance_paid_many_matches_the_single_rule_with_one_read():
    db = MagicMock()
    q = db.table.return_value
    for name in ("select", "eq", "in_"):
        getattr(q, name).return_value = q
    q.execute.return_value = MagicMock(data=[
        {"id": "D1", "paid_paise": 20000, "refunded_paise": 0, "stage": "awaiting_payment"},
        {"id": "D2", "paid_paise": 20000, "refunded_paise": 5000, "stage": "awaiting_payment"},
        {"id": "D3", "paid_paise": 0, "refunded_paise": 0, "stage": "won"},
    ])
    rows = [
        {"id": "b1", "deal_id": "D1", "advance_paise": 20000},
        {"id": "b2", "deal_id": "D2", "advance_paise": 20000},
        {"id": "b3", "deal_id": "D3", "advance_paise": 100},
        {"id": "b4", "deal_id": None, "advance_paise": 0},
        {"id": "b5", "deal_id": "GONE", "advance_paise": 100},
    ]
    assert bo.advance_paid_many("t", rows, db=db) == {"b1": True, "b2": False, "b3": True, "b4": True, "b5": False}
    assert q.execute.call_count == 1
