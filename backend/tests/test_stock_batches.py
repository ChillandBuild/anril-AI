"""Batches & expiry (migration 310, services/stock_batches.py): buckets, which batch a sale takes and
its price, bill lines, returns into the same batch, the tab's numbers, actions, the daily bell, the
AI's offer line and supplier dues. The SQL (_stock_change) is a stand-in here; it was run on the
live database inside a rolled-back transaction."""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.services import ai_reply, deals, purchases
from app.services import stock_batches as sb
from tests.fake_supabase import FakeSupabase

T = "aaaaaaaa-0000-0000-0000-000000000001"
SHOP = "bbbbbbbb-0000-0000-0000-000000000001"
PARA, PLAIN = "cccccccc-0000-0000-0000-000000000001", "cccccccc-0000-0000-0000-000000000002"
B_OLD, B_NEW, B_GONE, B_FIRST = (f"dddddddd-0000-0000-0000-00000000000{i}" for i in (1, 2, 3, 4))
SUP = "eeeeeeee-0000-0000-0000-000000000001"
TODAY = sb.today()


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture
def db():
    db = FakeSupabase()
    db.add("stock_places", id=SHOP, tenant_id=T, name="Shop", archived=False)
    db.add("suppliers", id=SUP, tenant_id=T, name="Sri Ram Pharma", archived=False)
    db.add("catalog_items", id=PARA, tenant_id=T, name="Paracetamol 650", price_paise=3000, gst_rate=12,
           tracks_batches=True, stock_quantity=60)
    db.add("catalog_items", id=PLAIN, tenant_id=T, name="Cotton saree", price_paise=95000, gst_rate=5,
           tracks_batches=False, stock_quantity=5)
    common = dict(tenant_id=T, catalog_item_id=PARA, variant_id=None, place_id=SHOP, status="active",
                  cost_paise=2000, supplier_id=SUP, sell_first=False, discount_pct=0)
    db.add("stock_batches", id=B_OLD, batch_no="PC2307", expiry_date=d(8), quantity=20, created_at="2026-01-01", **common)
    db.add("stock_batches", id=B_NEW, batch_no="PC2401", expiry_date=d(200), quantity=30, created_at="2026-02-01", **common)
    db.add("stock_batches", id=B_GONE, batch_no="PC2201", expiry_date=d(-3), quantity=10, created_at="2025-12-01", **common)
    return db


class TestBuckets:
    @pytest.mark.parametrize("days, want", [(-1, "expired"), (0, "soon"), (30, "soon"), (31, "later"),
                                            (90, "later"), (91, "fine"), (None, "fine")])
    def test_expiry_buckets(self, days, want):
        assert sb.bucket(d(days) if days is not None else None, TODAY) == want

    def test_label_for_bills(self):
        assert sb.label({"batch_no": "PC2307", "expiry_date": "2026-11-30"}) == "Batch PC2307 · Exp 30 Nov 2026"
        assert sb.label({"batch_no": "", "expiry_date": None}) == "No batch no."


class TestWhichBatchAndPrice:
    def test_the_first_expiring_sellable_batch_is_next_and_expired_never(self, db):
        assert [b["id"] for b in sb.item_batches(db, T, PARA)][:2] == [B_GONE, B_OLD]
        assert sb.sale_price(db, T, PARA, None, 3000)[1]["id"] == B_OLD

    def test_sell_first_beats_the_expiry_order(self, db):
        db.rows("stock_batches")[1]["sell_first"] = True
        assert sb.sale_price(db, T, PARA, None, 3000)[1]["id"] == B_NEW

    def test_a_discount_on_the_batch_being_sold_lowers_the_price(self, db):
        db.rows("stock_batches")[0]["discount_pct"] = 20
        assert sb.sale_price(db, T, PARA, None, 3000)[0] == 2400
        assert sb.sale_price(db, T, PARA, None, 3000, batch_id=B_NEW)[0] == 3000  # staff picked another batch

    def test_bill_lines_get_the_discounted_price_and_keep_the_chosen_batch(self, db):
        db.rows("stock_batches")[0]["discount_pct"] = 20
        line = deals._resolve_lines(T, [{"catalog_item_id": PARA, "qty": 2}], db)[0]
        assert line["unit_price_paise"] == 2400 and "batch_id" not in line
        line = deals._resolve_lines(T, [{"catalog_item_id": PARA, "qty": 1, "batch_id": B_NEW}], db)[0]
        assert line["unit_price_paise"] == 3000 and line["batch_id"] == B_NEW

    def test_an_expired_batch_can_never_be_put_on_a_bill(self, db):
        with pytest.raises(deals.DealError, match="can't be sold"):
            deals._resolve_lines(T, [{"catalog_item_id": PARA, "qty": 1, "batch_id": B_GONE}], db)

    def test_items_without_batches_are_untouched(self, db):
        line = deals._resolve_lines(T, [{"catalog_item_id": PLAIN, "qty": 1}], db)[0]
        assert line["unit_price_paise"] == 95000 and "batch_id" not in line


