import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from app.dependencies.auth import get_current_user

import os
from app.config import settings
from app.db.supabase import current_route
from app.services.scoring_rules import MORNING_SUMMARY_HOUR_IST
from app.routes import webhook, leads, messages, analytics, upload, segments, calls, callers, ai_tune, knowledge, system, follow_ups, numbers, incidents, lead_notes, voice_numbers, app_settings, templates, onboarding, team, media, todos, conversations, operator, chat_handovers, telegram, instagram, facebook, tags, inbound_leads, reengagement, notifications, assignment_log, call_scripts, telecalling_upload, push, subscriptions, catalog, rbac, feedback, ask, consistency
from app.routes.calls import public_router as calls_public_router
from app.routes.intake import public_router as intake_public_router
from app.routes import intake
from app.routes import call_review
from app.routes.marketplace_intake import public_router as marketplace_public_router
from app.routes import marketplace_intake
from app.routes import deals, business_details
from app.routes import brain
from app.routes import brain_sandbox
from app.routes import operator_brain
from app.routes import lead_details_share
from app.routes import scheduled_overview
from app.routes import auto_messages
from app.routes import private_send, private_send_keys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# httpx logs every request URL at INFO, query string included. Meta's Graph API takes
# credentials as query params, so that wrote the Meta app secret (inside the
# `{app_id}|{secret}` app access token) and every Page access token into Render's logs
# in plaintext — enough to forge webhook signatures for every tenant. Warnings and
# errors from httpx still come through; our own log lines are unaffected.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Laptop runs (scripts/dev-backend.sh) set OUTBOUND_MODE=dry_run: external sends are logged,
# not delivered. No-op in production (outbound_mode defaults to "live").
from app.services.outbound_guard import install_outbound_guard
install_outbound_guard()

from datetime import datetime, timezone
_startup_time = datetime.now(timezone.utc)
_heartbeats = {
    "scheduled-broadcasts": None,
    "callback-notifications": None,
    "number-quality-sync": None,
    "numbers-pool-sync": None,
    "send-log-prune": None,
    "call-ai-sweep": None,
    "ad-insights-sync": None,
    "astro-push-reconcile": None,
    "intake-staleness-sweep": None,
    "crm-cutoff-sweep": None,
    "call-alert-summary": None,
    "brain-weekly-digest": None,
    "auto-messages": None,
    "scheduled-templates": None,
    "private-send-meta-reconcile": None,
}


async def _process_scheduled_broadcasts() -> None:
    """APScheduler job: fire scheduled_broadcasts rows whose fire_at has passed."""
    _heartbeats["scheduled-broadcasts"] = datetime.now(timezone.utc)
    try:
        from app.db.supabase import get_supabase
        from app.services.broadcast_executor import execute_broadcast
        db = get_supabase()
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        rows = (
            db.table("scheduled_broadcasts")
            .select("*")
            .eq("status", "pending")
            .lte("fire_at", now)
            .limit(10)
            .execute()
        )
        for row in (rows.data or []):
            logger.info(f"Scheduled broadcast firing: id={row['id']} tenant={row['tenant_id']}")
            await execute_broadcast(row)
    except Exception as e:
        logger.error(f"Scheduled broadcast executor error: {e}")


