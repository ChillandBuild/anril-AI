"""
Analytics routes — service metrics for WhatsApp, telecalling, and lead funnel.
"""

import asyncio
import csv
import io
import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role
from app.services.pagination import fetch_all_rows
from app.services.inbound_leads_logic import INBOUND_SOURCES, aggregate_inbound
from app.services.assignment import get_telecalling_config
from app.services.call_evaluation import strip_evaluation
from app.services.call_wrapup import CONNECTS, OUTCOMES, connect_rate as wrapup_connect_rate
from app.services.analytics_compare import (
    CSV_FIELDNAMES,
    align_series,
    build_deltas,
    build_summary,
    compare_csv_rows,
    fill_days,
    previous_period,
    resolve_period,
    summarise_movement,
)
from app.utils.db_retry import execute_with_retry_async

logger = logging.getLogger(__name__)
router = APIRouter()

IST_OFFSET = timedelta(hours=5, minutes=30)


def _tenant_id_for_permission(ctx: dict, permissions: set[str]) -> str:
    user_permissions = set(ctx.get("permissions") or [])
    if ctx.get("role") == "owner" or user_permissions.intersection(permissions):
        return ctx["tenant_id"]
    required = " or ".join(sorted(permissions))
    raise HTTPException(status_code=403, detail=f"Permission required: {required}")


def get_dashboard_analytics_tenant_id(ctx: dict = Depends(get_tenant_and_role)) -> str:
    return _tenant_id_for_permission(ctx, {"dashboard.view", "analytics.view"})


def get_analytics_tenant_id(ctx: dict = Depends(get_tenant_and_role)) -> str:
    return _tenant_id_for_permission(ctx, {"analytics.view"})


def require_analytics_view(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    _tenant_id_for_permission(ctx, {"analytics.view"})
    return ctx


def _week_start() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()


def _range_params(range_str: str) -> tuple[datetime, list[str]]:
    """Return (window_start_utc, list_of_date_iso_strings) for a range value."""
    now = datetime.now(timezone.utc)
    if range_str == "today":
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_iso = [now.date().isoformat()]
    elif range_str == "30d":
        start_dt = now - timedelta(days=30)
        days_iso = [(now - timedelta(days=i)).date().isoformat() for i in range(29, -1, -1)]
    else:  # default "7d"
        start_dt = now - timedelta(days=7)
        days_iso = [(now - timedelta(days=i)).date().isoformat() for i in range(6, -1, -1)]
    return start_dt, days_iso


def _resolve_window(
    range_str: str,
    start: str | None,
    end: str | None,
    calendar_timezone: Literal["UTC", "Asia/Kolkata"] = "UTC",
) -> tuple[datetime, datetime, list[str]]:
    """Return (window_start_utc, window_end_utc, day_iso_list).

    `calendar_timezone` is opt-in so existing callers retain UTC bounds and
    rolling preset windows. Asia/Kolkata requests use the same inclusive
    calendar dates and half-open UTC bounds as `/compare`.
    """
    if start and end:
        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except ValueError as exc:
            raise ValueError("start and end must be YYYY-MM-DD") from exc
        if end_date < start_date:
            raise ValueError("end must not be earlier than start")
        utc_offset = IST_OFFSET if calendar_timezone == "Asia/Kolkata" else timedelta(0)
        window_start_dt = (
            datetime.combine(start_date, datetime.min.time(), timezone.utc) - utc_offset
        )
        window_end_dt = (
            datetime.combine(end_date + timedelta(days=1), datetime.min.time(), timezone.utc)
            - utc_offset
        )
        days_iso = []
        cursor = start_date
        while cursor <= end_date:
            days_iso.append(cursor.isoformat())
            cursor += timedelta(days=1)
        return window_start_dt, window_end_dt, days_iso

    if calendar_timezone == "Asia/Kolkata":
        today_ist = (datetime.now(timezone.utc) + IST_OFFSET).date()
        day_count = 1 if range_str == "today" else 30 if range_str == "30d" else 7
        start_date = today_ist - timedelta(days=day_count - 1)
        window_start_dt = (
            datetime.combine(start_date, datetime.min.time(), timezone.utc) - IST_OFFSET
        )
        window_end_dt = (
            datetime.combine(today_ist + timedelta(days=1), datetime.min.time(), timezone.utc)
            - IST_OFFSET
        )
        days_iso = [
            (start_date + timedelta(days=i)).isoformat() for i in range(day_count)
        ]
        return window_start_dt, window_end_dt, days_iso

    window_start_dt, days_iso = _range_params(range_str)
    return window_start_dt, datetime.now(timezone.utc), days_iso


def _bucket_inbound_leads(
    leads: list[dict], calendar_timezone: Literal["UTC", "Asia/Kolkata"]
) -> list[dict]:
    """Give the UTC-based aggregator local date keys for opted-in IST callers."""
    if calendar_timezone == "UTC":
        return leads

    ist = timezone(IST_OFFSET)
    bucketed = []
    for lead in leads:
        created_at = lead.get("created_at") or ""
        try:
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            day = created_dt.astimezone(ist).date().isoformat()
        except ValueError:
            day = created_at
        bucketed.append({**lead, "created_at": day})
    return bucketed


def _ist_hour(utc_iso: str) -> int:
    """Convert a UTC ISO string to IST hour (int)."""
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        ist = dt + IST_OFFSET
        return ist.hour
    except Exception:
        return -1


def _ist_today_start_utc() -> datetime:
    """Midnight IST expressed as a UTC datetime."""
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + IST_OFFSET
    midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_ist - IST_OFFSET


def _to_ist_date(iso_ts: str | None) -> str:
    """Convert a UTC ISO timestamp to its IST calendar date (YYYY-MM-DD)."""
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt + IST_OFFSET).date().isoformat()
    except ValueError:
        return iso_ts[:10]


def _manual_status_breakdown(logs: list[dict]) -> dict[str, int]:
    counts = {key: 0 for key in CONNECTS}
    for log in logs:
        status = log.get("manual_status")
        if status in counts:
            counts[status] += 1
    return counts


def _followups_scheduled(logs: list[dict]) -> int:
    """"Callback Today" (TeamCallsSection) counts wrap-ups where the telecaller
    picked call_later, not every call that happens to carry a next_action_at (a retry
    reminder from a no-connect, or a hot/warm next-step time, are not callbacks)."""
    return sum(1 for log in logs if log.get("outcome") == "call_later")


def _caller_idle_minutes(
    caller_logs: list[dict],
    caller_status_logs: list[dict],
    window_start: datetime,
    window_end: datetime,
) -> float:
    """Idle minutes for one caller in [window_start, window_end): merged 'active'
    interval minutes minus talk minutes. Mirrors the per-caller logic in the main
    telecalling endpoint."""
    intervals = []
    for sl in caller_status_logs:
        if sl.get("status") != "active":
            continue
        s_time = datetime.fromisoformat(sl["started_at"].replace("Z", "+00:00"))
        s_time = max(s_time, window_start)
        e_time = (
            datetime.fromisoformat(sl["ended_at"].replace("Z", "+00:00"))
            if sl.get("ended_at")
            else window_end
        )
        e_time = min(e_time, window_end)
        if s_time < e_time:
            intervals.append((s_time, e_time))

    intervals.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    active_minutes = sum((e - s).total_seconds() for s, e in merged) / 60.0
    talk_seconds = sum(l["duration_seconds"] for l in caller_logs if l.get("duration_seconds") is not None)
    talk_minutes = talk_seconds / 60.0
    return max(0.0, active_minutes - talk_minutes)


