"""Catalogue → Forms: the client's own WhatsApp Forms (Phase 2).

Every route is tenant-scoped through the caller's context and only works when the operator
switched WhatsApp Forms on for the tenant. Same rule as the Services page: reading needs
services.view or settings.view; changing, publishing and archiving need services.manage or
settings.manage; sending a form from a chat needs conversations.reply.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_any_permission, require_permission
from app.services import form_texts
from app.services import whatsapp_form_reach as reach
from app.services import whatsapp_live_forms as live
from app.services import whatsapp_forms as wf

router = APIRouter()
# Meta's encrypted requests for live forms: no Anril login (Meta can't have one); the
# request is authenticated by decrypting it with this business's private key, plus Meta's
# X-Hub-Signature-256 when an app secret is configured.
public_router = APIRouter()
require_read = require_any_permission("services.view", "settings.view")
require_manage = require_any_permission("services.manage", "settings.manage")
require_reply = require_permission("conversations.reply")


def _db_on(ctx: dict):
    db = get_supabase()
    if not wf.is_enabled(db, ctx["tenant_id"]):
        raise HTTPException(status_code=403, detail="WhatsApp Forms is not switched on for this account.")
    return db


def _uuid_or_404(value: str) -> str:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Form not found.") from exc
    return value


def _design_or_404(db, tenant_id: str, design_id: str) -> dict:
    design = wf.get_design(db, tenant_id, _uuid_or_404(design_id))
    if not design or design.get("archived"):
        raise HTTPException(status_code=404, detail="Form not found.")
    return design


def _counts(db, tenant_id: str, form_version_ids: list[str]) -> int:
    if not form_version_ids:
        return 0
    result = (
        db.table("whatsapp_form_responses").select("id", count="exact").eq("tenant_id", tenant_id)
        .in_("form_id", form_version_ids).limit(1).execute()
    )
    return result.count or 0


def _version_ids(db, tenant_id: str, design_id: str | None) -> list[str]:
    query = db.table("whatsapp_forms").select("id").eq("tenant_id", tenant_id)
    query = query.eq("kind", "custom").eq("design_id", design_id) if design_id else query.eq("kind", "intake")
    return [r["id"] for r in query.execute().data or []]


def _view(db, tenant_id: str, design: dict) -> dict:
    return {
        **{k: design.get(k) for k in ("id", "name", "language", "fields", "texts", "created_at", "updated_at")},
        "kind": design.get("kind") or "standard",
        "settings": live.clean_settings(design.get("kind") or "standard", design.get("settings")),
        "triggers": reach.clean_triggers(design.get("triggers")),
        "stats": reach.stats(db, tenant_id, design["id"]),
        "status": wf.version_status(db, tenant_id, design["id"]),
        "responses": _counts(db, tenant_id, _version_ids(db, tenant_id, design["id"])),
        "problems": wf.design_problems(design),
        "live": bool(wf.live_custom_form(db, tenant_id, design)),
    }


# ── texts and starters (what the builder offers) ─────────────────────────────


@router.get("/setup")
def setup(ctx: dict = Depends(require_read)):
    """Languages, every editable text with its starting value per language, Meta's limits,
    question types and the starter forms. The builder reads all of its wording from here."""
    _db_on(ctx)
    return {
        "languages": [{"key": k, "name": form_texts.LANGUAGE_NAMES[k]} for k in form_texts.LANGUAGES],
        "texts": form_texts.PRESETS,
        "text_limits": form_texts.LIMITS,
        "field_types": list(form_texts.FIELD_TYPES),
        "label_limits": form_texts.LABEL_LIMITS,
        "option_limit": form_texts.OPTION_LIMIT,
        "max_options": form_texts.MAX_OPTIONS,
        "max_fields": form_texts.MAX_FIELDS,
        "starters": [
            {"key": key, "names": dict(zip(form_texts.LANGUAGES, spec["names"]))}
            for key, spec in form_texts.STARTERS.items()
        ],
        # Live forms (Phase 4): their own starting names and settings.
        "live_kinds": [
            {"key": "order", "names": dict(zip(form_texts.LANGUAGES, LIVE_NAMES["order"])),
             "settings": live.ORDER_DEFAULTS},
            {"key": "booking", "names": dict(zip(form_texts.LANGUAGES, LIVE_NAMES["booking"])),
             "settings": live.BOOKING_DEFAULTS},
        ],
    }


LIVE_NAMES = {
    "order": ("Product order", "பொருள் ஆர்டர்", "Product order"),
    "booking": ("Appointment booking", "சந்திப்பு முன்பதிவு", "Appointment booking"),
}


# ── forms ────────────────────────────────────────────────────────────────────


@router.get("/forms")
def list_forms(ctx: dict = Depends(require_read)):
    db = _db_on(ctx)
    tenant_id = ctx["tenant_id"]
    designs = (
        db.table("whatsapp_form_designs").select("*").eq("tenant_id", tenant_id).eq("archived", False)
        .order("created_at", desc=True).execute()
    ).data or []
    from app.services.intake import get_intake_config

    config = get_intake_config(tenant_id, db=db)
    return {
        "services_form": {
            "collect_with": config.get("collect_with") or "chat",
            "selling_on": bool(config.get("enabled")),
            "status": wf.version_status(db, tenant_id),
            "responses": _counts(db, tenant_id, _version_ids(db, tenant_id, None)),
            "stats": reach.stats(db, tenant_id, None),
        },
        "forms": [_view(db, tenant_id, d) for d in designs],
    }


class NewForm(BaseModel):
    starter: str | None = None  # a key from /setup starters, "order" / "booking" (live forms); None = blank
    language: str = "en"
    name: str | None = Field(None, max_length=120)


@router.post("/forms")
def create_form(payload: NewForm, ctx: dict = Depends(require_manage)):
    db = _db_on(ctx)
    language = payload.language if payload.language in form_texts.LANGUAGES else "en"
    kind, settings = "standard", {}
    if payload.starter in LIVE_NAMES:
        kind = payload.starter
        settings = live.clean_settings(kind, None)
        content = {"name": LIVE_NAMES[kind][form_texts.LANGUAGES.index(language)], "fields": []}
    elif payload.starter:
        if payload.starter not in form_texts.STARTERS:
            raise HTTPException(status_code=400, detail="Unknown starter form.")
        content = form_texts.starter(payload.starter, language)
    else:
        content = {"name": "", "language": language, "fields": [], "texts": {}}
    name = ((payload.name or "").strip() or content["name"] or "New form").strip()[:120]
    row = db.table("whatsapp_form_designs").insert({
        "tenant_id": ctx["tenant_id"], "name": name, "language": language, "fields": content["fields"],
        "texts": {}, "created_by": ctx.get("user_id"), "kind": kind, "settings": settings,
    }).execute().data[0]
    return _view(db, ctx["tenant_id"], row)


@router.get("/forms/{design_id}")
def get_form(design_id: str, ctx: dict = Depends(require_read)):
    db = _db_on(ctx)
    return _view(db, ctx["tenant_id"], _design_or_404(db, ctx["tenant_id"], design_id))


class FieldIn(BaseModel):
    key: str = Field(max_length=40)
    type: str
    label: str = Field(max_length=200)
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=200)


class FormIn(BaseModel):
    name: str = Field(max_length=120)
    language: str
    fields: list[FieldIn] = Field(max_length=form_texts.MAX_FIELDS)
    texts: dict[str, str] = Field(default_factory=dict)
    # When Anril sends it by itself (whatsapp_form_reach.clean_triggers); None = keep as saved.
    triggers: dict | None = None
    # A live form's options (whatsapp_live_forms.clean_settings); None = keep as saved.
    settings: dict | None = None


@router.put("/forms/{design_id}")
def save_form(design_id: str, payload: FormIn, ctx: dict = Depends(require_manage)):
    """Save the draft. Nothing reaches customers until Publish."""
    db = _db_on(ctx)
    tenant_id = ctx["tenant_id"]
    current = _design_or_404(db, tenant_id, design_id)
    texts = {k: v for k, v in payload.texts.items() if isinstance(v, str) and v.strip()}
    triggers = payload.triggers if payload.triggers is not None else current.get("triggers")
    kind = current.get("kind") or "standard"  # a form's type is set when it's created
    design = {
        "name": payload.name.strip(), "language": payload.language,
        "fields": [f.model_dump() for f in payload.fields] if kind != "order" else [], "texts": texts,
        "triggers": reach.clean_triggers(triggers), "kind": kind,
        "settings": live.clean_settings(kind, payload.settings if payload.settings is not None else current.get("settings")),
    }
    problems = wf.design_problems(design) + reach.trigger_problems(triggers)
    if problems:
        raise HTTPException(status_code=400, detail=problems[0])
    row = db.table("whatsapp_form_designs").update({**design, "updated_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("id", design_id).eq("tenant_id", tenant_id).execute().data[0]
    return _view(db, tenant_id, row)


@router.post("/forms/{design_id}/publish")
async def publish_form(design_id: str, ctx: dict = Depends(require_manage)):
    db = _db_on(ctx)
    tenant_id = ctx["tenant_id"]
    _design_or_404(db, tenant_id, design_id)
    try:
        await wf.publish_design(db, tenant_id, design_id)
    except wf.FormBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _view(db, tenant_id, _design_or_404(db, tenant_id, design_id))


@router.delete("/forms/{design_id}")
async def archive_form(design_id: str, ctx: dict = Depends(require_manage)):
    """Archive: hidden from the list, stopped on WhatsApp. Its answers stay."""
    db = _db_on(ctx)
    _design_or_404(db, ctx["tenant_id"], design_id)
    await wf.retire_design(db, ctx["tenant_id"], design_id)
    return {"archived": True}


# ── answers ──────────────────────────────────────────────────────────────────


def _responses(db, tenant_id: str, design_id: str | None, page: int, limit: int):
    ids = _version_ids(db, tenant_id, design_id)
    if not ids:
        return [], 0
    start = (page - 1) * limit
    result = (
        db.table("whatsapp_form_responses")
        .select("id, form_id, lead_id, answers, outcome, created_at, leads(name, phone)", count="exact")
        .eq("tenant_id", tenant_id).in_("form_id", ids)
        .order("created_at", desc=True).range(start, start + limit - 1).execute()
    )
    return result.data or [], result.count or 0


def _rows(db, tenant_id: str, design: dict | None, raw: list[dict]) -> tuple[list[str], list[dict]]:
    """Column labels and readable rows. Labels come from each submission's own form version."""
    versions = {
        v["id"]: v for v in (
            db.table("whatsapp_forms").select("id, answer_map").eq("tenant_id", tenant_id)
            .in_("id", list({r["form_id"] for r in raw if r.get("form_id")}) or ["00000000-0000-0000-0000-000000000000"])
            .execute().data or []
        )
    }
    labels: list[str] = []
    rows = []
    for r in raw:
        answer_map = (versions.get(r.get("form_id")) or {}).get("answer_map") or {}
        if answer_map.get("kind") in ("order", "booking"):
            pairs = live.live_pairs(db, tenant_id, answer_map, r["answers"])
        elif answer_map.get("kind") == "custom":
            pairs = [(label, value) for _, label, value in wf._custom_answers(answer_map, r["answers"])]
        else:
            field_labels = {f["key"]: f.get("label") or f["key"] for f in (answer_map.get("fields") or {}).values()}
            pairs = [(field_labels.get(k, k), v) for k, v in wf._details(answer_map, r["answers"]).items()]
            _, path = wf._choice_path({}, r["answers"], answer_map.get("names"))
            if path:
                pairs.insert(0, ("Choice", " › ".join(path)))
        for label, _ in pairs:
            if label not in labels:
                labels.append(label)
        lead = r.get("leads") or {}
        rows.append({
            "id": r["id"], "lead_id": r.get("lead_id"), "submitted_at": r["created_at"], "outcome": r["outcome"],
            "name": lead.get("name"), "phone": lead.get("phone"), "answers": dict(pairs),
            "offers": wf._wants_offers(r["answers"]),
        })
    return labels, rows


