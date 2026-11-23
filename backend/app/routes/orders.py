"""Commerce > Orders & payments (services/orders.py holds the rules). Orders are deals rows,
so the deals.view / deals.manage permissions apply; the customer's bill page is public by
its secret token and shows only what is printed on the bill."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_owner, require_permission
from app.services import orders as orders_service
from app.services.orders import OrderError

logger = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()
require_deals_view = require_permission("deals.view")
require_deals_manage = require_permission("deals.manage")


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


def _caller_id(db, ctx: dict) -> str | None:
    """The signed-in person's team row, for "received by"."""
    if not ctx.get("user_id"):
        return None
    rows = (
        db.table("callers").select("id").eq("tenant_id", ctx["tenant_id"]).eq("user_id", ctx["user_id"]).limit(1).execute()
    ).data or []
    return rows[0]["id"] if rows else None


def _sender(ctx: dict) -> dict:
    return {"sent_by_user_id": ctx.get("user_id")} if ctx.get("user_id") else {}


@router.get("")
def list_orders(
    chip: str = Query("all"),
    channel: Literal["all", "online", "store"] = "all",
    days: int = Query(30, ge=0, le=3660),
    q: str | None = Query(None, max_length=80),
    ctx: dict = Depends(require_deals_view),
):
    return orders_service.list_orders(
        get_supabase(), ctx["tenant_id"], chip=chip, channel=None if channel == "all" else channel,
        days=days or None, q=q,
    )


@router.get("/new-bill/options")
def new_bill_options(ctx: dict = Depends(require_deals_manage)):
    return orders_service.bill_options(get_supabase(), ctx["tenant_id"])


@router.get("/customer")
def find_customer(phone: str = Query(..., min_length=6, max_length=20), ctx: dict = Depends(require_deals_manage)):
    """Who this number is, while staff type it on New bill."""
    from app.routes.upload import _normalize_phone
    db = get_supabase()
    number = _normalize_phone(phone)
    if not number:
        return {"found": False}
    rows = (
        db.table("leads").select("id, name, phone").eq("tenant_id", ctx["tenant_id"]).eq("phone", number)
        .is_("deleted_at", "null").limit(1).execute()
    ).data or []
    if not rows:
        return {"found": False}
    orders = (
        db.table("deals").select("id").eq("tenant_id", ctx["tenant_id"]).eq("lead_id", rows[0]["id"]).neq("stage", "lost").execute()
    ).data or []
    return {"found": True, "lead_id": rows[0]["id"], "name": rows[0].get("name"), "orders": len(orders)}


class BillLine(BaseModel):
    catalog_item_id: str = Field(..., max_length=64)
    variant_id: str | None = Field(None, max_length=64)
    qty: int = Field(1, ge=1, le=100000)
    unit_price_paise: int | None = Field(None, ge=0, le=10_000_000_00)
    batch_id: str | None = Field(None, max_length=64)  # Batches & expiry: the batch staff picked


class NewBillIn(BaseModel):
    mode: Literal["now", "later"]
    phone: str | None = Field(None, max_length=20)
    name: str | None = Field(None, max_length=120)
    items: list[BillLine] = Field(..., min_length=1, max_length=60)
    discount_paise: int = Field(0, ge=0, le=10_000_000_00)
    bill_type: Literal["gst", "simple"] = "gst"
    gstin: str | None = Field(None, max_length=15)
    business: str | None = Field(None, max_length=120)
    sold_by: str | None = Field(None, max_length=64)
    sold_by_ai: bool = False
    method: Literal["cash", "upi", "card", "link"]
    advance_paise: int = Field(0, ge=0, le=10_000_000_00)
    handover: Literal["pickup", "courier"] | None = None
    ready_by: str | None = Field(None, max_length=10)
    notes: str | None = Field(None, max_length=2000)


