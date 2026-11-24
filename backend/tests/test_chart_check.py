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


def test_a_wrong_lagnam_with_its_lord_and_a_rasi_in_the_next_sentence_are_caught(chart):
    # live Playground reply (23 Nov): the model read a chart pasted in the chat history, not APP DATA
    reply = ("உங்கள் ஜாதகத்தில் லக்னம் மேஷம், அதன் அதிபதி செவ்வாய். "
             "ராசி ரிஷபம், அதன் அதிபதி சுக்கிரன்.")
    wrong = find_wrong(chart, reply)
    assert "the lagnam is மகரம், not மேஷம்" in wrong and "the rasi is சிம்மம், not ரிஷபம்" in wrong
    assert find_wrong(chart, "உங்க ராசி சிம்மம், அதிபதி சூரியன் விருச்சிகத்துல இருக்கார்") == []


@pytest.mark.parametrize("reply,expect", [
    ("உங்க ஜாதகப்படி லக்னாதிபதி செவ்வாய், ராசிநாதன் சுக்கிரன்.", 2),   # live, 23 Nov
    ("Your lagna lord is Mars.", 1),
    ("Unga rasi athipathi Sukran.", 1),
    ("உங்க லக்னாதிபதி சனி, ராசிநாதன் சூரியன்.", 0),
    ("பொதுவாக லக்னாதிபதி பலமா இருக்கணும்.", 0),
    ("If the lagna lord is Mars, you are bold.", 0),
    ("7ம் இடமான கடக ராசிக்கு அதிபதி சந்திரன், அவர் 8ம் இடமான சிம்மத்துல இருக்கார்.", 0),   # that sign's lord
])
def test_lagna_lord_and_rasi_lord_claims(chart, reply, expect):
    assert len(find_wrong(chart, reply)) == expect, find_wrong(chart, reply)


# --- navamsa houses (24 Nov). Navamsa signs below are test values in AstroTamil's shape, not Prem's real D9.
NAV = {"lagnam": "Magaram", "Sun": "Mesham", "Moon": "Thulam", "Mars": "Kadagam", "Mercury": "Mithunam",
       "Jupiter": "Dhanusu", "Venus": "Meenam", "Saturn": "Kumbam", "Rahu": "Viruchigam", "Ketu": "Rishabam"}


def _with_navamsa(nav):
    return parse_app_data(json.dumps(dict(CHART, navamsa=nav)))


def test_a_lagnam_row_in_a_navamsa_list_is_the_navamsa_lagnam():
    """An app may send the navamsa as rows, lagnam first. Before: the row was dropped and Jothidar was told
    the navamsa lagnam is missing (live check 24 Nov: 1 of 2 marriage answers said so)."""
    from app.companion.prompt import CHART_RULES, chart_rules
    for first in ({"planet": "Lagnam", "rasi": "Magaram"}, {"name": "lagna", "sign": "மகரம்"},
                  {"planet": "Ascendant", "rasi": "Capricorn"}):
        rows = [first] + [{"planet": p, "rasi": s} for p, s in NAV.items() if p != "lagnam"]
        c = _with_navamsa(rows)
        assert c.d9_lagna == "மகரம்" and len(c.d9) == 9
        rules = chart_rules(json.dumps(dict(CHART, navamsa=rows)))
        assert rules.startswith(CHART_RULES) and "navamsa lagnam மகரம்" in rules and "no navamsa lagnam" not in rules


@pytest.mark.parametrize("reply", [
    # live 24 Nov, run 1: Sani is in Kumbam in the navamsa = the 2nd from a Magaram navamsa lagnam, not the 7th
    "உங்க நவாம்சத்துல 7ம் இடமான களத்திர ஸ்தானத்தை பார்த்தா, அங்க சனி பகவான் கும்ப ராசியில இருக்கார்.",
    "In your navamsa, Saturn sits in the 7th house.",
    "In your navamsa the 7th house is Capricorn.",
    "Unga navamsa-la 7th lord Sukkiran.",
])
def test_a_wrong_navamsa_house_is_caught(reply):
    assert find_wrong(_with_navamsa(NAV), reply)


