import logging
import re
from typing import Literal
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.config import settings as env_settings
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_id, require_any_permission, require_permission
from app.services.audit_log import record_audit_event
from app.services.incidents import clear_token_incidents
from app.services.assignment import (
    get_inbox_config, get_telecalling_config,
    save_inbox_config, save_telecalling_config,
    _INBOX_CONFIG_DEFAULT, _TELECALLING_CONFIG_DEFAULT,
)
from app.services import astro_bridge, razorpay_oauth
from app.services.intake import get_intake_config, save_intake_config
from app.services.numbers_pool import normalize_phone_number

logger = logging.getLogger(__name__)
router = APIRouter()
require_settings_read = require_permission("settings.view")
require_settings_manage = require_permission("settings.manage")
# Intake config is the Services page's whole data model: Services access or
# full Settings access can reach it.
require_services_read = require_any_permission("services.view", "settings.view")
require_services_manage = require_any_permission("services.manage", "settings.manage")

class SettingsUpdate(BaseModel):
    updates: dict[str, str | None]


# SMS connection settings are operator-managed; tenants cannot replace provider keys or
# callback secrets through the general settings API. See routes/operator_sms.py.
OPERATOR_ONLY_PREFIXES = ("sms_", "bulk9_")


def _operator_only(key: str) -> bool:
    return key.startswith(OPERATOR_ONLY_PREFIXES)


# The handover wording is the 8th Description section now (owner-only, edited through
# PUT /api/v1/ai-tune/profile). The old setting is only a read fallback until the data
# step moves it, so this route must not write it: a write would be silently ignored.
HANDOVER_LINE_KEY = "handover_line"
HANDOVER_LINE_MOVED_MESSAGE = (
    "The handover line is now part of your Description: edit the section "
    "'What Anril says when it brings in your team' on the Knowledge page."
)


class ActivateChannelRequest(BaseModel):
    channel: str  # whatsapp | instagram | facebook | telegram | meta_ads


class DisconnectChannelRequest(BaseModel):
    channel: str  # meta | whatsapp | instagram | facebook | meta_ads | telegram | razorpay
    release_assets: bool = False


class EmbeddedSignupRequest(BaseModel):
    code: str
    waba_id: str
    phone_number_id: str
    business_id: str | None = None
    is_coexistence: bool = False


class FacebookEmbeddedSignupRequest(BaseModel):
    code: str


class MetaBusinessLoginStartRequest(BaseModel):
    code: str


class UnifiedMetaSignupStartRequest(BaseModel):
    code: str
    waba_id: str
    phone_number_id: str
    business_id: str | None = None
    is_coexistence: bool = False


class UnifiedMetaSignupCompleteRequest(BaseModel):
    session_id: str
    # WhatsApp is the point of this flow; a Page is only needed for Messenger and
    # Instagram, so a Page-less signup still connects WhatsApp.
    page_id: str | None = None
    ad_account_id: str | None = None


class MetaBusinessLoginCompleteRequest(BaseModel):
    session_id: str
    page_id: str
    ad_account_id: str | None = None
    catalog_id: str | None = None


class MetaAdsSignupStartRequest(BaseModel):
    code: str


class MetaAdsSignupCompleteRequest(BaseModel):
    session_id: str
    ad_account_id: str


class InboxConfigUpdate(BaseModel):
    enabled: bool | None = None
    auto_assign_enabled: bool | None = None
    segments: list[str] | None = None
    channels: list[str] | None = None
    triggers: list[str] | None = None




class IntakeFieldUpdate(BaseModel):
    key: str
    label: str
    type: Literal["text", "date", "choice"]
    options: list[str] | None = None


class IntakeAddonUpdate(BaseModel):
    key: str
    name: str
    amount_paise: int = 0
    description: str = ""
    active: bool = True
    button_label: str | None = None


class IntakePackageUpdate(BaseModel):
    key: str
    name: str
    amount_paise: int = 0
    description: str = ""
    active: bool = True
    button_label: str | None = None
    options: list["IntakePackageUpdate"] | None = None
    addons: list[IntakeAddonUpdate] | None = None


IntakePackageUpdate.model_rebuild()


MAX_GST_PERCENT = 40


class IntakeConfigUpdate(BaseModel):
    enabled: bool | None = None
    trigger_description: str | None = None
    offer_message: str | None = None
    fields: list[IntakeFieldUpdate] | None = None
    packages: list[IntakePackageUpdate] | None = None
    service_noun: str | None = None
    amount_paise: int | None = None
    gst_percent: float | int | None = None


class TelecallingConfigUpdate(BaseModel):
    enabled: bool | None = None
    segments: list[str] | None = None
    channels: list[str] | None = None
    targets: dict[str, int] | None = None
    scripts: dict[str, str] | None = None
    max_call_attempts: int | None = None
    assignment_mode: Literal["push", "pull"] | None = None
    shift_mode: str | None = None
    shift_start_hour: int | None = None
    shift_end_hour: int | None = None
    recycle_enabled: bool | None = None
    recycle_delay_hours: int | None = None
    recycle_max_retries: int | None = None
    recycle_start_hour: int | None = None
    recycle_end_hour: int | None = None



def _get_setting_value(db, tenant_id: str, key: str) -> str | None:
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", key)
        .maybe_single()
        .execute()
    )
    return row.data["value"] if row and row.data else None

# One source of truth for "which settings keys belong to which channel".
# Used to reset a channel's status and to record how it was connected.
_CHANNEL_CREDENTIAL_KEYS: dict[str, frozenset[str]] = {
    "whatsapp": frozenset({
        "meta_access_token", "meta_phone_number_id", "meta_waba_id",
        "meta_app_secret", "meta_webhook_verify_token",
    }),
    "instagram": frozenset({"instagram_access_token", "instagram_page_id", "instagram_app_secret"}),
    "facebook": frozenset({"facebook_access_token", "facebook_page_id"}),
    "meta_ads": frozenset({"meta_ads_access_token", "meta_ads_account_id"}),
}


# What tearing down each channel means. Shared Meta keys are NOT listed here —
# they are removed only when the last Meta channel goes (see disconnect_channel).
_DISCONNECT_PLAN: dict[str, dict] = {
    "whatsapp": {
        "keys": ("meta_access_token", "meta_phone_number_id", "meta_waba_id"),
        "assets": (("whatsapp_business_account", "meta_waba_id"), ("whatsapp_phone_number", "meta_phone_number_id")),
    },
    "instagram": {
        # No Graph call: Instagram messaging rides the Facebook Page subscription,
        # so unsubscribing here would silently kill Messenger.
        "keys": ("instagram_access_token", "instagram_page_id", "instagram_app_secret"),
        "assets": (("instagram_account", "instagram_page_id"),),
    },
    "facebook": {
        "keys": ("facebook_access_token", "facebook_page_id"),
        "assets": (("facebook_page", "facebook_page_id"),),
    },
    "meta_ads": {
        "keys": ("meta_ads_access_token", "meta_ads_account_id", "meta_ads_account_name", "meta_ads_last_sync_at"),
        "assets": (("ad_account", "meta_ads_account_id"),),
    },
    "telegram": {
        "keys": ("telegram_bot_token", "telegram_webhook_secret"),
        "assets": (),
    },
    "razorpay": {
        "keys": ("razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret"),
        "assets": (),
    },
}

_META_CHANNELS = ("whatsapp", "instagram", "facebook", "meta_ads")

# Verify inbound webhook signatures for WhatsApp, Instagram and Messenger alike.
_SHARED_META_KEYS = ("meta_app_secret", "meta_webhook_verify_token")


def _stamp_connection_source(db, tenant_id: str, channel: str, source: str) -> None:
    """Record whether a channel's credentials came from a Meta-guided flow or a hand-pasted token.

    The UI uses this to label an embedded-provisioned channel instead of implying
    the tenant configured it by hand. `source` is "embedded" or "manual".
    """
    _save_tenant_setting(db, tenant_id, f"{channel}_connection_source", source)


def _upsert_onboarded_phone_number(
    db,
    tenant_id: str,
    *,
    number: str,
    display_name: str,
    meta_phone_number_id: str,
    claim_primary: bool = True,
) -> bool:
    """Record a freshly-onboarded Cloud API number. Returns True if it holds the
    tenant's primary (sending) slot afterwards.

    Primary is exclusive: PATCH /numbers/{id} demotes every other primary before
    promoting one, and numbers_pool picks the *first* row with role="primary", so
    two primaries would make the pool's choice arbitrary.

    `claim_primary=True` -- a hand-pasted token, which names one number explicitly
    and repoints meta_phone_number_id at it -- demotes any incumbent and takes the
    slot. Embedded Signup passes False: adding a second number to a live WABA must
    not silently move the client's traffic onto a number they added days later.
    The slot is still taken when there is no incumbent (a tenant's first number
    must be primary -- compute_unlocked_ids() unlocks nothing at all until one
    exists, so the connection would sit dead), or when the incoming number already
    IS the incumbent, since a reconnect must not demote it. Otherwise the number
    lands standby/warming -- locked if it is over the numbers_pool quota, exactly
    like a sync-from-meta arrival -- and the client promotes it from the Numbers
    page when ready.
    """
    rows = (
        db.table("phone_numbers")
        .select("id,number,role,meta_phone_number_id")
        .eq("tenant_id", tenant_id)
        .neq("status", "archived")
        .execute()
        .data
        or []
    )
    incumbent = next((r for r in rows if r.get("role") == "primary"), None)
    # Match on the Meta id first, then on the number itself normalized, since
    # sync-from-meta stores it stripped of spacing while signup stores it raw --
    # without that fallback a synced row would be duplicated rather than updated.
    target = normalize_phone_number(number)
    row = next(
        (r for r in rows if r.get("meta_phone_number_id") == meta_phone_number_id), None
    ) or next(
        (r for r in rows if normalize_phone_number(r.get("number") or "") == target), None
    )
    is_incumbent = row is not None and incumbent is not None and row["id"] == incumbent["id"]
    takes_primary = claim_primary or incumbent is None or is_incumbent

    fields = {
        "provider": "meta_cloud",
        "number": number.strip(),
        "display_name": display_name,
        "meta_phone_number_id": meta_phone_number_id,
        "tenant_id": tenant_id,
    }
    if takes_primary:
        if incumbent is not None and not is_incumbent:
            db.table("phone_numbers").update({"role": "standby"}).eq(
                "tenant_id", tenant_id
            ).eq("role", "primary").execute()
        # The tenant's own number is already in use, so it skips warm-up.
        warmed_since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        fields.update({
            "role": "primary", "status": "active", "warm_up_day": 14,
            "warm_up_started_at": warmed_since, "paused_outbound": False,
        })
    elif row is None:
        # New arrival that isn't claiming the slot starts cold, like any other
        # number the tenant has not warmed up yet.
        fields.update({"role": "standby", "status": "warming", "warm_up_day": 0, "paused_outbound": False})

    if row is not None:
        # Leave an existing standby's role/status/warm-up alone -- re-running
        # signup shouldn't reset progress it has already accrued.
        db.table("phone_numbers").update(fields).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
    else:
        db.table("phone_numbers").upsert(fields, on_conflict="number").execute()
    return takes_primary


