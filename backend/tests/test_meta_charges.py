"""Settings > Limits & Meta charges: Meta's own numbers, the AI-replies allowance, the daily limit.
Meta is never called: fetch_pricing is replaced, or httpx is."""
import threading
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import meta_charges
from fake_supabase import FakeSupabase

T1, T2 = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))


def point(category, volume, cost):
    return {"start": 1, "end": 2, "pricing_category": category, "volume": volume, "cost": cost}


def meta_body(points, currency="INR"):
    return {"id": "w1", "currency": currency, "pricing_analytics": {"data": [{"data_points": points}]}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    meta_charges.clear_cache()
    settings = {"meta_access_token": "tok", "meta_waba_id": "w1"}
    monkeypatch.setattr(meta_charges, "get_setting", lambda key, fallback=None, tenant_id=None: settings.get(key, fallback))
    yield
    meta_charges.clear_cache()
    app.dependency_overrides.clear()


def run(result):
    return result


def fake_fetch(body, calls=None):
    def fetch(waba_id, token, start, end):
        if calls is not None:
            calls.append((waba_id, token, start, end))
        if isinstance(body, Exception):
            raise body
        return body
    return fetch


# ---------------------------------------------------------------- category mapping and sums

def test_categories_are_mapped_and_summed():
    body = meta_body([
        point("MARKETING", 100, 80.5), point("MARKETING_LITE", 20, 10.25),
        point("UTILITY", 40, 12.0), point("UTILITY", 10, 3.0),
        point("AUTHENTICATION", 300, 150.0), point("AUTHENTICATION_INTERNATIONAL", 5, 20.0),
        point("SERVICE", 500, 0),
    ])
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(body)):
        out = run(meta_charges.get_charges(T1))
    assert out["available"] is True
    rows = {r["key"]: r for r in out["rows"]}
    assert rows["marketing"] == {"key": "marketing", "label": rows["marketing"]["label"], "messages": 120, "cost": 90.75}
    assert rows["utility"]["messages"] == 50 and rows["utility"]["cost"] == 15.0
    assert rows["authentication"]["messages"] == 305 and rows["authentication"]["cost"] == 170.0
    assert rows["service"]["messages"] == 500 and rows["service"]["cost"] == 0.0
    assert [r["key"] for r in out["rows"]] == ["marketing", "utility", "authentication", "service"]
    assert rows["utility"]["label"] == "Update messages: bills, reminders, order updates"
    assert rows["authentication"]["label"] == "OTP codes"
    assert rows["service"]["label"] == "Replies to customers within 24 hours"
    assert out["total"] == {"messages": 975, "cost": 275.75}
    assert out["currency"] == "INR" and out["gst_note"] == "+ GST"


def test_unknown_category_goes_to_other_row_and_counts_in_total():
    body = meta_body([point("UTILITY", 1, 1.0), point("SOMETHING_NEW", 2, 2.5)])
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(body)):
        out = run(meta_charges.get_charges(T1))
    assert out["rows"][-1]["key"] == "other" and out["rows"][-1]["cost"] == 2.5
    assert out["total"]["cost"] == 3.5


def test_no_messages_is_a_real_zero_not_unavailable():
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([]))):
        out = run(meta_charges.get_charges(T1))
    assert out["available"] is True and out["total"] == {"messages": 0, "cost": 0.0}


def test_currency_comes_from_meta():
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([point("UTILITY", 1, 1.0)], currency="USD"))):
        assert run(meta_charges.get_charges(T1))["currency"] == "USD"


def test_cost_hidden_by_meta_is_not_available_never_estimated():
    body = meta_body([{"start": 1, "end": 2, "pricing_category": "UTILITY", "volume": 10}])
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(body)):
        out = run(meta_charges.get_charges(T1))
    assert out == {"available": False, "reason": "Meta hasn't shared this month's charges yet."}


def test_several_wabas_are_summed(monkeypatch):
    settings = {"meta_access_token": "tok", "meta_waba_id": "w1, w2"}
    monkeypatch.setattr(meta_charges, "get_setting", lambda key, fallback=None, tenant_id=None: settings.get(key, fallback))
    calls = []

    def fetch(waba_id, token, start, end):
        calls.append(waba_id)
        return meta_body([point("MARKETING", 10, 5.0)])
    with patch.object(meta_charges, "fetch_pricing", fetch):
        out = run(meta_charges.get_charges(T1))
    assert calls == ["w1", "w2"]
    assert out["total"] == {"messages": 20, "cost": 10.0}


