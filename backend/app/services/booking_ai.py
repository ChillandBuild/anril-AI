"""v9.2 #19 — the AI's one booking ability: send the business's booking link.

The AI still cannot see a diary (deal_engine.py: "You cannot see a diary or slots, so never claim a
time is free or held"). When the business has Bookings set up — the booking link is on and at least
one service is active — the prompt gets one extra block with the link, so the AI can send it to
anyone who wants to book. The link itself only ever shows free times.

Cached per tenant for 60 s. Never raises: any problem means no block.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

_TTL = 60.0
_cache: dict[str, tuple[float, str]] = {}


def booking_link_url(token: str) -> str:
    base = (os.environ.get("FRONTEND_URL") or "https://www.anrilaitech.com").rstrip("/")
    return f"{base}/book/{token}"


def _build(db, tenant_id: str) -> str:
    rows = (
        db.table("booking_settings").select("link_token, link_on").eq("tenant_id", tenant_id).limit(1).execute()
    ).data or []
    if not rows or not rows[0].get("link_on") or not rows[0].get("link_token"):
        return ""
    services = (
        db.table("booking_services").select("name").eq("tenant_id", tenant_id).eq("active", True)
        .order("sort").limit(8).execute()
    ).data or []
    if not services:
        return ""
    names = ", ".join(s["name"] for s in services if s.get("name"))
    return (
        "\n\nBOOKINGS: customers can book a time themselves at this link: "
        f"{booking_link_url(rows[0]['link_token'])} (bookable: {names}). "
        "When someone wants to book, visit, or fix a time, send them this link in your reply. "
        "You cannot see free times: never say a time is free, held or booked; the link shows only free times "
        "and confirms the booking on WhatsApp."
    )


def prompt_block(db, tenant_id: str) -> str:
    now = time.monotonic()
    hit = _cache.get(tenant_id)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    try:
        text = _build(db, tenant_id)
    except Exception as e:  # e.g. migration 317 not applied yet
        logger.info("booking prompt block skipped for tenant %s: %s", tenant_id, type(e).__name__)
        text = ""
    _cache[tenant_id] = (now, text)
    return text


def clear_cache(tenant_id: str | None = None) -> None:
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(tenant_id, None)
