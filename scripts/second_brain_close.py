#!/usr/bin/env python3
"""Session-end second-brain health check. Read-only — reports, never mutates.
Run via `make second-brain-close` or `python3 scripts/second_brain_close.py [--write-report]`.
Fill in / extend the check functions below for this project's own stack.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""


def changed_files():
    """Best-effort: last commit's files, else staged, else all modified/untracked."""
    for cmd in (
        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "status", "--porcelain", "--untracked-files=all"],
    ):
        out = run(cmd).strip()
        if out:
            if cmd[1] == "status":
                return [line[3:] for line in out.splitlines() if line]
            return out.splitlines()
    return []


def check_router_dead_links():
    issues = []
    for router in ("CLAUDE.md", "AGENTS.md"):
        p = ROOT / router
        if not p.exists():
            continue
        text = p.read_text(errors="ignore")
        for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
            link = m.group(1).split("#")[0].replace("file://", "").replace("%20", " ")
            if link.startswith("http") or not link:
                continue
            if not (ROOT / link).exists():
                issues.append(f"{router}: dead link -> {link}")
    return issues


def check_generated_artifact_churn():
    """Primary: any dir THIS project's own .gitignore covers, that still has tracked
    files under it (the exact Aira bug — gitignored after already being committed,
    ghost files left behind). Works for any dir name, not a guessed list.
    Fallback: a small courtesy list of common generator-output names, for dirs that
    were never gitignored at all (a .gitignore obviously can't tell us about those)."""
    issues = []
    ignored_dirs = set()
    gitignore = ROOT / ".gitignore"
    if gitignore.exists():
        for line in gitignore.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            candidate = line.rstrip("/").lstrip("!").lstrip("/")
            if candidate and (ROOT / candidate).is_dir():
                ignored_dirs.add(candidate)

    for d in ignored_dirs:
        tracked = run(["git", "ls-files", d]).strip().splitlines()
        if tracked:
            issues.append(f"{d}: gitignored but still has {len(tracked)} tracked file(s) — run `git rm -r --cached {d}`")

    for d in ("graphify-out", "wiki", "docs/generated", "codemap"):
        if d in ignored_dirs or not (ROOT / d).is_dir():
            continue
        tracked = run(["git", "ls-files", d]).strip().splitlines()
        if len(tracked) > 20:
            issues.append(f"{d}: {len(tracked)} files tracked and not gitignored — likely churns on every regen (consider gitignoring)")
    return issues


def check_hook_liveness():
    issues = []
    if (ROOT / "lefthook.yml").exists() or (ROOT / ".lefthook.yml").exists():
        if not shutil.which("lefthook"):
            issues.append("lefthook.yml present but `lefthook` binary not on PATH — hooks are silently no-op'ing")
    return issues


