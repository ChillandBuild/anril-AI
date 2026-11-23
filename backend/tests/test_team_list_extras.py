"""Team & roles list (v9.2 #48): sales per person (only with deals.view), the leave tag, and the "what they can do"
line. DB = FakeSupabase."""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services.team_list_extras import role_summary
from tests.fake_supabase import FakeSupabase

T1, T2 = "t1", "t2"
TODAY = date(2026, 11, 23)
OWNER = {"tenant_id": T1, "role": "owner", "user_id": "u-owner", "permissions": []}
HR = {"tenant_id": T1, "role": "caller", "user_id": "u-hr", "permissions": ["roles.view"]}
HR_DEALS = {**HR, "permissions": ["roles.view", "deals.view"]}


def test_summary_owner_and_empty():
    assert role_summary("owner", []) == "Can do everything"
    assert role_summary("caller", []) == "Can only look around"


def test_summary_telecaller_default():
    perms = ["dashboard.view", "conversations.view", "leads.view", "deals.view", "telecalling.dialer"]
    assert role_summary("caller", perms) == "Can see orders, make calls, see leads and see chats"
    assert role_summary("caller", [*perms, "leads.download"]) == "Can see orders, make calls, see leads and 2 more"


def test_summary_manage_covers_view():
    # "work leads" already says "see leads", so the line does not repeat it.
    assert role_summary("caller", ["leads.manage", "leads.view"]) == "Can work leads"
    assert role_summary("caller", ["team.manage", "bookings.view"]) == "Can run the team and see bookings"


@pytest.fixture
def env():
    db = FakeSupabase()
    db.add("tenant_roles", id="r-tc", tenant_id=T1, name="Telecaller", slug="telecaller",
           permissions=["telecalling.dialer", "leads.view"])
    db.add("tenant_users", user_id="u-anitha", tenant_id=T1, role="caller", role_id="r-tc", full_name="Anitha", created_at="2026-01-01")
    db.add("tenant_users", user_id="u-bala", tenant_id=T1, role="caller", role_id="r-tc", full_name="Bala", created_at="2026-01-02")
    db.add("tenant_users", user_id="u-owner", tenant_id=T1, role="owner", full_name="Owner", created_at="2025-12-01")
    db.add("callers", id="c-anitha", tenant_id=T1, user_id="u-anitha", name="Anitha", active=True,
           leave_from="2026-11-22", leave_to="2026-11-25")
    db.add("callers", id="c-bala", tenant_id=T1, user_id="u-bala", name="Bala", active=True,
           leave_from="2026-11-01", leave_to="2026-11-05")               # leave is over
    # won orders: Anitha sold 1180 incl 180 GST = 1000 rupees before GST, plus 500; Bala sold 200; owner made one.
    def deal(did, sold_by, total, gst, when, created_by=None, tenant=T1, stage="won", ai=False):
        db.add("deals", id=did, tenant_id=tenant, stage=stage, sold_by=sold_by, sold_by_ai=ai, created_by=created_by,
               total_paise=total, gst_paise=gst, won_at=when)
    deal("d1", "c-anitha", 118000, 18000, "2026-11-10T06:00:00+00:00")
    deal("d2", "c-anitha", 50000, 0, "2026-11-20T06:00:00+00:00")
    deal("d3", "c-bala", 20000, 0, "2026-11-21T06:00:00+00:00")
    deal("d4", None, 30000, 0, "2026-11-22T06:00:00+00:00", created_by="u-owner")
    deal("d5", "c-anitha", 99900, 0, "2026-10-30T06:00:00+00:00")        # last month: not counted
    deal("d6", "c-anitha", 77700, 0, "2026-11-12T06:00:00+00:00", stage="lost")  # not won
    deal("d7", "c-anitha", 55500, 0, "2026-11-12T06:00:00+00:00", tenant=T2)     # another business
    deal("d8", None, 44400, 0, "2026-11-12T06:00:00+00:00", ai=True)     # the AI agent: nobody's sales
    holder = {"ctx": OWNER}
    with patch("app.routes.rbac.get_supabase", return_value=db), \
         patch("app.routes.rbac.ensure_default_roles"), patch("app.routes.rbac.ensure_team_leader_role"), \
         patch("app.routes.rbac._telecaller_seat_limit", return_value=1), \
         patch("app.routes.rbac._active_telecaller_count", return_value=0), \
         patch("app.services.team_list_extras.today_ist", return_value=TODAY):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]
        try:
            yield type("Env", (), {"db": db, "client": TestClient(app), "holder": holder})
        finally:
            app.dependency_overrides.clear()


def users(env, ctx):
    env.holder["ctx"] = ctx
    res = env.client.get("/api/v1/rbac/users")
    assert res.status_code == 200, res.text
    return {u["user_id"]: u for u in res.json()["data"]}, res.json()


def test_sales_this_month_before_gst_by_person(env):
    by, body = users(env, OWNER)
    assert by["u-anitha"]["sales_paise"] == 100000 + 50000
    assert by["u-bala"]["sales_paise"] == 20000
    assert by["u-owner"]["sales_paise"] == 30000
    assert body["sales_period"] == "this month"


def test_sales_hidden_without_deals_view(env):
    by, _ = users(env, HR)
    assert all("sales_paise" not in u for u in by.values())
    by, _ = users(env, HR_DEALS)
    assert by["u-anitha"]["sales_paise"] == 150000


def test_leave_tag_only_when_on_leave_today(env):
    by, _ = users(env, OWNER)
    assert by["u-anitha"]["on_leave_today"] is True
    assert by["u-anitha"]["leave_until"] == "2026-11-25"
    assert by["u-bala"]["on_leave_today"] is False
    assert by["u-bala"]["leave_until"] is None
    assert by["u-owner"]["on_leave_today"] is False


def test_what_they_can_do_comes_from_the_role(env):
    by, _ = users(env, OWNER)
    assert by["u-owner"]["can_do"] == "Can do everything"
    assert by["u-anitha"]["can_do"] == "Can make calls and see leads"
