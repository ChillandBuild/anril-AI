import csv
import io
import json
import logging
from datetime import date, datetime, timezone, timedelta
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from app.config import settings
from app.db.supabase import get_supabase
from app.services.actor import actor_name, sender_fields
from app.services.call_evaluation import strip_evaluation
from app.services.call_transcript import mask_transcripts
from app.dependencies.tenant import get_tenant_id, get_tenant_and_role, get_owner_tenant_id, require_permission
from app.models.schemas import Lead, LeadUpdate, LeadWithMessages, Message, PaginatedResponse
from app.services.ai_reply import (
    send_whatsapp, send_instagram, send_facebook, get_last_send_error,
    _call_context_block, _fetch_conversation_summary,
)
from app.services.growth import record_stage_event, sync_follow_up_jobs
from app.services.assignment import get_telecalling_config, record_assignment_event
from app.services.call_teams import assert_can_move_lead, assign_scope
from app.services.segmentation import new_lead_score_and_segment
from app.services.share_product import ShareProductError, share_product
from app.services import group_rules, scheduled_templates
from app.services.call_details_share import ShareError, _whatsapp_ready, compose_templates, prepare_template, send_approved_template

logger = logging.getLogger(__name__)

# PostgREST's `or=(...)` filter is a string mini-language: commas separate the
# branches, dots separate column/operator/value, and `*` is the ilike wildcard.
# A raw search term carrying any of those would rewrite the filter rather than
# be matched by it, so only characters a real name or phone number contains are
# kept. Everything else is dropped rather than escaped — there is no escape
# syntax to rely on here.
_SEARCH_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 +-_&'@")


def _sanitize_search(term: str | None) -> str | None:
    """Reduce a user search term to something safe to inline in an or_ filter."""
    if not term:
        return None
    cleaned = "".join(c for c in term.strip() if c in _SEARCH_ALLOWED).strip()
    return cleaned or None


require_leads_view = require_permission("leads.view")
require_leads_manage = require_permission("leads.manage")
require_conversations_reply = require_permission("conversations.reply")
router = APIRouter()


from app.services.gemini_client import gemini_chat_completion_json


class PreCallBriefResponse(BaseModel):
    brief: str
    opener: str


class ConvertPayload(BaseModel):
    notes: str | None = None


class AiToggle(BaseModel):
    enabled: bool


class HumanMessage(BaseModel):
    content: str


class AssignPayload(BaseModel):
    caller_id: str | None = None


class BulkAssignPayload(BaseModel):
    lead_ids: list[UUID]
    caller_id: str | None = None


class LeadFilters(BaseModel):
    """The Segments table's filters. The table and the broadcast share them, so a
    broadcast reaches exactly the leads the table shows."""
    segment: str | None = Field(None, pattern="^[ABCD]$")
    assigned_to: str | None = None
    source_filter: str | None = None
    broadcast_id: str | None = None
    ad_campaign_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    search: str | None = Field(None, max_length=100)
    reply_window: str | None = Field(None, pattern="^(open|closed)$")
    # Customers: True = people who have bought, False = people who have not.
    buyer: bool | None = None
    # A Customers group (customer_groups.id): only its members.
    group_id: str | None = None
    # The clickable KPI cards: "repeat" = 2+ won deals, "quiet" = bought before but not
    # in the last BUYER_QUIET_DAYS days.
    bought: str | None = Field(None, pattern="^(repeat|quiet)$")
    # "leads" = people who have never bought (no paid mark, no won deal). The mirror of buyer=true.
    only: str | None = Field(None, pattern="^leads$")
    # Where the person first came from: qr, google_ads, meta_ad, instant_form, website, inbound,
    # organic, broadcast, or a plain source (upload, manual, whatsapp, ...). See _CAME_FROM_SOURCES.
    came_from: str | None = Field(None, max_length=30)
    # A tag (customers > tags), matched ignoring upper / lower case.
    tag: str | None = Field(None, max_length=30)


class CustomBroadcastRequest(LeadFilters):
    message: str


# Plain lead sources a "Came from" choice can name directly (the rest are worked out from ads / QR / broadcasts).
_CAME_FROM_SOURCES = ('whatsapp', 'instagram', 'facebook', 'telegram', 'indiamart', 'justdial', 'upload', 'csv', 'manual',
                      'website', 'api', 'store')
_CAME_FROM_SPECIAL = ('qr', 'google_ads', 'meta_ad', 'instant_form', 'inbound', 'organic', 'broadcast')

INBOUND_SOURCES = ('whatsapp', 'instagram', 'facebook', 'telegram', 'indiamart', 'justdial', 'meta_form', 'qr')

# Reads of whole tables go through PostgREST, which caps one response at 1000 rows.
_PAGE = 1000
# How many ids go into one `in.(...)` filter or lookup.
_IN_CHUNK = 200
BUYER_QUIET_DAYS = 90
_MIN_DT = datetime.min.replace(tzinfo=timezone.utc)


def _fetch_all(build, order_by: tuple[str, ...] = ("id",)) -> list[dict]:
    """Every row of a query, paged through the 1000-row cap. `build` returns a fresh query
    each time; the order must be unique per row so pages cannot overlap."""
    rows: list[dict] = []
    while True:
        q = build()
        for column in order_by:
            q = q.order(column)
        page = q.range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows


def _in_scopes(ids: list[str] | None) -> list[list[str] | None]:
    """[None] for "the whole tenant", else the ids in chunks for `in.(...)` filters."""
    if ids is None:
        return [None]
    return [ids[i:i + _IN_CHUNK] for i in range(0, len(ids), _IN_CHUNK)]


def _parse_ts(raw) -> datetime | None:
    """A timestamp from PostgREST (or a datetime) as an aware datetime, None when unknown."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _group_kind_and_rule(db, tenant_id: str, group_id: str) -> dict | None:
    """{"kind", "rule"} of this tenant's group, None when it is not theirs (matches nobody)."""
    rows = (db.table("customer_groups").select("kind,rule").eq("id", group_id)
            .eq("tenant_id", tenant_id).limit(1).execute()).data or []
    if not rows:
        return None
    kind = rows[0].get("kind") or "picked"
    return {"kind": kind, "rule": group_rules.parse_rule(rows[0].get("rule")) if kind == "rule" else None}


def _memo_get(memo: dict, key, compute):
    """One lookup per request: a paged list re-runs the query builder for each page, and
    the lookups behind it (buyers, groups, search matches) must not repeat per page."""
    if key not in memo:
        memo[key] = compute()
    return memo[key]


def _buyer_facts(db, tenant_id: str, lead_ids: list[str] | None = None) -> dict:
    """Who has bought, from the won deals and the converted / booked marks.

    BUYER = converted_at or booked_at set, or at least one won deal.
    Returns {"buyers": set of lead ids,
             "per_lead": {lead_id: {won_count, spent_paise, last_purchase_at}}}.
    last_purchase_at = latest of the won deals' won_at, converted_at, booked_at (aware datetime).
    lead_ids limits the lookup to those leads; None reads the whole tenant."""
    per_lead: dict[str, dict] = {}
    milestone_buyers: set[str] = set()

    def entry(lead_id: str) -> dict:
        return per_lead.setdefault(lead_id, {"won_count": 0, "spent_paise": 0, "last_purchase_at": None})

    def note_time(lead_id: str, when: datetime | None) -> None:
        if when is not None:
            current = entry(lead_id)["last_purchase_at"]
            if current is None or when > current:
                entry(lead_id)["last_purchase_at"] = when

    for scope in _in_scopes(lead_ids):
        def won_deals(scope=scope):
            q = db.table("deals").select("id,lead_id,total_paise,won_at").eq("tenant_id", tenant_id).eq("stage", "won")
            return q.in_("lead_id", scope) if scope is not None else q

        for deal in _fetch_all(won_deals):
            lead_id = deal.get("lead_id")
            if not lead_id:
                continue
            fact = entry(lead_id)
            fact["won_count"] += 1
            fact["spent_paise"] += int(deal.get("total_paise") or 0)
            note_time(lead_id, _parse_ts(deal.get("won_at")))

        for column in ("converted_at", "booked_at"):
            def marked(scope=scope, column=column):
                q = db.table("leads").select(f"id,{column}").eq("tenant_id", tenant_id).not_.is_(column, "null")
                return q.in_("id", scope) if scope is not None else q

            for lead in _fetch_all(marked):
                milestone_buyers.add(lead["id"])
                note_time(lead["id"], _parse_ts(lead.get(column)))

    buyers = milestone_buyers | {lid for lid, fact in per_lead.items() if fact["won_count"] > 0}
    return {"buyers": buyers, "per_lead": per_lead}


def _broadcast_history(db, tenant_id: str) -> list[dict]:
    """The broadcast_history list kept in app_settings (see get_broadcast_history)."""
    try:
        row = (db.table("app_settings").select("value").eq("tenant_id", tenant_id)
               .eq("key", "broadcast_history").maybe_single().execute())
        raw = row.data.get("value") if row and row.data else None
        history = json.loads(raw) if raw else []
        return [h for h in history if isinstance(h, dict)] if isinstance(history, list) else []
    except Exception:
        return []


def _broadcast_names(db, tenant_id: str, broadcast_ids: set[str]) -> dict[str, str]:
    """broadcast id -> template name, from broadcast_history first, scheduled_broadcasts after."""
    names: dict[str, str] = {}
    for h in _broadcast_history(db, tenant_id):
        bid = str(h.get("broadcast_id") or "")
        if bid in broadcast_ids and h.get("template_name"):
            names[bid] = h["template_name"]
    missing = [b for b in broadcast_ids if b not in names]
    for scope in _in_scopes(missing):
        for r in _fetch_all(lambda scope=scope: db.table("scheduled_broadcasts").select("id,template_name")
                            .eq("tenant_id", tenant_id).in_("id", scope)):
            if r.get("template_name") and str(r["id"]) not in names:
                names[str(r["id"])] = r["template_name"]
    return names


