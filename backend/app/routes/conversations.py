import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from app.config_dynamic import get_setting
from app.db.supabase import get_supabase
from app.dependencies.tenant import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
require_conversations_view = require_permission("conversations.view")

# List tabs on the Chats page. "inbox" is every active chat, the ones waiting on a person
# first (the SQL function calls that ordering "needs_you"). The "Needs you" tab itself is the
# handover page (chat_handovers), not this list. Old folder names still work for older clients.
_VIEW_TO_SQL = {"inbox": "needs_you", "ai_handling": "ai_handling", "archived": "archived", "blocked": "blocked"}
_FOLDER_TO_VIEW = {"chats": "inbox", "archived": "archived", "blocked": "blocked"}

_CHANNELS = {"whatsapp", "instagram", "facebook", "telegram"}
_SEGMENTS = {"A", "B", "C", "D"}
_RESULTS = {"none", "booked", "paid", "lost"}
_CAME_FROM = {"meta_ads", "direct", "website", "indiamart", "justdial", "upload", "manual"}
_WAITING = {"unread", "over_1h", "payment_pending"}


def _csv(value: str | None, allowed: set[str] | None = None, name: str = "") -> list[str] | None:
    """A comma list from the query string; unknown values are a 400, not silently ignored,
    so a typo can never quietly widen the list."""
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    if allowed is not None:
        bad = [v for v in items if v not in allowed]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown {name}: {', '.join(bad)}")
    return items or None


def _handled_by(value: str | None) -> list[str] | None:
    items = _csv(value)
    if not items:
        return None
    for v in items:
        if v in ("ai", "nobody"):
            continue
        try:
            UUID(v)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown handled_by: {v}")
    return items


def _filter_params(
    ctx: dict,
    *,
    q: str | None,
    channels: str | None,
    segments: str | None,
    results: str | None,
    came_from: str | None,
    handled_by: str | None,
    waiting: str | None,
    since: datetime | None,
    tag_id: UUID | None,
) -> dict:
    search = q.strip() if q else None
    tenant_id = ctx["tenant_id"]
    return {
        "p_tenant_id": tenant_id,
        "p_caller_id": ctx["caller_id"] if ctx.get("role") == "caller" and ctx.get("caller_id") else None,
        "p_search": search or None,
        # Same rule as the reply gate: only the literal "false" turns the AI off for the account.
        "p_ai_master": get_setting("ai_auto_reply_enabled", fallback="true", tenant_id=tenant_id) != "false",
        "p_channels": _csv(channels, _CHANNELS, "channel"),
        "p_segments": _csv(segments, _SEGMENTS, "interest"),
        "p_results": _csv(results, _RESULTS, "result"),
        "p_came_from": _csv(came_from, _CAME_FROM, "came from"),
        "p_handled_by": _handled_by(handled_by),
        "p_waiting": _csv(waiting, _WAITING, "waiting"),
        "p_since": since.isoformat() if since else None,
        "p_tag_id": str(tag_id) if tag_id else None,
    }


def _view(view: str | None, folder: str | None) -> str:
    """The SQL function's p_view for a tab name."""
    if view:
        if view not in _VIEW_TO_SQL:
            raise HTTPException(status_code=400, detail="Unknown view")
        return _VIEW_TO_SQL[view]
    return _VIEW_TO_SQL[_FOLDER_TO_VIEW.get(folder or "chats", "inbox")]


@router.get("")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    view: str | None = Query(default=None),
    folder: str | None = Query(default=None, pattern="^(chats|archived|blocked)$"),
    q: str | None = Query(default=None, max_length=100),
    channels: str | None = Query(default=None, max_length=100),
    segments: str | None = Query(default=None, max_length=20),
    results: str | None = Query(default=None, max_length=60),
    came_from: str | None = Query(default=None, max_length=120),
    handled_by: str | None = Query(default=None, max_length=2000),
    waiting: str | None = Query(default=None, max_length=60),
    since: datetime | None = Query(default=None),
    tag_id: UUID | None = Query(default=None),
    ctx: dict = Depends(require_conversations_view),
):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]

    # Every filter lives inside the SQL function (migration 272), so `total` and the
    # page offsets count exactly the rows this tab shows -- never filter after the RPC.
    params = _filter_params(
        ctx, q=q, channels=channels, segments=segments, results=results, came_from=came_from,
        handled_by=handled_by, waiting=waiting, since=since, tag_id=tag_id,
    )
    params.update({"p_limit": limit, "p_offset": offset, "p_view": _view(view, folder)})
    rows = db.rpc("get_inbox_chats", params).execute().data or []
    if not rows:
        return {"leads": [], "total": 0}

    total = int(rows[0].get("total", 0))
    lead_ids = [r["lead_id"] for r in rows if r.get("lead_id")]
    row_by_id = {r["lead_id"]: r for r in rows if r.get("lead_id")}
    if not lead_ids:
        return {"leads": [], "total": 0}

    # Opted-out leads who actually reply must stay visible — the RPC only returns
    # leads with real conversation activity (an inbound reply or a non-template
    # outbound), so we keep them here and let the UI badge them as opted-out.
    lead_rows = (
        db.table("leads")
        .select("*")
        .in_("id", lead_ids)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .execute()
    )
    lead_map = {l["id"]: l for l in (lead_rows.data or [])}
    last_reply_map = {lid: row_by_id[lid].get("last_reply_at") for lid in lead_ids}
    last_sender = _last_message_senders(db, tenant_id, last_reply_map)
    reasons = _open_handover_reasons(db, tenant_id, lead_ids)
    wants = _latest_deal_summaries(db, tenant_id, lead_ids)

    leads = []
    for lid in lead_ids:
        if lid not in lead_map:
            continue
        row = row_by_id[lid]
        lead = dict(lead_map[lid])
        lead["last_reply_at"] = row.get("last_reply_at")
        lead["last_message_content"] = row.get("last_message_content")
        # Who sent the last message: lets the inbox say "AI replied" only when it did.
        sender = last_sender.get(lid)
        lead["last_message_direction"] = sender["direction"] if sender else None
        lead["last_message_is_ai"] = bool(sender and sender.get("is_ai_generated")) if sender else None
        lead["inbox_group"] = row.get("inbox_group")
        lead["waiting_since"] = row.get("waiting_since")
        lead["unread_count"] = row.get("unread_count") or 0
        lead["needs_reason"] = reasons.get(lid) or lead.get("escalation_reason")
        lead["wants"] = wants.get(lid)
        leads.append(lead)

    return {"leads": leads, "total": total}


