from app.services.ad_performance import compute_cost_metrics


def test_cpc_uses_inline_link_clicks():
    row = {"inline_link_clicks": 422, "messages": 38, "qualified": 22,
           "hot": 12, "spend": 3624.79, "revenue": 0}
    out = compute_cost_metrics(row)
    assert round(out["cpc"], 2) == 8.59


def test_cost_per_message_and_hot():
    row = {"inline_link_clicks": 65, "messages": 9, "qualified": 5,
           "hot": 2, "spend": 421.13, "revenue": 0}
    out = compute_cost_metrics(row)
    assert round(out["cost_per_message"], 2) == 46.79
    assert round(out["cost_per_hot"], 2) == 210.56


def test_zero_denominators_do_not_crash():
    row = {"inline_link_clicks": 0, "messages": 0, "qualified": 0,
           "hot": 0, "spend": 0, "revenue": 0}
    out = compute_cost_metrics(row)
    assert out["cpc"] is None
    assert out["cost_per_message"] is None
    assert out["roas"] is None


def test_roas_when_revenue_present():
    row = {"inline_link_clicks": 422, "messages": 38, "qualified": 22,
           "hot": 12, "spend": 4000, "revenue": 10000}
    out = compute_cost_metrics(row)
    assert out["roas"] == 2.5


# --- Delivery-status filter (Meta Ads tab "Delivery" dropdown + CSV export) ---

from app.services.ad_performance import DELIVERY_GROUPS, filter_by_delivery


def _rows():
    return [
        {"creative_label": "Live one", "delivery_status": "ACTIVE"},
        {"creative_label": "Paused above", "delivery_status": "CAMPAIGN_PAUSED"},
        {"creative_label": "Removed", "delivery_status": "ARCHIVED"},
        {"creative_label": "Gone", "delivery_status": "DELETED"},
        {"creative_label": "Rejected", "delivery_status": "DISAPPROVED"},
    ]


def test_no_filter_returns_everything():
    assert len(filter_by_delivery(_rows(), None)) == 5
    assert len(filter_by_delivery(_rows(), "")) == 5


def test_active_excludes_archived_and_paused():
    out = filter_by_delivery(_rows(), "active")
    assert [r["creative_label"] for r in out] == ["Live one"]


def test_paused_covers_campaign_and_adset_level_pauses():
    """An ad whose campaign is paused isn't delivering either -- users reading
    the dashboard don't care which level the pause came from."""
    out = filter_by_delivery(_rows(), "paused")
    assert [r["creative_label"] for r in out] == ["Paused above"]


def test_removed_groups_archived_and_deleted():
    out = filter_by_delivery(_rows(), "removed")
    assert {r["creative_label"] for r in out} == {"Removed", "Gone"}


def test_unknown_key_falls_back_to_unfiltered():
    """A stale bookmark or typo'd query param should show the table, not nothing."""
    assert len(filter_by_delivery(_rows(), "nonsense")) == 5


def test_filter_key_is_case_and_whitespace_tolerant():
    assert len(filter_by_delivery(_rows(), "  Active ")) == 1


def test_rows_with_no_status_are_excluded_by_any_filter():
    rows = [{"creative_label": "Never synced", "delivery_status": None}]
    assert filter_by_delivery(rows, "active") == []
    assert len(filter_by_delivery(rows, None)) == 1


def test_frontend_dropdown_keys_all_exist_server_side():
    """AdPerformanceTab.tsx sends these keys with the CSV export request; a key
    missing here would silently return an unfiltered download."""
    for key in ("active", "paused", "archived", "deleted", "issues"):
        assert key in DELIVERY_GROUPS


# --- Tracked-in-Anril scope, sync start clip, all-ads ---

import pytest

from app.services import ad_performance, meta_ads_fields
from app.services import meta_ads_insights_sync as sync
from tests.fake_supabase import FakeSupabase

ACCOUNT = "act_111"