@pytest.mark.parametrize("reply", [
    "உங்க நவாம்சத்துல லக்னம் மகரம், 7ம் இடம் கடகம்.",
    "உங்க நவாம்சத்துல 7ம் இடம் கடகம், அதோட அதிபதி சந்திரன் துலாத்துல இருக்கார்.",
    "உங்க நவாம்சத்துல சனி 2ம் இடத்துல இருக்கார்.",
    "In your navamsa, Venus is in the 3rd house, exalted in Meenam.",
    "நவாம்சத்துல சுக்கிரன் உச்சம் பெற்று மீனத்துல இருக்கறது ரொம்ப நல்ல விஷயம்.",
])
def test_a_right_navamsa_house_is_not_flagged(reply):
    assert find_wrong(_with_navamsa(NAV), reply) == []


def test_without_a_navamsa_lagnam_any_navamsa_house_is_wrong_but_signs_are_fine():
    c = _with_navamsa({p: s for p, s in NAV.items() if p != "lagnam"})
    assert find_wrong(c, "In your navamsa the 7th house is Capricorn.")
    assert find_wrong(c, "உங்க நவாம்சத்துல சனி 2ம் இடத்துல இருக்கார்.")
    assert find_wrong(c, "நவாம்சத்துல சுக்கிரன் மீனத்துல இருக்கார்.") == []


@pytest.mark.parametrize("reply", [
    # live 24 Nov, AstroTamil's real chart: the navamsa word in one clause, "7ம் இடத்துல கேது" in the next.
    # Checked as the birth chart (where Ketu IS in the 7th there), so it passed; in the navamsa Ketu is the 4th.
    # Here: birth Ketu is the 10th, navamsa Ketu (Rishabam) the 5th from a Magaram navamsa lagnam.
    "உங்க நவாம்சத்துல லக்னம் மகரமா இருக்கு, அதோட அதிபதி சனி 2ம் இடமான கும்பத்துல இருக்கார். "
    "இது ஒரு நல்ல அமைப்புதான், ஆனா 10ம் இடத்துல கேது இருக்கிறதுனால கருத்து வேறுபாடுகள் வரலாம்.",
    "உங்க நவாம்சத்துல லக்னம் மகரம். கேது 10ம் இடத்துல இருக்கார்.",
    "In your navamsa, Venus is exalted in Meenam. Ketu sits in the 10th house.",
    "நவாம்சக் கட்டத்தைப் பார்ப்போம். கேது 10ம் இடத்துல இருக்கார்.",
    # live 24 Nov: the next paragraph opened "ஆனா, 7ம் இடத்துல கேது..." -- still the navamsa
    "நவாம்சத்துல சனி 2ம் இடத்துல இருக்கார்.\n\nஆனா, 10ம் இடத்துல கேது இருக்கறது ஒரு சவால்.",
    # live 24 Nov: "being in" (இருப்பது) was read as a general rule, though the clause names the navamsa
    "இருப்பினும், நவாம்ச 10ம் இடத்தில் கேது இருப்பது சில நேரங்களில் கருத்து வேறுபாடுகளைத் தரலாம்.",
    "உங்க நவாம்சத்துல லக்னம் மகரம். ஆனா 10ம் இடத்துல கேது இருப்பது சவால்.",
])
def test_a_navamsa_house_in_the_sentence_after_the_navamsa_word_is_checked_in_the_navamsa(reply):
    assert find_wrong(_with_navamsa(NAV), reply)


@pytest.mark.parametrize("reply", [
    "உங்க நவாம்சத்துல லக்னம் மகரம். கேது 5ம் இடத்துல இருக்கார்.",                          # right, carried
    "நவாம்சத்துல சனி 2ம் இடத்துல. உங்க ராசி கட்டத்துல கேது 10ம் இடத்துல இருக்கார்.",      # back to the birth chart
    "In your navamsa, Saturn is in the 2nd house. In your birth chart, Ketu is in the 10th house.",
    "நவாம்சத்துல சனி 2ம் இடத்துல. இப்போ ராகு தசை நடக்குது, ராகு 4ம் இடத்துல இருக்கார்.",  # the dasa is birth chart
])
def test_the_navamsa_topic_ends_at_the_birth_chart_or_the_dasa(reply):
    assert find_wrong(_with_navamsa(NAV), reply) == []


