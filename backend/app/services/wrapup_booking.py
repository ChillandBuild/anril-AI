"""Call wrap-up "Interested, next step booked" can make a real booking (v9.2 item 136).

Uses the Bookings engine as it is: the services, the free times and `bookings.create_booking`, which
already refuses a taken time and a second booking for the same phone on the same day. Nothing here is
a second set of booking rules. Only businesses that set Bookings up (an active service done by an
active staff / chair column) get this; for everyone else the outcome works as it always did.
"""
import asyncio
import logging
from datetime import date

from app.services import booking_setup as bsetup
from app.services import bookings as bk
from app.services.booking_setup import BookingError

logger = logging.getLogger(__name__)


def options(db, tenant_id: str) -> dict:
    """{"enabled": bool, "services": [{id, name, duration_min}]}: active services that an active column does."""
    try:
        active_columns = {r["id"] for r in bsetup.list_resources(db, tenant_id, active_only=True)}
        services = [
            {"id": s["id"], "name": s["name"], "duration_min": s["duration_min"]}
            for s in bsetup.list_services(db, tenant_id, active_only=True)
            if active_columns.intersection(s.get("resource_ids") or [])
        ]
    except Exception as e:  # bookings tables missing or a failed read: the outcome simply works as before
        logger.info("wrapup booking: options unavailable for %s: %s", tenant_id, e)
        return {"enabled": False, "services": []}
    return {"enabled": bool(services), "services": services}


def _service(db, tenant_id: str, service_id: str) -> dict:
    if not bsetup.is_uuid(service_id):
        raise BookingError("That service is not available", 404)
    svc = bsetup.get_service(db, tenant_id, service_id, active_only=True)
    if not svc:
        raise BookingError("That service is not available", 404)
    svc["resource_ids"] = bsetup.get_service_shaped(db, tenant_id, service_id)["resource_ids"]
    return svc


def free_days(db, tenant_id: str, service_id: str) -> list[str]:
    """Days (IST, yyyy-mm-dd) that still have a free time for this service, any column."""
    return bk.days_with_times(db, tenant_id, _service(db, tenant_id, service_id), "any",
                              bsetup.get_settings(db, tenant_id), staff=True)


def free_times(db, tenant_id: str, service_id: str, day: date) -> list[dict]:
    """[{start_at, resource_id, resource_name}] for one day, earliest first."""
    return bk.times_for_day(db, tenant_id, _service(db, tenant_id, service_id), "any", day,
                            bsetup.get_settings(db, tenant_id), staff=True)


def _lead(db, tenant_id: str, lead_id: str) -> dict:
    rows = (db.table("leads").select("id,name,phone").eq("id", lead_id).eq("tenant_id", tenant_id)
            .limit(1).execute().data or [])
    if not rows or not rows[0].get("phone"):
        raise BookingError("This call isn't linked to a customer with a phone number, so it can't be booked", 400)
    return rows[0]


def existing_booking_id(db, tenant_id: str, call_log_id: str) -> str | None:
    """The booking this wrap-up already made, if any (a double tap or a retry). Tolerates migration 334 not applied."""
    try:
        rows = (db.table("call_logs").select("booking_id").eq("id", call_log_id).eq("tenant_id", tenant_id)
                .limit(1).execute().data or [])
        return (rows[0].get("booking_id") if rows else None) or None
    except Exception as e:
        logger.info("wrapup booking: booking_id not readable yet: %s", e)
        return None


def _live_booking_that_day(db, tenant_id: str, phone: str, start_at) -> dict | None:
    """This customer's live booking on the same Indian day as start_at (held, booked or came), if any."""
    day = bk.parse_ts(start_at).astimezone(bk.IST).date().isoformat()
    rows = (
        db.table("bookings").select("id,start_at,status").eq("tenant_id", tenant_id).eq("phone", phone)
        .eq("booking_date", day).in_("status", ["held", "booked", "came"]).limit(1).execute().data or []
    )
    return rows[0] if rows else None


async def book_visit(db, tenant_id: str, *, call_log_id: str, lead_id: str, booking: dict, note: str | None,
                     user_id: str | None) -> str:
    """Make the booking for this lead (source 'phone'), remember it on the call, return its id.

    Raises BookingError with a plain-words message (time taken, same-day rule, service gone, ...);
    nothing else of the wrap-up has been written yet when this runs."""
    already = await asyncio.to_thread(existing_booking_id, db, tenant_id, call_log_id)
    if already:
        return already
    lead = await asyncio.to_thread(_lead, db, tenant_id, lead_id)
    try:
        row, _info = await bk.create_booking(
            db, tenant_id, service_id=booking["service_id"], resource_id=booking.get("resource_id") or "any",
            start_at=booking["start_at"], phone=lead["phone"], customer_name=lead.get("name"), lead_id=lead_id,
            source="phone", note=note, created_by=user_id,
        )
    except BookingError as refused:
        # A retry after the booking was made but the wrap-up was not saved: reuse that booking.
        existing = await asyncio.to_thread(_live_booking_that_day, db, tenant_id, lead["phone"], booking["start_at"])
        if existing is None:
            raise
        if bk.parse_ts(existing["start_at"]) != bk.parse_ts(booking["start_at"]):
            when = bk.parse_ts(existing["start_at"]).astimezone(bk.IST).strftime("%d %b, %I:%M %p").lstrip("0")
            raise BookingError(
                f"This customer already has a visit booked on {when}. Change or cancel it in Bookings first.", 409) from refused
        row = existing

    def _remember():
        try:
            db.table("call_logs").update({"booking_id": row["id"]}).eq("id", call_log_id).eq("tenant_id", tenant_id).execute()
        except Exception as e:  # migration 334 not applied yet: the booking stands, only the double-tap guard is off
            logger.info("wrapup booking: could not remember booking on call %s: %s", call_log_id, e)

    await asyncio.to_thread(_remember)
    return row["id"]
