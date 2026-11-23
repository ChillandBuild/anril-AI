"""v9.2 "Send to calling": put people into Call IQ › Leads to call, from anywhere.

Used by Customers (bulk action), Customers › Groups ("Send to calling") and Meta Instant forms
(a form lead whose number has no WhatsApp). One function so every module cleans the list the same way.

The queue is leads.assigned_to (GET /calls/next-lead serves a caller their assigned, open leads), so
"send to calling" = give each open, unassigned person to a caller, taking turns (round-robin), exactly
like the automatic sharing does. It is a staff choice, so the per-source sharing rule is not asked;
the cleaning is the same as the queue's own (assignment._lead_is_open):

  * Said stop / Do not call   -> never called            (said_stop)
  * already bought            -> the queue skips buyers   (bought)
  * closed call status, deleted or blocked                (closed)
  * already with a caller     -> left with that caller    (already)

Returns counts the screen shows: "18 sent to calling · 3 said stop · 2 already bought · 4 already with a caller".
Never raises on one bad row; a missing caller list is reported as no_callers.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

MAX_PEOPLE = 2000
_CHUNK = 200
_COLS = "id,name,segment,assigned_to,do_not_call,opted_out,call_status,converted_at,deleted_at,blocked_at"


def _empty() -> dict:
    return {"added": 0, "already": 0, "said_stop": 0, "bought": 0, "closed": 0, "not_found": 0,
            "no_callers": False, "added_ids": []}


def classify(lead: dict) -> str:
    """'open' | 'already' | 'said_stop' | 'bought' | 'closed' for one lead row (same order as the queue)."""
    from app.services.assignment import CLOSED_LEAD_STATUSES

    if lead.get("opted_out") or lead.get("do_not_call"):
        return "said_stop"
    if lead.get("deleted_at") or lead.get("blocked_at") or lead.get("call_status") in CLOSED_LEAD_STATUSES:
        return "closed"
    if lead.get("converted_at"):
        return "bought"
    if lead.get("assigned_to"):
        return "already"
    return "open"


def _log_assignments(db, tenant_id: str, lead_ids: list[str], rows: dict, caller: dict, reason: str,
                     group_id: str | None = None) -> None:
    """The Assignment Log rows (same shape as assignment.record_assignment_event), one insert per batch."""
    try:
        db.table("lead_stage_events").insert([{
            "lead_id": lid,
            "to_segment": (rows.get(lid) or {}).get("segment") if (rows.get(lid) or {}).get("segment") in ("A", "B", "C", "D") else "C",
            "event_type": "assigned",
            "tenant_id": tenant_id,
            "metadata": {"caller_id": str(caller["id"]), "caller_name": caller.get("name"), "reason": reason,
                         "method": "round-robin", "score": None, "matched_segments": [],
                         "prev_caller_id": None, "prev_caller_name": None,
                         **({"group_id": group_id} if group_id else {})},
        } for lid in lead_ids]).execute()
    except Exception as e:
        logger.warning("send_to_calling: assignment log failed for %d leads: %s", len(lead_ids), e)


def send_to_calling(db, tenant_id: str, lead_ids: list[str], *, reason: str, group_id: str | None = None) -> dict:
    """Give the open, unassigned people in lead_ids to callers (round-robin). See module docstring.

    reason is stored on the assignment log (e.g. "customers_bulk", "group", "form_no_whatsapp").
    group_id (a Customers group) is kept on that log too, so Groups can say "Used by Call IQ".
    """
    from app.services import assignment

    db = db or get_supabase()
    out = _empty()
    ids = list(dict.fromkeys(str(i) for i in (lead_ids or []) if i))[:MAX_PEOPLE]
    if not ids:
        return out

    rows: dict[str, dict] = {}
    for i in range(0, len(ids), _CHUNK):
        part = ids[i:i + _CHUNK]
        for r in (db.table("leads").select(_COLS).eq("tenant_id", tenant_id).in_("id", part).execute().data or []):
            rows[str(r["id"])] = r
    out["not_found"] = len([i for i in ids if i not in rows])

    open_ids: list[str] = []
    for lid in ids:
        lead = rows.get(lid)
        if not lead:
            continue
        kind = classify(lead)
        if kind == "open":
            open_ids.append(lid)
        else:
            out[kind] += 1
    if not open_ids:
        return out

    callers = assignment.eligible_callers(db, tenant_id)
    if not callers:
        out["no_callers"] = True
        return out

    per_caller: Counter = Counter()
    by_id = {c["id"]: c for c in callers}
    # Taking turns, planned in memory (same order as assignment.pick_round_robin: the caller after the last
    # one used), then written as one update per caller per 200 people. Per-person writes made a 2,000-person
    # group take minutes and time out half-done.
    state = assignment._setting_json(db, tenant_id, assignment.RR_STATE_KEY, {})
    last = state.get("last_caller_id") if isinstance(state, dict) else None
    caller_ids = [c["id"] for c in callers]
    start = (caller_ids.index(last) + 1) % len(caller_ids) if last in caller_ids else 0
    plan: dict[str, list[str]] = {}
    for n, lid in enumerate(open_ids):
        plan.setdefault(caller_ids[(start + n) % len(caller_ids)], []).append(lid)
    last_used = caller_ids[(start + len(open_ids) - 1) % len(caller_ids)]

    now = datetime.now(timezone.utc).isoformat()
    for caller_id, lids in plan.items():
        caller = by_id[caller_id]
        for i in range(0, len(lids), _CHUNK):
            part = lids[i:i + _CHUNK]
            try:
                got = (db.table("leads").update({"assigned_to": caller_id, "assigned_at": now})
                       .eq("tenant_id", tenant_id).in_("id", part).is_("assigned_to", "null")
                       .execute().data or [])
            except Exception as e:  # one bad batch never stops the rest
                logger.warning("send_to_calling: %d leads not assigned to %s: %s", len(part), caller_id, e)
                got = []
            done = [str(r["id"]) for r in got]
            out["added"] += len(done)
            out["already"] += len(part) - len(done)  # taken by someone else a moment ago
            out["added_ids"].extend(done)
            per_caller[caller_id] += len(done)
            if done:
                _log_assignments(db, tenant_id, done, rows, caller, reason, group_id)
    try:
        assignment._save_setting_json(db, tenant_id, assignment.RR_STATE_KEY, {"last_caller_id": last_used})
    except Exception as e:
        logger.warning("send_to_calling: turn-taking state not saved: %s", e)

    # One bell per caller ("5 people sent to you to call"), not one per person.
    try:
        from app.services.notify import notify_user

        for caller_id, n in per_caller.items():
            user_id = (by_id.get(caller_id) or {}).get("user_id")
            if user_id:
                notify_user(tenant_id, user_id, "lead_assigned",
                            "People to call" if n > 1 else "Someone to call",
                            f"{n} {'people were' if n > 1 else 'person was'} sent to you to call.",
                            db=db, push_url="/dashboard/telecalling")
    except Exception as e:
        logger.warning("send_to_calling: caller bell failed: %s", e)
    return out
