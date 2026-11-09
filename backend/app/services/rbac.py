from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PERMISSION_CATALOG: list[dict] = [
    {"key": "dashboard.view", "label": "Dashboard", "group": "Overview"},
    {"key": "conversations.view", "label": "View conversations", "group": "Messaging"},
    {"key": "conversations.reply", "label": "Reply to conversations", "group": "Messaging"},
    {"key": "leads.view", "label": "View segments", "group": "Leads"},
    {"key": "leads.manage", "label": "Manage leads", "group": "Leads"},
    {"key": "inbound_leads.view", "label": "View inbound leads", "group": "Leads"},
    {"key": "inbound_leads.manage", "label": "Manage inbound leads", "group": "Leads"},
    {"key": "deals.view", "label": "View deals", "group": "Leads"},
    {"key": "deals.manage", "label": "Manage deals", "group": "Leads"},
    {"key": "meta_ads.view", "label": "View Meta ads", "group": "Leads"},
    {"key": "meta_ads.manage", "label": "Manage Meta ads", "group": "Leads"},
    {"key": "outbound_leads.view", "label": "View outbound leads", "group": "Messaging"},
    {"key": "outbound_leads.manage", "label": "Manage outbound leads", "group": "Messaging"},
    {"key": "templates.view", "label": "View templates", "group": "Messaging"},
    {"key": "templates.manage", "label": "Manage templates", "group": "Messaging"},
    {"key": "numbers.view", "label": "View numbers pool", "group": "Messaging"},
    {"key": "numbers.manage", "label": "Manage numbers pool", "group": "Messaging"},
    {"key": "auto_messages.view", "label": "View auto-messages", "group": "Messaging"},
    {"key": "auto_messages.manage", "label": "Manage auto-messages", "group": "Messaging"},
    {"key": "brain.view", "label": "View Anril Brain", "group": "AI"},
    {"key": "knowledge.view", "label": "View knowledge base", "group": "AI"},
    {"key": "knowledge.manage", "label": "Manage knowledge base", "group": "AI"},
    {"key": "catalog.view", "label": "View catalog", "group": "AI"},
    {"key": "catalog.manage", "label": "Manage catalog", "group": "AI"},
    {"key": "services.view", "label": "View services", "group": "AI"},
    {"key": "services.manage", "label": "Manage services", "group": "AI"},
    {"key": "analytics.view", "label": "View analytics", "group": "Reports"},
    {"key": "subscription.view", "label": "View subscription", "group": "Admin"},
    {"key": "subscription.manage", "label": "Manage subscription", "group": "Admin"},
    {"key": "team.view", "label": "View team performance", "group": "Team"},
    {"key": "team.manage", "label": "Manage team performance", "group": "Team"},
    {"key": "roles.view", "label": "View users and roles", "group": "Admin"},
    {"key": "roles.manage", "label": "Manage users and roles", "group": "Admin"},
    {"key": "settings.view", "label": "View settings", "group": "Admin"},
    {"key": "settings.manage", "label": "Manage settings", "group": "Admin"},
    {"key": "companions.manage", "label": "Manage Anril Agents (characters, keys, memories)", "group": "AI"},
    {"key": "telecalling.dialer.view", "label": "View dialer", "group": "Telecalling"},
    {"key": "telecalling.dialer", "label": "Use dialer", "group": "Telecalling"},
    {"key": "telecalling.upload.view", "label": "View call list uploads", "group": "Telecalling"},
    {"key": "telecalling.upload", "label": "Upload call lists", "group": "Telecalling"},
    {"key": "telecalling.scheduled.view", "label": "View scheduled calls", "group": "Telecalling"},
    {"key": "telecalling.scheduled", "label": "Scheduled calls", "group": "Telecalling"},
    {"key": "telecalling.notes.view", "label": "View call notes", "group": "Telecalling"},
    {"key": "telecalling.notes", "label": "Call notes", "group": "Telecalling"},
    {"key": "sms.view", "label": "View SMS campaigns and reports", "group": "SMS"},
    {"key": "sms.manage", "label": "Send SMS and manage SMS templates", "group": "SMS"},
]

ALL_PERMISSION_KEYS = [p["key"] for p in PERMISSION_CATALOG]

DEFAULT_TELECALLER_PERMISSIONS = [
    "dashboard.view",
    "conversations.view",
    "leads.view",
    "deals.view",
    "telecalling.dialer",
    "telecalling.scheduled",
    "telecalling.notes",
]

RBAC_SCHEMA_ERROR_MARKERS = (
    "tenant_roles",
    "role_id",
    "force_password_reset",
    "temporary_password_issued_at",
)


