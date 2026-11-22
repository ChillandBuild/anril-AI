"""Item page bits (migration 315): an item's own advance (per piece / percent), what the AI may say
(price not shared, discount up to a cap enforced in code) and the AI's link asking only the advance."""
import asyncio
from unittest.mock import patch

import pytest

from app.services import ai_reply, deal_actions, deals
from app.services import order_quotes as oq
from tests.fake_supabase import FakeSupabase

T = "aaaaaaaa-0000-0000-0000-000000000001"
GOWN, SAREE = "cccccccc-0000-0000-0000-000000000001", "cccccccc-0000-0000-0000-000000000002"


@pytest.fixture
def db():
    db = FakeSupabase()
    db.add("catalog_items", id=GOWN, tenant_id=T, name="Party wear gown", price_paise=420000,
           advance_rule={"kind": "fixed", "value": 1000})
    db.add("catalog_items", id=SAREE, tenant_id=T, name="Cotton saree", price_paise=95000, advance_rule=None)
    return db


def _lines(*pairs):
    return [{"catalog_item_id": i, "qty": q, "line_total_paise": p * q} for i, q, p in pairs]


class TestOrderAdvance:
    def test_fixed_is_per_piece_and_never_more_than_the_line(self, db):
        with patch.object(oq, "advance_rule", return_value={"kind": "none", "value": 0, "min_total_paise": 0}):
            assert oq.order_advance(db, T, _lines((GOWN, 2, 420000)), 840000) == 200000
            db.rows("catalog_items")[0]["advance_rule"] = {"kind": "fixed", "value": 9000}
            assert oq.order_advance(db, T, _lines((GOWN, 1, 420000)), 420000) == 420000

    def test_own_rule_lines_and_shop_rule_lines_add_up(self, db):
        shop = {"kind": "percent", "value": 30, "min_total_paise": 0}
        with patch.object(oq, "advance_rule", return_value=shop):
            got = oq.order_advance(db, T, _lines((GOWN, 1, 420000), (SAREE, 2, 95000)), 610000)
        assert got == 100000 + round(190000 * 0.30)

    def test_no_own_rules_is_exactly_the_shop_rule(self, db):
        db.rows("catalog_items")[0]["advance_rule"] = None
        shop = {"kind": "percent", "value": 30, "min_total_paise": 500000}
        with patch.object(oq, "advance_rule", return_value=shop):
            assert oq.order_advance(db, T, _lines((SAREE, 1, 95000)), 95000) == 0  # below the shop's minimum

    @pytest.mark.parametrize("raw, ok", [({"kind": "percent", "value": 30}, True), ({"kind": "percent", "value": 130}, False),
                                         ({"kind": "fixed", "value": 0}, False), ({"kind": "none"}, True), (None, True)])
    def test_item_rules_are_checked(self, raw, ok):
        if ok:
            oq.clean_item_rule(raw)
        else:
            with pytest.raises(oq.OrderError):
                oq.clean_item_rule(raw)


class TestWhatTheAiMaySay:
    def _prompt(self, **extra):
        row = {"id": GOWN, "name": "Party wear gown", "item_type": "product", "price_paise": 420000, "stock_quantity": 2, **extra}
        return ai_reply.catalog_prompt([row], "", {"can_recommend": True})[0]

    def test_price_not_shared_means_no_price_in_the_prompt(self):
        text = self._prompt(ai_share_price=False)
        assert "PRICE NOT SHARED" in text and "4200" not in text and "4,200" not in text

    def test_discount_limit_and_advance_are_told(self):
        text = self._prompt(ai_max_discount_pct=5, advance_text="₹1,000 per piece")
        assert "up to 5% off" in text and "advance to book: ₹1,000 per piece" in text


class TestSendQuote:
    def _ctx(self, **item):
        from types import SimpleNamespace
        catalog = {GOWN: {"id": GOWN, "name": "Party wear gown", "price_paise": 420000, "stock_quantity": None, **item}}
        return SimpleNamespace(catalog=catalog), catalog

    def test_price_not_shared_refuses_a_link(self):
        ctx, catalog = self._ctx(ai_share_price=False)
        lines, problem = deal_actions._quote_lines(ctx, {"item_ids": [GOWN]})
        assert lines == [] and "team shares the price" in problem

    def test_discount_is_capped_in_code(self):
        ctx, catalog = self._ctx(ai_max_discount_pct=5)
        assert "at most 5%" in deal_actions._quote_lines(ctx, {"item_ids": [GOWN], "discount_pct": 10})[1]
        lines, problem = deal_actions._quote_lines(ctx, {"item_ids": [GOWN], "discount_pct": 5})
        assert problem is None and lines[0]["unit_price_paise"] == 399000

    def test_no_discount_allowed_by_default(self):
        ctx, catalog = self._ctx()
        assert "no discount is allowed" in deal_actions._quote_lines(ctx, {"item_ids": [GOWN], "discount_pct": 3})[1]

    def test_the_quote_says_what_the_link_asks(self):
        text = deal_actions._quote_text([{"name": "Party wear gown", "qty": 1, "line_total_paise": 420000}], 420000, "https://rzp/x", 100000)
        assert "Advance to book: ₹1,000" in text and "₹3,200, later" in text and "Pay the advance here" in text


def test_the_ai_deal_link_asks_only_the_advance(db, monkeypatch):
    seen = {}

    async def fake_link(tenant_id, deal_id, *, send_whatsapp_message=True, amount_paise=None, db=None):
        seen["amount"] = amount_paise
        return {"payment_link": "https://rzp/x", "message_sent": False, "deal_patch": {}}

    monkeypatch.setattr(deals, "send_payment_link", fake_link)
    monkeypatch.setattr(deals, "_next_deal_number", lambda db, t: 7)
    monkeypatch.setattr(deals, "_deal_total", lambda t, lines, db: sum(li["line_total_paise"] for li in lines))
    monkeypatch.setattr(oq, "advance_rule", lambda t: {"kind": "none", "value": 0, "min_total_paise": 0})
    db.add("leads", id="lead-1", tenant_id=T)
    out = asyncio.run(deals.create_deal(T, "lead-1", [{"catalog_item_id": GOWN, "qty": 1}], "whatsapp", "awaiting_payment",
                                        advance_by_rule=True, db=db))
    assert seen["amount"] == 100000 and out["deal"]["advance_paise"] == 100000
