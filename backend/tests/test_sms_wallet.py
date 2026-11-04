"""SMS balance history, the low-balance alert, campaign cost and the send gate."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routes import sms
from app.services import bulk9_client, sms_wallet
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
EARLIER = (NOW - timedelta(minutes=15)).isoformat()


def _db(prev=None, low_alerted_at=None):
    db = FakeSupabase()
    db.add("app_settings", key="bulk9_api_key", value="k", tenant_id=T)
    db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
    if prev is not None:
        db.add("sms_wallet", tenant_id=T, sms_count=prev, checked_at=EARLIER, low_alerted_at=low_alerted_at)
    return db


def _sent(db, parts, *, at=None, request_id="req", status="submitted"):
    db.add("sms_messages", tenant_id=T, status=status, sms_count=parts, request_id=request_id,
           submitted_at=at or (NOW - timedelta(minutes=5)).isoformat())


async def _sync(db, balance):
    notes = []
    with patch.object(bulk9_client, "wallet", AsyncMock(return_value={"sms_count": balance})), \
         patch("app.services.notify.notify_user", lambda *a, **k: notes.append(a)):
        out = await sms_wallet.sync_tenant(db, T, "k", now=NOW)
    return out, notes


@pytest.mark.asyncio
async def test_first_check_stores_balance_without_an_event():
    db = _db()
    out, _ = await _sync(db, 2000)
    assert out == "first" and db.rows("sms_wallet")[0]["sms_count"] == 2000
    assert db.rows("sms_wallet_events") == []


@pytest.mark.asyncio
async def test_rise_beyond_own_sends_is_a_topup():
    db = _db(prev=500)
    _sent(db, 40)
    out, _ = await _sync(db, 1460)  # 1460 - 500 + 40
    assert out == "topup"
    ev = db.rows("sms_wallet_events")[0]
    assert ev["kind"] == "topup" and ev["sms_delta"] == 1000 and ev["balance_after"] == 1460


@pytest.mark.asyncio
async def test_drop_bigger_than_own_sends_is_outside_usage():
    db = _db(prev=1000)
    _sent(db, 40)
    out, _ = await _sync(db, 900)  # 900 - 1000 + 40 = -60
    assert out == "outside_usage" and db.rows("sms_wallet_events")[0]["sms_delta"] == -60


@pytest.mark.asyncio
async def test_own_sends_explain_the_drop_and_dry_runs_cost_nothing():
    db = _db(prev=1000)
    _sent(db, 40)
    _sent(db, 7, request_id="dry-run-x")
    _sent(db, 9, at=EARLIER)  # counted by the previous tick
    out, _ = await _sync(db, 960)
    assert out == "same" and db.rows("sms_wallet_events") == []


@pytest.mark.asyncio
async def test_mid_send_tenant_is_skipped():
    db = _db(prev=1000)
    _sent(db, 1, status="sending")
    out, _ = await _sync(db, 10)
    assert out == "busy" and db.rows("sms_wallet")[0]["sms_count"] == 1000


@pytest.mark.asyncio
async def test_low_alert_fires_once_and_rearms_after_topup():
    db = _db(prev=600)
    _, notes = await _sync(db, 450)
    assert len(notes) == 1 and "450 SMS left" in notes[0][4]
    _, notes = await _sync(db, 400)
    assert notes == []  # still low, already told
    _, notes = await _sync(db, 5000)
    assert notes == [] and db.rows("sms_wallet")[0]["low_alerted_at"] is None
    _, notes = await _sync(db, 100)
    assert len(notes) == 1


@pytest.mark.asyncio
async def test_provider_error_leaves_state_alone():
    db = _db(prev=700)
    with patch.object(bulk9_client, "wallet", AsyncMock(side_effect=bulk9_client.Bulk9Timeout("x"))):
        assert await sms_wallet.sync_tenant(db, T, "k", now=NOW) == "error"
    assert db.rows("sms_wallet")[0]["sms_count"] == 700


def test_history_merges_topups_and_campaign_spend_newest_first():
    db = _db()
    db.add("sms_wallet_events", tenant_id=T, kind="topup", sms_delta=1000, balance_after=1460,
           created_at="2026-11-01T10:00:00+00:00")
    camp = db.add("sms_campaigns", tenant_id=T, name="Diwali offer", template_text="Hi", sender_id="ANRILT",
                  template_type="promotional", status="completed", created_at="2026-11-02T10:00:00+00:00")
    db.add("sms_messages", tenant_id=T, campaign_id=camp["id"], status="delivered", sms_count=2, amount_debited="0.40")
    db.add("sms_messages", tenant_id=T, campaign_id=camp["id"], status="delivered", sms_count=1, amount_debited="0.2")
    items = sms_wallet.history(db, T)["items"]
    assert [i["kind"] for i in items] == ["campaign", "topup"]
    assert items[0]["sms"] == -3 and items[0]["amount"] == 0.6 and items[0]["label"] == "Diwali offer"
    assert items[1]["sms"] == 1000


# ---------------------------------------------------------------- the send gate

@pytest.mark.asyncio
@pytest.mark.parametrize("balance,needed,expect", [
    (5, 10, "needs 10 SMS and you have 5"),
    (10, 10, None),
])
async def test_send_gate(balance, needed, expect):
    """Only balance blocks a send; PE-TM binding is no longer an Anril gate."""
    with patch.object(bulk9_client, "wallet", AsyncMock(return_value={"sms_count": balance})):
        if expect is None:
            await sms._require_send_ready("k", needed)
        else:
            with pytest.raises(HTTPException) as e:
                await sms._require_send_ready("k", needed)
            assert e.value.status_code == 409 and expect in e.value.detail


@pytest.mark.asyncio
async def test_otp_send_passes_extra_values():
    send = AsyncMock(return_value={"request_id": "o1"})
    with patch.object(bulk9_client, "otp_send", send), patch.object(sms, "get_supabase", FakeSupabase):
        await sms.otp_send(sms.OtpSendBody(mobile="9876543210", otp_id="7", otp_length=4, otp_expiry=5,
                                           variables_values=" Astro|{otp} "), {"tenant_id": T, "api_key": "k"})
    assert send.call_args.kwargs["variables_values"] == "Astro|{otp}"
    assert send.call_args.kwargs["otp_length"] == 4 and send.call_args.kwargs["otp_expiry"] == 5