def _fallback_credential_patterns(files):
    """Narrow, best-effort fallback ONLY used when gitleaks isn't installed.
    Covers 4 common shapes — NOT a substitute for real coverage."""
    issues = []
    patterns = [
        (r"AKIA[0-9A-Z]{16}", "AWS access key"),
        (r"sk-[a-zA-Z0-9]{20,}", "OpenAI/Anthropic-style secret key"),
        (r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----", "private key block"),
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub personal access token"),
    ]
    for f in files:
        p = ROOT / f
        if not p.is_file() or p.suffix in {".png", ".jpg", ".jpeg", ".lock", ".ico"}:
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        for pattern, label in patterns:
            if re.search(pattern, text):
                issues.append(f"{f}: possible {label} pattern (fallback check) — verify before committing")
    return issues


def check_credential_patterns():
    """Scan recently-changed files (not the whole repo) for leaked secrets.
    Uses `gitleaks` (real, maintained pattern DB) when installed — falls back to
    4 narrow patterns otherwise, clearly labeled as such (not full coverage)."""
    files = changed_files()
    if not files:
        return []

    if not shutil.which("gitleaks"):
        return [
            "gitleaks not installed — only 4 narrow fallback patterns checked, NOT full coverage. "
            "Install: brew install gitleaks (or see https://github.com/gitleaks/gitleaks)."
        ] + _fallback_credential_patterns(files)

    # Scan only the changed files themselves, one at a time — NOT the whole working
    # tree. Whole-tree scans (even --no-git) can time out on a real repo with
    # node_modules/build output/large history-adjacent dirs; per-file scans stay
    # fast and are correctly scoped to "what changed this session" either way.
    issues = []
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "gitleaks-report.json"
            try:
                subprocess.run(
                    ["gitleaks", "detect", "--no-git", "--source", str(p),
                     "--report-format", "json", "--report-path", str(report_path)],
                    cwd=ROOT, capture_output=True, timeout=15,
                )
            except subprocess.TimeoutExpired:
                issues.append(f"{f}: gitleaks scan timed out — skipped")
                continue
            try:
                findings = json.loads(report_path.read_text()) if report_path.exists() and report_path.stat().st_size else []
            except Exception:
                findings = []
        for finding in findings:
            rule = finding.get("RuleID", "secret")
            line = finding.get("StartLine", "?")
            issues.append(f"{f}:{line}: gitleaks found a likely {rule} — verify before committing")
    return issues


# A note that says a file was removed or renamed is SUPPOSED to name something that
# no longer exists -- those sentences are the most valuable ones in the brain, and
# flagging them inverts the test. Checked against the line the reference sits on.
_REMOVAL_MARKERS = re.compile(
    r"\b(removed?|renamed?|deleted?|dropped?|parked|stripped|retired|replaced|"
    r"superseded|reverted|gone|no longer|used to|formerly|gitignored)\b|\u2192",
    re.I,
)

# Never committed by policy, so "not in the repo" says nothing about staleness.
_NEVER_COMMITTED_EXT = {".jks", ".keystore", ".p12", ".apk", ".aab", ".env"}


def _dependency_names():
    """The first path segment of a third-party module path (`slowapi/middleware.py`)
    is a dependency name, not a directory in this repo."""
    names = set()
    req = ROOT / "backend" / "requirements.txt"
    if req.exists():
        for line in req.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(re.split(r"[=<>~!\[\s;]", line)[0].strip().lower().replace("-", "_"))
    pkg = ROOT / "frontend" / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            for key in ("dependencies", "devDependencies"):
                names.update(n.lower() for n in (data.get(key) or {}))
        except Exception:
            pass
    return names


def check_stale_claims():
    """Best-effort: file paths quoted in .agents/ notes that no longer exist anywhere.
    Notes commonly abbreviate paths with an implied prefix (e.g. `services/x.py` for
    `backend/app/services/x.py`, established by surrounding prose) — a reference counts
    as live if it matches a tracked file exactly OR as a path suffix (leading slashes
    normalized away first), not just literally root-relative. Skips active-backlog.md
    (or any file with 'backlog' in its name) — backlog items intentionally describe
    planned, not-yet-built paths; flagging those as "stale" is the wrong test entirely."""
    issues = []
    agents_dir = ROOT / ".agents"
    if not agents_dir.is_dir():
        return issues
    tracked = run(["git", "ls-files"]).strip().splitlines()
    deps = _dependency_names()
    for md in agents_dir.rglob("*.md"):
        if "backlog" in md.name.lower():
            continue
        source = str(md.relative_to(ROOT))
        text = md.read_text(errors="ignore")
        # A doc that declares itself append-only is a historical record: an entry
        # written in July naming a file deleted in August was true when written and
        # is not a stale claim. Current-state docs (context/*) still get checked.
        if "append-only" in text[:600].lower():
            continue
        for m in re.finditer(r"`([\w./\-]+\.\w{2,4})`", text):
            raw = m.group(1)
            # A leading slash means a URL route (`/intake/sessions.csv`); repo paths in
            # these notes are written without one. "..." is an elision in prose.
            if raw.startswith("/") or "..." in raw:
                continue
            ref = raw.lstrip("/")
            if "/" not in ref or (ROOT / ref).exists():
                continue
            if any(t == ref or t.endswith("/" + ref) for t in tracked):
                continue
            if Path(ref).suffix.lower() in _NEVER_COMMITTED_EXT:
                continue
            if ref.split("/")[0].lower().replace("-", "_") in deps:
                continue
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start:line_end if line_end != -1 else len(text)]
            if _REMOVAL_MARKERS.search(line):
                continue
            issues.append(f"{source}: references `{ref}` — no longer found in the repo")
    return issues


