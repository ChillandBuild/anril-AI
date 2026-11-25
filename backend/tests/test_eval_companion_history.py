"""The memory eval's score history: one line per full run (code only, no AI calls)."""
from evals.companion_memory import history

SUMMARY = {
    "memory_mode": "auto", "probe_model": "gemini",
    "languages": {
        "en": {"probes": 60, "pass": 56}, "ta": {"probes": 60, "pass": 55}, "ta-en": {"probes": 60, "pass": 60},
        "all": {"probes": 180, "pass": 171, "invented": 2, "errors": 0, "unjudged": 0, "memory_ms_p95": 1190.4,
                "by_kind": {"recall": {"n": 125, "pass": 119}, "false": {"n": 30, "pass": 29}}},
    },
}


def test_row_holds_the_numbers_a_run_is_judged_by():
    line = history.row(SUMMARY, "2026-11-25", "d51ba732", "after the dedup fix")
    assert set(line) == set(history.COLUMNS)
    assert (line["probes"], line["passed"], line["recall_n"], line["recall_passed"], line["invented"]) == \
        (180, 171, 125, 119, 2)
    assert (line["en_passed"], line["ta_passed"], line["ta-en_passed"], line["ta-en_probes"]) == (56, 55, 60, 60)


def test_append_then_load_round_trips_and_last_run_is_per_mode(tmp_path):
    path = tmp_path / "history.csv"
    assert history.load(path) == [] and history.last_run("auto", path) is None
    first = history.row(SUMMARY, "2026-11-25", "aaaa1111")
    agentic = {**history.row(SUMMARY, "2026-11-26", "bbbb2222"), "memory_mode": "agentic", "errors": None}
    history.append(first, path)
    history.append(agentic, path)
    rows = history.load(path)
    assert [r["commit"] for r in rows] == ["aaaa1111", "bbbb2222"]
    assert rows[0]["passed"] == 171 and rows[0]["memory_ms_p95"] == 1190.4 and rows[1]["errors"] is None
    assert history.last_run("auto", path)["commit"] == "aaaa1111"
    assert history.last_run("agentic", path)["commit"] == "bbbb2222"


def test_the_recorded_baseline_file_loads():
    rows = history.load()
    assert rows and rows[0]["date"] == "2026-11-10" and rows[0]["probes"] == 180


def test_verdict_says_first_run_or_a_changed_probe_set_instead_of_comparing():
    line = history.row(SUMMARY, "2026-11-25", "d51ba732")
    assert "first recorded run" in history.verdict(None, line)
    assert "probe set changed" in history.verdict({**line, "probes": 170}, line)
    assert history.verdict(line, line).startswith("history: vs 2026-11-25 (d51ba732): passed 171 -> 171")
