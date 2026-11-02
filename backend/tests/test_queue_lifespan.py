"""Lifespan wiring (SPEC.md M5): the Procrastinate worker runs as a background task of the web
process. A laptop (SCHEDULER_ENABLED=false, scripts/dev-backend.sh) or a missing DATABASE_URL never
starts it, so nothing scheduled runs and no queue connection is opened."""
import asyncio
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

import app.main


async def _lifespan(enabled, database_url="postgresql://x"):
    worker = AsyncMock()
    with patch("app.main._run_queue_worker", worker), \
            patch("app.main.settings.scheduler_enabled", enabled), \
            patch("app.main.settings.database_url", database_url):
        async with app.main.lifespan(app.main.app):
            await asyncio.sleep(0)
    return worker


@pytest.mark.asyncio
async def test_production_starts_the_queue_worker(caplog):
    caplog.set_level(logging.INFO, logger="app.main")
    worker = await _lifespan(True)
    worker.assert_awaited_once()
    assert "Schedulers started (procrastinate)" in caplog.text


@pytest.mark.asyncio
async def test_a_laptop_starts_no_worker_and_says_so(caplog):
    worker = await _lifespan(False)
    worker.assert_not_called()
    assert any(
        "SCHEDULER_ENABLED=false" in r.message and r.levelname == "WARNING" for r in caplog.records
    )


@pytest.mark.asyncio
async def test_without_database_url_no_job_runs_and_it_is_logged(caplog):
    worker = await _lifespan(True, database_url=None)
    worker.assert_not_called()
    assert any("DATABASE_URL is not set" in r.message and r.levelname == "ERROR" for r in caplog.records)


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
