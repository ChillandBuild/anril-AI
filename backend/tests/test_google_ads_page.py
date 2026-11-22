"""Google Ads page: CSV parsing, month window, money hiding, permission gates, link, came_from."""
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.routes import google_ads, inbound_leads
from app.services import google_ads_report as rep
from app.services.google_ads_attribution import build_tracked_wa_link, parse_google_ref
from tests.fake_supabase import FakeSupabase

NOV = "2026-11"


# ── pure helpers ────────────────────────────────────────────────────────────

def test_month_window_is_the_ist_month_in_utc():
    start, end = rep.month_window_utc("2026-11")
    assert start == "2026-10-31T18:30:00+00:00"
    assert end == "2026-11-30T18:30:00+00:00"
    assert rep.month_window_utc("2026-12")[1] == "2026-12-31T18:30:00+00:00"


def test_parse_month_default_and_errors():
    assert rep.parse_month(None) == rep.current_month_ist()
    assert rep.parse_month("2026-02") == "2026-02"
    for bad in ("2026-13", "26-11", "2026-1", "nov", "2026-11-01"):
        with pytest.raises(rep.ReportError):
            rep.parse_month(bad)


def test_money_parsing():
    assert rep.parse_money_paise("₹1,23,456.50") == 12345650
    assert rep.parse_money_paise("Rs. 1,200") == 120000
    assert rep.parse_money_paise("1200") == 120000
    assert rep.parse_money_paise("--") is None
    assert rep.parse_money_paise("") is None
    assert rep.parse_money_paise("-5") is None
    assert rep.parse_count("1,234") == 1234
    assert rep.parse_count("--") is None
    assert rep.parse_count("12.0") == 12


GOOGLE_CSV = (
    "Campaign report\n"
    "1 November 2026 - 30 November 2026\n"
    "\n"
    'Campaign,Campaign status,Clicks,Impr.,Cost\n'
    'Diwali Offer,Enabled,"1,234","50,000","₹12,345.50"\n'
    "Brand Search,Enabled,300,9000,₹800\n"
    "Paused one,Paused,--,--,--\n"
    'Total: Account,,"1,534","59,000","₹13,145.50"\n'
)


def test_csv_skips_header_junk_and_reads_rupees_and_commas():
    out = rep.parse_report_csv(GOOGLE_CSV.encode("utf-8-sig"), NOV)
    rows = {r["google_campaign_name"]: r for r in out["rows"]}
    assert rows["Diwali Offer"] == {"google_campaign_name": "Diwali Offer", "spend_paise": 1234550, "clicks": 1234}
    assert rows["Brand Search"]["spend_paise"] == 80000
    assert rows["Paused one"]["spend_paise"] == 0
    assert not any(n.lower().startswith("total") for n in rows)


def test_csv_utf16_tab_separated():
    raw = "Campaign\tClicks\tCost\nSale\t10\t500\n".encode("utf-16")
    assert rep.parse_report_csv(raw, NOV)["rows"][0] == {"google_campaign_name": "Sale", "spend_paise": 50000, "clicks": 10}


def test_csv_day_column_keeps_only_the_month_and_adds_days_up():
    csv_text = (
        "Day,Campaign,Clicks,Cost\n"
        "2026-11-01,Sale,5,100\n"
        "2026-11-02,Sale,7,50.50\n"
        "2026-10-31,Sale,99,999\n"
    )
    out = rep.parse_report_csv(csv_text, NOV)
    assert out["rows"] == [{"google_campaign_name": "Sale", "spend_paise": 15050, "clicks": 12}]
    assert out["skipped_other_months"] == 1


def test_csv_month_column_names_and_formats():
    for cell in ("Nov 2026", "November 2026", "2026-11", "05/11/2026", "Nov 5, 2026"):
        out = rep.parse_report_csv(f'Month,Campaign,Clicks,Cost\n"{cell}",Sale,1,10\n', NOV)
        assert out["rows"][0]["clicks"] == 1, cell


def test_csv_errors_are_plain():
    with pytest.raises(rep.ReportError, match="couldn't find the table"):
        rep.parse_report_csv("hello,world\n1,2\n", NOV)
    with pytest.raises(rep.ReportError, match="No campaign rows for this month"):
        rep.parse_report_csv("Day,Campaign,Clicks,Cost\n2026-10-01,Sale,1,1\n", NOV)
    with pytest.raises(rep.ReportError, match="too big"):
        rep.parse_report_csv(b"x" * (rep.MAX_UPLOAD_BYTES + 1), NOV)


