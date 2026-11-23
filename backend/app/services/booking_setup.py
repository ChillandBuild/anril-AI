"""Bookings setup (v9.2 #19): the rules, the services, the columns (staff / chairs) and their leave.

Plain reads and writes with validation. Nothing here knows about slots or customers (that is
services/bookings.py). Services are also catalogue items, so an advance or "Came" can make a real order.
"""
from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

HOLD_MINUTES = 15
STEP_MIN = 15
LIVE = ("held", "booked", "came")

DEFAULT_RULES = {
    "link_on": True,
    "days_ahead": 14,
    "min_notice_min": 60,
    "cancel_cutoff_min": 180,
    "one_per_day": True,
    "no_show_limit": 2,
}
RULE_LIMITS = {
    "days_ahead": (1, 90),
    "min_notice_min": (0, 2880),
    "cancel_cutoff_min": (0, 2880),
    "no_show_limit": (1, 10),
}
KINDS = ("person", "chair", "room")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class BookingError(Exception):
    """Plain-words reason; safe to show to the person."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── hours ───────────────────────────────────────────────────────────────────

def to_minutes(value, *, end: bool = False) -> int | None:
    """'10:30' -> 630. With end=True, '24:00' (midnight, the end of the day) is also accepted -> 1440."""
    text = str(value or "").strip()
    if end and text == "24:00":
        return 1440
    m = _HHMM.match(text)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def normalize_hours(hours) -> dict:
    """Validated hours: {"0".."6": [["10:00","13:00"], ...]} (0 = Monday), at most 2 blocks a day,
    each end after its start, blocks in order and not overlapping. Empty days are left out."""
    if hours in (None, ""):
        return {}
    if not isinstance(hours, dict):
        raise BookingError("Working hours are not in the right form")
    out: dict[str, list[list[str]]] = {}
    for key, blocks in hours.items():
        if str(key) not in {"0", "1", "2", "3", "4", "5", "6"}:
            raise BookingError("Working hours can only be for Monday to Sunday")
        if not blocks:
            continue
        if not isinstance(blocks, (list, tuple)) or len(blocks) > 2:
            raise BookingError("Use at most 2 time blocks a day")
        parsed = []
        for block in blocks:
            if not isinstance(block, (list, tuple)) or len(block) != 2:
                raise BookingError("Each time block needs a start and an end")
            a, b = to_minutes(block[0]), to_minutes(block[1], end=True)
            if a is None or b is None:
                raise BookingError("Times must look like 10:00")
            if b <= a:
                raise BookingError("A time block must end after it starts")
            parsed.append((a, b))
        parsed.sort()
        if len(parsed) == 2 and parsed[1][0] < parsed[0][1]:
            raise BookingError("Time blocks on one day cannot overlap")
        out[str(key)] = [[f"{a // 60:02d}:{a % 60:02d}", f"{b // 60:02d}:{b % 60:02d}"] for a, b in parsed]
    return out


def hours_minutes(hours) -> dict[int, list[tuple[int, int]]]:
    """Lenient read of stored hours -> {weekday: [(start_min, end_min)]}; bad blocks are skipped."""
    out: dict[int, list[tuple[int, int]]] = {}
    if not isinstance(hours, dict):
        return out
    for key, blocks in hours.items():
        try:
            day = int(key)
        except (TypeError, ValueError):
            continue
        if day not in range(7) or not isinstance(blocks, (list, tuple)):
            continue
        got = []
        for block in blocks[:2]:
            if isinstance(block, (list, tuple)) and len(block) == 2:
                a, b = to_minutes(block[0]), to_minutes(block[1], end=True)
                if a is not None and b is not None and b > a:
                    got.append((a, b))
        if got:
            out[day] = sorted(got)
    return out


# ── settings ────────────────────────────────────────────────────────────────

def _new_token() -> str:
    return secrets.token_urlsafe(24)  # 32 URL-safe characters


def get_settings(db, tenant_id: str, *, create: bool = False) -> dict:
    """The rules for this client (defaults when no row). create=True makes the row, with a fresh link token."""
    rows = db.table("booking_settings").select("*").eq("tenant_id", tenant_id).limit(1).execute().data or []
    if rows:
        return {**DEFAULT_RULES, **rows[0]}
    base = {**DEFAULT_RULES, "tenant_id": tenant_id, "link_token": None}
    if not create:
        return base
    try:
        db.table("booking_settings").insert({"tenant_id": tenant_id, "link_token": _new_token()}).execute()
    except Exception as e:  # another request made it first
        logger.info("booking_settings insert raced for %s: %s", tenant_id, e)
    rows = db.table("booking_settings").select("*").eq("tenant_id", tenant_id).limit(1).execute().data or []
    return {**DEFAULT_RULES, **rows[0]} if rows else base


def public_settings(settings: dict) -> dict:
    return {k: settings.get(k, DEFAULT_RULES[k]) for k in DEFAULT_RULES}


def update_settings(db, tenant_id: str, data: dict) -> dict:
    get_settings(db, tenant_id, create=True)
    patch: dict = {}
    for key, (low, high) in RULE_LIMITS.items():
        if data.get(key) is None:
            continue
        try:
            value = int(data[key])
        except (TypeError, ValueError):
            raise BookingError("Numbers only, please")
        if not low <= value <= high:
            raise BookingError(f"Pick a number from {low} to {high}")
        patch[key] = value
    for key in ("link_on", "one_per_day"):
        if data.get(key) is not None:
            patch[key] = bool(data[key])
    if patch:
        patch["updated_at"] = now_utc().isoformat()
        db.table("booking_settings").update(patch).eq("tenant_id", tenant_id).execute()
    return get_settings(db, tenant_id)


def new_link_token(db, tenant_id: str) -> dict:
    get_settings(db, tenant_id, create=True)
    db.table("booking_settings").update(
        {"link_token": _new_token(), "updated_at": now_utc().isoformat()}
    ).eq("tenant_id", tenant_id).execute()
    return get_settings(db, tenant_id)


def settings_by_token(db, token: str) -> dict | None:
    rows = db.table("booking_settings").select("*").eq("link_token", token).limit(1).execute().data or []
    return {**DEFAULT_RULES, **rows[0]} if rows else None


# ── services ────────────────────────────────────────────────────────────────

def _links(db, tenant_id: str) -> list[dict]:
    return db.table("booking_service_resources").select("service_id, resource_id").eq("tenant_id", tenant_id).execute().data or []


def list_services(db, tenant_id: str, *, active_only: bool = False) -> list[dict]:
    q = db.table("booking_services").select("*").eq("tenant_id", tenant_id)
    if active_only:
        q = q.eq("active", True)
    rows = q.order("sort").execute().data or []
    links = _links(db, tenant_id)
    for r in rows:
        r["resource_ids"] = [l["resource_id"] for l in links if l["service_id"] == r["id"]]
    return rows


def is_uuid(value) -> bool:
    """True for a well-formed uuid. A bad id is "not found", never a database error (a 500)."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def get_service(db, tenant_id: str, service_id: str, *, active_only: bool = False) -> dict | None:
    if not is_uuid(service_id):
        return None
    q = db.table("booking_services").select("*").eq("tenant_id", tenant_id).eq("id", service_id)
    if active_only:
        q = q.eq("active", True)
    rows = q.limit(1).execute().data or []
    return rows[0] if rows else None