def _window_aggregate(
    logs: list[dict],
    status_logs: list[dict],
    caller_ids: list[str],
    window_start: datetime,
    window_end: datetime,
    day_count: int,
) -> dict:
    """Aggregate metrics for a window, comparable in magnitude to the daily 'today'
    headline. Count metrics (calls, conversions, idle_minutes) are divided by
    day_count to yield a per-day figure; rate/mean metrics are window-wide."""
    win_logs = [
        l for l in logs
        if window_start <= datetime.fromisoformat(l["created_at"].replace("Z", "+00:00")) < window_end
    ]
    win_status = [
        sl for sl in status_logs
        if window_start <= datetime.fromisoformat(sl["started_at"].replace("Z", "+00:00")) < window_end
    ]

    calls = len(win_logs)
    connect_rate = wrapup_connect_rate(win_logs)
    conversions = sum(1 for l in win_logs if l.get("outcome") == "converted")

    durations = [l["duration_seconds"] for l in win_logs if l.get("duration_seconds") is not None]
    avg_talk_seconds = round(sum(durations) / len(durations), 1) if durations else 0.0

    total_idle = 0.0
    for cid in caller_ids:
        c_logs = [l for l in win_logs if str(l.get("caller_id")) == cid]
        c_status = [sl for sl in win_status if str(sl.get("caller_id")) == cid]
        total_idle += _caller_idle_minutes(c_logs, c_status, window_start, window_end)

    days = max(day_count, 1)
    return {
        "calls": round(calls / days, 1),
        "connect_rate": connect_rate,
        "conversions": round(conversions / days, 1),
        "avg_talk_seconds": avg_talk_seconds,
        "idle_minutes": round(total_idle / days, 1),
    }


