"""Teach & offers: what the owner taught the AI agent, and the offers that are on now.

Two tables (migration 311, tenant-scoped, backend service key only):
  ai_teach_items  kind 'answer' (a doubt + how to answer it), kind 'word' (a word the shop uses) and
                  kind 'liked' (a customer message + a reply the owner liked; the AI copies its style, migration 340).
                  One row per (tenant, kind, match_key), so the same question taught twice is one row.
  ai_offers       an offer with a required end date; the AI mentions it only between starts_on and ends_on.

prompt_block() is the text added to every AI reply prompt (ai_reply.build_reply_system_prompt):
always the TODAY line, plus offers / taught answers / words only when there are any. It never raises."""
import logging
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
KINDS = ("answer", "word", "liked")
SOURCES = ("manual", "chat", "couldnt_answer")

MAX_PROMPT = {"answer": 300, "word": 80, "liked": 300}
MAX_REPLY = 1000
MAX_TITLE = 120
MAX_DETAILS = 500
MAX_OFFER_DAYS = 365
MEDIA_RULE_KEY = "ai_media_rule"          # app_settings: what to do when a customer sends a photo or voice note
MAX_MEDIA_RULE = 300
ENDED_KEEP_DAYS = 60

MAX_ANSWER_ITEMS = 60
MAX_ANSWER_CHARS = 2500
MAX_WORD_ITEMS = 80
MAX_WORD_CHARS = 1500
MAX_LIKED_SAVED = 50      # examples a business can keep
MAX_LIKED_PROMPT = 10     # the newest ones the AI reads
MAX_LIKED_CHARS = 3000
_CACHE_SECONDS = 60.0

NOT_READY = "Teach & offers not ready"


class TeachError(Exception):
    """A plain-words problem the owner can fix. `status` is the HTTP code the route answers with."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class TableMissing(Exception):
    """Migration 311 is not applied yet."""


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(IST)).astimezone(IST).date()


def match_key(text: str) -> str:
    """Lowercased, trimmed, punctuation and extra spaces removed. Unicode letters (Tamil) are kept."""
    cleaned = re.sub(r"[^\w\s]|_", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_missing(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("42p01", "pgrst205", "does not exist", "schema cache", "could not find the table"))


def _run(fn):
    """Runs a query; a missing table becomes TableMissing, anything else passes through."""
    try:
        return fn()
    except Exception as exc:
        if _is_missing(exc):
            raise TableMissing() from exc
        raise


# ---------------------------------------------------------------- the prompt block

_cache: dict[tuple[str, str], tuple[float, str]] = {}


def clear_cache(tenant_id: str | None = None) -> None:
    if tenant_id is None:
        _cache.clear()
    else:
        for key in [k for k in _cache if k[0] == tenant_id]:
            _cache.pop(key, None)


def _rows(res) -> list[dict]:
    data = getattr(res, "data", None)
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def today_line(now: datetime | None = None) -> str:
    d = today_ist(now)
    return f"\n\nTODAY: {d.strftime('%A')} {_fmt_date(d)} (India time)."


def _live_offers(rows: list[dict], today: date) -> list[dict]:
    live = []
    for r in rows:
        try:
            if date.fromisoformat(str(r["starts_on"])[:10]) <= today <= date.fromisoformat(str(r["ends_on"])[:10]):
                live.append(r)
        except (KeyError, ValueError):
            continue
    return sorted(live, key=lambda r: str(r["ends_on"]))


def read_media_rule(db, tenant_id: str) -> str:
    """The owner's rule for photos and voice notes ("" when none). Never raises: a read problem means no rule."""
    try:
        row = (db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", MEDIA_RULE_KEY)
               .maybe_single().execute())
        return _squash(row.data.get("value")) if row and isinstance(row.data, dict) else ""
    except Exception as exc:
        logger.warning("Teach media rule not read for tenant %s: %s", tenant_id, exc)
        return ""


def save_media_rule(db, tenant_id: str, rule: str) -> str:
    """Saves (or clears, when empty) the photo/voice-note rule and drops the cached prompt block."""
    text = _squash(rule)
    if len(text) > MAX_MEDIA_RULE:
        raise TeachError(f"Keep it under {MAX_MEDIA_RULE} characters.")
    db.table("app_settings").upsert(
        {"tenant_id": tenant_id, "key": MEDIA_RULE_KEY, "value": text, "is_secret": False}, on_conflict="key,tenant_id",
    ).execute()
    try:
        from app.config_dynamic import invalidate_cache
        invalidate_cache(MEDIA_RULE_KEY)
    except Exception:
        pass
    clear_cache(tenant_id)
    return text