# ---------------------------------------------------------------- cache and failures

def test_second_call_within_the_hour_is_served_from_cache():
    calls = []
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([point("UTILITY", 1, 1.0)]), calls)):
        first = run(meta_charges.get_charges(T1))
        second = run(meta_charges.get_charges(T1))
    assert len(calls) == 1 and first == second


def test_cache_is_per_tenant():
    calls = []
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([]), calls)):
        run(meta_charges.get_charges(T1))
        run(meta_charges.get_charges(T2))
    assert len(calls) == 2


def test_cache_expires_after_an_hour(monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(meta_charges.time, "monotonic", lambda: clock[0])
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([]), calls)):
        run(meta_charges.get_charges(T1))
        clock[0] += 3599
        run(meta_charges.get_charges(T1))
        assert len(calls) == 1
        clock[0] += 2
        run(meta_charges.get_charges(T1))
    assert len(calls) == 2


def test_meta_error_means_not_available():
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(RuntimeError("Meta pricing_analytics failed: token expired"))):
        out = run(meta_charges.get_charges(T1))
    assert out == {"available": False, "reason": "Meta hasn't shared this month's charges yet."}


def test_no_waba_or_no_token_means_not_available_without_calling_meta(monkeypatch):
    calls = []
    for settings in ({"meta_access_token": "tok"}, {"meta_waba_id": "w1"}, {}):
        meta_charges.clear_cache()
        monkeypatch.setattr(meta_charges, "get_setting", lambda key, fallback=None, tenant_id=None, s=settings: s.get(key, fallback))
        with patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([]), calls)):
            assert run(meta_charges.get_charges(T1))["available"] is False
    assert calls == []


def test_http_error_from_meta_is_not_available():
    class Resp:
        status_code = 400
        def json(self):
            return {"error": {"message": "bad token"}}

    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, url, params=None, headers=None, timeout=None):
            assert headers == {"Authorization": "Bearer tok"} and "tok" not in url
            assert 'metric_types(["COST","VOLUME"])' in params["fields"]
            assert 'dimensions(["PRICING_CATEGORY"])' in params["fields"]
            return Resp()
    with patch.object(meta_charges.httpx, "Client", lambda: Client()):
        out = run(meta_charges.get_charges(T1))
    assert out["available"] is False


def test_month_window_is_the_ist_month():
    now = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
    month, start, end = meta_charges.ist_month_window(now)
    assert month == "2026-11"
    assert start == int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
    assert end == int(now.timestamp())


def test_month_window_on_the_1st_early_morning_ist_never_starts_after_it_ends():
    # 02:00 IST on 1 Nov = 20:30 UTC on 31 Oct: the UTC midnight of the "1st" is still in the future.
    now = datetime(2026, 10, 31, 20, 30, tzinfo=timezone.utc)
    month, start, end = meta_charges.ist_month_window(now)
    assert month == "2026-11" and start < end == int(now.timestamp())
    assert end - start == 86400


def test_charges_on_the_1st_early_morning_send_meta_a_valid_window():
    calls = []
    now = datetime(2026, 10, 31, 20, 30, tzinfo=timezone.utc)
    with patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([]), calls)):
        assert run(meta_charges.get_charges(T1, now))["available"] is True
    _, _, start, end = calls[0]
    assert start < end