@router.get("/template-performance")
async def template_performance(
    range: str = Query("7d"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    calendar_timezone: Literal["UTC", "Asia/Kolkata"] = Query("Asia/Kolkata", alias="timezone"),
    tenant_id: str = Depends(get_analytics_tenant_id),
):
    """Per-template broadcast performance: Sent / Read / Replied / Hot leads."""
    db = get_supabase()
    try:
        window_start, window_end, _ = _resolve_window(
            range, start, end, calendar_timezone,
        )
        res = await asyncio.to_thread(
            db.rpc(
                "template_performance_range",
                {
                    "p_tenant_id": tenant_id,
                    "p_start": window_start.isoformat(),
                    "p_end": window_end.isoformat(),
                },
            ).execute,
        )
        return {"data": res.data or []}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        logger.error(f"template_performance failed for tenant {tenant_id}: {e}")
        return {"data": []}


@router.get("/telecalling")
async def telecalling_analytics(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    tenant_id: str = Depends(get_analytics_tenant_id),
):
    db = get_supabase()
    is_sim = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi") == "sim_basic"

    # Tenant is IST -- "today" is the IST calendar day, not UTC's.
    now = datetime.now(timezone.utc)
    today_start = _ist_today_start_utc()
    week = _week_start()

    # Reporting window: defaults to "today" when no from/to given.
    if from_date and to_date:
        try:
            # A picked date range means IST calendar days -- the same
            # definition this route's own "today" above already uses. Built at
            # UTC midnight, every custom range ran 5.5 hours late (1 Aug-7 Aug
            # actually fetched 1 Aug 05:30 IST to 8 Aug 05:30 IST).
            range_start = (
                datetime.combine(
                    date.fromisoformat(from_date), datetime.min.time(), timezone.utc
                )
                - IST_OFFSET
            )
            range_end_exclusive = (
                datetime.combine(
                    date.fromisoformat(to_date) + timedelta(days=1),
                    datetime.min.time(),
                    timezone.utc,
                )
                - IST_OFFSET
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="from/to must be in YYYY-MM-DD format")
    else:
        range_start = today_start
        range_end_exclusive = None
    range_start_iso = range_start.isoformat()
    range_end_for_clip = min(range_end_exclusive, now) if range_end_exclusive else now

    logs_today_query = (
        db.table("call_logs")
        .select("id,duration_seconds,outcome,manual_status,next_action_at,provider,feedback_source,caller_id,created_at,score,score_status,lead_id,leads(created_at,assigned_at)")
        .eq("tenant_id", tenant_id)
        .gte("created_at", range_start_iso)
    )
    if range_end_exclusive:
        logs_today_query = logs_today_query.lt("created_at", range_end_exclusive.isoformat())

    status_logs_query = (
        db.table("caller_status_logs")
        .select("id,caller_id,status,started_at,ended_at")
        .eq("tenant_id", tenant_id)
        .gte("started_at", range_start_iso)
    )
    if range_end_exclusive:
        status_logs_query = status_logs_query.lt("started_at", range_end_exclusive.isoformat())

    # These five reads are independent — run them concurrently off the event loop.
    logs_today_exec, logs_week_exec, all_time_res, status_logs_exec, callers_exec = await asyncio.gather(
        asyncio.to_thread(logs_today_query.execute),
        asyncio.to_thread(
            db.table("call_logs")
            .select("id,caller_id")
            .eq("tenant_id", tenant_id)
            .gte("created_at", week)
            .execute
        ),
        asyncio.to_thread(
            db.rpc("get_telecalling_all_time_stats", {"p_tenant_id": tenant_id}).execute
        ),
        asyncio.to_thread(status_logs_query.execute),
        asyncio.to_thread(
            db.table("callers")
            .select("id,name,user_id")
            .eq("tenant_id", tenant_id)
            .eq("active", True)
            .execute
        ),
    )
    logs_today_res = logs_today_exec.data or []
    logs_week_res = logs_week_exec.data or []
    all_time_data = (all_time_res.data or {}) if all_time_res else {}
    status_logs_today = status_logs_exec.data or []
    all_callers = callers_exec.data or []

    owner_row = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").limit(1).execute()
    owner_user_id = (owner_row.data[0] if owner_row.data else {}).get("user_id")
    callers_res = [c for c in all_callers if c.get("user_id") != owner_user_id] if owner_user_id else all_callers

    # Exclude the owner/admin's own calls from team aggregates (Invariant 13: admin is
    # excluded from ALL telecaller metrics). A null caller_id can only be an owner direct
    # call — telecallers always carry a caller_id — so drop those plus any owner caller-record
    # calls. Keeps the banner consistent with the owner-excluded leaderboard below.
    owner_caller_ids = {c["id"] for c in all_callers if c.get("user_id") == owner_user_id}
    logs_today_res = [l for l in logs_today_res if l.get("caller_id") is not None and l.get("caller_id") not in owner_caller_ids]
    logs_week_res = [l for l in logs_week_res if l.get("caller_id") is not None and l.get("caller_id") not in owner_caller_ids]

    calls_today = len(logs_today_res)
    calls_this_week = len(logs_week_res)
    conversions_today = sum(1 for l in logs_today_res if l.get("outcome") == "converted")

    # All-time durations and outcomes from RPC
    avg_duration_seconds = all_time_data.get("avg_duration_seconds")
    if avg_duration_seconds == 0:
        avg_duration_seconds = None

    outcome_breakdown = {key: 0 for key in OUTCOMES}
    rpc_breakdown = all_time_data.get("outcome_breakdown") or {}
    for k, v in rpc_breakdown.items():
        if k in outcome_breakdown:
            outcome_breakdown[k] = v

    manual_status_breakdown = _manual_status_breakdown(logs_today_res)

    # calls_per_hour — IST hours 9–18, today's calls
    hour_counts: dict[int, int] = {h: 0 for h in range(9, 19)}
    # calls_per_slot — 30-min slots 09:00–17:30 (18 slots)
    slots = [f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 30)]
    slot_counts: dict[str, int] = {s: 0 for s in slots}
    slot_caller_counts: dict[str, dict[str, int]] = {s: {} for s in slots}

    for log in logs_today_res:
        raw_ts = log.get("created_at") or ""
        if not raw_ts:
            continue
        ist_h = _ist_hour(raw_ts)
        if ist_h in hour_counts:
            hour_counts[ist_h] += 1
        # determine slot
        try:
            dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            ist_dt = dt + IST_OFFSET
            slot_min = 0 if ist_dt.minute < 30 else 30
            slot_key = f"{ist_dt.hour:02d}:{slot_min:02d}"
            if slot_key in slot_counts:
                slot_counts[slot_key] += 1
                cid = log.get("caller_id")
                if cid:
                    slot_caller_counts[slot_key][str(cid)] = slot_caller_counts[slot_key].get(str(cid), 0) + 1
        except Exception:
            pass

    hour_labels = {
        9: "9 AM", 10: "10 AM", 11: "11 AM", 12: "12 PM",
        13: "1 PM", 14: "2 PM", 15: "3 PM", 16: "4 PM",
        17: "5 PM", 18: "6 PM",
    }
    calls_per_hour = [
        {"hour": h, "label": hour_labels[h], "count": hour_counts[h]}
        for h in range(9, 19)
    ]
    calls_per_slot = [
        {"slot": s, "count": slot_counts[s], "caller_counts": slot_caller_counts[s]}
        for s in slots
    ]

    # per-caller conversion rates (all-time) from RPC
    caller_total: dict[str, int] = {}
    caller_converted: dict[str, int] = {}
    rpc_caller_stats = all_time_data.get("caller_stats") or {}
    for cid_str, stats_dict in rpc_caller_stats.items():
        caller_total[cid_str] = stats_dict.get("total", 0)
        caller_converted[cid_str] = stats_dict.get("converted", 0)

    # Team-wide aggregates
    team_connected_calls = [l for l in logs_today_res if l.get("manual_status") == "connected"]
    team_connect_rate = wrapup_connect_rate(logs_today_res)

    today_dur_all = [l["duration_seconds"] for l in logs_today_res if l.get("duration_seconds") is not None]
    team_avg_talk_seconds = round(sum(today_dur_all) / len(today_dur_all), 1) if today_dur_all else 0.0
    team_talk_minutes_today = round(sum(today_dur_all) / 60, 1) if today_dur_all else 0.0

    all_idle_minutes = []
    all_gaps = []
    all_longest_idles = []
    all_bunking_flags = []
    all_speed_to_leads = []
    all_quality_scores = []

    per_caller = []
    for c in callers_res:
        cid = c["id"]
        cid_str = str(cid)

        caller_calls = [l for l in logs_today_res if str(l.get("caller_id")) == cid_str]
        c_calls_count = len(caller_calls)
        c_connect_rate = wrapup_connect_rate(caller_calls)

        c_talk_durations = [l["duration_seconds"] for l in caller_calls if l.get("duration_seconds") is not None]
        c_avg_talk_seconds = round(sum(c_talk_durations) / len(c_talk_durations), 1) if c_talk_durations else 0.0
        c_talk_minutes_today = round(sum(c_talk_durations) / 60, 1) if c_talk_durations else 0.0

        # Status intervals clipping
        c_status_logs = [log for log in status_logs_today if str(log.get("caller_id")) == cid_str]
        c_active_intervals = []
        for log in c_status_logs:
            s_time = datetime.fromisoformat(log["started_at"].replace("Z", "+00:00"))
            s_time = max(s_time, range_start)
            e_time = datetime.fromisoformat(log["ended_at"].replace("Z", "+00:00")) if log.get("ended_at") else range_end_for_clip
            e_time = max(e_time, range_start)
            if s_time < e_time and log["status"] == "active":
                c_active_intervals.append((s_time, e_time))

        # Merge active intervals
        c_active_intervals.sort(key=lambda x: x[0])
        merged_active = []
        for start, end in c_active_intervals:
            if not merged_active:
                merged_active.append((start, end))
            else:
                prev_start, prev_end = merged_active[-1]
                if start <= prev_end:
                    merged_active[-1] = (prev_start, max(prev_end, end))
                else:
                    merged_active.append((start, end))

        total_active_seconds = sum((end - start).total_seconds() for start, end in merged_active)
        c_active_minutes_today = total_active_seconds / 60.0
        c_idle_minutes_today = max(0.0, c_active_minutes_today - c_talk_minutes_today)
        all_idle_minutes.append(c_idle_minutes_today)

        # Gaps
        c_gaps = []
        c_longest_idle = 0.0
        sorted_calls = sorted(caller_calls, key=lambda x: x["created_at"])

        def get_active_overlap(gs, ge):
            if gs >= ge:
                return 0.0
            overlap = 0.0
            for as_, ae_ in merged_active:
                os = max(gs, as_)
                oe = min(ge, ae_)
                if os < oe:
                    overlap += (oe - os).total_seconds()
            return overlap

        if merged_active:
            first_active_start = merged_active[0][0]
            if sorted_calls:
                first_call_start = datetime.fromisoformat(sorted_calls[0]["created_at"].replace("Z", "+00:00"))
                gap_before = get_active_overlap(first_active_start, first_call_start)
                if gap_before > 0:
                    c_gaps.append(gap_before)
                for i in range(1, len(sorted_calls)):
                    prev_call_end = datetime.fromisoformat(sorted_calls[i-1]["created_at"].replace("Z", "+00:00")) + timedelta(seconds=sorted_calls[i-1].get("duration_seconds") or 0)
                    curr_call_start = datetime.fromisoformat(sorted_calls[i]["created_at"].replace("Z", "+00:00"))
                    gap = get_active_overlap(prev_call_end, curr_call_start)
                    if gap > 0:
                        c_gaps.append(gap)
                last_call_end = datetime.fromisoformat(sorted_calls[-1]["created_at"].replace("Z", "+00:00")) + timedelta(seconds=sorted_calls[-1].get("duration_seconds") or 0)
                gap_after = get_active_overlap(last_call_end, range_end_for_clip)
                if gap_after > 0:
                    c_gaps.append(gap_after)
            else:
                c_gaps.append(total_active_seconds)

            c_longest_idle = max(c_gaps) if c_gaps else 0.0

        c_avg_gap_seconds = sum(c_gaps) / len(c_gaps) if c_gaps else 0.0
        all_gaps.extend(c_gaps)
        all_longest_idles.append(c_longest_idle)

        # Bunking: idle ≥15 min between calls while the caller was active.
        c_bunking_flag = c_longest_idle >= 900
        all_bunking_flags.append(c_bunking_flag)

        # speed_to_lead_min
        # speed_to_lead: minutes from assignment → the FIRST call per lead, median.
        first_call_by_lead: dict = {}
        for log in caller_calls:
            lid = log.get("lead_id")
            if not lid:
                continue
            if lid not in first_call_by_lead or log["created_at"] < first_call_by_lead[lid]["created_at"]:
                first_call_by_lead[lid] = log
        c_speed_to_lead_list = []
        for log in first_call_by_lead.values():
            assigned_str = (log.get("leads") or {}).get("assigned_at")
            if assigned_str:
                assigned_dt = datetime.fromisoformat(assigned_str.replace("Z", "+00:00"))
                call_created = datetime.fromisoformat(log["created_at"].replace("Z", "+00:00"))
                diff = (call_created - assigned_dt).total_seconds() / 60.0
                if diff >= 0:
                    c_speed_to_lead_list.append(diff)
                    all_speed_to_leads.append(diff)
        c_speed_to_lead_min = round(statistics.median(c_speed_to_lead_list), 1) if c_speed_to_lead_list else None

        # Average of this window's scored calls (short, no-answer and unscored calls don't count).
        c_scores = [
            float(log["score"]) for log in caller_calls
            if log.get("score_status") == "scored" and log.get("score") is not None
        ]
        all_quality_scores.extend(c_scores)
        c_avg_score = round(sum(c_scores) / len(c_scores), 1) if c_scores else None

        total = caller_total.get(cid_str, 0)
        converted = caller_converted.get(cid_str, 0)
        conv_rate = round(converted / total, 4) if total > 0 else None

        per_caller_row = {
            "caller_id": cid,
            "name": c.get("name"),
            "calls_today": c_calls_count,
            "total_minutes_today": c_talk_minutes_today,
            "conversion_rate": conv_rate,
            "connect_rate": c_connect_rate,
            "avg_talk_seconds": c_avg_talk_seconds,
            "talk_minutes_today": c_talk_minutes_today,
            "idle_minutes_today": round(c_idle_minutes_today, 1),
            "avg_gap_seconds": round(c_avg_gap_seconds, 1),
            "longest_idle_seconds": round(c_longest_idle, 1),
            "bunking_flag": c_bunking_flag,
            "speed_to_lead_min": c_speed_to_lead_min,
        }
        # SIM clients get no evaluation: no per-caller score, no scored-call count.
        if not is_sim:
            per_caller_row["overall_score"] = c_avg_score
            per_caller_row["scored_calls"] = len(c_scores)
        per_caller.append(per_caller_row)

    # Comparison block — fixed daily-report baselines anchored to REAL today (UTC),
    # independent of the from/to reporting window. yesterday = the day before today;
    # avg_7d = trailing 7 full days before today (today excluded), per-day averaged.
    caller_id_strs = [str(c["id"]) for c in callers_res]
    comp_window_start = today_start - timedelta(days=7)
    comp_window_start_iso = comp_window_start.isoformat()
    yesterday_start = today_start - timedelta(days=1)

    comp_logs = (
        await asyncio.to_thread(
            db.table("call_logs")
            .select("id,duration_seconds,outcome,manual_status,caller_id,created_at")
            .eq("tenant_id", tenant_id)
            .gte("created_at", comp_window_start_iso)
            .lt("created_at", today_start.isoformat())
            .execute
        )
    ).data or []
    comp_status = (
        await asyncio.to_thread(
            db.table("caller_status_logs")
            .select("id,caller_id,status,started_at,ended_at")
            .eq("tenant_id", tenant_id)
            .gte("started_at", comp_window_start_iso)
            .lt("started_at", today_start.isoformat())
            .execute
        )
    ).data or []

    comparison = {
        "yesterday": _window_aggregate(
            comp_logs, comp_status, caller_id_strs, yesterday_start, today_start, 1
        ),
        "avg_7d": _window_aggregate(
            comp_logs, comp_status, caller_id_strs, comp_window_start, today_start, 7
        ),
    }

    team_idle_minutes_today = round(sum(all_idle_minutes), 1) if all_idle_minutes else 0.0
    team_avg_gap_seconds = round(sum(all_gaps) / len(all_gaps), 1) if all_gaps else 0.0
    team_longest_idle_seconds = round(max(all_longest_idles), 1) if all_longest_idles else 0.0
    team_bunking_flag = any(all_bunking_flags) if all_bunking_flags else False
    team_speed_to_lead_min = round(statistics.median(all_speed_to_leads), 1) if all_speed_to_leads else None
    team_quality_avg = round(sum(all_quality_scores) / len(all_quality_scores), 1) if all_quality_scores else None

    result = {
        "calls_today": calls_today,
        "calls_attempted": calls_today,
        "connected_calls": len(team_connected_calls),
        "followups_scheduled": _followups_scheduled(logs_today_res),
        "calls_this_week": calls_this_week,
        "avg_duration_seconds": avg_duration_seconds,
        "outcome_breakdown": outcome_breakdown,
        "manual_status_breakdown": manual_status_breakdown,
        "conversions_today": conversions_today,
        "per_caller": per_caller,
        "total_minutes_today": team_talk_minutes_today,
        "calls_per_hour": calls_per_hour,
        "calls_per_slot": calls_per_slot,
        "connect_rate": team_connect_rate,
        "avg_talk_seconds": team_avg_talk_seconds,
        "talk_minutes_today": team_talk_minutes_today,
        "idle_minutes_today": team_idle_minutes_today,
        "avg_gap_seconds": team_avg_gap_seconds,
        "longest_idle_seconds": team_longest_idle_seconds,
        "bunking_flag": team_bunking_flag,
        "speed_to_lead_min": team_speed_to_lead_min,
        "comparison": comparison,
    }
    # SIM clients get no evaluation: no team-wide quality average either.
    if not is_sim:
        result["quality_avg"] = team_quality_avg
    return result


