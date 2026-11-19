import logging
import time

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)

_INVALID = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
_UPSTREAM = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Auth service temporarily unavailable. Please retry.",
)
_TOKEN_CACHE: dict[str, tuple[float, dict]] = {}
_TOKEN_CACHE_MAX_SECONDS = 300


def _is_connection_error(e: Exception) -> bool:
    """True for transient transport/connection failures (not bad credentials).

    Covers httpx transport errors plus h2 GOAWAY/ConnectionTerminated, which
    surface as RemoteProtocolError or by class name string in wrapped errors.
    """
    if isinstance(e, (httpx.TransportError, httpx.RemoteProtocolError)):
        return True
    blob = f"{type(e).__name__}: {e}".lower()
    return any(
        s in blob
        for s in ("server disconnected", "connectionterminated", "connection reset", "goaway")
    )


def _user_from_claims(claims: dict) -> dict:
    sub = claims.get("sub")
    if not sub:
        raise _INVALID
    return {"user_id": sub, "email": claims.get("email") or ""}


def _cache_ttl(token: str) -> float:
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        exp = float(claims.get("exp") or 0)
    except Exception:
        exp = 0
    if exp <= 0:
        return time.time() + 60
    return min(exp, time.time() + _TOKEN_CACHE_MAX_SECONDS)


def _get_cached_user(token: str) -> dict | None:
    cached = _TOKEN_CACHE.get(token)
    if not cached:
        return None
    expires_at, user = cached
    if expires_at <= time.time():
        _TOKEN_CACHE.pop(token, None)
        return None
    return user


def _set_cached_user(token: str, user: dict) -> None:
    _TOKEN_CACHE[token] = (_cache_ttl(token), user)


def _verify_local(token: str) -> dict | None:
    """Verify the JWT signature locally (no network). Returns the user on
    success, or None if the token can't be locally verified — the caller then
    falls back to the authoritative remote check so a misconfigured secret or
    a non-HS256 signing key never locks out a valid session."""
    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as e:
        logger.info(f"Local JWT not accepted, falling back to remote: {type(e).__name__}: {e}")
        return None
    return _user_from_claims(claims)


def _verify_remote(token: str) -> dict:
    """Validate via Supabase auth, retrying once on transient connection drops.
    Connection failures -> 503 (not 401) so valid sessions aren't logged out."""
    cached = _get_cached_user(token)
    if cached is not None:
        return cached
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            response = get_supabase().auth.get_user(token)
            user = response.user
            if not user:
                raise _INVALID
            verified = {"user_id": user.id, "email": user.email or ""}
            _set_cached_user(token, verified)
            return verified
        except HTTPException:
            raise
        except Exception as e:
            if _is_connection_error(e):
                last_err = e
                logger.warning(f"Auth upstream connection error (attempt {attempt + 1}/2): {e}")
                continue
            logger.warning(f"Auth failed: {e}")
            raise _INVALID
    logger.error(f"Auth upstream unavailable after retry: {last_err}")
    raise _UPSTREAM


def _is_oauth_client_token(token: str) -> bool:
    """True for a token Supabase's OAuth server issued to a client app (it carries `client_id`).
    Read without checking the signature: this is only ever used to REFUSE a token."""
    try:
        return bool(jwt.decode(token, options={"verify_signature": False}).get("client_id"))
    except jwt.PyJWTError:
        return False


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = credentials.credentials
    if _is_oauth_client_token(token):
        # The token Claude holds is good for the read-only MCP and nothing else. Without this it
        # would also be a full login for this API, writes included. Checked even when MCP_ENABLED
        # is off: turning the MCP off must not turn Claude's token into a normal login.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This token is only valid for Claude Access",
        )
    if settings.supabase_jwt_secret:
        user = _verify_local(token)
        if user is not None:
            _set_cached_user(token, user)
            return user
    return _verify_remote(token)
