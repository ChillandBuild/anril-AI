# backend/app/services/sms_delivery.py
"""SMS delivery results: Bulk9's delivery callbacks (/webhook/bulk9/{tenant_id}) and the
reconcile job that fills gaps from Bulk9's reports.

Status rules (sms_messages.status):
- delivered and failed are final; a later or older callback never moves a row out of them
  (callbacks can arrive out of order, and Bulk9 retries).
- 'Sent'/'Pending'-style updates only move queued/sending/unknown rows to submitted.
- unknown = "we timed out, Bulk9 may have it". Never re-sent; resolved here from the logs.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config_dynamic import get_setting
from app.services import bulk9_client
from app.services.bulk9_client import Bulk9Error, Bulk9NotConfigured, Bulk9Timeout

logger = logging.getLogger(__name__)

FINAL = ("delivered", "failed")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DELIVERED = {"delivered", "delivrd", "success"}
_FAILED = {"failed", "undelivered", "undeliv", "rejected", "expired", "blocked", "error", "dnd"}
_PENDING = {"sent", "pending", "submitted", "accepted", "queued"}


def classify(status: Any) -> str | None:
    """Bulk9's status text → 'delivered' | 'failed' | 'submitted' | None (unrecognised).
    Capitalisation varies between examples ('Delivered' vs 'delivered')."""
    s = str(status or "").strip().lower()
    if s in _DELIVERED:
        return "delivered"
    if s in _FAILED:
        return "failed"
    if s in _PENDING:
        return "submitted"
    return None


def last10(phone: Any) -> str:
    digits = "".join(c for c in str(phone or "") if c.isdigit())
    return digits[-10:]


def _decimal(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d >= 0 else None


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _buy_rate(tenant_id: str) -> Decimal | None:
    return _decimal(get_setting("sms_buy_rate", tenant_id=tenant_id))


def _is_uuid(v: Any) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False


def _find_message(db, tenant_id: str, *, udf1: Any, request_id: Any, phone: Any) -> dict | None:
    # udf1 carries our own row id (set at send time), the strongest match.
    if _is_uuid(udf1):
        rows = (db.table("sms_messages").select("*").eq("tenant_id", tenant_id).eq("id", str(udf1))
                .limit(1).execute().data or [])
        if rows:
            return rows[0]
    if request_id:
        rows = (db.table("sms_messages").select("*").eq("tenant_id", tenant_id)
                .eq("request_id", str(request_id)).limit(50).execute().data or [])
        want = last10(phone)
        for r in rows:
            if not want or last10(r.get("phone")) == want:
                return r
    return None


def apply_update(db, tenant_id: str, msg: dict, *, status: str, reason: str | None = None,
                 sms_count: Any = None, amount: Any = None, request_id: Any = None,
                 at: datetime | None = None) -> bool:
    """Apply one delivery result to a message row. Returns True if the row changed."""
    current = msg.get("status")
    if current in FINAL:
        return False
    if status == "submitted" and current == "submitted":
        return False
    now = datetime.now(timezone.utc)
    update: dict[str, Any] = {"status": status, "updated_at": now.isoformat()}
    if status == "failed":
        update["failure_reason"] = (reason or "Not delivered")[:300]
    if status == "delivered":
        update["delivered_at"] = (at or now).isoformat()
    # Later used in a Bulk9 URL path (/dev/dlr/{request_id}), so only plain ids are kept.
    if request_id and not msg.get("request_id") and _REQUEST_ID.fullmatch(str(request_id)):
        update["request_id"] = str(request_id)
    if not msg.get("submitted_at"):
        update["submitted_at"] = now.isoformat()
    count = _int(sms_count)
    if count is not None and count > 0:
        update["sms_count"] = count
        rate = _buy_rate(tenant_id)
        if rate is not None:
            update["cost_amount"] = str(rate * count)
    charged = _decimal(amount)
    if charged is not None:
        update["charged_amount"] = str(charged)
    # Conditional on the status we read, so a concurrent final update isn't overwritten.
    res = (db.table("sms_messages").update(update).eq("id", msg["id"]).eq("tenant_id", tenant_id)
           .eq("status", current).execute())
    return bool(res.data)


def _dedupe_key(p: dict) -> str:
    parts = [str(p.get(k) or "") for k in ("request_id", "mobile", "status", "delivery_attempt",
                                             "dlr_attempt", "delivery_timestamp")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def handle_callback(db, tenant_id: str, payload: dict) -> dict:
    """One Bulk9 SMS callback (already authenticated). Stored first (dedupe + audit), then
    applied. A callback for a message we can't find yet stays unmatched for the reconcile job."""
    key = _dedupe_key(payload)
    try:
        ins = db.table("sms_delivery_events").insert({
            "tenant_id": tenant_id,
            "request_id": str(payload.get("request_id") or payload.get("server_request_id") or "") or None,
            "phone": last10(payload.get("mobile")) or None,
            "status": str(payload.get("status") or "")[:40] or None,
            "dedupe_key": key,
            "matched": False,
            "payload": payload,
        }).execute()
    except Exception as exc:  # unique violation = Bulk9 retried a callback we already have
        if "duplicate" in str(exc).lower() or "23505" in str(exc):
            return {"status": "duplicate"}
        raise
    event_id = (ins.data or [{}])[0].get("id")
    return _apply_event(db, tenant_id, event_id, payload)


