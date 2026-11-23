"""v9.2 #21 Call IQ: Live, Evaluation, Results (read-only). Built by agent I-A."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_any_permission, require_permission
from app.services import call_iq_reports as svc

router = APIRouter()


@router.get("/live")
async def live(ctx: dict = Depends(require_any_permission("team.view", "telecalling.view"))):
    """Each telecaller now: on a call, on a break, free, or off. A telecaller sees only themself."""
    return await asyncio.to_thread(svc.live, get_supabase(), ctx)


@router.get("/evaluation")
async def evaluation(period: str = Query("7d"), ctx: dict = Depends(require_permission("team.view"))):
    if period not in svc.EVAL_DAYS:
        raise HTTPException(status_code=400, detail="period must be 7d or 30d.")
    return await asyncio.to_thread(svc.evaluation, get_supabase(), ctx, period)


@router.get("/results")
async def results(period: str = Query("today"), ctx: dict = Depends(require_permission("team.view"))):
    """Calls, orders and money per telecaller. Money (revenue_paise) only for people who may see deals."""
    if period not in svc.RESULT_DAYS:
        raise HTTPException(status_code=400, detail="period must be today, 7d or 30d.")
    return await asyncio.to_thread(svc.results, get_supabase(), ctx, period)
