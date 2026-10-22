# Aira AI — Agent Operating Manual

## Core Commands
- **Backend Dev**: `make dev-backend` (safe mode: scheduler paused, outbound dry-run). No `make` on the Windows machine: run `bash scripts/dev-backend.sh` (same thing). Never plain `uvicorn` on a laptop — it shares the live DB.
- **Backend Test**: `cd backend && python -m pytest` (runs tests under `backend/tests/`). Use `python -m pytest`, not bare `pytest` — several test modules import `app.*` without adding the backend dir to `sys.path`, so bare `pytest` dies at collection with `ModuleNotFoundError: No module named 'app'`. `python -m` puts the cwd on `sys.path` and the suite passes (4403 tests as of 2026-10-17). On Windows run it as `PYTHONUTF8=1 python -m pytest`: `test_anril_rename_copy` reads every backend file and fails under the default cp1252 encoding. Run it from `backend/`, not the repo root.
- **Production Run (Render)**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (executed from `backend/` directory)

---

## How to Work Efficiently (low context — this is the DEFAULT, no need to be told)
- The brain is **queried, not loaded**. Never read whole files or the whole wiki "to get context."
- Lookup order for ANY task: (1) find the exact file:line — `graphify query "<question>"` if `graphify` is installed AND `graphify-out/` exists, otherwise a targeted Grep/Glob for the symbol or UI string (as of 2026-10-13 neither graphify nor `graphify-out/` exists on the Windows machine), (2) the ONE relevant `graphify-out/wiki/<Module>.md` (when present) or `.agents/context/subsystem-notes.md` section, (3) at most 2–3 targeted reads. Full-file reads are the last resort.
- Pull ONLY the `.agents/` file the task scope points to (below) — never preload all of them.
- **Database/schema work:** the wiki is CODE only. Use the migration index in [decisions/log.md](.agents/decisions/log.md) + live Supabase `list_tables`/`execute_sql` — NOT the wiki.
- This runs automatically for every task; the user does NOT have to say "use the wiki/graph."

## How we work — the sprint (every task, no need to be told)

> Still applies: push or deploy only when the user says so, and the pre-commit checks
> (pytest, typecheck, lint) still run as before.

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
  as the UI test tenant — on the live site, or locally. Local backend ONLY via `make dev-backend`
  (plain uvicorn would run the scheduler and message real leads from the live DB; see
  subsystem-notes.md). Point the local frontend at it with NEXT_PUBLIC_API_URL=http://localhost:8000.
- Auth, webhooks, payments, RLS → also `security-and-hardening` + the security-checklist.md;
  anything irreversible → `doubt-driven-development`.
- Before any commit → run the checks that fit the change (`/review` on the diff, `python -m pytest` for
  backend, typecheck + lint for frontend), without asking. Do NOT repeat a check that already passed on the same
  code: if no code or test file changed since the last passing run, or the change is docs/config only, skip it and
  just commit. Commit to `main`, no branch. Push only when the user says so.
- Before finishing → `git fetch`, check `HEAD..origin/main` for teammate commits on the
  same files; if any, rebase and re-run the tests.
- Weekly → a short retro: what shipped, what broke.
- A push to `main` auto-deploys the backend on Render. Push or deploy only when the user says so, every time;
  `/ship` is the go/no-go checklist, not permission to push.

## Agent Routing Instructions
To prevent context dilution, general invariants and rules have been split into modular guides. **Always read these files first based on the scope of your task:**

1.  **Identity, Dev Persona & Code Style Rules**:
    *   Location: [.agents/context/identity.md](.agents/context/identity.md)
    *   Read when: You start a new session or need to review coding styles, formatting preferences, and file/API response conventions.
2.  **Invariants, Tech Stack & File Map**:
    *   Location: [.agents/context/stack-and-rules.md](.agents/context/stack-and-rules.md)
    *   Read when: Modifying DB calls, working with WhatsApp/TeleCMI webhooks, routing outbound calls, or checking security policies (RLS).
3.  **Historical Decisions & DB Migrations**:
    *   Location: [.agents/decisions/log.md](.agents/decisions/log.md)
    *   Read when: Seeking context on why specific modules (e.g., Bot Flow Builder) were dropped, checking migration histories, or verifying schema structures.
4.  **Active Roadmap & Technical Debt**:
    *   Location: [.agents/projects/active-backlog.md](.agents/projects/active-backlog.md)
    *   Read when: Checking current backlog tasks or reviewing known tech debt (e.g., orphaned tables).
5.  **Subsystem Notes & Load-Bearing Gotchas**:
    *   Location: [.agents/context/subsystem-notes.md](.agents/context/subsystem-notes.md)
    *   Read when: Editing broadcasts/delivery, scoring, call evaluation, knowledge RAG, frontend perf, telecalling, chat escalation, or operator console — holds the *why* and the traps the wiki can't.
6.  **Security & Vulnerability Guidance**:
    *   Location: [.agents/context/security-checklist.md](.agents/context/security-checklist.md)
    *   Read when: Touching auth, webhooks, payments (Razorpay), file uploads, RLS policies, or any route reading `tenant_id`. Escalate to the `security-reviewer` agent for new auth/webhook/payment code or RLS changes.
7.  **AI Reply Master Prompt**:
    *   Location: [docs/whatsapp-master-prompt.md](docs/whatsapp-master-prompt.md)
    *   Read when: Touching `_build_base_prompt()` / `ai_reply.py`'s prompt assembly, or the `ai_prompts` table's `master` row — this is the canonical text and explains why the per-channel rows (`whatsapp_reply` etc.) are dead weight.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `ChillandBuild/anril-AI`, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout — `CONTEXT.md` + `docs/adr/` at the repo root (created lazily as needed). See `docs/agents/domain.md`.

