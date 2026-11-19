"""Tools about a client's broadcasts. Each one calls the Operator Console's own read.

The Operator read is a FastAPI handler, so every parameter is passed by keyword: a parameter
left out would arrive as a Depends(...) / Query(...) default object instead of a value.
"""
from app.admin_mcp.wrapper import admin_tool, resolve_client
from app.routes import operator_broadcasts

_ADMIN = {"user_id": "mcp"}  # the Operator reads take the admin only as a gate; the MCP has its own


@admin_tool(title="Client broadcasts")
def client_broadcasts(client: str, date_from: str = "", date_to: str = "", limit: int = 50) -> dict:
    """A client's broadcasts in a date range, with sent, delivered, read, replied and failed counts, as the client sees them. Dates are YYYY-MM-DD in Indian time (IST), both days included; the default is the last 7 days."""
    tenant = resolve_client(client)
    return operator_broadcasts.client_broadcasts(
        tenant_id=tenant["id"],
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        _admin=_ADMIN,
    )
