# Aira AI — Agent Operating Manual

## Core Commands
- **Backend Dev**: `make dev-backend` (safe mode: scheduler paused, outbound dry-run). No `make` on the Windows machine: run `bash scripts/dev-backend.sh` (same thing). Never plain `uvicorn` on a laptop — it shares the live DB, so the scheduler would message real leads.
- **Backend Test**: `cd backend && python -m pytest` — never bare `pytest` (dies at collection). On Windows: `PYTHONUTF8=1 python -m pytest`. Why: [stack-and-rules.md § Running the Backend Tests](.agents/context/stack-and-rules.md).
- **Production Run (Render)**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (executed from `backend/` directory)

---

## How to Work Efficiently (low context — this is the DEFAULT, no need to be told)
- The brain is **queried, not loaded**. Never read whole files or the whole wiki "to get context."
- Lookup order for ANY task: (1) find the exact file:line — `graphify query "<question>"` if `graphify` is installed AND `graphify-out/` exists, otherwise a targeted Grep/Glob for the symbol or UI string (as of 2026-10-13 neither graphify nor `graphify-out/` exists on the Windows machine), (2) the ONE relevant `graphify-out/wiki/<Module>.md` (when present) or `.agents/context/subsystem-notes.md` section, (3) at most 2–3 targeted reads. Full-file reads are the last resort.
- Pull ONLY the `.agents/` file the task scope points to (below) — never preload all of them.
- **Database/schema work:** the wiki is CODE only. Use the migration index in [decisions/log.md](.agents/decisions/log.md) + live Supabase `list_tables`/`execute_sql` — NOT the wiki.
- This runs automatically for every task; the user does NOT have to say "use the wiki/graph."

## How we work — the sprint (every task, no need to be told)

- Skills and commands below are Addy Osmani's agent-skills (installed globally in `~/.claude/`).
- Front door: new feature, idea or behavior change → `interview-me`, one question at a time, until
  ~95% sure what the user wants (glossary of Prem's terms: `.agents/context/prem-glossary.md`).
  A new vague idea → `idea-refine` first, then `interview-me`. Bug → `debugging-and-error-recovery`
  first (interview only if the report is unclear). A fully specified one-liner skips the interview.
- Flow: `/spec` → `/plan` (show the plan, wait for approval) → `/build` → `/test` → `/review` →
  `/code-simplify` → `/ship`. Bug fixes: a regression test that fails before the fix and passes after.
- Who does the work: the model running the session plans and allocates. Opus → Sonnet and Haiku
  workers; Sonnet → Haiku workers. Haiku: search, renames, running tests/lint, docs, boilerplate
  from an exact spec. Sonnet: logic changes. Never delegated down (the planner does it itself):
  auth, webhooks, payments, RLS, migrations. The planner runs `code-review-and-quality` on every
  worker diff before showing it. Flat only: workers do not spawn workers.
- UI change → `frontend-ui-engineering` for the design in the plan; after building, run a UI QA pass
  as the UI test tenant — on the live site, or locally (backend via `make dev-backend` only, frontend
  pointed at it with NEXT_PUBLIC_API_URL=http://localhost:8000).
- Auth, webhooks, payments, RLS → also `security-and-hardening` + the security-checklist.md;
  anything irreversible → `doubt-driven-development`.
- Before any commit → run the checks that fit the change (`/review` on the diff, `python -m pytest` for
  backend, typecheck + lint for frontend), without asking. Do NOT repeat a check that already passed on the same
  code: if no code or test file changed since the last passing run, or the change is docs/config only, skip it and
  just commit. Commit to `main`, no branch.
- Before finishing → `git fetch`, check `HEAD..origin/main` for teammate commits on the
  same files; if any, rebase and re-run the tests.
- Weekly → a short retro: what shipped, what broke.
- A push to `main` auto-deploys the backend on Render. Push or deploy only when the user says so, every time;
  `/ship` is the go/no-go checklist, not permission to push.

## Agent Routing Instructions
Read ONLY the file your task's scope points to:

1. [.agents/context/identity.md](.agents/context/identity.md) — new session; code style, formatting, file/API response conventions.
2. [.agents/context/stack-and-rules.md](.agents/context/stack-and-rules.md) — DB calls, WhatsApp/TeleCMI webhooks, outbound call routing, RLS, tech stack, file map, running tests.
3. [.agents/decisions/log.md](.agents/decisions/log.md) — why a module was dropped (e.g. Bot Flow Builder), migration history, schema structure.
4. [.agents/projects/active-backlog.md](.agents/projects/active-backlog.md) — backlog tasks, known tech debt (e.g. orphaned tables).
5. [.agents/context/subsystem-notes.md](.agents/context/subsystem-notes.md) — broadcasts/delivery, scoring, call evaluation, knowledge RAG, frontend perf, telecalling, chat escalation, operator console: the *why* and the traps the wiki can't hold.
6. [.agents/context/security-checklist.md](.agents/context/security-checklist.md) — auth, webhooks, payments (Razorpay), file uploads, RLS, any route reading `tenant_id`. New auth/webhook/payment code or RLS changes → escalate to the `security-reviewer` agent.
7. [docs/whatsapp-master-prompt.md](docs/whatsapp-master-prompt.md) — `_build_base_prompt()` / `ai_reply.py` prompt assembly, or the `ai_prompts` `master` row. Canonical text; explains why the per-channel rows (`whatsapp_reply` etc.) are dead weight.

## Agent skills
- Issues: GitHub Issues for `ChillandBuild/anril-AI` via the `gh` CLI. See `docs/agents/issue-tracker.md`.
- Domain docs: single-context layout — `CONTEXT.md` + `docs/adr/` at the repo root (created lazily). See `docs/agents/domain.md`.
