"""Deals: one row per sale attempt, every source (see
docs/superpowers/specs/2026-09-25-deals-crm-design.md). All stage and stock
rules live in services/deals.py; this module only validates input, scopes by
tenant and shapes responses."""
import logging
import re
from datetime import datetime, date, timedelta, timezone, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import deals as deals_service
from app.services import deals_reports
from app.services.deals import DealError, format_deal_number

logger = logging.getLogger(__name__)
router = APIRouter()
require_deals_view = require_permission("deals.view")
require_deals_manage = require_permission("deals.manage")

DEAL_SELECT = "*, leads(id, name, phone), deal_items(id, catalog_item_id, name, qty, unit_price_paise, gst_rate, line_total_paise), intake_sessions(last_activity_at, refund_needed)"
DEAL_NUMBER_RE = re.compile(r"^(?:d-?)?0*(\d+)$", re.IGNORECASE)


def _csv(value: str | None, allowed: list[str] | None, label: str) -> list[str]:
    """Parse a comma-separated list, validate values if allowed is provided, raise HTTPException 400 for unknowns."""
    if not value:
        return []
    items = [v.strip() for v in value.split(",")]
    # Only validate if allowed list is provided (non-None and non-empty)
    if allowed:
        allowed_set = set(allowed)
        for item in items:
            if item and item not in allowed_set:
                raise HTTPException(status_code=400, detail=f"Unknown {label}")
    return [item for item in items if item]


