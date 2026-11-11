"""reply(): one companion turn, end to end. The public entry point other modules call.

Flow: load the character → take a load slot → person + conversation →
history → book search (kb.search over the character's collection) and memory in parallel →
build the prompt → LLM → read the mood tag and the [used: n] tag → label the reply
(primary / book / own / chat, decided by code) → save the reply, mood and label → return it.

App-run tools: if the LLM asks for one of the app's tools, the turn is saved as a
pending turn and reply() returns status "tool_call". The app runs the tool and calls
continue_reply(turn_id, results); the load slot is free while it does. At most 3 LLM rounds:
round 3 goes without tools, so the AI has to answer.

Logs carry ids, timings and error types only, never message text.
"""
import asyncio
import logging
import os
import time
import weakref

from app.companion import memory_refresh, store, tools as app_tools
from app.companion.memory import forget_providers, provider_for
from app.companion.models import AppTool, CompanionReply, ToolResult
from app.companion.kb import learning as kb_learning
from app.companion.kb import search as kb_search
from app.companion.kb.types import KbResult
from app.companion.prompt import build_messages, label_reply, parse_mood, parse_used
from app.services import ai_reply

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10   # default when a character has no history_messages set
LLM_MAX_TOKENS = 700
LLM_TEMPERATURE = 0.5
LLM_PURPOSE = "companion_reply"
SLOT_WAIT_SECONDS = 5.0
MAX_ROUNDS = 3

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


class CompanionNotLive(CompanionError):
    """A draft character, reached through the public chat API. Only live characters talk to end users;
    the owner tests drafts with the dashboard's test chat."""


class CompanionBusy(CompanionError):
    """Every load slot stayed taken for SLOT_WAIT_SECONDS. Callers answer 503 'try again'."""


class CompanionMisconfigured(CompanionError):
    """The tenant hasn't set an AI model or its API key."""


class TurnExpired(CompanionError):
    """Unknown, expired, already-continued or another tenant's turn_id."""


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


def _model_kw(model: str | None) -> dict:
    """The model keyword for ai_reply, only when the Playground picked one. Live replies send none."""
    return {"model": model} if model else {}


async def _live_companion(tenant_id: str, companion_id: str, require_live: bool = False,
                          model: str | None = None) -> tuple[dict, str]:
    """The character, checked usable, plus the LLM provider name (the tenant's, or the
    Playground's picked model's)."""
    companion = await store.get_companion(tenant_id, companion_id)
    if not companion:
        raise CompanionNotFound(companion_id)
    if companion.get("status") == "paused":
        raise CompanionPaused(companion_id)
    if require_live and companion.get("status") != "live":
        raise CompanionNotLive(companion_id)
    try:
        provider, _ = await asyncio.to_thread(ai_reply._provider_for, tenant_id, model)
    except RuntimeError as exc:
        raise CompanionMisconfigured(str(exc)) from exc
    return companion, provider


async def _take_slot(companion_id: str) -> asyncio.Semaphore:
    sem = _slots()
    try:
        await asyncio.wait_for(sem.acquire(), SLOT_WAIT_SECONDS)
    except TimeoutError as exc:
        logger.warning("companion %s: busy, no load slot within %ss", companion_id, SLOT_WAIT_SECONDS)
        raise CompanionBusy(companion_id) from exc
    return sem


async def reply(
    companion_id: str, tenant_id: str, external_user_id: str, message: str,
    *, display_name: str | None = None, tools: list[AppTool] | None = None, require_live: bool = False,
    model: str | None = None, use_memory: bool = True, timezone_name: str | None = None,
) -> CompanionReply:
    """model and use_memory are for the dashboard Playground only; the public API never sets them.
    use_memory=False is the "Compare" reply: no remembered facts, no chat history, no tools,
    nothing saved. It shows how the character answers a stranger.
    timezone_name: the person's IANA zone from their app (validated by the API), saved on the person."""
    tools = tools or []
    app_tools.validate_tools(tools)
    companion, provider = await _live_companion(tenant_id, companion_id, require_live, model)
    sem = await _take_slot(companion_id)
    try:
        if not use_memory:
            return await _reply_without_memory(companion, tenant_id, message, model)
        return await _reply(companion, provider, tenant_id, external_user_id, message, display_name, tools,
                            model, timezone_name)
    finally:
        sem.release()


