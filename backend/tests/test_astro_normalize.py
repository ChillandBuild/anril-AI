import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.services.astro_normalize import (
    normalize_date,
    normalize_gender,
    normalize_phone,
    normalize_time,
)

JUNK = ["", "   ", None, "abcd", "🎂🙏", "-", "??", 0.5, True, [], {}, "x" * 10000]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1990-03-12", "1990-03-12"),
        ("1990-3-2", "1990-03-02"),
        ("1990/03/12", "1990-03-12"),
        ("12/03/1990", "1990-03-12"),
        ("12-03-1990", "1990-03-12"),
        ("12.03.1990", "1990-03-12"),
        ("12th March 1990", "1990-03-12"),
        ("12 March 1990", "1990-03-12"),
        ("March 12 1990", "1990-03-12"),
        ("March 12, 1990", "1990-03-12"),
        ("1st Jan 2001", "2001-01-01"),
        ("2 sept 1975", "1975-09-02"),
        ("23rd DECEMBER 1988", "1988-12-23"),
        ("born on 12 march 1990", "1990-03-12"),
        ("1990 March 12", "1990-03-12"),
    ],
)
def test_normalize_date_formats(raw, expected):
    assert normalize_date(raw) == expected


def test_date_is_day_first_for_ambiguous_numeric_input():
    assert normalize_date("03/04/1990") == "1990-04-03"
    assert normalize_date("04/03/1990") == "1990-03-04"


def test_date_iso_four_digit_year_first_is_year_month_day():
    assert normalize_date("1990-03-12") == "1990-03-12"
    assert normalize_date("1990-12-03") == "1990-12-03"


def test_date_falls_back_to_month_first_only_when_day_first_is_impossible():
    assert normalize_date("03/25/1990") == "1990-03-25"


@pytest.mark.parametrize(
    "raw",
    [
        "99/99/9999",
        "32/01/1990",
        "1990-13-05",
        "1990-02-30",
        "13/13/1990",
        "31/04/1990",
        "12/03/90",
        "12/03/19",
        "12 march 90",
        "12/1990",
        "1990",
        "12/03/1990 09:30",
        "12/03/19900",
        "12 march april 1990",
        "12/03/1700",
    ],
)
def test_normalize_date_rejects_bad_input(raw):
    assert normalize_date(raw) is None


@pytest.mark.parametrize("raw", JUNK)
def test_normalize_date_junk(raw):
    assert normalize_date(raw) is None


def test_normalize_date_rejects_future_birth_year():
    # Regression: the upper bound was a fixed 2100, so a fat-finger year like
    # 2099 parsed as a valid chart. A birth date can never be in the future,
    # so an impossible future year must refuse while a normal past year parses.
    assert normalize_date("12/03/2099") is None
    assert normalize_date("12/03/1991") == "1991-03-12"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9:30 AM", "09:30:00"),
        ("9:30am", "09:30:00"),
        ("9:30 a.m.", "09:30:00"),
        ("9:30pm", "21:30:00"),
        ("9:30 PM", "21:30:00"),
        ("09.30", "09:30:00"),
        ("21:30", "21:30:00"),
        ("9 30", "09:30:00"),
        ("morning 9.30", "09:30:00"),
        ("evening 7.30", "19:30:00"),
        ("night 9", "21:00:00"),
        ("காலை 9.30", "09:30:00"),
        ("सुबह 9:30", "09:30:00"),
        ("9", "09:00:00"),
        ("9 am", "09:00:00"),
        ("0930", "09:30:00"),
        ("930", "09:30:00"),
        ("09:30:15", "09:30:15"),
        ("12 am", "00:00:00"),
        ("12 pm", "12:00:00"),
        ("12:45 am", "00:45:00"),
        ("00:00", "00:00:00"),
        ("23:59:59", "23:59:59"),
        ("12 midnight", "00:00:00"),
        ("12:00 midnight", "00:00:00"),
        ("12:30 midnight", "00:30:00"),
        ("12 நள்ளிரவு", "00:00:00"),
        ("12 मध्यरात्रि", "00:00:00"),
        ("12 noon", "12:00:00"),
    ],
)
def test_normalize_time_formats(raw, expected):
    assert normalize_time(raw) == expected


