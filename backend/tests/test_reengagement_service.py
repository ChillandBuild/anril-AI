import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


class _FakePicker:
    """A number is always free to send here -- sender choice is covered in
    test_number_failover.py. Keeps these tests off the live numbers table."""

    def __init__(self, _tenant_id):
        pass

    def next(self, prefer_meta_id=None):
        return {"id": "num-1", "meta_phone_number_id": "pnid-1"}


@pytest.fixture(autouse=True)
def _sender_always_available():
    from app.services import reengagement_service as rs
    rs._NO_SENDER_UNTIL.clear()
    # Templates here are approved; the not-approved case is in test_template_edits.py.
    with patch.object(rs, "SenderPicker", _FakePicker),          patch.object(rs, "template_status", return_value="APPROVED"):
        yield
    rs._NO_SENDER_UNTIL.clear()


def _make_db(captured_logs, template_row=None):
    """Supabase mock that records every reengagement_logs insert into captured_logs.
    template_row is what message_templates returns (none by default)."""
    db = MagicMock()

    def table_selector(name):
        t = MagicMock()
        if name == "message_templates":
            q = t.select.return_value
            q.eq.return_value = q
            q.limit.return_value = q
            q.execute.return_value.data = [template_row] if template_row else []
        elif name == "reengagement_logs":
            def _insert(row):
                captured_logs.append(row)
                res = MagicMock()
                res.execute.return_value.data = [{"id": "log-1"}]
                return res
            t.insert.side_effect = _insert
        elif name == "messages":
            t.insert.return_value.execute.return_value.data = [{"id": "msg-1"}]
        else:
            t.insert.return_value.execute.return_value.data = [{"id": "x"}]
        return t

    db.table.side_effect = table_selector
    return db


def _now_iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _step(message_type="freeform", fallback=None):
    return {
        "id": "step-1",
        "message_type": message_type,
        "message_content": "Hi there!",
        "template_name": "promo_v1",
        "template_variables": ["name"],
        "fallback_template_name": fallback,
        "fallback_template_variables": ["name"] if fallback else None,
    }


def _lead(hours_since_reply: float, source=None):
    return {
        "id": "lead-1",
        "name": "Asha",
        "phone": "919999999999",
        "last_inbound_at": _now_iso(hours_since_reply),
        "source": source,
        "extra_cols": {},
    }


@pytest.mark.asyncio
async def test_freeform_window_open_sends_freeform():
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs)
    with patch.object(svc, "send_whatsapp", new=AsyncMock(return_value="sid-1")) as wa, \
         patch.object(svc, "send_template_message", new=AsyncMock()) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(2), _step())
    assert ok is True
    wa.assert_awaited_once()
    tpl.assert_not_awaited()
    assert logs[-1]["status"] == "sent"
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_freeform_window_closed_with_fallback_sends_template():
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs)
    with patch.object(svc, "send_whatsapp", new=AsyncMock()) as wa, \
         patch.object(svc, "send_template_message",
                      new=AsyncMock(return_value={"messages": [{"id": "sid-2"}]})) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(30), _step(fallback="winback_v1"))
    assert ok is True
    wa.assert_not_awaited()
    tpl.assert_awaited_once()
    assert tpl.await_args.kwargs["template_name"] == "winback_v1"
    assert logs[-1]["status"] == "sent_fallback"
    assert len(logs) == 1
    components = tpl.await_args.kwargs["components"]
    assert components == [{"type": "body", "parameters": [{"type": "text", "text": "Asha"}]}]


@pytest.mark.asyncio
async def test_freeform_window_closed_fallback_send_fails_logs_failed():
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs)
    with patch.object(svc, "send_whatsapp", new=AsyncMock()) as wa, \
         patch.object(svc, "send_template_message",
                      new=AsyncMock(side_effect=RuntimeError("Meta API down"))) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(30), _step(fallback="winback_v1"))
    assert ok is False
    wa.assert_not_awaited()
    tpl.assert_awaited_once()
    assert logs[-1]["status"] == "failed"
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_freeform_window_closed_no_fallback_skips():
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs)
    with patch.object(svc, "send_whatsapp", new=AsyncMock()) as wa, \
         patch.object(svc, "send_template_message", new=AsyncMock()) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(30), _step(fallback=None))
    assert ok is False
    wa.assert_not_awaited()
    tpl.assert_not_awaited()
    assert logs[-1]["status"] == "skipped_window"
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_undeliverable_lead_is_skipped_no_send_no_log():
    """A lead Meta can't deliver to (whatsapp_undeliverable) must never be re-engaged
    and must not appear in re-engagement history."""
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs)
    lead = _lead(2)  # window wide open — would normally send freeform
    lead["whatsapp_undeliverable"] = True
    with patch.object(svc, "send_whatsapp", new=AsyncMock()) as wa, \
         patch.object(svc, "send_template_message", new=AsyncMock()) as tpl:
        ok = await svc._send_reengagement(db, "t1", lead, _step())
    assert ok is False
    wa.assert_not_awaited()
    tpl.assert_not_awaited()
    assert len(logs) == 0


