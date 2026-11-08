"""Catalogue of per-ad fields named the way Meta Ads Manager names them, plus a
live pass-through fetch that builds one report row per ad (or per breakdown
value). Values come from Meta untouched, Results and Cost per result included;
the only arithmetic is Budget (minor -> major currency units).

Read-only against Meta (ads_read). Results are cached in-process for a few
minutes; the token is not part of the cache key because account ids are unique
per tenant, so tenant isolation is by account.
"""
import json
import time

from app.services.meta_ads_insights_sync import (
    _ALL_AD_STATUSES,
    _GRAPH_BASE,
    _fetch_paged,
    _fetch_paged_all_statuses,
)

_TEXT_FORMATS = {"text", "date", "image"}

# Ranking metrics are not returned when the insights call is broken down.
RANKING_KEYS = {"quality_ranking", "engagement_rate_ranking", "conversion_rate_ranking"}


def _entry(key: str, label: str, group: str, fmt: str, source: dict) -> dict:
    return {"key": key, "label": label, "group": group, "format": fmt, "source": source}


def _field(key: str, label: str, group: str, fmt: str, field: str | None = None) -> dict:
    return _entry(key, label, group, fmt, {"kind": "field", "field": field or key})


def _list(key: str, label: str, group: str, fmt: str, field: str) -> dict:
    return _entry(key, label, group, fmt, {"kind": "list", "field": field})


def _action(key: str, label: str, group: str, fmt: str, types: list[str]) -> dict:
    return _entry(key, label, group, fmt, {"kind": "action", "types": types})


def _cpa(key: str, label: str, group: str, fmt: str, types: list[str]) -> dict:
    return _entry(key, label, group, fmt, {"kind": "cost_per_action", "types": types})


def _aval(key: str, label: str, group: str, fmt: str, types: list[str]) -> dict:
    return _entry(key, label, group, fmt, {"kind": "action_value", "types": types})


def _ad(key: str, label: str, group: str, fmt: str, path: str | list[str]) -> dict:
    return _entry(key, label, group, fmt, {"kind": "ad", "path": path})


_PERF = "Performance"
_CLICKS = "Clicks"
_MSG = "Messaging"
_ENG = "Engagement"
_VIDEO = "Video"
_LEADS = "Leads & website"
_RANK = "Ranking"
_SETUP = "Setup"
_CREATIVE = "Creative"

