import base64
import json
import wave
import io

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import gemini_client


def _pcm_wav_bytes(samples: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(samples)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_gemini_text_to_speech_decodes_pcm_and_transcodes_to_mp3():
    pcm_samples = b"\x00\x01" * 100  # 100 frames of silence-ish 16-bit mono PCM
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "steps": [
            {"content": [{"mime_type": "audio/l16", "data": base64.b64encode(pcm_samples).decode("ascii")}]}
        ]
    }
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=resp)

    with patch("app.services.gemini_client.require_tenant_setting", return_value="test-key"), \
         patch("app.services.gemini_client.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value = mock_instance
        audio = await gemini_client.gemini_text_to_speech(text="Vanga sir, order ready ah irukku", tenant_id="tenant-1")

    assert isinstance(audio, bytes)
    assert len(audio) > 0
    # MP3 frame sync (0xFF + top 3 bits of next byte set) or an ID3 tag -- confirms lameenc
    # actually produced MP3, not a raw PCM passthrough
    assert (audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0) or audio[:3] == b"ID3"

    call_args, call_kwargs = mock_instance.post.call_args
    assert call_args[0] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert call_kwargs["headers"] == {"x-goog-api-key": "test-key", "Content-Type": "application/json"}
    assert call_kwargs["json"] == {
        "model": "gemini-2.5-flash-preview-tts",
        "store": False,
        "input": "Vanga sir, order ready ah irukku",
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": "Kore"}]},
    }


@pytest.mark.asyncio
async def test_gemini_text_to_speech_raises_when_no_audio_returned():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"steps": []}
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=resp)

    with patch("app.services.gemini_client.require_tenant_setting", return_value="test-key"), \
         patch("app.services.gemini_client.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value = mock_instance
        with pytest.raises(RuntimeError, match="no audio"):
            await gemini_client.gemini_text_to_speech(text="Hi", tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_gemini_text_to_speech_raises_when_api_key_missing():
    with patch(
        "app.services.gemini_client.require_tenant_setting",
        side_effect=RuntimeError("gemini_api_key not configured for this client"),
    ):
        with pytest.raises(RuntimeError, match="not configured"):
            await gemini_client.gemini_text_to_speech(text="Hi", tenant_id="tenant-1")


def test_messages_to_gemini_input_splits_system_and_converts_roles():
    system, steps = gemini_client._messages_to_gemini_input([
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "bye"},
    ])
    assert system == "You are helpful."
    assert steps == [
        {"type": "user_input", "content": [{"type": "text", "text": "hi"}]},
        {"type": "model_output", "content": [{"type": "text", "text": "hello"}]},
        {"type": "user_input", "content": [{"type": "text", "text": "bye"}]},
    ]


def test_messages_to_gemini_input_no_system_message():
    system, steps = gemini_client._messages_to_gemini_input([{"role": "user", "content": "hi"}])
    assert system is None
    assert steps == [{"type": "user_input", "content": [{"type": "text", "text": "hi"}]}]


def test_openai_tools_to_gemini_flattens_function_wrapper():
    result = gemini_client._openai_tools_to_gemini([{
        "type": "function",
        "function": {"name": "recommend_catalog_item", "description": "desc", "parameters": {"type": "object"}},
    }])
    assert result == [{
        "type": "function", "name": "recommend_catalog_item", "description": "desc", "parameters": {"type": "object"},
    }]


def test_gemini_output_text_skips_thought_steps():
    steps = [
        {"type": "thought", "signature": "abc"},
        {"type": "model_output", "content": [{"type": "text", "text": "Hi there!"}]},
    ]
    assert gemini_client._gemini_output_text(steps) == "Hi there!"


def test_gemini_output_text_empty_when_no_model_output():
    assert gemini_client._gemini_output_text([{"type": "thought", "signature": "abc"}]) == ""


def test_gemini_steps_to_tool_calls_converts_function_call_steps():
    steps = [
        {"type": "thought"},
        {"type": "function_call", "id": "xyz", "name": "recommend_catalog_item", "arguments": {"item_id": "abc-123"}},
    ]
    result = gemini_client._gemini_steps_to_tool_calls(steps)
    assert result == [{
        "id": "xyz", "type": "function",
        "function": {"name": "recommend_catalog_item", "arguments": '{"item_id": "abc-123"}'},
    }]


def test_gemini_steps_to_tool_calls_empty_when_no_function_calls():
    assert gemini_client._gemini_steps_to_tool_calls([{"type": "model_output", "content": []}]) == []


@pytest.mark.asyncio
async def test_gemini_chat_completion_sends_translated_request_and_parses_text():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "Hello!"}]}]}
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=resp)

    with patch("app.services.gemini_client.require_tenant_setting", return_value="test-key"), \
         patch("app.services.gemini_client.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value = mock_instance
        text = await gemini_client.gemini_chat_completion(
            messages=[{"role": "system", "content": "Be nice."}, {"role": "user", "content": "hi"}],
            model="gemini-3.1-flash-lite",
            max_tokens=100,
            tenant_id="tenant-1",
        )

    assert text == "Hello!"
    call_kwargs = mock_instance.post.call_args.kwargs
    assert call_kwargs["json"]["model"] == "gemini-3.1-flash-lite"
    assert call_kwargs["json"]["system_instruction"] == "Be nice."
    assert call_kwargs["json"]["input"] == [{"type": "user_input", "content": [{"type": "text", "text": "hi"}]}]
    assert call_kwargs["json"]["generation_config"] == {"temperature": 0.4, "max_output_tokens": 100, "thinking_level": "minimal"}


@pytest.mark.asyncio
async def test_gemini_chat_completion_raises_when_tenant_key_missing():
    with patch(
        "app.services.gemini_client.require_tenant_setting",
        side_effect=RuntimeError("gemini_api_key not configured for this client"),
    ):
        with pytest.raises(RuntimeError, match="not configured"):
            await gemini_client.gemini_chat_completion(messages=[{"role": "user", "content": "hi"}], model="gemini-3.1-flash-lite", tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_gemini_chat_completion_with_tools_parses_content_and_tool_calls():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "Sure!"}]},
            {"type": "function_call", "id": "call1", "name": "recommend_catalog_item", "arguments": {"item_id": "abc-123"}},
        ]
    }
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=resp)

    with patch("app.services.gemini_client.require_tenant_setting", return_value="test-key"), \
         patch("app.services.gemini_client.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value = mock_instance
        content, tool_calls = await gemini_client.gemini_chat_completion_with_tools(
            messages=[{"role": "user", "content": "show me cakes"}],
            tools=[{"type": "function", "function": {"name": "recommend_catalog_item", "parameters": {}}}],
            model="gemini-3.1-flash-lite",
            tenant_id="tenant-1",
        )

    assert content == "Sure!"
    assert tool_calls == [{
        "id": "call1", "type": "function",
        "function": {"name": "recommend_catalog_item", "arguments": '{"item_id": "abc-123"}'},
    }]
    call_kwargs = mock_instance.post.call_args.kwargs
    assert call_kwargs["json"]["tools"] == [{"type": "function", "name": "recommend_catalog_item", "description": None, "parameters": {}}]


@pytest.mark.asyncio
async def test_gemini_speech_to_text_sends_flat_audio_content_part():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "  Andheri la flat venum  "}]}]}
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=resp)

    with patch("app.services.gemini_client.require_tenant_setting", return_value="test-key"), \
         patch("app.services.gemini_client.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value = mock_instance
        text = await gemini_client.gemini_speech_to_text(b"audio-bytes", "audio/ogg", tenant_id="tenant-1")

    assert text == "Andheri la flat venum"
    call_kwargs = mock_instance.post.call_args.kwargs
    content = call_kwargs["json"]["input"][0]["content"]
    audio_part = next(c for c in content if c["type"] == "audio")
    assert audio_part["mime_type"] == "audio/ogg"
    assert audio_part["data"] == base64.b64encode(b"audio-bytes").decode()


@pytest.mark.asyncio
async def test_gemini_speech_to_text_raises_when_api_key_missing():
    with patch(
        "app.services.gemini_client.require_tenant_setting",
        side_effect=RuntimeError("gemini_api_key not configured for this client"),
    ):
        with pytest.raises(RuntimeError, match="not configured"):
            await gemini_client.gemini_speech_to_text(b"audio-bytes", "audio/ogg", tenant_id="tenant-1")


def test_gemini_extract_document_text_uses_image_type_for_non_pdf():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "INVOICE TOTAL: Rs 4,500"}]}]}
    mock_instance = MagicMock()
    mock_instance.post = MagicMock(return_value=resp)

    with patch("app.services.gemini_client.require_tenant_setting", return_value="test-key"), \
         patch("app.services.gemini_client.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value = mock_instance
        text = gemini_client.gemini_extract_document_text(b"image-bytes", "image/png", tenant_id="tenant-1")

    assert text == "INVOICE TOTAL: Rs 4,500"
    call_kwargs = mock_instance.post.call_args.kwargs
    content = call_kwargs["json"]["input"][0]["content"]
    file_part = next(c for c in content if c["type"] in ("image", "document"))
    assert file_part["type"] == "image"
    assert file_part["mime_type"] == "image/png"


def test_gemini_extract_document_text_uses_document_type_for_pdf():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "blank page"}]}]}
    mock_instance = MagicMock()
    mock_instance.post = MagicMock(return_value=resp)

    with patch("app.services.gemini_client.require_tenant_setting", return_value="test-key"), \
         patch("app.services.gemini_client.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value = mock_instance
        text = gemini_client.gemini_extract_document_text(b"pdf-bytes", "application/pdf", tenant_id="tenant-1")

    assert text == "blank page"
    call_kwargs = mock_instance.post.call_args.kwargs
    content = call_kwargs["json"]["input"][0]["content"]
    file_part = next(c for c in content if c["type"] in ("image", "document"))
    assert file_part["type"] == "document"
    assert file_part["mime_type"] == "application/pdf"


def test_gemini_extract_document_text_raises_when_api_key_missing():
    with patch(
        "app.services.gemini_client.require_tenant_setting",
        side_effect=RuntimeError("gemini_api_key not configured for this client"),
    ):
        with pytest.raises(RuntimeError, match="not configured"):
            gemini_client.gemini_extract_document_text(b"pdf-bytes", "application/pdf", tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_gemini_chat_completion_json_parses_clean_json_first_try():
    with patch.object(gemini_client, "gemini_chat_completion", AsyncMock(return_value='{"sentiment": "positive"}')) as mock_call:
        data = await gemini_client.gemini_chat_completion_json(
            system_prompt="sys", user_prompt="user", tenant_id="tenant-1",
        )

    assert data == {"sentiment": "positive"}
    mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_gemini_chat_completion_json_strips_markdown_code_fence():
    with patch.object(gemini_client, "gemini_chat_completion", AsyncMock(return_value='```json\n{"ok": true}\n```')):
        data = await gemini_client.gemini_chat_completion_json(
            system_prompt="sys", user_prompt="user", tenant_id="tenant-1",
        )

    assert data == {"ok": True}


@pytest.mark.asyncio
async def test_gemini_chat_completion_json_retries_once_then_succeeds():
    mock_call = AsyncMock(side_effect=["not json at all", '{"ok": true}'])
    with patch.object(gemini_client, "gemini_chat_completion", mock_call):
        data = await gemini_client.gemini_chat_completion_json(
            system_prompt="sys", user_prompt="user", tenant_id="tenant-1",
        )

    assert data == {"ok": True}
    assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_gemini_chat_completion_json_raises_after_two_failures():
    mock_call = AsyncMock(side_effect=["not json", "still not json"])
    with patch.object(gemini_client, "gemini_chat_completion", mock_call):
        with pytest.raises(json.JSONDecodeError):
            await gemini_client.gemini_chat_completion_json(
                system_prompt="sys", user_prompt="user", tenant_id="tenant-1",
            )

    assert mock_call.call_count == 2
