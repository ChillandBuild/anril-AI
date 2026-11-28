"""Excel upload for WhatsApp templates: read a strict sheet, check every row, send the chosen ones.

The sheet must use the sample file's columns, in its order (COLUMNS). One row is one template:
name, type, language, an optional text header (+ its example), the body, one example per {{n}}
in the body, an optional footer and up to three buttons (link, call or quick reply). Picture,
video and document headers need a file, so those templates are made in the builder.

After the upload the rows open in a review screen where the owner can edit or remove any of them;
edited rows come back through check_rows again (POST /bulk/recheck), and only the rows they tick
are sent (POST /bulk/submit). The checks reuse the builder's Meta rules (services/template_rules.py)
and a send goes through the same create path as one template made by hand.

Pure helpers live here; the route (routes/templates.py) supplies the existing rows and the
function that really creates one template.
"""
import io
from itertools import islice
import re
from typing import Awaitable, Callable

from app.services import template_rules

MAX_ROWS = 50
_MAX_SCAN_LINES = 1 + 1000  # header + lines looked at (blank lines are skipped)
BODY_MAX = 1024
HEADER_MAX = 60
FOOTER_MAX = 60
BUTTON_TEXT_MAX = 25
EXAMPLES = 5  # Example {{1}} .. Example {{5}}
BUTTONS = 3

LANGUAGE_BY_NAME = {
    "english": "en", "tamil": "ta", "hindi": "hi", "telugu": "te", "kannada": "kn", "malayalam": "ml",
}
LANGUAGE_LABEL = {"en": "English", "ta": "Tamil", "hi": "Hindi", "te": "Telugu", "kn": "Kannada", "ml": "Malayalam"}
_LANGUAGE_CODES = {"en", "en_US", "en_IN", "hi", "kn", "ml", "ta", "te"}
_LANGUAGE_HELP = "English, Tamil, Hindi, Telugu, Kannada or Malayalam"
_CATEGORY = {"marketing": "MARKETING", "utility": "UTILITY"}
_BUTTON_KIND = {
    "link": "URL", "website": "URL", "url": "URL",
    "call": "PHONE_NUMBER", "phone": "PHONE_NUMBER", "call us": "PHONE_NUMBER",
    "quick reply": "QUICK_REPLY", "reply": "QUICK_REPLY", "quick_reply": "QUICK_REPLY",
}
BUTTON_KIND_LABEL = {"URL": "Link", "PHONE_NUMBER": "Call", "QUICK_REPLY": "Quick reply"}
_NAME_OK = re.compile(r"^[a-z0-9_]{1,512}$")
BUILDER_TEXT = "Make this one in the builder."

# The sample file's columns, in order. The upload must match these titles exactly (case and extra
# spaces don't matter), so a moved or renamed column is caught instead of filling the wrong field.
COLUMNS: list[tuple[str, str]] = (
    [("Template name", "name"), ("Type", "type"), ("Language", "language"),
     ("Header", "header"), ("Header example", "header_example"), ("Body", "body")]
    + [(f"Example {{{{{i}}}}}", f"example_{i}") for i in range(1, EXAMPLES + 1)]
    + [("Footer", "footer")]
    + [c for i in range(1, BUTTONS + 1)
       for c in ((f"Button {i} type", f"button_{i}_type"), (f"Button {i} text", f"button_{i}_text"),
                 (f"Button {i} link or phone", f"button_{i}_value"))]
)
REQUIRED = ("Template name", "Type", "Language", "Body")


class BulkFileError(ValueError):
    """The file itself can't be used (not an .xlsx, wrong columns, too many rows). The route turns it into a 422."""


def _cell(value) -> str:
    return "" if value is None else str(value).strip()


def _title(value) -> str:
    return " ".join(_cell(value).lower().split())


