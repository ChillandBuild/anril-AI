"""Education: fee instalments (migration 330).

A fee plan splits one order's fee into parts [{due_on, amount_paise}] that add up to the order total.
Money itself is never kept here: "Mark part paid" calls deals.record_payment, so Orders & payments stays the
one place money lives (the last part paid makes the order Paid). This file keeps which part is paid and its receipt.

Fee reminders (send_fee_reminders, daily 10:00 IST): the WhatsApp template `fee_reminder` goes out 3 days before a
part is due, on the day, and 3 days late (each with a one-day catch-up if a run was missed). It is OFF until the
template is approved AND the owner switches it on. Never to someone who opted out / said stop / is blocked.
After the late reminder the student goes to Call IQ (customer_calling.send_to_calling, reason "fee_late").
Claim-before-send: a fee_plan_reminders row (unique per plan, part, kind) is inserted BEFORE the send, so two
overlapping runs never both send it; a send that raised deletes the row so the next run can try again; one with no message id keeps it (never twice).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MAX_PARTS = 24
SETTING_KEY = "fee_reminders_enabled"
PAY_METHODS = ("cash", "upi", "card", "bank_transfer", "other")

FEE_TEMPLATE = {
    "name": "fee_reminder",
    "body": ("Hi {{1}}, a fee reminder from {{2}}. {{3}} for {{4}} is due on {{5}}. "
             "Please pay it soon, or reply here and we will help."),
    "examples": ["Ravi", "Bright Academy", "Rs 5,000", "Python batch", "28 Nov"],
}


class FeeError(Exception):
    """Plain-words reason; safe to show to the person."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def _io(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def _rupees(paise: int) -> str:
    paise = int(paise or 0)
    return f"₹{paise // 100:,}" if paise % 100 == 0 else f"₹{paise / 100:,.2f}"


def _day(value, label: str = "Due date") -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise FeeError(f"{label}: pick a real date")


def day_text(d: date) -> str:
    return f"{d.day} {d:%b}"


# ───────────────────────────────────────────────────────────── the parts

def split_parts(total_paise: int, count: int, first_due: date, every_days: int = 30) -> list[dict]:
    """Equal parts, one every `every_days` from first_due. Any leftover paise goes on the first part."""
    count = max(1, min(int(count), MAX_PARTS))
    total = int(total_paise)
    base, extra = divmod(total, count)
    return [{"due_on": (first_due + timedelta(days=every_days * i)).isoformat(),
             "amount_paise": base + (extra if i == 0 else 0)} for i in range(count)]


def clean_parts(parts, total_paise: int) -> list[dict]:
    """Validated parts sorted by date. They must add up to the order total."""
    if not isinstance(parts, (list, tuple)) or not 1 <= len(parts) <= MAX_PARTS:
        raise FeeError(f"A fee plan has 1 to {MAX_PARTS} parts")
    out = []
    for p in parts:
        if not isinstance(p, dict):
            raise FeeError("Each part needs a due date and an amount")
        try:
            amount = int(p.get("amount_paise"))
        except (TypeError, ValueError):
            raise FeeError("Each part needs an amount")
        if amount <= 0:
            raise FeeError("Each part must be more than ₹0")
        out.append({"due_on": _day(p.get("due_on")).isoformat(), "amount_paise": amount})
    out.sort(key=lambda p: p["due_on"])
    if sum(p["amount_paise"] for p in out) != int(total_paise):
        raise FeeError(f"The parts add up to {_rupees(sum(p['amount_paise'] for p in out))} "
                       f"but the fee is {_rupees(total_paise)}")
    return out


def _deal(db, tenant_id: str, deal_id: str) -> dict:
    rows = (db.table("deals").select("*").eq("id", deal_id).eq("tenant_id", tenant_id).limit(1).execute()).data or []
    if not rows:
        raise FeeError("Order not found", 404)
    return rows[0]


def fetch_all(make_query, page: int = 1000) -> list[dict]:
    """Every row of a query, page by page (PostgREST returns at most 1000 rows per request).
    make_query() builds a fresh query; rows are read in id order so no row is skipped or repeated."""
    rows: list[dict] = []
    for start in range(0, 200_000, page):
        got = make_query().order("id").range(start, start + page - 1).execute().data or []
        rows.extend(got)
        if len(got) < page:
            break
    return rows