def _filtered(db, tenant_id: str, *, source=None, q=None, created_from=None, created_to=None,
              min_rupees=None, max_rupees=None, payment_method=None, product=None, attention=None,
              select=DEAL_SELECT, count=None):
    """Build a filtered query for deals. Returns the query object or None if a lookup proves no rows can exist.

    Args:
        source: comma-separated list of sources (validated against SOURCES)
        q: deal number match via DEAL_NUMBER_RE, else lead name/phone search
        created_from/created_to: YYYY-MM-DD strings, IST timezone
        min_rupees/max_rupees: rupee amounts (converted to paise)
        payment_method: comma-separated list of payment methods
        product: comma-separated list of exact deal_items names
        attention: comma-separated list of attention criteria (unpaid_3d, link_expiring, refund)
        select: columns to select
        count: PostgREST count parameter (e.g., "exact")

    Returns:
        Query object or None if no rows can match
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    query = db.table("deals").select(select, count=count).eq("tenant_id", tenant_id)

    # source filter
    if source:
        sources = _csv(source, deals_service.SOURCES, "source")
        if sources:
            query = query.in_("source", sources)

    # q filter (deal number or lead search)
    if q and q.strip():
        number_match = DEAL_NUMBER_RE.match(q.strip())
        if number_match:
            query = query.eq("deal_number", int(number_match.group(1)))
        else:
            lead_ids = _lead_ids_matching(db, tenant_id, q.strip())
            if not lead_ids:
                return None
            query = query.in_("lead_id", lead_ids)

    # created_from/created_to date window (IST)
    if created_from:
        try:
            d = date.fromisoformat(created_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date")
        dt = datetime.combine(d, time.min, IST)
        query = query.gte("created_at", dt.isoformat())

    if created_to:
        try:
            d = date.fromisoformat(created_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date")
        # created_to is inclusive, so filter < (to + 1 day)
        dt = datetime.combine(d + timedelta(days=1), time.min, IST)
        query = query.lt("created_at", dt.isoformat())

    # min/max rupees (convert to paise)
    if min_rupees is not None:
        query = query.gte("total_paise", min_rupees * 100)

    if max_rupees is not None:
        query = query.lte("total_paise", max_rupees * 100)

    # payment_method filter
    if payment_method:
        methods = _csv(payment_method, deals_service.PAYMENT_METHODS, "payment_method")
        if methods:
            query = query.in_("payment_method", methods)

    # product filter (via deal_items)
    if product:
        names = _csv(product, None, "product")  # Don't validate against a list; max 20 names
        if len(names) > 20:
            raise HTTPException(status_code=400, detail="Too many products")
        if names:
            deal_ids = (
                db.table("deal_items")
                .select("deal_id")
                .eq("tenant_id", tenant_id)
                .in_("name", names)
                .limit(2000)
                .execute()
            ).data or []
            if not deal_ids:
                return None
            ids = [d["deal_id"] for d in deal_ids]
            query = query.in_("id", ids)

    # attention filter (unpaid_3d, link_expiring, refund)
    if attention:
        attention_list = _csv(attention, ["unpaid_3d", "link_expiring", "refund"], "attention")
        now = datetime.now(timezone.utc)

        for attn in attention_list:
            if attn == "unpaid_3d":
                threshold = (now - timedelta(days=3)).isoformat()
                query = query.eq("stage", "awaiting_payment").lt("created_at", threshold)
            elif attn == "link_expiring":
                # link_expires_at between now and now+24h
                query = query.eq("stage", "awaiting_payment")
                query = query.gte("link_expires_at", now.isoformat())
                query = query.lte("link_expires_at", (now + timedelta(hours=24)).isoformat())
            elif attn == "refund":
                # Find intake_sessions with refund_needed=true
                sessions = (
                    db.table("intake_sessions")
                    .select("id")
                    .eq("tenant_id", tenant_id)
                    .eq("refund_needed", True)
                    .limit(2000)
                    .execute()
                ).data or []
                if not sessions:
                    return None
                session_ids = [s["id"] for s in sessions]
                query = query.in_("intake_session_id", session_ids)

    return query


def _session_fields(row: dict) -> dict:
    """The linked intake session's card fields, from the PostgREST embed in DEAL_SELECT (an
    object for this many-to-one link). Deals with no session (quotes, manual) have none."""
    embedded = row.get("intake_sessions")
    if isinstance(embedded, list):
        embedded = embedded[0] if embedded else None
    return embedded or {}


def _summary(row: dict) -> dict:
    items = row.get("deal_items") or []
    lead = row.get("leads") or {}
    session = _session_fields(row)
    return {
        "id": row["id"],
        "deal_number": row["deal_number"],
        "deal_label": format_deal_number(row["deal_number"]),
        "stage": row["stage"],
        "source": row["source"],
        "total_paise": row["total_paise"],
        "payment_method": row.get("payment_method"),
        "payment_link": row.get("payment_link"),
        "link_expires_at": row.get("link_expires_at"),
        "last_activity_at": session.get("last_activity_at"),
        "refund_needed": bool(session.get("refund_needed")),
        "created_at": row["created_at"],
        "won_at": row.get("won_at"),
        "lost_at": row.get("lost_at"),
        "lost_reason": row.get("lost_reason"),
        "lead": {"id": row["lead_id"], "name": lead.get("name"), "phone": lead.get("phone")},
        "item_summary": ", ".join(f"{i['name']} ×{i['qty']}" for i in items),
        "item_count": len(items),
    }


def _full(row: dict, db, tenant_id: str) -> dict:
    intake_answers = None
    if row.get("intake_session_id"):
        session = (
            db.table("intake_sessions").select("collected_data")
            .eq("id", row["intake_session_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        )
        intake_answers = (session.data or {}).get("collected_data") if session else None
    return {
        **_summary(row),
        "items": row.get("deal_items") or [],
        "notes": row.get("notes"),
        "razorpay_payment_id": row.get("razorpay_payment_id"),
        "intake_session_id": row.get("intake_session_id"),
        "intake_answers": intake_answers,
    }


def _load_deal(db, tenant_id: str, deal_id: str) -> dict:
    res = db.table("deals").select(DEAL_SELECT).eq("id", deal_id).eq("tenant_id", tenant_id).maybe_single().execute()
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    return res.data


def _lead_ids_matching(db, tenant_id: str, q: str) -> list[str]:
    # PostgREST or() filter: strip the characters that would break its syntax.
    safe = re.sub(r"[,()*%]", "", q)[:60]
    if not safe:
        return []
    rows = (
        db.table("leads").select("id").eq("tenant_id", tenant_id)
        .or_(f"name.ilike.%{safe}%,phone.ilike.%{safe}%").limit(200).execute()
    ).data or []
    return [r["id"] for r in rows]


@router.get("/summary")
def get_summary(
    source: str | None = None,
    q: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    min_rupees: int | None = Query(None, ge=0),
    max_rupees: int | None = Query(None, ge=0),
    payment_method: str | None = None,
    product: str | None = None,
    attention: str | None = None,
    ctx: dict = Depends(require_deals_view),
):
    """Summary of deals matching the filters: per-stage counts/totals, unpaid_3d count/total, and distinct products."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    # Get filtered deals (excluding stage/sort/page)
    query = _filtered(
        db, tenant_id, source=source, q=q, created_from=created_from, created_to=created_to,
        min_rupees=min_rupees, max_rupees=max_rupees, payment_method=payment_method,
        product=product, attention=attention, select="stage, total_paise, created_at", count=None
    )

    if query is None:
        # No rows can match
        result = {
            "stages": {stage: {"count": 0, "total_paise": 0} for stage in deals_service.STAGES},
            "unpaid_3d": {"count": 0, "total_paise": 0},
            "products": [],
        }
    else:
        rows = query.limit(5000).execute().data or []

        # Compute per-stage counts and totals
        stages_data = {stage: {"count": 0, "total_paise": 0} for stage in deals_service.STAGES}
        for row in rows:
            stage = row.get("stage")
            if stage in stages_data:
                stages_data[stage]["count"] += 1
                stages_data[stage]["total_paise"] += row.get("total_paise", 0)

        # Compute unpaid_3d (awaiting_payment with created_at < 3 days ago)
        now = datetime.now(timezone.utc)
        three_days_ago = now - timedelta(days=3)
        unpaid_3d_count = 0
        unpaid_3d_total = 0
        for row in rows:
            if row.get("stage") == "awaiting_payment":
                created_str = row.get("created_at")
                if created_str:
                    # Parse ISO string (handles both with and without offset)
                    created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if created < three_days_ago:
                        unpaid_3d_count += 1
                        unpaid_3d_total += row.get("total_paise", 0)

        result = {
            "stages": stages_data,
            "unpaid_3d": {"count": unpaid_3d_count, "total_paise": unpaid_3d_total},
            "products": [],
        }

    # Get all distinct product names for the tenant (ignores filters)
    products_data = (
        db.table("deal_items")
        .select("name")
        .eq("tenant_id", tenant_id)
        .limit(2000)
        .execute()
    ).data or []
    products_set = sorted(set(p.get("name") for p in products_data if p.get("name")))[:200]
    result["products"] = products_set

    return result


