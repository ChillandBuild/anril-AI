"""Per-ad breakdown panel: the service, the route, and the ad_ids filter sent to Meta."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.routes import inbound_leads
from app.services import ad_performance
from app.services import meta_ads_fields as mf
from app.services import meta_ads_insights_sync as sync
from tests.fake_supabase import FakeSupabase

ACCOUNT = "act_111"
URL = "/api/v1/inbound-leads/ad-creatives/ad-1/breakdown"


@pytest.fixture(autouse=True)
def _clear_cache():
    mf._CACHE.clear()
    yield
    mf._CACHE.clear()


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.add("app_settings", tenant_id="t1", key="meta_ads_account_id", value=ACCOUNT)
    fake.add("ad_creatives", id="ad-1", tenant_id="t1", meta_ad_account_id=ACCOUNT,
             meta_ad_id="m1", messaging_channels=["whatsapp"])
    return fake


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setattr(sync, "_get_ads_credentials", lambda db, tenant_id: ("tok", ACCOUNT))
    monkeypatch.setattr(sync, "get_ads_setting", lambda db, tenant_id, key: None)


@pytest.fixture
def fetch(monkeypatch):
    """Fake fetch_meta_insights_live: records every call, returns canned rows per breakdown."""
    state = {"calls": [], "split": [], "whole": []}

    def fake(token, account, *, date_from, date_to, keys, breakdown=None, ad_ids=None):
        state["calls"].append({
            "token": token, "account": account, "date_from": date_from, "date_to": date_to,
            "keys": keys, "breakdown": breakdown, "ad_ids": ad_ids,
        })
        return list(state["whole"] if breakdown is None else state["split"])

    monkeypatch.setattr(mf, "fetch_meta_insights_live", fake)
    return state


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(inbound_leads, "get_supabase", lambda: db)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
    app.dependency_overrides[get_tenant_id] = lambda: "t1"
    app.dependency_overrides[get_tenant_and_role] = lambda: {
        "tenant_id": "t1", "role": "owner", "permissions": [],
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def _build(db, ad_creative_id="ad-1", date_from="2026-10-01", date_to="2026-10-15"):
    return ad_performance.build_ad_breakdown(
        db, "t1", ad_creative_id, breakdown="placement", date_from=date_from, date_to=date_to,
    )


# ---- service --------------------------------------------------------------

def test_other_tenants_creative_returns_none_and_fetches_nothing(db, credentials, fetch):
    db.add("ad_creatives", id="ad-other", tenant_id="t2", meta_ad_account_id=ACCOUNT,
           meta_ad_id="m9", messaging_channels=["whatsapp"])
    assert _build(db, ad_creative_id="ad-other") is None
    assert fetch["calls"] == []


def test_creative_without_messaging_channels_returns_none(db, credentials, fetch):
    db.add("ad_creatives", id="ad-plain", tenant_id="t1", meta_ad_account_id=ACCOUNT,
           meta_ad_id="m2", messaging_channels=[])
    assert _build(db, ad_creative_id="ad-plain") is None
    assert fetch["calls"] == []


def test_creative_on_another_account_returns_none(db, credentials, fetch):
    db.add("ad_creatives", id="ad-old", tenant_id="t1", meta_ad_account_id="act_999",
           meta_ad_id="m3", messaging_channels=["whatsapp"])
    assert _build(db, ad_creative_id="ad-old") is None
    assert fetch["calls"] == []


def test_date_from_is_clipped_to_sync_start_and_both_calls_scope_to_the_ad(db, monkeypatch, fetch):
    monkeypatch.setattr(sync, "_get_ads_credentials", lambda db, tenant_id: ("tok", ACCOUNT))
    monkeypatch.setattr(sync, "get_ads_setting", lambda db, tenant_id, key: "2026-10-05")

    result = _build(db, date_from="2026-09-01", date_to="2026-10-15")

    assert result["date_from"] == "2026-10-05"
    assert result["start_date"] == "2026-10-05"
    assert len(fetch["calls"]) == 2
    split, whole = fetch["calls"]
    assert split["date_from"] == whole["date_from"] == "2026-10-05"
    assert split["ad_ids"] == whole["ad_ids"] == {"m1"}
    assert split["breakdown"] == "placement"
    assert whole["breakdown"] is None
    assert split["keys"] == whole["keys"] == ad_performance.PANEL_KEYS


def test_rows_sort_by_clicks_desc_with_none_as_zero_and_overall_from_whole_ad(db, credentials, fetch):
    fetch["split"] = [
        {"breakdown": "facebook · feed", "values": {"inline_link_clicks": 5}},
        {"breakdown": None, "values": {"inline_link_clicks": None}},
        {"breakdown": "instagram · story", "values": {"inline_link_clicks": 9}},
    ]
    fetch["whole"] = [{"breakdown": None, "values": {"inline_link_clicks": 14, "spend": 3.5}}]

    result = _build(db)

    assert [r["label"] for r in result["rows"]] == ["instagram · story", "facebook · feed", "Unknown"]
    assert result["overall"] == {"inline_link_clicks": 14, "spend": 3.5}


def test_reversed_range_after_clipping_returns_empty_without_fetching(db, monkeypatch, fetch):
    monkeypatch.setattr(sync, "_get_ads_credentials", lambda db, tenant_id: ("tok", ACCOUNT))
    monkeypatch.setattr(sync, "get_ads_setting", lambda db, tenant_id, key: "2026-10-01")

    result = _build(db, date_from="2026-09-01", date_to="2026-09-10")

    assert result["rows"] == []
    assert result["overall"] is None
    assert result["date_from"] == "2026-10-01"
    assert fetch["calls"] == []


def test_no_credentials_raises_value_error(db, monkeypatch, fetch):
    monkeypatch.setattr(sync, "_get_ads_credentials", lambda db, tenant_id: None)
    with pytest.raises(ValueError, match="Connect a Meta Ads account first"):
        _build(db)
    assert fetch["calls"] == []


# ---- route ----------------------------------------------------------------

def test_route_rejects_an_hour_breakdown(client, db):
    res = client.get(URL + "?breakdown=hour")
    assert res.status_code == 400
    assert res.json()["detail"] == "Unknown breakdown: hour"


def test_route_rejects_a_bogus_breakdown(client, db):
    res = client.get(URL + "?breakdown=bogus")
    assert res.status_code == 400


def test_route_returns_404_when_service_finds_no_ad(client, db, monkeypatch):
    monkeypatch.setattr(ad_performance, "build_ad_breakdown", lambda *a, **k: None)
    res = client.get(URL + "?breakdown=age")
    assert res.status_code == 404
    assert res.json()["detail"] == "Ad not found"


def test_route_maps_httpx_errors_to_502(client, db, monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("x")

    monkeypatch.setattr(ad_performance, "build_ad_breakdown", boom)
    res = client.get(URL + "?breakdown=age")
    assert res.status_code == 502
    assert res.json()["detail"] == "Meta didn't respond, try again in a minute"


def test_route_returns_service_result(client, db, monkeypatch):
    seen = {}

    def fake(db_arg, tenant_id, ad_creative_id, *, breakdown, date_from, date_to):
        seen.update(tenant_id=tenant_id, ad_creative_id=ad_creative_id, breakdown=breakdown,
                    date_from=date_from, date_to=date_to)
        return {"ad_creative_id": ad_creative_id, "rows": []}

    monkeypatch.setattr(ad_performance, "build_ad_breakdown", fake)
    res = client.get(URL + "?breakdown=%20device%20&date_from=2026-10-01&date_to=2026-10-02")
    assert res.status_code == 200
    assert res.json() == {"ad_creative_id": "ad-1", "rows": []}
    assert seen == {"tenant_id": "t1", "ad_creative_id": "ad-1", "breakdown": "device",
                    "date_from": "2026-10-01", "date_to": "2026-10-02"}


# ---- meta_ads_fields: ad_ids narrows the Graph request --------------------

@pytest.fixture
def graph(monkeypatch):
    state = {"insight_calls": []}

    def fake_paged(url, params):
        state["insight_calls"].append(params)
        return []

    def fake_all_statuses(url, params, *, status_field, statuses):
        return []

    monkeypatch.setattr(mf, "_fetch_paged", fake_paged)
    monkeypatch.setattr(mf, "_fetch_paged_all_statuses", fake_all_statuses)
    return state


def test_ad_ids_are_sent_to_meta_as_a_filter(graph):
    mf.fetch_meta_insights_live("tok", ACCOUNT, date_from="2026-10-01", date_to="2026-10-15",
                                keys=["spend"], ad_ids={"1", "2"})
    filtering = json.loads(graph["insight_calls"][-1]["filtering"])
    # The status filter beside it keeps archived ads in (see test_meta_ads_fields).
    assert filtering[0] == {"field": "ad.id", "operator": "IN", "value": ["1", "2"]}


def test_no_ad_ids_filters_only_by_status(graph):
    mf.fetch_meta_insights_live("tok", ACCOUNT, date_from="2026-10-01", date_to="2026-10-15",
                                keys=["spend"], ad_ids=None)
    filtering = json.loads(graph["insight_calls"][-1]["filtering"])
    # Every status, so archived and deleted ads that spent in the range still come back.
    assert [f["field"] for f in filtering] == ["ad.effective_status"]
