"""Tests for app.companion.kb.filetypes: which files the knowledge base accepts and how the
non-PDF ones become text and "virtual pages" of 3,000 characters."""
import ast
import csv
import inspect

import pytest

from app.companion.kb import filetypes
from app.companion.kb.filetypes import (
    ACCEPTED_TYPES,
    IMAGE_MIME,
    PAGE_CHARS,
    UnsupportedFileType,
    extract_text,
    file_type_of,
    kind_of,
    virtual_pages,
)


# ---------- file_type_of / kind_of ----------

def test_file_type_of_is_case_insensitive_and_takes_last_extension():
    assert file_type_of("Book 7.PDF") == "pdf"
    assert file_type_of("a.b.c.docx") == "docx"
    assert file_type_of("scan.JPeG") == "jpeg"


@pytest.mark.parametrize("ext", ["pdf", "png", "jpg", "jpeg", "txt", "md", "json", "csv", "docx", "pptx", "xlsx"])
def test_every_accepted_type_is_accepted(ext):
    assert ext in ACCEPTED_TYPES
    assert file_type_of(f"x.{ext}") == ext


@pytest.mark.parametrize("name,message", [
    ("old.doc", "Old Word files (.doc) are not supported. Save the file as .docx and upload it again."),
    ("old.ppt", "Old PowerPoint files (.ppt) are not supported. Save the file as .pptx and upload it again."),
    ("old.xls", "Old Excel files (.xls) are not supported. Save the file as .xlsx and upload it again."),
    ("clip.mp4", "Video files are not supported yet."),
    ("thing.xyz", "This file type (.xyz) is not supported."),
])
def test_refused_types_have_a_readable_message(name, message):
    with pytest.raises(UnsupportedFileType) as exc:
        file_type_of(name)
    assert str(exc.value) == message


def test_unsupported_is_a_value_error():
    assert issubclass(UnsupportedFileType, ValueError)


def test_no_extension_is_refused_clearly():
    for name in ("README", "trailing.", ""):
        with pytest.raises(UnsupportedFileType) as exc:
            file_type_of(name)
        assert "extension" in str(exc.value)


def test_kind_of():
    assert kind_of("png") == "image"
    assert kind_of("jpg") == "image"
    assert kind_of("pdf") == "pdf"
    assert kind_of("docx") == "text"
    assert kind_of("csv") == "text"
    with pytest.raises(UnsupportedFileType):
        kind_of("mp4")


