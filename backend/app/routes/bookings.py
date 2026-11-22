"""Engage > Bookings (v9.2 #19).

Staff API (/api/v1/bookings): setup, the day and week boards, free times, and book / move / cancel /
came / didn't come. Public API (/api/v1/public/bookings): the customer's link, by secret token.
The rules live in services/bookings.py and services/booking_setup.py; money goes only through
services/booking_orders.py. Money columns need deals.view.
"""
import asyncio
import logging
import threading
import os
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission, require_permission
from app.routes.auto_messages import _client_ip, _SlidingWindow
from app.services import booking_setup as bsetup
from app.services import bookings as bk
from app.services.booking_setup import BookingError

logger = logging.getLogger(__name__)

router = APIRouter()
public_router = APIRouter()

view = require_permission("bookings.view")
manage = require_permission("bookings.manage")

# Public link limits. GETs and POSTs share one per-IP bucket; only POSTs count against the business's token.
# The status page polls, so it has its own buckets and never uses up the others.
_ip_limiter = _SlidingWindow(60, 60)
_token_post_limiter = _SlidingWindow(600, 60)
_status_ip_limiter = _SlidingWindow(240, 60)
_status_id_limiter = _SlidingWindow(120, 60)
HOLDS_PER_IP = 3
_ip_holds: dict[str, list[str]] = {}      # client ip -> ids of the holds it made (checked against the database)
_ip_holds_lock = threading.Lock()
_NO_STORE = {"Cache-Control": "no-store"}


@contextmanager
def _errors():
    """BookingError -> the HTTP error with its plain-words message."""
    try:
        yield
    except BookingError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


def _money(ctx: dict) -> bool:
    return _has_permission(ctx, "deals.view")


def _today():
    return bk.ist_date(bk._now())


def _day_param(value: str | None) -> date:
    return bk.parse_day(value) if value else _today()


def _frontend_base() -> str:
    return (os.environ.get("FRONTEND_URL") or "https://www.anrilaitech.com").rstrip("/")


# ── shapes ──────────────────────────────────────────────────────────────────

def _service_out(s: dict, show_money: bool) -> dict:
    out = {"id": s["id"], "name": s["name"], "duration_min": s["duration_min"],
           "gap_after_min": s.get("gap_after_min") or 0, "active": bool(s.get("active", True)),
           "resource_ids": s.get("resource_ids") or []}
    if show_money:
        out["price_paise"] = int(s.get("price_paise") or 0)
        out["advance_paise"] = int(s.get("advance_paise") or 0)
    return out


def _resource_out(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "kind": r.get("kind") or "person", "user_id": r.get("user_id"),
            "hours": r.get("hours") or {}, "active": bool(r.get("active", True)), "sort": r.get("sort") or 0,
            "service_ids": r.get("service_ids") or []}


def _templates() -> dict:
    return {"update": None, "reminder": None}


def _template_status(db, tenant_id: str) -> dict:
    try:
        from app.services.booking_messages import templates_status
        got = templates_status(db, tenant_id) or {}
        return {"update": got.get("update"), "reminder": got.get("reminder")}
    except Exception as e:
        logger.info("booking templates status unavailable: %s", e)
        return _templates()


# ── setup ───────────────────────────────────────────────────────────────────

@router.get("/setup")
def get_setup(ctx: dict = Depends(view)):
    db, tid = get_supabase(), ctx["tenant_id"]
    show = _money(ctx)
    settings = bsetup.get_settings(db, tid, create=True)
    all_resources = bsetup.list_resources(db, tid)
    mine = bk.my_resource_id(ctx, all_resources)
    manager = bk.can_manage(ctx)
    seen = {r["id"] for r in bk.visible_resources(ctx, all_resources) if manager or r.get("active", True)}
    return {
        "settings": bsetup.public_settings(settings),
        "link_url": f"{_frontend_base()}/book/{settings['link_token']}" if manager and settings.get("link_token") else None,
        "services": [_service_out(s, show) for s in bsetup.list_services(db, tid)],
        "resources": [_resource_out(r) for r in all_resources if r["id"] in seen],
        "leave": [l for l in bsetup.list_leave(db, tid, _today()) if l["resource_id"] in seen],
        "team": bsetup.team(db, tid) if manager else [],
        "my_resource_id": mine,
        "can_manage": manager,
        "templates": _template_status(db, tid) if manager else _templates(),
    }


