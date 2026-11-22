"""WhatsApp › QR & links (v9.2 #24). Schema: migration 317 (qr_links, qr_events, leads.qr_link_id).

A printed QR points at FRONTEND_URL/q/<CODE>. That page asks the public API for a wa.me link to the
business's main WhatsApp number, with the first message plus a "(Q-<CODE>)" tag. When the customer's
message arrives, handle_inbound_qr() (wired into the webhook by the planner) reads the tag and stamps
the lead's first-touch "came from"."""
from __future__ import annotations

import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from urllib.parse import quote

logger = logging.getLogger(__name__)

# No 0/O/1/I: a code is read aloud or typed from a printed sticker.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 5
CODE_ATTEMPTS = 10
CODE_RE = re.compile(r"^[A-Z0-9]{4,8}$")
TAG_RE = re.compile(r"\(Q-([A-Z0-9]{4,8})\)", re.IGNORECASE)

NAME_MAX = 80
MESSAGE_MAX = 300
_PAGE = 1000
_ID_CHUNK = 100


class QrError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ------------------------------------------------------------------ small helpers

def generate_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def is_unique_violation(err: Exception) -> bool:
    text = str(err).lower()
    return getattr(err, "code", None) == "23505" or "23505" in text or "duplicate key" in text


def frontend_base() -> str:
    # Same setting the order bills use (services/orders.py bill_url).
    return (os.environ.get("FRONTEND_URL") or "https://www.anrilaitech.com").rstrip("/")


def qr_url(code: str) -> str:
    return f"{frontend_base()}/q/{code}"


def clean_name(value: str | None) -> str:
    text = " ".join((value or "").split())
    if not text:
        raise QrError("Give this QR a name, like the place it will hang.")
    if len(text) > NAME_MAX:
        raise QrError(f"The name can be at most {NAME_MAX} letters.")
    return text


