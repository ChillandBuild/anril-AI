"""Customers > one customer's page: totals, everything that happened, and where we reach them.

Read-only. Built from what Anril already records: deals (orders and payments), the
booking on the lead, chats (messages, one line per day and channel), calls (call_logs),
broadcasts sent (broadcast_recipients), team notes, groups and Said stop. Scoped to the
caller's tenant; a telecaller sees only people assigned to them (404 otherwise).
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.db.supabase import get_supabase
from app.routes.leads import _PAGE, LeadFilters, _filtered_leads_query, _parse_ts, require_leads_view

logger = logging.getLogger(__name__)

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
_LEAD_COLUMNS = (
    "id,name,phone,source,segment,score,created_at,assigned_to,ad_name,converted_at,"
    "booked_at,booked_for,booking_note,lost_at,lost_reason,opted_out,opted_out_at,do_not_call,"
    "last_inbound_at,ai_enabled"
)
_STOP_COLUMNS = "opted_out_source,opted_out_detail"
# A long-running chat can hold thousands of lines; the page only needs counts per day.
_MAX_MESSAGES = 5000


def _lead_or_404(db, ctx: dict, lead_id: str) -> dict:
    rows = (db.table("leads").select(_LEAD_COLUMNS).eq("id", lead_id).eq("tenant_id", ctx["tenant_id"])
            .is_("deleted_at", "null").limit(1).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Customer not found")
    lead = rows[0]
    if ctx.get("role") == "caller" and ctx.get("caller_id") and lead.get("assigned_to") != ctx["caller_id"]:
        raise HTTPException(status_code=404, detail="Customer not found")
    try:
        extra = (db.table("leads").select(_STOP_COLUMNS).eq("id", lead_id)
                 .eq("tenant_id", ctx["tenant_id"]).limit(1).execute()).data or []
        lead.update(extra[0] if extra else {})
    except Exception:
        pass  # migration 281 not applied yet: no "how they stopped"
    return lead


def _names(db, table: str, column: str, tenant_id: str, ids: set) -> dict[str, str]:
    ids = {str(i) for i in ids if i}
    if not ids:
        return {}
    try:
        rows = (db.table(table).select(f"id,{column}").eq("tenant_id", tenant_id)
                .in_("id", sorted(ids)).execute()).data or []
    except Exception as e:
        logger.warning(f"Customer page: could not read {table} names: {e}")
        return {}
    return {str(r["id"]): r.get(column) for r in rows}


def _orders(db, tenant_id: str, lead_id: str) -> list[dict]:
    deals = (db.table("deals").select("id,deal_number,stage,source,total_paise,payment_method,lost_reason,"
                                      "created_at,won_at,lost_at,sold_by")
             .eq("tenant_id", tenant_id).eq("lead_id", lead_id).execute()).data or []
    if not deals:
        return []
    items = (db.table("deal_items").select("deal_id,name,qty").eq("tenant_id", tenant_id)
             .in_("deal_id", [d["id"] for d in deals]).execute()).data or []
    by_deal: dict[str, list[dict]] = {}
    for it in items:
        by_deal.setdefault(str(it["deal_id"]), []).append(it)
    sellers = _names(db, "callers", "name", tenant_id, {d.get("sold_by") for d in deals})
    for d in deals:
        lines = by_deal.get(str(d["id"]), [])
        d["items"] = [f"{it.get('name')}" + (f" × {it['qty']}" if (it.get("qty") or 1) > 1 else "") for it in lines]
        d["sold_by_name"] = sellers.get(str(d.get("sold_by"))) if d.get("sold_by") else None
    return deals


def _chats(db, tenant_id: str, lead_id: str) -> list[dict]:
    """One entry per (day in India, channel): how many lines each way and who answered."""
    # Newest first, in pages (PostgREST returns at most 1000 rows per request).
    msgs: list[dict] = []
    while len(msgs) < _MAX_MESSAGES:
        page = (db.table("messages").select("id,created_at,direction,channel,is_ai_generated,sent_by_name")
                .eq("tenant_id", tenant_id).eq("lead_id", lead_id)
                .order("created_at", desc=True).order("id", desc=True)
                .range(len(msgs), len(msgs) + _PAGE - 1).execute()).data or []
        msgs.extend(page)
        if len(page) < _PAGE:
            break
    days: dict[tuple, dict] = {}
    for m in msgs:
        at = _parse_ts(m.get("created_at"))
        if not at:
            continue
        key = (at.astimezone(IST).date().isoformat(), m.get("channel") or "whatsapp")
        day = days.setdefault(key, {"day": key[0], "channel": key[1], "at": m["created_at"], "inbound": 0,
                                    "outbound": 0, "ai_replies": 0, "team": set()})
        if (m.get("created_at") or "") > day["at"]:
            day["at"] = m["created_at"]
        if m.get("direction") == "inbound":
            day["inbound"] += 1
        else:
            day["outbound"] += 1
            if m.get("is_ai_generated"):
                day["ai_replies"] += 1
            elif m.get("sent_by_name"):
                day["team"].add(m["sent_by_name"])
    out = []
    for d in days.values():
        d["team"] = sorted(d["team"])
        out.append(d)
    return out


def _calls(db, tenant_id: str, lead_id: str) -> list[dict]:
    calls = (db.table("call_logs").select("id,created_at,caller_id,duration_seconds,outcome,manual_status,"
                                          "outcome_reason,direction,notes")
             .eq("tenant_id", tenant_id).eq("lead_id", lead_id).execute()).data or []
    callers = _names(db, "callers", "name", tenant_id, {c.get("caller_id") for c in calls})
    for c in calls:
        c["caller_name"] = callers.get(str(c.get("caller_id"))) if c.get("caller_id") else None
    return calls


def _broadcasts(db, tenant_id: str, lead_id: str) -> list[dict]:
    rows = (db.table("broadcast_recipients").select("id,broadcast_id,send_status,created_at,reply_sentiment")
            .eq("tenant_id", tenant_id).eq("lead_id", lead_id).execute()).data or []
    names = _names(db, "scheduled_broadcasts", "template_name", tenant_id, {r.get("broadcast_id") for r in rows})
    for r in rows:
        r["name"] = names.get(str(r.get("broadcast_id"))) if r.get("broadcast_id") else None
    return rows


def _notes(db, tenant_id: str, lead_id: str) -> list[dict]:
    rows = (db.table("lead_notes").select("id,content,created_at,caller_id,is_pinned")
            .eq("tenant_id", tenant_id).eq("lead_id", lead_id).order("created_at", desc=True)
            .limit(20).execute()).data or []
    callers = _names(db, "callers", "name", tenant_id, {r.get("caller_id") for r in rows})
    return [{"id": str(r["id"]), "content": r.get("content"), "created_at": r.get("created_at"),
             "is_pinned": bool(r.get("is_pinned")), "by": callers.get(str(r.get("caller_id")))} for r in rows]


def _groups(db, ctx: dict, lead: dict) -> list[dict]:
    """Picked groups they were added to, plus every group that fills itself whose rule matches them now."""
    tenant_id = ctx["tenant_id"]
    groups = (db.table("customer_groups").select("id,name,kind").eq("tenant_id", tenant_id).execute()).data or []
    if not groups:
        return []
    picked = {str(r["group_id"]) for r in (db.table("customer_group_members").select("group_id")
                                           .eq("tenant_id", tenant_id).eq("lead_id", lead["id"]).execute()).data or []}
    out = []
    for g in groups:
        gid = str(g["id"])
        if (g.get("kind") or "picked") == "picked":
            if gid in picked:
                out.append({"id": gid, "name": g["name"], "kind": "picked"})
            continue
        query = _filtered_leads_query(db, ctx, LeadFilters(group_id=gid), columns="id",
                                      opted_out_only=bool(lead.get("opted_out")))
        if query is not None and (query.eq("id", lead["id"]).limit(1).execute()).data:
            out.append({"id": gid, "name": g["name"], "kind": "rule"})
    return sorted(out, key=lambda g: g["name"].lower())


def _refunds(db, tenant_id: str, orders: list[dict]) -> list[dict]:
    """Money given back on this person's orders. Table missing -> []."""
    ids = [str(d["id"]) for d in orders]
    if not ids:
        return []
    try:
        rows = (db.table("deal_refunds").select("id,deal_id,amount_paise,method,reason,status,created_at,created_by")
                .eq("tenant_id", tenant_id).in_("deal_id", ids).execute()).data or []
    except Exception as e:
        logger.warning(f"Customer page: could not read refunds: {e}")
        return []
    numbers = {str(d["id"]): d.get("deal_number") for d in orders}
    from app.routes.customer_groups import _creator_names

    staff = _creator_names(db, tenant_id, [str(r["created_by"]) for r in rows if r.get("created_by")])
    for r in rows:
        r["number"] = numbers.get(str(r.get("deal_id")))
        r["by"] = staff.get(str(r.get("created_by")))
    return rows


