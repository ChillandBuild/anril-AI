"""Operator Console: one client's broadcast history. System admins only, read-only.

GET /api/v1/operator/clients/{tenant_id}/broadcasts

The figures must equal what the client sees on their own Broadcast History tab. That tab does
two things (frontend/app/dashboard/outbound-leads/page.tsx `refreshHistory`):
  1. POST /api/v1/upload/history/refresh  (upload.py ~L2370) re-counts every broadcast with
     `_classify_broadcast_outcomes` and SAVES the counts back into the stored history, then
  2. GET /api/v1/upload/history           (upload.py ~L2101) returns the stored list, enriched.

Reuse, not replicate, where the code allows it:
  - step 2 is `upload.get_broadcast_history(tenant_id=...)`: a plain function of tenant_id, called as is.
  - the re-count in step 1 is `upload._classify_broadcast_outcomes(db, tenant_id, ...)` (also a plain
    helper) and `upload._refresh_delivered_opened_timewindow`, called as is.
  - what is replicated here is only the small in-memory loop of the refresh handler (upload.py
    ~L2392-2417), because the handler itself needs a client login and WRITES the counts back; this
    endpoint is read-only and never saves.
"""
import asyncio
import contextvars
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.supabase import get_supabase
from app.dependencies.system_admin import get_system_admin
from app.routes import upload
from app.services.delivery_status import parse_ts

logger = logging.getLogger(__name__)

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_DAYS = 7          # today + the 6 days before it
MAX_SPAN_DAYS = 92
MAX_LIMIT = 100
HISTORY_CAP = 50          # the client's history keeps only its last 50 broadcasts (upload.py)


def _now() -> datetime:
    """Now, in UTC. A function so tests can freeze the clock."""
    return datetime.now(timezone.utc)


def _parse_day(raw: str, name: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"{name} must be a date like 2026-11-19.")


def _date_range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Inclusive IST calendar days. Default: the last 7 IST days including today."""
    date_from = (date_from or "").strip() if isinstance(date_from, str) else ""
    date_to = (date_to or "").strip() if isinstance(date_to, str) else ""
    today = _now().astimezone(IST).date()
    if date_from and date_to:
        start, end = _parse_day(date_from, "date_from"), _parse_day(date_to, "date_to")
    elif date_from:
        start = _parse_day(date_from, "date_from")
        end = today
    elif date_to:
        end = _parse_day(date_to, "date_to")
        start = end - timedelta(days=DEFAULT_DAYS - 1)
    else:
        end = today
        start = today - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise HTTPException(status_code=400, detail="date_from must not be after date_to.")
    if (end - start).days + 1 > MAX_SPAN_DAYS:
        raise HTTPException(status_code=400, detail=f"The range can be at most {MAX_SPAN_DAYS} days.")
    return start, end


def _run(coro):
    """Run a coroutine to its end from sync code (the history handler is `async def` but never awaits)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Called on an event loop thread: run on a helper thread, keeping contextvars (the read-only guard).
    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()


