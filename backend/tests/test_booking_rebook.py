"""v9.2 Bookings: Didn't come, what next? > the rebook message."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import booking_messages as bm
from tests.fake_supabase import FakeSupabase

T = "t1"


def _db(status="no_show", link_on=True):
    db = FakeSupabase()
    db.add("tenants", id=T, name="Glow Clinic")
    db.add("booking_services", id="s1", tenant_id=T, name="Skin check-up")
    db.add("booking_resources", id="r1", tenant_id=T, name="Dr. Kavitha", user_id=None)
    db.add("booking_settings", tenant_id=T, link_token="tok", link_on=link_on)
    db.add("bookings", id="b1", tenant_id=T, status=status, service_id="s1", resource_id="r1",
           customer_name="Divya M", phone="+919800000001", lead_id="L1", source="chat")
    return db


class RebookTests(unittest.TestCase):
    def test_text_with_and_without_the_booking_link(self):
        b = {"customer_name": "Divya M", "service_name": "Skin check-up"}
        self.assertEqual(bm.rebook_text(b, "https://x/book/tok"),
                         "Hi Divya, we missed you for your Skin check-up today. Would you like another time? Pick one here: https://x/book/tok")
        self.assertTrue(bm.rebook_text(b, None).endswith("Reply here and we'll book it."))

    def test_sends_only_for_a_no_show(self):
        deliver = AsyncMock(return_value=("wamid.1", ""))
        with patch.object(bm, "_deliver", deliver):
            self.assertEqual(asyncio.run(bm.send_rebook(_db(), T, "b1")), {"sent": True, "reason": ""})
            self.assertIn("/book/tok", deliver.await_args.kwargs["text"])
            self.assertTrue(deliver.await_args.kwargs["text_only"])
            self.assertEqual(asyncio.run(bm.send_rebook(_db(status="booked"), T, "b1"))["reason"], "not_no_show")

    def test_outside_the_window_says_so(self):
        with patch.object(bm, "_deliver", AsyncMock(return_value=(None, "outside_24h_no_template"))):
            self.assertEqual(asyncio.run(bm.send_rebook(_db(link_on=False), T, "b1")),
                             {"sent": False, "reason": "outside_24h_no_template"})


if __name__ == "__main__":
    unittest.main()
