"""Operator Console -> MCP: the per-client connector list and switch.

Every test swaps the database for a FakeSupabase: this laptop's environment points at the live
database, so a test that reached the real get_supabase would touch production.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import system_admin
from app.dependencies.auth import get_current_user
from app.main import app
from app.routes import operator_mcp
from app.services.client_claude import ist_day
from tests.fake_supabase import FakeSupabase

URL = "https://api.example.com/client/mcp"
ADMIN_ID = "admin-1"


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.clear()


def _db() -> FakeSupabase:
    db = FakeSupabase()
    db.add("system_admins", user_id=ADMIN_ID)
    return db


def _call(db, method, path, *, user_id=ADMIN_ID, **kwargs):
    """Calls the route as `user_id`, with both modules that read the database pointed at `db`."""
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "email": "x@example.com"}
    with patch.object(operator_mcp, "get_supabase", return_value=db), \
         patch.object(system_admin, "get_supabase", return_value=db), \
         patch.object(operator_mcp, "_client_public_url", return_value=URL), \
         patch.object(settings, "mcp_client_enabled", True):
        return getattr(TestClient(app, raise_server_exceptions=False), method)(path, **kwargs)


def _list(db, **kwargs):
    return _call(db, "get", "/api/v1/operator/mcp/clients", **kwargs)


def _switch(db, tenant_id, on, **kwargs):
    return _call(db, "put", f"/api/v1/operator/mcp/clients/{tenant_id}", json={"on": on}, **kwargs)


def _audit(db):
    return [r for r in db.rows("app_audit_logs") if r["action"] == "operator.features_updated"]


# ── the list ──────────────────────────────────────────────────────────────────

def test_list_shows_switch_connection_sends_and_cap_per_client_sorted_by_name():
    db = _db()
    db.add("tenants", id="t-b", name="beta shop", status="active", enabled_features=["whatsapp"])
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=["whatsapp", "claude"])
    db.add("tenants", id="t-c", name="Corner Store", status="suspended", enabled_features=["claude"])
    db.add("tenants", id="t-d", name="Dosa Hut", status="active", enabled_features=None)
    # Astro Tamil: two active connections (newest created / newest used are picked) and an older revoked one.
    db.add("tenant_mcp_connections", tenant_id="t-a", user_id="u1", client_id="app", status="active",
           created_at="2026-11-01T00:00:00+00:00", last_used_at="2026-11-20T00:00:00+00:00")
    db.add("tenant_mcp_connections", tenant_id="t-a", user_id="u2", client_id="app", status="active",
           created_at="2026-11-10T00:00:00+00:00", last_used_at=None)
    db.add("tenant_mcp_connections", tenant_id="t-a", user_id="u3", client_id="app", status="revoked",
           created_at="2026-12-01T00:00:00+00:00", last_used_at="2026-12-02T00:00:00+00:00")
    # Corner Store: only a revoked connection, so not connected.
    db.add("tenant_mcp_connections", tenant_id="t-c", user_id="u4", client_id="app", status="revoked",
           created_at="2026-11-05T00:00:00+00:00", last_used_at="2026-11-06T00:00:00+00:00")
    db.add("claude_send_days", tenant_id="t-a", day=ist_day(), sent=42)
    db.add("claude_send_days", tenant_id="t-a", day="2020-01-01", sent=999)  # another day: ignored
    db.add("app_settings", tenant_id="t-a", key="claude_daily_send_cap", value="120")
    db.add("app_settings", tenant_id="t-c", key="claude_daily_send_cap", value="999999")  # clamped
    db.add("app_settings", tenant_id="t-b", key="something_else", value="7")

    response = _list(db)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["mcp_url"] == URL
    assert body["default_daily_cap"] == 500
    assert [c["name"] for c in body["clients"]] == ["Astro Tamil", "beta shop", "Corner Store", "Dosa Hut"]
    astro, beta, corner, dosa = body["clients"]
    assert astro == {
        "tenant_id": "t-a", "name": "Astro Tamil", "status": "active", "on": True, "connected": True,
        "connected_at": "2026-11-10T00:00:00+00:00", "last_used_at": "2026-11-20T00:00:00+00:00",
        "sent_today": 42, "daily_cap": 120,
    }
    assert (beta["on"], beta["connected"], beta["sent_today"], beta["daily_cap"]) == (False, False, 0, 500)
    assert beta["connected_at"] is None and beta["last_used_at"] is None
    assert (corner["on"], corner["connected"], corner["status"]) == (True, False, "suspended")
    assert corner["connected_at"] is None and corner["last_used_at"] is None
    assert corner["daily_cap"] == 10_000
    assert dosa["on"] is False


def test_list_runs_four_queries_however_many_clients():
    db = _db()
    for i in range(5):
        db.add("tenants", id=f"t{i}", name=f"Client {i}", status="active", enabled_features=[])
    seen = []
    original = db.table
    db.table = lambda name: (seen.append(name), original(name))[1]

    assert _list(db).status_code == 200
    assert sorted(seen) == sorted(["system_admins", "tenants", "tenant_mcp_connections", "claude_send_days", "app_settings"])


# ── who may call ──────────────────────────────────────────────────────────────

def test_a_login_that_is_not_a_system_admin_gets_403_on_both_routes():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=[])

    assert _list(db, user_id="owner-of-a-client").status_code == 403
    assert _switch(db, "t-a", True, user_id="owner-of-a-client").status_code == 403
    assert db.rows("tenants")[0]["enabled_features"] == []
    assert _audit(db) == []


# ── the switch ────────────────────────────────────────────────────────────────

def test_switching_on_adds_only_claude_and_keeps_the_other_keys_in_order():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=["whatsapp", "telecalling"])

    response = _switch(db, "t-a", True)

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "t-a", "on": True}
    assert db.rows("tenants")[0]["enabled_features"] == ["whatsapp", "telecalling", "claude"]


def test_switching_on_twice_does_not_duplicate_the_key_or_write_a_second_audit_row():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=["whatsapp"])

    assert _switch(db, "t-a", True).status_code == 200
    again = _switch(db, "t-a", True)

    assert again.status_code == 200 and again.json() == {"tenant_id": "t-a", "on": True}
    assert db.rows("tenants")[0]["enabled_features"] == ["whatsapp", "claude"]
    assert len(_audit(db)) == 1


def test_switching_on_a_client_with_no_feature_list_creates_one():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=None)

    assert _switch(db, "t-a", True).status_code == 200
    assert db.rows("tenants")[0]["enabled_features"] == ["claude"]


def test_switching_off_removes_only_claude():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=["claude", "whatsapp", "telecalling"])

    response = _switch(db, "t-a", False)

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "t-a", "on": False}
    assert db.rows("tenants")[0]["enabled_features"] == ["whatsapp", "telecalling"]


def test_switching_off_when_already_off_changes_and_logs_nothing():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=["whatsapp"])

    assert _switch(db, "t-a", False).status_code == 200
    assert db.rows("tenants")[0]["enabled_features"] == ["whatsapp"]
    assert _audit(db) == []


def test_switching_an_unknown_client_gets_404():
    db = _db()

    response = _switch(db, "no-such-tenant", True)

    assert response.status_code == 404
    assert response.json()["detail"] == "Tenant not found"
    assert _audit(db) == []


def test_a_change_writes_the_features_updated_audit_row():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=["whatsapp"])

    _switch(db, "t-a", True)
    _switch(db, "t-a", False)

    on_row, off_row = _audit(db)
    assert on_row["tenant_id"] == "t-a" and on_row["target_id"] == "t-a" and on_row["target_type"] == "tenant"
    assert on_row["actor_user_id"] == ADMIN_ID and on_row["actor_role"] == "system_admin"
    assert on_row["metadata"] == {"features": ["whatsapp", "claude"], "changed": {"claude": True}}
    assert off_row["metadata"] == {"features": ["whatsapp"], "changed": {"claude": False}}


def test_the_switch_requires_the_on_field():
    db = _db()
    db.add("tenants", id="t-a", name="Astro Tamil", status="active", enabled_features=[])

    response = _call(db, "put", "/api/v1/operator/mcp/clients/t-a", json={})

    assert response.status_code == 422
