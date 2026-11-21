"""Upload price list (plan: docs/plans/commerce-stock-plan.md, part 3).

Read an Excel / CSV sheet directly, or a PDF / photo of a printed price list with the AI; compare
every row with the Catalogue (New / Update / Same, per size and colour); nothing changes until the
business presses Save, and Save checks every row again. Stock goes through the stock functions
(apply_stock_movement / apply_variant_stock_movement), so the history explains every number."""
from __future__ import annotations

import csv
import io
import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_ROWS = 2000
GST_RATES = (0, 0.25, 3, 5, 12, 18, 28, 40)
SAMPLE = [
    ["Item name", "Size", "Colour", "Price", "GST %", "HSN", "Stock", "Group"],
    ["Kanchi pattu", "M", "Red", "10500", "5", "5007", "4", "Sarees"],
    ["Kanchi pattu", "L", "Red", "10500", "5", "5007", "2", "Sarees"],
    ["Blouse stitching", "", "", "1600", "5", "998821", "", "Services"],
]
# Column name -> field. Matched on the lower-cased header, first hit wins.
_HEADERS = [
    ("name", ("item name", "product name", "item", "product", "name", "description of goods", "particulars")),
    ("size", ("size",)),
    ("colour", ("colour", "color", "shade")),
    ("price", ("selling price", "price", "mrp", "rate", "amount")),
    ("gst_rate", ("gst", "tax")),
    ("hsn", ("hsn", "sac")),
    ("stock", ("stock", "qty", "quantity", "in stock")),
    ("group", ("group", "category", "type")),
]
AI_INSTRUCTION = (
    "This is a shop's price list. Read every product line and answer with JSON only, no prose:\n"
    '{"rows": [{"name": str, "size": str|null, "colour": str|null, "price": number|null, '
    '"gst_rate": number|null, "hsn": str|null, "stock": int|null, "group": str|null}]}\n'
    "price is the selling price of ONE piece in rupees. One row per size/colour when the list gives them separately. "
    "Copy names as printed. Skip headings, totals and notes."
)


class PriceListError(ValueError):
    """Something the user can fix; routes turn it into a 400."""


def _text(value, limit: int) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


# ── reading ───────────────────────────────────────────────────────────────────


def _rows_from_table(table: list[list]) -> list[dict]:
    table = [r for r in table if any(str(c or "").strip() for c in r)]
    if not table:
        raise PriceListError("The sheet is empty.")
    header = [_norm(c) for c in table[0]]
    columns: dict[str, int] = {}
    for field, names in _HEADERS:
        for name in names:
            idx = next((i for i, h in enumerate(header) if h == name or h.startswith(name + " ") or h.endswith(" " + name)), None)
            if idx is not None and idx not in columns.values():
                columns[field] = idx
                break
    if "name" not in columns:
        raise PriceListError("Add a heading row with at least “Item name” and “Price”. Download the sample sheet to see how.")
    out = []
    for row in table[1:MAX_ROWS + 1]:
        def cell(field):
            i = columns.get(field)
            return row[i] if i is not None and i < len(row) else None
        out.append({f: cell(f) for f, _ in _HEADERS})
    if len(table) - 1 > MAX_ROWS:
        raise PriceListError(f"Up to {MAX_ROWS} rows at a time. Split the sheet.")
    return out


def read_sheet(content: bytes, filename: str) -> list[dict]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or content[:2] == b"PK":
        from openpyxl import load_workbook

        try:
            book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:
            raise PriceListError("Couldn't open the Excel file. Save it as .xlsx or CSV and try again.")
        sheet = book.worksheets[0]
        return _rows_from_table([list(r) for r in sheet.iter_rows(values_only=True, max_row=MAX_ROWS + 50)])
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    return _rows_from_table(list(csv.reader(io.StringIO(text))))


async def read_with_ai(db, tenant_id: str, content: bytes, mime: str) -> list[dict]:
    from app.services.gemini_client import gemini_read_file

    try:
        answer = await gemini_read_file(content, mime, AI_INSTRUCTION, tenant_id=tenant_id, purpose="price_list",
                                        max_tokens=16000)
    except Exception as exc:
        logger.warning("Price list read failed for tenant %s: %s", tenant_id, exc)
        raise PriceListError("Couldn't read the price list. Try a clearer photo, or use the Excel sample sheet.")
    match = re.search(r"\{.*\}", answer or "", re.S)
    try:
        rows = json.loads(match.group(0)).get("rows") if match else None
    except ValueError:
        rows = None
    if not isinstance(rows, list) or not rows:
        raise PriceListError("Couldn't find any items in it. Try a clearer photo, or use the Excel sample sheet.")
    return [r for r in rows if isinstance(r, dict)][:MAX_ROWS]


# ── checking a row ────────────────────────────────────────────────────────────


