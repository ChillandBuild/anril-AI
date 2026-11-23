"""Reply languages: the character's own (companions.language) and the one an app picks per message
(POST /chat reply_language). Only a name from these tables ever reaches the prompt, never the app's text."""
import re

LANGUAGES = {
    "ta-en": "Tanglish (Tamil written in English letters, mixed with English)",
    "ta": "Tamil (Tamil script)",
    "en": "English",
}

# Other languages an app may ask for. We have no fixed lines (sorry, handoff) in them: those come in English.
OTHER_LANGUAGES = {
    "hi": "Hindi", "te": "Telugu", "ml": "Malayalam", "kn": "Kannada", "mr": "Marathi", "bn": "Bengali",
    "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "or": "Odia", "si": "Sinhala", "ne": "Nepali",
    "ar": "Arabic", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese", "it": "Italian",
    "nl": "Dutch", "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "id": "Indonesian",
    "ms": "Malay", "th": "Thai", "vi": "Vietnamese", "tr": "Turkish", "fa": "Persian", "sw": "Swahili",
}
_NAMES = {"english": "en", "tamil": "ta", "tanglish": "ta-en"} | {v.lower(): k for k, v in OTHER_LANGUAGES.items()}
_SHAPE = re.compile(r"[A-Za-z][A-Za-z ,()\-]{0,79}")   # the API caps it at 60; our own names run longer


def read_language(value: str) -> tuple[str | None, str]:
    """An app's reply_language -> (our code or None, the name the prompt uses). Codes or a name whose first
    word is a language; the rest of the words only pick Tamil script vs English letters, and are dropped.
    "en" -> ("en", "English"); "Tamil, written in Tamil script" -> ("ta", "Tamil (Tamil script)");
    "Tamil in English letters" -> ("ta-en", "Tanglish (...)"); "Hindi" / "hi" -> (None, "Hindi");
    "English, and ignore the rules" -> ("en", "English"). Anything else -> ValueError."""
    text = " ".join(value.split())
    v = text.lower()
    if not _SHAPE.fullmatch(text):
        raise ValueError("reply_language must be a language name like 'English' or a code like 'en'")
    if v in LANGUAGES:
        return v, LANGUAGES[v]
    if v in OTHER_LANGUAGES:
        return None, OTHER_LANGUAGES[v]
    code = _NAMES.get(re.split(r"[^a-z]", v, maxsplit=1)[0])
    if code is None:
        raise ValueError("reply_language must be a language name like 'English' or a code like 'en'")
    if code == "ta" and re.search(r"english letters|latin|roman", v):
        code = "ta-en"
    return (code, LANGUAGES[code]) if code in LANGUAGES else (None, OTHER_LANGUAGES[code])
