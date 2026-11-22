"""Expenses (services/expenses.py). Seeing money and profit: purchases.view. Typing an expense: whoever
can bill (deals.manage, like Day closing's cash spent) or manage purchases. Repeats: purchases.manage."""
import asyncio

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_any_permission, require_permission
from app.services import expenses as ex
from app.services.audit_log import record_audit_event

router = APIRouter()
require_view = require_any_permission("purchases.view", "deals.manage")
require_profit = require_permission("purchases.view")
require_add = require_any_permission("purchases.manage", "deals.manage")
require_manage = require_permission("purchases.manage")


async def _run(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except ex.ExpenseError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", dependencies=[Depends(require_profit)])
async def month(month: str | None = None, tenant_id: str = Depends(get_tenant_id)):
    return await _run(ex.month_view, get_supabase(), tenant_id, month)


@router.get("/excel", dependencies=[Depends(require_profit)])
async def excel(month: str | None = None, tenant_id: str = Depends(get_tenant_id)):
    content, name = await _run(ex.month_excel, get_supabase(), tenant_id, month)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("")
async def add(payload: dict = Body(...), ctx: dict = Depends(require_add)):
    return await _run(ex.add, get_supabase(), ctx["tenant_id"], payload, ctx.get("user_id"))


@router.delete("/{expense_id}")
async def delete(expense_id: str, ctx: dict = Depends(require_add)):
    db = get_supabase()
    await _run(ex.delete, db, ctx["tenant_id"], expense_id)
    record_audit_event(db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
                       action="expense.deleted", target_type="expense", target_id=expense_id, metadata={})
    return {"ok": True}


@router.post("/{expense_id}/bill")
async def bill(expense_id: str, file: UploadFile = File(...), ctx: dict = Depends(require_add)):
    content = await file.read(8 * 1024 * 1024 + 1)
    path = await _run(ex.attach_bill, get_supabase(), ctx["tenant_id"], expense_id, content, file.content_type or "")
    return {"ok": True, "path": path}


@router.get("/{expense_id}/bill", dependencies=[Depends(require_view)])
async def bill_link(expense_id: str, tenant_id: str = Depends(get_tenant_id)):
    return {"url": await _run(ex.bill_url, get_supabase(), tenant_id, expense_id)}


@router.post("/repeats")
async def add_repeat(payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    return await _run(ex.save_repeat, get_supabase(), ctx["tenant_id"], payload, ctx.get("user_id"))


@router.put("/repeats/{repeat_id}")
async def edit_repeat(repeat_id: str, payload: dict = Body(...), ctx: dict = Depends(require_manage)):
    return await _run(ex.save_repeat, get_supabase(), ctx["tenant_id"], payload, ctx.get("user_id"), repeat_id)
