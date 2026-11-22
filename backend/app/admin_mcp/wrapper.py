"""The one door every admin MCP tool goes through.

`@admin_tool` registers a plain function as a tool. When Claude calls it, the wrapper:
  1. reads who is calling (auth.current_caller),
  2. runs the function with the database in read-only mode (app.db.supabase.read_only),
  3. writes one audit row and stamps the connection's last-used time (no row = no answer),
  4. returns {"source": <the Operator Console page the figures come from>, "data": ...}.
A function that is not on APPROVED_TOOLS cannot be registered.

Tool functions must not use `from __future__ import annotations`: the tool schema is built
from their real type hints.
"""
import asyncio
import contextvars
import functools
import inspect
import json
import logging
import uuid
import weakref
from dataclasses import dataclass
from typing import Any, Callable

import anyio
from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp.auth import current_caller
from app.db import supabase as supabase_db
from app.db.supabase import ReadOnlyViolation, get_supabase
from app.services import mcp_connections
from app.services.audit_log import write_audit_event

logger = logging.getLogger(__name__)

# Tool name -> where its figures come from. The approved list: nothing else can be registered.
APPROVED_TOOLS: dict[str, str] = {
    # all clients
    "fleet_summary": "Operator Console → Clients (overview, daily messages, broadcasts, alerts)",
    "list_clients": "Operator Console → Clients",
    "fleet_alerts": "Operator Console → alert bell",
    "scheduler_health": "Operator Console → Schedulers",
    "system_health": "Operator Console → Schedulers (system health)",
    "fleet_ai_spend": "Operator Console → AI Spend",
    "open_requests": "Operator Console → Requests (subscription and SMS credit)",
    "audit_log": "Operator Console → Audit Log",
    # one client
    "client_overview": "Operator Console → client → Product Overview",
    "client_health": "Operator Console → client → Health",
    "client_usage": "Operator Console → client → Entitlements & Usage, Token Consumption",
    "client_messages": "Operator Console → client → Analytics",
    "client_leads": "Operator Console → client → Inbound / Outbound Leads",
    "client_conversations": "Operator Console → client → Conversations",
    "client_telecalling": "Operator Console → client → Telecalling",
    "client_config": "Operator Console → client → Configuration",
    "client_broadcasts": "New Operator read: broadcast history",
    "find_lead": "New Operator read: lead search",
    "lead_thread": "New Operator read: full chat thread",
    "what_anril_saw": "Operator Console → client → Anril Brain (what Anril saw)",
    # gaps: one client
    "client_team": "Operator Console → client → Team",
    "client_templates": "Operator Console → client → Templates",
    "client_numbers": "Operator Console → client → Numbers Pool",
    "client_knowledge": "Operator Console → client → Knowledge Base",
    "client_calling_provider": "Operator Console → client → Configuration → calling provider",
    "client_private_send": "Operator Console → client → Private Send",
    "client_audit_logs": "Operator Console → client → Audit Logs",
    # gaps: the platform
    "subscription_plans": "Operator Console → Subscription (feature catalog and plans)",
    "master_prompt": "Operator Console → Master Prompt (read only)",
    "provider_rates": "Operator Console → AI Spend → provider rates",
    "clients_waiting": "Operator Console → Clients (waiting on client)",
}

MAX_RESULT_CHARS = 140_000  # Claude's cap is about 150,000 per tool result
ACTION = "mcp.tool_call"
MAX_PARALLEL_TOOLS = 3       # tool calls running at once; the rest wait their turn
TOOL_TIMEOUT_SECONDS = 90    # Claude gives up at 240
MAX_AUDIT_ARG_CHARS = 200

# The client a tool call was about, for the audit row. The wrapper puts a small box here before
# the call and resolve_client writes into it. A box (not a plain value) because most tools run in
# a worker thread, and a value SET in a worker thread is lost when the thread returns; a change
# made INSIDE the shared box is not.
_audit_holder: contextvars.ContextVar[dict | None] = contextvars.ContextVar("mcp_audit_holder", default=None)
_slots_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def note_client(tenant_id: str) -> None:
    """Record which client this tool call is about (for the audit row)."""
    holder = _audit_holder.get()
    if holder is not None:
        holder["tenant_id"] = tenant_id


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _slots_by_loop:
        _slots_by_loop[loop] = asyncio.Semaphore(MAX_PARALLEL_TOOLS)
    return _slots_by_loop[loop]


def _audit_arguments(arguments: dict) -> dict:
    """What the audit row keeps of a call's arguments: long text is cut, and a phone number
    typed into a lead search is kept as its last 4 digits only."""
    kept: dict = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if key == "query" and len(digits) >= 7:
                value = f"phone ending {digits[-4:]}"
            elif len(value) > MAX_AUDIT_ARG_CHARS:
                value = value[:MAX_AUDIT_ARG_CHARS] + "…"
        kept[key] = value
    return kept


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    source: str
    fn: Callable[..., Any]   # the plain function (tests call this)
    run: Callable[..., Any]  # the wrapped coroutine (the server registers this)


