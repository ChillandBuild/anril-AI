"""Call IQ reports (v9.2 #21): Live, Evaluation, Results. Read-only, nothing here writes.

Who is shown: active telecallers of this client. The owner's own caller record is left out, as on every
other telecaller number. A person without team.view (a plain telecaller) sees only themself. A Team
leader sees only their team (call_teams.caller_scope). Everyone else sees all.
Days are Indian (IST) calendar days. A missing table or a failed read gives an empty answer, never a 500.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.dependencies.tenant import _has_permission
from app.services.assignment import get_telecalling_config
from app.services.call_marking import CHECKS
from app.services.call_teams import caller_scope
from app.services.reports_common import paged, safe
from app.services.telecaller_performance import COUNTED_STATUSES, ist_day_bounds, summarize_calls

logger = logging.getLogger(__name__)

ON_CALL_STATUSES = ("initiated", "in_progress")
ON_CALL_MAX_AGE = timedelta(hours=3)  # a call row stuck "in progress" for longer than this is not a live call
EVAL_DAYS = {"7d": 7, "30d": 30}
RESULT_DAYS = {"today": 1, "7d": 7, "30d": 30}
WEAK_POINTS_SHOWN = 3
LOWEST_CALLS_SHOWN = 10
_CHECK_LABELS = {c["key"]: c["label"] for c in CHECKS}


def period_bounds(period: str, days_by_name: dict[str, int], now: datetime | None = None) -> tuple[str, str] | None:
    """(start_iso, end_iso) for 'today' / '7d' / '30d' in IST days, ending at the end of today. None if unknown."""
    days = days_by_name.get(period)
    if days is None:
        return None
    today_start, today_end = ist_day_bounds(now)
    start = datetime.fromisoformat(today_start) - timedelta(days=days - 1)
    return start.isoformat(), today_end


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── Who is shown ─────────────────────────────────────────────────────────────


def visible_callers(db, ctx: dict) -> list[dict]:
    """Active telecallers this person may see: [{id, name, status, status_changed_at}], sorted by name."""
    tenant_id = ctx["tenant_id"]
    rows = (
        db.table("callers").select("id,name,user_id,status,status_changed_at")
        .eq("tenant_id", tenant_id).eq("active", True).execute().data or []
    )
    owner = safe(lambda: (
        db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner")
        .limit(1).execute().data or []
    ), [], "owner")
    owner_user_id = owner[0].get("user_id") if owner else None
    if owner_user_id:
        rows = [r for r in rows if r.get("user_id") != owner_user_id]

    if _has_permission(ctx, "team.view"):
        scope = caller_scope(db, ctx)
        if scope is not None:
            rows = [r for r in rows if str(r["id"]) in scope]
    else:
        mine = str(ctx["caller_id"]) if ctx.get("caller_id") else None
        rows = [r for r in rows if mine and str(r["id"]) == mine]
    return sorted(rows, key=lambda r: (r.get("name") or "").lower())


def _name(caller: dict) -> str:
    return (caller.get("name") or "").strip() or "Unnamed"


# ── Live ─────────────────────────────────────────────────────────────────────


def break_minutes(status_rows: list[dict], now: datetime) -> dict[str, int]:
    """{caller_id: minutes on break} from caller_status_logs rows (an open break runs to now)."""
    out: dict[str, float] = {}
    for row in status_rows:
        if row.get("status") != "break":
            continue
        start = _parse(row.get("started_at"))
        if start is None:
            continue
        end = _parse(row.get("ended_at")) or now
        out[str(row["caller_id"])] = out.get(str(row["caller_id"]), 0.0) + max((end - start).total_seconds(), 0) / 60
    return {cid: round(minutes) for cid, minutes in out.items()}


def person_state(caller: dict, live_call_at: str | None) -> tuple[str, str | None]:
    """('on_call' | 'on_break' | 'idle' | 'off', since) for one person."""
    if live_call_at:
        return "on_call", live_call_at
    status = caller.get("status")
    since = caller.get("status_changed_at")
    if status == "break":
        return "on_break", since
    if status == "active":
        return "idle", since
    return "off", since


def live(db, ctx: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    callers = visible_callers(db, ctx)
    ids = [str(c["id"]) for c in callers]
    if not ids:
        return {"callers": [], "as_of": now.isoformat()}
    tenant_id = ctx["tenant_id"]
    day_start, day_end = ist_day_bounds(now)

    today_calls = safe(lambda: paged(lambda: (
        db.table("call_logs").select("id,caller_id,status,created_at").eq("tenant_id", tenant_id)
        .in_("caller_id", ids).gte("created_at", day_start).lt("created_at", day_end))), [], "today's calls")
    calls_today: dict[str, int] = {}
    live_since: dict[str, str] = {}
    for row in today_calls:
        cid = str(row["caller_id"])
        calls_today[cid] = calls_today.get(cid, 0) + 1
    # A call can start before midnight and still be going: look at open calls separately, not only today's.
    open_calls = safe(lambda: (
        db.table("call_logs").select("id,caller_id,status,created_at").eq("tenant_id", tenant_id)
        .in_("caller_id", ids).in_("status", list(ON_CALL_STATUSES))
        .gte("created_at", (now - ON_CALL_MAX_AGE).isoformat()).execute().data or []), [], "open calls")
    for row in open_calls:
        cid = str(row["caller_id"])
        if cid not in live_since or (row.get("created_at") or "") > live_since[cid]:
            live_since[cid] = row.get("created_at")

    status_rows = safe(lambda: paged(lambda: (
        db.table("caller_status_logs").select("id,caller_id,status,started_at,ended_at").eq("tenant_id", tenant_id)
        .in_("caller_id", ids).eq("status", "break").gte("started_at", day_start).lt("started_at", day_end))), [], "breaks")
    breaks = break_minutes(status_rows, now)

    people = []
    for c in callers:
        cid = str(c["id"])
        state, since = person_state(c, live_since.get(cid))
        people.append({
            "caller_id": cid, "name": _name(c), "state": state, "since": since,
            "calls_today": calls_today.get(cid, 0), "break_minutes_today": breaks.get(cid, 0),
        })
    return {"callers": people, "as_of": now.isoformat()}


# ── Evaluation ───────────────────────────────────────────────────────────────


def is_sim_client(db, tenant_id: str) -> bool:
    cfg = safe(lambda: get_telecalling_config(tenant_id, db=db), {}, "calling settings")
    return (cfg or {}).get("calling_provider", "telecmi") == "sim_basic"


def weak_points(criteria_avg: dict[str, float]) -> list[str]:
    """The weakest checks as plain sentences, weakest first. Checks at 100% are not weak points."""
    weak = sorted(((pct, key) for key, pct in criteria_avg.items() if pct < 100), key=lambda x: (x[0], x[1]))
    return [f"{_CHECK_LABELS.get(key, key)}: {round(pct)}% of the marks on average" for pct, key in weak[:WEAK_POINTS_SHOWN]]


def _scored_calls(db, tenant_id: str, ids: list[str], start_iso: str, end_iso: str) -> list[dict]:
    return paged(lambda: (
        db.table("call_logs").select("id,caller_id,lead_id,status,score,score_status,evaluation,created_at")
        .eq("tenant_id", tenant_id).in_("caller_id", ids).in_("status", list(COUNTED_STATUSES))
        .gte("created_at", start_iso).lt("created_at", end_iso)))


def _lead_names(db, tenant_id: str, lead_ids: list[str]) -> dict[str, str]:
    if not lead_ids:
        return {}
    rows = safe(lambda: (
        db.table("leads").select("id,name").eq("tenant_id", tenant_id).in_("id", lead_ids).execute().data or []
    ), [], "lead names")
    return {str(r["id"]): (r.get("name") or "").strip() for r in rows}


def evaluation(db, ctx: dict, period: str, now: datetime | None = None) -> dict:
    bounds = period_bounds(period, EVAL_DAYS, now)
    assert bounds is not None
    tenant_id = ctx["tenant_id"]
    empty = {"period": period, "available": True, "callers": [], "lowest_calls": []}
    if is_sim_client(db, tenant_id):
        return {**empty, "available": False,
                "message": "Call scores are not part of the phone-app (SIM) plan, so there is nothing to show here."}
    callers = visible_callers(db, ctx)
    ids = [str(c["id"]) for c in callers]
    if not ids:
        return empty
    rows = safe(lambda: _scored_calls(db, tenant_id, ids, *bounds), [], "scored calls")
    by_caller: dict[str, list[dict]] = {cid: [] for cid in ids}
    for row in rows:
        by_caller.setdefault(str(row["caller_id"]), []).append(row)

    people = []
    scored_rows: list[dict] = []
    for c in callers:
        cid = str(c["id"])
        mine = by_caller.get(cid, [])
        summary = summarize_calls(mine)
        scored = [r for r in mine if r.get("score_status") == "scored" and r.get("score") is not None]
        scored_rows.extend(scored)
        scores = [float(r["score"]) for r in scored]
        people.append({
            "caller_id": cid, "name": _name(c), "calls_scored": summary["scored_calls"],
            "avg_score": summary["avg_score"],
            "best": round(max(scores), 1) if scores else None,
            "worst": round(min(scores), 1) if scores else None,
            "top_weak_points": weak_points(summary["criteria_avg"]),
        })
    names = {str(c["id"]): _name(c) for c in callers}
    lowest = sorted(scored_rows, key=lambda r: (float(r["score"]), r.get("created_at") or ""))[:LOWEST_CALLS_SHOWN]
    leads = _lead_names(db, tenant_id, [str(r["lead_id"]) for r in lowest if r.get("lead_id")])
    return {
        "period": period, "available": True, "callers": people,
        "lowest_calls": [{
            "call_log_id": str(r["id"]), "caller_id": str(r["caller_id"]), "caller_name": names.get(str(r["caller_id"])),
            "score": round(float(r["score"]), 1), "at": r.get("created_at"),
            "lead_id": str(r["lead_id"]) if r.get("lead_id") else None,
            "lead_name": leads.get(str(r["lead_id"])) or None if r.get("lead_id") else None,
        } for r in lowest],
    }


# ── Results ──────────────────────────────────────────────────────────────────


def results(db, ctx: dict, period: str, now: datetime | None = None) -> dict:
    """Calls -> orders -> money per telecaller. Orders = paid orders sold by that person in the days;
    money = their sales before GST (the same number Reports shows), only for people with deals.view."""
    bounds = period_bounds(period, RESULT_DAYS, now)
    assert bounds is not None
    tenant_id = ctx["tenant_id"]
    sees_money = _has_permission(ctx, "deals.view")
    callers = visible_callers(db, ctx)
    ids = [str(c["id"]) for c in callers]

    calls = safe(lambda: paged(lambda: (
        db.table("call_logs").select("id,caller_id,manual_status").eq("tenant_id", tenant_id)
        .in_("caller_id", ids).gte("created_at", bounds[0]).lt("created_at", bounds[1]))), [], "calls") if ids else []
    deals = safe(lambda: paged(lambda: (
        db.table("deals").select("id,sold_by,total_paise,gst_paise").eq("tenant_id", tenant_id).eq("stage", "won")
        .in_("sold_by", ids).gte("won_at", bounds[0]).lt("won_at", bounds[1]))), [], "orders") if ids else []

    rows = {cid: {"calls": 0, "connected": 0, "orders": 0, "revenue": 0} for cid in ids}
    for r in calls:
        row = rows.get(str(r["caller_id"]))
        if row is not None:
            row["calls"] += 1
            row["connected"] += 1 if r.get("manual_status") == "connected" else 0
    for d in deals:
        row = rows.get(str(d["sold_by"]))
        if row is not None:
            row["orders"] += 1
            row["revenue"] += int(d.get("total_paise") or 0) - int(d.get("gst_paise") or 0)

    def shape(cid: str | None, name: str | None, row: dict) -> dict:
        out: dict = {"calls": row["calls"], "connected": row["connected"], "orders": row["orders"]}
        if cid is not None:
            out = {"caller_id": cid, "name": name, **out}
        if sees_money:
            out["revenue_paise"] = row["revenue"]
        return out

    people = [shape(str(c["id"]), _name(c), rows[str(c["id"])]) for c in callers]
    total = {k: sum(r[k] for r in rows.values()) for k in ("calls", "connected", "orders", "revenue")}
    return {"period": period, "callers": people, "totals": shape(None, None, total)}
