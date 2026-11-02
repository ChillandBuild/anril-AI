# backend/app/services/razorpay_oauth.py
"""Razorpay OAuth ("Connect with Razorpay"): Anril is a Razorpay Technology Partner, and a
tenant authorises Anril's partner app on its own Razorpay account instead of pasting API
keys. Docs: razorpay.com/docs/partners/technology-partners/onboard-businesses/integrate-oauth

Everything per-tenant lives in app_settings like every other credential. The partner app's
client id/secret, redirect URI and webhook secret are Anril's, not a tenant's, so they come
from env (config.py), the same way the shared Meta app's secret does.

Token lifetimes: access ~90 days, refresh 180 days. A refresh ROTATES the refresh token --
the old one dies the moment the new one is issued -- so two workers refreshing at once must
not both write (see refresh_access_token)."""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings as env_settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://auth.razorpay.com/authorize"
TOKEN_URL = "https://auth.razorpay.com/token"
REVOKE_URL = "https://auth.razorpay.com/revoke"
# Payment links need write access; nothing in Anril touches RazorpayX.
SCOPE = "read_write"
_STATE_TTL = timedelta(minutes=10)
# Refresh a week early: a token that dies mid-quote fails a live customer's payment link.
_REFRESH_WHEN_LEFT = timedelta(days=7)
# Used only if Razorpay ever omits expires_in: 0 would mean "expired now" and a refresh (and
# rotation) on every single API call. Too short is harmless -- a 401 forces a refresh anyway.
_FALLBACK_TTL = timedelta(days=30)

KEY_ACCESS = "razorpay_oauth_access_token"
KEY_REFRESH = "razorpay_oauth_refresh_token"
KEY_PUBLIC = "razorpay_oauth_public_token"
KEY_ACCOUNT = "razorpay_oauth_account_id"
KEY_EXPIRES = "razorpay_oauth_expires_at"
KEY_STATE = "razorpay_oauth_state"
KEY_STATE_EXPIRES = "razorpay_oauth_state_expires_at"
TOKEN_KEYS = (KEY_ACCESS, KEY_REFRESH, KEY_PUBLIC, KEY_ACCOUNT, KEY_EXPIRES)
ALL_KEYS = TOKEN_KEYS + (KEY_STATE, KEY_STATE_EXPIRES)
SECRET_KEYS = frozenset({KEY_ACCESS, KEY_REFRESH, KEY_PUBLIC, KEY_STATE})
# Only this module writes these; the generic settings PATCH refuses them (a tenant that could
# set its own account id could have another tenant's webhooks routed to it).
KEY_PREFIX = "razorpay_oauth_"


