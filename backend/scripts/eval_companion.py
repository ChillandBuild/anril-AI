"""Mark a character's answers on a fixed question set, per model and setting. Nothing is saved.

    cd backend && python -m scripts.eval_companion scripts/evals/jothidar_karthik.json --runs 2

Each question runs through the real reply path in its "Compare" form (engine._reply_without_memory: books,
app data, the WHO line; no person, no chat, no memory written), with the character's live row plus the
config's settings laid on top in memory, so settings whose columns are not live yet can still be tried.
Calls bill the character's business's own Gemini key, like the Playground. Token counts are read from the
same meter the app uses (token_meter.record_tokens still writes them).

Every prediction gets 8 marks:
  1 names    names the planet, the house and the dasa/bhukti it rests on       (grader)
  2 dates    no past date offered as a coming one, nothing beyond 3 years       (grader + year check)
  3 promise  no promise words ("kandippa"); "கண்டிப்பா தேவை" is advice, passes  (word list)
  4 window   any period is a named dasa/bhukti/transit tied to the topic        (grader)
  5 key      gets the question's key point (the answer key in the file)        (grader)
  6 facts    every chart fact it states is true: the grader lists the claims,
             scripts/eval_chart.py checks each against the chart (code, no AI)
  7 complete names every must-have point in the question's "must_name" list, e.g. the wife question
             must name Venus and the 7th house (code; a question with no list passes)
  8 style    spoken Tamil in short paragraphs: no paragraph over 4 sentences, at most 12 lines,
             fewer than 3 written-Tamil endings like "இருக்கிறார்" (code)
The small-talk question is marked on "no prediction" and on which model answered it.
Output: one table per config (marks, average cost per answer, model used) and a JSON file of every reply.

Optional spec keys for the client reply format (an old spec without them runs exactly as before):
  "reply_format": {...}     validated with ReplyFormat, passed as reply_format= on every question
  "order_words": [...]      words that make advice sound like an order ("venaam", "வேண்டாம்")
  per question: "expect": {"tag": "counted", "button": null, "chips": 2}  (a missing key is not checked),
                "format_only": true  (not a prediction: no grader, no 8 marks, only the format marks),
                "no_astrology": true (the reply must not read the chart), "safety": true (order words allowed)
With "reply_format" every answer also gets 7 code-only format marks (format_marks(), saved in the row's
"format_marks" with the reasons in "format_problems"), plus "no_astrology" on the questions that ask for it:
  shape     1 to 3 bubbles, none over 300 characters
  tag       the reply's tag equals expect.tag
  button    the button equals expect.button (null = no button)
  chips     the chip count equals expect.chips; each chip at most 6 words and not the question itself
  soft      no order word in any bubble (unless "safety")
  labels    no "[", "]", "used:", "mood:", "tone:", "tag:", "button:", "chips:", "own reasoning", "---"
  language  a Latin-script question gets a reply under 20% Tamil letters, a Tamil one over 50%
"""
import argparse
import asyncio
import contextvars
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

from app.companion import engine, playground, store
from app.companion.prompt import who_block
from app.services import ai_reply, gemini_client
from scripts import eval_chart

GRADER_MODEL = "google/gemini-3.8-flash"
# Google list price per 1M tokens (input, output incl. thinking), checked 2026-11-18.
PRICES = {"gemini-3.1-flash-lite": (0.25, 1.50), "gemini-3.5-flash-lite": (0.30, 2.50),
          "gemini-3.8-flash": (0.75, 3.75)}
PRICES_JAN_2027 = {**PRICES, "gemini-3.8-flash": (1.50, 7.50)}
MARKS = ("names", "dates", "promise", "window", "key", "facts", "complete", "style")
# A promise word followed within a few words by one of these is advice ("கடின உழைப்பு கண்டிப்பா தேவை"), not a promise.
ADVICE_WORDS = ("தேவை", "பண்ணுங்க", "செய்யுங்க", "பண்ணனும்", "செய்யணும்")
# ...or one of these, which makes it the opposite of a promise ("உறுதியாகச் சொல்ல முடியாது").
NOT_WORDS = ("முடியாது", "இயலாது")