def _int(value, label: str, low: int, high: int | None = None) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise BookingError(f"{label}: numbers only, please")
    if n < low or (high is not None and n > high):
        raise BookingError(f"{label}: pick a number from {low} to {high}" if high is not None else f"{label} cannot be less than {low}")
    return n


def _clean_service(data: dict, *, existing: dict | None) -> dict:
    out: dict = {}
    if "name" in data or existing is None:
        name = str(data.get("name") or "").strip()
        if not 1 <= len(name) <= 120:
            raise BookingError("Give the service a name (up to 120 letters)")
        out["name"] = name
    if "duration_min" in data or existing is None:
        out["duration_min"] = _int(data.get("duration_min"), "Minutes", 5, 600)
    if "price_paise" in data or existing is None:
        out["price_paise"] = _int(data.get("price_paise") or 0, "Price", 0)
    if "advance_paise" in data or existing is None:
        out["advance_paise"] = _int(data.get("advance_paise") or 0, "Advance", 0)
    if "gap_after_min" in data or existing is None:
        out["gap_after_min"] = _int(data.get("gap_after_min") or 0, "Gap after", 0, 240)
    if "active" in data and data["active"] is not None:
        out["active"] = bool(data["active"])
    price = out.get("price_paise", (existing or {}).get("price_paise", 0))
    advance = out.get("advance_paise", (existing or {}).get("advance_paise", 0))
    if advance > price:
        raise BookingError("The advance cannot be more than the price")
    return out