async def setup_telegram_webhook(bot_token: str, tenant_id: str) -> tuple[bool, str | None, str | None]:
    """Register Telegram webhook + return (success, secret_token, error_detail)."""
    from app.config_dynamic import get_setting
    # public_base_url is the host of the single shared deployment (global, not per-tenant);
    # only the webhook *path* is tenant-scoped. Source order: dynamic setting → env → last-resort default.
    _RENDER_BASE_URL = "https://aira-ai-5tfr.onrender.com"
    base_url = get_setting("public_base_url") or env_settings.public_base_url or _RENDER_BASE_URL
    if base_url == _RENDER_BASE_URL:
        logger.warning(
            "Telegram webhook base URL fell back to the hardcoded default — "
            "set PUBLIC_BASE_URL so webhooks register against the correct host."
        )
    webhook_url = f"{base_url.rstrip('/')}/webhook/telegram/{tenant_id}"
    secret_token = secrets.token_urlsafe(32)
    try:
        url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={"url": webhook_url, "secret_token": secret_token},
                timeout=10.0,
            )
            if resp.status_code != 200:
                try:
                    data = resp.json()
                    desc = data.get("description", resp.text)
                except Exception:
                    desc = resp.text
                return False, None, f"Telegram API error ({resp.status_code}): {desc}"
            logger.info(f"Telegram webhook set to {webhook_url} for tenant {tenant_id}")
            return True, secret_token, None
    except httpx.RequestError as req_err:
        logger.error(f"Telegram webhook connection error: {req_err}")
        return False, None, f"Network error connecting to Telegram: {str(req_err)}"
    except Exception as e:
        logger.error(f"Failed to set Telegram webhook: {e}")
        return False, None, str(e)


@router.get("/")
async def list_settings(ctx: dict = Depends(require_settings_read)):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    result = db.table("app_settings").select("*").eq("tenant_id", tenant_id).order("key").execute()
    rows = result.data or []
    settings = []
    for row in rows:
        if _operator_only(row["key"]):
            continue
        db_value = row["value"]
        effective_value = db_value
        is_set = effective_value is not None
        source = "db" if db_value else None
        if row["is_secret"] and is_set and effective_value:
            v = str(effective_value)
            if len(v) > 12:
                display_value = f"{v[:4]}{'•' * 8}{v[-4:]}"
            else:
                display_value = "•" * len(v)
        else:
            display_value = effective_value or "Not set"
        settings.append({
            "key": row["key"],
            "display_value": display_value,
            "is_secret": row["is_secret"],
            "is_set": is_set,
            "source": source,
            "updated_at": row["updated_at"],
        })
    return {"settings": settings}


DESCRIPTION_SETTING_KEY = "business_description"
DESCRIPTION_OWNER_ONLY_MESSAGE = "Only the owner can edit the Description"


def _checked_owner_description(updates: dict, ctx: dict) -> str | None:
    """The Description text to save, or None when this request does not touch it. The
    Description is owner-only and versioned (PUT /api/v1/ai-tune/profile), so the generic
    settings route may not write it raw: other roles get 403, and the owner's text gets the
    same word cap before anything is written."""
    if DESCRIPTION_SETTING_KEY not in updates:
        return None
    if ctx.get("role") != "owner":
        raise HTTPException(status_code=403, detail=DESCRIPTION_OWNER_ONLY_MESSAGE)
    from app.services.business_profile import parse, validate

    text = (updates[DESCRIPTION_SETTING_KEY] or "").strip()
    parsed = parse(text)
    errors = validate(parsed.sections, parsed.other)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return text


def _save_description_as_owner(db, tenant_id: str, text: str, user_id: str | None) -> None:
    """Same write as PUT /api/v1/ai-tune/profile: a version row, then the rubric follow-up."""
    from app.routes.ai_tune import queue_rubric_for_description
    from app.services import knowledge_versions

    knowledge_versions.save_description(db, tenant_id, text, "edit", user_id)
    queue_rubric_for_description(tenant_id, text)


@router.patch("/")
async def update_settings(
    payload: SettingsUpdate,
    background_tasks: BackgroundTasks,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    tenant_id = ctx["tenant_id"]
    if not payload.updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if HANDOVER_LINE_KEY in payload.updates:
        raise HTTPException(status_code=400, detail=HANDOVER_LINE_MOVED_MESSAGE)
    if any(key.startswith(razorpay_oauth.KEY_PREFIX) for key in payload.updates):
        raise HTTPException(status_code=400, detail="Razorpay connection details are set by Connect with Razorpay only.")
    if any(_operator_only(k) for k in payload.updates):
        raise HTTPException(status_code=403, detail="SMS settings are managed by Anril")
    description = _checked_owner_description(payload.updates, ctx)

    db = get_supabase()

    if "telegram_bot_token" in payload.updates:
        tg_token = payload.updates["telegram_bot_token"]
        if tg_token:
            tg_token = tg_token.strip()
            payload.updates["telegram_bot_token"] = tg_token
            # Validate token format locally — no outbound call (avoids Render proxy
            # timeout killing the response). Webhook registration is deferred to the
            # Activate button (same pattern as WhatsApp / Instagram / Facebook).
            if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", tg_token):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid Telegram bot token. Copy the full token from @BotFather — it looks like 123456789:AA... (you may have pasted only the part after the colon).",
                )
            # Clear the old webhook secret when the token changes so a stale
            # secret can't accidentally validate inbound updates for the new token.
            db.table("app_settings").delete() \
                .eq("tenant_id", tenant_id) \
                .eq("key", "telegram_webhook_secret") \
                .execute()
            db.table("app_settings").upsert({
                "tenant_id": tenant_id,
                "key": "telegram_status",
                "value": "configured",
                "is_secret": False,
                "updated_at": "now()",
            }, on_conflict="tenant_id,key").execute()
        else:
            # Token is cleared/empty. Scrub the webhook secret and status.
            db.table("app_settings").delete().eq("tenant_id", tenant_id).eq("key", "telegram_webhook_secret").execute()
            db.table("app_settings").delete().eq("tenant_id", tenant_id).eq("key", "telegram_status").execute()

    from app.config_dynamic import SECRET_SETTING_KEYS

    if (payload.updates.get("meta_ads_account_id") or "").strip():
        _stamp_meta_ads_connected(db, tenant_id, payload.updates["meta_ads_account_id"])

    updated = []
    for key, value in payload.updates.items():
        if key == DESCRIPTION_SETTING_KEY:
            continue  # written below through the versioned Description path
        is_secret = key in SECRET_SETTING_KEYS
        if value == "":
            # Empty string means "clear this value" — delete the row rather than
            # storing "", which would otherwise still read back as is_set=True.
            db.table("app_settings").delete().eq("tenant_id", tenant_id).eq("key", key).execute()
            updated.append(key)
            continue
        result = (
            db.table("app_settings")
            .upsert({
                "tenant_id": tenant_id,
                "key": key,
                "value": value,
                "is_secret": is_secret,
                "updated_at": "now()",
            }, on_conflict="tenant_id,key")
            .execute()
        )
        if result.data:
            updated.append(key)

    if description is not None:
        _save_description_as_owner(db, tenant_id, description, user.get("user_id"))
        updated.append(DESCRIPTION_SETTING_KEY)

    # Credentials changed by hand: the channel must be re-validated, and it is no
    # longer whatever the embedded flow provisioned.
    touched_meta_channel = False
    for channel, credential_keys in _CHANNEL_CREDENTIAL_KEYS.items():
        if any(key in updated for key in credential_keys):
            _save_tenant_setting(db, tenant_id, f"{channel}_status", "configured")
            _stamp_connection_source(db, tenant_id, channel, "manual")
            if channel in ("whatsapp", "instagram", "facebook"):
                touched_meta_channel = True

    # The app secret and verify token are Anril's own, identical for every tenant, and
    # only the WhatsApp form asks for them. Embedded Signup copies them in; a manual
    # save never did — so an Instagram- or Facebook-only tenant had no way to get them
    # and every inbound message was dropped as unsigned. Fill the gap here, without
    # overwriting anything the operator typed in this same request.
    if touched_meta_channel:
        _save_shared_meta_app_credentials(db, tenant_id, only_if_missing=True)

    from app.config_dynamic import invalidate_cache
    invalidate_cache()
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.updated",
        target_type="app_settings",
        target_id=tenant_id,
        metadata={
            "updated_keys": updated,
            "secret_keys": [key for key in updated if key in SECRET_SETTING_KEYS],
        },
    )
    if DESCRIPTION_SETTING_KEY in updated:
        from app.services.consistency import run_check_safely
        background_tasks.add_task(run_check_safely, tenant_id)
    return {"updated": updated}


@router.get("/webhook-health")
async def webhook_health(ctx: dict = Depends(require_settings_read)):
    """Return last inbound event timestamp per channel + recent token_invalid incidents."""
    from app.services.webhook_health import get_webhook_health

    return get_webhook_health(get_supabase(), ctx["tenant_id"])


