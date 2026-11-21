"""The "Download lists" rule (v9.2 Batch C): who may take a customer list out as a file.

Owner always may. Everyone else needs the leads.download permission (new in migration 307; every
existing custom role got it there so nobody who downloads today loses it; Telecaller and
Team leader do not have it). Each download is written to the Activity log: which list, how many
rows, which filters.
"""
import logging

from fastapi import HTTPException

from app.dependencies.tenant import _has_permission
from app.services.audit_log import record_audit_event

logger = logging.getLogger(__name__)

DOWNLOAD_PERMISSION = "leads.download"
DOWNLOAD_DENIED = "You don't have permission to download lists."


def can_download(ctx: dict) -> bool:
    return _has_permission(ctx, DOWNLOAD_PERMISSION)


def require_download(ctx: dict) -> dict:
    """Raises 403 unless the owner or a role with leads.download. Returns ctx for chaining."""
    if not can_download(ctx):
        raise HTTPException(status_code=403, detail=DOWNLOAD_DENIED)
    return ctx


def log_download(db, ctx: dict, *, list_name: str, row_count: int, filters: dict | None = None) -> None:
    """Activity log row for one successful download. Best-effort: never breaks the download."""
    try:
        used = {k: v for k, v in (filters or {}).items() if v not in (None, "", False)}
        record_audit_event(
            db,
            tenant_id=ctx.get("tenant_id"),
            actor_user_id=ctx.get("user_id"),
            actor_role=ctx.get("role"),
            action="leads.download",
            target_type="download",
            target_id=None,
            metadata={"list": list_name, "rows": int(row_count), "filters": used},
        )
    except Exception as e:  # record_audit_event already swallows; this guards the dict building
        logger.warning("download audit failed for %s: %s", list_name, e)
