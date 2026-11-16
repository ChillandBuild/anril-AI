import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.services.actor import actor_name
from app.dependencies.tenant import get_tenant_and_role, require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
require_conversations_view = require_permission("conversations.view")
require_conversations_reply = require_permission("conversations.reply")

IST_OFFSET = timedelta(hours=5, minutes=30)


def _ist_today_start_utc() -> datetime:
    """Midnight IST expressed as a UTC datetime -- tenant is IST, dashboard
    labels this "Escalations" card as a same-day count."""
    now_ist = datetime.now(timezone.utc) + IST_OFFSET
    midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_ist - IST_OFFSET


@router.get("/")
def list_handovers(ctx: dict = Depends(require_conversations_view)):
    db = get_supabase()
    query = (
        db.table("chat_handovers")
        .select("id, lead_id, assigned_to, reason, status, opened_at, leads(name, phone, segment, source, tg_username, ig_user_id, fb_user_id)")
        .eq("tenant_id", ctx["tenant_id"])
        .eq("status", "pending")
        .order("opened_at", desc=True)
        .limit(50)
    )
    # Shared escalation pool: all tenant users (admin + every telecaller) see all
    # pending handovers, so whoever is free can pick one up and resolve it.
    try:
        rows = query.execute()
    except Exception as e:
        logger.warning(f"chat_handovers list failed (transient?): {e}")
        return {"data": []}

    handovers = rows.data or []

    # Attach caller names in one batch lookup
    caller_ids = list({h["assigned_to"] for h in handovers if h.get("assigned_to")})
    caller_map: dict = {}
    if caller_ids:
        try:
            callers = db.table("callers").select("id, name").in_("id", caller_ids).execute()
            caller_map = {c["id"]: c["name"] for c in (callers.data or [])}
        except Exception:
            pass
    for h in handovers:
        h["caller_name"] = caller_map.get(h.get("assigned_to")) if h.get("assigned_to") else None

    return {"data": handovers}


@router.get("/count")
def handover_count(
    today_only: bool = Query(False),
    ctx: dict = Depends(require_conversations_view),
):
    """Sidebar badge (and the conversations-page tab badge) poll this every
    60s for the full pending backlog. Swallow transient Supabase HTTP/2
    disconnects (RemoteProtocolError) so a flaky connection doesn't spam
    500s into the UI — the next poll will succeed.

    `today_only` scopes the count to escalations opened since IST midnight,
    for the dashboard home "Escalations" card, which sits alongside other
    same-day KPIs and shouldn't include the all-time backlog."""
    db = get_supabase()
    query = (
        db.table("chat_handovers")
        .select("id", count="exact")
        .eq("tenant_id", ctx["tenant_id"])
        .eq("status", "pending")
    )
    # Shared escalation pool: all tenant users (admin + every telecaller) see all
    # pending handovers, so whoever is free can pick one up and resolve it.
    if today_only:
        query = query.gte("opened_at", _ist_today_start_utc().isoformat())
    try:
        result = query.execute()
    except Exception as e:
        logger.warning(f"chat_handovers count failed (transient?): {e}")
        return {"count": 0}
    return {"count": result.count or 0}


def _resolver_name(db, ctx: dict) -> str | None:
    """Snapshotted at resolve time so the history survives a caller being renamed or removed."""
    return actor_name(db, ctx)


def _duration_seconds(opened_at: str | None, resolved_at: str | None) -> int | None:
    if not opened_at or not resolved_at:
        return None
    try:
        a = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        b = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = int((b - a).total_seconds())
    return delta if delta >= 0 else None


