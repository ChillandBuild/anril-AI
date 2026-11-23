"""Auto-Messages routes. See services/auto_messages.py and docs/designs/auto-messages.md.

Public (no auth): the tenant is identified by an opaque token in the path, the
same shape as marketplace_intake.py. The token is NOT secret in practice -- the
website form puts it in the page -- so all it can do is create a lead and
trigger the tenant's own approved templates, and it is rate-limited per IP and
per tenant. It can never read data.
  POST /in/{token}          JSON or form fields (website form, Zapier, Pabbly, apps, billing software)
  GET  /in/{token}/form.js  the copy-paste website form

Authenticated: setup (URL + snippet), rules, custom events, send log, preview send.
"""
import functools
import ipaddress
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.config import settings as env_settings
from app.config_dynamic import get_setting, save_setting
from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import auto_messages as svc
from app.services.audit_log import record_audit_event
from app.services import private_send as private_send_svc

logger = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter()

require_auto_messages_manage = require_permission("auto_messages.manage")
require_auto_messages_view = require_permission("auto_messages.view")

TOKEN_KEY = "auto_messages_ingest_token"
_RENDER_BASE_URL = "https://aira-ai-5tfr.onrender.com"
_PUBLIC_HEADERS = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}


class _SlidingWindow:
    """`limit` hits per `window` seconds per key, in-process (same approach as
    brain_sandbox: slowapi in main.py is per IP only and can't express per tenant).
    Keys whose hits have all expired are swept out once per window, so memory is bounded
    by the keys seen in the last window, not every IP since the process started."""

    def __init__(self, limit: int, window_seconds: float):
        self._limit, self._window = limit, window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._next_sweep = time.monotonic() + window_seconds

    def __len__(self) -> int:
        with self._lock:
            return len(self._hits)

    def _sweep(self, now: float) -> None:
        stale = [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= self._window]
        for k in stale:
            del self._hits[k]
        self._next_sweep = now + self._window

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if now >= self._next_sweep:
                self._sweep(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Preview sends go to a real phone and cost a message: 5 a minute per tenant is plenty.
_preview_limiter = _SlidingWindow(5, 60)
# The in-process limiter resets on restart and is per worker, so the daily cap below is
# counted from the audit log (every preview attempt writes one event) and survives both.
PREVIEW_AUDIT_ACTION = "auto_messages.preview_sent"
PREVIEW_DAILY_LIMIT = 20
# One person filling a form a few times is fine; a script hammering it is not.
_per_ip = _SlidingWindow(10, 10 * 60)
# A busy billing system can post a lot; this only stops a runaway loop or abuse.
_per_tenant = _SlidingWindow(1000, 60 * 60)


def _base_url() -> str:
    base_url = get_setting("public_base_url") or env_settings.public_base_url or _RENDER_BASE_URL
    return base_url.rstrip("/")


def _urls(token: str) -> dict:
    base = f"{_base_url()}/api/v1/auto-messages/in/{token}"
    return {"ingest_url": base, "form_script_url": f"{base}/form.js"}


def _resolve_tenant(db, token: str) -> str | None:
    if not token or len(token) > 100:
        return None
    rows = (
        db.table("app_settings").select("tenant_id").eq("key", TOKEN_KEY).eq("value", token).limit(1).execute()
    ).data or []
    return rows[0]["tenant_id"] if rows else None


# Where requests reach us from in production (checked live 2026-11-23):
#   client -> Cloudflare (Render's DDoS edge: the onrender.com host is a CNAME to
#   *.cdn.cloudflare.net, answers with server: cloudflare + cf-ray) -> Render's load balancer
#   (peer 10.209.x.x in the uvicorn access log) -> uvicorn -> this app.
# Uvicorn on Render trusts every proxy (FORWARDED_ALLOW_IPS=* behaviour): it replaces
# request.client with the LEFTMOST X-Forwarded-For entry, which the caller types. A request
# with "X-Forwarded-For: 203.0.113.77" was logged as 203.0.113.77:0. So request.client.host
# is NOT a safe key on Render, and neither is anything we parse out of X-Forwarded-For.
# CF-Connecting-IP is: Cloudflare overwrites it on every request, and the service is only
# reachable through Cloudflare (render.com/docs/web-services: the port "is not directly
# reachable via the public internet").
# TRUSTED_PROXY_CIDRS (optional, for a setup where uvicorn's rewrite is switched off): when
# set, CF-Connecting-IP is only believed from a peer inside those ranges.


@functools.lru_cache(maxsize=1)
def _trusted_proxies() -> tuple | None:
    raw = env_settings.trusted_proxy_cidrs
    if raw is None:
        return None
    nets = []
    for cidr in (c.strip() for c in raw.split(",")):
        if not cidr:
            continue
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXY_CIDRS: ignoring %r, not a CIDR", cidr)
    return tuple(nets)


def _parse_ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def _client_ip(request: Request) -> str:
    """The client address a per-IP rate limit keys on.

    CF-Connecting-IP when it holds a valid IP (Cloudflare sets it on every request and
    overwrites a client-typed one), else request.client.host. X-Forwarded-For and
    True-Client-IP are never read here: the caller controls the leftmost X-Forwarded-For
    entry, and True-Client-IP is not set on every Cloudflare plan, so a typed one passes
    through. With TRUSTED_PROXY_CIDRS set, CF-Connecting-IP only counts from those peers."""
    peer = request.client.host if request.client and request.client.host else "unknown"
    trusted = _trusted_proxies()
    if trusted is not None:
        peer_ip = _parse_ip(peer)
        if peer_ip is None or not any(ipaddress.ip_address(peer_ip) in net for net in trusted):
            return peer
    return _parse_ip(request.headers.get("cf-connecting-ip")) or peer


async def _read_payload(request: Request) -> dict:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        return {k: v for k, v in form.items() if isinstance(v, str)}
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Send JSON or form fields")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    return payload


def _public(status_code: int, content: dict) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=content, headers=_PUBLIC_HEADERS)