META_FIELD_CATALOG: list[dict] = [
    # Performance
    _entry("results", "Results", _PERF, "number", {"kind": "result"}),
    _entry("result_type", "Result type", _PERF, "text", {"kind": "result_type"}),
    _entry("cost_per_result", "Cost per result", _PERF, "money", {"kind": "cost_per_result"}),
    _field("reach", "Reach", _PERF, "number"),
    _field("impressions", "Impressions", _PERF, "number"),
    _field("frequency", "Frequency", _PERF, "decimal"),
    _field("spend", "Amount spent", _PERF, "money"),
    _field("cpm", "CPM (cost per 1,000 impressions)", _PERF, "money"),
    _field("attribution_setting", "Attribution setting", _PERF, "text"),
    # Clicks
    _field("inline_link_clicks", "Link clicks", _CLICKS, "number"),
    _field("cost_per_inline_link_click", "CPC (cost per link click)", _CLICKS, "money"),
    _field("inline_link_click_ctr", "CTR (link click-through rate)", _CLICKS, "percent"),
    _field("clicks", "Clicks (all)", _CLICKS, "number"),
    _field("ctr", "CTR (all)", _CLICKS, "percent"),
    _field("cpc", "CPC (all)", _CLICKS, "money"),
    _field("unique_clicks", "Unique clicks (all)", _CLICKS, "number"),
    _field("unique_ctr", "Unique CTR (all)", _CLICKS, "percent"),
    _field("cost_per_unique_click", "Cost per unique click (all)", _CLICKS, "money"),
    _list("outbound_clicks", "Outbound clicks", _CLICKS, "number", "outbound_clicks"),
    _action(
        "landing_page_views", "Landing page views", _CLICKS, "number",
        ["landing_page_view", "omni_landing_page_view"],
    ),
    # Messaging
    _action(
        "messaging_conversations_started", "Messaging conversations started", _MSG, "number",
        ["onsite_conversion.messaging_conversation_started_7d"],
    ),
    _cpa(
        "cost_per_messaging_conversation", "Cost per messaging conversation started", _MSG, "money",
        ["onsite_conversion.messaging_conversation_started_7d"],
    ),
    _action(
        "messaging_contacts", "Messaging contacts", _MSG, "number",
        ["onsite_conversion.total_messaging_connection"],
    ),
    _action(
        "new_messaging_contacts", "New messaging contacts", _MSG, "number",
        ["onsite_conversion.messaging_first_reply"],
    ),
    _action(
        "messaging_conversations_replied", "Messaging conversations replied", _MSG, "number",
        ["onsite_conversion.messaging_conversation_replied_7d"],
    ),
    _action("messaging_blocks", "Blocks", _MSG, "number", ["onsite_conversion.messaging_block"]),
    # Engagement
    _action("post_engagement", "Post engagements", _ENG, "number", ["post_engagement"]),
    _action("page_engagement", "Page engagement", _ENG, "number", ["page_engagement"]),
    _action("post_reactions", "Post reactions", _ENG, "number", ["post_reaction"]),
    _action("post_comments", "Post comments", _ENG, "number", ["comment"]),
    _action("post_shares", "Post shares", _ENG, "number", ["post"]),
    _action("post_saves", "Post saves", _ENG, "number", ["onsite_conversion.post_save"]),
    _action("page_likes", "Follows or likes", _ENG, "number", ["like"]),
    # Video
    _action("video_plays_3s", "3-second video plays", _VIDEO, "number", ["video_view"]),
    _list("thruplays", "ThruPlays", _VIDEO, "number", "video_thruplay_watched_actions"),
    _list("video_p25", "Video plays at 25%", _VIDEO, "number", "video_p25_watched_actions"),
    _list("video_p50", "Video plays at 50%", _VIDEO, "number", "video_p50_watched_actions"),
    _list("video_p75", "Video plays at 75%", _VIDEO, "number", "video_p75_watched_actions"),
    _list("video_p95", "Video plays at 95%", _VIDEO, "number", "video_p95_watched_actions"),
    _list("video_p100", "Video plays at 100%", _VIDEO, "number", "video_p100_watched_actions"),
    _list(
        "video_avg_time", "Video average play time", _VIDEO, "decimal",
        "video_avg_time_watched_actions",
    ),
    # Leads & website
    _action("leads", "Leads", _LEADS, "number", ["lead", "onsite_conversion.lead_grouped"]),
    _cpa("cost_per_lead", "Cost per lead", _LEADS, "money", ["lead", "onsite_conversion.lead_grouped"]),
    _action("purchases", "Purchases", _LEADS, "number", ["omni_purchase", "purchase"]),
    _aval("purchase_value", "Purchases conversion value", _LEADS, "money", ["omni_purchase", "purchase"]),
    _list("purchase_roas", "Purchase ROAS (return on ad spend)", _LEADS, "decimal", "purchase_roas"),
    # Ranking
    _field("quality_ranking", "Quality ranking", _RANK, "text"),
    _field("engagement_rate_ranking", "Engagement rate ranking", _RANK, "text"),
    _field("conversion_rate_ranking", "Conversion rate ranking", _RANK, "text"),
    # Setup
    _ad("delivery", "Delivery", _SETUP, "text", "effective_status"),
    _field("objective", "Objective", _SETUP, "text"),
    _field("optimization_goal", "Optimisation goal", _SETUP, "text"),
    _ad("bid_strategy", "Bid strategy", _SETUP, "text", ["adset.bid_strategy", "campaign.bid_strategy"]),
    _entry("budget", "Budget", _SETUP, "money", {"kind": "budget"}),
    _ad("starts", "Starts", _SETUP, "date", "adset.start_time"),
    _ad("ends", "Ends", _SETUP, "date", "adset.end_time"),
    _ad("destination", "Destination", _SETUP, "text", "adset.destination_type"),
    # Creative
    _ad("thumbnail", "Ad preview", _CREATIVE, "image", "creative.thumbnail_url"),
    _ad("primary_text", "Primary text", _CREATIVE, "text", "creative.body"),
    _ad("headline", "Headline", _CREATIVE, "text", "creative.title"),
    _ad("call_to_action", "Call to action", _CREATIVE, "text", "creative.call_to_action_type"),
]