@router.post("/bills")
async def create_bill(payload: NewBillIn, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    try:
        return await orders_service.create_bill(db, ctx["tenant_id"], payload.model_dump(),
                                                user_id=ctx.get("user_id"), sender=_sender(ctx))
    except OrderError as e:
        raise _bad(e)


class WaitlistIn(BaseModel):
    catalog_item_id: str = Field(..., max_length=64)
    variant_id: str | None = Field(None, max_length=64)
    phone: str = Field(..., min_length=6, max_length=20)
    name: str | None = Field(None, max_length=120)


@router.post("/waitlist")
def add_to_waitlist(payload: WaitlistIn, ctx: dict = Depends(require_deals_manage)):
    try:
        return orders_service.add_waitlist(get_supabase(), ctx["tenant_id"], item_id=payload.catalog_item_id,
                                           variant_id=payload.variant_id, phone=payload.phone, name=payload.name,
                                           user_id=ctx.get("user_id"))
    except OrderError as e:
        raise _bad(e)


# ── Quotes ────────────────────────────────────────────────────────────────────

@router.get("/advance-rule")
def get_advance_rule(ctx: dict = Depends(require_deals_view)):
    from app.services.order_quotes import advance_rule
    return advance_rule(ctx["tenant_id"])


class AdvanceRuleIn(BaseModel):
    kind: Literal["none", "percent", "fixed"]
    value: float = Field(0, ge=0, le=10_000_000)
    min_total_paise: int = Field(0, ge=0, le=10_000_000_00)


@router.put("/advance-rule")
def put_advance_rule(payload: AdvanceRuleIn, ctx: dict = Depends(require_owner)):
    """Owner only: the shop's advance rule (quotes and New bill start from it)."""
    from app.services.order_quotes import save_advance_rule
    try:
        return save_advance_rule(get_supabase(), ctx["tenant_id"], payload.model_dump())
    except OrderError as e:
        raise _bad(e)


class QuoteLine(BaseModel):
    catalog_item_id: str | None = Field(None, max_length=64)
    variant_id: str | None = Field(None, max_length=64)
    name: str | None = Field(None, max_length=200)
    qty: int = Field(1, ge=1, le=100000)
    unit_price_paise: int | None = Field(None, ge=0, le=10_000_000_00)


class QuoteAdvance(BaseModel):
    kind: Literal["rule", "none", "percent", "fixed"] = "rule"
    value: float = Field(0, ge=0, le=10_000_000)


class NewQuoteIn(BaseModel):
    lead_id: str | None = Field(None, max_length=64)
    phone: str | None = Field(None, max_length=20)
    name: str | None = Field(None, max_length=120)
    items: list[QuoteLine] = Field(..., min_length=1, max_length=60)
    discount_paise: int = Field(0, ge=0, le=10_000_000_00)
    valid_until: str | None = Field(None, max_length=10)
    advance: QuoteAdvance = Field(default_factory=QuoteAdvance)
    ready_in_days: int | None = Field(None, ge=0, le=365)
    notes: str | None = Field(None, max_length=2000)
    sold_by: str | None = Field(None, max_length=64)
    send: bool = True


@router.post("/quotes")
async def create_quote(payload: NewQuoteIn, ctx: dict = Depends(require_deals_manage)):
    from app.services.order_quotes import create_quote as make
    try:
        return await make(get_supabase(), ctx["tenant_id"], payload.model_dump(), user_id=ctx.get("user_id"),
                          send=payload.send, sender=_sender(ctx))
    except OrderError as e:
        raise _bad(e)


# ── Order settings (middle step name, Google review link) ──────────────────────

@router.get("/settings")
def get_order_settings(ctx: dict = Depends(require_deals_view)):
    return orders_service.order_settings(ctx["tenant_id"])


class OrderSettingsIn(BaseModel):
    working_label: str = Field("Working on it", max_length=30)
    google_review_link: str = Field("", max_length=300)


@router.put("/settings")
def put_order_settings(payload: OrderSettingsIn, ctx: dict = Depends(require_owner)):
    try:
        return orders_service.save_order_settings(get_supabase(), ctx["tenant_id"], payload.model_dump())
    except OrderError as e:
        raise _bad(e)


class RemindersIn(BaseModel):
    on: bool


@router.get("/balance-reminders")
def get_balance_reminders(ctx: dict = Depends(require_deals_view)):
    """Is the automatic WhatsApp reminder for an unpaid balance on? (On unless the owner turned it off.)"""
    return {"on": orders_service.balance_reminders_on(get_supabase(), ctx["tenant_id"])}


@router.put("/balance-reminders")
def put_balance_reminders(payload: RemindersIn, ctx: dict = Depends(require_owner)):
    """Owner only: switch the automatic balance reminders on or off for the whole shop."""
    return {"on": orders_service.save_balance_reminders(get_supabase(), ctx["tenant_id"], payload.on)}


# ── Day closing ───────────────────────────────────────────────────────────────

@router.get("/day-closing")
def day_closing(day: str | None = Query(None, max_length=10), ctx: dict = Depends(require_deals_view)):
    from app.services import day_closing as dc
    try:
        return dc.summary(get_supabase(), ctx["tenant_id"], dc.parse_day(day))
    except OrderError as e:
        raise _bad(e)


class CashExpenseIn(BaseModel):
    day: str | None = Field(None, max_length=10)
    label: str = Field(..., min_length=1, max_length=80)
    amount_paise: int = Field(..., ge=100, le=10_000_000_00)
    spent_by: str | None = Field(None, max_length=60)


@router.post("/day-closing/expenses")
def add_cash_expense(payload: CashExpenseIn, ctx: dict = Depends(require_deals_manage)):
    from app.services import day_closing as dc
    db = get_supabase()
    try:
        day = dc.parse_day(payload.day)
        dc.add_expense(db, ctx["tenant_id"], day, payload.label, payload.amount_paise, payload.spent_by, ctx.get("user_id"))
        return dc.summary(db, ctx["tenant_id"], day)
    except OrderError as e:
        raise _bad(e)


@router.delete("/day-closing/expenses/{expense_id}")
def delete_cash_expense(expense_id: str, day: str | None = Query(None, max_length=10), ctx: dict = Depends(require_deals_manage)):
    from app.services import day_closing as dc
    db = get_supabase()
    try:
        d = dc.parse_day(day)
        dc.delete_expense(db, ctx["tenant_id"], expense_id)
        return dc.summary(db, ctx["tenant_id"], d)
    except OrderError as e:
        raise _bad(e)


class CloseDayIn(BaseModel):
    day: str | None = Field(None, max_length=10)
    opening_paise: int = Field(..., ge=0, le=10_000_000_00)
    counted_paise: int = Field(..., ge=0, le=10_000_000_00)
    note: str | None = Field(None, max_length=300)


@router.post("/day-closing/close")
def close_day(payload: CloseDayIn, ctx: dict = Depends(require_deals_manage)):
    from app.services import day_closing as dc
    try:
        return dc.close_day(get_supabase(), ctx["tenant_id"], dc.parse_day(payload.day), opening_paise=payload.opening_paise,
                            counted_paise=payload.counted_paise, note=payload.note, user_id=ctx.get("user_id"),
                            user_role=ctx.get("role"))
    except OrderError as e:
        raise _bad(e)


@router.get("/day-closing/export")
def export_day_closing(day: str | None = Query(None, max_length=10), ctx: dict = Depends(require_deals_view)):
    from fastapi.responses import Response
    from app.services import day_closing as dc
    try:
        d = dc.parse_day(day)
    except OrderError as e:
        raise _bad(e)
    content = dc.export_csv(get_supabase(), ctx["tenant_id"], d)
    return Response(content="\ufeff" + content, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="day-closing-{d.isoformat()}.csv"'})


# ── WhatsApp templates for orders ─────────────────────────────────────────────

def _template_status(db, tenant_id: str) -> list[dict]:
    from app.config_dynamic import get_setting
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    names = [t["name"] for t in orders_service.ORDER_TEMPLATES.values()]
    rows = (
        db.table("message_templates").select("name, status, meta_waba_id").eq("tenant_id", tenant_id).in_("name", names).execute()
    ).data or []
    by_name = {r["name"]: r for r in rows if not waba_id or r.get("meta_waba_id") == waba_id}
    out = []
    for key, t in orders_service.ORDER_TEMPLATES.items():
        row = by_name.get(t["name"])
        out.append({"key": key, "name": t["name"], "body": t["body"],
                    "status": (row.get("status") or "PENDING").upper() if row else "MISSING"})
    return out


@router.get("/whatsapp-setup")
def whatsapp_setup(ctx: dict = Depends(require_deals_view)):
    from app.config_dynamic import get_setting
    tenant_id = ctx["tenant_id"]
    return {"connected": bool(get_setting("meta_waba_id", tenant_id=tenant_id)),
            "templates": _template_status(get_supabase(), tenant_id)}


@router.post("/whatsapp-setup")
async def submit_order_templates(ctx: dict = Depends(require_permission("templates.manage"))):
    """Submit the missing order templates to Meta (utility, English) through the Templates
    page's own path, so they show and update there like any other template."""
    from app.routes.templates import Button, CreateTemplate, create_template
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    problems = []
    for item in _template_status(db, tenant_id):
        if item["status"] not in ("MISSING", "REJECTED"):
            continue
        spec = orders_service.ORDER_TEMPLATES[item["key"]]
        try:
            buttons = [Button(type="QUICK_REPLY", text=t) for t in spec.get("buttons", [])]
            if spec.get("view_bill"):
                base = orders_service.bill_url("{{1}}")
                buttons.append(Button(type="URL", text="View bill", url=base, url_example=orders_service.VIEW_BILL_EXAMPLE))
            header_handle = await _sample_header_handle(db, tenant_id, spec) if spec.get("header") else None
            await create_template(
                CreateTemplate(name=spec["name"], category="UTILITY", language="en", body_text=spec["body"],
                               body_examples=spec["examples"], footer_text=spec.get("footer"),
                               header_media_type=spec.get("header"), header_media_url=header_handle,
                               buttons=buttons or None),
                tenant_id=tenant_id, _ctx=ctx,
            )
        except HTTPException as e:
            problems.append(f"{spec['name']}: {e.detail}")
    return {"templates": _template_status(db, tenant_id), "problems": problems}


async def _sample_header_handle(db, tenant_id: str, spec: dict) -> str:
    """Meta reviews a picture/PDF template with an example file: a sample bill in the shop's name."""
    import asyncio
    from app.routes.templates import _meta_app_id
    from app.services import bill_files, template_media
    from app.services.meta_cloud import upload_media_for_template
    app_id = _meta_app_id(tenant_id)
    if not app_id:
        raise HTTPException(status_code=503, detail="Media upload isn't set up on the server yet. Please contact Anril support.")
    is_pdf = spec["header"] == "DOCUMENT"
    sample = bill_files.sample_bill(orders_service._shop_name(db, tenant_id), "gst" if is_pdf else "simple")
    data = await asyncio.to_thread(bill_files.invoice_pdf if is_pdf else bill_files.bill_png, sample)
    content_type = "application/pdf" if is_pdf else "image/png"
    handle = await upload_media_for_template(file_bytes=data, file_type=content_type, file_length=len(data),
                                             app_id=app_id, tenant_id=tenant_id)
    template_media.save_upload(db, tenant_id, handle, data, content_type)
    return handle


# ── One order ─────────────────────────────────────────────────────────────────

@router.get("/{deal_id}")
def get_order(deal_id: str, ctx: dict = Depends(require_deals_view)):
    try:
        return orders_service.order_detail(get_supabase(), ctx["tenant_id"], deal_id)
    except OrderError:
        raise HTTPException(status_code=404, detail="Order not found")


class PaymentIn(BaseModel):
    amount_paise: int = Field(..., ge=100, le=10_000_000_00)
    method: Literal["cash", "upi", "card", "bank_transfer", "other"]
    note: str | None = Field(None, max_length=300)


@router.post("/{deal_id}/payments")
async def add_payment(deal_id: str, payload: PaymentIn, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    try:
        out = await orders_service.take_payment(db, tenant_id, deal_id, payload.amount_paise, payload.method,
                                                user_id=ctx.get("user_id"), caller_id=_caller_id(db, ctx), note=payload.note)
    except OrderError as e:
        raise _bad(e)
    return {"order": orders_service.order_detail(db, tenant_id, deal_id), "paid_in_full": out["won"],
            "stock_warnings": out.get("stock_warnings") or []}


@router.post("/{deal_id}/pay-link")
async def pay_link(deal_id: str, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    try:
        out = await orders_service.send_pay_link(db, ctx["tenant_id"], deal_id, user_id=ctx.get("user_id"), sender=_sender(ctx))
    except OrderError as e:
        raise _bad(e)
    return {**out, "order": orders_service.order_detail(db, ctx["tenant_id"], deal_id)}


@router.post("/{deal_id}/remind")
async def remind(deal_id: str, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    try:
        out = await orders_service.send_pay_link(db, ctx["tenant_id"], deal_id, user_id=ctx.get("user_id"),
                                                 kind="reminder", sender=_sender(ctx))
    except OrderError as e:
        raise _bad(e)
    return {**out, "order": orders_service.order_detail(db, ctx["tenant_id"], deal_id)}


class DeliveryIn(BaseModel):
    action: Literal["working", "ready", "shipped", "delivered"]
    handover: Literal["pickup", "courier"] | None = None
    courier: str | None = Field(None, max_length=60)
    tracking_id: str | None = Field(None, max_length=80)
    tell_customer: bool = True


@router.post("/{deal_id}/delivery")
async def delivery(deal_id: str, payload: DeliveryIn, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    try:
        out = await orders_service.move_delivery(
            db, ctx["tenant_id"], deal_id, payload.action, handover=payload.handover, courier=payload.courier,
            tracking_id=payload.tracking_id, tell_customer=payload.tell_customer, user_id=ctx.get("user_id"),
            sender=_sender(ctx),
        )
    except OrderError as e:
        raise _bad(e)
    return {**out, "order": orders_service.order_detail(db, ctx["tenant_id"], deal_id)}


@router.post("/{deal_id}/send-quote")
async def send_quote(deal_id: str, ctx: dict = Depends(require_deals_manage)):
    from app.services.order_quotes import send_quote as send
    db = get_supabase()
    try:
        out = await send(db, ctx["tenant_id"], deal_id, user_id=ctx.get("user_id"), sender=_sender(ctx))
    except OrderError as e:
        raise _bad(e)
    return {**out, "order": orders_service.order_detail(db, ctx["tenant_id"], deal_id)}


class RefundItem(BaseModel):
    deal_item_id: str = Field(..., max_length=64)
    qty: int = Field(..., ge=1, le=100000)


class RefundIn(BaseModel):
    items: list[RefundItem] = Field(default_factory=list, max_length=60)
    mode: Literal["cancel", "full", "part"]
    amount_paise: int | None = Field(None, ge=100, le=10_000_000_00)
    method: Literal["razorpay", "cash", "upi", "bank_transfer"] | None = None
    reason: str = Field(..., min_length=1, max_length=200)


@router.post("/{deal_id}/refund")
async def refund(deal_id: str, payload: RefundIn, ctx: dict = Depends(require_deals_manage)):
    """Owner, or a role with "Refund orders" (deals.refund)."""
    from app.services.order_refunds import can_refund, refund as give_back
    if not can_refund(ctx):
        raise HTTPException(status_code=403, detail="Only the owner or a manager with Refund orders can do this")
    db = get_supabase()
    try:
        out = await give_back(db, ctx["tenant_id"], deal_id, mode=payload.mode, amount_paise=payload.amount_paise,
                              method=payload.method, reason=payload.reason, user_id=ctx.get("user_id"), sender=_sender(ctx),
                              items=[i.model_dump() for i in payload.items])
    except OrderError as e:
        raise _bad(e)
    return {**out, "order": orders_service.order_detail(db, ctx["tenant_id"], deal_id)}


class HandoverIn(BaseModel):
    handover: Literal["pickup", "courier"]


@router.patch("/{deal_id}/handover")
def set_handover(deal_id: str, payload: HandoverIn, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    try:
        deal = orders_service._load(db, tenant_id, deal_id)
    except OrderError:
        raise HTTPException(status_code=404, detail="Order not found")
    if deal.get("handover") == "taken":
        raise HTTPException(status_code=400, detail="The customer already took this order")
    db.table("deals").update({"handover": payload.handover}).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
    return orders_service.order_detail(db, tenant_id, deal_id)


class SendIn(BaseModel):
    kind: Literal["bill", "ready", "shipped", "delivered"]


@router.post("/{deal_id}/send")
async def send_update(deal_id: str, payload: SendIn, ctx: dict = Depends(require_deals_manage)):
    """Send (or send again) one update; when WhatsApp can't, the reply carries share_url."""
    db = get_supabase()
    try:
        orders_service._load(db, ctx["tenant_id"], deal_id)
    except OrderError:
        raise HTTPException(status_code=404, detail="Order not found")
    out = await orders_service.notify(db, ctx["tenant_id"], deal_id, payload.kind, user_id=ctx.get("user_id"), sender=_sender(ctx))
    return {**out, "order": orders_service.order_detail(db, ctx["tenant_id"], deal_id)}


class SharedIn(BaseModel):
    kind: Literal["bill", "ready", "shipped", "delivered", "reminder", "pay_link"]
    text: str = Field(..., max_length=2000)


@router.post("/{deal_id}/shared")
def shared(deal_id: str, payload: SharedIn, ctx: dict = Depends(require_deals_manage)):
    """Staff sent it from their own WhatsApp (Share on WhatsApp): keep it in Updates sent."""
    db = get_supabase()
    try:
        orders_service.log_shared(db, ctx["tenant_id"], deal_id, payload.kind, payload.text, ctx.get("user_id"))
    except OrderError:
        raise HTTPException(status_code=404, detail="Order not found")
    return orders_service.order_detail(db, ctx["tenant_id"], deal_id)


# ── The customer's bill page (public, by secret token) ────────────────────────

@public_router.get("/{token}")
def get_public_bill(token: str):
    bill = orders_service.public_bill(get_supabase(), token)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


def _bill_file_response(token: str, want_pdf: bool) -> Response:
    """The bill as WhatsApp carried it (shown in Anril's chat and openable by the customer)."""
    made = orders_service.bill_file(get_supabase(), token)
    if not made or (made[1] == "application/pdf") != want_pdf:
        raise HTTPException(status_code=404, detail="Bill not found")
    data, content_type, filename = made
    return Response(content=data, media_type=content_type, headers={
        "Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "private, max-age=300",
        "X-Robots-Tag": "noindex",
    })


@public_router.get("/{token}/picture.png")
def get_public_bill_picture(token: str):
    return _bill_file_response(token, want_pdf=False)


@public_router.get("/{token}/invoice.pdf")
def get_public_bill_pdf(token: str):
    return _bill_file_response(token, want_pdf=True)


@public_router.post("/{token}/accept")
async def accept_public_quote(token: str):
    """Accept quote from the quote page (works for a quote shared from a staff phone too)."""
    import re
    from app.services.order_quotes import accept_quote
    if not re.match(r"^[A-Za-z0-9_-]{16,64}$", token or ""):
        raise HTTPException(status_code=404, detail="Quote not found")
    db = get_supabase()
    rows = db.table("deals").select("id, tenant_id").eq("bill_token", token).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Quote not found")
    out = await accept_quote(db, rows[0]["tenant_id"], rows[0]["id"], via="page")
    return {"status": out["status"], "payment_link": out.get("payment_link"), "advance_paise": out.get("advance_paise", 0)}