def test_being_in_is_still_a_general_rule_when_it_is_about_no_one():
    assert find_wrong(_with_navamsa(NAV), "7ம் இடத்தில் கேது இருப்பது திருமணத்தை தாமதப்படுத்தும்") == []
    assert find_wrong(_with_navamsa(NAV), "உங்க ஜாதகத்துல 7ம் இடத்தில் கேது இருப்பது தாமதம் தரும்")   # yours: Ketu is 10th


def test_a_dosham_or_the_birth_lagnam_ends_the_navamsa_topic():
    """Live 24 Nov, dosham with "cancelled ... not in navamsa": the reply said the navamsa, then went back to the
    lagnam reason; that was read as a navamsa house, redone, and 2 of 9 answers became the handoff line."""
    c = _with_navamsa(dict(NAV, lagnam="Rishabam"))      # navamsa lagnam differs from the birth one (Magaram)
    assert find_wrong(c, "நவாம்சத்துல அந்த அமைப்பு இல்ல. மகர லக்னத்துக்கு 2ம் இடத்துல செவ்வாய் இருக்கார்.") == []
    assert find_wrong(c, "நவாம்சத்துல செவ்வாய் வேற இடத்துல இருக்கார். செவ்வாய் 2ம் இடத்துல இருக்கிறது தோஷம்.") == []
    assert find_wrong(c, "In the navamsa it is not there. Mars in the 2nd house gives mangal dosha.") == []
    assert find_wrong(c, "நவாம்ச லக்னம் ரிஷபம். செவ்வாய் 2ம் இடத்துல இருக்கார்.")   # still the navamsa: Mars is the 3rd


def test_the_chart_rules_say_a_cancelled_dosham_does_not_apply():
    from app.companion.prompt import CHART_RULES
    assert '"cancelled" = it was found in the chart but is cancelled, so it does not' in CHART_RULES
    assert "never add a reason" in CHART_RULES
    # live 24 Nov: kala sarpa is not sent; asked, Jothidar worked it out itself and once got it wrong (0/2)
    assert "even if KNOWLEDGE explains how to check it" in CHART_RULES
    assert "When the dosham list does have it (kala_sarpa or any other), give it like the others." in CHART_RULES


def test_without_a_navamsa_lagnam_the_next_sentence_stays_the_birth_chart():
    c = _with_navamsa({p: s for p, s in NAV.items() if p != "lagnam"})
    assert find_wrong(c, "நவாம்சத்துல சுக்கிரன் மீனத்துல இருக்கார். கேது 10ம் இடத்துல இருக்கார்.") == []


@pytest.mark.parametrize("reply,wrong", [
    # live 24 Nov, real chart: "its lord Mars sits in your navamsa lagnam itself (Rishabam)" -- Mars is the 6th.
    # Any clause with a lord word was skipped, and "in the lagnam" was not read as the 1st house.
    ("உங்க நவாம்ச லக்னம் மகரம். இதோட அதிபதி சனி உங்க நவாம்ச லக்னத்திலேயே இருக்கார்.", True),   # navamsa சனி: 2nd
    ("நவாம்சத்துல 7ம் அதிபதி சந்திரன் 1ம் இடத்துல இருக்கார்.", True),                             # navamsa சந்திரன்: 10th
    ("Your 7th lord Moon sits in the 5th house.", True),                                           # birth சந்திரன்: 8th
    ("சனி லக்னத்துல இருக்கார்.", True),                                                          # birth சனி: 6th
    ("லக்னாதிபதி சனி 7ம் இடத்துல இருக்கார்.", True),
    # the house a lord word belongs to is not where the planet sits
    ("நவாம்சத்துல 7ம் இடத்துக்குரிய சந்திரன் 10ம் இடமான துலாத்துல இருக்கார்.", False),           # live: read as சந்திரன் in 7
    ("நவாம்சத்துல 7ம் அதிபதி சந்திரன் 10ம் இடத்துல இருக்கார்.", False),
    ("Your 7th lord Moon sits in the 8th house.", False),
    ("Lord of your 7th house, the Moon, sits in the 8th house.", False),
    ("7ம் இடமான கடக ராசிக்கு அதிபதி சந்திரன்.", False),
    ("லக்னத்தில் இருந்து 7ம் இடம் கடகம்.", False),                                              # "from the lagnam": a count
    ("லக்னாதிபதி சனி 6ம் இடத்துல இருக்கார்.", False),
    # live 21 Nov (lang eval): a list of what to look at, not where Mars sits
    ("To see about buying a house, we look at the 4th house, its lord, and the planet Mars, which represents land.", False),
])
def test_where_a_lord_sits_is_checked(reply, wrong):
    assert bool(find_wrong(_with_navamsa(NAV), reply)) == wrong, find_wrong(_with_navamsa(NAV), reply)