def _private_send_refusal(db, tenant_id: str) -> JSONResponse | None:
    """A tenant that sends from its own server must not also fire the hosted form or
    link: those would send from Anril and double up (and the plug-in keeps no leads here)."""
    if not private_send_svc.has_active_key(db, tenant_id):
        return None
    return _public(409, {"error": "This account sends from its own server", "code": "private_send_on"})


def _coded(status_code: int, code: str, message: str) -> JSONResponse:
    """Authenticated error with a machine code: "detail" is the message the dashboard
    already shows for HTTPException errors, "code" is for the UI to branch on."""
    return JSONResponse(status_code=status_code, content={"detail": message, "code": code})


# The website form posts form-encoded fields, a CORS "simple request" with no
# preflight, so the global CORSMiddleware allow-list never blocks it and the
# Access-Control-Allow-Origin: * on the response lets the form read the result.
@public_router.post("/in/{token}")
async def ingest(token: str, request: Request):
    db = get_supabase()
    tenant_id = _resolve_tenant(db, token)
    if not tenant_id:
        return _public(401, {"error": "Unauthorized", "code": "unauthorized"})
    refused = _private_send_refusal(db, tenant_id)
    if refused:
        return refused
    try:
        payload = await _read_payload(request)
    except HTTPException as e:
        return _public(400, {"error": e.detail, "code": "bad_request"})
    source = "website" if payload.get("_src") == "form" else "api"
    # The per-IP limit is for the website form (one visitor = one IP). An app or
    # billing server sends every customer from the same IP, so API calls are
    # held only by the per-tenant cap.
    ip_ok = source != "website" or _per_ip.allow(f"{token}:{_client_ip(request)}")
    if not ip_ok or not _per_tenant.allow(tenant_id):
        return _public(429, {"error": "Too many requests, try again later", "code": "rate_limited"})

    # Hidden honeypot field on the website form: bots fill it, people can't see it.
    honeypot = payload.get("_hp")
    if isinstance(honeypot, str) and honeypot.strip():
        return _public(200, {"status": "ok"})

    data = svc.parse_payload(payload)
    result = await svc.handle_event(tenant_id, source, data, db=db)
    if result["status"] != "ok":
        return _public(422, {"error": result.get("detail"), "code": "ignored"})
    return _public(200, {k: result.get(k) for k in ("status", "event", "message_status", "reason")})