def test_match_rows_is_case_insensitive_and_trimmed():
    campaigns = [{"id": "c1", "campaign_name": "diwali", "google_campaign_name": "  Diwali OFFER "}]
    rows = [
        {"google_campaign_name": "diwali offer", "spend_paise": 1, "clicks": 1},
        {"google_campaign_name": "Other", "spend_paise": 2, "clicks": 2},
    ]
    matched, unmatched = rep.match_rows(rows, campaigns)
    assert [m["campaign_id"] for m in matched] == ["c1"]
    assert [u["google_campaign_name"] for u in unmatched] == ["Other"]


# ── link generator + webhook parser ─────────────────────────────────────────

def test_generated_link_has_tag_and_no_gclid():
    link = build_tracked_wa_link("+91 98765 43210", "diwali_offer", gclid="abc123")
    assert link.startswith("https://wa.me/919876543210?text=")
    assert "gclid" not in link.lower()
    assert "abc123" not in link
    assert parse_google_ref(unquote(link.split("text=", 1)[1])).campaign == "diwali_offer"


@pytest.mark.parametrize("text", [
    "hi [GADS:sale]", "hi [GOOGLE:sale]", "hi [GADS-sale]", "hi [GADS_sale]", "hi [gads:SALE]",
])
def test_parser_still_reads_every_tag_form(text):
    assert parse_google_ref(text).campaign.lower() == "sale"


# ── routes ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(google_ads, "get_supabase", lambda: fake)
    monkeypatch.setattr(inbound_leads, "get_supabase", lambda: fake)
    fake.add("phone_numbers", tenant_id="t1", number="919876543210", role="primary", status="active")
    fake.add("ad_campaigns", id="c1", tenant_id="t1", platform="google", campaign_name="diwali",
             google_campaign_name="Diwali Offer", created_at="2026-10-01")
    fake.add("ad_campaigns", id="c2", tenant_id="t1", platform="google", campaign_name="brand",
             google_campaign_name=None, created_at="2026-10-02")
    fake.add("ad_campaigns", id="m1", tenant_id="t1", platform="facebook", campaign_name="meta one")
    fake.add("ad_campaigns", id="x1", tenant_id="t2", platform="google", campaign_name="other")
    # leads: c1 has 3 in November (1 hot), 1 in October; other tenant's lead ignored
    for lid, seg, created in [("l1", "A", "2026-11-05T05:00:00+00:00"), ("l2", "C", "2026-11-10T05:00:00+00:00"),
                              ("l3", "B", "2026-11-30T18:00:00+00:00"), ("l4", "A", "2026-10-31T10:00:00+00:00")]:
        fake.add("leads", id=lid, tenant_id="t1", ad_campaign_id="c1", segment=seg, created_at=created)
    fake.add("leads", id="l9", tenant_id="t2", ad_campaign_id="c1", segment="A", created_at="2026-11-05T05:00:00+00:00")
    fake.add("call_logs", id="k1", tenant_id="t1", lead_id="l1", created_at="2026-11-06T05:00:00+00:00")
    fake.add("call_logs", id="k2", tenant_id="t1", lead_id="l2", created_at="2026-11-12T05:00:00+00:00")
    fake.add("call_logs", id="k3", tenant_id="t1", lead_id="l1", created_at="2026-12-02T05:00:00+00:00")  # next month
    fake.add("deals", id="d1", tenant_id="t1", lead_id="l1", paid_paise=100000, refunded_paise=0)
    fake.add("deals", id="d2", tenant_id="t1", lead_id="l2", paid_paise=50000, refunded_paise=50000)  # fully refunded
    fake.add("deals", id="d3", tenant_id="t1", lead_id="l2", paid_paise=30000, refunded_paise=10000)
    fake.add("google_ads_spend", tenant_id="t1", campaign_id="c1", month="2026-11-01", spend_paise=600000,
             clicks=200, source="upload")
    return fake


