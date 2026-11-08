import logging
import json
import re
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, field_validator
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services import meta_cloud
from app.services.meta_cloud import (
    submit_template,
    get_template_status,
    list_all_templates,
    delete_template_from_meta,
    update_template_on_meta,
    upload_media_for_template,
    TemplateContentExistsError,
    _build_button_components,
    _strip_emojis,
    build_core_components,
)
from app.services import template_fields, template_media, template_rules
from app.config import settings as env_settings
from app.config_dynamic import get_setting
from app.services.meta_webhook_verify import verify_meta_signature
from app.services.template_edit_limits import (
    blocked_message,
    edit_allowance,
    is_echo_of_anril_edit,
    load_edits,
    record_edit,
)

logger = logging.getLogger(__name__)
require_templates_read = require_permission("templates.view")
require_templates_manage = require_permission("templates.manage")

router = APIRouter(dependencies=[Depends(require_templates_read)])
public_router = APIRouter()  # No auth — Meta calls these endpoints directly


class Button(BaseModel):
    type: str  # QUICK_REPLY | URL | PHONE_NUMBER | WHATSAPP_CALL | COPY_CODE | ONE_TAP
    text: str
    url: str | None = None
    phone: str | None = None
    country: str | None = None
    offer_code: str | None = None
    active_for_days: int | None = None
    autofill_text: str | None = None
    package_name: str | None = None
    signature_hash: str | None = None
    url_example: str | None = None  # sample for a {{1}} at the end of a URL button's link


class CarouselCard(BaseModel):
    header_media_type: str = "IMAGE"  # IMAGE | VIDEO
    header_media_url: str
    body_text: str
    buttons: list[Button] | None = None  # 1-2 per card
    body_examples: list[str] | None = None


_SUPPORTED_TEMPLATE_LANGUAGES = {"en", "en_US", "en_IN", "hi", "kn", "ml", "ta", "te"}


def _belongs_to_current_waba(template: dict, current_waba_id: str | None) -> bool:
    """Remote templates are account-scoped; local drafts without Meta ids stay visible."""
    if not current_waba_id:
        return True
    row_waba_id = template.get("meta_waba_id")
    if row_waba_id == current_waba_id:
        return True
    status = (template.get("status") or "PENDING").upper()
    return not row_waba_id and not template.get("meta_template_id") and status not in {"APPROVED", "PAUSED"}


def _meta_error_text(detail) -> str:
    """Meta's own words from a Graph error body (error_user_msg, else message)."""
    try:
        err = json.loads(detail).get("error", {}) if isinstance(detail, str) else {}
    except (ValueError, AttributeError):
        err = {}
    return err.get("error_user_msg") or err.get("message") or str(detail)[:300]


def stored_template_status(meta_status) -> str:
    """Meta's template status (sync or webhook) -> what Anril stores. Anything
    Meta reports that isn't a known state counts as not approved (PENDING), so
    it's never sent; logged so a new Meta value gets noticed."""
    raw = str(meta_status or "PENDING").upper()
    mapped = _META_TEMPLATE_EVENT_STATUS.get(raw)
    if mapped is None:
        logger.warning(f"Unrecognised Meta template status {raw!r}; treating it as not approved")
        return "PENDING"
    return mapped


def _clean_rejection_reason(reason) -> str | None:
    """Meta sends the literal string 'NONE' when a template was never rejected."""
    if not reason:
        return None
    text = str(reason).strip()
    return None if text.upper() in ("NONE", "NULL") else text


def _filter_templates_for_waba(templates: list[dict], current_waba_id: str | None) -> list[dict]:
    """Visibility fails closed: no WhatsApp connection means nothing to show.

    Templates belong to a WABA, so a disconnected tenant's rows describe an account
    they no longer hold. They are hidden, not deleted — reconnecting the same WABA
    brings them straight back, keeping local-only data (variations) that Meta cannot
    restore. Note this is deliberately stricter than _belongs_to_current_waba, which
    answers ownership rather than visibility and must keep matching rows without a
    configured WABA so duplicate-name detection still works.
    """
    if not current_waba_id:
        return []
    return [t for t in templates if _belongs_to_current_waba(t, current_waba_id)]


def _validate_body_variables(body_text: str) -> str:
    """Meta's body rules (template_rules.body_problems), raised as one message."""
    problems = template_rules.body_problems(body_text)
    if problems:
        raise ValueError(" ".join(problems))
    return body_text