class SettingsIn(BaseModel):
    link_on: bool | None = None
    days_ahead: int | None = None
    min_notice_min: int | None = None
    cancel_cutoff_min: int | None = None
    one_per_day: bool | None = None
    no_show_limit: int | None = None


@router.put("/settings")
def put_settings(body: SettingsIn, ctx: dict = Depends(manage)):
    with _errors():
        saved = bsetup.update_settings(get_supabase(), ctx["tenant_id"], body.model_dump(exclude_unset=True))
    return {"settings": bsetup.public_settings(saved)}


@router.post("/settings/new-link")
def new_link(ctx: dict = Depends(manage)):
    """The old link stops working at once."""
    saved = bsetup.new_link_token(get_supabase(), ctx["tenant_id"])
    return {"link_url": f"{_frontend_base()}/book/{saved['link_token']}"}


class ServiceIn(BaseModel):
    name: str | None = Field(None, max_length=120)
    duration_min: int | None = None
    price_paise: int | None = None
    advance_paise: int | None = None
    gap_after_min: int | None = None
    resource_ids: list[str] | None = None
    active: bool | None = None


def _service_data(body: ServiceIn, ctx: dict) -> dict:
    data = body.model_dump(exclude_unset=True)
    if not _money(ctx):  # who cannot see money cannot change it
        data.pop("price_paise", None)
        data.pop("advance_paise", None)
    return data


@router.post("/services")
def create_service(body: ServiceIn, ctx: dict = Depends(manage)):
    with _errors():
        row = bsetup.create_service(get_supabase(), ctx["tenant_id"], _service_data(body, ctx))
    return _service_out(row, _money(ctx))


@router.patch("/services/{service_id}")
def update_service(service_id: str, body: ServiceIn, ctx: dict = Depends(manage)):
    with _errors():
        row = bsetup.update_service(get_supabase(), ctx["tenant_id"], service_id, _service_data(body, ctx))
    return _service_out(row, _money(ctx))


@router.delete("/services/{service_id}")
def delete_service(service_id: str, ctx: dict = Depends(manage)):
    """Soft: the service stops being offered; its past bookings stay."""
    with _errors():
        row = bsetup.deactivate_service(get_supabase(), ctx["tenant_id"], service_id)
    return _service_out(row, _money(ctx))


class ResourceIn(BaseModel):
    name: str | None = Field(None, max_length=80)
    kind: Literal["person", "chair", "room"] | None = None
    user_id: str | None = None
    hours: dict | None = None
    active: bool | None = None
    sort: int | None = None
    service_ids: list[str] | None = None


@router.post("/resources")
def create_resource(body: ResourceIn, ctx: dict = Depends(manage)):
    with _errors():
        row = bsetup.create_resource(get_supabase(), ctx["tenant_id"], body.model_dump(exclude_unset=True))
    return _resource_out(row)


@router.patch("/resources/{resource_id}")
def update_resource(resource_id: str, body: ResourceIn, ctx: dict = Depends(manage)):
    with _errors():
        row = bsetup.update_resource(get_supabase(), ctx["tenant_id"], resource_id, body.model_dump(exclude_unset=True))
    return _resource_out(row)


@router.delete("/resources/{resource_id}")
def delete_resource(resource_id: str, ctx: dict = Depends(manage)):
    """Soft: refused while it has upcoming bookings."""
    with _errors():
        row = bsetup.deactivate_resource(get_supabase(), ctx["tenant_id"], resource_id)
    return _resource_out(row)


class LeaveIn(BaseModel):
    from_date: str
    to_date: str | None = None
    note: str | None = Field(None, max_length=200)


@router.post("/resources/{resource_id}/leave")
def add_leave(resource_id: str, body: LeaveIn, ctx: dict = Depends(manage)):
    with _errors():
        return bsetup.add_leave(get_supabase(), ctx["tenant_id"], resource_id, body.model_dump(), ctx.get("user_id"))


@router.delete("/leave/{leave_id}")
def delete_leave(leave_id: str, ctx: dict = Depends(manage)):
    bsetup.delete_leave(get_supabase(), ctx["tenant_id"], leave_id)
    return {"ok": True}


@router.post("/templates/setup")
async def setup_templates(ctx: dict = Depends(manage)):
    """Submit the booking WhatsApp messages to Meta. Needs bookings.manage AND templates.manage."""
    if not _has_permission(ctx, "templates.manage"):
        raise HTTPException(status_code=403, detail="Permission required: templates.manage")
    from app.services.booking_messages import submit_templates
    return await submit_templates(get_supabase(), ctx["tenant_id"], ctx)