@router.get("/history")
def handover_history(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    resolver: str | None = Query(None),
    reason: str | None = Query(None),
    ctx: dict = Depends(require_conversations_view),
):
    """Resolved escalations, newest first. Powers the History tab.

    Search is resolved against `leads` first rather than against the embedded
    resource, because filtering an embedded PostgREST resource narrows the join
    and not the parent rows -- which would silently return handovers with a
    null `leads` object instead of excluding them."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    base_select = (
        "id, lead_id, assigned_to, reason, status, opened_at, resolved_at, "
        "resolved_by, resolved_by_name, "
        "leads(name, phone, segment, source, tg_username, ig_user_id, fb_user_id)"
    )

    def _scoped(select: str, count: str | None = None):
        query = db.table("chat_handovers").select(select, count=count) if count else \
            db.table("chat_handovers").select(select)
        query = query.eq("tenant_id", tenant_id).eq("status", "resolved")
        if resolver:
            query = query.eq("resolved_by_name", resolver)
        if reason:
            query = query.eq("reason", reason)
        return query

    lead_ids: list[str] | None = None
    if q and q.strip():
        # PostgREST's or_() takes a comma-separated filter list wrapped in
        # parens, so those characters in the term would corrupt the expression.
        term = "".join(c for c in q.strip() if c not in ",()*")
        try:
            matches = (
                db.table("leads")
                .select("id")
                .eq("tenant_id", tenant_id)
                .or_(f"name.ilike.%{term}%,phone.ilike.%{term}%")
                .limit(500)
                .execute()
            )
            lead_ids = [r["id"] for r in (matches.data or [])]
        except Exception as e:
            logger.warning(f"handover history lead search failed: {e}")
            lead_ids = []

    try:
        rows_query = _scoped(base_select, count="exact")
        if lead_ids is not None:
            if not lead_ids:
                return {"data": [], "total": 0, "stats": _empty_history_stats()}
            rows_query = rows_query.in_("lead_id", lead_ids)
        rows = (
            rows_query.order("resolved_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception as e:
        logger.warning(f"chat_handovers history failed (transient?): {e}")
        return {"data": [], "total": 0, "stats": _empty_history_stats()}

    handovers = rows.data or []
    for h in handovers:
        h["duration_seconds"] = _duration_seconds(h.get("opened_at"), h.get("resolved_at"))

    return {
        "data": handovers,
        "total": rows.count or 0,
        "stats": _history_stats(db, tenant_id),
    }


def _empty_history_stats() -> dict:
    return {"total": 0, "median_seconds": None, "top_resolver": None,
            "top_resolver_count": 0, "top_reason": None, "resolvers": [], "reasons": []}


def _history_stats(db, tenant_id: str) -> dict:
    """Summary across all resolved handovers for this tenant. The volume here is
    tens of rows, not millions, so a single scan beats four aggregate round
    trips -- revisit if a tenant ever passes a few thousand resolutions."""
    try:
        rows = (
            db.table("chat_handovers")
            .select("opened_at, resolved_at, resolved_by_name, reason")
            .eq("tenant_id", tenant_id)
            .eq("status", "resolved")
            .order("resolved_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"handover history stats failed: {e}")
        return _empty_history_stats()

    durations = sorted(
        d for d in (_duration_seconds(r.get("opened_at"), r.get("resolved_at")) for r in rows)
        if d is not None
    )
    median = None
    if durations:
        mid = len(durations) // 2
        median = durations[mid] if len(durations) % 2 else (durations[mid - 1] + durations[mid]) // 2

    resolver_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for r in rows:
        name = r.get("resolved_by_name")
        if name:
            resolver_counts[name] = resolver_counts.get(name, 0) + 1
        rsn = r.get("reason")
        if rsn:
            reason_counts[rsn] = reason_counts.get(rsn, 0) + 1

    top_resolver = max(resolver_counts.items(), key=lambda kv: kv[1], default=None)
    top_reason = max(reason_counts.items(), key=lambda kv: kv[1], default=None)

    return {
        "total": len(rows),
        "median_seconds": median,
        "top_resolver": top_resolver[0] if top_resolver else None,
        "top_resolver_count": top_resolver[1] if top_resolver else 0,
        "top_reason": top_reason[0] if top_reason else None,
        "resolvers": sorted(resolver_counts.keys()),
        "reasons": sorted(reason_counts.keys()),
    }


class AssignBody(BaseModel):
    caller_id: str


@router.patch("/{handover_id}/assign")
def assign_handover(handover_id: str, body: AssignBody, ctx: dict = Depends(require_conversations_reply)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    caller = (
        db.table("callers")
        .select("id")
        .eq("id", body.caller_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not caller.data:
        raise HTTPException(status_code=404, detail="Caller not found")
    result = (
        db.table("chat_handovers")
        .update({"assigned_to": body.caller_id})
        .eq("id", handover_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Handover not found")
    try:
        from app.services.notify import clear_pool_notifications_for_lead
        lead_id = result.data[0].get("lead_id")
        if lead_id:
            clear_pool_notifications_for_lead(tenant_id, lead_id, db=db)
    except Exception:
        pass
    return {"assigned": True}


@router.patch("/{handover_id}/resolve")
def resolve_handover(handover_id: str, ctx: dict = Depends(require_conversations_reply)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    result = db.table("chat_handovers").update({
        "status": "resolved",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "resolved_by": ctx["user_id"],
        "resolved_by_name": _resolver_name(db, ctx),
    }).eq("id", handover_id).eq("tenant_id", tenant_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Handover not found")

    lead_id = result.data[0].get("lead_id")
    if lead_id:
        try:
            from app.services.notify import clear_pool_notifications_for_lead
            clear_pool_notifications_for_lead(tenant_id, lead_id, db=db)
        except Exception:
            pass
        remaining = (
            db.table("chat_handovers")
            .select("id", count="exact")
            .eq("lead_id", lead_id)
            .eq("status", "pending")
            .execute()
        )
        if not (remaining.count or 0):
            # ai_enabled is deliberately not written here. Escalation no longer
            # disables it, so setting it True would clobber a manual admin mute.
            db.table("leads").update({
                "needs_human_attention": False,
                "escalation_reason": None,
            }).eq("id", lead_id).eq("tenant_id", tenant_id).execute()

    return {"resolved": True}


@router.patch("/{handover_id}/reopen")
def reopen_handover(handover_id: str, ctx: dict = Depends(require_conversations_reply)):
    """Backs the undo toast on Resolve, and the Reopen action in History.
    Clears the attribution so a re-resolve records whoever actually closed it."""
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    result = db.table("chat_handovers").update({
        "status": "pending",
        "resolved_at": None,
        "resolved_by": None,
        "resolved_by_name": None,
    }).eq("id", handover_id).eq("tenant_id", tenant_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Handover not found")

    row = result.data[0]
    lead_id = row.get("lead_id")
    if lead_id:
        db.table("leads").update({
            "needs_human_attention": True,
            "escalation_reason": row.get("reason"),
        }).eq("id", lead_id).eq("tenant_id", tenant_id).execute()

    return {"reopened": True}
