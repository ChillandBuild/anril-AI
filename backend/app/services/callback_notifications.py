import json
import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase
from app.services.call_team_scope import leader_user_ids_for_caller
from app.services.notification_config import get_notification_config
from app.services.notify import notify_user, notify_callback_claimable

logger = logging.getLogger(__name__)

REMINDER_LEAD_MINUTES = 10      # push the telecaller this long before the slot
LATE_AFTER_MINUTES = 15         # alert the team leader when still pending this long after the slot
LATE_ALERT_WINDOW_MINUTES = 180  # ...but only for callbacks that went late recently (no alerts for old backlog)
_SCHEDULED_URL = "/dashboard/telecalling/scheduled"
_IST = timezone(timedelta(hours=5, minutes=30))
_warned_missing_columns = False


def _resolve_user_id(db, caller_id: str, tenant_id: str) -> str | None:
    if not caller_id:
        return None
    res = (
        db.table("callers").select("user_id").eq("id", caller_id).maybe_single().execute()
    )
    return (res.data or {}).get("user_id") if res else None


def _is_missing_column(exc: Exception) -> bool:
    text = str(exc).lower()
    return "does not exist" in text or "42703" in text or "pgrst204" in text or "could not find" in text


def _slot_label(scheduled_for: str | None) -> str:
    """The callback time as a telecaller reads it: IST, 24-hour, e.g. 11:00."""
    try:
        dt = datetime.fromisoformat(str(scheduled_for).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST).strftime("%H:%M")
    except Exception:
        return ""


def _claim(db, tid: str, job_id: str, column: str, now_iso: str) -> bool:
    """Stamp the once-only guard. True only for the single run that stamped it, so a retry or an
    overlapping run can never send the same reminder twice (a failed push is simply not retried)."""
    res = (
        db.table("follow_up_jobs").update({column: now_iso})
        .eq("id", job_id).eq("tenant_id", tid).is_(column, "null").execute()
    )
    return bool(res and res.data)


def _owner_user_ids(db, tid: str) -> list[str]:
    rows = db.table("tenant_users").select("user_id").eq("tenant_id", tid).eq("role", "owner").execute().data or []
    return [str(r["user_id"]) for r in rows if r.get("user_id")]


def _lead_and_caller(db, tid: str, lead_id: str) -> tuple[dict, dict]:
    lead = (
        db.table("leads").select("id,name,assigned_to,deleted_at")
        .eq("id", lead_id).eq("tenant_id", tid).maybe_single().execute()
    )
    ld = (lead.data or {}) if lead else {}
    caller: dict = {}
    if ld.get("assigned_to"):
        res = (
            db.table("callers").select("id,name,user_id")
            .eq("id", ld["assigned_to"]).eq("tenant_id", tid).maybe_single().execute()
        )
        caller = (res.data or {}) if res else {}
    return ld, caller


def _reminder_pass(db, tid: str, now: datetime, now_iso: str) -> int:
    """10 minutes before the slot: push the assigned telecaller once (guard: reminder_notified_at)."""
    upper_iso = (now + timedelta(minutes=REMINDER_LEAD_MINUTES)).isoformat()
    jobs = (
        db.table("follow_up_jobs").select("id,lead_id,scheduled_for")
        .eq("tenant_id", tid).eq("cadence", "callback").eq("status", "pending")
        .gt("scheduled_for", now_iso).lte("scheduled_for", upper_iso)
        .is_("reminder_notified_at", "null").limit(100).execute()
    )
    sent = 0
    for job in (jobs.data or []):
        try:
            ld, caller = _lead_and_caller(db, tid, job["lead_id"])
            if ld.get("deleted_at") or not caller.get("user_id"):
                continue
            if not _claim(db, tid, job["id"], "reminder_notified_at", now_iso):
                continue
            at = _slot_label(job.get("scheduled_for"))
            notify_user(
                tid, caller["user_id"], "callback_reminder", "Call-back coming up",
                f"Your call-back with '{ld.get('name') or 'your lead'}'" + (f" is at {at}." if at else " is coming up."),
                db=db, push_url=_SCHEDULED_URL,
            )
            sent += 1
        except Exception as e:
            logger.warning(f"callback reminder failed for job {job.get('id')}: {e}")
    return sent


