"""Who got which lead (v9.2 #235): who sees which rows, the by-hand and date filters, masked phones, and the
download (Download lists rule + Activity log). DB = FakeSupabase."""
import csv
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from tests.fake_supabase import FakeSupabase

T1, T2 = "t1", "t2"
URL = "/api/v1/assignment-log"
OWNER = {"tenant_id": T1, "role": "owner", "user_id": "u-owner", "caller_id": None, "permissions": []}
MANAGER = {"tenant_id": T1, "role": "caller", "user_id": "u-mgr", "caller_id": None, "permissions": ["team.view", "leads.download"]}
LEADER = {"tenant_id": T1, "role": "caller", "role_slug": "team_leader", "user_id": "u-lead", "caller_id": "c-lead",
          "permissions": ["team.view", "leads.download"]}
TELECALLER = {"tenant_id": T1, "role": "caller", "user_id": "u-anitha", "caller_id": "c-anitha", "permissions": ["telecalling.dialer"]}
TELECALLER_DL = {**TELECALLER, "permissions": ["telecalling.dialer", "leads.download"]}
NOBODY = {"tenant_id": T1, "role": "caller", "user_id": "u-x", "caller_id": "c-x", "permissions": ["leads.view"]}


def event(db, eid, caller, lead, *, method="round-robin", reason="round_robin", when="2026-11-20T10:00:00+00:00", tenant=T1, segment="A"):
    db.add("lead_stage_events", id=eid, tenant_id=tenant, lead_id=lead, to_segment=segment, event_type="assigned",
           metadata={"caller_id": caller, "caller_name": caller.upper(), "reason": reason, "method": method}, created_at=when)


@pytest.fixture
def env():
    db = FakeSupabase()
    for lid, name, phone in (("l1", "Priya", "+919876543210"), ("l2", "Suresh", "+919123456789"), ("l3", "Meena", "+919000011111")):
        db.add("leads", id=lid, tenant_id=T1, name=name, phone=phone)
    event(db, "e1", "c-anitha", "l1", when="2026-11-20T10:00:00+00:00")
    event(db, "e2", "c-bala", "l2", method="admin", reason="manual_assign", when="2026-11-21T10:00:00+00:00")
    event(db, "e3", "c-anitha", "l3", method="admin", reason="bulk_assign", when="2026-11-22T10:00:00+00:00")
    event(db, "e4", "c-lead", "l3", when="2026-11-22T11:00:00+00:00")
    event(db, "e5", "c-anitha", "l1", tenant=T2)                       # another business
    db.add("callers", id="c-anitha", tenant_id=T1, team_id="team-1")
    db.add("callers", id="c-bala", tenant_id=T1, team_id="team-2")
    db.add("callers", id="c-lead", tenant_id=T1, team_id="team-1")
    db.add("tenant_users", tenant_id=T1, user_id="u-lead", role_id="r-lead")
    db.add("tenant_roles", id="r-lead", tenant_id=T1, slug="team_leader")
    db.add("call_team_leaders", tenant_id=T1, team_id="team-1", user_id="u-lead")
    with patch("app.routes.assignment_log.get_supabase", return_value=db), \
         patch("app.services.call_teams.get_supabase", return_value=db, create=True):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
        try:
            yield type("Env", (), {"db": db, "client": TestClient(app)})
        finally:
            app.dependency_overrides.clear()


def get(env, ctx, **params):
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    return env.client.get(URL, params=params)


def ids(res):
    return [r["id"] for r in res.json()["data"]]


def csv_rows(res):
    return list(csv.DictReader(io.StringIO(res.text)))


def test_owner_and_team_view_see_everyone_but_never_another_business(env):
    assert ids(get(env, OWNER)) == ["e4", "e3", "e2", "e1"]
    assert ids(get(env, MANAGER)) == ["e4", "e3", "e2", "e1"]


def test_a_telecaller_sees_only_their_own_rows(env):
    res = get(env, TELECALLER)
    assert ids(res) == ["e3", "e1"] and res.json()["meta"]["total"] == 2
    # asking for someone else's rows returns nothing, not their rows
    assert ids(get(env, TELECALLER, caller_id="c-bala")) == []
    assert get(env, TELECALLER, caller_id="c-anitha").json()["meta"]["total"] == 2


def test_a_telecaller_with_no_telecaller_profile_sees_nothing(env):
    assert ids(get(env, {**TELECALLER, "caller_id": None})) == []


