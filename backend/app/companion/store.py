"""Every DB call for the companion tables. The only module that touches them.

Uses the service-role client (RLS bypassed), so EVERY query filters on tenant_id itself.
Sync supabase calls run in a thread so they don't block the event loop.
"""
import asyncio
import re
import unicodedata
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


async def find_or_create_end_user(tenant_id: str, external_user_id: str, display_name: str | None = None,
                                  timezone_name: str | None = None) -> dict:
    """One row per person per business. first_seen_at / forgotten_at are never sent, so they survive.
    timezone_name (an IANA zone the API already validated) is saved when the app sends one."""
    payload = {"tenant_id": tenant_id, "external_user_id": external_user_id, "last_seen_at": _now()}
    name = (display_name or "").strip()[:100]
    if name:
        payload["display_name"] = name
    if timezone_name:
        payload["timezone"] = timezone_name

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
                       *, mood: str | None = None, tool_calls: list[dict] | None = None,
                       basis: str | None = None, sources: list[dict] | None = None) -> dict:
    """basis / sources: where an assistant reply came from ("book", [{"document": "Book 7", ...}]).
    Left out of the row when empty, so a character with no collection writes the same row as before."""
    row = {
        "tenant_id": tenant_id, "companion_id": conversation["companion_id"],
        "conversation_id": conversation["id"], "end_user_id": conversation["end_user_id"],
        "role": role, "content": content[:MAX_CONTENT], "mood": mood, "tool_calls": tool_calls,
    }
    if basis:
        row["basis"] = basis
        row["sources"] = sources or []
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


async def recent_messages(tenant_id: str, companion_id: str, end_user_id: str, limit: int = 10, *,
                          after: str | None = None) -> list[dict]:
    """Last `limit` messages of this character with this person, across conversations, oldest first.
    `after` (companion_end_users.chat_read_after): nothing sent at or before it is returned, so the
    character never re-reads the chat from before an owner deleted a memory."""
    def _q():
        q = (get_supabase().table("companion_messages").select("role, content, mood, created_at")
             .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id))
        if after:
            q = q.gt("created_at", after)
        return q.order("created_at", desc=True).limit(limit).execute().data
    rows = await asyncio.to_thread(_q) or []
    return list(reversed(rows))


# --- an owner deleted a memory: the person's own words leave the saved chat (migration 263) ------

ERASE_SCAN = 5000                   # newest messages / search pieces of the person that are checked
_PAGE = 1000                        # PostgREST returns at most 1000 rows per call
_LEFTOVER = re.compile(r"^[\W_]+|[\W_]+$")
_PLACEHOLDER = re.compile(r"\[(number|email)\]")


def _norm_map(text: str) -> tuple[str, list[int]]:
    """`text` as a receipt is compared (memory_card._norm_quote: case-folded, everything that is not a
    letter, a mark or a digit becomes one space), plus where each of its characters sits in `text`.
    "Amma-ku  sugar!" → ("amma ku sugar", [0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13])."""
    out: list[str] = []
    at: list[int] = []
    for i, ch in enumerate(text):
        category = unicodedata.category(ch)
        if category == "Cf":            # invisible joiners are dropped, not spaces
            continue
        if category[0] in "LMN":
            for folded in ch.casefold():
                out.append(folded)
                at.append(i)
        elif out and out[-1] != " ":
            out.append(" ")
            at.append(i)
    if out and out[-1] == " ":
        out.pop()
        at.pop()
    return "".join(out), at


def _quote_pattern(quote: str) -> "re.Pattern | None":
    """A whole-word pattern for `quote` over _norm_map text. The saved quote may hold "[number]" or
    "[email]" where the person typed digits or an address (memory_card.redact): those match the real thing.
    None for a quote with fewer than 3 characters of words."""
    quote = unicodedata.normalize("NFC", quote or "")
    parts: list[str] = []
    words = 0
    pieces = _PLACEHOLDER.split(quote)          # text, kind, text, kind, ..., text
    for i, piece in enumerate(pieces):
        if i % 2:
            last = not any(_norm_map(p)[0] for p in pieces[i + 1::2])
            parts.append(r"\d(?:[\d ]*\d)?" if piece == "number"
                         else r"\S+(?: \S+){0,3}" if last else r"\S+(?: \S+){0,5}?")
        else:
            norm = _norm_map(piece)[0]
            if norm:
                parts.append(re.escape(norm))
                words += len(norm)
    if words < 3:
        return None
    return re.compile(r"(?<!\S)" + " ".join(parts) + r"(?!\S)")


