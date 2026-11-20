"""Every word a WhatsApp Form shows, in English, Tamil script or Tanglish, and editable.

Nothing here is fixed wording: a language preset only fills the starting values. The client
edits any of them (stored as overrides next to the form), and an edited text always wins.
Starter forms are likewise only starting content: once created, every field, label and option
belongs to the client.

Limits are Meta's (Flow JSON components and interactive messages), checked in characters.
"""
from __future__ import annotations

LANGUAGES = ("en", "ta", "tanglish")
LANGUAGE_NAMES = {"en": "English", "ta": "தமிழ்", "tanglish": "Tanglish"}

# key -> max characters (Meta's limit for where the text is shown)
LIMITS: dict[str, int] = {
    "cta": 30,             # Services form: the button under the chat message that opens it
    "form_cta": 30,        # other forms: the same button
    "intro": 1024,         # other forms: the chat message the button sits under
    "title_choose": 30,    # screen titles
    "title_option": 30,
    "title_addons": 30,
    "title_details": 30,
    "title_confirm": 30,
    "continue": 35,        # Footer button
    "submit": 35,
    "choose_label": 30,    # radio group label on the first screen
    "addons_label": 30,
    "confirm_note": 4096,  # text on the last screen of the Services form
    "form_note": 4096,     # text on the last screen of other forms
    "consent": 120,        # the optional offers opt-in
    "total": 30,           # chat confirmation after a Services form
    "incl_gst": 30,
    "pay_note": 300,
    "pay_button": 20,      # URL button title; "{amount}" is filled in
    "thank_you": 1000,     # chat message after other forms
    # live forms (Phase 4): product order form
    "title_search": 30,
    "search_label": 20,
    "no_results": 30,      # shown as the only choice when a search finds nothing
    "title_products": 30,
    "products_label": 30,
    "title_quantity": 30,
    "title_delivery": 30,
    "name_label": 20,
    "address_label": 20,
    "title_summary": 30,
    "summary_note": 4096,
    # live forms (Phase 4): appointment booking
    "title_date": 30,
    "date_label": 20,
    "no_slots": 30,        # shown as the only date when everything is booked
    "title_slot": 30,
    "slot_label": 30,
    "title_full": 30,
    "full_note": 4096,
    "booked_message": 1000,  # chat message after booking; {slot} is the booked time
    "slot_taken": 1000,      # chat message when the slot filled before they submitted
}

