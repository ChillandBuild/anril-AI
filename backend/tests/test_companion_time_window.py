"""Item 5 (AstroTamil, 27 Nov 2026): an eppo / when answer starts with its dasa-bhukti time window.

The model writes the window in a [window: ...] slot; code puts it first. Rules alone never got it first
(3 of 10 timing answers, three wordings tried, 28 Nov 2026)."""
import json

from app.companion.chip_repeats import kinds
from app.companion.prompt import WINDOW_RULE, build_messages, wants_window
from app.companion.reply_format import ReplyFormat, place_window, read_format
from tests.test_companion_chart_guard import APP_DATA, _guard
from tests.test_companion_engine import env, reply  # noqa: F401  (env is a fixture)

WINDOW = "செவ்வாய் தசை - சுக்கிர புத்தி, மே 2027 - ஜூலை 2028: வீடு வாங்க வாய்ப்பு அதிகம்"


# --- place_window ------------------------------------------------------------------------------

def test_the_window_becomes_the_first_line_of_the_first_bubble():
    text = (f"[tag: counted] [button: none]\nஉங்க 4ம் அதிபதி சூரியன் லக்னத்துல இருக்கார்.\n---\nமுயற்சி பண்ணலாம்.\n"
            f"[window: {WINDOW}]\n[chips: none]")
    shaped = read_format(place_window(text), ReplyFormat())
    assert shaped.bubbles == [f"{WINDOW}\nஉங்க 4ம் அதிபதி சூரியன் லக்னத்துல இருக்கார்.", "முயற்சி பண்ணலாம்."]
    assert shaped.tag == "counted" and "[window" not in "".join(shaped.bubbles)


def test_a_plain_reply_gets_the_window_first_too():
    assert place_window(f"Guru 8th la irukkar.\n[window: {WINDOW}]") == f"{WINDOW}\nGuru 8th la irukkar."
    assert place_window(f"[ Window :{WINDOW} ] Guru 8th la.") == f"{WINDOW}\nGuru 8th la."


def test_no_window_or_an_empty_one_changes_nothing_but_the_tag():
    assert place_window("Guru 8th la.") == "Guru 8th la."
    assert place_window("Guru 8th la.\n[window: none]") == "Guru 8th la."
    assert place_window("[window:  ]\nGuru 8th la.") == "Guru 8th la."
    assert place_window("") == "" and place_window(None) is None


def test_only_the_first_window_is_used_and_it_is_cut_to_a_line():
    text = f"[window: {WINDOW}] Body.\n[window: second one]"
    assert place_window(text) == f"{WINDOW}\nBody."
    assert place_window(f"[window: {'x' * 300}] Body.").split("\n")[0] == "x" * 200


def test_a_window_repeated_word_for_word_in_the_reply_is_shown_once():
    text = f"[window: {WINDOW}]\n{WINDOW}.\nஉங்க 4ம் அதிபதி சூரியன்."
    assert place_window(text) == f"{WINDOW}\nஉங்க 4ம் அதிபதி சூரியன்."


# --- when the prompt asks for it ---------------------------------------------------------------

def test_follow_up_eppo_words_read_as_when():
    assert "when" in kinds("Adhu epodan start aagum") and "when" in kinds("Epo adhukaana time ah irkum")


def test_only_a_chart_guard_character_asked_a_when_question_gets_the_window_rule():
    card = {"name": "Jothidar", "rules": [], "chart_guard": True}
    assert wants_window(card, "புதிய வீடு எப்போது?") and wants_window(card, "Nan next house epo vanguven.")
    assert not wants_window(card, "Health condition epdi irkum")
    assert not wants_window({**card, "chart_guard": False}, "Kalyanam eppo?")
    system = build_messages(card, "calm", None, "", [], "Kalyanam eppo?", app_data=APP_DATA)[0]["content"]
    assert WINDOW_RULE in system and "[window:" in WINDOW_RULE
    assert WINDOW_RULE not in build_messages(card, "calm", None, "", [], "Health eppadi?",
                                             app_data=APP_DATA)[0]["content"]


# --- in a real reply ----------------------------------------------------------------------------

def test_a_when_answer_starts_with_its_window(env):  # noqa: F811
    _guard(env)
    env.state["replies"] = ["[mood: calm] [used: none] Guru is in Simmam, your 8th house. Patience.\n"
                            "[window: சுக்கிர தசை - புதன் புத்தி, 2028: marriage chance]"]
    r = reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA)
    assert r.text == "சுக்கிர தசை - புதன் புத்தி, 2028: marriage chance\nGuru is in Simmam, your 8th house. Patience."
    assert WINDOW_RULE in env.state["llm"][0]["messages"][0]["content"]
    assert env.db.rows("companion_messages")[-1]["content"] == r.text


def test_a_wrong_chart_fact_in_the_window_gets_the_redo(env):  # noqa: F811
    _guard(env)
    env.state["replies"] = ["[mood: calm] [used: none] Patience.\n[window: Guru is in your 7th house, so 2027]",
                            "[mood: calm] [used: none] Patience.\n[window: Guru is in Simmam, your 8th house: 2028]"]
    r = reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA)
    assert len(env.state["llm"]) == 2 and "குரு in house 7" in env.state["llm"][1]["messages"][-1]["content"]
    assert r.text.startswith("Guru is in Simmam, your 8th house: 2028")


def test_the_reply_format_puts_the_window_in_the_first_bubble(env):  # noqa: F811
    _guard(env)
    env.state["replies"] = ["[mood: calm] [used: none] [tag: counted] [button: none]\nGuru is in Simmam, your 8th "
                            "house.\n---\nPatience.\n[window: சுக்கிர புத்தி, 2028]\n[chips: none]"]
    r = reply(env.jothidar["id"], "Kalyanam eppo?", app_data=APP_DATA, reply_format=ReplyFormat())
    assert r.bubbles == ["சுக்கிர புத்தி, 2028\nGuru is in Simmam, your 8th house.", "Patience."]
    assert "[" not in "".join(r.bubbles) and "window" not in json.dumps(r.bubbles)