def with_catalog_price(db, tenant_id: str, service: dict) -> dict:
    """The service with the price its catalogue item has right now (that is what the order bills), and the
    advance capped at that price. A service with no catalogue item keeps its own price."""
    return with_catalog_prices(db, tenant_id, [service])[0]


def with_catalog_prices(db, tenant_id: str, services: list[dict]) -> list[dict]:
    ids = sorted({s["catalog_item_id"] for s in services if s.get("catalog_item_id")})
    prices: dict[str, int] = {}
    if ids:
        try:
            rows = db.table("catalog_items").select("id, price_paise").eq("tenant_id", tenant_id).in_("id", ids).execute().data or []
            prices = {r["id"]: int(r["price_paise"]) for r in rows if r.get("price_paise") is not None}
        except Exception as e:
            logger.warning("booking: catalogue prices unavailable: %s", e)
    out = []
    for svc in services:
        price = prices.get(svc.get("catalog_item_id"))
        if price is None:
            out.append(svc)
            continue
        advance = int(svc.get("advance_paise") or 0)
        out.append({**svc, "price_paise": price, "advance_paise": min(advance, price) if price > 0 else advance})
    return out


def _embed_item(db, tenant_id: str, item_id: str | None, name: str) -> None:
    """Index the catalogue item for search, like routes/catalog.py does. Best effort, never raises."""
    if not item_id:
        return
    try:
        import asyncio
        from app.services.catalog_retrieval import embed_and_store_catalog_item
        asyncio.run(embed_and_store_catalog_item(db, tenant_id, item_id, name, "service", None, {}))
    except Exception as e:
        logger.info("booking service: could not index catalogue item %s: %s", item_id, e)


def _catalog_item(db, tenant_id: str, existing_id: str | None, name: str, price_paise: int) -> str | None:
    """Each service is a catalogue item (item_type 'service'), so orders and bills work as usual.
    Renaming touches only the name and price; 'ready' is set only when the item is first made."""
    try:
        if existing_id:
            db.table("catalog_items").update({"name": name, "price_paise": price_paise}) \
                .eq("id", existing_id).eq("tenant_id", tenant_id).execute()
            return existing_id
        made = db.table("catalog_items").insert({"name": name, "item_type": "service", "price_paise": price_paise,
                                                 "status": "ready", "tenant_id": tenant_id}).execute().data or []
        return made[0]["id"] if made else None
    except Exception as e:
        logger.warning("booking service: catalogue item failed: %s", e)
        raise BookingError("Could not save this service in your catalogue. Please try again")


def _clean_ids(db, tenant_id: str, table: str, ids, message: str) -> list[str]:
    """Distinct ids, every one of them this business's row in `table`; BookingError before anything is written."""
    ids = list(dict.fromkeys(str(i) for i in (ids or [])))
    if any(not is_uuid(i) for i in ids):
        raise BookingError(message)
    if ids:
        valid = {r["id"] for r in db.table(table).select("id").eq("tenant_id", tenant_id).execute().data or []}
        if any(i not in valid for i in ids):
            raise BookingError(message)
    return ids


