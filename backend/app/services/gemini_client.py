# backend/app/services/gemini_client.py
import base64
import json

import httpx
import lameenc

from app.config_dynamic import require_tenant_setting
from app.services.token_meter import record_tokens

# Single model for STT, doc-digitization/OCR, and call analysis (operator decision:
# 3.1 Flash-Lite over the stronger-but-costlier 3.5 Flash, see decisions/log.md).
# Distinct from the operator-configurable ai_reply_model -- these three are internal
# pipeline steps, not exposed as a per-tenant choice in the operator console.
DEFAULT_GEMINI_TEXT_MODEL = "gemini-3.1-flash-lite"

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


def _record(tenant_id: str | None, purpose: str, model: str, data: dict) -> None:
    """Interactions responses carry a top-level usage block (live-probed 2026-07-18):
    total_input_tokens / total_output_tokens plus separately-counted thought and
    tool-use tokens, which bill like output and are folded into output here."""
    usage = data.get("usage") or {}
    output_total = (
        (usage.get("total_output_tokens") or 0)
        + (usage.get("total_thought_tokens") or 0)
        + (usage.get("total_tool_use_tokens") or 0)
    ) if usage else None
    record_tokens(tenant_id, purpose, "gemini", model, usage.get("total_input_tokens"), output_total)
# gemini-2.5-flash-preview-tts hard-400'd on every request ("Model tried to generate
# text, but it should only be used for TTS") on 2026-07-17, confirmed dead at Google's
# end at the time (not a request-shape bug -- gemini-3.1-flash-tts-preview accepted the
# identical body and worked). Re-tested later the same day: 2.5 was back to returning
# real audio again, no code change involved -- a preview-model flake on Google's side,
# not a permanent kill. Deliberately reverted to 2.5 anyway (costs ~half of 3.1) after
# an explicit operator call accepting that a preview model can silently break or get
# deprecated again with no warning -- if that happens, swap this constant back to
# "gemini-3.1-flash-tts-preview".
DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_GEMINI_VOICE = "Kore"
_PCM_SAMPLE_RATE = 24000
_PCM_CHANNELS = 1


def _messages_to_gemini_input(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Gemini's /v1beta/interactions endpoint doesn't use OpenAI's messages array --
    system prompt goes in a separate system_instruction field, and conversation turns are
    a list of {type: user_input|model_output, content: [{type: text, text}]} steps. Live-
    tested 2026-07-14: prior-assistant-turn history uses "model_output" (the same type the
    API returns responses as), NOT "model_response" -- that type doesn't exist and 400s."""
    system_parts: list[str] = []
    steps: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            steps.append({"type": "model_output", "content": [{"type": "text", "text": content}]})
        else:
            steps.append({"type": "user_input", "content": [{"type": "text", "text": content}]})
    return ("\n\n".join(system_parts) if system_parts else None), steps


def _openai_tools_to_gemini(tools: list[dict]) -> list[dict]:
    """Gemini's function declarations are flat ({type, name, description, parameters}),
    unlike OpenAI/Sarvam's nested {type: function, function: {name, description, parameters}}."""
    gemini_tools = []
    for t in tools:
        func = t.get("function") or {}
        gemini_tools.append({
            "type": "function",
            "name": func.get("name"),
            "description": func.get("description"),
            "parameters": func.get("parameters"),
        })
    return gemini_tools


def _gemini_output_text(steps: list[dict]) -> str:
    """Extracts and concatenates text from model_output steps. Live-tested 2026-07-14:
    there is no top-level output_text convenience field on this endpoint (despite docs
    implying one) -- responses come back as a steps array that can include a "thought"
    step (reasoning trace, present by default on 3.x models) before the real
    "model_output" step, so thought steps must be skipped, not concatenated in."""
    parts = []
    for step in steps:
        if step.get("type") != "model_output":
            continue
        for c in step.get("content") or []:
            if c.get("type") == "text":
                parts.append(c.get("text") or "")
    return "".join(parts).strip()


def _gemini_steps_to_tool_calls(steps: list[dict]) -> list[dict]:
    """Converts Gemini's function_call steps back into the OpenAI-shaped tool_calls tuple
    the rest of the codebase (generate_reply's catalog handling) already expects."""
    tool_calls = []
    for i, step in enumerate(steps):
        if step.get("type") != "function_call":
            continue
        tool_calls.append({
            "id": step.get("id") or f"call_{i}",
            "type": "function",
            "function": {
                "name": step.get("name"),
                "arguments": json.dumps(step.get("arguments") or {}),
            },
        })
    return tool_calls


async def gemini_chat_completion(
    messages: list[dict],
    model: str,
    temperature: float = 0.4,
    max_tokens: int = 300,
    tenant_id: str | None = None,
    purpose: str = "unknown",
) -> str:
    """Plain chat completion via Gemini's interactions endpoint. No fallback to a platform
    key -- every client must configure their own gemini_api_key (operator decision, see
    decisions/log.md).

    thinking_level="minimal" -- Gemini 3.x models default to "medium" thinking, which on
    gemini-3.5-flash spent most of a 300-token max_output_tokens budget on the hidden
    thought step, live-tested to either time out (30s client timeout) or return a reply
    truncated mid-sentence. gemini-3.1-flash-lite happened to be fast enough not to show
    it, but the same default applies there too."""
    api_key = require_tenant_setting("gemini_api_key", tenant_id)
    system_instruction, input_steps = _messages_to_gemini_input(messages)
    request_json: dict = {
        "model": model,
        "store": False,  # no copy kept at Google: it cost ~3.4s a call and nothing reads it back
        "input": input_steps,
        "generation_config": {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "thinking_level": "minimal",
        },
    }
    if system_instruction:
        request_json["system_instruction"] = system_instruction
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GEMINI_INTERACTIONS_URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=request_json,
        )
        resp.raise_for_status()
        data = resp.json()
    _record(tenant_id, purpose, model, data)
    return _gemini_output_text(data.get("steps") or [])


