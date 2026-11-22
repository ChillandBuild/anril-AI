"""Barcodes (migration 311, services/barcodes.py): own short codes, company barcodes, labels, scanning."""
from unittest.mock import patch

import pytest

from app.services import barcodes as bc
from tests.fake_supabase import FakeSupabase

T = "aaaaaaaa-0000-0000-0000-000000000001"
KP, SILK, SVC = "cccccccc-0000-0000-0000-000000000001", "cccccccc-0000-0000-0000-000000000002", "cccccccc-0000-0000-0000-000000000003"
RM, RL = "dddddddd-0000-0000-0000-000000000001", "dddddddd-0000-0000-0000-000000000002"


@pytest.fixture
def db():
    db = FakeSupabase()
    db.add("catalog_items", id=KP, tenant_id=T, name="Kanchi pattu", price_paise=1050000, item_type="product")
    db.add("catalog_items", id=SILK, tenant_id=T, name="Soft silk", price_paise=245000, item_type="product")
    db.add("catalog_items", id=SVC, tenant_id=T, name="Blouse stitching", price_paise=40000, item_type="service")
    db.add("catalog_item_variants", id=RM, tenant_id=T, catalog_item_id=KP, size="M", colour="Red", price_paise=None)
    db.add("catalog_item_variants", id=RL, tenant_id=T, catalog_item_id=KP, size="L", colour="Red", price_paise=1100000)
    return db


@pytest.fixture(autouse=True)
def shop_name():
    with patch("app.services.business_details.get_business_details", return_value={"legal_name": "Demo Silks"}):
        yield


class TestCodes:
    @pytest.mark.parametrize("item, variant, want", [
        ("Kanchi pattu", {"size": "M", "colour": "Red"}, "DS-KP-RM"),
        ("Soft silk", None, "DS-SS"),
        ("Saree", {"size": None, "colour": "Green"}, "DS-SA-GR"),
        ("Cotton kurti", {"size": "XL", "colour": None}, "DS-CK-XL"),
    ])
    def test_own_codes_read_like_the_item(self, item, variant, want):
        assert bc.own_code("DS", item, variant) == want

    def test_codes_are_made_once_and_never_clash(self, db):
        db.add("stock_codes", tenant_id=T, catalog_item_id=SVC, variant_id=None, code="DS-KP-RM", company=False)
        made = bc.ensure_codes(db, T, [(KP, RM), (KP, RL), (SILK, None)])
        assert [made[(KP, RM)]["code"], made[(KP, RL)]["code"], made[(SILK, None)]["code"]] == ["DS-KP-RM2", "DS-KP-RL", "DS-SS"]
        again = bc.ensure_codes(db, T, [(KP, RM)])
        assert again[(KP, RM)]["code"] == "DS-KP-RM2" and len(db.rows("stock_codes")) == 4

    def test_a_size_of_another_item_gets_no_code(self, db):
        assert bc.ensure_codes(db, T, [(SILK, RM)]) == {}


class TestScanAndCompanyCodes:
    def test_scanning_finds_the_size_and_its_price(self, db):
        bc.ensure_codes(db, T, [(KP, RL)])
        found = bc.lookup(db, T, " ds-kp-rl ")
        assert found["variant_id"] == RL and found["variant_label"] == "Red · L" and found["price_paise"] == 1100000
        assert bc.lookup(db, T, "NOPE-1") is None and bc.lookup(db, T, "x") is None

    def test_a_company_barcode_replaces_the_own_code_and_must_be_unique(self, db):
        bc.ensure_codes(db, T, [(SILK, None)])
        bc.set_company_code(db, T, SILK, None, "8901030865278")
        assert [(c["code"], c["company"]) for c in db.rows("stock_codes")] == [("8901030865278", True)]
        with pytest.raises(bc.BarcodeError, match="already has"):
            bc.set_company_code(db, T, KP, RM, "8901030865278")
        with pytest.raises(bc.BarcodeError, match="8, 12, 13 or 14 digits"):
            bc.set_company_code(db, T, KP, RM, "12345")
        bc.set_company_code(db, T, SILK, None, "")
        assert db.rows("stock_codes") == []

    def test_a_typo_never_wipes_the_code_on_printed_labels(self, db):
        bc.ensure_codes(db, T, [(SILK, None)])
        with pytest.raises(bc.BarcodeError):
            bc.set_company_code(db, T, SILK, None, "12345")
        assert [c["code"] for c in db.rows("stock_codes")] == ["DS-SS"]


class TestLabels:
    def test_picked_items_print_with_their_price_and_company_codes_are_left_out(self, db):
        bc.set_company_code(db, T, SILK, None, "8901030865278")
        out = bc.labels(db, T, {"source": "pick", "lines": [{"item_id": KP, "variant_id": RL, "qty": 3},
                                                            {"item_id": KP, "variant_id": RM, "qty": 1},
                                                            {"item_id": SILK, "variant_id": None, "qty": 2}]})
        assert [(l["code"], l["qty"], l["price_paise"]) for l in out["labels"]] == [("DS-KP-RL", 3, 1100000), ("DS-KP-RM", 1, 1050000)]
        assert out["kept_company"] == 1 and out["shop_name"] == "Demo Silks"

    def test_items_with_no_barcode_yet_skip_services(self, db):
        assert bc.labels(db, T, {"source": "no_code"})["labels"] and bc.options(db, T)["no_code"] == 3  # preview saves nothing
        out = bc.labels(db, T, {"source": "no_code", "save": True})
        assert sorted(l["code"] for l in out["labels"]) == ["DS-KP-RL", "DS-KP-RM", "DS-SS"]
        assert bc.options(db, T)["no_code"] == 0

    def test_todays_stock_in_prints_one_label_per_piece_kept(self, db):
        db.add("stock_ins", id="eeeeeeee-0000-0000-0000-000000000001", tenant_id=T, bill_no="SMT/1182", created_at="2099-01-01T10:00:00+05:30")
        db.add("stock_in_lines", tenant_id=T, stock_in_id="eeeeeeee-0000-0000-0000-000000000001", catalog_item_id=KP, variant_id=RM, qty_good=4,
               qty_damaged=1, damaged_action="discount")
        db.add("stock_in_lines", tenant_id=T, stock_in_id="eeeeeeee-0000-0000-0000-000000000001", catalog_item_id=SILK, variant_id=None, qty_good=6,
               qty_damaged=2, damaged_action="replace")
        assert bc.options(db, T)["stock_in"]["labels"] == 11
        out = bc.labels(db, T, {"source": "stock_in"})
        assert [(l["code"], l["qty"]) for l in out["labels"]] == [("DS-KP-RM", 5), ("DS-SS", 6)]

    def test_too_many_labels_are_refused(self, db):
        with pytest.raises(bc.BarcodeError, match="Print in parts"):
            bc.labels(db, T, {"source": "pick", "lines": [{"item_id": KP, "variant_id": RM, "qty": 500}] * 5})
