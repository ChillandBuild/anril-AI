"""Waiting-leads offer, as seen by one telecaller.

When a channel is set to "Available telecallers" and nobody is on shift, the
assignment sweep invites online, out-of-shift telecallers to take the waiting
leads (services/assignment_offers.py). These two routes let the signed-in
telecaller see that invite and answer it.

Both act only on the caller's own tenant and own caller row, both taken from
the auth context, never from the request.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.tenant import get_tenant_and_role
from app.services.assignment_offers import get_offer_for_caller, respond

logger = logging.getLogger(__name__)
router = APIRouter()

_NONE = {"state": "none"}


class OfferAnswer(BaseModel):
    accept: bool


@router.get("/current")
async def current_offer(ctx: dict = Depends(get_tenant_and_role)):
    caller_id = ctx.get("caller_id")
    if not caller_id:
        return _NONE
    try:
        return get_offer_for_caller(ctx["tenant_id"], str(caller_id))
    except Exception as e:
        # A poll every 20s from every telecaller: never surface a 500 for it.
        logger.warning(f"assignment offer lookup failed for caller {caller_id}: {e}")
        return _NONE


@router.post("/{offer_id}/respond")
async def respond_to_offer(offer_id: str, payload: OfferAnswer, ctx: dict = Depends(get_tenant_and_role)):
    caller_id = ctx.get("caller_id")
    if not caller_id:
        raise HTTPException(status_code=403, detail="Only telecallers can answer this")
    try:
        return respond(ctx["tenant_id"], str(caller_id), offer_id, payload.accept)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