@public_router.get("/in/{token}/form.js")
def form_script(token: str):
    db = get_supabase()
    tenant_id = _resolve_tenant(db, token)
    if not tenant_id:
        return Response("/* Anril: this form link is no longer valid. Copy the new snippet from Anril. */",
                        media_type="application/javascript", headers=_PUBLIC_HEADERS)
    refused = _private_send_refusal(db, tenant_id)
    if refused:
        # A <script src> that receives JSON is a syntax error on the client's page, so
        # answer in JS (status 409 kept), the same way as the invalid-token branch above.
        return Response("/* Anril: this account sends from its own server, so the website form is off. */",
                        status_code=409, media_type="application/javascript", headers=_PUBLIC_HEADERS)
    script = _FORM_JS.replace("__ENDPOINT__", json.dumps(_urls(token)["ingest_url"]))
    return Response(script, media_type="application/javascript",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})


# The website form. Renders into every <div data-anril-form>, and into every
# <div data-aira-form> already on customers' pages (the old snippet keeps working:
# the script is served from here, so it is upgraded for them). Options on the div:
#   data-event="signed_up"  default "interested"
#   data-title, data-button, data-success  text overrides
# Plain DOM, no dependencies, styles scoped under .anril-f (and .aira-f for old markup)
# so it can't break the host page.
_FORM_JS = r"""(function () {
  var ENDPOINT = __ENDPOINT__;
  function rules(p) {
    var f = "." + p + "-f";
    return f + "{font-family:inherit;max-width:380px;display:grid;gap:10px;padding:18px;border:1px solid #e3e3e3;border-radius:12px;background:#fff;color:#1a1a1a;box-sizing:border-box}" +
      f + " *{box-sizing:border-box}" + f + " h3{margin:0 0 2px;font-size:17px;font-weight:600}" +
      f + " input{width:100%;padding:10px 12px;border:1px solid #cfcfcf;border-radius:8px;font:inherit;font-size:15px;background:#fff;color:inherit}" +
      f + " input:focus{outline:2px solid #25d366;outline-offset:1px;border-color:#25d366}" +
      f + " button{padding:11px 14px;border:0;border-radius:8px;background:#25d366;color:#fff;font:inherit;font-size:15px;font-weight:600;cursor:pointer}" +
      f + " button[disabled]{opacity:.6;cursor:default}" + f + " ." + p + "-n{font-size:12px;color:#666;margin:0}" +
      f + " ." + p + "-e{font-size:13px;color:#c0392b;margin:0}" + f + " ." + p + "-ok{font-size:15px;margin:0;padding:6px 0}" +
      f + " ." + p + "-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}";
  }
  // New markup (anril-*) and the old markup already on customers' pages (aira-*) are both styled.
  var css = rules("anril") + rules("aira");
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    for (var k in attrs) { if (attrs[k] !== undefined) e.setAttribute(k, attrs[k]); }
    if (text) e.textContent = text;
    return e;
  }
  function render(host, p) {
    if (host.getAttribute("data-" + p + "-ready")) return;
    host.setAttribute("data-" + p + "-ready", "1");
    var form = el("form", { "class": p + "-f", novalidate: "" });
    form.appendChild(el("h3", {}, host.getAttribute("data-title") || "Get details on WhatsApp"));
    var name = el("input", { name: "name", placeholder: "Your name", autocomplete: "name", maxlength: "80" });
    var phone = el("input", { name: "phone", placeholder: "WhatsApp number", type: "tel", autocomplete: "tel", inputmode: "tel", maxlength: "16", required: "" });
    form.appendChild(name); form.appendChild(phone);
    var hp = el("div", { "class": p + "-hp", "aria-hidden": "true" });
    hp.appendChild(el("input", { name: "_hp", tabindex: "-1", autocomplete: "off" }));
    form.appendChild(hp);
    var err = el("p", { "class": p + "-e", role: "alert" });
    var btn = el("button", { type: "submit" }, host.getAttribute("data-button") || "Send me details");
    form.appendChild(err); form.appendChild(btn);
    form.appendChild(el("p", { "class": p + "-n" }, "We'll send you updates on WhatsApp."));
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      err.textContent = "";
      var digits = (phone.value || "").replace(/[^0-9]/g, "");
      if (digits.length < 10 || digits.length > 13) { err.textContent = "Please enter a valid WhatsApp number."; phone.focus(); return; }
      btn.disabled = true;
      var body = new URLSearchParams();
      body.set("name", name.value.trim()); body.set("phone", phone.value.trim());
      body.set("event", host.getAttribute("data-event") || "interested");
      body.set("page_url", location.href); body.set("_src", "form");
      body.set("_hp", form.querySelector("[name=_hp]").value);
      fetch(ENDPOINT, { method: "POST", body: body }).then(function (r) {
        if (r.status === 429) throw new Error("Too many tries. Please wait a few minutes.");
        if (!r.ok) throw new Error("Please check your number and try again.");
        form.innerHTML = "";
        form.appendChild(el("p", { "class": p + "-ok" }, host.getAttribute("data-success") || "Thanks! Check WhatsApp in a few minutes."));
      }).catch(function (e) { err.textContent = e.message || "Something went wrong. Please try again."; btn.disabled = false; });
    });
    host.appendChild(form);
  }
  function init() {
    if (!document.getElementById("anril-f-css")) { var s = el("style", { id: "anril-f-css" }); s.textContent = css; document.head.appendChild(s); }
    var prefixes = ["anril", "aira"];
    for (var j = 0; j < prefixes.length; j++) {
      var hosts = document.querySelectorAll("[data-" + prefixes[j] + "-form]");
      for (var i = 0; i < hosts.length; i++) render(hosts[i], prefixes[j]);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
"""


