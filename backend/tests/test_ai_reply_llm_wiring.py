import pytest
from unittest.mock import AsyncMock, patch

from app.services import ai_reply


import httpx


def _settings(model, has_key=True):
    """Patches the two settings reads _resolve_provider makes: get_setting for the reply
    model (None = the tenant never picked one) and require_tenant_setting for the Gemini key."""
    def _require(key, tenant_id):
        if not has_key:
            raise RuntimeError(f"{key} not configured for this client")
        return "key"
    return (
        patch.object(ai_reply, "get_setting", return_value=model),
        patch.object(ai_reply, "require_tenant_setting", side_effect=_require),
    )


def _google_error(status):
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/interactions")
    return httpx.HTTPStatusError(f"{status}", request=request, response=httpx.Response(status, request=request))


MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
TOOLS = [{"type": "function", "function": {"name": "recommend_catalog_item"}}]


def test_reply_models_are_the_two_gemini_models():
    assert ai_reply.REPLY_MODELS == {
        "google/gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
        "google/gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    }
    assert ai_reply.DEFAULT_REPLY_MODEL in ai_reply.REPLY_MODELS


def test_provider_and_native_model_strips_the_google_prefix():
    assert ai_reply._provider_and_native_model("google/gemini-3.1-flash-lite") == ("gemini", "gemini-3.1-flash-lite")
    assert ai_reply._provider_and_native_model("google/gemini-3.5-flash-lite") == ("gemini", "gemini-3.5-flash-lite")


@pytest.mark.parametrize("model", [
    "sarvam-30b", "openai/gpt-5.4-nano-2026-03-17", "groq/llama-3.3-70b-versatile",
    "google/gemini-3.5-flash", "anthropic/claude-4",
])
def test_provider_and_native_model_raises_for_a_model_off_the_list(model):
    with pytest.raises(RuntimeError, match="Unrecognized reply model"):
        ai_reply._provider_and_native_model(model)


def test_resolve_reply_model_uses_the_default_when_the_tenant_picked_none():
    with patch.object(ai_reply, "get_setting", return_value=None) as mock_get:
        assert ai_reply._resolve_reply_model("tenant-1") == "google/gemini-3.1-flash-lite"
    mock_get.assert_called_once_with("ai_reply_model", tenant_id="tenant-1")


@pytest.mark.parametrize("stale", ["groq/llama-3.3-70b-versatile", "sarvam-30b", "google/gemini-3.5-flash"])
def test_resolve_reply_model_uses_the_default_for_a_pick_since_removed(stale):
    with patch.object(ai_reply, "get_setting", return_value=stale):
        assert ai_reply._resolve_reply_model("tenant-1") == "google/gemini-3.1-flash-lite"


def test_resolve_reply_model_returns_the_tenants_pick():
    with patch.object(ai_reply, "get_setting", return_value="google/gemini-3.5-flash-lite"):
        assert ai_reply._resolve_reply_model("tenant-1") == "google/gemini-3.5-flash-lite"


def test_resolve_provider_raises_when_tenant_key_not_configured():
    get, require = _settings("google/gemini-3.1-flash-lite", has_key=False)
    with get, require as mock_require:
        with pytest.raises(RuntimeError, match="gemini_api_key not configured"):
            ai_reply._resolve_provider("tenant-1")
    mock_require.assert_called_once_with("gemini_api_key", "tenant-1")


def test_available_reply_models_needs_the_gemini_key():
    with patch.object(ai_reply, "get_setting", return_value=None):
        assert ai_reply.available_reply_models("tenant-1") == []
    with patch.object(ai_reply, "get_setting", return_value="key"):
        assert [m["id"] for m in ai_reply.available_reply_models("tenant-1")] == list(ai_reply.REPLY_MODELS)


@pytest.mark.asyncio
async def test_llm_complete_raises_when_the_tenant_has_no_gemini_key():
    get, require = _settings(None, has_key=False)
    with get, require:
        with pytest.raises(RuntimeError, match="gemini_api_key not configured"):
            await ai_reply._llm_complete("write a poem", max_tokens=120, tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_llm_complete_routes_to_gemini_and_strips_prefix():
    get, require = _settings("google/gemini-3.1-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion", AsyncMock(return_value="a poem")) as mock_call:
        text = await ai_reply._llm_complete("write a poem", max_tokens=120, tenant_id="tenant-1")

    assert text == "a poem"
    mock_call.assert_called_once_with(
        messages=[{"role": "user", "content": "write a poem"}],
        model="gemini-3.1-flash-lite",
        temperature=0.4,
        max_tokens=120,
        tenant_id="tenant-1",
        purpose="ai_reply",
    )


@pytest.mark.asyncio
async def test_llm_chat_uses_the_tenants_picked_model():
    get, require = _settings("google/gemini-3.5-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion", AsyncMock(return_value="a reply")) as mock_call:
        text = await ai_reply._llm_chat(MESSAGES, max_tokens=600, tenant_id="tenant-2")

    assert text == "a reply"
    mock_call.assert_called_once_with(
        messages=MESSAGES,
        model="gemini-3.5-flash-lite",
        temperature=0.4,
        max_tokens=600,
        tenant_id="tenant-2",
        purpose="ai_reply",
    )


@pytest.mark.asyncio
async def test_llm_chat_with_tools_routes_to_gemini_and_strips_prefix():
    get, require = _settings("google/gemini-3.1-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion_with_tools", AsyncMock(return_value=("here", []))) as mock_call:
        content, tool_calls = await ai_reply._llm_chat_with_tools(MESSAGES, TOOLS, max_tokens=600, tenant_id="tenant-1")

    assert (content, tool_calls) == ("here", [])
    mock_call.assert_called_once_with(
        messages=MESSAGES, tools=TOOLS, model="gemini-3.1-flash-lite", max_tokens=600, tenant_id="tenant-1",
        purpose="ai_reply",
    )


# --- Gemini-to-Gemini fallback ---------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    _google_error(429), _google_error(500), _google_error(503),
    httpx.ReadTimeout("slow"), httpx.ConnectError("down"),
])
async def test_a_google_side_failure_is_retried_once_on_the_other_model(failure):
    get, require = _settings("google/gemini-3.1-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion", AsyncMock(side_effect=[failure, "a reply"])) as mock_call:
        text = await ai_reply._llm_chat(MESSAGES, tenant_id="tenant-1")

    assert text == "a reply"
    assert [c.kwargs["model"] for c in mock_call.call_args_list] == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
    assert mock_call.call_args_list[1].kwargs["tenant_id"] == "tenant-1"


