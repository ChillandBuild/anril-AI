"""Bookings engine (v9.2 #19): slot maths, the rules, and create / move / cancel / came / no-show.

Times are stored in UTC; every decision (which day, which hours) is made in Indian time.
The database is the real guard against double booking (bookings_no_overlap, uq_bookings_phone_day,
uq_bookings_number); the checks here give plain-words errors first and map the database's errors second.
Money goes only through services/booking_orders.py.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

from app.services import booking_setup as bsetup
from app.services.booking_setup import BookingError, HOLD_MINUTES, LIVE, STEP_MIN

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
TAKEN = "That time was just taken, pick another"
NOT_FREE = "That time is already taken, pick another"
PHONE_DAY = "This phone already has a booking that day"
SOURCES = ("link", "chat", "phone", "walk_in", "ai")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── time helpers ────────────────────────────────────────────────────────────

def parse_ts(value) -> datetime:
    """An ISO time -> aware UTC. A time with no zone is read as Indian time."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise BookingError("That time is not valid")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def ist_date(dt: datetime) -> date:
    return dt.astimezone(IST).date()


def day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=IST)


def code_for(number) -> str:
    return f"BK-{int(number):04d}"


def parse_day(value, label: str = "date") -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise BookingError(f"Pick a valid {label}")


def floor_step(dt: datetime) -> datetime:
    """The start of the 15-minute slot that contains dt."""
    base = dt.astimezone(IST)
    return base.replace(minute=base.minute - base.minute % STEP_MIN, second=0, microsecond=0).astimezone(timezone.utc)


# ── slot maths (pure) ───────────────────────────────────────────────────────