@router.post("/webhook-subscriptions/sync")
async def sync_webhook_subscriptions(ctx: dict = Depends(require_settings_manage)):
    """Register the app-level callback URL + verify token for every channel.

    App-level rather than tenant-level: it installs the same canonical URLs derived
    from server config for everyone and takes no caller input, so this cannot be used
    to point the app's webhooks somewhere of the caller's choosing.
    """
    from app.services.meta_app_webhooks import sync_all_app_webhook_subscriptions

    results = await sync_all_app_webhook_subscriptions()
    return {"results": results, "all_ok": all(r.get("ok") for r in results.values())}


async def _resolve_token_app_id(access_token: str) -> tuple[str | None, bool]:
    """Ask Meta which app issued this token.

    Returns `(app_id, is_foreign)`. `is_foreign` is True when Meta states outright
    that the token belongs to another app — that refusal is the answer, not a
    failure to answer. Anything genuinely inconclusive returns `(None, False)` so a
    Graph outage never blocks activation.

    Same `debug_token` call `meta_cloud._read_granular_scopes` already makes.
    """
    if not env_settings.meta_app_id or not env_settings.meta_app_secret:
        return None, False
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://graph.facebook.com/v21.0/debug_token",
                params={
                    "input_token": access_token,
                    "access_token": f"{env_settings.meta_app_id}|{env_settings.meta_app_secret}",
                },
                timeout=10.0,
            )
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"debug_token lookup failed: {e}")
        return None, False

    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict) and data.get("app_id"):
        return str(data["app_id"]), False

    # Meta refuses to introspect a token issued by another app, and says so in
    # exactly these words. That refusal *is* the mismatch — treating it as merely
    # inconclusive is what let a Test Anril token through on 2026-08-30 12:21.
    error = (body or {}).get("error", {}) if isinstance(body, dict) else {}
    message = error.get("message", "no data returned")
    if "did not match the viewing app" in message.lower():
        logger.warning(f"debug_token: token belongs to another Meta app — {message}")
        return None, True

    logger.warning(f"debug_token could not identify the token's app: {message}")
    return None, False


@router.post("/activate")
async def activate_channel(
    payload: ActivateChannelRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    tenant_id = ctx["tenant_id"]
    """Validate credentials and connect the requested messaging or ads integration."""
    channel = payload.channel
    if channel not in ("whatsapp", "instagram", "facebook", "telegram", "meta_ads"):
        raise HTTPException(
            status_code=400,
            detail="Invalid channel. Must be whatsapp, instagram, facebook, telegram, or meta_ads.",
        )

    db = get_supabase()

    if channel == "meta_ads":
        from app.services.meta_ads_insights_sync import normalize_account_id

        token = _get_setting_value(db, tenant_id, "meta_ads_access_token")
        raw_account = _get_setting_value(db, tenant_id, "meta_ads_account_id")
        if not token or not raw_account:
            raise HTTPException(
                status_code=400,
                detail="Save the Meta Ads Account ID and System User token first.",
            )
        account = normalize_account_id(raw_account)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://graph.facebook.com/v21.0/{account}",
                params={
                    "fields": "id,name,account_status,currency,timezone_name",
                    "access_token": token,
                },
                timeout=10.0,
            )
        data = response.json()
        if "error" in data:
            raise HTTPException(
                status_code=400,
                detail=data["error"].get("message", "Invalid Meta Ads credentials"),
            )

        now_value = "now()"
        saved_values = {
            "meta_ads_account_id": account,
            "meta_ads_account_name": data.get("name") or account,
            "meta_ads_currency": data.get("currency"),
            "meta_ads_timezone": data.get("timezone_name"),
            "meta_ads_status": "live",
        }
        for key, value in saved_values.items():
            if value is None:
                continue
            db.table("app_settings").upsert({
                "tenant_id": tenant_id,
                "key": key,
                "value": str(value),
                "is_secret": False,
                "updated_at": now_value,
            }, on_conflict="tenant_id,key").execute()

        record_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=user.get("user_id"),
            actor_role="tenant_user",
            action="settings.channel_activated",
            target_type="channel",
            target_id="meta_ads",
            metadata={"channel": "meta_ads", "account_id": account},
        )
        return {
            "channel": "meta_ads",
            "account_id": account,
            "account_name": data.get("name"),
            "account_status": data.get("account_status"),
            "currency": data.get("currency"),
            "timezone": data.get("timezone_name"),
        }

    if channel == "telegram":
        token = _get_setting_value(db, tenant_id, "telegram_bot_token")
        if not token:
            raise HTTPException(status_code=400, detail="Save your Telegram bot token first.")

        # Re-register the webhook (refreshes the secret) without forcing the user to re-paste the token.
        success, secret_token, err_msg = await setup_telegram_webhook(token, tenant_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Telegram rejected this bot token. Error details: {err_msg or 'Unknown error'}. Re-copy the full token from @BotFather and try again.",
            )
        if secret_token:
            db.table("app_settings").upsert({
                "tenant_id": tenant_id,
                "key": "telegram_webhook_secret",
                "value": secret_token,
                "is_secret": True,
                "updated_at": "now()",
            }, on_conflict="tenant_id,key").execute()

        # Confirm the bot identity to show the user which bot is connected.
        bot_name = None
        bot_id = None
        try:
            async with httpx.AsyncClient() as client:
                me_r = await client.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10.0)
            me = me_r.json()
            if me.get("ok"):
                result = me.get("result", {})
                username = result.get("username")
                bot_name = f"@{username}" if username else result.get("first_name")
                bot_id = str(result.get("id")) if result.get("id") is not None else None
        except Exception as me_err:
            logger.warning(f"Telegram getMe failed for tenant {tenant_id}: {me_err}")

        db.table("app_settings").upsert({
            "tenant_id": tenant_id,
            "key": "telegram_status",
            "value": "live",
            "is_secret": False,
            "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()

        from app.config_dynamic import invalidate_cache
        invalidate_cache()
        record_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=user.get("user_id"),
            actor_role="tenant_user",
            action="settings.channel_activated",
            target_type="channel",
            target_id="telegram",
            metadata={"channel": "telegram", "subscribed": True},
        )
        return {
            "channel": "telegram",
            "page_name": bot_name,
            "page_id": bot_id,
            "subscribed": True,
        }

    if channel == "whatsapp":
        token = _get_setting_value(db, tenant_id, "meta_access_token")
        phone_id = _get_setting_value(db, tenant_id, "meta_phone_number_id")
        waba_id = _get_setting_value(db, tenant_id, "meta_waba_id")
        if not token or not phone_id:
            raise HTTPException(status_code=400, detail="Save meta_access_token and meta_phone_number_id first.")

        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://graph.facebook.com/v21.0/{phone_id}",
                params={"fields": "display_phone_number,verified_name", "access_token": token},
                timeout=10.0,
            )
        data = r.json()
        if "error" in data:
            raise HTTPException(status_code=400, detail=data["error"].get("message", "Invalid credentials"))

        subscribed = False
        if waba_id:
            async with httpx.AsyncClient() as client:
                sub_r = await client.post(
                    f"https://graph.facebook.com/v21.0/{waba_id}/subscribed_apps",
                    params={"access_token": token},
                    timeout=10.0,
                )
            sub_data = sub_r.json()
            subscribed = sub_data.get("success", False)
            if "error" in sub_data:
                logger.warning(f"WA subscribed_apps failed for tenant {tenant_id}: {sub_data['error']}")

        logger.info(f"WhatsApp activated tenant={tenant_id} phone={data.get('display_phone_number')} subscribed={subscribed}")
        
        # Upsert number into phone_numbers table
        try:
            display_phone = data.get("display_phone_number")
            if display_phone:
                _upsert_onboarded_phone_number(
                    db,
                    tenant_id,
                    number=display_phone,
                    display_name=data.get("verified_name") or "WhatsApp Primary",
                    meta_phone_number_id=phone_id,
                    claim_primary=True,
                )
                logger.info(f"Automatically registered active primary number {display_phone} for tenant {tenant_id}")
                # Mirror the human-readable identity onto app_settings so the
                # Connectivity Hub can name the account without a second fetch.
                _save_tenant_setting(db, tenant_id, "meta_phone_display", display_phone.strip())
                if data.get("verified_name"):
                    _save_tenant_setting(db, tenant_id, "meta_verified_name", data["verified_name"])
        except Exception as phone_reg_err:
            logger.warning(f"Failed to auto-register phone number on activation: {phone_reg_err}")

        # Save activation status to app_settings
        db.table("app_settings").upsert({
            "tenant_id": tenant_id,
            "key": "whatsapp_status",
            "value": "live",
            "is_secret": False,
            "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()

        record_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=user.get("user_id"),
            actor_role="tenant_user",
            action="settings.channel_activated",
            target_type="channel",
            target_id="whatsapp",
            metadata={"channel": "whatsapp", "subscribed": subscribed},
        )
        from app.services.meta_app_webhooks import ensure_app_webhook_subscription
        wa_webhook_registration = await ensure_app_webhook_subscription("whatsapp")

        return {
            "channel": "whatsapp",
            "phone_number": data.get("display_phone_number"),
            "business_name": data.get("verified_name"),
            "subscribed": subscribed,
            "webhook_registration": wa_webhook_registration,
        }

    # instagram or facebook
    token_key = f"{channel}_access_token"
    page_id_key = f"{channel}_page_id"
    token = _get_setting_value(db, tenant_id, token_key)
    page_id = _get_setting_value(db, tenant_id, page_id_key)
    if not token or not page_id:
        raise HTTPException(status_code=400, detail=f"Save {token_key} and {page_id_key} first.")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://graph.facebook.com/v21.0/me",
            params={"fields": "name,id", "access_token": token},
            timeout=10.0,
        )
    data = r.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"].get("message", "Invalid credentials"))

    # A token from a different Meta app passes /me and subscribes happily — and then
    # every inbound event fails signature verification and is dropped, because Meta
    # signs with the App Secret of the app that owns the subscription. That failure is
    # invisible from the product, so catch the mismatch here, at the click.
    token_app_id, token_is_foreign = await _resolve_token_app_id(token)
    if token_is_foreign or (
        token_app_id and env_settings.meta_app_id and token_app_id != env_settings.meta_app_id
    ):
        belongs_to = f"Meta app {token_app_id}" if token_app_id else "a different Meta app"
        raise HTTPException(
            status_code=400,
            detail=(
                f"This token belongs to {belongs_to}, but Anril verifies webhooks with app "
                f"{env_settings.meta_app_id}. Generate a Page access token inside app "
                f"{env_settings.meta_app_id} and paste that one — otherwise messages arrive "
                f"and are rejected as unsigned. Nothing was changed."
            ),
        )

    # Page and Instagram are separate webhook objects with separate field
    # vocabularies. message_deliveries/message_reads are Messenger-only; sending
    # them to the Instagram node rejects the whole call with (#100) and leaves the
    # channel subscribed to nothing, so Instagram gets its own equivalents.
    sub_fields = (
        "messages,messaging_postbacks,messaging_seen"
        if channel == "instagram"
        else "messages,messaging_postbacks,message_deliveries,message_reads,messaging_referrals"
    )
    async with httpx.AsyncClient() as client:
        sub_r = await client.post(
            f"https://graph.facebook.com/v21.0/{page_id}/subscribed_apps",
            params={"subscribed_fields": sub_fields, "access_token": token},
            timeout=10.0,
        )
    sub_data = sub_r.json()
    subscribed = sub_data.get("success", False)
    if "error" in sub_data:
        logger.warning(f"{channel} subscribed_apps failed tenant={tenant_id}: {sub_data['error']}")

    # Save activation status to app_settings
    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": f"{channel}_status",
        "value": "live",
        "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()

    # The callback URL + verify token are app-level and were historically pasted into
    # the Meta console by hand — which is why a channel could be "live" here while Meta
    # had nowhere to deliver to. Re-assert them on every activation: idempotent, and it
    # removes the manual step entirely.
    from app.services.meta_app_webhooks import ensure_app_webhook_subscription
    webhook_registration = await ensure_app_webhook_subscription(channel)

    logger.info(f"{channel} activated tenant={tenant_id} page={data.get('name')} subscribed={subscribed}")
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.channel_activated",
        target_type="channel",
        target_id=channel,
        metadata={"channel": channel, "subscribed": subscribed, "page_id": page_id},
    )
    return {
        "channel": channel,
        "page_name": data.get("name"),
        "page_id": data.get("id"),
        "subscribed": subscribed,
        "webhook_registration": webhook_registration,
    }


