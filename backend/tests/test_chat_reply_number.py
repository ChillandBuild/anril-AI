"""A reply typed in Chats goes from the number the customer wrote to, not always the primary.

WhatsApp's 24-hour window is per business number: a free reply is only allowed from the number
the customer messaged, and a reply from another number lands in a different chat on their phone.
The AI already replied from that number; staff replies (text, compose, photos/files) did not.
"""
from unittest.mock import AsyncMock

import pytest

from tests.fake_supabase import FakeSupabase

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
LEAD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PHONE = "+919876543210"
SECOND = "meta-pid-second"
PRIMARY = "meta-pid-primary"


def _db(last_inbound: str | None, *, number_tenant: str = T1, number_status: str = "active") -> FakeSupabase:
    db = FakeSupabase()
    db.add("leads", id=LEAD, tenant_id=T1, phone=PHONE, source="whatsapp", blocked_at=None,
           last_inbound_phone_number_id=last_inbound)
    db.add("phone_numbers", id="n1", tenant_id=T1, meta_phone_number_id=PRIMARY, role="primary", status="active")
    db.add("phone_numbers", id="n2", tenant_id=number_tenant, meta_phone_number_id=SECOND, role="standby", status=number_status)
    return db


def _use(monkeypatch, db):
    from app.routes import leads
    from app.services import blocked_guard
    monkeypatch.setattr(leads, "get_supabase", lambda: db)
    monkeypatch.setattr(blocked_guard, "get_supabase", lambda: db)
    blocked_guard.invalidate()
    sent = AsyncMock(return_value="wamid.1")
    monkeypatch.setattr(leads, "send_whatsapp", sent)
    return leads, sent


@pytest.mark.asyncio
async def test_staff_reply_goes_from_the_number_the_customer_wrote_to(monkeypatch):
    leads, sent = _use(monkeypatch, _db(SECOND))
    await leads.send_human_message(LEAD, leads.HumanMessage(content="hello"), {"tenant_id": T1})
    assert sent.await_args.kwargs["phone_number_id"] == SECOND


@pytest.mark.asyncio
async def test_a_customer_who_never_wrote_in_gets_the_primary(monkeypatch):
    leads, sent = _use(monkeypatch, _db(None))
    await leads.send_human_message(LEAD, leads.HumanMessage(content="hello"), {"tenant_id": T1})
    assert sent.await_args.kwargs["phone_number_id"] is None  # None = the primary number


@pytest.mark.asyncio
async def test_a_removed_number_falls_back_to_the_primary(monkeypatch):
    leads, sent = _use(monkeypatch, _db(SECOND, number_status="archived"))
    await leads.send_human_message(LEAD, leads.HumanMessage(content="hello"), {"tenant_id": T1})
    assert sent.await_args.kwargs["phone_number_id"] is None


@pytest.mark.asyncio
async def test_never_sends_from_another_business_number(monkeypatch):
    leads, sent = _use(monkeypatch, _db(SECOND, number_tenant=T2))
    await leads.send_human_message(LEAD, leads.HumanMessage(content="hello"), {"tenant_id": T1})
    assert sent.await_args.kwargs["phone_number_id"] is None


@pytest.mark.asyncio
async def test_compose_text_to_a_known_customer_goes_from_their_number(monkeypatch):
    leads, sent = _use(monkeypatch, _db(SECOND))
    await leads.compose_new_message(leads.ComposeMessage(phone=PHONE, content="hello"), None, {"tenant_id": T1})
    assert sent.await_args.kwargs["phone_number_id"] == SECOND


@pytest.mark.asyncio
async def test_photo_from_chats_uses_this_business_and_the_customers_number(monkeypatch):
    from io import BytesIO

    from fastapi import UploadFile
    from starlette.datastructures import Headers

    from app.routes import media

    db = _db(SECOND)
    monkeypatch.setattr(media, "get_supabase", lambda: db)
    upload = AsyncMock(return_value="media-1")
    send = AsyncMock(return_value={"messages": [{"id": "wamid.9"}]})
    monkeypatch.setattr(media, "upload_media_to_meta", upload)
    monkeypatch.setattr(media, "send_media_message", send)
    file = UploadFile(file=BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64), filename="a.png", headers=Headers({"content-type": "image/png"}))
    await media.send_media_to_lead(LEAD, file, "", {"tenant_id": T1})
    assert upload.await_args.kwargs["tenant_id"] == T1
    assert upload.await_args.kwargs["phone_number_id"] == SECOND
    assert send.await_args.kwargs["tenant_id"] == T1
    assert send.await_args.kwargs["phone_number_id"] == SECOND