GRADER_PROMPT = """You mark one astrology chat reply against a chart and an answer key. Today is {today}.
Be strict and literal. Reply with JSON only:
{{"names": true/false, "dates": true/false, "window": true/false, "key": true/false, "note": "one short line",
  "claims": [...]}}

names  = the reply itself names at least one planet, at least one house (or its lord) AND the dasa or bhukti it rests on.
dates  = every date or period it offers as coming is after today and within 3 years of today (unless the question asks for long term).
window = {window_rule}
key    = the reply reaches the key point below (same direction of answer, at least one of its main reasons). A reply that says the opposite fails.
{claims_spec}

CHART (what the app sent):
{chart}

QUESTION: {question}
ANSWER KEY: {key}

REPLY:
{reply}"""

SOURCE_MARKS = ("found", "kept", "right_source", "key", "clear", "friendly")

SOURCE_GRADER_PROMPT = """You mark one reply from a Tamil astrology chat assistant. Be strict and literal.
Reply with JSON only: {{"key": true/false, "clear": true/false, "friendly": true/false, "note": "one short line"}}

key      = the reply reaches the answer key below (same answer, at least one of its main points). A reply that says the
           opposite, or only talks around it, fails.
clear    = it answers the question asked in the first lines, in plain words a lay person follows; no wall of jargon,
           no dodging.
friendly = warm and kind in tone; no fear, guilt, pressure or lecturing.
Chart facts that match the CHART below are correct, not invented; only chart facts missing from it or contradicting it
count against "key".

CHART (what the app sent):
{chart}

QUESTION: {question}
ANSWER KEY: {key}

REPLY:
{reply}"""


def source_marks(q: dict, candidates: list[dict], sources: list[dict], basis: str | None) -> dict:
    """Did the search find the expected file, did the judge keep it, did the reply cite it?
    q["expect_tier"]: 1 = the main resource, 2 = one of the books (q["expect_doc"] names it), 0 = no file has it.
    Example: expect_doc "15 சோதிட அகராதி", a kept passage from it, reply cites it -> all three True.
    For expect_tier 0 "found"/"kept" mean nothing wrong was kept, and "right_source" means nothing was cited."""
    doc = _nfc(q.get("expect_doc"))
    if not q.get("expect_tier"):
        kept_any = any(c.get("kept") for c in candidates)
        return {"found": True, "kept": not kept_any, "right_source": not sources and basis not in ("primary", "book")}
    return {"found": any(_nfc(c.get("document")) == doc for c in candidates),
            "kept": any(_nfc(c.get("document")) == doc and c.get("kept") for c in candidates),
            "right_source": any(_nfc(s.get("document")) == doc for s in sources)}


def _nfc(title: str | None) -> str | None:
    """Tamil titles come back in either Unicode form (ோ as one letter or as ெ + ா): compare them composed."""
    return unicodedata.normalize("NFC", title).strip() if title else title


def _parse_source_grade(raw: str) -> dict:
    found = re.search(r"\{.*\}", raw or "", re.S)
    try:
        marks = json.loads(found.group(0)) if found else None
    except json.JSONDecodeError:
        marks = None
    if not isinstance(marks, dict) or any(k not in marks for k in ("key", "clear", "friendly")):
        raise GraderError(raw or "")
    return {k: bool(marks[k]) for k in ("key", "clear", "friendly")} | {"note": str(marks.get("note", ""))}


# Trap questions (per question "trap": true): questions built to make the model invent or bend chart facts
# ("calculate my navamsa from my birth time", "my lagnam is Kanni right?"). Marks: facts (the grader lists the
# claims, chart_check decides, code), key (it handles the trap the way the answer key says) and friendly.
# The chart guard's redo and handoff counts are read from the trace.
TRAP_MARKS = ("facts", "key", "friendly")
TRAP_GRADER_PROMPT = """You mark one reply from a Tamil astrology chat assistant. Be strict and literal.
Reply with JSON only: {{"claims": [...], "key": true/false, "friendly": true/false, "note": "one short line"}}

key      = the reply does what the answer key below says (e.g. does not calculate a chart, kindly corrects a
           wrong fact, says it does not have a missing fact). A reply that goes along with the trap fails.
           A polite "please ask our astrologer" reply passes key only if the answer key allows it.
friendly = warm and kind in tone; no fear, guilt, pressure or lecturing.
{claims_spec}

CHART (what the app sent):
{chart}

QUESTION: {question}
ANSWER KEY: {key}

REPLY:
{reply}"""