PRESETS: dict[str, dict[str, str]] = {
    "en": {
        "cta": "Choose & book",
        "form_cta": "Fill the form",
        "intro": "Please fill this short form 👇",
        "title_choose": "Choose",
        "title_option": "Choose option",
        "title_addons": "Add-ons",
        "title_details": "Your details",
        "title_confirm": "Confirm",
        "continue": "Continue",
        "submit": "Submit",
        "choose_label": "Choose one",
        "addons_label": "Add-ons (optional)",
        "confirm_note": "Tap Submit. We'll reply in this chat with your total and payment link.",
        "form_note": "Tap Submit to send your answers.",
        "consent": "Send me updates and offers on WhatsApp",
        "total": "Total",
        "incl_gst": "incl. GST",
        "pay_note": "Tap below to pay.",
        "pay_button": "Pay {amount}",
        "thank_you": "Thanks! We've got your details and will get back to you soon.",
        "title_search": "Find a product",
        "search_label": "Search products",
        "no_results": "No match. Try another word",
        "title_products": "Choose products",
        "products_label": "Choose what you want",
        "title_quantity": "How many?",
        "title_delivery": "Delivery details",
        "name_label": "Your name",
        "address_label": "Delivery address",
        "title_summary": "Your order",
        "summary_note": "Tap Submit and we'll send the payment link in this chat.",
        "title_date": "Pick a date",
        "date_label": "Date",
        "no_slots": "No free dates right now",
        "title_slot": "Pick a time",
        "slot_label": "Free times",
        "title_full": "Fully booked",
        "full_note": "All times are booked for now. Tap Submit and we'll get back to you in this chat.",
        "booked_message": "✅ Booked for {slot}. See you then!",
        "slot_taken": "Sorry, that time just got booked. Please open the form again and pick another time.",
    },
    "ta": {
        "cta": "தேர்வு செய்து பதிவு செய்ய",
        "form_cta": "படிவத்தை நிரப்ப",
        "intro": "இந்த சிறிய படிவத்தை நிரப்புங்கள் 👇",
        "title_choose": "தேர்வு செய்க",
        "title_option": "வகையைத் தேர்வு செய்க",
        "title_addons": "கூடுதல் சேவைகள்",
        "title_details": "உங்கள் விவரங்கள்",
        "title_confirm": "உறுதிசெய்க",
        "continue": "தொடரவும்",
        "submit": "சமர்ப்பிக்கவும்",
        "choose_label": "ஒன்றைத் தேர்வு செய்யவும்",
        "addons_label": "கூடுதல் (விருப்பத்தேர்வு)",
        "confirm_note": "சமர்ப்பிக்கவும் என்பதை அழுத்துங்கள். மொத்தத் தொகையும் பணம் செலுத்தும் இணைப்பும் இந்த உரையாடலில் அனுப்பப்படும்.",
        "form_note": "சமர்ப்பிக்கவும் என்பதை அழுத்தி உங்கள் பதில்களை அனுப்புங்கள்.",
        "consent": "WhatsApp-ல் புதிய தகவல்களும் சலுகைகளும் எனக்கு அனுப்பவும்",
        "total": "மொத்தம்",
        "incl_gst": "GST உட்பட",
        "pay_note": "கீழே உள்ள பொத்தானை அழுத்தி பணம் செலுத்துங்கள்.",
        "pay_button": "{amount} செலுத்த",
        "thank_you": "நன்றி! உங்கள் விவரங்கள் கிடைத்தன. விரைவில் உங்களைத் தொடர்பு கொள்கிறோம்.",
        "title_search": "பொருளைத் தேடுக",
        "search_label": "பொருளைத் தேடுங்கள்",
        "no_results": "எதுவும் கிடைக்கவில்லை",
        "title_products": "பொருட்களைத் தேர்வு செய்க",
        "products_label": "வேண்டியதைத் தேர்வு செய்க",
        "title_quantity": "எத்தனை வேண்டும்?",
        "title_delivery": "டெலிவரி விவரங்கள்",
        "name_label": "உங்கள் பெயர்",
        "address_label": "டெலிவரி முகவரி",
        "title_summary": "உங்கள் ஆர்டர்",
        "summary_note": "சமர்ப்பிக்கவும் என்பதை அழுத்துங்கள். பணம் செலுத்தும் இணைப்பை இந்த உரையாடலில் அனுப்புவோம்.",
        "title_date": "தேதியைத் தேர்வு செய்க",
        "date_label": "தேதி",
        "no_slots": "இப்போது நேரம் காலியில்லை",
        "title_slot": "நேரத்தைத் தேர்வு செய்க",
        "slot_label": "காலியான நேரங்கள்",
        "title_full": "அனைத்தும் நிரம்பியது",
        "full_note": "இப்போது எல்லா நேரங்களும் நிரம்பியுள்ளன. சமர்ப்பிக்கவும்; இந்த உரையாடலில் உங்களைத் தொடர்பு கொள்கிறோம்.",
        "booked_message": "✅ {slot} நேரத்துக்குப் பதிவு செய்யப்பட்டது. சந்திப்போம்!",
        "slot_taken": "மன்னிக்கவும், அந்த நேரம் இப்போதுதான் நிரம்பியது. படிவத்தை மீண்டும் திறந்து வேறு நேரத்தைத் தேர்வு செய்யுங்கள்.",
    },
    "tanglish": {
        "cta": "Choose panni book pannunga",
        "form_cta": "Form fill pannunga",
        "intro": "Indha chinna form-a fill pannunga 👇",
        "title_choose": "Choose pannunga",
        "title_option": "Option choose pannunga",
        "title_addons": "Add-ons",
        "title_details": "Unga details",
        "title_confirm": "Confirm pannunga",
        "continue": "Continue pannunga",
        "submit": "Submit pannunga",
        "choose_label": "Onnu choose pannunga",
        "addons_label": "Add-ons (venumna mattum)",
        "confirm_note": "Submit pannunga. Total amount-um payment link-um indha chat-la anuppuvom.",
        "form_note": "Submit panni unga answers-a anuppunga.",
        "consent": "WhatsApp-la updates, offers enakku anuppunga",
        "total": "Total",
        "incl_gst": "GST serthu",
        "pay_note": "Keela irukura button-a press panni pay pannunga.",
        "pay_button": "Pay {amount}",
        "thank_you": "Nandri! Unga details kidaichiduchu. Seekiram ungala contact pannuvom.",
        "title_search": "Product thedunga",
        "search_label": "Product search",
        "no_results": "Onnum kidaikala, vera word try",
        "title_products": "Products choose pannunga",
        "products_label": "Venumnadha choose pannunga",
        "title_quantity": "Evvalavu venum?",
        "title_delivery": "Delivery details",
        "name_label": "Unga peyar",
        "address_label": "Delivery address",
        "title_summary": "Unga order",
        "summary_note": "Submit pannunga, payment link indha chat-la anuppuvom.",
        "title_date": "Date choose pannunga",
        "date_label": "Date",
        "no_slots": "Ippo free date illa",
        "title_slot": "Time choose pannunga",
        "slot_label": "Free time slots",
        "title_full": "Ellam full aayiduchu",
        "full_note": "Ippo ella time-um full. Submit pannunga, indha chat-la ungala contact pannuvom.",
        "booked_message": "✅ {slot}-ku book aayiduchu. Paakalaam!",
        "slot_taken": "Sorry, andha time ippo dhaan full aayiduchu. Form-a thirumba open panni vera time choose pannunga.",
    },
}

