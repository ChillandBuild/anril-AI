"""Instant forms (Meta lead ads): the Meta Ads > Instant forms screens.

Every route is tenant-scoped through get_tenant_id; the tables have no member
RLS policies, so this module is the only way in. Reads need meta_ads.view,
anything that changes settings or talks to Meta on the client's behalf needs
meta_ads.manage.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services import meta_lead_forms as forms_service
from app.services.meta_lead_forms import InstantFormsError

logger = logging.getLogger(__name__)
router = APIRouter()

require_view = require_permission("meta_ads.view")
require_manage = require_permission("meta_ads.manage")

IST = timezone(timedelta(hours=5, minutes=30))


def _range(date_from: str | None, date_to: str | None) -> tuple[str, str, str, str]:
    """(from, to, from_iso_utc, to_exclusive_iso_utc); IST days, default last 30."""
    today = datetime.now(IST).date()
    try:
        end = date.fromisoformat(date_to) if date_to else today
        start = date.fromisoformat(date_from) if date_from else end - timedelta(days=29)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Dates must look like 2026-11-09.") from exc
    if start > end:
        raise HTTPException(status_code=400, detail="The start date is after the end date.")
    lo = datetime.combine(start, datetime.min.time(), IST).astimezone(timezone.utc).isoformat()
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), IST).astimezone(timezone.utc).isoformat()
    return start.isoformat(), end.isoformat(), lo, hi


def _form_or_404(db, tenant_id: str, form_id: str) -> dict:
    rows = (
        db.table("meta_lead_forms").select("*").eq("tenant_id", tenant_id).eq("form_id", form_id).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="Form not found. Try Sync forms.")
    return rows[0]


def _spend_by_ad(db, tenant_id: str, ad_ids: set[str], date_from: str, date_to: str) -> dict[str, float] | None:
    """Live spend per ad from the connected ad account, or None if Meta can't say."""
    ad_ids = {a for a in ad_ids if a and a.isdigit()}
    if not ad_ids:
        return {}
    from app.services.meta_ads_fields import fetch_meta_insights_live
    from app.services.meta_ads_insights_sync import _get_ads_credentials

    credentials = _get_ads_credentials(db, tenant_id)
    if not credentials:
        return None
    try:
        rows = fetch_meta_insights_live(
            *credentials, date_from=date_from, date_to=date_to, keys=["spend"], ad_ids=ad_ids,
        )
    except Exception as exc:
        logger.warning("instant forms: spend fetch failed tenant=%s: %s", tenant_id, exc)
        return None
    out: dict[str, float] = {}
    for row in rows:
        try:
            out[str(row.get("meta_ad_id"))] = out.get(str(row.get("meta_ad_id")), 0.0) + float(
                (row.get("values") or {}).get("spend") or 0
            )
        except (TypeError, ValueError):
            continue
    return out


def _replied_lead_ids(db, tenant_id: str, rows: list[dict]) -> set[str]:
    """Leads who wrote back on WhatsApp after the form's template went out."""
    sent = {r["lead_id"]: r["template_sent_at"] for r in rows if r.get("lead_id") and r.get("template_sent_at")}
    if not sent:
        return set()
    replied: set[str] = set()
    ids = list(sent)
    for start in range(0, len(ids), 200):
        leads = (
            db.table("leads").select("id,last_inbound_at").eq("tenant_id", tenant_id)
            .in_("id", ids[start:start + 200]).execute()
        ).data or []
        for lead in leads:
            last = lead.get("last_inbound_at")
            if last and str(last) > str(sent.get(lead["id"]) or ""):
                replied.add(lead["id"])
    return replied


def _stats(rows: list[dict], replied: set[str], spend: dict[str, float] | None) -> dict:
    leads = len(rows)
    ad_ids = {r.get("ad_id") for r in rows if r.get("ad_id")}
    total_spend = None if spend is None else round(sum(spend.get(a, 0.0) for a in ad_ids), 2)
    return {
        "leads": leads,
        "with_phone": sum(1 for r in rows if r.get("phone")),
        "template_sent": sum(1 for r in rows if r.get("template_status") == "sent"),
        "template_failed": sum(1 for r in rows if r.get("template_status") == "failed"),
        "replied": sum(1 for r in rows if r.get("lead_id") in replied),
        "from_ads": sum(1 for r in rows if not r.get("is_organic")),
        "spend": total_spend,
        "cost_per_lead": round(total_spend / leads, 2) if total_spend and leads else None,
    }