def _set_links(db, tenant_id: str, *, fixed: str, fixed_value: str, other: str, ids: list[str]) -> None:
    """Make the links for one side exactly `ids`: add the new ones first, then remove the rest, so a failure
    half-way never leaves the service or column with no links at all."""
    current = {l[other] for l in db.table("booking_service_resources").select("service_id, resource_id")
               .eq("tenant_id", tenant_id).eq(fixed, fixed_value).execute().data or []}
    want = set(ids)
    add = [i for i in ids if i not in current]
    if add:
        db.table("booking_service_resources").insert(
            [{fixed: fixed_value, other: i, "tenant_id": tenant_id} for i in add]).execute()
    for i in current - want:
        db.table("booking_service_resources").delete().eq(fixed, fixed_value).eq(other, i).eq("tenant_id", tenant_id).execute()


def _set_service_resources(db, tenant_id: str, *, service_id: str | None = None, resource_id: str | None = None,
                           ids: list[str]) -> None:
    if service_id:
        ids = _clean_ids(db, tenant_id, "booking_resources", ids, "One of the staff / chairs was not found")
        _set_links(db, tenant_id, fixed="service_id", fixed_value=service_id, other="resource_id", ids=ids)
    elif resource_id:
        ids = _clean_ids(db, tenant_id, "booking_services", ids, "One of the services was not found")
        _set_links(db, tenant_id, fixed="resource_id", fixed_value=resource_id, other="service_id", ids=ids)


def create_service(db, tenant_id: str, data: dict) -> dict:
    clean = _clean_service(data, existing=None)
    _clean_ids(db, tenant_id, "booking_resources", data.get("resource_ids"), "One of the staff / chairs was not found")
    item_id = _catalog_item(db, tenant_id, None, clean["name"], clean["price_paise"])
    _embed_item(db, tenant_id, item_id, clean["name"])
    count = len(db.table("booking_services").select("id").eq("tenant_id", tenant_id).execute().data or [])
    row = db.table("booking_services").insert(
        {**clean, "tenant_id": tenant_id, "catalog_item_id": item_id, "sort": count}).execute().data[0]
    _set_service_resources(db, tenant_id, service_id=row["id"], ids=data.get("resource_ids") or [])
    return get_service_shaped(db, tenant_id, row["id"])


def update_service(db, tenant_id: str, service_id: str, data: dict) -> dict:
    existing = get_service(db, tenant_id, service_id)
    if not existing:
        raise BookingError("Service not found", 404)
    clean = _clean_service(data, existing=existing)
    if data.get("resource_ids") is not None:
        _clean_ids(db, tenant_id, "booking_resources", data["resource_ids"], "One of the staff / chairs was not found")
    merged = {**existing, **clean}
    if {"name", "price_paise"} & clean.keys() or not existing.get("catalog_item_id"):
        clean["catalog_item_id"] = _catalog_item(db, tenant_id, existing.get("catalog_item_id"),
                                                 merged["name"], int(merged["price_paise"]))
        _embed_item(db, tenant_id, clean["catalog_item_id"], merged["name"])
    if clean:
        clean["updated_at"] = now_utc().isoformat()
        db.table("booking_services").update(clean).eq("id", service_id).eq("tenant_id", tenant_id).execute()
    if data.get("resource_ids") is not None:
        _set_service_resources(db, tenant_id, service_id=service_id, ids=data["resource_ids"])
    return get_service_shaped(db, tenant_id, service_id)


def deactivate_service(db, tenant_id: str, service_id: str) -> dict:
    return update_service(db, tenant_id, service_id, {"active": False})


