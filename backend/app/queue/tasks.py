"""The 26 scheduled jobs as Procrastinate periodic tasks (SPEC.md M2). Each task calls its service
function with no try/except, so a failure marks the job failed. Cron is UTC; IST is UTC+5:30."""
from app.queue.app import queue_app
from app.services.scoring_rules import MORNING_SUMMARY_HOUR_IST

# A: a sweep, the next tick redoes it. B: idempotent daily, rescued and re-run once.
# C: could double-send, never re-run, and never two copies at once (see _one_at_a_time).
RETRY_CLASS: dict[str, str] = {
    "scheduled-broadcasts": "A",
    "token-health-check": "A",
    "reengagement-rules": "C",
    "silence-nudge": "C",
    "assignment-sweep": "A",
    "recycle-contacts": "A",
    "callback-notifications": "C",
    "number-quality-sync": "A",
    "ad-insights-sync": "A",
    "call-ai-sweep": "A",
    "pending-whatsapp-alerts": "C",
    "astro-push-reconcile": "A",
    "intake-staleness-sweep": "A",
    "auto-messages": "A",
    "scheduled-templates": "A",
    "sms-send": "A",
    "sms-reconcile": "A",
    "sms-balance-sync": "A",
    "numbers-pool-sync": "B",
    "send-log-prune": "B",
    "scheduler-runs-prune": "B",
    "private-send-meta-reconcile": "B",
    "crm-cutoff-sweep": "A",
    "instant-forms-catch-up": "A",
    "call-alert-summary": "C",
    "brain-weekly-digest": "C",
    "companion-memory": "A",
}


def _one_at_a_time(job_id: str) -> dict:
    """Task options for a class-C job (and sms-send). The worker runs 4 jobs at once, so without these an
    every-minute job overlapped itself and each copy messaged the same people. lock: a copy
    waits until the running one finishes. queueing_lock: at most one copy waits in line
    (the periodic deferrer skips a slot while one is queued). A dead worker's copy is marked
    failed by rescue-stalled, which releases the lock."""
    return {"lock": job_id, "queueing_lock": job_id}


def _daily_ist_as_utc_cron(hour: int, minute: int) -> str:
    """Daily cron for a fixed IST clock time, in UTC (IST has no DST)."""
    total = (hour * 60 + minute - 330) % 1440
    return f"{total % 60} {total // 60} * * *"


@queue_app.periodic(cron="* * * * *", periodic_id="scheduled-broadcasts")
@queue_app.task(name="scheduled-broadcasts", queue="messages")
async def scheduled_broadcasts(timestamp: int) -> None:
    from datetime import datetime, timezone
    from app import main
    main._heartbeats["scheduled-broadcasts"] = datetime.now(timezone.utc)
    await main._process_scheduled_broadcasts()


@queue_app.periodic(cron="0 */4 * * *", periodic_id="token-health-check")
@queue_app.task(name="token-health-check", queue="maintenance")
async def token_health_check(timestamp: int) -> None:
    from app import main
    await main._check_token_health()


@queue_app.periodic(cron="* * * * *", periodic_id="reengagement-rules")
@queue_app.task(name="reengagement-rules", **_one_at_a_time("reengagement-rules"), queue="messages")
async def reengagement_rules(timestamp: int) -> None:
    from app.services.reengagement_service import process_due_reengagements
    await process_due_reengagements()


@queue_app.periodic(cron="* * * * *", periodic_id="silence-nudge")
@queue_app.task(name="silence-nudge", **_one_at_a_time("silence-nudge"), queue="messages")
async def silence_nudge(timestamp: int) -> None:
    from app.services.silence_nudge import drain_due_nudges
    await drain_due_nudges()


@queue_app.periodic(cron="*/2 * * * *", periodic_id="assignment-sweep")
@queue_app.task(name="assignment-sweep", queue="maintenance")
def assignment_sweep(timestamp: int) -> None:
    from app.services.assignment import sweep_unassigned_leads
    sweep_unassigned_leads()