def covered_parts(parts: list[dict], plan_paid: dict[int, int], deal_paid_paise: int) -> set[int]:
    """Indexes of parts that count as paid. A part is paid when "Mark part paid" recorded it, or when money
    was put on the order elsewhere (Orders page, a Razorpay link): money beyond what the plan itself recorded
    covers the unpaid parts in order, earliest first."""
    paid = set(plan_paid)
    extra = max(int(deal_paid_paise or 0) - sum(plan_paid.values()), 0)
    for i, part in enumerate(parts):
        if i in paid:
            continue
        amount = int(part.get("amount_paise") or 0)
        if amount > 0 and extra >= amount:
            paid.add(i)
            extra -= amount
    return paid


def get_plan(db, tenant_id: str, *, deal_id: str | None = None, plan_id: str | None = None) -> dict | None:
    q = db.table("fee_plans").select("*").eq("tenant_id", tenant_id)
    q = q.eq("deal_id", deal_id) if deal_id else q.eq("id", plan_id)
    rows = q.limit(1).execute().data or []
    return rows[0] if rows else None


def _payments(db, tenant_id: str, plan_id: str) -> dict[int, dict]:
    rows = (db.table("fee_plan_payments").select("*").eq("tenant_id", tenant_id).eq("fee_plan_id", plan_id)
            .execute()).data or []
    return {int(r["part_index"]): r for r in rows}


def create_plan(db, tenant_id: str, deal_id: str, parts) -> dict:
    """Make the plan for an order, or replace it while no part is paid."""
    deal = _deal(db, tenant_id, deal_id)
    if deal.get("stage") == "lost":
        raise FeeError("This order is cancelled")
    clean = clean_parts(parts, int(deal.get("total_paise") or 0))
    existing = get_plan(db, tenant_id, deal_id=deal_id)
    if existing:
        if _payments(db, tenant_id, existing["id"]):
            raise FeeError("A part is already paid, so the plan cannot be changed")
        db.table("fee_plans").update({"parts": clean}).eq("id", existing["id"]).eq("tenant_id", tenant_id).execute()
        _forget_reminders(db, tenant_id, existing["id"], existing.get("parts") or [], clean)
        return {**existing, "parts": clean}
    return db.table("fee_plans").insert({"tenant_id": tenant_id, "deal_id": deal_id, "parts": clean}).execute().data[0]


def _forget_reminders(db, tenant_id: str, plan_id: str, old: list[dict], new: list[dict]) -> None:
    """A part whose due date changed (or that is new) may be reminded again for its new date."""
    try:
        for i in range(max(len(old), len(new))):
            same = i < len(old) and i < len(new) and str(old[i].get("due_on"))[:10] == str(new[i].get("due_on"))[:10]
            if not same:
                db.table("fee_plan_reminders").delete().eq("tenant_id", tenant_id).eq("fee_plan_id", plan_id) \
                    .eq("part_index", i).execute()
    except Exception as e:
        logger.warning("fee plan %s: old reminders not cleared: %s", plan_id, e)


