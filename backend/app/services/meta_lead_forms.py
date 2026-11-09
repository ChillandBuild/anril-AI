"""Meta Instant Forms (lead ads) -> Anril.

Flow for one submission:
  Meta POSTs a `leadgen` change to the Page webhook (routes/facebook.py) carrying
  only ids. We answer 200 at once and, in the background, read the lead with the
  Page token (needs `leads_retrieval`), store every answer in meta_form_leads,
  create or merge the lead (source 'meta_form'), and send the form's chosen
  WhatsApp template -- the person has never messaged us, so only a template may go.

Safety nets:
  * meta_form_leads is unique on (tenant_id, leadgen_id), and the template is
    claimed with a pending -> sending update, so a webhook Meta retries, or the
    catch-up job finding the same lead, never sends twice.
  * catch_up() re-reads recent leads from every form, so a webhook that never
    arrived (deploy, outage) is still picked up; it only messages leads under a
    day old.
  * import_history() brings in what Meta still has from before the connection
    for the Instant forms screen only -- old leads are not added to Leads and
    are never messaged.

Tokens: the Page token (facebook_access_token) reads forms and leads. Lists of
forms need `pages_manage_ads`, the answers need `leads_retrieval`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings as env_settings
from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.services.meta_ads_insights_sync import _get_ads_credentials

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v25.0"
LEAD_FIELDS = (
    "id,created_time,field_data,form_id,ad_id,ad_name,adset_id,adset_name,"
    "campaign_id,campaign_name,is_organic,platform"
)
FORM_FIELDS = "id,name,status,locale,questions,created_time"
# A lead older than this when we first see it gets no template: the person has
# moved on, and a "thanks for your interest" days later reads as spam.
TEMPLATE_MAX_AGE = timedelta(hours=24)
# Meta keeps lead answers retrievable for 90 days.
HISTORY_DAYS = 90


class InstantFormsError(ValueError):
    """Something the client can act on; routes turn it into a 400."""


# ── Meta access ─────────────────────────────────────────────────────────────


def page_credentials(tenant_id: str) -> tuple[str, str] | None:
    """(page_id, page_token) of the tenant's connected Facebook Page, or None."""
    page_id = get_setting("facebook_page_id", tenant_id=tenant_id)
    token = get_setting("facebook_access_token", tenant_id=tenant_id)
    if not page_id or not token:
        return None
    return str(page_id), str(token)


def _graph_error(payload: dict) -> str | None:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not error:
        return None
    return str(error.get("message") or "Meta returned an error")


def _get(path: str, token: str, params: dict | None = None) -> dict:
    """GET a Graph path. Raises InstantFormsError with Meta's message on failure."""
    try:
        response = httpx.get(f"{GRAPH}/{path}", params={**(params or {}), "access_token": token}, timeout=20.0)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise InstantFormsError("Could not reach Meta. Try again in a minute.") from exc
    message = _graph_error(payload)
    if message:
        raise InstantFormsError(message)
    return payload


def _get_url(url: str) -> dict:
    """Follow a Graph `paging.next` URL (it already carries the token)."""
    try:
        payload = httpx.get(url, timeout=20.0).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise InstantFormsError("Could not reach Meta. Try again in a minute.") from exc
    message = _graph_error(payload)
    if message:
        raise InstantFormsError(message)
    return payload


def _missing_permission(message: str) -> str | None:
    """Turn Meta's permission errors into the one thing the client must do."""
    lowered = message.lower()
    if "pages_manage_ads" in lowered or "leads_retrieval" in lowered or "(#200)" in lowered or "permission" in lowered:
        return "permission"
    if "session has expired" in lowered or "access token" in lowered or "(#190)" in lowered:
        return "token"
    return None


