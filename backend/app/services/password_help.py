"""v9.2 #27 Forgot password = a request to the Anril team (no email, no SMS, nothing sent).

The public form stores one row; the Anril team checks it is really that person and gives the
new password in person or on a call. The reply is the same whatever was typed, so the form can
never be used to find out who is a customer. Limits (in-process, same approach as the other
public forms): 3 per identifier per hour, 10 per IP per hour; past a limit the request is
quietly dropped and the same reply is sent. Nothing here logs the identifier."""
import hashlib
import hmac
import ipaddress
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.routes.auto_messages import _SlidingWindow

logger = logging.getLogger(__name__)

REPLY = "If this account exists, the Anril team will contact you soon."
MAX_IDENTIFIER, MAX_BUSINESS, MAX_NOTE = 120, 120, 300
PER_IDENTIFIER_PER_HOUR = 3
PER_IP_PER_HOUR = 10
MAX_OPEN_PER_HOUR = 200  # across everyone

_identifier_limiter = _SlidingWindow(PER_IDENTIFIER_PER_HOUR, 3600)
_ip_limiter = _SlidingWindow(PER_IP_PER_HOUR, 3600)


def _clean(value: str | None, limit: int) -> str:
    """Trim, drop control characters, cap the length."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value or "").strip()
    return text[:limit]


def _secret() -> bytes:
    """A server-only secret for the hashes: PASSWORD_HELP_SALT if set, else the Supabase service key
    (never in the repo). No secret at all -> random per process, so hashes still never reveal an address."""
    value = os.environ.get("PASSWORD_HELP_SALT") or ""
    if not value:
        try:
            from app.config import settings
            value = settings.supabase_service_key or ""
        except Exception:  # noqa: BLE001
            value = ""
    return value.encode() if value else _RANDOM_SECRET


_RANDOM_SECRET = os.urandom(32)


def _hash(value: str) -> str:
    return hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()[:32]


def identifier_key(identifier: str) -> str:
    """The same person typed two ways counts once: emails lower-cased, phones as digits only."""
    text = identifier.strip().lower()
    if "@" in text:
        return text
    digits = re.sub(r"\D", "", text)
    return digits[-10:] if len(digits) >= 10 else (digits or text)


def ip_bucket(ip: str | None) -> str:
    """The key one sender is limited by. IPv6 hands one home a whole /64, so a new address per
    request must not mean a fresh allowance: limit the /64, not the single address."""
    text = (ip or "").strip()
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return text or "unknown"
    if addr.version == 6:
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def submit_request(identifier: str, business_name: str | None, note: str | None, ip: str) -> bool:
    """Save one request. Returns True when a row was stored. Never raises: the caller answers
    the same way whether this stored, was limited, or failed (the table may not exist yet)."""
    ident = _clean(identifier, MAX_IDENTIFIER)
    if not ident:
        return False
    ident_key = _hash(identifier_key(ident))
    # Both limiters are checked every time, so one noisy address can't use up a person's turns.
    ip_ok = _ip_limiter.allow(ip_bucket(ip))
    ident_ok = _identifier_limiter.allow(ident_key)
    if not (ip_ok and ident_ok):
        return False
    try:
        db = get_supabase()
        # A flood (many addresses, made-up names) can't bury real requests: past this many in an hour, drop.
        now = datetime.now(timezone.utc)
        since = datetime.fromtimestamp(now.timestamp() - 3600, timezone.utc).isoformat()
        recent = (db.table("password_help_requests").select("id").gte("created_at", since)
                  .limit(MAX_OPEN_PER_HOUR).execute().data) or []
        if len(recent) >= MAX_OPEN_PER_HOUR:
            logger.warning("password_help: hourly cap reached, request dropped")
            return False
        db.table("password_help_requests").insert({
            "identifier": ident,
            "business_name": _clean(business_name, MAX_BUSINESS) or None,
            "note": _clean(note, MAX_NOTE) or None,
            "ip_hash": _hash(ip or "unknown"),
            "status": "open",
            "created_at": now.isoformat(),
        }).execute()
        return True
    except Exception as e:  # noqa: BLE001 - never tell the caller; never log what they typed
        logger.warning("password_help: could not save a request (%s)", type(e).__name__)
        return False


def list_requests(status: str = "open", limit: int = 100) -> list[dict]:
    """For the Anril team (operator only): newest first."""
    try:
        res = (
            get_supabase().table("password_help_requests")
            .select("id, identifier, business_name, note, status, created_at, done_at")
            .eq("status", status).order("created_at", desc=True).limit(limit).execute()
        )
        return res.data or []
    except Exception as e:  # noqa: BLE001
        logger.warning("password_help: list failed (%s)", type(e).__name__)
        return []


def open_count() -> int:
    """How many requests are waiting: the planner can show this in the operator alerts."""
    return len(list_requests("open", 200))


def mark_done(request_id: str) -> bool:
    res = (
        get_supabase().table("password_help_requests")
        .update({"status": "done", "done_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", request_id).execute()
    )
    return bool(res.data)


KEEP_DAYS = 90


def prune_old(db=None) -> int:
    """Delete password-help requests older than 90 days (done or not): they hold an email or phone."""
    db = db or get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    try:
        res = db.table("password_help_requests").delete().lt("created_at", cutoff).execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("password_help prune failed (%s)", type(e).__name__)
        return 0
    return len(res.data or [])
