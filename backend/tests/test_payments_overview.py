"""My business > Payments & advance (read-only side): refund roles, reminder wording, ways to pay,
GSTIN masking, a piece that fails degrading alone, tenant isolation and the permission gate."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import payments_overview as po
from fake_supabase import FakeSupabase

T1, T2 = "t1", "t2"


def _ctx(role="owner", permissions=(), tenant=T1):
    return {"tenant_id": tenant, "user_id": "u1", "role": role, "caller_id": None, "permissions": list(permissions)}


@pytest.fixture
def db():
    return FakeSupabase()


def test_reminders_text_matches_the_orders_rule():
    assert po.reminders_text() == "With the Ready message, then on days 1, 3 and 7, between 10 AM and 7 PM"


def test_hour_and_day_wording():
    assert po._hour_text(0) == "12 AM" and po._hour_text(12) == "12 PM" and po._hour_text(19) == "7 PM"
    assert po._day_list((2,)) == "2" and po._day_list((1, 3)) == "1 and 3"


def test_refund_message_copy_says_5_to_7_days_for_razorpay():
    assert "5-7 working days" in po.REFUND_MESSAGE["razorpay"]
    assert "given back" in po.REFUND_MESSAGE["other"]


def test_refund_who_lists_owner_and_roles_with_deals_refund_only_for_this_shop(db):
    db.add("tenant_roles", tenant_id=T1, name="Manager", permissions=["deals.refund", "deals.view"])
    db.add("tenant_roles", tenant_id=T1, name="Cashier", permissions=["deals.view"])
    db.add("tenant_roles", tenant_id=T1, name="accounts", permissions=["deals.refund"])
    db.add("tenant_roles", tenant_id=T2, name="Other shop role", permissions=["deals.refund"])
    assert po.refund_who(db, T1) == ["Owner", "accounts", "Manager"]
    assert po.refund_who(db, "t3") == ["Owner"]


def test_refund_who_degrades_to_owner_when_roles_unreadable():
    class Broken:
        def table(self, name):
            raise RuntimeError("no table")
    assert po.refund_who(Broken(), T1) == ["Owner"]


def test_mask_gstin():
    assert po.mask_gstin("33ABCDE1234F1Z5") == "33AB••••••••1Z5"
    assert po.mask_gstin("33abcde1234f1z5") == "33AB••••••••1Z5"
    assert po.mask_gstin("123") == "•••"


def test_razorpay_ready_by_connect_or_by_both_keys(db):
    assert po.razorpay_way(db, T1)["ok"] is False
    db.add("app_settings", tenant_id=T1, key="razorpay_key_id", value="rzp_live_x")
    assert po.razorpay_way(db, T1)["ok"] is False          # a key id alone is not enough
    db.add("app_settings", tenant_id=T1, key="razorpay_key_secret", value="s")
    assert po.razorpay_way(db, T1)["ok"] is True
    assert po.razorpay_way(db, T2)["ok"] is False          # another shop's keys don't count
    db.add("app_settings", tenant_id=T2, key="razorpay_oauth_account_id", value="acc_1")
    assert po.razorpay_way(db, T2)["ok"] is True


def test_razorpay_unreadable_is_unknown_not_a_crash():
    class Broken:
        def table(self, name):
            raise RuntimeError("down")
    assert po.razorpay_way(Broken(), T1)["ok"] is None


def test_gst_way_masked_or_simple_bills(db, monkeypatch):
    monkeypatch.setattr("app.services.business_details.get_business_details",
                        lambda tid, db=None: {"gstin": "33ABCDE1234F1Z5" if tid == T1 else ""})
    out = po.gst_way(db, T1)
    assert out["ok"] is True and out["detail"] == "GSTIN 33AB••••••••1Z5" and "ABCDE" not in out["detail"]
    out = po.gst_way(db, T2)
    assert out == {"key": "gst", "ok": False, "detail": "No GSTIN — bills are simple bills"}


def test_gst_way_unreadable_is_unknown(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr("app.services.business_details.get_business_details", boom)
    assert po.gst_way(db, T1)["ok"] is None


def test_overview_shape(db, monkeypatch):
    monkeypatch.setattr("app.services.business_details.get_business_details", lambda tid, db=None: {"gstin": ""})
    out = po.overview(db, T1)
    assert set(out) == {"refund_who", "balance_reminders", "refund_message", "ways_to_pay"}
    assert [w["key"] for w in out["ways_to_pay"]] == ["razorpay", "in_shop", "gst"]
    assert out["ways_to_pay"][1] == {"key": "in_shop", "ok": True, "detail": "Cash, UPI and card are recorded in New bill"}
    assert set(out["refund_message"]) == {"razorpay", "other"}


def test_route_needs_settings_view_or_manage(db, monkeypatch):
    monkeypatch.setattr("app.routes.my_business.get_supabase", lambda: db)
    monkeypatch.setattr("app.services.business_details.get_business_details", lambda tid, db=None: {"gstin": ""})
    holder = {"ctx": _ctx("staff", ["deals.view"])}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]
    try:
        c = TestClient(app)
        assert c.get("/api/v1/my-business/payments").status_code == 403
        holder["ctx"] = _ctx("staff", ["settings.view"])
        assert c.get("/api/v1/my-business/payments").status_code == 200
        holder["ctx"] = _ctx("staff", ["settings.manage"])
        assert c.get("/api/v1/my-business/payments").json()["refund_who"] == ["Owner"]
    finally:
        app.dependency_overrides.clear()
