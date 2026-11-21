"""Purchases & suppliers (migration 307, services/purchases.py)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import purchases as p
from tests.fake_supabase import FakeSupabase

T = "tenant-1"
SAREE, KURTI = "10000000-0000-0000-0000-000000000001", "10000000-0000-0000-0000-000000000002"
KURTI_M, KURTI_L = "20000000-0000-0000-0000-000000000001", "20000000-0000-0000-0000-000000000002"
SHOP = "30000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 11, 21, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    db = FakeSupabase()
    db.table("stock_places").insert({"id": SHOP, "tenant_id": T, "name": "Shop", "archived": False}).execute()
    db.table("catalog_items").insert({"id": SAREE, "tenant_id": T, "name": "Cotton saree · Blue", "stock_quantity": 0,
                                      "low_stock_at": 3, "gst_rate": 5, "cost_price_paise": 45000}).execute()
    db.table("catalog_items").insert({"id": KURTI, "tenant_id": T, "name": "Cotton kurti", "stock_quantity": 1,
                                      "low_stock_at": 2, "gst_rate": 5}).execute()
    for vid, size, stock in ((KURTI_M, "M", 0), (KURTI_L, "L", 1)):
        db.table("catalog_item_variants").insert({"id": vid, "tenant_id": T, "catalog_item_id": KURTI, "size": size,
                                                  "stock_quantity": stock}).execute()
    moves = []
    db.moves = moves

    def item_move(params):
        moves.append(("item", params["p_item_id"], params["p_delta"], params.get("p_place_id")))
        return [{"ok": True, "tracked": True, "quantity_after": 0}]

    def variant_move(params):
        moves.append(("variant", params["p_variant_id"], params["p_delta"], params.get("p_place_id")))
        return [{"ok": True, "quantity_after": 0, "item_quantity_after": 0}]

    counter = {"n": 41}

    def next_po(params):
        counter["n"] += 1
        return counter["n"]

    def received(params):
        row = [r for r in db.rows("purchase_order_lines") if r["id"] == params["p_line_id"]][0]
        db.table("purchase_order_lines").update({"qty_received": int(row["qty_received"]) + params["p_qty"]})             .eq("id", params["p_line_id"]).execute()
        return int(row["qty_received"]) + params["p_qty"]

    db.rpc_handlers["add_po_line_received"] = received
    db.rpc_handlers.update({"apply_stock_movement": item_move, "apply_variant_stock_movement": variant_move,
                            "default_stock_place": lambda params: SHOP, "next_po_number": next_po})
    return db


def _supplier(db, name="Lakshmi Handlooms", phone="9876543120"):
    return p.save_supplier(db, T, {"name": name, "phone": phone, "gstin": "33abcde1234f1z5"})


class TestSuppliers:
    def test_phone_and_gstin_are_cleaned_and_a_bad_gstin_is_refused(self, db):
        s = _supplier(db)
        assert s["phone"] == "919876543120" and s["gstin"] == "33ABCDE1234F1Z5"
        with pytest.raises(p.PurchaseError):
            p.save_supplier(db, T, {"name": "X", "gstin": "12345"})

    def test_what_you_owe_is_bills_minus_payments_and_shows_when_overdue(self, db):
        s = _supplier(db)
        p.stock_in(db, T, {"supplier_id": s["id"], "bill_date": "2026-11-10", "pay_status": "later", "due_date": "2026-11-15",
                           "lines": [{"catalog_item_id": SAREE, "qty_good": 10, "unit_cost_paise": 48000, "gst_rate": 5}]}, None)
        p.record_payment(db, T, s["id"], {"amount_paise": 100000, "method": "cash"}, None)
        view = p.suppliers_view(db, T, NOW)["suppliers"][0]
        assert view["owe_paise"] == 504000 - 100000 and view["due_date"] == "2026-11-15" and view["overdue_days"] == 6


class TestStockIn:
    def test_good_pieces_go_in_damaged_are_kept_aside_and_cost_updates(self, db):
        s = _supplier(db)
        out = p.stock_in(db, T, {"supplier_id": s["id"], "bill_no": "LH/2231", "pay_status": "later", "lines": [
            {"catalog_item_id": SAREE, "qty_good": 19, "qty_damaged": 1, "damaged_action": "replace",
             "unit_cost_paise": 48000, "gst_rate": 5},
            {"catalog_item_id": KURTI, "variant_id": KURTI_M, "qty_good": 4, "unit_cost_paise": 38000, "gst_rate": 5},
        ]}, "user-1")
        assert db.moves == [("item", SAREE, 19, SHOP), ("variant", KURTI_M, 4, SHOP)]
        assert out["items_paise"] == 19 * 48000 + 4 * 38000 and out["gst_paise"] == 45600 + 7600
        assert out["pieces_in"] == 23 and out["damaged_aside"] == 1
        assert db.rows("catalog_items")[0]["cost_price_paise"] == 48000
        assert [v for v in db.rows("catalog_item_variants") if v["id"] == KURTI_M][0]["cost_price_paise"] == 38000

    def test_damaged_kept_to_sell_at_a_discount_are_paid_for_and_go_in(self, db):
        out = p.stock_in(db, T, {"lines": [{"catalog_item_id": SAREE, "qty_good": 2, "qty_damaged": 1,
                                            "damaged_action": "discount", "unit_cost_paise": 100, "gst_rate": 0}]}, None)
        assert out["items_paise"] == 300 and db.moves == [("item", SAREE, 3, SHOP)]

    def test_damaged_pieces_need_a_decision_and_sizes_must_be_picked(self, db):
        with pytest.raises(p.PurchaseError, match="damaged"):
            p.stock_in(db, T, {"lines": [{"catalog_item_id": SAREE, "qty_damaged": 1, "unit_cost_paise": 1}]}, None)
        with pytest.raises(p.PurchaseError, match="pick one"):
            p.stock_in(db, T, {"lines": [{"catalog_item_id": KURTI, "qty_good": 1, "unit_cost_paise": 1}]}, None)

    def test_part_paid_records_the_payment(self, db):
        s = _supplier(db)
        p.stock_in(db, T, {"supplier_id": s["id"], "pay_status": "part", "paid_paise": 1000, "pay_method": "upi",
                           "lines": [{"catalog_item_id": SAREE, "qty_good": 1, "unit_cost_paise": 5000}]}, None)
        assert db.rows("supplier_payments")[0]["amount_paise"] == 1000

    def test_people_waiting_for_what_came_are_counted(self, db):
        db.table("stock_waitlist").insert({"tenant_id": T, "catalog_item_id": KURTI, "variant_id": KURTI_M,
                                           "wants_message": True}).execute()
        out = p.stock_in(db, T, {"lines": [{"catalog_item_id": KURTI, "variant_id": KURTI_M, "qty_good": 2,
                                            "unit_cost_paise": 1}]}, None)
        assert out["waiting"] == [{"catalog_item_id": KURTI, "variant_id": KURTI_M, "people": 1}]


class TestPurchaseOrders:
    def _po(self, db):
        s = _supplier(db)
        return p.save_po(db, T, {"supplier_id": s["id"], "need_by": "2026-11-17", "lines": [
            {"catalog_item_id": SAREE, "qty": 20, "unit_cost_paise": 48000, "gst_rate": 5},
            {"catalog_item_id": KURTI, "variant_id": KURTI_M, "qty": 8, "unit_cost_paise": 38000, "gst_rate": 5},
        ]}, None)

    def test_numbered_and_totalled(self, db):
        po = self._po(db)
        assert po["po_number"] == "PO-0042" and po["total_paise"] == 20 * 48000 + 8 * 38000 + 48000 + 15200
        assert "Cotton kurti · M × 8" in po["message"]["text"] and po["message"]["values"][4] == "17 Nov"

    def test_goods_came_counts_what_arrived_and_tracks_the_short(self, db):
        po = self._po(db)
        line = {li["catalog_item_id"]: li for li in po["lines"]}[SAREE]
        p.stock_in(db, T, {"purchase_order_id": po["id"], "lines": [
            {"catalog_item_id": SAREE, "purchase_order_line_id": line["id"], "qty_good": 19, "qty_damaged": 1,
             "damaged_action": "less_on_bill", "unit_cost_paise": 48000, "gst_rate": 5}]}, None)
        view = p.pos_view(db, T, NOW)
        row = view["orders"][0]
        assert row["status"] == "part_received" and (row["ordered"], row["received"]) == (28, 19)
        assert row["late_days"] == 4 and view["late"]["count"] == 1
        assert view["short_or_damaged"]["claim_paise"] == 48000

    def test_a_sent_po_cannot_be_edited(self, db):
        po = self._po(db)
        db.table("purchase_orders").update({"status": "sent"}).eq("id", po["id"]).execute()
        with pytest.raises(p.PurchaseError):
            p.save_po(db, T, {"supplier_id": po["supplier_id"], "lines": [{"catalog_item_id": SAREE, "qty": 1}]}, None, po["id"])

    def test_only_the_supplier_can_confirm_their_po(self, db, monkeypatch):
        import app.services.brain_digest as bd
        import app.services.notify as notify
        monkeypatch.setattr(bd, "owner_user_ids", lambda db_, t: ["owner-1"])
        bells = []
        monkeypatch.setattr(notify, "notify_user", lambda *a, **k: bells.append(a[3]))
        po = self._po(db)
        db.table("purchase_orders").update({"status": "sent"}).eq("id", po["id"]).execute()
        assert p.button_po(f"po_confirm:{po['id']}") == ("confirm", po["id"])
        assert asyncio.run(p.answer_from_supplier(db, T, "919999999999", "confirm", po["id"])) is False
        assert asyncio.run(p.answer_from_supplier(db, T, "919876543120", "confirm", po["id"])) is True
        assert db.rows("purchase_orders")[0]["status"] == "confirmed" and bells == ["Lakshmi Handlooms confirmed PO-0042"]

    def test_no_reply_in_two_days_rings_the_owner_once(self, db, monkeypatch):
        import app.services.brain_digest as bd
        import app.services.notify as notify
        monkeypatch.setattr(bd, "owner_user_ids", lambda db_, t: ["owner-1"])
        bells = []
        monkeypatch.setattr(notify, "notify_user", lambda *a, **k: bells.append(a[3]))
        po = self._po(db)
        db.table("purchase_orders").update({"status": "sent", "sent_at": (NOW - timedelta(days=3)).isoformat(),
                                            "tenant_id": T}).eq("id", po["id"]).execute()
        assert p.sweep_unanswered(db, NOW) == 1 and p.sweep_unanswered(db, NOW) == 0
        assert bells == ["No reply on PO-0042"]


class TestSuggestions:
    def test_low_items_are_suggested_from_sales_minus_stock_and_what_is_on_order(self, db):
        for _ in range(3):
            db.table("stock_movements").insert({"tenant_id": T, "catalog_item_id": KURTI, "variant_id": KURTI_M,
                                                "delta": -4, "reason": "sale", "created_at": NOW.isoformat()}).execute()
        rows = p.suggestions(db, T, NOW + timedelta(minutes=1))
        m = next(r for r in rows if r["variant_id"] == KURTI_M)
        assert (m["stock"], m["sold_30d"], m["suggested"]) == (0, 12, 12)
        assert any(r["catalog_item_id"] == SAREE for r in rows)  # 0 in stock, at or below its alert level


def test_bill_lines_are_matched_to_items_and_sizes(db):
    lines = p.match_lines(db, T, [{"name": "COTTON KURTI", "size": "m", "qty": 8, "unit_cost": 380, "gst_rate": 5},
                                  {"name": "Mystery item", "qty": 2, "unit_cost": 10}])
    assert lines[0]["catalog_item_id"] == KURTI and lines[0]["variant_id"] == KURTI_M and lines[0]["unit_cost_paise"] == 38000
    assert lines[1]["catalog_item_id"] is None and lines[1]["read_name"] == "Mystery item"


def test_a_supplier_writing_in_is_recognised_and_the_owner_told(db, monkeypatch):
    import app.services.brain_digest as bd
    import app.services.notify as notify
    monkeypatch.setattr(bd, "owner_user_ids", lambda db_, t: ["owner-1"])
    bells = []
    monkeypatch.setattr(notify, "notify_user", lambda *a, **k: bells.append((a[3], k.get("dedupe_lead_id"))))
    s = _supplier(db)
    assert p.supplier_by_phone(db, T, "+91 98765 43120")["id"] == s["id"]
    assert p.supplier_by_phone(db, T, "919999999999") is None and p.supplier_by_phone(db, T, "") is None
    p.note_supplier_message(db, T, "lead-9", s)
    assert bells == [("Lakshmi Handlooms sent a message", "lead-9")]


def test_a_double_click_does_not_add_the_stock_twice(db):
    body = {"request_id": "abcdef01-0000-0000-0000-000000000001",
            "lines": [{"catalog_item_id": SAREE, "qty_good": 5, "unit_cost_paise": 100}]}
    first = p.stock_in(db, T, body, None)
    again = p.stock_in(db, T, body, None)
    assert again["id"] == first["id"] and again.get("repeat") and db.moves == [("item", SAREE, 5, SHOP)]


def test_a_po_line_cannot_be_credited_with_another_item(db):
    s = _supplier(db)
    po = p.save_po(db, T, {"supplier_id": s["id"], "lines": [{"catalog_item_id": SAREE, "qty": 5}]}, None)
    with pytest.raises(p.PurchaseError, match="isn't on this purchase order"):
        p.stock_in(db, T, {"purchase_order_id": po["id"], "lines": [
            {"catalog_item_id": KURTI, "variant_id": KURTI_M, "purchase_order_line_id": po["lines"][0]["id"],
             "qty_good": 5, "unit_cost_paise": 1}]}, None)


def test_a_payment_cannot_point_at_another_suppliers_bill(db):
    a, b = _supplier(db), _supplier(db, name="Other", phone="9000000001")
    bill = p.stock_in(db, T, {"supplier_id": a["id"], "lines": [{"catalog_item_id": SAREE, "qty_good": 1, "unit_cost_paise": 1}]}, None)
    with pytest.raises(p.PurchaseError):
        p.record_payment(db, T, b["id"], {"amount_paise": 100, "stock_in_id": bill["id"]}, None)
