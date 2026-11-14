"""Settings for Aira Companion characters (dashboard login, companions.manage).

A tenant can run several characters, e.g. Astrotamil's "Jothidar AI" and "Vastu Guru".
Every query is scoped to the caller's tenant_id; another tenant's id answers 404.
No route here lists or reads end users' chats (that belongs to companion-dashboard).
Remembered facts (Level 2 memory) are readable here only for characters in privacy mode A.
"""
import asyncio
import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.companion import (engine, install, keys, memory, memory_refresh, memory_search, playground,
                           playground_people, store)
from app.companion.kb import search as kb_search, store as kb_store
from app.companion.models import AppTool, CompanionSettings, CompanionUpdate, MemoryScopeIn, ToolResult
from app.companion.tools import MAX_TOOLS, ToolsInvalid
from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission
from app.routes.auto_messages import _SlidingWindow
from app.services import ai_reply
from app.services.audit_log import record_audit_event

logger = logging.getLogger(__name__)
router = APIRouter()
require_companions_manage = require_permission("companions.manage")

_NOT_FOUND = "Character not found"


async def _check_tag(tenant_id: str, tag_id: str | None) -> None:
    if tag_id and not await store.tag_belongs_to_tenant(tenant_id, tag_id):
        raise HTTPException(status_code=422, detail="That books tag isn't one of your tags")


async def _check_collection(tenant_id: str, collection_id: str | None) -> None:
    if collection_id and not await kb_store.collection_belongs_to_tenant(tenant_id, collection_id):
        raise HTTPException(status_code=422, detail="That collection isn't one of your collections")


@router.get("")
async def list_companions(archived: bool = False, ctx: dict = Depends(require_companions_manage)):
    """Active characters. ?archived=true → the Archived tab."""
    return {"companions": await store.list_companions(ctx["tenant_id"], archived=archived)}