def _groups_by_lead(db, tenant_id: str, lead_ids: list[str] | None = None) -> dict[str, list[dict]]:
    """lead id -> [{id, name}] for the customer groups it is in."""
    members: list[dict] = []
    for scope in _in_scopes(lead_ids):
        def rows(scope=scope):
            q = db.table("customer_group_members").select("group_id,lead_id").eq("tenant_id", tenant_id)
            return q.in_("lead_id", scope) if scope is not None else q

        members.extend(_fetch_all(rows, order_by=("group_id", "lead_id")))
    group_ids = sorted({str(m["group_id"]) for m in members})
    names: dict[str, str] = {}
    for scope in _in_scopes(group_ids):
        for g in _fetch_all(lambda scope=scope: db.table("customer_groups").select("id,name")
                            .eq("tenant_id", tenant_id).in_("id", scope)):
            names[str(g["id"])] = g["name"]
    out: dict[str, list[dict]] = {}
    for m in members:
        gid = str(m["group_id"])
        if gid in names:
            out.setdefault(str(m["lead_id"]), []).append({"id": gid, "name": names[gid]})
    return out



def _open_broadcast_scores(db, tenant_id: str, lead_ids: list[str]) -> dict[str, dict]:
    """lead id -> {broadcast_id, broadcast_name, segment} from the lead's latest broadcast
    score row that is still open (finalized_at null)."""
    rows: list[dict] = []
    for scope in _in_scopes(lead_ids):
        rows.extend(_fetch_all(lambda scope=scope: db.table("broadcast_lead_scores")
                               .select("id,lead_id,broadcast_id,segment,broadcast_sent_at")
                               .eq("tenant_id", tenant_id).is_("finalized_at", "null").in_("lead_id", scope)))
    latest: dict[str, dict] = {}
    for r in rows:
        lead_id = r.get("lead_id")
        if not lead_id:
            continue
        sent = _parse_ts(r.get("broadcast_sent_at")) or _MIN_DT
        current = latest.get(lead_id)
        if current is None or sent > (_parse_ts(current.get("broadcast_sent_at")) or _MIN_DT):
            latest[lead_id] = r
    names = _broadcast_names(db, tenant_id, {str(r["broadcast_id"]) for r in latest.values() if r.get("broadcast_id")})
    out = {}
    for lead_id, r in latest.items():
        bid = str(r["broadcast_id"]) if r.get("broadcast_id") else None
        out[lead_id] = {"broadcast_id": bid, "broadcast_name": names.get(bid) if bid else None,
                        "segment": r.get("segment")}
    return out


def _latest_iso(*candidates) -> str | None:
    """The latest of several timestamps, as the string it was given as."""
    best: tuple[datetime, str] | None = None
    for raw in candidates:
        dt = _parse_ts(raw)
        if dt is not None and (best is None or dt > best[0]):
            best = (dt, raw if isinstance(raw, str) else dt.isoformat())
    return best[1] if best else None


def _campaign_ids_matching(db, tenant_id: str, term: str) -> list[str]:
    """Ad campaigns whose name contains the term, plus their placeholder rows."""
    from app.services.ad_performance import campaign_ids_with_placeholders

    campaigns = _fetch_all(lambda: db.table("ad_campaigns").select("id").eq("tenant_id", tenant_id)
                           .ilike("campaign_name", f"%{term}%"))
    ids: list[str] = []
    for c in campaigns:
        ids.extend(campaign_ids_with_placeholders(db, tenant_id, str(c["id"])))
    return list(dict.fromkeys(ids))



def _google_campaign_ids(db, tenant_id: str) -> list[str]:
    """ids of this tenant's Google Ads campaigns (the other ad campaigns are Meta's)."""
    rows = _fetch_all(lambda: db.table("ad_campaigns").select("id").eq("tenant_id", tenant_id).eq("platform", "google"))
    return [str(r["id"]) for r in rows]


def _tag_spellings(db, tenant_id: str, tag: str) -> list[str]:
    """Every spelling of this tag in use ("VIP", "vip"), so the match ignores case. [] when none
    (or the tags table is not there yet): then nobody matches."""
    from app.services.lead_tags import tag_spellings

    return tag_spellings(db, tenant_id, tag)


def _apply_came_from(db, tenant_id: str, query, came_from: str, memo: dict):
    """Narrow `query` to one "Came from" choice, or None when nobody can match. Raises 400 for an unknown choice.

    qr            scanned a QR code (leads.qr_link_id, or source qr)
    google_ads    arrived through a Google Ads campaign
    meta_ad       arrived through a Meta (Facebook / Instagram) ad
    instant_form  filled a Meta instant form
    inbound / organic   the same two choices the Segments table already has
    broadcast     was sent at least one broadcast
    anything else a plain lead source (upload, manual, whatsapp, website, ...)
    """
    if came_from == "qr":
        return query.or_("qr_link_id.not.is.null,source.eq.qr")
    if came_from in ("google_ads", "meta_ad"):
        google = _memo_get(memo, ("google-campaigns",), lambda: _google_campaign_ids(db, tenant_id))
        if came_from == "google_ads":
            if not google:
                return None
            return query.in_("ad_campaign_id", google)
        query = query.not_.is_("ad_campaign_id", "null")
        return query.not_.in_("ad_campaign_id", google) if google else query
    if came_from == "instant_form":
        return query.eq("source", "meta_form")
    if came_from == "inbound":
        return query.in_("source", list(INBOUND_SOURCES))
    if came_from == "organic":
        return query.in_("source", list(INBOUND_SOURCES)).is_("ad_campaign_id", "null").neq("source", "meta_form")
    if came_from == "broadcast":
        return query  # the broadcast_recipients embed is added by the caller
    if came_from in _CAME_FROM_SOURCES:
        return query.eq("source", came_from)
    raise HTTPException(status_code=400, detail="Pick one of the 'came from' choices on the list")


