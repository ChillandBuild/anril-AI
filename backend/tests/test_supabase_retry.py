import logging
from unittest.mock import MagicMock

import httpx
import pytest

from app.db.supabase import _RetryTransport, _wrap_postgrest_session, current_route


class _ScriptedTransport(httpx.BaseTransport):
    """Raises the queued exceptions in order, then answers 200."""

    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return httpx.Response(200, json={"ok": True}, request=request)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr("app.db.supabase._BACKOFF_SECONDS", 0)


def _request(inner, method="GET"):
    client = httpx.Client(transport=_RetryTransport(inner), base_url="https://example.test")
    return client.request(method, "/rest/v1/leads")


def _disconnected():
    return httpx.RemoteProtocolError("Server disconnected")


def test_dropped_read_is_retried_and_succeeds():
    inner = _ScriptedTransport([_disconnected()])
    assert _request(inner).status_code == 200
    assert inner.calls == 2


def test_read_gives_up_after_max_attempts():
    inner = _ScriptedTransport([_disconnected(), _disconnected(), _disconnected()])
    with pytest.raises(httpx.RemoteProtocolError):
        _request(inner)
    assert inner.calls == 3


def test_write_is_never_replayed():
    inner = _ScriptedTransport([_disconnected()])
    with pytest.raises(httpx.RemoteProtocolError):
        _request(inner, method="POST")
    assert inner.calls == 1


def test_session_gives_up_after_10s_not_the_120s_default():
    client = MagicMock()
    client.postgrest.session = httpx.Client(base_url="https://example.test", timeout=120)
    _wrap_postgrest_session(client)
    assert client.postgrest.session.timeout.read == 10


def test_slow_query_is_logged_with_table_and_route(monkeypatch, caplog):
    monkeypatch.setattr("app.db.supabase._SLOW_SECONDS", 0)
    token = current_route.set("POST /api/v1/intake/partner/send-template")
    try:
        with caplog.at_level(logging.WARNING, logger="app.db.supabase"):
            _request(_ScriptedTransport([]))
    finally:
        current_route.reset(token)
    assert "Slow Supabase GET /rest/v1/leads" in caplog.text
    assert "POST /api/v1/intake/partner/send-template" in caplog.text


def test_fast_query_is_not_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="app.db.supabase"):
        _request(_ScriptedTransport([]))
    assert "Slow Supabase" not in caplog.text
