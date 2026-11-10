# backend/app/services/assignment.py
import json
import logging
from datetime import datetime, timedelta, timezone
from app.db.supabase import get_supabase
from app.services.assignment_rules import SEGMENT_ROWS, SOURCE_TO_ROW, get_channel_rules, resolve_row, rule_allows
from app.services.call_wrapup import CLOSED_LEAD_STATUSES
from app.utils.db_retry import execute_with_retry

logger = logging.getLogger(__name__)


def is_round_robin_enabled(tenant_id: str) -> bool:
    """Whether auto-assign to telecallers is on.

    Single source of truth: telecalling_config.enabled. The legacy
    round_robin_enabled toggle and the Settings panel now drive the same flag,
    so the two UIs can never contradict each other.
    """
    return bool(get_telecalling_config(tenant_id).get("enabled"))


def set_round_robin_enabled(tenant_id: str, enabled: bool) -> None:
    """Flip the single auto-assign switch (telecalling_config.enabled)."""
    cfg = get_telecalling_config(tenant_id)
    cfg["enabled"] = bool(enabled)
    save_telecalling_config(tenant_id, cfg)



def get_caller_id_for_user(user_id: str, tenant_id: str) -> str | None:
    """Return callers.id for this auth user, or None if not a caller."""
    db = get_supabase()
    result = execute_with_retry(
        db.table("callers")
        .select("id")
        .eq("user_id", user_id)
        .eq("tenant_id", tenant_id)
        .eq("active", True)
        .maybe_single()
    )
    if result is None:
        return None
    return (result.data or {}).get("id")


def _open_lead_count(db, tenant_id: str, caller_id: str) -> int:
    """Active workload for a caller = assigned leads that are still open.

    Excludes Not Interested (D), Converted, DNC, Disqualified and Unreachable leads.
    """
    res = (
        db.table("leads")
        .select("id", count="exact")
        .eq("tenant_id", tenant_id)
        .eq("assigned_to", caller_id)
        .neq("segment", "D")
        .is_("converted_at", "null")
        .neq("do_not_call", True)
        .neq("call_status", "converted")
        .neq("call_status", "dnc")
        .neq("call_status", "disqualified")
        .neq("call_status", "unreachable")
        .execute()
    )
    return res.count or 0


def record_assignment_event(
    lead_id: str,
    *,
    tenant_id: str,
    segment: str | None,
    caller_id: str,
    caller_name: str | None,
    reason: str,
    method: str,
    score: int | None = None,
    matched_segments: list | None = None,
    event_type: str = "assigned",
    prev_caller_id: str | None = None,
    prev_caller_name: str | None = None,
    db=None,
) -> None:
    """Write the proof event powering the Assignment Log. Never raises."""
    db = db or get_supabase()
    try:
        db.table("lead_stage_events").insert({
            "lead_id": str(lead_id),
            "to_segment": segment if segment in ("A", "B", "C", "D") else "C",
            "event_type": event_type,
            "tenant_id": tenant_id,
            "metadata": {
                "caller_id": str(caller_id),
                "caller_name": caller_name,
                "reason": reason,
                "method": method,
                "score": score,
                "matched_segments": matched_segments or [],
                "prev_caller_id": str(prev_caller_id) if prev_caller_id else None,
                "prev_caller_name": prev_caller_name,
            },
        }).execute()
    except Exception as e:
        logger.warning(f"record_assignment_event failed for lead {lead_id}: {e}")


RR_STATE_KEY = "assignment_rr_state"  # {"last_caller_id": "<id>"}
UPLOAD_PENDING_KEY = "assignment_upload_pending"  # ["<lead id>", ...], newest last
UPLOAD_PENDING_CAP = 5000
_LEAD_LOAD_CHUNK = 200


def _setting_json(db, tenant_id: str, key: str, default):
    """Read an app_settings value stored as JSON. Returns `default` when missing or unreadable."""
    res = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", key)
        .maybe_single()
        .execute()
    )
    if res and res.data:
        try:
            return json.loads(res.data["value"])
        except Exception:
            pass
    return default


def _save_setting_json(db, tenant_id: str, key: str, value) -> None:
    """Upsert an app_settings value as JSON."""
    db.table("app_settings").upsert(
        {
            "key": key,
            "value": json.dumps(value),
            "tenant_id": tenant_id,
            "is_secret": False,
        },
        on_conflict="tenant_id,key",
    ).execute()


