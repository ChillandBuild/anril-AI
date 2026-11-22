"""Teach the Anril AI: after a teammate answers a chat the AI handed over, turn that
reply into one general line the AI can reuse. Saving (owner only) goes to Teach & offers
(services/ai_teach.py); description_with_rule is only the fallback while migration 311 is not applied."""
import json
import logging
import re

from app.config_dynamic import get_setting
from app.services.business_profile import parse, render, validate

logger = logging.getLogger(__name__)

JOB_KEY = "job"
_MAX_WHEN = 160
_MAX_SAY = 400

_SYSTEM = """You help a small business teach its WhatsApp assistant.
The assistant could not answer a customer, so a person from the team replied instead.
Turn that exchange into ONE reusable rule for future customers.

Return only JSON: {"when": "...", "say": "..."}
- "when": the situation in plain English, starting with "someone asks", e.g. "someone asks for a discount on bridal sarees". Under 20 words.
- "say": what the assistant should reply next time, in the SAME language and style the team member used (Tanglish stays Tanglish, Tamil stays Tamil).
  Keep every fact, number and condition the team member gave. Remove this customer's name, greetings and anything that only fits this one customer (their order total, their date).
  Never add a fact, price, number or promise the team member did not write.
If the reply is not a reusable answer (just "ok", "calling you", a payment link, small talk), return {"when": "", "say": ""}."""


def _parse_json(raw: str | None) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)*", text or ""))


async def suggest(question: str, reply: str, *, tenant_id: str) -> dict | None:
    """{"when", "say"} or None when the reply isn't worth teaching. A suggestion carrying a
    number the team member never wrote is dropped -- the model must not invent prices."""
    from app.services.ai_reply import _llm_chat

    user = f"Customer asked:\n{question.strip()[:1500]}\n\nTeam member replied:\n{reply.strip()[:1500]}"
    try:
        raw = await _llm_chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            max_tokens=300, tenant_id=tenant_id, purpose="teach_answer", temperature=0.2,
        )
    except Exception as e:
        logger.warning(f"teach suggestion failed: {e}")
        return None
    data = _parse_json(raw)
    when = str(data.get("when") or "").strip()[:_MAX_WHEN]
    say = str(data.get("say") or "").strip()[:_MAX_SAY]
    if not when or not say:
        return None
    if not _numbers(say) <= _numbers(reply):
        logger.info("teach suggestion dropped: it carried a number the reply did not")
        return None
    return {"when": when, "say": say}


def rule_line(when: str, say: str) -> str:
    when = re.sub(r"\s+", " ", when).strip().rstrip(".")
    say = re.sub(r"\s+", " ", say).strip()
    return f"- When {when}, say: {say}"


def description_with_rule(tenant_id: str, line: str) -> tuple[str, list[str]]:
    """The full Description with the line added under YOUR JOB IN EVERY CONVERSATION,
    plus any validation errors (the 700-word cap)."""
    parsed = parse(get_setting("business_description", tenant_id=tenant_id) or "")
    sections = dict(parsed.sections)
    current = sections.get(JOB_KEY, "").strip()
    if line in current.split("\n"):
        return render(sections, parsed.other), []
    sections[JOB_KEY] = f"{current}\n{line}" if current else line
    return render(sections, parsed.other), validate(sections, parsed.other)
