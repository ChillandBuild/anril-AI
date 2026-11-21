"""Reach results: "Paid within 7 days: 23 · ₹41,500" on each sent campaign in the history.

A PAID order is a deal with stage 'won' (the same definition Customers and Commerce use for
"buyer": routes/leads.py _buyer_facts). Its paid time is won_at, falling back to created_at.

A person counts ONCE for a campaign when they have a paid order whose paid time is from that
person's own send time up to 7 days later. Only their FIRST such order counts, for the count and
for the rupees. Each person's 7 days start at THEIR sent row's created_at (not the history
timestamp, which for a scheduled or deferred campaign is when it finished), so a campaign that
ran over two days is judged fairly.

People are matched by lead id; a recipient row with no lead id (an uploaded contact never saved
as a lead) is matched by phone, compared the same way as the rest of Reach (digits with the
country code). The same order can count for two campaigns whose windows overlap; each campaign's
figure stands on its own.

Built for the history list (up to 50 campaigns) in a handful of batched queries: the won deals
are read once, then only the sent rows of the people who have a won deal are read. Nothing runs
per recipient.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.services.reach_audience import _CHUNK, _chunks, _paged, _spellings, phone_key

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7


def _parse(raw) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _won_deals(db, tenant_id: str, since: datetime, until: datetime) -> list[dict]:
    """Won deals paid between `since` and `until` (paid time = won_at, else created_at)."""
    cols = "id,lead_id,total_paise,won_at,created_at"
    lo, hi = since.isoformat(), until.isoformat()
    with_won_at = _paged(lambda: db.table("deals").select(cols).eq("tenant_id", tenant_id).eq("stage", "won")
                         .gte("won_at", lo).lte("won_at", hi))
    without = _paged(lambda: db.table("deals").select(cols).eq("tenant_id", tenant_id).eq("stage", "won")
                     .is_("won_at", "null").gte("created_at", lo).lte("created_at", hi))
    return with_won_at + without


def paid_within_window(db, tenant_id: str, campaigns: list[dict], *, include_amount: bool,
                       now: datetime | None = None) -> dict[str, dict]:
    """broadcast_id -> {"paid_count", "paid_amount_inr" (None unless include_amount), "paid_window_open"}.

    campaigns: [{"broadcast_id", "sent_at"}]; sent_at (the history timestamp) is only used to
    bound the deal lookup and to say whether the 7 days are still running.
    include_amount: the caller has deals.view. Without it only the count is returned.
    """
    now = now or datetime.now(timezone.utc)
    window = timedelta(days=WINDOW_DAYS)
    starts = {str(c["broadcast_id"]): _parse(c.get("sent_at")) for c in campaigns if c.get("broadcast_id")}
    results = {bid: {"paid_count": 0, "paid_amount_inr": 0 if include_amount else None,
                     "paid_window_open": bool(at and at + window > now)} for bid, at in starts.items()}
    known = [at for at in starts.values() if at]
    if not results or not known:
        return results
    # A person's send time can be a little before the history stamp (immediate sends stamp the start).
    since, until = min(known) - timedelta(days=1), max(known) + window + timedelta(days=1)

    try:
        deals = _won_deals(db, tenant_id, since, until)
        deals_by_lead: dict[str, list[tuple[datetime, int, str]]] = {}
        for d in deals:
            paid_at = _parse(d.get("won_at")) or _parse(d.get("created_at"))
            if d.get("lead_id") and paid_at:
                deals_by_lead.setdefault(d["lead_id"], []).append((paid_at, int(d.get("total_paise") or 0), d["id"]))
        if not deals_by_lead:
            return results
        for lst in deals_by_lead.values():
            lst.sort()

        # phone key -> lead ids that have a won deal, so a recipient with no lead id can still match.
        lead_ids = sorted(deals_by_lead)
        lead_by_phone: dict[str, str] = {}
        for chunk in _chunks(lead_ids, 200):
            for row in _paged(lambda chunk=chunk: db.table("leads").select("id,phone")
                              .eq("tenant_id", tenant_id).in_("id", chunk)):
                key = phone_key(row.get("phone"))
                if key:
                    lead_by_phone[key] = row["id"]

        # Sent rows of just those people, for just these campaigns.
        bids = sorted(starts)
        sent_rows: list[dict] = []
        for chunk in _chunks(lead_ids, 200):
            sent_rows += _paged(lambda chunk=chunk: db.table("broadcast_recipients")
                                .select("id,broadcast_id,lead_id,phone,created_at")
                                .eq("tenant_id", tenant_id).eq("send_status", "sent")
                                .in_("broadcast_id", bids).in_("lead_id", chunk))
        for chunk in _chunks(sorted(lead_by_phone), _CHUNK):
            sent_rows += _paged(lambda chunk=chunk: db.table("broadcast_recipients")
                                .select("id,broadcast_id,lead_id,phone,created_at")
                                .eq("tenant_id", tenant_id).eq("send_status", "sent")
                                .in_("broadcast_id", bids).is_("lead_id", "null")
                                .in_("phone", _spellings(chunk)))

        counted: set[tuple[str, str]] = set()  # (campaign, person): a person counts once
        for row in sent_rows:
            bid = str(row.get("broadcast_id") or "")
            lead_id = row.get("lead_id") or lead_by_phone.get(phone_key(row.get("phone")) or "")
            sent_at = _parse(row.get("created_at")) or starts.get(bid)
            if bid not in results or not lead_id or not sent_at or (bid, lead_id) in counted:
                continue
            first = next(((p, amt) for p, amt, _id in deals_by_lead.get(lead_id, []) if sent_at <= p <= sent_at + window), None)
            if first is None:
                continue
            counted.add((bid, lead_id))
            results[bid]["paid_count"] += 1
            if include_amount:
                results[bid]["paid_amount_inr"] += first[1] / 100
    except Exception:
        logger.exception("Reach: paid-within-7-days lookup failed")
        for r in results.values():
            r["paid_count"], r["paid_amount_inr"] = None, None
    if include_amount:
        for r in results.values():
            if r["paid_amount_inr"] is not None:
                r["paid_amount_inr"] = round(r["paid_amount_inr"], 2)
    return results
