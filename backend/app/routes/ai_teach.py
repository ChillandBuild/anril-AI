"""Anril Setup > Teach & offers: answers to doubts, the words a shop uses, and the offers on now.
View = owner, brain.view or knowledge.view (knowledge.manage implies it). Edit = owner or knowledge.manage."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_any_permission, require_permission
from app.services import ai_teach

logger = logging.getLogger(__name__)
router = APIRouter()
require_view = require_any_permission("brain.view", "knowledge.view")
require_edit = require_permission("knowledge.manage")


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, ai_teach.TableMissing):
        return HTTPException(status_code=503, detail=ai_teach.NOT_READY)
    return HTTPException(status_code=getattr(exc, "status", 422), detail=str(exc))


def _write(fn):
    try:
        return fn()
    except (ai_teach.TeachError, ai_teach.TableMissing) as exc:
        raise _fail(exc) from None


class ItemIn(BaseModel):
    kind: str = "answer"
    prompt: str = ""
    reply: str = ""
    source: Optional[str] = None     # the Brain "Couldn't answer" form sends 'couldnt_answer'; anything else = manual


class ItemPatch(BaseModel):
    prompt: Optional[str] = None
    reply: Optional[str] = None


class OfferIn(BaseModel):
    title: str = ""
    details: Optional[str] = None
    starts_on: Optional[str] = None
    ends_on: Optional[str] = None


class OfferPatch(BaseModel):
    title: Optional[str] = None
    details: Optional[str] = None
    starts_on: Optional[str] = None
    ends_on: Optional[str] = None


@router.get("/items")
def list_items(kind: Optional[str] = None, ctx: dict = Depends(require_view)):
    if kind not in (None, *ai_teach.KINDS):
        raise HTTPException(status_code=422, detail="Kind must be answer or word.")
    return ai_teach.list_items(get_supabase(), ctx["tenant_id"], kind)


@router.post("/items")
def add_item(body: ItemIn, ctx: dict = Depends(require_edit)):
    return _write(lambda: ai_teach.save_item(
        get_supabase(), ctx["tenant_id"], body.kind, body.prompt, body.reply,
        source="couldnt_answer" if body.source == "couldnt_answer" else "manual", user_id=ctx.get("user_id")))


@router.patch("/items/{item_id}")
def edit_item(item_id: str, body: ItemPatch, ctx: dict = Depends(require_edit)):
    return _write(lambda: ai_teach.update_item(get_supabase(), ctx["tenant_id"], item_id, body.prompt, body.reply))


@router.delete("/items/{item_id}")
def remove_item(item_id: str, ctx: dict = Depends(require_edit)):
    _write(lambda: ai_teach.delete_item(get_supabase(), ctx["tenant_id"], item_id))
    return {"deleted": True}


@router.get("/offers")
def list_offers(ctx: dict = Depends(require_view)):
    return ai_teach.list_offers(get_supabase(), ctx["tenant_id"])


@router.post("/offers")
def add_offer(body: OfferIn, ctx: dict = Depends(require_edit)):
    return _write(lambda: ai_teach.create_offer(
        get_supabase(), ctx["tenant_id"], body.title, body.details, body.starts_on, body.ends_on,
        user_id=ctx.get("user_id")))


@router.patch("/offers/{offer_id}")
def edit_offer(offer_id: str, body: OfferPatch, ctx: dict = Depends(require_edit)):
    changes = body.model_dump(exclude_unset=True)
    return _write(lambda: ai_teach.update_offer(get_supabase(), ctx["tenant_id"], offer_id, changes))


@router.post("/offers/{offer_id}/end")
def end_offer(offer_id: str, ctx: dict = Depends(require_edit)):
    return _write(lambda: ai_teach.end_offer(get_supabase(), ctx["tenant_id"], offer_id))


@router.delete("/offers/{offer_id}")
def remove_offer(offer_id: str, ctx: dict = Depends(require_edit)):
    _write(lambda: ai_teach.delete_offer(get_supabase(), ctx["tenant_id"], offer_id))
    return {"deleted": True}
