import asyncio
import csv
import io
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.services import astro_bridge, partner_send_mode, razorpay_oauth
from app.services.audit_log import record_audit_event
from app.services.ai_reply import send_whatsapp
from app.services.deals import format_deal_number
from app.services.intake import (
    alert_bridge_auth_failure,
    change_session_package,
    confirm_intake_payment,
    deliver_astro_reply,
    expire_intake_session,
    get_intake_config,
    get_session_tenant_id,
    notify_payment_failed,
    partner_send_template,
    partner_send_text,
    record_astro_bridge_ids,
    report_extra_deal_payment,
)
from app.services.intake_copy import compose_payment_receipt, gst_receipt_line
from app.services.intake_csv import FIXED_HEADERS, build_csv_headers, build_csv_row
from app.services.payment_razorpay import verify_webhook_signature

logger = logging.getLogger(__name__)
public_router = APIRouter()
router = APIRouter()
require_conversations_view = require_permission("conversations.view")
require_conversations_reply = require_permission("conversations.reply")

VISIBLE_STATUSES = ["awaiting_payment", "paid"]
# Resolved is a real outcome only for a client with the AstroTamil connection: the astrologer's
# delivered reply resolves the session (intake.deliver_astro_reply). For everyone else it stays hidden.
CONNECTED_STATUSES = [*VISIBLE_STATUSES, "resolved"]

SESSION_COLUMNS = (
    "id, lead_id, status, collected_data, field_schema, amount_paise, "
    "amount_mismatch, package_key, package_name, package_amount_paise, "
    "gst_percent, gst_amount_paise, payment_link, paid_at, created_at, leads(name, phone), "
    "astro_question_id, astro_horoscope_id"
)

CSV_MAX_ROWS = 5000

# Both q and cursor are interpolated into PostgREST filter-string syntax
# (or_()), not bound as query parameters, so they're validated against a
# strict allowlist before use rather than merely escaped — a value containing
# PostgREST operators/commas/parens could otherwise reshape the filter.
_SEARCH_QUERY_RE = re.compile(r"^[\w \-+@.]{1,64}$", re.UNICODE)
_CURSOR_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
_CURSOR_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _statuses_for(status: str, connected: bool = False) -> list[str]:
    allowed = CONNECTED_STATUSES if connected else VISIBLE_STATUSES
    if status == "all":
        return allowed
    if status in allowed:
        return [status]
    raise HTTPException(
        status_code=400,
        detail=f"status must be 'all' or one of {allowed}",
    )


def _build_query(
    db, tenant_id: str, status: str, package: str | None, q: str | None, cursor: str | None, limit: int,
    connected: bool = False,
):
    query = (
        db.table("intake_sessions")
        .select(SESSION_COLUMNS)
        .eq("tenant_id", tenant_id)
        .in_("status", _statuses_for(status, connected))
    )
    if package:
        query = query.eq("package_key", package)
    if q:
        # Matches the lead's name or phone. PostgREST needs the embedded-table
        # syntax here because name/phone live on `leads`, not on the session.
        if not _SEARCH_QUERY_RE.match(q):
            raise HTTPException(status_code=400, detail="Invalid search query")
        query = query.or_(f"name.ilike.*{q}*,phone.ilike.*{q}*", foreign_table="leads")
    if cursor:
        parts = cursor.split("|")
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        created_at, last_id = parts
        if not _CURSOR_TIMESTAMP_RE.match(created_at) or not _CURSOR_ID_RE.match(last_id):
            raise HTTPException(status_code=400, detail="Malformed cursor")
        # Keyset, not offset: rows arriving mid-scroll would make offset paging
        # duplicate and skip rows.
        query = query.or_(
            f"created_at.lt.{created_at},and(created_at.eq.{created_at},id.lt.{last_id})"
        )
    return query.order("created_at", desc=True).order("id", desc=True).limit(limit)