def quote_spans(text: str, quote: str) -> list[tuple[int, int]]:
    """Where `quote` sits in `text` as whole words, compared the way a receipt is (so "Amma-ku sugar"
    is found by the quote "amma ku sugar"). (start, end) pairs in `text`, which must be NFC."""
    pattern = _quote_pattern(quote)
    if pattern is None:
        return []
    norm, at = _norm_map(text)
    return [(at[m.start()], at[m.end() - 1] + 1) for m in pattern.finditer(norm) if m.end() > m.start()]


def cut_words(content: str, quote: str) -> str:
    """`content` without `quote`, tidied: "Amma-ku sugar problem. Naalaiku interview irukku" minus
    "amma ku sugar problem" → "Naalaiku interview irukku". "" when nothing is left; `content` itself
    when the quote is not in it."""
    text = unicodedata.normalize("NFC", content or "")
    spans = quote_spans(text, quote)
    if not spans:
        return content
    kept, last = [], 0
    for start, end in spans:
        kept.append(text[last:start])
        last = end
    kept.append(text[last:])
    cut = re.sub(r"\s{2,}", " ", " ".join(kept)).strip()
    cut = re.sub(r"^[\s.,;:!?\-]+", "", cut)
    return cut if re.sub(_LEFTOVER, "", cut) else ""


def _scan(build) -> list[dict]:
    """Up to ERASE_SCAN rows of `build()` (a fresh ordered query each call), read 1000 at a time."""
    rows: list[dict] = []
    while len(rows) < ERASE_SCAN:
        page = build().range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows += page
        if len(page) < _PAGE:
            break
    return rows


async def erase_words(tenant_id: str, end_user_id: str, quote: str) -> dict:
    """Cuts the person's words out of every saved message of theirs (with any character) and deletes
    the search pieces that carry them. A message with nothing left is deleted. The words are matched
    the way the receipt was (case, punctuation and spacing do not matter).
    {"messages": n, "pieces": n, "capped": bool}; capped = the person has more saved chat than was
    checked. No marker is left: the person must not learn a delete exists."""
    if _quote_pattern(quote) is None:
        return {"messages": 0, "pieces": 0, "capped": False}

    def _q():
        db = get_supabase()
        rows = _scan(lambda: db.table("companion_messages").select("id, content")
                     .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).eq("role", "user")
                     .order("created_at", desc=True))
        changed = 0
        for row in rows:                      # read everything first: a delete would shift the pages
            content = row.get("content") or ""
            left = cut_words(content, quote)
            if left == content:
                continue
            q = db.table("companion_messages")
            q = q.update({"content": left}) if left else q.delete()
            q.eq("tenant_id", tenant_id).eq("id", row["id"]).execute()
            changed += 1
        pieces = _scan(lambda: db.table("companion_memory_chunks").select("id, text")
                       .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).eq("kind", "messages")
                       .order("created_at", desc=True))
        hit = [r["id"] for r in pieces
               if quote_spans(unicodedata.normalize("NFC", r.get("text") or ""), quote)]
        for start in range(0, len(hit), 100):
            (db.table("companion_memory_chunks").delete().eq("tenant_id", tenant_id)
             .in_("id", hit[start:start + 100]).execute())
        return {"messages": changed, "pieces": len(hit),
                "capped": len(rows) >= ERASE_SCAN or len(pieces) >= ERASE_SCAN}
    return await asyncio.to_thread(_q)


async def set_read_after(tenant_id: str, end_user_id: str) -> str:
    """From now on no character reads this person's chat from before this moment (reply window,
    note-writer, search index, diary). The moment is the person's newest saved message, so it is on the
    database's clock like every message time (the app server's clock can be seconds off). Returns it."""
    def _q():
        db = get_supabase()
        newest = (db.table("companion_messages").select("created_at")
                  .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id)
                  .order("created_at", desc=True).limit(1).execute().data)
        edge = newest[0]["created_at"] if newest else _now()
        (db.table("companion_end_users").update({"chat_read_after": edge})
         .eq("tenant_id", tenant_id).eq("id", end_user_id).execute())
        return edge
    return await asyncio.to_thread(_q)


async def read_after(tenant_id: str, end_user_id: str) -> str | None:
    """companion_end_users.chat_read_after, or None (no memory was ever deleted for this person)."""
    def _q():
        return (get_supabase().table("companion_end_users").select("chat_read_after")
                .eq("tenant_id", tenant_id).eq("id", end_user_id).limit(1).execute().data)
    rows = await asyncio.to_thread(_q)
    return rows[0].get("chat_read_after") if rows else None


