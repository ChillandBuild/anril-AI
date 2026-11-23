"""Write with AI on the Templates page: drafts a WhatsApp template from the owner's own words.

It runs on its own key, `template_ai_api_key` (a Google AI Studio / Gemini key the owner sets
under Templates -> Write with AI), never on the business's main `gemini_api_key`: the owner asked
for template writing to be configured and paid for separately.

Nothing here saves a template or talks to Meta. The draft goes back to the browser and opens in
the Create Template builder, where the owner checks it and submits it themselves.

Security: the key is a per-tenant secret (app_settings.is_secret). It is never logged, never
returned in full (mask_key), and only read for the caller's own tenant.
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
_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

NO_KEY_MESSAGE = (
    "Write with AI needs its own AI key first. Open Templates, click Write with AI, "
    "then Set up AI key."
)

LANGUAGE_NAMES = {
    "en": "English", "en_US": "English (US)", "en_IN": "English (India)", "hi": "Hindi",
    "kn": "Kannada", "ml": "Malayalam", "ta": "Tamil", "te": "Telugu",
}
DRAFT_CATEGORIES = ("MARKETING", "UTILITY")
_BUTTON_TYPES = ("URL", "QUICK_REPLY", "PHONE_NUMBER")
_MAX_BUTTONS = 3


class TemplateAiError(Exception):
    """A problem the owner can act on; `status` is the HTTP code the route returns."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def mask_key(value: str | None) -> str:
    """'AIza••••••••x9Qk' for a long key, all dots for a short one. Never the whole key."""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) > 12:
        return f"{v[:4]}{'•' * 8}{v[-4:]}"
    return "•" * len(v)


def _google_says(exc: httpx.HTTPStatusError) -> str:
    code = exc.response.status_code
    try:
        body = exc.response.text.lower()
    except Exception:
        body = ""
    if code == 402 or "prepayment" in body or "credits are depleted" in body:
        return "Your Google AI Studio credits for this key are used up. Add credits at ai.studio, then try again."
    if "billing" in body:
        return "Google says billing isn't set up for this key's project. Fix it at ai.studio, then try again."
    if code in (400, 401, 403) and ("api key" in body or "api_key" in body or code in (401, 403)):
        return "Google didn't accept this AI key. Check it was copied fully, or make a new one at ai.studio."
    if code == 429:
        return "Too many requests on this AI key right now. Wait a minute and try again."
    if code >= 500:
        return "Google's AI service had a problem on its side. Try again in a minute."
    return f"Google refused the request (error {code}). Try again in a minute."


async def check_key(api_key: str) -> None:
    """Asks Google whether the key works (listing models costs nothing). Raises TemplateAiError."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_MODELS_URL, headers={"x-goog-api-key": api_key}, params={"pageSize": 1})
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Status code only: the request carried the key in a header, never log the request itself.
        logger.info("template AI key check refused by Google: HTTP %s", exc.response.status_code)
        raise TemplateAiError(_google_says(exc), 400) from None
    except httpx.TransportError:
        raise TemplateAiError("Couldn't reach Google to check the key. Try again in a minute.", 502) from None


_SYSTEM_PROMPT = """You write WhatsApp Business message templates that Meta will approve.
Return ONLY one JSON object, no markdown fences, with exactly these keys:
{"name": "...", "category": "MARKETING" or "UTILITY", "header_text": "...", "body_text": "...",
 "footer_text": "...", "buttons": [{"type": "URL" | "QUICK_REPLY" | "PHONE_NUMBER", "text": "...", "url": "...", "phone": "..."}]}

Rules:
- name: small letters, digits and underscores only, 3-5 words, describes the message (e.g. payment_due_reminder).
- category: UTILITY only for a transaction the customer already started (order, booking, bill, delivery,
  account alert). Anything that promotes, offers, announces or asks for a review is MARKETING.
- body_text: under 550 characters, warm and plain, like a small shop owner talking. Use numbered
  variables {{1}}, {{2}}... for details that change per customer (name, amount, date, order number),
  numbered in order with no gaps. The body must NOT start or end with a variable: put words before
  the first one and end with a full sentence. No more than 4 variables. At most 2 emojis.
