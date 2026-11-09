import json
import logging
import re
import time
import httpx
from app.db.supabase import get_supabase
from app.services.growth import record_stage_event, sync_follow_up_jobs
from app.services.knowledge_service import get_knowledge_context
from app.services.catalog_retrieval import (
    contention_set,
    classify_gate,
    differing_attribute_directive,
    broad_browse_directive,
    match_catalog_items,
)
from app.services.assignment import (
    maybe_assign_lead,
    get_inbox_config,
    should_escalate_to_inbox,
)
from app.services.entitlements import meter, check_quota

logger = logging.getLogger(__name__)

from app.config_dynamic import get_setting, require_tenant_setting
from app.services.sarvam_client import sarvam_chat_completion, sarvam_chat_completion_with_tools
from app.services.gemini_client import gemini_chat_completion, gemini_chat_completion_with_tools
from app.services.openai_client import openai_chat_completion, openai_chat_completion_with_tools
from app.services.groq_client import groq_chat_completion, groq_chat_completion_with_tools

# Each entry: stored ai_reply_model prefix -> (provider name, native-model-id prefix to
# strip). Sarvam has no prefix since its native IDs ("sarvam-30b") are used directly.
_PROVIDER_PREFIXES: list[tuple[str, str]] = [
    ("google/", "gemini"),
    ("openai/", "openai"),
    ("groq/", "groq"),
]

def _resolve_reply_model(tenant_id: str | None) -> str:
    """No silent fallback -- every tenant must explicitly pick a reply model in the
    operator console. Raises if unset, same as the per-provider API key requirement
    below (operator decision, see decisions/log.md)."""
    return require_tenant_setting("ai_reply_model", tenant_id)


def _provider_and_native_model(model: str) -> tuple[str, str]:
    if model.startswith("sarvam"):
        return "sarvam", model
    for prefix, provider in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return provider, model[len(prefix):]
    raise RuntimeError(f"Unrecognized reply model '{model}'")


# The reply models a tenant can pick (same list as the operator console's REPLY_MODELS).
REPLY_MODELS: dict[str, str] = {
    "sarvam-30b": "Sarvam 30B",
    "sarvam-105b": "Sarvam 105B",
    "google/gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "google/gemini-3.5-flash": "Gemini 3.5 Flash",
    "openai/gpt-5.4-nano-2026-03-17": "GPT-5.4 Nano",
    "openai/gpt-5-nano-2025-08-07": "GPT-5 Nano",
    "groq/llama-3.3-70b-versatile": "Llama 3.3 70B",
    "groq/qwen/qwen3-32b": "Qwen 3 32B",
}


def available_reply_models(tenant_id: str | None) -> list[dict]:
    """The models this tenant could switch to: those whose provider API key is set. Used only
    by the Agents Playground model picker; live replies always use ai_reply_model."""
    out = []
    for model_id, label in REPLY_MODELS.items():
        provider, _ = _provider_and_native_model(model_id)
        if get_setting(f"{provider}_api_key", tenant_id=tenant_id):
            out.append({"id": model_id, "label": label})
    return out


def _provider_for(tenant_id: str | None, model: str | None) -> tuple[str, str]:
    """(provider, native_model): the tenant's ai_reply_model, or an explicit model override
    (Playground only), whose provider key must still be set for this tenant."""
    if not model:
        return _resolve_provider(tenant_id)
    provider, native_model = _provider_and_native_model(model)
    require_tenant_setting(f"{provider}_api_key", tenant_id)
    return provider, native_model


def _resolve_provider(tenant_id: str | None) -> tuple[str, str]:
    """Resolves (provider, native_model) for this tenant's selected ai_reply_model, and
    enforces that the tenant has explicitly configured that provider's API key. No
    fallback to a platform-wide key for any provider, including Sarvam -- every client's
    keys are configured independently in the operator console (see decisions/log.md)."""
    provider, native_model = _provider_and_native_model(_resolve_reply_model(tenant_id))
    require_tenant_setting(f"{provider}_api_key", tenant_id)
    return provider, native_model


async def _llm_chat(
    messages: list[dict],
    max_tokens: int = 300,
    tenant_id: str | None = None,
    *,
    purpose: str = "ai_reply",
    temperature: float = 0.4,
    model: str | None = None,
) -> str:
    # purpose/temperature are overridable for non-reply callers (knowledge auto-sort
    # meters under "knowledge_sort" and needs near-deterministic output).
    # model: Agents Playground test chat only. Live replies never pass it.
    provider, native_model = _provider_for(tenant_id, model)
    kwargs = dict(
        messages=messages, model=native_model, temperature=temperature, max_tokens=max_tokens,
        tenant_id=tenant_id, purpose=purpose,
    )
    if provider == "sarvam":
        return await sarvam_chat_completion(**kwargs)
    if provider == "gemini":
        return await gemini_chat_completion(**kwargs)
    if provider == "openai":
        return await openai_chat_completion(**kwargs)
    return await groq_chat_completion(**kwargs)


async def _llm_complete(prompt: str, max_tokens: int = 300, tenant_id: str | None = None) -> str:
    return await _llm_chat([{"role": "user", "content": prompt}], max_tokens=max_tokens, tenant_id=tenant_id)


async def _llm_chat_with_tools(
    messages: list[dict], tools: list[dict], max_tokens: int = 300, tenant_id: str | None = None,
    *, purpose: str = "ai_reply", model: str | None = None,
) -> tuple[str, list[dict]]:
    """Tool-calling counterpart to _llm_chat -- routes catalog-recommendation replies
    through the tenant's selected ai_reply_model instead of hardcoding Sarvam.
    purpose is overridable so other callers (the companion) meter under their own name.
    model: Agents Playground test chat only. Live replies never pass it."""
    provider, native_model = _provider_for(tenant_id, model)
    kwargs = dict(
        messages=messages, tools=tools, model=native_model, max_tokens=max_tokens,
        tenant_id=tenant_id, purpose=purpose,
    )
    if provider == "sarvam":
        return await sarvam_chat_completion_with_tools(**kwargs)
    if provider == "gemini":
        return await gemini_chat_completion_with_tools(**kwargs)
    if provider == "openai":
        return await openai_chat_completion_with_tools(**kwargs)
    return await groq_chat_completion_with_tools(**kwargs)


def _resolve_campaign(db, lead_id: str) -> tuple[str | None, str | None]:
    """Resolve the campaign this lead most recently belongs to, from lead_tag_interest
    (the populated lead↔tag table written on every tagged broadcast send). Returns
    (tag_id, tag_name) or (None, None) for cold/inbound-first leads. Fail-safe: any
    error → no campaign, which makes retrieval fall back to the full (unscoped) KB."""
    try:
        row = (
            db.table("lead_tag_interest")
            .select("tag_id")
            .eq("lead_id", str(lead_id))
            .order("last_seen", desc=True)
            .limit(1)
            .execute()
        )
        if not row.data:
            return None, None
        tag_id = row.data[0]["tag_id"]
        tag = (
            db.table("broadcast_tags")
            .select("name")
            .eq("id", tag_id)
            .limit(1)
            .execute()
        )
        if not tag.data:
            # Tag was deleted — treat as no campaign so retrieval stays unscoped
            # rather than collapsing to global-only chunks.
            return None, None
        return tag_id, tag.data[0]["name"]
    except Exception as e:
        logger.warning(f"Campaign resolve failed for lead {lead_id}: {e}")
        return None, None


def _fetch_conversation_summary(db, lead_id: str) -> str | None:
    """Fetch the compacted conversation_summary from lead_conversation_state.
    Returns None if no summary exists or on error."""
    try:
        row = (
            db.table("lead_conversation_state")
            .select("conversation_summary")
            .eq("lead_id", str(lead_id))
            .limit(1)
            .execute()
        )
        if row and row.data:
            summary = (row.data[0].get("conversation_summary") or "").strip()
            return summary or None
    except Exception as e:
        logger.warning(f"Conversation summary fetch failed for lead {lead_id}: {e}")
    return None

def _fetch_call_context(db, lead_id: str, tenant_id: str) -> list[dict]:
    """Fetch recent call_logs with a populated ai_summary for this lead, newest
    first. Returns [] for a lead with no analyzed calls -- which today is every
    lead, since the SIM Basic path (100% of live calls) never produces a
    transcript. Silent no-op by design until a TeleCMI call actually completes."""
    try:
        rows = (
            db.table("call_logs")
            .select("outcome,manual_status,created_at,ai_summary")
            .eq("lead_id", str(lead_id))
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        return [r for r in (rows.data or []) if r.get("ai_summary")]
    except Exception as e:
        logger.warning(f"Call context fetch failed for lead {lead_id}: {e}")
        return []


def _call_context_block(calls: list[dict]) -> str:
    """Render recent call summaries for the reply prompt: the newest call in
    full, older calls collapsed to one line each. Returns "" if there is
    nothing to show, so it's a pure no-op when calls is empty.

    Shared with the telecaller-facing pre-call brief (routes/leads.py) so both
    surfaces describe the same call the same way."""
    from app.services.call_wrapup import call_result_label

    if not calls:
        return ""

    def _date(c: dict) -> str:
        return (c.get("created_at") or "")[:10]

    latest = calls[0]
    s = latest.get("ai_summary") or {}
    lines = [f"Most recent call ({_date(latest)}, outcome: {call_result_label(latest) or 'unknown'}):"]
    if s.get("brief"):
        lines.append(f"- What was discussed: {s['brief']}")
    if s.get("budget"):
        lines.append(f"- Budget mentioned: {s['budget']}")
    if s.get("timeline"):
        lines.append(f"- Timeline mentioned: {s['timeline']}")
    if s.get("objections"):
        lines.append(f"- Objections raised: {s['objections']}")
    if s.get("commitments"):
        lines.append(f"- We committed to: {s['commitments']}")
    if s.get("open_questions"):
        lines.append(f"- Left unanswered on the call: {s['open_questions']}")
    if s.get("next_action"):
        lines.append(f"- Agreed next step: {s['next_action']}")

    older = calls[1:]
    if older:
        lines.append("\nEarlier calls:")
        for c in older:
            os_ = (c.get("ai_summary") or {}).get("next_action") or "no next step recorded"
            lines.append(f"- {_date(c)} — {call_result_label(c) or 'unknown'} — {os_}")

    return (
        "\n\nPHONE CALL HISTORY:\n"
        + "\n".join(lines)
        + "\nUse this to inform your answer and honour anything the caller "
        "already committed to — do not re-ask something already answered on "
        "the call. Rules:\n"
        "- NEVER tell the customer you know about, heard, or read their phone "
        "call. Do not say things like \"on our call\" or \"you mentioned when "
        "we spoke\" — the customer does not know you have this information.\n"
        "- Use it silently to shape a more informed, consistent answer.\n"
    )


FALLBACK_PROMPT = """You are a helpful AI assistant for a business. Answer customer queries warmly and accurately.
Keep replies concise (2-3 sentences max).
Always guide the customer toward the next step: getting more information, making a purchase, or speaking with the team.
If you don't know a specific detail, say: "Let me connect you with our team who can help you right away."
If the customer asks to speak in a regional language, respond in that language.
"""
# NOTE: This is the generic fallback, used only when the platform master prompt row
# cannot be read. The real prompt lives in platform_defaults.default_master_prompt and
# is edited in one place: Operator → Master Prompt.

REENGAGEMENT_FALLBACKS = {}

_prompt_cache: dict[str, tuple[float, str]] = {}
_PROMPT_TTL = 60.0


_MASTER_CACHE_KEY = "platform:master"


def get_master_prompt() -> str:
    """The single master prompt every tenant runs on.

    Platform-wide by design: it lives in platform_defaults.default_master_prompt and is
    edited in exactly one place (Operator -> Master Prompt). There is deliberately no
    per-tenant override -- what differs between clients is the business description they
    write on their own Knowledge Base page, not how the assistant behaves.
    """
    cached = _prompt_cache.get(_MASTER_CACHE_KEY)
    now = time.monotonic()
    if cached and now - cached[0] < _PROMPT_TTL:
        return cached[1]
    try:
        db = get_supabase()
        row = (
            db.table("platform_defaults")
            .select("value")
            .eq("key", "default_master_prompt")
            .limit(1)
            .execute()
        )
        raw = (row.data[0].get("value") if row.data else None) or ""
        content = raw.strip() or FALLBACK_PROMPT
    except Exception as e:
        logger.error(f"Failed to load the platform master prompt: {e}")
        content = FALLBACK_PROMPT
    _prompt_cache[_MASTER_CACHE_KEY] = (now, content)
    return content


def invalidate_prompt_cache() -> None:
    _prompt_cache.clear()


_CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "instagram": "Instagram",
    "facebook": "Facebook Messenger",
}


