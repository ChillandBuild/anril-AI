"""Customers > Groups: named lists of leads.

kind 'picked': people added by hand (customer_group_members).
kind 'rule': fills itself from a saved set of All-people filters (services/group_rules.py);
its members are worked out each time, so the member routes refuse it.
Said-stop people stay in a group (counted in stop_count) but nothing is sent to them.
Every query is scoped to the caller's tenant. A group of another tenant reads as 404.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.db.supabase import get_supabase
from app.dependencies.tenant import _has_permission
from app.routes.conversations import _filter_params, _view
from app.routes.leads import (
    LeadFilters, _fetch_all, _filtered_leads_query, _in_scopes, require_leads_manage, require_leads_view,
)
from app.services.group_rules import GroupRule, describe, has_spend, parse_rule, without_money

logger = logging.getLogger(__name__)

router = APIRouter()

DUPLICATE_NAME = "A group with this name already exists"
SPEND_NEEDS_DEALS = "Spend rules need access to Orders & payments"

# "Save as a group" on Chats: most people one group can take from the Chats list.
FROM_CHATS_MAX = 5000
_FROM_CHATS_PAGE = 200
_MEMBER_CHUNK = 500


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


class NewGroupIn(GroupIn):
    # Set = a group that fills itself from these filters; empty = a picked group.
    rule: GroupRule | None = None


class RuleIn(BaseModel):
    rule: GroupRule


class LeadIdsIn(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=1000)


class FromChatsIn(GroupIn):
    """The Chats page's tab, search and filters, in the same words as GET /api/v1/conversations
    (comma lists for the multi-pick ones)."""
    view: str = "inbox"
    q: str | None = Field(default=None, max_length=100)
    channels: str | None = Field(default=None, max_length=100)
    segments: str | None = Field(default=None, max_length=20)
    results: str | None = Field(default=None, max_length=60)
    came_from: str | None = Field(default=None, max_length=120)
    handled_by: str | None = Field(default=None, max_length=2000)
    waiting: str | None = Field(default=None, max_length=60)
    since: datetime | None = None
    tag_id: UUID | None = None


def _valid_ids(raw: list[str]) -> list[str]:
    """Distinct, well-formed lead ids in lowercase (the form PostgREST returns). Others are dropped."""
    seen: dict[str, None] = {}
    for item in raw:
        try:
            seen[str(UUID(str(item)))] = None
        except ValueError:
            continue
    return list(seen)


def _group_or_404(db, tenant_id: str, group_id: str) -> dict:
    res = (db.table("customer_groups").select("id,name,kind,rule,created_by,created_at")
           .eq("id", group_id).eq("tenant_id", tenant_id).maybe_single().execute())
    if not (res and res.data):
        raise HTTPException(status_code=404, detail="Group not found")
    return res.data


def _name_taken(db, tenant_id: str, name: str, exclude_id: str | None = None) -> bool:
    """Case-insensitive, the same rule as the unique index on customer_groups."""
    wanted = name.strip().lower()
    rows = _fetch_all(lambda: db.table("customer_groups").select("id,name").eq("tenant_id", tenant_id))
    return any(str(r["id"]) != exclude_id and (r.get("name") or "").strip().lower() == wanted for r in rows)


def _live_lead_ids(db, tenant_id: str, lead_ids: list[str]) -> set[str]:
    """The ids that are leads of this tenant and not deleted."""
    found: set[str] = set()
    for scope in _in_scopes(lead_ids):
        rows = _fetch_all(lambda scope=scope: db.table("leads").select("id").eq("tenant_id", tenant_id)
                          .is_("deleted_at", "null").in_("id", scope))
        found.update(str(r["id"]) for r in rows)
    return found


def _member_counts(db, tenant_id: str, group_ids: list[str] | None = None) -> dict[str, int]:
    """group id -> number of members whose lead is not deleted."""
    wanted = set(group_ids) if group_ids is not None else None
    members = _fetch_all(lambda: db.table("customer_group_members").select("group_id,lead_id")
                         .eq("tenant_id", tenant_id), order_by=("group_id", "lead_id"))
    members = [m for m in members if wanted is None or str(m["group_id"]) in wanted]
    live = _live_lead_ids(db, tenant_id, sorted({str(m["lead_id"]) for m in members}))
    counts: dict[str, int] = {}
    for m in members:
        if str(m["lead_id"]) in live:
            gid = str(m["group_id"])
            counts[gid] = counts.get(gid, 0) + 1
    return counts


def _count(db, ctx: dict, group_id: str, opted_out_only: bool) -> int:
    """People in a group as All people would count them, optionally only the Said-stop ones."""
    query = _filtered_leads_query(db, ctx, LeadFilters(group_id=group_id), columns="id", count="exact",
                                  opted_out_only=opted_out_only)
    if query is None:
        return 0
    return query.limit(1).execute().count or 0


def _rule_names(db, tenant_id: str, rule: dict) -> dict:
    """Display names for the ids in a rule, so the table can say which broadcast or person."""
    names: dict = {}
    try:
        if rule.get("broadcast_id"):
            rows = (db.table("scheduled_broadcasts").select("template_name").eq("id", rule["broadcast_id"])
                    .eq("tenant_id", tenant_id).limit(1).execute()).data or []
            names["broadcast"] = rows[0].get("template_name") if rows else None
        if rule.get("ad_campaign_id"):
            rows = (db.table("ad_campaigns").select("campaign_name").eq("id", rule["ad_campaign_id"])
                    .eq("tenant_id", tenant_id).limit(1).execute()).data or []
            names["campaign"] = rows[0].get("campaign_name") if rows else None
        if rule.get("assigned_to") and rule["assigned_to"] not in ("unassigned", "ai_agent"):
            rows = (db.table("callers").select("name").eq("id", rule["assigned_to"])
                    .eq("tenant_id", tenant_id).limit(1).execute()).data or []
            names["caller"] = rows[0].get("name") if rows else None
    except Exception as e:
        logger.warning(f"Groups: could not read names for a rule: {e}")
    return names


def _creator_names(db, tenant_id: str, user_ids: list[str]) -> dict[str, str]:
    ids = sorted({u for u in user_ids if u})
    if not ids:
        return {}
    try:
        rows = (db.table("tenant_users").select("user_id,full_name").eq("tenant_id", tenant_id)
                .in_("user_id", ids).execute()).data or []
    except Exception:
        return {}
    return {str(r["user_id"]): r["full_name"] for r in rows if r.get("full_name")}


def _shape(row: dict, member_count: int, stop_count: int = 0, rule_text: str | None = None,
           made_by: str | None = None, show_money: bool = True) -> dict:
    kind = row.get("kind") or "picked"
    rule = parse_rule(row.get("rule")) if kind == "rule" else None
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "kind": kind,
        # Rupee rules (total spend) are only for people who can see money (deals.view).
        "rule": rule if show_money else without_money(rule),
        "spend_hidden": bool(not show_money and has_spend(rule)),
        "used_by": [],
        "rule_text": rule_text,
        "member_count": member_count,
        "stop_count": stop_count,
        "made_by": made_by,
        "created_at": row.get("created_at"),
    }


def _full_shape(db, ctx: dict, row: dict, made_by: str | None = None) -> dict:
    """A group with its counts. A rule group's count is everyone its filters match today."""
    gid = str(row["id"])
    money = _has_permission(ctx, "deals.view")
    stop = _count(db, ctx, gid, opted_out_only=True)
    if (row.get("kind") or "picked") == "rule":
        rule = parse_rule(row.get("rule")) or {}
        members = _count(db, ctx, gid, opted_out_only=False) + stop
        text = describe(rule, _rule_names(db, ctx["tenant_id"], rule), show_money=money) if rule else None
        return _shape(row, members, stop, text, made_by, money)
    members = _member_counts(db, ctx["tenant_id"], [gid]).get(gid, 0)
    return _shape(row, members, stop, None, made_by, money)