def _with_astro_status(rows: list[dict], connected: bool) -> list[dict]:
    """Fold the two AstroTamil ids into one "astro" object, and only for a client that has the
    AstroTamil connection. For everyone else the ids are dropped, so their rows and table are
    exactly what they were before the column existed."""
    for row in rows:
        question_id = row.pop("astro_question_id", None)
        horoscope_id = row.pop("astro_horoscope_id", None)
        if connected:
            row["astro"] = {"sent": question_id is not None, "question_id": question_id, "horoscope_id": horoscope_id}
    return rows


def _with_deal_labels(db, tenant_id: str, rows: list[dict]) -> list[dict]:
    """Each row's deal number ("D-0014"), or None while the session is still only a form.
    A session gets its deal once it reaches awaiting_payment (deals.sync_intake_session)."""
    if not rows:
        return rows
    deals = (
        db.table("deals").select("intake_session_id, deal_number").eq("tenant_id", tenant_id)
        .in_("intake_session_id", [r["id"] for r in rows]).execute()
    ).data or []
    labels = {d["intake_session_id"]: format_deal_number(d["deal_number"]) for d in deals}
    for row in rows:
        row["deal_label"] = labels.get(row["id"])
    return rows


@router.get("/sessions")
def list_intake_sessions(
    status: str = Query("all"),
    package: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    ctx: dict = Depends(require_conversations_view),
):
    db = get_supabase()
    connected = astro_bridge.is_connected(ctx["tenant_id"])
    result = _build_query(db, ctx["tenant_id"], status, package, q, cursor, limit, connected).execute()
    rows = _with_deal_labels(db, ctx["tenant_id"], _with_astro_status(result.data or [], connected))
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = f"{last['created_at']}|{last['id']}"
    page = {"data": rows, "next_cursor": next_cursor}
    if connected:
        page["astro_connected"] = True  # unlocks the Resolved tab; other clients' response is unchanged
    return page


@router.get("/sessions.csv")
def export_intake_sessions_csv(
    status: str = Query("all"),
    package: str | None = Query(None),
    q: str | None = Query(None),
    ctx: dict = Depends(require_conversations_view),
):
    """Honours the active filter and search; ignores the client's column picker,
    which is a viewing preference, not a data one."""
    db = get_supabase()
    connected = astro_bridge.is_connected(ctx["tenant_id"])
    result = _build_query(db, ctx["tenant_id"], status, package, q, None, CSV_MAX_ROWS, connected).execute()
    rows = result.data or []
    if len(rows) == CSV_MAX_ROWS:
        logger.warning(
            f"Intake CSV for tenant {ctx['tenant_id']} hit the {CSV_MAX_ROWS}-row cap"
        )

    headers = build_csv_headers(rows)
    field_keys = [key for key, _ in headers]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(FIXED_HEADERS + [label for _, label in headers])
    for row in rows:
        writer.writerow(build_csv_row(row, field_keys))
    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="intake-{status}.csv"'},
    )


require_settings_view = require_permission("settings.view")
require_settings_manage = require_permission("settings.manage")


@router.get("/partner/config")
def partner_config(ctx: dict = Depends(require_settings_view)):
    """What a partner developer needs before calling the partner send API: the
    tenant id that goes in every request body, the paths, and whether the shared
    secret is on file. The secret itself is never returned here; ops issue it
    (operator console → client → Astro Bridge) and hand it to the partner."""
    from app.config_dynamic import get_setting

    tenant_id = ctx["tenant_id"]
    return {
        "tenant_id": tenant_id,
        "secret_set": bool(get_setting("astro_bridge_secret", tenant_id=tenant_id)),
        "bridge_url_set": bool(get_setting("astro_bridge_url", tenant_id=tenant_id)),
        "api_key_set": bool(get_setting("astro_bridge_api_key", tenant_id=tenant_id)),
        "signature_header": SIGNATURE_HEADER,
        "legacy_signature_header": LEGACY_SIGNATURE_HEADER,
        "paths": {
            "send_template": "/api/v1/intake/partner/send-template",
            "send_text": "/api/v1/intake/partner/send-text",
            "reply_callback": "/api/v1/intake/astro-reply",
            "legacy_prefix": "/api/v1/expert-handoff",
        },
    }


