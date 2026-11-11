"""Client SMS API (prefix /api/v1/sms): DLT setup, templates, campaigns, reports, OTP, developer key.

Contract: docs/plans/2026-10-30-sms-api-contract.md. Each tenant sends with its own Bulk9 key
(app_settings bulk9_api_key). The key is never returned or logged, except GET /developer/key
(owner only). Recharge routes and the operator routes are not in this file.
"""
import csv
import io
import logging
import mimetypes
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.dependencies.tenant import require_owner, require_permission
from app.services import bulk9_client, sms_campaigns as camp, sms_setup, sms_wallet
from app.services.bulk9_client import Bulk9Error, Bulk9NotConfigured, Bulk9Timeout

logger = logging.getLogger(__name__)
router = APIRouter()

BUCKET = "sms-dlt"
SIGNED_URL_SECONDS = 24 * 3600
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
EXCEL_EXTS = {"xlsx", "csv"}
# A file must start with the bytes its type promises, so a renamed .exe isn't stored as proof.png.
MAGIC_BYTES = {"png": (b"\x89PNG\r\n\x1a\n",), "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
               "pdf": (b"%PDF-",)}
NOT_ENABLED = "SMS is not enabled for this account"
NOT_CONNECTED = "SMS is not connected yet"
EXPORT_CAP = 50_000
ENTITY_ID_RE = re.compile(r"[0-9]{5,30}")
SENDER_ID_RE = re.compile(r"[A-Z0-9]{3,6}")


# ---------------------------------------------------------------- gates + helpers

def _is_enabled(tenant_id: str) -> bool:
    rows = (get_supabase().table("tenants").select("enabled_features").eq("id", tenant_id)
            .limit(1).execute()).data or []
    return "sms" in ((rows[0].get("enabled_features") if rows else None) or [])


def _gate(permission: str, *, need_key: bool = True):
    """Permission first (403), then the SMS feature (403), then the Bulk9 key (409).
    The returned context carries `api_key` when need_key is set."""
    perm = require_permission(permission)

    def dep(ctx: dict = Depends(perm)) -> dict:
        if not _is_enabled(ctx["tenant_id"]):
            raise HTTPException(403, NOT_ENABLED)
        if need_key:
            key = get_setting("bulk9_api_key", tenant_id=ctx["tenant_id"])
            if not key:
                raise HTTPException(409, NOT_CONNECTED)
            return {**ctx, "api_key": key}
        return ctx

    return dep


view = _gate("sms.view")
view_no_key = _gate("sms.view", need_key=False)
manage = _gate("sms.manage")
manage_no_key = _gate("sms.manage", need_key=False)


async def _bulk9(coro):
    """Await a Bulk9 call and turn its failures into HTTP errors."""
    try:
        return await coro
    except Bulk9Error as e:
        raise HTTPException(502, str(e))
    except Bulk9Timeout:
        raise HTTPException(504, "The SMS provider did not respond in time. Please try again.")
    except Bulk9NotConfigured:
        raise HTTPException(409, NOT_CONNECTED)
    except ValueError as e:  # a wrapper refused bad input before calling Bulk9
        raise HTTPException(422, str(e))