@router.post("", status_code=201)
async def create_companion(payload: CompanionSettings, ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    await _check_tag(tenant_id, str(payload.knowledge_tag_id) if payload.knowledge_tag_id else None)
    await _check_collection(
        tenant_id, str(payload.knowledge_collection_id) if payload.knowledge_collection_id else None)
    try:
        return await store.create_companion(tenant_id, payload)
    except store.DuplicateCompanionName:
        raise HTTPException(status_code=409, detail=await _duplicate_name_detail(tenant_id, payload.name))


async def _duplicate_name_detail(tenant_id: str, name: str) -> str:
    """An archived character still holds its name, so say where the clash is."""
    archived = await store.list_companions(tenant_id, archived=True)
    if any(c.get("name", "").strip().lower() == name.strip().lower() for c in archived):
        return "An archived character has that name. Restore it or delete it permanently."
    return "You already have a character with that name"


def _tenant_model(tenant_id: str) -> tuple[str | None, bool]:
    """(model name, ready). Ready means the model and its provider's API key are both set."""
    try:
        return ai_reply._resolve_provider(tenant_id)[1], True
    except RuntimeError:
        pass
    try:
        return ai_reply._provider_and_native_model(ai_reply._resolve_reply_model(tenant_id))[1], False
    except RuntimeError:
        return None, False


@router.get("/overview")
async def overview(ctx: dict = Depends(require_companions_manage)):
    """The Agents Overview page: setup checklist inputs and the four stat tiles."""
    tenant_id = ctx["tenant_id"]
    counts = await store.overview_counts(tenant_id)
    model, ready = await asyncio.to_thread(_tenant_model, tenant_id)
    return {**counts, "model": model, "model_ready": ready}


def _tenant_model_id(tenant_id: str) -> str | None:
    try:
        return ai_reply._resolve_reply_model(tenant_id)
    except RuntimeError:
        return None


@router.get("/models")
async def list_models(ctx: dict = Depends(require_companions_manage)):
    """The Playground model picker: models whose API key this business has, plus the live one."""
    tenant_id = ctx["tenant_id"]
    models = await asyncio.to_thread(ai_reply.available_reply_models, tenant_id)
    return {"models": models, "default": await asyncio.to_thread(_tenant_model_id, tenant_id),
            "playground_defaults": playground.live_defaults()}


@router.get("/requests")
async def list_requests(kind: Literal[store.REQUEST_KINDS] | None = None,  # type: ignore[valid-type]
                        status: Literal["ok", "error"] | None = None,
                        days: int = Query(7, ge=1, le=30),
                        ctx: dict = Depends(require_companions_manage)):
    """The Requests page: calls to the public API (no message text), newest first, with daily counts."""
    tenant_id = ctx["tenant_id"]
    log = await store.request_log(tenant_id, kind=kind, status=status, days=days)
    names = {c["id"]: c["name"] for c in await store.list_companions(tenant_id)}
    for r in log["requests"]:
        r["companion_name"] = names.get(r.get("companion_id"))
        if r.get("companion_id") not in names:
            r["companion_id"] = None   # another business's or a deleted id: don't echo it back
    return log


# Declared before /{companion_id} so "memory-settings" is never read as a character id.
@router.get("/memory-settings")
async def get_memory_settings(ctx: dict = Depends(require_companions_manage)):
    return {"memory_scope": await store.get_memory_scope(ctx["tenant_id"])}


@router.put("/memory-settings")
async def put_memory_settings(payload: MemoryScopeIn, ctx: dict = Depends(require_companions_manage)):
    """'character': each character remembers only what it was told. 'business': all characters
    share what the person told any of them (the widget must say so)."""
    return {"memory_scope": await store.set_memory_scope(ctx["tenant_id"], payload.memory_scope)}


# --- people (Memories page). DELETE /people/... is declared before /{companion_id} routes. -------

ExternalUserIdPath = Path(min_length=1, max_length=200)


@router.delete("/people/{external_user_id}", status_code=204)
async def forget_person(external_user_id: str = ExternalUserIdPath,
                        ctx: dict = Depends(require_companions_manage)):
    """"Delete this person": their chats with every character and every remembered fact,
    business-wide (engine.forget_person). Audited by our person id, never the external id."""
    tenant_id = ctx["tenant_id"]
    person = await store.find_end_user(tenant_id, external_user_id)
    if not person or not await engine.forget_person(tenant_id, external_user_id):
        raise HTTPException(status_code=404, detail="Person not found")
    _audit_forget(ctx, person["id"])


def _audit_forget(ctx: dict, end_user_id: str, *, test: bool = False) -> None:
    try:
        record_audit_event(
            get_supabase(), tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
            action="tenant.companion_person_forgotten", target_type="companion_end_user",
            target_id=end_user_id, metadata={"test_person": True} if test else {},
        )
    except Exception as exc:
        logger.warning("companion forget audit failed (%s)", type(exc).__name__)


# --- Playground test customers. Declared before /{companion_id} too. -----------------------------
# Scoped to the caller's own login: another login's test customers and real customers are 404 here.

class TestPersonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)


async def _usable_test_person(ctx: dict, external_user_id: str) -> None:
    try:
        await playground_people.require_usable(ctx["tenant_id"], ctx["user_id"], external_user_id)
    except playground_people.PersonError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)


@router.get("/test-people")
async def list_test_people(ctx: dict = Depends(require_companions_manage)):
    """The Playground's "Testing as" list: "You" first, then this login's test customers."""
    people = await playground_people.list_people(ctx["tenant_id"], ctx["user_id"])
    return {"people": people, "max": playground_people.MAX_TEST_PEOPLE}


@router.post("/test-people", status_code=201)
async def create_test_person(payload: TestPersonIn, ctx: dict = Depends(require_companions_manage)):
    try:
        return await playground_people.create(ctx["tenant_id"], ctx["user_id"], payload.name)
    except playground_people.PersonError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)


@router.delete("/test-people/{external_user_id}", status_code=204)
async def delete_test_person(external_user_id: str = ExternalUserIdPath, ctx: dict = Depends(require_companions_manage)):
    """Deletes a test customer: its chats with every character and every memory, like "Delete this person"."""
    try:
        person = await playground_people.delete(ctx["tenant_id"], ctx["user_id"], external_user_id)
    except playground_people.PersonError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    if person:
        _audit_forget(ctx, person["id"], test=True)