def _rows_in_range(db, tenant_id: str, lo: str, hi: str, form_id: str | None = None) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        query = (
            db.table("meta_form_leads")
            .select("form_id,ad_id,is_organic,phone,lead_id,template_status,template_sent_at")
            .eq("tenant_id", tenant_id).gte("meta_created_at", lo).lt("meta_created_at", hi)
        )
        if form_id:
            query = query.eq("form_id", form_id)
        batch = query.order("meta_created_at", desc=True).range(offset, offset + 999).execute().data or []
        out.extend(batch)
        if len(batch) < 1000:
            return out
        offset += 1000


# ── Connection ──────────────────────────────────────────────────────────────


@router.get("/status", dependencies=[Depends(require_view)])
async def get_status(tenant_id: str = Depends(get_tenant_id)):
    status = await asyncio.to_thread(forms_service.connection_status, tenant_id)
    db = get_supabase()
    forms = db.table("meta_lead_forms").select("id", count="exact").eq("tenant_id", tenant_id).limit(1).execute()
    return {**status, "forms": forms.count or 0}


@router.post("/connect", dependencies=[Depends(require_manage)])
async def connect(background_tasks: BackgroundTasks, tenant_id: str = Depends(get_tenant_id)):
    """Turn on live form leads for the connected Page: subscribe the webhook,
    copy the forms, then import past leads in the background."""
    try:
        await asyncio.to_thread(forms_service.subscribe_leadgen, tenant_id)
        count = await asyncio.to_thread(forms_service.sync_forms, tenant_id)
    except InstantFormsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(forms_service.import_history, tenant_id)
    return {"forms": count, "importing": True}


@router.post("/sync", dependencies=[Depends(require_manage)])
async def sync(tenant_id: str = Depends(get_tenant_id)):
    """Re-read the form list and pick up any lead from the last two days."""
    try:
        count = await asyncio.to_thread(forms_service.sync_forms, tenant_id)
    except InstantFormsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await forms_service.catch_up(tenant_id)
    return {"forms": count}


# ── Overview and one form ──────────────────────────────────────────────────