def _bookings(db, tenant_id: str, lead_id: str) -> list[dict]:
    """This person's bookings with the service and staff names. Table missing -> []."""
    try:
        rows = (db.table("bookings").select("id,service_id,resource_id,start_at,status,came_at,cancelled_at,cancel_reason,note")
                .eq("tenant_id", tenant_id).eq("lead_id", lead_id).execute()).data or []
    except Exception as e:
        logger.warning(f"Customer page: could not read bookings: {e}")
        return []
    services = _names(db, "booking_services", "name", tenant_id, {r.get("service_id") for r in rows})
    staff = _names(db, "booking_resources", "name", tenant_id, {r.get("resource_id") for r in rows})
    for r in rows:
        r["service_name"] = services.get(str(r.get("service_id")))
        r["staff_name"] = staff.get(str(r.get("resource_id")))
    return rows


def _feedback(db, tenant_id: str, lead_id: str) -> list[dict]:
    """Star answers from this person. Table missing -> []."""
    try:
        rows = (db.table("customer_feedback").select("id,kind,stars,reason,staff_name,status,asked_at,answered_at")
                .eq("tenant_id", tenant_id).eq("lead_id", lead_id).not_.is_("stars", "null").execute()).data or []
    except Exception as e:
        logger.warning(f"Customer page: could not read feedback: {e}")
        return []
    return rows


