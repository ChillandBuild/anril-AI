"""Tools that change a lead's record. They stay inside Anril and can be undone in the app.
Each one first checks the lead belongs to the signed-in client, then calls the same handler the
dashboard calls, so the side effects (assignment history, the telecaller's alert) are the app's.

Not here on purpose: changing a lead's segment. In the app that re-plans the lead's automatic
WhatsApp follow-ups, so through the connector it would be a way to message customers outside
the daily cap. It needs cap booking first (spec section 8)."""
import asyncio

from mcp.server.mcpserver.exceptions import ToolError

from app.client_mcp import leads as lead_lookup
from app.client_mcp.wrapper import client_tool, seat, tenant_id
from app.db.supabase import get_supabase
from app.routes import lead_notes as lead_notes_routes
from app.routes import leads as leads_routes

MAX_NOTE_CHARS = 2000


def _owner_ctx() -> dict:
    who = seat()
    return {"tenant_id": who["tenant_id"], "role": "owner", "user_id": who["user_id"], "caller_id": None, "permissions": []}


def _team_member(db, tenant: str, name: str) -> dict:
    """The one telecaller this name means. Unknown or unclear -> the list to pick from."""
    rows = db.table("callers").select("id, name").eq("tenant_id", tenant).execute().data or []
    wanted = name.strip().lower()
    exact = [r for r in rows if (r.get("name") or "").strip().lower() == wanted]
    partial = [r for r in rows if wanted in (r.get("name") or "").lower()]
    matches = exact or partial
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(sorted((r.get("name") or "") for r in (matches or rows))) or "nobody yet"
    if matches:
        raise ToolError(f'More than one team member matches "{name}": {names}. Use the full name.')
    raise ToolError(f'No team member called "{name}". You can assign to: {names}.')


@client_tool(title="Assign a lead")
def assign_lead(lead_id: str, team_member: str = "") -> dict:
    """Assign one lead to a team member by name, as the Assign button in Anril does. Leave
    team_member empty to unassign. Get lead_id from find_leads and names from team."""
    db, tenant = get_supabase(), tenant_id()
    lead = lead_lookup.own_lead(db, tenant, lead_id)
    member = _team_member(db, tenant, team_member) if team_member.strip() else None
    asyncio.run(leads_routes.assign_lead(
        lead["id"], leads_routes.AssignPayload(caller_id=member["id"] if member else None), _owner_ctx(),
    ))
    return {"lead": lead.get("name") or lead.get("phone"), "assigned_to": member["name"] if member else None}


@client_tool(title="Add a note to a lead")
def add_lead_note(lead_id: str, note: str) -> dict:
    """Add a note to one lead, as the Notes box in Anril does. The note is internal: the
    customer never sees it."""
    text = (note or "").strip()
    if not text:
        raise ToolError("The note is empty.")
    if len(text) > MAX_NOTE_CHARS:
        raise ToolError(f"The note is too long ({len(text)} characters, the limit is {MAX_NOTE_CHARS}).")
    db, tenant = get_supabase(), tenant_id()
    lead = lead_lookup.own_lead(db, tenant, lead_id)
    row = asyncio.run(lead_notes_routes.create_lead_note(
        lead["id"], lead_notes_routes.CreateNote(content=text), _owner_ctx(),
    ))
    return {"lead": lead.get("name") or lead.get("phone"), "note_id": row.get("id"), "note": text}
