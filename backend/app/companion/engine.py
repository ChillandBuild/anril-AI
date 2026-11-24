"""reply(): one companion turn, end to end. The public entry point other modules call.

Flow: load the character → take a load slot → person + conversation →
history → book search (kb.search over the character's collection) and memory in parallel →
build the prompt → LLM → read the mood tag and the [used: n] tag → label the reply
(primary / book / own / chat, decided by code) → save the reply, mood and label → return it.

App-run tools: if the LLM asks for one of the app's tools, the turn is saved as a
pending turn and reply() returns status "tool_call". The app runs the tool and calls
continue_reply(turn_id, results); the load slot is free while it does. At most 3 LLM rounds:
round 3 goes without tools, so the AI has to answer.

reply_format (optional, per request): the reply comes back as chat bubbles, chips, a button and a tag
(reply_format.py). It rides in a paused tool turn's state, so the reply after the tools is shaped too.

Chart guard (companions.chart_guard, astrology characters): the reply's chart claims are checked by code
against the chart the app sent (chart_check.find_wrong). Wrong -> one redo with the wrong facts listed;
still wrong -> the handoff line (basis "handoff"), never a reply with a made-up chart fact.

Logs carry ids, timings and error types only, never message text.
"""
import asyncio
import logging
import os
import time
import weakref

from app.companion import chart_check, memory_card, memory_refresh, memory_search, playground, store, tools as app_tools
from app.companion.birth_guard import strip_app_data
from app.companion.memory import forget_providers, provider_for
from app.companion.models import AppTool, CompanionReply, ToolResult
from app.companion.kb import learning as kb_learning
from app.companion.kb import rewrite as kb_rewrite
from app.companion.kb import search as kb_search
from app.companion.kb.types import KbResult
from app.companion.prompt import (build_messages, label_reply, parse_mood, parse_used, said_talk, split_working,
                                  who_block, with_reply_language)
from app.companion.reply_format import ReplyFormat, finalize, read_format, strip_tags
from app.services import ai_reply

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10   # default when a character has no history_messages set
LLM_MAX_TOKENS = 700
# working_step: the hidden working comes first, then the reply. 1,800 was too few: on 3.8 Flash a long
# working used all of it and no reply came (the sorry line), live eval 2026-11-18.
LLM_MAX_TOKENS_WORKING = 3000


def _max_tokens(companion: dict) -> int:
    return LLM_MAX_TOKENS_WORKING if (companion or {}).get("working_step") else LLM_MAX_TOKENS
LLM_TEMPERATURE = 0.5
LLM_PURPOSE = "companion_reply"
SLOT_WAIT_SECONDS = 5.0
MAX_ROUNDS = 3

FALLBACK_LINES = {
    "ta-en": "Mannikkavum, ippo konjam technical problem irukku. Konja neram kazhichu thirumba kelunga.",
    "ta": "மன்னிக்கவும், இப்போது ஒரு சிறிய தொழில்நுட்பச் சிக்கல். சிறிது நேரம் கழித்து மீண்டும் கேளுங்கள்.",
    "en": "Sorry, I'm having a small technical problem right now. Please ask me again in a little while.",
}


