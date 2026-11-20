"""The Catalogue's copy on the shop's Meta catalogue (services/meta_catalog.py) and the new item
page routes (routes/catalog.py: item detail, correct stock, Meta switch, public item page)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import meta_catalog
from tests.fake_supabase import FakeSupabase

T = "00000000-0000-0000-0000-0000000000aa"
ITEM = "11111111-1111-1111-1111-111111111111"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def db():
    fake = FakeSupabase()
    fake.storage = MagicMock()
    fake.storage.from_.return_value.get_public_url.side_effect = lambda path: f"https://cdn.test/{path}"
    return fake


def _settings(sync="on", catalog="cat-1"):
    values = {"meta_catalog_id": catalog, "meta_catalog_access_token": "tok", meta_catalog.SYNC_KEY: sync,
              "meta_catalog_name": "Demo Silks catalogue"}
    return patch("app.services.meta_catalog.get_setting",
                 side_effect=lambda key, fallback=None, tenant_id=None: values.get(key, fallback))


def _item(db, **extra):
    row = {"id": ITEM, "tenant_id": T, "name": "Kanchi pattu", "description": "Pure silk", "status": "ready",
           "item_type": "product", "price_paise": 890000, "stock_quantity": 3, "meta_change_seq": 2,
           "meta_synced_seq": 0, "meta_pending": True, "meta_retailer_ids": [], "meta_sync_state": None, **extra}
    db.rows("catalog_items").append(row)
    return row


def _photo(db, path="kp.jpg"):
    db.add("catalog_media", tenant_id=T, catalog_item_id=ITEM, storage_path=path, sort_order=0)


def _variant(db, vid, size, colour, stock, price=None):
    db.add("catalog_item_variants", id=vid, tenant_id=T, catalog_item_id=ITEM, size=size, colour=colour,
           stock_quantity=stock, price_paise=price, sort_order=0)


# ── what Meta gets ──────────────────────────────────────────────────────────────

def test_each_size_and_colour_is_its_own_meta_product_grouped_under_the_item():
    item = {"id": ITEM, "name": "Kanchi pattu", "description": "", "status": "ready", "item_type": "product",
            "price_paise": 890000}
    variants = [{"id": "v1", "size": "M", "colour": "Red", "stock_quantity": 0, "price_paise": None},
                {"id": "v2", "size": "L", "colour": "Red", "stock_quantity": 2, "price_paise": 950000}]
    products, problem = meta_catalog.meta_products(item, variants, ["https://cdn/a.jpg", "https://cdn/b.jpg"], "Demo Silks")
    assert problem is None
    red_m, red_l = products
    assert (red_m["id"], red_m["item_group_id"], red_m["size"], red_m["color"]) == ("v1", ITEM, "M", "Red")
    assert (red_m["availability"], red_m["price"]) == ("out of stock", "8900.00 INR")
    assert (red_l["availability"], red_l["price"], red_l["quantity_to_sell_on_facebook"]) == ("in stock", "9500.00 INR", 2)
    assert red_m["description"] == "Kanchi pattu"  # Meta needs one: the name stands in
    assert red_m["additional_image_link"] == ["https://cdn/b.jpg"]
    assert red_m["link"].endswith(f"/item/{ITEM}") and red_m["brand"] == "Demo Silks"


def test_no_photo_or_no_price_says_what_to_add_and_drafts_are_not_for_meta():
    item = {"id": ITEM, "name": "Gown", "status": "ready", "item_type": "product", "price_paise": None}
    assert meta_catalog.meta_products(item, [], [], "S") == ([], "Add a photo: Meta needs one for every product")
    assert meta_catalog.meta_products(item, [], ["u"], "S")[1].startswith("Add a price")
    assert meta_catalog.meta_products({**item, "status": "draft"}, [], ["u"], "S") == (None, None)
    assert meta_catalog.meta_products({**item, "item_type": "service"}, [], ["u"], "S") == (None, None)
    untracked = meta_catalog.meta_products({**item, "price_paise": 100, "stock_quantity": None}, [], ["u"], "S")[0][0]
    assert untracked["availability"] == "in stock" and "quantity_to_sell_on_facebook" not in untracked


# ── pushing ─────────────────────────────────────────────────────────────────────

def test_nothing_goes_to_meta_until_the_owner_switches_it_on(db):
    _item(db)
    _photo(db)
    post = AsyncMock(return_value=("h1", None))
    with _settings(sync="off"), patch.object(meta_catalog, "_post_batch", post):
        out = run(meta_catalog.push_tenant(db, T))
    assert out == {"connected": False, "sent": 0}
    post.assert_not_awaited()


def test_a_changed_item_goes_and_a_removed_size_is_deleted_from_meta(db):
    _item(db, meta_retailer_ids=["v-old", "v1"])
    _photo(db)
    _variant(db, "v1", "M", "Red", 1)
    post = AsyncMock(return_value=("h1", None))
    with _settings(), patch.object(meta_catalog, "_post_batch", post), \
         patch.object(meta_catalog, "_brand", return_value="Demo Silks"):
        out = run(meta_catalog.push_tenant(db, T))
    assert out["sent"] == 1
    catalog_id, token, requests = post.await_args.args
    assert (catalog_id, token) == ("cat-1", "tok")
    assert requests[0] == {"method": "DELETE", "data": {"id": "v-old"}}
    assert requests[1]["method"] == "UPDATE" and requests[1]["data"]["id"] == "v1"
    row = db.rows("catalog_items")[0]
    assert (row["meta_sync_state"], row["meta_batch_handle"], row["meta_retailer_ids"]) == ("sending", "h1", ["v1"])
    assert row["meta_synced_seq"] == 2  # the change number it pushed: a later change goes again


def test_an_item_without_a_photo_waits_with_the_reason_and_is_taken_off_meta(db):
    _item(db, meta_retailer_ids=[ITEM])
    post = AsyncMock(return_value=("h2", None))
    with _settings(), patch.object(meta_catalog, "_post_batch", post), patch.object(meta_catalog, "_brand", return_value=""):
        run(meta_catalog.push_tenant(db, T))
    assert post.await_args.args[2] == [{"method": "DELETE", "data": {"id": ITEM}}]
    row = db.rows("catalog_items")[0]
    assert row["meta_sync_state"] == "skipped" and row["meta_sync_error"].startswith("Add a photo")


def test_when_meta_refuses_the_batch_every_item_shows_the_problem(db):
    _item(db)
    _photo(db)
    post = AsyncMock(return_value=(None, "Invalid OAuth access token"))
    with _settings(), patch.object(meta_catalog, "_post_batch", post), patch.object(meta_catalog, "_brand", return_value=""):
        out = run(meta_catalog.push_tenant(db, T))
    assert out["error"] == "Invalid OAuth access token"
    row = db.rows("catalog_items")[0]
    assert (row["meta_sync_state"], row["meta_sync_error"]) == ("error", "Meta: Invalid OAuth access token")


def test_meta_answer_marks_synced_or_the_rejected_item(db):
    _item(db, meta_sync_state="sending", meta_batch_handle="h1", meta_retailer_ids=["v1"])
    db.rows("catalog_items").append({"id": "other", "tenant_id": T, "meta_sync_state": "sending",
                                     "meta_batch_handle": "h1", "meta_retailer_ids": ["v9"]})
    answer = MagicMock(status_code=200)
    answer.json.return_value = {"data": [{"status": "finished", "errors": [{"id": "v9", "message": "Invalid image"}]}]}
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=answer)
    with _settings(), patch("app.services.meta_catalog.httpx.AsyncClient", return_value=client):
        assert run(meta_catalog.check_sent(db, T)) == 2
    ok, bad = db.rows("catalog_items")
    assert ok["meta_sync_state"] == "synced" and ok["meta_synced_at"]
    assert (bad["meta_sync_state"], bad["meta_sync_error"]) == ("error", "Meta: Invalid image")


def test_status_counts_items_by_where_they_are(db):
    _item(db, meta_pending=False, meta_sync_state="synced", meta_synced_at="2026-11-20T10:00:00")
    db.rows("catalog_items").append({"id": "b", "tenant_id": T, "item_type": "product", "meta_pending": False,
                                     "meta_sync_state": "error"})
    db.rows("catalog_items").append({"id": "c", "tenant_id": T, "item_type": "product", "meta_pending": True})
    with _settings(sync="off"):
        out = meta_catalog.status(db, T)
    assert (out["connected"], out["sync_on"], out["catalog_name"]) == (True, False, "Demo Silks catalogue")
    assert out["counts"] == {"synced": 1, "sending": 0, "error": 1, "skipped": 0, "waiting": 1}


# ── routes ──────────────────────────────────────────────────────────────────────

def _routes(db):
    return patch("app.routes.catalog.get_supabase", return_value=db)


def test_correcting_one_size_needs_a_reason_and_saves_it(db):
    from app.routes import catalog as route
    _item(db)
    _variant(db, "v1", "S", "Blue", 0)
    moves = []

    def fake_adjust(tenant_id, variant_id, delta, reason, note=None, created_by=None, db=None):
        moves.append((variant_id, delta, reason, note))
        return {"ok": True}

    with _routes(db), patch("app.services.deals.adjust_variant_stock", side_effect=fake_adjust), \
         patch("app.services.deals.held_quantities", return_value={}):
        with pytest.raises(HTTPException) as no_reason:
            run(route.correct_stock(ITEM, {"variant_id": "v1", "to": 2}, tenant_id=T, ctx={}))
        assert no_reason.value.status_code == 400
        run(route.correct_stock(ITEM, {"variant_id": "v1", "to": 2, "why": "found"}, tenant_id=T, ctx={"user_id": "u1"}))
    assert moves == [("v1", 2, "adjustment", "Found in shop")]


def test_hsn_and_cost_price_are_checked():
    from app.routes.catalog import _clean_stock_fields
    assert _clean_stock_fields({"hsn_code": " 5007 ", "cost_price_paise": "620000", "low_stock_at": 3}) == \
        {"hsn_code": "5007", "cost_price_paise": 620000, "low_stock_at": 3}
    assert _clean_stock_fields({"hsn_code": ""}) == {"hsn_code": None}
    for bad in ({"hsn_code": "50A7"}, {"cost_price_paise": -1}, {"low_stock_at": "x"}):
        with pytest.raises(HTTPException):
            _clean_stock_fields(bad)


def test_the_public_page_shows_only_ready_items_and_what_is_in_stock(db):
    from app.routes import catalog as route
    _item(db, status="draft")
    with _routes(db), pytest.raises(HTTPException) as hidden:
        run(route.public_item(ITEM))
    assert hidden.value.status_code == 404
    db.rows("catalog_items")[0]["status"] = "ready"
    _photo(db)
    _variant(db, "v1", "M", "Red", 0)
    _variant(db, "v2", "L", "Red", 2, price=950000)
    with _routes(db), patch("app.routes.inbound_leads._primary_whatsapp_number", return_value="+91 98765 43210"), \
         patch("app.services.business_details.get_business_details", return_value={"legal_name": "Demo Silks", "city": "Erode"}):
        out = run(route.public_item(ITEM))
    assert out["whatsapp"] == "919876543210" and out["shop"] == {"name": "Demo Silks", "city": "Erode"}
    assert [(o["size"], o["in_stock"], o["price_paise"]) for o in out["options"]] == [("M", False, 890000), ("L", True, 950000)]
    assert out["photos"] == ["https://cdn.test/kp.jpg"]


def test_switching_the_catalogue_on_sends_everything_once(db):
    from app.routes import catalog as route
    _item(db, meta_synced_seq=2, meta_pending=False)
    upserts = []
    push = AsyncMock(return_value={"sent": 1})
    with _routes(db), _settings(sync="off"), \
         patch.object(meta_catalog, "set_sync", side_effect=lambda d, t, on: upserts.append(on)), \
         patch.object(meta_catalog, "push_tenant", push):
        run(route.meta_catalogue_action({"action": "on"}, tenant_id=T, _ctx={}))
    assert upserts == [True]
    push.assert_awaited_once()