class PartnerSendModeIn(BaseModel):
    # extra="forbid": a tenant_id (or any other field) in the body is a 422, never used.
    model_config = ConfigDict(extra="forbid")

    mode: Literal["template", "event"]


@router.get("/partner/send-mode")
def get_partner_send_mode(ctx: dict = Depends(require_settings_view)):
    """How this account's app calls POST /partner/send-template: "template" (default) or "event"."""
    return {"mode": partner_send_mode.get_partner_send_mode(get_supabase(), ctx["tenant_id"])}


@router.put("/partner/send-mode")
def set_partner_send_mode(body: PartnerSendModeIn, ctx: dict = Depends(require_settings_manage)):
    """Admin switch, set on the Developer page. The app's calls must change at the same time: the
    other shape is refused with 400 wrong_mode from the next call on."""
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    previous = partner_send_mode.get_partner_send_mode(db, tenant_id)
    try:
        partner_send_mode.save_partner_send_mode(db, tenant_id, body.mode)
    except Exception as e:
        logger.error(f"partner_send_mode save failed for tenant {tenant_id}: {e}")
        return JSONResponse(status_code=500, content={
            "error": "Could not save the setting. Nothing was changed; try again.", "code": "setting_not_saved",
        })
    record_audit_event(
        db, tenant_id=tenant_id, actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
        action="tenant.partner_send_mode_updated", target_type="partner_send_mode", target_id=tenant_id,
        metadata={"mode": body.mode, "previous": previous},
    )
    return {"mode": body.mode}


@router.get("/stats")
def intake_stats(ctx: dict = Depends(require_conversations_view)):
    """Intake dashboard: message totals, answer progress and a 14-day trend for
    this tenant. "Answered" means the astrologer's reply came back over the
    bridge (astro_last_reply_id is set); "pending" is paid but not yet answered.
    Mirrors the astrobackmatrimony adminweb "Aira Customers" stats so both teams
    read the same numbers."""
    db = get_supabase()
    rows = (
        db.table("intake_sessions")
        .select("status, amount_paise, paid_at, created_at, astro_last_reply_id")
        .eq("tenant_id", ctx["tenant_id"])
        .order("created_at", desc=True)
        .limit(2000)
        .execute()
    ).data or []

    consultations = [r for r in rows if r.get("status") in ("paid", "resolved")]
    answered = sum(1 for r in consultations if r.get("astro_last_reply_id") is not None)
    # amount_paise is what Razorpay charged, so revenue_inr INCLUDES any GST collected.
    revenue_paise = sum(int(r.get("amount_paise") or 0) for r in consultations)

    today = datetime.now(timezone.utc).date()
    per_day = {(today - timedelta(days=i)).isoformat(): 0 for i in range(13, -1, -1)}
    for r in consultations:
        stamp = str(r.get("paid_at") or r.get("created_at") or "")[:10]
        if stamp in per_day:
            per_day[stamp] += 1

    revenue_inr = revenue_paise / 100
    return {
        "totals": {
            "messages": len(consultations),
            "answered": answered,
            "pending": len(consultations) - answered,
            "awaiting_payment": sum(1 for r in rows if r.get("status") == "awaiting_payment"),
            "revenue_inr": int(revenue_inr) if revenue_inr.is_integer() else revenue_inr,
        },
        "daily": [{"date": d, "count": n} for d, n in sorted(per_day.items())],
    }


class PackageChange(BaseModel):
    package_key: str


@router.patch("/sessions/{session_id}/package")
async def change_package(
    session_id: str,
    payload: PackageChange,
    ctx: dict = Depends(require_conversations_reply),
):
    updated = await change_session_package(session_id, ctx["tenant_id"], payload.package_key)
    if updated is None:
        raise HTTPException(
            status_code=400,
            detail="Session not found, already paid, or unknown package",
        )
    return updated