@router.post("/test-people/{external_user_id}/start-over")
async def start_over_test_person(external_user_id: str = ExternalUserIdPath,
                                 ctx: dict = Depends(require_companions_manage)):
    """Same test customer (id and name), no chats and no memories: the next chat is a first visit."""
    try:
        return await playground_people.start_over(ctx["tenant_id"], ctx["user_id"], external_user_id)
    except playground_people.PersonError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)


# --- chat API secret keys (Install tab). Declared before /{companion_id} too. --------------------

KEY_CHANGES_PER_MINUTE = 5
_NO_STORE = {"Cache-Control": "no-store"}
# Per tenant, in-process. Create and revoke share one budget.
_key_limiter = _SlidingWindow(KEY_CHANGES_PER_MINUTE, 60)


def _audit_key(ctx: dict, action: str, key_id: str, metadata: dict) -> None:
    # Never the key or its hash: the full key exists only in the create response.
    try:
        record_audit_event(
            get_supabase(), tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"),
            actor_role=ctx.get("role"), action=action, target_type="companion_api_key",
            target_id=key_id, metadata=metadata,
        )
    except Exception as exc:
        logger.warning("companion key audit failed (%s)", type(exc).__name__)


def _key_rate_check(tenant_id: str) -> None:
    if not _key_limiter.allow(tenant_id):
        raise HTTPException(status_code=429, detail="Too many key changes. Try again in a minute.",
                            headers={"Retry-After": "60"})


@router.get("/keys")
async def list_keys(ctx: dict = Depends(require_companions_manage)):
    return JSONResponse(content={"keys": await store.list_api_keys(ctx["tenant_id"]),
                                 "max_active": keys.MAX_ACTIVE_KEYS}, headers=_NO_STORE)


@router.post("/keys", status_code=201)
async def create_key(ctx: dict = Depends(require_companions_manage)):
    """The full key is in this response only. At most 2 active keys, so the owner can rotate."""
    tenant_id = ctx["tenant_id"]
    _key_rate_check(tenant_id)
    if await store.count_active_api_keys(tenant_id) >= keys.MAX_ACTIVE_KEYS:
        raise HTTPException(status_code=409, detail="You already have 2 active keys. Revoke one first.")
    raw, prefix, key_hash = keys.generate_key()
    row = await store.create_api_key(tenant_id, prefix, key_hash, ctx.get("user_id"))
    _audit_key(ctx, "tenant.companion_key_created", row["id"], {"prefix": prefix})
    logger.info("companion key created tenant=%s key=%s", tenant_id, row["id"])
    return JSONResponse(status_code=201, content={**row, "key": raw}, headers=_NO_STORE)


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_key(key_id: UUID, ctx: dict = Depends(require_companions_manage)):
    """Takes effect on the next request: the API and every widget signed with it stop working."""
    tenant_id = ctx["tenant_id"]
    _key_rate_check(tenant_id)
    if not await store.revoke_api_key(tenant_id, str(key_id)):
        raise HTTPException(status_code=404, detail="Key not found")
    _audit_key(ctx, "tenant.companion_key_revoked", str(key_id), {})
    logger.info("companion key revoked tenant=%s key=%s", tenant_id, key_id)