def _apply_event(db, tenant_id: str, event_id: str | None, p: dict) -> dict:
    status = classify(p.get("status") or p.get("status_lower"))
    msg = _find_message(db, tenant_id, udf1=p.get("udf1"),
                        request_id=p.get("request_id") or p.get("server_request_id"), phone=p.get("mobile"))
    if not msg:
        return {"status": "unmatched"}
    if status:
        at = None
        ts = _int(p.get("delivery_timestamp"))
        if ts:
            at = datetime.fromtimestamp(ts, tz=timezone.utc)
        apply_update(db, tenant_id, msg, status=status,
                     reason=p.get("status_description") or p.get("description") or p.get("failure_reason"),
                     sms_count=p.get("sms_count"), amount=p.get("amount_debited"),
                     request_id=p.get("request_id"), at=at)
    else:
        logger.warning("Bulk9 callback with unrecognised status %r (tenant %s)", p.get("status"), tenant_id)
    if event_id:
        db.table("sms_delivery_events").update({"matched": True}).eq("id", event_id).execute()
    return {"status": "ok"}


# ---------------------------------------------------------------- reconcile job

def _report_rows(body: dict) -> list[dict]:
    data = body.get("data")
    if isinstance(data, dict):
        data = data.get("data") or data.get("reports") or [data]
    return [r for r in (data or []) if isinstance(r, dict)]


async def reconcile(db, *, now: datetime | None = None, limit: int = 200) -> dict:
    """Every 15 minutes:
    1. callbacks that arrived before their message was recorded → match again;
    2. submitted rows with no final status after 10 minutes → Bulk9 delivery report (7-day window);
    3. unknown rows (send timed out) → Bulk9 logs by udf1 (3-day window). Not there after 30
       minutes means Bulk9 never accepted it → failed; still nothing is re-sent."""
    now = now or datetime.now(timezone.utc)
    stats = {"events": 0, "reports": 0, "unknown_resolved": 0, "errors": 0}

    events = (db.table("sms_delivery_events").select("*").eq("matched", False)
              .gte("received_at", (now - timedelta(days=7)).isoformat()).limit(limit).execute().data or [])
    for ev in events:
        if _apply_event(db, ev["tenant_id"], ev["id"], ev.get("payload") or {}).get("status") == "ok":
            stats["events"] += 1

    rows = (db.table("sms_messages").select("*").in_("status", ["submitted", "unknown"])
            .gte("updated_at", (now - timedelta(days=7)).isoformat())
            .lte("updated_at", (now - timedelta(minutes=10)).isoformat())
            .limit(limit).execute().data or [])
    keys: dict[str, str | None] = {}
    for m in rows:
        tid = m["tenant_id"]
        if tid not in keys:
            try:
                keys[tid] = bulk9_client.get_api_key(tid)
            except Bulk9NotConfigured:
                keys[tid] = None
        key = keys[tid]
        if not key:
            continue
        rid = m.get("request_id") or ""
        try:
            if m["status"] == "submitted" and rid and not rid.startswith("dry-run"):
                body = await bulk9_client.delivery_report(key, rid)
                for r in _report_rows(body):
                    if last10(r.get("mobile") or r.get("number")) in ("", last10(m["phone"])):
                        st = classify(r.get("status"))
                        if st and st != "submitted":
                            apply_update(db, tid, m, status=st, reason=r.get("status_description") or r.get("description"),
                                         sms_count=r.get("sms_count"), amount=r.get("amount_debited") or r.get("debit"))
                            stats["reports"] += 1
                        break
            elif m["status"] == "unknown":
                await _resolve_unknown(db, key, m, now, stats)
        except (Bulk9Error, Bulk9Timeout) as exc:
            stats["errors"] += 1
            logger.info("SMS reconcile: %s for message %s", exc, m["id"])
    return stats


async def _resolve_unknown(db, key: str, m: dict, now: datetime, stats: dict) -> None:
    sent = datetime.fromisoformat(str(m.get("claimed_at") or m["updated_at"]).replace("Z", "+00:00"))
    day = sent.date()
    body = await bulk9_client.sms_logs(key, date_from=(day - timedelta(days=1)).isoformat(),
                                       date_to=min(day + timedelta(days=1), now.date()).isoformat(), limit=1000)
    for r in _report_rows(body) or [x for x in (body.get("logs") or []) if isinstance(x, dict)]:
        if str(r.get("udf1") or "") == str(m["id"]):
            st = classify(r.get("status")) or "submitted"
            apply_update(db, m["tenant_id"], m, status=st, request_id=r.get("request_id"),
                         reason=r.get("status_description") or r.get("description"),
                         sms_count=r.get("sms_count"), amount=r.get("amount_debited") or r.get("debit"))
            stats["unknown_resolved"] += 1
            return
    if now - sent > timedelta(minutes=30):
        apply_update(db, m["tenant_id"], m, status="failed",
                     reason="Bulk9 has no record of this SMS — it was not sent")
        stats["unknown_resolved"] += 1
