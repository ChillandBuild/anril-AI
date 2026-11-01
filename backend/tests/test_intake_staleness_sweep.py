"""The intake staleness sweep (blueprint D1): an unfinished deal is closed only after the
tenant's idle-close days with no lead message and no real progress (last_activity_at), in
EVERY unfinished status; a paid session is never touched by it; a live link is never cut
off; a fresh lead message beats the sweep; and one bad row never stops the rest."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.services import intake
from app.services.intake import sweep_stale_intake_sessions
from tests.fake_supabase import FakeSupabase

T1, T2 = "tenant-1", "tenant-2"
UNFINISHED = (
    "offer_pending", "awaiting_package_choice", "awaiting_addon_choice", "collecting",
    "awaiting_confirmation", "awaiting_payment",
)


def _ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _session(db, tenant=T1, status="collecting", idle=None, **extra) -> dict:
    return db.add("intake_sessions", **{
        "tenant_id": tenant, "lead_id": f"lead-{len(db.rows('intake_sessions'))}", "status": status,
        "last_activity_at": _ago(days=idle) if idle is not None else None, "payment_link": None,
        "payment_link_expires_at": None, **extra,
    })


def _status(db, row) -> str:
    return next(r["status"] for r in db.rows("intake_sessions") if r["id"] == row["id"])


@pytest.fixture
def days():
    """Per-tenant idle-close days; the mock records how often each tenant was read."""
    table = {T1: 30, T2: 5}
    with patch("app.services.deal_settings.read_deal_idle_close_days", side_effect=lambda t: table[t]) as m:
        yield m


@pytest.fixture(autouse=True)
def _no_side_effects():
    with patch.object(intake, "_sync_deal"), patch.object(intake, "cancel_session_link", new=AsyncMock(return_value=True)) as c:
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("status", UNFINISHED)
async def test_every_unfinished_status_closes_after_the_idle_days(status, days):
    db = FakeSupabase()
    row = _session(db, status=status, idle=31)
    out = await sweep_stale_intake_sessions(db=db)
    assert out["cancelled"] == 1
    assert _status(db, row) == "cancelled"


@pytest.mark.asyncio
async def test_offer_pending_stuck_since_august_is_closed(days):
    db = FakeSupabase()
    row = _session(db, status="offer_pending", idle=49)
    await sweep_stale_intake_sessions(db=db)
    assert _status(db, row) == "cancelled"


@pytest.mark.asyncio
async def test_a_deal_idle_less_than_the_tenants_days_is_left_alone(days):
    db = FakeSupabase()
    row = _session(db, status="awaiting_payment", idle=29)
    out = await sweep_stale_intake_sessions(db=db)
    assert out["cancelled"] == 0 and _status(db, row) == "awaiting_payment"


@pytest.mark.asyncio
async def test_the_old_48h_created_at_rule_no_longer_closes_an_active_deal(days):
    """Created long ago but the lead was active yesterday: not idle."""
    db = FakeSupabase()
    row = _session(db, status="awaiting_payment", idle=1, created_at=_ago(days=40))
    await sweep_stale_intake_sessions(db=db)
    assert _status(db, row) == "awaiting_payment"


@pytest.mark.asyncio
async def test_each_tenant_uses_its_own_days_and_is_read_once(days):
    db = FakeSupabase()
    quick = _session(db, tenant=T2, status="collecting", idle=6)   # T2 closes after 5 days
    slow = _session(db, tenant=T1, status="collecting", idle=6)    # T1 waits 30 days
    _session(db, tenant=T2, status="offer_pending", idle=9)
    await sweep_stale_intake_sessions(db=db)
    assert _status(db, quick) == "cancelled" and _status(db, slow) == "collecting"
    reads = [c.args[0] for c in days.call_args_list]
    assert sorted(reads) == sorted(set(reads))  # one read per tenant


@pytest.mark.asyncio
async def test_a_live_link_is_never_cut_off(days):
    db = FakeSupabase()
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = _session(db, status="awaiting_payment", idle=40, payment_link="https://rzp.io/x", payment_link_expires_at=future)
    await sweep_stale_intake_sessions(db=db)
    assert _status(db, row) == "awaiting_payment"


@pytest.mark.asyncio
async def test_an_expired_link_deal_is_closed_and_its_link_cancelled(days, _no_side_effects):
    db = FakeSupabase()
    row = _session(db, status="awaiting_payment", idle=40, payment_link="https://rzp.io/x",
                   payment_link_expires_at=_ago(days=39), razorpay_payment_link_id="plink_1")
    await sweep_stale_intake_sessions(db=db)
    assert _status(db, row) == "cancelled"
    _no_side_effects.assert_awaited_once()
    assert _no_side_effects.await_args.args[1]["id"] == row["id"]


@pytest.mark.asyncio
async def test_a_message_that_lands_during_the_sweep_wins(days):
    """The row was idle when the sweep read it; the lead's message touches it before the
    cancel write. The conditional update must not fire."""
    db = FakeSupabase()
    row = _session(db, status="collecting", idle=40)
    real = intake.cancel_open_session

    async def touch_first(db_, session, **kw):
        intake.touch_session_activity(db_, T1, session["id"])
        return await real(db_, session, **kw)

    with patch.object(intake, "cancel_open_session", touch_first):
        out = await sweep_stale_intake_sessions(db=db)
    assert out["cancelled"] == 0 and _status(db, row) == "collecting"


@pytest.mark.asyncio
async def test_a_status_change_during_the_sweep_wins(days):
    db = FakeSupabase()
    row = _session(db, status="awaiting_payment", idle=40)
    real = intake.cancel_open_session

    async def paid_first(db_, session, **kw):
        db.rows("intake_sessions")[0]["status"] = "paid"
        return await real(db_, session, **kw)

    with patch.object(intake, "cancel_open_session", paid_first):
        await sweep_stale_intake_sessions(db=db)
    assert _status(db, row) == "paid"


@pytest.mark.asyncio
async def test_a_session_from_the_deploy_gap_with_no_activity_value_uses_created_at(days):
    db = FakeSupabase()
    old = _session(db, status="collecting", idle=None, created_at=_ago(days=45))
    new = _session(db, status="collecting", idle=None, created_at=_ago(days=3))
    await sweep_stale_intake_sessions(db=db)
    assert _status(db, old) == "cancelled" and _status(db, new) == "collecting"


@pytest.mark.asyncio
async def test_a_paid_session_is_never_resolved_by_the_sweep_however_old(days):
    """Only the astrologer's delivered answer closes a paid session (deliver_astro_reply)."""
    db = FakeSupabase()
    old = _session(db, status="paid", idle=90, paid_at=_ago(days=90))
    out = await sweep_stale_intake_sessions(db=db)
    assert out == {"cancelled": 0}
    assert _status(db, old) == "paid"


@pytest.mark.asyncio
async def test_one_failing_cancel_does_not_stop_the_rest(days):
    db = FakeSupabase()
    bad = _session(db, status="collecting", idle=40)
    good = _session(db, status="collecting", idle=41)
    real = intake.cancel_open_session

    async def flaky(db_, session, **kw):
        if session["id"] == bad["id"]:
            raise RuntimeError("db blip")
        return await real(db_, session, **kw)

    with patch.object(intake, "cancel_open_session", flaky):
        out = await sweep_stale_intake_sessions(db=db)
    assert out["cancelled"] == 1 and _status(db, good) == "cancelled"


@pytest.mark.asyncio
async def test_no_stale_rows_is_a_clean_no_op(days):
    db = FakeSupabase()
    assert await sweep_stale_intake_sessions(db=db) == {"cancelled": 0}


def test_sweep_job_is_registered_in_the_scheduler():
    import app.queue.tasks  # noqa: F401  (registers the periodic tasks)
    from app.queue.app import queue_app

    assert "intake-staleness-sweep" in queue_app.tasks