def clean_row(raw: dict) -> tuple[dict, list[str]]:
    """One row as the Catalogue stores it, plus what is wrong with it (plain words)."""
    problems: list[str] = []
    name = _text(raw.get("name"), 120)
    if not name:
        problems.append("No item name")
    price = None
    price_text = str(raw.get("price") if raw.get("price") is not None else "").replace(",", "").replace("₹", "").strip()
    if price_text:
        try:
            price = int(round(float(price_text) * 100))
            if price < 0:
                raise ValueError
        except ValueError:
            problems.append("Price isn't a number")
    gst = None
    gst_text = str(raw.get("gst_rate") if raw.get("gst_rate") is not None else "").replace("%", "").strip()
    if gst_text:
        try:
            gst = float(gst_text)
            if gst not in GST_RATES:
                raise ValueError
            gst = int(gst) if gst == int(gst) else gst
        except ValueError:
            problems.append("GST is 0, 0.25, 3, 5, 12, 18, 28 or 40")
    hsn = re.sub(r"\D", "", str(raw.get("hsn") or "").split(".")[0])
    if hsn and not 4 <= len(hsn) <= 8:
        problems.append("HSN is 4 to 8 digits")
    stock = None
    stock_text = str(raw.get("stock") if raw.get("stock") is not None else "").strip()
    if stock_text:
        try:
            stock = int(float(stock_text))
            if stock < 0 or stock > 1_000_000:
                raise ValueError
        except ValueError:
            problems.append("Stock must be 0 or more")
    return {
        "name": name, "size": _text(raw.get("size"), 30) or None, "colour": _text(raw.get("colour"), 30) or None,
        "price_paise": price, "gst_rate": gst, "hsn": hsn or None, "stock": stock, "group": _text(raw.get("group"), 60) or None,
    }, problems


def _catalog(db, tenant_id: str) -> tuple[dict, dict]:
    items = (db.table("catalog_items").select("id, name, price_paise, gst_rate, hsn_code, stock_quantity, attributes")
             .eq("tenant_id", tenant_id).limit(10000).execute().data or [])
    variants = (db.table("catalog_item_variants").select("id, catalog_item_id, size, colour, price_paise, stock_quantity")
                .eq("tenant_id", tenant_id).limit(50000).execute().data or [])
    by_name = {}
    for item in items:
        by_name.setdefault(_norm(item["name"]), item)
    by_item: dict[str, list[dict]] = {}
    for v in variants:
        by_item.setdefault(v["catalog_item_id"], []).append(v)
    return by_name, by_item


def preview(db, tenant_id: str, raw_rows: list[dict]) -> dict:
    """Each row: what it is (new item / new size / update / same), the changes, and problems."""
    by_name, by_item = _catalog(db, tenant_id)
    rows, seen = [], set()
    for n, raw in enumerate(raw_rows, 1):
        row, problems = clean_row(raw)
        if not row["name"] and not any(row[k] for k in ("price_paise", "size", "colour", "stock")):
            continue  # a blank line
        key = (_norm(row["name"]), _norm(row["size"]), _norm(row["colour"]))
        if key in seen:
            problems.append("Same item and size twice in the list")
        seen.add(key)
        item = by_name.get(_norm(row["name"]))
        variants = by_item.get(item["id"], []) if item else []
        has_size = bool(row["size"] or row["colour"])
        variant = next((v for v in variants if _norm(v.get("size")) == _norm(row["size"])
                        and _norm(v.get("colour")) == _norm(row["colour"])), None) if has_size else None
        changes: list[str] = []
        if not item:
            status = "new"
        elif has_size and not variant:
            status = "new_size"
        else:
            if variants and not has_size and row["stock"] is not None:
                problems.append("This item has sizes and colours: add Size or Colour to set its stock")
            current_price = (variant or {}).get("price_paise") if variant and variant.get("price_paise") is not None else item.get("price_paise")
            if row["price_paise"] is not None and row["price_paise"] != current_price:
                changes.append("price")
            if row["gst_rate"] is not None and float(row["gst_rate"]) != float(item.get("gst_rate") or -1):
                changes.append("gst")
            if row["hsn"] and row["hsn"] != (item.get("hsn_code") or None):
                changes.append("hsn")
            current_stock = (variant or item).get("stock_quantity")
            if row["stock"] is not None and row["stock"] != current_stock and not (variants and not has_size):
                changes.append("stock")
            status = "update" if changes else "same"
        current = None
        if item:
            src = variant or item
            current = {"price_paise": (variant or {}).get("price_paise") if variant and variant.get("price_paise") is not None
                       else item.get("price_paise"), "stock": src.get("stock_quantity"),
                       "gst_rate": item.get("gst_rate"), "hsn": item.get("hsn_code")}
        rows.append({"row": n, **row, "status": "problem" if problems else status, "changes": changes,
                     "problems": problems, "catalog_item_id": item["id"] if item else None,
                     "variant_id": variant["id"] if variant else None, "current": current})
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("new", "new_size", "update", "same", "problem")}
    return {"rows": rows, "counts": counts}


# ── saving ────────────────────────────────────────────────────────────────────