# ---------------------------------------------------------------- setup

@router.get("/setup")
def get_setup(ctx: dict = Depends(require_auto_messages_manage)):
    token = get_setting(TOKEN_KEY, tenant_id=ctx["tenant_id"])
    urls = _urls(token) if token else {"ingest_url": None, "form_script_url": None}
    # The dashboard hides the form and link for a tenant that sends from its own server.
    return {**urls, "private_send_on": private_send_svc.has_active_key(get_supabase(), ctx["tenant_id"])}


@router.post("/setup/token")
def rotate_token(ctx: dict = Depends(require_auto_messages_manage)):
    """(Re)generates the intake link. Rotating breaks the old link at once: the
    website snippet and any Zapier/app setup must be updated."""
    token = secrets.token_urlsafe(24)
    save_setting(TOKEN_KEY, token, tenant_id=ctx["tenant_id"])
    return _urls(token)


# ---------------------------------------------------------------- rules

class VariableSpec(BaseModel):
    source: str = Field(pattern="^(first_name|full_name|page_url|phone|extra|text)$")
    key: str | None = Field(default=None, max_length=50)
    value: str | None = Field(default=None, max_length=200)
    fallback: str | None = Field(default=None, max_length=200)


# delay_minutes is no longer accepted: pydantic ignores the unknown field, so an older
# dashboard that still sends it gets no error, and the column keeps its default 0.
class RuleIn(BaseModel):
    event: str = Field(pattern="^[a-z][a-z0-9_]{1,39}$")
    template_id: str
    variables: list[VariableSpec] = Field(default_factory=list, max_length=20)
    button_param: VariableSpec | None = None
    enabled: bool = True


class RulePatch(BaseModel):
    template_id: str | None = None
    variables: list[VariableSpec] | None = Field(default=None, max_length=20)
    button_param: VariableSpec | None = None
    enabled: bool | None = None


