"""Reports: the people behind a number (tap a number, see who).

Each metric returns the same people the number counted, as [{lead_id, name, phone, detail}], at most 500.
"""
from fastapi import HTTPException

from app.services.reports_common import Period, chunks, paged, safe
from app.services.reports_data import LEAD_COLUMNS, buyers_split, is_hot, new_chats, won_deals

MAX_PEOPLE = 500

METRICS = ("new_chats", "hot", "paid", "repeat", "bought_new", "funnel_paid", "came_from", "campaign_replied",
           "campaign_paid", "feedback_unhappy", "unmarked_chats", "ad_chats")
# The count of people who paid is not a rupee figure, so it is open to anyone who sees reports; only the
# "paid N rupees" detail line needs the rupee permission.
NEEDS_ID = {"campaign_replied", "campaign_paid", "ad_chats", "came_from"}


def _row(lead: dict, detail: str = "") -> dict:
    return {"lead_id": lead["id"], "name": lead.get("name"), "phone": lead.get("phone"), "detail": detail}


def _leads_by_id(db, tenant_id: str, ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for part in chunks(sorted(set(ids))):
        for r in paged(lambda part=part: db.table("leads").select(LEAD_COLUMNS).eq("tenant_id", tenant_id).in_("id", part)):
            out[r["id"]] = r
    return out


def _capped(rows: list[dict]) -> list[dict]:
    return rows[:MAX_PEOPLE]


def people(db, tenant_id: str, metric: str, period: Period, item_id: str | None = None, sees_money: bool = True) -> list[dict]:
    from app.services import reports_campaigns, reports_customers, reports_overview
    if metric not in METRICS:
        raise HTTPException(status_code=400, detail="That number can't be opened to see the people. Pick another.")
    if metric in NEEDS_ID and not item_id:
        raise HTTPException(status_code=400, detail="Say which one to open (the id is missing).")

    if metric == "new_chats":
        return _capped([_row(c, c.get("source") or "") for c in new_chats(db, tenant_id, period)])
    if metric == "hot":
        return _capped([_row(c, "Hot") for c in new_chats(db, tenant_id, period) if is_hot(c)])
    if metric == "unmarked_chats":
        ids = reports_overview.unmarked_lead_ids(db, tenant_id, period)
        leads = _leads_by_id(db, tenant_id, ids)
        return _capped([_row(leads[i], "No result marked yet") for i in ids if i in leads])
    if metric == "came_from":
        platforms = reports_customers.campaign_platforms(db, tenant_id)
        from app.services.reports_data import new_leads
        return _capped([_row(l, reports_customers.CAME_FROM_LABELS.get(item_id, item_id))
                        for l in new_leads(db, tenant_id, period) if reports_customers.came_from_key(l, platforms) == item_id])
    if metric == "ad_chats":
        rows = paged(lambda: db.table("leads").select(LEAD_COLUMNS).eq("tenant_id", tenant_id).is_("deleted_at", "null")
                     .eq("ad_campaign_id", item_id).gte("created_at", period.start_iso).lt("created_at", period.end_iso))
        return _capped([_row(r, "Hot" if is_hot(r) else "") for r in rows])

    if metric in ("paid", "repeat", "bought_new"):
        deals = won_deals(db, tenant_id, period)
        split = buyers_split(db, tenant_id, period, deals)
        ids = {"paid": split["buyer_ids"], "repeat": split["repeat_ids"], "bought_new": split["new_ids"]}[metric]
        spent: dict[str, int] = {}
        for d in deals:
            if d.get("lead_id"):
                spent[d["lead_id"]] = spent.get(d["lead_id"], 0) + int(d.get("total_paise") or 0)
        leads = _leads_by_id(db, tenant_id, ids)
        return _capped([_row(leads[i], (f"Paid {spent.get(i, 0) / 100:,.0f} rupees" if sees_money else "Paid")) for i in ids if i in leads])
    if metric == "funnel_paid":
        chats = new_chats(db, tenant_id, period)
        bought = reports_customers.cohort_buyer_ids(db, tenant_id, [c["id"] for c in chats])
        return _capped([_row(c, "Paid") for c in chats if c["id"] in bought])

    if metric == "feedback_unhappy":
        rows = safe(lambda: paged(lambda: db.table("customer_feedback").select("id,lead_id,phone,stars,reason,staff_name")
                                  .eq("tenant_id", tenant_id).eq("status", "answered").lte("stars", reports_overview.UNHAPPY_MAX)), [], "feedback")
        leads = _leads_by_id(db, tenant_id, [r["lead_id"] for r in rows if r.get("lead_id")])
        out = []
        for r in rows:
            lead = leads.get(r.get("lead_id") or "")
            if lead:
                out.append(_row(lead, f"{r['stars']} stars" + (f": {r['reason']}" if r.get("reason") else "")))
            else:
                out.append({"lead_id": r.get("lead_id") or "", "name": None, "phone": r.get("phone"), "detail": f"{r['stars']} stars"})
        return _capped(out)

    if metric == "campaign_replied":
        rows = paged(lambda: db.table("broadcast_recipients").select("id,lead_id,phone,reply_sentiment").eq("tenant_id", tenant_id)
                     .eq("broadcast_id", item_id).not_.is_("reply_sentiment", "null"))
        leads = _leads_by_id(db, tenant_id, [r["lead_id"] for r in rows if r.get("lead_id")])
        return _capped([_row(leads[r["lead_id"]], r.get("reply_sentiment") or "") for r in rows if r.get("lead_id") in leads])
    # campaign_paid
    ids = reports_campaigns.paid_lead_ids(db, tenant_id, item_id)
    leads = _leads_by_id(db, tenant_id, ids)
    return _capped([_row(leads[i], "Paid within 7 days") for i in ids if i in leads])
