import logging
import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.db.supabase import get_supabase
from app.dependencies.tenant import get_tenant_and_role, require_permission, invalidate_tenant_cache
from app.services.assignment import get_telecalling_config
from app.services.audit_log import record_audit_event
from app.services.entitlements import get_purchased_quantity, resolve_entitlements
from app.services.rbac import (
    DEFAULT_TELECALLER_PERMISSIONS,
    PERMISSION_CATALOG,
    ensure_default_roles,
    get_user_role,
    is_rbac_schema_unavailable,
    is_telecaller_role,
    normalize_permissions,
    touch_updated_at,
)

logger = logging.getLogger(__name__)
router = APIRouter()
require_roles_manage = require_permission("roles.manage")


def require_roles_read(ctx: dict = Depends(get_tenant_and_role)) -> dict:
    permissions = ctx.get("permissions") or []
    if ctx.get("role") == "owner" or "roles.view" in permissions or "roles.manage" in permissions:
        return ctx
    raise HTTPException(status_code=403, detail="Permission required: roles.view")


class RolePayload(BaseModel):
    name: str
    permissions: list[str]


class UserPayload(BaseModel):
    full_name: str
    email: EmailStr
    role_id: str
    temporary_password: str
    phone: str | None = None
    telecmi_agent_id: str | None = None
    telecmi_agent_password: str | None = None


class UserUpdatePayload(BaseModel):
    full_name: str | None = None
    role_id: str | None = None
    phone: str | None = None
    telecmi_agent_id: str | None = None
    telecmi_agent_password: str | None = None


def _temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value):
            return value + "!"


def _auth_user(db, user_id: str) -> dict:
    try:
        result = db.auth.admin.get_user_by_id(user_id)
        user = result.user
        return {
            "email": getattr(user, "email", None) or "",
            "full_name": (getattr(user, "user_metadata", None) or {}).get("full_name"),
        }
    except Exception:
        return {"email": "", "full_name": None}


def _update_auth_metadata(db, user_id: str, updates: dict) -> None:
    current = _auth_user(db, user_id)
    metadata = {}
    try:
        result = db.auth.admin.get_user_by_id(user_id)
        user = result.user
        metadata = dict(getattr(user, "user_metadata", None) or {})
    except Exception:
        pass
    if current.get("full_name") and "full_name" not in metadata:
        metadata["full_name"] = current["full_name"]
    metadata.update(updates)
    db.auth.admin.update_user_by_id(user_id, {"user_metadata": metadata})


def _role_map(db, tenant_id: str) -> dict[str, dict]:
    rows = db.table("tenant_roles").select("*").eq("tenant_id", tenant_id).order("name").execute()
    return {r["id"]: _serialize_role(r) for r in (rows.data or [])}


def _serialize_role(role: dict) -> dict:
    serialized = {**role, "permissions": normalize_permissions(role.get("permissions"))}
    serialized["is_telecaller"] = is_telecaller_role(serialized)
    return serialized


def _active_telecaller_count(db, tenant_id: str) -> int:
    # `create_client` seeds a free `callers` row for the tenant OWNER (so
    # owners can also take calls) -- that row is not a purchased telecaller
    # seat and must not count against the quota, or the owner's own free
    # profile silently eats one slot that should belong to a real telecaller.
    owner_row = (
        db.table("tenant_users")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("role", "owner")
        .limit(1)
        .execute()
    )
    owner_user_id = owner_row.data[0]["user_id"] if owner_row.data else None

    query = (
        db.table("callers")
        .select("id", count="exact")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
    )
    if owner_user_id:
        query = query.neq("user_id", owner_user_id)
    result = query.execute()
    return result.count or 0


