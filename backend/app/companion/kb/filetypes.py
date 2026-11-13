"""Which files the Anril Agents knowledge base accepts, and how the non-PDF ones become pages.

The page ledger works one page at a time. A PDF has real pages and an image is one page, but Word,
PowerPoint, Excel, CSV and plain text have none. So their text is pulled out and cut into "virtual
pages" of PAGE_CHARS (3,000) characters, and the same ledger, retry and page reference work for them.

Worked example: "Remedies.docx" holds a heading, a paragraph and a 2-row table.
  file_type_of("Remedies.DOCX")  -> "docx"       kind_of("docx") -> "text"
  extract_text(path, "docx")     -> "## Saturn\\nSaturn rules delay.\\nPlanet | Day\\nSaturn | Saturday"
  virtual_pages(that_text)       -> ["## Saturn\\n...Saturn | Saturday"]   (one page, it is short)
A 7,000-character text becomes 3 pages, each cut at a line break, never in the middle of a line
(unless one line alone is longer than a page).

This module is deliberately separate from app.services.knowledge_service (Anril Sales' reader).
It never raises on odd bytes in text files; it raises UnsupportedFileType, with a sentence an owner
can read, for file types we refuse and for Word/PowerPoint/Excel files that are broken or that
unpack to more than MAX_UNZIPPED_BYTES.
"""
import csv
import io
import os
import re
import zipfile

PAGE_CHARS = 3000
# The ONE place the per-file size limit lives. 300 MB: AstroTamil's biggest scanned book is 227 MB.
# Supabase Pro allows it only after the project's global file size limit (Storage settings) is raised
# to at least 300 MB. The storage bucket carries the same number as its file_size_limit (migration 264).
MAX_BYTES = 300 * 1024 * 1024
# A .docx/.pptx/.xlsx is a zip archive. A small zip can unpack to many gigabytes (a "zip bomb") and
# take the whole server down, so the sizes the archive itself declares are added up before any
# parser opens it. This stays 200 MB (below the upload limit): the office parsers load every part
# into memory, and a real text document is far smaller. Big scanned books come as PDFs.
MAX_UNZIPPED_BYTES = 200 * 1024 * 1024
BROKEN_OFFICE_ERROR = (
    "This file could not be opened. It may be damaged or password-protected. "
    "Open it on your computer, save it again and upload the new copy."
)
TOO_BIG_UNPACKED_ERROR = (
    "This file is too large to read once it is unpacked. "
    "Split it into smaller files and upload them one by one."
)
PDF_TYPES = ("pdf",)
IMAGE_TYPES = ("png", "jpg", "jpeg")
TEXT_TYPES = ("txt", "md", "json", "csv", "docx", "pptx", "xlsx")
ACCEPTED_TYPES = PDF_TYPES + IMAGE_TYPES + TEXT_TYPES
IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

_OLD_OFFICE = {
    "doc": ("Word", "docx"),
    "ppt": ("PowerPoint", "pptx"),
    "xls": ("Excel", "xlsx"),
}
_SEP = " | "


class UnsupportedFileType(ValueError):
    """The file type is not accepted. str(exc) is a sentence the owner can read."""


def file_type_of(filename: str) -> str:
    """Lower-case extension of an accepted file ("Book 7.PDF" -> "pdf"); else UnsupportedFileType."""
    ext = os.path.splitext(filename or "")[1].lstrip(".").strip().lower()
    if not ext:
        raise UnsupportedFileType(
            "This file has no extension (like .pdf or .docx), so we cannot tell what it is."
        )
    if ext in ACCEPTED_TYPES:
        return ext
    if ext in _OLD_OFFICE:
        name, new = _OLD_OFFICE[ext]
        raise UnsupportedFileType(
            f"Old {name} files (.{ext}) are not supported. Save the file as .{new} and upload it again."
        )
    if ext == "mp4":
        raise UnsupportedFileType("Video files are not supported yet.")
    raise UnsupportedFileType(f"This file type (.{ext}) is not supported.")


def kind_of(file_type: str) -> str:
    """"pdf", "image" or "text" for an accepted type; else UnsupportedFileType."""
    ft = (file_type or "").lower()
    if ft in PDF_TYPES:
        return "pdf"
    if ft in IMAGE_TYPES:
        return "image"
    if ft in TEXT_TYPES:
        return "text"
    raise UnsupportedFileType(f"This file type (.{ft}) is not supported.")


