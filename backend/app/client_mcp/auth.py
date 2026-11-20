"""Who may call the client connector (Anril AI).

A call is let in only when all of these hold:
  1. the bearer token is a valid Supabase token for this project (same check as the admin MCP),
  2. it was issued through the OAuth server to one of the approved client apps
     (MCP_CLIENT_OAUTH_CLIENT_IDS). The admin app's id is never accepted here,
  3. the user is the owner of exactly one client, that client is not suspended and has the
     connector switched on by the operator (services.client_claude.owner_seat),
  4. that owner has an active tenant_mcp_connections row for that app (the owner's off switch).
Anything else is a 401. The client a call acts for comes ONLY from this check: no tool takes a
client as an argument.
"""
import logging

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError

from app.admin_mcp.auth import _verified_claims
from app.db.supabase import get_supabase
from app.services import client_claude

logger = logging.getLogger(__name__)


def verify(token: str) -> AccessToken | None:
    claims = _verified_claims(token)
    if not claims:
        return None
    user_id, client_id = claims.get("sub"), claims.get("client_id")
    if not user_id or not client_id:
        return None  # a normal dashboard login, not a connector
    if client_id not in client_claude.approved_client_ids():
        logger.warning("Client MCP token refused: app %s is not an approved client app", client_id)
        return None
    db = get_supabase()
    seat, why = client_claude.owner_seat(db, user_id)
    if not seat:
        logger.warning("Client MCP token refused: user %s (%s)", user_id, why)
        return None
    connection = client_claude.find_active(db, seat["tenant_id"], user_id, client_id)
    if not connection:
        return None
    return AccessToken(
        token=token,
        client_id=client_id,
        scopes=[],
        expires_at=claims.get("exp"),
        subject=user_id,
        claims={
            "email": claims.get("email") or "",
            "connection_id": connection["id"],
            "tenant_id": seat["tenant_id"],
            "tenant_name": seat["tenant_name"],
        },
    )


class ClientTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return await anyio.to_thread.run_sync(verify, token)
        except Exception:
            logger.exception("Client MCP token check failed")
            return None


def current_seat() -> dict:
    """The owner, and their client, behind the tool call being served."""
    token = get_access_token()
    claims = (token.claims or {}) if token else {}
    if token is None or not token.subject or not claims.get("tenant_id"):
        raise ToolError("Not signed in.")
    return {
        "user_id": token.subject,
        "email": claims.get("email") or "",
        "client_id": token.client_id,
        "connection_id": claims.get("connection_id"),
        "tenant_id": claims["tenant_id"],
        "tenant_name": claims.get("tenant_name") or "",
    }