def get_service_shaped(db, tenant_id: str, service_id: str) -> dict:
    row = get_service(db, tenant_id, service_id) or {}
    row["resource_ids"] = [l["resource_id"] for l in _links(db, tenant_id) if l["service_id"] == service_id]
    return row


# ── resources (columns) ─────────────────────────────────────────────────────

def list_resources(db, tenant_id: str, *, active_only: bool = False) -> list[dict]:
    q = db.table("booking_resources").select("*").eq("tenant_id", tenant_id)
    if active_only:
        q = q.eq("active", True)
    rows = q.order("sort").execute().data or []
    links = _links(db, tenant_id)
    for r in rows:
        r["service_ids"] = [l["service_id"] for l in links if l["resource_id"] == r["id"]]
    return rows


def get_resource(db, tenant_id: str, resource_id: str) -> dict | None:
    if not is_uuid(resource_id):
        return None
    rows = db.table("booking_resources").select("*").eq("tenant_id", tenant_id).eq("id", resource_id).limit(1).execute().data or []
    return rows[0] if rows else None


def _check_user(db, tenant_id: str, user_id: str | None) -> str | None:
    if not user_id:
        return None
    rows = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("user_id", user_id).limit(1).execute().data or []
    if not rows:
        raise BookingError("That person is not on your team")
    return user_id


def _clean_resource(db, tenant_id: str, data: dict, *, existing: dict | None) -> dict:
    out: dict = {}
    if "name" in data or existing is None:
        name = str(data.get("name") or "").strip()
        if not 1 <= len(name) <= 80:
            raise BookingError("Give this a name (up to 80 letters)")
        out["name"] = name
    if "kind" in data or existing is None:
        kind = data.get("kind") or "person"
        if kind not in KINDS:
            raise BookingError("Pick person, chair or room")
        out["kind"] = kind
    if "user_id" in data:
        out["user_id"] = _check_user(db, tenant_id, data.get("user_id"))
    if "hours" in data or existing is None:
        out["hours"] = normalize_hours(data.get("hours"))
    if "active" in data and data["active"] is not None:
        out["active"] = bool(data["active"])
    if "sort" in data and data["sort"] is not None:
        out["sort"] = _int(data["sort"], "Order", 0, 10000)
    return out


def _unique_user(e: Exception) -> BookingError | None:
    if "uq_booking_resources_user" in str(e) or "23505" in str(e):
        return BookingError("That person already has a column")
    return None


def create_resource(db, tenant_id: str, data: dict) -> dict:
    clean = _clean_resource(db, tenant_id, data, existing=None)
    _clean_ids(db, tenant_id, "booking_services", data.get("service_ids"), "One of the services was not found")
    clean.setdefault("sort", len(db.table("booking_resources").select("id").eq("tenant_id", tenant_id).execute().data or []))
    try:
        row = db.table("booking_resources").insert({**clean, "tenant_id": tenant_id}).execute().data[0]
    except Exception as e:
        raise _unique_user(e) or e
    _set_service_resources(db, tenant_id, resource_id=row["id"], ids=data.get("service_ids") or [])
    return get_resource_shaped(db, tenant_id, row["id"])


def update_resource(db, tenant_id: str, resource_id: str, data: dict) -> dict:
    existing = get_resource(db, tenant_id, resource_id)
    if not existing:
        raise BookingError("Not found", 404)
    clean = _clean_resource(db, tenant_id, data, existing=existing)
    if data.get("service_ids") is not None:
        _clean_ids(db, tenant_id, "booking_services", data["service_ids"], "One of the services was not found")
    if clean.get("active") is False and existing.get("active", True):
        _refuse_if_upcoming(db, tenant_id, resource_id)
    if clean:
        clean["updated_at"] = now_utc().isoformat()
        try:
            db.table("booking_resources").update(clean).eq("id", resource_id).eq("tenant_id", tenant_id).execute()
        except Exception as e:
            raise _unique_user(e) or e
    if data.get("service_ids") is not None:
        _set_service_resources(db, tenant_id, resource_id=resource_id, ids=data["service_ids"])
    return get_resource_shaped(db, tenant_id, resource_id)


