"""T5: reading one page image with the business's own Gemini key (fake HTTP layer, no network)."""
import asyncio
import inspect
import io

import httpx
import pytest
from PIL import Image

from app.companion.kb import ocr
from app.services import gemini_client

TENANT = "11111111-1111-1111-1111-111111111111"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CUT = ("partial", True)


def run(coro):
    return asyncio.run(coro)


def png(width=200, height=1000) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


@pytest.fixture
def gem(monkeypatch):
    """Queue answers for `_generate`: a (text, cut_off) pair, or an Exception to raise.
    `gem.calls` records every call. The business has a key and a reply model."""
    state = type("Gem", (), {"answers": [], "calls": []})()

    async def fake(key, model, image, mime_type, tenant_id):
        state.calls.append({"key": key, "model": model, "image": image, "mime_type": mime_type,
                            "tenant_id": tenant_id})
        answer = state.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(ocr, "_generate", fake)
    monkeypatch.setattr(ocr, "require_tenant_setting", lambda key, tenant_id: "tenant-key")
    monkeypatch.setattr(ocr.ai_reply, "_provider_for", lambda tenant_id, model: ("gemini", "reply-model"))
    monkeypatch.setattr(ocr, "_TRY_DELAYS", (0.0, 0.0, 0.0))
    return state


# ---- ocr_image -------------------------------------------------------------------------------

def test_success_returns_the_text_with_one_call(gem):
    gem.answers = [("# Chapter 7\nSaturn in the 7th house", False)]
    assert run(ocr.ocr_image(TENANT, png())) == ("# Chapter 7\nSaturn in the 7th house", None)
    assert len(gem.calls) == 1
    call = gem.calls[0]
    assert (call["key"], call["model"], call["mime_type"], call["tenant_id"]) == \
        ("tenant-key", "reply-model", "image/png", TENANT)


def test_the_key_asked_for_is_the_business_gemini_key(gem, monkeypatch):
    asked = []
    monkeypatch.setattr(ocr, "require_tenant_setting", lambda key, tenant_id: asked.append((key, tenant_id)) or "k")
    gem.answers = [("text", False)]
    run(ocr.ocr_image(TENANT, png()))
    assert asked == [("gemini_api_key", TENANT)]


def test_ocr_model_constant_overrides_the_reply_model(gem, monkeypatch):
    monkeypatch.setattr(ocr, "OCR_MODEL", "stronger-model")
    gem.answers = [("text", False)]
    run(ocr.ocr_image(TENANT, png()))
    assert gem.calls[0]["model"] == "stronger-model"


def test_mime_type_is_passed_through(gem):
    gem.answers = [("text", False)]
    run(ocr.ocr_image(TENANT, b"jpeg-bytes", "image/jpeg"))
    assert gem.calls[0]["mime_type"] == "image/jpeg"


def test_cut_off_splits_the_page_and_joins_the_halves(gem):
    page = png(200, 1000)
    gem.answers = [CUT, ("top line 1\ntop line 2", False), ("bottom line 1\nbottom line 2", False)]
    text, error = run(ocr.ocr_image(TENANT, page))
    assert error is None
    assert text == "top line 1\ntop line 2\nbottom line 1\nbottom line 2"
    assert len(gem.calls) == 3                                   # 1 whole page + 2 halves
    assert gem.calls[0]["image"] == page
    top, bottom = ocr.split_image(page)
    assert [c["image"] for c in gem.calls[1:]] == [top, bottom]
    assert [c["mime_type"] for c in gem.calls[1:]] == ["image/png", "image/png"]


def test_duplicated_boundary_line_is_dropped(gem):
    gem.answers = [CUT, ("line A\nline B\n", False), ("\nline B  \nline C", False)]
    assert run(ocr.ocr_image(TENANT, png())) == ("line A\nline B\nline C", None)


