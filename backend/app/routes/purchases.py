"""Purchases & suppliers (services/purchases.py). Cost prices, supplier dues and payments are
money: reading needs purchases.view, changing stock, suppliers, orders and payments needs
purchases.manage (owners always); submitting the WhatsApp template needs templates.manage."""
import asyncio
import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import purchases as svc

require_read = require_permission("purchases.view")
require_manage = require_permission("purchases.manage")
router = APIRouter()


def _id(value: str, what: str) -> str:
    try:
        return str(UUID(str(value)))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── suppliers ────────────────────────────────────────────────────────────────

@router.get("/suppliers")
async def suppliers(ctx: dict = Depends(require_read)):
    db = get_supabase()
    view = await asyncio.to_thread(svc.suppliers_view, db, ctx["tenant_id"])
    low = await asyncio.to_thread(svc.suggestions, db, ctx["tenant_id"])
    return {**view, "low_stock": len(low)}


@router.post("/suppliers")
def create_supplier(payload: dict, ctx: dict = Depends(require_manage)):
    return _run(svc.save_supplier, get_supabase(), ctx["tenant_id"], payload)


@router.put("/suppliers/{supplier_id}")
def update_supplier(supplier_id: str, payload: dict, ctx: dict = Depends(require_manage)):
    return _run(svc.save_supplier, get_supabase(), ctx["tenant_id"], payload, _id(supplier_id, "Supplier"))


@router.post("/suppliers/{supplier_id}/payments")
def supplier_payment(supplier_id: str, payload: dict, ctx: dict = Depends(require_manage)):
    return _run(svc.record_payment, get_supabase(), ctx["tenant_id"], _id(supplier_id, "Supplier"), payload,
                ctx.get("user_id"))


@router.get("/suppliers/{supplier_id}/reorder")
def supplier_reorder(supplier_id: str, ctx: dict = Depends(require_read)):
    """A WhatsApp list of low-stock items to send the supplier from the phone (wa.me)."""
    db = get_supabase()
    sup = _run(svc._supplier, db, ctx["tenant_id"], _id(supplier_id, "Supplier"))
    low = svc.suggestions(db, ctx["tenant_id"])
    lines = [f"• {r['name']}{' ' + r['variant_label'] if r['variant_label'] else ''} × {r['suggested']}" for r in low[:30]]
    text = f"Vanakkam {sup['name'].split(' ')[0]}, we need these:\n" + "\n".join(lines) if lines else ""
    return {"text": text, "share_url": svc.share_url(sup.get("phone"), text) if text else None, "items": len(lines)}


# ── stock in ─────────────────────────────────────────────────────────────────

@router.post("/stock-in")
def stock_in(payload: dict, ctx: dict = Depends(require_manage)):
    return _run(svc.stock_in, get_supabase(), ctx["tenant_id"], payload, ctx.get("user_id"))


@router.get("/stock-in")
def stock_in_history(ctx: dict = Depends(require_read)):
    return {"data": svc.stock_in_history(get_supabase(), ctx["tenant_id"])}


@router.post("/stock-in/read-bill")
async def read_bill(file: UploadFile = File(...), ctx: dict = Depends(require_manage)):
    """The AI reads a photo / PDF of the supplier's bill; staff check it before saving."""
    from app.services.catalog_files import sniff

    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="The photo is too big. Up to 10 MB.")
    found = sniff(content)
    if not found or found[0] == "video":
        raise HTTPException(status_code=400, detail="Add a photo (JPG or PNG) or a PDF of the bill.")
    try:
        return await svc.read_bill(get_supabase(), ctx["tenant_id"], content, found[1])
    except svc.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/register.csv")
def purchase_register(month: str, ctx: dict = Depends(require_read)):
    """Purchase register for the accountant: supplier bills with GST paid, for one month (YYYY-MM)."""
    import re

    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise HTTPException(status_code=400, detail="Pick a month")
    db = get_supabase()
    y, m = int(month[:4]), int(month[5:])
    end = f"{y + (m == 12)}-{(m % 12) + 1:02d}-01"
    rows = (db.table("stock_ins").select("*").eq("tenant_id", ctx["tenant_id"]).gte("bill_date", f"{month}-01")
            .lt("bill_date", end).order("bill_date").limit(10000).execute().data or [])
    sups = {s["id"]: s["name"] for s in (db.table("suppliers").select("id, name").eq("tenant_id", ctx["tenant_id"])
                                          .limit(5000).execute().data or [])}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Bill date", "Supplier", "Supplier GSTIN", "Bill no.", "Taxable value", "GST paid", "Bill total"])
    def cell(value) -> str:  # a spreadsheet must never run a formula from a supplier's bill
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

    for r in rows:
        writer.writerow([cell(r["bill_date"]), cell(sups.get(r.get("supplier_id"))), cell(r.get("supplier_gstin")),
                         cell(r.get("bill_no")), f"{int(r['items_paise']) / 100:.2f}", f"{int(r['gst_paise']) / 100:.2f}",
                         f"{int(r['total_paise']) / 100:.2f}"])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="purchase-register-{month}.csv"'})


