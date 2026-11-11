"""Reading the text off ONE page image, for the Anril Agents knowledge base.

Why one page at a time: the Anril Sales reader sends a whole scanned PDF in one request capped
at 4,000 output tokens, so most of a book is lost and nobody is told. Here each page is its own
call with an 8,000-token limit, and a page that still does not fit is cut in two and read as
halves.

Worked example, Book 7 (AstroTamil, 320 pages):

    page 44   scanned image   -> render to PNG -> one Gemini call -> ("ஏழாம் வீட்டில் ...", None)
    page 120  a dense table   -> answer cut off at the limit -> top half + bottom half, joined
    page 200  Gemini 503 x 3  -> (None, "Gemini error 503")   the ledger marks the page failed

Rules:
- The business's own Gemini key, like memory_embed. A missing key is an error text, never
  another key.
- A page is tried OCR_TRIES times. The result is (text, None) or (None, short error an owner
  can read). Nothing here raises to the caller.
- Page text and the key are never logged.
- Same Gemini endpoint and response handling as app/services/gemini_client.py (read, not edited),
  so the calls are metered under the purpose "companion_kb_ocr".
"""
import asyncio
import base64
import io
import logging
import threading

import httpx
import pypdfium2 as pdfium
from PIL import Image

from app.config_dynamic import require_tenant_setting
from app.services import ai_reply
from app.services import gemini_client

logger = logging.getLogger(__name__)

OCR_MAX_TOKENS = 8000
OCR_TRIES = 3
# None = the business's reply model (flash-lite today). To read scans with a stronger Gemini
# model, set its name here ("gemini-3.5-flash"); this is the one place to change.
OCR_MODEL: str | None = None
OCR_PURPOSE = "companion_kb_ocr"
OCR_PROMPT = (
    "Transcribe every piece of text on this page exactly as it is written, in its original "
    "language and script.\n"
    "- Write headings as markdown headings (# for a chapter title, ## for a section).\n"
    "- Write each table row on its own line, with the cells joined by \" | \".\n"
    "- Keep the line breaks of verses and poems.\n"
    "- Do not translate, summarise, explain, correct or add anything. Do not describe pictures.\n"
    "- Return only the transcribed text, with no code fence and no commentary.\n"
    "- If the page has no text at all, answer with the single word EMPTY."
)

NO_KEY_ERROR = "No Gemini key is set for this business"
TOO_LONG_ERROR = "The page was too long to read"
NO_TEXT_ERROR = "Gemini returned no text"

_TIMEOUT = 60.0
_TRY_DELAYS = (0.0, 1.0, 3.0)       # wait before try 1, 2, 3
_RETRYABLE = (408, 429, 500, 502, 503, 504)
_OVERLAP = 0.03                     # the two halves share this band so a line on the cut is whole in one
_MAX_SIDE = 3000                    # a huge page is rendered smaller, not sent as a 40 MB image
_slots = asyncio.Semaphore(4)       # per process: OCR never takes every outbound slot
_pdfium_lock = threading.Lock()     # PDFium is not thread-safe; renders run one at a time


class OcrError(RuntimeError):
    """One failed try. str(exc) is short and safe to show an owner. retry=False: trying again
    cannot help (a refused key, a bad request)."""

    def __init__(self, message: str, retry: bool = True):
        super().__init__(message)
        self.retry = retry


def render_pdf_page(path: str, page_no: int, *, scale: float = 2.0) -> bytes:
    """Page page_no (1-based) of the PDF as PNG bytes. scale 2.0 is 144 dots per inch."""
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


def split_image(png: bytes) -> tuple[bytes, bytes]:
    """(top half, bottom half) as PNG bytes. Each half reaches about 3% of the height past the
    middle, so a line sitting on the cut is whole in at least one of them."""
    image = Image.open(io.BytesIO(png))
    width, height = image.size
    middle = height // 2
    band = max(1, round(height * _OVERLAP))
    halves = []
    for box in ((0, 0, width, min(height, middle + band)), (0, max(0, middle - band), width, height)):
        out = io.BytesIO()
        image.crop(box).save(out, format="PNG")
        halves.append(out.getvalue())
    return halves[0], halves[1]


def _join_halves(top: str, bottom: str) -> str:
    """The two halves as one text. The shared band can put the same line at the end of the top
    and the start of the bottom; that copy is dropped."""
    top_lines = top.rstrip().split("\n") if top.strip() else []
    bottom_lines = bottom.lstrip("\n").split("\n") if bottom.strip() else []
    while bottom_lines and not bottom_lines[0].strip():
        bottom_lines.pop(0)
    if top_lines and bottom_lines and top_lines[-1].strip() == bottom_lines[0].strip():
        bottom_lines.pop(0)
    return "\n".join(top_lines + bottom_lines).strip()