def _column_letter(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _check_titles(titles: tuple) -> None:
    for i, (want, _field) in enumerate(COLUMNS):
        got = titles[i] if i < len(titles) else None
        if _title(got) != _title(want):
            seen = f" It says '{_cell(got)}'." if _cell(got) else " It is empty."
            raise BulkFileError(
                f"Column {_column_letter(i)} must be '{want}'.{seen} Download the sample file again and copy your rows into it."
            )
    extra = [i for i in range(len(COLUMNS), len(titles)) if _cell(titles[i])]
    if extra:
        raise BulkFileError(
            f"Column {_column_letter(extra[0])} ('{_cell(titles[extra[0]])}') isn't in the sample file. "
            "Remove it, or download the sample file again."
        )


def _row_from_cells(values: tuple) -> dict:
    flat = {field: (_cell(values[i]) if i < len(values) else "") for i, (_t, field) in enumerate(COLUMNS)}
    return {
        "name": flat["name"],
        "type": flat["type"],
        "language": flat["language"],
        "header": flat["header"],
        "header_example": flat["header_example"],
        "body": flat["body"],
        "examples": [flat[f"example_{i}"] for i in range(1, EXAMPLES + 1)],
        "footer": flat["footer"],
        "buttons": [
            {"type": flat[f"button_{i}_type"], "text": flat[f"button_{i}_text"], "value": flat[f"button_{i}_value"]}
            for i in range(1, BUTTONS + 1)
        ],
    }


def _is_blank(row: dict) -> bool:
    return not any(
        [row["name"], row["type"], row["language"], row["header"], row["header_example"], row["body"], row["footer"],
         *row["examples"], *(b["type"] or b["text"] or b["value"] for b in row["buttons"])]
    )


def parse_workbook(content: bytes) -> list[dict]:
    """Rows of the first sheet, each {row, name, type, language, header, header_example, body,
    examples[5], footer, buttons[3]}. Raises BulkFileError when the sheet isn't the sample's layout."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:
        raise BulkFileError("That doesn't look like an Excel (.xlsx) file. Download the sample file and fill it in.") from e
    try:
        sheet = wb.worksheets[0]
        # Never read a huge sheet into memory: the header, 50 templates and room for blank lines is plenty.
        raw = list(islice(sheet.iter_rows(values_only=True), _MAX_SCAN_LINES))
    finally:
        wb.close()
    if not raw:
        raise BulkFileError("The file is empty. Download the sample file and fill it in.")
    _check_titles(raw[0])

    rows = []
    for number, values in enumerate(raw[1:], start=2):
        row = _row_from_cells(values)
        if _is_blank(row):
            continue
        row["row"] = number  # the spreadsheet line, so "row 4" matches what they see
        rows.append(row)
    if not rows:
        raise BulkFileError("No templates found in the file. Fill in the rows under the column titles.")
    if len(rows) > MAX_ROWS:
        raise BulkFileError(f"Upload at most {MAX_ROWS} templates at a time. This file has {len(rows)}.")
    return rows


def _clean_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", raw.strip().lower()).strip("_")


def language_code(raw: str) -> str | None:
    text = (raw or "").strip()
    if text in _LANGUAGE_CODES:
        return text
    return LANGUAGE_BY_NAME.get(text.lower())


def category_code(raw: str) -> str | None:
    return _CATEGORY.get((raw or "").strip().lower())


def button_kind(raw: str) -> str | None:
    text = (raw or "").strip()
    if text in BUTTON_KIND_LABEL:
        return text
    return _BUTTON_KIND.get(" ".join(text.lower().split()))


def split_phone(raw: str) -> tuple[str, str] | None:
    """'+91 98765 43210', '+919876543210' or '9876543210' -> ('+91', '9876543210'); None when unclear.
    Meta wants the country code apart from the number."""
    text = (raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if text.startswith("+"):
        parts = text[1:].split()
        if len(parts) > 1 and parts[0].isdigit() and 1 <= len(parts[0]) <= 3:
            rest = "".join(re.sub(r"\D", "", p) for p in parts[1:])
            return (f"+{parts[0]}", rest) if 6 <= len(rest) <= 13 else None
        if digits.startswith("91") and len(digits) == 12:
            return "+91", digits[2:]
        return None
    if len(digits) == 10:
        return "+91", digits  # a bare Indian mobile number
    if digits.startswith("91") and len(digits) == 12:
        return "+91", digits[2:]
    return None


def _has_emoji(text: str) -> bool:
    from app.services.meta_cloud import _strip_emojis
    return _strip_emojis(text) != text


def _existing_index(existing: list[dict]) -> tuple[set[tuple[str, str]], set[str], list[dict]]:
    pairs = {((e.get("name") or ""), (e.get("language") or "")) for e in existing}
    return pairs, {(e.get("name") or "") for e in existing}, existing


def _examples(raw: dict) -> list[str]:
    given = raw.get("examples")
    vals = [_cell(v) for v in given] if isinstance(given, list) else []
    return (vals + [""] * EXAMPLES)[:EXAMPLES]


def _buttons(raw: dict) -> list[dict]:
    given = raw.get("buttons")
    out = []
    for b in (given if isinstance(given, list) else [])[:BUTTONS]:
        b = b if isinstance(b, dict) else {}
        out.append({"type": _cell(b.get("type")), "text": _cell(b.get("text")), "value": _cell(b.get("value"))})
    return out + [{"type": "", "text": "", "value": ""}] * (BUTTONS - len(out))


def check_rows(rows: list[dict], existing: list[dict]) -> list[dict]:
    """One verdict per row. `existing` = this account's templates (name, language, body_text, footer_text).

    status: ready | need_fix | exists (same name and language: skipped) | update (same name and language,
    row sent with action "update" and no problems: it edits the existing template).
    issues: [{field, text}] so the review screen can mark the field; problems: the same texts as a list.
    Fields: name, type, language, header, header_example, body, example_1..5, footer, button_1..3.
    """
    pairs, names, existing_rows = _existing_index(existing)
    seen_in_file: dict[tuple[str, str], int] = {}
    out = []
    for raw in rows:
        issues: list[dict] = []

        def add(field: str, text: str) -> None:
            issues.append({"field": field, "text": text})

        # name, type, language
        name_raw = _cell(raw.get("name"))
        name = _clean_name(name_raw)
        if not name_raw:
            add("name", "Template name is empty.")
        elif name_raw != name or not _NAME_OK.match(name):
            add("name", f"Name: small letters, numbers and _ only -> {name or 'festival_offer'}")

        type_raw = _cell(raw.get("type"))
        category = category_code(type_raw) or (type_raw.upper() if type_raw.upper() in ("MARKETING", "UTILITY") else None)
        if category is None:
            if type_raw.lower() == "authentication":
                add("type", f"OTP templates can't be uploaded. {BUILDER_TEXT}")
            else:
                add("type", "Type must be Marketing or Utility.")

        lang_raw = _cell(raw.get("language"))
        language = language_code(lang_raw)
        if language is None:
            add("language", f"Unknown language{' ' + repr(lang_raw) if lang_raw else ''}. Use {_LANGUAGE_HELP}.")

        # header (text only) + its example
        header = _cell(raw.get("header"))
        header_example = _cell(raw.get("header_example"))
        if header:
            if len(header) > HEADER_MAX:
                add("header", f"Header is too long ({len(header)} of {HEADER_MAX} characters).")
            if _has_emoji(header):
                add("header", "Emojis aren't allowed in the header.")
            for p in template_rules.header_problems(header):
                add("header", p)
            if template_rules.variable_indices(header) and not header_example:
                add("header_example", "The header's {{1}} has no example.")

        # body + one example per variable
        body = _cell(raw.get("body"))
        examples = _examples(raw)
        if not body:
            add("body", "Body is empty.")
        else:
            if len(body) > BODY_MAX:
                add("body", f"Body is too long ({len(body)} of {BODY_MAX} characters).")
            for p in template_rules.body_problems(body):
                add("body", p)
            for idx in template_rules.variable_indices(body):
                if idx > EXAMPLES:
                    add("body", f"Excel holds examples for {{{{1}}}} to {{{{{EXAMPLES}}}}} only. {BUILDER_TEXT}")
                    break
                if not examples[idx - 1]:
                    add(f"example_{idx}", "{{" + str(idx) + "}} has no example")

        # footer
        footer = _cell(raw.get("footer"))
        for p in template_rules.footer_problems(footer):
            add("footer", p)
        if len(footer) > FOOTER_MAX:
            add("footer", f"Footer is too long ({len(footer)} of {FOOTER_MAX} characters).")

        # buttons: up to 3, link / call / quick reply
        buttons = _buttons(raw)
        kinds: list[str] = []
        texts: set[str] = set()
        clean_buttons: list[dict] = []
        for i, b in enumerate(buttons, start=1):
            if not (b["type"] or b["text"] or b["value"]):
                continue
            field = f"button_{i}"
            kind = button_kind(b["type"])
            if kind is None:
                add(field, f"Button {i} type must be Link, Call or Quick reply.")
                continue
            if not b["text"]:
                add(field, f"Button {i} needs its text.")
            elif len(b["text"]) > BUTTON_TEXT_MAX:
                add(field, f"Button {i} text is too long ({len(b['text'])} of {BUTTON_TEXT_MAX} characters).")
            elif b["text"].lower() in texts:
                add(field, f"Button {i} has the same text as another button.")
            texts.add(b["text"].lower())
            if kind == "URL":
                if not b["value"]:
                    add(field, f"Button {i} needs its link.")
                elif template_rules.VAR_RE.search(b["value"]):
                    add(field, f"Button {i} link has a {{{{1}}}} blank. {BUILDER_TEXT}")
                else:
                    for p in template_rules.url_problems(b["value"]):
                        add(field, p)
            elif kind == "PHONE_NUMBER":
                if not split_phone(b["value"]):
                    add(field, f"Button {i} needs a phone number with country code, like +91 98765 43210.")
            kinds.append(kind)
            clean_buttons.append({"type": kind, "text": b["text"], "value": b["value"] if kind != "QUICK_REPLY" else ""})
        if kinds.count("URL") > 2:
            add("button_1", "At most 2 link buttons.")
        if kinds.count("PHONE_NUMBER") > 1:
            add("button_1", "At most 1 call button.")
        groups = [k == "QUICK_REPLY" for k in kinds]
        if sum(1 for a, b in zip(groups, groups[1:]) if a != b) > 1:
            add("button_1", "Keep the quick reply buttons next to each other (Meta's rule).")

        verdict = {
            "row": raw.get("row"),
            # As typed: a row sent back unedited must fail the name check again, not pass as the cleaned name
            "name": name_raw,
            "type": category,
            "language": language,
            "header": header,
            "header_example": header_example,
            "body": body,
            "examples": examples,
            "footer": footer,
            "buttons": clean_buttons,
        }

        match = None
        if language is not None and name and (name, language) in pairs:
            match = next(e for e in existing_rows if e.get("name") == name and e.get("language") == language)
            verdict["existing_id"] = match.get("id")
            verdict["existing_status"] = match.get("status")
            verdict["existing_type"] = match.get("category")
            verdict["existing_header_media"] = match.get("header_media_type")
            verdict["existing_reached_meta"] = bool(match.get("meta_template_id"))
        updating = match is not None and _cell(raw.get("action")).lower() == "update"
        if match is not None and not updating:
            verdict["status"] = "exists"
            issues = [{"field": "name", "text": "Already on your account. Skipped."}]
        else:
            if language is not None and name:
                key = (name, language)
                if key in seen_in_file:
                    add("name", f"Same name and language as row {seen_in_file[key]}.")
                else:
                    seen_in_file[key] = raw.get("row")
                if name in names and not updating:
                    add("name", "A template with this name already exists in another language. Pick a different name.")
            if body and not issues:
                twin = next(
                    (e for e in existing_rows
                     if (e.get("body_text") or "") == body
                     and (e.get("footer_text") or "").strip() == footer and e.get("name") != name),
                    None,
                )
                if twin:
                    add("body", f"Template '{twin.get('name')}' already has this exact body and footer. "
                                "Meta rejects duplicates, so change the wording.")
            verdict["status"] = "need_fix" if issues else ("update" if updating else "ready")
            if updating:
                verdict["action"] = "update"
        verdict["issues"] = issues
        verdict["problems"] = [i["text"] for i in issues]
        out.append(verdict)
    return out


def to_payload(verdict: dict) -> dict:
    """Arguments for routes.templates.CreateTemplate from a ready row."""
    used = template_rules.variable_indices(verdict["body"])
    payload: dict = {
        "name": verdict["name"],
        "category": verdict["type"],
        "language": verdict["language"],
        "body_text": verdict["body"],
        "body_examples": verdict["examples"][: len(used)] or None,
    }
    if verdict.get("header"):
        payload["header_text"] = verdict["header"]
        if template_rules.variable_indices(verdict["header"]):
            payload["header_example"] = verdict["header_example"]
    if verdict.get("footer"):
        payload["footer_text"] = verdict["footer"]
    buttons = []
    for b in verdict.get("buttons") or []:
        if b["type"] == "URL":
            buttons.append({"type": "URL", "text": b["text"], "url": b["value"]})
        elif b["type"] == "PHONE_NUMBER":
            country, number = split_phone(b["value"]) or ("+91", b["value"])
            buttons.append({"type": "PHONE_NUMBER", "text": b["text"], "phone": number, "country": country})
        else:
            buttons.append({"type": "QUICK_REPLY", "text": b["text"]})
    if buttons:
        payload["buttons"] = buttons
    return payload


def to_update_payload(verdict: dict) -> dict:
    """Arguments for routes.templates.UpdateTemplate from an "update" row: no name, language or category."""
    full = to_payload(verdict)
    keys = ("body_text", "body_examples", "header_example")
    out = {k: full[k] for k in keys if k in full}
    # A missing field means "keep what's there" on an edit, so a blank cell is sent as an explicit clear.
    out["header_text"] = full.get("header_text", "")
    out["footer_text"] = full.get("footer_text", "")
    out["buttons"] = full.get("buttons", [])
    return out


CreateFn = Callable[[dict], Awaitable[dict]]
UpdateFn = Callable[[str, dict], Awaitable[dict]]
_EDITABLE = ("APPROVED", "REJECTED", "PAUSED")


def _reason(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):  # a pydantic validation error: its own plain messages
        try:
            return "; ".join(str(e.get("msg", "")).removeprefix("Value error, ") for e in errors()) or str(exc)
        except Exception:
            pass
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, list):
        return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    return str(exc) or "Couldn't send this template."


async def submit_rows(rows: list[dict], existing: list[dict], create: CreateFn, update: UpdateFn | None = None) -> list[dict]:
    """Re-check every row the owner ticked, then create the ready ones one after another.

    Returns one result per row: {row, name, language, status: sent | updated | refused | skipped, reason?, note?}.
    Sequential on purpose: Meta rate-limits template creation and each send changes what "exists" means.
    """
    verdicts = check_rows(rows, existing)
    results = []
    created: list[dict] = []
    for v in verdicts:
        base = {"row": v["row"], "name": v["name"], "language": v["language"]}
        if v["status"] == "update" and update is not None:
            if v.get("existing_reached_meta") and (v.get("existing_status") or "").upper() not in _EDITABLE:
                results.append({**base, "status": "refused",
                                "reason": "Meta is still reviewing this template, so it can't be changed yet."})
                continue
            payload = to_update_payload(v)
            media = (v.get("existing_header_media") or "NONE").upper() != "NONE"
            if media:  # the sheet only holds text headers: a picture/video header stays as it is
                payload.pop("header_text", None)
            try:
                await update(v["existing_id"], payload)
            except Exception as e:
                results.append({**base, "status": "refused", "reason": _reason(e)})
                continue
            result = {**base, "status": "updated"}
            notes = []
            if v.get("existing_type") and v["type"] != v["existing_type"]:
                notes.append(f"Type stays {v['existing_type']}: Meta doesn't let a template change type.")
            if media:
                notes.append("Picture/video header kept: change it in Create Template.")
            if notes:
                result["note"] = " ".join(notes)
            results.append(result)
            continue
        if v["status"] != "ready":
            results.append({**base, "status": "skipped", "reason": " ".join(v["problems"]) or "Not ready."})
            continue
        # a row sent a moment ago counts as existing for the rows after it
        clash = next((c for c in created if c["name"] == v["name"]), None)
        if clash:
            results.append({**base, "status": "skipped", "reason": f"Same name as row {clash['row']}, already sent."})
            continue
        try:
            await create(to_payload(v))
        except Exception as e:  # Meta's refusal, a duplicate, a validation error: the row's own result
            results.append({**base, "status": "refused", "reason": _reason(e)})
            continue
        created.append(v)
        results.append({**base, "status": "sent"})
    return results


def sample_workbook() -> bytes:
    """The sample file: the exact columns, two filled rows, dropdowns for type / language / button type,
    a frozen title row and a "How to fill" sheet."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Templates"
    ws.append([t for t, _ in COLUMNS])
    examples = [
        ["festival_offer", "Marketing", "English", "Diwali offer", "",
         "Hi {{1}}, flat {{2}} off on all sarees this week at our shop. Visit us before Sunday!",
         "Priya", "20%", "", "", "", "Reply STOP to stop",
         "Link", "Shop now", "https://example.com/shop", "Quick reply", "Not now", "", "", "", ""],
        ["order_ready", "Utility", "Tamil", "", "",
         "வணக்கம் {{1}}, உங்கள் ஆர்டர் {{2}} தயாராக உள்ளது. நன்றி!",
         "Priya", "D-1047", "", "", "", "",
         "Call", "Call shop", "+91 98765 43210", "", "", "", "", "", ""],
    ]
    for r in examples:
        ws.append(r)

    title_fill = PatternFill("solid", fgColor="E6F4F1")
    must_fill = PatternFill("solid", fgColor="FDE7D9")
    for i, (title, _f) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=i)
        cell.font = Font(bold=True)
        cell.fill = must_fill if title in REQUIRED else title_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = {
            "Body": 60, "Template name": 24, "Header": 24, "Footer": 24,
        }.get(title, 46 if "link or phone" in title else 16)
    ws.freeze_panes = "A2"
    ws.cell(row=1, column=1).comment = Comment("Orange columns must be filled. Small letters, numbers and _ only.", "Anril")
    ws.cell(row=1, column=7).comment = Comment("One example for each {{n}} in the Body: Example {{1}} for {{1}}, and so on.", "Anril")

    last = MAX_ROWS + 1
    dv_type = DataValidation(type="list", formula1='"Marketing,Utility"', allow_blank=False)
    dv_lang = DataValidation(type="list", formula1=f'"{",".join(LANGUAGE_LABEL.values())}"', allow_blank=False)
    dv_btn = DataValidation(type="list", formula1='"Link,Call,Quick reply"', allow_blank=True)
    for dv in (dv_type, dv_lang, dv_btn):
        ws.add_data_validation(dv)
    dv_type.add(f"B2:B{last}")
    dv_lang.add(f"C2:C{last}")
    for i in range(1, BUTTONS + 1):
        col = next(n for n, (t, _f) in enumerate(COLUMNS, start=1) if t == f"Button {i} type")
        letter = _column_letter(col - 1)
        dv_btn.add(f"{letter}2:{letter}{last}")

    help_ws = wb.create_sheet("How to fill")
    for line in [
        ["How to fill the Templates sheet"],
        [""],
        ["Keep the column titles and their order exactly as they are. One row is one template, up to 50 rows."],
        ["Must fill: Template name, Type, Language, Body, and an example for every {{n}} in the Body."],
        ["Template name: small letters, numbers and _ only, e.g. festival_offer."],
        ["Type: Marketing (offers, news) or Utility (orders, bookings, bills)."],
        ["Header: an optional short bold line, no emojis. If it has {{1}}, fill Header example."],
        ["Body: the message. Use {{1}}, {{2}} ... for details that change per customer; don't start or end with one."],
        ["Example {{1}} ... {{5}}: what Meta's reviewer sees in place of each {{n}}, e.g. Priya, 20%, D-1047."],
        ["Buttons (optional, up to 3): Link + text + https:// link, Call + text + phone with country code, or Quick reply + text."],
        ["Picture, video or document headers can't go in Excel: make those templates in the builder."],
        ["After you upload, every template shows with a WhatsApp preview. Fix or remove any of them, then send them to Meta together."],
    ]:
        help_ws.append(line)
    help_ws["A1"].font = Font(bold=True, size=13)
    help_ws.column_dimensions["A"].width = 120

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
