"""v9.2 Commerce > Properties: the five tiles and the per-project numbers.

Tiles: projects (units left), site visits this week (came / to come), hot buyers (Hot leads interested
in a property), token paid (paid orders with a property line, money only for deals.view), and
"asked, not available" (customers whose BHK, saved from the chat, no property with units left has).
Per project: enquiries (leads who picked it in "interested in"), site visits, tokens, and the media
marks (brochure, photo count, map, RERA). Every part fails alone to zeros.
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _norm_bhk(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _week_bounds(now: datetime) -> tuple[str, str]:
    day = now.astimezone(IST).date()
    monday = day - timedelta(days=day.weekday())
    start = datetime(monday.year, monday.month, monday.day, tzinfo=IST)
    return start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=7)).astimezone(timezone.utc).isoformat()


def summary(db, tenant_id: str, *, show_money: bool, now: datetime | None = None) -> dict:
    from app.services import properties as props
    now = now or datetime.now(timezone.utc)
    items = props.list_properties(db, tenant_id, show_money=False)
    ids = [p["id"] for p in items]
    per = {i: {"enquiries": 0, "visits": 0, "tokens": 0, "photos": 0, "brochure": False} for i in ids}
    out = {
        "projects": len(items),
        "units_left": sum(int(p.get("units_left") or 0) for p in items),
        "visits_week": 0, "visits_came": 0, "visits_to_come": 0,
        "hot_buyers": 0, "tokens": 0, "asked_not_available": 0, "asked_top": None,
        "per_property": per,
    }
    if not ids:
        return out

    # Enquiries and hot buyers: leads who picked a property in "interested in".
    try:
        leads = (db.table("leads").select("id,segment,interested_item_ids,collected_data,created_at")
                 .eq("tenant_id", tenant_id).is_("deleted_at", "null").limit(5000).execute().data or [])
    except Exception as e:
        logger.info("properties summary: leads unavailable: %s", e)
        leads = []
    hot = set()
    for lead in leads:
        picked = [i for i in (lead.get("interested_item_ids") or []) if i in per]
        for i in picked:
            per[i]["enquiries"] += 1
        if picked and lead.get("segment") == "A":
            hot.add(lead["id"])
    out["hot_buyers"] = len(hot)

    # Asked, not available: the BHK they want (lead details) that no property with units left offers.
    on_offer = {_norm_bhk(p.get("bhk")) for p in items if (p.get("units_left") or 0) > 0 and p.get("bhk")}
    since = (now - timedelta(days=30)).isoformat()
    missed = Counter()
    for lead in leads:
        want = (lead.get("collected_data") or {}).get("bhk") if isinstance(lead.get("collected_data"), dict) else None
        if want and (lead.get("created_at") or "") >= since and not any(_norm_bhk(want) in o or o in _norm_bhk(want) for o in on_offer if o):
            missed[str(want).strip()] += 1
    out["asked_not_available"] = sum(missed.values())
    out["asked_top"] = missed.most_common(1)[0][0] if missed else None

    # Site visits: this week's site-visit bookings, and all visits linked to each property.
    try:
        svc = props.site_visit_service(db, tenant_id, create=False)
        if svc:
            start, end = _week_bounds(now)
            week = (db.table("bookings").select("id,status").eq("tenant_id", tenant_id).eq("service_id", svc["id"])
                    .gte("start_at", start).lt("start_at", end).limit(2000).execute().data or [])
            week = [b for b in week if b.get("status") != "cancelled"]
            out["visits_week"] = len(week)
            out["visits_came"] = sum(1 for b in week if b.get("status") == "came")
            out["visits_to_come"] = sum(1 for b in week if b.get("status") in ("booked", "held"))
        for v in (db.table("property_visits").select("property_item_id").eq("tenant_id", tenant_id)
                  .limit(10000).execute().data or []):
            if v.get("property_item_id") in per:
                per[v["property_item_id"]]["visits"] += 1
    except Exception as e:
        logger.info("properties summary: visits unavailable: %s", e)

    # Tokens: paid orders with a property line.
    try:
        lines = (db.table("deal_items").select("deal_id,catalog_item_id").eq("tenant_id", tenant_id)
                 .in_("catalog_item_id", ids).limit(10000).execute().data or [])
        deal_ids = list({l["deal_id"] for l in lines})
        won = {}
        for k in range(0, len(deal_ids), 200):
            for d in (db.table("deals").select("id,total_paise").eq("tenant_id", tenant_id).eq("stage", "won")
                      .in_("id", deal_ids[k:k + 200]).execute().data or []):
                won[d["id"]] = int(d.get("total_paise") or 0)
        counted = set()
        for l in lines:
            if l["deal_id"] in won and (l["deal_id"], l["catalog_item_id"]) not in counted:
                counted.add((l["deal_id"], l["catalog_item_id"]))
                per[l["catalog_item_id"]]["tokens"] += 1
        out["tokens"] = len(won)
        if show_money:
            out["tokens_paise"] = sum(won.values())
    except Exception as e:
        logger.info("properties summary: tokens unavailable: %s", e)

    # Media marks.
    try:
        for m in (db.table("catalog_media").select("catalog_item_id").eq("tenant_id", tenant_id)
                  .in_("catalog_item_id", ids).limit(10000).execute().data or []):
            per[m["catalog_item_id"]]["photos"] += 1
        for f in (db.table("catalog_files").select("catalog_item_id").eq("tenant_id", tenant_id).eq("kind", "document")
                  .in_("catalog_item_id", ids).limit(5000).execute().data or []):
            per[f["catalog_item_id"]]["brochure"] = True
    except Exception as e:
        logger.info("properties summary: media unavailable: %s", e)
    return out