def _user_names(db, tenant_id: str, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    try:
        rows = db.table("tenant_users").select("user_id, full_name").eq("tenant_id", tenant_id).execute().data or []
        return {str(r["user_id"]): r.get("full_name") or "Team member" for r in rows if str(r["user_id"]) in ids}
    except Exception:
        return {}


def plan_view(db, tenant_id: str, plan: dict, deal: dict | None = None) -> dict:
    """The plan with each part's paid state, for the course page. Parts covered by money recorded on the order
    itself (Orders page, a pay link) show as paid too, with no receipt (on_order true)."""
    paid = _payments(db, tenant_id, plan["id"])
    if deal is None:
        try:
            deal = _deal(db, tenant_id, plan["deal_id"])
        except FeeError:
            deal = {}
    names = _user_names(db, tenant_id, {str(p["by_user_id"]) for p in paid.values() if p.get("by_user_id")})
    today = datetime.now(IST).date()
    plan_parts = plan.get("parts") or []
    done = covered_parts(plan_parts, {i: int(p["paid_paise"]) for i, p in paid.items()}, int((deal or {}).get("paid_paise") or 0))
    parts = []
    for i, part in enumerate(plan_parts):
        pay = paid.get(i)
        due = _day(part["due_on"])
        parts.append({
            "index": i, "due_on": part["due_on"], "amount_paise": int(part["amount_paise"]),
            "paid": i in done, "late": i not in done and due < today, "on_order": i in done and not pay,
            "payment_id": pay["id"] if pay else None, "paid_at": pay.get("paid_at") if pay else None,
            "receipt_no": pay["receipt_no"] if pay else None, "method": pay["method"] if pay else None,
            "by_name": names.get(str(pay.get("by_user_id"))) if pay else None,
        })
    return {"id": plan["id"], "deal_id": plan["deal_id"], "parts": parts,
            "paid_paise": sum(p["amount_paise"] for p in parts if p["paid"]),
            "total_paise": sum(p["amount_paise"] for p in parts)}


# ───────────────────────────────────────────────────────────── mark a part paid

_OVER = "This order has less left to pay than this part. Fix the plan, or check Orders & payments"


def _is_duplicate(e: Exception) -> bool:
    text = str(e).lower()
    return "duplicate" in text or "23505" in text or "unique" in text


def _money_landed(db, tenant_id: str, deal_id: str, note: str, paid_before: int) -> bool:
    """After an unexpected error from deals.record_payment: did the money get written anyway? The payment note
    carries the receipt number, and the order's paid total moves when a payment row exists."""
    try:
        rows = (db.table("deal_payments").select("id").eq("tenant_id", tenant_id).eq("deal_id", deal_id)
                .eq("note", note).limit(1).execute()).data or []
        if rows:
            return True
        return int(_deal(db, tenant_id, deal_id).get("paid_paise") or 0) > paid_before
    except Exception as e:  # cannot tell: keep the claim, so the part is never charged twice
        logger.warning("fee part payment check failed for order %s: %s", deal_id, e)
        return True


def _mark_part_paid(db, tenant_id: str, plan_id: str, part_index: int, *, method: str,
                    by_user_id: str | None = None) -> tuple[dict, dict | None]:
    """Record one part as paid, once. The payment row is the claim (unique per plan + part); the money
    goes through deals.record_payment. If that refuses, the claim is removed again. If it fails with an
    unexpected error AFTER the money was written, the claim stays and the part counts as paid.
    Returns (receipt, the order's now-stale pay link or None)."""
    from app.services import deals

    if method not in PAY_METHODS:
        raise FeeError("Pick how it was paid: cash, UPI, card or bank transfer")
    plan = get_plan(db, tenant_id, plan_id=plan_id)
    if not plan:
        raise FeeError("Fee plan not found", 404)
    parts = plan.get("parts") or []
    if not isinstance(part_index, int) or not 0 <= part_index < len(parts):
        raise FeeError("That part is not in this plan", 404)
    deal = _deal(db, tenant_id, plan["deal_id"])
    if deal.get("stage") == "lost":
        raise FeeError("This order is cancelled")
    amount = int(parts[part_index]["amount_paise"])
    receipt_no = f"FEE-{int(deal.get('deal_number') or 0):04d}-{part_index + 1}"
    already = FeeError("That part is already marked paid", 409)
    recorded = _payments(db, tenant_id, plan_id)
    if recorded.get(part_index):
        raise already
    if part_index in covered_parts(parts, {i: int(r["paid_paise"]) for i, r in recorded.items()},
                                   int(deal.get("paid_paise") or 0)):
        raise FeeError("That part is already paid on the order", 409)
    try:
        claim = db.table("fee_plan_payments").insert({
            "tenant_id": tenant_id, "fee_plan_id": plan_id, "part_index": part_index, "paid_paise": amount,
            "method": method, "receipt_no": receipt_no, "by_user_id": by_user_id,
        }).execute().data[0]
    except Exception as e:
        if _is_duplicate(e):
            raise already
        raise
    note = f"Fee part {part_index + 1} of {len(parts)} ({receipt_no})"
    stale = None
    try:
        res = deals.record_payment(tenant_id, plan["deal_id"], amount, method, received_by=by_user_id, note=note, db=db)
        status = res.get("status")
        stale = res.get("stale_link")
    except Exception as e:
        logger.warning("fee plan %s part %s: payment call failed: %s", plan_id, part_index, e)
        # deals._insert_payment can write the money and then fail (invoice number): never release the claim then.
        status = "recorded" if _money_landed(db, tenant_id, plan["deal_id"], note, int(deal.get("paid_paise") or 0)) else "error"
    if status != "recorded":
        db.table("fee_plan_payments").delete().eq("id", claim["id"]).eq("tenant_id", tenant_id).execute()
        raise FeeError({"over": _OVER, "closed": "This order is cancelled",
                        "duplicate": "That payment is already recorded"}.get(
                            status, "Could not save the payment. Please try again"))
    return receipt(db, tenant_id, claim["id"]), stale


def mark_part_paid(db, tenant_id: str, plan_id: str, part_index: int, *, method: str,
                   by_user_id: str | None = None) -> dict:
    """Synchronous form of mark_part_paid_async (no pay-link cleanup). Returns the receipt."""
    return _mark_part_paid(db, tenant_id, plan_id, part_index, method=method, by_user_id=by_user_id)[0]


async def mark_part_paid_async(db, tenant_id: str, plan_id: str, part_index: int, *, method: str,
                               by_user_id: str | None = None) -> dict:
    """Mark a part paid, then cancel the order's open pay link (it was for the old balance), like Orders does."""
    from app.services import deals
    out, stale = await _io(_mark_part_paid, db, tenant_id, plan_id, part_index, method=method, by_user_id=by_user_id)
    try:
        await deals.cancel_stale_link(stale)
    except Exception as e:
        logger.warning("fee part paid, but the old pay link was not cancelled: %s", e)
    return out


def receipt(db, tenant_id: str, payment_id: str) -> dict:
    """What the printable receipt shows."""
    rows = (db.table("fee_plan_payments").select("*").eq("id", payment_id).eq("tenant_id", tenant_id)
            .limit(1).execute()).data or []
    if not rows:
        raise FeeError("Receipt not found", 404)
    pay = rows[0]
    plan = get_plan(db, tenant_id, plan_id=pay["fee_plan_id"]) or {"parts": [], "deal_id": None}
    deal = _deal(db, tenant_id, plan["deal_id"]) if plan.get("deal_id") else {}
    enrol = ((db.table("batch_enrolments").select("student_name, phone, batch_id").eq("tenant_id", tenant_id)
              .eq("deal_id", plan.get("deal_id")).limit(1).execute()).data or [{}])[0]
    batch = ((db.table("course_batches").select("name, course_item_id").eq("tenant_id", tenant_id)
              .eq("id", enrol.get("batch_id")).limit(1).execute()).data or [{}])[0] if enrol.get("batch_id") else {}
    course = ((db.table("catalog_items").select("name").eq("tenant_id", tenant_id)
               .eq("id", batch.get("course_item_id")).limit(1).execute()).data or [{}])[0] if batch else {}
    ten = (db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute().data or [{}])[0]
    plan_paid = sum(int(p["paid_paise"]) for p in _payments(db, tenant_id, plan["id"]).values()) if plan.get("id") else 0
    paid_total = max(plan_paid, int(deal.get("paid_paise") or 0))  # money put on the order elsewhere counts too
    total = int(deal.get("total_paise") or 0)
    return {
        "id": pay["id"], "receipt_no": pay["receipt_no"], "paid_at": pay.get("paid_at"), "method": pay["method"],
        "amount_paise": int(pay["paid_paise"]), "part_number": int(pay["part_index"]) + 1,
        "parts_total": len(plan.get("parts") or []), "business_name": ten.get("name") or "",
        "student_name": enrol.get("student_name") or "", "phone": enrol.get("phone") or "",
        "course_name": course.get("name") or "", "batch_name": batch.get("name") or "",
        "fee_total_paise": total, "balance_paise": max(total - paid_total, 0),
        "paid_by": _user_names(db, tenant_id, {str(pay["by_user_id"])}).get(str(pay.get("by_user_id"))) if pay.get("by_user_id") else None,
    }


# ───────────────────────────────────────────────────────────── the reminder template and switch

def template_status(db, tenant_id: str) -> str | None:
    """APPROVED | PENDING | REJECTED | ... or None when it was never submitted."""
    from app.config_dynamic import get_setting
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    rows = (db.table("message_templates").select("name, status, meta_waba_id").eq("tenant_id", tenant_id)
            .eq("name", FEE_TEMPLATE["name"]).execute()).data or []
    rows = [r for r in rows if not waba_id or r.get("meta_waba_id") == waba_id]
    return ((rows[0].get("status") or "PENDING").upper()) if rows else None


def reminders_on(tenant_id: str) -> bool:
    from app.config_dynamic import get_setting
    return str(get_setting(SETTING_KEY, fallback="false", tenant_id=tenant_id) or "false").lower() == "true"


def reminders_state(db, tenant_id: str) -> dict:
    return {"enabled": reminders_on(tenant_id), "template": template_status(db, tenant_id),
            "template_body": FEE_TEMPLATE["body"]}


def set_reminders(db, tenant_id: str, enabled: bool) -> dict:
    """OFF until the template is approved: switching on before that is refused in plain words."""
    from app.config_dynamic import save_setting
    if enabled and template_status(db, tenant_id) != "APPROVED":
        raise FeeError("Send the fee reminder message to WhatsApp and wait until it is approved, then switch this on")
    save_setting(SETTING_KEY, "true" if enabled else "false", tenant_id=tenant_id)
    return reminders_state(db, tenant_id)


async def submit_template(db, tenant_id: str, ctx: dict | None = None) -> dict:
    """Submit `fee_reminder` (utility, English) through the Templates page's own path, if not already there."""
    from fastapi import HTTPException
    from app.routes.templates import CreateTemplate, create_template

    if template_status(db, tenant_id) not in (None, "REJECTED"):
        return reminders_state(db, tenant_id)
    try:
        await create_template(CreateTemplate(name=FEE_TEMPLATE["name"], category="UTILITY", language="en",
                                             body_text=FEE_TEMPLATE["body"], body_examples=FEE_TEMPLATE["examples"]),
                              tenant_id=tenant_id, _ctx=ctx or {})
    except HTTPException as e:
        raise FeeError(str(e.detail))
    except Exception as e:
        logger.warning("fee reminder template did not submit: %s", e)
        raise FeeError("Could not send the message to WhatsApp. Please try again")
    return reminders_state(db, tenant_id)


# ───────────────────────────────────────────────────────────── the daily reminder run

def kind_for(days_late: int) -> str | None:
    """days_late = today - due date. Exact day plus one day of catch-up if a run was missed."""
    if -3 <= days_late <= -2:
        return "before"
    if 0 <= days_late <= 1:
        return "due"
    if 3 <= days_late <= 4:
        return "late"
    return None


def _chunks(items: list, size: int = 200):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_in(db, table: str, tenant_id: str, column: str, values: list, select: str = "*") -> list[dict]:
    out: list[dict] = []
    for part in _chunks(list(values)):
        out += fetch_all(lambda part=part: db.table(table).select(select).eq("tenant_id", tenant_id).in_(column, part))
    return out


def _first_name(name: str | None) -> str:
    from app.services.booking_messages import clean_text
    return (clean_text(name, 40).split(" ") or [""])[0] or "there"


def _lead_block(lead: dict | None) -> str | None:
    """Why this person must not get an automated message, or None."""
    from app.services import automation_guards as guards
    if not lead:
        return None
    if lead.get("do_not_call"):
        return "said stop"
    return guards.lead_blocks_automated_outbound({**lead, "phone": lead.get("phone") or "x"})


def _claim(db, tenant_id: str, plan_id: str, index: int, kind: str) -> str | None:
    try:
        rows = db.table("fee_plan_reminders").insert({"tenant_id": tenant_id, "fee_plan_id": plan_id,
                                                      "part_index": index, "kind": kind}).execute().data
        return rows[0]["id"] if rows else None
    except Exception as e:
        if not _is_duplicate(e):
            logger.warning("fee reminder claim failed: %s", e)
        return None


def _unclaim(db, tenant_id: str, claim_id: str) -> None:
    try:
        db.table("fee_plan_reminders").delete().eq("id", claim_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.warning("fee reminder claim %s not released: %s", claim_id, e)


async def _send_one(db, tenant_id: str, template: dict, phone: str, values: list[str]) -> tuple[str, str] | None:
    from app.services.call_details_share import render_template
    from app.services.meta_cloud import send_template_message
    vals = [" ".join(str(v).split()) or "-" for v in values]
    components = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in vals]}]
    resp = await send_template_message(phone, template["name"], template.get("language") or "en",
                                       components=components, tenant_id=tenant_id)
    sid = ((resp or {}).get("messages") or [{}])[0].get("id")
    return (sid, render_template(template.get("body_text"), vals)) if sid else None