def _client(perms=(), role="member"):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_id] = lambda: "t1"
    app.dependency_overrides[get_tenant_and_role] = lambda: {
        "tenant_id": "t1", "role": role, "user_id": "u1", "permissions": list(perms),
    }
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def test_campaigns_numbers_for_the_month(db):
    res = _client(role="owner").get(f"/api/v1/google-ads/campaigns?month={NOV}")
    assert res.status_code == 200
    body = res.json()
    assert body["month"] == NOV
    assert body["connect"] == {"available": False, "reason": "Needs Google approval"}
    by_name = {r["name"]: r for r in body["rows"]}
    assert set(by_name) == {"diwali", "brand"}          # google only, own tenant only
    r = by_name["diwali"]
    assert r["chats"] == 3 and r["hot"] == 1 and r["calls"] == 2
    assert r["paid_orders"] == 2 and r["paid_paise"] == 120000   # d1 + d3 net; d2 refunded in full
    assert r["spent_paise"] == 600000 and r["clicks"] == 200 and r["per_chat_paise"] == 200000
    assert r["google_campaign_name"] == "Diwali Offer"
    brand = by_name["brand"]
    assert brand["chats"] == 0 and brand["clicks"] is None and brand["spent_paise"] is None and brand["per_chat_paise"] is None
    assert body["totals"]["chats"] == 3 and body["totals"]["spent_paise"] == 600000


def test_month_window_excludes_the_edges(db):
    # l4 (31 Oct 15:40 IST) is October; l3 (1 Dec 00:00 IST minus 30 min) is still November.
    october = _client(role="owner").get("/api/v1/google-ads/campaigns?month=2026-10").json()
    assert {r["name"]: r["chats"] for r in october["rows"]}["diwali"] == 1


def test_money_hidden_without_deals_view(db):
    body = _client(perms=["meta_ads.view"]).get(f"/api/v1/google-ads/campaigns?month={NOV}").json()
    for row in body["rows"]:
        assert not ({"spent_paise", "paid_paise", "per_chat_paise"} & set(row))
    assert not ({"spent_paise", "paid_paise", "per_chat_paise"} & set(body["totals"]))
    assert body["rows"][0]["paid_orders"] >= 0 and "clicks" in body["rows"][0]
    shown = _client(perms=["meta_ads.view", "deals.view"]).get(f"/api/v1/google-ads/campaigns?month={NOV}").json()
    assert shown["rows"][0]["spent_paise"] == 600000


def test_bad_month_is_400(db):
    assert _client(role="owner").get("/api/v1/google-ads/campaigns?month=2026-13").status_code == 400


def test_permission_gates(db):
    nobody = _client(perms=["leads.view"])
    assert nobody.get("/api/v1/google-ads/campaigns").status_code == 403
    viewer = _client(perms=["meta_ads.view"])
    assert viewer.get("/api/v1/google-ads/campaigns").status_code == 200
    assert viewer.patch("/api/v1/google-ads/campaigns/c1", json={"google_campaign_name": "x"}).status_code == 403
    assert viewer.put("/api/v1/google-ads/campaigns/c1/spend", json={"month": NOV, "spend_paise": 1, "clicks": 1}).status_code == 403
    assert viewer.post("/api/v1/google-ads/upload", files={"file": ("a.csv", b"x")}).status_code == 403
    assert viewer.post("/api/v1/google-ads/pair", json={"google_campaign_name": "a", "campaign_id": "c1", "month": NOV, "spend_paise": 1, "clicks": 1}).status_code == 403
    assert viewer.post("/api/v1/google-ads/links", json={"campaign": "x"}).status_code == 403
    manager = _client(perms=["meta_ads.manage"])          # manage implies view
    assert manager.get("/api/v1/google-ads/campaigns").status_code == 200


