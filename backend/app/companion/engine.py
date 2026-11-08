"""reply(): one companion turn, end to end. The public entry point other modules call.

Flow (spec §3.7): load the character → take a load slot → person + conversation →
knowledge, memory and history in parallel → build the prompt → LLM → read the mood tag →
save the reply and mood → return it.

Logs carry ids, timings and error types only, never message text.
"""
import asyncio
import logging
import os
import time
import weakref

from app.companion import store
from app.companion.memory import provider_for
from app.companion.models import AppTool, CompanionReply
from app.companion.prompt import build_messages, parse_mood
from app.services import ai_reply
from app.services.knowledge_service import get_knowledge_context

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10
LLM_MAX_TOKENS = 700
LLM_TEMPERATURE = 0.5
LLM_PURPOSE = "companion_reply"
SLOT_WAIT_SECONDS = 5.0

FALLBACK_LINES = {
    "ta-en": "Mannikkavum, ippo konjam technical problem irukku. Konja neram kazhichu thirumba kelunga.",
    "ta": "மன்னிக்கவும், இப்போது ஒரு சிறிய தொழில்நுட்பச் சிக்கல். சிறிது நேரம் கழித்து மீண்டும் கேளுங்கள்.",
    "en": "Sorry, I'm having a small technical problem right now. Please ask me again in a little while.",
}


class CompanionError(Exception):
    """Base for the errors reply() raises on purpose."""


class CompanionNotFound(CompanionError):
    pass


class CompanionPaused(CompanionError):
    pass


class CompanionBusy(CompanionError):
    """Every load slot stayed taken for SLOT_WAIT_SECONDS. Callers answer 503 'try again'."""


class CompanionMisconfigured(CompanionError):
    """The tenant hasn't set an AI model or its API key."""


# One semaphore per event loop (tests run many loops; production runs one).
_SLOTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _max_concurrent() -> int:
    try:
        return max(1, int(os.getenv("COMPANION_MAX_CONCURRENT", "4")))
    except ValueError:
        return 4


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _SLOTS.get(loop)
    if sem is None:
        sem = _SLOTS[loop] = asyncio.Semaphore(_max_concurrent())
    return sem


def fallback_line(language: str | None) -> str:
    return FALLBACK_LINES.get(language or "", FALLBACK_LINES["en"])


async def reply(
    companion_id: str, tenant_id: str, external_user_id: str, message: str,
    *, display_name: str | None = None, tools: list[AppTool] | None = None,
) -> CompanionReply:
    if tools:
        raise NotImplementedError("app-run tools arrive in companion-core T6")
    companion = await store.get_companion(tenant_id, companion_id)
    if not companion:
        raise CompanionNotFound(companion_id)
    if companion.get("status") == "paused":
        raise CompanionPaused(companion_id)
    try:
        await asyncio.to_thread(ai_reply._resolve_provider, tenant_id)
    except RuntimeError as exc:
        raise CompanionMisconfigured(str(exc)) from exc

    sem = _slots()
    try:
        await asyncio.wait_for(sem.acquire(), SLOT_WAIT_SECONDS)
    except TimeoutError as exc:
        logger.warning("companion %s: busy, no load slot within %ss", companion_id, SLOT_WAIT_SECONDS)
        raise CompanionBusy(companion_id) from exc
    try:
        return await _reply(companion, tenant_id, external_user_id, message, display_name)
    finally:
        sem.release()


async def _knowledge(tenant_id: str, message: str, tag_id: str | None) -> str:
    try:
        return await get_knowledge_context(tenant_id, message, campaign_tag_id=tag_id) or ""
    except Exception as exc:
        logger.warning("companion: knowledge lookup failed for tenant %s (%s)", tenant_id, type(exc).__name__)
        return ""


async def _memory(provider, companion_id: str, end_user_id: str, message: str) -> str:
    try:
        return await provider.context_for(companion_id, end_user_id, message) or ""
    except Exception as exc:
        logger.warning("companion %s: memory lookup failed (%s)", companion_id, type(exc).__name__)
        return ""


async def _reply(companion: dict, tenant_id: str, external_user_id: str, message: str,
                 display_name: str | None) -> CompanionReply:
    started = time.monotonic()
    companion_id = companion["id"]
    person = await store.find_or_create_end_user(tenant_id, external_user_id, display_name)
    conversation = await store.open_conversation(
        tenant_id, companion_id, person["id"], companion.get("default_mood") or "calm")
    provider = provider_for(companion.get("memory_level") or 1)

    # History is read before this message is saved, so the prompt doesn't carry it twice.
    kb_context, memory_context, history = await asyncio.gather(
        _knowledge(tenant_id, message, companion.get("knowledge_tag_id")),
        _memory(provider, companion_id, person["id"], message),
        store.recent_messages(tenant_id, companion_id, person["id"], limit=HISTORY_LIMIT),
    )
    await store.save_message(tenant_id, conversation, "user", message)

    previous_mood = conversation.get("mood") or companion.get("default_mood") or "calm"
    messages = build_messages(companion, previous_mood, kb_context, memory_context, history, message)
    prep_ms = int((time.monotonic() - started) * 1000)

    llm_started = time.monotonic()
    raw = None
    try:
        raw = await ai_reply._llm_chat(
            messages, max_tokens=LLM_MAX_TOKENS, tenant_id=tenant_id,
            purpose=LLM_PURPOSE, temperature=LLM_TEMPERATURE,
        )
    except Exception as exc:
        logger.warning("companion %s: LLM call failed (%s)", companion_id, type(exc).__name__)
    llm_ms = int((time.monotonic() - llm_started) * 1000)

    text, mood = parse_mood(raw or "", previous_mood)
    text = text.strip()
    if not text:
        text, mood = fallback_line(companion.get("language")), previous_mood

    save_started = time.monotonic()
    saved = await store.save_message(tenant_id, conversation, "assistant", text, mood=mood)
    if mood != conversation.get("mood"):
        await store.set_conversation_mood(tenant_id, conversation["id"], mood)
    try:
        await provider.record_turn(companion_id, person["id"], message, text)
    except Exception as exc:
        logger.warning("companion %s: memory record failed (%s)", companion_id, type(exc).__name__)
    save_ms = int((time.monotonic() - save_started) * 1000)

    logger.info("companion %s: reply done (prep %dms, llm %dms, save %dms)", companion_id, prep_ms, llm_ms, save_ms)
    return CompanionReply(
        status="done", text=text, mood=mood, conversation_id=conversation["id"], message_id=saved["id"],
    )
