"""v9.2 Reach: the 9 AM summary of yesterday's campaigns."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import campaign_morning_summary as cms
from tests.fake_supabase import FakeSupabase

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 24, 9, 0, tzinfo=IST)
YDAY = datetime(2026, 11, 23, 11, 0, tzinfo=IST).astimezone(timezone.utc).isoformat()


def _db():
    db = FakeSupabase()
    db.add("broadcast_recipients", tenant_id="t1", lead_id="L1", send_status="sent", meta_message_id="w1", created_at=YDAY)
    db.add("broadcast_recipients", tenant_id="t1", lead_id="L2", send_status="sent", meta_message_id="w2", created_at=YDAY)
    db.add("broadcast_recipients", tenant_id="t1", lead_id="L3", send_status="failed", meta_message_id=None, created_at=YDAY)
    db.add("messages", tenant_id="t1", meta_message_id="w1", delivery_status="read", lead_id="L1", direction="outbound", created_at=YDAY)
    db.add("messages", tenant_id="t1", meta_message_id="w2", delivery_status="delivered", lead_id="L2", direction="outbound", created_at=YDAY)
    db.add("messages", tenant_id="t1", lead_id="L1", direction="inbound", created_at=(NOW - timedelta(hours=10)).isoformat(), meta_message_id=None)
    return db


class SummaryTests(unittest.TestCase):
    def test_numbers(self):
        db = _db()
        self.assertEqual(cms.tenant_numbers(db, "t1", db.rows("broadcast_recipients")), {"sent": 2, "read": 1, "replied": 1})

    def test_bell_once_per_person_per_day(self):
        db = _db()
        told = []

        def notify(tenant_id, uid, kind, title, message, **kw):
            told.append(message)
            db.add("app_notifications", tenant_id=tenant_id, user_id=uid, type=kind, created_at=NOW.astimezone(timezone.utc).isoformat())

        with patch("app.services.call_alerts.admin_user_ids", return_value=["u1"]), patch("app.services.notify.notify_user", side_effect=notify):
            self.assertEqual(cms.send_morning_summaries(db, NOW), 1)
            self.assertEqual(cms.send_morning_summaries(db, NOW), 0)
        self.assertEqual(told[0], "2 sent · 1 read · 1 replied. Open Reach for who paid.")


if __name__ == "__main__":
    unittest.main()
