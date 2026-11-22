"""What Meta itself charged this tenant this month, plus the AI-replies allowance and the daily
sending limit. Read-only.

The charges come ONLY from Meta's own pricing_analytics numbers on the tenant's WhatsApp
Business Account. If Meta can't or won't share them (no connection, an error, a partner credit
line that hides cost) the answer is "not available", never an estimate.

Meta docs (WhatsApp Business Management API, pricing analytics):
https://developers.facebook.com/docs/whatsapp/business-management-api/analytics
Request: GET /<WABA_ID>?fields=pricing_analytics.start(<unix>).end(<unix>).granularity(DAILY)
.metric_types(["COST","VOLUME"]).dimensions(["PRICING_CATEGORY"]). Every data point carries
start, end, pricing_category, volume and cost (cost is in the account's currency).
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config_dynamic import get_setting
from app.services import entitlements
from app.services.private_send import GRAPH_BASE, META_TIMEOUT_SECONDS, _json_or_empty, _meta_error_message

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))

CACHE_TTL_SECONDS = 3600
ERROR_CACHE_TTL_SECONDS = 300  # a Meta failure is remembered briefly so a page refresh doesn't hammer Meta
NOT_AVAILABLE_REASON = "Meta hasn't shared this month's charges yet."
GST_NOTE = "+ GST"
DEFAULT_CURRENCY = "INR"
NUMBERS_LINK = "/dashboard/numbers"

# Meta's pricing category -> our row key. Anything Meta adds later lands in "other".
_CATEGORY_TO_KEY = {
    "MARKETING": "marketing",
    "MARKETING_LITE": "marketing",
    "UTILITY": "utility",
    "AUTHENTICATION": "authentication",
    "AUTHENTICATION_INTERNATIONAL": "authentication",
    "SERVICE": "service",
}

ROW_LABELS = [
    ("marketing", "Marketing messages: offers and broadcasts"),
    ("utility", "Update messages: bills, reminders, order updates"),
    ("authentication", "OTP codes"),
    ("service", "Replies to customers within 24 hours"),
]
OTHER_LABEL = "Other messages"

# tenant_id -> (expires_at_monotonic, payload)
_CACHE: dict[str, tuple[float, dict]] = {}
# One lock per tenant so a burst of page opens after the cache expires makes a single Meta call.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def clear_cache() -> None:
    _CACHE.clear()


def _lock_for(tenant_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(tenant_id, threading.Lock())


def ist_month_window(now: datetime | None = None) -> tuple[str, int, int]:
    """("YYYY-MM", start_unix, end_unix) for the current IST calendar month, up to now."""
    now = now or datetime.now(timezone.utc)
    ist = now.astimezone(_IST)
    # Meta buckets DAILY data by UTC day, so start on the UTC midnight of the 1st.
    first = datetime(ist.year, ist.month, 1, tzinfo=timezone.utc)
    start, end = int(first.timestamp()), int(now.timestamp())
    if start >= end:
        # 00:00-05:30 IST on the 1st is still the previous UTC day: Meta needs start < end, so
        # look back one day rather than send a window Meta would reject.
        start = end - 86400
    return ist.strftime("%Y-%m"), start, end


def fetch_pricing(waba_id: str, token: str, start: int, end: int) -> dict:
    """One WABA's currency and pricing_analytics for [start, end]. The token goes in a header,
    never in the URL, so it can't reach a request log. Raises RuntimeError on any Meta problem."""
    fields = (
        "currency,"
        f"pricing_analytics.start({start}).end({end})"
        '.granularity(DAILY).metric_types(["COST","VOLUME"]).dimensions(["PRICING_CATEGORY"])'
    )
    with httpx.Client() as client:
        r = client.get(
            f"{GRAPH_BASE}/{waba_id}", params={"fields": fields},
            headers={"Authorization": f"Bearer {token}"}, timeout=META_TIMEOUT_SECONDS,
        )
    body = _json_or_empty(r)
    if r.status_code >= 400 or "error" in body:
        raise RuntimeError(f"Meta pricing_analytics failed: {_meta_error_message(body)}")
    return body


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def summarise(bodies: list[dict]) -> dict | None:
    """Add up Meta responses (one per WABA) into the charges payload. None when Meta's answer has
    no pricing data, or hides the cost (accounts on a partner's credit line get volume only)."""
    totals: dict[str, dict] = {}
    currency = None
    seen_points = 0
    cost_seen = False
    for body in bodies:
        analytics = body.get("pricing_analytics")
        if not isinstance(analytics, dict):
            return None
        currency = currency or (body.get("currency") or None)
        for block in analytics.get("data") or []:
            for point in block.get("data_points") or []:
                seen_points += 1
                if "cost" in point and point["cost"] is not None:
                    cost_seen = True
                key = _CATEGORY_TO_KEY.get(str(point.get("pricing_category") or "").upper(), "other")
                row = totals.setdefault(key, {"messages": 0, "cost": 0.0})
                row["messages"] += int(_number(point.get("volume")))
                row["cost"] += _number(point.get("cost"))
    if seen_points and not cost_seen:
        return None

    rows = []
    for key, label in ROW_LABELS:
        t = totals.get(key, {"messages": 0, "cost": 0.0})
        rows.append({"key": key, "label": label, "messages": t["messages"], "cost": round(t["cost"], 2)})
    other = totals.get("other")
    if other and (other["messages"] or other["cost"]):
        rows.append({"key": "other", "label": OTHER_LABEL, "messages": other["messages"], "cost": round(other["cost"], 2)})
    return {
        "currency": currency or DEFAULT_CURRENCY,
        "rows": rows,
        "total": {
            "messages": sum(r["messages"] for r in rows),
            "cost": round(sum(r["cost"] for r in rows), 2),
        },
        "gst_note": GST_NOTE,
    }