def _refresh_in_memory(db, tenant_id: str, record: dict) -> None:
    """The re-count POST /upload/history/refresh does for one record (upload.py ~L2392-2417),
    minus the save. Same rule: classifier when the broadcast has recipient rows, else the
    time-window fallback. A record that cannot be re-counted keeps its stored numbers."""
    try:
        record_time = parse_ts(record.get("timestamp"))
        if record_time is None:
            return
        window_start = (record_time - timedelta(minutes=2)).isoformat()
        window_end = (record_time + timedelta(minutes=10)).isoformat()
        broadcast_id = record.get("broadcast_id")
        if broadcast_id:
            outcome = upload._classify_broadcast_outcomes(db, tenant_id, broadcast_id, record["timestamp"])
            if outcome["found"]:
                counts = outcome["counts"]
                record["sent"] = counts["sent"]
                record["delivered"] = counts["delivered"]
                record["opened"] = counts["opened"]
                record["failed"] = counts["failed"]
                record["opted_out"] = counts.get("opted_out", 0)
            else:
                upload._refresh_delivered_opened_timewindow(db, record, tenant_id, window_start, window_end)
        else:
            upload._refresh_delivered_opened_timewindow(db, record, tenant_id, window_start, window_end)
    except Exception as exc:
        logger.warning("operator broadcasts: could not re-count %s: %s", record.get("broadcast_id"), exc)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _row(record: dict, sent_at: datetime) -> dict:
    pos, neg, neu = (_int(record.get("replied_positive")), _int(record.get("replied_negative")),
                     _int(record.get("replied_neutral")))
    return {
        "id": record.get("broadcast_id"),
        "name": record.get("template_name"),
        "tag_id": record.get("tag_id"),
        "tag": record.get("tag_name"),
        "sent_at": sent_at.isoformat(),
        "sent_at_ist": sent_at.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
        "opt_in_source": record.get("opt_in_source"),
        "number_used": record.get("number_used"),
        "recipients": _int(record.get("total_leads")),
        "sent": _int(record.get("sent")),
        "delivered": _int(record.get("delivered")),
        "read": _int(record.get("opened")),
        "replied": pos + neg + neu,
        "replied_positive": pos,
        "replied_negative": neg,
        "replied_neutral": neu,
        "failed": _int(record.get("failed")),
        "opted_out": _int(record.get("opted_out")),
        "hot": _int(record.get("hot")),
        "warm": _int(record.get("warm")),
        "cold": _int(record.get("cold")),
    }


@router.get("/clients/{tenant_id}/broadcasts")
def client_broadcasts(
    tenant_id: str,
    date_from: str | None = Query(None, description="First IST day, YYYY-MM-DD"),
    date_to: str | None = Query(None, description="Last IST day, YYYY-MM-DD (inclusive)"),
    limit: int = Query(50, description="Most broadcasts to return (max 100)"),
    _admin: dict = Depends(get_system_admin),
):
    """A client's broadcasts in a range of Indian-time days, with the same counts the client sees.

    sent / delivered / read(=opened) / failed are the client's Broadcast History numbers after its
    own refresh (upload._classify_broadcast_outcomes). failed = the send was rejected by Meta
    (broadcast_recipients.send_status failed/rejected) or the delivery receipt said failed
    (messages.delivery_status = 'failed' on the outbound message nearest the send). Opt-outs are
    counted separately (opted_out), as on the client's page. replied = replies the AI classified
    positive + negative + neutral (broadcast_recipients.reply_sentiment).
    """
    start, end = _date_range(date_from, date_to)
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 50
    try:
        tenant_id = str(uuid.UUID(str(tenant_id)))
    except ValueError:
        raise HTTPException(status_code=404, detail="Tenant not found")

    db = get_supabase()
    tenant = db.table("tenants").select("id, name").eq("id", tenant_id).maybe_single().execute()
    if not tenant or not tenant.data:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # The client's own history read (upload.py ~L2101): stored list + tag names + hot/warm/cold + replies.
    history = _run(upload.get_broadcast_history(tenant_id=tenant_id)).get("data") or []

    dated: list[tuple[datetime, dict]] = []
    for record in history:
        ts = parse_ts(record.get("timestamp"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if start <= ts.astimezone(IST).date() <= end:
            dated.append((ts, record))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    matched = len(dated)
    dated = dated[:limit]

    rows = []
    for ts, record in dated:
        _refresh_in_memory(db, tenant_id, record)
        rows.append(_row(record, ts))

    totals = {k: sum(r[k] for r in rows)
              for k in ("recipients", "sent", "delivered", "read", "replied", "failed", "opted_out")}

    oldest = min((parse_ts(h.get("timestamp")) for h in history if parse_ts(h.get("timestamp"))), default=None)
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    may_be_incomplete = bool(
        len(history) >= HISTORY_CAP and oldest is not None and oldest.astimezone(IST).date() > start
    )

    return {
        "client_name": tenant.data.get("name") if isinstance(tenant.data, dict) else None,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "count": len(rows),
        "matched": matched,
        "totals": totals,
        "history_may_be_incomplete": may_be_incomplete,
        "broadcasts": rows,
    }