def _perf_db():
    db = FakeSupabase()
    db.add("app_settings", tenant_id="t1", key="meta_ads_account_id", value=ACCOUNT)
    db.add("app_settings", tenant_id="t1", key="meta_ads_access_token", value="tok")
    db.add("ad_campaigns", id="c1", tenant_id="t1", meta_ad_account_id=ACCOUNT, campaign_name="Camp A")
    db.add("ad_creatives", id="ad-1", tenant_id="t1", meta_ad_account_id=ACCOUNT, campaign_id="c1",
           is_click_to_whatsapp=True, tracked_in_anril=True, meta_ad_id="m1",
           creative_label="One", destination_type="WHATSAPP", ad_effective_status="ACTIVE",
           messaging_channels=["whatsapp"])
    # Website ad: not a messaging ad, so it is in no list and no report.
    db.add("ad_creatives", id="ad-2", tenant_id="t1", meta_ad_account_id=ACCOUNT, campaign_id="c1",
           is_click_to_whatsapp=False, tracked_in_anril=False, meta_ad_id="m2",
           creative_label="Two", destination_type="WEBSITE", ad_effective_status="ACTIVE",
           messaging_channels=[])
    db.add("ad_creatives", id="ad-3", tenant_id="t1", meta_ad_account_id=ACCOUNT, campaign_id="c1",
           is_click_to_whatsapp=True, tracked_in_anril=True, meta_ad_id="m3",
           creative_label="Three", destination_type="WHATSAPP_MESSENGER", ad_effective_status="PAUSED",
           messaging_channels=["whatsapp", "messenger"])
    # Instagram-only messaging ad: no WhatsApp anywhere in its destination.
    db.add("ad_creatives", id="ad-4", tenant_id="t1", meta_ad_account_id=ACCOUNT, campaign_id="c1",
           is_click_to_whatsapp=False, tracked_in_anril=True, meta_ad_id="m4",
           creative_label="Four", destination_type="INSTAGRAM_DIRECT", ad_effective_status="ACTIVE",
           messaging_channels=["instagram"])
    # Messenger-only messaging ad that is not tracked in Anril yet.
    db.add("ad_creatives", id="ad-5", tenant_id="t1", meta_ad_account_id=ACCOUNT, campaign_id="c1",
           is_click_to_whatsapp=False, tracked_in_anril=False, meta_ad_id="m5",
           creative_label="Five", destination_type="MESSENGER", ad_effective_status="ACTIVE",
           messaging_channels=["messenger"])
    return db


@pytest.fixture
def settings(monkeypatch):
    """app_settings values read through get_ads_setting; the reach fetch is stubbed out."""
    store: dict[str, str] = {}
    monkeypatch.setattr(sync, "get_ads_setting", lambda db, tenant_id, key: store.get(key))
    monkeypatch.setattr(sync, "fetch_unique_reach_by_ad", lambda *a, **k: {})
    return store


class _FakeMeta:
    def __init__(self):
        self.results: list[dict] = []
        self.error: Exception | None = None
        self.calls: list[dict] = []

    def __call__(self, token, account, **kwargs):
        self.calls.append({"token": token, "account": account, **kwargs})
        if self.error:
            raise self.error
        return self.results


@pytest.fixture
def meta(monkeypatch):
    """Stands in for meta_ads_fields.fetch_meta_insights_live."""
    fake = _FakeMeta()
    monkeypatch.setattr(meta_ads_fields, "fetch_meta_insights_live", fake)
    return fake


def test_untracked_creative_is_left_out(settings):
    rows = ad_performance.build_creative_performance(_perf_db(), "t1")
    assert sorted(r["ad_creative_id"] for r in rows) == ["ad-1", "ad-3", "ad-4"]


def test_rows_carry_destination_type_and_multi_destination_flag(settings):
    rows = {r["ad_creative_id"]: r for r in ad_performance.build_creative_performance(_perf_db(), "t1")}
    assert rows["ad-1"]["destination_type"] == "WHATSAPP"
    assert rows["ad-1"]["is_multi_destination"] is False
    assert rows["ad-1"]["messaging_channels"] == ["whatsapp"]
    assert rows["ad-3"]["destination_type"] == "WHATSAPP_MESSENGER"
    assert rows["ad-3"]["is_multi_destination"] is True
    assert rows["ad-3"]["messaging_channels"] == ["whatsapp", "messenger"]


def test_instagram_only_creative_appears_in_the_report(settings):
    rows = {r["ad_creative_id"]: r for r in ad_performance.build_creative_performance(_perf_db(), "t1")}
    assert rows["ad-4"]["destination_type"] == "INSTAGRAM_DIRECT"
    assert rows["ad-4"]["messaging_channels"] == ["instagram"]
    assert rows["ad-4"]["is_multi_destination"] is False
    assert rows["ad-4"]["messages_by_channel"] == {"whatsapp": 0, "instagram": 0, "messenger": 0}


