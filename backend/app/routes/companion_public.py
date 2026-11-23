"""Public companion chat API (companion-chat-api). Mounted at /api/v1/companion, no login.

Two doors, both ending in engine.reply / engine.continue_reply:
- /chat, /chat/continue: server to server, "Authorization: Bearer acs_live_...". The tenant
  comes from the key, never from the body. /forget (same key) wipes a deleted profile or account.
- /widget/session, /widget/chat, /widget/chat/continue: the web widget. The body carries the
  character id plus a user id signed by the business's server (app/companion/keys.py). The
  tenant comes from the character, and the signature must match one of THAT tenant's keys.

Only live characters answer here (drafts are tested in the dashboard). Every error is
{"error": "...", "code": "..."}. Logs carry ids and codes, never message text.

Rate limits (in-process, like private_send): 120/min per IP before any DB lookup, 600/min per
business, 20/min per person.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.companion import engine, keys, store
from app.companion.models import AppData, AppTool, ReplyLanguage, ToolResult
from app.companion.reply_format import ReplyFormat
from app.companion.tools import MAX_TOOLS, ToolsInvalid
from app.db.supabase import get_supabase
from app.routes.auto_messages import _SlidingWindow, _client_ip
from app.services.audit_log import record_audit_event

logger = logging.getLogger(__name__)

public_router = APIRouter()

IP_PER_MINUTE = 120
TENANT_PER_MINUTE = 600
PERSON_PER_MINUTE = 20
HISTORY_ON_OPEN = 20
TOUCH_EVERY_SECONDS = 60

_ip_limiter = _SlidingWindow(IP_PER_MINUTE, 60)
_tenant_limiter = _SlidingWindow(TENANT_PER_MINUTE, 60)
_person_limiter = _SlidingWindow(PERSON_PER_MINUTE, 60)
# /forget has its own budget: a client's bulk delete job must not use up live chat's limits (or hit them).
FORGET_PER_MINUTE = 600
_forget_limiter = _SlidingWindow(FORGET_PER_MINUTE, 60)
_NO_STORE = {"Cache-Control": "no-store"}
_last_touch: dict[str, float] = {}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def _json(content: dict, status: int = 200, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=content, headers={**_NO_STORE, **(headers or {})})


def _error(exc: ApiError) -> JSONResponse:
    return _json({"error": exc.message, "code": exc.code}, exc.status, exc.headers)


_RATE = ApiError(429, "rate_limited", "Too many messages. Try again in a minute.", {"Retry-After": "60"})


def _engine_error(exc: Exception) -> ApiError:
    if isinstance(exc, engine.CompanionNotFound):
        return ApiError(404, "companion_not_found", "Character not found")
    if isinstance(exc, engine.TurnExpired):
        return ApiError(404, "turn_expired", "This tool turn has expired or was already used. Send the message again.")
    if isinstance(exc, ToolsInvalid):
        return ApiError(422, "tools_invalid", str(exc))
    if isinstance(exc, (engine.CompanionPaused, engine.CompanionNotLive)):
        return ApiError(409, "companion_not_live", "This character isn't live yet.")
    if isinstance(exc, engine.CompanionMisconfigured):
        return ApiError(503, "companion_not_configured", "The business hasn't finished setting up its AI model.")
    return ApiError(503, "busy", "The companion is busy right now. Try again in a few seconds.",
                    {"Retry-After": "5"})


# --- request bodies (extra="forbid": a tenant_id in the body is a 422, never used) --------------

UserId = Field(min_length=1, max_length=128)
# Which profile this message is about (AstroTamil: which family chart). Optional; see keys.person_key.
ProfileId = Field(None, min_length=1, max_length=64)
ProfileName = Field(None, max_length=100)
Message = Field(min_length=1, max_length=4000)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _zone(value: str | None) -> str | None:
    """Optional IANA zone of the person ("Asia/Kolkata", "America/Toronto"): "today" for their memory."""
    if value is None or not value.strip():
        return None
    from app.companion.memory_card import valid_zone
    zone = valid_zone(value)
    if not zone:
        raise ValueError("timezone must be an IANA zone name like 'Asia/Kolkata'")
    return zone


Timezone = Annotated[str | None, Field(None, max_length=64), AfterValidator(_zone)]


class ServerChatIn(_Body):
    companion_id: UUID
    user_id: str = UserId
    profile_id: str | None = ProfileId       # e.g. "p7": one memory per (user, profile)
    profile_name: str | None = ProfileName   # e.g. "Karthik": whose profile (chart) this is
    message: str = Message
    display_name: str | None = Field(None, max_length=100)
    timezone: Timezone = None
    tools: list[AppTool] = Field(default_factory=list, max_length=MAX_TOOLS)
    app_data: AppData = None   # what your app knows about this person (text or a JSON object, up to 12,000 chars)
    reply_format: ReplyFormat | None = None   # opt in to bubbles, chips, a button and a tag (reply_format.py)
    reply_language: ReplyLanguage = None   # "en", "ta", "ta-en" or a name like "English"; None = the character's


class ServerContinueIn(_Body):
    user_id: str = UserId
    profile_id: str | None = ProfileId
    turn_id: UUID
    results: list[ToolResult] = Field(default_factory=list, max_length=MAX_TOOLS)


class ServerForgetIn(_Body):
    user_id: str = UserId
    profile_id: str | None = ProfileId   # given: just this profile; left out: the user and every profile


class WidgetAuthIn(_Body):
    companion_id: UUID
    user_id: str = UserId
    profile_id: str | None = ProfileId   # not signed: it only picks among this signed user's own profiles
    exp: int
    signature: str = Field(min_length=64, max_length=64)


class WidgetChatIn(WidgetAuthIn):
    profile_name: str | None = ProfileName
    message: str = Message
    display_name: str | None = Field(None, max_length=100)
    timezone: Timezone = None
    tools: list[AppTool] = Field(default_factory=list, max_length=MAX_TOOLS)
    app_data: AppData = None
    reply_format: ReplyFormat | None = None
    reply_language: ReplyLanguage = None


class WidgetContinueIn(WidgetAuthIn):
    turn_id: UUID
    results: list[ToolResult] = Field(default_factory=list, max_length=MAX_TOOLS)


# --- who is calling ---------------------------------------------------------------------------

def _check_ip(request: Request) -> None:
    if not _ip_limiter.allow(_client_ip(request)):
        raise _RATE


def _valid_person(user_id: str, profile_id: str | None = None) -> str:
    """The person's key (keys.person_key): "u42", or "u42~p7" when the app names a profile."""
    if not keys.valid_user_id(user_id):
        raise ApiError(422, "invalid_user_id", "user_id may use letters, digits and _ . @ : - (up to 128)")
    if profile_id is not None and not keys.valid_profile_id(profile_id):
        raise ApiError(422, "invalid_profile_id", "profile_id may use letters, digits and _ . @ : - (up to 64)")
    return keys.person_key(user_id, profile_id)


