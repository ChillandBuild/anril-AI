from datetime import date, timedelta

import pytest

from app.services.meta_ads_insights_sync import (
    _date_chunks,
    _select_rows,
    compute_sync_since,
    is_click_to_whatsapp_adset,
    is_messaging_adset,
    is_multi_destination,
    messaging_channels_for,
    normalize_account_id,
    refresh_ad_registry,
    upsert_creative_from_insight,
    sync_tenant_ad_insights_verbose,
)


def test_normalize_account_id_adds_prefix():
    assert normalize_account_id("1910086849857231") == "act_1910086849857231"


def test_normalize_account_id_keeps_prefix():
    assert normalize_account_id("act_1910086849857231") == "act_1910086849857231"


def test_normalize_account_id_strips_whitespace():
    assert normalize_account_id("  act_123 ") == "act_123"


def test_whatsapp_destinations_are_included():
    assert is_click_to_whatsapp_adset({"destination_type": "WHATSAPP"}) is True
    assert is_click_to_whatsapp_adset({
        "destination_type": "MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP",
    }) is True
    assert is_click_to_whatsapp_adset({"destination_type": "ON_AD"}) is False
    assert is_click_to_whatsapp_adset({"destination_type": "WEBSITE"}) is False
    assert is_click_to_whatsapp_adset({"destination_type": None}) is False
    assert is_click_to_whatsapp_adset(None) is False


def test_is_multi_destination_means_more_than_one_chat_app():
    assert is_multi_destination("MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP") is True
    assert is_multi_destination("MESSAGING_MESSENGER_WHATSAPP") is True
    assert is_multi_destination("MESSAGING_INSTAGRAM_DIRECT_MESSENGER") is True
    assert is_multi_destination("WHATSAPP") is False
    assert is_multi_destination("MESSENGER") is False
    assert is_multi_destination("INSTAGRAM_DIRECT") is False
    assert is_multi_destination("WEBSITE") is False
    assert is_multi_destination(None) is False


@pytest.mark.parametrize("destination_type, channels", [
    ("WHATSAPP", ["whatsapp"]),
    ("MESSENGER", ["messenger"]),
    ("INSTAGRAM_DIRECT", ["instagram"]),
    ("MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP", ["whatsapp", "instagram", "messenger"]),
    ("MESSAGING_INSTAGRAM_DIRECT_MESSENGER", ["instagram", "messenger"]),
    ("INSTAGRAM_PROFILE", []),
    ("WEBSITE", []),
    ("ON_AD", []),
    (None, []),
])
def test_messaging_channels_for_destinations(destination_type, channels):
    assert messaging_channels_for(destination_type) == channels


def test_messaging_ad_sets_are_any_chat_app_destination():
    assert is_messaging_adset({"destination_type": "INSTAGRAM_DIRECT"}) is True
    assert is_messaging_adset({"destination_type": "MESSENGER"}) is True
    assert is_messaging_adset({"destination_type": "WHATSAPP"}) is True
    assert is_messaging_adset({"destination_type": "INSTAGRAM_PROFILE"}) is False
    assert is_messaging_adset({"destination_type": "ON_AD"}) is False
    assert is_messaging_adset(None) is False


def test_unique_reach_uses_one_meta_window_per_ad(monkeypatch):
    import app.services.meta_ads_insights_sync as mod

    requests = []

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"data": [{"ad_id": "A1", "reach": "17309"}]}

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, params):
            requests.append((url, params))
            return FakeResponse()

    monkeypatch.setattr(mod.httpx, "Client", FakeClient)

    result = mod.fetch_unique_reach_by_ad(
        "token", "act_1", date_from="2026-07-03", date_to="2026-08-01",
    )

    assert result == {"A1": 17309}
    assert requests[0][1]["time_range"] == '{"since": "2026-07-03", "until": "2026-08-01"}'