@router.get("/forms/{design_id}/responses")
def form_responses(
    design_id: str, page: int = Query(1, ge=1, le=1000), limit: int = Query(50, ge=1, le=200),
    ctx: dict = Depends(require_read),
):
    """design_id 'services' = the Services form's answers."""
    db = _db_on(ctx)
    tenant_id = ctx["tenant_id"]
    design = None if design_id == "services" else _design_or_404(db, tenant_id, design_id)
    raw, total = _responses(db, tenant_id, design and design["id"], page, limit)
    labels, rows = _rows(db, tenant_id, design, raw)
    return {"columns": labels, "data": rows, "total": total, "page": page, "limit": limit}


_FORMULA = re.compile(r"^[=+\-@\t\r]")


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if _FORMULA.match(text) else text


@router.get("/forms/{design_id}/responses.csv")
def form_responses_csv(design_id: str, ctx: dict = Depends(require_read)):
    db = _db_on(ctx)
    tenant_id = ctx["tenant_id"]
    design = None if design_id == "services" else _design_or_404(db, tenant_id, design_id)
    raw: list[dict] = []
    page, total = 1, 0
    while True:
        chunk, total = _responses(db, tenant_id, design and design["id"], page, 200)
        raw += chunk
        if not chunk or len(raw) >= total or page >= 50:
            break
        page += 1
    truncated = len(raw) < total
    labels, rows = _rows(db, tenant_id, design, raw)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Submitted", "Name", "Phone", *[_cell(label) for label in labels], "Offers on WhatsApp"])
    for r in rows:
        writer.writerow([r["submitted_at"], _cell(r["name"]), r["phone"] or "",
                         *[_cell(r["answers"].get(label, "")) for label in labels], "Yes" if r["offers"] else "No"])
    if truncated:
        writer.writerow([f"Showing the newest {len(raw)} of {total} answers."])
    name = re.sub(r"[^A-Za-z0-9 _-]", "_", (design or {}).get("name") or "Services form").strip() or "form"
    return Response(content=out.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}_answers.csv"',
                             "Cache-Control": "no-store"})


