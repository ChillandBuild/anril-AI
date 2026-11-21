"""Batches & expiry (services/stock_batches.py)."""
import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services import stock_batches as sb
from app.services.audit_log import record_audit_event

router = APIRouter(dependencies=[Depends(require_permission("catalog.view"))])
require_manage = require_permission("catalog.manage")


def _audit(db, ctx: dict, action: str, target_id: str, metadata: dict) -> None:
    record_audit_event(db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
                       action=action, target_type="stock_batch", target_id=target_id, metadata=metadata)


async def _run(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except sb.BatchError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/batches")
async def overview(tenant_id: str = Depends(get_tenant_id)):
    return await _run(sb.overview, get_supabase(), tenant_id)


@router.get("/items/{item_id}/batches")
async def item_batches(item_id: str, variant_id: str | None = None, tenant_id: str = Depends(get_tenant_id)):
    """Sellable batches for one item / size-colour, in the order selling takes them (bill line pick)."""
    if not sb._UUID.fullmatch(item_id) or (variant_id and not sb._UUID.fullmatch(variant_id)):
        raise HTTPException(status_code=404, detail="Item not found")
    rows = await asyncio.to_thread(sb.item_batches, get_supabase(), tenant_id, item_id, variant_id)
    return {"data": [r for r in rows if sb.sellable(r) and (variant_id or not r.get("variant_id"))]}


@router.put("/items/{item_id}/batch-tracking")
async def set_tracking(item_id: str, payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    db = get_supabase()
    on = bool(payload.get("on"))
    await _run(sb.set_tracking, db, ctx["tenant_id"], item_id, on)
    record_audit_event(db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
                       action="catalog.batches_on" if on else "catalog.batches_off", target_type="catalog_item",
                       target_id=item_id, metadata={})
    return {"ok": True, "tracks_batches": on}


@router.patch("/batches/{batch_id}")
async def update_batch(batch_id: str, payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    db = get_supabase()
    out = None
    if "discount_pct" in payload:
        out = await _run(sb.set_discount, db, ctx["tenant_id"], batch_id, payload["discount_pct"])
        _audit(db, ctx, "stock.batch_discount", batch_id, {"discount_pct": out["discount_pct"]})
    if "sell_first" in payload:
        out = await _run(sb.set_sell_first, db, ctx["tenant_id"], batch_id, bool(payload["sell_first"]))
        _audit(db, ctx, "stock.batch_sell_first", batch_id, {"on": out["sell_first"]})
    if out is None:
        raise HTTPException(status_code=400, detail="Nothing to change")
    return {"ok": True}


@router.post("/batches/{batch_id}/write-off")
async def write_off(batch_id: str, payload: dict = Body(default={}), ctx: dict = Depends(require_manage)):
    db = get_supabase()
    qty = await _run(sb.write_off, db, ctx["tenant_id"], batch_id, payload.get("quantity"),
                     user_id=ctx.get("user_id"), note=payload.get("note"))
    _audit(db, ctx, "stock.batch_written_off", batch_id, {"quantity": qty})
    return {"ok": True, "quantity": qty}


@router.post("/batches/{batch_id}/return")
async def return_to_supplier(batch_id: str, payload: dict = Body(default={}), ctx: dict = Depends(require_manage)):
    db = get_supabase()
    out = await _run(sb.return_to_supplier, db, ctx["tenant_id"], batch_id, payload.get("quantity"),
                     user_id=ctx.get("user_id"), note=payload.get("note"))
    _audit(db, ctx, "stock.batch_returned", batch_id, out)
    return {"ok": True, **out}
