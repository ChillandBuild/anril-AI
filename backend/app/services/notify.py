import logging
import re

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# migration 315 adds app_notifications.url. Until it is applied the insert is retried without it.
_url_column_warned = False


def _is_missing_url_column(err: Exception) -> bool:
    msg = str(err).lower()
    if "url" not in msg:
        return False
    return any(k in msg for k in ("column", "schema cache", "pgrst204", "42703"))


def _insert_notification(db, row: dict, url: str | None = None) -> None:
    """Insert one app_notifications row, with its link when given.

    If the url column does not exist yet (migration 315 not applied), retry once without it.
    Any other error is raised to the caller.
    """
    global _url_column_warned
    if url:
        try:
            db.table("app_notifications").insert({**row, "url": url}).execute()
            return
        except Exception as e:
            if not _is_missing_url_column(e):
                raise
            if not _url_column_warned:
                _url_column_warned = True
                logger.warning("app_notifications.url is missing (migration 315 not applied); saving alerts without a link")
    db.table("app_notifications").insert(row).execute()


def notify_user(
    tenant_id: str,
    user_id: str,
    type: str,
    title: str,
    message: str,
    *,
    db=None,
    dedupe_lead_id: str | None = None,
    push_url: str | None = None,
    push: bool = True,
) -> None:
    """Insert a single notification for one user. Best-effort: never raises.

    `push_url` is also stored as the alert's link (app_notifications.url) so the bell can open it.
    `push=False` writes the bell row only (no web push).
    """
    if not user_id:
        return
    db = db or get_supabase()
    try:
        if dedupe_lead_id:
            existing = (
                db.table("app_notifications")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("user_id", user_id)
                .eq("type", type)
                .eq("is_read", False)
                .limit(50)
                .execute()
            )
            if existing.data:
                return
        _insert_notification(db, {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "type": type,
            "title": title,
            "message": message,
        }, push_url)
        try:
            from app.services.notification_config import push_allowed
            if push and push_allowed(tenant_id, type, db=db):
                from app.services.web_push import send_user_push
                push_body = re.sub(r"\s*\[(lead_id|handover_id):.*?\]", "", message)
                send_user_push(
                    tenant_id,
                    user_id,
                    title=title,
                    body=push_body,
                    url=push_url or "/dashboard",
                    tag=f"{type}:{dedupe_lead_id}" if dedupe_lead_id else type,
                    data={"type": type, "lead_id": dedupe_lead_id},
                    db=db,
                )
        except Exception as push_err:
            logger.warning("notify_user push failed (type=%s user=%s): %s", type, user_id, push_err)
    except Exception as e:
        logger.warning(f"notify_user failed (type={type} user={user_id}): {e}")


