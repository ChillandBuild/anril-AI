"""Campaigns to SMS contacts (built in the background), pasted numbers, raw DLT IDs, and OTP delivery."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.routes import sms
from app.services import bulk9_client, sms_campaigns as camp, sms_delivery
from tests.fake_supabase import FakeSupabase

T = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
CTX = {"tenant_id": T, "api_key": "k", "user_id": "u1"}


def _template(db, template_type="service", message="Hi {#var#}, your plan is {#var#}"):
    return db.add("sms_templates", tenant_id=T, template_type=template_type, status="ready", message_id="77",
                  sender_id="ANRILT", message=message)


def _contacts(db, group, *rows, tenant=T):
    return [db.add("sms_contacts", tenant_id=tenant, phone=p, name=n, fields=f, group_ids=[group["id"]],
                   promo_consent_at=c) for p, n, f, c in rows]


def _setup():
    db = FakeSupabase()
    db.add("tenants", id=T, enabled_features=["sms"])
    g = db.add("sms_contact_groups", tenant_id=T, name="Diwali")
    _contacts(db, g,
              ("9876543210", "Ravi Kumar", {"plan": "Gold"}, "2026-11-01"),
              ("9876500000", "Asha", {}, None),             # no plan value
              ("9876511111", "Meena", {"plan": "Silver"}, None))  # no promo consent
    return db, g


def _create(db, template, g, vmap, **kw):
    return camp.create_campaign(db, T, "u1", name="Diwali", template=template, variable_map=vmap, send_at=None,
                                idempotency_key=kw.pop("key", "key-12345678"), now=NOW,
                                audience=camp.Audience(source="contacts", group_ids=[g["id"]]), **kw)


VMAP = [{"source": "field", "value": "first_name"}, {"source": "field", "value": "col:plan"}]


# ---------------------------------------------------------------- contacts

def test_preview_fills_variables_from_extra_columns_and_explains_the_rest():
    db, g = _setup()
    out = camp.preview(db, T, _template(db), VMAP, audience=camp.Audience(source="contacts", group_ids=[g["id"]]))
    assert out["eligible_count"] == 2 and out["excluded_total"] == 1
    assert out["excluded"][0]["reason"] == camp.R_MISSING("col:plan")
    assert {x["content"] for x in out["samples"]} == {"Hi Ravi, your plan is Gold", "Hi Meena, your plan is Silver"}


def test_promotional_skips_contacts_without_consent():
    db, g = _setup()
    out = camp.preview(db, T, _template(db, "promotional"), VMAP,
                       audience=camp.Audience(source="contacts", group_ids=[g["id"]]))
    assert out["eligible_count"] == 1
    assert {e["reason"] for e in out["excluded"]} == {camp.R_NO_CONSENT}


def test_another_tenants_group_is_not_found():
    db, _ = _setup()
    theirs = db.add("sms_contact_groups", tenant_id=OTHER, name="Theirs")
    _contacts(db, theirs, ("9000000001", "X", {}, None), tenant=OTHER)
    with pytest.raises(camp.SmsError) as e:
        camp.preview(db, T, _template(db, message="Hello"), [],
                     audience=camp.Audience(source="contacts", group_ids=[theirs["id"]]))
    assert e.value.status == 404


def test_column_variables_only_for_contacts():
    db, _ = _setup()
    lead = db.add("leads", tenant_id=T, name="Ravi", phone="9876543210")
    with pytest.raises(camp.SmsError, match="Unknown field"):
        camp.preview(db, T, _template(db), VMAP, [lead["id"]])


def test_one_person_in_two_groups_gets_one_sms():
    db, g = _setup()
    g2 = db.add("sms_contact_groups", tenant_id=T, name="VIP")
    db.rows("sms_contacts")[0]["group_ids"].append(g2["id"])
    out = camp.preview(db, T, _template(db, message="Hello"), [],
                       audience=camp.Audience(source="contacts", group_ids=[g["id"], g2["id"]]))
    assert out["eligible_count"] == 3


def test_more_than_the_cap_is_refused():
    db, g = _setup()
    with patch.object(camp, "MAX_CONTACTS", 2), pytest.raises(camp.SmsError, match="more than"):
        camp.preview(db, T, _template(db, message="Hello"), [],
                     audience=camp.Audience(source="contacts", group_ids=[g["id"]]))


def test_contacts_campaign_is_built_by_the_job_then_sent():
    db, g = _setup()
    c, created = _create(db, _template(db), g, VMAP)
    assert created and c["status"] == "preparing" and db.rows("sms_messages") == []
    assert camp.build_preparing(db, NOW) == 1
    c = db.rows("sms_campaigns")[0]
    assert c["status"] == "scheduled" and c["build_error"] is None
    msgs = db.rows("sms_messages")
    assert len(msgs) == 2 and all(m["send_at"] == c["send_at"] and m["contact_id"] for m in msgs)
    assert {m["content"] for m in msgs} == {"Hi Ravi, your plan is Gold", "Hi Meena, your plan is Silver"}


def test_build_claim_is_taken_once_and_a_stale_one_is_rebuilt_without_duplicates():
    db, g = _setup()
    _create(db, _template(db), g, VMAP)
    db.rows("sms_campaigns")[0]["build_started_at"] = (NOW - timedelta(minutes=2)).isoformat()
    assert camp.build_preparing(db, NOW) == 0  # another run is on it
    # That run crashed after inserting (and even releasing) part of the list.
    c = db.rows("sms_campaigns")[0]
    db.add("sms_messages", tenant_id=T, campaign_id=c["id"], phone="9876543210", status="queued",
           send_at=c["send_at"], content="x", variables=[])
    later = NOW + camp.BUILD_STALE + timedelta(minutes=1)
    assert camp.build_preparing(db, later) == 1
    assert len(db.rows("sms_messages")) == 2


def test_cancelled_while_building_sends_nothing():
    db, g = _setup()
    c, _ = _create(db, _template(db), g, VMAP)
    camp.cancel_campaign(db, T, c["id"], now=NOW)
    assert camp.build_preparing(db, NOW) == 0
    assert db.rows("sms_messages") == []


def test_nobody_eligible_cancels_with_a_reason():
    db, g = _setup()
    c, _ = _create(db, _template(db, message="Hello"), g, [])
    for r in db.rows("sms_contacts"):
        r["group_ids"] = []
    camp.build_preparing(db, NOW)
    c = db.rows("sms_campaigns")[0]
    assert c["status"] == "cancelled" and "can receive" in c["build_error"]


def test_a_build_that_keeps_failing_gives_up_after_an_hour():
    db, g = _setup()
    _create(db, _template(db), g, VMAP)
    db.rows("sms_campaigns")[0]["created_at"] = (NOW - timedelta(hours=2)).isoformat()
    camp.build_preparing(db, NOW)
    c = db.rows("sms_campaigns")[0]
    assert c["status"] == "cancelled" and "couldn't be prepared" in c["build_error"]


@pytest.mark.asyncio
async def test_sender_never_sends_for_a_preparing_campaign():
    db, g = _setup()
    c, _ = _create(db, _template(db), g, VMAP)
    db.add("sms_messages", tenant_id=T, campaign_id=c["id"], phone="9876543210", status="sending",
           send_at=NOW.isoformat(), content="x", variables=[])
    row = db.rows("sms_messages")[0]
    send = AsyncMock()
    with patch.object(bulk9_client, "send_dlt", send):
        await camp._send_one(db, row, c, {"enabled": True, "key": "k"})
    send.assert_not_awaited()
    assert row["status"] == "queued" and row["send_at"] == camp.HOLD


@pytest.mark.asyncio
async def test_removed_contact_or_lost_consent_is_skipped_at_send_time():
    db, g = _setup()
    c, _ = _create(db, _template(db, "promotional"), g, VMAP)
    camp.build_preparing(db, NOW)
    row = db.rows("sms_messages")[0]
    db.rows("sms_contacts")[0]["promo_consent_at"] = None
    row["status"] = "sending"
    with patch.object(bulk9_client, "send_dlt", AsyncMock()) as send:
        await camp._send_one(db, row, db.rows("sms_campaigns")[0], {"enabled": True, "key": "k"})
        row2 = {**row, "contact_id": None, "status": "sending"}
        db.rows("sms_messages").append(row2)
        await camp._send_one(db, row2, db.rows("sms_campaigns")[0], {"enabled": True, "key": "k"})
    send.assert_not_awaited()
    assert row["failure_reason"] == camp.R_NO_CONSENT and row2["failure_reason"] == "The contact was removed."


# ---------------------------------------------------------------- pasted numbers

def test_pasted_numbers_are_normalised_deduped_and_reported():
    db, _ = _setup()
    out = camp.preview(db, T, _template(db, message="Hello"), [],
                       audience=camp.Audience(source="numbers", numbers=["+91 98765 43210", "9876543210", "12345", " "]))
    assert out["eligible_count"] == 1
    assert [e["reason"] for e in out["excluded"]] == [camp.R_DUPLICATE, camp.R_NOT_INDIAN]


def test_promotional_to_pasted_numbers_needs_the_tick_and_records_who():
    db, _ = _setup()
    t = _template(db, "promotional", message="Sale")
    aud = camp.Audience(source="numbers", numbers=["9876543210"])
    with pytest.raises(camp.SmsError, match="agreed"):
        camp.create_campaign(db, T, "u1", name="x", template=t, variable_map=[], send_at=None,
                             idempotency_key="key-abcdefgh", now=NOW, audience=aud)
    aud.consent_confirmed = True
    c, _ = camp.create_campaign(db, T, "u1", name="x", template=t, variable_map=[], send_at=None,
                                idempotency_key="key-abcdefgh", now=NOW, audience=aud)
    assert c["status"] == "scheduled" and c["consent_source"].startswith("confirmed by u1")
    assert db.rows("sms_messages")[0]["phone"] == "9876543210"


# ---------------------------------------------------------------- Type my own (route=dlt_manual)

MANUAL = {"sender_id": "kelir", "entity_id": "1701176655431156940", "dlt_template_id": "1707176655431156001",
          "message": "Your booking is confirmed"}


@pytest.mark.asyncio
async def test_type_my_own_sends_with_dlt_manual_and_no_category():
    db, _ = _setup()
    body = sms.PreviewBody(kind="manual", manual=MANUAL, source="numbers", numbers=["9876543210"])
    t = sms._body_template(db, T, body)
    assert t["template_type"] == "unknown" and t["sender_id"] == "KELIR"
    c, _ = camp.create_campaign(db, T, "u1", name="x", template=t, variable_map=[], send_at=None,
                                idempotency_key="manual-key-1", now=NOW, audience=sms._audience(body))
    assert (c["kind"], c["message_id"], c["manual_template_id"]) == ("manual", None, MANUAL["dlt_template_id"])
    row = db.rows("sms_messages")[0]
    row["status"] = "sending"
    manual = AsyncMock(return_value={"status": True, "request_id": "r1"})
    with patch.object(bulk9_client, "send_dlt_manual", manual), patch.object(bulk9_client, "send_dlt", AsyncMock()) as dlt:
        await camp._send_one(db, row, c, {"enabled": True, "key": "k"})
    dlt.assert_not_awaited()
    kw = manual.await_args.kwargs
    assert (kw["entity_id"], kw["template_id"], kw["message"]) == (MANUAL["entity_id"], MANUAL["dlt_template_id"], MANUAL["message"])
    assert row["status"] == "submitted"


def test_type_my_own_refuses_unfilled_variables_and_variable_maps():
    db, _ = _setup()
    with pytest.raises(camp.SmsError, match="var"):
        sms._body_template(db, T, sms.PreviewBody(kind="manual", manual={**MANUAL, "message": "Hi {#var#}"}))
    t = camp.manual_template(sender_id="KELIR", entity_id="1701", dlt_template_id="1707", message="Hi")
    with pytest.raises(camp.SmsError, match="no variables"):
        camp.preview(db, T, t, [{"source": "text", "value": "x"}],
                     audience=camp.Audience(source="numbers", numbers=["9876543210"]))
    with pytest.raises(camp.SmsError, match="Fill in"):
        sms._body_template(db, T, sms.PreviewBody(kind="manual"))


@pytest.mark.asyncio
async def test_send_dlt_manual_payload():
    req = AsyncMock(return_value={"status": True, "request_id": "r1", "wallet": 9})
    with patch.object(bulk9_client, "_request", req):
        out = await bulk9_client.send_dlt_manual("k", sender_id="KELIR", entity_id="1", template_id="2",
                                                 message="Hi", numbers=["9876543210"], udf1="m1")
    assert req.await_args.kwargs["json"] == {"route": "dlt_manual", "sender_id": "KELIR", "entity_id": "1",
        "template_id": "2", "message": "Hi", "numbers": "9876543210", "flash": 0, "sms_details": 1, "udf1": "m1"}
    assert "wallet" not in out


# ---------------------------------------------------------------- OTP delivery webhook

def _otp(db, request_id="otp-1"):
    db.add("sms_otp_log", tenant_id=T, mobile="9876543210", action="send", ok=True, request_id=request_id)
    return db.rows("sms_otp_log")[-1]


def test_otp_delivered_fills_history_and_is_never_undone():
    db = FakeSupabase()
    row = _otp(db)
    out = sms_delivery.handle_otp_callback(db, T, {"request_id": "otp-1", "status": "Delivered",
                                                   "delivery_timestamp": 1762164000, "amount_debited": "0.18"})
    assert out["status"] == "ok" and row["delivery_status"] == "delivered" and row["amount_debited"] == "0.18"
    assert row["delivered_at"].startswith("2025-11-03")
    sms_delivery.handle_otp_callback(db, T, {"request_id": "otp-1", "status": "failed"})
    assert row["delivery_status"] == "delivered"


def test_otp_callback_for_another_tenant_or_pending_status_changes_nothing():
    db = FakeSupabase()
    row = _otp(db)
    assert sms_delivery.handle_otp_callback(db, OTHER, {"request_id": "otp-1", "status": "failed"})["status"] == "unmatched"
    assert sms_delivery.handle_otp_callback(db, T, {"request_id": "otp-1", "status": "sent"})["status"] == "ignored"
    assert row.get("delivery_status") is None


@pytest.mark.asyncio
async def test_fields_route_adds_contact_columns():
    db, g = _setup()
    db.rpc_handlers["sms_contact_field_keys"] = lambda p: [{"key": "plan"}]
    with patch.object(sms, "get_supabase", lambda: db):
        out = await sms.campaign_fields(source="contacts", group_ids=g["id"], ctx=CTX)
    assert out["fields"][-1] == {"key": "col:plan", "label": "plan"}


def test_otp_callback_with_absurd_timestamp_still_records_status():
    db = FakeSupabase()
    for rid, ts in (("otp-1", "1e999"), ("otp-2", 10 ** 20)):
        row = _otp(db, rid)
        out = sms_delivery.handle_otp_callback(db, T, {"request_id": rid, "status": "Delivered",
                                                       "delivery_timestamp": ts})
        assert out["status"] == "ok" and row["delivery_status"] == "delivered"
        assert row.get("delivered_at") is None
