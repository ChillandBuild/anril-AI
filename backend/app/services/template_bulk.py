"""Excel upload for WhatsApp templates: read the file, check every row, send the good ones.

Only simple templates fit a spreadsheet: a message (with {{1}}, {{2}} blanks and a sample
for each), an optional footer and one website button. Anything else is made in the
builder. The checks reuse the same Meta rules as the builder and as POST /templates/
(services/template_rules.py), so a row that says "ready" here is accepted by the
single-template path too.

Pure helpers live here; the route (routes/templates.py) supplies the existing rows and the
function that really creates one template, so a bulk send goes through the same code as
a template made one at a time.
"""
import io
from itertools import islice
import re
from typing import Awaitable, Callable

from app.services import template_rules

MAX_ROWS = 50
_MAX_SCAN_LINES = 1 + 1000  # header + lines looked at (blank lines are skipped)
BODY_MAX = 1024
FOOTER_MAX = 60
BUTTON_TEXT_MAX = 25

LANGUAGE_BY_NAME = {
    "english": "en", "tamil": "ta", "hindi": "hi", "telugu": "te", "kannada": "kn", "malayalam": "ml",
}
_LANGUAGE_CODES = {"en", "en_US", "en_IN", "hi", "kn", "ml", "ta", "te"}
_LANGUAGE_HELP = "English, Tamil, Hindi, Telugu, Kannada or Malayalam"
_CATEGORY = {"marketing": "MARKETING", "utility": "UTILITY"}
_NAME_OK = re.compile(r"^[a-z0-9_]{1,512}$")
BUILDER_TEXT = "Make this one in the builder."

# spreadsheet column title (lower case, single spaces) -> field
_COLUMNS = {
    "name": "name", "template name": "name",
    "type": "type", "category": "type",
    "language": "language",
    "message": "message", "body": "message",
    "sample values": "samples", "samples": "samples", "sample": "samples",
    "footer": "footer",
    "button text": "button_text",
    "button link": "button_link", "button url": "button_link",
}
_FIELDS = ("name", "type", "language", "message", "samples", "footer", "button_text", "button_link")


class BulkFileError(ValueError):
    """The file itself can't be used (not an .xlsx, too many rows). The route turns it into a 422."""


def _cell(value) -> str:
    return "" if value is None else str(value).strip()


def parse_workbook(content: bytes) -> list[dict]:
    """Rows of the first sheet as {name, type, language, message, samples, footer, button_text, button_link}."""
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

    columns: dict[int, str] = {}
    for i, title in enumerate(raw[0]):
        field = _COLUMNS.get(" ".join(_cell(title).lower().split()))
        if field and field not in columns.values():
            columns[i] = field
    missing = [f for f in ("name", "type", "language", "message") if f not in columns.values()]
    if missing:
        raise BulkFileError(
            "The first row must have the column titles from the sample file (name, type, language, message, "
            "sample values, footer, button text, button link). Missing: " + ", ".join(missing) + "."
        )

    rows = []
    for number, values in enumerate(raw[1:], start=2):
        row = {f: "" for f in _FIELDS}
        for i, field in columns.items():
            row[field] = _cell(values[i]) if i < len(values) else ""
        if not any(row.values()):
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


def _split_samples(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",")] if raw.strip() else []


def language_code(raw: str) -> str | None:
    text = (raw or "").strip()
    if text in _LANGUAGE_CODES:
        return text
    return LANGUAGE_BY_NAME.get(text.lower())


def _existing_index(existing: list[dict]) -> tuple[set[tuple[str, str]], set[str], list[dict]]:
    pairs = {((e.get("name") or ""), (e.get("language") or "")) for e in existing}
    return pairs, {(e.get("name") or "") for e in existing}, existing


