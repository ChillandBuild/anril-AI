"""Operator scheduler console on the Procrastinate backend (SPEC.md M4): same response shapes as
the APScheduler branch, read from procrastinate_jobs/events and task_controls.

Needs a throwaway Postgres: set QUEUE_TEST_DSN (never the live database)."""
import asyncio
import contextlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

DSN = os.environ.get("QUEUE_TEST_DSN")
needs_pg = pytest.mark.skipif(not DSN, reason="QUEUE_TEST_DSN not set (throwaway Postgres only)")

NOW = datetime(2026, 10, 31, 12, 0, 30, tzinfo=timezone.utc)
BOOT = NOW - timedelta(hours=1)  # this process started an hour ago
APSCHEDULER_KEYS = {
    "id", "next_run", "paused", "last_status", "last_run", "last_lateness_ms", "last_error",
    "errors_24h", "last_success", "interval_seconds", "watch_from",
}


@pytest.fixture
def fresh_db():
    import psycopg
    from psycopg.conninfo import make_conninfo

    name = "queue_operator_test"
    admin = make_conninfo(DSN, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name}")
        c.execute(f"CREATE DATABASE {name}")
        for role in ("anon", "authenticated"):
            c.execute(f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    dsn = make_conninfo(DSN, dbname=name)
    from app.queue.schema import install
    asyncio.run(install(dsn))
    yield dsn
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@contextlib.asynccontextmanager
async def open_queue(dsn):
    """queue_app pointed at the throwaway database for the duration of the block."""
    import procrastinate
    from app.queue.app import _set_search_path, queue_app

    connector = procrastinate.PsycopgConnector(conninfo=dsn, min_size=1, max_size=2, configure=_set_search_path)
    with queue_app.replace_connector(connector):
        await connector.open_async()
        try:
            yield queue_app
        finally:
            await connector.close_async()


def sql(dsn, query, *params):
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else None


def seed_job(dsn, task, slot, outcome, started_at, finished_at, queue="messages"):
    """One finished periodic job: deferred -> started -> succeeded|failed."""
    import psycopg
    status = "succeeded" if outcome == "succeeded" else "failed"
    with psycopg.connect(dsn, autocommit=True) as c:
        jid = c.execute(
            "INSERT INTO procrastinate.procrastinate_jobs (queue_name, task_name, args, status, scheduled_at) "
            "VALUES (%s, %s, %s::jsonb, %s::procrastinate.procrastinate_job_status, %s) RETURNING id",
            (queue, task, f'{{"timestamp": {slot}}}', status, started_at)).fetchone()[0]
        c.execute("DELETE FROM procrastinate.procrastinate_events WHERE job_id = %s", (jid,))
        for kind, at in (("started", started_at), (outcome, finished_at)):
            c.execute("INSERT INTO procrastinate.procrastinate_events (job_id, type, at) "
                      "VALUES (%s, %s::procrastinate.procrastinate_job_event_type, %s)", (jid, kind, at))
    return jid


def failures_db(rows=None, errors=0):
    """A fake Supabase for the scheduler_runs lookups, shaped like test_scheduler_runs_recording."""
    db = MagicMock()
    q = db.table.return_value.select.return_value.eq.return_value
    q.order.return_value.limit.return_value.execute.return_value.data = rows or []
    q.eq.return_value.gte.return_value.execute.return_value.count = errors
    return db


def build(dsn, db=None):
    from app.routes import operator

    async def go():
        async with open_queue(dsn):
            return await operator._build_queue_scheduler_jobs(db or failures_db(), NOW)

    with patch("app.routes.operator.settings") as s, patch("app.main._scheduler_started_at", BOOT):
        s.scheduler_backend = "procrastinate"
        return {j["id"]: j for j in asyncio.run(go())}


@needs_pg
def test_every_registered_task_is_listed_with_exactly_the_apscheduler_keys(fresh_db):
    import app.queue.tasks  # noqa: F401  (registers the periodic tasks)
    from app.queue.app import queue_app

    jobs = build(fresh_db)
    assert len(jobs) == len(queue_app.periodic_registry.periodic_tasks) >= 24
    assert list(jobs) == sorted(jobs)
    assert all(set(j) == APSCHEDULER_KEYS for j in jobs.values())
    quiet = jobs["token-health-check"]
    assert quiet["last_status"] is None and quiet["last_run"] is None and quiet["last_success"] is None
    assert quiet["errors_24h"] == 0 and quiet["paused"] is False
    assert quiet["watch_from"] == BOOT  # no success yet: judged from this process's start


@needs_pg
def test_next_run_and_interval_come_from_the_cron(fresh_db):
    jobs = build(fresh_db)
    minute = jobs["scheduled-broadcasts"]  # * * * * *
    assert minute["next_run"] == datetime(2026, 10, 31, 12, 1, tzinfo=timezone.utc).isoformat()
    assert minute["interval_seconds"] == 60
    assert jobs["assignment-sweep"]["interval_seconds"] == 120
    assert jobs["token-health-check"]["interval_seconds"] == 4 * 3600
    daily = jobs["send-log-prune"]  # 30 21 * * *
    assert daily["next_run"] == datetime(2026, 10, 31, 21, 30, tzinfo=timezone.utc).isoformat()
    assert daily["interval_seconds"] is None
    assert jobs["brain-weekly-digest"]["interval_seconds"] is None


@needs_pg
def test_last_success_run_and_lateness_come_from_the_events(fresh_db):
    slot = int(datetime(2026, 10, 31, 11, 59, tzinfo=timezone.utc).timestamp())
    started = datetime(2026, 10, 31, 11, 59, 2, tzinfo=timezone.utc)
    seed_job(fresh_db, "scheduled-broadcasts", slot - 60, "succeeded",
             started - timedelta(minutes=1), started - timedelta(minutes=1) + timedelta(seconds=1))
    seed_job(fresh_db, "scheduled-broadcasts", slot, "succeeded", started, started + timedelta(seconds=1))
    job = build(fresh_db)["scheduled-broadcasts"]
    assert job["last_status"] == "success"
    assert job["last_run"] == (started + timedelta(seconds=1)).isoformat()
    assert job["last_success"] == (started + timedelta(seconds=1)).isoformat()
    assert job["last_lateness_ms"] == 2000
    assert job["last_error"] is None
    assert job["watch_from"] == started + timedelta(seconds=1)  # newer than boot


@needs_pg
def test_a_newer_failure_wins_and_reads_its_error_from_scheduler_runs(fresh_db):
    slot = int(datetime(2026, 10, 31, 11, 58, tzinfo=timezone.utc).timestamp())
    t = datetime(2026, 10, 31, 11, 58, 1, tzinfo=timezone.utc)
    seed_job(fresh_db, "auto-messages", slot - 60, "succeeded", t - timedelta(minutes=1), t - timedelta(minutes=1))
    seed_job(fresh_db, "auto-messages", slot, "failed", t, t + timedelta(seconds=1))
    db = failures_db([{"status": "error", "ran_at": t.isoformat(), "lateness_ms": 1000, "error": "boom"}], errors=1)
    job = build(fresh_db, db)["auto-messages"]
    assert job["last_status"] == "error"
    assert job["last_error"] == "boom"
    assert job["errors_24h"] == 1
    assert job["last_success"] == (t - timedelta(minutes=1)).isoformat()
    assert job["last_lateness_ms"] == 1000


@needs_pg
def test_a_paused_task_reports_paused_and_no_next_run(fresh_db):
    sql(fresh_db, "INSERT INTO procrastinate.task_controls (task_name, paused) VALUES ('sms-send', true)")
    sql(fresh_db, "INSERT INTO procrastinate.task_controls (task_name, paused) VALUES ('sms-reconcile', false)")
    jobs = build(fresh_db)
    assert jobs["sms-send"]["paused"] is True and jobs["sms-send"]["next_run"] is None
    assert jobs["sms-reconcile"]["paused"] is False and jobs["sms-reconcile"]["next_run"]


def call(dsn, coro_fn, backend="procrastinate"):
    from app.routes import operator

    async def go():
        async with open_queue(dsn):
            return await coro_fn(operator)

    with patch("app.routes.operator.settings") as s:
        s.scheduler_backend = backend
        return asyncio.run(go())


@needs_pg
def test_toggle_flips_task_controls_and_back(fresh_db):
    first = call(fresh_db, lambda op: op.toggle_scheduler_job("sms-send", _admin={}))
    assert first["id"] == "sms-send" and first["paused"] is True and first["next_run"] is None
    assert sql(fresh_db, "SELECT paused FROM procrastinate.task_controls WHERE task_name='sms-send'") == [(True,)]
    second = call(fresh_db, lambda op: op.toggle_scheduler_job("sms-send", _admin={}))
    assert second["paused"] is False and second["next_run"]
    assert sql(fresh_db, "SELECT paused FROM procrastinate.task_controls WHERE task_name='sms-send'") == [(False,)]


@needs_pg
def test_toggle_unknown_task_is_404(fresh_db):
    with pytest.raises(HTTPException) as e:
        call(fresh_db, lambda op: op.toggle_scheduler_job("nope", _admin={}))
    assert e.value.status_code == 404 and e.value.detail == "Job 'nope' not found"
    assert sql(fresh_db, "SELECT count(*) FROM procrastinate.task_controls") == [(0,)]


@needs_pg
def test_run_now_defers_a_job_with_a_timestamp(fresh_db):
    out = call(fresh_db, lambda op: op.run_scheduler_job("sms-send", _admin={"user_id": "u"}))
    assert out["id"] == "sms-send" and out["triggered"] is True and out["next_run"]
    rows = sql(fresh_db, "SELECT task_name, queue_name, status::text, args->>'timestamp' "
                         "FROM procrastinate.procrastinate_jobs")
    assert len(rows) == 1 and rows[0][:3] == ("sms-send", "messages", "todo")
    assert abs(int(rows[0][3]) - datetime.now(timezone.utc).timestamp()) < 30


@needs_pg
def test_run_now_on_a_paused_task_is_409_and_defers_nothing(fresh_db):
    sql(fresh_db, "INSERT INTO procrastinate.task_controls (task_name, paused) VALUES ('sms-send', true)")
    with pytest.raises(HTTPException) as e:
        call(fresh_db, lambda op: op.run_scheduler_job("sms-send", _admin={}))
    assert e.value.status_code == 409 and "paused" in e.value.detail
    assert sql(fresh_db, "SELECT count(*) FROM procrastinate.procrastinate_jobs") == [(0,)]


@needs_pg
def test_run_now_unknown_task_is_404(fresh_db):
    with pytest.raises(HTTPException) as e:
        call(fresh_db, lambda op: op.run_scheduler_job("nope", _admin={}))
    assert e.value.status_code == 404


def test_a_closed_queue_app_answers_503_on_every_scheduler_route():
    from app.routes import operator

    async def attempts():
        out = []
        for fn in (
            lambda: operator._build_queue_scheduler_jobs(MagicMock(), NOW),
            lambda: operator.toggle_scheduler_job("sms-send", _admin={}),
            lambda: operator.run_scheduler_job("sms-send", _admin={}),
            lambda: operator.scheduler_health(_admin={}),
        ):
            with pytest.raises(HTTPException) as e:
                await fn()
            out.append((e.value.status_code, e.value.detail))
        return out

    with patch("app.routes.operator.settings") as s, patch("app.routes.operator.get_supabase"):
        s.scheduler_backend = "procrastinate"
        # queue_app is never opened in this test: AppNotOpen -> 503
        result = asyncio.run(attempts())
    assert result == [(503, "Task queue not connected")] * 4


def test_alerts_do_not_crash_when_the_queue_is_closed():
    from app.routes import operator

    with patch("app.routes.operator.settings") as s, patch("app.routes.operator.get_supabase"), \
            patch("app.routes.operator._build_fleet_rows", return_value=[]):
        s.scheduler_backend = "procrastinate"
        assert asyncio.run(operator.operator_alerts(_admin={})) == {"data": []}


def test_apscheduler_backend_never_touches_the_queue():
    from app.routes import operator
    from app.queue.app import queue_app

    sched = MagicMock()
    sched.get_job.return_value = None
    with patch("app.routes.operator.settings") as s, patch("app.main._scheduler", sched), \
            patch.object(queue_app.connector, "execute_query_one_async", side_effect=AssertionError("queue touched")):
        s.scheduler_backend = "apscheduler"
        with pytest.raises(HTTPException) as e:
            asyncio.run(operator.toggle_scheduler_job("x", _admin={}))
    assert e.value.status_code == 404
