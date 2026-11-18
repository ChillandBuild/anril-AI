"""Chats page actions on one chat: mark it seen by the team, book a visit, mark it
not buying, and teach the Anril AI from a teammate's reply."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_owner, require_permission
from app.services import teach
from app.services.knowledge_versions import save_description

logger = logging.getLogger(__name__)
router = APIRouter()
require_conversations_view = require_permission("conversations.view")
require_conversations_reply = require_permission("conversations.reply")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_lead(lead_id: UUID, tenant_id: str, patch: dict) -> dict:
    res = (
        get_supabase().table("leads").update(patch)
        .eq("id", str(lead_id)).eq("tenant_id", tenant_id).is_("deleted_at", "null")
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Chat not found")
    return res.data[0]


@router.post("/{lead_id}/seen")
def mark_seen(lead_id: UUID, ctx: dict = Depends(require_conversations_view)):
    """Shared unread: once any teammate opens the chat it is read for everyone."""
    _update_lead(lead_id, ctx["tenant_id"], {"team_seen_at": _now()})
    return {"seen": True}


class BookingIn(BaseModel):
    booked_for: datetime | None = None
    note: str | None = Field(None, max_length=300)


@router.put("/{lead_id}/booking")
def book_visit(lead_id: UUID, payload: BookingIn, ctx: dict = Depends(require_conversations_reply)):
    """Marks the chat Booked. Booking clears Not buying: the newer decision wins."""
    lead = _update_lead(lead_id, ctx["tenant_id"], {
        "booked_at": _now(),
        "booked_for": payload.booked_for.isoformat() if payload.booked_for else None,
        "booking_note": (payload.note or "").strip() or None,
        "lost_at": None,
        "lost_reason": None,
        "lost_auto": False,
    })
    return lead


@router.delete("/{lead_id}/booking")
def cancel_booking(lead_id: UUID, ctx: dict = Depends(require_conversations_reply)):
    return _update_lead(lead_id, ctx["tenant_id"], {"booked_at": None, "booked_for": None, "booking_note": None})


class NotBuyingIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=120)


@router.put("/{lead_id}/not-buying")
def mark_not_buying(lead_id: UUID, payload: NotBuyingIn, ctx: dict = Depends(require_conversations_reply)):
    """Marks the chat Lost with a reason. A later payment still shows it as Came / Paid."""
    return _update_lead(lead_id, ctx["tenant_id"], {
        "lost_at": _now(),
        "lost_reason": payload.reason.strip(),
        "lost_auto": False,
        "booked_at": None,
        "booked_for": None,
        "booking_note": None,
    })


@router.delete("/{lead_id}/not-buying")
def undo_not_buying(lead_id: UUID, ctx: dict = Depends(require_conversations_reply)):
    """Back to no result. Undoing an automatic "stopped replying" is remembered
    (auto_lost_dismissed_at), so Anril does not mark them again for the same follow-up."""
    current = (get_supabase().table("leads").select("lost_auto").eq("id", str(lead_id))
               .eq("tenant_id", ctx["tenant_id"]).limit(1).execute()).data or []
    patch = {"lost_at": None, "lost_reason": None, "lost_auto": False}
    if current and current[0].get("lost_auto"):
        patch["auto_lost_dismissed_at"] = _now()
    return _update_lead(lead_id, ctx["tenant_id"], patch)


@router.get("/{lead_id}/teach-suggestion")
async def teach_suggestion(lead_id: UUID, ctx: dict = Depends(require_owner)):
    """The newest teammate reply in this chat, turned into a rule the AI can reuse.
    Owner only: only the owner can change what the AI is told."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    rows = (
        db.table("messages")
        .select("direction,is_ai_generated,content,media_type,sent_by_user_id,created_at")
        .eq("tenant_id", tenant_id)
        .eq("lead_id", str(lead_id))
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    ).data or []
    reply_idx = next(
        (i for i, m in enumerate(rows)
         if m["direction"] == "outbound" and not m.get("is_ai_generated") and m.get("sent_by_user_id")
         and not m.get("media_type") and (m.get("content") or "").strip()),
        None,
    )
    if reply_idx is None:
        return {"suggestion": None}
    reply = rows[reply_idx]["content"]
    # The customer's messages just before that reply (newest first in `rows`).
    question_parts: list[str] = []
    for m in rows[reply_idx + 1:]:
        if m["direction"] == "inbound":
            if (m.get("content") or "").strip():
                question_parts.append(m["content"].strip())
            if len(question_parts) == 3:
                break
        elif question_parts:
            break
    if not question_parts:
        return {"suggestion": None}
    question = "\n".join(reversed(question_parts))
    suggestion = await teach.suggest(question, reply, tenant_id=tenant_id)
    return {"suggestion": suggestion}


class TeachIn(BaseModel):
    when: str = Field(..., min_length=3, max_length=160)
    say: str = Field(..., min_length=1, max_length=400)


@router.post("/teach")
def save_taught_answer(payload: TeachIn, background_tasks: BackgroundTasks, ctx: dict = Depends(require_owner)):
    """Adds the rule under YOUR JOB IN EVERY CONVERSATION. Saved as a Description version,
    so the owner can change or undo it from Knowledge Base > Description."""
    tenant_id = ctx["tenant_id"]
    line = teach.rule_line(payload.when, payload.say)
    text, errors = teach.description_with_rule(tenant_id, line)
    if errors:
        raise HTTPException(
            status_code=422,
            detail="Your business description is full (700 words). Shorten it in Knowledge Base, then save this answer.",
        )
    save_description(get_supabase(), tenant_id, text, "edit", ctx.get("user_id"))
    from app.routes.ai_tune import queue_rubric_for_description
    from app.services.consistency import run_check_safely
    queue_rubric_for_description(tenant_id, text)
    background_tasks.add_task(run_check_safely, tenant_id)
    return {"saved": True, "line": line}