@router.get("/overview", dependencies=[Depends(require_view)])
async def overview(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    start, end, lo, hi = _range(date_from, date_to)
    db = get_supabase()
    forms = (
        db.table("meta_lead_forms")
        .select("form_id,name,status,meta_created_at,template_id,questions")
        .eq("tenant_id", tenant_id).order("meta_created_at", desc=True).execute()
    ).data or []
    rows = await asyncio.to_thread(_rows_in_range, db, tenant_id, lo, hi)
    replied = await asyncio.to_thread(_replied_lead_ids, db, tenant_id, rows)
    spend = await asyncio.to_thread(
        _spend_by_ad, db, tenant_id, {r["ad_id"] for r in rows if r.get("ad_id")}, start, end,
    )
    template_names = _template_names(db, tenant_id, {f["template_id"] for f in forms if f.get("template_id")})
    by_form: dict[str, list[dict]] = {}
    for row in rows:
        by_form.setdefault(row["form_id"], []).append(row)
    last_lead, lead_ads = _lead_history_by_form(db, tenant_id)
    ad_names = await asyncio.to_thread(forms_service.ads_by_form, db, tenant_id)
    return {
        "date_from": start,
        "date_to": end,
        "spend_available": spend is not None,
        "totals": _stats(rows, replied, spend),
        "forms": [
            {
                "form_id": form["form_id"],
                "name": form.get("name") or "Untitled form",
                "status": form.get("status"),
                "created_at": form.get("meta_created_at"),
                "questions": len(form.get("questions") or []),
                "ad_names": ad_names.get(form["form_id"], []),
                # Only for a form no ad uses now: the ads its leads came from.
                "past_ad_names": [] if ad_names.get(form["form_id"]) else lead_ads.get(form["form_id"], []),
                "template_id": form.get("template_id"),
                "template_name": template_names.get(form.get("template_id") or ""),
                "last_lead_at": last_lead.get(form["form_id"]),
                **_stats(by_form.get(form["form_id"], []), replied, spend),
            }
            for form in forms
        ],
    }


def _template_names(db, tenant_id: str, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (
        db.table("message_templates").select("id,name").eq("tenant_id", tenant_id).in_("id", list(ids)).execute()
    ).data or []
    return {r["id"]: r["name"] for r in rows}


def _lead_history_by_form(db, tenant_id: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Each form's newest lead time, and the ads its leads came from (newest first).
    Meta forgets which ad an old form was on; every lead still names its ad."""
    rows = (
        db.table("meta_form_leads").select("form_id,meta_created_at,ad_name").eq("tenant_id", tenant_id)
        .order("meta_created_at", desc=True).limit(2000).execute()
    ).data or []
    last: dict[str, str] = {}
    ads: dict[str, list[str]] = {}
    for row in rows:
        last.setdefault(row["form_id"], row["meta_created_at"])
        name = row.get("ad_name")
        if name and name not in ads.setdefault(row["form_id"], []):
            ads[row["form_id"]].append(name)
    return last, ads


@router.get("/forms/{form_id}", dependencies=[Depends(require_view)])
async def get_form(
    form_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    if not form_id.isdigit():
        raise HTTPException(status_code=404, detail="Form not found.")
    start, end, lo, hi = _range(date_from, date_to)
    db = get_supabase()
    form = _form_or_404(db, tenant_id, form_id)
    rows = await asyncio.to_thread(_rows_in_range, db, tenant_id, lo, hi, form_id)
    replied = await asyncio.to_thread(_replied_lead_ids, db, tenant_id, rows)
    spend = await asyncio.to_thread(
        _spend_by_ad, db, tenant_id, {r["ad_id"] for r in rows if r.get("ad_id")}, start, end,
    )
    return {
        "form_id": form_id,
        "name": form.get("name") or "Untitled form",
        "status": form.get("status"),
        "locale": form.get("locale"),
        "created_at": form.get("meta_created_at"),
        "synced_at": form.get("synced_at"),
        "questions": form.get("questions") or [],
        "template_id": form.get("template_id"),
        "template_variables": form.get("template_variables") or [],
        "date_from": start,
        "date_to": end,
        "spend_available": spend is not None,
        "stats": _stats(rows, replied, spend),
    }


@router.get("/forms/{form_id}/leads", dependencies=[Depends(require_view)])
async def form_leads(
    form_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1, le=1000),
    limit: int = Query(50, ge=1, le=500),
    tenant_id: str = Depends(get_tenant_id),
):
    if not form_id.isdigit():
        raise HTTPException(status_code=404, detail="Form not found.")
    _, _, lo, hi = _range(date_from, date_to)
    db = get_supabase()
    query = (
        db.table("meta_form_leads")
        .select(
            "id,leadgen_id,meta_created_at,name,phone,email,answers,ad_id,ad_name,adset_name,campaign_name,"
            "platform,is_organic,lead_id,received_via,template_status,template_error,template_sent_at",
            count="exact",
        )
        .eq("tenant_id", tenant_id).eq("form_id", form_id)
        .gte("meta_created_at", lo).lt("meta_created_at", hi)
    )
    term = (search or "").strip()
    if term:
        # PostgREST or-filter: strip characters that would break its syntax.
        safe = "".join(ch for ch in term if ch.isalnum() or ch in " @.+-_")[:100]
        if safe:
            query = query.or_(f"name.ilike.*{safe}*,phone.ilike.*{safe}*,email.ilike.*{safe}*")
    start = (page - 1) * limit
    result = query.order("meta_created_at", desc=True).range(start, start + limit - 1).execute()
    rows = result.data or []
    replied = _replied_lead_ids(db, tenant_id, rows)
    for row in rows:
        row["replied"] = row.get("lead_id") in replied
    return {"data": rows, "total": result.count or 0, "page": page, "limit": limit}


def _csv_download(text: str, name: str) -> Response:
    safe = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in name).strip() or "leads"
    return Response(
        content=text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.csv"', "Cache-Control": "no-store"},
    )


@router.get("/forms/{form_id}/download", dependencies=[Depends(require_view)])
async def download_form_leads(form_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Every lead on the form, read live from Meta: a later download has the newer leads too."""
    if not form_id.isdigit():
        raise HTTPException(status_code=404, detail="Form not found.")
    db = get_supabase()
    form = _form_or_404(db, tenant_id, form_id)
    try:
        text = await asyncio.to_thread(forms_service.form_leads_csv, db, tenant_id, form_id)
    except InstantFormsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    today = datetime.now(IST).date().isoformat()
    return _csv_download(text, f"{form.get('name') or 'form'}_Leads_{today}")


@router.get("/ads/download", dependencies=[Depends(require_view)])
async def download_ad_leads(
    ad_ids: str = Query(..., max_length=4000),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """Leads from these ads in the chosen dates, read live from Meta (All ads > Results)."""
    ids = list(dict.fromkeys(a.strip() for a in ad_ids.split(",") if a.strip()))
    if not ids or len(ids) > 200 or not all(a.isdigit() for a in ids):
        raise HTTPException(status_code=400, detail="Pick between 1 and 200 ads.")
    start, end, lo, hi = _range(date_from, date_to)
    try:
        text = await asyncio.to_thread(
            forms_service.ads_leads_csv, get_supabase(), tenant_id, ids,
            datetime.fromisoformat(lo), datetime.fromisoformat(hi),
        )
    except InstantFormsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _csv_download(text, f"Leads_{start}_{end}")


# ── Template settings ──────────────────────────────────────────────────────


class TemplateVariable(BaseModel):
    source: str = Field(pattern="^(field|text)$")
    field: str | None = Field(None, max_length=100)
    text: str | None = Field(None, max_length=200)


class TemplateSettings(BaseModel):
    template_id: str | None = None
    variables: list[TemplateVariable] = Field(default_factory=list, max_length=20)


@router.get("/templates", dependencies=[Depends(require_view)])
async def approved_templates(tenant_id: str = Depends(get_tenant_id)):
    """Approved templates on the current WhatsApp number a form can send, with their
    blanks. Image / video / document headers are included when their file is saved."""
    templates = await asyncio.to_thread(forms_service.sendable_templates, get_supabase(), tenant_id)
    return {
        "data": [
            {
                "id": t["id"],
                "name": t["name"],
                "language": t.get("language") or "en",
                "body_text": t.get("body_text") or "",
                "blanks": forms_service.template_blanks(t),
                "header_media_type": (t.get("header_media_type") or "").upper() or None,
                "header_media_url": t.get("header_media_url"),
                "header_text": t.get("header_text"),
            }
            for t in templates
        ]
    }


@router.put("/forms/{form_id}/template", dependencies=[Depends(require_manage)])
async def set_template(form_id: str, payload: TemplateSettings, tenant_id: str = Depends(get_tenant_id)):
    """Choose what goes out when someone fills this form. None = send nothing."""
    if not form_id.isdigit():
        raise HTTPException(status_code=404, detail="Form not found.")
    db = get_supabase()
    form = _form_or_404(db, tenant_id, form_id)
    if not payload.template_id:
        db.table("meta_lead_forms").update({
            "template_id": None, "template_variables": [], "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", form["id"]).execute()
        return {"template_id": None, "template_variables": []}

    template = next((t for t in forms_service.sendable_templates(db, tenant_id) if t["id"] == payload.template_id), None)
    if not template:
        raise HTTPException(
            status_code=400,
            detail="Pick an approved template. One with an image, video or document header needs its file saved in Templates.",
        )
    blanks = forms_service.template_blanks(template)
    if len(payload.variables) > blanks:
        raise HTTPException(status_code=400, detail=f"This template has {blanks} blank(s).")
    fields = {q.get("key") for q in form.get("questions") or []} | {"first_name"}
    cleaned: list[dict] = []
    for variable in payload.variables:
        if variable.source == "field":
            if variable.field not in fields:
                raise HTTPException(status_code=400, detail="One blank points at a question this form doesn't have.")
            cleaned.append({"source": "field", "field": variable.field})
        else:
            text = " ".join((variable.text or "").split())
            if not text:
                raise HTTPException(status_code=400, detail="Fill in the fixed text, or pick a form answer.")
            cleaned.append({"source": "text", "text": text})
    db.table("meta_lead_forms").update({
        "template_id": payload.template_id, "template_variables": cleaned,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", form["id"]).execute()
    return {"template_id": payload.template_id, "template_variables": cleaned}


@router.post("/leads/{row_id}/send-template", dependencies=[Depends(require_manage)])
async def send_template_now(row_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Send (or retry) the form's template to one lead, from the leads table.
    An older lead that was only on this screen is added to Leads first, so the
    reply lands on a lead with the form answers."""
    try:
        uuid.UUID(row_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Lead not found.") from exc
    db = get_supabase()
    rows = (
        db.table("meta_form_leads").select("id,template_status,phone")
        .eq("tenant_id", tenant_id).eq("id", row_id).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="Lead not found.")
    row = rows[0]
    if row["template_status"] in ("sent", "sending"):
        raise HTTPException(status_code=400, detail="The template was already sent to this lead.")
    if not row.get("phone"):
        raise HTTPException(status_code=400, detail="This lead didn't leave a phone number.")
    db.table("meta_form_leads").update({"template_status": "pending", "template_error": None}).eq(
        "id", row_id
    ).eq("tenant_id", tenant_id).in_("template_status", ["failed", "no_template", "skipped_old"]).execute()
    await asyncio.to_thread(forms_service.ensure_lead, db, tenant_id, row_id)
    status = await forms_service.send_form_template(db, tenant_id, row_id, manual=True)
    refreshed = (
        db.table("meta_form_leads").select("template_status,template_error,template_sent_at")
        .eq("id", row_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or [{}]
    return {"status": status, **refreshed[0]}
