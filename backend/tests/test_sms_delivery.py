"""Bulk9 delivery callbacks and the reconcile job: final states stick, retried callbacks are
dropped, a callback that beats its message row is matched later, and a timed-out send is
resolved from Bulk9's logs (never re-sent)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import sms_delivery
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"


class UniqueEventsDb(FakeSupabase):
    """Enforces the sms_delivery_events (tenant_id, dedupe_key) unique index like Postgres."""

    def table(self, name):
        q = super().table(name)
        if name != "sms_delivery_events":
            return q
        db, real_execute = self, q.execute

        def execute():
            if q.op == "insert":
                key = (q.payload["tenant_id"], q.payload["dedupe_key"])
                if any((r["tenant_id"], r["dedupe_key"]) == key for r in db.rows(name)):
                    raise Exception('duplicate key value violates unique constraint (23505)')
            return real_execute()
        q.execute = execute
        return q


def _msg(db, **kw):
    row = {"tenant_id": T, "phone": "+919876543210", "status": "submitted", "request_id": "req-1",
           "submitted_at": None, "updated_at": "2026-10-30T00:00:00+00:00", **kw}
    return db.add("sms_messages", **row)


@pytest.fixture(autouse=True)
def _buy_rate():
    with patch.object(sms_delivery, "get_setting", return_value="0.14"):
        yield


@pytest.mark.parametrize("raw,want", [("Delivered", "delivered"), ("DELIVRD", "delivered"),
                                      ("Failed", "failed"), ("DND", "failed"), ("Sent", "submitted"),
                                      ("weird", None), (None, None)])
def test_classify(raw, want):
    assert sms_delivery.classify(raw) == want


def test_delivered_callback_matched_by_udf1_and_costed():
    db = UniqueEventsDb()
    m = _msg(db)
    out = sms_delivery.handle_callback(db, T, {"request_id": "other", "udf1": m["id"], "mobile": "9876543210",
                                               "status": "Delivered", "sms_count": 2, "amount_debited": "0.50"})
    assert out == {"status": "ok"}
    row = db.rows("sms_messages")[0]
    assert row["status"] == "delivered" and row["delivered_at"]
    assert row["sms_count"] == 2 and row["cost_amount"] == "0.28" and row["charged_amount"] == "0.50"
    assert db.rows("sms_delivery_events")[0]["matched"] is True


def test_retried_callback_is_dropped():
    db = UniqueEventsDb()
    _msg(db)
    p = {"request_id": "req-1", "mobile": "919876543210", "status": "Delivered"}
    assert sms_delivery.handle_callback(db, T, p)["status"] == "ok"
    assert sms_delivery.handle_callback(db, T, p) == {"status": "duplicate"}
    assert len(db.rows("sms_delivery_events")) == 1


def test_final_status_is_never_overwritten():
    db = UniqueEventsDb()
    _msg(db, status="delivered")
    sms_delivery.handle_callback(db, T, {"request_id": "req-1", "mobile": "9876543210", "status": "Failed"})
    assert db.rows("sms_messages")[0]["status"] == "delivered"


def test_request_id_match_checks_the_phone():
    db = UniqueEventsDb()
    _msg(db, phone="+919000000001")
    b = _msg(db, phone="+919000000002")
    sms_delivery.handle_callback(db, T, {"request_id": "req-1", "mobile": "9000000002", "status": "Failed",
                                         "status_description": "Number switched off"})
    rows = {r["id"]: r for r in db.rows("sms_messages")}
    assert rows[b["id"]]["status"] == "failed" and rows[b["id"]]["failure_reason"] == "Number switched off"
    assert [r["status"] for r in rows.values() if r["id"] != b["id"]] == ["submitted"]


@pytest.mark.asyncio
async def test_early_callback_is_matched_by_reconcile():
    db = UniqueEventsDb()
    now = datetime.now(timezone.utc)
    out = sms_delivery.handle_callback(db, T, {"request_id": "req-9", "mobile": "9876543210", "status": "Delivered"})
    assert out == {"status": "unmatched"}
    db.rows("sms_delivery_events")[0]["received_at"] = now.isoformat()
    _msg(db, request_id="req-9", updated_at=now.isoformat())
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"):
        stats = await sms_delivery.reconcile(db, now=now)
    assert stats["events"] == 1
    assert db.rows("sms_messages")[0]["status"] == "delivered"


@pytest.mark.asyncio
async def test_unknown_found_in_logs_is_applied():
    db = UniqueEventsDb()
    now = datetime.now(timezone.utc)
    m = _msg(db, status="unknown", request_id=None, claimed_at=(now - timedelta(minutes=20)).isoformat(),
             updated_at=(now - timedelta(minutes=20)).isoformat())
    logs = {"return": True, "data": [{"udf1": m["id"], "request_id": "req-7", "status": "Delivered"}]}
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "sms_logs", AsyncMock(return_value=logs)):
        await sms_delivery.reconcile(db, now=now)
    row = db.rows("sms_messages")[0]
    assert row["status"] == "delivered" and row["request_id"] == "req-7"


@pytest.mark.asyncio
async def test_unknown_missing_after_30_minutes_fails_without_resend():
    db = UniqueEventsDb()
    now = datetime.now(timezone.utc)
    _msg(db, status="unknown", request_id=None, claimed_at=(now - timedelta(minutes=45)).isoformat(),
         updated_at=(now - timedelta(minutes=45)).isoformat())
    send = AsyncMock()
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "sms_logs", AsyncMock(return_value={"return": True, "data": []})), \
         patch.object(sms_delivery.bulk9_client, "send_dlt", send):
        await sms_delivery.reconcile(db, now=now)
    row = db.rows("sms_messages")[0]
    assert row["status"] == "failed" and "not sent" in row["failure_reason"]
    send.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_missing_but_recent_stays_unknown():
    db = UniqueEventsDb()
    now = datetime.now(timezone.utc)
    _msg(db, status="unknown", request_id=None, claimed_at=(now - timedelta(minutes=12)).isoformat(),
         updated_at=(now - timedelta(minutes=12)).isoformat())
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "sms_logs", AsyncMock(return_value={"return": True, "data": []})):
        await sms_delivery.reconcile(db, now=now)
    assert db.rows("sms_messages")[0]["status"] == "unknown"
