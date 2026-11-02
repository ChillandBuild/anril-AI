"""The queue safety net (SPEC.md M3): the console pause switch, failures into scheduler_runs,
rescuing jobs a dead worker left in 'doing', and trimming old job rows.

Postgres tests need a throwaway database: set QUEUE_TEST_DSN (never the live database)."""
import asyncio
import os
import time

import pytest

from app.queue import safety

DSN = os.environ.get("QUEUE_TEST_DSN")
needs_pg = pytest.mark.skipif(not DSN, reason="QUEUE_TEST_DSN not set (throwaway Postgres only)")


def test_the_guard_wraps_every_job_and_the_safety_tasks_are_registered():
    from app.queue.app import queue_app
    import app.queue.tasks  # noqa: F401  (registers the periodic tasks)

    assert queue_app.worker_defaults["worker_middleware"] == [safety.guard]
    periodic = {pid: pt.cron for (_, pid), pt in queue_app.periodic_registry.periodic_tasks.items()}
    assert periodic["rescue-stalled"] == "* * * * *"
    assert periodic["queue-cleanup"] == "15 22 * * *"  # 03:45 IST
    assert queue_app.tasks["rescue-stalled"].queue == "maintenance"
    assert queue_app.tasks["queue-cleanup"].queue == "maintenance"


@pytest.fixture
def queue_db():
    """A fresh database with the queue installed and a copy of public.scheduler_runs."""
    import psycopg
    from psycopg.conninfo import make_conninfo
    from app.queue.schema import install

    name = "queue_safety_test"
    admin = make_conninfo(DSN, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {name}")
        for role in ("anon", "authenticated"):
            c.execute(f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    dsn = make_conninfo(DSN, dbname=name)
    asyncio.run(install(dsn))
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(
            "CREATE TABLE public.scheduler_runs (id bigserial PRIMARY KEY, job_id text NOT NULL, status text NOT NULL,"
            " scheduled_at timestamptz, ran_at timestamptz NOT NULL DEFAULT now(), lateness_ms integer, error text)"
        )
    yield dsn
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _app(dsn):
    import procrastinate
    from app.queue.app import _set_search_path

    return procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=dsn, configure=_set_search_path))


def _sql(dsn, query, *args):
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as c:
        cur = c.execute(query, args)
        return cur.fetchall() if cur.description else None


def _runs(dsn):
    return _sql(dsn, "SELECT job_id, status, scheduled_at, lateness_ms, error FROM public.scheduler_runs ORDER BY id")


class _Ctx:
    def __init__(self, app, task_name, timestamp=None, started=None):
        from procrastinate.jobs import Job

        kwargs = {} if timestamp is None else {"timestamp": timestamp}
        self.app = app
        self.job = Job(id=1, queue="messages", lock=None, queueing_lock=None, task_name=task_name, task_kwargs=kwargs)
        self.start_timestamp = started if started is not None else time.time()


async def _with_app(dsn, fn):
    app = _app(dsn)
    async with app.open_async():
        return await fn(app)


@needs_pg
def test_a_paused_task_is_skipped(queue_db):
    _sql(queue_db, "INSERT INTO procrastinate.task_controls (task_name, paused) VALUES ('auto-messages', true)")
    calls = []

    async def run(app):
        async def call_next():
            calls.append(1)

        return await safety.guard(call_next, _Ctx(app, "auto-messages", 0), None)

    assert asyncio.run(_with_app(queue_db, run)) is None
    assert calls == []
    assert _runs(queue_db) == []


@needs_pg
def test_an_unpaused_task_runs_and_success_writes_nothing(queue_db):
    _sql(queue_db, "INSERT INTO procrastinate.task_controls (task_name, paused) VALUES ('auto-messages', false)")

    async def run(app):
        async def call_next():
            return "done"

        return await safety.guard(call_next, _Ctx(app, "auto-messages", 0), None)

    assert asyncio.run(_with_app(queue_db, run)) == "done"
    assert _runs(queue_db) == []


@needs_pg
def test_a_failure_is_recorded_with_its_lateness_then_re_raised(queue_db):
    slot = 1_800_000_000

    async def run(app):
        async def call_next():
            raise RuntimeError("Meta said 500")

        await safety.guard(call_next, _Ctx(app, "sms-send", slot, started=slot + 2.5), None)

    with pytest.raises(RuntimeError, match="Meta said 500"):
        asyncio.run(_with_app(queue_db, run))
    [(job_id, status, scheduled_at, lateness_ms, error)] = _runs(queue_db)
    assert (job_id, status, error) == ("sms-send", "error", "Meta said 500")
    assert scheduled_at.timestamp() == slot
    assert lateness_ms == 2500