def _sms_error(e: camp.SmsError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _message(body: dict, default: str = "Done") -> str:
    msg = body.get("message")
    if isinstance(msg, list):
        msg = "; ".join(str(m) for m in msg)
    return str(msg or default)


def _safe_filename(name: str | None) -> str:
    base = (name or "file").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "file"
    return base[-80:]


async def _save_upload(db, tenant_id: str, file: UploadFile, allowed: set[str]) -> str:
    """Validate type + size, store privately under {tenant_id}/, return the storage path."""
    safe = _safe_filename(file.filename)
    ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
    if ext not in allowed:
        raise HTTPException(422, f"{safe}: allowed file types are {', '.join(sorted(allowed))}.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{safe} is larger than 20 MB.")
    if not data:
        raise HTTPException(422, f"{safe} is empty.")
    if ext in MAGIC_BYTES and not data.startswith(MAGIC_BYTES[ext]):
        raise HTTPException(422, f"{safe} isn't a real {ext.upper()} file.")
    path = f"{tenant_id}/{uuid.uuid4().hex[:12]}_{safe}"
    ctype = mimetypes.guess_type(safe)[0] or "application/octet-stream"
    try:
        db.storage.from_(BUCKET).upload(path, data, {"content-type": ctype})
    except Exception:
        logger.exception("sms: upload to storage failed")
        raise HTTPException(500, "Could not store the file. Please try again.")
    return path


def signed_url(db, path: str, seconds: int = SIGNED_URL_SECONDS) -> str:
    try:
        signed = db.storage.from_(BUCKET).create_signed_url(path, seconds)
    except Exception:
        logger.exception("sms: signing a stored file failed")
        raise HTTPException(500, "Could not prepare the file. Please try again.")
    url = None
    if isinstance(signed, dict):
        url = signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url") or signed.get("url")
    else:
        url = getattr(signed, "signed_url", None) or getattr(signed, "signedURL", None)
    if not url:
        raise HTTPException(500, "Could not prepare the file for upload.")
    return url


async def _store_upload(db, tenant_id: str, file: UploadFile, allowed: set[str]) -> str:
    """Store the file and return a 24h signed URL for Bulk9."""
    return signed_url(db, await _save_upload(db, tenant_id, file, allowed))


# ---------------------------------------------------------------- status, balance, senders

def _templates_ready(tenant_id: str) -> bool:
    rows = (get_supabase().table("sms_templates").select("id").eq("tenant_id", tenant_id).eq("status", "ready")
            .limit(1).execute()).data or []
    return bool(rows)


@router.get("/status")
async def status(ctx: dict = Depends(require_permission("sms.view"))):
    tid = ctx["tenant_id"]
    return {
        "enabled": _is_enabled(tid),
        "connected": bool(get_setting("bulk9_api_key", tenant_id=tid)),
        "templates_ready": _templates_ready(tid),
        "support_contact": get_setting("sms_support_contact", tenant_id=tid) or "",
    }


async def _require_send_ready(api_key: str, needed: int) -> None:
    """Block a send that would fail anyway: not enough balance (every message would fail)."""
    have = (await _bulk9(bulk9_client.wallet(api_key)))["sms_count"]
    if have < needed:
        raise HTTPException(409, f"Not enough SMS balance: this needs {needed:,} SMS and you have {have:,}.")


@router.get("/wallet/history")
async def wallet_history(limit: int = Query(100, ge=1, le=200), ctx: dict = Depends(view_no_key)):
    return sms_wallet.history(get_supabase(), ctx["tenant_id"], limit)


@router.get("/balance")
async def balance(ctx: dict = Depends(view)):
    body = await _bulk9(bulk9_client.wallet(ctx["api_key"]))
    try:
        sms_count = int(float(body.get("sms_count") or 0))
    except (TypeError, ValueError):
        sms_count = 0
    return {"sms_count": sms_count, "wallet": body.get("wallet")}


def _dlt_items(body: dict) -> list[dict]:
    """The sender / template groups in a DLT Manager answer (its list key isn't documented)."""
    for key in ("data", "senders", "templates", "result"):
        if isinstance(body.get(key), list):
            return [i for i in body[key] if isinstance(i, dict)]
    return [i for v in body.values() if isinstance(v, list) for i in v if isinstance(i, dict)]


def _approved_senders(body: dict) -> list[dict]:
    seen, out = set(), []
    for i in _dlt_items(body):
        if not i.get("sender_id"):
            continue
        key = (i.get("sender_id"), i.get("entity_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"sender_id": i.get("sender_id"), "entity_id": i.get("entity_id"),
                    "entity_name": i.get("entity_name")})
    return out


@router.get("/senders")
async def senders(ctx: dict = Depends(view)):
    """Approved senders only: what Send SMS can use."""
    return {"senders": _approved_senders(await _bulk9(bulk9_client.list_dlt(ctx["api_key"], "sender")))}


@router.get("/dlt/entities")
async def dlt_entities(ctx: dict = Depends(view)):
    """DLT Manager: entities and senders, approved (from Bulk9) or submitted (from Anril). If Bulk9
    can't be read, the submitted ones still show and `error` says why (HTTP 200)."""
    error = None
    try:
        approved = _approved_senders(await _bulk9(bulk9_client.list_dlt(ctx["api_key"], "sender")))
    except HTTPException as e:
        approved, error = [], str(e.detail)
    db, tid = get_supabase(), ctx["tenant_id"]
    return {"entities": sms_setup.entities(db, tid, approved), "senders": sms_setup.senders(db, tid, approved),
            "error": error}


# ---------------------------------------------------------------- templates (cache of Bulk9's list)

TEMPLATE_FIELDS = ("id", "message_id", "dlt_template_id", "sender_id", "entity_id", "entity_name", "message",
                   "var_count", "template_type", "status", "last_synced_at")


def _public_template(r: dict) -> dict:
    return {k: r.get(k) for k in TEMPLATE_FIELDS}


def _cached_templates(db, tenant_id: str, error: str | None = None) -> dict:
    rows = (db.table("sms_templates").select("*").eq("tenant_id", tenant_id)
            .order("created_at", desc=True).execute()).data or []
    synced = [r["last_synced_at"] for r in rows if r.get("last_synced_at")]
    return {"templates": [_public_template(r) for r in rows],
            "last_synced_at": max(synced) if synced else None, "error": error}


@router.get("/templates")
async def list_templates(ctx: dict = Depends(view_no_key)):
    return _cached_templates(get_supabase(), ctx["tenant_id"])


@router.post("/templates/refresh")
async def refresh_templates(ctx: dict = Depends(manage)):
    """Re-read Bulk9's approved templates. On any Bulk9 failure the cached rows stay and `error`
    says why (HTTP 200), so the page keeps working."""
    db, tid = get_supabase(), ctx["tenant_id"]
    try:
        body = await bulk9_client.list_dlt(ctx["api_key"], "template")
    except (Bulk9Error, Bulk9Timeout, Bulk9NotConfigured) as e:
        return _cached_templates(db, tid, error=str(e) or "Could not reach the SMS provider.")
    now = datetime.now(timezone.utc).isoformat()
    existing = (db.table("sms_templates").select("*").eq("tenant_id", tid).execute()).data or []
    by_msg = {str(r["message_id"]): r for r in existing if r.get("message_id")}
    submitted = [r for r in existing if not r.get("message_id")]
    logged = False
    for group in _dlt_items(body):
        for t in group.get("templates") or []:
            mid, text = t.get("message_id"), t.get("message")
            if mid is None or not text:
                continue
            if not logged:  # which fields Bulk9 sends (its docs don't list a category one)
                logger.info("Bulk9 template fields: group=%s template=%s", sorted(group), sorted(t))
                logged = True
            # DLT's category when Bulk9 reports it on the template. Not read from the sender group:
            # a group's "type" may be the header type, which would mislabel promo templates.
            category = bulk9_client.template_category(t)
            fields = {"sender_id": group.get("sender_id") or "", "entity_id": group.get("entity_id"),
                      "entity_name": group.get("entity_name"), "message": text,
                      "var_count": int(t.get("var_count") or camp.var_count(text)),
                      "status": "ready", "last_synced_at": now,
                      **({"template_type": category} if category else {})}
            row = by_msg.get(str(mid))
            if row:
                db.table("sms_templates").update(fields).eq("id", row["id"]).eq("tenant_id", tid).execute()
                continue
            # An Anril-submitted row for the same wording is now approved: keep its choices, drop the stub.
            stub = next((s for s in submitted if s["message"].strip() == text.strip()
                         and s["sender_id"] == fields["sender_id"]), None)
            if stub:
                db.table("sms_templates").update({**fields, "message_id": str(mid)}) \
                    .eq("id", stub["id"]).eq("tenant_id", tid).execute()
                submitted.remove(stub)
            else:
                db.table("sms_templates").insert({"tenant_id": tid, "message_id": str(mid),
                    "template_type": "unclassified", **fields}).execute()  # fields' category wins
    return _cached_templates(db, tid)


# ---------------------------------------------------------------- DLT adds

class EntityBody(BaseModel):
    entity_name: str = Field(min_length=1, max_length=200)
    entity_id: str = Field(min_length=1, max_length=40)


@router.post("/dlt/entity")
async def dlt_entity(body: EntityBody, ctx: dict = Depends(manage)):
    name, eid = body.entity_name.strip(), body.entity_id.strip()
    if not name or not eid:
        raise HTTPException(422, "Enter the entity name and entity ID.")
    db = get_supabase()
    res = await _bulk9(bulk9_client.add_entity(ctx["api_key"], entity_name=name, entity_id=eid))
    if ENTITY_ID_RE.fullmatch(eid):
        sms_setup.record_submission(db, ctx["tenant_id"], ctx.get("user_id"), kind="entity",
                                    entity_id=eid, entity_name=name)
    return {"ok": True, "message": _message(res, "Entity submitted for approval.")}


class SenderBody(BaseModel):
    entity_id: str = Field(min_length=1, max_length=40)
    sender_id: str = Field(min_length=3, max_length=6)


@router.post("/dlt/sender")
async def dlt_sender(body: SenderBody, ctx: dict = Depends(manage)):
    res = await _bulk9(bulk9_client.add_sender(ctx["api_key"], entity_id=body.entity_id.strip(),
                                               sender_id=body.sender_id.strip()))
    eid, sid = body.entity_id.strip(), body.sender_id.strip().upper()
    if ENTITY_ID_RE.fullmatch(eid) and SENDER_ID_RE.fullmatch(sid):
        sms_setup.record_submission(get_supabase(), ctx["tenant_id"], ctx.get("user_id"), kind="sender",
                                    entity_id=eid, sender_id=sid)
    return {"ok": True, "message": _message(res, "Sender ID submitted for approval.")}


@router.post("/dlt/sender-excel")
async def dlt_sender_excel(entity_id: str = Form(..., max_length=40), file: UploadFile = File(...),
                           ctx: dict = Depends(manage)):
    url = await _store_upload(get_supabase(), ctx["tenant_id"], file, EXCEL_EXTS)
    res = await _bulk9(bulk9_client.add_sender_excel(ctx["api_key"], entity_id=entity_id.strip(), file_url=url))
    return {"ok": True, "message": _message(res, "Sender IDs uploaded.")}


class DltTemplateBody(BaseModel):
    entity_id: str = Field(min_length=1, max_length=40)
    sender_ids: list[str] = Field(min_length=1, max_length=20)
    dlt_template_id: str = Field(min_length=1, max_length=40)
    message_text: str = Field(min_length=1, max_length=1600)
    template_type: Literal["service", "promotional"]


@router.post("/dlt/template")
async def dlt_template(body: DltTemplateBody, ctx: dict = Depends(manage)):
    res = await _bulk9(bulk9_client.add_template(
        ctx["api_key"], entity_id=body.entity_id.strip(), sender_ids=[s.strip() for s in body.sender_ids],
        template_id=body.dlt_template_id.strip(), message_text=body.message_text,
        promotional=body.template_type == "promotional"))
    # Bulk9 lists the template only once approved; show it meanwhile as "submitted".
    db = get_supabase()
    names = (db.table("sms_templates").select("entity_name").eq("tenant_id", ctx["tenant_id"])
             .eq("entity_id", body.entity_id.strip()).limit(1).execute()).data or []
    db.table("sms_templates").insert({
        "tenant_id": ctx["tenant_id"], "dlt_template_id": body.dlt_template_id.strip(),
        "sender_id": body.sender_ids[0].strip(), "entity_id": body.entity_id.strip(),
        "entity_name": names[0]["entity_name"] if names else None, "message": body.message_text,
        "var_count": camp.var_count(body.message_text), "template_type": body.template_type,
        "status": "submitted",
    }).execute()
    return {"ok": True, "message": _message(res, "Template submitted for approval.")}


@router.post("/dlt/template-excel")
async def dlt_template_excel(entity_id: str = Form(..., max_length=40),
                             file: UploadFile = File(...), ctx: dict = Depends(manage)):
    """No category: the DLT export already says which each template is (Bulk9's own panel doesn't ask)."""
    url = await _store_upload(get_supabase(), ctx["tenant_id"], file, EXCEL_EXTS)
    res = await _bulk9(bulk9_client.add_template_excel(
        ctx["api_key"], entity_id=entity_id.strip(), file_url=url))
    return {"ok": True, "message": _message(res, "Templates uploaded.")}


# ---------------------------------------------------------------- Add credit


def _setup(fn, *args):
    try:
        return fn(*args)
    except camp.SmsError as e:
        raise _sms_error(e)


class CreditBody(BaseModel):
    amount: float = Field(ge=100, le=1_000_000)
    note: Optional[str] = Field(default=None, max_length=300)


@router.get("/credit-requests")
async def credit_list(ctx: dict = Depends(view_no_key)):
    return {"items": [sms_setup.public_credit(r) for r in sms_setup.credit_requests(get_supabase(), ctx["tenant_id"])]}


@router.post("/credit-requests")
async def credit_request(body: CreditBody, ctx: dict = Depends(manage_no_key)):
    row = _setup(sms_setup.request_credit, get_supabase(), ctx["tenant_id"], ctx.get("user_id"), body.amount, body.note)
    return sms_setup.public_credit(row)


# ---------------------------------------------------------------- campaigns

@router.get("/campaigns/fields")
async def campaign_fields(source: Literal["leads", "contacts", "numbers"] = "leads",
                          group_ids: Optional[str] = Query(None, max_length=2000),
                          ctx: dict = Depends(view_no_key)):
    """Fields a {#var#} can be filled from. SMS contacts add their extra upload columns as col:<name>.
    Typed numbers have no name, so only Phone is offered for them."""
    if source == "numbers":
        return {"fields": [f for f in camp.FIELDS if f["key"] == "phone"]}
    fields = list(camp.FIELDS)
    gids = [g for g in (group_ids or "").split(",") if g.strip()][:camp.MAX_GROUPS]
    if source == "contacts" and gids:
        try:
            gids = [str(uuid.UUID(g.strip())) for g in gids]
        except ValueError:
            raise HTTPException(422, "Group not found.")
        keys = (get_supabase().rpc("sms_contact_field_keys", {"p_tenant": ctx["tenant_id"], "p_groups": gids})
                .execute()).data or []
        fields += [{"key": f"{camp.COL_PREFIX}{k['key']}", "label": k["key"]} for k in keys]
    return {"fields": fields}


class VarSource(BaseModel):
    source: Literal["field", "text", "typed"]
    value: str = Field("", max_length=200)


class ManualSpec(BaseModel):
    """"Type my own": the DLT IDs and the exact approved text (variables filled in). No category:
    DLT already decided it when it approved the template."""
    sender_id: str = Field(min_length=3, max_length=6, pattern=r"^[A-Za-z0-9]+$")
    entity_id: str = Field(min_length=5, max_length=30, pattern=r"^[0-9]+$")
    dlt_template_id: str = Field(min_length=5, max_length=30, pattern=r"^[0-9]+$")
    message: str = Field(min_length=1, max_length=2000)


class PreviewBody(BaseModel):
    kind: Literal["template", "manual"] = "template"
    manual: Optional[ManualSpec] = None
    source: Literal["leads", "contacts", "numbers"] = "leads"
    template_id: Optional[str] = None
    variable_map: list[VarSource] = Field(default_factory=list, max_length=20)
    lead_ids: list[str] = Field(default_factory=list, max_length=camp.MAX_LEADS)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=camp.MAX_GROUPS)
    numbers: list[str] = Field(default_factory=list, max_length=camp.MAX_NUMBERS)
    typed_values: list[Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=20)]] = Field(
        default_factory=list, max_length=camp.MAX_NUMBERS)
    consent_confirmed: bool = False


