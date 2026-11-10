"""Outbound guard for dry_run mode — blocks external HTTP writes, logs them instead."""

import json
import logging
import re
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Safe hosts that are never blocked, even in dry_run
_SAFE_HOSTS = frozenset({
    "generativelanguage.googleapis.com",
    "api.jina.ai",
    "localhost",
    "127.0.0.1",
})

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Store original send methods for restoration
_ORIGINAL_ASYNC_CLIENT_SEND: Callable | None = None
_ORIGINAL_SYNC_CLIENT_SEND: Callable | None = None


def _is_safe_host(host: str) -> bool:
    """Check if a host is safe (always allowed)."""
    if host in _SAFE_HOSTS:
        return True
    # Only OUR Supabase project — not any *.supabase.co (another project's edge function
    # could fan out messages). Compare hostnames: request.url.host carries no port.
    try:
        return host == (urlparse(settings.supabase_url).hostname or "")
    except Exception:
        return False


def _extract_recipient(request: httpx.Request) -> str | None:
    """Extract recipient from request body (to, chat_id, or recipient.id)."""
    try:
        data = json.loads(request.content)
        if isinstance(data, dict):
            # Direct 'to' or 'chat_id' field
            if "to" in data:
                return str(data["to"])
            if "chat_id" in data:
                return str(data["chat_id"])
            # Nested 'recipient.id'
            if "recipient" in data and isinstance(data["recipient"], dict):
                if "id" in data["recipient"]:
                    return str(data["recipient"]["id"])
    except Exception:
        pass
    return None


def _digits_only(value: str) -> str:
    """Extract digits only from a string."""
    return re.sub(r"\D", "", value)


def _is_allowlisted_recipient(recipient: str | None) -> bool:
    """Check if recipient is in the allowlist (digits-only comparison)."""
    if not recipient or not settings.outbound_allow_to:
        return False

    recipient_digits = _digits_only(recipient)
    if not recipient_digits:
        return False
    allowed = {_digits_only(entry) for entry in settings.outbound_allow_to.split(",")}
    return recipient_digits in allowed - {""}


def _redact_url(url: str) -> str:
    """Redact secrets from URL (bot tokens, query strings)."""
    parsed = urlparse(url)
    # Redact bot<...> path segments
    path = parsed.path
    path = re.sub(r"/bot[^/]+/", "/bot***/", path)

    # Return scheme://host/path (no query string)
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _is_blocked(request: httpx.Request) -> bool:
    """Check if a request should be blocked in dry_run mode."""
    if settings.outbound_mode != "dry_run":
        return False

    if request.method not in _WRITE_METHODS:
        return False

    host = request.url.host or ""

    if _is_safe_host(host):
        return False

    recipient = _extract_recipient(request)
    if _is_allowlisted_recipient(recipient):
        return False

    return True


def _fake_response(request: httpx.Request) -> httpx.Response:
    """Create a fake response for a blocked request."""
    dry_run_id = f"wamid.DRYRUN-{uuid.uuid4().hex}"
    fake_body = {
        "dry_run": True,
        "messages": [{"id": dry_run_id}],
        "message_id": dry_run_id,
        "id": dry_run_id,
        "ok": True,
        "result": {"message_id": int(uuid.uuid4().int % 2147483647)},
        "success": True,
        "short_url": "https://example.invalid/dryrun",
        "status": "created",
        "code": 200,
        "msg": "DRY-RUN: blocked",
        "message": "DRY-RUN: blocked",
    }
    return httpx.Response(200, json=fake_body, request=request)


def _mask_recipient(recipient: str | None) -> str:
    """Phone numbers / chat ids are PII — keep only the last 4 characters in logs."""
    if not recipient:
        return "-"
    return f"***{recipient[-4:]}"


def _block(request: httpx.Request) -> httpx.Response:
    """Log a blocked request (secrets and PII redacted) and return the fake reply."""
    logger.warning(
        "DRY-RUN blocked %s %s to=%s",
        request.method,
        _redact_url(str(request.url)),
        _mask_recipient(_extract_recipient(request)),
    )
    return _fake_response(request)


def _wrap_async_send(original_send: Callable) -> Callable:
    """Wrap AsyncClient.send to intercept and block requests."""

    async def wrapped_send(
        self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any
    ) -> httpx.Response:
        if _is_blocked(request):
            return _block(request)
        return await original_send(self, request, **kwargs)

    return wrapped_send


def _wrap_sync_send(original_send: Callable) -> Callable:
    """Wrap Client.send to intercept and block requests."""

    def wrapped_send(
        self: httpx.Client, request: httpx.Request, **kwargs: Any
    ) -> httpx.Response:
        if _is_blocked(request):
            return _block(request)
        return original_send(self, request, **kwargs)

    return wrapped_send


def install_outbound_guard() -> None:
    """Install the outbound guard to block dry_run writes. Idempotent."""
    global _ORIGINAL_ASYNC_CLIENT_SEND, _ORIGINAL_SYNC_CLIENT_SEND

    if settings.outbound_mode != "dry_run":
        if not settings.scheduler_enabled:
            # Scheduler off usually means "laptop" — but outbound is still LIVE.
            logger.warning(
                "SCHEDULER_ENABLED=false but OUTBOUND_MODE=live: requests from this process "
                "WILL reach real people. Use scripts/dev-backend.sh for safe local mode."
            )
        return

    # Only install once
    if _ORIGINAL_ASYNC_CLIENT_SEND is not None:
        return

    _ORIGINAL_ASYNC_CLIENT_SEND = httpx.AsyncClient.send
    _ORIGINAL_SYNC_CLIENT_SEND = httpx.Client.send

    httpx.AsyncClient.send = _wrap_async_send(_ORIGINAL_ASYNC_CLIENT_SEND)
    httpx.Client.send = _wrap_sync_send(_ORIGINAL_SYNC_CLIENT_SEND)

    allow_list = settings.outbound_allow_to or "(none)"
    logger.warning(
        "OUTBOUND DRY-RUN active: writes to external hosts are logged, not sent (allow: %s)",
        allow_list,
    )


def uninstall_outbound_guard() -> None:
    """Uninstall the outbound guard. For testing only."""
    global _ORIGINAL_ASYNC_CLIENT_SEND, _ORIGINAL_SYNC_CLIENT_SEND

    if _ORIGINAL_ASYNC_CLIENT_SEND is not None:
        httpx.AsyncClient.send = _ORIGINAL_ASYNC_CLIENT_SEND
        _ORIGINAL_ASYNC_CLIENT_SEND = None

    if _ORIGINAL_SYNC_CLIENT_SEND is not None:
        httpx.Client.send = _ORIGINAL_SYNC_CLIENT_SEND
        _ORIGINAL_SYNC_CLIENT_SEND = None
