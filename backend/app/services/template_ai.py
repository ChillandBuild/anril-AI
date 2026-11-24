"""Write with AI inside Create Template: three different drafts of a WhatsApp template, from the
owner's own words, the style and goal they pick, and what Anril already knows about the business.

Modelled on AiSensy's template writer (docs/research/aisensy-ai-teardown.html), fixing what the
teardown found weak there: their three drafts read alike (ours each take a different approach),
nothing checks Meta's rules (ours checks each draft), and the AI knows nothing about the shop
(ours reads the business description from Anril Setup).

It runs on its own key, `template_ai_api_key`, never the business's main `gemini_api_key`. The
key is set per client by Anril in the operator console (Client -> Config -> AI Integrations); a
business can't set or read it.

Nothing here saves a template or talks to Meta. The drafts go back to the builder, where the owner
picks one, edits it and submits it themselves.

Security: the key is a per-tenant secret (app_settings.is_secret), never logged or returned, and
only read for the caller's own tenant.
"""
import json
import logging
import re

import httpx

from app.services import template_rules
from app.services import gemini_client
from app.services.gemini_client import (
    _gemini_output_text,
    _messages_to_gemini_input,
    _record,
    thinking_level,
)

logger = logging.getLogger(__name__)

TEMPLATE_AI_KEY = "template_ai_api_key"
DRAFT_MODEL = "gemini-3.5-flash-lite"
DRAFT_COUNT = 3

NO_KEY_MESSAGE = "Write with AI isn't switched on for your account yet. Ask Anril support to turn it on."
KEY_REFUSED_MESSAGE = "Google refused the Write with AI key. Ask Anril support to check it."

LANGUAGE_NAMES = {
    "en": "English", "en_US": "English (US)", "en_IN": "English (India)", "hi": "Hindi",
    "kn": "Kannada", "ml": "Malayalam", "ta": "Tamil", "te": "Telugu",
}
DRAFT_CATEGORIES = ("MARKETING", "UTILITY")
STYLES = {
    "friendly": "warm and friendly, like a shop owner who knows the customer",
    "festive": "festive and joyful, good for festivals and celebrations",
    "urgent": "short and urgent, with a clear reason to act now (only use a deadline the owner gave)",
    "formal": "polite and formal, clear and to the point",
}
GOALS = {
    "clicks": "get the customer to tap a link button (lead with the benefit, one clear call to action)",
    "replies": "get the customer to reply in the chat (end with an easy question, quick-reply buttons)",
}
# The three drafts each take one of these, so the owner gets a real choice, not three rewordings.
APPROACHES = (
    "Short and direct: 2-3 lines, the point first.",
    "Warm and personal: greet them by name, a friendly line about them, then the point.",
    "Offer or benefit first: open with what the customer gets, then the details.",
)
_BUTTON_TYPES = ("URL", "QUICK_REPLY", "PHONE_NUMBER")
_MAX_BUTTONS = 3
_DESCRIPTION_LIMIT = 1500


class TemplateAiError(Exception):
    """A problem the owner can act on; `status` is the HTTP code the route returns."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _google_says(exc: httpx.HTTPStatusError) -> str:
    code = exc.response.status_code
    try:
        body = exc.response.text.lower()
    except Exception:
        body = ""
    if code == 402 or "prepayment" in body or "credits are depleted" in body or "billing" in body:
        return "The Write with AI key has no Google credits left. Ask Anril support to top it up."
    if code in (401, 403) or (code == 400 and ("api key" in body or "api_key" in body)):
        return KEY_REFUSED_MESSAGE
    if code == 429:
        return "Write with AI is busy right now. Wait a minute and try again."
    if code >= 500:
        return "Google's AI service had a problem on its side. Try again in a minute."
    return f"Google refused the request (error {code}). Try again in a minute."


_SYSTEM_PROMPT = f"""You write WhatsApp Business message templates that Meta will approve.
Return ONLY one JSON object, no markdown fences:
{{"drafts": [<exactly {DRAFT_COUNT} draft objects>]}}
Each draft object has exactly these keys:
{{"name": "...", "category": "MARKETING" or "UTILITY", "header_text": "...", "body_text": "...",
 "footer_text": "...", "buttons": [{{"type": "URL" | "QUICK_REPLY" | "PHONE_NUMBER", "text": "...", "url": "...", "phone": "..."}}]}}