@router.get("/qa-queue")
async def qa_queue(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    caller_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    ctx: dict = Depends(require_analytics_view),
):
    """QA review feed: the window's scored calls, lowest score first, so the
    weakest calls get reviewed. Same IST-day window as the Performance filter;
    the owner's own calls are left out like every other telecaller metric.
    SIM clients get no evaluation at all -- this route doesn't exist for them."""
    from app.services.call_transcript import mask_transcripts

    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    if get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi") == "sim_basic":
        raise HTTPException(status_code=404, detail="Not available for this client")
    today = (datetime.now(timezone.utc) + IST_OFFSET).date()
    try:
        start_day = date.fromisoformat(from_date) if from_date else today
        end_day = date.fromisoformat(to_date) if to_date else start_day
    except ValueError:
        raise HTTPException(status_code=400, detail="from/to must be in YYYY-MM-DD format")
    start = datetime.combine(start_day, datetime.min.time(), timezone.utc) - IST_OFFSET
    end = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), timezone.utc) - IST_OFFSET

    owner = db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner").limit(1).execute()
    owner_user_id = (owner.data[0] if owner.data else {}).get("user_id")
    owner_caller_ids: list[str] = []
    if owner_user_id:
        rows = db.table("callers").select("id").eq("tenant_id", tenant_id).eq("user_id", owner_user_id).execute()
        owner_caller_ids = [r["id"] for r in (rows.data or [])]

    query = (
        db.table("call_logs")
        .select(
            "id,created_at,duration_seconds,status,outcome,manual_status,provider,score,score_status,"
            "evaluation,ai_summary,ai_status,recording_url,transcript,"
            "call_group,talk_share,interruption_count,interruptions_per_5min,score_final,"
            "lead_id,caller_id,leads(name,phone),callers(name)",
            count="exact",
        )
        .eq("tenant_id", tenant_id)
        .eq("score_status", "scored")
        .gte("created_at", start.isoformat())
        .lt("created_at", end.isoformat())
    )
    if caller_id:
        query = query.eq("caller_id", str(caller_id))
    if owner_caller_ids:
        query = query.not_.in_("caller_id", owner_caller_ids)
    offset = (page - 1) * limit
    res = await asyncio.to_thread(
        query.order("score").order("created_at", desc=True).range(offset, offset + limit - 1).execute
    )
    return {"data": mask_transcripts(res.data), "total": res.count or 0, "page": page, "limit": limit}


