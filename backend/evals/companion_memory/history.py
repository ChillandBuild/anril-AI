"""Score history for the companion memory eval: one line per full run, so a change can be judged
against the run before it.

Example line (results/history.csv):
  2026-11-25,d51ba732,auto,gemini,180,171,125,119,2,0,0,1190.4,56,60,55,60,60,60,
means: on 25 Nov, at commit d51ba732, 171 of 180 probes passed, 119 of 125 recall probes, 2 invented
facts, memory p95 1190 ms; en 56/60, ta 55/60, ta-en 60/60.

Partial runs (--only) are not recorded: 12 probes can't be compared with 180.
"""
import csv
import pathlib
import subprocess

FILE = pathlib.Path(__file__).parent / "results" / "history.csv"
LANGS = ("en", "ta", "ta-en")
COLUMNS = ["date", "commit", "memory_mode", "probe_model", "probes", "passed", "recall_n", "recall_passed",
           "invented", "errors", "unjudged", "memory_ms_p95",
           *[f"{lang}_{part}" for lang in LANGS for part in ("passed", "probes")], "note"]
NUMBERS = [c for c in COLUMNS if c not in ("date", "commit", "memory_mode", "probe_model", "note")]


def commit() -> str:
    """The short commit the run measured, with '+' when files were changed since ("d51ba732+")."""
    try:
        here = pathlib.Path(__file__).parent

        def git(*args):
            return subprocess.run(["git", *args], cwd=here, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = "+" if git("status", "--porcelain", "--untracked-files=no") else ""
        return (git("rev-parse", "--short=8", "HEAD") or "unknown") + dirty
    except Exception:
        return "unknown"


def row(summary: dict, day: str, commit_id: str, note: str = "") -> dict:
    """One history line from run.summarize()'s output."""
    langs = summary["languages"]
    everything = langs["all"]
    recall = everything["by_kind"].get("recall", {"n": 0, "pass": 0})
    out = {"date": day, "commit": commit_id, "memory_mode": summary.get("memory_mode", "auto"),
           "probe_model": summary.get("probe_model", ""), "probes": everything["probes"],
           "passed": everything["pass"], "recall_n": recall["n"], "recall_passed": recall["pass"],
           "invented": everything["invented"], "errors": everything["errors"],
           "unjudged": everything["unjudged"], "memory_ms_p95": everything["memory_ms_p95"], "note": note}
    for lang in LANGS:
        out[f"{lang}_passed"] = langs.get(lang, {}).get("pass", 0)
        out[f"{lang}_probes"] = langs.get(lang, {}).get("probes", 0)
    return out


def load(path: pathlib.Path = FILE) -> list[dict]:
    """Every recorded run, oldest first, numbers as numbers ('' stays None)."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in NUMBERS:
            r[c] = float(r[c]) if c == "memory_ms_p95" and r.get(c) else int(r[c]) if r.get(c) else None
    return rows


def last_run(mode: str, path: pathlib.Path = FILE) -> dict | None:
    """The newest recorded run in the same memory mode (auto is never compared with agentic)."""
    same = [r for r in load(path) if r["memory_mode"] == mode]
    return same[-1] if same else None


def append(new: dict, path: pathlib.Path = FILE) -> None:
    fresh = not path.exists()
    path.parent.mkdir(exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if fresh:
            writer.writeheader()
        writer.writerow({c: "" if new.get(c) is None else new[c] for c in COLUMNS})


def worse(before: dict, after: dict) -> list[str]:
    """Why `after` is a worse run than `before`; an empty list means "not worse, safe to ship".
    Both are history lines (see row()). Example of one reason: "invented facts went from 2 to 4".
    """
    # TODO(human): decide what counts as "worse" and return one short reason per failed rule.
    return []


def verdict(before: dict | None, after: dict) -> str:
    """The line the run prints after its report."""
    if before is None:
        return "history: first recorded run in this mode, nothing to compare with"
    if before["probes"] != after["probes"]:
        return (f"history: not compared, the probe set changed ({before['probes']} -> {after['probes']} probes)")
    reasons = worse(before, after)
    head = f"history: vs {before['date']} ({before['commit']}): passed {before['passed']} -> {after['passed']}"
    return head + ("; WORSE: " + "; ".join(reasons) if reasons else "; not worse")