_MISSING = object()


def _attribute(db, lead_id, segment, channel=_MISSING, meta_ad_id="m1"):
    """One lead's first contact with an ad. channel=_MISSING leaves the column out entirely."""
    db.add("leads", id=lead_id, tenant_id="t1", segment=segment)
    row = dict(tenant_id="t1", meta_ad_account_id=ACCOUNT, lead_id=lead_id,
               meta_ad_id=meta_ad_id, first_seen_at="2026-09-05T10:00:00+00:00")
    if channel is not _MISSING:
        row["channel"] = channel
    db.add("lead_meta_ad_attributions", **row)


def test_messages_split_by_channel_and_total_stays_the_sum(settings):
    db = _perf_db()
    _attribute(db, "L1", "A", "whatsapp")
    _attribute(db, "L2", "B", "whatsapp")
    _attribute(db, "L3", "B", "instagram")

    rows = {r["ad_creative_id"]: r for r in ad_performance.build_creative_performance(db, "t1")}

    assert rows["ad-1"]["messages"] == 3
    assert rows["ad-1"]["messages_by_channel"] == {"whatsapp": 2, "instagram": 1, "messenger": 0}
    assert rows["ad-1"]["hot"] == 1


def test_attribution_without_a_channel_counts_as_whatsapp(settings):
    db = _perf_db()
    _attribute(db, "L1", "B", None)
    _attribute(db, "L2", "B")

    rows = {r["ad_creative_id"]: r for r in ad_performance.build_creative_performance(db, "t1")}

    assert rows["ad-1"]["messages"] == 2
    assert rows["ad-1"]["messages_by_channel"] == {"whatsapp": 2, "instagram": 0, "messenger": 0}


def test_sync_start_date_bounds_the_insights_query(settings, monkeypatch):
    settings["meta_ads_sync_start_date"] = "2026-09-01"
    reach_calls = []
    monkeypatch.setattr(sync, "fetch_unique_reach_by_ad",
                        lambda *a, **k: reach_calls.append(k) or {})
    db = _perf_db()
    db.add("ad_insights_daily", tenant_id="t1", meta_ad_account_id=ACCOUNT, ad_creative_id="ad-1",
           insight_date="2026-08-15", spend=10, inline_link_clicks=1)
    db.add("ad_insights_daily", tenant_id="t1", meta_ad_account_id=ACCOUNT, ad_creative_id="ad-1",
           insight_date="2026-09-05", spend=20, inline_link_clicks=2)

    rows = ad_performance.build_creative_performance(db, "t1", date_from="2026-08-01")

    row = next(r for r in rows if r["ad_creative_id"] == "ad-1")
    assert row["spend"] == 20
    assert row["inline_link_clicks"] == 2
    assert reach_calls[0]["date_from"] == "2026-09-01"


