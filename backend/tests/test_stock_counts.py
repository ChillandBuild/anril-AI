"""Stock count (migration 312, services/stock_counts.py): start, count by scan or typing, the difference
against what the system said at that moment, reasons, owner Finish applying each difference once."""
import pytest

from app.services import deals
from app.services import stock_counts as sc
from tests.fake_supabase import FakeSupabase

T = "aaaaaaaa-0000-0000-0000-000000000001"
SHOP = "bbbbbbbb-0000-0000-0000-000000000001"
KP, SILK = "cccccccc-0000-0000-0000-000000000001", "cccccccc-0000-0000-0000-000000000002"
RM = "dddddddd-0000-0000-0000-000000000001"


@pytest.fixture
def db():
    db = FakeSupabase()
    db.add("stock_places", id=SHOP, tenant_id=T, name="Shop", archived=False, bills_from=True, sort_order=0)
    db.add("catalog_items", id=KP, tenant_id=T, name="Kanchi pattu", price_paise=1050000, cost_price_paise=620000, stock_quantity=4)
    db.add("catalog_items", id=SILK, tenant_id=T, name="Soft silk", price_paise=245000, cost_price_paise=145000, stock_quantity=2)
    db.add("catalog_item_variants", id=RM, tenant_id=T, catalog_item_id=KP, size="M", colour="Red", stock_quantity=4)
    db.add("stock_levels", tenant_id=T, catalog_item_id=KP, variant_id=RM, place_id=SHOP, quantity=4)
    db.add("stock_levels", tenant_id=T, catalog_item_id=SILK, variant_id=None, place_id=SHOP, quantity=2)
    db.rpc_handlers["claim_stock_count"] = lambda p: _claim(db, p)
    return db


def _claim(db, p):
    row = next(c for c in db.rows("stock_counts") if c["id"] == p["p_count"])
    if row["status"] not in ("open", "paused"):
        return False
    row.update(status="finished", finished_at="2026-11-22T10:00:00+00:00")  # as claim_stock_count does
    return True


def _start(db):
    return sc.start(db, T, SHOP, ["Saree rack 1", " Saree rack 1 ", "Back room"], user_id=None, user_name="Meena")


def test_a_count_starts_with_clean_sections(db):
    count = _start(db)
    assert count["sections"] == ["Saree rack 1", "Back room"] and count["status"] == "open"


def test_scans_add_up_and_typing_sets_the_number(db):
    count = _start(db)
    for _ in range(3):
        line = sc.record(db, T, count["id"], {"item_id": KP, "variant_id": RM, "section": "Saree rack 1", "add": 1},
                         user_id=None, user_name="Meena")
    assert line["counted_qty"] == 3 and line["system_qty"] == 4 and line["section"] == "Saree rack 1"
    line = sc.record(db, T, count["id"], {"item_id": SILK, "qty": 2}, user_id=None, user_name="Karthik")
    assert line["counted_qty"] == 2


def test_an_item_with_sizes_is_counted_per_size(db):
    count = _start(db)
    with pytest.raises(sc.CountError, match="count each one"):
        sc.record(db, T, count["id"], {"item_id": KP, "qty": 3}, user_id=None, user_name=None)


def test_a_paused_count_takes_no_numbers(db):
    count = _start(db)
    sc.set_status(db, T, count["id"], "paused")
    with pytest.raises(sc.CountError, match="paused"):
        sc.record(db, T, count["id"], {"item_id": SILK, "qty": 2}, user_id=None, user_name=None)


def test_the_view_shows_differences_and_what_is_not_counted(db):
    count = _start(db)
    sc.record(db, T, count["id"], {"item_id": KP, "variant_id": RM, "qty": 3}, user_id=None, user_name="Meena")
    view = sc.view(db, T)["count"]
    assert view["cards"]["less"] == {"items": 1, "pieces": 1, "value_paise": 620000}
    assert view["cards"]["not_counted"] == 1 and view["not_counted"][0]["name"] == "Soft silk"
    assert view["missing_reasons"] == 1 and view["lines"][0]["variant_label"] == "Red · M"


def test_finish_needs_every_reason_then_applies_each_difference_once(db, monkeypatch):
    count = _start(db)
    line = sc.record(db, T, count["id"], {"item_id": KP, "variant_id": RM, "qty": 3}, user_id=None, user_name="Meena")
    sc.record(db, T, count["id"], {"item_id": SILK, "qty": 2}, user_id=None, user_name="Meena")  # matches
    with pytest.raises(sc.CountError, match="reason"):
        sc.finish(db, T, count["id"], user_id=None, user_name="Owner")
    sc.set_reason(db, T, line["id"], "damaged")
    calls = []
    monkeypatch.setattr(deals, "adjust_variant_stock", lambda *a, **k: calls.append((a, k)) or {"ok": True})
    out = sc.finish(db, T, count["id"], user_id=None, user_name="Owner")
    assert out == {"changed": 1, "loss_paise": 620000, "gain_paise": 0, "not_applied": 0}
    (args, kw), = calls
    assert args[1:4] == (RM, -1, "count") and kw["place_id"] == SHOP and kw["note"] == "Stock count: Damaged"
    with pytest.raises(sc.CountError, match="already finished"):
        sc.finish(db, T, count["id"], user_id=None, user_name="Owner")
    assert sc.stock_loss(db, T, "2000-01-01") == 620000


def test_bills_during_the_count_dont_count_twice(db, monkeypatch):
    count = _start(db)
    line = sc.record(db, T, count["id"], {"item_id": SILK, "qty": 1}, user_id=None, user_name="Meena")  # system said 2
    sc.set_reason(db, T, line["id"], "lost")
    db.rows("stock_levels")[1]["quantity"] = 0  # then two were sold on a bill
    calls = []
    monkeypatch.setattr(deals, "adjust_stock", lambda *a, **k: calls.append(a) or {"ok": True})
    assert sc.finish(db, T, count["id"], user_id=None, user_name="Owner")["changed"] == 0
    assert calls == []  # never below zero


def test_one_open_count_per_place(db, monkeypatch):
    _start(db)
    monkeypatch.setattr(db, "table", lambda name, _t=db.table: _Refuse() if name == "stock_counts" else _t(name))
    with pytest.raises(sc.CountError, match="already going on"):
        _start(db)


class _Refuse:
    def insert(self, *_a, **_k):
        return self

    def execute(self):
        raise Exception('23505 duplicate key value violates unique constraint "stock_counts_one_open_uq"')
