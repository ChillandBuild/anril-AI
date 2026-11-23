"""Call IQ > Live, Evaluation, Results. Read-only; the DB is the in-memory fake."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import call_iq_reports as svc
from fake_supabase import FakeSupabase

T1, T2 = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
NOW = datetime(2026, 11, 22, 7, 0, tzinfo=timezone.utc)  # 12:30 PM in India, 22 Nov
TODAY = "2026-11-22T05:00:00+00:00"  # 10:30 AM IST today
YESTERDAY = "2026-11-21T05:00:00+00:00"
LONG_AGO = "2026-09-01T05:00:00+00:00"


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.clear()


def caller(db, tenant, name, **fields):
    row = db.add("callers", tenant_id=tenant, name=name, active=True, **fields)
    return row["id"]


def ctx(tenant=T1, role="caller", perms=(), caller_id=None):
    return {"tenant_id": tenant, "role": role, "user_id": "u", "caller_id": caller_id, "permissions": list(perms)}


def checks(**levels):
    """An evaluation with the given check -> (level, full) pairs."""
    return {"evaluation_version": 4, "checks": [{"key": k, "level": lvl, "full": full} for k, (lvl, full) in levels.items()]}


def scored_call(db, tenant, caller_id, score, at=TODAY, **extra):
    return db.add("call_logs", tenant_id=tenant, caller_id=caller_id, status="completed", score=score,
                  score_status="scored", created_at=at, **extra)


# ── Live ─────────────────────────────────────────────────────────────────────


def test_person_state_order_on_call_beats_break_and_active():
    assert svc.person_state({"status": "break", "status_changed_at": "x"}, "2026-11-22T06:00:00Z") == ("on_call", "2026-11-22T06:00:00Z")
    assert svc.person_state({"status": "break", "status_changed_at": "b"}, None) == ("on_break", "b")
    assert svc.person_state({"status": "active", "status_changed_at": "a"}, None) == ("idle", "a")
    assert svc.person_state({"status": "logged_out", "status_changed_at": "o"}, None) == ("off", "o")
    assert svc.person_state({}, None) == ("off", None)


def test_break_minutes_closed_and_open_breaks_only_breaks_count():
    rows = [
        {"caller_id": "a", "status": "break", "started_at": "2026-11-22T05:00:00+00:00", "ended_at": "2026-11-22T05:15:00+00:00"},
        {"caller_id": "a", "status": "break", "started_at": "2026-11-22T06:30:00+00:00", "ended_at": None},  # open: 30 min to NOW
        {"caller_id": "a", "status": "active", "started_at": "2026-11-22T04:00:00+00:00", "ended_at": None},
        {"caller_id": "b", "status": "break", "started_at": "bad", "ended_at": None},
    ]
    assert svc.break_minutes(rows, NOW) == {"a": 45}


def test_live_states_counts_and_breaks():
    db = FakeSupabase()
    a = caller(db, T1, "Anitha", status="active", status_changed_at="2026-11-22T04:00:00+00:00")
    b = caller(db, T1, "Bala", status="break", status_changed_at="2026-11-22T06:30:00+00:00")
    c = caller(db, T1, "Chitra", status="logged_out", status_changed_at="2026-11-21T12:00:00+00:00")
    d = caller(db, T1, "Dev", status="active", status_changed_at="2026-11-22T04:00:00+00:00")
    db.add("call_logs", tenant_id=T1, caller_id=a, status="completed", created_at=TODAY)
    db.add("call_logs", tenant_id=T1, caller_id=a, status="in_progress", created_at="2026-11-22T06:55:00+00:00")
    db.add("call_logs", tenant_id=T1, caller_id=d, status="completed", created_at=YESTERDAY)
    db.add("caller_status_logs", tenant_id=T1, caller_id=b, status="break", started_at="2026-11-22T06:30:00+00:00", ended_at=None)
    out = svc.live(db, ctx(role="owner"), NOW)
    people = {p["name"]: p for p in out["callers"]}
    assert [p["name"] for p in out["callers"]] == ["Anitha", "Bala", "Chitra", "Dev"]
    assert people["Anitha"]["state"] == "on_call" and people["Anitha"]["since"] == "2026-11-22T06:55:00+00:00"
    assert people["Anitha"]["calls_today"] == 2
    assert people["Bala"]["state"] == "on_break" and people["Bala"]["break_minutes_today"] == 30
    assert people["Chitra"]["state"] == "off"
    assert people["Dev"]["state"] == "idle" and people["Dev"]["calls_today"] == 0  # yesterday's call is not today's
    assert set(people["Anitha"]) == {"caller_id", "name", "state", "since", "calls_today", "break_minutes_today"}
    assert out["as_of"] == NOW.isoformat()
    assert c  # silence unused


def test_live_a_call_row_stuck_open_for_days_is_not_a_live_call():
    db = FakeSupabase()
    a = caller(db, T1, "Anitha", status="active")
    db.add("call_logs", tenant_id=T1, caller_id=a, status="initiated", created_at="2026-11-18T05:00:00+00:00")
    assert svc.live(db, ctx(role="owner"), NOW)["callers"][0]["state"] == "idle"


def test_live_leaves_out_the_owners_own_caller_record_and_inactive_people():
    db = FakeSupabase()
    db.add("tenant_users", tenant_id=T1, user_id="owner-user", role="owner")
    caller(db, T1, "Owner Self", user_id="owner-user", status="active")
    caller(db, T1, "Anitha", user_id="anitha-user", status="active")
    db.add("callers", tenant_id=T1, name="Left", active=False, status="active")
    out = svc.live(db, ctx(role="owner"), NOW)
    assert [p["name"] for p in out["callers"]] == ["Anitha"]


def test_live_tenant_isolation():
    db = FakeSupabase()
    other = caller(db, T2, "Other client", status="active")
    caller(db, T1, "Anitha", status="active")
    db.add("call_logs", tenant_id=T2, caller_id=other, status="in_progress", created_at="2026-11-22T06:55:00+00:00")
    out = svc.live(db, ctx(role="owner"), NOW)
    assert [p["name"] for p in out["callers"]] == ["Anitha"] and out["callers"][0]["state"] == "idle"


def test_live_a_telecaller_sees_only_themself():
    db = FakeSupabase()
    me = caller(db, T1, "Anitha", status="active")
    caller(db, T1, "Bala", status="active")
    out = svc.live(db, ctx(perms=["telecalling.view"], caller_id=me), NOW)
    assert [p["name"] for p in out["callers"]] == ["Anitha"]
    assert svc.live(db, ctx(perms=["telecalling.view"], caller_id=None), NOW)["callers"] == []


def test_live_a_team_leader_sees_only_their_team():
    db = FakeSupabase()
    team = str(uuid.uuid4())
    leader_caller = caller(db, T1, "Leader", status="active", team_id=team)
    member = caller(db, T1, "Member", status="active", team_id=team)
    caller(db, T1, "Outsider", status="active", team_id=str(uuid.uuid4()))
    role_id = str(uuid.uuid4())
    db.add("tenant_roles", id=role_id, tenant_id=T1, slug="team_leader")
    db.add("tenant_users", tenant_id=T1, user_id="u", role="member", role_id=role_id)
    db.add("call_team_leaders", tenant_id=T1, team_id=team, user_id="u")
    out = svc.live(db, ctx(perms=["team.view"], caller_id=leader_caller), NOW)
    assert sorted(p["name"] for p in out["callers"]) == ["Leader", "Member"]
    assert member


# ── Evaluation ───────────────────────────────────────────────────────────────


def test_weak_points_are_plain_weakest_first_and_skip_full_marks():
    out = svc.weak_points({"opening": 100.0, "decision": 40.0, "next_step": 55.4, "clarity": 90.0, "listening": 70.0})
    assert out == [
        "Asking for the decision: 40% of the marks on average",
        "Next step: 55% of the marks on average",
        "Listening: 70% of the marks on average",
    ]
    assert svc.weak_points({"opening": 100.0}) == [] and svc.weak_points({}) == []


def test_period_bounds_cover_ist_days_ending_tomorrow_midnight():
    start, end = svc.period_bounds("7d", svc.EVAL_DAYS, NOW)
    assert start == "2026-11-15T18:30:00+00:00" and end == "2026-11-22T18:30:00+00:00"
    start, end = svc.period_bounds("today", svc.RESULT_DAYS, NOW)
    assert start == "2026-11-21T18:30:00+00:00" and end == "2026-11-22T18:30:00+00:00"
    assert svc.period_bounds("yearly", svc.RESULT_DAYS, NOW) is None


def test_evaluation_scorecard_best_worst_weak_points_and_lowest_calls():
    db = FakeSupabase()
    a = caller(db, T1, "Anitha")
    b = caller(db, T1, "Bala")
    lead = db.add("leads", tenant_id=T1, name="Ravi")["id"]
    scored_call(db, T1, a, 80, evaluation=checks(opening=("excellent", 5), next_step=("missing", 10)))
    low = scored_call(db, T1, a, 40, lead_id=lead, evaluation=checks(opening=("excellent", 5), next_step=("missing", 10)))
    scored_call(db, T1, a, 95, at="2026-11-20T05:00:00+00:00")
    scored_call(db, T1, a, 10, at=LONG_AGO)  # outside 7 days
    db.add("call_logs", tenant_id=T1, caller_id=a, status="completed", score=None, score_status="processing", created_at=TODAY)
    db.add("call_logs", tenant_id=T1, caller_id=b, status="no_answer", score_status="not_connected", created_at=TODAY)
    out = svc.evaluation(db, ctx(role="owner"), "7d", NOW)
    assert out["available"] is True
    people = {p["name"]: p for p in out["callers"]}
    assert people["Anitha"]["calls_scored"] == 3
    assert people["Anitha"]["avg_score"] == round((80 + 40 + 95) / 3, 1)
    assert people["Anitha"]["top_weak_points"] == ["Next step: 0% of the marks on average"]
    assert people["Anitha"]["best"] == 95 and people["Anitha"]["worst"] == 40
    assert people["Bala"] == {"caller_id": b, "name": "Bala", "calls_scored": 0, "avg_score": None,
                              "best": None, "worst": None, "top_weak_points": []}
    assert out["lowest_calls"][0]["call_log_id"] == low["id"]
    assert out["lowest_calls"][0]["score"] == 40 and out["lowest_calls"][0]["lead_name"] == "Ravi"
    assert [c["score"] for c in out["lowest_calls"]] == [40, 80, 95]


def test_evaluation_30_days_includes_older_calls():
    db = FakeSupabase()
    a = caller(db, T1, "Anitha")
    scored_call(db, T1, a, 60, at="2026-11-01T05:00:00+00:00")
    assert svc.evaluation(db, ctx(role="owner"), "7d", NOW)["callers"][0]["calls_scored"] == 0
    assert svc.evaluation(db, ctx(role="owner"), "30d", NOW)["callers"][0]["calls_scored"] == 1


def test_evaluation_sim_client_gets_no_scores():
    db = FakeSupabase()
    db.add("app_settings", tenant_id=T1, key="telecalling_config", value=json.dumps({"calling_provider": "sim_basic"}))
    a = caller(db, T1, "Anitha")
    scored_call(db, T1, a, 80)
    out = svc.evaluation(db, ctx(role="owner"), "7d", NOW)
    assert out["available"] is False and out["callers"] == [] and out["lowest_calls"] == [] and out["message"]


def test_evaluation_tenant_isolation():
    db = FakeSupabase()
    other = caller(db, T2, "Other client")
    scored_call(db, T2, other, 5)
    mine = caller(db, T1, "Anitha")
    scored_call(db, T1, mine, 70)
    scored_call(db, T2, mine, 1)  # a stray row of another client pointing at my caller id
    out = svc.evaluation(db, ctx(role="owner"), "7d", NOW)
    assert [p["name"] for p in out["callers"]] == ["Anitha"]
    assert out["callers"][0]["calls_scored"] == 1 and len(out["lowest_calls"]) == 1


# ── Results ──────────────────────────────────────────────────────────────────


def seed_results(db):
    a = caller(db, T1, "Anitha")
    b = caller(db, T1, "Bala")
    for _ in range(3):
        db.add("call_logs", tenant_id=T1, caller_id=a, status="completed", manual_status="connected", created_at=TODAY)
    db.add("call_logs", tenant_id=T1, caller_id=a, status="no_answer", manual_status="not_reachable", created_at=TODAY)
    db.add("call_logs", tenant_id=T1, caller_id=b, status="completed", manual_status="connected", created_at=TODAY)
    db.add("call_logs", tenant_id=T1, caller_id=a, status="completed", manual_status="connected", created_at=YESTERDAY)
    db.add("call_logs", tenant_id=T1, caller_id=None, status="completed", created_at=TODAY)  # owner's own call
    db.add("deals", tenant_id=T1, stage="won", sold_by=a, won_at=TODAY, total_paise=118000, gst_paise=18000)
    db.add("deals", tenant_id=T1, stage="won", sold_by=a, won_at=TODAY, total_paise=50000, gst_paise=0)
    db.add("deals", tenant_id=T1, stage="open", sold_by=a, won_at=None, total_paise=999900, gst_paise=0)  # not paid yet
    db.add("deals", tenant_id=T1, stage="won", sold_by=b, won_at=YESTERDAY, total_paise=70000, gst_paise=0)
    db.add("deals", tenant_id=T1, stage="won", sold_by=None, won_at=TODAY, total_paise=30000, gst_paise=0)  # AI agent sale
    db.add("deals", tenant_id=T2, stage="won", sold_by=a, won_at=TODAY, total_paise=77700, gst_paise=0)
    return a, b


def test_results_today_calls_to_orders_to_money_with_totals():
    db = FakeSupabase()
    a, b = seed_results(db)
    out = svc.results(db, ctx(role="owner"), "today", NOW)
    rows = {r["name"]: r for r in out["callers"]}
    assert rows["Anitha"] == {"caller_id": a, "name": "Anitha", "calls": 4, "connected": 3, "orders": 2, "revenue_paise": 150000}
    assert rows["Bala"] == {"caller_id": b, "name": "Bala", "calls": 1, "connected": 1, "orders": 0, "revenue_paise": 0}
    assert out["totals"] == {"calls": 5, "connected": 4, "orders": 2, "revenue_paise": 150000}


def test_results_7d_adds_the_earlier_days():
    db = FakeSupabase()
    seed_results(db)
    out = svc.results(db, ctx(role="owner"), "7d", NOW)
    assert out["totals"] == {"calls": 6, "connected": 5, "orders": 3, "revenue_paise": 220000}


def test_results_money_is_left_out_without_deals_view():
    db = FakeSupabase()
    seed_results(db)
    out = svc.results(db, ctx(perms=["team.view"]), "today", NOW)
    assert all("revenue_paise" not in r for r in out["callers"]) and "revenue_paise" not in out["totals"]
    assert out["totals"]["orders"] == 2
    assert "revenue_paise" in svc.results(db, ctx(perms=["team.view", "deals.view"]), "today", NOW)["totals"]


def test_results_with_nobody_to_show_is_empty_not_an_error():
    out = svc.results(FakeSupabase(), ctx(role="owner"), "today", NOW)
    assert out["callers"] == [] and out["totals"] == {"calls": 0, "connected": 0, "orders": 0, "revenue_paise": 0}


# ── Routes ───────────────────────────────────────────────────────────────────


def get(c, db, path):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
    app.dependency_overrides[get_tenant_and_role] = lambda: c
    with patch("app.routes.call_iq_reports.get_supabase", return_value=db):
        return TestClient(app).get(f"/api/v1/call-iq{path}")


def test_live_route_allows_team_view_or_telecalling_view_only():
    db = FakeSupabase()
    me = caller(db, T1, "Anitha", status="active")
    assert get(ctx(perms=["telecalling.view"], caller_id=me), db, "/live").json()["callers"][0]["name"] == "Anitha"
    assert get(ctx(perms=["team.view"]), db, "/live").status_code == 200
    assert get(ctx(role="owner"), db, "/live").status_code == 200
    assert get(ctx(perms=["deals.view"]), db, "/live").status_code == 403


def test_evaluation_and_results_routes_need_team_view():
    db = FakeSupabase()
    for path in ("/evaluation", "/results"):
        assert get(ctx(perms=["telecalling.view"]), db, path).status_code == 403
        assert get(ctx(perms=["team.view"]), db, path).status_code == 200
        assert get(ctx(role="owner"), db, path).status_code == 200


def test_period_is_checked():
    db = FakeSupabase()
    owner = ctx(role="owner")
    assert get(owner, db, "/evaluation?period=today").status_code == 400  # evaluation has no 'today'
    assert get(owner, db, "/evaluation?period=30d").status_code == 200
    assert get(owner, db, "/results?period=90d").status_code == 400
    assert get(owner, db, "/results?period=today").status_code == 200
    assert get(owner, db, "/results").json()["period"] == "today"
    assert get(owner, db, "/evaluation").json()["period"] == "7d"