@router.get("/caller-timeline")
async def caller_timeline(
    caller_id: UUID = Query(...),
    date: str | None = Query(None),
    ctx: dict = Depends(require_analytics_view),
):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    
    if not date:
        # Tenant is IST. UTC's "today" is still yesterday until 05:30 IST, so
        # opening this page overnight showed the previous day's timeline.
        # NB: the `date` query param shadows datetime.date inside this
        # function -- parse with strptime, not date.fromisoformat.
        date = (datetime.now(timezone.utc) + IST_OFFSET).strftime("%Y-%m-%d")
        
    try:
        day_start = (
            datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            - IST_OFFSET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
        
    day_end = day_start + timedelta(days=1)
    day_start_iso = day_start.isoformat()
    day_end_iso = day_end.isoformat()
    
    calls = (
        await asyncio.to_thread(
            db.table("call_logs")
            .select("id,created_at,duration_seconds,outcome,manual_status,lead_id,leads(name,phone)")
            .eq("caller_id", str(caller_id))
            .eq("tenant_id", tenant_id)
            .gte("created_at", day_start_iso)
            .lt("created_at", day_end_iso)
            .order("created_at")
            .execute
        )
    ).data or []
    
    status_logs = (
        await asyncio.to_thread(
            db.table("caller_status_logs")
            .select("id,status,started_at,ended_at")
            .eq("caller_id", str(caller_id))
            .eq("tenant_id", tenant_id)
            .gte("started_at", day_start_iso)
            .lt("started_at", day_end_iso)
            .order("started_at")
            .execute
        )
    ).data or []
    
    events = []
    
    for s in status_logs:
        events.append({
            "type": "status",
            "id": s["id"],
            "status": s["status"],
            "started_at": s["started_at"],
            "ended_at": s["ended_at"],
            "duration_seconds": None,
        })
        
    for c in calls:
        lead = c.get("leads") or {}
        events.append({
            "type": "call",
            "id": c["id"],
            "started_at": c["created_at"],
            "duration_seconds": c.get("duration_seconds") or 0,
            "outcome": c.get("outcome"),
            "manual_status": c.get("manual_status"),
            "lead_name": lead.get("name") or "Unknown",
            "lead_phone": lead.get("phone") or "",
        })
        
    events.sort(key=lambda x: x["started_at"])
    
    return {"data": events}


@router.get("/telecalling/export")
async def export_telecalling(
    ctx: dict = Depends(require_analytics_view)
):
    tenant_id = ctx["tenant_id"]
    db = get_supabase()
    is_sim = get_telecalling_config(tenant_id, db=db).get("calling_provider", "telecmi") == "sim_basic"

    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=90)).isoformat()

    rows = (
        await asyncio.to_thread(
            db.table("call_logs")
            .select("id,created_at,caller_id,lead_id,duration_seconds,outcome,disposition,manual_status,status,provider,feedback_source,recording_url,score,score_status,callers(name),leads(name,phone)")
            .eq("tenant_id", tenant_id)
            .gte("created_at", start_date)
            .order("created_at", desc=True)
            .limit(5000)
            .execute
        )
    ).data or []
    rows = strip_evaluation(rows, is_sim)

    output = io.StringIO()
    fieldnames = [
        "call_log_id", "created_at", "caller_id", "caller_name",
        "lead_id", "lead_name", "lead_phone", "duration_seconds",
        "outcome", "disposition", "manual_status", "status", "provider", "feedback_source", "recording_url",
    ]
    # SIM clients get no evaluation at all: no score columns in the export either.
    if not is_sim:
        fieldnames += ["score", "score_status"]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in rows:
        record = {
            "call_log_id": row["id"],
            "created_at": row["created_at"],
            "caller_id": row.get("caller_id") or "",
            "caller_name": (row.get("callers") or {}).get("name") or "",
            "lead_id": row.get("lead_id") or "",
            "lead_name": (row.get("leads") or {}).get("name") or "",
            "lead_phone": (row.get("leads") or {}).get("phone") or "",
            "duration_seconds": row.get("duration_seconds") or 0,
            "outcome": row.get("outcome") or "",
            "disposition": row.get("disposition") or "",
            "manual_status": row.get("manual_status") or "",
            "status": row.get("status") or "",
            "provider": row.get("provider") or "",
            "feedback_source": row.get("feedback_source") or "",
            "recording_url": row.get("recording_url") or "",
        }
        if not is_sim:
            record["score"] = row.get("score") if row.get("score") is not None else ""
            record["score_status"] = row.get("score_status") or ""
        writer.writerow(record)
        
    filename = f"telecalling_calls_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/funnel")
async def funnel_analytics(tenant_id: str = Depends(get_analytics_tenant_id)):
    db = get_supabase()
    week = _week_start()

    leads_all = await fetch_all_rows(
        lambda: db.table("leads")
        .select("id,segment,source,score,created_at")
        .eq("tenant_id", tenant_id)
    )

    total_leads = len(leads_all)

    by_segment: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
    by_source: dict[str, int] = {
        "whatsapp": 0, "instagram": 0, "facebook": 0,
        "telegram": 0, "upload": 0, "manual": 0,
        "indiamart": 0, "justdial": 0,
        "website": 0, "api": 0, "store": 0, "meta_form": 0,
    }
    scores = []
    leads_this_week = 0

    now = datetime.now(timezone.utc)
    hot_aging: dict[str, int] = {"<1d": 0, "1-3d": 0, "3-7d": 0, "7d+": 0}

    for lead in leads_all:
        seg = lead.get("segment")
        if seg in by_segment:
            by_segment[seg] += 1

        src = lead.get("source")
        if src in by_source:
            by_source[src] += 1

        score = lead.get("score")
        if score is not None:
            scores.append(score)

        if (lead.get("created_at") or "") >= week:
            leads_this_week += 1

        # hot lead aging for segment A
        if seg == "A":
            created_str = lead.get("created_at") or ""
            if created_str:
                try:
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    age_days = (now - created_dt.replace(tzinfo=timezone.utc if created_dt.tzinfo is None else created_dt.tzinfo)).days
                    if age_days < 1:
                        hot_aging["<1d"] += 1
                    elif age_days <= 3:
                        hot_aging["1-3d"] += 1
                    elif age_days <= 7:
                        hot_aging["3-7d"] += 1
                    else:
                        hot_aging["7d+"] += 1
                except Exception:
                    pass

    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    # Segment labels for response
    segment_labels = {"A": "Hot", "B": "Warm", "C": "Cold", "D": "Not Interested"}
    score_histogram = [
        {"range": segment_labels[seg], "count": by_segment[seg]}
        for seg in ("A", "B", "C", "D")
    ]
    hot_lead_aging = [
        {"bucket": b, "count": hot_aging[b]}
        for b in ("<1d", "1-3d", "3-7d", "7d+")
    ]

    return {
        "total_leads": total_leads,
        "by_segment": by_segment,
        "by_source": by_source,
        "leads_this_week": leads_this_week,
        "avg_score": avg_score,
        "score_histogram": score_histogram,
        "hot_lead_aging": hot_lead_aging,
    }


def _pct_trend(current: int, prior: int) -> float | None:
    """None when there's no meaningful baseline (prior window had zero
    activity) -- going from 0 to any activity isn't a "% increase," it's new,
    and dividing by zero would misrepresent that."""
    if prior <= 0:
        return None
    return round((current - prior) / prior * 100)


