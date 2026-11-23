"""Reports > Campaigns: the Reach campaigns sent in the picked days and what came back.

Reads the same history the Reach page shows (app_settings "broadcast_history", last 50 sends) and, per
campaign, counts from broadcast_recipients: replied = people whose reply was read, said stop = people who
opted out of that send. "Paid in 7 days" is services/reach_results (a person counts once, first paid order
within 7 days of their own send). Rupees are paid_paise and need deals.view.
"""
import json
from datetime import timedelta

from app.services.reports_common import Flags, Period, chunks, paged, plural, safe, sentence
from app.services.reports_data import won_deals  # noqa: F401  (kept for symmetry with the other tabs)

WINDOW_DAYS = 7


def read_history(db, tenant_id: str) -> list[dict]:
    row = db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", "broadcast_history").maybe_single().execute()
    raw = (row.data or {}).get("value") if row else None
    try:
        data = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []
    return [h for h in data if isinstance(h, dict) and h.get("broadcast_id")]


def campaigns_in(history: list[dict], period: Period) -> list[dict]:
    from app.services.reach_results import _parse
    out = []
    for h in history:
        at = _parse(h.get("timestamp"))
        if at and period.start_utc <= at < period.end_utc:
            out.append(h)
    return sorted(out, key=lambda h: str(h.get("timestamp")), reverse=True)


def recipient_counts(db, tenant_id: str, ids: list[str]) -> dict[str, dict]:
    """broadcast id -> {replied, said_stop}."""
    out = {i: {"replied": 0, "said_stop": 0} for i in ids}
    for part in chunks(ids, 50):
        for r in paged(lambda part=part: db.table("broadcast_recipients").select("id,broadcast_id,reply_sentiment,opted_out_at")
                       .eq("tenant_id", tenant_id).in_("broadcast_id", part)):
            row = out.get(str(r["broadcast_id"]))
            if row is None:
                continue
            if r.get("reply_sentiment"):
                row["replied"] += 1
            if r.get("opted_out_at"):
                row["said_stop"] += 1
    return out


def compute(db, tenant_id: str, period: Period, flags: Flags) -> tuple[dict, dict]:
    from app.services.reach_results import paid_within_window
    sent = campaigns_in(safe(lambda: read_history(db, tenant_id), [], "campaign history"), period)
    ids = [str(h["broadcast_id"]) for h in sent]
    counts = safe(lambda: recipient_counts(db, tenant_id, ids), {}, "campaign replies")
    paid = safe(lambda: paid_within_window(db, tenant_id, [{"broadcast_id": i, "sent_at": h.get("timestamp")} for i, h in zip(ids, sent)],
                                           include_amount=flags.sees_money), {}, "campaign paid")
    rows = []
    for h in sent:
        bid = str(h["broadcast_id"])
        c, p = counts.get(bid) or {}, paid.get(bid) or {}
        amount = p.get("paid_amount_inr")
        rows.append({
            "id": bid, "name": h.get("template_name") or h.get("tag_name") or "Campaign", "sent_at": h.get("timestamp"),
            "sent": int(h.get("sent") or 0), "delivered": h.get("delivered"), "read": h.get("opened"),
            "replied": c.get("replied"), "said_stop": c.get("said_stop"),
            "paid": p.get("paid_count"), "paid_paise": round(amount * 100) if amount is not None else None,
        })

    def total(key: str) -> int:
        return sum(int(r.get(key) or 0) for r in rows)
    numbers = {"campaigns": len(rows), "sent": total("sent"), "delivered": total("delivered"), "read": total("read"),
               "replied": total("replied"), "said_stop": total("said_stop"), "paid": total("paid"),
               "paid_paise": sum(int(r.get("paid_paise") or 0) for r in rows)}
    return numbers, {"rows": rows}


def paid_lead_ids(db, tenant_id: str, broadcast_id: str) -> list[str]:
    """People who paid within 7 days of being sent this campaign (the same rule as paid_within_window)."""
    from app.services.reach_results import _parse, _won_deals
    hist = next((h for h in read_history(db, tenant_id) if str(h["broadcast_id"]) == broadcast_id), None)
    if not hist:
        return []
    sent_rows = paged(lambda: db.table("broadcast_recipients").select("id,lead_id,created_at").eq("tenant_id", tenant_id)
                      .eq("broadcast_id", broadcast_id).eq("send_status", "sent").not_.is_("lead_id", "null"))
    if not sent_rows:
        return []
    at = _parse(hist.get("timestamp"))
    window = timedelta(days=WINDOW_DAYS)
    starts = [_parse(r.get("created_at")) or at for r in sent_rows]
    starts = [s for s in starts if s]
    if not starts:
        return []
    deals = _won_deals(db, tenant_id, min(starts) - timedelta(days=1), max(starts) + window + timedelta(days=1))
    paid_at: dict[str, list] = {}
    for d in deals:
        when = _parse(d.get("won_at")) or _parse(d.get("created_at"))
        if d.get("lead_id") and when:
            paid_at.setdefault(d["lead_id"], []).append(when)
    out: list[str] = []
    for r in sent_rows:
        sent = _parse(r.get("created_at")) or at
        if sent and r["lead_id"] not in out and any(sent <= w <= sent + window for w in paid_at.get(r["lead_id"], [])):
            out.append(r["lead_id"])
    return out


def in_short(numbers: dict, before: dict | None) -> str:
    if not numbers.get("campaigns"):
        return "No campaigns were sent in these days."
    parts = [f"{plural(numbers['campaigns'], 'campaign')} sent to {plural(numbers['sent'], 'person', 'people')}"]
    if numbers.get("replied"):
        parts.append(f"{numbers['replied']} replied")
    if numbers.get("paid"):
        parts.append(f"{numbers['paid']} paid within 7 days")
    return sentence(parts, "")
