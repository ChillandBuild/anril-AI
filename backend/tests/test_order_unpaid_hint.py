"""New bill: the picked customer's unpaid orders for the "1 unpaid order · Open it" hint
(GET /api/v1/orders/customer), on the fake database."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.services.order_unpaid import unpaid_for_lead
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
OWNER = {"tenant_id": T1, "role": "owner", "user_id": "u1", "permissions": []}


class UnpaidHintTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        self.db.rows("leads").append({"id": "L1", "tenant_id": T1, "name": "Ann", "phone": "+919000000001", "deleted_at": None})
        self.db.rows("leads").append({"id": "L2", "tenant_id": T1, "name": "Bob", "phone": "+919000000002", "deleted_at": None})
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_id] = lambda: T1
        app.dependency_overrides[get_tenant_and_role] = lambda: OWNER
        self.patch = patch("app.routes.orders.get_supabase", return_value=self.db)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        app.dependency_overrides.clear()

    def deal(self, did, lead="L1", stage="awaiting_payment", total=100000, paid=0, created="2026-11-01T10:00:00+00:00", tenant=T1):
        self.db.rows("deals").append({"id": did, "tenant_id": tenant, "lead_id": lead, "stage": stage,
                                      "total_paise": total, "paid_paise": paid, "created_at": created})

    def hint(self):
        res = TestClient(app).get("/api/v1/orders/customer", params={"phone": "9000000001"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_one_unpaid_order_is_counted_and_linked(self):
        self.deal("D1")
        out = self.hint()
        self.assertEqual((out["unpaid_orders"], out["unpaid_order_id"]), (1, "D1"))
        self.assertEqual(out["orders"], 1)   # the old fields are unchanged

    def test_an_advance_taken_still_counts_as_unpaid_until_the_balance_is_zero(self):
        self.deal("D1", paid=40000)
        self.deal("D2", paid=100000, stage="awaiting_payment")   # fully paid: nothing left
        out = self.hint()
        self.assertEqual((out["unpaid_orders"], out["unpaid_order_id"]), (1, "D1"))

    def test_paid_cancelled_and_plain_quotes_do_not_count(self):
        self.deal("W", stage="won", paid=100000)
        self.deal("X", stage="lost")
        self.deal("Q", stage="quoted")
        out = self.hint()
        self.assertEqual((out["unpaid_orders"], out["unpaid_order_id"]), (0, None))

    def test_with_several_the_newest_is_linked(self):
        self.deal("old", created="2026-10-01T00:00:00+00:00")
        self.deal("new", created="2026-11-20T00:00:00+00:00")
        out = self.hint()
        self.assertEqual((out["unpaid_orders"], out["unpaid_order_id"]), (2, "new"))

    def test_another_customer_or_tenant_does_not_leak_in(self):
        self.deal("B1", lead="L2")
        self.deal("T2", tenant=T2)
        self.assertEqual(self.hint()["unpaid_orders"], 0)
        self.assertEqual(unpaid_for_lead(self.db, T1, "L2")["unpaid_order_id"], "B1")
        self.assertEqual(unpaid_for_lead(self.db, T2, "L1")["unpaid_order_id"], "T2")

    def test_an_unknown_number_has_no_hint_fields(self):
        res = TestClient(app).get("/api/v1/orders/customer", params={"phone": "9111111111"})
        self.assertEqual(res.json(), {"found": False})


if __name__ == "__main__":
    unittest.main()
