"""Shared test data for the Reports tests: one shop (T1) with a week of activity, and a second shop (T2)
whose rows must never show up. Days: picked = 2026-10-10..16, the days before = 2026-10-03..09."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datetime import date

from fake_supabase import FakeSupabase
from app.services.reports_common import Period

T1, T2 = "t1", "t2"
PERIOD = Period(date(2026, 10, 10), date(2026, 10, 16))


def at(day: int, hour: int = 6, minute: int = 30) -> str:
    """An October 2026 time, written as the database writes it (UTC)."""
    return f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00+00:00"


class MissingTables(FakeSupabase):
    """A database where some tables (or database functions) are not there yet (migration not applied)."""
    def __init__(self, *missing):
        super().__init__()
        self.missing = set(missing)

    def table(self, name):
        if name in self.missing:
            raise Exception(f'relation "{name}" does not exist')
        return super().table(name)

    def rpc(self, name, params):
        if name in self.missing:
            raise Exception(f"function {name} does not exist")
        return super().rpc(name, params)


def seed(db: FakeSupabase) -> FakeSupabase:
    for lid, source, day, seg, extra in [
        ("L1", "whatsapp", 11, "A", {"name": "Asha", "phone": "919000000001", "ad_campaign_id": "camp-m"}),
        ("L2", "instagram", 12, "B", {"name": "Bala", "phone": "919000000002"}),
        ("L3", "qr", 12, "A", {"name": "Chitra", "phone": "919000000003"}),
        ("L4", "meta_form", 13, "C", {"name": "Dev", "phone": "919000000004", "ad_campaign_id": "camp-g"}),
        ("L5", "whatsapp", 5, "C", {"name": "Esha", "phone": "919000000005"}),
        ("L6", "upload", 11, "C", {"name": "Farid", "phone": "919000000006"}),
    ]:
        db.add("leads", id=lid, tenant_id=T1, source=source, created_at=at(day), segment=seg, **extra)
    db.add("leads", id="X1", tenant_id=T2, source="whatsapp", created_at=at(11), segment="A", name="Other shop")

    db.add("ad_campaigns", id="camp-m", tenant_id=T1, campaign_name="Diwali Meta", platform="meta")
    db.add("ad_campaigns", id="camp-g", tenant_id=T1, campaign_name="Search Google", platform="google")
    db.add("ad_creatives", id="cr1", tenant_id=T1, campaign_id="camp-m")
    db.add("ad_insights_daily", tenant_id=T1, ad_creative_id="cr1", insight_date="2026-10-12", spend=500.0)
    db.add("google_ads_spend", tenant_id=T1, campaign_id="camp-g", month="2026-10-01", spend_paise=3_100_000)

    deal = dict(tenant_id=T1, stage="won", refunded_paise=0, deal_number="D")
    db.add("deals", id="D0", lead_id="L5", total_paise=20_000, gst_paise=0, paid_paise=20_000, won_at=at(4), **deal)
    db.add("deals", id="D1", lead_id="L1", total_paise=118_000, gst_paise=18_000, paid_paise=118_000, won_at=at(12),
           bill_type="gst", buyer_gstin="33AAAAA0000A1Z5", buyer_business="Asha Traders", sold_by_ai=True,
           customer_name="Asha", invoice_number="INV-1", payment_method="upi", **deal)
    db.add("deals", id="D2", lead_id="L5", total_paise=50_000, gst_paise=0, paid_paise=50_000, won_at=at(14),
           sold_by="c1", customer_name="Esha", invoice_number="INV-2", payment_method="cash", **deal)
    db.add("deals", id="D3", tenant_id=T1, stage="awaiting_payment", lead_id="L2", total_paise=30_000, paid_paise=10_000)
    db.add("deals", id="D4", tenant_id=T1, stage="lost", lead_id="L2", total_paise=10_000, lost_at=at(13))
    db.add("deals", id="D5", tenant_id=T1, stage="quoted", lead_id="L2", total_paise=7_000)
    db.add("deals", id="DX", tenant_id=T2, stage="won", lead_id="X1", total_paise=999_999, gst_paise=0, won_at=at(12))
    db.add("deal_items", tenant_id=T1, deal_id="D1", name="Rice 5kg", qty=2, line_total_paise=118_000)
    db.add("deal_items", tenant_id=T1, deal_id="D2", name="Oil", qty=1, line_total_paise=50_000)
    db.add("deal_refunds", tenant_id=T1, deal_id="D1", amount_paise=5_000, method="upi", status="done", created_at=at(13),
           credit_note_number="CN-1", reason="Damaged")
    db.add("deal_payments", tenant_id=T1, deal_id="D1", amount_paise=118_000, method="upi", paid_at=at(12))
    db.add("deal_payments", tenant_id=T1, deal_id="D2", amount_paise=50_000, method="cash", paid_at=at(14))
    return db


def seed_money(db: FakeSupabase) -> FakeSupabase:
    db.add("catalog_items", id="i1", tenant_id=T1, name="Rice 5kg", stock_quantity=2, cost_price_paise=20_000)
    db.add("catalog_items", id="i2", tenant_id=T1, name="Salt", stock_quantity=1, cost_price_paise=None)
    db.add("catalog_items", id="i3", tenant_id=T1, name="Ghee", stock_quantity=100, cost_price_paise=None)
    db.add("stock_movements", tenant_id=T1, catalog_item_id="i1", delta=-2, reason="sale", created_at=at(12))
    db.add("cash_expenses", tenant_id=T1, amount_paise=7_000, day="2026-10-13", label="Tea")
    db.add("stock_ins", id="b1", tenant_id=T1, supplier_id="s1", bill_date="2026-10-11", total_paise=60_000, gst_paise=9_000)
    db.add("suppliers", id="s1", tenant_id=T1, name="Wholesale Co", gstin="33BBBBB0000B1Z5")
    db.add("supplier_payments", tenant_id=T1, supplier_id="s1", amount_paise=20_000)
    db.add("day_closings", tenant_id=T1, day="2026-10-14", difference_paise=-2_500)
    return db
