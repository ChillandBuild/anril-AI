"""Catalogue: photo linked to a colour (never sent when that colour is out of stock) and a photo
on damaged stock. Fake database; the stock function is a stand-in that writes the history row."""
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.main import app
from app.services import ai_reply
from app.services.catalog_photos import sendable_photos
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
ITEM = str(uuid.uuid5(uuid.NAMESPACE_URL, "item"))
ITEM2 = str(uuid.uuid5(uuid.NAMESPACE_URL, "item-t2"))
def _u(n):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "media-" + n))


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def _storage():
    storage = MagicMock()
    bucket = MagicMock()
    bucket.get_public_url.side_effect = lambda p: "https://files.test/" + p
    bucket.download.side_effect = lambda p: b"bytes:" + p.encode()
    storage.from_.return_value = bucket
    return storage, bucket


def _fresh_db():
    db = FakeSupabase()
    db.storage, _ = _storage()
    db.rows("catalog_items").extend([
        {"id": ITEM, "tenant_id": T1, "name": "Kurta", "stock_quantity": 5},
        {"id": ITEM2, "tenant_id": T2, "name": "Other", "stock_quantity": 5},
    ])
    db.rows("catalog_item_variants").extend([
        {"id": "v-red-m", "tenant_id": T1, "catalog_item_id": ITEM, "size": "M", "colour": "Red", "stock_quantity": 0},
        {"id": "v-red-l", "tenant_id": T1, "catalog_item_id": ITEM, "size": "L", "colour": "Red", "stock_quantity": 0},
        {"id": "v-blue-m", "tenant_id": T1, "catalog_item_id": ITEM, "size": "M", "colour": "Blue", "stock_quantity": 4},
        {"id": "v-green", "tenant_id": T1, "catalog_item_id": ITEM, "size": "M", "colour": "Green", "stock_quantity": None},
    ])
    db.rows("catalog_media").extend([
        {"id": _u("plain"), "tenant_id": T1, "catalog_item_id": ITEM, "storage_path": "t/plain.jpg", "label": "Front", "sort_order": 0, "colour": None},
        {"id": _u("red"), "tenant_id": T1, "catalog_item_id": ITEM, "storage_path": "t/red.jpg", "label": "Red", "sort_order": 1, "colour": "Red"},
        {"id": _u("blue"), "tenant_id": T1, "catalog_item_id": ITEM, "storage_path": "t/blue.jpg", "label": "Blue", "sort_order": 2, "colour": "blue"},
        {"id": _u("green"), "tenant_id": T1, "catalog_item_id": ITEM, "storage_path": "t/green.jpg", "label": "Green", "sort_order": 3, "colour": "Green"},
        {"id": _u("t2"), "tenant_id": T2, "catalog_item_id": ITEM2, "storage_path": "t2/x.jpg", "label": "x", "sort_order": 0, "colour": None},
    ])
    return db


class PhotoFilterTests(unittest.TestCase):
    def test_out_of_stock_colour_photo_is_never_picked(self):
        db = _fresh_db()
        ids = [r["id"] for r in sendable_photos(db, T1, ITEM, 10)]
        self.assertEqual(ids, [_u("plain"), _u("blue"), _u("green")])  # red is out; untracked green is fine

    def test_a_colour_with_any_stocked_size_still_counts_as_in_stock(self):
        db = _fresh_db()
        db.rows("catalog_item_variants")[0]["stock_quantity"] = 2  # Red M back in stock
        self.assertIn(_u("red"), [r["id"] for r in sendable_photos(db, T1, ITEM, 10)])

    def test_limit_applies_after_the_filter(self):
        db = _fresh_db()
        self.assertEqual([r["id"] for r in sendable_photos(db, T1, ITEM, 2)], [_u("plain"), _u("blue")])

    def test_other_business_photos_are_not_returned(self):
        db = _fresh_db()
        self.assertEqual(sendable_photos(db, T1, ITEM2, 10), [])

    def test_ai_image_loader_skips_the_out_of_stock_colour(self):
        db = _fresh_db()
        images = ai_reply._load_catalog_images(db, T1, [ITEM], 5, {ITEM: {"name": "Kurta"}})
        self.assertEqual([label for label, _ in images], ["Front", "Blue", "Green"])

    def test_nothing_linked_means_nothing_blocked(self):
        db = _fresh_db()
        for r in db.rows("catalog_media"):
            r["colour"] = None
        self.assertEqual(len(sendable_photos(db, T1, ITEM, 10)), 4)


class RouteBase(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        self.p = patch("app.routes.catalog.get_supabase", return_value=self.db)
        self.p.start()
        self.ctx = {"tenant_id": T1, "role": "owner", "user_id": "user-1", "permissions": []}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "user-1"}
        app.dependency_overrides[get_tenant_id] = lambda: T1
        app.dependency_overrides[get_tenant_and_role] = lambda: self.ctx
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.p.stop()


