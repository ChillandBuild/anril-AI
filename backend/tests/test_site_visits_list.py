"""v9.2 Bookings > Site visits: the list with property, shown by and pickup; Token paid outcome."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.routes import bookings as routes
from app.services import property_visit_messages as pvm
from tests.fake_supabase import FakeSupabase

T = "t1"


class SiteVisitsTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()
        start = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        self.db.add("bookings", id="b1", tenant_id=T, number=1, status="booked", source="ai", start_at=start, end_at=start,
                    block_end_at=start, service_id="svc", resource_id="r1", customer_name="Senthil", phone="+91980",
                    lead_id="L1", booking_date=datetime.now(timezone.utc).date().isoformat(), pickup="Chatram bus stand")
        self.db.add("property_visits", tenant_id=T, booking_id="b1", property_item_id="p1")
        self.db.add("catalog_items", id="p1", tenant_id=T, name="Green Meadows")
        self.db.add("leads", id="L1", tenant_id=T, segment="A")
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "owner", "user_id": "u1", "permissions": []}
        for p in (patch.object(routes, "get_supabase", return_value=self.db),
                  patch("app.services.properties.site_visit_service", return_value={"id": "svc"}),
                  patch.object(routes, "_visible", return_value=[{"id": "r1", "name": "Prakash"}]),
                  patch.object(routes.bk, "service_map", return_value={"svc": {"name": "Site visit"}})):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_list_carries_property_shown_by_pickup_and_interest(self):
        res = self.client.get("/api/v1/bookings/site-visits")
        self.assertEqual(res.status_code, 200, res.text)
        row = res.json()["data"][0]
        self.assertEqual((row["property_name"], row["shown_by"], row["pickup"], row["segment"]),
                         ("Green Meadows", "Prakash", "Chatram bus stand", "A"))

    def test_pickup_is_saved_trimmed(self):
        with patch.object(routes, "_may_act"):
            res = self.client.patch("/api/v1/bookings/b1/pickup", json={"pickup": "  Own   vehicle "})
        self.assertEqual(res.json(), {"pickup": "Own vehicle"})
        self.assertEqual(self.db.rows("bookings")[0]["pickup"], "Own vehicle")


def test_token_paid_is_an_outcome():
    assert "token_paid" in pvm.OUTCOMES and pvm.OUTCOME_LABEL["token_paid"] == "Token paid"


if __name__ == "__main__":
    unittest.main()