def _check_template(db, tenant_id: str, template_id: str) -> None:
    rows = (
        db.table("message_templates").select("status").eq("id", template_id).eq("tenant_id", tenant_id)
        .limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Template not found")
    if (rows[0].get("status") or "").upper() != "APPROVED":
        raise HTTPException(status_code=400, detail="Pick a template that Meta has approved")


@router.get("/rules")
def list_rules(ctx: dict = Depends(require_auto_messages_view)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    rows = db.table("auto_message_rules").select("*").eq("tenant_id", tenant_id).order("created_at").execute().data or []
    if not rows:
        return {"rules": []}
    approved = svc.approved_template_ids(db, tenant_id, [r["template_id"] for r in rows])
    sent = svc.sent_event_keys(db, tenant_id)
    return {"rules": [
        {**r, "has_sent": r["event"] in sent, "template_approved": r["template_id"] in approved} for r in rows
    ]}


@router.post("/rules")
def create_rule(payload: RuleIn, ctx: dict = Depends(require_auto_messages_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if not svc.is_valid_event_key(db, tenant_id, payload.event):
        return _coded(422, "unknown_event", "That event doesn't exist. Add it under your own events first.")
    _check_template(db, tenant_id, payload.template_id)
    existing = (
        db.table("auto_message_rules").select("id").eq("tenant_id", tenant_id).eq("event", payload.event)
        .limit(1).execute()
    ).data or []
    if existing:
        raise HTTPException(status_code=409, detail="There is already a message for this event")
    row = {
        **payload.model_dump(exclude={"variables", "button_param"}),
        "variables": [v.model_dump() for v in payload.variables],
        "button_param": payload.button_param.model_dump() if payload.button_param else None,
        "tenant_id": tenant_id,
    }
    inserted = db.table("auto_message_rules").insert(row).execute().data or []
    if not inserted:
        raise HTTPException(status_code=500, detail="Could not save")
    return inserted[0]


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: str, payload: RulePatch, ctx: dict = Depends(require_auto_messages_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    patch = payload.model_dump(exclude_unset=True)
    if "template_id" in patch:
        if not patch["template_id"]:
            raise HTTPException(status_code=400, detail="Pick a template")
        _check_template(db, tenant_id, patch["template_id"])
    if "variables" in patch and patch["variables"] is not None:
        patch["variables"] = [v.model_dump() for v in payload.variables or []]
    elif "variables" in patch:
        patch.pop("variables")
    if "button_param" in patch:
        patch["button_param"] = payload.button_param.model_dump() if payload.button_param else None
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to change")
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = (
        db.table("auto_message_rules").update(patch).eq("id", rule_id).eq("tenant_id", tenant_id).execute()
    ).data or []
    if not updated:
        raise HTTPException(status_code=404, detail="Rule not found")
    return updated[0]


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, ctx: dict = Depends(require_auto_messages_manage)):
    deleted = (
        get_supabase().table("auto_message_rules").delete().eq("id", rule_id).eq("tenant_id", ctx["tenant_id"])
        .execute()
    ).data or []
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": True}


class PreviewIn(BaseModel):
    phone: str = Field(min_length=1, max_length=20)


def _ist_day_start_utc(now: datetime) -> datetime:
    """Midnight IST of the day containing `now`, as a UTC datetime."""
    local = now.astimezone(svc.IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _previews_sent_today(db, tenant_id: str) -> int:
    return (
        db.table("app_audit_logs").select("id", count="exact")
        .eq("tenant_id", tenant_id).eq("action", PREVIEW_AUDIT_ACTION)
        .gte("created_at", _ist_day_start_utc(_utcnow()).isoformat())
        .limit(1).execute()
    ).count or 0


@router.post("/rules/{rule_id}/preview")
async def preview_rule(rule_id: str, payload: PreviewIn, ctx: dict = Depends(require_auto_messages_manage)):
    """Sends this rule's template, with sample values, to the number typed in. Any valid
    mobile number is accepted (nothing proves it is the owner's), so every attempt is
    audited with the last 4 digits only and a tenant gets 20 previews per IST day. No
    lead, no send-log row. Goes through the same send helper as real sends."""
    from app.routes.upload import _normalize_phone
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    phone = _normalize_phone(payload.phone)
    if not phone:
        return _coded(422, "invalid_phone", "Enter a valid mobile number")
    rows = (
        db.table("auto_message_rules").select("*").eq("id", rule_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Rule not found")
    if not _preview_limiter.allow(tenant_id):
        return _coded(429, "rate_limited", "Too many previews. Try again in a minute.")
    # Check-then-send, so concurrent requests can overshoot by a few; the 5/min limiter bounds that.
    if _previews_sent_today(db, tenant_id) >= PREVIEW_DAILY_LIMIT:
        return _coded(429, "preview_daily_limit",
                      f"You've sent {PREVIEW_DAILY_LIMIT} previews today. Try again tomorrow.")
    result = await svc.send_preview(db, tenant_id, rows[0], phone)
    record_audit_event(
        db, tenant_id=tenant_id, actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
        action=PREVIEW_AUDIT_ACTION, target_type="auto_message_rule", target_id=rule_id,
        metadata={"rule_id": rule_id, "phone_last4": phone[-4:], "status": result.get("status")},
    )
    return result


@router.get("/templates")
def list_templates(ctx: dict = Depends(require_auto_messages_view)):
    """Approved templates with what the rule editor needs: the body's {{n}}
    count, the header type and whether a URL button has a {{1}} suffix."""
    rows = (
        get_supabase().table("message_templates")
        .select("id, name, category, language, status, body_text, header_media_type, header_text, buttons")
        .eq("tenant_id", ctx["tenant_id"]).execute()
    ).data or []
    out = []
    for t in rows:
        if (t.get("status") or "").upper() != "APPROVED":
            continue
        out.append({
            "id": t["id"], "name": t["name"], "category": t.get("category"), "language": t.get("language"),
            "body_text": t.get("body_text") or "", "header_media_type": t.get("header_media_type"),
            "variable_count": len(set(svc.VAR_RE.findall(t.get("body_text") or ""))),
            "has_dynamic_button": any(
                (b.get("type") or "").upper() == "URL" and svc.VAR_RE.search(b.get("url") or "")
                for b in (t.get("buttons") or [])
            ),
            "buttons": [b.get("text") for b in (t.get("buttons") or []) if b.get("text")],
        })
    return {"templates": sorted(out, key=lambda t: t["name"])}


# ---------------------------------------------------------------- events

class EventIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)


class EventPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)


def _clean_description(value: str | None) -> str | None:
    return (value or "").strip() or None


@router.get("/events")
def list_events(ctx: dict = Depends(require_auto_messages_view)):
    return {
        "builtin": list(svc.BUILTIN_EVENTS),
        "custom": svc.list_custom_events(get_supabase(), ctx["tenant_id"]),
        "limit": svc.MAX_CUSTOM_EVENTS,
    }


@router.post("/events")
def create_event(payload: EventIn, ctx: dict = Depends(require_auto_messages_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    label = payload.label.strip()
    key = svc.derive_event_key(label)
    if not key:
        return _coded(422, "invalid_label", "Use a name that starts with a letter, like Kundli ready")
    existing = svc.list_custom_events(db, tenant_id)
    if svc.is_reserved_event_key(key) or any(e["key"] == key for e in existing):
        return _coded(409, "event_exists", f"{key} is already used")
    if len(existing) >= svc.MAX_CUSTOM_EVENTS:
        return _coded(409, "event_limit", f"You can add up to {svc.MAX_CUSTOM_EVENTS} events")
    row = {"tenant_id": tenant_id, "key": key, "label": label, "description": _clean_description(payload.description)}
    # Two simultaneous creates can both pass the check above; UNIQUE (tenant_id, key) settles it.
    # The 20-event cap has the same theoretical race (a tenant could land on 21); left as is.
    try:
        inserted = db.table("auto_message_events").insert(row).execute().data or []
    except Exception as e:
        if getattr(e, "code", None) == "23505" or "23505" in str(e):
            return _coded(409, "event_exists", f"{key} is already used")
        raise
    if not inserted:
        raise HTTPException(status_code=500, detail="Could not save")
    return svc.public_event(inserted[0])


@router.patch("/events/{key}")
def update_event(key: str, payload: EventPatch, ctx: dict = Depends(require_auto_messages_manage)):
    """Name and description only: the key is what the developer's app sends, so it never changes."""
    if key in svc.EVENTS:
        raise HTTPException(status_code=400, detail="Built-in events can't be changed")
    patch = payload.model_dump(exclude_unset=True)
    if patch.get("label") is not None:
        patch["label"] = patch["label"].strip()
    if "label" in patch and not patch["label"]:
        raise HTTPException(status_code=422, detail="Name can't be empty")
    if "description" in patch:
        patch["description"] = _clean_description(patch["description"])
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to change")
    updated = (
        get_supabase().table("auto_message_events").update(patch)
        .eq("tenant_id", ctx["tenant_id"]).eq("key", key).execute()
    ).data or []
    if not updated:
        raise HTTPException(status_code=404, detail="Event not found")
    return svc.public_event(updated[0])


@router.delete("/events/{key}")
def delete_event(key: str, ctx: dict = Depends(require_auto_messages_manage)):
    """Deletes the event and its message. Old send-log rows keep the key as text."""
    if key in svc.EVENTS:
        raise HTTPException(status_code=400, detail="Built-in events can't be deleted")
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if not svc.find_custom_event(db, tenant_id, key):
        raise HTTPException(status_code=404, detail="Event not found")
    db.table("auto_message_rules").delete().eq("tenant_id", tenant_id).eq("event", key).execute()
    db.table("auto_message_events").delete().eq("tenant_id", tenant_id).eq("key", key).execute()
    return {"deleted": True}


# ---------------------------------------------------------------- send log

SENDS_DEFAULT_LIMIT = 10
SENDS_MAX_LIMIT = 50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/summary")
def month_summary(ctx: dict = Depends(require_auto_messages_view)):
    """Sent / failed / skipped for the current calendar month in India time."""
    return svc.month_summary(get_supabase(), ctx["tenant_id"], _utcnow())


@router.get("/sends")
def list_sends(
    status: str | None = None, event: str | None = None,
    limit: int = SENDS_DEFAULT_LIMIT, offset: int = 0,
    ctx: dict = Depends(require_auto_messages_view),
):
    """Newest first. Same {"sends": [...]} shape as before, plus has_more for "Show more"."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    limit = max(1, min(limit, SENDS_MAX_LIMIT))
    offset = max(0, offset)
    q = (
        db.table("auto_message_sends")
        .select("id, lead_id, phone, name, event, source, template_id, status, reason, send_at, sent_at, created_at")
        .eq("tenant_id", tenant_id)
    )
    if status:
        q = q.eq("status", status)
    if event:
        q = q.eq("event", event)
    # One extra row tells us whether another page exists.
    fetched = q.order("created_at", desc=True).range(offset, offset + limit).execute().data or []
    rows, has_more = fetched[:limit], len(fetched) > limit

    template_ids = list({r["template_id"] for r in rows if r.get("template_id")})
    templates = {
        t["id"]: t["name"] for t in (
            db.table("message_templates").select("id, name").eq("tenant_id", tenant_id).in_("id", template_ids).execute().data or []
        )
    } if template_ids else {}
    for r in rows:
        r["template_name"] = templates.get(r.get("template_id"))
    return {"sends": rows, "has_more": has_more}


# ---------------------------------------------------------------- private send

@router.get("/private-send")
def private_send_overview(ctx: dict = Depends(require_auto_messages_view)):
    """Private Send status and the last 30 days of plug-in send counts (no lead data exists here)."""
    return private_send_svc.tenant_overview(get_supabase(), ctx["tenant_id"])
