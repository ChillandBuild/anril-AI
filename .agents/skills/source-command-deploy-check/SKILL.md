---
name: "source-command-deploy-check"
description: "Production health check — backend /health, scheduler jobs, latest Render deploy, keep-alive cron"
---

# source-command-deploy-check

Use this skill when the user asks to run the migrated source command `deploy-check`.

## Command Template

When this skill is invoked, do the following in order. Report each step as a one-line PASS/WARN/FAIL.

## Step 1 — Backend liveness
`curl -s -o /dev/null -w "%{http_code}" --max-time 120 https://aira-ai-5tfr.onrender.com/health`
- 200 → PASS. Non-200 / timeout → FAIL (retry once — the service restarts every ~5h, so a request can land mid-restart; if it still fails, check Render logs).

## Step 2 — Scheduler health
Fetch the operator scheduler-health view (`GET /api/v1/operator/scheduler-health`) or query `scheduler_runs`.
Verify all 20 jobs have run within their interval + grace (source of truth: `_scheduler.add_job` in `backend/app/main.py`):
- 1-min: `scheduled-broadcasts`, `reengagement-rules`, `silence-nudge`, `callback-notifications`, `pending-whatsapp-alerts`, `auto-messages`
- `assignment-sweep` (2m), `call-ai-sweep` (3m), `astro-push-reconcile` (5m), `intake-staleness-sweep` (5m), `crm-cutoff-sweep` (10m), `recycle-contacts` (30m)
- `ad-insights-sync` (1h), `token-health-check` (4h), `number-quality-sync` (4h)
- Fixed IST times: `numbers-pool-sync` (06:00 + 18:00), `send-log-prune` (03:00), `private-send-meta-reconcile` (03:30), `call-alert-summary` (morning), `brain-weekly-digest` (Mon 09:00)
- Render recycles the process every ~5h, so a job "missing" just after a restart is normal; one missing for longer than its interval + 1h is not.
- Any job with no recent run or a logged error → WARN with the job id + last_run + error.

## Step 3 — Latest Render deploy
Use the Render MCP (`list_deploys` for service `aira-ai-backend`).
- Latest deploy `live` → PASS. `build_failed` / `update_failed` → FAIL with the deploy id.

## Step 4 — Keep-alive cron
Confirm `.github/workflows/keep-alive.yml` cron is `*/14 * * * *` and the last GH Actions run succeeded (`gh run list --workflow keep-alive.yml --limit 1`).
- Success → PASS. Failing → WARN (backend will cold-start, but app still works).

## Step 5 — Summary
One table: step / status / detail. End with overall verdict (HEALTHY / DEGRADED / DOWN). No trailing prose.
