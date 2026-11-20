"""Finding this client's leads. Every query here starts from the client the sign-in gave
(the `tenant` argument is always wrapper.tenant_id()), so a lead of another client is simply
not found."""
import uuid
from datetime import date, datetime, timedelta, timezone

from mcp.server.mcpserver.exceptions import ToolError

SEGMENTS = ("A", "B", "C", "D")
_IST = timezone(timedelta(hours=5, minutes=30))
_COLUMNS = (
    "id, name, phone, source, segment, score, assigned_to, opt_in_source, opted_out, blocked_at, "
    "archived_at, whatsapp_undeliverable, last_inbound_at, converted_at, created_at"
)
PAGE = 1000


def as_uuid(value: str, what: str = "lead_id") -> str:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError, TypeError):
        raise ToolError(f"{what} must be an id from find_leads, not a name or phone number.")


def own_lead(db, tenant: str, lead_id: str) -> dict:
    """The lead, only if it belongs to this client and is not deleted."""
    rows = (
        db.table("leads").select(_COLUMNS)
        .eq("id", as_uuid(lead_id)).eq("tenant_id", tenant).is_("deleted_at", "null").limit(1).execute()
    ).data or []
    if not rows:
        raise ToolError("No lead with that id in your account.")
    return rows[0]


def _ist_midnight(day: str, what: str) -> datetime:
    try:
        d = date.fromisoformat(day.strip())
    except ValueError:
        raise ToolError(f"{what} must be a date like 2026-10-01.")
    return datetime(d.year, d.month, d.day, tzinfo=_IST)


def search_term(search: str) -> tuple[str, str] | None:
    """What a search really looks for: ("phone", digits) or ("name", text). None when nothing
    usable is left (blank, or only symbols), so it filters nothing."""
    term = (search or "").strip()
    digits = "".join(ch for ch in term if ch.isdigit())
    if len(digits) >= 4 and len(digits) >= len(term) - 3:
        return "phone", digits
    safe = "".join(ch for ch in term if ch.isalnum() or ch in " .-'")[:60].strip()
    return ("name", safe) if safe else None


def filtered(db, tenant: str, *, search: str = "", segment: str = "", source: str = "",
             created_from: str = "", created_to: str = "", lead_ids: list[str] | None = None):
    """A leads query for this client with the given filters applied (dates are Indian time,
    both ends included). The caller adds order / range and runs it."""
    q = db.table("leads").select(_COLUMNS).eq("tenant_id", tenant).is_("deleted_at", "null")
    if segment:
        if segment.strip().upper() not in SEGMENTS:
            raise ToolError("segment must be A, B, C or D.")
        q = q.eq("segment", segment.strip().upper())
    if source:
        q = q.eq("source", source.strip().lower())
    if created_from:
        q = q.gte("created_at", _ist_midnight(created_from, "created_from").isoformat())
    if created_to:
        q = q.lt("created_at", (_ist_midnight(created_to, "created_to") + timedelta(days=1)).isoformat())
    if lead_ids:
        q = q.in_("id", [as_uuid(i) for i in lead_ids])
    term = search_term(search)
    if term:
        q = q.ilike(term[0], f"%{term[1]}%")
    return q


def public(lead: dict) -> dict:
    """What a tool answer shows of a lead."""
    return {
        "id": lead.get("id"), "name": lead.get("name"), "phone": lead.get("phone"),
        "source": lead.get("source"), "segment": lead.get("segment"), "score": lead.get("score"),
        "assigned_to": lead.get("assigned_to"), "opted_out": bool(lead.get("opted_out")),
        "last_customer_message_at": lead.get("last_inbound_at"), "converted_at": lead.get("converted_at"),
        "created_at": lead.get("created_at"),
    }
