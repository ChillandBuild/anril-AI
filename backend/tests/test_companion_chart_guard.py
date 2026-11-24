"""Chart guard in the engine: wrong chart fact -> one redo -> still wrong -> the handoff line.

Same fake DB and fake model as test_companion_engine. The chart is Prem's (Guru in Simmam, house 8 from
Magaram lagnam; Simmam rasi)."""
import asyncio
import json

import pytest

from app.companion import engine
from tests.test_chart_check import CHART
from tests.test_companion_engine import env, reply  # noqa: F401  (env is a fixture)

APP_DATA = json.dumps({**CHART, "birth": {"date": "19-11-2003", "time": "10:30 AM", "place": "Madurai"}})
WRONG = "[mood: calm] [used: none] Guru is in your 7th house, so marriage comes soon."
RIGHT = "[mood: calm] [used: none] Guru is in Simmam, your 8th house. Marriage needs patience."
HANDOFF = "Idharku engal team-idam ketpadhu nalladhu."


def _guard(env, on=True):
    next(c for c in env.db.rows("companions") if c["id"] == env.jothidar["id"])["chart_guard"] = on


def test_a_wrong_fact_gets_one_redo_that_lists_it(env):
    _guard(env)
    env.state["replies"] = [WRONG, RIGHT]
    r = reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA)
    assert r.text == "Guru is in Simmam, your 8th house. Marriage needs patience."
    assert len(env.state["llm"]) == 2
    redo = env.state["llm"][1]["messages"]
    assert redo[-2] == {"role": "assistant", "content": WRONG}
    assert "குரு in house 7" in redo[-1]["content"] and redo[-1]["role"] == "user"
    assert env.db.rows("companion_messages")[-1]["content"] == r.text


def test_still_wrong_after_the_redo_sends_the_handoff_line_and_saves_no_wrong_fact(env):
    _guard(env)
    env.state["replies"] = [WRONG, WRONG]
    r = reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA)
    assert r.text == HANDOFF and r.basis is None
    assert env.db.rows("companion_messages")[-1]["content"] == HANDOFF
    assert [entry[3] for entry in env.state["logged"]] == ["handoff"]


def test_a_failed_redo_also_hands_off(env):
    _guard(env)
    env.state["replies"] = [WRONG, RuntimeError("gemini down")]
    assert reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA).text == HANDOFF


def test_guard_off_sends_the_draft_with_no_extra_call(env):
    env.state["replies"] = [WRONG]
    r = reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA)
    assert r.text.startswith("Guru is in your 7th house") and len(env.state["llm"]) == 1


def test_a_right_reply_and_a_question_back_are_not_redone(env):
    _guard(env)
    env.state["replies"] = [RIGHT, "[mood: warm] [used: talk] Guru 7th house pathi ketkureengala?"]
    reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA)
    reply(env.jothidar["id"], "Guru?", app_data=APP_DATA)
    assert len(env.state["llm"]) == 2


def test_no_chart_in_app_data_means_nothing_to_check(env):
    _guard(env)
    env.state["replies"] = [WRONG]
    reply(env.jothidar["id"], "Kalyanam eppo?", app_data='{"plan": "gold"}')
    assert len(env.state["llm"]) == 1


def test_birth_details_never_reach_the_model_with_the_guard_on(env):
    _guard(env)
    env.state["replies"] = [RIGHT]
    reply(env.jothidar["id"], "I was born on 19 Nov 2003 at 10:30 AM in Madurai. Kalyanam eppo?", app_data=APP_DATA)
    sent = json.dumps(env.state["llm"][0]["messages"], ensure_ascii=False)
    assert "19-11-2003" not in sent and "10:30" not in sent and "Madurai" not in sent
    assert "விருச்சிகம்" in sent or "Viruchigam" in sent   # the chart itself is still there


def test_the_compare_reply_without_memory_is_checked_too(env):
    _guard(env)
    env.state["replies"] = [WRONG, WRONG]
    companion = next(c for c in env.db.rows("companions") if c["id"] == env.jothidar["id"])
    r = asyncio.run(engine._reply_without_memory(companion, "t1", "Kalyanam eppo?", None, APP_DATA))
    assert r.text == HANDOFF and len(env.state["llm"]) == 2