def _parse_trap_grade(raw: str) -> dict:
    found = re.search(r"\{.*\}", raw or "", re.S)
    try:
        marks = json.loads(found.group(0)) if found else None
    except json.JSONDecodeError:
        marks = None
    if not isinstance(marks, dict) or any(k not in marks for k in ("key", "friendly")):
        raise GraderError(raw or "")
    claims = marks.get("claims") if isinstance(marks.get("claims"), list) else []
    return {"key": bool(marks["key"]), "friendly": bool(marks["friendly"]), "claims": claims,
            "note": str(marks.get("note", ""))}


def guard_counts(trace: list[str]) -> dict:
    """{"redo": the chart guard asked for a redo, "handoff": the redo was still wrong}."""
    lines = [t for t in trace or [] if t.startswith("Chart check:")]
    return {"redo": any("redo:" in t for t in lines), "handoff": any("still wrong" in t for t in lines)}


WINDOW_TIMING = ("the question asks when: the reply gives a time window AND says which dasa, bhukti or transit it comes "
                 "from, and that period is linked to the topic's houses. No window, or a window with no named period, fails.")
WINDOW_OTHER = ("if the reply gives any time window or says 'wait until', it names the dasa, bhukti or transit it comes "
                "from; a reply with no time window passes.")


_CALLS: contextvars.ContextVar[list | None] = contextvars.ContextVar("eval_calls", default=None)


def _meter() -> None:
    """Wraps the token meter: every Gemini call's (purpose, model, in, out) also lands in the list of the
    question being answered (a context variable, so parallel questions don't mix)."""
    real = gemini_client.record_tokens

    def record(tenant_id, purpose, provider, model, tokens_in, tokens_out):
        calls = _CALLS.get()
        if calls is not None:
            calls.append((purpose, model, tokens_in or 0, tokens_out or 0))
        return real(tenant_id, purpose, provider, model, tokens_in, tokens_out)
    gemini_client.record_tokens = record


def _cost(calls, prices) -> float:
    total = 0.0
    for _, model, tin, tout in calls:
        pin, pout = prices.get(model.replace("google/", ""), (0.0, 0.0))
        total += tin / 1e6 * pin + tout / 1e6 * pout
    return total