# What a Strict character (own_reasoning off) says instead of an answer that came from no file, when the
# business has not written its own on the Knowledge tab (companions.handoff_line). Per language;
# English when unknown. Generic on purpose: "our astrologer" is AstroTamil's own line, not ours.
# Same text as frontend characterForm.GENERIC_HANDOFF (the box's placeholder): change both.
HANDOFF_LINES = {
    "ta-en": "Idharku engal team-idam ketpadhu nalladhu.",
    "ta": "இதற்கு எங்கள் குழுவிடம் கேட்பது நல்லது.",
    "en": "Our team can help you with this better.",
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


def handoff_line(companion: dict) -> str:
    """The business's own line, else the generic one in the character's language.
    {"handoff_line": "இதற்கு நம் ஜோதிடரிடம் கேட்பது நல்லது."} -> that line;
    {"language": "ta"} -> "இதற்கு எங்கள் குழுவிடம் கேட்பது நல்லது." """
    own = (companion.get("handoff_line") or "").strip()
    return own or HANDOFF_LINES.get(line_language(companion) or "", HANDOFF_LINES["en"])


def line_language(companion: dict) -> str | None:
    """The code for the fixed lines: the app's reply_language for this reply, else the character's."""
    return companion.get("reply_language_code") or companion.get("language")


def _person_today(companion: dict, person: dict):
    """The person's own date: their app's zone -> else the character's -> else India. Never the server's."""
    return memory_card.local_today(None, memory_card.zone_for(companion, person.get("timezone")))


def character_model(companion: dict | None) -> str:
    """The model this character replies with (companions.model). Missing, or a model since removed
    from the list, is the default, so a reply never fails over a stale value."""
    return ai_reply.reply_model_or_default((companion or {}).get("model"))


def is_small_talk(kb: KbResult | None) -> bool:
    """True when the question step said no file is needed ("வணக்கம்", "thanks"). Unknown (no search ran) is
    not small talk, so a real question is never sent to the cheap model by mistake."""
    return kb is not None and not kb.needs_docs


def _model_kw(companion: dict, model: str | None, kb: KbResult | None = None) -> dict:
    """The model keywords for ai_reply. model = the Playground's pick: exactly that model, no fallback
    (a test of one model must not be answered by the other). None = the character's own model, with
    the usual one retry on the other model when Google struggles. Small talk goes to the character's
    small_talk_model when one is set (and still offered).
    Example: Jothidar on 3.8 Flash, small talk on 3.5 Flash Lite: "வணக்கம்" -> 3.5 Flash Lite;
    "வெளிநாட்டு வேலை கிடைக்குமா?" -> {"model": "google/gemini-3.8-flash", "fallback": True}."""
    if model:
        return {"model": model}
    small = (companion or {}).get("small_talk_model")
    if small in ai_reply.REPLY_MODELS and is_small_talk(kb):
        return {"model": small, "fallback": True}
    return {"model": character_model(companion), "fallback": True}


# Backup call: Google sometimes sits on one reply for 15 s or more while the next identical call takes 1.5 s.
# After HEDGE_AFTER_SECONDS with no answer, the SAME call (same prompt, model, settings) goes out once more
# and the first one back with text is used; the other is dropped. At most MAX_BACKUPS backups are out at
# once across this server, so a Google slowdown does not double every call while it lasts.
HEDGE_AFTER_SECONDS = 6.0
MAX_BACKUPS = 2
_backups_out = 0


async def _chat(companion: dict, tenant_id: str, prompt: list[dict], model: str | None,
                kb: KbResult | None) -> str | None:
    """ai_reply._llm_chat for one reply, with the backup call above. Raises what _llm_chat raises when
    every call failed. Example: call 1 has not answered at 6 s -> call 2 goes out, answers at 7.4 s ->
    call 2's text is used, call 1 is cancelled."""
    global _backups_out

    def call():
        task = asyncio.create_task(ai_reply._llm_chat(
            prompt, max_tokens=_max_tokens(companion), tenant_id=tenant_id, purpose=LLM_PURPOSE,
            temperature=LLM_TEMPERATURE, **_model_kw(companion, model, kb)))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())   # a dropped call's error is not logged as lost
        return task

    first = call()
    try:
        done, _ = await asyncio.wait({first}, timeout=HEDGE_AFTER_SECONDS)
    except asyncio.CancelledError:   # the reply itself was cancelled: don't leave the call running
        first.cancel()
        raise
    if done or _backups_out >= MAX_BACKUPS:
        return await first
    _backups_out += 1
    calls = [first, call()]
    try:
        pending, empty, error = set(calls), None, None
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception() is not None:
                    error = task.exception()
                elif (task.result() or "").strip():
                    logger.info("companion %s: backup call sent, call %d answered first",
                                companion["id"], calls.index(task) + 1)
                    return task.result()
                else:
                    empty = task.result()   # no text: wait for the other call before settling for this
        if empty is not None or error is None:
            return empty
        raise error
    finally:
        _backups_out -= 1
        for task in calls:
            task.cancel()   # no-op for a finished call