async def apply(db, tenant_id: str, raw_rows: list[dict], user_id: str | None) -> dict:
    """Save the checked rows. Every row is checked again here; rows with a problem are skipped."""
    from app.services.catalog_retrieval import embed_and_store_catalog_item
    from app.services.deals import adjust_stock, adjust_variant_stock

    checked = preview(db, tenant_id, raw_rows[:MAX_ROWS])["rows"]
    done = {"new_items": 0, "new_sizes": 0, "updated": 0, "skipped": 0}
    created: dict[str, dict] = {}  # normalised name -> new item, so a list's sizes share one item
    new_ids: list[dict] = []
    note = "Price list upload"
    for row in checked:
        if row["status"] in ("problem", "same"):
            done["skipped"] += row["status"] == "problem"
            continue
        has_size = bool(row["size"] or row["colour"])
        item_id = row["catalog_item_id"] or (created.get(_norm(row["name"])) or {}).get("id")
        if not item_id:
            attrs = {"category": row["group"]} if row["group"] else {}
            item = (db.table("catalog_items").insert({
                "tenant_id": tenant_id, "name": row["name"], "item_type": "product", "status": "ready",
                "attributes": attrs, "price_paise": row["price_paise"], "gst_rate": row["gst_rate"],
                "hsn_code": row["hsn"], "stock_quantity": 0 if (row["stock"] is not None or has_size) else None,
            }).execute().data or [{}])[0]
            created[_norm(row["name"])] = item
            new_ids.append(item)
            item_id = item["id"]
            done["new_items"] += 1
            if not has_size and row["stock"]:
                adjust_stock(tenant_id, item_id, row["stock"], "restock", note=note, created_by=user_id, db=db)
            if not has_size:
                continue
        if has_size and not row["variant_id"]:
            parent = created.get(_norm(row["name"])) or {}
            item_price = parent.get("price_paise") if parent else None
            if not parent:
                item_price = (db.table("catalog_items").select("price_paise").eq("id", item_id).eq("tenant_id", tenant_id)
                              .limit(1).execute().data or [{}])[0].get("price_paise")
            sort = len(db.table("catalog_item_variants").select("id").eq("catalog_item_id", item_id).eq("tenant_id", tenant_id)
                       .limit(500).execute().data or [])
            variant = (db.table("catalog_item_variants").insert({
                "tenant_id": tenant_id, "catalog_item_id": item_id, "size": row["size"], "colour": row["colour"],
                "stock_quantity": 0, "sort_order": sort,
                "price_paise": row["price_paise"] if row["price_paise"] not in (None, item_price) else None,
            }).execute().data or [{}])[0]
            db.table("catalog_items").update({"stock_quantity": 0}).eq("id", item_id).eq("tenant_id", tenant_id) \
                .is_("stock_quantity", "null").execute()
            if row["stock"]:
                adjust_variant_stock(tenant_id, variant["id"], row["stock"], "restock", note=note, created_by=user_id, db=db)
            if row["status"] == "new_size":
                done["new_sizes"] += 1
            continue
        # An update of an existing item (or one of its sizes).
        patch = {}
        if "gst" in row["changes"]:
            patch["gst_rate"] = row["gst_rate"]
        if "hsn" in row["changes"]:
            patch["hsn_code"] = row["hsn"]
        if "price" in row["changes"]:
            if row["variant_id"]:
                db.table("catalog_item_variants").update({"price_paise": row["price_paise"]}).eq("id", row["variant_id"]) \
                    .eq("tenant_id", tenant_id).execute()
            else:
                patch["price_paise"] = row["price_paise"]
        if patch:
            db.table("catalog_items").update(patch).eq("id", item_id).eq("tenant_id", tenant_id).execute()
        if "stock" in row["changes"]:
            current = (row["current"] or {}).get("stock")
            if row["variant_id"]:
                adjust_variant_stock(tenant_id, row["variant_id"], row["stock"] - int(current or 0), "adjustment",
                                     note=note, created_by=user_id, db=db)
            else:
                if current is None:
                    db.table("catalog_items").update({"stock_quantity": 0}).eq("id", item_id).eq("tenant_id", tenant_id).execute()
                    current = 0
                adjust_stock(tenant_id, item_id, row["stock"] - int(current), "restock" if current == 0 else "adjustment",
                             note=note, created_by=user_id, db=db)
        done["updated"] += 1
    for item in new_ids:
        try:
            await embed_and_store_catalog_item(db, tenant_id, item["id"], item["name"], "product", None,
                                               item.get("attributes") or {})
        except Exception:
            logger.warning("Couldn't teach the AI new item %s", item.get("id"))
    if user_id:
        from app.services.audit_log import record_audit_event

        record_audit_event(db, tenant_id=tenant_id, actor_user_id=user_id, actor_role=None, action="catalog.price_list",
                           target_type="catalog", target_id=None, metadata=done)
    return done


def sample_csv() -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(SAMPLE)
    return "﻿" + buf.getvalue()
