"""Client-only SMS contract regressions."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from app.routes import sms
from app.services import bulk9_client, sms_campaigns as camp
from tests.fake_supabase import FakeSupabase
T = "11111111-1111-1111-1111-111111111111"
CTX = {"tenant_id": T, "api_key": "test"}


def setup_campaign():
    db = FakeSupabase()
    lead = db.add("leads", tenant_id=T, name="Prem", phone="9876543210", deleted_at=None,
                  opted_out=False, sms_consent_at="2026-10-01", sms_consent_source="signup")
    template = db.add("sms_templates", tenant_id=T, template_type="service", status="ready",
                      message_id="1", sender_id="ANRILT", message="Hello")
    return db, lead, template


@pytest.mark.asyncio
async def test_balance_is_sms_count_and_the_clients_own_wallet_only():
    with patch.object(bulk9_client, "wallet", AsyncMock(return_value={"sms_count": 4, "wallet": 55.0, "cost": 9})):
        assert await sms.balance(CTX) == {"sms_count": 4, "wallet": 55.0}


def test_preview_counts_and_campaign_storage_have_no_money():
    db, lead, template = setup_campaign()
    result = camp.preview(db, T, template, [], [lead["id"]])
    assert result["total_segments"] == 1
    assert "price_per_sms" not in result and "estimated_total" not in result
    row, _ = camp.create_campaign(db, T, None, name="Test", template=template, variable_map=[],
                                 lead_ids=[lead["id"]], send_at=None, idempotency_key="test-key-123")
    assert "estimated_amount" not in db.rows("sms_messages")[0]
    assert "charged_total" not in camp.public_campaigns(db, T, [row])[0]


def test_past_schedule_is_rejected():
    db, lead, template = setup_campaign()
    now = datetime.now(timezone.utc)
    with pytest.raises(camp.SmsError, match="future"):
        camp.create_campaign(db, T, None, name="Past", template=template, variable_map=[],
            lead_ids=[lead["id"]], send_at=now-timedelta(minutes=1), idempotency_key="past-key-123", now=now)


def test_template_with_no_known_category_still_sends_without_consent_filter():
    # DLT decides the category; when Bulk9 doesn't report it the client is never asked.
    db, lead, template = setup_campaign()
    db.rows("sms_templates")[0]["template_type"] = "unclassified"
    db.rows("leads")[0]["sms_consent_at"] = None
    t = camp.get_template(db, T, template["id"])
    assert t["template_type"] == "unknown"
    c, _ = camp.create_campaign(db, T, None, name="x", template=t, variable_map=[], lead_ids=[lead["id"]],
                                send_at=None, idempotency_key="unknown-key-1")
    assert c["template_type"] == "unknown" and len(db.rows("sms_messages")) == 1


@pytest.mark.parametrize("source,date", [(None, "2026-10-01"), ("signup", None), ("", "2026-10-01")])
def test_promotional_requires_consent_date_and_source(source, date):
    eligible, excluded = camp.eligibility([{"id": "1", "phone": "9876543210",
        "sms_consent_at": date, "sms_consent_source": source}], "promotional", [])
    assert not eligible and excluded[0]["reason"] == camp.R_NO_CONSENT


@pytest.mark.asyncio
async def test_sync_reads_dlt_category_and_keeps_existing_when_bulk9_is_silent():
    db = FakeSupabase()
    db.add("sms_templates", tenant_id=T, message_id="1", message="Hello", sender_id="ANRILT",
           template_type="promotional")
    response = {"data": [{"sender_id": "ANRILT", "templates": [
        {"message_id": "1", "message": "Hello"}, {"message_id": "2", "message": "New"},
        {"message_id": "3", "message": "OTP", "template_type": "Service Implicit"},
        {"message_id": "4", "message": "Sale", "category": "Service Explicit / Promo"}]}]}
    with patch.object(sms, "get_supabase", return_value=db), \
         patch.object(bulk9_client, "list_dlt", AsyncMock(return_value=response)):
        await sms.refresh_templates(CTX)
    rows = {r["message_id"]: r for r in db.rows("sms_templates")}
    assert rows["1"]["template_type"] == "promotional"
    assert rows["2"]["template_type"] == "unclassified"
    assert rows["3"]["template_type"] == "service"
    assert rows["4"]["template_type"] == "promotional"


@pytest.mark.asyncio
async def test_sync_logs_raw_fields_of_a_template_with_no_known_category(caplog):
    db = FakeSupabase()
    response = {"data": [{"sender_id": "ANRILT", "templates": [
        {"message_id": "7", "message": "<#> OTP {#VAR#}", "type": "OTP", "var_count": 1},
        {"message_id": "8", "message": "Hi", "type": "Service Implicit"}]}]}
    with patch.object(sms, "get_supabase", return_value=db), \
         patch.object(bulk9_client, "list_dlt", AsyncMock(return_value=response)), \
         caplog.at_level("INFO", logger=sms.logger.name):
        await sms.refresh_templates(CTX)
    unrecognised = [r.getMessage() for r in caplog.records if "no category we recognise" in r.getMessage()]
    assert len(unrecognised) == 1
    assert "Bulk9 template 7 " in unrecognised[0] and "'type': 'OTP'" in unrecognised[0]
    assert "<#>" not in unrecognised[0]  # the message text itself stays out of the log


@pytest.mark.parametrize("item,expected", [
    ({"template_type": "n"}, "service"), ({"template_type": "y"}, "promotional"),
    ({"type": "SERVICE IMPLICIT"}, "service"), ({"template_category": "Promotional"}, "promotional"),
    ({"category": "Transactional"}, "service"), ({"type": "text"}, None), ({}, None), ({"category": 3}, None)])
def test_template_category_mapping(item, expected):
    assert bulk9_client.template_category(item) == expected


@pytest.mark.asyncio
async def test_excel_template_upload_sends_no_category():
    req = AsyncMock(return_value={"status": True})
    with patch.object(bulk9_client, "_request", req):
        await bulk9_client.add_template_excel("k", entity_id="1701", file_url="https://x/f.xlsx")
    assert "template_type" not in req.await_args.kwargs["json"]


@pytest.mark.asyncio
async def test_reports_and_csv_scrub_money():
    db = FakeSupabase()
    db.add("sms_messages", tenant_id=T, phone="9876543210", content="Hello", status="delivered",
           charged_amount=9, cost_amount=5)
    response = {"return": True, "data": [{"request_id": "parent", "debit": 10,
        "delivery_status": [{"mobile": "9876543210", "status": "Delivered", "amount_debited": 2}]}]}
    with patch.object(sms, "get_supabase", return_value=db), \
         patch.object(bulk9_client, "sms_logs", AsyncMock(return_value=response)):
        logs = await sms.reports_logs(None, None, 1, 50, CTX)
        csv = await sms.export_messages(None, None, None, None, None, CTX)
    assert logs["logs"][0]["request_id"] == "parent"
    assert "debit" not in str(logs) and "amount" not in str(logs)
    assert b"Charged" not in csv.body


@pytest.mark.parametrize("response", [httpx.Response(503, json={"return": False}),
    httpx.Response(200, text="gateway broken"), httpx.Response(200, json=[])])
def test_ambiguous_provider_response_is_timeout(response):
    with pytest.raises(bulk9_client.Bulk9Timeout):
        bulk9_client._parse(response)


@pytest.mark.asyncio
async def test_wallet_helper_keeps_only_sms_count_and_the_clients_wallet():
    with patch.object(bulk9_client, "_request", AsyncMock(return_value={"sms_count": "30", "wallet": "99.5",
                                                                        "reseller_cost": "40"})):
        assert await bulk9_client.wallet("key") == {"sms_count": 30, "wallet": 99.5}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", "abc", "-5", "NaN", "Infinity"])
async def test_a_missing_or_bad_rupee_wallet_is_none_not_an_error(value):
    with patch.object(bulk9_client, "_request", AsyncMock(return_value={"sms_count": "30", "wallet": value})):
        assert await bulk9_client.wallet("key") == {"sms_count": 30, "wallet": None}


@pytest.mark.asyncio
async def test_webhook_update_and_delete_use_documented_methods_and_full_body():
    request = AsyncMock(return_value={"return": True})
    with patch.object(bulk9_client, "_request", request):
        await bulk9_client.create_sms_webhook("key", url="https://example.test/hook", secret="secret")
        await bulk9_client.update_sms_webhook("key", "42", url="https://example.test/hook", secret="secret")
        await bulk9_client.delete_sms_webhook("key", "42")
    create, update, delete = request.await_args_list
    assert update.args == ("key", "PUT", "/dev/webhook/v2/sms/42")
    assert create.kwargs["json"] == update.kwargs["json"]
    assert delete.args == ("key", "DELETE", "/dev/webhook/v2/sms/42")


def test_recursive_financial_scrub_preserves_delivery_fields():
    assert bulk9_client.scrub_financial({"generated_at": "now", "delivery_status": [
        {"status": "Delivered", "sms_count": 2, "totalCharge": 4, "cost_amount": 2}]}) == {
            "generated_at": "now", "delivery_status": [{"status": "Delivered", "sms_count": 2}]}


def test_explicit_provider_rejection_is_not_ambiguous():
    with pytest.raises(bulk9_client.Bulk9Error):
        bulk9_client._parse(httpx.Response(200, json={"return": False, "message": "Invalid template"}))


@pytest.mark.parametrize("flag", ["return", "success"])
@pytest.mark.parametrize("value", [False, "false", "FALSE"])
def test_provider_refusal_flags_are_rejected(flag, value):
    with pytest.raises(bulk9_client.Bulk9Error, match="Invalid key"):
        bulk9_client._parse(httpx.Response(200, json={flag: value, "message": "Invalid key"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, -1, "not-a-count", True, 1.5])
async def test_wallet_rejects_unverified_credit_count(value):
    with patch.object(bulk9_client, "_request", AsyncMock(return_value={"return": True, "sms_count": value})):
        with pytest.raises(bulk9_client.Bulk9Error, match="SMS count"):
            await bulk9_client.wallet("dummy")


@pytest.mark.asyncio
async def test_wallet_accepts_a_verified_zero_balance():
    with patch.object(bulk9_client, "_request", AsyncMock(return_value={"return": "true", "sms_count": "0"})):
        assert await bulk9_client.wallet("dummy") == {"sms_count": 0, "wallet": None}
