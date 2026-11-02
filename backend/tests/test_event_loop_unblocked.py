"""A stalled Supabase query must not freeze the whole server.

The Supabase client is synchronous. Run on the event loop, one stalled query
froze every request, health checks and the scheduler for 35-45 s during
AstroTamil's partner-send campaigns (24 and 26 Oct 2026); requests that arrived
meanwhile were never processed. These tests stall the database and check the
loop keeps ticking.
"""
import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, Request

STALL = 0.5  # seconds each fake query blocks


class _StallingQuery:
    """Any builder chain; execute() blocks like a stalled Supabase call."""

    def __init__(self, data):
        self._data = data

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        time.sleep(STALL)
        return MagicMock(data=self._data)


class _StallingDB:
    def __init__(self, by_table):
        self._by_table = by_table

    def table(self, name):
        return _StallingQuery(self._by_table.get(name))

    def rpc(self, *a, **k):
        return _StallingQuery(None)


async def _run_with_ticker(coro):
    """Run coro beside a 10 ms ticker. Returns its result and the longest gap
    between ticks: a blocked loop shows up as one long gap."""
    loop = asyncio.get_running_loop()
    gaps = []
    done = False

    async def ticker():
        last = loop.time()
        while not done:
            await asyncio.sleep(0.01)
            now = loop.time()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)  # ticker takes its first timestamp before coro can block
    try:
        result = await coro
    finally:
        done = True
        await task
    return result, max(gaps, default=0.0)


@pytest.mark.asyncio
async def test_partner_send_keeps_the_loop_running_while_the_db_stalls():
    from app.services.intake import partner_send_template

    def slow_mode(db, tenant_id):
        time.sleep(STALL)
        return "template"

    with patch("app.services.partner_send_mode.get_partner_send_mode", side_effect=slow_mode):
        (status, _body), gap = await _run_with_ticker(partner_send_template(
            {"template_code": "T1", "phone": "919876543210"}, "tenant-a", db=_StallingDB({}),
        ))
    assert status == 404  # no such template: two stalled queries, then out
    assert gap < STALL / 2


@pytest.mark.asyncio
async def test_status_webhook_keeps_the_loop_running_while_the_db_stalls():
    from app.routes import webhook

    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "pn-1"},
        "statuses": [{"id": "wamid.1", "status": "delivered"}],
    }}]}]}
    request = MagicMock(spec=Request)
    request.body = AsyncMock(return_value=json.dumps(payload).encode("utf-8"))
    request.headers = {"x-hub-signature-256": "sha256=doesnt-matter-here"}
    db = _StallingDB({"phone_numbers": {"tenant_id": "tenant-a"}, "messages": []})
    with patch("app.routes.webhook.get_supabase", return_value=db), \
         patch("app.routes.webhook.verify_meta_signature", return_value=True):
        result, gap = await _run_with_ticker(
            webhook.whatsapp_webhook(request, MagicMock(spec=BackgroundTasks)),
        )
    assert result == {"status": "ok"}
    assert gap < STALL / 2


@pytest.mark.asyncio
async def test_loop_lag_watchdog_logs_a_blocked_loop(monkeypatch, caplog):
    import app.main as main

    monkeypatch.setattr(main, "_LOOP_LAG_INTERVAL", 0.05)
    monkeypatch.setattr(main, "_LOOP_LAG_WARN", 0.2)
    task = asyncio.create_task(main._watch_event_loop_lag())
    await asyncio.sleep(0.01)
    with caplog.at_level(logging.WARNING, logger=main.logger.name):
        time.sleep(0.4)  # a sync call hogging the loop
        await asyncio.sleep(0.1)
    task.cancel()
    assert "Event loop blocked" in caplog.text
