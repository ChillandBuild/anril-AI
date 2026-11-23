"""v9.2 #184 New logins in the Activity log.

Sign-in itself happens at Supabase, so the first dashboard load of a new sign-in is the moment we can see it: the
session id comes from the token the backend has already verified (never from anything the browser typed in a form),
the address from the request headers. One row per sign-in session: the same session loading more pages, or the
token refreshing, writes nothing. Best-effort: never raises, never slows a page by more than one small read.
"""
import logging

logger = logging.getLogger(__name__)

_SEEN: set[tuple[str, str]] = set()  # (user, session) already handled by this process
_SEEN_MAX = 5000


def _session_id(authorization: str | None) -> str | None:
    """The Supabase session id inside a bearer token that the auth check has already accepted."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        import jwt
        claims = jwt.decode(authorization[7:].strip(), options={"verify_signature": False, "verify_aud": False})
    except Exception:
        return None
    sid = claims.get("session_id")
    return str(sid)[:64] if sid else None


def _client_ip(headers, client_host: str | None) -> str | None:
    # The LAST hop is the one our own proxy appended; the first can be typed by the client.
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[-1].strip()
    return (forwarded or client_host or None)


def _remember(user_id: str, sid: str) -> None:
    if len(_SEEN) >= _SEEN_MAX:
        _SEEN.clear()
    _SEEN.add((user_id, sid))


def note_login(db, ctx: dict, authorization: str | None, headers, client_host: str | None) -> bool:
    """Write "auth.login" the first time this sign-in session is seen. True when a row was written."""
    try:
        user_id = str(ctx.get("user_id") or "")
        sid = _session_id(authorization)
        if not user_id or not sid or (user_id, sid) in _SEEN:
            return False
        tenant_id = ctx["tenant_id"]
        known = (db.table("app_audit_logs").select("id").eq("tenant_id", tenant_id).eq("action", "auth.login")
                 .eq("actor_user_id", user_id).eq("target_id", sid).limit(1).execute().data or [])
        if known:
            _remember(user_id, sid)
            return False
        from app.services import orders
        from app.services.audit_log import write_audit_event  # raises, so a failed write is not remembered
        write_audit_event(
            db, tenant_id=tenant_id, actor_user_id=user_id, actor_role=ctx.get("role"), action="auth.login",
            target_type="session", target_id=sid,
            metadata={"ip": _client_ip(headers, client_host), "device": (headers.get("user-agent") or "")[:120] or None,
                      "by_name": orders._actor_name(db, tenant_id, user_id)},
        )
        _remember(user_id, sid)  # only after the row is safely written, so a failed write is tried again
        return True
    except Exception as e:
        logger.warning("login log failed: %s", e)
        return False
