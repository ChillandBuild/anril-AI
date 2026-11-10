# backend/app/services/assignment_offers.py
"""Waiting-leads offer.

When leads sit in an 'available' row and nobody is on shift, the telecallers who are
online but outside their shift hours are invited to take them. The first "yes" starts
a 2-minute window for others to join; the waiting leads are then split evenly, oldest
first, among everyone who said yes.

State lives in app_settings: one OFFER_KEY row for the offer itself, and one answer row
per telecaller (so two answers at the same moment never overwrite each other).
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.services.assignment import (
    _assign_to,
    _lead_is_open,
    _load_leads_by_ids,
    _save_setting_json,
    _setting_json,
    caller_in_shift,
    eligible_callers,
    get_telecalling_config,
    get_upload_pending,
    ist_hour,
    pick_available,
    qualifying_unassigned_leads,
    remove_upload_pending,
)
from app.services.assignment_rules import get_channel_rules

logger = logging.getLogger(__name__)

OFFER_KEY = "assignment_offer"
ANSWER_KEY_PREFIX = "assignment_offer_answer:"
SPLIT_WINDOW = timedelta(minutes=2)
COOLDOWN = timedelta(minutes=30)
EXPIRY = timedelta(minutes=30)

_WAITING_LIMIT = 500
_ONLINE_STATUSES = ("active", "break")
_WAITING_COLUMNS = "id,assigned_to,source,segment,created_at,do_not_call,call_status,converted_at,deleted_at"


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_online(caller: dict) -> bool:
    return (caller.get("status") or "active") in _ONLINE_STATUSES


def _load_state(db, tenant_id: str) -> dict | None:
    state = _setting_json(db, tenant_id, OFFER_KEY, None)
    return state if isinstance(state, dict) else None


def _save_state(db, tenant_id: str, state: dict) -> None:
    _save_setting_json(db, tenant_id, OFFER_KEY, state)


def _invited_ids(state: dict) -> list[str]:
    return [str(c) for c in (state.get("invited") or [])]


def waiting_leads(db, tenant_id: str, cfg: dict) -> list[dict]:
    """Leads that are waiting for someone to take them, oldest first.

    Unassigned open leads whose row is 'available' and whose segment the row allows, plus
    pending upload leads when the upload row is 'available'. Upload leads are marked
    {"_upload": True}.
    """
    rules = get_channel_rules(cfg)
    rows = qualifying_unassigned_leads(
        db, tenant_id, rules, {"available"}, _WAITING_COLUMNS, limit_per_row=_WAITING_LIMIT,
    )

    waiting: list[dict] = []
    seen: set[str] = set()
    for lead in rows:
        waiting.append(lead)
        seen.add(lead["id"])

    upload_rule = rules["upload"]
    if upload_rule.get("enabled") and upload_rule.get("mode") == "available":
        pending = [p for p in get_upload_pending(db, tenant_id) if p not in seen]
        loaded = _load_leads_by_ids(db, tenant_id, pending, _WAITING_COLUMNS)
        for lead_id in pending:
            lead = loaded.get(lead_id)
            if not lead or lead.get("assigned_to") or not _lead_is_open(lead):
                continue
            waiting.append({**lead, "_upload": True})
            seen.add(lead_id)

    waiting.sort(key=lambda lead: lead.get("created_at") or "")
    return waiting


def offer_candidates(db, tenant_id: str, cfg: dict, now: datetime | None = None) -> list[dict]:
    """Callers who are online (active or break) but outside shift hours right now."""
    hour = ist_hour(now)
    return [
        c for c in eligible_callers(db, tenant_id)
        if _is_online(c) and not caller_in_shift(c, cfg, hour)
    ]


def _answers(db, tenant_id: str, offer_id: str) -> dict[str, bool]:
    """caller_id -> accepted? for every telecaller who has answered this offer."""
    prefix = f"{ANSWER_KEY_PREFIX}{offer_id}:"
    res = (
        db.table("app_settings")
        .select("key,value")
        .eq("tenant_id", tenant_id)
        .like("key", f"assignment_offer_answer:{offer_id}:%")
        .execute()
    )
    answers: dict[str, bool] = {}
    for row in (res.data or []):
        key = row.get("key") or ""
        if not key.startswith(prefix):
            continue
        try:
            payload = json.loads(row.get("value") or "{}")
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        answers[key[len(prefix):]] = payload.get("accept") is True
    return answers


def _delete_answers(db, tenant_id: str, offer_id: str) -> None:
    """Drop a closed offer's answer rows so app_settings does not collect one row per answer forever."""
    try:
        (
            db.table("app_settings")
            .delete()
            .eq("tenant_id", tenant_id)
            .like("key", f"{ANSWER_KEY_PREFIX}{offer_id}:%")
            .execute()
        )
    except Exception as e:
        logger.warning(f"could not clear answers for offer {offer_id}: {e}")