def _owner_user_id(db, tenant_id: str) -> str | None:
    owner = (
        db.table("tenant_users")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("role", "owner")
        .limit(1)
        .execute()
    )
    return (owner.data[0] if owner.data else {}).get("user_id")


def eligible_callers(db, tenant_id: str) -> list[dict]:
    """The assignment pool: active callers minus the owner's own caller row, oldest first.

    Status and shift hours are NOT filtered here; each mode applies its own rule.
    """
    owner_user_id = _owner_user_id(db, tenant_id)
    query = (
        db.table("callers")
        .select("id,name,user_id,status,shift_start_hour,shift_end_hour,created_at")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
    )
    if owner_user_id:
        query = query.neq("user_id", owner_user_id)
    rows = list(query.execute().data or [])
    rows.sort(key=lambda c: (c.get("created_at") or "", c.get("id") or ""))
    return rows


def caller_in_shift(caller: dict, cfg: dict, current_hour: int) -> bool:
    """Whether `current_hour` (IST) falls inside the caller's shift.

    individual shift mode uses the caller's own hours (common hours when unset);
    common mode always uses the common hours. An end before the start means overnight.
    """
    shift_mode = cfg.get("shift_mode", "common")
    common_start = cfg.get("shift_start_hour", 9)
    common_end = cfg.get("shift_end_hour", 19)
    if shift_mode == "individual":
        start_h = caller.get("shift_start_hour")
        end_h = caller.get("shift_end_hour")
        if start_h is None:
            start_h = common_start
        if end_h is None:
            end_h = common_end
    else:
        start_h, end_h = common_start, common_end
    if start_h <= end_h:
        return start_h <= current_hour < end_h
    return current_hour >= start_h or current_hour < end_h


