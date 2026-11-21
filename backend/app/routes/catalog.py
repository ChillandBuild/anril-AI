import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File

from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_id, require_permission
from app.services.catalog_retrieval import embed_and_store_catalog_item, reindex_catalog_items

logger = logging.getLogger(__name__)
require_catalog_read = require_permission("catalog.view")
require_catalog_manage = require_permission("catalog.manage")

router = APIRouter(dependencies=[Depends(require_catalog_read)])

_VALID_STATUSES = {"draft", "ready"}
_AI_RULES_DEFAULTS = {"can_recommend": True, "can_send_images": True, "max_images_per_reply": 3}


@router.get("/items")
async def list_items(q: str | None = None, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    query = db.table("catalog_items").select("*").eq("tenant_id", tenant_id)
    if q:
        query = query.ilike("name", f"%{q}%")
    items = query.order("created_at", desc=True).execute().data or []
    if not items:
        return {"data": []}
    # held = units on unpaid payment links (services/deals.held_quantities);
    # thumbnail = first photo by sort order, so the Products list can show it.
    from app.services.deals import held_quantities
    ids = [i["id"] for i in items]
    held = held_quantities(tenant_id, [i["id"] for i in items if i.get("stock_quantity") is not None], db)
    wanted = set(ids)
    media = [
        m for m in (
            db.table("catalog_media").select("catalog_item_id, storage_path, sort_order")
            .eq("tenant_id", tenant_id).order("sort_order").limit(10000).execute()
        ).data or []
        if m["catalog_item_id"] in wanted
    ]
    first_photo: dict[str, str] = {}
    for m in media:
        first_photo.setdefault(m["catalog_item_id"], m["storage_path"])
    bucket = db.storage.from_("catalog-media")
    extra = _list_extras(db, tenant_id, wanted)
    return {
        "data": [
            {
                **{k: v for k, v in i.items() if k != "embedding"},
                "embedding": bool(i.get("embedding")),
                "held_quantity": held.get(i["id"], 0),
                "thumbnail_url": bucket.get_public_url(first_photo[i["id"]]) if i["id"] in first_photo else None,
                **extra.get(i["id"], _EMPTY_EXTRAS),
            }
            for i in items
        ]
    }


_EMPTY_EXTRAS = {"sizes": [], "colours": [], "out_variants": [], "low_variants": [], "sold_30d": 0, "waiting": 0}
_SOLD_DAYS = 30


def _list_extras(db, tenant_id: str, wanted: set[str]) -> dict[str, dict]:
    """Per item, for the Items list: sizes and colours, which of them are out or on their last
    pieces, units sold in the last 30 days, and people waiting for a "back in stock" message."""
    from datetime import timedelta
    out: dict[str, dict] = {}

    def entry(item_id: str) -> dict:
        return out.setdefault(item_id, {k: (list(v) if isinstance(v, list) else v) for k, v in _EMPTY_EXTRAS.items()})

    for v in (
        db.table("catalog_item_variants").select("catalog_item_id, size, colour, stock_quantity, sort_order")
        .eq("tenant_id", tenant_id).order("sort_order").limit(20000).execute()
    ).data or []:
        if v["catalog_item_id"] not in wanted:
            continue
        e = entry(v["catalog_item_id"])
        if v.get("size") and v["size"] not in e["sizes"]:
            e["sizes"].append(v["size"])
        if v.get("colour") and v["colour"] not in e["colours"]:
            e["colours"].append(v["colour"])
        label = " ".join(x for x in (v.get("colour"), v.get("size")) if x)
        stock = int(v.get("stock_quantity") or 0)
        if stock <= 0:
            e["out_variants"].append(label)
        elif stock == 1:
            e["low_variants"].append(label)
    since = (datetime.now(timezone.utc) - timedelta(days=_SOLD_DAYS)).isoformat()
    for m in (
        db.table("stock_movements").select("catalog_item_id, delta")
        .eq("tenant_id", tenant_id).eq("reason", "sale").gte("created_at", since).limit(50000).execute()
    ).data or []:
        if m["catalog_item_id"] in wanted:
            entry(m["catalog_item_id"])["sold_30d"] += -int(m.get("delta") or 0)
    for w in (
        db.table("stock_waitlist").select("catalog_item_id")
        .eq("tenant_id", tenant_id).is_("closed_at", "null").eq("wants_message", True).limit(20000).execute()
    ).data or []:
        if w["catalog_item_id"] in wanted:
            entry(w["catalog_item_id"])["waiting"] += 1
    return out


def _validate_gst_rate(value) -> None:
    if value is not None and not (0 <= float(value) <= 40):
        raise HTTPException(status_code=400, detail="gst_rate must be between 0 and 40")


def _clean_stock_fields(payload: dict) -> dict:
    """Cost price, HSN and the low-stock alert level from the Edit item form (only keys sent)."""
    out: dict = {}
    if "cost_price_paise" in payload:
        cost = payload["cost_price_paise"]
        if cost is not None:
            try:
                cost = int(cost)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Cost price must be a number")
            if cost < 0:
                raise HTTPException(status_code=400, detail="Cost price must not be negative")
        out["cost_price_paise"] = cost
    if "hsn_code" in payload:
        hsn = "".join(str(payload["hsn_code"] or "").split())
        if hsn and not (hsn.isdigit() and 4 <= len(hsn) <= 8):
            raise HTTPException(status_code=400, detail="HSN is 4 to 8 digits")
        out["hsn_code"] = hsn or None
    if "low_stock_at" in payload:
        level = payload["low_stock_at"]
        if level is not None:
            try:
                level = int(level)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="The alert level must be a whole number")
            if level < 0 or level > 100_000:
                raise HTTPException(status_code=400, detail="The alert level must be 0 or more")
        out["low_stock_at"] = level
    return out


