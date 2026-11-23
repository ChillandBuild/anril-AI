"""Reports > Ads: Meta and Google campaigns in one table for the picked days.

Chats = people from the campaign whose record was created in the days (hot = segment A).
Sales = paid orders in the days from people the campaign brought (any time); earned = what they paid us,
less refunds. Meta cost comes from the daily ad numbers. Google cost is typed in per whole month
(Google Ads page), so for other days it is shared out by day.

The Meta and Google Ads pages (services/ad_performance.py, google_ads_report.py) answer one month at a
time, so they cannot answer a free date range; this reads the same tables for the range instead.
"""
import calendar
from datetime import date, timedelta

from app.services.reports_common import Flags, Period, chunks, count_phrase, money, paged, safe, sentence
from app.services.reports_data import won_deals


def _div(a: int, b: int) -> int | None:
    return round(a / b) if b else None


def google_spend_for(rows: list[dict], period: Period) -> dict[str, int]:
    """campaign id -> paise for the days, from whole-month figures shared out by day."""
    out: dict[str, int] = {}
    for r in rows:
        try:
            first = date.fromisoformat(str(r["month"])[:10])
        except (KeyError, ValueError):
            continue
        dim = calendar.monthrange(first.year, first.month)[1]
        last = first + timedelta(days=dim - 1)
        overlap = (min(last, period.end) - max(first, period.start)).days + 1
        if overlap <= 0:
            continue
        cid = str(r["campaign_id"])
        out[cid] = out.get(cid, 0) + (int(r.get("spend_paise") or 0) * overlap + dim // 2) // dim
    return out


def meta_spend_for(db, tenant_id: str, period: Period) -> dict[str, int]:
    """campaign id -> paise from ad_insights_daily (rupees as a decimal) via ad_creatives."""
    creatives = paged(lambda: db.table("ad_creatives").select("id,campaign_id").eq("tenant_id", tenant_id))
    campaign_of = {str(c["id"]): str(c["campaign_id"]) for c in creatives if c.get("campaign_id")}
    if not campaign_of:
        return {}
    rows = paged(lambda: db.table("ad_insights_daily").select("ad_creative_id,insight_date,spend")
                 .eq("tenant_id", tenant_id).gte("insight_date", period.start.isoformat())
                 .lt("insight_date", period.end_excl_day.isoformat()), order_by=("ad_creative_id", "insight_date"))
    out: dict[str, int] = {}
    for r in rows:
        cid = campaign_of.get(str(r.get("ad_creative_id")))
        if cid:
            out[cid] = out.get(cid, 0) + round(float(r.get("spend") or 0) * 100)
    return out


def compute(db, tenant_id: str, period: Period, flags: Flags) -> tuple[dict, dict]:
    campaigns = paged(lambda: db.table("ad_campaigns").select("id,campaign_name,platform").eq("tenant_id", tenant_id))
    names = {str(c["id"]): c for c in campaigns}

    leads = paged(lambda: db.table("leads").select("id,ad_campaign_id,segment").eq("tenant_id", tenant_id)
                  .is_("deleted_at", "null").not_.is_("ad_campaign_id", "null")
                  .gte("created_at", period.start_iso).lt("created_at", period.end_iso))
    chats: dict[str, int] = {}
    hot: dict[str, int] = {}
    for lead in leads:
        cid = str(lead["ad_campaign_id"])
        chats[cid] = chats.get(cid, 0) + 1
        if (lead.get("segment") or "").upper() == "A":
            hot[cid] = hot.get(cid, 0) + 1

    sales: dict[str, int] = {}
    earned: dict[str, int] = {}
    deals = [d for d in won_deals(db, tenant_id, period) if d.get("lead_id")]
    campaign_of_lead: dict[str, str] = {}
    for part in chunks(sorted({d["lead_id"] for d in deals})):
        for r in paged(lambda part=part: db.table("leads").select("id,ad_campaign_id").eq("tenant_id", tenant_id)
                       .in_("id", part).not_.is_("ad_campaign_id", "null")):
            campaign_of_lead[r["id"]] = str(r["ad_campaign_id"])
    for d in deals:
        cid = campaign_of_lead.get(d["lead_id"])
        if cid:
            sales[cid] = sales.get(cid, 0) + 1
            earned[cid] = earned.get(cid, 0) + max(int(d.get("paid_paise") or 0) - int(d.get("refunded_paise") or 0), 0)

    spend: dict[str, int] = {}
    if flags.sees_money:
        for cid, paise in safe(lambda: meta_spend_for(db, tenant_id, period), {}, "meta ad cost").items():
            spend[cid] = spend.get(cid, 0) + paise
        google_rows = safe(lambda: paged(lambda: db.table("google_ads_spend").select("campaign_id,month,spend_paise")
                                         .eq("tenant_id", tenant_id)
                                         .gte("month", period.start.replace(day=1).isoformat())
                                         .lte("month", period.end.isoformat()), order_by=("campaign_id", "month")),
                           [], "google ad cost")
        for cid, paise in google_spend_for(google_rows, period).items():
            spend[cid] = spend.get(cid, 0) + paise

    rows = []
    for cid in sorted(set(chats) | set(spend) | set(sales)):
        camp = names.get(cid)
        if not camp:
            continue
        sp = spend.get(cid, 0)
        n_chats, n_hot, n_sales, money_in = chats.get(cid, 0), hot.get(cid, 0), sales.get(cid, 0), earned.get(cid, 0)
        rows.append({
            "id": cid, "name": camp.get("campaign_name") or "Ad", "platform": "google" if camp.get("platform") == "google" else "meta",
            "spend_paise": sp, "chats": n_chats, "hot": n_hot, "sales": n_sales, "earned_paise": money_in,
            "cost_per_chat_paise": _div(sp, n_chats), "cost_per_hot_paise": _div(sp, n_hot),
            "cost_per_sale_paise": _div(sp, n_sales), "money_back": round(money_in / sp, 2) if sp else None,
        })
    rows.sort(key=lambda r: (-r["chats"], r["name"].lower()))

    t_spend, t_chats = sum(r["spend_paise"] for r in rows), sum(r["chats"] for r in rows)
    t_hot, t_sales = sum(r["hot"] for r in rows), sum(r["sales"] for r in rows)
    t_earned = sum(r["earned_paise"] for r in rows)
    numbers = {
        "spend_paise": t_spend, "chats": t_chats, "hot": t_hot, "sales": t_sales, "earned_paise": t_earned,
        "cost_per_chat_paise": _div(t_spend, t_chats), "cost_per_hot_paise": _div(t_spend, t_hot),
        "cost_per_sale_paise": _div(t_spend, t_sales), "money_back": round(t_earned / t_spend, 2) if t_spend else None,
    }
    return numbers, {"rows": rows}


def in_short(numbers: dict, before: dict | None) -> str:
    b = before or {}
    parts = []
    if numbers.get("spend_paise"):
        parts.append(f"{money(numbers['spend_paise'])} spent on ads")
    parts.append(count_phrase(numbers.get("chats"), b.get("chats"), "chat from ads", "chats from ads"))
    if numbers.get("cost_per_chat_paise"):
        parts.append(f"{money(numbers['cost_per_chat_paise'])} per chat")
    if numbers.get("sales"):
        parts.append(f"{numbers['sales']} paid")
    return sentence(parts, "No ad chats in these days.")