@pytest.mark.asyncio
async def test_opted_out_lead_is_skipped_no_send_no_log():
    """A lead who has opted out must never be re-engaged and must not appear
    in re-engagement history."""
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs)
    lead = _lead(2)  # window wide open — would normally send freeform
    lead["opted_out"] = True
    with patch.object(svc, "send_whatsapp", new=AsyncMock()) as wa, \
         patch.object(svc, "send_template_message", new=AsyncMock()) as tpl:
        ok = await svc._send_reengagement(db, "t1", lead, _step())
    assert ok is False
    wa.assert_not_awaited()
    tpl.assert_not_awaited()
    assert len(logs) == 0


@pytest.mark.asyncio
async def test_ai_auto_reply_disabled_skips_reengagement_no_send_no_log():
    """ai_auto_reply_enabled is the single master switch for every automated AI-authored
    outbound message, not just inbound replies -- when a tenant has it off, re-engagement
    must not fire either, and (matching the opted_out/undeliverable skips) no log row is
    written so the lead+step resumes automatically once re-enabled."""
    from app.services import reengagement_service as svc
    from app.services import automation_guards as guards
    logs = []
    db = _make_db(logs)
    lead = _lead(2)  # window wide open — would normally send freeform
    # The master-switch read lives in automation_guards, shared with silence_nudge.
    with patch.object(guards, "get_setting", return_value="false") as get_setting, \
         patch.object(svc, "send_whatsapp", new=AsyncMock()) as wa, \
         patch.object(svc, "send_template_message", new=AsyncMock()) as tpl:
        ok = await svc._send_reengagement(db, "t1", lead, _step())
    assert ok is False
    wa.assert_not_awaited()
    tpl.assert_not_awaited()
    assert len(logs) == 0
    get_setting.assert_called_once_with("ai_auto_reply_enabled", fallback="true", tenant_id="t1")


@pytest.mark.asyncio
async def test_template_step_always_sends_template():
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs)
    with patch.object(svc, "send_whatsapp", new=AsyncMock()) as wa, \
         patch.object(svc, "send_template_message",
                      new=AsyncMock(return_value={"messages": [{"id": "sid-3"}]})) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(30), _step(message_type="template"))
    assert ok is True
    wa.assert_not_awaited()
    tpl.assert_awaited_once()
    assert tpl.await_args.kwargs["template_name"] == "promo_v1"
    assert logs[-1]["status"] == "sent"
    assert len(logs) == 1
    components = tpl.await_args.kwargs["components"]
    assert components == [{"type": "body", "parameters": [{"type": "text", "text": "Asha"}]}]


@pytest.mark.asyncio
async def test_template_with_image_header_sends_the_image():
    """Regression: an approved template with an IMAGE header was sent with no
    header component, so Meta refused every send (#132012 "expected IMAGE,
    received UNKNOWN") and 146 re-engagements in a row were logged failed."""
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs, template_row={
        "header_media_type": "IMAGE",
        "header_media_url": "https://example.com/promo.jpg",
        "header_text": None,
    })
    with patch.object(svc, "send_template_message",
                      new=AsyncMock(return_value={"messages": [{"id": "sid-9"}]})) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(30), _step(message_type="template"))
    assert ok is True
    assert tpl.await_args.kwargs["components"] == [
        {"type": "header", "parameters": [{"type": "image", "image": {"link": "https://example.com/promo.jpg"}}]},
        {"type": "body", "parameters": [{"type": "text", "text": "Asha"}]},
    ]
    assert logs[-1]["status"] == "sent"


@pytest.mark.asyncio
async def test_template_with_text_header_variable_fills_it_with_the_name():
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs, template_row={"header_media_type": None, "header_media_url": None, "header_text": "Hi {{1}}"})
    with patch.object(svc, "send_template_message",
                      new=AsyncMock(return_value={"messages": [{"id": "sid-10"}]})) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(30), _step(message_type="template"))
    assert ok is True
    assert tpl.await_args.kwargs["components"][0] == {"type": "header", "parameters": [{"type": "text", "text": "Asha"}]}


@pytest.mark.asyncio
async def test_image_header_with_no_saved_link_fails_without_calling_meta():
    from app.services import reengagement_service as svc
    logs = []
    db = _make_db(logs, template_row={"header_media_type": "IMAGE", "header_media_url": None, "header_text": None})
    with patch.object(svc, "send_template_message", new=AsyncMock()) as tpl:
        ok = await svc._send_reengagement(db, "t1", _lead(30), _step(message_type="template"))
    assert ok is False
    tpl.assert_not_awaited()
    assert logs[-1]["status"] == "failed"
