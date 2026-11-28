"""The eval's client-format marks (code only, no AI calls) and the table that prints them."""
import asyncio
from types import SimpleNamespace

import pytest

from scripts import eval_companion as ev
from scripts.eval_companion import format_marks

ORDER = ["venaam", "வேண்டாம்", "kudathu"]
TANGLISH_Q = "enakku marriage eppo nadakkum"
TAMIL_Q = "எனக்கு திருமணம் எப்போது நடக்கும்"
GOOD = ["Sevvai 7th house la irukku, so konjam late ah nadakkalam.", "Rahu dasa mudinjathum clear aagum 🙏"]


def run(q=None, bubbles=GOOD, chips=(), button=None, tag="counted", question=TANGLISH_Q, order=ORDER):
    return format_marks(question, list(bubbles), list(chips), button, tag, q or {}, order)


def test_clean_reply_passes_all_seven():
    marks, problems = run()
    assert list(marks) == ["shape", "tag", "button", "chips", "soft", "labels", "language"]
    assert all(marks.values()) and problems == []


# shape
@pytest.mark.parametrize("bubbles, fragment", [
    (["a", "b", "c", "d"], "4 bubbles"),
    ([], "0 bubbles"),
    (["short", "x" * 412], "bubble 2 has 412 characters"),
])
def test_shape_fails(bubbles, fragment):
    marks, problems = run(bubbles=bubbles)
    assert marks["shape"] is False and any(fragment in p for p in problems)


def test_shape_edges_pass():
    assert run(bubbles=["x" * 300])[0]["shape"]
    assert run(bubbles=["a", "b", "c"])[0]["shape"]


# tag
def test_tag_must_match_when_expected():
    marks, problems = run({"expect": {"tag": "need_details"}}, tag="counted")
    assert marks["tag"] is False and "tag asked 'need_details' got 'counted'" in problems
    assert run({"expect": {"tag": "counted"}}, tag="counted")[0]["tag"]


def test_tag_passes_when_not_expected():
    assert run({"expect": {"chips": 0}}, tag="anything")[0]["tag"]
    assert run({}, tag="anything")[0]["tag"]


# button
def test_button_null_means_no_button():
    q = {"expect": {"button": None}}
    assert run(q, button=None)[0]["button"]
    marks, problems = run(q, button="porutham")
    assert marks["button"] is False and any("porutham" in p for p in problems)


def test_button_named_must_match():
    q = {"expect": {"button": "porutham"}}
    assert run(q, button="porutham")[0]["button"]
    assert run(q, button=None)[0]["button"] is False
    assert run(q, button="other")[0]["button"] is False


def test_button_absent_key_passes():
    assert run({"expect": {"tag": "counted"}}, button="porutham")[0]["button"]


# chips
def test_chip_count_must_match():
    q = {"expect": {"chips": 2}}
    assert run(q, chips=["Job eppo?", "Health eppadi?"])[0]["chips"]
    marks, problems = run(q, chips=[])
    assert marks["chips"] is False and any("2" in p and "0" in p for p in problems)
    assert run({"expect": {"chips": 0}}, chips=["Job eppo?", "Health eppadi?"])[0]["chips"] is False
    assert run({"expect": {"chips": 0}}, chips=[])[0]["chips"]


def test_chip_count_absent_passes_but_chips_still_checked():
    assert run({}, chips=["a b"])[0]["chips"]
    assert run({}, chips=["one two three four five six seven"])[0]["chips"] is False


def test_chip_seven_words_fails_six_passes():
    q = {"expect": {"chips": 2}}
    marks, problems = run(q, chips=["one two three four five six seven", "ok"])
    assert marks["chips"] is False and any("7 words" in p for p in problems)
    assert run(q, chips=["one two three four five six", "ok"])[0]["chips"]


def test_chip_equal_to_question_fails_ignoring_case_and_punctuation():
    q = {"expect": {"chips": 2}}
    marks, problems = run(q, chips=["  ENAKKU marriage, eppo nadakkum?! ", "Job eppo?"])
    assert marks["chips"] is False and any("question" in p for p in problems)


# soft
def test_order_word_fails_case_insensitive_substring():
    marks, problems = run(bubbles=["Intha velai VENAAM nu solren"])
    assert marks["soft"] is False and any("venaam" in p for p in problems)
    marks, _ = run(bubbles=["இது செய்ய வேண்டாம்"], question=TAMIL_Q)
    assert marks["soft"] is False


def test_safety_question_allows_order_words():
    marks, problems = run({"safety": True}, bubbles=["Please venaam, call the helpline"])
    assert marks["soft"] and problems == []