@pytest.mark.parametrize("reply,wrong", [
    # live 24 Nov, AstroTamil's real chart: "உங்க நவாம்ச 7ம் இடத்துல எந்த கிரகமும் இல்ல" -- Venus is there.
    # The checker read only "planet X in house N", never "house N is empty". Here: navamsa Mars is the 7th.
    ("உங்க நவாம்ச 7ம் இடத்துல எந்த கிரகமும் இல்ல, அந்த இடத்தோட அதிபதி சந்திரன்.", True),
    ("In your navamsa, there is no planet in the 7th house.", True),
    ("உங்க நவாம்சத்துல 7ம் இடம் காலியா இருக்கு.", True),
    ("உங்க 4ம் இடத்துல எந்த கிரகமும் இல்ல.", True),     # birth: Rahu (lagnam), Sun (rasi, and today)
    # right: really empty
    ("உங்க நவாம்ச 8ம் இடம் காலியா இருக்கு.", False),
    ("Your navamsa 9th house is empty.", False),
    ("உங்க 7ம் இடத்துல எந்த கிரகமும் இல்லை.", False),   # birth Kadagam from Magaram: empty
    # general or conditional: not a claim
    ("7ம் இடத்துல எந்த கிரகமும் இல்லைன்னா, 7ம் அதிபதியை பார்க்கணும்.", False),
    ("If there is no planet in the 4th house, look at its lord.", False),
])
def test_an_empty_house_claim_is_checked(reply, wrong):
    assert bool(find_wrong(_with_navamsa(NAV), reply)) == wrong, find_wrong(_with_navamsa(NAV), reply)


def test_the_navamsa_houses_are_counted_for_jothidar():
    """Live 24 Nov: Ketu sat in Simmam in both charts and 3 of 5 answers put it in the navamsa 7th (its birth house)."""
    from app.companion.prompt import chart_rules
    rules = chart_rules(json.dumps(dict(CHART, navamsa=NAV)))
    assert "கேது 5 (ரிஷபம்)" in rules and "சனி 2 (கும்பம்)" in rules     # from a Magaram navamsa lagnam
    assert "7 கடகம் (lord சந்திரன்)" in rules and "12 தனுசு (lord குரு)" in rules


def test_the_redo_never_apologises_for_a_draft_the_person_never_saw():
    """Live 24 Nov: after a redo the reply opened "மன்னிக்கவும், நவாம்சத்துல உங்க 7ம் இடமான கடக ராசியை
    கவனிக்காம விட்டேன்" (sorry, I missed your navamsa 7th house), for a first draft nobody saw."""
    note = redo_note(["reply says சனி in navamsa house 7"])
    assert "never saw that draft" in note and "No sorry" in note


@pytest.mark.parametrize("reply", [
    # live 24 Nov, "What is my lagnam and rasi?": a right answer read as "rasi Magaram", redone, then swapped
    "Unga lagnam Magaram, rasi Simmam.",
    "உங்க ஜாதகப்படி லக்னம் மகரம் (Capricorn), ராசி சிம்மம் (Leo).",
    "உங்க லக்னம் மகரம் ராசி, சந்திர ராசி சிம்மம்.",
])
def test_lagnam_then_rasi_in_one_sentence_is_not_a_wrong_rasi(chart, reply):
    assert find_wrong(chart, reply) == []


