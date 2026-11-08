"""Static assertions on the inbound leads route + analytics wiring."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_old_ctwa_route_file_is_gone():
    assert not (ROOT / "app/routes/ctwa_leads.py").exists()


def test_inbound_route_filters_to_messaging_channels_and_origin():
    src = read("app/routes/inbound_leads.py")
    assert "INBOUND_SOURCES" in src
    assert '.in_("source", list(INBOUND_SOURCES))' in src
    assert 'origin == "ad"' in src
    assert 'origin == "organic"' in src
    assert '.not_.is_("ad_campaign_id", "null")' in src
    assert '.is_("ad_campaign_id", "null")' in src
    assert '.eq("segment", segment)' in src
    assert '"origin"' in src
    assert "filename=inbound_leads.csv" in src


def test_ad_performance_export_headers_match_table_labels():
    import re

    src = read("app/routes/inbound_leads.py")
    block = src.split("AD_PERFORMANCE_EXPORT_COLUMNS = [", 1)[1].split("]", 1)[0]
    export_labels = re.findall(r'\("\w+", "([^"]+)"\)', block)

    tab = (ROOT.parent / "frontend/app/dashboard/meta-ads/AdPerformanceTab.tsx").read_text(encoding="utf-8")
    metrics_block = tab.split("const METRICS", 1)[1].split("];", 1)[0]
    # The CSV opens with the identity columns an Ads Manager export has, so the
    # two files line up by Ad ID; after them it follows the on-screen table.
    meta_identity = ["Reporting starts", "Reporting ends", "Ad ID", "Campaign name", "Ad set name", "Ad name"]
    assert export_labels[:len(meta_identity)] == meta_identity
    export_labels = export_labels[len(meta_identity):]
    table_labels = re.findall(r'label: "([^"]+)"', metrics_block)

    # The per-app split shows inside the Messages sent cell on screen; the CSV
    # gives it its own columns right after Messages sent.
    split = ["WhatsApp messages", "Instagram messages", "Messenger messages"]
    at = export_labels.index("Messages sent (Anril confirmed)") + 1
    assert export_labels[at:at + 3] == split
    assert export_labels[:at] + export_labels[at + 3:] == table_labels


def test_main_registers_inbound_leads_prefix_not_ctwa():
    main = read("app/main.py")
    assert "/api/v1/inbound-leads" in main
    assert "inbound_leads.router" in main
    assert "ctwa_leads" not in main
    assert "ctwa-leads" not in main


def test_analytics_has_inbound_endpoint():
    src = read("app/routes/analytics.py")
    assert '@router.get("/inbound")' in src
    assert "aggregate_inbound" in src
    assert 'in_("source", list(INBOUND_SOURCES))' in src


def test_analytics_routes_use_rbac_view_permissions():
    src = read("app/routes/analytics.py")
    assert "get_dashboard_analytics_tenant_id" in src
    assert "tenant_id: str = Depends(get_dashboard_analytics_tenant_id)" in src
    assert "get_analytics_tenant_id" in src
    assert "require_analytics_view" in src
    assert "get_owner_tenant_id" not in src
    assert "require_owner" not in src
