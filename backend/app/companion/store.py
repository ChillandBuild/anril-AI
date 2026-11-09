"""Every DB call for the companion tables. The only module that touches them.

Uses the service-role client (RLS bypassed), so EVERY query filters on tenant_id itself.
Sync supabase calls run in a thread so they don't block the event loop.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.companion.models import CompanionSettings
from app.db.supabase import get_supabase
from app.services.pagination import fetch_all_rows


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


TEST_PERSON_PATTERN = "owner-test:%"   # the dashboard Playground's person, not a customer


async def overview_counts(tenant_id: str) -> dict:
    """The Overview tiles. Example: 1 live character of 2, 2 people, 3 messages from people this
    week, 1 active key last used an hour ago. Forgotten people and Playground test chats are left
    out."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    def _q():
        db = get_supabase()
        chars = db.table("companions").select("status").eq("tenant_id", tenant_id).execute().data or []
        testers = [r["id"] for r in (
            db.table("companion_end_users").select("id")
            .eq("tenant_id", tenant_id).like("external_user_id", TEST_PERSON_PATTERN).execute().data or [])]
        people = (
            db.table("companion_end_users").select("id", count="exact")
            .eq("tenant_id", tenant_id).is_("forgotten_at", "null")
            .not_.like("external_user_id", TEST_PERSON_PATTERN).limit(1).execute())
        msgs = (db.table("companion_messages").select("id", count="exact")
                .eq("tenant_id", tenant_id).eq("role", "user").gte("created_at", since))
        if testers:
            msgs = msgs.not_.in_("end_user_id", testers)
        msgs = msgs.limit(1).execute()
        keys = (
            db.table("companion_api_keys").select("last_used_at")
            .eq("tenant_id", tenant_id).eq("status", "active").execute().data or [])
        used = [k["last_used_at"] for k in keys if k.get("last_used_at")]
        return {
            "characters": len(chars),
            "live_characters": sum(1 for c in chars if c.get("status") == "live"),
            "people": people.count or 0,
            "messages_this_week": msgs.count or 0,
            "active_keys": len(keys),
            "key_last_used_at": max(used) if used else None,
        }
    return await asyncio.to_thread(_q)


PEOPLE_SCAN_LIMIT = 5000   # conversations read per character for the Memories list


async def list_people(tenant_id: str, companion_id: str, q: str = "", limit: int = 25,
                      offset: int = 0) -> tuple[list[dict], int]:
    """The people one character talked to, newest first, for the Memories page. Example: Karthik
    (48213), 4 active facts learned by this character, 46 messages over two conversations.
    Forgotten people are left out. q matches the external id or display name (case-insensitive).
    Returns (page, total)."""
    def _q():
        db = get_supabase()
        convs = (
            db.table("companion_conversations").select("end_user_id, message_count, last_message_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id)
            .order("last_message_at", desc=True).limit(PEOPLE_SCAN_LIMIT).execute().data or [])
        stats: dict[str, dict] = {}
        for c in convs:
            s = stats.setdefault(c["end_user_id"], {"message_count": 0, "last_seen_at": c["last_message_at"]})
            s["message_count"] += int(c.get("message_count") or 0)
            if c["last_message_at"] > s["last_seen_at"]:
                s["last_seen_at"] = c["last_message_at"]
        if not stats:
            return [], 0
        ids, users = list(stats), []
        for i in range(0, len(ids), 200):   # keeps each in.(...) filter well under URL limits
            users += (
                db.table("companion_end_users").select("id, external_user_id, display_name, forgotten_at")
                .eq("tenant_id", tenant_id).in_("id", ids[i:i + 200]).execute().data or [])
        needle = q.strip().lower()
        people = [
            {"end_user_id": u["id"], "external_user_id": u["external_user_id"],
             "display_name": u.get("display_name"), **stats[u["id"]]}
            for u in users
            if not u.get("forgotten_at") and (
                not needle or needle in u["external_user_id"].lower()
                or needle in (u.get("display_name") or "").lower())
        ]
        people.sort(key=lambda p: p["last_seen_at"], reverse=True)
        page = people[offset:offset + limit]
        if page:
            facts = (
                db.table("companion_memory_facts").select("end_user_id")
                .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("status", "active")
                .in_("end_user_id", [p["end_user_id"] for p in page]).execute().data or [])
            counts: dict[str, int] = {}
            for f in facts:
                counts[f["end_user_id"]] = counts.get(f["end_user_id"], 0) + 1
            for p in page:
                p["fact_count"] = counts.get(p["end_user_id"], 0)
        return page, len(people)
    return await asyncio.to_thread(_q)


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
    return rows[0].get("last_message_at") if rows else None


async def set_watermark(tenant_id: str, companion_id: str, end_user_id: str, last_message_at: str) -> None:
    """Moves the watermark and clears the failed-night count."""
    row = {"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
           "last_message_at": last_message_at, "failures": 0, "updated_at": _now()}

    def _q():
        (get_supabase().table("companion_memory_state")
         .upsert(row, on_conflict="companion_id,end_user_id").execute())
    await asyncio.to_thread(_q)


async def record_failure(tenant_id: str, companion_id: str, end_user_id: str, failures: int) -> None:
    """Counts a failed night for this pair; the watermark stays where it is."""
    row = {"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
           "failures": failures, "updated_at": _now()}

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


async def memory_states(tenant_id: str, companion_id: str) -> dict[str, tuple[str | None, int]]:
    """end_user_id → (watermark, failed nights) for every person this character has swept
    (paged past 1000 rows)."""
    rows = await fetch_all_rows(lambda: (
        get_supabase().table("companion_memory_state").select("end_user_id, last_message_at, failures")
        .eq("tenant_id", tenant_id).eq("companion_id", companion_id).order("end_user_id")))
    return {r["end_user_id"]: (r.get("last_message_at"), r.get("failures") or 0) for r in rows}


async def active_conversations(tenant_id: str, companion_id: str, since: str) -> list[dict]:
    """This character's conversations with a message after `since`, oldest activity first
    (paged past 1000 rows)."""
    return await fetch_all_rows(lambda: (
        get_supabase().table("companion_conversations").select("end_user_id, last_message_at")
        .eq("tenant_id", tenant_id).eq("companion_id", companion_id).gt("last_message_at", since)
        .order("last_message_at")))


async def message_exists(tenant_id: str, message_id: str) -> bool:
    """False once 'forget me' has deleted the message (the sweep checks before writing facts)."""
    def _q():
        return (
            get_supabase().table("companion_messages").select("id")
            .eq("tenant_id", tenant_id).eq("id", message_id).limit(1).execute().data
        )
    return bool(await asyncio.to_thread(_q))


async def messages_after(tenant_id: str, companion_id: str, end_user_id: str, after: str | None,
                         limit: int) -> list[dict]:
    """Messages of this (character, person) after the watermark, oldest first, at most `limit`.
    No watermark yet → the latest `limit` messages."""
    def _q():
        q = (get_supabase().table("companion_messages").select("id, role, content, created_at")
             .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id))
        if after:
            return q.gt("created_at", after).order("created_at").limit(limit).execute().data
        return list(reversed(q.order("created_at", desc=True).limit(limit).execute().data or []))
    return await asyncio.to_thread(_q) or []