async def _live_companion(tenant_id: str, companion_id: str, require_live: bool = False,
                          model: str | None = None) -> tuple[dict, str]:
    """The character, checked usable, plus the LLM provider name (of the Playground's picked model,
    else the character's own)."""
    companion = await store.get_companion(tenant_id, companion_id)
    if not companion:
        raise CompanionNotFound(companion_id)
    # An archived character is silent even if a racing PATCH left its status as live.
    if companion.get("status") == "paused" or companion.get("archived_at"):
        raise CompanionPaused(companion_id)
    if require_live and companion.get("status") != "live":
        raise CompanionNotLive(companion_id)
    try:
        provider, _ = await asyncio.to_thread(ai_reply._provider_for, tenant_id, model or character_model(companion))
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
    app_data: str | None = None, profile_name: str | None = None, reply_format: ReplyFormat | None = None,
    reply_language: str | None = None,
) -> CompanionReply:
    """model and use_memory are for the dashboard Playground only; the public API never sets them.
    use_memory=False is the "Compare" reply: no remembered facts, no chat history, no tools,
    nothing saved. It shows how the character answers a stranger.
    timezone_name: the person's IANA zone from their app (validated by the API), saved on the person.
    app_data: what the app knows about this person, sent with this message (models.app_data_text). It goes
    into this reply's prompt only; it is never saved (a paused tool turn keeps its prompt for 2 minutes).
    profile_name: whose profile this person row is about (e.g. "Karthik" for the chart in app_data); saved on
    the person like display_name, and both go into the prompt's WHO line (prompt.who_block).
    reply_format: the app wants bubbles, chips, a button and a tag (reply_format.py); None = text only, as before.
    reply_language: the language the app wants this reply in ("en", "English"); None = the character's own."""
    tools = tools or []
    app_tools.validate_tools(tools)
    companion, provider = await _live_companion(tenant_id, companion_id, require_live, model)
    companion = with_reply_language(companion, reply_language)
    sem = await _take_slot(companion_id)
    try:
        if not use_memory:
            return await _reply_without_memory(companion, tenant_id, message, model, app_data,
                                               who_block(display_name, profile_name), reply_format=reply_format)
        return await _reply(companion, provider, tenant_id, external_user_id, message, display_name, tools,
                            model, timezone_name, app_data, profile_name, reply_format)
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
        companion = with_reply_language(companion, state.get("reply_language"))
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
            reply_format=ReplyFormat(**state["reply_format"]) if state.get("reply_format") else None,
            app_data=state.get("app_data"),
        )
    finally:
        sem.release()


async def _knowledge(tenant_id: str, companion: dict, message: str, history: list[dict],
                     rewrite=None) -> KbResult | None:
    """The passages this character's collection holds for the message. None: the character has no
    collection, so nothing is searched and the reply carries no label. A search that breaks never
    breaks the reply: it comes back as "nothing found"."""
    collection_id = companion.get("knowledge_collection_id")
    if not collection_id:
        return None
    try:
        whole = {"full_main": True} if companion.get("full_main_resource") else {}   # only when switched on
        return await kb_search.search(tenant_id, collection_id, message, history, companion_id=companion["id"],
                                      rewrite=rewrite, **whole)
    except Exception as exc:
        logger.warning("companion %s: knowledge search failed (%s)", companion["id"], type(exc).__name__)
        return KbResult(failed=True)


def _shared_rewrite(tenant_id: str, companion: dict, memory, message: str, history: list[dict],
                    with_kb: bool):
    """ONE rewrite call per reply, started here and read by both searches (kb/rewrite.py). None when
    nobody needs it: a Level 1 character with no files, or the Playground's rewrite switch is off.
    Example: Priya -> Guru "amma surgery epdi pochu": one flash-lite call gives the English and the
    Tamil-script question; the file search and the memory search both use that same answer."""
    ov = playground.current()
    if ov is not None and not ov.rewrite:
        return None
    memory_searches = getattr(memory, "searches", False) and (
        ov is None or (ov.mode == "auto" and ov.sources != "knowledge"))   # same test as MemoryCard.context_for
    wanted = (with_kb and companion.get("knowledge_collection_id")) or memory_searches
    return asyncio.ensure_future(kb_rewrite.rewrite(tenant_id, message, history)) if wanted else None


async def _memory(provider, tenant_id: str, companion: dict, person: dict, message: str, rewrite=None) -> str:
    companion_id = companion["id"]
    try:
        return await provider.context_for(tenant_id, companion_id, person["id"], message,
                                          companion=companion, person=person, rewrite=rewrite) or ""
    except Exception as exc:
        logger.warning("companion %s: memory lookup failed (%s)", companion_id, type(exc).__name__)
        return ""


async def _reply_without_memory(companion: dict, tenant_id: str, message: str,
                                model: str | None, app_data: str | None = None,
                                who: str | None = None, reply_format: ReplyFormat | None = None) -> CompanionReply:
    """One stateless reply: books only, no facts, no history, and no DB write at all (no person,
    no conversation), so it can run beside the normal reply without racing it. The app's data still
    comes along: it is what the app sends, not what the character remembers."""
    started = time.monotonic()
    kb = await _knowledge(tenant_id, companion, message, [])
    mood = companion.get("default_mood") or "calm"
    prompt = build_messages(companion, mood, kb, "", [], message, app_data=app_data, who=who,
                            reply_format=reply_format)
    raw = None
    try:
        raw = await _chat(companion, tenant_id, prompt, model, kb)
    except Exception as exc:
        logger.warning("companion %s: LLM call failed without memory (%s)", companion["id"], type(exc).__name__)
        playground.problem(ai_reply.describe_llm_error(exc))
    raw, chart_failed = await _chart_guard(companion, tenant_id, prompt, raw, app_data, kb, mood, model, reply_format)
    text, new_mood, basis, sources = _read_reply(raw, mood, kb, companion, reply_format, chart_failed)
    text, shape = _shape(text, raw, basis, kb, companion, reply_format, message)
    logger.info("companion %s: reply without memory done (total %dms)", companion["id"],
                int((time.monotonic() - started) * 1000))
    return CompanionReply(status="done", text=text, mood=new_mood, basis=_shown_basis(basis, companion),
                          sources=sources, **shape)


