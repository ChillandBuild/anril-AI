import contextvars
import logging
import time

import httpx
from supabase import create_client, Client
from app.config import settings

logger = logging.getLogger(__name__)

_client: Client | None = None

# PostgREST's session is HTTP/2 (postgrest sets http2=True), so every query in
# the process shares one connection to Supabase's edge. When that edge recycles
# the connection, whichever request is holding it dies with
# `RemoteProtocolError: Server disconnected`. postgrest's own send_with_retry
# only covers HTTP 520/503 and httpx `NetworkError` — `RemoteProtocolError` is a
# `ProtocolError`, so it escapes and surfaces as a 500 (seen on
# GET /api/v1/subscriptions/me, 2026-08-28). Retrying here fixes every call site
# at once, since nothing in the app talks to postgrest directly.
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.25
_TRANSIENT = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError)
# Only replay what is safe to replay. A dropped POST/PATCH/DELETE may already
# have been applied server-side, so those keep raising.
_REPLAYABLE = frozenset({"GET", "HEAD", "OPTIONS"})
# postgrest's default is 120 s. Every app query finishes in under 8 s on the
# database (pg_stat_statements, 2026-10-30), but a stalled connection held calls
# for 35-45 s on 24 and 26 Oct and AstroTamil's partner sends timed out. A read
# timeout also marks the HTTP/2 connection broken, so the next query opens a
# fresh one instead of queueing on the dead one.
_TIMEOUT = httpx.Timeout(10.0)
# Queries slower than this are logged with the table and the route that ran them.
_SLOW_SECONDS = 2.0
# The request being served, for that log. Set by middleware in main.py;
# asyncio.to_thread copies it into the worker thread. Scheduler jobs keep the default.
current_route: contextvars.ContextVar[str] = contextvars.ContextVar("current_route", default="background")


class _RetryTransport(httpx.BaseTransport):
    """Replays idempotent PostgREST requests when the pooled connection dies,
    and logs slow ones."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        started = time.monotonic()
        try:
            return self._send_with_retry(request)
        finally:
            elapsed = time.monotonic() - started
            if elapsed >= _SLOW_SECONDS:
                logger.warning(
                    "Slow Supabase %s %s: %.1fs (route %s)",
                    request.method,
                    request.url.path,
                    elapsed,
                    current_route.get(),
                )

    def _send_with_retry(self, request: httpx.Request) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._inner.handle_request(request)
            except _TRANSIENT as exc:
                if request.method not in _REPLAYABLE:
                    raise
                last_exc = exc
                if attempt + 1 < _MAX_ATTEMPTS:
                    logger.warning(
                        "Supabase %s %s dropped (%s) — retrying %d/%d",
                        request.method,
                        request.url.path,
                        type(exc).__name__,
                        attempt + 1,
                        _MAX_ATTEMPTS - 1,
                    )
                    time.sleep(_BACKOFF_SECONDS * (2 ** attempt))
        raise last_exc  # type: ignore[misc]

    def close(self) -> None:
        self._inner.close()


def _wrap_postgrest_session(client: Client) -> None:
    """Swap PostgREST's session for one whose transport retries dropped reads.

    Rebuilds the session rather than passing ClientOptions(httpx_client=...):
    that option hands the *same* httpx client to postgrest, storage and
    functions, and each one assigns its own `base_url` onto it — last writer
    wins, and the other two then talk to the wrong host.
    """
    limits = httpx.Limits(max_keepalive_connections=30, max_connections=100, keepalive_expiry=60.0)
    old = client.postgrest.session
    client.postgrest.session = httpx.Client(
        base_url=old.base_url,
        headers=old.headers,
        timeout=_TIMEOUT,
        follow_redirects=True,
        transport=_RetryTransport(httpx.HTTPTransport(http2=True, limits=limits)),
    )
    old.close()


# Claude Access (the read-only admin MCP) sets this while one of its tools runs. Until it is
# reset, get_supabase() hands out a client that refuses every table write and every RPC not
# listed below, so a tool cannot change data even by calling code that would.
read_only: contextvars.ContextVar[bool] = contextvars.ContextVar("read_only", default=False)
_WRITE_METHODS = frozenset({"insert", "upsert", "update", "delete"})
# RPCs that only read. Anything else is refused in read-only mode.
READ_ONLY_RPCS = frozenset({"distinct_token_usage_pairs"})


class ReadOnlyViolation(RuntimeError):
    """A write was attempted while the read-only guard was on."""


class _ReadOnlyTable:
    def __init__(self, inner, name: str) -> None:
        self._inner = inner
        self._name = name

    def __getattr__(self, attr: str):
        if attr in _WRITE_METHODS:
            raise ReadOnlyViolation(f"read-only mode: {attr} on {self._name} refused")
        return getattr(self._inner, attr)


class _ReadOnlyAuthAdmin:
    """Of the user-admin API, only the lookups. Creating, changing or deleting a user is refused."""
    _READS = frozenset({"get_user_by_id", "list_users"})

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, attr: str):
        if attr not in self._READS:
            raise ReadOnlyViolation(f"read-only mode: auth.admin.{attr} refused")
        return getattr(self._inner, attr)


class _ReadOnlyAuth:
    def __init__(self, inner) -> None:
        self._inner = inner

    @property
    def admin(self):
        return _ReadOnlyAuthAdmin(self._inner.admin)

    def __getattr__(self, attr: str):
        raise ReadOnlyViolation(f"read-only mode: auth.{attr} refused")


class _ReadOnlyClient:
    """Deny by default. Only table reads, the listed RPCs and user lookups get through; every
    other door on the real client (postgrest, schema, storage, functions, ...) is refused."""

    def __init__(self, inner: Client) -> None:
        self._inner = inner

    def table(self, name: str):
        return _ReadOnlyTable(self._inner.table(name), name)

    from_ = table

    def rpc(self, fn: str, *args, **kwargs):
        if fn not in READ_ONLY_RPCS:
            raise ReadOnlyViolation(f"read-only mode: rpc {fn} refused")
        return self._inner.rpc(fn, *args, **kwargs)

    @property
    def auth(self):
        return _ReadOnlyAuth(self._inner.auth)

    def __getattr__(self, attr: str):
        raise ReadOnlyViolation(f"read-only mode: client.{attr} refused")


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
        _wrap_postgrest_session(_client)
    if read_only.get():
        return _ReadOnlyClient(_client)  # type: ignore[return-value]
    return _client