@public_router.post("/razorpay-webhook")
async def razorpay_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    session_id, deal_id = _payment_note_ids(payload)
    if not session_id and not deal_id:
        logger.error("Intake webhook: no session id or deal id in notes")
        return {"status": "error", "detail": "no session id"}

    # Signature is verified per-tenant: each tenant configures its own
    # razorpay_webhook_secret, so the tenant must be known before the HMAC
    # check runs (see get_session_tenant_id's docstring for why this lookup
    # is safe to do before the payload is trusted). deal_id follows the
    # exact same reasoning via deals.get_deal_tenant_id.
    tenant_id = _payment_note_tenant_id(session_id, deal_id)
    if not tenant_id:
        logger.warning(f"Intake webhook: unknown session/deal id {session_id or deal_id}")
        raise HTTPException(status_code=400, detail="Unknown session")

    if not verify_webhook_signature(raw_body, signature, tenant_id=tenant_id):
        logger.warning(f"Intake Razorpay webhook: invalid signature for tenant {tenant_id}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    return await _handle_payment_event(payload, session_id, deal_id, tenant_id)


def _payment_note_ids(payload: dict) -> tuple[str | None, str | None]:
    """(booking_id, deal_id) from the notes payment_razorpay.py wrote at link-creation time."""
    payload_data = payload.get("payload", {})
    pl_entity = payload_data.get("payment_link", {}).get("entity", {})
    # payment.failed carries no payment_link entity at all -- its notes live one
    # level down, under payload.payment.entity.notes instead. Both are the same
    # notes dict payment_razorpay.py wrote at link-creation time.
    payment_entity = payload_data.get("payment", {}).get("entity", {})
    notes = pl_entity.get("notes") or payment_entity.get("notes") or {}
    return notes.get("booking_id"), notes.get("deal_id")


def _payment_note_tenant_id(session_id: str | None, deal_id: str | None) -> str | None:
    if session_id:
        return get_session_tenant_id(session_id)
    from app.services.deals import get_deal_tenant_id
    return get_deal_tenant_id(deal_id)


@public_router.post("/razorpay-oauth-webhook")
async def razorpay_oauth_webhook(request: Request):
    """Webhook of the Razorpay OAuth partner app: one URL and one secret for every tenant that
    connected through Connect with Razorpay. Pasted-key tenants keep /razorpay-webhook.

    The signature proves Razorpay sent it, not which tenant it is for: the tenant comes from
    the payload's account_id, and the payment's own notes must point at that same tenant --
    otherwise a merchant could pay a link whose notes name another tenant's deal."""
    raw_body = await request.body()
    if not razorpay_oauth.verify_app_webhook(raw_body, request.headers.get("x-razorpay-signature", "")):
        logger.warning("Razorpay OAuth webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event", "")
    account_id = payload.get("account_id")
    db = get_supabase()
    tenant_id = razorpay_oauth.tenant_for_account(db, account_id)

    if event == "account.app.authorization_revoked":
        if tenant_id and razorpay_oauth.connected_after(db, tenant_id, payload.get("created_at")):
            return {"status": "ignored", "event": event}  # about a grant older than this connection
        if tenant_id:
            razorpay_oauth.clear_tokens(db, tenant_id)
            record_audit_event(
                db, tenant_id=tenant_id, actor_user_id=None, actor_role="system",
                action="settings.channel_disconnected", target_type="channel", target_id="razorpay",
                metadata={"source": "oauth", "reason": "revoked_in_razorpay", "account_id": account_id},
            )
        return {"status": "ok" if tenant_id else "ignored", "event": event}

    if not tenant_id:
        logger.warning(f"Razorpay OAuth webhook: no connected tenant for account {account_id} ({event})")
        return {"status": "ignored", "event": event}

    session_id, deal_id = _payment_note_ids(payload)
    if not session_id and not deal_id:
        return {"status": "ignored", "event": event}
    if _payment_note_tenant_id(session_id, deal_id) != tenant_id:
        logger.warning(
            f"Razorpay OAuth webhook: notes {session_id or deal_id} don't belong to tenant {tenant_id} ({account_id})"
        )
        raise HTTPException(status_code=400, detail="Unknown session")

    return await _handle_payment_event(payload, session_id, deal_id, tenant_id)


async def _handle_payment_event(payload: dict, session_id: str | None, deal_id: str | None, tenant_id: str):
    """Act on a verified Razorpay event whose tenant is already established."""
    event = payload.get("event", "")
    pl_entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})

    if deal_id:
        return await _handle_deal_payment_event(payload, event, deal_id, tenant_id)

    if event == "payment_link.expired":
        if _is_stale_link_event("intake_sessions", session_id, tenant_id, pl_entity.get("id")):
            return {"status": "ignored", "event": event}
        expired = expire_intake_session(session_id)
        return {"status": "ok" if expired else "ignored", "event": event}

    if event == "payment.failed":
        sent = await notify_payment_failed(session_id)
        return {"status": "ok" if sent else "ignored", "event": event}

    if event != "payment_link.paid":
        return {"status": "ignored", "event": event}

    razorpay_payment_id = (
        payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id", "")
    )
    amount_paid_paise = (
        payload.get("payload", {}).get("payment", {}).get("entity", {}).get("amount")
    )

    result = confirm_intake_payment(session_id, razorpay_payment_id, amount_paid_paise=amount_paid_paise)
    if result:
        phone = result["phone"]
        tenant_id = result["tenant_id"]
        lead_id = result["lead_id"]
        customer_name = result["customer_name"]

        # Best-effort: a bridge outage must not block the receipt or the paid
        # transition. The astro-push-reconcile job re-drives whatever fails here.
        try:
            pushed = await astro_bridge.push_consultation(result["session"], result["lead"], tenant_id)
            if pushed:
                record_astro_bridge_ids(session_id, tenant_id, pushed)
        except Exception as e:
            logger.error(f"Astro bridge consultation push failed for session {session_id}: {e}")

        service_noun = get_intake_config(tenant_id)["service_noun"]
        receipt = await compose_payment_receipt(
            lead_id=lead_id, tenant_id=tenant_id, customer_name=customer_name, service_noun=service_noun,
        )
        receipt = _with_gst_line(receipt, _fetch_session_gst(session_id, tenant_id))
        try:
            await send_whatsapp(phone, receipt, tenant_id=tenant_id)
        except Exception as e:
            logger.error(f"Intake receipt send failed for {phone}: {e}")

    return {"status": "ok"}