async def gemini_chat_completion_with_tools(
    messages: list[dict],
    tools: list[dict],
    model: str,
    temperature: float = 0.4,
    max_tokens: int = 300,
    tenant_id: str | None = None,
    purpose: str = "unknown",
) -> tuple[str, list[dict]]:
    api_key = require_tenant_setting("gemini_api_key", tenant_id)
    system_instruction, input_steps = _messages_to_gemini_input(messages)
    request_json: dict = {
        "model": model,
        "store": False,  # no copy kept at Google: it cost ~3.4s a call and nothing reads it back
        "input": input_steps,
        "tools": _openai_tools_to_gemini(tools),
        "generation_config": {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "thinking_level": "minimal",
        },
    }
    if system_instruction:
        request_json["system_instruction"] = system_instruction
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GEMINI_INTERACTIONS_URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=request_json,
        )
        resp.raise_for_status()
        data = resp.json()
    _record(tenant_id, purpose, model, data)
    steps = data.get("steps") or []
    content = _gemini_output_text(steps)
    tool_calls = _gemini_steps_to_tool_calls(steps)
    return content, tool_calls


async def gemini_speech_to_text(
    audio_bytes: bytes,
    mime_type: str,
    model: str = DEFAULT_GEMINI_TEXT_MODEL,
    tenant_id: str | None = None,
    purpose: str = "speech_to_text",
) -> str:
    """Transcribe audio via Gemini's interactions endpoint. Live-tested 2026-07-18: the
    audio content-part shape is NOT the standard Gemini API's nested inline_data
    convention -- it's {"type": "audio", "data": <base64>, "mime_type": ...} as a flat
    sibling to the text part, same pattern confirmed for "image" and "document" types.
    Replaces Sarvam Saaras for both WhatsApp voice notes and call-recording transcripts."""
    api_key = require_tenant_setting("gemini_api_key", tenant_id)
    request_json = {
        "model": model,
        "store": False,  # no copy kept at Google: it cost ~3.4s a call and nothing reads it back
        "input": [{
            "type": "user_input",
            "content": [
                {"type": "text", "text": "Transcribe this audio verbatim. Return only the transcript, no commentary."},
                {"type": "audio", "data": base64.b64encode(audio_bytes).decode(), "mime_type": mime_type},
            ],
        }],
        "generation_config": {
            "temperature": 0.2,
            "max_output_tokens": 4000,
            "thinking_level": "minimal",
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            GEMINI_INTERACTIONS_URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=request_json,
        )
        resp.raise_for_status()
        data = resp.json()
    _record(tenant_id, purpose, model, data)
    return _gemini_output_text(data.get("steps") or [])


_INCOMPLETE_STATUSES = {"incomplete", "max_tokens", "cancelled", "failed"}


def _hit_output_cap(data: dict, max_tokens: int) -> bool:
    """True when a response stopped early. The usage block is the reliable signal
    (live-confirmed 2026-07-18); an explicit non-completed status is honoured too."""
    status = str(data.get("status") or "").lower()
    if status in _INCOMPLETE_STATUSES:
        return True
    output_tokens = (data.get("usage") or {}).get("total_output_tokens") or 0
    return output_tokens >= int(max_tokens * 0.98)


def _audio_part(audio_bytes: bytes, mime_type: str) -> dict:
    return {"type": "audio", "data": base64.b64encode(audio_bytes).decode(), "mime_type": mime_type}


async def gemini_transcribe_audio(
    audio_bytes: bytes,
    mime_type: str,
    prompt: str,
    model: str = DEFAULT_GEMINI_TEXT_MODEL,
    tenant_id: str | None = None,
    max_tokens: int = 24000,
    timeout: float = 180.0,
    purpose: str = "call_transcription",
    temperature: float = 0.1,
) -> tuple[str, bool]:
    """Transcribe one piece of a call recording. Returns (text, complete); complete is
    False when the output cap was hit, so the caller can cut the piece smaller instead
    of scoring half a call. Separate from gemini_speech_to_text, which WhatsApp voice
    notes still use unchanged."""
    api_key = require_tenant_setting("gemini_api_key", tenant_id)
    request_json = {
        "model": model,
        "store": False,  # no copy kept at Google: it cost ~3.4s a call and nothing reads it back
        "input": [{
            "type": "user_input",
            "content": [{"type": "text", "text": prompt}, _audio_part(audio_bytes, mime_type)],
        }],
        "generation_config": {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "thinking_level": "minimal",
        },
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            GEMINI_INTERACTIONS_URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=request_json,
        )
        resp.raise_for_status()
        data = resp.json()
    _record(tenant_id, purpose, model, data)
    text = _gemini_output_text(data.get("steps") or [])
    return text, not _hit_output_cap(data, max_tokens)


async def gemini_analysis_json(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_GEMINI_TEXT_MODEL,
    tenant_id: str | None = None,
    max_tokens: int = 3000,
    timeout: float = 120.0,
    purpose: str = "call_analysis",
    temperature: float = 0.2,
) -> dict:
    """JSON completion with prompt-only JSON discipline and a single retry."""
    api_key = require_tenant_setting("gemini_api_key", tenant_id)
    content: list[dict] = [{"type": "text", "text": user_prompt}]
    request_json = {
        "model": model,
        "store": False,  # no copy kept at Google: it cost ~3.4s a call and nothing reads it back
        "system_instruction": system_prompt,
        "input": [{"type": "user_input", "content": content}],
        "generation_config": {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "thinking_level": "minimal",
        },
    }
    last_error: Exception = ValueError("gemini_analysis_json: no attempts made")
    for _ in range(2):
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                GEMINI_INTERACTIONS_URL,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=request_json,
            )
            resp.raise_for_status()
            data = resp.json()
        _record(tenant_id, purpose, model, data)
        cleaned = _gemini_output_text(data.get("steps") or [])
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_error = e
    raise last_error


