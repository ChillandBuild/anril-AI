"""The R&D fence: what an unattended run may and may not do.

    python3 -m pytest scripts/rnd/test_fence.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FENCE = Path(__file__).with_name("fence.py")
ROOT = "/tmp/aira-rnd-test/worktree"
OUT = "/tmp/aira-rnd-test/reports"


def run(tool: str, tool_input: dict, autonomous: bool = True) -> str:
    env = {**os.environ, "AIRA_RND_ROOT": ROOT, "AIRA_RND_OUT": OUT}
    env.pop("AIRA_AUTONOMOUS", None)
    if autonomous:
        env["AIRA_AUTONOMOUS"] = "1"
    res = subprocess.run(
        [sys.executable, str(FENCE)], input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
        capture_output=True, text=True, env=env, check=True,
    )
    out = json.loads(res.stdout or "{}")
    return (out.get("hookSpecificOutput") or {}).get("permissionDecision", "pass")


@pytest.mark.parametrize("cmd", [
    "git push origin main",
    "cd backend && git commit -m x",
    "git reset --hard origin/main",
    "git checkout -b feature",
    "gh pr create --fill",
    "gh api -X POST repos/x/y/issues",
    "render deploys create srv-1",
    "npx vercel --prod",
    "cd backend && uvicorn app.main:app",
    "curl -X POST https://api.render.com/v1/services",
    "curl https://x.y -d 'a=1'",
    "rm -rf backend",
    "cat .env",
    "cat backend/.env",
    "cat backend/evals/ui/.test-account.json",
    "sudo ls",
    "echo x; launchctl load foo.plist",
    "python -m evals.replies.run_eval --key-tenant abc",
])
def test_dangerous_bash_is_denied(cmd):
    assert run("Bash", {"command": cmd}) == "deny"


@pytest.mark.parametrize("cmd", [
    "git status && git log --oneline -5 && git diff HEAD~1",
    "git fetch origin main",
    "gh issue list --limit 5",
    "gh pr view 12",
    "grep -rn render_template backend/app | head",
    "cat render.yaml",
    "grep -n security .agents/context/security-checklist.md",
    "cat backend/.env.example",
    "cd backend && .venv/bin/python -m pytest -q",
    "node backend/evals/ui/check_dashboard_ia.js",
    "curl -s https://www.bloommatrix.in/aira",
    "python -m evals.conversations.run_aira --key-tenant t --test-key-tenant --no-judge",
])
def test_reading_and_testing_is_not_blocked(cmd):
    assert run("Bash", {"command": cmd}) == "pass"


def test_writes_only_inside_worktree_and_reports():
    assert run("Write", {"file_path": f"{OUT}/2026-09-28.md"}) == "pass"
    assert run("Edit", {"file_path": f"{ROOT}/backend/app/x.py"}) == "pass"
    assert run("Edit", {"file_path": "/Users/prem/Documents/anril AI/backend/app/x.py"}) == "deny"
    assert run("Write", {"file_path": f"{ROOT}/../escape.py"}) == "deny"
    assert run("Write", {"file_path": "/Users/prem/.claude/settings.json"}) == "deny"


@pytest.mark.parametrize("sql,expected", [
    ("select count(*) from messages", "pass"),
    ("  -- note\nWITH x AS (select 1) SELECT * FROM x", "pass"),
    ("select updated_at, created_at from leads", "pass"),
    ("update leads set name='x'", "deny"),
    ("select 1; delete from leads", "deny"),
    ("insert into leads(id) values (1)", "deny"),
    ("drop table leads", "deny"),
])
def test_sql_must_be_read_only(sql, expected):
    assert run("mcp__supabase__execute_sql", {"query": sql}) == expected


@pytest.mark.parametrize("tool,expected", [
    ("mcp__render__list_logs", "pass"),
    ("mcp__render__get_deploy", "pass"),
    ("mcp__render__trigger_deploy", "deny"),
    ("mcp__render__update_environment_variables", "deny"),
    ("mcp__supabase__list_tables", "pass"),
    ("mcp__supabase__apply_migration", "deny"),
    ("mcp__claude_ai_Gmail__send_message", "deny"),
])
def test_mcp_is_read_only(tool, expected):
    assert run(tool, {}) == expected


def test_ship_skills_denied():
    assert run("Skill", {"skill": "ship"}) == "deny"
    assert run("Skill", {"skill": "land-and-deploy"}) == "deny"
    assert run("Skill", {"skill": "qa-only"}) == "pass"


def test_off_unless_autonomous():
    assert run("Bash", {"command": "git push origin main"}, autonomous=False) == "pass"
    assert run("mcp__render__trigger_deploy", {}, autonomous=False) == "pass"