def _check_person(tenant_id: str, user_id: str, profile_id: str | None = None) -> str:
    """_valid_person plus the chat rate limits."""
    person_key = _valid_person(user_id, profile_id)
    # Person first: a person over their own limit must not use up the business-wide budget.
    if not _person_limiter.allow(f"{tenant_id}:{user_id}") or not _tenant_limiter.allow(tenant_id):
        raise _RATE
    return person_key


async def _touch(tenant_id: str, key_id: str) -> None:
    """last_used_at for the Install tab, at most once a minute per key."""
    now = time.monotonic()
    if now - _last_touch.get(key_id, -TOUCH_EVERY_SECONDS) < TOUCH_EVERY_SECONDS:
        return
    _last_touch[key_id] = now
    try:
        await store.touch_api_key(tenant_id, key_id)
    except Exception as exc:
        logger.warning("companion key heartbeat failed (%s)", type(exc).__name__)


async def _server_key(request: Request) -> dict:
    """The active key row behind "Authorization: Bearer acs_live_...". Its tenant_id is the business."""
    _check_ip(request)
    header = request.headers.get("authorization") or ""
    raw = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if not keys.looks_like_key(raw):
        raise ApiError(401, "invalid_key", "Send your secret key as 'Authorization: Bearer acs_live_...'")
    row = await store.find_active_api_key(keys.hash_key(raw))
    if not row:
        raise ApiError(401, "invalid_key", "This key is wrong or was revoked")
    await _touch(row["tenant_id"], row["id"])
    return row


async def _server_tenant(request: Request) -> str:
    return (await _server_key(request))["tenant_id"]


async def _widget_tenant(request: Request, body: WidgetAuthIn) -> str:
    _check_ip(request)
    bad = ApiError(401, "invalid_signature", "The signed user id is wrong or expired. Reload the page.")
    tenant_id = await store.companion_tenant(str(body.companion_id))
    if not tenant_id:
        raise bad   # same answer as a bad signature: don't reveal which character ids exist
    key_id = keys.check_signature(await store.active_key_hashes(tenant_id), body.user_id, body.exp, body.signature)
    if not key_id:
        raise bad
    await _touch(tenant_id, key_id)
    return tenant_id