def _gemini_document_interaction(
    file_bytes: bytes,
    mime_type: str,
    prompt: str,
    model: str,
    tenant_id: str | None,
    purpose: str,
) -> str:
    """Shared sync request/response plumbing for document+image content-parts via
    Gemini's interactions endpoint. Content-part type is "document" for PDFs, "image"
    for anything else -- live-tested 2026-07-18, same flat {"data": <base64>,
    "mime_type": ...} shape as audio.

    Deliberately synchronous (httpx.Client, not AsyncClient) -- the only callers
    (knowledge_service.extract_text_from_file, upload.py's scan-to-lead route) are
    sync functions dispatched via asyncio.to_thread / already sync, matching the
    execution model the original Sarvam version used."""
    api_key = require_tenant_setting("gemini_api_key", tenant_id)
    content_type = "document" if mime_type == "application/pdf" else "image"
    request_json = {
        "model": model,
        "store": False,  # no copy kept at Google: it cost ~3.4s a call and nothing reads it back
        "input": [{
            "type": "user_input",
            "content": [
                {"type": "text", "text": prompt},
                {"type": content_type, "data": base64.b64encode(file_bytes).decode(), "mime_type": mime_type},
            ],
        }],
        "generation_config": {
            "temperature": 0.2,
            "max_output_tokens": 4000,
            "thinking_level": "minimal",
        },
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            GEMINI_INTERACTIONS_URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=request_json,
        )
        resp.raise_for_status()
        data = resp.json()
    _record(tenant_id, purpose, model, data)
    return _gemini_output_text(data.get("steps") or [])