# ── the boards ──────────────────────────────────────────────────────────────

def _shape_all(db, ctx: dict, rows: list[dict]) -> list[dict]:
    return bk.shape_many(db, ctx["tenant_id"], rows, bk.service_map(db, ctx["tenant_id"]), show_money=_money(ctx))


def _visible(db, ctx: dict) -> list[dict]:
    """Active columns this person may see, with the services each does."""
    return bk.scoped_columns(db, ctx)


@router.get("/day")
def get_day(date: str | None = Query(None, max_length=10), ctx: dict = Depends(view)):
    db, tid = get_supabase(), ctx["tenant_id"]
    with _errors():
        day = _day_param(date)
    resources = _visible(db, ctx)
    ids = [r["id"] for r in resources]
    rows = bk.bookings_on(db, tid, day, day, ids, spill=True)
    live = {rid: [] for rid in ids}
    for r in rows:
        if r["status"] in bsetup.LIVE:
            live[r["resource_id"]].append((bk.parse_ts(r["start_at"]), bk.parse_ts(r["block_end_at"])))
    leave = bk._leave_by_resource(db, tid, ids, day, day)
    earliest = bk.floor_step(bk._now())
    free = {}
    for r in resources:
        off = any(a <= day <= b for a, b in leave.get(r["id"], []))
        free[r["id"]] = [[bk.iso(a), bk.iso(b)] for a, b in
                         bk.free_ranges(r.get("hours") or {}, day, earliest=earliest, live=live[r["id"]], on_leave=off)]
    return {"date": day.isoformat(), "resources": [_resource_out(r) for r in resources],
            "bookings": _shape_all(db, ctx, rows), "free": free}


@router.get("/week")
def get_week(start: str | None = Query(None, max_length=10), ctx: dict = Depends(view)):
    db = get_supabase()
    with _errors():
        first = _day_param(start)
    first -= timedelta(days=first.weekday())  # the Monday of that week
    last = first + timedelta(days=6)
    resources = _visible(db, ctx)
    shaped = _shape_all(db, ctx, bk.bookings_on(db, ctx["tenant_id"], first, last, [r["id"] for r in resources]))
    days = []
    for i in range(7):
        d = first + timedelta(days=i)
        days.append({"date": d.isoformat(),
                     "bookings": [b for b in shaped if bk.ist_date(bk.parse_ts(b["start_at"])) == d]})
    return {"start": first.isoformat(), "days": days, "resources": [_resource_out(r) for r in resources]}


def _service_for_free(db, tenant_id: str, service_id: str) -> dict:
    svc = bsetup.get_service(db, tenant_id, service_id, active_only=True)
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    svc["resource_ids"] = bsetup.get_service_shaped(db, tenant_id, service_id)["resource_ids"]
    return svc


def _own_booking_id(db, tenant_id: str, booking_id: str | None) -> str | None:
    """The booking being moved, so its own slot counts as free. Must be this business's booking."""
    if not booking_id:
        return None
    if len(booking_id) > 64:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        bk.get_booking(db, tenant_id, booking_id)
    except BookingError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:  # not a valid id for the column type
        logger.info("free times: bad exclude_booking_id: %s", e)
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking_id


@router.get("/free")
def get_free(service_id: str = Query(..., max_length=64), resource_id: str = Query("any", max_length=64),
             date: str = Query(..., max_length=10), exclude_booking_id: str | None = Query(None, max_length=64),
             ctx: dict = Depends(view)):
    db, tid = get_supabase(), ctx["tenant_id"]
    with _errors():
        times = bk.times_for_day(db, tid, _service_for_free(db, tid, service_id), resource_id, bk.parse_day(date),
                                 bsetup.get_settings(db, tid), staff=True, allowed=_visible(db, ctx),
                                 exclude_booking_id=_own_booking_id(db, tid, exclude_booking_id))
    return {"times": times}


@router.get("/free-days")
def get_free_days(service_id: str = Query(..., max_length=64), resource_id: str = Query("any", max_length=64),
                  exclude_booking_id: str | None = Query(None, max_length=64), ctx: dict = Depends(view)):
    db, tid = get_supabase(), ctx["tenant_id"]
    dates = bk.days_with_times(db, tid, _service_for_free(db, tid, service_id), resource_id,
                               bsetup.get_settings(db, tid), staff=True, allowed=_visible(db, ctx),
                               exclude_booking_id=_own_booking_id(db, tid, exclude_booking_id))
    return {"dates": dates}


