"""Barcodes (plan: docs/plans/commerce-stock-plan.md, "The rest"; migration 311).

Every item (no sizes) or size/colour gets a code: Anril's own short code (shop initials · item initials ·
size/colour, e.g. DS-KP-RM), made the first time it is needed and printed on labels; or a company
barcode (EAN/UPC) typed or scanned on the item, which is kept and never printed. Scanning (USB scanner
or phone camera) finds the item by its code on New bill, Stock in and Stock count.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
LABEL_SIZES = ("38x25", "50x25", "a4_65")
MAX_LABELS = 2000
MAX_PICK = 300
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_CODE = re.compile(r"[A-Za-z0-9-]{3,40}")
_COMPANY = re.compile(r"\d{8}|\d{12,14}")  # EAN-8, UPC-A, EAN-13, GTIN-14


class BarcodeError(ValueError):
    """A plain-words problem the dashboard shows as is (routes turn it into a 400)."""


def _initials(text: str | None, single_word_letters: int = 2) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(text or ""))
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:single_word_letters].upper()
    return "".join(w[0] for w in words[:3]).upper()


def _variant_part(variant: dict | None) -> str:
    if not variant:
        return ""
    colour = _initials(variant.get("colour"), 1) if variant.get("colour") else ""
    size = re.sub(r"[^A-Za-z0-9]", "", str(variant.get("size") or "")).upper()[:4]
    if colour and size:
        return colour + size
    return size or _initials(variant.get("colour"), 2)


def own_code(prefix: str, item_name: str, variant: dict | None) -> str:
    """'DS-KP-RM': shop · item · colour+size (no size → no last part)."""
    parts = [p for p in (prefix, _initials(item_name) or "IT", _variant_part(variant)) if p]
    return "-".join(parts)[:36]


def shop_prefix(db, tenant_id: str) -> str:
    from app.services.business_details import get_business_details
    try:
        name = (get_business_details(tenant_id, db) or {}).get("legal_name") or ""
    except Exception:
        name = ""
    return _initials(name) or "AN"


def _codes(db, tenant_id: str) -> list[dict]:
    return (db.table("stock_codes").select("id, catalog_item_id, variant_id, code, company").eq("tenant_id", tenant_id)
            .limit(50000).execute().data or [])


def ensure_codes(db, tenant_id: str, lines: list[tuple[str, str | None]]) -> dict[tuple[str, str | None], dict]:
    """The code for each (item, size/colour) line, making Anril's own code where there is none yet."""
    existing = _codes(db, tenant_id)
    by_line = {(c["catalog_item_id"], c.get("variant_id")): c for c in existing}
    taken = {c["code"].upper() for c in existing}
    missing = [line for line in dict.fromkeys(lines) if line not in by_line]
    if missing:
        prefix = shop_prefix(db, tenant_id)
        item_ids = list({i for i, _ in missing})
        names = {r["id"]: r["name"] for r in (db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id)
                                              .in_("id", item_ids).execute().data or [])}
        variant_ids = [v for _, v in missing if v]
        variants = {r["id"]: r for r in (db.table("catalog_item_variants").select("id, catalog_item_id, size, colour")
                                         .eq("tenant_id", tenant_id).in_("id", variant_ids).execute().data or [])} \
            if variant_ids else {}
        for item_id, variant_id in missing:
            if item_id not in names or (variant_id and variants.get(variant_id, {}).get("catalog_item_id") != item_id):
                continue
            base = own_code(prefix, names[item_id], variants.get(variant_id) if variant_id else None)
            code, n = base, 2
            while code.upper() in taken:
                code, n = f"{base}{n}", n + 1
            try:
                row = (db.table("stock_codes").insert({"tenant_id": tenant_id, "catalog_item_id": item_id,
                                                       "variant_id": variant_id, "code": code, "company": False})
                       .execute().data or [None])[0]
            except Exception as e:  # made at the same moment by someone else: read theirs
                logger.info("Code for %s/%s already made (%s)", item_id, variant_id, e)
                row = next((c for c in _codes(db, tenant_id)
                            if (c["catalog_item_id"], c.get("variant_id")) == (item_id, variant_id)), None)
            if row:
                by_line[(item_id, variant_id)] = row
                taken.add(row["code"].upper())
    return {line: by_line[line] for line in lines if line in by_line}


