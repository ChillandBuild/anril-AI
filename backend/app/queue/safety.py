"""The queue's safety net (SPEC.md M3): the operator console's pause switch, failures into
scheduler_runs (Procrastinate keeps no error text), rescuing jobs a dead worker left in 'doing',
and trimming old job rows. Imports nothing from app.queue.app, which wires `guard` in."""
import logging
from datetime import datetime, timezone

from procrastinate.jobs import Status

logger = logging.getLogger(__name__)

STALLED_NOTE = "worker died mid-run"
# Event-loop freezes of 35-45 s were seen on 24 and 26 Oct; a shorter cut-off would fail
# jobs that are still running on a worker that merely missed its 10 s heartbeats.
STALLED_AFTER_SECONDS = 120


async def _record_failure(connector, task_name: str, slot: int | None, error: str, started: float | None) -> None:
    """One scheduler_runs row per failure: the error text the Scheduler page shows. Best-effort."""
    try:
        scheduled = datetime.fromtimestamp(slot, timezone.utc) if slot is not None else None
        lateness_ms = int((started - slot) * 1000) if slot is not None and started is not None else None
        await connector.execute_query_async(
            "INSERT INTO public.scheduler_runs (job_id, status, scheduled_at, ran_at, lateness_ms, error)"
            " VALUES (%(job_id)s, 'error', %(scheduled_at)s, now(), %(lateness_ms)s, %(error)s)",
            job_id=task_name, scheduled_at=scheduled, lateness_ms=lateness_ms, error=error[:2000],
        )
    except Exception as e:
        logger.warning(f"scheduler_runs record failed (non-fatal): {e}")


async def guard(call_next, context, worker):
    """Worker middleware around every job: skip a paused task; record a failure, then re-raise
    so the job is marked failed."""
    job = context.job
    row = await context.app.connector.execute_query_one_async(
        "SELECT EXISTS (SELECT 1 FROM task_controls WHERE task_name = %(name)s AND paused) AS paused",
        name=job.task_name,
    )
    if row["paused"]:
        logger.info(f"Queue task {job.task_name} skipped: paused in the operator console")
        return None
    try:
        return await call_next()
    except Exception as e:
        await _record_failure(
            context.app.connector, job.task_name, job.task_kwargs.get("timestamp"), str(e), context.start_timestamp
        )
        raise


async def rescue_stalled(app) -> None:
    """Jobs a dead worker left in 'doing': an idempotent daily job (class B) runs once more,
    anything else is marked failed — a sweep's next tick redoes it, and a send may have gone out."""
    from app.queue.tasks import RETRY_CLASS

    jm = app.job_manager
    for job in await jm.get_stalled_jobs(seconds_since_heartbeat=STALLED_AFTER_SECONDS):
        if RETRY_CLASS.get(job.task_name) == "B" and job.attempts == 0:
            await jm.retry_job(job)
            logger.warning(f"Queue rescue: re-running {job.task_name} (job {job.id}), its worker died mid-run")
            continue
        await jm.finish_job_by_id_async(job.id, Status.FAILED, delete_job=False)
        await _record_failure(app.connector, job.task_name, job.task_kwargs.get("timestamp"), STALLED_NOTE, None)
        logger.warning(f"Queue rescue: marked {job.task_name} (job {job.id}) failed, its worker died mid-run")


async def cleanup(app) -> None:
    """Succeeded jobs go after 2 days; failed, cancelled and aborted ones after 14."""
    jm = app.job_manager
    await jm.delete_old_jobs(nb_hours=48)
    await jm.delete_old_jobs(nb_hours=14 * 24, include_failed=True, include_cancelled=True, include_aborted=True)
