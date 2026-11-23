"""v9.2 Replies & handover: three more reasons to pass a chat to a person, and who gets it.

  G  the customer is angry or complains (words in the message; English, Tanglish and Tamil)
  H  an order above the owner's amount (inbox_config.order_above_paise, default Rs 25,000), or a bulk order
  I  the customer sends a photo (the AI cannot read images)

Who gets it: inbox_config.handover_to (a teammate) when the chat has no owner yet; if nobody has
replied after 15 minutes, inbox_config.backup_to takes it (services/handover_alerts.py).
All of it lives in the inbox_config JSON setting: no new table.
"""
import re
from datetime import datetime, timedelta, timezone

DEFAULT_ORDER_ABOVE_PAISE = 25_000_00
REASONS = {
    "G": "Customer is angry or complaining",
    "H": "Big or bulk order",
    "I": "Customer sent a photo",
}

_ANGRY_RE = re.compile(
    r"\bworst\b|\bcheat(ed|ing|ers?)?\b|\bfraud\b|\bscam\b|\bangry\b|\bcomplain(t|ts|ing)?\b|\bdisgust|"
    r"\buseless\b|\bpathetic\b|\bridiculous\b|\bvery bad\b|\bnot happy\b|\bnot satisfied\b|\bconsumer court\b|"
    r"\bmoney back\b|\bpoor service\b|\bwaste of (money|time)\b|"
    r"\bmosam\b|\bmosamana\b|\bkevalam\b|\bemathitinga\b|\bemathittinga\b|\bwaste\b|"
    r"மோசம்|ஏமாற்ற|கேவலம்|புகார்",
    re.IGNORECASE,
)
_BULK_RE = re.compile(
    r"\bbulk\b|\bwholesale\b|\bin bulk\b|\bdealer(ship)?\b|\bresell(er|ing)?\b|"
    r"\b([2-9]\d|\d{3,})\s*(pcs|pieces|nos|units|qty|sets|boxes|cartons|kg)\b",
    re.IGNORECASE,
)


def angry(message: str) -> bool:
    return bool(_ANGRY_RE.search(message or ""))


def bulk(message: str) -> bool:
    return bool(_BULK_RE.search(message or ""))


def order_above(cfg: dict) -> int:
    try:
        value = int(cfg.get("order_above_paise") or DEFAULT_ORDER_ABOVE_PAISE)
    except (TypeError, ValueError):
        value = DEFAULT_ORDER_ABOVE_PAISE
    return max(value, 100)


def big_order(db, tenant_id: str, lead_id: str, message: str, cfg: dict, now: datetime | None = None) -> bool:
    """A bulk order in the message, or an open order for this customer (made in the last 15 minutes,
    e.g. by the AI agent in this reply) at or above the owner's amount."""
    if bulk(message):
        return True
    since = ((now or datetime.now(timezone.utc)) - timedelta(minutes=15)).isoformat()
    try:
        rows = (db.table("deals").select("total_paise").eq("tenant_id", tenant_id).eq("lead_id", lead_id)
                .gte("created_at", since).neq("stage", "lost").execute().data or [])
    except Exception:
        return False
    return any(int(r.get("total_paise") or 0) >= order_above(cfg) for r in rows)


def first_owner(cfg: dict, lead_owner: str | None) -> str | None:
    """The chat's own teammate if it has one, else the named person from Replies & handover."""
    return lead_owner or cfg.get("handover_to") or None
