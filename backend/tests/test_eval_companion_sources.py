"""source_marks: did the search find the expected file, did the judge keep it, did the reply cite it."""
from scripts.eval_companion import _parse_source_grade, GraderError, source_marks

BOOK = "15 சோதிட அகராதி"


def _c(doc, kept):
    return {"document": doc, "kept": kept}


def test_book_found_kept_and_cited():
    q = {"expect_tier": 2, "expect_doc": BOOK}
    marks = source_marks(q, [_c("00 Rule Book", True), _c(BOOK, True)], [{"document": BOOK}], "book")
    assert marks == {"found": True, "kept": True, "right_source": True}


def test_book_found_but_judge_dropped_it():
    q = {"expect_tier": 2, "expect_doc": BOOK}
    marks = source_marks(q, [_c("00 Rule Book", True), _c(BOOK, False)], [{"document": "00 Rule Book"}], "primary")
    assert marks == {"found": True, "kept": False, "right_source": False}


def test_book_never_searched():
    q = {"expect_tier": 2, "expect_doc": BOOK}
    assert source_marks(q, [_c("00 Rule Book", True)], [], "primary")["found"] is False


def test_no_file_has_it_passes_only_when_nothing_kept_or_cited():
    q = {"expect_tier": 0, "expect_doc": None}
    assert source_marks(q, [_c(BOOK, False)], [], "own") == {"found": True, "kept": True, "right_source": True}
    assert source_marks(q, [_c(BOOK, True)], [{"document": BOOK}], "book") == {
        "found": True, "kept": False, "right_source": False}


def test_source_grade_parse():
    assert _parse_source_grade('x {"key": true, "clear": false, "friendly": true, "note": "ok"}') == {
        "key": True, "clear": False, "friendly": True, "note": "ok"}
    try:
        _parse_source_grade('{"key": true}')
    except GraderError:
        pass
    else:
        raise AssertionError("missing marks must raise")
