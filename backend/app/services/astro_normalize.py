import re
import unicodedata
from datetime import date

import phonenumbers

_MAX_INPUT_LEN = 120
_MIN_YEAR = 1900

# Combining marks in Tamil/Devanagari are not \w in Python, so `\w+` shreds
# "பெண்" into ["ப", "ண"]. Split on explicit separators instead.
_SEPARATORS = re.compile(r"[\s,;:/|()\[\]{}<>_.+*?!\"'=\\-]+")

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_MERIDIEM = re.compile(r"(?<![a-z])([ap])\.?m\.?(?![a-z])")

_AM_WORDS = {
    "morning", "dawn", "midnight",
    "காலை", "விடியல்", "நள்ளிரவு", "மத்தியிரவு",
    "सुबह", "प्रातः", "मध्यरात्रि",
}
_PM_WORDS = {
    "afternoon", "evening", "night", "noon",
    "மதியம்", "பிற்பகல்", "மாலை", "இரவு",
    "दोपहर", "शाम", "रात",
}

_FEMALE = {
    "f", "fem", "female", "girl", "woman", "women", "lady", "she", "her",
    "daughter", "mrs", "miss", "ms",
    "பெண்", "பெண", "பெண்குழந்தை", "ஸ்திரீ",
    "महिला", "स्त्री", "औरत", "लड़की", "बेटी",
}

_MALE = {
    "m", "male", "boy", "man", "men", "gent", "gentleman", "he", "him",
    "son", "mr",
    "ஆண்", "ஆண", "ஆண்குழந்தை", "பையன்",
    "पुरुष", "आदमी", "मर्द", "लड़का", "बेटा",
}


def _text(raw) -> str | None:
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = str(raw)
    if not isinstance(raw, str):
        return None
    if len(raw) > _MAX_INPUT_LEN:
        return None
    return unicodedata.normalize("NFC", raw).strip().lower() or None


def _words(text: str) -> list[str]:
    return [w for w in _SEPARATORS.split(text) if w]


def _build_date(year: int, month: int, day: int) -> str | None:
    # A birth date can never be in the future, so cap at the current year
    # rather than a fixed far-future bound. date.today() is the only clock
    # read; the functions stay deterministic for any given calendar day.
    if not _MIN_YEAR <= year <= date.today().year:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _compact_date(digits: str) -> str | None:
    """DDMMYYYY ("19112003") or YYYYMMDD ("20031119") typed with no separators. The two can
    never both be real dates (DDMMYYYY needs the last four digits to be a year, YYYYMMDD needs
    them to be a month and day), so at most one reading survives and nothing is guessed."""
    day_first = _build_date(int(digits[4:]), int(digits[2:4]), int(digits[:2]))
    return day_first or _build_date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))


def normalize_date(raw) -> str | None:
    """Return a birth date as YYYY-MM-DD, or None when genuinely unparseable."""
    text = _text(raw)
    if not text:
        return None

    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)

    named_month = None
    for word in _words(text):
        month = _MONTHS.get(word)
        if month and named_month and month != named_month:
            return None
        named_month = month or named_month

    nums = re.findall(r"\d+", text)

    if named_month:
        if len(nums) != 2:
            return None
        first, second = nums
        if len(first) == 4:
            return _build_date(int(first), named_month, int(second))
        if len(second) == 4:
            return _build_date(int(second), named_month, int(first))
        return None

    if len(nums) == 1 and len(nums[0]) == 8:
        return _compact_date(nums[0])

    if len(nums) != 3:
        return None
    first, second, third = nums

    # A 4-digit leading number is ISO year-month-day. Otherwise Indian users
    # write day-first, so "03/04/1990" is 3 April; month-first is tried only
    # when day-first is an impossible date, where one reading is left.
    if len(first) == 4:
        return _build_date(int(first), int(second), int(third))
    if len(third) != 4:
        return None
    year = int(third)
    return _build_date(year, int(second), int(first)) or _build_date(year, int(first), int(second))