@router.get("/counts")
async def conversation_counts(
    view: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    channels: str | None = Query(default=None, max_length=100),
    segments: str | None = Query(default=None, max_length=20),
    results: str | None = Query(default=None, max_length=60),
    came_from: str | None = Query(default=None, max_length=120),
    handled_by: str | None = Query(default=None, max_length=2000),
    waiting: str | None = Query(default=None, max_length=60),
    since: datetime | None = Query(default=None),
    tag_id: UUID | None = Query(default=None),
    ctx: dict = Depends(require_conversations_view),
):
    """Tab counts (Needs you, AI handling) and channel-chip counts under the same
    filters as the list, from the same SQL definition, so the numbers always match."""
    params = _filter_params(
        ctx, q=q, channels=channels, segments=segments, results=results, came_from=came_from,
        handled_by=handled_by, waiting=waiting, since=since, tag_id=tag_id,
    )
    params["p_view"] = _view(view, None)
    data = get_supabase().rpc("get_inbox_counts", params).execute().data
    return data or {"needs_you": 0, "ai_handling": 0, "all_active": 0, "channels": {}}


def _open_handover_reasons(db, tenant_id: str, lead_ids: list[str]) -> dict:
    """lead_id -> why the AI handed the chat to a person (the open handover's reason)."""
    try:
        rows = (
            db.table("chat_handovers")
            .select("lead_id,reason,opened_at")
            .eq("tenant_id", tenant_id)
            .eq("status", "pending")
            .in_("lead_id", lead_ids)
            .order("opened_at", desc=True)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"open handover lookup failed: {e}")
        return {}
    reasons: dict = {}
    for r in rows:
        if r.get("reason"):
            reasons.setdefault(r["lead_id"], r["reason"])
    return reasons


def _latest_deal_summaries(db, tenant_id: str, lead_ids: list[str]) -> dict:
    """lead_id -> {items, total_paise, stage} of the lead's newest deal that isn't lost:
    what the customer wants and for how much, for the inbox row."""
    try:
        deals = (
            db.table("deals")
            .select("id,lead_id,total_paise,stage,created_at")
            .eq("tenant_id", tenant_id)
            .in_("lead_id", lead_ids)
            .neq("stage", "lost")
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        ).data or []
        latest: dict = {}
        for d in deals:
            latest.setdefault(d["lead_id"], d)
        if not latest:
            return {}
        items = (
            db.table("deal_items")
            .select("deal_id,name")
            .eq("tenant_id", tenant_id)
            .in_("deal_id", [d["id"] for d in latest.values()])
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"deal summary lookup failed: {e}")
        return {}
    names: dict = {}
    for it in items:
        names.setdefault(it["deal_id"], []).append(it.get("name") or "")
    return {
        lid: {
            "items": ", ".join(n for n in names.get(d["id"], []) if n),
            "total_paise": d.get("total_paise") or 0,
            "stage": d.get("stage"),
        }
        for lid, d in latest.items()
    }


def _last_message_senders(db, tenant_id: str, last_reply_map: dict) -> dict:
    """lead_id -> {direction, is_ai_generated} of that lead's latest message.

    One query for the whole page: messages newer than the page's oldest activity,
    newest first, keeping the first row seen per lead. A lead whose last message
    falls outside the window is simply left out (the inbox then shows no sender tag)."""
    times = [t for t in last_reply_map.values() if t]
    if not times:
        return {}
    try:
        rows = (
            db.table("messages")
            .select("lead_id,direction,is_ai_generated,created_at")
            .eq("tenant_id", tenant_id)
            .in_("lead_id", list(last_reply_map.keys()))
            .gte("created_at", min(times))
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"last message sender lookup failed: {e}")
        return {}
    senders: dict = {}
    for r in rows:
        senders.setdefault(r["lead_id"], r)
    return senders