class CampaignBody(PreviewBody):
    name: str = Field(min_length=1, max_length=120)
    send_at: Optional[datetime] = None
    idempotency_key: str = Field(min_length=8, max_length=100)


def _vmap(body: PreviewBody) -> list[dict]:
    return [v.model_dump() for v in body.variable_map]


def _audience(body: PreviewBody) -> camp.Audience:
    return camp.Audience(source=body.source, lead_ids=body.lead_ids, group_ids=[str(g) for g in body.group_ids],
                         numbers=body.numbers, typed_values=body.typed_values,
                         consent_confirmed=body.consent_confirmed)


def _body_template(db, tid: str, body: PreviewBody) -> dict:
    if body.kind == "manual":
        if not body.manual:
            raise camp.SmsError("Fill in the sender ID, DLT template ID and message.")
        m = body.manual
        return camp.manual_template(sender_id=m.sender_id, entity_id=m.entity_id,
                                    dlt_template_id=m.dlt_template_id, message=m.message)
    if not body.template_id:
        raise camp.SmsError("Pick a template.")
    return camp.get_template(db, tid, body.template_id)


@router.post("/campaigns/preview")
async def preview_campaign(body: PreviewBody, ctx: dict = Depends(view_no_key)):
    db = get_supabase()
    try:
        template = _body_template(db, ctx["tenant_id"], body)
        return camp.preview(db, ctx["tenant_id"], template, _vmap(body), audience=_audience(body))
    except camp.SmsError as e:
        raise _sms_error(e)