The {DRAFT_COUNT} drafts must each take a DIFFERENT approach, in this order:
""" + "\n".join(f"{i + 1}. {a}" for i, a in enumerate(APPROACHES)) + """

Rules for every draft:
- name: small letters, digits and underscores only, 3-5 words, says what the message is (e.g. payment_due_reminder).
  Give each draft a different name.
- category: UTILITY only for something the customer already started (order, booking, bill, delivery,
  account alert). Anything that promotes, offers, announces or asks for a review is MARKETING.
- body_text: under 550 characters, plain words. Use numbered variables {{1}}, {{2}}... for details that
  change per customer (name, amount, date, order number), numbered in order with no gaps. {{1}} is the
  customer's name when a name is used. The body must NOT start or end with a variable: put words before
  the first one and end with a full sentence. At most 4 variables. At most 2 emojis. *bold* is allowed.
- header_text: optional short bold line (under 60 characters, no emojis, no variables), or "".
- footer_text: optional small grey line under 60 characters, or "". No variables.
- buttons: 0 to 3. URL buttons need a real https:// link; if the owner gave none, use "https://example.com"
  so they replace it. Button text under 25 characters, no two buttons with the same text. Use [] when none fits.
- Never invent prices, discounts, codes, dates or policies the owner did not mention: use a variable instead.
- Use what you are told about the business only to get products and tone right; never make claims about it.
- Write in the requested language. If the owner wrote their idea in that language using English letters
  (for example Tamil in English letters, "Tanglish"), write the same way."""


def _extract_json(raw: str) -> dict:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def _safe_name(raw: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", (raw or "").lower())
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:60] or "ai_draft_template"


def _clean_line(text: str, limit: int) -> str:
    """Header/footer: one line, no variables, trimmed to Meta's size."""
    t = re.sub(r"\{\{\s*\d+\s*\}\}", "", str(text or "")).replace("\n", " ")
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t[:limit].strip()


def _clean_buttons(raw) -> list[dict]:
    buttons: list[dict] = []
    seen: set[str] = set()
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, dict):
            continue
        kind = str(b.get("type") or "").upper()
        text = str(b.get("text") or "").strip()[:25]
        if kind not in _BUTTON_TYPES or not text or text.lower() in seen:
            continue  # Meta refuses two buttons with the same words
        if kind == "URL":
            url = str(b.get("url") or "").strip()
            if not url.startswith("https://") or template_rules.url_problems(url):
                url = "https://example.com"
            button = {"type": "URL", "text": text, "url": url}
        elif kind == "PHONE_NUMBER":
            phone = re.sub(r"[^\d+]", "", str(b.get("phone") or ""))
            if len(phone) < 8:
                continue  # a made-up number is worse than no button
            button = {"type": "PHONE_NUMBER", "text": text, "phone": phone}
        else:
            button = {"type": "QUICK_REPLY", "text": text}
        seen.add(text.lower())
        buttons.append(button)
        if len(buttons) == _MAX_BUTTONS:
            break
    return buttons


def clean_draft(data: dict, *, language: str, category: str | None) -> dict:
    """One draft from the AI, made safe for the builder. Raises ValueError when it has no body."""
    if not isinstance(data, dict):
        raise ValueError("not an object")
    body = str(data.get("body_text") or "").strip()[:1024]
    if not body:
        raise ValueError("empty body")
    picked = str(data.get("category") or "").upper()
    return {
        "name": _safe_name(str(data.get("name") or "")),
        "category": category or (picked if picked in DRAFT_CATEGORIES else "MARKETING"),
        "language": language,
        "header_text": _clean_line(data.get("header_text") or "", 60),
        "body_text": body,
        "footer_text": _clean_line(data.get("footer_text") or "", 60),
        "buttons": _clean_buttons(data.get("buttons")),
    }


def meta_problems(draft: dict) -> list[str]:
    """What Meta would refuse, in the same words the builder uses before submitting."""
    return (
        template_rules.body_problems(draft["body_text"])
        + template_rules.header_problems(draft.get("header_text"))
        + template_rules.footer_problems(draft.get("footer_text"))
    )


