"""Push the Catalogue to the shop's Meta catalogue (the one WhatsApp, Facebook and Instagram show).

The shop's Catalogue stays the master list; Meta gets a copy. Every change Meta shows bumps
catalog_items.meta_change_seq (migration 300 triggers), so the every-minute meta-catalogue-sync
task sends only what changed: a sale in the shop reaches WhatsApp within about a minute.

What goes to Meta: products marked Ready with a price and a photo. An item with sizes and colours
goes as one Meta product per size/colour, grouped under the item (item_group_id), each with its
own stock. Drafts, other item types and deleted sizes are deleted from Meta. Meta answers a batch
later, so items wait as "sending" until the next run reads the batch result (synced or the exact
problem Meta gave).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v25.0"
BATCH_ITEMS = 100          # items per push (each can be up to 400 sizes x colours)
_ID_CHUNK = 80             # ids per .in_() filter, keeps the URL short
_MAX_PHOTOS = 10


def item_link(item_id: str) -> str:
    """The public page Meta links each product to (frontend /item/[id])."""
    base = (os.environ.get("FRONTEND_URL") or "https://www.anrilaitech.com").rstrip("/")
    return f"{base}/item/{item_id}"


SYNC_KEY = "meta_catalog_sync"  # "on" once the owner taps "Show on WhatsApp"; nothing is sent before


def linked_catalog(tenant_id: str) -> tuple[str, str] | None:
    """(catalog id, access token) of the Meta catalogue the shop connected, whether or not sync is on."""
    catalog_id = get_setting("meta_catalog_id", fallback=None, tenant_id=tenant_id)
    token = (get_setting("meta_catalog_access_token", fallback=None, tenant_id=tenant_id)
             or get_setting("meta_ads_access_token", fallback=None, tenant_id=tenant_id))
    if not catalog_id or not token:
        return None
    return str(catalog_id), str(token)


def connection(tenant_id: str) -> tuple[str, str] | None:
    """linked_catalog, only while the owner has the sync switched on."""
    if (get_setting(SYNC_KEY, fallback=None, tenant_id=tenant_id) or "") != "on":
        return None
    return linked_catalog(tenant_id)


def _price(paise: int) -> str:
    return f"{int(paise) / 100:.2f} INR"


def _availability(stock) -> str:
    # NULL stock = not tracked = always available (same rule as the AI reply).
    return "out of stock" if stock is not None and int(stock) <= 0 else "in stock"


def meta_products(item: dict, variants: list[dict], photo_urls: list[str], brand: str) -> tuple[list[dict] | None, str | None]:
    """What Meta should hold for this item.

    (None, None): not for Meta (draft, not a product) -- anything Meta has is deleted.
    ([], problem): should be on Meta but can't yet ("Add a photo", "Add a price").
    (products, None): the Meta products (data dicts, "id" = retailer id).
    """
    if item.get("item_type") != "product" or item.get("status") != "ready":
        return None, None
    if not photo_urls:
        return [], "Add a photo: Meta needs one for every product"
    base = {
        "title": (item.get("name") or "").strip()[:150],
        "description": ((item.get("description") or "").strip() or (item.get("name") or "").strip())[:9999],
        "condition": "new",
        "link": item_link(item["id"]),
        "image_link": photo_urls[0],
        "brand": (brand or "").strip()[:100] or "Shop",
    }
    if len(photo_urls) > 1:
        base["additional_image_link"] = photo_urls[1:_MAX_PHOTOS]
    if not variants:
        if item.get("price_paise") is None:
            return [], "Add a price: Meta needs a price for every product"
        product = {**base, "id": item["id"], "price": _price(item["price_paise"]),
                   "availability": _availability(item.get("stock_quantity"))}
        if item.get("stock_quantity") is not None:
            product["quantity_to_sell_on_facebook"] = max(int(item["stock_quantity"]), 0)
        return [product], None
    products = []
    for v in variants:
        price = v.get("price_paise") if v.get("price_paise") is not None else item.get("price_paise")
        if price is None:
            return [], "Add a price: Meta needs a price for every size and colour"
        product = {**base, "id": v["id"], "item_group_id": item["id"], "price": _price(price),
                   "availability": _availability(v.get("stock_quantity")),
                   "quantity_to_sell_on_facebook": max(int(v.get("stock_quantity") or 0), 0)}
        if v.get("size"):
            product["size"] = str(v["size"])[:100]
        if v.get("colour"):
            product["color"] = str(v["colour"])[:100]
        products.append(product)
    return products, None


def _chunks(values: list, size: int = _ID_CHUNK):
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _children(db, tenant_id: str, item_ids: list[str]) -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    """Sizes/colours and photo URLs per item, in the order the shop set."""
    variants: dict[str, list[dict]] = {}
    photos: dict[str, list[str]] = {}
    bucket = db.storage.from_("catalog-media")
    for chunk in _chunks(item_ids):
        for v in (
            db.table("catalog_item_variants").select("id, catalog_item_id, size, colour, stock_quantity, price_paise, sort_order")
            .eq("tenant_id", tenant_id).in_("catalog_item_id", chunk).order("sort_order").execute()
        ).data or []:
            variants.setdefault(v["catalog_item_id"], []).append(v)
        for m in (
            db.table("catalog_media").select("catalog_item_id, storage_path, sort_order")
            .eq("tenant_id", tenant_id).in_("catalog_item_id", chunk).order("sort_order").execute()
        ).data or []:
            photos.setdefault(m["catalog_item_id"], []).append(bucket.get_public_url(m["storage_path"]))
    return variants, photos


def _brand(db, tenant_id: str) -> str:
    from app.services.business_details import get_business_details
    try:
        return get_business_details(tenant_id, db).get("legal_name") or ""
    except Exception:
        return ""


def _meta_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return str(err.get("error_user_msg") or err.get("message") or resp.text)[:300]
    except ValueError:
        return resp.text[:300]


async def _post_batch(catalog_id: str, token: str, requests: list[dict]) -> tuple[str | None, str | None]:
    """(batch handle, error). Meta processes the batch afterwards; the handle reads the result."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GRAPH}/{catalog_id}/items_batch",
            data={"access_token": token, "item_type": "PRODUCT_ITEM", "requests": json.dumps(requests)},
        )
    if resp.status_code != 200:
        return None, _meta_error(resp)
    handles = (resp.json() or {}).get("handles") or []
    return (handles[0] if handles else None), None