def _more_events(refunds: list[dict], bookings: list[dict], feedback: list[dict]) -> list[dict]:
    """Timeline events from the newer tables: refund, booking / visit / no_show, feedback."""
    events: list[dict] = []
    for r in refunds:
        if r.get("status") == "failed":
            continue
        events.append({"kind": "refund", "at": r.get("created_at"), "amount_paise": int(r.get("amount_paise") or 0),
                       "method": r.get("method"), "reason": r.get("reason"), "number": r.get("number"),
                       "by": r.get("by"), "status": r.get("status")})
    for b in bookings:
        status = b.get("status")
        kind = "visit" if status == "came" else "no_show" if status == "no_show" else "booking"
        at = (b.get("came_at") if status == "came" else b.get("cancelled_at") if status == "cancelled" else None) \
            or b.get("start_at")
        events.append({"kind": kind, "at": at, "time": b.get("start_at"), "for": b.get("start_at"), "note": b.get("note"),
                       "service": b.get("service_name"),
                       "staff": b.get("staff_name"), "status": status,
                       "reason": b.get("cancel_reason") if status == "cancelled" else None})
    for f in feedback:
        events.append({"kind": "feedback", "at": f.get("answered_at") or f.get("asked_at"), "stars": f.get("stars"),
                       "reason": f.get("reason"), "staff": f.get("staff_name"), "about": f.get("kind")})
    return events


