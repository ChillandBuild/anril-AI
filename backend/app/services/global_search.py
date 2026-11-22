"""Global search (the box in the top bar): one question, up to four short groups of answers.

Every group follows the same rule as the module's own list, so a result never shows something the
person could not open today:
  customers  leads.view         callers only see the leads assigned to them (as the Customers list)
  orders     deals.view         no caller scoping (as Orders today)
  items      catalog.view
  chats      conversations.view callers only see leads assigned to them or needing a person (as Chats)
A group is left out when the person lacks its permission, when it has no hits, or when its own query
fails (logged, never a 500). The groups run side by side under one time budget.
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone

from app.dependencies.tenant import _has_permission
from app.services.deals import format_deal_number

logger = logging.getLogger(__name__)

MIN_LEN = 2
MAX_LEN = 60
GROUP_LIMIT = 5
BUDGET_SECONDS = 3.0
CHAT_DAYS = 90
CHAT_CANDIDATES = 150
CHAT_LEAD_CAP = 40
CALLER_LEAD_CAP = 120  # a caller's visible leads are put in one in_() filter, so keep the URL short
MAX_INFLIGHT_PER_USER = 2

# What may stay in a search word. Letters, digits and combining marks of any script are kept (Tamil and
# Hindi vowel signs are marks), plus a few punctuation characters. PostgREST's or(...) string treats
# , ( ) . " \ as structure, and % _ * are LIKE wildcards, so those are never kept.
_OR_PUNCT = set(" +-&'@")
_VALUE_PUNCT = _OR_PUNCT | set("/.")  # single-column filters only: bill numbers like B/25-26.12, items like 1.5 mm
_KEEP_CATEGORIES = {"L", "N", "M"}
# The same regex Orders uses for "D-0012" / "12", plus a leading "#".
_ORDER_NO_RE = re.compile(r"^(?:d-?)?0*(\d+)$", re.IGNORECASE | re.ASCII)
_PHONE_LIKE_RE = re.compile(r"^[\d\s+\-]+$", re.ASCII)

_SEGMENT_LABELS = {"A": "Hot", "B": "Warm", "C": "Cold", "D": "Not interested"}
_STAGE_WORDS = {"won": "paid", "awaiting_payment": "unpaid", "quoted": "quote", "lost": "lost"}
_IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------- small pure helpers

def _clean(text: str, punct: set[str]) -> str:
    return "".join(c for c in text.strip() if c in punct or unicodedata.category(c)[0] in _KEEP_CATEGORIES).strip()


def sanitize_or_term(q: str) -> str:
    """Safe to inline in a PostgREST or(...) filter: no comma, paren, dot, quote, backslash, star, percent
    or underscore. Letters of every script are kept."""
    return _clean(q, _OR_PUNCT)


def sanitize_value(q: str) -> str:
    """Safe for a single-column ilike: also keeps / and . (bill numbers like B/25-26/0012)."""
    return _clean(q, _VALUE_PUNCT)


def phone_digits(q: str) -> str | None:
    """The digits of a phone-looking query (digits, spaces, + and - only) with at least 4 digits."""
    if not _PHONE_LIKE_RE.match(q.strip()):
        return None
    digits = re.sub(r"\D", "", q, flags=re.ASCII)
    return digits if len(digits) >= 4 else None


def order_number(q: str) -> int | None:
    """12 for "D-0012", "d12", "12" or "#12"; None when q is not an order number. Long digit runs are
    phone numbers, not order numbers (and would not fit the column)."""
    match = _ORDER_NO_RE.match(q.strip().lstrip("#").strip())
    if not match:
        return None
    digits = match.group(1)
    return int(digits) if len(digits) <= 7 else None


def format_rupees(paise: int | None) -> str:
    """₹10,500 with Indian digit grouping (₹1,05,000); paise shown only when there are some."""
    paise = int(paise or 0)
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts) + "," + tail
    sign = "-" if paise < 0 else ""
    return f"{sign}₹{digits}" + (f".{rest:02d}" if rest else "")


def short_date(value) -> str:
    """"12 Nov" in Indian time; empty when the stamp is missing or unreadable."""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    stamp = stamp.astimezone(_IST)
    return f"{stamp.day} {stamp.strftime('%b')}"


def snippet_around(content: str, term: str, width: int = 60) -> str:
    """About `width` characters of the message around the first match, with … where it was cut."""
    text = " ".join((content or "").split())
    if len(text) <= width:
        return text
    at = text.lower().find(term.lower())
    if at < 0:
        return text[:width].rstrip() + "…"
    start = max(0, at - (width - len(term)) // 2)
    end = min(len(text), start + width)
    start = max(0, end - width)
    return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _caller_scope(ctx: dict) -> tuple[bool, str | None]:
    """(is a caller, caller id). A caller with no caller profile sees nothing in the scoped groups."""
    if ctx.get("role") == "caller":
        return True, ctx.get("caller_id")
    return False, None


# ---------------------------------------------------------------- the four groups

def _customers(db, ctx: dict, term: str, digits: str | None) -> list[dict]:
    scoped, caller_id = _caller_scope(ctx)
    if scoped and not caller_id:
        return []
    clauses = [f"name.ilike.*{term}*"]
    if digits:
        clauses.append(f"phone.ilike.*{digits}*")
    query = (
        db.table("leads").select("id, name, phone, segment, is_buyer")
        .eq("tenant_id", ctx["tenant_id"]).is_("deleted_at", "null")
        .or_(",".join(clauses))
    )
    if scoped:
        query = query.eq("assigned_to", caller_id)
    rows = query.order("created_at", desc=True).limit(GROUP_LIMIT).execute().data or []
    out = []
    for row in rows:
        detail = "Buyer" if row.get("is_buyer") else _SEGMENT_LABELS.get(row.get("segment") or "", "")
        out.append({
            "id": row["id"], "name": row.get("name") or row.get("phone") or "Unnamed",
            "phone": row.get("phone") or "", "detail": detail,
            "href": f"/dashboard/leads/{row['id']}",
        })
    return out


def _order_detail(row: dict) -> str:
    bits = [format_rupees(row.get("total_paise")), _STAGE_WORDS.get(row.get("stage") or "", ""), short_date(row.get("created_at"))]
    return " · ".join(b for b in bits if b)


def _orders(db, ctx: dict, q: str, term: str, value: str, digits: str | None) -> list[dict]:
    tenant_id = ctx["tenant_id"]
    cols = "id, deal_number, invoice_number, lead_id, total_paise, stage, created_at"

    def base():
        return db.table("deals").select(cols).eq("tenant_id", tenant_id)

    found: list[tuple[dict, str]] = []  # (deal row, why it matched) in rank order
    number = order_number(q)
    if number is not None:
        for row in base().eq("deal_number", number).order("created_at", desc=True).limit(GROUP_LIMIT).execute().data or []:
            found.append((row, "number"))
    if value:
        for row in (base().ilike("invoice_number", f"%{value}%").order("created_at", desc=True)
                    .limit(GROUP_LIMIT).execute().data or []):
            found.append((row, "bill"))
    # Orders of the customers whose name or phone matched (the same lookup the Orders search uses).
    if term:
        clauses = [f"name.ilike.*{term}*"]
        if digits:
            clauses.append(f"phone.ilike.*{digits}*")
        leads = (db.table("leads").select("id").eq("tenant_id", tenant_id).is_("deleted_at", "null")
                 .or_(",".join(clauses)).order("last_inbound_at", desc=True, nullsfirst=False)
                 .order("created_at", desc=True).limit(50).execute().data or [])
        lead_ids = [r["id"] for r in leads]
        if lead_ids:
            for row in base().in_("lead_id", lead_ids).order("created_at", desc=True).limit(GROUP_LIMIT).execute().data or []:
                found.append((row, "customer"))

    seen, picked = set(), []
    for row, why in found:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        picked.append((row, why))
        if len(picked) == GROUP_LIMIT:
            break
    if not picked:
        return []
    lead_ids = list({r["lead_id"] for r, _ in picked if r.get("lead_id")})
    names: dict[str, str] = {}
    if lead_ids:
        for lead in db.table("leads").select("id, name, phone").eq("tenant_id", tenant_id).in_("id", lead_ids).execute().data or []:
            names[lead["id"]] = lead.get("name") or lead.get("phone") or ""
    out = []
    for row, why in picked:
        who = names.get(row.get("lead_id") or "", "")
        if why == "bill" and row.get("invoice_number"):
            label = f"Bill {row['invoice_number']}"
        else:
            label = format_deal_number(int(row["deal_number"])) if row.get("deal_number") is not None else "Order"
        out.append({
            "id": row["id"], "label": f"{label} · {who}" if who else label,
            "detail": _order_detail(row), "href": f"/dashboard/deals/orders/{row['id']}",
        })
    return out


def _items(db, ctx: dict, value: str) -> list[dict]:
    if not value:
        return []
    rows = (
        db.table("catalog_items").select("id, name, price_paise, stock_quantity")
        .eq("tenant_id", ctx["tenant_id"]).ilike("name", f"%{value}%")
        .order("created_at", desc=True).limit(GROUP_LIMIT).execute().data or []
    )
    out = []
    for row in rows:
        bits = []
        if row.get("price_paise") is not None:
            bits.append(format_rupees(row["price_paise"]))
        stock = row.get("stock_quantity")
        if stock is not None:
            bits.append(f"{int(stock)} in stock" if int(stock) > 0 else "Out of stock")
        out.append({"id": row["id"], "name": row.get("name") or "Item", "detail": " · ".join(bits),
                    "href": f"/dashboard/catalog/items/{row['id']}"})
    return out


def _caller_lead_ids(db, tenant_id: str, caller_id: str) -> list[str]:
    """The leads a caller can open in Chats (assigned to them, or needing a person), most recently active
    first, capped so they fit one in_() filter."""
    found: dict[str, str] = {}
    for column, value in (("assigned_to", caller_id), ("needs_human_attention", True)):
        rows = (
            db.table("leads").select("id, last_inbound_at").eq("tenant_id", tenant_id).is_("deleted_at", "null")
            .eq(column, value).order("last_inbound_at", desc=True, nullsfirst=False)
            .limit(CALLER_LEAD_CAP).execute().data or []
        )
        for row in rows:
            found.setdefault(row["id"], str(row.get("last_inbound_at") or ""))
    return [lid for lid, _ in sorted(found.items(), key=lambda kv: kv[1], reverse=True)][:CALLER_LEAD_CAP]


def _chats(db, ctx: dict, term: str) -> list[dict]:
    scoped, caller_id = _caller_scope(ctx)
    if scoped and not caller_id:
        return []
    tenant_id = ctx["tenant_id"]
    visible: list[str] | None = None
    if scoped:
        # Cut to the caller's own leads BEFORE the newest-N limit, so other people's chats can't crowd them out.
        visible = _caller_lead_ids(db, tenant_id, caller_id)
        if not visible:
            return []
    since = (datetime.now(timezone.utc) - timedelta(days=CHAT_DAYS)).isoformat()
    query = (
        db.table("messages").select("lead_id, content, channel, created_at")
        # "[Template: ...]" / "[Template Broadcast: ...]" lines are bookkeeping for sent templates, not chat words.
        .eq("tenant_id", tenant_id).not_.like("content", "[Template%")
        .gte("created_at", since).ilike("content", f"%{term}%")
    )
    if visible is not None:
        query = query.in_("lead_id", visible)
    messages = query.order("created_at", desc=True).limit(CHAT_CANDIDATES).execute().data or []
    first_hit: dict[str, dict] = {}  # one hit per lead, newest first
    for m in messages:
        lid = m.get("lead_id")
        if lid and lid not in first_hit and len(first_hit) < CHAT_LEAD_CAP:
            first_hit[lid] = m
    if not first_hit:
        return []
    leads = (
        db.table("leads").select("id, name, phone, assigned_to, needs_human_attention")
        .eq("tenant_id", tenant_id).is_("deleted_at", "null").in_("id", list(first_hit)).execute().data or []
    )
    by_id = {l["id"]: l for l in leads}
    out = []
    for lid, m in first_hit.items():  # dict keeps newest-first order
        lead = by_id.get(lid)
        if not lead:
            continue
        if scoped and not (lead.get("assigned_to") == caller_id or lead.get("needs_human_attention") is True):
            continue
        out.append({
            "lead_id": lid, "name": lead.get("name") or lead.get("phone") or "Unnamed",
            "snippet": snippet_around(m.get("content") or "", term), "channel": m.get("channel") or "whatsapp",
            "date": m.get("created_at"), "href": f"/dashboard/conversations?lead={lid}",
        })
        if len(out) == GROUP_LIMIT:
            break
    return out


# ---------------------------------------------------------------- the whole search

GROUP_TITLES = (
    ("customers", "Customers"),
    ("orders", "Orders & bills"),
    ("items", "Items"),
    ("chats", "Chats"),
)


_inflight: dict[str, int] = {}
_inflight_lock = threading.Lock()


def _acquire(user: str) -> bool:
    with _inflight_lock:
        n = _inflight.get(user, 0)
        if n >= MAX_INFLIGHT_PER_USER:
            return False
        _inflight[user] = n + 1
        return True


def _release(user: str) -> None:
    with _inflight_lock:
        n = _inflight.get(user, 0) - 1
        if n > 0:
            _inflight[user] = n
        else:
            _inflight.pop(user, None)


def search(db, ctx: dict, q: str, *, budget: float = BUDGET_SECONDS) -> dict:
    """{"query": q, "groups": [{"key", "title", "items": [...]}]} in a fixed order, empty groups left out."""
    term = sanitize_or_term(q)
    value = sanitize_value(q)
    digits = phone_digits(q)
    jobs = {}
    if _has_permission(ctx, "leads.view") and term:
        jobs["customers"] = lambda: _customers(db, ctx, term, digits)
    if _has_permission(ctx, "deals.view") and (term or value):
        jobs["orders"] = lambda: _orders(db, ctx, q, term, value, digits)
    if _has_permission(ctx, "catalog.view") and value:
        jobs["items"] = lambda: _items(db, ctx, value)
    if _has_permission(ctx, "conversations.view") and value:
        jobs["chats"] = lambda: _chats(db, ctx, value)

    results: dict[str, list[dict]] = {}
    if jobs:
        user = str(ctx.get("user_id") or ctx.get("tenant_id"))
        if not _acquire(user):
            logger.warning("global search: too many searches in flight for one user, answered empty")
            return {"query": q, "groups": [], "busy": True}
        # The slot is held until the last group's thread has really finished, even if we stopped waiting.
        remaining = [len(jobs)]
        remaining_lock = threading.Lock()

        def guarded(fn):
            def run():
                try:
                    return fn()
                finally:
                    with remaining_lock:
                        remaining[0] -= 1
                        last = remaining[0] == 0
                    if last:
                        _release(user)
            return run

        pool = ThreadPoolExecutor(max_workers=len(jobs))
        try:
            # Each worker gets its own copy of the request's context vars (read-only mode, route name).
            futures = {pool.submit(contextvars.copy_context().run, guarded(fn)): key for key, fn in jobs.items()}
            done, not_done = wait(futures, timeout=budget)
            for fut in done:
                key = futures[fut]
                try:
                    results[key] = fut.result()
                except Exception:
                    logger.warning("global search: %s group failed, skipped", key, exc_info=True)
            for fut in not_done:
                logger.warning("global search: %s group ran out of time, skipped", futures[fut])
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    groups = [{"key": key, "title": title, "items": results[key]}
              for key, title in GROUP_TITLES if results.get(key)]
    return {"query": q, "groups": groups}