def _astro_unauthorized() -> JSONResponse:
    # Same body for an unknown external_ref as for a bad signature: a partner that
    # can't sign must not be able to probe which session ids exist.
    return JSONResponse(status_code=401, content={"error": "Unauthorized", "code": "unauthorized"})


@public_router.post("/astro-reply")
async def astro_reply(request: Request):
    """The astrologer's answer, called by the astrobackmatrimony Django app.
    Signed with HMAC-SHA256 over the raw body using this tenant's
    astro_bridge_secret. Wire contract — see subsystem-notes.md, AstroTamil consultation bridge."""
    raw_body = await request.body()
    signature = _signature_header(request)

    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON", "code": "invalid_json"})

    external_ref = str(payload.get("external_ref") or "")
    tenant_id = get_session_tenant_id(external_ref) if external_ref else None
    if not tenant_id:
        logger.warning(f"Astro reply callback: unknown external_ref {external_ref!r}")
        return _astro_unauthorized()

    secret = astro_bridge.get_bridge_secret(tenant_id)
    if not astro_bridge.verify_astro_signature(raw_body, signature, secret):
        # The ref resolved to a real session, so this is the expert platform
        # calling with a mismatched secret — not a probe. Nothing else surfaces
        # this: they see "sent", the customer hears nothing. Tell staff.
        logger.warning(f"Astro reply callback: invalid signature for tenant {tenant_id}")
        alert_bridge_auth_failure(tenant_id, external_ref)
        return _astro_unauthorized()

    return await deliver_astro_reply(payload, tenant_id)