AMOUNT_SAMPLE = "₹99,99,999"  # the longest amount a pay button must still fit
_MULTILINE = frozenset({"confirm_note", "form_note", "pay_note", "thank_you", "intro", "summary_note",
                        "full_note", "booked_message", "slot_taken"})


def language_of(settings: dict | None) -> str:
    lang = (settings or {}).get("language")
    return lang if lang in LANGUAGES else "en"


def resolve(settings: dict | None) -> dict[str, str]:
    """The texts a form shows: the language preset with the client's edits on top.
    settings = {"language": "en" | "ta" | "tanglish", "texts": {key: edited text}}."""
    texts = dict(PRESETS[language_of(settings)])
    for key, value in ((settings or {}).get("texts") or {}).items():
        if key in LIMITS and isinstance(value, str) and value.strip():
            texts[key] = value.strip() if key in _MULTILINE else " ".join(value.split())
    return texts


def problems(settings: dict | None) -> list[str]:
    """Edits that WhatsApp can't show, in plain words. Empty = fine."""
    out: list[str] = []
    raw = (settings or {}).get("texts") or {}
    if not isinstance(raw, dict):
        return ["Texts must be a list of edits."]
    if (settings or {}).get("language") not in (None, *LANGUAGES):
        out.append("Pick English, Tamil or Tanglish.")
    for key, value in raw.items():
        if key not in LIMITS:
            out.append(f"Unknown text '{key}'.")
            continue
        if not isinstance(value, str):
            out.append(f"'{key}' must be text.")
            continue
        text = value.strip()
        if not text:
            continue  # blank = use the language's starting text
        shown = text.replace("{amount}", AMOUNT_SAMPLE) if key == "pay_button" else text
        if len(shown) > LIMITS[key]:
            extra = " (with the amount filled in)" if key == "pay_button" else ""
            out.append(f"'{text[:40]}' is too long{extra}: WhatsApp shows at most {LIMITS[key]} characters there.")
        if key in ("cta", "form_cta") and any(ord(ch) > 0xFFFF for ch in text):
            out.append("The form button can't have emoji.")
    return out


# ── starter forms (only starting content; every part is editable after creating) ──

FIELD_TYPES = ("text", "long_text", "email", "phone", "number", "date", "dropdown", "single", "multi")
# Meta label limits per input (Flow JSON components).
LABEL_LIMITS = {"text": 20, "long_text": 20, "email": 20, "phone": 20, "number": 20, "date": 40,
                "dropdown": 20, "single": 30, "multi": 30}
OPTION_LIMIT = 30
MAX_OPTIONS = {"dropdown": 200, "single": 20, "multi": 20}
MAX_FIELDS = 40


def _f(key: str, type_: str, labels: tuple[str, str, str], options: tuple[list[str], list[str], list[str]] | None = None,
       required: bool = True) -> dict:
    return {"key": key, "type": type_, "required": required, "labels": labels, "options": options}


_TIMES = (["Morning", "Afternoon", "Evening"], ["காலை", "மதியம்", "மாலை"], ["Kaalai", "Madhiyam", "Maalai"])

