"""v9.2 Courses: tiles and Fee instalments."""
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import course_fees as cf
from tests.fake_supabase import FakeSupabase

T = "t1"
TODAY = date(2026, 11, 24)


def _db():
    db = FakeSupabase()
    db.add("catalog_items", id="c1", tenant_id=T, name="German A1")
    db.add("course_batches", id="b3", tenant_id=T, name="Batch 3", course_item_id="c1")
    # Harini: 3 parts of 8,000, first paid -> on track (next 5 Dec is 11 days away)
    db.add("fee_plans", id="p1", tenant_id=T, deal_id="d1", parts=[
        {"due_on": "2026-11-05", "amount_paise": 800000}, {"due_on": "2026-12-05", "amount_paise": 800000},
        {"due_on": "2027-01-05", "amount_paise": 800000}])
    db.add("fee_plan_payments", tenant_id=T, fee_plan_id="p1", part_index=0, paid_paise=800000)
    db.add("deals", id="d1", tenant_id=T, paid_paise=800000, stage="awaiting_payment")
    db.add("batch_enrolments", id="e1", tenant_id=T, deal_id="d1", batch_id="b3", lead_id="L1", student_name="Harini S", phone="+91981", status="active")
    # Fathima: late since 2 Nov
    db.add("fee_plans", id="p2", tenant_id=T, deal_id="d2", parts=[
        {"due_on": "2026-10-20", "amount_paise": 600000}, {"due_on": "2026-11-02", "amount_paise": 600000}])
    db.add("deals", id="d2", tenant_id=T, paid_paise=600000, stage="awaiting_payment")
    db.add("batch_enrolments", id="e2", tenant_id=T, deal_id="d2", batch_id="b3", lead_id="L2", student_name="Fathima N", phone="+91982", status="active")
    # Karthik: fully paid on the order itself
    db.add("fee_plans", id="p3", tenant_id=T, deal_id="d3", parts=[{"due_on": "2026-11-01", "amount_paise": 650000}])
    db.add("deals", id="d3", tenant_id=T, paid_paise=650000, stage="won")
    db.add("batch_enrolments", id="e3", tenant_id=T, deal_id="d3", batch_id="b3", lead_id="L3", student_name="Karthik P", phone="+91983", status="active")
    # Dropped student: left out
    db.add("fee_plans", id="p4", tenant_id=T, deal_id="d4", parts=[{"due_on": "2026-11-01", "amount_paise": 1}])
    db.add("deals", id="d4", tenant_id=T, paid_paise=0, stage="awaiting_payment")
    db.add("batch_enrolments", id="e4", tenant_id=T, deal_id="d4", batch_id="b3", student_name="X", phone="1", status="dropped")
    return db


class InstalmentTests(unittest.TestCase):
    def test_rows_status_order_and_next_part(self):
        rows = cf.instalments(_db(), T, today=TODAY)
        self.assertEqual([r["student_name"] for r in rows], ["Fathima N", "Harini S", "Karthik P"])
        fathima, harini, karthik = rows
        self.assertEqual((fathima["status"], fathima["days_late"], fathima["next_paise"]), ("late", 22, 600000))
        self.assertEqual((harini["status"], harini["next_due"], harini["paid_paise"], harini["total_paise"]),
                         ("on_track", "2026-12-05", 800000, 2400000))
        self.assertEqual((harini["course_name"], harini["batch_name"]), ("German A1", "Batch 3"))
        self.assertEqual(karthik["status"], "paid")

    def test_status_rules(self):
        self.assertEqual(cf.status_for(date(2026, 11, 30), TODAY), ("due_soon", 0))
        self.assertEqual(cf.status_for(None, TODAY), ("paid", 0))

    def test_money_can_be_hidden(self):
        row = cf.hide_money(cf.instalments(_db(), T, today=TODAY))[0]
        self.assertFalse(any(k.endswith("_paise") for k in row))


class TileTests(unittest.TestCase):
    def test_tiles(self):
        courses = [{"batches": [
            {"name": "Batch 14", "status": "open", "seats_filled": 18, "seats_waiting": 0, "seats_left": 2, "waitlist_count": 0, "starts_on": "2026-11-18"},
            {"name": "Weekend", "status": "full", "seats_filled": 20, "seats_waiting": 0, "seats_left": 0, "waitlist_count": 11, "starts_on": "2026-11-21"},
            {"name": "Old", "status": "closed", "seats_filled": 9, "seats_waiting": 0, "seats_left": 0, "waitlist_count": 0, "starts_on": "2026-01-01"},
        ]}]
        with patch("app.services.courses.find_demo_service", return_value=None):
            out = cf.tiles(_db(), T, courses, show_money=True, today=TODAY)
        self.assertEqual((out["students"], out["batches"], out["seats_left_this_month"], out["waitlist"]), (38, 2, 2, 11))
        self.assertEqual(out["full_batches"], ["Weekend"])
        self.assertEqual((out["fees_due_students"], out["fees_due_paise"]), (1, 600000))


if __name__ == "__main__":
    unittest.main()