def extract_text(path: str, file_type: str) -> str:
    """The text of a TEXT_TYPES file. Raises UnsupportedFileType for any other type."""
    ft = (file_type or "").lower()
    if ft not in TEXT_TYPES:
        raise UnsupportedFileType(f"Text cannot be read directly from .{ft} files.")
    if ft in ("txt", "md", "json"):
        return _decode(_read_bytes(path))
    if ft == "csv":
        return _csv_text(_decode(_read_bytes(path)))
    _check_office_archive(path)
    if ft == "docx":
        text = _docx_text(path)
    elif ft == "pptx":
        text = _pptx_text(path)
    else:
        text = _xlsx_text(path)
    return text.replace("\x00", "")


def text_pages(path: str, file_type: str) -> list[str]:
    """The pages of a TEXT_TYPES file: extract_text cut by virtual_pages. Runs in the helper process."""
    return virtual_pages(extract_text(path, file_type))


def virtual_pages(text: str, size: int = PAGE_CHARS) -> list[str]:
    """Cut text into pages of at most `size` characters, breaking at a line break when the piece has one.

    Never returns an empty or whitespace-only page. Joining the pages loses no non-whitespace text.
    """
    pages: list[str] = []
    pos, n = 0, len(text)
    while pos < n:
        if n - pos <= size:
            cut, nxt = n, n
        else:
            idx = text.rfind("\n", pos, pos + size + 1)  # +1: a newline right after the piece is a clean cut
            if idx >= 0:
                cut, nxt = idx, idx + 1
            else:
                cut = nxt = pos + size                    # one line longer than a page: hard cut
        page = text[pos:cut].strip("\r\n")
        if page.strip():
            pages.append(page)
        pos = nxt
    return pages


# ---------- readers ----------

def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _decode(raw: bytes) -> str:
    """Bytes of a text file as text. Never raises, and never returns a NUL character: Postgres
    refuses a text value with one in it, and Windows Notepad's "Unicode" (UTF-16) files are full
    of them when read as UTF-8."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):        # UTF-16 byte-order mark
        text = raw.decode("utf-16", errors="replace")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
    return text.replace("\x00", "")


def _check_office_archive(path: str) -> None:
    """Refuse a Word/PowerPoint/Excel file that is not a real archive or that unpacks too big.
    Reads only the archive's list of contents, never the contents themselves."""
    try:
        with zipfile.ZipFile(path) as archive:
            unpacked = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise UnsupportedFileType(BROKEN_OFFICE_ERROR) from exc
    if unpacked > MAX_UNZIPPED_BYTES:
        raise UnsupportedFileType(TOO_BIG_UNPACKED_ERROR)


def _cell(value) -> str:
    """One cell as one line of text."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _row_line(values) -> str:
    """Cells joined with ' | ', or '' when every cell is empty."""
    cells = [_cell(v) for v in values]
    return _SEP.join(cells) if any(cells) else ""


def _csv_text(text: str) -> str:
    lines = (_row_line(row) for row in csv.reader(io.StringIO(text, newline="")))
    return "\n".join(ln for ln in lines if ln)


def _docx_text(path: str) -> str:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(path)
    out: list[str] = []
    for child in document.element.body.iterchildren():   # body order: paragraphs and tables interleaved
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            text = para.text.strip()
            if not text:
                continue
            m = re.match(r"Heading (\d+)$", para.style.name if para.style is not None else "")
            out.append(f"{'#' * int(m.group(1))} {text}" if m else text)
        elif child.tag == qn("w:tbl"):
            out.extend(_docx_table_lines(Table(child, document)))
    return "\n".join(out)


def _docx_table_lines(table) -> list[str]:
    lines = []
    for row in table.rows:
        cells, last_tc = [], None
        for c in row.cells:
            if c._tc is last_tc:        # a merged cell comes back once per column it spans
                continue
            last_tc = c._tc
            cells.append(c.text)
        line = _row_line(cells)
        if line:
            lines.append(line)
    return lines


def _pptx_text(path: str) -> str:
    from pptx import Presentation

    out: list[str] = []
    for n, slide in enumerate(Presentation(path).slides, start=1):
        out.append(f"## Slide {n}")
        _pptx_shapes(slide.shapes, out)
    return "\n".join(out)


def _pptx_shapes(shapes, out: list[str]) -> None:
    for shape in shapes:
        if getattr(shape, "shape_type", None) == 6:          # MSO_SHAPE_TYPE.GROUP
            _pptx_shapes(shape.shapes, out)
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                line = _row_line(c.text for c in row.cells)
                if line:
                    out.append(line)
        elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            text = shape.text_frame.text.strip()
            if text:
                out.append(text)


def _xlsx_text(path: str) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        out: list[str] = []
        for ws in wb.worksheets:
            out.append(f"## {ws.title}")
            for row in ws.iter_rows(values_only=True):
                line = _row_line(row)
                if line:
                    out.append(line)
        return "\n".join(out)
    finally:
        wb.close()
