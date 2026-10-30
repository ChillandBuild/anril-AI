# backend/app/routes/sms_recharge.py
"""Client-side SMS recharge (mounted under /api/v1/sms next to routes/sms.py)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import sms_billing
from app.services.bulk9_client import Bulk9Error

logger = logging.getLogger(__name__)

router = APIRouter()

_CLIENT_STATUS = {"credit_failed": "processing", "amount_mismatch": "processing"}


def _require_sms_enabled(db, tenant_id: str) -> dict:
    rows = db.table("tenants").select("name, enabled_features").eq("id", tenant_id).limit(1).execute().data or []
    if not rows or "sms" not in (rows[0].get("enabled_features") or []):
        raise HTTPException(status_code=403, detail="SMS is not enabled for this account")
    return rows[0]


class RechargeIn(BaseModel):
    amount_rupees: int


@router.get("/recharge/packs")
def recharge_packs(ctx: dict = Depends(require_permission("sms.view"))):
    db = get_supabase()
    _require_sms_enabled(db, ctx["tenant_id"])
    return {"packs": sms_billing.packs(ctx["tenant_id"])}


@router.post("/recharge")
async def recharge(body: RechargeIn, ctx: dict = Depends(require_permission("sms.recharge"))):
    db = get_supabase()
    tenant = _require_sms_enabled(db, ctx["tenant_id"])
    try:
        return await sms_billing.create_recharge(db, ctx["tenant_id"], amount_rupees=body.amount_rupees,
                                                 user_id=ctx.get("user_id"), customer_name=tenant.get("name"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (sms_billing.BillingNotConfigured, Bulk9Error) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/recharge/payments")
def recharge_payments(ctx: dict = Depends(require_permission("sms.view"))):
    db = get_supabase()
    _require_sms_enabled(db, ctx["tenant_id"])
    # No error column: it can carry reseller stock text. A paid-but-not-credited recharge shows
    # as "processing" to the client while the operator sorts it out.
    rows = (db.table("sms_payments").select("id, amount_paise, sms_count, status, short_url, created_at, credited_at")
            .eq("tenant_id", ctx["tenant_id"]).order("created_at", desc=True).limit(100).execute().data or [])
    return {"payments": [{**{k: v for k, v in r.items() if k != "amount_paise"},
                          "status": _CLIENT_STATUS.get(r["status"], r["status"]),
                          "amount_rupees": r["amount_paise"] / 100} for r in rows]}
