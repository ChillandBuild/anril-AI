"""Chats > Archived: an order marked Delivered moves its chat to Archived (archived_reason='order_delivered'),
unless the chat needs attention, the customer just wrote, or another order is still open."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.auto_archive import archive_after_delivery
from tests.fake_supabase import FakeSupabase

T = "t1"


def _db(**lead_extra) -> FakeSupabase:
    db = FakeSupabase()
    lead = {"archived_at": None, "blocked_at": None, "pinned_at": None, "needs_human_attention": False,
            "needs_human_intervention": False, "deleted_at": None,
            "last_inbound_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), **lead_extra}
    db.add("leads", id="L1", tenant_id=T, **lead)
    db.add("deals", id="D1", tenant_id=T, lead_id="L1", stage="won", delivery_status="delivered")
    return db


def _lead(db) -> dict:
    return next(r for r in db.rows("leads") if r["id"] == "L1")


class ArchiveAfterDeliveryTests(unittest.TestCase):
    def test_archives_with_the_delivered_reason(self):
        db = _db()
        self.assertTrue(archive_after_delivery(db, T, "L1", "D1"))
        lead = _lead(db)
        self.assertIsNotNone(lead["archived_at"])
        self.assertEqual(lead["archived_reason"], "order_delivered")
        self.assertIsNone(lead["archived_by_name"])

    def test_leaves_a_chat_that_needs_a_person_pinned_blocked_or_archived(self):
        for extra in ({"needs_human_attention": True}, {"needs_human_intervention": True},
                      {"pinned_at": "2026-11-20T00:00:00+00:00"}, {"blocked_at": "2026-11-20T00:00:00+00:00"},
                      {"archived_at": "2026-11-20T00:00:00+00:00"}):
            with self.subTest(extra=extra):
                db = _db(**extra)
                self.assertFalse(archive_after_delivery(db, T, "L1", "D1"))
                self.assertNotEqual(_lead(db).get("archived_reason"), "order_delivered")

    def test_leaves_a_chat_where_the_customer_wrote_in_the_last_hour(self):
        db = _db()
        _lead(db)["last_inbound_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        self.assertFalse(archive_after_delivery(db, T, "L1", "D1"))
        self.assertIsNone(_lead(db)["archived_at"])

    def test_leaves_it_when_another_order_is_still_open(self):
        for stage, status in (("quoted", None), ("awaiting_payment", None), ("won", "shipped"), ("won", "ready")):
            with self.subTest(stage=stage, status=status):
                db = _db()
                db.add("deals", id="D2", tenant_id=T, lead_id="L1", stage=stage, delivery_status=status)
                self.assertFalse(archive_after_delivery(db, T, "L1", "D1"))
                self.assertIsNone(_lead(db)["archived_at"])

    def test_a_lost_or_delivered_other_order_does_not_block(self):
        db = _db()
        db.add("deals", id="D2", tenant_id=T, lead_id="L1", stage="lost", delivery_status=None)
        db.add("deals", id="D3", tenant_id=T, lead_id="L1", stage="won", delivery_status="delivered")
        self.assertTrue(archive_after_delivery(db, T, "L1", "D1"))

    def test_no_lead_or_another_tenants_lead_does_nothing(self):
        db = _db()
        self.assertFalse(archive_after_delivery(db, T, None, "D1"))
        self.assertFalse(archive_after_delivery(db, "other", "L1", "D1"))
        self.assertIsNone(_lead(db)["archived_at"])


if __name__ == "__main__":
    unittest.main()
