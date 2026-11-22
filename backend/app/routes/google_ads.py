"""Leads › Google Ads (v9.2 #20), /api/v1/google-ads. Logic: app/services/google_ads_report.py.

Google can't send us spend, so the page works from a campaign report the client uploads (or
types in). Chats, calls, hot and paid come from our own data.

meta_ads.view to see, meta_ads.manage to upload / edit / make links. Money (spent, paid, per
chat) only for people with deals.view; the keys are left out of the answer otherwise.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_permission
from app.services import google_ads_report as report
from app.services.google_ads_attribution import build_tracked_wa_link, slugify_campaign

logger = logging.getLogger(__name__)

router = APIRouter()

require_view = require_permission("meta_ads.view")
require_manage = require_permission("meta_ads.manage")

_CONNECT = {"available": False, "reason": "Needs Google approval"}


def _can_see_money(ctx: dict) -> bool:
    return _has_permission(ctx, "deals.view")


def _bad_request(e: report.ReportError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


def _month(value: str | None) -> str:
    try:
        return report.parse_month(value)
    except report.ReportError as e:
        raise _bad_request(e)


def _own_google_campaign(db, tenant_id: str, campaign_id: str) -> dict:
    rows = (
        db.table("ad_campaigns").select("*")
        .eq("id", campaign_id).eq("tenant_id", tenant_id).eq("platform", "google")
        .limit(1).execute().data or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return rows[0]


def _claim_google_name(db, tenant_id: str, campaign_id: str, name: str | None) -> None:
    """Set a campaign's Google name. One Google name belongs to one campaign, so any other
    campaign using the same name (any casing) is cleared first."""
    if name:
        for other in report.google_campaigns(db, tenant_id):
            if str(other["id"]) != campaign_id and (other.get("google_campaign_name") or "").strip().casefold() == name.casefold():
                db.table("ad_campaigns").update({"google_campaign_name": None}).eq("id", other["id"]).eq(
                    "tenant_id", tenant_id).execute()
    db.table("ad_campaigns").update({"google_campaign_name": name}).eq("id", campaign_id).eq(
        "tenant_id", tenant_id).execute()


@router.get("/campaigns")
async def list_campaigns(month: str | None = Query(None), ctx: dict = Depends(require_view)):
    month = _month(month)
    db = get_supabase()
    try:
        data = report.campaign_rows(db, ctx["tenant_id"], month, show_money=_can_see_money(ctx))
    except Exception as e:
        logger.error("google-ads campaigns error: %s", e)
        raise HTTPException(status_code=503, detail="Couldn't load Google Ads right now. Nothing is lost; try again.")
    return {**data, "connect": _CONNECT}


class CampaignPatch(BaseModel):
    google_campaign_name: str | None = Field(None, max_length=200)


@router.patch("/campaigns/{campaign_id}")
async def rename_google_campaign(campaign_id: str, body: CampaignPatch, ctx: dict = Depends(require_manage)):
    """Tell us how Google's report spells this campaign (empty clears it)."""
    db = get_supabase()
    _own_google_campaign(db, ctx["tenant_id"], campaign_id)
    name = (body.google_campaign_name or "").strip() or None
    _claim_google_name(db, ctx["tenant_id"], campaign_id, name)
    return {"campaign_id": campaign_id, "google_campaign_name": name}


class SpendBody(BaseModel):
    month: str
    spend_paise: int = Field(ge=0, le=10**12)
    clicks: int = Field(ge=0, le=10**9)


@router.put("/campaigns/{campaign_id}/spend")
async def put_spend(campaign_id: str, body: SpendBody, ctx: dict = Depends(require_manage)):
    """Type in a month's spend and clicks by hand."""
    month = _month(body.month)
    db = get_supabase()
    _own_google_campaign(db, ctx["tenant_id"], campaign_id)
    row = report.save_spend(db, ctx["tenant_id"], campaign_id, month, body.spend_paise, body.clicks,
                            source="hand", user_id=ctx.get("user_id"))
    return {"campaign_id": campaign_id, "month": month, "spend_paise": row["spend_paise"],
            "clicks": row["clicks"], "source": "hand"}


