"""Customers' "came from": a lead created by a staff dial reads "dialled by <caller>"."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.google_ads_report import came_from_labels, dialled_label


def _lead(**kw):
    base = {"id": "L1", "source": "manual", "created_at": "2026-11-28T10:00:00+00:00"}
    base.update(kw)
    return base


def _call(created_at="2026-11-28T10:00:05+00:00", name="Anitha"):
    return {"lead_id": "L1", "created_at": created_at, "callers": {"name": name} if name else None}


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.table = db, table

    def select(self, *a, **k): return self
    def eq(self, *a): return self
    def in_(self, *a): return self

    def lte(self, col, val):
        self.db.lte.append((col, val))
        return self

    def order(self, *a, **k): return self

    def execute(self):
        if self.table == "call_logs":
            self.db.call_queries += 1
            if self.db.fail_calls:
                raise RuntimeError("boom")
        return _Res(self.db.rows.get(self.table, []))


class _DB:
    def __init__(self, rows=None, fail_calls=False):
        self.rows, self.fail_calls, self.call_queries, self.lte = rows or {}, fail_calls, 0, []

    def table(self, name):
        return _Q(self, name)


class DialledLabelTests(unittest.TestCase):
    def test_dialled_label_names_the_caller(self):
        self.assertEqual(dialled_label(_lead(), _call()), "dialled by Anitha")

    def test_dialled_label_ignores_late_first_call(self):
        self.assertIsNone(dialled_label(_lead(), _call("2026-11-28T10:10:00+00:00")))

    def test_dialled_label_ignores_other_sources(self):
        self.assertIsNone(dialled_label(_lead(source="whatsapp"), _call()))

    def test_dialled_label_needs_a_caller_name(self):
        self.assertIsNone(dialled_label(_lead(), _call(name=None)))
        self.assertIsNone(dialled_label(_lead(), None))

    def test_ad_label_still_wins(self):
        db = _DB({
            "ad_campaigns": [{"id": "C1", "campaign_name": "Diwali", "platform": "google"}],
            "call_logs": [_call()],
        })
        labels = came_from_labels(db, "t", [_lead(ad_campaign_id="C1")])
        self.assertEqual(labels["L1"], "from Google Ads · Diwali")
        self.assertEqual(db.call_queries, 0)

    def test_came_from_labels_adds_dialled_for_unlabelled_leads(self):
        db = _DB({"call_logs": [_call()]})
        self.assertEqual(came_from_labels(db, "t", [_lead()]), {"L1": "dialled by Anitha"})

    def test_first_call_is_the_earliest(self):
        db = _DB({"call_logs": [_call(name="Anitha"), _call("2026-11-28T10:00:09+00:00", "Ravi")]})
        self.assertEqual(came_from_labels(db, "t", [_lead()])["L1"], "dialled by Anitha")

    def test_failed_call_read_means_no_label(self):
        db = _DB({"call_logs": [_call()]}, fail_calls=True)
        self.assertEqual(came_from_labels(db, "t", [_lead()]), {})

    def test_call_read_is_capped_to_the_dial_window(self):
        db = _DB({"call_logs": [_call()]})
        came_from_labels(db, "t", [_lead()])
        self.assertEqual(db.lte, [("created_at", "2026-11-28T10:02:00+00:00")])


if __name__ == "__main__":
    unittest.main()