def connection_status(tenant_id: str) -> dict:
    """What the Instant forms screen needs to know before it can show forms."""
    creds = page_credentials(tenant_id)
    if not creds:
        return {"state": "no_page", "page_id": None, "subscribed": False, "message": None}
    page_id, token = creds
    try:
        _get(f"{page_id}/leadgen_forms", token, {"fields": "id", "limit": 1})
    except InstantFormsError as exc:
        kind = _missing_permission(str(exc))
        state = "needs_permission" if kind == "permission" else "needs_reconnect" if kind == "token" else "error"
        return {"state": state, "page_id": page_id, "subscribed": False, "message": str(exc)}
    return {"state": "ready", "page_id": page_id, "subscribed": _is_subscribed(page_id, token), "message": None}


def _our_subscription(page_id: str, token: str) -> list[str] | None:
    """The fields this app is subscribed to on the Page, or None if not installed."""
    payload = _get(f"{page_id}/subscribed_apps", token)
    for app in payload.get("data") or []:
        if env_settings.meta_app_id and str(app.get("id")) != str(env_settings.meta_app_id):
            continue
        return [str(f) for f in app.get("subscribed_fields") or []]
    return None


def _is_subscribed(page_id: str, token: str) -> bool:
    try:
        fields = _our_subscription(page_id, token)
    except InstantFormsError:
        return False
    return bool(fields and "leadgen" in fields)


def subscribe_leadgen(tenant_id: str) -> None:
    """Add `leadgen` to the Page's webhook fields without dropping the Messenger
    ones (a POST replaces the list). If Meta refuses, the old list is left as is."""
    creds = page_credentials(tenant_id)
    if not creds:
        raise InstantFormsError("Connect your Facebook Page first (Settings → Connect Channels).")
    page_id, token = creds
    current = _our_subscription(page_id, token) or []
    if "leadgen" in current:
        return
    wanted = list(dict.fromkeys([*current, "leadgen"]))
    try:
        payload = httpx.post(
            f"{GRAPH}/{page_id}/subscribed_apps",
            params={"subscribed_fields": ",".join(wanted), "access_token": token},
            timeout=20.0,
        ).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise InstantFormsError("Could not reach Meta. Try again in a minute.") from exc
    message = _graph_error(payload)
    if message or not payload.get("success"):
        raise InstantFormsError(message or "Meta did not confirm the subscription.")


# ── Forms ───────────────────────────────────────────────────────────────────