def test_patch_and_hand_spend(db):
    c = _client(perms=["meta_ads.manage"])
    assert c.patch("/api/v1/google-ads/campaigns/c2", json={"google_campaign_name": " Brand Search "}).json()["google_campaign_name"] == "Brand Search"
    assert db.rows("ad_campaigns")[1]["google_campaign_name"] == "Brand Search"
    assert c.put("/api/v1/google-ads/campaigns/c2/spend", json={"month": NOV, "spend_paise": 70000, "clicks": 40}).status_code == 200
    row = [r for r in db.rows("google_ads_spend") if r["campaign_id"] == "c2"][0]
    assert (row["spend_paise"], row["clicks"], row["source"], row["month"]) == (70000, 40, "hand", "2026-11-01")
    # other tenant's / non-google campaigns are 404
    assert c.put("/api/v1/google-ads/campaigns/x1/spend", json={"month": NOV, "spend_paise": 1, "clicks": 1}).status_code == 404
    assert c.put("/api/v1/google-ads/campaigns/m1/spend", json={"month": NOV, "spend_paise": 1, "clicks": 1}).status_code == 404
    assert c.put("/api/v1/google-ads/campaigns/c2/spend", json={"month": NOV, "spend_paise": -1, "clicks": 1}).status_code == 422


def test_upload_matches_saves_and_returns_unmatched(db):
    c = _client(perms=["meta_ads.manage"])
    res = c.post(f"/api/v1/google-ads/upload?month={NOV}", files={"file": ("r.csv", GOOGLE_CSV.encode("utf-8-sig"))})
    assert res.status_code == 200
    body = res.json()
    assert [m["campaign_id"] for m in body["matched"]] == ["c1"]
    assert {u["google_campaign_name"] for u in body["unmatched"]} == {"Brand Search", "Paused one"}
    saved = [r for r in db.rows("google_ads_spend") if r["campaign_id"] == "c1"]
    assert len(saved) == 1 and saved[0]["spend_paise"] == 1234550 and saved[0]["clicks"] == 1234 and saved[0]["source"] == "upload"


def test_upload_rejects_big_and_unreadable_files(db):
    c = _client(perms=["meta_ads.manage"])
    big = c.post(f"/api/v1/google-ads/upload?month={NOV}", files={"file": ("r.csv", b"a" * (rep.MAX_UPLOAD_BYTES + 5))})
    assert big.status_code == 413
    bad = c.post(f"/api/v1/google-ads/upload?month={NOV}", files={"file": ("r.csv", b"nothing,here\n")})
    assert bad.status_code == 400 and "table" in bad.json()["detail"]


def test_pair_saves_the_name_and_the_spend_and_frees_a_duplicate_name(db):
    c = _client(perms=["meta_ads.manage"])
    res = c.post("/api/v1/google-ads/pair", json={"google_campaign_name": "diwali offer", "campaign_id": "c2",
                                                  "month": NOV, "spend_paise": 80000, "clicks": 300})
    assert res.status_code == 200
    camps = {r["id"]: r for r in db.rows("ad_campaigns")}
    assert camps["c2"]["google_campaign_name"] == "diwali offer"
    assert camps["c1"]["google_campaign_name"] is None          # one Google name, one campaign
    assert [r for r in db.rows("google_ads_spend") if r["campaign_id"] == "c2"][0]["spend_paise"] == 80000
    assert c.post("/api/v1/google-ads/pair", json={"google_campaign_name": "a", "campaign_id": "x1", "month": NOV,
                                                   "spend_paise": 1, "clicks": 1}).status_code == 404


def test_links_endpoint_has_tag_no_gclid_and_makes_campaign(db):
    c = _client(perms=["meta_ads.manage"])
    res = c.post("/api/v1/google-ads/links", json={"campaign": "Summer Sale 2026!"})
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_slug"] == "summer_sale_2026"
    assert "gclid" not in body["link"].lower()
    assert "%5BGADS%3Asummer_sale_2026%5D" in body["link"]
    made = [r for r in db.rows("ad_campaigns") if r["campaign_name"] == "summer_sale_2026"]
    assert len(made) == 1 and made[0]["platform"] == "google" and made[0]["external_campaign_id"] == "google:summer_sale_2026"
    assert body["campaign_id"] == made[0]["id"]
    assert c.post("/api/v1/google-ads/links", json={"campaign": "!!!"}).status_code == 400
    # the older endpoint still works and also ignores a gclid
    old = c.get("/api/v1/inbound-leads/google-link?campaign=Sale&gclid=zzz")
    assert old.status_code == 200 and "gclid" not in old.json()["link"].lower() and "zzz" not in old.json()["link"]


# ── came_from ───────────────────────────────────────────────────────────────