def _taught_text(db, tenant_id: str, today: date) -> str:
    parts: list[str] = []
    media = read_media_rule(db, tenant_id)
    if media:
        parts.append(f"\n\nWHEN A CUSTOMER SENDS A PHOTO OR VOICE NOTE: {media}")

    offers = _live_offers(_rows(
        db.table("ai_offers").select("title,details,starts_on,ends_on")
        .eq("tenant_id", tenant_id).is_("deleted_at", "null").gte("ends_on", today.isoformat())
        .order("ends_on").limit(50).execute()), today)
    if offers:
        lines = []
        for o in offers:
            line = f"- {_squash(o.get('title'))}"
            if _squash(o.get("details")):
                line += f": {_squash(o['details'])}"
            lines.append(f"{line} (ends {_fmt_date(date.fromisoformat(str(o['ends_on'])[:10]))})")
        parts.append("\n\nOFFERS ON NOW (mention only these; never invent offers or dates):\n" + "\n".join(lines))

    for kind, cap_items, cap_chars, heading, template in (
        ("answer", MAX_ANSWER_ITEMS, MAX_ANSWER_CHARS,
         "ANSWERS THE OWNER TAUGHT YOU (use these exact facts when a customer asks something similar):", "- {p} -> {r}"),
        ("word", MAX_WORD_ITEMS, MAX_WORD_CHARS, "WORDS THIS SHOP USES:", "- {p} = {r}"),
        ("liked", MAX_LIKED_PROMPT, MAX_LIKED_CHARS,
         "REPLIES THE OWNER LIKED (copy their tone, length, language mix and emoji use. Style only: never copy "
         "their prices, offers or facts; those come only from the catalogue, knowledge and offers above):",
         "- Customer: {p}\n  Reply: {r}"),
    ):
        items = _rows(
            db.table("ai_teach_items").select("prompt,reply,updated_at")
            .eq("tenant_id", tenant_id).eq("kind", kind).order("updated_at", desc=True).limit(cap_items).execute())
        lines, used = [], 0
        for it in items:
            line = template.format(p=_squash(it.get("prompt")), r=_squash(it.get("reply")))
            if used + len(line) + 1 > cap_chars:
                continue
            lines.append(line)
            used += len(line) + 1
        if lines:
            parts.append(f"\n\n{heading}\n" + "\n".join(lines))
    return "".join(parts)


def prompt_block(db, tenant_id: str, now: datetime | None = None) -> str:
    """TODAY line (always) + offers on now + taught answers + words. Cached per tenant for 60 s.
    Any read problem logs one warning per cache window and adds only the TODAY line."""
    now = now or datetime.now(IST)
    today = today_ist(now)
    head = today_line(now)
    key = (tenant_id, today.isoformat())
    hit = _cache.get(key)
    mono = time.monotonic()
    if hit and mono - hit[0] < _CACHE_SECONDS:
        return head + hit[1]
    try:
        extra = _taught_text(db, tenant_id, today)
    except Exception as exc:
        logger.warning("Teach & offers prompt block skipped for tenant %s: %s", tenant_id, exc)
        extra = ""
    _cache[key] = (mono, extra)
    return head + extra


# ---------------------------------------------------------------- answers and words

def _clean_item(kind: str, prompt: str, reply: str) -> tuple[str, str, str]:
    if kind not in KINDS:
        raise TeachError("Kind must be answer, word or liked.")
    label = {"answer": "question", "word": "word", "liked": "customer's message"}[kind]
    prompt, reply = _squash(prompt), (reply or "").strip()
    if not prompt:
        raise TeachError(f"Write the {label} first.")
    if len(prompt) > MAX_PROMPT[kind]:
        raise TeachError(f"The {label} is too long (most {MAX_PROMPT[kind]} characters).")
    if not reply:
        raise TeachError({"answer": "Write the answer first.", "word": "Write what it means first.",
                          "liked": "Write the reply first."}[kind])
    if len(reply) > MAX_REPLY:
        raise TeachError(f"That is too long (most {MAX_REPLY} characters).")
    key = match_key(prompt)
    if not key:
        raise TeachError(f"The {label} needs some letters or numbers.")
    return prompt, reply, key


def _now_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


def list_items(db, tenant_id: str, kind: str | None = None) -> list[dict]:
    def read():
        q = db.table("ai_teach_items").select("*").eq("tenant_id", tenant_id)
        if kind:
            q = q.eq("kind", kind)
        return q.order("updated_at", desc=True).limit(1000).execute()
    try:
        return _rows(_run(read))
    except TableMissing:
        return []


