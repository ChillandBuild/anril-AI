"""Shop & godown: places, stock per place, Move stock (services/stock_places.py)."""
import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services import stock_places as sp
from app.services.actor import actor_name
from app.services.audit_log import record_audit_event

router = APIRouter(dependencies=[Depends(require_permission("catalog.view"))])
require_manage = require_permission("catalog.manage")


def _audit(db, ctx: dict, action: str, target_id: str | None, metadata: dict) -> None:
    record_audit_event(db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
                       action=action, target_type="stock", target_id=target_id, metadata=metadata)


@router.get("/overview")
async def overview(tenant_id: str = Depends(get_tenant_id)):
    return await asyncio.to_thread(sp.overview, get_supabase(), tenant_id)


@router.get("/places")
async def list_places(tenant_id: str = Depends(get_tenant_id)):
    return {"data": await asyncio.to_thread(sp.places, get_supabase(), tenant_id)}


@router.put("/places")
async def save_places(payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    db = get_supabase()
    try:
        rows = await asyncio.to_thread(sp.save_places, db, ctx["tenant_id"], payload.get("places"))
    except sp.StockPlaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit(db, ctx, "stock.places_saved", None, {"places": [p["name"] for p in rows]})
    return {"data": rows}


@router.post("/moves")
async def send_move(payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    db = get_supabase()
    try:
        out = await asyncio.to_thread(sp.send_move, db, ctx["tenant_id"], payload,
                                      user_id=ctx.get("user_id"), user_name=actor_name(db, ctx))
    except sp.StockPlaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit(db, ctx, "stock.move_sent", out["id"], {"from": payload.get("from_place_id"), "to": payload.get("to_place_id")})
    return out


async def _finish(move_id: str, ctx: dict, received: bool) -> dict:
    db = get_supabase()
    try:
        done = await asyncio.to_thread(sp.finish_move, db, ctx["tenant_id"], move_id, received=received,
                                       user_id=ctx.get("user_id"), user_name=actor_name(db, ctx))
    except sp.StockPlaceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not done:
        raise HTTPException(status_code=409, detail="This move was already received or cancelled.")
    _audit(db, ctx, "stock.move_received" if received else "stock.move_cancelled", move_id, {})
    return {"ok": True}


@router.post("/moves/{move_id}/received")
async def receive_move(move_id: str, ctx: dict = Depends(require_manage)):
    return await _finish(move_id, ctx, True)


@router.post("/moves/{move_id}/cancel")
async def cancel_move(move_id: str, ctx: dict = Depends(require_manage)):
    return await _finish(move_id, ctx, False)