def test_came_from_labels():
    db = FakeSupabase()
    db.add("ad_campaigns", id="g", tenant_id="t1", platform="google", campaign_name="diwali")
    db.add("ad_campaigns", id="f", tenant_id="t1", platform="facebook", campaign_name="Reel 3")
    db.add("ad_campaigns", id="i", tenant_id="t1", platform="instagram", campaign_name="Story")
    db.add("qr_links", id="q", tenant_id="t1", name="Shop door")
    db.add("qr_links", id="q2", tenant_id="t2", name="Other tenant")
    leads = [
        {"id": "a", "ad_campaign_id": "g"}, {"id": "b", "ad_campaign_id": "f"}, {"id": "c", "ad_campaign_id": "i"},
        {"id": "d", "qr_link_id": "q"}, {"id": "e", "qr_link_id": "q2"}, {"id": "f", "ad_campaign_id": "gone"}, {"id": "g"},
    ]
    labels = rep.came_from_labels(db, "t1", leads)
    assert labels["a"] == "from Google Ads · diwali"
    assert labels["b"] == "from Meta ad · Reel 3"
    assert labels["c"] == "from Meta ad · Story"
    assert labels["d"] == "from QR · Shop door"
    assert "e" not in labels and "g" not in labels            # another tenant's QR / no source: no label
    assert labels["f"] == "from an ad"                        # campaign row missing: never claim Meta


def test_came_from_never_raises():
    class Boom:
        def table(self, _):
            raise RuntimeError("db down")
    assert rep.came_from_labels(Boom(), "t1", [{"id": "a", "ad_campaign_id": "g", "qr_link_id": "q"}]) == {"a": "from an ad"}


def test_inbox_conversations_carry_came_from(monkeypatch):
    """The Chats inbox loads leads from GET /api/v1/conversations, so that is where came_from must be set."""
    from unittest.mock import patch
    from app.routes import conversations as conv_route

    fake = FakeSupabase()
    fake.add("ad_campaigns", id="g", tenant_id="t1", platform="google", campaign_name="diwali")
    fake.add("qr_links", id="q", tenant_id="t1", name="Shop door")
    for lid, extra in (("a", {"ad_campaign_id": "g"}), ("b", {"qr_link_id": "q"}), ("c", {})):
        fake.add("leads", id=lid, tenant_id="t1", deleted_at=None, archived_at=None, blocked_at=None,
                 escalation_reason=None, **extra)
    fake.rpc_handlers["get_inbox_chats"] = lambda params: [
        {"lead_id": lid, "last_reply_at": "2026-10-10T09:00:00+00:00", "last_message_content": "x", "total": 3,
         "inbox_group": 1, "waiting_since": None, "unread_count": 0} for lid in ("a", "b", "c")
    ]
    with patch.object(conv_route, "get_supabase", return_value=fake), \
            patch.object(conv_route, "get_setting", return_value="true"):
        res = _client(role="owner").get("/api/v1/conversations")
    assert res.status_code == 200
    by_id = {l["id"]: l for l in res.json()["leads"]}
    assert by_id["a"]["came_from"] == "from Google Ads · diwali"
    assert by_id["b"]["came_from"] == "from QR · Shop door"
    assert "came_from" not in by_id["c"]


def test_inbox_still_loads_when_the_label_lookup_fails(monkeypatch):
    from unittest.mock import patch
    from app.routes import conversations as conv_route

    fake = FakeSupabase()
    fake.add("leads", id="a", tenant_id="t1", deleted_at=None, archived_at=None, blocked_at=None,
             escalation_reason=None, ad_campaign_id="g")
    fake.rpc_handlers["get_inbox_chats"] = lambda params: [
        {"lead_id": "a", "last_reply_at": "2026-10-10T09:00:00+00:00", "last_message_content": "x", "total": 1,
         "inbox_group": 1, "waiting_since": None, "unread_count": 0}]

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(rep, "came_from_labels", boom)
    with patch.object(conv_route, "get_supabase", return_value=fake), \
            patch.object(conv_route, "get_setting", return_value="true"):
        res = _client(role="owner").get("/api/v1/conversations")
    assert res.status_code == 200 and res.json()["leads"][0]["id"] == "a"


# ── review fixes ────────────────────────────────────────────────────────────

