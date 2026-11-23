"""v9.2 #21 Call IQ leave: a telecaller on leave hands their open leads to the others, round robin.

Leave dates live on callers (leave_from, leave_to; migration 321). Each lead that moves is written to the
same Assignment Log the rest of calling uses (lead_stage_events, reason 'moved_for_leave'). Built by agent I-B.
"""
import logging
from datetime import date, datetime, timezone

from app.services.call_rules import now_ist

logger = logging.getLogger(__name__)

MAX_MOVE = 10000
_CHUNK = 200
LEAVE_REASON = "moved_for_leave"


def today_ist(now: datetime | None = None) -> date:
    return now_ist(now).date()


def on_leave(caller: dict, today: date) -> bool:
    """True when `today` falls inside this caller's leave (both ends included)."""
    try:
        start = date.fromisoformat(str(caller.get("leave_from") or "")[:10])
        end = date.fromisoformat(str(caller.get("leave_to") or "")[:10])
    except ValueError:
        return False
    return start <= today <= end


def _open_lead_rows(db, tenant_id: str, caller_id: str) -> list[dict]:
    """Leads still being worked: not won, lost, Said stop, deleted or blocked."""
    from app.services.call_wrapup import CLOSED_LEAD_STATUSES

    rows: list[dict] = []
    page = 1000  # PostgREST returns at most 1000 rows per request, so read page by page.
    for start in range(0, MAX_MOVE, page):
        res = (
            db.table("leads").select("id,segment,score,call_status")
            .eq("tenant_id", tenant_id).eq("assigned_to", caller_id)
            .neq("segment", "D")
            .is_("converted_at", "null").is_("deleted_at", "null").is_("blocked_at", "null")
            .neq("do_not_call", True)
            .or_("opted_out.is.null,opted_out.eq.false")
            .order("id").range(start, min(start + page, MAX_MOVE) - 1).execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
    closed = (*CLOSED_LEAD_STATUSES, "not_interested")
    return [r for r in rows if r.get("call_status") not in closed]


def _targets(db, tenant_id: str, caller_id: str, today: date) -> list[dict]:
    """The other active telecallers who are not on leave, oldest first."""
    from app.services.assignment import eligible_callers

    leave = {
        r["id"]: r for r in (
            db.table("callers").select("id,leave_from,leave_to").eq("tenant_id", tenant_id).execute().data or []
        )
    }
    return [
        c for c in eligible_callers(db, tenant_id)
        if c["id"] != caller_id and not on_leave(leave.get(c["id"], {}), today)
    ]


def move_leads_of_caller_on_leave(db, tenant_id: str, caller_id: str, now: datetime | None = None) -> dict:
    """Hand this person's open leads to the other active telecallers, round robin.

    Returns {"moved": int, "to": [{"name", "count"}], "no_one_free": bool}. Leaves everything where it is
    when nobody else is free to take the leads.
    """
    today = today_ist(now)
    caller_id = str(caller_id)
    targets = _targets(db, tenant_id, caller_id, today)
    if not targets:
        return {"moved": 0, "to": [], "no_one_free": True}
    leads = _open_lead_rows(db, tenant_id, caller_id)
    if not leads:
        # Nothing to move is still "handled": without the stamp start_due_leaves runs again every 5 minutes and
        # bounces a lead an admin hands this person during the leave. Only no_one_free keeps retrying.
        _mark_handled(db, tenant_id, caller_id)
        return {"moved": 0, "to": [], "no_one_free": False}

    me = db.table("callers").select("name").eq("id", caller_id).eq("tenant_id", tenant_id).maybe_single().execute()
    my_name = ((me.data if me else None) or {}).get("name")

    plan: dict[str, list[dict]] = {t["id"]: [] for t in targets}
    for i, lead in enumerate(leads):
        plan[targets[i % len(targets)]["id"]].append(lead)

    moved = 0
    counts: list[dict] = []
    for target in targets:
        batch = plan[target["id"]]
        done: list[dict] = []
        for start in range(0, len(batch), _CHUNK):
            chunk = batch[start:start + _CHUNK]
            ids = [r["id"] for r in chunk]
            # Only rows still with the person on leave move, so a lead someone just claimed is left alone.
            res = (
                db.table("leads").update({"assigned_to": target["id"]})
                .eq("tenant_id", tenant_id).eq("assigned_to", caller_id).in_("id", ids).execute()
            )
            moved_ids = {r["id"] for r in (res.data or [])}
            done.extend(r for r in chunk if r["id"] in moved_ids)
        if done:
            _log_moves(db, tenant_id, done, target, caller_id, my_name)
            moved += len(done)
            counts.append({"name": target.get("name") or "Telecaller", "count": len(done)})

    _mark_handled(db, tenant_id, caller_id)
    return {"moved": moved, "to": counts, "no_one_free": False}


def _mark_handled(db, tenant_id: str, caller_id: str) -> None:
    try:
        db.table("callers").update({"leave_leads_moved_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", caller_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.warning("could not mark leave as handled for caller %s: %s", caller_id, e)


def _log_moves(db, tenant_id: str, leads: list[dict], target: dict, prev_id: str, prev_name: str | None) -> None:
    """One Assignment Log row per lead (same shape as assignment.record_assignment_event). Never raises."""
    rows = [{
        "lead_id": lead["id"],
        "to_segment": lead.get("segment") if lead.get("segment") in ("A", "B", "C", "D") else "C",
        "event_type": "reassigned",
        "tenant_id": tenant_id,
        "metadata": {
            "caller_id": str(target["id"]),
            "caller_name": target.get("name"),
            "reason": LEAVE_REASON,
            "method": "leave",
            "score": lead.get("score"),
            "matched_segments": [],
            "prev_caller_id": prev_id,
            "prev_caller_name": prev_name,
        },
    } for lead in leads]
    try:
        for start in range(0, len(rows), _CHUNK):
            db.table("lead_stage_events").insert(rows[start:start + _CHUNK]).execute()
    except Exception as e:
        logger.warning("assignment log write failed for leave move: %s", e)


def start_leave(db, tenant_id: str, caller_id: str, leave_from: date, leave_to: date, reason: str | None,
                now: datetime | None = None) -> dict:
    """Save the leave; when it starts today (or already has), move the open leads right away.

    A leave that starts later moves its leads on its first day (check_break_limits calls start_due_leaves).
    """
    db.table("callers").update({
        "leave_from": leave_from.isoformat(),
        "leave_to": leave_to.isoformat(),
        "leave_reason": (reason or "").strip() or None,
        "leave_leads_moved_at": None,
    }).eq("id", str(caller_id)).eq("tenant_id", tenant_id).execute()
    if leave_from <= today_ist(now):
        result = move_leads_of_caller_on_leave(db, tenant_id, str(caller_id), now)
        return {**result, "starts_later": False}
    return {"moved": 0, "to": [], "no_one_free": False, "starts_later": True}


def end_leave(db, tenant_id: str, caller_id: str) -> None:
    db.table("callers").update({
        "leave_from": None, "leave_to": None, "leave_reason": None, "leave_leads_moved_at": None,
    }).eq("id", str(caller_id)).eq("tenant_id", tenant_id).execute()


def start_due_leaves(db, now: datetime | None = None) -> int:
    """Move the leads of everyone whose leave has begun but was not handled yet. Returns how many people."""
    today = today_ist(now)
    try:
        rows = (
            db.table("callers").select("id,tenant_id,leave_from,leave_to")
            .eq("active", True).is_("leave_leads_moved_at", "null")
            .lte("leave_from", today.isoformat()).gte("leave_to", today.isoformat()).execute()
        ).data or []
    except Exception as e:
        logger.warning("start_due_leaves could not read callers: %s", e)
        return 0
    handled = 0
    for c in rows:
        try:
            move_leads_of_caller_on_leave(db, c["tenant_id"], c["id"], now)
            handled += 1
        except Exception as e:
            logger.warning("leave move failed for caller %s: %s", c.get("id"), e)
    return handled