def ist_hour(now: datetime | None = None) -> int:
    """The IST hour (0-23) of `now` (defaults to the current time)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    return (now + timedelta(hours=5, minutes=30)).hour


def pick_round_robin(db, tenant_id: str, callers: list[dict]) -> dict | None:
    """Strict turn-taking: the caller right after the last one assigned (wrapping around).

    Ignores status and shift hours. An unknown or missing last caller starts at the first.
    """
    if not callers:
        return None
    state = _setting_json(db, tenant_id, RR_STATE_KEY, {})
    last = state.get("last_caller_id") if isinstance(state, dict) else None
    ids = [c["id"] for c in callers]
    idx = (ids.index(last) + 1) % len(ids) if last in ids else 0
    chosen = callers[idx]
    _save_setting_json(db, tenant_id, RR_STATE_KEY, {"last_caller_id": chosen["id"]})
    return chosen


def pick_available(db, tenant_id: str, callers: list[dict], cfg: dict, now: datetime | None = None) -> dict | None:
    """Among callers who are active or on break AND inside shift now, the one with the fewest open leads."""
    hour = ist_hour(now)
    candidates = [
        c for c in callers
        if (c.get("status") or "active") in ("active", "break") and caller_in_shift(c, cfg, hour)
    ]
    chosen = None
    best = None
    for caller in candidates:
        count = _open_lead_count(db, tenant_id, caller["id"])
        if best is None or count < best:
            best = count
            chosen = caller
    return chosen


def _assign_to(
    db,
    lead_id,
    tenant_id: str,
    caller: dict,
    *,
    reason: str,
    method: str,
    segment: str | None = None,
    score: int | None = None,
    matched_segments: list | None = None,
    notify: bool = True,
) -> str | None:
    """Write the assignment for a lead that is still unassigned. Returns the caller id, or None if the lead was taken first.

    notify=False skips the per-lead bell notification (bulk callers send one summary instead).
    """
    chosen_id = caller["id"]
    update_res = (
        db.table("leads")
        .update({
            "assigned_to": chosen_id,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", lead_id)
        .eq("tenant_id", tenant_id)
        .is_("assigned_to", "null")
        .execute()
    )
    if not update_res.data:
        logger.info(f"Lead {lead_id} was already assigned or not found. Skipping assignment.")
        return None

    logger.info(f"Lead {lead_id} assigned to caller {chosen_id} (reason={reason}, method={method})")

    record_assignment_event(
        lead_id,
        tenant_id=tenant_id,
        segment=segment,
        caller_id=chosen_id,
        caller_name=caller.get("name"),
        reason=reason,
        method=method,
        score=score,
        matched_segments=matched_segments,
        db=db,
    )

    try:
        if notify and caller.get("user_id"):
            from app.services.notify import notify_user
            lead_row = db.table("leads").select("name").eq("id", lead_id).maybe_single().execute()
            lead_name = (lead_row.data or {}).get("name") if lead_row else None
            notify_user(
                tenant_id,
                caller["user_id"],
                "lead_assigned",
                "New lead assigned",
                f"You've been assigned '{lead_name or 'a new lead'}'. [lead_id:{lead_id}]",
                db=db,
                dedupe_lead_id=lead_id,
                push_url=f"/dashboard/telecalling?lead_id={lead_id}",
            )
    except Exception:
        pass

    return chosen_id


def assign_upload_batch(db, tenant_id: str, lead_ids: list[str], cfg: dict) -> tuple[list[dict], list[str]]:
    """Assign a Telecalling upload's leads in one pass, per the upload row's mode ('auto' or 'available').

    The callers, the round-robin position and the open-lead counts are read ONCE for the whole
    file (not per lead), and each telecaller gets ONE summary notification instead of one per lead.
    The caller has already dropped closed leads and checked the master switch and the row.
    Returns (assignments, unplaced): assignments are {"lead_id", "caller_id", "caller_name"}.
    """
    mode = get_channel_rules(cfg)["upload"].get("mode")
    ids = [str(x) for x in lead_ids]
    callers = eligible_callers(db, tenant_id)
    if mode == "available":
        hour = ist_hour()
        callers = [
            c for c in callers
            if (c.get("status") or "active") in ("active", "break") and caller_in_shift(c, cfg, hour)
        ]
    if not ids or not callers or mode not in ("auto", "available"):
        return [], ids

    load = {c["id"]: _open_lead_count(db, tenant_id, c["id"]) for c in callers} if mode == "available" else {}
    state = _setting_json(db, tenant_id, RR_STATE_KEY, {}) if mode == "auto" else {}
    last = state.get("last_caller_id") if isinstance(state, dict) else None
    order = [c["id"] for c in callers]
    turn = (order.index(last) + 1) % len(order) if last in order else 0

    assignments: list[dict] = []
    unplaced: list[str] = []
    method = "round-robin" if mode == "auto" else "available"
    for lead_id in ids:
        if mode == "auto":
            caller = callers[turn]
        else:
            caller = min(callers, key=lambda c: load[c["id"]])  # min keeps the earliest on a tie
        got = _assign_to(
            db, lead_id, tenant_id, caller,
            reason="telecalling_upload", method=method, notify=False,
        )
        if not got:
            unplaced.append(lead_id)
            continue
        assignments.append({"lead_id": lead_id, "caller_id": caller["id"], "caller_name": caller.get("name")})
        if mode == "auto":
            last = caller["id"]
            turn = (turn + 1) % len(callers)
        else:
            load[caller["id"]] += 1
    if mode == "auto" and assignments:
        _save_setting_json(db, tenant_id, RR_STATE_KEY, {"last_caller_id": last})

    counts: dict[str, int] = {}
    for a in assignments:
        counts[a["caller_id"]] = counts.get(a["caller_id"], 0) + 1
    by_id = {c["id"]: c for c in callers}
    from app.services.notify import notify_user
    for caller_id, count in counts.items():
        user_id = by_id[caller_id].get("user_id")
        if not user_id:
            continue
        try:
            notify_user(
                tenant_id, user_id, "lead_assigned", "New leads assigned",
                f"You've been assigned {count} new leads from telecalling upload.", db=db,
            )
        except Exception:
            logger.exception("Failed to send telecalling upload notification to caller")
    return assignments, unplaced


def _lead_is_open(lead: dict) -> bool:
    """Not do-not-call, not in a closed call status, not converted, not deleted."""
    return (
        not lead.get("do_not_call")
        and lead.get("call_status") not in CLOSED_LEAD_STATUSES
        and not lead.get("converted_at")
        and not lead.get("deleted_at")
    )


def _unassigned_open_query(db, tenant_id: str, columns: str):
    """Query for unassigned, open leads (the sweep and the waiting-leads offer share this filter)."""
    query = (
        db.table("leads")
        .select(columns)
        .eq("tenant_id", tenant_id)
        .is_("assigned_to", "null")
        .is_("converted_at", "null")
        .is_("deleted_at", "null")
        .neq("do_not_call", True)
    )
    for status in CLOSED_LEAD_STATUSES:
        query = query.neq("call_status", status)
    return query


def qualifying_unassigned_leads(
    db,
    tenant_id: str,
    rules: dict,
    modes: set[str],
    columns: str,
    limit_per_row: int = 200,
    newest_first: bool = False,
) -> list[dict]:
    """Unassigned open leads that some enabled segment row with one of `modes` would take.

    One query per row, filtered by that row's sources AND segments in the database. A single
    "oldest N unassigned leads" query would fill up with leads no row wants (old Cold broadcast
    imports, say) and never reach the ones that qualify. Upload-pending leads are not included.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for row in SEGMENT_ROWS:
        rule = rules[row]
        if not rule.get("enabled") or rule.get("mode") not in modes or not rule.get("segments"):
            continue
        sources = [source for source, r in SOURCE_TO_ROW.items() if r == row]
        query = _unassigned_open_query(db, tenant_id, columns).in_("segment", rule["segments"])
        if row == "whatsapp":
            # Leads with no source count as WhatsApp (resolve_row).
            query = query.or_(",".join([f"source.eq.{s}" for s in sources] + ["source.is.null"]))
        else:
            query = query.in_("source", sources)
        if newest_first:
            query = query.order("last_inbound_at", desc=True, nullsfirst=False).order("created_at", desc=True)
        else:
            query = query.order("created_at")
        for lead in (query.limit(limit_per_row).execute().data or []):
            if lead["id"] not in seen:
                seen.add(lead["id"])
                out.append(lead)
    if not newest_first:
        out.sort(key=lambda lead: lead.get("created_at") or "")
    return out