def _build_base_prompt(channel: str, tenant_id: str | None) -> str:
    """Assemble the developer-owned master prompt with the channel label and the
    client-owned business description.

    The master prompt is platform-wide -- one text, identical for every tenant, edited
    only under Operator -> Master Prompt. It defines HOW to behave; the description
    (client's Knowledge Base page) defines WHO the assistant is and what the business
    sells, and is the only part that varies per tenant. The description is always
    injected in full and never goes through RAG -- a retrieval miss would leave the
    assistant with no role at all.

    The channel label is appended unconditionally rather than substituted into a
    placeholder, so it works regardless of how the developer writes the master text.
    """
    prompt = get_master_prompt()
    prompt += f"\n\nCHANNEL: You are replying over {_CHANNEL_LABELS.get(channel, channel)}."

    description = (get_setting("business_description", tenant_id=tenant_id) or "").strip()
    if description:
        prompt += "\n\nBUSINESS DESCRIPTION:\n" + description

    prompt += _handover_rule_block(tenant_id)
    prompt += (
        "\n\nNEVER write a placeholder like \"[Insert Link Here]\" or \"[link]\" in a reply. "
        "If you need a link you don't have, follow the HANDOVER RULE instead of inventing one."
    )

    return prompt


_URL_IN_TEXT_RE = re.compile(r"https?://[^\s)>\]\"']+")


def business_app_link(tenant_id: str | None) -> str:
    """The business's app or booking link: the first link written in its Description. The
    Description is the one place for it (a separate app-link field could disagree with it)."""
    description = get_setting("business_description", tenant_id=tenant_id) or ""
    found = _URL_IN_TEXT_RE.search(description)
    return found.group(0).rstrip(".,;:!?") if found else ""


def _handover_line(tenant_id: str | None) -> str:
    """The client's own words for "I can't help with this here": the 8th Description
    section (business_profile.get_handover_line, which owns the legacy-setting fallback).
    Empty means the client hasn't set one and the platform default applies."""
    from app.services.business_profile import get_handover_line

    return get_handover_line(tenant_id)


def _handover_rule_block(tenant_id: str | None) -> str:
    """One place that decides what the AI says when it can't answer or a human is
    asked for. Every other block (knowledge, campaign, missing link, escalation, the
    master prompt) points here instead of hardcoding its own wording.

    The model brings a person in with the hand_to_human tool (offered to every reply,
    see deal_turn.converse_once), which alerts the team in the inbox, so the default
    wording is the truth: the team replies here. A client's own handover line replaces
    that wording."""
    line = _handover_line(tenant_id)
    action = (
        "when you cannot answer from the information you have, or the customer asks for a "
        "person, call hand_to_human. That alerts a person on this team, who replies in this "
        "same chat. If they asked for something you do not have but you have a close real "
        "alternative (a similar product, a custom order, a consultation), offer it warmly first. "
    )
    if line:
        return (
            f"\n\nHANDOVER RULE (this business's own instruction): {action}"
            "Tell the customer this business's own words for it, in the customer's language: "
            f"\"{line}\". Say it once. Do not say anyone will contact them unless that line "
            "says so, and never promise a time or a named person."
        )
    return f"\n\nHANDOVER RULE: {action}" + (
        "Tell the customer, in your own words, that you are checking with the team and they "
        "will reply here. Never promise a time, a callback or a named person."
    )


def _recent_thread(db, lead_id: str, limit: int = 6, *, tenant_id: str | None = None) -> list[dict]:
    # Fetch extra rows so we can filter out [Template] messages without falling short of the requested limit
    query = db.table("messages").select("direction,content,created_at,interactive_id").eq("lead_id", str(lead_id))
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    raw = query.order("created_at", desc=True).limit(limit + 10).execute().data or []
    filtered = [
        r for r in raw
        if not (r.get("content") or "").strip().startswith("[Template")
    ]
    return filtered[:limit]

_FALLBACK_BY_LANG = {
    "ta": "நன்றி! உங்கள் விசாரணைக்கு விரைவில் பதிலளிப்போம்.",
    "hi": "धन्यवाद! हम जल्द ही आपसे संपर्क करेंगे।",
    "te": "ధన్యవాదాలు! మేము త్వరలో మీకు తిరిగి వస్తాము.",
    "kn": "ಧನ್ಯವಾದಗಳು! ನಾವು ಶೀಘ್ರದಲ್ಲೇ ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತೇವೆ.",
    "ml": "നന്ദി! ഞങ്ങൾ ഉടൻ തന്നെ നിങ്ങളുമായി ബന്ധപ്പെടും.",
    "en": "Thank you for reaching out! We'll get back to you shortly.",
    "tanglish": "Nandri! Naanga seekiram ungale contact pandrom.",
}

# Common Tamil words/suffixes seen in Tanglish (Tamil written in Latin letters).
# Pure Unicode-block detection can't tell Tanglish apart from English since both
# use the Latin script - this closes that gap with a curated keyword heuristic.
_TANGLISH_MARKERS = frozenset({
    "nalla", "romba", "seri", "vanga", "vaanga", "sollunga", "solunga",
    "pannunga", "panren", "panniten", "pannitu", "pannanum", "panna",
    "venum", "vendum", "irukku", "irukka", "iruken", "illa", "illai",
    "epdi", "eppadi", "eppo", "yaaru", "yaru", "enna", "yenna", "kandippa",
    "unga", "ungal", "naanga", "namma", "kekkanum", "paakanum", "paakalam",
    "paathu", "poganum", "poyitu", "irundha", "vela", "jaadhagam",
    "jadhagam", "jothidam", "kalyanam", "thirumanam", "nanba", "nanban",
    "machi", "aiyo", "dhan", "thaan", "nu", "pa", "da",
})


def _dominant_script(text: str) -> str:
    """Return dominant script code based on Unicode block frequency alone
    (no keyword heuristics -- this half of the detection is deterministic
    and reliable, unlike the Tanglish-vs-English guess in _detect_lang)."""
    if not text:
        return "en"
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        if 0x0B80 <= cp <= 0x0BFF:
            counts["ta"] = counts.get("ta", 0) + 1
        elif 0x0C00 <= cp <= 0x0C7F:
            counts["te"] = counts.get("te", 0) + 1
        elif 0x0C80 <= cp <= 0x0CFF:
            counts["kn"] = counts.get("kn", 0) + 1
        elif 0x0D00 <= cp <= 0x0D7F:
            counts["ml"] = counts.get("ml", 0) + 1
        elif 0x0900 <= cp <= 0x097F:
            counts["hi"] = counts.get("hi", 0) + 1
        elif ch.isalpha() and cp < 128:
            counts["en"] = counts.get("en", 0) + 1
    return max(counts, key=counts.__getitem__) if counts else "en"


def _detect_lang(text: str) -> str:
    """Return dominant language code based on Unicode block frequency,
    falling back to a Tanglish keyword heuristic when the script is pure Latin."""
    dominant = _dominant_script(text)
    if dominant == "en":
        tokens = set(re.findall(r"[a-zA-Z']+", text.lower()))
        if tokens & _TANGLISH_MARKERS:
            return "tanglish"
    return dominant


