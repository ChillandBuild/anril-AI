"""The manager's call report: the prompt that asks the AI for it, and the validator that checks it.

The AI is untrusted. Every quote must be found in the transcript (by the right speaker);
the time always comes from the matched line, never from the AI. Anything that fails is dropped.
"""
from app.services.call_lines import Line, clock
from app.services.call_quotes import clip, find_quote

REPORT_VERSION = 1
MAX_MOOD = 8
MAX_OBJECTIONS = 6
MAX_PROMISES = 6

_CUSTOMER = ("customer",)
_TELECALLER = ("telecaller",)
_BOTH = ("telecaller", "customer")
_MOODS = {"positive", "neutral", "negative"}
_DIRECTIONS = {"warmed", "cooled"}
_HANDLING = {"handled", "partly", "dodged"}

REPORT_RUBRIC = """
Also return a "report" key with these parts. Copy every "quote" EXACTLY from the transcript (original language, same speaker). Write "why" and "tip" in English, one short sentence each.
- mood: 3-8 moments of the CUSTOMER's mood across the call, in time order. {"quote": customer words, "mood": "positive"|"neutral"|"negative"}
- turning_point: the single moment the customer clearly warmed or cooled, or null. {"quote": customer words, "direction": "warmed"|"cooled", "why": ...}
- objections: each customer objection or concern. {"quote": customer words, "handling": "handled"|"partly"|"dodged", "why": how the telecaller responded}
- promises: each concrete promise or offer by the TELECALLER (discount, guarantee, refund, timeline, freebie, placement). {"quote": telecaller words, "risky": true if the knowledge base does not support it else false, "why": ...}
- coach: exactly one tip. {"quote": exact words from the moment to fix, "tip": what to do differently}
Use [] for a part with nothing to report.
Example shape: "report": {"mood": [{"quote": "<customer words>", "mood": "negative"}], "turning_point": {"quote": "<customer words>", "direction": "cooled", "why": "<reason>"}, "objections": [{"quote": "<customer words>", "handling": "dodged", "why": "<reason>"}], "promises": [{"quote": "<telecaller words>", "risky": true, "why": "<reason>"}], "coach": {"quote": "<words>", "tip": "<one sentence>"}}
""".strip()


def _text(value) -> str:
    return clip(value.strip()) or "" if isinstance(value, str) else ""


def _enum(value, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in allowed else None


def _located(item: dict, lines: list[Line], speakers: tuple[str, ...]) -> tuple[Line, dict] | None:
    """Find the item's quote in the transcript; return the line and the fields the AI may not set."""
    line = find_quote(item.get("quote"), lines, speakers=speakers)
    if line is None:
        return None
    return line, {"time": clock(line.start), "start": line.start, "quote": clip(item["quote"])}


def _mood_item(item: dict, lines: list[Line]) -> tuple[Line, dict] | None:
    mood = _enum(item.get("mood"), _MOODS)
    found = _located(item, lines, _CUSTOMER) if mood else None
    return None if found is None else (found[0], {**found[1], "mood": mood})


def _objection_item(item: dict, lines: list[Line]) -> tuple[Line, dict] | None:
    handling = _enum(item.get("handling"), _HANDLING)
    found = _located(item, lines, _CUSTOMER) if handling else None
    return None if found is None else (found[0], {**found[1], "handling": handling, "why": _text(item.get("why"))})


def _promise_item(item: dict, lines: list[Line]) -> tuple[Line, dict] | None:
    found = _located(item, lines, _TELECALLER)
    if found is None:
        return None
    risky = item.get("risky") is True
    return found[0], {**found[1], "risky": risky, "why": _text(item.get("why"))}


def _collect(raw_list, lines: list[Line], build, cap: int, dedupe: bool) -> list[dict]:
    """Validate each dict item in AI order, optionally dedupe by matched line, cap, then sort by time."""
    if not isinstance(raw_list, list):
        return []
    out: list[dict] = []
    seen: set[Line] = set()
    for item in raw_list:
        if len(out) >= cap:
            break
        built = build(item, lines) if isinstance(item, dict) else None
        if built is None:
            continue
        line, fields = built
        if dedupe and line in seen:
            continue
        seen.add(line)
        out.append(fields)
    return sorted(out, key=lambda f: f["start"])


def _turning_point(raw, lines: list[Line]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    direction = _enum(raw.get("direction"), _DIRECTIONS)
    found = _located(raw, lines, _CUSTOMER) if direction else None
    return None if found is None else {**found[1], "direction": direction, "why": _text(raw.get("why"))}


def _coach(raw, lines: list[Line]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    tip = _text(raw.get("tip"))
    found = _located(raw, lines, _BOTH) if tip else None
    return None if found is None else {**found[1], "tip": tip}


def build_report(raw, lines: list[Line]) -> dict:
    """Turn the AI's raw report into a validated dict. Returns {} when nothing survives. Never raises."""
    if not isinstance(raw, dict):
        return {}
    candidates = {
        "mood": _collect(raw.get("mood"), lines, _mood_item, MAX_MOOD, dedupe=False),
        "turning_point": _turning_point(raw.get("turning_point"), lines),
        "objections": _collect(raw.get("objections"), lines, _objection_item, MAX_OBJECTIONS, dedupe=True),
        "promises": _collect(raw.get("promises"), lines, _promise_item, MAX_PROMISES, dedupe=True),
        "coach": _coach(raw.get("coach"), lines),
    }
    report = {key: value for key, value in candidates.items() if value}
    return {"report_version": REPORT_VERSION, **report} if report else {}
