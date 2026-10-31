"""scheduler_runs keeps only failures. A success row for every run of every 1-minute job
grew the table to 307 MB of a 353 MB database and ~12k API writes a day (2026-10-31), so
successes live in memory (app.main._last_success) and the health view reads them there."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED

import app.main
from app.routes.operator import _build_scheduler_jobs

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _event(code, job_id="auto-messages", exception=None):
    return SimpleNamespace(
        code=code, job_id=job_id, exception=exception,
        scheduled_run_time=datetime.now(timezone.utc) - timedelta(seconds=2),
    )


@pytest.fixture(autouse=True)
def _clean_memory():
    app.main._last_success.clear()
    yield
    app.main._last_success.clear()


def test_a_successful_run_is_kept_in_memory_not_written():
    db = MagicMock()
    with patch("app.db.supabase.get_supabase", return_value=db):
        app.main._record_scheduler_event(_event(EVENT_JOB_EXECUTED))
    db.table.assert_not_called()
    ok = app.main._last_success["auto-messages"]
    assert ok["ran_at"] and ok["lateness_ms"] >= 2000


@pytest.mark.parametrize("code,status", [(EVENT_JOB_ERROR, "error"), (EVENT_JOB_MISSED, "missed")])
def test_failures_are_still_written(code, status):
    db = MagicMock()
    with patch("app.db.supabase.get_supabase", return_value=db):
        app.main._record_scheduler_event(_event(code, exception=RuntimeError("boom")))
    db.table.assert_called_once_with("scheduler_runs")
    row = db.table.return_value.insert.call_args.args[0]
    assert row["status"] == status
    assert "auto-messages" not in app.main._last_success


def _health(last_failure, errors_24h=0):
    db = MagicMock()
    q = db.table.return_value.select.return_value.eq.return_value
    q.order.return_value.limit.return_value.execute.return_value.data = [last_failure] if last_failure else []
    q.eq.return_value.gte.return_value.execute.return_value.count = errors_24h
    job = SimpleNamespace(
        id="auto-messages", next_run_time=NOW + timedelta(minutes=1),
        trigger=SimpleNamespace(interval=timedelta(minutes=1)),
    )
    sched = SimpleNamespace(get_jobs=lambda: [job])
    with patch("app.main._scheduler", sched), patch("app.main._scheduler_started_at", NOW - timedelta(hours=1)):
        return _build_scheduler_jobs(db, NOW)[0], db


def test_health_shows_a_success_newer_than_the_last_failure():
    app.main._last_success["auto-messages"] = {"ran_at": (NOW - timedelta(seconds=30)).isoformat(), "lateness_ms": 1500}
    job, _ = _health({"status": "error", "ran_at": (NOW - timedelta(hours=3)).isoformat(),
                      "lateness_ms": 900, "error": "boom"})
    assert job["last_status"] == "success"
    assert job["last_error"] is None
    assert job["last_lateness_ms"] == 1500
    assert job["last_success"] == app.main._last_success["auto-messages"]["ran_at"]
    assert job["watch_from"] == NOW - timedelta(seconds=30)


def test_health_shows_a_failure_newer_than_the_last_success():
    app.main._last_success["auto-messages"] = {"ran_at": (NOW - timedelta(hours=3)).isoformat(), "lateness_ms": 1500}
    job, _ = _health({"status": "error", "ran_at": (NOW - timedelta(seconds=30)).isoformat(),
                      "lateness_ms": 900, "error": "boom"}, errors_24h=1)
    assert job["last_status"] == "error"
    assert job["last_error"] == "boom"
    assert job["errors_24h"] == 1


def test_health_with_no_success_since_boot_watches_from_boot():
    job, _ = _health(None)
    assert job["last_status"] is None
    assert job["last_success"] is None
    assert job["watch_from"] == NOW - timedelta(hours=1)


@pytest.mark.asyncio
async def test_the_nightly_prune_drops_rows_older_than_7_days():
    db = MagicMock()
    with patch("app.db.supabase.get_supabase", return_value=db):
        await app.main._prune_scheduler_runs()
    db.table.assert_called_once_with("scheduler_runs")
    col, cutoff = db.table.return_value.delete.return_value.lt.call_args.args
    assert col == "ran_at"
    age = datetime.now(timezone.utc) - datetime.fromisoformat(cutoff)
    assert timedelta(days=7) - timedelta(minutes=1) < age < timedelta(days=7) + timedelta(minutes=1)
