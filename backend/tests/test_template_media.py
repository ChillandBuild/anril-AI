# backend/tests/test_template_media.py
"""Template header media must keep sending after Meta's example link expires.

Meta's synced example link (scontent.whatsapp.net, oe=<hex unix time>) expires,
and an in-app upload only yields a Meta handle. Both are replaced by our own
copy in the template-media bucket."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services import template_media

TENANT = "tenant-1"
# oe=6a1f0000 -> 2026-05-31: already expired.
EXPIRED_META_URL = "https://scontent.whatsapp.net/v/t61/abc.jpg?oe=6a1f0000&oh=xyz"
OURS = f"https://proj.supabase.co/storage/v1/object/public/template-media/{TENANT}/cold_leads_reengagement-1a2b3c.jpg"


def _bucket_db():
    db = MagicMock()
    bucket = db.storage.from_.return_value
    bucket.get_public_url.side_effect = lambda path: f"https://proj.supabase.co/storage/v1/object/public/template-media/{path}"
    return db, bucket


def _client_with(handler):
    real = httpx.AsyncClient
    return lambda **kw: real(transport=httpx.MockTransport(handler), **kw)


# ── copy_from_meta ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_copy_from_meta_stores_file_and_returns_permanent_url():
    db, bucket = _bucket_db()
    handler = lambda req: httpx.Response(200, content=b"JPEGDATA", headers={"content-type": "image/jpeg"})
    with patch.object(template_media.httpx, "AsyncClient", _client_with(handler)):
        url = await template_media.copy_from_meta(db, TENANT, "promo", EXPIRED_META_URL)

    path, data, opts = bucket.upload.call_args.args
    assert path.startswith(f"{TENANT}/promo-") and path.endswith(".jpg")
    assert data == b"JPEGDATA" and opts["content-type"] == "image/jpeg"
    assert template_media.is_ours(url) and "scontent" not in url


@pytest.mark.asyncio
async def test_copy_from_meta_same_file_same_url():
    db, _ = _bucket_db()
    handler = lambda req: httpx.Response(200, content=b"SAME", headers={"content-type": "image/png"})
    with patch.object(template_media.httpx, "AsyncClient", _client_with(handler)):
        a = await template_media.copy_from_meta(db, TENANT, "promo", EXPIRED_META_URL)
        b = await template_media.copy_from_meta(db, TENANT, "promo", EXPIRED_META_URL + "&new=sig")
    assert a == b


@pytest.mark.asyncio
async def test_copy_from_meta_gives_up_on_expired_link():
    db, bucket = _bucket_db()
    handler = lambda req: httpx.Response(403, content=b"URL signature expired")
    with patch.object(template_media.httpx, "AsyncClient", _client_with(handler)):
        assert await template_media.copy_from_meta(db, TENANT, "promo", EXPIRED_META_URL) is None
    bucket.upload.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://scontent.whatsapp.net/a.jpg",          # not https
    "https://evil.example.com/a.jpg",               # not Meta
    "https://whatsapp.net.evil.com/a.jpg",          # lookalike host
    "http://169.254.169.254/latest/meta-data",      # internal address
])
async def test_copy_from_meta_only_fetches_meta_cdn(url):
    db, _ = _bucket_db()

    def handler(req):
        raise AssertionError(f"must not fetch {req.url}")

    with patch.object(template_media.httpx, "AsyncClient", _client_with(handler)):
        assert await template_media.copy_from_meta(db, TENANT, "promo", url) is None


@pytest.mark.asyncio
async def test_copy_from_meta_refuses_oversized_file():
    db, bucket = _bucket_db()
    handler = lambda req: httpx.Response(200, content=b"x" * (template_media.MAX_BYTES + 1))
    with patch.object(template_media.httpx, "AsyncClient", _client_with(handler)):
        assert await template_media.copy_from_meta(db, TENANT, "promo", EXPIRED_META_URL) is None
    bucket.upload.assert_not_called()


# ── sync-from-meta ────────────────────────────────────────────────────────────

def _meta_template(example_url):
    return {
        "name": "cold_leads_reengagement", "status": "APPROVED", "category": "MARKETING",
        "language": "en", "id": "meta-1",
        "components": [
            {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [example_url]}},
            {"type": "BODY", "text": "Hi {{1}}, still interested?"},
        ],
    }


async def _run_sync(existing_rows, copy_result):
    from app.routes.templates import sync_templates_from_meta

    written: dict = {}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = existing_rows

    def capture_update(values):
        written["update"] = values
        return MagicMock()

    def capture_insert(values):
        written["insert"] = values
        return MagicMock()

    db.table.return_value.update.side_effect = capture_update
    db.table.return_value.insert.side_effect = capture_insert

    async def fake_list(**kw):
        return [_meta_template(EXPIRED_META_URL)]

    async def fake_copy(_db, tenant_id, name, url):
        return copy_result

    with patch("app.routes.templates.get_setting", side_effect=lambda k, **kw: "waba-1" if k == "meta_waba_id" else None), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.list_all_templates", side_effect=fake_list), \
         patch.object(template_media, "copy_from_meta", side_effect=fake_copy):
        await sync_templates_from_meta(tenant_id=TENANT)
    return written


@pytest.mark.asyncio
async def test_sync_stores_our_copy_not_metas_expiring_link():
    """Regression: sync used to save Meta's scontent link, which expires."""
    written = await _run_sync(existing_rows=[], copy_result=OURS)
    assert written["insert"]["header_media_url"] == OURS


