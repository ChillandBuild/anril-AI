import json
import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase
from app.services.notification_config import get_notification_config
from app.services.notify import notify_user, notify_callback_claimable

logger = logging.getLogger(__name__)


def _resolve_user_id(db, caller_id: str, tenant_id: str) -> str | None:
    if not caller_id:
        return None
    res = (
        db.table("callers").select("user_id").eq("id", caller_id).maybe_single().execute()
    )
    return (res.data or {}).get("user_id") if res else None


def process_callback_notifications() -> dict:
    """Scheduler job: callback 'due' reminders + 'claimable' broadcasts (claimable-only model).

    Due:       at the scheduled slot, push the assigned caller.
    Claimable: threshold minutes later (config, default 15), broadcast to the configured
               audience regardless of shift. Guards prevent re-firing. Never raises.
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    due_count = 0
    claimable_count = 0

    try:
        tenants = (
            db.table("app_settings").select("tenant_id,value").eq("key", "telecalling_config").execute()
        )
    except Exception as e:
        logger.error(f"callback notifications: tenant scan failed: {e}")
        return {"due": 0, "claimable": 0}

    seen: set[str] = set()
    for row in (tenants.data or []):
        tid = row.get("tenant_id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        try:
            # Read "enabled" from the scan's own row: a get_telecalling_config call per
            # tenant every minute was ~13k app_settings requests a day (2026-10-31).
            if not json.loads(row.get("value") or "{}").get("enabled"):
                continue
            ncfg = get_notification_config(tid, db=db)
            threshold = int(ncfg.get("claimable_threshold_minutes", 15) or 15)
            audience = ncfg.get("claimable_audience", "telecallers_and_admin")
            audience_caller_ids = ncfg.get("claimable_caller_ids") or []
            claimable_cutoff_iso = (now - timedelta(minutes=threshold)).isoformat()

            # ── DUE PASS ──
            due_jobs = (
                db.table("follow_up_jobs")
                .select("id,lead_id")
                .eq("tenant_id", tid).eq("cadence", "callback").eq("status", "pending")
                .lte("scheduled_for", now_iso).is_("due_notified_at", "null")
                .limit(100).execute()
            )
            for job in (due_jobs.data or []):
                try:
                    lead = (
                        db.table("leads").select("id,name,assigned_to")
                        .eq("id", job["lead_id"]).eq("tenant_id", tid).maybe_single().execute()
                    )
                    ld = (lead.data or {}) if lead else {}
                    uid = _resolve_user_id(db, ld.get("assigned_to"), tid) if ld.get("assigned_to") else None
                    if uid:
                        notify_user(
                            tid, uid, "callback_due", "Callback due now",
                            f"Your scheduled callback with '{ld.get('name') or 'your lead'}' is due now.",
                            db=db, push_url="/dashboard/telecalling/scheduled",
                        )
                    db.table("follow_up_jobs").update({"due_notified_at": now_iso}) \
                        .eq("id", job["id"]).eq("tenant_id", tid).execute()
                    due_count += 1
                except Exception as e:
                    logger.warning(f"callback due notify failed for job {job['id']}: {e}")

            # ── CLAIMABLE PASS (no shift check) ──
            claimable_jobs = (
                db.table("follow_up_jobs")
                .select("id,lead_id")
                .eq("tenant_id", tid).eq("cadence", "callback").eq("status", "pending")
                .lte("scheduled_for", claimable_cutoff_iso).is_("claimable_notified_at", "null")
                .limit(100).execute()
            )
            for job in (claimable_jobs.data or []):
                try:
                    lead = (
                        db.table("leads").select("id,name,assigned_to")
                        .eq("id", job["lead_id"]).eq("tenant_id", tid).maybe_single().execute()
                    )
                    ld = (lead.data or {}) if lead else {}
                    exclude: list[str] = []
                    if ld.get("assigned_to"):
                        owner_uid = _resolve_user_id(db, ld.get("assigned_to"), tid)
                        if owner_uid:
                            exclude.append(owner_uid)
                    notify_callback_claimable(
                        tid,
                        title="Callback open to claim",
                        message=f"An overdue callback with '{ld.get('name') or 'a lead'}' is open to claim.",
                        lead_id=job["lead_id"],
                        audience=audience,
                        caller_ids=audience_caller_ids,
                        exclude_user_ids=exclude,
                        db=db,
                    )
                    db.table("follow_up_jobs").update({"claimable_notified_at": now_iso}) \
                        .eq("id", job["id"]).eq("tenant_id", tid).execute()
                    claimable_count += 1
                except Exception as e:
                    logger.warning(f"callback claimable notify failed for job {job['id']}: {e}")
        except Exception as e:
            logger.error(f"callback notifications failed for tenant {tid}: {e}")

    if due_count or claimable_count:
        logger.info(f"Callback notifications: {due_count} due, {claimable_count} claimable")
    return {"due": due_count, "claimable": claimable_count}