USED_BY_ORDER = ("Reach", "Call IQ", "Follow-ups")


def _used_by(db, tenant_id: str, rows: list[dict]) -> dict[str, list[str]]:
    """group id -> where it is used: "Reach" (a campaign was sent to it, or one is scheduled),
    "Call IQ" (it was sent to calling) and "Follow-ups" (a follow-up step is aimed at it).
    Each lookup is one query for every group, and a failed lookup only leaves its word out."""
    import json
    from app.services.reach_audience import GROUP_LABEL_PREFIX

    used: dict[str, set[str]] = {str(r["id"]): set() for r in rows}
    by_label = {f"{GROUP_LABEL_PREFIX}{r['name']}": str(r["id"]) for r in rows}
    try:  # Follow-ups: a step with target_group_id (migration 320)
        steps = (db.table("reengagement_steps").select("target_group_id").eq("tenant_id", tenant_id)
                 .not_.is_("target_group_id", "null").execute().data or [])
        for s in steps:
            if str(s.get("target_group_id")) in used:
                used[str(s["target_group_id"])].add("Follow-ups")
    except Exception as e:
        logger.info("Groups: follow-up use not read: %s", e)
    try:  # Reach: a group send is saved with the group's name in the file-name slot (see upload.bulk_send)
        held = (db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", "broadcast_history")
                .maybe_single().execute())
        history = json.loads(held.data["value"]) if held and held.data and held.data.get("value") else []
        for h in history:
            if isinstance(h, dict) and not h.get("csv_file_url") and not h.get("csv_file_path") \
                    and by_label.get(h.get("csv_file_name") or ""):
                used[by_label[h["csv_file_name"]]].add("Reach")
        pending = (db.table("scheduled_broadcasts").select("csv_file_name").eq("tenant_id", tenant_id)
                   .in_("csv_file_name", list(by_label)).limit(1000).execute().data or []) if by_label else []
        for p in pending:
            if by_label.get(p.get("csv_file_name") or ""):
                used[by_label[p["csv_file_name"]]].add("Reach")
    except Exception as e:
        logger.info("Groups: Reach use not read: %s", e)
    try:  # Call IQ: the assignment log keeps the group id of a "send group to calling" (new rows only)
        events = (db.table("lead_stage_events").select("metadata").eq("tenant_id", tenant_id)
                  .eq("event_type", "assigned").eq("metadata->>reason", "group")
                  .order("created_at", desc=True).limit(1000).execute().data or [])
        for ev in events:
            gid = str((ev.get("metadata") or {}).get("group_id") or "")
            if gid in used:
                used[gid].add("Call IQ")
    except Exception as e:
        logger.info("Groups: Call IQ use not read: %s", e)
    return {gid: [w for w in USED_BY_ORDER if w in words] for gid, words in used.items()}


