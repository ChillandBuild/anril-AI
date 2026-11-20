"""The eval's chart-fact checker, promise word check and grader parsing. No AI calls."""
import json
from pathlib import Path

import pytest

from scripts import eval_chart
from scripts.eval_chart import check_claim, parse_chart

SPEC = Path(__file__).resolve().parents[1] / "scripts" / "evals" / "jothidar_karthik.json"


@pytest.fixture(scope="module")
def chart():
    return parse_chart(json.loads(SPEC.read_text(encoding="utf-8"))["app_data"])


def test_parse_karthik(chart):
    assert chart.lagna == "ரிஷபம்" and chart.rasi == "மேஷம்"
    assert chart.d1["புதன்"] == "ரிஷபம்" and chart.d1["குரு"] == "துலாம்" and chart.d1["கேது"] == "மேஷம்"
    assert chart.d9["சுக்கிரன்"] == "மீனம்" and chart.transit["சனி"] == "மீனம்"
    assert chart.dasa.planet == "செவ்வாய்" and chart.dasa.end.year == 2029
    assert [b.planet for b in chart.bhuktis] == ["புதன்", "கேது", "சுக்கிரன்", "சூரியன்", "சந்திரன்"]
    assert chart.next_dasa.planet == "ராகு"


# The three rows from the plan: yesterday's two real mistakes, and one true claim.
def test_mercury_not_own_sign_in_taurus(chart):
    verdict, why = check_claim(chart, {"kind": "dignity", "planet": "புதன்", "dignity": "ஆட்சி", "chart": "D1"})
    assert verdict == "wrong" and "ரிஷபம்" in why


def test_running_dasa_is_mars_not_venus(chart):
    verdict, why = check_claim(chart, {"kind": "period", "level": "dasa", "planet": "சுக்கிரன்", "when": "current"})
    assert verdict == "wrong" and "செவ்வாய்" in why
    assert check_claim(chart, {"kind": "lord", "house": 6, "planet": "சுக்கிரன்"})[0] == "ok"


def test_mars_own_sign_in_12th(chart):
    assert check_claim(chart, {"kind": "position", "planet": "செவ்வாய்", "house": 12, "chart": "D1"})[0] == "ok"
    assert check_claim(chart, {"kind": "dignity", "planet": "செவ்வாய்", "dignity": "ஆட்சி"})[0] == "ok"
    assert check_claim(chart, {"kind": "house_sign", "house": 12, "sign": "மேஷம்"})[0] == "ok"


@pytest.mark.parametrize("claim, verdict", [
    ({"kind": "house_sign", "house": 7, "sign": "கும்பம்"}, "wrong"),                     # 7 is விருச்சிகம்
    ({"kind": "lord", "house": 4, "planet": "Sun"}, "ok"),                                # English name
    ({"kind": "position", "planet": "சனி", "house": 12, "chart": "transit", "from": "rasi"}, "ok"),
    ({"kind": "position", "planet": "சனி", "house": 12, "chart": "transit"}, "wrong"),   # from லக்னம் it is 11
    ({"kind": "position", "planet": "குரு", "sign": "கடகம்", "chart": "D1"}, "wrong"),
    ({"kind": "dignity", "planet": "ராகு", "dignity": "உச்சம்"}, "unchecked"),            # texts disagree
    ({"kind": "period", "level": "bhukti", "planet": "சுக்கிரன்", "start": "2027-05", "end": "2028-07"}, "ok"),
    ({"kind": "period", "level": "bhukti", "planet": "சுக்கிரன்", "start": "2026-06"}, "wrong"),
    ({"kind": "period", "level": "bhukti", "planet": "குரு", "start": "2027-01"}, "wrong"),  # no குரு புத்தி listed
    ({"kind": "period", "level": "dasa", "planet": "செவ்வாய்", "when": "current", "end": "2029-06"}, "ok"),
    ({"kind": "period", "level": "dasa", "planet": "குரு", "when": "next"}, "wrong"),       # next is ராகு
    ({"kind": "mood"}, "unchecked"),
    # a predicted window inside the period is fine; outside it is wrong (yesterday's marriage false alarm)
    ({"kind": "period", "level": "bhukti", "planet": "சுக்கிரன்", "window_start": "2027-06", "window_end": "2028-02"}, "ok"),
    ({"kind": "period", "level": "bhukti", "planet": "சுக்கிரன்", "window_start": "2028-09"}, "wrong"),
    # only a year said: "சூரியன் புத்தி 2028-ல" (the property false alarm)
    ({"kind": "period", "level": "bhukti", "planet": "சூரியன்", "start": "2028"}, "ok"),
    ({"kind": "period", "level": "bhukti", "planet": "சூரியன்", "start": "2027"}, "wrong"),
    ({"kind": "period", "level": "dasa", "planet": "செவ்வாய்", "when": "current", "end": "2027"}, "wrong"),
])
def test_claims(chart, claim, verdict):
    assert check_claim(chart, claim)[0] == verdict


def test_names_with_case_endings():
    assert eval_chart.planet_name("சுக்கிரனின்") == "சுக்கிரன்"
    assert eval_chart.sign_name("ரிஷபத்தில்") == "ரிஷபம்"
    assert eval_chart.planet_name("சந்தோஷம்") is None   # short names (சனி) never match loosely


# Promise words and grader parsing live in the eval script; it imports app modules, so import lazily.
@pytest.fixture(scope="module")
def ev():
    from scripts import eval_companion
    return eval_companion


WORDS = ["கண்டிப்பா", "நிச்சயம்"]


def test_promise_advice_passes(ev):
    assert not ev._promise_hit("கடின உழைப்பு கண்டிப்பா தேவைப்படும்.", WORDS)


def test_promise_prediction_fails(ev):
    assert ev._promise_hit("கவலைப்படாதீங்க, சொந்த வீடு வாங்குற யோகம் கார்த்திக்கு நிச்சயம் இருக்கு.", WORDS)


@pytest.mark.parametrize("raw", ["", "I think the reply is fine", '{"names": true, "note": "cut off"}', "{bad json"])
def test_unreadable_grader_raises(ev, raw):
    with pytest.raises(ev.GraderError):
        ev._parse_grade(raw)


def test_grader_parsed(ev):
    raw = 'ok ```json\n{"names": true, "dates": false, "window": true, "key": true, "note": "x", "claims": [{"kind": "lord"}]}\n```'
    got = ev._parse_grade(raw)
    assert got["names"] and not got["dates"] and got["claims"] == [{"kind": "lord"}]
