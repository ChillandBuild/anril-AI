import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role, require_permission, invalidate_tenant_cache
from app.services.assignment import get_telecalling_config, save_telecalling_config
from app.services.call_teams import assert_caller_in_scope, attach_team, caller_scope, team_by_caller
from app.services.attendance import build_attendance_map, compute_team_summary, date_range
from app.services.rbac import ensure_default_roles

logger = logging.getLogger(__name__)
router = APIRouter()
require_team_view = require_permission("team.view")
require_team_manage = require_permission("team.manage")


class AttendancePayload(BaseModel):
    date: str
    status: str


class MarkHolidayPayload(BaseModel):
    date: str


class ShiftConfigPayload(BaseModel):
    shift_mode: str
    shift_start_hour: int
    shift_end_hour: int


class CallerShiftPayload(BaseModel):
    shift_start_hour: int
    shift_end_hour: int


def _active_team_callers(db, tenant_id: str) -> list[dict]:
    """Active, non-owner callers for a tenant (mirrors list_callers filtering)."""
    owner = (
        db.table("tenant_users")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("role", "owner")
        .maybe_single()
        .execute()
    )
    owner_user_id = (owner.data or {}).get("user_id")

    query = (
        db.table("callers")
        .select("id, name")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
    )
    if owner_user_id:
        query = query.neq("user_id", owner_user_id)
    return query.execute().data or []


