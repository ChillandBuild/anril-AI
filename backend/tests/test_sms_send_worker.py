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
    assert r["sms_count"] == 1
    assert "charged_amount" not in r and "cost_amount" not in r
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


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [Bulk9Error("Upstream unavailable", http_status=503), {"return": True}])
async def test_ambiguous_send_stays_unknown_and_is_not_resent(outcome):
    db = _db()
    send = AsyncMock(side_effect=outcome) if isinstance(outcome, Exception) else AsyncMock(return_value=outcome)
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", send):
        await sms_campaigns.process_due_sms(db, now=NOW)
        await sms_campaigns.process_due_sms(db, now=NOW + timedelta(hours=1))
    assert _row(db)["status"] == "unknown"
    send.assert_awaited_once()


# ---------------------------------------------------------------- batch send (Bulk9 "Multiple", /dev/custom)

def _batch_db(n=3, *, kind="template", variables=("Ravi", "Gold")):
    db = FakeSupabase()
    db.add("tenants", id=T, enabled_features=["sms"])
    extra = {"kind": "manual", "message_id": None, "manual_entity_id": "1701", "manual_template_id": "1707"} \
        if kind == "manual" else {"kind": "template", "message_id": "15001"}
    camp = db.add("sms_campaigns", tenant_id=T, status="scheduled", sender_id="KELIR", source="numbers",
                  completed_at=None, **extra)
    for i in range(n):
        db.add("sms_messages", tenant_id=T, campaign_id=camp["id"], phone=f"98765000{i:02d}", content=f"Hi {i}",
               variables=list(variables), status="queued", send_at=(NOW - timedelta(minutes=1)).isoformat(),
               claimed_at=None)
    return db


def _batch_on(key, tenant_id=None):
    return {"bulk9_api_key": "k", "bulk9_batch_send": "true"}.get(key)


@pytest.mark.asyncio
async def test_batch_on_sends_one_call_and_each_row_keeps_its_tag():
    db = _batch_db(3)
    custom = AsyncMock(return_value={"return": True, "request_id": "R9", "message": ["SMS sent successfully"]})
    with patch.object(sms_campaigns, "get_setting", side_effect=_batch_on), \
         patch.object(sms_campaigns.bulk9_client, "send_custom", custom), \
         patch.object(sms_campaigns.bulk9_client, "send_dlt", AsyncMock()) as single:
        assert await sms_campaigns.process_due_sms(db, now=NOW) == {"claimed": 3}
    single.assert_not_awaited()
    custom.assert_awaited_once()
    kw = custom.await_args.kwargs
    rows = db.rows("sms_messages")
    assert kw["route"] == "dlt"
    assert kw["requests"] == [{"sender_id": "KELIR", "message": 15001, "variables_values": "Ravi|Gold",
                               "numbers": r["phone"], "udf1": r["id"]} for r in rows]
    assert all(r["status"] == "submitted" and r["request_id"] == "R9" for r in rows)


@pytest.mark.asyncio
async def test_batch_off_by_default_sends_one_by_one():
    db = _batch_db(3)
    single = AsyncMock(return_value={"return": True, "request_id": "r1"})
    with patch.object(sms_campaigns.bulk9_client, "send_dlt", single), \
         patch.object(sms_campaigns.bulk9_client, "send_custom", AsyncMock()) as custom:
        await sms_campaigns.process_due_sms(db, now=NOW)
    custom.assert_not_awaited()
    assert single.await_count == 3


@pytest.mark.asyncio
async def test_refused_batch_falls_back_to_single_sends():
    db = _batch_db(3)
    single = AsyncMock(side_effect=[{"return": True, "request_id": "a"}, Bulk9Error("Invalid number"),
                                    {"return": True, "request_id": "c"}])
    with patch.object(sms_campaigns, "get_setting", side_effect=_batch_on), \
         patch.object(sms_campaigns.bulk9_client, "send_custom",
                      AsyncMock(side_effect=Bulk9Error("Invalid number", http_status=400))), \
         patch.object(sms_campaigns.bulk9_client, "send_dlt", single):
        await sms_campaigns.process_due_sms(db, now=NOW)
    assert [r["status"] for r in db.rows("sms_messages")] == ["submitted", "failed", "submitted"]


@pytest.mark.asyncio
async def test_batch_return_false_on_http_200_marks_unknown_and_never_resends():
    # Bulk9's docs don't say whether part of a return=false batch still went out: never re-send it.
    db = _batch_db(3)
    with patch.object(sms_campaigns, "get_setting", side_effect=_batch_on), \
         patch.object(sms_campaigns.bulk9_client, "send_custom",
                      AsyncMock(side_effect=Bulk9Error("Request 2 invalid", http_status=200))), \
         patch.object(sms_campaigns.bulk9_client, "send_dlt", AsyncMock()) as single:
        await sms_campaigns.process_due_sms(db, now=NOW)
        await sms_campaigns.process_due_sms(db, now=NOW + timedelta(minutes=1))
    single.assert_not_awaited()
    assert all(r["status"] == "unknown" for r in db.rows("sms_messages"))