def after_cutoff(messages: list[dict], cutoff: str | None, *, roles: tuple[str, ...] = ("user", "assistant")
                 ) -> list[dict]:
    """`messages` without those of `roles` sent at or before `cutoff` (None = keep all)."""
    if not cutoff:
        return messages
    edge = _parse_ts(cutoff)
    return [m for m in messages if m["role"] not in roles or _parse_ts(m["created_at"]) > edge]


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


# --- public API request log (migration 252) -----------------------------------------------------

REQUEST_KINDS = ("chat", "chat_continue", "widget_session", "widget_chat", "widget_continue")
REQUEST_LOG_PAGE = 100       # newest rows shown in the Requests table
REQUEST_LOG_SCAN = 20000     # rows read for the daily counts (a busy month for one business)


async def log_request(row: dict) -> None:
    """One public API call: who, which character, how it went. Never message text."""
    def _q():
        get_supabase().table("companion_request_log").insert(row).execute()
    await asyncio.to_thread(_q)


async def request_log(tenant_id: str, *, kind: str | None = None, status: str | None = None,
                      days: int = 7) -> dict:
    """The Requests page. status "ok" = below 400, "error" = 400 and up. Example: days=7 →
    the newest 100 rows, plus per-day ok/error counts and totals for the 7 days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def _base(columns: str):
        q = (get_supabase().table("companion_request_log").select(columns)
             .eq("tenant_id", tenant_id).gte("created_at", since))
        if kind:
            q = q.eq("kind", kind)
        if status == "ok":
            q = q.lt("status", 400)
        elif status == "error":
            q = q.gte("status", 400)
        return q

    def _q():
        rows = (_base("id, companion_id, kind, external_user_id, status, ms, created_at")
                .order("created_at", desc=True).limit(REQUEST_LOG_PAGE).execute().data or [])
        stats = (_base("status, ms, created_at").order("created_at", desc=True)
                 .limit(REQUEST_LOG_SCAN).execute().data or [])
        return rows, stats
    rows, stats = await asyncio.to_thread(_q)

    daily: dict[str, dict] = {}
    for r in stats:
        day = daily.setdefault(str(r["created_at"])[:10], {"ok": 0, "error": 0})
        day["error" if int(r["status"]) >= 400 else "ok"] += 1
    times = sorted(int(r["ms"]) for r in stats)
    return {
        "requests": rows,
        "daily": [{"date": d, **daily[d]} for d in sorted(daily)],
        "total": len(stats),
        "errors": sum(1 for r in stats if int(r["status"]) >= 400),
        "median_ms": times[len(times) // 2] if times else None,
        "capped": len(stats) >= REQUEST_LOG_SCAN,
    }


FACT_SEARCH_SCAN = 2000   # newest facts read per character for the Playground memory search
_WORD = re.compile(r"\w+", re.UNICODE)


def search_words(q: str) -> list[str]:
    """Lowercase words to match, at most 8, single letters dropped. "Karthik's job?" → ["karthik", "job"]."""
    words: list[str] = []
    for w in _WORD.findall(q.lower()):
        if len(w) > 1 and w not in words:
            words.append(w)
    return words[:8]


async def search_facts(tenant_id: str, companion_id: str, q: str, limit: int = 10,
                       end_user_id: str | None = None) -> list[dict]:
    """Facts this character learned whose text contains any word of q, most words matched first,
    then newest. Plain word match, no meaning: q "Zoho job" finds "new job at Zoho" but not
    "works at Infosys". Only this character's own facts; forgotten people are left out."""
    words = search_words(q)
    if not words:
        return []

    def _q():
        db = get_supabase()
        query = (db.table("companion_memory_facts").select("end_user_id, section, text, status, created_at")
                 .eq("tenant_id", tenant_id).eq("companion_id", companion_id))
        if end_user_id:
            query = query.eq("end_user_id", end_user_id)
        facts = query.order("created_at", desc=True).limit(FACT_SEARCH_SCAN).execute().data or []
        scored = []
        for f in facts:
            text = (f.get("text") or "").lower()
            score = sum(1 for w in words if w in text)
            if score:
                scored.append((score, f))
        scored.sort(key=lambda sf: sf[0], reverse=True)   # stable: newest first within a score
        hits = [f for _, f in scored[: limit * 2]]   # spare rows in case some people were forgotten
        ids, users = list({f["end_user_id"] for f in hits}), {}
        for i in range(0, len(ids), 200):
            for u in (db.table("companion_end_users").select("id, external_user_id, display_name, forgotten_at")
                      .eq("tenant_id", tenant_id).in_("id", ids[i:i + 200]).execute().data or []):
                users[u["id"]] = u
        out = []
        for f in hits:
            u = users.get(f["end_user_id"])
            if not u or u.get("forgotten_at"):
                continue
            out.append({"text": f["text"], "section": f["section"], "status": f["status"],
                        "learned_at": f.get("created_at"), "external_user_id": u["external_user_id"],
                        "display_name": u.get("display_name")})
        return out[:limit]
    return await asyncio.to_thread(_q)