def save_item(db, tenant_id: str, kind: str, prompt: str, reply: str, *, source: str = "manual",
              user_id: str | None = None, message_id: str | None = None) -> dict:
    """Adds an item. The same question (match_key) again updates that row's reply, bumps times_taught
    and updated_at: one row, counted once per teaching."""
    prompt, reply, key = _clean_item(kind, prompt, reply)
    if source not in SOURCES:
        source = "manual"
    for _ in range(2):  # the second pass covers two people saving the same question at once
        found = _run(lambda: db.table("ai_teach_items").select("*").eq("tenant_id", tenant_id)
                     .eq("kind", kind).eq("match_key", key).limit(1).execute())
        existing = _rows(found)
        if existing:
            row = existing[0]
            patch = {"reply": reply, "prompt": prompt, "times_taught": int(row.get("times_taught") or 1) + 1,
                     "updated_at": _now_iso()}
            if message_id:
                patch["message_id"] = message_id
            res = _run(lambda: db.table("ai_teach_items").update(patch)
                       .eq("id", row["id"]).eq("tenant_id", tenant_id).execute())
            clear_cache(tenant_id)
            return {**row, **patch, **(_rows(res)[0] if _rows(res) else {})}
        if kind == "liked" and _liked_count(db, tenant_id) >= MAX_LIKED_SAVED:
            raise TeachError(f"You have {MAX_LIKED_SAVED} replies you like. Remove one first.")
        try:
            res = _run(lambda: db.table("ai_teach_items").insert({
                "tenant_id": tenant_id, "kind": kind, "prompt": prompt, "reply": reply, "match_key": key,
                "source": source, "created_by": user_id,
                **({"message_id": message_id} if message_id else {})}).execute())
            clear_cache(tenant_id)
            return _rows(res)[0]
        except TableMissing:
            raise
        except Exception as exc:
            if "23505" not in str(exc) and "duplicate" not in str(exc).lower():
                raise
    raise TeachError("Could not save that. Try again.", 409)


def update_item(db, tenant_id: str, item_id: str, prompt: str | None, reply: str | None) -> dict:
    found = _rows(_run(lambda: db.table("ai_teach_items").select("*").eq("id", item_id)
                       .eq("tenant_id", tenant_id).limit(1).execute()))
    if not found:
        raise TeachError("Not found.", 404)
    row = found[0]
    new_prompt, new_reply, key = _clean_item(
        row["kind"], row["prompt"] if prompt is None else prompt, row["reply"] if reply is None else reply)
    if key != row["match_key"]:
        clash = _rows(_run(lambda: db.table("ai_teach_items").select("id").eq("tenant_id", tenant_id)
                           .eq("kind", row["kind"]).eq("match_key", key).limit(1).execute()))
        if clash and clash[0]["id"] != item_id:
            raise TeachError("You already have this one. Edit that entry instead.")
    patch = {"prompt": new_prompt, "reply": new_reply, "match_key": key, "updated_at": _now_iso()}
    res = _run(lambda: db.table("ai_teach_items").update(patch).eq("id", item_id).eq("tenant_id", tenant_id).execute())
    clear_cache(tenant_id)
    return {**row, **patch, **(_rows(res)[0] if _rows(res) else {})}


def delete_item(db, tenant_id: str, item_id: str) -> None:
    res = _run(lambda: db.table("ai_teach_items").delete().eq("id", item_id).eq("tenant_id", tenant_id).execute())
    if not _rows(res):
        raise TeachError("Not found.", 404)
    clear_cache(tenant_id)


# ---------------------------------------------------------------- replies you like (👍 in Chats)

def _liked_count(db, tenant_id: str) -> int:
    res = _run(lambda: db.table("ai_teach_items").select("id", count="exact").eq("tenant_id", tenant_id)
               .eq("kind", "liked").execute())
    count = getattr(res, "count", None)
    return int(count) if isinstance(count, int) else len(_rows(res))