REGISTRY: dict[str, ToolSpec] = {}


def resolve_client(client: str) -> dict:
    """A client given by name ("AstroTamil") or id -> {"id", "name"}. Unknown -> a clear error."""
    db = get_supabase()
    wanted = (client or "").strip()
    if not wanted:
        raise ToolError("Say which client: its name or id.")
    rows = (db.table("tenants").select("id, name").execute().data) or []
    match = None
    try:
        as_id = str(uuid.UUID(wanted))
        match = next((r for r in rows if str(r["id"]) == as_id), None)
    except ValueError:
        low = wanted.lower()
        exact = [r for r in rows if (r.get("name") or "").lower() == low]
        partial = [r for r in rows if low in (r.get("name") or "").lower()]
        if len(exact) == 1:
            match = exact[0]
        elif not exact and len(partial) == 1:
            match = partial[0]
        elif len(exact) > 1 or len(partial) > 1:
            names = ", ".join(sorted(f'{r["name"]} ({r["id"]})' for r in (exact or partial)))
            raise ToolError(f'More than one client matches "{wanted}": {names}. Use the id.')
    if not match:
        names = ", ".join(sorted((r.get("name") or "") for r in rows))
        raise ToolError(f'No client called "{wanted}". Clients: {names}')
    note_client(str(match["id"]))
    return {"id": str(match["id"]), "name": match.get("name") or ""}


async def _call(fn: Callable[..., Any], kwargs: dict) -> Any:
    """Plain functions (the normal case) run in a worker thread, so their database reads never
    hold up the web server. An async tool must not block: it awaits or uses a thread itself."""
    if inspect.iscoroutinefunction(fn):
        return await fn(**kwargs)
    # abandon_on_cancel: a timed-out call returns at once instead of waiting for the thread.
    return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs), abandon_on_cancel=True)


def _after_call(caller: dict, name: str, tenant_id: str | None, arguments: dict, ok: bool) -> None:
    db = get_supabase()
    write_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=caller["user_id"],
        actor_role="system_admin",
        action=ACTION,
        target_type="mcp_tool",
        target_id=name,
        metadata={"connection_id": caller.get("connection_id"), "arguments": arguments, "ok": ok},
    )
    if caller.get("connection_id"):
        try:
            mcp_connections.touch(db, caller["connection_id"])
        except Exception as exc:
            logger.warning("mcp last-used stamp failed: %s", exc)


def admin_tool(*, title: str):
    """Register a read-only tool. The function's docstring is what Claude reads."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        name = fn.__name__
        if name not in APPROVED_TOOLS:
            raise RuntimeError(f"{name} is not on APPROVED_TOOLS")
        if name in REGISTRY:
            raise RuntimeError(f"{name} is registered twice")
        source = APPROVED_TOOLS[name]

        @functools.wraps(fn)
        async def run(**kwargs):
            caller = current_caller()
            holder: dict = {"tenant_id": None}
            holder_token = _audit_holder.set(holder)
            guard_token = supabase_db.read_only.set(True)
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
                raise ToolError("This took too long and was stopped. Try again, or ask for less.") from exc
            except HTTPException as exc:
                raise ToolError(str(exc.detail)) from exc
            except ReadOnlyViolation as exc:
                logger.error("MCP tool %s tried to write: %s", name, exc)
                raise ToolError("This tool tried to change data and was stopped. Nothing was changed.") from exc
            finally:
                supabase_db.read_only.reset(guard_token)
                _audit_holder.reset(holder_token)
                # Shielded: if Claude hangs up mid-call, the row is still written.
                with anyio.CancelScope(shield=True):
                    try:
                        await anyio.to_thread.run_sync(
                            _after_call, caller, name, holder["tenant_id"], _audit_arguments(kwargs), ok,
                        )
                        audited = True
                    except Exception as exc:
                        logger.error("mcp audit row not written for %s: %s", name, exc)
            if not audited:
                # No row, no answer: a read must never go out without its audit row.
                raise ToolError("The audit log could not be written, so the answer was withheld. Try again.")
            result = {"source": source, "data": data}
            if len(json.dumps(result, default=str)) > MAX_RESULT_CHARS:
                raise ToolError("The answer is too long. Ask for fewer rows (a smaller limit or a later page).")
            return result

        REGISTRY[name] = ToolSpec(
            name=name, title=title, description=(inspect.getdoc(fn) or title), source=source, fn=fn, run=run,
        )
        return fn

    return decorate
