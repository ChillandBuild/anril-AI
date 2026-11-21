"""Full block: a blocked person (leads.blocked_at set) gets NOTHING sent, on any channel.

One central check, so a new sender cannot forget it:
  - every WhatsApp send in services/meta_cloud.py calls guard_whatsapp_recipient first;
  - the Instagram / Facebook / Telegram senders in services/ai_reply.py call is_blocked first;
  - the SMS campaign send-time gate (services/sms_campaigns.py) calls is_blocked_sync.
A few schedulers also check up front (broadcast, Auto-Messages, re-engagement, scheduled
templates) only so their own history says "blocked" instead of "failed".

Exempt, by design: the client's website OTP (services/otp.py passes skip_blocked_check) and
alerts to the business's own staff numbers (services/whatsapp_notify.py does the same).

How a block is looked up: per tenant, the set of blocked people's identifiers (phone,
Instagram id, Telegram id, Facebook id) is read once and kept for CACHE_TTL seconds, so a
broadcast of 5,000 messages costs one query a minute, not 5,000. Only leads of THAT tenant
with blocked_at set and not deleted are in the set. Phones are compared in one form
(digits, a bare 10-digit number is Indian, same rule as outbound_router.recipient_key);
chat ids are compared only against the same channel's ids, so a Telegram id can never
match a phone number.

Trade-off, on purpose: if the lookup itself fails (database blip) the send is ALLOWED and a
warning is logged. Stopping every business message because one read failed is worse than a
rare message to a blocked person. The last good list is reused when there is one. A new
block takes effect at once in the process that saved it and within CACHE_TTL elsewhere.
"""
import asyncio
import logging
import re
import time

from fastapi import HTTPException

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

BLOCKED_DETAIL = "This person is blocked. Unblock to reply."
CACHE_TTL = 60.0          # seconds a tenant's blocked list is trusted
_FAILED_RETRY = 10.0      # after a failed read, try again in this many seconds
_NUMBER_TTL = 600.0       # a sending number's tenant almost never changes
_PAGE = 1000
_MAX_PAGES = 20           # 20,000 blocked people per tenant; more is logged and truncated

PHONE, INSTAGRAM, TELEGRAM, FACEBOOK = "p", "ig", "tg", "fb"
_CHANNEL_KEY = {"whatsapp": PHONE, "sms": PHONE, "phone": PHONE, "instagram": INSTAGRAM,
                "telegram": TELEGRAM, "facebook": FACEBOOK, PHONE: PHONE, INSTAGRAM: INSTAGRAM,
                TELEGRAM: TELEGRAM, FACEBOOK: FACEBOOK}

_PHONE_SHAPE = re.compile(r"\+?[\d\s\-().]+")

# tenant_id -> (expires_at, frozenset of "kind:value" keys)
_cache: dict[str, tuple[float, frozenset[str]]] = {}
# meta phone_number_id -> (expires_at, tenant_id | None)
_number_cache: dict[str, tuple[float, str | None]] = {}


class RecipientBlocked(HTTPException):
    """The person is blocked. An HTTPException (409), so every sender's existing "send failed"
    handling already copes with it and a staff route answers with the plain message."""

    def __init__(self) -> None:
        super().__init__(status_code=409, detail=BLOCKED_DETAIL)


def phone_key(raw) -> str | None:
    """One form per person. "+91 98765 43210", "919876543210" and "09876543210" are the same;
    a value that is not shaped like a phone (a placeholder id) is compared exactly."""
    text = str(raw or "").strip()
    if not text:
        return None
    if not _PHONE_SHAPE.fullmatch(text):
        return text.lower()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def _key(channel: str, value) -> str | None:
    kind = _CHANNEL_KEY.get(channel, PHONE)
    if kind == PHONE:
        norm = phone_key(value)
    else:
        norm = str(value).strip() if value not in (None, "") else None
    return f"{kind}:{norm}" if norm else None


def _keys_for_lead(row: dict) -> set[str]:
    keys = {
        _key(PHONE, row.get("phone")),
        _key(INSTAGRAM, row.get("ig_user_id")),
        _key(TELEGRAM, row.get("tg_user_id")),
        _key(FACEBOOK, row.get("fb_user_id")),
    }
    keys.discard(None)
    return keys


def _load(tenant_id: str) -> frozenset[str] | None:
    """The tenant's blocked identifiers, or None when the read failed."""
    try:
        db = get_supabase()
        keys: set[str] = set()
        for page in range(_MAX_PAGES):
            start = page * _PAGE
            rows = (
                db.table("leads").select("phone,ig_user_id,tg_user_id,fb_user_id")
                .eq("tenant_id", tenant_id).not_.is_("blocked_at", "null").is_("deleted_at", "null")
                .order("id").range(start, start + _PAGE - 1).execute()
            ).data or []
            for row in rows:
                keys |= _keys_for_lead(row)
            if len(rows) < _PAGE:
                return frozenset(keys)
        logger.warning("blocked_guard: tenant %s has more than %d blocked people; the rest are not checked",
                       tenant_id, _MAX_PAGES * _PAGE)
        return frozenset(keys)
    except Exception as e:
        logger.warning("blocked_guard: could not read blocked people for tenant %s (%s); allowing sends", tenant_id, e)
        return None