@router.get("/{companion_id}")
async def get_companion(companion_id: UUID, ctx: dict = Depends(require_companions_manage)):
    row = await store.get_companion(ctx["tenant_id"], str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


@router.patch("/{companion_id}")
async def update_companion(companion_id: UUID, payload: CompanionUpdate,
                           ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    current = await store.get_companion(tenant_id, str(companion_id))
    if not current:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    changes = payload.changes()
    if current.get("archived_at") and "status" in changes:
        raise HTTPException(status_code=409, detail="This character is archived. Restore it first.")
    engine_switched = changes.get("memory_engine", current.get("memory_engine", "card")) != \
        current.get("memory_engine", "card")
    await _check_tag(tenant_id, changes.get("knowledge_tag_id"))
    await _check_collection(tenant_id, changes.get("knowledge_collection_id"))
    try:
        row = await store.update_companion(tenant_id, str(companion_id), changes)
    except store.DuplicateCompanionName:
        raise HTTPException(status_code=409, detail=await _duplicate_name_detail(tenant_id, changes.get("name", "")))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if engine_switched:
        # The new engine relearns from each person's latest messages; the old engine's facts stay
        # until forget-me or a manual delete.
        await store.reset_watermarks(tenant_id, str(companion_id))
    return row


def _audit_character(ctx: dict, action: str, row: dict) -> None:
    try:
        record_audit_event(
            get_supabase(), tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"),
            actor_role=ctx.get("role"), action=action, target_type="companion",
            target_id=row["id"], metadata={"name": row.get("name"), "status": row.get("status")},
        )
    except Exception as exc:
        logger.warning("companion %s audit failed (%s)", action, type(exc).__name__)


@router.post("/{companion_id}/archive")
async def archive_companion(companion_id: UUID, ctx: dict = Depends(require_companions_manage)):
    """Hide from the list and stop answering (paused). Its chats and memory are kept."""
    tenant_id = ctx["tenant_id"]
    before = await store.get_companion(tenant_id, str(companion_id))
    row = await store.archive_companion(tenant_id, str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if before and not before.get("archived_at"):
        _audit_character(ctx, "tenant.companion_archived", before)
    return row


@router.post("/{companion_id}/restore")
async def restore_companion(companion_id: UUID, ctx: dict = Depends(require_companions_manage)):
    """Back to the list as Draft."""
    tenant_id = ctx["tenant_id"]
    before = await store.get_companion(tenant_id, str(companion_id))
    row = await store.restore_companion(tenant_id, str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if before and before.get("archived_at"):
        _audit_character(ctx, "tenant.companion_restored", row)
    return row


@router.delete("/{companion_id}", status_code=204)
async def delete_companion(companion_id: UUID, ctx: dict = Depends(require_companions_manage)):
    """Delete permanently, with its chats and memory. Cannot be undone."""
    tenant_id = ctx["tenant_id"]
    row = await store.get_companion(tenant_id, str(companion_id))
    if not row or not await store.delete_companion(tenant_id, str(companion_id)):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    _audit_character(ctx, "tenant.companion_deleted", row)


_SEARCH_MAX = 20


class PlaygroundSettings(BaseModel):
    """The Playground's search / memory settings. Left out, every one is what live chat uses."""
    model_config = ConfigDict(extra="forbid")
    sources: Literal["all", "memories", "knowledge"] = "all"
    results: int | None = Field(None, ge=1, le=_SEARCH_MAX)
    memory_floor: float | None = Field(None, ge=0.0, le=1.0)
    judge_min: int | None = Field(None, ge=0, le=3)
    rerank: bool = True
    rewrite: bool = True
    memory_card: bool = True
    mode: Literal["auto", "agentic"] = "auto"

    def overrides(self) -> playground.Overrides:
        return playground.Overrides(**self.model_dump())


class TestChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    tools: list[AppTool] = Field(default_factory=list)
    model: str | None = Field(None, max_length=100)   # Playground picker; must be one the tenant has a key for
    use_memory: bool = True                           # False = the "Compare without memory" reply
    settings: PlaygroundSettings | None = None        # Playground settings panel; None = live behaviour
    test_person: str | None = Field(None, min_length=1, max_length=200)  # a test customer's id; None = "You"


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
async def test_chat_continue(payload: ContinueIn, ctx: dict = Depends(require_companions_manage)):
    """The owner types the tool result by hand (playing the app) and the reply finishes."""
    try:
        result = await engine.continue_reply(str(payload.turn_id), ctx["tenant_id"], payload.results)
    except _EXPECTED as exc:
        raise _http_error(exc)
    return result.model_dump()


@router.post("/{companion_id}/test-chat")
async def test_chat(companion_id: UUID, payload: TestChatIn, ctx: dict = Depends(require_companions_manage)):
    """The owner chats with a character from the dashboard, as "You" ("owner-test:<user_id>") or one of
    their test customers (playground_people). Either way it is a test person,
    so it never mixes with a real end user's history."""
    tenant_id = ctx["tenant_id"]
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Type a message first")
    person_id = payload.test_person or playground_people.you_id(ctx["user_id"])
    await _usable_test_person(ctx, person_id)
    if payload.model:
        allowed = {m["id"] for m in await asyncio.to_thread(ai_reply.available_reply_models, tenant_id)}
        if payload.model not in allowed:
            raise HTTPException(status_code=422, detail="That model isn't set up for your business")
    ov = (payload.settings or PlaygroundSettings()).overrides()
    try:
        with playground.use(ov):
            result = await engine.reply(
                str(companion_id), tenant_id, person_id, message,
                tools=payload.tools if payload.use_memory else [], model=payload.model, use_memory=payload.use_memory)
    except _EXPECTED as exc:
        raise _http_error(exc)
    companion = await store.get_companion(tenant_id, str(companion_id)) or {}
    model = payload.model or engine.character_model(companion)
    person = await store.find_end_user(tenant_id, person_id)
    status = await memory_refresh.status({**companion, "tenant_id": tenant_id}, person and person["id"])
    return {**result.model_dump(), "model": ai_reply.REPLY_MODELS.get(model, model), "trace": ov.trace,
            "memory": status, "problem": ov.problem}



@router.get("/{companion_id}/install")
async def get_install(companion_id: UUID, ctx: dict = Depends(require_companions_manage)):
    """The Install tab: copy-paste widget and server code for this character, plus key status."""
    tenant_id = ctx["tenant_id"]
    row = await store.get_companion(tenant_id, str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    info = install.install_info(row)
    info["has_active_key"] = await store.count_active_api_keys(tenant_id) > 0
    return info


ExternalUserId = Path(min_length=1, max_length=200)
_PRIVATE = "This character is in privacy mode B: the business can't read what it remembers"


async def _readable_character(tenant_id: str, companion_id: UUID) -> dict:
    row = await store.get_companion(tenant_id, str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if row.get("privacy_mode") == "B":
        raise HTTPException(status_code=403, detail=_PRIVATE)
    return row


@router.get("/{companion_id}/people")
async def list_people(companion_id: UUID, q: str = Query("", max_length=100),
                      limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000),
                      ctx: dict = Depends(require_companions_manage)):
    """People this character talked to, newest first. fact_count is None in privacy mode B
    (the business can't see that character's memory)."""
    tenant_id = ctx["tenant_id"]
    row = await store.get_companion(tenant_id, str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    people, total = await store.list_people(tenant_id, str(companion_id), q, limit, offset)
    private = row.get("privacy_mode") == "B"
    return {
        "people": [
            {"external_user_id": p["external_user_id"], "display_name": p["display_name"],
             "fact_count": None if private else p["fact_count"], "message_count": p["message_count"],
             "last_seen_at": p["last_seen_at"], "is_test": p.get("is_test", False)}
            for p in people
        ],
        "total": total,
        "privacy_mode": row.get("privacy_mode", "A"),
    }


async def _test_pair(companion_id: UUID, external_user_id: str, ctx: dict) -> tuple[dict, dict | None]:
    """(character, person or None) for a Playground memory call; the person must be the caller's own."""
    tenant_id = ctx["tenant_id"]
    await _usable_test_person(ctx, external_user_id)
    companion = await store.get_companion(tenant_id, str(companion_id))
    if not companion:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return {**companion, "tenant_id": tenant_id}, await store.find_end_user(tenant_id, external_user_id)


@router.get("/{companion_id}/test-people/{external_user_id}/memory")
async def test_person_memory_status(companion_id: UUID, external_user_id: str = ExternalUserId,
                                    ctx: dict = Depends(require_companions_manage)):
    """The Playground memory line: {level, unread, saves_at}."""
    companion, person = await _test_pair(companion_id, external_user_id, ctx)
    return await memory_refresh.status(companion, person and person["id"])


_SAVE_OUTCOME = {"ok": "saved", "busy": "busy", "waiting": "waiting"}


@router.post("/{companion_id}/test-people/{external_user_id}/save-memory")
async def save_test_person_memory(companion_id: UUID, external_user_id: str = ExternalUserId,
                                  ctx: dict = Depends(require_companions_manage)):
    """"Save now": runs the memory step the Nth message would start, at once (one AI call).
    facts = what the character now remembers about this person (None in privacy mode B)."""
    companion, person = await _test_pair(companion_id, external_user_id, ctx)
    if (companion.get("memory_level") or 1) != 2:
        raise HTTPException(status_code=409, detail="This character keeps only recent chat, so there is nothing to save.")
    if not person:
        return {"outcome": "nothing_new", "facts": 0}
    outcome = await memory_refresh.save_now(companion, person["id"])
    if outcome == "failed":
        raise HTTPException(status_code=502, detail="The AI couldn't read the chat just now. Try again in a few minutes.")
    if companion.get("privacy_mode") == "B":
        facts = None
    else:
        facts = len(await store.list_facts(ctx["tenant_id"], person["id"], str(companion_id), include_closed=False))
    return {"outcome": _SAVE_OUTCOME.get(outcome, "nothing_new"), "facts": facts}


class SearchIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    in_: Literal["knowledge", "memories", "all"] = Field(alias="in")
    q: str = Field(min_length=1, max_length=500)
    limit: int = Field(5, ge=1, le=_SEARCH_MAX)
    external_user_id: str | None = Field(None, min_length=1, max_length=200)
    settings: PlaygroundSettings | None = None


def _memory_row(hit: dict) -> dict:
    return {"kind": hit["kind"], "day": str(hit.get("day") or "")[:10] or None,
            "text": memory_search._hit_text(hit), "meaning": round(hit["vector"], 3) or None,
            "words": round(hit["trigram"], 3) or None, "kept": hit["kept"]}


@router.post("/{companion_id}/search")
async def search(companion_id: UUID, payload: SearchIn, ctx: dict = Depends(require_companions_manage)):
    """The Playground "Search" tab: what a character would find, with the settings panel applied.

    knowledge: every passage the judge looked at (document, pages, meaning score, judge 0-3 or None
    with the judge off, kept). memories: with a person, the meaning + word search live chat uses,
    including pieces below the strictness floor (kept False); without one, word-matched facts
    across everyone (memory_mode "words"). Privacy mode B hides memories. The query is never logged."""
    tenant_id = ctx["tenant_id"]
    q = payload.q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="Type something to search for")
    row = await store.get_companion(tenant_id, str(companion_id))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    # results stays None unless the owner changed it, so default settings keep live's 3 / 4 passages.
    ov = (payload.settings or PlaygroundSettings()).overrides()
    out: dict = {"in": payload.in_, "knowledge": [], "memories": [], "rewritten": None, "needs_docs": True,
                 "no_collection": False, "knowledge_error": False, "memory_mode": None, "memories_hidden": None}

    if payload.in_ in ("knowledge", "all"):
        found = None
        collection_id = row.get("knowledge_collection_id")
        if not collection_id:      # this character reads no collection: nothing to find
            out["no_collection"] = True
        else:
            with playground.use(ov):
                try:
                    found = await kb_search.search(tenant_id, collection_id, q, [], companion_id=str(companion_id))
                except Exception as exc:
                    logger.warning("companion %s: knowledge search failed (%s)", companion_id, type(exc).__name__)
                    found = None
            if (found is None or found.failed) and payload.in_ == "knowledge":
                raise HTTPException(status_code=502, detail="Knowledge search isn't available right now. Try again.")
            if found is None or found.failed:      # "all": the memories still show
                out["knowledge_error"] = True
                found = None
        if found is not None:
            out["needs_docs"] = found.needs_docs
            out["rewritten"] = ov.rewritten
            # Normally kb-search recorded every passage it judged; if it recorded none (a shortcut-only
            # result, or a stubbed search) the passages it returned are shown as kept.
            candidates = ov.kb_candidates or [
                {"document": p.document_title, "page_from": p.page_from, "page_to": p.page_to,
                 "heading_path": p.heading_path, "text": p.text, "tier": p.tier, "step": "main",
                 "score": p.score, "meaning": None, "kept": True} for p in found.passages[:payload.limit]]
            out["knowledge"] = sorted(({k: v for k, v in c.items() if k != "id"} for c in candidates),
                                      key=lambda c: (not c["kept"], -(c["score"] or 0), -(c["meaning"] or 0)))

    if payload.in_ in ("memories", "all"):
        if row.get("privacy_mode") == "B":
            if payload.in_ == "memories":
                raise HTTPException(status_code=403, detail=_PRIVATE)
            out["memories_hidden"] = "private"
        elif payload.external_user_id:
            person = await store.find_end_user(tenant_id, payload.external_user_id)
            if not person or person.get("forgotten_at"):
                raise HTTPException(status_code=404, detail="No one with that user id has talked to your characters")
            with playground.use(ov):
                await memory_search.search(tenant_id, str(companion_id), person["id"], q, with_recent=False)
            # With memory scope "business" the search also reads other characters' pieces (as chat does).
            # What a privacy-mode-B character learned is never shown to the owner.
            private = {str(c["id"]) for c in await store.list_companions(tenant_id) if c.get("privacy_mode") == "B"}
            hits = [h for h in ov.memory_candidates if str(h.get("companion_id")) not in private]
            kept = [_memory_row(h) for h in hits if h["kept"]][:payload.limit]
            out["memories"] = kept + [_memory_row(h) for h in hits if not h["kept"]]
            out["memory_mode"] = "meaning"
        else:
            facts = await store.search_facts(tenant_id, str(companion_id), q, payload.limit)
            out["memories"] = [{**f, "kind": "fact", "day": str(f.get("learned_at") or "")[:10] or None,
                                "meaning": None, "words": None, "kept": True} for f in facts]
            out["memory_mode"] = "words"
    return out


@router.get("/{companion_id}/people/{external_user_id}/memory")
async def list_person_memory(companion_id: UUID, external_user_id: str = ExternalUserId,
                             ctx: dict = Depends(require_companions_manage)):
    """What the character remembers about one person (privacy mode A only)."""
    tenant_id = ctx["tenant_id"]
    await _readable_character(tenant_id, companion_id)
    facts = await memory.list_memory(tenant_id, str(companion_id), external_user_id)
    return {"facts": [f.model_dump() for f in facts], "memory_scope": await store.get_memory_scope(tenant_id)}


@router.delete("/{companion_id}/people/{external_user_id}/memory/{fact_id}", status_code=204)
async def delete_person_fact(companion_id: UUID, fact_id: UUID, external_user_id: str = ExternalUserId,
                             ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    await _readable_character(tenant_id, companion_id)
    if not await memory.forget_fact(tenant_id, str(companion_id), external_user_id, str(fact_id)):
        raise HTTPException(status_code=404, detail="Fact not found")
    logger.info("companion %s: owner deleted one remembered fact", companion_id)


@router.get("/{companion_id}/people/{external_user_id}/diary")
async def list_person_diary(companion_id: UUID, external_user_id: str = ExternalUserId,
                            ctx: dict = Depends(require_companions_manage)):
    """The Diary tab (privacy mode A only): "earlier today" plus one line per past day."""
    tenant_id = ctx["tenant_id"]
    await _readable_character(tenant_id, companion_id)
    return await memory.list_diary(tenant_id, str(companion_id), external_user_id)


@router.delete("/{companion_id}/people/{external_user_id}/diary/{day}", status_code=204)
async def delete_person_diary_day(companion_id: UUID, day: date, external_user_id: str = ExternalUserId,
                                  ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    await _readable_character(tenant_id, companion_id)
    if not await memory.forget_diary_day(tenant_id, str(companion_id), external_user_id, day.isoformat()):
        raise HTTPException(status_code=404, detail="Diary line not found")
    logger.info("companion %s: owner deleted one diary line", companion_id)


@router.delete("/{companion_id}/people/{external_user_id}/recap", status_code=204)
async def delete_person_recap(companion_id: UUID, external_user_id: str = ExternalUserId,
                              ctx: dict = Depends(require_companions_manage)):
    tenant_id = ctx["tenant_id"]
    await _readable_character(tenant_id, companion_id)
    if not await memory.forget_recap(tenant_id, str(companion_id), external_user_id):
        raise HTTPException(status_code=404, detail="Nothing from today to delete")
    logger.info("companion %s: owner deleted the earlier-today note", companion_id)