@router.get("/overview")
async def overview_analytics(
    tenant_id: str = Depends(get_dashboard_analytics_tenant_id),
    range: str = Query("7d"),
):
    """Dashboard root — KPIs and N-day series."""
    db = get_supabase()
    now = datetime.now(timezone.utc)
    today_start = _ist_today_start_utc()
    today_ist_date = (now + IST_OFFSET).date()
    today_iso_date = today_ist_date.isoformat()

    window_start_dt, _ = _range_params(range)
    window_span = now - window_start_dt
    prior_window_start_dt = window_start_dt - window_span

    # Tenant is IST -- every "today"/daily bucket in this endpoint (leads,
    # hot leads, messages) keys off IST calendar days, not UTC ones.
    # `range` above is this route's query param, so the `range()` builtin
    # is shadowed here -- build the day list with an explicit loop instead.
    _day_count = 1 if range == "today" else 30 if range == "30d" else 7
    days_iso_ist = []
    _cursor = today_ist_date - timedelta(days=_day_count - 1)
    while _cursor <= today_ist_date:
        days_iso_ist.append(_cursor.isoformat())
        _cursor += timedelta(days=1)

    leads_rows = await fetch_all_rows(
        lambda: db.table("leads")
        .select("id,phone,segment,score,source,created_at,converted_at,ai_enabled,deleted_at,ad_campaign_id")
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
    )

    prior_leads_rows = await fetch_all_rows(
        lambda: db.table("leads")
        .select("id,created_at,converted_at,segment")
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .gte("created_at", prior_window_start_dt.isoformat())
        .lt("created_at", window_start_dt.isoformat())
    )

    daily_leads_map = {d: 0 for d in days_iso_ist}
    # Leads created within the window whose *current* segment is Hot (A) --
    # not a count of hot-segment scoring events, which double-counts a lead
    # every time they get rescored while already Hot. Reflects "of today's
    # new leads, how many are hot right now," updating live as scores change.
    hot_among_new_daily_map = {d: 0 for d in days_iso_ist}
    by_segment = {"A": 0, "B": 0, "C": 0, "D": 0}
    by_segment_today = {"A": 0, "B": 0, "C": 0, "D": 0}
    channel_breakdown = {
        "whatsapp": 0, "instagram": 0, "facebook": 0,
        "telegram": 0, "upload": 0, "manual": 0,
        "indiamart": 0, "justdial": 0,
        "website": 0, "api": 0, "store": 0, "meta_form": 0,
    }
    channel_breakdown_today = {
        "whatsapp": 0, "instagram": 0, "facebook": 0,
        "telegram": 0, "upload": 0, "manual": 0,
        "indiamart": 0, "justdial": 0,
        "website": 0, "api": 0, "store": 0, "meta_form": 0,
    }
    converted_7d = 0
    converted_today = 0
    funnel_inquiries = 0
    funnel_engaged = 0
    funnel_hot = 0
    funnel_converted = 0
    week_start_for_funnel = now - timedelta(days=7)
    ad_attributed_leads = 0
    ad_attributed_leads_today = 0

    for lead in leads_rows:
        created = _to_ist_date(lead.get("created_at"))
        is_today = created == today_iso_date
        if created in daily_leads_map:
            daily_leads_map[created] += 1
        converted_at = lead.get("converted_at")
        if converted_at:
            funnel_converted += 1
            if converted_at >= week_start_for_funnel.isoformat():
                converted_7d += 1
            if converted_at >= today_start.isoformat():
                converted_today += 1
        seg = lead.get("segment")
        if seg in by_segment:
            by_segment[seg] += 1
            if is_today:
                by_segment_today[seg] += 1
        if seg == "A" and created in hot_among_new_daily_map:
            hot_among_new_daily_map[created] += 1
        src = lead.get("source")
        if src in channel_breakdown:
            channel_breakdown[src] += 1
            if is_today:
                channel_breakdown_today[src] += 1
        if lead.get("ad_campaign_id"):
            ad_attributed_leads += 1
            if is_today:
                ad_attributed_leads_today += 1
        funnel_inquiries += 1
        if seg in ("A", "B"):
            funnel_engaged += 1
        if seg == "A":
            funnel_hot += 1

    total_leads = len(leads_rows)

    prior_new_leads = len(prior_leads_rows)
    current_new_leads = sum(daily_leads_map.values())
    daily_leads_trend_pct = _pct_trend(current_new_leads, prior_new_leads)

    # Scans the full leads_rows population, not prior_leads_rows -- a lead's
    # created_at and converted_at can fall in different windows (created 3
    # weeks ago, converted this week), so filtering by created_at would miss
    # it. Bounded above by window_start_dt so conversions already counted in
    # the current converted_7d aren't double-counted into the baseline.
    prior_converted_7d = sum(
        1 for lead in leads_rows
        if lead.get("converted_at")
        and prior_window_start_dt.isoformat() <= lead["converted_at"] < window_start_dt.isoformat()
    )
    converted_7d_trend_pct = _pct_trend(converted_7d, prior_converted_7d)

    new_hot_leads_7d = sum(hot_among_new_daily_map.values())
    prior_hot_among_new = sum(1 for lead in prior_leads_rows if lead.get("segment") == "A")
    new_hot_leads_7d_trend_pct = _pct_trend(new_hot_leads_7d, prior_hot_among_new)

    # Aggregate in SQL, never by pulling raw rows: PostgREST caps result sets
    # at 1000 and returns no error, which was silently dropping 250 of the
    # 1250 messages in a 7-day window (and over half of a 30-day window),
    # under-reporting AI replies as 579 when the true figure was 730.
    # p_timezone='Asia/Kolkata' so "Inbound Today"/"Outbound Today" on the
    # dashboard home reset at IST midnight, not UTC midnight -- this field is
    # only consumed by AiWorkloadSection.tsx, nothing else shares these keys.
    # execute_with_retry_async, not a bare to_thread: postgrest sends an RPC as
    # a POST, and _RetryTransport (db/supabase.py) replays only GET/HEAD/OPTIONS
    # because a dropped write may already have landed. These four RPCs are
    # read-only aggregates, so replaying one is safe -- without it a single
    # "Server disconnected" turned the whole dashboard into an error card.
    daily_msg_rows = (
        await execute_with_retry_async(
            db.rpc("analytics_daily_messages", {
                "p_tenant_id": tenant_id,
                "p_start": window_start_dt.isoformat(),
                "p_end": now.isoformat(),
                "p_channel": None,
                "p_timezone": "Asia/Kolkata",
            })
        )
    ).data or []

    daily_msgs_map = {d: {"inbound": 0, "outbound": 0, "ai": 0, "human": 0} for d in days_iso_ist}
    ai_count = 0
    human_count = 0
    ai_handled_today = 0
    for row in daily_msg_rows:
        day = str(row.get("day") or "")
        ai = int(row.get("ai") or 0)
        human = int(row.get("human") or 0)
        if day in daily_msgs_map:
            daily_msgs_map[day] = {
                "inbound": int(row.get("inbound") or 0),
                "outbound": int(row.get("outbound") or 0),
                "ai": ai,
                "human": human,
            }
        ai_count += ai
        human_count += human
        if day == today_iso_date:
            ai_handled_today = ai

    # unreplied_24h needs per-lead rows, but only over 24h -- a bounded set,
    # explicitly limited so it can never silently truncate the way the
    # window-wide fetch above did.
    recent_msgs = (
        await asyncio.to_thread(
            db.table("messages")
            .select("direction,created_at,lead_id")
            .eq("tenant_id", tenant_id)
            .gte("created_at", (now - timedelta(hours=24)).isoformat())
            .limit(1000)
            .execute
        )
    ).data or []

    last_inbound: dict[str, str] = {}
    last_outbound: dict[str, str] = {}
    for m in recent_msgs:
        ts = m.get("created_at") or ""
        lid = m.get("lead_id")
        if not lid:
            continue
        if m.get("direction") == "inbound":
            if ts > last_inbound.get(lid, ""):
                last_inbound[lid] = ts
        elif m.get("direction") == "outbound":
            if ts > last_outbound.get(lid, ""):
                last_outbound[lid] = ts

    unreplied_24h = sum(
        1 for lid, ts in last_inbound.items()
        if last_outbound.get(lid, "") < ts
    )

    # Cost-per-lead and first-response speed for the selected range. Additive
    # fields only -- the dashboard home and operator console read this same
    # response and must keep working untouched.
    # Returning leads that an ad brought back: an older lead who sent an
    # ad-tagged message on a given day. daily_leads_map above only ever counts
    # leads by created_at, so before this these conversations appeared in no
    # lead count at all. Bounded by the IST day list rather than
    # window_start_dt (a rolling "now - 7 days") so the oldest day in the
    # series is a whole IST day, matching the buckets it is merged into.
    returning_window_start = (
        datetime.combine(
            date.fromisoformat(days_iso_ist[0]), datetime.min.time(), timezone.utc
        )
        - IST_OFFSET
    )

    money_res, response_res, returning_res = await asyncio.gather(
        execute_with_retry_async(
            db.rpc("analytics_period_money", {
                "p_tenant_id": tenant_id,
                "p_start": window_start_dt.isoformat(),
                "p_end": now.isoformat(),
            })
        ),
        execute_with_retry_async(
            db.rpc("analytics_response_times", {
                "p_tenant_id": tenant_id,
                "p_start": window_start_dt.isoformat(),
                "p_end": now.isoformat(),
            })
        ),
        execute_with_retry_async(
            db.rpc("analytics_daily_returning_ad_leads", {
                "p_tenant_id": tenant_id,
                "p_start": returning_window_start.isoformat(),
                "p_end": now.isoformat(),
                "p_timezone": "Asia/Kolkata",
            })
        ),
    )
    money_rows = money_res.data or []
    response_rows = response_res.data or []

    returning_ad_leads_map = {d: 0 for d in days_iso_ist}
    for row in (returning_res.data or []):
        day = str(row.get("day") or "")
        if day in returning_ad_leads_map:
            returning_ad_leads_map[day] = int(row.get("returning_leads") or 0)

    return {
        "money": money_rows[0] if money_rows else {},
        "response_times": response_rows[0] if response_rows else {},
        "daily_leads": [{"day": d, "count": daily_leads_map[d]} for d in days_iso_ist],
        "daily_leads_trend_pct": daily_leads_trend_pct,
        "returning_ad_leads_daily": [
            {"day": d, "count": returning_ad_leads_map[d]} for d in days_iso_ist
        ],
        "daily_messages": [
            {
                "day": d,
                "inbound": daily_msgs_map[d]["inbound"],
                "outbound": daily_msgs_map[d]["outbound"],
                "ai": daily_msgs_map[d]["ai"],
                "human": daily_msgs_map[d]["human"],
            }
            for d in days_iso_ist
        ],
        "funnel": {
            "inquiries": funnel_inquiries,
            "engaged": funnel_engaged,
            "hot": funnel_hot,
            "converted": funnel_converted,
        },
        "ai_vs_human": {"ai": ai_count, "human": human_count},
        "unreplied_24h": unreplied_24h,
        "converted_7d": converted_7d,
        "converted_7d_trend_pct": converted_7d_trend_pct,
        "converted_today": converted_today,
        "ai_handled_today": ai_handled_today,
        "by_segment": by_segment,
        "by_segment_today": by_segment_today,
        "channel_breakdown": channel_breakdown,
        "channel_breakdown_today": channel_breakdown_today,
        "total_leads": total_leads,
        "ad_attributed_leads": ad_attributed_leads,
        "ad_attributed_leads_today": ad_attributed_leads_today,
        "new_hot_leads_7d": new_hot_leads_7d,
        "new_hot_leads_daily": [{"day": d, "count": hot_among_new_daily_map[d]} for d in days_iso_ist],
        "new_hot_leads_7d_trend_pct": new_hot_leads_7d_trend_pct,
    }