@pytest.mark.asyncio
async def test_batch_timeout_marks_all_unknown_and_never_resends():
    db = _batch_db(3)
    with patch.object(sms_campaigns, "get_setting", side_effect=_batch_on), \
         patch.object(sms_campaigns.bulk9_client, "send_custom", AsyncMock(side_effect=Bulk9Timeout("slow"))), \
         patch.object(sms_campaigns.bulk9_client, "send_dlt", AsyncMock()) as single:
        await sms_campaigns.process_due_sms(db, now=NOW)
        await sms_campaigns.process_due_sms(db, now=NOW + timedelta(minutes=1))
    single.assert_not_awaited()
    assert all(r["status"] == "unknown" for r in db.rows("sms_messages"))


@pytest.mark.asyncio
async def test_batch_type_my_own_uses_dlt_manual_items():
    db = _batch_db(2, kind="manual", variables=())
    custom = AsyncMock(return_value={"return": True, "request_id": "R7"})
    with patch.object(sms_campaigns, "get_setting", side_effect=_batch_on), \
         patch.object(sms_campaigns.bulk9_client, "send_custom", custom):
        await sms_campaigns.process_due_sms(db, now=NOW)
    kw = custom.await_args.kwargs
    assert kw["route"] == "dlt_manual"
    assert kw["requests"][0] == {"sender_id": "KELIR", "entity_id": "1701", "template_id": "1707", "message": "Hi 0",
                                 "numbers": "9876500000", "udf1": db.rows("sms_messages")[0]["id"]}


@pytest.mark.asyncio
async def test_a_value_with_a_pipe_goes_on_its_own_and_one_left_over_uses_single_send():
    db = _batch_db(2)
    db.rows("sms_messages")[0]["variables"] = ["Ra|vi", "Gold"]
    with patch.object(sms_campaigns, "get_setting", side_effect=_batch_on), \
         patch.object(sms_campaigns.bulk9_client, "send_custom", AsyncMock()) as custom:
        await sms_campaigns.process_due_sms(db, now=NOW)
    custom.assert_not_awaited()
    rows = db.rows("sms_messages")
    assert rows[0]["status"] == "failed" and "|" in rows[0]["failure_reason"]


@pytest.mark.asyncio
async def test_send_custom_payload_and_scrub():
    req = AsyncMock(return_value={"return": True, "request_id": "R9", "wallet": 900})
    items = [{"sender_id": "KELIR", "message": 1, "variables_values": "", "numbers": "9876543210", "udf1": "m1"}]
    with patch.object(sms_campaigns.bulk9_client, "_request", req):
        out = await sms_campaigns.bulk9_client.send_custom("k", route="dlt", requests=items)
    assert req.await_args.args[1:] == ("POST", "/dev/custom")
    assert req.await_args.kwargs["json"] == {"route": "dlt", "requests": items}
    assert "wallet" not in out
    with pytest.raises(ValueError):
        await sms_campaigns.bulk9_client.send_custom("k", route="q", requests=items)


@pytest.mark.asyncio
async def test_reconcile_of_a_shared_batch_request_id_matches_each_row_by_tag():
    from app.services import sms_delivery
    db = FakeSupabase()
    old = (NOW - timedelta(minutes=30)).isoformat()
    a = db.add("sms_messages", tenant_id=T, phone="9876500000", status="submitted", request_id="R9", submitted_at=old,
               updated_at=old, last_reconciled_at=None)
    b = db.add("sms_messages", tenant_id=T, phone="9876500001", status="submitted", request_id="R9", submitted_at=old,
               updated_at=old, last_reconciled_at=None)
    report = {"data": [{"mobile": "", "udf1": a["id"], "status": "DELIVERED"},
                       {"mobile": "", "udf1": b["id"], "status": "FAILED", "status_description": "Switched off"}]}
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "delivery_report", AsyncMock(return_value=report)) as dr:
        await sms_delivery.reconcile(db, now=NOW)
    rows = {r["id"]: r for r in db.rows("sms_messages")}
    assert (rows[a["id"]]["status"], rows[b["id"]]["status"]) == ("delivered", "failed")
    assert dr.await_count == 1  # one report call for the whole batch


@pytest.mark.asyncio
async def test_reconcile_ignores_untagged_numberless_report_rows_for_a_shared_request_id():
    from app.services import sms_delivery
    db = FakeSupabase()
    old = (NOW - timedelta(minutes=30)).isoformat()
    for i in range(2):
        db.add("sms_messages", tenant_id=T, phone=f"98765000{i:02d}", status="submitted", request_id="R9",
               submitted_at=old, updated_at=old, last_reconciled_at=None)
    report = {"data": [{"mobile": "", "status": "DELIVERED"}]}
    with patch.object(sms_delivery.bulk9_client, "get_api_key", return_value="k"), \
         patch.object(sms_delivery.bulk9_client, "delivery_report", AsyncMock(return_value=report)):
        await sms_delivery.reconcile(db, now=NOW)
    assert all(r["status"] == "submitted" for r in db.rows("sms_messages"))
