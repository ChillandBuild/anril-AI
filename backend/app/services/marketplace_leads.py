"""IndiaMART / JustDial enquiries -> Anril leads.

A marketplace buyer usually sends the same enquiry to 5-10 sellers at once and
the first to reply tends to win, so a new enquiry must (1) land as a lead with
everything the buyer typed, (2) get the tenant's approved WhatsApp template
straight away -- the buyer has never messaged us, so the 24h window is closed
and only a template can go out -- and (3) go to the top of the call queue.

Payload shapes:
  IndiaMART CRM Push API: {"CODE":200,"STATUS":"SUCCESS","RESPONSE":{SENDER_MOBILE,
    SENDER_NAME, SENDER_EMAIL, SENDER_COMPANY, SENDER_CITY, SENDER_STATE,
    SENDER_PINCODE, QUERY_PRODUCT_NAME, QUERY_MESSAGE, UNIQUE_QUERY_ID, ...}}.
    Flat (un-nested) payloads are accepted too.
  JustDial: no public spec. Known fields: leadid, name, mobile, phone, email,
    category, city, area, company, pincode, dncmobile. Arrives as JSON, form
    fields or query params depending on how their team configures it.
"""
import logging
import re

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {"indiamart": "IndiaMART", "justdial": "JustDial"}
WELCOME_TEMPLATE_KEY = "marketplace_welcome_template"
_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_enquiry(provider: str, payload: dict) -> dict:
    """Normalise one provider payload into a flat enquiry dict. Every value is
    a string (a numeric phone from a JSON body is coerced, not a 500)."""
    if provider == "indiamart":
        body = payload.get("RESPONSE") if isinstance(payload.get("RESPONSE"), dict) else payload
        return {
            "phone": _text(body.get("SENDER_MOBILE") or body.get("mobile") or body.get("SENDER_MOBILE_ALT")),
            "name": _text(body.get("SENDER_NAME") or body.get("name")),
            "email": _text(body.get("SENDER_EMAIL") or body.get("email")),
            "company": _text(body.get("SENDER_COMPANY")),
            "city": _text(body.get("SENDER_CITY")),
            "state": _text(body.get("SENDER_STATE")),
            "pincode": _text(body.get("SENDER_PINCODE")),
            "product": _text(body.get("QUERY_PRODUCT_NAME") or body.get("QUERY_MCAT_NAME")),
            "message": _text(body.get("QUERY_MESSAGE")),
            "query_id": _text(body.get("UNIQUE_QUERY_ID")),
            "do_not_call": False,
        }
    return {
        "phone": _text(payload.get("mobile") or payload.get("phone")),
        "name": " ".join(p for p in (_text(payload.get("prefix")), _text(payload.get("name"))) if p),
        "email": _text(payload.get("email")),
        "company": _text(payload.get("company")),
        "city": _text(payload.get("city")),
        "state": "",
        "pincode": _text(payload.get("pincode")),
        "product": _text(payload.get("category")),
        "message": _text(payload.get("area")) and f"Area: {_text(payload.get('area'))}",
        "query_id": _text(payload.get("leadid")),
        # JustDial flags numbers registered on India's Do-Not-Call registry.
        "do_not_call": _text(payload.get("dncmobile")) == "1",
    }


def enquiry_note(provider: str, enquiry: dict) -> str:
    label = PROVIDER_LABELS.get(provider, provider)
    parts = [f"{label} enquiry"]
    if enquiry.get("product"):
        parts.append(f": {enquiry['product']}")
    if enquiry.get("message"):
        parts.append(f" — “{enquiry['message'][:500]}”")
    where = ", ".join(p for p in (enquiry.get("city"), enquiry.get("state")) if p)
    if where:
        parts.append(f" ({where})")
    extra = [f"{k}: {enquiry[k]}" for k in ("company", "email") if enquiry.get(k)]
    if extra:
        parts.append("\n" + " · ".join(extra))
    return "".join(parts)


