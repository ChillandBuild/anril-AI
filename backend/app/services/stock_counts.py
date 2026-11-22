"""Stock count (plan: docs/plans/commerce-stock-plan.md, "The rest"; migration 312).

Count one place in sections; staff scan or type. A counted line keeps what the system said at that moment
(system_qty), so selling can go on: Finish applies (counted − system_qty) to the stock as it is then.
Finish and fix stock is owner only; each change is a stock movement (reason 'count') with its reason,
and the loss at cost is "Stock loss" (shown in Expenses → Real profit).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REASONS = {"damaged": "Damaged", "lost": "Lost", "count_wrong": "Count wrong", "found": "Found in shop", "other": "Other"}
MAX_SECTIONS = 30
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class CountError(ValueError):
    """A plain-words problem the dashboard shows as is (routes turn it into a 400)."""


def _one_line(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _count(db, tenant_id: str, count_id: str, *, open_only: bool = True) -> dict:
    if not _UUID.fullmatch(str(count_id)):
        raise CountError("That count isn't there any more.")
    rows = db.table("stock_counts").select("*").eq("id", count_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
    if not rows or (open_only and rows[0]["status"] not in ("open", "paused")):
        raise CountError("That count is already finished or cancelled.")
    return rows[0]


def start(db, tenant_id: str, place_id: str, sections, *, user_id: str | None, user_name: str | None) -> dict:
    place = (db.table("stock_places").select("id, name").eq("id", place_id).eq("tenant_id", tenant_id)
             .eq("archived", False).limit(1).execute().data or []) if _UUID.fullmatch(str(place_id or "")) else []
    if not place:
        raise CountError("Pick the place to count.")
    names = [s for s in dict.fromkeys(_one_line(s, 60) for s in (sections or []) if isinstance(s, str)) if s][:MAX_SECTIONS]
    try:
        return db.table("stock_counts").insert({
            "tenant_id": tenant_id, "place_id": place_id, "sections": names, "status": "open", "started_by": user_id,
            "started_by_name": user_name, "started_at": datetime.now(timezone.utc).isoformat()}).execute().data[0]
    except Exception as e:
        if "23505" in str(e) or "duplicate" in str(e).lower():
            raise CountError(f"A count of {place[0]['name']} is already going on. Open it instead.")
        raise


def _level(db, tenant_id: str, place_id: str, item_id: str, variant_id: str | None) -> int:
    q = (db.table("stock_levels").select("quantity").eq("tenant_id", tenant_id).eq("place_id", place_id)
         .eq("catalog_item_id", item_id))
    q = q.eq("variant_id", variant_id) if variant_id else q.is_("variant_id", "null")
    return sum(int(r["quantity"]) for r in (q.execute().data or []))


def record(db, tenant_id: str, count_id: str, payload: dict, *, user_id: str | None, user_name: str | None) -> dict:
    """Count a line: {item_id, variant_id, section, qty} sets the number; {…, add: 1} adds (a scan)."""
    count = _count(db, tenant_id, count_id)
    if count["status"] == "paused":
        raise CountError("The count is paused. Resume it to go on counting.")
    item_id, variant_id = payload.get("item_id"), payload.get("variant_id") or None
    if not _UUID.fullmatch(str(item_id or "")) or (variant_id and not _UUID.fullmatch(str(variant_id))):
        raise CountError("Pick the item again.")
    item = (db.table("catalog_items").select("id, name, stock_quantity").eq("id", item_id).eq("tenant_id", tenant_id)
            .limit(1).execute().data or [])
    if not item:
        raise CountError("Pick the item again.")
    has_sizes = bool(db.table("catalog_item_variants").select("id").eq("tenant_id", tenant_id)
                     .eq("catalog_item_id", item_id).limit(1).execute().data)
    if variant_id:
        if not (db.table("catalog_item_variants").select("id").eq("id", variant_id).eq("tenant_id", tenant_id)
                .eq("catalog_item_id", item_id).limit(1).execute().data):
            raise CountError("That size or colour isn't on this item.")
    elif has_sizes:
        raise CountError(f"{item[0]['name']} has sizes/colours: count each one.")
    q = (db.table("stock_count_lines").select("*").eq("tenant_id", tenant_id).eq("count_id", count_id)
         .eq("catalog_item_id", item_id))
    existing = ((q.eq("variant_id", variant_id) if variant_id else q.is_("variant_id", "null")).limit(1).execute().data or [])
    try:
        if "add" in payload:
            qty = (int(existing[0]["counted_qty"]) if existing else 0) + int(payload["add"])
        else:
            qty = int(payload.get("qty"))
    except (TypeError, ValueError):
        raise CountError("The count must be a whole number.")
    if not 0 <= qty <= 1_000_000:
        raise CountError("The count must be 0 or more.")
    section = _one_line(payload.get("section"), 60) or (existing[0].get("section") if existing else None)
    fields = {"counted_qty": qty, "section": section, "counted_by": user_id, "counted_by_name": user_name,
              "counted_at": datetime.now(timezone.utc).isoformat(),
              # what the system says now: bills made after this are allowed for on Finish
              "system_qty": _level(db, tenant_id, count["place_id"], item_id, variant_id)}
    if existing:
        if fields["counted_qty"] - fields["system_qty"] == 0:
            fields["reason"] = None
        return db.table("stock_count_lines").update(fields).eq("id", existing[0]["id"]).eq("tenant_id", tenant_id) \
            .execute().data[0]
    return db.table("stock_count_lines").insert({**fields, "tenant_id": tenant_id, "count_id": count_id,
                                                 "catalog_item_id": item_id, "variant_id": variant_id}).execute().data[0]


def set_reason(db, tenant_id: str, line_id: str, reason: str | None) -> None:
    if reason is not None and reason not in REASONS:
        raise CountError("Pick a reason.")
    if not _UUID.fullmatch(str(line_id)):
        raise CountError("That line isn't there any more.")
    line = (db.table("stock_count_lines").select("count_id").eq("id", line_id).eq("tenant_id", tenant_id)
            .limit(1).execute().data or [])
    if not line:
        raise CountError("That line isn't there any more.")
    _count(db, tenant_id, line[0]["count_id"])
    db.table("stock_count_lines").update({"reason": reason}).eq("id", line_id).eq("tenant_id", tenant_id).execute()


def set_status(db, tenant_id: str, count_id: str, status: str) -> None:
    if status not in ("open", "paused", "cancelled"):
        raise CountError("Unknown action.")
    _count(db, tenant_id, count_id)
    db.table("stock_counts").update({"status": status}).eq("id", count_id).eq("tenant_id", tenant_id) \
        .in_("status", ["open", "paused"]).execute()


def _costs(db, tenant_id: str, lines: list[dict]) -> dict[tuple[str, str | None], int]:
    """Cost each (cost price, else selling price) per line, for the ₹ at cost."""
    item_ids = list({l["catalog_item_id"] for l in lines})
    items = {r["id"]: r for r in (db.table("catalog_items").select("id, cost_price_paise, price_paise").eq("tenant_id", tenant_id)
                                  .in_("id", item_ids).execute().data or [])} if item_ids else {}
    variant_ids = [l["variant_id"] for l in lines if l.get("variant_id")]
    variants = {r["id"]: r for r in (db.table("catalog_item_variants").select("id, cost_price_paise, price_paise")
                                     .eq("tenant_id", tenant_id).in_("id", variant_ids).execute().data or [])} \
        if variant_ids else {}
    out = {}
    for l in lines:
        v, it = variants.get(l.get("variant_id") or ""), items.get(l["catalog_item_id"], {})
        out[(l["catalog_item_id"], l.get("variant_id"))] = int(
            (v or {}).get("cost_price_paise") or it.get("cost_price_paise") or (v or {}).get("price_paise") or it.get("price_paise") or 0)
    return out


def view(db, tenant_id: str) -> dict:
    """The open (or paused) counts, the latest one in full: lines, cards, what is not counted yet."""
    from app.services.deals import variant_label

    places = {p["id"]: p for p in (db.table("stock_places").select("id, name, bills_from").eq("tenant_id", tenant_id)
                                   .eq("archived", False).order("sort_order").execute().data or [])}
    open_counts = (db.table("stock_counts").select("*").eq("tenant_id", tenant_id).in_("status", ["open", "paused"])
                   .order("started_at", desc=True).execute().data or [])
    last = (db.table("stock_counts").select("id, place_id, finished_at, finished_by_name, loss_paise, gain_paise")
            .eq("tenant_id", tenant_id).eq("status", "finished").order("finished_at", desc=True).limit(5).execute().data or [])
    base = {"places": list(places.values()), "open": [{**c, "place": places.get(c["place_id"], {}).get("name")} for c in open_counts],
            "finished": [{**c, "place": places.get(c["place_id"], {}).get("name")} for c in last], "count": None}
    if not open_counts:
        return base
    count = open_counts[0]
    lines = (db.table("stock_count_lines").select("*").eq("tenant_id", tenant_id).eq("count_id", count["id"])
             .order("counted_at", desc=True).limit(5000).execute().data or [])
    levels = (db.table("stock_levels").select("catalog_item_id, variant_id, quantity").eq("tenant_id", tenant_id)
              .eq("place_id", count["place_id"]).gt("quantity", 0).limit(20000).execute().data or [])
    counted_keys = {(l["catalog_item_id"], l.get("variant_id")) for l in lines}
    not_counted = [lv for lv in levels if (lv["catalog_item_id"], lv.get("variant_id")) not in counted_keys]
    every = lines + [{"catalog_item_id": lv["catalog_item_id"], "variant_id": lv.get("variant_id")} for lv in not_counted]
    item_ids = list({l["catalog_item_id"] for l in every})
    names = {r["id"]: r["name"] for r in (db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id)
                                          .in_("id", item_ids).execute().data or [])} if item_ids else {}
    variant_ids = list({l["variant_id"] for l in every if l.get("variant_id")})
    variants = {r["id"]: r for r in (db.table("catalog_item_variants").select("id, size, colour").eq("tenant_id", tenant_id)
                                     .in_("id", variant_ids).execute().data or [])} if variant_ids else {}
    costs = _costs(db, tenant_id, every)
    rows = []
    for l in lines:
        diff = int(l["counted_qty"]) - int(l["system_qty"])
        v = variants.get(l.get("variant_id") or "")
        rows.append({**l, "name": names.get(l["catalog_item_id"], "Removed item"), "variant_label": variant_label(v) if v else "",
                     "difference": diff, "value_paise": diff * costs.get((l["catalog_item_id"], l.get("variant_id")), 0)})
    rows.sort(key=lambda r: (r["difference"] == 0, -abs(r["difference"]), r["name"].lower()))
    less = [r for r in rows if r["difference"] < 0]
    more = [r for r in rows if r["difference"] > 0]
    count_view = {
        **count, "place": places.get(count["place_id"], {}).get("name"), "lines": rows,
        "cards": {
            "counted": len(rows), "total": len(rows) + len(not_counted),
            "match": sum(1 for r in rows if r["difference"] == 0),
            "less": {"items": len(less), "pieces": -sum(r["difference"] for r in less), "value_paise": -sum(r["value_paise"] for r in less)},
            "more": {"items": len(more), "pieces": sum(r["difference"] for r in more), "value_paise": sum(r["value_paise"] for r in more)},
            "not_counted": len(not_counted),
            "counters": list(dict.fromkeys(r["counted_by_name"] for r in rows if r.get("counted_by_name"))),
        },
        "not_counted": sorted(({"catalog_item_id": lv["catalog_item_id"], "variant_id": lv.get("variant_id"),
                                "name": names.get(lv["catalog_item_id"], ""),
                                "variant_label": variant_label(variants[lv["variant_id"]]) if lv.get("variant_id") in variants else "",
                                "system_qty": int(lv["quantity"])} for lv in not_counted), key=lambda r: (r["name"].lower(), r["variant_label"]))[:300],
        "missing_reasons": sum(1 for r in rows if r["difference"] and not r.get("reason")),
    }
    return {**base, "count": count_view}


def finish(db, tenant_id: str, count_id: str, *, user_id: str | None, user_name: str | None) -> dict:
    """Owner only (the route checks). Applies every difference once, with its reason. Returns a summary."""
    from app.services.deals import adjust_stock, adjust_variant_stock

    count = _count(db, tenant_id, count_id)
    lines = (db.table("stock_count_lines").select("*").eq("tenant_id", tenant_id).eq("count_id", count_id)
             .limit(5000).execute().data or [])
    off = [l for l in lines if int(l["counted_qty"]) != int(l["system_qty"])]
    if any(not l.get("reason") for l in off):
        raise CountError("Give a reason for every difference first.")
    if not db.rpc("claim_stock_count", {"p_tenant_id": tenant_id, "p_count": count_id, "p_user": user_id,
                                         "p_name": user_name}).execute().data:
        raise CountError("That count is already finished or cancelled.")
    costs = _costs(db, tenant_id, off)
    loss = gain = changed = 0
    for l in off:
        delta = int(l["counted_qty"]) - int(l["system_qty"])
        if delta < 0:  # never below zero: bills during the count may already have taken some
            delta = -min(-delta, _level(db, tenant_id, count["place_id"], l["catalog_item_id"], l.get("variant_id")))
        if delta == 0:
            continue
        note = f"Stock count: {REASONS.get(l['reason'], 'Other')}"
        common = {"note": note, "created_by": user_id, "place_id": count["place_id"], "db": db}
        res = (adjust_variant_stock(tenant_id, l["variant_id"], delta, "count", **common) if l.get("variant_id")
               else adjust_stock(tenant_id, l["catalog_item_id"], delta, "count", **common))
        if not res["ok"]:
            logger.warning("Count %s: couldn't apply %s to %s", count_id, delta, l["id"])
            continue
        db.table("stock_count_lines").update({"applied_delta": delta}).eq("id", l["id"]).eq("tenant_id", tenant_id).execute()
        value = abs(delta) * costs.get((l["catalog_item_id"], l.get("variant_id")), 0)
        loss, gain, changed = loss + (value if delta < 0 else 0), gain + (value if delta > 0 else 0), changed + 1
    db.table("stock_counts").update({"loss_paise": loss, "gain_paise": gain}).eq("id", count_id).eq("tenant_id", tenant_id).execute()
    return {"changed": changed, "loss_paise": loss, "gain_paise": gain}


def corrections(db, tenant_id: str, limit: int = 200) -> list[dict]:
    """Purchases → Suppliers → Stock corrections: every change that isn't a sale, purchase or move."""
    from app.services.deals import variant_label

    rows = (db.table("stock_movements").select("catalog_item_id, variant_id, delta, reason, note, created_by, created_at")
            .eq("tenant_id", tenant_id).in_("reason", ["adjustment", "count", "write_off", "supplier_return"])
            .order("created_at", desc=True).limit(limit).execute().data or [])
    item_ids = list({r["catalog_item_id"] for r in rows})
    names = {r["id"]: r["name"] for r in (db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id)
                                          .in_("id", item_ids).execute().data or [])} if item_ids else {}
    variant_ids = list({r["variant_id"] for r in rows if r.get("variant_id")})
    variants = {r["id"]: r for r in (db.table("catalog_item_variants").select("id, size, colour").eq("tenant_id", tenant_id)
                                     .in_("id", variant_ids).execute().data or [])} if variant_ids else {}
    users = list({r["created_by"] for r in rows if r.get("created_by")})
    who = {u["user_id"]: u.get("full_name") for u in (db.table("tenant_users").select("user_id, full_name")
                                                      .eq("tenant_id", tenant_id).in_("user_id", users).execute().data or [])} \
        if users else {}
    return [{"name": names.get(r["catalog_item_id"], "Removed item"),
             "variant_label": variant_label(variants[r["variant_id"]]) if r.get("variant_id") in variants else "",
             "delta": r["delta"], "reason": r["reason"], "note": r.get("note"), "by": who.get(r.get("created_by")),
             "at": r["created_at"]} for r in rows]


def stock_loss(db, tenant_id: str, since_iso: str) -> int:
    """Stock loss (at cost) of counts finished since then, less what counts found."""
    rows = (db.table("stock_counts").select("loss_paise, gain_paise").eq("tenant_id", tenant_id).eq("status", "finished")
            .gte("finished_at", since_iso).limit(1000).execute().data or [])
    return sum(int(r["loss_paise"]) - int(r["gain_paise"]) for r in rows)