@router.post("/whatsapp/embedded-signup")
async def whatsapp_embedded_signup(
    payload: EmbeddedSignupRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    """Finish WhatsApp Embedded Signup: exchange the popup's code for a token,
    register the phone number, subscribe the webhook, and save credentials —
    the automated replacement for manually pasting them in below."""
    from app.services.meta_cloud import exchange_embedded_signup_code, register_phone_number, request_coexistence_sync

    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    exchange = await exchange_embedded_signup_code(payload.code)
    access_token = exchange["access_token"]

    if payload.is_coexistence:
        # Number is already registered on the phone's WhatsApp Business app —
        # calling register_phone_number here would be wrong for this path.
        logger.info(f"Embedded Signup: coexistence path — skipping phone registration tenant={tenant_id}")
        await request_coexistence_sync(payload.phone_number_id, access_token)
    else:
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        reg_result = await register_phone_number(payload.phone_number_id, access_token, pin)
        if "error" in reg_result:
            logger.warning(f"Embedded Signup: phone registration failed tenant={tenant_id}: {reg_result['error']}")

    async with httpx.AsyncClient() as client:
        sub_r = await client.post(
            f"https://graph.facebook.com/v21.0/{payload.waba_id}/subscribed_apps",
            params={"access_token": access_token},
            timeout=10.0,
        )
    sub_data = sub_r.json()
    subscribed = sub_data.get("success", False)
    if "error" in sub_data:
        logger.warning(f"Embedded Signup: subscribed_apps failed tenant={tenant_id}: {sub_data['error']}")

    async with httpx.AsyncClient() as client:
        info_r = await client.get(
            f"https://graph.facebook.com/v21.0/{payload.phone_number_id}",
            params={"fields": "display_phone_number,verified_name", "access_token": access_token},
            timeout=10.0,
        )
    info_data = info_r.json()
    display_phone = info_data.get("display_phone_number")

    # Settle the phone_numbers row before writing credentials: whether this
    # number took the primary slot decides whether the tenant-level sender
    # follows it. An added second number must leave both pointing at the
    # incumbent, or outbound would split -- pool-routed sends would use the old
    # number while everything falling back on meta_phone_number_id used the new.
    holds_primary = True
    if display_phone:
        holds_primary = _upsert_onboarded_phone_number(
            db,
            tenant_id,
            number=display_phone,
            display_name=info_data.get("verified_name") or "WhatsApp Primary",
            meta_phone_number_id=payload.phone_number_id,
            claim_primary=False,
        )

    creds_to_save = {
        "meta_access_token": access_token,
        "meta_waba_id": payload.waba_id,
    }
    if holds_primary:
        creds_to_save["meta_phone_number_id"] = payload.phone_number_id
    for key, value in creds_to_save.items():
        if not value:
            continue
        db.table("app_settings").upsert({
            "tenant_id": tenant_id,
            "key": key,
            "value": value,
            "is_secret": key == "meta_access_token",
            "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()
    _save_shared_meta_app_credentials(db, tenant_id)

    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": "whatsapp_status",
        "value": "live",
        "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()
    _stamp_connection_source(db, tenant_id, "whatsapp", "embedded")

    # The Hub's account label names the sending number, so it only moves when
    # the sending number does.
    if holds_primary:
        if display_phone:
            _save_tenant_setting(db, tenant_id, "meta_phone_display", display_phone.strip())
        if info_data.get("verified_name"):
            _save_tenant_setting(db, tenant_id, "meta_verified_name", info_data["verified_name"])
    _save_tenant_setting(db, tenant_id, "meta_connected_at", datetime.now(timezone.utc).isoformat())

    from app.config_dynamic import invalidate_cache
    invalidate_cache()

    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.whatsapp_embedded_signup_connected",
        target_type="channel",
        target_id="whatsapp",
        metadata={"channel": "whatsapp", "waba_id": payload.waba_id, "subscribed": subscribed, "is_coexistence": payload.is_coexistence},
    )

    return {
        "success": True,
        "phone_number": display_phone,
        "business_name": info_data.get("verified_name"),
        "subscribed": subscribed,
    }


_META_BUSINESS_ONBOARDING_KEYS = (
    "meta_business_onboarding_token",
    "meta_business_onboarding_session_id",
    "meta_business_onboarding_expires_at",
    "meta_business_onboarding_waba_id",
    "meta_business_onboarding_phone_number_id",
    "meta_business_onboarding_business_id",
    "meta_business_onboarding_is_coexistence",
)

# The ads-only signup stages under its own keys so a WhatsApp signup running in
# another tab cannot consume or clear this session's token.
_META_ADS_ONBOARDING_KEYS = (
    "meta_ads_onboarding_token",
    "meta_ads_onboarding_session_id",
    "meta_ads_onboarding_expires_at",
)


def _delete_tenant_settings(db, tenant_id: str, keys) -> None:
    key_list = list(keys)
    if not key_list:
        return
    db.table("app_settings").delete().eq("tenant_id", tenant_id).in_("key", key_list).execute()


async def _unsubscribe_channel_webhook(db, tenant_id: str, channel: str) -> bool:
    """Best-effort remote unsubscribe. Never blocks the local teardown."""
    try:
        if channel == "whatsapp":
            waba_id = _get_setting_value(db, tenant_id, "meta_waba_id")
            token = _get_setting_value(db, tenant_id, "meta_access_token")
            if not waba_id or not token:
                return False
            async with httpx.AsyncClient() as client:
                await client.delete(
                    f"https://graph.facebook.com/v21.0/{waba_id}/subscribed_apps",
                    params={"access_token": token},
                    timeout=10.0,
                )
            return True
        if channel == "facebook":
            page_id = _get_setting_value(db, tenant_id, "facebook_page_id")
            token = _get_setting_value(db, tenant_id, "facebook_access_token")
            if not page_id or not token:
                return False
            async with httpx.AsyncClient() as client:
                await client.delete(
                    f"https://graph.facebook.com/v25.0/{page_id}/subscribed_apps",
                    params={"access_token": token},
                    timeout=10.0,
                )
            return True
        if channel == "telegram":
            token = _get_setting_value(db, tenant_id, "telegram_bot_token")
            if not token:
                return False
            async with httpx.AsyncClient() as client:
                await client.delete(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=10.0)
            return True
    except Exception as exc:
        logger.warning("Disconnect webhook unsubscribe failed tenant=%s channel=%s: %s", tenant_id, channel, exc)
        return False
    return False


@router.post("/disconnect")
async def disconnect_channel(
    payload: DisconnectChannelRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    """Tear down a channel: unsubscribe at the provider, delete credentials, optionally
    release the Meta asset claim so it can be connected to a different workspace."""
    tenant_id = ctx["tenant_id"]
    channels = list(_META_CHANNELS) if payload.channel == "meta" else [payload.channel]
    unknown = [c for c in channels if c not in _DISCONNECT_PLAN]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown channel: {unknown[0]}")

    db = get_supabase()
    results = []
    released_assets: list[dict[str, str]] = []

    for channel in channels:
        plan = _DISCONNECT_PLAN[channel]
        unsubscribed = await _unsubscribe_channel_webhook(db, tenant_id, channel)
        if channel == "razorpay":
            await razorpay_oauth.disconnect(db, tenant_id)

        if payload.release_assets:
            for asset_type, source_key in plan["assets"]:
                asset_id = _get_setting_value(db, tenant_id, source_key)
                if asset_id:
                    released_assets.append({"asset_type": asset_type, "asset_id": asset_id})

        if channel == "whatsapp":
            phone_number_id = _get_setting_value(db, tenant_id, "meta_phone_number_id")
            if phone_number_id:
                # History rows reference this number — archive, never delete. Bookkeeping only:
                # the webhook is already unsubscribed by here, so a failure must not abort the
                # teardown and strand the tenant with live credentials and no delivery.
                try:
                    db.table("phone_numbers").update({"status": "archived", "paused_outbound": True}) \
                        .eq("tenant_id", tenant_id).eq("meta_phone_number_id", phone_number_id).execute()
                except Exception as exc:
                    logger.error(
                        "Archiving phone number failed tenant=%s phone_number_id=%s: %s",
                        tenant_id, phone_number_id, exc,
                    )

        _delete_tenant_settings(
            db, tenant_id,
            list(plan["keys"]) + [f"{channel}_status", f"{channel}_connection_source"],
        )
        clear_token_incidents(db, tenant_id, channel)
        results.append({"channel": channel, "webhook_unsubscribed": unsubscribed})

    remaining_meta = [
        c for c in _META_CHANNELS
        if c not in channels and any(_get_setting_value(db, tenant_id, k) for k in _DISCONNECT_PLAN[c]["keys"])
    ]
    if not remaining_meta and any(c in _META_CHANNELS for c in channels):
        _delete_tenant_settings(db, tenant_id, _SHARED_META_KEYS)

    if released_assets:
        try:
            db.rpc("release_meta_assets", {"p_tenant_id": tenant_id, "p_assets": released_assets}).execute()
        except Exception as exc:
            logger.error("Meta asset release failed tenant=%s: %s", tenant_id, exc)
            raise HTTPException(
                status_code=503,
                detail="Channels were disconnected, but the Meta assets could not be released. Please try again.",
            ) from exc

    from app.config_dynamic import invalidate_cache
    invalidate_cache()
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.channel_disconnected",
        target_type="channel",
        target_id=payload.channel,
        metadata={"channels": channels, "released_assets": len(released_assets)},
    )
    return {"success": True, "results": results, "released_assets": len(released_assets)}


class RazorpayOAuthCompleteRequest(BaseModel):
    code: str
    state: str


@router.post("/razorpay/oauth/start")
async def start_razorpay_oauth(ctx: dict = Depends(require_settings_manage)):
    """Begin Connect with Razorpay: returns the consent URL the browser should go to."""
    try:
        url = razorpay_oauth.start(get_supabase(), ctx["tenant_id"])
    except razorpay_oauth.RazorpayOAuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return {"authorize_url": url}


@router.post("/razorpay/oauth/complete")
async def complete_razorpay_oauth(
    payload: RazorpayOAuthCompleteRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    """Finish Connect with Razorpay from the callback page (code + state from the redirect)."""
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    try:
        result = await razorpay_oauth.complete(db, tenant_id, payload.code, payload.state)
    except razorpay_oauth.RazorpayOAuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.channel_connected",
        target_type="channel",
        target_id="razorpay",
        metadata={"source": "oauth", "account_id": result["account_id"]},
    )
    return {"success": True, **result}


def _stamp_meta_ads_connected(db, tenant_id: str, account_id: str) -> None:
    """Start the Meta Ads join rule for a newly connected ad account.

    Call BEFORE meta_ads_account_id is overwritten. Reconnecting the same account
    (e.g. a token refresh) keeps the original join time and history choice. A new
    account gets: connected-at now, history "from today" until the tenant picks a
    date, and a fresh snapshot of the ads running right now on its next sync
    (services/meta_ads_insights_sync.refresh_ad_registry).
    """
    def _act(value: str | None) -> str:
        v = (value or "").strip()
        return v if v.startswith("act_") or not v else f"act_{v}"

    previous = _get_setting_value(db, tenant_id, "meta_ads_account_id")
    if _act(previous) == _act(account_id) and _get_setting_value(db, tenant_id, "meta_ads_connected_at"):
        return
    now = datetime.now(timezone.utc)
    db.table("app_settings").upsert([
        {"tenant_id": tenant_id, "key": "meta_ads_connected_at", "value": now.isoformat(),
         "is_secret": False, "updated_at": now.isoformat()},
        {"tenant_id": tenant_id, "key": "meta_ads_sync_start_date", "value": now.date().isoformat(),
         "is_secret": False, "updated_at": now.isoformat()},
    ], on_conflict="tenant_id,key").execute()
    _delete_tenant_settings(
        db, tenant_id, ("meta_ads_join_snapshot_account", "meta_ads_backfilled_from")
    )


def _save_tenant_setting(db, tenant_id: str, key: str, value: str, *, is_secret: bool = False) -> None:
    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": key,
        "value": value,
        "is_secret": is_secret,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()


def _save_shared_meta_app_credentials(db, tenant_id: str, only_if_missing: bool = False) -> None:
    """Copy the app-level Meta secrets onto a tenant that just connected a channel.

    Every tenant signs up through the same Meta app, so the app secret and the
    webhook verify token are Anril's, not theirs. Meta never returns either one —
    the verify token in particular is a string we choose and paste into the app's
    webhook settings — but the inbound routes read both per-tenant and
    get_setting has no env fallback, so a tenant without these rows silently
    fails Meta's webhook challenge with a 403. Writing them at connect time is
    what saves someone hand-pasting them after every signup.

    `only_if_missing` is for manual saves. The WhatsApp form asks the operator for
    both values directly, and `update_settings` has already stored whatever they
    typed by the time this runs — so skipping keys that already have a value keeps
    an explicit entry from being overwritten, while still filling the gap for an
    Instagram- or Facebook-only tenant whose form never asks for them.
    """
    # META_VERIFY_TOKEN is not set on every deployment; fall back to the copy the
    # existing tenants already hold rather than writing nothing.
    from app.services.meta_app_webhooks import resolve_verify_token

    for key, value in (
        ("meta_app_secret", env_settings.meta_app_secret),
        ("meta_webhook_verify_token", env_settings.meta_verify_token or resolve_verify_token()),
    ):
        if not value:
            continue
        if only_if_missing and _get_setting_value(db, tenant_id, key):
            continue
        _save_tenant_setting(db, tenant_id, key, value, is_secret=True)


def _public_business_login_assets(assets: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Return only browser-safe metadata; Graph access tokens must never leave Anril."""
    return {
        "pages": [
            {
                "id": page.get("id"),
                "name": page.get("name") or "Unnamed Page",
                "instagram_business_account": page.get("instagram_business_account"),
            }
            for page in assets.get("pages", [])
            if page.get("id")
        ],
        "ad_accounts": [
            {
                key: account[key]
                for key in ("id", "name", "account_id", "account_status", "currency", "timezone_name")
                if account.get(key) is not None
            }
            for account in assets.get("ad_accounts", [])
            if account.get("id")
        ],
        "catalogs": [
            {"id": catalog.get("id"), "name": catalog.get("name") or "Unnamed catalog"}
            for catalog in assets.get("catalogs", [])
            if catalog.get("id")
        ],
    }


def _public_unified_meta_assets(assets: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Return only the assets supported by Anril's unified setup flow."""
    public_assets = _public_business_login_assets(assets)
    return {"pages": public_assets["pages"], "ad_accounts": public_assets["ad_accounts"]}


def _public_meta_ads_assets(assets: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Return only ad accounts — the ads-only Login configuration grants nothing else."""
    return {"ad_accounts": _public_business_login_assets(assets)["ad_accounts"]}


def _claim_business_assets(db, tenant_id: str, claims: list[dict[str, str]]) -> None:
    """Atomically claim Meta assets so an inbound webhook has one tenant owner."""
    try:
        db.rpc("claim_meta_assets", {"p_tenant_id": tenant_id, "p_assets": claims}).execute()
    except Exception as exc:
        logger.warning("General Meta signup asset claim failed tenant=%s: %s", tenant_id, exc)
        if "23505" in str(getattr(exc, "code", "")) or "23505" in str(exc):
            raise HTTPException(status_code=409, detail="One of those Meta assets is already connected to another Anril workspace.") from exc
        raise HTTPException(status_code=503, detail="Meta asset ownership could not be confirmed. Please try again.") from exc


@router.post("/facebook/business-login/start")
async def start_meta_business_login(
    payload: MetaBusinessLoginStartRequest,
    ctx: dict = Depends(require_settings_manage),
):
    """Exchange a General Facebook Login for Business code and safely list assets.

    The Meta code is single-use. Its token stays server-side while the browser chooses
    which of the granted Page, ad account, and catalog it wants to connect.
    """
    from app.services.meta_cloud import exchange_embedded_signup_code, discover_business_login_assets

    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    exchange = await exchange_embedded_signup_code(payload.code)
    access_token = exchange["access_token"]
    assets = await discover_business_login_assets(access_token)
    public_assets = _public_business_login_assets(assets)
    if not public_assets["pages"]:
        raise HTTPException(status_code=400, detail="No Facebook Page was granted — select at least one Page during Meta signup.")

    session_id = str(uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_token", access_token, is_secret=True)
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_session_id", session_id, is_secret=True)
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_expires_at", expires_at)

    return {"session_id": session_id, **public_assets}


@router.post("/meta/unified-signup/start")
async def start_unified_meta_signup(
    payload: UnifiedMetaSignupStartRequest,
    ctx: dict = Depends(require_settings_manage),
):
    """Exchange one Meta signup code and stage WhatsApp plus safe asset choices.

    The popup code can only be exchanged once. The access token and WhatsApp IDs
    therefore remain server-side until the person explicitly selects their Page
    and optional read-only ads account.
    """
    from app.services.meta_cloud import exchange_embedded_signup_code, discover_business_login_assets

    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    exchange = await exchange_embedded_signup_code(payload.code)
    access_token = exchange["access_token"]
    assets = await discover_business_login_assets(access_token)
    public_assets = _public_unified_meta_assets(assets)
    if not public_assets["pages"]:
        logger.info("Unified Meta signup granted no Facebook Page tenant=%s — connecting WhatsApp only", tenant_id)

    session_id = str(uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_token", access_token, is_secret=True)
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_session_id", session_id, is_secret=True)
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_expires_at", expires_at)
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_waba_id", payload.waba_id)
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_phone_number_id", payload.phone_number_id)
    if payload.business_id:
        _save_tenant_setting(db, tenant_id, "meta_business_onboarding_business_id", payload.business_id)
    _save_tenant_setting(db, tenant_id, "meta_business_onboarding_is_coexistence", str(payload.is_coexistence).lower())

    return {"session_id": session_id, **public_assets}


@router.post("/facebook/business-login/complete")
async def complete_meta_business_login(
    payload: MetaBusinessLoginCompleteRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    """Validate explicit General Login selections and persist the connected assets."""
    from app.services.meta_cloud import discover_business_login_assets

    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    access_token = _get_setting_value(db, tenant_id, "meta_business_onboarding_token")
    session_id = _get_setting_value(db, tenant_id, "meta_business_onboarding_session_id")
    expires_at = _get_setting_value(db, tenant_id, "meta_business_onboarding_expires_at")
    if not access_token or not session_id or not expires_at or payload.session_id != session_id:
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.") from exc
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.")

    assets = await discover_business_login_assets(access_token)
    pages_by_id = {page.get("id"): page for page in assets.get("pages", []) if page.get("id")}
    ads_by_id = {account.get("id"): account for account in assets.get("ad_accounts", []) if account.get("id")}
    catalogs_by_id = {catalog.get("id"): catalog for catalog in assets.get("catalogs", []) if catalog.get("id")}
    page = pages_by_id.get(payload.page_id)
    if not page or not page.get("access_token"):
        raise HTTPException(status_code=400, detail="Select a Facebook Page that was granted during this Meta signup.")
    ad_account = ads_by_id.get(payload.ad_account_id) if payload.ad_account_id else None
    if payload.ad_account_id and not ad_account:
        raise HTTPException(status_code=400, detail="Select an ad account that was granted during this Meta signup.")
    catalog = catalogs_by_id.get(payload.catalog_id) if payload.catalog_id else None
    if payload.catalog_id and not catalog:
        raise HTTPException(status_code=400, detail="Select a catalog that was granted during this Meta signup.")

    ig_account = page.get("instagram_business_account") or {}
    ig_account_id = ig_account.get("id")
    claims = [{"asset_type": "facebook_page", "asset_id": payload.page_id}]
    if ig_account_id:
        claims.append({"asset_type": "instagram_account", "asset_id": ig_account_id})
    if ad_account:
        claims.append({"asset_type": "ad_account", "asset_id": ad_account["id"]})
    if catalog:
        claims.append({"asset_type": "catalog", "asset_id": catalog["id"]})
    _claim_business_assets(db, tenant_id, claims)

    page_token = page["access_token"]
    subscribed = False
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://graph.facebook.com/v25.0/{payload.page_id}/subscribed_apps",
                params={
                    "subscribed_fields": "messages,messaging_postbacks,message_deliveries,message_reads,messaging_referrals",
                    "access_token": page_token,
                },
                timeout=10.0,
            )
        subscribed = bool(response.json().get("success", False))
    except httpx.HTTPError as exc:
        logger.warning("General Meta signup webhook subscription failed tenant=%s: %s", tenant_id, exc)

    _save_tenant_setting(db, tenant_id, "facebook_access_token", page_token, is_secret=True)
    _save_tenant_setting(db, tenant_id, "facebook_page_id", payload.page_id)
    _save_tenant_setting(db, tenant_id, "meta_business_access_token", access_token, is_secret=True)
    _save_shared_meta_app_credentials(db, tenant_id)

    connected_instagram = bool(ig_account_id)
    if connected_instagram:
        _save_tenant_setting(db, tenant_id, "instagram_access_token", page_token, is_secret=True)
        _save_tenant_setting(db, tenant_id, "instagram_page_id", ig_account_id)

    if ad_account:
        _stamp_meta_ads_connected(db, tenant_id, ad_account["id"])
        _save_tenant_setting(db, tenant_id, "meta_ads_access_token", access_token, is_secret=True)
        _save_tenant_setting(db, tenant_id, "meta_ads_account_id", ad_account["id"])
        _save_tenant_setting(db, tenant_id, "meta_ads_account_name", ad_account.get("name") or ad_account["id"])
        _save_tenant_setting(db, tenant_id, "meta_ads_status", "configured")
        _stamp_connection_source(db, tenant_id, "meta_ads", "embedded")
    if catalog:
        _save_tenant_setting(db, tenant_id, "meta_catalog_id", catalog["id"])
        _save_tenant_setting(db, tenant_id, "meta_catalog_name", catalog.get("name") or catalog["id"])

    _save_tenant_setting(db, tenant_id, "facebook_status", "live" if subscribed else "configured")
    _stamp_connection_source(db, tenant_id, "facebook", "embedded")
    if connected_instagram:
        _save_tenant_setting(db, tenant_id, "instagram_status", "live" if subscribed else "configured")
        _stamp_connection_source(db, tenant_id, "instagram", "embedded")
    if page.get("name"):
        _save_tenant_setting(db, tenant_id, "facebook_page_name", page["name"])
    if ig_account.get("username"):
        _save_tenant_setting(db, tenant_id, "instagram_username", ig_account["username"])
    _save_tenant_setting(db, tenant_id, "meta_connected_at", datetime.now(timezone.utc).isoformat())
    db.table("app_settings").delete().eq("tenant_id", tenant_id).in_("key", list(_META_BUSINESS_ONBOARDING_KEYS)).execute()

    from app.config_dynamic import invalidate_cache
    invalidate_cache()
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.meta_business_login_connected",
        target_type="channel",
        target_id="facebook",
        metadata={
            "page_id": payload.page_id,
            "instagram_connected": connected_instagram,
            "ad_account_id": ad_account.get("id") if ad_account else None,
            "catalog_id": catalog.get("id") if catalog else None,
            "subscribed": subscribed,
        },
    )
    return {
        "success": True,
        "page_name": page.get("name"),
        "page_id": payload.page_id,
        "instagram_connected": connected_instagram,
        "ad_account_id": ad_account.get("id") if ad_account else None,
        "catalog_id": catalog.get("id") if catalog else None,
        "subscribed": subscribed,
    }


@router.post("/meta/unified-signup/complete")
async def complete_unified_meta_signup(
    payload: UnifiedMetaSignupCompleteRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    """Persist the validated WhatsApp, Messenger, Instagram and ads connection."""
    from app.services.meta_cloud import discover_business_login_assets, register_phone_number, request_coexistence_sync, verify_waba_phone_number

    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    access_token = _get_setting_value(db, tenant_id, "meta_business_onboarding_token")
    session_id = _get_setting_value(db, tenant_id, "meta_business_onboarding_session_id")
    expires_at = _get_setting_value(db, tenant_id, "meta_business_onboarding_expires_at")
    waba_id = _get_setting_value(db, tenant_id, "meta_business_onboarding_waba_id")
    phone_number_id = _get_setting_value(db, tenant_id, "meta_business_onboarding_phone_number_id")
    _get_setting_value(db, tenant_id, "meta_business_onboarding_business_id")
    is_coexistence = _get_setting_value(db, tenant_id, "meta_business_onboarding_is_coexistence") == "true"
    if not access_token or not session_id or not expires_at or not waba_id or not phone_number_id or payload.session_id != session_id:
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.") from exc
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.")

    assets = await discover_business_login_assets(access_token)
    pages_by_id = {page.get("id"): page for page in assets.get("pages", []) if page.get("id")}
    ads_by_id = {account.get("id"): account for account in assets.get("ad_accounts", []) if account.get("id")}
    page = pages_by_id.get(payload.page_id) if payload.page_id else None
    if payload.page_id and not page:
        raise HTTPException(status_code=400, detail="Select a Facebook Page that was granted during this Meta signup.")
    if page and not page.get("access_token"):
        raise HTTPException(status_code=400, detail="Meta did not issue a token for that Page. Reconnect and grant the Page to Anril.")
    ad_account = ads_by_id.get(payload.ad_account_id) if payload.ad_account_id else None
    if payload.ad_account_id and not ad_account:
        raise HTTPException(status_code=400, detail="Select an ad account that was granted during this Meta signup.")
    if not await verify_waba_phone_number(waba_id, phone_number_id, access_token):
        raise HTTPException(status_code=400, detail="The WhatsApp number was not granted for this Meta business signup.")
    existing_phone = (
        db.table("phone_numbers")
        .select("tenant_id")
        .eq("meta_phone_number_id", phone_number_id)
        .maybe_single()
        .execute()
    )
    # maybe_single() returns None outright when the number is new, not a row with data=None.
    existing_phone_row = (existing_phone.data or {}) if existing_phone else {}
    if existing_phone_row and existing_phone_row.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=409, detail="This WhatsApp number is already connected to another Anril workspace.")

    ig_account = (page.get("instagram_business_account") or {}) if page else {}
    ig_account_id = ig_account.get("id")
    claims = [
        {"asset_type": "whatsapp_business_account", "asset_id": waba_id},
        {"asset_type": "whatsapp_phone_number", "asset_id": phone_number_id},
    ]
    if page:
        claims.insert(0, {"asset_type": "facebook_page", "asset_id": payload.page_id})
    if ig_account_id:
        claims.insert(1, {"asset_type": "instagram_account", "asset_id": ig_account_id})
    if ad_account:
        claims.append({"asset_type": "ad_account", "asset_id": ad_account["id"]})
    _claim_business_assets(db, tenant_id, claims)

    if not is_coexistence:
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        registration = await register_phone_number(phone_number_id, access_token, pin)
        if registration.get("error"):
            logger.warning("Unified Meta signup phone registration failed tenant=%s: %s", tenant_id, registration["error"])
    else:
        # Number is already registered on the phone's WhatsApp Business app —
        # request Meta's SMB App Data API backfill instead (see meta_cloud.py).
        await request_coexistence_sync(phone_number_id, access_token)

    subscribed_whatsapp = False
    subscribed_page = False
    display_phone = None
    business_name = None
    try:
        async with httpx.AsyncClient() as client:
            waba_response = await client.post(
                f"https://graph.facebook.com/v21.0/{waba_id}/subscribed_apps",
                params={"access_token": access_token},
                timeout=10.0,
            )
            subscribed_whatsapp = bool(waba_response.json().get("success", False))
            phone_response = await client.get(
                f"https://graph.facebook.com/v21.0/{phone_number_id}",
                params={"fields": "display_phone_number,verified_name", "access_token": access_token},
                timeout=10.0,
            )
            phone_data = phone_response.json()
            display_phone = phone_data.get("display_phone_number")
            business_name = phone_data.get("verified_name")
            if page:
                page_response = await client.post(
                    f"https://graph.facebook.com/v25.0/{payload.page_id}/subscribed_apps",
                    params={
                        "subscribed_fields": "messages,messaging_postbacks,message_deliveries,message_reads,messaging_referrals",
                        "access_token": page["access_token"],
                    },
                    timeout=10.0,
                )
                subscribed_page = bool(page_response.json().get("success", False))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Unified Meta signup webhook setup failed tenant=%s: %s", tenant_id, exc)

    # Same rule as whatsapp_embedded_signup: the row decides whether the
    # tenant-level sender follows this number or stays on the incumbent.
    holds_primary = True
    if display_phone:
        holds_primary = _upsert_onboarded_phone_number(
            db,
            tenant_id,
            number=display_phone,
            display_name=business_name or "WhatsApp Primary",
            meta_phone_number_id=phone_number_id,
            claim_primary=False,
        )

    settings_to_save = [
        ("meta_access_token", access_token, True),
        ("meta_waba_id", waba_id, False),
        ("meta_business_access_token", access_token, True),
        ("whatsapp_status", "live" if subscribed_whatsapp else "configured", False),
        ("whatsapp_connection_source", "embedded", False),
    ]
    if holds_primary:
        settings_to_save.append(("meta_phone_number_id", phone_number_id, False))
    if page:
        settings_to_save += [
            ("facebook_access_token", page["access_token"], True),
            ("facebook_page_id", payload.page_id, False),
            ("facebook_status", "live" if subscribed_page else "configured", False),
            ("facebook_connection_source", "embedded", False),
        ]
    for key, value, is_secret in settings_to_save:
        if value:
            _save_tenant_setting(db, tenant_id, key, value, is_secret=is_secret)
    _save_shared_meta_app_credentials(db, tenant_id)

    connected_instagram = bool(ig_account_id)
    if connected_instagram:
        _save_tenant_setting(db, tenant_id, "instagram_access_token", page["access_token"], is_secret=True)
        _save_tenant_setting(db, tenant_id, "instagram_page_id", ig_account_id)
        _save_tenant_setting(db, tenant_id, "instagram_status", "live" if subscribed_page else "configured")
        _stamp_connection_source(db, tenant_id, "instagram", "embedded")
    if ad_account:
        _stamp_meta_ads_connected(db, tenant_id, ad_account["id"])
        _save_tenant_setting(db, tenant_id, "meta_ads_access_token", access_token, is_secret=True)
        _save_tenant_setting(db, tenant_id, "meta_ads_account_id", ad_account["id"])
        _save_tenant_setting(db, tenant_id, "meta_ads_account_name", ad_account.get("name") or ad_account["id"])
        _save_tenant_setting(db, tenant_id, "meta_ads_status", "configured")
        _stamp_connection_source(db, tenant_id, "meta_ads", "embedded")
    if page and page.get("name"):
        _save_tenant_setting(db, tenant_id, "facebook_page_name", page["name"])
    if ig_account.get("username"):
        _save_tenant_setting(db, tenant_id, "instagram_username", ig_account["username"])
    if holds_primary:
        if display_phone:
            _save_tenant_setting(db, tenant_id, "meta_phone_display", display_phone.strip())
        if business_name:
            _save_tenant_setting(db, tenant_id, "meta_verified_name", business_name)
    _save_tenant_setting(db, tenant_id, "meta_connected_at", datetime.now(timezone.utc).isoformat())
    db.table("app_settings").delete().eq("tenant_id", tenant_id).in_("key", list(_META_BUSINESS_ONBOARDING_KEYS)).execute()

    from app.config_dynamic import invalidate_cache
    invalidate_cache()
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.meta_unified_signup_connected",
        target_type="channel",
        target_id="meta",
        metadata={
            "waba_id": waba_id,
            "page_id": payload.page_id,
            "instagram_connected": connected_instagram,
            "ad_account_id": ad_account.get("id") if ad_account else None,
            "whatsapp_subscribed": subscribed_whatsapp,
            "page_subscribed": subscribed_page,
        },
    )
    return {
        "success": True,
        "phone_number": display_phone,
        "page_id": payload.page_id,
        "instagram_connected": connected_instagram,
        "ad_account_id": ad_account.get("id") if ad_account else None,
    }


@router.post("/meta/ads-signup/start")
async def start_meta_ads_signup(
    payload: MetaAdsSignupStartRequest,
    ctx: dict = Depends(require_settings_manage),
):
    """Exchange an ads-only Login code and list the ad accounts it granted.

    Deliberately separate from `/facebook/business-login/start`, which rejects any
    signup that granted no Page — the ads-only Login configuration grants exactly
    one asset type and never includes a Page. The token stays server-side while the
    browser picks which granted account to connect.
    """
    from app.services.meta_cloud import exchange_embedded_signup_code, discover_business_login_assets

    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    exchange = await exchange_embedded_signup_code(payload.code)
    access_token = exchange["access_token"]
    assets = await discover_business_login_assets(access_token)
    public_assets = _public_meta_ads_assets(assets)
    if not public_assets["ad_accounts"]:
        raise HTTPException(
            status_code=400,
            detail="No ad account was granted — select an ad account during Meta signup.",
        )

    session_id = str(uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    _save_tenant_setting(db, tenant_id, "meta_ads_onboarding_token", access_token, is_secret=True)
    _save_tenant_setting(db, tenant_id, "meta_ads_onboarding_session_id", session_id, is_secret=True)
    _save_tenant_setting(db, tenant_id, "meta_ads_onboarding_expires_at", expires_at)

    return {"session_id": session_id, **public_assets}


@router.post("/meta/ads-signup/complete")
async def complete_meta_ads_signup(
    payload: MetaAdsSignupCompleteRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    """Validate the chosen ad account against the staged token, then connect Meta Ads.

    Nothing here touches WhatsApp, Page or Instagram settings: an ads-only tenant has
    none, and a tenant that already connected them must keep what they have.
    """
    from app.services.meta_cloud import discover_business_login_assets

    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    access_token = _get_setting_value(db, tenant_id, "meta_ads_onboarding_token")
    session_id = _get_setting_value(db, tenant_id, "meta_ads_onboarding_session_id")
    expires_at = _get_setting_value(db, tenant_id, "meta_ads_onboarding_expires_at")
    if not access_token or not session_id or not expires_at or payload.session_id != session_id:
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.") from exc
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This Meta signup session has expired. Start the connection again.")

    assets = await discover_business_login_assets(access_token)
    ads_by_id = {account.get("id"): account for account in assets.get("ad_accounts", []) if account.get("id")}
    ad_account = ads_by_id.get(payload.ad_account_id)
    if not ad_account:
        raise HTTPException(status_code=400, detail="Select an ad account that was granted during this Meta signup.")

    _claim_business_assets(db, tenant_id, [{"asset_type": "ad_account", "asset_id": ad_account["id"]}])

    _stamp_meta_ads_connected(db, tenant_id, ad_account["id"])
    _save_tenant_setting(db, tenant_id, "meta_ads_access_token", access_token, is_secret=True)
    _save_tenant_setting(db, tenant_id, "meta_ads_account_id", ad_account["id"])
    _save_tenant_setting(db, tenant_id, "meta_ads_account_name", ad_account.get("name") or ad_account["id"])
    _save_tenant_setting(db, tenant_id, "meta_ads_status", "configured")
    _stamp_connection_source(db, tenant_id, "meta_ads", "embedded")
    db.table("app_settings").delete().eq("tenant_id", tenant_id).in_("key", list(_META_ADS_ONBOARDING_KEYS)).execute()

    from app.config_dynamic import invalidate_cache
    invalidate_cache()
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.meta_ads_signup_connected",
        target_type="channel",
        target_id="meta_ads",
        metadata={"ad_account_id": ad_account["id"]},
    )
    return {
        "success": True,
        "ad_account_id": ad_account["id"],
        "ad_account_name": ad_account.get("name") or ad_account["id"],
    }


@router.post("/facebook/embedded-signup")
async def facebook_embedded_signup(
    payload: FacebookEmbeddedSignupRequest,
    ctx: dict = Depends(require_settings_manage),
    user: dict = Depends(get_current_user),
):
    """Finish Facebook Login for Business signup for Messenger + linked Instagram:
    exchange the popup's code for a user token, find the granted Page, subscribe it
    to webhooks, and save Page/Instagram credentials — the automated replacement for
    manually pasting facebook_access_token/page_id and instagram_access_token/page_id."""
    from app.services.meta_cloud import exchange_embedded_signup_code

    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    exchange = await exchange_embedded_signup_code(payload.code)
    user_token = exchange["access_token"]

    async with httpx.AsyncClient() as client:
        pages_r = await client.get(
            "https://graph.facebook.com/v21.0/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account",
                "access_token": user_token,
            },
            timeout=10.0,
        )
    pages_data = pages_r.json()
    if "error" in pages_data:
        raise HTTPException(status_code=400, detail=pages_data["error"].get("message", "Could not list granted Facebook Pages"))
    pages = pages_data.get("data", [])
    if not pages:
        raise HTTPException(status_code=400, detail="No Facebook Page was granted — select a Page during signup.")

    # Only one Page/tenant is supported today — same single-asset shape as the WhatsApp flow.
    page = pages[0]
    if len(pages) > 1:
        logger.info(f"Facebook embedded signup: tenant={tenant_id} granted {len(pages)} pages, connecting first ({page.get('name')}) only")

    page_id = page["id"]
    page_token = page["access_token"]
    ig_account = page.get("instagram_business_account")

    sub_fields = "messages,messaging_postbacks,message_deliveries,message_reads,messaging_referrals"
    async with httpx.AsyncClient() as client:
        sub_r = await client.post(
            f"https://graph.facebook.com/v21.0/{page_id}/subscribed_apps",
            params={"subscribed_fields": sub_fields, "access_token": page_token},
            timeout=10.0,
        )
    sub_data = sub_r.json()
    subscribed = sub_data.get("success", False)
    if "error" in sub_data:
        logger.warning(f"Facebook embedded signup: subscribed_apps failed tenant={tenant_id}: {sub_data['error']}")

    connected_instagram = bool(ig_account and ig_account.get("id"))
    creds_to_save = {
        "facebook_access_token": page_token,
        "facebook_page_id": page_id,
    }
    if connected_instagram:
        # Page-linked Instagram messaging is authenticated with the same Page access
        # token (Meta's Messenger Platform for Instagram) — not a separate IG token.
        creds_to_save["instagram_access_token"] = page_token
        creds_to_save["instagram_page_id"] = ig_account["id"]

    for key, value in creds_to_save.items():
        if not value:
            continue
        db.table("app_settings").upsert({
            "tenant_id": tenant_id,
            "key": key,
            "value": value,
            "is_secret": key.endswith("_access_token"),
            "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()
    _save_shared_meta_app_credentials(db, tenant_id)

    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": "facebook_status",
        "value": "live",
        "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()
    _stamp_connection_source(db, tenant_id, "facebook", "embedded")
    if connected_instagram:
        db.table("app_settings").upsert({
            "tenant_id": tenant_id,
            "key": "instagram_status",
            "value": "live",
            "is_secret": False,
            "updated_at": "now()",
        }, on_conflict="tenant_id,key").execute()
        _stamp_connection_source(db, tenant_id, "instagram", "embedded")

    from app.config_dynamic import invalidate_cache
    invalidate_cache()

    logger.info(f"Facebook embedded signup: tenant={tenant_id} page={page.get('name')} instagram_connected={connected_instagram} subscribed={subscribed}")
    record_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.get("user_id"),
        actor_role="tenant_user",
        action="settings.facebook_embedded_signup_connected",
        target_type="channel",
        target_id="facebook",
        metadata={"channel": "facebook", "page_id": page_id, "subscribed": subscribed, "instagram_connected": connected_instagram},
    )

    return {
        "success": True,
        "page_name": page.get("name"),
        "page_id": page_id,
        "subscribed": subscribed,
        "instagram_connected": connected_instagram,
    }


@router.get("/inbox-config")
async def get_inbox_config_route(ctx: dict = Depends(require_settings_read)):
    tenant_id = ctx["tenant_id"]
    return get_inbox_config(tenant_id)


@router.patch("/inbox-config")
async def patch_inbox_config(payload: InboxConfigUpdate, ctx: dict = Depends(require_settings_manage)):
    tenant_id = ctx["tenant_id"]
    current = get_inbox_config(tenant_id)
    patch = payload.model_dump(exclude_none=True)
    valid_segs = {"A", "B", "C"}
    if "segments" in patch:
        bad = [s for s in patch["segments"] if s not in valid_segs]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid segments: {bad}")
    valid_ch = {"whatsapp", "instagram", "facebook", "telegram"}
    if "channels" in patch:
        bad = [c for c in patch["channels"] if c not in valid_ch]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid channels: {bad}")
    valid_tr = {"A", "B", "C", "D", "F"}
    if "triggers" in patch:
        bad = [t for t in patch["triggers"] if t not in valid_tr]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid triggers: {bad}")
    merged = {**current, **patch}
    save_inbox_config(tenant_id, merged)
    return merged


@router.get("/ai-auto-reply")
async def get_ai_auto_reply_state(tenant_id: str = Depends(get_tenant_id)):
    """Master AI switch, readable by any signed-in teammate (chat screens grey out their
    per-lead toggle when it is off). Same rule as the reply gate: only the literal "false" is off."""
    from app.config_dynamic import get_setting
    return {"enabled": get_setting("ai_auto_reply_enabled", fallback="true", tenant_id=tenant_id) != "false"}


@router.get("/telecalling-config")
async def get_telecalling_config_route(ctx: dict = Depends(require_settings_read)):
    tenant_id = ctx["tenant_id"]
    return get_telecalling_config(tenant_id)


@router.patch("/telecalling-config")
async def patch_telecalling_config(payload: TelecallingConfigUpdate, ctx: dict = Depends(require_settings_manage)):
    tenant_id = ctx["tenant_id"]
    current = get_telecalling_config(tenant_id)
    patch = payload.model_dump(exclude_none=True)
    valid_segs = {"A", "B", "C"}
    if "segments" in patch:
        bad = [s for s in patch["segments"] if s not in valid_segs]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid segments: {bad}")
    valid_ch = {"whatsapp", "instagram", "facebook", "telegram"}
    if "channels" in patch:
        bad = [c for c in patch["channels"] if c not in valid_ch]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid channels: {bad}")
    if "max_call_attempts" in patch:
        patch["max_call_attempts"] = max(1, min(int(patch["max_call_attempts"]), 20))
    if "assignment_mode" in patch:
        if patch["assignment_mode"] not in ("push", "pull"):
            raise HTTPException(status_code=400, detail="Invalid assignment mode")
    merged = {**current, **patch}
    merged.pop("eval_daily_cap", None)
    save_telecalling_config(tenant_id, merged)
    return merged


def _walk_packages(nodes: list[dict]):
    """Yield (node, is_leaf) for every package node in the tree, depth-first."""
    for n in nodes:
        options = n.get("options") or []
        yield n, not options
        yield from _walk_packages(options)


def _validate_packages(packages: list[dict]) -> None:
    keys: list[str] = []
    for node, is_leaf in _walk_packages(packages):
        keys.append(node["key"])
        if not node["name"].strip():
            raise HTTPException(status_code=400, detail="Package name is required")
        if is_leaf and node["amount_paise"] < 1:
            raise HTTPException(status_code=400, detail="Package amount must be >= 1 paise")
        for addon in node.get("addons") or []:
            keys.append(addon["key"])
            if not addon["name"].strip():
                raise HTTPException(status_code=400, detail="Addon name is required")
            if addon["amount_paise"] < 0:
                raise HTTPException(status_code=400, detail="Addon amount must be >= 0")
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=400, detail="Duplicate package or addon keys")


def _has_active_package(packages: list[dict]) -> bool:
    """At least one leaf package the AI could actually offer and sell -- an
    enabled tenant with every package switched off would show WhatsApp buttons
    that lead nowhere, which is worse than staying disabled."""
    return any(node.get("active", True) for node, is_leaf in _walk_packages(packages) if is_leaf)


def _check_form_fits_astrotamil(tenant_id: str, fields: list[dict]) -> None:
    """A client connected to AstroTamil needs a form that can collect everything AstroTamil asks
    for. Refusing here beats finding out when a paid question is turned away. Other clients are
    not checked."""
    if not astro_bridge.is_connected(tenant_id):
        return
    missing = astro_bridge.missing_form_fields(fields)
    if not missing:
        return
    detail = f"AstroTamil needs these details in the form: {', '.join(missing)}."
    unrecognised = astro_bridge.unrecognised_form_keys(fields)
    if unrecognised:
        detail += f" No AstroTamil detail matches the key(s): {', '.join(unrecognised)}."
    raise HTTPException(status_code=400, detail=detail)


@router.get("/intake-config")
async def get_intake_config_route(ctx: dict = Depends(require_services_read)):
    return get_intake_config(ctx["tenant_id"])


@router.patch("/intake-config")
async def patch_intake_config(
    payload: IntakeConfigUpdate,
    background_tasks: BackgroundTasks,
    ctx: dict = Depends(require_services_manage),
):
    tenant_id = ctx["tenant_id"]
    current = get_intake_config(tenant_id)
    patch = payload.model_dump(exclude_none=True)
    if "amount_paise" in patch and patch["amount_paise"] < 0:
        raise HTTPException(status_code=400, detail="amount_paise must be >= 0")
    if "gst_percent" in patch and not 0 <= patch["gst_percent"] <= MAX_GST_PERCENT:
        raise HTTPException(status_code=400, detail=f"gst_percent must be between 0 and {MAX_GST_PERCENT}")
    if "fields" in patch:
        keys = [f["key"] for f in patch["fields"]]
        if len(keys) != len(set(keys)):
            raise HTTPException(status_code=400, detail="Duplicate field keys")
    if "packages" in patch:
        _validate_packages(patch["packages"])
    if patch.get("enabled"):
        # Trigger description / offer message are dead fields (only the bypassed
        # legacy route_intake ever read them) -- enabling only ever needs a real,
        # active package to sell. "packages" may be absent from this patch (e.g.
        # a fields-only save on an already-configured tenant), so fall back to
        # the currently stored tree; the legacy single amount_paise fee is kept
        # as a migration-only fallback for tenants who never moved to packages.
        effective_packages = patch["packages"] if "packages" in patch else current.get("packages")
        if not (_has_active_package(effective_packages or []) or current.get("amount_paise")):
            raise HTTPException(status_code=400, detail="Add at least one active package before enabling")
    if "service_noun" in patch and not patch["service_noun"].strip():
        raise HTTPException(status_code=400, detail="service_noun cannot be blank")
    merged = {**current, **patch}
    if ("fields" in patch or patch.get("enabled")) and merged.get("enabled"):
        _check_form_fits_astrotamil(tenant_id, merged.get("fields") or [])
    save_intake_config(tenant_id, merged)
    from app.services.consistency import run_check_safely
    background_tasks.add_task(run_check_safely, tenant_id)
    return merged