def _check_against_meta_rules(
    *,
    body_text: str,
    body_examples: list[str] | None,
    header_text: str | None,
    header_example: str | None,
    header_media_type: str | None,
    footer_text: str | None,
    buttons: list[dict] | None,
    carousel_cards: list[dict] | None = None,
) -> None:
    """Refuse, with a clear 400, anything Meta would reject, before it is sent.

    Sample values are checked here too: a missing sample used to be replaced by an
    invented one ("Sample text"), a common reason for Meta to reject a template.
    """
    problems: list[str] = []
    if not (header_media_type and header_media_type != "NONE"):
        problems += template_rules.header_problems(header_text)
    problems += template_rules.footer_problems(footer_text)
    try:
        build_core_components(
            body_text, body_examples, header_text, header_example,
            header_media_type, None, footer_text,
        )
    except ValueError as e:
        problems.append(str(e))
    all_buttons = list(buttons or [])
    for card in carousel_cards or []:
        problems += template_rules.body_problems(card.get("body_text") or "")
        try:
            template_rules.samples_for(card.get("body_text"), card.get("body_examples"), "card text")
        except ValueError as e:
            problems.append(str(e))
        all_buttons += card.get("buttons") or []
    for btn in all_buttons:
        if btn.get("type") == "URL":
            problems += template_rules.url_problems(btn.get("url"))
            try:
                template_rules.url_with_sample((btn.get("url") or "").strip(), btn.get("url_example"))
            except ValueError as e:
                problems.append(str(e))
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(dict.fromkeys(problems)))


class CreateTemplate(BaseModel):
    name: str
    category: str
    language: str = "en"
    body_text: str
    header_text: str | None = None
    header_media_type: str | None = None  # IMAGE | VIDEO | DOCUMENT | LOCATION
    header_media_url: str | None = None
    footer_text: str | None = None
    buttons: list[Button] | None = None
    carousel_cards: list[CarouselCard] | None = None
    body_examples: list[str] | None = None
    header_example: str | None = None

    @field_validator("language")
    @classmethod
    def _validate_language(cls, v: str) -> str:
        if v not in _SUPPORTED_TEMPLATE_LANGUAGES:
            raise ValueError(f"Unsupported language '{v}'. Supported: {sorted(_SUPPORTED_TEMPLATE_LANGUAGES)}")
        return v

    @field_validator("body_text")
    @classmethod
    def _validate_body_text(cls, v: str) -> str:
        return _validate_body_variables(v)


