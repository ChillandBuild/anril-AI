"""birth_guard: birth date, time and place are hidden; the chart and other dates stay."""
import json

import pytest

from app.companion.birth_guard import HIDDEN, strip_app_data, strip_birth_json, strip_birth_text


@pytest.mark.parametrize("text", [
    "I was born on 19 Nov 2003 at 10:30 AM in Madurai.",
    "naan 2003la porandhen, Madurai la.",
    "நான் 10.30 மணிக்கு மதுரையில் பிறந்தேன்.",
    "My DOB is 19-11-2003.",
])
def test_a_sentence_with_birth_details_is_hidden(text):
    assert strip_birth_text(text + " Will I get a job?") == HIDDEN + " Will I get a job?"


@pytest.mark.parametrize("text", [
    "என் பிறந்த நட்சத்திரம் உத்திரம்.",          # a birth star is part of the chart
    "ஜனன ஜாதகத்தில் 7ம் இடம் பலமாக உள்ளது.",     # chart talk, not a birth place
    "My exam is on 5 Dec 2026.",                  # a date, but no birth word
    "Rahu dasa started on 23 Jun 2026.",
])
def test_chart_talk_and_other_dates_stay(text):
    assert strip_birth_text(text) == text


def test_labelled_lines_of_a_text_chart_are_dropped():
    chart = "Birth date: 19-11-2003\nBirth time: 10:30 AM\nLat / Long: 9.9, 78.1\nTamil date: Karthigai 3\nRasi: Simmam\nLagnam: Magaram"
    assert strip_birth_text(chart) == "Rasi: Simmam\nLagnam: Magaram"


def test_json_birth_keys_are_dropped_at_any_depth():
    data = {"dob": "19-11-2003", "rasi": "Simmam",
            "profile": {"time_of_birth": "10:30", "place-of-birth": "Madurai", "Latitude": 9.9, "name": "Prem"},
            "birth": {"date": "19-11-2003"}, "dasa": {"from": "23 Jun 2026"}}
    assert strip_birth_json(data) == {"rasi": "Simmam", "profile": {"name": "Prem"}, "dasa": {"from": "23 Jun 2026"}}


def test_app_data_json_stays_compact_json_and_text_stays_text():
    out = strip_app_data(json.dumps({"dob": "19-11-2003", "rasi": "சிம்மம்"}))
    assert out == '{"rasi":"சிம்மம்"}'
    assert strip_app_data("Birth place: Madurai\nRasi: Simmam") == "Rasi: Simmam"
    assert strip_app_data(None) is None


@pytest.mark.parametrize("text,kept", [
    # the trap eval's question: hiding the whole sentence left the model nothing but a greeting
    ("என் பிறந்த நேரம் 10.30, அதை வைத்து அடுத்த புத்தி எப்போ ஆரம்பம்னு கணக்கு போட்டு சொல்லுங்க",
     "அதை வைத்து அடுத்த புத்தி எப்போ ஆரம்பம்னு கணக்கு போட்டு சொல்லுங்க"),
    ("Born 19 Nov 2003, kalyanam eppo nadakkum?", "kalyanam eppo nadakkum?"),
    ("I was born in 2003 at 10:30, in Madurai, when will I marry?", "when will I marry?"),   # place hidden too
])
def test_only_the_birth_part_of_a_sentence_is_hidden_and_the_question_stays(text, kept):
    assert strip_birth_text(text) == HIDDEN + " " + kept


def test_a_block_marked_as_the_birth_day_is_dropped():
    """AstroTamil, 24 Nov 2026: "panchangam" was the birth day's (born Wednesday), sent next to today's date, so
    "what is today's thithi?" would get the birth one. They now mark it; the block is a birth detail and goes."""
    data = {"overview": {"rasi": "Rishabam", "today": "2026-11-24"},
            "panchangam": {"of": "the birth day, not today", "thithi": "Pournami", "vaaram": "Wednesday"},
            "gocharam": {"for_rasi": "Rishabam", "as_of": "2026-11-24T04:15:00+05:30"},
            "today_panchangam": {"of": "today", "thithi": "Pradhamai"}}
    out = strip_birth_json(data)
    assert "panchangam" not in out
    assert out["gocharam"] == data["gocharam"] and out["today_panchangam"] == data["today_panchangam"]
    assert out["overview"] == data["overview"]