@router.get("/leads/{lead_id}/answers")
def answers_for_lead(lead_id: str, ctx: dict = Depends(require_any_permission("conversations.view", "leads.view", "services.view"))):
    """The lead profile's "Form answers" card."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    _uuid_or_404(lead_id)
    if not wf.is_enabled(db, tenant_id):
        return {"available": False, "data": []}
    return {"available": True, "data": wf.lead_answers(db, tenant_id, lead_id)}


# ── sending from a chat ──────────────────────────────────────────────────────


class SendIn(BaseModel):
    lead_id: str


@router.get("/sendable")
def sendable_forms(ctx: dict = Depends(require_reply)):
    """Forms an agent can send from Conversations: published with their latest changes."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if not wf.is_enabled(db, tenant_id):
        return {"available": False, "data": []}
    designs = (
        db.table("whatsapp_form_designs").select("*").eq("tenant_id", tenant_id).eq("archived", False)
        .order("created_at", desc=True).execute()
    ).data or []
    return {"available": True,
            "data": [{"id": d["id"], "name": d["name"]} for d in designs if wf.live_custom_form(db, tenant_id, d)]}


@router.post("/forms/{design_id}/send")
async def send_to_lead(design_id: str, payload: SendIn, ctx: dict = Depends(require_reply)):
    db = _db_on(ctx)
    tenant_id = ctx["tenant_id"]
    _design_or_404(db, tenant_id, design_id)
    _uuid_or_404(payload.lead_id)
    try:
        sid = await wf.send_design_to_lead(db, tenant_id, design_id, payload.lead_id)
    except wf.FormBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sent": True, "message_id": sid}


