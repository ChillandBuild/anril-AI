"""SMS recharge money path: Anril's Razorpay webhook signature, credit exactly once per payment,
an amount mismatch never credits, and a Bulk9 failure leaves a retryable credit_failed row."""
import hashlib
import hmac
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services import sms_billing
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"


def _settings(key, tenant_id=None):
    return {"bulk9_username": "astro_tamil", "sms_price_per_sms": "0.25", "sms_buy_rate": "0.14"}.get(key)


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setenv("SMS_RAZORPAY_WEBHOOK_SECRET", "whsec_sms")
    with patch.object(sms_billing, "get_setting", side_effect=_settings):
        yield


def _payment(db, **kw):
    return db.add("sms_payments", **{"tenant_id": T, "amount_paise": 50000, "sms_count": 2000,
                                     "price_per_sms": "0.25", "status": "created",
                                     "razorpay_link_id": "plink_1", "created_by": None, **kw})


def _paid_event(row, amount=50000, link_id="plink_1"):
    return {"event": "payment_link.paid", "payload": {
        "payment_link": {"entity": {"id": link_id, "notes": {"sms_payment_id": row["id"]}, "amount_paid": amount}},
        "payment": {"entity": {"id": "pay_1", "amount": amount}}}}


def test_verify_webhook():
    body = b'{"event":"payment_link.paid"}'
    good = hmac.new(b"whsec_sms", body, hashlib.sha256).hexdigest()
    assert sms_billing.verify_webhook(body, good)
    assert not sms_billing.verify_webhook(body, "0" * 64)
    assert not sms_billing.verify_webhook(body, "")


def test_verify_webhook_without_secret_rejects(monkeypatch):
    monkeypatch.delenv("SMS_RAZORPAY_WEBHOOK_SECRET")
    assert not sms_billing.verify_webhook(b"{}", "abc")


def test_packs_use_client_price():
    assert sms_billing.packs(T)[0] == {"amount_rupees": 500, "sms_count": 2000, "price_per_sms": 0.25}


@pytest.mark.asyncio
async def test_paid_credits_once_even_if_webhook_retries():
    db = FakeSupabase()
    row = _payment(db)
    add = AsyncMock(return_value={})
    with patch.object(sms_billing.bulk9_reseller, "add_sms_credit", add):
        assert await sms_billing.handle_razorpay_event(db, _paid_event(row)) == {"status": "ok"}
        assert await sms_billing.handle_razorpay_event(db, _paid_event(row)) == {"status": "duplicate"}
    add.assert_awaited_once_with("astro_tamil", sms_count=2000, price_per_sms=Decimal("0.25"))
    p = db.rows("sms_payments")[0]
    assert p["status"] == "credited" and p["razorpay_payment_id"] == "pay_1"
    [ledger] = db.rows("sms_ledger")
    assert ledger["kind"] == "recharge" and ledger["sms_count"] == 2000 and ledger["amount"] == "500.00"
    assert ledger["buy_rate"] == "0.14" and ledger["reference"] == "pay_1"


@pytest.mark.asyncio
async def test_amount_mismatch_never_credits():
    db = FakeSupabase()
    row = _payment(db)
    add = AsyncMock()
    with patch.object(sms_billing.bulk9_reseller, "add_sms_credit", add):
        out = await sms_billing.handle_razorpay_event(db, _paid_event(row, amount=100))
    assert out == {"status": "amount_mismatch"}
    add.assert_not_called()
    assert db.rows("sms_payments")[0]["status"] == "amount_mismatch"  # not retryable as credit_failed


@pytest.mark.asyncio
async def test_link_id_mismatch_is_ignored():
    db = FakeSupabase()
    row = _payment(db)
    add = AsyncMock()
    with patch.object(sms_billing.bulk9_reseller, "add_sms_credit", add):
        out = await sms_billing.handle_razorpay_event(db, _paid_event(row, link_id="plink_other"))
    assert out == {"status": "ignored"}
    add.assert_not_called()
    assert db.rows("sms_payments")[0]["status"] == "created"