class MediaColourRouteTests(RouteBase):
    def test_link_a_colour_saves_the_items_own_spelling(self):
        res = self.client.patch("/api/v1/catalog/media/" + _u("plain"), json={"colour": "  RED "})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["colour"], "Red")

    def test_a_colour_the_item_does_not_have_is_400(self):
        res = self.client.patch("/api/v1/catalog/media/" + _u("plain"), json={"colour": "Purple"})
        self.assertEqual(res.status_code, 400)

    def test_empty_colour_clears_the_link(self):
        res = self.client.patch("/api/v1/catalog/media/" + _u("red"), json={"colour": ""})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()["colour"])

    def test_other_business_photo_is_404(self):
        res = self.client.patch("/api/v1/catalog/media/" + _u("t2"), json={"colour": "Red"})
        self.assertEqual(res.status_code, 404)

    def test_item_page_lists_each_photos_colour(self):
        with patch("app.routes.catalog.list_variants", return_value={"variants": []}), \
                patch("app.services.deals.held_quantities", return_value={}), \
                patch("app.services.meta_catalog.item_link", return_value="x"):
            res = self.client.get(f"/api/v1/catalog/items/{ITEM}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual({p["id"]: p["colour"] for p in res.json()["photos"]}[_u("red")], "Red")


class DamagedPhotoTests(RouteBase):
    def setUp(self):
        super().setUp()

        def apply(params):
            self.db.add("stock_movements", tenant_id=params["p_tenant_id"], catalog_item_id=params["p_item_id"],
                        delta=params["p_delta"], reason=params["p_reason"], note=params["p_note"],
                        created_by=params["p_created_by"], created_at="2026-11-23T10:00:00+00:00")
            return [{"ok": True, "quantity_after": 3, "tracked": True}]

        self.db.rpc_handlers["apply_stock_movement"] = apply
        self.db.rows("catalog_items")[0]["stock_quantity"] = 5
        self.db.rows("catalog_item_variants").clear()  # a plain item: one number

    def _upload(self, data=PNG, ctype="image/png", item=ITEM):
        return self.client.post(f"/api/v1/catalog/items/{item}/stock-photo", files={"file": ("d.png", data, ctype)})

    def test_upload_takes_a_picture_into_the_tenants_folder(self):
        res = self._upload()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["path"].startswith(f"{T1}/{ITEM}/stock/"))

    def test_upload_refuses_non_pictures_fakes_and_big_files(self):
        self.assertEqual(self._upload(b"hello", "text/plain").status_code, 400)
        self.assertEqual(self._upload(b"not a png at all", "image/png").status_code, 400)
        self.assertEqual(self._upload(PNG + b"0" * (5 * 1024 * 1024), "image/png").status_code, 413)

    def test_upload_stores_the_type_the_bytes_show_not_the_browsers_claim(self):
        res = self._upload(PNG, "image/jpeg")  # the browser says JPEG, the bytes are PNG
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["path"].endswith(".png"))
        args = self.db.storage.from_.return_value.upload.call_args
        self.assertEqual(args.args[2], {"content-type": "image/png"})

    def test_a_photo_problem_after_the_stock_change_is_not_an_error(self):
        path = self._upload().json()["path"]
        with patch("app.routes.catalog._attach_stock_photo_row", side_effect=RuntimeError("boom")):
            res = self.client.post(f"/api/v1/catalog/items/{ITEM}/correct-stock",
                                   json={"to": 3, "why": "damaged", "photo_path": path})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(self.db.rows("stock_movements")), 1)  # the stock did change

    def test_upload_for_another_business_item_is_404(self):
        self.assertEqual(self._upload(item=ITEM2).status_code, 404)

    def test_damaged_correction_attaches_the_photo_and_history_shows_it(self):
        path = self._upload().json()["path"]
        res = self.client.post(f"/api/v1/catalog/items/{ITEM}/correct-stock",
                               json={"to": 3, "why": "damaged", "photo_path": path})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.db.rows("stock_movements")[0]["photo_path"], path)
        hist = self.client.get(f"/api/v1/catalog/items/{ITEM}/stock-movements").json()["data"]
        self.assertEqual(hist[0]["photo_url"], "https://files.test/" + path)
        self.assertNotIn("photo_path", hist[0])

    def test_photo_only_goes_with_damaged(self):
        path = f"{T1}/{ITEM}/stock/a.png"
        res = self.client.post(f"/api/v1/catalog/items/{ITEM}/correct-stock",
                               json={"to": 3, "why": "lost", "photo_path": path})
        self.assertEqual(res.status_code, 400)

    def test_photo_path_from_another_business_or_item_is_refused(self):
        for bad in (f"{T2}/{ITEM}/stock/a.png", f"{T1}/{ITEM2}/stock/a.png", f"{T1}/{ITEM}/stock/../../x.png"):
            res = self.client.post(f"/api/v1/catalog/items/{ITEM}/correct-stock",
                                   json={"to": 3, "why": "damaged", "photo_path": bad})
            self.assertEqual(res.status_code, 400, bad)
        self.assertEqual(self.db.rows("stock_movements"), [])

    def test_damaged_without_a_photo_still_works(self):
        res = self.client.post(f"/api/v1/catalog/items/{ITEM}/correct-stock", json={"to": 4, "why": "damaged"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("photo_path", self.db.rows("stock_movements")[0])


if __name__ == "__main__":
    unittest.main()