SIGNATURE_HEADER = "X-Anril-Signature"
# Partners integrated under the old names; both keep working. Inbound only: this
# backend verifies the header and never sends it.
LEGACY_SIGNATURE_HEADERS = ("X-Aira-Signature", "X-Astro-Signature")
LEGACY_SIGNATURE_HEADER = "X-Astro-Signature"  # the one config/docs still list as "legacy"


def _signature_header(request: Request) -> str:
    """The HMAC header, under its current name or either older one."""
    for name in (SIGNATURE_HEADER, *LEGACY_SIGNATURE_HEADERS):
        value = request.headers.get(name.lower(), "")
        if value:
            return value
    return ""


async def _partner_request(request: Request) -> tuple[dict, str] | JSONResponse:
    """Parse and authenticate a signed partner call. Returns (payload, tenant_id),
    or the response to send back."""
    raw_body = await request.body()
    signature = _signature_header(request)

    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON", "code": "invalid_json"})

    tenant_id = payload.get("tenant_id")
    # get_setting falls back to the default tenant for an empty id, so a missing
    # tenant_id must never reach the secret lookup.
    try:
        tenant_id = str(uuid.UUID(str(tenant_id))) if tenant_id else None
    except ValueError:
        tenant_id = None
    if not tenant_id:
        return _astro_unauthorized()

    secret = await asyncio.to_thread(astro_bridge.get_bridge_secret, tenant_id)
    if not astro_bridge.verify_astro_signature(raw_body, signature, secret):
        logger.warning(f"Partner send: rejected signature for tenant {tenant_id}")
        return _astro_unauthorized()
    return payload, tenant_id


@public_router.post("/partner/send-template")
async def partner_send_template_route(request: Request):
    """The one door for apps. Send EXACTLY ONE of: template_code (an approved template by its
    Anril ID, the AstroTamil call) or event (a built-in or custom Auto Messages event key,
    optional name and extra). Both send from the tenant's WhatsApp number at once and are
    logged as source 'partner'; neither creates a lead. Wire contract — see subsystem-notes.md,
    AstroTamil consultation bridge, and services/partner_events.py for event mode."""
    parsed = await _partner_request(request)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload, tenant_id = parsed
    status, body = await partner_send_template(payload, tenant_id)
    return JSONResponse(status_code=status, content=body)


@public_router.post("/partner/send-text")
async def partner_send_text_route(request: Request):
    """Free text from the tenant's number; Meta delivers it only inside the 24h
    window. Wire contract — see subsystem-notes.md, AstroTamil consultation bridge."""
    parsed = await _partner_request(request)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload, tenant_id = parsed
    status, body = await partner_send_text(payload, tenant_id)
    return JSONResponse(status_code=status, content=body)


def _fetch_session_gst(session_id: str, tenant_id: str) -> dict:
    """GST columns of one session, tenant-scoped. confirm_intake_payment's select
    list doesn't carry them, so the receipt reads them here. Best-effort: {} on any
    failure means the receipt simply goes out without the amount line."""
    try:
        row = (
            get_supabase().table("intake_sessions")
            .select("total_amount_paise, gst_percent, gst_amount_paise")
            .eq("id", session_id).eq("tenant_id", tenant_id)
            .maybe_single().execute()
        )
        return (row.data if row else None) or {}
    except Exception as e:
        logger.warning(f"Intake receipt: GST lookup failed for session {session_id}: {e}")
        return {}


def _with_gst_line(receipt: str, gst_row: dict) -> str:
    line = gst_receipt_line(
        int(gst_row.get("total_amount_paise") or 0), gst_row.get("gst_amount_paise"), gst_row.get("gst_percent"),
    )
    return f"{receipt}\n{line}" if line else receipt


