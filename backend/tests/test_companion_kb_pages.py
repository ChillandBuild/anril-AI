"""Page reading rules for the knowledge base (app/companion/kb/pages.py): pure logic plus tiny generated PDFs."""
import os

import pytest
from PIL import Image

from app.companion.kb import pages
from app.companion.kb.pages import (
    count_pages, distrust_text_layer, pick_spot_check_pages, read_page, text_difference, text_layer_ok,
)

TAMIL = "தமிழ் மொழி மிகவும் பழமையான மொழி. இது உலகின் செம்மொழிகளில் ஒன்றாகும். திருக்குறள் தமிழின் சிறந்த நூல்."
OLD_FONT_TEXT = "jkpo; Ntjk; jkpo;ehL fhy;gJ jpUf;Fws; kpfTk; rpwe;j E}y; mUk;ngUk; tpsf;fk;"
# Exactly what pdfplumber reads from the AstroTamil AI Rule Book (a Tamil page printed to PDF from Chrome):
# the vowel signs ெ ே ை come BEFORE their letter (screen order) and every ி comes out as \x00.
# Correct text: "AI ஜோதிட விதி புத்தகம் நம் AI ஒவ்வொரு கேள்விக்கும் ... சொல்லும்."
SCRAMBLED = (
    "AI ேஜாத\x00ட வ\x00த\x00 புத்தகம்\nநம் AI ஒவ்ெவாரு ேகள்வ\x00க்கும் ஜாதகத்த\x00ல் எைதப் பார்க்க ேவண்டும் "
    "என்று இந்த\nவ\x00த\x00கள் ெசால்க\x00ன்றன. கணக்கு நம் app ெசய்யும். AI வ\x00ளக்கம் மட்டும் ெசால்லும்."
)
UNSCRAMBLED = (
    "AI ஜோதிட விதி புத்தகம்\nநம் AI ஒவ்வொரு கேள்விக்கும் ஜாதகத்தில் எதைப் பார்க்க வேண்டும் "
    "என்று இந்த\nவிதிகள் சொல்கின்றன. கணக்கு நம் app செய்யும். AI விளக்கம் மட்டும் சொல்லும்."
)
NOTO = {"BAAAAA+NotoSansTamil-Regular"}
ENGLISH = "Hello, world. Don't worry, this page is ordinary English prose with a normal font and plain punctuation."


