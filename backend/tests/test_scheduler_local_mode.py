"""Tests for scheduler paused mode when scheduler_enabled=False.

Ensures that when settings.scheduler_enabled is False, the scheduler starts
paused so jobs are registered (Health view works) but nothing executes.

Run with:
    cd backend && python -m pytest tests/test_scheduler_local_mode.py -q -p no:cacheprovider
"""
import asyncio
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main


class FakeScheduler:
    """Minimal fake scheduler to capture calls without starting a real one."""
    def __init__(self):
        self.calls = {
            'add_job': [],
            'add_listener': [],
            'start': [],
            'shutdown': [],
        }

    def add_job(self, *args, **kwargs):
        self.calls['add_job'].append(('add_job', args, kwargs))

    def add_listener(self, *args, **kwargs):
        self.calls['add_listener'].append(('add_listener', args, kwargs))

    def start(self, **kwargs):
        self.calls['start'].append(('start', kwargs))

    def get_jobs(self):
        return self.calls['add_job']

    def shutdown(self, **kwargs):
        self.calls['shutdown'].append(('shutdown', kwargs))


@pytest.mark.asyncio
async def test_scheduler_starts_paused_when_disabled():
    """With scheduler_enabled=False, _scheduler.start(paused=True)."""
    fake_scheduler = FakeScheduler()

    with patch('app.main._scheduler', fake_scheduler):
        with patch('app.main.settings.scheduler_enabled', False):
            async with app.main.lifespan(app.main.app):
                pass

    # Verify start() was called
    assert len(fake_scheduler.calls['start']) == 1
    start_call = fake_scheduler.calls['start'][0]
    assert start_call[0] == 'start'
    assert start_call[1].get('paused') is True, f"Expected paused=True, got {start_call[1]}"


@pytest.mark.asyncio
async def test_scheduler_starts_unpaused_when_enabled():
    """With scheduler_enabled=True, _scheduler.start() is called without paused or paused=False."""
    fake_scheduler = FakeScheduler()

    with patch('app.main._scheduler', fake_scheduler):
        with patch('app.main.settings.scheduler_enabled', True):
            async with app.main.lifespan(app.main.app):
                pass

    # Verify start() was called
    assert len(fake_scheduler.calls['start']) == 1
    start_call = fake_scheduler.calls['start'][0]
    assert start_call[0] == 'start'
    # paused should be False or absent
    paused_arg = start_call[1].get('paused')
    assert paused_arg is not True, f"Expected paused=False or absent, got {paused_arg}"


@pytest.mark.asyncio
async def test_warning_log_when_disabled(caplog):
    """With scheduler_enabled=False, logs WARNING with 'SCHEDULER_ENABLED=false'."""
    import logging
    caplog.set_level(logging.WARNING, logger='app.main')

    fake_scheduler = FakeScheduler()

    with patch('app.main._scheduler', fake_scheduler):
        with patch('app.main.settings.scheduler_enabled', False):
            async with app.main.lifespan(app.main.app):
                pass

    # Check for the warning message
    assert any('SCHEDULER_ENABLED=false' in record.message
               for record in caplog.records
               if record.levelname == 'WARNING')


@pytest.mark.asyncio
async def test_info_log_when_enabled(caplog):
    """With scheduler_enabled=True, logs INFO with the scheduler message."""
    import logging
    caplog.set_level(logging.INFO, logger='app.main')

    fake_scheduler = FakeScheduler()

    with patch('app.main._scheduler', fake_scheduler):
        with patch('app.main.settings.scheduler_enabled', True):
            async with app.main.lifespan(app.main.app):
                pass

    # Check for the info message containing the scheduler list
    assert any('Schedulers started' in record.message
               for record in caplog.records
               if record.levelname == 'INFO')
