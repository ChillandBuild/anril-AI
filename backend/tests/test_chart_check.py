"""chart_check, live part: read AstroTamil's chart JSON and find wrong chart claims in a reply by code.

The chart is Prem's (prem-chart-astrotamil.json, trimmed): Magaram lagnam, Simmam rasi; Sani in Mithunam
at birth, in Meenam today. Every "ok"/"no claim" case below is a sentence shape that once gave a false alarm.
"""
import json

import pytest

from app.companion.chart_check import find_claims, find_wrong, parse_app_data, planet_name, redo_note, sign_name

CHART = {
    "overview": {"rasi": "Simmam (Leo)", "lagnam": "Magaram (Capricorn)"},
    "planets": [{"planet": p, "rasi": s} for p, s in [
        ("Sun", "Viruchigam"), ("Moon", "Simmam"), ("Mars", "Kumbam"), ("Mercury", "Viruchigam"),
        ("Jupiter", "Simmam"), ("Venus", "Viruchigam"), ("Saturn", "Mithunam"), ("Rahu", "Mesham"),
        ("Ketu", "Thulam")]],
    "navamsa": {"lagnam": "Magaram (Capricorn)", "Rahu": "Viruchigam", "Ketu": "Rishabam"},
    "dasa": {"now": {"dasa": "Rahu", "from": "23 Jun 2026", "to": "Jun 2044", "bhukti": "Rahu",
                     "bhukti_from": "Jun 2026", "bhukti_to": "Mar 2029"},
             "all": [["Mars", "2019", "2026"], ["Rahu", "2026", "2044"], ["Jupiter", "2044", "2060"]]},
    "gocharam": {"planets_today": [{"planet": p, "rasi": s} for p, s in [
        ("Sun", "Viruchigam"), ("Moon", "Mesham"), ("Jupiter", "Simmam"), ("Saturn", "Meenam")]],
        "month_readings": {"readings": [{"planet": "Jupiter", "moves_this_year": ["Kadagam -> Simmam, Jun 2026"]}]}},
}


@pytest.fixture(scope="module")
def chart():
    return parse_app_data(json.dumps(CHART))


def test_parse_json(chart):
    assert (chart.lagna, chart.rasi) == ("மகரம்", "சிம்மம்")
    assert chart.d1["சனி"] == "மிதுனம்" and chart.transit["சனி"] == "மீனம்"
    assert chart.d9 == {"ராகு": "விருச்சிகம்", "கேது": "ரிஷபம்"} and chart.d9_lagna == "மகரம்"
    assert chart.dasa.planet == "ராகு" and chart.next_dasa.planet == "குரு"
    assert chart.bhuktis[0].end.year == 2029
    assert chart.moves["குரு"] == {"கடகம்", "சிம்மம்"}


def test_not_a_chart_gives_no_claims():
    assert find_claims(parse_app_data('{"plan": "gold"}'), "Guru is in Rishabam") == []
    assert find_claims(parse_app_data(None), "Guru is in Rishabam") == []


@pytest.mark.parametrize("raw,name", [("Guruvin", "குரு"), ("Saniyal", "சனி"), ("Sevvai", "செவ்வாய்"),
                                      ("Kethu", "கேது"), ("சனிக்கிழமை", None), ("புத்திர", None),
                                      ("புதனின்", "புதன்")])
def test_planet_names(raw, name):
    assert planet_name(raw) == name


@pytest.mark.parametrize("raw,name", [("Simmathil", "சிம்மம்"), ("Magaram (Capricorn)", "மகரம்"),
                                      ("Kumbathil", "கும்பம்"), ("kumbabishekam", None), ("Leo", "சிம்மம்")])
def test_sign_names(raw, name):
    assert sign_name(raw) == name


@pytest.mark.parametrize("reply,expect", [
    ("Sani Mithunathil aatchi, so 6th house is strong.", "சனி is not ஆட்சி in மிதுனம்"),
    ("அதோட அதிபதி சனி, 6ம் இடத்துலயே ஆட்சி பலத்தோட இருக்கார்", "சனி is not ஆட்சி"),
    ("Guru is in Rishabam in your chart.", "குரு in ரிஷபம்"),
    ("Guru is in your 7th house.", "குரு in house 7"),
    ("Your rasi is Kanni.", "the rasi is சிம்மம், not கன்னி"),
    ("You are now running Guru dasa.", "the running dasa is ராகு தசை"),
    ("Guru dasa-la 2030-la kalyanam nadakkum.", "2030 is outside குரு 2044-2060"),
    ("Venus is your 7th lord.", "the lord of house 7"),
])
def test_wrong_claims_found(chart, reply, expect):
    wrong = find_wrong(chart, reply)
    assert wrong and expect in wrong[0], wrong


