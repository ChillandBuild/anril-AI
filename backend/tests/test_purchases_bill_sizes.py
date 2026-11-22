"""The supplier bill photo: a size/colour is matched only when it fits everything the bill says (never
"same colour, another size"), and a new one is added under the same item on Save."""
from app.services import purchases
from tests.fake_supabase import FakeSupabase

T = "aaaaaaaa-0000-0000-0000-000000000001"
KP = "cccccccc-0000-0000-0000-000000000001"
RM, RL = "dddddddd-0000-0000-0000-000000000001", "dddddddd-0000-0000-0000-000000000002"


def _db():
    db = FakeSupabase()
    db.add("catalog_items", id=KP, tenant_id=T, name="Kanchi pattu", gst_rate=5, stock_quantity=8, cost_price_paise=620000,
           tracks_batches=False)
    db.add("catalog_item_variants", id=RM, tenant_id=T, catalog_item_id=KP, size="M", colour="Red", price_paise=1050000, sort_order=0)
    db.add("catalog_item_variants", id=RL, tenant_id=T, catalog_item_id=KP, size="L", colour="Red", price_paise=1050000, sort_order=1)
    return db


def test_an_exact_size_matches_and_a_new_one_is_flagged_not_misplaced():
    db = _db()
    out = purchases.match_lines(db, T, [
        {"name": "Kanchi pattu", "size": "L", "colour": "red", "qty": 2, "unit_cost": 6200},
        {"name": "Kanchi pattu", "size": "XL", "colour": "Red", "qty": 4, "unit_cost": 6200},
        {"name": "Kanchi pattu", "colour": "Red", "qty": 1, "unit_cost": 6200},  # which size? staff picks
    ])
    assert out[0]["variant_id"] == RL and out[0]["new_variant"] is None
    assert out[1]["variant_id"] is None and out[1]["new_variant"] == {"size": "XL", "colour": "Red"}
    assert out[1]["label"] == "Kanchi pattu · Red · XL (new)"
    assert out[2]["variant_id"] is None and out[2]["new_variant"] is None


def test_the_new_size_is_made_once_under_the_item_with_the_colours_price():
    db = _db()
    item, variant, label = purchases._resolve_line(db, T, {"catalog_item_id": KP, "new_size": "XL", "new_colour": "Red"})
    assert label == "Kanchi pattu · Red · XL" and variant["price_paise"] == 1050000 and variant["sort_order"] == 2
    _, again, _ = purchases._resolve_line(db, T, {"catalog_item_id": KP, "new_size": "xl", "new_colour": "red"})
    assert again["id"] == variant["id"] and len(db.rows("catalog_item_variants")) == 3


def test_still_to_come_gets_one_reminder_on_the_expected_date(monkeypatch):
    import asyncio
    from datetime import datetime, timezone

    db = _db()
    po_id = "eeeeeeee-0000-0000-0000-000000000001"
    sup = "ffffffff-0000-0000-0000-000000000001"
    db.add("suppliers", id=sup, tenant_id=T, name="Lakshmi Handlooms", phone="919800000000")
    db.add("purchase_orders", id=po_id, tenant_id=T, number=41, supplier_id=sup, status="part_received",
           need_by="2026-11-17", short_reminded_at=None)
    db.add("purchase_order_lines", tenant_id=T, purchase_order_id=po_id, catalog_item_id=KP, variant_id=RM,
           label="Kanchi pattu · Red · M", qty_ordered=8, qty_received=3, unit_cost_paise=1, gst_rate=5)
    db.add("tenant_users", tenant_id=T, user_id="owner-1", role="owner")
    bells = []
    monkeypatch.setattr("app.services.notify.notify_user", lambda *a, **k: bells.append(a[3]))
    monkeypatch.setattr("app.services.brain_digest.owner_user_ids", lambda db, t: ["owner-1"])
    monkeypatch.setattr("app.config_dynamic.get_setting", lambda *a, **k: None)  # WhatsApp not connected
    monkeypatch.setattr("app.services.orders._shop_name", lambda db, t: "Demo Silks")
    now = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)
    assert asyncio.run(purchases.remind_short(db, now)) == 1
    assert bells == ["PO-0041: 5 still to come"]
    assert asyncio.run(purchases.remind_short(db, now)) == 0  # once
