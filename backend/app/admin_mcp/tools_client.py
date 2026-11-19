"""Tools about one client. Each one calls the Operator Console's own read for that client.

The Operator reads are FastAPI handlers, so every parameter is passed by keyword: a parameter
left out would arrive as a Depends(...) / Query(...) default object instead of a value.
"""
import asyncio

from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp.wrapper import admin_tool, resolve_client
from app.db.supabase import get_supabase
from app.routes import operator, operator_brain
from app.services.entitlements import compute_period_key

_ADMIN = {"user_id": "mcp"}  # the Operator reads take the admin only as a gate; the MCP has its own

_DIRECTIONS = ("all", "inbound", "outbound")
_TELECALLING_SECTIONS = ("upload", "dialer", "scheduled", "notes")
_MAX_DAYS = 366


def _usage_counters(tenant_id: str) -> dict:
    """The same answer as operator.get_client_usage, without its side effect. That handler calls
    get_billing_period, which WRITES when a client's billing period has rolled over (it resets
    the counters), and a write is refused here. So the period is worked out with the pure
    compute_period_key. A period that has rolled over but not been reset yet has no counters,
    and the answer says so."""
    db = get_supabase()
    sub = (
        db.table("tenant_subscriptions").select("period_start, period_end")
        .eq("tenant_id", tenant_id).maybe_single().execute()
    )
    row = (sub.data if sub else None) or {}
    period = compute_period_key(row.get("period_start"), row.get("period_end"))
    counters = (
        db.table("tenant_usage_counters").select("metric, used, included, hard_cap")
        .eq("tenant_id", tenant_id).eq("period", period).execute()
    )
    result = {"data": counters.data or [], "period": period}
    if row.get("period_start") and period != row["period_start"]:
        result["note"] = (
            "A new billing period has started. Its counters are reset on the client's next use, "
            "so none are shown yet."
        )
    return result


def _check_days(days: int) -> None:
    if days < 1 or days > _MAX_DAYS:
        raise ToolError(f"days must be between 1 and {_MAX_DAYS}.")


def _date_range(from_date: str, to_date: str) -> tuple[str | None, str | None]:
    """Both dates (YYYY-MM-DD) or neither. Empty means 'not given'."""
    from_date, to_date = (from_date or "").strip(), (to_date or "").strip()
    if bool(from_date) != bool(to_date):
        raise ToolError("Give both from_date and to_date (YYYY-MM-DD), or neither.")
    return (from_date or None, to_date or None)


@admin_tool(title="Client overview")
def client_overview(client: str) -> dict:
    """The Product Overview for one client: status, plan, owner, lead and message totals, and recent activity."""
    tenant = resolve_client(client)
    return operator.client_overview(tenant_id=tenant["id"], _admin=_ADMIN)


@admin_tool(title="Client health")
def client_health(client: str) -> dict:
    """Health of one client: whether each channel (WhatsApp, Instagram, Facebook, Telegram) has received messages lately, and other warning signs."""
    tenant = resolve_client(client)
    return operator.client_health(tenant_id=tenant["id"], _admin=_ADMIN)


@admin_tool(title="Client usage and tokens")
def client_usage(client: str, days: int = 30, all_time: bool = False, from_date: str = "", to_date: str = "") -> dict:
    """What one client bought (entitlements), how much of each quota it has used this billing period, and its AI token consumption by feature and model. days is the token window (default 30); all_time=true ignores it; from_date and to_date (YYYY-MM-DD, both) pick an exact range."""
    tenant = resolve_client(client)
    _check_days(days)
    from_d, to_d = _date_range(from_date, to_date)
    return {
        "entitlements": operator.get_client_entitlements(tenant_id=tenant["id"], _admin=_ADMIN),
        "usage": _usage_counters(tenant["id"]),
        "token_usage": operator.get_client_token_usage(
            tenant_id=tenant["id"], range_days=days, all_time=all_time,
            from_date=from_d, to_date=to_d, _admin=_ADMIN,
        ),
    }


@admin_tool(title="Client messages")
def client_messages(client: str, days: int = 7, all_time: bool = False, from_date: str = "", to_date: str = "") -> dict:
    """Messages per day for one client (inbound, outbound, AI-written, human-written) plus its last-30-day analytics. days is the daily window (default 7); all_time=true ignores it; from_date and to_date (YYYY-MM-DD, both) pick an exact range."""
    tenant = resolve_client(client)
    _check_days(days)
    from_d, to_d = _date_range(from_date, to_date)
    return {
        "daily": operator.client_dashboard_daily_messages(
            tenant_id=tenant["id"], range_days=days, all_time=all_time,
            from_date=from_d, to_date=to_d, _admin=_ADMIN,
        ),
        "analytics": operator.client_dashboard_analytics(tenant_id=tenant["id"], _admin=_ADMIN),
    }


@admin_tool(title="Client leads")
def client_leads(client: str, direction: str = "all") -> dict:
    """Lead totals for one client, split by segment A to D, plus its 20 newest leads. direction is "all", "inbound" (people who wrote in) or "outbound" (uploaded lists)."""
    if direction not in _DIRECTIONS:
        raise ToolError('direction must be "all", "inbound" or "outbound".')
    tenant = resolve_client(client)
    return operator.client_dashboard_leads(tenant_id=tenant["id"], direction=direction, _admin=_ADMIN)


@admin_tool(title="Client conversations")
def client_conversations(client: str) -> dict:
    """The Conversations page for one client: how many chats are waiting for a human, and the latest conversations."""
    tenant = resolve_client(client)
    return operator.client_dashboard_inbox(tenant_id=tenant["id"], _admin=_ADMIN)


@admin_tool(title="Client telecalling")
def client_telecalling(client: str, section: str = "dialer") -> dict:
    """The Telecalling page for one client. section is "dialer" (today's calls and connect rate), "upload" (contact list uploads), "scheduled" (pending follow-ups) or "notes" (call notes)."""
    if section not in _TELECALLING_SECTIONS:
        raise ToolError('section must be "upload", "dialer", "scheduled" or "notes".')
    tenant = resolve_client(client)
    return operator.client_dashboard_telecalling(tenant_id=tenant["id"], section=section, _admin=_ADMIN)


@admin_tool(title="Client configuration")
def client_config(client: str) -> dict:
    """The Configuration page for one client: enabled features, business description, whether each integration's credentials are set or missing (never the credentials themselves), AI settings and quota counters."""
    tenant = resolve_client(client)
    return operator.client_config(tenant_id=tenant["id"], _admin=_ADMIN)


@admin_tool(title="What Anril saw")
def what_anril_saw(client: str, lead_id: str) -> dict:
    """What Anril would see for one lead right now: the profile, recent chat, and the instructions behind a reply. Use it to explain why Anril answered the way it did. Needs the lead id (from find_lead)."""
    tenant = resolve_client(client)
    # The Operator read is an async function whose database reads block. A plain tool runs in a
    # worker thread, so asyncio.run here keeps those reads off the web server's own loop.
    # retrieval=False always: retrieval=True makes a paid embedding call.
    return asyncio.run(operator_brain.what_aira_saw(
        tenant_id=tenant["id"], lead_id=lead_id, retrieval=False, _admin=_ADMIN,
    ))