def _load_leads_by_ids(db, tenant_id: str, lead_ids, columns: str) -> dict:
    """Load leads by id in chunks (keeps the request URL short). Returns {id: row}."""
    ids = list(lead_ids)
    out: dict = {}
    for start in range(0, len(ids), _LEAD_LOAD_CHUNK):
        chunk = ids[start:start + _LEAD_LOAD_CHUNK]
        res = (
            db.table("leads")
            .select(columns)
            .eq("tenant_id", tenant_id)
            .in_("id", chunk)
            .execute()
        )
        for row in (res.data or []):
            out[row["id"]] = row
    return out


def assign_by_rule(
    lead_id,
    tenant_id: str,
    *,
    reason: str,
    segment: str | None = None,
    score: int | None = None,
    row_override: str | None = None,
    db=None,
    cfg: dict | None = None,
) -> str | None:
    """Assign one lead according to its row's rule. Returns the caller id, or None if it was not assigned.

    The row comes from the lead's origin source unless row_override is given (the upload flow).
    """
    db = db or get_supabase()
    cfg = cfg if cfg is not None else get_telecalling_config(tenant_id, db)
    if not cfg.get("enabled"):
        return None

    lead_res = (
        db.table("leads")
        .select("id,source,segment,assigned_to,do_not_call,call_status,converted_at,deleted_at")
        .eq("id", lead_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    lead = lead_res.data if lead_res else None
    if not lead:
        return None
    if lead.get("assigned_to") or not _lead_is_open(lead):
        return None

    row = row_override or resolve_row(lead.get("source"))
    if row is None:
        return None
    rule = get_channel_rules(cfg)[row]
    seg = segment if segment is not None else lead.get("segment")
    if not rule_allows(rule, row, seg):
        return None

    mode = rule.get("mode")
    if mode == "pull":
        return None
    callers = eligible_callers(db, tenant_id)
    if not callers:
        return None
    if mode == "auto":
        picked = pick_round_robin(db, tenant_id, callers)
        method = "round-robin"
    elif mode == "available":
        picked = pick_available(db, tenant_id, callers, cfg)
        method = "available"
    else:
        return None
    if picked is None:
        return None

    return _assign_to(
        db,
        lead_id,
        tenant_id,
        picked,
        reason=reason,
        method=method,
        segment=seg,
        score=score,
        matched_segments=rule.get("segments"),
    )


def maybe_assign_lead(
    lead_id: str,
    tenant_id: str,
    segment: str | None,
    channel: str | None = "whatsapp",
    *,
    reason: str = "segment_match",
    score: int | None = None,
) -> str | None:
    """Single entry point for automatic assignment of a new or changed lead.

    The `channel` argument is accepted for the existing call sites but IGNORED: the
    lead's row comes from its origin source (leads.source), not from the message channel.
    Delegates to assign_by_rule, which applies the master switch, the row rule and the mode.
    """
    return assign_by_rule(lead_id, tenant_id, reason=reason, segment=segment, score=score)


def get_upload_pending(db, tenant_id: str) -> list[str]:
    """Lead ids from the Telecalling upload that no telecaller has been given yet."""
    value = _setting_json(db, tenant_id, UPLOAD_PENDING_KEY, [])
    if not isinstance(value, list):
        return []
    return [str(x) for x in value if x]


def add_upload_pending(db, tenant_id: str, lead_ids: list[str]) -> None:
    """Remember upload leads that could not be placed yet. Keeps the newest UPLOAD_PENDING_CAP ids."""
    current = get_upload_pending(db, tenant_id)
    seen = set(current)
    merged = list(current)
    for lead_id in lead_ids:
        lead_id = str(lead_id)
        if lead_id not in seen:
            seen.add(lead_id)
            merged.append(lead_id)
    if merged == current:
        return
    _save_setting_json(db, tenant_id, UPLOAD_PENDING_KEY, merged[-UPLOAD_PENDING_CAP:])


def remove_upload_pending(db, tenant_id: str, lead_ids: list[str]) -> None:
    drop = {str(x) for x in lead_ids}
    current = get_upload_pending(db, tenant_id)
    remaining = [x for x in current if x not in drop]
    if len(remaining) != len(current):
        _save_setting_json(db, tenant_id, UPLOAD_PENDING_KEY, remaining)


def sweep_tenant(tenant_id: str, cfg: dict | None = None, limit: int = 200, db=None) -> int:
    """Assign unassigned leads whose row rule is 'auto' or 'available', plus pending upload leads.

    Returns the number of leads assigned. Does nothing when the master switch is off.
    """
    db = db or get_supabase()
    if cfg is None:
        cfg = get_telecalling_config(tenant_id, db)
    if not cfg.get("enabled"):
        return 0
    rules = get_channel_rules(cfg)
    assigned = 0

    # 1) Unassigned open leads that an auto/available row takes, oldest first.
    leads = qualifying_unassigned_leads(
        db, tenant_id, rules, {"auto", "available"}, "id,source,segment,created_at", limit_per_row=limit,
    )
    exhausted: set[str] = set()
    for lead in leads:
        row = resolve_row(lead.get("source"))
        if row is None:
            continue
        rule = rules[row]
        mode = rule.get("mode")
        if mode not in ("auto", "available") or mode in exhausted:
            continue
        if not rule_allows(rule, row, lead.get("segment")):
            continue
        try:
            if assign_by_rule(lead["id"], tenant_id, reason="sweep", db=db, cfg=cfg):
                assigned += 1
            else:
                # Nobody to give it to in this mode right now: stop trying this mode this sweep.
                exhausted.add(mode)
        except Exception as e:
            logger.warning(f"sweep assign failed for lead {lead.get('id')}: {e}")

    # 2) Pending upload leads.
    pending = get_upload_pending(db, tenant_id)
    if pending:
        upload_rule = rules["upload"]
        pending_leads = _load_leads_by_ids(
            db, tenant_id, pending,
            "id,assigned_to,source,segment,do_not_call,call_status,converted_at,deleted_at",
        )
        still_open: list[str] = []
        drop: list[str] = []
        for lead_id in pending:
            lead = pending_leads.get(lead_id)
            if lead and not lead.get("assigned_to") and _lead_is_open(lead):
                still_open.append(lead_id)
            else:
                drop.append(lead_id)
        if drop:
            remove_upload_pending(db, tenant_id, drop)

        if upload_rule.get("enabled") and upload_rule.get("mode") in ("auto", "available"):
            done: list[str] = []
            for lead_id in still_open[:limit]:
                try:
                    got = assign_by_rule(
                        lead_id, tenant_id, reason="sweep", row_override="upload", db=db, cfg=cfg,
                    )
                except Exception as e:
                    logger.warning(f"sweep upload assign failed for lead {lead_id}: {e}")
                    got = None
                if got:
                    assigned += 1
                    done.append(lead_id)
                elif upload_rule.get("mode") == "available":
                    break
            if done:
                remove_upload_pending(db, tenant_id, done)

    return assigned


def sweep_unassigned_leads(limit_per_tenant: int = 200) -> int:
    """Periodic safety net (every 2 min): run the assignment sweep and the waiting-leads offer per tenant.

    Only tenants with the master switch on are touched. Returns the number of leads assigned.
    """
    db = get_supabase()
    rows = (
        db.table("app_settings")
        .select("tenant_id,value")
        .eq("key", "telecalling_config")
        .execute()
    )
    total = 0
    for row in (rows.data or []):
        tenant_id = row.get("tenant_id")
        try:
            cfg = {**_TELECALLING_CONFIG_DEFAULT, **json.loads(row.get("value") or "{}")}
        except Exception:
            continue
        if not tenant_id or not cfg.get("enabled"):
            continue
        try:
            total += sweep_tenant(tenant_id, cfg=cfg, limit=limit_per_tenant, db=db)
        except Exception as e:
            logger.warning(f"assignment sweep failed for tenant {tenant_id}: {e}")
        try:
            from app.services.assignment_offers import process_tenant
            process_tenant(tenant_id, db=db)
        except Exception as e:
            logger.warning(f"waiting-leads offer failed for tenant {tenant_id}: {e}")
    if total:
        logger.info(f"Assignment sweep: assigned {total} unassigned lead(s)")
    return total


def reassign_backlog(caller_id: str, tenant_id: str) -> None:
    """
    Called when a telecaller switches to Active.

    Gives this caller any unassigned flagged leads (needs_human_attention, up to 10),
    then runs the normal assignment sweep so waiting leads follow their row rules.
    No-op when the master switch is off.
    """
    cfg = get_telecalling_config(tenant_id)
    if not cfg.get("enabled"):
        return

    db = get_supabase()

    # 1. Fetch unassigned flagged leads
    flagged_res = (
        db.table("leads")
        .select("id,segment")
        .eq("tenant_id", tenant_id)
        .is_("assigned_to", "null")
        .eq("needs_human_attention", True)
        .limit(10)
        .execute()
    )

    seg_by_id: dict = {}
    for row in (flagged_res.data or []):
        seg_by_id[row["id"]] = row.get("segment")

    if seg_by_id:
        ids_to_assign = list(seg_by_id.keys())
        db.table("leads").update({
            "assigned_to": caller_id,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }).in_("id", ids_to_assign).is_("assigned_to", "null").execute()
        cn = db.table("callers").select("name").eq("id", caller_id).eq("tenant_id", tenant_id).maybe_single().execute()
        caller_name = (cn.data or {}).get("name") if cn else None
        for lead_id, seg in seg_by_id.items():
            record_assignment_event(
                lead_id, tenant_id=tenant_id, segment=seg,
                caller_id=caller_id, caller_name=caller_name,
                reason="backlog_claim", method="login", db=db,
            )
        logger.info(f"Reassigned {len(ids_to_assign)} flagged backlog leads to caller {caller_id} upon coming online.")

    # 2. Waiting leads, per the channel rules.
    sweep_tenant(tenant_id, cfg=cfg, db=db)


_INBOX_CONFIG_DEFAULT: dict = {
    "enabled": False,
    "auto_assign_enabled": False,
    "segments": ["A"],
    "channels": ["whatsapp", "instagram", "facebook", "telegram"],
    "triggers": ["A", "B", "C", "F"],
}

_TELECALLING_CONFIG_DEFAULT: dict = {
    "enabled": False,
    "calling_provider": "telecmi",
    "segments": ["A"],
    "channels": ["whatsapp"],
    "targets": {},
    "scripts": {},
    "max_call_attempts": 4,
    "assignment_mode": "push",
}


def get_inbox_config(tenant_id: str) -> dict:
    """Return inbox_config from app_settings, merged with defaults."""
    db = get_supabase()
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "inbox_config")
        .maybe_single()
        .execute()
    )
    if row and row.data:
        try:
            stored = json.loads(row.data["value"])
            return {**_INBOX_CONFIG_DEFAULT, **stored}
        except Exception:
            pass
    return dict(_INBOX_CONFIG_DEFAULT)