def notify_assigned_caller_of_reply(lead_id: str, tenant_id: str, *, db=None) -> None:
    """Notify the caller who owns this lead that the lead replied. Best-effort."""
    if not lead_id:
        return
    db = db or get_supabase()
    try:
        lead = (
            db.table("leads")
            .select("assigned_to,name,blocked_at")
            .eq("id", lead_id)
            .maybe_single()
            .execute()
        )
        data = lead.data if lead else None
        if not data or not data.get("assigned_to"):
            return
        if data.get("blocked_at"):
            return  # a blocked person's message is saved but never alerts the team (full block)
        caller = (
            db.table("callers")
            .select("user_id")
            .eq("id", data["assigned_to"])
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        user_id = (caller.data or {}).get("user_id") if caller else None
        if not user_id:
            return
        notify_user(
            tenant_id,
            user_id,
            "lead_replied",
            "Lead replied",
            f"'{data.get('name') or 'Your lead'}' just replied.",
            db=db,
            dedupe_lead_id=lead_id,
            push_url=f"/dashboard/conversations?lead={lead_id}",
        )
    except Exception as e:
        logger.warning(f"notify_assigned_caller_of_reply failed (lead={lead_id}): {e}")


def _active_caller_user_ids(db, tenant_id: str) -> list[str]:
    callers = (
        db.table("callers")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
        .eq("status", "active")
        .execute()
    )
    return [c["user_id"] for c in (callers.data or []) if c.get("user_id")]


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


def _enrolled_caller_user_ids(db, tenant_id: str) -> list[str]:
    """user_ids of every enrolled caller (active=True), regardless of online status.

    Push reaches anyone with a push_subscriptions row (app installed), so we must
    NOT filter on caller.status — a logged-out caller with the app still gets push.
    """
    callers = (
        db.table("callers")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
        .execute()
    )
    return [c["user_id"] for c in (callers.data or []) if c.get("user_id")]


def _caller_user_ids_by_ids(db, tenant_id: str, caller_ids: list[str]) -> list[str]:
    """user_ids for a specific set of active caller IDs (for the 'specific' audience)."""
    if not caller_ids:
        return []
    res = (
        db.table("callers")
        .select("user_id")
        .eq("tenant_id", tenant_id)
        .eq("active", True)
        .in_("id", caller_ids)
        .execute()
    )
    return [c["user_id"] for c in (res.data or []) if c.get("user_id")]


def notify_callback_claimable(
    tenant_id: str,
    *,
    title: str,
    message: str,
    lead_id: str,
    audience: str = "telecallers_and_admin",
    caller_ids: list[str] | None = None,
    exclude_user_ids: list[str] | None = None,
    db=None,
) -> None:
    """Broadcast a claimable callback (in-app + push) to the configured audience.

    audience:
      "telecallers_and_admin" → all enrolled callers + owner
      "telecallers_only"      → all enrolled callers
      "admin_only"            → owner
      "specific"              → only the callers in caller_ids (owner NOT auto-added)
    Reuses notify_user so each recipient gets bell + push (push still subject to
    push_allowed). Dedupe across re-runs is handled by claimable_notified_at, so
    we do NOT pass dedupe_lead_id. Best-effort: never raises.
    """
    db = db or get_supabase()
    exclude = set(exclude_user_ids or [])
    try:
        recipients: set[str] = set()
        if audience == "specific":
            recipients |= set(_caller_user_ids_by_ids(db, tenant_id, caller_ids or []))
        else:
            if audience in ("telecallers_and_admin", "telecallers_only"):
                recipients |= set(_enrolled_caller_user_ids(db, tenant_id))
            if audience in ("telecallers_and_admin", "admin_only"):
                owner = _owner_user_id(db, tenant_id)
                if owner:
                    recipients.add(owner)
        for uid in recipients - exclude:
            notify_user(
                tenant_id, uid, "callback_claimable", title, message,
                db=db, push_url="/dashboard/telecalling/scheduled",
            )
    except Exception as e:
        logger.warning(f"notify_callback_claimable failed (lead={lead_id}): {e}")


def notify_pool(
    tenant_id: str,
    type: str,
    title: str,
    message: str,
    *,
    db=None,
    segments: list | None = None,
    exclude_user_ids: list[str] | None = None,
    url: str | None = None,
) -> None:
    """Fan out one notification per active caller + owner. Best-effort: never raises.

    `segments` is accepted for future per-segment routing; the callers table has
    no segment column today, so it does not filter recipients yet.
    `url` is the page the alert opens; a handover alert whose message carries a
    [lead_id:...] tag falls back to that lead's chat.
    """
    db = db or get_supabase()
    exclude = set(exclude_user_ids or [])
    if not url and type == "handover_new":
        m = re.search(r"\[lead_id:([^\]\s]+)\]", message or "")
        if m:
            url = f"/dashboard/conversations?lead={m.group(1)}"
    try:
        recipients = set(_active_caller_user_ids(db, tenant_id))
        owner = _owner_user_id(db, tenant_id)
        if owner:
            recipients.add(owner)
        for uid in recipients:
            if uid in exclude:
                continue
            _insert_notification(db, {
                "tenant_id": tenant_id,
                "user_id": uid,
                "type": type,
                "title": title,
                "message": message,
            }, url)
    except Exception as e:
        logger.warning(f"notify_pool failed (type={type}): {e}")


def clear_pool_notifications_for_lead(tenant_id: str, lead_id: str, *, db=None) -> None:
    """Mark handover/pool notifications for a lead as read for all users when claimed/resolved."""
    db = db or get_supabase()
    try:
        db.table("app_notifications").update({"is_read": True}).eq("tenant_id", tenant_id).in_("type", ["handover_new", "callback_claimable"]).like("message", f"%{lead_id}%").execute()
    except Exception as e:
        logger.warning(f"clear_pool_notifications_for_lead failed for lead {lead_id}: {e}")