@router.get("/")
async def list_templates(tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    result = db.table("message_templates").select("*").eq("tenant_id", tenant_id).order("submitted_at", desc=True).execute()
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    rows = _filter_templates_for_waba(result.data or [], waba_id)
    # Meta's edit limit for approved templates (1 per 24h, 10 per 30 days), so
    # the page can block Edit before Meta refuses it.
    approved_ids = [r["id"] for r in rows if (r.get("status") or "").upper() == "APPROVED"]
    try:
        edits = load_edits(db, tenant_id, approved_ids)
    except Exception as e:
        logger.warning(f"template edit log unavailable for tenant {tenant_id}: {e}")
        edits = {}
    for r in rows:
        if r["id"] in approved_ids:
            r["edit_allowance"] = edit_allowance(edits.get(r["id"], []))
    return {"data": rows}


@router.post("/")
async def create_template(
    payload: CreateTemplate,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    name = payload.name.strip().lower().replace(" ", "_")
    category = payload.category.upper()
    if category not in ("MARKETING", "UTILITY", "AUTHENTICATION"):
        raise HTTPException(status_code=400, detail="Invalid category")

    # Validate header text emoji presence
    if payload.header_text and _strip_emojis(payload.header_text) != payload.header_text:
        raise HTTPException(status_code=400, detail="Emojis are not allowed in the header text.")

    # Validate duplicate button texts
    if payload.buttons:
        btn_texts = [b.text.strip().lower() for b in payload.buttons if b.text]
        if len(btn_texts) != len(set(btn_texts)):
            raise HTTPException(status_code=400, detail="You can't enter the same text for multiple buttons.")

    buttons_dict = [b.model_dump() for b in payload.buttons] if payload.buttons else None
    carousel_dict = None
    if payload.carousel_cards:
        carousel_dict = []
        for c in payload.carousel_cards:
            raw = c.model_dump()
            if c.buttons:
                raw["buttons"] = [b.model_dump() for b in c.buttons]
            carousel_dict.append(raw)
    _check_against_meta_rules(
        body_text=payload.body_text,
        body_examples=payload.body_examples,
        header_text=payload.header_text,
        header_example=payload.header_example,
        header_media_type=payload.header_media_type,
        footer_text=payload.footer_text,
        buttons=buttons_dict,
        carousel_cards=carousel_dict,
    )

    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    if not waba_id:
        # Saving locally would strand the template: it never reaches Meta, and the
        # templates list hides rows for a tenant with no WABA connected.
        raise HTTPException(status_code=400, detail="Connect Meta WhatsApp (meta_waba_id) in Settings first")

    db = get_supabase()
    existing = db.table("message_templates").select("id,meta_template_id,meta_waba_id").eq("name", name).eq("tenant_id", tenant_id).execute()
    existing_rows = existing.data or []
    if any(_belongs_to_current_waba(row, waba_id) for row in existing_rows):
        raise HTTPException(status_code=409, detail=f"Template '{name}' already exists")
    stale_existing_id = existing_rows[0]["id"] if existing_rows else None

    # Meta rejects a template whose body and footer match an existing one
    # (authentication templates excepted).
    if category != "AUTHENTICATION":
        same_body = (
            db.table("message_templates")
            .select("name,footer_text,meta_template_id,meta_waba_id,status")
            .eq("tenant_id", tenant_id)
            .eq("body_text", payload.body_text)
            .execute()
        )
        for row in same_body.data or []:
            if row.get("name") == name or not _belongs_to_current_waba(row, waba_id):
                continue
            if (row.get("footer_text") or "").strip() == (payload.footer_text or "").strip():
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Template '{row.get('name')}' already has this exact message and footer. "
                        "Meta rejects duplicates, so change the wording."
                    ),
                )

    meta_template_id = None
    status = "PENDING"
    # Sent to Meta first. If it doesn't get there -- Meta refuses it or can't be
    # reached -- nothing is saved: a template Meta never saw used to be stored as
    # REJECTED (no reason, no Meta id) and an edit could never send it.
    try:
        meta_response = await submit_template(
            waba_id=waba_id,
            name=name,
            category=category,
            language=payload.language,
            body_text=payload.body_text,
            header_text=payload.header_text,
            header_media_type=payload.header_media_type,
            header_media_url=payload.header_media_url,
            footer_text=payload.footer_text,
            buttons=buttons_dict,
            carousel_cards=carousel_dict,
            tenant_id=tenant_id,
            body_examples=payload.body_examples,
            header_example=payload.header_example,
        )
        meta_template_id = str(meta_response.get("id", ""))
    except TemplateContentExistsError:
        raise
    except HTTPException as e:
        logger.warning(f"Meta refused template {name}: {e.detail}")
        raise HTTPException(status_code=400, detail=f"Meta didn't accept the template: {_meta_error_text(e.detail)}")
    except Exception as e:
        logger.warning(f"Couldn't reach Meta to submit template {name}: {e}")
        raise HTTPException(status_code=502, detail="Couldn't reach Meta, so the template wasn't sent. Please try again.")
    if not meta_template_id:
        raise HTTPException(status_code=502, detail="Meta didn't confirm the template, so it wasn't saved. Please try again.")

    db_insert = {
        "name": name,
        "category": category,
        "language": payload.language,
        "body_text": payload.body_text,
        "header_media_type": payload.header_media_type,
        # Meta got the upload handle; sends need a link Meta can fetch.
        "header_media_url": template_media.link_for(db, tenant_id, payload.header_media_url),
        "buttons": [b.model_dump() for b in payload.buttons] if payload.buttons else None,
        "carousel_cards": (
            [
                {**c.model_dump(), "buttons": [b.model_dump() for b in c.buttons] if c.buttons else None}
                for c in payload.carousel_cards
            ]
            if payload.carousel_cards
            else None
        ),
        "status": status,
        "meta_template_id": meta_template_id,
        "meta_waba_id": waba_id,
        "tenant_id": tenant_id,
        # A reused stale row still carries the previous submission's lifecycle —
        # reset it so the dates describe *this* submission.
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "approved_at": None,
        "rejection_reason": None,
    }
    if payload.header_text:
        db_insert["header_text"] = payload.header_text
    if payload.footer_text:
        db_insert["footer_text"] = payload.footer_text

    if stale_existing_id:
        result = db.table("message_templates").update(db_insert).eq("id", stale_existing_id).eq("tenant_id", tenant_id).execute()
    else:
        result = db.table("message_templates").insert(db_insert).execute()

    return result.data[0]


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    db = get_supabase()
    row = db.table("message_templates").select("name,meta_template_id,meta_waba_id").eq("id", template_id).eq("tenant_id", tenant_id).limit(1).execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Template not found")

    template_name = row.data[0].get("name", "")
    meta_template_id = row.data[0].get("meta_template_id")

    # Delete on Meta first. If Meta refuses, keep our copy so the client can see
    # the template is still live on WhatsApp and try again later.
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    if meta_template_id and waba_id and template_name:
        try:
            await delete_template_from_meta(
                template_name=template_name,
                waba_id=waba_id,
                tenant_id=tenant_id,
                hsm_id=meta_template_id,
            )
        except Exception as e:
            detail = str(getattr(e, "detail", e))
            if not _meta_says_template_missing(detail):
                logger.warning(f"Meta template delete failed for '{template_name}': {detail}")
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Couldn't delete this template on WhatsApp, so it was kept here. "
                        "Please try again in a few minutes."
                    ),
                )

    db.table("message_templates").delete().eq("id", template_id).eq("tenant_id", tenant_id).execute()
    return {"deleted": True}


