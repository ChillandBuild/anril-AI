import contextvars
import logging
import time

import httpx
from supabase import create_client, Client
from app.config import settings

logger = logging.getLogger(__name__)

_client: Client | None = None

# Every Supabase client here is used by many threads at once (route handlers, webhooks,
# scheduler jobs). supabase-py turns HTTP/2 on for all of them, which puts every request on ONE
# connection, and httpcore's sync HTTP/2 connection is not thread-safe: it takes the next stream
# id and packs the headers without a lock. Two threads then send the same stream id or scramble
# the header compression, Supabase's edge answers GOAWAY PROTOCOL_ERROR or just hangs up, and
# every request on that connection dies with `RemoteProtocolError: Server disconnected`
# (about 20 cuts an hour on 2026-11-27; with 8 threads, 61 failures in 5,600 requests on
# HTTP/2 against 0 in 3,200 on an HTTP/1.1 pool). So these clients speak HTTP/1.1: each
# request in flight gets its own pooled connection.
#
# A pooled connection can still close just as it is reused. postgrest's own send_with_retry
# only covers HTTP 520/503 and httpx `NetworkError`; `RemoteProtocolError` is a
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
# timeout closes that one connection; the next query takes another from the pool.
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
        transport=_RetryTransport(httpx.HTTPTransport(http2=False, limits=limits)),
    )
    old.close()


def _use_http1(session: httpx.Client) -> None:
    """Swap a client's HTTP/2 transport for an HTTP/1.1 pool, keeping the client object:
    auth and auth.admin share one, and storage hands its own to every bucket."""
    old = session._transport
    session._transport = httpx.HTTPTransport(http2=False)
    old.close()


# Claude Access (the read-only admin MCP) sets this while one of its tools runs. Until it is
# reset, get_supabase() hands out a client that refuses every table write and every RPC not
# listed below, so a tool cannot change data even by calling code that would.
read_only: contextvars.ContextVar[bool] = contextvars.ContextVar("read_only", default=False)
_WRITE_METHODS = frozenset({"insert", "upsert", "update", "delete"})
# RPCs that only read. Anything else is refused in read-only mode. Each name below was checked
# against its function body in pg_proc (2026-11-23): a SELECT and nothing else, and every one
# filters by its p_tenant_id argument. The Reports tools pass the signed-in client's id.
READ_ONLY_RPCS = frozenset({
    "distinct_token_usage_pairs",
    "analytics_daily_leads",
    "analytics_daily_messages",
    "analytics_daily_returning_ad_leads",
    "analytics_lead_arrival_heatmap",
    "analytics_period_money",
    "analytics_period_summary",
    "analytics_reply_sources",
    "analytics_response_times",
    "analytics_segment_movement",
    "get_telecalling_all_time_stats",
    "template_performance_range",
})


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
        # Built in a local and published last: another thread must never pick up a client whose
        # sessions are still being swapped (the old ones get closed under it).
        client = create_client(settings.supabase_url, settings.supabase_service_key)
        _wrap_postgrest_session(client)
        try:
            _use_http1(client.auth._http_client)
            _use_http1(client.storage.session)
        except Exception:
            # These reach into supabase-py and httpx internals. If a new version moves them, keep
            # serving (on HTTP/2, as before) and let test_supabase_retry.py fail in CI.
            logger.exception("Supabase auth/storage clients left on HTTP/2: could not switch them to HTTP/1.1")
        _client = client
    if read_only.get():
        return _ReadOnlyClient(_client)  # type: ignore[return-value]
    return _client