# --- Level 2 memory: facts, watermarks, tenant settings (migration 249) -------------------------

FACT_SECTIONS = ("profile", "people", "life", "preferences", "threads")
MAX_FACTS_PER_PAIR = 500   # a safety ceiling, not a working limit: nothing is evicted (see _has_room)
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


def _has_room(db, tenant_id: str, companion_id: str, end_user_id: str) -> bool:
    """False once a (character, person) pair holds MAX_FACTS_PER_PAIR facts. Nothing is ever thrown
    away to make room (Prem, 2026-11-11): the card shows the newest that fit, search finds the rest,
    and a pair at the ceiling stops taking new facts until the owner deletes some (an alert is raised).
    Counted: active facts and facts closed in the last 90 days (what list_facts shows the owner). An
    old closed fact ("Lived in Madurai", closed last year) does not use up room."""
    def _count(status: str, room: int) -> int:
        q = (db.table("companion_memory_facts").select("id")
             .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
             .eq("status", status))
        if status == "closed":
            q = q.gte("updated_at", (datetime.now(timezone.utc) - CLOSED_FACT_WINDOW).isoformat())
        return len(q.limit(room).execute().data or [])
    active = _count("active", MAX_FACTS_PER_PAIR)
    return active < MAX_FACTS_PER_PAIR and active + _count("closed", MAX_FACTS_PER_PAIR - active) < MAX_FACTS_PER_PAIR


async def add_fact(tenant_id: str, companion_id: str, end_user_id: str, section: str, text: str,
                   valid_from: str | None = None, valid_to: str | None = None, *,
                   quote: str | None = None, source_message_id: str | None = None) -> dict | None:
    """Adds one active fact. None when the pair is at the ceiling (MAX_FACTS_PER_PAIR rows).
    quote / source_message_id (migration 261): the person's words the fact came from and the message
    they were found in. The memory sweep always sends them; hand-added facts have none."""
    if section not in FACT_SECTIONS:
        raise ValueError(f"unknown section {section!r}")
    now = _now()
    row = {
        "tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
        "section": section, "text": text.strip()[:300], "valid_from": valid_from, "valid_to": valid_to,
        "status": "active", "created_at": now, "updated_at": now,
    }
    if quote:
        row["quote"], row["source_message_id"] = quote.strip()[:300], source_message_id

    def _q():
        db = get_supabase()
        if not _has_room(db, tenant_id, companion_id, end_user_id):
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


async def update_fact_text(tenant_id: str, fact_id: str, text: str, *, quote: str | None = None,
                           source_message_id: str | None = None) -> bool:
    """New wording for a fact. With a quote, the fact's receipt is replaced too."""
    payload = {"text": text.strip()[:300]}
    if quote:
        payload["quote"], payload["source_message_id"] = quote.strip()[:300], source_message_id
    return await _update_fact(tenant_id, fact_id, payload)


async def delete_fact(tenant_id: str, fact_id: str) -> bool:
    def _q():
        return (
            get_supabase().table("companion_memory_facts").delete()
            .eq("tenant_id", tenant_id).eq("id", fact_id).execute().data
        )
    return bool(await asyncio.to_thread(_q))


async def set_slot_fact(tenant_id: str, companion_id: str, end_user_id: str, slot: str, section: str,
                        text: str, valid_from: str | None, closed_on: str, *, quote: str | None = None,
                        source_message_id: str | None = None) -> tuple[dict | None, list[dict]]:
    """The one live fact of a slot (migration 262): closes this pair's active fact in `slot` on
    `closed_on` and adds the new one, in one transaction. Returns (new fact, the facts it closed);
    (None, []) when the pair is full. "Lives in Chennai" → closed, "Lives in Bengaluru" → active."""
    params = {"p_tenant": tenant_id, "p_companion": companion_id, "p_end_user": end_user_id, "p_slot": slot,
              "p_section": section, "p_text": text.strip()[:300], "p_valid_from": valid_from,
              "p_closed_on": closed_on, "p_quote": quote.strip()[:300] if quote else None,
              "p_source": source_message_id if quote else None}

    def _q():
        db = get_supabase()
        if not _has_room(db, tenant_id, companion_id, end_user_id):
            return None, []
        out = db.rpc("companion_set_slot_fact", params).execute().data or {}
        return out.get("fact"), out.get("closed") or []
    return await asyncio.to_thread(_q)