async def continue_reply(turn_id: str, tenant_id: str, results: list[ToolResult], *,
                         external_user_id: str | None = None, require_live: bool = False) -> CompanionReply:
    """Finishes a turn paused for app-run tools. The turn is consumed: a turn_id works once.
    The load slot is taken first, so a busy moment doesn't use up the turn.
    external_user_id (public API): the turn must belong to this person, else TurnExpired."""
    sem = await _take_slot(f"turn {turn_id}")
    try:
        turn = await store.take_pending_turn(tenant_id, turn_id)
        if not turn:
            raise TurnExpired(turn_id)
        state = turn["messages"]
        model = state.get("model")   # set only by a Playground turn (owner-test person)
        companion, provider = await _live_companion(tenant_id, turn["companion_id"], require_live, model)
        conversation = await store.get_conversation(tenant_id, turn["conversation_id"])
        if not conversation:
            raise TurnExpired(turn_id)
        if external_user_id is not None:
            person = await store.find_end_user(tenant_id, external_user_id)
            if not person or person["id"] != conversation.get("end_user_id"):
                raise TurnExpired(turn_id)
        tools = [AppTool(**t) for t in turn.get("tools") or []]
        extra, log = app_tools.round_messages(
            provider, state.get("assistant_text") or "", state["calls"], results, {t.name for t in tools})
        return await _run_rounds(
            companion, provider, tenant_id, conversation, state["user_message"],
            state["prompt"] + extra, tools, int(turn["round"]) + 1, state.get("tool_log", []) + log,
            time.monotonic(), model=model, kb=KbResult.from_json(state.get("kb")),
        )
    finally:
        sem.release()


async def _knowledge(tenant_id: str, companion: dict, message: str, history: list[dict]) -> KbResult | None:
    """The passages this character's collection holds for the message. None: the character has no
    collection, so nothing is searched and the reply carries no label. A search that breaks never
    breaks the reply: it comes back as "nothing found"."""
    collection_id = companion.get("knowledge_collection_id")
    if not collection_id:
        return None
    try:
        return await kb_search.search(tenant_id, collection_id, message, history, companion_id=companion["id"])
    except Exception as exc:
        logger.warning("companion %s: knowledge search failed (%s)", companion["id"], type(exc).__name__)
        return KbResult(failed=True)


async def _memory(provider, tenant_id: str, companion: dict, person: dict, message: str) -> str:
    companion_id = companion["id"]
    try:
        return await provider.context_for(tenant_id, companion_id, person["id"], message,
                                          companion=companion, person=person) or ""
    except Exception as exc:
        logger.warning("companion %s: memory lookup failed (%s)", companion_id, type(exc).__name__)
        return ""


async def _reply_without_memory(companion: dict, tenant_id: str, message: str,
                                model: str | None) -> CompanionReply:
    """One stateless reply: books only, no facts, no history, and no DB write at all (no person,
    no conversation), so it can run beside the normal reply without racing it."""
    started = time.monotonic()
    kb = await _knowledge(tenant_id, companion, message, [])
    mood = companion.get("default_mood") or "calm"
    prompt = build_messages(companion, mood, kb, "", [], message)
    raw = None
    try:
        raw = await ai_reply._llm_chat(prompt, max_tokens=LLM_MAX_TOKENS, tenant_id=tenant_id,
                                       purpose=LLM_PURPOSE, temperature=LLM_TEMPERATURE, **_model_kw(model))
    except Exception as exc:
        logger.warning("companion %s: LLM call failed without memory (%s)", companion["id"], type(exc).__name__)
    text, new_mood, basis, sources = _read_reply(raw, mood, kb, companion)
    logger.info("companion %s: reply without memory done (total %dms)", companion["id"],
                int((time.monotonic() - started) * 1000))
    return CompanionReply(status="done", text=text, mood=new_mood, basis=_shown_basis(basis, companion),
                          sources=sources)