async def _reply(companion: dict, provider: str, tenant_id: str, external_user_id: str, message: str,
                 display_name: str | None, tools: list[AppTool], model: str | None = None,
                 timezone_name: str | None = None, app_data: str | None = None,
                 profile_name: str | None = None, reply_format: ReplyFormat | None = None) -> CompanionReply:
    started = time.monotonic()
    companion_id = companion["id"]
    person = await store.find_or_create_end_user(tenant_id, external_user_id, display_name, timezone_name,
                                                 profile_name=profile_name)
    who = who_block(person.get("display_name"), person.get("profile_name"))   # the saved names, not just this message's
    memory = _provider(companion)

    # History is read before this message is saved, so the prompt doesn't carry it twice. It is read
    # first because the book search needs it: "and what about Rahu?" only makes sense with the turn before.
    # The conversation and the history need only the person, not each other, so they are read together.
    conversation, history = await asyncio.gather(
        store.open_conversation(tenant_id, companion_id, person["id"], companion.get("default_mood") or "calm"),
        store.recent_messages(tenant_id, companion_id, person["id"],
                              limit=companion.get("history_messages") or HISTORY_LIMIT,
                              after=person.get("chat_read_after")))
    ov = playground.current()   # None on the live path
    agentic = ov is not None and ov.mode == "agentic"
    with_kb = ov is None or (not agentic and ov.sources != "memories")
    rewrite = _shared_rewrite(tenant_id, companion, memory, message, history, with_kb)
    try:
        kb, memory_context = await asyncio.gather(
            _knowledge(tenant_id, companion, message, history, rewrite) if with_kb else _no_kb(),
            _memory(memory, tenant_id, companion, person, message, rewrite),
        )
    finally:
        if rewrite is not None and not rewrite.done():   # memory gave up waiting and nobody else needs it
            rewrite.cancel()
    # The message is saved in _finish, together with the reply, and only when the reply worked: a failed
    # turn leaves no "sorry" line in the history for the next prompt or the memory step to read.

    mood = _mood(conversation, companion)
    if agentic:
        return await _agentic(companion, provider, tenant_id, conversation, person, message, history,
                              memory_context, mood, tools, started, model, ov, app_data, who, reply_format)
    prompt = build_messages(companion, mood, kb, memory_context, history, message, _person_today(companion, person),
                            app_data=app_data, who=who, reply_format=reply_format)
    logger.info("companion %s: prompt ready (prep %dms)", companion_id, int((time.monotonic() - started) * 1000))
    return await _run_rounds(companion, provider, tenant_id, conversation, message, prompt, tools, 1, [], started,
                             model=model, kb=kb, reply_format=reply_format, app_data=app_data)


async def _no_kb() -> None:
    return None


# ---- Agentic mode (Playground only) -----------------------------------------------------------
# Round 1 offers the model two search tools and nothing has been searched yet. If it calls them,
# we run the searches here (never handed to the app), rebuild the prompt with what was found, and
# round 2 is the normal reply path, so the [used: n] label and app tools work as in auto mode.
# Example: "how did it go?" -> search_memory("interview") -> "Interview at Zoho on 20 Nov" -> the
# reply asks about Zoho. "hi" -> no tool call -> round 1's text is the reply, no search at all.

_QUERY = {"type": "object", "properties": {"query": {"type": "string", "description": "What to look for, in a few words"}},
          "required": ["query"]}
SEARCH_MEMORY = AppTool(name="search_memory", parameters=_QUERY, description=(
    "Search what this person told you in earlier conversations. Use it when the answer depends on "
    "their past: what they bought, said, planned or asked before."))
SEARCH_KNOWLEDGE = AppTool(name="search_knowledge", parameters=_QUERY, description=(
    "Search your files (policies, product details, documents). Use it for factual questions your "
    "files may answer."))
AGENTIC_NOTE = (
    "\n\n[SEARCH TOOLS]\nYour files and older conversations have NOT been searched for this message yet; "
    "'none found' above only means that. Call search_knowledge for questions your files may answer and "
    "search_memory when the answer depends on what this person said before. For small talk, just reply.")


