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
from app.dependencies.tenant import get_tenant_and_role, get_tenant_id, require_owner, require_permission
from app.services.download_gate import log_download, require_download
from app.services.inbound_leads_logic import INBOUND_SOURCES, lead_result
from app.services.google_ads_attribution import build_tracked_wa_link, slugify_campaign
from app.routes.leads import _sanitize_search

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
    "qr": "QR",
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


class InboundFilters:
    """Engage > Inbound leads filters. One object feeds the list, the counts (/summary) and
    the CSV, so the chips, the cards, the table and the download always agree."""

    def __init__(self, *, origin: str = "all", segment: str | None = None, result: str | None = None,
                 waiting: bool = False, search: str | None = None, meta_ad_id: str | None = None,
                 source: str | None = None, date_from: str | None = None, date_to: str | None = None,
                 tag: str | None = None):
        self.origin = origin
        self.segment = segment
        self.result = result
        self.waiting = waiting
        self.search = _sanitize_search(search)
        self.meta_ad_id = meta_ad_id
        self.source = source
        self.date_from = date_from
        self.date_to = date_to
        self.tag = " ".join((tag or "").split()) or None

    def but(self, **changes) -> "InboundFilters":
        copy = InboundFilters()
        copy.__dict__.update(self.__dict__)
        copy.__dict__.update(changes)
        return copy


def _inbound_filters(
    origin: str = Query("all", pattern="^(all|organic|ad)$"),
    segment: str | None = Query(None, pattern="^[ABCD]$"),
    result: str | None = Query(None, pattern="^(none|booked|paid|lost)$"),
    waiting: bool = Query(False),
    search: str | None = Query(None, max_length=100),
    meta_ad_id: str | None = Query(None, pattern="^[0-9]{1,30}$"),
    source: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tag: str | None = Query(None, max_length=30),
) -> InboundFilters:
    return InboundFilters(origin=origin, segment=segment, result=result, waiting=waiting, search=search,
                          meta_ad_id=meta_ad_id, source=source, date_from=date_from, date_to=date_to, tag=tag)


# Result of a lead, the same order as Chats' inbox (migration 272 inbox_chat_rows):
# Came / Paid (marked converted, or a won order) > Lost > Booked > none.
_PAID = "converted_at.not.is.null,won_deal_count.gte.1"


def _not_paid(q):
    return q.is_("converted_at", "null").eq("won_deal_count", 0)


def _apply_result(q, result: str | None):
    if result == "paid":
        return q.or_(_PAID)
    if result == "lost":
        return _not_paid(q.not_.is_("lost_at", "null"))
    if result == "booked":
        return _not_paid(q.not_.is_("booked_at", "null").is_("lost_at", "null"))
    if result == "none":
        return _not_paid(q.is_("booked_at", "null").is_("lost_at", "null"))
    return q


def _apply_inbound(q, tenant_id: str, f: InboundFilters):
    q = (
        q.eq("tenant_id", tenant_id)
        .in_("source", list(INBOUND_SOURCES))
        .is_("deleted_at", "null")
    )
    origin = f.origin
    segment = f.segment
    # Instant form leads are ad leads without an ad_campaigns row.
    if origin == "ad":
        q = q.or_("ad_campaign_id.not.is.null,source.eq.meta_form")
    elif origin == "organic":
        q = q.is_("ad_campaign_id", "null").neq("source", "meta_form")
    if segment:
        q = q.eq("segment", segment)
    q = _apply_result(q, f.result)
    if f.waiting:
        # waiting_since is a computed field (migrations 282/283): an inbound message nothing was sent after.
        q = q.not_.is_("last_inbound_at", "null").not_.is_("waiting_since", "null")
    if f.search:
        term = f.search
        q = q.or_(f"name.ilike.*{term}*,phone.ilike.*{term}*,ad_name.ilike.*{term}*")
    if f.meta_ad_id:
        # One ad: the people with an attribution row for it (the rows Meta Ads counts).
        q = q.eq("lead_meta_ad_attributions.meta_ad_id", f.meta_ad_id)
    if f.source:
        q = q.eq("source", f.source)
    if f.date_from:
        q = q.gte("created_at", f.date_from)
    if f.date_to:
        q = q.lte("created_at", f.date_to)
    return q