def test_only_the_boundary_copy_is_dropped():
    assert ocr._join_halves("om\nom", "om\nom") == "om\nom\nom"   # a verse may repeat a line
    assert ocr._join_halves("a\nb", "c\nb") == "a\nb\nc\nb"
    assert ocr._join_halves("", "c") == "c"
    assert ocr._join_halves("a", "") == "a"


def test_a_cut_off_half_is_a_failed_try_and_is_not_split_again(gem):
    gem.answers = [CUT, ("top", False), CUT,          # try 1: the bottom half is cut off too
                   ("whole page", False)]             # try 2
    assert run(ocr.ocr_image(TENANT, png())) == ("whole page", None)
    assert len(gem.calls) == 4


def test_cut_off_on_every_try_gives_the_too_long_error(gem):
    gem.answers = [CUT, CUT] * 3                      # each try: page cut off, then the top half too
    assert run(ocr.ocr_image(TENANT, png())) == (None, "The page was too long to read")
    assert len(gem.calls) == 6


def test_an_empty_half_does_not_fail_the_page(gem):
    gem.answers = [CUT, ("all the text", False), ("EMPTY", False)]
    assert run(ocr.ocr_image(TENANT, png())) == ("all the text", None)


def test_third_failure_returns_the_error_and_does_not_raise(gem):
    gem.answers = [ocr.OcrError("Gemini error 503")] * 3
    assert run(ocr.ocr_image(TENANT, png())) == (None, "Gemini error 503")
    assert len(gem.calls) == ocr.OCR_TRIES == 3


def test_a_later_try_can_succeed(gem):
    gem.answers = [ocr.OcrError("Gemini error 503"), ocr.OcrError("Gemini error 429"), ("text", False)]
    assert run(ocr.ocr_image(TENANT, png())) == ("text", None)
    assert len(gem.calls) == 3


def test_an_error_that_cannot_improve_stops_at_once(gem):
    gem.answers = [ocr.OcrError("Gemini error 400", retry=False)]
    assert run(ocr.ocr_image(TENANT, png())) == (None, "Gemini error 400")
    assert len(gem.calls) == 1


def test_an_unexpected_exception_is_a_failed_try_with_a_safe_error(gem, caplog):
    gem.answers = [ValueError("secret page text tenant-key")] * 3
    text, error = run(ocr.ocr_image(TENANT, png()))
    assert (text, error) == (None, "The page could not be read")
    assert "secret page text" not in caplog.text and "tenant-key" not in caplog.text


def test_missing_key_returns_an_error_text_and_makes_no_call(gem, monkeypatch):
    def no_key(key, tenant_id):
        raise RuntimeError("gemini_api_key not configured for this client")
    monkeypatch.setattr(ocr, "require_tenant_setting", no_key)
    assert run(ocr.ocr_image(TENANT, png())) == (None, "No Gemini key is set for this business")
    assert gem.calls == []


@pytest.mark.parametrize("answer", ["EMPTY", " empty\n", "EMPTY."])
def test_empty_answer_is_a_success_with_no_text(gem, answer):
    gem.answers = [(answer, False)]
    assert run(ocr.ocr_image(TENANT, png())) == ("", None)
    assert len(gem.calls) == 1


def test_no_text_back_is_a_failed_try(gem):
    gem.answers = [("", False), ("   ", False), ("", False)]     # blocked / no candidates
    assert run(ocr.ocr_image(TENANT, png())) == (None, "Gemini returned no text")
    assert len(gem.calls) == 3


def test_at_most_four_calls_run_at_once(gem, monkeypatch):
    assert ocr._slots._value == 4
    monkeypatch.setattr(ocr, "_slots", asyncio.Semaphore(4))     # a fresh one for this event loop
    state = {"now": 0, "peak": 0}

    async def slow(key, model, image, mime_type, tenant_id):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return "text", False
    monkeypatch.setattr(ocr, "_generate", slow)

    async def ten():
        return await asyncio.gather(*[ocr.ocr_image(TENANT, b"x") for _ in range(10)])
    assert run(ten()) == [("text", None)] * 10
    assert state["peak"] == 4


