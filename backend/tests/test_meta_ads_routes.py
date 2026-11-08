"""Routes for Anril tracking per ad, the all-ads view and the Meta sync start date."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.routes import inbound_leads
from app.services import meta_ads_insights_sync as sync
from tests.fake_supabase import FakeSupabase

ACCOUNT = "act_111"


def _today():
    return datetime.now(timezone.utc).date()


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    fake.add("app_settings", tenant_id="t1", key="meta_ads_account_id", value=ACCOUNT)
    fake.add("ad_creatives", id="ad-1", tenant_id="t1", meta_ad_account_id=ACCOUNT,
             is_click_to_whatsapp=True, tracked_in_anril=True, meta_ad_id="m1",
             messaging_channels=["whatsapp", "instagram"], creative_label="One")
    monkeypatch.setattr(inbound_leads, "get_supabase", lambda: fake)
    return fake


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
    app.dependency_overrides[get_tenant_id] = lambda: "t1"
    app.dependency_overrides[get_tenant_and_role] = lambda: {
        "tenant_id": "t1", "role": "owner", "permissions": [],
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_patch_tracking_404_when_ad_is_missing(client, db):
    res = client.patch("/api/v1/inbound-leads/ad-creatives/nope/tracking", json={"tracked": False})
    assert res.status_code == 404
    assert res.json()["detail"] == "Ad not found"


def test_patch_tracking_updates_the_ad_and_echoes_the_flag(client, db):
    res = client.patch("/api/v1/inbound-leads/ad-creatives/ad-1/tracking", json={"tracked": False})
    assert res.status_code == 200
    assert res.json() == {"ad_creative_id": "ad-1", "tracked": False}
    assert db.rows("ad_creatives")[0]["tracked_in_anril"] is False


def test_patch_tracking_does_not_touch_another_tenants_ad(client, db):
    db.add("ad_creatives", id="ad-other", tenant_id="t2", meta_ad_account_id=ACCOUNT,
           is_click_to_whatsapp=True, tracked_in_anril=True)
    res = client.patch("/api/v1/inbound-leads/ad-creatives/ad-other/tracking", json={"tracked": False})
    assert res.status_code == 404
    other = next(r for r in db.rows("ad_creatives") if r["id"] == "ad-other")
    assert other["tracked_in_anril"] is True


@pytest.fixture
def sync_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(sync, "sync_tenant_ad_insights", lambda *args: calls.append(args))
    return calls


def test_put_sync_start_rejects_a_future_date(client, db, sync_calls):
    future = (_today() + timedelta(days=3)).isoformat()
    res = client.put("/api/v1/inbound-leads/meta-ads/sync-start", json={"start_date": future})
    assert res.status_code == 400
    assert res.json()["detail"] == "Pick a date that isn't in the future"
    assert sync_calls == []


def test_put_sync_start_rejects_a_date_older_than_meta_history(client, db, sync_calls):
    too_old = (_today() - timedelta(days=sync._MAX_HISTORY_DAYS + 30)).isoformat()
    res = client.put("/api/v1/inbound-leads/meta-ads/sync-start", json={"start_date": too_old})
    assert res.status_code == 400
    assert "37 months" in res.json()["detail"]
    assert sync_calls == []


def test_put_sync_start_rejects_a_malformed_date(client, db, sync_calls):
    res = client.put("/api/v1/inbound-leads/meta-ads/sync-start", json={"start_date": "soon"})
    assert res.status_code == 400
    assert sync_calls == []


def test_put_sync_start_saves_the_date_and_schedules_a_resync(client, db, sync_calls):
    chosen = (_today() - timedelta(days=30)).isoformat()
    res = client.put("/api/v1/inbound-leads/meta-ads/sync-start", json={"start_date": chosen})

    assert res.status_code == 200
    body = res.json()
    assert body["start_date"] == chosen
    assert body["syncing"] is True
    assert body["max_history_days"] == sync._MAX_HISTORY_DAYS
    saved = [r for r in db.rows("app_settings") if r["key"] == "meta_ads_sync_start_date"]
    assert [r["value"] for r in saved] == [chosen]
    # BackgroundTasks run before TestClient returns, so the re-sync has been scheduled by now.
    assert len(sync_calls) == 1
    assert sync_calls[0][1] == "t1"


def test_get_sync_start_reports_the_accounts_first_ad_even_if_it_was_off(client, db, sync_calls):
    # The "Data from" floor is the account's first ad ever, so a client can go back
    # to it: All ads shows an ad that was already off at connect (m3) for its dates.
    db.add("meta_ad_registry", tenant_id="t1", meta_ad_account_id=ACCOUNT, meta_ad_id="m1",
           eligible=True, ad_created_time="2026-03-14T10:00:00+00:00")
    db.add("meta_ad_registry", tenant_id="t1", meta_ad_account_id=ACCOUNT, meta_ad_id="m2",
           eligible=True, ad_created_time="2026-02-01T08:00:00+00:00")
    db.add("meta_ad_registry", tenant_id="t1", meta_ad_account_id=ACCOUNT, meta_ad_id="m3",
           eligible=False, ad_created_time="2025-12-01T08:00:00+00:00")
    # A previously connected account's ads never count.
    db.add("meta_ad_registry", tenant_id="t1", meta_ad_account_id="act_old", meta_ad_id="m4",
           eligible=True, ad_created_time="2024-01-01T08:00:00+00:00")

    body = client.get("/api/v1/inbound-leads/meta-ads/sync-start").json()

    assert body["earliest_ad_start"] == "2025-12-01"
    assert body["start_date"] is None
    assert body["max_history_days"] == sync._MAX_HISTORY_DAYS


def test_all_ads_rejects_an_unknown_breakdown(client, db):
    res = client.get("/api/v1/inbound-leads/meta-ads/all-ads?breakdown=not_a_breakdown")
    assert res.status_code == 400


def test_all_ads_rejects_a_reversed_date_range(client, db):
    res = client.get("/api/v1/inbound-leads/meta-ads/all-ads?date_from=2026-10-10&date_to=2026-10-01")
    assert res.status_code == 400


def test_all_ads_rejects_a_malformed_date(client, db):
    res = client.get("/api/v1/inbound-leads/meta-ads/all-ads?date_from=10%2F01%2F2026")
    assert res.status_code == 400


def test_ad_performance_csv_splits_messages_per_chat_app(client, db):
    import csv
    import io

    for lead_id, channel in [("L1", "whatsapp"), ("L2", "whatsapp"), ("L3", "instagram")]:
        db.add("leads", id=lead_id, tenant_id="t1", segment="B")
        db.add("lead_meta_ad_attributions", tenant_id="t1", meta_ad_account_id=ACCOUNT,
               lead_id=lead_id, meta_ad_id="m1", channel=channel)

    res = client.get("/api/v1/inbound-leads/ad-performance/export")

    assert res.status_code == 200
    table = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    header, row = table[0], table[1]
    cell = dict(zip(header, row))
    assert "WhatsApp clicks" not in header
    assert cell["Chat clicks"] == "0"
    assert cell["Messages sent (Anril confirmed)"] == "3"
    assert cell["WhatsApp messages"] == "2"
    assert cell["Instagram messages"] == "1"
    assert cell["Messenger messages"] == "0"
    assert header.index("WhatsApp messages") == header.index("Messages sent (Anril confirmed)") + 1