def test_no_order_words_given_passes():
    assert run(bubbles=["venaam"], order=None)[0]["soft"]


# labels
@pytest.mark.parametrize("leak", ["[used: 1]", "Mood: calm", "tone: soft", "TAG: counted", "button: x", "chips: 2",
                                  "my own reasoning says", "---", "see [1]", "a ] b"])
def test_label_leak_in_bubble_fails(leak):
    marks, problems = run(bubbles=[f"Reply text {leak}"])
    assert marks["labels"] is False and problems


def test_leaked_used_label_names_it():
    marks, problems = run(bubbles=["Sevvai la irukku [used: 1]"])
    assert marks["labels"] is False and any("used:" in p or "[" in p for p in problems)


def test_label_leak_in_chip_fails():
    assert run(chips=["Job eppo? [chips]", "x"])[0]["labels"] is False


# language
def test_tanglish_question_with_tamil_reply_fails():
    marks, problems = run(bubbles=["செவ்வாய் ஏழாம் இடத்தில் இருக்கிறது"])
    assert marks["language"] is False and any("language" in p.lower() or "script" in p.lower() for p in problems)


def test_tanglish_question_with_tanglish_reply_passes():
    assert run()[0]["language"]


def test_tanglish_question_small_tamil_share_passes():
    # one Tamil word among many Latin letters is under 20%
    assert run(bubbles=["Sevvai la irukku, athu oru problem illa, சனி paarunga for timing"])[0]["language"]


def test_tamil_question_with_tamil_reply_passes():
    assert run(bubbles=["செவ்வாய் ஏழாம் இடத்தில் இருக்கு", "ராகு தசை முடிஞ்சதும் சரியாகும் 🙏"], question=TAMIL_Q)[0]["language"]


def test_tamil_question_with_latin_reply_fails():
    assert run(question=TAMIL_Q)[0]["language"] is False


def test_emoji_and_digits_ignored_in_language():
    # no letters besides the emoji and digits: share is 0, so a Latin question passes
    assert run(bubbles=["🙏 2027 🙏"])[0]["language"]
    # a Tamil question stays Tamil when the reply is Tamil plus lots of digits/emoji
    assert run(bubbles=["சரி 2027 2028 2029 🙏🙏🙏"], question=TAMIL_Q)[0]["language"]


def test_mixed_question_is_unchecked():
    mixed = "enakku marriage eppo நடக்கும்"   # between 20% and 50% Tamil is not checked
    assert run(question=mixed, bubbles=["செவ்வாய் இருக்கு"])[0]["language"]
    assert run(question=mixed, bubbles=["Sevvai irukku"])[0]["language"]


# no_astrology
def test_no_astrology_key_only_when_asked():
    assert "no_astrology" not in run({})[0]
    marks, problems = run({"no_astrology": True}, bubbles=["Hi! Eppadi irukeenga?"])
    assert marks["no_astrology"] is True and problems == []


@pytest.mark.parametrize("text", ["உங்க ஜாதகத்தில் பார்த்தால்", "Rahu dasa nadakkuthu", "sani peyarchi", "குரு பலம்",
                                  "Jathagam paartha", "bhukti mudiyum", "இந்த தசை", "Guru sollrar", "SUKRAN", "கிரகம் சரியில்ல"])
def test_no_astrology_hits(text):
    marks, problems = run({"no_astrology": True}, bubbles=[text])
    assert marks["no_astrology"] is False and problems


def test_guru_inside_gurukulam_does_not_trip():
    marks, _ = run({"no_astrology": True}, bubbles=["Naan gurukulam la padichen"])
    assert marks["no_astrology"] is True


# the pure function never raises on odd input
def test_no_astrology_failure_does_not_fail_other_marks():
    marks, _ = run({"no_astrology": True}, bubbles=["Rahu dasa"])
    assert marks["tag"] and marks["shape"]


# ---- _table --------------------------------------------------------------------------------------------------------

OLD = {m: True for m in ev.MARKS}


def _row(question, marks, **extra):
    return {"config": "c1", "question": question, "run": 1, "reply": "x", "basis": "own", "seconds": 2.0,
            "cost": 0.01, "cost_jan_2027": 0.02, "marks": marks, **extra}


