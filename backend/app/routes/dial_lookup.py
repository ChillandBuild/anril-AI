"""Call IQ > Dial a number (v9.2 #231): while a telecaller types a number or a name, show the matching
customers. Same people and same hidden-number rule as the leads list: this business only, a telecaller
sees only the leads assigned to them, and the number is masked when the business hides numbers."""
import asyncio
import re

from fastapi import APIRouter, Depends, Query

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_any_permission
from app.routes.leads import LeadFilters, _filtered_leads_query, _hide_numbers_for_caller, _sanitize_search

router = APIRouter()

MAX_MATCHES = 5
_MIN_DIGITS = 3
_MIN_NAME = 2
_PHONE_CHARS = re.compile(r"^[\d\s+\-*#()]+$")
# The dial page's own gate (same as who can open it): the Dialer permissions, or the leads / team views.
_gate = require_any_permission("leads.view", "telecalling.dialer", "telecalling.dialer.view", "team.view")


def _lookup(db, ctx: dict, text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    by_phone = bool(_PHONE_CHARS.match(text))
    if by_phone:
        digits = re.sub(r"\D", "", text)
        if len(digits) < _MIN_DIGITS:
            return []
        if ctx.get("role") == "caller":
            # A hidden number must not be guessable one digit at a time: searching by digits only works
            # when this person is allowed to see the numbers.
            from app.services.call_rules import phone_mask_for
            if phone_mask_for(db, ctx["tenant_id"], ctx):
                return []
        clause = f"phone.ilike.*{digits}*"
    else:
        term = _sanitize_search(text)
        if not term or len(term) < _MIN_NAME:
            return []
        clause = f"name.ilike.*{term}*"
    query = _filtered_leads_query(db, ctx, LeadFilters(), columns="id,name,phone,segment,is_buyer")
    if query is None:
        return []
    rows = query.or_(clause).order("created_at", desc=True).limit(MAX_MATCHES).execute().data or []
    _hide_numbers_for_caller(db, ctx["tenant_id"], ctx, rows)
    return [{"id": r["id"], "name": r.get("name"), "phone": r.get("phone"), "segment": r.get("segment"),
             "is_buyer": bool(r.get("is_buyer")), "phone_hidden": bool(r.get("phone_hidden"))} for r in rows]


@router.get("/lookup")
async def lookup(q: str = Query("", max_length=60), ctx: dict = Depends(_gate)):
    """Up to 5 customers matching what is typed: digits search the number, anything else searches the name."""
    return {"matches": await asyncio.to_thread(_lookup, get_supabase(), ctx, q)}
