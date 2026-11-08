"""Per-creative ad performance.

Meta provides delivery/click/spend. Anril counts each lead once per Meta ad from
lead_meta_ad_attributions, so repeat messages from the same lead and ad do not
duplicate the conversion, while the same lead may count once for another ad.

"Messaging ads" are every ad whose ad set opens a chat app (WhatsApp, Instagram
Direct or Messenger). Hot-lead counting and the tracking code stay WhatsApp-only.
"""
import logging

logger = logging.getLogger(__name__)

# Chat apps a messaging ad can open, in report order. Attribution rows written
# before the channel column existed count as WhatsApp.
MESSAGING_CHANNELS = ("whatsapp", "instagram", "messenger")


def _empty_channel_counts() -> dict[str, int]:
    return {channel: 0 for channel in MESSAGING_CHANNELS}


# Meta reports many delivery states; these are the buckets worth filtering by.
# CAMPAIGN_PAUSED / ADSET_PAUSED mean the ad itself is fine but something above
# it is off -- still "paused" as far as anyone reading the dashboard cares.
DELIVERY_GROUPS: dict[str, set[str]] = {
    "active": {"ACTIVE"},
    "paused": {"PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"},
    "archived": {"ARCHIVED"},
    "deleted": {"DELETED"},
    "removed": {"ARCHIVED", "DELETED"},
    "issues": {"DISAPPROVED", "WITH_ISSUES", "PENDING_REVIEW", "PENDING_BILLING_INFO"},
}


def filter_by_delivery(rows: list[dict], delivery_status: str | None) -> list[dict]:
    """Narrow rows to one DELIVERY_GROUPS bucket. An unknown key is ignored
    rather than returning nothing -- a stale bookmark or a typo'd query param
    should show the unfiltered table, not an empty one.
    """
    if not delivery_status:
        return rows
    wanted = DELIVERY_GROUPS.get(delivery_status.strip().lower())
    if wanted is None:
        return rows
    return [r for r in rows if (r.get("delivery_status") or "").upper() in wanted]


def _safe_div(numer: float, denom: float):
    if not denom:
        return None
    return numer / denom


# Meta's messaging counters, summed from each day's stored `actions`.
# row key -> Meta action_type.
_META_MESSAGING_ACTIONS = {
    "meta_conversations": "onsite_conversion.total_messaging_connection",
    "meta_conversations_started": "onsite_conversion.messaging_conversation_started_7d",
    "meta_new_contacts": "onsite_conversion.messaging_first_reply",
    "meta_conversations_replied": "onsite_conversion.messaging_conversation_replied_7d",
    "meta_blocks": "onsite_conversion.messaging_block",
}


def _empty_insights() -> dict:
    return {
        "inline_link_clicks": 0,
        "clicks": 0,
        "spend": 0.0,
        "impressions": 0,
        "reach": 0,
        **{key: 0 for key in _META_MESSAGING_ACTIONS},
    }


def compute_cost_metrics(row: dict) -> dict:
    """Add cpc / cost_per_message / cost_per_qualified / cost_per_hot / roas.
    All guard against divide-by-zero (return None). Mutates and returns row.
    CPC uses inline_link_clicks to match the 'Clicks' column shown in the UI.
    """
    spend = float(row.get("spend", 0) or 0)
    clicks = float(row.get("inline_link_clicks", 0) or 0)
    messages = float(row.get("messages", 0) or 0)
    qualified = float(row.get("qualified", 0) or 0)
    hot = float(row.get("hot", 0) or 0)
    revenue = float(row.get("revenue", 0) or 0)

    row["cpc"] = _safe_div(spend, clicks)
    row["cost_per_message"] = _safe_div(spend, messages)
    row["cost_per_qualified"] = _safe_div(spend, qualified)
    row["cost_per_hot"] = _safe_div(spend, hot)
    row["roas"] = _safe_div(revenue, spend)
    return row


def _clip_date_from(date_from: str | None, start: str | None) -> str | None:
    """Never read before the tenant's chosen sync start date (app_settings
    meta_ads_sync_start_date). Without a start date the range is unchanged."""
    if start:
        return max(date_from, start) if date_from else start
    return date_from


