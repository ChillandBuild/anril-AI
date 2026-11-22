"""Stock count (services/stock_counts.py). Counting: anyone who manages the catalogue, purchases or bills.
Finish and fix stock: owners only (it changes stock everywhere and is recorded as a loss)."""
import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_any_permission, require_permission
from app.services import stock_counts as sc
from app.services.actor import actor_name
from app.services.audit_log import record_audit_event

router = APIRouter()
require_view = require_permission("catalog.view")
require_count = require_any_permission("catalog.manage", "purchases.manage", "deals.manage")


async def _run(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except sc.CountError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/counts", dependencies=[Depends(require_any_permission("catalog.view", "catalog.manage", "purchases.manage",
                                                                    "deals.manage"))])
async def counts(tenant_id: str = Depends(get_tenant_id)):
    return await _run(sc.view, get_supabase(), tenant_id)


@router.get("/corrections", dependencies=[Depends(require_any_permission("catalog.view", "purchases.view"))])
async def corrections(tenant_id: str = Depends(get_tenant_id)):
    return {"data": await _run(sc.corrections, get_supabase(), tenant_id)}


@router.post("/counts")
async def start(payload: dict = Body(...), ctx: dict = Depends(require_count)):
    db = get_supabase()
    return await _run(sc.start, db, ctx["tenant_id"], payload.get("place_id"), payload.get("sections"),
                      user_id=ctx.get("user_id"), user_name=actor_name(db, ctx))


@router.post("/counts/{count_id}/lines")
async def record(count_id: str, payload: dict = Body(...), ctx: dict = Depends(require_count)):
    db = get_supabase()
    return await _run(sc.record, db, ctx["tenant_id"], count_id, payload, user_id=ctx.get("user_id"),
                      user_name=actor_name(db, ctx))


@router.patch("/counts/lines/{line_id}")
async def reason(line_id: str, payload: dict = Body(...), ctx: dict = Depends(require_count)):
    await _run(sc.set_reason, get_supabase(), ctx["tenant_id"], line_id, payload.get("reason"))
    return {"ok": True}


@router.post("/counts/{count_id}/{action}")
async def status(count_id: str, action: str, ctx: dict = Depends(require_count)):
    db = get_supabase()
    if action == "finish":
        if ctx.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Only the owner can finish a count and fix stock.")
        out = await _run(sc.finish, db, ctx["tenant_id"], count_id, user_id=ctx.get("user_id"),
                         user_name=actor_name(db, ctx))
        record_audit_event(db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role="owner",
                           action="stock.count_finished", target_type="stock_count", target_id=count_id, metadata=out)
        return out
    target = {"pause": "paused", "resume": "open", "cancel": "cancelled"}.get(action)
    if not target:
        raise HTTPException(status_code=404, detail="Unknown action")
    await _run(sc.set_status, db, ctx["tenant_id"], count_id, target)
    return {"ok": True}