def _require_text(message: str) -> None:
    if not message.strip():
        raise ApiError(422, "empty_message", "Type a message first")


async def _log_request(row: dict) -> None:
    """Runs after the response is sent. Never raises: a broken log must not break a chat."""
    try:
        await store.log_request(row)
    except Exception as exc:
        logger.warning("companion public api: request log insert failed (%s)", type(exc).__name__)


# The calls that end in an agent reply. Each finished one ("status": "done") is +1 on the business's monthly
# agent_reply counter (Agents -> Usage); a tool pause is not, the reply after the tools is.
REPLY_KINDS = frozenset({"chat", "chat_continue", "widget_chat", "widget_continue"})


async def _after_response(row: dict, count_reply: bool) -> None:
    """Runs after the response is sent: the request log row, then the usage count. Never raises."""
    await _log_request(row)
    if count_reply:
        try:
            await store.count_agent_reply(row["tenant_id"])
        except Exception as exc:
            logger.warning("companion public api: usage count failed (%s)", type(exc).__name__)


async def _run(call, kind: str, log: dict) -> JSONResponse:
    """Runs one public call and, once the business is known (log["tenant_id"], set by call()),
    queues one companion_request_log row to be written after the response (no message text), plus
    one agent_reply count when the call finished a reply."""
    started = time.monotonic()
    replied = False
    try:
        result = await call()
        replied = kind in REPLY_KINDS and isinstance(result, dict) and result.get("status") == "done"
        response = _json(result)
    except ApiError as exc:
        response = _error(exc)
    except (engine.CompanionError, ToolsInvalid) as exc:
        api = _engine_error(exc)
        logger.info("companion public api: %s", api.code)
        response = _error(api)
    if log.get("tenant_id"):
        response.background = BackgroundTask(_after_response, {
            "tenant_id": log["tenant_id"], "companion_id": log.get("companion_id"), "kind": kind,
            "external_user_id": log.get("user_id"), "status": response.status_code,
            "ms": int((time.monotonic() - started) * 1000),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, replied)
    return response


# --- server to server -------------------------------------------------------------------------

@public_router.post("/chat")
async def server_chat(body: ServerChatIn, request: Request):
    """{"companion_id", "user_id", "message", "display_name"?, "profile_id"?, "profile_name"?, "timezone"?,
    "tools"?, "app_data"?, "reply_format"?} → the reply,
    or status "tool_call" with a turn_id: run the tools and POST /chat/continue. app_data rides with every
    message (e.g. AstroTamil's chart for this user) and is never stored.
    reply_format {"buttons"?: [{"id", "when", "handoff"?}] (0-6), "questions_left"?}: the reply also carries
    "bubbles" (1-3 short texts), "chips" (0 or 2 follow-up questions), "button" (one of your ids or null) and
    "tag" ("counted" = count this question; "ask_back", "greeting", "off_topic", "need_details", a button id,
    "handoff" or "failed" = don't). "text" is then the bubbles joined by a blank line. Without reply_format
    those four are null. The format carries over to /chat/continue on its own."""
    log = {"companion_id": str(body.companion_id), "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _server_tenant(request)
        person_key = _check_person(tenant_id, body.user_id, body.profile_id)
        _require_text(body.message)
        result = await engine.reply(str(body.companion_id), tenant_id, person_key, body.message.strip(),
                                    display_name=body.display_name, tools=body.tools, require_live=True,
                                    timezone_name=body.timezone, app_data=body.app_data,
                                    profile_name=body.profile_name, reply_format=body.reply_format,
                                    reply_language=body.reply_language)
        return result.model_dump()
    return await _run(call, "chat", log)


@public_router.post("/chat/continue")
async def server_continue(body: ServerContinueIn, request: Request):
    log = {"companion_id": None, "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _server_tenant(request)
        person_key = _check_person(tenant_id, body.user_id, body.profile_id)
        result = await engine.continue_reply(str(body.turn_id), tenant_id, body.results,
                                             external_user_id=person_key, require_live=True)
        return result.model_dump()
    return await _run(call, "chat_continue", log)


@public_router.post("/forget")
async def server_forget(body: ServerForgetIn, request: Request):
    """The business deleted a profile or an account: {"user_id", "profile_id"?} → {"forgotten": bool}.
    With profile_id ("48213" + "104"): that profile's chats and memories, with every character. Without it:
    the user and every profile of theirs ("48213", "48213~101", "48213~104"...). false = they never chatted
    here, not an error, so a delete job can call it for everyone. Server door only: deleting is not the
    phone's job. A reply still being written at that moment may save one message after the wipe; calling
    again clears it. Audited like the dashboard's "Delete this person"."""
    log = {"companion_id": None, "user_id": body.user_id}

    async def call():
        key = await _server_key(request)
        tenant_id = log["tenant_id"] = key["tenant_id"]
        person_key = _valid_person(body.user_id, body.profile_id)
        if not _forget_limiter.allow(tenant_id):
            raise _RATE
        try:
            people = await store.find_person_rows(tenant_id, person_key)
            if people:
                await engine.forget_person(tenant_id, person_key)
        except Exception as exc:   # e.g. the DB dropped mid-wipe: safe to call again, so say "retry"
            logger.warning("companion api forget failed (%s)", type(exc).__name__)
            raise ApiError(503, "busy", "Couldn't finish forgetting. Try again in a few seconds.",
                           {"Retry-After": "5"}) from exc
        for person in people:
            _audit_api_forget(tenant_id, person["id"], key)
        return {"forgotten": bool(people)}
    return await _run(call, "forget", log)


def _audit_api_forget(tenant_id: str, end_user_id: str, key: dict) -> None:
    """Same action as the dashboard's forget; the actor is the key (its row id, from find_active_api_key's
    "id, tenant_id"), not a login."""
    try:
        record_audit_event(
            get_supabase(), tenant_id=tenant_id, actor_user_id=None, actor_role="api_key",
            action="tenant.companion_person_forgotten", target_type="companion_end_user",
            target_id=end_user_id, metadata={"via": "api", "key_id": key["id"]},
        )
    except Exception as exc:
        logger.warning("companion api forget audit failed (%s)", type(exc).__name__)


# --- web widget -------------------------------------------------------------------------------

@public_router.post("/widget/session")
async def widget_session(body: WidgetAuthIn, request: Request):
    """When the widget opens: the character's name and language, plus this person's last 20
    messages with it (empty for a first visit). Creates nothing."""
    log = {"companion_id": str(body.companion_id), "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _widget_tenant(request, body)
        person_key = _check_person(tenant_id, body.user_id, body.profile_id)
        companion = await store.get_companion(tenant_id, str(body.companion_id))
        if not companion or companion.get("status") != "live" or companion.get("archived_at"):
            raise ApiError(409, "companion_not_live", "This character isn't live yet.")
        person = await store.find_end_user(tenant_id, person_key)
        history = []
        if person:
            history = await store.recent_messages(tenant_id, companion["id"], person["id"], HISTORY_ON_OPEN)
        return {
            "companion": {"name": companion["name"], "language": companion.get("language")},
            "messages": [{"role": m["role"], "content": m["content"], "mood": m.get("mood"),
                          "created_at": m.get("created_at")} for m in history],
        }
    return await _run(call, "widget_session", log)


@public_router.post("/widget/chat")
async def widget_chat(body: WidgetChatIn, request: Request):
    log = {"companion_id": str(body.companion_id), "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _widget_tenant(request, body)
        person_key = _check_person(tenant_id, body.user_id, body.profile_id)
        _require_text(body.message)
        result = await engine.reply(str(body.companion_id), tenant_id, person_key, body.message.strip(),
                                    display_name=body.display_name, tools=body.tools, require_live=True,
                                    timezone_name=body.timezone, app_data=body.app_data,
                                    profile_name=body.profile_name, reply_format=body.reply_format,
                                    reply_language=body.reply_language)
        return result.model_dump()
    return await _run(call, "widget_chat", log)


@public_router.post("/widget/chat/continue")
async def widget_continue(body: WidgetContinueIn, request: Request):
    """The page ran the tools (a browser tool can be faked by the user, so tools that touch money
    or other people's data belong on the business's server, through /chat)."""
    log = {"companion_id": None, "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _widget_tenant(request, body)
        person_key = _check_person(tenant_id, body.user_id, body.profile_id)
        result = await engine.continue_reply(str(body.turn_id), tenant_id, body.results,
                                             external_user_id=person_key, require_live=True)
        return result.model_dump()
    return await _run(call, "widget_continue", log)