async def _check_token_health() -> None:
    """APScheduler daily job: validate Meta tokens for all tenants, create incidents if invalid."""
    import httpx
    from app.db.supabase import get_supabase
    from app.services.incidents import create_token_incident as _create_token_incident, is_token_auth_failure

    db = get_supabase()
    rows = (
        db.table("app_settings")
        .select("tenant_id,key,value")
        .in_("key", [
            "meta_access_token", "meta_phone_number_id",
            "instagram_access_token", "instagram_page_id",
            "facebook_access_token", "facebook_page_id",
        ])
        .not_.is_("value", "null")
        .execute()
    )
    if not rows.data:
        return

    tenant_cfg: dict[str, dict] = {}
    for row in rows.data:
        tid = row["tenant_id"]
        if tid not in tenant_cfg:
            tenant_cfg[tid] = {}
        tenant_cfg[tid][row["key"]] = row["value"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for tenant_id, cfg in tenant_cfg.items():
            # WhatsApp
            wa_token = cfg.get("meta_access_token")
            wa_phone_id = cfg.get("meta_phone_number_id")
            if wa_token and wa_phone_id:
                try:
                    r = await client.get(
                        f"https://graph.facebook.com/v21.0/{wa_phone_id}",
                        params={"fields": "display_phone_number", "access_token": wa_token},
                    )
                    data = r.json()
                    if is_token_auth_failure(data.get("error")):
                        _create_token_incident(db, tenant_id, "whatsapp", data["error"].get("message", "Token invalid"))
                except Exception as e:
                    logger.warning(f"Token health check error tenant={tenant_id} channel=whatsapp: {e}")

            # Instagram
            ig_token = cfg.get("instagram_access_token")
            if ig_token:
                try:
                    r = await client.get(
                        "https://graph.facebook.com/v21.0/me",
                        params={"fields": "id", "access_token": ig_token},
                    )
                    data = r.json()
                    if is_token_auth_failure(data.get("error")):
                        _create_token_incident(db, tenant_id, "instagram", data["error"].get("message", "Token invalid"))
                except Exception as e:
                    logger.warning(f"Token health check error tenant={tenant_id} channel=instagram: {e}")

            # Facebook
            fb_token = cfg.get("facebook_access_token")
            if fb_token:
                try:
                    r = await client.get(
                        "https://graph.facebook.com/v21.0/me",
                        params={"fields": "id", "access_token": fb_token},
                    )
                    data = r.json()
                    if is_token_auth_failure(data.get("error")):
                        _create_token_incident(db, tenant_id, "facebook", data["error"].get("message", "Token invalid"))
                except Exception as e:
                    logger.warning(f"Token health check error tenant={tenant_id} channel=facebook: {e}")

    logger.info(f"Token health check complete for {len(tenant_cfg)} tenant(s)")


async def _process_reengagement_rules() -> None:
    """APScheduler job: process due automated re-engagement steps."""
    try:
        from app.services.reengagement_service import process_due_reengagements
        count = await process_due_reengagements()
        if count:
            logger.info(f"Re-engagement scheduler: processed {count} re-engagement message(s)")
    except Exception as e:
        logger.error(f"Re-engagement scheduler error: {e}")


async def _process_silence_nudges() -> None:
    """APScheduler job: send due silence nudges."""
    try:
        from app.services.silence_nudge import drain_due_nudges
        count = await drain_due_nudges()
        if count:
            logger.info(f"Silence nudge scheduler: sent {count} nudge(s)")
    except Exception as e:
        logger.error(f"Silence nudge scheduler error: {e}")


async def _sweep_unassigned_leads() -> None:
    """APScheduler job: state-based safety net that assigns any unassigned lead
    whose current segment qualifies under the tenant's telecalling_config."""
    try:
        from app.services.assignment import sweep_unassigned_leads
        sweep_unassigned_leads()
    except Exception as e:
        logger.error(f"Assignment sweep scheduler error: {e}")


async def _recycle_contacts() -> None:
    """APScheduler job: re-queue leads nobody has reached yet, within calling hours."""
    try:
        from app.services.contact_recycler import recycle_all_tenants
        count = recycle_all_tenants()
        if count:
            logger.info(f"Contact recycler: recycled {count} lead(s)")
    except Exception as e:
        logger.error(f"Contact recycler error: {e}")


async def _process_callback_notifications() -> None:
    """APScheduler job: callback 'due' reminders and 'claimable' broadcasts."""
    _heartbeats["callback-notifications"] = datetime.now(timezone.utc)
    try:
        from app.services.callback_notifications import process_callback_notifications
        result = process_callback_notifications()
        if result.get("due") or result.get("claimable"):
            logger.info(f"Callback notifications: {result['due']} due, {result['claimable']} claimable")
    except Exception as e:
        logger.error(f"Callback notifications error: {e}")


async def _sync_all_number_quality() -> None:
    """APScheduler 4-hourly job: refresh every number from Meta so a Red primary
    fails over within hours. See number_sync.sync_all_number_quality."""
    _heartbeats["number-quality-sync"] = datetime.now(timezone.utc)
    try:
        from app.services.number_sync import sync_all_number_quality
        await sync_all_number_quality()
    except Exception as e:
        logger.error(f"Number quality sync error: {e}")


async def _sync_numbers_pool() -> None:
    """APScheduler job at 06:00 and 18:00 IST: full numbers-pool sync from Meta for every
    tenant -- new numbers, verification, limits, warm-up, recovery."""
    _heartbeats["numbers-pool-sync"] = datetime.now(timezone.utc)
    try:
        from app.services.number_sync import sync_all_tenants_pool
        await sync_all_tenants_pool()
    except Exception as e:
        logger.error(f"Numbers pool sync error: {e}")


async def _prune_send_log() -> None:
    """APScheduler job at 03:00 IST: drop template_send_log rows too old to count."""
    _heartbeats["send-log-prune"] = datetime.now(timezone.utc)
    try:
        from app.services.outbound_router import prune_send_log
        await prune_send_log()
    except Exception as e:
        logger.error(f"Send-log prune error: {e}")


async def _sync_ad_insights() -> None:
    """APScheduler job: pull Meta Ads Insights per tenant and store daily
    clicks/spend for the Ad Performance tab."""
    _heartbeats["ad-insights-sync"] = datetime.now(timezone.utc)
    try:
        import asyncio
        from app.services.meta_ads_insights_sync import sync_all_tenants_ad_insights
        await asyncio.to_thread(sync_all_tenants_ad_insights)
    except Exception as e:
        logger.error(f"Ad insights scheduler error: {e}")


async def _sweep_call_ai() -> None:
    """APScheduler job: resume call recordings a restart interrupted and retry failures."""
    _heartbeats["call-ai-sweep"] = datetime.now(timezone.utc)
    try:
        from app.services.call_ai_pipeline import sweep_call_ai
        await sweep_call_ai()
    except Exception as e:
        logger.error(f"Call AI sweep error: {e}")


async def _process_pending_whatsapp_alerts() -> None:
    """APScheduler job: process due pending WhatsApp alerts."""
    try:
        from app.services.whatsapp_notify import process_due_whatsapp_alerts
        await process_due_whatsapp_alerts()
    except Exception as e:
        logger.error(f"Pending WhatsApp alerts scheduler error: {e}")


async def _reconcile_astro_pushes() -> None:
    """APScheduler job: re-drive AstroTamil consultation pushes that failed at
    payment-confirm time (paid sessions with astro_question_id still NULL)."""
    _heartbeats["astro-push-reconcile"] = datetime.now(timezone.utc)
    try:
        from app.services.intake import reconcile_pending_astro_pushes
        await reconcile_pending_astro_pushes()
    except Exception as e:
        logger.error(f"Astro push reconcile scheduler error: {e}")


async def _sweep_stale_intake_sessions() -> None:
    """APScheduler job: cancel unfinished deals idle past the tenant's deal_idle_close_days.
    See intake.sweep_stale_intake_sessions."""
    _heartbeats["intake-staleness-sweep"] = datetime.now(timezone.utc)
    try:
        from app.services.intake import sweep_stale_intake_sessions
        await sweep_stale_intake_sessions()
    except Exception as e:
        logger.error(f"Intake staleness sweep scheduler error: {e}")


async def _process_auto_messages() -> None:
    """APScheduler job: send Auto-Messages whose delay is up. See services/auto_messages.py."""
    _heartbeats["auto-messages"] = datetime.now(timezone.utc)
    try:
        from app.services.auto_messages import process_due_sends
        count = await process_due_sends()
        if count:
            logger.info(f"Auto-messages scheduler: sent {count} message(s)")
    except Exception as e:
        logger.error(f"Auto-messages scheduler error: {e}")


async def _process_scheduled_templates() -> None:
    """APScheduler job: send scheduled templates whose time has come. See services/scheduled_templates.py."""
    _heartbeats["scheduled-templates"] = datetime.now(timezone.utc)
    try:
        from app.services.scheduled_templates import process_due
        count = await process_due()
        if count:
            logger.info(f"Scheduled-templates scheduler: sent {count} message(s)")
    except Exception as e:
        logger.error(f"Scheduled-templates scheduler error: {e}")


async def _reconcile_private_send_meta() -> None:
    """APScheduler job: store Meta's message count for yesterday per Private Send tenant."""
    _heartbeats["private-send-meta-reconcile"] = datetime.now(timezone.utc)
    try:
        from app.services.private_send import process_meta_reconcile
        count = await process_meta_reconcile()
        if count:
            logger.info(f"Private Send reconcile: {count} tenant(s)")
    except Exception as e:
        logger.error(f"Private Send reconcile error: {e}")


async def _sweep_crm_cutoff() -> None:
    _heartbeats["crm-cutoff-sweep"] = datetime.now(timezone.utc)
    try:
        from app.services.call_ai_pipeline import sweep_crm_cutoff
        await sweep_crm_cutoff()
    except Exception as e:
        logger.error(f"CRM cut-off sweep error: {e}")


async def _send_call_alert_summaries() -> None:
    _heartbeats["call-alert-summary"] = datetime.now(timezone.utc)
    try:
        from app.db.supabase import get_supabase
        from app.services.call_alerts import send_morning_summaries
        send_morning_summaries(get_supabase())
    except Exception as e:
        logger.error(f"Call alert summary error: {e}")


async def _send_brain_weekly_digest() -> None:
    _heartbeats["brain-weekly-digest"] = datetime.now(timezone.utc)
    try:
        from app.db.supabase import get_supabase
        import asyncio
        from app.services.brain_digest import send_weekly_digests
        await asyncio.to_thread(send_weekly_digests, get_supabase())
    except Exception as e:
        logger.error(f"Brain weekly digest error: {e}")


# APScheduler's default misfire_grace_time is 1s: a run that starts more than 1s late is
# dropped as "missed". Ours start 1.3-2s late (many jobs share a second and block on sync DB
# calls), so for 30 days most runs of most jobs were silently skipped -- the intake sweep ran
# 6 times out of 8,520 (scheduler_runs, 2026-09-30). coalesce folds a backlog into one run.
_scheduler = AsyncIOScheduler(job_defaults={"misfire_grace_time": 60, "coalesce": True, "max_instances": 1})
# When this process's scheduler started: the "not running" alert measures from here for a
# job that has no successful run yet (operator._build_scheduler_jobs).
_scheduler_started_at: datetime | None = None


def _record_scheduler_event(event) -> None:
    """Persist every job run to scheduler_runs for the operator Scheduler Health
    view. Best-effort: must never raise into the scheduler."""
    try:
        if event.code == EVENT_JOB_ERROR:
            status = "error"
            error = str(getattr(event, "exception", "") or "")[:2000]
        elif event.code == EVENT_JOB_MISSED:
            status, error = "missed", None
        else:
            status, error = "success", None
        scheduled = getattr(event, "scheduled_run_time", None)
        ran_at = datetime.now(timezone.utc)
        lateness_ms = int((ran_at - scheduled).total_seconds() * 1000) if scheduled else None
        from app.db.supabase import get_supabase
        get_supabase().table("scheduler_runs").insert({
            "job_id": event.job_id,
            "status": status,
            "scheduled_at": scheduled.isoformat() if scheduled else None,
            "ran_at": ran_at.isoformat(),
            "lateness_ms": lateness_ms,
            "error": error,
        }).execute()
    except Exception as e:
        logger.warning(f"scheduler_runs record failed (non-fatal): {e}")


# Any sync call left on the event loop (a Supabase query not sent to a thread)
# freezes every request, health checks and the scheduler with it: 35-45 s on 24
# and 26 Oct, CPU idle, nothing in the logs. This makes such a freeze visible;
# the "Slow Supabase" log in db/supabase.py names the query.
_LOOP_LAG_INTERVAL = 0.5
_LOOP_LAG_WARN = 1.0


async def _watch_event_loop_lag() -> None:
    loop = asyncio.get_running_loop()
    while True:
        started = loop.time()
        await asyncio.sleep(_LOOP_LAG_INTERVAL)
        lag = loop.time() - started - _LOOP_LAG_INTERVAL
        if lag >= _LOOP_LAG_WARN:
            logger.warning(f"Event loop blocked for {lag:.1f}s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Anril AI backend starting up...")
    logger.info(f"Supabase: {settings.supabase_url}")
    logger.info("Voice: TeleCMI")

    _scheduler.add_job(
        _process_scheduled_broadcasts,
        trigger="interval",
        minutes=1,
        id="scheduled-broadcasts",
        replace_existing=True,
    )
    _scheduler.add_job(
        _check_token_health,
        trigger="interval",
        hours=4,
        id="token-health-check",
        replace_existing=True,
    )
    _scheduler.add_job(
        _process_reengagement_rules,
        trigger="interval",
        minutes=1,
        id="reengagement-rules",
        replace_existing=True,
    )
    _scheduler.add_job(
        _process_silence_nudges,
        trigger="interval",
        minutes=1,
        id="silence-nudge",
        replace_existing=True,
    )
    _scheduler.add_job(
        _sweep_unassigned_leads,
        trigger="interval",
        minutes=2,
        id="assignment-sweep",
        replace_existing=True,
    )
    _scheduler.add_job(
        _recycle_contacts,
        trigger="interval",
        minutes=30,
        id="recycle-contacts",
        replace_existing=True,
    )
    _scheduler.add_job(
        _process_callback_notifications,
        trigger="interval",
        minutes=1,
        id="callback-notifications",
        replace_existing=True,
    )
    _scheduler.add_job(
        _sync_all_number_quality,
        trigger="interval",
        hours=4,
        id="number-quality-sync",
        replace_existing=True,
    )
    _scheduler.add_job(
        _sync_ad_insights,
        trigger="interval",
        hours=1,
        id="ad-insights-sync",
        replace_existing=True,
    )
    _scheduler.add_job(
        _sweep_call_ai,
        trigger="interval",
        minutes=3,
        id="call-ai-sweep",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _process_pending_whatsapp_alerts,
        trigger="interval",
        minutes=1,
        id="pending-whatsapp-alerts",
        replace_existing=True,
    )
    _scheduler.add_job(
        _reconcile_astro_pushes,
        trigger="interval",
        minutes=5,
        id="astro-push-reconcile",
        replace_existing=True,
    )
    _scheduler.add_job(
        _sweep_stale_intake_sessions,
        trigger="interval",
        minutes=5,
        id="intake-staleness-sweep",
        replace_existing=True,
    )
    _scheduler.add_job(_process_auto_messages, trigger="interval", minutes=1, id="auto-messages",
                       replace_existing=True)
    _scheduler.add_job(_process_scheduled_templates, trigger="interval", minutes=1, id="scheduled-templates",
                       replace_existing=True)
    # Fixed clock times, not interval=12h: Render recycles the process every ~5h,
    # so an interval of 5h+ never fires (subsystem-notes.md, 2026-09-19).
    _scheduler.add_job(_sync_numbers_pool, trigger="cron", hour="6,18", minute=0,
                       timezone="Asia/Kolkata", id="numbers-pool-sync", replace_existing=True)
    _scheduler.add_job(_prune_send_log, trigger="cron", hour=3, minute=0,
                       timezone="Asia/Kolkata", id="send-log-prune", replace_existing=True)
    _scheduler.add_job(_reconcile_private_send_meta, trigger="cron", hour=3, minute=30,
                       timezone="Asia/Kolkata", id="private-send-meta-reconcile", replace_existing=True)
    _scheduler.add_job(_sweep_crm_cutoff, trigger="interval", minutes=10, id="crm-cutoff-sweep",
                       replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.add_job(_send_call_alert_summaries, trigger="cron", hour=MORNING_SUMMARY_HOUR_IST, minute=0,
                       timezone="Asia/Kolkata", id="call-alert-summary", replace_existing=True)
    _scheduler.add_job(_send_brain_weekly_digest, trigger="cron", day_of_week="mon", hour=9, minute=0,
                       timezone="Asia/Kolkata", id="brain-weekly-digest", replace_existing=True)
    _scheduler.add_listener(
        _record_scheduler_event,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    global _scheduler_started_at
    _scheduler_started_at = datetime.now(timezone.utc)
    _scheduler.start(paused=not settings.scheduler_enabled)
    if settings.scheduler_enabled:
        logger.info("Schedulers started: broadcasts(1m) + token-health(4h) + reengagement(1m) + assignment-sweep(2m) + recycle-contacts(30m) + callback-notify(1m) + quality-sync(4h) + numbers-pool-sync(06:00+18:00 IST) + send-log-prune(03:00 IST) + call-ai-sweep(3m) + pending-whatsapp-alerts(1m) + astro-push-reconcile(5m) + intake-staleness-sweep(5m) + silence-nudge(1m) + crm-cutoff-sweep(10m) + auto-messages(1m) + scheduled-templates(1m) + private-send-meta-reconcile(03:30 IST) + call-alert-summary(09:00 IST) + brain-weekly-digest(Mon 09:00 IST)")
    else:
        logger.warning("LOCAL MODE: SCHEDULER_ENABLED=false — 21 jobs registered but PAUSED; nothing will run")

    lag_watchdog = asyncio.create_task(_watch_event_loop_lag())

    yield

    lag_watchdog.cancel()
    _scheduler.shutdown(wait=False)
    logger.info("Anril AI backend shutting down.")


app = FastAPI(
    title="Anril AI",
    version="0.1.0",
    description="B2B SaaS Lead Intelligence Platform for Education Consultancies",
    lifespan=lifespan,
)

# Rate limiting. Webhook routes must always answer 200 even when throttled --
# a 4xx here reads as delivery failure and triggers provider retry storms
# (see .agents/context/security-checklist.md, hard check #2).
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    if request.url.path.startswith("/webhook/"):
        return Response(status_code=200)
    return JSONResponse(status_code=429, content={"detail": "Too many requests"})


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIASGIMiddleware)


@app.middleware("http")
async def server_error_json_middleware(request: Request, call_next):
    current_route.set(f"{request.method} {request.url.path}")
    try:
        return await call_next(request)
    except RateLimitExceeded:
        raise
    except Exception:
        logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )


# CORS - allow frontend origins
_allowed = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://www.anrilaitech.com",
    "https://anrilaitech.com",
    # Legacy host: kept so sessions and links from before the domain move still work.
    "https://www.bloommatrix.in",
    "https://bloommatrix.in",
]
_frontend_url = os.environ.get("FRONTEND_URL", "")
if _frontend_url:
    _allowed.append(_frontend_url)