# ---- the one HTTP call ---------------------------------------------------------------------------

class FakeClient:
    """Stands in for httpx.AsyncClient: records the request, answers from `reply`."""
    sent: list = []
    reply = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        FakeClient.sent.append({"url": url, "headers": headers, "json": json})
        if isinstance(FakeClient.reply, Exception):
            raise FakeClient.reply
        return FakeClient.reply


@pytest.fixture
def http(monkeypatch):
    FakeClient.sent, FakeClient.reply = [], None
    metered = []
    monkeypatch.setattr(ocr.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(gemini_client, "_record", lambda *args: metered.append(args))
    FakeClient.metered = metered
    return FakeClient


def answer(text="page text", status="completed", output_tokens=50):
    return httpx.Response(200, json={
        "status": status, "usage": {"total_input_tokens": 300, "total_output_tokens": output_tokens},
        "steps": [{"type": "thought", "content": [{"type": "text", "text": "thinking"}]},
                  {"type": "model_output", "content": [{"type": "text", "text": text}]}]})


def test_generate_sends_one_image_with_the_key_in_a_header(http):
    http.reply = answer("ஏழாம் வீடு")
    assert run(ocr._generate("tenant-key", "reply-model", b"img", "image/png", TENANT)) == ("ஏழாம் வீடு", False)
    sent = http.sent[0]
    assert sent["url"] == gemini_client.GEMINI_INTERACTIONS_URL and "tenant-key" not in sent["url"]
    assert sent["headers"]["x-goog-api-key"] == "tenant-key"
    body = sent["json"]
    assert body["model"] == "reply-model"
    assert body["generation_config"]["max_output_tokens"] == ocr.OCR_MAX_TOKENS == 8000
    parts = body["input"][0]["content"]
    assert parts[0] == {"type": "text", "text": ocr.OCR_PROMPT}
    assert parts[1] == {"type": "image", "data": "aW1n", "mime_type": "image/png"}   # base64 of b"img"
    assert http.metered[0][:3] == (TENANT, "companion_kb_ocr", "reply-model")


@pytest.mark.parametrize("reply", [answer(status="incomplete"), answer(output_tokens=7900)])
def test_generate_reports_a_cut_off_answer(http, reply):
    http.reply = reply
    assert run(ocr._generate("k", "m", b"img", "image/png", TENANT)) == ("page text", True)


@pytest.mark.parametrize("code,retry", [(503, True), (429, True), (400, False), (403, False)])
def test_generate_http_error_is_short_and_safe(http, code, retry):
    http.reply = httpx.Response(code, text="API key tenant-key is invalid https://generativelanguage...")
    with pytest.raises(ocr.OcrError) as caught:
        run(ocr._generate("tenant-key", "m", b"img", "image/png", TENANT))
    assert str(caught.value) == f"Gemini error {code}"
    assert caught.value.retry is retry


def test_generate_timeout_and_network_errors_are_safe(http):
    for raised, message in ((httpx.ReadTimeout("t"), "Gemini took too long to answer"),
                            (httpx.ConnectError("c"), "Gemini could not be reached")):
        http.reply = raised
        with pytest.raises(ocr.OcrError) as caught:
            run(ocr._generate("k", "m", b"img", "image/png", TENANT))
        assert str(caught.value) == message and caught.value.retry is True


def test_generate_failed_status_is_an_error_not_a_cut_off(http):
    http.reply = answer(text="", status="failed")
    with pytest.raises(ocr.OcrError):
        run(ocr._generate("k", "m", b"img", "image/png", TENANT))


def test_generate_blocked_answer_has_no_text(http):
    http.reply = httpx.Response(200, json={"status": "completed", "steps": []})
    assert run(ocr._generate("k", "m", b"img", "image/png", TENANT)) == ("", False)


# ---- images --------------------------------------------------------------------------------------

def test_split_image_halves_have_the_right_heights():
    top, bottom = ocr.split_image(png(200, 1000))
    assert top.startswith(PNG_SIGNATURE) and bottom.startswith(PNG_SIGNATURE)
    assert size_of(top) == (200, 530)            # 500 + a 3% band (30)
    assert size_of(bottom) == (200, 530)


def test_split_image_halves_overlap_and_cover_the_page():
    page = Image.new("RGB", (10, 101), "white")
    for y in range(101):
        page.putpixel((0, y), (y, 0, 0))         # each row carries its own number
    out = io.BytesIO()
    page.save(out, format="PNG")
    top, bottom = (Image.open(io.BytesIO(h)) for h in ocr.split_image(out.getvalue()))
    top_rows = [top.getpixel((0, y))[0] for y in range(top.height)]
    bottom_rows = [bottom.getpixel((0, y))[0] for y in range(bottom.height)]
    assert top_rows[0] == 0 and bottom_rows[-1] == 100
    assert sorted(set(top_rows) | set(bottom_rows)) == list(range(101))
    assert len(set(top_rows) & set(bottom_rows)) == 6      # band of 3 rows on each side of the middle


def test_render_pdf_page_returns_png_bytes(tmp_path):
    path = tmp_path / "two.pdf"
    Image.new("RGB", (200, 300), "white").save(
        path, format="PDF", save_all=True, append_images=[Image.new("RGB", (300, 200), "black")])
    first, second = ocr.render_pdf_page(str(path), 1), ocr.render_pdf_page(str(path), 2)
    assert first.startswith(PNG_SIGNATURE) and second.startswith(PNG_SIGNATURE)
    w1, h1 = size_of(first)
    w2, h2 = size_of(second)
    assert h1 > w1 and w2 > h2                    # page 1 is tall, page 2 is wide: 1-based
    small = size_of(ocr.render_pdf_page(str(path), 1, scale=1.0))
    assert abs(w1 - 2 * small[0]) <= 2            # scale 2.0 is the default


def test_render_pdf_page_out_of_range_raises(tmp_path):
    path = tmp_path / "one.pdf"
    Image.new("RGB", (100, 100), "white").save(path, format="PDF")
    with pytest.raises(Exception):
        ocr.render_pdf_page(str(path), 2)


# ---- ocr_pdf_page --------------------------------------------------------------------------------

def test_ocr_pdf_page_renders_then_reads(gem, tmp_path):
    path = tmp_path / "one.pdf"
    Image.new("RGB", (200, 300), "white").save(path, format="PDF")
    gem.answers = [("page one", False)]
    assert run(ocr.ocr_pdf_page(TENANT, str(path), 1)) == ("page one", None)
    assert gem.calls[0]["image"].startswith(PNG_SIGNATURE) and gem.calls[0]["mime_type"] == "image/png"


def test_ocr_pdf_page_that_cannot_be_opened_is_an_error_text(gem, tmp_path):
    assert run(ocr.ocr_pdf_page(TENANT, str(tmp_path / "missing.pdf"), 1)) == (None, "The page could not be opened")
    assert gem.calls == []


# ---- the module itself ---------------------------------------------------------------------------

def test_prompt_says_what_to_keep_and_what_not_to_do():
    prompt = ocr.OCR_PROMPT
    for needle in ("exactly", "markdown headings", " | ", "line breaks", "translate", "summarise", "EMPTY"):
        assert needle in prompt


def test_module_uses_only_the_business_key():
    source = inspect.getsource(ocr)
    assert 'require_tenant_setting("gemini_api_key", tenant_id)' in source
    for banned in ("get_tenant_setting", "get_setting", "get_settings", "os.environ", "getenv",
                   "GEMINI_API_KEY", "platform_", "default_gemini", "settings."):
        assert banned not in source, banned
