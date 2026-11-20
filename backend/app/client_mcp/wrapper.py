"""The one door every client-connector tool goes through.

`@client_tool` registers a plain function as a tool. When the owner's Claude calls it, the wrapper:
  1. reads who is calling and for which client (auth.current_seat). The client comes from the
     sign-in only: a tool reads it with `tenant_id()` and never takes it as an argument,
  2. READ tools run with the database in read-only mode (app.db.supabase.read_only),
  3. EDIT and SEND tools write an audit row BEFORE they act (no row = nothing is done),
  4. every call writes an audit row when it ends (a READ whose row fails is withheld),
  5. returns {"source": <the Anril page the answer matches>, "data": ...}.
A function that is not on APPROVED_TOOLS cannot be registered, and its kind and permission are
fixed there, not at the call site.

Tool functions must not use `from __future__ import annotations`: the tool schema is built
from their real type hints.
"""
import asyncio
import contextvars
import functools
import inspect
import json
import logging
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

import anyio
from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp.wrapper import _call
from app.client_mcp import auth
from app.db import supabase as supabase_db
from app.db.supabase import ReadOnlyViolation, get_supabase
from app.services import client_claude
from app.services.audit_log import write_audit_event

logger = logging.getLogger(__name__)

READ, EDIT, SEND = "read", "edit", "send"
ACTIONS = {READ: "claude.read", EDIT: "claude.edit", SEND: "claude.send"}

# Tool name -> (kind, the permission the same action needs in the app, the page it matches).
# The approved list: nothing else can be registered. Version 1 lets only the owner connect, and
# an owner holds every permission; the keys are recorded so staff access can be switched on later.
APPROVED_TOOLS: dict[str, tuple[str, str, str]] = {
    # ask
    "my_business": (READ, "dashboard.view", "Anril → Settings (account, plan, Anril AI)"),
    "dashboard_summary": (READ, "analytics.view", "Anril → Dashboard"),
    "leads_overview": (READ, "leads.view", "Anril → Leads (totals by segment, newest leads)"),
    "find_leads": (READ, "leads.view", "Anril → Leads"),
    "lead_details": (READ, "leads.view", "Anril → Leads → one lead"),
    "conversations": (READ, "conversations.view", "Anril → Chats"),
    "messaging_stats": (READ, "analytics.view", "Anril → Analytics → Messaging"),
    "calling_stats": (READ, "analytics.view", "Anril → Analytics → Telecalling"),
    "broadcasts": (READ, "outbound_leads.view", "Anril → Broadcasts"),
    "templates": (READ, "templates.view", "Anril → Templates"),
    "team": (READ, "team.view", "Anril → Team"),
    "plan_and_usage": (READ, "subscription.view", "Anril → Subscription"),
    # edit records (stays inside Anril, can be undone)
    "assign_lead": (EDIT, "leads.manage", "Anril → Leads → one lead"),
    "add_lead_note": (EDIT, "leads.manage", "Anril → Leads → one lead → notes"),
    # send to customers (leaves Anril)
    "reply_options": (READ, "conversations.reply", "Anril → Chats → Send template"),
    "send_reply": (SEND, "conversations.reply", "Anril → Chats"),
    "preview_broadcast": (READ, "outbound_leads.manage", "Anril → Broadcasts"),
    "send_broadcast": (SEND, "outbound_leads.manage", "Anril → Broadcasts"),
}

MAX_RESULT_CHARS = 140_000  # Claude's cap is about 150,000 per tool result
MAX_PARALLEL_TOOLS = 6      # across all clients; the rest wait their turn
TOOL_TIMEOUT_SECONDS = 90   # Claude gives up at 240
CALLS_PER_MINUTE = 60       # per client
MAX_AUDIT_TEXT = 200
MAX_AUDIT_LIST = 10

_seat: contextvars.ContextVar[dict | None] = contextvars.ContextVar("client_mcp_seat", default=None)
_slots_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
_calls: dict[str, tuple[int, int]] = {}  # client id -> (minute, calls in it)


def seat() -> dict:
    """Who the running tool acts for: user_id, email, tenant_id, tenant_name, client_id."""
    current = _seat.get()
    if current is None:
        raise ToolError("Not signed in.")
    return current


def tenant_id() -> str:
    """The ONLY way a tool learns its client."""
    return seat()["tenant_id"]


@contextmanager
def acting_as(tenant_id: str, user_id: str = "owner-1", **more):
    """Tests: run a tool's plain function as this client's owner."""
    token = _seat.set({
        "tenant_id": tenant_id, "user_id": user_id, "email": "", "client_id": "test-app",
        "connection_id": None, "tenant_name": "", **more,
    })
    try:
        yield
    finally:
        _seat.reset(token)


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _slots_by_loop:
        _slots_by_loop[loop] = asyncio.Semaphore(MAX_PARALLEL_TOOLS)
    return _slots_by_loop[loop]