def like_message(db, tenant_id: str, message_id: str, user_id: str | None = None, *,
                 caller_id: str | None = None) -> dict:
    """👍 on an AI agent reply in Chats: saves it with the customer's message(s) just before it.
    caller_id (a telecaller): only replies on their own customers, like the thumbs-down."""
    try:
        found = _rows(db.table("messages").select("id, lead_id, direction, is_ai_generated, content, created_at")
                      .eq("id", message_id).eq("tenant_id", tenant_id).limit(1).execute())
    except Exception:  # a malformed id is just "not found", never a 500
        found = []
    if not found:
        raise TeachError("That message was not found.", 404)
    msg = found[0]
    if msg.get("direction") != "outbound" or not msg.get("is_ai_generated"):
        raise TeachError("Only replies the AI agent sent can be liked.")
    if caller_id is not None:
        lead = _rows(db.table("leads").select("assigned_to").eq("id", msg["lead_id"]).eq("tenant_id", tenant_id)
                     .limit(1).execute())
        if not lead or lead[0].get("assigned_to") != caller_id:
            raise TeachError("That message was not found.", 404)
    reply = (msg.get("content") or "").strip()
    if not reply:
        raise TeachError("This reply has no words to copy.")
    if len(reply) > MAX_REPLY:
        raise TeachError(f"This reply is too long to use as an example (most {MAX_REPLY} characters).")
    before = _rows(db.table("messages").select("direction, content").eq("tenant_id", tenant_id)
                   .eq("lead_id", msg["lead_id"]).lt("created_at", msg["created_at"])
                   .order("created_at", desc=True).limit(6).execute())
    asked: list[str] = []
    for row in before:  # newest first: the customer's messages since the business last wrote
        if row.get("direction") != "inbound":
            break
        if _squash(row.get("content")):
            asked.append(_squash(row["content"]))
        if len(asked) == 3:
            break
    if not asked:
        raise TeachError("There is no customer message just before this reply, so there is nothing to pair it with.")
    prompt = " / ".join(reversed(asked))[-MAX_PROMPT["liked"]:]
    return save_item(db, tenant_id, "liked", prompt, reply, source="chat", user_id=user_id, message_id=message_id)


def unlike_message(db, tenant_id: str, message_id: str) -> None:
    _run(lambda: db.table("ai_teach_items").delete().eq("tenant_id", tenant_id).eq("kind", "liked")
         .eq("message_id", message_id).execute())
    clear_cache(tenant_id)


def liked_message_ids(db, tenant_id: str, message_ids: list[str]) -> list[str]:
    """Which of these messages are saved as replies you like (for the 👍 state in Chats)."""
    if not message_ids:
        return []
    try:
        rows = _rows(_run(lambda: db.table("ai_teach_items").select("message_id").eq("tenant_id", tenant_id)
                          .eq("kind", "liked").in_("message_id", message_ids[:200]).execute()))
    except TableMissing:
        return []
    return [r["message_id"] for r in rows if r.get("message_id")]


# ---------------------------------------------------------------- offers