@router.post("/campaigns")
async def create_campaign(body: CampaignBody, ctx: dict = Depends(manage)):
    db, tid = get_supabase(), ctx["tenant_id"]
    try:
        template = _body_template(db, tid, body)
        needed = camp.preview(db, tid, template, _vmap(body), audience=_audience(body))["total_segments"]
        await _require_send_ready(ctx["api_key"], needed)
        row, created = camp.create_campaign(
            db, tid, ctx.get("user_id"), name=body.name, template=template, variable_map=_vmap(body),
            send_at=body.send_at, idempotency_key=body.idempotency_key, audience=_audience(body))
    except camp.SmsError as e:
        raise _sms_error(e)
    return JSONResponse(camp.public_campaigns(db, tid, [row])[0], status_code=201 if created else 200)


@router.get("/campaigns")
async def list_campaigns(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                         ctx: dict = Depends(view_no_key)):
    db, tid = get_supabase(), ctx["tenant_id"]
    rows = (db.table("sms_campaigns").select("*").eq("tenant_id", tid).is_("deleted_at", "null")
            .order("created_at", desc=True).range(offset, offset + limit - 1).execute()).data or []
    return {"campaigns": camp.public_campaigns(db, tid, rows)}


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, ctx: dict = Depends(view_no_key)):
    db, tid = get_supabase(), ctx["tenant_id"]
    row = camp.get_campaign_row(db, tid, campaign_id)
    if not row:
        raise HTTPException(404, "Campaign not found.")
    return camp.public_campaigns(db, tid, [row])[0]


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str, ctx: dict = Depends(manage_no_key)):
    db, tid = get_supabase(), ctx["tenant_id"]
    try:
        row = camp.cancel_campaign(db, tid, campaign_id)
    except camp.SmsError as e:
        raise _sms_error(e)
    return camp.public_campaigns(db, tid, [row])[0]