def is_rbac_schema_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    schema_cache_error = "pgrst205" in msg or "schema cache" in msg or "could not find" in msg
    return schema_cache_error and any(marker in msg for marker in RBAC_SCHEMA_ERROR_MARKERS)


def _legacy_access(tenant_id: str, user_id: str, legacy_role: str, exc: Exception) -> dict:
    logger.error(
        "RBAC schema unavailable for tenant %s user %s; using legacy %s access. Error: %s",
        tenant_id,
        user_id,
        legacy_role,
        exc,
    )
    if legacy_role == "owner":
        permissions = ALL_PERMISSION_KEYS
        role_name = "Owner"
        role_slug = "owner"
    else:
        permissions = DEFAULT_TELECALLER_PERMISSIONS
        role_name = "Telecaller"
        role_slug = "telecaller"
    return {
        "role_id": None,
        "role_name": role_name,
        "role_slug": role_slug,
        "permissions": normalize_permissions(permissions),
        "force_password_reset": False,
        "rbac_schema_unavailable": True,
    }


def _permission_values(values: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw = values.strip()
        if not raw:
            return []
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        return [item.strip().strip('"') for item in raw.split(",") if item.strip()]
    return list(values)


def normalize_permissions(values: list[str] | tuple[str, ...] | str | None) -> list[str]:
    allowed = set(ALL_PERMISSION_KEYS)
    return sorted({v for v in _permission_values(values) if v in allowed})


def _with_normalized_permissions(role: dict | None) -> dict | None:
    if not role:
        return None
    return {**role, "permissions": normalize_permissions(role.get("permissions"))}


def _select_default_role(db, tenant_id: str) -> dict | None:
    existing = (
        db.table("tenant_roles")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("slug", "telecaller")
        .limit(1)
        .execute()
    )
    return _with_normalized_permissions(existing.data[0]) if existing.data else None


def ensure_default_roles(db, tenant_id: str) -> dict:
    existing = _select_default_role(db, tenant_id)
    if existing:
        return existing

    row = {
        "tenant_id": tenant_id,
        "name": "Telecaller",
        "slug": "telecaller",
        "description": "Default calling workspace role for agents.",
        "permissions": DEFAULT_TELECALLER_PERMISSIONS,
        "is_system_template": True,
    }
    insert_error = None
    try:
        created = db.table("tenant_roles").insert(row).execute()
        if created.data:
            return _with_normalized_permissions(created.data[0])
    except Exception as e:
        insert_error = e
        logger.info("Default Telecaller role insert fell back to reselect for tenant %s: %s", tenant_id, e)

    existing = _select_default_role(db, tenant_id)
    if existing:
        return existing
    if insert_error:
        raise insert_error
    raise RuntimeError("Failed to create default Telecaller role")


def is_telecaller_role(role: dict | None) -> bool:
    if not role:
        return False
    permissions = normalize_permissions(role.get("permissions"))
    role_name = (role.get("name") or "").strip().lower()
    return role.get("slug") == "telecaller" or "telecaller" in role_name or "telecalling.dialer" in permissions


def get_user_role(db, tenant_id: str, role_id: str | None) -> dict | None:
    if not role_id:
        return None
    result = (
        db.table("tenant_roles")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("id", role_id)
        .limit(1)
        .execute()
    )
    return _with_normalized_permissions(result.data[0]) if result.data else None


def resolve_permissions(db, tenant_id: str, user_id: str, legacy_role: str) -> dict:
    if legacy_role == "owner":
        return {
            "role_id": None,
            "role_name": "Owner",
            "role_slug": "owner",
            "permissions": ALL_PERMISSION_KEYS,
            "force_password_reset": False,
        }

    try:
        ensure_default_roles(db, tenant_id)
        membership = (
            db.table("tenant_users")
            .select("role_id, force_password_reset")
            .eq("tenant_id", tenant_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        row = membership.data[0] if membership.data else {}
        role = get_user_role(db, tenant_id, row.get("role_id"))
        if not role:
            role = ensure_default_roles(db, tenant_id)
            db.table("tenant_users").update({"role_id": role["id"]}).eq("tenant_id", tenant_id).eq("user_id", user_id).execute()
    except Exception as exc:
        if is_rbac_schema_unavailable(exc):
            return _legacy_access(tenant_id, user_id, legacy_role, exc)
        raise

    return {
        "role_id": role["id"],
        "role_name": role["name"],
        "role_slug": role.get("slug"),
        "permissions": normalize_permissions(role.get("permissions")),
        "force_password_reset": bool(row.get("force_password_reset")),
    }


def touch_updated_at(row: dict) -> dict:
    return {**row, "updated_at": datetime.now(timezone.utc).isoformat()}