def check_rows(rows: list[dict], existing: list[dict]) -> list[dict]:
    """One verdict per row. `existing` = this account's templates (name, language, body_text, footer_text).

    status: ready | need_fix (problems = plain reasons) | exists (same name and language: skipped, never updated).
    """
    pairs, names, existing_rows = _existing_index(existing)
    seen_in_file: dict[tuple[str, str], int] = {}
    out = []
    for raw in rows:
        problems: list[str] = []
        name_raw = _cell(raw.get("name"))
        name = _clean_name(name_raw)
        if not name_raw:
            problems.append("Name is empty.")
        elif name_raw != name or not _NAME_OK.match(name):
            problems.append(f"Name: small letters, numbers and _ only -> {name or 'festival_offer'}")

        category = _CATEGORY.get(_cell(raw.get("type")).lower())
        if category is None:
            kind = _cell(raw.get("type")).lower()
            if kind == "authentication":
                problems.append(f"Type: OTP templates can't be uploaded. {BUILDER_TEXT}")
            else:
                problems.append("Type must be Marketing or Utility.")

        lang_raw = _cell(raw.get("language"))
        language = language_code(lang_raw)
        if language is None:
            problems.append(f"Unknown language{' ' + repr(lang_raw) if lang_raw else ''}. Use {_LANGUAGE_HELP}.")

        message = _cell(raw.get("message"))
        given = raw.get("samples")
        samples = [_cell(s) for s in given] if isinstance(given, list) else _split_samples(_cell(given))
        if not message:
            problems.append("Message is empty.")
        else:
            if len(message) > BODY_MAX:
                problems.append(f"Message is too long ({len(message)} of {BODY_MAX} characters).")
            problems += template_rules.body_problems(message)
            for idx in template_rules.variable_indices(message):
                pos = idx - 1
                if pos >= len(samples) or not samples[pos]:
                    problems.append("{{" + str(idx) + "}} has no sample")

        footer = _cell(raw.get("footer"))
        problems += template_rules.footer_problems(footer)
        if len(footer) > FOOTER_MAX:
            problems.append(f"Footer is too long ({len(footer)} of {FOOTER_MAX} characters).")

        button_text, button_link = _cell(raw.get("button_text")), _cell(raw.get("button_link"))
        if button_text or button_link:
            if not (button_text and button_link):
                problems.append("A button needs both its text and its link.")
            else:
                if len(button_text) > BUTTON_TEXT_MAX:
                    problems.append(f"Button text is too long ({len(button_text)} of {BUTTON_TEXT_MAX} characters).")
                if template_rules.VAR_RE.search(button_link):
                    problems.append(f"Button link has a {{{{1}}}} blank. {BUILDER_TEXT}")
                else:
                    problems += template_rules.url_problems(button_link)

        verdict = {
            "row": raw.get("row"),
            "name": name,
            "type": category,
            "language": language,
            "message": message,
            "samples": samples,
            "footer": footer,
            "button_text": button_text,
            "button_link": button_link,
            "problems": problems,
        }

        if language is not None and name and (name, language) in pairs:
            verdict["status"] = "exists"
            verdict["problems"] = ["Already on your account. Skipped."]
        else:
            if language is not None and name:
                key = (name, language)
                if key in seen_in_file:
                    problems.append(f"Same name and language as row {seen_in_file[key]}.")
                else:
                    seen_in_file[key] = raw.get("row")
                if name in names:
                    problems.append("A template with this name already exists in another language. Pick a different name.")
            if message and not problems and category != "AUTHENTICATION":
                twin = next(
                    (e for e in existing_rows
                     if (e.get("body_text") or "") == message
                     and (e.get("footer_text") or "").strip() == footer and e.get("name") != name),
                    None,
                )
                if twin:
                    problems.append(
                        f"Template '{twin.get('name')}' already has this exact message and footer. "
                        "Meta rejects duplicates, so change the wording."
                    )
            verdict["status"] = "need_fix" if problems else "ready"
        out.append(verdict)
    return out


def to_payload(verdict: dict) -> dict:
    """Arguments for routes.templates.CreateTemplate from a ready row."""
    payload: dict = {
        "name": verdict["name"],
        "category": verdict["type"],
        "language": verdict["language"],
        "body_text": verdict["message"],
        "body_examples": verdict["samples"][: len(template_rules.variable_indices(verdict["message"]))] or None,
    }
    if verdict.get("footer"):
        payload["footer_text"] = verdict["footer"]
    if verdict.get("button_text") and verdict.get("button_link"):
        payload["buttons"] = [{"type": "URL", "text": verdict["button_text"], "url": verdict["button_link"]}]
    return payload


CreateFn = Callable[[dict], Awaitable[dict]]


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


async def submit_rows(rows: list[dict], existing: list[dict], create: CreateFn) -> list[dict]:
    """Re-check every row, then create the ready ones one after another through `create(payload)`.

    Returns one result per row: {row, name, language, status: sent | refused | skipped, reason?}.
    Sequential on purpose: Meta rate-limits template creation and each send changes what "exists" means.
    """
    verdicts = check_rows(rows, existing)
    results = []
    created: list[dict] = []
    for raw, v in zip(rows, verdicts):
        base = {"row": v["row"], "name": v["name"], "language": v["language"]}
        if raw.get("status") in ("need_fix", "exists"):
            # the screen already said this row isn't ready; it stays out even if its cleaned-up name now passes
            reason = " ".join(str(p) for p in raw.get("problems") or []) or "Not ready."
            results.append({**base, "status": "skipped", "reason": reason})
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