def _meta_says_template_missing(detail: str) -> bool:
    """Meta has no such template any more (deleted in WhatsApp Manager): safe to drop ours."""
    text = detail.lower()
    return "not found" in text or "does not exist" in text


@router.post("/{template_id}/sync")
async def sync_template_status(
    template_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    """Pull current status from Meta API and update the local record."""
    db = get_supabase()
    row = db.table("message_templates").select("name,meta_template_id,meta_waba_id,approved_at").eq("id", template_id).eq("tenant_id", tenant_id).limit(1).execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Template not found")

    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    if not waba_id:
        raise HTTPException(status_code=400, detail="meta_waba_id not configured in Settings")
    if not _belongs_to_current_waba(row.data[0], waba_id):
        raise HTTPException(status_code=404, detail="Template not found for current WABA")

    meta_info = await get_template_status(waba_id=waba_id, template_name=row.data[0]["name"], tenant_id=tenant_id)
    if not meta_info:
        raise HTTPException(status_code=502, detail="Template not found on Meta — check WABA ID and access token in Settings")

    new_status = stored_template_status(meta_info.get("status"))
    updates: dict = {"status": new_status, "meta_waba_id": waba_id}
    if meta_info.get("id"):
        updates["meta_template_id"] = str(meta_info["id"])
    if new_status == "APPROVED":
        # Only stamp the first approval — re-syncing must not move the date to today.
        if not row.data[0].get("approved_at"):
            updates["approved_at"] = datetime.now(timezone.utc).isoformat()
    else:
        updates["approved_at"] = None
    updates["rejection_reason"] = _clean_rejection_reason(meta_info.get("rejected_reason"))

    db.table("message_templates").update(updates).eq("id", template_id).eq("tenant_id", tenant_id).execute()
    updated = db.table("message_templates").select("*").eq("id", template_id).eq("tenant_id", tenant_id).limit(1).execute()
    return updated.data[0] if updated.data else None


@router.post("/sync-from-meta")
async def sync_templates_from_meta(
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    """Pull all templates from Meta and upsert into local DB. Returns added/updated counts."""
    waba_id = get_setting("meta_waba_id", tenant_id=tenant_id)
    if not waba_id:
        raise HTTPException(status_code=400, detail="meta_waba_id not configured in Settings")

    meta_templates = await list_all_templates(waba_id=waba_id, tenant_id=tenant_id)
    if not meta_templates:
        return {"added": 0, "updated": 0, "total": 0}

    db = get_supabase()
    existing_rows = db.table("message_templates").select("*").eq("tenant_id", tenant_id).execute()
    existing_by_name = {r["name"]: r for r in (existing_rows.data or [])}

    added = 0
    updated = 0

    for t in meta_templates:
        name = t.get("name", "")
        status = stored_template_status(t.get("status"))
        category = (t.get("category") or "MARKETING").upper()
        language = t.get("language", "en")
        rejection_reason = _clean_rejection_reason(t.get("rejected_reason"))
        meta_id = str(t.get("id", "")) if t.get("id") else None

        # Parse the full components array from Meta
        body_text = ""
        header_text = None
        header_media_type = None
        header_media_url = None
        footer_text = None
        buttons = None
        for comp in (t.get("components") or []):
            comp_type = comp.get("type", "").upper()
            if comp_type == "BODY":
                body_text = comp.get("text", "")
            elif comp_type == "HEADER":
                fmt = (comp.get("format") or "").upper()
                if fmt == "TEXT":
                    header_text = comp.get("text", "")
                elif fmt in ("IMAGE", "VIDEO", "DOCUMENT", "LOCATION"):
                    header_media_type = fmt
                    # Extract example URL if present
                    example = comp.get("example", {})
                    header_handle = example.get("header_handle", [])
                    if header_handle:
                        header_media_url = header_handle[0] if isinstance(header_handle, list) else header_handle
            elif comp_type == "FOOTER":
                footer_text = comp.get("text", "")
            elif comp_type == "BUTTONS":
                buttons = comp.get("buttons", [])

        if header_media_url and header_media_type in template_media.MEDIA_TYPES:
            # Meta's example link expires; sends need a permanent one. If the copy
            # fails (e.g. the link already expired), keep the copy we already have.
            previous = (existing_by_name.get(name) or {}).get("header_media_url")
            ours = await template_media.copy_from_meta(db, tenant_id, name, header_media_url)
            if ours:
                header_media_url = ours
            elif template_media.is_ours(previous):
                header_media_url = previous

        if name in existing_by_name:
            # Sync is authoritative for the active WABA. If this row came from a
            # previous Meta account, overwrite the account-bound fields too.
            current = existing_by_name[name]
            updates: dict = {
                "status": status,
                "category": category,
                "language": language,
                "body_text": body_text,
                "meta_template_id": meta_id,
                "meta_waba_id": waba_id,
                "rejection_reason": rejection_reason,
                "header_text": header_text,
                "header_media_type": header_media_type,
                "header_media_url": header_media_url,
                "footer_text": footer_text,
                "buttons": buttons,
            }
            if status == "APPROVED":
                if not current.get("approved_at"):
                    updates["approved_at"] = datetime.now(timezone.utc).isoformat()
            elif current.get("approved_at"):
                updates["approved_at"] = None

            changed = any(current.get(k) != v for k, v in updates.items())
            if changed:
                db.table("message_templates").update(updates).eq("name", name).eq("tenant_id", tenant_id).execute()
                updated += 1
        else:
            # Insert new template with full component data
            insert_row: dict = {
                "name": name,
                "category": category,
                "language": language,
                "body_text": body_text,
                "status": status,
                "meta_template_id": meta_id,
                "meta_waba_id": waba_id,
                "rejection_reason": rejection_reason,
                "approved_at": datetime.now(timezone.utc).isoformat() if status == "APPROVED" else None,
                "tenant_id": tenant_id,
            }
            if header_text:
                insert_row["header_text"] = header_text
            if header_media_type:
                insert_row["header_media_type"] = header_media_type
            if header_media_url:
                insert_row["header_media_url"] = header_media_url
            if footer_text:
                insert_row["footer_text"] = footer_text
            if buttons:
                insert_row["buttons"] = buttons
            db.table("message_templates").insert(insert_row).execute()
            added += 1

    return {"added": added, "updated": updated, "total": len(meta_templates)}


TEMPLATE_WEBHOOK_FIELDS = ("message_template_status_update", "message_template_components_update")

# Meta's message_template_status_update events -> the status Anril stores.
# Only APPROVED is sent anywhere.
_META_TEMPLATE_EVENT_STATUS = {
    "APPROVED": "APPROVED",
    "REINSTATED": "APPROVED",
    "PENDING": "PENDING",
    "IN_APPEAL": "PENDING",
    "REJECTED": "REJECTED",
    "PAUSED": "PAUSED",
    "DISABLED": "DISABLED",
    "ARCHIVED": "ARCHIVED",
    "DELETED": "DELETED",
    "PENDING_DELETION": "DELETED",
}

# The button types message_template_components_update reports; any other
# buttons (quick replies, copy code, ...) aren't in it and are kept as they are.
_REPORTED_BUTTON_TYPES = {"URL": "url", "PHONE_NUMBER": "phone_number"}


def tenant_for_template_payload(db, payload: dict) -> str | None:
    """The tenant owning the first template a template webhook mentions."""
    for e in payload.get("entry", []):
        for change in e.get("changes", []):
            if change.get("field") not in TEMPLATE_WEBHOOK_FIELDS:
                continue
            meta_id = str((change.get("value") or {}).get("message_template_id") or "")
            if meta_id:
                row = db.table("message_templates").select("tenant_id").eq("meta_template_id", meta_id).limit(1).execute()
                if row.data:
                    return row.data[0]["tenant_id"]
    return None


def _merge_reported_buttons(existing: list | None, reported: list | None) -> list:
    kept = [b for b in (existing or []) if (b or {}).get("type") not in _REPORTED_BUTTON_TYPES]
    fresh = []
    for b in reported or []:
        kind = str(b.get("message_template_button_type") or "").upper()
        if kind not in _REPORTED_BUTTON_TYPES:
            continue
        btn = {"type": kind, "text": b.get("message_template_button_text") or ""}
        if kind == "URL":
            btn["url"] = b.get("message_template_button_url")
        else:
            btn["phone"] = b.get("message_template_button_phone_number")
        fresh.append(btn)
    return kept + fresh


def apply_template_change(db, field: str, value: dict, tenant_id: str | None = None) -> None:
    """One template webhook change -> message_templates. tenant_id scopes the
    write to that tenant's rows (the WhatsApp webhook); None updates every row
    mirroring that Meta template (the legacy /templates/webhook-status door)."""
    meta_id = str(value.get("message_template_id") or "")
    if not meta_id:
        return

    def _rows(q):
        q = q.eq("meta_template_id", meta_id)
        return q.eq("tenant_id", tenant_id) if tenant_id else q

    if field == "message_template_status_update":
        new_status = _META_TEMPLATE_EVENT_STATUS.get(str(value.get("event") or "").upper())
        if not new_status:
            # FLAGGED / LOCKED / LIMIT_EXCEEDED don't change whether it can be
            # sent; UNARCHIVED restores an earlier status Meta doesn't name here
            # (the next template sync picks it up).
            return
        updates: dict = {"status": new_status, "rejection_reason": _clean_rejection_reason(value.get("reason"))}
        if new_status == "APPROVED":
            updates["approved_at"] = datetime.now(timezone.utc).isoformat()
        _rows(db.table("message_templates").update(updates)).execute()
        logger.info(f"Template {meta_id} status -> {new_status}")

    elif field == "message_template_components_update":
        # Someone edited the template (e.g. in WhatsApp Manager). Keep Anril's
        # copy identical to Meta's: the broadcast screen counts {{n}} variables
        # from body_text, and a stale count makes Meta reject every send.
        existing = _rows(db.table("message_templates").select("id,tenant_id,header_media_type,buttons,approved_at")).limit(1).execute().data or []
        if not existing:
            return
        row = existing[0]
        # An edit made in WhatsApp Manager counts toward Meta's limit too; Meta
        # also reports Anril's own edits here, which are logged already.
        if row.get("approved_at") and not is_echo_of_anril_edit(db, row["id"]):
            try:
                record_edit(db, row["tenant_id"], row["id"], "meta_webhook")
            except Exception as e:
                logger.warning(f"template edit log write failed for {row['id']}: {e}")
        updates = {"body_text": value.get("message_template_element") or ""}
        # Meta only sends a title for a text header and a footer when there is one.
        if not row.get("header_media_type"):
            updates["header_text"] = value.get("message_template_title")
        updates["footer_text"] = value.get("message_template_footer")
        updates["buttons"] = _merge_reported_buttons(row.get("buttons"), value.get("message_template_buttons"))
        _rows(db.table("message_templates").update(updates)).execute()
        logger.info(f"Template {meta_id} components updated from Meta")


@public_router.post("/webhook-status")
async def template_status_webhook(request: Request):
    """Meta template webhooks (status changes and edits). No auth -- signed."""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except Exception as e:
        logger.warning(f"Template status webhook: invalid JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    signature = request.headers.get("X-Hub-Signature-256")

    has_template_id = any(
        (c.get("value") or {}).get("message_template_id")
        for e in payload.get("entry", []) for c in e.get("changes", [])
        if c.get("field") in TEMPLATE_WEBHOOK_FIELDS
    )
    if not has_template_id:
        logger.warning("Template status webhook: message_template_id not found in payload")
        return {"status": "ok"}

    db = get_supabase()
    tenant_id = tenant_for_template_payload(db, payload)
    if not tenant_id:
        logger.warning("Template status webhook: tenant not found for the payload's template")
        raise HTTPException(status_code=404, detail="Template not found")

    if not signature:
        logger.warning("Template status webhook: missing signature header")
        raise HTTPException(status_code=403, detail="Missing signature")

    if not verify_meta_signature(raw_body, signature, tenant_id):
        logger.warning(f"Template status webhook: invalid signature for tenant {tenant_id}")
        raise HTTPException(status_code=403, detail="Invalid signature")

    for e in payload.get("entry", []):
        for change in e.get("changes", []):
            if change.get("field") in TEMPLATE_WEBHOOK_FIELDS:
                apply_template_change(db, change["field"], change.get("value") or {})
    return {"status": "ok"}


class VariationsPayload(BaseModel):
    variations: list[str]


@router.get("/{template_id}/variations")
async def get_template_variations(template_id: str, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    row = db.table("message_templates").select("id,name,variations").eq("id", template_id).eq("tenant_id", tenant_id).execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"id": template_id, "variations": row.data[0].get("variations") or []}


@router.put("/{template_id}/variations")
async def update_template_variations(
    template_id: str,
    payload: VariationsPayload,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    db = get_supabase()
    result = db.table("message_templates").update({"variations": payload.variations}).eq("id", template_id).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"id": template_id, "variations": payload.variations}


class VariableMapPayload(BaseModel):
    # {"1": "lead_phone", "2": "collected:course"}; empty clears it (back to the alert's fixed order).
    variable_map: dict[str, str]


@router.put("/{template_id}/variable-map")
async def update_template_variable_map(
    template_id: str,
    payload: VariableMapPayload,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    """Save which field fills each {{n}} when the WhatsApp alerts send this template.
    Anril-only: nothing goes to Meta, so any status can be changed."""
    db = get_supabase()
    row = (
        db.table("message_templates").select("id,body_text")
        .eq("id", template_id).eq("tenant_id", tenant_id).limit(1).execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="Template not found")
    count = template_fields.placeholder_count(row.data[0].get("body_text"))
    clean: dict[str, str] = {}
    for slot, field in payload.variable_map.items():
        if not slot.isdigit() or not 1 <= int(slot) <= count:
            raise HTTPException(status_code=400, detail=f"This template has no {{{{{slot}}}}}.")
        field = field.strip()
        if not template_fields.is_valid_field(field):
            raise HTTPException(status_code=400, detail=f"Unknown field for {{{{{slot}}}}}: {field or 'empty'}")
        clean[str(int(slot))] = field
    db.table("message_templates").update({"variable_map": clean or None}).eq("id", template_id).eq("tenant_id", tenant_id).execute()
    return {"id": template_id, "variable_map": clean}


class UpdateTemplate(BaseModel):
    body_text: Optional[str] = None
    header_text: Optional[str] = None
    header_media_type: Optional[str] = None
    header_media_url: Optional[str] = None
    footer_text: Optional[str] = None
    buttons: Optional[list[Button]] = None
    body_examples: Optional[list[str]] = None
    header_example: Optional[str] = None

    @field_validator("body_text")
    @classmethod
    def _validate_body_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_body_variables(v)


@router.patch("/{template_id}")
async def update_template(
    template_id: str,
    payload: UpdateTemplate,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    """Edit an APPROVED, REJECTED or PAUSED template -- the statuses Meta allows.
    Meta caps approved-template edits (1 per 24 hours, 10 per 30 days) and
    re-reviews them; rejected/paused ones can be edited any number of times.
    Pushed to Meta first: if Meta refuses, nothing changes locally, so Anril's
    copy never drifts from Meta's."""
    db = get_supabase()
    row = db.table("message_templates").select("*").eq("id", template_id).eq("tenant_id", tenant_id).limit(1).execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Template not found")

    template = row.data[0]
    # A template Meta never received (no meta_template_id) isn't bound by Meta's
    # edit rules: saving submits it to Meta for the first time.
    never_reached_meta = not template.get("meta_template_id")
    if not never_reached_meta and template.get("status") not in ("APPROVED", "REJECTED", "PAUSED"):
        raise HTTPException(
            status_code=400,
            detail=f"Meta only allows editing Approved, Rejected or Paused templates. This one is {template.get('status')}.",
        )

    was_approved = (template.get("status") or "").upper() == "APPROVED" and not never_reached_meta
    if was_approved:
        allowance = edit_allowance(load_edits(db, tenant_id, [template_id]).get(template_id, []))
        if not allowance["allowed"]:
            raise HTTPException(status_code=400, detail=blocked_message(allowance))

    if payload.header_text is not None and _strip_emojis(payload.header_text) != payload.header_text:
        raise HTTPException(status_code=400, detail="Emojis are not allowed in the header text.")

    if payload.buttons is not None:
        btn_texts = [b.text.strip().lower() for b in payload.buttons if b.text]
        if len(btn_texts) != len(set(btn_texts)):
            raise HTTPException(status_code=400, detail="You can't enter the same text for multiple buttons.")

    # Build DB updates from payload. An edit is a fresh submission to Meta, so the
    # lifecycle restarts: new submitted_at, no approval, no stale rejection reason.
    updates: dict = {
        "status": "PENDING",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "approved_at": None,
        "rejection_reason": None,
    }
    if payload.body_text is not None:
        updates["body_text"] = payload.body_text
    if payload.header_text is not None:
        updates["header_text"] = payload.header_text
    if payload.header_media_type is not None:
        updates["header_media_type"] = payload.header_media_type
    if payload.header_media_url is not None:
        updates["header_media_url"] = payload.header_media_url
    if payload.footer_text is not None:
        updates["footer_text"] = payload.footer_text
    if payload.buttons is not None:
        updates["buttons"] = [b.model_dump() for b in payload.buttons]

    # Meta's template API wants an upload handle as the header example; the DB
    # keeps a link Meta can fetch at send time.
    meta_header_media = await _meta_header_handle(
        db, tenant_id,
        updates.get("header_media_type", template.get("header_media_type")),
        updates.get("header_media_url", template.get("header_media_url")),
    )
    if "header_media_url" in updates:
        updates["header_media_url"] = template_media.link_for(db, tenant_id, updates["header_media_url"])

    if never_reached_meta:
        waba_id = template.get("meta_waba_id") or get_setting("meta_waba_id", tenant_id=tenant_id)
        if not waba_id:
            raise HTTPException(status_code=400, detail="Connect Meta WhatsApp (meta_waba_id) in Settings first")
        try:
            meta_response = await submit_template(
                waba_id=waba_id,
                name=template["name"],
                category=template.get("category") or "MARKETING",
                language=template.get("language") or "en",
                body_text=updates.get("body_text", template.get("body_text", "")),
                header_text=updates.get("header_text", template.get("header_text")),
                header_media_type=updates.get("header_media_type", template.get("header_media_type")),
                header_media_url=meta_header_media,
                footer_text=updates.get("footer_text", template.get("footer_text")),
                buttons=updates.get("buttons", template.get("buttons")),
                tenant_id=tenant_id,
                body_examples=payload.body_examples,
                header_example=payload.header_example,
            )
        except TemplateContentExistsError:
            raise
        except HTTPException as e:
            raise HTTPException(status_code=400, detail=f"Meta didn't accept the template: {_meta_error_text(e.detail)}")
        except Exception as e:
            logger.warning(f"Couldn't reach Meta to submit template {template['name']}: {e}")
            raise HTTPException(status_code=502, detail="Couldn't reach Meta, so the template wasn't sent. Please try again.")
        if not meta_response.get("id"):
            raise HTTPException(status_code=502, detail="Meta didn't confirm the template, so nothing changed. Please try again.")
        updates["meta_template_id"] = str(meta_response["id"])
        updates["meta_waba_id"] = waba_id

    # If the template has a meta_template_id, push update to Meta
    meta_template_id = template.get("meta_template_id")
    if meta_template_id:
        # Build Meta components from the merged template data
        merged_body = updates.get("body_text", template.get("body_text", ""))
        merged_header_text = updates.get("header_text", template.get("header_text"))
        merged_header_media_type = updates.get("header_media_type", template.get("header_media_type"))
        merged_footer_text = updates.get("footer_text", template.get("footer_text"))
        merged_buttons = updates.get("buttons", template.get("buttons"))

        _check_against_meta_rules(
            body_text=merged_body,
            body_examples=payload.body_examples,
            header_text=merged_header_text,
            header_example=payload.header_example,
            header_media_type=merged_header_media_type,
            footer_text=merged_footer_text,
            buttons=merged_buttons,
        )
        components = build_core_components(
            merged_body, payload.body_examples, merged_header_text, payload.header_example,
            merged_header_media_type, meta_header_media, merged_footer_text,
        )

        if merged_buttons:
            button_components = _build_button_components(merged_buttons, 3)
            if button_components:
                components.append({"type": "BUTTONS", "buttons": button_components})

        try:
            await update_template_on_meta(
                meta_template_id=meta_template_id,
                components=components,
                tenant_id=tenant_id,
            )
        except HTTPException as e:
            logger.warning(f"Meta template update failed for {meta_template_id}: {e.detail}")
            raise HTTPException(status_code=400, detail=f"Meta didn't accept the edit: {_meta_error_text(e.detail)}")

    db.table("message_templates").update(updates).eq("id", template_id).eq("tenant_id", tenant_id).execute()
    if was_approved:
        record_edit(db, tenant_id, template_id, "anril")
    updated = db.table("message_templates").select("*").eq("id", template_id).limit(1).execute()
    return updated.data[0] if updated.data else None


@router.post("/upload-media")
async def upload_template_media(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_templates_manage),
):
    """Upload a media file for use in template headers. Returns the Meta header_handle."""
    access_token = get_setting("meta_access_token", tenant_id=tenant_id)
    if not access_token:
        raise HTTPException(status_code=400, detail="meta_access_token not configured in Settings")

    app_id = _meta_app_id(tenant_id)
    if not app_id:
        logger.error("Template media upload: no Meta app id (env META_APP_ID is unset)")
        raise HTTPException(
            status_code=503,
            detail="Media upload isn't set up on the server yet. Please contact Anril support.",
        )

    file_bytes = await file.read()
    file_type = file.content_type or "application/octet-stream"
    file_length = len(file_bytes)

    handle = await upload_media_for_template(
        file_bytes=file_bytes,
        file_type=file_type,
        file_length=file_length,
        app_id=app_id,
        access_token=access_token,
        tenant_id=tenant_id,
    )
    template_media.save_upload(get_supabase(), tenant_id, handle, file_bytes, file_type)
    return {"header_handle": handle}


def _meta_app_id(tenant_id: str) -> Optional[str]:
    # Meta's upload API needs the id of the app that issued the access token. Clients
    # connect through Anril's own Meta app (Embedded Signup), so that is the default;
    # a client who set up their own app can still override it in app_settings.
    return get_setting("meta_app_id", tenant_id=tenant_id) or env_settings.meta_app_id


async def _meta_header_handle(db, tenant_id: str, media_type: Optional[str], value: Optional[str]) -> Optional[str]:
    """The header example to send Meta on an edit. Our stored copy is a URL, which
    Meta's template API doesn't take, so re-upload it for a fresh handle. If that
    fails, send what we have (what edits did before)."""
    if (media_type or "").upper() not in template_media.MEDIA_TYPES or not template_media.is_ours(value):
        return value
    try:
        data, content_type = template_media.read_ours(db, value)
        return await upload_media_for_template(
            file_bytes=data, file_type=content_type, file_length=len(data),
            app_id=_meta_app_id(tenant_id), tenant_id=tenant_id,
        )
    except Exception as e:
        logger.warning("Couldn't re-upload template media to Meta: %s", e)
        return value
