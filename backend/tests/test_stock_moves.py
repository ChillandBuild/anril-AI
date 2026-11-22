"""Shop & godown (migration 309, services/stock_places.py): places, suggested moves, Move stock,
online orders packed from their own place, and what the AI says about godown-only stock.
The SQL functions themselves (send / receive once / cancel / sell across places) are stand-ins
here; their own behaviour is pinned in the migration's comments and was run by hand."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services import ai_reply, deals
from app.services import stock_places as sp
from tests.fake_supabase import FakeSupabase

T = "aaaaaaaa-0000-0000-0000-000000000001"
SHOP, GD = "bbbbbbbb-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"
ITEM, ITEM2 = "cccccccc-0000-0000-0000-000000000001", "cccccccc-0000-0000-0000-000000000002"


@pytest.fixture
def db():
    db = FakeSupabase()
    db.add("stock_places", id=SHOP, tenant_id=T, name="Shop", kind="shop", bills_from=True, online_from=False,
           ready_note=None, archived=False, sort_order=0)
    db.add("stock_places", id=GD, tenant_id=T, name="Gandhipuram godown", kind="godown", bills_from=False,
           online_from=True, ready_note="ready tomorrow", archived=False, sort_order=1)
    db.add("catalog_items", id=ITEM, tenant_id=T, name="Kanchi pattu", price_paise=1_050_000, stock_quantity=5,
           low_stock_at=None)
    db.add("catalog_items", id=ITEM2, tenant_id=T, name="Cotton saree", price_paise=95_000, stock_quantity=19,
           low_stock_at=None)
    db.add("stock_levels", tenant_id=T, catalog_item_id=ITEM, variant_id=None, place_id=SHOP, quantity=1)
    db.add("stock_levels", tenant_id=T, catalog_item_id=ITEM, variant_id=None, place_id=GD, quantity=4)
    db.add("stock_levels", tenant_id=T, catalog_item_id=ITEM2, variant_id=None, place_id=SHOP, quantity=19)
    db.add("stock_movements", tenant_id=T, catalog_item_id=ITEM, variant_id=None, delta=-3, reason="sale",
           created_at=datetime.now(timezone.utc).isoformat())
    return db


class TestSuggestions:
    def test_a_low_shop_gets_stock_from_the_place_that_has_it(self, db):
        view = sp.overview(db, T)
        kanchi = next(li for li in view["lines"] if li["item_id"] == ITEM)
        assert kanchi["by_place"] == {SHOP: 1, GD: 4} and kanchi["sold"] == 3
        # Low = 5 or fewer (no own level): enough to reach 6, but the godown only has 4
        assert kanchi["suggestion"] == {"from_place_id": GD, "to_place_id": SHOP, "quantity": 4}
        assert view["suggested"] == 1 and view["lines"][0]["item_id"] == ITEM  # suggestions first

    def test_the_items_own_low_level_and_a_weeks_sales_set_the_amount(self):
        assert sp.suggestion({"by_place": {SHOP: 2, GD: 50}, "sold": 0, "low_stock_at": 2}, SHOP, [SHOP, GD])["quantity"] == 1
        assert sp.suggestion({"by_place": {SHOP: 6, GD: 50}, "sold": 10, "low_stock_at": None}, SHOP, [SHOP, GD])["quantity"] == 4
        assert sp.suggestion({"by_place": {SHOP: 3, GD: 50}, "sold": 0, "low_stock_at": 2}, SHOP, [SHOP, GD]) is None

    def test_stock_already_on_the_way_to_the_shop_is_not_suggested_again(self, db):
        db.add("stock_moves", id="move-1", tenant_id=T, from_place_id=GD, to_place_id=SHOP, status="on_the_way")
        db.add("stock_move_lines", tenant_id=T, move_id="move-1", catalog_item_id=ITEM, variant_id=None, quantity=3)
        kanchi = next(li for li in sp.overview(db, T)["lines"] if li["item_id"] == ITEM)
        assert kanchi["suggestion"]["quantity"] == 2  # 1 + 3 coming, up to 6

    def test_no_suggestion_when_the_shop_has_enough_or_nobody_else_has_it(self):
        line = {"by_place": {SHOP: 19}, "sold": 4, "low_stock_at": None}
        assert sp.suggestion(line, SHOP, [SHOP, GD]) is None
        assert sp.suggestion({"by_place": {SHOP: 0}, "sold": 2, "low_stock_at": None}, SHOP, [SHOP, GD]) is None

    def test_never_more_than_the_other_place_has(self):
        line = {"by_place": {SHOP: 0, GD: 2}, "sold": 10, "low_stock_at": 3}
        assert sp.suggestion(line, SHOP, [SHOP, GD])["quantity"] == 2

    def test_place_cards_add_up_pieces_and_value(self, db):
        cards = {p["id"]: p for p in sp.overview(db, T)["places"]}
        assert cards[SHOP]["pieces"] == 20 and cards[SHOP]["value_paise"] == 1_050_000 + 19 * 95_000
        assert cards[GD]["pieces"] == 4


class TestPlaces:
    def _payload(self, db):
        return [dict(p) for p in sp.places(db, T)]

    @pytest.mark.parametrize("change, message", [
        (lambda ps: ps[1].update(bills_from=True), "counter bills"),
        (lambda ps: ps[1].update(online_from=False), "online orders"),
        (lambda ps: ps[1].update(name="shop"), "same name"),
        (lambda ps: ps[0].update(name="  "), "needs a name"),
    ])
    def test_settings_that_cant_work_are_refused_in_plain_words(self, db, change, message):
        ps = self._payload(db)
        change(ps)
        with pytest.raises(sp.StockPlaceError, match=message):
            sp.save_places(db, T, ps)

    def test_a_place_with_stock_cant_be_removed(self, db):
        ps = self._payload(db)
        ps[1].update(archived=True, online_from=False)
        ps[0]["online_from"] = True
        with pytest.raises(sp.StockPlaceError, match="still has stock"):
            sp.save_places(db, T, ps)

    def test_adding_a_branch_and_its_own_words(self, db):
        ps = self._payload(db) + [{"name": "Branch 2", "kind": "shop", "ready_note": "ready in 2 days"}]
        rows = sp.save_places(db, T, ps)
        assert [p["name"] for p in rows] == ["Shop", "Gandhipuram godown", "Branch 2"]
        assert rows[2]["ready_note"] == "ready in 2 days" and not rows[2]["bills_from"]


class TestMoves:
    def test_a_move_goes_to_the_database_function_with_merged_lines(self, db):
        seen = {}
        db.rpc_handlers["send_stock_move"] = lambda p: seen.update(p) or "move-1"
        out = sp.send_move(db, T, {"from_place_id": GD, "to_place_id": SHOP, "note": "  for Diwali  ", "lines": [
            {"item_id": ITEM, "quantity": 2}, {"item_id": ITEM, "quantity": 1}]}, user_id=None, user_name="Bala")
        assert out == {"id": "move-1"}
        assert seen["p_lines"] == [{"item": ITEM, "variant": None, "qty": 3}]
        assert seen["p_note"] == "for Diwali" and seen["p_user_name"] == "Bala"

    @pytest.mark.parametrize("payload, message", [
        ({"from_place_id": GD, "to_place_id": GD, "lines": [{"item_id": ITEM, "quantity": 1}]}, "two different"),
        ({"from_place_id": GD, "to_place_id": "x", "lines": [{"item_id": ITEM, "quantity": 1}]}, "both places"),
        ({"from_place_id": GD, "to_place_id": SHOP, "lines": []}, "at least one item"),
        ({"from_place_id": GD, "to_place_id": SHOP, "lines": [{"item_id": ITEM, "quantity": 0}]}, "at least 1"),
        ({"from_place_id": GD, "to_place_id": SHOP,
          "lines": [{"item_id": "dddddddd-0000-0000-0000-000000000009", "quantity": 1}]}, "isn't in your catalogue"),
    ])
    def test_bad_moves_are_refused(self, db, payload, message):
        with pytest.raises(sp.StockPlaceError, match=message):
            sp.send_move(db, T, payload, user_id=None, user_name=None)

    def test_not_enough_stock_names_the_item(self, db):
        def short(_p):
            raise Exception(f"P0001: stock_move_short:{ITEM}")
        db.rpc_handlers["send_stock_move"] = short
        with pytest.raises(sp.StockPlaceError, match="doesn't have that many of Kanchi pattu"):
            sp.send_move(db, T, {"from_place_id": SHOP, "to_place_id": GD,
                                 "lines": [{"item_id": ITEM, "quantity": 9}]}, user_id=None, user_name=None)

    def test_received_works_once(self, db):
        db.rpc_handlers["finish_stock_move"] = lambda p: False
        assert sp.finish_move(db, T, "eeeeeeee-0000-0000-0000-000000000001", received=True, user_id=None,
                              user_name="Meena") is False
        assert sp.finish_move(db, T, "not-an-id", received=True, user_id=None, user_name=None) is False


class TestWhereSalesTakeFrom:
    def _deal(self, channel):
        db = MagicMock()

        def table(name):
            q = MagicMock()
            data = {"deal_items": [{"catalog_item_id": ITEM, "variant_id": None, "name": "Kanchi", "qty": 1}],
                    "deals": [{"channel": channel}],
                    "stock_places": [{"id": SHOP, "bills_from": True, "online_from": False},
                                     {"id": GD, "bills_from": False, "online_from": True}]}[name]
            for m in ("select", "eq", "order", "limit"):
                getattr(q, m).return_value = q
            q.execute.return_value.data = data
            return q

        db.table.side_effect = table
        db.rpc.return_value.execute.return_value.data = [{"ok": True, "tracked": True, "quantity_after": 4}]
        deals._deduct_for_deal(T, "deal-1", None, db, direction=-1)
        return db.rpc.call_args[0][1]

    def test_online_orders_start_at_their_own_place(self):
        params = self._deal("online")
        assert params["p_first_place"] == GD and "p_place_id" not in params

    def test_counter_bills_start_at_the_bill_place(self):
        params = self._deal("store")
        assert "p_first_place" not in params and "p_place_id" not in params


class TestWhatTheAiSays:
    def test_godown_only_stock_is_offered_with_the_business_own_words(self, db):
        db.rows("stock_places")[0]["online_from"] = True
        db.rows("stock_places")[1]["online_from"] = False
        db.rows("stock_levels")[0]["quantity"] = 0
        notes = sp.elsewhere_notes(db, T, [ITEM, ITEM2])
        assert notes == {ITEM: {"place": "Gandhipuram godown", "ready": "ready tomorrow"}}
        row = {"id": ITEM, "name": "Kanchi pattu", "item_type": "product", "stock_quantity": 4, "elsewhere": notes}
        text, *_ = ai_reply.catalog_prompt([row], "", {"can_recommend": True})
        assert "in our Gandhipuram godown: say it IS available, ready tomorrow" in text

    def test_one_place_means_nothing_extra_and_nothing_written(self, db):
        db.tables["stock_places"] = []
        assert sp.elsewhere_notes(db, T, [ITEM]) == {}
        assert db.rows("stock_places") == []


class TestStaffTiedToAPlace:
    STAFF = "ffffffff-0000-0000-0000-000000000001"
    MOVE = "eeeeeeee-0000-0000-0000-000000000009"

    def _setup(self, db, place):
        db.add("tenant_users", tenant_id=T, user_id=self.STAFF, role="member", full_name="Bala", place_id=place)
        db.add("stock_moves", id=self.MOVE, tenant_id=T, from_place_id=SHOP, to_place_id=GD, status="on_the_way")
        db.rpc_handlers["finish_stock_move"] = lambda p: True

    def test_godown_staff_receive_moves_to_the_godown_only(self, db):
        self._setup(db, SHOP)
        with pytest.raises(sp.StockPlaceError, match="other place"):
            sp.finish_move(db, T, self.MOVE, received=True, user_id=self.STAFF, user_name="Bala")
        assert sp.finish_move(db, T, self.MOVE, received=False, user_id=self.STAFF, user_name="Bala")  # it left their shop
        assert sp.finish_move(db, T, self.MOVE, received=True, user_id=self.STAFF, user_name="Owner", role="owner")

    def test_staff_with_no_place_do_everything(self, db):
        self._setup(db, None)
        assert sp.finish_move(db, T, self.MOVE, received=True, user_id=self.STAFF, user_name="Bala")

    def test_setting_a_place_checks_both_belong_here(self, db):
        self._setup(db, None)
        sp.set_staff_place(db, T, self.STAFF, GD)
        assert sp.staff_place(db, T, self.STAFF) == GD
        with pytest.raises(sp.StockPlaceError, match="place again"):
            sp.set_staff_place(db, T, self.STAFF, "bbbbbbbb-0000-0000-0000-00000000dead")
        with pytest.raises(sp.StockPlaceError, match="teammate again"):
            sp.set_staff_place(db, T, "ffffffff-0000-0000-0000-00000000dead", GD)

    def test_a_counter_bill_made_by_godown_staff_starts_at_the_godown(self):
        db = MagicMock()

        def table(name):
            q = MagicMock()
            data = {"deal_items": [{"id": "li-1", "catalog_item_id": ITEM, "variant_id": None, "name": "K", "qty": 1}],
                    "deals": [{"channel": "store", "place_id": GD}]}.get(name, [])
            for m in ("select", "eq", "order", "limit", "in_"):
                getattr(q, m).return_value = q
            q.execute.return_value.data = data
            return q

        db.table.side_effect = table
        db.rpc.return_value.execute.return_value.data = [{"ok": True, "tracked": True, "quantity_after": 1}]
        deals._deduct_for_deal(T, "deal-1", None, db, direction=-1)
        assert db.rpc.call_args[0][1]["p_first_place"] == GD
