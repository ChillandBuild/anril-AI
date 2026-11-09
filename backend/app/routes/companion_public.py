"""Public companion chat API (companion-chat-api). Mounted at /api/v1/companion, no login.

Two doors, both ending in engine.reply / engine.continue_reply:
- /chat, /chat/continue: server to server, "Authorization: Bearer acs_live_...". The tenant
  comes from the key, never from the body.
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
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, ConfigDict, Field

from app.companion import engine, keys, store
from app.companion.models import AppTool, ToolResult
from app.companion.tools import MAX_TOOLS, ToolsInvalid
from app.routes.auto_messages import _SlidingWindow, _client_ip

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
Message = Field(min_length=1, max_length=4000)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerChatIn(_Body):
    companion_id: UUID
    user_id: str = UserId
    message: str = Message
    display_name: str | None = Field(None, max_length=100)
    tools: list[AppTool] = Field(default_factory=list, max_length=MAX_TOOLS)


class ServerContinueIn(_Body):
    user_id: str = UserId
    turn_id: UUID
    results: list[ToolResult] = Field(default_factory=list, max_length=MAX_TOOLS)


class WidgetAuthIn(_Body):
    companion_id: UUID
    user_id: str = UserId
    exp: int
    signature: str = Field(min_length=64, max_length=64)


class WidgetChatIn(WidgetAuthIn):
    message: str = Message
    display_name: str | None = Field(None, max_length=100)
    tools: list[AppTool] = Field(default_factory=list, max_length=MAX_TOOLS)


class WidgetContinueIn(WidgetAuthIn):
    turn_id: UUID
    results: list[ToolResult] = Field(default_factory=list, max_length=MAX_TOOLS)


# --- who is calling ---------------------------------------------------------------------------

def _check_ip(request: Request) -> None:
    if not _ip_limiter.allow(_client_ip(request)):
        raise _RATE


def _check_person(tenant_id: str, user_id: str) -> None:
    if not keys.valid_user_id(user_id):
        raise ApiError(422, "invalid_user_id", "user_id may use letters, digits and _ . @ : - (up to 128)")
    # Person first: a person over their own limit must not use up the business-wide budget.
    if not _person_limiter.allow(f"{tenant_id}:{user_id}") or not _tenant_limiter.allow(tenant_id):
        raise _RATE


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


async def _server_tenant(request: Request) -> str:
    _check_ip(request)
    header = request.headers.get("authorization") or ""
    raw = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if not keys.looks_like_key(raw):
        raise ApiError(401, "invalid_key", "Send your secret key as 'Authorization: Bearer acs_live_...'")
    row = await store.find_active_api_key(keys.hash_key(raw))
    if not row:
        raise ApiError(401, "invalid_key", "This key is wrong or was revoked")
    await _touch(row["tenant_id"], row["id"])
    return row["tenant_id"]


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


async def _run(call, kind: str, log: dict) -> JSONResponse:
    """Runs one public call and, once the business is known (log["tenant_id"], set by call()),
    queues one companion_request_log row to be written after the response. No message text."""
    started = time.monotonic()
    try:
        response = _json(await call())
    except ApiError as exc:
        response = _error(exc)
    except (engine.CompanionError, ToolsInvalid) as exc:
        api = _engine_error(exc)
        logger.info("companion public api: %s", api.code)
        response = _error(api)
    if log.get("tenant_id"):
        response.background = BackgroundTask(_log_request, {
            "tenant_id": log["tenant_id"], "companion_id": log.get("companion_id"), "kind": kind,
            "external_user_id": log.get("user_id"), "status": response.status_code,
            "ms": int((time.monotonic() - started) * 1000),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return response


# --- server to server -------------------------------------------------------------------------

@public_router.post("/chat")
async def server_chat(body: ServerChatIn, request: Request):
    """{"companion_id", "user_id", "message", "display_name"?, "tools"?} → the reply, or
    status "tool_call" with a turn_id: run the tools and POST /chat/continue."""
    log = {"companion_id": str(body.companion_id), "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _server_tenant(request)
        _check_person(tenant_id, body.user_id)
        _require_text(body.message)
        result = await engine.reply(str(body.companion_id), tenant_id, body.user_id, body.message.strip(),
                                    display_name=body.display_name, tools=body.tools, require_live=True)
        return result.model_dump()
    return await _run(call, "chat", log)


@public_router.post("/chat/continue")
async def server_continue(body: ServerContinueIn, request: Request):
    log = {"companion_id": None, "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _server_tenant(request)
        _check_person(tenant_id, body.user_id)
        result = await engine.continue_reply(str(body.turn_id), tenant_id, body.results,
                                             external_user_id=body.user_id, require_live=True)
        return result.model_dump()
    return await _run(call, "chat_continue", log)


# --- web widget -------------------------------------------------------------------------------

@public_router.post("/widget/session")
async def widget_session(body: WidgetAuthIn, request: Request):
    """When the widget opens: the character's name and language, plus this person's last 20
    messages with it (empty for a first visit). Creates nothing."""
    log = {"companion_id": str(body.companion_id), "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _widget_tenant(request, body)
        _check_person(tenant_id, body.user_id)
        companion = await store.get_companion(tenant_id, str(body.companion_id))
        if not companion or companion.get("status") != "live":
            raise ApiError(409, "companion_not_live", "This character isn't live yet.")
        person = await store.find_end_user(tenant_id, body.user_id)
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
        _check_person(tenant_id, body.user_id)
        _require_text(body.message)
        result = await engine.reply(str(body.companion_id), tenant_id, body.user_id, body.message.strip(),
                                    display_name=body.display_name, tools=body.tools, require_live=True)
        return result.model_dump()
    return await _run(call, "widget_chat", log)


@public_router.post("/widget/chat/continue")
async def widget_continue(body: WidgetContinueIn, request: Request):
    """The page ran the tools (a browser tool can be faked by the user, so tools that touch money
    or other people's data belong on the business's server, through /chat)."""
    log = {"companion_id": None, "user_id": body.user_id}

    async def call():
        tenant_id = log["tenant_id"] = await _widget_tenant(request, body)
        _check_person(tenant_id, body.user_id)
        result = await engine.continue_reply(str(body.turn_id), tenant_id, body.results,
                                             external_user_id=body.user_id, require_live=True)
        return result.model_dump()
    return await _run(call, "widget_continue", log)
