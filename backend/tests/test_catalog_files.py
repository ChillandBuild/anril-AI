"""Shop files (migration 306, services/catalog_files.py): what can be uploaded, the AI's send_file
tool, and sending after the reply."""
import asyncio

import pytest

from app.services import catalog_files as cf
from app.services import deal_actions
from tests.fake_supabase import FakeSupabase

T = "tenant-1"
PDF = b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj 2 0 obj << /Type /Page >> endobj 3 0 obj << /Type /Pages >>"
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100


class _Bucket:
    def __init__(self):
        self.saved = {}

    def upload(self, path, content, opts):
        self.saved[path] = (content, opts)

    def get_public_url(self, path):
        return f"https://files.example/{path}"

    def remove(self, paths):
        for p in paths:
            self.saved.pop(p, None)


@pytest.fixture
def db():
    db = FakeSupabase()
    bucket = _Bucket()
    db.storage = type("S", (), {"from_": staticmethod(lambda name: bucket)})()
    db.bucket = bucket
    db.rpc_handlers["record_catalog_file_send"] = lambda p: (
        db.table("catalog_file_sends").insert({"tenant_id": p["p_tenant_id"], "file_id": p["p_file_id"],
                                               "lead_id": p["p_lead_id"],
                                               "sent_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}).execute(), None)[1]
    return db


class TestUpload:
    def test_the_file_type_comes_from_its_bytes_not_its_name(self):
        assert cf.sniff(PDF) == ("document", "application/pdf")
        assert cf.sniff(JPG) == ("image", "image/jpeg")
        assert cf.sniff(MP4) == ("video", "video/mp4")
        assert cf.sniff(b"<html>price list</html>") is None

    def test_whatsapp_size_limits(self):
        with pytest.raises(cf.FileError):
            cf.check_upload(JPG + b"\x00" * (5 * 1024 * 1024))
        with pytest.raises(cf.FileError):
            cf.check_upload(b"MZ\x90\x00 an exe")

    def test_a_pdf_is_saved_with_its_pages_and_a_clean_name(self, db):
        row = cf.upload(db, T, PDF, filename="price_list-nov-2026.pdf", title="", send_when="  asks for the  price list ",
                        item_id=None, user_id=None)
        assert row["title"] == "price list nov 2026" and row["pages"] == 2 and row["kind"] == "document"
        assert row["send_when"] == "asks for the price list" and row["url"].endswith(".pdf")
        assert row["storage_path"].startswith(f"{T}/files/")


class TestAi:
    def test_only_files_with_send_when_words_reach_the_ai(self, db):
        cf.upload(db, T, PDF, filename="a.pdf", title="Price list", send_when="asks for prices", item_id=None, user_id=None)
        cf.upload(db, T, JPG, filename="b.jpg", title="Shop map", send_when=None, item_id=None, user_id=None)
        tool = cf.ai_tool(cf.ai_files(db, T))
        assert tool["function"]["name"] == "send_file"
        assert 'PDF "Price list" -- send when: asks for prices' in tool["function"]["description"]
        assert "Shop map" not in tool["function"]["description"]
        assert cf.ai_tool([]) is None

    def test_at_most_two_files_a_reply(self):
        ctx = deal_actions.DealContext(config={}, db=None, lead_id="l", tenant_id=T, phone="x")
        turn = deal_actions._Turn()
        for fid in ("a", "a", "b"):
            assert asyncio.run(deal_actions._send_file(ctx, {"file_id": fid}, turn)) is None
        assert "at most" in asyncio.run(deal_actions._send_file(ctx, {"file_id": "c"}, turn))
        assert turn.outcome().file_ids == ("a", "b")

    def test_sending_counts_it_and_logs_the_message(self, db, monkeypatch):
        row = cf.upload(db, T, PDF, filename="a.pdf", title="Price list", send_when="prices", item_id=None, user_id=None)
        off = cf.upload(db, T, JPG, filename="b.jpg", title="Old", send_when="x", item_id=None, user_id=None)
        cf.update(db, T, off["id"], {"ai_enabled": False})
        sent = []

        async def fake_send(**kw):
            sent.append(kw)
            return {"messages": [{"id": "wamid.f"}]}

        import app.services.meta_cloud as meta_cloud
        monkeypatch.setattr(meta_cloud, "send_media_message", fake_send)
        n = asyncio.run(cf.send_after_reply(db, T, "lead-1", "9198", [row["id"], off["id"], "unknown"]))
        assert n == 1 and sent[0]["wa_type"] == "document" and sent[0]["filename"] == "Price list.pdf"
        assert db.rows("catalog_file_sends")[0]["file_id"] == row["id"]
        assert db.rows("messages")[0]["content"] == "[PDF: Price list]"


def test_a_heic_photo_is_not_taken_for_a_video():
    assert cf.sniff(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 50) is None


def test_the_same_file_is_not_sent_twice_a_day_to_one_customer(db, monkeypatch):
    row = cf.upload(db, T, PDF, filename="a.pdf", title="Price list", send_when="prices", item_id=None, user_id=None)
    sent = []

    async def fake_send(**kw):
        sent.append(kw)
        return {"messages": [{"id": "w"}]}

    import app.services.meta_cloud as meta_cloud
    monkeypatch.setattr(meta_cloud, "send_media_message", fake_send)
    asyncio.run(cf.send_after_reply(db, T, "lead-1", "9198", [row["id"]]))
    asyncio.run(cf.send_after_reply(db, T, "lead-1", "9198", [row["id"]]))
    assert len(sent) == 1