def _filtered_leads_query(db, ctx: dict, f: LeadFilters, columns: str = "*", count: str | None = None,
                          memo: dict | None = None, opted_out_only: bool = False):
    """Leads matching the Segments filters, or None when nothing can match.

    memo: pass one dict per request when the same filters are run again (paging); it keeps
    the lookups from being repeated. opted_out_only: the said-stop people instead of the
    rest (same filters otherwise)."""
    tenant_id = ctx["tenant_id"]
    memo = {} if memo is None else memo
    # NULL-safe "IS NOT TRUE": a bare .neq("col", True) compiles to `col <> true`,
    # which SQL evaluates to NULL (row excluded) whenever the column is NULL rather
    # than explicitly false. Both columns were added via manual ALTER outside the
    # migration set with no guaranteed NOT NULL DEFAULT false, so untouched leads
    # (e.g. freshly assigned, never opted out / never delivery-failed) can be NULL
    # here and were silently vanishing from this endpoint's callers (Segments page,
    # telecaller Dialer queue) while still showing up via Conversations' RPC path,
    # which never applied this filter in the first place.
    # Group and broadcast filters are answered by the database with an empty inner embed
    # (`table!inner()` joins without adding a key to the rows), never by shipping the
    # member ids back in the URL: PostgREST refuses `id=in.(...)` at ~1000 uuids.
    embeds: list[str] = []
    group_id = None
    if f.group_id:
        try:
            group_id = str(UUID(f.group_id))
        except ValueError:
            return None
        group = _memo_get(memo, ("group", group_id), lambda: _group_kind_and_rule(db, tenant_id, group_id))
        if group is None:
            return None
        if group["kind"] == "rule":
            # A group that fills itself is its saved filters (services/group_rules.py), applied
            # on top of the page's own filters; nothing is stored per member.
            if not group["rule"]:
                return None
            f = group_rules.apply_rule(f, group["rule"])
            if f is None:
                return None
            group_id = None
        else:
            embeds.append("customer_group_members!inner()")
    broadcast_id = f.broadcast_id if f.source_filter == "broadcast" and f.broadcast_id else None
    if broadcast_id:
        embeds.append("broadcast_recipients!inner()")
    if f.came_from and f.came_from not in _CAME_FROM_SPECIAL and f.came_from not in _CAME_FROM_SOURCES:
        raise HTTPException(status_code=400, detail="Pick one of the 'came from' choices on the list")
    any_broadcast = f.came_from == "broadcast" and not broadcast_id
    if any_broadcast:
        embeds.append("broadcast_recipients!inner()")
    tag_spellings = None
    if f.tag and f.tag.strip():
        tag_spellings = _memo_get(memo, ("tag", f.tag.strip().lower()), lambda: _tag_spellings(db, tenant_id, f.tag))
        if not tag_spellings:
            return None
        embeds.append("lead_tags!inner()")
    select_cols = ",".join([columns, *embeds]) if embeds else columns
    query = (db.table("leads").select(select_cols, count=count)
             .eq("tenant_id", tenant_id)
             .is_("deleted_at", "null"))
    if group_id:
        # Members carry tenant_id, so another tenant's group matches nobody.
        query = (query.eq("customer_group_members.group_id", group_id)
                 .eq("customer_group_members.tenant_id", tenant_id))
    if broadcast_id:
        query = (query.eq("broadcast_recipients.broadcast_id", broadcast_id)
                 .eq("broadcast_recipients.tenant_id", tenant_id))
    if any_broadcast:
        query = query.eq("broadcast_recipients.tenant_id", tenant_id)
    if tag_spellings:
        query = query.eq("lead_tags.tenant_id", tenant_id)
        query = (query.eq("lead_tags.tag", tag_spellings[0]) if len(tag_spellings) == 1
                 else query.in_("lead_tags.tag", tag_spellings))
    if opted_out_only:
        query = query.eq("opted_out", True)
    else:
        query = query.or_("opted_out.is.null,opted_out.eq.false")
    query = query.or_("whatsapp_undeliverable.is.null,whatsapp_undeliverable.eq.false")
    if f.date_from:
        try:
            date.fromisoformat(f.date_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from must be YYYY-MM-DD")
        query = query.gte("created_at", f.date_from)
    if f.date_to:
        try:
            date_to_parsed = date.fromisoformat(f.date_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to must be YYYY-MM-DD")
        query = query.lt("created_at", (date_to_parsed + timedelta(days=1)).isoformat())
    if f.segment:
        query = query.eq("segment", f.segment)
    # Name or phone, substring, case-insensitive. Phones are stored with the
    # country code (+916369781582), so a term typed without it still has to
    # match — hence a contains match on both sides rather than a prefix one.
    search_term = _sanitize_search(f.search)
    if search_term:
        # One OR across everything a person can be found by: name, phone, the ad they came
        # from, the ad campaign, and the broadcasts they were sent (sent_broadcast_names is a
        # computed field, migration 279, so this stays one short request at any size).
        clauses = [f"name.ilike.*{search_term}*", f"phone.ilike.*{search_term}*", f"ad_name.ilike.*{search_term}*",
                   f"sent_broadcast_names.ilike.*{search_term}*"]
        campaign_ids = _memo_get(memo, ("search-campaigns", search_term),
                                 lambda: _campaign_ids_matching(db, tenant_id, search_term))
        if campaign_ids:
            clauses.append(f"ad_campaign_id.in.({','.join(campaign_ids)})")
        query = query.or_(",".join(clauses))
    if ctx.get("role") == "caller" and ctx.get("caller_id"):
        query = query.eq("assigned_to", ctx["caller_id"])
    elif f.assigned_to:
        if f.assigned_to == "unassigned":
            query = query.is_("assigned_to", "null")
        elif f.assigned_to == "ai_agent":
            # Nobody holds the lead and the AI has not been switched off for it.
            query = query.is_("assigned_to", "null").or_("ai_enabled.is.null,ai_enabled.eq.true")
        else:
            query = query.eq("assigned_to", f.assigned_to)

    if f.buyer is not None:
        # leads.is_buyer is kept by triggers (migration 279): paid, booked or a won deal.
        query = query.eq("is_buyer", f.buyer)
    # Computed fields won_deal_count / last_purchase_at (migration 280), so the same rule
    # as the summary cards runs inside the database.
    if f.bought == "repeat":
        query = query.gte("won_deal_count", 2)
    elif f.bought == "quiet":
        quiet_since = (datetime.now(timezone.utc) - timedelta(days=BUYER_QUIET_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = query.eq("is_buyer", True).lt("last_purchase_at", quiet_since)
    if f.only == "leads":
        # Never bought: not marked paid and no won deal (won_deal_count is the computed field above).
        query = query.is_("converted_at", "null").eq("won_deal_count", 0)
    if f.came_from:
        query = _apply_came_from(db, tenant_id, query, f.came_from, memo)
        if query is None:
            return None

    # Medium / campaign / broadcast filters
    if f.source_filter == "inbound":
        query = query.in_("source", list(INBOUND_SOURCES))
    elif f.source_filter == "organic":
        query = query.in_("source", list(INBOUND_SOURCES)).is_("ad_campaign_id", "null").neq("source", "meta_form")
    elif f.source_filter == "meta_ads":
        query = query.in_("source", list(INBOUND_SOURCES)).not_.is_("ad_campaign_id", "null")
        if f.ad_campaign_id:
            # Include leads the webhook filed under a placeholder for one of this
            # campaign's ads before the ad synced (see campaign_ids_with_placeholders).
            from app.services.ad_performance import campaign_ids_with_placeholders

            query = query.in_("ad_campaign_id", campaign_ids_with_placeholders(db, tenant_id, f.ad_campaign_id))

    if f.reply_window:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if f.reply_window == "open":
            query = query.gte("last_inbound_at", cutoff_iso)
        else:
            query = query.or_(f"last_inbound_at.is.null,last_inbound_at.lt.{cutoff_iso}")
    return query


def _lead_filters(
    segment: str | None = Query(None, pattern="^[ABCD]$"),
    assigned_to: str | None = Query(None),
    source_filter: str | None = Query(None),
    broadcast_id: str | None = Query(None),
    ad_campaign_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    search: str | None = Query(None, max_length=100),
    reply_window: str | None = Query(None, pattern="^(open|closed)$"),
    buyer: bool | None = Query(None),
    group_id: str | None = Query(None, max_length=64),
    bought: str | None = Query(None, pattern="^(repeat|quiet)$"),
    only: str | None = Query(None, pattern="^leads$"),
    came_from: str | None = Query(None, max_length=30),
    tag: str | None = Query(None, max_length=30),
) -> LeadFilters:
    """The Segments filter query parameters, shared by the list, summary and export routes."""
    return LeadFilters(
        segment=segment, assigned_to=assigned_to, source_filter=source_filter, broadcast_id=broadcast_id,
        ad_campaign_id=ad_campaign_id, date_from=date_from, date_to=date_to, search=search,
        reply_window=reply_window, buyer=buyer, group_id=group_id, bought=bought,
        only=only, came_from=came_from, tag=tag,
    )


def _customer_fields(db, tenant_id: str, leads_data: list[dict]) -> None:
    """Adds is_buyer, spent_paise, last_activity_at, groups and broadcast_score to each lead.
    Batched per page: no query per lead. Expects `last_inbound_at` already set."""
    lead_ids = [l["id"] for l in leads_data]
    facts = _buyer_facts(db, tenant_id, lead_ids=lead_ids)
    groups = _groups_by_lead(db, tenant_id, lead_ids=lead_ids)
    scores = _open_broadcast_scores(db, tenant_id, lead_ids)
    from app.services.lead_tags import tags_by_lead

    tags = tags_by_lead(db, tenant_id, lead_ids)
    for lead in leads_data:
        lead_id = lead["id"]
        fact = facts["per_lead"].get(lead_id) or {}
        last_purchase = fact.get("last_purchase_at")
        lead["is_buyer"] = lead_id in facts["buyers"]
        lead["spent_paise"] = int(fact.get("spent_paise") or 0)
        lead["last_activity_at"] = _latest_iso(lead.get("last_inbound_at"), last_purchase) or lead.get("created_at")
        lead["groups"] = groups.get(lead_id, [])
        lead["broadcast_score"] = scores.get(lead_id)
        lead["tags"] = tags.get(lead_id, [])


@router.get("/", response_model=PaginatedResponse)
async def list_leads(
    sort: str | None = Query(None, pattern="^(newest|oldest|urgent)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    filters: LeadFilters = Depends(_lead_filters),
    ctx: dict = Depends(require_leads_view),
):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    offset = (page - 1) * limit
    source_filter, broadcast_id = filters.source_filter, filters.broadcast_id
    query = _filtered_leads_query(db, ctx, filters, count="exact")
    if query is None:
        return PaginatedResponse(data=[], total=0, page=page, limit=limit)

    # Apply sorting
    if sort == "newest":
        result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    elif sort == "oldest":
        result = query.order("created_at", desc=False).range(offset, offset + limit - 1).execute()
    elif sort == "urgent":
        result = query.order("last_inbound_at", desc=False, nullsfirst=False).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    else:
        result = query.order("segment").order("last_inbound_at", desc=True, nullsfirst=False).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    leads_data = result.data or []

    # Enrichment
    lead_ids = [l["id"] for l in leads_data]
    if lead_ids:
        # 1. Fetch latest inbound message time for 24h window
        inbound_msgs = (
            db.table("messages")
            .select("lead_id,created_at")
            .in_("lead_id", lead_ids)
            .eq("direction", "inbound")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        last_inbound_by_lead = {}
        for m in (inbound_msgs.data or []):
            lid = m["lead_id"]
            msg_time = m["created_at"]
            if lid not in last_inbound_by_lead or msg_time > last_inbound_by_lead[lid]:
                last_inbound_by_lead[lid] = msg_time

        # 2. Fetch broadcast sent time if filtered by broadcast
        br_time_by_lead = {}
        if source_filter == "broadcast" and broadcast_id:
            br_times = (
                db.table("broadcast_recipients")
                .select("lead_id,created_at")
                .eq("broadcast_id", broadcast_id)
                .in_("lead_id", lead_ids)
                .eq("tenant_id", tenant_id)
                .execute()
            )
            br_time_by_lead = {r["lead_id"]: r["created_at"] for r in (br_times.data or []) if r.get("lead_id")}

        for lead in leads_data:
            lead["last_inbound_at"] = last_inbound_by_lead.get(lead["id"])
            if lead["id"] in br_time_by_lead:
                lead["broadcast_sent_at"] = br_time_by_lead[lead["id"]]

        _customer_fields(db, tenant_id, leads_data)
        _add_came_from(db, tenant_id, leads_data)
        _hide_numbers_for_caller(db, tenant_id, ctx, leads_data)

    return PaginatedResponse(
        data=leads_data,
        total=result.count or 0,
        page=page,
        limit=limit,
    )


def _hide_numbers_for_caller(db, tenant_id: str, ctx: dict, leads: list[dict]) -> None:
    """Call IQ (v9.2 #21): a cloud-calling telecaller sees 98•••••210 when the business hides numbers.
    Calls are placed by lead id, so dialing still works. Any problem leaves the numbers as they were."""
    if ctx.get("role") != "caller" or not leads:
        return
    try:
        from app.services.call_rules import hides_numbers, mask_phone
        if not hides_numbers(db, tenant_id, ctx):
            return
        for lead in leads:
            if lead.get("phone"):
                lead["phone"] = mask_phone(lead["phone"])
                lead["phone_hidden"] = True
    except Exception as e:
        logger.warning(f"leads: could not apply hidden numbers for {tenant_id}: {e}")


def _add_came_from(db, tenant_id: str, leads: list[dict]) -> None:
    """Set came_from ("from Google Ads · summer_sale", "from Meta ad · …", "from QR · …") for the chat header."""
    try:
        from app.services.google_ads_report import came_from_labels
        labels = came_from_labels(db, tenant_id, leads)
    except Exception as e:  # a label is never worth failing the list
        logger.warning("came_from lookup failed: %s", e)
        return
    for lead in leads:
        label = labels.get(str(lead.get("id")))
        if label:
            lead["came_from"] = label


BROADCAST_PAGE = 1000  # PostgREST caps one response at 1000 rows


def _broadcast_targets(db, ctx: dict, f: LeadFilters) -> tuple[int, list[dict], set[str]]:
    """(leads the table shows, those with an opt-in record, ids inside the 24-hour window)."""
    tenant_id = ctx["tenant_id"]
    query = _filtered_leads_query(db, ctx, f, columns="id,phone,source,ig_user_id,tg_user_id,fb_user_id,opt_in_source,blocked_at")
    if query is None:
        return 0, [], set()
    rows: list[dict] = []
    while True:
        page = (query.order("created_at").order("id")
                .range(len(rows), len(rows) + BROADCAST_PAGE - 1).execute().data or [])
        rows.extend(page)
        if len(page) < BROADCAST_PAGE:
            break
    # Hard invariant: bulk-send rejects leads with null opt_in_source
    # Full block: a blocked person is never a broadcast target, and is not counted as a match
    # or as "no opt-in" either, so the preview numbers only describe people who can be messaged.
    rows = [r for r in rows if not r.get("blocked_at")]
    targets = [r for r in rows if r.get("opt_in_source")]

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    eligible: set[str] = set()
    ids = [t["id"] for t in targets]
    for i in range(0, len(ids), 200):
        recent = (
            db.table("messages").select("lead_id")
            .eq("direction", "inbound").eq("tenant_id", tenant_id)
            .gte("created_at", cutoff).in_("lead_id", ids[i:i + 200]).execute()
        )
        eligible.update(r["lead_id"] for r in (recent.data or []))
    return len(rows), targets, eligible


def _reachable(target: dict, eligible: set[str]) -> bool:
    # Telegram has no 24h window
    return target.get("source") == "telegram" or target["id"] in eligible


@router.post("/broadcast/preview")
def broadcast_preview(body: LeadFilters, ctx: dict = Depends(require_leads_manage)):
    """How many leads a broadcast with these filters would reach, before sending."""
    matching, targets, eligible = _broadcast_targets(get_supabase(), ctx, body)
    reachable = sum(1 for t in targets if _reachable(t, eligible))
    return {
        "matching": matching,
        "reachable": reachable,
        "outside_window": len(targets) - reachable,
        "no_opt_in": matching - len(targets),
    }


@router.post("/broadcast")
async def broadcast_custom_message(
    body: CustomBroadcastRequest,
    ctx: dict = Depends(require_leads_manage),
):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty")

    _, targets, eligible_ids = await run_in_threadpool(_broadcast_targets, db, ctx, body)
    if not targets:
        return {"sent": 0, "failed": 0, "skipped_window": 0, "total": 0}

    sent = 0
    failed = 0
    skipped_window = 0

    for t in targets:
        lead_id = t["id"]
        source = t.get("source", "whatsapp")

        if not _reachable(t, eligible_ids):
            skipped_window += 1
            continue

        channel = (
            "instagram" if source == "instagram"
            else "telegram" if source == "telegram"
            else "facebook" if source == "facebook"
            else "whatsapp"
        )

        sid = None
        try:
            if channel == "instagram":
                ig_id = t.get("ig_user_id")
                if ig_id:
                    sid = await send_instagram(ig_id, body.message, tenant_id=tenant_id)
            elif channel == "telegram":
                tg_id = t.get("tg_user_id")
                if tg_id:
                    from app.services.ai_reply import send_telegram
                    sid = await send_telegram(tg_id, body.message, tenant_id=tenant_id)
            elif channel == "facebook":
                fb_id = t.get("fb_user_id")
                if fb_id:
                    sid = await send_facebook(fb_id, body.message, tenant_id=tenant_id)
            else:
                phone = t.get("phone")
                if phone:
                    sid = await send_whatsapp(phone, body.message, tenant_id=tenant_id)
        except Exception as e:
            logger.error(f"Failed to send broadcast message to lead {lead_id} on {channel}: {e}")

        if sid:
            sent += 1
            sid_field = (
                "tg_message_id" if channel == "telegram"
                else "fb_message_id" if channel == "facebook"
                else "meta_message_id"
            )
            db.table("messages").insert({
                "lead_id": str(lead_id),
                "tenant_id": tenant_id,
                "direction": "outbound",
                "channel": channel,
                "content": body.message,
                "is_ai_generated": False,
                sid_field: sid,
            }).execute()
            db.table("leads").update({"needs_human_intervention": False}).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
        else:
            failed += 1

    return {
        "total": len(targets),
        "sent": sent,
        "failed": failed,
        "skipped_window": skipped_window,
    }


@router.patch("/{lead_id}/assign")
async def assign_lead(
    lead_id: str,
    payload: AssignPayload,
    ctx: dict = Depends(get_tenant_and_role),
):
    db = get_supabase()
    scope = assign_scope(db, ctx)  # owner: None (no limit); Team leader: their team; others: 403 "Owner only"
    
    # Fetch current lead info to check previous caller and other meta
    lead = db.table("leads").select("name, segment, score, assigned_to").eq("id", lead_id).eq("tenant_id", ctx["tenant_id"]).maybe_single().execute()
    if not lead.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    assert_can_move_lead(scope, lead.data.get("assigned_to"), payload.caller_id)
        
    prev_caller_id = lead.data.get("assigned_to")
    segment = lead.data.get("segment")
    score = lead.data.get("score")
    
    caller_name = None
    if payload.caller_id:
        caller = db.table("callers").select("name").eq("id", payload.caller_id).eq("tenant_id", ctx["tenant_id"]).maybe_single().execute()
        if caller.data:
            caller_name = caller.data.get("name")
            
    prev_caller_name = None
    if prev_caller_id:
        prev_caller = db.table("callers").select("name").eq("id", prev_caller_id).eq("tenant_id", ctx["tenant_id"]).maybe_single().execute()
        if prev_caller.data:
            prev_caller_name = prev_caller.data.get("name")

    assigned_at = datetime.now(timezone.utc).isoformat() if payload.caller_id else None
    db.table("leads").update({
        "assigned_to": payload.caller_id,
        "assigned_at": assigned_at
    }).eq("id", lead_id).eq("tenant_id", ctx["tenant_id"]).execute()
    
    if payload.caller_id:
        event_type = "reassigned" if prev_caller_id and str(prev_caller_id) != str(payload.caller_id) else "assigned"
        record_assignment_event(
            lead_id=lead_id,
            tenant_id=ctx["tenant_id"],
            segment=segment,
            caller_id=payload.caller_id,
            caller_name=caller_name,
            reason="manual_assign",
            method="admin",
            score=score,
            event_type=event_type,
            prev_caller_id=prev_caller_id,
            prev_caller_name=prev_caller_name,
            db=db
        )
        try:
            new_caller_uid = None
            new_caller_res = db.table("callers").select("user_id").eq("id", payload.caller_id).eq("tenant_id", ctx["tenant_id"]).maybe_single().execute()
            if new_caller_res.data:
                new_caller_uid = new_caller_res.data.get("user_id")

            prev_caller_uid = None
            if prev_caller_id:
                prev_caller_res = db.table("callers").select("user_id").eq("id", prev_caller_id).eq("tenant_id", ctx["tenant_id"]).maybe_single().execute()
                if prev_caller_res.data:
                    prev_caller_uid = prev_caller_res.data.get("user_id")

            from app.services.notify import notify_user
            lead_name = lead.data.get("name") or "Unknown Lead"
            
            if new_caller_uid:
                notify_user(
                    ctx["tenant_id"],
                    new_caller_uid,
                    "lead_assigned",
                    "New Lead Assigned" if event_type == "assigned" else "Lead Reassigned",
                    f"Lead '{lead_name}' was assigned to you by Admin." if event_type == "assigned" else f"Lead '{lead_name}' was reassigned to you by Admin.",
                    db=db,
                )
                
            if prev_caller_uid and prev_caller_uid != new_caller_uid:
                notify_user(
                    ctx["tenant_id"],
                    prev_caller_uid,
                    "lead_reassigned",
                    "Lead Reassigned",
                    f"Lead '{lead_name}' has been reassigned to another caller.",
                    db=db,
                )
        except Exception as notify_err:
            logger.warning(f"Failed to notify caller on manual assign: {notify_err}")

    try:
        from app.services.notify import clear_pool_notifications_for_lead
        clear_pool_notifications_for_lead(ctx["tenant_id"], lead_id, db=db)
    except Exception:
        pass
        
    return {"success": True}


class SendToCallingPayload(BaseModel):
    lead_ids: list[UUID] = Field(min_length=1, max_length=1000)


@router.post("/send-to-calling")
async def send_leads_to_calling(payload: SendToCallingPayload, ctx: dict = Depends(require_leads_manage)):
    """Customers > bulk "Send to calling": give the picked people to callers (Call IQ > Leads to call).
    Returns {added, already, said_stop, bought, closed, not_found, no_callers, added_ids}."""
    from app.services import customer_calling

    db = get_supabase()
    ids = [str(i) for i in payload.lead_ids]
    return await run_in_threadpool(
        customer_calling.send_to_calling, db, ctx["tenant_id"], ids, reason="customers_bulk")


@router.post("/bulk-assign")
async def bulk_assign(
    payload: BulkAssignPayload,
    ctx: dict = Depends(get_tenant_and_role),
):
    db = get_supabase()
    scope = assign_scope(db, ctx)  # owner: None (no limit); Team leader: their team; others: 403 "Owner only"
    if not payload.lead_ids:
        return {"success": True, "count": 0}
        
    tenant_id = ctx["tenant_id"]
    
    # Fetch all leads details to be assigned
    lead_ids_str = [str(lid) for lid in payload.lead_ids]
    leads = db.table("leads").select("id, segment, score, assigned_to").in_("id", lead_ids_str).eq("tenant_id", tenant_id).execute().data or []
    for l in leads:
        assert_can_move_lead(scope, l.get("assigned_to"), payload.caller_id)
    
    caller_name = None
    if payload.caller_id:
        caller = db.table("callers").select("name").eq("id", payload.caller_id).eq("tenant_id", tenant_id).maybe_single().execute()
        if caller.data:
            caller_name = caller.data.get("name")
            
    # Batch query caller names for prev_caller names to avoid N queries
    prev_caller_ids = list({l["assigned_to"] for l in leads if l.get("assigned_to")})
    prev_caller_names = {}
    if prev_caller_ids:
        callers = db.table("callers").select("id, name").in_("id", prev_caller_ids).eq("tenant_id", tenant_id).execute().data or []
        prev_caller_names = {c["id"]: c["name"] for c in callers}
        
    assigned_at = datetime.now(timezone.utc).isoformat() if payload.caller_id else None
    
    for lead in leads:
        lead_id = lead["id"]
        prev_caller_id = lead.get("assigned_to")
        segment = lead.get("segment")
        score = lead.get("score")
        
        db.table("leads").update({
            "assigned_to": payload.caller_id,
            "assigned_at": assigned_at
        }).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
        
        if payload.caller_id:
            event_type = "reassigned" if prev_caller_id and str(prev_caller_id) != str(payload.caller_id) else "assigned"
            record_assignment_event(
                lead_id=lead_id,
                tenant_id=tenant_id,
                segment=segment,
                caller_id=payload.caller_id,
                caller_name=caller_name,
                reason="bulk_assign",
                method="admin",
                score=score,
                event_type=event_type,
                prev_caller_id=prev_caller_id,
                prev_caller_name=prev_caller_names.get(prev_caller_id),
                db=db
            )
            try:
                from app.services.notify import clear_pool_notifications_for_lead
                clear_pool_notifications_for_lead(tenant_id, lead_id, db=db)
            except Exception:
                pass
            
    if payload.caller_id and leads:
        try:
            caller_res = db.table("callers").select("user_id").eq("id", payload.caller_id).eq("tenant_id", tenant_id).maybe_single().execute()
            if caller_res.data and caller_res.data.get("user_id"):
                from app.services.notify import notify_user
                count = len(leads)
                notify_user(
                    tenant_id,
                    caller_res.data["user_id"],
                    "lead_assigned",
                    "New Leads Assigned",
                    f"You have been assigned {count} leads by Admin." if count > 1 else f"You have been assigned a lead by Admin.",
                    db=db,
                    push_url="/dashboard/telecalling",
                )
        except Exception as e:
            logger.warning(f"Bulk assign notification failed: {e}")
            
    return {"success": True, "count": len(leads)}

def _matching_rows(db, ctx: dict, f: LeadFilters, columns: str, memo: dict, opted_out_only: bool = False) -> list[dict]:
    """Every lead row the filters match, paged. [] when nothing can match."""
    def build():
        return _filtered_leads_query(db, ctx, f, columns=columns, memo=memo, opted_out_only=opted_out_only)

    if build() is None:
        return []
    return _fetch_all(build)


@router.get("/summary")
async def leads_summary(f: LeadFilters = Depends(_lead_filters), ctx: dict = Depends(require_leads_view)):
    """Headline numbers for the Customers page, over the leads these filters match.
    Declared before the /{lead_id} routes so "summary" is not read as an id."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    memo: dict = {}
    ids = {r["id"] for r in _matching_rows(db, ctx, f, "id", memo)}

    said_stop = 0
    stop_query = _filtered_leads_query(db, ctx, f, columns="id", count="exact", memo=memo, opted_out_only=True)
    if stop_query is not None:
        said_stop = stop_query.range(0, 0).execute().count or 0

    buyers = repeat_buyers = not_back_90 = spent_paise = 0
    if ids:
        facts = _buyer_facts(db, tenant_id)
        quiet_since = datetime.now(timezone.utc) - timedelta(days=BUYER_QUIET_DAYS)
        for lead_id in ids:
            if lead_id not in facts["buyers"]:
                continue
            buyers += 1
            fact = facts["per_lead"].get(lead_id) or {}
            if fact.get("won_count", 0) >= 2:
                repeat_buyers += 1
            spent_paise += fact.get("spent_paise", 0)
            last_purchase = fact.get("last_purchase_at")
            if last_purchase is not None and last_purchase < quiet_since:
                not_back_90 += 1

    return {
        "people": len(ids),
        "leads": len(ids) - buyers,
        "buyers": buyers,
        "repeat_buyers": repeat_buyers,
        "spent_paise": spent_paise,
        "not_back_90": not_back_90,
        "said_stop": said_stop,
    }


INTEREST_LABELS = {"A": "Hot", "B": "Warm", "C": "Cold", "D": "Not interested"}


@router.get("/export")
async def export_leads(
    f: LeadFilters = Depends(_lead_filters),
    tenant_id: str = Depends(get_owner_tenant_id),
):
    db = get_supabase()
    ctx = {"tenant_id": tenant_id, "role": "owner"}
    leads = _matching_rows(db, ctx, f, "id,phone,name,source,ad_name,segment,assigned_to,created_at,last_inbound_at", {})

    # Exclude leads that appear only in failed broadcasts (never successfully sent to)
    any_br_ids: set[str] = set()
    sent_br_ids: set[str] = set()
    lead_ids = [l["id"] for l in leads]
    for scope in _in_scopes(lead_ids):
        for r in _fetch_all(lambda scope=scope: db.table("broadcast_recipients").select("lead_id,send_status")
                            .eq("tenant_id", tenant_id).in_("lead_id", scope)):
            if r.get("lead_id"):
                any_br_ids.add(r["lead_id"])
                if r.get("send_status") == "sent":
                    sent_br_ids.add(r["lead_id"])
    leads = [l for l in leads if l["id"] not in any_br_ids or l["id"] in sent_br_ids]

    facts = _buyer_facts(db, tenant_id)
    groups = _groups_by_lead(db, tenant_id)
    caller_ids = sorted({str(l["assigned_to"]) for l in leads if l.get("assigned_to")})
    caller_names: dict[str, str] = {}
    for scope in _in_scopes(caller_ids):
        for c in _fetch_all(lambda scope=scope: db.table("callers").select("id,name").eq("tenant_id", tenant_id).in_("id", scope)):
            caller_names[str(c["id"])] = c.get("name") or ""

    fieldnames = ["Name", "Phone", "Status", "Interest", "Came from", "Ad", "Assigned to",
                  "Spent", "Groups", "Added", "Last message"]
    rows = []
    for l in leads:
        lead_id = l["id"]
        spent = (facts["per_lead"].get(lead_id) or {}).get("spent_paise", 0)
        rows.append({
            "Name": l.get("name") or "",
            "Phone": l.get("phone") or "",
            "Status": "Buyer" if lead_id in facts["buyers"] else "Lead",
            "Interest": INTEREST_LABELS.get(l.get("segment"), ""),
            "Came from": l.get("source") or "",
            "Ad": l.get("ad_name") or "",
            "Assigned to": caller_names.get(str(l["assigned_to"]), "") if l.get("assigned_to") else "",
            "Spent": f"{spent / 100:.2f}",
            "Groups": "; ".join(g["name"] for g in groups.get(lead_id, [])),
            "Added": l.get("created_at") or "",
            "Last message": l.get("last_inbound_at") or "",
        })

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    filename = f"leads_{f.segment or 'all'}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@router.get("/export-assigned")
async def export_assigned_leads(
    ctx: dict = Depends(get_tenant_and_role),
):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    caller_id = ctx.get("caller_id")
    
    if not caller_id:
        raise HTTPException(status_code=400, detail="Caller profile not found")
        
    # Query leads assigned to caller
    leads_res = db.table("leads").select("*").eq("tenant_id", tenant_id).eq("assigned_to", caller_id).is_("deleted_at", "null").order("segment").order("last_inbound_at", desc=True, nullsfirst=False).order("created_at", desc=True).execute()
    leads = leads_res.data or []
    
    # Collect lead IDs for batch fetching
    lead_ids = [l["id"] for l in leads]
    
    # Fetch latest broadcast recipients for all these leads
    br_map = {}
    if lead_ids:
        br_recs = db.table("broadcast_recipients").select("lead_id, broadcast_id, tag_id").in_("lead_id", lead_ids).eq("tenant_id", tenant_id).order("created_at").execute()
        # Group by lead_id, keeping the latest (since ordered by created_at ascending, the last one is the latest)
        for rec in (br_recs.data or []):
            br_map[rec["lead_id"]] = rec
            
    # Collect all unique broadcast_ids, tag_ids, ad_campaign_ids
    broadcast_ids = list({str(rec["broadcast_id"]) for rec in br_map.values() if rec.get("broadcast_id")})
    tag_ids = list({str(rec["tag_id"]) for rec in br_map.values() if rec.get("tag_id")})
    ad_campaign_ids = list({str(l["ad_campaign_id"]) for l in leads if l.get("ad_campaign_id")})
    
    # Fetch scheduled_broadcasts templates
    sb_map = {}
    if broadcast_ids:
        sb_recs = db.table("scheduled_broadcasts").select("id, template_name").in_("id", broadcast_ids).eq("tenant_id", tenant_id).execute()
        sb_map = {str(r["id"]): r["template_name"] for r in (sb_recs.data or [])}
        
    # Fetch tag names
    tag_map = {}
    if tag_ids:
        tag_recs = db.table("broadcast_tags").select("id, name").in_("id", tag_ids).eq("tenant_id", tenant_id).execute()
        tag_map = {str(r["id"]): r["name"] for r in (tag_recs.data or [])}
        
    # Fetch ad campaigns
    campaign_map = {}
    if ad_campaign_ids:
        campaign_recs = db.table("ad_campaigns").select("id, campaign_name, platform").in_("id", ad_campaign_ids).eq("tenant_id", tenant_id).execute()
        campaign_map = {str(r["id"]): r for r in (campaign_recs.data or [])}
        
    # Generate rows
    rows = []
    for l in leads:
        lead_id = l["id"]
        br_rec = br_map.get(lead_id)
        
        broadcast_id = str(br_rec["broadcast_id"]) if br_rec else ""
        template_name = sb_map.get(broadcast_id, "") if broadcast_id else ""
        tag_name = tag_map.get(str(br_rec["tag_id"]), "") if br_rec and br_rec.get("tag_id") else ""
        
        ad_campaign_id = str(l.get("ad_campaign_id")) if l.get("ad_campaign_id") else ""
        ad_campaign_name = campaign_map.get(ad_campaign_id, {}).get("campaign_name", "") if ad_campaign_id else ""
        channel = campaign_map.get(ad_campaign_id, {}).get("platform", l.get("source", "")) if ad_campaign_id else l.get("source", "")
        
        lead_type = "inbound" if l.get("source") in INBOUND_SOURCES and not broadcast_id else "outbound"
        
        rows.append({
            "name": l.get("name") or "",
            "phone": l.get("phone") or "",
            "type": lead_type,
            "broadcast_id": broadcast_id,
            "template_name": template_name,
            "ad_campaign": ad_campaign_name,
            "channel": channel,
            "tag": tag_name,
            "score": l.get("score", 5),
            "segment": l.get("segment", "C"),
            "assigned_at": l.get("assigned_at") or ""
        })
        
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["name", "phone", "type", "broadcast_id", "template_name", "ad_campaign", "channel", "tag", "score", "segment", "assigned_at"])
    writer.writeheader()
    writer.writerows(rows)
    
    filename = f"assigned_leads_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@router.get("/{lead_id}/messages", response_model=list[Message])
async def get_lead_messages(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    result = db.table("messages").select("*").eq("lead_id", str(lead_id)).eq("tenant_id", tenant_id).order("created_at").execute()
    return result.data or []

@router.get("/{lead_id}", response_model=LeadWithMessages)
async def get_lead(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    lead_result = db.table("leads").select("*").eq("id", str(lead_id)).eq("tenant_id", tenant_id).is_("deleted_at", "null").maybe_single().execute()
    if not lead_result or not lead_result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    msgs_result = db.table("messages").select("*").eq("lead_id", str(lead_id)).eq("tenant_id", tenant_id).order("created_at").execute()
    lead = lead_result.data
    lead["messages"] = msgs_result.data or []
    
    # Enrichment
    lead["broadcast_id"] = None
    lead["template_name"] = None
    lead["tag_name"] = None
    lead["ad_campaign_name"] = None
    lead["channel"] = lead.get("source")
    
    # 1. Fetch latest broadcast recipient entry
    br_rec = db.table("broadcast_recipients").select("broadcast_id, tag_id").eq("lead_id", str(lead_id)).eq("tenant_id", tenant_id).order("created_at", desc=True).limit(1).execute()
    if br_rec.data:
        rec = br_rec.data[0]
        lead["broadcast_id"] = str(rec["broadcast_id"])
        
        # Look up template name
        sb_rec = db.table("scheduled_broadcasts").select("template_name").eq("id", rec["broadcast_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        if sb_rec and sb_rec.data:
            lead["template_name"] = sb_rec.data["template_name"]

        # Look up tag name
        if rec.get("tag_id"):
            tag_rec = db.table("broadcast_tags").select("name").eq("id", rec["tag_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
            if tag_rec and tag_rec.data:
                lead["tag_name"] = tag_rec.data["name"]

    # 2. Check for ad campaign
    if lead.get("ad_campaign_id"):
        campaign = db.table("ad_campaigns").select("campaign_name, platform").eq("id", lead["ad_campaign_id"]).eq("tenant_id", tenant_id).maybe_single().execute()
        if campaign and campaign.data:
            lead["ad_campaign_name"] = campaign.data["campaign_name"]
            lead["channel"] = campaign.data["platform"]

    _add_came_from(db, tenant_id, [lead])
    return lead

@router.patch("/{lead_id}", response_model=Lead)
async def update_lead(lead_id: UUID, updates: LeadUpdate, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    existing = (
        db.table("leads")
        .select("segment,phone,ai_enabled,converted_at")
        .eq("id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    update_data = updates.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = db.table("leads").update(update_data).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    updated = result.data[0]
    if updated.get("segment") != existing.data.get("segment"):
        record_stage_event(
            str(lead_id),
            from_segment=existing.data.get("segment"),
            to_segment=updated.get("segment") or existing.data.get("segment") or "C",
            event_type="manual_update",
            metadata={"source": "dashboard"},
            tenant_id=tenant_id,
            db=db,
        )
        # Manually moving a lead into a qualifying segment should queue it for
        # telecalling, same as an AI-driven promotion.
        if not updated.get("assigned_to") and not updated.get("converted_at"):
            from app.services.assignment import maybe_assign_lead
            maybe_assign_lead(
                str(lead_id), tenant_id, updated.get("segment"), None,
                reason="manual",
            )
    sync_follow_up_jobs(
        str(lead_id),
        segment=updated.get("segment"),
        phone=updated.get("phone") or existing.data.get("phone"),
        converted_at=updated.get("converted_at"),
        ai_enabled=updated.get("ai_enabled", existing.data.get("ai_enabled", True)),
        reason="manual_update",
        tenant_id=tenant_id,
        db=db,
    )
    return updated

@router.post("/{lead_id}/convert", response_model=Lead)
async def mark_converted(lead_id: UUID, payload: ConvertPayload | None = None, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    existing = (
        db.table("leads")
        .select("segment,phone,ai_enabled")
        .eq("id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    notes = (payload.notes if payload else None) or None
    update = {
        "converted_at": datetime.now(timezone.utc).isoformat(),
        "call_status": "converted",
    }
    if notes:
        update["conversion_notes"] = notes
    result = db.table("leads").update(update).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    updated = result.data[0]
    record_stage_event(
        str(lead_id),
        from_segment=existing.data.get("segment"),
        to_segment=existing.data.get("segment"),
        event_type="converted",
        metadata={"notes": notes} if notes else {},
        tenant_id=tenant_id,
        db=db,
    )
    sync_follow_up_jobs(
        str(lead_id),
        segment=existing.data.get("segment"),
        phone=updated.get("phone") or existing.data.get("phone"),
        converted_at=updated.get("converted_at"),
        ai_enabled=updated.get("ai_enabled", existing.data.get("ai_enabled", True)),
        reason="converted",
        tenant_id=tenant_id,
        db=db,
    )
    return updated


@router.patch("/{lead_id}/ai", response_model=Lead)
async def toggle_ai(lead_id: UUID, payload: AiToggle, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    existing = (
        db.table("leads")
        .select("segment,phone,converted_at")
        .eq("id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    result = db.table("leads").update({"ai_enabled": payload.enabled}).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    updated = result.data[0]
    sync_follow_up_jobs(
        str(lead_id),
        segment=updated.get("segment") or existing.data.get("segment"),
        phone=updated.get("phone") or existing.data.get("phone"),
        converted_at=updated.get("converted_at") or existing.data.get("converted_at"),
        ai_enabled=payload.enabled,
        reason="ai_toggle",
        tenant_id=tenant_id,
        db=db,
    )
    return updated


@router.patch("/{lead_id}/pin")
async def toggle_pin(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    result = db.rpc("toggle_lead_pin", {"p_lead_id": str(lead_id), "p_tenant_id": tenant_id}).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return result.data[0]


@router.patch("/{lead_id}/archive")
async def toggle_archive(lead_id: UUID, ctx: dict = Depends(require_conversations_reply)):
    """Toggle a conversation's archived state (inbox tidy — does not stop AI)."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    cur = db.table("leads").select("archived_at").eq("id", str(lead_id)).eq("tenant_id", tenant_id).maybe_single().execute()
    if not cur.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    new_val = None if cur.data.get("archived_at") else datetime.now(timezone.utc).isoformat()
    patch = {"archived_at": new_val, "archived_by_name": actor_name(db, ctx) if new_val else None, "archived_reason": None}
    res = db.table("leads").update(patch).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    return res.data[0] if res.data else patch


@router.patch("/{lead_id}/block")
async def toggle_block(lead_id: UUID, ctx: dict = Depends(get_tenant_and_role)):
    """Toggle a contact's blocked state — hides from active inbox and stops AI auto-reply."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    cur = db.table("leads").select("blocked_at").eq("id", str(lead_id)).eq("tenant_id", tenant_id).maybe_single().execute()
    if not cur.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    blocking = not cur.data.get("blocked_at")
    update: dict = {
        "blocked_at": datetime.now(timezone.utc).isoformat() if blocking else None,
        "blocked_by_name": actor_name(db, ctx) if blocking else None,
    }
    if blocking:
        update["ai_enabled"] = False  # blocked contacts must not get auto-replies
    res = db.table("leads").update(update).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    # Full block: nothing is sent to a blocked person (services/blocked_guard.py). Forget the
    # cached list so this process obeys the change at once; other workers within a minute.
    from app.services.blocked_guard import invalidate
    invalidate(tenant_id)
    if blocking:
        _close_handovers_for_blocked(db, ctx, tenant_id, str(lead_id))
    return res.data[0] if res.data else update


def _close_handovers_for_blocked(db, ctx: dict, tenant_id: str, lead_id: str) -> None:
    """A blocked person must not sit in the Needs you tab, the sidebar count or the team's
    claim banner: close their open handovers. Never fails the block itself."""
    try:
        done = db.table("chat_handovers").update({
            "status": "resolved",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": ctx.get("user_id"),
            "resolved_by_name": actor_name(db, ctx),
        }).eq("lead_id", lead_id).eq("tenant_id", tenant_id).eq("status", "pending").execute().data or []
        if done:
            from app.services.notify import clear_pool_notifications_for_lead
            clear_pool_notifications_for_lead(tenant_id, lead_id, db=db)
        db.table("leads").update({"needs_human_attention": False, "escalation_reason": None}) \
            .eq("id", lead_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.warning(f"Block: could not close open handovers for lead {lead_id}: {e}")


@router.post("/{lead_id}/send")
async def send_human_message(
    lead_id: UUID,
    payload: HumanMessage,
    ctx: dict = Depends(require_conversations_reply),
):
    tenant_id = ctx["tenant_id"]
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message is empty")

    db = get_supabase()
    lead = db.table("leads").select("phone,source,ig_user_id,tg_user_id,fb_user_id,blocked_at").eq("id", str(lead_id)).eq("tenant_id", tenant_id).maybe_single().execute()
    if not lead.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.data.get("blocked_at"):
        # Fresh read of the lead itself, not the cached list: a blocked person gets no staff reply.
        raise HTTPException(status_code=409, detail="This person is blocked. Unblock to reply.")

    source = lead.data.get("source")
    channel = (
        "instagram" if source == "instagram"
        else "telegram" if source == "telegram"
        else "facebook" if source == "facebook"
        else "whatsapp"
    )
    sid: str | None = None
    if channel == "instagram":
        ig_id = lead.data.get("ig_user_id")
        if not ig_id:
            raise HTTPException(status_code=400, detail="Instagram lead missing ig_user_id")
        sid = await send_instagram(ig_id, content, tenant_id=tenant_id)
    elif channel == "telegram":
        tg_id = lead.data.get("tg_user_id")
        if not tg_id:
            raise HTTPException(status_code=400, detail="Telegram lead missing tg_user_id")
        from app.services.ai_reply import send_telegram
        sid = await send_telegram(tg_id, content, tenant_id=tenant_id)
    elif channel == "facebook":
        fb_id = lead.data.get("fb_user_id")
        if not fb_id:
            raise HTTPException(status_code=400, detail="Facebook lead missing fb_user_id")
        sid = await send_facebook(fb_id, content, tenant_id=tenant_id)
    else:
        phone = lead.data.get("phone")
        if not phone:
            raise HTTPException(status_code=400, detail="Lead has no phone number")
        sid = await send_whatsapp(phone, content, tenant_id=tenant_id)

    if not sid:
        meta_err = get_last_send_error() or "unknown error"
        raise HTTPException(status_code=502, detail=f"Channel send failed: {meta_err}")

    if channel == "telegram":
        sid_field = "tg_message_id"
    elif channel == "facebook":
        sid_field = "fb_message_id"
    else:
        sid_field = "meta_message_id"  # whatsapp and instagram both use meta_message_id
    row = db.table("messages").insert({
        "lead_id": str(lead_id),
        "tenant_id": tenant_id,
        "direction": "outbound",
        "channel": channel,
        "content": content,
        "is_ai_generated": False,
        sid_field: sid,
        **sender_fields(db, ctx),
    }).execute()
    
    # Clear needs_human_intervention flag
    db.table("leads").update({"needs_human_intervention": False}).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    
    return row.data[0] if row.data else {"sent": True, "sid": sid}


class ShareProductIn(BaseModel):
    item_id: str = Field(..., max_length=64)


@router.post("/{lead_id}/share-product")
async def share_product_route(lead_id: UUID, payload: ShareProductIn, ctx: dict = Depends(require_conversations_reply)):
    """Conversations 'Share product': one catalogue item, photo + name + price, on WhatsApp."""
    try:
        db = get_supabase()
        return await share_product(db, ctx["tenant_id"], str(lead_id), payload.item_id, sender=sender_fields(db, ctx))
    except ShareProductError as e:
        raise HTTPException(status_code=400, detail=str(e))


class ComposeMessage(BaseModel):
    phone: str
    content: str | None = None
    name: str | None = None
    # Send an approved template instead of free text (required outside the 24-hour window).
    template_id: str | None = Field(None, max_length=64)
    variables: list[str] = Field(default_factory=list, max_length=20)


@router.get("/compose/templates")
def compose_template_options(ctx: dict = Depends(require_leads_manage)):
    """Approved WhatsApp templates the New message form can send."""
    return {"templates": compose_templates(get_supabase(), ctx["tenant_id"])}


def _compose_phone(raw: str) -> str:
    phone = raw.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    if len(phone) < 8:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    return phone


def _compose_lead(db, tenant_id: str, phone: str, name: str | None) -> str:
    """The lead for this number, created when there isn't one yet; the typed name is kept."""
    existing = db.table("leads").select("id").eq("phone", phone).eq("tenant_id", tenant_id).limit(1).execute()
    if existing.data:
        lead_id = existing.data[0]["id"]
        if name:
            db.table("leads").update({"name": name}).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
        return lead_id
    initial_score, initial_segment = new_lead_score_and_segment(tenant_id)
    insert_data = {"phone": phone, "source": "manual", "score": initial_score, "segment": initial_segment, "tenant_id": tenant_id}
    if name:
        insert_data["name"] = name
    lead_id = db.table("leads").insert(insert_data).execute().data[0]["id"]
    record_stage_event(lead_id, to_segment=initial_segment, event_type="created", metadata={"source": "manual"}, tenant_id=tenant_id, db=db)
    return lead_id


class ComposeSchedule(BaseModel):
    phone: str
    name: str | None = None
    template_id: str = Field(..., max_length=64)
    variables: list[str] = Field(default_factory=list, max_length=20)
    send_at: datetime


@router.post("/compose/schedule")
def compose_schedule_template(payload: ComposeSchedule, ctx: dict = Depends(require_leads_manage)):
    """The New message form's Schedule: same lead handling as /compose, but the template goes out later."""
    tenant_id = ctx["tenant_id"]
    phone = _compose_phone(payload.phone)
    db = get_supabase()
    try:
        # Checked before the lead is created, so a bad time or an unfilled blank leaves nothing behind.
        scheduled_templates.check_send_at(payload.send_at, scheduled_templates.utcnow())
        prepare_template(db, tenant_id, payload.template_id, payload.variables)
        if not _whatsapp_ready(tenant_id, {"phone": phone, "opted_out": False}):
            raise ShareError("WhatsApp isn't connected. Connect it in Settings first.")
        lead_id = _compose_lead(db, tenant_id, phone, payload.name)
        row = scheduled_templates.schedule_template(
            db, tenant_id, ctx.get("user_id"), lead_id, payload.template_id, payload.variables, payload.send_at,
        )
    except scheduled_templates.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {**row, "phone": phone}


@router.post("/compose")
async def compose_new_message(
    payload: ComposeMessage,
    background_tasks: BackgroundTasks,
    ctx: dict = Depends(require_leads_manage),
):
    """Send a WhatsApp message to any phone — creates lead if it doesn't exist."""
    tenant_id = ctx["tenant_id"]
    content = (payload.content or "").strip()
    if payload.template_id is None and not content:
        raise HTTPException(status_code=400, detail="Message is empty")
    if payload.template_id is not None and content:
        raise HTTPException(status_code=400, detail="Send either a message or a template")

    phone = _compose_phone(payload.phone)
    from app.services.blocked_guard import ensure_not_blocked
    await ensure_not_blocked(tenant_id, phone)  # full block: 409 "This person is blocked. Unblock to reply."
    db = get_supabase()
    lead_id = _compose_lead(db, tenant_id, phone, payload.name)

    if payload.template_id is not None:
        try:
            sid, content = await send_approved_template(db, tenant_id, phone, payload.template_id, payload.variables)
        except ShareError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        sid = await send_whatsapp(phone, content, tenant_id=tenant_id)
    if not sid:
        meta_err = get_last_send_error() or "unknown error"
        # Note: outside 24h window, freeform text fails — Meta requires templates
        raise HTTPException(
            status_code=502,
            detail=(
                f"Send failed: {meta_err}. "
                "If recipient hasn't messaged you in 24h, you must use an approved template."
            ),
        )

    db.table("messages").insert({
        "lead_id": lead_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "channel": "whatsapp",
        "content": content,
        "is_ai_generated": False,
        "meta_message_id": sid,
        **sender_fields(db, ctx),
    }).execute()
    return {"lead_id": lead_id, "sid": sid, "phone": phone}


@router.delete("/{lead_id}/clear-data")
@router.delete("/{lead_id}/clear-chat")  # the pre-rename path, for a frontend still on the old build
async def clear_data(lead_id: UUID, tenant_id: str = Depends(get_owner_tenant_id)):
    """Clear Data: erase the lead and everything about it -- messages, bookings, payments,
    notes, score -- so the next message from that number starts as a brand-new lead.

    This used to be "Clear Chat", which kept the lead row, its score and every paid booking,
    so a cleared test lead still came back "A · Hot" with its history half there. Owner-only
    because it now erases payment records too (Razorpay keeps its own copy of the payment).
    """
    from app.services.lead_wipe import wipe_lead

    db = get_supabase()
    lead = db.table("leads").select("id").eq("id", str(lead_id)).eq("tenant_id", tenant_id).maybe_single().execute()
    if not lead or not lead.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    cancelled = await wipe_lead(db, str(lead_id), tenant_id)
    return {"success": True, "message": "Lead data cleared", "payment_links_cancelled": cancelled}


@router.delete("/{lead_id}")
async def delete_lead(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    result = db.table("leads").update({"deleted_at": now, "ai_enabled": False}).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    db.table("follow_up_jobs").update({"status": "skipped", "skip_reason": "Lead deleted."}).eq("lead_id", str(lead_id)).eq("status", "pending").execute()
    return {"success": True, "message": "Lead deleted"}

@router.post("/{lead_id}/pre-call-brief", response_model=PreCallBriefResponse)
async def pre_call_brief(
    lead_id: UUID,
    ctx: dict = Depends(get_tenant_and_role),
    force: bool = Query(False, description="Skip the cache and regenerate."),
):
    role = ctx.get("role")
    if role not in ("caller", "owner"):
        raise HTTPException(status_code=403, detail="Caller or owner role required")

    tenant_id = ctx["tenant_id"]
    db = get_supabase()

    lead_res = (
        db.table("leads")
        .select(
            "name,score,segment,source,ad_campaign_id,assigned_at,"
            "needs_human_attention,precall_brief,precall_brief_fingerprint"
        )
        .eq("id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not lead_res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead = lead_res.data

    campaign_name = None
    if lead.get("ad_campaign_id"):
        camp_res = (
            db.table("ad_campaigns")
            .select("campaign_name")
            .eq("id", lead["ad_campaign_id"])
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if camp_res.data:
            campaign_name = camp_res.data.get("campaign_name")

    # Newest-first for the fingerprint; a wider window than the old cap of 5 so a
    # telecaller opening a long-running lead sees more than the last exchange.
    msgs_res = (
        db.table("messages")
        .select("content,direction,created_at")
        .eq("lead_id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    messages_desc = msgs_res.data or []
    messages = list(reversed(messages_desc))

    calls_res = (
        db.table("call_logs")
        .select("outcome,manual_status,duration_seconds,created_at,ai_summary")
        .eq("lead_id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    call_logs = calls_res.data or []

    # Cache: a lead with no new messages and no new calls since the last brief
    # gets the stored copy back with no LLM call at all. `force` (the UI's
    # "Refresh" button) always bypasses this.
    latest_msg_at = messages_desc[0]["created_at"] if messages_desc else ""
    latest_call_at = call_logs[0]["created_at"] if call_logs else ""
    fingerprint = f"{latest_msg_at}|{latest_call_at}"
    if (
        not force
        and lead.get("precall_brief")
        and lead.get("precall_brief_fingerprint") == fingerprint
    ):
        cached = lead["precall_brief"]
        return PreCallBriefResponse(brief=cached["brief"], opener=cached["opener"])

    if messages:
        messages_text = "\n".join(
            f"[{m['direction']}] {m['content']}" for m in messages
        )
    else:
        messages_text = None

    conversation_summary = _fetch_conversation_summary(db, str(lead_id))

    # Reuses the exact block the AI reply prompt builds (ai_reply.py) so the
    # telecaller and the AI describe the same call the same way.
    call_context_block = _call_context_block(call_logs) or None

    open_handover_line = (
        "Yes — this lead is currently escalated to a human and waiting on a reply.\n"
        if lead.get("needs_human_attention")
        else "No.\n"
    )

    name = lead.get("name") or "Unknown"
    score = lead.get("score") or 5
    segment = lead.get("segment") or "C"
    channel = lead.get("source") or "unknown"
    campaign = campaign_name or "N/A"
    assigned_at = lead.get("assigned_at") or "N/A"

    prompt = f"""You are a sales coach briefing a telecaller before they dial.

Lead profile:
- Name: {name}
- Score: {score}/10 (Segment {segment})
- Source: {channel} — {campaign}
- Assigned: {assigned_at}

Earlier conversation summary (before the messages below):
{conversation_summary or "None"}

Recent WhatsApp messages (newest last):
{messages_text or "No WhatsApp activity"}

{call_context_block or "No call history."}

Currently escalated to a human, waiting unresolved: {open_handover_line}
Write EXACTLY this JSON (no markdown, no explanation):
{{"brief": "2-3 sentence summary of who this lead is, where they came from, what happened on WhatsApp and any past calls, and — if the AI could not resolve something — what that is", "opener": "one natural opening line the caller can use to start the conversation"}}"""

    try:
        parsed = await gemini_chat_completion_json(
            system_prompt="You are a sales coach briefing a telecaller before they dial.",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=400,
            tenant_id=tenant_id,
            purpose="pre_call_brief",
        )
        brief_data = {"brief": parsed["brief"], "opener": parsed["opener"]}
    except Exception as e:
        logger.error(f"Pre-call brief generation failed for lead {lead_id}: {e}")
        raise HTTPException(status_code=500, detail="Brief generation failed")

    try:
        db.table("leads").update({
            "precall_brief": brief_data,
            "precall_brief_fingerprint": fingerprint,
        }).eq("id", str(lead_id)).eq("tenant_id", tenant_id).execute()
    except Exception:
        logger.exception("Failed to cache pre-call brief for lead %s", lead_id)

    return PreCallBriefResponse(brief=brief_data["brief"], opener=brief_data["opener"])


@router.get("/{lead_id}/call-logs")
async def get_lead_call_logs(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    db = get_supabase()
    result = (
        db.table("call_logs")
        .select("id,call_sid,status,outcome,manual_status,next_action_at,provider,duration_seconds,recording_url,score,score_status,call_group,talk_share,interruption_count,interruptions_per_5min,score_final,evaluation,ai_status,ai_error,ai_summary,transcript,created_at,callers(name)")
        .eq("lead_id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    is_sim = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi") == "sim_basic"
    return {"data": strip_evaluation(mask_transcripts(result.data), is_sim)}


@router.post("/{lead_id}/compact")
async def manual_compact(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    """Manually trigger conversation compaction for debugging/admin purposes."""
    db = get_supabase()
    try:
        from app.services.conversation_compactor import compact_conversation
        summary = await compact_conversation(str(lead_id), tenant_id, db, mode="rolling")
        return {"summary": summary, "status": "compacted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compaction failed: {str(e)}")


@router.get("/{lead_id}/score-history")
async def score_history(lead_id: UUID, ctx: dict = Depends(get_tenant_and_role)):
    """Return score change events for a lead, newest first. Max 20."""
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    result = (
        db.table("lead_stage_events")
        .select("id,event_type,from_segment,to_segment,metadata,created_at")
        .eq("lead_id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .in_("event_type", ["segment_changed", "score_updated"])
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"data": result.data or []}


@router.patch("/{lead_id}/release")
async def release_lead(lead_id: UUID, tenant_id: str = Depends(get_tenant_id)):
    """Unassign a lead from its caller — caller marks it as 'done'.
    Drops it from their queue so the next auto-assign can pick it up."""
    db = get_supabase()
    result = (
        db.table("leads")
        .update({"assigned_to": None})
        .eq("id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"released": True}


@router.post("/{lead_id}/takeover")
async def takeover_lead(lead_id: UUID, ctx: dict = Depends(get_tenant_and_role)):
    """Allow a telecaller to claim an overdue callback from an unavailable caller."""
    tenant_id = ctx["tenant_id"]
    caller_id = ctx.get("caller_id")
    if not caller_id:
        raise HTTPException(status_code=400, detail="Only telecallers can claim callbacks")

    db = get_supabase()
    
    # 1. Fetch lead and its assigned caller status
    lead_res = (
        db.table("leads")
        .select("id,name,assigned_to,segment,score")
        .eq("id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not lead_res or not lead_res.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead_data = lead_res.data
    assigned_to = lead_data.get("assigned_to")
    if str(assigned_to) == str(caller_id):
        raise HTTPException(status_code=400, detail="This lead is already assigned to you")

    # 2. Fetch pending callback details
    job_res = (
        db.table("follow_up_jobs")
        .select("id,scheduled_for")
        .eq("lead_id", str(lead_id))
        .eq("tenant_id", tenant_id)
        .eq("cadence", "callback")
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    if not job_res.data:
        raise HTTPException(status_code=400, detail="Lead has no pending callback scheduled")

    job_data = job_res.data[0]
    scheduled_for = datetime.fromisoformat(job_data["scheduled_for"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    
    # Look up the previous owner only to notify them after the claim.
    prev_caller_name = "Unknown"
    prev_caller_user_id = None
    if assigned_to:
        caller_res = (
            db.table("callers")
            .select("name,user_id")
            .eq("id", assigned_to)
            .maybe_single()
            .execute()
        )
        if caller_res and caller_res.data:
            prev_caller_name = caller_res.data.get("name") or "Unknown"
            prev_caller_user_id = caller_res.data.get("user_id")

    # Claimable purely on time: 15 minutes past the scheduled slot, regardless of status.
    if now < scheduled_for + timedelta(minutes=15):
        raise HTTPException(
            status_code=400,
            detail="Cannot claim yet: callback is not 15 minutes overdue",
        )

    # 3. Perform takeover atomically
    # CAS guard: only succeeds if assigned_to still matches what we read
    update_query = db.table("leads").update({
        "assigned_to": caller_id,
        "assigned_at": now.isoformat(),
    }).eq("id", str(lead_id)).eq("tenant_id", tenant_id)
    if assigned_to is None:
        update_query = update_query.is_("assigned_to", "null")
    else:
        update_query = update_query.eq("assigned_to", assigned_to)
    update_result = update_query.execute()
    if not update_result.data:
        raise HTTPException(status_code=409, detail="Lead already claimed by another caller")

    # Update callback scheduled_for to now (so it shows as due now for the claiming caller)
    db.table("follow_up_jobs").update({
        "scheduled_for": now.isoformat(),
    }).eq("id", job_data["id"]).eq("tenant_id", tenant_id).execute()

    # Get claiming caller's name
    me_res = db.table("callers").select("name").eq("id", caller_id).maybe_single().execute()
    me_name = me_res.data.get("name") if me_res and me_res.data else "Another Caller"

    # Log assignment event
    record_assignment_event(
        lead_id=str(lead_id),
        tenant_id=tenant_id,
        segment=lead_data.get("segment"),
        caller_id=caller_id,
        caller_name=me_name,
        reason="caller_unavailable",
        method="takeover",
        score=lead_data.get("score"),
        matched_segments=[lead_data.get("segment")] if lead_data.get("segment") else [],
        prev_caller_id=assigned_to,
        prev_caller_name=prev_caller_name,
        event_type="reassigned",
        db=db,
    )

    if prev_caller_user_id:
        from app.services.notify import notify_user
        notify_user(
            tenant_id,
            prev_caller_user_id,
            "callback_taken_over",
            "Callback claimed",
            f"{me_name} claimed your callback for '{lead_data.get('name') or 'Unknown'}'.",
            db=db,
            push_url="/dashboard/telecalling/scheduled",
        )

    try:
        from app.services.notify import clear_pool_notifications_for_lead
        clear_pool_notifications_for_lead(tenant_id, str(lead_id), db=db)
    except Exception:
        pass

    return {"success": True, "assigned_to": caller_id}