_SCRIPT_NAMES = {"ta": "Tamil", "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "hi": "Hindi"}


def _latest_message_script_note(text: str) -> str:
    """Per-turn instruction stating the customer's latest message script. Live-tested
    2026-07-13: does NOT fix silent script switches (0/6 across two prompt placements,
    see subsystem-notes.md) -- the model overrides this instruction in favor of its own
    prior reply style. Kept because it's harmless and doesn't regress the cases that
    already work (explicit switch requests, no-switch). The actual fix for silent
    switches is the post-reply check below (_reply_script_mismatch + regen)."""
    name = _SCRIPT_NAMES.get(_dominant_script(text))
    if name:
        return f"{name} script. Reply in {name} script."
    return "Latin/English script. Do not reply in Tamil script."


_LANGUAGE_SWITCH_REQUEST_RE = re.compile(
    r"\b(in\s+(english|tamil|hindi|telugu|kannada|malayalam)\b"
    r"|reply\s+in\s+(english|tamil|hindi|telugu|kannada|malayalam)\b"
    r"|(english|tamil|hindi|telugu|kannada|malayalam)[\s-]?la\s+(sollunga|solunga|solu))",
    re.IGNORECASE,
)


# The Latin-script pattern above cannot match a request written in Tamil script
# ("தமிழ்ல பேசுங்க"), which is the ONLY thing that may flip tanglish_escalate_tamil
# (tenant decision 2026-08-13: a lead merely answering in Tamil script is not a
# request and must keep getting Tanglish).
_TAMIL_SCRIPT_REQUEST_RE = re.compile(
    r"தமிழ"                                    # the word "Tamil" ...
    r"[^\n]{0,20}?"                            # ... within the same clause as ...
    r"(சொல்|பேசு|எழுது|அனுப்பு|ரிப்ளை|மட்டும்)"  # ... a say/speak/write/send/only verb
)


def _is_tamil_script_language_request(text: str) -> bool:
    """True only for an explicit 'speak Tamil' request written in Tamil script."""
    return bool(_TAMIL_SCRIPT_REQUEST_RE.search(text))


def _is_explicit_language_switch_request(text: str) -> bool:
    """Matches the same trigger phrasing already given to the model in the LANGUAGE
    RULE prompt (e.g. 'in English please', 'tamil-la sollunga', 'reply in tamil').
    Live-tested 3/3 reliable when the model handles this itself -- the mismatch check
    below must not second-guess it, or it would force a wrong regeneration."""
    return bool(_LANGUAGE_SWITCH_REQUEST_RE.search(text))


def _reply_script_mismatch(customer_message: str, reply_text: str) -> bool:
    """True if the reply's script bucket (Indic vs Latin) doesn't match the customer's
    latest message, and the customer wasn't explicitly requesting a different language
    (that case already works and must be left alone). This is the post-reply catch for
    the silent-switch bug that preemptive prompt instructions could not fix -- see
    subsystem-notes.md 2026-07-13."""
    if _is_explicit_language_switch_request(customer_message):
        return False
    customer_is_indic = _dominant_script(customer_message) != "en"
    reply_is_indic = _dominant_script(reply_text) != "en"
    return customer_is_indic != reply_is_indic


def _regen_target_instruction(customer_message: str) -> str:
    """Target-language phrasing for the isolated regen call below. Must name the
    actual language explicitly ('English or Tanglish') rather than 'Latin script' --
    live-tested 2026-07-13: a vague 'Latin/English script' instruction let the model
    drift into literal Latin (the dead language) once, since any Latin-alphabet
    output technically satisfies 'not Tamil script'."""
    name = _SCRIPT_NAMES.get(_dominant_script(customer_message))
    if name:
        return f"natural {name} script (the way a customer service agent in India would text)"
    return (
        "natural English or Tanglish (the way a customer service agent in India would "
        "text over WhatsApp) -- never a foreign or unrelated language"
    )


# Fixed regen target per forced reply_language_mode -- unlike mirror mode, these modes
# don't take their target from the customer's script, so the mismatch check below can't
# reuse _reply_script_mismatch/_regen_target_instruction (both keyed off the customer's
# message). tanglish_escalate_tamil never appears here: build_reply_system_prompt already
# resolves it to "tamil" or "tanglish" before this point.
_FORCED_MODE_TARGET_INSTRUCTION = {
    "tanglish": (
        "natural Tanglish (Tamil words spelled in English letters, e.g. 'eppo varuvinga', "
        "'jaadhagam paakanum', the way a Tamil customer-service agent casually texts on "
        "WhatsApp) -- not Tamil script, not formal English"
    ),
    "english": "natural English",
    "tamil": "natural Tamil script (the way a Tamil customer-service agent would text)",
}


def _forced_mode_script_mismatch(mode: str, reply_text: str) -> bool:
    """True if reply_text's script doesn't match this tenant's forced reply_language_mode.
    Same Indic-vs-Latin bucket _reply_script_mismatch uses, except the target comes from
    the forced mode instead of the customer's script. Live evidence 2026-08-31: a tenant
    on 'tanglish' got one native-Tamil-script reply mid-conversation (the LANGUAGE STYLE
    prompt instruction alone doesn't reliably hold, same failure class as the mirror-mode
    silent switch this file already documents) -- and it shipped uncaught because the
    regen guard used to only run for mode == 'mirror'."""
    reply_is_indic = _dominant_script(reply_text) != "en"
    if mode == "tamil":
        return not reply_is_indic
    if mode in ("tanglish", "english"):
        return reply_is_indic
    return False


_LANGUAGE_MODES = {"mirror", "tanglish", "english", "tamil", "tanglish_escalate_tamil"}


def _should_lock_tamil(message: str) -> bool:
    """Both conditions required: dominantly Tamil script AND an explicit request to be
    spoken to in Tamil. Script alone is not enough -- a lead answering a question in
    Tamil script still gets Tanglish (tenant decision 2026-08-13). A romanized request
    ("tamil sollunga") is not enough either: the request must itself be in Tamil."""
    return _dominant_script(message) == "ta" and _is_tamil_script_language_request(message)


def record_tamil_lock_request(db, lead_id: str, tenant_id: str | None, message: str) -> bool:
    """Persist leads.tamil_locked when a lead asks, in Tamil script, to be spoken to in
    Tamil. Called from the webhook BEFORE any flow that can consume the turn
    (route_intake), because generate_reply -- where this check used to live alone --
    never runs on a consumed turn. Live evidence 2026-08-12: a lead sent four
    Tamil-script messages during an intake session and tamil_locked stayed false
    throughout. Returns True only when the lock was newly written."""
    if _resolve_reply_language_mode(tenant_id) != "tanglish_escalate_tamil":
        return False
    if not _should_lock_tamil(message):
        return False
    try:
        db.table("leads").update({"tamil_locked": True}).eq("id", str(lead_id)).execute()
    except Exception:
        logger.exception("Failed to persist tamil_locked for lead %s", lead_id)
        return False
    logger.info("Tamil lock set for lead %s", lead_id)
    return True


def _resolve_tamil_lock(
    db, lead_id: str, lead_data: dict, message: str, *, persist: bool = True
) -> str:
    """For the 'tanglish_escalate_tamil' mode: returns 'tamil' once this lead has asked
    (in Tamil script) to be spoken to in Tamil, persisted via leads.tamil_locked since
    the _recent_thread() history window used for the LLM prompt is only 8 messages and
    can't be trusted to remember a switch from many turns ago. Returns 'tanglish'
    otherwise. The write here is the belt-and-braces path for turns that reach
    generate_reply directly; record_tamil_lock_request covers consumed turns.
    persist=False computes the same answer in memory without writing (read-only callers)."""
    if lead_data.get("tamil_locked"):
        return "tamil"
    if _should_lock_tamil(message):
        if persist:
            try:
                db.table("leads").update({"tamil_locked": True}).eq("id", str(lead_id)).execute()
            except Exception:
                logger.exception("Failed to persist tamil_locked for lead %s", lead_id)
        return "tamil"
    return "tanglish"


def _resolve_reply_language_mode(tenant_id: str | None) -> str:
    """Per-tenant override of the default mirror-the-lead's-language behavior, set via
    the operator console (config.tsx). Falls back to 'mirror' for any tenant that hasn't
    configured it, or for an unrecognized stored value. The console offers five modes:
    mirror, tanglish, english, tamil, and tanglish_escalate_tamil."""
    mode = get_setting("reply_language_mode", fallback="mirror", tenant_id=tenant_id) or "mirror"
    return mode if mode in _LANGUAGE_MODES else "mirror"


# How to write Tanglish well. Lived in the platform master prompt (as rule 9) until
# 2026-09-24; moved here so it rides with the language setting: every client whose
# setting can produce Tanglish gets it, and the master prompt stays language-neutral.
# Declarative wording on purpose -- see the _language_rule_block docstring.
_TANGLISH_STYLE_GUIDE = (
    "\n\nTANGLISH STYLE (whenever you reply in Tanglish): write natural, simple, everyday "
    "Tanglish, the way people text on WhatsApp, not translated or literary Tamil and not "
    "formal customer-service language. Prefer simple words such as puriyudhu, vishayam, "
    "therinjukka, paathu, ketkalaam, sollunga, share pannunga, question, guidance. Avoid "
    "literary words such as soozhnilai, manasthapam, aazhamaaga aaraainthu, thevaiyaana. "
    "Keep common English words in English instead of forcing a Tamil translation."
)


def _language_rule_block(mode: str, message: str) -> str:
    """System-prompt LANGUAGE instruction, branched on this tenant's reply_language_mode.
    The three forced modes use calm/declarative phrasing only -- live-tested 2026-07-17:
    an aggressive 'override everything / no matter what / never' framing reproducibly
    made gpt-5-nano burn its entire token budget on hidden reasoning and return an empty
    reply (0/8 across two prompt variants at the real 600-token production budget), while
    this declarative framing was 100% reliable (12/12 on Gemini 3.1 Flash Lite, across
    English, Tamil-script, and Tanglish input) at the same budget. Do not "strengthen"
    this wording without re-running that test."""
    if mode == "tanglish":
        return (
            "\n\nLANGUAGE STYLE: Your reply style is always Tanglish -- Tamil words spelled "
            "out in Roman/English letters (e.g. 'eppo varuvinga', 'jaadhagam paakanum'), the "
            "way a Tamil customer-service agent casually texts on WhatsApp. Use this Tanglish "
            "style for every reply, even when the customer writes in English or in Tamil script."
        ) + _TANGLISH_STYLE_GUIDE
    if mode == "english":
        return (
            "\n\nLANGUAGE STYLE: Always reply in English only, regardless of what language or "
            "script the customer's message is in -- English, Tamil script, or Tanglish."
        )
    if mode == "tamil":
        return (
            "\n\nLANGUAGE STYLE: Always reply in native Tamil script, regardless of what "
            "language or script the customer's message is in -- English, Tamil script, or "
            "Tanglish."
        )
    return (
        "\n\nLANGUAGE RULE: Reply in the SAME language style the user just wrote in. "
        "Tamil script -> reply in Tamil script. English -> reply in English. "
        "Tanglish (Tamil words spelled in English letters, e.g. 'eppo varuvinga', 'jaadhagam paakanum') "
        "-> reply in Tanglish too - do NOT convert it to pure Tamil script or to formal English. "
        "If the customer's latest message explicitly requests a different language (e.g. 'in English please', "
        "'tamil-la sollunga', 'reply in tamil'), you MUST fully switch to that requested language for this "
        "reply and continue in it afterward, overriding whatever style earlier messages in the conversation used."
    ) + _TANGLISH_STYLE_GUIDE + f"\n\nCUSTOMER'S LATEST MESSAGE SCRIPT: {_latest_message_script_note(message)}"


# NOTE: the hardcoded ACCURACY RULE was removed 2026-07-20 (operator decision). It
# previously banned stating any price/fee/payment method and forced a "I'll connect you
# with the team" answer for anything outside the knowledge base, for every client. It was
# removed so each client's master prompt can decide how to handle pricing. Consequence:
# there is no longer a platform-wide anti-invention guard -- each client's master prompt
# must carry its own ("never invent prices, dates, predictions, or guarantees"), or that
# client's AI may state a plausible-sounding number it made up.


_LAST_SEND_ERROR: str | None = None


def get_last_send_error() -> str | None:
    return _LAST_SEND_ERROR


async def send_whatsapp_voice_reply(
    to_phone: str,
    message: str,
    tenant_id: str | None = None,
    phone_number_id: str | None = None,
    speaker: str | None = None,
    db=None,
) -> str | None:
    try:
        from app.services.gemini_client import gemini_text_to_speech, DEFAULT_GEMINI_VOICE
        from app.services.meta_cloud import upload_media_to_meta, send_media_message

        # Gemini's TTS is LLM-native and handles raw Roman-script Tanglish correctly with
        # no language hint (live-tested 2026-07-13/14, see subsystem-notes.md -- Sarvam
        # Bulbul mispronounced the same text as North-Indian-accented regardless of the
        # target_language_code it was given), so there's no pace or language param here --
        # only speaker/voice carries through, using Gemini's own voice names (e.g. "Kore").
        audio_bytes = await gemini_text_to_speech(text=message, voice=speaker or DEFAULT_GEMINI_VOICE, tenant_id=tenant_id)
        if db is not None and tenant_id:
            meter(db, tenant_id, "ai_text_to_speech")
        media_id = await upload_media_to_meta(
            file_bytes=audio_bytes,
            mime_type="audio/mpeg",
            filename="aira-reply.mp3",
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
        )
        data = await send_media_message(
            to_number=to_phone,
            media_id=media_id,
            wa_type="audio",
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
        )
        mid = (data.get("messages") or [{}])[0].get("id")
        logger.info(f"Meta voice reply sent to {to_phone}: id={mid}")
        return mid
    except Exception as e:
        logger.error(f"WhatsApp voice reply failed to {to_phone}: {e}")
        return None


async def send_whatsapp(
    to_phone: str,
    message: str,
    tenant_id: str | None = None,
    phone_number_id: str | None = None,
    reply_to_message_id: str | None = None,
) -> str | None:
    """Send a WhatsApp message via Meta Cloud API. Returns message ID or None on failure.

    phone_number_id pins the sending number to the one that received the inbound
    message; when None, meta_cloud falls back to the tenant's default.
    reply_to_message_id quotes the given inbound message in the WhatsApp bubble --
    only passed when the reply is answering an older message out of order (see
    generate_reply's burst check).
    """
    global _LAST_SEND_ERROR
    try:
        from app.services.meta_cloud import send_text_message
        data = await send_text_message(
            to_number=to_phone,
            text=message,
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
            reply_to_message_id=reply_to_message_id,
        )
        mid = (data.get("messages") or [{}])[0].get("id")
        logger.info(f"Meta sent to {to_phone}: id={mid}")
        _LAST_SEND_ERROR = None
        return mid
    except Exception as e:
        err_msg = str(e)
        # Surface Meta's actual error body so the UI can show it
        from fastapi import HTTPException as _HTTP
        if isinstance(e, _HTTP):
            err_msg = str(e.detail)[:500]
        _LAST_SEND_ERROR = err_msg
        logger.error(f"Meta send failed to {to_phone}: {err_msg}")
        if tenant_id:
            try:
                from app.services.notify import notify_user
                from app.db.supabase import get_supabase
                db = get_supabase()
                owner = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").limit(1).execute()
                owner_uid = (owner.data[0] if owner.data else {}).get("user_id")
                if owner_uid:
                    notify_user(
                        tenant_id,
                        owner_uid,
                        "system_error",
                        "System API Failure",
                        f"WhatsApp Cloud API send failed: {err_msg}",
                        db=db,
                        dedupe_lead_id="whatsapp_send_failed",
                    )
            except Exception as notify_err:
                logger.warning(f"Failed to notify owner of API failure: {notify_err}")
        return None

async def send_instagram(ig_user_id: str, message: str, tenant_id: str | None = None) -> str | None:
    """Send an Instagram DM via Facebook Graph API (Messenger Platform for Instagram).
    Uses Page Access Token — requires pages_messaging + instagram_manage_messages scope.
    """
    from app.config_dynamic import get_setting
    access_token = get_setting("instagram_access_token", tenant_id=tenant_id)
    if not access_token:
        logger.error(f"instagram_access_token not configured for tenant {tenant_id} — cannot send Instagram DM")
        return None
    try:
        url = "https://graph.facebook.com/v21.0/me/messages"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                params={"access_token": access_token},
                json={
                    "recipient": {"id": ig_user_id},
                    "message": {"text": message},
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            mid = data.get("message_id")
            logger.info(f"Instagram sent to {ig_user_id}: mid={mid}")
            return mid
    except httpx.HTTPStatusError as e:
        logger.error(f"Instagram send failed to {ig_user_id}: {e.response.status_code} {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Instagram send failed to {ig_user_id}: {e}")
        return None


async def send_telegram(tg_user_id: str, message: str, tenant_id: str | None = None) -> str | None:
    """Send a Telegram message via Bot API. Returns message ID (as string) or None on failure."""
    from app.config_dynamic import get_setting
    bot_token = get_setting("telegram_bot_token", tenant_id=tenant_id)
    if not bot_token:
        logger.error(f"telegram_bot_token not configured for tenant {tenant_id} — cannot send Telegram DM")
        return None
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": tg_user_id,
                    "text": message,
                },
                timeout=15.0,
            )
            if resp.status_code != 200:
                try:
                    desc = resp.json().get("description", resp.text)
                except Exception:
                    desc = resp.text
                logger.error(f"Telegram API send error ({resp.status_code}) to {tg_user_id}: {desc}")
                # 401 = the bot token itself is invalid/revoked → surface in Settings.
                # 403 ("bot was blocked by the user") is per-recipient, NOT a token problem — never flag it.
                if resp.status_code == 401 and tenant_id:
                    try:
                        from app.services.incidents import create_token_incident
                        create_token_incident(get_supabase(), tenant_id, "telegram", desc or "Telegram token invalid")
                    except Exception as inc_err:
                        logger.error(f"Failed to record Telegram token incident: {inc_err}")
                return None
            data = resp.json()
            mid = str(data.get("result", {}).get("message_id"))
            logger.info(f"Telegram sent to {tg_user_id}: mid={mid}")
            return mid
    except httpx.RequestError as req_err:
        logger.error(f"Telegram network send error to {tg_user_id}: {req_err}")
        return None
    except Exception as e:
        logger.error(f"Telegram send failed to {tg_user_id}: {e}")
        return None