def _late_alert_pass(db, tid: str, now: datetime, now_iso: str) -> int:
    """15 minutes after the slot and still pending: alert the team leader(s) of the telecaller's team,
    or the owner(s) when there is no team or no leader (guard: late_alerted_at). Staff only, never customers."""
    late_iso = (now - timedelta(minutes=LATE_AFTER_MINUTES)).isoformat()
    floor_iso = (now - timedelta(minutes=LATE_ALERT_WINDOW_MINUTES)).isoformat()
    jobs = (
        db.table("follow_up_jobs").select("id,lead_id,scheduled_for")
        .eq("tenant_id", tid).eq("cadence", "callback").eq("status", "pending")
        .lte("scheduled_for", late_iso).gte("scheduled_for", floor_iso)
        .is_("late_alerted_at", "null").limit(100).execute()
    )
    sent = 0
    for job in (jobs.data or []):
        try:
            ld, caller = _lead_and_caller(db, tid, job["lead_id"])
            if ld.get("deleted_at") or not caller.get("id"):
                continue  # nobody to be late: the "open to claim" broadcast covers unassigned callbacks
            if not _claim(db, tid, job["id"], "late_alerted_at", now_iso):
                continue
            try:
                recipients = leader_user_ids_for_caller(db, tid, caller["id"])
            except Exception as e:  # team tables not there yet: behave as "no leader"
                logger.warning(f"late alert: could not read the team leaders ({e}); alerting the owner")
                recipients = []
            recipients = [u for u in recipients if u != caller.get("user_id")]
            if not recipients:
                recipients = [u for u in _owner_user_ids(db, tid) if u != caller.get("user_id")]
            try:
                late = max(LATE_AFTER_MINUTES, int((now - datetime.fromisoformat(str(job["scheduled_for"]).replace("Z", "+00:00"))).total_seconds() // 60))
            except Exception:
                late = LATE_AFTER_MINUTES
            at = _slot_label(job.get("scheduled_for"))
            message = (
                f"{caller.get('name') or 'A telecaller'} is {late} min late on a call-back to "
                f"{ld.get('name') or 'a lead'}" + (f" ({at})" if at else "")
            )
            for uid in recipients:
                notify_user(tid, uid, "callback_late", "Call-back running late", message, db=db, push_url=_SCHEDULED_URL)
            sent += 1
        except Exception as e:
            logger.warning(f"callback late alert failed for job {job.get('id')}: {e}")
    return sent


def _run_reminder_steps(db, tid: str, now: datetime, now_iso: str) -> tuple[int, int]:
    """Reminder + late alert for one tenant. Never raises; skips with one warning when migration 307 is not applied."""
    global _warned_missing_columns
    reminders = late = 0
    for name, step in (("reminder", _reminder_pass), ("late alert", _late_alert_pass)):
        try:
            count = step(db, tid, now, now_iso)
            if name == "reminder":
                reminders = count
            else:
                late = count
        except Exception as e:
            if _is_missing_column(e):
                if not _warned_missing_columns:
                    _warned_missing_columns = True
                    logger.warning(f"callback {name}s skipped: migration 307 is not applied yet ({e})")
            else:
                logger.warning(f"callback {name} pass failed for tenant {tid}: {e}")
    return reminders, late


def process_callback_notifications() -> dict:
    """Scheduler job: callback 'due' reminders + 'claimable' broadcasts (claimable-only model),
    plus the heads-up before a slot and the late alert to the team leader (migration 307).

    Reminder:  10 minutes before the slot, push the assigned caller (once).
    Due:       at the scheduled slot, push the assigned caller.
    Claimable: threshold minutes later (config, default 15), broadcast to the configured
               audience regardless of shift. Guards prevent re-firing. Never raises.
    Late:      15 minutes after the slot and still pending, alert the team leader(s) (or the owner).
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    due_count = 0
    claimable_count = 0
    reminders = 0
    late_alerts = 0

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
            continue
        reminder_count, late_count = _run_reminder_steps(db, tid, now, now_iso)
        reminders += reminder_count
        late_alerts += late_count

    if due_count or claimable_count or reminders or late_alerts:
        logger.info(
            f"Callback notifications: {due_count} due, {claimable_count} claimable, "
            f"{reminders} reminders, {late_alerts} late alerts"
        )
    return {"due": due_count, "claimable": claimable_count}
