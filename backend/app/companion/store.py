"""Every DB call for the companion tables. The only module that touches them.

Uses the service-role client (RLS bypassed), so EVERY query filters on tenant_id itself.
Sync supabase calls run in a thread so they don't block the event loop.
"""
import asyncio
from datetime import datetime, timezone

from app.companion.models import CompanionSettings
from app.db.supabase import get_supabase


class DuplicateCompanionName(Exception):
    """This tenant already has a character with that name."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "23505" or "23505" in str(exc) or "duplicate key" in str(exc)


async def create_companion(tenant_id: str, settings: CompanionSettings) -> dict:
    row = {**settings.model_dump(mode="json"), "tenant_id": tenant_id}

    def _q():
        return get_supabase().table("companions").insert(row).execute().data

    try:
        rows = await asyncio.to_thread(_q)
    except Exception as exc:
        if _is_unique_violation(exc):
            raise DuplicateCompanionName(settings.name) from exc
        raise
    return rows[0]


async def get_companion(tenant_id: str, companion_id: str) -> dict | None:
    def _q():
        return (
            get_supabase().table("companions").select("*")
            .eq("tenant_id", tenant_id).eq("id", companion_id)
            .limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else None


async def list_companions(tenant_id: str) -> list[dict]:
    def _q():
        return (
            get_supabase().table("companions").select("*")
            .eq("tenant_id", tenant_id).order("created_at").execute().data
        )
    return await asyncio.to_thread(_q) or []


async def update_companion(tenant_id: str, companion_id: str, changes: dict) -> dict | None:
    """Apply a partial update. Returns the updated row, or None if it isn't this tenant's."""
    if not changes:
        return await get_companion(tenant_id, companion_id)
    payload = {**changes, "updated_at": _now()}
    payload.pop("tenant_id", None)
    payload.pop("id", None)

    def _q():
        return (
            get_supabase().table("companions").update(payload)
            .eq("tenant_id", tenant_id).eq("id", companion_id).execute().data
        )

    try:
        rows = await asyncio.to_thread(_q)
    except Exception as exc:
        if _is_unique_violation(exc):
            raise DuplicateCompanionName(changes.get("name", "")) from exc
        raise
    return rows[0] if rows else None


async def tag_belongs_to_tenant(tenant_id: str, tag_id: str) -> bool:
    """A character's books tag must be one of this tenant's broadcast_tags."""
    def _q():
        return (
            get_supabase().table("broadcast_tags").select("id")
            .eq("tenant_id", tenant_id).eq("id", tag_id).limit(1).execute().data
        )
    return bool(await asyncio.to_thread(_q))