async def send_facebook(fb_user_id: str, message: str, tenant_id: str | None = None) -> str | None:
    """Send a Facebook Messenger message via Graph API. Returns message id or None on failure."""
    from app.config_dynamic import get_setting
    access_token = get_setting("facebook_access_token", tenant_id=tenant_id)
    if not access_token:
        logger.error(f"facebook_access_token not configured for tenant {tenant_id} — cannot send Facebook DM")
        return None
    try:
        url = "https://graph.facebook.com/v21.0/me/messages"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                params={"access_token": access_token},
                json={
                    "recipient": {"id": fb_user_id},
                    "message": {"text": message},
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            mid = data.get("message_id")
            logger.info(f"Facebook sent to {fb_user_id}: mid={mid}")
            return mid
    except httpx.HTTPStatusError as e:
        logger.error(f"Facebook send failed to {fb_user_id}: {e.response.status_code} {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Facebook send failed to {fb_user_id}: {e}")
        return None


async def generate_reengagement_message(lead_id: str, cadence: str, db=None) -> str:
    db = db or get_supabase()
    lead = (
        db.table("leads")
        .select("name,segment,tenant_id")
        .eq("id", str(lead_id))
        .limit(1)
        .execute()
    )
    lead_data = lead.data[0] if lead.data else {}
    tenant_id = lead_data.get("tenant_id")
    history_rows = list(reversed(_recent_thread(db, lead_id, limit=6, tenant_id=tenant_id)))
    history = "\n".join(
        f"{row.get('direction', 'unknown')}: {row.get('content', '').strip()}"
        for row in history_rows
        if (row.get("content") or "").strip()
    ) or "No prior conversation history available."

    prompt = f"""You write proactive WhatsApp re-engagement messages for a business.

Cadence: {cadence}
Lead name: {lead_data.get("name") or "there"}
Current segment: {lead_data.get("segment") or "C"}
Recent conversation:
{history}

Write a single WhatsApp message under 280 characters.
Be warm, specific, and low-pressure.
Reference the lead's interest naturally and end with one clear next step.
Do not use markdown or quotes."""
    try:
        text = await _llm_complete(prompt, max_tokens=120, tenant_id=tenant_id)
        return text[:280] if len(text) > 280 else text
    except Exception as e:
        logger.error(f"Re-engagement copy failed for lead {lead_id}: {e}")
        return REENGAGEMENT_FALLBACKS.get(cadence, "Hi! Just checking in — happy to help if you have any questions.")


async def generate_silence_nudge(lead_id: str, db=None) -> str:
    """One short line for a lead who went quiet minutes after a live AI reply.

    Deliberately does NOT go through _build_base_prompt(): that carries catalog
    context, and commits 24494b3d and 5716c840 both fixed link/catalog leaks
    into outbound copy. Keep this prompt self-contained and link-free.
    """
    from app.services.silence_nudge import SILENCE_NUDGE_FALLBACK

    db = db or get_supabase()
    lead = (
        db.table("leads")
        .select("name,tenant_id")
        .eq("id", str(lead_id))
        .limit(1)
        .execute()
    )
    lead_data = lead.data[0] if lead.data else {}
    tenant_id = lead_data.get("tenant_id")

    history_rows = list(reversed(_recent_thread(db, lead_id, limit=6, tenant_id=tenant_id)))
    history = "\n".join(
        f"{row.get('direction', 'unknown')}: {row.get('content', '').strip()}"
        for row in history_rows
        if (row.get("content") or "").strip()
    ) or "No prior conversation history available."
    latest_inbound = next(
        (row.get("content") or "" for row in reversed(history_rows) if row.get("direction") == "inbound"), "",
    )
    # The same LANGUAGE block live replies get: without it the English prompt below made
    # Tanglish tenants' nudges English (Astro Tamil, 2026-09-28).
    language_rule = _language_rule_block(_resolve_reply_language_mode(tenant_id), latest_inbound)

    prompt = f"""A customer was mid-conversation with a business on WhatsApp and has gone quiet.
Write ONE short line checking in on them.

Customer name: {lead_data.get("name") or "there"}
Recent conversation:
{history}

Rules:
- Under 160 characters. One sentence.
- No greeting — the conversation is already open.
- Refer naturally to whatever was just being discussed.
- Offer to help further. Low pressure, never pushy.
- NEVER include links, URLs, prices, discounts, or new offers.
- No markdown, no quotes, at most one emoji.{language_rule}"""

    try:
        text = await _llm_complete(prompt, max_tokens=60, tenant_id=tenant_id)
        text = " ".join((text or "").split())
        if not text:
            return SILENCE_NUDGE_FALLBACK
        return text[:160]
    except Exception as e:
        logger.error(f"Silence nudge copy failed for lead {lead_id}: {e}")
        return SILENCE_NUDGE_FALLBACK


_AI_ESCALATION_RE = re.compile(
    r"""
    (
        # Group 1: Action/Verb followed by Noun (with verb tense suffix support)
        \b(connect|inform|ask|request|transfer|escalat|forward|assign|hand\s+over|refer|alert|confirm|check)\w*\s+(?:[^.?!]*?\s+)?(?:team|owner|admin|staff|human|person|agent|representative|expert|colleague)\b
        |
        # Group 2: Noun followed by action/verb
        \b(?:team|owner|admin|staff|human|person|agent|representative|expert|colleague)\s+(?:[^.?!]*?\s+)?(?:will|would|shall|can|should|is\s+going\s+to)\s+(?:[^.?!]*?\s+)?(?:contact|reach|get\s+back|assist|follow\s+up|connect|call|message|respond|help|take\s+over|write)\w*\b
        |
        # Group 3: Common phrases/actions
        \b(?:get\s+back\s+to\s+you|get\s+in\s+touch|reach\s+out\s+to\s+you|contact\s+you\s+shortly)\b
        |
        \b(?:escalat\w*\s+(?:[^.?!]*?\s+)?(?:query|request|ticket|issue|case))\b
        |
        # Group 4: Tamil script -- AI indicates a team/expert will connect or follow up.
        # No \b boundaries here (see _HUMAN_REQUEST_RE's native-script section above for
        # why -- Unicode combining marks make \b unreliable on Indic script).
        (?:குழு(?:வுடன்|வினர்|வினுடன்)?|அணியினர்|நிபுணர்|ஆலோசகர்)[^.?!]{0,25}(?:இணைக்க|தொடர்பு\s*கொள்|அனுப்ப|பேசு)\w*
        |
        (?:இணைக்கிறேன்|இணைக்கிறோம்|இணைப்போம்|தொடர்பு\s*கொள்வோம்|தொடர்பு\s*கொள்கிறோம்|தொடர்பு\s*கொள்கிறேன்)
        |
        # Group 5: Tanglish -- Tamil verb-final grammar puts the noun BEFORE the verb
        # stem, often joined by a postposition (kooda/oda/kitta), not English word order
        # (verb-then-noun, or noun-then-modal-then-verb) that Groups 1-2 expect. Live-
        # tested 2026-07-17: 3/3 real Tanglish escalation replies from Gemini used this
        # shape ("team-kooda connect panren") and Groups 1-2 missed all three.
        \b(?:team|staff|group|owner|admin|human|person|agent|representative|expert|colleague)[\s-]*(?:kooda|oda|kitta)?\s*(?:connect|contact|transfer|refer|escalat)\w*\s*(?:pan\w*|irukk\w*|vendiyadhu|solren|solluven|soll\w*)\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_HUMAN_REQUEST_RE = re.compile(
    r"""
    # 1. English Verb + Noun patterns (e.g. speak to owner, talk with team, contact support)
    \b(?:talk|speak|chat|connect|contact|call|get|find|meet|reach|confirm|check)\s+(?:(?:to|with|your|our|my|a|an|the|some|any|this|that|us|me)\s+){0,3}(?:human|person|agent|someone|representative|staff|team|owner|boss|admin|manager|support|caller|telecaller|executive|sir|maam)\b
    |
    # 2. English Pronoun + Action (e.g. connect me, call me, contact me)
    \b(?:call|contact|connect)\s+(?:me|us)\b
    |
    # 3. Romanized Indian / Tanglish / Hinglish / Tenglish noun + regional verb
    \b(?:human|person|agent|team|owner|boss|admin|manager|support|caller|telecaller|sir|maam|insan|aadmi|banda|officer|staff)
        [\s\-]+(?:(?:kitta|se|ku|sath|thru|through|to|with|your|our|my|a|an|the|some|any|ko)\s+){0,2}
        (?:pesa|pesu|baat|kar|karv|karn|call|contact|connect|matlad|mathad|samsar)\w*
    |
    # Standalone Romanized verbs / phrases
    \b(?:pesanum|pesunga|pesalaam|pesanom|pesala|pesu|pesa)\b
    |
    \b(?:matladali|matladandi|matladaali|matladu)\b
    |
    \b(?:mathadabeku|mathadi|mathadu)\b
    |
    \b(?:samsarikkanam|samsarikkoo)\b
    |
    # Direct common Hinglish/Tanglish phrases (e.g. call pannunga, contact karo)
    \b(?:call|contact|connect)\s+(?:pannu|pannunga|karo|karwao|chey|cheyandi|madi|cheyyoo)\b
    |
    \bbaat\s+(?:kar|karna|karvao|karwao|krni|karni|kro)\b
    |
    \bpesa\s+(?:mudiyuma|venum|num)\b
    |
    # 4. Short/Single Word Overrides (case-insensitive boundary checks)
    \b(?:human\s+agent|real\s+person|live\s+agent|customer\s+(?:care|support|service))\b
    |
    \b(?:agent|admin|support|representative|telecaller|caller)\b
    |
    # 5. Native regional scripts (Tamil, Hindi, Telugu, Kannada, Malayalam)
    # Tamil
    பேச\s+(?:வேண்டும்|வேணும்|முடியுமா)|பேசணும்|பேசுங்க|பேசலாமா|அழைக்கவும்|தொடர்பு\s+கொள்ளவும்
    |
    # Hindi
    बात\s+(?:करनी|करवाओ|करो|करना)|कॉल\s+करो|सम्पर्क\s+करो
    |
    # Telugu
    మాట్లాడాలి|మాట్లాడండి|కాల్\s+చేయండి
    |
    # Kannada
    ಮಾತನಾಡಬೇಕು|ಮಾತನಾಡಿ|ಕಾಲ್\s+ಮಾಡಿ
    |
    # Malayalam
    സംസാരിക്കണം|വിളിക്കൂ
    """,
    re.VERBOSE | re.IGNORECASE,
)

_GENERIC_FALLBACK_MARKERS = [
    "we'll get back to you shortly",
    "get back to you shortly",
    "team will get back to you",
]

_TRIGGER_PRIORITY = ["C", "B", "A", "D", "F"]
_TRIGGER_REASONS: dict[str, str] = {
    "C": "User requested a human agent",
    "B": "AI failed to generate a response",
    "A": "AI gave a generic fallback reply",
    "D": "User repeated the same question",
    "F": "AI indicated team will follow up",
}


def _is_similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """True if two messages share ≥threshold fraction of words (rough duplicate check)."""
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if len(wa) < 3 or len(wb) < 3:
        return False
    return len(wa & wb) / max(len(wa), len(wb)) >= threshold


def _is_generic_fallback(text: str) -> bool:
    t = text.lower()
    return any(marker in t for marker in _GENERIC_FALLBACK_MARKERS)


def _trigger_chat_escalation(
    lead_id: str, reason: str, tenant_id: str, assigned_to: str | None, db,
) -> None:
    """Create a pending chat handover into the shared escalation pool.

    The handover is NOT auto-assigned to a telecaller — it lands unassigned and
    is visible to the admin inbox + every telecaller inbox, so whoever is free
    picks it up. `assigned_to` only carries the lead's existing owner, if any.
    """
    existing = (
        db.table("chat_handovers")
        .select("id")
        .eq("lead_id", lead_id)
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    if existing and existing.data:
        return  # already has an open handover

    # NOTE: ai_enabled is deliberately NOT touched here. The AI stays live for
    # the whole handover so an escalated customer is never met with silence —
    # see _escalation_prompt_block for how its replies change. `ai_enabled` is
    # a manual admin control only.
    db.table("leads").update({
        "needs_human_attention": True,
        "escalation_reason": reason,
    }).eq("id", lead_id).execute()

    handover_res = db.table("chat_handovers").insert({
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "assigned_to": assigned_to,
        "reason": reason,
        "status": "pending",
    }).execute()
    handover_id = handover_res.data[0]["id"] if (handover_res and handover_res.data) else "Unknown"
    logger.info(f"Chat handover created for lead {lead_id} — reason: {reason[:60]}")
    try:
        from app.services.notify import notify_pool
        lead_row = (
            db.table("leads").select("name").eq("id", lead_id).maybe_single().execute()
        )
        lead_name = (lead_row.data or {}).get("name") if lead_row else None
        notify_pool(
            tenant_id,
            "handover_new",
            "New handover in pool",
            f"Lead '{lead_name or 'Unknown'}' needs a human — unclaimed. [handover_id:{handover_id}] [lead_id:{lead_id}]",
            db=db,
        )
    except Exception:
        pass

    try:
        from app.services.whatsapp_notify import queue_escalation_whatsapp_alert
        queue_escalation_whatsapp_alert(
            db,
            tenant_id=tenant_id,
            lead_id=lead_id,
            handover_id=handover_id,
            reason=reason,
            assigned_to=assigned_to,
        )
    except Exception:
        logger.exception("Escalation WhatsApp queue failed for lead %s", lead_id)


def _escalation_prompt_block(handover_line: str = "", now=None) -> str:
    """System-prompt section for a lead already waiting on a person: the team was alerted in
    the Inbox and replies in this chat. The team's hours, if the business states them, are in
    its Description; the current time is given so the AI can apply them."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = (now or datetime.now(ZoneInfo("Asia/Kolkata"))).astimezone(ZoneInfo("Asia/Kolkata"))
    when = now.strftime("%A %d %B %Y, %I:%M %p IST")
    wording = (
        f"use this business's own words, in their language, once: \"{handover_line}\". "
        if handover_line else "say the team has their request and will reply here. "
    )
    return (
        "\n\nESCALATION CONTEXT:\n"
        "This customer is waiting for a person on this team, who has been alerted and will "
        f"reply in this chat. It is now {when}. If they ask for a person, ask about their "
        f"request, or say nobody has helped them yet, {wording}If they ask when, answer from "
        "the team hours in your description if it gives them; otherwise say the team will reply "
        "as soon as they can.\n"
        "Rules:\n"
        "- Never promise a specific time, a named person, a call or a callback.\n"
        "- Never claim someone has already called or messaged them.\n"
        "- Never say the request was resolved.\n"
        "- Otherwise keep answering their questions normally and helpfully.\n"
    )


def _intake_paid_prompt_block(service_noun: str, *, answer_in_app: bool = False) -> str:
    """System-prompt section for a lead who already paid for a human expert
    session and is waiting to be contacted. Mirrors _escalation_prompt_block's
    "stay live, don't go silent" approach for the Intake flow.

    `answer_in_app` is set for tenants whose expert answers land in their own app
    rather than on WhatsApp (see intake._compose_reply_nudge). Without it the AI
    tells a paying customer their answer is coming to WhatsApp, which for those
    tenants is simply untrue.
    """
    if answer_in_app:
        waiting_rule = (
            "- If they ask when the expert will contact them, or say nobody has "
            "reached out yet: reassure them the expert has been notified, that we "
            "will message them here the moment their answer is ready, and that they "
            "will read the full answer in our app. Do NOT write a link or a URL of "
            "any kind — the app link is sent automatically when the answer is "
            "ready, and a link you invent would send a paying customer nowhere.\n"
        )
    else:
        waiting_rule = (
            "- If they ask when the expert will contact them, or say nobody has "
            "reached out yet: reassure them the expert has been notified and will "
            "be in touch here on WhatsApp soon.\n"
        )
    return (
        f"\n\nPAID {service_noun.upper()} CONTEXT:\n"
        f"This customer has already paid for a one-on-one {service_noun} with our "
        "human expert. A team member has been notified.\n"
        "Rules:\n"
        "- Do NOT attempt to answer their original question yourself — that is "
        "what they paid the human expert for.\n"
        f"- Do NOT offer or re-sell the paid {service_noun} again.\n"
        + waiting_rule +
        "- Never promise a specific time or name a specific person.\n"
        "- Never claim the expert has already contacted them.\n"
        "- Otherwise, keep answering their other questions normally and helpfully.\n"
    )


_CATALOG_RECOMMEND_TOOL = {
    "type": "function",
    "function": {
        "name": "recommend_catalog_item",
        "description": (
            "Recommend a catalog item to the customer and send its image. "
            "Call this whenever you mention a specific product/service from the catalog in your reply "
            "— the system will automatically send the item's photo alongside your text. "
            "Only call for items the customer has shown genuine interest in. Do NOT call more than once per reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "The UUID of the catalog item to recommend",
                }
            },
            "required": ["item_id"],
        },
    },
}

