"""Chats > Record payment > "Send GST invoice on WhatsApp": the bill goes only with a GSTIN, and a failed
send never undoes the saved payment."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import deals as deals_route
from app.routes.deals import RecordPaymentIn


def _run(gstin: str, notify):
    with patch("app.services.business_details.get_business_details", return_value={"gstin": gstin}), \
         patch("app.services.orders.notify", notify):
        return asyncio.run(deals_route._send_record_payment_bill(object(), "t1", "D1", "u1"))


class RecordPaymentBillTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(RecordPaymentIn(lead_id="L1", method="cash", amount_paise=10000).send_bill)

    def test_sends_the_bill_when_the_business_has_a_gstin(self):
        notify = AsyncMock(return_value={"sent": True})
        self.assertTrue(_run("33ABCDE1234F1Z5", notify))
        notify.assert_awaited_once()
        args, kwargs = notify.call_args
        self.assertEqual(args[1:4], ("t1", "D1", "bill"))
        self.assertEqual(kwargs["sender"], {"sent_by_user_id": "u1"})

    def test_no_gstin_sends_nothing(self):
        notify = AsyncMock(return_value={"sent": True})
        self.assertFalse(_run("  ", notify))
        notify.assert_not_awaited()

    def test_whatsapp_not_sending_is_false(self):
        self.assertFalse(_run("33ABCDE1234F1Z5", AsyncMock(return_value={"sent": False, "reason": "whatsapp_not_connected"})))

    def test_an_error_is_false_not_a_crash(self):
        self.assertFalse(_run("33ABCDE1234F1Z5", AsyncMock(side_effect=RuntimeError("meta down"))))


if __name__ == "__main__":
    unittest.main()
