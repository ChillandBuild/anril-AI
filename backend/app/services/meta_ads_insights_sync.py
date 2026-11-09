"""Pull Meta Ads Insights (level=ad) per tenant, auto-import creatives, and
store daily clicks/spend. Credentials come from app_settings
(meta_ads_access_token / meta_ads_account_id, plaintext). Read-only against
Meta (ads_read). Service-role DB writes bypass RLS.

Only messaging ad sets (any ad set whose destination opens WhatsApp, Instagram
Direct or Messenger, alone or mixed) are kept, and only for ads marked eligible
in meta_ad_registry (see refresh_ad_registry).
"""
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from app.db.supabase import get_supabase
from app.services.growth import get_or_create_campaign

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com/v21.0"
_INSIGHT_FIELDS = (
    "ad_id,ad_name,adset_id,adset_name,campaign_id,campaign_name,"
    "optimization_goal,inline_link_clicks,clicks,spend,impressions,reach,actions"
)

_CAMPAIGN_FIELDS = "id,name,objective,effective_status,daily_budget,lifetime_budget,bid_strategy,created_time,updated_time"
_ADSET_FIELDS = (
    "id,name,campaign_id,optimization_goal,effective_status,destination_type,"
    "daily_budget,lifetime_budget,start_time,end_time,updated_time"
)
_AD_FIELDS = "id,name,adset_id,campaign_id,effective_status,created_time"

# Meta's ads/adsets edges hide DELETED and ARCHIVED objects unless the request
# asks for them by name. Without this, an ad deleted in Ads Manager simply stops
# appearing and its last-known status ("ACTIVE") sticks in our table forever.
_ALL_AD_STATUSES = [
    "ACTIVE", "PAUSED", "DELETED", "ARCHIVED", "PENDING_REVIEW", "DISAPPROVED",
    "PREAPPROVED", "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED", "ADSET_PAUSED",
    "IN_PROCESS", "WITH_ISSUES",
]
_ALL_CAMPAIGN_STATUSES = ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED", "IN_PROCESS", "WITH_ISSUES"]
_ALL_ADSET_STATUSES = [
    "ACTIVE", "PAUSED", "DELETED", "ARCHIVED", "PENDING_REVIEW", "DISAPPROVED",
    "PREAPPROVED", "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED", "IN_PROCESS",
    "WITH_ISSUES",
]

def sum_actions(actions, action_types: set[str]) -> int:
    """Sum the integer `value` across entries whose action_type is in the set."""
    total = 0
    for a in (actions or []):
        if a.get("action_type") in action_types:
            try:
                total += int(float(a.get("value", 0) or 0))
            except (TypeError, ValueError):
                continue
    return total


def normalize_account_id(raw: str) -> str:
    """Return the ad account id in act_<digits> form."""
    v = (raw or "").strip()
    return v if v.startswith("act_") else f"act_{v}"


def _get_ads_credentials(db, tenant_id: str) -> tuple[str, str] | None:
    """(access_token, act_account_id) from app_settings, or None if unset."""
    rows = (
        db.table("app_settings").select("key,value")
        .eq("tenant_id", tenant_id)
        .in_("key", ["meta_ads_access_token", "meta_ads_account_id"])
        .execute()
    )
    kv = {r["key"]: r["value"] for r in (rows.data or []) if r.get("value")}
    token = kv.get("meta_ads_access_token")
    account = kv.get("meta_ads_account_id")
    if not token or not account:
        return None
    return token, normalize_account_id(account)


def get_current_ads_account_id(db, tenant_id: str) -> str | None:
    """Return the configured account id without requiring the token."""
    rows = (
        db.table("app_settings").select("key,value")
        .eq("tenant_id", tenant_id)
        .eq("key", "meta_ads_account_id")
        .limit(1)
        .execute()
    )
    value = ((rows.data or [{}])[0]).get("value")
    return normalize_account_id(value) if value else None


def get_ads_setting(db, tenant_id: str, key: str) -> str | None:
    """Read one app_settings value for this tenant, or None when unset."""
    rows = (
        db.table("app_settings").select("value")
        .eq("tenant_id", tenant_id).eq("key", key)
        .limit(1).execute()
    )
    return ((rows.data or [{}])[0]).get("value") or None