@router.get("")
def list_deals(
    stage: str | None = None,
    source: str | None = None,
    q: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    min_rupees: int | None = Query(None, ge=0),
    max_rupees: int | None = Query(None, ge=0),
    payment_method: str | None = None,
    product: str | None = None,
    attention: str | None = None,
    sort: str = Query("created_at"),
    dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    ctx: dict = Depends(require_deals_view),
):
    """List deals matching all filters, with pagination and sorting."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    # Validate stage
    if stage:
        if stage not in deals_service.STAGES:
            raise HTTPException(status_code=400, detail="Unknown stage")

    # Validate sort
    valid_sorts = {"created_at", "total_paise", "deal_number"}
    if sort not in valid_sorts:
        raise HTTPException(status_code=400, detail="Unknown sort")

    # Validate dir
    if dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Unknown dir")

    # Build filtered query
    query = _filtered(
        db, tenant_id, source=source, q=q, created_from=created_from, created_to=created_to,
        min_rupees=min_rupees, max_rupees=max_rupees, payment_method=payment_method,
        product=product, attention=attention, select=DEAL_SELECT, count="exact"
    )

    if query is None:
        return {"data": [], "total": 0, "page": page, "limit": limit}

    # Apply stage filter
    if stage:
        query = query.eq("stage", stage)

    # Apply sorting and pagination
    # id breaks ties, so equal values (many ₹1 deals) never repeat or vanish across pages.
    query = query.order(sort, desc=(dir == "desc")).order("id", desc=(dir == "desc"))
    query = query.range((page - 1) * limit, page * limit - 1)

    result = query.execute()
    rows = result.data or []
    total = result.count or 0

    return {
        "data": [_summary(r) for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/stats")
def deal_stats(month: str, source: str | None = None, ctx: dict = Depends(require_deals_view)):
    sources = _csv(source, deals_service.SOURCES, "source") or None
    return deals_reports.monthly_stats(ctx["tenant_id"], month, sources=sources)


@router.get("/active-months")
def deal_active_months(ctx: dict = Depends(require_deals_view)):
    return {"months": deals_reports.active_months(ctx["tenant_id"])}


@router.get("/export")
def export_deals(
    month: str,
    format: Literal["xlsx", "csv"] = "xlsx",
    ctx: dict = Depends(require_deals_view),
):
    content, media_type, filename = deals_reports.sales_register(ctx["tenant_id"], month, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/by-lead/{lead_id}")
def deals_for_lead(lead_id: str, ctx: dict = Depends(require_deals_view)):
    db = get_supabase()
    rows = (
        db.table("deals").select(DEAL_SELECT).eq("tenant_id", ctx["tenant_id"]).eq("lead_id", lead_id)
        .order("created_at", desc=True).limit(50).execute()
    ).data or []
    return {"data": [_summary(r) for r in rows]}


# ------------------------------------------------------------ Chats: Record payment

@router.get("/record-payment/options")
def record_payment_options(lead_id: str, ctx: dict = Depends(require_deals_manage)):
    """What the Record payment pop-up needs besides the catalogue and the team: the GST
    setup, and the products this customer was already quoted (suggested first)."""
    from app.services.business_details import charges_gst, get_business_details, prices_include_gst
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    quoted = (
        db.table("deals").select("id").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
        .neq("stage", "lost").order("created_at", desc=True).limit(5).execute()
    ).data or []
    suggested: list[str] = []
    if quoted:
        items = (
            db.table("deal_items").select("catalog_item_id").eq("tenant_id", tenant_id)
            .in_("deal_id", [d["id"] for d in quoted]).execute()
        ).data or []
        for it in items:
            item_id = it.get("catalog_item_id")
            if item_id and item_id not in suggested:
                suggested.append(item_id)
    details = get_business_details(tenant_id, db) or {}
    return {
        "prices_include_gst": prices_include_gst(tenant_id, db),
        "gstin_set": bool((details.get("gstin") or "").strip()),
        # Only a shop registered for GST (not composition / none) can send a GST invoice.
        "gst_registered": bool(charges_gst(tenant_id, db)),
        "suggested_item_ids": suggested[:3],
        # What this order will most likely be called (the counter is only taken on save).
        "next_order_label": _next_order_label(db, tenant_id),
    }


def _next_order_label(db, tenant_id: str) -> str | None:
    try:
        row = (db.table("deal_counters").select("last_number").eq("tenant_id", tenant_id).limit(1).execute()).data or []
        return deals_service.format_deal_number(int((row[0].get("last_number") if row else 0) or 0) + 1)
    except Exception:
        return None


class RecordPaymentIn(BaseModel):
    lead_id: str = Field(..., max_length=64)
    method: Literal["link", "cash", "upi", "card"]
    amount_paise: int = Field(..., ge=100, le=10_000_000_00)
    item_ids: list[str] = Field(default_factory=list, max_length=10)
    sold_by: str | None = Field(None, max_length=64)
    # After a paid-now record, send the order's bill/invoice on WhatsApp (same as Orders > Send bill).
    send_gst_invoice: bool = False


def record_payment_lines(amount_paise: int, items: list[dict]) -> list[dict]:
    """Deal lines whose prices add up to the typed amount. Each product keeps its catalogue
    price except the last, which takes the difference (a discount or an extra); with no
    product picked it is one "Payment" line."""
    if not items:
        return [{"name": "Payment", "qty": 1, "unit_price_paise": amount_paise}]
    lines = [
        {"catalog_item_id": it["id"], "name": it["name"], "qty": 1, "unit_price_paise": int(it.get("price_paise") or 0)}
        for it in items
    ]
    others = sum(li["unit_price_paise"] for li in lines[:-1])
    last = amount_paise - others
    if last < 0:
        raise HTTPException(status_code=400, detail="The amount is less than the other products' prices. Remove a product or raise the amount.")
    lines[-1]["unit_price_paise"] = last
    return lines


@router.post("/record-payment")
async def record_payment(payload: RecordPaymentIn, ctx: dict = Depends(require_deals_manage)):
    """Chats > Record payment: a paid order (cash / UPI / card), or a Razorpay link sent on
    WhatsApp that turns the order paid by itself when the customer pays."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    lead = (
        db.table("leads").select("id, source").eq("id", payload.lead_id).eq("tenant_id", tenant_id)
        .is_("deleted_at", "null").maybe_single().execute()
    )
    if not lead or not lead.data:
        raise HTTPException(status_code=404, detail="Contact not found")
    if payload.sold_by:
        caller = db.table("callers").select("id").eq("id", payload.sold_by).eq("tenant_id", tenant_id).limit(1).execute()
        if not caller.data:
            raise HTTPException(status_code=400, detail="That teammate isn't on your team")
    items: list[dict] = []
    if payload.item_ids:
        ids = list(dict.fromkeys(payload.item_ids))
        rows = (
            db.table("catalog_items").select("id, name, price_paise").eq("tenant_id", tenant_id).in_("id", ids).execute()
        ).data or []
        by_id = {r["id"]: r for r in rows}
        if len(by_id) != len(ids):
            raise HTTPException(status_code=400, detail="Product not found")
        items = [by_id[i] for i in ids]
    lines = record_payment_lines(payload.amount_paise, items)
    paid_now = payload.method != "link"
    if payload.send_gst_invoice:
        from app.services.business_details import charges_gst
        if not charges_gst(tenant_id, db):
            raise HTTPException(status_code=400, detail="Your shop doesn't charge GST, so there is no GST invoice to send.")
    try:
        result = await deals_service.create_deal(
            tenant_id, payload.lead_id, lines,
            "whatsapp" if (lead.data.get("source") or "whatsapp") not in ("instagram", "facebook", "telegram") else "manual",
            "won" if paid_now else "awaiting_payment",
            payment_method=payload.method if paid_now else None,
            created_by=ctx.get("user_id"), send_link=not paid_now, db=db,
        )
    except DealError as e:
        raise HTTPException(status_code=400, detail=str(e))
    deal_id = result["deal"]["id"]
    if payload.sold_by:
        db.table("deals").update({"sold_by": payload.sold_by}).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
    invoice = None
    if payload.send_gst_invoice and paid_now:
        invoice = await _send_paid_invoice(db, tenant_id, deal_id, result["deal"], payload.method, ctx)
    elif payload.send_gst_invoice:
        # A link order: the Razorpay paid webhook sends the bill once the customer pays.
        db.table("deals").update({"send_invoice_on_paid": True}).eq("id", deal_id).eq("tenant_id", tenant_id).execute()
        invoice = {"sent": False, "reason": "on_paid"}
    deal = _full(_load_deal(db, tenant_id, deal_id), db, tenant_id)
    return {
        "deal": deal,
        "payment_link": result["payment_link"],
        "message_sent": result["message_sent"],
        "stock_warnings": result["stock_warnings"],
        "invoice": invoice,
    }