_BY_KEY: dict[str, dict] = {e["key"]: e for e in META_FIELD_CATALOG}

# Results come straight from Meta's own `results` / `cost_per_result` insight
# fields -- the same numbers as Ads Manager's Results column for every goal,
# including what a Conversions ad actually targets. Meta names the result by an
# indicator such as "actions:mobile_app_install"; these are the friendly names.
_RESULT_LABELS: dict[str, str] = {
    "mobile_app_install": "App installs",
    "omni_app_install": "App installs",
    "onsite_conversion.messaging_conversation_started_7d": "Messaging conversations started",
    "onsite_conversion.total_messaging_connection": "Messaging contacts",
    "onsite_conversion.messaging_first_reply": "New messaging contacts",
    "lead": "Leads",
    "onsite_conversion.lead_grouped": "Leads",
    "offsite_conversion.fb_pixel_lead": "Website leads",
    "link_click": "Link clicks",
    "landing_page_view": "Landing page views",
    "omni_landing_page_view": "Landing page views",
    "purchase": "Purchases",
    "omni_purchase": "Purchases",
    "offsite_conversion.fb_pixel_purchase": "Website purchases",
    "app_custom_event.fb_mobile_purchase": "App purchases",
    "omni_complete_registration": "Registrations completed",
    "offsite_conversion.fb_pixel_complete_registration": "Website registrations completed",
    "app_custom_event.fb_mobile_complete_registration": "App registrations completed",
    "omni_activate_app": "App activations",
    "app_custom_event.fb_mobile_activate_app": "App activations",
    "omni_add_to_cart": "Adds to cart",
    "omni_initiated_checkout": "Checkouts initiated",
    "omni_view_content": "Content views",
    "omni_search": "Searches",
    "post_engagement": "Post engagements",
    "page_engagement": "Page engagement",
    "like": "Follows or likes",
    "video_view": "3-second video plays",
    "video_thruplay_watched_actions": "ThruPlays",
    "reach": "Reach",
    "impressions": "Impressions",
}
# Stripped from an unlisted indicator to make a readable name.
_INDICATOR_PREFIXES = (
    "offsite_conversion.fb_pixel_", "app_custom_event.fb_mobile_", "onsite_conversion.",
    "offsite_conversion.", "app_custom_event.", "omni_",
)
_RESULT_FIELDS = ["results", "cost_per_result"]

BREAKDOWNS: dict[str, dict] = {
    "age": {"label": "Age", "breakdowns": "age"},
    "gender": {"label": "Gender", "breakdowns": "gender"},
    "region": {"label": "Region", "breakdowns": "region"},
    "device": {"label": "Impression device", "breakdowns": "impression_device"},
    "placement": {"label": "Placement", "breakdowns": "publisher_platform,platform_position"},
    "hour": {
        "label": "Time of day (ad account time zone)",
        "breakdowns": "hourly_stats_aggregated_by_advertiser_time_zone",
    },
}

_BASE_INSIGHT_FIELDS = [
    "ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name",
    "objective", "optimization_goal", "spend", "impressions", "reach",
    "inline_link_clicks", "actions", "cost_per_action_type", "action_values",
]

_CACHE_TTL_SECONDS = 300
_CACHE_MAX_ENTRIES = 200
_CACHE: dict[tuple, tuple[float, list[dict]]] = {}


def insight_fields_for(keys: list[str]) -> str:
    """Base insight fields plus the Graph fields the requested keys read."""
    fields = list(_BASE_INSIGHT_FIELDS)
    for k in keys:
        entry = _BY_KEY.get(k)
        if entry is None:
            continue
        src = entry["source"]
        kind = src["kind"]
        if kind in ("field", "list"):
            fields.append(src["field"])
        elif kind in ("result", "result_type", "cost_per_result"):
            fields.extend(_RESULT_FIELDS)
    return ",".join(dict.fromkeys(fields))


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_match(entries, types: list[str]) -> float | None:
    """First action_type in `types` (in order) that appears in `entries`.
    Never sums: omni_purchase and purchase often carry the same count."""
    if not isinstance(entries, list):
        return None
    by_type: dict[str, object] = {}
    for e in entries:
        if isinstance(e, dict):
            by_type.setdefault(e.get("action_type"), e.get("value"))
    for t in types:
        if t in by_type:
            return _to_float(by_type[t])
    return None


