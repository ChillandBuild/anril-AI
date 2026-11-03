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


@pytest.mark.parametrize("raw,want", [("Delivered", "delivered"), ("DELIVRD", "delivered"),
                                      ("Failed", "failed"), ("DND", "failed"), ("Sent", "submitted"),
                                      ("weird", None), (None, None)])
def test_classify(raw, want):
    assert sms_delivery.classify(raw) == want


def test_delivered_callback_keeps_only_the_clients_own_debit():
    db = UniqueEventsDb()
    m = _msg(db)
    out = sms_delivery.handle_callback(db, T, {"request_id": "other", "udf1": m["id"], "mobile": "9876543210",
                                               "status": "Delivered", "sms_count": 2, "amount_debited": "0.50",
                                               "per_sms_cost": "0.11", "reseller_rate": "0.09"})
    assert out == {"status": "ok"}
    row = db.rows("sms_messages")[0]
    assert row["status"] == "delivered" and row["delivered_at"]
    assert row["sms_count"] == 2
    assert row["amount_debited"] == "0.50"
    assert "cost_amount" not in row and "charged_amount" not in row
    payload = db.rows("sms_delivery_events")[0]["payload"]
    assert payload["amount_debited"] == "0.50"
    assert "per_sms_cost" not in payload and "reseller_rate" not in payload
    assert db.rows("sms_delivery_events")[0]["matched"] is True


def test_debit_arriving_after_final_status_is_still_recorded_once():
    db = UniqueEventsDb()
    m = _msg(db, status="delivered")
    sms_delivery.handle_callback(db, T, {"udf1": m["id"], "mobile": "9876543210", "status": "Delivered",
                                         "amount_debited": "₹ 0.2000", "delivery_attempt": 1})
    sms_delivery.handle_callback(db, T, {"udf1": m["id"], "mobile": "9876543210", "status": "Delivered",
                                         "amount_debited": "9.99", "delivery_attempt": 2})
    assert db.rows("sms_messages")[0]["amount_debited"] == "0.2000"


@pytest.mark.parametrize("raw", ["abc", "-1", "5000", None])
def test_bad_debit_values_are_ignored(raw):
    db = UniqueEventsDb()
    m = _msg(db)
    assert sms_delivery.record_debit(db, T, m, raw) is False
    assert db.rows("sms_messages")[0].get("amount_debited") is None


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
async def test_unknown_missing_after_30_minutes_stays_unknown_without_resend():
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
    assert row["status"] == "unknown"
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


@pytest.mark.asyncio
async def test_nested_delivery_report_uses_recipient_status():
    db = UniqueEventsDb()
    now = datetime.now(timezone.utc)
    _msg(db, updated_at=(now - timedelta(minutes=20)).isoformat())
    report = {"return": True, "data": [{"request_id": "req-1", "debit": "0.5",
              "delivery_status": [{"mobile": "9876543210", "status": "Delivered", "sms_count": 2}]}]}
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "delivery_report", AsyncMock(return_value=report)):
        await sms_delivery.reconcile(db, now=now)
    assert db.rows("sms_messages")[0]["status"] == "delivered"
    assert db.rows("sms_messages")[0]["sms_count"] == 2


@pytest.mark.asyncio
async def test_unknown_log_search_pages_and_keeps_parent_request_id():
    db = UniqueEventsDb()
    now = datetime.now(timezone.utc)
    m = _msg(db, status="unknown", request_id=None, updated_at=(now - timedelta(minutes=45)).isoformat())
    first = {"return": True, "data": [{"request_id": "other"}], "pagination": {"total_pages": 2}}
    second = {"return": True, "data": [{"request_id": "parent-req", "udf1": m["id"],
              "delivery_status": [{"mobile": "9876543210", "status": "Delivered"}]}],
              "pagination": {"total_pages": 2}}
    logs = AsyncMock(side_effect=[first, second])
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "sms_logs", logs):
        await sms_delivery.reconcile(db, now=now)
    assert logs.await_count == 2
    assert logs.await_args_list[1].kwargs["page"] == 2
    assert db.rows("sms_messages")[0]["request_id"] == "parent-req"
    assert db.rows("sms_messages")[0]["status"] == "delivered"


def test_callback_scrubs_nested_financial_fields():
    db = UniqueEventsDb()
    _msg(db)
    sms_delivery.handle_callback(db, T, {"request_id": "req-1", "mobile": "9876543210", "status": "Delivered",
        "details": {"cost_amount": 1, "charged_amount": 2, "price_per_sms": 3, "wallet": 4,
                    "sms_count": 1}})
    assert db.rows("sms_delivery_events")[0]["payload"]["details"] == {"sms_count": 1}


@pytest.mark.asyncio
async def test_reconcile_attempts_rotate_past_unresolved_rows():
    db = UniqueEventsDb()
    now = datetime.now(timezone.utc)
    first = _msg(db, id="00000000-0000-0000-0000-000000000001", request_id="old", updated_at=(now-timedelta(minutes=30)).isoformat())
    second = _msg(db, id="00000000-0000-0000-0000-000000000002", request_id="new", updated_at=(now-timedelta(minutes=20)).isoformat())
    report = AsyncMock(side_effect=sms_delivery.Bulk9Error("not found", http_status=404))
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "delivery_report", report):
        await sms_delivery.reconcile(db, now=now, limit=1)
        await sms_delivery.reconcile(db, now=now+timedelta(minutes=15), limit=1)
    assert [call.args[1] for call in report.await_args_list] == [first["request_id"], second["request_id"]]
    assert all(row.get("last_reconciled_at") for row in db.rows("sms_messages"))
