import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from app.db.supabase import _TRANSIENT as _DROPPED

logger = logging.getLogger(__name__)

# How often a write cut off by a dropped connection is sent again, and the first wait.
_RETRIES = 2
_RETRY_WAIT_SECONDS = 0.25

_SENSITIVE_MARKERS = ("password", "token", "secret", "key", "credential")
_MASK = "********"


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, raw in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in _SENSITIVE_MARKERS):
                clean[key_text] = _MASK
            else:
                clean[key_text] = _sanitize(raw)
        return clean
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def write_audit_event(
    db,
    *,
    tenant_id: str | None,
    actor_user_id: str | None,
    actor_role: str | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Append one audit row. Raises when the write fails: for callers that must not go on
    without the row (Claude Access withholds a tool's answer if its row cannot be written).

    The row's id is chosen here, so a write cut off by a dropped connection can be sent again
    without writing twice: the first try may already have been saved, and the retry saves the
    id only if it is not there yet."""
    row = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "metadata": _sanitize(metadata or {}),
    }
    try:
        db.table("app_audit_logs").insert(row).execute()
        return
    except _DROPPED as exc:
        dropped = exc
    for attempt in range(_RETRIES):
        time.sleep(_RETRY_WAIT_SECONDS * (2 ** attempt))
        try:
            db.table("app_audit_logs").upsert(row, on_conflict="id", ignore_duplicates=True).execute()
            return
        except _DROPPED as exc:
            dropped = exc
    raise dropped


def record_audit_event(
    db,
    *,
    tenant_id: str | None,
    actor_user_id: str | None,
    actor_role: str | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort append-only audit log.

    Audit logging should never break the user action it observes. During staged
    rollout the table may not exist yet, so failures are logged and swallowed.
    """
    try:
        write_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, actor_role=actor_role,
            action=action, target_type=target_type, target_id=target_id, metadata=metadata,
        )
    except Exception as exc:
        logger.warning("audit log insert failed action=%s target=%s:%s err=%s", action, target_type, target_id, exc)
