#!/usr/bin/env python3
"""Detect a partially-destroyed dev environment before it wastes an hour.

Antivirus software (Avast in particular) has quarantined individual files out
of otherwise-intact packages on this project's dev machines - including
`difflib.py` from the Python standard library and `fetch.js.text.js` from
Next.js. The damage is silent: nothing errors until some unrelated code path
happens to import the missing module, and the resulting traceback points at
the importer rather than the real cause.

Run `make doctor` (or `python scripts/check_env_integrity.py`) when imports
start failing in ways that make no sense, or after any AV alert.

Stdlib only, by design - it has to run in an environment too broken for pip.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Stdlib modules this project (or its test tooling) actually depends on.
# difflib is listed first because pytest imports it via unittest, and its
# absence presents as a baffling "No module named 'difflib'" during collection.
STDLIB = [
    "difflib", "unittest", "doctest", "inspect", "dataclasses", "typing",
    "json", "re", "zoneinfo", "asyncio", "logging", "datetime", "pathlib",
    "subprocess", "email", "http.cookiejar", "urllib.request", "sqlite3",
    "csv", "decimal", "statistics", "concurrent.futures", "importlib.metadata",
]

# Third-party packages whose absence breaks the backend.
BACKEND = [
    "fastapi", "starlette", "pydantic", "pydantic_core", "httpx", "httpcore",
    "anyio", "supabase", "postgrest", "pytest", "pygments", "pptx",
    "pandas", "cffi", "typing_extensions", "certifi", "charset_normalizer",
]

# Files that have actually been quarantined before. Cheap canaries.
NODE_CANARIES = [
    "next/dist/compiled/@edge-runtime/primitives/fetch.js.text.js",
    "@eslint-community/eslint-utils/index.js",
    "next/dist/cli/next-lint.js",
]


def check_imports(label: str, names: list[str]) -> list[str]:
    broken: list[str] = []
    for name in names:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            broken.append(f"{name}  ->  {exc}")
        except Exception as exc:  # noqa: BLE001 - unrelated import errors are not damage
            print(f"  ? {name}: {type(exc).__name__} (not a missing-file problem)")
    status = "OK" if not broken else f"{len(broken)} BROKEN"
    print(f"{label + ':':<10}{status}")
    for item in broken:
        print(f"  x {item}")
    return broken


def check_pip() -> list[str]:
    """pip check catches wrong-platform or half-installed distributions."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"pip:      UNUSABLE ({type(exc).__name__}) - pip itself may be damaged")
        return ["pip is not runnable"]

    if proc.returncode == 0:
        print("pip:      OK")
        return []
    issues = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
    print(f"pip:      {len(issues)} ISSUE(S)")
    for line in issues:
        print(f"  x {line}")
    return issues


def check_node() -> list[str]:
    modules = REPO / "frontend" / "node_modules"
    if not modules.is_dir():
        print("node:     SKIPPED (frontend/node_modules not installed)")
        return []

    missing = [rel for rel in NODE_CANARIES if not (modules / rel).exists()]

    pkg_json = REPO / "frontend" / "package.json"
    if pkg_json.exists():
        deps = json.loads(pkg_json.read_text(encoding="utf-8"))
        wanted = {**deps.get("dependencies", {}), **deps.get("devDependencies", {})}
        for name in wanted:
            if not (modules / name).exists():
                missing.append(f"{name}/ (declared dependency not installed)")

    status = "OK" if not missing else f"{len(missing)} MISSING"
    print(f"node:     {status}")
    for item in missing:
        print(f"  x {item}")
    return missing


def main() -> int:
    print(f"Python {sys.version.split()[0]} at {sys.executable}\n")

    problems: list[str] = []
    problems += check_imports("stdlib", STDLIB)
    problems += check_imports("backend", BACKEND)
    problems += check_pip()
    problems += check_node()

    print()
    if not problems:
        print("Environment intact.")
        return 0

    print(f"{len(problems)} problem(s) found. This is usually antivirus quarantine,")
    print("not a bad install. Before reinstalling, add exclusions for the repo,")
    print("the Python install, and the npm cache - otherwise the new files get")
    print("eaten too. Then:")
    print("    cd frontend && rm -rf node_modules && npm ci")
    print("    cd backend  && pip install -r requirements.txt --force-reinstall")
    print("If pip itself is broken, restore it by extracting the pip wheel with")
    print("urllib + zipfile - pip cannot repair its own vendored files.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