def test_normalize_time_midnight_is_zero_not_noon():
    # Regression: "midnight" was absent from _AM_WORDS, so "12 midnight"
    # collapsed to 12:00:00 (noon) — a birth time off by 12 hours.
    assert normalize_time("12 midnight") == "00:00:00"
    # A bare meridiem word with no digits is still unparseable.
    assert normalize_time("midnight") is None
    # The neighbouring 12-o'clock phrasings are unchanged.
    assert normalize_time("12 am") == "00:00:00"
    assert normalize_time("12 noon") == "12:00:00"
    assert normalize_time("12 pm") == "12:00:00"


@pytest.mark.parametrize(
    "raw",
    ["25:00", "24:30", "9:70", "09:30:99", "99999", "1:2:3:4", "morning"],
)
def test_normalize_time_rejects_bad_input(raw):
    assert normalize_time(raw) is None


def test_normalize_time_tolerates_llm_bullet_prefix():
    assert normalize_time("- 9:30 AM") == "09:30:00"


@pytest.mark.parametrize("raw", JUNK)
def test_normalize_time_junk(raw):
    assert normalize_time(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["female", "Female", "FEMALE", "f", "F", " f ", "girl", "woman", "lady",
     "she", "பெண்", "பெண", "महिला", "स्त्री", "female (f)", "Gender: Female"],
)
def test_normalize_gender_female(raw):
    assert normalize_gender(raw) == "F"


@pytest.mark.parametrize(
    "raw",
    ["male", "Male", "MALE", "m", "M", " m ", "boy", "man", "he",
     "ஆண்", "ஆண", "पुरुष", "आदमी", "male (m)", "Gender: Male"],
)
def test_normalize_gender_male(raw):
    assert normalize_gender(raw) == "M"


@pytest.mark.parametrize(
    "raw",
    ["unknown", "other", "n/a", "not sure", "male female", "x", "0", "1",
     "transgender", "prefer not to say", "மனிதன்"],
)
def test_normalize_gender_never_guesses(raw):
    assert normalize_gender(raw) is None


@pytest.mark.parametrize("raw", JUNK)
def test_normalize_gender_junk(raw):
    assert normalize_gender(raw) is None


def test_normalize_gender_female_is_not_read_as_male_substring():
    assert normalize_gender("female") == "F"
    assert normalize_gender("FEMALE") == "F"


@pytest.mark.parametrize(
    "raw",
    [
        "9345679286",
        "+91 93456 79286",
        "+919345679286",
        "91-9345679286",
        "919345679286",
        "009345679286",
        "00919345679286",
        "09345679286",
        "+91-93456-79286",
        "(+91) 93456 79286",
        " 93456 79286 ",
    ],
)
def test_normalize_phone_variants(raw):
    assert normalize_phone(raw) == "+919345679286"


def test_normalize_phone_keeps_foreign_numbers_that_carry_a_plus():
    assert normalize_phone("+1 415 555 2671") == "+14155552671"


def test_normalize_phone_honours_default_cc():
    assert normalize_phone("4155552671", default_cc="+1") == "+14155552671"


# Partner sends country code + number with no "+" (2026-10-23: 168 of 168 overseas sends refused).
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("94771234567", "+94771234567"),
        ("+94771234567", "+94771234567"),
        ("60123456789", "+60123456789"),
        ("971501234567", "+971501234567"),
        ("00971501234567", "+971501234567"),
        ("447911123456", "+447911123456"),
        ("97455123456", "+97455123456"),
    ],
)
def test_normalize_phone_reads_foreign_country_code_without_plus(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["9477123456789", "947712345", "+9477123", "60123"])
def test_normalize_phone_rejects_foreign_numbers_of_the_wrong_length(raw):
    assert normalize_phone(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "12345",
        "1234567890",
        "5345679286",
        "0000000000",
        "9345679286123456",
        "+919345679286123",
        "+918",
        "93456 7928",
    ],
)
def test_normalize_phone_rejects_bad_input(raw):
    assert normalize_phone(raw) is None


