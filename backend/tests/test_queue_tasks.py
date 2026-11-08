"""M2: the 25 scheduled jobs as Procrastinate periodic tasks (SPEC.md section 5).

Run with:
    cd backend && python -m pytest tests/test_queue_tasks.py -q -p no:cacheprovider
"""
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from croniter import croniter

import app.main
from app.queue import tasks as queue_tasks
from app.queue.app import queue_app
from app.services.scoring_rules import MORNING_SUMMARY_HOUR_IST

START = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)  # a Monday
FIRES = 30

MESSAGES = {
    "scheduled-broadcasts", "reengagement-rules", "silence-nudge", "callback-notifications",
    "pending-whatsapp-alerts", "auto-messages", "scheduled-templates", "sms-send",
    "call-alert-summary", "brain-weekly-digest",
}
CALLS = {"call-ai-sweep", "crm-cutoff-sweep"}
COMPANION = {"companion-memory"}
CLASS_B = {"numbers-pool-sync", "send-log-prune", "scheduler-runs-prune", "private-send-meta-reconcile"}
CLASS_C = {
    "reengagement-rules", "silence-nudge", "pending-whatsapp-alerts", "callback-notifications",
    "call-alert-summary", "brain-weekly-digest",
}
SYNC_JOBS = {
    "assignment-sweep", "recycle-contacts", "callback-notifications", "call-alert-summary",
    "ad-insights-sync", "brain-weekly-digest",
}

# id -> (patch target, is the callee async, receives the Supabase client)
CALLEES = {
    "scheduled-broadcasts": ("app.main._process_scheduled_broadcasts", True, False),
    "token-health-check": ("app.main._check_token_health", True, False),
    "reengagement-rules": ("app.services.reengagement_service.process_due_reengagements", True, False),
    "silence-nudge": ("app.services.silence_nudge.drain_due_nudges", True, False),
    "assignment-sweep": ("app.services.assignment.sweep_unassigned_leads", False, False),
    "recycle-contacts": ("app.services.contact_recycler.recycle_all_tenants", False, False),
    "callback-notifications": ("app.services.callback_notifications.process_callback_notifications", False, False),
    "number-quality-sync": ("app.services.number_sync.sync_all_number_quality", True, False),
    "ad-insights-sync": ("app.services.meta_ads_insights_sync.sync_all_tenants_ad_insights", False, False),
    "call-ai-sweep": ("app.services.call_ai_pipeline.sweep_call_ai", True, False),
    "pending-whatsapp-alerts": ("app.services.whatsapp_notify.process_due_whatsapp_alerts", True, False),
    "astro-push-reconcile": ("app.services.intake.reconcile_pending_astro_pushes", True, False),
    "intake-staleness-sweep": ("app.services.intake.sweep_stale_intake_sessions", True, False),
    "auto-messages": ("app.services.auto_messages.process_due_sends", True, False),
    "scheduled-templates": ("app.services.scheduled_templates.process_due", True, False),
    "sms-send": ("app.services.sms_campaigns.process_due_sms", True, True),
    "sms-reconcile": ("app.services.sms_delivery.reconcile", True, True),
    "sms-balance-sync": ("app.services.sms_wallet.sync_balances", True, True),
    "numbers-pool-sync": ("app.services.number_sync.sync_all_tenants_pool", True, False),
    "send-log-prune": ("app.services.outbound_router.prune_send_log", True, False),
    "scheduler-runs-prune": ("app.main._prune_scheduler_runs", True, False),
    "private-send-meta-reconcile": ("app.services.private_send.process_meta_reconcile", True, False),
    "crm-cutoff-sweep": ("app.services.call_ai_pipeline.sweep_crm_cutoff", True, False),
    "call-alert-summary": ("app.services.call_alerts.send_morning_summaries", False, True),
    "brain-weekly-digest": ("app.services.brain_digest.send_weekly_digests", False, True),
    "companion-memory": ("app.companion.memory_sweep.run_memory_sweep", True, False),
}


IST = timezone(timedelta(hours=5, minutes=30))
MONDAY = 0

# The intended schedule, as people say it. Interval jobs: seconds between runs, aligned to the
# clock. Daily jobs: IST wall-clock times, optionally on one weekday only.
EVERY = {
    "scheduled-broadcasts": 60, "reengagement-rules": 60, "silence-nudge": 60,
    "callback-notifications": 60, "pending-whatsapp-alerts": 60, "auto-messages": 60,
    "scheduled-templates": 60, "sms-send": 60, "companion-memory": 60, "assignment-sweep": 120, "call-ai-sweep": 180,
    "astro-push-reconcile": 300, "intake-staleness-sweep": 300, "crm-cutoff-sweep": 600,
    "sms-reconcile": 900, "sms-balance-sync": 900, "recycle-contacts": 1800, "ad-insights-sync": 3600,
    "token-health-check": 4 * 3600, "number-quality-sync": 4 * 3600,
}
AT_IST = {
    "numbers-pool-sync": (["06:00", "18:00"], None),
    "send-log-prune": (["03:00"], None),
    "scheduler-runs-prune": (["03:15"], None),
    "private-send-meta-reconcile": (["03:30"], None),
    "call-alert-summary": ([f"{MORNING_SUMMARY_HOUR_IST:02d}:00"], None),
    "brain-weekly-digest": (["09:00"], MONDAY),
}