def test_meta_messaging_counters_are_summed_across_days(settings):
    db = _perf_db()
    for day, started, first_reply, blocks in (("2026-09-05", "3", "2", "1"), ("2026-09-06", "5", "4", "0")):
        db.add("ad_insights_daily", tenant_id="t1", meta_ad_account_id=ACCOUNT, ad_creative_id="ad-1",
               insight_date=day, spend=40, inline_link_clicks=10, actions=[
                   {"action_type": "onsite_conversion.total_messaging_connection", "value": "6"},
                   {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": started},
                   {"action_type": "onsite_conversion.messaging_first_reply", "value": first_reply},
                   {"action_type": "onsite_conversion.messaging_conversation_replied_7d", "value": "2"},
                   {"action_type": "onsite_conversion.messaging_block", "value": blocks},
               ])

    rows = {r["ad_creative_id"]: r for r in ad_performance.build_creative_performance(db, "t1")}

    row = rows["ad-1"]
    assert row["meta_conversations"] == 12
    assert row["meta_conversations_started"] == 8
    assert row["meta_new_contacts"] == 6
    assert row["meta_conversations_replied"] == 4
    assert row["meta_blocks"] == 1
    assert row["cost_per_meta_conversation"] == 10  # spend 80 / 8 conversations started


def test_meta_messaging_counters_default_to_zero_and_cost_is_none(settings):
    rows = {r["ad_creative_id"]: r for r in ad_performance.build_creative_performance(_perf_db(), "t1")}

    row = rows["ad-1"]  # no insights rows at all
    assert row["meta_conversations_started"] == 0
    assert row["meta_blocks"] == 0
    assert row["cost_per_meta_conversation"] is None


@pytest.mark.parametrize("destination, label", [
    ("WHATSAPP", "WhatsApp"),
    ("WHATSAPP_MESSENGER", "Multi-destination"),
    ("ON_AD", "Instant form"),
    ("WEBSITE", "Website"),
    ("MESSENGER", "Messenger"),
    ("INSTAGRAM_DIRECT", "Instagram Direct"),
    ("INSTAGRAM_PROFILE", "Instagram profile"),
    ("FACEBOOK", "Facebook page"),
    ("APP", "App"),
    ("PHONE_CALL", "Calls"),
    ("MESSAGING_INSTAGRAM_DIRECT_MESSENGER", "Multi-destination"),
    ("MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP", "Multi-destination"),
    ("MESSAGING_INSTAGRAM_DIRECT", "Messaging"),
    ("INSTAGRAM_STORY", "Messaging"),
    (None, "Other"),
    ("", "Other"),
    ("SOMETHING_NEW", "Something New"),
])
def test_ad_type_label(destination, label):
    assert ad_performance.ad_type_label(destination) == label


def test_list_ads_for_tracking_includes_every_messaging_ad_and_sorts(settings):
    rows = ad_performance.list_ads_for_tracking(_perf_db(), "t1")
    # Same campaign for all, so the sort falls through to creative label:
    # Five, Four, One, Three. The website ad (Two) is not a messaging ad, so it is left out.
    assert [r["ad_creative_id"] for r in rows] == ["ad-5", "ad-4", "ad-1", "ad-3"]
    assert [r["tracked"] for r in rows] == [False, True, True, True]
    assert rows[3]["is_multi_destination"] is True
    assert rows[1]["messaging_channels"] == ["instagram"]
    assert rows[0]["campaign_name"] == "Camp A"


def _registry(db, *ads):
    for meta_ad_id, eligible in ads:
        db.add("meta_ad_registry", tenant_id="t1", meta_ad_account_id=ACCOUNT,
               meta_ad_id=meta_ad_id, eligible=eligible)


def test_build_all_ads_passes_only_eligible_ids(settings, meta):
    db = _perf_db()
    _registry(db, ("m1", True), ("m3", True), ("m9", False))
    meta.results = [{"meta_ad_id": "m1", "destination_type": "WHATSAPP", "values": {"results": 4}}]

    out = ad_performance.build_all_ads(db, "t1", date_from="2026-09-01", date_to="2026-09-30",
                                       fields=["results"], breakdown=None)

    assert meta.calls[0]["ad_ids"] == {"m1", "m3"}
    assert meta.calls[0]["keys"] == ["results"]
    assert out["data"][0]["ad_type"] == "WhatsApp"
    assert out["date_from"] == "2026-09-01"
    assert out["date_to"] == "2026-09-30"
    assert out["start_date"] is None


def test_build_all_ads_without_eligible_ads_skips_meta(settings, meta):
    db = _perf_db()
    _registry(db, ("m9", False))

    out = ad_performance.build_all_ads(db, "t1", date_from="2026-09-01", date_to="2026-09-30",
                                       fields=["results"], breakdown=None)

    assert out["data"] == []
    assert meta.calls == []


def test_build_all_ads_clips_to_sync_start_and_skips_empty_range(settings, meta):
    settings["meta_ads_sync_start_date"] = "2026-09-15"
    db = _perf_db()
    _registry(db, ("m1", True))

    out = ad_performance.build_all_ads(db, "t1", date_from="2026-08-01", date_to="2026-09-10",
                                       fields=["results"], breakdown=None)

    assert out["data"] == []
    assert out["date_from"] == "2026-09-15"
    assert meta.calls == []


def test_build_all_ads_without_connected_account_raises(settings, meta):
    with pytest.raises(ValueError, match="Connect a Meta Ads account first"):
        ad_performance.build_all_ads(FakeSupabase(), "t1", date_from="2026-09-01",
                                     date_to="2026-09-30", fields=["results"], breakdown=None)
