"""Customers > Said stop: the list, its three cards, and adding / removing by hand.

The rules (what stops, what still goes, how people get on it) live in
services/said_stop.py. Every query is scoped to the caller's tenant; a telecaller sees
only the people assigned to them, as on All people.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.routes.customer_groups import _valid_ids
from app.routes.leads import _fetch_all, _in_scopes, _parse_ts, require_leads_manage, require_leads_view
from app.services import said_stop
from app.services.actor import actor_name

logger = logging.getLogger(__name__)

router = APIRouter()

_WITH_SOURCE = "id,name,phone,opted_out,do_not_call,opted_out_at,opted_out_source,opted_out_detail,blocked_at"
_WITHOUT_SOURCE = "id,name,phone,opted_out,do_not_call,opted_out_at,blocked_at"
RATE_DAYS = 30
WEEK_DAYS = 7


class LeadIdsIn(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=1000)


def _stopped_rows(db, ctx: dict) -> list[dict]:
    """Said stop people (opted_out), people a caller marked Don't call (do_not_call) and people staff
    blocked (blocked_at), each once."""
    tenant_id = ctx["tenant_id"]

    def build(columns: str, flag: str):
        def _q():
            q = (db.table("leads").select(columns).eq("tenant_id", tenant_id)
                 .eq(flag, True).is_("deleted_at", "null"))
            if ctx.get("role") == "caller" and ctx.get("caller_id"):
                q = q.eq("assigned_to", ctx["caller_id"])
            return q
        return _q

    try:
        rows = _fetch_all(build(_WITH_SOURCE, "opted_out"))
        columns = _WITH_SOURCE
    except Exception as e:
        # Migration 281 not applied yet: the list still works, every row reads "before we tracked how".
        logger.warning(f"Said stop: reading without opted_out_source ({e})")
        columns = _WITHOUT_SOURCE
        rows = _fetch_all(build(columns, "opted_out"))
    seen = {str(r["id"]) for r in rows}
    for r in _fetch_all(build(columns, "do_not_call")):
        if str(r["id"]) not in seen:
            rows.append(r)
            seen.add(str(r["id"]))

    def blocked_q():
        q = (db.table("leads").select(columns).eq("tenant_id", tenant_id)
             .not_.is_("blocked_at", "null").is_("deleted_at", "null"))
        if ctx.get("role") == "caller" and ctx.get("caller_id"):
            q = q.eq("assigned_to", ctx["caller_id"])
        return q

    for r in _fetch_all(blocked_q):
        if str(r["id"]) not in seen:
            rows.append(r)
    return rows


def _dnc_only(row: dict) -> bool:
    """On the list only because a caller marked Don't call: they still get messages."""
    return bool(row.get("do_not_call")) and not row.get("opted_out")


def _blocked_only(row: dict) -> bool:
    """On the list only because staff blocked them (not said stop, not Don't call)."""
    return bool(row.get("blocked_at")) and not row.get("opted_out") and not row.get("do_not_call")


def _source(row: dict):
    if _dnc_only(row):
        return said_stop.DO_NOT_CALL_SOURCE
    if _blocked_only(row):
        return said_stop.BLOCKED_SOURCE
    return row.get("opted_out_source")


def _when(row: dict):
    """When they went on the list: the Said stop date, or the block date for a blocked-only person."""
    return row.get("blocked_at") if _blocked_only(row) else row.get("opted_out_at")


def _messaged_first_count(db, tenant_id: str, since_iso: str) -> int:
    """People a broadcast went to in the window: the stop rate's denominator."""
    rows = _fetch_all(lambda: db.table("broadcast_recipients").select("id,lead_id")
                      .eq("tenant_id", tenant_id).gte("created_at", since_iso))
    return len({r["lead_id"] for r in rows if r.get("lead_id")})