@router.get("/history")
def get_history(phone: str = Query(..., max_length=30), ctx: dict = Depends(view)):
    db = get_supabase()
    everything = bsetup.list_resources(db, ctx["tenant_id"])
    limited = bk.only_own_column(ctx, everything) is not None       # a linked person sees only their own column
    ids = [r["id"] for r in _visible(db, ctx)] if limited else None
    with _errors():
        return bk.history(db, ctx["tenant_id"], phone, bsetup.get_settings(db, ctx["tenant_id"]), ids)


# ── actions ─────────────────────────────────────────────────────────────────

class NewBooking(BaseModel):
    service_id: str = Field(max_length=64)
    resource_id: str = Field("any", max_length=64)
    start_at: str = Field(max_length=40)
    phone: str = Field(max_length=30)
    customer_name: str | None = Field(None, max_length=120)
    lead_id: str | None = Field(None, max_length=64)
    source: Literal["phone", "walk_in", "chat"] = "phone"
    note: str | None = Field(None, max_length=500)
    send_advance_link: bool = False


@router.post("")
async def create_booking(body: NewBooking, ctx: dict = Depends(manage)):
    db, tid = get_supabase(), ctx["tenant_id"]
    with _errors():
        row, info = await bk.create_booking(
            db, tid, service_id=body.service_id, resource_id=body.resource_id, start_at=body.start_at,
            phone=body.phone, customer_name=body.customer_name, lead_id=body.lead_id, source=body.source,
            note=body.note, send_advance_link=body.send_advance_link, created_by=ctx.get("user_id"),
            allowed_resources=_visible(db, ctx))
    out = _shape_all(db, ctx, [row])[0]
    if info.get("advance_error"):
        out["advance_error"] = info["advance_error"]
    return out


class MoveIn(BaseModel):
    start_at: str = Field(max_length=40)
    resource_id: str | None = Field(None, max_length=64)


@router.post("/{booking_id}/move")
async def move_booking(booking_id: str, body: MoveIn, ctx: dict = Depends(manage)):
    db = get_supabase()
    with _errors():
        row = await bk.move_booking(db, ctx["tenant_id"], booking_id, body.start_at, body.resource_id, by="staff",
                                    allowed_resources=_visible(db, ctx))
    return _shape_all(db, ctx, [row])[0]


class CancelIn(BaseModel):
    reason: str | None = Field(None, max_length=200)


@router.post("/{booking_id}/cancel")
async def cancel_booking(booking_id: str, body: CancelIn | None = None, ctx: dict = Depends(manage)):
    db = get_supabase()
    with _errors():
        row = await bk.cancel_booking(db, ctx["tenant_id"], booking_id, by="staff", reason=body.reason if body else None)
    return _shape_all(db, ctx, [row])[0]


def _may_act(db, ctx: dict, booking_id: str) -> None:
    """Came / Didn't come: bookings.manage, or the person linked to that booking's column."""
    booking = bk.get_booking(db, ctx["tenant_id"], booking_id)
    if not bk.can_act_on(ctx, bsetup.get_resource(db, ctx["tenant_id"], booking["resource_id"])):
        raise HTTPException(status_code=403, detail="Only the person on this column or a manager can do this")


@router.post("/{booking_id}/came")
async def came(booking_id: str, ctx: dict = Depends(view)):
    db = get_supabase()
    with _errors():
        await asyncio.to_thread(_may_act, db, ctx, booking_id)
        done = await bk.mark_came(db, ctx["tenant_id"], booking_id, created_by=ctx.get("user_id"))
    if not _money(ctx):
        done = {**done, "href": None}               # the order page is for people who may see money
    return done


@router.post("/{booking_id}/no-show")
def no_show(booking_id: str, ctx: dict = Depends(view)):
    db = get_supabase()
    with _errors():
        _may_act(db, ctx, booking_id)
        row = bk.mark_no_show(db, ctx["tenant_id"], booking_id)
    return _shape_all(db, ctx, [row])[0]


# ═══════════════════════════ public: the customer's link ═══════════════════════════

def _gone() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


def _too_many() -> HTTPException:
    return HTTPException(status_code=429, detail="Too many requests. Try again in a minute.", headers={"Retry-After": "60"})