def _existing_lead(db, tenant_id: str, phone: str) -> dict | None:
    from app.routes.upload import _normalize_phone
    normalized = _normalize_phone(phone)
    if not normalized:
        return None
    rows = (
        db.table("leads").select("id, segment, collected_data, deleted_at")
        .eq("tenant_id", tenant_id).eq("phone", normalized).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def _merge_enquiry(db, tenant_id: str, lead: dict, provider: str, enquiry: dict) -> None:
    collected = dict(lead.get("collected_data") or {})
    history = list(collected.get("enquiries") or [])
    history.append({"provider": provider, **{k: v for k, v in enquiry.items() if v and k != "do_not_call"}})
    collected["enquiries"] = history[-20:]
    patch: dict = {"collected_data": collected}
    if enquiry.get("do_not_call"):
        patch["do_not_call"] = True
    db.table("leads").update(patch).eq("id", lead["id"]).eq("tenant_id", tenant_id).execute()


def _add_note(db, tenant_id: str, lead_id: str, content: str) -> None:
    try:
        db.table("lead_notes").insert({
            "lead_id": lead_id, "tenant_id": tenant_id, "content": content, "is_pinned": False, "structured": False,
        }).execute()
    except Exception as e:
        logger.warning(f"marketplace: note insert failed for lead {lead_id}: {e}")


def _assign_now(lead_id: str, tenant_id: str, segment: str | None) -> None:
    """IndiaMART/JustDial enquiries follow the 'Other sources' row; its default segments include Cold so a fresh enquiry is still assigned."""
    try:
        from app.services.assignment import maybe_assign_lead
        maybe_assign_lead(lead_id, tenant_id, segment, None, reason="marketplace_enquiry")
    except Exception as e:
        logger.warning(f"marketplace: assignment failed for lead {lead_id}: {e}")


async def send_welcome_template(db, tenant_id: str, phone: str, enquiry: dict, provider: str = "indiamart") -> bool:
    """Send the tenant's chosen approved template. Variables are filled in
    order with the buyer's first name then the product, padded with neutral
    words, so any 0-2 variable template works. Media-header templates are
    skipped (they need a media parameter we don't have)."""
    from app.config_dynamic import get_setting
    from app.services.automation_guards import instant_template_allowed
    if not instant_template_allowed(tenant_id, provider):
        logger.info(f"marketplace: {provider} welcome template skipped for tenant {tenant_id}: switched off in Auto-Reply")
        return False
    template_id = get_setting(WELCOME_TEMPLATE_KEY, tenant_id=tenant_id)
    if not template_id:
        return False
    rows = (
        db.table("message_templates").select("name, language, body_text, status, header_media_type")
        .eq("id", template_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows:
        logger.warning(f"marketplace: welcome template {template_id} not found for tenant {tenant_id}")
        return False
    template = rows[0]
    if (template.get("status") or "").upper() != "APPROVED" or template.get("header_media_type"):
        logger.warning(f"marketplace: welcome template {template['name']} not sendable (status/media header)")
        return False
    var_count = len(set(_VAR_RE.findall(template.get("body_text") or "")))
    first_name = (enquiry.get("name") or "").split(" ")[0] or "there"
    values = [first_name, enquiry.get("product") or "your enquiry"] + ["—"] * max(0, var_count - 2)
    components = (
        [{"type": "body", "parameters": [{"type": "text", "text": v} for v in values[:var_count]]}] if var_count else None
    )
    try:
        from app.services.meta_cloud import send_template_message
        await send_template_message(
            phone, template["name"], template.get("language") or "en", components=components, tenant_id=tenant_id,
        )
        return True
    except Exception as e:
        logger.warning(f"marketplace: welcome template send failed for tenant {tenant_id}: {e}")
        return False


async def handle_enquiry(tenant_id: str, provider: str, enquiry: dict, db=None) -> dict:
    """Returns {"status": "ok"|"ignored", "lead_id", "is_new"}. Never lets the
    welcome message or assignment failing turn into a non-200 for the
    provider -- IndiaMART disables a push URL after repeated failures."""
    db = db or get_supabase()
    if not enquiry.get("phone"):
        return {"status": "ignored", "detail": "no phone in payload"}

    existing = _existing_lead(db, tenant_id, enquiry["phone"])
    is_new = existing is None or bool(existing.get("deleted_at"))

    from app.services.inbound_lead import create_inbound_lead
    lead_id = create_inbound_lead(
        tenant_id, enquiry["phone"], provider, name=enquiry.get("name") or None,
        opt_in_source=provider, db=db,
    )
    if not lead_id:
        return {"status": "ignored", "detail": "unusable phone"}

    lead = _existing_lead(db, tenant_id, enquiry["phone"]) or {"id": lead_id}
    _merge_enquiry(db, tenant_id, lead, provider, enquiry)
    _add_note(db, tenant_id, lead_id, enquiry_note(provider, enquiry))

    if not is_new:
        # A repeat enquiry from someone we already know: the note above makes
        # it visible on their timeline (lead_stage_events.event_type is a closed
        # list, so no new event type), and nobody is re-messaged or re-queued.
        return {"status": "ok", "lead_id": lead_id, "is_new": False}

    if not enquiry.get("do_not_call"):
        _assign_now(lead_id, tenant_id, lead.get("segment"))
    from app.routes.upload import _normalize_phone
    await send_welcome_template(db, tenant_id, _normalize_phone(enquiry["phone"]) or enquiry["phone"], enquiry, provider)
    return {"status": "ok", "lead_id": lead_id, "is_new": True}
