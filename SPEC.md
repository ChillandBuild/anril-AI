# SPEC: Scheduled jobs on a Postgres task queue (Procrastinate)

Status: draft, approved capability map 2026-10-31. Owner: Prem.

## 1. Objective

Move all 24 APScheduler jobs (backend/app/main.py:484-606) onto Procrastinate, a task queue whose
queue lives in our Supabase Postgres. The worker runs inside the existing Render web service
(option B, $0) and can later move to a separate Render background worker with no code change.

**Why:** the setup must stay reliable at 50+ tenants. Today a restart at the wrong second loses a
run, failures are swallowed (0 error rows ever), and two copies during a deploy can both run a job.

**Success looks like:**
- A job scheduled for 09:00 runs once, even if the app restarts at 08:59 or two copies are alive.
- A crashed run is either re-run (safe jobs) or shows red on the operator Scheduler page (unsafe jobs).
- Web response times do not change (proven locally: median 2.5 ms, max 27 ms during blocking jobs).
- One setting flips back to APScheduler in under 5 minutes.

**Already proven (2026-10-31, local + Render probe):** Procrastinate 3.10.0 installs with our
requirements (pip check clean); periodic tasks dedupe across 2 copies; sync tasks run in threads;
retry works; Render reaches aws-1-ap-south-1.pooler.supabase.com:5432 over IPv4 with LISTEN/NOTIFY
(66 ms) and session locks.

### Worked example: auto-messages, every minute

```
10:00:00  worker A's periodic deferrer inserts 1 row: auto_messages_tick @10:00   (worker B tries, unique key says no)
10:00:00  NOTIFY wakes a worker; it locks the row (SKIP LOCKED) -> status doing
10:00:02  process_due_sends() runs, same code as today -> status succeeded
10:01:00  next row ...
```
If the app is down 10:00-10:04, on restart the worker defers the 10:04 slot once (not 5 times):
process_due_sends() picks up everything queued since, exactly as a late APScheduler run would.

## 2. Commands

- Backend dev (safe mode, no worker): `make dev-backend` / `bash scripts/dev-backend.sh`
- Tests: `cd backend && python -m pytest`
- Apply queue schema (once per database, operator runs it): `cd backend && python -m app.queue.schema`
- Production: unchanged, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## 3. Project structure