async def _reply(companion: dict, provider: str, tenant_id: str, external_user_id: str, message: str,
                 display_name: str | None, tools: list[AppTool], model: str | None = None,
                 timezone_name: str | None = None) -> CompanionReply:
    started = time.monotonic()
    companion_id = companion["id"]
    person = await store.find_or_create_end_user(tenant_id, external_user_id, display_name, timezone_name)
    conversation = await store.open_conversation(
        tenant_id, companion_id, person["id"], companion.get("default_mood") or "calm")
    memory = _provider(companion)

    # History is read before this message is saved, so the prompt doesn't carry it twice. It is read
    # first because the book search needs it: "and what about Rahu?" only makes sense with the turn before.
    history = await store.recent_messages(tenant_id, companion_id, person["id"],
                                          limit=companion.get("history_messages") or HISTORY_LIMIT)
    kb, memory_context = await asyncio.gather(
        _knowledge(tenant_id, companion, message, history),
        _memory(memory, tenant_id, companion, person, message),
    )
    await store.save_message(tenant_id, conversation, "user", message)

    mood = _mood(conversation, companion)
    prompt = build_messages(companion, mood, kb, memory_context, history, message)
    logger.info("companion %s: prompt ready (prep %dms)", companion_id, int((time.monotonic() - started) * 1000))
    return await _run_rounds(companion, provider, tenant_id, conversation, message, prompt, tools, 1, [], started,
                             model=model, kb=kb)


def _provider(companion: dict):
    return provider_for(companion.get("memory_level") or 1, companion.get("memory_engine") or "card")


def _mood(conversation: dict, companion: dict) -> str:
    return conversation.get("mood") or companion.get("default_mood") or "calm"


async def _run_rounds(companion: dict, provider: str, tenant_id: str, conversation: dict, user_message: str,
                      prompt: list[dict], tools: list[AppTool], round_no: int, tool_log: list[dict],
                      started: float, *, model: str | None = None, kb: KbResult | None = None) -> CompanionReply:
    """One LLM round. Either pauses for app tools (status tool_call) or finishes the reply.
    kb: the passages in the prompt. It rides along (and into a paused turn's state) so the finished
    reply can be checked against what was really supplied."""
    companion_id = companion["id"]
    use_tools = bool(tools) and round_no < MAX_ROUNDS
    llm_started = time.monotonic()
    raw, calls = None, []
    try:
        if use_tools:
            raw, raw_calls = await ai_reply._llm_chat_with_tools(
                prompt, app_tools.to_llm_tools(tools), max_tokens=LLM_MAX_TOKENS,
                tenant_id=tenant_id, purpose=LLM_PURPOSE, **_model_kw(model),
            )
            calls = app_tools.normalize_calls(raw_calls)
        else:
            raw = await ai_reply._llm_chat(
                prompt, max_tokens=LLM_MAX_TOKENS, tenant_id=tenant_id,
                purpose=LLM_PURPOSE, temperature=LLM_TEMPERATURE, **_model_kw(model),
            )
    except Exception as exc:
        logger.warning("companion %s: LLM call failed on round %d (%s)", companion_id, round_no, type(exc).__name__)
    llm_ms = int((time.monotonic() - llm_started) * 1000)

    known = {t.name for t in tools}
    if calls and not any(c["name"] in known for c in calls):
        # The AI asked only for tools the app never sent: answer "tool unavailable" ourselves
        # and go straight to the next round instead of handing the app nothing to run.
        extra, log = app_tools.round_messages(provider, raw or "", calls, [], known)
        return await _run_rounds(companion, provider, tenant_id, conversation, user_message,
                                 prompt + extra, tools, round_no + 1, tool_log + log, started, model=model, kb=kb)
    if calls:
        state = {"prompt": prompt, "calls": calls, "assistant_text": raw or "",
                 "user_message": user_message, "tool_log": tool_log}
        if model:
            state["model"] = model
        if kb is not None:
            state["kb"] = kb.to_json()
        turn_id = await store.create_pending_turn(
            tenant_id, companion_id, conversation["id"], state, [t.model_dump() for t in tools], round_no)
        logger.info("companion %s: paused for %d tool call(s) on round %d (llm %dms)",
                    companion_id, len(calls), round_no, llm_ms)
        return CompanionReply(
            status="tool_call", turn_id=turn_id, conversation_id=conversation["id"],
            tool_calls=[c for c in calls if c["name"] in known],
        )
    return await _finish(companion, tenant_id, conversation, user_message, raw, tool_log, started, llm_ms, kb)