def clean_message(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        raise QrError("Write the first message the customer will send.")
    if len(text) > MESSAGE_MAX:
        raise QrError(f"The first message can be at most {MESSAGE_MAX} letters.")
    return text


def build_wa_url(number: str, first_message: str, code: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    text = f"{first_message.strip()} (Q-{code})"
    return f"https://wa.me/{digits}?text={quote(text, safe='')}"


def primary_whatsapp_number(db, tenant_id: str) -> str | None:
    """The tenant's active primary WhatsApp number (same rule as inbound_leads._primary_whatsapp_number)."""
    rows = (
        db.table("phone_numbers").select("number,role").eq("tenant_id", tenant_id).eq("status", "active")
        .execute().data
        or []
    )
    if not rows:
        return None
    primary = next((r for r in rows if r.get("role") == "primary"), None)
    return (primary or rows[0]).get("number")


def _paged(make_query) -> list[dict]:
    """Every row of a query, past PostgREST's 1000-row page. `make_query()` builds a fresh query."""
    out: list[dict] = []
    start = 0
    while True:
        rows = make_query().range(start, start + _PAGE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < _PAGE:
            return out
        start += _PAGE


# ------------------------------------------------------------------ places

def load_places(db, tenant_id: str) -> tuple[list[dict], dict[str, str]]:
    """(not-archived places for the picker, id -> name for every place). Empty when the read fails."""
    try:
        rows = (
            db.table("stock_places").select("id,name,archived,sort_order").eq("tenant_id", tenant_id)
            .order("sort_order").execute().data
            or []
        )
    except Exception as e:  # the Places feature is optional for this page
        logger.warning("qr_links: stock_places read failed tenant=%s: %s", tenant_id, e)
        return [], {}
    names = {r["id"]: r.get("name") or "" for r in rows}
    return [{"id": r["id"], "name": r.get("name") or ""} for r in rows if not r.get("archived")], names


def _check_place(db, tenant_id: str, place_id: str) -> None:
    try:
        rows = (
            db.table("stock_places").select("id").eq("tenant_id", tenant_id).eq("id", place_id)
            .limit(1).execute().data
        )
    except Exception as e:
        logger.warning("qr_links: place check failed tenant=%s: %s", tenant_id, e)
        raise QrError("Couldn't check that place. Try again.", 400)
    if not rows:
        raise QrError("That place wasn't found.", 400)


# ------------------------------------------------------------------ stats

def link_stats(db, tenant_id: str, link_ids: list[str], *, include_money: bool) -> dict[str, dict]:
    """link id -> {opens, chats, new_customers, paid_orders, paid_paise?}. All time.
    paid = the deals of the link's customers with money still in after refunds."""
    stats = {i: {"opens": 0, "chats": 0, "new_customers": 0, "paid_orders": 0} for i in link_ids}
    if include_money:
        for s in stats.values():
            s["paid_paise"] = 0
    if not link_ids:
        return stats

    # Exact counts (no rows come back): one per QR per kind. Cheaper than reading thousands of event
    # rows, and a business has few QRs. PostgREST can't group a count, so this can't be one query.
    for link_id in link_ids:
        for kind, key in (("open", "opens"), ("chat", "chats")):
            res = (
                db.table("qr_events").select("id", count="exact").eq("tenant_id", tenant_id)
                .eq("qr_link_id", link_id).eq("kind", kind).limit(1).execute()
            )
            stats[link_id][key] = int(res.count or 0)

    leads = _paged(lambda: (
        db.table("leads").select("id,qr_link_id").eq("tenant_id", tenant_id).in_("qr_link_id", link_ids)
        .is_("deleted_at", "null").order("id")
    ))
    link_of: dict[str, str] = {}
    for lead in leads:
        if lead.get("qr_link_id") in stats:
            link_of[lead["id"]] = lead["qr_link_id"]
            stats[lead["qr_link_id"]]["new_customers"] += 1

    lead_ids = list(link_of)
    for i in range(0, len(lead_ids), _ID_CHUNK):
        chunk = lead_ids[i:i + _ID_CHUNK]
        deals = _paged(lambda: (
            db.table("deals").select("id,lead_id,paid_paise,refunded_paise").eq("tenant_id", tenant_id)
            .in_("lead_id", chunk).order("id")
        ))
        for deal in deals:
            net = int(deal.get("paid_paise") or 0) - int(deal.get("refunded_paise") or 0)
            link_id = link_of.get(deal.get("lead_id"))
            if net > 0 and link_id:
                stats[link_id]["paid_orders"] += 1
                if include_money:
                    stats[link_id]["paid_paise"] += net
    return stats


def build_items(db, tenant_id: str, rows: list[dict], *, include_money: bool, place_names: dict[str, str]) -> list[dict]:
    stats = link_stats(db, tenant_id, [r["id"] for r in rows], include_money=include_money)
    return [
        {
            "id": r["id"],
            "code": r["code"],
            "name": r["name"],
            "first_message": r["first_message"],
            "place_id": r.get("place_id"),
            "place_name": place_names.get(r.get("place_id") or "") or None,
            "archived": bool(r.get("archived")),
            "url": qr_url(r["code"]),
            "stats": stats[r["id"]],
        }
        for r in rows
    ]


# ------------------------------------------------------------------ staff actions

def list_links(db, tenant_id: str, *, include_money: bool) -> dict:
    rows = (
        db.table("qr_links").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True)
        .execute().data
        or []
    )
    places, names = load_places(db, tenant_id)
    # Live QRs first, archived ones at the bottom; newest first inside each group.
    rows.sort(key=lambda r: bool(r.get("archived")))
    return {"items": build_items(db, tenant_id, rows, include_money=include_money, place_names=names), "places": places}


def create_link(db, tenant_id: str, *, name: str, first_message: str, place_id: str | None,
                created_by: str | None) -> dict:
    name, first_message = clean_name(name), clean_message(first_message)
    if place_id:
        _check_place(db, tenant_id, place_id)
    last: Exception | None = None
    for _ in range(CODE_ATTEMPTS):
        try:
            res = db.table("qr_links").insert({
                "tenant_id": tenant_id, "code": generate_code(), "name": name,
                "first_message": first_message, "place_id": place_id or None, "created_by": created_by,
            }).execute()
            return res.data[0]
        except Exception as e:
            if not is_unique_violation(e):
                raise
            last = e
    logger.error("qr_links: no free code after %d tries: %s", CODE_ATTEMPTS, last)
    raise QrError("Couldn't make a new code. Please try again.", 503)


def update_link(db, tenant_id: str, link_id: str, changes: dict) -> dict | None:
    """`changes` holds only the fields the caller sent. None if the QR isn't this business's."""
    patch: dict = {}
    if "name" in changes:
        patch["name"] = clean_name(changes["name"])
    if "first_message" in changes:
        patch["first_message"] = clean_message(changes["first_message"])
    if "place_id" in changes:
        place_id = changes["place_id"] or None
        if place_id:
            _check_place(db, tenant_id, place_id)
        patch["place_id"] = place_id
    if "archived" in changes and changes["archived"] is not None:
        patch["archived"] = bool(changes["archived"])
    existing = db.table("qr_links").select("*").eq("tenant_id", tenant_id).eq("id", link_id).limit(1).execute().data
    if not existing:
        return None
    if not patch:
        return existing[0]
    from datetime import datetime, timezone
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = db.table("qr_links").update(patch).eq("tenant_id", tenant_id).eq("id", link_id).execute()
    return (res.data or [None])[0] or {**existing[0], **patch}


# ------------------------------------------------------------------ public page

def find_live_link(db, code: str) -> dict | None:
    code = (code or "").strip().upper()
    if not CODE_RE.match(code):
        return None
    rows = db.table("qr_links").select("*").eq("code", code).eq("archived", False).limit(1).execute().data
    return rows[0] if rows else None


def log_event(db, tenant_id: str, link_id: str, kind: str, lead_id: str | None = None) -> None:
    """Best effort: a counting failure must never break a scan or a webhook."""
    try:
        row = {"tenant_id": tenant_id, "qr_link_id": link_id, "kind": kind}
        if lead_id:
            row["lead_id"] = lead_id
        db.table("qr_events").insert(row).execute()
    except Exception as e:
        logger.warning("qr_links: %s event not logged: %s", kind, e)


OPEN_DEDUPE_SECONDS = 10
_recent_opens: dict[str, float] = {}
_recent_lock = threading.Lock()
OPEN_CAP_PER_HOUR = 300
_open_log_times: dict[str, deque] = {}


def _is_repeat_open(client_key: str | None, code: str) -> bool:
    """True when this visitor already opened this QR in the last few seconds (a double tap or a reload).
    In-process, like the rate limiter: a restart only means one extra count."""
    if not client_key:
        return False
    now = time.monotonic()
    key = f"{client_key}|{code}"
    with _recent_lock:
        if len(_recent_opens) > 5000:
            for k in [k for k, t in _recent_opens.items() if now - t >= OPEN_DEDUPE_SECONDS]:
                del _recent_opens[k]
        last = _recent_opens.get(key)
        if last is not None and now - last < OPEN_DEDUPE_SECONDS:
            return True
        _recent_opens[key] = now
        return False


def _under_open_cap(code: str) -> bool:
    """At most OPEN_CAP_PER_HOUR logged opens per code per hour, so a script hammering one QR can't
    flood qr_events. Past the cap the redirect still works; it just isn't counted."""
    now = time.monotonic()
    with _recent_lock:
        hits = _open_log_times.setdefault(code, deque())
        while hits and now - hits[0] >= 3600:
            hits.popleft()
        if len(hits) >= OPEN_CAP_PER_HOUR:
            return False
        hits.append(now)
        return True


def public_redirect(db, code: str, client_key: str | None = None) -> str | None:
    """The wa.me link for a printed QR, or None (unknown / archived / no WhatsApp number).
    `client_key` (the visitor's IP) stops a double tap counting as two scans."""
    link = find_live_link(db, code)
    if not link:
        return None
    number = primary_whatsapp_number(db, link["tenant_id"])
    if not re.sub(r"\D", "", number or ""):
        logger.warning("qr_links: tenant %s has no active WhatsApp number for QR %s", link["tenant_id"], link["code"])
        return None
    if not _is_repeat_open(client_key, link["code"]) and _under_open_cap(link["code"]):
        log_event(db, link["tenant_id"], link["id"], "open")
    return build_wa_url(number, link["first_message"], link["code"])


# ------------------------------------------------------------------ webhook hook

def handle_inbound_qr(db, tenant_id: str, lead_id: str, text: str, *, is_new_lead: bool) -> str | None:
    """Read a "(Q-XXXX)" tag in an inbound message. Counts a 'chat' and, on the customer's first touch,
    stamps leads.qr_link_id (and source/opt_in_source 'qr' for a brand-new lead). Returns the QR's id,
    or None. Never raises."""
    try:
        match = TAG_RE.search(text or "")
        if not match or not lead_id:
            return None
        code = match.group(1).upper()
        links = (
            db.table("qr_links").select("id").eq("tenant_id", tenant_id).eq("code", code).eq("archived", False)
            .limit(1).execute().data
        )
        if not links:
            return None
        link_id = links[0]["id"]
        log_event(db, tenant_id, link_id, "chat", lead_id)

        first_touch = is_new_lead
        if not first_touch:
            lead = (
                db.table("leads").select("id,qr_link_id,ad_campaign_id").eq("tenant_id", tenant_id)
                .eq("id", lead_id).limit(1).execute().data
            )
            first_touch = bool(lead) and not lead[0].get("qr_link_id") and not lead[0].get("ad_campaign_id")
        if first_touch:
            patch: dict = {"qr_link_id": link_id}
            if is_new_lead:
                patch.update({"source": "qr", "opt_in_source": "qr"})
            db.table("leads").update(patch).eq("tenant_id", tenant_id).eq("id", lead_id).execute()
        return link_id
    except Exception as e:
        logger.warning("qr_links: inbound tag not handled tenant=%s lead=%s: %s", tenant_id, lead_id, e)
        return None
