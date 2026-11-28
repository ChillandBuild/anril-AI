"""Does a follow-up chip repeat a question the person already asked? Marks the chips shown (chip_repeats.py).
Nothing is saved.

    cd backend && .venv/bin/python -m scripts.eval_chips                    # 25 cases, up to 50 chips
    cd backend && .venv/bin/python -m scripts.eval_chips --seed 28 --runs 2  # other cases, each asked twice

Each case is one person: questions they asked this week (5, 15 or 29, in Tanglish, Tamil or English) and the
message they just sent. The message goes through the real reply (engine._reply_without_memory) with those
questions (ReplyFormat.with_asked), as live: the prompt lists them and code drops the chip ideas that repeat
one by meaning. The chips that come back are the ones the app would show.
A grader model then marks each chip shown against the case's questions:
  SAME    asks the same thing as a line, in any wording, language or script ("will it be delayed" = when) -> the bug
  DEEPER  same subject as a line, but a different ask                                                   -> allowed
  NEW     a subject not in the list                                                                     -> allowed
A chip that is a label and no question ("job when") counts as a repeat too: the label version showed 16 in 42.
Pass bar: at most 5 bad in 100 chips shown. The reply's own chips (27 Nov 2026): 27 in 100; labels: 21 in 100.
--out keeps every case's chip ideas and what code did with them, for tuning chip_repeats' lines.
Calls bill the character's business's own Gemini key; the cost printed is read from the token meter.
Most questions are real ones from Jothidar AI's live chats (Nov 2026); the ones under "written for the test"
fill the Tamil and English lists up to 30.
"""
import argparse
import asyncio
import contextvars
import json
import random
import re
import sys
import time
from pathlib import Path

from app.companion import chip_repeats, engine, playground, store
from app.companion.prompt import who_block
from app.companion.reply_format import ReplyFormat
from scripts import eval_companion as base

SPEC = "scripts/evals/jothidar_client_doc.json"   # tenant, character and the app's reply_format
PASS_PER_100 = 5

POOLS = {
    "tanglish": [   # real, except the last 8 (the Karthik question set)
        "2027 enaku epdi irkum sollunga", "apa nan when overseas try pannatum ?", "bike ku enna number vangalam?",
        "Change of place of work irkuma", "En company epo hike kudupaanga", "enaku when job kidaikum?",
        "Endha temple poradhu", "Enga company nala develop aaguma", "Health condition epdi irkum",
        "innaiku enaaku yepadi irukum?", "interview enaku next week iruku...which day pona correct ah irukum?",
        "interview ku nan enna colour shirt wear pannitu pogatum?", "kalyanam eppo",
        "naan IT la work panren, salary increase eppo varum?", "nan bike vangalama ipa ?",
        "Nan next ena pana correct ah irkum business or current office job", "Nan next house epo vanguven.",
        "Ok en husband health pathi solria", "overseas job kidaikuma ?", "Parigaaram edaadbu iruka",
        "tomorrow enaku yepadi irukum?", "when enaku loan issues ellam close aagum?",
        "Kuzhandhai bhaakkiyam eppadi irukku?", "Love marriage-a arranged marriage-a?",
        "Panam serum vaaippu eppadi irukku?", "Higher studies abroad pannalama?", "Velinaattula settle aaga mudiyuma?",
        "Kadan prachanai theeruma?", "Sontha veedu eppo vaangalam?", "Udambu nalla irukkuma? Ethavathu kavanikkanuma?",
    ],
    "tamil": [      # the first 18 are real; the last 12 are written for the test
        "இப்போ என்ன தசை நடக்குது?", "இன்னைக்கு என்ன திதி?", "எந்த தேதில கல்யாணம் நடக்கும்?",
        "எனக்கு காலசர்ப்ப தோஷம் இருக்கா?", "எனக்கு செவ்வாய் தோஷம் இருக்கா?", "என் future எப்படி இருக்கு?",
        "என் அக்கா ஜாதகம் எப்படி?", "என் லக்னம் கன்னி தானே?", "என் ஜாதகத்துல ஏதாவது தோஷம் இருக்கா?",
        "கல்யாணம் எப்போ நடக்கும்?", "குரு தசை எப்போது தொடங்கும்?", "சரி, இப்போ job மாறலாமா?",
        "சனி தசை எப்படி இருக்கும்?", "திருமண வாழ்க்கை எப்படி இருக்கும்?", "நவாம்சப்படி என் கல்யாண வாழ்க்கை எப்படி?",
        "பதவி உயர்வு எப்போது?", "புதிய வீடு எப்போது?", "வேலை வாய்ப்பு எப்படி இருக்கும்?",
        "உடல்நலம் எப்படி இருக்கும்?", "பண வரவு எப்போது கூடும்?", "வெளிநாடு போக வாய்ப்பு இருக்கா?",
        "குழந்தை பாக்கியம் எப்போது?", "கடன் எப்போது தீரும்?", "சொந்த தொழில் தொடங்கலாமா?", "மேல் படிப்பு படிக்கலாமா?",
        "வாகனம் வாங்க நல்ல நேரம் எப்போது?", "காதல் திருமணம் நடக்குமா?", "அரசு வேலை கிடைக்குமா?",
        "என்ன பரிகாரம் செய்யணும்?", "எந்த கோவிலுக்கு போகணும்?",
    ],
    "english": [    # the first 7 are real; the rest are written for the test
        "Hi I planned to do my ME. Is this good time for that?", "is this a good day for me", "Ok tell me about myself",
        "What is my lagnam and rasi?", "When will I get married?", "Will I get a government job?", "Will I go abroad?",
        "How is my health this year?", "When will I buy a house?", "Will my loan be cleared soon?",
        "Should I start a business?", "When will I get a promotion?", "How will my married life be?",
        "Do I have any dosham?", "Which dasa is running now?", "When will I have a child?",
        "Is this a good time to change jobs?", "Will I get a salary hike?", "What remedy should I do?",
        "Is a love marriage possible for me?", "How will 2027 be for me?", "When will my money problems end?",
        "Can I buy a vehicle now?", "Which temple should I visit?", "How is my career overall?",
        "Will I settle abroad?", "How is my father's health?", "When does my Guru dasa start?",
        "Is tomorrow a good day for an interview?", "Which colour is lucky for me?",
    ],
}
# (script, how many earlier questions): 25 cases = 50 chips
CASES = ([("tanglish", n) for n in (5, 15, 29, 5, 15, 29, 5, 15, 29, 15)]
         + [("tamil", n) for n in (5, 15, 29, 5, 15, 29, 5, 15)]
         + [("english", n) for n in (5, 15, 29, 5, 15, 29, 15)])

