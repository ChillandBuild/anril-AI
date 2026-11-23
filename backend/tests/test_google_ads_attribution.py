"""Tests for Google Ads click-to-WhatsApp attribution parsing. No DB, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.services.google_ads_attribution import (
    GoogleAdRef,
    build_tracked_wa_link,
    parse_google_ref,
    slugify_campaign,
)


def test_parses_gads_colon_tag():
    ref = parse_google_ref("Hi, I'm interested [GADS:summer_sale]")
    assert ref == GoogleAdRef(campaign="summer_sale", gclid=None)


def test_accepts_google_prefix_and_hyphen_underscore_separators():
    assert parse_google_ref("hello [GOOGLE-winter]").campaign == "winter"
    assert parse_google_ref("hello [GADS_promo2026]").campaign == "promo2026"


def test_is_case_insensitive():
    assert parse_google_ref("hey [gads:diwali]").campaign == "diwali"


def test_captures_optional_gclid_when_present():
    ref = parse_google_ref("Hi [GADS:brand] [GCLID:Cj0abc-123_XY]")
    assert ref.campaign == "brand"
    assert ref.gclid == "Cj0abc-123_XY"


def test_returns_none_for_organic_message():
    assert parse_google_ref("Hi, I'd like to know the fees") is None


def test_returns_none_for_empty_or_missing_text():
    assert parse_google_ref("") is None
    assert parse_google_ref(None) is None


def test_external_campaign_id_is_namespaced_to_avoid_meta_collision():
    ref = GoogleAdRef(campaign="summer_sale")
    assert ref.external_campaign_id == "google:summer_sale"


def test_gclid_without_campaign_is_not_attributed():
    # A gclid alone is not enough — we key attribution on the campaign tag.
    assert parse_google_ref("random text [GCLID:abc123]") is None


def test_build_link_strips_plus_and_encodes_text():
    link = build_tracked_wa_link("+91 98765 43210", "summer_sale")
    assert link.startswith("https://wa.me/919876543210?text=")
    assert "%5BGADS%3Asummer_sale%5D" in link  # [GADS:summer_sale] url-encoded


def test_build_link_round_trips_through_parser():
    # The generator and parser must agree on the tag format — prove it.
    link = build_tracked_wa_link("919876543210", "diwali_2026")
    from urllib.parse import unquote
    prefilled = unquote(link.split("text=", 1)[1])
    ref = parse_google_ref(prefilled)
    assert ref == GoogleAdRef(campaign="diwali_2026", gclid=None)


def test_build_link_never_carries_a_gclid_even_when_one_is_passed():
    link = build_tracked_wa_link("919876543210", "diwali_2026", gclid="Cj0abc_XY")
    assert "gclid" not in link.lower()
    assert "Cj0abc_XY" not in link
    assert "%5BGADS%3Adiwali_2026%5D" in link


def test_build_link_rejects_invalid_slug():
    with pytest.raises(ValueError):
        build_tracked_wa_link("919876543210", "summer-sale!")  # hyphen + bang


def test_slugify_normalizes_human_names():
    assert slugify_campaign("Summer Sale 2026!") == "summer_sale_2026"
    assert slugify_campaign("  Diwali-Offer  ") == "diwali_offer"
    assert slugify_campaign("already_ok") == "already_ok"


def test_slugify_returns_empty_when_nothing_usable():
    assert slugify_campaign("!!!") == ""
    assert slugify_campaign("") == ""
    assert slugify_campaign(None) == ""


def test_slugify_output_is_accepted_by_build_link():
    slug = slugify_campaign("Monsoon Blowout 2026")
    build_tracked_wa_link("919876543210", slug)  # must not raise
    assert parse_google_ref(f"hi [GADS:{slug}]").campaign == slug
