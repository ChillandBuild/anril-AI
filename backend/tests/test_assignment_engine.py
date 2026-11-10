"""Per-channel telecaller assignment engine: round robin, availability, the rule gate in
assign_by_rule, the upload-pending memory, the sweep, and the backlog claim on login.

Runs against the in-memory FakeSupabase. Times are fixed: 22:00 UTC is 03:30 IST (outside
the 9-19 common shift), 12:30 UTC is 18:00 IST (inside it).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import assignment as asg  # noqa: E402
from app.services.assignment_rules import ROWS  # noqa: E402
from tests.fake_supabase import FakeSupabase  # noqa: E402

TENANT = "tenant-1"
OWNER_USER = "owner-user"
OUT_OF_SHIFT = datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc)  # 03:30 IST
IN_SHIFT = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)  # 18:00 IST


def full_rules(mode="auto", segments=("A", "B", "C"), **overrides):
    """All seven rows, same mode and segments everywhere (upload has no segments)."""
    rules = {}
    for row in ROWS:
        rule = {"enabled": True, "mode": mode}
        if row != "upload":
            rule["segments"] = list(segments)
        rules[row] = rule
    rules.update(overrides)
    return rules


def make_db(*, enabled=True, rules=None, shift_mode=None, callers=(), leads=(), owner=True):
    db = FakeSupabase()
    cfg = {"enabled": enabled, "channel_rules": rules if rules is not None else full_rules()}
    if shift_mode:
        cfg["shift_mode"] = shift_mode
    db.add("app_settings", tenant_id=TENANT, key="telecalling_config", value=json.dumps(cfg), is_secret=False)
    if owner:
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


def lead(lid, **kw):
    return {"id": lid, **kw}


def assigned_to(db, lead_id):
    row = next(r for r in db.rows("leads") if r["id"] == lead_id)
    return row.get("assigned_to")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """No real notifications; no real database unless a test installs one with use_db()."""
    monkeypatch.setattr("app.services.notify.notify_user", MagicMock())


def use_db(monkeypatch, db):
    monkeypatch.setattr(asg, "get_supabase", lambda: db)


def set_hour(monkeypatch, hour):
    monkeypatch.setattr(asg, "ist_hour", lambda now=None: hour)


# --- round robin ---------------------------------------------------------------------

def test_round_robin_takes_turns_in_creation_order():
    db = make_db(
        callers=[caller("c1"), caller("c2"), caller("c3")],
        leads=[lead(f"l{i}") for i in range(6)],
    )
    picked = [asg.assign_by_rule(f"l{i}", TENANT, reason="t", db=db) for i in range(6)]
    assert picked == ["c1", "c2", "c3", "c1", "c2", "c3"]


def test_pick_round_robin_continues_after_last_and_wraps():
    db = make_db(callers=[caller("c1"), caller("c2"), caller("c3")])
    pool = asg.eligible_callers(db, TENANT)
    assert asg.pick_round_robin(db, TENANT, pool)["id"] == "c1"
    assert asg.pick_round_robin(db, TENANT, pool)["id"] == "c2"
    assert asg.pick_round_robin(db, TENANT, pool)["id"] == "c3"
    assert asg.pick_round_robin(db, TENANT, pool)["id"] == "c1"


def test_round_robin_unknown_last_caller_starts_at_first():
    db = make_db(callers=[caller("c1"), caller("c2")])
    db.add("app_settings", tenant_id=TENANT, key=asg.RR_STATE_KEY,
           value=json.dumps({"last_caller_id": "deleted-caller"}), is_secret=False)
    pool = asg.eligible_callers(db, TENANT)
    assert asg.pick_round_robin(db, TENANT, pool)["id"] == "c1"


def test_round_robin_empty_pool_returns_none():
    db = make_db()
    assert asg.pick_round_robin(db, TENANT, []) is None


def test_round_robin_ignores_status_and_shift(monkeypatch):
    db = make_db(
        shift_mode="individual",
        callers=[
            caller("c1", status="logged_out", shift_start_hour=20, shift_end_hour=21),
            caller("c2", status="break", shift_start_hour=20, shift_end_hour=21),
        ],
        leads=[lead("l1"), lead("l2")],
    )
    use_db(monkeypatch, db)
    set_hour(monkeypatch, 3)  # nobody's shift covers 03:00
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) == "c1"
    assert asg.assign_by_rule("l2", TENANT, reason="t", db=db) == "c2"


def test_eligible_callers_excludes_owner_inactive_and_sorts_oldest_first():
    db = make_db(callers=[caller("c2"), caller("c1")])
    db.add("callers", tenant_id=TENANT, id="owner-caller", name="Owner", user_id=OWNER_USER, active=True)
    db.add("callers", tenant_id=TENANT, id="gone", name="Gone", user_id="u-gone", active=False)
    pool = asg.eligible_callers(db, TENANT)
    assert [c["id"] for c in pool] == ["c2", "c1"]  # creation order, owner and inactive left out


# --- available ----------------------------------------------------------------------

def test_available_picks_only_active_or_break_inside_shift():
    db = make_db(
        shift_mode="individual",
        callers=[
            caller("c1", status="logged_out"),                                  # never
            caller("c2", status="active", shift_start_hour=20, shift_end_hour=21),  # out of shift
            caller("c3", status="break"),                                        # in shift (common 9-19)
        ],
    )
    pool = asg.eligible_callers(db, TENANT)
    cfg = asg.get_telecalling_config(TENANT, db)
    picked = asg.pick_available(db, TENANT, pool, cfg, now=IN_SHIFT)
    assert picked["id"] == "c3"


def test_available_picks_fewest_open_leads():
    db = make_db(
        callers=[caller("c1"), caller("c2")],
        leads=[
            lead("busy-1", assigned_to="c1"),
            lead("busy-2", assigned_to="c1"),
            lead("free-now"),
        ],
    )
    pool = asg.eligible_callers(db, TENANT)
    cfg = asg.get_telecalling_config(TENANT, db)
    assert asg.pick_available(db, TENANT, pool, cfg, now=IN_SHIFT)["id"] == "c2"


def test_available_ties_go_to_the_earlier_caller():
    db = make_db(callers=[caller("c1"), caller("c2")])
    pool = asg.eligible_callers(db, TENANT)
    cfg = asg.get_telecalling_config(TENANT, db)
    assert asg.pick_available(db, TENANT, pool, cfg, now=IN_SHIFT)["id"] == "c1"


def test_available_returns_none_when_nobody_qualifies():
    db = make_db(callers=[caller("c1", status="logged_out"), caller("c2", status="active")])
    pool = asg.eligible_callers(db, TENANT)
    cfg = asg.get_telecalling_config(TENANT, db)
    assert asg.pick_available(db, TENANT, pool, cfg, now=OUT_OF_SHIFT) is None


def test_assign_by_rule_available_leaves_lead_waiting_when_nobody_on_shift(monkeypatch):
    rules = full_rules(whatsapp={"enabled": True, "mode": "available", "segments": ["A"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("l1")])
    use_db(monkeypatch, db)
    set_hour(monkeypatch, 3)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None
    assert assigned_to(db, "l1") is None


# --- assign_by_rule gate ------------------------------------------------------------

def test_assign_by_rule_assigns_when_everything_allows(monkeypatch):
    db = make_db(callers=[caller("c1")], leads=[lead("l1", source="instagram", segment="B")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) == "c1"
    assert assigned_to(db, "l1") == "c1"


def test_master_switch_off_assigns_nothing(monkeypatch):
    db = make_db(enabled=False, callers=[caller("c1")], leads=[lead("l1")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None
    assert assigned_to(db, "l1") is None


def test_disabled_row_assigns_nothing(monkeypatch):
    rules = full_rules(instagram={"enabled": False, "mode": "auto", "segments": ["A", "B", "C"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("l1", source="instagram")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None


def test_pull_mode_row_assigns_nothing(monkeypatch):
    rules = full_rules(whatsapp={"enabled": True, "mode": "pull", "segments": ["A", "B", "C"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("l1")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None
    assert assigned_to(db, "l1") is None


def test_segment_not_allowed_by_row_assigns_nothing(monkeypatch):
    rules = full_rules(whatsapp={"enabled": True, "mode": "auto", "segments": ["A"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("l1", segment="C")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None


def test_explicit_segment_argument_overrides_lead_segment(monkeypatch):
    rules = full_rules(whatsapp={"enabled": True, "mode": "auto", "segments": ["A"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("l1", segment="C")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", segment="A", db=db) == "c1"


def test_unknown_source_is_never_auto_assigned(monkeypatch):
    db = make_db(callers=[caller("c1")], leads=[lead("l1", source="carrier-pigeon")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None


def test_null_source_counts_as_whatsapp(monkeypatch):
    db = make_db(callers=[caller("c1")], leads=[lead("l1", source=None)])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) == "c1"


@pytest.mark.parametrize("closed", [
    {"do_not_call": True},
    {"call_status": "converted"},
    {"call_status": "dnc"},
    {"call_status": "unreachable"},
    {"call_status": "wrong_number"},
    {"call_status": "disqualified"},
    {"converted_at": "2026-01-01T00:00:00+00:00"},
    {"deleted_at": "2026-01-01T00:00:00+00:00"},
])
def test_closed_lead_is_not_assigned(monkeypatch, closed):
    db = make_db(callers=[caller("c1")], leads=[lead("l1", **closed)])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None
    assert assigned_to(db, "l1") is None


def test_already_assigned_lead_is_left_alone(monkeypatch):
    db = make_db(callers=[caller("c1"), caller("c2")], leads=[lead("l1", assigned_to="c2")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None
    assert assigned_to(db, "l1") == "c2"


def test_missing_lead_returns_none(monkeypatch):
    db = make_db(callers=[caller("c1")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("nope", TENANT, reason="t", db=db) is None


def test_no_callers_returns_none(monkeypatch):
    db = make_db(callers=[], leads=[lead("l1")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("l1", TENANT, reason="t", db=db) is None


def test_row_override_upload_ignores_segments(monkeypatch):
    # Upload leads have source "upload", which maps to the whatsapp row (segments A only).
    rules = full_rules(whatsapp={"enabled": True, "mode": "auto", "segments": ["A"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("u1", source="upload", segment="C")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("u1", TENANT, reason="t", row_override="upload", db=db) == "c1"


def test_upload_lead_without_override_follows_whatsapp_row(monkeypatch):
    rules = full_rules(whatsapp={"enabled": True, "mode": "auto", "segments": ["A"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("u1", source="upload", segment="C")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("u1", TENANT, reason="t", db=db) is None


def test_row_override_upload_respects_upload_row_off(monkeypatch):
    rules = full_rules(upload={"enabled": False, "mode": "auto"})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("u1", source="upload")])
    use_db(monkeypatch, db)
    assert asg.assign_by_rule("u1", TENANT, reason="t", row_override="upload", db=db) is None


def test_maybe_assign_lead_routes_by_source_not_channel(monkeypatch):
    rules = full_rules(whatsapp={"enabled": False, "mode": "auto", "segments": ["A"]})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("l1", source="instagram", segment="A")])
    use_db(monkeypatch, db)
    # The channel argument says whatsapp, but the lead's origin is instagram.
    assert asg.maybe_assign_lead("l1", TENANT, "A", "whatsapp", reason="created") == "c1"


def test_maybe_assign_lead_with_no_channel(monkeypatch):
    db = make_db(callers=[caller("c1")], leads=[lead("l1", source="facebook", segment="A")])
    use_db(monkeypatch, db)
    assert asg.maybe_assign_lead("l1", TENANT, "A", None) == "c1"


# --- upload pending memory ----------------------------------------------------------

def test_upload_pending_add_dedupes_and_remove_drops():
    db = make_db()
    asg.add_upload_pending(db, TENANT, ["a", "b"])
    asg.add_upload_pending(db, TENANT, ["b", "c"])
    assert asg.get_upload_pending(db, TENANT) == ["a", "b", "c"]
    asg.remove_upload_pending(db, TENANT, ["b"])
    assert asg.get_upload_pending(db, TENANT) == ["a", "c"]


def test_upload_pending_keeps_newest_cap(monkeypatch):
    monkeypatch.setattr(asg, "UPLOAD_PENDING_CAP", 3)
    db = make_db()
    asg.add_upload_pending(db, TENANT, ["a", "b", "c", "d", "e"])
    assert asg.get_upload_pending(db, TENANT) == ["c", "d", "e"]


def test_upload_pending_ignores_a_corrupt_value():
    db = make_db()
    db.add("app_settings", tenant_id=TENANT, key=asg.UPLOAD_PENDING_KEY, value="{not json", is_secret=False)
    assert asg.get_upload_pending(db, TENANT) == []


# --- sweep --------------------------------------------------------------------------

def test_sweep_assigns_auto_rows_and_skips_pull_rows(monkeypatch):
    rules = full_rules(meta_form={"enabled": True, "mode": "pull", "segments": ["A", "B", "C"]})
    db = make_db(
        rules=rules,
        callers=[caller("c1")],
        leads=[lead("auto-1", source="whatsapp"), lead("pull-1", source="meta_form")],
    )
    use_db(monkeypatch, db)
    assert asg.sweep_tenant(TENANT, db=db) == 1
    assert assigned_to(db, "auto-1") == "c1"
    assert assigned_to(db, "pull-1") is None


def test_sweep_does_nothing_when_master_off(monkeypatch):
    db = make_db(enabled=False, callers=[caller("c1")], leads=[lead("l1")])
    use_db(monkeypatch, db)
    assert asg.sweep_tenant(TENANT, db=db) == 0
    assert assigned_to(db, "l1") is None


def test_sweep_stops_an_available_row_when_nobody_is_on_shift_but_keeps_auto(monkeypatch):
    rules = full_rules(instagram={"enabled": True, "mode": "available", "segments": ["A", "B", "C"]})
    db = make_db(
        rules=rules,
        callers=[caller("c1")],
        leads=[
            lead("ig-1", source="instagram"),
            lead("ig-2", source="instagram"),
            lead("wa-1", source="whatsapp"),
        ],
    )
    use_db(monkeypatch, db)
    set_hour(monkeypatch, 3)
    assert asg.sweep_tenant(TENANT, db=db) == 1
    assert assigned_to(db, "ig-1") is None
    assert assigned_to(db, "ig-2") is None
    assert assigned_to(db, "wa-1") == "c1"


def test_sweep_assigns_pending_upload_leads_and_clears_them(monkeypatch):
    # whatsapp row off, so the upload lead can only be placed by the upload path.
    rules = full_rules(
        whatsapp={"enabled": False, "mode": "auto", "segments": ["A"]},
        upload={"enabled": True, "mode": "auto"},
    )
    db = make_db(
        rules=rules,
        callers=[caller("c1")],
        leads=[lead("u1", source="upload", segment="C")],
    )
    use_db(monkeypatch, db)
    asg.add_upload_pending(db, TENANT, ["u1"])
    assert asg.sweep_tenant(TENANT, db=db) == 1
    assert assigned_to(db, "u1") == "c1"
    assert asg.get_upload_pending(db, TENANT) == []


def test_sweep_drops_pending_upload_leads_that_are_closed_or_gone(monkeypatch):
    rules = full_rules(upload={"enabled": True, "mode": "auto"})
    db = make_db(
        rules=rules,
        callers=[caller("c1")],
        leads=[lead("u-closed", source="upload", call_status="converted"), lead("u-taken", source="upload", assigned_to="c1")],
    )
    use_db(monkeypatch, db)
    asg.add_upload_pending(db, TENANT, ["u-closed", "u-taken", "u-missing"])
    assert asg.sweep_tenant(TENANT, db=db) == 0
    assert asg.get_upload_pending(db, TENANT) == []


def test_sweep_keeps_pending_upload_leads_while_upload_row_is_pull(monkeypatch):
    rules = full_rules(
        whatsapp={"enabled": False, "mode": "auto", "segments": ["A"]},
        upload={"enabled": True, "mode": "pull"},
    )
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("u1", source="upload")])
    use_db(monkeypatch, db)
    asg.add_upload_pending(db, TENANT, ["u1"])
    asg.sweep_tenant(TENANT, db=db)
    assert assigned_to(db, "u1") is None
    assert asg.get_upload_pending(db, TENANT) == ["u1"]


# --- backlog claim on login ---------------------------------------------------------

def test_reassign_backlog_gives_flagged_leads_and_sweeps_the_rest(monkeypatch):
    db = make_db(
        callers=[caller("c1"), caller("c2")],
        leads=[lead("flagged", needs_human_attention=True), lead("plain")],
    )
    use_db(monkeypatch, db)
    asg.reassign_backlog("c2", TENANT)
    assert assigned_to(db, "flagged") == "c2"
    assert assigned_to(db, "plain") == "c1"  # the sweep runs round robin from the pool
    events = [e for e in db.rows("lead_stage_events") if e["metadata"]["reason"] == "backlog_claim"]
    assert [e["lead_id"] for e in events] == ["flagged"]


def test_reassign_backlog_noop_when_master_off(monkeypatch):
    db = make_db(enabled=False, callers=[caller("c1")], leads=[lead("flagged", needs_human_attention=True)])
    use_db(monkeypatch, db)
    asg.reassign_backlog("c1", TENANT)
    assert assigned_to(db, "flagged") is None


def test_sweep_reaches_a_new_hot_lead_behind_many_old_cold_ones(monkeypatch):
    # Regression: the sweep used to read the oldest N unassigned leads of ANY segment and filter
    # in Python, so a pile of old Cold broadcast imports hid every newer Hot lead forever.
    rules = full_rules(segments=("A",))
    old_cold = [
        lead(f"cold-{i}", source="upload", segment="C", created_at=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z")
        for i in range(30)
    ]
    hot = lead("hot-1", source="whatsapp", segment="A", created_at="2026-06-01T00:00:00Z")
    db = make_db(rules=rules, callers=[caller("c1")], leads=[*old_cold, hot])
    use_db(monkeypatch, db)
    assert asg.sweep_tenant(TENANT, db=db, limit=10) == 1
    assert assigned_to(db, "hot-1") == "c1"
    assert all(assigned_to(db, f"cold-{i}") is None for i in range(30))


# --- telecalling upload batch --------------------------------------------------------

def _cfg_of(db):
    row = next(r for r in db.rows("app_settings") if r["key"] == "telecalling_config")
    return json.loads(row["value"])


def test_upload_batch_takes_turns_continuing_the_round_robin_and_sends_one_summary_each(monkeypatch):
    notify = MagicMock()
    monkeypatch.setattr("app.services.notify.notify_user", notify)
    db = make_db(
        callers=[caller("c1", created_at="1"), caller("c2", created_at="2"), caller("c3", created_at="3")],
        leads=[lead(f"u{i}", source="upload", segment="C") for i in range(5)],
    )
    db.add("app_settings", tenant_id=TENANT, key=asg.RR_STATE_KEY, value=json.dumps({"last_caller_id": "c1"}), is_secret=False)
    assignments, unplaced = asg.assign_upload_batch(db, TENANT, [f"u{i}" for i in range(5)], _cfg_of(db))
    assert unplaced == []
    assert [a["caller_id"] for a in assignments] == ["c2", "c3", "c1", "c2", "c3"]
    rr = next(r for r in db.rows("app_settings") if r["key"] == asg.RR_STATE_KEY)
    assert json.loads(rr["value"]) == {"last_caller_id": "c3"}
    # One summary per telecaller, never one per lead.
    assert notify.call_count == 3
    assert {c.args[1] for c in notify.call_args_list} == {"user-c1", "user-c2", "user-c3"}


def test_upload_batch_available_mode_with_nobody_on_shift_places_nothing(monkeypatch):
    rules = full_rules(upload={"enabled": True, "mode": "available"})
    db = make_db(rules=rules, callers=[caller("c1")], leads=[lead("u1", source="upload")])
    set_hour(monkeypatch, 3)
    assignments, unplaced = asg.assign_upload_batch(db, TENANT, ["u1"], _cfg_of(db))
    assert assignments == []
    assert unplaced == ["u1"]
    assert assigned_to(db, "u1") is None


def test_upload_batch_available_mode_spreads_by_open_leads(monkeypatch):
    rules = full_rules(upload={"enabled": True, "mode": "available"})
    db = make_db(
        rules=rules,
        callers=[caller("c1", created_at="1"), caller("c2", created_at="2")],
        leads=[lead("busy", assigned_to="c1"), *[lead(f"u{i}", source="upload") for i in range(3)]],
    )
    set_hour(monkeypatch, 12)
    assignments, _ = asg.assign_upload_batch(db, TENANT, ["u0", "u1", "u2"], _cfg_of(db))
    # c1 already holds one open lead, so c2 goes first and they end up level.
    assert [a["caller_id"] for a in assignments] == ["c2", "c1", "c2"]