async def mark_threads_asked(tenant_id: str, fact_ids: list[str]) -> None:
    """The character was shown these threads as due: it asks once, then waits to hear."""
    if not fact_ids:
        return

    def _q():
        (get_supabase().table("companion_memory_facts").update({"asked_at": _now()})
         .eq("tenant_id", tenant_id).in_("id", fact_ids).eq("section", "threads").eq("status", "active")
         .is_("asked_at", "null").execute())
    await asyncio.to_thread(_q)


async def expire_threads(tenant_id: str, companion_id: str, end_user_id: str, *, dated_before: str,
                         undated_before: str) -> int:
    """Open threads nobody closed: a date before `dated_before` (a day), or no date and created before
    `undated_before` (a timestamp). They become closed + expired_at, and leave the card. Returns the count."""
    now = _now()
    payload = {"status": "closed", "expired_at": now, "updated_at": now}

    def _base():
        return (get_supabase().table("companion_memory_facts").update(payload)
                .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
                .eq("section", "threads").eq("status", "active"))

    def _q():
        dated = _base().lt("valid_from", dated_before).execute().data or []
        undated = _base().is_("valid_from", "null").lt("created_at", undated_before).execute().data or []
        return len(dated) + len(undated)
    return await asyncio.to_thread(_q)


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
    """'Forget me' for the card engine: every fact, diary line, search piece and watermark (with its
    recap) of this person, all characters."""
    def _q():
        db = get_supabase()
        (db.table("companion_memory_facts").delete()
         .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute())
        (db.table("companion_memory_diary").delete()
         .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute())
        (db.table("companion_memory_state").delete()
         .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute())
        (db.table("companion_memory_chunks").delete()
         .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute())
    await asyncio.to_thread(_q)


# --- same-day recap and diary lines (migration 255) --------------------------------------------

async def get_recap(tenant_id: str, companion_id: str, end_user_id: str) -> dict | None:
    """{"text", "day", "through"} of this pair's "earlier today" note, or None when there is none."""
    def _q():
        return (
            get_supabase().table("companion_memory_state").select("today_recap, recap_day, recap_through")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    if not rows or not rows[0].get("today_recap"):
        return None
    row = rows[0]
    return {"text": row["today_recap"], "day": str(row.get("recap_day") or "")[:10] or None,
            "through": row.get("recap_through")}


async def set_recap(tenant_id: str, companion_id: str, end_user_id: str, text: str, day: str,
                    through: str) -> None:
    """Replaces the pair's recap. The watermark and failure count on the same row are left alone."""
    row = {"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
           "today_recap": text, "recap_day": day, "recap_through": through, "updated_at": _now()}

    def _q():
        (get_supabase().table("companion_memory_state")
         .upsert(row, on_conflict="companion_id,end_user_id").execute())
    await asyncio.to_thread(_q)


async def clear_recap(tenant_id: str, companion_id: str, end_user_id: str) -> None:
    def _q():
        (get_supabase().table("companion_memory_state")
         .update({"today_recap": None, "recap_day": None, "recap_through": None, "updated_at": _now()})
         .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id).execute())
    await asyncio.to_thread(_q)


async def has_diary(tenant_id: str, companion_id: str, end_user_id: str, day: str) -> bool:
    def _q():
        return (
            get_supabase().table("companion_memory_diary").select("day")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .eq("day", day).limit(1).execute().data
        )
    return bool(await asyncio.to_thread(_q))


async def upsert_diary(tenant_id: str, companion_id: str, end_user_id: str, day: str, text: str) -> None:
    row = {"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
           "day": day, "text": text, "updated_at": _now()}

    def _q():
        (get_supabase().table("companion_memory_diary")
         .upsert(row, on_conflict="companion_id,end_user_id,day").execute())
    await asyncio.to_thread(_q)


async def recent_diary(tenant_id: str, companion_id: str, end_user_id: str, before_day: str,
                       limit: int = 5) -> list[dict]:
    """This pair's diary lines from days before `before_day`, newest first."""
    def _q():
        return (
            get_supabase().table("companion_memory_diary").select("day, text")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .lt("day", before_day).order("day", desc=True).limit(limit).execute().data
        )
    return await asyncio.to_thread(_q) or []


