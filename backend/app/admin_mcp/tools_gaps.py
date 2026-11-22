"""Admin tools for Operator Console reads the first 20 tools did not cover.

Same rules as tools_client.py: each tool calls the Operator Console's own read, every handler
parameter is passed by keyword (a parameter left out would arrive as a Depends(...) / Query(...)
object), and the database is read-only while a tool runs. These tools add two things on top:
long lists are cut to a fixed size with a note, and anything that could be a secret (keys,
tokens, passwords) is never passed on.
"""
from datetime import date

from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp.wrapper import admin_tool, resolve_client
from app.db.supabase import get_supabase
from app.routes import operator, operator_brain

_ADMIN = {"user_id": "mcp"}  # the Operator reads take the admin only as a gate; the MCP has its own

_LIST_LIMIT = 50          # rows shown per list
_RATES_LIMIT = 100        # provider-rate and plan lists are short by nature; allow more
_MAX_AUDIT_LIMIT = 50
_MAX_AUDIT_PAGE = 1000
_MAX_PROMPT_CHARS = 100_000
_MAX_AUDIT_TEXT = 300

# A metadata field whose name contains one of these is hidden, whatever its value.
_SECRET_WORDS = (
    "secret", "token", "password", "passwd", "authorization", "credential",
    "api_key", "apikey", "private_key", "key_hash", "license", "otp",
)


def _cap(rows: list | None, limit: int = _LIST_LIMIT) -> tuple[list, int]:
    """(the first `limit` rows, how many rows there were in all)."""
    rows = list(rows or [])
    return rows[:limit], len(rows)


def _truncation_note(shown: int, total: int, what: str) -> str | None:
    if total > shown:
        return f"Showing the first {shown} of {total} {what}."
    return None


def _is_secret_name(name: object) -> bool:
    low = str(name).lower()
    return low == "key" or any(word in low for word in _SECRET_WORDS)