@router.get("")
def list_groups(ctx: dict = Depends(require_leads_view)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    rows = _fetch_all(lambda: db.table("customer_groups").select("id,name,kind,rule,created_by,created_at")
                      .eq("tenant_id", tenant_id).order("created_at", desc=True))
    picked_ids = [str(r["id"]) for r in rows if (r.get("kind") or "picked") == "picked"]
    counts = _member_counts(db, tenant_id, picked_ids) if picked_ids else {}
    creators = _creator_names(db, tenant_id, [str(r["created_by"]) for r in rows if r.get("created_by")])
    used = _used_by(db, tenant_id, rows)
    out = []
    for r in rows:
        gid = str(r["id"])
        made_by = creators.get(str(r.get("created_by")))
        try:
            if (r.get("kind") or "picked") == "rule":
                shaped = _full_shape(db, ctx, r, made_by)
            else:
                shaped = _shape(r, counts.get(gid, 0), _count(db, ctx, gid, opted_out_only=True), None, made_by)
        except Exception as e:  # e.g. total_spent_paise missing before migration 333: one group, not the whole list
            logger.warning("Groups: count for group %s failed: %s", gid, e)
            shaped = _shape(r, 0, 0, None, made_by, _has_permission(ctx, "deals.view"))
            shaped["count_unknown"] = True
        shaped["used_by"] = used.get(gid, [])
        out.append(shaped)
    return out


@router.post("")
def create_group(body: NewGroupIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if _name_taken(db, tenant_id, body.name):
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
    if body.rule and has_spend(body.rule.as_dict()) and not _has_permission(ctx, "deals.view"):
        raise HTTPException(status_code=403, detail=SPEND_NEEDS_DEALS)
    try:
        res = db.table("customer_groups").insert({
            "tenant_id": tenant_id,
            "name": body.name,
            "kind": "rule" if body.rule else "picked",
            "rule": body.rule.as_dict() if body.rule else None,
            "created_by": ctx.get("user_id"),
        }).execute()
    except Exception as e:
        if "23505" in str(e):
            raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
        raise
    return _full_shape(db, ctx, res.data[0])


def _collect_chat_lead_ids(db, ctx: dict, body: FromChatsIn) -> list[str]:
    """Every lead the Chats list would show for this tab + search + filters, page by page through
    the same SQL function the list uses (so the callers' own-leads rule and every filter apply).
    Refuses (400) when more than FROM_CHATS_MAX match, rather than quietly saving part of them."""
    params = _filter_params(
        ctx, q=body.q, channels=body.channels, segments=body.segments, results=body.results,
        came_from=body.came_from, handled_by=body.handled_by, waiting=body.waiting,
        since=body.since, tag_id=body.tag_id,
    )
    params["p_view"] = _view(body.view, None)
    ids: dict[str, None] = {}
    offset = 0
    while True:
        rows = db.rpc("get_inbox_chats", {**params, "p_limit": _FROM_CHATS_PAGE, "p_offset": offset}).execute().data or []
        if not rows:
            break
        total = int(rows[0].get("total", 0))
        if total > FROM_CHATS_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"{total:,} chats match, and a group can hold up to {FROM_CHATS_MAX:,}. "
                       "Narrow the filters and try again.",
            )
        for r in rows:
            if r.get("lead_id"):
                ids[str(r["lead_id"])] = None
        offset += len(rows)
        if offset >= total:
            break
    return list(ids)


@router.post("/from-chats")
def create_group_from_chats(body: FromChatsIn, ctx: dict = Depends(require_leads_manage)):
    """Chats > Filter > Save as a group: a fixed (picked) group holding every chat that matches
    the current tab, search and filters, not just the page on screen."""
    if not _has_permission(ctx, "conversations.view"):
        # The list behind this is the Chats list: only people who may see Chats may save from it.
        raise HTTPException(status_code=403, detail="Permission required: conversations.view")
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    if _name_taken(db, tenant_id, body.name):
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
    candidates = _collect_chat_lead_ids(db, ctx, body)
    lead_ids = sorted(_live_lead_ids(db, tenant_id, _valid_ids(candidates)))
    if not lead_ids:
        raise HTTPException(status_code=400, detail="No chats match these filters, so there is nothing to save")
    try:
        res = db.table("customer_groups").insert({
            "tenant_id": tenant_id,
            "name": body.name,
            "kind": "picked",
            "rule": None,
            "created_by": ctx.get("user_id"),
        }).execute()
    except Exception as e:
        if "23505" in str(e):
            raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
        raise
    group = res.data[0]
    gid = str(group["id"])
    try:
        for i in range(0, len(lead_ids), _MEMBER_CHUNK):
            db.table("customer_group_members").upsert(
                [{"group_id": gid, "lead_id": lid, "tenant_id": tenant_id, "added_by": ctx.get("user_id")}
                 for lid in lead_ids[i:i + _MEMBER_CHUNK]],
                on_conflict="group_id,lead_id",
                ignore_duplicates=True,
            ).execute()
    except Exception:
        # No half-filled group: take the empty shell away and let the caller try again.
        try:
            db.table("customer_groups").delete().eq("id", gid).eq("tenant_id", tenant_id).execute()
        except Exception as cleanup:
            logger.warning(f"Groups: could not remove group {gid} after a failed save from Chats: {cleanup}")
        raise
    return {**_full_shape(db, ctx, group), "added": len(lead_ids)}


@router.patch("/{group_id}")
def rename_group(group_id: UUID, body: GroupIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    group = _group_or_404(db, tenant_id, gid)
    if _name_taken(db, tenant_id, body.name, exclude_id=gid):
        raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
    try:
        db.table("customer_groups").update({
            "name": body.name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", gid).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        if "23505" in str(e):
            raise HTTPException(status_code=409, detail=DUPLICATE_NAME)
        raise
    return _full_shape(db, ctx, {**group, "name": body.name})


@router.put("/{group_id}/rule")
def update_rule(group_id: UUID, body: RuleIn, ctx: dict = Depends(require_leads_manage)):
    """Change what a group that fills itself looks for. Members follow by themselves."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    group = _group_or_404(db, tenant_id, gid)
    if group.get("kind") != "rule":
        raise HTTPException(status_code=400, detail="Only a group that fills itself has rules")
    rule = body.rule.as_dict()
    if not _has_permission(ctx, "deals.view") and (has_spend(rule) or has_spend(parse_rule(group.get("rule")))):
        # A spend rule is a rupee figure: not for people who cannot see money, and they cannot change one either.
        raise HTTPException(status_code=403, detail=SPEND_NEEDS_DEALS)
    db.table("customer_groups").update({
        "rule": rule,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", gid).eq("tenant_id", tenant_id).execute()
    return _full_shape(db, ctx, {**group, "rule": rule})


@router.delete("/{group_id}")
def delete_group(group_id: UUID, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    _group_or_404(db, tenant_id, gid)
    # A follow-up aimed at this group would turn into "send to everybody" if the group vanished
    # (the link is ON DELETE SET NULL), so the group stays until that follow-up is changed.
    try:
        in_use = (db.table("reengagement_steps").select("id").eq("tenant_id", tenant_id)
                  .eq("target_group_id", gid).limit(1).execute()).data or []
    except Exception:
        in_use = []  # column not there yet: no follow-up can point at a group
    if in_use:
        raise HTTPException(status_code=409, detail="An auto-message is using this group. Change or delete that auto-message first.")
    # customer_group_members rows go with it (ON DELETE CASCADE).
    db.table("customer_groups").delete().eq("id", gid).eq("tenant_id", tenant_id).execute()
    return {"deleted": True}


@router.post("/{group_id}/send-to-calling")
def send_group_to_calling(group_id: UUID, ctx: dict = Depends(require_leads_manage)):
    """Give this group's open people to callers (Call IQ > Leads to call). Same result line as All people:
    {added, already, said_stop, bought, closed, not_found, no_callers, added_ids}."""
    from app.services import customer_calling
    from app.services.reach_audience import GroupNotFound, resolve_group

    db = get_supabase()
    gid = str(group_id)
    _group_or_404(db, ctx["tenant_id"], gid)
    try:
        resolved = resolve_group(db, ctx, gid)
    except GroupNotFound:
        raise HTTPException(status_code=404, detail="Group not found")
    # Calling is for everyone in the group, not only people WhatsApp can reach: the member list behind
    # resolve_group hides people with no WhatsApp (bounced numbers, Instagram-only), and those are exactly
    # who a caller should phone. A picked group reads its members straight from the table; send_to_calling
    # itself sorts out Said stop, closed, bought and deleted people.
    group = resolved["group"]
    if group["kind"] == "picked":
        rows = (db.table("customer_group_members").select("lead_id").eq("group_id", gid)
                .eq("tenant_id", ctx["tenant_id"]).limit(customer_calling.MAX_PEOPLE).execute().data or [])
        lead_ids = [str(r["lead_id"]) for r in rows]
        return customer_calling.send_to_calling(db, ctx["tenant_id"], lead_ids, reason="group", group_id=gid)
    # A self-filling group: its rules are the Customers filters, which already hide bounced numbers.
    from app.routes.leads import LeadFilters, _fetch_all, _filtered_leads_query
    filters = LeadFilters(group_id=gid)
    memo: dict = {}
    live = (_fetch_all(lambda: _filtered_leads_query(db, ctx, filters, columns="id", memo=memo),
                       order_by=("created_at", "id"))
            if _filtered_leads_query(db, ctx, filters, columns="id", memo=memo) is not None else [])
    result = customer_calling.send_to_calling(db, ctx["tenant_id"], [r["id"] for r in live], reason="group", group_id=gid)
    # That list leaves Said stop people out; count them so the line reads like the others.
    result["said_stop"] = int(result.get("said_stop") or 0) + int(resolved.get("stopped") or 0)
    return result


@router.post("/{group_id}/members")
def add_members(group_id: UUID, body: LeadIdsIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    group = _group_or_404(db, tenant_id, gid)
    if group.get("kind") == "rule":
        raise HTTPException(status_code=400, detail="This group fills itself")
    accepted = sorted(_live_lead_ids(db, tenant_id, _valid_ids(body.lead_ids)))
    if accepted:
        db.table("customer_group_members").upsert(
            [{"group_id": gid, "lead_id": lid, "tenant_id": tenant_id, "added_by": ctx.get("user_id")}
             for lid in accepted],
            on_conflict="group_id,lead_id",
            ignore_duplicates=True,
        ).execute()
    return {"added": len(accepted)}


@router.delete("/{group_id}/members")
def remove_members(group_id: UUID, body: LeadIdsIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    gid = str(group_id)
    _group_or_404(db, tenant_id, gid)
    ids = _valid_ids(body.lead_ids)
    removed = 0
    if ids:
        res = (db.table("customer_group_members").delete()
               .eq("group_id", gid).eq("tenant_id", tenant_id).in_("lead_id", ids).execute())
        removed = len(res.data or [])
    return {"removed": removed}
