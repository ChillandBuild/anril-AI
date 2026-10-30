"""The SMS send job (process_due_sms): each queued row is sent at most once. A timeout becomes
unknown and is never re-sent, opted-out leads and cancelled campaigns are skipped at send time,
and a row stuck in `sending` is handed to the reconcile job instead of being sent again."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import sms_campaigns
from app.services.bulk9_client import Bulk9Error, Bulk9Timeout
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)


def _settings(key, tenant_id=None):
    return {"bulk9_api_key": "k", "sms_buy_rate": "0.14"}.get(key)


@pytest.fixture(autouse=True)
def _cfg():
    with patch.object(sms_campaigns, "get_setting", side_effect=_settings):
        yield


def _db(*, opted_out=False, campaign_status="scheduled", features=("sms",)):
    db = FakeSupabase()
    db.add("tenants", id=T, enabled_features=list(features))
    lead = db.add("leads", tenant_id=T, opted_out=opted_out, deleted_at=None)
    camp = db.add("sms_campaigns", tenant_id=T, status=campaign_status, sender_id="ANRILT",
                  message_id="12345", completed_at=None)
    db.add("sms_messages", tenant_id=T, campaign_id=camp["id"], lead_id=lead["id"], phone="+919876543210",
           variables=["Prem"], status="queued", send_at=(NOW - timedelta(minutes=1)).isoformat(), claimed_at=None)
    return db


def _row(db):
    return db.rows("sms_messages")[0]


@pytest.mark.asyncio
async def test_sends_once_and_records_submission():
    db = _db()
    send = AsyncMock(return_value={"return": True, "request_id": "req-1", "sms_count": 1, "amount_debited": 0.25})
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        assert await sms_campaigns.process_due_sms(db, now=NOW) == {"claimed": 1}
        assert await sms_campaigns.process_due_sms(db, now=NOW + timedelta(minutes=1)) == {"claimed": 0}
    send.assert_awaited_once()
    kw = send.await_args.kwargs
    assert kw["numbers"] == ["+919876543210"] and kw["variables"] == ["Prem"] and kw["udf1"] == _row(db)["id"]
    r = _row(db)
    assert r["status"] == "submitted" and r["request_id"] == "req-1"
    assert r["sms_count"] == 1 and r["charged_amount"] == 0.25 and r["cost_amount"] == 0.14
    assert db.rows("sms_campaigns")[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_not_yet_due_is_left_alone():
    db = _db()
    _row(db)["send_at"] = (NOW + timedelta(hours=1)).isoformat()
    send = AsyncMock()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        await sms_campaigns.process_due_sms(db, now=NOW)
    send.assert_not_called()
    assert _row(db)["status"] == "queued"


@pytest.mark.asyncio
async def test_timeout_becomes_unknown_and_is_never_resent():
    db = _db()
    send = AsyncMock(side_effect=Bulk9Timeout("slow"))
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        await sms_campaigns.process_due_sms(db, now=NOW)
        await sms_campaigns.process_due_sms(db, now=NOW + timedelta(hours=1))
    send.assert_awaited_once()
    assert _row(db)["status"] == "unknown"


@pytest.mark.asyncio
async def test_bulk9_rejection_is_failed_with_reason():
    db = _db()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", AsyncMock(side_effect=Bulk9Error("Template not approved"))):
        await sms_campaigns.process_due_sms(db, now=NOW)
    assert _row(db)["status"] == "failed" and _row(db)["failure_reason"] == "Template not approved"


@pytest.mark.asyncio
async def test_lead_opted_out_after_scheduling_is_skipped():
    db = _db(opted_out=True)
    send = AsyncMock()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        await sms_campaigns.process_due_sms(db, now=NOW)
    send.assert_not_called()
    assert _row(db)["status"] == "skipped" and "opted out" in _row(db)["failure_reason"]


@pytest.mark.asyncio
async def test_cancelled_campaign_is_not_sent():
    db = _db(campaign_status="cancelled")
    send = AsyncMock()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        await sms_campaigns.process_due_sms(db, now=NOW)
    send.assert_not_called()
    assert _row(db)["status"] == "cancelled"


@pytest.mark.asyncio
async def test_sms_turned_off_skips():
    db = _db(features=())
    send = AsyncMock()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        await sms_campaigns.process_due_sms(db, now=NOW)
    send.assert_not_called()
    assert _row(db)["status"] == "skipped"


@pytest.mark.asyncio
async def test_row_already_claimed_by_another_run_is_not_sent():
    db = _db()
    _row(db).update(status="sending", claimed_at=NOW.isoformat())
    send = AsyncMock()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        assert await sms_campaigns.process_due_sms(db, now=NOW) == {"claimed": 0}
    send.assert_not_called()
    assert _row(db)["status"] == "sending"


@pytest.mark.asyncio
async def test_stuck_sending_row_becomes_unknown_not_resent():
    db = _db()
    _row(db).update(status="sending", claimed_at=(NOW - timedelta(minutes=20)).isoformat())
    send = AsyncMock()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        await sms_campaigns.process_due_sms(db, now=NOW)
    send.assert_not_called()
    assert _row(db)["status"] == "unknown"


@pytest.mark.asyncio
async def test_dry_run_body_gets_a_visibly_fake_request_id():
    db = _db()
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", AsyncMock(return_value={"dry_run": True})):
        await sms_campaigns.process_due_sms(db, now=NOW)
    assert _row(db)["request_id"].startswith("dry-run-")
