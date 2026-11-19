"""Tools that find a lead and read its chat. Each one calls the Operator Console's own read."""
from app.admin_mcp.wrapper import admin_tool, resolve_client
from app.routes import operator_leads

_ADMIN = {"user_id": "mcp"}  # the Operator reads take the admin only as a gate; the MCP has its own


@admin_tool(title="Find a lead")
def find_lead(client: str, query: str, limit: int = 10) -> dict:
    """Find a client's leads by name or phone number (full numbers). Returns id, name, phone, segment, score, source."""
    c = resolve_client(client)
    return operator_leads.client_lead_search(tenant_id=c["id"], q=query, limit=limit, _admin=_ADMIN)


@admin_tool(title="Lead chat thread")
def lead_thread(client: str, lead_id: str, limit: int = 30, before: str = "") -> dict:
    """The full chat of one lead, newest message first, with the whole text. To read older messages, call again with before = the previous answer's next_before."""
    c = resolve_client(client)
    return operator_leads.client_lead_thread(
        tenant_id=c["id"], lead_id=lead_id, limit=limit, before=before, _admin=_ADMIN,
    )