async def prune_diary(tenant_id: str, companion_id: str, end_user_id: str, before_day: str) -> None:
    """Deletes this pair's diary lines older than `before_day` (the 90-day window)."""
    def _q():
        (get_supabase().table("companion_memory_diary").delete()
         .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
         .lt("day", before_day).execute())
    await asyncio.to_thread(_q)


async def messages_between(tenant_id: str, companion_id: str, end_user_id: str, start: str, end: str,
                           limit: int) -> list[dict]:
    """The latest `limit` messages of this pair with start < created_at < end, oldest first."""
    def _q():
        return (
            get_supabase().table("companion_messages").select("id, role, content, created_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .gt("created_at", start).lt("created_at", end)
            .order("created_at", desc=True).limit(limit).execute().data
        )
    return list(reversed(await asyncio.to_thread(_q) or []))


# --- the memory sweep (system job: reads across tenants, but every per-pair query filters tenant_id)

async def level2_companions() -> list[dict]:
    """Every character with Level 2 memory, all tenants. Only ids and settings, no content."""
    def _q():
        return (
            get_supabase().table("companions")
            .select("id, tenant_id, language, memory_level, memory_engine, timezone, history_messages")
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


async def memory_states_full(tenant_id: str, companion_id: str) -> list[dict]:
    """Every state row of this character (paged past 1000 rows)."""
    return await fetch_all_rows(lambda: (
        get_supabase().table("companion_memory_state")
        .select("end_user_id, last_message_at, updated_at, search_backfilled_at")
        .eq("tenant_id", tenant_id).eq("companion_id", companion_id).order("end_user_id")))


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


# --- memory v2 (migration 256): pair state, claims, day context, search chunks ------------------

async def get_state(tenant_id: str, companion_id: str, end_user_id: str) -> dict:
    """The pair's companion_memory_state row ({} when there is none)."""
    def _q():
        return (
            get_supabase().table("companion_memory_state").select("*")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else {}


async def update_state(tenant_id: str, companion_id: str, end_user_id: str, fields: dict) -> None:
    """Sets some columns of the pair's state row, creating the row when it is missing."""
    row = {"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
           **fields, "updated_at": _now()}

    def _q():
        (get_supabase().table("companion_memory_state")
         .upsert(row, on_conflict="companion_id,end_user_id").execute())
    await asyncio.to_thread(_q)


async def claim_pair(tenant_id: str, companion_id: str, end_user_id: str, seconds: int) -> bool:
    """One memory run per pair at a time, across every server process (claim_memory_pair)."""
    def _q():
        return get_supabase().rpc("claim_memory_pair", {
            "p_tenant": tenant_id, "p_companion": companion_id, "p_end_user": end_user_id,
            "p_seconds": seconds}).execute().data
    return bool(await asyncio.to_thread(_q))


async def release_pair(tenant_id: str, companion_id: str, end_user_id: str) -> None:
    def _q():
        (get_supabase().table("companion_memory_state").update({"busy_until": None})
         .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id).execute())
    await asyncio.to_thread(_q)


async def day_context_rows(tenant_id: str, companion_id: str, end_user_id: str, before_day: str,
                           days: int) -> dict:
    """{"recap", "recap_day", "diary": [{"day", "text"}, newest first]} in one round trip."""
    def _q():
        return get_supabase().rpc("companion_day_context", {
            "p_tenant": tenant_id, "p_companion": companion_id, "p_end_user": end_user_id,
            "p_before_day": before_day, "p_days": days}).execute().data
    return await asyncio.to_thread(_q) or {}


async def person_timezone(tenant_id: str, end_user_id: str) -> str | None:
    """The zone the person's app last sent (companion_end_users.timezone), or None."""
    def _q():
        return (
            get_supabase().table("companion_end_users").select("timezone")
            .eq("tenant_id", tenant_id).eq("id", end_user_id).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0].get("timezone") if rows else None


async def messages_page(tenant_id: str, companion_id: str, end_user_id: str, start: str, end: str,
                        limit: int) -> list[dict]:
    """The first `limit` messages of this pair with start < created_at < end, oldest first.
    Page on by passing the last message's created_at as the next `start`."""
    def _q():
        return (
            get_supabase().table("companion_messages").select("id, role, content, created_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .gt("created_at", start).lt("created_at", end).order("created_at").limit(limit).execute().data
        )
    return await asyncio.to_thread(_q) or []


async def messages_before(tenant_id: str, companion_id: str, end_user_id: str, before: str,
                          limit: int) -> list[dict]:
    """The `limit` messages just before `before`, oldest first (the overlap of a search window)."""
    def _q():
        return (
            get_supabase().table("companion_messages").select("id, role, content, created_at")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .lt("created_at", before).order("created_at", desc=True).limit(limit).execute().data
        )
    return list(reversed(await asyncio.to_thread(_q) or []))


async def diary_since(tenant_id: str, companion_id: str, end_user_id: str, since_day: str) -> list[dict]:
    """This pair's diary lines from `since_day` on, newest first."""
    def _q():
        return (
            get_supabase().table("companion_memory_diary").select("day, text")
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .gte("day", since_day).order("day", desc=True).execute().data
        )
    return await asyncio.to_thread(_q) or []


async def person_diary(tenant_id: str, end_user_id: str, since_day: str) -> list[dict]:
    """This person's diary lines with every character of the tenant from `since_day` on."""
    def _q():
        return (
            get_supabase().table("companion_memory_diary").select("companion_id, day, text")
            .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id)
            .gte("day", since_day).order("day").execute().data
        )
    return await asyncio.to_thread(_q) or []


async def person_recaps(tenant_id: str, end_user_id: str) -> list[dict]:
    """This person's "earlier today" recaps with every character of the tenant."""
    def _q():
        return (
            get_supabase().table("companion_memory_state").select("companion_id, today_recap, recap_day")
            .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id).execute().data
        )
    return [r for r in (await asyncio.to_thread(_q) or []) if r.get("today_recap")]


async def delete_diary(tenant_id: str, companion_id: str, end_user_id: str, day: str) -> bool:
    def _q():
        return (
            get_supabase().table("companion_memory_diary").delete()
            .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
            .eq("day", day).execute().data
        )
    return bool(await asyncio.to_thread(_q))


async def upsert_chunks(rows: list[dict]) -> None:
    """Search pieces; a row with the same (character, person, kind, source_key) is replaced."""
    if not rows:
        return

    def _q():
        (get_supabase().table("companion_memory_chunks")
         .upsert(rows, on_conflict="companion_id,end_user_id,kind,source_key").execute())
    await asyncio.to_thread(_q)


async def delete_chunks(tenant_id: str, end_user_id: str, *, companion_id: str | None = None,
                        kind: str | None = None, source_keys: list[str] | None = None,
                        ids: list[str] | None = None) -> None:
    def _q():
        q = (get_supabase().table("companion_memory_chunks").delete()
             .eq("tenant_id", tenant_id).eq("end_user_id", end_user_id))
        if companion_id:
            q = q.eq("companion_id", companion_id)
        if kind:
            q = q.eq("kind", kind)
        if source_keys is not None:
            q = q.in_("source_key", source_keys)
        if ids is not None:
            q = q.in_("id", ids)
        q.execute()
    if (source_keys is not None and not source_keys) or (ids is not None and not ids):
        return
    await asyncio.to_thread(_q)


async def match_chunks(tenant_id: str, companion_ids: list[str], end_user_id: str,
                       embedding: list[float] | None, query: str, count: int) -> list[dict]:
    """match_memory_chunks: rows tagged source 'vector' or 'trigram' with their score."""
    from app.services.embeddings import to_pgvector

    def _q():
        return get_supabase().rpc("match_memory_chunks", {
            "p_tenant": tenant_id, "p_companions": companion_ids, "p_end_user": end_user_id,
            "p_embedding": to_pgvector(embedding) if embedding else None, "p_query": query,
            "p_count": count}).execute().data
    return await asyncio.to_thread(_q) or []


async def chunks_missing_embedding(tenant_id: str, limit: int) -> list[dict]:
    """This business's search pieces whose embedding failed earlier, oldest first (the hourly job
    fills them in with the business's own key)."""
    def _q():
        return (
            get_supabase().table("companion_memory_chunks").select("id, tenant_id, text")
            .eq("tenant_id", tenant_id).is_("embedding", "null").order("created_at").limit(limit).execute().data
        )
    return await asyncio.to_thread(_q) or []


async def set_chunk_embedding(tenant_id: str, chunk_id: str, embedding: list[float]) -> None:
    from app.services.embeddings import to_pgvector

    def _q():
        (get_supabase().table("companion_memory_chunks").update({"embedding": to_pgvector(embedding)})
         .eq("tenant_id", tenant_id).eq("id", chunk_id).execute())
    await asyncio.to_thread(_q)


async def get_fact(tenant_id: str, fact_id: str) -> dict | None:
    def _q():
        return (
            get_supabase().table("companion_memory_facts").select("*")
            .eq("tenant_id", tenant_id).eq("id", fact_id).limit(1).execute().data
        )
    rows = await asyncio.to_thread(_q)
    return rows[0] if rows else None


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


# --- "forget that": compare-and-set rewrites and the retry queue (migration 256) -------------------

async def replace_diary_if(tenant_id: str, companion_id: str, end_user_id: str, day: str, old: str,
                           new: str | None) -> bool:
    """Rewrites (or deletes, new=None) one diary line only if it still reads `old`, so a line the
    diary job rewrote meanwhile is never overwritten with a stale copy. True if a row changed."""
    def _q():
        q = get_supabase().table("companion_memory_diary")
        q = q.update({"text": new, "updated_at": _now()}) if new else q.delete()
        return (q.eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
                .eq("day", day).eq("text", old).execute().data)
    return bool(await asyncio.to_thread(_q))


async def replace_recap_if(tenant_id: str, companion_id: str, end_user_id: str, old: str,
                           new: str | None) -> bool:
    """Rewrites (or clears, new=None) the "earlier today" note only if it still reads `old`."""
    fields = {"today_recap": new, "updated_at": _now()} if new else {
        "today_recap": None, "recap_day": None, "recap_through": None, "updated_at": _now()}

    def _q():
        return (get_supabase().table("companion_memory_state").update(fields)
                .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
                .eq("today_recap", old).execute().data)
    return bool(await asyncio.to_thread(_q))


async def queue_forget(tenant_id: str, companion_id: str, end_user_id: str, items: list[str],
                       tries: int) -> None:
    """A "forget that" cleanup that failed: the hourly job tries it again. The items are kept only
    until the cleanup succeeds; forget-me deletes the whole state row."""
    await update_state(tenant_id, companion_id, end_user_id,
                       {"forget_pending": {"items": items[:10], "tries": tries}})


async def pending_forgets(tenant_id: str) -> list[dict]:
    """This business's pairs with a "forget that" cleanup waiting."""
    def _q():
        return (get_supabase().table("companion_memory_state")
                .select("companion_id, end_user_id, forget_pending")
                .eq("tenant_id", tenant_id).not_.is_("forget_pending", "null").limit(200).execute().data)
    return await asyncio.to_thread(_q) or []


# --- skipped message ranges (migration 261): what the card could not read, kept on record ---------

async def messages_range(tenant_id: str, companion_id: str, end_user_id: str, after: str, through: str,
                         limit: int) -> list[dict]:
    """Messages of this pair with after < created_at <= through, oldest first, at most `limit`."""
    def _q():
        return (get_supabase().table("companion_messages").select("id, role, content, created_at")
                .eq("tenant_id", tenant_id).eq("companion_id", companion_id).eq("end_user_id", end_user_id)
                .gt("created_at", after).lte("created_at", through).order("created_at").limit(limit)
                .execute().data)
    return await asyncio.to_thread(_q) or []


async def park_messages(tenant_id: str, companion_id: str, end_user_id: str, *, after: str, through: str,
                        count: int, mark: str | None) -> None:
    """Writes down a range the card could not read and moves the watermark past it, in ONE write, so the
    messages are either still waiting behind the watermark or on record here, never neither.
    A range that starts where the last one ended (`mark` is its `through`) is joined to it.
    Call only while holding the pair's claim (read, then write)."""
    ranges = list((await get_state(tenant_id, companion_id, end_user_id)).get("skipped") or [])
    last = ranges[-1] if ranges else None
    if last and mark and last.get("through") == mark and not last.get("dead"):
        ranges[-1] = {**last, "through": through, "count": int(last.get("count") or 0) + count}
    else:
        ranges.append({"after": after, "through": through, "count": count, "tries": 0, "since": _now()})
    await update_state(tenant_id, companion_id, end_user_id,
                       {"skipped": ranges, "last_message_at": through, "failures": 0})


async def set_skipped(tenant_id: str, companion_id: str, end_user_id: str, ranges: list[dict]) -> None:
    await update_state(tenant_id, companion_id, end_user_id, {"skipped": ranges or None})


async def pairs_with_skipped(tenant_id: str) -> list[dict]:
    """This business's pairs that have skipped message ranges on record."""
    def _q():
        return (get_supabase().table("companion_memory_state")
                .select("companion_id, end_user_id, skipped")
                .eq("tenant_id", tenant_id).not_.is_("skipped", "null").limit(500).execute().data)
    return await asyncio.to_thread(_q) or []
