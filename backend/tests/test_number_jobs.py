"""Picking a number for staff alerts, OTP codes and Reach (WhatsApp > Numbers > Which number does what)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.services import number_jobs
from tests.fake_supabase import FakeSupabase

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=30)).isoformat()


def _num(id_, tenant=T1, role="standby", **over):
    return {"id": id_, "tenant_id": tenant, "role": role, "status": "active", "meta_status": "CONNECTED",
            "meta_phone_number_id": f"pid-{id_}", "quality_rating": "green", "paused_outbound": False,
            "messaging_tier": 1000, "warm_up_started_at": OLD, "created_at": OLD, **over}


def _db(*rows):
    db = FakeSupabase()
    for r in rows:
        db.add("phone_numbers", **r)
    return db


def _picks(monkeypatch, **picks):
    monkeypatch.setattr(number_jobs, "get_setting",
                        lambda key, tenant_id=None, **k: picks.get(key.removeprefix("sender_for_")) if tenant_id == T1 else None)


# ── alerts / OTP ─────────────────────────────────────────────────────────────

def test_otp_and_alerts_go_from_the_picked_number(monkeypatch):
    _picks(monkeypatch, otp="n2", alerts="n3")
    db = _db(_num("n1", role="primary"), _num("n2"), _num("n3"))
    assert number_jobs.sender_for(db, T1, "otp") == "pid-n2"
    assert number_jobs.sender_for(db, T1, "alerts") == "pid-n3"


def test_nothing_picked_means_main(monkeypatch):
    _picks(monkeypatch)
    assert number_jobs.sender_for(_db(_num("n1", role="primary")), T1, "otp") is None  # None = default sender


def test_a_disconnected_or_removed_pick_falls_back_to_main(monkeypatch):
    _picks(monkeypatch, otp="n2", alerts="n3")
    db = _db(_num("n2", meta_status="PENDING"), _num("n3", status="archived"))
    assert number_jobs.sender_for(db, T1, "otp") is None
    assert number_jobs.sender_for(db, T1, "alerts") is None


def test_never_another_business_number(monkeypatch):
    _picks(monkeypatch, otp="n9")
    assert number_jobs.sender_for(_db(_num("n9", tenant=T2)), T1, "otp") is None


# ── Reach ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("over, why", [
    ({"quality_rating": "red"}, "Rated red by Meta"),
    ({"paused_outbound": True}, "Paused"),
    ({"meta_status": "PENDING"}, "Not connected to Meta"),
    ({"messaging_tier": None}, "No daily limit from Meta yet"),
])
def test_numbers_that_cannot_broadcast_are_greyed_out_with_a_reason(over, why):
    row = _num("n2", **over)
    assert number_jobs.reach_block_reason(row, NOW, {"n2"}, 0) == why


def test_used_up_and_locked_numbers_are_greyed_out_too():
    assert number_jobs.reach_block_reason(_num("n2"), NOW, {"n2"}, 1000) == "Today's cap used"
    assert number_jobs.reach_block_reason(_num("n2"), NOW, set(), 0) == "Locked by your plan"
    assert number_jobs.reach_block_reason(_num("n2"), NOW, {"n2"}, 10) is None


def test_reach_sticks_to_the_picked_number_and_drops_it_when_it_turns_red(monkeypatch):
    _picks(monkeypatch, reach="n2")
    rows = [_num("n1", role="primary"), _num("n2")]
    assert number_jobs.reach_pin(None, T1, rows, NOW, {"n1", "n2"})["id"] == "n2"
    rows[1]["quality_rating"] = "red"
    assert number_jobs.reach_pin(None, T1, rows, NOW, {"n1", "n2"}) is None  # back to Automatic


def test_picker_only_uses_the_picked_number_for_reach_and_waits_when_its_cap_is_used(monkeypatch):
    from app.services import outbound_router

    _picks(monkeypatch, reach="n2")
    db = _db(_num("n1", role="primary"), _num("n2", messaging_tier=1000))
    monkeypatch.setattr(outbound_router, "get_supabase", lambda: db)
    monkeypatch.setattr(outbound_router, "get_unlocked_number_ids", lambda *_: {"n1", "n2"})
    usage = outbound_router.Usage()
    monkeypatch.setattr(outbound_router, "load_usage", lambda *_: usage)

    assert outbound_router.SenderPicker(T1, job="reach").next()["id"] == "n2"
    assert outbound_router.SenderPicker(T1).next()["id"] == "n1"  # other senders: Main first as before

    usage.per_number["n2"] = 1000  # the picked number's cap is used: the rest waits, Main is not used
    usage.total = 100
    assert outbound_router.SenderPicker(T1, job="reach").next() is None


# ── route ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_picking_a_red_number_for_reach_is_refused(monkeypatch):
    from app.routes import numbers

    db = _db(_num("n2", quality_rating="red"))
    monkeypatch.setattr(numbers, "get_supabase", lambda: db)
    monkeypatch.setattr(numbers, "get_unlocked_number_ids", lambda *_: {"n2"})
    monkeypatch.setattr(numbers, "_usage_or_empty", lambda *_: numbers.Usage())
    with pytest.raises(HTTPException) as e:
        await numbers.set_sender(numbers.SenderPick(job="reach", number_id="n2"), tenant_id=T1, _ctx={})
    assert e.value.status_code == 400 and "Rated red by Meta" in e.value.detail
    assert db.rows("app_settings") == []


@pytest.mark.asyncio
async def test_picking_and_clearing_a_number_saves_this_business_setting(monkeypatch):
    from app.routes import numbers

    db = _db(_num("n2"), _num("n9", tenant=T2))
    monkeypatch.setattr(numbers, "get_supabase", lambda: db)
    await numbers.set_sender(numbers.SenderPick(job="otp", number_id="n2"), tenant_id=T1, _ctx={})
    assert [(r["tenant_id"], r["key"], r["value"]) for r in db.rows("app_settings")] == [(T1, "sender_for_otp", "n2")]
    with pytest.raises(HTTPException) as e:
        await numbers.set_sender(numbers.SenderPick(job="otp", number_id="n9"), tenant_id=T1, _ctx={})
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        await numbers.set_sender(numbers.SenderPick(job="bills", number_id="n2"), tenant_id=T1, _ctx={})
    await numbers.set_sender(numbers.SenderPick(job="otp", number_id=None), tenant_id=T1, _ctx={})
    assert db.rows("app_settings") == []


def test_extra_is_no_longer_a_role():
    from app.routes import numbers

    assert numbers._PICKABLE_ROLES == frozenset({"primary", "standby"})