def _telecaller_seat_limit(db, tenant_id: str) -> int:
    """
    Purchasing SIM Basic or TeleCMI calling includes 1 free telecaller seat
    -- that's the calling module's whole point, not an add-on. A tenant
    with no calling module purchased at all gets 0, matching the
    pre-purchase "nothing works yet" gate.

    The `telecaller_seats` quantity in `tenant_subscription_items` is the
    tenant's TOTAL desired seat count, not a top-up on top of the free
    seat -- the cart's stepper starts at 1 (the free seat) and billing
    (`_monthly_price_for_item`, via `included_qty=1` on the catalog row)
    already nets the first unit out as free. So the limit is whichever is
    larger: the free baseline, or the purchased total (it must never be
    summed with the baseline, that double-counts the included free seat).
    """
    ent = resolve_entitlements(db, tenant_id)
    features = set(ent.get("features") or [])
    baseline = 1 if ("telecalling_sim" in features or "telecalling_telecmi" in features) else 0
    return max(baseline, get_purchased_quantity(db, tenant_id, "telecaller_seats"))


def _check_telecaller_seat_available(db, tenant_id: str) -> None:
    seat_limit = _telecaller_seat_limit(db, tenant_id)
    current = _active_telecaller_count(db, tenant_id)
    if current >= seat_limit:
        raise HTTPException(
            status_code=400,
            detail=f"Telecaller seat limit reached ({current}/{seat_limit}). Request more seats from Subscriptions.",
        )


def _caller_for_user(db, tenant_id: str, user_id: str) -> dict | None:
    result = (
        db.table("callers")
        .select("id,name,phone,active,telecmi_agent_id,telecmi_agent_password")
        .eq("tenant_id", tenant_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _ensure_caller_profile(db, tenant_id: str, user_id: str, payload: UserPayload | UserUpdatePayload, role: dict) -> None:
    existing = _caller_for_user(db, tenant_id, user_id)
    should_be_caller = is_telecaller_role(role)
    now = datetime.now(timezone.utc).isoformat()
    name = (payload.full_name or "").strip() if payload.full_name is not None else None
    phone = (payload.phone or "").strip() if payload.phone is not None else None
    telecmi_agent_id = (payload.telecmi_agent_id or "").strip() if payload.telecmi_agent_id is not None else None
    telecmi_agent_password = (payload.telecmi_agent_password or "").strip() if payload.telecmi_agent_password is not None else None

    if should_be_caller:
        updates = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "active": True,
            "status": "active",
        }
        if name:
            updates["name"] = name
        if phone is not None:
            updates["phone"] = phone or None
        if telecmi_agent_id is not None:
            updates["telecmi_agent_id"] = telecmi_agent_id or None
        if telecmi_agent_password is not None:
            updates["telecmi_agent_password"] = telecmi_agent_password or None
        if existing:
            db.table("callers").update(updates).eq("id", existing["id"]).eq("tenant_id", tenant_id).execute()
        else:
            db.table("callers").insert({
                **updates,
                "name": name or "Telecaller",
                "status_changed_at": now,
            }).execute()
        return

    if existing:
        db.table("callers").update({"active": False}).eq("id", existing["id"]).eq("tenant_id", tenant_id).execute()


def _serialize_user(db, tenant_id: str, member: dict, roles: dict[str, dict]) -> dict:
    auth = _auth_user(db, member["user_id"])
    role = roles.get(member.get("role_id") or "")
    caller = _caller_for_user(db, tenant_id, member["user_id"])
    if caller and caller.get("telecmi_agent_password"):
        caller["has_telecmi_agent_password"] = True
        caller.pop("telecmi_agent_password", None)
    return {
        "user_id": member["user_id"],
        "full_name": member.get("full_name") or auth.get("full_name") or (caller or {}).get("name") or "",
        "email": auth.get("email") or "",
        "role": member.get("role"),
        "role_id": member.get("role_id"),
        "role_name": (role or {}).get("name") or ("Owner" if member.get("role") == "owner" else "Telecaller"),
        "force_password_reset": bool(member.get("force_password_reset")),
        "created_at": member.get("created_at"),
        "caller_profile": caller,
    }


@router.get("/permissions")
def list_permissions(_ctx: dict = Depends(require_roles_read)):
    return {"data": PERMISSION_CATALOG}


@router.get("/roles")
def list_roles(ctx: dict = Depends(require_roles_read)):
    db = get_supabase()
    try:
        ensure_default_roles(db, ctx["tenant_id"])
        roles = db.table("tenant_roles").select("*").eq("tenant_id", ctx["tenant_id"]).order("name").execute()
    except Exception as exc:
        if is_rbac_schema_unavailable(exc):
            logger.error("RBAC roles schema unavailable for tenant %s: %s", ctx["tenant_id"], exc)
            return {
                "data": [],
                "permissions": PERMISSION_CATALOG,
                "setup_required": True,
                "detail": "RBAC schema is not available yet. Apply the tenant RBAC repair migration.",
            }
        raise
    return {"data": [_serialize_role(role) for role in (roles.data or [])], "permissions": PERMISSION_CATALOG}


@router.post("/roles")
def create_role(payload: RolePayload, ctx: dict = Depends(require_roles_manage)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Role name is required")
    db = get_supabase()
    row = {
        "tenant_id": ctx["tenant_id"],
        "name": name,
        "description": None,
        "permissions": normalize_permissions(payload.permissions),
        "is_system_template": False,
    }
    try:
        created = db.table("tenant_roles").insert(row).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create role: {e}")
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx["user_id"], actor_role=ctx.get("role"),
        action="role.created", target_type="tenant_role", target_id=created.data[0]["id"],
        metadata={"name": name, "permissions": row["permissions"]},
    )
    return _serialize_role(created.data[0])


@router.patch("/roles/{role_id}")
def update_role(role_id: str, payload: RolePayload, ctx: dict = Depends(require_roles_manage)):
    db = get_supabase()
    role = get_user_role(db, ctx["tenant_id"], role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    updates = touch_updated_at({
        "name": payload.name.strip() or role["name"],
        "description": role.get("description"),
        "permissions": normalize_permissions(payload.permissions),
    })
    updated = db.table("tenant_roles").update(updates).eq("id", role_id).eq("tenant_id", ctx["tenant_id"]).execute()
    invalidate_tenant_cache()
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx["user_id"], actor_role=ctx.get("role"),
        action="role.updated", target_type="tenant_role", target_id=role_id,
        metadata={"name": updates["name"], "permissions": updates["permissions"]},
    )
    return _serialize_role(updated.data[0])


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, ctx: dict = Depends(require_roles_manage)):
    db = get_supabase()
    role = get_user_role(db, ctx["tenant_id"], role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.get("slug") == "telecaller":
        raise HTTPException(status_code=400, detail="The default Telecaller role can be edited but not deleted")
    assigned = db.table("tenant_users").select("id").eq("tenant_id", ctx["tenant_id"]).eq("role_id", role_id).limit(1).execute()
    if assigned.data:
        raise HTTPException(status_code=400, detail="Role is assigned to users")
    db.table("tenant_roles").delete().eq("id", role_id).eq("tenant_id", ctx["tenant_id"]).execute()
    invalidate_tenant_cache()
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx["user_id"], actor_role=ctx.get("role"),
        action="role.deleted", target_type="tenant_role", target_id=role_id,
        metadata={"name": role.get("name")},
    )
    return {"deleted": True}


