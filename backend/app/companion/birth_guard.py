"""Chart guard, part 1: birth date, time and place never reach the reply model.

With them the model can work out a chart of its own and mix it with the one the app sent. Without them
it can only read the app's chart. Only for characters with companions.chart_guard on (an astrology app
whose app sends the finished chart); every other business's prompt is untouched.

Three shapes come in:
- the app's chart as JSON  -> birth keys dropped:   {"dob": "19-11-2003", "rasi": "Simmam"} -> {"rasi": "Simmam"}
- the app's chart as text  -> labelled lines dropped: "Birth time: 10:30 AM" -> (line gone); "Rasi: Simmam" stays
- chat, memory notes       -> the part of a sentence that gives birth details is hidden:
      "I was born on 19 Nov 2003 at 10:30 AM in Madurai. Will I get a job?"
      -> "[birth details hidden] Will I get a job?"
  "என் பிறந்த நட்சத்திரம் உத்திரம்" stays: a birth star is part of the chart, not a birth detail.
"""
from __future__ import annotations

import json
import re

HIDDEN = "[birth details hidden]"

# Keys an app may use for birth details (compared lower-case, with "-", " " and "." as "_").
_BIRTH_KEY = re.compile(
    r"^(?:birth.*|.*_?dob|dob_?.*|date_of_birth|time_of_birth|place_of_birth|birth_?place|tob|pob|lat|latitude|"
    r"lng|lon|long|longitude|lat_?long|timezone|time_?zone|tz|utc_?offset|tamil_?date)$")

# A text chart's own lines: "Birth date: …", "Lat / Long: …", "Tamil date: …", "பிறந்த தேதி: …".
_LABEL_LINE = re.compile(
    r"^[ \t]*(?:[-•*][ \t]*)?(?:birth[ \t]*(?:date|time|place|details?)|date[ \t]+of[ \t]+birth|time[ \t]+of[ \t]+birth|"
    r"place[ \t]+of[ \t]+birth|d\.?o\.?b\.?|lat(?:itude)?[ \t]*/[ \t]*long(?:itude)?|latitude|longitude|time[ \t]*zone|"
    r"tamil[ \t]+date|பிறந்த[ \t]*(?:தேதி|நேரம்|இடம்|ஊர்)|பிறப்பு[ \t]*(?:தேதி|நேரம்|இடம்)|ஜனன[ \t]*(?:தேதி|நேரம்|இடம்))"
    r"[ \t]*[:：=\-–].*$", re.I | re.M)

# A sentence counts as giving birth details when it has a birth word AND a date, time, year or place cue.
_BIRTH_WORD = re.compile(
    r"\b(?:born|birth|dob|d\.o\.b)\b|பிறந்த|பிறந்தேன்|பிறப்பு|ஜனன|\b(?:piran|poran|pirand|porand|piranth|poranth)\w*",
    re.I)
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DETAIL = re.compile(
    r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b\d{4}-\d{1,2}-\d{1,2}\b|"            # 19-11-2003, 2003-11-19
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTHS + r"\b|\b" + _MONTHS + r"\s+\d{1,2}\b|"   # 19 Nov, Nov 19
    r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?|\b\d{1,2}\s*(?:am|pm)\b|"     # 10:30 AM, 6 pm
    r"(?<!\d)(?:19|20)\d{2}(?!\d)|"                                                # 2003, "2003la"
    r"\b(?:in|at)\s+(?-i:[A-Z][a-z]{2,})|ஊர்|ஊரில்|மணிக்கு|place\b|city\b|town\b",   # in Madurai, ஊர்
    # not "இடம்": "ஜனன ஜாதகத்தில் 7ம் இடம்" is chart talk, not a birth place
    re.I)
# A sentence ends at . ! ? । followed by a space (so "10.30" and "v2.6" are not ends), or at a line end.
_SENTENCE_END = re.compile(r"(?<=[.!?।])(\s+)")


# A sentence splits into clauses at "," and ";" (not inside "9,9").
_CLAUSE_END = re.compile(r"(?<=[,;])(\s+)")


def _hide_clauses(sentence: str) -> str:
    """Hides the clauses that give the birth details, keeps the rest of the sentence:
    "என் பிறந்த நேரம் 10.30, அதை வைத்து அடுத்த புத்தி எப்போ?" -> "[birth details hidden] அதை வைத்து அடுத்த புத்தி எப்போ?"
    (hiding the whole sentence left the model only "hi" to answer). A clause right after a hidden one is the
    rest of the birth details ("…porandhen, Madurai la") when it is short or has a date/place cue, and is not
    a question."""
    parts = _CLAUSE_END.split(sentence)   # [clause, space, clause, space, ...]
    if not any(_BIRTH_WORD.search(parts[i]) and _DETAIL.search(parts[i]) for i in range(0, len(parts), 2)):
        return sentence
    hidden_before = False
    for i in range(0, len(parts), 2):
        clause = parts[i]
        own = bool(_BIRTH_WORD.search(clause) and _DETAIL.search(clause))
        rest = (hidden_before and "?" not in clause
                and (bool(_DETAIL.search(clause)) or len(clause.split()) <= 3))
        hidden_before = own or rest
        if hidden_before:
            parts[i] = HIDDEN
    # "[hidden], [hidden]." -> one marker; a marker keeps no trailing comma.
    out = "".join(parts)
    out = re.sub(re.escape(HIDDEN) + r"(?:[,;]?\s*" + re.escape(HIDDEN) + r")+", HIDDEN, out)
    return re.sub(re.escape(HIDDEN) + r"\s*[,;]", HIDDEN, out)


def _hide_sentences(line: str) -> str:
    parts = _SENTENCE_END.split(line)   # [sentence, space, sentence, space, ...]
    for i in range(0, len(parts), 2):
        parts[i] = _hide_clauses(parts[i])
    return "".join(parts)


def strip_birth_text(text: str | None) -> str | None:
    """Drops a text chart's birth lines and hides any sentence that gives birth details (see the module doc)."""
    if not text:
        return text
    text = _LABEL_LINE.sub("", text)
    text = "\n".join(_hide_sentences(line) for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _norm_key(key: str) -> str:
    return re.sub(r"[-\s.]+", "_", str(key).strip().lower())


def _of_birth(value) -> bool:
    """A block the app marks as the birth day's: AstroTamil's panchangam comes as {"of": "the birth day, not today",
    "vaaram": ...} (24 Nov 2026). Its weekday and thithi are birth details, and read as today's they are wrong."""
    return isinstance(value, dict) and any(
        _norm_key(k) in ("of", "for") and isinstance(v, str) and _BIRTH_WORD.search(v) for k, v in value.items())


def strip_birth_json(value):
    """Drops birth keys, and blocks marked as the birth day's, at any depth; strings are cleaned like chat text.
    Lists and other values pass through."""
    if isinstance(value, dict):
        return {k: strip_birth_json(v) for k, v in value.items()
                if not _BIRTH_KEY.match(_norm_key(k)) and not _of_birth(v)}
    if isinstance(value, list):
        return [strip_birth_json(v) for v in value]
    if isinstance(value, str):
        return strip_birth_text(value)
    return value


def strip_app_data(app_data: str | None) -> str | None:
    """The app's data, as JSON or text, without birth details. JSON stays compact JSON."""
    if not app_data:
        return app_data
    try:
        parsed = json.loads(app_data)
    except (ValueError, TypeError):
        return strip_birth_text(app_data)
    if not isinstance(parsed, (dict, list)):
        return strip_birth_text(app_data)
    return json.dumps(strip_birth_json(parsed), ensure_ascii=False, separators=(",", ":"))