class RescheduleBody(BaseModel):
    send_at: datetime


@router.post("/campaigns/{campaign_id}/reschedule")
async def reschedule_campaign(campaign_id: str, body: RescheduleBody, ctx: dict = Depends(manage_no_key)):
    db, tid = get_supabase(), ctx["tenant_id"]
    try:
        row = camp.reschedule_campaign(db, tid, campaign_id, body.send_at)
    except camp.SmsError as e:
        raise _sms_error(e)
    return camp.public_campaigns(db, tid, [row])[0]


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, ctx: dict = Depends(manage_no_key)):
    try:
        camp.delete_campaign(get_supabase(), ctx["tenant_id"], campaign_id)
    except camp.SmsError as e:
        raise _sms_error(e)
    return {"ok": True}


# ---------------------------------------------------------------- messages

IST = timezone(timedelta(hours=5, minutes=30))


def _day_bounds(d_from: Optional[date], d_to: Optional[date]) -> tuple[str | None, str | None]:
    """A date range as Indian days (clients read "today" in IST, not UTC)."""
    lo = datetime(d_from.year, d_from.month, d_from.day, tzinfo=IST).isoformat() if d_from else None
    hi = (datetime(d_to.year, d_to.month, d_to.day, tzinfo=IST) + timedelta(days=1)
          - timedelta(microseconds=1)).isoformat() if d_to else None
    return lo, hi