@pytest.mark.asyncio
async def test_the_fallback_runs_the_other_way_for_a_tenant_on_the_newer_model():
    get, require = _settings("google/gemini-3.5-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion_with_tools",
                      AsyncMock(side_effect=[_google_error(503), ("here", [])])) as mock_call:
        result = await ai_reply._llm_chat_with_tools(MESSAGES, TOOLS, tenant_id="tenant-1")

    assert result == ("here", [])
    assert [c.kwargs["model"] for c in mock_call.call_args_list] == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    assert mock_call.call_args_list[1].kwargs["tools"] == TOOLS


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_a_bad_key_or_bad_request_is_not_retried(status):
    get, require = _settings("google/gemini-3.1-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion", AsyncMock(side_effect=_google_error(status))) as mock_call:
        with pytest.raises(httpx.HTTPStatusError):
            await ai_reply._llm_chat(MESSAGES, tenant_id="tenant-1")
    assert mock_call.call_count == 1


@pytest.mark.asyncio
async def test_when_both_models_fail_the_second_error_is_raised_and_nothing_loops():
    get, require = _settings("google/gemini-3.1-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion",
                      AsyncMock(side_effect=[_google_error(503), _google_error(500)])) as mock_call:
        with pytest.raises(httpx.HTTPStatusError) as raised:
            await ai_reply._llm_chat(MESSAGES, tenant_id="tenant-1")
    assert raised.value.response.status_code == 500
    assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_a_playground_model_pick_never_falls_back():
    """A test chat of one model must not be silently answered by the other."""
    get, require = _settings("google/gemini-3.1-flash-lite")
    with get, require, \
         patch.object(ai_reply, "gemini_chat_completion", AsyncMock(side_effect=_google_error(503))) as mock_call:
        with pytest.raises(httpx.HTTPStatusError):
            await ai_reply._llm_chat(MESSAGES, tenant_id="tenant-1", model="google/gemini-3.5-flash-lite")
    assert [c.kwargs["model"] for c in mock_call.call_args_list] == ["gemini-3.5-flash-lite"]