def get_telecalling_config(tenant_id: str, db = None) -> dict:
    """Return telecalling_config from app_settings, merged with defaults."""
    if db is None:
        db = get_supabase()
    row = (
        db.table("app_settings")
        .select("value")
        .eq("tenant_id", tenant_id)
        .eq("key", "telecalling_config")
        .maybe_single()
        .execute()
    )
    if row and row.data:
        try:
            stored = json.loads(row.data["value"])
            return {**_TELECALLING_CONFIG_DEFAULT, **stored}
        except Exception:
            pass
    return dict(_TELECALLING_CONFIG_DEFAULT)


def save_inbox_config(tenant_id: str, config: dict) -> None:
    """Persist inbox_config to app_settings."""
    db = get_supabase()
    db.table("app_settings").upsert(
        {
            "key": "inbox_config",
            "value": json.dumps(config),
            "tenant_id": tenant_id,
            "is_secret": False,
        },
        on_conflict="tenant_id,key",
    ).execute()


def save_telecalling_config(tenant_id: str, config: dict, db = None) -> None:
    """Persist telecalling_config to app_settings."""
    if db is None:
        db = get_supabase()
    db.table("app_settings").upsert(
        {
            "key": "telecalling_config",
            "value": json.dumps(config),
            "tenant_id": tenant_id,
            "is_secret": False,
        },
        on_conflict="tenant_id,key",
    ).execute()