```
backend/app/queue/
  __init__.py
  app.py        # procrastinate.App + PsycopgConnector (search_path=procrastinate, pool max 4)
  tasks.py      # the 24 periodic tasks, each a thin call into the existing service function
  safety.py     # rescue-stalled task, failure recording, pause check
  worker.py     # start/stop helpers called from main.py lifespan
  schema.py     # one-off: create schema procrastinate + apply Procrastinate DDL into it
backend/supabase/migrations/238_procrastinate_schema.sql   # schema + grants only (DDL applied by schema.py)
```
Touched: app/main.py (lifespan branches on SCHEDULER_BACKEND), app/config.py (new settings),
app/routes/operator.py (scheduler endpoints), frontend/app/operator/(console)/scheduler/page.tsx
(only if response shapes change; goal is that they don't), requirements.txt, render.yaml.

## 4. Code style

Follow .agents/context/identity.md: no inline comments unless the why is non-obvious, one-line
docstrings, match surrounding code. Task functions are thin: name, schedule, one call into the
existing service. No business logic moves.

## 5. Modules (build in this order)

### M1 Queue engine
- requirements.txt: `procrastinate==3.10.0`, `psycopg[binary,pool]` (pinned to what was tested).
- config.py: `database_url` (Render env DATABASE_URL = Supabase session pooler string, port 5432),
  `scheduler_backend: "apscheduler" | "procrastinate"` (default "apscheduler" until M5).
- Queue tables live in Postgres schema `procrastinate` (not exposed by PostgREST, which serves
  `public` only). Connector sets `search_path=procrastinate` on every pooled connection.
  Fallback if Procrastinate's DDL won't install outside `public`: install in `public`, enable RLS on
  every procrastinate_* table, revoke all from anon/authenticated. Decided in build task 1 by test.
- Worker starts in `lifespan` only when `scheduler_backend == "procrastinate"` AND
  `scheduler_enabled` is true. `make dev-backend` sets SCHEDULER_ENABLED=false, so laptops never
  run the worker or the periodic deferrer.
- Pool: max 4 connections (Supabase allows 60; ~21 in use). Worker concurrency 4.
- Startup must not block or crash the web app if the DB is unreachable: log an error, serve HTTP,
  retry the worker start every 30 s.

**Done when:** with the flag on, a local run against a throwaway Postgres starts the worker, /health
answers during startup, and the procrastinate schema holds the queue tables; with the flag off,
no psycopg connection is opened.

### M2 Move the 24 jobs
Each job becomes `@app.periodic(cron=...)` + `@app.task(name=<same id as today>)` calling the
same service function the main.py wrapper calls today. Same schedules: interval jobs become
cron (`*/1`, `*/2`, `*/3`, `*/5`, `*/10`, `*/15`, `*/30` minutes, hourly, `0 */4`); cron jobs keep
Asia/Kolkata times (Procrastinate cron is UTC: 03:00 IST = 21:30 UTC previous day, etc.).
Plain-`def` services (assignment-sweep, recycle-contacts, callback-notifications,
call-alert-summary, ad-insights-sync, brain-weekly-digest) become sync tasks (run in a thread).
Async services stay async tasks (no behavior change; moving them off the loop is out of scope).

Queues: `messages` (sends), `calls` (call-ai-sweep, crm-cutoff-sweep), `maintenance` (rest).

| Retry class | Jobs | On crash mid-run |
|---|---|---|
| **A. Sweep** (claims rows, next tick redoes) | scheduled-broadcasts, auto-messages, scheduled-templates, sms-send, sms-reconcile, assignment-sweep, recycle-contacts, call-ai-sweep, crm-cutoff-sweep, astro-push-reconcile, intake-staleness-sweep, token-health-check, number-quality-sync, ad-insights-sync | marked failed; next tick does the work |
| **B. Idempotent daily** | numbers-pool-sync, send-log-prune, scheduler-runs-prune, private-send-meta-reconcile | rescued and re-run once |
| **C. Could double-send** (send first, mark after, or no mark) | reengagement-rules, silence-nudge, pending-whatsapp-alerts, callback-notifications, call-alert-summary, brain-weekly-digest | never re-run; marked failed, red on console |

**Done when:** a test asserts all 24 ids are registered with the expected cron, queue and retry
class, and each task calls the right service function (mocked).

### M3 Safety net
- `rescue-stalled` periodic task, every minute: `get_stalled_jobs()` (worker heartbeat older than
  30 s). Class B: `retry_job`. Class A and C: mark failed with error "worker died mid-run".
- Catch-up: `periodic_defaults max_delay = 6 h`. A daily job missed by a restart runs on startup if
  its slot is under 6 h old; minute jobs defer only their latest slot.
- Wrappers stop swallowing: a service exception fails the job (status failed + error text in
  procrastinate_events) so failures are visible. Existing per-row try/except inside services stays.
- Retention: Procrastinate's built-in `remove_old_jobs` daily at 03:45 IST: succeeded jobs older
  than 2 days, failed older than 14 days. Expected table size at ~13.6k jobs/day: under 20 MB.
- Lateness: started_at minus the periodic slot time, exposed to the console.

**Done when:** local tests reproduce the 3 crash cases (A marked failed, B re-run and succeeds,
C marked failed and not re-run) and the retention task deletes only old rows.

### M4 Operator console
Same endpoints, same response shapes, so the frontend scheduler page needs no change:
- `GET /scheduler-health` and `GET /alerts`: per task, last status/run/error/lateness, 24 h error
  count, next run (from cron), paused, read from procrastinate_jobs/events.
- `POST /scheduler/{id}/toggle`: pause state in table `procrastinate.task_controls(task_name pk,
  paused bool, updated_at)`. A paused task's run exits immediately as "skipped".
- `POST /scheduler/{id}/run`: defers the task now; 409 if paused (as today).
- `/ready`: scheduled-broadcasts heartbeat read from its last succeeded job.
Both backends keep working behind the flag until M5 cleanup.

**Done when:** the existing operator scheduler tests pass against the procrastinate backend with
the same response shapes, plus tests for pause and run-now.

### M5 Switch-over
1. Deploy with flag `apscheduler` (no behavior change), add DATABASE_URL on Render, run schema.py.
2. Flip SCHEDULER_BACKEND=procrastinate on Render (restart only). Watch the console for 24 h.
3. Rollback = set it back to `apscheduler` and restart.
4. After ~2 quiet weeks: delete APScheduler code, scheduler_runs writes, the flag and the dependency
   (separate change, asks first).

**Done when:** step 2 runs 24 h with every task green or explained, and step 3 was tried once.

## 6. Testing strategy

- **Unit (pytest, no DB):** task registry (24 ids, cron, queue, class), each task calls its service,
  pause check, rescue decision per class, console response shapes. Existing scheduler tests keep
  passing with the flag on `apscheduler`.
- **Integration (local throwaway Postgres, same harness as the 2026-10-31 test):** schema installs
  into `procrastinate`; two app copies produce one run per slot; the 3 crash cases; catch-up after a
  stop; retention. Never against the live Supabase DB.
- **Live check (M5 step 2):** operator Scheduler page shows all 24 tasks green within 1 h; Supabase
  connections stay under 30; /health latency unchanged in Render metrics.

## 7. Boundaries

**Always**
- Keep each job's business logic untouched; tasks only call existing service functions.
- Keep both backends working behind SCHEDULER_BACKEND until M5 step 4.
- Run `cd backend && python -m pytest` before each commit; commit to main.

**Ask first**
- Running schema.py / migration 238 on the live database.
- Any push to main (auto-deploys the backend), any Render env change, flipping the flag.
- Fixing the double-send guards of class C jobs (separate task).
- Deleting APScheduler code (M5 step 4).

**Never**
- Start the worker or the deferrer from a laptop against the live DB.
- Put queue tables in `public` without RLS.
- Auto re-run a class C job.
- Echo or commit DATABASE_URL or any secret.

## 8. Risks and open questions

| Risk | Mitigation |
|---|---|
| Procrastinate DDL may not install cleanly outside `public` | Build task 1 tests it locally; fallback in M1 |
| Cron timezone: Procrastinate evaluates cron in UTC | Convert IST times to UTC in the registry; test asserts the IST times |
| Async jobs still block the event loop (sync Supabase client), as today | Unchanged behavior; follow-up task to move them to threads |
| Supavisor session pool limits on the Free plan | Pool max 4; watch connections during M5 step 2 |
| Teammate (keerthi-sarav) edits main.py jobs during the build | git log check before /plan and before each commit |

## 9. Out of scope

Per-tenant fan-out of the 1-minute jobs, moving async jobs off the event loop, fixing class C
guards, a separate Render worker service, Supabase Pro.