async def _tenant_ready(db, tenant_id: str) -> dict | None:
    """The approved template when this business may send fee reminders now, else None."""
    from app.config_dynamic import get_setting
    from app.services import automation_guards as guards
    from app.services.call_details_share import _approved_templates
    if not reminders_on(tenant_id) or not guards.master_switch_on(tenant_id):
        return None
    if not (get_setting("meta_phone_number_id", tenant_id=tenant_id) and get_setting("meta_access_token", tenant_id=tenant_id)):
        return None
    approved = await _io(_approved_templates, db, tenant_id)
    return next((t for t in approved if t.get("name") == FEE_TEMPLATE["name"]), None)


async def send_fee_reminders(db=None, now: datetime | None = None) -> int:
    """Daily 10:00 IST. Returns how many reminders went out. Never raises."""
    db = db or get_supabase()
    today = (now or datetime.now(IST)).astimezone(IST).date()
    try:
        plans = await _io(fetch_all, lambda: db.table("fee_plans").select("*"))
    except Exception as e:  # migration 330 not applied yet
        logger.info("fee reminders skipped: %s", type(e).__name__)
        return 0
    by_tenant: dict[str, list[dict]] = {}
    for p in plans:
        by_tenant.setdefault(str(p["tenant_id"]), []).append(p)
    sent = 0
    for tenant_id, tenant_plans in by_tenant.items():
        try:
            template = await _tenant_ready(db, tenant_id)
            if template:
                sent += await _run_tenant(db, tenant_id, tenant_plans, template, today)
        except Exception as e:
            logger.warning("fee reminders for tenant %s failed: %s", tenant_id, e)
    return sent


