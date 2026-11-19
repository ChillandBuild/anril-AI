"""Tools about all clients at once. Each one calls the Operator Console's own read."""
import asyncio
import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import anyio

from app.admin_mcp.wrapper import admin_tool, resolve_client
from app.db.supabase import get_supabase
from app.routes import operator, operator_broadcasts, operator_sms

logger = logging.getLogger(__name__)
_IST = timezone(timedelta(hours=5, minutes=30))
_SUMMARY_WORKERS = 4

_ADMIN = {"user_id": "mcp"}  # the Operator reads take the admin only as a gate; the MCP has its own


@admin_tool(title="List clients")
def list_clients() -> dict:
    """Every Anril client: id, name, status, enabled features, created date, owner email."""
    return operator.list_clients(_admin=_ADMIN)


@admin_tool(title="Fleet alerts")
async def fleet_alerts() -> dict:
    """The active platform alerts across all clients (the Operator Console alert bell), most severe first."""
    return await operator.operator_alerts(_admin=_ADMIN)


@admin_tool(title="Scheduler health")
async def scheduler_health() -> dict:
    """Each background job's next run, last run, recent error count, plus the latest failed or missed runs."""
    return await operator.scheduler_health(_admin=_ADMIN)


@admin_tool(title="System health")
def system_health() -> dict:
    """Server health: uptime, memory, CPU, Python version and start time."""
    return operator.system_health(_admin=_ADMIN)


@admin_tool(title="Fleet AI spend")
def fleet_ai_spend(range_days: int = 90, all_time: bool = False, from_date: str = "", to_date: str = "") -> dict:
    """AI token use and estimated cost across all clients: totals, by provider, by feature, daily, and a per-client leaderboard with trend. Give range_days (default 90), or all_time, or both from_date and to_date as YYYY-MM-DD."""
    return operator.get_fleet_token_usage(
        range_days=range_days,
        all_time=all_time,
        from_date=from_date or None,
        to_date=to_date or None,
        _admin=_ADMIN,
    )


@admin_tool(title="Open requests")
def open_requests() -> dict:
    """Requests waiting for an operator: subscription requests that are submitted but not yet approved or rejected, and open SMS credit requests."""
    subscription_requests = operator.list_subscription_requests(status="submitted", _admin=_ADMIN)
    # An async Operator read whose database read blocks: run it here, in this tool's worker thread.
    sms_credit_requests = asyncio.run(operator_sms.list_credit_requests(status="open", _admin=_ADMIN))
    return {"subscription_requests": subscription_requests, "sms_credit_requests": sms_credit_requests}


@admin_tool(title="Audit log")
def audit_log(page: int = 1, limit: int = 50, client: str = "", action: str = "", include_claude_reads: bool = False) -> dict:
    """What operators did in the Operator Console, newest first, with a total count. Optionally only one client (name or id), only actions containing some text, and optionally including Claude's own tool-call rows."""
    return operator.list_audit_logs(
        page=max(1, page),
        limit=min(max(1, limit), 100),
        tenant_id=resolve_client(client)["id"] if client else None,
        action=action or None,
        include_mcp=include_claude_reads,
        _admin=_ADMIN,
    )



def _ist_today() -> tuple[str, str, str]:
    """(start of today in India as a UTC timestamp, today's IST date, yesterday's IST date)."""
    now_ist = datetime.now(timezone.utc).astimezone(_IST)
    midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        midnight.astimezone(timezone.utc).isoformat(),
        now_ist.date().isoformat(),
        (now_ist.date() - timedelta(days=1)).isoformat(),
    )


def _count(query) -> int:
    return query.execute().count or 0


def _client_row(client: dict, since_utc: str, today: str, yesterday: str) -> dict:
    """One client's line in the summary. A failure in one part is reported in that part, so one
    broken client never hides the others."""
    tenant_id = client["id"]
    row: dict = {"client": client.get("name"), "id": tenant_id}
    db = get_supabase()
    try:
        # The Operator Console's own figures (client → Product Overview).
        row["operator_overview"] = operator.client_overview(tenant_id=tenant_id, _admin=_ADMIN).get("stats")
    except Exception as exc:
        row["operator_overview_error"] = str(getattr(exc, "detail", exc))
    try:
        # New figures, not on any Operator Console page: counted from the start of today in India.
        def messages(direction: str) -> int:
            return _count(
                db.table("messages").select("id", count="exact").eq("tenant_id", tenant_id)
                .eq("direction", direction).gte("created_at", since_utc).limit(1)
            )

        row["today_ist"] = {
            "new_leads": _count(
                db.table("leads").select("id", count="exact").eq("tenant_id", tenant_id)
                .is_("deleted_at", "null").gte("created_at", since_utc).limit(1)
            ),
            "messages_received": messages("inbound"),
            "messages_sent": messages("outbound"),
        }
    except Exception as exc:
        row["today_ist_error"] = str(exc)
    try:
        sends = operator_broadcasts.client_broadcasts(
            tenant_id=tenant_id, date_from=yesterday, date_to=today, limit=100, _admin=_ADMIN,
        )
        row["broadcasts_yesterday_and_today"] = {"count": sends.get("count", 0), **(sends.get("totals") or {})}
    except Exception as exc:
        row["broadcasts_error"] = str(getattr(exc, "detail", exc))
    return row


def _client_rows(clients: list[dict], since_utc: str, today: str, yesterday: str) -> list[dict]:
    # Each task gets its own copy of the context: that is what carries the read-only guard
    # (app.db.supabase.read_only) into the worker threads.
    with ThreadPoolExecutor(max_workers=_SUMMARY_WORKERS) as pool:
        futures = [
            pool.submit(contextvars.copy_context().run, _client_row, client, since_utc, today, yesterday)
            for client in clients
        ]
        return [f.result() for f in futures]


@admin_tool(title="How is Anril today?")
async def fleet_summary() -> dict:
    """The daily health check in one call. For every active client: the Operator Console overview
    figures (total and active leads, messages in the last 30 days, team size, last activity), new
    figures for today in India (new leads, messages received and sent), and broadcasts sent
    yesterday and today with how many failed. Plus the platform alerts and whether the
    background jobs are running. The today_ist figures are new: no Operator Console page shows them."""
    since_utc, today, yesterday = _ist_today()
    clients = (await anyio.to_thread.run_sync(lambda: operator.list_clients(_admin=_ADMIN), abandon_on_cancel=True)).get("data") or []
    active = [c for c in clients if (c.get("status") or "active") == "active"]
    rows = await anyio.to_thread.run_sync(_client_rows, active, since_utc, today, yesterday, abandon_on_cancel=True)
    result: dict = {
        "day_ist": today,
        "clients": rows,
        "not_active": [{"client": c.get("name"), "status": c.get("status")} for c in clients if c not in active],
    }
    try:
        result["alerts"] = await operator.operator_alerts(_admin=_ADMIN)
    except Exception as exc:
        result["alerts_error"] = str(getattr(exc, "detail", exc))
    try:
        result["scheduler"] = await operator.scheduler_health(_admin=_ADMIN)
    except Exception as exc:
        result["scheduler_error"] = str(getattr(exc, "detail", exc))
    return result