# A log section larger than this costs too much context to read as one slice. Measured
# 2026-11-28: after the heading repair the largest real section was 15,933 chars; before
# it, one heading had swallowed three months of entries and reached 193,869.
LOG_SECTION_MAX_CHARS = 20_000

_INDEX_HEADING = "## DB Migrations Index"
_INDEX_ROW = re.compile(r"^\| \*\*(\d{3})\*\* \|")


def migration_index_gap(log_text, migration_numbers):
    """Issue if a committed migration has no row in the index table in log.md.
    Only rows inside the index section count — dated entries further down can hold
    tables of their own. `migration_numbers` is every 3-digit prefix of a committed file."""
    lines = log_text.split("\n")
    start = next((i for i, x in enumerate(lines) if x.startswith(_INDEX_HEADING)), None)
    if start is None:
        return [f"decisions/log.md: no '{_INDEX_HEADING}' section — CLAUDE.md points agents at it"]
    indexed = Counter()
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        m = _INDEX_ROW.match(line)
        if m:
            indexed[int(m.group(1))] += 1
    # One row per file, so compare counts: two files can share a number, and a lower
    # number can land after a higher one. Numbers below the table's first row belong
    # to the separate historical index.
    first, last = min(indexed, default=0), max(indexed, default=0)
    missing = Counter(n for n in migration_numbers if n >= first) - indexed
    if missing:
        return [
            f"decisions/log.md: migration index (rows {first}–{last}) is missing {sum(missing.values())} "
            f"committed file(s): {', '.join(map(str, sorted(missing)[:10]))} — regenerate the table "
            "from `git ls-files backend/supabase/migrations`"
        ]
    return []


def oversized_sections(text, limit=LOG_SECTION_MAX_CHARS):
    """One issue per '## ' section of `text` that is longer than `limit` characters.
    A section runs from its '## ' heading line up to (not including) the next '## ' line."""
    sections = []  # [heading text, char count]; text before the first heading is not a section
    for line in text.split("\n"):
        if line.startswith("## "):
            sections.append([line[3:].strip(), 0])
        if sections:
            sections[-1][1] += len(line) + 1
    return [
        f"decisions/log.md: section '{heading[:70]}' is {size:,} chars (limit {limit:,}) — "
        "split it under more '## ' headings (one per dated entry, or one per month for a list)"
        for heading, size in sections
        if size > limit
    ]


def check_log_health():
    """decisions/log.md stays cheap to search: no giant sections, migration index current."""
    log = ROOT / ".agents" / "decisions" / "log.md"
    if not log.is_file():
        return []
    text = log.read_text(errors="ignore")
    numbers = [
        int(m.group(1))
        for m in re.finditer(r"^backend/supabase/migrations/(\d{3})_[^/]+\.sql$",
                             run(["git", "ls-files", "backend/supabase/migrations"]), re.M)
    ]
    return oversized_sections(text) + migration_index_gap(text, numbers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    sections = {
        "Dead router links": check_router_dead_links(),
        "Generated-artifact git churn": check_generated_artifact_churn(),
        "Git hook liveness": check_hook_liveness(),
        "Credential patterns (recent changes)": check_credential_patterns(),
        "Stale claims in .agents/": check_stale_claims(),
        "Decision log health": check_log_health(),
    }

    total = sum(len(v) for v in sections.values())
    lines = ["# Second-brain close report", ""]
    for name, issues in sections.items():
        lines.append(f"## {name}: {'OK' if not issues else f'{len(issues)} issue(s)'}")
        lines.extend(f"- {i}" for i in issues)
        lines.append("")
    report = "\n".join(lines)
    print(report)

    if args.write_report:
        out_dir = ROOT / ".agents" / "session-reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md"
        out_path.write_text(report)
        print(f"\nReport written to {out_path.relative_to(ROOT)}")

    print(f"\n{total} total issue(s) found. Read-only — nothing was changed.")
    print("Still manual (not automatable): route this session's new knowledge —")
    print("project facts into .agents/*, personal/working-style into your personal memory.")

    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