def _close(db, tenant_id: str, state: dict, now: datetime) -> None:
    _save_state(db, tenant_id, {**state, "status": "closed", "closed_at": now.isoformat()})
    _delete_answers(db, tenant_id, state["id"])


def settle(db, tenant_id: str, state: dict, accepted_ids: list[str], cfg: dict, now: datetime | None = None) -> int:
    """Close the offer, then split the waiting leads (oldest first) across the accepting telecallers.

    The offer is saved as closed BEFORE any lead is assigned, so a parallel settle sees it closed.
    Returns the number of leads assigned.
    """
    now = _now(now)
    _save_state(db, tenant_id, {**state, "status": "closed", "closed_at": now.isoformat()})

    by_id = {c["id"]: c for c in eligible_callers(db, tenant_id)}
    callers = [by_id[cid] for cid in accepted_ids if cid in by_id]
    if not callers:
        return 0

    assigned = 0
    upload_done: list[str] = []
    for i, lead in enumerate(waiting_leads(db, tenant_id, cfg)):
        caller = callers[i % len(callers)]
        if _assign_to(
            db,
            lead["id"],
            tenant_id,
            caller,
            reason="offer_accepted",
            method="offer",
            segment=lead.get("segment"),
        ):
            assigned += 1
            if lead.get("_upload"):
                upload_done.append(lead["id"])
    if upload_done:
        remove_upload_pending(db, tenant_id, upload_done)
    _delete_answers(db, tenant_id, state["id"])
    return assigned


def _advance_open_offer(db, tenant_id: str, state: dict, cfg: dict, now: datetime) -> None:
    """Settle or close an open offer if its time is up or everyone has answered."""
    if not cfg.get("enabled"):
        # Master switch turned off mid-offer: nothing is assigned automatically any more.
        _close(db, tenant_id, state, now)
        return

    invited = _invited_ids(state)
    answers = _answers(db, tenant_id, state["id"])
    accepted = [c for c in invited if answers.get(c) is True]

    if all(c in answers for c in invited):
        if accepted:
            settle(db, tenant_id, state, accepted, cfg, now)
        else:
            _close(db, tenant_id, state, now)
        return

    if accepted:
        first = _parse(state.get("first_accept_at"))
        if first is None:
            # Accepted but the first-accept time was never stored: start the window now.
            _save_state(db, tenant_id, {**state, "first_accept_at": now.isoformat()})
        elif now - first >= SPLIT_WINDOW:
            settle(db, tenant_id, state, accepted, cfg, now)
        return

    created = _parse(state.get("created_at")) or now
    if now - created >= EXPIRY:
        _close(db, tenant_id, state, now)


def _notify_invited(db, tenant_id: str, candidates: list[dict], lead_count: int) -> None:
    from app.services.notify import notify_user

    message = f"{lead_count} leads are waiting for a telecaller. Do you want to take them?"
    for caller in candidates:
        if not caller.get("user_id"):
            continue
        try:
            notify_user(
                tenant_id,
                caller["user_id"],
                "leads_waiting",
                "Leads are waiting",
                message,
                db=db,
                push_url="/dashboard/telecalling",
            )
        except Exception as e:
            logger.warning(f"leads_waiting notification failed for caller {caller.get('id')}: {e}")