def _first_list(entries) -> float | None:
    if not isinstance(entries, list) or not entries:
        return None
    first = entries[0]
    return _to_float(first.get("value")) if isinstance(first, dict) else None


def _ad_lookup(ad: dict | None, path: str | list[str]):
    if ad is None:
        return None
    paths = [path] if isinstance(path, str) else path
    for p in paths:
        cur = ad
        for part in p.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur is not None:
            return cur
    return None


def _budget(ad: dict | None) -> dict | None:
    """Ad-set budget first, then campaign budget. Meta reports minor units."""
    if not ad:
        return None
    adset = ad.get("adset") or {}
    campaign = ad.get("campaign") or {}
    for obj, level in ((adset, "ad_set"), (campaign, "campaign")):
        for btype in ("daily", "lifetime"):
            raw = obj.get(f"{btype}_budget")
            if raw in (None, ""):
                continue
            amount = _to_float(raw)
            if amount is None:
                continue
            return {"amount": amount / 100, "type": btype, "level": level}
    return None


def _result_label(indicator: str) -> str:
    """'actions:mobile_app_install' -> 'App installs'; unlisted ones are tidied up."""
    name = indicator.split(":", 1)[-1]
    if name in _RESULT_LABELS:
        return _RESULT_LABELS[name]
    if indicator in _RESULT_LABELS:
        return _RESULT_LABELS[indicator]
    for prefix in _INDICATOR_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = name.replace(".", " ").replace("_", " ").strip()
    return name[:1].upper() + name[1:] if name else indicator


def _meta_result(entries) -> tuple[str | None, float | None]:
    """(label, value) from Meta's `results` or `cost_per_result` list. Meta sends the
    indicator without values when there is nothing to count -- Ads Manager's '—'."""
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        return None, None
    first = entries[0]
    indicator = str(first.get("indicator") or "")
    values = first.get("values") or []
    value = _to_float(values[0].get("value")) if values and isinstance(values[0], dict) else None
    return (_result_label(indicator) if indicator else None), value


def extract_value(entry: dict, row: dict, ad: dict | None):
    """Value for one catalogue entry from an insight row and its /ads object.
    `row` may be {} for ad-only rows (zero-delivery ads)."""
    row = row or {}
    src = entry["source"]
    kind = src["kind"]
    if kind == "field":
        raw = row.get(src["field"])
        if entry["format"] in _TEXT_FORMATS:
            return None if raw in (None, "") else str(raw)
        return _to_float(raw)
    if kind == "list":
        return _first_list(row.get(src["field"]))
    if kind == "action":
        return _first_match(row.get("actions"), src["types"])
    if kind == "cost_per_action":
        return _first_match(row.get("cost_per_action_type"), src["types"])
    if kind == "action_value":
        return _first_match(row.get("action_values"), src["types"])
    if kind == "ad":
        return _ad_lookup(ad, src["path"])
    if kind == "budget":
        return _budget(ad)
    if kind == "result":
        return _meta_result(row.get("results"))[1]
    if kind == "result_type":
        return _meta_result(row.get("results"))[0]
    if kind == "cost_per_result":
        return _meta_result(row.get("cost_per_result"))[1]
    raise ValueError(f"unknown source kind: {kind}")


def _breakdown_label(row: dict, breakdown: str) -> str | None:
    cols = BREAKDOWNS[breakdown]["breakdowns"].split(",")
    parts = [str(row[c]) for c in cols if row.get(c) not in (None, "")]
    return " · ".join(parts) or None


def _build_row(ad_id: str, row: dict, ad: dict | None, label: str | None, keys: list[str]) -> dict:
    ad_obj = ad or {}
    adset = ad_obj.get("adset") or {}
    campaign = ad_obj.get("campaign") or {}
    return {
        "meta_ad_id": ad_id,
        "ad_name": row.get("ad_name") or ad_obj.get("name"),
        "adset_name": row.get("adset_name") or adset.get("name"),
        "campaign_name": row.get("campaign_name") or campaign.get("name"),
        "destination_type": adset.get("destination_type"),
        "breakdown": label,
        "values": {k: extract_value(_BY_KEY[k], row, ad) for k in keys},
    }


