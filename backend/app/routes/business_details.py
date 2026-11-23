"""The tenant's own business details: legal name, address, GSTIN, PAN, bill series, UPI and bank
for the bill, terms, logo and signature. Printed on bills and on the monthly sales export so the
file belongs to the client, not Anril.

Seeing it: settings.view (the bank account number shows only its last 4 digits).
Changing it: settings.manage."""
import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_permission
from app.services import business_details as svc
from app.services.audit_log import record_audit_event
from app.services.business_details import GSTIN_RE, get_business_details, save_business_details  # noqa: F401

logger = logging.getLogger(__name__)
router = APIRouter()
require_settings_view = require_permission("settings.view")
require_settings_manage = require_permission("settings.manage")


class BusinessProfileIn(BaseModel):
    """Every field is optional: only what is sent changes."""
    legal_name: str | None = Field(None, max_length=200)
    bill_name: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=400)
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=100)
    state_code: str | None = Field(None, max_length=2)
    pincode: str | None = Field(None, max_length=12)
    gstin: str | None = Field(None, max_length=15)
    pan: str | None = Field(None, max_length=10)
    gst_type: str | None = Field(None, max_length=12)
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=32)
    prices_include_gst: bool | None = None
    bill_prefix: str | None = Field(None, max_length=6)
    licence_number: str | None = Field(None, max_length=60)
    terms: str | None = Field(None, max_length=1000)
    upi_id: str | None = Field(None, max_length=80)
    bank_account_name: str | None = Field(None, max_length=120)
    bank_name: str | None = Field(None, max_length=120)
    bank_ifsc: str | None = Field(None, max_length=11)
    bank_account_number: str | None = Field(None, max_length=24)


def _answer(profile: dict, ctx: dict, db=None) -> dict:
    """What the screen gets: the profile (bank number masked unless the viewer can manage) plus
    short-lived links to the logo and signature."""
    out = svc.view_for(profile, _has_permission(ctx, "settings.manage"))
    out["logo_url"] = svc.brand_image_url(profile, "logo", db) if out["has_logo"] else None
    out["signature_url"] = svc.brand_image_url(profile, "signature", db) if out["has_signature"] else None
    return out


@router.get("")
def read_profile(ctx: dict = Depends(require_settings_view)):
    return _answer(get_business_details(ctx["tenant_id"]), ctx)


@router.put("")
def update_profile(payload: BusinessProfileIn, ctx: dict = Depends(require_settings_manage)):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    try:
        before = get_business_details(tenant_id, db)
        merged = svc.clean_update(before, payload.model_dump(exclude_unset=True))
    except svc.BusinessDetailsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        saved = save_business_details(tenant_id, merged, db)
    except Exception as e:
        logger.error(f"business_details save failed for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Couldn't save your business details — please try again")
    changed = sorted(k for k in svc.EDITABLE_FIELDS if before.get(k) != saved.get(k))
    if changed:
        record_audit_event(
            db, tenant_id=tenant_id, actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
            action="business_details.updated", target_type="business_details",
            metadata={"fields": changed},
        )
    return _answer(saved, ctx, db)


async def _read_image(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read(svc.MAX_IMAGE_BYTES + 1)
    return content, file.content_type or ""


@router.post("/image/{kind}")
async def upload_image(kind: str, file: UploadFile = File(...), ctx: dict = Depends(require_settings_manage)):
    """kind is 'logo' or 'signature'. PNG, JPG or WEBP, up to 1 MB."""
    content, mime = await _read_image(file)
    db = get_supabase()
    try:
        saved = await asyncio.to_thread(svc.save_brand_image, ctx["tenant_id"], kind, content, mime, db)
    except svc.BusinessDetailsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
        action="business_details.updated", target_type="business_details", metadata={"fields": [kind]},
    )
    return _answer(saved, ctx, db)


@router.delete("/image/{kind}")
async def delete_image(kind: str, ctx: dict = Depends(require_settings_manage)):
    db = get_supabase()
    try:
        saved = await asyncio.to_thread(svc.remove_brand_image, ctx["tenant_id"], kind, db)
    except svc.BusinessDetailsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _answer(saved, ctx, db)