SUMMARY_METRICS = (
    "new_leads", "inbound_leads", "outbound_leads",
    "hot", "warm", "cold", "disqualified", "avg_score",
    "messages_in", "messages_out", "ai_replies", "human_replies", "converted",
    "engagement_rate",
)

MONEY_METRICS = (
    "spend", "impressions", "clicks", "ad_leads", "ad_hot_leads",
    "cost_per_lead", "cost_per_hot_lead",
)
RESPONSE_METRICS = ("inbound_total", "answered", "p50_seconds", "p90_seconds")
MOVEMENT_METRICS = ("promoted", "demoted", "promoted_to_hot")

LEAD_SERIES_KEYS = ("inbound", "outbound", "hot", "warm", "cold", "disqualified")
MESSAGE_SERIES_KEYS = ("inbound", "outbound", "ai", "human")


def _ist_bounds(start: date, end: date) -> tuple[str, str]:
    """Inclusive IST dates -> half-open UTC timestamptz bounds for the RPCs."""
    start_utc = datetime.combine(start, datetime.min.time(), timezone.utc) - IST_OFFSET
    end_utc = datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc) - IST_OFFSET
    return start_utc.isoformat(), end_utc.isoformat()


async def _period_payload(db, tenant_id: str, start: date, end: date) -> dict:
    """Fetch summary + both daily series for one period. Three RPCs, concurrent."""
    start_iso, end_iso = _ist_bounds(start, end)
    params = {"p_tenant_id": tenant_id, "p_start": start_iso, "p_end": end_iso}

    summary_res, leads_res, msgs_res, money_res, movement_res, response_res, heatmap_res = await asyncio.gather(
        asyncio.to_thread(db.rpc("analytics_period_summary", params).execute),
        asyncio.to_thread(db.rpc("analytics_daily_leads", params).execute),
        asyncio.to_thread(db.rpc("analytics_daily_messages", params).execute),
        asyncio.to_thread(db.rpc("analytics_period_money", params).execute),
        asyncio.to_thread(db.rpc("analytics_segment_movement", params).execute),
        asyncio.to_thread(db.rpc("analytics_response_times", params).execute),
        asyncio.to_thread(db.rpc("analytics_lead_arrival_heatmap", params).execute),
    )

    def first_row(res) -> dict:
        rows = res.data or []
        return rows[0] if rows else {}

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "summary": first_row(summary_res),
        "money": first_row(money_res),
        "response": first_row(response_res),
        "movement": summarise_movement(movement_res.data or []),
        "daily_leads": fill_days(leads_res.data or [], start, end, LEAD_SERIES_KEYS),
        "daily_messages": fill_days(msgs_res.data or [], start, end, MESSAGE_SERIES_KEYS),
        "heatmap": heatmap_res.data or [],
    }


