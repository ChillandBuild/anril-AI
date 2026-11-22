"""Settings > Calling: "How your team calls". Read-only; the DB is the in-memory fake."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app
from app.services import calling_overview as co
from fake_supabase import FakeSupabase

T1, T2 = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
NOW = datetime(2026, 11, 22, 7, 0, tzinfo=timezone.utc)  # 12:30 PM in India


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.clear()


def config(db, tenant, **values):
    db.add("app_settings", tenant_id=tenant, key="telecalling_config", value=json.dumps(values))


def caller(db, tenant, name, **fields):
    db.add("callers", tenant_id=tenant, name=name, active=True, **fields)


def test_provider_mapping():
    assert co.provider_name({"calling_provider": "sim_basic"}) == "sim"
    assert co.provider_name({"calling_provider": "telecmi"}) == "cloud"
    assert co.provider_name({}) == "cloud"  # the app's default is TeleCMI


def test_sim_ready_when_app_version_or_last_sync_present():
    assert co.person_status({"name": "A", "app_version": 14}, "sim", NOW)["ready"] is True
    assert co.person_status({"name": "A", "last_sync_at": "2026-11-22T04:32:00+00:00"}, "sim", NOW)["ready"] is True
    out = co.person_status({"name": "A"}, "sim", NOW)
    assert out == {"name": "A", "ready": False, "detail": "Phone app not connected yet"}


def test_sim_detail_shows_version_and_last_seen_in_ist():
    out = co.person_status({"name": "Anitha", "app_version": 14, "last_sync_at": "2026-11-22T04:32:00+00:00"}, "sim", NOW)
    assert out["detail"] == "Phone app connected · app version 14 · last seen 10:02 AM"


def test_last_seen_on_an_earlier_day_names_the_day():
    assert co.last_seen_text("2026-11-12T04:32:00Z", NOW) == "12 Nov, 10:02 AM"
    assert co.last_seen_text(None, NOW) is None
    assert co.last_seen_text("garbage", NOW) is None


def test_cloud_ready_only_with_an_agent_id():
    assert co.person_status({"name": "A", "telecmi_agent_id": "5002_x"}, "cloud") == {"name": "A", "ready": True, "detail": "Cloud login set"}
    for blank in (None, "", "  "):
        assert co.person_status({"name": "A", "telecmi_agent_id": blank}, "cloud") == {"name": "A", "ready": False, "detail": "Cloud login not set"}


def test_rules_defaults_and_common_hours():
    db = FakeSupabase()
    out = co.overview(db, T1)
    assert out["rules"] == {"daily_target_calls": 50, "calling_hours": "9 AM to 7 PM"}
    config(db, T1, shift_start_hour=8, shift_end_hour=20, targets={"daily_calls": 80})
    out = co.overview(db, T1)
    assert out["rules"] == {"daily_target_calls": 80, "calling_hours": "8 AM to 8 PM"}


def test_individual_shift_mode_says_each_person_has_their_own_hours():
    db = FakeSupabase()
    config(db, T1, shift_mode="individual", shift_start_hour=9, shift_end_hour=19)
    assert co.overview(db, T1)["rules"]["calling_hours"] == "Each person has their own hours"


def test_hour_text_edges():
    assert [co.hour_text(h) for h in (0, 12, 13, 23)] == ["12 AM", "12 PM", "1 PM", "11 PM"]


def test_people_are_active_callers_of_this_tenant_only():
    db = FakeSupabase()
    config(db, T1, calling_provider="telecmi")
    caller(db, T1, "Bala", telecmi_agent_id="a1")
    caller(db, T1, "Anitha")
    db.add("callers", tenant_id=T1, name="Gone", active=False, telecmi_agent_id="a9")
    caller(db, T2, "Other client", telecmi_agent_id="z")
    out = co.overview(db, T1)
    assert out["provider"] == "cloud" and out["available"] is True
    assert [p["name"] for p in out["people"]] == ["Anitha", "Bala"]
    assert [p["ready"] for p in out["people"]] == [False, True]


def test_sim_tenant_people_use_phone_app_rules():
    db = FakeSupabase()
    config(db, T1, calling_provider="sim_basic")
    caller(db, T1, "Anitha", app_version=14)
    out = co.overview(db, T1, NOW)
    assert out["provider"] == "sim" and out["people"][0]["ready"] is True


def test_missing_callers_table_degrades():
    class Broken(FakeSupabase):
        def table(self, name):
            if name == "callers":
                raise RuntimeError("relation does not exist")
            return super().table(name)
    out = co.overview(Broken(), T1)
    assert out["available"] is False and out["people"] == []


def call(c, db):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
    app.dependency_overrides[get_tenant_and_role] = lambda: c
    with patch("app.routes.connections_overview.get_supabase", return_value=db):
        return TestClient(app).get("/api/v1/connections/calling")


def ctx(tenant=T1, role="caller", perms=()):
    return {"tenant_id": tenant, "role": role, "user_id": "u", "caller_id": None, "permissions": list(perms)}


def test_route_ok_for_settings_view_manage_and_owner():
    db = FakeSupabase()
    caller(db, T1, "Anitha", telecmi_agent_id="a")
    for c in (ctx(perms=["settings.view"]), ctx(perms=["settings.manage"]), ctx(role="owner")):
        r = call(c, db)
        assert r.status_code == 200 and r.json()["people"][0]["name"] == "Anitha"


def test_route_403_without_settings_permission():
    assert call(ctx(perms=["team.view", "deals.view"]), FakeSupabase()).status_code == 403


def test_route_tenant_isolation():
    db = FakeSupabase()
    caller(db, T2, "Other client")
    assert call(ctx(perms=["settings.view"]), db).json()["people"] == []


def test_failed_config_read_is_not_available_not_a_guessed_cloud(monkeypatch):
    def boom(tenant_id, db=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(co, "get_telecalling_config", boom)
    out = co.overview(FakeSupabase(), T1)
    assert out["available"] is False


def test_null_shift_hours_fall_back_to_defaults():
    assert co.calling_hours({"shift_start_hour": None, "shift_end_hour": None}) == "9 AM to 7 PM"
    assert co.calling_hours({"shift_start_hour": None, "shift_end_hour": 21}) == "9 AM to 9 PM"
    assert co.calling_hours({"shift_start_hour": "abc", "shift_end_hour": 99}) == "9 AM to 7 PM"
    assert co.calling_hours({"shift_start_hour": 0, "shift_end_hour": 12}) == "12 AM to 12 PM"  # 0 is a real hour


def test_non_dict_or_null_targets_use_the_default():
    for bad in (None, [], "50", 7, {"daily_calls": None}):
        assert co.daily_target({"targets": bad}) == 50
    assert co.daily_target({"targets": {"daily_calls": "80"}}) == 80


def test_stored_nulls_do_not_crash_the_overview():
    db = FakeSupabase()
    config(db, T1, shift_start_hour=None, shift_end_hour=None, targets=None)
    assert co.overview(db, T1)["rules"] == {"daily_target_calls": 50, "calling_hours": "9 AM to 7 PM"}