@router.get("/reach-options")
def reach_options(ctx: dict = Depends(require_read)):
    """What a form's "when to send" rules can point at: this account's Click-to-WhatsApp ads
    (seen in Meta Ads reporting) and its approved templates."""
    db = _db_on(ctx)
    tenant_id = ctx["tenant_id"]
    ads: list[dict] = []
    try:
        rows = (
            db.table("ad_creatives").select("meta_ad_id, creative_label, ad_effective_status, effective_status")
            .eq("tenant_id", tenant_id).eq("is_click_to_whatsapp", True).limit(500).execute()
        ).data or []
        seen: set[str] = set()
        for r in rows:
            ad_id = str(r.get("meta_ad_id") or "")
            if ad_id.isdigit() and ad_id not in seen:
                seen.add(ad_id)
                ads.append({"id": ad_id, "name": r.get("creative_label") or ad_id,
                            "status": r.get("ad_effective_status") or r.get("effective_status")})
        ads.sort(key=lambda a: (a["status"] != "ACTIVE", a["name"].lower()))
    except Exception:
        ads = []
    templates = (
        db.table("message_templates").select("name, status").eq("tenant_id", tenant_id).execute()
    ).data or []
    names = sorted({t["name"] for t in templates if (t.get("status") or "").upper() == "APPROVED" and t.get("name")})
    return {"ads": ads, "templates": names}