@pytest.mark.asyncio
async def test_send_whatsapp_voice_reply_uses_gemini_tts_and_meta_audio_upload():
    db = object()
    with patch("app.services.gemini_client.gemini_text_to_speech", AsyncMock(return_value=b"audio-bytes")) as tts, \
         patch("app.services.meta_cloud.upload_media_to_meta", AsyncMock(return_value="media-123")) as upload, \
         patch("app.services.meta_cloud.send_media_message", AsyncMock(return_value={"messages": [{"id": "wamid.voice.1"}]})) as send, \
         patch.object(ai_reply, "meter") as meter:
        mid = await ai_reply.send_whatsapp_voice_reply(
            to_phone="+919999999999",
            message="Hi Prem",
            tenant_id="tenant-1",
            phone_number_id="phone-number-1",
            speaker="Kore",
            db=db,
        )

    assert mid == "wamid.voice.1"
    tts.assert_awaited_once_with(text="Hi Prem", voice="Kore", tenant_id="tenant-1")
    meter.assert_called_once_with(db, "tenant-1", "ai_text_to_speech")
    upload.assert_awaited_once_with(
        file_bytes=b"audio-bytes",
        mime_type="audio/mpeg",
        filename="aira-reply.mp3",
        tenant_id="tenant-1",
        phone_number_id="phone-number-1",
    )
    send.assert_awaited_once_with(
        to_number="+919999999999",
        media_id="media-123",
        wa_type="audio",
        tenant_id="tenant-1",
        phone_number_id="phone-number-1",
    )


@pytest.mark.asyncio
async def test_send_whatsapp_voice_reply_defaults_to_default_gemini_voice_when_no_speaker():
    from app.services.gemini_client import DEFAULT_GEMINI_VOICE
    with patch("app.services.gemini_client.gemini_text_to_speech", AsyncMock(return_value=b"audio-bytes")) as tts, \
         patch("app.services.meta_cloud.upload_media_to_meta", AsyncMock(return_value="media-123")), \
         patch("app.services.meta_cloud.send_media_message", AsyncMock(return_value={"messages": [{"id": "wamid.voice.1"}]})):
        await ai_reply.send_whatsapp_voice_reply(
            to_phone="+919999999999", message="Hi Prem", tenant_id="tenant-1",
        )

    tts.assert_awaited_once_with(text="Hi Prem", voice=DEFAULT_GEMINI_VOICE, tenant_id="tenant-1")


def test_generate_reply_uses_voice_only_for_audio_inbound_whatsapp_dispatch():
    import ast
    import inspect
    source = inspect.getsource(ai_reply.generate_reply)
    signature = inspect.signature(ai_reply.generate_reply)
    assert "inbound_media_type" in signature.parameters
    assert "ai_voice_reply_enabled" in source
    assert "ai_voice_reply_speaker" in source
    assert 'inbound_media_type == "audio"' in source
    assert "send_whatsapp_voice_reply" in source
    # Structural, not textual: the call is reflowed across lines and carries
    # extra keywords, so a literal source match breaks on formatting alone.
    text_sends = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "send_whatsapp"
        and {a.id for a in node.args if isinstance(a, ast.Name)} >= {"_wa_phone", "reply_text"}
    ]
    assert text_sends, "generate_reply no longer sends the text reply via send_whatsapp(_wa_phone, reply_text, ...)"


@pytest.mark.asyncio
async def test_llm_chat_passes_purpose_and_temperature_through():
    """Knowledge auto-sort meters under its own purpose and needs a low temperature;
    reply generation keeps its defaults."""
    with patch.object(ai_reply, "_resolve_provider", return_value=("gemini", "m")), \
         patch.object(ai_reply, "gemini_chat_completion", new=AsyncMock(return_value="ok")) as mock_gemini:
        await ai_reply._llm_chat(
            [{"role": "user", "content": "x"}], max_tokens=9, tenant_id="t",
            purpose="knowledge_sort", temperature=0.1,
        )
        kwargs = mock_gemini.call_args.kwargs
        assert kwargs["purpose"] == "knowledge_sort"
        assert kwargs["temperature"] == 0.1

        await ai_reply._llm_chat([{"role": "user", "content": "x"}], tenant_id="t")
        kwargs = mock_gemini.call_args.kwargs
        assert kwargs["purpose"] == "ai_reply"
        assert kwargs["temperature"] == 0.4