def _cache_get(key: tuple) -> list[dict] | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    stored_at, rows = entry
    if time.monotonic() - stored_at > _CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return rows


def _cache_put(key: tuple, rows: list[dict]) -> None:
    _CACHE.pop(key, None)
    _CACHE[key] = (time.monotonic(), rows)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def fetch_meta_insights_live(
    token: str,
    account: str,
    *,
    date_from: str,
    date_to: str,
    keys: list[str],
    breakdown: str | None = None,
    ad_ids: set[str] | None = None,
) -> list[dict]:
    if breakdown is not None and breakdown not in BREAKDOWNS:
        raise ValueError(f"unknown breakdown: {breakdown}")

    effective = [k for k in dict.fromkeys(keys) if k in _BY_KEY]
    if breakdown is not None:
        effective = [k for k in effective if k not in RANKING_KEYS]
    wanted = None if ad_ids is None else {str(a) for a in ad_ids}

    cache_key = (
        account,
        date_from,
        date_to,
        tuple(sorted(effective)),
        breakdown,
        None if wanted is None else tuple(sorted(wanted)),
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    insight_params = {
        "level": "ad",
        "fields": insight_fields_for(effective),
        "time_range": json.dumps({"since": date_from, "until": date_to}),
        "limit": "200",
        "access_token": token,
    }
    if breakdown is not None:
        insight_params["breakdowns"] = BREAKDOWNS[breakdown]["breakdowns"]
    if wanted is not None and 0 < len(wanted) <= 50:
        # Ask Meta for just these ads instead of the whole account. With an ad.id
        # filter Meta silently drops archived/deleted ads unless the status filter
        # names them, and their spend would vanish from the report.
        insight_params["filtering"] = json.dumps([
            {"field": "ad.id", "operator": "IN", "value": sorted(wanted)},
            {"field": "ad.effective_status", "operator": "IN", "value": list(_ALL_AD_STATUSES)},
        ])
    insight_rows = _fetch_paged(f"{_GRAPH_BASE}/{account}/insights", insight_params)

    ad_rows = _fetch_paged_all_statuses(
        f"{_GRAPH_BASE}/{account}/ads",
        {
            "fields": (
                "id,name,effective_status,"
                "adset{id,name,destination_type,daily_budget,lifetime_budget,start_time,end_time,bid_strategy},"
                "campaign{id,name,objective,daily_budget,lifetime_budget,bid_strategy},"
                "creative{thumbnail_url,body,title,call_to_action_type}"
            ),
            "limit": "200",
            "access_token": token,
        },
        status_field="ad.effective_status",
        statuses=_ALL_AD_STATUSES,
    )
    ads_by_id = {str(a["id"]): a for a in ad_rows if a.get("id") is not None}

    out: list[dict] = []
    seen: set[str] = set()
    for row in insight_rows:
        ad_id = str(row.get("ad_id") or "")
        if wanted is not None and ad_id not in wanted:
            continue
        seen.add(ad_id)
        label = _breakdown_label(row, breakdown) if breakdown is not None else None
        out.append(_build_row(ad_id, row, ads_by_id.get(ad_id), label, effective))

    if breakdown is None:
        # Zero-delivery ads get a row too, so they still show in the report.
        # Ads Meta no longer returns have no name to show, so they get no row.
        candidates = [a for a in ads_by_id if wanted is None or a in wanted]
        for ad_id in candidates:
            if ad_id in seen:
                continue
            out.append(_build_row(ad_id, {}, ads_by_id.get(ad_id), None, effective))

    _cache_put(cache_key, out)
    return list(out)


def catalog_for_api() -> list[dict]:
    return [
        {
            "key": e["key"],
            "label": e["label"],
            "group": e["group"],
            "format": e["format"],
            "breakdown_ok": e["key"] not in RANKING_KEYS,
        }
        for e in META_FIELD_CATALOG
    ]


def breakdowns_for_api() -> list[dict]:
    return [{"key": k, "label": v["label"]} for k, v in BREAKDOWNS.items()]