def _messages_query(db, tid: str, campaign_id, status_, d_from, d_to, search):
    q = db.table("sms_messages").select("*", count="exact").eq("tenant_id", tid)
    if campaign_id:
        q = q.eq("campaign_id", campaign_id)
    if status_:
        if status_ not in camp.STATUSES:
            raise HTTPException(422, "Unknown status.")
        q = q.eq("status", status_)
    lo, hi = _day_bounds(d_from, d_to)
    if lo:
        q = q.gte("created_at", lo)
    if hi:
        q = q.lte("created_at", hi)
    if search:
        term = re.sub(r"[,()%*\\]", " ", search).strip()[:50]
        if term:
            q = q.or_(f"phone.ilike.%{term}%,content.ilike.%{term}%")
    return q.order("created_at", desc=True)


@router.get("/messages")
async def list_messages(campaign_id: Optional[str] = None, status: Optional[str] = None,
                        from_: Optional[date] = Query(None, alias="from"), to: Optional[date] = None,
                        search: Optional[str] = None, limit: int = Query(50, ge=1, le=200),
                        offset: int = Query(0, ge=0), ctx: dict = Depends(view_no_key)):
    db, tid = get_supabase(), ctx["tenant_id"]
    res = _messages_query(db, tid, campaign_id, status, from_, to, search) \
        .range(offset, offset + limit - 1).execute()
    return {"messages": camp.public_messages(db, tid, res.data or []), "total": res.count or 0}


@router.get("/messages/export.csv")
async def export_messages(campaign_id: Optional[str] = None, status: Optional[str] = None,
                          from_: Optional[date] = Query(None, alias="from"), to: Optional[date] = None,
                          search: Optional[str] = None, ctx: dict = Depends(view_no_key)):
    db, tid = get_supabase(), ctx["tenant_id"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Phone", "Message", "Status", "Reason", "SMS count",
                "Sent at", "Delivered at"])

    def cell(v):
        s = "" if v is None else str(v)
        # A spreadsheet runs a cell starting with these as a formula; lead names are user data.
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    start = 0
    while start < EXPORT_CAP:
        rows = _messages_query(db, tid, campaign_id, status, from_, to, search) \
            .range(start, start + 999).execute().data or []
        for m in camp.public_messages(db, tid, rows):
            w.writerow([cell(m["lead_name"]), cell(m["phone"]), cell(m["content"]), m["status"],
                        cell(m["failure_reason"]), m["sms_count"] if m["sms_count"] is not None else "",
                        m["submitted_at"] or "", m["delivered_at"] or ""])
        if len(rows) < 1000:
            break
        start += 1000
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="sms-messages.csv"'})


