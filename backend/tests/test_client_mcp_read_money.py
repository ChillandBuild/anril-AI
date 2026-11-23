"""Anril AI client connector: the money and report read tools (tools_read_money).

Per tool: it answers for the signed-in client, never shows the other client's rows, never lets a
secret or a payment/bill link out, and never writes. The database is a fake, run behind the REAL
read-only guard (app.db.supabase._ReadOnlyClient), so a write or an unlisted RPC fails the test.
"""
import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp import tools_read_money as money
from app.client_mcp import wrapper
from app.db import supabase as supabase_db
from app.db.supabase import ReadOnlyViolation
from tests.fake_supabase import FakeSupabase

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEAL_A = "d1111111-1111-1111-1111-111111111111"
DEAL_B = "d2222222-2222-2222-2222-222222222222"
LEAD_A = "11111111-1111-1111-1111-111111111111"
LEAD_B = "22222222-2222-2222-2222-222222222222"
SECRETS = ("SECRET-LINK", "BILL-TOKEN-SECRET", "rzp-SECRET-VALUE", "SECRET-ACCESS-TOKEN", "signed-SECRET")

NOW = datetime.now(timezone.utc)


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


def seeded() -> FakeSupabase:
    """Two clients. Everything of B's contains the word 'SECRET-B' or 'OTHER'."""
    db = FakeSupabase()
    db.add("tenants", id=A, name="Shop A", status="active")
    db.add("tenants", id=B, name="Shop B", status="active")
    db.add("tenant_users", tenant_id=A, user_id="owner-a", role="owner")
    db.add("tenant_users", tenant_id=B, user_id="owner-b", role="owner")
    # leads
    db.add("leads", id=LEAD_A, tenant_id=A, name="Priya", phone="919000000001", segment="A", source="whatsapp",
           score=80, created_at=_ago(days=1), deleted_at=None, ad_campaign_id="camp-a", converted_at=None)
    db.add("leads", id="11111111-1111-1111-1111-222222222222", tenant_id=A, name="Karthik", phone="919000000002",
           segment="C", source="instagram", score=20, created_at=_ago(days=2), deleted_at=None,
           ad_campaign_id=None, converted_at=None)
    db.add("leads", id=LEAD_B, tenant_id=B, name="SECRET-B", phone="919999999999", segment="A", source="whatsapp",
           score=90, created_at=_ago(days=1), deleted_at=None, ad_campaign_id="camp-b", converted_at=None)
    # orders (deals), with a payment link and a bill token that must never come out
    db.add("deals", id=DEAL_A, tenant_id=A, deal_number=7, stage="won", channel="online", total_paise=50000,
           paid_paise=20000, refunded_paise=0, gst_paise=0, lead_id=LEAD_A, customer_name="Priya",
           created_at=_ago(days=1), payment_link="https://pay.example/SECRET-LINK", bill_token="BILL-TOKEN-SECRET",
           notes="deliver evening", handover=None, delivery_status=None, bill_type="gst")
    db.add("deals", id=DEAL_B, tenant_id=B, deal_number=3, stage="won", channel="online", total_paise=99999,
           paid_paise=99999, refunded_paise=0, gst_paise=0, lead_id=LEAD_B, customer_name="SECRET-B",
           created_at=_ago(days=1), payment_link="https://pay.example/SECRET-B", bill_token="OTHER-TOKEN",
           handover=None, delivery_status=None, bill_type="gst")
    db.add("deal_items", tenant_id=A, deal_id=DEAL_A, name="Silk saree", qty=1, unit_price_paise=50000,
           gst_rate=5, line_total_paise=50000, variant_label=None, created_at=_ago(days=1))
    db.add("deal_items", tenant_id=B, deal_id=DEAL_B, name="SECRET-B item", qty=1, unit_price_paise=99999,
           gst_rate=5, line_total_paise=99999, variant_label=None, created_at=_ago(days=1))
    db.add("deal_payments", tenant_id=A, deal_id=DEAL_A, amount_paise=20000, method="upi", kind="advance",
           paid_at=_ago(hours=5), note="first half", razorpay_signature="signed-SECRET")
    db.add("deal_payments", tenant_id=B, deal_id=DEAL_B, amount_paise=99999, method="cash", kind="full",
           paid_at=_ago(hours=5), note="SECRET-B paid")
    db.add("deal_refunds", tenant_id=A, deal_id=DEAL_A, amount_paise=500, method="cash", reason="small",
           status="done", credit_note_number="CN1", created_at=_ago(hours=2))
    db.add("deal_refunds", tenant_id=B, deal_id=DEAL_B, amount_paise=7777, method="cash", reason="SECRET-B",
           status="done", credit_note_number="CNB", created_at=_ago(hours=2))
    # settings: the Razorpay keys must only ever turn into "connected: yes"
    db.add("app_settings", tenant_id=A, key="razorpay_key_id", value="rzp-SECRET-VALUE")
    db.add("app_settings", tenant_id=A, key="razorpay_key_secret", value="rzp-SECRET-VALUE")
    db.add("app_settings", tenant_id=B, key="razorpay_key_id", value="OTHER")
    return db


