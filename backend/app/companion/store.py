"""Every DB call for the companion tables. The only module that touches them.

Uses the service-role client (RLS bypassed), so EVERY query filters on tenant_id itself.
Sync supabase calls run in a thread so they don't block the event loop.
"""
import asyncio
from datetime import datetime, timedelta, timezone

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


CONVERSATION_GAP = timedelta(hours=24)
MAX_CONTENT = 8000


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def find_or_create_end_user(tenant_id: str, external_user_id: str, display_name: str | None = None) -> dict:
    """One row per person per business. first_seen_at / forgotten_at are never sent, so they survive."""
    payload = {"tenant_id": tenant_id, "external_user_id": external_user_id, "last_seen_at": _now()}
    name = (display_name or "").strip()[:100]
    if name:
        payload["display_name"] = name

    def _q():
        return (
            get_supabase().table("companion_end_users")
            .upsert(payload, on_conflict="tenant_id,external_user_id").execute().data
        )
    return (await asyncio.to_thread(_q))[0]


async def open_conversation(tenant_id: str, companion_id: str, end_user_id: str, default_mood: str) -> dict:
    """The live conversation for this (character, person), or a new one after 24 h of silence.
    A new one starts in the previous conversation's mood."""
    def _latest():
        return (
            get_supabase().table("companion_conversations").select("*")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .order("last_message_at", desc=True).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_latest)
    previous = rows[0] if rows else None
    if previous and datetime.now(timezone.utc) - _parse_ts(previous["last_message_at"]) < CONVERSATION_GAP:
        return previous

    now = _now()
    row = {
        "tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
        "mood": previous["mood"] if previous else default_mood,
        "started_at": now, "last_message_at": now, "message_count": 0,
    }

    def _insert():
        return get_supabase().table("companion_conversations").insert(row).execute().data
    return (await asyncio.to_thread(_insert))[0]