def test_total_rows_are_skipped_but_a_campaign_called_total_something_is_kept():
    csv_text = (
        "Campaign,Clicks,Cost\n"
        "Total Wellness Search,10,100\n"
        "Total,99,999\n"
        "Total: Account,99,999\n"
        "Totally Brand,5,50\n"
    )
    names = [r["google_campaign_name"] for r in rep.parse_report_csv(csv_text, NOV)["rows"]]
    assert names == ["Total Wellness Search", "Totally Brand"]


def test_csv_error_becomes_a_plain_message(monkeypatch):
    import csv as csv_mod

    def boom(*a, **k):
        raise csv_mod.Error("bad")
    monkeypatch.setattr(rep.csv, "reader", boom)
    with pytest.raises(rep.ReportError, match="couldn't read that file as a CSV"):
        rep.parse_report_csv("Campaign,Clicks,Cost\nA,1,1\n", NOV)


def test_missing_column_is_none_in_the_parse():
    only_cost = rep.parse_report_csv("Campaign,Cost\nSale,50\n", NOV)["rows"][0]
    assert only_cost == {"google_campaign_name": "Sale", "spend_paise": 5000, "clicks": None}
    only_clicks = rep.parse_report_csv("Campaign,Clicks\nSale,7\n", NOV)["rows"][0]
    assert only_clicks == {"google_campaign_name": "Sale", "spend_paise": None, "clicks": 7}


def test_upload_without_clicks_column_keeps_the_saved_clicks(db):
    c = _client(perms=["meta_ads.manage"])
    res = c.post(f"/api/v1/google-ads/upload?month={NOV}",
                 files={"file": ("r.csv", b"Campaign,Cost\nDiwali Offer,900\n")})
    assert res.status_code == 200
    saved = [r for r in db.rows("google_ads_spend") if r["campaign_id"] == "c1"]
    assert len(saved) == 1 and saved[0]["spend_paise"] == 90000 and saved[0]["clicks"] == 200   # clicks kept
    res = c.post(f"/api/v1/google-ads/upload?month={NOV}",
                 files={"file": ("r.csv", b"Campaign,Clicks\nDiwali Offer,321\n")})
    saved = [r for r in db.rows("google_ads_spend") if r["campaign_id"] == "c1"][0]
    assert saved["spend_paise"] == 90000 and saved["clicks"] == 321                              # spend kept


def test_first_save_of_a_missing_column_is_zero(db):
    rep.save_spend(db, "t1", "c2", NOV, 5000, None, source="upload")
    row = [r for r in db.rows("google_ads_spend") if r["campaign_id"] == "c2"][0]
    assert row["spend_paise"] == 5000 and row["clicks"] == 0


def test_day_column_with_weekday_name():
    csv_text = 'Day,Campaign,Clicks,Cost\n"Sunday, 1 November 2026",Sale,3,10\n"Monday, 2 November 2026",Sale,4,20\n'
    out = rep.parse_report_csv(csv_text, NOV)
    assert out["rows"][0]["clicks"] == 7 and out["skipped_other_months"] == 0


@pytest.mark.parametrize("cost", ["$12.50", "USD 12", "EUR 10", "€10", "£4"])
def test_foreign_currency_is_refused(cost):
    with pytest.raises(rep.ReportError, match="not in rupees"):
        rep.parse_report_csv(f'Campaign,Clicks,Cost\nSale,1,"{cost}"\n', NOV)
    with pytest.raises(rep.ReportError, match="not in rupees"):
        rep.parse_report_csv("Campaign,Clicks,Cost (USD)\nSale,1,5\n", NOV)


def test_upload_refuses_a_declared_size_over_the_limit_before_reading(db):
    c = _client(perms=["meta_ads.manage"])
    res = c.post(f"/api/v1/google-ads/upload?month={NOV}", files={"file": ("r.csv", b"Campaign,Clicks\nA,1\n")},
                 headers={"Content-Length": str(rep.MAX_UPLOAD_BYTES + 70_000)})
    assert res.status_code == 413


def test_patch_frees_a_duplicate_google_name(db):
    c = _client(perms=["meta_ads.manage"])
    assert c.patch("/api/v1/google-ads/campaigns/c2", json={"google_campaign_name": "diwali OFFER"}).status_code == 200
    camps = {r["id"]: r for r in db.rows("ad_campaigns")}
    assert camps["c2"]["google_campaign_name"] == "diwali OFFER" and camps["c1"]["google_campaign_name"] is None