async def _send_paid_invoice(db, tenant_id: str, deal_id: str, deal: dict, method: str, ctx: dict) -> dict:
    """Give the just-paid order its invoice number, then send its bill the way Orders > Send bill does
    (orders.notify, kind "bill"). create_deal already wrote the payment row. Never raises: the payment
    is already saved. Returns {"sent": bool, "reason": str | None}."""
    from app.services import orders as orders_service
    try:
        orders_service.ensure_invoice(db, tenant_id, deal_id)
        sender = {"sent_by_user_id": ctx["user_id"]} if ctx.get("user_id") else {}
        out = await orders_service.notify(db, tenant_id, deal_id, "bill", user_id=ctx.get("user_id"), sender=sender)
        return {"sent": bool(out.get("sent")), "reason": out.get("reason")}
    except Exception as e:
        logger.warning(f"Record payment: invoice for deal {deal_id} didn't go: {e}")
        return {"sent": False, "reason": "send_failed"}


@router.get("/{deal_id}")
def get_deal(deal_id: str, ctx: dict = Depends(require_deals_view)):
    db = get_supabase()
    return _full(_load_deal(db, ctx["tenant_id"], deal_id), db, ctx["tenant_id"])


class DealLineIn(BaseModel):
    catalog_item_id: str | None = None
    name: str = Field("", max_length=200)
    qty: int = Field(1, ge=1, le=100000)
    unit_price_paise: int | None = Field(None, ge=0)


class NewDealIn(BaseModel):
    lead_id: str | None = None
    phone: str | None = Field(None, max_length=32)
    name: str | None = Field(None, max_length=120)
    items: list[DealLineIn] = Field(..., min_length=1, max_length=50)
    source: Literal["call", "walk_in", "manual"]
    stage: Literal["won", "awaiting_payment", "quoted"]
    payment_method: Literal["razorpay", "cash", "upi", "card", "bank_transfer", "other"] | None = None
    notes: str | None = Field(None, max_length=2000)


def _resolve_lead(db, tenant_id: str, payload: NewDealIn) -> str:
    if bool(payload.lead_id) == bool(payload.phone):
        raise HTTPException(status_code=400, detail="Give either an existing contact or a phone number")
    if payload.lead_id:
        lead = db.table("leads").select("id").eq("id", payload.lead_id).eq("tenant_id", tenant_id).maybe_single().execute()
        if not lead or not lead.data:
            raise HTTPException(status_code=404, detail="Contact not found")
        return payload.lead_id
    from app.services.inbound_lead import create_inbound_lead
    lead_id = create_inbound_lead(
        tenant_id, payload.phone, "manual", name=(payload.name or "").strip() or None,
        opt_in_source="manual", db=db,
    )
    if not lead_id:
        raise HTTPException(status_code=400, detail="That phone number doesn't look valid")
    return lead_id


@router.post("")
async def create_deal(payload: NewDealIn, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    lead_id = _resolve_lead(db, tenant_id, payload)
    try:
        result = await deals_service.create_deal(
            tenant_id, lead_id, [li.model_dump() for li in payload.items], payload.source, payload.stage,
            payment_method=payload.payment_method, notes=payload.notes, created_by=ctx.get("user_id"),
            send_link=payload.stage == "awaiting_payment", db=db,
        )
    except DealError as e:
        raise HTTPException(status_code=400, detail=str(e))
    deal = _full(_load_deal(db, tenant_id, result["deal"]["id"]), db, tenant_id)
    return {
        "deal": deal,
        "payment_link": result["payment_link"],
        "message_sent": result["message_sent"],
        "stock_warnings": result["stock_warnings"],
    }


class StageIn(BaseModel):
    stage: Literal["won", "lost"]
    payment_method: Literal["razorpay", "cash", "upi", "card", "bank_transfer", "other"] | None = None
    lost_reason: str | None = Field(None, max_length=300)


@router.patch("/{deal_id}/stage")
def update_stage(deal_id: str, payload: StageIn, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    _load_deal(db, tenant_id, deal_id)
    if payload.stage == "won":
        result = deals_service.mark_won(
            tenant_id, deal_id, payment_method=payload.payment_method or "cash",
            created_by=ctx.get("user_id"), db=db,
        )
    else:
        result = deals_service.mark_lost(
            tenant_id, deal_id, payload.lost_reason or "Marked lost", created_by=ctx.get("user_id"), db=db,
        )
    if result is None:
        raise HTTPException(status_code=409, detail=f"Deal is already {payload.stage}")
    return {"deal": _full(_load_deal(db, tenant_id, deal_id), db, tenant_id), "stock_warnings": result["stock_warnings"]}


@router.post("/{deal_id}/send-link")
async def send_link(deal_id: str, ctx: dict = Depends(require_deals_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    _load_deal(db, tenant_id, deal_id)
    try:
        result = await deals_service.send_payment_link(tenant_id, deal_id, db=db)
    except DealError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"payment_link": result["payment_link"], "message_sent": result["message_sent"]}
