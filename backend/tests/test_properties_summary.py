"""v9.2 Commerce > Properties: tiles and per-project numbers."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import properties_summary as ps
from tests.fake_supabase import FakeSupabase

T = "t1"
NOW = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)
P1, P2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def _db():
    db = FakeSupabase()
    db.add("leads", id="L1", tenant_id=T, segment="A", interested_item_ids=[P1], collected_data={}, created_at="2026-11-20", deleted_at=None)
    db.add("leads", id="L2", tenant_id=T, segment="B", interested_item_ids=[P1, P2], collected_data={"bhk": "3BHK"}, created_at="2026-11-20", deleted_at=None)
    db.add("leads", id="L3", tenant_id=T, segment="C", interested_item_ids=None, collected_data={"bhk": "2 BHK"}, created_at="2026-11-20", deleted_at=None)
    db.add("property_visits", tenant_id=T, property_item_id=P1, booking_id="b1")
    db.add("deal_items", tenant_id=T, deal_id="d1", catalog_item_id=P1)
    db.add("deals", id="d1", tenant_id=T, stage="won", total_paise=10000000)
    db.add("catalog_media", tenant_id=T, catalog_item_id=P1)
    db.add("catalog_media", tenant_id=T, catalog_item_id=P1)
    db.add("catalog_files", tenant_id=T, catalog_item_id=P2, kind="document")
    return db


PROPS = [{"id": P1, "bhk": "2 BHK", "units_left": 12}, {"id": P2, "bhk": "3BHK", "units_left": 0}]


class SummaryTests(unittest.TestCase):
    def run_it(self, show_money=True):
        with patch("app.services.properties.list_properties", return_value=PROPS), \
             patch("app.services.properties.site_visit_service", return_value=None):
            return ps.summary(_db(), T, show_money=show_money, now=NOW)

    def test_tiles(self):
        out = self.run_it()
        self.assertEqual((out["projects"], out["units_left"], out["hot_buyers"], out["tokens"]), (2, 12, 1, 1))
        self.assertEqual(out["tokens_paise"], 10000000)
        # 3BHK is wanted, but the only 3BHK project has no units left
        self.assertEqual((out["asked_not_available"], out["asked_top"]), (1, "3BHK"))

    def test_per_property(self):
        per = self.run_it()["per_property"]
        self.assertEqual(per[P1], {"enquiries": 2, "visits": 1, "tokens": 1, "photos": 2, "brochure": False})
        self.assertEqual(per[P2]["enquiries"], 1)
        self.assertTrue(per[P2]["brochure"])

    def test_money_hidden(self):
        self.assertNotIn("tokens_paise", self.run_it(show_money=False))


if __name__ == "__main__":
    unittest.main()
