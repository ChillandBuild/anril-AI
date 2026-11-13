r"""Page-by-page reading rules for the knowledge base: when a page's own text layer can be trusted.

Why: a scanned or old-font PDF (Tamil books typed in Bamini/TSCII) has a text layer that looks like text
but is garbage. Using it poisons search. So each page is judged on its own, and the page goes to OCR
(reading text from the page image) when the layer cannot be trusted. Pure functions plus two small
pdfplumber readers; no database, no network. Page text is never logged.

Worked example:
  "jkpo;ehL fhy;gJ ..." (Tamil typed through a legacy font, read back as Latin) has ';' sitting between
  two letters 2 times in 12 letters = 0.17, above MAX_INWORD_PUNCT (0.08), so text_layer_ok is False.
  "Hello, world. Don't worry." has 1 in 19 = 0.05, so it passes. Real Unicode Tamil has no ASCII
  punctuation inside words, so it passes.
  "AI ேஜாத\x00ட வ\x00த\x00 புத்தகம்" (a Tamil page printed to PDF from Chrome; correct: "AI ஜோதிட விதி
  புத்தகம்") fails too: the vowel signs ெ ே ை sit BEFORE their letter (screen order, so 8-22% of words
  start with one, against at most 1.8% on 9 real archive.org books) and the font left ி unmapped (\x00).
A document-level spot-check then catches garbage that passes those rules: OCR 3 pages
(pick_spot_check_pages), compare with their text layer (text_difference); if 2 of 3 differ by more than
SPOT_DIFF, distrust_text_layer is True and every page of the document goes to OCR.
"""
import difflib
import io
import re
import string
import threading

import pdfplumber
import pypdfium2 as pdfium

MIN_CHARS = 50                 # under this many non-space characters the text layer counts as missing
MAX_INWORD_PUNCT = 0.08        # share of punctuation sitting between two letters, the old-font fingerprint
SPOT_DIFF = 0.40               # a spot-check page "differs" above this
MAX_SCREEN_ORDER_WORDS = 0.05  # share of Tamil words that START with ெ ே ை, the screen-order fingerprint
MIN_SCREEN_ORDER_WORDS = 3     # ...and at least this many, so one stray sign on a short page is not enough

# Lowercase fragments of legacy (non-Unicode) Tamil font names. Unicode fonts (Latha, Nirmala) are not here.
OLD_TAMIL_FONTS: tuple[str, ...] = (
    "bamini", "tscii", "tsc_", "tscu_", "tab-", "tam-", "tab_", "tam_", "vanavil", "shree-tam", "shree_tam",
)

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_TAMIL_WORD = re.compile(r"[\u0B80-\u0BFF]+")
_PRE_BASE_SIGNS = ("\u0BC6", "\u0BC7", "\u0BC8")     # ெ ே ை: drawn left of the letter, typed after it
_UNMAPPED = ("\x00", "\ufffd")                        # a glyph the PDF font gave no letter for
_PUNCT = set(string.punctuation)
_MAX_SIDE = 3000                    # a huge page is rendered smaller, not sent as a 40 MB image
_pdfium_lock = threading.Lock()     # PDFium is not thread-safe (tests draw pages from threads)
# Zero-width non-joiner (Thanjavur library PDFs put one after every ்), zero-width space, byte-order
# mark. Invisible, but word search treats மூலம்+mark as another word than a typed மூலம். The
# zero-width joiner stays: it can change how a letter is drawn.
_INVISIBLE = dict.fromkeys(map(ord, "\u200c\u200b\ufeff"))


def strip_invisible(text: str | None) -> str | None:
    return text.translate(_INVISIBLE) if isinstance(text, str) else text


def count_pages(path: str) -> int:
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


def read_page(path: str, page_no: int) -> tuple[str, set[str]]:
    """Text layer and font names of one page (1-based). ("", set()) when the page has no text."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_no - 1]
        text = strip_invisible(page.extract_text() or "")    # also keeps the spot-check comparison fair
        fonts = {str(c["fontname"]) for c in page.chars if c.get("fontname")}
    if not text.strip():
        return "", set()
    return text, fonts


def render_pdf_page(path: str, page_no: int, *, scale: float = 2.0) -> bytes:
    """Page page_no (1-based) of the PDF as PNG bytes, for OCR. scale 2.0 is 144 dots per inch.
    Lives here, not in ocr.py, so the helper process that runs it loads only this light module."""
    with _pdfium_lock:
        pdf = pdfium.PdfDocument(path)
        try:
            page = pdf[page_no - 1]
            longest = max(page.get_size()) * scale
            if longest > _MAX_SIDE:
                scale = scale * _MAX_SIDE / longest
            image = page.render(scale=scale).to_pil()
        finally:
            pdf.close()
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return out.getvalue()


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


def _screen_order_tamil(text: str) -> bool:
    """True when Tamil words start with a vowel sign, which correct Unicode never does (see the module example)."""
    words = _TAMIL_WORD.findall(text)
    starts = sum(1 for word in words if word.startswith(_PRE_BASE_SIGNS))
    return starts >= MIN_SCREEN_ORDER_WORDS and starts > MAX_SCREEN_ORDER_WORDS * len(words)


def text_layer_ok(text: str, fonts: set[str]) -> bool:
    """False when the page's own text cannot be trusted: missing, old Tamil font, old-font look, letters the
    font left unmapped, or Tamil in screen order."""
    if sum(1 for ch in text if not ch.isspace()) < MIN_CHARS:
        return False
    if _old_font(fonts):
        return False
    if any(mark in text for mark in _UNMAPPED) or _screen_order_tamil(text):
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