def _log_initial_stock(db, tenant_id: str, item_id: str, quantity: int, user_id: str | None) -> None:
    """Opening stock (new item, or an item that starts being tracked; it is saved at 0 first) goes in
    through apply_stock_movement like every change, so it lands in the bill place (migration 304),
    the total stays the sum of the places, and the history explains the number."""
    if quantity and quantity > 0:
        from app.services.deals import adjust_stock
        adjust_stock(tenant_id, item_id, quantity, "restock", note="Opening stock", created_by=user_id, db=db)


@router.post("/items")
async def create_item(
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    price_paise = payload.get("price_paise")
    if price_paise is not None and price_paise < 0:
        raise HTTPException(status_code=400, detail="price_paise must not be negative")
    stock_quantity = payload.get("stock_quantity")
    if stock_quantity is not None and stock_quantity < 0:
        raise HTTPException(status_code=400, detail="stock_quantity must not be negative")
    _validate_gst_rate(payload.get("gst_rate"))
    res = db.table("catalog_items").insert({
        "tenant_id": tenant_id,
        "name": payload.get("name"),
        "item_type": payload.get("item_type") or "product",
        "description": payload.get("description"),
        "status": "draft",
        "attributes": payload.get("attributes") or {},
        "variant_group_id": payload.get("variant_group_id"),
        "price_paise": price_paise,
        "price_note": payload.get("price_note"),
        "stock_quantity": 0 if stock_quantity is not None else None,  # opening stock goes in below
        "gst_rate": payload.get("gst_rate"),
        **_clean_stock_fields(payload),
    }).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create catalog item")
    item = res.data[0]
    if stock_quantity:
        _log_initial_stock(db, tenant_id, item["id"], stock_quantity, _ctx.get("user_id"))
        item["stock_quantity"] = stock_quantity
    try:
        await embed_and_store_catalog_item(
            db, tenant_id, item["id"], item["name"], item["item_type"],
            item.get("description"), item.get("attributes") or {},
        )
    except Exception as e:
        logger.warning(f"Failed to embed catalog item {item['id']}: {e}")
    return item


@router.patch("/items/{item_id}")
async def update_item(
    item_id: UUID,
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    updates = {
        k: v for k, v in payload.items()
        if k in {"name", "item_type", "description", "status", "attributes", "variant_group_id", "price_paise", "price_note", "stock_quantity", "gst_rate"}
    }
    updates.update(_clean_stock_fields(payload))
    if "status" in updates and updates["status"] not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {_VALID_STATUSES}")
    if updates.get("price_paise") is not None and updates["price_paise"] < 0:
        raise HTTPException(status_code=400, detail="price_paise must not be negative")
    if updates.get("stock_quantity") is not None and updates["stock_quantity"] < 0:
        raise HTTPException(status_code=400, detail="stock_quantity must not be negative")
    _validate_gst_rate(updates.get("gst_rate"))
    stock_delta = None
    if "stock_quantity" in updates and _has_variants(db, tenant_id, str(item_id)):
        updates.pop("stock_quantity")  # the sizes and colours grid owns the number
    if "stock_quantity" in updates:
        current = (
            db.table("catalog_items").select("stock_quantity").eq("id", str(item_id)).eq("tenant_id", tenant_id)
            .maybe_single().execute()
        )
        if not current or not current.data:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        before, after = current.data.get("stock_quantity"), updates["stock_quantity"]
        if before is not None and after is not None:
            # Tracked -> tracked goes through the ledger as a correction, so
            # the history explains every change to the number.
            updates.pop("stock_quantity")
            stock_delta = after - before
        elif before is None and after:
            stock_delta = "opening"
            updates["stock_quantity"] = 0  # tracked from now; the opening stock goes in below
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    res = (
        db.table("catalog_items")
        .update(updates)
        .eq("id", str(item_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    item = res.data[0]
    if stock_delta == "opening":
        _log_initial_stock(db, tenant_id, item["id"], after, _ctx.get("user_id"))
        item["stock_quantity"] = after
    elif stock_delta:
        from app.services.deals import adjust_stock
        moved = adjust_stock(tenant_id, item["id"], stock_delta, "adjustment",
                             note="Corrected in product form", created_by=_ctx.get("user_id"), db=db)
        if not moved["ok"]:
            raise HTTPException(status_code=409, detail="Stock changed meanwhile — reload and try again")
        item["stock_quantity"] = moved["quantity_after"]
    if {"name", "item_type", "description", "attributes"} & updates.keys():
        try:
            await embed_and_store_catalog_item(
                db, tenant_id, item["id"], item["name"], item["item_type"],
                item.get("description"), item.get("attributes") or {},
            )
        except Exception as e:
            logger.warning(f"Failed to re-embed catalog item {item['id']}: {e}")
    return item


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    res = (
        db.table("catalog_items")
        .delete()
        .eq("id", str(item_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    from app.services.meta_catalog import delete_from_meta
    await delete_from_meta(tenant_id, res.data[0].get("meta_retailer_ids") or [])
    return {"success": True}


@router.post("/items/{item_id}/media")
async def upload_item_media(
    item_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    file: UploadFile = File(...),
    label: str | None = Form(None),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    item_res = (
        db.table("catalog_items")
        .select("id")
        .eq("id", str(item_id))
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not item_res.data:
        raise HTTPException(status_code=404, detail="Catalog item not found")

    existing_res = (
        db.table("catalog_media")
        .select("sort_order")
        .eq("catalog_item_id", str(item_id))
        .eq("tenant_id", tenant_id)
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    )
    next_sort_order = (existing_res.data[0]["sort_order"] + 1) if existing_res.data else 0

    content = await file.read()
    storage_path = f"{tenant_id}/{item_id}/{uuid4()}_{file.filename}"
    db.storage.from_("catalog-media").upload(
        storage_path, content, {"content-type": file.content_type or "application/octet-stream"}
    )
    url = db.storage.from_("catalog-media").get_public_url(storage_path)

    res = db.table("catalog_media").insert({
        "tenant_id": tenant_id,
        "catalog_item_id": str(item_id),
        "storage_path": storage_path,
        # No filename fallback -- a raw upload filename ("IMG_2026.png") makes a
        # useless WhatsApp caption. ai_reply.py falls back to the item's own name
        # when label is empty, and the dashboard prompts the operator to name it.
        "label": (label or "").strip() or None,
        "sort_order": next_sort_order,
    }).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to save catalog media record")

    return {**res.data[0], "url": url}


@router.patch("/media/{media_id}")
async def update_media(
    media_id: UUID,
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    updates: dict = {}
    if "label" in payload:
        updates["label"] = (payload.get("label") or "").strip() or None
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    res = (
        db.table("catalog_media")
        .update(updates)
        .eq("id", str(media_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Catalog media not found")
    return res.data[0]


@router.patch("/items/{item_id}/media/reorder")
async def reorder_item_media(
    item_id: UUID,
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    media_ids = payload.get("media_ids")
    if not isinstance(media_ids, list) or not media_ids:
        raise HTTPException(status_code=400, detail="media_ids must be a non-empty list")

    db = get_supabase()
    owned_res = (
        db.table("catalog_media")
        .select("id")
        .eq("catalog_item_id", str(item_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    owned_ids = {row["id"] for row in (owned_res.data or [])}
    if not owned_ids.issuperset(set(media_ids)):
        raise HTTPException(status_code=400, detail="media_ids must all belong to this item")

    for index, media_id in enumerate(media_ids):
        db.table("catalog_media").update({"sort_order": index}).eq("id", media_id).eq("tenant_id", tenant_id).execute()

    return {"success": True}


@router.get("/media")
async def list_media(tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    media_res = (
        db.table("catalog_media")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("catalog_item_id")
        .order("sort_order")
        .execute()
    )
    media_rows = media_res.data or []
    if not media_rows:
        return {"data": []}

    item_ids = list({row["catalog_item_id"] for row in media_rows})
    items_res = (
        db.table("catalog_items")
        .select("id,name")
        .in_("id", item_ids)
        .execute()
    )
    item_names = {row["id"]: row["name"] for row in (items_res.data or [])}

    data = [
        {
            **row,
            "item_name": item_names.get(row["catalog_item_id"]),
            "url": db.storage.from_("catalog-media").get_public_url(row["storage_path"]),
        }
        for row in media_rows
    ]
    return {"data": data}


@router.delete("/media/{media_id}")
async def delete_media(
    media_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    media_res = (
        db.table("catalog_media")
        .select("storage_path")
        .eq("id", str(media_id))
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not media_res.data:
        raise HTTPException(status_code=404, detail="Catalog media not found")

    storage_path = media_res.data[0]["storage_path"]
    db.table("catalog_media").delete().eq("id", str(media_id)).eq("tenant_id", tenant_id).execute()
    try:
        db.storage.from_("catalog-media").remove([storage_path])
    except Exception as e:
        logger.warning(f"Failed to remove catalog media object {storage_path}: {e}")

    return {"success": True}


def _catalog_ai_rules_stored(db, tenant_id: str) -> dict:
    """The client's own catalog_ai_rules preferences, merged with defaults -- no operator
    overlay. Operator controls (feature_enabled, max_images_ceiling) are surfaced
    separately so they never get written back into the client's stored blob."""
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "catalog_ai_rules")
        .limit(1)
        .execute()
    )
    stored = {}
    if row.data:
        try:
            stored = json.loads(row.data[0]["value"])
        except (ValueError, TypeError):
            stored = {}
    return {**_AI_RULES_DEFAULTS, **stored}


def _operator_media_recommendation_controls(tenant_id: str) -> tuple[bool, int]:
    """(feature_enabled, max_images_ceiling) as set by the operator console. The client
    can choose anything under the ceiling but never above it -- see decisions/log.md."""
    enabled = get_setting("ai_media_recommendations_enabled", fallback="true", tenant_id=tenant_id) == "true"
    ceiling_raw = get_setting("catalog_ai_max_images_ceiling", fallback="5", tenant_id=tenant_id) or "5"
    try:
        ceiling = max(0, int(float(ceiling_raw)))
    except (TypeError, ValueError):
        ceiling = 5
    return enabled, ceiling


@router.get("/ai-rules")
async def get_ai_rules(tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    rules = _catalog_ai_rules_stored(db, tenant_id)
    feature_enabled, ceiling = _operator_media_recommendation_controls(tenant_id)
    return {**rules, "feature_enabled": feature_enabled, "max_images_ceiling": ceiling}


@router.patch("/ai-rules")
async def update_ai_rules(
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    current = _catalog_ai_rules_stored(db, tenant_id)
    updates = {k: v for k, v in payload.items() if k in _AI_RULES_DEFAULTS}

    feature_enabled, ceiling = _operator_media_recommendation_controls(tenant_id)
    if "max_images_per_reply" in updates:
        try:
            requested = int(updates["max_images_per_reply"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_images_per_reply must be a whole number")
        if requested < 0:
            raise HTTPException(status_code=400, detail="max_images_per_reply cannot be negative")
        if requested > ceiling:
            raise HTTPException(status_code=400, detail=f"max_images_per_reply cannot exceed {ceiling}, the limit set for your account")

    merged = {**current, **updates}

    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": "catalog_ai_rules",
        "value": json.dumps(merged),
        "is_secret": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="tenant_id,key").execute()

    return {**merged, "feature_enabled": feature_enabled, "max_images_ceiling": ceiling}


@router.post("/variant-groups")
async def create_variant_group(
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    db = get_supabase()
    res = db.table("catalog_variant_groups").insert({
        "tenant_id": tenant_id,
        "name": payload.get("name"),
        "item_type": payload.get("item_type") or "product",
    }).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create variant group")
    return res.data[0]


@router.get("/variant-groups")
async def list_variant_groups(tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    res = (
        db.table("catalog_variant_groups")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"data": res.data or []}


@router.post("/reindex")
async def reindex_catalog(
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    """Backfill embeddings for existing catalog items (run once after grouping variants)."""
    result = await reindex_catalog_items(tenant_id)
    return {"success": True, **result}


@router.post("/items/{item_id}/stock")
async def change_stock(
    item_id: UUID,
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    ctx: dict = Depends(require_catalog_manage),
):
    """Restock / correct / return. An untracked item (NULL stock) starts being
    tracked on its first restock."""
    reason = payload.get("reason")
    if reason not in {"restock", "adjustment", "return"}:
        raise HTTPException(status_code=400, detail="reason must be restock, adjustment or return")
    try:
        delta = int(payload.get("delta"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="delta must be a whole number")
    if delta == 0:
        raise HTTPException(status_code=400, detail="delta must not be zero")
    note = (payload.get("note") or "").strip()[:300] or None
    db = get_supabase()
    item = (
        db.table("catalog_items").select("stock_quantity").eq("id", str(item_id)).eq("tenant_id", tenant_id)
        .maybe_single().execute()
    )
    if not item or not item.data:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    if _has_variants(db, tenant_id, str(item_id)):
        raise HTTPException(status_code=400, detail="This item has sizes and colours: change the stock in its grid")
    if item.data.get("stock_quantity") is None:
        if delta < 0:
            raise HTTPException(status_code=400, detail="This item doesn't track stock yet — restock it first")
        db.table("catalog_items").update({"stock_quantity": 0}).eq("id", str(item_id)).eq("tenant_id", tenant_id).execute()
    from app.services.deals import adjust_stock
    result = adjust_stock(tenant_id, str(item_id), delta, reason, note=note, created_by=ctx.get("user_id"), db=db)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail="Stock can't go below zero")
    return result


@router.get("/items/{item_id}/stock-movements")
async def stock_movements(item_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    rows = (
        db.table("stock_movements")
        .select("id, catalog_item_id, delta, quantity_after, reason, deal_id, note, created_at")
        .eq("tenant_id", tenant_id)
        .eq("catalog_item_id", str(item_id))
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    ).data or []
    return {"data": rows}


# ── Sizes x colours (migration 294) ──────────────────────────────────────────────
# Each size/colour has its own stock; the item's stock_quantity is their sum, so the AI
# and every older screen keep reading one number. Changes go through
# apply_variant_stock_movement, so the stock history explains every number.

_MAX_OPTIONS = 20


def _has_variants(db, tenant_id: str, item_id: str) -> bool:
    return bool((
        db.table("catalog_item_variants").select("id").eq("tenant_id", tenant_id)
        .eq("catalog_item_id", item_id).limit(1).execute()
    ).data)


def _clean_options(values) -> list[str]:
    out: list[str] = []
    for v in values or []:
        text = " ".join(str(v or "").split())[:30]
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    if len(out) > _MAX_OPTIONS:
        raise HTTPException(status_code=400, detail=f"At most {_MAX_OPTIONS} sizes and {_MAX_OPTIONS} colours")
    return out


def _variant_key(size, colour) -> tuple[str, str]:
    return ((size or "").lower(), (colour or "").lower())


@router.get("/items/{item_id}/variants")
async def list_variants(item_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    rows = (
        db.table("catalog_item_variants").select("id, size, colour, stock_quantity, price_paise, sort_order")
        .eq("tenant_id", tenant_id).eq("catalog_item_id", str(item_id)).order("sort_order").execute()
    ).data or []
    sizes = _clean_options([r.get("size") for r in rows if r.get("size")])
    colours = _clean_options([r.get("colour") for r in rows if r.get("colour")])
    return {"sizes": sizes, "colours": colours, "variants": rows}


@router.put("/items/{item_id}/variants")
async def save_variants(
    item_id: UUID,
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    ctx: dict = Depends(require_catalog_manage),
):
    """Replace the item's sizes and colours. payload: sizes [..], colours [..],
    cells [{size, colour, stock, price_paise?}]. A size/colour removed from the grid has its
    stock taken out (logged) and goes away; empty lists turn sizes and colours off."""
    from app.services.deals import adjust_variant_stock
    db = get_supabase()
    item = (
        db.table("catalog_items").select("id, stock_quantity").eq("id", str(item_id)).eq("tenant_id", tenant_id)
        .maybe_single().execute()
    )
    if not item or not item.data:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    sizes = _clean_options(payload.get("sizes"))
    colours = _clean_options(payload.get("colours"))
    wanted: dict[tuple[str, str], dict] = {}
    combos = [(s_, c_) for c_ in (colours or [None]) for s_ in (sizes or [None]) if s_ or c_]
    cells = {_variant_key(c.get("size"), c.get("colour")): c for c in payload.get("cells") or [] if isinstance(c, dict)}
    for order, (size, colour) in enumerate(combos):
        cell = cells.get(_variant_key(size, colour), {})
        try:
            stock = int(cell.get("stock") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Stock must be a whole number")
        if stock < 0 or stock > 1_000_000:
            raise HTTPException(status_code=400, detail="Stock must be 0 or more")
        price = cell.get("price_paise")
        if price is not None:
            try:
                price = int(price)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Price must be a number")
            if price < 0:
                raise HTTPException(status_code=400, detail="Price must not be negative")
        wanted[_variant_key(size, colour)] = {"size": size, "colour": colour, "stock": stock, "price_paise": price,
                                              "sort_order": order}

    existing = (
        db.table("catalog_item_variants").select("id, size, colour, stock_quantity")
        .eq("tenant_id", tenant_id).eq("catalog_item_id", str(item_id)).execute()
    ).data or []
    by_key = {_variant_key(r.get("size"), r.get("colour")): r for r in existing}
    user_id = ctx.get("user_id")
    if not existing and wanted and item.data.get("stock_quantity"):
        # The single number is replaced by the grid: it goes out (logged), the grid comes in below.
        from app.services.deals import adjust_stock
        adjust_stock(tenant_id, str(item_id), -int(item.data["stock_quantity"]), "adjustment",
                     note="Moved into sizes and colours", created_by=user_id, db=db)
    for key, row in by_key.items():
        if key in wanted:
            continue
        if int(row.get("stock_quantity") or 0) > 0:
            adjust_variant_stock(tenant_id, row["id"], -int(row["stock_quantity"]), "adjustment",
                                 note="Size or colour removed", created_by=user_id, db=db)
        db.table("catalog_item_variants").delete().eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
    for key, cell in wanted.items():
        row = by_key.get(key)
        if not row:
            created = db.table("catalog_item_variants").insert({
                "tenant_id": tenant_id, "catalog_item_id": str(item_id), "size": cell["size"], "colour": cell["colour"],
                "stock_quantity": 0, "price_paise": cell["price_paise"], "sort_order": cell["sort_order"],
            }).execute().data or []
            row = {**(created[0] if created else {}), "stock_quantity": 0}
        else:
            db.table("catalog_item_variants").update({
                "price_paise": cell["price_paise"], "sort_order": cell["sort_order"],
            }).eq("id", row["id"]).eq("tenant_id", tenant_id).execute()
        delta = cell["stock"] - int(row.get("stock_quantity") or 0)
        if delta and row.get("id"):
            result = adjust_variant_stock(tenant_id, row["id"], delta, "restock" if delta > 0 else "adjustment",
                                          note="Sizes and colours grid", created_by=user_id, db=db)
            if not result["ok"]:
                raise HTTPException(status_code=409, detail="Stock changed while you were editing. Reload and try again.")
    if wanted and item.data.get("stock_quantity") is None:
        # An untracked item starts being tracked with its grid (whose stock went in above).
        total = sum(c["stock"] for c in wanted.values())
        db.table("catalog_items").update({"stock_quantity": total}).eq("id", str(item_id)) \
            .eq("tenant_id", tenant_id).is_("stock_quantity", "null").execute()
    return await list_variants(item_id, tenant_id=tenant_id)


# ── The item page (Catalogue redesign, migration 300) ───────────────────────────

_STOCK_WHY = {"stock_in": "New stock came", "found": "Found in shop", "damaged": "Damaged", "lost": "Lost",
              "supplier_return": "Returned to supplier", "count_wrong": "Count was wrong"}


@router.get("/items/{item_id}")
async def item_detail(item_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    """One item for its page: the item, sizes x colours, photos, sold this month, people waiting."""
    from app.services.deals import held_quantities
    from app.services.meta_catalog import item_link
    db = get_supabase()
    rows = (
        db.table("catalog_items").select("*").eq("id", str(item_id)).eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    item = {k: v for k, v in rows[0].items() if k != "embedding"}
    item["embedding"] = bool(rows[0].get("embedding"))
    bucket = db.storage.from_("catalog-media")
    photos = [
        {"id": m["id"], "url": bucket.get_public_url(m["storage_path"]), "label": m.get("label")}
        for m in (
            db.table("catalog_media").select("id, storage_path, label, sort_order").eq("tenant_id", tenant_id)
            .eq("catalog_item_id", str(item_id)).order("sort_order").execute()
        ).data or []
    ]
    month_start = _month_start_ist()
    sold = sum(
        -int(m.get("delta") or 0) for m in (
            db.table("stock_movements").select("delta").eq("tenant_id", tenant_id).eq("catalog_item_id", str(item_id))
            .eq("reason", "sale").gte("created_at", month_start).limit(10000).execute()
        ).data or []
    )
    waiting = len((
        db.table("stock_waitlist").select("id").eq("tenant_id", tenant_id).eq("catalog_item_id", str(item_id))
        .is_("closed_at", "null").eq("wants_message", True).limit(10000).execute()
    ).data or [])
    group = None
    if item.get("variant_group_id"):
        g = (db.table("catalog_variant_groups").select("id, name").eq("id", item["variant_group_id"])
             .eq("tenant_id", tenant_id).limit(1).execute()).data or []
        group = g[0]["name"] if g else None
    held = held_quantities(tenant_id, [item["id"]], db).get(item["id"], 0) if item.get("stock_quantity") is not None else 0
    return {
        **item,
        "held_quantity": held,
        "group_name": group,
        "photos": photos,
        "sold_this_month": sold,
        "waiting": waiting,
        "public_url": item_link(item["id"]),
        **(await list_variants(item_id, tenant_id=tenant_id)),
    }


def _month_start_ist() -> str:
    from datetime import timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


@router.post("/items/{item_id}/correct-stock")
async def correct_stock(
    item_id: UUID,
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    ctx: dict = Depends(require_catalog_manage),
):
    """Correct one size/colour (variant_id) or the item's single number, with the reason saved
    in the stock history. payload: variant_id?, to (the right number), why (a _STOCK_WHY key)."""
    from app.services.deals import adjust_stock, adjust_variant_stock
    why = payload.get("why")
    if why not in _STOCK_WHY:
        raise HTTPException(status_code=400, detail="Pick why the stock changed")
    try:
        target = int(payload.get("to"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Type the right stock")
    if target < 0 or target > 1_000_000:
        raise HTTPException(status_code=400, detail="Stock must be 0 or more")
    db = get_supabase()
    note = _STOCK_WHY[why]
    reason = "restock" if why == "stock_in" else "adjustment"
    variant_id = payload.get("variant_id")
    if variant_id:
        rows = (
            db.table("catalog_item_variants").select("id, stock_quantity").eq("id", str(variant_id))
            .eq("catalog_item_id", str(item_id)).eq("tenant_id", tenant_id).limit(1).execute()
        ).data or []
        if not rows:
            raise HTTPException(status_code=404, detail="That size or colour isn't on this item")
        delta = target - int(rows[0].get("stock_quantity") or 0)
        if delta:
            result = adjust_variant_stock(tenant_id, str(variant_id), delta, reason, note=note,
                                          created_by=ctx.get("user_id"), db=db)
            if not result["ok"]:
                raise HTTPException(status_code=409, detail="Stock changed meanwhile. Reload and try again.")
        return await item_detail(item_id, tenant_id=tenant_id)
    if _has_variants(db, tenant_id, str(item_id)):
        raise HTTPException(status_code=400, detail="Pick the size or colour to correct")
    rows = (
        db.table("catalog_items").select("stock_quantity").eq("id", str(item_id)).eq("tenant_id", tenant_id)
        .limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    current = rows[0].get("stock_quantity")
    if current is None:
        db.table("catalog_items").update({"stock_quantity": 0}).eq("id", str(item_id)).eq("tenant_id", tenant_id).execute()
        current = 0
    delta = target - int(current)
    if delta:
        result = adjust_stock(tenant_id, str(item_id), delta, reason, note=note,
                              created_by=ctx.get("user_id"), db=db)
        if not result["ok"]:
            raise HTTPException(status_code=409, detail="Stock changed meanwhile. Reload and try again.")
    return await item_detail(item_id, tenant_id=tenant_id)


# ── The shop's Meta catalogue (services/meta_catalog.py) ────────────────────────

@router.get("/meta")
async def meta_catalogue_status(tenant_id: str = Depends(get_tenant_id)):
    from app.services import meta_catalog
    return meta_catalog.status(get_supabase(), tenant_id)


@router.post("/meta")
async def meta_catalogue_action(
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    """action: "on" (show the catalogue on WhatsApp: send everything), "off" (stop sending),
    "again" (send every item again now)."""
    from app.services import meta_catalog
    action = payload.get("action")
    if action not in ("on", "off", "again"):
        raise HTTPException(status_code=400, detail="action must be on, off or again")
    db = get_supabase()
    if action != "off" and not meta_catalog.linked_catalog(tenant_id):
        raise HTTPException(status_code=400, detail="Connect your Meta catalogue first")
    if action == "again":
        meta_catalog.resend_all(db, tenant_id)
    else:
        meta_catalog.set_sync(db, tenant_id, action == "on")
    if action != "off":
        await meta_catalog.push_tenant(db, tenant_id)
    return meta_catalog.status(db, tenant_id)


# ── The public item page Meta links to (no sign-in) ─────────────────────────────

public_router = APIRouter()


@public_router.get("/{item_id}")
async def public_item(item_id: UUID):
    """Name, price, photos and what's in stock for a Ready product, plus the shop's WhatsApp
    to order on. Drafts and unknown ids are 404, so nothing unpublished shows."""
    from app.routes.inbound_leads import _primary_whatsapp_number
    from app.services.business_details import get_business_details
    db = get_supabase()
    rows = (
        db.table("catalog_items").select("id, tenant_id, name, description, price_paise, price_note, stock_quantity")
        .eq("id", str(item_id)).eq("status", "ready").limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    item = rows[0]
    tenant_id = item["tenant_id"]
    bucket = db.storage.from_("catalog-media")
    photos = [
        bucket.get_public_url(m["storage_path"]) for m in (
            db.table("catalog_media").select("storage_path, sort_order").eq("tenant_id", tenant_id)
            .eq("catalog_item_id", item["id"]).order("sort_order").limit(10).execute()
        ).data or []
    ]
    variants = (
        db.table("catalog_item_variants").select("size, colour, stock_quantity, price_paise, sort_order")
        .eq("tenant_id", tenant_id).eq("catalog_item_id", item["id"]).order("sort_order").execute()
    ).data or []
    business = get_business_details(tenant_id, db)
    number = "".join(ch for ch in str(_primary_whatsapp_number(db, tenant_id) or "") if ch.isdigit())
    return {
        "name": item["name"],
        "description": item.get("description"),
        "price_paise": item.get("price_paise"),
        "price_note": item.get("price_note"),
        "in_stock": item.get("stock_quantity") is None or int(item["stock_quantity"]) > 0,
        "photos": photos,
        "options": [
            {"size": v.get("size"), "colour": v.get("colour"), "in_stock": int(v.get("stock_quantity") or 0) > 0,
             "price_paise": v.get("price_paise") if v.get("price_paise") is not None else item.get("price_paise")}
            for v in variants
        ],
        "shop": {"name": business.get("legal_name") or "", "city": business.get("city") or ""},
        "whatsapp": number or None,
    }


# ── Asked but out of stock (migration 305, services/stock_asks.py) ─────────────


def _stock_asks_view(db, tenant_id: str, days: int) -> dict:
    from app.services import stock_asks

    data = stock_asks.summary(db, tenant_id, days=days)
    return {**data, "message": stock_asks.message_settings(db, tenant_id),
            "starting_bodies": stock_asks.STARTING_BODY,
            "template_status": stock_asks.template_status(db, tenant_id)}


@router.get("/stock-asks")
async def stock_asks_list(days: int = 30, tenant_id: str = Depends(get_tenant_id)):
    import asyncio

    days = min(max(int(days), 1), 365)
    return await asyncio.to_thread(_stock_asks_view, get_supabase(), tenant_id, days)


@router.get("/stock-asks.csv")
async def stock_asks_csv(days: int = 30, tenant_id: str = Depends(get_tenant_id)):
    import asyncio
    import csv
    import io

    from fastapi.responses import Response

    from app.services import stock_asks

    data = await asyncio.to_thread(stock_asks.summary, get_supabase(), tenant_id, days=min(max(int(days), 1), 365))
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in stock_asks.csv_rows(data):
        writer.writerow(["'" + c if c[:1] in ("=", "+", "-", "@", "\t", "\r") else c for c in row])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="asked-but-out-of-stock.csv"'})


@router.post("/stock-asks/back-in-stock")
async def stock_asks_back_in_stock(
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    ctx: dict = Depends(require_catalog_manage),
):
    """Message everyone waiting for this item / size that it is back (team-triggered)."""
    from app.services import stock_asks

    item_id = str(payload.get("catalog_item_id") or "")
    variant_id = payload.get("variant_id") or None
    try:
        UUID(item_id)
        if variant_id:
            UUID(str(variant_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Pick an item")
    try:
        result = await stock_asks.mark_back(get_supabase(), tenant_id, item_id=item_id,
                                            variant_id=str(variant_id) if variant_id else None,
                                            user_id=ctx.get("user_id"))
    except stock_asks.StockAskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.put("/stock-asks/message")
async def stock_asks_message(
    payload: dict,
    tenant_id: str = Depends(get_tenant_id),
    _ctx: dict = Depends(require_catalog_manage),
):
    from app.services import stock_asks

    try:
        return stock_asks.save_message_settings(get_supabase(), tenant_id, str(payload.get("language") or ""),
                                                payload.get("body"))
    except stock_asks.StockAskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stock-asks/message/submit")
async def stock_asks_submit_template(ctx: dict = Depends(require_permission("templates.manage"))):
    """Send the saved back-in-stock message to Meta for approval as anril_back_in_stock, through
    the Templates page's own path (it shows and updates there like any template)."""
    from app.routes.templates import CreateTemplate, create_template
    from app.services import stock_asks

    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    status = stock_asks.template_status(db, tenant_id)
    if status in ("PENDING", "APPROVED"):
        raise HTTPException(status_code=400, detail="It's already with WhatsApp." if status == "PENDING"
                            else "It's already approved.")
    settings = stock_asks.message_settings(db, tenant_id)
    problems = stock_asks.body_problems(settings["body"])
    if problems:
        raise HTTPException(status_code=400, detail=problems[0])
    await create_template(
        CreateTemplate(name=stock_asks.TEMPLATE_NAME, category="MARKETING",
                       language=stock_asks.META_LANGUAGE[settings["language"]], body_text=settings["body"],
                       body_examples=stock_asks.EXAMPLES),
        tenant_id=tenant_id, _ctx=ctx,
    )
    return {"template_status": stock_asks.template_status(db, tenant_id)}
