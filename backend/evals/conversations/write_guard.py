"""Proof that an eval run writes nothing to the database.

engine_sim replaces the session, deal, link and handover functions. This is the second
lock for everything it does not replace: the provider clients' token counter is switched
off, and the Supabase transport refuses every request that is not a read (a POST to a
read-only search RPC is let through). Each refused request is recorded in `blocked`, so
a run can print "0 database writes attempted" as measured evidence, not a promise.
"""
import importlib
from contextlib import ExitStack
from unittest.mock import patch

import httpx

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
READ_ONLY_RPC_PREFIXES = ("match_", "keyword_match_", "search_")
TOKEN_METER_MODULES = (
    "app.services.token_meter", "app.services.gemini_client",
)

blocked: list[str] = []


def is_read(request: httpx.Request) -> bool:
    if request.method in READ_METHODS:
        return True
    path = request.url.path
    if request.method == "POST" and "/rpc/" in path:
        return path.rsplit("/rpc/", 1)[1].startswith(READ_ONLY_RPC_PREFIXES)
    return False


def refuse(request: httpx.Request) -> httpx.Response:
    blocked.append(f"{request.method} {request.url.path}")
    return httpx.Response(200, json=[], request=request)


def install(stack: ExitStack) -> None:
    from app.db import supabase as supabase_module

    real_handle = supabase_module._RetryTransport.handle_request

    def guarded(self, request):
        return real_handle(self, request) if is_read(request) else refuse(request)

    stack.enter_context(patch.object(supabase_module._RetryTransport, "handle_request", guarded))
    for name in TOKEN_METER_MODULES:
        module = importlib.import_module(name)
        if hasattr(module, "record_tokens"):
            stack.enter_context(patch.object(module, "record_tokens", lambda *a, **k: None))