@pytest.mark.parametrize("raw", JUNK)
def test_normalize_phone_junk(raw):
    assert normalize_phone(raw) is None


def test_normalize_phone_accepts_integer_input():
    assert normalize_phone(9345679286) == "+919345679286"


def test_long_input_is_rejected_without_scanning():
    blob = "12/03/1990 " * 2000
    assert normalize_date(blob) is None
    assert normalize_time(blob) is None
    assert normalize_gender("female " * 2000) is None
    assert normalize_phone("9345679286 " * 2000) is None


# ── Compact dates, unknown times and AM/PM ambiguity (Keerthi, 2026-10-01: "19112003") ──
from app.services.astro_normalize import (
    format_time_12h,
    is_unknown_time,
    time_needs_meridiem,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("19112003", "2003-11-19"),
        ("01011990", "1990-01-01"),
        ("20031119", "2003-11-19"),
        (19112003, "2003-11-19"),
        ("19 11 2003", "2003-11-19"),
        ("19-11-2003", "2003-11-19"),
    ],
)
def test_compact_dates_are_read_when_only_one_reading_fits(raw, expected):
    assert normalize_date(raw) == expected


@pytest.mark.parametrize("raw", ["1911203", "191120033", "99992003", "31022003", "19112099", "123456"])
def test_compact_dates_that_do_not_fit_are_refused(raw):
    # 31 Feb, year 2099 (future), wrong digit counts: never guess.
    assert normalize_date(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["theriyathu", "Theriyadhu", "தெரியாது", "தெரியலை", "don't know", "dont know", "not known",
     "unknown", "no idea", "pata nahi", "पता नहीं", "I do not know",
     "therila", "teriyathu", "theriyaathu", "theriyalai"],
)
def test_unknown_time_words_are_recognised(raw):
    assert is_unknown_time(raw) is True
    assert normalize_time(raw) is None


@pytest.mark.parametrize("raw", ["10:30 am", "6 pm", "morning", "", None, "abc", "10.30", "theriyum", "terrible"])
def test_real_or_unreadable_times_are_not_unknown(raw):
    assert is_unknown_time(raw) is False


@pytest.mark.parametrize(
    "raw,needs",
    [
        ("10:30", True),
        ("5.30", True),
        ("1030", True),
        ("9", True),
        ("10:30 am", False),
        ("10:30 PM", False),
        ("6 in the evening", False),
        ("morning 6", False),
        ("மாலை 6", False),
        ("17:45", False),
        ("13.05", False),
        ("00:15", False),
        ("0030", False),
        ("theriyathu", False),
    ],
)
def test_twelve_hour_time_without_am_pm_needs_a_question(raw, needs):
    assert time_needs_meridiem(raw) is needs


@pytest.mark.parametrize(
    "normalized,shown",
    [("10:30:00", "10:30 AM"), ("00:05:00", "12:05 AM"), ("12:00:00", "12:00 PM"), ("18:00:00", "06:00 PM"),
     ("23:59:30", "11:59:30 PM")],
)
def test_time_is_shown_in_twelve_hour_form(normalized, shown):
    assert format_time_12h(normalized) == shown
    assert normalize_time(shown) == normalized


from app.services.astro_normalize import normalize_place


@pytest.mark.parametrize("raw,expected", [
    ("Neyveli", "Neyveli"), ("  Coimbatore, Tamil Nadu ", "Coimbatore, Tamil Nadu"), ("நெய்வேலி", "நெய்வேலி"),
    ("St. John's", "St. John's"),
])
def test_a_real_place_is_kept(raw, expected):
    assert normalize_place(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "?", "-", "12", "x", "idk", "na", "N/A", "theriyathu", "don't know", "🙏"])
def test_a_non_place_is_refused(raw):
    assert normalize_place(raw) is None
