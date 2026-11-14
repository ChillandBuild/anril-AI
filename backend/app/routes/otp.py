"""Anril OTP routes. Spec: docs/specs/anril-otp.md; service: app/services/otp.py.

public_router  (/api/v1/otp/...)          the client's SERVER, Bearer anr_otp_live_... key
console router (/api/v1/otp-console/...)  the dashboard, signed-in user

The tenant always comes from the key or the signed-in user, never from the request body
(every body model forbids unknown fields). Keys and the signing secret are owner-only and
returned exactly once."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.dependencies.tenant import require_owner, require_permission
from app.routes.auto_messages import _client_ip, _SlidingWindow
from app.services import bulk9_client
from app.services import otp as svc
from app.services.audit_log import record_audit_event

logger = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
# Runs BEFORE the key lookup, so someone guessing keys can't hammer the database.
_ip_limiter = _SlidingWindow(120, 60)
_key_limiter = _SlidingWindow(120, 60)
_verify_limiter = _SlidingWindow(60, 60)
_key_change_limiter = _SlidingWindow(5, 60)
_console_send_limiter = _SlidingWindow(10, 60)

view = require_permission("sms.view")
manage = require_permission("sms.manage")
settings_manage = require_permission("settings.manage")

Mode = Literal["sms", "whatsapp", "both", "sms_then_whatsapp"]
TEMPLATE_NAME_RE = re.compile(r"[a-z0-9_]{1,60}")
LANG_RE = re.compile(r"[a-z]{2,3}(_[A-Z]{2})?")


def _error(status_code: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    # `detail` too: the dashboard's apiFetch shows err.detail.
    return JSONResponse(status_code=status_code, content={"error": message, "code": code, "detail": message},
                        headers={**_NO_STORE, **(headers or {})})


def _rate_limited() -> JSONResponse:
    return _error(429, "rate_limited", "Too many requests. Try again in a minute.", {"Retry-After": "60"})


def _from_service(e: svc.OtpError) -> JSONResponse:
    headers = {"Retry-After": "3600"} if e.code == "too_many_codes" else None
    return _error(e.status_code, e.code, e.message, headers)


def _ok(content: dict) -> JSONResponse:
    return JSONResponse(content=content, headers=_NO_STORE)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _audit(ctx: dict, action: str, target_id: str, metadata: dict) -> None:
    # Never put a key, its hash, a code or the signing secret in here.
    try:
        record_audit_event(get_supabase(), tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"),
                           actor_role=ctx.get("role"), action=action, target_type="otp",
                           target_id=target_id, metadata=metadata)
    except Exception:
        logger.warning("otp audit write failed action=%s", action)


# ================================================================ public API (client servers)

class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=6, max_length=20)
    mode: Optional[Mode] = None
    code: Optional[str] = Field(None, min_length=4, max_length=10)
    ref: Optional[str] = Field(None, max_length=svc.REF_MAX)


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=4, max_length=10)
    otp_id: Optional[str] = Field(None, max_length=40)
    phone: Optional[str] = Field(None, min_length=6, max_length=20)


def _api_key(request: Request, db, limiter: _SlidingWindow) -> dict | JSONResponse:
    if not _ip_limiter.allow(_client_ip(request)):
        return _rate_limited()
    try:
        key = svc.find_key(db, _bearer(request))
    except svc.OtpError as e:
        return _from_service(e)
    if not limiter.allow(key["id"]):
        return _rate_limited()
    return key


@public_router.post("/send")
async def api_send(body: SendIn, request: Request):
    db = get_supabase()
    key = await asyncio.to_thread(_api_key, request, db, _key_limiter)
    if isinstance(key, JSONResponse):
        return key
    try:
        result = await svc.send_code(db, key["tenant_id"], phone=body.phone, mode=body.mode, code=body.code,
                                     ref=body.ref, origin="api", api_key_id=key["id"])
    except svc.OtpError as e:
        return _from_service(e)
    return _ok(result)


@public_router.post("/verify")
async def api_verify(body: VerifyIn, request: Request):
    db = get_supabase()
    key = await asyncio.to_thread(_api_key, request, db, _verify_limiter)
    if isinstance(key, JSONResponse):
        return key
    try:
        result = await asyncio.to_thread(svc.verify, db, key["tenant_id"], code=body.code,
                                         otp_id=body.otp_id, phone=body.phone)
    except svc.OtpError as e:
        return _from_service(e)
    return _ok(result)


@public_router.get("/{otp_id}")
async def api_status(otp_id: str, request: Request):
    db = get_supabase()
    key = await asyncio.to_thread(_api_key, request, db, _key_limiter)
    if isinstance(key, JSONResponse):
        return key
    row = await asyncio.to_thread(svc.get_request, db, key["tenant_id"], otp_id)
    if not row:
        return _error(404, "not_found", "No code found for this request")
    return _ok(svc.public_view(row))


# ================================================================ dashboard

class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_mode: Optional[Mode] = None
    fallback_wait_seconds: Optional[int] = None
    max_per_hour: Optional[int] = None
    expiry_minutes: Optional[int] = None
    code_length: Optional[int] = None
    max_attempts: Optional[int] = None
    sms_sender_id: Optional[str] = Field(None, max_length=20)
    sms_message_id: Optional[str] = Field(None, max_length=40)
    wa_template_name: Optional[str] = Field(None, max_length=60)
    wa_template_language: Optional[str] = Field(None, max_length=10)
    status_webhook_url: Optional[str] = Field(None, max_length=500)


class ConsoleSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=6, max_length=20)
    mode: Optional[Mode] = None
    code: Optional[str] = Field(None, min_length=4, max_length=10)


class ConsoleVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    otp_id: str = Field(max_length=40)
    code: str = Field(min_length=4, max_length=10)


class TemplateCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    language: str = Field(min_length=2, max_length=10)


def _overview(tenant_id: str) -> dict:
    db = get_supabase()
    cfg = svc.get_settings(db, tenant_id)
    return {
        "settings": cfg,
        "channels": {
            "sms": {"ready": svc.sms_problem(db, tenant_id, cfg) is None, "problem": svc.sms_problem(db, tenant_id, cfg)},
            "whatsapp": {"ready": svc.whatsapp_problem(tenant_id, cfg) is None, "problem": svc.whatsapp_problem(tenant_id, cfg)},
        },
        "not_requested_7d": svc.not_requested_count(db, tenant_id),
        "failed_updates_7d": svc.failed_webhook_count(db, tenant_id),
        "limits": svc.LIMITS,
    }


@router.get("/overview")
async def console_overview(ctx: dict = Depends(view)):
    return _ok(await asyncio.to_thread(_overview, ctx["tenant_id"]))


@router.put("/settings")
async def console_save_settings(body: SettingsIn, ctx: dict = Depends(settings_manage)):
    patch = body.model_dump(exclude_unset=True)
    try:
        saved = await asyncio.to_thread(svc.save_settings, get_supabase(), ctx["tenant_id"], patch)
    except svc.OtpError as e:
        return _from_service(e)
    _audit(ctx, "tenant.otp_settings_updated", ctx["tenant_id"], {"fields": sorted(patch)})
    return _ok({"settings": saved})


@router.post("/webhook-secret")
async def console_rotate_secret(ctx: dict = Depends(require_owner)):
    if not _key_change_limiter.allow(ctx["tenant_id"]):
        return _rate_limited()
    secret = await asyncio.to_thread(svc.rotate_webhook_secret, get_supabase(), ctx["tenant_id"])
    _audit(ctx, "tenant.otp_webhook_secret_rotated", ctx["tenant_id"], {})
    return _ok({"secret": secret})


@router.post("/webhook-test")
async def console_webhook_test(ctx: dict = Depends(settings_manage)):
    """Sends one signed `test` event to the saved status URL and says what came back."""
    if not _console_send_limiter.allow(ctx["tenant_id"]):
        return _rate_limited()
    db = get_supabase()
    cfg = await asyncio.to_thread(svc.get_settings, db, ctx["tenant_id"])
    secret = await asyncio.to_thread(svc._webhook_secret, db, ctx["tenant_id"])
    if not cfg.get("status_webhook_url"):
        return _error(409, "no_webhook_url", "Save a status URL first")
    if not secret:
        return _error(409, "no_webhook_secret", "Create the signing secret first")
    payload = {"id": f"evt_test_{int(time.time())}", "event": "test", "otp_id": None, "ref": None,
               "phone": None, "mode": None, "source": None, "status": None, "sms": None, "whatsapp": None,
               "whatsapp_backup_sent": False}
    error = await svc._post_event(cfg["status_webhook_url"], secret, {"event": "test", "payload": payload})
    return _ok({"ok": error is None, "error": error})


@router.post("/send")
async def console_send(body: ConsoleSendIn, ctx: dict = Depends(manage)):
    if not _console_send_limiter.allow(ctx["tenant_id"]):
        return _rate_limited()
    try:
        result = await svc.send_code(get_supabase(), ctx["tenant_id"], phone=body.phone, mode=body.mode,
                                     code=body.code, origin="dashboard", created_by=ctx.get("user_id"))
    except svc.OtpError as e:
        return _from_service(e)
    return _ok(result)


@router.post("/verify")
async def console_verify(body: ConsoleVerifyIn, ctx: dict = Depends(manage)):
    try:
        result = await asyncio.to_thread(svc.verify, get_supabase(), ctx["tenant_id"], code=body.code,
                                         otp_id=body.otp_id)
    except svc.OtpError as e:
        return _from_service(e)
    return _ok(result)


@router.get("/history")
async def console_history(before: Optional[str] = None, limit: int = 50, ctx: dict = Depends(view)):
    rows = await asyncio.to_thread(svc.history, get_supabase(), ctx["tenant_id"], limit=limit, before=before)
    return _ok({"items": rows})


@router.get("/history/{otp_id}")
async def console_history_item(otp_id: str, ctx: dict = Depends(view)):
    db = get_supabase()
    row = await asyncio.to_thread(svc.get_request, db, ctx["tenant_id"], otp_id)
    if not row:
        return _error(404, "not_found", "Not found")
    events = (db.table("otp_status_events").select("event, status, attempts, last_error, created_at, delivered_at")
              .eq("tenant_id", ctx["tenant_id"]).eq("otp_id", row["id"]).order("id").execute()).data or []
    return _ok({"item": svc.history_view(row), "updates": events})


# ---------------------------------------------------------------- template pickers

@router.get("/sms-templates")
async def console_sms_templates(ctx: dict = Depends(view)):
    """Approved DLT templates with exactly one variable: the code goes in it."""
    key = get_setting("bulk9_api_key", tenant_id=ctx["tenant_id"])
    if not key:
        return _ok({"templates": [], "problem": "Connect your SMS account first."})
    try:
        body = await bulk9_client.list_dlt(key, "template")
    except bulk9_client.Bulk9Error as e:
        return _ok({"templates": [], "problem": str(e)})
    except Exception:
        return _ok({"templates": [], "problem": "SMS service did not answer. Try again."})
    out: list[dict] = []

    def walk(node, sender=None):
        if isinstance(node, dict):
            sender = node.get("sender_id") or sender
            if node.get("message_id") is not None and node.get("message"):
                if int(node.get("var_count") or 0) == 1 and sender:
                    out.append({"sender_id": sender, "message_id": str(node["message_id"]),
                                "message": node["message"]})
            for value in node.values():
                walk(value, sender)
        elif isinstance(node, list):
            for value in node:
                walk(value, sender)

    walk(body)
    seen, unique = set(), []
    for t in out:
        if (t["sender_id"], t["message_id"]) not in seen:
            seen.add((t["sender_id"], t["message_id"]))
            unique.append(t)
    return _ok({"templates": unique, "problem": None})


def _waba(tenant_id: str) -> str | None:
    return get_setting("meta_waba_id", tenant_id=tenant_id)


@router.get("/whatsapp-templates")
async def console_wa_templates(ctx: dict = Depends(view)):
    from app.services import meta_cloud
    waba = _waba(ctx["tenant_id"])
    if not waba or not get_setting("meta_access_token", tenant_id=ctx["tenant_id"]):
        return _ok({"templates": [], "problem": "Connect your WhatsApp number first."})
    try:
        items = await meta_cloud.list_all_templates(waba, tenant_id=ctx["tenant_id"])
    except Exception:
        return _ok({"templates": [], "problem": "Couldn't load templates from WhatsApp. Try again."})
    templates = [
        {"name": t.get("name"), "language": t.get("language"), "status": t.get("status"),
         "body": next((c.get("text") for c in (t.get("components") or []) if c.get("type") == "BODY"), None)}
        for t in items if (t.get("category") or "").upper() == "AUTHENTICATION"
    ]
    return _ok({"templates": templates, "problem": None})


@router.post("/whatsapp-templates")
async def console_wa_template_create(body: TemplateCreateIn, ctx: dict = Depends(settings_manage)):
    """Submits Anril's standard authentication template: the code, WhatsApp's 'do not share'
    line, an expiry note and a Copy code button. Meta reviews it; the picker shows its status."""
    from app.services import meta_cloud
    if not _key_change_limiter.allow(ctx["tenant_id"]):
        return _rate_limited()
    if not TEMPLATE_NAME_RE.fullmatch(body.name):
        return _error(400, "invalid_name", "Use lowercase letters, numbers and _ only")
    if not LANG_RE.fullmatch(body.language):
        return _error(400, "invalid_language", "Unknown language code")
    waba = _waba(ctx["tenant_id"])
    token = get_setting("meta_access_token", tenant_id=ctx["tenant_id"])
    if not waba or not token:
        return _error(409, "whatsapp_not_connected", "Connect your WhatsApp number first.")
    cfg = await asyncio.to_thread(svc.get_settings, get_supabase(), ctx["tenant_id"])
    payload = {
        "name": body.name, "language": body.language, "category": "AUTHENTICATION",
        "components": [
            {"type": "BODY", "add_security_recommendation": True},
            {"type": "FOOTER", "code_expiration_minutes": int(cfg["expiry_minutes"])},
            {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}]},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{meta_cloud._GRAPH_BASE}/{waba}/message_templates", json=payload,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return _error(502, "whatsapp_unreachable", "WhatsApp did not answer. Try again.")
    if not resp.is_success:
        try:
            err = resp.json().get("error", {})
            message = err.get("error_user_msg") or err.get("message") or "WhatsApp rejected the template"
        except (json.JSONDecodeError, ValueError):
            message = "WhatsApp rejected the template"
        return _error(400, "template_rejected", str(message)[:300])
    data = resp.json()
    _audit(ctx, "tenant.otp_template_submitted", ctx["tenant_id"], {"name": body.name, "language": body.language})
    return _ok({"name": body.name, "language": body.language, "status": data.get("status") or "PENDING"})


# ---------------------------------------------------------------- API keys (owner only)

@router.get("/keys")
async def console_keys(ctx: dict = Depends(require_owner)):
    return _ok({"keys": await asyncio.to_thread(svc.list_keys, get_supabase(), ctx["tenant_id"])})


@router.post("/keys")
async def console_create_key(ctx: dict = Depends(require_owner)):
    if not _key_change_limiter.allow(ctx["tenant_id"]):
        return _rate_limited()
    db = get_supabase()
    active = [k for k in await asyncio.to_thread(svc.list_keys, db, ctx["tenant_id"]) if k["status"] == "active"]
    if len(active) >= 2:  # two lets a client rotate without downtime; more is clutter
        return _error(409, "too_many_keys", "You already have 2 active keys. Revoke one first.")
    created = await asyncio.to_thread(svc.create_key, db, ctx["tenant_id"], ctx.get("user_id"))
    _audit(ctx, "tenant.otp_key_created", created["id"], {"prefix": created["key_prefix"]})
    return _ok(created)


@router.delete("/keys/{key_id}")
async def console_revoke_key(key_id: str, ctx: dict = Depends(require_owner)):
    if not _key_change_limiter.allow(ctx["tenant_id"]):
        return _rate_limited()
    try:
        ok = await asyncio.to_thread(svc.revoke_key, get_supabase(), ctx["tenant_id"], key_id)
    except Exception:
        ok = False
    if not ok:
        return _error(404, "no_active_key", "No active key with that id")
    _audit(ctx, "tenant.otp_key_revoked", key_id, {})
    return _ok({"ok": True})