def process_tenant(tenant_id: str, db=None, now: datetime | None = None) -> None:
    """Run the offer state machine once for a tenant. Called from the 2-minute sweep."""
    db = db or get_supabase()
    now = _now(now)
    cfg = get_telecalling_config(tenant_id, db)
    if not cfg.get("enabled"):
        return

    state = _load_state(db, tenant_id)
    if state and state.get("status") == "open":
        _advance_open_offer(db, tenant_id, state, cfg, now)
        return

    waiting = waiting_leads(db, tenant_id, cfg)
    if not waiting:
        return
    if pick_available(db, tenant_id, eligible_callers(db, tenant_id), cfg, now=now):
        # Someone is on shift: the sweep assigns the leads, no offer needed.
        return
    candidates = offer_candidates(db, tenant_id, cfg, now=now)
    if not candidates:
        return

    if state and state.get("status") == "closed":
        last_prompt_at = _parse(state.get("last_prompt_at"))
        last_count = int(state.get("last_prompt_count") or 0)
        if last_prompt_at and now - last_prompt_at < COOLDOWN and len(waiting) <= last_count:
            return

    offer_id = uuid.uuid4().hex
    _save_state(db, tenant_id, {
        "id": offer_id,
        "status": "open",
        "created_at": now.isoformat(),
        "invited": [c["id"] for c in candidates],
        "first_accept_at": None,
        "last_prompt_at": now.isoformat(),
        "last_prompt_count": len(waiting),
        "closed_at": None,
    })
    _notify_invited(db, tenant_id, candidates, len(waiting))


def get_offer_for_caller(tenant_id: str, caller_id: str | None, db=None, now: datetime | None = None) -> dict:
    """What the telecaller should see right now: none, invited, or accepted (with the seconds left)."""
    db = db or get_supabase()
    now = _now(now)
    cfg = get_telecalling_config(tenant_id, db)

    state = _load_state(db, tenant_id)
    if state and state.get("status") == "open":
        _advance_open_offer(db, tenant_id, state, cfg, now)
        state = _load_state(db, tenant_id)

    none = {"state": "none"}
    if not state or state.get("status") != "open" or caller_id is None:
        return none
    if str(caller_id) not in _invited_ids(state):
        return none

    answer = _answers(db, tenant_id, state["id"]).get(str(caller_id))
    if answer is False:
        return none

    lead_count = len(waiting_leads(db, tenant_id, cfg))
    if answer is True:
        first = _parse(state.get("first_accept_at"))
        window_end = (first or now) + SPLIT_WINDOW
        return {
            "state": "accepted",
            "offer_id": state["id"],
            "lead_count": lead_count,
            "seconds_left": max(0, int((window_end - now).total_seconds())),
        }
    return {"state": "invited", "offer_id": state["id"], "lead_count": lead_count}


def respond(tenant_id: str, caller_id: str, offer_id: str, accept: bool, db=None, now: datetime | None = None) -> dict:
    """Record a telecaller's Yes/No for an open offer. Raises LookupError if the offer is no longer open for them."""
    db = db or get_supabase()
    now = _now(now)

    state = _load_state(db, tenant_id)
    if (
        not state
        or state.get("status") != "open"
        or state.get("id") != offer_id
        or str(caller_id) not in _invited_ids(state)
    ):
        raise LookupError("This offer is no longer open")

    _save_setting_json(
        db,
        tenant_id,
        f"{ANSWER_KEY_PREFIX}{offer_id}:{caller_id}",
        {"accept": bool(accept), "at": now.isoformat()},
    )

    current = _load_state(db, tenant_id)
    if current and current.get("status") == "open" and current.get("id") == offer_id:
        if accept and current.get("first_accept_at") is None:
            current = {**current, "first_accept_at": now.isoformat()}
            _save_state(db, tenant_id, current)
        cfg = get_telecalling_config(tenant_id, db)
        _advance_open_offer(db, tenant_id, current, cfg, now)

    return get_offer_for_caller(tenant_id, caller_id, db=db, now=now)
