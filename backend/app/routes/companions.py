"""Settings for Aira Companion characters (dashboard login, settings.manage).

A tenant can run several characters, e.g. Astrotamil's "Jothidar AI" and "Vastu Guru".
Every query is scoped to the caller's tenant_id; another tenant's id answers 404.
No route here lists or reads end users' chats (that belongs to companion-dashboard).
Remembered facts (Level 2 memory) are readable here only for characters in privacy mode A.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.companion import engine, memory, store
from app.companion.models import AppTool, CompanionSettings, CompanionUpdate, MemoryScopeIn, ToolResult
from app.companion.tools import MAX_TOOLS, ToolsInvalid
from app.dependencies.tenant import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
require_settings_manage = require_permission("settings.manage")

_NOT_FOUND = "Character not found"


async def _check_tag(tenant_id: str, tag_id: str | None) -> None:
    if tag_id and not await store.tag_belongs_to_tenant(tenant_id, tag_id):
        raise HTTPException(status_code=422, detail="That books tag isn't one of your tags")


@router.get("")
async def list_companions(ctx: dict = Depends(require_settings_manage)):
    return {"companions": await store.list_companions(ctx["tenant_id"])}


@router.post("", status_code=201)
async def create_companion(payload: CompanionSettings, ctx: dict = Depends(require_settings_manage)):
    tenant_id = ctx["tenant_id"]
    await _check_tag(tenant_id, str(payload.knowledge_tag_id) if payload.knowledge_tag_id else None)
    try:
        return await store.create_companion(tenant_id, payload)
    except store.DuplicateCompanionName:
        raise HTTPException(status_code=409, detail="You already have a character with that name")


# Declared before /{companion_id} so "memory-settings" is never read as a character id.
@router.get("/memory-settings")
async def get_memory_settings(ctx: dict = Depends(require_settings_manage)):
    return {"memory_scope": await store.get_memory_scope(ctx["tenant_id"])}


@router.put("/memory-settings")
async def put_memory_settings(payload: MemoryScopeIn, ctx: dict = Depends(require_settings_manage)):
    """'character': each character remembers only what it was told. 'business': all characters
    share what the person told any of them (the widget must say so)."""
    return {"memory_scope": await store.set_memory_scope(ctx["tenant_id"], payload.memory_scope)}


@router.get("/{companion_id}")
async def get_companion(companion_id: UUID, ctx: dict = Depends(require_settings_manage)):
    row = await store.get_companion(ctx["tenant_id"], str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


@router.patch("/{companion_id}")
async def update_companion(companion_id: UUID, payload: CompanionUpdate,
                           ctx: dict = Depends(require_settings_manage)):
    tenant_id = ctx["tenant_id"]
    if not await store.get_companion(tenant_id, str(companion_id)):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    changes = payload.changes()
    await _check_tag(tenant_id, changes.get("knowledge_tag_id"))
    try:
        row = await store.update_companion(tenant_id, str(companion_id), changes)
    except store.DuplicateCompanionName:
        raise HTTPException(status_code=409, detail="You already have a character with that name")
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


class TestChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    tools: list[AppTool] = Field(default_factory=list)


class ContinueIn(BaseModel):
    turn_id: UUID
    results: list[ToolResult] = Field(default_factory=list, max_length=MAX_TOOLS)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (engine.CompanionNotFound, engine.TurnExpired)):
        detail = _NOT_FOUND if isinstance(exc, engine.CompanionNotFound) else \
            "This tool turn has expired or was already used. Send the message again."
        return HTTPException(status_code=404, detail=detail)
    if isinstance(exc, ToolsInvalid):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, engine.CompanionPaused):
        return HTTPException(status_code=409, detail="This character is paused. Set it to draft or live to chat.")
    if isinstance(exc, engine.CompanionMisconfigured):
        return HTTPException(status_code=400, detail="Set your AI model and its API key in Settings first")
    return HTTPException(status_code=503, detail="The companion is busy right now. Try again in a few seconds.")


_EXPECTED = (engine.CompanionError, ToolsInvalid)


@router.post("/test-chat/continue")
async def test_chat_continue(payload: ContinueIn, ctx: dict = Depends(require_settings_manage)):
    """The owner types the tool result by hand (playing the app) and the reply finishes."""
    try:
        result = await engine.continue_reply(str(payload.turn_id), ctx["tenant_id"], payload.results)
    except _EXPECTED as exc:
        raise _http_error(exc)
    return result.model_dump()


@router.post("/{companion_id}/test-chat")
async def test_chat(companion_id: UUID, payload: TestChatIn, ctx: dict = Depends(require_settings_manage)):
    """The owner chats with a character from the dashboard. Stored as person "owner-test:<user_id>",
    so it never mixes with a real end user's history."""
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Type a message first")
    try:
        result = await engine.reply(
            str(companion_id), ctx["tenant_id"], f"owner-test:{ctx['user_id']}", message, tools=payload.tools)
    except _EXPECTED as exc:
        raise _http_error(exc)
    return result.model_dump()


ExternalUserId = Path(min_length=1, max_length=200)
_PRIVATE = "This character is in privacy mode B: the business can't read what it remembers"


async def _readable_character(tenant_id: str, companion_id: UUID) -> dict:
    row = await store.get_companion(tenant_id, str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if row.get("privacy_mode") == "B":
        raise HTTPException(status_code=403, detail=_PRIVATE)
    return row


@router.get("/{companion_id}/people/{external_user_id}/memory")
async def list_person_memory(companion_id: UUID, external_user_id: str = ExternalUserId,
                             ctx: dict = Depends(require_settings_manage)):
    """What the character remembers about one person (privacy mode A only)."""
    tenant_id = ctx["tenant_id"]
    await _readable_character(tenant_id, companion_id)
    facts = await memory.list_memory(tenant_id, str(companion_id), external_user_id)
    return {"facts": [f.model_dump() for f in facts], "memory_scope": await store.get_memory_scope(tenant_id)}


@router.delete("/{companion_id}/people/{external_user_id}/memory/{fact_id}", status_code=204)
async def delete_person_fact(companion_id: UUID, fact_id: UUID, external_user_id: str = ExternalUserId,
                             ctx: dict = Depends(require_settings_manage)):
    tenant_id = ctx["tenant_id"]
    await _readable_character(tenant_id, companion_id)
    if not await memory.forget_fact(tenant_id, str(companion_id), external_user_id, str(fact_id)):
        raise HTTPException(status_code=404, detail="Fact not found")
    logger.info("companion %s: owner deleted one remembered fact", companion_id)