# Class A: each lead's template is claimed pending -> sending, so a re-run or an
# overlap with the live webhook never sends twice.
@queue_app.periodic(cron="*/30 * * * *", periodic_id="instant-forms-catch-up")
@queue_app.task(name="instant-forms-catch-up", queue="messages")
async def instant_forms_catch_up(timestamp: int) -> None:
    from app.services.meta_lead_forms import catch_up_all
    await catch_up_all()


@queue_app.periodic(cron="*/30 * * * *", periodic_id="recycle-contacts")
@queue_app.task(name="recycle-contacts", queue="maintenance")
def recycle_contacts(timestamp: int) -> None:
    from app.services.contact_recycler import recycle_all_tenants
    recycle_all_tenants()


@queue_app.periodic(cron="* * * * *", periodic_id="callback-notifications")
@queue_app.task(name="callback-notifications", **_one_at_a_time("callback-notifications"), queue="messages")
def callback_notifications(timestamp: int) -> None:
    from app.services.callback_notifications import process_callback_notifications
    process_callback_notifications()


@queue_app.periodic(cron="0 */4 * * *", periodic_id="number-quality-sync")
@queue_app.task(name="number-quality-sync", queue="maintenance")
async def number_quality_sync(timestamp: int) -> None:
    from app.services.number_sync import sync_all_number_quality
    await sync_all_number_quality()


@queue_app.periodic(cron="0 * * * *", periodic_id="ad-insights-sync")
@queue_app.task(name="ad-insights-sync", queue="maintenance")
def ad_insights_sync(timestamp: int) -> None:
    from app.services.meta_ads_insights_sync import sync_all_tenants_ad_insights
    sync_all_tenants_ad_insights()


@queue_app.periodic(cron="*/3 * * * *", periodic_id="call-ai-sweep")
@queue_app.task(name="call-ai-sweep", queue="calls")
async def call_ai_sweep(timestamp: int) -> None:
    from app.services.call_ai_pipeline import sweep_call_ai
    await sweep_call_ai()


@queue_app.periodic(cron="* * * * *", periodic_id="pending-whatsapp-alerts")
@queue_app.task(name="pending-whatsapp-alerts", **_one_at_a_time("pending-whatsapp-alerts"), queue="messages")
async def pending_whatsapp_alerts(timestamp: int) -> None:
    from app.services.whatsapp_notify import process_due_whatsapp_alerts
    await process_due_whatsapp_alerts()


@queue_app.periodic(cron="*/5 * * * *", periodic_id="astro-push-reconcile")
@queue_app.task(name="astro-push-reconcile", queue="maintenance")
async def astro_push_reconcile(timestamp: int) -> None:
    from app.services.intake import reconcile_pending_astro_pushes
    await reconcile_pending_astro_pushes()


@queue_app.periodic(cron="*/5 * * * *", periodic_id="intake-staleness-sweep")
@queue_app.task(name="intake-staleness-sweep", queue="maintenance")
async def intake_staleness_sweep(timestamp: int) -> None:
    from app.services.intake import sweep_stale_intake_sessions
    await sweep_stale_intake_sessions()


@queue_app.periodic(cron="* * * * *", periodic_id="auto-messages")
@queue_app.task(name="auto-messages", queue="messages")
async def auto_messages(timestamp: int) -> None:
    from app.services.auto_messages import process_due_sends
    await process_due_sends()


@queue_app.periodic(cron="* * * * *", periodic_id="scheduled-templates")
@queue_app.task(name="scheduled-templates", queue="messages")
async def scheduled_templates(timestamp: int) -> None:
    from app.services.scheduled_templates import process_due
    await process_due()


@queue_app.periodic(cron="* * * * *", periodic_id="sms-send")
# Class A, but locked: overlapping copies could both build one campaign once a build
# runs past BUILD_STALE (10 min) and send its SMS twice (sms_campaigns.build_preparing).
@queue_app.task(name="sms-send", **_one_at_a_time("sms-send"), queue="messages")
async def sms_send(timestamp: int) -> None:
    from app.db.supabase import get_supabase
    from app.services.sms_campaigns import process_due_sms
    await process_due_sms(get_supabase())


@queue_app.periodic(cron="*/15 * * * *", periodic_id="sms-reconcile")
@queue_app.task(name="sms-reconcile", queue="maintenance")
async def sms_reconcile(timestamp: int) -> None:
    from app.db.supabase import get_supabase
    from app.services.sms_delivery import reconcile
    await reconcile(get_supabase())