_ROW_COLUMNS = (
    "id,phone,name,source,score,segment,created_at,ad_campaign_id,ad_name,assigned_to,ai_enabled,"
    "needs_human_attention,needs_human_intervention,converted_at,booked_at,booked_for,lost_at,lost_reason,lost_auto,"
    "collected_data,last_inbound_at,waiting_since,last_message,won_deal_count"
)


_NO_LEAD = "00000000-0000-0000-0000-000000000000"  # an id no lead has: "the tag matches nobody"


def _leads_query(db, columns: str, tenant_id: str, f: InboundFilters, count: str | None = None):
    """leads filtered by f. The one-ad filter needs the attribution rows joined in; so does the tag filter
    (lead_tags, Customers > tags). A tag is matched ignoring upper / lower case; one nobody has matches nobody."""
    spellings: list[str] = []
    if f.tag:
        from app.services.lead_tags import tag_spellings
        spellings = tag_spellings(db, tenant_id, f.tag)
        if spellings:
            columns += ",lead_tags!inner()"
    if f.meta_ad_id:
        columns += ",lead_meta_ad_attributions!inner(meta_ad_id)"
    q = _apply_inbound(db.table("leads").select(columns, count=count), tenant_id, f)
    if f.tag:
        if not spellings:
            return q.eq("id", _NO_LEAD)
        q = q.eq("lead_tags.tenant_id", tenant_id)
        q = q.eq("lead_tags.tag", spellings[0]) if len(spellings) == 1 else q.in_("lead_tags.tag", spellings)
    return q


def _fetch_inbound_leads(db, tenant_id: str, f: InboundFilters, *, sort: str = "newest",
                         limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
    """A page of inbound leads (source in INBOUND_SOURCES) and the total. Two queries, no JOIN.
    sort "waiting": longest waiting first, then newest."""
    q = _leads_query(db, _ROW_COLUMNS, tenant_id, f)
    if sort == "waiting":
        q = q.order("waiting_since", desc=False, nullsfirst=False)
    rows = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute().data or []
    count = _leads_query(db, "id", tenant_id, f, count="exact").limit(1).execute()
    return rows, count.count or len(rows)


def _count(db, tenant_id: str, f: InboundFilters) -> int:
    return _leads_query(db, "id", tenant_id, f, count="exact").limit(1).execute().count or 0


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


_KEYWORD_CHUNK = 500  # well under PostgREST's 1000-row response cap


def _fetch_first_keywords(db, tenant_id: str, lead_ids: list[str]) -> dict[str, str]:
    """
    For each lead_id, fetch the first inbound message (the CTA keyword/pre-fill text).
    Returns {lead_id: first_message_content}.
    """
    if not lead_ids:
        return {}
    # One row per lead from a DB function (migration 253). Fetching every
    # inbound message and keeping the first in Python hit PostgREST's 1000-row
    # cap, which blanked the NEWEST leads once the page's leads had sent more
    # than 1000 messages. Chunked so a big CSV export stays under the cap too.
    keyword_map: dict[str, str] = {}
    for i in range(0, len(lead_ids), _KEYWORD_CHUNK):
        rows = db.rpc(
            "first_inbound_messages",
            {"p_tenant": tenant_id, "p_lead_ids": lead_ids[i:i + _KEYWORD_CHUNK]},
        ).execute().data or []
        for row in rows:
            lid = row.get("lead_id")
            if lid:
                keyword_map[lid] = (row.get("content") or "").strip()
    return keyword_map


def _fetch_caller_names(db, tenant_id: str, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (db.table("callers").select("id,name").eq("tenant_id", tenant_id).in_("id", ids).execute()).data or []
    return {str(r["id"]): r.get("name") or "" for r in rows}


def _fetch_open_orders(db, tenant_id: str, lead_ids: list[str]) -> dict[str, dict]:
    """The order each row's "Open order" points at: the newest won or waiting-for-payment deal."""
    if not lead_ids:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(lead_ids), _KEYWORD_CHUNK):
        rows = (db.table("deals").select("id,lead_id,deal_number,stage,total_paise,created_at,won_at")
                .eq("tenant_id", tenant_id).in_("lead_id", lead_ids[i:i + _KEYWORD_CHUNK])
                .in_("stage", ["won", "awaiting_payment"]).execute()).data or []
        for d in rows:
            at = d.get("won_at") or d.get("created_at") or ""
            current = out.get(d["lead_id"])
            if current is None or at > current["_at"]:
                out[d["lead_id"]] = {"id": str(d["id"]), "number": d.get("deal_number"), "stage": d.get("stage"),
                                     "total_paise": int(d.get("total_paise") or 0), "_at": at}
    for d in out.values():
        d.pop("_at", None)
    return out


# Business / city as a form gave them (Instant form answers, IndiaMART / JustDial enquiry).
# Chat leads have neither until the AI saves details from chats (backlog: Inbound leads v2, Q2).
_BUSINESS_KEYS = ("business", "business_name", "company", "company_name", "shop_name", "organisation",
                  "organization", "firm")
_CITY_KEYS = ("city", "town", "location", "district")


def _from_collected(collected, keys: tuple[str, ...]) -> str | None:
    if not isinstance(collected, dict):
        return None
    lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in collected.items()}
    for key in keys:
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return None