def test_table_prints_for_old_small_talk_and_format_only_rows(capsys):
    rows = [
        _row("wife", dict(OLD), claims=[], fact_errors=[], missing=[], style_problems=[]),
        _row("hello", {"no_prediction": True}, answer_model="m"),
        _row("greet", {}, format_marks={"shape": True, "tag": False, "button": True, "chips": True, "soft": True,
                                         "labels": True, "language": True},
             format_problems=["tag asked 'greeting' got 'counted'"]),
    ]
    ev._table(rows, {"c1": {}})
    out = capsys.readouterr().out
    assert "8/8 marks on 1 prediction answers" in out
    assert "NOT GRADED" not in out
    assert "client format marks: 6/7 on 1 answers" in out
    assert "tag      0/1" in out and "shape    1/1" in out
    assert "FORMAT      greet (run 1): tag asked 'greeting' got 'counted'" in out


def test_table_has_no_format_block_for_old_specs(capsys):
    ev._table([_row("wife", dict(OLD), claims=[])], {"c1": {}})
    assert "client format marks" not in capsys.readouterr().out


def test_table_still_lists_ungraded_prediction_rows(capsys):
    ev._table([_row("wife", {}, grader_error="GraderError")], {"c1": {}})
    assert "NOT GRADED (grader failed twice): 1" in capsys.readouterr().out


def test_table_counts_no_astrology_mark_when_present(capsys):
    fm = {"shape": True, "tag": True, "button": True, "chips": True, "soft": True, "labels": True, "language": True}
    rows = [_row("a", {}, format_marks=dict(fm), format_problems=[]),
            _row("b", {}, format_marks={**fm, "no_astrology": False}, format_problems=["reads the chart"])]
    ev._table(rows, {"c1": {}})
    out = capsys.readouterr().out
    assert "client format marks: 14/15 on 2 answers" in out
    assert "no_astrology 0/1" in out and "shape    2/2" in out


# ---- _one: format_only skips the grader ----------------------------------------------------------------------------

def _fake_engine(monkeypatch, bubbles, tag="greeting"):
    reply = SimpleNamespace(text="\n\n".join(bubbles), basis="own", bubbles=bubbles, chips=[], button=None, tag=tag)
    seen = {}

    async def fake(char, tenant_id, text, person, app_data, who, **kw):
        seen.update(kw)
        return reply
    monkeypatch.setattr(ev.engine, "_reply_without_memory", fake)
    monkeypatch.setattr(ev, "_reply_format", lambda spec: "FMT" if spec.get("reply_format") else None)

    async def no_grader(*a, **k):
        raise AssertionError("the grader must not be called")
    monkeypatch.setattr(ev, "_grade", no_grader)
    return seen


def _call_one(spec, q):
    return asyncio.run(ev._one(spec, {}, "c1", {}, q, 1, asyncio.Semaphore(1), ev.date(2026, 11, 21)))


def test_one_format_only_row_has_no_grade_and_only_format_marks(monkeypatch):
    seen = _fake_engine(monkeypatch, ["Vanakkam! Eppadi irukeenga?"])
    spec = {"tenant_id": "t", "app_data": "", "reply_format": {"buttons": []}, "order_words": ORDER}
    q = {"id": "greet", "text": "hi", "format_only": True, "expect": {"tag": "greeting", "chips": 0}}
    row = _call_one(spec, q)
    assert seen["reply_format"] == "FMT"
    assert row["marks"] == {} and "grader_error" not in row
    assert all(row["format_marks"].values()) and row["format_problems"] == []
    assert row["bubbles"] == ["Vanakkam! Eppadi irukeenga?"] and row["tag"] == "greeting" and row["button"] is None


def test_one_old_spec_passes_no_reply_format_and_adds_no_format_keys(monkeypatch):
    seen = _fake_engine(monkeypatch, ["hello"])
    row = _call_one({"tenant_id": "t", "app_data": ""}, {"id": "s", "text": "hi", "small_talk": True})
    assert "reply_format" not in seen and "format_marks" not in row and "bubbles" not in row
    assert "no_prediction" in row["marks"]


# --- scripts/eval_chips.py: the repeat-chip eval's own code (no AI) --------------------------------

def test_eval_chips_builds_25_cases_and_reads_the_graders_marks():
    from scripts import eval_chips
    cases = eval_chips.build_cases(27)
    assert len(cases) == 25 and cases == eval_chips.build_cases(27)             # same seed, same cases
    assert all(c["message"] not in c["asked"] and len(set(c["asked"])) == len(c["asked"]) for c in cases)
    assert {len(c["asked"]) for c in cases} == {5, 15, 29}
    marks = eval_chips.parse_marks('```json\n{"1": "same", "1_line": "Velai eppo?", "2": "NEW", "2_line": null}\n```')
    assert marks == {"1": "SAME", "2": "NEW", "1_line": "Velai eppo?", "2_line": None}
    assert eval_chips.parse_marks("no json") == {} and eval_chips.parse_marks('{"1": "MAYBE", "2": "NEW"}') == {}
