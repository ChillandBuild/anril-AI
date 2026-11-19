import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.intake import _fetch_session_gst as _real_fetch_session_gst
from app.routes.intake import public_router

app = FastAPI()
app.include_router(public_router, prefix="/api/v1/expert-handoff")
client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_gst_lookup_by_default():
    """The receipt's GST line reads the session row itself; default to 'no GST' so
    tests never reach a real database."""
    with patch("app.routes.intake._fetch_session_gst", return_value={}):
        yield


def _payload(session_id="sess-1", event="payment_link.paid"):
    return {
        "event": event,
        "payload": {
            "payment_link": {"entity": {"notes": {"booking_id": session_id, "booking_ref": "EH-ABC123"}}},
            "payment": {"entity": {"id": "pay_abc123", "amount": 2900}},
        },
    }


def test_webhook_rejects_invalid_signature():
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=False):
        res = client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "bad"})
    assert res.status_code == 400


def test_webhook_rejects_unknown_session_id():
    with patch("app.routes.intake.get_session_tenant_id", return_value=None):
        res = client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "whatever"})
    assert res.status_code == 400


def test_webhook_verifies_signature_against_the_sessions_own_tenant():
    with patch("app.routes.intake.get_session_tenant_id", return_value="tenant-astro-tamil") as get_tenant, \
         patch("app.routes.intake.verify_webhook_signature", return_value=True) as verify, \
         patch("app.routes.intake.confirm_intake_payment", return_value=None):
        client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    get_tenant.assert_called_once_with("sess-1")
    assert verify.call_args.kwargs.get("tenant_id") == "tenant-astro-tamil"


def test_webhook_ignores_non_paid_events():
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True):
        res = client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(event="payment_link.cancelled"), headers={"x-razorpay-signature": "ok"})
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


# confirm_intake_payment's success shape: the receipt fields plus the session and
# lead rows the AstroTamil bridge push needs.
_CONFIRMED = {
    "phone": "+919876543210",
    "tenant_id": "t-1",
    "lead_id": "lead-1",
    "customer_name": "Priya",
    "session": {"id": "sess-1", "tenant_id": "t-1", "collected_data": {"name": "Priya"}},
    "lead": {"id": "lead-1", "phone": "+919876543210", "name": "Priya"},
}


def test_webhook_confirms_payment_and_sends_receipt():
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True), \
         patch("app.routes.intake.confirm_intake_payment", return_value=_CONFIRMED), \
         patch("app.routes.intake.astro_bridge.push_consultation", new=AsyncMock(return_value=None)), \
         patch("app.routes.intake.get_intake_config", return_value={"service_noun": "consultation"}), \
         patch("app.routes.intake.send_whatsapp", new=AsyncMock(return_value="wamid.123")) as send:
        res = client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    send.assert_awaited_once()
    assert "Priya" in send.call_args[0][1]
    assert "consultation" in send.call_args[0][1]


def test_webhook_composes_the_receipt_in_the_leads_actual_language():
    """Live evidence 2026-08-14: a lead locked into native Tamil for the whole
    collection got a plain English 'Payment received, thank you...' receipt the
    moment payment cleared -- this route never touched resolve_language_mode at
    all, since it fires from Razorpay's webhook, outside the WhatsApp message flow."""
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True), \
         patch("app.routes.intake.confirm_intake_payment", return_value=_CONFIRMED), \
         patch("app.routes.intake.astro_bridge.push_consultation", new=AsyncMock(return_value=None)), \
         patch("app.routes.intake.get_intake_config", return_value={"service_noun": "consultation"}), \
         patch("app.routes.intake.compose_payment_receipt", new=AsyncMock(return_value="Priya, உங்க ரீடிங் உறுதி.")) as compose, \
         patch("app.routes.intake.send_whatsapp", new=AsyncMock(return_value="wamid.123")) as send:
        client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    compose.assert_awaited_once_with(
        lead_id="lead-1", tenant_id="t-1", customer_name="Priya", service_noun="consultation",
    )
    assert send.call_args[0][1] == "Priya, உங்க ரீடிங் உறுதி."


