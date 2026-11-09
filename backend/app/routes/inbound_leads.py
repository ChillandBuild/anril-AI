"""
Inbound Leads — all leads that arrived through a messaging channel.

Inbound universe:  source IN ('whatsapp','instagram','facebook','telegram')
  (upload / manual leads are NOT inbound and never appear here)

Origin (independent of channel):
  ad_campaign_id IS NOT NULL  →  origin = "ad"      (clicked a Meta Ad CTA)
  ad_campaign_id IS NULL      →  origin = "organic" (messaged directly)

The "keyword" is the first inbound message the lead sent — for ad leads this is
the pre-filled CTA text; for organic leads it is just their opening message.
"""

import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from pydantic import BaseModel, Field
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services.inbound_leads_logic import INBOUND_SOURCES
from app.services.google_ads_attribution import build_tracked_wa_link, slugify_campaign

logger = logging.getLogger(__name__)
router = APIRouter()
require_meta_ads_view = require_permission("meta_ads.view")
require_meta_ads_manage = require_permission("meta_ads.manage")

CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "telegram": "Telegram",
    "indiamart": "IndiaMART",
    "justdial": "JustDial",
    "meta_form": "Instant form",
}

SEGMENT_LABELS = {
    "A": "Hot",
    "B": "Warm",
    "C": "Cold",
    "D": "Not Interested",
}


class MetaAdTrackingCodeRequest(BaseModel):
    ad_creative_id: str
    message: str = Field(
        default="Hi, I'm interested in this service.",
        min_length=1,
        max_length=500,
    )


class AdTrackingToggle(BaseModel):
    tracked: bool


class SyncStartUpdate(BaseModel):
    start_date: str