class FakeTable:
    def __init__(self, store, name):
        self.store, self.name, self._filters, self._payload = store, name, {}, None
        self._op = None
        self._single = False

    def select(self, *a): self._op = "select"; return self
    def eq(self, k, v): self._filters[k] = v; return self
    def in_(self, k, v): self._filters[k] = ("in", v); return self
    def limit(self, n): return self
    def maybe_single(self): self._single = True; return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload; return self

    def update(self, payload):
        self._op, self._payload = "update", payload; return self

    def upsert(self, payload, on_conflict=None):
        self._op, self._payload, self._on_conflict = "upsert", payload, on_conflict; return self

    def _matches(self, r):
        for k, v in self._filters.items():
            if isinstance(v, tuple) and v[0] == "in":
                if r.get(k) not in v[1]:
                    return False
            elif r.get(k) != v:
                return False
        return True

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self._op == "select":
            match = [r for r in rows if self._matches(r)]
            class R: data = (match[0] if match else None) if self._single else match
            return R()
        if self._op == "insert":
            row = dict(self._payload); row.setdefault("id", f"cr-{len(rows)+1}")
            rows.append(row)
            class R: data = [row]
            return R()
        if self._op == "update":
            touched = []
            for r in rows:
                if self._matches(r):
                    r.update(self._payload)
                    touched.append(r)
            # PostgREST returns the updated rows (supabase-py sends
            # Prefer: return=representation), so the fake does too.
            class R: data = touched
            return R()
        if self._op == "upsert":
            key_cols = (self._on_conflict or "id").split(",")
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            for payload in payloads:
                existing = next(
                    (r for r in rows if all(r.get(k) == payload.get(k) for k in key_cols)),
                    None,
                )
                if existing:
                    existing.update(payload)
                else:
                    rows.append(dict(payload))
            class R: data = payloads
            return R()
        class R: data = []
        return R()


class FakeDB:
    def __init__(self): self.store = {}
    def table(self, name): return FakeTable(self.store, name)