def _scrub(value, depth: int = 0):
    """A copy of audit metadata with secret-looking fields hidden and long text cut."""
    if depth > 6:
        return "[too deep]"
    if isinstance(value, dict):
        return {
            k: ("[hidden]" if _is_secret_name(k) else _scrub(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v, depth + 1) for v in value[:_LIST_LIMIT]]
    if isinstance(value, str) and len(value) > _MAX_AUDIT_TEXT:
        return value[:_MAX_AUDIT_TEXT] + "…"
    return value


def _valid_day(value: str, label: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{label} must be a date like 2026-11-30.")
    return value


@admin_tool(title="Client team")
def client_team(client: str) -> dict:
    """The Team tab for one client: its owner (id, email, joined date), its telecallers with role, shift hours, active flag and this month's average call score, and its calling provider. Lists are cut at 50."""
    tenant = resolve_client(client)
    result = dict(operator.client_team(tenant_id=tenant["id"], _admin=_ADMIN))
    callers, total = _cap(result.get("callers"))
    result["callers"] = callers
    result["total_callers"] = total
    note = _truncation_note(len(callers), total, "team members")
    if note:
        result["note"] = note
    return result


@admin_tool(title="Client templates")
def client_templates(client: str) -> dict:
    """The Templates tab for one client: its WhatsApp message templates (name, status, category, language, last updated) with totals for all, approved and pending. The list is cut at 50."""
    tenant = resolve_client(client)
    result = dict(operator.client_dashboard_templates(tenant_id=tenant["id"], _admin=_ADMIN))
    templates, total = _cap(result.get("templates"))
    result["templates"] = templates
    note = _truncation_note(len(templates), total, "templates")
    if note:
        result["note"] = note
    return result


@admin_tool(title="Client numbers")
def client_numbers(client: str) -> dict:
    """The Numbers Pool tab for one client: its WhatsApp numbers (number, display name, quality rating, status, messaging limit tier) with totals for all and active. No access tokens. The list is cut at 50."""
    tenant = resolve_client(client)
    result = dict(operator.client_dashboard_numbers(tenant_id=tenant["id"], _admin=_ADMIN))
    numbers, total = _cap(result.get("numbers"))
    result["numbers"] = numbers
    note = _truncation_note(len(numbers), total, "numbers")
    if note:
        result["note"] = note
    return result


@admin_tool(title="Client knowledge base")
def client_knowledge(client: str) -> dict:
    """The Knowledge Base tab for one client: how many documents and text chunks it has, and each document's title, file type, added date and chunk count (a document with 0 chunks is not searchable). The list is cut at 50."""
    tenant = resolve_client(client)
    result = dict(operator.client_dashboard_knowledge(tenant_id=tenant["id"], _admin=_ADMIN))
    documents, total = _cap(result.get("documents"))
    result["documents"] = documents
    note = _truncation_note(len(documents), total, "documents")
    if note:
        result["note"] = note
    return result


@admin_tool(title="Client calling provider")
def client_calling_provider(client: str) -> dict:
    """Which calling provider one client uses (for example telecmi or sim_basic) and whether telecalling is switched on for it. Never any provider credentials."""
    tenant = resolve_client(client)
    result = operator.get_calling_provider(tenant_id=tenant["id"], _admin=_ADMIN)
    return {
        "tenant_id": result.get("tenant_id"),
        "calling_provider": result.get("calling_provider"),
        "telecalling_enabled": result.get("telecalling_enabled"),
    }


def _private_send_keys(keys: list[dict] | None) -> list[dict]:
    """Only whether a key exists and when it was made, last seen or revoked. Never the key, its
    start, or its hash."""
    return [
        {
            "id": k.get("id"),
            "status": k.get("status"),
            "created_at": k.get("created_at"),
            "last_seen_at": k.get("last_seen_at"),
            "revoked_at": k.get("revoked_at"),
        }
        for k in (keys or [])
    ]


@admin_tool(title="Client Private Send")
def client_private_send(client: str) -> dict:
    """The Private Send tab for one client: whether it is on, monthly cap, reply mode, offline grace hours, this month's usage (sent as reported by the client's plug-in against Meta's own count, per day) and the client's keys as status and dates only. Never a key value. Lists are cut at 50."""
    tenant = resolve_client(client)
    overview = operator.get_private_send(tenant_id=tenant["id"], _admin=_ADMIN)
    keys = _private_send_keys(overview.get("keys"))
    usage = dict(overview.get("usage") or {})
    days, total_days = _cap(usage.get("days"))
    usage["days"] = days
    result = {
        "enabled": overview.get("enabled"),
        "monthly_cap": overview.get("monthly_cap"),
        "reply_mode": overview.get("reply_mode"),
        "offline_grace_hours": overview.get("offline_grace_hours"),
        "has_active_key": any(k["status"] == "active" for k in keys),
        "keys": keys[:_LIST_LIMIT],
        "usage": usage,
    }
    notes = [
        n for n in (
            _truncation_note(len(days), total_days, "days of usage"),
            _truncation_note(len(result["keys"]), len(keys), "keys"),
        ) if n
    ]
    if notes:
        result["note"] = " ".join(notes)
    return result


@admin_tool(title="Client audit logs")
def client_audit_logs(client: str, limit: int = 25, page: int = 1, date_from: str = "", date_to: str = "") -> dict:
    """The Audit Logs tab for one client: what was done on its account (who, what, when), newest first, with the total. limit is rows per page (default 25, at most 50), page starts at 1, and date_from and date_to (YYYY-MM-DD) narrow the dates. Secret-looking fields in the details are hidden."""
    tenant = resolve_client(client)
    result = dict(operator.client_audit_logs(
        tenant_id=tenant["id"],
        page=min(max(1, page), _MAX_AUDIT_PAGE),
        limit=min(max(1, limit), _MAX_AUDIT_LIMIT),
        date_from=_valid_day(date_from, "date_from"),
        date_to=_valid_day(date_to, "date_to"),
        _admin=_ADMIN,
    ))
    result["data"] = [{**row, "metadata": _scrub(row.get("metadata"))} for row in (result.get("data") or [])]
    return result


@admin_tool(title="Subscription plans")
def subscription_plans() -> dict:
    """The Subscription page: the feature catalog (name, category, monthly or unit price, whether it is metered, included quantity) and the active plans (name, price, features, discount). Lists are cut at 100."""
    features, total_features = _cap(operator.get_features_catalog(_admin=_ADMIN).get("data"), _RATES_LIMIT)
    plans, total_plans = _cap(operator.list_plans(_admin=_ADMIN).get("data"), _RATES_LIMIT)
    result: dict = {"features": features, "plans": plans}
    notes = [
        n for n in (
            _truncation_note(len(features), total_features, "features"),
            _truncation_note(len(plans), total_plans, "plans"),
        ) if n
    ]
    if notes:
        result["note"] = " ".join(notes)
    return result


@admin_tool(title="Master prompt")
def master_prompt() -> dict:
    """The Master Prompt page: the one prompt text every client's assistant runs on. Read only; this tool cannot change it. Very long text is cut with a note."""
    text = operator.read_prompt_template(_admin=_ADMIN).get("template") or ""
    result: dict = {"prompt": text[:_MAX_PROMPT_CHARS], "characters": len(text)}
    if len(text) > _MAX_PROMPT_CHARS:
        result["note"] = f"The prompt is {len(text)} characters; only the first {_MAX_PROMPT_CHARS} are shown."
    return result


@admin_tool(title="Provider rates")
def provider_rates() -> dict:
    """The AI Spend page's provider rates: the cost per 1,000 input and output tokens set for each AI provider and model, and the provider and model pairs that have been used but still have no rate (their cost shows as zero). Lists are cut at 100."""
    rates = operator.list_provider_rates(_admin=_ADMIN).get("data") or {}
    configured, total_configured = _cap(rates.get("configured"), _RATES_LIMIT)
    missing, total_missing = _cap(rates.get("missing"), _RATES_LIMIT)
    result: dict = {"configured": configured, "missing": missing}
    notes = [
        n for n in (
            _truncation_note(len(configured), total_configured, "configured rates"),
            _truncation_note(len(missing), total_missing, "missing rates"),
        ) if n
    ]
    if notes:
        result["note"] = " ".join(notes)
    return result


@admin_tool(title="Clients waiting")
def clients_waiting() -> dict:
    """The Clients page's "Waiting approvals" list: clients with something waiting on them (sorted files to approve, knowledge conflicts, failed files, rejected templates), with how many and how long the oldest approval has waited, plus alerts for approvals stuck more than a week. Only clients with something waiting appear."""
    waiting = operator_brain.brain_waiting(_admin=_ADMIN)
    names = {
        str(r["id"]): r.get("name") or ""
        for r in (get_supabase().table("tenants").select("id, name").execute().data or [])
    }
    rows, total = _cap(waiting.get("data"))
    result = {
        "data": [{**row, "client": names.get(str(row.get("tenant_id")))} for row in rows],
        "alerts": (waiting.get("alerts") or [])[:_LIST_LIMIT],
        "stuck_after_days": waiting.get("stuck_after_days"),
        "clients_waiting": total,
    }
    note = _truncation_note(len(rows), total, "clients")
    if note:
        result["note"] = note
    return result