async def _agentic(companion: dict, provider: str, tenant_id: str, conversation: dict, person: dict,
                   message: str, history: list[dict], memory_context: str, mood: str, tools: list[AppTool],
                   started: float, model: str | None, ov: "playground.Overrides",
                   app_data: str | None = None, who: str | None = None,
                   reply_format: ReplyFormat | None = None) -> CompanionReply:
    offered = [t for t in (SEARCH_MEMORY, SEARCH_KNOWLEDGE)
               if ov.sources == "all" or (ov.sources == "memories") == (t is SEARCH_MEMORY)]
    if not companion.get("knowledge_collection_id"):
        offered = [t for t in offered if t is not SEARCH_KNOWLEDGE]
    if not offered:   # nothing to search (e.g. knowledge only, no collection): the normal reply path
        ov.note("Agentic: no search tool to offer, replied as usual")
        prompt = build_messages(companion, mood, None, memory_context, history, message, _person_today(companion, person),
                                app_data=app_data, who=who, reply_format=reply_format)
        return await _run_rounds(companion, provider, tenant_id, conversation, message, prompt, tools, 1, [],
                                 started, model=model, reply_format=reply_format)
    search_names = {t.name for t in offered}
    # The app's own tools are offered too (search tool names win a clash). An app-tool call here is not
    # run in round 1: round 2 offers the app tools again, after any searches, through the normal pause path.
    app_offered = [t for t in tools if t.name not in search_names]
    prompt = build_messages(companion, mood, None, memory_context, history, message, _person_today(companion, person),
                            app_data=app_data, who=who, reply_format=reply_format)
    prompt[0] = {**prompt[0], "content": prompt[0]["content"] + AGENTIC_NOTE}
    llm_started = time.monotonic()
    raw, calls, wants_app = None, [], False
    try:
        raw, raw_calls = await ai_reply._llm_chat_with_tools(
            prompt, app_tools.to_llm_tools(offered + app_offered), max_tokens=_max_tokens(companion),
            tenant_id=tenant_id, purpose=LLM_PURPOSE, **_model_kw(companion, model))
        normalized = app_tools.normalize_calls(raw_calls)
        calls = [c for c in normalized if c["name"] in search_names]
        wants_app = any(c["name"] in {t.name for t in app_offered} for c in normalized)
    except Exception as exc:
        logger.warning("companion %s: agentic round failed (%s)", companion["id"], type(exc).__name__)
    llm_ms = int((time.monotonic() - llm_started) * 1000)
    if not calls and not wants_app:
        ov.note(f"Round 1: answered without searching ({llm_ms} ms)")
        return await _finish(companion, tenant_id, conversation, message, raw, [], started, llm_ms, None,
                             reply_format)
    if wants_app:
        ov.note("Round 1: asked for an app tool; it is offered again in round 2")

    kb, found, log = None, [], []
    for call in calls:
        query = str(call["args"].get("query") or message)[:500]
        if call["name"] == SEARCH_KNOWLEDGE.name and kb is None:
            kb = await _knowledge(tenant_id, companion, query, history)
            ov.note(f'Round 1: called search_knowledge("{query}") -> {len(kb.passages) if kb else 0} passages')
        elif call["name"] == SEARCH_MEMORY.name:
            hits = await memory_search.search(tenant_id, companion["id"], person["id"], query, with_recent=False)
            block = memory_search.render_hits(hits, shown=memory_context)
            if block:
                found.append(block)
            ov.note(f'Round 1: called search_memory("{query}") -> {len(hits)} hits')
        log.append({"name": call["name"], "args": call["args"], "ok": True})
    context = "\n".join(part for part in [memory_context] + found if part)
    prompt = build_messages(companion, mood, kb, context, history, message, _person_today(companion, person),
                            app_data=app_data, who=who, reply_format=reply_format)
    reply = await _run_rounds(companion, provider, tenant_id, conversation, message, prompt, tools, 2, log, started,
                              model=model, kb=kb, reply_format=reply_format)
    total = int((time.monotonic() - started) * 1000)
    ov.note(f"Round 2: reply written ({total} ms total)" if reply.status == "done"
            else f"Round 2: paused for app tools ({total} ms so far)")
    return reply


def _provider(companion: dict):
    return provider_for(companion.get("memory_level") or 1, companion.get("memory_engine") or "card")


def _mood(conversation: dict, companion: dict) -> str:
    return conversation.get("mood") or companion.get("default_mood") or "calm"