def test_image_mime():
    assert IMAGE_MIME == {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


# ---------- extract_text ----------

def test_extract_text_rejects_non_text_types(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF")
    with pytest.raises(UnsupportedFileType):
        extract_text(str(p), "pdf")
    with pytest.raises(UnsupportedFileType):
        extract_text(str(p), "png")


@pytest.mark.parametrize("ext,body", [
    ("txt", "Line one\nLine two\n\nவணக்கம்"),
    ("md", "# Title\n\nSome *text*\n\n## Sub\n- a\n- b\n"),
    ("json", '{"a": 1,\n  "b": ["x", "y"]}'),
])
def test_plain_text_round_trip(tmp_path, ext, body):
    p = tmp_path / f"f.{ext}"
    p.write_text(body, encoding="utf-8")
    assert extract_text(str(p), ext) == body


def test_text_accepts_bom_and_survives_bad_bytes(tmp_path):
    bom = tmp_path / "bom.txt"
    bom.write_bytes(b"\xef\xbb\xbfhello")
    assert extract_text(str(bom), "txt") == "hello"
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"ok \xff\xfe end")
    out = extract_text(str(bad), "txt")
    assert out.startswith("ok ") and out.endswith(" end")


def test_csv_one_line_per_row_joined_with_pipes(tmp_path):
    p = tmp_path / "t.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "city"])
        w.writerow(["Asha, K", "Chennai"])
    assert extract_text(str(p), "csv").splitlines() == ["name | city", "Asha, K | Chennai"]


def test_docx_paragraphs_headings_and_tables_in_body_order(tmp_path):
    import docx

    d = docx.Document()
    d.add_heading("Chapter One", level=2)
    d.add_paragraph("Intro paragraph before the table.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Planet"
    t.cell(0, 1).text = "Day"
    t.cell(1, 0).text = "Saturn"
    t.cell(1, 1).text = "Saturday"
    d.add_paragraph("Closing paragraph after the table.")
    p = tmp_path / "b.docx"
    d.save(str(p))

    out = extract_text(str(p), "docx")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines == [
        "## Chapter One",
        "Intro paragraph before the table.",
        "Planet | Day",
        "Saturn | Saturday",
        "Closing paragraph after the table.",
    ]


def test_docx_heading_1_is_one_hash(tmp_path):
    import docx

    d = docx.Document()
    d.add_heading("Heading One", level=1)
    d.add_paragraph("body")
    p = tmp_path / "h.docx"
    d.save(str(p))
    assert extract_text(str(p), "docx").splitlines()[0] == "# Heading One"


def test_xlsx_reads_every_sheet(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "First"
    ws1.append(["a", "b"])
    ws1.append([None, None])
    ws1.append([1, 2])
    ws2 = wb.create_sheet("Second")
    ws2.append(["needle-from-sheet-2", "z"])
    p = tmp_path / "w.xlsx"
    wb.save(str(p))

    out = extract_text(str(p), "xlsx")
    assert "## First" in out and "## Second" in out
    assert "needle-from-sheet-2 | z" in out
    lines = out.splitlines()
    assert lines.index("## First") < lines.index("a | b") < lines.index("1 | 2") < lines.index("## Second")
    assert not any(ln.strip() == "" for ln in lines)  # empty row skipped


def test_pptx_slide_text_and_tables(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Slide title here"
    s1.placeholders[1].text = "Bullet body text"
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    gt = s2.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(2)).table
    gt.cell(0, 0).text = "k"
    gt.cell(0, 1).text = "v"
    gt.cell(1, 0).text = "sun"
    gt.cell(1, 1).text = "Sunday"
    p = tmp_path / "d.pptx"
    prs.save(str(p))

    out = extract_text(str(p), "pptx")
    lines = out.splitlines()
    assert "## Slide 1" in lines and "## Slide 2" in lines
    assert "Slide title here" in out and "Bullet body text" in out
    assert "sun | Sunday" in lines
    assert lines.index("## Slide 1") < lines.index("Slide title here") < lines.index("## Slide 2")


# ---------- virtual_pages ----------

def test_virtual_pages_empty():
    assert virtual_pages("") == []
    assert virtual_pages("   \n\n  ") == []


def test_virtual_pages_default_size():
    assert PAGE_CHARS == 3000


def test_virtual_pages_7000_chars_of_lines():
    lines = [f"line {i:04d} " + "x" * 40 for i in range(130)]  # 50 chars + "\n" each = 51
    text = "\n".join(lines)
    assert 6500 < len(text) < 7100
    pages = virtual_pages(text)
    assert len(pages) == 3
    assert all(0 < len(pg) <= 3000 for pg in pages)
    page_lines = [ln for pg in pages for ln in pg.splitlines()]
    assert page_lines == lines  # no line cut, nothing lost, order kept


def test_virtual_pages_loses_no_text_and_never_returns_blank_pages():
    text = "\n".join(["alpha beta", "", "", "gamma"] * 400)
    pages = virtual_pages(text, size=100)
    assert all(pg.strip() for pg in pages)
    assert all(len(pg) <= 100 for pg in pages)
    assert "".join("".join(pg.split()) for pg in pages) == "".join(text.split())


def test_virtual_pages_cuts_a_single_overlong_line():
    text = "y" * 7000
    pages = virtual_pages(text)
    assert [len(p) for p in pages] == [3000, 3000, 1000]
    assert "".join(pages) == text


def test_virtual_pages_short_text_is_one_page():
    assert virtual_pages("hello\nworld") == ["hello\nworld"]


def test_virtual_pages_overlong_line_after_short_lines():
    text = "head\n" + "z" * 250 + "\ntail"
    pages = virtual_pages(text, size=100)
    assert all(len(p) <= 100 for p in pages)
    assert "".join("".join(p.split()) for p in pages) == "".join(text.split())


# ---------- separation from the other product ----------

def test_does_not_import_the_sales_knowledge_service():
    tree = ast.parse(inspect.getsource(filetypes))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [a.name for a in node.names]
    assert not any("knowledge_service" in name for name in imported)


# ---------- hostile and odd files ----------

def test_the_one_size_limit_lives_here():
    assert filetypes.MAX_BYTES == 300 * 1024 * 1024
    assert filetypes.MAX_UNZIPPED_BYTES == 200 * 1024 * 1024


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_an_office_file_that_is_not_a_real_archive_is_refused_in_plain_words(tmp_path, ext):
    path = tmp_path / f"broken.{ext}"
    path.write_bytes(b"this is not a zip archive at all")
    with pytest.raises(UnsupportedFileType) as exc:
        extract_text(str(path), ext)
    assert str(exc.value) == filetypes.BROKEN_OFFICE_ERROR


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_an_office_file_that_unpacks_too_big_is_refused_before_it_is_opened(tmp_path, monkeypatch, ext):
    import zipfile

    path = tmp_path / f"bomb.{ext}"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * 5000)     # 5,000 bytes unpacked, a few dozen packed
    monkeypatch.setattr(filetypes, "MAX_UNZIPPED_BYTES", 4000)
    opened = []
    monkeypatch.setattr(filetypes, "_docx_text", lambda p: opened.append(p))
    monkeypatch.setattr(filetypes, "_pptx_text", lambda p: opened.append(p))
    monkeypatch.setattr(filetypes, "_xlsx_text", lambda p: opened.append(p))
    with pytest.raises(UnsupportedFileType) as exc:
        extract_text(str(path), ext)
    assert str(exc.value) == filetypes.TOO_BIG_UNPACKED_ERROR
    assert opened == []                                   # the parser never saw the file


def test_utf16_text_is_read_and_carries_no_nul_bytes(tmp_path):
    for name, raw in (("le.txt", "வணக்கம் Saturn".encode("utf-16")),              # BOM + little endian
                      ("be.txt", b"\xfe\xff" + "வணக்கம் Saturn".encode("utf-16-be"))):
        path = tmp_path / name
        path.write_bytes(raw)
        assert extract_text(str(path), "txt") == "வணக்கம் Saturn"


def test_nul_bytes_never_leave_the_reader(tmp_path):
    path = tmp_path / "nul.txt"
    path.write_bytes(b"Saturn\x00 rules\x00 delay")
    assert extract_text(str(path), "txt") == "Saturn rules delay"
    path = tmp_path / "nul.csv"
    path.write_bytes(b"a\x00,b\n")
    assert "\x00" not in extract_text(str(path), "csv")