# Allow all *.vercel.app subdomains for preview deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_origin_regex=r"https://aira-ai-.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




def _format_uptime(uptime_s: int) -> str:
    d, rem = divmod(uptime_s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d {h}h {m}m" if d else (f"{h}h {m}m" if h else f"{m}m")


def _base_health_payload(now: datetime) -> dict:
    uptime_s = int((now - _startup_time).total_seconds())
    return {
        "service": "anril-ai",
        "uptime_seconds": uptime_s,
        "uptime_human": _format_uptime(uptime_s),
        "started_at": _startup_time.isoformat(),
        "server_time": now.isoformat(),
    }


def _readiness_payload() -> tuple[dict, bool]:
    now = datetime.now(timezone.utc)

    # 1. Ping the Supabase database
    db_ok = False
    db_error = None
    try:
        from app.db.supabase import get_supabase
        db = get_supabase()
        db.table("app_settings").select("key").limit(1).execute()
        db_ok = True
    except Exception as e:
        db_error = str(e)
        logger.error(f"Health check database ping failed: {db_error}")

    # 2. Check scheduled jobs heartbeats
    now = datetime.now(timezone.utc)
    
    # scheduled-broadcasts (runs every 1 minute)
    sb_heartbeat = _heartbeats["scheduled-broadcasts"]
    sb_ok = False
    if sb_heartbeat is not None:
        if (now - sb_heartbeat).total_seconds() <= 180: # 3 minutes threshold
            sb_ok = True
    else:
        # Grace period since startup
        if (now - _startup_time).total_seconds() <= 180:
            sb_ok = True

    details = {
        "database": "ok" if db_ok else f"error: {db_error}",
        "scheduler_jobs": {
            "scheduled-broadcasts": {
                "status": "healthy" if sb_ok else "unhealthy",
                "last_heartbeat": sb_heartbeat.isoformat() if sb_heartbeat else None,
            }
        }
    }

    base = {**_base_health_payload(now), "details": details}

    ready = db_ok and sb_ok
    return {**base, "status": "healthy" if ready else "unhealthy"}, ready


# Liveness check (no auth, no prefix). Render uses this endpoint, so it must
# answer 200 while the process is alive even if dependencies are degraded.
@app.api_route("/health", methods=["GET", "HEAD"], tags=["system"])
async def health():
    now = datetime.now(timezone.utc)
    return {**_base_health_payload(now), "status": "healthy"}


# Readiness/deep health check (no auth, no prefix). Operator tooling can use
# this for dependency details without letting a DB blip fail Render liveness.
@app.api_route("/ready", methods=["GET", "HEAD"], tags=["system"])
async def ready():
    payload, is_ready = _readiness_payload()
    if is_ready:
        return payload
    return JSONResponse(status_code=503, content=payload)

_auth = [Depends(get_current_user)]

# Webhook routes — no auth (Meta calls directly)
app.include_router(webhook.router, prefix="/webhook/whatsapp", tags=["webhook"])
app.include_router(telegram.router, prefix="/webhook/telegram", tags=["telegram-webhook"])
app.include_router(instagram.router, prefix="/webhook/instagram", tags=["instagram-webhook"])
app.include_router(facebook.router, prefix="/webhook/facebook", tags=["facebook-webhook"])
app.include_router(calls_public_router, prefix="/api/v1/calls", tags=["calls-telecmi"])
app.include_router(intake_public_router, prefix="/api/v1/intake", tags=["intake-webhook"])
app.include_router(intake.router, prefix="/api/v1/intake", tags=["intake"], dependencies=_auth)
# Authed router MUST come first: its POST /{provider}/token would otherwise be
# swallowed by the public POST /{provider}/{ingest_token}, which reads "token"
# as the ingest token and 401s every "Generate URL" click.
app.include_router(marketplace_intake.router, prefix="/api/v1/marketplace", tags=["marketplace"], dependencies=_auth)
app.include_router(deals.router, prefix="/api/v1/deals", tags=["deals"], dependencies=_auth)
app.include_router(business_details.router, prefix="/api/v1/business-details", tags=["business-details"], dependencies=_auth)
app.include_router(marketplace_public_router, prefix="/api/v1/marketplace", tags=["marketplace-webhook"])
app.include_router(auto_messages.public_router, prefix="/api/v1/auto-messages", tags=["auto-messages-webhook"])
app.include_router(auto_messages.router, prefix="/api/v1/auto-messages", tags=["auto-messages"], dependencies=_auth)
app.include_router(private_send.public_router, prefix="/api/v1/private-send", tags=["private-send"])
app.include_router(private_send_keys.router, prefix="/api/v1/private-send", tags=["private-send-keys"], dependencies=_auth)
# Legacy prefix. Razorpay's dashboard has /api/v1/expert-handoff/razorpay-webhook
# registered externally; remove these two lines only after updating it there.
app.include_router(intake_public_router, prefix="/api/v1/expert-handoff", tags=["intake-webhook-legacy"])
app.include_router(intake.router, prefix="/api/v1/expert-handoff", tags=["intake-legacy"], dependencies=_auth)
# API routes — all require auth
app.include_router(lead_details_share.router, prefix="/api/v1/leads", tags=["leads"], dependencies=_auth)
app.include_router(scheduled_overview.router, prefix="/api/v1/scheduled-overview", tags=["scheduled-overview"], dependencies=_auth)
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"], dependencies=_auth)
app.include_router(messages.router, prefix="/api/v1/messages", tags=["messages"], dependencies=_auth)
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"], dependencies=_auth)
app.include_router(ask.router, prefix="/api/v1", tags=["ask"], dependencies=_auth)
app.include_router(upload.router, prefix="/api/v1/upload", tags=["upload"], dependencies=_auth)
app.include_router(segments.router, prefix="/api/v1/segments", tags=["segments"], dependencies=_auth)
app.include_router(calls.router, prefix="/api/v1/calls", tags=["calls"], dependencies=_auth)
app.include_router(callers.router, prefix="/api/v1/callers", tags=["callers"], dependencies=_auth)
app.include_router(ai_tune.router, prefix="/api/v1/ai-tune", tags=["ai-tune"], dependencies=_auth)
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"], dependencies=_auth)
app.include_router(consistency.router, prefix="/api/v1/consistency", tags=["consistency"], dependencies=_auth)
app.include_router(brain.router, prefix="/api/v1/brain", tags=["brain"], dependencies=_auth)
app.include_router(brain_sandbox.client_router, prefix="/api/v1/brain", tags=["brain"], dependencies=_auth)
app.include_router(catalog.router, prefix="/api/v1/catalog", tags=["catalog"], dependencies=_auth)
app.include_router(system.router, prefix="/api/v1/system", tags=["system"], dependencies=_auth)
app.include_router(follow_ups.router, prefix="/api/v1/follow-ups", tags=["follow-ups"], dependencies=_auth)
app.include_router(numbers.router, prefix="/api/v1/numbers", tags=["numbers"], dependencies=_auth)
app.include_router(incidents.router, prefix="/api/v1/incidents", tags=["incidents"], dependencies=_auth)
app.include_router(lead_notes.router, prefix="/api/v1/lead-notes", tags=["lead-notes"], dependencies=_auth)
app.include_router(call_review.router, prefix="/api/v1/call-review", tags=["call-review"], dependencies=_auth)
app.include_router(voice_numbers.router, prefix="/api/v1/voice-numbers", tags=["voice-numbers"], dependencies=_auth)
app.include_router(app_settings.router, prefix="/api/v1/settings", tags=["settings"], dependencies=_auth)
app.include_router(templates.public_router, prefix="/api/v1/templates", tags=["templates-webhook"])
app.include_router(templates.router, prefix="/api/v1/templates", tags=["templates"], dependencies=_auth)
app.include_router(onboarding.router, prefix="/api/v1/onboarding", tags=["onboarding"], dependencies=_auth)
app.include_router(team.router, prefix="/api/v1/team", tags=["team"], dependencies=_auth)
app.include_router(rbac.router, prefix="/api/v1/rbac", tags=["rbac"], dependencies=_auth)
app.include_router(media.router, prefix="/api/v1/leads", tags=["media"], dependencies=_auth)
app.include_router(todos.router, prefix="/api/v1/todos", tags=["todos"], dependencies=_auth)
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"], dependencies=_auth)
app.include_router(operator.router, prefix="/api/v1/operator", tags=["operator"])
app.include_router(operator_brain.router, prefix="/api/v1/operator", tags=["operator"])
app.include_router(brain_sandbox.operator_router, prefix="/api/v1/operator", tags=["operator"])
app.include_router(chat_handovers.router, prefix="/api/v1/chat-handovers", tags=["chat-handovers"], dependencies=_auth)
app.include_router(tags.router, prefix="/api/v1/broadcast-tags", tags=["broadcast-tags"], dependencies=_auth)
app.include_router(inbound_leads.router, prefix="/api/v1/inbound-leads", tags=["inbound-leads"], dependencies=_auth)
app.include_router(reengagement.router, prefix="/api/v1/reengagement", tags=["reengagement"], dependencies=_auth)
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"], dependencies=_auth)
app.include_router(assignment_log.router, prefix="/api/v1/assignment-log", tags=["assignment-log"], dependencies=_auth)
app.include_router(push.public_router, prefix="/api/v1/push", tags=["push-public"])
app.include_router(push.router, prefix="/api/v1/push", tags=["push"], dependencies=_auth)
app.include_router(call_scripts.router, prefix="/api/v1/call-scripts", tags=["call-scripts"], dependencies=_auth)
app.include_router(telecalling_upload.router, prefix="/api/v1/telecalling-upload", tags=["telecalling-upload"], dependencies=_auth)
app.include_router(subscriptions.router, prefix="/api/v1/subscriptions", tags=["subscriptions"], dependencies=_auth)
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"], dependencies=_auth)


