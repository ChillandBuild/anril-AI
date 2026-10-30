import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, Optional[str]]] = {}
_TTL = 60.0
# Bootstrapping default for get_setting/save_setting when called without an explicit
# tenant_id (the two genuinely-global reads: public_base_url + webhook verify fallback).
# This is NOT a privileged tenant — all credentials resolve per-tenant from app_settings.
_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Settings whose value is masked when shown (app_settings.is_secret). One list for every
# save path: the operator console once kept its own shorter copy and saved Razorpay
# secrets unmasked.
SECRET_SETTING_KEYS = frozenset({
    "sarvam_api_key",
    "groq_api_key",
    "gemini_api_key",
    "openai_api_key",
    "jina_api_key",
    "meta_access_token",
    "meta_webhook_verify_token",
    "meta_app_secret",
    "telecmi_secret",
    "telecmi_agent_password",
    "telecmi_webhook_secret",
    "razorpay_key_secret",
    "razorpay_webhook_secret",
    "razorpay_oauth_access_token",
    "razorpay_oauth_refresh_token",
    "razorpay_oauth_public_token",
    "razorpay_oauth_state",
    "telegram_bot_token",
    "telegram_webhook_secret",
    "instagram_access_token",
    "instagram_app_secret",
    "facebook_access_token",
    "meta_ads_access_token",
    "astro_bridge_api_key",
    "astro_bridge_secret",
    "indiamart_ingest_token",
    "justdial_ingest_token",
    "auto_messages_ingest_token",
    "bulk9_api_key",
    "bulk9_webhook_secret",
})


class SettingReadError(RuntimeError):
    """The settings database could not be read (as opposed to the key being unset)."""


def get_setting(key: str, fallback: Optional[str] = None, tenant_id: Optional[str] = None) -> Optional[str]:
    """Read from cache → app_settings table → fallback. No env-var fallback: every
    tenant (including the first) configures its own credentials in app_settings."""
    return _load_setting(key, fallback, tenant_id, strict=False)


def get_setting_strict(key: str, fallback: Optional[str] = None, tenant_id: Optional[str] = None) -> Optional[str]:
    """Like get_setting, but a failed database read raises SettingReadError instead of quietly
    looking like "not set". For callers where acting on a wrong default is worse than skipping
    (e.g. the idle sweep closing deals on a 30-day default for a tenant who chose 90)."""
    return _load_setting(key, fallback, tenant_id, strict=True)


def _load_setting(key: str, fallback: Optional[str], tenant_id: Optional[str], *, strict: bool) -> Optional[str]:
    now = time.monotonic()
    resolved_tenant_id = tenant_id or _DEFAULT_TENANT_ID
    cache_key = f"{resolved_tenant_id}:{key}"
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    from app.db.supabase import get_supabase
    db = get_supabase()

    value: Optional[str] = None
    read_ok = False
    # One immediate retry: Supabase's REST endpoint occasionally drops a pooled
    # keep-alive connection ("Server disconnected") on the first request after
    # it's been idle. That's not "not configured" — retrying once resolves it
    # without ever surfacing an error.
    for attempt in range(2):
        try:
            row = (
                db.table("app_settings")
                .select("value")
                .eq("tenant_id", resolved_tenant_id)
                .eq("key", key)
                .maybe_single()
                .execute()
            )
            if row and row.data:
                value = row.data.get("value")
            read_ok = True
            break
        except Exception as e:
            if attempt == 0:
                continue
            logger.warning(f"get_setting({key}, tenant_id={resolved_tenant_id}) DB read failed: {e}")

    if strict and not read_ok:
        raise SettingReadError(f"could not read setting {key} for tenant {resolved_tenant_id}")
    if not value:
        value = fallback

    # Only cache a confirmed read. Caching a failed read's None would make a
    # transient outage look like "not configured" for the next _TTL seconds,
    # even after the DB recovers.
    if read_ok:
        _CACHE[cache_key] = (now, value)
    return value


def save_setting(key: str, value: str, tenant_id: Optional[str] = None) -> None:
    """Upsert a key/value into app_settings and invalidate the local cache."""
    resolved_tenant_id = tenant_id or _DEFAULT_TENANT_ID
    try:
        from app.db.supabase import get_supabase
        db = get_supabase()
        db.table("app_settings").upsert(
            {"key": key, "value": value, "tenant_id": resolved_tenant_id, "is_secret": key in SECRET_SETTING_KEYS},
            on_conflict="key,tenant_id",
        ).execute()
    except Exception as e:
        logger.warning(f"save_setting({key}, tenant_id={resolved_tenant_id}) DB write failed: {e}")
        return
    cache_key = f"{resolved_tenant_id}:{key}"
    _CACHE[cache_key] = (time.monotonic(), value)


def require_tenant_setting(key: str, tenant_id: Optional[str]) -> str:
    """Like get_setting, but with no fallback of any kind -- raises if this tenant hasn't
    explicitly configured the key. Used for per-tenant AI provider credentials, where each
    provider must be independently configured per client with no shared/platform default."""
    value = get_setting(key, tenant_id=tenant_id)
    if not value:
        raise RuntimeError(f"{key} not configured for this client")
    return value


def invalidate_cache(key: Optional[str] = None) -> None:
    if key:
        keys_to_remove = [cache_key for cache_key in _CACHE if cache_key.endswith(f":{key}")]
        for cache_key in keys_to_remove:
            _CACHE.pop(cache_key, None)
    else:
        _CACHE.clear()
