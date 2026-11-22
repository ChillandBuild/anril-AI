"""Anril OTP › Overview: one read-only summary of this month's codes, where they come from,
the SMS balance and a short "is everything working?" list.

Only reads. It never changes otp.py (it calls failed_webhook_count, read-only) and every query
filters tenant_id. A missing table or column never raises: that part comes back empty/zero and
the page says so in plain words (`available` false for the codes, ok null for a health row)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import otp as otp_svc

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
PAGE = 1000
SMS_LOW_BELOW = 500
# More than this share of Anril-made codes going unused turns the row amber.
UNUSED_WARN_PCT = 20
# The whole overview is kept per tenant for a minute: the page is opened often, the numbers move slowly.
CACHE_SECONDS = 60
_cache: dict[str, tuple[float, dict]] = {}

_ORIGIN_LABELS = {
    "dashboard": "Test codes from the dashboard",
    "api": "Your website or app",
    "bot": "The WhatsApp bot",
    "telecaller": "Telecallers",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _ist_start(day) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=_IST)


def _pct(part: int, whole: int) -> int | None:
    """Whole percent, rounded half up; None when there is nothing to divide by."""
    if not whole:
        return None
    return int(part * 100 / whole + 0.5)


def _change_pct(now_value: int, before: int) -> int | None:
    if not before:
        return None
    diff = (now_value - before) * 100 / before
    return int(diff + 0.5) if diff >= 0 else -int(-diff + 0.5)


def indian(n: int) -> str:
    """12345678 -> '1,23,45,678' (lakh/crore grouping)."""
    sign = "-" if n < 0 else ""
    s = str(abs(int(n)))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


def _month_bounds(today):
    """(this month start, next month start, previous month start) as IST dates."""
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    return first, nxt, prev


def _fetch_codes(db, tenant_id: str, since: datetime, until: datetime) -> list[dict]:
    out: list[dict] = []
    start = 0
    while True:
        # created_at first (the index is tenant_id, created_at); id breaks ties so pages never overlap.
        rows = (db.table("otp_requests")
                .select("id,status,source,origin,api_key_id,sms_status,whatsapp_status,fallback_sent_at,expires_at,created_at")
                .eq("tenant_id", tenant_id)
                .gte("created_at", since.isoformat()).lt("created_at", until.isoformat())
                .order("created_at").order("id").range(start, start + PAGE - 1).execute()).data or []
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def _count_codes(db, tenant_id: str, since: datetime, until: datetime) -> int:
    """How many codes were made in [since, until), without pulling the rows."""
    res = (db.table("otp_requests").select("id", count="exact").eq("tenant_id", tenant_id)
           .gte("created_at", since.isoformat()).lt("created_at", until.isoformat())
           .limit(1).execute())
    return int(res.count or 0)


def _empty_month() -> dict:
    return {"sent": 0, "prev_month_sent": 0, "change_pct": None, "verified": 0, "used_pct": None,
            "by_sms": 0, "by_whatsapp": 0, "backups": 0, "locked": 0, "not_requested": 0, "failed": 0}


def _key_labels(db, tenant_id: str) -> dict[str, str]:
    try:
        rows = (db.table("otp_api_keys").select("id,key_prefix").eq("tenant_id", tenant_id).execute()).data or []
    except Exception:
        logger.warning("otp overview: could not read otp_api_keys", exc_info=True)
        return {}
    return {r["id"]: f"Website or app, key {r['key_prefix']}…" for r in rows if r.get("id") and r.get("key_prefix")}


def _sources(rows: list[dict], labels: dict[str, str]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in rows:
        key_id = r.get("api_key_id")
        if key_id:
            gid, label = f"key:{key_id}", labels.get(key_id)
        else:
            origin = r.get("origin") or "api"
            gid, label = f"origin:{origin}", _ORIGIN_LABELS.get(origin, origin.capitalize())
        g = groups.setdefault(gid, {"key": gid, "label": label, "sent": 0, "anril": 0, "verified": 0})
        g["sent"] += 1
        if r.get("source") == "anril":
            g["anril"] += 1
            if r.get("status") == "verified":
                g["verified"] += 1
    ordered = sorted(groups.values(), key=lambda g: (-g["sent"], g["key"]))
    # A key we couldn't name (lookup failed, or it was deleted) still gets its own readable row.
    unnamed = 0
    for g in ordered:
        if g["label"] is None:
            unnamed += 1
            g["label"] = f"Website or app {unnamed}"
    seen: dict[str, int] = {}
    for g in ordered:
        seen[g["label"]] = seen.get(g["label"], 0) + 1
        if seen[g["label"]] > 1:
            g["label"] = f"{g['label']} ({seen[g['label']]})"
    return [{"key": g["key"], "label": g["label"], "sent": g["sent"], "used_pct": _pct(g["verified"], g["anril"])}
            for g in ordered]


def _balance(db, tenant_id: str) -> dict:
    out = {"sms_left": None, "checked_at": None, "low_below": SMS_LOW_BELOW}
    try:
        rows = (db.table("sms_wallet").select("sms_count,checked_at").eq("tenant_id", tenant_id)
                .limit(1).execute()).data or []
    except Exception:
        logger.warning("otp overview: could not read sms_wallet", exc_info=True)
        return out
    if rows and rows[0].get("sms_count") is not None:
        out["sms_left"] = int(rows[0]["sms_count"])
        out["checked_at"] = rows[0].get("checked_at")
    return out


# Only what this page uses: never pull the website-updates signing secret into memory.
_SETTINGS_COLUMNS = "wa_template_name,wa_template_language,sms_message_id,status_webhook_url"


def _settings(db, tenant_id: str) -> dict:
    try:
        rows = (db.table("otp_settings").select(_SETTINGS_COLUMNS).eq("tenant_id", tenant_id).limit(1).execute()).data or []
    except Exception:
        logger.warning("otp overview: could not read otp_settings", exc_info=True)
        return {}
    return rows[0] if rows else {}


def _health_item(key: str, label: str, ok: bool | None, detail: str) -> dict:
    return {"key": key, "label": label, "ok": ok, "detail": detail}


def _whatsapp_template_health(db, tenant_id: str, cfg: dict) -> dict:
    label = "WhatsApp code template approved"
    name, language = cfg.get("wa_template_name"), cfg.get("wa_template_language")
    if not name or not language:
        return _health_item("whatsapp_template", label, None, "Not set up")
    try:
        rows = (db.table("message_templates").select("status").eq("tenant_id", tenant_id)
                .eq("name", name).eq("language", language).limit(1).execute()).data or []
    except Exception:
        logger.warning("otp overview: could not read message_templates", exc_info=True)
        return _health_item("whatsapp_template", label, None, "Couldn't check right now")
    if not rows:
        return _health_item("whatsapp_template", label, False, "Template not found in your WhatsApp templates")
    status = str(rows[0].get("status") or "").upper()
    if status == "APPROVED":
        return _health_item("whatsapp_template", label, True, "Approved by WhatsApp")
    return _health_item("whatsapp_template", label, False, f"Status: {status.lower() or 'unknown'}")


def _sms_template_health(db, tenant_id: str, cfg: dict) -> dict:
    label = "SMS code template ready"
    message_id = cfg.get("sms_message_id")
    if not message_id:
        return _health_item("sms_template", label, None, "Not set up")
    try:
        rows = (db.table("sms_templates").select("status").eq("tenant_id", tenant_id)
                .eq("message_id", message_id).eq("status", "ready").limit(1).execute()).data or []
    except Exception:
        logger.warning("otp overview: could not read sms_templates", exc_info=True)
        return _health_item("sms_template", label, None, "Couldn't check right now")
    if rows:
        return _health_item("sms_template", label, True, "Ready to send")
    return _health_item("sms_template", label, None, "Not ready yet")


def _website_updates_health(db, tenant_id: str, cfg: dict) -> dict | None:
    if not cfg.get("status_webhook_url"):
        return None
    label = "Updates to your website"
    try:
        failed = otp_svc.failed_webhook_count(db, tenant_id, 7)
    except Exception:
        logger.warning("otp overview: could not count failed status updates", exc_info=True)
        return _health_item("website_updates", label, None, "Couldn't check right now")
    if not failed:
        return _health_item("website_updates", label, True, "No failed updates in the last 7 days")
    word = "update" if failed == 1 else "updates"
    return _health_item("website_updates", label, False, f"{indian(failed)} {word} to your website failed in the last 7 days")


def _unused_health(month_rows: list[dict], now: datetime) -> dict:
    label = "Codes not used this month"
    anril = [r for r in month_rows if r.get("source") == "anril"]
    if not anril:
        return _health_item("unused_codes", label, None, "No codes made by Anril yet")
    unused = 0
    for r in anril:
        if r.get("status") == "expired":
            unused += 1
        elif r.get("status") == "pending":
            expires = _parse_ts(r.get("expires_at"))
            if expires and expires < now:
                unused += 1
    pct = _pct(unused, len(anril)) or 0
    detail = f"{pct}% of codes were not used ({indian(unused)} of {indian(len(anril))})"
    return _health_item("unused_codes", label, pct <= UNUSED_WARN_PCT, detail)


def in_short(month: dict, available: bool = True) -> str:
    if not available:
        return "Your code numbers aren't available right now. Try again in a little while."
    sent = month["sent"]
    if not sent:
        return "No codes were sent this month yet."
    head = f"This month {indian(sent)} code{' was' if sent == 1 else 's were'} sent"
    if month["used_pct"] is not None:
        head += f" and {month['used_pct']}% were used"
    text = head + "."
    if month["by_sms"]:
        text += f" {indian(month['by_sms'])} went by SMS."
    return text


def overview(db, tenant_id: str, now: datetime | None = None) -> dict:
    """The overview for one tenant, kept for CACHE_SECONDS. Passing `now` (tests) skips the cache."""
    if now is not None:
        return _build(db, tenant_id, now)
    hit = _cache.get(tenant_id)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = _build(db, tenant_id, _now())
    if result["available"]:                       # a failed read is retried on the next open
        if len(_cache) > 500:
            _cache.clear()
        _cache[tenant_id] = (time.monotonic(), result)
    return result


def _build(db, tenant_id: str, now: datetime) -> dict:
    today = now.astimezone(_IST).date()
    first, nxt, prev_first = _month_bounds(today)
    first_dt, next_dt, prev_dt = _ist_start(first), _ist_start(nxt), _ist_start(prev_first)
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    daily = {d.isoformat(): {"day": d.isoformat(), "sent": 0, "verified": 0} for d in days}

    month = _empty_month()
    available = True
    month_rows: list[dict] = []
    try:
        # Rows: this month, plus the few days before it that the 7-day bars may reach back into.
        # Last month's total is only a count, never its rows.
        rows = _fetch_codes(db, tenant_id, min(first_dt, _ist_start(days[0])), next_dt)
        month["prev_month_sent"] = _count_codes(db, tenant_id, prev_dt, first_dt)
    except Exception:
        logger.warning("otp overview: could not read otp_requests for %s", tenant_id, exc_info=True)
        rows, available = [], False

    anril_made = 0
    for r in rows:
        created = _parse_ts(r.get("created_at"))
        if not created:
            continue
        day = daily.get(created.astimezone(_IST).date().isoformat())
        if day is not None:
            day["sent"] += 1
            if r.get("status") == "verified":
                day["verified"] += 1
        if created < first_dt:
            continue                                  # only here for the 7-day bars
        month_rows.append(r)
        month["sent"] += 1
        status = r.get("status")
        if r.get("source") == "anril":
            anril_made += 1
            if status == "verified":
                month["verified"] += 1
        if (r.get("sms_status") or "none") != "none":
            month["by_sms"] += 1
        if (r.get("whatsapp_status") or "none") != "none":
            month["by_whatsapp"] += 1
        if r.get("fallback_sent_at"):
            month["backups"] += 1
        if status in ("locked", "not_requested", "failed"):
            month[status] += 1
    month["used_pct"] = _pct(month["verified"], anril_made)
    month["change_pct"] = _change_pct(month["sent"], month["prev_month_sent"])

    cfg = _settings(db, tenant_id)
    health = [
        _whatsapp_template_health(db, tenant_id, cfg),
        _sms_template_health(db, tenant_id, cfg),
    ]
    website = _website_updates_health(db, tenant_id, cfg)
    if website:
        health.append(website)
    health.append(_unused_health(month_rows, now) if available
                  else _health_item("unused_codes", "Codes not used this month", None, "Couldn't check right now"))

    return {
        "available": available,
        "month": month,
        "daily_7": list(daily.values()),
        "sources": _sources(month_rows, _key_labels(db, tenant_id)) if available else [],
        "balance": _balance(db, tenant_id),
        "health": health,
        "in_short": in_short(month, available),
    }