def should_escalate_to_inbox(config: dict, trigger: str, channel: str) -> bool:
    """Return True if this trigger should create an inbox handover.
    Trigger C always escalates (explicit user request, bypasses all gates).
    Other triggers check master switch, trigger list, and channel — no segment gate."""
    if trigger == "C":
        return True
    if not config.get("enabled"):
        return False
    if trigger not in config.get("triggers", []):
        return False
    if channel not in config.get("channels", []):
        return False
    return True


def should_escalate_hot_lead(config: dict, segment: str, channel: str) -> bool:
    """Segment-driven hot lead escalation. Used by score ≥ 7 events
    in both AI and bot paths. Single gate: master + segment + channel."""
    if not config.get("enabled"):
        return False
    if segment not in config.get("segments", []):
        return False
    if channel not in config.get("channels", []):
        return False
    return True


def is_caller_on_call(db, caller_id: str, tenant_id: str) -> bool:
    """Return True if the caller has an active call log (status in ('initiated', 'in_progress'))."""
    res = (
        db.table("call_logs")
        .select("id")
        .eq("caller_id", caller_id)
        .eq("tenant_id", tenant_id)
        .in_("status", ["initiated", "in_progress"])
        .limit(1)
        .execute()
    )
    return bool(res.data)


def _in_shift_caller_ids(tenant_id: str) -> set[str]:
    """Return the set of active caller ids currently within their shift hours."""
    db = get_supabase()
    cfg = get_telecalling_config(tenant_id)
    shift_mode = cfg.get("shift_mode", "common")
    common_start = cfg.get("shift_start_hour", 9)
    common_end = cfg.get("shift_end_hour", 19)

    from datetime import timedelta
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    current_hour = now_ist.hour

    owner = (
        db.table("tenant_users")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("role", "owner")
        .limit(1)
        .execute()
    )
    owner_user_id = (owner.data[0] if owner.data else {}).get("user_id")

    query = (
        db.table("callers")
        .select("id,user_id,shift_start_hour,shift_end_hour")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
    )
    if owner_user_id:
        query = query.neq("user_id", owner_user_id)
    callers = query.execute()
    if not callers.data:
        return set()

    ids: set[str] = set()
    for caller in callers.data:
        if shift_mode == "individual":
            start_h = caller.get("shift_start_hour") if caller.get("shift_start_hour") is not None else common_start
            end_h = caller.get("shift_end_hour") if caller.get("shift_end_hour") is not None else common_end
        else:
            start_h = common_start
            end_h = common_end

        if start_h <= end_h:
            in_shift = (start_h <= current_hour < end_h)
        else:
            in_shift = (current_hour >= start_h or current_hour < end_h)
        if in_shift:
            ids.add(caller["id"])
    return ids