class TestSellingAndReturns:
    def _db(self, lines, picks=()):
        db = MagicMock()
        data = {"deal_items": lines, "deals": [{"channel": "store"}], "deal_item_batches": list(picks)}

        def table(name):
            q = MagicMock()
            for m in ("select", "eq", "in_", "limit", "order"):
                getattr(q, m).return_value = q
            q.execute.return_value.data = data.get(name, [])
            return q

        db.table.side_effect = table
        db.rpc.return_value.execute.return_value.data = [{"ok": True, "tracked": True, "quantity_after": 1}]
        return db

    def test_a_sale_names_the_bill_line_and_the_chosen_batch(self):
        db = self._db([{"id": "li-1", "catalog_item_id": PARA, "variant_id": None, "name": "Para", "qty": 3, "batch_id": B_NEW}])
        deals._deduct_for_deal(T, "deal-1", None, db, direction=-1)
        params = db.rpc.call_args[0][1]
        assert params["p_batch_id"] == B_NEW and params["p_deal_item_id"] == "li-1" and params["p_delta"] == -3

    def test_if_the_chosen_batch_cant_cover_it_the_usual_order_takes_over(self):
        db = self._db([{"id": "li-1", "catalog_item_id": PARA, "variant_id": None, "name": "Para", "qty": 3, "batch_id": B_NEW}])
        db.rpc.return_value.execute.side_effect = [MagicMock(data=[{"ok": False, "tracked": True, "quantity_after": 0}]),
                                                   MagicMock(data=[{"ok": True, "tracked": True, "quantity_after": 0}])]
        assert deals._deduct_for_deal(T, "deal-1", None, db, direction=-1) == []
        assert "p_batch_id" not in db.rpc.call_args[0][1]

    def test_a_return_goes_back_into_the_batches_the_line_took(self):
        db = self._db([{"id": "li-1", "catalog_item_id": PARA, "variant_id": None, "name": "Para", "qty": 3, "batch_id": None}],
                      picks=[{"deal_item_id": "li-1", "batch_id": B_OLD, "quantity": 2},
                             {"deal_item_id": "li-1", "batch_id": B_NEW, "quantity": 1}])
        deals._deduct_for_deal(T, "deal-1", None, db, direction=1)
        calls = [c[0][1] for c in db.rpc.call_args_list]
        assert [(c.get("p_batch_id"), c["p_delta"]) for c in calls] == [(B_OLD, 2), (B_NEW, 1)]


class TestTabAndActions:
    def test_cards_and_rows(self, db):
        view = sb.overview(db, T)
        assert [b["batch_no"] for b in view["batches"]] == ["PC2201", "PC2307", "PC2401"]  # expired first
        assert view["cards"]["expired"] == {"batches": 1, "value_paise": 20000}
        assert view["cards"]["soon"]["batches"] == 1 and view["cards"]["fine"]["batches"] == 1
        assert view["cards"]["returnable"]["batches"] == 1  # soon + has a supplier
        assert view["batches"][1]["supplier"] == "Sri Ram Pharma"

    def test_a_switched_off_item_disappears(self, db):
        db.rows("catalog_items")[0]["tracks_batches"] = False
        assert sb.overview(db, T)["batches"] == []

    @pytest.mark.parametrize("pct, message", [(91, "0 to 90"), ("x", "whole number")])
    def test_discount_limits(self, db, pct, message):
        with pytest.raises(sb.BatchError, match=message):
            sb.set_discount(db, T, B_OLD, pct)

    def test_an_expired_batch_cant_be_discounted_or_sold_first(self, db):
        with pytest.raises(sb.BatchError, match="expired"):
            sb.set_discount(db, T, B_GONE, 10)
        with pytest.raises(sb.BatchError, match="expired"):
            sb.set_sell_first(db, T, B_GONE, True)

    def test_write_off_takes_that_batch_out(self, db, monkeypatch):
        seen = {}
        monkeypatch.setattr(deals, "adjust_stock", lambda *a, **k: seen.update(args=a, **k) or {"ok": True})
        assert sb.write_off(db, T, B_GONE) == 10
        assert seen["args"][2:4] == (-10, "write_off") and seen["batch_id"] == B_GONE

    def test_return_needs_a_supplier_and_gives_the_credit(self, db):
        db.rows("stock_batches")[1]["supplier_id"] = None
        with pytest.raises(sb.BatchError, match="no supplier"):
            sb.return_to_supplier(db, T, B_NEW)
        db.rpc_handlers["return_batch_to_supplier"] = lambda p: p["p_qty"] * 2000
        assert sb.return_to_supplier(db, T, B_OLD, 5) == {"quantity": 5, "credit_paise": 10000}
        with pytest.raises(sb.BatchError, match="has 20"):
            sb.return_to_supplier(db, T, B_OLD, 21)