def _fmt_ist(iso: str) -> str:
    """Format UTC ISO timestamp to IST string."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
        return ist.strftime("%d %b %Y, %I:%M %p IST")
    except Exception:
        return iso


def _fetch_inbound_leads(
    db,
    tenant_id: str,
    *,
    origin: str = "all",
    segment: str | None = None,
    ad_campaign_id: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Fetch inbound leads (source in INBOUND_SOURCES). Returns (rows, total_count).
    origin: "all" | "organic" | "ad". Two simple queries, no JOIN.
    """
    def _apply_common(q):
        q = (
            q.eq("tenant_id", tenant_id)
            .in_("source", list(INBOUND_SOURCES))
            .is_("deleted_at", "null")
        )
        # Instant form leads are ad leads without an ad_campaigns row.
        if origin == "ad":
            q = q.or_("ad_campaign_id.not.is.null,source.eq.meta_form")
        elif origin == "organic":
            q = q.is_("ad_campaign_id", "null").neq("source", "meta_form")
        if segment:
            q = q.eq("segment", segment)
        if ad_campaign_id:
            q = q.eq("ad_campaign_id", ad_campaign_id)
        if source:
            q = q.eq("source", source)
        if date_from:
            q = q.gte("created_at", date_from)
        if date_to:
            q = q.lte("created_at", date_to)
        return q

    data_q = _apply_common(
        db.table("leads").select(
            "id,phone,name,source,score,segment,created_at,ad_campaign_id"
        )
    )
    data_result = (
        data_q.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = data_result.data or []

    count_q = _apply_common(db.table("leads").select("id", count="exact"))
    count_result = count_q.execute()
    total = count_result.count or len(rows)

    return rows, total


def _fetch_campaign_names(db, tenant_id: str, campaign_ids: list[str]) -> dict[str, str]:
    """Look up campaign names for a set of campaign IDs. Returns {id: name}."""
    if not campaign_ids:
        return {}
    result = (
        db.table("ad_campaigns")
        .select("id,campaign_name")
        .in_("id", campaign_ids)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return {row["id"]: row["campaign_name"] for row in (result.data or [])}


def _fetch_first_keywords(db, tenant_id: str, lead_ids: list[str]) -> dict[str, str]:
    """
    For each lead_id, fetch the first inbound message (the CTA keyword/pre-fill text).
    Returns {lead_id: first_message_content}.
    """
    if not lead_ids:
        return {}
    # Explicit high limit: PostgREST caps at 1000 rows by default, which would
    # silently drop keywords for leads beyond that window on large exports.
    result = (
        db.table("messages")
        .select("lead_id,content,created_at")
        .in_("lead_id", lead_ids)
        .eq("tenant_id", tenant_id)
        .eq("direction", "inbound")
        .order("created_at", desc=False)
        .limit(50000)
        .execute()
    )
    keyword_map: dict[str, str] = {}
    for msg in (result.data or []):
        lid = msg.get("lead_id", "")
        if lid and lid not in keyword_map:
            keyword_map[lid] = (msg.get("content") or "").strip()
    return keyword_map


def _enrich(
    leads: list[dict],
    campaign_map: dict[str, str],
    keyword_map: dict[str, str],
) -> list[dict]:
    """Attach campaign name, keyword, and origin to each lead row."""
    enriched = []
    for lead in leads:
        cid = lead.get("ad_campaign_id") or ""
        src = lead.get("source", "whatsapp")
        enriched.append({
            "id": lead.get("id", ""),
            "phone": lead.get("phone") or "—",
            "name": lead.get("name") or "—",
            "source": src,
            "channel_label": CHANNEL_LABELS.get(src, src.title()),
            "origin": "ad" if lead.get("ad_campaign_id") or lead.get("source") == "meta_form" else "organic",
            "score": lead.get("score", 5),
            "segment": lead.get("segment", "C"),
            "segment_label": SEGMENT_LABELS.get(lead.get("segment", "C"), "—"),
            "created_at": lead.get("created_at", ""),
            "ad_campaign_id": cid,
            "campaign_name": campaign_map.get(cid, "Unknown Campaign"),
            "keyword": keyword_map.get(lead.get("id", ""), "—") or "—",
        })
    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/campaigns")
async def list_campaigns(
    current_account: bool = Query(False),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return ad campaigns for this tenant (used for filter dropdowns).

    current_account=true (the Segments page) limits it to campaigns synced from the
    ad account connected now -- the same scope as the Meta Ads table. Without it,
    every campaign ever recorded is returned, as before."""
    db = get_supabase()
    if current_account:
        from app.services.ad_performance import current_account_campaigns

        try:
            return {"data": current_account_campaigns(db, tenant_id)}
        except Exception as e:
            logger.error(f"inbound-leads current-account campaigns fetch error: {e}")
            return {"data": []}
    try:
        result = (
            db.table("ad_campaigns")
            .select("id,campaign_name,platform")
            .eq("tenant_id", tenant_id)
            .order("campaign_name")
            .execute()
        )
        return {"data": result.data or []}
    except Exception as e:
        logger.error(f"inbound-leads campaigns fetch error: {e}")
        return {"data": []}


def _primary_whatsapp_number(db, tenant_id: str) -> str | None:
    """The tenant's active primary WhatsApp number, for building wa.me links."""
    result = (
        db.table("phone_numbers")
        .select("number,role")
        .eq("tenant_id", tenant_id)
        .eq("status", "active")
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None
    primary = next((r for r in rows if r.get("role") == "primary"), None)
    return (primary or rows[0]).get("number")


@router.get("/google-link")
async def generate_google_ads_link(
    campaign: str = Query(..., min_length=1, max_length=80),
    gclid: str | None = Query(None, max_length=200),
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate a tracked wa.me link for a Google Ads campaign CTA.

    The returned link carries a [GADS:<slug>] tag in its pre-filled text so the
    WhatsApp webhook can attribute inbound leads to this Google campaign. Point
    the Google ad at `link` and every click becomes an attributed lead.
    """
    slug = slugify_campaign(campaign)
    if not slug:
        raise HTTPException(status_code=400, detail="Campaign name must contain letters or numbers.")

    db = get_supabase()
    number = _primary_whatsapp_number(db, tenant_id)
    if not number:
        raise HTTPException(
            status_code=400,
            detail="No active WhatsApp number found. Activate WhatsApp before generating a link.",
        )

    try:
        link = build_tracked_wa_link(number, slug, gclid=(gclid or None))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"link": link, "campaign_slug": slug, "whatsapp_number": number}


@router.get("/")
async def list_inbound_leads(
    origin: str = Query("all", pattern="^(all|organic|ad)$"),
    segment: str | None = Query(None, pattern="^[ABCD]$"),
    ad_campaign_id: str | None = Query(None),
    source: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    tenant_id: str = Depends(get_tenant_id),
):
    """List inbound leads (organic + ad) with optional origin/segment/channel filters."""
    db = get_supabase()
    offset = (page - 1) * limit
    try:
        leads, total = _fetch_inbound_leads(
            db, tenant_id,
            origin=origin, segment=segment,
            ad_campaign_id=ad_campaign_id, source=source,
            date_from=date_from, date_to=date_to,
            limit=limit, offset=offset,
        )
    except Exception as e:
        logger.error(f"inbound-leads list error: {e}")
        return {"data": [], "total": 0, "page": page, "limit": limit}

    if not leads:
        return {"data": [], "total": total, "page": page, "limit": limit}

    try:
        lead_ids = [l["id"] for l in leads]
        campaign_ids = list({l["ad_campaign_id"] for l in leads if l.get("ad_campaign_id")})
        campaign_map = _fetch_campaign_names(db, tenant_id, campaign_ids)
        keyword_map = _fetch_first_keywords(db, tenant_id, lead_ids)
        enriched = _enrich(leads, campaign_map, keyword_map)
    except Exception as e:
        logger.error(f"inbound-leads enrich error: {e}")
        return {"data": [], "total": total, "page": page, "limit": limit}
    return {"data": enriched, "total": total, "page": page, "limit": limit}


@router.get("/export")
async def export_inbound_leads(
    origin: str = Query("all", pattern="^(all|organic|ad)$"),
    segment: str | None = Query(None, pattern="^[ABCD]$"),
    ad_campaign_id: str | None = Query(None),
    source: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """CSV export for inbound leads. Respects origin/segment/channel/campaign/date filters."""
    db = get_supabase()
    try:
        leads, _ = _fetch_inbound_leads(
            db, tenant_id,
            origin=origin, segment=segment,
            ad_campaign_id=ad_campaign_id, source=source,
            date_from=date_from, date_to=date_to,
            limit=5000, offset=0,
        )
    except Exception as e:
        logger.error(f"inbound-leads export error: {e}")
        leads = []

    FIELDNAMES = [
        "phone", "name", "origin", "channel", "keyword",
        "ad_campaign", "date_joined_ist", "segment", "score",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()

    if leads:
        try:
            lead_ids = [l["id"] for l in leads]
            campaign_ids = list({l["ad_campaign_id"] for l in leads if l.get("ad_campaign_id")})
            campaign_map = _fetch_campaign_names(db, tenant_id, campaign_ids)
            keyword_map = _fetch_first_keywords(db, tenant_id, lead_ids)
            enriched = _enrich(leads, campaign_map, keyword_map)
        except Exception as e:
            logger.error(f"inbound-leads export enrich error: {e}")
            enriched = []
        for lead in enriched:
            writer.writerow({
                "phone": lead["phone"],
                "name": lead["name"],
                "origin": lead["origin"],
                "channel": lead["channel_label"],
                "keyword": lead["keyword"],
                "ad_campaign": lead["campaign_name"],
                "date_joined_ist": _fmt_ist(lead["created_at"]),
                "segment": lead["segment_label"],
                "score": lead["score"],
            })

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inbound_leads.csv"},
    )


@router.get("/ad-filters", dependencies=[Depends(require_meta_ads_view)])
async def ad_filters(tenant_id: str = Depends(get_tenant_id)):
    """Campaign -> adset -> creative option tree for the cascading dropdowns."""
    from app.services.ad_performance import build_ad_filter_tree
    db = get_supabase()
    return build_ad_filter_tree(db, tenant_id)


@router.post("/ad-tracking-code", dependencies=[Depends(require_meta_ads_manage)])
async def generate_meta_ad_tracking_code(
    payload: MetaAdTrackingCodeRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Return a stable per-ad fallback code and ready-to-copy pre-filled text."""
    from app.services.meta_ads_insights_sync import get_current_ads_account_id
    from app.services.meta_ctwa_attribution import (
        build_prefilled_message,
        clean_greeting,
        ensure_creative_tracking_code,
    )

    db = get_supabase()
    account_id = get_current_ads_account_id(db, tenant_id)
    if not account_id:
        raise HTTPException(status_code=400, detail="Connect a Meta Ads account first")

    creative = ensure_creative_tracking_code(
        db,
        tenant_id=tenant_id,
        meta_ad_account_id=account_id,
        ad_creative_id=payload.ad_creative_id,
    )
    if not creative:
        raise HTTPException(
            status_code=404,
            detail="Click-to-WhatsApp creative not found in the current ad account",
        )
    if not creative.get("meta_ad_id"):
        raise HTTPException(
            status_code=409,
            detail="This creative does not have a Meta Ad ID yet; sync Meta Ads and try again",
        )

    code = creative["prefilled_message_code"]
    greeting = clean_greeting(payload.message)
    db.table("ad_creatives").update({"prefilled_greeting_text": greeting}).eq(
        "id", creative["id"]
    ).eq("tenant_id", tenant_id).execute()
    return {
        "code": code,
        "prefilled_message": build_prefilled_message(payload.message, code),
        "ad_creative_id": creative["id"],
        "creative_name": creative.get("creative_label") or creative.get("meta_ad_id"),
        "meta_ad_id": creative.get("meta_ad_id"),
    }


def _split_fields(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _check_breakdown(breakdown: str | None) -> str | None:
    """Empty means no breakdown; an unknown key is a 400, not a silent fallback."""
    from app.services.meta_ads_fields import BREAKDOWNS
    key = (breakdown or "").strip() or None
    if key and key not in BREAKDOWNS:
        raise HTTPException(status_code=400, detail=f"Unknown breakdown: {key}")
    return key


@router.get("/ad-performance", dependencies=[Depends(require_meta_ads_view)])
async def ad_performance(
    campaign_id: str | None = Query(None),
    adset_id: str | None = Query(None),
    ad_creative_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    delivery_status: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """Per-creative performance rows for the Ad Performance tab."""
    from app.services.ad_performance import build_creative_performance
    db = get_supabase()
    rows = build_creative_performance(
        db, tenant_id,
        campaign_id=campaign_id, adset_id=adset_id, ad_creative_id=ad_creative_id,
        date_from=date_from, date_to=date_to, delivery_status=delivery_status,
    )
    return {"data": rows}


@router.get("/ad-performance/total-reach", dependencies=[Depends(require_meta_ads_view)])
async def ad_performance_total_reach(
    ad_creative_ids: str = Query(..., description="Comma-separated ad_creative ids on screen"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """Meta's de-duplicated reach across the ads in the Total row."""
    from app.services.ad_performance import build_total_reach
    ids = [i.strip() for i in ad_creative_ids.split(",") if i.strip()][:200]
    d_from = _parse_day(date_from, "date_from") if date_from else None
    d_to = _parse_day(date_to, "date_to") if date_to else datetime.now(timezone.utc).date().isoformat()
    return build_total_reach(
        get_supabase(), tenant_id, ad_creative_ids=ids, date_from=d_from, date_to=d_to,
    )


@router.get("/meta-ads/all-ads/total-reach", dependencies=[Depends(require_meta_ads_view)])
async def meta_ads_all_ads_total_reach(
    meta_ad_ids: str | None = Query(None, description="Comma-separated Meta ad ids; omit for the whole account"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """Meta's de-duplicated reach for the All ads Total row."""
    from app.services.ad_performance import build_all_ads_total_reach
    ids = None if meta_ad_ids is None else [i.strip() for i in meta_ad_ids.split(",") if i.strip()][:200]
    today = datetime.now(timezone.utc).date()
    d_to = _parse_day(date_to, "date_to") if date_to else today.isoformat()
    d_from = _parse_day(date_from, "date_from") if date_from else (today - timedelta(days=30)).isoformat()
    return build_all_ads_total_reach(
        get_supabase(), tenant_id, meta_ad_ids=ids, date_from=d_from, date_to=d_to,
    )


@router.get("/meta-ads/reach-by-level", dependencies=[Depends(require_meta_ads_view)])
async def meta_ads_reach_by_level(
    level: str = Query(..., description="campaign or adset"),
    meta_ad_ids: str | None = Query(None, description="Comma-separated Meta ad ids; omit for the whole account"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """Meta's de-duplicated reach per campaign or ad set, for the Campaigns / Ad sets views."""
    from app.services.ad_performance import build_reach_by_level
    ids = None if meta_ad_ids is None else [i.strip() for i in meta_ad_ids.split(",") if i.strip()][:200]
    today = datetime.now(timezone.utc).date()
    d_to = _parse_day(date_to, "date_to") if date_to else today.isoformat()
    d_from = _parse_day(date_from, "date_from") if date_from else (today - timedelta(days=30)).isoformat()
    try:
        return build_reach_by_level(
            get_supabase(), tenant_id, level=level, meta_ad_ids=ids, date_from=d_from, date_to=d_to,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/meta-ads/field-catalog", dependencies=[Depends(require_meta_ads_view)])
async def meta_ads_field_catalog():
    """Meta-computed columns and breakdowns the All ads page can ask for."""
    from app.services.meta_ads_fields import breakdowns_for_api, catalog_for_api
    return {"fields": catalog_for_api(), "breakdowns": breakdowns_for_api()}


_ALL_ADS_DEFAULT_FIELDS = (
    "results,result_type,cost_per_result,reach,impressions,spend,cpm,"
    "inline_link_clicks,ctr,delivery"
)


def _parse_day(value: str, name: str) -> str:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} must be a date like 2026-10-01")


@router.get("/meta-ads/all-ads", dependencies=[Depends(require_meta_ads_view)])
async def meta_ads_all_ads(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    fields: str | None = Query(None),
    breakdown: str | None = Query(None),
    refresh: bool = Query(False, description="Skip the few-minute cache (Sync now)"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Live Meta numbers for every ad that delivered in the range."""
    import httpx
    from app.services.ad_performance import build_all_ads

    today = datetime.now(timezone.utc).date()
    d_to = _parse_day(date_to, "date_to") if date_to else today.isoformat()
    d_from = (
        _parse_day(date_from, "date_from") if date_from
        else (today - timedelta(days=30)).isoformat()
    )
    if d_from > d_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    breakdown = _check_breakdown(breakdown)
    field_keys = _split_fields(fields or _ALL_ADS_DEFAULT_FIELDS)

    db = get_supabase()
    try:
        return build_all_ads(
            db, tenant_id,
            date_from=d_from, date_to=d_to, fields=field_keys, breakdown=breakdown,
            refresh=refresh,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Meta didn't respond, try again in a minute",
        )


@router.get("/meta-ads/tracked-ads", dependencies=[Depends(require_meta_ads_view)])
async def meta_ads_tracked_ads(tenant_id: str = Depends(get_tenant_id)):
    """Every messaging ad of the connected account with its Anril tracking switch."""
    from app.services.ad_performance import list_ads_for_tracking
    db = get_supabase()
    return {"data": list_ads_for_tracking(db, tenant_id)}


@router.patch("/ad-creatives/{ad_creative_id}/tracking", dependencies=[Depends(require_meta_ads_manage)])
async def set_ad_tracking(
    ad_creative_id: str,
    payload: AdTrackingToggle,
    tenant_id: str = Depends(get_tenant_id),
):
    """Turn Anril tracking on or off for one ad. Untracked ads drop out of the
    Ad Performance table and the filter dropdowns."""
    db = get_supabase()
    res = (
        db.table("ad_creatives")
        .update({"tracked_in_anril": payload.tracked})
        .eq("id", ad_creative_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not (res.data or []):
        raise HTTPException(status_code=404, detail="Ad not found")
    return {"ad_creative_id": ad_creative_id, "tracked": payload.tracked}


@router.get("/ad-creatives/{ad_creative_id}/breakdown", dependencies=[Depends(require_meta_ads_view)])
async def ad_creative_breakdown(
    ad_creative_id: str,
    breakdown: str = Query(...),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """Meta's numbers for one messaging ad split by placement, age, gender, region or device."""
    import httpx
    from app.services.ad_performance import PANEL_BREAKDOWNS, build_ad_breakdown

    key = (breakdown or "").strip()
    if key not in PANEL_BREAKDOWNS:
        raise HTTPException(status_code=400, detail=f"Unknown breakdown: {key}")

    today = datetime.now(timezone.utc).date()
    d_to = _parse_day(date_to, "date_to") if date_to else today.isoformat()
    d_from = (
        _parse_day(date_from, "date_from") if date_from
        else (today - timedelta(days=30)).isoformat()
    )
    if d_from > d_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")

    try:
        result = build_ad_breakdown(
            get_supabase(), tenant_id, ad_creative_id,
            breakdown=key, date_from=d_from, date_to=d_to,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Meta didn't respond, try again in a minute",
        )
    if result is None:
        raise HTTPException(status_code=404, detail="Ad not found")
    return result


def _sync_start_payload(db, tenant_id: str) -> dict:
    from app.services.meta_ads_insights_sync import (
        _MAX_HISTORY_DAYS,
        get_ads_setting,
        get_current_ads_account_id,
    )

    account = get_current_ads_account_id(db, tenant_id)
    earliest = None
    if account:
        # The account's first ad ever, eligible or not: the "Data from" floor. An ad
        # that was already off at connect still shows in All ads for its dates.
        registry = (
            db.table("meta_ad_registry").select("ad_created_time")
            .eq("tenant_id", tenant_id)
            .eq("meta_ad_account_id", account)
            .execute().data
        ) or []
        times = [str(r["ad_created_time"]) for r in registry if r.get("ad_created_time")]
        if times:
            earliest = min(times)[:10]
    return {
        "start_date": get_ads_setting(db, tenant_id, "meta_ads_sync_start_date"),
        "connected_at": get_ads_setting(db, tenant_id, "meta_ads_connected_at"),
        "backfilled_from": get_ads_setting(db, tenant_id, "meta_ads_backfilled_from"),
        "earliest_ad_start": earliest,
        "last_synced_at": get_ads_setting(db, tenant_id, "meta_ads_last_sync_at"),
        "max_history_days": _MAX_HISTORY_DAYS,
    }


@router.get("/meta-ads/sync-start", dependencies=[Depends(require_meta_ads_view)])
async def get_sync_start(tenant_id: str = Depends(get_tenant_id)):
    """The date the Meta Ads sync reads from, plus what Meta can still give us."""
    return _sync_start_payload(get_supabase(), tenant_id)


@router.put("/meta-ads/sync-start", dependencies=[Depends(require_meta_ads_manage)])
async def set_sync_start(
    payload: SyncStartUpdate,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Pick the earliest day to sync from, then re-sync in the background."""
    from app.services.meta_ads_insights_sync import (
        _MAX_HISTORY_DAYS,
        set_ads_setting,
        sync_tenant_ad_insights,
    )

    chosen = _parse_day(payload.start_date, "start_date")
    today = datetime.now(timezone.utc).date()
    if datetime.strptime(chosen, "%Y-%m-%d").date() > today:
        raise HTTPException(status_code=400, detail="Pick a date that isn't in the future")
    if datetime.strptime(chosen, "%Y-%m-%d").date() < today - timedelta(days=_MAX_HISTORY_DAYS):
        raise HTTPException(
            status_code=400,
            detail="Meta keeps about 37 months of history — pick a later date",
        )

    db = get_supabase()
    set_ads_setting(db, tenant_id, "meta_ads_sync_start_date", chosen)
    background_tasks.add_task(sync_tenant_ad_insights, db, tenant_id)
    return {**_sync_start_payload(db, tenant_id), "syncing": True}


# (row key, header). The first six match an Ads Manager export so the two files
# line up by Ad ID; the rest follow the on-screen order and mirror the table's
# column labels (METRICS in frontend/app/dashboard/meta-ads/AdPerformanceTab.tsx).
AD_PERFORMANCE_EXPORT_COLUMNS = [
    ("reporting_starts", "Reporting starts"),
    ("reporting_ends", "Reporting ends"),
    ("meta_ad_id", "Ad ID"),
    ("campaign_name", "Campaign name"),
    ("adset_name", "Ad set name"),
    ("creative_label", "Ad name"),
    ("delivery_status", "Delivery"),
    ("budget", "Budget"),
    ("impressions", "Impressions"),
    ("reach", "Reach"),
    ("frequency", "Frequency"),
    ("inline_link_clicks", "Chat clicks"),
    ("clicks_all", "Clicks (all)"),
    ("messages", "Messages sent (Anril confirmed)"),
    ("messages_whatsapp", "WhatsApp messages"),
    ("messages_instagram", "Instagram messages"),
    ("messages_messenger", "Messenger messages"),
    ("meta_conversations", "Meta messaging contacts"),
    ("meta_conversations_started", "Messaging conversations started"),
    ("meta_new_contacts", "New messaging contacts"),
    ("meta_conversations_replied", "Messaging conversations replied"),
    ("meta_blocks", "Messaging blocks"),
    ("conversation_rate", "Message rate"),
    ("meta_conversation_rate", "Meta messaging contact rate"),
    ("attribution_gap", "Tracking difference"),
    ("clicked_no_message", "No message"),
    ("no_message_rate", "No-message rate"),
    ("spend", "Spend"),
    ("cpc", "CPC"),
    ("cost_per_message", "Cost / sent message"),
    ("cost_per_meta_conversation", "Cost per messaging conversation started"),
    ("ctr", "CTR"),
    ("cpm", "CPM"),
    ("hot", "Hot"),
    ("hot_rate", "Hot lead rate"),
    ("cost_per_hot", "Cost / hot lead"),
]


def _budget_label(row: dict) -> str:
    """The table's single Budget cell: '₹500/day · Ad set', '₹20000 lifetime · Campaign'."""
    suffix = {"ad_set": " · Ad set", "campaign": " · Campaign"}.get(row.get("budget_level"), "")
    if row.get("daily_budget") is not None:
        return f"₹{round(row['daily_budget'])}/day{suffix}"
    if row.get("lifetime_budget") is not None:
        return f"₹{round(row['lifetime_budget'])} lifetime{suffix}"
    return ""


@router.get("/ad-performance/export", dependencies=[Depends(require_meta_ads_view)])
async def ad_performance_export(
    campaign_id: str | None = Query(None),
    adset_id: str | None = Query(None),
    ad_creative_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    delivery_status: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """CSV of the per-creative performance table, honoring the same filters."""
    from app.services.ad_performance import (
        _clip_date_from,
        build_creative_performance,
        delivery_label,
        excel_text,
    )
    from app.services.meta_ads_insights_sync import get_ads_setting
    db = get_supabase()
    rows = build_creative_performance(
        db, tenant_id,
        campaign_id=campaign_id, adset_id=adset_id, ad_creative_id=ad_creative_id,
        date_from=date_from, date_to=date_to, delivery_status=delivery_status,
    )
    # The dates the numbers actually cover: the table never reads before the history date.
    report_cells = {
        "reporting_starts": _clip_date_from(
            date_from, get_ads_setting(db, tenant_id, "meta_ads_sync_start_date")
        ) or "",
        "reporting_ends": date_to or datetime.now(timezone.utc).date().isoformat(),
    }
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([label for _, label in AD_PERFORMANCE_EXPORT_COLUMNS])
    for r in rows:
        by_channel = r.get("messages_by_channel") or {}
        channel_cells = {
            "messages_whatsapp": by_channel.get("whatsapp", 0),
            "messages_instagram": by_channel.get("instagram", 0),
            "messages_messenger": by_channel.get("messenger", 0),
            **report_cells,
            "meta_ad_id": excel_text(r.get("meta_ad_id")),
            "delivery_status": delivery_label(r.get("delivery_status")),
        }
        writer.writerow([
            _budget_label(r) if key == "budget"
            else channel_cells[key] if key in channel_cells
            else ("" if r.get(key) is None else r.get(key))
            for key, _ in AD_PERFORMANCE_EXPORT_COLUMNS
        ])
    filename = f"ad_performance_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/ad-sync-now", dependencies=[Depends(require_meta_ads_manage)])
async def ad_sync_now(tenant_id: str = Depends(get_tenant_id)):
    """Manually trigger the Meta Ads Insights sync for this tenant, returning
    a diagnostic result instead of waiting on the hourly scheduled job."""
    from app.services.meta_ads_insights_sync import sync_tenant_ad_insights_verbose
    db = get_supabase()
    return sync_tenant_ad_insights_verbose(db, tenant_id)
