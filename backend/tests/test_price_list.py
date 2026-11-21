"""Upload price list (services/price_list.py): reading sheets, the New / Update / Same preview,
and saving through the stock functions."""
import asyncio
import io

import pytest

from app.services import price_list as pl
from tests.fake_supabase import FakeSupabase

T = "tenant-1"
SAREE = "10000000-0000-0000-0000-000000000001"
RED_M = "20000000-0000-0000-0000-000000000001"


@pytest.fixture
def db(monkeypatch):
    db = FakeSupabase()
    db.table("catalog_items").insert({"id": SAREE, "tenant_id": T, "name": "Kanchi pattu", "price_paise": 1050000,
                                      "gst_rate": 5, "hsn_code": "5007", "stock_quantity": 3}).execute()
    db.table("catalog_item_variants").insert({"id": RED_M, "tenant_id": T, "catalog_item_id": SAREE, "size": "M",
                                              "colour": "Red", "stock_quantity": 3, "price_paise": None}).execute()
    db.moves = []

    def item_move(params):
        db.moves.append(("item", params["p_item_id"], params["p_delta"], params["p_reason"]))
        return [{"ok": True, "tracked": True, "quantity_after": 0}]

    def variant_move(params):
        db.moves.append(("variant", params["p_variant_id"], params["p_delta"], params["p_reason"]))
        return [{"ok": True, "quantity_after": 0, "item_quantity_after": 0}]

    db.rpc_handlers.update({"apply_stock_movement": item_move, "apply_variant_stock_movement": variant_move})
    import app.services.catalog_retrieval as cr

    async def no_embed(*a, **k):
        return None
    monkeypatch.setattr(cr, "embed_and_store_catalog_item", no_embed)
    return db


def test_a_csv_with_its_own_headings_is_read():
    rows = pl.read_sheet("Product,Color,Size,MRP,GST %,Qty\nKanchi pattu,Red,M,\"11,000\",5,6\n".encode(), "list.csv")
    assert rows[0]["name"] == "Kanchi pattu" and rows[0]["colour"] == "Red" and rows[0]["price"] == "11,000"
    assert rows[0]["stock"] == "6"


def test_an_excel_file_is_read():
    from openpyxl import Workbook

    book = Workbook()
    for r in pl.SAMPLE:
        book.active.append(r)
    buf = io.BytesIO()
    book.save(buf)
    rows = pl.read_sheet(buf.getvalue(), "list.xlsx")
    assert len(rows) == 3 and rows[2]["name"] == "Blouse stitching"


def test_a_sheet_without_a_name_column_says_what_to_do():
    with pytest.raises(pl.PriceListError, match="Item name"):
        pl.read_sheet(b"foo,bar\n1,2\n", "x.csv")


def test_the_preview_marks_new_update_same_and_problems(db):
    out = pl.preview(db, T, [
        {"name": "kanchi PATTU", "size": "M", "colour": "red", "price": "11000", "stock": "3"},   # price changes
        {"name": "Kanchi pattu", "size": "L", "colour": "Red", "price": "10500", "stock": "2"},   # new size
        {"name": "Soft silk", "price": "2450", "gst_rate": "5", "stock": "11"},                   # new item
        {"name": "Kanchi pattu", "size": "M", "colour": "Red", "price": "11000"},                 # twice
        {"name": "Cotton", "price": "abc", "gst_rate": "7"},
        {"name": "", "price": ""},                                                                # blank line
    ])
    statuses = [r["status"] for r in out["rows"]]
    assert statuses == ["update", "new_size", "new", "problem", "problem"]
    assert out["rows"][0]["changes"] == ["price"] and out["rows"][0]["current"]["price_paise"] == 1050000
    assert out["rows"][4]["problems"] == ["Price isn't a number", "GST is 0, 0.25, 3, 5, 12, 18, 28 or 40"]


def test_saving_creates_items_and_sizes_and_moves_stock_through_the_ledger(db):
    out = asyncio.run(pl.apply(db, T, [
        {"name": "Kanchi pattu", "size": "M", "colour": "Red", "price": "11000", "stock": "5"},
        {"name": "Kanchi pattu", "size": "L", "colour": "Red", "price": "10500", "stock": "2"},
        {"name": "Soft silk", "size": "Free", "colour": "Green", "price": "2450", "stock": "4"},
        {"name": "Soft silk", "size": "Free", "colour": "Blue", "price": "2600", "stock": "1"},
        {"name": "Bad", "price": "x"},
    ], None))
    assert out == {"new_items": 1, "new_sizes": 1, "updated": 1, "skipped": 1}
    silk = [i for i in db.rows("catalog_items") if i["name"] == "Soft silk"][0]
    silk_sizes = [v for v in db.rows("catalog_item_variants") if v["catalog_item_id"] == silk["id"]]
    assert silk["price_paise"] == 245000 and [v["price_paise"] for v in silk_sizes] == [None, 260000]
    red_m = [v for v in db.rows("catalog_item_variants") if v["id"] == RED_M][0]
    assert red_m["price_paise"] == 1100000
    assert ("variant", RED_M, 2, "adjustment") in db.moves  # 3 -> 5
    assert sum(1 for m in db.moves if m[3] == "restock") == 3  # Red L 2, silk 4 and 1
