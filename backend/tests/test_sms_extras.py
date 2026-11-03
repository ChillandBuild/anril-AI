"""SMS page extras: the ₹ estimate, moving a scheduled campaign, deleting, and OTP history."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routes import sms
from app.services import bulk9_client, sms_campaigns as camp, sms_wallet
from app.services.bulk9_client import Bulk9Error
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
CTX = {"tenant_id": T, "api_key": "k", "user_id": "u1"}


def _campaign(db, status="scheduled", send_at=NOW + timedelta(hours=2), tenant=T, **extra):
    return db.add("sms_campaigns", tenant_id=tenant, name="Diwali", template_text="Hi", sender_id="ANRILT",
                  template_type="promotional", status=status, send_at=send_at.isoformat(),
                  created_at=NOW.isoformat(), **extra)


# ---------------------------------------------------------------- ₹ estimate

def test_rate_is_the_clients_own_recent_charge_per_part():
    db = FakeSupabase()
    db.add("sms_messages", tenant_id=T, sms_count=2, amount_debited="0.50", updated_at="2026-11-02")
    db.add("sms_messages", tenant_id=T, sms_count=1, amount_debited="0.25", updated_at="2026-11-02")
    db.add("sms_messages", tenant_id=T, sms_count=1, amount_debited=None, updated_at="2026-11-02")
    db.add("sms_messages", tenant_id=OTHER, sms_count=1, amount_debited="9", updated_at="2026-11-02")
    assert float(camp.rate_per_sms(db, T)) == 0.25


def test_no_charge_reported_yet_means_no_estimate():
    db = FakeSupabase()
    db.add("sms_messages", tenant_id=T, sms_count=1, amount_debited=None)
    assert camp.rate_per_sms(db, T) is None


# ---------------------------------------------------------------- reschedule

def test_reschedule_moves_the_campaign_and_its_queued_messages():
    db = FakeSupabase()
    c = _campaign(db)
    db.add("sms_messages", tenant_id=T, campaign_id=c["id"], status="queued", send_at=c["send_at"])
    db.add("sms_messages", tenant_id=T, campaign_id=c["id"], status="skipped", send_at=c["send_at"])
    new = NOW + timedelta(days=1)
    camp.reschedule_campaign(db, T, c["id"], new, now=NOW)
    assert db.rows("sms_campaigns")[0]["send_at"] == new.isoformat()
    queued, skipped = db.rows("sms_messages")
    assert queued["send_at"] == new.isoformat() and skipped["send_at"] == c["send_at"]


@pytest.mark.parametrize("status,starts_in,when,code", [
    ("sending", timedelta(hours=2), timedelta(days=1), 409),
    ("scheduled", timedelta(seconds=30), timedelta(days=1), 409),  # the scheduler may already have it
    ("scheduled", timedelta(hours=2), timedelta(minutes=-5), 422),  # into the past
])
def test_reschedule_refusals(status, starts_in, when, code):
    db = FakeSupabase()
    c = _campaign(db, status=status, send_at=NOW + starts_in)
    with pytest.raises(camp.SmsError) as e:
        camp.reschedule_campaign(db, T, c["id"], NOW + when, now=NOW)
    assert e.value.status == code


def test_reschedule_another_tenants_campaign_is_not_found():
    db = FakeSupabase()
    c = _campaign(db, tenant=OTHER)
    with pytest.raises(camp.SmsError) as e:
        camp.reschedule_campaign(db, T, c["id"], NOW + timedelta(days=1), now=NOW)
    assert e.value.status == 404


# ---------------------------------------------------------------- delete

def test_delete_hides_a_finished_campaign_but_keeps_its_spend():
    db = FakeSupabase()
    c = _campaign(db, status="completed")
    db.add("sms_messages", tenant_id=T, campaign_id=c["id"], status="delivered", sms_count=2, amount_debited="0.4")
    camp.delete_campaign(db, T, c["id"], now=NOW)
    assert camp.get_campaign_row(db, T, c["id"]) is None
    assert len(db.rows("sms_messages")) == 1
    item = sms_wallet.history(db, T)["items"][0]
    assert item["label"] == "Diwali (deleted)" and item["campaign_id"] is None and item["sms"] == -2


@pytest.mark.parametrize("status,code", [("scheduled", 409), ("sending", 409)])
def test_live_campaigns_cannot_be_deleted(status, code):
    db = FakeSupabase()
    c = _campaign(db, status=status)
    with pytest.raises(camp.SmsError) as e:
        camp.delete_campaign(db, T, c["id"], now=NOW)
    assert e.value.status == code and db.rows("sms_campaigns")[0].get("deleted_at") is None


def test_deleting_twice_or_across_tenants_is_not_found():
    db = FakeSupabase()
    c = _campaign(db, status="cancelled")
    camp.delete_campaign(db, T, c["id"], now=NOW)
    with pytest.raises(camp.SmsError) as e:
        camp.delete_campaign(db, T, c["id"], now=NOW)
    assert e.value.status == 404
    theirs = _campaign(db, status="cancelled", tenant=OTHER)
    with pytest.raises(camp.SmsError) as e:
        camp.delete_campaign(db, T, theirs["id"], now=NOW)
    assert e.value.status == 404


@pytest.mark.asyncio
async def test_deleted_campaigns_leave_the_list():
    db = FakeSupabase()
    keep = _campaign(db, status="completed")
    gone = _campaign(db, status="cancelled", deleted_at=NOW.isoformat())
    with patch.object(sms, "get_supabase", lambda: db):
        out = await sms.list_campaigns(limit=50, offset=0, ctx=CTX)
    assert [c["id"] for c in out["campaigns"]] == [keep["id"]] and gone["id"] != keep["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [("requested", None), ("rejected", None), ("in_progress", 409), ("ready", 409)])
async def test_template_request_delete(status, code):
    db = FakeSupabase()
    r = db.add("sms_template_requests", tenant_id=T, wording="Hello {#var#}", template_type="service", status=status)
    with patch.object(sms, "get_supabase", lambda: db):
        if code is None:
            assert (await sms.delete_template_request(r["id"], CTX))["ok"]
            assert db.rows("sms_template_requests") == []
        else:
            with pytest.raises(HTTPException) as e:
                await sms.delete_template_request(r["id"], CTX)
            assert e.value.status_code == code and len(db.rows("sms_template_requests")) == 1


@pytest.mark.asyncio
async def test_template_request_of_another_tenant_is_not_found():
    db = FakeSupabase()
    r = db.add("sms_template_requests", tenant_id=OTHER, wording="Hello", template_type="service", status="requested")
    with patch.object(sms, "get_supabase", lambda: db), pytest.raises(HTTPException) as e:
        await sms.delete_template_request(r["id"], CTX)
    assert e.value.status_code == 404 and len(db.rows("sms_template_requests")) == 1


# ---------------------------------------------------------------- OTP history

@pytest.mark.asyncio
async def test_otp_send_resend_and_verify_are_logged_without_the_code():
    db = FakeSupabase()
    with patch.object(sms, "get_supabase", lambda: db), \
         patch.object(bulk9_client, "otp_send", AsyncMock(return_value={"request_id": "o1", "message": "sent"})), \
         patch.object(bulk9_client, "otp_resend", AsyncMock(return_value={"message": "again"})), \
         patch.object(bulk9_client, "otp_verify", AsyncMock(side_effect=Bulk9Error("Invalid OTP"))):
        await sms.otp_send(sms.OtpSendBody(mobile="9876543210", otp_id="7"), CTX)
        await sms.otp_resend(sms.OtpResendBody(mobile="9876543210"), CTX)
        out = await sms.otp_verify(sms.OtpVerifyBody(mobile="9876543210", otp="123456"), CTX)
    assert out == {"ok": False, "message": "Invalid OTP"}
    rows = db.rows("sms_otp_log")
    assert [(r["action"], r["ok"]) for r in rows] == [("send", True), ("resend", True), ("verify", False)]
    assert rows[0]["request_id"] == "o1" and rows[0]["created_by"] == "u1"
    assert all("123456" not in str(r) for r in rows)


@pytest.mark.asyncio
async def test_failed_send_is_logged_and_still_raised():
    db = FakeSupabase()
    with patch.object(sms, "get_supabase", lambda: db), \
         patch.object(bulk9_client, "otp_send", AsyncMock(side_effect=Bulk9Error("Bad OTP template"))), \
         pytest.raises(HTTPException) as e:
        await sms.otp_send(sms.OtpSendBody(mobile="9876543210", otp_id="7"), CTX)
    assert e.value.status_code == 502
    assert db.rows("sms_otp_log")[0]["ok"] is False


@pytest.mark.asyncio
async def test_otp_history_is_per_tenant_newest_first():
    db = FakeSupabase()
    db.add("sms_otp_log", tenant_id=T, mobile="9876543210", action="send", ok=True, created_at="2026-11-01")
    db.add("sms_otp_log", tenant_id=T, mobile="9876543210", action="verify", ok=True, created_at="2026-11-02")
    db.add("sms_otp_log", tenant_id=OTHER, mobile="9000000000", action="send", ok=True, created_at="2026-11-03")
    with patch.object(sms, "get_supabase", lambda: db):
        out = await sms.otp_history(limit=50, offset=0, ctx=CTX)
    assert [i["action"] for i in out["items"]] == ["verify", "send"]
    assert set(out["items"][0]) == {"id", "mobile", "action", "ok", "message", "created_at", "delivery_status", "delivered_at"}
