"""Stock per place (migration 304): every change goes through apply_stock_movement /
apply_variant_stock_movement, which keep the item total = the sum of its places. These tests pin
that the catalogue never writes a stock number straight into the item any more (the SQL itself
was tested against the live database inside a rolled-back transaction, 2026-11-21)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies.auth import get_current_user  # noqa: E402
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id  # noqa: E402
from app.main import app  # noqa: E402
from app.services import deals  # noqa: E402


def _client():
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
    app.dependency_overrides[get_tenant_id] = lambda: "tenant-1"
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "tenant-1", "role": "owner"}
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


@patch("app.routes.catalog.embed_and_store_catalog_item")
@patch("app.routes.catalog.get_supabase")
def test_opening_stock_goes_in_through_the_stock_function(mock_get_db, _embed):
    db = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "item-1", "name": "Kaju katli", "item_type": "product", "status": "draft", "stock_quantity": 0}]
    db.rpc.return_value.execute.return_value.data = [{"ok": True, "tracked": True, "quantity_after": 5}]
    mock_get_db.return_value = db

    res = _client().post("/api/v1/catalog/items", json={"name": "Kaju katli", "stock_quantity": 5})

    assert res.status_code == 200 and res.json()["stock_quantity"] == 5
    assert db.table.return_value.insert.call_args[0][0]["stock_quantity"] == 0  # saved at 0 first
    name, params = db.rpc.call_args[0]
    assert name == "apply_stock_movement"
    assert params["p_delta"] == 5 and params["p_reason"] == "restock" and params["p_note"] == "Opening stock"


@patch("app.routes.catalog.embed_and_store_catalog_item")
@patch("app.routes.catalog.get_supabase")
def test_an_item_without_stock_stays_untracked(mock_get_db, _embed):
    db = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "item-1", "name": "Consultation", "item_type": "service", "status": "draft", "stock_quantity": None}]
    mock_get_db.return_value = db

    _client().post("/api/v1/catalog/items", json={"name": "Consultation", "item_type": "service"})

    assert db.table.return_value.insert.call_args[0][0]["stock_quantity"] is None
    db.rpc.assert_not_called()


def test_a_place_is_sent_only_when_one_is_chosen():
    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = [{"ok": True, "tracked": True, "quantity_after": 1}]
    deals.adjust_stock("tenant-1", "item-1", -1, "sale", db=db)
    assert "p_place_id" not in db.rpc.call_args[0][1]  # the business's bill place
    deals.adjust_stock("tenant-1", "item-1", -1, "sale", place_id="place-2", db=db)
    assert db.rpc.call_args[0][1]["p_place_id"] == "place-2"
    db.rpc.return_value.execute.return_value.data = [{"ok": True, "quantity_after": 1, "item_quantity_after": 3}]
    deals.adjust_variant_stock("tenant-1", "v-1", 2, "restock", place_id="place-3", db=db)
    assert db.rpc.call_args[0] == ("apply_variant_stock_movement", {
        "p_tenant_id": "tenant-1", "p_variant_id": "v-1", "p_delta": 2, "p_reason": "restock", "p_deal_id": None,
        "p_note": None, "p_created_by": None, "p_place_id": "place-3"})