async def _run_rounds(companion: dict, provider: str, tenant_id: str, conversation: dict, user_message: str,
                      prompt: list[dict], tools: list[AppTool], round_no: int, tool_log: list[dict],
                      started: float, *, model: str | None = None, kb: KbResult | None = None,
                      reply_format: ReplyFormat | None = None, app_data: str | None = None) -> CompanionReply:
    """One LLM round. Either pauses for app tools (status tool_call) or finishes the reply.
    kb: the passages in the prompt. It rides along (and into a paused turn's state) so the finished
    reply can be checked against what was really supplied. reply_format rides along the same way, and
    app_data too (for the chart guard; kept only when the guard is on, birth details already removed)."""
    companion_id = companion["id"]
    use_tools = bool(tools) and round_no < MAX_ROUNDS
    llm_started = time.monotonic()
    raw, calls = None, []
    try:
        if use_tools:
            raw, raw_calls = await ai_reply._llm_chat_with_tools(
                prompt, app_tools.to_llm_tools(tools), max_tokens=_max_tokens(companion),
                tenant_id=tenant_id, purpose=LLM_PURPOSE, **_model_kw(companion, model, kb),
            )
            calls = app_tools.normalize_calls(raw_calls)
        else:
            raw = await _chat(companion, tenant_id, prompt, model, kb)
    except Exception as exc:
        logger.warning("companion %s: LLM call failed on round %d (%s)", companion_id, round_no, type(exc).__name__)
        playground.problem(ai_reply.describe_llm_error(exc))
    llm_ms = int((time.monotonic() - llm_started) * 1000)

    known = {t.name for t in tools}
    if calls and not any(c["name"] in known for c in calls):
        # The AI asked only for tools the app never sent: answer "tool unavailable" ourselves
        # and go straight to the next round instead of handing the app nothing to run.
        extra, log = app_tools.round_messages(provider, raw or "", calls, [], known)
        return await _run_rounds(companion, provider, tenant_id, conversation, user_message,
                                 prompt + extra, tools, round_no + 1, tool_log + log, started, model=model, kb=kb,
                                 reply_format=reply_format, app_data=app_data)
    if calls:
        state = {"prompt": prompt, "calls": calls, "assistant_text": raw or "",
                 "user_message": user_message, "tool_log": tool_log}
        if model:
            state["model"] = model
        if kb is not None:
            state["kb"] = kb.to_json()
        if reply_format is not None:
            state["reply_format"] = reply_format.model_dump()
        if app_data and companion.get("chart_guard"):
            state["app_data"] = strip_app_data(app_data)
        if companion.get("reply_language"):   # the sorry and handoff lines after the tools speak it too
            state["reply_language"] = companion["reply_language"]
        turn_id = await store.create_pending_turn(
            tenant_id, companion_id, conversation["id"], state, [t.model_dump() for t in tools], round_no)
        logger.info("companion %s: paused for %d tool call(s) on round %d (llm %dms)",
                    companion_id, len(calls), round_no, llm_ms)
        return CompanionReply(
            status="tool_call", turn_id=turn_id, conversation_id=conversation["id"],
            tool_calls=[c for c in calls if c["name"] in known],
        )
    raw, chart_failed = await _chart_guard(companion, tenant_id, prompt, raw, app_data, kb,
                                           _mood(conversation, companion), model, reply_format)
    return await _finish(companion, tenant_id, conversation, user_message, raw, tool_log, started, llm_ms, kb,
                         reply_format, chart_failed)


async def _chart_guard(companion: dict, tenant_id: str, prompt: list[dict], raw: str | None,
                       app_data: str | None, kb: KbResult | None, mood: str, model: str | None,
                       reply_format: ReplyFormat | None) -> tuple[str | None, bool]:
    """Chart guard, part 2: (raw reply to use, handed off?). Only for chart_guard characters with a chart
    in app_data; small talk and an already handed-off reply are not checked.
    Example: draft "Guru is in your 7th house" (chart: Guru in Simmam, house 8; today house 1 from rasi)
    -> one redo with that fact listed -> "Guru is in Simmam, your 8th house..." -> sent. A redo that is
    still wrong (or fails) -> (draft, True): the person gets the handoff line, not the wrong fact."""
    if not companion.get("chart_guard") or not app_data or is_small_talk(kb) or not _has_text(raw):
        return raw, False
    chart = chart_check.parse_app_data(app_data)
    if chart.empty():
        return raw, False
    basis = _read_reply(raw, mood, kb, companion, reply_format)[2]
    if basis in (None, "chat") or _handed_off(basis, companion):   # a question back, or already the handoff line
        return raw, False
    wrong = chart_check.find_wrong(chart, _visible(raw))
    if not wrong:
        return raw, False
    ov = playground.current()
    if ov is not None:
        ov.note(f"Chart check: {len(wrong)} wrong fact(s), redo: " + "; ".join(wrong[:3]))
    redo = None
    try:
        redo = await _chat(companion, tenant_id, prompt + [
            {"role": "assistant", "content": raw}, {"role": "user", "content": chart_check.redo_note(wrong)}], model, kb)
    except Exception as exc:
        logger.warning("companion %s: chart redo failed (%s)", companion["id"], type(exc).__name__)
    still = chart_check.find_wrong(chart, _visible(redo)) if _has_text(redo) else wrong
    logger.info("companion %s: chart check wrong=%d redo=%s", companion["id"], len(wrong),
                "handoff" if still else "ok")
    if ov is not None:
        ov.note("Chart check: redo passed" if not still else
                f"Chart check: redo still wrong ({'; '.join(still[:3])}), sent the handoff line")
    return (redo, False) if not still else (raw, True)