def _timeline(lead: dict, orders: list[dict], chats: list[dict], calls: list[dict], broadcasts: list[dict],
              more: list[dict] | None = None, has_booking_rows: bool = False) -> list[dict]:
    events: list[dict] = list(more or [])
    for d in orders:
        stage = d.get("stage")
        at = (d.get("won_at") if stage == "won" else d.get("lost_at") if stage == "lost" else None) or d.get("created_at")
        events.append({"kind": "order", "at": at, "stage": stage, "number": d.get("deal_number"),
                       "amount_paise": int(d.get("total_paise") or 0), "items": d.get("items") or [],
                       "source": d.get("source"), "payment_method": d.get("payment_method"),
                       "by": d.get("sold_by_name"), "lost_reason": d.get("lost_reason")})
    if lead.get("booked_at") and not has_booking_rows:  # real bookings, when there are any, say it better
        events.append({"kind": "booking", "at": lead["booked_at"], "for": lead.get("booked_for"),
                       "note": lead.get("booking_note")})
    for c in chats:
        events.append({"kind": "chat", "at": c["at"], "channel": c["channel"], "inbound": c["inbound"],
                       "outbound": c["outbound"], "ai_replies": c["ai_replies"], "team": c["team"]})
    for c in calls:
        events.append({"kind": "call", "at": c.get("created_at"), "by": c.get("caller_name"),
                       "outcome": c.get("outcome") or c.get("manual_status"), "reason": c.get("outcome_reason"),
                       "seconds": c.get("duration_seconds"), "direction": c.get("direction"), "notes": c.get("notes")})
    for b in broadcasts:
        events.append({"kind": "broadcast", "at": b.get("created_at"), "name": b.get("name"),
                       "status": b.get("send_status"), "reply": b.get("reply_sentiment")})
    if lead.get("opted_out") and lead.get("opted_out_at"):
        events.append({"kind": "said_stop", "at": lead["opted_out_at"], "source": lead.get("opted_out_source"),
                       "detail": lead.get("opted_out_detail")})
    if lead.get("created_at"):
        events.append({"kind": "joined", "at": lead["created_at"], "source": lead.get("source"), "ad": lead.get("ad_name")})
    events = [e for e in events if e.get("at")]
    events.sort(key=lambda e: _parse_ts(e["at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return events


@router.get("/{lead_id}")
def customer_profile(lead_id: UUID, ctx: dict = Depends(require_leads_view)):
    db = get_supabase()
    tenant_id = ctx["tenant_id"]
    lead = _lead_or_404(db, ctx, str(lead_id))
    orders = _orders(db, tenant_id, lead["id"])
    chats = _chats(db, tenant_id, lead["id"])
    calls = _calls(db, tenant_id, lead["id"])
    broadcasts = _broadcasts(db, tenant_id, lead["id"])
    refunds = _refunds(db, tenant_id, orders)
    bookings = _bookings(db, tenant_id, lead["id"])
    feedback = _feedback(db, tenant_id, lead["id"])
    from app.services.lead_tags import tags_by_lead

    tags = tags_by_lead(db, tenant_id, [lead["id"]]).get(str(lead["id"]), [])
    stars = [int(f["stars"]) for f in feedback if f.get("stars")]

    won = [d for d in orders if d.get("stage") == "won"]
    waiting = [d for d in orders if d.get("stage") == "awaiting_payment"]
    spent = sum(int(d.get("total_paise") or 0) for d in won)
    last_won = max((d.get("won_at") or d.get("created_at") for d in won), default=None)
    handler = _names(db, "callers", "name", tenant_id, {lead.get("assigned_to")}).get(str(lead.get("assigned_to")))

    channels: dict[str, int] = {}
    for c in chats:
        channels[c["channel"]] = channels.get(c["channel"], 0) + 1

    return {
        "lead": {
            "id": str(lead["id"]), "name": lead.get("name"), "phone": lead.get("phone"),
            "source": lead.get("source"), "ad_name": lead.get("ad_name"), "created_at": lead.get("created_at"),
            "segment": lead.get("segment"), "score": lead.get("score"), "handled_by": handler,
            "ai_enabled": lead.get("ai_enabled") is not False,
            "tags": tags,
        },
        "tags": tags,
        "said_stop": {
            "on_list": bool(lead.get("opted_out")), "at": lead.get("opted_out_at"),
            "source": lead.get("opted_out_source"), "detail": lead.get("opted_out_detail"),
            "do_not_call": bool(lead.get("do_not_call")),
        },
        "totals": {
            "spent_paise": spent, "orders_won": len(won),
            "average_paise": spent // len(won) if won else 0,
            "last_bought_at": last_won,
            "to_pay_paise": sum(int(d.get("total_paise") or 0) for d in waiting), "orders_waiting": len(waiting),
            "refunds_paise": sum(int(r.get("amount_paise") or 0) for r in refunds if r.get("status") == "done"),
            "visits": sum(1 for b in bookings if b.get("status") == "came"),
            "no_shows": sum(1 for b in bookings if b.get("status") == "no_show"),
            "avg_stars": round(sum(stars) / len(stars), 1) if stars else None,
        },
        "reached_on": {
            "chat_days": channels, "calls": len(calls), "broadcasts": len(broadcasts),
            "store_bills": sum(1 for d in won if d.get("source") == "walk_in"),
        },
        "timeline": _timeline(lead, orders, chats, calls, broadcasts, _more_events(refunds, bookings, feedback),
                              has_booking_rows=bool(bookings)),
        "notes": _notes(db, tenant_id, lead["id"]),
        "groups": _groups(db, ctx, lead),
    }