# The queue's own upkeep tasks (app/queue/safety.py), not business jobs.
SAFETY_TASKS = {"rescue-stalled", "queue-cleanup"}


def _periodic() -> dict[str, object]:
    return {
        pid: pt for (_, pid), pt in queue_app.periodic_registry.periodic_tasks.items() if pid not in SAFETY_TASKS
    }


def _call_task(name: str):
    func = queue_app.tasks[name].func
    return func(timestamp=0)


def test_every_scheduled_job_has_a_periodic_task():
    every = {pid for (_, pid) in queue_app.periodic_registry.periodic_tasks}
    assert every == set(EVERY) | set(AT_IST) | SAFETY_TASKS
    assert len(_periodic()) == 26


def test_task_name_matches_periodic_id():
    for (task_name, periodic_id), pt in queue_app.periodic_registry.periodic_tasks.items():
        assert task_name == periodic_id == pt.task.name


def _ist_fires(times: list[str], weekday: int | None) -> list[datetime]:
    fires, day = [], START.astimezone(IST).date()
    while len(fires) < FIRES:
        if weekday is None or day.weekday() == weekday:
            for t in times:
                h, m = map(int, t.split(":"))
                at = datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(timezone.utc)
                if at > START:
                    fires.append(at)
        day += timedelta(days=1)
    return sorted(fires)[:FIRES]


def _croniter_fires(cron: str) -> list[datetime]:
    it = croniter(cron, START)
    return [it.get_next(datetime) for _ in range(FIRES)]


def test_daily_jobs_fire_at_their_ist_times():
    for job_id, (times, weekday) in AT_IST.items():
        assert _croniter_fires(_periodic()[job_id].cron) == _ist_fires(times, weekday), job_id


def test_interval_jobs_keep_their_period_aligned_to_the_clock():
    for job_id, seconds in EVERY.items():
        fires = _croniter_fires(_periodic()[job_id].cron)
        gaps = {(b - a).total_seconds() for a, b in zip(fires, fires[1:])}
        assert gaps == {seconds}, job_id
        assert all(f.timestamp() % seconds == 0 for f in fires), job_id


def test_queues():
    for job_id, pt in _periodic().items():
        want = ("messages" if job_id in MESSAGES else "calls" if job_id in CALLS
                else "companion" if job_id in COMPANION else "maintenance")
        assert queue_app.tasks[job_id].queue == want, job_id
        assert pt.task.queue == want, job_id


def test_retry_classes():
    assert set(queue_tasks.RETRY_CLASS) == set(_periodic())
    for job_id, cls in queue_tasks.RETRY_CLASS.items():
        want = "B" if job_id in CLASS_B else "C" if job_id in CLASS_C else "A"
        assert cls == want, job_id
    values = list(queue_tasks.RETRY_CLASS.values())
    assert (values.count("A"), values.count("B"), values.count("C")) == (16, 4, 6)


def test_sync_and_async_split():
    assert set(CALLEES) == set(_periodic())
    for job_id in _periodic():
        is_coro = inspect.iscoroutinefunction(queue_app.tasks[job_id].func)
        assert is_coro == (job_id not in SYNC_JOBS), job_id


def _patched(job_id: str):
    target, is_async, _ = CALLEES[job_id]
    mock = AsyncMock() if is_async else MagicMock()
    return patch(target, mock), mock


async def _run(job_id: str) -> None:
    result = _call_task(job_id)
    if inspect.isawaitable(result):
        await result


@pytest.mark.parametrize("job_id", sorted(CALLEES))
@pytest.mark.asyncio
async def test_each_task_calls_its_service_once(job_id):
    db = object()
    patcher, mock = _patched(job_id)
    with patcher, patch("app.db.supabase.get_supabase", return_value=db):
        await _run(job_id)
    if CALLEES[job_id][2]:
        mock.assert_called_once_with(db)
    else:
        mock.assert_called_once_with()


@pytest.mark.parametrize("job_id", sorted(CALLEES))
@pytest.mark.asyncio
async def test_a_service_error_propagates_so_the_job_is_marked_failed(job_id):
    patcher, mock = _patched(job_id)
    mock.side_effect = RuntimeError("boom")
    with patcher, patch("app.db.supabase.get_supabase", return_value=object()):
        with pytest.raises(RuntimeError, match="boom"):
            await _run(job_id)


@pytest.mark.asyncio
async def test_scheduled_broadcasts_sets_the_heartbeat_for_the_ready_check():
    app.main._heartbeats["scheduled-broadcasts"] = None
    with patch("app.main._process_scheduled_broadcasts", AsyncMock()):
        await _run("scheduled-broadcasts")
    assert isinstance(app.main._heartbeats["scheduled-broadcasts"], datetime)



# sms-send is class A (a sweep), but two overlapping copies can both build the same
# campaign when a build runs past BUILD_STALE (10 min), so it is locked too.
ONE_AT_A_TIME = CLASS_C | {"sms-send", "companion-memory"}


@pytest.mark.parametrize("job_id", sorted(ONE_AT_A_TIME))
def test_a_job_that_could_double_send_runs_one_copy_at_a_time(job_id):
    """Regression: with no lock, the worker (concurrency 4) ran up to 4 copies of
    reengagement-rules at once and each one messaged the same leads. lock makes
    a copy wait for the running one; queueing_lock keeps at most one waiting."""
    task = queue_app.tasks[job_id]
    assert task.lock == job_id
    assert task.queueing_lock == job_id