def _parse_day(value, what: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise TeachError(f"{what} is not a valid date.") from None


def _check_offer(title: str, details: str | None, starts_on, ends_on, today: date, *, check_end_today: bool) -> dict:
    title = _squash(title)
    if not title:
        raise TeachError("Give the offer a name.")
    if len(title) > MAX_TITLE:
        raise TeachError(f"The offer name is too long (most {MAX_TITLE} characters).")
    details = (details or "").strip() or None
    if details and len(details) > MAX_DETAILS:
        raise TeachError(f"The details are too long (most {MAX_DETAILS} characters).")
    if not ends_on:
        raise TeachError("Pick the date this offer ends.")
    start = _parse_day(starts_on, "The start date") if starts_on else today
    end = _parse_day(ends_on, "The end date")
    if end < start:
        raise TeachError("The end date can't be before the start date.")
    if end > start + timedelta(days=MAX_OFFER_DAYS):
        raise TeachError("An offer can run for 365 days at most.")
    if check_end_today and end < today:
        raise TeachError("The end date has to be today or later.")
    return {"title": title, "details": details, "starts_on": start.isoformat(), "ends_on": end.isoformat()}


def offer_status(row: dict, today: date) -> str:
    start, end = date.fromisoformat(str(row["starts_on"])[:10]), date.fromisoformat(str(row["ends_on"])[:10])
    return "upcoming" if start > today else "ended" if end < today else "live"


def list_offers(db, tenant_id: str, now: datetime | None = None) -> list[dict]:
    """Live first, then starting later, then ended in the last 60 days. Each row has a `status`."""
    today = today_ist(now)
    oldest = (today - timedelta(days=ENDED_KEEP_DAYS)).isoformat()
    try:
        rows = _rows(_run(lambda: db.table("ai_offers").select("*").eq("tenant_id", tenant_id)
                          .is_("deleted_at", "null").gte("ends_on", oldest).limit(500).execute()))
    except TableMissing:
        return []
    out = [{**r, "status": offer_status(r, today)} for r in rows]
    # Live and upcoming: the one ending soonest first. Ended: the most recently ended first.
    by_end = lambda r: str(r["ends_on"])[:10]  # noqa: E731
    live = sorted((r for r in out if r["status"] == "live"), key=by_end)
    upcoming = sorted((r for r in out if r["status"] == "upcoming"), key=by_end)
    ended = sorted((r for r in out if r["status"] == "ended"), key=by_end, reverse=True)
    return live + upcoming + ended


def create_offer(db, tenant_id: str, title: str, details: str | None, starts_on, ends_on, *,
                 source: str = "manual", broadcast_ref: str | None = None, user_id: str | None = None,
                 now: datetime | None = None) -> dict:
    fields = _check_offer(title, details, starts_on, ends_on, today_ist(now), check_end_today=True)
    res = _run(lambda: db.table("ai_offers").insert({
        "tenant_id": tenant_id, **fields, "source": source if source in ("manual", "reach") else "manual",
        "broadcast_ref": broadcast_ref, "created_by": user_id}).execute())
    clear_cache(tenant_id)
    return _rows(res)[0]


def _get_offer(db, tenant_id: str, offer_id: str) -> dict:
    found = _rows(_run(lambda: db.table("ai_offers").select("*").eq("id", offer_id)
                       .eq("tenant_id", tenant_id).is_("deleted_at", "null").limit(1).execute()))
    if not found:
        raise TeachError("Not found.", 404)
    return found[0]


def update_offer(db, tenant_id: str, offer_id: str, changes: dict, now: datetime | None = None) -> dict:
    row = _get_offer(db, tenant_id, offer_id)
    today = today_ist(now)
    new_end = changes.get("ends_on", row["ends_on"])
    ends_changed = "ends_on" in changes and str(new_end)[:10] != str(row["ends_on"])[:10]
    fields = _check_offer(
        changes.get("title", row["title"]), changes.get("details", row.get("details")),
        changes.get("starts_on", row["starts_on"]), new_end, today, check_end_today=ends_changed)
    patch = {**fields, "updated_at": _now_iso()}
    res = _run(lambda: db.table("ai_offers").update(patch).eq("id", offer_id).eq("tenant_id", tenant_id).execute())
    clear_cache(tenant_id)
    return {**row, **patch, **(_rows(res)[0] if _rows(res) else {})}


def end_offer(db, tenant_id: str, offer_id: str, now: datetime | None = None) -> dict:
    """End now: the offer stops today. Ends yesterday when it had started before today, otherwise it
    never ran, so it is deleted."""
    row = _get_offer(db, tenant_id, offer_id)
    yesterday = today_ist(now) - timedelta(days=1)
    if yesterday >= date.fromisoformat(str(row["starts_on"])[:10]):
        _run(lambda: db.table("ai_offers").update({"ends_on": yesterday.isoformat(), "updated_at": _now_iso()})
             .eq("id", offer_id).eq("tenant_id", tenant_id).execute())
        deleted = False
    else:
        _run(lambda: db.table("ai_offers").update({"deleted_at": _now_iso()})
             .eq("id", offer_id).eq("tenant_id", tenant_id).execute())
        deleted = True
    clear_cache(tenant_id)
    return {"ended": True, "deleted": deleted}


def delete_offer(db, tenant_id: str, offer_id: str) -> None:
    _get_offer(db, tenant_id, offer_id)
    _run(lambda: db.table("ai_offers").update({"deleted_at": _now_iso()})
         .eq("id", offer_id).eq("tenant_id", tenant_id).execute())
    clear_cache(tenant_id)


def check_reach_offer(title: str, ends_on, details: str | None, starts_on=None, now: datetime | None = None) -> None:
    """Reach checks the offer BEFORE anything is sent, so a bad end date is a 422, not a silent miss."""
    _check_offer(title, details, starts_on, ends_on, today_ist(now), check_end_today=True)


def create_reach_offer(db, tenant_id: str, title: str, ends_on, details: str | None, broadcast_ref: str | None,
                       user_id: str | None, starts_on=None) -> bool:
    """Reach marked this campaign as an offer (already checked by check_reach_offer). A scheduled
    campaign's offer starts on the day it goes out. Never raises: the campaign is already queued."""
    try:
        create_offer(db, tenant_id, title, details, starts_on, ends_on, source="reach",
                     broadcast_ref=broadcast_ref, user_id=user_id)
        return True
    except Exception as exc:
        logger.warning("Reach offer not saved for tenant %s: %s", tenant_id, exc)
        return False
