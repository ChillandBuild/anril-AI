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