def _fresh(tenant_id: str) -> frozenset[str] | None:
    hit = _cache.get(tenant_id)
    if hit and time.monotonic() < hit[0]:
        return hit[1]
    return None


def _store(tenant_id: str, loaded: frozenset[str] | None) -> frozenset[str]:
    """Remember a read. A failed read keeps the last good list (or an empty one) for a few
    seconds only, so the next send tries again soon."""
    now = time.monotonic()
    if loaded is not None:
        _cache[tenant_id] = (now + CACHE_TTL, loaded)
        return loaded
    stale = _cache.get(tenant_id)
    keep = stale[1] if stale else frozenset()
    _cache[tenant_id] = (now + _FAILED_RETRY, keep)
    return keep


def invalidate(tenant_id: str | None = None) -> None:
    """Forget the cached list (all tenants when none is given). Called when someone is blocked
    or unblocked so this process sees it at once."""
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(str(tenant_id), None)


def blocked_set_sync(tenant_id: str) -> frozenset[str]:
    tenant_id = str(tenant_id)
    keys = _fresh(tenant_id)
    if keys is None:
        keys = _store(tenant_id, _load(tenant_id))
    return keys


async def _blocked_set(tenant_id: str) -> frozenset[str]:
    tenant_id = str(tenant_id)
    keys = _fresh(tenant_id)
    if keys is None:
        keys = _store(tenant_id, await asyncio.to_thread(_load, tenant_id))
    return keys


def is_blocked_sync(tenant_id: str | None, value, channel: str = "whatsapp") -> bool:
    """Is this person blocked in this tenant? channel: whatsapp | sms | instagram | facebook | telegram."""
    key = _key(channel, value)
    if not tenant_id or not key:
        return False
    return key in blocked_set_sync(tenant_id)


async def is_blocked(tenant_id: str | None, value, channel: str = "whatsapp") -> bool:
    key = _key(channel, value)
    if not tenant_id or not key:
        return False
    return key in await _blocked_set(tenant_id)


async def ensure_not_blocked(tenant_id: str | None, value, channel: str = "whatsapp") -> None:
    """Raise RecipientBlocked (409) when the person is blocked."""
    if await is_blocked(tenant_id, value, channel):
        raise RecipientBlocked()


def _number_tenant_sync(phone_number_id: str) -> str | None:
    try:
        rows = (get_supabase().table("phone_numbers").select("tenant_id")
                .eq("meta_phone_number_id", phone_number_id).limit(1).execute()).data or []
        return str(rows[0]["tenant_id"]) if rows and rows[0].get("tenant_id") else None
    except Exception as e:
        logger.warning("blocked_guard: could not find the business behind sending number %s (%s)", phone_number_id, e)
        return None


async def _tenant_for_number(phone_number_id: str) -> str | None:
    hit = _number_cache.get(phone_number_id)
    if hit and time.monotonic() < hit[0]:
        return hit[1]
    tenant = await asyncio.to_thread(_number_tenant_sync, phone_number_id)
    # A miss is remembered only briefly: a number added a moment ago should not stay unknown.
    _number_cache[phone_number_id] = (time.monotonic() + (_NUMBER_TTL if tenant else _FAILED_RETRY), tenant)
    return tenant


async def guard_whatsapp_recipient(to_number: str, tenant_id: str | None = None,
                                   phone_number_id: str | None = None) -> None:
    """The WhatsApp senders call this first. The business is the explicit tenant_id, else the
    one that owns the sending number, else the one meta_cloud falls back to for credentials
    (the same business the message is sent as)."""
    tenant = str(tenant_id) if tenant_id else None
    if not tenant and phone_number_id:
        tenant = await _tenant_for_number(str(phone_number_id))
    if not tenant:
        from app.config_dynamic import _DEFAULT_TENANT_ID
        tenant = _DEFAULT_TENANT_ID
    if await is_blocked(tenant, to_number, "whatsapp"):
        logger.info("blocked_guard: WhatsApp message to ***%s not sent, the person is blocked (tenant %s)",
                    str(to_number)[-4:], tenant)
        raise RecipientBlocked()


async def lead_is_blocked(tenant_id: str, lead_id: str) -> bool:
    """A fresh read of one lead's block (no cache), for the staff reply and similar one-off
    checks where being a minute stale is not acceptable. A failed read counts as not blocked
    and is logged (same trade-off as above)."""
    try:
        rows = await asyncio.to_thread(
            lambda: (get_supabase().table("leads").select("blocked_at")
                     .eq("id", str(lead_id)).eq("tenant_id", str(tenant_id)).limit(1).execute()).data or []
        )
        return bool(rows and rows[0].get("blocked_at"))
    except Exception as e:
        logger.warning("blocked_guard: could not read lead %s (%s); allowing", lead_id, e)
        return False


def lead_is_blocked_sync(db, tenant_id: str, lead_id: str) -> bool:
    """lead_is_blocked for sync code that already holds a db handle."""
    try:
        rows = (db.table("leads").select("blocked_at").eq("id", str(lead_id)).eq("tenant_id", str(tenant_id))
                .limit(1).execute()).data or []
        return bool(rows and rows[0].get("blocked_at"))
    except Exception as e:
        logger.warning("blocked_guard: could not read lead %s (%s); allowing", lead_id, e)
        return False
