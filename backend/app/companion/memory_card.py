"""Card engine: Level 2 memory kept as dated facts in companion_memory_facts.

This module renders the facts for the prompt (context_for) and turns new messages into fact
operations (the sweep calls extract_and_apply). Fact text and message text are never logged.
"""
import logging
from datetime import date

from app.companion import store

logger = logging.getLogger(__name__)

CONTEXT_CAP = 2000
SEPARATOR = " · "
_LABELS = (  # (section, status, label) in render order
    ("threads", "active", "Open threads"),
    ("profile", None, "Profile"),
    ("people", None, "People"),
    ("life", None, "Life"),
    ("preferences", None, "Preferences"),
    ("threads", "closed", "Finished threads"),
)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt_date(value) -> str:
    """'2026-11-20' → '20 Nov 2026'; the 1st of a month → 'Nov 2026' (the AI often gives months only)."""
    if not value:
        return ""
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    month = f"{_MONTHS[d.month - 1]} {d.year}"
    return month if d.day == 1 else f"{d.day} {month}"


def _fact_line(fact: dict) -> str:
    start, end = _fmt_date(fact.get("valid_from")), _fmt_date(fact.get("valid_to"))
    if fact.get("status") == "closed":
        when = f"until {end}" if end else "no longer true"
    elif fact["section"] == "threads":
        when = start
    else:
        when = f"since {start}" if start else ""
    return f"{fact['text']} ({when})" if when else fact["text"]


def render(facts: list[dict], cap: int = CONTEXT_CAP) -> str:
    """Facts as short labelled lines in a fixed section order, cut at whole facts to stay under
    `cap`. Within a section the input order is kept (callers pass newest first, own facts first);
    closed facts sit after the active ones."""
    lines: list[str] = []
    for section, status, label in _LABELS:
        picked = [f for f in facts if f["section"] == section
                  and (status is None or f.get("status", "active") == status)]
        picked.sort(key=lambda f: f.get("status") == "closed")  # stable: keeps the caller's order
        items: list[str] = []
        for fact in picked:
            candidate = f"{label}: " + SEPARATOR.join(items + [_fact_line(fact)])
            if len("\n".join(lines + [candidate])) > cap:
                break
            items.append(_fact_line(fact))
        if items:
            lines.append(f"{label}: " + SEPARATOR.join(items))
    return "\n".join(lines)


def newest_first(facts: list[dict]) -> list[dict]:
    return sorted(facts, key=lambda f: str(f.get("created_at") or ""), reverse=True)


class MemoryCard:
    async def context_for(self, tenant_id: str, companion_id: str, end_user_id: str, message: str) -> str:
        facts = await store.list_facts(tenant_id, end_user_id, companion_id)
        return render(newest_first(facts))

    async def record_turn(self, tenant_id: str, companion_id: str, end_user_id: str,
                          user_msg: str, reply: str) -> None:
        return None  # facts are written by the sweep, off the reply path

    async def forget(self, tenant_id: str, end_user_id: str) -> None:
        await store.forget_memory(tenant_id, end_user_id)
