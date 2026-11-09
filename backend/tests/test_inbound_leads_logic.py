"""Tests for inbound lead reporting pure logic. No DB, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.inbound_leads_logic import (
    INBOUND_SOURCES,
    is_inbound_lead,
    lead_origin,
    aggregate_inbound,
)


def test_inbound_sources_are_the_messaging_marketplace_and_lead_form_channels():
    assert set(INBOUND_SOURCES) == {
        "whatsapp", "instagram", "facebook", "telegram", "indiamart", "justdial", "meta_form",
    }


def test_is_inbound_lead_excludes_upload_and_manual():
    assert is_inbound_lead({"source": "whatsapp"}) is True
    assert is_inbound_lead({"source": "telegram"}) is True
    assert is_inbound_lead({"source": "upload"}) is False
    assert is_inbound_lead({"source": "manual"}) is False
    assert is_inbound_lead({"source": None}) is False
    assert is_inbound_lead({}) is False


def test_lead_origin_is_ad_when_campaign_present_else_organic():
    assert lead_origin({"ad_campaign_id": "abc"}) == "ad"
    assert lead_origin({"ad_campaign_id": None}) == "organic"
    assert lead_origin({}) == "organic"


def test_aggregate_inbound_splits_organic_vs_ad_and_buckets_by_utc_day():
    days = ["2026-06-05", "2026-06-06"]
    today = "2026-06-06"
    leads = [
        {"source": "whatsapp", "ad_campaign_id": None, "segment": "A",
         "created_at": "2026-06-06T03:00:00+00:00"},
        {"source": "whatsapp", "ad_campaign_id": "c1", "segment": "B",
         "created_at": "2026-06-06T10:00:00+00:00"},
        {"source": "instagram", "ad_campaign_id": "c1", "segment": "C",
         "created_at": "2026-06-05T22:00:00+00:00"},
        {"source": "upload", "ad_campaign_id": None, "segment": "A",
         "created_at": "2026-06-06T05:00:00+00:00"},
    ]
    out = aggregate_inbound(leads, days, today)

    assert out["kpis"]["today"] == {"total": 2, "organic": 1, "ad": 1}
    assert out["kpis"]["range"] == {"total": 3, "organic": 1, "ad": 2}
    assert out["daily"] == [
        {"day": "2026-06-05", "organic": 0, "ad": 1},
        {"day": "2026-06-06", "organic": 1, "ad": 1},
    ]
    assert out["by_segment"] == {"A": 1, "B": 1, "C": 1, "D": 0}
    assert out["by_channel"] == {
        "whatsapp": 2, "instagram": 1, "facebook": 0, "telegram": 0,
        "indiamart": 0, "justdial": 0, "meta_form": 0,
    }
