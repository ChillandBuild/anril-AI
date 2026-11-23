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
                       now: datetime | None = None, people: dict[str, list[dict]] | None = None) -> dict[str, dict]:
    """broadcast_id -> {"paid_count", "paid_amount_inr" (None unless include_amount), "paid_window_open"}.

    campaigns: [{"broadcast_id", "sent_at"}]; sent_at (the history timestamp) is only used to
    bound the deal lookup and to say whether the 7 days are still running.
    include_amount: the caller has deals.view. Without it only the count is returned.
    people: pass an empty dict to also learn WHO paid: it is filled with broadcast_id ->
    [{"lead_id", "paid_paise", "paid_at"}] using the same counting rule, one row per person.
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
            if people is not None:
                people.setdefault(bid, []).append({"lead_id": lead_id, "paid_paise": first[1], "paid_at": first[0].isoformat()})
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


# ── one campaign's results (the drawer on the Reach history) ─────────────────

def said_stop_counts(db, tenant_id: str, broadcast_ids: list[str]) -> dict[str, int]:
    """broadcast id -> how many people said stop after that campaign (opted_out_at set on their row)."""
    from app.services.reports_common import chunks, paged
    out = {str(b): 0 for b in broadcast_ids}
    for part in chunks(list(out), 50):
        for r in paged(lambda part=part: db.table("broadcast_recipients").select("id,broadcast_id")
                       .eq("tenant_id", tenant_id).in_("broadcast_id", part).not_.is_("opted_out_at", "null")):
            bid = str(r.get("broadcast_id"))
            if bid in out:
                out[bid] += 1
    return out


def back_per_rupee(paid_inr, cost_inr) -> float | None:
    """Rupees paid back for each rupee of message cost (an estimate), or None when there is no cost."""
    if paid_inr is None or not cost_inr:
        return None
    return round(float(paid_inr) / float(cost_inr), 2)


def campaign_results(db, tenant_id: str, item: dict, *, include_amount: bool, now: datetime | None = None) -> dict:
    """Everything the one-campaign drawer shows. `item` is the campaign's history entry.

    Rupee figures (paid amount, estimated cost, back per Re 1, each person's amount) are only present
    when include_amount (deals.view). Cost = messages sent x the one rate setting (meta_marketing_rate_inr).
    A part that fails to load comes back as None (the drawer shows a dash), never a made-up 0."""
    from app.services.reach_audience import cost_for
    from app.services.reports_common import chunks, paged
    bid = str(item["broadcast_id"])
    sent = int(item.get("sent") or 0)
    collected: dict[str, list[dict]] = {}
    paid = paid_within_window(db, tenant_id, [{"broadcast_id": bid, "sent_at": item.get("timestamp")}],
                              include_amount=include_amount, now=now, people=collected).get(bid) or {}
    try:
        said_stop = said_stop_counts(db, tenant_id, [bid]).get(bid)
    except Exception:
        logger.exception("Reach: said-stop count failed")
        said_stop = None

    rows = sorted(collected.get(bid, []), key=lambda r: r["paid_at"]) if paid.get("paid_count") is not None else []
    who: list[dict] = []
    if rows:
        by_id: dict[str, dict] = {}
        try:
            for part in chunks([r["lead_id"] for r in rows], 200):
                for lead in paged(lambda part=part: db.table("leads").select("id,name,phone")
                                  .eq("tenant_id", tenant_id).in_("id", part)):
                    by_id[lead["id"]] = lead
        except Exception:
            logger.exception("Reach: who-paid names failed")
        for r in rows:
            lead = by_id.get(r["lead_id"]) or {}
            person = {"lead_id": r["lead_id"], "name": lead.get("name"), "phone": lead.get("phone"), "paid_at": r["paid_at"]}
            if include_amount:
                person["paid_inr"] = round(r["paid_paise"] / 100, 2)
            who.append(person)

    out = {
        "broadcast_id": bid, "sent": sent, "said_stop": said_stop,
        "paid_count": paid.get("paid_count"), "paid_window_open": paid.get("paid_window_open", False),
        "paid_people": who,
    }
    if include_amount:
        cost = cost_for(sent)
        amount = paid.get("paid_amount_inr")
        out.update({"paid_amount_inr": amount, "cost_inr": cost["cost_inr"], "rate_inr": cost["rate_inr"],
                    "back_per_rupee": back_per_rupee(amount, cost["cost_inr"])})
    return out