@queue_app.periodic(cron="*/15 * * * *", periodic_id="sms-balance-sync")
@queue_app.task(name="sms-balance-sync", queue="maintenance")
async def sms_balance_sync(timestamp: int) -> None:
    from app.db.supabase import get_supabase
    from app.services.sms_wallet import sync_balances
    await sync_balances(get_supabase())


@queue_app.periodic(cron="30 0,12 * * *", periodic_id="numbers-pool-sync")  # 06:00 and 18:00 IST
@queue_app.task(name="numbers-pool-sync", queue="maintenance")
async def numbers_pool_sync(timestamp: int) -> None:
    from app.services.number_sync import sync_all_tenants_pool
    await sync_all_tenants_pool()


@queue_app.periodic(cron="30 21 * * *", periodic_id="send-log-prune")  # 03:00 IST
@queue_app.task(name="send-log-prune", queue="maintenance")
async def send_log_prune(timestamp: int) -> None:
    from app.services.outbound_router import prune_send_log
    await prune_send_log()


@queue_app.periodic(cron="45 21 * * *", periodic_id="scheduler-runs-prune")  # 03:15 IST
@queue_app.task(name="scheduler-runs-prune", queue="maintenance")
async def scheduler_runs_prune(timestamp: int) -> None:
    from app import main
    await main._prune_scheduler_runs()


@queue_app.periodic(cron="0 22 * * *", periodic_id="private-send-meta-reconcile")  # 03:30 IST
@queue_app.task(name="private-send-meta-reconcile", queue="maintenance")
async def private_send_meta_reconcile(timestamp: int) -> None:
    from app.services.private_send import process_meta_reconcile
    await process_meta_reconcile()


@queue_app.periodic(cron="*/10 * * * *", periodic_id="crm-cutoff-sweep")
@queue_app.task(name="crm-cutoff-sweep", queue="calls")
async def crm_cutoff_sweep(timestamp: int) -> None:
    from app.services.call_ai_pipeline import sweep_crm_cutoff
    await sweep_crm_cutoff()


@queue_app.periodic(cron=_daily_ist_as_utc_cron(MORNING_SUMMARY_HOUR_IST, 0), periodic_id="call-alert-summary")
@queue_app.task(name="call-alert-summary", **_one_at_a_time("call-alert-summary"), queue="messages")
def call_alert_summary(timestamp: int) -> None:
    from app.db.supabase import get_supabase
    from app.services.call_alerts import send_morning_summaries
    send_morning_summaries(get_supabase())


@queue_app.periodic(cron="30 3 * * 1", periodic_id="brain-weekly-digest")  # Monday 09:00 IST
@queue_app.task(name="brain-weekly-digest", **_one_at_a_time("brain-weekly-digest"), queue="messages")
def brain_weekly_digest(timestamp: int) -> None:
    from app.db.supabase import get_supabase
    from app.services.brain_digest import send_weekly_digests
    send_weekly_digests(get_supabase())


@queue_app.periodic(cron="30 20 * * *", periodic_id="companion-memory")  # 02:00 IST
@queue_app.task(name="companion-memory", **_one_at_a_time("companion-memory"), queue="companion")
async def companion_memory(timestamp: int) -> None:
    """Aira Companion Level 2 memory card: turns the day's chat messages into facts, nightly
    (spec 2026-11-09 §3.2). Locked so a long night (up to 500 pairs) never runs twice at once."""
    from app.companion.memory_sweep import run_memory_sweep
    await run_memory_sweep()


@queue_app.periodic(cron="* * * * *", periodic_id="rescue-stalled")
@queue_app.task(name="rescue-stalled", queue="maintenance", pass_context=True)
async def rescue_stalled(context, timestamp: int) -> None:
    from app.queue import safety
    await safety.rescue_stalled(context.app)


@queue_app.periodic(cron="15 22 * * *", periodic_id="queue-cleanup")  # 03:45 IST
@queue_app.task(name="queue-cleanup", queue="maintenance", pass_context=True)
async def queue_cleanup(context, timestamp: int) -> None:
    from app.queue import safety
    await safety.cleanup(context.app)