def lookup(db, tenant_id: str, code: str) -> dict | None:
    """The item (and size/colour) a scanned code belongs to, or None."""
    code = re.sub(r"\s", "", str(code or ""))
    if not _CODE.fullmatch(code):
        return None
    rows = (db.table("stock_codes").select("catalog_item_id, variant_id, code, company").eq("tenant_id", tenant_id)
            .ilike("code", code).limit(1).execute().data or [])
    if not rows:
        return None
    row = rows[0]
    item = (db.table("catalog_items").select("id, name, price_paise, status").eq("id", row["catalog_item_id"])
            .eq("tenant_id", tenant_id).limit(1).execute().data or [None])[0]
    if not item:
        return None
    variant = None
    if row.get("variant_id"):
        variant = (db.table("catalog_item_variants").select("id, size, colour, price_paise").eq("id", row["variant_id"])
                   .eq("tenant_id", tenant_id).limit(1).execute().data or [None])[0]
    from app.services.deals import variant_label
    return {"catalog_item_id": item["id"], "variant_id": (variant or {}).get("id"), "name": item["name"],
            "variant_label": variant_label(variant) if variant else "", "code": row["code"],
            "price_paise": (variant or {}).get("price_paise") or item.get("price_paise")}


def set_company_code(db, tenant_id: str, item_id: str, variant_id: str | None, code: str | None) -> dict | None:
    """Type (or scan) the barcode printed by the maker. Empty = forget it (Anril's own code is made next
    time labels are printed)."""
    if not _UUID.fullmatch(str(item_id)) or (variant_id and not _UUID.fullmatch(str(variant_id))):
        raise BarcodeError("Item not found.")
    item = db.table("catalog_items").select("id").eq("id", item_id).eq("tenant_id", tenant_id).limit(1).execute().data
    if not item:
        raise BarcodeError("Item not found.")
    if variant_id and not (db.table("catalog_item_variants").select("id").eq("id", variant_id).eq("tenant_id", tenant_id)
                           .eq("catalog_item_id", item_id).limit(1).execute().data):
        raise BarcodeError("That size or colour isn't on this item.")
    q = db.table("stock_codes").delete().eq("tenant_id", tenant_id).eq("catalog_item_id", item_id)
    (q.eq("variant_id", variant_id) if variant_id else q.is_("variant_id", "null")).execute()
    code = re.sub(r"\s", "", str(code or ""))
    if not code:
        return None
    if not _COMPANY.fullmatch(code):
        raise BarcodeError("A company barcode is 8, 12, 13 or 14 digits (the number under the bars).")
    other = (db.table("stock_codes").select("catalog_item_id").eq("tenant_id", tenant_id).ilike("code", code)
             .limit(1).execute().data)
    if other:
        raise BarcodeError("Another item already has this barcode.")
    return (db.table("stock_codes").insert({"tenant_id": tenant_id, "catalog_item_id": item_id, "variant_id": variant_id,
                                            "code": code, "company": True}).execute().data or [None])[0]


# ── labels ───────────────────────────────────────────────────────────────────


def _lines_of_stock_in(db, tenant_id: str, stock_in_id: str) -> list[tuple[str, str | None, int]]:
    rows = (db.table("stock_in_lines").select("catalog_item_id, variant_id, qty_good, qty_damaged, damaged_action")
            .eq("tenant_id", tenant_id).eq("stock_in_id", stock_in_id).execute().data or [])
    return [(r["catalog_item_id"], r.get("variant_id"),
             int(r["qty_good"]) + (int(r["qty_damaged"]) if r.get("damaged_action") == "discount" else 0)) for r in rows]


def latest_stock_in(db, tenant_id: str) -> dict | None:
    """Today's latest stock in (the default 'what to print')."""
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = (db.table("stock_ins").select("id, bill_no, created_at").eq("tenant_id", tenant_id).gte("created_at", start)
            .order("created_at", desc=True).limit(1).execute().data or [])
    return rows[0] if rows else None


def _stock_lines(db, tenant_id: str) -> list[tuple[str, str | None]]:
    """Every product stock line: items without sizes, and each size/colour."""
    items = (db.table("catalog_items").select("id, item_type").eq("tenant_id", tenant_id).limit(5000).execute().data or [])
    products = {i["id"] for i in items if (i.get("item_type") or "product") == "product"}
    variants = (db.table("catalog_item_variants").select("id, catalog_item_id").eq("tenant_id", tenant_id)
                .limit(20000).execute().data or [])
    with_sizes = {v["catalog_item_id"] for v in variants}
    return ([(v["catalog_item_id"], v["id"]) for v in variants if v["catalog_item_id"] in products]
            + [(i, None) for i in products if i not in with_sizes])