async def _public_tenant(request: Request, token: str, *, post: bool = False, status_id: str | None = None) -> tuple:
    """(db, tenant_id, settings). Unknown token or link switched off = the same 404.
    Limits: status checks use their own buckets (per booking id, per IP); everything else counts against the IP
    bucket, and POSTs also against the business's token bucket."""
    ip = _client_ip(request)
    if status_id is not None:
        if not _status_ip_limiter.allow(ip) or not _status_id_limiter.allow(status_id[:64]):
            raise _too_many()
    elif not _ip_limiter.allow(ip):
        raise _too_many()
    if not token or len(token) > 64:
        raise _gone()
    if post and not _token_post_limiter.allow(token):
        raise _too_many()
    db = get_supabase()
    settings = await asyncio.to_thread(bsetup.settings_by_token, db, token)
    if not settings or not settings.get("link_on"):
        raise _gone()
    return db, settings["tenant_id"], settings


def _json(content: dict) -> JSONResponse:
    return JSONResponse(content=content, headers=_NO_STORE)


def _page_sync(db, tid: str) -> dict:
    services = bsetup.list_services(db, tid, active_only=True)
    live_ids = {s["id"] for s in services}
    resources = [{**r, "service_ids": [i for i in r["service_ids"] if i in live_ids]}
                 for r in bsetup.list_resources(db, tid, active_only=True)]
    resources = [r for r in resources if r["service_ids"]]
    covered = {i for r in resources for i in r["service_ids"]}
    services = [s for s in services if s["id"] in covered]          # a service nobody does is not offered
    name = ""
    try:
        t = db.table("tenants").select("name").eq("id", tid).limit(1).execute().data or []
        name = (t[0].get("name") if t else "") or ""
    except Exception as e:
        logger.warning("booking page: tenant name failed: %s", e)
    return {"name": name, "number": bk.main_number(db, tid), "services": services, "resources": resources}


@public_router.get("/{token}")
async def public_page(token: str, request: Request):
    db, tid, settings = await _public_tenant(request, token)
    page = await asyncio.to_thread(_page_sync, db, tid)
    return _json({
        "business_name": page["name"], "business_phone": page["number"],
        "services": [{"id": s["id"], "name": s["name"], "duration_min": s["duration_min"],
                      "price_paise": int(s.get("price_paise") or 0), "advance_paise": int(s.get("advance_paise") or 0)}
                     for s in page["services"]],
        "resources": [{"id": r["id"], "name": r["name"], "kind": r.get("kind") or "person", "service_ids": r["service_ids"]}
                      for r in page["resources"]],
        "rules": {"days_ahead": settings["days_ahead"], "cancel_cutoff_min": settings["cancel_cutoff_min"]},
    })


def _public_service(db, tid: str, service_id: str) -> dict:
    svc = bsetup.get_service(db, tid, service_id, active_only=True)       # a malformed id is "not found"
    if not svc:
        raise _gone()
    svc["resource_ids"] = bsetup.get_service_shaped(db, tid, service_id)["resource_ids"]
    return svc


def _public_resource(resource_id: str | None) -> str:
    if resource_id and resource_id != "any" and not bsetup.is_uuid(resource_id):
        raise HTTPException(status_code=400, detail="Please pick one of the options")
    return resource_id or "any"


def _days_sync(db, tid: str, settings: dict, service_id: str, resource_id: str) -> dict:
    return {"dates": bk.days_with_times(db, tid, _public_service(db, tid, service_id), resource_id, settings, staff=False)}


@public_router.get("/{token}/days")
async def public_days(token: str, request: Request, service_id: str = Query(..., max_length=64),
                      resource_id: str = Query("any", max_length=64)):
    db, tid, settings = await _public_tenant(request, token)
    resource_id = _public_resource(resource_id)
    return _json(await asyncio.to_thread(_days_sync, db, tid, settings, service_id, resource_id))


def _times_sync(db, tid: str, settings: dict, service_id: str, resource_id: str, date_text: str) -> dict:
    with _errors():
        return {"times": bk.times_for_day(db, tid, _public_service(db, tid, service_id), resource_id,
                                          bk.parse_day(date_text), settings, staff=False)}


@public_router.get("/{token}/times")
async def public_times(token: str, request: Request, service_id: str = Query(..., max_length=64),
                       resource_id: str = Query("any", max_length=64), date: str = Query(..., max_length=10)):
    db, tid, settings = await _public_tenant(request, token)
    resource_id = _public_resource(resource_id)
    return _json(await asyncio.to_thread(_times_sync, db, tid, settings, service_id, resource_id, date))