@router.get("/audit-log")
def list_audit_log(
    page: int = 1,
    limit: int = 50,
    date_from: str | None = None,
    date_to: str | None = None,
    ctx: dict = Depends(require_roles_read),
):
    db = get_supabase()
    # Tenant-facing scope is deliberately narrower than the operator console's
    # view of this same table: team membership and role/permission changes,
    # not every settings/broadcast/operator action ever logged for this tenant.
    # The owner also sees what was done through the Anril AI connector
    # (claude.*): those rows can hold the text of a message sent to a customer,
    # so staff who can only view roles do not get them.
    scope = "action.like.team.%,action.like.role.%"
    if ctx.get("role") == "owner":
        scope += ",action.like.claude.%"
    q = db.table("app_audit_logs").select(
        "id, actor_user_id, actor_role, action, target_type, target_id, metadata, created_at",
        count="exact",
    ).eq("tenant_id", ctx["tenant_id"]).or_(scope)

    if date_from:
        q = q.gte("created_at", date_from)
    if date_to:
        q = q.lte("created_at", date_to + "T23:59:59.999Z")

    offset = (page - 1) * limit
    result = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    return {"data": result.data or [], "total": result.count or 0, "page": page, "limit": limit}


@router.get("/users")
def list_users(ctx: dict = Depends(require_roles_read)):
    db = get_supabase()
    try:
        ensure_default_roles(db, ctx["tenant_id"])
        roles = _role_map(db, ctx["tenant_id"])
        members = (
            db.table("tenant_users")
            .select("user_id, role, role_id, full_name, force_password_reset, created_at")
            .eq("tenant_id", ctx["tenant_id"])
            .order("created_at")
            .execute()
        )
    except Exception as exc:
        if not is_rbac_schema_unavailable(exc):
            raise
        logger.error("RBAC users schema unavailable for tenant %s: %s", ctx["tenant_id"], exc)
        roles = {}
        members = (
            db.table("tenant_users")
            .select("user_id, role, created_at")
            .eq("tenant_id", ctx["tenant_id"])
            .order("created_at")
            .execute()
        )
    seat_limit = _telecaller_seat_limit(db, ctx["tenant_id"])
    seat_used = _active_telecaller_count(db, ctx["tenant_id"])
    return {
        "data": [_serialize_user(db, ctx["tenant_id"], m, roles) for m in (members.data or [])],
        "telecaller_seats": {"limit": seat_limit, "used": seat_used},
    }