def test_the_model_choosing_the_astrologer_button_goes_on_the_missing_answers_list(env):
    from tests.test_companion_engine import FMT
    env.state["replies"] = ["[mood: calm] [used: none] [tag: astrologer] [button: astrologer]\n"
                            "Idhai namma jothidar kitta kelunga."]
    r = reply(env.jothidar["id"], "En vazhkai eppadi irukkum?", reply_format=FMT)
    assert r.button == "astrologer"
    assert [entry[3] for entry in env.state["logged"]] == ["handoff"]


def test_the_porutham_button_is_not_a_handoff(env):
    from tests.test_companion_engine import FMT
    env.state["replies"] = ["[mood: calm] [used: none] [tag: porutham] [button: porutham]\nPorutham paarkalaam."]
    reply(env.jothidar["id"], "Porutham paarkanum", reply_format=FMT)
    assert [entry[3] for entry in env.state["logged"]] == ["chat"]


# --- an own-reading answer also points to the business's astrologer -------------------------------------

def test_an_own_reading_answer_keeps_its_text_and_gets_the_astrologer_button(env):
    from tests.test_companion_engine import FMT
    env.state["kb_error"] = True   # no file answers -> basis "own"
    env.state["replies"] = ["[mood: calm] [used: none] Naga dosham pothuvaa Rahu Kethu sambandham.\n"
                            "[chips: Parigaaram? | Kovil?]"]
    r = reply(env.jothidar["id"], "Naga dosham na enna?", reply_format=FMT)
    assert r.basis == "own" and r.text == "Naga dosham pothuvaa Rahu Kethu sambandham."
    assert r.button == "astrologer" and r.tag == "counted" and r.chips


def test_an_answer_from_the_files_gets_no_added_button(env):
    from tests.test_companion_engine import FMT
    env.state["replies"] = ["[mood: calm] [used: 1] Guru 7th house la irukku."]
    r = reply(env.jothidar["id"], "Kalyanam eppo?", reply_format=FMT)
    assert r.basis != "own" and r.button is None


def test_the_prompt_asks_for_the_businesss_own_handoff_line_after_an_own_answer():
    from app.companion.platform_rules import OWN_REASONING_ALLOWED
    from app.companion.prompt import own_reasoning_allowed
    assert own_reasoning_allowed({}) == OWN_REASONING_ALLOWED
    text = own_reasoning_allowed({"handoff_line": 'இதை நம்ம "AstroTamil" ஜோதிடர்கிட்ட கேளுங்க.'})
    assert 'like: "இதை நம்ம AstroTamil ஜோதிடர்கிட்ட கேளுங்க."' in text


# --- a chart pasted into the chat never reaches the model (live 23 Nov: "your lagnam is Mesham") ---------

PASTED = ("this is my horoscope details\n\nPlanets\tPositions\tDegrees\tRasi\n"
          "Sun Sun\t256° 26'\t16° 26′\tDhanu Dhanu\tJupiter\nMoon Moon\t30° 7'\t0° 7′\tVrishabha Vrishabha\tVenus\n"
          "Jupiter Jupiter\t117° 40'\t27° 40′\tKarka Karka\tMoon\nAscendant Ascendant\t1° 22'\t1° 22′\tMesha Mesha\tMars\n"
          "Rasi\tVrishabha\nAscendant\tMesha")


def test_a_pasted_chart_is_swapped_and_a_short_chart_question_stays():
    from app.companion.prompt import PASTED_CHART, hide_pasted_chart
    assert hide_pasted_chart(PASTED) == PASTED_CHART
    assert hide_pasted_chart("En rasi Kanni thaane? Guru Simmathil irukka?") == "En rasi Kanni thaane? Guru Simmathil irukka?"


def test_with_the_guard_on_a_pasted_chart_in_history_is_not_sent(env):
    _guard(env)
    env.state["replies"] = [RIGHT, RIGHT]
    reply(env.jothidar["id"], PASTED, app_data=APP_DATA)
    reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA)
    sent = json.dumps(env.state["llm"][1]["messages"], ensure_ascii=False)
    assert "Mesha Mesha" not in sent and "pasted a horoscope" in sent