GRADER = (
    "A chat app shows 2 follow-up questions (chips) under an astrologer's reply. A chip must not repeat a question "
    "the person already asked.\n\nALREADY ASKED (the last one is the message they just sent):\n{asked}\n\n"
    "CHIPS:\n1. {one}\n2. {two}\n\n"
    "Mark each chip against ALREADY ASKED, comparing meaning across wording, language and script:\n"
    "SAME = it asks the same thing as a line there: the same subject and the same kind of ask (both ask WHEN "
    "marriage happens; 'will my marriage be delayed' is also asking when).\nDEEPER = same subject as a line, but "
    "a different ask (the line asks when marriage happens, the chip asks love or arranged).\n"
    "NEW = its subject is in no line.\n"
    'Answer with JSON only: {{"1": "SAME|DEEPER|NEW", "1_line": "the line it repeats or null", '
    '"2": "SAME|DEEPER|NEW", "2_line": "the line it repeats or null"}}')


def build_cases(seed: int) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for script, count in CASES:
        picked = rng.sample(POOLS[script], count + 1)
        cases.append({"script": script, "asked": picked[:-1], "message": picked[-1]})
    return cases


def parse_marks(raw: str) -> dict:
    """'```json {"1": "same", ...}```' -> {"1": "SAME", "1_line": ..., "2": ..., "2_line": ...}; unreadable -> {}."""
    try:
        got = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except (ValueError, TypeError):
        return {}
    marks = {k: str(got.get(k) or "").upper() for k in ("1", "2")}
    if not all(m in ("SAME", "DEEPER", "NEW") for m in marks.values()):
        return {}
    return {**marks, "1_line": got.get("1_line"), "2_line": got.get("2_line")}


LABEL_ONLY = re.compile(r"^[a-z]+ (when|whether|how|which|what|advice|why)$", re.IGNORECASE)

# the ideas the model wrote and the chips code kept, per question (a context variable: parallel questions never mix)
_SEEN: contextvars.ContextVar[dict | None] = contextvars.ContextVar("chips_seen", default=None)


def _watch_fresh():
    fresh = chip_repeats.fresh

    async def watched(tenant_id, ideas, asked):
        out = await fresh(tenant_id, ideas, asked)
        seen = _SEEN.get()
        if seen is not None:
            seen.update(ideas=list(ideas), checked_against=len(asked))
        return out
    chip_repeats.fresh = watched


