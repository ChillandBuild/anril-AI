"""The "ask" tools. Read-only: the wrapper runs each with the database locked against writes.

Most of them return what the matching Operator Console read returns for ONE client. Those reads
are already proven read-only on the live system by the admin connector; here the client is fixed
by the sign-in (wrapper.tenant_id) instead of being an argument.
"""
from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp.tools_client import _check_days, _date_range, _usage_counters
from app.client_mcp import leads as lead_lookup
from app.client_mcp.wrapper import client_tool, seat, tenant_id
from app.db.supabase import get_supabase
from app.routes import operator, operator_broadcasts, operator_leads
from app.services import client_claude

# The Operator reads take the caller only as a marker; nothing is looked up from it.
_AS = {"user_id": "client-mcp"}
MAX_PAGE = 50


@client_tool(title="Your account")
def my_business() -> dict:
    """Start here. Your business name, the features switched on, how many leads and messages
    you have, and how many customer messages Anril AI may still send today (the daily cap)."""
    db, tenant = get_supabase(), tenant_id()
    overview = operator.client_overview(tenant_id=tenant, _admin=_AS)
    cap, sent = client_claude.daily_cap(db, tenant), client_claude.sent_today(db, tenant)
    return {
        "business": overview.get("tenant"),
        "signed_in_as": {"email": seat().get("email"), "role": "owner"},
        "stats": overview.get("stats"),
        "sending_through_anril_ai": {
            "daily_cap": cap, "sent_today": sent, "left_today": max(cap - sent, 0),
            "note": "Counts every reply and broadcast message sent through this connector. "
                    "The day is Indian time. The owner can change the cap in Anril → Settings.",
        },
    }


@client_tool(title="Dashboard numbers")
def dashboard_summary() -> dict:
    """The last 30 days at a glance: messages, delivery rate, average lead score, and calls
    with connect rate when telecalling is on."""
    return operator.client_dashboard_analytics(tenant_id=tenant_id(), _admin=_AS)


@client_tool(title="Messages per day")
def messaging_stats(days: int = 7, all_time: bool = False, from_date: str = "", to_date: str = "") -> dict:
    """Messages per day: received, sent, sent by Anril's AI and sent by people. Give days
    (default 7, at most 366), or from_date and to_date as 2026-11-01, or all_time."""
    _check_days(days)
    start, end = _date_range(from_date, to_date)
    return operator.client_dashboard_daily_messages(
        tenant_id=tenant_id(), range_days=days, all_time=all_time, from_date=start, to_date=end, _admin=_AS,
    )


@client_tool(title="Leads at a glance")
def leads_overview(direction: str = "all") -> dict:
    """How many leads there are, split by segment A to D, and the 20 newest. direction is
    all, inbound or outbound."""
    if direction not in ("all", "inbound", "outbound"):
        raise ToolError("direction must be all, inbound or outbound.")
    return operator.client_dashboard_leads(tenant_id=tenant_id(), direction=direction, _admin=_AS)


@client_tool(title="Find leads")
def find_leads(search: str = "", segment: str = "", source: str = "", created_from: str = "",
               created_to: str = "", limit: int = 20, page: int = 1) -> dict:
    """Find leads by any mix of: search (part of a name, or 4+ digits of a phone number),
    segment (A, B, C or D), source (for example whatsapp, instagram, website_form), and the
    dates they were created (created_from / created_to as 2026-10-01, Indian time, both
    included). Newest first. Each row has the `id` the other tools need."""
    if not 1 <= limit <= MAX_PAGE:
        raise ToolError(f"limit must be between 1 and {MAX_PAGE}.")
    if page < 1:
        raise ToolError("page starts at 1.")
    start = (page - 1) * limit
    rows = (
        lead_lookup.filtered(
            get_supabase(), tenant_id(), search=search, segment=segment, source=source,
            created_from=created_from, created_to=created_to,
        ).order("created_at", desc=True).range(start, start + limit).execute()
    ).data or []
    return {
        "page": page, "leads": [lead_lookup.public(r) for r in rows[:limit]],
        "more": len(rows) > limit,
    }


@client_tool(title="One lead and its chat")
def lead_details(lead_id: str, limit: int = 30, before: str = "") -> dict:
    """One lead with its latest messages, oldest first. For earlier messages pass the
    `next_before` value from the previous answer as `before`."""
    return operator_leads.client_lead_thread(
        tenant_id=tenant_id(), lead_id=lead_lookup.as_uuid(lead_id), limit=limit, before=before, _admin=_AS,
    )


@client_tool(title="Chats")
def conversations() -> dict:
    """The 20 most recent chats with the last message of each, and how many chats are waiting
    for a person (handover_count)."""
    return operator.client_dashboard_inbox(tenant_id=tenant_id(), _admin=_AS)


@client_tool(title="Telecalling")
def calling_stats(section: str = "dialer") -> dict:
    """Telecalling. section is one of: dialer (calls today, connect rate, recent calls),
    scheduled (callbacks waiting), notes (call notes), upload (uploaded lead lists)."""
    if section not in ("dialer", "scheduled", "notes", "upload"):
        raise ToolError("section must be dialer, scheduled, notes or upload.")
    return operator.client_dashboard_telecalling(tenant_id=tenant_id(), section=section, _admin=_AS)


@client_tool(title="Broadcast history")
def broadcasts(date_from: str = "", date_to: str = "", limit: int = 50) -> dict:
    """Broadcasts already sent, newest first, with sent / delivered / read / replied / failed
    for each. Dates as 2026-11-01 (at most 92 days apart)."""
    return operator_broadcasts.client_broadcasts(
        tenant_id=tenant_id(), date_from=date_from or None, date_to=date_to or None, limit=limit, _admin=_AS,
    )


@client_tool(title="WhatsApp templates")
def templates() -> dict:
    """Your WhatsApp templates with Meta's status and the message text. Only APPROVED ones can
    be sent. {{1}}, {{2}} in the text are the blanks to fill when sending."""
    rows = (
        get_supabase().table("message_templates").select("*").eq("tenant_id", tenant_id()).order("name").limit(200).execute()
    ).data or []
    return {
        "templates": [
            {
                "id": r.get("id"), "name": r.get("name"), "status": (r.get("status") or "").upper(),
                "category": r.get("category"), "language": r.get("language"), "text": r.get("body_text"),
                "has_media_header": bool(r.get("header_media_type")),
                "rejection_reason": r.get("rejection_reason"),
            }
            for r in rows
        ],
    }


@client_tool(title="Team")
def team() -> dict:
    """Your telecallers (the names assign_lead accepts), their shifts and whether each is active."""
    data = operator.client_team(tenant_id=tenant_id(), _admin=_AS)
    return {"owner": data.get("owner"), "team": data.get("callers") or []}


@client_tool(title="Plan and usage")
def plan_and_usage() -> dict:
    """What your plan includes, the current billing period, and what has been used in it."""
    tenant = tenant_id()
    return {
        "plan": operator.get_client_entitlements(tenant_id=tenant, _admin=_AS).get("data"),
        "used_this_period": _usage_counters(tenant),
    }
