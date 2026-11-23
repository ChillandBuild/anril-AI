"""v9.2 #26 small helpers shared by the Evening summary, Come-back offer and pause logic:
one JSON setting per business in app_settings, the owner's bell/phone, and the template status check."""
import json
import logging

logger = logging.getLogger(__name__)


def read_setting(db, tenant_id: str, key: str) -> dict:
    """The JSON setting `key` for this business, or {} when it was never saved or cannot be read."""
    try:
        row = (
            db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", key)
            .maybe_single().execute()
        )
        if row and row.data and row.data.get("value"):
            value = json.loads(row.data["value"])
            return value if isinstance(value, dict) else {}
    except Exception as e:
        logger.warning(f"automations: could not read {key} for {tenant_id}: {e}")
    return {}


def write_setting(db, tenant_id: str, key: str, value: dict) -> dict:
    db.table("app_settings").upsert(
        {"tenant_id": tenant_id, "key": key, "value": json.dumps(value), "is_secret": False},
        on_conflict="tenant_id,key",
    ).execute()
    return value


def settings_rows(db, key: str) -> list[dict]:
    """Every business's row for `key`: [{tenant_id, value(dict)}]. Unreadable rows are left out."""
    out = []
    try:
        rows = db.table("app_settings").select("tenant_id, value").eq("key", key).limit(5000).execute().data or []
    except Exception as e:
        logger.warning(f"automations: could not list {key}: {e}")
        return out
    for r in rows:
        try:
            value = json.loads(r.get("value") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and r.get("tenant_id"):
            out.append({"tenant_id": r["tenant_id"], "value": value})
    return out


def template_status_of(db, tenant_id: str, name: str | None) -> str | None:
    """PENDING / APPROVED / REJECTED / PAUSED ..., or None when the business has no template with that name."""
    if not name:
        return None
    try:
        rows = (
            db.table("message_templates").select("status").eq("tenant_id", tenant_id).eq("name", name)
            .limit(5).execute().data or []
        )
    except Exception as e:
        logger.warning(f"automations: template status not read ({name}): {e}")
        return None
    statuses = [(r.get("status") or "PENDING").upper() for r in rows]
    if not statuses:
        return None
    return "APPROVED" if "APPROVED" in statuses else statuses[0]


def owner_user_ids(db, tenant_id: str) -> list[str]:
    try:
        rows = (
            db.table("tenant_users").select("user_id").eq("tenant_id", tenant_id).eq("role", "owner")
            .limit(20).execute().data or []
        )
    except Exception as e:
        logger.warning(f"automations: owners not read for {tenant_id}: {e}")
        return []
    return [r["user_id"] for r in rows if r.get("user_id")]


def owner_phone(db, tenant_id: str) -> str | None:
    """The business's own contact number in WhatsApp's +<country><number> form, or None."""
    try:
        row = db.table("tenants").select("contact_phone").eq("id", tenant_id).maybe_single().execute()
        raw = ((row.data if row else None) or {}).get("contact_phone") or ""
    except Exception as e:
        logger.warning(f"automations: owner phone not read for {tenant_id}: {e}")
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) == 10:
        digits = "91" + digits          # a bare 10-digit number is Indian, like the rest of the app
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits
