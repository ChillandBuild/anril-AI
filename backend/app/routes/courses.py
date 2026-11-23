"""Education: Courses & batches + fee instalments (/api/v1/courses). Services: services/courses.py, services/fee_plans.py.

Permissions: catalog.view to see, catalog.manage to change courses, batches and the waitlist; money (the batch fee,
fee plans, receipts) needs deals.view and is left out of answers without it; enrolling, changing a fee plan,
marking a part paid and the fee reminders need deals.manage. A telecaller sees only students assigned to them.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_permission
from app.services import courses as svc
from app.services import fee_plans as fees
from app.services.courses import CourseError
from app.services.fee_plans import FeeError

logger = logging.getLogger(__name__)

router = APIRouter()

view = require_permission("catalog.view")
manage = require_permission("catalog.manage")
money_view = require_permission("deals.view")
money_manage = require_permission("deals.manage")


@contextmanager
def _errors():
    """CourseError / FeeError / BookingError -> the HTTP error with its plain-words message."""
    from app.services.booking_setup import BookingError
    try:
        yield
    except (CourseError, FeeError, BookingError) as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        # Migration 330 not applied yet: say so plainly instead of a 500.
        text = str(e).lower()
        if any(m in text for m in ("42p01", "pgrst205", "does not exist", "schema cache", "could not find the table")):
            raise HTTPException(status_code=404, detail="Courses aren't set up for this business yet") from None
        raise


def _money(ctx: dict) -> bool:
    return _has_permission(ctx, "deals.view")


def _caller(ctx: dict) -> str | None:
    """A telecaller sees only their own students. A caller with no caller id sees none (the empty id matches
    no lead), never everyone."""
    if ctx.get("role") != "caller":
        return None
    return ctx.get("caller_id") or ""


class CourseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = Field(None, max_length=2000)
    price_paise: Optional[int] = Field(None, ge=0)


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, max_length=120)
    starts_on: Optional[str] = Field(None, max_length=10)
    timing_text: Optional[str] = Field(None, max_length=200)
    mode: Optional[Literal["online", "offline", "both"]] = None
    seats_total: Optional[int] = Field(None, ge=0, le=10000)
    fee_paise: Optional[int] = Field(None, ge=0)
    teacher_name: Optional[str] = Field(None, max_length=120)
    status: Optional[Literal["open", "full", "closed"]] = None


class PartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_on: str = Field(max_length=10)
    amount_paise: int = Field(gt=0)


class EnrolIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, max_length=120)
    phone: str = Field(min_length=1, max_length=30)
    parent_phone: Optional[str] = Field(None, max_length=30)
    parts: Optional[list[PartIn]] = Field(None, max_length=24)
    instalments: Optional[int] = Field(None, ge=1, le=24)
    first_due_on: Optional[str] = Field(None, max_length=10)


class WaitlistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=1, max_length=30)
    name: Optional[str] = Field(None, max_length=120)


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[PartIn] = Field(min_length=1, max_length=24)


class PayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["cash", "upi", "card", "bank_transfer", "other"] = "cash"


class RemindersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


# ================================================================ courses and batches

@router.get("")
def list_courses(ctx: dict = Depends(view)):
    with _errors():
        courses = svc.list_courses(get_supabase(), ctx["tenant_id"], show_money=_money(ctx))
    return {"courses": courses, "can_see_money": _money(ctx)}


@router.post("")
async def create_course(body: CourseIn, ctx: dict = Depends(manage)):
    db = get_supabase()
    data = body.model_dump(exclude_unset=True)
    if not _money(ctx):
        data.pop("price_paise", None)
    with _errors():
        item = await asyncio.to_thread(svc.create_course, db, ctx["tenant_id"], data)
    await svc.index_course(db, ctx["tenant_id"], item)
    return {"id": item["id"], "name": item["name"]}


@router.patch("/{course_id}")
async def update_course(course_id: str, body: CourseIn, ctx: dict = Depends(manage)):
    db = get_supabase()
    data = body.model_dump(exclude_unset=True)
    if not _money(ctx):
        data.pop("price_paise", None)
    with _errors():
        item = await asyncio.to_thread(svc.update_course, db, ctx["tenant_id"], course_id, data)
    await svc.index_course(db, ctx["tenant_id"], item)
    return {"id": item["id"], "name": item["name"]}


@router.post("/{course_id}/batches")
def create_batch(course_id: str, body: BatchIn, ctx: dict = Depends(manage)):
    with _errors():
        row = svc.create_batch(get_supabase(), ctx["tenant_id"], course_id, body.model_dump(exclude_unset=True),
                               allow_fee=_money(ctx))
    svc.clear_cache(ctx["tenant_id"])
    return {"id": row["id"]}


@router.patch("/batches/{batch_id}")
def update_batch(batch_id: str, body: BatchIn, ctx: dict = Depends(manage)):
    with _errors():
        row = svc.update_batch(get_supabase(), ctx["tenant_id"], batch_id, body.model_dump(exclude_unset=True),
                               allow_fee=_money(ctx))
    svc.clear_cache(ctx["tenant_id"])
    return {"id": row["id"]}


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str, ctx: dict = Depends(view)):
    db = get_supabase()
    with _errors():
        out = svc.batch_detail(db, ctx["tenant_id"], batch_id, show_money=_money(ctx), caller_id=_caller(ctx))
    from app.services.call_rules import phone_mask_for
    mask = phone_mask_for(db, ctx["tenant_id"], ctx)  # fails closed for telecallers
    if mask and isinstance(out, dict):
        for key in ("students", "waitlist"):
            for row in out.get(key) or []:
                for field in ("phone", "parent_phone"):
                    if row.get(field):
                        row[field] = mask(row[field])
    return out


# ================================================================ students, waitlist

@router.post("/batches/{batch_id}/enrol")
async def enrol(batch_id: str, body: EnrolIn, ctx: dict = Depends(money_manage)):
    if not _has_permission(ctx, "catalog.view"):
        raise HTTPException(status_code=403, detail="You need access to the catalogue to enrol a student")
    with _errors():
        out = await svc.enrol_student(
            get_supabase(), ctx["tenant_id"], batch_id, phone=body.phone, name=body.name,
            parent_phone=body.parent_phone, parts=[p.model_dump() for p in body.parts] if body.parts else None,
            instalments=body.instalments, first_due_on=body.first_due_on, created_by=ctx.get("user_id"))
    svc.clear_cache(ctx["tenant_id"])
    return out


@router.post("/enrolments/{enrolment_id}/drop")
def drop(enrolment_id: str, ctx: dict = Depends(money_manage)):
    with _errors():
        out = svc.drop_enrolment(get_supabase(), ctx["tenant_id"], enrolment_id, created_by=ctx.get("user_id"))
    svc.clear_cache(ctx["tenant_id"])
    return out


@router.post("/batches/{batch_id}/waitlist")
def join_waitlist(batch_id: str, body: WaitlistIn, ctx: dict = Depends(manage)):
    with _errors():
        row = svc.join_waitlist(get_supabase(), ctx["tenant_id"], batch_id, body.phone, body.name)
    return {"id": row["id"]}


@router.delete("/waitlist/{waitlist_id}")
def leave_waitlist(waitlist_id: str, ctx: dict = Depends(manage)):
    with _errors():
        svc.leave_waitlist(get_supabase(), ctx["tenant_id"], waitlist_id)
    return {"ok": True}


# ================================================================ fee plans, receipts, reminders

@router.put("/enrolments/{enrolment_id}/fee-plan")
def put_fee_plan(enrolment_id: str, body: PlanIn, ctx: dict = Depends(money_manage)):
    db = get_supabase()
    with _errors():
        if not svc.is_uuid(enrolment_id):
            raise CourseError("Student not found", 404)
        rows = (db.table("batch_enrolments").select("deal_id").eq("id", enrolment_id).eq("tenant_id", ctx["tenant_id"])
                .eq("status", "active").limit(1).execute()).data or []
        if not rows or not rows[0].get("deal_id"):
            raise CourseError("Student not found", 404)
        plan = fees.create_plan(db, ctx["tenant_id"], rows[0]["deal_id"], [p.model_dump() for p in body.parts])
        return fees.plan_view(db, ctx["tenant_id"], plan)


@router.post("/fee-plans/{plan_id}/parts/{part_index}/pay")
async def pay_part(plan_id: str, part_index: int, body: PayIn, ctx: dict = Depends(money_manage)):
    with _errors():
        if not svc.is_uuid(plan_id):
            raise CourseError("Fee plan not found", 404)
        return await fees.mark_part_paid_async(get_supabase(), ctx["tenant_id"], plan_id, part_index,
                                               method=body.method, by_user_id=ctx.get("user_id"))


@router.get("/receipts/{payment_id}")
def get_receipt(payment_id: str, ctx: dict = Depends(money_view)):
    with _errors():
        if not svc.is_uuid(payment_id):
            raise CourseError("Receipt not found", 404)
        return fees.receipt(get_supabase(), ctx["tenant_id"], payment_id)


@router.get("/fee-reminders")
def get_reminders(ctx: dict = Depends(money_view)):
    return fees.reminders_state(get_supabase(), ctx["tenant_id"])


@router.put("/fee-reminders")
def put_reminders(body: RemindersIn, ctx: dict = Depends(money_manage)):
    with _errors():
        return fees.set_reminders(get_supabase(), ctx["tenant_id"], body.enabled)


@router.post("/fee-reminders/template")
async def submit_reminder_template(ctx: dict = Depends(money_manage)):
    with _errors():
        return await fees.submit_template(get_supabase(), ctx["tenant_id"], ctx)


# ================================================================ free demo class

@router.post("/demo-class")
def demo_class(ctx: dict = Depends(manage)):
    if not _has_permission(ctx, "bookings.manage"):
        raise HTTPException(status_code=403, detail="You need Bookings access to set up the demo class")
    with _errors():
        out = svc.ensure_demo_service(get_supabase(), ctx["tenant_id"])
    svc.clear_cache(ctx["tenant_id"])
    return out