def test_upsert_creative_inserts_then_reuses(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    db = FakeDB()
    row = {
        "ad_id": "23857950447780795", "ad_name": "Clarity",
        "adset_id": "as1", "adset_name": "Astro Video",
        "campaign_id": "c1", "campaign_name": "Astro Video",
    }
    first = upsert_creative_from_insight(db, "t1", row)
    second = upsert_creative_from_insight(db, "t1", row)
    assert first == second
    assert len(db.store["ad_creatives"]) == 1
    assert db.store["ad_creatives"][0]["creative_label"] == "Clarity"
    assert db.store["ad_creatives"][0]["campaign_id"] == "camp-1"


def test_upsert_creative_does_not_overwrite_edited_label(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    db = FakeDB()
    db.store["ad_creatives"] = [{
        "id": "cr-1", "tenant_id": "t1", "meta_ad_id": "A1",
        "creative_label": "My Renamed", "label_edited": True,
    }]
    upsert_creative_from_insight(db, "t1", {
        "ad_id": "A1", "ad_name": "Original Meta Name",
        "adset_id": "as1", "adset_name": "Set", "campaign_id": "c1", "campaign_name": "Camp",
    })
    assert db.store["ad_creatives"][0]["creative_label"] == "My Renamed"


def test_verbose_sync_reports_missing_credentials():
    db = FakeDB()
    result = sync_tenant_ad_insights_verbose(db, "t1")
    assert result["ok"] is False
    assert "credentials" in result["error"].lower() or "token" in result["error"].lower()
    assert result["written"] == 0


def test_verbose_sync_reports_fetch_failure(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    db = FakeDB()
    db.store["app_settings"] = [
        {"tenant_id": "t1", "key": "meta_ads_access_token", "value": "tok"},
        {"tenant_id": "t1", "key": "meta_ads_account_id", "value": "act_1"},
    ]
    def boom(*a, **k):
        raise RuntimeError("Meta 400: Missing Permissions")
    monkeypatch.setattr(mod, "_fetch_insights", boom)
    result = sync_tenant_ad_insights_verbose(db, "t1")
    assert result["ok"] is False
    assert "Missing Permissions" in result["error"]
    assert result["written"] == 0


def test_verbose_sync_writes_and_reports_success(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    db = FakeDB()
    db.store["app_settings"] = [
        {"tenant_id": "t1", "key": "meta_ads_access_token", "value": "tok"},
        {"tenant_id": "t1", "key": "meta_ads_account_id", "value": "act_1"},
    ]
    fake_rows = [{
        "ad_id": "A1", "ad_name": "Clarity", "adset_id": "as1", "adset_name": "Set",
        "campaign_id": "c1", "campaign_name": "Camp",
        "clicks": "5", "inline_link_clicks": "4", "spend": "10.0", "date_start": "2026-07-20",
    }]
    monkeypatch.setattr(mod, "_fetch_insights", lambda *a, **k: fake_rows)
    monkeypatch.setattr(mod, "_fetch_ads", lambda *a, **k: [{
        "id": "A1", "adset_id": "as1", "campaign_id": "c1",
        "effective_status": "ACTIVE", "created_time": "2026-07-01T10:00:00+0000",
    }])
    monkeypatch.setattr(mod, "_fetch_adsets", lambda *a, **k: [{
        "id": "as1",
        "name": "Set",
        "destination_type": "WHATSAPP",
        "optimization_goal": "CONVERSATIONS",
        "effective_status": "ACTIVE",
        "daily_budget": "80000",
    }])
    # Campaign metadata enrichment is a separate Meta call — mock it so the
    # unit test stays hermetic (no live Graph API request).
    monkeypatch.setattr(mod, "_fetch_campaigns", lambda *a, **k: [])
    result = sync_tenant_ad_insights_verbose(db, "t1")
    assert result["ok"] is True
    assert result["error"] is None
    assert result["rows_fetched"] == 1
    assert result["whatsapp_rows"] == 1
    assert result["skipped_non_whatsapp"] == 0
    assert result["written"] == 1
    assert len(db.store["ad_insights_daily"]) == 1
    assert db.store["ad_insights_daily"][0]["meta_ad_account_id"] == "act_1"
    assert db.store["ad_creatives"][0]["is_click_to_whatsapp"] is True
    assert db.store["ad_sets"][0]["meta_ad_account_id"] == "act_1"
    assert db.store["ad_sets"][0]["daily_budget"] == 800.0


def test_verbose_sync_includes_today_live_delivery(monkeypatch):
    import app.services.meta_ads_insights_sync as mod

    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    db = FakeDB()
    db.store["app_settings"] = [
        {"tenant_id": "t1", "key": "meta_ads_access_token", "value": "tok"},
        {"tenant_id": "t1", "key": "meta_ads_account_id", "value": "act_1"},
    ]
    presets = []

    def fetch_insights(_token, _account, preset):
        presets.append(preset)
        return [{
            "ad_id": "A1", "ad_name": "Clarity", "adset_id": "as1", "adset_name": "Set",
            "campaign_id": "c1", "campaign_name": "Camp", "date_start": "2026-08-02",
        }] if preset == "last_30d" else [{
            "ad_id": "A1", "ad_name": "Clarity", "adset_id": "as1", "adset_name": "Set",
            "campaign_id": "c1", "campaign_name": "Camp", "date_start": "2026-08-03",
        }]

    monkeypatch.setattr(mod, "_fetch_insights", fetch_insights)
    monkeypatch.setattr(mod, "_fetch_ads", lambda *a, **k: [{
        "id": "A1", "adset_id": "as1", "campaign_id": "c1",
        "effective_status": "ACTIVE", "created_time": "2026-07-01T10:00:00+0000",
    }])
    monkeypatch.setattr(mod, "_fetch_adsets", lambda *a, **k: [{
        "id": "as1", "destination_type": "WHATSAPP",
    }])
    monkeypatch.setattr(mod, "_fetch_campaigns", lambda *a, **k: [])

    result = sync_tenant_ad_insights_verbose(db, "t1")

    assert result["ok"] is True
    assert presets == ["last_30d", "today"]
    assert result["rows_fetched"] == 2
    assert result["written"] == 2
    assert {row["insight_date"] for row in db.store["ad_insights_daily"]} == {
        "2026-08-02", "2026-08-03",
    }


def test_verbose_sync_keeps_multi_destination_and_skips_other_ads(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    db = FakeDB()
    db.store["app_settings"] = [
        {"tenant_id": "t1", "key": "meta_ads_access_token", "value": "tok"},
        {"tenant_id": "t1", "key": "meta_ads_account_id", "value": "act_1"},
    ]
    monkeypatch.setattr(mod, "_fetch_insights", lambda *a, **k: [
        {"ad_id": "A1", "adset_id": "as1", "campaign_id": "c1", "date_start": "2026-07-20"},
        {"ad_id": "A2", "adset_id": "as2", "campaign_id": "c1", "date_start": "2026-07-20"},
        {"ad_id": "A3", "adset_id": "as3", "campaign_id": "c1", "date_start": "2026-07-20"},
    ])
    monkeypatch.setattr(mod, "_fetch_adsets", lambda *a, **k: [
        {"id": "as1", "destination_type": "WEBSITE"},
        {"id": "as2", "destination_type": "ON_AD"},
        {"id": "as3", "destination_type": "MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP"},
    ])
    monkeypatch.setattr(mod, "_fetch_ads", lambda *a, **k: [
        {"id": "A1", "adset_id": "as1", "campaign_id": "c1", "effective_status": "ACTIVE",
         "created_time": "2026-07-01T10:00:00+0000"},
        {"id": "A2", "adset_id": "as2", "campaign_id": "c1", "effective_status": "ACTIVE",
         "created_time": "2026-07-01T10:00:00+0000"},
        {"id": "A3", "adset_id": "as3", "campaign_id": "c1", "effective_status": "ACTIVE",
         "created_time": "2026-07-01T10:00:00+0000"},
    ])
    monkeypatch.setattr(mod, "_fetch_campaigns", lambda *a, **k: [])

    result = sync_tenant_ad_insights_verbose(db, "t1")

    assert result["ok"] is True
    assert result["rows_fetched"] == 3
    assert result["whatsapp_rows"] == 1
    assert result["skipped_non_whatsapp"] == 2
    assert result["written"] == 1
    assert [r["meta_ad_id"] for r in db.store["ad_creatives"]] == ["A3"]


# --- Ad registry (eligibility) -------------------------------------------------

def _registry_db(*, connected_at=None, snapshot_account=None, registry_rows=()):
    db = FakeDB()
    settings = []
    if connected_at:
        settings.append({"tenant_id": "t1", "key": "meta_ads_connected_at", "value": connected_at})
    if snapshot_account:
        settings.append({"tenant_id": "t1", "key": "meta_ads_join_snapshot_account", "value": snapshot_account})
    db.store["app_settings"] = settings
    db.store["meta_ad_registry"] = [dict(r) for r in registry_rows]
    return db


def _ad(ad_id, status, created, adset_id="as1"):
    return {
        "id": ad_id, "adset_id": adset_id, "campaign_id": "c1",
        "effective_status": status, "created_time": created,
    }


def test_registry_snapshot_mode_takes_active_ads_and_recent_ones():
    db = _registry_db(connected_at="2026-08-01T00:00:00+00:00")
    ads = [
        _ad("OLD_ACTIVE", "ACTIVE", "2026-07-01T10:00:00+0000"),
        _ad("OLD_PAUSED", "PAUSED", "2026-07-01T10:00:00+0000"),
        _ad("NEW_PAUSED", "PAUSED", "2026-08-10T10:00:00+0530"),
    ]
    adsets = [{"id": "as1", "destination_type": "WHATSAPP"}]

    eligible = refresh_ad_registry(db, "t1", "act_1", ads, adsets)

    assert eligible == {"OLD_ACTIVE": "2026-07-01", "NEW_PAUSED": "2026-08-10"}
    by_ad = {r["meta_ad_id"]: r for r in db.store["meta_ad_registry"]}
    assert by_ad["OLD_PAUSED"]["eligible"] is False
    assert by_ad["OLD_ACTIVE"]["status_at_join"] == "ACTIVE"
    assert by_ad["NEW_PAUSED"]["destination_type"] == "WHATSAPP"
    snapshot = [s for s in db.store["app_settings"] if s["key"] == "meta_ads_join_snapshot_account"]
    assert snapshot and snapshot[0]["value"] == "act_1"


def test_registry_later_runs_keep_eligibility_and_skip_old_new_ads():
    db = _registry_db(
        connected_at="2026-08-01T00:00:00+00:00",
        snapshot_account="act_1",
        registry_rows=[{
            "tenant_id": "t1", "meta_ad_id": "OLD", "meta_ad_account_id": "act_1",
            "eligible": True, "status_at_join": "ACTIVE",
            "ad_created_time": "2026-07-01T00:00:00+00:00",
        }],
    )
    ads = [
        _ad("OLD", "PAUSED", "2026-07-01T10:00:00+0000"),
        _ad("FIRST_SEEN", "ACTIVE", "2026-07-15T10:00:00+0000"),
    ]

    eligible = refresh_ad_registry(db, "t1", "act_1", ads, [{"id": "as1", "destination_type": "WHATSAPP"}])

    assert eligible == {"OLD": "2026-07-01"}
    by_ad = {r["meta_ad_id"]: r for r in db.store["meta_ad_registry"]}
    assert by_ad["OLD"]["eligible"] is True
    assert by_ad["FIRST_SEEN"]["eligible"] is False


def test_registry_empty_ads_writes_nothing_and_returns_existing_eligible():
    registry = [
        {"tenant_id": "t1", "meta_ad_id": "A_OLD", "meta_ad_account_id": "act_1",
         "eligible": True, "ad_created_time": "2026-07-01T00:00:00+00:00"},
        {"tenant_id": "t1", "meta_ad_id": "B_NO", "meta_ad_account_id": "act_1",
         "eligible": False, "ad_created_time": "2026-07-01T00:00:00+00:00"},
    ]
    db = _registry_db(registry_rows=registry)

    eligible = refresh_ad_registry(db, "t1", "act_1", [], [])

    assert eligible == {"A_OLD": "2026-07-01"}
    assert db.store["meta_ad_registry"] == registry
    assert db.store.get("app_settings", []) == []


def test_compute_sync_since_clamps_to_37_months():
    today = date(2026, 10, 15)
    assert compute_sync_since(None, today) is None
    assert compute_sync_since("2026-08-01", today) == "2026-08-01"
    floor = today - timedelta(days=1125)
    assert compute_sync_since("2020-01-01", today) == floor.isoformat()


def test_date_chunks_are_contiguous_inclusive_and_at_most_30_days():
    chunks = _date_chunks("2026-08-24", "2026-10-15")
    assert chunks[0][0] == "2026-08-24"
    assert chunks[-1][1] == "2026-10-15"
    for (_, end), (start, _) in zip(chunks, chunks[1:]):
        assert date.fromisoformat(start) == date.fromisoformat(end) + timedelta(days=1)
    for start, end in chunks:
        assert (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 <= 30


def test_select_rows_keeps_every_messaging_ad_set_and_drops_the_rest():
    rows = [
        {"ad_id": "W", "adset_id": "as_wa", "date_start": "2026-08-25"},
        {"ad_id": "M", "adset_id": "as_ms", "date_start": "2026-08-25"},
        {"ad_id": "I", "adset_id": "as_ig", "date_start": "2026-08-25"},
        {"ad_id": "SITE", "adset_id": "as_web", "date_start": "2026-08-25"},
        {"ad_id": "FORM", "adset_id": "as_form", "date_start": "2026-08-25"},
        {"ad_id": "PROFILE", "adset_id": "as_profile", "date_start": "2026-08-25"},
    ]
    adsets = [
        {"id": "as_wa", "destination_type": "WHATSAPP"},
        {"id": "as_ms", "destination_type": "MESSENGER"},
        {"id": "as_ig", "destination_type": "INSTAGRAM_DIRECT"},
        {"id": "as_web", "destination_type": "WEBSITE"},
        {"id": "as_form", "destination_type": "ON_AD"},
        {"id": "as_profile", "destination_type": "INSTAGRAM_PROFILE"},
    ]
    eligible = {ad: None for ad in ("W", "M", "I", "SITE", "FORM", "PROFILE")}

    kept, _ = _select_rows(rows, adsets, eligible, None)

    assert sorted(r["ad_id"] for r in kept) == ["I", "M", "W"]


def test_upsert_creative_stores_messaging_channels_for_an_instagram_only_ad(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    greeting_calls = []
    monkeypatch.setattr(mod, "fetch_prefilled_greeting",
                        lambda token, ad_id: greeting_calls.append(ad_id) or "hi")
    db = FakeDB()
    row = {"ad_id": "IG1", "ad_name": "Insta ad", "adset_id": "as_ig",
           "adset_name": "IG set", "campaign_id": "c1", "campaign_name": "Camp"}
    adset = {"id": "as_ig", "name": "IG set", "destination_type": "INSTAGRAM_DIRECT"}

    upsert_creative_from_insight(db, "t1", row, adset_meta=adset, token="tok")

    stored = db.store["ad_creatives"][0]
    assert stored["messaging_channels"] == ["instagram"]
    assert stored["is_click_to_whatsapp"] is False
    assert stored["cta_type"] is None
    assert greeting_calls == []


def test_upsert_creative_refreshes_messaging_channels_on_update(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    monkeypatch.setattr(mod, "fetch_prefilled_greeting", lambda token, ad_id: None)
    db = FakeDB()
    db.store["ad_creatives"] = [{
        "id": "cr-1", "tenant_id": "t1", "meta_ad_id": "M1", "label_edited": False,
        "messaging_channels": [], "prefilled_greeting_text": "already set",
    }]
    row = {"ad_id": "M1", "ad_name": "Messenger ad", "adset_id": "as_ms", "campaign_id": "c1"}
    adset = {"id": "as_ms", "destination_type": "MESSAGING_INSTAGRAM_DIRECT_MESSENGER"}

    upsert_creative_from_insight(db, "t1", row, adset_meta=adset, token="tok")

    assert db.store["ad_creatives"][0]["messaging_channels"] == ["instagram", "messenger"]


def test_select_rows_applies_since_and_eligibility():
    rows = [
        {"ad_id": "A1", "adset_id": "as1", "date_start": "2026-06-30"},
        {"ad_id": "A1", "adset_id": "as1", "date_start": "2026-08-24"},
        {"ad_id": "A2", "adset_id": "as1", "date_start": "2026-08-25"},
    ]
    adsets = [{"id": "as1", "destination_type": "WHATSAPP"}]

    kept, adset_by_id = _select_rows(rows, adsets, {"A1": "2026-08-24"}, "2026-07-01")

    assert [r["date_start"] for r in kept] == ["2026-08-24"]
    assert adset_by_id["as1"]["destination_type"] == "WHATSAPP"


def test_failed_ads_fetch_still_syncs_known_eligible_ads(monkeypatch):
    """Breaks if a flaky /ads call blanks the whole sync instead of falling back."""
    import app.services.meta_ads_insights_sync as sync

    def boom(*_a, **_k):
        raise RuntimeError("ads edge down")

    monkeypatch.setattr(sync, "_fetch_ads", boom)
    assert sync._fetch_ads_best_effort("tok", "act_1", "t1") == []


# --- Ad-level delivery status (fix for stale "Active" on deleted ads) ---------
#
# The dashboard's Delivery column used to render the *campaign's* status. An ad
# deleted in Ads Manager stopped coming back from Meta, the update-only sync
# never touched its row again, and it kept showing Active indefinitely.


def _creative(cid, ad_id, status="ACTIVE", tenant="t1", account="act_1"):
    return {
        "id": cid, "tenant_id": tenant, "meta_ad_id": ad_id,
        "meta_ad_account_id": account, "ad_effective_status": status,
    }


def test_fetch_ads_asks_meta_for_deleted_and_archived():
    """Meta's /ads edge hides DELETED/ARCHIVED unless the request names them."""
    import app.services.meta_ads_insights_sync as mod
    import json as _json

    captured = {}

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"data": [{"id": "A1", "effective_status": "DELETED"}]}

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, params):
            captured["url"], captured["params"] = url, params
            return FakeResponse()

    import unittest.mock as _mock
    with _mock.patch.object(mod.httpx, "Client", FakeClient):
        ads = mod._fetch_ads("token", "act_1")

    assert ads == [{"id": "A1", "effective_status": "DELETED"}]
    assert captured["url"].endswith("/act_1/ads")
    clause = _json.loads(captured["params"]["filtering"])[0]
    assert clause["field"] == "ad.effective_status"
    assert "DELETED" in clause["value"] and "ARCHIVED" in clause["value"]


def test_fetch_all_statuses_falls_back_when_meta_rejects_the_filter():
    """A rejected filter must not take the whole sync down with it."""
    import app.services.meta_ads_insights_sync as mod
    import httpx as _httpx

    calls = []

    def fake_paged(url, params):
        calls.append(params)
        if "filtering" in params:
            request = _httpx.Request("GET", url)
            response = _httpx.Response(400, text="unsupported filter", request=request)
            raise _httpx.HTTPStatusError("400", request=request, response=response)
        return [{"id": "A1"}]

    import unittest.mock as _mock
    with _mock.patch.object(mod, "_fetch_paged", fake_paged):
        out = mod._fetch_paged_all_statuses(
            "http://x/ads", {"fields": "id"},
            status_field="ad.effective_status", statuses=["ACTIVE", "DELETED"],
        )

    assert out == [{"id": "A1"}]
    assert len(calls) == 2 and "filtering" not in calls[1]


def test_delivery_status_writes_each_ads_own_status():
    import app.services.meta_ads_insights_sync as mod
    db = FakeDB()
    db.store["ad_creatives"] = [
        _creative("cr-1", "A1"), _creative("cr-2", "A2"), _creative("cr-3", "A3"),
    ]

    result = mod.sync_ad_delivery_status(
        db, "t1", "token", "act_1",
        ads=[
            {"id": "A1", "effective_status": "ACTIVE"},
            {"id": "A2", "effective_status": "PAUSED"},
            {"id": "A3", "effective_status": "DELETED"},
        ],
    )

    by_id = {r["id"]: r for r in db.store["ad_creatives"]}
    assert by_id["cr-1"]["ad_effective_status"] == "ACTIVE"
    assert by_id["cr-2"]["ad_effective_status"] == "PAUSED"
    assert by_id["cr-3"]["ad_effective_status"] == "DELETED"
    assert all(r.get("last_seen_at") for r in db.store["ad_creatives"])
    assert result["reconciled"] is True and result["marked_deleted"] == 0


def test_ad_missing_from_meta_is_marked_deleted():
    """The reported bug: the ad is gone from Ads Manager, so Meta stops
    returning it entirely -- not even with DELETED in the status filter."""
    import app.services.meta_ads_insights_sync as mod
    db = FakeDB()
    db.store["ad_creatives"] = [_creative("cr-1", "A1"), _creative("cr-2", "GONE")]

    result = mod.sync_ad_delivery_status(
        db, "t1", "token", "act_1",
        ads=[{"id": "A1", "effective_status": "ACTIVE"}],
    )

    by_id = {r["id"]: r for r in db.store["ad_creatives"]}
    assert by_id["cr-1"]["ad_effective_status"] == "ACTIVE"
    assert by_id["cr-2"]["ad_effective_status"] == "DELETED"
    assert result["marked_deleted"] == 1


def test_empty_ads_response_does_not_mark_everything_deleted():
    """An empty edge is a failed/denied fetch far more often than an empty
    account. Marking the tenant's whole table DELETED on that would be worse
    than the stale status this fix replaces."""
    import app.services.meta_ads_insights_sync as mod
    db = FakeDB()
    db.store["ad_creatives"] = [_creative("cr-1", "A1")]

    result = mod.sync_ad_delivery_status(db, "t1", "token", "act_1", ads=[])

    assert db.store["ad_creatives"][0]["ad_effective_status"] == "ACTIVE"
    assert result["reconciled"] is False and result["marked_deleted"] == 0


def test_other_tenants_creatives_are_untouched():
    import app.services.meta_ads_insights_sync as mod
    db = FakeDB()
    db.store["ad_creatives"] = [
        _creative("cr-1", "A1"),
        _creative("cr-2", "B1", tenant="t2"),
    ]

    mod.sync_ad_delivery_status(db, "t1", "token", "act_1", ads=[{"id": "A1", "effective_status": "PAUSED"}])

    by_id = {r["id"]: r for r in db.store["ad_creatives"]}
    assert by_id["cr-1"]["ad_effective_status"] == "PAUSED"
    assert by_id["cr-2"]["ad_effective_status"] == "ACTIVE"
    assert by_id["cr-2"].get("last_seen_at") is None


# ─── "Connection expired" flag (Graph error code 190) ──────────────────────────

def _graph_error(code, message="Error validating access token"):
    import httpx
    req = httpx.Request("GET", "https://graph.facebook.com/v21.0/act_1/insights")
    resp = httpx.Response(400, json={"error": {"message": message, "type": "OAuthException", "code": code}}, request=req)
    return httpx.HTTPStatusError("400 Bad Request", request=req, response=resp)


def _creds_db():
    db = FakeDB()
    db.store["app_settings"] = [
        {"tenant_id": "t1", "key": "meta_ads_access_token", "value": "tok"},
        {"tenant_id": "t1", "key": "meta_ads_account_id", "value": "act_1"},
    ]
    return db


def _flag(db):
    return next((r["value"] for r in db.store["app_settings"]
                 if r["tenant_id"] == "t1" and r["key"] == "meta_ads_token_expired"), None)


def test_is_token_expired_error_reads_graph_code_190():
    from app.services.meta_ads_insights_sync import is_token_expired_error
    assert is_token_expired_error(_graph_error(190)) is True
    assert is_token_expired_error(_graph_error(100, "Invalid parameter")) is False
    assert is_token_expired_error(RuntimeError("boom")) is False


def test_verbose_sync_flags_an_expired_token(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    db = _creds_db()
    def expired(*a, **k):
        raise _graph_error(190)
    monkeypatch.setattr(mod, "_fetch_insights", expired)
    result = sync_tenant_ad_insights_verbose(db, "t1")
    assert result["ok"] is False and result["token_expired"] is True
    assert _flag(db) == "1"


def test_verbose_sync_does_not_flag_other_meta_errors(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    db = _creds_db()
    def other(*a, **k):
        raise _graph_error(100, "Invalid parameter")
    monkeypatch.setattr(mod, "_fetch_insights", other)
    result = sync_tenant_ad_insights_verbose(db, "t1")
    assert result["ok"] is False and result["token_expired"] is False
    assert _flag(db) is None


def test_background_sync_flags_an_expired_token_and_returns_zero(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    db = _creds_db()
    def expired(*a, **k):
        raise _graph_error(190)
    monkeypatch.setattr(mod, "_fetch_insights", expired)
    assert mod.sync_tenant_ad_insights(db, "t1") == 0
    assert _flag(db) == "1"


def test_a_good_sync_clears_the_expired_flag(monkeypatch):
    import app.services.meta_ads_insights_sync as mod
    monkeypatch.setattr(mod, "get_or_create_campaign", lambda **k: {"id": "camp-1"})
    db = _creds_db()
    db.store["app_settings"].append({"tenant_id": "t1", "key": "meta_ads_token_expired", "value": "1"})
    monkeypatch.setattr(mod, "_fetch_insights", lambda *a, **k: [])
    monkeypatch.setattr(mod, "_fetch_ads", lambda *a, **k: [])
    monkeypatch.setattr(mod, "_fetch_adsets", lambda *a, **k: [])
    monkeypatch.setattr(mod, "_fetch_campaigns", lambda *a, **k: [])
    result = sync_tenant_ad_insights_verbose(db, "t1")
    assert result["ok"] is True
    assert _flag(db) == ""
    assert mod.get_ads_setting(db, "t1", "meta_ads_token_expired") is None


def test_sync_start_payload_carries_the_flag():
    from app.routes.inbound_leads import _sync_start_payload
    db = _creds_db()
    assert _sync_start_payload(db, "t1")["token_expired"] is False
    db.store["app_settings"].append({"tenant_id": "t1", "key": "meta_ads_token_expired", "value": "1"})
    assert _sync_start_payload(db, "t1")["token_expired"] is True


@pytest.mark.asyncio
async def test_reconnecting_meta_ads_clears_the_expired_flag():
    from unittest.mock import MagicMock, patch
    from app.routes.app_settings import activate_channel, ActivateChannelRequest

    class _Resp:
        def json(self):
            return {"id": "act_1", "name": "Shop ads", "currency": "INR", "timezone_name": "Asia/Kolkata", "account_status": 1}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    db = MagicMock()
    with patch("app.routes.app_settings.get_supabase", return_value=db), \
         patch("app.routes.app_settings._get_setting_value", return_value="act_1"), \
         patch("app.routes.app_settings.httpx.AsyncClient", lambda *a, **k: _Client()), \
         patch("app.routes.app_settings.record_audit_event"):
        await activate_channel(
            ActivateChannelRequest(channel="meta_ads"),
            ctx={"tenant_id": "t1"}, user={"user_id": "u1"},
        )
    rows = {c.args[0]["key"]: c.args[0] for c in db.table.return_value.upsert.call_args_list}
    assert rows["meta_ads_token_expired"]["value"] == ""
    assert rows["meta_ads_token_expired"]["tenant_id"] == "t1"
