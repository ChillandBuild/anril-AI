"""Waiting-leads offer: when leads wait in an 'available' row and nobody is on shift, online
telecallers outside shift are invited; the first yes starts a 2-minute window; the waiting
leads are then split oldest-first among the accepters. Times are fixed so no test depends on
the wall clock: T0 is 22:00 UTC (03:30 IST, outside the 9-19 common shift).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import assignment_offers as offers  # noqa: E402
from app.services.assignment_rules import ROWS  # noqa: E402
from tests.fake_supabase import FakeSupabase  # noqa: E402

TENANT = "tenant-1"
OWNER_USER = "owner-user"
T0 = datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc)
WHATSAPP_AVAILABLE = {"enabled": True, "mode": "available", "segments": ["A", "B", "C"]}


def full_rules(**overrides):
    rules = {}
    for row in ROWS:
        rule = {"enabled": True, "mode": "auto"}
        if row != "upload":
            rule["segments"] = ["A", "B", "C"]
        rules[row] = rule
    rules["whatsapp"] = dict(WHATSAPP_AVAILABLE)
    rules.update(overrides)
    return rules


def make_db(*, rules=None, callers=(), leads=(), shift_mode=None):
    db = FakeSupabase()
    cfg = {"enabled": True, "channel_rules": rules if rules is not None else full_rules()}
    if shift_mode:
        cfg["shift_mode"] = shift_mode
    db.add("app_settings", tenant_id=TENANT, key="telecalling_config", value=json.dumps(cfg), is_secret=False)
    db.add("tenant_users", tenant_id=TENANT, user_id=OWNER_USER, role="owner")
    for c in callers:
        db.add("callers", **{
            "tenant_id": TENANT, "active": True, "status": "active", "user_id": None,
            "shift_start_hour": None, "shift_end_hour": None, **c,
        })
    for lead in leads:
        db.add("leads", **{
            "tenant_id": TENANT, "source": "whatsapp", "segment": "A", "assigned_to": None,
            "do_not_call": False, "call_status": "new", "converted_at": None, "deleted_at": None,
            **lead,
        })
    return db


def caller(cid, **kw):
    return {"id": cid, "name": cid.upper(), "user_id": f"user-{cid}", **kw}


def four_waiting_leads():
    return [{"id": f"w{i}"} for i in range(1, 5)]


def offer_state(db):
    return offers._load_state(db, TENANT)


def assigned_to(db, lead_id):
    return next(r for r in db.rows("leads") if r["id"] == lead_id).get("assigned_to")


@pytest.fixture
def notify(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("app.services.notify.notify_user", mock)
    return mock


@pytest.fixture
def two_out_of_shift(notify):
    """c1 and c2 are online but outside shift; four whatsapp leads are waiting."""
    return make_db(
        callers=[caller("c1", status="active", user_id="u1"), caller("c2", status="break", user_id="u2")],
        leads=four_waiting_leads(),
    )


# --- when an offer opens ------------------------------------------------------------

def test_offer_opens_for_online_out_of_shift_callers(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)

    state = offer_state(db)
    assert state["status"] == "open"
    assert state["invited"] == ["c1", "c2"]
    assert state["last_prompt_count"] == 4
    assert notify.call_count == 2
    for call in notify.call_args_list:
        assert call.args[2] == "leads_waiting"
        assert call.args[3] == "Leads are waiting"
        assert call.args[4] == "4 leads are waiting for a telecaller. Do you want to take them?"
        assert call.kwargs["push_url"] == "/dashboard/telecalling"


def test_no_offer_when_someone_is_on_shift(notify):
    db = make_db(
        shift_mode="individual",
        callers=[
            caller("c1", user_id="u1", shift_start_hour=9, shift_end_hour=19),   # out of shift at 03:30
            caller("c2", user_id="u2", shift_start_hour=0, shift_end_hour=24),   # on shift
        ],
        leads=four_waiting_leads(),
    )
    offers.process_tenant(TENANT, db=db, now=T0)
    assert offer_state(db) is None
    assert notify.call_count == 0


def test_no_offer_when_nobody_is_online_out_of_shift(notify):
    db = make_db(
        callers=[caller("c1", status="logged_out", user_id="u1")],
        leads=four_waiting_leads(),
    )
    offers.process_tenant(TENANT, db=db, now=T0)
    assert offer_state(db) is None


def test_no_offer_when_no_leads_wait(notify, two_out_of_shift):
    db = two_out_of_shift
    for row in db.rows("leads"):
        row["assigned_to"] = "c1"
    offers.process_tenant(TENANT, db=db, now=T0)
    assert offer_state(db) is None


def test_no_offer_when_master_switch_is_off(notify, two_out_of_shift):
    db = two_out_of_shift
    cfg = json.loads(db.rows("app_settings")[0]["value"])
    cfg["enabled"] = False
    db.rows("app_settings")[0]["value"] = json.dumps(cfg)
    offers.process_tenant(TENANT, db=db, now=T0)
    assert offer_state(db) is None


# --- cooldown and re-prompting ------------------------------------------------------

def _open_and_decline(db, notify):
    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]
    offers.respond(TENANT, "c1", offer_id, False, db=db, now=T0 + timedelta(seconds=5))
    offers.respond(TENANT, "c2", offer_id, False, db=db, now=T0 + timedelta(seconds=10))
    assert offer_state(db)["status"] == "closed"
    return offer_id


def test_everyone_declining_closes_the_offer(two_out_of_shift, notify):
    db = two_out_of_shift
    _open_and_decline(db, notify)
    assert all(assigned_to(db, f"w{i}") is None for i in range(1, 5))


def test_cooldown_blocks_a_repeat_prompt_for_the_same_waiting_count(two_out_of_shift, notify):
    db = two_out_of_shift
    first_id = _open_and_decline(db, notify)
    notify.reset_mock()

    offers.process_tenant(TENANT, db=db, now=T0 + timedelta(minutes=5))
    assert offer_state(db)["status"] == "closed"
    assert offer_state(db)["id"] == first_id
    assert notify.call_count == 0


def test_reprompt_after_cooldown_expires(two_out_of_shift, notify):
    db = two_out_of_shift
    _open_and_decline(db, notify)
    notify.reset_mock()

    offers.process_tenant(TENANT, db=db, now=T0 + timedelta(minutes=31))
    assert offer_state(db)["status"] == "open"
    assert notify.call_count == 2


def test_more_waiting_leads_prompts_again_inside_cooldown(two_out_of_shift, notify):
    db = two_out_of_shift
    _open_and_decline(db, notify)
    notify.reset_mock()
    db.add("leads", tenant_id=TENANT, source="whatsapp", segment="A", assigned_to=None,
           do_not_call=False, call_status="new", converted_at=None, deleted_at=None)

    offers.process_tenant(TENANT, db=db, now=T0 + timedelta(minutes=5))
    assert offer_state(db)["status"] == "open"
    assert offer_state(db)["last_prompt_count"] == 5
    assert notify.call_count == 2


# --- answers: split, single accepter, immediate settle, expiry ----------------------

def test_two_accepters_split_the_waiting_leads_oldest_first(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]

    offers.respond(TENANT, "c1", offer_id, True, db=db, now=T0 + timedelta(seconds=10))
    assert offer_state(db)["status"] == "open"  # c2 has not answered yet

    offers.respond(TENANT, "c2", offer_id, True, db=db, now=T0 + timedelta(seconds=20))

    # Both answered, so it settled right away, well inside the 2-minute window.
    assert offer_state(db)["status"] == "closed"
    assert [assigned_to(db, f"w{i}") for i in range(1, 5)] == ["c1", "c2", "c1", "c2"]


def test_single_accepter_gets_everything_after_the_window(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]
    offers.respond(TENANT, "c1", offer_id, True, db=db, now=T0 + timedelta(seconds=10))

    offers.process_tenant(TENANT, db=db, now=T0 + timedelta(minutes=1, seconds=59))
    assert offer_state(db)["status"] == "open"
    assert all(assigned_to(db, f"w{i}") is None for i in range(1, 5))

    offers.process_tenant(TENANT, db=db, now=T0 + timedelta(minutes=2, seconds=10))
    assert offer_state(db)["status"] == "closed"
    assert [assigned_to(db, f"w{i}") for i in range(1, 5)] == ["c1", "c1", "c1", "c1"]
    assert assigned_to(db, "w1") == "c1"


def test_offer_settles_immediately_when_everyone_answered_yes(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]
    offers.respond(TENANT, "c1", offer_id, True, db=db, now=T0 + timedelta(seconds=1))
    offers.respond(TENANT, "c2", offer_id, True, db=db, now=T0 + timedelta(seconds=2))
    assert offer_state(db)["status"] == "closed"
    assert sum(1 for i in range(1, 5) if assigned_to(db, f"w{i}")) == 4


def test_mixed_answers_settle_for_the_one_who_said_yes(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]
    offers.respond(TENANT, "c1", offer_id, False, db=db, now=T0 + timedelta(seconds=1))
    offers.respond(TENANT, "c2", offer_id, True, db=db, now=T0 + timedelta(seconds=2))
    assert offer_state(db)["status"] == "closed"
    assert [assigned_to(db, f"w{i}") for i in range(1, 5)] == ["c2"] * 4


def test_offer_nobody_answers_expires_after_30_minutes(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)

    offers.process_tenant(TENANT, db=db, now=T0 + timedelta(minutes=29, seconds=59))
    assert offer_state(db)["status"] == "open"

    offers.process_tenant(TENANT, db=db, now=T0 + timedelta(minutes=30))
    assert offer_state(db)["status"] == "closed"
    assert all(assigned_to(db, f"w{i}") is None for i in range(1, 5))


def test_respond_refuses_a_closed_offer_or_an_uninvited_caller(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]

    with pytest.raises(LookupError):
        offers.respond(TENANT, "stranger", offer_id, True, db=db, now=T0)
    with pytest.raises(LookupError):
        offers.respond(TENANT, "c1", "some-other-offer", True, db=db, now=T0)

    offers.respond(TENANT, "c1", offer_id, False, db=db, now=T0)
    offers.respond(TENANT, "c2", offer_id, False, db=db, now=T0)
    with pytest.raises(LookupError):
        offers.respond(TENANT, "c1", offer_id, True, db=db, now=T0)


# --- what a telecaller sees ---------------------------------------------------------

def test_get_offer_for_caller_states(two_out_of_shift, notify):
    db = two_out_of_shift
    assert offers.get_offer_for_caller(TENANT, "c1", db=db, now=T0) == {"state": "none"}

    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]
    assert offers.get_offer_for_caller(TENANT, "c1", db=db, now=T0) == {
        "state": "invited", "offer_id": offer_id, "lead_count": 4,
    }
    assert offers.get_offer_for_caller(TENANT, "stranger", db=db, now=T0) == {"state": "none"}

    offers.respond(TENANT, "c1", offer_id, True, db=db, now=T0 + timedelta(seconds=30))
    # The 2-minute window started at the first yes (30s); at 60s, 90 seconds are left.
    accepted = offers.get_offer_for_caller(TENANT, "c1", db=db, now=T0 + timedelta(seconds=60))
    assert accepted == {"state": "accepted", "offer_id": offer_id, "lead_count": 4, "seconds_left": 90}

    # c2 declines after everyone has answered, so the offer settles at once for c1.
    offers.respond(TENANT, "c2", offer_id, False, db=db, now=T0 + timedelta(seconds=40))
    assert offer_state(db)["status"] == "closed"
    assert offers.get_offer_for_caller(TENANT, "c1", db=db, now=T0 + timedelta(seconds=40)) == {"state": "none"}


def test_declined_caller_sees_none_while_offer_is_still_open(two_out_of_shift, notify):
    db = two_out_of_shift
    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]
    offers.respond(TENANT, "c1", offer_id, False, db=db, now=T0 + timedelta(seconds=5))
    assert offers.get_offer_for_caller(TENANT, "c1", db=db, now=T0 + timedelta(seconds=6)) == {"state": "none"}
    assert offers.get_offer_for_caller(TENANT, "c2", db=db, now=T0 + timedelta(seconds=6))["state"] == "invited"


# --- upload leads waiting in the offer ----------------------------------------------

def test_pending_upload_leads_join_the_offer_and_are_removed_on_settle(notify):
    # whatsapp row paused so the upload lead is only waiting through the upload path.
    rules = full_rules(
        whatsapp={"enabled": False, "mode": "auto", "segments": ["A"]},
        upload={"enabled": True, "mode": "available"},
    )
    db = make_db(
        rules=rules,
        callers=[caller("c1", user_id="u1")],
        leads=[{"id": "up1", "source": "upload", "segment": "C"}],
    )
    from app.services import assignment as asg
    asg.add_upload_pending(db, TENANT, ["up1"])

    waiting = offers.waiting_leads(db, TENANT, offers.get_telecalling_config(TENANT, db))
    assert [w["id"] for w in waiting] == ["up1"]
    assert waiting[0].get("_upload") is True

    offers.process_tenant(TENANT, db=db, now=T0)
    offer_id = offer_state(db)["id"]
    offers.respond(TENANT, "c1", offer_id, True, db=db, now=T0 + timedelta(seconds=5))
    assert assigned_to(db, "up1") == "c1"
    assert asg.get_upload_pending(db, TENANT) == []
