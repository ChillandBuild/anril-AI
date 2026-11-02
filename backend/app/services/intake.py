"""Generic, per-tenant paid intake: a lead opts in to pay for a human
consultation, details are collected via LLM slot-filling (not a rigid step
order — see docs/superpowers/specs/2026-08-07-paid-expert-handoff-design.md
for why), payment happens in-chat via Razorpay, and the AI mutes for that
lead once paid.
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.config_dynamic import SettingReadError
from app.services.gemini_client import gemini_chat_completion_json
from app.services.intake_copy import (
    collector_identity,
    compose_line,
    compose_wrapped,
    gather_context,
    localized_fields,
    resolve_language_mode,
)
from app.services.notify import notify_pool
from app.services.payment_razorpay import cancel_payment_link, create_payment_link

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = {
    "enabled": False,
    "trigger_description": "",
    "offer_message": "",
    "fields": [],  # list of {"key": str, "label": str, "type": "text"|"date"|"choice", "options": list[str]?}
    "packages": [],  # list of {"key": str, "name": str, "amount_paise": int, "description": str}
    "service_noun": "consultation",
    "amount_paise": 0,  # legacy single fee; superseded by packages, kept for auto-migration
    "gst_percent": 0,  # GST added on top of package + add-ons at payment; 0 = off
}


def gst_paise(subtotal_paise: int, percent) -> int:
    """GST on a pre-tax subtotal. Rounds like deals._deal_total; 0 when GST is off."""
    if not percent:
        return 0
    return round(subtotal_paise * percent / 100)


def charge_paise(subtotal_paise: int, percent) -> int:
    """What the payment link charges: the pre-GST subtotal plus its GST."""
    return subtotal_paise + gst_paise(subtotal_paise, percent)


def gst_link_description(base: str, subtotal_paise: int, percent) -> str:
    """The Razorpay link description, with the pre-GST price and rate when GST is on."""
    if not percent:
        return base
    return f"{base} · {_rupees(subtotal_paise)} + {percent:g}% GST"


def gst_session_fields(subtotal_paise: int, percent) -> dict:
    """The intake_sessions columns recorded when a link is made: the amount charged
    (GST included) and the GST split. total_amount_paise stays the pre-GST subtotal."""
    return {
        "amount_paise": charge_paise(subtotal_paise, percent),
        "gst_percent": percent or 0,
        "gst_amount_paise": gst_paise(subtotal_paise, percent),
    }


def get_intake_config(tenant_id: str, db=None) -> dict:
    """Return intake_config from app_settings, merged with defaults."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "intake_config")
        .maybe_single()
        .execute()
    )
    if row and row.data:
        try:
            stored = json.loads(row.data["value"])
            return {**_DEFAULT_CONFIG, **stored}
        except Exception:
            logger.warning(f"Failed to parse intake_config for tenant {tenant_id}")
    return dict(_DEFAULT_CONFIG)


def save_intake_config(tenant_id: str, config: dict, db=None) -> None:
    """Persist intake_config to app_settings."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    db.table("app_settings").upsert(
        {
            "key": "intake_config",
            "value": json.dumps(config),
            "tenant_id": tenant_id,
            "is_secret": False,
        },
        on_conflict="tenant_id,key",
    ).execute()


_DETECTION_SYSTEM_PROMPT = """You are a classifier. Given a business's description of what
kind of message should trigger a paid human-expert handoff, and one incoming customer
message, decide if THIS message matches that description.