def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def slots_for_day(resource_hours: dict, service: dict, day: date, *, earliest: datetime,
                  live: list[tuple[datetime, datetime]], on_leave: bool = False) -> list[datetime]:
    """Start times (UTC) on `day` where the service fits one column.

    A slot fits when [start, start + minutes) is inside a working block and [start, start + minutes + gap)
    touches no live booking (a live booking holds its own minutes + gap). Starts are on the 15-minute grid
    and not before `earliest`. `resource_hours` is the stored hours JSON.
    """
    if on_leave:
        return []
    blocks = bsetup.hours_minutes(resource_hours).get(day.weekday(), [])
    dur = int(service["duration_min"])
    gap = int(service.get("gap_after_min") or 0)
    base = day_start(day)
    out: list[datetime] = []
    for b_start, b_end in blocks:
        t = -(-b_start // STEP_MIN) * STEP_MIN
        while t + dur <= b_end:
            start = (base + timedelta(minutes=t)).astimezone(timezone.utc)
            if start >= earliest:
                block_end = start + timedelta(minutes=dur + gap)
                if not any(overlaps(start, block_end, ls, le) for ls, le in live):
                    out.append(start)
            t += STEP_MIN
    return out


def free_ranges(resource_hours: dict, day: date, *, earliest: datetime,
                live: list[tuple[datetime, datetime]], on_leave: bool = False) -> list[tuple[datetime, datetime]]:
    """Open stretches of a column's day (for the staff timeline): working blocks minus live bookings,
    nothing before `earliest`, and nothing shorter than one step."""
    if on_leave:
        return []
    base = day_start(day)
    out: list[tuple[datetime, datetime]] = []
    for b_start, b_end in bsetup.hours_minutes(resource_hours).get(day.weekday(), []):
        pieces = [((base + timedelta(minutes=b_start)).astimezone(timezone.utc),
                   (base + timedelta(minutes=b_end)).astimezone(timezone.utc))]
        for ls, le in sorted(live):
            nxt = []
            for ps, pe in pieces:
                if not overlaps(ps, pe, ls, le):
                    nxt.append((ps, pe))
                    continue
                if ps < ls:
                    nxt.append((ps, ls))
                if le < pe:
                    nxt.append((le, pe))
            pieces = nxt
        for ps, pe in pieces:
            ps = max(ps, earliest)
            if pe - ps >= timedelta(minutes=STEP_MIN):
                out.append((ps, pe))
    return out


# ── who sees which column ───────────────────────────────────────────────────

def can_manage(ctx: dict) -> bool:
    from app.dependencies.tenant import _has_permission
    return _has_permission(ctx, "bookings.manage")


def my_resource_id(ctx: dict, resources: list[dict]) -> str | None:
    uid = ctx.get("user_id")
    if not uid:
        return None
    for r in resources:
        if r.get("user_id") and str(r["user_id"]) == str(uid):
            return r["id"]
    return None


def visible_resources(ctx: dict, resources: list[dict]) -> list[dict]:
    """Managers (and the owner) see every column. Someone linked to a column with only view sees just that
    one. View with no column of their own sees all, read-only."""
    if can_manage(ctx):
        return resources
    mine = my_resource_id(ctx, resources)
    return [r for r in resources if r["id"] == mine] if mine else resources


def only_own_column(ctx: dict, resources: list[dict]) -> str | None:
    """The one column id a view-only linked person is limited to, else None."""
    if can_manage(ctx):
        return None
    return my_resource_id(ctx, resources)


def scoped_columns(db, ctx: dict) -> list[dict]:
    """THE list of active columns this person may see (setup, boards, free times, history, Home, search).
    Who is linked is decided over ALL columns, inactive ones included: someone linked to a column that is
    switched off sees nothing, never everything."""
    everything = bsetup.list_resources(db, ctx["tenant_id"])
    return [r for r in visible_resources(ctx, everything) if r.get("active", True)]


def can_act_on(ctx: dict, resource: dict | None) -> bool:
    """Came / Didn't come: bookings.manage, or the person linked to that column."""
    if can_manage(ctx):
        return True
    return bool(resource and resource.get("user_id") and str(resource["user_id"]) == str(ctx.get("user_id")))


# ── loading what the maths needs ────────────────────────────────────────────

PAGE = 1000


def fetch_all(build) -> list[dict]:
    """Every row of a query, past the 1000-row API cap. build() returns a fresh, ordered query each call
    (order by start_at then id so pages never skip or repeat a row)."""
    out: list[dict] = []
    while True:
        rows = build().range(len(out), len(out) + PAGE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < PAGE:
            return out


def _live_by_resource(db, tenant_id: str, resource_ids: list[str], first: date, last: date,
                      exclude_id: str | None) -> dict[str, list[tuple[datetime, datetime]]]:
    out: dict[str, list[tuple[datetime, datetime]]] = {rid: [] for rid in resource_ids}
    if not resource_ids:
        return out
    rows = fetch_all(lambda: (
        db.table("bookings").select("id, resource_id, start_at, block_end_at, booking_date")
        .eq("tenant_id", tenant_id).in_("resource_id", resource_ids).in_("status", list(LIVE))
        .gte("booking_date", (first - timedelta(days=1)).isoformat()).lte("booking_date", last.isoformat())
        .order("start_at").order("id")
    ))
    for r in rows:
        if exclude_id and r["id"] == exclude_id:
            continue
        out.setdefault(r["resource_id"], []).append((parse_ts(r["start_at"]), parse_ts(r["block_end_at"])))
    return out


def _leave_by_resource(db, tenant_id: str, resource_ids: list[str], first: date, last: date) -> dict[str, list[tuple[date, date]]]:
    out: dict[str, list[tuple[date, date]]] = {rid: [] for rid in resource_ids}
    if not resource_ids:
        return out
    rows = (
        db.table("booking_leave").select("resource_id, from_date, to_date").eq("tenant_id", tenant_id)
        .in_("resource_id", resource_ids).gte("to_date", first.isoformat()).execute().data or []
    )
    for r in rows:
        a, b = date.fromisoformat(str(r["from_date"])[:10]), date.fromisoformat(str(r["to_date"])[:10])
        if a <= last:
            out.setdefault(r["resource_id"], []).append((a, b))
    return out


def window(rules: dict, now: datetime, staff: bool) -> tuple[datetime, date, date]:
    """(earliest start, first day, last day) a slot may be offered.

    Customers: not within min_notice_min, not beyond days_ahead. Staff (phone, walk-in, chat): from the
    current 15-minute slot, up to a year ahead.
    """
    today = ist_date(now)
    if staff:
        return floor_step(now), today, today + timedelta(days=365)
    earliest = now + timedelta(minutes=int(rules.get("min_notice_min") or 0))
    return earliest, today, today + timedelta(days=int(rules.get("days_ahead") or 14))


def free_times(db, tenant_id: str, service: dict, resources: list[dict], days: list[date], rules: dict, *,
               staff: bool, now: datetime | None = None, exclude_booking_id: str | None = None) -> dict[date, list[tuple[datetime, dict]]]:
    """{day: [(start, resource), ...]} for the columns that do `service`, in column order."""
    now = now or _now()
    earliest, first_ok, last_ok = window(rules, now, staff)
    days = [d for d in days if first_ok <= d <= last_ok]
    out: dict[date, list[tuple[datetime, dict]]] = {d: [] for d in days}
    if not days:
        return out
    ids = [r["id"] for r in resources]
    live = _live_by_resource(db, tenant_id, ids, min(days), max(days), exclude_booking_id)
    leave = _leave_by_resource(db, tenant_id, ids, min(days), max(days))
    for d in days:
        for r in resources:
            off = any(a <= d <= b for a, b in leave.get(r["id"], []))
            for start in slots_for_day(r.get("hours") or {}, service, d, earliest=earliest,
                                       live=live.get(r["id"], []), on_leave=off):
                out[d].append((start, r))
    return out


def resources_for(db, tenant_id: str, service: dict, resource_id: str | None, allowed: list[dict] | None = None) -> list[dict]:
    """Active columns that do this service; resource_id None/'any' = all of them, else just that one."""
    pool = allowed if allowed is not None else bsetup.list_resources(db, tenant_id, active_only=True)
    can = set(service.get("resource_ids") or [])
    pool = [r for r in pool if r.get("active", True) and r["id"] in can]
    if resource_id and resource_id != "any":
        pool = [r for r in pool if r["id"] == resource_id] if bsetup.is_uuid(resource_id) else []
    return pool


def times_for_day(db, tenant_id: str, service: dict, resource_id: str | None, day: date, rules: dict, *,
                  staff: bool, allowed: list[dict] | None = None, now: datetime | None = None,
                  exclude_booking_id: str | None = None) -> list[dict]:
    """[{start_at, resource_id, resource_name}], earliest first; with 'any' each time lists its first free column."""
    pool = resources_for(db, tenant_id, service, resource_id, allowed)
    found = free_times(db, tenant_id, service, pool, [day], rules, staff=staff, now=now,
                       exclude_booking_id=exclude_booking_id).get(day, [])
    seen: dict[datetime, dict] = {}
    for start, r in found:
        seen.setdefault(start, r)
    return [{"start_at": iso(s), "resource_id": r["id"], "resource_name": r["name"]} for s, r in sorted(seen.items())]


def days_with_times(db, tenant_id: str, service: dict, resource_id: str | None, rules: dict, *, staff: bool,
                    allowed: list[dict] | None = None, now: datetime | None = None,
                    exclude_booking_id: str | None = None) -> list[str]:
    now = now or _now()
    _, first, last = window(rules, now, staff)
    if staff:
        last = first + timedelta(days=int(rules.get("days_ahead") or 14))
    pool = resources_for(db, tenant_id, service, resource_id, allowed)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    got = free_times(db, tenant_id, service, pool, days, rules, staff=staff, now=now,
                     exclude_booking_id=exclude_booking_id)
    return [d.isoformat() for d in days if got.get(d)]


# ── how a booking looks to the screens ──────────────────────────────────────

def _paid(db, tenant_id: str, row: dict) -> bool:
    if int(row.get("advance_paise") or 0) <= 0 or not row.get("deal_id"):
        return False
    try:
        from app.services import booking_orders
        return bool(booking_orders.advance_paid(tenant_id, row, db))
    except Exception as e:
        logger.warning("booking %s: advance_paid failed: %s", row.get("id"), e)
        return False


def shape_many(db, tenant_id: str, rows: list[dict], services: dict[str, dict], *, show_money: bool) -> list[dict]:
    """Bookings for the staff screens. Money (advance_paise) only for people who may see money.
    advance_paid comes from ONE deals read for the whole list."""
    paid_map: dict[str, bool] = {}
    need = [r for r in rows if int(r.get("advance_paise") or 0) > 0 and r.get("deal_id")]
    if need:
        try:
            from app.services import booking_orders
            paid_map = booking_orders.advance_paid_many(tenant_id, need, db)
        except Exception as e:
            logger.warning("booking: advance_paid_many failed: %s", e)
    out_rows = []
    for row in rows:
        svc = services.get(row.get("service_id") or "") or {}
        advance = int(row.get("advance_paise") or 0)
        out = {
            "id": row["id"], "number": row["number"], "code": code_for(row["number"]), "status": row["status"],
            "source": row.get("source"), "start_at": row["start_at"], "end_at": row["end_at"],
            "block_end_at": row["block_end_at"], "service_id": row.get("service_id"),
            "service_name": svc.get("name"), "resource_id": row.get("resource_id"),
            "customer_name": row.get("customer_name"), "phone": row.get("phone"), "lead_id": row.get("lead_id"),
            "phone_checked": bool(row.get("phone_checked")), "advance_needed": advance > 0,
            "advance_paid": bool(paid_map.get(row["id"], False)), "deal_id": row.get("deal_id"),
            "confirmed_at": row.get("confirmed_at"),
            "call_now": bool(row.get("call_now_at")) and not row.get("confirmed_at") and row.get("status") == "booked",
            "note": row.get("note"),
        }
        if show_money:
            out["advance_paise"] = advance
        out_rows.append(out)
    return out_rows


def shape(db, tenant_id: str, row: dict, services: dict[str, dict], *, show_money: bool) -> dict:
    return shape_many(db, tenant_id, [row], services, show_money=show_money)[0]


def service_map(db, tenant_id: str) -> dict[str, dict]:
    return {s["id"]: s for s in bsetup.list_services(db, tenant_id)}


def bookings_on(db, tenant_id: str, first: date, last: date, resource_ids: list[str] | None = None,
                statuses: tuple[str, ...] = ("held", "booked", "came", "no_show"), *, spill: bool = False) -> list[dict]:
    """Bookings starting on first..last (IST days), earliest first. spill=True also brings in a live booking
    from the day before whose gap-after runs into `first`, so the board shows the column as busy."""
    if resource_ids is not None and not resource_ids:
        return []

    def build():
        q = (
            db.table("bookings").select("*").eq("tenant_id", tenant_id)
            .gte("booking_date", first.isoformat()).lte("booking_date", last.isoformat()).in_("status", list(statuses))
        )
        if resource_ids is not None:
            q = q.in_("resource_id", resource_ids)
        return q.order("start_at").order("id")

    rows = fetch_all(build)
    if spill:
        edge = day_start(first).astimezone(timezone.utc)
        prev = (
            db.table("bookings").select("*").eq("tenant_id", tenant_id)
            .eq("booking_date", (first - timedelta(days=1)).isoformat()).in_("status", list(LIVE))
        )
        if resource_ids is not None:
            prev = prev.in_("resource_id", resource_ids)
        rows = [r for r in (prev.execute().data or []) if parse_ts(r["block_end_at"]) > edge] + rows
    return sorted(rows, key=lambda r: (r["start_at"], r["id"]))


# ── database errors -> plain words ──────────────────────────────────────────

def violation(e: Exception) -> str | None:
    """'overlap' | 'phone_day' | 'number' | 'unique' (some other 23505) | None."""
    text = " ".join(str(x) for x in (e, getattr(e, "message", ""), getattr(e, "details", ""), getattr(e, "code", "")))
    if "23P01" in text or "bookings_no_overlap" in text:
        return "overlap"
    if "uq_bookings_phone_day" in text:
        return "phone_day"
    if "uq_bookings_number" in text:
        return "number"
    if "23505" in text:
        return "unique"
    return None


def _taken_error() -> BookingError:
    return BookingError(TAKEN, 409)


PUBLIC_CANT_BOOK = "This number can't book this time. Please pick another day or call the business."
TOO_MANY_HOLDS = "Too many bookings waiting — please confirm one on WhatsApp first"
MAX_UPCOMING_PER_PHONE = 2
MAX_HOLDS_PER_BUSINESS = 20
MAX_CUSTOMER_MOVES = 3


def _phone_day_error(public: bool = False) -> BookingError:
    """Staff get the specific words. The customer's link never says whose booking is in the way."""
    return BookingError(PUBLIC_CANT_BOOK if public else PHONE_DAY, 409)


def _phone_has_live(db, tenant_id: str, phone: str, day: date, exclude_id: str | None = None) -> bool:
    rows = (
        db.table("bookings").select("id").eq("tenant_id", tenant_id).eq("phone", phone)
        .eq("booking_date", day.isoformat()).in_("status", list(LIVE)).execute().data or []
    )
    return any(r["id"] != exclude_id for r in rows)


def _next_number(db, tenant_id: str) -> int:
    rows = db.table("bookings").select("number").eq("tenant_id", tenant_id).order("number", desc=True).limit(1).execute().data or []
    return int(rows[0]["number"]) + 1 if rows else 1


# ── the customer's lead (Inbound leads "Result" + the 8 PM unmarked-bookings alert) ──

def sync_lead_mirror(db, tenant_id: str, lead_id: str | None, *, set_booked_at: bool = False) -> None:
    """leads.booked_at is set once on create/move; leads.booked_for is the next live booking's start
    (null when none), recomputed by booking_messages.recompute_lead_mirror. Never touches lost_* or
    converted_at. Best effort."""
    if not lead_id:
        return
    try:
        if set_booked_at:
            lead = db.table("leads").select("booked_at").eq("id", lead_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
            if lead and not lead[0].get("booked_at"):
                db.table("leads").update({"booked_at": iso(_now())}).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
        from app.services.booking_messages import recompute_lead_mirror
        recompute_lead_mirror(db, tenant_id, lead_id)
    except Exception as e:
        logger.warning("booking lead mirror failed for lead %s: %s", lead_id, e)


# ── the bell ────────────────────────────────────────────────────────────────

def when_text(start: datetime) -> str:
    local = start.astimezone(IST)
    hour = local.hour % 12 or 12
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')}, {hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"


def notify(db, tenant_id: str, kind: str, booking: dict, *, service_name: str | None, resource: dict | None) -> None:
    """Bell: booking_new / booking_cancelled, through booking_messages.ring_bell. Never raises."""
    try:
        from app.services.booking_messages import ring_bell
        who = booking.get("customer_name") or booking.get("phone") or "A customer"
        titles = {"booking_new": "New booking", "booking_cancelled": "Booking cancelled"}
        text = f"{who}, {service_name or 'booking'}, {when_text(parse_ts(booking['start_at']))}"
        ring_bell(db, tenant_id, {**booking, "resource_user_id": (resource or {}).get("user_id")},
                  kind, titles.get(kind, "Booking"), text)
    except Exception as e:
        logger.warning("booking bell failed: %s", e)


async def _message(name: str, db, tenant_id: str, booking_id: str, **kwargs) -> None:
    """B2's WhatsApp messages (booking_messages.send_*). Never fails the action."""
    try:
        from app.services import booking_messages
        await getattr(booking_messages, name)(db, tenant_id, booking_id, **kwargs)
    except Exception as e:
        logger.warning("booking message %s failed for %s: %s", name, booking_id, e)


# ── create ──────────────────────────────────────────────────────────────────

def _no_shows(db, tenant_id: str, phone: str) -> int:
    rows = db.table("bookings").select("id").eq("tenant_id", tenant_id).eq("phone", phone).eq("status", "no_show").execute().data or []
    return len(rows)


def history(db, tenant_id: str, phone: str, rules: dict, resource_ids: list[str] | None = None) -> dict:
    """What this phone did before. resource_ids limits it to the columns the asker may see (None = all)."""
    from app.routes.upload import _normalize_phone
    norm = _normalize_phone(phone)
    if not norm:
        raise BookingError("Please enter a valid phone number")
    if resource_ids is not None and not resource_ids:
        rows: list[dict] = []
    else:
        q = db.table("bookings").select("id, status").eq("tenant_id", tenant_id).eq("phone", norm)
        if resource_ids is not None:
            q = q.in_("resource_id", resource_ids)
        rows = q.execute().data or []
    shows = sum(1 for r in rows if r["status"] == "no_show")
    return {"bookings_count": sum(1 for r in rows if r["status"] != "cancelled"), "no_shows": shows,
            "advance_needed": shows >= int(rules.get("no_show_limit") or 2)}


def _free_columns(db, tenant_id: str, service: dict, resource_id: str | None, start: datetime, rules: dict, *,
                  staff: bool, allowed: list[dict] | None, exclude_booking_id: str | None = None) -> list[dict]:
    """Every column that is free for this service at exactly `start`, in column order (empty list = none)."""
    pool = resources_for(db, tenant_id, service, resource_id, allowed)
    if resource_id and resource_id != "any" and not pool:
        raise BookingError("That staff / chair does not do this service")
    day = ist_date(start)
    found = free_times(db, tenant_id, service, pool, [day], rules, staff=staff,
                       exclude_booking_id=exclude_booking_id).get(day, [])
    return [r for start_t, r in found if start_t == start]


def _check_start(start: datetime) -> None:
    local = start.astimezone(IST)
    if local.second or local.microsecond or local.minute % STEP_MIN:
        raise BookingError("Pick a time on a quarter hour")


# Which lead source a booking's customer gets when we have to make the lead.
LEAD_SOURCE = {"phone": "manual", "walk_in": "manual", "chat": "whatsapp", "ai": "whatsapp", "link": "website"}
CHANGED = "This booking just changed — refresh"


def _changed() -> BookingError:
    return BookingError(CHANGED, 409)


def _transition(db, tenant_id: str, booking_id: str, allowed: tuple[str, ...], patch: dict) -> dict:
    """Update only while the booking is still in one of `allowed` statuses. Losing a race = a plain 409."""
    rows = (db.table("bookings").update(patch).eq("id", booking_id).eq("tenant_id", tenant_id)
            .in_("status", list(allowed)).execute().data or [])
    if not rows:
        raise _changed()
    return rows[0]


def _own_lead(db, tenant_id: str, lead_id: str, norm_phone: str) -> str:
    from app.routes.upload import _normalize_phone
    if not bsetup.is_uuid(lead_id):
        raise BookingError("That customer does not match this phone number")
    rows = db.table("leads").select("id, phone").eq("id", lead_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
    if not rows or _normalize_phone(rows[0].get("phone") or "") != norm_phone:
        raise BookingError("That customer does not match this phone number")
    return lead_id


_INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff\u00ad]")      # invisible: removed
_ODD_SPACE = re.compile("[\u00a0\u1680\u2000-\u200a\u2028-\u202f\u205f\u3000]")  # look like a space: turned into one


def clean_public_name(raw: str | None) -> str:
    """A customer-typed name: no control / zero-width / odd-space characters, one space between words, at most
    60 letters, and never a link."""
    text = _ODD_SPACE.sub(" ", _ZERO_WIDTH.sub("", str(raw or "")))
    text = "".join(ch for ch in text if ch.isprintable())
    text = " ".join(text.split())
    low = text.lower()
    if not text or "http" in low or "www." in low or "://" in low:
        raise BookingError("Please enter your name")
    return text[:60]


def _upcoming_live(db, tenant_id: str, phone: str, now: datetime) -> int:
    rows = (db.table("bookings").select("id").eq("tenant_id", tenant_id).eq("phone", phone)
            .in_("status", ["held", "booked"]).gte("start_at", iso(now)).execute().data or [])
    return len(rows)


def _unchecked_holds(db, tenant_id: str, now: datetime) -> int:
    rows = (db.table("bookings").select("id").eq("tenant_id", tenant_id).eq("status", "held")
            .eq("phone_checked", False).gt("hold_until", iso(now)).execute().data or [])
    return len(rows)


def _create_sync(db, tenant_id: str, *, service_id: str, resource_id: str | None, start_at, phone: str,
                 customer_name: str | None, lead_id: str | None, source: str, note: str | None,
                 send_advance_link: bool, public: bool, created_by: str | None,
                 allowed_resources: list[dict] | None) -> dict:
    """Every database step of making a booking up to and including the insert. Returns what the rest needs."""
    from app.routes.upload import _normalize_phone
    from app.services import booking_orders

    if source not in SOURCES:
        raise BookingError("Unknown booking source")
    norm = _normalize_phone(phone or "")
    if not norm:
        raise BookingError("Please enter a 10-digit mobile number" if public else "Please enter a valid phone number")
    if public and not _INDIAN_MOBILE.match(norm):
        raise BookingError("Please enter a 10-digit mobile number")
    start = parse_ts(start_at)
    _check_start(start)
    service = bsetup.get_service(db, tenant_id, service_id, active_only=True)
    if not service:
        raise BookingError("That service is not available")
    service["resource_ids"] = [l["resource_id"] for l in db.table("booking_service_resources").select("service_id, resource_id")
                               .eq("tenant_id", tenant_id).eq("service_id", service_id).execute().data or []]
    service = bsetup.with_catalog_price(db, tenant_id, service)     # what the order will bill
    settings = bsetup.get_settings(db, tenant_id)
    candidates = _free_columns(db, tenant_id, service, resource_id, start, settings, staff=not public,
                               allowed=allowed_resources)
    if not candidates:
        raise BookingError(NOT_FREE, 409)
    day = ist_date(start)
    day_guard = bool(settings.get("one_per_day", True))
    if day_guard and _phone_has_live(db, tenant_id, norm, day):
        raise _phone_day_error(public)
    now = _now()
    if public:
        if _upcoming_live(db, tenant_id, norm, now) >= MAX_UPCOMING_PER_PHONE:
            raise _phone_day_error(True)
        if _unchecked_holds(db, tenant_id, now) >= MAX_HOLDS_PER_BUSINESS:
            raise BookingError(TOO_MANY_HOLDS, 429)
        name = clean_public_name(customer_name)
    else:
        name = (customer_name or "").strip()[:120] or None
    if lead_id:
        lead_id = _own_lead(db, tenant_id, lead_id, norm)
    else:
        try:
            from app.services.inbound_lead import create_inbound_lead
            lead_id = create_inbound_lead(tenant_id, norm, LEAD_SOURCE.get(source, "manual"), name=name, db=db)
        except Exception as e:
            logger.warning("booking: could not find or make the lead for %s: %s", norm, e)
            lead_id = None

    advance = 0
    if public or send_advance_link:
        advance = booking_orders.advance_due(tenant_id, service, _no_shows(db, tenant_id, norm), int(settings["no_show_limit"]))
    hold = public          # a link booking is ALWAYS held: it becomes booked once the phone is proved (and any advance paid)
    end = start + timedelta(minutes=int(service["duration_min"]))
    base = {
        "tenant_id": tenant_id, "lead_id": lead_id, "phone": norm, "customer_name": name,
        "service_id": service_id, "start_at": iso(start), "end_at": iso(end),
        "block_end_at": iso(end + timedelta(minutes=int(service.get("gap_after_min") or 0))),
        "booking_date": day.isoformat(), "day_guard": day_guard, "status": "held" if hold else "booked", "source": source,
        "advance_paise": advance, "phone_checked": (not public) and source in ("chat", "ai"), "hold_until": iso(now + timedelta(minutes=HOLD_MINUTES)) if hold else None,
        "note": (note or "").strip()[:500] or None, "created_by": created_by,
    }
    saved, resource = None, None
    for column in candidates:                      # "any": if one column is taken in a race, try the next free one
        taken = False
        for _ in range(6):
            try:
                saved = db.table("bookings").insert(
                    {**base, "resource_id": column["id"], "number": _next_number(db, tenant_id)}).execute().data[0]
                resource = column
                break
            except Exception as e:
                kind = violation(e)
                if kind == "overlap":
                    taken = True
                    break
                if kind == "phone_day":
                    raise _phone_day_error(public)
                if kind == "unique" and day_guard and _phone_has_live(db, tenant_id, norm, day):
                    raise _phone_day_error(public)
                if kind in ("number", "unique"):
                    continue
                raise
        if saved or not taken:
            break
    if not saved:
        raise _taken_error() if candidates and taken else BookingError("Could not save the booking, please try again")
    return {"saved": saved, "service": service, "resource": resource, "advance": advance, "hold": hold, "now": now}


def _release_orphan_order(db, tenant_id: str, booking: dict, err: Exception | None = None) -> None:
    """The advance order was made but never attached to the booking (the link step failed): close it."""
    from app.services import booking_orders
    try:
        deal_id = getattr(err, "deal_id", None) or (getattr(err, "deal", None) or {}).get("id") if err else None
        if not deal_id:
            rows = (db.table("deals").select("id").eq("tenant_id", tenant_id)
                    .eq("notes", f"Booking {code_for(booking['number'])}").in_("stage", ["quoted", "awaiting_payment"])
                    .execute().data or [])
            deal_id = rows[0]["id"] if rows else None
        if deal_id:
            booking_orders.release_unpaid_order(tenant_id, {**booking, "deal_id": deal_id}, db)
    except Exception as e:
        logger.warning("booking %s: could not release the orphan order: %s", booking.get("id"), e)


def _after_create_sync(db, tenant_id: str, saved: dict, service: dict, resource: dict, source: str) -> dict:
    if saved["status"] != "booked":
        return saved       # an unchecked link hold: no lead mirror, no bell, no message. The flip to booked does those.
    sync_lead_mirror(db, tenant_id, saved.get("lead_id"), set_booked_at=True)
    if source in ("link", "ai"):
        notify(db, tenant_id, "booking_new", saved, service_name=service["name"], resource=resource)
    return saved


async def create_booking(db, tenant_id: str, *, service_id: str, resource_id: str | None, start_at, phone: str,
                         customer_name: str | None = None, lead_id: str | None = None, source: str = "phone",
                         note: str | None = None, send_advance_link: bool = False, public: bool = False,
                         created_by: str | None = None, allowed_resources: list[dict] | None = None) -> tuple[dict, dict]:
    """Make a booking. Returns (row, info) with info = {"payment_url", "advance_error", "service", "resource"}.

    public=True is the customer's link: rules for notice and days ahead apply, and an advance (when due) puts
    the booking on hold for 15 minutes. Staff bookings are booked straight away. Database work runs in a worker
    thread; only the real awaits (the order, the WhatsApp message) stay on the event loop.
    """
    from app.services import booking_orders

    made = await asyncio.to_thread(
        _create_sync, db, tenant_id, service_id=service_id, resource_id=resource_id, start_at=start_at, phone=phone,
        customer_name=customer_name, lead_id=lead_id, source=source, note=note, send_advance_link=send_advance_link,
        public=public, created_by=created_by, allowed_resources=allowed_resources)
    saved, service, resource, advance, hold, now = (made[k] for k in ("saved", "service", "resource", "advance", "hold", "now"))

    info: dict = {"payment_url": None, "advance_error": None, "service": service, "resource": resource}
    if advance > 0:
        try:
            order = await booking_orders.create_advance_order(
                tenant_id, saved, service, advance, send_whatsapp_message=not public, created_by=created_by, db=db)
            paid_part = {"deal_id": order["deal_id"], "advance_paise": min(advance, int(order.get("advance") or advance))}
            info["payment_url"] = order.get("payment_url")

            def _reread():
                return {**((db.table("bookings").select("*").eq("id", saved["id"]).limit(1).execute().data or [saved])[0]),
                        **paid_part}
            saved = await asyncio.to_thread(_reread)
        except Exception as e:     # any failure: a hold with no way to pay must not block the column
            logger.warning("booking %s: advance order failed: %s", saved["id"], e)
            if hold:
                def _undo():
                    _release_orphan_order(db, tenant_id, saved, e)
                    db.table("bookings").update({
                        "status": "cancelled", "cancelled_at": iso(now), "cancelled_by": "system",
                        "cancel_reason": "Could not make the payment link", "hold_until": None,
                    }).eq("id", saved["id"]).eq("tenant_id", tenant_id).execute()
                    sync_lead_mirror(db, tenant_id, saved.get("lead_id"))
                await asyncio.to_thread(_undo)
                raise BookingError("Couldn't make the payment link, please try again", 503)
            info["advance_error"] = str(e) if isinstance(e, booking_orders.BookingOrderError) else "Could not make the payment link"

            def _no_advance():
                db.table("bookings").update({"advance_paise": 0}).eq("id", saved["id"]).eq("tenant_id", tenant_id).execute()
            await asyncio.to_thread(_no_advance)
            saved = {**saved, "advance_paise": 0}
    saved = await asyncio.to_thread(_after_create_sync, db, tenant_id, saved, service, resource, source)
    if saved["status"] == "booked":
        await _message("send_confirmation", db, tenant_id, saved["id"])
    return saved, info


# ── move / cancel / came / no-show ──────────────────────────────────────────

def get_booking(db, tenant_id: str, booking_id: str) -> dict:
    if not bsetup.is_uuid(booking_id):
        raise BookingError("Booking not found", 404)
    rows = db.table("bookings").select("*").eq("tenant_id", tenant_id).eq("id", booking_id).limit(1).execute().data or []
    if not rows:
        raise BookingError("Booking not found", 404)
    return rows[0]


def before_cutoff(booking: dict, rules: dict, now: datetime | None = None) -> bool:
    now = now or _now()
    return parse_ts(booking["start_at"]) - now >= timedelta(minutes=int(rules.get("cancel_cutoff_min") or 0))


def _need_live(booking: dict, what: str) -> None:
    if booking["status"] not in ("held", "booked"):
        raise BookingError(f"This booking is already {booking['status'].replace('_', ' ')}, so it cannot be {what}")


def _move_sync(db, tenant_id: str, booking_id: str, start_at, resource_id: str | None, by: str,
               allowed_resources: list[dict] | None) -> dict:
    booking = get_booking(db, tenant_id, booking_id)
    _need_live(booking, "moved")
    settings = bsetup.get_settings(db, tenant_id)
    if by == "customer" and not before_cutoff(booking, settings):
        raise BookingError("It is too close to the time to change this online. Please call the business", 403)
    if by == "customer" and int(booking.get("moved_count") or 0) >= MAX_CUSTOMER_MOVES:
        raise BookingError("Please call the business to change it again", 403)
    start = parse_ts(start_at)
    _check_start(start)
    service = bsetup.get_service(db, tenant_id, booking["service_id"])
    if not service:
        raise BookingError("Service not found", 404)
    service["resource_ids"] = [l["resource_id"] for l in db.table("booking_service_resources").select("service_id, resource_id")
                               .eq("tenant_id", tenant_id).eq("service_id", service["id"]).execute().data or []]
    want = resource_id or ("any" if by == "customer" else booking["resource_id"])
    candidates = _free_columns(db, tenant_id, service, want, start, settings, staff=by != "customer",
                               allowed=allowed_resources, exclude_booking_id=booking_id)
    if not candidates:
        raise BookingError(NOT_FREE, 409)
    day = ist_date(start)
    day_guard = bool(settings.get("one_per_day", True))
    if day_guard and _phone_has_live(db, tenant_id, booking["phone"], day, exclude_id=booking_id):
        raise _phone_day_error(by == "customer")
    end = start + timedelta(minutes=int(service["duration_min"]))
    patch = {
        "start_at": iso(start), "end_at": iso(end),
        "block_end_at": iso(end + timedelta(minutes=int(service.get("gap_after_min") or 0))),
        "booking_date": day.isoformat(), "day_guard": day_guard,
        "moved_count": int(booking.get("moved_count") or 0) + 1,
        # a new time needs a fresh yes and fresh reminders
        "confirmed_at": None, "call_now_at": None, "reminder_day_sent_at": None, "reminder_2h_sent_at": None,
        "reminder_wamid": None, "updated_at": iso(_now()),
    }
    done = None
    for column in candidates:
        try:
            _transition(db, tenant_id, booking_id, ("held", "booked"), {**patch, "resource_id": column["id"]})
            done = {**booking, **patch, "resource_id": column["id"]}
            break
        except BookingError:
            raise
        except Exception as e:
            kind = violation(e)
            if kind == "overlap":
                continue                      # taken in a race: try the next free column for that start
            if kind in ("phone_day", "unique"):
                raise _phone_day_error(by == "customer")
            raise
    if not done:
        raise _taken_error()
    sync_lead_mirror(db, tenant_id, booking.get("lead_id"), set_booked_at=True)
    return done


async def move_booking(db, tenant_id: str, booking_id: str, start_at, resource_id: str | None = None, *,
                       by: str = "staff", allowed_resources: list[dict] | None = None) -> dict:
    """Move to another time (and column). by='customer' only before the cancel/move cutoff and only inside
    the customer rules (notice, days ahead)."""
    moved = await asyncio.to_thread(_move_sync, db, tenant_id, booking_id, start_at, resource_id, by, allowed_resources)
    await _message("send_moved", db, tenant_id, booking_id)
    return moved


def _cancel_sync(db, tenant_id: str, booking_id: str, by: str, reason: str | None) -> dict:
    booking = get_booking(db, tenant_id, booking_id)
    _need_live(booking, "cancelled")
    settings = bsetup.get_settings(db, tenant_id)
    if by == "customer" and not before_cutoff(booking, settings):
        raise BookingError("It is too close to the time to cancel online. Please call the business", 403)
    patch = {"status": "cancelled", "cancelled_at": iso(_now()), "cancelled_by": by,
             "cancel_reason": (reason or "").strip()[:200] or None, "hold_until": None, "updated_at": iso(_now())}
    _transition(db, tenant_id, booking_id, ("held", "booked"), patch)
    from app.services import booking_orders
    booking_orders.release_unpaid_order(tenant_id, booking, db)      # only ever touches an unpaid quote / awaiting order
    done = {**booking, **patch}
    sync_lead_mirror(db, tenant_id, booking.get("lead_id"))
    if by == "customer":
        svc = bsetup.get_service(db, tenant_id, booking["service_id"]) or {}
        notify(db, tenant_id, "booking_cancelled", booking, service_name=svc.get("name"),
               resource=bsetup.get_resource(db, tenant_id, booking["resource_id"]))
    return done


async def cancel_booking(db, tenant_id: str, booking_id: str, *, by: str = "staff", reason: str | None = None) -> dict:
    done = await asyncio.to_thread(_cancel_sync, db, tenant_id, booking_id, by, reason)
    if by != "customer":
        await _message("send_cancelled", db, tenant_id, booking_id, reason=reason)
    return done


def _came_sync(db, tenant_id: str, booking_id: str) -> tuple[dict, dict]:
    booking = get_booking(db, tenant_id, booking_id)
    if booking["status"] == "came" and not booking.get("deal_id"):
        pass                                   # came, but the order failed last time: allow trying the order again
    else:
        _need_live(booking, "marked as came")
        now = iso(_now())
        _transition(db, tenant_id, booking_id, ("held", "booked"),
                    {"status": "came", "came_at": now, "hold_until": None, "updated_at": now})
        sync_lead_mirror(db, tenant_id, booking.get("lead_id"))
    return booking, bsetup.get_service(db, tenant_id, booking["service_id"]) or {}


async def mark_came(db, tenant_id: str, booking_id: str, *, created_by: str | None = None) -> dict:
    """Came: status came, and the order to finish the bill on. If the order cannot be made the booking is
    still marked came, and the reason comes back in order_error. Came again on a came booking with no
    order tries the order once more."""
    from app.services import booking_orders
    booking, service = await asyncio.to_thread(_came_sync, db, tenant_id, booking_id)
    try:
        deal_id = await booking_orders.order_for_came(tenant_id, booking, service, created_by=created_by, db=db)
        return {"deal_id": deal_id, "href": f"/dashboard/deals/orders/{deal_id}", "order_error": None}
    except booking_orders.BookingOrderError as e:
        return {"deal_id": None, "href": None, "order_error": str(e)}


def mark_no_show(db, tenant_id: str, booking_id: str) -> dict:
    booking = get_booking(db, tenant_id, booking_id)
    _need_live(booking, "marked as didn't come")
    if parse_ts(booking["start_at"]) > _now():
        raise BookingError("This booking has not started yet")
    patch = {"status": "no_show", "hold_until": None, "updated_at": iso(_now())}
    _transition(db, tenant_id, booking_id, ("held", "booked"), patch)
    from app.services import booking_orders
    booking_orders.release_unpaid_order(tenant_id, booking, db)
    sync_lead_mirror(db, tenant_id, booking.get("lead_id"))
    return {**booking, **patch}


# ── the customer's link ─────────────────────────────────────────────────────

def main_number(db, tenant_id: str) -> str | None:
    """The main WhatsApp number as +<digits>, or None."""
    import re
    try:
        rows = (db.table("phone_numbers").select("number, role").eq("tenant_id", tenant_id)
                .eq("status", "active").execute().data or [])
        row = next((r for r in rows if r.get("role") == "primary"), None)
        digits = re.sub(r"\D", "", (row or {}).get("number") or "")
        return f"+{digits}" if digits else None
    except Exception as e:
        logger.warning("booking: main number lookup failed: %s", e)
        return None


def whatsapp_url(db, tenant_id: str, booking: dict) -> str | None:
    from urllib.parse import quote
    number = main_number(db, tenant_id)
    if not number:
        return None
    return f"https://wa.me/{number.lstrip('+')}?text={quote('Hi, my booking code is ' + code_for(booking['number']))}"


def whatsapp_link(number: str | None, booking: dict) -> str | None:
    from urllib.parse import quote
    if not number:
        return None
    return f"https://wa.me/{number.lstrip('+')}?text={quote('Hi, my booking code is ' + code_for(booking['number']))}"


async def public_view(db, tenant_id: str, booking: dict, rules: dict) -> dict:
    """The status page's answer. A held booking becomes booked here once the number is proved AND any advance is paid."""
    if booking["status"] == "held":
        try:
            from app.services import booking_messages
            ready = getattr(booking_messages, "confirm_if_ready", None) or booking_messages.confirm_if_paid
            await ready(db, tenant_id, booking)
        except Exception as e:
            logger.warning("booking %s: confirm_if_ready failed: %s", booking["id"], e)
        booking = get_booking(db, tenant_id, booking["id"])
    svc, res, number, paid, pay_url = await asyncio.gather(
        asyncio.to_thread(bsetup.get_service, db, tenant_id, booking["service_id"]),
        asyncio.to_thread(bsetup.get_resource, db, tenant_id, booking["resource_id"]),
        asyncio.to_thread(main_number, db, tenant_id),
        asyncio.to_thread(_paid, db, tenant_id, booking),
        asyncio.to_thread(_payment_url, db, tenant_id, booking),
    )
    svc, res = svc or {}, res or {}
    live = booking["status"] in ("held", "booked")
    return {
        "code": code_for(booking["number"]), "status": booking["status"], "start_at": booking["start_at"],
        "service_id": booking["service_id"], "resource_id": booking["resource_id"],
        "service_name": svc.get("name"), "resource_name": res.get("name"),
        "duration_min": svc.get("duration_min"), "advance_paise": int(booking.get("advance_paise") or 0),
        "advance_paid": paid, "payment_url": pay_url,
        "phone_checked": bool(booking.get("phone_checked")),
        "hold_until": booking.get("hold_until") if booking["status"] == "held" else None,
        "can_change": live and before_cutoff(booking, rules),
        "moves_left": max(0, MAX_CUSTOMER_MOVES - int(booking.get("moved_count") or 0)) if live else 0,
        "whatsapp_url": whatsapp_link(number, booking), "business_phone": number,
    }


def _payment_url(db, tenant_id: str, booking: dict) -> str | None:
    """The advance's pay link while the booking is still waiting for it."""
    if booking["status"] != "held" or not booking.get("deal_id"):
        return None
    try:
        rows = db.table("deals").select("payment_link").eq("id", booking["deal_id"]).eq("tenant_id", tenant_id).limit(1).execute().data or []
        return (rows[0].get("payment_link") if rows else None) or None
    except Exception:
        return None