class TestAlertsBillsAndAi:
    def test_bill_lines_print_their_batches(self, db):
        db.add("deal_item_batches", tenant_id=T, deal_item_id="li-1", batch_id=B_OLD, quantity=2)
        db.add("deal_item_batches", tenant_id=T, deal_item_id="li-1", batch_id=B_NEW, quantity=1)
        db.add("deal_item_batches", tenant_id=T, deal_item_id="li-1", batch_id=B_NEW, quantity=-1)  # returned
        out = sb.bill_line_batches(db, T, ["li-1"])
        assert out == {"li-1": f"Batch PC2307 · Exp {sb.label({'batch_no': 'x', 'expiry_date': d(8)}).split('Exp ')[1]}"}

    def test_one_bell_a_day_per_owner(self, db, monkeypatch):
        db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
        sent = []

        def notify(tenant_id, user_id, type_, title, message, **kw):
            sent.append(title)
            db.add("app_notifications", tenant_id=tenant_id, user_id=user_id, type=type_,
                   created_at=datetime.now(sb.IST).isoformat())

        monkeypatch.setattr("app.services.notify.notify_user", notify)
        assert sb.ring_expiry_bells(db) == 1 and sent == ["Batches: 1 expired · 1 expiring in 30 days"]
        assert sb.ring_expiry_bells(db) == 0

    def test_the_ai_sees_the_offer_price(self, db):
        db.rows("stock_batches")[0]["discount_pct"] = 20
        offers = sb.ai_offers(db, T, [PARA, PLAIN])
        assert offers == {PARA: 20}
        row = {"id": PARA, "name": "Paracetamol 650", "item_type": "product", "price_paise": 3000,
               "stock_quantity": 60, "offers": offers}
        text, *_ = ai_reply.catalog_prompt([row], "", {"can_recommend": True})
        assert "ON OFFER NOW: 20% off, ₹24" in text


def test_returns_lower_what_is_owed_to_the_supplier():
    db = FakeSupabase()
    db.add("suppliers", id=SUP, tenant_id=T, name="Sri Ram Pharma", archived=False)
    db.add("stock_ins", id="si-1", tenant_id=T, supplier_id=SUP, bill_date=date.today().isoformat(), total_paise=50000,
           due_date=None, pay_status="later")
    db.add("supplier_payments", tenant_id=T, supplier_id=SUP, amount_paise=20000)
    db.add("supplier_returns", tenant_id=T, supplier_id=SUP, amount_paise=10000)
    view = purchases.suppliers_view(db, T)
    assert view["suppliers"][0]["owe_paise"] == 20000


def test_a_chosen_batch_must_cover_the_line(db):
    with pytest.raises(deals.DealError, match="has only 20"):
        deals._resolve_lines(T, [{"catalog_item_id": PARA, "qty": 21, "batch_id": B_OLD}], db)


def test_the_discount_follows_the_place_a_bill_takes_first(db):
    gd = "bbbbbbbb-0000-0000-0000-000000000002"
    db.rows("stock_places")[0].update(bills_from=True, sort_order=0)
    db.add("stock_places", id=gd, tenant_id=T, name="Godown", archived=False, bills_from=False, sort_order=1)
    old = db.rows("stock_batches")[0]
    old.update(place_id=gd, discount_pct=20)  # the earliest expiry, on discount, but in the godown
    price, batch = sb.sale_price(db, T, PARA, None, 3000)
    assert batch["id"] == B_NEW and price == 3000  # the shop's batch is sold first, at full price
