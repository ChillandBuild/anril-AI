"""M2: the 24 APScheduler jobs as Procrastinate periodic tasks (SPEC.md section 5).

Run with:
    cd backend && python -m pytest tests/test_queue_tasks.py -q -p no:cacheprovider
"""
import inspect
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter

import app.main
from app.queue import tasks as queue_tasks
from app.queue.app import queue_app
from test_scheduler_local_mode import FakeScheduler

START = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)  # a Monday
FIRES = 30

MESSAGES = {
    "scheduled-broadcasts", "reengagement-rules", "silence-nudge", "callback-notifications",
    "pending-whatsapp-alerts", "auto-messages", "scheduled-templates", "sms-send",
    "call-alert-summary", "brain-weekly-digest",
}
CALLS = {"call-ai-sweep", "crm-cutoff-sweep"}
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
    "scheduled-broadcasts": ("app.main._process_scheduled_broadcasts_body", True, False),
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
    "numbers-pool-sync": ("app.services.number_sync.sync_all_tenants_pool", True, False),
    "send-log-prune": ("app.services.outbound_router.prune_send_log", True, False),
    "scheduler-runs-prune": ("app.main._prune_scheduler_runs_body", True, False),
    "private-send-meta-reconcile": ("app.services.private_send.process_meta_reconcile", True, False),
    "crm-cutoff-sweep": ("app.services.call_ai_pipeline.sweep_crm_cutoff", True, False),
    "call-alert-summary": ("app.services.call_alerts.send_morning_summaries", False, True),
    "brain-weekly-digest": ("app.services.brain_digest.send_weekly_digests", False, True),
}


@pytest_asyncio.fixture
async def apscheduler_jobs() -> dict[str, dict]:
    """Every add_job call the lifespan makes, keyed by job id."""
    scheduler = FakeScheduler()
    with patch("app.main._scheduler", scheduler), patch("app.main.settings.scheduler_enabled", False):
        async with app.main.lifespan(app.main.app):
            pass
    return {kw["id"]: kw for _, _, kw in scheduler.calls["add_job"]}


def _periodic() -> dict[str, object]:
    return {pid: pt for (_, pid), pt in queue_app.periodic_registry.periodic_tasks.items()}


def _call_task(name: str):
    func = queue_app.tasks[name].func
    return func(timestamp=0)


def test_every_apscheduler_job_has_a_periodic_task(apscheduler_jobs):
    assert set(_periodic()) == set(apscheduler_jobs)
    assert len(_periodic()) == 24


def test_task_name_matches_periodic_id():
    for (task_name, periodic_id), pt in queue_app.periodic_registry.periodic_tasks.items():
        assert task_name == periodic_id == pt.task.name


def _apscheduler_fires(kw: dict) -> list[datetime]:
    fields = {k: kw[k] for k in ("day_of_week", "hour", "minute") if k in kw}
    trigger = CronTrigger(timezone=kw["timezone"], **fields)
    fires, prev, now = [], None, START
    for _ in range(FIRES):
        prev = trigger.get_next_fire_time(prev, now)
        fires.append(prev)
        now = prev
    return fires


def _croniter_fires(cron: str) -> list[datetime]:
    it = croniter(cron, START)
    return [it.get_next(datetime) for _ in range(FIRES)]


def test_cron_jobs_fire_at_the_same_instants(apscheduler_jobs):
    cron_ids = [i for i, kw in apscheduler_jobs.items() if kw["trigger"] == "cron"]
    assert len(cron_ids) == 6
    for job_id in cron_ids:
        expected = _apscheduler_fires(apscheduler_jobs[job_id])
        assert _croniter_fires(_periodic()[job_id].cron) == expected, job_id


def test_interval_jobs_keep_their_period_aligned_to_the_clock(apscheduler_jobs):
    interval_ids = [i for i, kw in apscheduler_jobs.items() if kw["trigger"] == "interval"]
    assert len(interval_ids) == 18
    for job_id in interval_ids:
        kw = apscheduler_jobs[job_id]
        seconds = kw.get("minutes", 0) * 60 + kw.get("hours", 0) * 3600
        fires = _croniter_fires(_periodic()[job_id].cron)
        gaps = {(b - a).total_seconds() for a, b in zip(fires, fires[1:])}
        assert gaps == {seconds}, job_id


def test_call_alert_summary_follows_the_morning_summary_hour(apscheduler_jobs):
    expected = _apscheduler_fires(apscheduler_jobs["call-alert-summary"])
    assert _croniter_fires(_periodic()["call-alert-summary"].cron) == expected


def test_queues():
    for job_id, pt in _periodic().items():
        want = "messages" if job_id in MESSAGES else "calls" if job_id in CALLS else "maintenance"
        assert queue_app.tasks[job_id].queue == want, job_id
        assert pt.task.queue == want, job_id


def test_retry_classes():
    assert set(queue_tasks.RETRY_CLASS) == set(_periodic())
    for job_id, cls in queue_tasks.RETRY_CLASS.items():
        want = "B" if job_id in CLASS_B else "C" if job_id in CLASS_C else "A"
        assert cls == want, job_id
    values = list(queue_tasks.RETRY_CLASS.values())
    assert (values.count("A"), values.count("B"), values.count("C")) == (14, 4, 6)


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
    with patch("app.main._process_scheduled_broadcasts_body", AsyncMock()):
        await _run("scheduled-broadcasts")
    assert isinstance(app.main._heartbeats["scheduled-broadcasts"], datetime)


@pytest.mark.parametrize("wrapper,body", [
    ("_process_scheduled_broadcasts", "_process_scheduled_broadcasts_body"),
    ("_prune_scheduler_runs", "_prune_scheduler_runs_body"),
])
@pytest.mark.asyncio
async def test_the_apscheduler_wrapper_still_swallows_and_logs(wrapper, body, caplog):
    caplog.set_level(logging.ERROR, logger="app.main")
    with patch(f"app.main.{body}", AsyncMock(side_effect=RuntimeError("boom"))) as mock:
        await getattr(app.main, wrapper)()
    mock.assert_awaited_once()
    assert any("boom" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_the_broadcast_wrapper_still_stamps_its_heartbeat():
    app.main._heartbeats["scheduled-broadcasts"] = None
    with patch("app.main._process_scheduled_broadcasts_body", AsyncMock()):
        await app.main._process_scheduled_broadcasts()
    assert isinstance(app.main._heartbeats["scheduled-broadcasts"], datetime)