def deactivate_resource(db, tenant_id: str, resource_id: str) -> dict:
    return update_resource(db, tenant_id, resource_id, {"active": False})


def _refuse_if_upcoming(db, tenant_id: str, resource_id: str) -> None:
    rows = (
        db.table("bookings").select("id").eq("tenant_id", tenant_id).eq("resource_id", resource_id)
        .in_("status", ["held", "booked"]).gte("start_at", now_utc().isoformat()).limit(50).execute().data or []
    )
    if rows:
        n = len(rows)
        raise BookingError(f"{n} upcoming booking{'s' if n != 1 else ''} on this column. Move or cancel them first")


def get_resource_shaped(db, tenant_id: str, resource_id: str) -> dict:
    row = get_resource(db, tenant_id, resource_id) or {}
    row["service_ids"] = [l["service_id"] for l in _links(db, tenant_id) if l["resource_id"] == resource_id]
    return row


# ── leave ───────────────────────────────────────────────────────────────────

def _day(value, label: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise BookingError(f"{label}: pick a date")


def list_leave(db, tenant_id: str, since: date) -> list[dict]:
    rows = (
        db.table("booking_leave").select("id, resource_id, from_date, to_date, note").eq("tenant_id", tenant_id)
        .gte("to_date", since.isoformat()).order("from_date").execute().data or []
    )
    return rows


def add_leave(db, tenant_id: str, resource_id: str, data: dict, created_by: str | None) -> dict:
    if not get_resource(db, tenant_id, resource_id):
        raise BookingError("Not found", 404)
    start, end = _day(data.get("from_date"), "From"), _day(data.get("to_date") or data.get("from_date"), "To")
    if end < start:
        raise BookingError("The last day cannot be before the first day")
    if (end - start).days > 366:
        raise BookingError("Leave can be at most a year")
    note = (data.get("note") or "").strip()[:200] or None
    row = db.table("booking_leave").insert({
        "tenant_id": tenant_id, "resource_id": resource_id, "from_date": start.isoformat(),
        "to_date": end.isoformat(), "note": note, "created_by": created_by,
    }).execute().data[0]
    affected = (
        db.table("bookings").select("id").eq("tenant_id", tenant_id).eq("resource_id", resource_id)
        .in_("status", ["held", "booked"]).gte("booking_date", start.isoformat()).lte("booking_date", end.isoformat())
        .execute().data or []
    )
    return {"id": row["id"], "resource_id": resource_id, "from_date": row["from_date"], "to_date": row["to_date"],
            "note": row.get("note"), "affected_bookings": len(affected)}


def delete_leave(db, tenant_id: str, leave_id: str) -> None:
    if not is_uuid(leave_id):
        return
    db.table("booking_leave").delete().eq("id", leave_id).eq("tenant_id", tenant_id).execute()


# ── team ────────────────────────────────────────────────────────────────────

def team(db, tenant_id: str) -> list[dict]:
    """Who can be linked to a column. has_view says whether that person's role has bookings.view (the owner
    always does), so the screen can warn when linking someone who could not see their own column."""
    rows = db.table("tenant_users").select("user_id, full_name, role").eq("tenant_id", tenant_id).execute().data or []
    out = []
    for r in rows:
        has_view = r.get("role") == "owner"
        if not has_view:
            try:
                from app.services.rbac import resolve_permissions
                perms = set((resolve_permissions(db, tenant_id, str(r["user_id"]), r.get("role")) or {}).get("permissions") or [])
                has_view = bool(perms & {"bookings.view", "bookings.manage"})
            except Exception as e:
                logger.info("booking team: could not read permissions of %s: %s", r.get("user_id"), e)
        out.append({"user_id": str(r["user_id"]), "name": r.get("full_name") or "Team member", "has_view": has_view})
    return out