def gemini_extract_document_text(
    file_bytes: bytes,
    mime_type: str,
    model: str = DEFAULT_GEMINI_TEXT_MODEL,
    tenant_id: str | None = None,
    purpose: str = "doc_digitization",
) -> str:
    """OCR/extraction for scanned PDFs and images, verbatim as markdown. Replaces Sarvam
    Document Digitization's whole create->upload->start->poll->download->unzip job
    lifecycle with one request -- no polling needed. Confirmed with real output (exact
    verbatim OCR text back from a test image)."""
    return _gemini_document_interaction(
        file_bytes,
        mime_type,
        "Extract all text from this document, verbatim, as markdown. Return only the extracted text, no commentary.",
        model,
        tenant_id,
        purpose,
    )


def gemini_extract_contacts_csv(
    file_bytes: bytes,
    mime_type: str,
    model: str = DEFAULT_GEMINI_TEXT_MODEL,
    tenant_id: str | None = None,
    purpose: str = "lead_scan_ocr",
) -> str:
    """OCR a photographed/scanned page of names and phone numbers (e.g. a notebook
    page) directly into CSV rows, for the scan-to-lead upload path. Caller
    (upload.py's /upload/scan) re-validates every phone number with the same
    _normalize_phone used by CSV uploads -- this function's job is just getting the
    handwriting into a parseable shape, not validating it."""
    return _gemini_document_interaction(
        file_bytes,
        mime_type,
        (
            "This image or PDF contains a list of names and/or phone numbers, possibly "
            "handwritten in a notebook. Extract every contact you can find into strict "
            "CSV with exactly two columns, header \"name,phone\". Use an empty string for "
            "name if none is written next to a number. Output only the CSV, no markdown "
            "code fences, no commentary."
        ),
        model,
        tenant_id,
        purpose,
    )


async def gemini_chat_completion_json(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_GEMINI_TEXT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    tenant_id: str | None = None,
    purpose: str = "unknown",
) -> dict:
    """Prompt-based JSON completion. Gemini's interactions endpoint has a formal
    response_format={"type": "object", "schema": ...} mode, but live-tested 2026-07-18:
    it's broken -- the model emits '{' followed by unbounded whitespace and never
    completes, regardless of max_output_tokens (tried up to 800). Falls back to the same
    "return JSON only" prompt discipline gemini_chat_completion already relies on for
    plain text, plus one retry on a parse failure -- unlike Groq's
    response_format={"type": "json_object"}, there's no hard guarantee here. Raises on a
    second failure so callers decide their own fallback rather than silently returning
    something wrong."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error: Exception = ValueError("gemini_chat_completion_json: no attempts made")
    for _ in range(2):
        raw = await gemini_chat_completion(
            messages, model=model, temperature=temperature, max_tokens=max_tokens, tenant_id=tenant_id,
            purpose=purpose,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_error = e
    raise last_error


def _pcm_to_mp3(pcm_bytes: bytes) -> bytes:
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(64)
    encoder.set_in_sample_rate(_PCM_SAMPLE_RATE)
    encoder.set_channels(_PCM_CHANNELS)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm_bytes) + encoder.flush())


async def gemini_text_to_speech(
    text: str,
    voice: str = DEFAULT_GEMINI_VOICE,
    model: str = DEFAULT_GEMINI_TTS_MODEL,
    tenant_id: str | None = None,
    purpose: str = "voice_reply_tts",
) -> bytes:
    """Sarvam Bulbul mispronounced Romanized Tanglish with a non-Tamil accent regardless
    of target_language_code (live-tested 2026-07-13/14, see subsystem-notes.md). Gemini's
    TTS is LLM-native rather than a classic grapheme-to-phoneme pipeline, and handles raw
    Roman-script Tanglish correctly with no code-switch preprocessing -- confirmed via live
    A/B audio testing. Returns MP3 bytes (transcoded from Gemini's raw PCM output via
    lameenc, since the API has no compressed-format response option and WhatsApp's Cloud
    API doesn't accept raw PCM).

    No fallback to a platform key -- every client must configure their own gemini_api_key
    for voice replies, same policy as every other AI provider (operator decision, see
    decisions/log.md)."""
    api_key = require_tenant_setting("gemini_api_key", tenant_id)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            GEMINI_INTERACTIONS_URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "model": model,
                "store": False,  # no copy kept at Google: it cost ~3.4s a call and nothing reads it back
                "input": text,
                "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [{"voice": voice}]},
            },
        )
        resp.raise_for_status()
        data = resp.json()
    _record(tenant_id, purpose, model, data)
    steps = data.get("steps") or []
    content = steps[0].get("content") if steps else None
    if not content:
        raise RuntimeError("Gemini TTS returned no audio")
    pcm_bytes = base64.b64decode(content[0]["data"])
    return _pcm_to_mp3(pcm_bytes)
