"""A template approved with an image/video/document header must carry that header on
every send, or Meta refuses it: "(#132012) Parameter format does not match format in
the created template". Broadcasts used to send only the body, so Kelir's
kelir_host_registration_invitation (image header + {{1}}) failed 148 of 148."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import broadcast_executor
from app.services.template_params import header_components
from tests.test_broadcast_executor_resume import LEAD_A, ROW, FakeDB, _FixedPicker

IMG = "https://example.supabase.co/storage/v1/object/public/template-media/t/invite.png"


def test_image_header_is_sent_by_link():
    t = {"header_media_type": "IMAGE", "header_media_url": IMG}
    assert header_components(t, "Ravi") == [
        {"type": "header", "parameters": [{"type": "image", "image": {"link": IMG}}]}
    ]


def test_video_and_document_headers():
    for kind in ("VIDEO", "DOCUMENT"):
        comp = header_components({"header_media_type": kind, "header_media_url": IMG}, None)
        assert comp[0]["parameters"][0] == {"type": kind.lower(), kind.lower(): {"link": IMG}}


def test_header_text_with_a_variable_gets_the_lead_name():
    t = {"header_text": "Welcome {{1}}"}
    assert header_components(t, "Ravi") == [{"type": "header", "parameters": [{"type": "text", "text": "Ravi"}]}]
    assert header_components(t, None)[0]["parameters"][0]["text"] == "Customer"


def test_plain_header_text_or_no_header_sends_nothing():
    assert header_components({"header_text": "Welcome to Kelir"}, "Ravi") == []
    assert header_components({}, "Ravi") == []
    assert header_components(None, "Ravi") == []


@pytest.mark.asyncio
async def test_scheduled_broadcast_sends_the_template_image():
    templates = {"promo": [{
        "language": "en", "body_text": "Hi {{1}}!", "variations": [], "status": "APPROVED",
        "header_media_type": "IMAGE", "header_media_url": IMG, "header_text": None,
    }]}
    db = FakeDB([LEAD_A], [{"id": "phone-num-1", "meta_phone_number_id": "num-1", "number": "+910000000000"}], templates)
    row = dict(ROW, leads_json=[{"phone": LEAD_A["phone"], "name": "Alice"}])

    with patch("app.services.broadcast_executor.get_supabase", return_value=db), \
         patch("app.services.broadcast_executor.send_template_message", new=AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})) as mock_send, \
         patch("app.services.broadcast_executor.meter"), \
         patch("app.services.broadcast_executor.SenderPicker", _FixedPicker), \
         patch("app.services.broadcast_executor.new_lead_score_and_segment", return_value=(3, "C")):
        await broadcast_executor.execute_broadcast(row)

    components = mock_send.await_args.kwargs["components"]
    assert components == [
        {"type": "header", "parameters": [{"type": "image", "image": {"link": IMG}}]},
        {"type": "body", "parameters": [{"type": "text", "text": "Alice"}]},
    ]
