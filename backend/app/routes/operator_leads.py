"""Lead search and the full chat thread of one lead, for the Operator Console and the admin MCP.
System admins only, read-only. Every read is filtered by the client's tenant_id."""
import re
import unicodedata
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin

router = APIRouter()

_LEAD_COLUMNS = "id, name, phone, segment, score, source, created_at"
_MESSAGE_COLUMNS = "id,created_at,direction,channel,is_ai_generated,sent_by_name,media_type,content"
_SEARCH_MAX_LIMIT = 25
_THREAD_MAX_LIMIT = 100
_MESSAGE_MAX_CHARS = 4000
_QUERY_EXTRA_CHARS = set(" +-.'")


def _uuid_or_404(value: str, detail: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail=detail)


def _clean_query(q: str) -> str:
    """Letters (any language, with their vowel signs), digits, spaces and + - . ' only."""
    q = (q or "").strip()
    if not 2 <= len(q) <= 60:
        raise HTTPException(status_code=400, detail="Search text must be 2 to 60 characters.")
    for ch in q:
        cat = unicodedata.category(ch)
        if not (cat[0] in "LMN" and (cat[0] != "N" or ch.isdigit()) or ch in _QUERY_EXTRA_CHARS):
            raise HTTPException(
                status_code=400,
                detail="Search text may only have letters, digits, spaces and + - . '",
            )
    return q


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _lead_row(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "name", "phone", "segment", "score", "source", "created_at")}


@router.get("/clients/{tenant_id}/leads/search")
def client_lead_search(tenant_id: str, q: str = "", limit: int = 10, _admin: dict = Depends(get_system_admin)):
    """Find leads of one client by name or phone. Full phone numbers."""
    tenant_id = _uuid_or_404(tenant_id, "Client not found")
    q = _clean_query(q)
    limit = min(max(int(limit), 1), _SEARCH_MAX_LIMIT)

    digits = re.sub(r"\D", "", q)
    has_letters = any(unicodedata.category(c)[0] in "LM" for c in q)
    if len(digits) >= 4 and not has_letters:
        column, needle = "phone", digits
    else:
        column, needle = "name", q

    rows = (
        get_supabase()
        .table("leads")
        .select(_LEAD_COLUMNS)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .ilike(column, _like_pattern(needle))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []
    return {"query": q, "count": len(rows), "leads": [_lead_row(r) for r in rows]}


@router.get("/clients/{tenant_id}/leads/{lead_id}/thread")
def client_lead_thread(
    tenant_id: str,
    lead_id: str,
    limit: int = 50,
    before: str = "",
    _admin: dict = Depends(get_system_admin),
):
    """The chat thread of one lead, newest first. A lead of another client is a 404."""
    tenant_id = _uuid_or_404(tenant_id, "Lead not found")
    lead_id = _uuid_or_404(lead_id, "Lead not found")
    limit = min(max(int(limit), 1), _THREAD_MAX_LIMIT)

    cursor = (before or "").strip()
    if cursor:
        cursor = re.sub(r"\s(\d{2}:\d{2})$", r"+\1", cursor)  # "+" in a URL arrives as a space
        try:
            datetime.fromisoformat(cursor.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="before must be an ISO timestamp.")

    db = get_supabase()
    lead_res = (
        db.table("leads")
        .select(_LEAD_COLUMNS)
        .eq("id", lead_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not lead_res or not lead_res.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    query = db.table("messages").select(_MESSAGE_COLUMNS).eq("tenant_id", tenant_id).eq("lead_id", lead_id)
    if cursor:
        query = query.lt("created_at", cursor)
    rows = (query.order("created_at", desc=True).limit(limit).execute()).data or []

    messages = []
    for row in rows:
        msg = dict(row)
        content = msg.get("content")
        if isinstance(content, str) and len(content) > _MESSAGE_MAX_CHARS:
            msg["content"] = content[:_MESSAGE_MAX_CHARS]
            msg["truncated"] = True
        messages.append(msg)

    next_before = messages[-1].get("created_at") if messages and len(messages) >= limit else None
    return {"lead": _lead_row(lead_res.data), "messages": messages, "next_before": next_before}