def _current_plink_id(table: str, row_id: str, tenant_id: str) -> str | None:
    """The Razorpay link id a session/deal currently points at (None for rows from before it
    was stored). Tenant-scoped; raises on a database error so the caller can fail closed."""
    row = (
        get_supabase().table(table).select("razorpay_payment_link_id")
        .eq("id", row_id).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    return ((row.data if row else None) or {}).get("razorpay_payment_link_id")


def _is_stale_link_event(table: str, row_id: str, tenant_id: str, event_plink_id: str | None) -> bool:
    """True when a cancelled/expired event is NOT about the row's current link, so it must not
    change any state: we cancel replaced links ourselves, and an old link can expire late.
    A row with no stored link id keeps the old behaviour (False). If the row can't be read the
    event is treated as stale: a lost 'expired' is harmless, a wrongly closed deal is not."""
    try:
        current = _current_plink_id(table, row_id, tenant_id)
    except Exception as e:
        logger.warning(f"Link event ignored: could not read {table} {row_id}: {e}")
        return True
    if not current or current == event_plink_id:
        return False
    logger.info(f"Ignoring event for non-current link {event_plink_id} on {table} {row_id} (current {current})")
    return True


_OPEN_DEAL_STAGES = ("quoted", "awaiting_payment")


async def _handle_deal_payment_event(payload: dict, event: str, deal_id: str, tenant_id: str) -> dict:
    """Payment events for a deal's Razorpay link (services/deals.send_payment_link
    puts notes.deal_id on it). Paid -> won (stock deducts once: mark_won's claim
    makes a retried delivery a no-op); expired -> the link is cleared and the deal stays open;
    cancelled -> lost; a failed
    attempt is ignored because the customer can still retry the same link."""
    from app.services.deals import expire_deal_link, mark_lost, mark_won

    if event in ("payment_link.expired", "payment_link.cancelled"):
        event_plink = payload.get("payload", {}).get("payment_link", {}).get("entity", {}).get("id")
        if _is_stale_link_event("deals", deal_id, tenant_id, event_plink):
            return {"status": "ignored", "event": event}
        if event == "payment_link.expired":
            # D2: a link dying is not a lost sale. Clear it, keep the deal open.
            cleared = expire_deal_link(tenant_id, deal_id)
            return {"status": "ok" if cleared else "ignored", "event": event}
        # A cancel of the CURRENT link is not ours (we only cancel links we replace or close,
        # and those no longer match the deal's current link id): staff killed it on purpose.
        # Open stages only: a deal already won (staff took cash, then cancelled the open link)
        # must never be un-won -- that would restore its stock and hide a real sale.
        lost = mark_lost(tenant_id, deal_id, "Payment link cancelled", only_from=_OPEN_DEAL_STAGES)
        return {"status": "ok" if lost else "ignored", "event": event}
    if event != "payment_link.paid":
        return {"status": "ignored", "event": event}

    razorpay_payment_id = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id", "")
    result = mark_won(tenant_id, deal_id, payment_method="razorpay", razorpay_payment_id=razorpay_payment_id)
    if not result:
        # Already won: a retry of the same payment is a no-op, but a DIFFERENT payment id is a
        # second payment (or a link paid after staff took cash) -- flag it and tell staff.
        report_extra_deal_payment(tenant_id, deal_id, razorpay_payment_id, db=get_supabase())
        return {"status": "ignored", "detail": "already won"}
    lead = (
        get_supabase().table("leads").select("phone").eq("id", result["deal"]["lead_id"])
        .eq("tenant_id", tenant_id).maybe_single().execute()
    )
    phone = (lead.data or {}).get("phone") if lead else None
    if phone:
        receipt = "Payment received, thank you! We'll be in touch shortly to arrange the next steps."
        intake_session_id = result["deal"].get("intake_session_id")
        if intake_session_id:
            receipt = _with_gst_line(receipt, _fetch_session_gst(intake_session_id, tenant_id))
        try:
            await send_whatsapp(phone, receipt, tenant_id=tenant_id)
        except Exception as e:
            logger.error(f"Deal receipt send failed for {phone}: {e}")
    return {"status": "ok"}
