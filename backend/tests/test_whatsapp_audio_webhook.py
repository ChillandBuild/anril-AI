import sys
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import webhook


def _db(captured_messages: list[dict]):
    db = MagicMock()

    def table_selector(name):
        table = MagicMock()
        if name == "messages":
            def _insert(row):
                captured_messages.append(row)
                result = MagicMock()
                result.execute.return_value.data = [{"id": "message-1"}]
                return result
            table.insert.side_effect = _insert
        return table

    db.table.side_effect = table_selector
    return db


class _Result:
    def __init__(self, data):
        self.data = data


class _RouteTable:
    def __init__(self, name: str, captured_messages: list[dict]):
        self.name = name
        self.captured_messages = captured_messages
        self.operation = "select"

    def select(self, *_args, **_kwargs):
        self.operation = "select"
        return self

    def insert(self, row):
        self.operation = "insert"
        if self.name == "messages":
            self.captured_messages.append(row)
        return self

    def update(self, *_args, **_kwargs):
        self.operation = "update"
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self.name == "phone_numbers":
            return _Result({"tenant_id": "tenant-1"})
        if self.name == "leads" and self.operation == "select":
            return _Result([{
                "id": "lead-1",
                "score": 5,
                "segment": "C",
                "deleted_at": None,
                "ai_enabled": True,
                "whatsapp_undeliverable": False,
            }])
        if self.name == "leads" and self.operation == "insert":
            return _Result([{"id": "lead-1"}])
        if self.name == "messages" and self.operation == "insert":
            return _Result([{"id": "message-1"}])
        return _Result([])


def _route_db(captured_messages: list[dict]):
    db = MagicMock()
    db.table.side_effect = lambda name: _RouteTable(name, captured_messages)
    return db


@pytest.mark.asyncio
async def test_audio_background_transcribes_inserts_and_routes_reply():
    captured_messages: list[dict] = []
    db = _db(captured_messages)

    with patch("app.db.supabase.get_supabase", return_value=db), \
         patch("app.services.conversation_state.get_or_create_state", return_value={"message_count": 0}), \
         patch.object(webhook, "_transcribe_whatsapp_audio", new=AsyncMock(return_value=("I need a flat near Andheri", "audio/ogg")), create=True) as transcribe, \
         patch("app.services.notify.notify_assigned_caller_of_reply") as notify, \
         patch("app.services.purchases.supplier_by_phone", return_value=None), \
         patch("app.services.context_builder.build_scorer_context", return_value="ctx") as build_ctx, \
         patch("app.services.ai_reply.generate_reply", new=AsyncMock()) as generate_reply, \
         patch("app.routes.webhook.meter") as meter:
        await webhook._process_inbound_message_background(
            lead_id="lead-1",
            tenant_id="tenant-1",
            phone="+919999999999",
            body="",
            msg_type="audio",
            meta_phone_number_id="phone-number-1",
            meta_media_id="media-1",
        )

    transcribe.assert_awaited_once_with("media-1", "tenant-1")
    meter.assert_called_once_with(db, "tenant-1", "ai_speech_to_text")
    assert captured_messages == [{
        "lead_id": "lead-1",
        "direction": "inbound",
        "channel": "whatsapp",
        "content": "I need a flat near Andheri",
        "is_ai_generated": False,
        "meta_message_id": "media-1",
        "tenant_id": "tenant-1",
        "media_url": "meta:media-1",
        "media_type": "audio",
        "media_mime_type": "audio/ogg",
    }]
    notify.assert_called_once_with("lead-1", "tenant-1", db=db)
    build_ctx.assert_called_once_with("lead-1", db)
    generate_reply.assert_awaited_once_with(
        lead_id="lead-1",
        message="I need a flat near Andheri",
        phone="+919999999999",
        context_block="ctx",
        phone_number_id="phone-number-1",
        inbound_media_type="audio",
        # The inbound media id doubles as the message id, so the reply can be
        # sent as a quoted reply to the voice note it answers.
        meta_message_id="media-1",
        # A voice note is not a button tap.
        interactive_id=None,
    )