def _visible(raw: str | None) -> str:
    """The reply text the person would see: no working block, no [used]/[mood] or reply_format tags."""
    text, _ = parse_used(split_working(raw)[0] or "", 0)
    return strip_tags(parse_mood(text, "calm")[0])


def _read_reply(raw: str | None, previous_mood: str, kb: KbResult | None, companion: dict,
                reply_format: ReplyFormat | None = None,
                chart_failed: bool = False) -> tuple[str, str, str | None, list[dict]]:
    """'[mood: calm] [used: 1] Sani 7th house la…' -> (text, mood, basis, sources), both tags removed.
    The label is decided by code from the passages really supplied. An empty reply becomes the
    fallback line with no label: it came from no book and from no reasoning.
    [used: ...] is taken out first, so the mood tag is found even when the model wrote it second.
    [used: talk] (a question back, small talk, a polite decline) is "chat", not a gap. A Strict
    character's "own" answer becomes the handoff line; the label stays "own" so the gap is counted.
    A <working> block (working_step) is cut off first; the Playground shows it.
    reply_format: a reply the model tagged as anything but an answer ([tag: need_details], a button id, ...)
    is "chat" too, so a Strict character's helpline or "use this button" reply is not swapped for the handoff line.
    chart_failed: the chart guard found wrong chart facts twice -> the handoff line, basis "handoff"."""
    raw, working = split_working(raw)
    ov = playground.current()
    if ov is not None:
        ov.working = working
    text, used = parse_used(raw or "", len(kb.passages) if kb else 0)
    text, mood = parse_mood(text, previous_mood)
    text = text.strip()
    if not text:
        return fallback_line(line_language(companion)), previous_mood, None, []
    basis, sources = label_reply(kb, used)
    if basis == "own" and (said_talk(raw) or _not_an_answer(text, reply_format)):
        basis = "chat"
    if chart_failed:
        basis, sources = "handoff", []
    if _handed_off(basis, companion):
        text = handoff_line(companion)
    return text, mood, basis, sources


def _not_an_answer(text: str, fmt: ReplyFormat | None) -> bool:
    """True when the app asked for a reply_format and the model tagged this reply as something other than an
    answer: '[tag: helpline] ...' -> True; '[tag: counted] ...', no tag, or no format -> False."""
    return fmt is not None and read_format(text, fmt).tag not in (None, "counted")


def _handed_off(basis: str | None, companion: dict) -> bool:
    """A Strict character's own-reasoning answer, or a reply the chart guard stopped: _read_reply swapped it
    for the handoff line."""
    return basis == "handoff" or (basis == "own" and companion.get("own_reasoning") is False)


def _has_text(raw: str | None, with_format: bool = False) -> bool:
    """False when the model gave nothing to show (the call failed or only tags came back), i.e. when
    _read_reply answers with the fallback line. with_format: the [tag:] [button:] [chips:] tags of a
    reply_format count as tags too, so '[mood: calm] [tag: counted] [chips: none]' is nothing to show."""
    text, _ = parse_used(split_working(raw)[0] or "", 0)
    text = parse_mood(text, "calm")[0]
    return bool((strip_tags(text) if with_format else text).strip())


def _shape(text: str, raw: str | None, basis: str | None, kb: KbResult | None, companion: dict,
           fmt: ReplyFormat | None, question: str | None = None) -> tuple[str, dict]:
    """(text for CompanionReply.text and the saved chat, the four reply_format fields). No format: text as is,
    all four None. With one: text = the bubbles joined by a blank line, never a tag, separator or chip.
    Example: '[tag: counted] Guru 7th la.\n---\nNalla time.\n[chips: Eppo? | Velai?]' ->
    ('Guru 7th la.\n\nNalla time.', {"bubbles": [...2], "chips": ["Eppo?", "Velai?"], "button": None, "tag": "counted"})"""
    if fmt is None:
        return text, {"bubbles": None, "chips": None, "button": None, "tag": None}
    handed = _handed_off(basis, companion)
    # the astrologer button comes with an own reading, not with a chart lookup ("What is my lagnam?")
    reading = basis == "own" and not chart_check.is_chart_lookup(question)
    shaped = finalize(read_format(text, fmt), fmt, small_talk=is_small_talk(kb), handed_off=handed,
                      failed=not _has_text(raw, with_format=True), text=text, own=reading,
                      fallback_text=handoff_line(companion) if handed else fallback_line(line_language(companion)))
    return "\n\n".join(shaped.bubbles), shaped._asdict()