class Rpcs:
    """Records every RPC call and answers from `rows[name]` (a dict tenant_id -> rows)."""

    def __init__(self, db: FakeSupabase, rows: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.rows = rows or {}
        self.names = frozenset(self.rows)
        for name in self.rows:
            db.rpc_handlers[name] = lambda p, n=name: self._answer(n, p)

    def _answer(self, name: str, params: dict):
        self.calls.append((name, params))
        return self.rows[name].get(params.get("p_tenant_id"), [])

    def tenants(self, name: str) -> set:
        return {p.get("p_tenant_id") for n, p in self.calls if n == name}


@contextmanager
def signed_in(db: FakeSupabase, tenant: str = A, rpcs: Rpcs | None = None):
    """The tool runs as `tenant`'s owner, with the database behind the real read-only guard."""
    allowed = rpcs.names if rpcs else frozenset()
    token = supabase_db.read_only.set(True)
    try:
        with patch.object(supabase_db, "_client", db), \
             patch.object(supabase_db, "READ_ONLY_RPCS", allowed), \
             wrapper.acting_as(tenant):
            yield
    finally:
        supabase_db.read_only.reset(token)


def run(tool, db=None, tenant: str = A, rpcs: Rpcs | None = None, **kwargs):
    """Call the tool's plain function, then prove it wrote nothing and leaked no secret."""
    db = db or seeded()
    before = deepcopy(db.tables)
    with signed_in(db, tenant, rpcs):
        out = tool(**kwargs)
    # (the fake creates an empty table the first time one is read; that is not a change)
    assert {k: v for k, v in db.tables.items() if v} == {k: v for k, v in before.items() if v}, "the tool changed data"
    text = json.dumps(out, default=str)
    for secret in SECRETS:
        assert secret not in text, f"{secret} leaked"
    return out, text


def test_every_tool_is_registered_with_no_client_argument():
    import inspect
    names = ["reports_overview", "reports_funnel", "reports_compare", "reports_templates", "reports_telecalling",
             "meta_ads", "orders", "order_details", "purchase_orders", "suppliers", "payments_overview",
             "sales_target"]
    forbidden = {"tenant", "tenant_id", "client", "client_id", "user_id", "owner_id"}
    for name in names:
        spec = wrapper.REGISTRY[name]
        assert spec.kind == wrapper.READ
        assert not forbidden & set(inspect.signature(spec.fn).parameters), name
        assert inspect.getdoc(spec.fn)
        assert not inspect.iscoroutinefunction(spec.fn)


# ── orders ────────────────────────────────────────────────────────────────────

def test_orders_shows_only_this_clients_orders_money_and_no_links():
    out, text = run(money.orders)
    assert [o["id"] for o in out["orders"]] == [DEAL_A]
    assert out["cards"]["money_in"]["paise"] == 19500  # 20000 received less 500 refunded
    assert "SECRET-B" not in text and "OTHER" not in text and "99999" not in text
    assert out["day_closing_today"]["day"]
    assert "working_label" in out["settings"]


def test_orders_other_client_sees_its_own():
    out, text = run(money.orders, tenant=B)
    assert [o["id"] for o in out["orders"]] == [DEAL_B]
    assert "Priya" not in text


def test_orders_rejects_a_bad_status_and_a_bad_limit():
    with pytest.raises(ToolError):
        run(money.orders, status="bogus")
    with pytest.raises(ToolError):
        run(money.orders, limit=51)
    with pytest.raises(ToolError):
        run(money.orders, days=0)


def test_order_details_one_order_without_links_or_tokens():
    out, text = run(money.order_details, order_id=DEAL_A)
    assert out["id"] == DEAL_A and out["total_paise"] == 50000
    assert [i["name"] for i in out["items_full"]] == ["Silk saree"]
    assert [p["amount_paise"] for p in out["payments"]] == [20000]
    assert [r["amount_paise"] for r in out["refunds"]] == [500]
    assert "payment_link" not in out and "bill_token" not in out
    assert "razorpay_signature" not in text


def test_order_details_refuses_another_clients_order_and_junk_ids():
    for bad in (DEAL_B, "not-a-uuid", "d9999999-9999-9999-9999-999999999999"):
        with pytest.raises(ToolError, match="No order with that id in your account"):
            run(money.order_details, order_id=bad)


# ── payments and target ──────────────────────────────────────────────────────

def test_payments_overview_is_this_clients_money_and_hides_the_razorpay_keys():
    out, text = run(money.payments_overview)
    assert [p["amount_paise"] for p in out["recent_payments"]] == [20000]
    assert out["recent_payments"][0]["order"] == "D-0007"
    razorpay = next(w for w in out["ways_to_pay"] if w["key"] == "razorpay")
    assert razorpay["ok"] is True
    assert "99999" not in text and "SECRET-B" not in text


def test_payments_overview_other_client_has_no_razorpay():
    out, _ = run(money.payments_overview, tenant=B)
    assert [p["amount_paise"] for p in out["recent_payments"]] == [99999]


def test_sales_target_reads_this_clients_target_only():
    db = seeded()
    month = money.sales_target_service.month_key(datetime.now(timezone.utc))
    db.add("app_settings", tenant_id=A, key=money.sales_target_service.KEY,
           value=json.dumps({"monthly_paise": 100000, "months": {}, "show_team": True}))
    db.add("app_settings", tenant_id=B, key=money.sales_target_service.KEY,
           value=json.dumps({"monthly_paise": 777777, "months": {}, "show_team": False}))
    out, text = run(money.sales_target, db=db)
    assert out["monthly_paise"] == 100000
    assert out["this_month"]["month"] == month and out["this_month"]["target_paise"] == 100000
    assert out["this_month"]["money_in_paise"] == 19500
    assert "777777" not in text


# ── purchases ────────────────────────────────────────────────────────────────

def purchases_db():
    db = seeded()
    for tenant, name in ((A, "Ravi Textiles"), (B, "OTHER Supplier")):
        sid = f"s-{tenant[:1]}"
        db.add("suppliers", id=sid, tenant_id=tenant, name=name, phone="9100000000", city="Salem", gstin=None,
               supplies="silk", archived=False, bank_account="123456789012")
        db.add("stock_ins", id=f"si-{tenant[:1]}", tenant_id=tenant, supplier_id=sid, bill_date=NOW.date().isoformat(),
               total_paise=100000, due_date=None, pay_status="unpaid", items_paise=95000, gst_paise=5000,
               bill_no="B1" if tenant == A else "OTHER-B", bill_image_url="https://x/signed-SECRET")
        db.add("purchase_orders", id=f"po-{tenant[:1]}", tenant_id=tenant, supplier_id=sid, number=1,
               status="sent", need_by=None, items_paise=95000, gst_paise=5000, created_at=_ago(days=1),
               access_token="SECRET-ACCESS-TOKEN")
        db.add("purchase_order_lines", tenant_id=tenant, purchase_order_id=f"po-{tenant[:1]}", label="Saree",
               catalog_item_id="item-1", variant_id=None, qty_ordered=10, qty_received=0)
    return db


def test_suppliers_only_this_clients_suppliers_without_bank_fields():
    out, text = run(money.suppliers, db=purchases_db())
    assert [s["name"] for s in out["suppliers"]] == ["Ravi Textiles"]
    assert out["suppliers"][0]["owe_paise"] == 100000
    assert "OTHER" not in text and "123456789012" not in text and "bank_account" not in text


def test_purchase_orders_only_this_clients_orders_and_bills_without_secrets():
    out, text = run(money.purchase_orders, db=purchases_db())
    assert [p["supplier_name"] for p in out["purchase_orders"]] == ["Ravi Textiles"]
    assert [b["bill_no"] for b in out["stock_in_latest"]] == ["B1"]
    assert "OTHER" not in text and "access_token" not in text and "bill_image_url" not in text


def test_purchase_orders_limit_is_checked():
    for bad in (0, 51):
        with pytest.raises(ToolError):
            run(money.purchase_orders, limit=bad)


# ── reports (these use database RPCs) ────────────────────────────────────────

def overview_rpcs(db) -> Rpcs:
    return Rpcs(db, {
        "analytics_daily_messages": {A: [{"day": _ago().split("T")[0], "inbound": 4, "outbound": 3, "ai": 2, "human": 1}],
                                     B: [{"day": _ago().split("T")[0], "inbound": 999, "outbound": 0, "ai": 0, "human": 0}]},
        "analytics_period_money": {A: [{"spend": 1500, "ad_leads": 2}], B: [{"spend": 424242, "ad_leads": 9}]},
        "analytics_response_times": {A: [{"p50_seconds": 30}], B: [{"p50_seconds": 4242}]},
        "analytics_daily_returning_ad_leads": {A: [], B: []},
    })


def test_reports_overview_asks_every_rpc_for_this_client_only():
    db = seeded()
    rpcs = overview_rpcs(db)
    out, text = run(money.reports_overview, db=db, rpcs=rpcs, days=30)
    assert out["range_used"] == "30d" and out["money"]["spend"] == 1500
    assert out["total_leads"] == 2 and out["by_segment"]["A"] == 1
    assert {n for n, _ in rpcs.calls} == set(rpcs.names)
    for name in rpcs.names:
        assert rpcs.tenants(name) == {A}, name
    assert "424242" not in text and "999" not in text and "SECRET-B" not in text


@pytest.mark.parametrize("days, window", [(1, "today"), (7, "7d"), (8, "30d"), (366, "30d")])
def test_reports_overview_maps_days_to_the_window_reports_has(days, window):
    db = seeded()
    out, _ = run(money.reports_overview, db=db, rpcs=overview_rpcs(db), days=days)
    assert out["range_used"] == window


def test_reports_overview_rejects_bad_days():
    for bad in (0, 367):
        with pytest.raises(ToolError):
            run(money.reports_overview, days=bad)


def test_reports_overview_is_refused_until_its_rpcs_are_allowed():
    # the planner's allowlist (READ_ONLY_RPCS) must name every RPC the tool needs
    with pytest.raises(ReadOnlyViolation):
        run(money.reports_overview, db=seeded(), rpcs=None, days=7)


def test_reports_funnel_counts_only_this_clients_leads():
    out, text = run(money.reports_funnel)
    assert out["total_leads"] == 2 and out["by_source"]["whatsapp"] == 1 and out["by_source"]["instagram"] == 1
    assert out["by_segment"]["A"] == 1 and out["by_segment"]["C"] == 1
    assert "SECRET-B" not in text


COMPARE_RPCS = ("analytics_period_summary", "analytics_daily_leads", "analytics_daily_messages",
                "analytics_period_money", "analytics_segment_movement", "analytics_response_times",
                "analytics_lead_arrival_heatmap")


def compare_rpcs(db) -> Rpcs:
    rows = {name: {A: [], B: []} for name in COMPARE_RPCS}
    rows["analytics_period_summary"] = {A: [{"new_leads": 5}], B: [{"new_leads": 4242}]}
    return Rpcs(db, rows)


def test_reports_compare_period_and_previous_use_this_client():
    db = seeded()
    rpcs = compare_rpcs(db)
    out, text = run(money.reports_compare, db=db, rpcs=rpcs, preset="last_7d")
    assert out["current"]["summary"]["new_leads"] == 5 and out["previous"] is not None
    assert rpcs.tenants("analytics_period_summary") == {A}
    assert len([c for c in rpcs.calls if c[0] == "analytics_period_summary"]) == 2  # period + previous
    assert "4242" not in text


def test_reports_compare_alone_and_bad_input():
    db = seeded()
    out, _ = run(money.reports_compare, db=db, rpcs=compare_rpcs(db), compare_to_previous=False)
    assert out["previous"] is None
    for kwargs in ({"preset": "nonsense"}, {"preset": "custom"}, {"preset": "custom", "start": "2026-11-05", "end": "2026-11-01"}):
        # the wrapper turns the route's 400 into a ToolError; the plain function raises it as is
        with pytest.raises((ToolError, HTTPException)):
            run(money.reports_compare, db=db, rpcs=compare_rpcs(db), **kwargs)


def test_reports_templates_asks_for_this_client_and_caps_the_list():
    db = seeded()
    rows = [{"template_name": f"t{i}", "sent": i} for i in range(60)]
    rpcs = Rpcs(db, {"template_performance_range": {A: rows, B: [{"template_name": "SECRET-B", "sent": 1}]}})
    out, text = run(money.reports_templates, db=db, rpcs=rpcs, days=30)
    assert rpcs.tenants("template_performance_range") == {A}
    assert len(out["rows"]) == 50 and out["total"] == 60 and out["more"] is True
    assert "SECRET-B" not in text
    with pytest.raises(ToolError):
        run(money.reports_templates, db=db, rpcs=rpcs, days=0)


def test_reports_telecalling_counts_only_this_clients_calls():
    db = seeded()
    for tenant, caller, name, user in ((A, "c-a", "Asha", "u-a"), (B, "c-b", "SECRET-B caller", "u-b")):
        db.add("callers", id=caller, tenant_id=tenant, name=name, user_id=user, active=True)
        for _ in range(2 if tenant == A else 5):
            db.add("call_logs", tenant_id=tenant, caller_id=caller, duration_seconds=60, outcome="interested",
                   manual_status="connected", created_at=_ago(minutes=5), lead_id=None)
    rpcs = Rpcs(db, {"get_telecalling_all_time_stats": {A: [], B: []}})
    out, text = run(money.reports_telecalling, db=db, rpcs=rpcs)
    assert out["calls_today"] == 2
    assert rpcs.tenants("get_telecalling_all_time_stats") == {A}
    assert "SECRET-B" not in text and "Asha" in text


def test_reports_telecalling_dates_both_or_neither_and_max_range():
    db = seeded()
    rpcs = Rpcs(db, {"get_telecalling_all_time_stats": {A: []}})
    for kwargs in ({"from_date": "2026-11-01"}, {"from_date": "2026-11-05", "to_date": "2026-11-01"},
                   {"from_date": "2026-01-01", "to_date": "2026-11-01"}, {"from_date": "x", "to_date": "y"}):
        with pytest.raises(ToolError):
            run(money.reports_telecalling, db=db, rpcs=rpcs, **kwargs)
    out, _ = run(money.reports_telecalling, db=db, rpcs=rpcs, from_date="2026-11-01", to_date="2026-11-07")
    assert out["calls_today"] == 0


# ── ads ──────────────────────────────────────────────────────────────────────

def ads_db():
    db = seeded()
    month = money.google_ads_report.current_month_ist()
    for tenant, camp, platform, name in ((A, "camp-a", "meta", "Diwali Meta"), (A, "g-a", "google", "Diwali Google"),
                                         (B, "camp-b", "meta", "SECRET-B Meta"), (B, "g-b", "google", "SECRET-B Google")):
        db.add("ad_campaigns", id=camp, tenant_id=tenant, platform=platform, campaign_name=name,
               external_campaign_id=camp, spend_inr=1000, google_campaign_name=None, created_at=_ago(days=3),
               access_token="SECRET-ACCESS-TOKEN")
    db.add("google_ads_spend", tenant_id=A, campaign_id="g-a", month=f"{month}-01", spend_paise=250000, clicks=40, source="hand")
    db.add("google_ads_spend", tenant_id=B, campaign_id="g-b", month=f"{month}-01", spend_paise=999000, clicks=77, source="hand")
    db.add("meta_lead_forms", tenant_id=A, form_id="f-a", name="Saree enquiry", status="ACTIVE",
           meta_created_at=_ago(days=10), template_id=None, questions=[1, 2], page_access_token="SECRET-ACCESS-TOKEN")
    db.add("meta_lead_forms", tenant_id=B, form_id="f-b", name="SECRET-B form", status="ACTIVE",
           meta_created_at=_ago(days=10), template_id=None, questions=[1])
    db.add("meta_form_leads", tenant_id=A, form_id="f-a", ad_id="1", is_organic=False, phone="9", lead_id=None,
           template_status="sent", template_sent_at=_ago(days=2), meta_created_at=_ago(days=2), ad_name="Ad A")
    db.add("meta_form_leads", tenant_id=B, form_id="f-b", ad_id="2", is_organic=False, phone="8", lead_id=None,
           template_status="failed", template_sent_at=None, meta_created_at=_ago(days=2), ad_name="SECRET-B ad")
    return db


def test_meta_ads_shows_only_this_clients_campaigns_forms_and_google_spend():
    out, text = run(money.meta_ads, db=ads_db())
    assert [c["campaign_name"] for c in out["ad_performance"]["campaigns"]] == ["Diwali Meta"]
    assert [r["name"] for r in out["google_ads"]["rows"]] == ["Diwali Google"]
    assert out["google_ads"]["rows"][0]["spent_paise"] == 250000
    assert [f["name"] for f in out["instant_forms"]["forms"]] == ["Saree enquiry"]
    assert out["instant_forms"]["totals"]["leads"] == 1 and out["instant_forms"]["totals"]["template_sent"] == 1
    assert "spend" not in out["instant_forms"]["totals"]  # live Meta spend is not fetched
    assert out["inbound_leads"]["kpis"]["range"]["total"] == 2  # A's two leads, not B's
    assert out["ad_performance"]["totals"]["tracked_leads"] == 1
    for part in ("ad_performance", "inbound_leads", "google_ads", "instant_forms"):
        assert not out[part].get("unavailable"), part
    assert "SECRET-B" not in text and "999000" not in text


def test_meta_ads_makes_no_call_to_meta(monkeypatch):
    import app.services.meta_lead_forms as forms_service
    def boom(*a, **k):
        raise AssertionError("tried to call Meta")
    monkeypatch.setattr(forms_service, "_get", boom)
    monkeypatch.setattr(forms_service, "_get_url", boom)
    out, _ = run(money.meta_ads, db=ads_db())
    assert out["instant_forms"]["forms"]


def test_meta_ads_checks_days_and_month():
    with pytest.raises(ToolError):
        run(money.meta_ads, db=ads_db(), days=93)
    with pytest.raises(ToolError, match="Month must look like"):
        run(money.meta_ads, db=ads_db(), month="November")
