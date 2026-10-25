#!/usr/bin/env python3
"""Local dashboard for the Aira R&D team: read the reports, approve items, review builds,
merge / drop / push, start a run.  `make rnd-dashboard`

Safety: listens on 127.0.0.1 only; every API call needs the per-start token from the URL
(another site open in the browser cannot press the buttons) and a localhost Host header
(no DNS rebinding). Git runs with fixed arguments on rnd/* branches only; merge refuses a
dirty main checkout; push fetches first and refuses when origin/main has moved.
Standard library only.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAIN = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("RND_OUT") or Path.home() / "Documents" / "anril-assets" / "rnd" / "reports")  # same as run.sh
STATE = Path.home() / ".aira-rnd"
PAGE = Path(__file__).with_name("dashboard.html")
SCRIPT = Path(__file__).with_name("dashboard.js")
PORT = int(os.environ.get("RND_DASHBOARD_PORT", "8787"))
TOKEN = secrets.token_urlsafe(24)
BRANCH_RE = re.compile(r"^rnd/[a-z0-9][a-z0-9.#_-]{0,120}$")
REPORT_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+\.(md|txt)$|^LATEST-[a-z]+\.md$")
HEADING = re.compile(r"^###\s+(\d+)\.\s+(.+?)\s*$")
TICK = re.compile(r"^(\s*-\s*\[)([ xX])(\]\s*Approve\b.*)$")
ALARM = "ai.bloommatrix.aira-rnd"


def git(*args: str, cwd: Path = MAIN, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check, timeout=120)


# ---------- reading ----------

def reports() -> list[dict]:
    if not OUT.exists():
        return []
    found = []
    for f in sorted(OUT.glob("*.md"), reverse=True):
        if f.name.startswith("LATEST-"):
            continue
        kind = "strategy" if "strategy" in f.name else "builds" if f.name.startswith("builds-") else "night"
        found.append({"name": f.name, "kind": kind, "date": f.name[:10]})
    return found


def items(text: str) -> list[dict]:
    out, current = [], None
    for line in text.splitlines():
        h = HEADING.match(line)
        if h:
            current = {"n": h.group(1), "title": re.sub(r"[*_`]", "", h.group(2)), "approved": None}
            out.append(current)
        elif line.startswith("## "):
            current = None
        elif current is not None:
            t = TICK.match(line)
            if t and current["approved"] is None:
                current["approved"] = t.group(2).lower() == "x"
    return [i for i in out if i["approved"] is not None]


def built_ids() -> set[str]:
    f = STATE / "built.json"
    return set(json.loads(f.read_text())) if f.exists() else set()


def builds() -> list[dict]:
    listing = git("for-each-ref", "--format=%(refname:short)|%(objectname:short)|%(committerdate:relative)", "refs/heads/rnd/")
    merged = set(git("branch", "--merged", "main", "--format=%(refname:short)").stdout.split())
    result = []
    for line in listing.stdout.splitlines():
        branch, sha, when = line.split("|", 2)
        safe = branch.removeprefix("rnd/")
        summary = OUT / "build" / f"{safe}.md"
        verify = OUT / "build" / f"{safe}-verify.txt"
        summary_md = summary.read_text(encoding="utf-8") if summary.exists() else ""
        status = next((l.split(":", 1)[1].strip() for l in summary_md.splitlines() if l.startswith("Status:")), "unknown")
        result_line = ""
        if verify.exists():
            result_line = next((l for l in verify.read_text().splitlines() if l.startswith("RESULT:")), "")
        stat = git("diff", "--stat", f"main...{branch}").stdout.strip()
        result.append({
            "branch": branch, "sha": sha, "when": when, "status": status,
            "verify": result_line.removeprefix("RESULT:").strip() or "not run",
            "merged": branch in merged, "diffstat": stat, "summary": summary_md,
        })
    return result


def status() -> dict:
    logs = sorted((STATE / "logs").glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:4] if (STATE / "logs").exists() else []
    alarm = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{ALARM}"], capture_output=True, text=True).returncode == 0
    dirty = [l for l in git("status", "--porcelain").stdout.splitlines() if not l.startswith("??")]
    return {
        "alarm": alarm,
        "running": (STATE / "run.lock").exists(),
        "branch": git("branch", "--show-current").stdout.strip(),
        "dirty": len(dirty),
        "unpushed": git("log", "--oneline", "origin/main..main").stdout.splitlines(),
        "logs": [{"name": p.name, "tail": p.read_text(errors="replace").splitlines()[-6:]} for p in logs],
    }


def state() -> dict:
    all_reports = reports()
    night = next((r for r in all_reports if r["kind"] == "night"), None)
    night_items = items((OUT / night["name"]).read_text(encoding="utf-8")) if night else []
    done = built_ids()
    for i in night_items:
        i["built"] = f"{Path(night['name']).stem}#{i['n']}" in done
    return {"reports": all_reports, "night": night, "night_items": night_items,
            "builds": builds(), "status": status()}


# ---------- actions ----------

def approve(report: str, n: str, on: bool) -> dict:
    if not REPORT_RE.match(report) or report.startswith("LATEST-") or not n.isdigit():
        raise ValueError("bad report or item")
    path = OUT / report
    lines, inside, changed = path.read_text(encoding="utf-8").splitlines(), False, False
    for k, line in enumerate(lines):
        h = HEADING.match(line)
        if h:
            inside = h.group(1) == n
        elif line.startswith("## "):
            inside = False
        elif inside and not changed:
            t = TICK.match(line)
            if t:
                lines[k] = f"{t.group(1)}{'x' if on else ' '}{t.group(3)}"
                changed = True
    if not changed:
        raise ValueError("no Approve line in that item")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True}


def need_branch(branch: str) -> None:
    if not BRANCH_RE.match(branch) or git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode:
        raise ValueError("not an R&D branch")


def merge(branch: str) -> dict:
    need_branch(branch)
    st = status()
    if st["branch"] != "main":
        raise ValueError(f"your main folder is on '{st['branch']}', not main")
    if st["dirty"]:
        raise ValueError(f"your main folder has {st['dirty']} unsaved change(s); commit or stash them first")
    res = git("merge", "--no-ff", "-m", f"Merge {branch} (R&D build, reviewed)", branch)
    if res.returncode:
        git("merge", "--abort")
        raise ValueError("merge conflict — nothing changed. Merge this one by hand.\n" + res.stdout[-800:])
    return {"ok": True, "output": res.stdout[-800:]}


def drop(branch: str) -> dict:
    need_branch(branch)
    worktree = MAIN / ".worktrees" / f"build-{branch.removeprefix('rnd/')}"
    if worktree.exists():
        git("worktree", "remove", "--force", str(worktree))
    res = git("branch", "-D", branch)
    if res.returncode:
        raise ValueError(res.stderr[-400:])
    return {"ok": True}


def push_preview() -> dict:
    git("fetch", "-q", "origin", "main")
    behind = int(git("rev-list", "--count", "main..origin/main").stdout.strip() or 0)
    return {"behind": behind, "commits": git("log", "--oneline", "origin/main..main").stdout.splitlines(),
            "branch": git("branch", "--show-current").stdout.strip()}


def push(confirm: str) -> dict:
    if confirm != "PUSH":
        raise ValueError("type PUSH to confirm")
    p = push_preview()
    if p["branch"] != "main":
        raise ValueError("your main folder is not on main")
    if p["behind"]:
        raise ValueError(f"GitHub has {p['behind']} newer commit(s) (a teammate pushed). Pull and re-run the tests first.")
    if not p["commits"]:
        raise ValueError("nothing to push")
    res = git("push", "origin", "main")
    if res.returncode:
        raise ValueError(res.stderr[-800:])
    return {"ok": True, "output": (res.stdout + res.stderr)[-800:]}


def run(kind: str) -> dict:
    if kind not in {"night", "build", "strategy"}:
        raise ValueError("unknown run")
    if (STATE / "run.lock").exists():
        raise ValueError("a run is already in progress")
    log = open(STATE / "logs" / f"dashboard-{kind}.out", "a")
    subprocess.Popen(["bash", str(MAIN / "scripts/rnd/run.sh"), kind], cwd=MAIN, stdout=log, stderr=log,
                     start_new_session=True)
    return {"ok": True}


# ---------- http ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _allowed(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in {"127.0.0.1", "localhost"}

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
                         "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data).encode())

    def _authed(self) -> bool:
        return self._allowed() and secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN)

    def do_GET(self):
        url = urlparse(self.path)
        if not self._allowed():
            return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
        if url.path == "/":
            return self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/app.js":
            return self._send(HTTPStatus.OK, SCRIPT.read_bytes(), "text/javascript; charset=utf-8")
        if not self._authed():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "missing or wrong token — reopen the link printed by make rnd-dashboard"})
        try:
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/state":
                return self._json(HTTPStatus.OK, state())
            if url.path == "/api/report":
                name = q.get("name", "")
                if not REPORT_RE.match(name):
                    raise ValueError("bad report name")
                return self._json(HTTPStatus.OK, {"markdown": (OUT / name).read_text(encoding="utf-8")})
            if url.path == "/api/diff":
                need_branch(q.get("branch", ""))
                return self._json(HTTPStatus.OK, {"diff": git("diff", f"main...{q['branch']}").stdout[:200_000]})
            if url.path == "/api/push-preview":
                return self._json(HTTPStatus.OK, push_preview())
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (ValueError, FileNotFoundError) as e:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

    def do_POST(self):
        if not self._authed():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            actions = {
                "/api/approve": lambda: approve(str(body.get("report", "")), str(body.get("n", "")), bool(body.get("on"))),
                "/api/merge": lambda: merge(str(body.get("branch", ""))),
                "/api/drop": lambda: drop(str(body.get("branch", ""))),
                "/api/push": lambda: push(str(body.get("confirm", ""))),
                "/api/run": lambda: run(str(body.get("kind", ""))),
            }
            action = actions.get(urlparse(self.path).path)
            if not action:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return self._json(HTTPStatus.OK, action())
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})


def main() -> None:
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/#t={TOKEN}"
    print(f"Aira R&D dashboard: {url}\n(Ctrl+C to stop; the link changes every start)", flush=True)
    if "--no-open" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
