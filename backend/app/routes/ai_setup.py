"""v9.2 #23 Anril Setup: Couldn't answer, AI report card, reply thumbs-down, Questions & scoring (read-only).

Seeing = knowledge.view. Answering a question = knowledge.manage. A thumbs-down on an AI reply = conversations.view
or knowledge.view. Rupee figures (money from AI chats) need the owner or deals.view; without it the key is left out.
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_any_permission, require_permission
from app.services import ai_setup_report as report

logger = logging.getLogger(__name__)
router = APIRouter()
require_view = require_permission("knowledge.view")
require_edit = require_permission("knowledge.manage")
require_feedback = require_any_permission("conversations.view", "knowledge.view")


def _days(period: str | None) -> int:
    try:
        return report.parse_days(period)
    except report.SetupError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


def _caller_scope(ctx: dict) -> str | None:
    """Telecallers only ever see their own people."""
    return ctx.get("caller_id") if ctx.get("role") == "caller" else None


def _run(fn):
    try:
        return fn()
    except report.SetupError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


class AnswerIn(BaseModel):
    question: str = ""
    answer: str = ""


class FeedbackIn(BaseModel):
    message_id: str
    reason: str = "wrong"
    note: Optional[str] = None


@router.get("/couldnt-answer")
async def couldnt_answer(period: str = Query("30d"), ctx: dict = Depends(require_view)):
    days = _days(period)
    show_leads = _has_permission(ctx, "conversations.view")
    questions = await asyncio.to_thread(
        report.couldnt_answer, get_supabase(), ctx["tenant_id"], days,
        show_leads=show_leads, caller_id=_caller_scope(ctx))
    return {"period": {"days": days}, "questions": questions}


@router.post("/couldnt-answer/answer")
async def answer(body: AnswerIn, ctx: dict = Depends(require_edit)):
    return await asyncio.to_thread(
        _run, lambda: report.answer_question(get_supabase(), ctx["tenant_id"], body.question, body.answer,
                                             ctx.get("user_id")))


@router.get("/report-card")
async def report_card(period: str = Query("30d"), ctx: dict = Depends(require_view)):
    # The report card counts every chat in the business, so it is for the owner and managers, not telecallers.
    if ctx.get("role") == "caller":
        raise HTTPException(status_code=403, detail="The AI report card is for the owner and managers.")
    days = _days(period)
    return await asyncio.to_thread(
        report.report_card, get_supabase(), ctx["tenant_id"], days,
        sees_money=_has_permission(ctx, "deals.view"), caller_id=_caller_scope(ctx))


@router.post("/reply-feedback")
async def thumbs_down(body: FeedbackIn, ctx: dict = Depends(require_feedback)):
    saved = await asyncio.to_thread(
        _run, lambda: report.save_feedback(get_supabase(), ctx, body.message_id, body.reason, body.note))
    return {"ok": True, "feedback": saved}


@router.get("/reply-feedback/mine")
async def my_thumbs_down(message_ids: str = Query("", max_length=9000), ctx: dict = Depends(require_feedback)):
    """The caller's own marks on the AI replies on screen: {marks: {message_id: {reason, note}}}."""
    ids = [m for m in message_ids.split(",") if m.strip()]
    marks = await asyncio.to_thread(report.my_feedback, get_supabase(), ctx, ids)
    return {"marks": marks}


@router.delete("/reply-feedback/{message_id}")
async def undo_thumbs_down(message_id: str, ctx: dict = Depends(require_feedback)):
    await asyncio.to_thread(report.delete_feedback, get_supabase(), ctx, message_id)
    return {"ok": True}


@router.get("/scoring")
async def scoring(ctx: dict = Depends(require_view)):
    return await asyncio.to_thread(report.scoring_view, ctx["tenant_id"])
