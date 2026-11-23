"""v9.2 Mark Lost: the reason chips for this kind of business, and the AI agent's guess from the chat.

The guess is one small model call over the last chat lines, asked to pick ONE chip and quote the
customer's own words. It is only a suggestion: the teammate taps the chip they want.
"""
import json
import logging
import re

from app.services.lead_details import _kind

logger = logging.getLogger(__name__)

COMMON = ["Price too high", "Bought elsewhere", "Just looking", "Not now, maybe later", "Stopped replying", "Wrong number"]
BY_KIND = {
    "real_estate": ["Budget too high", "Location not right", "Bought elsewhere", "Just checking",
                    "Loan not approved", "Not now, maybe later", "Stopped replying"],
    "education": ["Fee too high", "Timing doesn't suit", "Joined elsewhere", "Just asking",
                  "Not now, maybe later", "Stopped replying"],
}

_PROMPT = """A customer chatted with a business and did not buy. Read the chat and pick the ONE reason
from this list that fits best, and copy the customer's own words that show it (up to 15 words).
If nothing in the chat shows a reason, answer {{"reason": null, "quote": null}}.

Reasons:
{choices}

Chat (oldest first):
{chat}

Answer with JSON only: {{"reason": "<one reason from the list, exactly>", "quote": "<their words>"}}"""


def choices_for(kind: str | None) -> list[str]:
    return list(BY_KIND.get(kind or "", COMMON))


def choices(db, tenant_id: str) -> list[str]:
    return choices_for(_kind(db, tenant_id))


def parse_guess(text: str, allowed: list[str]) -> dict:
    """The model's answer -> {"reason", "quote"}; a reason not in the list is dropped."""
    empty = {"reason": None, "quote": None}
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return empty
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return empty
    if not isinstance(data, dict):
        return empty
    reason = data.get("reason")
    by_lower = {c.lower(): c for c in allowed}
    reason = by_lower.get(str(reason).strip().lower()) if isinstance(reason, str) else None
    quote = data.get("quote")
    quote = " ".join(str(quote).split())[:160] if reason and isinstance(quote, str) and quote.strip() else None
    return {"reason": reason, "quote": quote}


def _chat(rows: list[dict]) -> str:
    lines = []
    for r in reversed(rows):  # rows come newest first
        text = " ".join((r.get("content") or "").split())[:300]
        if text:
            lines.append(f"{'Customer' if r.get('direction') == 'inbound' else 'Business'}: {text}")
    return "\n".join(lines[-14:])


async def guess(db, tenant_id: str, lead_id: str, *, llm=None) -> dict:
    """{"choices": [...], "reason": str|None, "quote": str|None}. Never raises."""
    import asyncio
    allowed = await asyncio.to_thread(choices, db, tenant_id)
    out = {"choices": allowed, "reason": None, "quote": None}
    try:
        rows = (await asyncio.to_thread(lambda: db.table("messages").select("direction,content")
                                        .eq("tenant_id", tenant_id).eq("lead_id", lead_id)
                                        .order("created_at", desc=True).limit(20).execute())).data or []
        if not any(r.get("direction") == "inbound" and (r.get("content") or "").strip() for r in rows):
            return out
        prompt = _PROMPT.format(choices="\n".join(f"- {c}" for c in allowed), chat=_chat(rows))
        if llm is None:
            from app.services.ai_reply import _llm_chat
            text = await _llm_chat([{"role": "user", "content": prompt}], max_tokens=120, tenant_id=tenant_id,
                                   purpose="lost_reason_guess", temperature=0.0)
        else:
            text = await llm(prompt)
        out.update(parse_guess(text, allowed))
    except Exception:
        logger.warning("Lost reason guess failed for lead %s", lead_id, exc_info=True)
    return out
