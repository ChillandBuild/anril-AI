"""Guards in scripts/second_brain_close.py that keep .agents/decisions/log.md cheap to search.

Why they exist (measured 2026-11-28): one log heading had grown to 193,869 characters because
three months of entries were filed under it, and the migration index had stopped at 224 while
the newest migration was 350. Both made every lookup cost more context than it should.
"""
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "second_brain_close.py"
_spec = importlib.util.spec_from_file_location("second_brain_close", _SCRIPT)
sbc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sbc)


def _log(index_rows, extra=""):
    rows = "\n".join(f"| **{n}** | some scope |" for n in index_rows)
    return (
        "# Decisions\n\n"
        "## DB Migrations Index (120–999, generated from filenames)\n\n"
        "| Migration | Scope |\n|---|---|\n"
        f"{rows}\n\n---\n\n"
        "## 2026-07-01 — A dated entry\n- **Decision**: something.\n"
        f"{extra}"
    )


# --- migration index -------------------------------------------------------------------------

def test_index_gap_flags_migrations_missing_from_the_index():
    issues = sbc.migration_index_gap(_log([223, 224]), [223, 224, 225, 350])
    assert len(issues) == 1
    assert "224" in issues[0] and "350" in issues[0]


def test_index_gap_is_quiet_when_the_index_is_current():
    assert sbc.migration_index_gap(_log([349, 350]), [349, 350]) == []


def test_index_gap_flags_a_second_file_sharing_an_indexed_number():
    # Two people can each add a migration with the same number (248, 273, 295... did this).
    issues = sbc.migration_index_gap(_log([349, 350]), [349, 350, 350])
    assert len(issues) == 1 and "350" in issues[0]


def test_index_gap_flags_a_hole_below_the_newest_number():
    issues = sbc.migration_index_gap(_log([348, 350]), [348, 349, 350])
    assert len(issues) == 1 and "349" in issues[0]


def test_index_gap_ignores_migrations_older_than_the_index():
    # Numbers below the table's first row live in the separate historical index.
    assert sbc.migration_index_gap(_log([349, 350]), [51, 119, 349, 350]) == []


def test_index_gap_ignores_rows_in_later_sections():
    # A dated entry further down may contain its own table; only the index section counts.
    extra = "\n| **900** | a table inside a dated entry |\n"
    issues = sbc.migration_index_gap(_log([223, 224], extra), [224, 350])
    assert len(issues) == 1 and "224" in issues[0]


def test_index_gap_reports_a_missing_index_section():
    issues = sbc.migration_index_gap("# Decisions\n\n## 2026-07-01 — entry\n", [350])
    assert len(issues) == 1 and "index" in issues[0].lower()


# --- oversized sections ----------------------------------------------------------------------

def test_oversized_sections_flags_a_section_over_the_limit():
    big = "## 2026-07-01 — Callback notifications\n" + ("- **Decision**: " + "x" * 200 + "\n") * 150
    text = "# Decisions\n\n## 2026-06-30 — Small entry\n- fine\n\n" + big
    issues = sbc.oversized_sections(text, limit=20_000)
    assert len(issues) == 1
    assert "Callback notifications" in issues[0]


def test_oversized_sections_is_quiet_when_every_section_fits():
    text = "# Decisions\n\n## 2026-06-30 — One\n- fine\n\n## 2026-07-01 — Two\n- also fine\n"
    assert sbc.oversized_sections(text, limit=20_000) == []


def test_oversized_sections_measures_each_section_separately():
    # Two sections that are each under the limit must not be added together.
    part = "- **Decision**: " + "x" * 200 + "\n"
    text = "## 2026-07-01 — One\n" + part * 60 + "## 2026-07-02 — Two\n" + part * 60
    assert sbc.oversized_sections(text, limit=20_000) == []