_SEND_QUOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "send_quote",
        "description": (
            "Send a formal price quote with a payment link for one or more catalog items the "
            "customer has clearly decided to buy -- not just shown interest in. The exact prices "
            "are read from the catalog, never invented. Only call this when the customer has "
            "confirmed what they want and is ready to pay; use recommend_catalog_item instead for "
            "browsing or answering 'how much is X'. If the item or the quantity is not clear, ask the "
            "customer first instead of calling this. Do NOT call for an item marked OUT OF STOCK."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UUIDs of the catalog items the customer wants to buy",
                },
                "quantities": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Quantity for each item_id, same order and length as item_ids. Omit for 1 each.",
                },
            },
            "required": ["item_ids"],
        },
    },
}


def _intake_in_progress_prompt_block(service_noun: str) -> str:
    """System-prompt section for a lead who is mid-way through the paid intake flow
    -- past the offer, not yet paid. Live evidence 2026-08-13: a lead corrected a
    field instead of confirming the summary with a plain yes; route_intake correctly
    handed the turn to the AI (that message wasn't a yes), but with no context the AI
    fell back to the business's general knowledge base and told the lead to download
    the app and resubmit there -- abandoning a payment link one message from being
    sent. This block is the guard against that: it fires for ANY in-progress status
    (not just paid), see get_in_progress_session in intake.py."""
    return (
        f"\n\n{service_noun.upper()} IN PROGRESS:\n"
        f"This customer is in the middle of signing up for the paid {service_noun} -- "
        "details are being collected, or a payment link has already been sent and is "
        "waiting on them.\n"
        "Rules:\n"
        "- Do NOT tell them about an app, a website, or any other way to reach an "
        f"expert -- the {service_noun} they already started IS the way.\n"
        f"- Do NOT re-offer or re-describe the paid {service_noun}.\n"
        "- If their message is a question you can answer directly, answer it in one "
        "short sentence, then remind them to reply so the details/payment already in "
        "progress can continue.\n"
    )


def _load_catalog_ai_rules(db, tenant_id: str) -> dict:
    """Read catalog_ai_rules (the client's own preferences, set via the catalog dashboard)
    merged with defaults, then apply the operator's controls on top: ai_media_recommendations_enabled
    is a hard master switch (client's can_recommend has no effect while it's off), and
    catalog_ai_max_images_ceiling caps max_images_per_reply regardless of what the client
    chose -- the client can pick anything under the ceiling, never over it."""
    defaults = {"can_recommend": True, "can_send_images": True, "max_images_per_reply": 3}
    rules = dict(defaults)
    try:
        row = (
            db.table("app_settings")
            .select("value")
            .eq("tenant_id", tenant_id)
            .eq("key", "catalog_ai_rules")
            .limit(1)
            .execute()
        )
        if row.data:
            stored = json.loads(row.data[0]["value"])
            rules = {**defaults, **stored}
    except Exception:
        logger.warning(f"Failed to load catalog_ai_rules for tenant {tenant_id}")

    operator_enabled = get_setting("ai_media_recommendations_enabled", fallback="true", tenant_id=tenant_id) == "true"
    if not operator_enabled:
        rules["can_recommend"] = False

    ceiling_raw = get_setting("catalog_ai_max_images_ceiling", fallback="5", tenant_id=tenant_id) or "5"
    try:
        ceiling = max(0, int(float(ceiling_raw)))
    except (TypeError, ValueError):
        ceiling = 5
    try:
        client_max = int(rules.get("max_images_per_reply", 3))
    except (TypeError, ValueError):
        client_max = 3
    rules["max_images_per_reply"] = min(client_max, ceiling)

    return rules


def catalog_prompt(items: list[dict], directive: str, rules: dict) -> tuple[str, list[dict], dict[str, dict], int]:
    """Pure half of _build_catalog_context: the CATALOG prompt block and tool definitions for
    the given candidate items. Split out so the conversation eval renders exactly this text."""
    if not items and not directive:
        return "", [], {}, 0

    items_by_id = {row["id"]: row for row in items}
    item_lines: list[str] = []
    for row in items:
        # stock_quantity is NULL for anything that isn't a tracked physical
        # product (services, courses) -- NULL always means "available", only
        # an explicit 0 means out of stock.
        out_of_stock = row.get("stock_quantity") == 0
        line = f"  • {row['name']} ({row['item_type']}) [id: {row['id']}]"
        if row.get("price_paise") is not None:
            price_rupees = row["price_paise"] / 100
            price_str = f"₹{price_rupees:.0f}" if price_rupees == int(price_rupees) else f"₹{price_rupees:.2f}"
            if row.get("price_note"):
                price_str += f" ({row['price_note']})"
            line += f" — {price_str}"
        if row.get("description"):
            line += f" — {row['description']}"
        if out_of_stock:
            line += " — OUT OF STOCK: if asked, say so honestly, but do NOT call recommend_catalog_item for this item"
        elif row.get("stock_quantity") is not None:
            line += f" — only {row['stock_quantity']} available right now; never promise more than that"
        item_lines.append(line)

    text_block = ""
    if item_lines:
        text_block = (
            "\n\nCATALOG:\nWhen the customer asks about what's available or shows interest in a type of "
            "product/service, use your catalog below. Mention items by name — and when you do, call the "
            "recommend_catalog_item tool with the item's [id] so the customer receives its photo automatically. "
            "Never call that tool for an item marked OUT OF STOCK. When the customer says they want to "
            "buy an item and the item and quantity are clear, call send_quote in that same reply -- do "
            "not ask for permission to send the link.\n"
            + "\n".join(item_lines)
        )
    text_block += directive

    try:
        max_images = max(0, int(rules.get("max_images_per_reply", 3)))
    except (TypeError, ValueError):
        max_images = 3
    tools: list[dict] = []
    if rules.get("can_send_images", True) and items:
        tools = [dict(_CATALOG_RECOMMEND_TOOL)]
        text_block += f"\n\nYou may recommend up to {max_images} item(s) with photos per reply."
    if any(row.get("price_paise") is not None for row in items):
        tools.append(dict(_SEND_QUOTE_TOOL))

    return text_block, tools, items_by_id, max_images


