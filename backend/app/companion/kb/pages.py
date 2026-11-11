"""Page-by-page reading rules for the knowledge base: when a page's own text layer can be trusted.

Why: a scanned or old-font PDF (Tamil books typed in Bamini/TSCII) has a text layer that looks like text
but is garbage. Using it poisons search. So each page is judged on its own, and the page goes to OCR
(reading text from the page image) when the layer cannot be trusted. Pure functions plus two small
pdfplumber readers; no database, no network. Page text is never logged.

Worked example:
  "jkpo;ehL fhy;gJ ..." (Tamil typed through a legacy font, read back as Latin) has ';' sitting between
  two letters 2 times in 12 letters = 0.17, above MAX_INWORD_PUNCT (0.08), so text_layer_ok is False.
  "Hello, world. Don't worry." has 1 in 19 = 0.05, so it passes. Real Unicode Tamil has no ASCII
  punctuation inside words, so it passes.
A document-level spot-check then catches garbage that passes those rules: OCR 3 pages
(pick_spot_check_pages), compare with their text layer (text_difference); if 2 of 3 differ by more than
SPOT_DIFF, distrust_text_layer is True and every page of the document goes to OCR.
"""
import difflib
import re
import string

import pdfplumber

MIN_CHARS = 50                 # under this many non-space characters the text layer counts as missing
MAX_INWORD_PUNCT = 0.08        # share of punctuation sitting between two letters, the old-font fingerprint
SPOT_DIFF = 0.40               # a spot-check page "differs" above this

# Lowercase fragments of legacy (non-Unicode) Tamil font names. Unicode fonts (Latha, Nirmala) are not here.
OLD_TAMIL_FONTS: tuple[str, ...] = (
    "bamini", "tscii", "tsc_", "tscu_", "tab-", "tam-", "tab_", "tam_", "vanavil", "shree-tam", "shree_tam",
)

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_PUNCT = set(string.punctuation)


def count_pages(path: str) -> int:
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


def read_page(path: str, page_no: int) -> tuple[str, set[str]]:
    """Text layer and font names of one page (1-based). ("", set()) when the page has no text."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_no - 1]
        text = page.extract_text() or ""
        fonts = {str(c["fontname"]) for c in page.chars if c.get("fontname")}
    if not text.strip():
        return "", set()
    return text, fonts


def _old_font(fonts: set[str]) -> bool:
    for name in fonts:
        bare = _SUBSET_PREFIX.sub("", name).lower()
        if any(frag in bare for frag in OLD_TAMIL_FONTS):
            return True
    return False


def _inword_punct_ratio(text: str) -> float:
    """ASCII punctuation with a letter right before and right after it, divided by the letters."""
    letters = sum(1 for ch in text if ch.isalpha())
    if letters == 0:
        return 0.0
    inside = sum(
        1 for i in range(1, len(text) - 1)
        if text[i] in _PUNCT and text[i - 1].isalpha() and text[i + 1].isalpha()
    )
    return inside / letters


def text_layer_ok(text: str, fonts: set[str]) -> bool:
    """False when the page's own text cannot be trusted (missing, old Tamil font, or old-font look)."""
    if sum(1 for ch in text if not ch.isspace()) < MIN_CHARS:
        return False
    if _old_font(fonts):
        return False
    return _inword_punct_ratio(text) <= MAX_INWORD_PUNCT


def text_difference(a: str, b: str) -> float:
    """0.0 same .. 1.0 nothing in common. Whitespace differences are ignored."""
    a, b = "".join(a.split()), "".join(b.split())
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    return 1.0 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def pick_spot_check_pages(page_nos: list[int], count: int = 3) -> list[int]:
    """A deterministic spread (first, middle, last); all pages when there are no more than count."""
    nos = sorted(set(page_nos))
    if len(nos) <= count:
        return nos
    if count == 1:
        return [nos[0]]
    return [nos[(i * (len(nos) - 1)) // (count - 1)] for i in range(count)]


def distrust_text_layer(pairs: list[tuple[str, str]]) -> bool:
    """pairs are (text layer, OCR text). True when at least 2 differ by more than SPOT_DIFF."""
    return sum(1 for layer, ocr in pairs if text_difference(layer, ocr) > SPOT_DIFF) >= 2