def _logged_basis(basis: str | None, shape: dict, fmt: ReplyFormat | None) -> str | None:
    """The question log's label. The model choosing the handoff button (e.g. "astrologer") is a question
    the files did not answer, so it is "handoff" (on the Missing answers list), not "chat"."""
    if basis == "chat" and fmt is not None and shape.get("button") and any(
            b.handoff and b.id == shape["button"] for b in fmt.buttons):
        return "handoff"
    return basis


def _shown_basis(basis: str | None, companion: dict) -> str | None:
    """The label the person sees. A Strict character (own_reasoning off) answers "own" with the
    handoff line; showing "own reading" on that would be wrong. The
    question log still gets "own", so the owner's missing-answers list keeps counting it."""
    return None if _handed_off(basis, companion) else basis


async def _finish(companion: dict, tenant_id: str, conversation: dict, user_message: str, raw: str | None,
                  tool_log: list[dict], started: float, llm_ms: int, kb: KbResult | None = None,
                  reply_format: ReplyFormat | None = None, chart_failed: bool = False) -> CompanionReply:
    companion_id = companion["id"]
    text, mood, basis, sources = _read_reply(raw, _mood(conversation, companion), kb, companion,
                                             reply_format, chart_failed)
    text, shape = _shape(text, raw, basis, kb, companion, reply_format, user_message)
    if not _has_text(raw, with_format=reply_format is not None):
        # The AI call failed (or came back empty): the person gets the sorry line, and nothing is saved,
        # so it isn't counted toward the memory step and isn't read back as something the character said.
        logger.info("companion %s: reply failed, turn not saved", companion_id)
        return CompanionReply(status="done", text=text, mood=mood, conversation_id=conversation["id"], **shape)

    # Saved with secrets hidden ("my OTP is [hidden]"); the prompt got the message as typed.
    await store.save_message(tenant_id, conversation, "user", memory_card.mask_secrets(user_message))
    shown = _shown_basis(basis, companion)
    saved = await store.save_message(tenant_id, conversation, "assistant", memory_card.mask_secrets(text), mood=mood,
                                     tool_calls=tool_log or None, basis=shown, sources=sources)
    if mood != conversation.get("mood"):
        await store.set_conversation_mood(tenant_id, conversation["id"], mood)
    try:
        await _provider(companion).record_turn(
            tenant_id, companion_id, conversation["end_user_id"], user_message, text)
    except Exception as exc:
        logger.warning("companion %s: memory record failed (%s)", companion_id, type(exc).__name__)
    try:
        memory_refresh.schedule(companion, conversation["end_user_id"])  # background; Level 2 only
    except Exception as exc:
        logger.warning("companion %s: memory refresh not scheduled (%s)", companion_id, type(exc).__name__)

    if kb is not None and basis and not playground.changes_search():
        # Background, never raises: the question log keeps only the topic, never the person or the message.
        # A Playground reply with changed search settings is left out: a stricter judge would log
        # "missing answers" and shortcut misses that live chat never had.
        kb_learning.schedule_log(tenant_id, companion_id, kb, _logged_basis(basis, shape, reply_format), sources)

    logger.info("companion %s: reply done (llm %dms, total %dms, basis %s)", companion_id, llm_ms,
                int((time.monotonic() - started) * 1000), basis)
    return CompanionReply(
        status="done", text=text, mood=mood, conversation_id=conversation["id"], message_id=saved["id"],
        basis=shown, sources=[{k: s[k] for k in ("document", "page_from", "page_to")} for s in sources], **shape,
    )


async def forget_person(tenant_id: str, external_user_id: str) -> bool:
    """'Forget me', business-wide: wipes this person's chats with every character of the tenant,
    then wipes their facts in every memory engine. A plain user id takes every profile of theirs with it
    ("u42" also forgets "u42~p7"); a profile id forgets just that profile. False if none ever talked here."""
    people = await store.find_person_rows(tenant_id, external_user_id)
    for person in people:
        await store.forget_end_user(tenant_id, person["id"])
        for provider in forget_providers():
            await provider.forget(tenant_id, person["id"])
        logger.info("companion: forgot end user %s for tenant %s", person["id"], tenant_id)
    return bool(people)
