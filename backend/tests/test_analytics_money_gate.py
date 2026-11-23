"""/analytics/compare and /analytics/ad-performance: ad spend and costs in rupees need owner or deals.view
(the Reports rule). Counts stay for everyone with analytics.view."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app

MONEY_ROW = {"spend": 1200.0, "impressions": 900, "clicks": 40, "ad_leads": 8, "ad_hot_leads": 2,
             "cost_per_lead": 150.0, "cost_per_hot_lead": 600.0}
SUMMARY = {"new_leads": 10, "inbound_leads": 10, "outbound_leads": 0, "hot": 2, "warm": 3, "cold": 5,
           "disqualified": 0, "avg_score": 5.0, "messages_in": 50, "messages_out": 60, "ai_replies": 60,
           "human_replies": 0, "converted": 0}


@pytest.fixture
def as_role():
    holder = {}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]

    def set_ctx(role="staff", permissions=()):
        holder["ctx"] = {"tenant_id": "t1", "user_id": "u1", "role": role, "permissions": list(permissions)}
        return TestClient(app)

    yield set_ctx
    app.dependency_overrides.clear()


def _db():
    data = {
        "analytics_period_summary": [SUMMARY], "analytics_period_money": [MONEY_ROW],
        "analytics_daily_leads": [], "analytics_daily_messages": [], "analytics_segment_movement": [],
        "analytics_response_times": [], "analytics_lead_arrival_heatmap": [],
    }
    db = MagicMock()

    def rpc(name, params):
        res = MagicMock()
        res.execute.return_value = MagicMock(data=list(data.get(name, [])))
        return res

    db.rpc.side_effect = rpc
    return db


URL = "/api/v1/analytics/compare?preset=custom&start=2026-07-15&end=2026-07-16&comparison=previous"


@patch("app.routes.analytics.get_supabase")
def test_compare_hides_rupees_without_deals_view(mock_db, as_role):
    mock_db.return_value = _db()
    body = as_role("staff", ["analytics.view"]).get(URL).json()
    for side in ("current", "previous"):
        money = body[side]["money"]
        assert "spend" not in money and "cost_per_lead" not in money and "cost_per_hot_lead" not in money
        assert money["ad_leads"] == 8 and money["clicks"] == 40  # counts stay
    assert not {"spend", "cost_per_lead", "cost_per_hot_lead"} & set(body["money_metrics"])
    assert "ad_leads" in body["money_metrics"]


@pytest.mark.parametrize("role,perms", [("owner", []), ("staff", ["analytics.view", "deals.view"]),
                                        ("staff", ["analytics.view", "deals.manage"])])
@patch("app.routes.analytics.get_supabase")
def test_compare_keeps_rupees_for_owner_and_deals_view(mock_db, as_role, role, perms):
    mock_db.return_value = _db()
    body = as_role(role, perms).get(URL).json()
    assert body["current"]["money"]["spend"] == 1200.0
    assert body["current"]["money"]["cost_per_lead"] == 150.0
    assert "spend" in body["money_metrics"]


CAMPAIGNS = {"totals": {"campaigns": 1, "tracked_leads": 5}, "campaigns": [
    {"id": "c1", "campaign_name": "Diwali", "spend_inr": 5000.0, "total_leads": 5,
     "cost_per_lead": 1000.0, "cost_per_conversion": 2500.0, "conversion_rate": 0.4}]}


@patch("app.services.growth.build_ad_performance", return_value=CAMPAIGNS)
def test_ad_performance_hides_rupees_without_deals_view(_build, as_role):
    row = as_role("staff", ["analytics.view"]).get("/api/v1/analytics/ad-performance").json()["campaigns"][0]
    assert not {"spend_inr", "cost_per_lead", "cost_per_conversion"} & set(row)
    assert row["total_leads"] == 5 and row["conversion_rate"] == 0.4


@patch("app.services.growth.build_ad_performance", return_value=CAMPAIGNS)
def test_ad_performance_keeps_rupees_with_deals_view(_build, as_role):
    row = as_role("staff", ["analytics.view", "deals.view"]).get("/api/v1/analytics/ad-performance").json()["campaigns"][0]
    assert row["spend_inr"] == 5000.0 and row["cost_per_lead"] == 1000.0


def test_both_routes_still_need_analytics_view(as_role):
    client = as_role("staff", ["deals.view"])
    assert client.get("/api/v1/analytics/ad-performance").status_code == 403


def test_ask_strips_the_same_keys():
    from app.routes.ask import _without_money
    payload = {"current": {"money": dict(MONEY_ROW)}, "previous": None,
               "money_metrics": {"spend": {}, "ad_leads": {}}}
    out = _without_money(payload)
    assert out["current"]["money"] == {"impressions": 900, "clicks": 40, "ad_leads": 8, "ad_hot_leads": 2}
    assert out["money_metrics"] == {"ad_leads": {}}
