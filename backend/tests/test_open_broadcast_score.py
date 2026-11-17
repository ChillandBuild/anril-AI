"""_update_open_broadcast_score: a lead's open broadcast row is scored only on what was said
after that broadcast went out, and the global segment is never touched."""
import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import scoring_engine
from app.services.scoring_engine import _apply_segment_lock, _update_open_broadcast_score
from tests.fake_supabase import FakeSupabase

SENT_AT = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)   # the Diwali broadcast
BEFORE = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc)    # silk saree chat, before it
AFTER = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)      # Diwali reply, after it
NOW = "2026-10-21T09:30:00+00:00"


def _db_with_open_row(segment="A"):
    db = FakeSupabase()
    db.rows("broadcast_lead_scores").append({
        "id": "bls-1", "lead_id": "lead-1", "tenant_id": "tenant-1", "broadcast_id": "b-diwali",
        "segment": segment, "segment_drop_count": 0, "arc_message_count": 0,
        "broadcast_sent_at": SENT_AT.isoformat(), "finalized_at": None,
    })
    return db


class OpenBroadcastScoreTests(unittest.TestCase):
    def test_classifier_sees_only_lines_after_the_broadcast(self):
        db = _db_with_open_row(segment="A")
        lines = ["User: want silk sarees?", "User: is the diwali offer still on?"]
        line_times = [BEFORE, AFTER]
        classifier = AsyncMock(return_value=("C", "asked about the offer"))
        with patch.object(scoring_engine, "_classify_segment", classifier):
            asyncio.run(_update_open_broadcast_score(
                db, "lead-1", "tenant-1", NOW, "is the diwali offer still on?",
                lines=lines, line_times=line_times,
            ))
        classifier.assert_awaited_once()
        conversation = classifier.await_args.args[0]
        self.assertIn("diwali offer", conversation)
        self.assertNotIn("silk sarees", conversation)

    def test_segment_follows_the_lock_and_the_row_is_updated(self):
        db = _db_with_open_row(segment="A")
        classifier = AsyncMock(return_value=("C", "cold"))
        with patch.object(scoring_engine, "_classify_segment", classifier):
            asyncio.run(_update_open_broadcast_score(
                db, "lead-1", "tenant-1", NOW, "ok",
                lines=["User: ok"], line_times=[AFTER],
            ))
        # One small drop from A to C is held for a second confirming message, as in the global lock.
        expected_segment, expected_drop = _apply_segment_lock("C", "A", 0, big_drop=False)
        row = db.rows("broadcast_lead_scores")[0]
        self.assertEqual(expected_segment, "A")
        self.assertEqual(row["segment"], expected_segment)
        self.assertEqual(row["segment_drop_count"], expected_drop)
        self.assertEqual(row["score"], 9)
        self.assertEqual(row["arc_message_count"], 1)
        self.assertEqual(row["last_inbound_at"], NOW)

    def test_a_confirmed_drop_is_written_on_the_second_message(self):
        db = _db_with_open_row(segment="A")
        db.rows("broadcast_lead_scores")[0]["segment_drop_count"] = 1
        classifier = AsyncMock(return_value=("C", "cold"))
        with patch.object(scoring_engine, "_classify_segment", classifier):
            asyncio.run(_update_open_broadcast_score(
                db, "lead-1", "tenant-1", NOW, "ok", lines=["User: ok"], line_times=[AFTER],
            ))
        row = db.rows("broadcast_lead_scores")[0]
        self.assertEqual(row["segment"], "C")
        self.assertEqual(row["score"], 2)

    def test_rejection_writes_d_without_calling_the_classifier(self):
        db = _db_with_open_row(segment="A")
        classifier = AsyncMock(return_value=("A", "should not be used"))
        with patch.object(scoring_engine, "_classify_segment", classifier):
            asyncio.run(_update_open_broadcast_score(
                db, "lead-1", "tenant-1", NOW, "stop sending these", rejection=True,
            ))
        classifier.assert_not_awaited()
        row = db.rows("broadcast_lead_scores")[0]
        self.assertEqual(row["segment"], "D")
        self.assertEqual(row["score"], 0)
        self.assertEqual(row["segment_drop_count"], 0)

    def test_no_open_row_means_nothing_is_classified_or_written(self):
        db = FakeSupabase()
        classifier = AsyncMock(return_value=("A", "x"))
        with patch.object(scoring_engine, "_classify_segment", classifier):
            asyncio.run(_update_open_broadcast_score(db, "lead-9", "tenant-1", NOW, "hi"))
        classifier.assert_not_awaited()
        self.assertEqual(db.rows("broadcast_lead_scores"), [])


if __name__ == "__main__":
    unittest.main()