def _parse_drafts(raw: str, *, language: str, category: str | None) -> list[dict]:
    data = _extract_json(raw)
    items = data.get("drafts") if isinstance(data.get("drafts"), list) else [data]
    drafts: list[dict] = []
    for i, item in enumerate(items[:DRAFT_COUNT]):
        try:
            d = clean_draft(item, language=language, category=category)
        except ValueError:
            continue
        drafts.append({**d, "approach": APPROACHES[i].split(":")[0] if i < len(APPROACHES) else "", "problems": meta_problems(d)})
    if not drafts:
        raise ValueError("no usable drafts")
    # Same name twice would collide when submitted; make each one its own
    names: set[str] = set()
    for d in drafts:
        base, n = d["name"], 2
        while d["name"] in names:
            d["name"] = f"{base[:57]}_{n}"
            n += 1
        names.add(d["name"])
    return drafts


async def _ask(api_key: str, messages: list[dict], tenant_id: str) -> str:
    system_instruction, steps = _messages_to_gemini_input(messages)
    request_json = {
        "model": DRAFT_MODEL,
        "store": False,
        "input": steps,
        "system_instruction": system_instruction,
        "generation_config": {"temperature": 0.8, "max_output_tokens": 2200, "thinking_level": thinking_level(DRAFT_MODEL)},
    }
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(
                gemini_client.GEMINI_INTERACTIONS_URL,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=request_json,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        # Status code only: the request carried the key in a header, never log the request itself.
        logger.info("template AI draft refused by Google for tenant %s: HTTP %s", tenant_id, exc.response.status_code)
        raise TemplateAiError(_google_says(exc), 502) from None
    except httpx.TransportError:
        raise TemplateAiError("Couldn't reach Google's AI service. Try again in a minute.", 502) from None
    _record(tenant_id, "template_ai_draft", DRAFT_MODEL, data)
    return _gemini_output_text(data.get("steps") or [])


def build_request(*, idea: str, category: str | None, language: str, style: str, goal: str,
                  business_description: str | None) -> str:
    about = (business_description or "").strip()[:_DESCRIPTION_LIMIT]
    return "\n".join(filter(None, [
        f"About the business (from its own setup): {about}" if about else "",
        f"Language: {LANGUAGE_NAMES.get(language, language)}",
        f"Category: {category or 'pick MARKETING or UTILITY'}",
        f"Style: {STYLES.get(style, STYLES['friendly'])}",
        f"Goal: {GOALS.get(goal, GOALS['clicks'])}",
        f"What the owner wants the message to do, in their own words:\n{idea.strip()}",
    ]))


async def draft_templates(*, api_key: str, idea: str, category: str | None, language: str, style: str,
                          goal: str, business_description: str | None, tenant_id: str) -> list[dict]:
    """Three drafts. When any of them breaks Meta's rules, the AI gets one go at fixing them, and each
    slot keeps whichever version has fewer problems; what is left shows as that draft's `problems`."""
    ask = build_request(idea=idea, category=category, language=language, style=style, goal=goal,
                        business_description=business_description)
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": ask}]
    drafts: list[dict] | None = None
    for _attempt in range(2):
        raw = await _ask(api_key, messages, tenant_id)
        try:
            fresh = _parse_drafts(raw, language=language, category=category)
        except (ValueError, json.JSONDecodeError):
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": "That was not the JSON object asked for. Return only the JSON object."}]
            continue
        if drafts is None:
            drafts = fresh
        else:
            for i, d in enumerate(fresh):
                if i >= len(drafts):
                    drafts.append(d)
                elif len(d["problems"]) < len(drafts[i]["problems"]):
                    drafts[i] = d
        broken = [f"Draft {i + 1}: {' '.join(d['problems'])}" for i, d in enumerate(drafts) if d["problems"]]
        if not broken and len(drafts) == DRAFT_COUNT:
            break
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "Meta would refuse some of these. " + " ".join(broken)
             + f" Fix them and return all {DRAFT_COUNT} drafts as the full JSON again."},
        ]
    if not drafts:
        raise TemplateAiError("The AI's drafts could not be read. Try again, or say it a little differently.", 502)
    return drafts