def build_creative_performance(
    db,
    tenant_id: str,
    *,
    campaign_id: str | None = None,
    adset_id: str | None = None,
    ad_creative_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    delivery_status: str | None = None,
) -> list[dict]:
    """One row per creative with volume/quality/money metrics.

    Filters:
      campaign_id     -> ad_creatives.campaign_id (Anril ad_campaigns FK)
      adset_id        -> ad_creatives.meta_adset_id
      ad_creative_id  -> ad_creatives.id
      date_from/to    -> bound insights and first lead/ad attribution date
      delivery_status -> the computed delivery_status (see DELIVERY_GROUPS);
                         applied after rows are built, since the value is a
                         coalesce across three tables rather than one column
    """
    from app.services.meta_ads_insights_sync import (
        _get_ads_credentials,
        fetch_unique_reach_by_ad,
        get_ads_setting,
        get_current_ads_account_id,
        is_multi_destination,
        sum_actions,
    )

    account = get_current_ads_account_id(db, tenant_id)
    if not account:
        return []

    start = get_ads_setting(db, tenant_id, "meta_ads_sync_start_date")
    date_from = _clip_date_from(date_from, start)

    q = db.table("ad_creatives").select(
        "id,creative_label,meta_ad_id,meta_adset_id,meta_adset_name,"
        "campaign_id,effective_status,ad_effective_status,"
        "destination_type,tracked_in_anril,messaging_channels"
    ).eq("tenant_id", tenant_id).eq(
        "meta_ad_account_id", account
    ).neq("messaging_channels", "{}").eq("tracked_in_anril", True)
    if campaign_id:
        q = q.eq("campaign_id", campaign_id)
    if adset_id:
        q = q.eq("meta_adset_id", adset_id)
    if ad_creative_id:
        q = q.eq("id", ad_creative_id)
    creatives = (q.execute().data) or []
    if not creatives:
        return []
    creative_ids = [c["id"] for c in creatives]
    campaign_ids = sorted({c["campaign_id"] for c in creatives if c.get("campaign_id")})
    campaigns: dict[str, dict] = {}
    if campaign_ids:
        campaign_rows = (
            db.table("ad_campaigns").select(
                "id,campaign_name,effective_status,daily_budget,lifetime_budget,meta_created_at"
            )
            .eq("tenant_id", tenant_id)
            .eq("meta_ad_account_id", account)
            .in_("id", campaign_ids)
            .execute()
            .data
        ) or []
        campaigns = {c["id"]: c for c in campaign_rows}

    adset_ids = sorted({c["meta_adset_id"] for c in creatives if c.get("meta_adset_id")})
    adsets: dict[str, dict] = {}
    if adset_ids:
        adset_rows = (
            db.table("ad_sets").select(
                "meta_adset_id,daily_budget,lifetime_budget"
            )
            .eq("tenant_id", tenant_id)
            .eq("meta_ad_account_id", account)
            .in_("meta_adset_id", adset_ids)
            .execute()
            .data
        ) or []
        adsets = {a["meta_adset_id"]: a for a in adset_rows}

    # Insights (summed over the date range) per creative.
    ins_q = db.table("ad_insights_daily").select(
        "ad_creative_id,inline_link_clicks,clicks,spend,impressions,reach,actions,insight_date"
    ).eq("tenant_id", tenant_id).eq(
        "meta_ad_account_id", account
    ).in_("ad_creative_id", creative_ids)
    if date_from:
        ins_q = ins_q.gte("insight_date", date_from)
    if date_to:
        ins_q = ins_q.lte("insight_date", date_to)
    insights = (ins_q.execute().data) or []

    unique_reach_by_ad: dict[str, int] = {}
    credentials = _get_ads_credentials(db, tenant_id)
    if credentials:
        try:
            unique_reach_by_ad = fetch_unique_reach_by_ad(
                *credentials,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception as error:
            logger.warning("Meta unique reach fetch failed for tenant %s: %s", tenant_id, error)

    ins_by_creative: dict[str, dict] = {}
    for r in insights:
        acc = ins_by_creative.setdefault(r["ad_creative_id"], _empty_insights())
        acc["inline_link_clicks"] += int(r.get("inline_link_clicks", 0) or 0)
        acc["clicks"] += int(r.get("clicks", 0) or 0)
        acc["spend"] += float(r.get("spend", 0) or 0)
        acc["impressions"] += int(r.get("impressions", 0) or 0)
        acc["reach"] += int(r.get("reach", 0) or 0)
        for key, action_type in _META_MESSAGING_ACTIONS.items():
            acc[key] += sum_actions(r.get("actions"), {action_type})

    # Unique lead/ad relationships. The table primary key prevents the same
    # lead from being counted twice for the same Meta ad.
    meta_ad_ids = [c["meta_ad_id"] for c in creatives if c.get("meta_ad_id")]
    attributions: list[dict] = []
    if meta_ad_ids:
        attribution_q = (
            db.table("lead_meta_ad_attributions")
            .select("lead_id,meta_ad_id,first_seen_at,channel")
            .eq("tenant_id", tenant_id)
            .eq("meta_ad_account_id", account)
            .in_("meta_ad_id", meta_ad_ids)
        )
        if date_from:
            attribution_q = attribution_q.gte("first_seen_at", date_from)
        if date_to:
            attribution_q = attribution_q.lte("first_seen_at", date_to + "T23:59:59")
        attributions = (attribution_q.execute().data) or []

    lead_ids = sorted({row["lead_id"] for row in attributions if row.get("lead_id")})
    leads_by_id: dict[str, dict] = {}
    if lead_ids:
        leads = (
            db.table("leads")
            .select("id,segment")
            .eq("tenant_id", tenant_id)
            .in_("id", lead_ids)
            .is_("deleted_at", "null")
            .execute()
            .data
        ) or []
        leads_by_id = {lead["id"]: lead for lead in leads}

    funnel: dict[str, dict] = {}
    for attribution in attributions:
        lead = leads_by_id.get(attribution.get("lead_id"))
        ad_id = attribution.get("meta_ad_id")
        if not lead or not ad_id:
            continue
        f = funnel.setdefault(ad_id, {"messages": 0, "hot": 0, "by_channel": _empty_channel_counts()})
        f["messages"] += 1
        channel = attribution.get("channel") or "whatsapp"
        if channel in f["by_channel"]:
            f["by_channel"][channel] += 1
        if lead.get("segment") == "A":
            f["hot"] += 1

    def _status(c: dict) -> str | None:
        # The ad's own status first -- it is the only one that reflects an ad
        # deleted or paused on its own. The campaign/ad-set statuses are
        # fallbacks for rows synced before ad_effective_status existed.
        return (
            c.get("ad_effective_status")
            or campaigns.get(c.get("campaign_id"), {}).get("effective_status")
            or c.get("effective_status")
        )

    last_delivery = last_delivery_dates(
        db, tenant_id, account,
        [c["id"] for c in creatives if (_status(c) or "").upper() == "ACTIVE"],
    )

    out: list[dict] = []
    for c in creatives:
        ins = ins_by_creative.get(c["id"]) or _empty_insights()
        fn = funnel.get(c["meta_ad_id"], {"messages": 0, "hot": 0, "by_channel": _empty_channel_counts()})
        campaign = campaigns.get(c.get("campaign_id"), {})
        adset = adsets.get(c.get("meta_adset_id"), {})
        uses_adset_budget = (
            adset.get("daily_budget") is not None
            or adset.get("lifetime_budget") is not None
        )
        clicks = ins["inline_link_clicks"]
        messages = fn["messages"]
        no_message = max(clicks - messages, 0)
        spend = round(ins["spend"], 2)
        impressions = ins["impressions"]
        # Without Meta's de-duplicated figure, reach is the daily rows added up,
        # which counts anyone reached on two days twice -- flag it for the page.
        reach_estimated = c["meta_ad_id"] not in unique_reach_by_ad and ins["reach"] > 0
        reach = unique_reach_by_ad.get(c["meta_ad_id"], ins["reach"])
        row = {
            "ad_creative_id": c["id"],
            "creative_label": c["creative_label"],
            "meta_ad_id": c["meta_ad_id"],
            "meta_ad_account_id": account,
            "adset_id": c.get("meta_adset_id"),
            "adset_name": c.get("meta_adset_name"),
            "campaign_id": c.get("campaign_id"),
            "campaign_name": campaign.get("campaign_name") or "—",
            # When the campaign was created in Ads Manager; None until the next sync stores it.
            "campaign_created_at": campaign.get("meta_created_at"),
            "delivery_status": _status(c),
            # Only set for ACTIVE ads; None there means it has never delivered.
            "last_delivery_date": last_delivery.get(c["id"]),
            "daily_budget": (
                adset.get("daily_budget") if uses_adset_budget
                else campaign.get("daily_budget")
            ),
            "lifetime_budget": (
                adset.get("lifetime_budget") if uses_adset_budget
                else campaign.get("lifetime_budget")
            ),
            "budget_level": (
                "ad_set" if uses_adset_budget
                else "campaign" if (
                    campaign.get("daily_budget") is not None
                    or campaign.get("lifetime_budget") is not None
                )
                else None
            ),
            "impressions": impressions,
            "reach": reach,
            "reach_estimated": reach_estimated,
            "clicks_all": ins["clicks"],
            "inline_link_clicks": clicks,
            "messages": messages,
            "meta_conversations": ins["meta_conversations"],
            "meta_conversations_started": ins["meta_conversations_started"],
            "meta_new_contacts": ins["meta_new_contacts"],
            "meta_conversations_replied": ins["meta_conversations_replied"],
            "meta_blocks": ins["meta_blocks"],
            "cost_per_meta_conversation": _safe_div(spend, ins["meta_conversations_started"]),
            "clicked_no_message": no_message,
            "hot": fn["hot"],
            "spend": spend,
            "frequency": _safe_div(impressions, reach),
            "ctr": (_safe_div(clicks, impressions) or 0) * 100 if impressions else None,
            "cpm": _safe_div(spend * 1000, impressions),
            "conversation_rate": (_safe_div(messages, clicks) or 0) * 100 if clicks else None,
            "meta_conversation_rate": (
                (_safe_div(ins["meta_conversations"], clicks) or 0) * 100
                if clicks else None
            ),
            "no_message_rate": (_safe_div(no_message, clicks) or 0) * 100 if clicks else None,
            "hot_rate": (
                (_safe_div(fn["hot"], messages) or 0) * 100
                if messages else None
            ),
            "attribution_gap": messages - ins["meta_conversations"],
            "revenue": 0,
            "destination_type": c.get("destination_type"),
            "is_multi_destination": is_multi_destination(c.get("destination_type")),
            "messaging_channels": c.get("messaging_channels") or [],
            "messages_by_channel": dict(fn["by_channel"]),
        }
        compute_cost_metrics(row)
        out.append(row)

    out = filter_by_delivery(out, delivery_status)
    out.sort(key=lambda r: r["inline_link_clicks"], reverse=True)
    return out


def last_delivery_dates(db, tenant_id: str, account: str, creative_ids: list[str]) -> dict[str, str]:
    """Latest day each creative was actually shown (impressions > 0), over all time --
    not the page's date range. Lets the table flag an ad Meta reports as ACTIVE but
    that hasn't delivered in weeks. One small query per creative: callers pass only
    the ACTIVE ones, and per-creative LIMIT 1 avoids the PostgREST row cap that a
    single "all days for all ads" read would hit on a long-running account."""
    out: dict[str, str] = {}
    for creative_id in creative_ids:
        rows = (
            db.table("ad_insights_daily").select("insight_date")
            .eq("tenant_id", tenant_id)
            .eq("meta_ad_account_id", account)
            .eq("ad_creative_id", creative_id)
            .gte("impressions", 1)
            .order("insight_date", desc=True)
            .limit(1)
            .execute()
            .data
        ) or []
        if rows:
            out[creative_id] = str(rows[0]["insight_date"])[:10]
    return out


def current_account_campaigns(db, tenant_id: str) -> list[dict]:
    """Campaigns synced from the ad account connected right now. Campaigns from an
    account the tenant used before, and the webhook's ad-headline placeholders (no
    account id), are left out -- the same scope as the Meta Ads table."""
    from app.services.meta_ads_insights_sync import get_current_ads_account_id

    account = get_current_ads_account_id(db, tenant_id)
    if not account:
        return []
    return (
        db.table("ad_campaigns").select("id,campaign_name,platform,created_at,meta_created_at")
        .eq("tenant_id", tenant_id)
        .eq("meta_ad_account_id", account)
        .order("campaign_name")
        .execute()
        .data
    ) or []


def campaign_ids_with_placeholders(db, tenant_id: str, campaign_id: str) -> list[str]:
    """The campaign plus any placeholder rows standing in for its ads.

    When a lead arrives from an ad that hasn't synced yet, the WhatsApp webhook files
    it under a placeholder ad_campaigns row named after the ad's headline and keyed by
    the AD id (routes/webhook.py, get_or_create_campaign fallback). Those leads belong
    to the real campaign, so filtering by it must include them."""
    ad_ids = [
        r["meta_ad_id"]
        for r in (
            db.table("ad_creatives").select("meta_ad_id")
            .eq("tenant_id", tenant_id)
            .eq("campaign_id", campaign_id)
            .execute()
            .data
        ) or []
        if r.get("meta_ad_id")
    ]
    ids = [campaign_id]
    if ad_ids:
        placeholders = (
            db.table("ad_campaigns").select("id")
            .eq("tenant_id", tenant_id)
            .in_("external_campaign_id", ad_ids)
            .execute()
            .data
        ) or []
        ids += sorted(p["id"] for p in placeholders if p["id"] != campaign_id)
    return ids


def build_ad_filter_tree(db, tenant_id: str) -> dict:
    """Campaign -> adset -> creative option tree for cascading dropdowns."""
    from app.services.meta_ads_insights_sync import get_current_ads_account_id

    account = get_current_ads_account_id(db, tenant_id)
    if not account:
        return {"campaigns": [], "adsets": [], "creatives": [], "account_id": None}

    creatives = (
        db.table("ad_creatives").select(
            "id,creative_label,meta_ad_id,meta_adset_id,meta_adset_name,"
            "campaign_id,prefilled_message_code,messaging_channels"
        ).eq("tenant_id", tenant_id)
        .eq("meta_ad_account_id", account)
        .neq("messaging_channels", "{}")
        .eq("tracked_in_anril", True)
        .execute().data
    ) or []

    campaign_ids = sorted({c["campaign_id"] for c in creatives if c.get("campaign_id")})
    camp_names: dict[str, str] = {}
    if campaign_ids:
        camps = (
            db.table("ad_campaigns").select("id,campaign_name")
            .eq("tenant_id", tenant_id)
            .eq("meta_ad_account_id", account)
            .in_("id", campaign_ids).execute().data
        ) or []
        camp_names = {c["id"]: c["campaign_name"] for c in camps}

    return {
        "campaigns": [{"id": cid, "name": camp_names.get(cid, "—")} for cid in campaign_ids],
        "adsets": [
            {"id": aid, "name": name, "campaign_id": campc}
            for aid, name, campc in sorted({
                (c["meta_adset_id"], c.get("meta_adset_name") or "—", c.get("campaign_id"))
                for c in creatives if c.get("meta_adset_id")
            })
        ],
        "creatives": [
            {"id": c["id"], "name": c["creative_label"],
             "meta_ad_id": c.get("meta_ad_id"),
             "tracking_code": c.get("prefilled_message_code"),
             # Generate ID (the pre-filled tracking code) only works on WhatsApp.
             "messaging_channels": c.get("messaging_channels") or [],
             "adset_id": c.get("meta_adset_id"), "campaign_id": c.get("campaign_id")}
            for c in creatives
        ],
        "account_id": account,
    }


def list_ads_for_tracking(db, tenant_id: str) -> list[dict]:
    """Every messaging ad of the connected account, tracked or not, so the
    user can switch Anril tracking on or off per ad."""
    from app.services.meta_ads_insights_sync import get_current_ads_account_id, is_multi_destination

    account = get_current_ads_account_id(db, tenant_id)
    if not account:
        return []
    creatives = (
        db.table("ad_creatives").select(
            "id,creative_label,meta_ad_id,meta_adset_name,campaign_id,"
            "effective_status,ad_effective_status,destination_type,tracked_in_anril,"
            "messaging_channels"
        ).eq("tenant_id", tenant_id)
        .eq("meta_ad_account_id", account)
        .neq("messaging_channels", "{}")
        .execute().data
    ) or []

    campaign_ids = sorted({c["campaign_id"] for c in creatives if c.get("campaign_id")})
    camp_names: dict[str, str] = {}
    if campaign_ids:
        camps = (
            db.table("ad_campaigns").select("id,campaign_name")
            .eq("tenant_id", tenant_id)
            .eq("meta_ad_account_id", account)
            .in_("id", campaign_ids).execute().data
        ) or []
        camp_names = {c["id"]: c["campaign_name"] for c in camps}

    out = [
        {
            "ad_creative_id": c["id"],
            "creative_label": c.get("creative_label") or c.get("meta_ad_id") or "—",
            "campaign_name": camp_names.get(c.get("campaign_id"), "—"),
            "adset_name": c.get("meta_adset_name") or "—",
            "delivery_status": c.get("ad_effective_status") or c.get("effective_status"),
            "destination_type": c.get("destination_type"),
            "is_multi_destination": is_multi_destination(c.get("destination_type")),
            "messaging_channels": c.get("messaging_channels") or [],
            "tracked": c.get("tracked_in_anril") is True,
        }
        for c in creatives
    ]
    out.sort(key=lambda r: (r["campaign_name"] or "", r["creative_label"] or ""))
    return out


def ad_type_label(destination_type: str | None) -> str:
    """Human label for a Meta ad's destination_type (where a click goes)."""
    value = (destination_type or "").strip().upper()
    if not value:
        return "Other"
    exact = {
        "WHATSAPP": "WhatsApp",
        "ON_AD": "Instant form",
        "WEBSITE": "Website",
        "MESSENGER": "Messenger",
        "INSTAGRAM_DIRECT": "Instagram Direct",
        "INSTAGRAM_PROFILE": "Instagram profile",
        "FACEBOOK": "Facebook page",
        "APP": "App",
        "PHONE_CALL": "Calls",
    }
    if value in exact:
        return exact[value]
    from app.services.meta_ads_insights_sync import messaging_channels_for

    channels = messaging_channels_for(value)
    if len(channels) > 1:
        return "Multi-destination"
    if channels == ["whatsapp"]:
        return "WhatsApp"
    if any(word in value for word in ("MESSAGING", "MESSENGER", "INSTAGRAM")):
        return "Messaging"
    return value.replace("_", " ").title()


def build_total_reach(
    db,
    tenant_id: str,
    *,
    ad_creative_ids: list[str],
    date_from: str | None,
    date_to: str | None,
) -> dict:
    """De-duplicated reach for the Messaging ads Total row: the ads currently on
    screen, read from Meta in one call. {"reach": None} when Meta can't answer, so
    the page falls back to the added-up figure marked as an estimate."""
    from app.services.meta_ads_insights_sync import (
        _get_ads_credentials,
        fetch_total_unique_reach,
        get_ads_setting,
        get_current_ads_account_id,
    )

    account = get_current_ads_account_id(db, tenant_id)
    credentials = _get_ads_credentials(db, tenant_id)
    if not account or not credentials or not ad_creative_ids or not date_to:
        return {"reach": None}
    date_from = _clip_date_from(date_from, get_ads_setting(db, tenant_id, "meta_ads_sync_start_date"))
    if not date_from or date_from > date_to:
        return {"reach": None}

    # Only this tenant's ads on the connected account ever go to Meta.
    creatives = (
        db.table("ad_creatives").select("meta_ad_id")
        .eq("tenant_id", tenant_id)
        .eq("meta_ad_account_id", account)
        .in_("id", ad_creative_ids)
        .execute().data
    ) or []
    meta_ad_ids = sorted({str(c["meta_ad_id"]) for c in creatives if c.get("meta_ad_id")})
    if not meta_ad_ids:
        return {"reach": None}
    try:
        reach = fetch_total_unique_reach(
            *credentials, meta_ad_ids=meta_ad_ids, date_from=date_from, date_to=date_to,
        )
    except Exception as error:
        logger.warning("Meta total reach fetch failed for tenant %s: %s", tenant_id, error)
        reach = None
    return {"reach": reach}


def build_all_ads(
    db,
    tenant_id: str,
    *,
    date_from: str,
    date_to: str,
    fields: list[str],
    breakdown: str | None,
) -> dict:
    """Live Meta numbers for every eligible ad of the connected account, not only
    the ones tracked in Anril. Eligible ads come from meta_ad_registry."""
    from app.services.meta_ads_fields import fetch_meta_insights_live
    from app.services.meta_ads_insights_sync import _get_ads_credentials, get_ads_setting

    credentials = _get_ads_credentials(db, tenant_id)
    if not credentials:
        raise ValueError("Connect a Meta Ads account first")
    token, account = credentials

    registry = (
        db.table("meta_ad_registry").select("meta_ad_id")
        .eq("tenant_id", tenant_id)
        .eq("meta_ad_account_id", account)
        .eq("eligible", True)
        .execute().data
    ) or []
    eligible_ids = {r["meta_ad_id"] for r in registry if r.get("meta_ad_id")}

    start = get_ads_setting(db, tenant_id, "meta_ads_sync_start_date")
    date_from = _clip_date_from(date_from, start)
    if date_from > date_to or not eligible_ids:
        return {"data": [], "start_date": start, "date_from": date_from, "date_to": date_to}

    rows = fetch_meta_insights_live(
        token,
        account,
        date_from=date_from,
        date_to=date_to,
        keys=fields,
        breakdown=breakdown,
        ad_ids=eligible_ids,
    )
    for row in rows:
        row["ad_type"] = ad_type_label(row.get("destination_type"))
    return {"data": rows, "start_date": start, "date_from": date_from, "date_to": date_to}


PANEL_BREAKDOWNS = ("placement", "age", "gender", "region", "device")
PANEL_KEYS = [
    "inline_link_clicks", "spend", "cost_per_inline_link_click",
    "impressions", "inline_link_click_ctr",
]


def build_ad_breakdown(
    db,
    tenant_id: str,
    ad_creative_id: str,
    *,
    breakdown: str,
    date_from: str,
    date_to: str,
) -> dict | None:
    """Meta's numbers for one messaging ad, split by one breakdown, plus the whole-ad
    row for comparison. None when the ad isn't this tenant's messaging ad on the
    connected account."""
    from app.services.meta_ads_fields import fetch_meta_insights_live
    from app.services.meta_ads_insights_sync import _get_ads_credentials, get_ads_setting

    creative = (
        db.table("ad_creatives").select("id,meta_ad_id,meta_ad_account_id,messaging_channels")
        .eq("id", ad_creative_id)
        .eq("tenant_id", tenant_id)
        .execute().data
    ) or []
    if not creative:
        return None
    creative = creative[0]
    if not creative.get("messaging_channels") or not creative.get("meta_ad_id"):
        return None

    credentials = _get_ads_credentials(db, tenant_id)
    if not credentials:
        raise ValueError("Connect a Meta Ads account first")
    token, account = credentials
    if creative.get("meta_ad_account_id") != account:
        return None

    start = get_ads_setting(db, tenant_id, "meta_ads_sync_start_date")
    date_from = _clip_date_from(date_from, start)
    result = {
        "ad_creative_id": ad_creative_id,
        "breakdown": breakdown,
        "date_from": date_from,
        "date_to": date_to,
        "start_date": start,
        "overall": None,
        "rows": [],
    }
    if date_from > date_to:
        return result

    ad_ids = {str(creative["meta_ad_id"])}
    split = fetch_meta_insights_live(
        token, account,
        date_from=date_from, date_to=date_to, keys=PANEL_KEYS,
        breakdown=breakdown, ad_ids=ad_ids,
    )
    whole = fetch_meta_insights_live(
        token, account,
        date_from=date_from, date_to=date_to, keys=PANEL_KEYS,
        breakdown=None, ad_ids=ad_ids,
    )
    result["overall"] = whole[0]["values"] if whole else None
    rows = [{"label": r.get("breakdown") or "Unknown", "values": r["values"]} for r in split]
    rows.sort(key=lambda r: r["values"].get("inline_link_clicks") or 0, reverse=True)
    result["rows"] = rows
    return result