async def _run_tenant(db, tenant_id: str, plans: list[dict], template: dict, today: date) -> int:
    """One business's due reminders. Returns how many were sent. One bad plan never stops the others."""
    deals_by_id = {r["id"]: r for r in await _io(_fetch_in, db, "deals", tenant_id, "id", [p["deal_id"] for p in plans],
                                                    "id, stage, paid_paise, total_paise")}
    # Not for a cancelled or fully paid order, even when the money went in on the Orders page.
    live = [p for p in plans if (deals_by_id.get(p["deal_id"]) or {}).get("stage") not in (None, "lost", "won")
            and int(deals_by_id[p["deal_id"]].get("total_paise") or 0) - int(deals_by_id[p["deal_id"]].get("paid_paise") or 0) > 0]
    if not live:
        return 0
    enrols = {r["deal_id"]: r for r in await _io(_fetch_in, db, "batch_enrolments", tenant_id, "deal_id",
                                                  [p["deal_id"] for p in live])
              if r.get("status") == "active"}
    paid: dict[str, dict[int, int]] = {}
    for r in await _io(_fetch_in, db, "fee_plan_payments", tenant_id, "fee_plan_id", [p["id"] for p in live],
                       "id, fee_plan_id, part_index, paid_paise"):
        paid.setdefault(r["fee_plan_id"], {})[int(r["part_index"])] = int(r["paid_paise"])
    leads = {r["id"]: r for r in await _io(_fetch_in, db, "leads", tenant_id, "id",
                                           [e["lead_id"] for e in enrols.values()],
                                           "id, name, phone, opted_out, do_not_call, blocked_at, whatsapp_undeliverable")}
    ten = (await _io(lambda: db.table("tenants").select("name").eq("id", tenant_id).limit(1).execute().data)) or [{}]
    business = (ten[0].get("name") or "").strip() or "us"
    sent = 0
    for plan in live:
        enrol = enrols.get(plan["deal_id"])
        if not enrol:
            continue
        try:
            done = covered_parts(plan.get("parts") or [], paid.get(plan["id"], {}),
                                 int(deals_by_id[plan["deal_id"]].get("paid_paise") or 0))
            sent += await _run_plan(db, tenant_id, plan, enrol, leads.get(enrol["lead_id"]) or {}, done,
                                    template, business, today)
        except Exception as e:
            logger.warning("fee reminders: plan %s skipped: %s", plan.get("id"), e)
    return sent


