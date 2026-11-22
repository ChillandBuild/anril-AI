"""Anril OTP › Overview (read-only): /api/v1/otp-overview.

Same access as the rest of OTP viewing: SMS view or Settings view (owner passes everything).
The tenant always comes from the signed-in user. Numbers come from services/otp_overview.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_any_permission
from app.services import otp_overview as svc

router = APIRouter()

view = require_any_permission("sms.view", "settings.view")


@router.get("")
def get_overview(ctx: dict = Depends(view)) -> dict:
    return svc.overview(get_supabase(), ctx["tenant_id"])
