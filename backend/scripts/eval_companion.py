"""Mark a character's answers on a fixed question set, per model and setting. Nothing is saved.

    cd backend && python -m scripts.eval_companion scripts/evals/jothidar_karthik.json --runs 2

Each question runs through the real reply path in its "Compare" form (engine._reply_without_memory: books,
app data, the WHO line; no person, no chat, no memory written), with the character's live row plus the
config's settings laid on top in memory, so settings whose columns are not live yet can still be tried.
Calls bill the character's business's own Gemini key, like the Playground. Token counts are read from the
same meter the app uses (token_meter.record_tokens still writes them).

Every prediction gets 6 marks:
  1 names    names the planet, the house and the dasa/bhukti it rests on       (grader)
  2 dates    no past date offered as a coming one, nothing beyond 3 years       (grader + year check)
  3 promise  no promise words ("kandippa"); "கண்டிப்பா தேவை" is advice, passes  (word list)
  4 window   any period is a named dasa/bhukti/transit tied to the topic        (grader)
  5 key      gets the question's key point (the answer key in the file)        (grader)
  6 facts    every chart fact it states is true: the grader lists the claims,
             scripts/eval_chart.py checks each against the chart (code, no AI)
The small-talk question is marked on "no prediction" and on which model answered it.
Output: one table per config (marks, average cost per answer, model used) and a JSON file of every reply.
"""
import argparse
import asyncio
import contextvars
import json
import re
import sys
import time
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
MARKS = ("names", "dates", "promise", "window", "key", "facts")
# A promise word followed within a few words by one of these is advice ("கடின உழைப்பு கண்டிப்பா தேவை"), not a promise.
ADVICE_WORDS = ("தேவை", "பண்ணுங்க", "செய்யுங்க", "பண்ணனும்", "செய்யணும்")

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


def _promise_hit(text: str, words) -> bool:
    """A promise word in the reply, unless the next few words make it advice (ADVICE_WORDS)."""
    low = text.lower()
    for w in words:
        for m in re.finditer(re.escape(w.lower()), low):
            after = low[m.end():m.end() + 30]
            if not any(a in after for a in ADVICE_WORDS):
                return True
    return False


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
        with playground.use(ov):
            reply = await engine._reply_without_memory(char, spec["tenant_id"], q["text"], None, spec["app_data"], who)
        seconds = time.monotonic() - started
        answer_calls = [c for c in calls if c[0] == engine.LLM_PURPOSE]
        row = {"config": config_name, "question": q["id"], "run": run_no, "reply": reply.text, "basis": reply.basis,
               "working": ov.working, "seconds": round(seconds, 1),
               "answer_model": answer_calls[-1][1] if answer_calls else None,
               "cost": _cost(calls, PRICES), "cost_jan_2027": _cost(calls, PRICES_JAN_2027),
               "tokens": [{"purpose": c[0], "model": c[1], "in": c[2], "out": c[3]} for c in calls],
               "trace": ov.trace, "problem": ov.problem}
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
        if graded is None:
            row["marks"] = {}
            return row
        promise = _promise_hit(reply.text, spec.get("promise_words", []))
        checks = eval_chart.check_claims(eval_chart.parse_chart(spec["app_data"]), graded["claims"])
        wrong = [why for verdict, why in checks if verdict == "wrong"]
        row["marks"] = {"names": graded["names"], "dates": graded["dates"] and not _past_year(reply.text, today),
                        "promise": not promise, "window": graded["window"], "key": graded["key"], "facts": not wrong}
        row["grader_note"] = graded["note"]
        row["claims"] = [{**cl, "verdict": v, "why": why} for cl, (v, why) in zip(graded["claims"], checks)]
        row["fact_errors"] = wrong
        return row


def _table(rows, configs):
    print()
    for name in configs:
        mine = [r for r in rows if r["config"] == name]
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
    _table(rows, configs)
    print(f"\nEvery reply: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