def _handled_by(lead: dict, callers: dict[str, str]) -> dict:
    """Who has the chat: a team member, the AI agent, or nobody (AI off and nobody assigned)."""
    needs_you = bool(lead.get("needs_human_attention") or lead.get("needs_human_intervention"))
    if lead.get("assigned_to"):
        return {"kind": "person", "name": callers.get(str(lead["assigned_to"])) or "A team member",
                "needs_you": needs_you}
    if lead.get("ai_enabled") is not False and not needs_you:
        return {"kind": "ai", "name": "AI agent", "needs_you": False}
    return {"kind": "nobody", "name": None, "needs_you": needs_you}


def _enrich(
    leads: list[dict],
    campaign_map: dict[str, str],
    keyword_map: dict[str, str],
    callers: dict[str, str] | None = None,
    orders: dict[str, dict] | None = None,
) -> list[dict]:
    """Attach campaign name, keyword, origin, result, reply status and who handles it."""
    callers = callers or {}
    orders = orders or {}
    enriched = []
    for lead in leads:
        cid = lead.get("ad_campaign_id") or ""
        src = lead.get("source", "whatsapp")
        last = lead.get("last_message") if isinstance(lead.get("last_message"), dict) else None
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
            # No campaign id (organic, or an instant form) means no campaign:
            # "Unknown Campaign" is only for an id we can't find a name for.
            "campaign_name": campaign_map.get(cid, "Unknown Campaign") if cid else "—",
            "ad_name": lead.get("ad_name"),
            "keyword": keyword_map.get(lead.get("id", ""), "—") or "—",
            "business": _from_collected(lead.get("collected_data"), _BUSINESS_KEYS),
            "city": _from_collected(lead.get("collected_data"), _CITY_KEYS),
            "last_message": last,
            "waiting_since": lead.get("waiting_since"),
            "last_inbound_at": lead.get("last_inbound_at"),
            "result": lead_result(lead),
            "booked_for": lead.get("booked_for"),
            "lost_reason": lead.get("lost_reason"),
            "lost_auto": bool(lead.get("lost_auto")),
            "order": orders.get(lead.get("id", "")),
            "handled_by": _handled_by(lead, callers),
        })
    return enriched