# ---------------------------------------------------------------- reports

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _ist_day(value) -> str | None:
    d = _parse_ts(value)
    return d.astimezone(IST).date().isoformat() if d else None


def quiet_release(value) -> datetime | None:
    """TRAI night rule: an SMS handed over between 9 PM and 10 AM IST is held by the operator until
    10 AM IST. Returns that 10 AM, or None for a daytime send."""
    d = _parse_ts(value)
    if not d:
        return None
    ist = d.astimezone(IST)
    if 10 <= ist.hour < 21:
        return None
    day = ist.date() + timedelta(days=1 if ist.hour >= 21 else 0)
    return datetime(day.year, day.month, day.day, 10, tzinfo=IST)


def _window(d_from: Optional[date], d_to: Optional[date], max_days: int) -> tuple[date, date]:
    d_to = d_to or datetime.now(IST).date()  # "today" is India's, not the server's UTC day
    d_from = d_from or d_to - timedelta(days=min(max_days, 7) - 1)
    if d_from > d_to:
        raise HTTPException(422, "'from' must be on or before 'to'.")
    if (d_to - d_from).days + 1 > max_days:
        raise HTTPException(422, f"Pick a range of at most {max_days} days.")
    return d_from, d_to


@router.get("/reports/summary")
async def reports_summary(from_: Optional[date] = Query(None, alias="from"), to: Optional[date] = None,
                          ctx: dict = Depends(view)):
    d_from, d_to = _window(from_, to, 30)
    db, tid = get_supabase(), ctx["tenant_id"]
    lo, hi = _day_bounds(d_from, d_to)
    counts = {s: 0 for s in camp.STATUSES}
    days = [(d_from + timedelta(days=i)).isoformat() for i in range((d_to - d_from).days + 1)]
    daily = {d: {"day": d, "delivered": 0, "failed": 0, "waiting": 0, "otp": 0} for d in days}
    now, held = _utcnow(), 0
    start = 0
    while True:
        rows = (db.table("sms_messages").select("status,created_at,submitted_at").eq("tenant_id", tid)
                .gte("created_at", lo).lte("created_at", hi).order("id").range(start, start + 999).execute()).data or []
        for r in rows:
            st = r["status"]
            if st in counts:
                counts[st] += 1
            day = daily.get(_ist_day(r.get("created_at")))
            if day is not None:
                if st in ("delivered", "failed"):
                    day[st] += 1
                elif st in ("submitted", "unknown"):
                    day["waiting"] += 1
            release = quiet_release(r.get("submitted_at")) if st == "submitted" else None
            if release and now < release:
                held += 1
        if len(rows) < 1000:
            break
        start += 1000
    start = 0
    while True:
        otps = (db.table("sms_otp_log").select("created_at").eq("tenant_id", tid).in_("action", ["send", "resend"])
                .eq("ok", True).gte("created_at", lo).lte("created_at", hi).order("id")
                .range(start, start + 999).execute()).data or []
        for r in otps:
            day = daily.get(_ist_day(r.get("created_at")))
            if day is not None:
                day["otp"] += 1
        if len(otps) < 1000:
            break
        start += 1000
    out = {"anril": counts, "held": held, "daily": list(daily.values()), "bulk9": None, "error": None}
    try:
        out["bulk9"] = bulk9_client.scrub_financial(await bulk9_client.sms_summary(ctx["api_key"], date_from=d_from.isoformat(),
                                                      date_to=d_to.isoformat()))
    except (Bulk9Error, Bulk9Timeout) as e:
        out["error"] = str(e) or "Could not reach the SMS provider."
    return out


@router.get("/reports/logs")
async def reports_logs(from_: Optional[date] = Query(None, alias="from"), to: Optional[date] = None,
                       page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=1000),
                       ctx: dict = Depends(view)):
    d_from, d_to = _window(from_, to, 3)
    try:
        body = await bulk9_client.sms_logs(ctx["api_key"], date_from=d_from.isoformat(),
                                           date_to=d_to.isoformat(), page=page, limit=limit)
    except (Bulk9Error, Bulk9Timeout) as e:
        return {"logs": [], "page": page, "error": str(e) or "Could not reach the SMS provider."}
    logs = bulk9_client.scrub_financial(bulk9_client.report_rows(body))
    return {"logs": logs, "page": page, "error": None}


# ---------------------------------------------------------------- developer key + OTP

