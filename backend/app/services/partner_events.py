"""Partner door, event mode and the partner send log.

POST /partner/send-template takes EITHER template_code (the original AstroTamil call, in
services/intake.py) OR an Auto Messages event key. Event mode uses the tenant's rule for that
event, sends at once and never creates a lead. Every partner send, in both modes, is one
auto_message_sends row with source 'partner' (migration 222); logging never blocks a send.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app.services import auto_messages as am
from app.services import private_send as private_send_svc
from app.services.intake import _astro_phone_number_id, _log_partner_message, _partner_error, _partner_reference

logger = logging.getLogger(__name__)

SOURCE = "partner"
_NAME_MAX = 200
_EXTRA_KEY_MAX = 50
_EXTRA_VALUE_MAX = 200
_REASON_MAX = 300
_TEMPLATE_COLUMNS = (
    "id, name, language, short_code, status, category, body_text, header_media_type, header_media_url, "
    "header_text, buttons"
)


def log_partner_send(
    db, tenant_id: str, *, phone: str | None, event: str | None, template_id: str | None, status: str,
    reason: str | None = None, name: str | None = None, rule_id: str | None = None, extra: dict | None = None,
) -> None:
    """One send-log row. Never raises: a broken log must not fail or hide the send itself."""
    if not phone:
        return
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "tenant_id": tenant_id, "lead_id": None, "phone": phone, "name": name or None, "event": event,
        "source": SOURCE, "rule_id": rule_id, "template_id": template_id, "extra": extra or {},
        "status": status, "reason": (reason or None) and str(reason)[:_REASON_MAX],
        "send_at": now, "sent_at": now if status == "sent" else None,
    }
    try:
        db.table("auto_message_sends").insert(row).execute()
    except Exception as e:
        logger.warning(f"Partner send log (auto_message_sends) failed for tenant {tenant_id}: {e}")


def _clean_name(value) -> tuple[str, bool]:
    if value is None:
        return "", True
    if not isinstance(value, str):
        return "", False
    return value.strip()[:_NAME_MAX], True


def _clean_extra(value) -> dict | None:
    """{key: str} with lowercased keys (the rule's variable lookup is lowercase), or None when invalid."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > am.MAX_EXTRA_KEYS:
        return None
    out: dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(val, str):
            return None
        out[key.strip().lower()[:_EXTRA_KEY_MAX]] = val.strip()[:_EXTRA_VALUE_MAX]
    return out


def _sent_text(template: dict, components: list[dict]) -> str:
    """The body as the customer saw it, for the lead's chat."""
    body = next((c for c in components if c.get("type") == "body"), None)
    values = [p.get("text", "") for p in (body or {}).get("parameters", [])]
    return am.VAR_RE.sub(
        lambda m: values[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(values) else m.group(0),
        template.get("body_text") or "",
    )


async def partner_send_event(payload: dict, tenant_id: str, db) -> tuple[int, dict]:
    from app.services.astro_normalize import normalize_phone
    from app.services.meta_cloud import send_template_message

    raw_event = payload.get("event")
    name, name_ok = _clean_name(payload.get("name"))
    extra = _clean_extra(payload.get("extra"))
    if not isinstance(raw_event, str) or not name_ok or extra is None:
        return _partner_error(
            400, "invalid_request",
            "event must be text, name must be text and extra must be an object of text values (at most "
            f"{am.MAX_EXTRA_KEYS} keys)",
        )
    phone = normalize_phone(payload.get("phone"))
    if not phone:
        return _partner_error(400, "invalid_phone", "phone is not a valid mobile number. Include the country code, e.g. 94771234567")

    if private_send_svc.has_active_key(db, tenant_id):
        return _partner_error(409, "private_send_on", "This account sends from its own server")

    event = am.resolve_event(db, tenant_id, raw_event)
    if not event:
        return _partner_error(400, "unknown_event", f"This account has no event called {raw_event.strip()[:60]}")
    rule = am.pick_rule(db, tenant_id, event)
    if not rule:
        return _partner_error(409, "no_rule", "No message is set for this event")

    reference = _partner_reference(payload)
    log_extra = {**extra, **({"reference": reference} if reference else {})}
    log = dict(event=event, name=name, rule_id=rule["id"], template_id=rule["template_id"], extra=log_extra)

    rows = (
        db.table("message_templates").select(_TEMPLATE_COLUMNS)
        .eq("id", rule["template_id"]).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    template = rows[0] if rows else {}
    status = str(template.get("status") or "")
    if status.upper() != "APPROVED":
        log_partner_send(db, tenant_id, phone=phone, status="failed", reason="template_not_approved", **log)
        return _partner_error(409, "template_not_approved", f"Template status is {status or 'unknown'}")

    ctx = {"first_name": name.split(" ")[0] if name else "", "full_name": name, "page_url": "", "phone": phone, "extra": extra}
    components = am.build_components(template, rule, ctx)
    try:
        data = await send_template_message(
            to_number=phone, template_name=template["name"], lang_code=template.get("language") or "en",
            components=components or None, tenant_id=tenant_id, phone_number_id=_astro_phone_number_id(tenant_id, db, phone),
        )
    except HTTPException as e:
        logger.error(f"Partner event {event} ({reference}) for tenant {tenant_id} rejected by Meta: {e.detail}")
        log_partner_send(db, tenant_id, phone=phone, status="failed", reason=str(e.detail), **log)
        return _partner_error(502, "meta_error", str(e.detail))
    except Exception as e:
        logger.error(f"Partner event {event} ({reference}) for tenant {tenant_id} failed: {e}")
        log_partner_send(db, tenant_id, phone=phone, status="failed", reason=str(e), **log)
        return _partner_error(502, "meta_error", str(e))
    mid = ((data or {}).get("messages") or [{}])[0].get("id")
    if not mid:
        log_partner_send(db, tenant_id, phone=phone, status="failed", reason="no message id", **log)
        return _partner_error(502, "meta_error", "no message id")

    log_partner_send(db, tenant_id, phone=phone, status="sent", **log)
    _log_partner_message(db, tenant_id, phone, _sent_text(template, components), mid)
    logger.info(f"Partner event {event} ({reference}) sent for tenant {tenant_id}: {mid}")
    return 200, {
        "ok": True, "message_id": mid, "event": event,
        "template": {"code": template.get("short_code"), "name": template["name"], "language": template.get("language") or "en"},
    }