@pytest.mark.parametrize("reply", ["Unga lagnam Kanni, rasi Simmam.", "உங்க லக்னம் மகரம் (Capricorn), ராசி மகரம்."])
def test_a_wrong_lagnam_or_rasi_in_that_shape_is_still_caught(chart, reply):
    assert find_wrong(chart, reply)


# --- AstroTamil's real app_data (24 Nov): ISO dates and the full bhukti list of the running dasa
ISO_CHART = {
    "overview": {"lagnam": "Kumbam (Aquarius)", "rasi": "Rishabam (Taurus)"},
    "planets": [{"planet": "Saturn", "rasi": "Dhanusu"}, {"planet": "Moon", "rasi": "Rishabam"}],
    "dasa": {
        "now": {"dasa": "Rahu", "from": "2008-12-10", "to": "2026-12-11",
                "bhukti": "Mars", "bhukti_from": "2025-11-22", "bhukti_to": "2026-12-11"},
        "next_bhukti": ["Jupiter", "2026-12-11", "2029-01-28"],
        "all": [["Mars", "2001-12-10", "2008-12-10"], ["Rahu", "2008-12-10", "2026-12-11"],
                ["Jupiter", "2026-12-11", "2042-12-11"], ["Saturn", "2042-12-11", "2061-12-10"]],
        "bhuktis_of_this_dasa": [["Moon", "2024-05-23", "2025-11-22"], ["Mars", "2025-11-22", "2026-12-11"]],
    },
}


def test_iso_dates_and_the_bhukti_lists_are_read():
    """Before: '2008-12-10' was not a date to us, so the dasa and bhukti were invisible to the guard."""
    c = parse_app_data(json.dumps(ISO_CHART))
    assert (c.dasa.planet, c.dasa.start.isoformat(), c.dasa.end.isoformat()) == ("ராகு", "2008-12-10", "2026-12-11")
    assert len(c.dasas) == 4 and c.next_dasa.planet == "குரு"
    assert [b.planet for b in c.bhuktis] == ["செவ்வாய்", "குரு"]   # the running one first, then the next
    assert c.bhuktis[1].end.isoformat() == "2029-01-28"


@pytest.mark.parametrize("reply", ["Ippo ungalukku Sani dasai nadakkuthu.", "இப்போ சனி புத்தி நடக்குது."])
def test_a_wrong_running_period_is_caught_with_iso_dates(reply):
    assert find_wrong(parse_app_data(json.dumps(ISO_CHART)), reply)


def test_the_right_running_period_is_not_flagged_with_iso_dates():
    c = parse_app_data(json.dumps(ISO_CHART))
    assert find_wrong(c, "இப்போ ராகு தசை, செவ்வாய் புத்தி நடக்குது.") == []
    assert find_wrong(c, "குரு புத்தி 2027-ல நடக்கும்.") == []


def test_now_and_the_next_dasa_in_one_sentence_is_not_flagged():
    """Live 24 Nov (AstroTamil's real chart): "the Rahu dasa running now ends Dec 2026, after that Guru dasa
    starts" was flagged "the running dasa is Rahu, not Guru" once ISO dates made the dasa visible."""
    c = parse_app_data(json.dumps(ISO_CHART))
    assert find_wrong(c, "இப்போ நடக்குற ராகு தசை, செவ்வாய் புத்தி டிசம்பர் 2026-ல் முடியுது, "
                         "அதன்பிறகு குரு தசை ஆரம்பிக்கிறது.") == []
    assert find_wrong(c, "இப்போ குரு தசை நடக்குது.")   # a wrong "now" alone is still caught


def test_a_moves_list_under_another_name_is_read():
    data = dict(ISO_CHART, gocharam={"month_readings": {"readings": [
        {"planet": "Saturn", "moves": ["Meenam -> Mesham, Jun 2027"]}]}})
    assert parse_app_data(json.dumps(data)).moves["சனி"] == {"மீனம்", "மேஷம்"}