def test_webhook_uses_the_tenants_configured_service_noun_in_the_receipt():
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True), \
         patch("app.routes.intake.confirm_intake_payment", return_value=_CONFIRMED), \
         patch("app.routes.intake.astro_bridge.push_consultation", new=AsyncMock(return_value=None)), \
         patch("app.routes.intake.get_intake_config", return_value={"service_noun": "reading"}), \
         patch("app.routes.intake.send_whatsapp", new=AsyncMock(return_value="wamid.123")) as send:
        client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    assert "reading" in send.call_args[0][1]
    assert "consultation" not in send.call_args[0][1]


def test_webhook_pushes_the_paid_consultation_to_the_astro_bridge():
    """The whole point of the bridge: the astrologer platform learns about a paid
    consultation without anyone re-typing it."""
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True), \
         patch("app.routes.intake.confirm_intake_payment", return_value=_CONFIRMED), \
         patch("app.routes.intake.get_intake_config", return_value={"service_noun": "consultation"}), \
         patch("app.routes.intake.send_whatsapp", new=AsyncMock(return_value="wamid.123")), \
         patch("app.routes.intake.record_astro_bridge_ids") as record, \
         patch("app.routes.intake.astro_bridge.push_consultation",
               new=AsyncMock(return_value={"question_id": 77})) as push:
        res = client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    assert res.status_code == 200
    push.assert_awaited_once_with(_CONFIRMED["session"], _CONFIRMED["lead"], "t-1")
    record.assert_called_once_with("sess-1", "t-1", {"question_id": 77})


def test_webhook_still_sends_the_receipt_when_the_bridge_push_fails():
    """A Django outage must not cost the customer their confirmation message —
    the astro-push-reconcile job re-drives the push later."""
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True), \
         patch("app.routes.intake.confirm_intake_payment", return_value=_CONFIRMED), \
         patch("app.routes.intake.get_intake_config", return_value={"service_noun": "consultation"}), \
         patch("app.routes.intake.send_whatsapp", new=AsyncMock(return_value="wamid.123")) as send, \
         patch("app.routes.intake.astro_bridge.push_consultation",
               new=AsyncMock(side_effect=RuntimeError("django down"))):
        res = client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    assert res.status_code == 200
    send.assert_awaited_once()


def test_webhook_passes_the_paid_amount_through_to_confirm_intake_payment():
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True), \
         patch("app.routes.intake.confirm_intake_payment", return_value=None) as confirm, \
         patch("app.routes.intake.get_intake_config", return_value={"service_noun": "consultation"}):
        client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    assert confirm.call_args.kwargs.get("amount_paid_paise") == 2900


def test_webhook_missing_session_id_returns_error_status():
    payload = _payload()
    payload["payload"]["payment_link"]["entity"]["notes"] = {}
    res = client.post("/api/v1/expert-handoff/razorpay-webhook", json=payload, headers={"x-razorpay-signature": "ok"})
    assert res.status_code == 200
    assert res.json()["status"] == "error"


class IntakeWebhookAmountTests(unittest.TestCase):
    def test_records_the_amount_from_the_webhook_not_the_session(self):
        from app.services.intake import confirm_intake_payment

        db = MagicMock()
        existing = MagicMock()
        existing.data = {
            "id": "sess-1", "status": "awaiting_payment", "lead_id": "lead-1",
            "tenant_id": "t-1", "collected_data": {"name": "Cheran"},
            "package_amount_paise": 500000,
        }
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = existing

        confirm_intake_payment("sess-1", "pay_123", amount_paid_paise=200000, db=db)

        # First update is the session's; a later one adopts the collected name onto
        # the lead, so this must not read the most recent call.
        update_patch = db.table.return_value.update.call_args_list[0][0][0]
        self.assertEqual(update_patch["amount_paise"], 200000)
        self.assertTrue(update_patch["amount_mismatch"])

    def test_no_mismatch_flag_when_amount_matches(self):
        from app.services.intake import confirm_intake_payment

        db = MagicMock()
        existing = MagicMock()
        existing.data = {
            "id": "sess-1", "status": "awaiting_payment", "lead_id": "lead-1",
            "tenant_id": "t-1", "collected_data": {"name": "Cheran"},
            "package_amount_paise": 500000,
        }
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = existing

        confirm_intake_payment("sess-1", "pay_123", amount_paid_paise=500000, db=db)

        # First update is the session's; a later one adopts the collected name onto
        # the lead, so this must not read the most recent call.
        update_patch = db.table.return_value.update.call_args_list[0][0][0]
        self.assertEqual(update_patch["amount_paise"], 500000)
        self.assertFalse(update_patch["amount_mismatch"])