- header_text: optional short bold line (under 60 characters, no emojis, no variables), or "".
- footer_text: optional small grey line under 60 characters, or "". No variables.
- buttons: 0 to 3. URL buttons need a real https:// link; if the owner gave none, use
  "https://example.com" so they replace it. Button text under 25 characters. Use [] when no button fits.
- Never invent prices, discounts, dates or policies the owner did not mention: use a variable instead.
- Write in the requested language. If the owner wrote their idea in that language using English
  letters (for example Tamil in English letters), write the same way."""


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
    """Header/footer: one line, no variables, no emojis are added by us, trimmed to Meta's size."""
    t = re.sub(r"\{\{\s*\d+\s*\}\}", "", str(text or "")).replace("\n", " ").strip()
    return t[:limit].strip()


def _clean_buttons(raw) -> list[dict]:
    buttons: list[dict] = []
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, dict):
            continue
        kind = str(b.get("type") or "").upper()
        text = str(b.get("text") or "").strip()[:25]
        if kind not in _BUTTON_TYPES or not text:
            continue
        if kind == "URL":
            url = str(b.get("url") or "").strip()
            if not url.startswith("https://") or template_rules.url_problems(url):
                url = "https://example.com"
            buttons.append({"type": "URL", "text": text, "url": url})
        elif kind == "PHONE_NUMBER":
            phone = re.sub(r"[^\d+]", "", str(b.get("phone") or ""))
            if len(phone) < 8:
                continue  # a made-up number is worse than no button
            buttons.append({"type": "PHONE_NUMBER", "text": text, "phone": phone})
        else:
            buttons.append({"type": "QUICK_REPLY", "text": text})
        if len(buttons) == _MAX_BUTTONS:
            break
    # Meta refuses two buttons with the same words
    seen: set[str] = set()
    return [b for b in buttons if not (b["text"].lower() in seen or seen.add(b["text"].lower()))]


def clean_draft(data: dict, *, language: str, category: str | None) -> dict:
    """The AI's JSON, made safe for the builder. Raises ValueError when there is no usable body."""
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


async def _ask(api_key: str, messages: list[dict], tenant_id: str) -> str:
    system_instruction, steps = _messages_to_gemini_input(messages)
    request_json = {
        "model": DRAFT_MODEL,
        "store": False,
        "input": steps,
        "system_instruction": system_instruction,
        "generation_config": {"temperature": 0.6, "max_output_tokens": 900, "thinking_level": thinking_level(DRAFT_MODEL)},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                gemini_client.GEMINI_INTERACTIONS_URL,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=request_json,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.info("template AI draft refused by Google for tenant %s: HTTP %s", tenant_id, exc.response.status_code)
        raise TemplateAiError(_google_says(exc), 502) from None
    except httpx.TransportError:
        raise TemplateAiError("Couldn't reach Google's AI service. Try again in a minute.", 502) from None
    _record(tenant_id, "template_ai_draft", DRAFT_MODEL, data)
    return _gemini_output_text(data.get("steps") or [])


async def draft_template(*, api_key: str, idea: str, category: str | None, language: str, tenant_id: str) -> dict:
    """One draft. If Meta's body rules fail, the AI gets one go at fixing them; whatever is left
    is returned as `problems` and the builder shows the same messages before submitting."""
    ask = (
        f"Language: {LANGUAGE_NAMES.get(language, language)}\n"
        f"Category: {category or 'pick MARKETING or UTILITY'}\n"
        f"What the owner wants the message to do, in their own words:\n{idea.strip()}"
    )
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": ask}]
    draft: dict | None = None
    problems: list[str] = []
    for _attempt in range(2):
        raw = await _ask(api_key, messages, tenant_id)
        try:
            draft = clean_draft(_extract_json(raw), language=language, category=category)
        except (ValueError, json.JSONDecodeError):
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "That was not the JSON object asked for. Return only the JSON object."}]
            continue
        problems = template_rules.body_problems(draft["body_text"])
        if not problems:
            break
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "Meta would refuse this body: " + " ".join(problems) + " Fix it and return the full JSON again."},
        ]
    if draft is None:
        raise TemplateAiError("The AI's draft could not be read. Try again, or say it a little differently.", 502)
    return {**draft, "problems": problems}