@router.get("/compare")
async def compare_analytics(
    preset: str = Query("last_7d"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    comparison: Literal["off", "previous", "custom"] = Query("off"),
    comparison_start: str | None = Query(None),
    comparison_end: str | None = Query(None),
    tenant_id: str = Depends(get_dashboard_analytics_tenant_id),
):
    """Return a period, optionally alongside an explicitly selected comparison.

    Day bucketing and period boundaries are IST -- this is an India-based
    product and a UTC "day" starts at 05:30 local, which shifts 6% of rows
    into the wrong bucket.
    """
    today_ist = (datetime.now(timezone.utc) + IST_OFFSET).date()
    try:
        cur_start, cur_end = resolve_period(preset, start, end, today_ist)
        if comparison == "custom":
            prev_start, prev_end = resolve_period(
                "custom", comparison_start, comparison_end, today_ist
            )
        elif comparison == "previous":
            prev_start, prev_end = previous_period(cur_start, cur_end, preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db = get_supabase()
    if comparison == "off":
        current = await _period_payload(db, tenant_id, cur_start, cur_end)
        previous = None
    else:
        current, previous = await asyncio.gather(
            _period_payload(db, tenant_id, cur_start, cur_end),
            _period_payload(db, tenant_id, prev_start, prev_end),
        )

    cur_sum = current["summary"]
    prev_sum = previous["summary"] if previous else {}

    def series_for(source: str, key: str) -> list[dict]:
        return align_series(current[source], previous[source], key) if previous else []

    return {
        "preset": preset,
        "current": {
            "start": current["start"], "end": current["end"],
            "summary": cur_sum,
            "money": current["money"],
            "response": current["response"],
            "movement": current["movement"],
            "daily_segment_mix": [
                {
                    "day": d["day"], "hot": d["hot"], "warm": d["warm"],
                    "cold": d["cold"], "disqualified": d["disqualified"],
                }
                for d in current["daily_leads"]
            ],
            "heatmap": current["heatmap"],
        },
        "previous": {
            "start": previous["start"], "end": previous["end"],
            "summary": prev_sum,
            "money": previous["money"],
            "response": previous["response"],
            "movement": previous["movement"],
        } if previous else None,
        "summary_text": build_summary(cur_sum, prev_sum, cur_start, cur_end) if previous else None,
        "metrics": build_deltas(cur_sum, prev_sum, SUMMARY_METRICS) if previous else {},
        "money_metrics": (
            build_deltas(current["money"], previous["money"], MONEY_METRICS)
            if previous else {}
        ),
        "response_metrics": (
            build_deltas(current["response"], previous["response"], RESPONSE_METRICS)
            if previous else {}
        ),
        "movement_metrics": (
            build_deltas(current["movement"], previous["movement"], MOVEMENT_METRICS)
            if previous else {}
        ),
        "series": {
            "leads_inbound": series_for("daily_leads", "inbound"),
            "leads_outbound": series_for("daily_leads", "outbound"),
            "messages_in": series_for("daily_messages", "inbound"),
            "messages_out": series_for("daily_messages", "outbound"),
        } if previous else {},
    }


@router.get("/compare/export")
async def export_compare(
    preset: str = Query("last_7d"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    comparison: Literal["off", "previous", "custom"] = Query("off"),
    comparison_start: str | None = Query(None),
    comparison_end: str | None = Query(None),
    tenant_id: str = Depends(get_dashboard_analytics_tenant_id),
):
    """Same data as /compare, as a CSV the client can open in Excel."""
    if comparison == "off":
        raise HTTPException(
            status_code=400,
            detail="comparison export requires comparison=previous or comparison=custom",
        )
    payload = await compare_analytics(
        preset=preset,
        start=start,
        end=end,
        comparison=comparison,
        comparison_start=comparison_start,
        comparison_end=comparison_end,
        tenant_id=tenant_id,
    )
    rows = compare_csv_rows(payload["series"])

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    filename = f"comparison_{payload['current']['start']}_vs_{payload['previous']['start']}.csv"
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/messaging")
async def messaging_analytics(
    tenant_id: str = Depends(get_analytics_tenant_id),
    channel: str = Query("all"),
    range: str = Query("7d"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    calendar_timezone: Literal["UTC", "Asia/Kolkata"] = Query(
        "UTC", alias="timezone"
    ),
):
    """Messaging analytics with optional channel filter and date range.

    `start`/`end` (YYYY-MM-DD) override `range` when both are given.
    sent_today/received_today always reflect the real current day regardless
    of range or custom dates -- that is existing, documented behaviour.
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    today_start = (
        _ist_today_start_utc()
        if calendar_timezone == "Asia/Kolkata"
        else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )

    try:
        window_start_dt, window_end_dt, days_iso = _resolve_window(
            range, start, end, calendar_timezone
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Aggregate in SQL -- a raw window fetch hits PostgREST's silent 1000-row
    # cap (1250 rows in 7 days, 2143 in 30).
    rpc_params = {
        "p_tenant_id": tenant_id,
        "p_start": window_start_dt.isoformat(),
        "p_end": window_end_dt.isoformat(),
        "p_channel": None if channel == "all" else channel,
    }
    daily_res, reply_source_res = await asyncio.gather(
        asyncio.to_thread(
            db.rpc(
                "analytics_daily_messages",
                {**rpc_params, "p_timezone": calendar_timezone},
            ).execute
        ),
        asyncio.to_thread(db.rpc("analytics_reply_sources", rpc_params).execute),
    )
    daily_rows = daily_res.data or []
    reply_source_rows = reply_source_res.data or []

    # sent_today / received_today — always from today regardless of range
    today_q = (
        db.table("messages")
        .select("id,direction")
        .eq("tenant_id", tenant_id)
        .gte("created_at", today_start.isoformat())
    )
    if channel != "all":
        today_q = today_q.eq("channel", channel)
    msgs_today = (await asyncio.to_thread(today_q.execute)).data or []

    sent_today = sum(1 for m in msgs_today if m.get("direction") == "outbound")
    received_today = sum(1 for m in msgs_today if m.get("direction") == "inbound")

    # daily_messages series
    daily_msgs_map = {d: {"inbound": 0, "outbound": 0} for d in days_iso}
    outbound_total = 0
    outbound_ai = 0
    for row in daily_rows:
        day = str(row.get("day") or "")
        if day in daily_msgs_map:
            daily_msgs_map[day] = {
                "inbound": int(row.get("inbound") or 0),
                "outbound": int(row.get("outbound") or 0),
            }
        outbound_total += int(row.get("outbound") or 0)
        outbound_ai += int(row.get("ai") or 0)

    # reply_source breakdown — outbound only (inbound has null reply_source).
    # 'reengagement' is a real, high-volume source (365 messages, 29% of
    # outbound) that previously matched no branch and was silently dropped,
    # so the bar's percentages were computed against an understated total.
    reply_source_counts: dict[str, int] = {
        "ai": 0, "knowledge": 0, "reengagement": 0, "manual": 0, "unknown": 0,
    }
    for row in reply_source_rows:
        source = row.get("reply_source")
        count = int(row.get("total") or 0)
        if source in reply_source_counts:
            reply_source_counts[source] += count
        elif source == "automation":
            reply_source_counts["ai"] += count
        elif source is None:
            key = "unknown" if row.get("is_ai_generated") else "manual"
            reply_source_counts[key] += count
        else:
            # Any future reply_source lands here rather than vanishing.
            reply_source_counts["unknown"] += count

    ai_reply_rate: float | None = round(outbound_ai / outbound_total, 4) if outbound_total > 0 else None

    return {
        "sent_today": sent_today,
        "received_today": received_today,
        "ai_reply_rate": ai_reply_rate,
        "reply_source_breakdown": reply_source_counts,
        "daily_messages": [
            {"day": d, "inbound": daily_msgs_map[d]["inbound"], "outbound": daily_msgs_map[d]["outbound"]}
            for d in days_iso
        ],
    }


@router.get("/ad-performance")
async def ad_performance_summary(tenant_id: str = Depends(get_analytics_tenant_id)):
    db = get_supabase()
    from app.services.growth import build_ad_performance
    return build_ad_performance(tenant_id=tenant_id, db=db)


@router.get("/inbound")
async def inbound_analytics(
    range: str = Query("7d"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    calendar_timezone: Literal["UTC", "Asia/Kolkata"] = Query(
        "UTC", alias="timezone"
    ),
    tenant_id: str = Depends(get_analytics_tenant_id),
):
    """New inbound leads acquired, split organic vs ad. Range: today|7d|30d,
    or pass start/end (YYYY-MM-DD) for an arbitrary window."""
    db = get_supabase()
    try:
        start_dt, end_dt, days_iso = _resolve_window(
            range, start, end, calendar_timezone
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    today_iso = (
        (datetime.now(timezone.utc) + IST_OFFSET).date().isoformat()
        if calendar_timezone == "Asia/Kolkata"
        else datetime.now(timezone.utc).date().isoformat()
    )

    try:
        leads = await fetch_all_rows(
            lambda: db.table("leads")
            .select("id,source,ad_campaign_id,segment,created_at")
            .eq("tenant_id", tenant_id)
            .in_("source", list(INBOUND_SOURCES))
            .is_("deleted_at", "null")
            .gte("created_at", start_dt.isoformat())
            .lt("created_at", end_dt.isoformat())
        )
    except Exception as e:
        logger.error(f"inbound analytics error: {e}")
        leads = []
    return aggregate_inbound(
        _bucket_inbound_leads(leads, calendar_timezone), days_iso, today_iso
    )