@router.post("/upload")
async def upload_report(
    month: str | None = Query(None),
    file: UploadFile = File(...),
    content_length: int | None = Header(None),
    ctx: dict = Depends(require_manage),
):
    """Read a Google Ads campaign report CSV and save each matched campaign's spend and clicks
    for ?month=. Rows we can't match to a campaign come back in `unmatched` so the page can ask."""
    month = _month(month)
    too_big = HTTPException(status_code=413, detail="That file is too big (limit 1 MB). Download just the campaign report.")
    # Early check on the declared size (a little slack for the multipart wrapper); the read below is the backstop.
    if content_length is not None and content_length > report.MAX_UPLOAD_BYTES + 65_536:
        raise too_big
    raw = await file.read(report.MAX_UPLOAD_BYTES + 1)
    if len(raw) > report.MAX_UPLOAD_BYTES:
        raise too_big
    try:
        parsed = report.parse_report_csv(raw, month)
    except report.ReportError as e:
        raise _bad_request(e)

    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    matched, unmatched = report.match_rows(parsed["rows"], report.google_campaigns(db, tenant_id))
    for row in matched:
        report.save_spend(db, tenant_id, row["campaign_id"], month, row["spend_paise"], row["clicks"],
                          source="upload", user_id=ctx.get("user_id"))
    return {"month": month, "matched": matched, "unmatched": unmatched,
            "skipped_other_months": parsed["skipped_other_months"]}


class PairBody(BaseModel):
    google_campaign_name: str = Field(min_length=1, max_length=200)
    campaign_id: str
    month: str
    spend_paise: int | None = Field(None, ge=0, le=10**12)   # None: the report had no such column
    clicks: int | None = Field(None, ge=0, le=10**9)


@router.post("/pair")
async def pair_campaign(body: PairBody, ctx: dict = Depends(require_manage)):
    """Remember that Google's "<name>" is this campaign, and save that row's spend and clicks."""
    month = _month(body.month)
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    _own_google_campaign(db, tenant_id, body.campaign_id)
    name = body.google_campaign_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Google's campaign name is empty.")
    _claim_google_name(db, tenant_id, body.campaign_id, name)
    report.save_spend(db, tenant_id, body.campaign_id, month, body.spend_paise, body.clicks,
                      source="upload", user_id=ctx.get("user_id"))
    return {"campaign_id": body.campaign_id, "google_campaign_name": name, "month": month,
            "spend_paise": body.spend_paise, "clicks": body.clicks}


class LinkBody(BaseModel):
    campaign: str = Field(min_length=1, max_length=80)


@router.post("/links")
async def make_link(body: LinkBody, ctx: dict = Depends(require_manage)):
    """A wa.me link to paste into Google Ads, tagged [GADS:<slug>], and its campaign row."""
    from app.routes.inbound_leads import _primary_whatsapp_number
    from app.services.growth import get_or_create_campaign

    slug = slugify_campaign(body.campaign)
    if not slug:
        raise HTTPException(status_code=400, detail="Campaign name must contain letters or numbers.")
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    number = _primary_whatsapp_number(db, tenant_id)
    if not number:
        raise HTTPException(
            status_code=400,
            detail="No active WhatsApp number found. Activate WhatsApp before generating a link.",
        )
    try:
        link = build_tracked_wa_link(number, slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Same identity the webhook uses when the first tagged message arrives, so both land on one row.
    campaign = get_or_create_campaign(
        db, tenant_id=tenant_id, platform="google", campaign_name=slug,
        external_campaign_id=f"google:{slug}",
    )
    out: dict[str, Any] = {"link": link, "campaign_slug": slug, "whatsapp_number": number,
                           "campaign_id": campaign["id"] if campaign else None}
    return out