def _read_reply(raw: str | None, previous_mood: str, kb: KbResult | None,
                companion: dict) -> tuple[str, str, str | None, list[dict]]:
    """'[mood: calm] [used: 1] Sani 7th house la…' -> (text, mood, basis, sources), both tags removed.
    The label is decided by code from the passages really supplied. An empty reply becomes the
    fallback line with no label: it came from no book and from no reasoning.
    [used: ...] is taken out first, so the mood tag is found even when the model wrote it second."""
    text, used = parse_used(raw or "", len(kb.passages) if kb else 0)
    text, mood = parse_mood(text, previous_mood)
    text = text.strip()
    if not text:
        return fallback_line(companion.get("language")), previous_mood, None, []
    basis, sources = label_reply(kb, used)
    return text, mood, basis, sources


def _shown_basis(basis: str | None, companion: dict) -> str | None:
    """The label the person sees. A documents-only character (own_reasoning off) that found nothing
    says "my material does not cover this"; showing "own reading" on that would be wrong. The
    question log still gets "own", so the owner's missing-answers list keeps counting it."""
    return None if basis == "own" and companion.get("own_reasoning") is False else basis


async def _finish(companion: dict, tenant_id: str, conversation: dict, user_message: str, raw: str | None,
                  tool_log: list[dict], started: float, llm_ms: int, kb: KbResult | None = None) -> CompanionReply:
    companion_id = companion["id"]
    text, mood, basis, sources = _read_reply(raw, _mood(conversation, companion), kb, companion)

    shown = _shown_basis(basis, companion)
    saved = await store.save_message(tenant_id, conversation, "assistant", text, mood=mood,
                                     tool_calls=tool_log or None, basis=shown, sources=sources)
    if mood != conversation.get("mood"):
        await store.set_conversation_mood(tenant_id, conversation["id"], mood)
    try:
        await _provider(companion).record_turn(
            tenant_id, companion_id, conversation["end_user_id"], user_message, text)
    except Exception as exc:
        logger.warning("companion %s: memory record failed (%s)", companion_id, type(exc).__name__)
    try:
        memory_refresh.schedule(companion, conversation["end_user_id"], user_message)  # background; Level 2 only
    except Exception as exc:
        logger.warning("companion %s: memory refresh not scheduled (%s)", companion_id, type(exc).__name__)

    if kb is not None and basis:
        # Background, never raises: the question log keeps only the topic, never the person or the message.
        kb_learning.schedule_log(tenant_id, companion_id, kb, basis, sources)

    logger.info("companion %s: reply done (llm %dms, total %dms, basis %s)", companion_id, llm_ms,
                int((time.monotonic() - started) * 1000), basis)
    return CompanionReply(
        status="done", text=text, mood=mood, conversation_id=conversation["id"], message_id=saved["id"],
        basis=shown, sources=[{k: s[k] for k in ("document", "page_from", "page_to")} for s in sources],
    )


async def forget_person(tenant_id: str, external_user_id: str) -> bool:
    """'Forget me', business-wide: wipes this person's chats with every character of the tenant,
    then wipes their facts in every memory engine. False if the person never talked to this tenant."""
    person = await store.find_end_user(tenant_id, external_user_id)
    if not person:
        return False
    await store.forget_end_user(tenant_id, person["id"])
    for provider in forget_providers():
        await provider.forget(tenant_id, person["id"])
    logger.info("companion: forgot end user %s for tenant %s", person["id"], tenant_id)
    return True