@pytest.mark.parametrize("reply", [
    "உங்கள் ஜாதகத்தில் சனி மிதுனத்தில் இருக்கிறார்.",                       # birth chart
    "உங்கள் சிம்ம ராசிக்கு சனி 8ல் இருப்பதால் அஷ்டம சனி.",                 # today, from rasi
    "Sun, Mercury and Venus are in Viruchigam, your 11th house.",          # a group of planets
    "Guru is in Simmam.",                                                  # birth and today
    "Rahu dasa runs until 2044.",
    "7ம் அதிபதி சந்திரன் 8ம் இடத்துல இருக்கார்",                            # lord of 7, sitting in 8
    "உங்க ஜாதகப்படி, 10ம் இடம் (ஜீவன ஸ்தானம்) துலாம் ராசி",                # a house's sign, not the rasi
    "உங்க ஜாதகத்துல 4ம் இடம், மேஷ ராசியில இருக்கு",
    "சூரியன் 10ம் அதிபதியுடன் தொடர்பு கொண்டிருப்பது நல்ல அறிகுறி",          # "with" the 10th lord
    "4ம் இடம் மற்றும் 5ம் இடத்தைப் (புத்திர/கல்வி ஸ்தானம்) பார்க்கணும்",     # புத்திர is not புதன்
    "சூரியன் 11-ம் இடமான லாப ஸ்தானத்தில் விருச்சிக ராசியில் இருக்கிறார், நீசம் பெறவில்லை",  # negated
    "If Sani is in the 7th house, marriage gets delayed.",                 # a general rule
    "ஜாதகத்துல சனி உச்சம் பெற்றிருந்தா, அந்த நபர் நல்ல பாதுகாப்பு உணர்வு கொண்டவர்",
    "சூரியன் நீசம் பெற்று பாப ஸ்தானத்தில் இருக்கும்போது கவனம் தேவை",
    "Sani Thulathil uchcham.",                                             # a true rule
    "Sevvai Chandranukku 7il irukkirar.",                                  # counted from another planet
    "Guru moved from Kadagam to Simmam this year.",
    "You said your lagnam is Kanni, but your chart shows Magaram lagnam.",
    "சனிக்கிழமை சிம்ம ராசிக்காரர்கள் கோவிலுக்கு செல்லலாம்.",
])
def test_no_false_alarm(chart, reply):
    assert find_wrong(chart, reply) == []


def test_redo_note_lists_the_wrong_facts():
    note = redo_note(["the rasi is சிம்மம், not கன்னி"])
    assert "the rasi is சிம்மம், not கன்னி" in note and "APP DATA" in note


@pytest.mark.parametrize("reply", [
    "அரசு வேலை பத்தி பார்க்க, சூரியன், 10ம் அதிபதி மற்றும் 6ம் இடத்தை கவனிக்கணும்",   # a list, not a claim
    "மகர லக்னத்துக்கு 10ம் வீட்டு அதிபதி சுக்கிரன்",                                  # 10th house lord = Venus: true
    "7ம் இடத்தில் சனி இருப்பது திருமணத்தை தாமதப்படுத்தும்",                            # a general rule
    "Rahu bhukti ends in Mar 2029, then Guru bhukti starts in 2029.",
])
def test_no_false_alarm_from_the_trap_eval(chart, reply):
    assert find_wrong(chart, reply) == []


def test_house_lord_named_next_to_the_lord_word_is_still_checked(chart):
    assert "the lord of house 10" in find_wrong(chart, "மகர லக்னத்துக்கு 10ம் வீட்டு அதிபதி சனி")[0]
    assert "the lord of house 7" in find_wrong(chart, "Venus is your 7th lord.")[0]
    assert "the lord of மகரம் is சனி" in find_wrong(chart, "மகரத்தின் அதிபதி சுக்கிரன்")[0]


def test_eval_year_only_bhukti_window_in_the_last_listed_year_is_not_wrong(chart):
    from app.companion.chart_check import check_claim
    claim = {"kind": "period", "level": "bhukti", "planet": "குரு", "when": "later", "window_start": "2029"}
    assert check_claim(chart, claim)[0] != "wrong"
    assert check_claim(chart, {**claim, "window_start": "2028"})[0] == "wrong"


@pytest.mark.parametrize("reply", [
    "உங்க ஜாதகத்துல லக்னம் மகரம், ராகு விருச்சிகம் மற்றும் கேது ரிஷப ராசியில இருக்காங்க",   # navamsa signs
    "உங்க ஜாதகப்படி லக்னம் கன்னி இல்லங்க, மகர லக்னம்",                                       # spoken "not"
    "உங்க ராசி சிம்மம், அதிபதி சூரியன் விருச்சிகத்துல 4ம் இடத்துல இருக்கார்",                  # lord of சிம்மம் only
])
def test_no_false_alarm_from_the_trap_eval_round_2(chart, reply):
    assert find_wrong(chart, reply) == []


def test_a_sign_the_count_starts_from_is_not_a_position(chart):
    assert find_wrong(chart, "சனி உங்க சிம்ம ராசிக்கு 8-ம் இடமான மீனத்துல இருக்கார்") == []
    assert find_wrong(chart, "Sani unga Simma rasikku 8il irukkar") == []
    assert find_wrong(chart, "சனி உங்க சிம்ம ராசிக்கு 5ம் இடத்துல இருக்கார்")   # 5th from anywhere: still caught
