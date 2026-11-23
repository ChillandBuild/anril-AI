"""v9.2 Anril Brain, the top of the page: how much the AI agent knows, who it is, the goal of every
chat, Never do, recent changes and this week's numbers.

Everything here is read from what already drives replies (the Description sections, the language
setting, the Knowledge Kit readiness, the version history). The one new setting is the chat goals
(app_settings.ai_chat_goals, a JSON list of up to two goal keys), which _build_base_prompt turns
into a GOAL line (goals_block below).
"""
import json
import logging

from app.config_dynamic import get_setting, invalidate_cache, save_setting

logger = logging.getLogger(__name__)

GOALS_KEY = "ai_chat_goals"
GOALS = {
    "order": ("Take the order", "take the order: help them choose and get it paid or confirmed"),
    "visit": ("Book a visit", "book a visit: agree a day and time for them to come"),
    "callback": ("Get a call back", "get a call back: ask when a person from the team may call them"),
    "advance": ("Collect advance", "collect an advance payment to confirm"),
}
MAX_GOALS = 2
LANGUAGE_WORDS = {
    "mirror": "Same as the customer", "tanglish": "Tanglish", "english": "English", "tamil": "Tamil",
    "tanglish_escalate_tamil": "Tanglish first",
}


def get_goals(tenant_id: str | None) -> list[str]:
    try:
        raw = json.loads(get_setting(GOALS_KEY, tenant_id=tenant_id) or "[]")
    except (ValueError, TypeError):
        return []
    return [g for g in raw if g in GOALS][:MAX_GOALS] if isinstance(raw, list) else []


def clean_goals(goals: list[str]) -> list[str]:
    """Known keys only, no repeats, at most two, in the order picked."""
    out: list[str] = []
    for g in goals:
        if g in GOALS and g not in out:
            out.append(g)
    if len(out) > MAX_GOALS:
        raise ValueError("Pick one or two goals.")
    return out


def save_goals(tenant_id: str, goals: list[str]) -> list[str]:
    goals = clean_goals(goals)
    save_setting(GOALS_KEY, json.dumps(goals), tenant_id=tenant_id)
    invalidate_cache(GOALS_KEY)
    return goals


def goals_block(tenant_id: str | None) -> str:
    """The prompt line. One goal: aim for it. Two: the first, and the second only if they say not now."""
    goals = get_goals(tenant_id)
    if not goals:
        return ""
    first = GOALS[goals[0]][1]
    text = f"\n\nGOAL OF EVERY CHAT (this business's choice): work towards one thing at a time. First, {first}."
    if len(goals) > 1:
        text += f" Only if the customer says not now, {GOALS[goals[1]][1]}."
    return text + " Never push: answer what they ask first."


def _first_line(text: str, limit: int = 60) -> str:
    line = next((l.strip(" -*•\t") for l in (text or "").splitlines() if l.strip(" -*•\t")), "")
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _rules(text: str) -> list[str]:
    return [l.strip(" -*•\t") for l in (text or "").splitlines() if l.strip(" -*•\t")]


def overview(db, tenant_id: str) -> dict:
    from app.services import business_profile
    from app.services import knowledge_versions as kv
    from app.services.knowledge_kit import readiness

    description = get_setting("business_description", tenant_id=tenant_id) or ""
    sections = business_profile.parse(description).sections
    try:
        live = (db.table("knowledge_documents").select("full_text").eq("tenant_id", tenant_id)
                .eq("status", "indexed").execute().data or [])
    except Exception:
        live = []
    items = readiness(description=description, handover_line=business_profile.get_handover_line(tenant_id),
                      facts=[r.get("full_text") or "" for r in live])
    weights = {"must": 3, "nice": 2, "optional": 1}
    total = sum(weights[i["level"]] for i in items)
    have = sum(weights[i["level"]] for i in items if i["ok"])
    never = _rules(sections.get("never", ""))
    try:
        versions = kv.list_versions(db, tenant_id, "description", limit=4)
    except Exception:
        versions = []
    mode = get_setting("reply_language_mode", fallback="mirror", tenant_id=tenant_id) or "mirror"
    return {
        "knows_pct": round(have * 100 / total) if total else 0,
        "missing": [i["label"] for i in items if not i["ok"]][:3],
        "who": {
            "talks_like": _first_line(sections.get("voice", "")) or None,
            "language": LANGUAGE_WORDS.get(mode, "Same as the customer"),
            "about": _first_line(sections.get("about", ""), 90) or None,
        },
        "goals": get_goals(tenant_id),
        "goal_choices": [{"key": k, "label": v[0]} for k, v in GOALS.items()],
        "never": {"count": len(never), "first": never[:2]},
        "recent": [{"id": v.get("id"), "reason": v.get("reason"), "at": v.get("created_at")} for v in versions[:3]],
    }
