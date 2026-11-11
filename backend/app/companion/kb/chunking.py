"""Cut the text of a book into searchable passages (companion_kb passages). Pure logic, no I/O.

Input: the text of every page that was read, as (page_no, text) in page order. Output: passages of
about TARGET_CHARS characters in reading order, each with its heading path and page range.

How it cuts, in this order:
1. Text flows across pages. Every line remembers its page, so a passage can run from page 44 to 45.
2. A markdown heading ("#" to "######") starts a new passage and sets the heading path:
   "Book 7 > Chapter 4 > Saturn". A deeper heading replaces deeper levels, a shallower one clears them.
3. Inside a heading section the text is BLOCKS: runs of non-blank lines (a paragraph, a verse, a table).
   Blocks are packed until the next one would pass the target. A block is never cut, so a verse stays
   whole and a table row is never split. The heading line is glued to the first block under it.
4. A block longer than MAX_CHARS (a huge table) is cut between lines; a single line longer than
   MAX_CHARS is cut at a sentence end, or failing that at a space.
5. Overlap: each passage after the first in a section opens with the last whole block(s) of the
   passage before it, up to OVERLAP * target characters, so an answer on a boundary is found from
   either side. If the last block is bigger than that budget, no overlap (we do not cut a block).
   Overlap never crosses a heading.

Worked example (target 1800, overlap 0.15 so a budget of 270):
    "# Chapter 4" / "## Saturn" / thirty 200-character paragraphs
    -> passage 1: "## Saturn" glued to paragraph 1, then paragraphs up to ~1800 chars, path "Book 7 > Chapter 4 > Saturn"
    -> passage 2: starts with the last paragraph of passage 1 again (200 <= 270), then new paragraphs.
A passage can pass the target by one block, and MAX_CHARS keeps a passage with overlap from growing
past about 3,600 characters. Length is counted in characters, so Tamil and English behave the same.
"""
import re

TARGET_CHARS = 1800
OVERLAP = 0.15
MAX_CHARS = 3600        # a single block longer than this is split at line breaks

_HEADING = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*#*[ \t]*$")
_SENTENCE_END = re.compile(r"[.!?।][\"'”’)\]]*\s")

Line = tuple[int, str]                 # (page_no, text of the line)
Unit = tuple[list[Line], str]          # (lines, separator written before it when joined to the unit before)


def _lines_of(pages: list[tuple[int, str]]) -> list[Line]:
    out: list[Line] = []
    for page_no, text in pages:
        for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            out.append((page_no, raw.rstrip()))
    return out


def _heading(line: str) -> tuple[int, str] | None:
    m = _HEADING.match(line)
    return (len(m.group(1)), m.group(2)) if m else None


def _blocks(lines: list[Line]) -> list[list[Line]]:
    """Runs of consecutive non-blank lines."""
    blocks: list[list[Line]] = []
    cur: list[Line] = []
    for ln in lines:
        if ln[1].strip():
            cur.append(ln)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def _size(lines: list[Line]) -> int:
    return sum(len(t) for _, t in lines) + max(len(lines) - 1, 0)


def _split_long_line(page: int, text: str, limit: int) -> list[Line]:
    """Cut one over-long line into pieces of at most `limit`: at a sentence end, else at a space."""
    pieces: list[Line] = []
    rest = text.strip()
    while len(rest) > limit:
        window = rest[: limit + 1]
        cut = 0
        for m in _SENTENCE_END.finditer(window):
            cut = m.end() - 1               # just after the punctuation (and any closing quote)
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        piece, rest = rest[:cut].rstrip(), rest[cut:].lstrip()
        if piece:
            pieces.append((page, piece))
    if rest:
        pieces.append((page, rest))
    return pieces


def _units(block: list[Line]) -> list[Unit]:
    """A normal block is one unit. A giant block becomes one unit per line (joined with a single newline)."""
    if _size(block) <= MAX_CHARS:
        return [(block, "\n\n")]
    lines: list[Line] = []
    for page, text in block:
        lines.extend(_split_long_line(page, text, MAX_CHARS) if len(text) > MAX_CHARS else [(page, text)])
    return [([ln], "\n\n" if i == 0 else "\n") for i, ln in enumerate(lines)]


def _passage_size(units: list[Unit]) -> int:
    return sum(_size(lines) for lines, _ in units) + sum(len(sep) for _, sep in units[1:])


def _text(units: list[Unit]) -> str:
    parts: list[str] = []
    for i, (lines, sep) in enumerate(units):
        if i:
            parts.append(sep)
        parts.append("\n".join(t for _, t in lines))
    return "".join(parts).strip()


def _tail(units: list[Unit], budget: float) -> list[Unit]:
    """The trailing whole units that fit in the budget (none if even the last one is too big)."""
    taken: list[Unit] = []
    for unit in reversed(units):
        if _passage_size([unit, *taken]) > budget:
            break
        taken.insert(0, unit)
    return taken


def _pack(units: list[Unit], target: int, overlap: float) -> list[list[Unit]]:
    """Group units into passages of about `target` characters, each opening with the overlap."""
    budget = overlap * target
    passages: list[list[Unit]] = []
    cur: list[Unit] = []
    fresh = 0                                   # how many units in `cur` are new (not overlap)
    for unit in units:
        if fresh and _passage_size(cur + [unit]) > target:
            passages.append(cur)
            carry = _tail(cur, budget)
            if carry and _passage_size(carry + [unit]) > MAX_CHARS:
                carry = []
            cur, fresh = carry, 0
        cur = cur + [unit]
        fresh += 1
    if fresh:
        passages.append(cur)
    return passages


def _sections(lines: list[Line]) -> list[tuple[list[tuple[int, str]], list[Line]]]:
    """Split on headings. Each section is (heading levels so far as [(level, text)], its lines)."""
    sections: list[tuple[list[tuple[int, str]], list[Line]]] = []
    levels: list[tuple[int, str]] = []
    cur: list[Line] = []
    cur_levels: list[tuple[int, str]] = []
    for ln in lines:
        h = _heading(ln[1])
        if h:
            if cur:
                sections.append((cur_levels, cur))
            levels = [(lv, tx) for lv, tx in levels if lv < h[0]] + [h]
            cur_levels, cur = list(levels), [ln]
        else:
            cur.append(ln)
    if cur:
        sections.append((cur_levels, cur))
    return sections


def chunk_pages(pages: list[tuple[int, str]], *, title: str,
                target: int = TARGET_CHARS, overlap: float = OVERLAP) -> list[dict]:
    """pages: (page_no, text) for every page that was read, in page order (failed pages are simply absent).
    Returns passages in reading order, each:
      {"heading_path": "Book 7 > Chapter 4 > Saturn", "text": "...", "page_from": 44, "page_to": 45}"""
    out: list[dict] = []
    for levels, lines in _sections(_lines_of(pages)):
        path = " > ".join(([title] if title else []) + [tx for _, tx in levels])
        first_is_heading = _heading(lines[0][1]) is not None
        blocks = _blocks(lines[1:] if first_is_heading else lines)
        if first_is_heading:
            head = [lines[0]]
            blocks = [head + blocks[0]] + blocks[1:] if blocks else [head]
        units = [u for block in blocks for u in _units(block)]
        for passage in _pack(units, target, overlap):
            text = _text(passage)
            if not text:
                continue
            all_lines = [ln for lines_, _ in passage for ln in lines_]
            out.append({
                "heading_path": path,
                "text": text,
                "page_from": all_lines[0][0],
                "page_to": all_lines[-1][0],
            })
    return out