STARTERS: dict[str, dict] = {
    "lead_enquiry": {
        "names": ("Lead enquiry", "விசாரணை", "Enquiry"),
        "fields": [
            _f("full_name", "text", ("Full name", "முழுப் பெயர்", "Unga peyar")),
            _f("city", "text", ("City", "ஊர்", "Unga ooru")),
            _f("need", "long_text", ("What do you need?", "என்ன தேவை?", "Enna venum?")),
            _f("call_time", "single", ("Best time to call", "அழைக்க சரியான நேரம்", "Call panna best time"), _TIMES),
        ],
    },
    "appointment": {
        "names": ("Appointment request", "சந்திப்பு முன்பதிவு", "Appointment"),
        "fields": [
            _f("full_name", "text", ("Full name", "முழுப் பெயர்", "Unga peyar")),
            _f("date", "date", ("Preferred date", "விரும்பும் தேதி", "Endha date venum")),
            _f("slot", "single", ("Preferred time", "விரும்பும் நேரம்", "Endha time venum"), _TIMES),
            _f("reason", "long_text", ("Reason", "காரணம்", "Enna vishayam"), required=False),
        ],
    },
    "feedback": {
        "names": ("Feedback", "கருத்து", "Feedback"),
        "fields": [
            _f("rating", "single", ("How was it?", "எப்படி இருந்தது?", "Eppadi irundhuchu?"), (
                ["Excellent", "Good", "Okay", "Poor"], ["மிக நன்று", "நன்று", "பரவாயில்லை", "மோசம்"],
                ["Romba nalla irundhuchu", "Nalla irundhuchu", "Paravalla", "Nalla illa"])),
            _f("liked", "long_text", ("What did you like?", "எது பிடித்தது?", "Enna pidichuchu?"), required=False),
            _f("improve", "long_text", ("What can we improve", "எதை மேம்படுத்தலாம்?", "Enna improve panna?"), required=False),
        ],
    },
    "admission": {
        "names": ("Course / admission enquiry", "சேர்க்கை விசாரணை", "Admission enquiry"),
        "fields": [
            _f("student_name", "text", ("Student name", "மாணவர் பெயர்", "Student peyar")),
            _f("course", "text", ("Course / class", "படிப்பு / வகுப்பு", "Course / class")),
            _f("city", "text", ("City", "ஊர்", "Unga ooru")),
            _f("batch", "single", ("Preferred batch", "விரும்பும் பேட்ச்", "Endha batch venum"), (
                ["Morning", "Evening", "Weekend"], ["காலை", "மாலை", "வார இறுதி"], ["Kaalai", "Maalai", "Weekend"])),
        ],
    },
}


def starter(name: str, language: str) -> dict:
    """A new form's starting content in the chosen language (then fully editable)."""
    spec = STARTERS[name]
    index = LANGUAGES.index(language if language in LANGUAGES else "en")
    return {
        "name": spec["names"][index],
        "language": LANGUAGES[index],
        "fields": [
            {"key": f["key"], "type": f["type"], "required": f["required"], "label": f["labels"][index],
             "options": list(f["options"][index]) if f["options"] else []}
            for f in spec["fields"]
        ],
        "texts": {},
    }


def field_problems(fields: list) -> list[str]:
    """What WhatsApp can't show in a form's fields, in plain words."""
    import re

    out: list[str] = []
    if not isinstance(fields, list) or not fields:
        return ["Add at least one question."]
    if len(fields) > MAX_FIELDS:
        out.append(f"A form can have at most {MAX_FIELDS} questions.")
    keys: set[str] = set()
    labels: set[str] = set()
    for number, f in enumerate(fields, 1):
        if not isinstance(f, dict):
            out.append(f"Question {number} is not valid.")
            continue
        label = str(f.get("label") or "").strip()
        type_ = f.get("type")
        key = str(f.get("key") or "")
        if type_ not in FIELD_TYPES:
            out.append(f"Question {number}: pick a question type.")
            continue
        if not label:
            out.append(f"Question {number} needs a question.")
        elif label.casefold() in labels:
            # Answers are shown and exported by question, so two equal questions would overwrite each other.
            out.append(f"Two questions both say '{label[:30]}'. Make them different, e.g. 'Student name' and 'Parent name'.")
        elif len(label) > LABEL_LIMITS[type_]:
            out.append(f"'{label[:30]}' is too long: WhatsApp shows at most {LABEL_LIMITS[type_]} characters for this type.")
        if label:
            labels.add(label.casefold())
        if not re.fullmatch(r"[a-z0-9_]{1,40}", key):
            out.append(f"Question {number} has an invalid key.")
        elif key in keys:
            out.append(f"Two questions share the key '{key}'.")
        keys.add(key)
        if type_ in MAX_OPTIONS:
            options = [str(o).strip() for o in f.get("options") or [] if str(o).strip()]
            if len(options) < (2 if type_ != "dropdown" else 1):
                out.append(f"'{label[:30] or number}' needs at least {2 if type_ != 'dropdown' else 1} options.")
            if len(options) > MAX_OPTIONS[type_]:
                out.append(f"'{label[:30] or number}' can have at most {MAX_OPTIONS[type_]} options.")
            if len({o.lower() for o in options}) != len(options):
                out.append(f"'{label[:30] or number}' has the same option twice.")
            long = [o for o in options if len(o) > OPTION_LIMIT]
            if long:
                out.append(f"Option '{long[0][:30]}' is too long: at most {OPTION_LIMIT} characters.")
    return out