def _enrich_page(db, tenant_id: str, leads: list[dict]) -> list[dict]:
    lead_ids = [l["id"] for l in leads]
    campaign_ids = list({l["ad_campaign_id"] for l in leads if l.get("ad_campaign_id")})
    caller_ids = sorted({str(l["assigned_to"]) for l in leads if l.get("assigned_to")})
    return _enrich(
        leads,
        _fetch_campaign_names(db, tenant_id, campaign_ids),
        _fetch_first_keywords(db, tenant_id, lead_ids),
        _fetch_caller_names(db, tenant_id, caller_ids),
        _fetch_open_orders(db, tenant_id, lead_ids),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

# ── Result step names (Booked / Came / Paid / Lost), renamable by the owner ──────────────────
RESULT_LABELS_KEY = "inbound_result_labels"
DEFAULT_RESULT_LABELS = {"booked": "Booked", "paid": "Came / Paid", "lost": "Lost"}


class ResultLabelsIn(BaseModel):
    booked: str = Field(min_length=1, max_length=30)
    paid: str = Field(min_length=1, max_length=30)
    lost: str = Field(min_length=1, max_length=30)


def result_labels(tenant_id: str) -> dict:
    """The tenant's names for the result steps, defaults filled in for any not renamed."""
    import json
    from app.config_dynamic import get_setting
    raw = get_setting(RESULT_LABELS_KEY, fallback=None, tenant_id=tenant_id)
    try:
        saved = json.loads(raw) if raw else {}
    except ValueError:
        saved = {}
    out = dict(DEFAULT_RESULT_LABELS)
    for key in out:
        value = saved.get(key) if isinstance(saved, dict) else None
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:30]
    return out


@router.get("/result-labels")
async def get_result_labels(tenant_id: str = Depends(get_tenant_id)):
    return result_labels(tenant_id)