def normalize_time(raw) -> str | None:
    """Return a birth time as 24-hour HH:MM:SS, or None when genuinely unparseable."""
    text = _text(raw)
    if not text:
        return None

    meridiem = None
    found = _MERIDIEM.search(text)
    if found:
        meridiem = found.group(1)
        text = f"{text[:found.start()]} {text[found.end():]}"

    if not meridiem:
        for word in _words(text):
            if word in _AM_WORDS:
                meridiem = "a"
                break
            if word in _PM_WORDS:
                meridiem = "p"
                break

    nums = re.findall(r"\d+", text)
    if not nums or len(nums) > 3:
        return None

    if len(nums) == 1:
        token = nums[0]
        if len(token) <= 2:
            parts = [token, "0", "0"]
        elif len(token) <= 4:
            parts = [token[:-2], token[-2:], "0"]
        else:
            return None
    else:
        parts = nums + ["0"] * (3 - len(nums))

    hour, minute, second = (int(p) for p in parts)

    if meridiem == "p" and hour < 12:
        hour += 12
    elif meridiem == "a" and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"


_UNKNOWN_TIME = re.compile(
    r"unknown|no\s*idea|not\s*known|(?:don'?t|do\s*not|didn'?t|not)\s*know"
    r"|(?<![a-z])th?eriy?a{0,2}(?:th?u|dhu|lai|la|lae|illai|illa)"
    r"|தெரியா|தெரியல|தெரியவில்லை"
    r"|pata\s*nahi|maloom\s*nahi|पता\s*नहीं|मालूम\s*नहीं"
)


def is_unknown_time(raw) -> bool:
    """True when the customer says they do not know their birth time ("theriyathu"), which is
    different from a time that is merely unreadable ("abc")."""
    text = _text(raw)
    return bool(text and _UNKNOWN_TIME.search(text))


def time_needs_meridiem(raw) -> bool:
    """True for a readable 12-hour-looking time with nothing saying AM or PM ("5:30", "1030"):
    it could be 05:30 or 17:30, and a horoscope cast for the wrong one is wrong. 24-hour
    times ("17:45", "00:15") and anything with am/pm or a day-part word are unambiguous."""
    normalized = normalize_time(raw)
    if not normalized:
        return False
    text = _text(raw) or ""
    if _MERIDIEM.search(text) or any(w in _AM_WORDS or w in _PM_WORDS for w in _words(text)):
        return False
    return 1 <= int(normalized[:2]) <= 12


def format_time_12h(normalized: str) -> str:
    """"18:00:00" -> "06:00 PM". The form we store, so the AM/PM question is settled in the data."""
    hour, minute, second = (int(p) for p in normalized.split(":"))
    shown = f"{hour % 12 or 12:02d}:{minute:02d}" + (f":{second:02d}" if second else "")
    return f"{shown} {'AM' if hour < 12 else 'PM'}"


_NOT_A_PLACE = {"idk", "na", "n/a", "none", "nil", "unknown"}


def normalize_place(raw) -> str | None:
    """The place as typed, trimmed, or None when it is not a place ("?", "idk", "theriyathu").
    No geocoding: only enough to stop a junk answer being cast as a chart."""
    text = _text(raw)
    if not text or text in _NOT_A_PLACE or _UNKNOWN_TIME.search(text):
        return None
    if sum(ch.isalpha() for ch in text) < 2:
        return None
    return unicodedata.normalize("NFC", str(raw)).strip()


def normalize_gender(raw) -> str | None:
    """Return "M" or "F", or None when unparseable — never guess."""
    # Django coerces anything that is not exactly "M"/"F" into "M", so a wrong
    # guess here silently makes every customer male. None lets the caller refuse.
    text = _text(raw)
    if not text:
        return None

    words = _words(text)
    female = any(w in _FEMALE for w in words)
    male = any(w in _MALE for w in words)
    if female == male:
        return None
    return "F" if female else "M"


def normalize_phone(raw, default_cc: str = "+91") -> str | None:
    """Return an E.164 phone number, or None when it is not a plausible number."""
    text = _text(raw)
    if not text:
        return None

    had_plus = text.startswith("+")
    cc = re.sub(r"\D", "", default_cc or "")
    digits = re.sub(r"\D", "", text).lstrip("0")
    if not cc or not digits:
        return None

    if had_plus:
        return _international_phone(digits)
    if len(digits) == 10:
        national = digits
    elif digits.startswith(cc) and len(digits) == len(cc) + 10:
        national = digits[len(cc):]
    else:
        # Partners send country code + number with no "+" (94771234567), so
        # anything that is not a national number is read as international.
        return _international_phone(digits)

    if cc == "91" and national[0] not in "6789":
        return None
    return f"+{cc}{national}"


def _international_phone(digits: str) -> str | None:
    """E.164 for country code + number, checked against that country's numbering plan."""
    try:
        number = phonenumbers.parse(f"+{digits}")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    if e164.startswith("+91") and e164[3] not in "6789":
        return None
    return e164