@router.get("/template-forms")
def template_forms(ctx: dict = Depends(require_permission("templates.manage"))):
    """Templates → "Open form" button: the forms a template can open (published, latest changes)."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if not wf.is_enabled(db, tenant_id):
        return {"available": False, "data": []}
    out = []
    services = wf._latest(db, tenant_id, status="published")
    if services and services.get("meta_flow_id"):
        out.append({"id": "services", "name": "Services form"})
    designs = (
        db.table("whatsapp_form_designs").select("*").eq("tenant_id", tenant_id).eq("archived", False)
        .order("created_at", desc=True).execute()
    ).data or []
    out += [{"id": d["id"], "name": d["name"]} for d in designs if wf.live_custom_form(db, tenant_id, d)]
    return {"available": True, "data": out}



# ── live forms: Meta's encrypted endpoint ────────────────────────────────────


_LIVE_MAX_BODY = 64 * 1024  # Meta's requests are a few KB
from app.routes.auto_messages import _SlidingWindow  # noqa: E402

_live_limiter = _SlidingWindow(600, 60)  # per tenant; the app-wide per-IP limit applies too


@public_router.post("/{tenant_id}")
async def live_form_endpoint(tenant_id: str, request: Request):
    """Meta asks for a live form's next screen (products, free slots, a summary). Returns the
    reply encrypted with the request's own key, as plain text. Reads only, never saves."""
    import asyncio
    import logging

    from app.services.meta_webhook_verify import verify_meta_signature

    log = logging.getLogger(__name__)
    _uuid_or_404(tenant_id)
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        return Response(status_code=400)
    if length > _LIVE_MAX_BODY:
        return Response(status_code=413)
    db = get_supabase()
    # A business without a live-form key has nothing here. Checked first, so made-up tenant ids
    # never reach the limiter or the settings cache (keys are cached only when found).
    keys = await asyncio.to_thread(live.private_keys, db, tenant_id)
    if not keys:
        return Response(status_code=404)
    if not _live_limiter.allow(tenant_id):
        return Response(status_code=429)
    raw = await request.body()
    if len(raw) > _LIVE_MAX_BODY:
        return Response(status_code=413)
    # Only Meta may call this: its X-Hub-Signature-256 is required (fail closed, like the
    # WhatsApp webhook). Decryption alone proves nothing about the sender.
    signed = await asyncio.to_thread(verify_meta_signature, raw, request.headers.get("x-hub-signature-256"), tenant_id)
    if not signed:
        return Response(status_code=432)
    try:
        body = __import__("json").loads(raw or b"{}")
    except ValueError:
        return Response(status_code=400)
    try:
        payload, aes_key, iv = live.decrypt_request(body, keys)
    except live.EndpointError as exc:
        return Response(status_code=exc.status)
    try:
        reply = await asyncio.to_thread(live.handle_request, db, tenant_id, payload)
    except live.EndpointError as exc:
        return Response(status_code=exc.status)
    except Exception:
        log.exception("Live form request failed for tenant %s", tenant_id)
        return Response(status_code=500)
    return Response(content=live.encrypt_response(reply, aes_key, iv), media_type="text/plain")