def _owner_gate(ctx: dict = Depends(require_owner)) -> dict:
    if not _is_enabled(ctx["tenant_id"]):
        raise HTTPException(403, NOT_ENABLED)
    key = get_setting("bulk9_api_key", tenant_id=ctx["tenant_id"])
    if not key:
        raise HTTPException(409, NOT_CONNECTED)
    return {**ctx, "api_key": key}


@router.get("/developer/key")
async def developer_key(ctx: dict = Depends(_owner_gate)):
    return {"api_key": ctx["api_key"]}


def _mobile(raw: str) -> str:
    m = camp.normalize_indian_mobile(raw)
    if not m:
        raise HTTPException(422, "Enter a valid 10-digit Indian mobile number.")
    return m


class OtpSendBody(BaseModel):
    mobile: str
    otp_id: str = Field(min_length=1, max_length=40)
    otp_length: int = Field(6, ge=4, le=10)
    otp_expiry: int = Field(15, ge=1, le=10080)
    variables_values: Optional[str] = Field(None, max_length=200)


class OtpVerifyBody(BaseModel):
    mobile: str
    otp: str = Field(min_length=1, max_length=12)


class OtpResendBody(BaseModel):
    mobile: str


def _log_otp(ctx: dict, mobile: str, action: str, ok: bool, message: str | None,
             request_id: str | None = None) -> None:
    """OTP history row (never the code). Best effort: a failed write must not fail the OTP."""
    try:
        get_supabase().table("sms_otp_log").insert({
            "tenant_id": ctx["tenant_id"], "mobile": mobile, "action": action, "ok": ok,
            "request_id": request_id, "message": (message or "")[:300] or None,
            "created_by": ctx.get("user_id"),
        }).execute()
    except Exception:
        logger.exception("sms: OTP history write failed for tenant %s", ctx["tenant_id"])


async def _otp_call(ctx: dict, mobile: str, action: str, call, ok_text: str) -> dict:
    try:
        res = await _bulk9(call)
    except HTTPException as e:
        _log_otp(ctx, mobile, action, False, str(e.detail))
        raise
    message = _message(res, ok_text)
    _log_otp(ctx, mobile, action, True, message, res.get("request_id"))
    return {"ok": True, "request_id": res.get("request_id"), "message": message}


@router.post("/otp/send")
async def otp_send(body: OtpSendBody, ctx: dict = Depends(manage)):
    mobile = _mobile(body.mobile)
    return await _otp_call(ctx, mobile, "send", bulk9_client.otp_send(
        ctx["api_key"], mobile=mobile, otp_id=body.otp_id, otp_length=body.otp_length,
        otp_expiry=body.otp_expiry, variables_values=(body.variables_values or "").strip() or None), "OTP sent.")


@router.post("/otp/verify")
async def otp_verify(body: OtpVerifyBody, ctx: dict = Depends(manage)):
    mobile = _mobile(body.mobile)
    try:
        res = await bulk9_client.otp_verify(ctx["api_key"], mobile=mobile, otp=body.otp.strip())
    except Bulk9Error as e:
        # A wrong or expired code is an answer, not a provider outage.
        _log_otp(ctx, mobile, "verify", False, str(e))
        return {"ok": False, "message": str(e)}
    except Bulk9Timeout:
        raise HTTPException(504, "The SMS provider did not respond in time. Please try again.")
    message = _message(res, "OTP verified.")
    _log_otp(ctx, mobile, "verify", True, message)
    return {"ok": True, "message": message}


@router.post("/otp/resend")
async def otp_resend(body: OtpResendBody, ctx: dict = Depends(manage)):
    mobile = _mobile(body.mobile)
    out = await _otp_call(ctx, mobile, "resend", bulk9_client.otp_resend(ctx["api_key"], mobile=mobile),
                          "OTP sent again.")
    return {"ok": True, "message": out["message"]}


OTP_LOG_FIELDS = ("id", "mobile", "action", "ok", "message", "created_at", "delivery_status", "delivered_at")


@router.get("/otp/history")
async def otp_history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                      ctx: dict = Depends(view_no_key)):
    """OTPs sent, resent and checked from this dashboard. OTPs your own app sends with the API key
    aren't here: Bulk9 has no OTP-history API."""
    res = (get_supabase().table("sms_otp_log").select("*", count="exact").eq("tenant_id", ctx["tenant_id"])
           .order("created_at", desc=True).range(offset, offset + limit - 1).execute())
    return {"items": [{k: r.get(k) for k in OTP_LOG_FIELDS} for r in res.data or []], "total": res.count or 0}