@pytest.mark.asyncio
@pytest.mark.parametrize("exc,phrase", [(Bulk9Timeout("slow"), "Check the client's balance"),
                                        (Bulk9Error("Insufficient reseller stock"), "Insufficient")])
async def test_bulk9_failure_leaves_credit_failed(exc, phrase):
    db = FakeSupabase()
    row = _payment(db)
    with patch.object(sms_billing.bulk9_reseller, "add_sms_credit", AsyncMock(side_effect=exc)):
        assert await sms_billing.handle_razorpay_event(db, _paid_event(row)) == {"status": "ok"}
    p = db.rows("sms_payments")[0]
    assert p["status"] == "credit_failed" and phrase in p["error"]
    assert db.rows("sms_ledger") == []


@pytest.mark.asyncio
async def test_expired_only_moves_unpaid_rows():
    db = FakeSupabase()
    a = _payment(db)
    b = _payment(db, status="credited", razorpay_link_id="plink_2")
    for row, link in ((a, "plink_1"), (b, "plink_2")):
        await sms_billing.handle_razorpay_event(db, {"event": "payment_link.expired", "payload": {
            "payment_link": {"entity": {"id": link, "notes": {"sms_payment_id": row["id"]}}}}})
    assert [r["status"] for r in db.rows("sms_payments")] == ["expired", "credited"]


@pytest.mark.asyncio
async def test_recharge_rejects_amounts_outside_the_packs():
    with pytest.raises(ValueError):
        await sms_billing.create_recharge(FakeSupabase(), T, amount_rupees=750, user_id=None)


@pytest.mark.asyncio
async def test_bonus_credit_has_zero_amount():
    db = FakeSupabase()
    with patch.object(sms_billing.bulk9_reseller, "add_sms_credit", AsyncMock(return_value={})):
        await sms_billing.manual_credit(db, T, kind="bonus", sms_count=100, price=None, expiry_date=None,
                                        note="Diwali", actor="prem")
    [row] = db.rows("sms_ledger")
    assert row["kind"] == "bonus" and row["amount"] == "0" and row["sms_count"] == 100


@pytest.mark.asyncio
async def test_debit_writes_negative_ledger_row():
    db = FakeSupabase()
    with patch.object(sms_billing.bulk9_reseller, "debit_sms_credit", AsyncMock(return_value={})):
        await sms_billing.manual_debit(db, T, sms_count=50, note="refund reversal", actor="prem")
    assert db.rows("sms_ledger")[0]["sms_count"] == -50


@pytest.mark.asyncio
async def test_recharge_refused_when_price_below_buy_rate(monkeypatch):
    monkeypatch.setenv("SMS_RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setenv("SMS_RAZORPAY_KEY_SECRET", "s")
    low = lambda key, tenant_id=None: {**{"bulk9_username": "u", "sms_buy_rate": "0.14"},
                                       "sms_price_per_sms": "0.10"}.get(key)
    db = FakeSupabase()
    with patch.object(sms_billing, "get_setting", side_effect=low):
        with pytest.raises(sms_billing.BillingNotConfigured):
            await sms_billing.create_recharge(db, T, amount_rupees=500, user_id=None)
    assert db.rows("sms_payments") == []


@pytest.mark.asyncio
async def test_recharge_refused_with_three_open_links(monkeypatch):
    monkeypatch.setenv("SMS_RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setenv("SMS_RAZORPAY_KEY_SECRET", "s")
    db = FakeSupabase()
    from datetime import datetime, timezone
    for i in range(3):
        _payment(db, razorpay_link_id=f"plink_{i}", created_at=datetime.now(timezone.utc).isoformat())
    with pytest.raises(ValueError, match="unpaid recharge links"):
        await sms_billing.create_recharge(db, T, amount_rupees=500, user_id=None)
    assert len(db.rows("sms_payments")) == 3
