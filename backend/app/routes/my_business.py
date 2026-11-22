"""My business: Payments & advance and Target & profit (Settings > My business).

  GET /my-business/payments  read-only explanation of refunds, reminders and ways to pay
  GET /my-business/target    the target, a suggestion, and this month so far
  PUT /my-business/target    owner only

The advance rule is NOT here: the page reads and saves it through /orders/advance-rule.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, get_tenant_and_role, require_any_permission
from app.services import payments_overview, sales_target

logger = logging.getLogger(__name__)
router = APIRouter()
require_settings_view = require_any_permission("settings.view", "settings.manage")


def require_target_owner(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    if ctx.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can set the target.")
    return ctx


@router.get("/payments")
def get_payments(ctx: dict = Depends(require_settings_view)):
    return payments_overview.overview(get_supabase(), ctx["tenant_id"])


class TargetIn(BaseModel):
    monthly_paise: int | None = Field(None)
    months: dict[str, int] = Field(default_factory=dict)
    show_team: bool = False


@router.get("/target")
def get_target(ctx: dict = Depends(require_settings_view)):
    # Rupees of money in are for the owner and people who can see Orders; others get target and % only.
    sees_money = ctx.get("role") == "owner" or _has_permission(ctx, "deals.view")
    return sales_target.overview(get_supabase(), ctx["tenant_id"], sees_money=sees_money)


@router.put("/target")
def put_target(payload: TargetIn, ctx: dict = Depends(require_target_owner)):
    db = get_supabase()
    try:
        sales_target.save_target(db, ctx["tenant_id"], payload.model_dump())
    except sales_target.TargetError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning("sales target: save failed for tenant %s: %s", ctx["tenant_id"], e)
        raise HTTPException(status_code=503, detail="Could not save the target right now. Please try again.")
    return sales_target.overview(db, ctx["tenant_id"])