async def push_tenant(db, tenant_id: str, *, limit: int = BATCH_ITEMS) -> dict:
    """Send this shop's changed items to Meta. Returns counts for the caller and the logs."""
    conn = connection(tenant_id)
    if not conn:
        return {"connected": False, "sent": 0}
    catalog_id, token = conn
    items = (
        db.table("catalog_items")
        .select("id, name, description, status, item_type, price_paise, stock_quantity, meta_change_seq, meta_retailer_ids")
        .eq("tenant_id", tenant_id).eq("meta_pending", True).limit(limit).execute()
    ).data or []
    if not items:
        return {"connected": True, "sent": 0}
    variants, photos = _children(db, tenant_id, [i["id"] for i in items])
    brand = _brand(db, tenant_id)

    requests: list[dict] = []
    outcome: dict[str, dict] = {}
    for item in items:
        products, problem = meta_products(item, variants.get(item["id"], []), photos.get(item["id"], []), brand)
        new_ids = [p["id"] for p in products or []]
        for old in item.get("meta_retailer_ids") or []:
            if old not in new_ids:
                requests.append({"method": "DELETE", "data": {"id": old}})
        for p in products or []:
            requests.append({"method": "UPDATE", "data": p})
        if products is None:
            state, error = None, None
        elif problem:
            state, error = "skipped", problem
        else:
            state, error = "sending", None
        outcome[item["id"]] = {"meta_retailer_ids": new_ids, "meta_sync_state": state, "meta_sync_error": error}

    handle, error = (None, None)
    if requests:
        try:
            handle, error = await _post_batch(catalog_id, token, requests)
        except httpx.HTTPError as e:
            error = f"Couldn't reach Meta: {e.__class__.__name__}"
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        row = {**outcome[item["id"]], "meta_synced_seq": item["meta_change_seq"]}
        if error:
            # Nothing reached Meta: keep what Meta had, show the problem. "Sync again" retries.
            row = {"meta_synced_seq": item["meta_change_seq"], "meta_sync_state": "error",
                   "meta_sync_error": f"Meta: {error}"}
        elif row["meta_sync_state"] == "sending":
            row["meta_batch_handle"] = handle
        elif row["meta_sync_state"] is None:
            row["meta_synced_at"] = now
        db.table("catalog_items").update(row).eq("id", item["id"]).eq("tenant_id", tenant_id).execute()
    if error:
        logger.warning("meta catalogue push failed tenant=%s: %s", tenant_id, error)
    return {"connected": True, "sent": len(items), "error": error}