# --- chat API secret keys (migration 250). Only the SHA-256 of a key is ever stored. -------------

_KEY_FIELDS = ("id", "key_prefix", "status", "created_at", "revoked_at", "last_used_at")
_KEY_COLUMNS = ", ".join(_KEY_FIELDS)


async def create_api_key(tenant_id: str, key_prefix: str, key_hash: str, created_by: str | None) -> dict:
    row = {"tenant_id": tenant_id, "key_prefix": key_prefix, "key_hash": key_hash, "status": "active",
           "created_by": created_by}

    def _q():
        return get_supabase().table("companion_api_keys").insert(row).execute().data[0]
    created = await asyncio.to_thread(_q)
    return {k: created.get(k) for k in ("id", "key_prefix", "status", "created_at")}


async def list_api_keys(tenant_id: str) -> list[dict]:
    """Newest first: the active keys and the 10 most recent revoked ones. Never the hash."""
    def _q():
        return (
            get_supabase().table("companion_api_keys").select(_KEY_COLUMNS)
            .eq("tenant_id", tenant_id).order("created_at", desc=True).limit(20).execute().data
        )
    rows = [{k: r.get(k) for k in _KEY_FIELDS} for r in (await asyncio.to_thread(_q) or [])]
    active = [r for r in rows if r.get("status") == "active"]
    return active + [r for r in rows if r.get("status") != "active"][:10]


async def count_active_api_keys(tenant_id: str) -> int:
    def _q():
        return (
            get_supabase().table("companion_api_keys").select("id")
            .eq("tenant_id", tenant_id).eq("status", "active").execute().data
        )
    return len(await asyncio.to_thread(_q) or [])


async def revoke_api_key(tenant_id: str, key_id: str) -> bool:
    """False if the key isn't this tenant's or is already revoked."""
    def _q():
        return (
            get_supabase().table("companion_api_keys")
            .update({"status": "revoked", "revoked_at": _now()})
            .eq("tenant_id", tenant_id).eq("id", key_id).eq("status", "active").execute().data
        )
    return bool(await asyncio.to_thread(_q))


async def find_active_api_key(key_hash: str) -> dict | None:
    """The key itself names the tenant, so this one lookup has no tenant filter: the caller
    takes tenant_id FROM the row and every later query filters on it."""
    def _q():
        return (
            get_supabase().table("companion_api_keys").select("id, tenant_id")
            .eq("key_hash", key_hash).eq("status", "active").limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else None


async def active_key_hashes(tenant_id: str) -> list[tuple[str, str]]:
    """(key id, key hash) of the tenant's active keys, for checking a widget's signed user id."""
    def _q():
        return (
            get_supabase().table("companion_api_keys").select("id, key_hash")
            .eq("tenant_id", tenant_id).eq("status", "active").execute().data
        )
    return [(r["id"], r["key_hash"]) for r in (await asyncio.to_thread(_q) or [])]


async def touch_api_key(tenant_id: str, key_id: str) -> None:
    def _q():
        get_supabase().table("companion_api_keys").update({"last_used_at": _now()}) \
            .eq("tenant_id", tenant_id).eq("id", key_id).execute()
    await asyncio.to_thread(_q)


async def companion_tenant(companion_id: str) -> str | None:
    """Which business owns this character. The widget sends only the character id and a signed
    user id, so the tenant must come from here; the signature is then checked against THAT
    tenant's keys, and every later query filters on it."""
    def _q():
        return (
            get_supabase().table("companions").select("tenant_id")
            .eq("id", companion_id).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0]["tenant_id"] if rows else None
