"""Lifespan wiring for SCHEDULER_BACKEND (SPEC.md M5): on the queue backend APScheduler keeps the
24 jobs registered but paused and a Procrastinate worker runs as a background task; a laptop
(SCHEDULER_ENABLED=false) never opens a queue connection."""
import asyncio
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

import app.main
from tests.test_scheduler_local_mode import FakeScheduler


async def _lifespan(backend, enabled, database_url="postgresql://x"):
    fake = FakeScheduler()
    worker = AsyncMock()
    with patch("app.main._scheduler", fake), \
            patch("app.main._run_queue_worker", worker), \
            patch("app.main.settings.scheduler_backend", backend), \
            patch("app.main.settings.scheduler_enabled", enabled), \
            patch("app.main.settings.database_url", database_url):
        async with app.main.lifespan(app.main.app):
            await asyncio.sleep(0)
    return fake, worker


@pytest.mark.asyncio
async def test_queue_backend_pauses_apscheduler_and_starts_the_worker(caplog):
    caplog.set_level(logging.INFO, logger="app.main")
    fake, worker = await _lifespan("procrastinate", True)
    assert fake.calls["start"][0][1]["paused"] is True
    assert len(fake.calls["add_job"]) == 24
    worker.assert_awaited_once()
    assert "Schedulers started (procrastinate)" in caplog.text


@pytest.mark.asyncio
async def test_a_laptop_on_the_queue_backend_opens_no_connection(caplog):
    fake, worker = await _lifespan("procrastinate", False)
    assert fake.calls["start"][0][1]["paused"] is True
    worker.assert_not_called()
    assert "SCHEDULER_ENABLED=false" in caplog.text


@pytest.mark.asyncio
async def test_apscheduler_backend_is_unchanged():
    fake, worker = await _lifespan("apscheduler", True)
    assert fake.calls["start"][0][1]["paused"] is False
    worker.assert_not_called()


@pytest.mark.asyncio
async def test_queue_backend_without_database_url_falls_back_to_apscheduler(caplog):
    fake, worker = await _lifespan("procrastinate", True, database_url=None)
    assert fake.calls["start"][0][1]["paused"] is False
    worker.assert_not_called()
    assert "DATABASE_URL is not set" in caplog.text


@pytest.mark.asyncio
async def test_the_worker_retries_after_a_connection_error_and_stops_on_cancel(caplog):
    from app.queue.app import queue_app

    opens, ran = [], asyncio.Event()

    @asynccontextmanager
    async def open_async():
        opens.append(1)
        if len(opens) == 1:
            raise OSError("pooler unreachable")
        yield queue_app

    async def run_worker_async(**kwargs):
        assert kwargs["install_signal_handlers"] is False
        ran.set()
        await asyncio.Event().wait()

    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    with patch.object(queue_app, "open_async", open_async), \
            patch.object(queue_app, "run_worker_async", run_worker_async), \
            patch("app.main.asyncio.sleep", fake_sleep):
        task = asyncio.create_task(app.main._run_queue_worker())
        await asyncio.wait_for(ran.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(opens) == 2 and sleeps == [30]
    assert "pooler unreachable" in caplog.text