class PublicBooking(BaseModel):
    service_id: str = Field(max_length=64)
    resource_id: str = Field("any", max_length=64)
    start_at: str = Field(max_length=40)
    phone: str = Field(max_length=30)
    name: str = Field(min_length=1, max_length=120)


def _live_holds_of(db, ids: list[str]) -> list[str]:
    """Of these booking ids, the ones that are still unchecked holds."""
    if not ids:
        return []
    rows = (db.table("bookings").select("id").in_("id", ids).eq("status", "held").eq("phone_checked", False)
            .gt("hold_until", bk.iso(bk._now())).execute().data or [])
    return [r["id"] for r in rows]


def _check_ip_holds(db, ip: str) -> None:
    """At most HOLDS_PER_IP unchecked holds per client address, across all businesses. Kept in this process
    and checked against the database, so a hold that was confirmed or has run out stops counting."""
    with _ip_holds_lock:
        ids = _ip_holds.get(ip, [])
    live = _live_holds_of(db, ids)
    with _ip_holds_lock:
        if live:
            _ip_holds[ip] = live
        else:
            _ip_holds.pop(ip, None)
    if len(live) >= HOLDS_PER_IP:
        raise HTTPException(status_code=429, detail=bk.TOO_MANY_HOLDS)


def _remember_hold(ip: str, booking_id: str) -> None:
    with _ip_holds_lock:
        _ip_holds.setdefault(ip, []).append(booking_id)


@public_router.post("/{token}")
async def public_book(token: str, body: PublicBooking, request: Request):
    db, tid, settings = await _public_tenant(request, token, post=True)
    if not bsetup.is_uuid(body.service_id):
        raise _gone()
    resource_id = _public_resource(body.resource_id)
    ip = _client_ip(request)
    await asyncio.to_thread(_check_ip_holds, db, ip)
    with _errors():
        row, info = await bk.create_booking(
            db, tid, service_id=body.service_id, resource_id=resource_id, start_at=body.start_at,
            phone=body.phone, customer_name=body.name, source="link", public=True)
    if row["status"] == "held" and not row.get("phone_checked"):
        _remember_hold(ip, row["id"])
    number = await asyncio.to_thread(bk.main_number, db, tid)
    return _json({
        "id": row["id"], "code": bk.code_for(row["number"]), "status": row["status"], "start_at": row["start_at"],
        "service_name": info["service"]["name"], "resource_name": info["resource"]["name"],
        "advance_paise": int(row.get("advance_paise") or 0), "payment_url": info.get("payment_url"),
        "phone_checked": bool(row.get("phone_checked")),
        "hold_until": row.get("hold_until") if row["status"] == "held" else None,
        "whatsapp_url": bk.whatsapp_link(number, row),
    })


def _public_booking(db, tid: str, booking_id: str) -> dict:
    if len(booking_id) > 64:
        raise _gone()
    try:
        return bk.get_booking(db, tid, booking_id)       # a malformed id is "not found" too
    except BookingError:
        raise _gone()
    except Exception as e:
        logger.info("public booking lookup failed: %s", e)
        raise _gone()


@public_router.get("/{token}/booking/{booking_id}")
async def public_status(token: str, booking_id: str, request: Request):
    db, tid, settings = await _public_tenant(request, token, status_id=booking_id)
    booking = await asyncio.to_thread(_public_booking, db, tid, booking_id)
    return _json(await bk.public_view(db, tid, booking, settings))


@public_router.post("/{token}/booking/{booking_id}/cancel")
async def public_cancel(token: str, booking_id: str, request: Request):
    db, tid, _ = await _public_tenant(request, token, post=True)
    await asyncio.to_thread(_public_booking, db, tid, booking_id)
    with _errors():
        row = await bk.cancel_booking(db, tid, booking_id, by="customer")
    return _json({"status": row["status"]})


class PublicMove(BaseModel):
    start_at: str = Field(max_length=40)
    resource_id: str | None = Field(None, max_length=64)


@public_router.post("/{token}/booking/{booking_id}/move")
async def public_move(token: str, booking_id: str, body: PublicMove, request: Request):
    db, tid, settings = await _public_tenant(request, token, post=True)
    await asyncio.to_thread(_public_booking, db, tid, booking_id)
    resource_id = _public_resource(body.resource_id) if body.resource_id else None
    with _errors():
        row = await bk.move_booking(db, tid, booking_id, body.start_at, resource_id, by="customer")
    return _json(await bk.public_view(db, tid, row, settings))