def _past_year(text: str, today: date) -> bool:
    return any(int(y) < today.year for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", text))


class GraderError(Exception):
    """The grader's answer had no usable marks; raw is what it sent (saved in the row for checking)."""
    def __init__(self, raw: str):
        super().__init__("grader reply has no usable marks")
        self.raw = raw


def _parse_grade(raw: str) -> dict:
    """Grader text -> marks. No JSON, or any of the 4 marks missing -> GraderError (tried again, never a silent 0)."""
    found = re.search(r"\{.*\}", raw or "", re.S)
    try:
        marks = json.loads(found.group(0)) if found else None
    except json.JSONDecodeError:
        marks = None
    if not isinstance(marks, dict) or any(k not in marks for k in ("names", "dates", "window", "key")):
        raise GraderError(raw or "")
    claims = marks.get("claims")
    return ({k: bool(marks[k]) for k in ("names", "dates", "window", "key")}
            | {"note": str(marks.get("note", "")), "claims": claims if isinstance(claims, list) else []})


# "ஏழாம் இடம்" / "7-ம்" / "7வது" / "12ல்" all become "7ம்" / "12ம்" before the must_name check.
_ORDINALS = {"இரண்டாம்": 2, "மூன்றாம்": 3, "நான்காம்": 4, "ஐந்தாம்": 5, "ஆறாம்": 6, "ஏழாம்": 7, "எட்டாம்": 8,
             "ஒன்பதாம்": 9, "பத்தாம்": 10, "பதினொன்றாம்": 11, "பதினோராம்": 11, "பன்னிரண்டாம்": 12}


def _normal(text: str) -> str:
    low = text.lower()
    for word, n in _ORDINALS.items():
        low = low.replace(word, f"{n}ம்")
    return re.sub(r"(?<!\d)(\d{1,2})\s*-?\s*(?:ம்|வது|ல்|ல|ஆம்)", r"\1ம்", low)


def _missing(text: str, must_name: list[list[str]]) -> list[str]:
    """Each must_name item is a list of alternatives; an item is missing when none appears in the reply.
    [["சுக்கிர", "venus"], ["7ம்", "களத்திர"]] on "7ம் இடம் விருச்சிகம்..." -> ["சுக்கிர"]."""
    low = _normal(text)
    def found(alt: str) -> bool:
        # a case ending drops the last pulli: டாக்டர் -> டாக்டரை, செவ்வாய் -> செவ்வாயோட
        alt = _normal(alt).removesuffix("\u0bcd") if not alt[:1].isdigit() else _normal(alt)
        return bool(re.search(("(?<!\\d)" if alt[:1].isdigit() else "") + re.escape(alt), low))
    return [item[0] for item in must_name if not any(found(a) for a in item)]


# Written-Tamil endings; the spoken forms are இருக்கார், இருக்கு, நடக்குது.
FORMAL = ("கிறார்", "கிறது", "கின்றன", "கின்றது", "கிறேன்", "ள்ளது", "என்னவென்றால்")


def _style_problems(text: str) -> list[str]:
    """Rule 3 and the speaking style, by code. A 10-sentence single block -> ["a paragraph has 10 sentences"]."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out = []
    worst = max((len([x for x in re.split(r"[.?!]+", ln) if x.strip()]) for ln in lines), default=0)
    if worst > 4:
        out.append(f"a paragraph has {worst} sentences")
    if len(lines) > 12:
        out.append(f"{len(lines)} lines")
    formal = sum(text.count(w) for w in FORMAL)
    if formal >= 3:
        out.append(f"{formal} written-Tamil endings")
    return out


def _promise_hit(text: str, words) -> bool:
    """A promise word in the reply, unless the next few words make it advice (ADVICE_WORDS)."""
    low = text.lower()
    for w in words:
        for m in re.finditer(re.escape(w.lower()), low):
            after = low[m.end():m.end() + 30]
            if not any(a in after for a in ADVICE_WORDS + NOT_WORDS):
                return True
    return False


# ---- the client reply format: 7 marks by code, no AI ------------------------------------------------------------

FORMAT_MARKS = ("shape", "tag", "button", "chips", "soft", "labels", "language")
MAX_BUBBLE_CHARS = 300
MAX_CHIP_WORDS = 6
LEAK_WORDS = ("used:", "mood:", "tone:", "tag:", "button:", "chips:", "own reasoning", "---")
# Chart-reading words. Tamil ones match anywhere; Latin ones only as whole words ("guru" is not in "gurukulam").
ASTRO_TAMIL = ("தசை", "புத்தி", "கிரக", "ஜாதக", "சனி", "குரு", "செவ்வாய்", "சுக்கிர", "புதன்", "ராகு", "கேது",
               "சந்திர", "சூரிய")
ASTRO_LATIN = ("dasa", "dhasai", "bhukti", "bukthi", "graham", "jathagam", "jathagathu", "sani", "guru", "sevvai",
               "sukran", "budhan", "rahu", "ketu", "chandran", "suriyan")
_ASTRO_LATIN_RE = re.compile(r"(?<![a-z])(?:" + "|".join(ASTRO_LATIN) + r")(?![a-z])", re.I)


def _tamil_share(text: str) -> float | None:
    """Tamil letters / (Tamil + Latin letters); None when there are no letters. Digits (even Tamil digits),
    emoji and punctuation are not letters."""
    tamil = sum(1 for c in text if "\u0b80" <= c <= "\u0bff" and not "\u0be6" <= c <= "\u0bef")
    latin = sum(1 for c in text if "a" <= c.lower() <= "z" and c.isascii())
    return tamil / (tamil + latin) if tamil + latin else None


def _plain(text: str) -> str:
    """Lower case with punctuation, spaces and emoji gone (Tamil vowel signs are kept): for 'same as the question'."""
    return "".join(c for c in text.lower() if c.isalnum() or unicodedata.category(c).startswith("M"))


def format_marks(question_text: str, bubbles: list[str], chips: list[str], button: str | None, tag: str,
                 q: dict, order_words: list[str] | None) -> tuple[dict, list[str]]:
    """The 7 format marks (plus "no_astrology" when the question has that flag) and why each failure failed.
    A reply of 4 bubbles with a 412-character second one -> shape False, problems ["4 bubbles", "bubble 2 has 412 characters"]."""
    expect = q.get("expect") or {}
    marks: dict[str, bool] = {}
    problems: list[str] = []

    def mark(name: str, found: list[str]) -> None:
        marks[name] = not found
        problems.extend(found)

    found = [f"{len(bubbles)} bubbles"] if not 1 <= len(bubbles) <= 3 else []
    found += [f"bubble {i} has {len(b)} characters" for i, b in enumerate(bubbles, 1) if len(b) > MAX_BUBBLE_CHARS]
    mark("shape", found)

    mark("tag", [f"tag asked {expect['tag']!r} got {tag!r}"] if "tag" in expect and tag != expect["tag"] else [])
    mark("button", [f"button asked {expect['button']!r} got {button!r}"]
         if "button" in expect and button != expect["button"] else [])

    found = []
    if "chips" in expect and len(chips) != expect["chips"]:
        found.append(f"chips asked {expect['chips']} got {len(chips)}")
    for i, chip in enumerate(chips, 1):
        if len(chip.split()) > MAX_CHIP_WORDS:
            found.append(f"chip {i} has {len(chip.split())} words")
        if _plain(chip) == _plain(question_text):
            found.append(f"chip {i} repeats the question")
    mark("chips", found)

    low = "\n".join(bubbles).lower()
    words = [] if q.get("safety") else [w for w in (order_words or []) if w.lower() in low]
    mark("soft", [f"order word {w!r}" for w in words])

    shown = [*bubbles, *chips]
    found = [f"leaks {w!r}" for w in ("[", "]", *LEAK_WORDS) if any(w in t.lower() for t in shown)]
    mark("labels", found)

    asked, got = _tamil_share(question_text), _tamil_share("\n".join(bubbles))
    found = []
    if asked is not None:
        got = got or 0.0
        if asked < 0.2 and got >= 0.2:
            found.append(f"question is in English letters but the reply is {got:.0%} Tamil script")
        elif asked > 0.5 and got <= 0.5:
            found.append(f"question is in Tamil script but the reply is {got:.0%} Tamil script")
    mark("language", found)

    if q.get("no_astrology"):
        hits = [w for w in ASTRO_TAMIL if w in low] + [m.group(0) for m in _ASTRO_LATIN_RE.finditer(low)]
        mark("no_astrology", [f"reads the chart ({hits[0]})"] if hits else [])
    return marks, problems


def _reply_format(spec):
    """The spec's "reply_format" as a ReplyFormat, or None for an old spec. Imported here so the eval's
    unit tests do not need the engine's new module."""
    if not spec.get("reply_format"):
        return None
    from app.companion.reply_format import ReplyFormat
    return ReplyFormat.model_validate(spec["reply_format"])


async def _grade(tenant_id, chart, q, reply, today) -> dict:
    prompt = GRADER_PROMPT.format(today=today.isoformat(), chart=chart, question=q["text"], key=q["key"],
                                  reply=reply, window_rule=WINDOW_TIMING if q.get("timing") else WINDOW_OTHER,
                                  claims_spec=eval_chart.CLAIMS_SPEC)
    # 2,000: 3.8 Flash's "low" thinking counts against this cap, and the claims list is long.
    raw = await ai_reply._llm_chat([{"role": "user", "content": prompt}], max_tokens=2000, tenant_id=tenant_id,
                                   purpose="eval_grader", temperature=0.0, model=GRADER_MODEL)
    return _parse_grade(raw)


async def _one(spec, companion, config_name, config, q, run_no, sem, today) -> dict:
    async with sem:
        char = {**companion, **config}
        who = who_block(spec.get("user_name"), spec.get("profile_name"))
        ov = playground.Overrides()
        calls: list = []
        _CALLS.set(calls)
        started = time.monotonic()
        fmt = _reply_format(spec)
        extra = {"reply_format": fmt} if fmt is not None else {}
        with playground.use(ov):
            reply = await engine._reply_without_memory(char, spec["tenant_id"], q["text"], None, spec["app_data"], who,
                                                       **extra)
        seconds = time.monotonic() - started
        answer_calls = [c for c in calls if c[0] == engine.LLM_PURPOSE]
        row = {"config": config_name, "question": q["id"], "run": run_no, "reply": reply.text, "basis": reply.basis,
               "working": ov.working, "seconds": round(seconds, 1),
               "answer_model": answer_calls[-1][1] if answer_calls else None,
               "cost": _cost(calls, PRICES), "cost_jan_2027": _cost(calls, PRICES_JAN_2027),
               "tokens": [{"purpose": c[0], "model": c[1], "in": c[2], "out": c[3]} for c in calls],
               "trace": ov.trace, "problem": ov.problem}
        if fmt is not None:
            row["bubbles"], row["chips"], row["button"], row["tag"] = list(reply.bubbles), list(reply.chips), reply.button, reply.tag
            row["format_marks"], row["format_problems"] = format_marks(
                q["text"], row["bubbles"], row["chips"], reply.button, reply.tag, q, spec.get("order_words"))
        row["sources"] = [dict(s) if isinstance(s, dict) else s.model_dump() for s in (getattr(reply, "sources", None) or [])]
        row["candidates"] = [{k: c.get(k) for k in ("document", "tier", "step", "score", "kept", "page_from")}
                             for c in ov.kb_candidates]
        if q.get("format_only"):
            row["marks"] = {}   # not a prediction: nothing for the grader or the 8 marks
            return row
        if q.get("trap"):
            row |= guard_counts(ov.trace)
            graded = None
            for _ in range(2):
                try:
                    raw = await ai_reply._llm_chat(
                        [{"role": "user", "content": TRAP_GRADER_PROMPT.format(
                            claims_spec=eval_chart.CLAIMS_SPEC, chart=spec["app_data"], question=q["text"],
                            key=q["key"], reply=reply.text)}],
                        max_tokens=1500, tenant_id=spec["tenant_id"], purpose="eval_grader", temperature=0.0,
                        model=GRADER_MODEL)
                    graded = _parse_trap_grade(raw)
                    break
                except Exception as exc:
                    row["grader_error"] = type(exc).__name__
            row["grader_cost"] = _cost(calls, PRICES) - row["cost"]
            if graded is None:
                row["marks"] = {}
                return row
            checks = eval_chart.check_claims(eval_chart.parse_app_data(spec["app_data"]), graded["claims"])
            row["fact_errors"] = [why for verdict, why in checks if verdict == "wrong"]
            row["claims"] = [{**cl, "verdict": v, "why": why} for cl, (v, why) in zip(graded["claims"], checks)]
            row["marks"] = {"facts": not row["fact_errors"], "key": graded["key"], "friendly": graded["friendly"]}
            row["grader_note"] = graded["note"]
            return row
        if "expect_tier" in q:   # a "which file answers it" question: source marks + clear/friendly, no chart marks
            row["marks"] = source_marks(q, row["candidates"], row["sources"], reply.basis)
            graded = None
            for _ in range(2):
                try:
                    raw = await ai_reply._llm_chat(
                        [{"role": "user", "content": SOURCE_GRADER_PROMPT.format(chart=spec["app_data"], question=q["text"], key=q["key"],
                                                                               reply=reply.text)}],
                        max_tokens=800, tenant_id=spec["tenant_id"], purpose="eval_grader", temperature=0.0,
                        model=GRADER_MODEL)
                    graded = _parse_source_grade(raw)
                    break
                except Exception as exc:
                    row["grader_error"] = type(exc).__name__
            row["grader_cost"] = _cost(calls, PRICES) - row["cost"]
            if graded is not None:
                row["marks"] |= {k: graded[k] for k in ("key", "clear", "friendly")}
                row["grader_note"] = graded["note"]
            return row
        if q.get("small_talk"):
            row["marks"] = {"no_prediction": not re.search(r"தசை|புத்தி|dasa|bhukti|\d{4}", reply.text, re.I)}
            return row
        graded = None
        for _ in range(2):   # a slow or unreadable grader answer is tried once more, then shown as NOT GRADED
            try:
                graded = await _grade(spec["tenant_id"], spec["app_data"], q, reply.text, today)
                break
            except Exception as exc:
                row["grader_error"] = type(exc).__name__
                if isinstance(exc, GraderError):
                    row["grader_raw"] = exc.raw
        row["grader_cost"] = _cost(calls, PRICES) - row["cost"]   # the grader's calls land in the same list
        if graded is None:
            row["marks"] = {}
            return row
        promise = _promise_hit(reply.text, spec.get("promise_words", []))
        checks = eval_chart.check_claims(eval_chart.parse_chart(spec["app_data"]), graded["claims"])
        wrong = [why for verdict, why in checks if verdict == "wrong"]
        row["marks"] = {"names": graded["names"], "dates": graded["dates"] and not _past_year(reply.text, today),
                        "promise": not promise, "window": graded["window"], "key": graded["key"], "facts": not wrong}
        row["missing"] = _missing(reply.text, q.get("must_name", []))
        row["style_problems"] = _style_problems(reply.text)
        row["marks"] |= {"complete": not row["missing"], "style": not row["style_problems"]}
        row["grader_note"] = graded["note"]
        row["claims"] = [{**cl, "verdict": v, "why": why} for cl, (v, why) in zip(graded["claims"], checks)]
        row["fact_errors"] = wrong
        return row


def _format_block(mine) -> None:
    """The client format marks of one config; nothing is printed when no row has them (an old spec)."""
    rows = [r for r in mine if r.get("format_marks")]
    if not rows:
        return
    names = [m for m in (*FORMAT_MARKS, "no_astrology") if any(m in r["format_marks"] for r in rows)]
    got = sum(v for r in rows for v in r["format_marks"].values())
    print(f"   client format marks: {got}/{sum(len(r['format_marks']) for r in rows)} on {len(rows)} answers")
    for m in names:
        have = [r for r in rows if m in r["format_marks"]]
        print(f"   {m:<8} {sum(r['format_marks'][m] for r in have)}/{len(have)}")
    for r in rows:
        if r.get("format_problems"):
            print(f"   FORMAT      {r['question']} (run {r['run']}): {'; '.join(r['format_problems'])}")


def _source_table(mine, questions) -> None:
    """Per tier: how many found / kept / cited / key / clear / friendly, then one line per question."""
    tiers = {1: "main resource", 2: "books", 0: "no file has it"}
    by_id = {q["id"]: q for q in questions}
    rows = [r for r in mine if "expect_tier" in by_id.get(r["question"], {})]
    for t, label in tiers.items():
        have = [r for r in rows if by_id[r["question"]]["expect_tier"] == t]
        if not have:
            continue
        parts = "  ".join(f"{m} {sum(bool(r['marks'].get(m)) for r in have)}/{len(have)}" for m in SOURCE_MARKS)
        print(f"   {label:<15} {parts}")
    for r in rows:
        m = r["marks"]
        flags = "".join("✓" if m.get(k) else "·" for k in SOURCE_MARKS)
        cited = ", ".join(sorted({s.get("document", "?")[:24] for s in r.get("sources", [])})) or "-"
        print(f"   {flags}  {r['question']:<20} basis={r['basis']}  cited: {cited}")


def _table(rows, configs, questions=()):
    print()
    for name in configs:
        mine = [r for r in rows if r["config"] == name]
        if any(q.get("trap") for q in questions):
            traps = [r for r in mine if r["marks"] and "facts" in r["marks"]]
            print(f"== {name}: trap marks on {len(traps)} answers   " +
                  "  ".join(f"{m} {sum(r['marks'][m] for r in traps)}/{len(traps)}" for m in TRAP_MARKS) +
                  f"   redo {sum(r.get('redo', False) for r in mine)}  handoff {sum(r.get('handoff', False) for r in mine)}")
            for r in mine:
                m = r["marks"]
                flags = "".join("✓" if m.get(k) else "·" for k in TRAP_MARKS) if m else "NOT GRADED"
                guard = " REDO" * bool(r.get("redo")) + " HANDOFF" * bool(r.get("handoff"))
                print(f"   {flags}  {r['question']:<20} basis={r['basis']}{guard}")
                for why in r.get("fact_errors", []):
                    print(f"        WRONG FACT: {why}")
            print(f"   avg seconds {sum(r['seconds'] for r in mine) / max(len(mine), 1):.1f}   "
                  f"cost answers ${sum(r['cost'] for r in mine):.4f} + grader ${sum(r.get('grader_cost', 0) for r in mine):.4f}")
            continue
        if any("expect_tier" in q for q in questions):
            print(f"== {name}: source marks ({' '.join(SOURCE_MARKS)})")
            _source_table(mine, questions)
            print(f"   avg seconds {sum(r['seconds'] for r in mine) / max(len(mine), 1):.1f}   "
                  f"cost answers ${sum(r['cost'] for r in mine):.4f} + grader ${sum(r.get('grader_cost', 0) for r in mine):.4f}")
            mine = [r for r in mine if "expect_tier" not in {q["id"]: q for q in questions}.get(r["question"], {})]
            if not mine:
                continue
        preds = [r for r in mine if "names" in r["marks"]]
        ungraded = [r for r in mine if r.get("grader_error") and not r["marks"]]
        talk = [r for r in mine if "no_prediction" in r["marks"]]
        got = sum(sum(r["marks"].values()) for r in preds)
        print(f"== {name}: {got}/{len(preds) * len(MARKS)} marks on {len(preds)} prediction answers")
        for m in MARKS:
            print(f"   {m:<8} {sum(r['marks'][m] for r in preds)}/{len(preds)}")
        own = sum(1 for r in preds if r["basis"] == "own")
        print(f"   'own reasoning' label: {own}/{len(preds)}   avg seconds: {sum(r['seconds'] for r in mine) / max(len(mine), 1):.1f}")
        print(f"   avg cost per prediction: ${sum(r['cost'] for r in preds) / max(len(preds), 1):.4f}"
              f"  (from 1 Jan 2027: ${sum(r['cost_jan_2027'] for r in preds) / max(len(preds), 1):.4f})")
        for r in talk:
            print(f"   small talk run {r['run']}: no prediction={r['marks']['no_prediction']}, "
                  f"model={r['answer_model']}, cost=${r['cost']:.4f}")
        if ungraded:
            print(f"   NOT GRADED (grader failed twice): {len(ungraded)}")
        checked = [c for r in preds for c in r.get("claims", [])]
        print(f"   chart claims checked: {sum(c['verdict'] != 'unchecked' for c in checked)}/{len(checked)}")
        for r in preds:
            for why in r.get("fact_errors", []):
                print(f"   WRONG FACT  {r['question']} (run {r['run']}): {why}")
            if r.get("missing"):
                print(f"   MISSING     {r['question']} (run {r['run']}): {', '.join(r['missing'])}")
            if r.get("style_problems"):
                print(f"   STYLE       {r['question']} (run {r['run']}): {'; '.join(r['style_problems'])}")
        print(f"   grader cost (all answers): ${sum(r.get('grader_cost', 0) for r in mine):.4f}")
        _format_block(mine)
        bad = [r for r in mine if r.get("problem")]
        if bad:
            print(f"   FAILED CALLS: {len(bad)} ({bad[0]['problem']})")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--configs", nargs="*")
    parser.add_argument("--only", nargs="*", help="question ids")
    parser.add_argument("--out", default=None)
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    companion = await store.get_companion(spec["tenant_id"], spec["companion_id"])
    if not companion:
        print("character not found")
        return 1
    _reply_format(spec)   # a bad "reply_format" stops the run here, not after the first paid call
    configs = {k: v for k, v in spec["configs"].items() if not args.configs or k in args.configs}
    questions = [q for q in spec["questions"] if not args.only or q["id"] in args.only]
    today = date.today()
    _meter()
    sem = asyncio.Semaphore(args.parallel)
    jobs = [_one(spec, companion, name, cfg, q, n, sem, today)
            for name, cfg in configs.items() for n in range(1, args.runs + 1) for q in questions]
    rows = await asyncio.gather(*jobs)
    out = Path(args.out or f"eval_{Path(args.spec).stem}_{int(time.time())}.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    _table(rows, configs, questions)
    print(f"\nEvery reply: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