async def check_sent(db, tenant_id: str) -> int:
    """Read Meta's answer for batches still marked sending. Returns how many items settled."""
    conn = connection(tenant_id)
    if not conn:
        return 0
    catalog_id, token = conn
    rows = (
        db.table("catalog_items").select("id, meta_batch_handle, meta_retailer_ids")
        .eq("tenant_id", tenant_id).eq("meta_sync_state", "sending").limit(500).execute()
    ).data or []
    by_handle: dict[str, list[dict]] = {}
    for r in rows:
        by_handle.setdefault(r.get("meta_batch_handle") or "", []).append(r)
    settled = 0
    now = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=20) as client:
        for handle, group in by_handle.items():
            if not handle:
                for r in group:
                    db.table("catalog_items").update({"meta_sync_state": "synced", "meta_synced_at": now}) \
                        .eq("id", r["id"]).eq("tenant_id", tenant_id).execute()
                settled += len(group)
                continue
            try:
                resp = await client.get(f"{GRAPH}/{catalog_id}/check_batch_request_status",
                                        params={"handle": handle, "access_token": token})
            except httpx.HTTPError:
                continue
            if resp.status_code != 200:
                continue
            status = ((resp.json() or {}).get("data") or [{}])[0]
            if status.get("status") not in ("finished", "error"):
                continue
            errors = status.get("errors") or []
            unplaced = [e for e in errors if not e.get("id")]
            for r in group:
                mine = [e for e in errors if e.get("id") and e["id"] in (r.get("meta_retailer_ids") or [])] or unplaced
                update = ({"meta_sync_state": "error", "meta_sync_error": f"Meta: {str(mine[0].get('message') or 'rejected')[:300]}"}
                          if mine or status.get("status") == "error"
                          else {"meta_sync_state": "synced", "meta_sync_error": None, "meta_synced_at": now})
                db.table("catalog_items").update(update).eq("id", r["id"]).eq("tenant_id", tenant_id).execute()
            settled += len(group)
    return settled


async def delete_from_meta(tenant_id: str, retailer_ids: list[str]) -> None:
    """A deleted item: take its products off Meta (best effort, the item is gone either way)."""
    conn = connection(tenant_id)
    if not conn or not retailer_ids:
        return
    catalog_id, token = conn
    try:
        _, error = await _post_batch(catalog_id, token, [{"method": "DELETE", "data": {"id": rid}} for rid in retailer_ids])
        if error:
            logger.warning("meta catalogue delete failed tenant=%s: %s", tenant_id, error)
    except httpx.HTTPError as e:
        logger.warning("meta catalogue delete failed tenant=%s: %s", tenant_id, e)


def resend_all(db, tenant_id: str) -> None:
    """"Sync again" (and switching the sync on): every item goes on the next push."""
    db.table("catalog_items").update({"meta_synced_seq": 0}).eq("tenant_id", tenant_id).execute()


def set_sync(db, tenant_id: str, on: bool) -> None:
    """Switch the push on (everything goes once) or off (Meta keeps what it has; nothing more is sent)."""
    from app.config_dynamic import invalidate_cache
    db.table("app_settings").upsert({
        "tenant_id": tenant_id, "key": SYNC_KEY, "value": "on" if on else "off", "is_secret": False,
        "updated_at": "now()",
    }, on_conflict="tenant_id,key").execute()
    invalidate_cache(SYNC_KEY)
    if on:
        resend_all(db, tenant_id)


def status(db, tenant_id: str) -> dict:
    """The Catalogue page's Meta line: connected?, which catalogue, and how many items are where."""
    linked = linked_catalog(tenant_id) is not None
    sync_on = linked and connection(tenant_id) is not None
    rows = (
        db.table("catalog_items").select("meta_sync_state, meta_pending, meta_synced_at")
        .eq("tenant_id", tenant_id).eq("item_type", "product").limit(5000).execute()
    ).data or []
    counts = {"synced": 0, "sending": 0, "error": 0, "skipped": 0, "waiting": 0}
    last = None
    for r in rows:
        if r.get("meta_pending"):
            counts["waiting"] += 1
        elif r.get("meta_sync_state") in counts:
            counts[r["meta_sync_state"]] += 1
        if r.get("meta_synced_at") and (last is None or r["meta_synced_at"] > last):
            last = r["meta_synced_at"]
    return {
        "connected": linked,
        "sync_on": sync_on,
        "catalog_name": get_setting("meta_catalog_name", fallback=None, tenant_id=tenant_id) if linked else None,
        "counts": counts,
        "last_synced_at": last,
    }


async def sync_all_tenants() -> None:
    """The every-minute task: for each shop with a Meta catalogue, read answers, then push changes."""
    db = get_supabase()
    tenants = {
        r["tenant_id"] for r in (
            db.table("app_settings").select("tenant_id").eq("key", SYNC_KEY).eq("value", "on").limit(5000).execute()
        ).data or [] if r.get("tenant_id")
    }
    for tenant_id in tenants:
        try:
            await check_sent(db, tenant_id)
            await push_tenant(db, tenant_id)
        except Exception:
            logger.exception("meta catalogue sync failed tenant=%s", tenant_id)