def _over_rate(client: str) -> bool:
    minute = int(time.monotonic() // 60)
    seen_minute, count = _calls.get(client, (minute, 0))
    if seen_minute != minute:
        count = 0
    if len(_calls) > 5000:  # forget old minutes
        for key in [k for k, v in _calls.items() if v[0] != minute]:
            del _calls[key]
    _calls[client] = (minute, count + 1)
    return count + 1 > CALLS_PER_MINUTE


def _audit_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        if key == "search" and len(digits) >= 7:
            return f"phone ending {digits[-4:]}"
        return value if len(value) <= MAX_AUDIT_TEXT else value[:MAX_AUDIT_TEXT] + "…"
    if isinstance(value, (list, tuple)):
        kept = [_audit_value("", item) for item in value[:MAX_AUDIT_LIST]]
        return kept if len(value) <= MAX_AUDIT_LIST else kept + [f"… {len(value) - MAX_AUDIT_LIST} more"]
    return value


def _audit_arguments(arguments: dict) -> dict:
    """What the audit row keeps of a call's arguments: long text is cut, long lists are cut,
    and a phone number typed into a search is kept as its last 4 digits only."""
    return {key: _audit_value(key, value) for key, value in arguments.items()}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    kind: str
    permission: str
    source: str
    fn: Callable[..., Any]   # the plain function (tests call this inside acting_as)
    run: Callable[..., Any]  # the wrapped coroutine (the server registers this)


REGISTRY: dict[str, ToolSpec] = {}


def _audit(who: dict, name: str, kind: str, arguments: dict, stage: str, ok: bool | None) -> None:
    db = get_supabase()
    write_audit_event(
        db,
        tenant_id=who["tenant_id"],
        actor_user_id=who["user_id"],
        actor_role="owner",
        action=ACTIONS[kind],
        target_type="claude_tool",
        target_id=name,
        metadata={
            "connection_id": who.get("connection_id"), "app": who.get("client_id"),
            "arguments": arguments, "stage": stage, "ok": ok,
        },
    )
    if stage != "started" and who.get("connection_id"):
        try:
            client_claude.touch(db, who["connection_id"])
        except Exception as exc:
            logger.warning("client mcp last-used stamp failed: %s", exc)


def client_tool(*, title: str):
    """Register a tool. The function's docstring is what Claude reads."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        name = fn.__name__
        if name not in APPROVED_TOOLS:
            raise RuntimeError(f"{name} is not on APPROVED_TOOLS")
        if name in REGISTRY:
            raise RuntimeError(f"{name} is registered twice")
        if inspect.iscoroutinefunction(fn):
            raise RuntimeError(f"{name} must be a plain function (it runs in a worker thread)")
        kind, permission, source = APPROVED_TOOLS[name]
        changes = kind != READ

        @functools.wraps(fn)
        async def run(**kwargs):
            who = auth.current_seat()
            if _over_rate(who["tenant_id"]):
                raise ToolError("Too many requests this minute. Wait a moment and try again.")
            arguments = _audit_arguments(kwargs)
            if changes:
                # No row, no action: the record of what was asked exists before anything changes.
                try:
                    await anyio.to_thread.run_sync(_audit, who, name, kind, arguments, "started", None)
                except Exception as exc:
                    logger.error("client mcp audit row not written before %s: %s", name, exc)
                    raise ToolError("The audit log could not be written, so nothing was done. Try again.") from exc
            seat_token = _seat.set(who)
            guard_token = supabase_db.read_only.set(not changes)
            ok = False
            audited = False
            try:
                with anyio.fail_after(TOOL_TIMEOUT_SECONDS):
                    async with _slots():
                        data = await _call(fn, kwargs)
                ok = True
            except ToolError:
                raise
            except TimeoutError as exc:
                if changes:
                    raise ToolError(
                        "This took too long and Anril stopped waiting. It may still have gone "
                        "through: check in Anril before trying again."
                    ) from exc
                raise ToolError("This took too long and was stopped. Try again, or ask for less.") from exc
            except HTTPException as exc:
                if exc.status_code >= 500:  # the app's own refusals are 4xx; anything else stays inside
                    logger.error("Client MCP tool %s failed: %s", name, exc.detail)
                    raise ToolError("Something went wrong inside Anril. Check in Anril before trying again.") from exc
                raise ToolError(str(exc.detail)) from exc
            except ReadOnlyViolation as exc:
                logger.error("Client MCP tool %s tried to write: %s", name, exc)
                raise ToolError("This tool tried to change data and was stopped. Nothing was changed.") from exc
            except Exception as exc:
                # Never hand a raw database or provider error to the model.
                logger.exception("Client MCP tool %s failed", name)
                if changes:
                    raise ToolError(
                        "Something went wrong inside Anril. It may or may not have gone through: "
                        "check in Anril before trying again."
                    ) from exc
                raise ToolError("Something went wrong inside Anril. Try again.") from exc
            finally:
                supabase_db.read_only.reset(guard_token)
                _seat.reset(seat_token)
                # Shielded: if Claude hangs up mid-call, the row is still written.
                with anyio.CancelScope(shield=True):
                    try:
                        await anyio.to_thread.run_sync(
                            _audit, who, name, kind, arguments, "done" if ok else "failed", ok,
                        )
                        audited = True
                    except Exception as exc:
                        logger.error("client mcp audit row not written for %s: %s", name, exc)
            if not changes and not audited:
                # No row, no answer: a read must never go out without its audit row.
                raise ToolError("The audit log could not be written, so the answer was withheld. Try again.")
            result = {"source": source, "data": data}
            if not changes and len(json.dumps(result, default=str)) > MAX_RESULT_CHARS:
                raise ToolError("The answer is too long. Ask for fewer rows (a smaller limit or a later page).")
            return result

        REGISTRY[name] = ToolSpec(
            name=name, title=title, description=(inspect.getdoc(fn) or title),
            kind=kind, permission=permission, source=source, fn=fn, run=run,
        )
        return fn

    return decorate
