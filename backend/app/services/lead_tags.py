"""Customers > tags: plain words on a person ("VIP", "wedding order").

Rules (the same ones the table lead_tags enforces, applied here first so the owner gets plain words):
  * a tag is trimmed text, 1-30 characters
  * at most MAX_TAGS_PER_PERSON per person; over the limit is skipped and counted, never an error
  * "VIP" = "vip": matching ignores case, the first spelling stays
Every query is scoped to the tenant. The table is new (migration 320): if it is missing the reads
return empty and the writes report nothing done, instead of failing.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_TAG_LEN = 30
MAX_TAGS_PER_PERSON = 10
MAX_LEADS_PER_CALL = 1000
_CHUNK = 200
_PAGE = 1000


def clean_tags(raw) -> list[str]:
    """Trimmed, 1-30 chars, de-duplicated case-insensitively (first spelling kept), order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw or []:
        if not isinstance(item, str):
            continue
        tag = " ".join(item.split())
        if not tag or len(tag) > MAX_TAG_LEN:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def _chunks(items: list[str], n: int = _CHUNK):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _all_rows(build) -> list[dict]:
    """Every row of a query, paged through the 1000-row cap."""
    rows: list[dict] = []
    while True:
        page = build().range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows


def tags_by_lead(db, tenant_id: str, lead_ids: list[str]) -> dict[str, list[str]]:
    """lead id -> its tags (oldest first). Missing table or any error -> {} (a tag is never worth failing a page)."""
    out: dict[str, list[str]] = {}
    ids = [str(i) for i in lead_ids if i]
    if not ids:
        return out
    try:
        for part in _chunks(ids):
            rows = (db.table("lead_tags").select("lead_id,tag,created_at").eq("tenant_id", tenant_id)
                    .in_("lead_id", part).order("created_at").execute().data or [])
            for r in rows:
                out.setdefault(str(r["lead_id"]), []).append(r["tag"])
    except Exception as e:
        logger.warning("lead_tags lookup failed: %s", e)
        return {}
    return out


def tags_in_use(db, tenant_id: str) -> list[dict]:
    """[{tag, count}] for every tag in use, most used first. Case-insensitive: counts merge under the first spelling."""
    try:
        rows = _all_rows(lambda: db.table("lead_tags").select("lead_id,tag,created_at")
                         .eq("tenant_id", tenant_id).order("created_at").order("lead_id").order("tag"))
    except Exception as e:
        logger.warning("lead_tags list failed: %s", e)
        return []
    spelling: dict[str, str] = {}
    people: dict[str, set[str]] = {}
    for r in rows:
        tag = r.get("tag") or ""
        key = tag.lower()
        spelling.setdefault(key, tag)
        people.setdefault(key, set()).add(str(r["lead_id"]))
    out = [{"tag": spelling[k], "count": len(v)} for k, v in people.items()]
    out.sort(key=lambda x: (-x["count"], x["tag"].lower()))
    return out


def tag_spellings(db, tenant_id: str, tag: str) -> list[str]:
    """Every spelling of `tag` in use for this tenant, ignoring case ("VIP" and "vip"). [] when none or on any error."""
    wanted = " ".join((tag or "").split()).lower()
    if not wanted or len(wanted) > MAX_TAG_LEN:
        return []
    # ilike with every wildcard-ish character turned into the one-character wildcard "_": it may over-match
    # ("a_b" also finds "a*b"), so the exact comparison is made here.
    pattern = "".join("_" if c in "%_*\\" else c for c in wanted)
    try:
        rows = _all_rows(lambda: db.table("lead_tags").select("lead_id,tag,created_at").eq("tenant_id", tenant_id)
                         .ilike("tag", pattern).order("created_at").order("lead_id").order("tag"))
    except Exception as e:
        logger.warning("lead_tags spelling lookup failed: %s", e)
        return []
    # Oldest first, so the first spelling ever used comes first.
    return list(dict.fromkeys(r["tag"] for r in rows if (r.get("tag") or "").lower() == wanted))


def _live_lead_ids(db, tenant_id: str, lead_ids: list[str]) -> list[str]:
    """The ids that are this tenant's (not deleted), in the order given."""
    found: set[str] = set()
    for part in _chunks(lead_ids):
        for r in (db.table("leads").select("id").eq("tenant_id", tenant_id).is_("deleted_at", "null")
                  .in_("id", part).execute().data or []):
            found.add(str(r["id"]))
    return [i for i in lead_ids if i in found]


def add_tags(db, tenant_id: str, lead_ids: list[str], tags: list[str], *, user_id: str | None = None) -> dict:
    """Give each person each tag. Returns {"added": n, "removed": 0, "skipped_limit": n}.

    added = (person, tag) pairs newly written. A person already holding the tag (any case) is not counted.
    skipped_limit = pairs left out because the person already has MAX_TAGS_PER_PERSON tags.
    """
    ids = list(dict.fromkeys(str(i) for i in (lead_ids or []) if i))[:MAX_LEADS_PER_CALL]
    wanted = clean_tags(tags)
    result = {"added": 0, "removed": 0, "skipped_limit": 0}
    if not ids or not wanted:
        return result
    ids = _live_lead_ids(db, tenant_id, ids)
    # A tag already in use keeps the spelling it was first given ("vip" is stored as "VIP" if "VIP" exists).
    wanted = [(tag_spellings(db, tenant_id, t) or [t])[0] for t in wanted]
    have = tags_by_lead(db, tenant_id, ids)
    new_rows: list[dict] = []
    for lid in ids:
        current = list(have.get(lid, []))
        keys = {t.lower() for t in current}
        for tag in wanted:
            if tag.lower() in keys:
                continue
            if len(current) >= MAX_TAGS_PER_PERSON:
                result["skipped_limit"] += 1
                continue
            current.append(tag)
            keys.add(tag.lower())
            new_rows.append({"tenant_id": tenant_id, "lead_id": lid, "tag": tag, "created_by": user_id})
    for part in _chunks(new_rows):
        try:
            db.table("lead_tags").upsert(part, on_conflict="lead_id,tag", ignore_duplicates=True).execute()
            result["added"] += len(part)
        except Exception as e:  # table missing, or a race with the unique "VIP" = "vip" rule
            logger.warning("lead_tags add failed: %s", e)
    return result


def remove_tags(db, tenant_id: str, lead_ids: list[str], tags: list[str]) -> dict:
    """Take each tag off each person (case-insensitive). Returns {"added": 0, "removed": n, "skipped_limit": 0}."""
    ids = list(dict.fromkeys(str(i) for i in (lead_ids or []) if i))[:MAX_LEADS_PER_CALL]
    wanted = {t.lower() for t in clean_tags(tags)}
    result = {"added": 0, "removed": 0, "skipped_limit": 0}
    if not ids or not wanted:
        return result
    have = tags_by_lead(db, tenant_id, ids)
    for lid in ids:
        for tag in have.get(lid, []):
            if tag.lower() not in wanted:
                continue
            try:
                db.table("lead_tags").delete().eq("tenant_id", tenant_id).eq("lead_id", lid).eq("tag", tag).execute()
                result["removed"] += 1
            except Exception as e:
                logger.warning("lead_tags remove failed: %s", e)
    return result