def test_a_team_leader_sees_their_team_and_themself(env):
    assert ids(get(env, LEADER)) == ["e4", "e3", "e1"]               # c-bala is on the other team
    assert ids(get(env, LEADER, caller_id="c-bala")) == []


def test_people_without_team_or_telecalling_view_are_refused(env):
    assert get(env, NOBODY).status_code == 403
    assert get(env, NOBODY, format="csv").status_code == 403


def test_by_hand_filter_keeps_only_leads_a_person_assigned(env):
    assert ids(get(env, OWNER, by_hand="true")) == ["e3", "e2"]
    assert ids(get(env, TELECALLER, by_hand="true")) == ["e3"]


def test_date_filter_keeps_the_days_asked_for(env):
    res = get(env, OWNER, from_date="2026-11-21T00:00:00+00:00", to_date="2026-11-21T23:59:59+00:00")
    assert ids(res) == ["e2"]
    assert ids(get(env, OWNER, from_date="2026-11-22T00:00:00+00:00")) == ["e4", "e3"]


def test_phones_are_hidden_for_a_telecaller_when_the_business_hides_numbers(env):
    with patch("app.services.call_rules.get_rules", return_value={"hide_numbers_for_callers": True}), \
         patch("app.services.call_rules.effective_calling_mode", return_value="telecmi"):
        mine = get(env, TELECALLER).json()["data"]
        assert {r["lead_phone"] for r in mine} == {"98•••••210", "90•••••111"}
        assert all("+91" not in (r["lead_phone"] or "") for r in mine)
        assert get(env, OWNER).json()["data"][0]["lead_phone"] == "+919000011111"      # the owner is never masked


def test_phones_show_for_a_telecaller_when_numbers_are_not_hidden(env):
    with patch("app.services.call_rules.get_rules", return_value={"hide_numbers_for_callers": False}):
        assert get(env, TELECALLER).json()["data"][0]["lead_phone"] == "+919000011111"


def test_download_needs_the_download_permission_and_is_logged(env):
    assert get(env, TELECALLER, format="csv").status_code == 403
    assert [r for r in env.db.rows("app_audit_logs") if r.get("action") == "leads.download"] == []
    res = get(env, TELECALLER_DL, format="csv", by_hand="true", from_date="2026-11-01T00:00:00+00:00")
    assert res.status_code == 200
    assert [r["lead_name"] for r in csv_rows(res)] == ["Meena"]
    log = [r for r in env.db.rows("app_audit_logs") if r.get("action") == "leads.download"]
    assert log[0]["metadata"]["list"] == "Assignment log" and log[0]["metadata"]["rows"] == 1
    assert log[0]["metadata"]["filters"]["by_hand"] is True and log[0]["tenant_id"] == T1


def test_download_keeps_the_same_scope_and_masks_phones(env):
    with patch("app.services.call_rules.get_rules", return_value={"hide_numbers_for_callers": True}), \
         patch("app.services.call_rules.effective_calling_mode", return_value="telecmi"):
        rows = csv_rows(get(env, TELECALLER_DL, format="csv"))
    assert [r["lead_name"] for r in rows] == ["Meena", "Priya"] and {r["lead_phone"] for r in rows} == {"98•••••210", "90•••••111"}
    assert [r["lead_name"] for r in csv_rows(get(env, LEADER, format="csv"))] == ["Meena", "Meena", "Priya"]


def test_download_reads_past_the_1000_row_cap(env):
    for i in range(1200):
        event(env.db, f"x{i}", "c-anitha", "l1", when=f"2026-10-01T00:{i // 60:02d}:{i % 60:02d}+00:00")
    assert len(csv_rows(get(env, OWNER, format="csv"))) == 1204


def test_summary_follows_the_same_people(env):
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    event(env.db, "s1", "c-anitha", "l1", when=today)
    event(env.db, "s2", "c-bala", "l2", when=today)
    app.dependency_overrides[get_tenant_and_role] = lambda: OWNER
    assert env.client.get(URL + "/summary").json()["assigned_today"] == 2
    app.dependency_overrides[get_tenant_and_role] = lambda: TELECALLER
    mine = env.client.get(URL + "/summary").json()
    assert mine["assigned_today"] == 1 and list(mine["by_caller"]) == ["c-anitha"]