@pytest.mark.asyncio
async def test_sync_after_meta_link_expired_keeps_our_copy():
    existing = [{
        "name": "cold_leads_reengagement", "status": "APPROVED", "category": "MARKETING", "language": "en",
        "body_text": "Hi {{1}}, still interested?", "meta_template_id": "meta-1", "meta_waba_id": "waba-1",
        "rejection_reason": None, "header_text": None, "header_media_type": "IMAGE",
        "header_media_url": OURS, "footer_text": None, "buttons": None, "approved_at": "2026-11-01T00:00:00Z",
    }]
    written = await _run_sync(existing_rows=existing, copy_result=None)
    # Nothing changed, so no write; and the expired Meta link never replaces ours.
    assert "update" not in written


@pytest.mark.asyncio
async def test_synced_row_sends_our_link_after_expiry():
    """End to end: what sync stores is what a send puts in the header."""
    from app.services.auto_messages import build_components
    from app.services.reengagement_service import _header_component

    row = (await _run_sync(existing_rows=[], copy_result=OURS))["insert"]

    comps = build_components(row, {"variables": []}, {"first_name": "Priya"})
    assert comps[0] == {"type": "header", "parameters": [{"type": "image", "image": {"link": OURS}}]}

    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [row]
    header = _header_component(db, TENANT, "cold_leads_reengagement", {"name": "Priya"})
    assert header["parameters"][0]["image"]["link"] == OURS


# ── in-app upload / create / edit ─────────────────────────────────────────────

def test_upload_then_link_for_turns_handle_into_our_url():
    db, bucket = _bucket_db()
    handle = "4::aW1hZ2UvanBlZw==:ARZ"
    template_media.save_upload(db, TENANT, handle, b"IMG", "image/jpeg")
    stored_path = bucket.upload.call_args.args[0]
    bucket.list.return_value = [{"name": stored_path.rsplit("/", 1)[1]}]

    url = template_media.link_for(db, TENANT, handle)
    assert url.endswith(stored_path) and template_media.is_ours(url)


def test_link_for_leaves_unknown_handle_and_urls_alone():
    db, bucket = _bucket_db()
    bucket.list.return_value = []
    assert template_media.link_for(db, TENANT, "4::unknown") == "4::unknown"
    assert template_media.link_for(db, TENANT, OURS) == OURS
    assert template_media.link_for(db, TENANT, None) is None


@pytest.mark.asyncio
async def test_create_stores_link_not_handle():
    from app.routes.templates import create_template, CreateTemplate

    payload = CreateTemplate(
        name="promo", category="MARKETING", language="en", body_text="Big sale this week",
        header_media_type="IMAGE", header_media_url="4::handle",
    )
    captured: dict = {}
    submitted: dict = {}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    def capture_insert(values):
        captured.update(values)
        chain = MagicMock()
        chain.execute.return_value.data = [values]
        return chain

    db.table.return_value.insert.side_effect = capture_insert

    async def fake_submit(**kw):
        submitted.update(kw)
        return {"id": "meta-9"}

    with patch("app.routes.templates.get_setting", side_effect=lambda k, **kw: "waba-1" if k == "meta_waba_id" else None), \
         patch("app.routes.templates.get_supabase", return_value=db), \
         patch("app.routes.templates.submit_template", side_effect=fake_submit), \
         patch.object(template_media, "link_for", return_value=OURS):
        await create_template(payload, tenant_id=TENANT)

    assert submitted["header_media_url"] == "4::handle", "Meta's review still gets the upload handle"
    assert captured["header_media_url"] == OURS


@pytest.mark.asyncio
async def test_edit_reuploads_our_copy_for_metas_example():
    from app.routes.templates import _meta_header_handle

    uploaded: dict = {}

    async def fake_upload(**kw):
        uploaded.update(kw)
        return "4::fresh"

    with patch.object(template_media, "read_ours", return_value=(b"IMG", "image/jpeg")), \
         patch("app.routes.templates.upload_media_for_template", side_effect=fake_upload), \
         patch("app.routes.templates.get_setting", return_value="app-1"):
        assert await _meta_header_handle(MagicMock(), TENANT, "IMAGE", OURS) == "4::fresh"
    assert uploaded["file_bytes"] == b"IMG"

    # Not ours / not media: passed through untouched, no upload.
    assert await _meta_header_handle(MagicMock(), TENANT, "IMAGE", "4::handle") == "4::handle"
    assert await _meta_header_handle(MagicMock(), TENANT, None, OURS) == OURS