class RazorpayOAuthError(Exception):
    """A connect step failed. `str(e)` is safe to show the tenant; `status` is the HTTP code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def is_configured() -> bool:
    return bool(
        env_settings.razorpay_oauth_client_id
        and env_settings.razorpay_oauth_client_secret
        and env_settings.razorpay_oauth_redirect_uri
    )


def _client_credentials() -> tuple[str, str]:
    if not is_configured():
        raise RazorpayOAuthError("Connect with Razorpay isn't set up on this server yet.", status=503)
    return env_settings.razorpay_oauth_client_id, env_settings.razorpay_oauth_client_secret


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read(db, tenant_id: str, keys) -> dict[str, str]:
    rows = (
        db.table("app_settings").select("key,value")
        .eq("tenant_id", tenant_id).in_("key", list(keys))
        .execute()
    ).data or []
    return {r["key"]: r["value"] for r in rows if r.get("value")}


def _write(db, tenant_id: str, values: dict[str, str]) -> None:
    now = _now().isoformat()
    db.table("app_settings").upsert(
        [
            {"tenant_id": tenant_id, "key": k, "value": v, "is_secret": k in SECRET_KEYS, "updated_at": now}
            for k, v in values.items()
        ],
        on_conflict="tenant_id,key",
    ).execute()


def _delete(db, tenant_id: str, keys) -> None:
    db.table("app_settings").delete().eq("tenant_id", tenant_id).in_("key", list(keys)).execute()


def _invalidate() -> None:
    from app.config_dynamic import invalidate_cache
    invalidate_cache()


def start(db, tenant_id: str) -> str:
    """Stage a single-use state for this tenant and return the Razorpay consent URL.

    The state is what ties the browser coming back from Razorpay to the tenant that left:
    /complete is authenticated, so the tenant comes from the JWT, and the state proves this
    tenant (not someone who planted a link) started this very flow in the last 10 minutes."""
    client_id, _ = _client_credentials()
    state = secrets.token_urlsafe(32)
    _write(db, tenant_id, {KEY_STATE: state, KEY_STATE_EXPIRES: (_now() + _STATE_TTL).isoformat()})
    return f"{AUTHORIZE_URL}?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": env_settings.razorpay_oauth_redirect_uri,
        "scope": SCOPE,
        "state": state,
    })


async def _token_request(body: dict) -> dict:
    client_id, client_secret = _client_credentials()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                TOKEN_URL, json={"client_id": client_id, "client_secret": client_secret, **body},
            )
    except httpx.HTTPError as e:
        raise RazorpayOAuthError("Couldn't reach Razorpay. Please try again.", status=502) from e
    if not resp.is_success:
        # The error body carries no token; log it so a misconfigured redirect URI is diagnosable.
        logger.warning("Razorpay token request (%s) failed: %s %s", body.get("grant_type"), resp.status_code, resp.text[:300])
        raise RazorpayOAuthError("Razorpay didn't accept the connection. Please start again.", status=502)
    data = resp.json()
    if not data.get("access_token") or not data.get("refresh_token"):
        raise RazorpayOAuthError("Razorpay returned an incomplete response. Please start again.", status=502)
    return data


def _token_values(data: dict) -> dict[str, str]:
    ttl = timedelta(seconds=int(data["expires_in"])) if data.get("expires_in") else _FALLBACK_TTL
    values = {
        KEY_ACCESS: data["access_token"],
        KEY_REFRESH: data["refresh_token"],
        KEY_EXPIRES: (_now() + ttl).isoformat(),
    }
    if data.get("public_token"):
        values[KEY_PUBLIC] = data["public_token"]
    return values


async def complete(db, tenant_id: str, code: str, state: str) -> dict:
    """Validate the state, swap the code for tokens and store them. Returns {account_id}."""
    staged = _read(db, tenant_id, (KEY_STATE, KEY_STATE_EXPIRES))
    expected = staged.get(KEY_STATE)
    expiry = _parse_ts(staged.get(KEY_STATE_EXPIRES))
    matches = bool(expected and state) and hmac.compare_digest(expected.encode(), state.encode())
    expired = not expiry or expiry <= _now()
    # Single-use: a match burns it before the code swap, so a replayed callback URL can't reuse
    # it. A mismatch leaves it, so a planted link with a junk state can't kill a pending connect.
    if matches or expired:
        _delete(db, tenant_id, (KEY_STATE, KEY_STATE_EXPIRES))
    if not matches or expired:
        raise RazorpayOAuthError("This Razorpay connection has expired. Click Connect again.")
    if not code:
        raise RazorpayOAuthError("Razorpay didn't send an authorisation code. Click Connect again.")

    data = await _token_request({
        "grant_type": "authorization_code",
        "redirect_uri": env_settings.razorpay_oauth_redirect_uri,
        "code": code,
        "mode": env_settings.razorpay_oauth_mode,
    })
    account_id = data.get("razorpay_account_id") or ""
    if not account_id:
        await _revoke_quietly(data["access_token"], "access_token")
        raise RazorpayOAuthError("Razorpay didn't say which account was connected. Please start again.", status=502)

    # One Razorpay account, one workspace: the app webhook is routed by account id alone.
    other = (
        db.table("app_settings").select("tenant_id")
        .eq("key", KEY_ACCOUNT).eq("value", account_id).neq("tenant_id", tenant_id)
        .execute()
    ).data
    if other:
        # Don't revoke: the grant is per account+app, so revoking would also cut off the workspace
        # that rightly owns this account (and its revoked webhook would clear that workspace).
        raise RazorpayOAuthError("This Razorpay account is already connected to another Anril workspace.", status=409)

    _delete(db, tenant_id, (KEY_PUBLIC,))  # a reconnect to another account must not keep the old one
    _write(db, tenant_id, {**_token_values(data), KEY_ACCOUNT: account_id})
    _invalidate()
    return {"account_id": account_id}


async def refresh_access_token(db, tenant_id: str) -> str | None:
    """Swap the refresh token for a new pair; returns the access token to use.

    Two workers may refresh the same tenant at once. Razorpay kills the old refresh token the
    moment it issues a new one, so the slower worker either gets an error from Razorpay or
    (if both calls land) must not overwrite the winner's refresh token with its own. Both
    cases fall back to re-reading what the winner stored."""
    stored = _read(db, tenant_id, (KEY_REFRESH,))
    old_refresh = stored.get(KEY_REFRESH)
    if not old_refresh:
        return None
    try:
        data = await _token_request({"grant_type": "refresh_token", "refresh_token": old_refresh})
    except RazorpayOAuthError:
        current = _read(db, tenant_id, (KEY_REFRESH, KEY_ACCESS))
        if current.get(KEY_REFRESH) and current[KEY_REFRESH] != old_refresh:
            return current.get(KEY_ACCESS)  # another worker already refreshed
        raise
    # Compare-and-swap: only the worker whose old token is still stored gets to write.
    claimed = (
        db.table("app_settings")
        .update({"value": data["refresh_token"], "updated_at": _now().isoformat()})
        .eq("tenant_id", tenant_id).eq("key", KEY_REFRESH).eq("value", old_refresh)
        .execute()
    ).data
    if not claimed:
        return _read(db, tenant_id, (KEY_ACCESS,)).get(KEY_ACCESS)
    values = _token_values(data)
    values.pop(KEY_REFRESH)
    # update, not upsert: if the tenant disconnected mid-refresh, recreating the access row would
    # leave an orphan token that silently overrides their pasted keys.
    now = _now().isoformat()
    for key, value in values.items():
        db.table("app_settings").update({"value": value, "updated_at": now}) \
            .eq("tenant_id", tenant_id).eq("key", key).execute()
    _invalidate()
    return data["access_token"]


async def get_access_token(tenant_id: str | None, *, force_refresh: bool = False) -> str | None:
    """The Bearer token for this tenant's Razorpay API calls, or None when the tenant isn't
    connected through OAuth (the caller then falls back to pasted keys).

    Read straight from the DB, not get_setting's 60s per-process cache: after another
    worker refreshes, a cached refresh token here would be a dead one."""
    if not tenant_id:
        return None
    db = get_supabase()
    stored = _read(db, tenant_id, (KEY_ACCESS, KEY_EXPIRES))
    access = stored.get(KEY_ACCESS)
    if not access:
        return None
    expiry = _parse_ts(stored.get(KEY_EXPIRES))
    if not force_refresh and expiry and expiry - _now() > _REFRESH_WHEN_LEFT:
        return access
    try:
        return await refresh_access_token(db, tenant_id) or access
    except RazorpayOAuthError as e:
        if expiry and expiry > _now() and not force_refresh:
            logger.warning("Razorpay token refresh failed tenant=%s (token still valid): %s", tenant_id, e)
            return access
        logger.error("Razorpay token refresh failed tenant=%s: %s", tenant_id, e)
        raise RuntimeError("Razorpay connection expired -- reconnect Razorpay in Settings") from e


async def _revoke_quietly(token: str, token_type_hint: str) -> bool:
    try:
        client_id, client_secret = _client_credentials()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(REVOKE_URL, json={
                "client_id": client_id, "client_secret": client_secret,
                "token_type_hint": token_type_hint, "token": token,
            })
        return resp.is_success
    except Exception as e:
        logger.warning("Razorpay token revoke (%s) failed: %s", token_type_hint, type(e).__name__)
        return False


async def disconnect(db, tenant_id: str) -> None:
    """Revoke at Razorpay (best effort) and forget the tokens. Pasted keys are untouched."""
    stored = _read(db, tenant_id, (KEY_ACCESS, KEY_REFRESH))
    if stored.get(KEY_ACCESS):
        await _revoke_quietly(stored[KEY_ACCESS], "access_token")
    if stored.get(KEY_REFRESH):
        await _revoke_quietly(stored[KEY_REFRESH], "refresh_token")
    clear_tokens(db, tenant_id)


def clear_tokens(db, tenant_id: str) -> None:
    _delete(db, tenant_id, ALL_KEYS)
    _invalidate()


def tenant_for_account(db, account_id: str | None) -> str | None:
    """The one tenant connected to this Razorpay account, or None (unknown or ambiguous)."""
    if not account_id:
        return None
    rows = (
        db.table("app_settings").select("tenant_id")
        .eq("key", KEY_ACCOUNT).eq("value", account_id)
        .execute()
    ).data or []
    tenants = {r["tenant_id"] for r in rows}
    return tenants.pop() if len(tenants) == 1 else None


def connected_after(db, tenant_id: str, unix_ts) -> bool:
    """True when this tenant's current connection was made after `unix_ts` -- a revoked event
    from before then (our own disconnect's, delivered late, or a replay) is about an older grant."""
    try:
        event_at = datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return False
    row = (
        db.table("app_settings").select("updated_at")
        .eq("tenant_id", tenant_id).eq("key", KEY_ACCOUNT).maybe_single()
        .execute()
    )
    connected_at = _parse_ts((row.data or {}).get("updated_at") if row else None)
    return bool(connected_at and connected_at > event_at)


def verify_app_webhook(raw_body: bytes, received_signature: str) -> bool:
    """HMAC-SHA256 of the raw body with the partner app's webhook secret (one for every
    connected merchant, set in the Razorpay dashboard under Applications → Manage Webhook)."""
    secret = env_settings.razorpay_oauth_webhook_secret
    if not secret or not received_signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), received_signature.encode())
