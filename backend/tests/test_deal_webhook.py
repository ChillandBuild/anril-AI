"""Razorpay events for a deal's payment link (notes.deal_id): paid -> won plus
a receipt, expired -> lost, a retried paid delivery is a no-op, and a failed
attempt is ignored because the customer can still pay the same link."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routes.intake import _handle_deal_payment_event

PAID = {"payload": {"payment": {"entity": {"id": "pay_1"}}}}


def _leads_db():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        SimpleNamespace(data={"phone": "+919800000001"})
    )
    return db


@pytest.mark.asyncio
async def test_paid_marks_won_and_sends_receipt():
    send = AsyncMock()
    with patch("app.services.deals.mark_won", return_value={"deal": {"lead_id": "l1"}, "stock_warnings": []}) as won, \
         patch("app.routes.intake.get_supabase", return_value=_leads_db()), \
         patch("app.routes.intake.send_whatsapp", send):
        out = await _handle_deal_payment_event(PAID, "payment_link.paid", "d1", "t1")
    assert out == {"status": "ok"}
    won.assert_called_once_with("t1", "d1", payment_method="razorpay", razorpay_payment_id="pay_1")
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_retried_paid_delivery_is_ignored_without_second_receipt():
    send = AsyncMock()
    with patch("app.services.deals.mark_won", return_value=None), \
         patch("app.routes.intake.report_extra_deal_payment"), \
         patch("app.routes.intake.get_supabase"), \
         patch("app.routes.intake.send_whatsapp", send):
        out = await _handle_deal_payment_event(PAID, "payment_link.paid", "d1", "t1")
    assert out["status"] == "ignored"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_link_clears_the_link_and_keeps_the_deal_open():
    with patch("app.routes.intake._current_plink_id", return_value=None), \
         patch("app.services.deals.expire_deal_link", return_value=True) as expire, \
         patch("app.services.deals.mark_lost") as lost:
        out = await _handle_deal_payment_event({}, "payment_link.expired", "d1", "t1")
    assert out["status"] == "ok"
    expire.assert_called_once_with("t1", "d1")
    lost.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_link_still_marks_the_deal_lost_with_its_own_reason():
    with patch("app.routes.intake._current_plink_id", return_value=None), \
         patch("app.services.deals.mark_lost", return_value={"deal": {}, "stock_warnings": []}) as lost:
        out = await _handle_deal_payment_event({}, "payment_link.cancelled", "d1", "t1")
    assert out["status"] == "ok"
    lost.assert_called_once_with("t1", "d1", "Payment link cancelled", only_from=("quoted", "awaiting_payment"))


@pytest.mark.asyncio
async def test_failed_attempt_is_ignored():
    with patch("app.services.deals.mark_lost") as lost, patch("app.services.deals.mark_won") as won:
        out = await _handle_deal_payment_event({}, "payment.failed", "d1", "t1")
    assert out["status"] == "ignored"
    lost.assert_not_called()
    won.assert_not_called()


@pytest.mark.asyncio
async def test_a_fee_reminder_link_expiring_leaves_the_order_link_alone():
    """v9.2 #217: a course fee reminder's own link expires after a day; the order's link must not be cleared."""
    payload = {"payload": {"payment_link": {"entity": {"id": "plink_fee", "notes": {"deal_id": "d1", "fee_plan_id": "P1"}}}}}
    with patch("app.services.deals.expire_deal_link") as clear, patch("app.services.deals.mark_lost") as lost:
        out = await _handle_deal_payment_event(payload, "payment_link.expired", "d1", "t1")
        out2 = await _handle_deal_payment_event(payload, "payment_link.cancelled", "d1", "t1")
    assert out["status"] == out2["status"] == "ignored"
    clear.assert_not_called()
    lost.assert_not_called()
