"""GET /api/v1/operator/clients/{tenant_id}/broadcasts: a client's broadcast history for the
system admin, with the same figures the client sees on their own Broadcast History tab."""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.system_admin import get_system_admin

TENANT = "11111111-1111-4111-8111-111111111111"
URL = f"/api/v1/operator/clients/{TENANT}/broadcasts"
SCOPED_TABLES = {"app_settings", "scheduled_broadcasts", "broadcast_tags", "broadcast_lead_scores", "broadcast_recipients"}


class FakeQuery:
    """Chainable stand-in for a PostgREST query. Records the filters; `eq` filters rows that have the key."""

    def __init__(self, db, name):
        self.db, self.name = db, name
        self.eqs, self.ins, self.limited, self.single = {}, set(), False, False

    def __getattr__(self, attr):  # select / gte / lte / is_ / order / not_ ... all just chain
        self.db.calls.append(attr)
        return lambda *a, **k: self

    @property
    def not_(self):
        return self

    def eq(self, key, value):
        self.eqs[key] = value
        return self

    def in_(self, key, _values):
        self.ins.add(key)
        return self

    def limit(self, _n):
        self.limited = True
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        self.db.queries.append(self)
        data = self.db.data.get(self.name, [])
        if isinstance(data, list):
            data = [r for r in data if all(k not in r or r[k] == v for k, v in self.eqs.items())]
        return SimpleNamespace(data=data, count=None)


class FakeDB:
    def __init__(self, data):
        self.data, self.queries, self.calls = data, [], []

    def table(self, name):
        return FakeQuery(self, name)


def entry(bid, ts, **over):
    base = {"broadcast_id": bid, "timestamp": ts, "template_name": f"tpl-{bid}", "opt_in_source": "web",
            "sent": 1, "delivered": 1, "opened": 1, "failed": 0, "total_leads": 5,
            "number_used": "+91 1", "tag_id": None}
    base.update(over)
    return base


def db_with(history, **extra):
    data = {
        "tenants": {"id": TENANT, "name": "AstroTamil"},
        "app_settings": {"value": json.dumps(history)},
    }
    data.update(extra)
    return FakeDB(data)


def freeze(year=2026, month=11, day=19, hour=10, minute=0):
    return patch("app.routes.operator_broadcasts._now",
                 return_value=datetime(year, month, day, hour, minute, tzinfo=timezone.utc))


class OperatorBroadcastsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def get(self, db, query="", url=URL):
        with patch("app.routes.operator_broadcasts.get_supabase", return_value=db), \
             patch("app.routes.upload.get_supabase", return_value=db):
            return self.client.get(url + query)

    def test_default_range_is_last_7_ist_days_including_today(self):
        # 10:00 UTC on 19 Nov = 15:30 IST on 19 Nov -> 13..19 Nov
        history = [
            entry("in-today", "2026-11-19T04:00:00+00:00"),
            entry("in-first-day", "2026-11-13T00:00:00+00:00"),
            entry("too-old", "2026-11-12T18:00:00+00:00"),   # = 12 Nov 23:30 IST, outside
        ]
        with freeze():
            r = self.get(db_with(history))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["date_from"], body["date_to"]), ("2026-11-13", "2026-11-19"))
        self.assertEqual({b["id"] for b in body["broadcasts"]}, {"in-today", "in-first-day"})
        self.assertEqual(body["client_name"], "AstroTamil")

    def test_default_range_rolls_over_at_ist_midnight(self):
        # 19:00 UTC on 19 Nov = 00:30 IST on 20 Nov
        with freeze(hour=19):
            r = self.get(db_with([]))
        self.assertEqual((r.json()["date_from"], r.json()["date_to"]), ("2026-11-14", "2026-11-20"))

    def test_ist_day_boundary(self):
        history = [
            entry("before", "2026-11-18T18:25:00+00:00"),   # 23:55 IST on 18 Nov
            entry("after", "2026-11-18T18:45:00+00:00"),    # 00:15 IST on 19 Nov
        ]
        r19 = self.get(db_with(history), "?date_from=2026-11-19&date_to=2026-11-19").json()
        self.assertEqual([b["id"] for b in r19["broadcasts"]], ["after"])
        self.assertEqual(r19["broadcasts"][0]["sent_at_ist"], "2026-11-19 00:15")
        r18 = self.get(db_with(history), "?date_from=2026-11-18&date_to=2026-11-18").json()
        self.assertEqual([b["id"] for b in r18["broadcasts"]], ["before"])

    def test_bad_inputs_are_400(self):
        db = db_with([])
        for q in ("?date_from=nope", "?date_to=2026-13-45", "?date_from=2026-11-19&date_to=2026-11-18",
                  "?date_from=2026-01-01&date_to=2026-12-31"):
            with freeze():
                r = self.get(db, q)
            self.assertEqual(r.status_code, 400, q)

    def test_span_of_92_days_is_allowed_93_is_not(self):
        db = db_with([])
        ok = self.get(db, "?date_from=2026-08-01&date_to=2026-10-31")      # 92 days inclusive
        bad = self.get(db, "?date_from=2026-08-01&date_to=2026-11-01")     # 93
        self.assertEqual((ok.status_code, bad.status_code), (200, 400))

    def test_unknown_tenant_is_404(self):
        db = db_with([])
        db.data["tenants"] = None
        r = self.get(db)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "Tenant not found"))

    def test_non_uuid_tenant_is_404(self):
        r = self.get(db_with([]), url="/api/v1/operator/clients/not-a-uuid/broadcasts")
        self.assertEqual(r.status_code, 404)

    def test_limit_is_capped_and_newest_first(self):
        history = [entry(f"b{i}", f"2026-11-19T0{i}:00:00+00:00") for i in range(5)]
        with freeze():
            body = self.get(db_with(history), "?limit=2").json()
        self.assertEqual([b["id"] for b in body["broadcasts"]], ["b4", "b3"])
        self.assertEqual((body["count"], body["matched"]), (2, 5))
        with freeze():
            body = self.get(db_with(history), "?limit=100000").json()
        self.assertEqual(body["count"], 5)

    def test_counts_come_from_the_clients_own_classifier(self):
        """sent/delivered/read/failed are recounted from broadcast_recipients + messages exactly as the
        client's refresh does; replies and hot/warm/cold come from the client's history read."""
        ts = "2026-11-19T04:00:00+00:00"
        history = [entry("b1", ts, sent=99, delivered=99, opened=99, failed=99, total_leads=3)]
        recipients = [
            {"broadcast_id": "b1", "lead_id": "l1", "phone": "1", "send_status": "sent", "created_at": ts, "reply_sentiment": "positive"},
            {"broadcast_id": "b1", "lead_id": "l2", "phone": "2", "send_status": "sent", "created_at": ts, "reply_sentiment": None},
            {"broadcast_id": "b1", "lead_id": "l3", "phone": "3", "send_status": "sent", "created_at": ts, "reply_sentiment": "negative"},
        ]
        messages = [
            {"lead_id": "l1", "delivery_status": "read", "created_at": "2026-11-19T04:00:05+00:00"},
            {"lead_id": "l2", "delivery_status": "delivered", "created_at": "2026-11-19T04:00:05+00:00"},
            {"lead_id": "l3", "delivery_status": "failed", "created_at": "2026-11-19T04:00:05+00:00"},
        ]
        scores = [{"broadcast_id": "b1", "segment": "A"}, {"broadcast_id": "b1", "segment": "B"},
                  {"broadcast_id": "b1", "segment": "C"}]
        db = db_with(history, broadcast_recipients=recipients, messages=messages, broadcast_lead_scores=scores)
        with freeze():
            body = self.get(db).json()
        row = body["broadcasts"][0]
        self.assertEqual((row["recipients"], row["sent"], row["delivered"], row["read"], row["failed"]), (3, 2, 2, 1, 1))
        self.assertEqual((row["replied"], row["replied_positive"], row["replied_negative"]), (2, 1, 1))
        self.assertEqual((row["hot"], row["warm"], row["cold"]), (1, 1, 1))

    def test_totals_equal_sum_of_rows(self):
        history = [
            entry("a", "2026-11-19T01:00:00+00:00", sent=4, delivered=3, opened=2, failed=1, total_leads=5),
            entry("b", "2026-11-18T01:00:00+00:00", sent=10, delivered=8, opened=6, failed=2, total_leads=12),
        ]
        with freeze():
            body = self.get(db_with(history)).json()   # no recipient rows -> time-window fallback over no messages
        rows = body["broadcasts"]
        self.assertEqual(len(rows), 2)
        for key in ("recipients", "sent", "delivered", "read", "replied", "failed"):
            self.assertEqual(body["totals"][key], sum(r[key] for r in rows), key)
        self.assertEqual(body["totals"]["recipients"], 17)

    def test_every_query_carries_the_tenant_filter(self):
        ts = "2026-11-19T04:00:00+00:00"
        history = [entry("b1", ts, tag_id="t1")]
        db = db_with(
            history,
            scheduled_broadcasts=[{"id": "b1", "tag_id": "t1"}],
            broadcast_tags=[{"id": "t1", "name": "Diwali"}],
            broadcast_lead_scores=[{"broadcast_id": "b1", "segment": "A"}],
            broadcast_recipients=[{"broadcast_id": "b1", "lead_id": "l1", "phone": "1", "send_status": "sent", "created_at": ts}],
            messages=[{"lead_id": "l1", "delivery_status": "delivered", "created_at": ts}],
        )
        with freeze():
            body = self.get(db).json()
        self.assertEqual(body["broadcasts"][0]["tag"], "Diwali")
        seen = {q.name for q in db.queries}
        for q in db.queries:
            if q.name == "tenants":
                self.assertEqual(q.eqs, {"id": TENANT})
            elif q.limited:
                continue  # the classifier's "does this column exist" probes read no rows
            elif q.name in SCOPED_TABLES:
                self.assertEqual(q.eqs.get("tenant_id"), TENANT, q.name)
            else:
                # upload._classify_broadcast_outcomes reads leads (by id) and messages (by lead_id) with
                # ids taken from tenant-filtered recipient rows, not with an extra tenant filter.
                self.assertTrue({"id", "lead_id"} & q.ins, q.name)
        self.assertTrue({"app_settings", "broadcast_recipients", "messages", "scheduled_broadcasts", "broadcast_tags"} <= seen)

    def test_nothing_is_written(self):
        db = db_with([entry("b1", "2026-11-19T04:00:00+00:00")])
        with freeze():
            self.get(db)
        self.assertTrue(db.calls)  # the recorder saw the reads
        self.assertEqual([c for c in db.calls if c in ("insert", "update", "upsert", "delete")], [])

    def test_no_auth_is_rejected(self):
        app.dependency_overrides.clear()
        r = TestClient(app).get(URL)
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