def _unavailable() -> dict:
    return {"available": False, "reason": NOT_AVAILABLE_REASON}


def _waba_ids(tenant_id: str) -> list[str]:
    """The tenant's WhatsApp Business Accounts. The app stores one per tenant today; summing a
    list keeps this correct if a tenant ever has several."""
    raw = get_setting("meta_waba_id", tenant_id=tenant_id)
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def get_charges(tenant_id: str, now: datetime | None = None) -> dict:
    """Meta's own numbers for the current IST month, cached per tenant for an hour."""
    cached = _CACHE.get(tenant_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    with _lock_for(tenant_id):
        # A caller that waited on the lock finds the answer the first one stored.
        cached = _CACHE.get(tenant_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        payload = _load_charges(tenant_id, now)
        ttl = CACHE_TTL_SECONDS if payload.get("available") else ERROR_CACHE_TTL_SECONDS
        _CACHE[tenant_id] = (time.monotonic() + ttl, payload)
        return payload


def _load_charges(tenant_id: str, now: datetime | None) -> dict:
    try:
        token = get_setting("meta_access_token", tenant_id=tenant_id)
        wabas = _waba_ids(tenant_id)
    except Exception:
        logger.warning("meta_charges: could not read Meta settings for tenant %s", tenant_id, exc_info=True)
        return _unavailable()
    if not token or not wabas:
        return _unavailable()

    month, start, end = ist_month_window(now)
    try:
        bodies = [fetch_pricing(waba, token, start, end) for waba in wabas]
    except Exception as exc:
        logger.warning("meta_charges: Meta did not answer for tenant %s: %s", tenant_id, exc)
        return _unavailable()
    summary = summarise(bodies)
    if summary is None:
        logger.warning("meta_charges: Meta's answer had no cost data for tenant %s", tenant_id)
        return _unavailable()
    return {"available": True, "month": month, **summary}


def ai_replies(db, tenant_id: str) -> dict:
    """AI replies used vs included in the current billing period. `included` is None when the
    plan has no allowance, and then there is no percentage."""
    empty = {"used": 0, "included": None, "pct": None}
    try:
        sub = db.table("tenant_subscriptions").select("period_start, period_end").eq("tenant_id", tenant_id).maybe_single().execute()
        row = (sub.data if sub else None) or {}
        period = entitlements.compute_period_key(row.get("period_start"), row.get("period_end"))
        res = (
            db.table("tenant_usage_counters").select("used, included")
            .eq("tenant_id", tenant_id).eq("period", period).eq("metric", "ai_reply")
            .limit(1).execute()
        )
        counter = (res.data or [None])[0] or {}
    except Exception:
        logger.warning("meta_charges: could not read AI reply usage for tenant %s", tenant_id, exc_info=True)
        return empty
    used = int(counter.get("used") or 0)
    included = int(counter.get("included") or 0) or None
    pct = round(used * 100 / included) if included else None
    return {"used": used, "included": included, "pct": pct}


def daily_limit(db, tenant_id: str) -> dict:
    """The biggest messaging limit Meta has given any of the tenant's numbers (None if none)."""
    tier = None
    try:
        rows = (
            db.table("phone_numbers").select("messaging_tier")
            .eq("tenant_id", tenant_id).neq("status", "archived").execute()
        ).data or []
        tiers = [int(r["messaging_tier"]) for r in rows if r.get("messaging_tier")]
        tier = max(tiers) if tiers else None
    except Exception:
        logger.warning("meta_charges: could not read messaging limits for tenant %s", tenant_id, exc_info=True)
    return {"tier": tier, "link": NUMBERS_LINK}
