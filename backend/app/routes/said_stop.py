"""Customers > Said stop: the list, its three cards, and adding / removing by hand.

The rules (what stops, what still goes, how people get on it) live in
services/said_stop.py. Every query is scoped to the caller's tenant; a telecaller sees
only the people assigned to them, as on All people.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.supabase import get_supabase
from app.routes.customer_groups import _valid_ids
from app.routes.leads import _fetch_all, _in_scopes, _parse_ts, require_leads_manage, require_leads_view
from app.services import said_stop
from app.services.actor import actor_name

logger = logging.getLogger(__name__)

router = APIRouter()

_WITH_SOURCE = "id,name,phone,opted_out,do_not_call,opted_out_at,opted_out_source,opted_out_detail"
_WITHOUT_SOURCE = "id,name,phone,opted_out,do_not_call,opted_out_at"
RATE_DAYS = 30
WEEK_DAYS = 7


class LeadIdsIn(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=1000)


def _stopped_rows(db, ctx: dict) -> list[dict]:
    """Said stop people (opted_out) plus people a caller marked Don't call (do_not_call), each once."""
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
    return rows


def _dnc_only(row: dict) -> bool:
    """On the list only because a caller marked Don't call: they still get messages."""
    return bool(row.get("do_not_call")) and not row.get("opted_out")


def _source(row: dict):
    return said_stop.DO_NOT_CALL_SOURCE if _dnc_only(row) else row.get("opted_out_source")


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
    rows.sort(key=lambda r: _parse_ts(r.get("opted_out_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    week_start = now - timedelta(days=WEEK_DAYS)
    rate_start = now - timedelta(days=RATE_DAYS)
    this_week: dict[str, int] = {}
    in_rate_window = 0
    for r in rows:
        at = _parse_ts(r.get("opted_out_at"))
        if at and at >= week_start:
            key = _source(r) or "unknown"
            this_week[key] = this_week.get(key, 0) + 1
        if at and at >= rate_start:
            in_rate_window += 1

    messaged = _messaged_first_count(db, ctx["tenant_id"], rate_start.isoformat())
    return {
        "people": [{
            "id": str(r["id"]),
            "name": r.get("name"),
            "phone": r.get("phone"),
            "opted_out_at": r.get("opted_out_at"),
            "source": _source(r),
            "source_label": said_stop.DO_NOT_CALL_LABEL if _dnc_only(r) else None,
            "detail": r.get("opted_out_detail"),
            "do_not_call": bool(r.get("do_not_call")),
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