def test_with_the_guard_off_a_pasted_chart_is_sent_as_before(env):
    env.state["replies"] = [RIGHT]
    reply(env.jothidar["id"], PASTED, app_data=APP_DATA)
    assert "Mesha Mesha" in json.dumps(env.state["llm"][0]["messages"], ensure_ascii=False)


# --- the astrologer nudge (24 Nov, Playground App view): once, and only on readings ---------------------

def test_with_the_apps_handoff_button_the_prompt_drops_the_handoff_line():
    """Live: "my lagnam is Kanni, right?" ended with the line "ask our AstroTamil astrologer" as a bubble AND
    the astrologer button under it. When the app has a hand-off button, the button is the nudge."""
    from app.companion.prompt import own_reasoning_allowed
    s = {"handoff_line": "இதை நம்ம AstroTamil ஜோதிடர்கிட்ட நேரடியா கேக்கறது நல்லதுங்க."}
    with_button = own_reasoning_allowed(s, app_button=True)
    assert "ஜோதிடர்கிட்ட" not in with_button and "button" in with_button
    assert "ஜோதிடர்கிட்ட" in own_reasoning_allowed(s)   # no button (plain text, widget): the line stays


def test_the_prompt_built_with_a_handoff_button_has_no_handoff_line(env):
    from tests.test_companion_engine import FMT
    next(c for c in env.db.rows("companions") if c["id"] == env.jothidar["id"])["handoff_line"] = "Ask our astrologer da."
    env.state["replies"] = ["[mood: calm] [used: none] [tag: counted] [button: none] Simmam rasi.\n[chips: none]"] * 2
    reply(env.jothidar["id"], "En rasi enna?", reply_format=FMT)
    assert "Ask our astrologer da." not in env.state["llm"][0]["messages"][0]["content"]
    reply(env.jothidar["id"], "En rasi enna?")   # no format, no button: the line is asked for
    assert "Ask our astrologer da." in env.state["llm"][1]["messages"][0]["content"]


@pytest.mark.parametrize("answer, button", [
    # a chart fact or a correction: no astrologer button
    ("[mood: calm] [used: none] [tag: counted] [button: none] உங்க ஜாதகப்படி உங்க லக்னம் மகரம் தான்.\n---\n"
     "கன்னி லக்னம் இல்லைங்க, உங்க ஜாதகத்துல லக்னம் மகரம்னு தான் பதிவாகிருக்கு.\n[chips: a? | b?]", None),
    ("[mood: calm] [used: none] [tag: counted] [button: none] Unga rasi Simmam, lagnam Magaram.\n[chips: a? | b?]", None),
    # a reading: the button stays
    ("[mood: calm] [used: none] [tag: counted] [button: none] 7ம் அதிபதி சந்திரன் 8ம் இடத்துல இருக்கார். இது "
     "திருமணத்துல கொஞ்சம் தாமதத்தை காட்டலாம்.\n[chips: a? | b?]", "astrologer"),
    ("[mood: calm] [used: none] [tag: counted] [button: none] Naga dosham pothuvaa Rahu Kethu sambandham.\n[chips: a? | b?]",
     "astrologer"),
])
def test_the_astrologer_button_comes_with_readings_not_with_chart_facts(env, answer, button):
    from tests.test_companion_engine import FMT
    env.state["replies"] = [answer]
    question = "En lagnam Kanni thaane?" if button is None else "Kalyanam eppo nadakkum?"
    r = reply(env.jothidar["id"], question, reply_format=FMT)
    assert r.basis == "own" and r.tag == "counted" and r.button == button


@pytest.mark.parametrize("question, lookup", [
    ("என் லக்னம் கன்னி தானே?", True), ("What is my lagnam and rasi?", True), ("இப்போ என்ன தசை நடக்குது?", True),
    ("En natchathiram enna?", True),
    ("When will I get married?", False), ("Rahu dasa nalla irukuma?", False), ("என் வேலை இந்த வருஷம் எப்படி இருக்கும்?", False),
    ("Do I have sevvai dosham?", False), ("Hi", False),
])
def test_a_chart_lookup_is_told_apart_from_a_reading(question, lookup):
    from app.companion.chart_check import is_chart_lookup
    assert is_chart_lookup(question) is lookup