@needs_pg
def test_the_original_error_still_raises_when_recording_it_fails(queue_db):
    _sql(queue_db, "DROP TABLE public.scheduler_runs")

    async def run(app):
        async def call_next():
            raise ValueError("the real problem")

        await safety.guard(call_next, _Ctx(app, "sms-send", 0), None)

    with pytest.raises(ValueError, match="the real problem"):
        asyncio.run(_with_app(queue_db, run))


async def _defer_doing(app, task_name, attempts=0):
    """A job a dead worker left mid-run: status doing, no live worker."""
    job_id = await app.configure_task(name=task_name, allow_unknown=True, queue="maintenance").defer_async(timestamp=1_800_000_000)
    await app.connector.execute_query_async(
        "UPDATE procrastinate_jobs SET status = 'doing', attempts = %(attempts)s WHERE id = %(id)s",
        id=job_id, attempts=attempts,
    )
    return job_id


def _status(dsn, job_id):
    return _sql(dsn, "SELECT status::text, attempts FROM procrastinate.procrastinate_jobs WHERE id = %s", job_id)[0]


@needs_pg
def test_rescue_re_runs_an_idempotent_daily_job_once(queue_db):
    async def run(app):
        first = await _defer_doing(app, "send-log-prune")
        again = await _defer_doing(app, "numbers-pool-sync", attempts=1)
        await safety.rescue_stalled(app)
        return first, again

    first, again = asyncio.run(_with_app(queue_db, run))
    assert _status(queue_db, first) == ("todo", 1)
    assert _status(queue_db, again)[0] == "failed"
    assert [(r[0], r[4]) for r in _runs(queue_db)] == [("numbers-pool-sync", "worker died mid-run")]


@needs_pg
def test_rescue_never_re_runs_a_sweep_or_a_job_that_could_double_send(queue_db):
    async def run(app):
        return [await _defer_doing(app, name) for name in ("auto-messages", "silence-nudge")]

    ids = asyncio.run(_with_app(queue_db, run))
    asyncio.run(_with_app(queue_db, safety.rescue_stalled))
    assert [_status(queue_db, i)[0] for i in ids] == ["failed", "failed"]
    assert [(r[0], r[1], r[4]) for r in _runs(queue_db)] == [
        ("auto-messages", "error", "worker died mid-run"),
        ("silence-nudge", "error", "worker died mid-run"),
    ]


@needs_pg
def test_rescue_leaves_a_live_workers_job_alone(queue_db):
    async def run(app):
        job_id = await _defer_doing(app, "auto-messages")
        worker = await app.connector.execute_query_one_async(
            "INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now()) RETURNING id"
        )
        await app.connector.execute_query_async(
            "UPDATE procrastinate_jobs SET worker_id = %(w)s WHERE id = %(id)s", w=worker["id"], id=job_id
        )
        await safety.rescue_stalled(app)
        return job_id

    assert _status(queue_db, asyncio.run(_with_app(queue_db, run)))[0] == "doing"


@needs_pg
def test_cleanup_trims_old_rows_keeps_recent_ones_and_the_periodic_bookmark(queue_db):
    async def run(app):
        async def finished(task, status, hours_ago, periodic=False):
            job_id = await app.configure_task(name=task, allow_unknown=True).defer_async(timestamp=hours_ago)
            await app.connector.execute_query_async(
                "UPDATE procrastinate_jobs SET status = %(status)s WHERE id = %(id)s", id=job_id, status=status
            )
            await app.connector.execute_query_async(
                "UPDATE procrastinate_events SET at = now() - make_interval(hours => %(h)s) WHERE job_id = %(id)s",
                id=job_id, h=hours_ago,
            )
            if periodic:  # the bookmark that stops a slot being deferred twice points at its job
                await app.connector.execute_query_async(
                    "INSERT INTO procrastinate_periodic_defers (task_name, periodic_id, defer_timestamp, job_id)"
                    " VALUES (%(t)s, %(t)s, 1, %(id)s)",
                    t=task, id=job_id,
                )
            return job_id

        jobs = {
            "old_ok": await finished("auto-messages", "succeeded", 49),
            "new_ok": await finished("auto-messages", "succeeded", 47),
            "old_fail": await finished("sms-send", "failed", 337),
            "new_fail": await finished("sms-send", "failed", 49),
            "weekly_latest": await finished("brain-weekly-digest", "succeeded", 100, periodic=True),
            "todo": await finished("auto-messages", "todo", 500),
        }
        await safety.cleanup(app)
        return jobs

    jobs = asyncio.run(_with_app(queue_db, run))
    left = {r[0] for r in _sql(queue_db, "SELECT id FROM procrastinate.procrastinate_jobs")}
    assert {k for k, v in jobs.items() if v in left} == {"new_ok", "new_fail", "todo"}
    assert _sql(queue_db, "SELECT task_name, job_id FROM procrastinate.procrastinate_periodic_defers") == [
        ("brain-weekly-digest", None)
    ]
