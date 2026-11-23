"""Business details & bills (services/business_details.py, bill_number_format.py, routes/business_details.py)."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import business_details as route
from app.services import business_details as svc
from app.services import orders
from app.services.bill_number_format import clean_prefix, format_bill_number, format_number
from tests.fake_supabase import FakeSupabase, FakeStorage
from tests.test_orders import T, _deal, db as orders_db  # noqa: F401  (orders_db is the orders fixture)

OWNER = {"tenant_id": T, "user_id": "u1", "role": "owner", "permissions": []}
VIEWER = {"tenant_id": T, "user_id": "u2", "role": "member", "permissions": ["settings.view"]}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def _fresh():
    db = FakeSupabase()
    db.storage = FakeStorage()
    return db


def _store(db, **fields):
    db.add("app_settings", tenant_id=T, key="business_details", value=json.dumps(fields), is_secret=False)


@pytest.fixture
def patched(monkeypatch):
    db = _fresh()
    monkeypatch.setattr(route, "get_supabase", lambda: db)
    monkeypatch.setattr(svc, "get_supabase", lambda: db)
    return db


# ── bill number ─────────────────────────────────────────────────────────────────

def test_default_number_is_exactly_todays_format():
    assert format_number("", "2026-27", 45) == "2026-27/0045" == f"{'2026-27'}/{45:04d}"
    assert format_number("", "2026-27", 12345) == "2026-27/12345"


def test_prefix_number_uses_the_short_year():
    assert format_number("DS", "2026-27", 1) == "DS/26-27/0001"


def test_prefix_is_capitalised_and_checked():
    assert clean_prefix(" ds ") == "DS"
    assert clean_prefix("") == "" and clean_prefix(None) == ""
    for bad in ("TOOLONG1", "D S", "D/S", "dé"):
        with pytest.raises(ValueError):
            clean_prefix(bad)


def test_format_bill_number_reads_the_tenant_prefix():
    db = _fresh()
    assert format_bill_number(db, T, "2026-27", 7) == "2026-27/0007"
    _store(db, bill_prefix="DS")
    assert format_bill_number(db, T, "2026-27", 7) == "DS/26-27/0007"
    assert format_bill_number(db, "other-tenant", "2026-27", 7) == "2026-27/0007"


def test_a_broken_prefix_or_unreadable_settings_fall_back_to_the_default():
    db = _fresh()
    _store(db, bill_prefix="no good!")
    assert format_bill_number(db, T, "2026-27", 3) == "2026-27/0003"

    class Boom:
        def table(self, *_):
            raise RuntimeError("down")
    assert format_bill_number(Boom(), T, "2026-27", 3) == "2026-27/0003"


def test_the_invoice_gets_the_prefixed_number_and_the_counter_still_restarts_each_year(orders_db):
    _deal(orders_db, stage="won", paid_paise=240000)
    _store(orders_db, bill_prefix="DS")
    number = orders.ensure_invoice(orders_db, T, "d1")
    fy = orders.fiscal_year(orders._now())
    assert number == f"DS/{fy[2:]}/0001"
    # the counter is per financial year: a new year starts again at 1
    assert orders_db._next_invoice({"p_tenant_id": T, "p_fy": "2099-00"}) == 1


def test_the_invoice_without_a_prefix_is_unchanged(orders_db):
    _deal(orders_db, stage="won", paid_paise=240000)
    number = orders.ensure_invoice(orders_db, T, "d1")
    assert number == f"{orders.fiscal_year(orders._now())}/0001"


# ── validation ──────────────────────────────────────────────────────────────────

def _base():
    return {k: "" for k in svc.TEXT_FIELDS + svc.BILL_FIELDS + svc.IMAGE_FIELDS} | {"gst_type": "regular", "prices_include_gst": True}


@pytest.mark.parametrize("field,good,bad", [
    ("pan", "abcde1234f", "ABCDE12345"),
    ("bank_ifsc", "sbin0001234", "SBIN1001234"),
    ("upi_id", "shop.name@okbank", "no-at-sign"),
    ("bank_account_number", "123456789012", "12ab34"),
    ("state_code", "33", "3"),
    ("gstin", "33abcde1234f1z5", "33ABCDE1234F1Z"),
])
def test_each_checked_field_accepts_a_good_value_and_refuses_a_bad_one(field, good, bad):
    saved = svc.clean_update(_base(), {field: good})
    assert saved[field] == (good.upper() if field in ("pan", "bank_ifsc", "gstin") else good)
    with pytest.raises(svc.BusinessDetailsError):
        svc.clean_update(_base(), {field: bad})


def test_gst_type_licence_and_terms_limits():
    for ok in ("regular", "composition", "none"):
        assert svc.clean_update(_base(), {"gst_type": ok})["gst_type"] == ok
    with pytest.raises(svc.BusinessDetailsError):
        svc.clean_update(_base(), {"gst_type": "other"})
    with pytest.raises(svc.BusinessDetailsError):
        svc.clean_update(_base(), {"licence_number": "x" * 61})
    with pytest.raises(svc.BusinessDetailsError):
        svc.clean_update(_base(), {"terms": "x" * 1001})
    assert svc.clean_update(_base(), {"terms": "x" * 1000})["terms"] == "x" * 1000


def test_only_what_is_sent_changes_and_the_masked_bank_number_keeps_the_saved_one():
    base = _base() | {"bank_account_number": "123456789012", "bill_prefix": "DS", "logo_path": f"{T}/logo.png"}
    out = svc.clean_update(base, {"legal_name": "Shree Silks"})
    assert out["bank_account_number"] == "123456789012" and out["bill_prefix"] == "DS" and out["logo_path"].endswith("logo.png")
    out = svc.clean_update(base, {"bank_account_number": "••••9012", "bill_prefix": "ab"})
    assert out["bank_account_number"] == "123456789012" and out["bill_prefix"] == "AB"
    # the pictures can't be set through the form
    assert svc.clean_update(base, {"logo_path": "evil"})["logo_path"].endswith("logo.png")


# ── the routes ──────────────────────────────────────────────────────────────────

def test_only_the_last_four_digits_of_the_account_show_to_a_viewer(patched):
    _store(patched, bank_account_number="123456789012", legal_name="Shree Silks")
    assert route.read_profile(ctx=VIEWER)["bank_account_number"] == "••••9012"
    assert route.read_profile(ctx=OWNER)["bank_account_number"] == "123456789012"
    assert "logo_path" not in route.read_profile(ctx=OWNER)


def test_saving_writes_an_audit_row_without_values_and_hides_the_raw_blob(patched):
    out = route.update_profile(route.BusinessProfileIn(pan="ABCDE1234F", bank_account_number="123456789012"), ctx=OWNER)
    assert out["pan"] == "ABCDE1234F"
    row = patched.rows("app_settings")[0]
    assert row["is_secret"] is True  # the generic settings list shows it masked
    audit = patched.rows("app_audit_logs")[0]
    assert audit["action"] == "business_details.updated"
    assert "bank_account_number" in audit["metadata"]["fields"] and "123456789012" not in json.dumps(audit)


def test_a_bad_value_is_a_plain_400(patched):
    with pytest.raises(HTTPException) as e:
        route.update_profile(route.BusinessProfileIn(pan="nope"), ctx=OWNER)
    assert e.value.status_code == 400 and "PAN" in e.value.detail


def test_an_older_screen_sending_the_old_nine_fields_keeps_the_new_ones(patched):
    _store(patched, bill_prefix="DS", upi_id="shop@upi")
    out = route.update_profile(route.BusinessProfileIn(legal_name="X", gstin="", prices_include_gst=True), ctx=OWNER)
    assert out["bill_prefix"] == "DS" and out["upi_id"] == "shop@upi"


def _upload(kind, content, mime, db):
    from io import BytesIO
    from starlette.datastructures import Headers, UploadFile
    f = UploadFile(BytesIO(content), filename="x", headers=Headers({"content-type": mime}))
    return asyncio.run(route.upload_image(kind, file=f, ctx=OWNER))


def test_logo_upload_stores_the_picture_and_returns_a_link(patched):
    out = _upload("logo", PNG, "image/png", patched)
    assert out["has_logo"] and out["logo_url"].startswith("https://")
    assert (svc.BRAND_BUCKET, f"{T}/logo.png") in patched.storage.files
    # replacing with a jpg removes the old png
    _upload("logo", b"\xff\xd8\xff" + b"0" * 50, "image/jpeg", patched)
    assert (svc.BRAND_BUCKET, f"{T}/logo.png") not in patched.storage.files
    assert (svc.BRAND_BUCKET, f"{T}/logo.jpg") in patched.storage.files
    route_out = asyncio.run(route.delete_image("logo", ctx=OWNER))
    assert not route_out["has_logo"] and not patched.storage.files


@pytest.mark.parametrize("content,mime", [
    (PNG + b"0" * (1024 * 1024), "image/png"),      # over 1 MB
    (b"GIF89a" + b"0" * 20, "image/gif"),            # wrong type
    (b"not really a png at all", "image/png"),        # lying about the type
    (b"", "image/png"),
])
def test_bad_pictures_are_refused(patched, content, mime):
    with pytest.raises(HTTPException) as e:
        _upload("signature", content, mime, patched)
    assert e.value.status_code == 400 and not patched.storage.files


def test_unknown_picture_kind_is_refused(patched):
    with pytest.raises(HTTPException):
        _upload("banner", PNG, "image/png", patched)


def test_a_missing_bucket_gives_a_friendly_error_not_a_500(patched):
    class Broken:
        def from_(self, *_):
            raise RuntimeError("bucket not found")
    patched.storage = Broken()
    with pytest.raises(HTTPException) as e:
        _upload("logo", PNG, "image/png", patched)
    assert e.value.status_code == 400 and "try again" in e.value.detail
