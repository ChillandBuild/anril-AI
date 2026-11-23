"""Chats > Record payment: the "Send GST invoice on WhatsApp" switch."""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import deals as deals_routes
from tests.fake_supabase import FakeSupabase

LEAD = "11111111-1111-1111-1111-111111111111"
DEAL = "dddddddd-dddd-dddd-dddd-dddddddddddd"


class RecordPaymentInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {
            "tenant_id": "t1", "role": "owner", "user_id": "u1", "caller_id": None, "permissions": ["deals.manage"],
        }
        self.db = FakeSupabase()
        self.db.add("leads", id=LEAD, tenant_id="t1", deleted_at=None, source="whatsapp")
        self.addCleanup(app.dependency_overrides.clear)
        for p in (
            patch.object(deals_routes, "get_supabase", return_value=self.db),
            patch.object(deals_routes.deals_service, "create_deal", new=AsyncMock(return_value={
                "deal": {"id": DEAL, "total_paise": 250000}, "payment_link": None, "message_sent": False,
                "stock_warnings": []})),
            patch.object(deals_routes, "_load_deal", return_value={"id": DEAL, "total_paise": 250000}),
            patch.object(deals_routes, "_full", side_effect=lambda row, db, t: row),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.pay = patch.object(deals_routes.deals_service, "_insert_payment", return_value=True).start()
        self.addCleanup(patch.stopall)

    def body(self, **extra):
        return {"lead_id": LEAD, "method": "cash", "amount_paise": 250000, "item_ids": [], "sold_by": None, **extra}

    def test_registered_shop_sends_the_bill_after_recording(self):
        from app.services import orders
        with patch("app.services.business_details.charges_gst", return_value=True), \
             patch.object(orders, "ensure_invoice", return_value="INV/1") as ensure, \
             patch.object(orders, "notify", new=AsyncMock(return_value={"sent": True, "reason": None})) as notify:
            res = self.client.post("/api/v1/deals/record-payment", json=self.body(send_gst_invoice=True))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["invoice"], {"sent": True, "reason": None})
        # create_deal writes the payment row (mocked here); the route must not add a second one.
        self.pay.assert_not_called()
        ensure.assert_called_once()
        self.assertEqual(notify.call_args.args[1:4], ("t1", DEAL, "bill"))

    def test_switch_off_sends_nothing(self):
        from app.services import orders
        with patch.object(orders, "notify", new=AsyncMock()) as notify:
            res = self.client.post("/api/v1/deals/record-payment", json=self.body())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json()["invoice"])
        notify.assert_not_called()
        self.pay.assert_not_called()

    def test_whatsapp_trouble_is_reported_not_raised(self):
        from app.services import orders
        with patch("app.services.business_details.charges_gst", return_value=True), \
             patch.object(orders, "ensure_invoice", return_value="INV/1"), \
             patch.object(orders, "notify", new=AsyncMock(return_value={"sent": False, "reason": "outside_24h_no_template"})):
            res = self.client.post("/api/v1/deals/record-payment", json=self.body(send_gst_invoice=True))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["invoice"], {"sent": False, "reason": "outside_24h_no_template"})

    def test_composition_or_unregistered_shop_is_refused_before_anything_is_saved(self):
        with patch("app.services.business_details.charges_gst", return_value=False):
            res = self.client.post("/api/v1/deals/record-payment", json=self.body(send_gst_invoice=True))
        self.assertEqual(res.status_code, 400)
        deals_routes.deals_service.create_deal.assert_not_called()

    def test_payment_link_order_sends_the_invoice_once_paid(self):
        from app.services import orders
        self.db.add("deals", id=DEAL, tenant_id="t1", send_invoice_on_paid=False)
        with patch("app.services.business_details.charges_gst", return_value=True),              patch.object(orders, "notify", new=AsyncMock()) as notify:
            res = self.client.post("/api/v1/deals/record-payment", json=self.body(method="link", send_gst_invoice=True))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["invoice"], {"sent": False, "reason": "on_paid"})
        notify.assert_not_called()  # nothing is sent until the customer pays
        self.assertTrue(next(r for r in self.db.rows("deals") if r["id"] == DEAL)["send_invoice_on_paid"])

    def test_options_show_the_next_order_number(self):
        self.db.add("deal_counters", tenant_id="t1", last_number=1041)
        with patch("app.services.business_details.get_business_details", return_value={}),              patch("app.services.business_details.prices_include_gst", return_value=True),              patch("app.services.business_details.charges_gst", return_value=True):
            res = self.client.get(f"/api/v1/deals/record-payment/options?lead_id={LEAD}")
        self.assertEqual(res.json()["next_order_label"], "D-1042")

    def test_options_say_whether_the_shop_is_gst_registered(self):
        with patch("app.services.business_details.get_business_details", return_value={"gstin": "33AAAAA0000A1Z5"}), \
             patch("app.services.business_details.prices_include_gst", return_value=True):
            for registered in (True, False):
                with patch("app.services.business_details.charges_gst", return_value=registered):
                    res = self.client.get(f"/api/v1/deals/record-payment/options?lead_id={LEAD}")
                self.assertEqual(res.status_code, 200, res.text)
                self.assertIs(res.json()["gst_registered"], registered)


class InvoiceWhenLinkPaidTests(unittest.TestCase):
    """The Razorpay paid webhook sends the bill when Record payment asked for it."""

    def run_it(self, flag, sent=True):
        import asyncio
        from app.routes import intake
        from app.services import orders
        db = FakeSupabase()
        db.add("deals", id=DEAL, tenant_id="t1", send_invoice_on_paid=flag)
        with patch.object(intake, "get_supabase", return_value=db),              patch.object(orders, "ensure_invoice", return_value="INV/1") as ensure,              patch.object(orders, "notify", new=AsyncMock(return_value={"sent": sent, "reason": None})) as notify:
            out = asyncio.run(intake._send_invoice_if_asked("t1", DEAL))
        return out, ensure, notify, db.rows("deals")[0]

    def test_sends_the_bill_and_clears_the_flag(self):
        out, ensure, notify, deal = self.run_it(True)
        self.assertTrue(out)
        ensure.assert_called_once()
        self.assertEqual(notify.call_args.args[1:4], ("t1", DEAL, "bill"))
        self.assertFalse(deal["send_invoice_on_paid"])

    def test_not_asked_sends_nothing(self):
        out, ensure, notify, _ = self.run_it(False)
        self.assertFalse(out)
        notify.assert_not_called()

    def test_bill_that_did_not_go_falls_back_to_the_receipt(self):
        out, _, _, deal = self.run_it(True, sent=False)
        self.assertFalse(out)
        self.assertTrue(deal["send_invoice_on_paid"])


if __name__ == "__main__":
    unittest.main()
