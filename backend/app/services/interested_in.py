"""Customers > "Interested in": the Catalogue items a person has shown interest in.

Stored on the lead as interested_item_ids (migration 333). Every read and write is
scoped to the tenant; an id that is not one of the tenant's Catalogue items is dropped.
Reads never raise: before the migration is applied the list is simply empty.
"""
import logging

logger = logging.getLogger(__name__)

MAX_ITEMS = 10


def _clean_ids(ids) -> list[str]:
    seen: list[str] = []
    for raw in ids or []:
        value = str(raw).strip()
        if value and value not in seen:
            seen.append(value)
    return seen[:MAX_ITEMS]


def items_for(db, tenant_id: str, lead_id: str, item_ids=None) -> list[dict]:
    """[{id, name}] for the lead's interested items (items deleted since are skipped).
    item_ids: the lead's already-loaded list, which saves the read of the lead row."""
    try:
        if item_ids is None:
            rows = (db.table("leads").select("interested_item_ids").eq("id", lead_id)
                    .eq("tenant_id", tenant_id).is_("deleted_at", "null").limit(1).execute()).data or []
            item_ids = (rows[0] if rows else {}).get("interested_item_ids")
        ids = _clean_ids(item_ids)
        if not ids:
            return []
        found = (db.table("catalog_items").select("id,name").eq("tenant_id", tenant_id)
                 .in_("id", ids).execute()).data or []
    except Exception:
        logger.warning("interested_in: could not read for lead %s", lead_id)
        return []
    by_id = {str(r["id"]): r for r in found}
    return [{"id": i, "name": by_id[i].get("name") or ""} for i in ids if i in by_id]


def set_items(db, tenant_id: str, lead_id: str, item_ids) -> list[dict]:
    """Replace the list. Unknown / other-tenant ids are dropped. Returns what was saved."""
    ids = _clean_ids(item_ids)
    valid: list[dict] = []
    if ids:
        found = (db.table("catalog_items").select("id,name").eq("tenant_id", tenant_id)
                 .in_("id", ids).execute()).data or []
        by_id = {str(r["id"]): r for r in found}
        valid = [{"id": i, "name": by_id[i].get("name") or ""} for i in ids if i in by_id]
    (db.table("leads").update({"interested_item_ids": [v["id"] for v in valid]})
     .eq("id", lead_id).eq("tenant_id", tenant_id).execute())
    return valid


def prompt_line(db, tenant_id: str, lead_id: str, item_ids=None) -> str:
    """One short fact line for the AI reply prompt, or '' when there is nothing.
    Names are item names a business typed: one line each, capped, never a paragraph."""
    names = []
    for i in items_for(db, tenant_id, lead_id, item_ids):
        name = " ".join((i["name"] or "").split())[:80]
        if name:
            names.append(name)
    if not names:
        return ""
    return "Interested in: " + ", ".join(names[:5])