Respond with JSON only: {"matches": true} or {"matches": false}. No other text."""


async def detect_intake_intent(message: str, trigger_description: str, tenant_id: str) -> bool:
    """Fail closed: any error, empty trigger_description, or unparseable response -> False.
    A missed offer is recoverable (the lead can ask again); a wrongly-triggered paid
    flow from a classifier hiccup is not."""
    if not trigger_description:
        return False
    user_prompt = f"Trigger description: {trigger_description}\n\nCustomer message: {message}"
    try:
        data = await gemini_chat_completion_json(
            system_prompt=_DETECTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=50,
            tenant_id=tenant_id,
            purpose="expert_handoff_detection",
        )
        return bool(data.get("matches") is True)
    except Exception as e:
        logger.warning(f"Intake detection failed, defaulting to no-match: {e}")
        _notify_owner_of_trigger_failure(tenant_id, str(e))
        return False


def _notify_owner_of_trigger_failure(tenant_id: str, error: str) -> None:
    """A dead Gemini key/quota/timeout here means every new lead silently never
    gets offered the paid flow -- nothing else surfaces this to a human. Best
    effort, owner-only (this is a config problem, not a telecaller task), and
    deduped on the unread row so a broken key produces one bell notification,
    not one per inbound message. Mirrors ai_reply.py's WhatsApp-send-failure
    owner alert (ai_reply.py:_send_meta_message's except block)."""
    try:
        from app.db.supabase import get_supabase
        from app.services.notify import notify_user
        db = get_supabase()
        owner = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").limit(1).execute()
        owner_uid = (owner.data[0] if owner.data else {}).get("user_id")
        if owner_uid:
            notify_user(
                tenant_id,
                owner_uid,
                "intake_trigger_failed",
                "Paid intake trigger check is failing",
                "Anril could not classify whether a lead's message should trigger the paid "
                f"consultation offer, so no offer was made ({error}). Check the Gemini API "
                "key and quota in Settings.",
                db=db,
                dedupe_lead_id="intake_trigger_failed",
            )
    except Exception as notify_err:
        logger.warning(f"Failed to notify owner of intake trigger failure: {notify_err}")


# Tenants name their own intake fields, so the key holding a person's name is
# whatever they typed into the console -- full_name for an astrologer,
# patient_name for a clinic, member_name for a gym. Matching on the literal key
# "name" found none of them. Live evidence 2026-08-15: a lead who typed
# "Prem Kumar D" got "Customer, Payment success aayiduchu" when their payment
# cleared, and staff were notified about "Lead 'Customer'".
#
# The token list is deliberately short and honest: it cannot cover every language
# a tenant might label a field in, which is exactly why resolve_customer_name
# returns None rather than a placeholder when nothing matches. A missing greeting
# is invisible; a wrong one is not.
_NAME_TOKENS = ("name", "naam", "peyar")


def _looks_like_a_name_field(key: str, label: str = "") -> bool:
    haystack = f"{key} {label}".lower()
    return any(token in haystack for token in _NAME_TOKENS)


def resolve_customer_name(
    collected_data: dict | None,
    fields: list[dict] | None = None,
    lead_name: str | None = None,
) -> str | None:
    """The customer's own name, or None when it genuinely cannot be identified.

    Never returns a placeholder: callers decide how to degrade (the receipt drops
    the greeting, the staff notification says "a lead", the Razorpay description
    falls back to the phone number). Config order is respected so a form asking
    for both a customer and a nominee resolves to the customer.
    """
    collected = collected_data or {}

    def _clean(value) -> str | None:
        text = str(value or "").strip()
        return text or None

    if fields:
        for field in fields:
            key = field.get("key", "")
            if _looks_like_a_name_field(key, field.get("label", "")):
                found = _clean(collected.get(key))
                if found:
                    return found
    else:
        for key, value in collected.items():
            if _looks_like_a_name_field(key):
                found = _clean(value)
                if found:
                    return found

    return _clean(lead_name)


def adopt_lead_name(db, lead_id: str, tenant_id: str, name: str | None) -> None:
    """Fill in leads.name from what the customer told the collector, but only when
    the lead has no name yet -- the guard lives in the query rather than a prior
    read, so a name a human set by hand is never overwritten. Best effort: the
    dashboard label is not worth failing a payment or a reply over."""
    if not name:
        return
    try:
        (
            db.table("leads")
            .update({"name": name})
            .eq("id", lead_id)
            .eq("tenant_id", tenant_id)
            .is_("name", "null")
            .execute()
        )
    except Exception as e:
        logger.warning(f"Could not adopt collected name onto lead {lead_id}: {e}")


def missing_field_labels(fields: list[dict], collected_data: dict) -> list[str]:
    return [f["label"] for f in fields if not collected_data.get(f["key"])]


_MAX_FIELD_ATTEMPTS = 2

# A message that yields no field value is not automatically a failed attempt at the
# pending field. Live evidence 2026-08-13: a lead's fresh "Hii" was recorded as the
# second failed attempt at place of birth, so the field was skipped and the flow
# jumped to the summary. Greetings, withdrawals and questions are not attempts.
_GREETING_WORDS = frozenset({
    "hi", "hii", "hiii", "hello", "helo", "hey", "hai", "haai",
    "vanakkam", "வணக்கம்", "namaskaram", "good", "morning", "evening", "afternoon",
})

_CANCEL_WORDS = frozenset({
    "vendaam", "vendam", "venam", "veanam", "cancel", "stop", "quit", "exit",
    "later", "apparam", "aprm", "baduve", "வேண்டாம்", "வேண்டாம",
})

_QUESTION_WORDS = frozenset({
    "eppo", "eppa", "enna", "evlo", "evvalavu", "yaar", "yaaru", "epdi", "eppadi",
    "yen", "ean", "when", "what", "how", "why", "who", "where", "will", "can", "does",
    "is", "are", "எப்போ", "எப்படி", "என்ன", "எவ்வளவு", "ஏன்", "யார்",
})


def classify_non_answer(message: str) -> str:
    """Why a message contained no field value: 'greeting' | 'cancel' | 'question' |
    'attempt'. Only 'attempt' counts toward the skip ceiling.

    Deliberately deterministic rather than another LLM call: this runs on every
    collecting turn, and a keyword miss just falls through to 'attempt', which is
    the old behaviour -- no worse than before, and no extra latency on the flow.
    """
    import re
    tokens = set(re.findall(r"[\w஀-௿]+", message.strip().lower()))
    if not tokens:
        return "attempt"
    # Cancel first: a withdrawal outranks everything else in the message.
    if tokens & _CANCEL_WORDS:
        return "cancel"
    # Greeting only when that is essentially the whole message -- "hi, my name is
    # Prem" carries a real answer and must not be treated as a bare greeting.
    if tokens <= _GREETING_WORDS:
        return "greeting"
    if "?" in message or (tokens & _QUESTION_WORDS):
        return "question"
    return "attempt"


def pending_fields(fields: list[dict], collected_data: dict, skipped=()) -> list[dict]:
    """Fields still needed: neither collected nor given up on. Ordered by config, so
    the collector always asks for the first outstanding one."""
    skipped_set = set(skipped)
    return [
        f for f in fields
        if not collected_data.get(f["key"]) and f["key"] not in skipped_set
    ]


_EXTRACTION_SYSTEM_PROMPT = """You extract structured field values from one customer chat
message. You are given a list of fields the business needs and the values already
collected from earlier turns. Read the new message and return ONLY the fields you can
confidently find IN THIS MESSAGE, as flat JSON: {"field_key": "value", ...}.

Rules:
- Only include a key if this message actually contains that value.
- Never guess or invent a value that isn't stated.
- Do not repeat values that weren't in this message, even if already collected.
- If this message contains none of the requested fields, return {}.
- JSON only, no other text."""


async def extract_fields(message: str, fields: list[dict], collected_data: dict, tenant_id: str) -> dict:
    """Never drops already-collected data: the LLM only ever contributes additions
    for THIS message, which are merged on top of (never replacing) collected_data."""
    field_list = "\n".join(f"- {f['key']}: {f['label']} ({f['type']})" for f in fields)
    already = ", ".join(f"{k}={v}" for k, v in collected_data.items()) or "(none yet)"
    user_prompt = (
        f"Fields needed:\n{field_list}\n\n"
        f"Already collected: {already}\n\n"
        f"New message: {message}"
    )
    try:
        data = await gemini_chat_completion_json(
            system_prompt=_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=300,
            tenant_id=tenant_id,
            purpose="expert_handoff_extraction",
        )
    except Exception as e:
        logger.warning(f"Intake extraction failed, keeping existing collected_data: {e}")
        return dict(collected_data)

    fields_by_key = {f["key"]: f for f in fields}
    new_values = {}
    for k, v in data.items():
        field = fields_by_key.get(k)
        if field is None or not v:
            continue
        # A "choice" field's options are a closed set the tenant configured in
        # Settings -- accepting anything the LLM hands back defeats the point of
        # configuring options at all. Case-insensitive match against the configured
        # spelling, then normalize to it so the summary/receipt always shows the
        # tenant's own wording rather than whatever casing the customer typed.
        # Unmatched free text is dropped, same fail-closed shape as match_package:
        # the field stays unanswered and gets re-asked rather than silently accepting
        # an option that doesn't exist.
        options = field.get("options") if field.get("type") == "choice" else None
        if options:
            match = next((opt for opt in options if str(v).strip().lower() == opt.strip().lower()), None)
            if match is None:
                continue
            v = match
        new_values[k] = v
    return {**collected_data, **new_values}


def normalize_packages(config: dict) -> list[dict]:
    """The tenant's packages, with the pre-packages single `amount_paise` config
    auto-migrated to one 'standard' package so an existing tenant keeps working
    without touching their settings."""
    packages = config.get("packages") or []
    if packages:
        return [dict(p) for p in packages]
    legacy_fee = config.get("amount_paise") or 0
    if legacy_fee > 0:
        return [{
            "key": "standard",
            "name": "Consultation",
            "amount_paise": legacy_fee,
            "description": "",
        }]
    return []


def _rupees(amount_paise: int) -> str:
    """Whole rupees when the amount is exact, two decimals otherwise."""
    if amount_paise % 100 == 0:
        return f"₹{amount_paise // 100}"
    return f"₹{amount_paise / 100:.2f}"


def package_list_block(packages: list[dict]) -> str:
    """Rendered in Python, never by the LLM: these are prices the customer will
    be held to, and a hallucinated figure is a real liability. The surrounding
    intro/question are composed in the tenant's language by intake_copy.

    A non-leaf entry (has `options`) shows no price -- its true price depends on
    which leaf under it gets picked, so `amount_paise` on a non-leaf is display-only
    and would be misleading here."""
    lines = []
    for p in packages:
        if p.get("options"):
            line = f"• {p['name']}"
        else:
            line = f"• {p['name']} — {_rupees(p['amount_paise'])}"
        if p.get("description"):
            line += f"\n  {p['description']}"
        lines.append(line)
    return "\n".join(lines)


def package_list_message(packages: list[dict], service_noun: str) -> str:
    """English-only wrapper, kept for callers outside route_intake."""
    return (
        f"Here are our {service_noun} options:\n\n"
        + package_list_block(packages)
        + "\n\nWhich one would you like?"
    )


def _active_children(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if n.get("active", True)]


def _resolve_choice(level: list[dict], path: list[dict]) -> tuple[str, dict | list[dict], list[dict]]:
    """Resolve what the bot should do at a given menu level, auto-descending
    through any chain of single-active-option levels -- this is the recursive
    generalization of the old root-only "if len(packages) == 1: auto-select" rule.

    Returns one of:
      ("leaf", node, path)      -- a single purchasable package was resolved
      ("choose", [nodes], path) -- 2+ active options, ask the lead to pick
      ("empty", [], path)       -- zero active options at this level (misconfigured)
    `path` is the breadcrumb [{key, name}, ...] from root to here."""
    active = _active_children(level)
    if not active:
        return ("empty", [], path)
    if len(active) == 1:
        only = active[0]
        new_path = path + [{"key": only["key"], "name": only["name"]}]
        if only.get("options"):
            return _resolve_choice(only["options"], new_path)
        return ("leaf", only, new_path)
    return ("choose", active, path)


def _menu_at_path(packages: list[dict], path: list[dict]) -> list[dict]:
    """Re-derive the menu the lead is currently looking at, by walking the live
    config from root using the keys already confirmed in `path`. Always re-derived
    rather than cached, so an operator editing packages mid-conversation can't
    leave the lead looking at a stale menu."""
    level = packages
    for step in path:
        match = next((n for n in level if n.get("key") == step["key"]), None)
        level = match["options"] if match and match.get("options") else []
    return level


def _find_leaf(packages: list[dict], key: str, path: list[dict] | None = None) -> tuple[dict, list[dict]] | None:
    """Depth-first search for a leaf package by key anywhere in the tree,
    returning it with its breadcrumb. Used when a session already has a
    package_key and the bot needs to look up that leaf's current addons, or
    when an operator repoints a session at any leaf regardless of depth."""
    path = path or []
    for node in packages:
        node_path = path + [{"key": node["key"], "name": node["name"]}]
        if node.get("options"):
            found = _find_leaf(node["options"], key, node_path)
            if found:
                return found
        elif node["key"] == key:
            return (node, node_path)
    return None


_PACKAGE_MATCH_SYSTEM_PROMPT = """You match a customer's reply to one of a fixed list of
packages. You are given the packages (key and name) and the customer's message.

Respond with JSON only: {"key": "<the matching package key>"} or {"key": null} if the
message does not clearly indicate one of the listed packages.

Rules:
- The key MUST be one of the keys given. Never invent a key.
- If the customer is ambiguous or asking a question rather than choosing, return null.
- JSON only, no other text."""


async def match_package(
    message: str, packages: list[dict], tenant_id: str, interactive_id: str | None = None,
) -> dict | None:
    """Match a lead's free-text reply to one configured package. Exact name or key
    matches short-circuit the LLM. Fails closed: any error or unknown key returns
    None so the caller re-asks rather than charging the wrong amount.

    interactive_id is the WhatsApp button/list row id the lead actually tapped
    (button_reply.id / list_reply.id) -- _build_buttons/_build_list_sections set it
    to the package's own key (intake.py's builders), so it is the one value that
    survives a button_label shorter than the name, or a list row title truncated to
    WhatsApp's 24-char cap, both of which break a text-only match against name/key.
    Checked first because it's exact and free; only an id that doesn't match any
    CURRENT option (a stale tap from an earlier/different menu) falls through to the
    text match below rather than being trusted blindly."""
    if not packages:
        return None

    if interactive_id:
        for p in packages:
            if interactive_id == p["key"]:
                return dict(p)

    cleaned = message.strip().lower()
    for p in packages:
        if cleaned == p["name"].strip().lower() or cleaned == p["key"].strip().lower():
            return dict(p)

    package_list = "\n".join(f"- {p['key']}: {p['name']}" for p in packages)
    try:
        data = await gemini_chat_completion_json(
            system_prompt=_PACKAGE_MATCH_SYSTEM_PROMPT,
            user_prompt=f"Packages:\n{package_list}\n\nCustomer message: {message}",
            temperature=0.0,
            max_tokens=50,
            tenant_id=tenant_id,
            purpose="intake_package_match",
        )
    except Exception as e:
        logger.warning(f"Intake package match failed, treating as no-match: {e}")
        return None

    key = data.get("key")
    for p in packages:
        if key == p["key"]:
            return dict(p)
    return None


def addon_list_block(addons: list[dict]) -> str:
    """Same non-LLM-rendered-price principle as package_list_block -- see its
    docstring."""
    lines = []
    for a in addons:
        line = f"• {a['name']} — +{_rupees(a['amount_paise'])}"
        if a.get("description"):
            line += f"\n  {a['description']}"
        lines.append(line)
    return "\n".join(lines)


_BUTTON_TITLE_MAX = 20
_LIST_ROW_TITLE_MAX = 24


def _short_label(node: dict, limit: int) -> str | None:
    label = node.get("button_label") or node["name"]
    return label if len(label) <= limit else None


def _tap_mode(level: list[dict]) -> str:
    """Pure Python, no LLM -- same rule as prices never being LLM-authored.
    Returns "buttons", "list", or "text". Buttons are for exactly two options whose
    titles are <=20 chars (WhatsApp's real cap, same rule as choices.build_menu). Any
    other count from 2-10 falls to a list, which always renders (see _row_title's
    truncation fallback) rather than ever giving up on tappability over label length alone.
    Only outside 2-10 -- zero/one option, or more than WhatsApp's 10-row list cap
    -- is genuinely unfixable in code and stays "text"."""
    n = len(level)
    if n == 2 and all(_short_label(item, _BUTTON_TITLE_MAX) for item in level):
        return "buttons"
    if 2 <= n <= 10:
        return "list"
    return "text"


def _build_buttons(level: list[dict]) -> list[dict]:
    return [{"id": item["key"], "title": _short_label(item, _BUTTON_TITLE_MAX)} for item in level]


def _row_title(node: dict) -> str:
    """List rows are the last tappable option before plain text -- unlike a button,
    which only renders when _tap_mode already confirmed a clean fit, a list row
    still needs a title even when the configured name/button_label is longer than
    WhatsApp's 24-char row cap. Truncating (rather than failing) is what lets
    _tap_mode treat every 2-10 option level as tappable, never falling through to
    unclickable text over label length alone."""
    label = node.get("button_label") or node["name"]
    if len(label) <= _LIST_ROW_TITLE_MAX:
        return label
    return label[: _LIST_ROW_TITLE_MAX - 1].rstrip() + "…"


def _build_list_sections(level: list[dict]) -> list[dict]:
    return [{"rows": [
        {"id": item["key"], "title": _row_title(item)}
        for item in level
    ]}]


_ADDON_DECLINE_WORDS = frozenset({"no", "skip", "none", "no thanks", "nope", "not needed"})

# Tap target for declining every addon -- its title is one of _ADDON_DECLINE_WORDS
# above (case-insensitive), so match_addons's early-exit decline check catches it
# with no extra wiring: the tap just becomes the same body text a typed "no thanks" would.
_NO_ADDONS_OPTION = {"key": "no_addons", "name": "No thanks"}

_ADDON_MATCH_SYSTEM_PROMPT = """You match a customer's reply to zero or more addons from a
fixed list. You are given the addons (key and name) and the customer's message.

Respond with JSON only: {"keys": ["<matching addon keys>"]} -- an empty list if the customer
declined, said no/skip/none, or didn't clearly choose any of the listed addons.

Rules:
- Every key in the list MUST be one of the keys given. Never invent a key.
- If ambiguous, return an empty list rather than guessing.
- JSON only, no other text."""


async def match_addons(
    message: str, addons: list[dict], tenant_id: str, interactive_id: str | None = None,
) -> list[dict]:
    """Match a lead's free-text reply to zero or more configured addons.
    Multi-select, unlike match_package -- an empty result is a valid, common
    outcome (the lead declined all addons), not a failure to re-ask about.

    interactive_id: see match_package's docstring -- same id-first, same reasoning.
    A tap is always a single row, so a matching id resolves to exactly one addon (or
    zero, for the synthetic "no thanks" decline option). A non-matching id (stale
    tap) falls through to text matching rather than being trusted blindly."""
    if not addons:
        return []

    if interactive_id:
        if interactive_id == _NO_ADDONS_OPTION["key"]:
            return []
        for a in addons:
            if interactive_id == a["key"]:
                return [a]

    if message.strip().lower() in _ADDON_DECLINE_WORDS:
        return []

    addon_list = "\n".join(f"- {a['key']}: {a['name']}" for a in addons)
    try:
        data = await gemini_chat_completion_json(
            system_prompt=_ADDON_MATCH_SYSTEM_PROMPT,
            user_prompt=f"Addons:\n{addon_list}\n\nCustomer message: {message}",
            temperature=0.0,
            max_tokens=100,
            tenant_id=tenant_id,
            purpose="intake_addon_match",
        )
    except Exception as e:
        logger.warning(f"Intake addon match failed, treating as no addons chosen: {e}")
        return []

    keys = set(data.get("keys") or [])
    return [a for a in addons if a["key"] in keys]


_ACTIVE_STATUSES = (
    "offer_pending", "awaiting_package_choice", "awaiting_addon_choice", "collecting",
    "awaiting_confirmation", "awaiting_payment", "paid",
)

_PACKAGE_CHANGEABLE_STATUSES = (
    "awaiting_package_choice", "awaiting_addon_choice", "collecting", "awaiting_confirmation", "awaiting_payment",
)


def _get_active_session(lead_id: str, tenant_id: str, db) -> dict | None:
    result = (
        db.table("intake_sessions")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("tenant_id", tenant_id)
        .neq("status", "resolved")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    active = [r for r in rows if r["status"] in _ACTIVE_STATUSES]
    return active[0] if active else None


# Statuses that end a session; migration 213 allows one session per (tenant, lead) outside these.
_CLOSED_STATUSES = ("paid", "cancelled", "resolved")


def _is_unique_violation(error: Exception) -> bool:
    """Postgres 23505, as postgrest-py's APIError carries it (or its text, if wrapped)."""
    return getattr(error, "code", None) == "23505" or "23505" in str(error)


def _create_session(lead_id: str, tenant_id: str, db) -> dict:
    """Open a session for a lead. Two racing inbound messages both try to; the 213 unique index
    lets one win, and the loser gets the winner's open session back instead of an exception."""
    try:
        result = (
            db.table("intake_sessions")
            .insert({
                "lead_id": lead_id, "tenant_id": tenant_id, "status": "offer_pending", "collected_data": {},
                "last_activity_at": _now_iso(),
            })
            .execute()
        )
    except Exception as e:
        if not _is_unique_violation(e):
            raise
        existing = (
            db.table("intake_sessions")
            .select("*")
            .eq("lead_id", lead_id)
            .eq("tenant_id", tenant_id)
            .not_.in_("status", list(_CLOSED_STATUSES))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        if not existing:
            raise
        logger.info(f"Racing session create for lead {lead_id} (tenant {tenant_id}): using the open session")
        return existing[0]
    return result.data[0]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Statuses a session can sit in before it is paid: the idle-close sweep covers all of them.
_UNFINISHED_STATUSES = ("offer_pending", *_PACKAGE_CHANGEABLE_STATUSES)

_PROGRESS_KEYS = frozenset({"package_key", "collected_data", "skipped_fields", "selected_addons"})


def _is_progress(patch: dict) -> bool:
    """A write that means the lead really moved the deal on (D3): an offering picked, details
    saved, a link created, paid. Cancelling, clearing a link or a status-only nudge is not."""
    return bool(
        _PROGRESS_KEYS & patch.keys() or patch.get("payment_link") or patch.get("status") == "paid"
    )


def touch_session_activity(db, tenant_id: str, session_id: str) -> None:
    """Restart the idle-close clock of one unfinished session. Tenant-scoped; the status
    filter keeps a closed or paid session from being revived by a stray message."""
    (
        db.table("intake_sessions")
        .update({"last_activity_at": _now_iso()})
        .eq("id", session_id)
        .eq("tenant_id", tenant_id)
        .in_("status", list(_UNFINISHED_STATUSES))
        .execute()
    )


def note_lead_message(db, tenant_id: str, lead_id: str) -> str | None:
    """A lead message arrived: restart the idle clock of their open deal and return the value
    it had BEFORE (None when there is no open deal), so the reply can tell how long they were
    away. Call it first thing, before any progress write moves the clock. Never raises."""
    try:
        rows = (
            db.table("intake_sessions")
            .select("id,last_activity_at,created_at")
            .eq("lead_id", lead_id)
            .eq("tenant_id", tenant_id)
            .in_("status", list(_UNFINISHED_STATUSES))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        if not rows:
            return None
        touch_session_activity(db, tenant_id, rows[0]["id"])
        return rows[0].get("last_activity_at") or rows[0].get("created_at")
    except Exception as e:
        logger.warning(f"Activity touch failed for lead {lead_id}: {e}")
        return None


_PREVIOUS_LOOKBACK = 5


def previous_booking(db, tenant_id: str, lead_id: str) -> dict | None:
    """The lead's most recent finished booking that holds details (cancelled, paid or
    resolved), for D6: offered back to them to confirm or correct, never reused silently.
    Tenant-scoped. Never raises."""
    try:
        rows = (
            db.table("intake_sessions")
            .select("package_name,collected_data,status")
            .eq("lead_id", lead_id)
            .eq("tenant_id", tenant_id)
            .in_("status", ["cancelled", "paid", "resolved"])
            .order("created_at", desc=True)
            .limit(_PREVIOUS_LOOKBACK)
            .execute()
        ).data or []
        return next((r for r in rows if any((r.get("collected_data") or {}).values())), None)
    except Exception as e:
        logger.warning(f"Previous booking lookup failed for lead {lead_id}: {e}")
        return None


def _update_session(session_id: str, patch: dict, db, unless_status: str | None = None) -> bool:
    """unless_status: skip the write if the session is already in that status, so a slow
    caller (a Razorpay call in between) cannot undo a webhook that just moved it there.
    Real progress also restarts the idle clock (last_activity_at).
    Returns whether a row was written (False when unless_status skipped it)."""
    if _is_progress(patch):
        patch = {**patch, "last_activity_at": _now_iso()}
    query = db.table("intake_sessions").update(patch).eq("id", session_id)
    if unless_status:
        query = query.neq("status", unless_status)
    result = query.execute()
    if "status" in patch:
        _sync_deal(result, db)
    return bool(getattr(result, "data", None))


def _sync_deal(update_result, db, lost_reason: str | None = None) -> None:
    """Mirror the session rows an UPDATE just returned onto their Deals-board
    deal (services/deals.sync_intake_session). Uses the returned rows rather
    than re-reading, so the conversation path pays for no extra query. Never
    raises: the Deals board is a view of this flow and must never break the
    WhatsApp conversation."""
    try:
        rows = getattr(update_result, "data", None)
        if not isinstance(rows, list):
            return
        from app.services.deals import sync_intake_session
        for row in rows:
            if isinstance(row, dict) and row.get("tenant_id") and row.get("status"):
                sync_intake_session(row, db=db, lost_reason=lost_reason)
    except Exception as e:
        logger.warning(f"Deal sync failed after intake update: {e}")


def link_store_patch(link: dict) -> dict:
    """The intake_sessions columns that record a freshly created Razorpay link. The Razorpay id
    is what the webhook compares against, so an event for a replaced link can be told apart."""
    return {
        "payment_link": link["payment_link_url"],
        "razorpay_payment_link_id": link.get("razorpay_payment_link_id"),
        "payment_link_expires_at": link.get("payment_link_expires_at"),
    }


def legacy_link_key(session: dict) -> str:
    """Idempotency key for the scripted flow's link. Razorpay replays the original link for a
    repeated key, so once a link has existed (and may have been cancelled) the key carries
    that link's id: a re-link then makes a genuinely new link."""
    previous = session.get("razorpay_payment_link_id")
    if not previous:
        return f"booking:{session['id']}:payment_link"
    return f"booking:{session['id']}:{previous}:payment_link"


async def cancel_session_link(db, session: dict, *, keep_plink_id: str | None = None) -> bool:
    """Best-effort: cancel the session's outstanding Razorpay link so it can't be paid after
    it was replaced or the deal was closed. Call it AFTER the replacement link is stored (or
    the session is closed) so a failed cancel never leaves the lead without a link.

    `session` is the row as it was BEFORE the change. Skips (False) when there is nothing
    outstanding: no stored Razorpay id, no link, a link already past its expiry, or
    keep_plink_id equal to it (Razorpay replayed the same link). Never raises; a cancel
    Razorpay refuses (an already-paid link) is left to the paid webhook."""
    try:
        if "razorpay_payment_link_id" in session:
            plink_id = session.get("razorpay_payment_link_id")
        else:
            row = (
                db.table("intake_sessions").select("razorpay_payment_link_id")
                .eq("id", session["id"]).eq("tenant_id", session["tenant_id"])
                .maybe_single().execute()
            )
            plink_id = ((row.data if row else None) or {}).get("razorpay_payment_link_id")
        if not plink_id or plink_id == keep_plink_id or not session.get("payment_link"):
            return False
        from app.services.deal_engine import parse_time
        expires_at = parse_time(session.get("payment_link_expires_at"))
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            return False
        return await cancel_payment_link(plink_id, session["tenant_id"])
    except Exception as e:
        logger.warning(f"Cancel of the old link failed for session {session.get('id')}: {e}")
        return False


def _package_patch(package: dict, path: list[dict] | None = None, total_amount_paise: int | None = None) -> dict:
    """Snapshot the chosen package onto the session row. Repricing or renaming a
    package later must not rewrite what a past lead was actually offered."""
    patch = {
        "package_key": package["key"],
        "package_name": package["name"],
        "package_amount_paise": package["amount_paise"],
    }
    if path is not None:
        patch["package_path"] = path
    if total_amount_paise is not None:
        patch["total_amount_paise"] = total_amount_paise
    return patch


async def _send_and_log(phone: str, text: str, tenant_id: str, lead_id: str, db) -> None:
    """Send, then log. The WhatsApp send is the customer-facing side effect and
    cannot be undone -- a failure logging it afterward (e.g. a CHECK-constraint
    violation on messages.reply_source) must never raise, or route_intake's
    caller sees this turn as unconsumed and generate_reply() sends a second,
    unrelated reply on top of the one that already reached the customer."""
    from app.services.ai_reply import send_whatsapp
    mid = await send_whatsapp(phone, text, tenant_id=tenant_id)
    try:
        db.table("messages").insert({
            "lead_id": lead_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "channel": "whatsapp",
            "content": text,
            "is_ai_generated": True,
            "meta_message_id": mid,
            "reply_source": "expert_handoff",
        }).execute()
    except Exception:
        logger.exception(
            "Intake message send succeeded but logging it failed for lead %s -- "
            "message was delivered, this is an audit-trail gap only", lead_id,
        )


async def _send_buttons_and_log(phone: str, body_text: str, buttons: list[dict], tenant_id: str, lead_id: str, db) -> None:
    """Same non-raising-into-caller contract as _send_and_log -- see its docstring."""
    from app.services.meta_cloud import send_interactive_buttons
    data = await send_interactive_buttons(phone, body_text, buttons, tenant_id=tenant_id)
    mid = (data.get("messages") or [{}])[0].get("id")
    logged_text = body_text + "\n\n" + "  ".join(f"[{b['title']}]" for b in buttons)
    try:
        db.table("messages").insert({
            "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound",
            "channel": "whatsapp", "content": logged_text, "is_ai_generated": True,
            "meta_message_id": mid, "reply_source": "expert_handoff",
        }).execute()
    except Exception:
        logger.exception(
            "Intake button message send succeeded but logging it failed for lead %s -- "
            "message was delivered, this is an audit-trail gap only", lead_id,
        )


async def _send_list_and_log(phone: str, body_text: str, button_text: str, sections: list[dict], tenant_id: str, lead_id: str, db) -> None:
    """Same non-raising-into-caller contract as _send_and_log -- see its docstring."""
    from app.services.meta_cloud import send_list_message
    data = await send_list_message(phone, body_text, button_text, sections, tenant_id=tenant_id)
    mid = (data.get("messages") or [{}])[0].get("id")
    row_titles = [row["title"] for section in sections for row in section.get("rows") or []]
    logged_text = body_text + "\n\n" + "  ".join(f"[{t}]" for t in row_titles)
    try:
        db.table("messages").insert({
            "lead_id": lead_id, "tenant_id": tenant_id, "direction": "outbound",
            "channel": "whatsapp", "content": logged_text, "is_ai_generated": True,
            "meta_message_id": mid, "reply_source": "expert_handoff",
        }).execute()
    except Exception:
        logger.exception(
            "Intake list message send succeeded but logging it failed for lead %s -- "
            "message was delivered, this is an audit-trail gap only", lead_id,
        )


# Roman-script Tamil is deliberately included: the moment the offer message is
# written in Tanglish, leads answer in Tanglish ("seri", "aama"), and anything
# unmatched here is treated as a refusal that cancels the session and loses the
# sale. Spellings vary a lot in real chat, so the common ones are all listed.
# Deliberately excluded: bare verbs like "pannunga"/"venum", which appear just as
# often in requests that are not a yes ("call pannunga").
_AFFIRMATIVE_RE_WORDS = frozenset({
    # English
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "okey", "correct", "right", "fine",
    # Tanglish / romanized Tamil
    "seri", "sari", "seriyaa", "seriya", "aama", "aamaa", "aamam", "ama", "amaam", "nalladhu",
    # Tamil script
    "ஆம்", "சரி", "ஆமாம்",
    # Hindi
    "हाँ", "ठीक", "haan", "theek", "thik",
})


def _is_affirmative(message: str) -> bool:
    import re
    tokens = set(re.findall(r"[\w஀-௿ऀ-ॿ]+", message.strip().lower()))
    return bool(tokens & _AFFIRMATIVE_RE_WORDS)


# A plain "no"/"no thanks"/"nah" is a clear refusal of the offer, but none of
# these are withdrawal words in the mid-flow sense _CANCEL_WORDS covers (that
# set is "vendaam"/"stop"/"later" -- words for backing out of something already
# started, not this-specific-yes/no-question negatives). Kept separate and
# equally small/exact-match for the same reason _AFFIRMATIVE_RE_WORDS is: a
# false positive here silently loses a sale, so only unambiguous "no" tokens
# belong in it.
_NEGATIVE_RE_WORDS = frozenset({
    "no", "nah", "nope", "never",
    "illa", "venda", "இல்லை", "नहीं", "nahi",
})


def _is_explicit_negative(message: str) -> bool:
    import re
    tokens = set(re.findall(r"[\w஀-௿ऀ-ॿ]+", message.strip().lower()))
    return bool(tokens & _NEGATIVE_RE_WORDS)


def _summary_block(fields: list[dict], collected_data: dict, skipped=()) -> str:
    """The collected values, rendered in Python. Never LLM-written -- these are the
    details the expert works from, and a rewritten value is a wrong reading. A field
    the lead could not answer is marked distinctly from one still blank."""
    skipped_set = set(skipped)
    lines = []
    for f in fields:
        value = collected_data.get(f["key"])
        if not value:
            value = "— (not provided)" if f["key"] in skipped_set else "—"
        lines.append(f"{f['label']}: {value}")
    return "\n".join(lines)


async def route_intake(
    lead_id: str, tenant_id: str, phone: str, body: str, db=None, interactive_id: str | None = None,
) -> bool:
    """Webhook-level routing for the intake session. Returns True if the
    inbound message was consumed (caller must skip generate_reply for this turn).

    interactive_id is the button/list row id from a WhatsApp button tap
    (button_reply.id / list_reply.id), when the inbound message was a tap rather
    than typed text. See match_package's docstring for why this matters."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    if not body:
        return False

    try:
        config = get_intake_config(tenant_id, db=db)
        if not config.get("enabled"):
            return False

        session = _get_active_session(lead_id, tenant_id, db)

        # Resolved once per turn and shared by every line this turn may send.
        language_mode = resolve_language_mode(lead_id, tenant_id, db)
        thread, knowledge = await gather_context(db, lead_id, tenant_id, body)
        brain_prompt = collector_identity(db, lead_id, tenant_id, body)

        async def _say(purpose: str, collected: dict | None = None, **kwargs) -> None:
            text = await compose_line(
                purpose,
                tenant_id=tenant_id,
                language_mode=language_mode,
                customer_message=body,
                thread=thread,
                knowledge=knowledge,
                brain_prompt=brain_prompt,
                collected=collected if collected is not None else (session.get("collected_data") or {}),
                **kwargs,
            )
            await _send_and_log(phone, text, tenant_id, lead_id, db)

        async def _say_summary(collected: dict, skipped=()) -> None:
            fields = await localized_fields(config["fields"], language_mode, tenant_id)
            text = await compose_wrapped(
                "summary",
                tenant_id=tenant_id,
                language_mode=language_mode,
                customer_message=body,
                block=_summary_block(fields, collected, skipped),
                thread=thread,
            )
            await _send_and_log(phone, text, tenant_id, lead_id, db)

        async def _send_menu(purpose: str, level: list[dict], selected: dict | None = None) -> None:
            # Addons are optional -- unlike a package pick, "none of these" is a valid
            # tap, not just a typed decline. Fold it into the tier math as a real option
            # so it never pushes a menu over WhatsApp's 3-button/10-row hard caps.
            tap_level = level + [_NO_ADDONS_OPTION] if purpose == "addons" and level else level
            mode = _tap_mode(tap_level)
            block = package_list_block(level) if purpose == "packages" else addon_list_block(level)
            if selected:
                # A single-active-child branch (e.g. "Career Reading") auto-skips straight
                # to its leaf ("General Career Reading") without ever asking again -- so
                # the customer's last message still names the branch, not the leaf. Render
                # the resolved leaf as a fact here instead of letting the composer guess
                # "what was picked" from that stale customer_message.
                fact = f"{selected['name']} — {_rupees(selected['amount_paise'])}"
                if selected.get("description"):
                    fact += f"\n{selected['description']}"
                block = f"{fact}\n\n{block}"
            text = await compose_wrapped(
                purpose, tenant_id=tenant_id, language_mode=language_mode,
                customer_message=body, block=block, thread=thread,
            )
            try:
                if mode == "buttons":
                    await _send_buttons_and_log(phone, text, _build_buttons(tap_level), tenant_id, lead_id, db)
                elif mode == "list":
                    await _send_list_and_log(phone, text, "Choose", _build_list_sections(tap_level), tenant_id, lead_id, db)
                else:
                    await _send_and_log(phone, text, tenant_id, lead_id, db)
            except Exception:
                # Never lose the turn over a WhatsApp API failure on the tappable
                # send -- same reasoning as ai_reply.py's quick-reply-block fallback
                # (ai_reply.py:1952-1961). Without this, the caller's _update_session
                # write that already committed the new status/path leaves the session
                # one step ahead of what the customer actually received, and the
                # customer gets nothing at all for this turn. Fall back to the same
                # options as plain text, which _send_and_log's own contract guarantees
                # won't raise a second time into route_intake.
                logger.exception(
                    "Intake menu send (%s) failed for lead %s -- falling back to plain text", mode, lead_id,
                )
                await _send_and_log(phone, f"{text}\n\n{block}", tenant_id, lead_id, db)

        async def _finalize_leaf(leaf: dict, path: list[dict]) -> None:
            active_addons = _active_children(leaf.get("addons") or [])
            if active_addons:
                _update_session(session["id"], _package_patch(leaf, path) | {"status": "awaiting_addon_choice"}, db)
                await _send_menu("addons", active_addons, selected=leaf)
                return
            collected = await extract_fields(body, config["fields"], session.get("collected_data") or {}, tenant_id)
            missing = missing_field_labels(config["fields"], collected)
            patch = _package_patch(leaf, path, total_amount_paise=leaf["amount_paise"]) | {
                "collected_data": collected, "field_schema": config["fields"],
            }
            if missing:
                _update_session(session["id"], patch | {"status": "collecting"}, db)
                await _say("ask_field", field_label=missing[0], collected=collected)
            else:
                _update_session(session["id"], patch | {"status": "awaiting_confirmation"}, db)
                await _say_summary(collected)

        # An explicit "let me talk to a human" mid-intake used to be unreachable:
        # a consumed turn returns before generate_reply() ever runs, and that's
        # the only place escalation-trigger detection lived. classify_non_answer
        # still gets first say so an explicit withdrawal ("stop", "cancel") is
        # never misread as a handoff request. The intake session itself is left
        # completely untouched -- status, collected_data, ask_attempts all
        # unchanged -- so the next inbound resumes exactly where it stopped;
        # this is "paused" without a new status value or a migration. Excludes
        # 'paid': that status already returns False further down and reaches
        # generate_reply(), whose own Trigger C (ai_reply.py:1549) covers it.
        if session is not None and session["status"] != "paid" and classify_non_answer(body) != "cancel":
            from app.services.ai_reply import _HUMAN_REQUEST_RE
            if _HUMAN_REQUEST_RE.search(body):
                existing_handover = (
                    db.table("chat_handovers")
                    .select("id")
                    .eq("lead_id", lead_id)
                    .eq("status", "pending")
                    .limit(1)
                    .execute()
                )
                if not (existing_handover and existing_handover.data):
                    from app.services.ai_reply import _trigger_chat_escalation
                    lead_row = db.table("leads").select("assigned_to").eq("id", lead_id).maybe_single().execute()
                    assigned_to = (lead_row.data or {}).get("assigned_to") if lead_row else None
                    _trigger_chat_escalation(lead_id, "User requested a human agent", tenant_id, assigned_to, db)
                    await _say("human_handoff")
                    return True
                # A pending handover already exists -- don't send a second
                # reassurance, let the normal status dispatch below continue so
                # an already-escalated lead can still finish paying.

        if session is None:
            matched = await detect_intake_intent(body, config["trigger_description"], tenant_id)
            if not matched:
                return False
            new_session = _create_session(lead_id, tenant_id, db)
            _update_session(new_session["id"], {"trigger_reason": body[:500]}, db)
            await _send_and_log(phone, config["offer_message"], tenant_id, lead_id, db)
            return True

        status = session["status"]

        if status == "offer_pending":
            if not _is_affirmative(body):
                # An explicit withdrawal ("stop", "vendaam", "cancel") ends the offer.
                # Anything else -- "interested", "how much", a stray question -- is not
                # a refusal, so re-ask instead of killing the session on one ambiguous
                # reply. Every later stage of the flow re-asks on a miss; this is the
                # only one that used to cancel outright. Live evidence 2026-09-09: a
                # lead replying "interested, tell me more" to the offer had their
                # session silently cancelled and got a generic AI reply instead.
                if classify_non_answer(body) == "cancel" or _is_explicit_negative(body):
                    _update_session(session["id"], {"status": "cancelled"}, db)
                    return False
                await _say("offer_reask")
                return True
            packages = normalize_packages(config)
            outcome, result, path = _resolve_choice(packages, [])
            if outcome == "empty":
                logger.error(f"Intake session {session['id']} has no active packages configured despite being enabled")
                await _say("no_packages")
                return True
            if outcome == "leaf":
                await _finalize_leaf(result, path)
                return True
            _update_session(session["id"], {"status": "awaiting_package_choice", "package_draft_path": path}, db)
            await _send_menu("packages", result)
            return True

        if status == "awaiting_package_choice":
            packages = normalize_packages(config)
            draft_path = session.get("package_draft_path") or []
            current_level = _menu_at_path(packages, draft_path) or packages
            active_here = _active_children(current_level)
            if classify_non_answer(body) == "cancel":
                _update_session(session["id"], {"status": "cancelled"}, db)
                logger.info(f"Intake session {session['id']} cancelled by lead during package choice")
                return False
            chosen = await match_package(body, active_here, tenant_id, interactive_id=interactive_id)
            if chosen is None:
                intro = await compose_line(
                    "package_reask",
                    tenant_id=tenant_id,
                    language_mode=language_mode,
                    customer_message=body,
                    thread=thread,
                    knowledge=knowledge,
                )
                await _send_and_log(
                    phone,
                    f"{intro}\n\n{package_list_block(active_here)}",
                    tenant_id, lead_id, db,
                )
                return True
            outcome, result, path = _resolve_choice([chosen], draft_path)
            if outcome == "empty":
                logger.error(f"Intake session {session['id']} package {chosen['key']} has no active options")
                await _say("no_packages")
                return True
            if outcome == "leaf":
                await _finalize_leaf(result, path)
                return True
            _update_session(session["id"], {"package_draft_path": path}, db)
            await _send_menu("packages", result)
            return True

        if status == "awaiting_addon_choice":
            packages = normalize_packages(config)
            found = _find_leaf(packages, session.get("package_key"))
            leaf = found[0] if found else None
            if leaf is None:
                # The package this session snapshotted no longer exists in the
                # tenant's current config -- e.g. the operator replaced the package
                # list after this lead paused mid-flow. Showing the addon menu here
                # would render the wrapper's intro/question around an empty block
                # forever (no package fact, no addons to list) -- live evidence
                # 2026-09-25: a lead stuck replying "hii" to a blank "pick your
                # add-ons" bubble for a package (general_career_reading) deleted a
                # month earlier, since this status has no staleness sweep (see
                # sweep_stale_intake_sessions). Cancel instead and fall through to
                # a normal reply / a fresh offer on the next matching intent.
                _update_session(session["id"], {"status": "cancelled"}, db)
                logger.warning(
                    f"Intake session {session['id']} cancelled -- package_key "
                    f"{session.get('package_key')!r} no longer in tenant {tenant_id} config"
                )
                return False
            active_addons = _active_children(leaf.get("addons") or [])

            is_decline = body.strip().lower() in _ADDON_DECLINE_WORDS
            if not is_decline and classify_non_answer(body) == "cancel":
                _update_session(session["id"], {"status": "cancelled"}, db)
                logger.info(f"Intake session {session['id']} cancelled by lead during addon choice")
                return False

            chosen_addons = [] if is_decline else await match_addons(body, active_addons, tenant_id, interactive_id=interactive_id)
            if not is_decline and not chosen_addons:
                # An empty match_addons result is ambiguous -- explicit decline or
                # simply no match -- so is_decline above is what actually decides
                # "the customer said no". Anything else that matched nothing (a
                # greeting, a question, an off-topic reply like "career reading")
                # re-shows the offer instead of silently treating silence as "no
                # thanks", matching package choice's own reask-until-resolved
                # behaviour rather than guessing on the customer's behalf.
                await _send_menu("addons", active_addons, selected=leaf)
                return True

            addons_total = sum(a["amount_paise"] for a in chosen_addons)
            total = (session.get("package_amount_paise") or 0) + addons_total
            collected = await extract_fields(body, config["fields"], session.get("collected_data") or {}, tenant_id)
            missing = missing_field_labels(config["fields"], collected)
            patch = {
                "selected_addons": chosen_addons,
                "total_amount_paise": total,
                "collected_data": collected,
                "field_schema": config["fields"],
            }
            if missing:
                _update_session(session["id"], patch | {"status": "collecting"}, db)
                await _say("ask_field", field_label=missing[0], collected=collected)
            else:
                _update_session(session["id"], patch | {"status": "awaiting_confirmation"}, db)
                await _say_summary(collected)
            return True

        if status == "collecting":
            before = session.get("collected_data") or {}
            collected = await extract_fields(body, config["fields"], before, tenant_id)
            attempts = dict(session.get("ask_attempts") or {})
            skipped = list(session.get("skipped_fields") or [])
            pending = pending_fields(config["fields"], collected, skipped)

            purpose = "ask_field"
            given_up_label: str | None = None
            if pending and collected == before:
                # This message added nothing -- but that does not make it a failed
                # attempt at the pending field. Only a genuine try counts toward the
                # skip ceiling; a greeting or a question is answered on its own terms
                # and leaves the counter alone, and a withdrawal ends the flow.
                kind = classify_non_answer(body)
                if kind == "cancel":
                    _update_session(session["id"], {"status": "cancelled"}, db)
                    logger.info(f"Intake session {session['id']} cancelled by lead during collection")
                    return False
                if kind == "greeting":
                    purpose = "greeting_reask"
                elif kind == "question":
                    purpose = "reask_field"
                else:
                    # After _MAX_FIELD_ATTEMPTS give up on the field rather than asking
                    # a third time -- live evidence 2026-08-12: the same question went
                    # out three times to a lead who had twice said they did not know it.
                    key = pending[0]["key"]
                    attempts[key] = attempts.get(key, 0) + 1
                    if attempts[key] >= _MAX_FIELD_ATTEMPTS:
                        given_up_label = pending[0]["label"]
                        skipped.append(key)
                        pending = pending_fields(config["fields"], collected, skipped)
                        purpose = "skip_field"
                    else:
                        purpose = "reask_field"

            patch = {
                "collected_data": collected,
                "ask_attempts": attempts,
                "skipped_fields": skipped,
            }
            if pending:
                _update_session(session["id"], patch, db)
                if purpose == "skip_field":
                    await _say(
                        "skip_field",
                        field_label=given_up_label,
                        next_field_label=pending[0]["label"],
                        collected=collected,
                    )
                else:
                    await _say(purpose, field_label=pending[0]["label"], collected=collected)
            else:
                _update_session(session["id"], patch | {"status": "awaiting_confirmation"}, db)
                await _say_summary(collected, skipped)
            return True

        if status == "awaiting_confirmation":
            if not _is_affirmative(body):
                # Not a yes, but not necessarily unrelated either -- the lead may be
                # correcting or supplying a field they see is wrong or missing on the
                # summary. Live evidence 2026-08-13: "Time of birth is 6:30 am" sent
                # right after a summary that showed that field as not provided. Try
                # extraction before giving up the turn; only a message that adds
                # nothing usable is released to the AI.
                before = session.get("collected_data") or {}
                skipped = list(session.get("skipped_fields") or [])
                updated = await extract_fields(body, config["fields"], before, tenant_id)
                changed = [k for k, v in updated.items() if v and v != before.get(k)]
                if not changed:
                    return False
                skipped = [k for k in skipped if k not in changed]
                _update_session(
                    session["id"],
                    {"collected_data": updated, "skipped_fields": skipped},
                    db,
                )
                await _say_summary(updated, skipped)
                return True
            ref = f"IN-{uuid.uuid4().hex[:8].upper()}"
            collected = session.get("collected_data") or {}
            # Razorpay needs a string here, so an unidentifiable customer falls back
            # to their phone -- always real, always that person.
            customer_name = resolve_customer_name(collected, config["fields"]) or phone
            # total_amount_paise is package + addons; package_amount_paise alone
            # is the fallback for sessions from before addons existed, where
            # total was never set.
            subtotal_paise = session.get("total_amount_paise") or session.get("package_amount_paise")
            if not subtotal_paise:
                logger.error(f"Intake session {session['id']} reached payment with no package amount")
                await _say("payment_delay")
                return True
            gst_percent = config.get("gst_percent")
            gst_fields = gst_session_fields(subtotal_paise, gst_percent)
            service_noun = config["service_noun"].capitalize()
            try:
                link = await create_payment_link(
                    idempotency_key=legacy_link_key(session),
                    notes={"booking_id": session["id"], "booking_ref": ref},
                    amount_paise=gst_fields["amount_paise"],
                    customer_name=customer_name,
                    customer_phone=phone,
                    description=gst_link_description(
                        f"{service_noun} — {customer_name} ({ref})", subtotal_paise, gst_percent,
                    ),
                    tenant_id=tenant_id,
                )
                _update_session(session["id"], {
                    "status": "awaiting_payment",
                    **gst_fields,
                    **link_store_patch(link),
                }, db)
                await cancel_session_link(db, session, keep_plink_id=link.get("razorpay_payment_link_id"))
                intro = await compose_line(
                    "payment_intro",
                    tenant_id=tenant_id,
                    language_mode=language_mode,
                    customer_message=body,
                    thread=thread,
                    knowledge=knowledge,
                )
                await _send_and_log(
                    phone,
                    f"{intro}\n{link['payment_link_url']}",
                    tenant_id, lead_id, db,
                )
            except Exception as e:
                logger.error(f"Intake payment link creation failed for session {session['id']}: {e}")
                await _say("payment_delay")
            return True

        if status == "paid":
            # Already paid, not yet resolved by staff -- do NOT start a second paid
            # session for the same unresolved one (risk of a double charge). The lead
            # gets reassured on this same turn anyway: ai_reply.py's
            # _intake_paid_prompt_block fires from generate_reply() right after this
            # returns False. This branch used to be an implicit fallthrough with no
            # log line, making it indistinguishable from a bug when it fired -- it's
            # intentional, so make it explicit and visible.
            logger.info(f"Intake session {session['id']} already paid and unresolved -- suppressing new offer for lead {lead_id}")
            return False

        # awaiting_payment: nothing to do here, wait for the Razorpay webhook.
        return False
    except Exception as e:
        logger.error(f"route_intake failed for lead {lead_id}: {e}")
        return False


_FOLLOWUP_REF_RE = re.compile(r"^(?P<sid>.+?)::f\d+$")


def session_ref_to_id(external_ref: str) -> str | None:
    """Resolve a bridge external_ref to its session uuid, or None.

    A follow-up's ref is ``{session_id}::f{n}`` (see astro_bridge.push_followup);
    a consultation's ref is the bare session id. The column is uuid-typed, so a
    non-uuid must never reach the DB — PostgREST rejects it with an APIError
    that would surface as a 500 on a public route instead of the intended 401."""
    ref = str(external_ref or "").strip()
    m = _FOLLOWUP_REF_RE.match(ref)
    if m:
        ref = m.group("sid")
    try:
        return str(uuid.UUID(ref))
    except (ValueError, AttributeError, TypeError):
        return None


_BRIDGE_AUTH_ALERT_COOLDOWN_MINUTES = 60


def alert_bridge_auth_failure(tenant_id: str, external_ref: str, db=None) -> None:
    """Tell staff the expert platform's replies are being rejected.

    A signature mismatch on /astro-reply is the one bridge failure with no other
    symptom: Anril answers 401, the astrologer's screen still shows the reply as
    sent, and the customer who paid simply never hears back. Only reached once
    the external_ref has already resolved to a real session, so this is a
    misconfigured secret rather than someone probing the endpoint.

    Rate-limited per tenant: Django retries, and one wrong secret must not put a
    notification in every caller's tray on every retry.
    """
    from datetime import datetime, timedelta, timezone

    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()

    since = (datetime.now(timezone.utc) - timedelta(minutes=_BRIDGE_AUTH_ALERT_COOLDOWN_MINUTES)).isoformat()
    try:
        recent = (
            db.table("app_notifications")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("type", "intake_bridge_auth_failed")
            .gte("created_at", since)
            .limit(1)
            .execute()
        )
        if recent and recent.data:
            return
    except Exception as e:
        # Never let the cooldown lookup stop the alert — a missed alert is the
        # failure this whole function exists to prevent.
        logger.warning(f"Bridge auth alert cooldown check failed for tenant {tenant_id}: {e}")

    try:
        notify_pool(
            tenant_id,
            "intake_bridge_auth_failed",
            "Expert replies are being rejected",
            "The expert platform's reply for a paid consultation failed its signature check, "
            "so it was not delivered to the customer. Check that astro_bridge_secret in "
            "Settings matches AIRA_BRIDGE_SECRET on the expert platform.",
            db=db,
        )
    except Exception as e:
        logger.warning(f"Bridge auth alert notify_pool failed for tenant {tenant_id}: {e}")


def get_session_tenant_id(session_id: str, db=None) -> str | None:
    """Look up which tenant owns a session, so the webhook route can verify the
    Razorpay signature against that tenant's own webhook secret rather than the
    default tenant's. Safe to call before the signature is verified: an attacker
    supplying a forged session_id just gets a lookup miss or another tenant's
    id, and the subsequent HMAC check against that tenant's real secret still
    fails without it. Accepts a follow-up ref ("{sid}::f{n}") and treats any
    malformed/non-uuid ref as a plain miss, never an exception."""
    resolved = session_ref_to_id(session_id)
    if not resolved:
        return None
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    try:
        row = (
            db.table("intake_sessions")
            .select("tenant_id")
            .eq("id", resolved)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        logger.warning(f"Session tenant lookup failed for ref {session_id!r}: {e}")
        return None
    if not row or not row.data:
        return None
    return row.data.get("tenant_id")


def _is_already_paid(session: dict) -> bool:
    """A session that has taken money: status paid, or a payment id on file (a paid session that
    staff or the 48h sweep has since resolved keeps its id, and must not be paid "again")."""
    return session.get("status") == "paid" or bool(session.get("razorpay_payment_id"))


def _record_extra_payment(
    db, session_id: str, razorpay_payment_id: str, *, tenant_id: str | None = None, known_paid: bool = False,
) -> None:
    """A payment arrived for a session that is already paid. Razorpay retries the SAME payment
    id, so that one is a no-op; a DIFFERENT id means the lead paid twice (e.g. two live links).
    Record it, flag the session refund_needed and tell staff, who refund by hand -- there is no
    auto-refund. Idempotent per payment id; never raises (the webhook must still answer 200).

    known_paid: the caller already knows money was taken (a won deal linked to this session), so
    the session's own status is not required to say paid. tenant_id scopes the read and write.

    The write is a compare-and-set (only when the id is not already in extra_payment_ids) and
    staff are alerted only when it changed a row, so two racing deliveries alert once. If the
    write itself fails staff are alerted anyway: money must never go unreported."""
    try:
        query = (
            db.table("intake_sessions")
            .select("id,tenant_id,lead_id,status,razorpay_payment_id,extra_payment_ids,collected_data,field_schema")
            .eq("id", session_id)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        row = query.maybe_single().execute()
        session = (row.data if row else None) or {}
        if not session or not (known_paid or _is_already_paid(session)):
            return
        extras = list(session.get("extra_payment_ids") or [])
        if not razorpay_payment_id or razorpay_payment_id == session.get("razorpay_payment_id") \
                or razorpay_payment_id in extras:
            return
    except Exception as e:
        logger.error(f"Reading session {session_id} to record a second payment failed: {e}")
        return
    tenant_id = session["tenant_id"]
    try:
        written = (
            db.table("intake_sessions")
            .update({"extra_payment_ids": [*extras, razorpay_payment_id], "refund_needed": True})
            .eq("id", session_id)
            .eq("tenant_id", tenant_id)
            .not_.contains("extra_payment_ids", [razorpay_payment_id])
            .execute()
        )
        if not (written and written.data):
            logger.info(f"Second payment {razorpay_payment_id} on session {session_id} already recorded")
            return
    except Exception as e:
        logger.error(
            f"Recording second payment {razorpay_payment_id} on session {session_id} (tenant {tenant_id}) "
            f"failed: {e} -- alerting staff anyway"
        )
    else:
        logger.warning(
            f"Second payment {razorpay_payment_id} on already-paid intake session {session_id} "
            f"(tenant {tenant_id}) -- refund needed"
        )
    _alert_double_payment(db, session, razorpay_payment_id)


def report_extra_deal_payment(tenant_id: str, deal_id: str, razorpay_payment_id: str, db=None) -> None:
    """A payment.paid event reached a deal that is already won. The same payment id as the one
    the deal was won with is a Razorpay retry (no-op); anything else is a second payment (or a
    link paid after staff took cash): flag it and tell staff, who refund by hand. A deal linked to
    an intake session is recorded on that session, so the board's refund_needed tag shows.
    Never raises; a deal with no session has no flag column, so staff get the alert only."""
    if not razorpay_payment_id:
        return
    try:
        if db is None:
            from app.db.supabase import get_supabase
            db = get_supabase()
        row = (
            db.table("deals").select("id,lead_id,razorpay_payment_id,intake_session_id,deal_number")
            .eq("id", deal_id).eq("tenant_id", tenant_id).maybe_single().execute()
        )
        deal = (row.data if row else None) or {}
        if not deal or razorpay_payment_id == deal.get("razorpay_payment_id"):
            return
        if deal.get("intake_session_id"):
            _record_extra_payment(
                db, deal["intake_session_id"], razorpay_payment_id, tenant_id=tenant_id, known_paid=True,
            )
            return
        logger.warning(
            f"Second payment {razorpay_payment_id} on already-won deal {deal_id} (tenant {tenant_id}) -- refund needed"
        )
        notify_pool(
            tenant_id,
            "deal_double_payment",
            "Refund needed: paid twice",
            f"A customer paid deal {deal_id} again (extra payment {razorpay_payment_id}). "
            "Refund the extra payment in Razorpay.",
            db=db,
        )
    except Exception as e:
        logger.error(f"Reporting extra payment {razorpay_payment_id} on deal {deal_id} failed: {e}")


def _alert_double_payment(db, session: dict, razorpay_payment_id: str) -> None:
    """In-app notification for the tenant's staff, plus a chat handover, which is what queues the
    tenant's configured staff WhatsApp alert. Each part is best-effort."""
    tenant_id, lead_id = session["tenant_id"], session.get("lead_id")
    name = resolve_customer_name(session.get("collected_data"), session.get("field_schema"))
    who = f"'{name}'" if name else "A lead"
    try:
        notify_pool(
            tenant_id,
            "intake_double_payment",
            "Refund needed: paid twice",
            f"{who} paid twice for the same consultation (extra payment {razorpay_payment_id}). "
            "Refund the extra payment in Razorpay.",
            db=db,
        )
    except Exception as e:
        logger.warning(f"Double-payment notify_pool failed for session {session.get('id')}: {e}")
    if not lead_id:
        return
    try:
        from app.services import ai_reply
        ai_reply._trigger_chat_escalation(
            lead_id=lead_id, reason="Paid twice: refund needed", tenant_id=tenant_id, assigned_to=None, db=db,
        )
    except Exception as e:
        logger.warning(f"Double-payment handover failed for session {session.get('id')}: {e}")


def confirm_intake_payment(
    session_id: str,
    razorpay_payment_id: str,
    amount_paid_paise: int | None = None,
    db=None,
) -> dict | None:
    """Mark a session paid. The AI stays live for the lead (see
    get_paid_unresolved_session / _intake_paid_prompt_block in
    ai_reply.py) so a lead asking "when will the expert contact me" isn't met
    with silence while waiting for staff to pick up the notification. Returns
    {phone, tenant_id, lead_id, customer_name, session, lead} on success, None if
    the session doesn't exist or was already paid (idempotent — Razorpay may
    retry webhooks, and two retries may land concurrently). ``session`` and
    ``lead`` are what the AstroTamil bridge push needs; see routes/intake.py."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()

    from datetime import datetime, timezone

    existing = (
        db.table("intake_sessions")
        .select("id,status,lead_id,tenant_id,collected_data,field_schema,razorpay_payment_id,"
                "package_key,package_name,package_amount_paise,total_amount_paise,amount_paise,trigger_reason")
        .eq("id", session_id)
        .maybe_single()
        .execute()
    )
    if not existing or not existing.data:
        return None
    if _is_already_paid(existing.data):
        _record_extra_payment(db, session_id, razorpay_payment_id)
        return None

    session = existing.data
    now_iso = datetime.now(timezone.utc).isoformat()
    # What the payment link actually charged: amount_paise, written at link creation
    # (GST included). Falls back to total (package + addons), then the bare package
    # price, for sessions whose link predates that column or was made without one.
    expected = (
        session.get("amount_paise")
        or session.get("total_amount_paise")
        or session.get("package_amount_paise")
    )
    charged = amount_paid_paise if amount_paid_paise is not None else expected
    # The status filter is the whole point: it turns the read-then-write above into
    # a single conditional UPDATE, so of two concurrent Razorpay retries exactly one
    # gets a row back and the other cannot bill/consult the lead twice. Filtering on
    # "not already paid" rather than "is awaiting_payment" keeps the pre-bridge
    # behaviour: money arriving against a cancelled or resolved session still
    # surfaces to staff instead of vanishing.
    claimed = (
        db.table("intake_sessions")
        .update({
            "status": "paid",
            "razorpay_payment_id": razorpay_payment_id,
            "paid_at": now_iso,
            "amount_paise": charged,
            # A lead can pay a link that was just superseded by a package change.
            # Record what actually arrived and flag the gap for staff rather than
            # trusting config.
            "amount_mismatch": bool(expected and charged and expected != charged),
        })
        .eq("id", session_id)
        .neq("status", "paid")
        .execute()
    )
    if not claimed or not claimed.data:
        logger.info(f"Intake session {session_id} already claimed by a concurrent confirm — skipping")
        _record_extra_payment(db, session_id, razorpay_payment_id)
        return None

    session = {**session, **(claimed.data[0] or {})}
    lead_id = session["lead_id"]
    tenant_id = session["tenant_id"]
    _sync_deal(claimed, db)

    lead_row = (
        db.table("leads")
        .select("id,phone,name")
        .eq("id", lead_id)
        .maybe_single()
        .execute()
    )
    lead = (lead_row.data if lead_row else None) or {}
    phone = lead.get("phone", "")
    customer_name = resolve_customer_name(
        session.get("collected_data"),
        session.get("field_schema") or get_intake_config(tenant_id, db=db).get("fields"),
        lead.get("name"),
    )
    adopt_lead_name(db, lead_id, tenant_id, customer_name if not lead.get("name") else None)

    try:
        notify_pool(
            tenant_id,
            "intake_paid",
            "New paid consultation",
            (
                f"Lead '{customer_name}' paid for a consultation — check Intake."
                if customer_name
                else "A lead paid for a consultation — check Intake."
            ),
            db=db,
        )
    except Exception as e:
        logger.warning(f"intake_paid notify_pool failed for session {session_id}: {e}")

    return {
        "phone": phone,
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "customer_name": customer_name,
        "session": session,
        "lead": lead,
    }


def expire_intake_session(session_id: str, db=None) -> bool:
    """A Razorpay payment link expired (payment_razorpay._LINK_EXPIRE_SECONDS, 24h --
    matches WhatsApp's own free-form messaging window, Hard Invariant 3). Only the LINK dies:
    it is cleared and the deal stays open in awaiting_payment, so the lead who comes back gets
    a fresh link for the same booking (blueprint D2). The old link's Razorpay id is kept: the
    next link's idempotency key is built from it. Filtered to 'awaiting_payment' so this can
    never touch a session that raced to 'paid' just before the expiry webhook arrived, and it
    is naturally idempotent on a retried webhook. Not activity (D3) and no message to the
    lead: expiry lands at or past the 24h window, so nothing could be sent without burning an
    approved template."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    # The webhook names the session, not which link expired. A regenerated session
    # holds a NEWER link, so a late "old link expired" event must not clear it: only
    # clear when the stored link's expiry is unknown (NULL) or already past.
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = (
        db.table("intake_sessions")
        .update({"payment_link": None, "payment_link_expires_at": None})
        .eq("id", session_id)
        .eq("status", "awaiting_payment")
        .or_(f"payment_link_expires_at.is.null,payment_link_expires_at.lte.{now_iso}")
        .execute()
    )
    _sync_deal(result, db)
    return bool(result and result.data)


_PAYMENT_FAILED_RENUDGE_MINUTES = 10


async def notify_payment_failed(session_id: str, db=None) -> bool:
    """A card was declined etc -- Razorpay allows a retry on the same link, so
    session status is deliberately left untouched (unlike expire_intake_session).
    Re-paste the existing link so the lead isn't left guessing what happened.
    Guarded against decline-retry spam: skips if an expert_handoff outbound
    already went to this lead in the last _PAYMENT_FAILED_RENUDGE_MINUTES."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    session = (
        db.table("intake_sessions")
        .select("id,status,lead_id,tenant_id,payment_link")
        .eq("id", session_id)
        .maybe_single()
        .execute()
    )
    if not session or not session.data:
        return False
    row = session.data
    if row.get("status") != "awaiting_payment" or not row.get("payment_link"):
        return False
    lead_id = row["lead_id"]
    tenant_id = row["tenant_id"]

    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=_PAYMENT_FAILED_RENUDGE_MINUTES)).isoformat()
    recent = (
        db.table("messages")
        .select("id")
        .eq("lead_id", lead_id)
        .eq("direction", "outbound")
        .eq("reply_source", "expert_handoff")
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    if recent and recent.data:
        return False

    lead_row = db.table("leads").select("phone").eq("id", lead_id).maybe_single().execute()
    phone = (lead_row.data or {}).get("phone") if lead_row else None
    if not phone:
        return False

    language_mode = resolve_language_mode(lead_id, tenant_id, db)
    text = await compose_line(
        "payment_failed",
        tenant_id=tenant_id,
        language_mode=language_mode,
        customer_message="",
    )
    await _send_and_log(phone, f"{text}\n{row['payment_link']}", tenant_id, lead_id, db)
    return True


def get_paid_unresolved_session(lead_id: str, tenant_id: str, db=None) -> dict | None:
    """The lead's most recent paid-but-not-yet-resolved session, if any. Used by
    ai_reply.py to keep the AI reassuring the lead instead of going silent, and
    by route_intake/_get_active_session to stop a lead being offered a
    second paid consultation while the first is still unresolved."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    result = (
        db.table("intake_sessions")
        .select("id")
        .eq("lead_id", lead_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "paid")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


_IN_PROGRESS_STATUSES = frozenset({
    "awaiting_package_choice", "awaiting_addon_choice", "collecting", "awaiting_confirmation", "awaiting_payment",
})


def get_in_progress_session(lead_id: str, tenant_id: str, db=None) -> dict | None:
    """The lead's most recent intake session that is actively in motion -- past the
    initial offer, not yet paid or resolved. Used by ai_reply.py so the AI does not
    derail a near-closed sale. Live evidence 2026-08-13: a lead corrected a field at
    awaiting_confirmation instead of saying yes; route_intake correctly handed the
    turn to the AI (that's not a yes), but with zero context the AI answered from the
    business's general knowledge base and told the lead to download the app and
    resubmit there -- abandoning a ₹29 payment one message from completing."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    result = (
        db.table("intake_sessions")
        .select("id,status")
        .eq("lead_id", lead_id)
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None
    row = rows[0]
    return row if row.get("status") in _IN_PROGRESS_STATUSES else None


def resolve_intake_session(session_id: str, tenant_id: str, db=None) -> bool:
    """Close a paid intake session as handled — the AI reassurance context
    (get_paid_unresolved_session) stops applying. Its only caller is
    deliver_astro_reply, once the astrologer's answer has been announced to the customer.
    Only transitions from 'paid'; returns False if the session doesn't exist, belongs to
    another tenant, or isn't paid yet."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    from datetime import datetime, timezone

    result = (
        db.table("intake_sessions")
        .update({"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", session_id)
        .eq("tenant_id", tenant_id)
        .eq("status", "paid")
        .execute()
    )
    return bool(result.data)


_SWEEP_BATCH = 200
_SWEEP_TENANT_LIMIT = 1000


def _iso_z(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


async def cancel_open_session(
    db, session: dict, *, idle_before: str | None = None, reason: str | None = None,
) -> bool:
    """Close one unfinished session, but only if it is still in the status the caller saw
    (tenant-scoped), so a payment or a state change that just landed wins. With idle_before
    (the idle sweep) it also requires that the lead has not been active since then and that
    no live link exists, so a fresh lead message wins the race. Afterwards its outstanding
    Razorpay link is cancelled (best effort) and the Deals-board card follows."""
    query = (
        db.table("intake_sessions")
        .update({"status": "cancelled"})
        .eq("id", session["id"])
        .eq("tenant_id", session["tenant_id"])
        .eq("status", session["status"])
    )
    if idle_before is not None:
        query = query.or_(
            f"payment_link_expires_at.is.null,payment_link_expires_at.lte.{_iso_z(datetime.now(timezone.utc))}"
        )
        if session.get("last_activity_at"):
            query = query.lt("last_activity_at", idle_before)
        else:
            query = query.is_("last_activity_at", "null")  # deploy-gap row: only ever touched by a message
    result = query.execute()
    if not result.data:
        return False
    _sync_deal(result, db, lost_reason=reason)
    await cancel_session_link(db, session)
    return True


# Deals-board "lost" reason for a deal the idle sweep closed.
_IDLE_LOST_REASON = "No reply from the customer (idle close)"


def _idle_since(row: dict) -> str | None:
    return row.get("last_activity_at") or row.get("created_at")


async def _close_idle_for_tenant(db, tenant_id: str, now: datetime) -> int:
    from app.services import deal_settings
    from app.services.deal_engine import parse_time

    try:
        idle_days = deal_settings.read_deal_idle_close_days(tenant_id)
    except SettingReadError as e:
        # Not the 30-day default: a tenant who chose 90 would lose deals early. Try next sweep.
        logger.warning(f"Idle-close sweep skipped tenant {tenant_id}: deal_idle_close_days unreadable ({e})")
        return 0
    cutoff_at = now - timedelta(days=idle_days)
    cutoff = cutoff_at.isoformat()
    rows = (
        db.table("intake_sessions")
        .select("id,tenant_id,status,created_at,last_activity_at,payment_link,payment_link_expires_at,razorpay_payment_link_id")
        .eq("tenant_id", tenant_id)
        .in_("status", list(_UNFINISHED_STATUSES))
        .or_(f"last_activity_at.lt.{cutoff},last_activity_at.is.null")
        .order("last_activity_at")
        .limit(_SWEEP_BATCH)
        .execute()
    ).data or []
    closed = 0
    for row in rows:
        idle_since = parse_time(_idle_since(row))
        if idle_since is None or idle_since >= cutoff_at:
            continue  # a NULL-activity row that is younger than the window
        try:
            if await cancel_open_session(db, row, idle_before=cutoff, reason=_IDLE_LOST_REASON):
                closed += 1
        except Exception as e:
            logger.error(f"Idle close failed for session {row['id']}: {e}")
    return closed


async def sweep_stale_intake_sessions(db=None) -> dict:
    """Queue task intake-staleness-sweep (every 5 min).

    - Unfinished deals (every status before paid, offer_pending included) with no lead
      message and no real progress for the tenant's deal_idle_close_days
      (deal_settings, default 30) -> cancelled (blueprint D1/D3, measured by
      last_activity_at). Each tenant's setting is read once per sweep. The cancel is
      conditional, so a lead who writes right now keeps the deal, and a deal whose link can
      still be paid is never cancelled. A lead who pays a cancelled link later is still
      confirmed and surfaced to staff: confirm_intake_payment() filters on `.neq(status,
      "paid")`, so this only stops the AI's "reply so payment can continue" nagging.
    Paid sessions are never touched here: a paid session closes only when the astrologer's
    answer is announced to the customer (deliver_astro_reply).
    """
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()

    from app.services import deal_settings

    now = datetime.now(timezone.utc)
    cancelled = 0

    try:
        floor = (now - timedelta(days=deal_settings.DEAL_IDLE_CLOSE_DAYS_MIN)).isoformat()
        candidates = (
            db.table("intake_sessions")
            .select("tenant_id")
            .in_("status", list(_UNFINISHED_STATUSES))
            .or_(f"last_activity_at.lt.{floor},last_activity_at.is.null")
            .order("last_activity_at")
            .limit(_SWEEP_TENANT_LIMIT)
            .execute()
        ).data or []
        for tenant_id in dict.fromkeys(r["tenant_id"] for r in candidates):
            try:
                cancelled += await _close_idle_for_tenant(db, tenant_id, now)
            except Exception as e:
                logger.error(f"Idle-close sweep failed for tenant {tenant_id}: {e}")
    except Exception as e:
        logger.error(f"Idle-close sweep query failed: {e}")

    if cancelled:
        logger.info(f"Intake staleness sweep: cancelled {cancelled} idle")
    return {"cancelled": cancelled}


async def change_session_package(session_id: str, tenant_id: str, package_key: str, db=None) -> dict | None:
    """Re-point an unpaid session at a different package and clear the stale
    payment link. Returns None if the session is missing, already paid, or the
    key is not configured — the caller turns that into a 404/400."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()

    row = (
        db.table("intake_sessions")
        .select("id,tenant_id,lead_id,status,collected_data,package_key,"
                "payment_link,payment_link_expires_at,razorpay_payment_link_id")
        .eq("id", session_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    session = (row.data if row else None) or None
    if not session or session["status"] not in _PACKAGE_CHANGEABLE_STATUSES:
        return None

    config = get_intake_config(tenant_id, db=db)
    packages = normalize_packages(config)
    found = _find_leaf(packages, package_key)
    if found is None:
        return None
    chosen, path = found

    # The old Razorpay link stays live until Razorpay processes the cancel, so
    # confirm_intake_payment records the amount that actually arrives rather
    # than assuming this one. See D16.
    patch = _package_patch(chosen, path, total_amount_paise=chosen["amount_paise"]) | {
        "payment_link": None, "amount_paise": None, "payment_link_expires_at": None,
        "gst_percent": None, "gst_amount_paise": None,
    }
    updated = db.table("intake_sessions").update(patch).eq("id", session_id).eq("tenant_id", tenant_id).execute()
    _sync_deal(updated, db)
    # The old link is only cancelled once the session no longer points at it. The stored
    # Razorpay id stays as the "last link", so a later re-link's idempotency key is new.
    await cancel_session_link(db, session)
    return {**session, **patch}


# --------------------------------------------------------------------------
# AstroTamil bridge: outbound push of a paid session, and delivery of the
# astrologer's reply back into the lead's WhatsApp thread.
# The wire contract (paths, payload keys, header names, external_ref format)
# is shared with the astrobackmatrimony Django app — see
# subsystem-notes.md (AstroTamil consultation bridge). Do not rename anything that crosses the wire.
# --------------------------------------------------------------------------

def record_astro_bridge_ids(session_id: str, tenant_id: str, bridge_response: dict, db=None) -> None:
    """Persist the ids Django created for a pushed session, so its reply callback maps back here."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    patch = {
        "astro_question_id": (bridge_response or {}).get("question_id"),
        "astro_horoscope_id": (bridge_response or {}).get("horoscope_id"),
        "astro_user_id": (bridge_response or {}).get("astro_user_id"),
    }
    patch = {k: v for k, v in patch.items() if v is not None}
    if not patch:
        logger.warning(f"Astro bridge returned no ids for session {session_id} — nothing to persist")
        return
    (
        db.table("intake_sessions")
        .update(patch)
        .eq("id", session_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )


_ASTRO_PUSH_ALERT_AFTER = timedelta(minutes=10)


def alert_astro_push_stuck(db, session: dict, lead: dict, tenant_id: str) -> bool:
    """Tell staff a paid question still has not reached AstroTamil. Until 2026-10-01 the only trace
    was a log line, so a customer who had paid could wait for an answer that was never asked for.

    Called by the retry job after a failed push, so a payment from the last few minutes is left
    alone (the webhook's own push may still be in flight), and each session is alerted once, not on
    every 5-minute retry. Returns True when an alert was raised. Best-effort: never raises."""
    from app.services import astro_bridge

    if not astro_bridge.is_connected(tenant_id):
        return False  # the retry job scans every client's paid sessions; only AstroTamil ones have a push

    try:
        paid_at = datetime.fromisoformat(str(session.get("paid_at")).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - paid_at < _ASTRO_PUSH_ALERT_AFTER:
            return False
    except (TypeError, ValueError):
        pass  # no usable paid_at: better an early alert than none

    session_id = session.get("id")
    try:
        seen = (
            db.table("app_notifications")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("type", "intake_astro_push_failed")
            .like("message", f"%{session_id}%")
            .limit(1)
            .execute()
        )
        if seen and seen.data:
            return False
    except Exception as e:
        logger.warning(f"Astro push alert dedupe check failed for session {session_id}: {e}")

    unusable = astro_bridge.unusable_for_push(
        session.get("collected_data"), session.get("skipped_fields"), (lead or {}).get("phone"),
        session.get("trigger_reason"),
    )
    reason = (
        f"AstroTamil cannot use their {', '.join(unusable)}. Ask the customer for it."
        if unusable else "AstroTamil did not accept it (it may be down). Anril keeps retrying."
    )
    who = (lead or {}).get("name") or "A customer"
    try:
        notify_pool(
            tenant_id,
            "intake_astro_push_failed",
            "Paid question not sent to AstroTamil",
            f"{who} has paid, but the question has not reached AstroTamil. {reason} (session {session_id})",
            db=db,
        )
    except Exception as e:
        logger.warning(f"Astro push alert notify_pool failed for session {session_id}: {e}")
        return False
    return True


async def reconcile_pending_astro_pushes(db=None) -> int:
    """Re-drive the Django consultation push for paid sessions it never reached.

    The confirm-time push is best-effort: if Django is down for the one webhook
    that flips a session to paid, the paid transition is idempotent and never
    re-fires, so without this sweep the customer has paid, been told "our expert
    will be in touch", and no astrologer ever sees the consultation. Django's
    side is idempotent on the session id (UNIQUE order id), so re-driving is
    always safe. Window: 3 days — older stuck sessions need a human anyway."""
    from datetime import datetime, timedelta, timezone

    from app.services import astro_bridge

    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    try:
        rows = (
            db.table("intake_sessions")
            .select("id,tenant_id,lead_id,collected_data,skipped_fields,trigger_reason,amount_paise,paid_at")
            .eq("status", "paid")
            .is_("astro_question_id", "null")
            .gte("created_at", cutoff)
            .limit(20)
            .execute()
        )
    except Exception as e:
        logger.error(f"Astro push reconcile query failed: {e}")
        return 0

    pushed = 0
    for session in rows.data or []:
        tenant_id = session.get("tenant_id")
        try:
            lead_row = (
                db.table("leads")
                .select("id,name,phone")
                .eq("id", session.get("lead_id"))
                .eq("tenant_id", tenant_id)
                .maybe_single()
                .execute()
            )
            lead = (lead_row.data if lead_row else None) or {}
            result = await astro_bridge.push_consultation(session, lead, tenant_id)
            if result:
                record_astro_bridge_ids(session["id"], tenant_id, result, db=db)
                pushed += 1
                logger.info(f"Astro push reconciled for session {session['id']} (tenant {tenant_id})")
            else:
                alert_astro_push_stuck(db, session, lead, tenant_id)
        except Exception as e:
            logger.error(f"Astro push reconcile failed for session {session.get('id')}: {e}")
    return pushed


def _astro_phone_number_id(tenant_id: str, db, phone: str | None = None) -> str | None:
    """The number the lead last messaged, so the astrologer's reply lands in the
    lead's existing thread -- even after a failover moved the primary. Falls back
    to the tenant's primary for a lead who has never messaged in."""
    if phone:
        try:
            rows = (
                db.table("leads")
                .select("last_inbound_phone_number_id")
                .eq("tenant_id", tenant_id)
                .eq("phone", phone)
                .limit(1)
                .execute()
            )
            pid = ((rows.data or [{}])[0] or {}).get("last_inbound_phone_number_id")
            if pid:
                return pid
        except Exception as e:
            logger.warning(f"Could not resolve lead's inbound number for tenant {tenant_id}: {e}")
    try:
        rows = (
            db.table("phone_numbers")
            .select("meta_phone_number_id")
            .eq("tenant_id", tenant_id)
            .eq("role", "primary")
            .limit(1)
            .execute()
        )
        return ((rows.data or [{}])[0] or {}).get("meta_phone_number_id")
    except Exception as e:
        logger.warning(f"Could not resolve primary phone_number_id for tenant {tenant_id}: {e}")
        return None


def _log_astro_message(
    db, lead_id: str, tenant_id: str, content: str, mid: str | None, delivery_status: str,
) -> None:
    """Every attempt is logged, sent or not, so staff reading the chat can see a
    nudge that never reached the customer. "sent", not "delivered": Meta has only
    accepted it; the status webhook moves it on from there by meta_message_id."""
    db.table("messages").insert({
        "lead_id": lead_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "channel": "whatsapp",
        "content": content,
        "is_ai_generated": False,
        "meta_message_id": mid,
        # Constrained value from migration 173; the feature was renamed to
        # "intake" but the stored reply_source was deliberately left alone.
        "reply_source": "expert_handoff",
        "delivery_status": delivery_status,
    }).execute()


# Meta refuses free-form text once 24h pass since the customer's last message;
# only a pre-approved template can reach them after that.
_WA_SESSION_WINDOW = timedelta(hours=24)
_REPLY_READY_TEMPLATE_DEFAULT = "astro_reply_ready"
# What the chat thread shows for a template send: its wording lives at Meta.
_REPLY_READY_TEMPLATE_LOG = "[WhatsApp template] Your expert has replied. Tap the button to read the answer in the app."


def _within_whatsapp_window(last_inbound_at) -> bool:
    if not last_inbound_at:
        return False
    try:
        last = datetime.fromisoformat(str(last_inbound_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last <= _WA_SESSION_WINDOW


async def _send_reply_ready_template(phone: str, tenant_id: str, phone_number_id: str | None) -> str | None:
    """The fixed-wording template (text + app-link button, approved by Meta), so it
    has no variables to fill and can go out any time. Returns the message id."""
    from app.config_dynamic import get_setting
    from app.services.meta_cloud import send_template_message

    name = get_setting("astro_reply_template_name", fallback=_REPLY_READY_TEMPLATE_DEFAULT, tenant_id=tenant_id)
    from app.db.supabase import get_supabase
    from app.services.template_params import template_status
    status = template_status(get_supabase(), tenant_id, name)
    if status != "APPROVED":
        # Under review after an edit, rejected or paused: Meta would refuse it.
        logger.warning(f"Astro reply-ready template {name} is {status or 'missing'} for tenant {tenant_id}; not sent")
        return None
    data = await send_template_message(
        to_number=phone,
        template_name=name,
        tenant_id=tenant_id,
        phone_number_id=phone_number_id,
    )
    return (data.get("messages") or [{}])[0].get("id")


async def _compose_reply_nudge(lead_id: str, tenant_id: str, phone: str, db) -> str:
    """The one message the customer gets when their expert has answered: the
    answer is ready, open the app, sign in with this number.

    The link is appended here in code, never written by the model. A model that
    invents a download URL sends a paying customer somewhere that does not exist
    — see commit 24494b3d, the same lesson learned on the intake offer message.
    """
    from app.config_dynamic import get_setting

    service_noun = get_intake_config(tenant_id, db=db).get("service_noun") or "consultation"
    language_mode = resolve_language_mode(lead_id, tenant_id, db)
    thread, knowledge = await gather_context(db, lead_id, tenant_id, "")
    line = await compose_line(
        "reply_ready",
        tenant_id=tenant_id,
        language_mode=language_mode,
        customer_message="",
        field_label=service_noun,
        thread=thread,
        knowledge=knowledge,
        brain_prompt=collector_identity(db, lead_id, tenant_id, ""),
    )

    from app.services.ai_reply import business_app_link
    app_link = business_app_link(tenant_id)
    if not app_link:
        # Still worth telling them an answer exists — but without the link they
        # have no way to reach it, so this is a configuration error, not a nudge.
        logger.error(
            f"Tenant {tenant_id} has no app_download_link: telling {phone} their answer "
            f"is ready with no way to open it. Add the app link to the Description."
        )
        return line
    return f"{line}\n{app_link}"


async def deliver_astro_reply(payload: dict, tenant_id: str, db=None) -> dict:
    """Deliver one astrologer reply from the Django bridge to the lead's WhatsApp thread."""
    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()
    from app.services.ai_reply import send_whatsapp

    external_ref = str(payload.get("external_ref") or "")
    session_id = session_ref_to_id(external_ref)
    if not session_id:
        logger.warning(f"Astro reply with malformed external_ref {external_ref!r} (tenant {tenant_id})")
        return {"ok": True, "delivered": [], "reason": "unknown_session"}
    try:
        reply_id = int(payload.get("reply_id"))
    except (TypeError, ValueError):
        logger.error(f"Astro reply for session {external_ref} has no usable reply_id — cannot dedupe, dropping")
        return {"ok": True, "delivered": [], "reason": "missing_reply_id"}

    row = (
        db.table("intake_sessions")
        .select("id,lead_id,tenant_id,astro_last_reply_id")
        .eq("id", session_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    session = (row.data if row else None) or {}
    if not session:
        logger.warning(f"Astro reply for unknown session {external_ref} (tenant {tenant_id})")
        return {"ok": True, "delivered": [], "reason": "unknown_session"}

    prior_reply_id = session.get("astro_last_reply_id")

    # Claim the reply id before sending, not after: a Django retry that overlaps
    # the first delivery must lose here rather than send the astrologer's answer
    # to the customer twice. Monotonic (.lt) rather than mere inequality, so a
    # replayed OLDER reply arriving after a newer one is also a duplicate.
    claimed = (
        db.table("intake_sessions")
        .update({"astro_last_reply_id": reply_id})
        .eq("id", session_id)
        .eq("tenant_id", tenant_id)
        .or_(f"astro_last_reply_id.is.null,astro_last_reply_id.lt.{reply_id}")
        .execute()
    )
    if not claimed or not claimed.data:
        logger.info(f"Astro reply {reply_id} for session {external_ref} already delivered — ignoring duplicate")
        return {"ok": True, "duplicate": True}

    lead_id = session.get("lead_id")
    lead_row = (
        db.table("leads")
        .select("id,phone,last_inbound_at")
        .eq("id", lead_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    lead = (lead_row.data if lead_row else None) or {}
    phone = lead.get("phone") or ""
    if not phone:
        logger.error(f"Astro reply {reply_id} for session {external_ref} undeliverable: lead {lead_id} has no phone")
        return {"ok": True, "nudged": False, "reason": "no_phone"}

    # Kept, never sent: the customer reads the answer in the app, but support
    # needs to see what the astrologer actually wrote when someone says they
    # can't find it there. Deliberately not written to `messages` — that table
    # is what the customer received, and this is precisely what they did not.
    reply_text = str(payload.get("reply_text") or "").strip()
    if reply_text:
        try:
            (
                db.table("intake_sessions")
                .update({"astro_last_reply_text": reply_text})
                .eq("id", session_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
        except Exception as e:
            logger.warning(f"Astro reply {reply_id} text archive failed for session {external_ref}: {e}")

    phone_number_id = _astro_phone_number_id(tenant_id, db, phone)
    mid, via, content = None, "", _REPLY_READY_TEMPLATE_LOG
    if _within_whatsapp_window(lead.get("last_inbound_at")):
        content = await _compose_reply_nudge(lead_id, tenant_id, phone, db)
        try:
            mid = await send_whatsapp(phone, content, tenant_id=tenant_id, phone_number_id=phone_number_id)
            via = "text"
        except Exception as e:
            logger.error(f"Astro reply {reply_id} nudge send failed for session {external_ref}: {e}")
    if not mid:
        # Outside the window, or the text failed inside it: the approved template
        # is the only thing Meta will still deliver.
        try:
            mid = await _send_reply_ready_template(phone, tenant_id, phone_number_id)
            via, content = "template", _REPLY_READY_TEMPLATE_LOG
        except Exception as e:
            logger.error(f"Astro reply {reply_id} template send failed for session {external_ref}: {e}")

    if not mid:
        try:
            _log_astro_message(db, lead_id, tenant_id, content, None, "failed")
        except Exception as e:
            logger.warning(f"Astro reply {reply_id} failed-nudge log failed for session {external_ref}: {e}")
        try:
            notify_pool(
                tenant_id,
                "intake_reply_undelivered",
                "Expert answer could not be announced",
                f"The expert answered a paid consultation, but the WhatsApp message telling "
                f"{phone} could not be sent. Reach the customer another way.",
                db=db,
            )
        except Exception as e:
            logger.warning(f"Astro reply {reply_id} staff alert failed for session {external_ref}: {e}")
        # Give the claim back so a re-push from the expert platform can try the
        # nudge again, rather than the customer never learning an answer exists.
        try:
            (
                db.table("intake_sessions")
                .update({"astro_last_reply_id": prior_reply_id})
                .eq("id", session_id)
                .eq("tenant_id", tenant_id)
                .eq("astro_last_reply_id", reply_id)
                .execute()
            )
        except Exception as e:
            logger.warning(f"Astro reply {reply_id} claim rollback failed for session {external_ref}: {e}")
        return {"ok": True, "nudged": False, "reason": "send_failed"}

    _log_astro_message(db, lead_id, tenant_id, content, mid, "sent")
    logger.info(f"Astro reply {reply_id} for session {external_ref}: customer nudged to the app via {via}")

    # The astrologer's answer just landed -- that's the resolution signal itself,
    # nothing else closes a paid session, so a paid row with no answer yet stays Paid
    # (and visible) until this runs. No-ops if already resolved.
    resolve_intake_session(session_id, tenant_id, db=db)

    return {"ok": True, "nudged": True, "via": via}


# ---------------------------------------------------------------- partner sends
# A partner app (AstroTamil's Django backend) sends WhatsApp messages to its own
# users through the tenant's number. Signature is verified by the route.

_PARTNER_TEXT_MAX = 4096
_PARTNER_REFERENCE_MAX = 120


def _partner_error(status: int, code: str, error: str) -> tuple[int, dict]:
    return status, {"ok": False, "code": code, "error": error}


def _partner_reference(payload: dict) -> str:
    return str(payload.get("reference") or "")[:_PARTNER_REFERENCE_MAX]


def _log_partner_message(db, tenant_id: str, phone: str, content: str, mid: str) -> None:
    """Shows the send in the lead's chat when the number is already a lead. A
    lead is never created here: that would hand the partner's app users to the
    tenant's assignment and re-engagement automations."""
    try:
        lead_row = (
            db.table("leads")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", phone)
            .maybe_single()
            .execute()
        )
        lead_id = ((lead_row.data if lead_row else None) or {}).get("id")
        if not lead_id:
            return
        db.table("messages").insert({
            "lead_id": lead_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "channel": "whatsapp",
            "content": content,
            "is_ai_generated": False,
            "meta_message_id": mid,
            "reply_source": "automation",
            "delivery_status": "sent",
        }).execute()
    except Exception as e:
        logger.warning(f"Partner send {mid} for tenant {tenant_id}: chat log failed: {e}")


def _has_dynamic_header_or_url(template: dict) -> bool:
    if "{{" in (template.get("header_text") or ""):
        return True
    for button in template.get("buttons") or []:
        if not isinstance(button, dict):
            continue
        if str(button.get("type") or "").upper() == "URL" and "{{" in str(button.get("url") or ""):
            return True
    return False


def _partner_name(payload: dict) -> str | None:
    name = payload.get("name")
    return name.strip()[:200] if isinstance(name, str) and name.strip() else None


async def partner_send_template(payload: dict, tenant_id: str, db=None) -> tuple[int, dict]:
    """Each account's app calls this ONE way, set on the Developer page (services/partner_send_mode.py):
    template_code (the default, the original AstroTamil call) or event (the tenant's Auto Messages
    rule, services/partner_events.py). A call in the other shape is 400 wrong_mode. Both are logged."""
    from app.services.astro_normalize import normalize_phone
    from app.services.meta_cloud import send_template_message
    from app.services.partner_events import log_partner_send
    from app.services.partner_send_mode import (
        EVENT_REFUSED_MESSAGE, TEMPLATE_REFUSED_MESSAGE, WRONG_MODE_CODE, get_partner_send_mode,
    )
    from app.services.template_rules import VAR_RE, variable_indices

    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()

    code = str(payload.get("template_code") or "").strip()
    has_event = payload.get("event") not in (None, "")
    # Every query below goes through asyncio.to_thread: the Supabase client is
    # synchronous, and one stalled call on the event loop froze the whole server
    # for 35-45 s during AstroTamil's campaigns (24 and 26 Oct 2026).
    if await asyncio.to_thread(get_partner_send_mode, db, tenant_id) == "event":
        if code:
            return _partner_error(400, WRONG_MODE_CODE, TEMPLATE_REFUSED_MESSAGE)
        if not has_event:
            return _partner_error(400, "invalid_request", "event is required")
        from app.services.partner_events import partner_send_event
        return await partner_send_event(payload, tenant_id, db)
    if has_event:
        return _partner_error(400, WRONG_MODE_CODE, EVENT_REFUSED_MESSAGE)
    variables = payload.get("variables")
    if variables is None:
        variables = []
    if not code or not isinstance(variables, list):
        return _partner_error(400, "invalid_request", "template_code is required and variables must be a list")
    variables = [str(v) for v in variables]

    row = await asyncio.to_thread(
        db.table("message_templates")
        .select("id,name,language,status,body_text,header_text,buttons")
        .eq("tenant_id", tenant_id)
        .eq("short_code", code)
        .limit(1)
        .execute
    )
    template = (row.data or [None])[0] if row else None
    if not template:
        return _partner_error(404, "template_not_found", f"No template with Anril ID {code}")
    status = str(template.get("status") or "")
    if status != "APPROVED":
        await asyncio.to_thread(
            log_partner_send,
            db, tenant_id, phone=normalize_phone(payload.get("phone")), event=None, template_id=template.get("id"),
            status="failed", reason="template_not_approved", name=_partner_name(payload),
        )
        return _partner_error(409, "template_not_approved", f"Template status is {status or 'unknown'}")

    phone = normalize_phone(payload.get("phone"))
    if not phone:
        return _partner_error(400, "invalid_phone", "phone is not a valid mobile number. Include the country code, e.g. 94771234567")

    if _has_dynamic_header_or_url(template):
        return _partner_error(400, "unsupported_template", "Only templates with body variables can be sent")
    body_text = template.get("body_text") or ""
    expected = len(variable_indices(body_text))
    if len(variables) < expected:
        return _partner_error(
            400, "variables_mismatch", f"Template expects {expected} variable(s), got {len(variables)}",
        )
    # The partner always sends its full fixed set ({{1}} customer name, {{2}}
    # service name) and does not know how many placeholders a given template
    # uses, so extra values are dropped rather than rejected. Too few is still
    # an error: Meta would reject the send anyway.
    variables = variables[:expected]

    name = template.get("name") or ""
    lang = template.get("language") or "en"
    reference = _partner_reference(payload)
    components = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in variables]}] if variables else None
    log = dict(
        phone=phone, event=None, template_id=template.get("id"), name=_partner_name(payload),
        extra={"reference": reference} if reference else None,
    )
    try:
        data = await send_template_message(
            to_number=phone,
            template_name=name,
            lang_code=lang,
            components=components,
            tenant_id=tenant_id,
            phone_number_id=await asyncio.to_thread(_astro_phone_number_id, tenant_id, db, phone),
        )
    except HTTPException as e:
        logger.error(f"Partner template {code} ({reference}) for tenant {tenant_id} rejected by Meta: {e.detail}")
        await asyncio.to_thread(log_partner_send, db, tenant_id, status="failed", reason=str(e.detail), **log)
        return _partner_error(502, "meta_error", str(e.detail))
    except Exception as e:
        logger.error(f"Partner template {code} ({reference}) for tenant {tenant_id} failed: {e}")
        await asyncio.to_thread(log_partner_send, db, tenant_id, status="failed", reason=str(e), **log)
        return _partner_error(502, "meta_error", str(e))
    mid = ((data or {}).get("messages") or [{}])[0].get("id")
    if not mid:
        await asyncio.to_thread(log_partner_send, db, tenant_id, status="failed", reason="no message id", **log)
        return _partner_error(502, "meta_error", "no message id")
    await asyncio.to_thread(log_partner_send, db, tenant_id, status="sent", **log)

    content = VAR_RE.sub(
        lambda m: variables[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(variables) else m.group(0),
        body_text,
    )
    await asyncio.to_thread(_log_partner_message, db, tenant_id, phone, content, mid)
    logger.info(f"Partner template {code} ({reference}) sent for tenant {tenant_id}: {mid}")
    return 200, {"ok": True, "message_id": mid, "template": {"code": code, "name": name, "language": lang}}


async def partner_send_text(payload: dict, tenant_id: str, db=None) -> tuple[int, dict]:
    from app.services.ai_reply import get_last_send_error, send_whatsapp
    from app.services.astro_normalize import normalize_phone

    if db is None:
        from app.db.supabase import get_supabase
        db = get_supabase()

    raw_text = payload.get("text")
    text = raw_text.strip() if isinstance(raw_text, str) else ""
    if not text or len(text) > _PARTNER_TEXT_MAX:
        return _partner_error(400, "invalid_request", f"text must be 1 to {_PARTNER_TEXT_MAX} characters")

    phone = normalize_phone(payload.get("phone"))
    if not phone:
        return _partner_error(400, "invalid_phone", "phone is not a valid mobile number. Include the country code, e.g. 94771234567")

    reference = _partner_reference(payload)
    try:
        pid = await asyncio.to_thread(_astro_phone_number_id, tenant_id, db, phone)
        mid = await send_whatsapp(phone, text, tenant_id=tenant_id, phone_number_id=pid)
    except Exception as e:
        logger.error(f"Partner text ({reference}) for tenant {tenant_id} failed: {e}")
        return _partner_error(502, "meta_error", str(e))
    if not mid:
        # Outside the 24h window Meta refuses free text; its reason is kept by send_whatsapp.
        return _partner_error(502, "meta_error", get_last_send_error() or "no message id")

    await asyncio.to_thread(_log_partner_message, db, tenant_id, phone, text, mid)
    logger.info(f"Partner text ({reference}) sent for tenant {tenant_id}: {mid}")
    return 200, {"ok": True, "message_id": mid}