def _model(tenant_id: str) -> str:
    return OCR_MODEL or ai_reply._provider_for(tenant_id, None)[1]


async def _generate(key: str, model: str, image: bytes, mime_type: str, tenant_id: str) -> tuple[str, bool]:
    """One Gemini request for one image: (text, cut_off). cut_off = the answer stopped at the
    output limit. Raises OcrError for anything that is not a usable answer."""
    payload = {
        "model": model,
        "input": [{
            "type": "user_input",
            "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image", "data": base64.b64encode(image).decode(), "mime_type": mime_type},
            ],
        }],
        "generation_config": {"temperature": 0.0, "max_output_tokens": OCR_MAX_TOKENS,
                              "thinking_level": "minimal"},
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                gemini_client.GEMINI_INTERACTIONS_URL,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=payload)
    except httpx.TimeoutException:
        raise OcrError("Gemini took too long to answer") from None
    except httpx.HTTPError:
        raise OcrError("Gemini could not be reached") from None
    if resp.status_code != 200:
        raise OcrError(f"Gemini error {resp.status_code}", retry=resp.status_code in _RETRYABLE)
    try:
        data = resp.json() or {}
    except ValueError:
        raise OcrError(NO_TEXT_ERROR) from None
    try:
        gemini_client._record(tenant_id, OCR_PURPOSE, model, data)
    except Exception as exc:        # a metering hiccup must not cost the page
        logger.warning("companion kb: OCR metering failed (%s)", type(exc).__name__)
    if str(data.get("status") or "").lower() in ("failed", "cancelled"):
        raise OcrError("Gemini could not read the page")    # not a cut-off: do not split
    text =gemini_client._gemini_output_text(data.get("steps") or [])
    return text, gemini_client._hit_output_cap(data, OCR_MAX_TOKENS)


async def _call(key: str, model: str, image: bytes, mime_type: str, tenant_id: str) -> tuple[str, bool]:
    async with _slots:
        return await _generate(key, model, image, mime_type, tenant_id)


def _page_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        # Also what a refused (blocked) page looks like: no model_output step at all.
        raise OcrError(NO_TEXT_ERROR)
    return "" if text.upper().strip(".") == "EMPTY" else text


async def _read_once(key: str, model: str, image: bytes, mime_type: str, tenant_id: str) -> str:
    """One try at one page. A cut-off answer is read again as two halves; a half that is cut
    off too fails the try (it is not split again)."""
    text, cut_off = await _call(key, model, image, mime_type, tenant_id)
    if not cut_off:
        return _page_text(text)
    try:
        halves = await asyncio.to_thread(split_image, image)
    except Exception:
        raise OcrError(TOO_LONG_ERROR, retry=False) from None
    parts = []
    for half in halves:
        half_text, half_cut = await _call(key, model, half, "image/png", tenant_id)
        if half_cut:
            raise OcrError(TOO_LONG_ERROR)
        parts.append(_page_text(half_text))
    return _join_halves(parts[0], parts[1])


async def ocr_image(tenant_id: str, image: bytes, mime_type: str = "image/png") -> tuple[str | None, str | None]:
    """(text, None) on success, (None, error text) after OCR_TRIES failures. Never raises.
    A page with no text on it is a success with text ""."""
    try:
        key = require_tenant_setting("gemini_api_key", tenant_id)
    except Exception:
        return None, NO_KEY_ERROR
    try:
        model = _model(tenant_id)
    except Exception as exc:
        logger.warning("companion kb: no OCR model (%s)", type(exc).__name__)
        return None, "No reply model is set for this business"
    error = NO_TEXT_ERROR
    for attempt in range(OCR_TRIES):
        delay = _TRY_DELAYS[min(attempt, len(_TRY_DELAYS) - 1)]
        if delay:
            await asyncio.sleep(delay)
        try:
            return await _read_once(key, model, image, mime_type, tenant_id), None
        except OcrError as exc:
            error = str(exc)
            if not exc.retry:
                break
        except Exception as exc:
            logger.warning("companion kb: OCR try failed (%s)", type(exc).__name__)
            error = "The page could not be read"
    return None, error


async def ocr_pdf_page(tenant_id: str, path: str, page_no: int) -> tuple[str | None, str | None]:
    """Render page page_no (1-based) of the PDF and read it. Same result shape as ocr_image."""
    try:
        image = await asyncio.to_thread(render_pdf_page, path, page_no)
    except Exception as exc:
        logger.warning("companion kb: page render failed (%s)", type(exc).__name__)
        return None, "The page could not be opened"
    return await ocr_image(tenant_id, image, "image/png")
