# Anril AI — Agent Operating Manual

## Core Commands
- **Backend Dev**: `make dev-backend` (safe mode: scheduler paused, outbound dry-run). No `make` on the Windows machine: run `bash scripts/dev-backend.sh` (same thing). Never plain `uvicorn` on a laptop — it shares the live DB, so the scheduler would message real leads.
- **Backend Test**: `cd backend && python -m pytest` — never bare `pytest` (dies at collection). On Windows: `PYTHONUTF8=1 python -m pytest`. Why: [stack-and-rules.md § Running the Backend Tests](.agents/context/stack-and-rules.md).
- **Production Run (Render)**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (executed from `backend/` directory)

---

## How to Work Efficiently (low context — this is the DEFAULT, no need to be told)
- The brain is **queried, not loaded**. Never read whole files "to get context."
- Lookup order for ANY task: (1) find the exact file:line with a targeted grep for the symbol, UI string or error text, narrowing in steps (which files mention it → where it is defined → who calls it), (2) the ONE relevant `.agents/context/subsystem-notes.md` section, (3) at most 2–3 targeted reads. Full-file reads are the last resort.
- Pull ONLY the `.agents/` file the task scope points to (below) — never preload all of them.
- Searching `.agents/` files: lines there are whole paragraphs, so never print raw hits (measured 2026-11-28: cutting hits saves 56–65%).
  Step 1: `grep -n -i "<word>" <file> | cut -c1-200 | head -40`.
  Step 2: get the smallest heading block around hit line N (prints its heading line and the next one; `##` and `###` both count):
  `awk -v n=N '/^##/{ if (NR>n) {print NR": "$0; exit} h=NR": "$0 } NR==n{print h}' <file> | cut -c1-90`
  Step 3: `sed -n '<start>,<end>p' <file>` for that ONE block. Never guess a line range.
  Don't list every heading (notes ~7k chars, log ~26k). For the log, filter by month: `grep -n "^## 2026-11" .agents/decisions/log.md | cut -c1-80`.
- Writing `.agents/` files: no heading block over 8,000 chars in subsystem-notes.md (add `### ` sub-headings) or 20,000 in the log; `make second-brain-close` checks both.
- **Database/schema work:** use the migration index in [decisions/log.md](.agents/decisions/log.md) + live Supabase `list_tables`/`execute_sql`.
- This runs automatically for every task; the user does NOT have to ask for it.

## How we work — the sprint (every task, no need to be told)

- Skills below are the `superpowers` plugin (`superpowers:` prefix) plus Claude Code's built-in `/code-review`,
  `/simplify` and `/security-review`. Never `/ship`: the built-in one commits and pushes.
- Front door: new feature, idea or behavior change → `superpowers:brainstorming`, one question at a time,
  until ~95% sure what the user wants (glossary of Prem's terms: `.agents/context/prem-glossary.md`).
  Bug → `superpowers:systematic-debugging` first. A fully specified one-liner skips the questions.
- Flow: `superpowers:writing-plans` (show the plan, wait for approval) → `superpowers:executing-plans`
  (or `superpowers:subagent-driven-development` for workers) → `superpowers:test-driven-development` →
  `/code-review` → `/simplify` → `superpowers:verification-before-completion`. Bug fix: a regression test first.
- Who does the work: the model running the session plans and allocates. Opus → Sonnet and Haiku
  workers; Sonnet → Haiku workers. Haiku: search, renames, running tests/lint, docs, boilerplate
  from an exact spec. Sonnet: logic changes. Never delegated down (the planner does it itself):
  auth, webhooks, payments, RLS, migrations. The planner runs `/code-review` on every
  worker diff before showing it. Flat only: workers do not spawn workers.
- UI change → review the design in the plan before building; after building, run a UI QA pass as the UI
  test tenant — on the live site, or locally (backend via `make dev-backend` only, frontend pointed at it
  with NEXT_PUBLIC_API_URL=http://localhost:8000).
- Auth, webhooks, payments, RLS → also `/security-review` + the security-checklist.md;
  anything irreversible → stop and double-check with the user first.
- Before any commit → run the checks that fit the change (`/code-review` on the diff, `python -m pytest` for
  backend, typecheck + lint for frontend), without asking. Do NOT repeat a check that already passed on the same
  code: if no code or test file changed since the last passing run, or the change is docs/config only, skip it and
  just commit. Commit to `main`, no branch.
- Before finishing → `git fetch`, check `HEAD..origin/main` for teammate commits on the
  same files; if any, rebase and re-run the tests.
- Weekly → a short retro: what shipped, what broke.
- A push to `main` auto-deploys the backend on Render. Push or deploy only when the user says so, every time;
  `superpowers:verification-before-completion` is the go/no-go check, not permission to push.

## Agent Routing Instructions
Read ONLY the file your task's scope points to:

1. [.agents/context/identity.md](.agents/context/identity.md) — new session; code style, formatting, file/API response conventions.
2. [.agents/context/stack-and-rules.md](.agents/context/stack-and-rules.md) — DB calls, WhatsApp/TeleCMI webhooks, outbound call routing, RLS, tech stack, file map, running tests.
3. [.agents/decisions/log.md](.agents/decisions/log.md) — why a module was dropped (e.g. Bot Flow Builder), migration history, schema structure.
4. [.agents/projects/active-backlog.md](.agents/projects/active-backlog.md) — backlog tasks, known tech debt (e.g. orphaned tables).
5. [.agents/context/subsystem-notes.md](.agents/context/subsystem-notes.md) — broadcasts/delivery, scoring, call evaluation, knowledge RAG, frontend perf, telecalling, chat escalation, operator console: the *why* and the traps the code can't show.
6. [.agents/context/security-checklist.md](.agents/context/security-checklist.md) — auth, webhooks, payments (Razorpay), file uploads, RLS, any route reading `tenant_id`. New auth/webhook/payment code or RLS changes → run `/security-review` on the diff.
7. [docs/whatsapp-master-prompt.md](docs/whatsapp-master-prompt.md) — `_build_base_prompt()` / `ai_reply.py` prompt assembly, or the `ai_prompts` `master` row. Canonical text; explains why the per-channel rows (`whatsapp_reply` etc.) are dead weight.

## Project conventions
- Customer-facing copy says "Anril", never "Aira" (the repo and code still say Aira).

## Agent skills
- Issues: GitHub Issues for `ChillandBuild/anril-AI` via the `gh` CLI. See `docs/agents/issue-tracker.md`.
- Domain docs: single-context layout — `CONTEXT.md` + `docs/adr/` at the repo root (created lazily). See `docs/agents/domain.md`.