def _form_row(tenant_id: str, page_id: str, form: dict) -> dict:
    return {
        "tenant_id": tenant_id,
        "page_id": page_id,
        "form_id": str(form["id"]),
        "name": form.get("name") or "",
        "status": form.get("status"),
        "locale": form.get("locale"),
        "questions": [
            {"key": q.get("key"), "label": q.get("label"), "type": q.get("type")}
            for q in form.get("questions") or []
            if isinstance(q, dict)
        ],
        "meta_created_at": form.get("created_time"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def sync_forms(tenant_id: str, db=None) -> int:
    """Copy the Page's forms into meta_lead_forms. Upsert writes only Meta's own
    columns, so each form's template choice survives a re-sync."""
    db = db or get_supabase()
    creds = page_credentials(tenant_id)
    if not creds:
        raise InstantFormsError("Connect your Facebook Page first (Settings → Connect Channels).")
    page_id, token = creds
    payload = _get(f"{page_id}/leadgen_forms", token, {"fields": FORM_FIELDS, "limit": 100})
    rows: list[dict] = []
    pages = 0
    while True:
        rows.extend(_form_row(tenant_id, page_id, form) for form in payload.get("data") or [] if form.get("id"))
        next_url = (payload.get("paging") or {}).get("next")
        pages += 1
        if not next_url or pages >= 20:
            break
        payload = _get_url(next_url)
    if rows:
        db.table("meta_lead_forms").upsert(rows, on_conflict="tenant_id,form_id").execute()
    return len(rows)


def _ensure_form(db, tenant_id: str, page_id: str, token: str, form_id: str) -> None:
    """A lead from a form created after the last sync: fetch that one form."""
    existing = (
        db.table("meta_lead_forms").select("id").eq("tenant_id", tenant_id).eq("form_id", form_id).limit(1).execute()
    ).data
    if existing:
        return
    try:
        form = _get(form_id, token, {"fields": FORM_FIELDS})
    except InstantFormsError as exc:
        logger.warning("instant forms: could not read form %s for tenant %s: %s", form_id, tenant_id, exc)
        form = {"id": form_id}
    db.table("meta_lead_forms").upsert(_form_row(tenant_id, page_id, form), on_conflict="tenant_id,form_id").execute()


# ── Answers ─────────────────────────────────────────────────────────────────


def answers_map(field_data: list | None) -> dict[str, str]:
    """{"full_name": "Priya R", "city": "Chennai", ...}; multi-choice answers joined."""
    out: dict[str, str] = {}
    for item in field_data or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        values = [str(v).strip() for v in item.get("values") or [] if str(v).strip()]
        out[str(item["name"])] = ", ".join(values)
    return out


def contact_from_answers(answers: dict[str, str]) -> dict[str, str]:
    name = answers.get("full_name") or " ".join(
        p for p in (answers.get("first_name"), answers.get("last_name")) if p
    )
    phone = answers.get("phone_number") or answers.get("phone") or answers.get("mobile_number") or ""
    email = answers.get("email") or ""
    return {"name": name.strip(), "phone": phone.strip(), "email": email.strip()}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Meta sends "2026-11-09T10:15:00+0000".
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def _lead_note(form_name: str, answers: dict[str, str], ad_name: str | None) -> str:
    lines = [f"Instant form: {form_name or 'form'}" + (f" (ad: {ad_name})" if ad_name else "")]
    lines += [f"{key.replace('_', ' ').capitalize()}: {value}" for key, value in answers.items() if value]
    return "\n".join(lines)


def _attach_to_lead(db, tenant_id: str, contact: dict, answers: dict, form_name: str, lead: dict) -> str | None:
    """Create or merge the Anril lead for a fresh submission; returns its id."""
    from app.services.inbound_lead import create_inbound_lead

    lead_id = create_inbound_lead(
        tenant_id, contact["phone"], "meta_form", name=contact["name"] or None, opt_in_source="meta_form", db=db,
    )
    if not lead_id:
        return None
    current = (
        db.table("leads").select("name,collected_data").eq("id", lead_id).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or [{}]
    collected = dict(current[0].get("collected_data") or {})
    history = list(collected.get("instant_forms") or [])
    history.append({
        "form_id": lead.get("form_id"), "form_name": form_name, "leadgen_id": lead.get("id"),
        "ad_name": lead.get("ad_name"), "submitted_at": lead.get("created_time"), "answers": answers,
    })
    collected["instant_forms"] = history[-20:]
    if contact["email"] and not collected.get("email"):
        collected["email"] = contact["email"]
    patch: dict = {"collected_data": collected}
    if contact["name"] and not current[0].get("name"):
        patch["name"] = contact["name"]
    db.table("leads").update(patch).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
    try:
        db.table("lead_notes").insert({
            "lead_id": lead_id, "tenant_id": tenant_id, "content": _lead_note(form_name, answers, lead.get("ad_name")),
            "is_pinned": False, "structured": False,
        }).execute()
    except Exception as exc:
        logger.warning("instant forms: note insert failed for lead %s: %s", lead_id, exc)
    return lead_id


def store_lead(db, tenant_id: str, page_id: str, lead: dict, *, received_via: str) -> dict | None:
    """Save one Meta lead. Returns the new meta_form_leads row, or None when it
    was already stored (Meta retry, or the catch-up found it again)."""
    from app.routes.upload import _normalize_phone

    leadgen_id = str(lead.get("id") or "")
    form_id = str(lead.get("form_id") or "")
    created = _parse_time(lead.get("created_time"))
    if not leadgen_id.isdigit() or not form_id or not created:
        logger.warning("instant forms: skipping malformed lead for tenant %s", tenant_id)
        return None

    answers = answers_map(lead.get("field_data"))
    contact = contact_from_answers(answers)
    phone = _normalize_phone(contact["phone"]) if contact["phone"] else None
    fresh = received_via != "import" and datetime.now(timezone.utc) - created <= TEMPLATE_MAX_AGE
    status = "pending" if fresh and phone else ("no_phone" if fresh else "skipped_old")

    row = {
        "tenant_id": tenant_id,
        "leadgen_id": leadgen_id,
        "page_id": page_id,
        "form_id": form_id,
        "ad_id": lead.get("ad_id"),
        "ad_name": lead.get("ad_name"),
        "adset_id": lead.get("adset_id"),
        "adset_name": lead.get("adset_name"),
        "campaign_id": lead.get("campaign_id"),
        "campaign_name": lead.get("campaign_name"),
        "platform": lead.get("platform"),
        "is_organic": bool(lead.get("is_organic")),
        "meta_created_at": created.isoformat(),
        "answers": lead.get("field_data") or [],
        "name": contact["name"] or None,
        "phone": phone or (contact["phone"] or None),
        "email": contact["email"] or None,
        "received_via": received_via,
        "template_status": status,
    }
    inserted = (
        db.table("meta_form_leads").upsert(row, on_conflict="tenant_id,leadgen_id", ignore_duplicates=True).execute()
    ).data
    if not inserted:
        return None
    stored = inserted[0]

    # Old leads (first import, or found days late) stay on the Instant forms
    # screen only: adding them to Leads would start follow-ups to people who
    # filled the form weeks ago.
    if received_via == "import" or not fresh or not phone:
        return stored
    form_rows = (
        db.table("meta_lead_forms").select("name").eq("tenant_id", tenant_id).eq("form_id", form_id).limit(1).execute()
    ).data or [{}]
    try:
        lead_id = _attach_to_lead(db, tenant_id, {**contact, "phone": phone}, answers, form_rows[0].get("name") or "", lead)
    except Exception as exc:
        logger.error("instant forms: lead create failed tenant=%s leadgen=%s: %s", tenant_id, leadgen_id, exc)
        lead_id = None
    if lead_id:
        db.table("meta_form_leads").update({"lead_id": lead_id}).eq("id", stored["id"]).execute()
        stored["lead_id"] = lead_id
    return stored


def ensure_lead(db, tenant_id: str, row_id: str) -> str | None:
    """Add a stored submission to Leads if it isn't there yet (a manual send to an
    older lead). Returns the lead id."""
    rows = (
        db.table("meta_form_leads").select("*").eq("tenant_id", tenant_id).eq("id", row_id).limit(1).execute()
    ).data
    if not rows:
        return None
    row = rows[0]
    if row.get("lead_id"):
        return row["lead_id"]
    if not row.get("phone"):
        return None
    form_rows = (
        db.table("meta_lead_forms").select("name").eq("tenant_id", tenant_id).eq("form_id", row["form_id"]).limit(1).execute()
    ).data or [{}]
    lead = {
        "id": row["leadgen_id"], "form_id": row["form_id"], "ad_name": row.get("ad_name"),
        "created_time": row.get("meta_created_at"),
    }
    contact = {"name": row.get("name") or "", "phone": row["phone"], "email": row.get("email") or ""}
    lead_id = _attach_to_lead(db, tenant_id, contact, answers_map(row.get("answers")), form_rows[0].get("name") or "", lead)
    if lead_id:
        db.table("meta_form_leads").update({"lead_id": lead_id}).eq("id", row_id).eq("tenant_id", tenant_id).execute()
    return lead_id


# ── Template ────────────────────────────────────────────────────────────────


def template_values(mapping: list | None, blanks: int, answers: dict[str, str], name: str | None) -> list[str]:
    """One value per template blank, from the form's mapping. A blank with no
    mapping, or an empty answer, still gets a value: Meta rejects empty ones."""
    first = (name or "").strip().split(" ")[0]
    values: list[str] = []
    for index in range(blanks):
        spec = mapping[index] if mapping and index < len(mapping) and isinstance(mapping[index], dict) else {}
        if spec.get("source") == "text":
            value = str(spec.get("text") or "")
        elif spec.get("source") == "field":
            field = str(spec.get("field") or "")
            value = first if field == "first_name" and first else answers.get(field, "")
        else:
            value = first if index == 0 else ""
        value = " ".join(value.split())
        values.append(value or ("there" if index == 0 else "-"))
    return values


MEDIA_HEADERS = ("IMAGE", "VIDEO", "DOCUMENT")
_TEMPLATE_COLUMNS = "id,name,language,body_text,status,meta_waba_id,header_media_type,header_media_url,header_text,buttons"


def sendable_templates(db, tenant_id: str) -> list[dict]:
    """Approved templates on the tenant's current WhatsApp number that a form can
    send: text-only, or an image / video / document header whose file is saved
    with the template (Meta needs the file again at send time)."""
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    if not waba_id:
        return []
    rows = db.table("message_templates").select(_TEMPLATE_COLUMNS).eq("tenant_id", tenant_id).execute().data or []
    out = []
    for row in rows:
        if (row.get("status") or "").upper() != "APPROVED" or row.get("meta_waba_id") != waba_id:
            continue
        media = (row.get("header_media_type") or "").upper()
        if media and media != "NONE" and (media not in MEDIA_HEADERS or not row.get("header_media_url")):
            continue
        out.append(row)
    return out


def template_blanks(template: dict) -> int:
    from app.services.call_details_share import VAR_RE

    return max((int(m) for m in VAR_RE.findall(template.get("body_text") or "")), default=0)


def build_template_components(template: dict, values: list[str], name: str | None) -> list[dict]:
    """The same header / button handling as Auto messages (its saved image, video or
    document; a {{1}} header text gets the first name; a link button's ending gets a
    dash), with the body blanks filled from this form's answers."""
    from app.services.auto_messages import build_components

    first = (name or "").strip().split(" ")[0]
    ctx = {"first_name": first, "full_name": (name or "").strip(), "page_url": "", "phone": "", "extra": {}}
    components = [
        c for c in build_components(template, {"variables": [], "button_param": None}, ctx) if c.get("type") != "body"
    ]
    if values:
        components.append({"type": "body", "parameters": [{"type": "text", "text": v[:500]} for v in values]})
    return components


def _meta_error(exc: Exception) -> str:
    """Meta's own message out of a send failure, not the raw JSON."""
    detail = getattr(exc, "detail", None) or str(exc)
    try:
        payload = json.loads(detail) if isinstance(detail, str) else {}
        error = (payload or {}).get("error") or {}
        detail = (error.get("error_data") or {}).get("details") or error.get("message") or detail
    except (ValueError, AttributeError):
        pass
    return f"WhatsApp didn't send it: {str(detail)[:300]}"


async def send_form_template(db, tenant_id: str, form_lead_id: str) -> str:
    """Send the form's template to one stored lead. Returns the final status.
    The pending -> sending claim makes a second caller a no-op."""
    from app.services.meta_cloud import send_template_message

    claimed = (
        db.table("meta_form_leads").update({"template_status": "sending"})
        .eq("id", form_lead_id).eq("tenant_id", tenant_id).eq("template_status", "pending")
        .execute()
    ).data
    if not claimed:
        return "skipped"
    row = claimed[0]

    def finish(status: str, **extra) -> str:
        db.table("meta_form_leads").update({"template_status": status, **extra}).eq("id", form_lead_id).execute()
        return status

    form = (
        db.table("meta_lead_forms").select("template_id,template_variables")
        .eq("tenant_id", tenant_id).eq("form_id", row["form_id"]).limit(1).execute()
    ).data or [{}]
    template_id = form[0].get("template_id")
    if not template_id:
        return finish("no_template")
    if not row.get("phone"):
        return finish("no_phone")
    if row.get("lead_id"):
        lead = (
            db.table("leads").select("opted_out").eq("id", row["lead_id"]).eq("tenant_id", tenant_id).limit(1).execute()
        ).data or [{}]
        if lead[0].get("opted_out"):
            return finish("failed", template_error="This person opted out of WhatsApp messages.")

    template = next((t for t in sendable_templates(db, tenant_id) if t["id"] == template_id), None)
    if not template:
        return finish("failed", template_error="The chosen template isn't approved on your WhatsApp number any more.")
    values = template_values(
        form[0].get("template_variables"), template_blanks(template), answers_map(row.get("answers")), row.get("name"),
    )
    try:
        response = await send_template_message(
            row["phone"], template["name"], template.get("language") or "en",
            components=build_template_components(template, values, row.get("name")) or None, tenant_id=tenant_id,
        )
    except Exception as exc:  # never let one send break the webhook/background job
        logger.warning("instant forms: template send failed tenant=%s row=%s: %s", tenant_id, form_lead_id, exc)
        return finish("failed", template_error=_meta_error(exc)[:500])
    message_id = ((response or {}).get("messages") or [{}])[0].get("id")

    if row.get("lead_id"):
        # Logged the way broadcasts log templates: get_conversation_leads skips a chat
        # whose only messages are "[Template: …]", so it reaches Conversations when
        # the person replies, not when the form is filled.
        content = f"[Template: {template['name']}]"
        try:
            db.table("messages").insert({
                "lead_id": row["lead_id"], "tenant_id": tenant_id, "direction": "outbound", "channel": "whatsapp",
                "content": content, "is_ai_generated": False, "meta_message_id": message_id,
            }).execute()
        except Exception as exc:
            logger.warning("instant forms: message log failed for lead %s: %s", row["lead_id"], exc)
    return finish(
        "sent", template_message_id=message_id, template_sent_at=datetime.now(timezone.utc).isoformat(),
        template_error=None,
    )


# ── Entry points ────────────────────────────────────────────────────────────


def _fetch_and_store(tenant_id: str, page_id: str, leadgen_id: str) -> dict | None:
    creds = page_credentials(tenant_id)
    if not creds or creds[0] != str(page_id):
        logger.warning("instant forms: leadgen for page %s but tenant %s has no token for it", page_id, tenant_id)
        return None
    _, token = creds
    db = get_supabase()
    lead = _get(leadgen_id, token, {"fields": LEAD_FIELDS})
    if lead.get("form_id"):
        _ensure_form(db, tenant_id, page_id, token, str(lead["form_id"]))
    return store_lead(db, tenant_id, page_id, lead, received_via="webhook")


async def process_leadgen_event(tenant_id: str, page_id: str, value: dict) -> None:
    """Background work for one webhook `leadgen` change. Never raises. The Meta
    and Supabase calls are blocking, so they run off the event loop."""
    leadgen_id = str((value or {}).get("leadgen_id") or "")
    if not leadgen_id.isdigit():
        return
    try:
        stored = await asyncio.to_thread(_fetch_and_store, tenant_id, str(page_id), leadgen_id)
        if stored and stored.get("template_status") == "pending":
            await send_form_template(get_supabase(), tenant_id, stored["id"])
    except InstantFormsError as exc:
        logger.warning("instant forms: could not read lead %s for tenant %s: %s", leadgen_id, tenant_id, exc)
    except Exception as exc:
        logger.error("instant forms: leadgen processing failed tenant=%s lead=%s: %s", tenant_id, leadgen_id, exc)


def _form_leads_since(token: str, form_id: str, since: datetime, max_pages: int = 40):
    """Yield a form's leads, newest first, until they are older than `since`."""
    payload = _get(f"{form_id}/leads", token, {"fields": LEAD_FIELDS, "limit": 100})
    pages = 0
    while True:
        for lead in payload.get("data") or []:
            created = _parse_time(lead.get("created_time"))
            if created and created < since:
                return
            lead.setdefault("form_id", form_id)
            yield lead
        next_url = (payload.get("paging") or {}).get("next")
        pages += 1
        if not next_url or pages >= max_pages:
            return
        payload = _get_url(next_url)


def _pull(tenant_id: str, since: datetime, received_via: str) -> list[str]:
    """Store every lead since `since` on every form; returns new pending row ids."""
    db = get_supabase()
    creds = page_credentials(tenant_id)
    if not creds:
        return []
    page_id, token = creds
    forms = (db.table("meta_lead_forms").select("form_id").eq("tenant_id", tenant_id).execute()).data or []
    pending: list[str] = []
    for form in forms:
        try:
            for lead in _form_leads_since(token, form["form_id"], since):
                stored = store_lead(db, tenant_id, page_id, lead, received_via=received_via)
                if stored and stored.get("template_status") == "pending":
                    pending.append(stored["id"])
        except InstantFormsError as exc:
            logger.warning("instant forms: %s pull failed tenant=%s form=%s: %s", received_via, tenant_id, form["form_id"], exc)
    return pending


def import_history(tenant_id: str) -> int:
    """First connect: everything Meta still has, for the Instant forms screen only."""
    since = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    _pull(tenant_id, since, "import")
    rows = (
        get_supabase().table("meta_form_leads").select("id", count="exact").eq("tenant_id", tenant_id).execute()
    )
    return rows.count or 0


async def catch_up(tenant_id: str) -> None:
    """Pick up any lead from the last two days whose webhook never arrived."""
    since = datetime.now(timezone.utc) - timedelta(days=2)
    pending = await asyncio.to_thread(_pull, tenant_id, since, "catch_up")
    db = get_supabase()
    for row_id in pending:
        await send_form_template(db, tenant_id, row_id)


async def catch_up_all() -> None:
    """Periodic job: every tenant that has synced at least one form."""
    rows = (get_supabase().table("meta_lead_forms").select("tenant_id").execute()).data or []
    for tenant_id in dict.fromkeys(r["tenant_id"] for r in rows if r.get("tenant_id")):
        try:
            await catch_up(tenant_id)
        except Exception as exc:
            logger.error("instant forms: catch-up failed tenant=%s: %s", tenant_id, exc)


# ── Which ads use each form ────────────────────────────────────────────────
# Read from the ad account (ads_read), not from leads, so a form shows its ad
# even before its first lead. Cached briefly: the list page reloads often.

_ADS_BY_FORM_TTL = 300
_ADS_BY_FORM_CACHE: dict[tuple[str, str], tuple[float, dict[str, list[str]]]] = {}


def _creative_form_ids(creative: dict) -> set[str]:
    """Lead form ids on an ad's creative: single-media ads keep it in
    object_story_spec, dynamic-creative ads in asset_feed_spec."""
    ids: set[str] = set()
    story = creative.get("object_story_spec") or {}
    ctas = [(story.get(k) or {}).get("call_to_action") or {} for k in ("link_data", "video_data")]
    ctas += (creative.get("asset_feed_spec") or {}).get("call_to_actions") or []
    for cta in ctas:
        form_id = (cta.get("value") or {}).get("lead_gen_form_id") if isinstance(cta, dict) else None
        if form_id:
            ids.add(str(form_id))
    return ids


def ads_by_form(db, tenant_id: str) -> dict[str, list[str]]:
    """{form_id: [ad name, ...]}, running ads first. {} when no ad account or Meta fails."""
    creds = _get_ads_credentials(db, tenant_id)
    if not creds:
        return {}
    token, account = creds
    key = (tenant_id, account)
    cached = _ADS_BY_FORM_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _ADS_BY_FORM_TTL:
        return cached[1]
    fields = ("name,effective_status,creative{object_story_spec{link_data{call_to_action},"
              "video_data{call_to_action}},asset_feed_spec{call_to_actions}}")
    ads: list[dict] = []
    try:
        page = _get(f"{account}/ads", token, {"fields": fields, "limit": 200})
        for _ in range(10):
            ads.extend(page.get("data") or [])
            next_url = (page.get("paging") or {}).get("next")
            if not next_url:
                break
            page = _get_url(next_url)
    except InstantFormsError as exc:
        logger.warning("instant forms: ad names unavailable tenant=%s: %s", tenant_id, exc)
        return {}
    ads.sort(key=lambda ad: ad.get("effective_status") != "ACTIVE")
    out: dict[str, list[str]] = {}
    for ad in ads:
        name = ad.get("name")
        for form_id in _creative_form_ids(ad.get("creative") or {}):
            if name and name not in out.setdefault(form_id, []):
                out[form_id].append(name)
    _ADS_BY_FORM_CACHE[key] = (time.monotonic(), out)
    return out
