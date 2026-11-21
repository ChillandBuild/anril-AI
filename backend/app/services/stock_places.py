"""Shop & godown (plan: docs/plans/commerce-stock-plan.md, part 4; migrations 304 + 309).

* Places: the business's own (Shop, Gandhipuram godown, Branch 2…). One is where counter bills
  take stock from, one is where online / AI orders are packed from (often the same).
* Stock per place lives in stock_levels; the item and size/colour totals stay the sum, so every
  old reader is unchanged. Selling with no place given starts at the bill (or online) place and
  takes the rest from the others (apply_stock_movement, 309).
* Move stock: sending takes it out of the "from" place at once (On the way, sellable nowhere);
  it reaches the "to" place only when someone taps Received. Received / Cancel work once.
* Suggested moves: the bill place has less than a week's sales (or is at its low-stock level)
  and another place has it.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
KINDS = ("shop", "godown", "other")
MAX_PLACES = 20
NAME_MAX = 60
READY_MAX = 80
NOTE_MAX = 300
MAX_LINES = 100
SOLD_DAYS = 7
DEFAULT_READY = "ready in 1 day"
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class StockPlaceError(ValueError):
    """A plain-words problem the dashboard shows as is (routes turn it into a 400)."""


def _one_line(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


# ── places ───────────────────────────────────────────────────────────────────


def places(db, tenant_id: str, *, with_archived: bool = False, create: bool = True) -> list[dict]:
    """The business's places in their order; a business with none gets "Shop" (holding everything).
    create=False only reads (the AI's reply path never writes)."""
    def read():
        q = db.table("stock_places").select("id, name, kind, bills_from, online_from, ready_note, archived, sort_order") \
            .eq("tenant_id", tenant_id)
        if not with_archived:
            q = q.eq("archived", False)
        return q.order("sort_order").order("created_at").execute().data or []

    rows = read()
    if not rows and not with_archived and create:
        db.rpc("default_stock_place", {"p_tenant_id": tenant_id}).execute()
        rows = read()
    return rows


def _place_problems(rows: list[dict]) -> list[str]:
    live = [r for r in rows if not r.get("archived")]
    out: list[str] = []
    if not live:
        out.append("Keep at least one place.")
    if len(live) > MAX_PLACES:
        out.append(f"At most {MAX_PLACES} places.")
    names = [r["name"].lower() for r in live]
    if any(not n for n in names):
        out.append("Every place needs a name.")
    if len(set(names)) != len(names):
        out.append("Two places have the same name.")
    if live and sum(1 for r in live if r["bills_from"]) != 1:
        out.append("Pick the one place counter bills take stock from.")
    if live and sum(1 for r in live if r["online_from"]) != 1:
        out.append("Pick the one place online orders are packed from.")
    return out


def save_places(db, tenant_id: str, payload: list) -> list[dict]:
    """Replace the place settings with what the Places dialog saved (nothing applies until Save)."""
    if not isinstance(payload, list):
        raise StockPlaceError("Send the list of places.")
    current = {p["id"]: p for p in places(db, tenant_id, with_archived=True)}
    rows: list[dict] = []
    for i, raw in enumerate(payload[: MAX_PLACES + 5]):
        if not isinstance(raw, dict):
            continue
        pid = raw.get("id") if isinstance(raw.get("id"), str) and raw.get("id") in current else None
        rows.append({
            "id": pid,
            "name": _one_line(raw.get("name"), NAME_MAX),
            "kind": raw.get("kind") if raw.get("kind") in KINDS else "other",
            "bills_from": bool(raw.get("bills_from")),
            "online_from": bool(raw.get("online_from")),
            "ready_note": _one_line(raw.get("ready_note"), READY_MAX) or None,
            "archived": bool(raw.get("archived")) and pid is not None,
            "sort_order": i,
        })
    problems = _place_problems(rows)
    to_archive = [r["id"] for r in rows if r["archived"] and not current[r["id"]]["archived"]]
    if to_archive:
        stocked = (
            db.table("stock_levels").select("place_id").eq("tenant_id", tenant_id).in_("place_id", to_archive)
            .gt("quantity", 0).limit(1).execute()
        ).data or []
        if stocked:
            name = next(r["name"] for r in rows if r["id"] == stocked[0]["place_id"])
            problems.append(f"{name} still has stock: move it to another place before removing {name}.")
        open_moves = (
            db.table("stock_moves").select("id, from_place_id, to_place_id").eq("tenant_id", tenant_id)
            .eq("status", "on_the_way").limit(500).execute()
        ).data or []
        if any(m["from_place_id"] in to_archive or m["to_place_id"] in to_archive for m in open_moves):
            problems.append("A place you are removing has stock on the way: receive or cancel that move first.")
    if problems:
        raise StockPlaceError(" ".join(problems))
    # The two "one per business" flags are unique: clear them all first, then write each place.
    db.table("stock_places").update({"bills_from": False, "online_from": False}).eq("tenant_id", tenant_id).execute()
    for r in sorted(rows, key=lambda r: not r["archived"]):  # removals first, so a new place may take a freed name
        fields = {k: v for k, v in r.items() if k != "id"}
        if r["id"]:
            db.table("stock_places").update(fields).eq("id", r["id"]).eq("tenant_id", tenant_id).execute()
        else:
            db.table("stock_places").insert({**fields, "tenant_id": tenant_id}).execute()
    return places(db, tenant_id)


def bill_place(rows: list[dict]) -> dict | None:
    return next((p for p in rows if p.get("bills_from")), rows[0] if rows else None)


def online_place(rows: list[dict]) -> dict | None:
    return next((p for p in rows if p.get("online_from")), bill_place(rows))


# ── the overview: stock per place, suggestions ───────────────────────────────


def _lines(db, tenant_id: str) -> list[dict]:
    """Every tracked stock line: an item without sizes, or one size/colour of an item."""
    items = (
        db.table("catalog_items").select("id, name, price_paise, stock_quantity, low_stock_at")
        .eq("tenant_id", tenant_id).not_.is_("stock_quantity", "null").order("name").limit(5000).execute()
    ).data or []
    variants = (
        db.table("catalog_item_variants").select("id, catalog_item_id, size, colour, price_paise, sort_order")
        .eq("tenant_id", tenant_id).order("sort_order").limit(20000).execute()
    ).data or []
    by_item: dict[str, list[dict]] = {}
    for v in variants:
        by_item.setdefault(v["catalog_item_id"], []).append(v)
    out: list[dict] = []
    for it in items:
        vs = by_item.get(it["id"])
        if vs:
            for v in vs:
                label = " · ".join(x for x in (v.get("colour"), v.get("size")) if x)
                out.append({"key": v["id"], "item_id": it["id"], "variant_id": v["id"], "name": it["name"],
                            "label": label, "price_paise": v.get("price_paise") or it.get("price_paise"),
                            "low_stock_at": it.get("low_stock_at")})
        else:
            out.append({"key": it["id"], "item_id": it["id"], "variant_id": None, "name": it["name"], "label": "",
                        "price_paise": it.get("price_paise"), "low_stock_at": it.get("low_stock_at")})
    return out


def suggestion(line: dict, to_place: str, place_ids: list[str]) -> dict | None:
    """When the bill place is Low (the item's own level, else deals.LOW_STOCK_THRESHOLD, as everywhere
    in the catalogue) or holds less than a week's sales: move enough to be above Low and cover the week."""
    from app.services.deals import LOW_STOCK_THRESHOLD

    have = line["by_place"].get(to_place, 0) + int(line.get("coming") or 0)  # on the way there counts
    sold = int(line.get("sold") or 0)
    low_at = line.get("low_stock_at")
    low_at = LOW_STOCK_THRESHOLD if low_at is None else int(low_at)
    if have > low_at and have >= sold:
        return None
    target = max(sold, low_at + 1)
    others = [(line["by_place"].get(p, 0), p) for p in place_ids if p != to_place]
    best_qty, best = max(others, default=(0, None))
    if not best or best_qty <= 0:
        return None
    return {"from_place_id": best, "to_place_id": to_place, "quantity": min(best_qty, target - have)}


def overview(db, tenant_id: str) -> dict:
    rows = places(db, tenant_id)
    place_ids = [p["id"] for p in rows]
    home = bill_place(rows)
    lines = _lines(db, tenant_id)
    by_key = {li["key"]: {**li, "by_place": {}, "sold": 0} for li in lines}
    for lv in (
        db.table("stock_levels").select("catalog_item_id, variant_id, place_id, quantity")
        .eq("tenant_id", tenant_id).gt("quantity", 0).limit(50000).execute()
    ).data or []:
        line = by_key.get(lv.get("variant_id") or lv["catalog_item_id"])
        if line is not None:
            line["by_place"][lv["place_id"]] = line["by_place"].get(lv["place_id"], 0) + int(lv["quantity"])
    since = (datetime.now(timezone.utc) - timedelta(days=SOLD_DAYS)).isoformat()
    for m in (
        db.table("stock_movements").select("catalog_item_id, variant_id, delta")
        .eq("tenant_id", tenant_id).eq("reason", "sale").gte("created_at", since).limit(50000).execute()
    ).data or []:
        line = by_key.get(m.get("variant_id") or m["catalog_item_id"])
        if line is not None:
            line["sold"] += -int(m.get("delta") or 0)
    if home:  # stock already on the way to the bill place, so a suggestion isn't sent twice
        open_to_home = [m["id"] for m in (
            db.table("stock_moves").select("id").eq("tenant_id", tenant_id).eq("status", "on_the_way")
            .eq("to_place_id", home["id"]).limit(500).execute()
        ).data or []]
        if open_to_home:
            for li in (
                db.table("stock_move_lines").select("catalog_item_id, variant_id, quantity").eq("tenant_id", tenant_id)
                .in_("move_id", open_to_home).limit(5000).execute()
            ).data or []:
                line = by_key.get(li.get("variant_id") or li["catalog_item_id"])
                if line is not None:
                    line["coming"] = line.get("coming", 0) + int(li["quantity"])
    out_lines = []
    for line in by_key.values():
        line["suggestion"] = suggestion(line, home["id"], place_ids) if home and len(rows) > 1 else None
        out_lines.append(line)
    out_lines.sort(key=lambda li: (li["suggestion"] is None, li["name"].lower(), li["label"]))
    totals = {p["id"]: {"pieces": 0, "value_paise": 0} for p in rows}
    for line in out_lines:
        for pid, qty in line["by_place"].items():
            if pid in totals:
                totals[pid]["pieces"] += qty
                totals[pid]["value_paise"] += qty * int(line.get("price_paise") or 0)
    moves = list_moves(db, tenant_id)
    on_way = [m for m in moves if m["status"] == "on_the_way"]
    return {
        "places": [{**p, **totals[p["id"]]} for p in rows],
        "lines": out_lines,
        "moves": moves,
        "on_the_way": {"pieces": sum(m["pieces"] for m in on_way), "moves": len(on_way)},
        "suggested": sum(1 for li in out_lines if li["suggestion"]),
        "sold_days": SOLD_DAYS,
    }


# ── moves ────────────────────────────────────────────────────────────────────


def list_moves(db, tenant_id: str) -> list[dict]:
    """Every move still on the way, and those received or cancelled today."""
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    cols = "id, from_place_id, to_place_id, status, note, sent_by_name, done_by_name, created_at, done_at"
    open_rows = (
        db.table("stock_moves").select(cols).eq("tenant_id", tenant_id).eq("status", "on_the_way")
        .order("created_at", desc=True).limit(200).execute()
    ).data or []
    done_rows = (
        db.table("stock_moves").select(cols).eq("tenant_id", tenant_id).neq("status", "on_the_way")
        .gte("done_at", start).order("done_at", desc=True).limit(100).execute()
    ).data or []
    moves = open_rows + done_rows
    if not moves:
        return []
    ids = [m["id"] for m in moves]
    lines = (
        db.table("stock_move_lines").select("move_id, catalog_item_id, variant_id, quantity")
        .eq("tenant_id", tenant_id).in_("move_id", ids).limit(5000).execute()
    ).data or []
    names = _line_names(db, tenant_id, lines)
    by_move: dict[str, list[dict]] = {}
    for li in lines:
        by_move.setdefault(li["move_id"], []).append({
            "name": names.get(li.get("variant_id") or li["catalog_item_id"], "Removed item"),
            "quantity": li["quantity"],
        })
    return [{**m, "lines": by_move.get(m["id"], []), "pieces": sum(li["quantity"] for li in by_move.get(m["id"], []))}
            for m in moves]


def _line_names(db, tenant_id: str, lines: list[dict]) -> dict[str, str]:
    item_ids = list({li["catalog_item_id"] for li in lines})
    variant_ids = list({li["variant_id"] for li in lines if li.get("variant_id")})
    items = {r["id"]: r["name"] for r in (
        db.table("catalog_items").select("id, name").eq("tenant_id", tenant_id).in_("id", item_ids).execute()
    ).data or []} if item_ids else {}
    out = dict(items)
    if variant_ids:
        for v in (
            db.table("catalog_item_variants").select("id, catalog_item_id, size, colour").eq("tenant_id", tenant_id)
            .in_("id", variant_ids).execute()
        ).data or []:
            label = " · ".join(x for x in (v.get("colour"), v.get("size")) if x)
            out[v["id"]] = f"{items.get(v['catalog_item_id'], 'Item')} · {label}" if label else items.get(v["catalog_item_id"], "Item")
    return out


def _clean_move_lines(db, tenant_id: str, raw) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise StockPlaceError("Add at least one item to move.")
    merged: dict[tuple[str, str | None], int] = {}
    for li in raw[:MAX_LINES]:
        if not isinstance(li, dict):
            continue
        item, variant = li.get("item_id"), li.get("variant_id") or None
        try:
            qty = int(li.get("quantity"))
        except (TypeError, ValueError):
            raise StockPlaceError("Each quantity must be a whole number.")
        if not (isinstance(item, str) and _UUID.fullmatch(item)) or (variant and not (isinstance(variant, str) and _UUID.fullmatch(variant))):
            raise StockPlaceError("Pick the items again: one of them isn't in your catalogue.")
        if qty < 1:
            raise StockPlaceError("Each quantity must be at least 1.")
        merged[(item, variant)] = merged.get((item, variant), 0) + qty
    if not merged:
        raise StockPlaceError("Add at least one item to move.")
    known = {r["id"] for r in (
        db.table("catalog_items").select("id").eq("tenant_id", tenant_id).in_("id", list({k[0] for k in merged})).execute()
    ).data or []}
    variants = [k[1] for k in merged if k[1]]
    known_v = {(r["catalog_item_id"], r["id"]) for r in (
        db.table("catalog_item_variants").select("id, catalog_item_id").eq("tenant_id", tenant_id).in_("id", variants).execute()
    ).data or []} if variants else set()
    for item, variant in merged:
        if item not in known or (variant and (item, variant) not in known_v):
            raise StockPlaceError("Pick the items again: one of them isn't in your catalogue.")
    return [{"item": i, "variant": v, "qty": min(q, 100000)} for (i, v), q in merged.items()]


def send_move(db, tenant_id: str, payload: dict, *, user_id: str | None, user_name: str | None) -> dict:
    rows = {p["id"]: p for p in places(db, tenant_id)}
    src, dst = payload.get("from_place_id"), payload.get("to_place_id")
    if src not in rows or dst not in rows:
        raise StockPlaceError("Pick both places again.")
    if src == dst:
        raise StockPlaceError("Pick two different places.")
    lines = _clean_move_lines(db, tenant_id, payload.get("lines"))
    try:
        move_id = db.rpc("send_stock_move", {
            "p_tenant_id": tenant_id, "p_from": src, "p_to": dst, "p_lines": lines,
            "p_note": _one_line(payload.get("note"), NOTE_MAX) or None, "p_user": user_id, "p_user_name": user_name,
        }).execute().data
    except Exception as e:
        short = re.search(r"stock_move_short:([0-9a-f-]{36})", str(e))
        if short:
            name = _line_names(db, tenant_id, [{"catalog_item_id": short.group(1), "variant_id": short.group(1)}])
            what = name.get(short.group(1)) or "One of the items"
            raise StockPlaceError(f"{rows[src]['name']} doesn't have that many of {what}. Check the quantity.")
        raise
    return {"id": move_id}


def finish_move(db, tenant_id: str, move_id: str, *, received: bool, user_id: str | None, user_name: str | None) -> bool:
    """Received or Cancel. False when the move was already received or cancelled (by anyone)."""
    if not _UUID.fullmatch(str(move_id)):
        return False
    try:
        return bool(db.rpc("finish_stock_move", {
            "p_tenant_id": tenant_id, "p_move": move_id, "p_received": received, "p_user": user_id,
            "p_user_name": user_name,
        }).execute().data)
    except Exception as e:
        if "stock_move_short" in str(e):  # cancel: the sending place's stock can't go back (it can always)
            raise StockPlaceError("That move can't be undone now.")
        raise


# ── what the AI and bills need ───────────────────────────────────────────────


def online_first_place(db, tenant_id: str) -> str | None:
    """Where online / AI orders start taking stock (None = the bill place, the database default)."""
    try:
        rows = places(db, tenant_id, create=False)
    except Exception:
        logger.warning("Couldn't read stock places for tenant %s", tenant_id)
        return None
    place = online_place(rows)
    home = bill_place(rows)
    return place["id"] if place and home and place["id"] != home["id"] else None


def elsewhere_notes(db, tenant_id: str, item_ids: list[str]) -> dict[str, dict]:
    """For the AI: lines (item or size/colour id) with stock, but none where online orders are packed.
    {line id: {"place": "Gandhipuram godown", "ready": "ready in 1 day"}}. Empty with one place."""
    if not item_ids:
        return {}
    rows = places(db, tenant_id, create=False)
    if len(rows) < 2:
        return {}
    home = online_place(rows)
    names = {p["id"]: p for p in rows}
    have: dict[str, dict[str, int]] = {}
    for lv in (
        db.table("stock_levels").select("catalog_item_id, variant_id, place_id, quantity")
        .eq("tenant_id", tenant_id).in_("catalog_item_id", item_ids).gt("quantity", 0).limit(5000).execute()
    ).data or []:
        key = lv.get("variant_id") or lv["catalog_item_id"]
        have.setdefault(key, {})[lv["place_id"]] = have.get(key, {}).get(lv["place_id"], 0) + int(lv["quantity"])
        if lv.get("variant_id"):  # the item as a whole, too
            item = have.setdefault(lv["catalog_item_id"], {})
            item[lv["place_id"]] = item.get(lv["place_id"], 0) + int(lv["quantity"])
    out: dict[str, dict] = {}
    for key, per in have.items():
        if per.get(home["id"], 0) > 0:
            continue
        where = max((q, p) for p, q in per.items() if p in names)[1] if any(p in names for p in per) else None
        if where:
            out[key] = {"place": names[where]["name"], "ready": names[where].get("ready_note") or DEFAULT_READY}
    return out
