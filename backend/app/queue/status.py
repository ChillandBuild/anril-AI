"""Operator-console reads and writes against the Procrastinate queue (SPEC.md M4): per-task
run state, the pause switch, and run-now. Everything goes through queue_app.connector, which is
async, so callers must await these from the event loop and never block it."""
from datetime import datetime, timezone

from croniter import croniter

# One query for every task: the newest finished run (succeeded/failed), then its start time for
# just those rows. Lateness = when the worker started the job minus the periodic slot it was for.
LAST_RUNS_SQL = """
SELECT l.task_name, l.outcome, l.finished_at, s.started_at, l.slot_epoch
FROM (
    SELECT DISTINCT ON (j.task_name)
           j.task_name, e.job_id, e.type::text AS outcome, e.at AS finished_at,
           (j.args->>'timestamp')::bigint AS slot_epoch
    FROM procrastinate_events e
    JOIN procrastinate_jobs j ON j.id = e.job_id
    WHERE e.type IN ('succeeded', 'failed')
    ORDER BY j.task_name, e.at DESC, e.id DESC
) l
LEFT JOIN LATERAL (
    SELECT max(at) AS started_at FROM procrastinate_events
    WHERE job_id = l.job_id AND type = 'started'
) s ON true
"""

LAST_SUCCESS_SQL = """
SELECT j.task_name, max(e.at) AS at
FROM procrastinate_events e JOIN procrastinate_jobs j ON j.id = e.job_id
WHERE e.type = 'succeeded'
GROUP BY j.task_name
"""

PAUSED_SQL = "SELECT task_name FROM task_controls WHERE paused"

def _utc(t: datetime | None) -> datetime | None:
    """The connection's session timezone leaks into timestamptz values; the console speaks UTC."""
    return t.astimezone(timezone.utc) if t else None


def registered_tasks(app) -> dict:
    """task name -> PeriodicTask, sorted by name (the order the page lists them in)."""
    return {name: pt for (name, _pid), pt in sorted(app.periodic_registry.periodic_tasks.items())}


def next_run(cron: str, now: datetime) -> datetime:
    return croniter(cron, now).get_next(datetime)


def interval_seconds(cron: str, now: datetime) -> float | None:
    """The constant gap between fires for every-N-minutes/hours crons; None for daily/weekly
    (or any cron whose consecutive gaps differ, e.g. '0 */5 * * *' wraps at midnight)."""
    it = croniter(cron, now)
    fires = [it.get_next(datetime) for _ in range(6)]
    gaps = {(b - a).total_seconds() for a, b in zip(fires, fires[1:])}
    if len(gaps) != 1:
        return None
    gap = gaps.pop()
    return gap if gap < 86400 else None


async def build_jobs(app, now: datetime, runs_failures, started_at: datetime | None) -> list[dict]:
    """Same dicts as the APScheduler branch of operator._build_scheduler_jobs. `started_at` is
    when this process started its scheduler: a task with no success since boot is judged from it.
    `runs_failures(task_name)` -> (last_failure_row | None, errors_24h): the scheduler_runs
    lookups, which stay in operator.py (sync Supabase calls, sent to a thread there)."""
    conn = app.connector
    last = {r["task_name"]: r for r in await conn.execute_query_all_async(LAST_RUNS_SQL)}
    ok = {r["task_name"]: _utc(r["at"]) for r in await conn.execute_query_all_async(LAST_SUCCESS_SQL)}
    paused = {r["task_name"] for r in await conn.execute_query_all_async(PAUSED_SQL)}

    out = []
    for name, pt in registered_tasks(app).items():
        row = last.get(name)
        failure, errors_24h = await runs_failures(name)
        status = {"succeeded": "success", "failed": "error"}.get(row["outcome"]) if row else None
        lateness = None
        if row and row["started_at"] is not None and row["slot_epoch"] is not None:
            lateness = int((row["started_at"].timestamp() - row["slot_epoch"]) * 1000)
        last_success = ok.get(name)
        out.append({
            "id": name,
            "next_run": None if name in paused else next_run(pt.cron, now).isoformat(),
            "paused": name in paused,
            "last_status": status,
            "last_run": _utc(row["finished_at"]).isoformat() if row else None,
            "last_lateness_ms": lateness,
            "last_error": (failure or {}).get("error") if status == "error" else None,
            "errors_24h": errors_24h,
            "last_success": last_success.isoformat() if last_success else None,
            "interval_seconds": interval_seconds(pt.cron, now),
            "watch_from": max((t for t in (last_success, started_at) if t), default=None),
        })
    return out


async def toggle(app, job_id: str, now: datetime) -> dict | None:
    """Flip the pause switch. None for an unknown task."""
    pt = registered_tasks(app).get(job_id)
    if pt is None:
        return None
    row = await app.connector.execute_query_one_async(
        """INSERT INTO task_controls (task_name, paused, updated_at) VALUES (%(n)s, true, now())
           ON CONFLICT (task_name) DO UPDATE SET paused = NOT task_controls.paused, updated_at = now()
           RETURNING paused""",
        n=job_id,
    )
    paused = bool(row["paused"])
    return {"id": job_id, "paused": paused,
            "next_run": None if paused else next_run(pt.cron, now).isoformat()}


async def is_paused(app, job_id: str) -> bool:
    rows = await app.connector.execute_query_all_async(
        "SELECT paused FROM task_controls WHERE task_name = %(n)s", n=job_id)
    return bool(rows and rows[0]["paused"])


async def run_now(app, job_id: str, now: datetime):
    """Defer the task for right now. Returns the PeriodicTask, or None for an unknown id."""
    pt = registered_tasks(app).get(job_id)
    if pt is not None:
        await pt.task.defer_async(timestamp=int(now.replace(tzinfo=now.tzinfo or timezone.utc).timestamp()))
    return pt