@router.get("/me")
def get_me(ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()

    # Enabled features for this tenant
    tenant = (
        db.table("tenants")
        .select("name, enabled_features")
        .eq("id", ctx["tenant_id"])
        .limit(1)
        .execute()
    )
    tenant_row = tenant.data[0] if tenant and tenant.data else {}
    enabled_features: list[str] = (
        tenant_row.get("enabled_features") or ["whatsapp", "telecalling"]
    )

    # Check system admin — use limit(1) instead of maybe_single() to avoid
    # PostgREST 406 on zero rows, which causes the client to return None and
    # crash the `.data` access (was the cause of /api/v1/team/me 500s for
    # non-admin users like callers).
    admin = (
        db.table("system_admins")
        .select("user_id")
        .eq("user_id", ctx["user_id"])
        .limit(1)
        .execute()
    )
    is_system_admin = bool(admin and admin.data)

    caller = (
        db.table("callers")
        .select("id, name, phone")
        .eq("user_id", ctx["user_id"])
        .eq("tenant_id", ctx["tenant_id"])
        .limit(1)
        .execute()
    )
    profile = caller.data[0] if caller and caller.data else None

    return {
        "tenant_id": ctx["tenant_id"],
        "role": ctx["role"],
        "role_id": ctx.get("role_id"),
        "role_name": ctx.get("role_name"),
        "role_slug": ctx.get("role_slug"),
        "permissions": ctx.get("permissions") or [],
        "force_password_reset": ctx.get("force_password_reset", False),
        "caller_id": ctx.get("caller_id"),
        "caller_profile": profile,
        "enabled_features": enabled_features,
        "is_system_admin": is_system_admin,
        "tenant_name": tenant_row.get("name"),
    }


@router.get("/")
def list_team(ctx: dict = Depends(require_team_view)):
    db = get_supabase()
    ensure_default_roles(db, ctx["tenant_id"])
    calling_provider = get_telecalling_config(ctx["tenant_id"]).get("calling_provider", "telecmi")
    members = (
        db.table("tenant_users")
        .select("user_id, role, role_id, full_name, force_password_reset, created_at")
        .eq("tenant_id", ctx["tenant_id"])
        .execute()
    )
    user_ids = [m["user_id"] for m in (members.data or [])]
    callers = {}
    if user_ids:
        caller_rows = (
            db.table("callers")
            .select("user_id, id, name, phone, active, telecmi_agent_id")
            .in_("user_id", user_ids)
            .eq("tenant_id", ctx["tenant_id"])
            .execute()
        )
        callers = {r["user_id"]: r for r in (caller_rows.data or [])}
    result = []
    roles = {}
    role_ids = [m.get("role_id") for m in (members.data or []) if m.get("role_id")]
    if role_ids:
        role_rows = (
            db.table("tenant_roles")
            .select("id,name,slug,permissions")
            .eq("tenant_id", ctx["tenant_id"])
            .in_("id", role_ids)
            .execute()
        )
        roles = {r["id"]: r for r in (role_rows.data or [])}
    scope = caller_scope(db, ctx)
    teams = team_by_caller(db, ctx["tenant_id"])
    for m in (members.data or []):
        if scope is not None and str((callers.get(m["user_id"]) or {}).get("id")) not in scope:
            # A Team leader sees only their own team: no owner, admins or other teams' people.
            continue
        profile = callers.get(m["user_id"])
        if profile:
            attach_team([profile], teams)
        result.append({
            **m,
            "role_name": (roles.get(m.get("role_id")) or {}).get("name") or ("Owner" if m.get("role") == "owner" else "Telecaller"),
            "permissions": (roles.get(m.get("role_id")) or {}).get("permissions") or [],
            "caller_profile": profile,
        })
    return {"data": result, "calling_provider": calling_provider}


@router.patch("/shift-config")
def update_shift_config(payload: ShiftConfigPayload, ctx: dict = Depends(require_team_manage)):
    if caller_scope(get_supabase(), ctx) is not None:
        # The common shift hours are the whole client's setting, not one team's.
        raise HTTPException(status_code=403, detail="Only the owner or an admin can change the shift hours for everyone.")
    if payload.shift_mode not in ("common", "individual"):
        raise HTTPException(status_code=400, detail="shift_mode must be 'common' or 'individual'")
    if not (0 <= payload.shift_start_hour <= 23 and 0 <= payload.shift_end_hour <= 23):
        raise HTTPException(status_code=400, detail="Shift hours must be between 0 and 23")

    current = get_telecalling_config(ctx["tenant_id"])
    updated = {
        **current,
        "shift_mode": payload.shift_mode,
        "shift_start_hour": payload.shift_start_hour,
        "shift_end_hour": payload.shift_end_hour,
    }
    save_telecalling_config(ctx["tenant_id"], updated)
    return updated


@router.patch("/{caller_id}/shift")
def update_caller_shift(
    caller_id: str,
    payload: CallerShiftPayload,
    ctx: dict = Depends(require_team_manage),
):
    if not (0 <= payload.shift_start_hour <= 23 and 0 <= payload.shift_end_hour <= 23):
        raise HTTPException(status_code=400, detail="Shift hours must be between 0 and 23")

    db = get_supabase()
    assert_caller_in_scope(db, ctx, caller_id)
    result = (
        db.table("callers")
        .update({
            "shift_start_hour": payload.shift_start_hour,
            "shift_end_hour": payload.shift_end_hour,
        })
        .eq("id", caller_id)
        .eq("tenant_id", ctx["tenant_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Caller not found")
    return {"data": result.data[0]}


@router.delete("/{user_id}")
def remove_member(user_id: str, ctx: dict = Depends(get_tenant_and_role)):
    if ctx["role"] != "owner" and "team.manage" not in (ctx.get("permissions") or []):
        raise HTTPException(status_code=403, detail="Permission required: team.manage")
    db = get_supabase()
    if caller_scope(db, ctx) is not None:
        raise HTTPException(status_code=403, detail="Only the owner or an admin can remove people.")
    db.table("tenant_users").delete().eq("user_id", user_id).eq("tenant_id", ctx["tenant_id"]).execute()
    db.table("callers").delete().eq("user_id", user_id).eq("tenant_id", ctx["tenant_id"]).execute()
    invalidate_tenant_cache(user_id)
    return {"removed": True}


@router.get("/attendance")
def get_team_attendance(
    month: str | None = None,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    ctx: dict = Depends(require_team_view),
):
    db = get_supabase()
    today = datetime.utcnow().date()

    if from_date and to_date:
        try:
            range_start = date.fromisoformat(from_date)
            range_end = date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="from/to must be in YYYY-MM-DD format")
        if range_end < range_start:
            range_start, range_end = range_end, range_start
        month_start, month_end = range_start, range_end
    else:
        if month:
            try:
                year_str, mon_str = month.split("-")
                month_start = date(int(year_str), int(mon_str), 1)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="month must be in YYYY-MM format")
        else:
            month_start = today.replace(day=1)

        if month_start.month == 12:
            next_month = date(month_start.year + 1, 1, 1)
        else:
            next_month = date(month_start.year, month_start.month + 1, 1)
        month_end = next_month - timedelta(days=1)

    callers = _active_team_callers(db, ctx["tenant_id"])
    scope = caller_scope(db, ctx)
    if scope is not None:
        callers = [c for c in callers if str(c["id"]) in scope]
    caller_ids = [c["id"] for c in callers]

    days = date_range(month_start, month_end)
    overrides_by_caller: dict[str, dict[str, str]] = {cid: {} for cid in caller_ids}
    active_by_caller: dict[str, set[str]] = {cid: set() for cid in caller_ids}

    if caller_ids:
        override_rows = (
            db.table("caller_attendance_overrides")
            .select("caller_id, date, status")
            .in_("caller_id", caller_ids)
            .gte("date", month_start.isoformat())
            .lte("date", month_end.isoformat())
            .execute()
        )
        for r in (override_rows.data or []):
            overrides_by_caller.setdefault(r["caller_id"], {})[r["date"]] = r["status"]

        log_rows = (
            db.table("caller_status_logs")
            .select("caller_id, started_at")
            .in_("caller_id", caller_ids)
            .gte("started_at", f"{month_start.isoformat()}T00:00:00")
            .lt("started_at", f"{(month_end + timedelta(days=1)).isoformat()}T00:00:00")
            .execute()
        )
        for r in (log_rows.data or []):
            active_by_caller.setdefault(r["caller_id"], set()).add(r["started_at"][:10])

    grid = {
        cid: build_attendance_map(days, today, overrides_by_caller.get(cid, {}), active_by_caller.get(cid, set()))
        for cid in caller_ids
    }
    summary = compute_team_summary(grid, today.isoformat())

    return {
        "data": {
            "callers": [{"caller_id": c["id"], "name": c["name"]} for c in callers],
            "days": [d.isoformat() for d in days],
            "grid": grid,
            "summary": summary,
        }
    }


@router.get("/attendance/{caller_id}")
def get_caller_attendance(caller_id: str, months: int = 4, ctx: dict = Depends(get_tenant_and_role)):
    if (
        ctx["role"] != "owner"
        and ctx.get("caller_id") != caller_id
        and "team.view" not in (ctx.get("permissions") or [])
    ):
        raise HTTPException(status_code=403, detail="Permission required: team.view")
    db = get_supabase()
    assert_caller_in_scope(db, ctx, caller_id)

    caller = (
        db.table("callers")
        .select("id")
        .eq("id", caller_id)
        .eq("tenant_id", ctx["tenant_id"])
        .limit(1)
        .execute()
    )
    if not caller.data:
        raise HTTPException(status_code=404, detail="Caller not found")

    today = datetime.utcnow().date()
    start = today - timedelta(days=30 * months)
    end = today + timedelta(days=14)
    days = date_range(start, end)

    override_rows = (
        db.table("caller_attendance_overrides")
        .select("date, status")
        .eq("caller_id", caller_id)
        .gte("date", start.isoformat())
        .lte("date", end.isoformat())
        .execute()
    )
    overrides = {r["date"]: r["status"] for r in (override_rows.data or [])}

    log_rows = (
        db.table("caller_status_logs")
        .select("started_at")
        .eq("caller_id", caller_id)
        .gte("started_at", f"{start.isoformat()}T00:00:00")
        .lt("started_at", f"{(today + timedelta(days=1)).isoformat()}T00:00:00")
        .execute()
    )
    active_dates = {r["started_at"][:10] for r in (log_rows.data or [])}

    day_map = build_attendance_map(days, today, overrides, active_dates)

    return {
        "data": {
            "caller_id": caller_id,
            "days": [{"date": d, "status": s} for d, s in day_map.items()],
            "today_status": day_map.get(today.isoformat(), "absent"),
        }
    }


@router.post("/attendance/holiday")
def mark_holiday(payload: MarkHolidayPayload, ctx: dict = Depends(get_tenant_and_role)):
    if ctx["role"] != "owner" and "team.manage" not in (ctx.get("permissions") or []):
        raise HTTPException(status_code=403, detail="Permission required: team.manage")
    try:
        holiday_date = date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")
    if holiday_date > datetime.utcnow().date() + timedelta(days=14):
        raise HTTPException(status_code=400, detail="Holidays can only be marked up to 14 days in advance")

    db = get_supabase()

    scope = caller_scope(db, ctx)
    caller_ids = [c["id"] for c in _active_team_callers(db, ctx["tenant_id"]) if scope is None or str(c["id"]) in scope]

    if not caller_ids:
        return {"data": {"date": payload.date, "status": "holiday", "caller_count": 0}}

    existing = (
        db.table("caller_attendance_overrides")
        .select("id, caller_id")
        .in_("caller_id", caller_ids)
        .eq("date", payload.date)
        .execute()
    )
    existing_by_caller = {r["caller_id"]: r["id"] for r in (existing.data or [])}

    for cid in caller_ids:
        row = {
            "tenant_id": ctx["tenant_id"],
            "caller_id": cid,
            "date": payload.date,
            "status": "holiday",
            "marked_by": ctx["user_id"],
            "updated_at": datetime.utcnow().isoformat(),
        }
        existing_id = existing_by_caller.get(cid)
        if existing_id:
            db.table("caller_attendance_overrides").update(row).eq("id", existing_id).execute()
        else:
            db.table("caller_attendance_overrides").insert(row).execute()

    logger.info(f"Marked holiday {payload.date} for {len(caller_ids)} callers in tenant {ctx['tenant_id']}")
    return {"data": {"date": payload.date, "status": "holiday", "caller_count": len(caller_ids)}}


@router.post("/attendance/{caller_id}")
def mark_attendance(caller_id: str, payload: AttendancePayload, ctx: dict = Depends(get_tenant_and_role)):
    if ctx["role"] != "owner" and "team.manage" not in (ctx.get("permissions") or []):
        raise HTTPException(status_code=403, detail="Permission required: team.manage")
    if payload.status not in ("present", "absent"):
        raise HTTPException(status_code=400, detail="status must be 'present' or 'absent'")
    try:
        date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")

    db = get_supabase()
    assert_caller_in_scope(db, ctx, caller_id)
    caller = (
        db.table("callers")
        .select("id")
        .eq("id", caller_id)
        .eq("tenant_id", ctx["tenant_id"])
        .limit(1)
        .execute()
    )
    if not caller.data:
        raise HTTPException(status_code=404, detail="Caller not found")

    existing = (
        db.table("caller_attendance_overrides")
        .select("id")
        .eq("caller_id", caller_id)
        .eq("date", payload.date)
        .limit(1)
        .execute()
    )
    row = {
        "tenant_id": ctx["tenant_id"],
        "caller_id": caller_id,
        "date": payload.date,
        "status": payload.status,
        "marked_by": ctx["user_id"],
        "updated_at": datetime.utcnow().isoformat(),
    }
    if existing.data:
        db.table("caller_attendance_overrides").update(row).eq("id", existing.data[0]["id"]).execute()
    else:
        db.table("caller_attendance_overrides").insert(row).execute()

    return {"data": {"date": payload.date, "status": payload.status}}
