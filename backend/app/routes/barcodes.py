"""Barcodes: labels to print, scanning, company barcodes (services/barcodes.py)."""
import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_any_permission, require_permission
from app.services import barcodes as bc

router = APIRouter()
require_view = require_permission("catalog.view")
require_manage = require_permission("catalog.manage")
# Scanning is for whoever bills, takes stock in or counts.
require_scan = require_any_permission("catalog.view", "deals.manage", "purchases.manage")


async def _run(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except bc.BarcodeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/labels/options", dependencies=[Depends(require_view)])
async def label_options(tenant_id: str = Depends(get_tenant_id)):
    return await _run(bc.options, get_supabase(), tenant_id)


@router.post("/labels")
async def make_labels(payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    """Makes Anril's own codes where needed (so it needs catalog.manage), then returns the labels."""
    return await _run(bc.labels, get_supabase(), ctx["tenant_id"], payload)


@router.get("/scan", dependencies=[Depends(require_scan)])
async def scan(code: str, tenant_id: str = Depends(get_tenant_id)):
    found = await asyncio.to_thread(bc.lookup, get_supabase(), tenant_id, code)
    if not found:
        raise HTTPException(status_code=404, detail="No item has this barcode.")
    return found


@router.get("/items/{item_id}/codes", dependencies=[Depends(require_view)])
async def item_codes(item_id: str, tenant_id: str = Depends(get_tenant_id)):
    if not bc._UUID.fullmatch(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    rows = (get_supabase().table("stock_codes").select("variant_id, code, company").eq("tenant_id", tenant_id)
            .eq("catalog_item_id", item_id).execute().data or [])
    return {"data": rows}


@router.put("/items/{item_id}/company-code")
async def company_code(item_id: str, payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    row = await _run(bc.set_company_code, get_supabase(), ctx["tenant_id"], item_id, payload.get("variant_id"),
                     payload.get("code"))
    return {"ok": True, "code": row}
