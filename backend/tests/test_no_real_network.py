"""Tests never leave the machine (conftest._no_real_network): a call nobody faked is refused at
once, with no retry wait. Before this, 301 tests read app_settings through the real client; on
CI each read retried against an address that does not exist and the run took 4.5 hours."""
import asyncio
import logging
import time

import httpx
import pytest

from app import config_dynamic
from app.db.supabase import get_supabase

REFUSED = "tests never reach the network"


def test_an_unfaked_settings_read_is_refused_at_once_and_gives_the_fallback(caplog):
    get_supabase()                           # build the client first: the clock times the reads only
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        value = config_dynamic.get_setting("a_key_nobody_set", fallback="the-default", tenant_id="no-such-tenant")
    assert value == "the-default"
    assert REFUSED in caplog.text            # it was our refusal, not a real database answering
    assert time.monotonic() - started < 1.0  # 2 reads x 3 attempts, none of them waited


def test_a_plain_http_call_is_refused():
    with pytest.raises(httpx.ConnectError, match=REFUSED):
        httpx.get("https://example.invalid/")


def test_an_async_http_call_is_refused():
    async def go():
        async with httpx.AsyncClient() as client:
            await client.get("https://example.invalid/")

    with pytest.raises(httpx.ConnectError, match=REFUSED):
        asyncio.run(go())
