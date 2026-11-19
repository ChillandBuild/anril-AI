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
    return {
        "data": [
            {
                **i,
                "held_quantity": held.get(i["id"], 0),
                "thumbnail_url": bucket.get_public_url(first_photo[i["id"]]) if i["id"] in first_photo else None,
            }
            for i in items
        ]
    }


def _validate_gst_rate(value) -> None:
    if value is not None and not (0 <= float(value) <= 40):
        raise HTTPException(status_code=400, detail="gst_rate must be between 0 and 40")


def _log_initial_stock(db, tenant_id: str, item_id: str, quantity: int, user_id: str | None) -> None:
    """Stock set directly (new item, or an item that starts being tracked) gets
    a matching 'restock' row, so the history always explains the number."""
    if quantity > 0:
        db.table("stock_movements").insert({
            "tenant_id": tenant_id, "catalog_item_id": item_id, "delta": quantity,
            "quantity_after": quantity, "reason": "restock", "note": "Opening stock", "created_by": user_id,
        }).execute()


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
        "stock_quantity": stock_quantity,
        "gst_rate": payload.get("gst_rate"),
    }).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create catalog item")
    item = res.data[0]
    if stock_quantity:
        _log_initial_stock(db, tenant_id, item["id"], stock_quantity, _ctx.get("user_id"))
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
        _log_initial_stock(db, tenant_id, item["id"], item["stock_quantity"], _ctx.get("user_id"))
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
        # The single number is replaced by the grid: log it going out, the grid comes in below.
        db.table("stock_movements").insert({
            "tenant_id": tenant_id, "catalog_item_id": str(item_id), "delta": -int(item.data["stock_quantity"]),
            "quantity_after": 0, "reason": "adjustment", "note": "Moved into sizes and colours", "created_by": user_id,
        }).execute()
        db.table("catalog_items").update({"stock_quantity": 0}).eq("id", str(item_id)).eq("tenant_id", tenant_id).execute()
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
    total = sum(c["stock"] for c in wanted.values())
    if wanted:
        db.table("catalog_items").update({"stock_quantity": total}).eq("id", str(item_id)).eq("tenant_id", tenant_id).execute()
    return await list_variants(item_id, tenant_id=tenant_id)
