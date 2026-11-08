import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from app.dependencies.auth import get_current_user

import os
from app.config import settings
from app.db.supabase import current_route
from app.routes import webhook, leads, messages, analytics, upload, segments, calls, callers, ai_tune, knowledge, system, follow_ups, numbers, incidents, lead_notes, voice_numbers, app_settings, templates, onboarding, team, media, todos, conversations, operator, chat_handovers, telegram, instagram, facebook, tags, inbound_leads, reengagement, notifications, assignment_log, call_scripts, telecalling_upload, push, subscriptions, catalog, rbac, feedback, ask, consistency
from app.routes.calls import public_router as calls_public_router
from app.routes.intake import public_router as intake_public_router
from app.routes import intake
from app.routes import call_review
from app.routes.marketplace_intake import public_router as marketplace_public_router
from app.routes import marketplace_intake
from app.routes import deals, business_details
from app.routes import companions
from app.routes import brain
from app.routes import brain_sandbox
from app.routes import operator_brain
from app.routes import lead_details_share
from app.routes import scheduled_overview
from app.routes import sms, sms_contacts, sms_webhooks, operator_sms
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
# /ready reads the scheduled-broadcasts heartbeat; the queue task sets it each run.
_heartbeats = {"scheduled-broadcasts": None}


async def _process_scheduled_broadcasts() -> None:
    """Fire scheduled_broadcasts rows whose fire_at has passed (queue task scheduled-broadcasts)."""
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


async def _check_token_health() -> None:
    """Validate Meta tokens for all tenants, create incidents if invalid (queue task token-health-check)."""
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


async def _prune_scheduler_runs() -> None:
    """Drop scheduler_runs (failure) rows older than 7 days (queue task scheduler-runs-prune)."""
    from datetime import timedelta
    from app.db.supabase import get_supabase
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    get_supabase().table("scheduler_runs").delete().lt("ran_at", cutoff).execute()


# When this process started the queue worker: the "not running" alert measures from here for a
# job that has no successful run yet (operator._build_scheduler_jobs).
_scheduler_started_at: datetime | None = None
# The Procrastinate worker (SPEC.md): a task on this event loop.
_queue_worker: asyncio.Task | None = None


async def _run_queue_worker() -> None:
    """Run the queue worker inside the web process. Never blocks startup: a failed connection
    is logged and retried every 30 s, so the site stays up while the queue is unreachable."""
    from app.queue.app import queue_app
    import app.queue.tasks  # noqa: F401  (registers the periodic tasks)

    while True:
        try:
            async with queue_app.open_async():
                # Render sends SIGTERM 30 s before SIGKILL; the rescue task covers anything cut off.
                await queue_app.run_worker_async(install_signal_handlers=False, shutdown_graceful_timeout=20)
        except Exception as e:
            logger.error(f"Queue worker stopped: {e}; retrying in 30 s")
            await asyncio.sleep(30)


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

    global _scheduler_started_at, _queue_worker
    if not settings.scheduler_enabled:
        logger.warning("LOCAL MODE: SCHEDULER_ENABLED=false — queue worker not started; no scheduled job will run")
    elif not settings.database_url:
        logger.error("DATABASE_URL is not set: queue worker not started; no scheduled job will run")
    else:
        _scheduler_started_at = datetime.now(timezone.utc)
        _queue_worker = asyncio.create_task(_run_queue_worker())
        logger.info("Schedulers started (procrastinate): 24 queue tasks + rescue-stalled(1m) + queue-cleanup(03:45 IST) on queues messages, calls, maintenance")

    lag_watchdog = asyncio.create_task(_watch_event_loop_lag())

    yield

    lag_watchdog.cancel()
    if _queue_worker:
        _queue_worker.cancel()
        try:
            await _queue_worker
        except asyncio.CancelledError:
            pass
        _queue_worker = None
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
app.include_router(operator_sms.router, prefix="/api/v1/operator", tags=["operator-sms"])
app.include_router(sms.router, prefix="/api/v1/sms", tags=["sms"], dependencies=_auth)
app.include_router(sms_contacts.router, prefix="/api/v1/sms", tags=["sms-contacts"], dependencies=_auth)
app.include_router(sms_webhooks.router, tags=["sms-webhook"])
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
app.include_router(companions.router, prefix="/api/v1/companions", tags=["companions"], dependencies=_auth)