def test_concurrent_misses_make_one_meta_call():
    calls = []

    def slow_fetch(waba_id, token, start, end):
        calls.append(waba_id)
        time.sleep(0.2)
        return meta_body([point("UTILITY", 1, 1.0)])
    results = []
    with patch.object(meta_charges, "fetch_pricing", slow_fetch):
        threads = [threading.Thread(target=lambda: results.append(meta_charges.get_charges(T1))) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert len(calls) == 1 and len(results) == 5 and all(r["available"] for r in results)


# ---------------------------------------------------------------- AI replies

def db_with_counter(used=None, included=None, tenant=T1):
    db = FakeSupabase()
    if used is not None:
        db.add("tenant_usage_counters", tenant_id=tenant, period=datetime.now(timezone.utc).strftime("%Y-%m"),
               metric="ai_reply", used=used, included=included)
    return db


def test_ai_pct():
    assert meta_charges.ai_replies(db_with_counter(760, 1000), T1) == {"used": 760, "included": 1000, "pct": 76}


def test_ai_pct_is_null_when_no_allowance():
    assert meta_charges.ai_replies(db_with_counter(50, 0), T1) == {"used": 50, "included": None, "pct": None}


def test_ai_with_no_counter_row_is_zero_and_null():
    assert meta_charges.ai_replies(db_with_counter(), T1) == {"used": 0, "included": None, "pct": None}


def test_ai_only_counts_this_tenant():
    db = db_with_counter(900, 1000, tenant=T2)
    assert meta_charges.ai_replies(db, T1)["used"] == 0


def test_ai_missing_table_degrades():
    class Broken:
        def table(self, name):
            raise RuntimeError("relation does not exist")
    assert meta_charges.ai_replies(Broken(), T1) == {"used": 0, "included": None, "pct": None}


# ---------------------------------------------------------------- daily limit

def test_daily_limit_is_the_biggest_tier_of_live_numbers():
    db = FakeSupabase()
    db.add("phone_numbers", tenant_id=T1, status="active", messaging_tier=1000)
    db.add("phone_numbers", tenant_id=T1, status="active", messaging_tier=10000)
    db.add("phone_numbers", tenant_id=T1, status="archived", messaging_tier=100000)
    db.add("phone_numbers", tenant_id=T2, status="active", messaging_tier=100000)
    assert meta_charges.daily_limit(db, T1) == {"tier": 10000, "link": "/dashboard/numbers"}


def test_daily_limit_none_without_numbers():
    assert meta_charges.daily_limit(FakeSupabase(), T1) == {"tier": None, "link": "/dashboard/numbers"}


# ---------------------------------------------------------------- the route

def ctx(tenant=T1, role="caller", perms=()):
    return {"tenant_id": tenant, "role": role, "user_id": "u", "caller_id": None, "permissions": list(perms)}


def call(path, c):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
    app.dependency_overrides[get_tenant_and_role] = lambda: c
    return TestClient(app).get(f"/api/v1/connections{path}")


def test_route_returns_all_three_pieces():
    db = db_with_counter(760, 1000)
    db.add("phone_numbers", tenant_id=T1, status="active", messaging_tier=10000)
    body = meta_body([point("UTILITY", 4, 2.0)])
    with patch("app.routes.connections_overview.get_supabase", return_value=db), \
            patch.object(meta_charges, "fetch_pricing", fake_fetch(body)):
        r = call("/meta-charges", ctx(perms=["settings.view"]))
    assert r.status_code == 200
    data = r.json()
    assert data["charges"]["available"] is True and data["charges"]["total"]["cost"] == 2.0
    assert data["ai_replies"]["pct"] == 76
    assert data["daily_limit"] == {"tier": 10000, "link": "/dashboard/numbers"}


def test_route_allows_manage_and_owner():
    for c in (ctx(perms=["settings.manage"]), ctx(role="owner")):
        with patch("app.routes.connections_overview.get_supabase", return_value=FakeSupabase()), \
                patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([]))):
            assert call("/meta-charges", c).status_code == 200


def test_route_403_without_settings_permission():
    with patch("app.routes.connections_overview.get_supabase", return_value=FakeSupabase()):
        assert call("/meta-charges", ctx(perms=["deals.view", "team.view"])).status_code == 403


def test_route_only_reads_the_callers_tenant():
    db = db_with_counter(900, 1000, tenant=T2)
    db.add("phone_numbers", tenant_id=T2, status="active", messaging_tier=100000)
    with patch("app.routes.connections_overview.get_supabase", return_value=db), \
            patch.object(meta_charges, "fetch_pricing", fake_fetch(meta_body([]))):
        data = call("/meta-charges", ctx(perms=["settings.view"])).json()
    assert data["ai_replies"]["used"] == 0 and data["daily_limit"]["tier"] is None