async def _ask(case: dict, companion: dict, spec: dict, fmt: ReplyFormat, sem: asyncio.Semaphore) -> dict:
    async with sem:
        seen = {"ideas": [], "checked_against": 0}
        _SEEN.set(seen)
        started = time.monotonic()
        with playground.use(playground.Overrides()):
            r = await engine._reply_without_memory(
                companion, spec["tenant_id"], case["message"], None, spec["app_data"],
                who_block(spec.get("user_name"), spec.get("profile_name")),
                reply_format=fmt.with_asked(case["asked"]))
        return {**seen, "chips": r.chips or [], "ms": int((time.monotonic() - started) * 1000)}


async def _grade(case: dict, chips: list[str], tenant_id: str, sem: asyncio.Semaphore) -> dict:
    asked = case["asked"] + [case["message"]]
    async with sem:
        try:
            raw = await engine.ai_reply._llm_chat(
                [{"role": "user", "content": GRADER.format(asked="\n".join(f"- {a}" for a in asked),
                                                           one=chips[0], two=chips[1])}],
                max_tokens=1000, tenant_id=tenant_id, purpose="eval_grader", temperature=0.0, model=base.GRADER_MODEL)
        except Exception as exc:   # one failed grader call must not lose the whole run
            print(f"grader failed ({type(exc).__name__}): case left unmarked")
            return {}
    return parse_marks(raw)


def _bad(row: dict, n: str) -> bool:
    return row["marks"][n] == "SAME" or bool(LABEL_ONLY.match(row["chips"][int(n) - 1]))


def report(rows: list[dict], calls: list) -> int:
    marked = [r for r in rows if r["marks"]]
    chips = [(r, n) for r in marked for n in ("1", "2")]
    bad = [(r, n) for r, n in chips if _bad(r, n)]
    print(f"\n{len(rows)} cases: {sum(bool(r['chips']) for r in rows)} show chips, {len(chips)} chips marked")
    for script in POOLS:
        for size in (5, 15, 29):
            mine = [(r, n) for r, n in chips if r["script"] == script and len(r["asked"]) == size]
            if mine:
                print(f"  {script:9} {size:>2} asked: {sum(_bad(r, n) for r, n in mine)} bad in {len(mine)} chips")
    for mark in ("SAME", "DEEPER", "NEW"):
        print(f"  {mark:7} {sum(r['marks'][n] == mark for r, n in chips)}")
    print(f"  LABEL   {sum(bool(LABEL_ONLY.match(r['chips'][int(n) - 1])) for r, n in chips)}")
    for r, n in bad:
        print(f"  REPEAT  chip '{r['chips'][int(n) - 1]}'  =  asked '{r['marks'].get(n + '_line')}'")
    dropped = sum(len(r["ideas"]) for r in rows) - sum(len(r["chips"]) for r in rows)
    print(f"  ideas written {sum(len(r['ideas']) for r in rows)}, not shown {dropped}")
    for r in rows:
        if not r["chips"]:
            print(f"  NO CHIPS  ({r['script']}, {len(r['asked'])} asked) message: {r['message']}  ideas: {r['ideas']}")
    replies = [c for c in calls if c[0] == engine.LLM_PURPOSE]
    grader = [c for c in calls if c[0] == "eval_grader"]
    print(f"  reply timing: median {sorted(r['ms'] for r in rows)[len(rows) // 2]} ms")
    print(f"  cost: replies ${base._cost(replies, base.PRICES):.4f} for {len(replies)} calls, "
          f"grader ${base._cost(grader, base.PRICES):.4f} for {len(grader)} (the eval only; embeddings not metered)")
    rate = 100 * len(bad) / max(len(chips), 1)
    passed = bool(chips) and rate <= PASS_PER_100
    print(f"bad chips shown: {len(bad)} of {len(chips)} = {rate:.1f} per 100 (bar: {PASS_PER_100}) -> "
          f"{'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=27)
    parser.add_argument("--runs", type=int, default=1, help="ask every case this many times")
    parser.add_argument("--out", default=None)
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()
    spec = json.loads(Path(SPEC).read_text(encoding="utf-8"))
    companion = await store.get_companion(spec["tenant_id"], spec["companion_id"])
    if not companion:
        print("character not found")
        return 1
    fmt = ReplyFormat.model_validate(spec["reply_format"])
    base._meter()
    calls: list = []
    base._CALLS.set(calls)
    _watch_fresh()
    sem = asyncio.Semaphore(args.parallel)
    cases = build_cases(args.seed) * args.runs
    print(f"{len(cases)} messages, each with the questions asked before it "
          f"({companion['name']} on {engine.character_model(companion)})")

    async def case_row(case: dict) -> dict:
        got = await _ask(case, companion, spec, fmt, sem)
        marks = await _grade(case, got["chips"], spec["tenant_id"], sem) if got["chips"] else {}
        return {**case, **got, "marks": marks}
    rows = await asyncio.gather(*[case_row(c) for c in cases])
    if args.out:
        Path(args.out).write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report(rows, calls)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
