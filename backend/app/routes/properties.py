"""Catalogue > Properties (real estate, Batch P1). Planner registers this at /api/v1/properties.

Reading needs catalog.view, changing needs catalog.manage. Prices (the money columns) need deals.view and
are left out for everyone else; a person without deals.view cannot change them either.
Site visits are Bookings bookings under the "Site visit" service; see services/properties.py.
"""
import logging
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_permission
from app.services import properties as props

logger = logging.getLogger(__name__)

router = APIRouter()

view = require_permission("catalog.view")
manage = require_permission("catalog.manage")


@contextmanager
def _errors():
    try:
        yield
    except props.PropertyError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


def _money(ctx: dict) -> bool:
    return _has_permission(ctx, "deals.view")


class PropertyIn(BaseModel):
    name: str | None = None
    description: str | None = None
    ai_on: bool | None = None
    project: str | None = None
    kind: str | None = None
    bhk: int | None = None
    price_min_paise: int | None = None
    price_max_paise: int | None = None
    size_text: str | None = None
    units_total: int | None = None
    units_left: int | None = None
    map_url: str | None = None
    rera_no: str | None = None


class AttachIn(BaseModel):
    booking_id: str


@router.get("/availability")
def get_availability(ctx: dict = Depends(view)):
    """{"enabled": bool}: whether the catalogue shows the Properties tab for this business."""
    return props.availability(get_supabase(), ctx["tenant_id"])


@router.get("")
def list_all(q: str | None = Query(None, max_length=120), ctx: dict = Depends(view)):
    return {"data": props.list_properties(get_supabase(), ctx["tenant_id"], show_money=_money(ctx), q=q)}


@router.post("")
def create(body: PropertyIn, ctx: dict = Depends(manage)):
    with _errors():
        return props.create_property(get_supabase(), ctx["tenant_id"], body.model_dump(exclude_unset=True),
                                     show_money=_money(ctx))


@router.get("/{item_id}")
def get_one(item_id: str, ctx: dict = Depends(view)):
    with _errors():
        return props.get_property(get_supabase(), ctx["tenant_id"], item_id, show_money=_money(ctx))


@router.patch("/{item_id}")
def update(item_id: str, body: PropertyIn, ctx: dict = Depends(manage)):
    with _errors():
        return props.update_property(get_supabase(), ctx["tenant_id"], item_id, body.model_dump(exclude_unset=True),
                                     show_money=_money(ctx))


@router.delete("/{item_id}")
def delete(item_id: str, ctx: dict = Depends(manage)):
    with _errors():
        props.delete_property(get_supabase(), ctx["tenant_id"], item_id)
    return {"deleted": True}


@router.get("/{item_id}/visits")
def visits(item_id: str, ctx: dict = Depends(view)):
    """Upcoming site visits for this property, and upcoming ones not yet tied to any property. Phone numbers
    are hidden for people the business hides numbers from. Needs bookings.view too (visits are bookings)."""
    if not _has_permission(ctx, "bookings.view"):
        return {"mine": [], "others": [], "service_ready": False, "allowed": False}
    db = get_supabase()
    mask = None
    try:
        from app.services import call_rules
        if call_rules.hides_numbers(db, ctx["tenant_id"], ctx):
            mask = call_rules.mask_phone
    except Exception as e:  # fail closed: a telecaller never sees full numbers because a check failed
        logger.info("property visits: number hiding unavailable: %s", e)
        if ctx.get("role") == "caller":
            from app.services.call_rules import mask_phone
            mask = mask_phone
    with _errors():
        return {**props.visits_for(db, ctx["tenant_id"], item_id, mask=mask), "allowed": True}


@router.post("/{item_id}/visits")
def attach(item_id: str, body: AttachIn, ctx: dict = Depends(manage)):
    if not _has_permission(ctx, "bookings.view"):
        raise HTTPException(status_code=403, detail="Permission required: bookings.view")
    with _errors():
        props.attach_visit(get_supabase(), ctx["tenant_id"], item_id, body.booking_id)
    return {"attached": True}


@router.delete("/{item_id}/visits/{booking_id}")
def detach(item_id: str, booking_id: str, ctx: dict = Depends(manage)):
    if not _has_permission(ctx, "bookings.view"):
        raise HTTPException(status_code=403, detail="Permission required: bookings.view")
    with _errors():
        props.detach_visit(get_supabase(), ctx["tenant_id"], item_id, booking_id)
    return {"detached": True}
