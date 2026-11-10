"""Synthetic test people for the companion memory eval: loading and validation.

One JSON file per person in stories/ (en-01.json … ta-10.json … ta-en-10.json). Format:
{
  "id": "ta-en-03", "language": "ta-en" | "ta" | "en", "timezone": "Asia/Kolkata", "person": "Karthik",
  "theme": "pet",
  "days": [{"date": "2026-10-01", "messages": [["09:15", "user", "text"], ["09:16", "assistant", "text"]]}],
  "probes": [{"id": "ta-en-03-p1", "kind": "recall", "at": "2026-11-09T10:00", "ask": "Bruno epdi irukan?",
              "expect": "Knows Bruno is the dog who was sick", "any": ["Bruno"], "none": []}],
  "search": [{"id": "ta-en-03-s1", "query": "naai ku vet enna sonnanga?", "day": "2026-10-03", "any": ["vet"]}]
}
Times are the person's local wall-clock time. Probe kinds: recall, changed, forget, false, same_day.
Run: python -m evals.companion_memory.stories   (validates every file, prints counts)
"""
import json
import pathlib
import re
import sys
from datetime import date, datetime

HERE = pathlib.Path(__file__).parent / "stories"
KINDS = {"recall", "changed", "forget", "false", "same_day"}
LANGS = {"en", "ta", "ta-en"}
_TIME = re.compile(r"^\d{2}:\d{2}$")


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(story: dict) -> list[str]:
    errs: list[str] = []
    sid = story.get("id", "?")
    if story.get("language") not in LANGS:
        errs.append(f"{sid}: language must be one of {sorted(LANGS)}")
    for key in ("timezone", "person", "theme", "days", "probes", "search"):
        if key not in story:
            errs.append(f"{sid}: missing {key}")
    if errs:
        return errs
    last = None
    days = []
    for d in story["days"]:
        try:
            day = date.fromisoformat(d["date"])
        except (KeyError, ValueError):
            errs.append(f"{sid}: bad day date {d.get('date')}")
            continue
        days.append(day)
        prev_t = ""
        for m in d.get("messages", []):
            if not (isinstance(m, list) and len(m) == 3 and _TIME.match(str(m[0])) and m[1] in ("user", "assistant")
                    and isinstance(m[2], str) and m[2].strip()):
                errs.append(f"{sid} {day}: bad message {m!r:.80}")
                continue
            if m[0] < prev_t:
                errs.append(f"{sid} {day}: messages out of order at {m[0]}")
            prev_t = m[0]
        stamp = (day, prev_t)
        if last and stamp < last:
            errs.append(f"{sid}: days out of order at {day}")
        last = stamp
    if not 3 <= len(days) <= 20:
        errs.append(f"{sid}: {len(days)} days (3–20 expected)")
    for p in story["probes"]:
        if p.get("kind") not in KINDS:
            errs.append(f"{sid} {p.get('id')}: kind must be one of {sorted(KINDS)}")
        try:
            at = datetime.fromisoformat(p["at"])
        except (KeyError, ValueError):
            errs.append(f"{sid} {p.get('id')}: bad at")
            continue
        if days and at.date() < days[0]:
            errs.append(f"{sid} {p.get('id')}: probe before the story starts")
        for key in ("ask", "expect"):
            if not isinstance(p.get(key), str) or not p[key].strip():
                errs.append(f"{sid} {p.get('id')}: missing {key}")
        for key in ("any", "none"):
            if not isinstance(p.get(key), list):
                errs.append(f"{sid} {p.get('id')}: {key} must be a list")
    for s in story["search"]:
        if not s.get("query") or not s.get("day") or not isinstance(s.get("any"), list) or not s["any"]:
            errs.append(f"{sid} {s.get('id')}: search needs query, day, any")
    return errs


def all_stories() -> list[dict]:
    return [load(p) for p in sorted(HERE.glob("*.json"))]


if __name__ == "__main__":
    problems, counts = [], {}
    for path in sorted(HERE.glob("*.json")):
        try:
            story = load(path)
        except ValueError as exc:
            problems.append(f"{path.name}: not JSON ({exc})")
            continue
        problems += validate(story)
        lang = story.get("language", "?")
        c = counts.setdefault(lang, {"people": 0, "messages": 0, "probes": 0, "search": 0})
        c["people"] += 1
        c["messages"] += sum(len(d.get("messages", [])) for d in story.get("days", []))
        c["probes"] += len(story.get("probes", []))
        c["search"] += len(story.get("search", []))
    print(json.dumps(counts, indent=1))
    print("\n".join(problems) or "all valid")
    sys.exit(1 if problems else 0)
