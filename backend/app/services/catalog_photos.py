"""Which Catalogue photos the AI (or Share product) may send for an item.

A photo can be linked to a colour (catalog_media.colour, migration 333). A photo whose
colour is out of stock is never sent. A colour is out of stock when the item has variants
of that colour and every one of them has a tracked stock of 0. Photos with no colour are
always fine. Before the migration is applied nothing is linked, so every photo is fine.
"""
import logging

logger = logging.getLogger(__name__)

_FETCH = 60  # more than anyone sends; the filter runs after the fetch


def _key(colour) -> str:
    return " ".join(str(colour or "").split()).lower()


def out_of_stock_colours(db, tenant_id: str, item_id: str) -> set[str]:
    """Lower-cased colour names that have no stock left on this item."""
    try:
        rows = (db.table("catalog_item_variants").select("colour, stock_quantity")
                .eq("tenant_id", tenant_id).eq("catalog_item_id", item_id).execute()).data or []
    except Exception:
        return set()
    seen: dict[str, bool] = {}  # colour -> still has stock
    for v in rows:
        colour = _key(v.get("colour"))
        if not colour:
            continue
        qty = v.get("stock_quantity")
        has_stock = qty is None or int(qty) > 0  # untracked counts as in stock
        seen[colour] = seen.get(colour, False) or has_stock
    return {c for c, has in seen.items() if not has}


def sendable_photos(db, tenant_id: str, item_id: str, limit: int, columns: str = "id,storage_path,label") -> list[dict]:
    """The item's photos in saved order, minus those linked to an out-of-stock colour."""
    try:
        rows = (db.table("catalog_media").select(columns + ",colour")
                .eq("catalog_item_id", item_id).eq("tenant_id", tenant_id)
                .order("sort_order").limit(_FETCH).execute()).data or []
    except Exception:
        # migration 333 not applied yet: no photo is linked to a colour
        rows = (db.table("catalog_media").select(columns)
                .eq("catalog_item_id", item_id).eq("tenant_id", tenant_id)
                .order("sort_order").limit(_FETCH).execute()).data or []
    if any(_key(r.get("colour")) for r in rows):
        blocked = out_of_stock_colours(db, tenant_id, item_id)
        rows = [r for r in rows if _key(r.get("colour")) not in blocked]
    return rows[:max(limit, 0)]