if __name__ == "__main__":
    unittest.main()


_GST_SESSION = {"total_amount_paise": 4900, "gst_percent": 18, "gst_amount_paise": 882}


def _post_paid_webhook(receipt_text="Priya, your consultation is confirmed.", gst=None):
    with patch("app.routes.intake.get_session_tenant_id", return_value="t-1"), \
         patch("app.routes.intake.verify_webhook_signature", return_value=True), \
         patch("app.routes.intake.confirm_intake_payment", return_value=_CONFIRMED), \
         patch("app.routes.intake.astro_bridge.push_consultation", new=AsyncMock(return_value=None)), \
         patch("app.routes.intake.get_intake_config", return_value={"service_noun": "consultation"}), \
         patch("app.routes.intake._fetch_session_gst", return_value=gst or {}), \
         patch("app.routes.intake.compose_payment_receipt", new=AsyncMock(return_value=receipt_text)) as compose, \
         patch("app.routes.intake.send_whatsapp", new=AsyncMock(return_value="wamid.1")) as send:
        client.post("/api/v1/expert-handoff/razorpay-webhook", json=_payload(), headers={"x-razorpay-signature": "ok"})
    return compose, send


def test_receipt_appends_a_code_written_gst_breakdown_when_the_session_has_gst():
    compose, send = _post_paid_webhook(gst=_GST_SESSION)
    assert send.call_args[0][1] == "Priya, your consultation is confirmed.\nPaid ₹57.82 (₹49 + ₹8.82 GST @18%)."
    # the model never sees or writes the amounts
    assert "57" not in str(compose.await_args)


def test_receipt_has_no_amount_line_without_gst():
    _, send = _post_paid_webhook(gst={"total_amount_paise": 4900, "gst_percent": None, "gst_amount_paise": None})
    assert send.call_args[0][1] == "Priya, your consultation is confirmed."


def test_deal_flow_receipt_gets_the_same_breakdown_for_a_gst_intake_deal():
    from app.routes.intake import _handle_deal_payment_event
    won = {"deal": {"lead_id": "lead-1", "intake_session_id": "sess-1"}}
    lead_query = MagicMock()
    lead_query.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"phone": "+91"}
    paid = {"status": "recorded", "won": True, "deal": won["deal"], "stock_warnings": []}
    with patch("app.services.deals.mark_won", return_value=won), \
         patch("app.services.deals.record_payment", return_value=paid), \
         patch("app.routes.intake.get_supabase", return_value=lead_query), \
         patch("app.routes.intake._fetch_session_gst", return_value=_GST_SESSION), \
         patch("app.routes.intake.send_whatsapp", new=AsyncMock(return_value="w")) as send:
        res = asyncio.run(_handle_deal_payment_event(_payload(event="payment_link.paid"), "payment_link.paid", "d-1", "t-1"))
    assert res["status"] == "ok"
    assert send.call_args[0][1].endswith("Paid ₹57.82 (₹49 + ₹8.82 GST @18%).")


def test_fetch_session_gst_is_tenant_scoped_and_swallows_errors():
    db = MagicMock()
    chain = db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value
    chain.execute.return_value.data = _GST_SESSION
    with patch("app.routes.intake.get_supabase", return_value=db):
        assert _real_fetch_session_gst("sess-1", "t-1") == _GST_SESSION
    db.table.return_value.select.return_value.eq.assert_called_with("id", "sess-1")
    db.table.return_value.select.return_value.eq.return_value.eq.assert_called_with("tenant_id", "t-1")
    with patch("app.routes.intake.get_supabase", side_effect=RuntimeError("db down")):
        assert _real_fetch_session_gst("sess-1", "t-1") == {}