@pytest.mark.asyncio
async def test_audio_webhook_payload_schedules_transcription_without_blank_insert():
    captured_messages: list[dict] = []
    db = _route_db(captured_messages)
    payload = {
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "phone-number-1"},
                    "messages": [{
                        "id": "wamid.audio.1",
                        "from": "919999999999",
                        "type": "audio",
                        "audio": {"id": "media-1", "mime_type": "audio/ogg"},
                    }],
                },
            }],
        }],
    }
    request = MagicMock(spec=Request)
    request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
    request.headers = {"x-hub-signature-256": "sha256=test"}
    background_tasks = MagicMock(spec=BackgroundTasks)

    with patch("app.routes.webhook.get_supabase", return_value=db), \
         patch("app.routes.webhook.verify_meta_signature", return_value=True):
        response = await webhook.whatsapp_webhook(request, background_tasks)

    assert response == {"status": "ok"}
    assert captured_messages == []
    background_tasks.add_task.assert_called_once()
    task_func = background_tasks.add_task.call_args.args[0]
    task_kwargs = background_tasks.add_task.call_args.kwargs
    assert task_func is webhook._process_inbound_message_background
    assert task_kwargs["lead_id"] == "lead-1"
    assert task_kwargs["tenant_id"] == "tenant-1"
    assert task_kwargs["phone"] == "+919999999999"
    assert task_kwargs["body"] == ""
    assert task_kwargs["msg_type"] == "audio"
    assert task_kwargs["meta_phone_number_id"] == "phone-number-1"
    assert task_kwargs["meta_message_id"] == "wamid.audio.1"
    assert task_kwargs["meta_media_id"] == "media-1"


@pytest.mark.asyncio
async def test_audio_background_empty_transcript_does_not_insert_or_reply():
    captured_messages: list[dict] = []
    db = _db(captured_messages)

    with patch("app.db.supabase.get_supabase", return_value=db), \
         patch.object(webhook, "_transcribe_whatsapp_audio", new=AsyncMock(return_value=("", "audio/ogg")), create=True), \
         patch("app.services.conversation_state.get_or_create_state") as get_state, \
         patch("app.services.context_builder.build_scorer_context") as build_ctx, \
         patch("app.services.ai_reply.generate_reply", new=AsyncMock()) as generate_reply:
        await webhook._process_inbound_message_background(
            lead_id="lead-1",
            tenant_id="tenant-1",
            phone="+919999999999",
            body="",
            msg_type="audio",
            meta_phone_number_id="phone-number-1",
            meta_message_id="wamid.audio.1",
            meta_media_id="media-1",
        )

    assert captured_messages == []
    get_state.assert_not_called()
    build_ctx.assert_not_called()
    generate_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_background_transcription_failure_does_not_insert_or_reply(caplog):
    captured_messages: list[dict] = []
    db = _db(captured_messages)

    with caplog.at_level(logging.ERROR), \
         patch("app.db.supabase.get_supabase", return_value=db), \
         patch.object(webhook, "_transcribe_whatsapp_audio", new=AsyncMock(side_effect=RuntimeError("sarvam down")), create=True), \
         patch("app.services.conversation_state.get_or_create_state") as get_state, \
         patch("app.services.context_builder.build_scorer_context") as build_ctx, \
         patch("app.services.ai_reply.generate_reply", new=AsyncMock()) as generate_reply:
        await webhook._process_inbound_message_background(
            lead_id="lead-1",
            tenant_id="tenant-1",
            phone="+919999999999",
            body="",
            msg_type="audio",
            meta_phone_number_id="phone-number-1",
            meta_message_id="wamid.audio.1",
            meta_media_id="media-1",
        )

    assert captured_messages == []
    get_state.assert_not_called()
    build_ctx.assert_not_called()
    generate_reply.assert_not_awaited()
    assert "Audio transcription failed" in caplog.text
    assert "lead-1" in caplog.text
    assert "media-1" in caplog.text