async def save_message(tenant_id: str, conversation: dict, role: str, content: str,
                       *, mood: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    row = {
        "tenant_id": tenant_id, "companion_id": conversation["companion_id"],
        "conversation_id": conversation["id"], "end_user_id": conversation["end_user_id"],
        "role": role, "content": content[:MAX_CONTENT], "mood": mood, "tool_calls": tool_calls,
    }
    count = conversation["message_count"] + 1  # read-modify-write: fine for v1, not atomic
    now = _now()

    def _q():
        db = get_supabase()
        saved = db.table("companion_messages").insert(row).execute().data[0]
        (
            db.table("companion_conversations").update({"message_count": count, "last_message_at": now})
            .eq("tenant_id", tenant_id).eq("id", conversation["id"]).execute()
        )
        return saved

    saved = await asyncio.to_thread(_q)
    conversation["message_count"], conversation["last_message_at"] = count, now
    return saved


async def set_conversation_mood(tenant_id: str, conversation_id: str, mood: str) -> None:
    def _q():
        (
            get_supabase().table("companion_conversations").update({"mood": mood})
            .eq("tenant_id", tenant_id).eq("id", conversation_id).execute()
        )
    await asyncio.to_thread(_q)


async def recent_messages(tenant_id: str, companion_id: str, end_user_id: str, limit: int = 10) -> list[dict]:
    """Last `limit` messages of this character with this person, across conversations, oldest first."""
    def _q():
        return (
            get_supabase().table("companion_messages").select("role, content, mood, created_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .order("created_at", desc=True).limit(limit).execute().data
        )
    rows = await asyncio.to_thread(_q) or []
    return list(reversed(rows))


# --- pending turns (a reply paused while the client's app runs a tool) -------------------------

PENDING_TTL = timedelta(minutes=2)


def _sweep_expired(db) -> None:
    """Deletes every tenant's expired pending turns. Deliberately not tenant-filtered: it only
    removes rows past expires_at, so no paused prompt outlives its 2 minutes. No cron needed."""
    db.table("companion_pending_turns").delete().lt("expires_at", _now()).execute()


async def create_pending_turn(tenant_id: str, companion_id: str, conversation_id: str,
                              state: dict, tools: list[dict], round_no: int) -> str:
    """Saves the paused turn and returns its id (the turn_id given to the app).
    state holds the prompt so far plus what's needed to finish the reply later."""
    row = {
        "tenant_id": tenant_id, "companion_id": companion_id, "conversation_id": conversation_id,
        "messages": state, "tools": tools, "round": round_no,
        "expires_at": (datetime.now(timezone.utc) + PENDING_TTL).isoformat(),
    }

    def _q():
        db = get_supabase()
        _sweep_expired(db)
        return db.table("companion_pending_turns").insert(row).execute().data[0]["id"]
    return await asyncio.to_thread(_q)


async def take_pending_turn(tenant_id: str, turn_id: str) -> dict | None:
    """Consumes a live turn: deleted as it's read, so one turn_id can be continued only once.
    Unknown, expired or another tenant's turn → None."""
    def _q():
        db = get_supabase()
        _sweep_expired(db)
        return (
            db.table("companion_pending_turns").delete()
            .eq("tenant_id", tenant_id).eq("id", turn_id).gt("expires_at", _now()).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else None


async def get_conversation(tenant_id: str, conversation_id: str) -> dict | None:
    def _q():
        return (
            get_supabase().table("companion_conversations").select("*")
            .eq("tenant_id", tenant_id).eq("id", conversation_id).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else None


# --- forget (business-wide: every character's chats with this person) ---------------------------

async def find_end_user(tenant_id: str, external_user_id: str) -> dict | None:
    def _q():
        return (
            get_supabase().table("companion_end_users").select("*")
            .eq("tenant_id", tenant_id).eq("external_user_id", external_user_id).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else None


async def forget_end_user(tenant_id: str, end_user_id: str) -> None:
    """Hard-deletes the person's pending turns, messages and conversations with every character
    of this tenant, then blanks their name and stamps forgotten_at. The person row stays, so a
    later message starts fresh (empty history, default mood) under the same external id."""
    def _q():
        db = get_supabase()
        conv_ids = [c["id"] for c in (
            db.table("companion_conversations").select("id")
            .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute().data or [])]
        if conv_ids:
            (db.table("companion_pending_turns").delete()
             .eq("tenant_id", tenant_id).in_("conversation_id", conv_ids).execute())
        db.table("companion_messages").delete().eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute()
        (db.table("companion_conversations").delete()
         .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute())
        (db.table("companion_end_users").update({"display_name": None, "forgotten_at": _now()})
         .eq("tenant_id", tenant_id).eq("id", end_user_id).execute())
    await asyncio.to_thread(_q)


# --- Level 2 memory: facts, watermarks, tenant settings (migration 249) -------------------------

FACT_SECTIONS = ("profile", "people", "life", "preferences", "threads")
MAX_FACTS_PER_PAIR = 60
CLOSED_FACT_WINDOW = timedelta(days=90)


async def get_memory_scope(tenant_id: str) -> str:
    """'character' (default: each character keeps its own facts) or 'business' (shared)."""
    def _q():
        return (
            get_supabase().table("companion_tenant_settings").select("memory_scope")
            .eq("tenant_id", tenant_id).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0]["memory_scope"] if rows else "character"


async def set_memory_scope(tenant_id: str, scope: str) -> str:
    if scope not in ("character", "business"):
        raise ValueError("memory_scope must be 'character' or 'business'")

    def _q():
        (
            get_supabase().table("companion_tenant_settings")
            .upsert({"tenant_id": tenant_id, "memory_scope": scope, "updated_at": _now()},
                    on_conflict="tenant_id").execute()
        )
    await asyncio.to_thread(_q)
    return scope


async def list_facts(tenant_id: str, end_user_id: str, companion_id: str | None = None,
                     *, include_closed: bool = True) -> list[dict]:
    """This person's active facts, plus facts closed in the last 90 days. companion_id=None reads
    every character's facts (business scope). Oldest first."""
    since = (datetime.now(timezone.utc) - CLOSED_FACT_WINDOW).isoformat()

    def _base():
        q = (get_supabase().table("companion_memory_facts").select("*")
             .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id))
        return q.eq("companion_id", companion_id) if companion_id else q

    def _q():
        active = _base().eq("status", "active").order("created_at").execute().data or []
        closed = (_base().eq("status", "closed").gte("updated_at", since).order("created_at").execute().data
                  or []) if include_closed else []
        return active + closed
    return await asyncio.to_thread(_q)


async def get_fact(tenant_id: str, fact_id: str) -> dict | None:
    def _q():
        return (
            get_supabase().table("companion_memory_facts").select("*")
            .eq("tenant_id", tenant_id).eq("id", fact_id).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else None


def _make_room(db, tenant_id: str, companion_id: str, end_user_id: str) -> bool:
    """Keeps a (character, person) pair under MAX_FACTS_PER_PAIR rows before an add: deletes the
    oldest closed fact first, then the oldest active preference. False if neither exists."""
    rows = (
        db.table("companion_memory_facts").select("id, status, section, created_at")
        .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
        .order("created_at").execute().data or []
    )
    if len(rows) < MAX_FACTS_PER_PAIR:
        return True
    victim = next((r for r in rows if r["status"] == "closed"), None) or next(
        (r for r in rows if r["status"] == "active" and r["section"] == "preferences"), None)
    if not victim:
        return False
    db.table("companion_memory_facts").delete().eq("tenant_id", tenant_id).eq("id", victim["id"]).execute()
    return True


async def add_fact(tenant_id: str, companion_id: str, end_user_id: str, section: str, text: str,
                   valid_from: str | None = None, valid_to: str | None = None) -> dict | None:
    """Adds one active fact. None when the pair is full (60 rows, nothing evictable)."""
    if section not in FACT_SECTIONS:
        raise ValueError(f"unknown section {section!r}")
    now = _now()
    row = {
        "tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
        "section": section, "text": text.strip()[:300], "valid_from": valid_from, "valid_to": valid_to,
        "status": "active", "created_at": now, "updated_at": now,
    }

    def _q():
        db = get_supabase()
        if not _make_room(db, tenant_id, companion_id, end_user_id):
            return None
        return db.table("companion_memory_facts").insert(row).execute().data[0]
    return await asyncio.to_thread(_q)


async def _update_fact(tenant_id: str, fact_id: str, payload: dict) -> bool:
    payload = {**payload, "updated_at": _now()}

    def _q():
        return (
            get_supabase().table("companion_memory_facts").update(payload)
            .eq("tenant_id", tenant_id).eq("id", fact_id).execute().data
        )
    return bool(await asyncio.to_thread(_q))


async def close_fact(tenant_id: str, fact_id: str, valid_to: str | None = None) -> bool:
    """Marks a fact as no longer true. It stays visible to the character for 90 days."""
    return await _update_fact(tenant_id, fact_id, {"status": "closed", "valid_to": valid_to})


async def update_fact_text(tenant_id: str, fact_id: str, text: str) -> bool:
    return await _update_fact(tenant_id, fact_id, {"text": text.strip()[:300]})


async def delete_fact(tenant_id: str, fact_id: str) -> bool:
    def _q():
        return (
            get_supabase().table("companion_memory_facts").delete()
            .eq("tenant_id", tenant_id).eq("id", fact_id).execute().data
        )
    return bool(await asyncio.to_thread(_q))


async def get_watermark(tenant_id: str, companion_id: str, end_user_id: str) -> str | None:
    """created_at of the newest message already turned into memory, or None (never swept)."""
    def _q():
        return (
            get_supabase().table("companion_memory_state").select("last_message_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0]["last_message_at"] if rows else None


async def set_watermark(tenant_id: str, companion_id: str, end_user_id: str, last_message_at: str) -> None:
    row = {"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
           "last_message_at": last_message_at, "updated_at": _now()}

    def _q():
        (get_supabase().table("companion_memory_state")
         .upsert(row, on_conflict="companion_id,end_user_id").execute())
    await asyncio.to_thread(_q)


async def reset_watermarks(tenant_id: str, companion_id: str) -> None:
    """After an engine switch: the new engine relearns from each person's recent messages."""
    def _q():
        (get_supabase().table("companion_memory_state").delete()
         .eq("tenant_id", tenant_id).eq("companion_id", companion_id).execute())
    await asyncio.to_thread(_q)


async def forget_memory(tenant_id: str, end_user_id: str) -> None:
    """'Forget me' for the card engine: every fact and watermark of this person, all characters."""
    def _q():
        db = get_supabase()
        (db.table("companion_memory_facts").delete()
         .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute())
        (db.table("companion_memory_state").delete()
         .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute())
    await asyncio.to_thread(_q)


# --- the memory sweep (system job: reads across tenants, but every per-pair query filters tenant_id)

async def level2_companions() -> list[dict]:
    """Every character with Level 2 memory, all tenants. Only ids and settings, no content."""
    def _q():
        return (
            get_supabase().table("companions")
            .select("id, tenant_id, language, memory_level, memory_engine")
            .eq("memory_level", 2).order("created_at").execute().data
        )
    return await asyncio.to_thread(_q) or []


async def memory_watermarks(tenant_id: str, companion_id: str) -> dict[str, str | None]:
    """end_user_id → watermark for every person this character has swept."""
    def _q():
        return (
            get_supabase().table("companion_memory_state").select("end_user_id, last_message_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).execute().data
        )
    return {r["end_user_id"]: r["last_message_at"] for r in (await asyncio.to_thread(_q) or [])}


async def active_conversations(tenant_id: str, companion_id: str, since: str) -> list[dict]:
    """This character's conversations with a message after `since`, oldest activity first."""
    def _q():
        return (
            get_supabase().table("companion_conversations").select("end_user_id, last_message_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).gt("last_message_at", since)
            .order("last_message_at").execute().data
        )
    return await asyncio.to_thread(_q) or []


async def messages_after(tenant_id: str, companion_id: str, end_user_id: str, after: str | None,
                         limit: int) -> list[dict]:
    """Messages of this (character, person) after the watermark, oldest first, at most `limit`.
    No watermark yet → the latest `limit` messages."""
    def _q():
        q = (get_supabase().table("companion_messages").select("role, content, created_at")
             .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id))
        if after:
            return q.gt("created_at", after).order("created_at").limit(limit).execute().data
        return list(reversed(q.order("created_at", desc=True).limit(limit).execute().data or []))
    return await asyncio.to_thread(_q) or []
