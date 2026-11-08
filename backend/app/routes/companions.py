"""Settings for Aira Companion characters (dashboard login, settings.manage).

A tenant can run several characters, e.g. Astrotamil's "Jothidar AI" and "Vastu Guru".
Every query is scoped to the caller's tenant_id; another tenant's id answers 404.
No route here lists or reads end users' chats (that belongs to companion-dashboard).
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.companion import store
from app.companion.models import CompanionSettings, CompanionUpdate
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