@router.get("")
def list_said_stop(ctx: dict = Depends(require_leads_view)):
    db = get_supabase()
    now = datetime.now(timezone.utc)
    rows = _stopped_rows(db, ctx)
    rows.sort(key=lambda r: _parse_ts(_when(r)) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    week_start = now - timedelta(days=WEEK_DAYS)
    rate_start = now - timedelta(days=RATE_DAYS)
    this_week: dict[str, int] = {}
    in_rate_window = 0
    for r in rows:
        at = _parse_ts(_when(r))
        if at and at >= week_start:
            key = _source(r) or "unknown"
            this_week[key] = this_week.get(key, 0) + 1
        # A block is not an answer to a message, so it stays out of the stop rate.
        if at and at >= rate_start and not _blocked_only(r):
            in_rate_window += 1

    messaged = _messaged_first_count(db, ctx["tenant_id"], rate_start.isoformat())
    return {
        "people": [{
            "id": str(r["id"]),
            "name": r.get("name"),
            "phone": r.get("phone"),
            "opted_out_at": _when(r),
            "source": _source(r),
            "source_label": (said_stop.DO_NOT_CALL_LABEL if _dnc_only(r)
                             else said_stop.BLOCKED_LABEL if _blocked_only(r) else None),
            "detail": r.get("opted_out_detail"),
            "do_not_call": bool(r.get("do_not_call")),
            "blocked": bool(r.get("blocked_at")),
        } for r in rows],
        "summary": {
            "on_list": len(rows),
            "this_week": sum(this_week.values()),
            "this_week_by_source": this_week,
            "stopped_in_window": in_rate_window,
            "messaged_in_window": messaged,
            # None when nobody was messaged: a rate of nothing is not 0%.
            "stop_rate": round(in_rate_window / messaged * 100, 1) if messaged else None,
            "window_days": RATE_DAYS,
        },
    }


@router.post("/add")
def add_to_said_stop(body: LeadIdsIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    ids = _valid_ids(body.lead_ids)
    added = 0
    name = actor_name(db, ctx) if ids else None
    for scope in _in_scopes(ids):
        added += said_stop.add_by_hand(db, ctx["tenant_id"], scope or [], ctx.get("user_id"), name)
    return {"added": added}


class NumberIn(BaseModel):
    phone: str = Field(min_length=1, max_length=30)
    name: str | None = Field(default=None, max_length=80)


@router.post("/add-number")
def add_number_to_said_stop(body: NumberIn, ctx: dict = Depends(require_leads_manage)):
    """Add a number that may never have messaged you. A person already known is found by number and
    added through said_stop.add_by_hand. A brand-new number gets a bare record that is on Said stop
    from the start: no score events, no auto-assign, no follow-ups, never an inbound lead (so nothing
    can message them). A team member whose people are limited to their own (caller) adds only their own."""
    from app.routes.upload import _normalize_phone
    phone = _normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="That number does not look right. Check it and try again.")
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    own_only = ctx.get("role") == "caller" and ctx.get("caller_id")
    name = " ".join((body.name or "").split()) or None
    existing = (db.table("leads").select("id,deleted_at,opted_out,assigned_to").eq("tenant_id", tenant_id)
                .eq("phone", phone).limit(1).execute().data or [])
    # A telecaller limited to their own people adds only those. Any other number (someone else's customer
    # OR a brand-new one) gets the same answer, so typing numbers can't reveal who is a customer.
    if own_only and (not existing or str(existing[0].get("assigned_to") or "") != str(ctx["caller_id"])):
        raise HTTPException(status_code=403, detail="You can add only your own customers here. Ask the owner to add this number.")
    created = False
    if existing:
        lead = existing[0]
        lead_id = str(lead["id"])
        if lead.get("deleted_at") and not lead.get("opted_out"):
            # Bring a removed record back only because it is going onto Said stop now (so the list shows it).
            db.table("leads").update({"deleted_at": None}).eq("id", lead_id).eq("tenant_id", tenant_id).execute()
        if name:
            db.table("leads").update({"name": name}).eq("id", lead_id).eq("tenant_id", tenant_id) \
                .is_("name", "null").execute()
    else:
        from app.services.segmentation import new_lead_score_and_segment
        score, segment = new_lead_score_and_segment(tenant_id)
        row = {"phone": phone, "source": "manual", "score": score, "segment": segment, "tenant_id": tenant_id}
        if name:
            row["name"] = name
        lead_id = str(db.table("leads").insert(row).execute().data[0]["id"])
        created = True
    staff = actor_name(db, ctx)
    try:
        added = said_stop.add_by_hand(db, tenant_id, [lead_id], ctx.get("user_id"), staff)
    except Exception:
        if created:
            try:
                db.table("leads").delete().eq("id", lead_id).eq("tenant_id", tenant_id).execute()
            except Exception as cleanup:
                logger.warning(f"Said stop: could not undo the record made for a new number: {cleanup}")
        raise
    logger.info(f"Said stop: number added by hand (new record: {created}) by user {ctx.get('user_id')} tenant {tenant_id}")
    return {"added": added, "created": created, "already_on_list": added == 0}


@router.post("/remove")
def remove_from_said_stop(body: LeadIdsIn, ctx: dict = Depends(require_leads_manage)):
    db = get_supabase()
    ids = _valid_ids(body.lead_ids)
    removed = 0
    for scope in _in_scopes(ids):
        removed += said_stop.remove_by_hand(db, ctx["tenant_id"], scope or [])
    logger.info(f"Said stop: {removed} removed by hand by user {ctx.get('user_id')} tenant {ctx['tenant_id']}")
    if removed:
        from app.services.audit_log import record_audit_event
        record_audit_event(db, tenant_id=ctx["tenant_id"], actor_user_id=ctx.get("user_id"), actor_role=ctx.get("role"),
                           action="said_stop.remove", target_type="leads",
                           metadata={"removed": removed, "lead_ids": [str(i) for i in ids][:200]})
    return {"removed": removed}