def _hand_made_pdf(text: str) -> bytes:
    """One page, one Helvetica text object, with a correct xref table."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 18 Tf 72 700 Td ({text}) Tj ET".encode()
    objs[3] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref_at)
    return out


# --- text_layer_ok ---

def test_strip_invisible_drops_zero_width_marks_only():
    # Zero-width non-joiner after ் (Thanjavur library PDFs), zero-width space, byte-order mark.
    assert pages.strip_invisible("மூலம்\u200c, \u200bராசி\ufeff") == "மூலம், ராசி"
    assert pages.strip_invisible("ஸ்ரீ\u200d") == "ஸ்ரீ\u200d"     # zero-width joiner can shape a letter: kept
    assert pages.strip_invisible(None) is None


def test_unicode_tamil_passes():
    assert len(TAMIL) > 60
    assert text_layer_ok(TAMIL, {"ABCDEF+Latha"})


def test_old_tamil_font_fails_even_with_clean_looking_text():
    assert not text_layer_ok(ENGLISH, {"ABCDEF+Bamini"})
    assert not text_layer_ok(ENGLISH, {"Helvetica", "xyzabc+TSCII-Arial"})


def test_old_font_name_without_subset_prefix_or_case_fails():
    assert not text_layer_ok(ENGLISH, {"BAMINI"})
    assert not text_layer_ok(ENGLISH, {"Tab-Kavi"})


def test_old_font_text_with_bamini_font_fails():
    assert not text_layer_ok(OLD_FONT_TEXT, {"ABCDEF+Bamini"})


def test_empty_page_fails():
    assert not text_layer_ok("", set())
    assert not text_layer_ok("   \n  ", {"Helvetica"})


def test_too_short_page_fails():
    assert not text_layer_ok("Chapter 1", {"Helvetica"})


def test_old_font_text_with_harmless_font_name_fails_via_punctuation():
    assert len(OLD_FONT_TEXT.replace(" ", "")) >= pages.MIN_CHARS
    assert not text_layer_ok(OLD_FONT_TEXT, {"ABCDEF+Arial"})
    assert not text_layer_ok(OLD_FONT_TEXT, set())


def test_ordinary_english_passes():
    assert text_layer_ok(ENGLISH, {"ABCDEF+Times-Roman"})


def test_normal_font_not_mistaken_for_old_font():
    assert text_layer_ok(ENGLISH, {"Table-Bold", "ABCDEF+Latha", "Helvetica"})


# --- text_difference ---

def test_screen_order_tamil_with_missing_i_fails():
    # The rule book bug: this used to pass, so the scrambled text was saved and search missed "விதி".
    assert text_layer_ok(SCRAMBLED, NOTO) is False


def test_screen_order_tamil_fails_even_when_i_is_mapped():
    # Another font may map ி correctly but still put ெ ே ை before the letter: 6 of 20 words start with one.
    assert text_layer_ok(SCRAMBLED.replace("\x00", "ி"), NOTO) is False


def test_same_text_in_correct_order_passes():
    assert text_layer_ok(UNSCRAMBLED, NOTO) is True


def test_one_stray_sign_from_ocr_noise_still_passes():
    # Archive.org text layers have the odd stray sign (at most 1.8% of words on 9 real books): not a reason to OCR.
    assert text_layer_ok(TAMIL + " ேமலும் இது நல்ல நூல்.", NOTO) is True


def test_replacement_character_fails():
    assert text_layer_ok(TAMIL + " வ\ufffdதி", set()) is False


@pytest.mark.skipif(not os.environ.get("KB_SCRAMBLED_TAMIL_PDF"),
                    reason="set KB_SCRAMBLED_TAMIL_PDF to a Chrome-printed Tamil PDF (the client's rule book is not in the repo)")
def test_every_page_of_the_real_scrambled_pdf_goes_to_ocr():
    path = os.environ["KB_SCRAMBLED_TAMIL_PDF"]
    trusted = [no for no in range(1, count_pages(path) + 1) if text_layer_ok(*read_page(path, no))]
    assert trusted == []


def test_text_difference_identical_and_whitespace_only():
    assert text_difference("abc def", "abc def") == 0.0
    assert text_difference("abc  def\n", "abcdef") == 0.0
    assert text_difference("", "") == 0.0


def test_text_difference_nothing_in_common():
    assert text_difference("aaaaaaaa", "zzzzzzzz") == 1.0
    assert text_difference("abc", "") == 1.0


def test_text_difference_partial():
    d = text_difference("the quick brown fox", "the quick brown cat")
    assert 0.0 < d < pages.SPOT_DIFF


# --- pick_spot_check_pages ---

def test_spot_check_spread_first_middle_last():
    assert pick_spot_check_pages(list(range(1, 11))) == [1, 5, 10]
    assert pick_spot_check_pages(list(range(1, 12))) == [1, 6, 11]


def test_spot_check_fewer_pages_than_count():
    assert pick_spot_check_pages([]) == []
    assert pick_spot_check_pages([7]) == [7]
    assert pick_spot_check_pages([2, 9]) == [2, 9]
    assert pick_spot_check_pages([2, 4, 9]) == [2, 4, 9]


def test_spot_check_is_deterministic_and_uses_given_numbers():
    pages_ = [3, 4, 8, 9, 20, 21, 22]
    assert pick_spot_check_pages(pages_) == pick_spot_check_pages(pages_) == [3, 9, 22]
    assert pick_spot_check_pages([5, 1, 3]) == [1, 3, 5]


# --- distrust_text_layer ---

BAD = ("abcdefgh", "zzzzzzzz")
GOOD = ("same text here", "same text here")


def test_distrust_when_two_of_three_differ():
    assert distrust_text_layer([BAD, BAD, GOOD])


def test_no_distrust_when_only_one_differs():
    assert not distrust_text_layer([BAD, GOOD, GOOD])


def test_no_distrust_for_empty_list():
    assert not distrust_text_layer([])


# --- count_pages / read_page ---

def test_image_only_pdf_has_no_text_layer(tmp_path):
    path = str(tmp_path / "scan.pdf")
    img = Image.new("RGB", (200, 200), "white")
    img.save(path, save_all=True, append_images=[Image.new("RGB", (200, 200), "gray")])
    assert count_pages(path) == 2
    assert read_page(path, 1) == ("", set())
    assert read_page(path, 2) == ("", set())


def test_pdf_with_text_layer(tmp_path):
    path = tmp_path / "text.pdf"
    path.write_bytes(_hand_made_pdf("Hello world from a text layer"))
    assert count_pages(str(path)) == 1
    text, fonts = read_page(str(path), 1)
    assert "Hello world from a text layer" in text
    assert fonts == {"Helvetica"}
