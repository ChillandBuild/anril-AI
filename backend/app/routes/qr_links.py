"""WhatsApp › QR & links (v9.2 #24). Service: app/services/qr_links.py.

router         /api/v1/qr-links        staff: numbers.view to see, numbers.manage to change
public_router  /api/v1/public/qr/{code} no login: the /q/<code> page asks where to send the customer"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_permission
from app.routes.auto_messages import _client_ip, _SlidingWindow
from app.services import qr_links as svc

logger = logging.getLogger(__name__)

router = APIRouter()
public_router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
_public_limiter = _SlidingWindow(120, 60)

view = require_permission("numbers.view")
manage = require_permission("numbers.manage")


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    first_message: str = Field(min_length=1, max_length=2000)
    place_id: Optional[str] = Field(None, max_length=64)


class UpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, max_length=200)
    first_message: Optional[str] = Field(None, max_length=2000)
    place_id: Optional[str] = Field(None, max_length=64)
    archived: Optional[bool] = None


def _money_ok(ctx: dict) -> bool:
    return _has_permission(ctx, "deals.view")


def _one(db, ctx: dict, row: dict) -> dict:
    _, names = svc.load_places(db, ctx["tenant_id"])
    return svc.build_items(db, ctx["tenant_id"], [row], include_money=_money_ok(ctx), place_names=names)[0]


def _fail(e: svc.QrError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.message)


# ================================================================ staff

@router.get("")
def list_qr_links(ctx: dict = Depends(view)):
    return svc.list_links(get_supabase(), ctx["tenant_id"], include_money=_money_ok(ctx))


@router.post("")
def create_qr_link(body: CreateIn, ctx: dict = Depends(manage)):
    db = get_supabase()
    try:
        row = svc.create_link(db, ctx["tenant_id"], name=body.name, first_message=body.first_message,
                              place_id=body.place_id, created_by=ctx.get("user_id"))
    except svc.QrError as e:
        raise _fail(e)
    return _one(db, ctx, row)


@router.patch("/{link_id}")
def update_qr_link(link_id: str, body: UpdateIn, ctx: dict = Depends(manage)):
    try:
        uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="QR not found.")
    db = get_supabase()
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    # name / first_message / archived cannot be cleared by sending null; only place_id can.
    for key in ("name", "first_message", "archived"):
        if key in changes and changes[key] is None:
            del changes[key]
    try:
        row = svc.update_link(db, ctx["tenant_id"], link_id, changes)
    except svc.QrError as e:
        raise _fail(e)
    if not row:
        raise HTTPException(status_code=404, detail="QR not found.")
    return _one(db, ctx, row)


# ================================================================ public

def _gone() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "This QR is no longer in use."}, headers=_NO_STORE)


@public_router.get("/{code}")
def public_qr(code: str, request: Request):
    ip = _client_ip(request)
    if not _public_limiter.allow(ip):
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Try again in a minute."},
                            headers={**_NO_STORE, "Retry-After": "60"})
    try:
        wa_url = svc.public_redirect(get_supabase(), code, ip)
    except Exception as e:
        logger.warning("qr_links: public lookup failed: %s", e)
        return JSONResponse(status_code=503, content={"detail": "Couldn't open this right now. Try again."},
                            headers=_NO_STORE)
    if not wa_url:
        return _gone()
    return JSONResponse(content={"wa_url": wa_url}, headers=_NO_STORE)