# ── purchase orders ──────────────────────────────────────────────────────────

@router.get("/orders")
async def orders(ctx: dict = Depends(require_read)):
    db = get_supabase()
    view = await asyncio.to_thread(svc.pos_view, db, ctx["tenant_id"])
    return {**view, "template_status": svc.template_status(db, ctx["tenant_id"])}


@router.get("/suggestions")
def suggestions(ctx: dict = Depends(require_read)):
    return {"data": svc.suggestions(get_supabase(), ctx["tenant_id"])}


@router.post("/orders")
def create_po(payload: dict, ctx: dict = Depends(require_manage)):
    return _run(svc.save_po, get_supabase(), ctx["tenant_id"], payload, ctx.get("user_id"))


@router.get("/orders/{po_id}")
def get_po(po_id: str, ctx: dict = Depends(require_read)):
    return _run(svc.po_view, get_supabase(), ctx["tenant_id"], _id(po_id, "Purchase order"))


@router.get("/orders/{po_id}/pdf")
def po_pdf(po_id: str, ctx: dict = Depends(require_read)):
    content, name = _run(svc.po_pdf, get_supabase(), ctx["tenant_id"], _id(po_id, "Purchase order"))
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.put("/orders/{po_id}")
def update_po(po_id: str, payload: dict, ctx: dict = Depends(require_manage)):
    return _run(svc.save_po, get_supabase(), ctx["tenant_id"], payload, ctx.get("user_id"), _id(po_id, "Purchase order"))


@router.post("/orders/{po_id}/send")
async def send_po(po_id: str, ctx: dict = Depends(require_manage)):
    try:
        return await svc.send_po(get_supabase(), ctx["tenant_id"], _id(po_id, "Purchase order"), ctx.get("user_id"))
    except svc.PurchaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/orders/{po_id}/cancel")
def cancel_po(po_id: str, ctx: dict = Depends(require_manage)):
    _run(svc.cancel_po, get_supabase(), ctx["tenant_id"], _id(po_id, "Purchase order"))
    return {"cancelled": True}


@router.get("/orders/{po_id}/remind")
def remind_po(po_id: str, ctx: dict = Depends(require_read)):
    """A reminder to send the supplier from the phone (wa.me): the PO and that it is late."""
    view = _run(svc.po_view, get_supabase(), ctx["tenant_id"], _id(po_id, "Purchase order"))
    text = f"Vanakkam, a reminder about {view['po_number']}. When can we expect it?\n\n" + view["message"]["text"]
    return {"text": text, "share_url": svc.share_url(view["supplier"].get("phone"), text)}


@router.post("/whatsapp-setup")
async def submit_template(ctx: dict = Depends(require_permission("templates.manage"))):
    """Submit anril_purchase_order (utility, with Confirm / Change date buttons) to Meta."""
    from app.routes.templates import Button, CreateTemplate, create_template

    db = get_supabase()
    status = svc.template_status(db, ctx["tenant_id"])
    if status in ("PENDING", "APPROVED"):
        return {"template_status": status}
    t = svc.TEMPLATE
    await create_template(
        CreateTemplate(name=t["name"], category="UTILITY", language="en", body_text=t["body"], body_examples=t["examples"],
                       buttons=[Button(type="QUICK_REPLY", text=b) for b in t["buttons"]]),
        tenant_id=ctx["tenant_id"], _ctx=ctx,
    )
    return {"template_status": svc.template_status(db, ctx["tenant_id"])}


@router.get("/options")
def form_options(ctx: dict = Depends(require_read)):
    # Cost prices are shown here on purpose: whoever places purchase orders needs what an item costs to order it.
    # Elsewhere (Catalogue, batches, counts) cost needs deals.view. Decided 2026-11-23 (v9.2 Batch 5).
    return svc.options(get_supabase(), ctx["tenant_id"])