async def _run_plan(db, tenant_id: str, plan: dict, enrol: dict, lead: dict, done: set[int], template: dict,
                    business: str, today: date) -> int:
    from app.services import blocked_guard
    from app.services.customer_calling import send_to_calling

    sent = 0
    for index, part in enumerate(plan.get("parts") or []):
        if index in done:
            continue
        try:
            kind = kind_for((today - _day(part["due_on"])).days)
        except (FeeError, KeyError, TypeError):
            continue  # a malformed part: skip it, the rest of the plan still runs
        if not kind:
            continue
        try:
            sent += await _remind_part(db, tenant_id, plan, enrol, lead, index, part, kind, template, business,
                                       blocked_guard, send_to_calling)
        except Exception as e:
            logger.warning("fee reminder plan %s part %s skipped: %s", plan.get("id"), index, e)
    return sent


async def _remind_part(db, tenant_id, plan, enrol, lead, index, part, kind, template, business, blocked_guard,
                       send_to_calling) -> int:
    phone = enrol.get("parent_phone") or enrol.get("phone")
    why = _lead_block(lead)
    if not why and enrol.get("parent_phone"):
        parent = (await _io(lambda: db.table("leads").select("opted_out, do_not_call, blocked_at, whatsapp_undeliverable")
                            .eq("tenant_id", tenant_id).eq("phone", phone).limit(1).execute().data)) or [None]
        why = _lead_block(parent[0])
    if not why and await blocked_guard.is_blocked(tenant_id, phone):
        why = "blocked"
    if why:
        # Calling is still right for a number WhatsApp cannot reach; never for someone who said stop.
        if kind == "late" and why == "whatsapp undeliverable":
            await _io(send_to_calling, db, tenant_id, [enrol["lead_id"]], reason="fee_late")
        return 0
    claim = await _io(_claim, db, tenant_id, plan["id"], index, kind)
    if not claim:
        return 0  # another run has it
    try:
        book = (await _io(lambda: db.table("course_batches").select("name").eq("id", enrol["batch_id"])
                          .eq("tenant_id", tenant_id).limit(1).execute().data)) or [{}]
        values = [_first_name(enrol.get("student_name") or lead.get("name")), business,
                  _rupees(part["amount_paise"]), book[0].get("name") or "your course",
                  day_text(_day(part["due_on"]))]
        res = await _send_one(db, tenant_id, template, phone, values)
    except Exception as e:
        logger.warning("fee reminder plan %s part %s failed: %s", plan["id"], index, e)
        await _io(_unclaim, db, tenant_id, claim)  # the send raised: nothing went out, try again next run
        return 0
    if not res:
        # The send came back with no message id: we cannot tell if it left. Keep the claim so it is never sent twice.
        logger.warning("fee reminder plan %s part %s: no message id, claim kept", plan["id"], index)
        return 0
    sid, text = res
    try:
        await _io(lambda: db.table("fee_plan_reminders").update({"wamid": sid}).eq("id", claim)
                  .eq("tenant_id", tenant_id).execute())
        await _io(lambda: db.table("messages").insert({
            "lead_id": enrol["lead_id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
            "content": text, "is_ai_generated": False, "meta_message_id": sid}).execute())
    except Exception as e:  # the customer already has it
        logger.warning("fee reminder sent but not saved: %s", e)
    if kind == "late":
        try:
            await _io(send_to_calling, db, tenant_id, [enrol["lead_id"]], reason="fee_late")
        except Exception as e:
            logger.warning("fee reminder: send to calling failed: %s", e)
    return 1