def set_ads_setting(db, tenant_id: str, key: str, value: str) -> None:
    """Upsert one plaintext app_settings value for this tenant."""
    db.table("app_settings").upsert({
        "tenant_id": tenant_id,
        "key": key,
        "value": value,
        "is_secret": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="tenant_id,key").execute()


def messaging_channels_for(destination_type: str | None) -> list[str]:
    """The chat apps an ad set's destination opens, in a fixed order:
    WhatsApp, Instagram Direct, Messenger. Empty for non-messaging destinations
    (website, instant form, Instagram profile, ...)."""
    dt = (destination_type or "").upper()
    channels: list[str] = []
    if "WHATSAPP" in dt:
        channels.append("whatsapp")
    if "INSTAGRAM_DIRECT" in dt:
        channels.append("instagram")
    if "MESSENGER" in dt:
        channels.append("messenger")
    return channels


def is_messaging_adset(row: dict | None) -> bool:
    """Ad sets that open at least one chat app (WhatsApp, Instagram Direct or Messenger)."""
    return bool(messaging_channels_for((row or {}).get("destination_type")))


def is_click_to_whatsapp_adset(row: dict | None) -> bool:
    """Ad sets whose destinations include WhatsApp: WhatsApp-only and multi-destination (Messenger/Instagram + WhatsApp)."""
    return "WHATSAPP" in ((row or {}).get("destination_type") or "").upper()


def is_multi_destination(destination_type: str | None) -> bool:
    """Opens more than one chat app (e.g. WhatsApp + Messenger, or Messenger + Instagram).
    Meta's numbers cover all of them."""
    return len(messaging_channels_for(destination_type)) > 1


def _major_currency_units(value) -> float | None:
    """Meta returns budget values in the account currency's minor unit."""
    if value in (None, ""):
        return None
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return None


def fetch_prefilled_greeting(token: str, ad_id: str) -> str | None:
    """Fetch the exact autofill text Meta shows in a lead's message box when they
    tap this Click-to-WhatsApp ad -- object_story_spec.link_data.page_welcome_message,
    which is itself a JSON-encoded string, with the real text nested at
    text_format.message.autofill_message.content. Live-verified 2026-08-02 against
    a real connected ad account and creative.

    Best-effort: returns None on any failure, or if this ad uses the newer
    Advantage+/dynamic-creative format (a separate welcome_message_sequence tied
    to the phone number, not the creative) -- not handled here, see
    active-backlog.md. A None return means "unknown", not "no pre-fill" --
    callers must not treat it as evidence either way.
    """
    try:
        with httpx.Client(timeout=15) as client:
            ad_resp = client.get(
                f"{_GRAPH_BASE}/{ad_id}",
                params={"fields": "creative{id}", "access_token": token},
            )
            ad_resp.raise_for_status()
            creative_id = (ad_resp.json().get("creative") or {}).get("id")
            if not creative_id:
                return None

            cre_resp = client.get(
                f"{_GRAPH_BASE}/{creative_id}",
                params={
                    "fields": "object_story_spec{link_data{page_welcome_message}}",
                    "access_token": token,
                },
            )
            cre_resp.raise_for_status()
            raw = (
                (cre_resp.json().get("object_story_spec") or {})
                .get("link_data", {})
                .get("page_welcome_message")
            )
            if not raw:
                return None
            parsed = json.loads(raw)
            content = (
                parsed.get("text_format", {})
                .get("message", {})
                .get("autofill_message", {})
                .get("content")
            )
            return content.strip() if content else None
    except Exception as e:
        logger.warning(f"Failed to fetch prefilled greeting for ad {ad_id}: {e}")
        return None


def upsert_creative_from_insight(
    db,
    tenant_id: str,
    row: dict,
    *,
    account: str | None = None,
    adset_meta: dict | None = None,
    token: str | None = None,
) -> str | None:
    """Insert-or-reuse an ad_creatives row keyed by (tenant_id, meta_ad_id).
    Links to an ad_campaigns row via get_or_create_campaign. Never overwrites a
    tenant-edited creative_label (label_edited=True). Returns ad_creatives.id.

    When token is provided and this is a CTWA creative missing prefilled_greeting_text,
    fetches it once from Meta and stores it -- this is the ground truth scoring_engine.py
    compares an incoming ad-referred message against to tell "sent Meta's pre-fill
    untouched" apart from "edited it before sending."
    """
    ad_id = (row.get("ad_id") or "").strip()
    if not ad_id:
        return None

    campaign = get_or_create_campaign(
        db=db,
        tenant_id=tenant_id,
        platform="whatsapp",
        campaign_name=row.get("campaign_name"),
        external_campaign_id=row.get("campaign_id"),
    )
    campaign_id = campaign["id"] if campaign else None
    if campaign_id and account:
        db.table("ad_campaigns").update({
            "meta_ad_account_id": account,
        }).eq("id", campaign_id).eq("tenant_id", tenant_id).execute()
    if adset_meta and adset_meta.get("id") and account:
        db.table("ad_sets").upsert({
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "meta_adset_id": adset_meta.get("id"),
            "meta_ad_account_id": account,
            "adset_name": adset_meta.get("name") or row.get("adset_name"),
            "optimization_goal": adset_meta.get("optimization_goal"),
            "effective_status": adset_meta.get("effective_status"),
            "daily_budget": _major_currency_units(adset_meta.get("daily_budget")),
            "lifetime_budget": _major_currency_units(adset_meta.get("lifetime_budget")),
            "start_time": adset_meta.get("start_time"),
            "end_time": adset_meta.get("end_time"),
            "meta_updated_at": adset_meta.get("updated_time"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="tenant_id,meta_adset_id").execute()

    existing = (
        db.table("ad_creatives").select("id,label_edited,prefilled_greeting_text")
        .eq("tenant_id", tenant_id).eq("meta_ad_id", ad_id)
        .limit(1).execute()
    )
    found = (existing.data or [None])[0]
    now_iso = datetime.now(timezone.utc).isoformat()
    is_ctwa = is_click_to_whatsapp_adset(adset_meta)
    channels = messaging_channels_for((adset_meta or {}).get("destination_type"))

    if found:
        updates = {
            "meta_adset_id": row.get("adset_id"),
            "meta_adset_name": row.get("adset_name"),
            "meta_campaign_id": row.get("campaign_id"),
            "campaign_id": campaign_id,
            "meta_ad_account_id": account,
            "is_click_to_whatsapp": is_ctwa,
            "optimization_goal": (adset_meta or {}).get("optimization_goal") or row.get("optimization_goal"),
            "effective_status": (adset_meta or {}).get("effective_status"),
            "cta_type": "WHATSAPP_MESSAGE" if is_ctwa else None,
            "destination_type": (adset_meta or {}).get("destination_type"),
            "messaging_channels": channels,
            "updated_at": now_iso,
        }
        if not found.get("label_edited"):
            updates["creative_label"] = (row.get("ad_name") or ad_id)
        if is_ctwa and token and not found.get("prefilled_greeting_text"):
            greeting = fetch_prefilled_greeting(token, ad_id)
            if greeting:
                updates["prefilled_greeting_text"] = greeting
        db.table("ad_creatives").update(updates).eq("id", found["id"]).eq(
            "tenant_id", tenant_id
        ).execute()
        return found["id"]

    greeting = fetch_prefilled_greeting(token, ad_id) if (is_ctwa and token) else None
    inserted = db.table("ad_creatives").insert({
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "meta_ad_id": ad_id,
        "meta_adset_id": row.get("adset_id"),
        "meta_adset_name": row.get("adset_name"),
        "meta_campaign_id": row.get("campaign_id"),
        "meta_ad_account_id": account,
        "creative_label": (row.get("ad_name") or ad_id),
        "is_click_to_whatsapp": is_ctwa,
        "optimization_goal": (adset_meta or {}).get("optimization_goal") or row.get("optimization_goal"),
        "effective_status": (adset_meta or {}).get("effective_status"),
        "cta_type": "WHATSAPP_MESSAGE" if is_ctwa else None,
        "destination_type": (adset_meta or {}).get("destination_type"),
        "messaging_channels": channels,
        "prefilled_greeting_text": greeting,
        "created_at": now_iso,
        "updated_at": now_iso,
    }).execute()
    return (inserted.data or [{}])[0].get("id")


_MAX_HISTORY_DAYS = 1125  # Meta keeps ~37 months of insights


def compute_sync_since(start_date: str | None, today: date) -> str | None:
    """max(start_date, today - 37 months) as YYYY-MM-DD, or None when no start date is set."""
    if not start_date:
        return None
    try:
        start = date.fromisoformat(start_date)
    except ValueError:
        logger.warning(f"Ignoring malformed meta_ads_sync_start_date: {start_date!r}")
        return None
    floor = today - timedelta(days=_MAX_HISTORY_DAYS)
    return max(start, floor).isoformat()


def _date_chunks(since: str, until: str, days: int = 30) -> list[tuple[str, str]]:
    """Contiguous inclusive [start, end] windows of at most `days` days covering since..until."""
    out: list[tuple[str, str]] = []
    cur = date.fromisoformat(since)
    end = date.fromisoformat(until)
    while cur <= end:
        chunk_end = min(cur + timedelta(days=days - 1), end)
        out.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return out


def _fetch_insight_pages(token: str, account: str, window: dict) -> list[dict]:
    """Page through level=ad daily insights for one window (date_preset or time_range).
    One page is enough for typical accounts; follow paging.next if present."""
    url = f"{_GRAPH_BASE}/{account}/insights"
    params = {
        "level": "ad",
        "fields": _INSIGHT_FIELDS,
        **window,
        "time_increment": "1",   # one row per ad PER DAY
        "limit": "200",
        "access_token": token,
    }
    out: list[dict] = []
    with httpx.Client(timeout=30) as client:
        next_url, next_params = url, params
        for _ in range(20):  # hard cap on pages
            resp = client.get(next_url, params=next_params)
            resp.raise_for_status()
            body = resp.json()
            out.extend(body.get("data", []))
            nxt = (body.get("paging") or {}).get("next")
            if not nxt:
                break
            next_url, next_params = nxt, None  # next already carries all params
    return out


def _fetch_insights(token: str, account: str, date_preset: str) -> list[dict]:
    """Insights for a Meta date_preset (e.g. last_30d, today)."""
    return _fetch_insight_pages(token, account, {"date_preset": date_preset})


def _fetch_insights_range(token: str, account: str, since: str, until: str) -> list[dict]:
    """Insights for an explicit inclusive YYYY-MM-DD range."""
    return _fetch_insight_pages(
        token, account, {"time_range": json.dumps({"since": since, "until": until})},
    )


def _fetch_sync_insights(
    token: str, account: str, date_preset: str, *, backfill_from: str | None = None,
) -> list[dict]:
    """Fetch the completed reporting window plus today's live delivery once.

    With backfill_from, fetch every 30-day chunk from backfill_from through today
    instead; today is included in the chunks, so there is no separate "today" call.
    """
    if backfill_from:
        today = datetime.now(timezone.utc).date().isoformat()
        rows = []
        for since, until in _date_chunks(backfill_from, today):
            rows.extend(_fetch_insights_range(token, account, since, until))
    else:
        rows = _fetch_insights(token, account, date_preset)
        if date_preset == "last_30d":
            rows.extend(_fetch_insights(token, account, "today"))
    by_ad_day = {
        (str(row.get("ad_id") or ""), str(row.get("date_start") or "")): row
        for row in rows
    }
    return list(by_ad_day.values())


def _fetch_campaigns(token: str, account: str) -> list[dict]:
    """Includes archived/deleted campaigns: their ads still appear in the Meta Ads
    table, which shows each campaign's creation date."""
    return _fetch_paged_all_statuses(
        f"{_GRAPH_BASE}/{account}/campaigns",
        {"fields": _CAMPAIGN_FIELDS, "limit": "200", "access_token": token},
        status_field="campaign.effective_status",
        statuses=_ALL_CAMPAIGN_STATUSES,
    )


def fetch_unique_reach_by_ad(
    token: str,
    account: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, int]:
    """Return Meta's de-duplicated reach for each ad in the reporting window."""
    url = f"{_GRAPH_BASE}/{account}/insights"
    params = {
        "level": "ad",
        "fields": "ad_id,reach",
        "limit": "200",
        "access_token": token,
    }
    if date_from and date_to:
        params["time_range"] = json.dumps({"since": date_from, "until": date_to})
    else:
        params["date_preset"] = "last_30d"

    rows: list[dict] = []
    with httpx.Client(timeout=30) as client:
        next_url, next_params = url, params
        for _ in range(20):
            response = client.get(next_url, params=next_params)
            response.raise_for_status()
            body = response.json()
            rows.extend(body.get("data", []))
            next_url = (body.get("paging") or {}).get("next")
            if not next_url:
                break
            next_params = None

    return {
        str(row["ad_id"]): int(float(row.get("reach", 0) or 0))
        for row in rows
        if row.get("ad_id")
    }


def fetch_reach_by_level(
    token: str,
    account: str,
    *,
    level: str,
    meta_ad_ids: list[str] | None,
    date_from: str,
    date_to: str,
) -> dict[str, int] | None:
    """Meta's de-duplicated reach per campaign or per ad set ({id: reach}), for the
    reports' Campaigns / Ad sets views -- adding the ads' reach would count anyone
    who saw two of them twice. `meta_ad_ids` None means every ad in the account.
    None when there are too many ads to filter by."""
    if level not in ("campaign", "adset"):
        raise ValueError(f"unknown level: {level}")
    if meta_ad_ids is not None and (not meta_ad_ids or len(meta_ad_ids) > _TOTAL_REACH_MAX_ADS):
        return None
    filtering = [{"field": "ad.effective_status", "operator": "IN", "value": list(_ALL_AD_STATUSES)}]
    if meta_ad_ids is not None:
        filtering.insert(0, {"field": "ad.id", "operator": "IN", "value": sorted(meta_ad_ids)})
    rows = _fetch_paged(f"{_GRAPH_BASE}/{account}/insights", {
        "level": level,
        "fields": f"{level}_id,reach",
        "time_range": json.dumps({"since": date_from, "until": date_to}),
        "filtering": json.dumps(filtering),
        "limit": "200",
        "access_token": token,
    })
    return {
        str(r[f"{level}_id"]): int(float(r.get("reach", 0) or 0))
        for r in rows if r.get(f"{level}_id")
    }


# Meta's ad.id filter is kept to the size the All ads report already uses.
_TOTAL_REACH_MAX_ADS = 50


def fetch_total_unique_reach(
    token: str,
    account: str,
    *,
    meta_ad_ids: list[str] | None,
    date_from: str,
    date_to: str,
) -> int | None:
    """Meta's de-duplicated reach across a set of ads -- someone who saw two of
    them counts once, as in Ads Manager's total row. `meta_ad_ids` None means
    every ad in the account. None when there are too many ads to filter by."""
    if meta_ad_ids is not None and (not meta_ad_ids or len(meta_ad_ids) > _TOTAL_REACH_MAX_ADS):
        return None
    # Without the status filter Meta drops archived/deleted ads.
    filtering = [{"field": "ad.effective_status", "operator": "IN", "value": list(_ALL_AD_STATUSES)}]
    if meta_ad_ids is not None:
        filtering.insert(0, {"field": "ad.id", "operator": "IN", "value": sorted(meta_ad_ids)})
    params = {
        "level": "account",
        "fields": "reach",
        "time_range": json.dumps({"since": date_from, "until": date_to}),
        "filtering": json.dumps(filtering),
        "access_token": token,
    }
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{_GRAPH_BASE}/{account}/insights", params=params)
        response.raise_for_status()
        data = response.json().get("data") or []
    return int(float(data[0].get("reach", 0) or 0)) if data else 0


def _fetch_paged(url: str, params: dict) -> list[dict]:
    """GET an edge and follow paging.next. Hard cap of 20 pages, as elsewhere."""
    out: list[dict] = []
    with httpx.Client(timeout=30) as client:
        next_url, next_params = url, params
        for _ in range(20):
            resp = client.get(next_url, params=next_params)
            resp.raise_for_status()
            body = resp.json()
            out.extend(body.get("data", []))
            nxt = (body.get("paging") or {}).get("next")
            if not nxt:
                break
            next_url, next_params = nxt, None  # next already carries all params
    return out


def _fetch_paged_all_statuses(
    url: str, params: dict, *, status_field: str, statuses: list[str]
) -> list[dict]:
    """Same as _fetch_paged, but asks Meta to include DELETED/ARCHIVED objects.

    The filtering syntax is version-sensitive, so a rejected filter falls back to
    an unfiltered fetch rather than failing the whole sync -- the caller's
    last_seen_at reconciliation still catches deletions in that case, it just
    can't tell DELETED from ARCHIVED.
    """
    filtered = dict(params)
    filtered["filtering"] = json.dumps(
        [{"field": status_field, "operator": "IN", "value": statuses}]
    )
    try:
        return _fetch_paged(url, filtered)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 400:
            logger.warning(
                f"Meta rejected {status_field} filtering ({e.response.text[:200]}); "
                "refetching without it"
            )
            return _fetch_paged(url, params)
        raise


def _fetch_adsets(token: str, account: str) -> list[dict]:
    """Includes deleted/archived ad sets so a deleted ad's insight rows can still
    be classified as a messaging ad set by _select_rows."""
    return _fetch_paged_all_statuses(
        f"{_GRAPH_BASE}/{account}/adsets",
        {"fields": _ADSET_FIELDS, "limit": "200", "access_token": token},
        status_field="adset.effective_status",
        statuses=_ALL_ADSET_STATUSES,
    )


def _fetch_ads(token: str, account: str) -> list[dict]:
    """Every ad in the account with its own effective_status, deleted ones included.

    This is the only place ad-level status enters the system -- insights carry no
    status, and the adset/campaign edges describe their own level, not the ad's.
    """
    return _fetch_paged_all_statuses(
        f"{_GRAPH_BASE}/{account}/ads",
        {"fields": _AD_FIELDS, "limit": "200", "access_token": token},
        status_field="ad.effective_status",
        statuses=_ALL_AD_STATUSES,
    )


def sync_campaign_meta(
    db,
    tenant_id: str,
    token: str,
    account: str,
    *,
    campaign_ids: set[str] | None = None,
) -> int:
    """Update ad_campaigns rows with objective/status/budget from Meta. Matches on
    external_campaign_id (Meta campaign id). Best-effort; returns count updated."""
    campaigns = _fetch_campaigns(token, account)
    updated = 0
    for c in campaigns:
        cid = (c.get("id") or "").strip()
        if not cid:
            continue
        if campaign_ids is not None and cid not in campaign_ids:
            # No WhatsApp delivery in this window, but the Meta Ads table still lists the
            # campaign's ads, so keep its Ads Manager timestamps current anyway.
            timestamps = {
                key: value
                for key, value in {
                    "meta_created_at": c.get("created_time"),
                    "meta_updated_at": c.get("updated_time"),
                }.items()
                if value
            }
            if timestamps:
                db.table("ad_campaigns").update(timestamps).eq(
                    "external_campaign_id", cid
                ).eq("tenant_id", tenant_id).execute()
            continue
        daily = c.get("daily_budget")
        lifetime = c.get("lifetime_budget")
        payload = {
            "objective": c.get("objective"),
            "effective_status": c.get("effective_status"),
            # Meta returns budgets in minor units (paise) as strings.
            "daily_budget": (float(daily) / 100.0) if daily else None,
            "lifetime_budget": (float(lifetime) / 100.0) if lifetime else None,
            "bid_strategy": c.get("bid_strategy"),
            "meta_created_at": c.get("created_time"),
            "meta_updated_at": c.get("updated_time"),
            "meta_ad_account_id": account,
        }
        res = (
            db.table("ad_campaigns").update(payload)
            .eq("external_campaign_id", cid).eq("tenant_id", tenant_id).execute()
        )
        if res.data:
            updated += 1
    return updated


def _chunks(items: list[str], size: int = 100):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def sync_ad_delivery_status(
    db,
    tenant_id: str,
    token: str,
    account: str,
    *,
    ads: list[dict] | None = None,
) -> dict:
    """Write each ad's own effective_status onto ad_creatives, and mark the ads
    Meta no longer returns as DELETED.

    This is the fix for stale "Active" badges. The rest of the sync is
    update-only -- it walks what Meta returns and updates matching rows -- so an
    ad deleted in Ads Manager just stopped being touched and kept whatever status
    it last had. Two passes close that:

      1. Every ad the /ads edge returns (deleted ones included, see _fetch_ads)
         gets its real status written and last_seen_at stamped.
      2. Any ad_creatives row for this account that pass 1 did not touch is gone
         from Ads Manager entirely -- mark it DELETED.

    An empty `ads` list means a failed or permission-denied fetch far more often
    than a genuinely empty ad account, so pass 2 is skipped in that case rather
    than marking the tenant's whole table deleted. Returns a diagnostic dict.
    """
    if ads is None:
        ads = _fetch_ads(token, account)
    if not ads:
        logger.warning(
            f"Ads edge returned nothing for tenant {tenant_id} account {account}; "
            "skipping delivery-status reconciliation"
        )
        return {"updated": 0, "marked_deleted": 0, "reconciled": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    by_status: dict[str, list[str]] = {}
    for ad in ads:
        ad_id = (ad.get("id") or "").strip()
        if not ad_id:
            continue
        by_status.setdefault(ad.get("effective_status") or "UNKNOWN", []).append(ad_id)

    updated = 0
    for status, ad_ids in by_status.items():
        for chunk in _chunks(ad_ids):
            res = (
                db.table("ad_creatives")
                .update({"ad_effective_status": status, "last_seen_at": now_iso})
                .eq("tenant_id", tenant_id)
                .eq("meta_ad_account_id", account)
                .in_("meta_ad_id", chunk)
                .execute()
            )
            updated += len(res.data or [])

    seen_ad_ids = {ad_id for ids in by_status.values() for ad_id in ids}
    existing = (
        db.table("ad_creatives").select("id,meta_ad_id,ad_effective_status")
        .eq("tenant_id", tenant_id)
        .eq("meta_ad_account_id", account)
        .execute().data
    ) or []
    gone = [
        r["id"] for r in existing
        if (r.get("meta_ad_id") or "").strip() not in seen_ad_ids
        and r.get("ad_effective_status") != "DELETED"
    ]
    for chunk in _chunks(gone):
        db.table("ad_creatives").update(
            {"ad_effective_status": "DELETED", "last_seen_at": now_iso}
        ).eq("tenant_id", tenant_id).in_("id", chunk).execute()

    if gone:
        logger.info(
            f"Ads delivery sync: tenant {tenant_id} marked {len(gone)} creative(s) "
            "DELETED (no longer returned by Meta)"
        )
    return {"updated": updated, "marked_deleted": len(gone), "reconciled": True}


def _write_insight_row(
    db,
    tenant_id: str,
    creative_id: str,
    row: dict,
    *,
    account: str | None = None,
) -> None:
    """Upsert one ad_insights_daily row. Raises on failure — caller decides
    whether to swallow (background job) or surface (manual trigger)."""
    insight_date = row.get("date_start")  # present when time_increment=1
    if not insight_date:
        raise ValueError(f"insight row for ad_id={row.get('ad_id')} has no date_start")
    db.table("ad_insights_daily").upsert({
        "tenant_id": tenant_id,
        "ad_creative_id": creative_id,
        "meta_ad_account_id": account,
        "insight_date": insight_date,
        "clicks": int(float(row.get("clicks", 0) or 0)),
        "inline_link_clicks": int(float(row.get("inline_link_clicks", 0) or 0)),
        "spend": float(row.get("spend", 0) or 0),
        "impressions": int(float(row.get("impressions", 0) or 0)),
        "reach": int(float(row.get("reach", 0) or 0)),
        "actions": row.get("actions") or [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="tenant_id,ad_creative_id,insight_date").execute()


def _parse_iso_datetime(raw) -> datetime | None:
    """Parse an ISO timestamp, a trailing "Z", or Meta's "+0530" offset form. None on failure."""
    if not raw:
        return None
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "T" in s:
        s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    try:
        parsed = datetime.fromisoformat(s)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def refresh_ad_registry(
    db, tenant_id: str, account: str, ads: list[dict], adsets: list[dict],
) -> dict[str, str | None]:
    """Decide which of this account's ads are messaging-eligible and persist the registry.

    An ad is eligible when it was already eligible (sticky: pausing or deleting it
    later never removes it), or it was created on/after the moment the account
    connected, or, during the one-time join snapshot (first sync of this account),
    it was ACTIVE. Returns {meta_ad_id: created date YYYY-MM-DD or None} for every
    eligible ad of this account. An empty `ads` list (a failed fetch) writes nothing
    and returns the map from existing rows.
    """
    existing = (
        db.table("meta_ad_registry")
        .select("meta_ad_id,meta_ad_account_id,eligible,status_at_join,ad_created_time")
        .eq("tenant_id", tenant_id).execute().data
    ) or []
    existing_by_ad = {str(r.get("meta_ad_id") or ""): r for r in existing}
    eligible_map: dict[str, str | None] = {}

    if ads:
        now_iso = datetime.now(timezone.utc).isoformat()
        connected_at = _parse_iso_datetime(get_ads_setting(db, tenant_id, "meta_ads_connected_at"))
        if connected_at is None:
            connected_at = datetime.now(timezone.utc)
            set_ads_setting(db, tenant_id, "meta_ads_connected_at", connected_at.isoformat())
        snapshot_mode = get_ads_setting(db, tenant_id, "meta_ads_join_snapshot_account") != account
        adset_by_id = {str(a.get("id")): a for a in adsets if a.get("id")}

        rows_out: list[dict] = []
        for ad in ads:
            ad_id = str(ad.get("id") or "").strip()
            if not ad_id:
                continue
            dest = adset_by_id.get(str(ad.get("adset_id") or ""), {}).get("destination_type")
            created = _parse_iso_datetime(ad.get("created_time"))
            status = ad.get("effective_status")
            prior = existing_by_ad.get(ad_id) or {}
            eligible = (
                bool(prior.get("eligible"))
                or (snapshot_mode and status == "ACTIVE")
                or (created is not None and created >= connected_at)
            )
            rows_out.append({
                "tenant_id": tenant_id,
                "meta_ad_account_id": account,
                "meta_ad_id": ad_id,
                "meta_adset_id": ad.get("adset_id"),
                "meta_campaign_id": ad.get("campaign_id"),
                "destination_type": dest,
                "ad_created_time": created.isoformat() if created else None,
                "status_at_join": status if snapshot_mode else prior.get("status_at_join"),
                "eligible": eligible,
                "updated_at": now_iso,
            })
            if eligible:
                eligible_map[ad_id] = created.date().isoformat() if created else None
        for chunk in _chunks(rows_out):
            db.table("meta_ad_registry").upsert(
                chunk, on_conflict="tenant_id,meta_ad_id"
            ).execute()
        if snapshot_mode:
            set_ads_setting(db, tenant_id, "meta_ads_join_snapshot_account", account)

    # Eligible rows of this account that this run did not see (e.g. deleted ads).
    for r in existing:
        ad_id = str(r.get("meta_ad_id") or "")
        if r.get("meta_ad_account_id") != account or not r.get("eligible") or ad_id in eligible_map:
            continue
        created = _parse_iso_datetime(r.get("ad_created_time"))
        eligible_map[ad_id] = created.date().isoformat() if created else None
    return eligible_map


def _select_rows(
    rows: list[dict],
    adsets: list[dict],
    eligible: dict[str, str | None],
    since: str | None,
) -> tuple[list[dict], dict[str, dict]]:
    """Keep insight rows for eligible ads on messaging ad sets, dated on or after
    `since`. No per-ad creation-day check: Meta reports no days before an ad
    existed, and comparing its created_time (any offset) to date_start (account
    time zone) could drop a real first day. Returns (kept rows, adset_by_id)."""
    adset_by_id = {str(r.get("id")): r for r in adsets if r.get("id")}
    kept: list[dict] = []
    for row in rows:
        ad_id = str(row.get("ad_id") or "")
        if ad_id not in eligible:
            continue
        if not is_messaging_adset(adset_by_id.get(str(row.get("adset_id")))):
            continue
        day = str(row.get("date_start") or "")
        if since is not None and day < since:
            continue
        kept.append(row)
    return kept, adset_by_id


def _fetch_ads_best_effort(token: str, account: str, tenant_id: str) -> list[dict]:
    """The /ads edge, or [] on failure: refresh_ad_registry then keeps the eligible
    ads it already knows, and delivery-status reconciliation skips this run."""
    try:
        return _fetch_ads(token, account)
    except Exception as e:
        logger.warning(f"Ads list fetch failed for tenant {tenant_id}: {e}")
        return []


def _sync_window(db, tenant_id: str) -> tuple[str | None, str | None]:
    """(since, backfill_from): the history floor, and the start of a backfill still owed."""
    start = get_ads_setting(db, tenant_id, "meta_ads_sync_start_date")
    since = compute_sync_since(start, datetime.now(timezone.utc).date())
    backfilled = get_ads_setting(db, tenant_id, "meta_ads_backfilled_from")
    backfill_from = since if since and (not backfilled or backfilled > since) else None
    return since, backfill_from


def _record_sync_metadata(db, tenant_id: str, account: str, written: int) -> None:
    set_ads_setting(db, tenant_id, "meta_ads_last_sync_at", datetime.now(timezone.utc).isoformat())
    set_ads_setting(db, tenant_id, "meta_ads_last_sync_count", str(written))
    set_ads_setting(db, tenant_id, "meta_ads_last_synced_account_id", account)


def sync_tenant_ad_insights(db, tenant_id: str, *, date_preset: str = "last_30d") -> int:
    """Pull level=ad daily insights, including today's live delivery, and upsert rows.
    Only messaging ad sets (any chat app), and only eligible ads (see
    refresh_ad_registry), are written. Returns number of daily rows written.
    Best-effort per row — used by the background scheduler, which must never
    crash on one tenant's bad data.
    """
    creds = _get_ads_credentials(db, tenant_id)
    if not creds:
        return 0
    token, account = creds
    since, backfill_from = _sync_window(db, tenant_id)
    try:
        # Meta's last_30d preset contains completed days only. Include today's
        # partial delivery so the dashboard agrees with Ads Manager.
        rows = _fetch_sync_insights(token, account, date_preset, backfill_from=backfill_from)
        adsets = _fetch_adsets(token, account)
    except Exception as e:
        logger.warning(f"Ads insights fetch failed for tenant {tenant_id}: {e}")
        return 0
    ads = _fetch_ads_best_effort(token, account, tenant_id)
    try:
        eligible = refresh_ad_registry(db, tenant_id, account, ads, adsets)
    except Exception as e:
        logger.warning(f"ad registry update failed (tenant {tenant_id}): {e}")
        return 0
    selected, adset_by_id = _select_rows(rows, adsets, eligible, since)

    written = 0
    for row in selected:
        creative_id = upsert_creative_from_insight(
            db,
            tenant_id,
            row,
            account=account,
            adset_meta=adset_by_id.get(str(row.get("adset_id"))),
            token=token,
        )
        if not creative_id:
            continue
        try:
            _write_insight_row(db, tenant_id, creative_id, row, account=account)
            written += 1
        except Exception as e:
            logger.warning(f"insight row write failed (tenant {tenant_id}): {e}")
    try:
        sync_campaign_meta(
            db,
            tenant_id,
            token,
            account,
            campaign_ids={str(r.get("campaign_id")) for r in selected if r.get("campaign_id")},
        )
    except Exception as e:
        logger.warning(f"campaign meta sync failed (tenant {tenant_id}): {e}")
    # After the creative upserts, so ads imported in this run get a status too.
    try:
        sync_ad_delivery_status(db, tenant_id, token, account, ads=ads)
    except Exception as e:
        logger.warning(f"ad delivery status sync failed (tenant {tenant_id}): {e}")
    if backfill_from:
        try:
            set_ads_setting(db, tenant_id, "meta_ads_backfilled_from", backfill_from)
        except Exception as e:
            logger.warning(f"backfill marker write failed (tenant {tenant_id}): {e}")
    _record_sync_metadata(db, tenant_id, account, written)
    logger.info(f"Ads insights sync: tenant {tenant_id} wrote {written} daily rows")
    return written


def sync_tenant_ad_insights_verbose(db, tenant_id: str, *, date_preset: str = "last_30d") -> dict:
    """Manual-trigger variant for the 'Sync now' button: same pipeline, including
    today's live delivery, as
    sync_tenant_ad_insights (messaging ad sets, eligible ads
    only), but returns a diagnostic result (credential
    status, fetch errors, per-row write errors) instead of swallowing
    everything into a background-job log line.
    """
    creds = _get_ads_credentials(db, tenant_id)
    if not creds:
        return {
            "ok": False,
            "error": "No Ads Account ID / Ads System-User Token configured for this tenant.",
            "rows_fetched": 0,
            "whatsapp_rows": 0,
            "skipped_non_whatsapp": 0,
            "account_id": None,
            "written": 0,
        }
    token, account = creds
    since, backfill_from = _sync_window(db, tenant_id)
    try:
        rows = _fetch_sync_insights(token, account, date_preset, backfill_from=backfill_from)
        adsets = _fetch_adsets(token, account)
    except Exception as e:
        return {
            "ok": False,
            "error": f"Meta API request failed: {e}",
            "rows_fetched": 0,
            "whatsapp_rows": 0,
            "skipped_non_whatsapp": 0,
            "account_id": account,
            "written": 0,
        }
    ads = _fetch_ads_best_effort(token, account, tenant_id)
    try:
        eligible = refresh_ad_registry(db, tenant_id, account, ads, adsets)
    except Exception as e:
        return {
            "ok": False,
            "error": f"Ad registry update failed: {e}",
            "rows_fetched": len(rows),
            "whatsapp_rows": 0,
            "skipped_non_whatsapp": 0,
            "account_id": account,
            "written": 0,
            "backfilled_from": None,
        }
    selected, adset_by_id = _select_rows(rows, adsets, eligible, since)

    written = 0
    row_errors: list[str] = []
    for row in selected:
        try:
            creative_id = upsert_creative_from_insight(
                db,
                tenant_id,
                row,
                account=account,
                adset_meta=adset_by_id.get(str(row.get("adset_id"))),
                token=token,
            )
            if not creative_id:
                row_errors.append(f"ad_id={row.get('ad_id')}: no ad_id in Meta response")
                continue
            _write_insight_row(db, tenant_id, creative_id, row, account=account)
            written += 1
        except Exception as e:
            row_errors.append(f"ad_id={row.get('ad_id')}: {e}")

    if backfill_from and not row_errors:
        try:
            set_ads_setting(db, tenant_id, "meta_ads_backfilled_from", backfill_from)
        except Exception as e:
            logger.warning(f"backfill marker write failed (tenant {tenant_id}): {e}")

    # Campaign metadata is a best-effort enrichment — a failure here must NOT
    # flip the sync's ok status, since the insight rows (the primary data) may
    # have written fine. Log only, don't append to row_errors.
    try:
        sync_campaign_meta(
            db,
            tenant_id,
            token,
            account,
            campaign_ids={str(r.get("campaign_id")) for r in selected if r.get("campaign_id")},
        )
    except Exception as e:
        logger.warning(f"campaign meta sync failed (tenant {tenant_id}): {e}")
    delivery = {"updated": 0, "marked_deleted": 0, "reconciled": False}
    try:
        delivery = sync_ad_delivery_status(db, tenant_id, token, account, ads=ads)
    except Exception as e:
        logger.warning(f"ad delivery status sync failed (tenant {tenant_id}): {e}")
    _record_sync_metadata(db, tenant_id, account, written)

    return {
        "ok": not row_errors,
        "delivery_status_updated": delivery["updated"],
        "marked_deleted": delivery["marked_deleted"],
        "error": "; ".join(row_errors[:3]) if row_errors else None,
        "rows_fetched": len(rows),
        "whatsapp_rows": len(selected),
        "skipped_non_whatsapp": len(rows) - len(selected),
        "account_id": account,
        "written": written,
        "backfilled_from": backfill_from,
    }


def sync_all_tenants_ad_insights() -> None:
    """Scheduler entrypoint: sync every tenant that has ads credentials set."""
    db = get_supabase()
    try:
        rows = (
            db.table("app_settings").select("tenant_id")
            .eq("key", "meta_ads_account_id").execute()
        )
        tenant_ids = sorted({r["tenant_id"] for r in (rows.data or []) if r.get("tenant_id")})
    except Exception as e:
        logger.error(f"Ads insights sync: tenant enumeration failed: {e}")
        return
    for tid in tenant_ids:
        try:
            sync_tenant_ad_insights(db, tid)
        except Exception as e:
            logger.warning(f"Ads insights sync failed for tenant {tid}: {e}")
