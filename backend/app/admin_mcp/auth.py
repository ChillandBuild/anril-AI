"""Who may call the admin MCP.

A call is let in only when all four hold:
  1. the bearer token is a valid Supabase token for this project,
  2. it was issued through the OAuth server to a client (it carries `client_id`), and that
     client is the one registered for Claude (MCP_OAUTH_CLIENT_ID, required),
  3. the user is in system_admins,
  4. that user has an active mcp_connections row for that client (the off switch).
Anything else is a 401, which makes Claude start the sign-in again.
"""
import logging

import anyio
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError

from app.config import settings
from app.db.supabase import get_supabase
from app.services import mcp_connections

logger = logging.getLogger(__name__)

_ASYMMETRIC = ("RS256", "ES256")
_jwks_client: jwt.PyJWKClient | None = None


def issuer() -> str:
    return settings.supabase_url.rstrip("/") + "/auth/v1"


def peek_claims(token: str) -> dict:
    """The token's payload WITHOUT checking its signature. Only for deciding to refuse."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        return claims if isinstance(claims, dict) else {}
    except jwt.PyJWTError:
        return {}


def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(issuer() + "/.well-known/jwks.json", cache_keys=True, lifespan=3600)
    return _jwks_client


def _verified_claims(token: str) -> dict | None:
    """Signature, expiry, audience and issuer checked. None when the token is not good."""
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError:
        logger.info("MCP token refused: not a readable JWT")
        return None
    try:
        if alg == "HS256" and settings.supabase_jwt_secret:
            return jwt.decode(
                token, settings.supabase_jwt_secret, algorithms=["HS256"],
                audience="authenticated", issuer=issuer(),
            )
        if alg in _ASYMMETRIC:
            key = _jwks().get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=list(_ASYMMETRIC), audience="authenticated", issuer=issuer())
    except jwt.PyJWTError as exc:
        logger.info("MCP token refused locally: %s", type(exc).__name__)
        return None
    except Exception as exc:  # JWKS fetch failed: fall through to asking Supabase
        logger.warning("MCP token: JWKS check unavailable: %s", exc)
    if alg != "HS256" and alg not in _ASYMMETRIC:
        logger.info("MCP token has an unsupported algorithm (%s); asking Supabase", alg)
    # No local way to check (no shared secret configured, or JWKS down): ask Supabase.
    try:
        user = get_supabase().auth.get_user(token).user
    except Exception as exc:
        logger.info("MCP token refused by Supabase: %s", type(exc).__name__)
        return None
    claims = peek_claims(token)
    if not user or not claims.get("sub") or str(user.id) != str(claims["sub"]):
        logger.info("MCP token refused by Supabase: no matching user")
        return None
    return claims


def verify(token: str) -> AccessToken | None:
    claims = _verified_claims(token)
    if not claims:
        return None
    user_id, client_id = claims.get("sub"), claims.get("client_id")
    if not user_id or not client_id:
        logger.info("MCP token refused: no client_id, so not issued to a connector")
        return None  # a normal dashboard login, not Claude
    # No registered client configured = nobody gets in (main.py also refuses to start the MCP).
    if not settings.mcp_oauth_client_id or client_id != settings.mcp_oauth_client_id:
        logger.warning("MCP token refused: client %s is not the registered Claude client", client_id)
        return None
    db = get_supabase()
    admin = db.table("system_admins").select("user_id").eq("user_id", user_id).limit(1).execute()
    if not (admin and admin.data):
        logger.warning("MCP token refused: user %s is not a system admin", user_id)
        return None
    connection = mcp_connections.find_active(db, user_id, client_id)
    if not connection:
        logger.warning("MCP token refused: user %s has no active connection (switched off or replaced by a newer one)", str(user_id)[:8])
        return None
    return AccessToken(
        token=token,
        client_id=client_id,
        scopes=[],
        expires_at=claims.get("exp"),
        subject=user_id,
        claims={"email": claims.get("email") or "", "connection_id": connection["id"]},
    )


class AdminTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return await anyio.to_thread.run_sync(verify, token)
        except Exception:
            logger.exception("MCP token check failed")
            return None


def current_caller() -> dict:
    """The admin behind the tool call being served."""
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("Not signed in.")
    claims = token.claims or {}
    return {
        "user_id": token.subject,
        "email": claims.get("email") or "",
        "client_id": token.client_id,
        "connection_id": claims.get("connection_id"),
    }