@router.put("/result-labels")
async def put_result_labels(body: ResultLabelsIn, ctx: dict = Depends(require_owner)):
    """Owner only: e.g. "Site visit booked" / "Advance paid" / "Lost". Names only; the rules stay."""
    import json
    from app.config_dynamic import invalidate_cache
    labels = {k: " ".join(v.split()) for k, v in body.model_dump().items()}
    if len({v.lower() for v in labels.values()}) < 3:
        raise HTTPException(status_code=400, detail="Give each step a different name")
    get_supabase().table("app_settings").upsert({
        "tenant_id": ctx["tenant_id"],
        "key": RESULT_LABELS_KEY,
        "value": json.dumps(labels),
        "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()
    invalidate_cache(RESULT_LABELS_KEY)
    return result_labels(ctx["tenant_id"])


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


@router.get("/ads")
async def list_ads(tenant_id: str = Depends(get_tenant_id)):
    """Every messaging ad, one per Meta ad, for the Inbound leads "which ad" filter.
    Ads that share a name get their campaign added so they can be told apart."""
    db = get_supabase()
    try:
        ads = (
            db.table("ad_creatives")
            .select("meta_ad_id,creative_label,campaign_id")
            .eq("tenant_id", tenant_id)
            .neq("messaging_channels", "{}")
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.error(f"inbound-leads ads fetch error: {e}")
        return {"data": []}
    by_id: dict[str, dict] = {}
    for ad in ads:
        if ad.get("meta_ad_id") and ad["meta_ad_id"] not in by_id:
            by_id[ad["meta_ad_id"]] = ad
    names = _fetch_campaign_names(db, tenant_id, sorted({a["campaign_id"] for a in by_id.values() if a.get("campaign_id")}))
    label_count: dict[str, int] = {}
    for ad in by_id.values():
        label = (ad.get("creative_label") or "Untitled ad").strip()
        label_count[label.lower()] = label_count.get(label.lower(), 0) + 1
    out = []
    for meta_ad_id, ad in by_id.items():
        label = (ad.get("creative_label") or "Untitled ad").strip()
        campaign = names.get(ad.get("campaign_id") or "")
        if label_count[label.lower()] > 1 and campaign:
            label = f"{label} · {campaign}"
        out.append({"meta_ad_id": meta_ad_id, "name": label})
    out.sort(key=lambda a: a["name"].lower())
    return {"data": out}


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
    f: InboundFilters = Depends(_inbound_filters),
    sort: str = Query("newest", pattern="^(newest|waiting)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
):
    """Inbound leads (organic + ad) with their result, reply status and who handles them."""
    db = get_supabase()
    offset = (page - 1) * limit
    try:
        leads, total = _fetch_inbound_leads(db, tenant_id, f, sort=sort, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"inbound-leads list error: {e}")
        raise HTTPException(status_code=503, detail="Couldn't load inbound leads right now. Nothing is lost; try again.")
    if not leads:
        return {"data": [], "total": total, "page": page, "limit": limit}
    try:
        enriched = _enrich_page(db, tenant_id, leads)
    except Exception as e:
        logger.error(f"inbound-leads enrich error: {e}")
        raise HTTPException(status_code=503, detail="Couldn't load inbound leads right now. Nothing is lost; try again.")
    return {"data": enriched, "total": total, "page": page, "limit": limit}


@router.get("/summary")
async def inbound_leads_summary(
    f: InboundFilters = Depends(_inbound_filters),
    tenant_id: str = Depends(get_tenant_id),
):
    """Counts for the Interest and Result chips and the top cards. Each chip group is
    counted without its own filter (so picking Hot still shows how many Warm there are),
    but with every other filter on screen."""
    db = get_supabase()
    try:
        base = f.but(segment=None, result=None, waiting=False)
        by_segment = {s: _count(db, tenant_id, f.but(segment=s, waiting=False)) for s in ("A", "B", "C", "D")}
        by_result = {r: _count(db, tenant_id, f.but(result=r, waiting=False)) for r in ("booked", "paid", "lost")}
        return {
            "total": _count(db, tenant_id, base.but(segment=f.segment, result=f.result)),
            "segments": by_segment,
            "results": by_result,
            "waiting": _count(db, tenant_id, f.but(waiting=True)),
            # Booked > came / paid: everyone booked or paid in these filters, and how many paid.
            "booked_or_paid": by_result["booked"] + by_result["paid"],
        }
    except Exception as e:
        logger.error(f"inbound-leads summary error: {e}")
        raise HTTPException(status_code=503, detail="Couldn't count inbound leads right now.")


@router.get("/export")
async def export_inbound_leads(
    f: InboundFilters = Depends(_inbound_filters),
    ctx: dict = Depends(get_tenant_and_role),
):
    """CSV of exactly the list on screen (every filter, up to 5000 rows).

    Owner, or a role with leads.download ("Download lists"); each download is written to the
    Activity log with the filters used."""
    require_download(ctx)
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    try:
        leads, _ = _fetch_inbound_leads(db, tenant_id, f, limit=5000, offset=0)
    except Exception as e:
        logger.error(f"inbound-leads export error: {e}")
        raise HTTPException(status_code=503, detail="Couldn't prepare the download right now.")

    FIELDNAMES = [
        "name", "phone", "business", "city", "interest", "result", "booking_date", "came_from",
        "origin", "ad_campaign", "ad", "handled_by", "last_message_date", "first_message", "date_joined_ist",
        "score",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()

    enriched: list[dict] = []
    if leads:
        try:
            enriched = []
            for i in range(0, len(leads), _KEYWORD_CHUNK):
                enriched.extend(_enrich_page(db, tenant_id, leads[i:i + _KEYWORD_CHUNK]))
        except Exception as e:
            logger.error(f"inbound-leads export enrich error: {e}")
            raise HTTPException(status_code=503, detail="Couldn't prepare the download right now.")
    labels = result_labels(tenant_id)
    for lead in enriched:
        last = lead.get("last_message") or {}
        handled = lead.get("handled_by") or {}
        writer.writerow({
            "name": lead["name"],
            "phone": lead["phone"],
            "business": lead.get("business") or "",
            "city": lead.get("city") or "",
            "interest": lead["segment_label"],
            "result": labels.get(lead["result"], ""),
            "booking_date": _fmt_ist(lead["booked_for"]) if lead.get("booked_for") else "",
            "came_from": lead["channel_label"],
            "origin": lead["origin"],
            "ad_campaign": lead["campaign_name"],
            "ad": lead.get("ad_name") or "",
            "handled_by": handled.get("name") or ("Nobody" if handled.get("kind") == "nobody" else ""),
            "last_message_date": _fmt_ist(last["at"]) if last.get("at") else "",
            "first_message": lead["keyword"],
            "date_joined_ist": _fmt_ist(lead["created_at"]),
            "score": lead["score"],
        })

    log_download(db, ctx, list_name="Inbound leads", row_count=len(enriched), filters={
        "origin": None if f.origin == "all" else f.origin, "interest": f.segment, "result": f.result,
        "waiting": f.waiting, "search": f.search, "ad": f.meta_ad_id, "source": f.source,
        "date_from": f.date_from, "date_to": f.date_to, "tag": f.tag,
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


@router.get("/ad-creatives/{ad_creative_id}/people", dependencies=[Depends(require_meta_ads_view)])
async def ad_creative_people(
    ad_creative_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """The people behind one messaging ad's "Actually messaged" count, for its panel."""
    from app.services.ad_performance import build_ad_people

    d_from = _parse_day(date_from, "date_from") if date_from else None
    d_to = _parse_day(date_to, "date_to") if date_to else None
    people = build_ad_people(get_supabase(), tenant_id, ad_creative_id, date_from=d_from, date_to=d_to)
    if people is None:
        raise HTTPException(status_code=404, detail="Ad not found")
    return {"data": people}


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
        # Meta said the token is expired or invalid (code 190); cleared by the next good sync or reconnect.
        "token_expired": bool(get_ads_setting(db, tenant_id, "meta_ads_token_expired")),
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
    ("schedule", "Schedule"),
    ("last_significant_edit", "Last significant edit"),
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
    ("cost_per_messaging_contact", "Cost per messaging contact"),
    ("cost_per_new_messaging_contact", "Cost per new messaging contact"),
    ("conversation_rate", "Message rate"),
    ("meta_conversation_rate", "Meta messaging contact rate"),
    ("messaging_reply_rate", "Messaging reply rate"),
    ("messaging_block_rate", "Messaging block rate"),
    ("meta_anril_contact_match_rate", "Meta-to-Anril contact match rate"),
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
    ("booked", "Booked"),
    ("paid", "Paid"),
    ("lost", "Lost"),
    ("revenue", "Earned"),
    ("cost_per_booking", "Cost / booking"),
    ("roas", "Earned per ₹1"),
]


def _budget_label(row: dict) -> str:
    """The table's single Budget cell: '₹500/day · Ad set', '₹20000 lifetime · Campaign'."""
    suffix = {"ad_set": " · Ad set", "campaign": " · Campaign"}.get(row.get("budget_level"), "")
    if row.get("daily_budget") is not None:
        return f"₹{round(row['daily_budget'])}/day{suffix}"
    if row.get("lifetime_budget") is not None:
        return f"₹{round(row['lifetime_budget'])} lifetime{suffix}"
    return ""


def _schedule_label(row: dict) -> str:
    """The table's Schedule cell, as dates: '2026-11-01 – Ongoing', '2026-11-01 – 2026-11-30'."""
    start = (row.get("schedule_start") or "")[:10] or "—"
    end = (row.get("schedule_end") or "")[:10] or "Ongoing"
    return f"{start} – {end}"


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
            "schedule": _schedule_label(r),
            "last_significant_edit": (r.get("last_significant_edit") or "")[:10],
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