async def _build_catalog_context(db, tenant_id: str, message: str) -> tuple[str, list[dict], dict[str, dict], int]:
    """Fetch relevant catalog items for this message and build the prompt context + tool
    definitions, gating disambiguation when multiple variants of one item are in contention.

    Returns (catalog_text_block, tool_definitions, items_by_id, max_images_per_reply).
    catalog_text_block is empty when no items exist or can_recommend is disabled. On any
    retrieval failure, when nothing matches, or when the tenant's ready items aren't fully
    embedded yet, falls back to listing every ready item -- today's original behavior --
    so a provider hiccup or a partially-migrated catalog never hides items from the AI.
    """
    rules = _load_catalog_ai_rules(db, tenant_id)
    if not rules.get("can_recommend"):
        return "", [], {}, 0

    candidates: list[dict] = []
    try:
        unembedded = (
            db.table("catalog_items")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("status", "ready")
            .is_("embedding", "null")
            .execute()
        )
        has_full_embedding_coverage = not (unembedded.count or 0)
    except Exception as e:
        logger.warning(f"Embedding coverage check failed for tenant {tenant_id}, treating as partial: {e}")
        has_full_embedding_coverage = False

    if has_full_embedding_coverage:
        # Smart retrieval is only trustworthy when every ready item has an embedding --
        # match_catalog_items filters to embedding IS NOT NULL, so a partially-embedded
        # catalog would silently hide the un-embedded items the moment ANY item matches
        # elsewhere. Falling back to the full-catalog listing below (same as a zero-match
        # result) guarantees no item is ever invisible, at the cost of losing the smart
        # gate for that one reply.
        try:
            candidates = await match_catalog_items(db, tenant_id, message)
        except Exception as e:
            logger.warning(f"Catalog retrieval failed for tenant {tenant_id}, falling back to full catalog: {e}")

    directive = ""
    if candidates:
        contention = contention_set(candidates)
        gate = classify_gate(contention)
        if gate == "confident":
            items = contention
        elif gate == "same_group":
            items = []
            directive = differing_attribute_directive(contention)
        else:
            items = []
            directive = broad_browse_directive(contention)
    else:
        try:
            res = (
                db.table("catalog_items")
                .select("id,name,item_type,description,price_paise,price_note,stock_quantity")
                .eq("tenant_id", tenant_id)
                .eq("status", "ready")
                .order("name")
                .execute()
            )
            items = res.data or []
        except Exception as e:
            logger.warning(f"Failed to load catalog items for tenant {tenant_id}: {e}")
            return "", [], {}, 0

    return catalog_prompt(items, directive, rules)


def _load_catalog_images(
    db, tenant_id: str, item_ids, max_images: int, items_by_id: dict,
) -> list[tuple[str, bytes]]:
    """(label, image bytes) for the recommended items, in the client's ranked order, capped
    at max_images in total. A storage failure costs the photo, never the reply."""
    images: list[tuple[str, bytes]] = []
    for item_id in item_ids or ():
        remaining = max_images - len(images)
        if remaining <= 0:
            break
        item = items_by_id.get(item_id) or {}
        try:
            rows = (
                db.table("catalog_media").select("id,storage_path,label")
                .eq("catalog_item_id", item_id).eq("tenant_id", tenant_id)
                .order("sort_order").limit(remaining).execute()
            ).data or []
            for row in rows:
                data = db.storage.from_("catalog-media").download(row["storage_path"])
                images.append((row["label"] or item.get("name") or "Photo", data))
        except Exception as media_err:
            logger.warning("Failed to load catalog media for item %s: %s", item_id, media_err)
    return images


_HUMAN_TOUCH_BLOCK = (
    "\n\nHUMAN TOUCH (you are one real person on this business's team, texting on WhatsApp):\n"
    "- Speak as a person on the team (\"I\", \"we\"). Do not call yourself a bot, an AI or an "
    "automated assistant. Only if they sincerely ask whether they are talking to a bot, answer "
    "honestly in one light line and carry on helping.\n"
    "- Personal or flirty questions: brush them off lightly in a few words and return to how you "
    "can help.\n"
    "- Match their mood. No emoji at all when they are upset, worried, grieving or asking "
    "something serious.\n"
    "- If they are angry or let down, first say sorry for the specific thing that went wrong.\n"
    "- Never end two messages with the same sentence, and never send the same reply twice; vary "
    "your words the way a person does.\n"
    "- Keep it short: one or two small paragraphs. Answer exactly what they asked, directly."
)


def build_reply_system_prompt(
    db,
    lead_id: str,
    tenant_id: str,
    lead_data: dict,
    message: str,
    channel: str = "whatsapp",
    *,
    campaign_name: str | None = None,
    context_text: str = "",
    catalog_context: str = "",
    include_intake_context: bool = True,
    tapped_option_key: str | None = None,
    persist: bool = True,
    last_seen_at: str | None = None,
) -> tuple[str, str, bool]:
    """Assemble the main-brain system prompt, and return the reply language mode it
    was built with (the caller needs that mode for the post-generation script-mismatch
    check) plus whether an active intake session added its own holding block --
    callers use that to suppress catalog tool-calling and to skip the escalation
    block, since both are wrong once intake is already holding the conversation.

    Extracted verbatim from generate_reply so other flows can speak with the same
    voice. The intake collector composes its own lines and had none of this -- no
    master prompt, no business description, no lead or campaign context -- which is
    why it reads as a thinner, different assistant mid-conversation.

    include_intake_context=False for callers that ARE the intake flow: telling the
    collector "an intake is in progress" is noise at best, contradictory at worst.

    persist=False makes the build read-only (it skips the tamil_locked write) so the
    operator "What Anril saw" reconstruction can never change a lead.
    """
    system_prompt = _build_base_prompt(channel, tenant_id)
    if campaign_name:
        system_prompt += (
            f'\n\nCAMPAIGN CONTEXT:\nThis lead came from the "{campaign_name}" campaign. '
            "Assume their questions relate to that unless they clearly ask about something else. "
            "If they ask about something outside it that you cannot answer, follow the HANDOVER RULE."
        )
    if context_text:
        system_prompt += (
            "\n\nKNOWLEDGE BASE:\nUse the following excerpts to answer the user's question "
            "accurately. If the answer is not in the excerpts, do not guess and do not answer "
            "yes or no; say you don't have that detail and follow the HANDOVER RULE.\n\n"
            + context_text
        )

    lead_name = (lead_data.get("name") or "").strip()
    lead_segment = lead_data.get("segment") or "C"
    summary = _fetch_conversation_summary(db, lead_id)

    lead_facts: list[str] = []
    if lead_name:
        lead_facts.append(f"Lead name: {lead_name}")
    lead_facts.append(f"Current segment: {lead_segment} (A=hot, B=warm, C=cold, D=disqualified)")
    if summary:
        lead_facts.append(f"Earlier conversation summary:\n{summary}")
    system_prompt += "\n\nLEAD CONTEXT:\n" + "\n".join(lead_facts)

    try:
        call_context = _fetch_call_context(db, lead_id, tenant_id)
        system_prompt += _call_context_block(call_context)
    except Exception:
        logger.exception(
            "Call context block failed for lead %s — replying without it",
            lead_id,
        )

    reply_language_mode = _resolve_reply_language_mode(tenant_id)
    if reply_language_mode == "tanglish_escalate_tamil":
        reply_language_mode = _resolve_tamil_lock(
            db, lead_id, lead_data, message, persist=persist
        )
    system_prompt += _language_rule_block(reply_language_mode, message)
    system_prompt += _HUMAN_TOUCH_BLOCK

    # Intake context takes priority over the generic escalation holding message --
    # it is the more specific, money-aware story (names the expert/service, forbids
    # invented links, forbids promising a time) and stacking the vaguer "our team
    # will reach out" escalation block on top of it just doubles the holding
    # pattern without adding information. Checked first so the escalation block
    # below can see whether intake already covered this turn.
    intake_active = False
    if include_intake_context:
        try:
            from app.services.intake import (
                get_in_progress_session,
                get_intake_config,
                get_paid_unresolved_session,
            )
            # The enabled flag is the tenant's off switch for the whole feature, so it
            # gates these blocks too. Without it, turning Paid Intake off left every
            # lead holding a live session row still being told "the expert will be in
            # touch" / "reply so the payment can continue" -- pointing at a flow that
            # no longer runs, with no way out short of editing the rows by hand.
            intake_config = get_intake_config(tenant_id, db=db)
            from app.services import deal_engine
            if channel == "whatsapp" and deal_engine.is_enabled(intake_config):
                # AI-native selling: the model sees the offerings, the required details and
                # the deal state, and drives the sale itself through tools (deal_turn).
                # Replaces the old "intake in progress" holding block, whose "do not
                # re-offer" rule contradicts a lead asking which package to pick.
                from app.services.intake import _IN_PROGRESS_STATUSES, _get_active_session
                deal_session = _get_active_session(lead_id, tenant_id, db)
                from app.services.intake import previous_booking
                # last_seen_at is the deal's idle clock as it was BEFORE this message (the
                # caller read it first; capture_details has since moved it). The model, not a
                # keyword list, judges whether the message shows intent (D4).
                system_prompt += deal_engine.deal_prompt(
                    intake_config, deal_session, tapped_key=tapped_option_key, last_seen_at=last_seen_at,
                    previous_details=None if deal_session else previous_booking(db, tenant_id, lead_id),
                )
                status = (deal_session or {}).get("status")
                if status == "paid":
                    from app.config_dynamic import get_setting
                    system_prompt += _intake_paid_prompt_block(
                        intake_config["service_noun"],
                        answer_in_app=bool(business_app_link(tenant_id)),
                    )
                intake_active = status == "paid" or status in _IN_PROGRESS_STATUSES
            elif intake_config.get("enabled"):
                if get_paid_unresolved_session(lead_id, tenant_id, db=db):
                    from app.config_dynamic import get_setting
                    system_prompt += _intake_paid_prompt_block(
                        intake_config["service_noun"],
                        answer_in_app=bool(business_app_link(tenant_id)),
                    )
                    intake_active = True
                elif get_in_progress_session(lead_id, tenant_id, db=db):
                    # Covers collecting/awaiting_confirmation/awaiting_payment turns that
                    # route_intake handed back to the AI (e.g. a correction, or an
                    # off-topic question) -- without this the AI has no idea a sale is
                    # mid-flow and can derail it. See _intake_in_progress_prompt_block.
                    system_prompt += _intake_in_progress_prompt_block(
                        intake_config["service_noun"]
                    )
                    intake_active = True
        except Exception:
            logger.exception(
                "Intake session-context check failed for lead %s — replying without it",
                lead_id,
            )

    # Escalated leads keep talking to the AI, but it must answer as a
    # holding presence, not as if nothing happened. Degrades to a normal
    # reply if business hours can't be read — never to no reply. Skipped
    # when intake already added its own holding message this turn.
    if lead_data.get("needs_human_attention") and not intake_active:
        try:
            system_prompt += _escalation_prompt_block(handover_line=_handover_line(tenant_id))
        except Exception:
            logger.exception(
                "Escalation prompt block failed for lead %s — replying without it",
                lead_id,
            )

    # The lead's recent product orders (quoted / link sent / paid), so a "did my order go
    # through?" or "send the link again" is answered from facts. Never raises.
    from app.services import deal_actions, deal_engine
    system_prompt += deal_engine.orders_block(deal_actions.lead_orders(db, tenant_id, lead_id))
    try:
        from app.services import intake
        from app.services.business_details import get_business_details
        gst_on_top = bool(deal_engine.gst_percent(intake.get_intake_config(tenant_id, db=db)))
        system_prompt += deal_engine.business_facts_block(get_business_details(tenant_id, db), gst_on_top=gst_on_top)
    except Exception:
        logger.warning("Business details block failed for tenant %s -- replying without it", tenant_id)

    if catalog_context:
        system_prompt += catalog_context

    # Last, so it is the freshest instruction when the model decides how to ask a question.
    from app.services.choices import PROMPT_BLOCK as _CHOICES_BLOCK
    system_prompt += _CHOICES_BLOCK

    return system_prompt, reply_language_mode, intake_active