def options(db, tenant_id: str) -> dict:
    latest = latest_stock_in(db, tenant_id)
    count = sum(q for _, _, q in _lines_of_stock_in(db, tenant_id, latest["id"])) if latest else 0
    have = {(c["catalog_item_id"], c.get("variant_id")) for c in _codes(db, tenant_id)}
    lines = _stock_lines(db, tenant_id)
    names = {r["id"]: r["name"] for r in (db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id)
                                          .limit(5000).execute().data or [])}
    variants = {r["id"]: r for r in (db.table("catalog_item_variants").select("id, size, colour").eq("tenant_id", tenant_id)
                                     .limit(20000).execute().data or [])}
    from app.services.deals import variant_label
    company = {(c["catalog_item_id"], c.get("variant_id")) for c in _codes(db, tenant_id) if c.get("company")}
    pick = sorted(({"item_id": i, "variant_id": v, "name": names.get(i, ""),
                    "variant_label": variant_label(variants[v]) if v and v in variants else "",
                    "company": (i, v) in company} for i, v in lines if names.get(i)),
                  key=lambda r: (r["name"].lower(), r["variant_label"]))
    return {"stock_in": {**latest, "labels": count} if latest else None,
            "no_code": sum(1 for line in lines if line not in have),
            "shop_name": _shop_name(db, tenant_id), "lines": pick}


def _shop_name(db, tenant_id: str) -> str:
    from app.services.business_details import get_business_details
    try:
        return ((get_business_details(tenant_id, db) or {}).get("legal_name") or "").strip()[:40]
    except Exception:
        return ""


def labels(db, tenant_id: str, payload: dict) -> dict:
    """The labels to print. source: stock_in (+stock_in_id, default today's latest) | pick (lines
    [{item_id, variant_id, qty}]) | no_code. Lines with a company barcode are left out (kept, not printed)."""
    source = payload.get("source")
    if source == "stock_in":
        sid = payload.get("stock_in_id") or (latest_stock_in(db, tenant_id) or {}).get("id")
        if not sid or not _UUID.fullmatch(str(sid)):
            raise BarcodeError("No stock in today. Pick items instead.")
        wanted = _lines_of_stock_in(db, tenant_id, sid)
    elif source == "pick":
        wanted = []
        for li in (payload.get("lines") or [])[:MAX_PICK]:
            if not isinstance(li, dict) or not _UUID.fullmatch(str(li.get("item_id"))):
                continue
            v = li.get("variant_id") or None
            if v and not _UUID.fullmatch(str(v)):
                continue
            try:
                qty = max(1, min(int(li.get("qty") or 1), 500))
            except (TypeError, ValueError):
                qty = 1
            wanted.append((li["item_id"], v, qty))
    elif source == "no_code":
        have = {(c["catalog_item_id"], c.get("variant_id")) for c in _codes(db, tenant_id)}
        wanted = [(i, v, 1) for i, v in _stock_lines(db, tenant_id) if (i, v) not in have]
    else:
        raise BarcodeError("Pick what to print.")
    wanted = [w for w in wanted if w[2] > 0]
    if sum(q for _, _, q in wanted) > MAX_LABELS:
        raise BarcodeError(f"That is more than {MAX_LABELS} labels. Print in parts.")
    codes = ensure_codes(db, tenant_id, [(i, v) for i, v, _ in wanted])
    item_ids = list({i for i, _, _ in wanted})
    items = {r["id"]: r for r in (db.table("catalog_items").select("id, name, price_paise").eq("tenant_id", tenant_id)
                                  .in_("id", item_ids).execute().data or [])} if item_ids else {}
    variant_ids = [v for _, v, _ in wanted if v]
    variants = {r["id"]: r for r in (db.table("catalog_item_variants").select("id, size, colour, price_paise")
                                     .eq("tenant_id", tenant_id).in_("id", variant_ids).execute().data or [])} \
        if variant_ids else {}
    from app.services.deals import variant_label
    out, kept = [], 0
    for item_id, variant_id, qty in wanted:
        code = codes.get((item_id, variant_id))
        item = items.get(item_id)
        if not code or not item:
            continue
        if code.get("company"):
            kept += 1
            continue
        v = variants.get(variant_id or "")
        out.append({"code": code["code"], "name": item["name"], "variant_label": variant_label(v) if v else "",
                    "price_paise": (v or {}).get("price_paise") or item.get("price_paise"), "qty": qty})
    return {"labels": out, "kept_company": kept, "shop_name": _shop_name(db, tenant_id)}