@router.post("/users")
def create_user(payload: UserPayload, ctx: dict = Depends(require_roles_manage)):
    db = get_supabase()
    role = get_user_role(db, ctx["tenant_id"], payload.role_id)
    if not role:
        raise HTTPException(status_code=400, detail="Choose a valid role")
    if len(payload.temporary_password) < 8:
        raise HTTPException(status_code=400, detail="Temporary password must be at least 8 characters")

    calling_provider = get_telecalling_config(ctx["tenant_id"]).get("calling_provider", "telecmi")
    if is_telecaller_role(role) and calling_provider == "sim_basic" and not (payload.phone or "").strip():
        raise HTTPException(status_code=400, detail="Phone number is required for SIM Basic telecallers")
    if is_telecaller_role(role):
        _check_telecaller_seat_available(db, ctx["tenant_id"])

    try:
        result = db.auth.admin.create_user({
            "email": str(payload.email),
            "password": payload.temporary_password,
            "email_confirm": True,
            "user_metadata": {"full_name": payload.full_name.strip(), "force_password_reset": True},
        })
        user = result.user
        user_id = user.id if hasattr(user, "id") else user["id"]
    except Exception as e:
        msg = str(e)
        if any(s in msg.lower() for s in ("already", "duplicate", "registered")):
            raise HTTPException(status_code=400, detail="A user with this email already exists")
        raise HTTPException(status_code=400, detail=f"Failed to create user: {msg}")

    db.table("tenant_users").insert({
        "tenant_id": ctx["tenant_id"],
        "user_id": user_id,
        "role": "caller",
        "role_id": payload.role_id,
        "full_name": payload.full_name.strip(),
        "force_password_reset": True,
        "temporary_password_issued_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    invalidate_tenant_cache(user_id)
    _ensure_caller_profile(db, ctx["tenant_id"], user_id, payload, role)
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx["user_id"], actor_role=ctx.get("role"),
        action="team.member_created", target_type="tenant_user", target_id=user_id,
        metadata={"full_name": payload.full_name.strip(), "email": str(payload.email), "role_name": role.get("name")},
    )
    return {"created": True, "user_id": user_id, "temporary_password": payload.temporary_password}


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: UserUpdatePayload, ctx: dict = Depends(require_roles_manage)):
    db = get_supabase()
    member = (
        db.table("tenant_users")
        .select("user_id, role, role_id")
        .eq("tenant_id", ctx["tenant_id"])
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not member.data:
        raise HTTPException(status_code=404, detail="User not found")
    if member.data[0].get("role") == "owner":
        raise HTTPException(status_code=400, detail="Owner role cannot be edited here")

    role_id = payload.role_id or member.data[0].get("role_id")
    role = get_user_role(db, ctx["tenant_id"], role_id)
    if not role:
        raise HTTPException(status_code=400, detail="Choose a valid role")

    existing_caller = _caller_for_user(db, ctx["tenant_id"], user_id)
    becoming_telecaller = is_telecaller_role(role) and not (existing_caller and existing_caller.get("active"))
    if becoming_telecaller:
        _check_telecaller_seat_available(db, ctx["tenant_id"])

    updates = {}
    if payload.full_name is not None:
        updates["full_name"] = payload.full_name.strip()
        try:
            _update_auth_metadata(db, user_id, {"full_name": payload.full_name.strip()})
        except Exception:
            logger.warning("Failed to update auth metadata for user %s", user_id)
    if payload.role_id is not None:
        updates["role_id"] = payload.role_id
    if updates:
        db.table("tenant_users").update(updates).eq("tenant_id", ctx["tenant_id"]).eq("user_id", user_id).execute()
        invalidate_tenant_cache(user_id)
    _ensure_caller_profile(db, ctx["tenant_id"], user_id, payload, role)
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx["user_id"], actor_role=ctx.get("role"),
        action="team.member_updated", target_type="tenant_user", target_id=user_id,
        metadata={"full_name": payload.full_name, "role_name": role.get("name")},
    )
    return {"updated": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, ctx: dict = Depends(require_roles_manage)):
    if user_id == ctx["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    db = get_supabase()
    member = db.table("tenant_users").select("role").eq("tenant_id", ctx["tenant_id"]).eq("user_id", user_id).limit(1).execute()
    if not member.data:
        raise HTTPException(status_code=404, detail="User not found")
    if member.data[0].get("role") == "owner":
        raise HTTPException(status_code=400, detail="Owner cannot be deleted here")

    caller = _caller_for_user(db, ctx["tenant_id"], user_id)
    if caller:
        # chat_handovers.assigned_to has no delete cascade (ON DELETE NO ACTION) --
        # null it first or the callers delete below fails.
        db.table("chat_handovers").update({"assigned_to": None}).eq("assigned_to", caller["id"]).execute()
        db.table("callers").delete().eq("id", caller["id"]).eq("tenant_id", ctx["tenant_id"]).execute()

    db.table("tenant_users").delete().eq("tenant_id", ctx["tenant_id"]).eq("user_id", user_id).execute()
    invalidate_tenant_cache(user_id)
    try:
        db.auth.admin.delete_user(user_id)
    except Exception:
        logger.warning("Deleted tenant membership but auth user delete failed for %s", user_id)

    record_audit_event(
        db,
        tenant_id=ctx["tenant_id"],
        actor_user_id=ctx["user_id"],
        actor_role=ctx.get("role"),
        action="team.member_deleted",
        target_type="tenant_user",
        target_id=user_id,
        metadata={"caller_name": caller.get("name") if caller else None},
    )
    return {"deleted": True}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: str, ctx: dict = Depends(require_roles_manage)):
    db = get_supabase()
    member = db.table("tenant_users").select("role").eq("tenant_id", ctx["tenant_id"]).eq("user_id", user_id).limit(1).execute()
    if not member.data:
        raise HTTPException(status_code=404, detail="User not found")
    password = _temp_password()
    _update_auth_metadata(db, user_id, {"force_password_reset": True})
    db.auth.admin.update_user_by_id(user_id, {"password": password})
    db.table("tenant_users").update({
        "force_password_reset": True,
        "temporary_password_issued_at": datetime.now(timezone.utc).isoformat(),
    }).eq("tenant_id", ctx["tenant_id"]).eq("user_id", user_id).execute()
    invalidate_tenant_cache(user_id)
    record_audit_event(
        db, tenant_id=ctx["tenant_id"], actor_user_id=ctx["user_id"], actor_role=ctx.get("role"),
        action="team.password_reset", target_type="tenant_user", target_id=user_id, metadata={},
    )
    return {"temporary_password": password}


@router.post("/password-reset-complete")
def password_reset_complete(ctx: dict = Depends(get_tenant_and_role)):
    db = get_supabase()
    db.table("tenant_users").update({"force_password_reset": False}).eq("tenant_id", ctx["tenant_id"]).eq("user_id", ctx["user_id"]).execute()
    invalidate_tenant_cache(ctx["user_id"])
    try:
        _update_auth_metadata(db, ctx["user_id"], {"force_password_reset": False})
    except Exception:
        logger.warning("Failed to clear auth force reset metadata for user %s", ctx["user_id"])
    return {"updated": True}