async def generate_reply(
    lead_id: str,
    message: str,
    phone: str | None = None,
    channel: str = "whatsapp",
    ig_user_id: str | None = None,
    context_block: str | None = None,
    tg_user_id: str | None = None,
    fb_user_id: str | None = None,
    phone_number_id: str | None = None,
    inbound_media_type: str | None = None,
    meta_message_id: str | None = None,
    interactive_id: str | None = None,
) -> None:
    """
    Core pipeline:
    1. Inject knowledge base context
    2. Call the LLM for a reply
    3. Send reply via the matching channel
    4. Score the message and update lead score + segment in DB
    """
    db = get_supabase()

    # Step 0: fetch lead + load module configs
    lead_row = (
        db.table("leads")
        .select("ai_enabled,score,segment,phone,converted_at,tenant_id,assigned_to,name,blocked_at,needs_human_attention,tamil_locked")
        .eq("id", str(lead_id))
        .limit(1)
        .execute()
    )
    lead_data = lead_row.data[0] if lead_row.data else {}
    if lead_data.get("blocked_at"):
        logger.info(f"Lead {lead_id} is blocked — skipping auto-reply")
        return
    tenant_id = lead_data.get("tenant_id")
    if not tenant_id:
        raise ValueError("tenant_id missing from lead_data")
    segment = lead_data.get("segment") or "C"

    # D3: any lead message restarts their open deal's idle clock, whoever ends up replying. Read
    # first: the value it had before this message says how long they were away (D4), and the
    # detail capture below moves it again.
    from app.services.intake import note_lead_message
    last_seen_at = note_lead_message(db, tenant_id, str(lead_id))

    # Enforce global AI auto-reply toggle
    _ai_setting = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "ai_auto_reply_enabled")
        .limit(1)
        .execute()
    )
    if _ai_setting.data and _ai_setting.data[0].get("value") == "false":
        logger.info(f"AI auto-reply globally disabled for tenant {tenant_id} — skipping reply")
        return

    inbox_cfg = get_inbox_config(tenant_id)
    escalation_flags: set[str] = set()

    # Trigger C: user explicitly asked for human (always fires, not config-gated)
    if _HUMAN_REQUEST_RE.search(message):
        escalation_flags.add("C")
        logger.info(f"Trigger C: lead {lead_id} asked for human agent")

    # Pre-fetch recent thread (reused for trigger D + LLM chat below)
    recent_thread = _recent_thread(db, lead_id, limit=8, tenant_id=tenant_id)

    # Trigger D: user repeated the same question (AI not resolving it)
    # Skip the first inbound match — it's the current message (already stored before generate_reply runs).
    # We need the PREVIOUS inbound to compare against.
    if "D" in inbox_cfg.get("triggers", []):
        prev_inbounds = [r for r in recent_thread if r.get("direction") == "inbound"]
        prev_inbound = prev_inbounds[1] if len(prev_inbounds) > 1 else None
        if prev_inbound and _is_similar(message, prev_inbound.get("content", "")):
            escalation_flags.add("D")
            logger.info(f"Trigger D: lead {lead_id} repeated same question")
    from app.config_dynamic import get_setting
    global_ai_enabled = get_setting("ai_auto_reply_enabled", fallback="true", tenant_id=tenant_id) == "true"
    if (lead_data and lead_data.get("ai_enabled") is False) or not global_ai_enabled:
        logger.info(f"AI auto-reply is disabled (lead_ai_enabled={lead_data.get('ai_enabled')}, global_ai_enabled={global_ai_enabled}) — skipping auto-reply")
        # Still rescore via Score Engine v2 so admin sees segment updates during manual handling
        try:
            from app.services.scoring_engine import compute_score as _compute_score
            _tid = lead_data.get("tenant_id")
            _sr = await _compute_score(
                message=message, lead_id=str(lead_id), db=db,
                tenant_id=_tid,
            )
            new_score = _sr["score"]
            new_segment = _sr["segment"]
            if _sr.get("intent_reason") == "rejection" and lead_data.get("assigned_to"):
                try:
                    db.table("leads").update({"assigned_to": None}).eq("id", str(lead_id)).execute()
                    lead_data["assigned_to"] = None
                    logger.info(f"Lead {lead_id} unassigned after rejection (AI-disabled path)")
                except Exception:
                    pass
            _score_meta = {
                "new_score": new_score,
                "prev_score": lead_data.get("score", 5),
                "arc_score": _sr["arc_score"],
                "intent_delta": _sr["intent_delta"],
                "engagement": _sr["engagement"],
                "intent_reason": _sr["intent_reason"],
                "arc_updated": _sr["arc_updated"],
                "classification_reason": _sr.get("reason"),
                "message_snippet": message[:150],
                "channel": channel,
                "reason": "ai_disabled_inbound",
            }
            record_stage_event(
                lead_id,
                from_segment=lead_data.get("segment"),
                to_segment=new_segment,
                event_type="segment_changed" if new_segment != lead_data.get("segment") else "score_updated",
                metadata=_score_meta,
                tenant_id=_tid,
                db=db,
            )
            sync_follow_up_jobs(
                lead_id,
                segment=new_segment,
                phone=lead_data.get("phone") or phone,
                converted_at=lead_data.get("converted_at"),
                ai_enabled=False,
                reason="ai_disabled",
                tenant_id=_tid,
                db=db,
            )
        except Exception as e:
            logger.error(f"Scoring update failed (takeover mode) for lead {lead_id}: {e}")
        return

    # Campaign scoping: which campaign did this lead come from? Drives both the
    # KB filter and the prompt focus. None = cold lead → unscoped (full KB) as before.
    if not check_quota(db, tenant_id, "ai_reply"):
        logger.info(f"AI reply skipped for tenant {tenant_id}: ai_reply quota exhausted")
        return

    campaign_tag_id, campaign_name = _resolve_campaign(db, lead_id)

    # RAG: retrieve the most relevant knowledge-base chunks for THIS message
    try:
        context_text = await get_knowledge_context(
            tenant_id,
            query=message,
            campaign_tag_id=campaign_tag_id,
        )
    except Exception as e:
        logger.warning(f"Knowledge context fetch failed for lead {lead_id}: {e}")
        context_text = ""

    catalog_tools: list[dict] = []
    catalog_items_by_id: dict[str, dict] = {}
    catalog_max_images = 0
    try:
        catalog_context, catalog_tools, catalog_items_by_id, catalog_max_images = await _build_catalog_context(
            db, tenant_id, message
        )
    except Exception:
        catalog_context = ""
        logger.warning(f"Catalog context build failed for tenant {tenant_id}")

    # Bound out here, not inside the try below: that block's except does not return,
    # it falls through to the channel dispatch, which reads both of these. A variable
    # only assigned inside the try raises NameError on any LLM failure -- turning a
    # recoverable error into a lost reply. (catalog_images_to_send had this bug.)
    catalog_images_to_send: list[tuple[str, bytes]] = []  # (filename, image_bytes)

    # Every reply runs through one guarded loop (services/deal_turn.py): package selling on
    # WhatsApp, product photos and quotes, quick-reply blocks, the price guard and the
    # payment-complaint handover. None of these steps raise.
    from app.services import deal_turn
    from app.services.choices import is_choice_tap as _is_choice_tap
    deal_outcome = None
    deal_ctx = deal_turn.build_context(
        db, tenant_id, lead_id, phone or lead_data.get("phone"),
        channel=channel, catalog=catalog_items_by_id, max_images=catalog_max_images,
    )
    payment_guard_fired = deal_turn.pre_turn_guards(deal_ctx, message)
    if payment_guard_fired:
        logger.info(f"Payment complaint: lead {lead_id} handed to a person before the model ran")
    # Save any required details in this message before the prompt is built, so the
    # DEAL STATE the model reads is already up to date (see capture_details).
    reply_thread = deal_turn.without_detail_taps(recent_thread)
    earlier_inbound = [
        (row.get("content") or "") for row in reversed(reply_thread)
        if row.get("direction") == "inbound" and (row.get("content") or "") != message
    ]
    await deal_turn.capture_details(deal_ctx, message, earlier=earlier_inbound, interactive_id=interactive_id)
    rejected_tap_note = deal_turn.detail_tap_note(deal_ctx, interactive_id)
    if rejected_tap_note:
        from dataclasses import replace
        deal_ctx = replace(deal_ctx, rejected_detail_tap=True)

    try:
        system_prompt, reply_language_mode, intake_active = build_reply_system_prompt(
            db,
            lead_id,
            tenant_id,
            lead_data,
            message,
            channel,
            campaign_name=campaign_name,
            context_text=context_text,
            catalog_context=catalog_context,
            # A tap on a choice Anril offered in words ("choice:2") is just its title as text;
            # only a package/addon key is a tapped offering.
            tapped_option_key=None if _is_choice_tap(interactive_id) else interactive_id,
            last_seen_at=last_seen_at,
        )
        # recent_thread already fetched at step 0 (reuse - no extra DB call)
        chat_messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for row in reversed(reply_thread):  # oldest first
            content = (row.get("content") or "").strip()
            if not content:
                continue
            role = "assistant" if row.get("direction") == "outbound" else "user"
            chat_messages.append({"role": role, "content": content})

        # No code-injected tag on the user turn itself: the CUSTOMER'S LATEST MESSAGE
        # SCRIPT line already added to system_prompt above covers the one thing that's
        # reliably checkable (Tamil-block vs Latin script). We deliberately do NOT also
        # inject _detect_lang()'s Tanglish-vs-English keyword guess here -- that half is
        # fuzzy, and the model reading the raw words is reliably better at that call
        # than a hardcoded keyword list.
        if not chat_messages or chat_messages[-1].get("role") != "user" or chat_messages[-1].get("content") != message:
            chat_messages.append({"role": "user", "content": message})
        if rejected_tap_note:
            chat_messages[0]["content"] += "\n\n" + rejected_tap_note
            chat_messages[-1] = {"role": "user", "content": "[Tapped an old detail button; ask for the current details again.]"}

        # The payment link and any product quote are appended below, after the
        # script-mismatch rewrite, so a translation pass can never touch a URL or a price.
        reply_text, tool_calls, deal_outcome = await deal_turn.converse_once(
            chat_messages, catalog_tools, deal_ctx, tenant_id=tenant_id,
            append_link=False, handover_opened=payment_guard_fired,
            handover_line=_handover_line(tenant_id),
        )
        # Product photos the model picked (validated by deal_actions: in the catalog,
        # in stock, capped at max_images_per_reply).
        catalog_images_to_send = _load_catalog_images(
            db, tenant_id, deal_outcome.image_item_ids, catalog_max_images, catalog_items_by_id,
        )

        is_ai = True
        reply_source = "knowledge" if context_text else "ai"

        if not reply_text:
            reply_text = _FALLBACK_BY_LANG.get(_detect_lang(message), _FALLBACK_BY_LANG["en"])
        else:
            # Preemptive prompt instructions (LANGUAGE RULE + the per-turn script note
            # above, or the forced-mode LANGUAGE STYLE block) do not reliably stop a
            # silent script switch -- live-tested 0/6 for mirror mode, see
            # subsystem-notes.md 2026-07-13; the same failure hits forced modes too
            # (live evidence 2026-08-31, see _forced_mode_script_mismatch). This catches
            # it after generation, before anything is sent, and asks for one corrected
            # regeneration. mirror's target is the customer's own script; every forced
            # mode has a fixed target regardless of what the customer wrote.
            regen_target: str | None = None
            if reply_language_mode == "mirror":
                if _reply_script_mismatch(message, reply_text):
                    regen_target = _regen_target_instruction(message)
            elif _forced_mode_script_mismatch(reply_language_mode, reply_text):
                regen_target = _FORCED_MODE_TARGET_INSTRUCTION.get(reply_language_mode)

            if regen_target:
                # The regen call deliberately carries NO conversation history and is
                # framed as an isolated translation task, not "continue the chat" --
                # live-tested 2026-07-13: feeding the wrong reply back in as part of the
                # same history (i.e. asking the model to "redo" its own last turn) mostly
                # failed (1/6, the anchor re-triggers even with an explicit correction).
                # An isolated rewrite-only call with no prior turns to anchor to fixed it
                # 10/10. The target language must be named explicitly ("English or
                # Tanglish"), not "Latin script" -- a vague script-only instruction let
                # the model drift into literal Latin (the dead language) once, since any
                # Latin-alphabet text technically satisfies "not Tamil script".
                try:
                    regen_messages = [
                        {
                            "role": "system",
                            "content": (
                                "You are a translator. Rewrite the following WhatsApp reply so it is in "
                                f"{regen_target}. Keep the same meaning, tone, and "
                                "length. Output ONLY the rewritten reply, nothing else."
                            ),
                        },
                        {"role": "user", "content": reply_text},
                    ]
                    regenerated = (await _llm_chat(regen_messages, max_tokens=600, tenant_id=tenant_id)).strip()
                    if regenerated:
                        still_mismatched = (
                            _reply_script_mismatch(message, regenerated)
                            if reply_language_mode == "mirror"
                            else _forced_mode_script_mismatch(reply_language_mode, regenerated)
                        )
                        if still_mismatched:
                            logger.warning(f"Script-mismatch regen still mismatched for lead {lead_id}")
                        reply_text = regenerated
                except Exception as regen_err:
                    logger.warning(f"Script-mismatch regeneration failed for lead {lead_id}: {regen_err}")

        if deal_outcome and deal_outcome.payment_link:
            reply_text = f"{reply_text}\n{deal_outcome.payment_link}".strip()
        if deal_outcome and deal_outcome.quote_text:
            reply_text = f"{reply_text}\n\n{deal_outcome.quote_text}".strip()

        # Trigger A: AI gave a generic fallback reply
        if _is_generic_fallback(reply_text):
            escalation_flags.add("A")
            logger.info(f"Trigger A: lead {lead_id} received generic fallback reply")
        # Trigger F: AI reply contained escalation phrases
        if _AI_ESCALATION_RE.search(reply_text):
            escalation_flags.add("F")

    except Exception as e:
        logger.error(f"LLM reply failed for lead {lead_id}: {e}")
        reply_text = _FALLBACK_BY_LANG.get(_detect_lang(message), _FALLBACK_BY_LANG["en"])
        is_ai = False
        reply_source = "ai"
        # Trigger B: AI/LLM exception - escalate so a human can pick up
        escalation_flags.add("B")
        logger.info(f"Trigger B: lead {lead_id} LLM exception - {e}")

    # Step 3: Dispatch to the correct channel
    outbound_media_type: str | None = None
    outbound_media_mime_type: str | None = None
    if channel == "instagram":
        sid = await send_instagram(ig_user_id, reply_text, tenant_id=lead_data.get("tenant_id")) if ig_user_id else None
    elif channel == "telegram":
        sid = await send_telegram(tg_user_id, reply_text, tenant_id=lead_data.get("tenant_id")) if tg_user_id else None
    elif channel == "facebook":
        sid = await send_facebook(fb_user_id, reply_text, tenant_id=lead_data.get("tenant_id")) if fb_user_id else None
    else:
        _wa_phone = phone or lead_data.get("phone")
        sid = None
        voice_reply_enabled = get_setting("ai_voice_reply_enabled", fallback="false", tenant_id=tenant_id) == "true"
        if _wa_phone and voice_reply_enabled and inbound_media_type == "audio":
            from app.services.gemini_client import DEFAULT_GEMINI_VOICE
            voice_speaker = get_setting("ai_voice_reply_speaker", fallback=DEFAULT_GEMINI_VOICE, tenant_id=tenant_id) or DEFAULT_GEMINI_VOICE
            sid = await send_whatsapp_voice_reply(
                _wa_phone,
                reply_text,
                tenant_id=lead_data.get("tenant_id"),
                phone_number_id=phone_number_id,
                speaker=voice_speaker,
                db=db,
            )
            if sid:
                outbound_media_type = "audio"
                outbound_media_mime_type = "audio/mpeg"
                if deal_outcome and deal_outcome.menu:
                    # A voice note cannot carry buttons; the options follow it so a
                    # choice is never left untappable.
                    from app.services import deal_turn
                    await deal_turn.send_menu(
                        _wa_phone, deal_turn.CHOICE_BODY_FALLBACK, deal_outcome.menu,
                        tenant_id=lead_data.get("tenant_id"), phone_number_id=phone_number_id,
                    )
        if _wa_phone and not sid:
            reply_to_message_id = None
            if meta_message_id:
                try:
                    latest_inbound = (
                        db.table("messages")
                        .select("meta_message_id")
                        .eq("lead_id", lead_id)
                        .eq("tenant_id", tenant_id)
                        .eq("direction", "inbound")
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    latest_id = (latest_inbound.data or [{}])[0].get("meta_message_id")
                    # A newer inbound message already landed while this reply was being
                    # generated -- quote the one we're actually answering so it's clear
                    # which question this reply is for.
                    if latest_id and latest_id != meta_message_id:
                        reply_to_message_id = meta_message_id
                except Exception as burst_err:
                    logger.warning(f"Burst check failed for lead {lead_id}: {burst_err}")
            if deal_outcome and deal_outcome.menu:
                from app.services import deal_turn
                sid, tappable = await deal_turn.send_menu(
                    _wa_phone, reply_text, deal_outcome.menu,
                    tenant_id=lead_data.get("tenant_id"), phone_number_id=phone_number_id,
                )
                reply_text = deal_turn.menu_record(reply_text, deal_outcome.menu, tappable=tappable)
            else:
                from app.services import choices, deal_turn
                # One https link in the reply goes out as a URL button instead of a raw address.
                # A quoted reply stays plain text: the button message cannot quote.
                link = None if reply_to_message_id else choices.split_link(reply_text)
                if link:
                    sid, _tappable = await deal_turn.send_link(
                        _wa_phone, link, tenant_id=lead_data.get("tenant_id"),
                        phone_number_id=phone_number_id, original=reply_text,
                    )
                else:
                    sid = await send_whatsapp(
                        _wa_phone,
                        reply_text,
                        tenant_id=lead_data.get("tenant_id"),
                        phone_number_id=phone_number_id,
                        reply_to_message_id=reply_to_message_id,
                    )

        # Send catalog recommendation images as follow-up WhatsApp media
        if _wa_phone and sid and catalog_images_to_send:
            from app.services.meta_cloud import upload_media_to_meta, send_media_message
            for img_filename, img_bytes in catalog_images_to_send[:catalog_max_images]:
                try:
                    media_id = await upload_media_to_meta(
                        file_bytes=img_bytes,
                        mime_type="image/jpeg",
                        filename=img_filename,
                        tenant_id=lead_data.get("tenant_id"),
                        phone_number_id=phone_number_id,
                    )
                    await send_media_message(
                        to_number=_wa_phone,
                        media_id=media_id,
                        wa_type="image",
                        caption=img_filename,
                        tenant_id=lead_data.get("tenant_id"),
                        phone_number_id=phone_number_id,
                    )
                    db.table("messages").insert({
                        "lead_id": str(lead_id),
                        "direction": "outbound",
                        "channel": channel,
                        "content": f"[Catalog image: {img_filename}]",
                        "is_ai_generated": True,
                        "reply_source": "ai",
                        "tenant_id": tenant_id,
                        "media_type": "image",
                        "media_mime_type": "image/jpeg",
                    }).execute()
                    meter(db, tenant_id, "ai_media_recommendation")
                except Exception as img_err:
                    logger.warning("Catalog image send failed for lead %s: %s", lead_id, img_err)

    # Track-only usage metering: count once per AI-generated reply that was
    # actually sent (non-None message id). Never blocks/caps — best-effort only.
    if is_ai and sid is not None:
        meter(db, tenant_id, "ai_reply")

    # Step 4: Store outbound message
    if channel == "telegram":
        sid_field = "tg_message_id"
    elif channel == "facebook":
        sid_field = "fb_message_id"
    elif channel == "whatsapp":
        sid_field = "meta_message_id"
    else:
        sid_field = "meta_message_id"  # instagram uses meta_message_id
    outbound_row = {
        "lead_id": str(lead_id),
        "direction": "outbound",
        "channel": channel,
        "content": reply_text,
        "is_ai_generated": is_ai,
        "reply_source": reply_source,
        "tenant_id": tenant_id,
        sid_field: sid,
    }
    if outbound_media_type:
        outbound_row["media_type"] = outbound_media_type
        outbound_row["media_mime_type"] = outbound_media_mime_type
    _outbound_res = db.table("messages").insert(outbound_row).execute()

    # Arm the silence nudge. Best-effort by design: the customer has already
    # received their reply, and a failure here must never turn a delivered
    # answer into an exception. Same pattern as the intake/escalation blocks.
    try:
        from app.services.silence_nudge import maybe_arm_after_ai_reply
        maybe_arm_after_ai_reply(
            db,
            tenant_id=tenant_id,
            lead_id=str(lead_id),
            channel=channel,
            is_ai=is_ai,
            sid=sid,
            reply_source=reply_source,
            inserted=((_outbound_res.data or [None])[0]),
        )
    except Exception:
        logger.exception("Silence nudge arm failed for lead %s — reply already sent", lead_id)

    # Step 5: Score Engine v2 — composite arc + intent + engagement (no gate)
    new_segment = segment  # fallback if scoring fails
    new_score = lead_data.get("score", 5)
    try:
        from app.services.scoring_engine import compute_score
        from datetime import datetime, timezone

        score_result = await compute_score(
            message=message,
            lead_id=str(lead_id),
            db=db,
            tenant_id=tenant_id,
        )
        new_score = score_result["score"]
        new_segment = score_result["segment"]

        _score_meta = {
            "new_score": new_score,
            "prev_score": lead_data.get("score", 5),
            "arc_score": score_result["arc_score"],
            "intent_delta": score_result["intent_delta"],
            "engagement": score_result["engagement"],
            "intent_reason": score_result["intent_reason"],
            "arc_updated": score_result["arc_updated"],
            "message_snippet": message[:150],
            "channel": channel,
            "broadcast_id": None,
            "classification_reason": score_result.get("reason"),
        }
        record_stage_event(
            lead_id,
            from_segment=lead_data.get("segment"),
            to_segment=new_segment,
            event_type="segment_changed" if new_segment != lead_data.get("segment") else "score_updated",
            metadata=_score_meta,
            tenant_id=tenant_id,
            db=db,
        )
        if score_result.get("intent_reason") == "rejection" and lead_data.get("assigned_to"):
            try:
                db.table("leads").update({"assigned_to": None}).eq("id", str(lead_id)).execute()
                lead_data["assigned_to"] = None
                logger.info(f"Lead {lead_id} unassigned after rejection")
            except Exception:
                pass
        if not lead_data.get("assigned_to"):
            assigned_caller = maybe_assign_lead(
                str(lead_id), tenant_id, new_segment, channel,
                reason="scored", score=new_score,
            )
            if assigned_caller:
                lead_data["assigned_to"] = assigned_caller
    except Exception as e:
        logger.error(f"Scoring update failed for lead {lead_id}: {e}")

    sync_follow_up_jobs(
        lead_id,
        segment=new_segment,
        phone=lead_data.get("phone") or phone,
        converted_at=lead_data.get("converted_at"),
        ai_enabled=lead_data.get("ai_enabled", True),
        reason=f"{channel}_reply",
        tenant_id=tenant_id,
        db=db,
    )

    # Step 6: Fire inbox escalation — trigger-based only (A/B/C/D/F), no segment gate.
    # Creates an UNASSIGNED pending handover → shared pool (admin + any telecaller).
    active_triggers = [
        t for t in _TRIGGER_PRIORITY
        if t in escalation_flags and should_escalate_to_inbox(inbox_cfg, t, channel)
    ]
    if active_triggers:
        primary = active_triggers[0]
        try:
            _trigger_chat_escalation(
                lead_id=str(lead_id),
                reason=_TRIGGER_REASONS[primary],
                tenant_id=tenant_id,
                assigned_to=lead_data.get("assigned_to"),
                db=db,
            )
            logger.info(f"Inbox escalation fired for lead {lead_id} — trigger {primary}")
        except Exception as e:
            logger.error(f"Inbox escalation failed for lead {lead_id}: {e}")
