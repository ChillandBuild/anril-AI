"""v9.2 #216: the AI puts a customer on a FULL batch's waiting list; the list is told when a seat frees."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services import courses as svc
from app.services import deal_actions
from tests.fake_supabase import FakeSupabase
from tests.test_courses import BATCH, T, enrol, enrol_row, world

# Monday 23 Nov 2026, 11:00 IST: inside the 9 AM-8 PM send hours.
NOW = datetime(2026, 11, 23, 5, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh():
    svc.clear_cache()


def _full_world():
    db = world(seats=1)
    enrol_row(db, 1, paid=1)  # the only seat is taken
    return db


# ── the AI tool ─────────────────────────────────────────────────────────────

def test_tool_is_offered_only_while_a_batch_is_full_and_lists_only_full_ids():
    assert svc.ai_tool(world(seats=3), T) is None
    svc.clear_cache()  # full batches are cached 60 s per business; a new world needs a fresh read
    tool = svc.ai_tool(_full_world(), T)
    assert tool["function"]["name"] == "join_batch_waitlist"
    assert tool["function"]["parameters"]["properties"]["batch_id"]["enum"] == [BATCH]


def test_prompt_block_carries_batch_ids_and_the_waitlist_rule():
    block = svc.prompt_block(_full_world(), T)
    assert f"[{BATCH}]" in block and "join_batch_waitlist" in block and "FULL" in block


def test_ai_joins_the_customer_once_and_refuses_a_batch_with_seats():
    db = _full_world()
    db.add("leads", id="L9", tenant_id=T, name="Priya", phone="+919840012345")
    assert svc.ai_join_waitlist(db, T, "L9", "+919840012345", BATCH) is None
    assert svc.ai_join_waitlist(db, T, "L9", "+919840012345", BATCH) is None  # once per number
    rows = db.rows("batch_waitlist")
    assert len(rows) == 1 and rows[0]["source"] == "ai" and rows[0]["lead_id"] == "L9" and rows[0]["name"] == "Priya"
    assert "not a batch id" in svc.ai_join_waitlist(db, T, "L9", "+919840012345", "nope")
    roomy = world(seats=5)
    roomy.add("leads", id="L9", tenant_id=T, name="Priya", phone="+919840012345")
    assert "has a seat" in svc.ai_join_waitlist(roomy, T, "L9", "+919840012345", BATCH)


def test_the_deal_turn_runs_the_tool():
    db = _full_world()
    db.add("leads", id="L9", tenant_id=T, name="Priya", phone="+919840012345")
    ctx = deal_actions.DealContext(config={}, db=db, lead_id="L9", tenant_id=T, phone="+919840012345")
    call = {"function": {"name": "join_batch_waitlist", "arguments": f'{{"batch_id": "{BATCH}"}}'}}
    out = asyncio.run(deal_actions.apply_tool_calls([call], ctx))
    assert out.refusals == () and len(db.rows("batch_waitlist")) == 1


def test_enrolling_takes_the_person_off_that_batch_waitlist():
    db = world(seats=3)
    svc.join_waitlist(db, T, BATCH, "98765 43210", "Ravi")
    enrol(db)
    assert db.rows("batch_waitlist") == []


# ── telling the waiting list ────────────────────────────────────────────────

def _waiting(db, n, *, told_at=None, inbound=None):
    db.add("leads", id=f"W{n}", tenant_id=T, name=f"Wait{n}", phone=f"+91980000000{n}", opted_out=False,
           last_inbound_at=inbound)
    db.add("batch_waitlist", id=f"00000000-0000-0000-0000-00000000aa0{n}", tenant_id=T, batch_id=BATCH, lead_id=f"W{n}",
           phone=f"+91980000000{n}", name=f"Wait{n}", created_at=f"2026-11-0{n}T00:00:00+00:00", told_at=told_at)


def _run(db, *, approved=(), connected=True):
    bells = []
    with patch("app.config_dynamic.get_setting", return_value="x" if connected else None), \
            patch("app.services.call_details_share._approved_templates", return_value=list(approved)), \
            patch("app.services.blocked_guard.is_blocked", AsyncMock(return_value=False)), \
            patch("app.services.ai_reply.send_whatsapp", AsyncMock(return_value="wamid.1")) as text, \
            patch("app.services.orders._send_order_template", AsyncMock(return_value=("wamid.2", "tpl text"))) as tpl, \
            patch("app.services.orders._shop_name", return_value="Bright Academy"), \
            patch.object(svc, "_seat_bell", lambda db, tid, title, msg: bells.append(title)):
        told = asyncio.run(svc.tell_waitlists(db, NOW))
    return told, text, tpl, bells


def test_a_free_seat_tells_the_oldest_person_in_the_window_by_whatsapp():
    db = world(seats=2)
    enrol_row(db, 1, paid=1)  # one seat free
    _waiting(db, 1, inbound=(NOW - timedelta(hours=2)).isoformat())
    _waiting(db, 2, inbound=(NOW - timedelta(hours=2)).isoformat())
    told, text, tpl, bells = _run(db)
    assert told == 1 and text.await_count == 1 and tpl.await_count == 0
    assert "a seat is now free in Python, Weekend" in text.await_args.args[1]
    first, second = sorted(db.rows("batch_waitlist"), key=lambda r: r["created_at"])
    assert first["told_via"] == "text" and first["told_at"] and second.get("told_at") is None
    assert bells == ["Seat free in Weekend: Wait1 was told"]
    assert db.rows("messages")[0]["meta_message_id"] == "wamid.1"
    # Next run: the told person holds the seat, so nobody else is told.
    told, *_ = _run(db)
    assert told == 0


def test_outside_the_window_uses_the_approved_template_else_asks_the_team_to_call():
    db = world(seats=3)
    enrol_row(db, 1, paid=1)  # two seats free
    _waiting(db, 1, inbound=(NOW - timedelta(days=5)).isoformat())
    _waiting(db, 2, inbound=None)
    told, text, tpl, bells = _run(db, approved=[{"id": "TP", "name": "batch_seat_free"}])
    assert told == 2 and tpl.await_count == 2 and text.await_count == 0
    db2 = world(seats=2)
    enrol_row(db2, 1, paid=1)
    _waiting(db2, 1, inbound=None)
    told, text, tpl, bells = _run(db2)
    assert told == 1 and tpl.await_count == 0 and db2.rows("batch_waitlist")[0]["told_via"] == "staff"
    assert bells == ["Seat free in Weekend: call Wait1"]


def test_auto_reply_switched_off_means_the_team_calls_instead():
    db = world(seats=2)
    enrol_row(db, 1, paid=1)
    _waiting(db, 1, inbound=(NOW - timedelta(hours=2)).isoformat())
    with patch("app.services.automation_guards.ai_replies_allowed_for_lead", return_value=False):
        told, text, tpl, bells = _run(db)
    assert told == 1 and text.await_count == 0 and tpl.await_count == 0
    assert db.rows("batch_waitlist")[0]["told_via"] == "staff" and bells == ["Seat free in Weekend: call Wait1"]


def test_nothing_is_told_when_full_closed_marked_full_or_out_of_hours():
    db = _full_world()
    _waiting(db, 1)
    assert _run(db)[0] == 0
    for status in ("closed", "full"):
        db = world(seats=4, status=status)
        _waiting(db, 1)
        assert _run(db)[0] == 0
    db = world(seats=4)
    _waiting(db, 1)
    with patch.object(svc, "_tell_one", AsyncMock(return_value="text")):
        assert asyncio.run(svc.tell_waitlists(db, NOW.replace(hour=16))) == 0  # 9:30 PM IST


def test_job_waits_quietly_before_the_migration():
    class Broken(FakeSupabase):
        def table(self, name):
            raise RuntimeError("column told_at does not exist")
    assert asyncio.run(svc.tell_waitlists(Broken(), NOW)) == 0


def test_lead_line_mentions_the_held_seat():
    db = world(seats=2)
    _waiting(db, 1, told_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    assert "seat is free in Python - Weekend" in svc.lead_line(db, T, "W1")
    assert svc.lead_line(db, T, "W2") == ""
