"""v9.2 #80 "Let the Anril team do it" on first setup step 2, plus the operator's list."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.system_admin import get_system_admin
from app.dependencies.tenant import get_tenant_and_role
from app.routes import setup_help as routes
from tests.fake_supabase import FakeSupabase


def _client(perms, tenant="t-1", admin=False):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/setup-help")
    app.include_router(routes.operator_router, prefix="/api/v1/operator")
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": tenant, "role": "caller", "permissions": perms, "user_id": "u-1"}
    if admin:
        app.dependency_overrides[get_system_admin] = lambda: {"user_id": "admin-1"}
    return TestClient(app)


@pytest.fixture()
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(routes, "get_supabase", lambda: fake)
    monkeypatch.setattr(routes, "record_audit_event", lambda *a, **k: None)
    return fake


def test_not_requested_yet(db):
    assert _client(["settings.manage"]).get("/api/v1/setup-help/catalogue").json() == {"requested": False, "requested_at": None}


def test_request_is_saved_for_this_business_only(db):
    res = _client(["settings.manage"]).post("/api/v1/setup-help/catalogue")
    assert res.status_code == 200 and res.json()["requested"] is True
    rows = db.rows("setup_help_requests")
    assert [(r["tenant_id"], r["kind"], r["status"], r["requested_by"]) for r in rows] == [("t-1", "catalogue", "open", "u-1")]
    assert _client(["settings.manage"]).get("/api/v1/setup-help/catalogue").json()["requested"] is True
    assert _client(["settings.manage"], tenant="t-2").get("/api/v1/setup-help/catalogue").json()["requested"] is False


def test_asking_twice_keeps_one_open_request(db):
    c = _client(["settings.manage"])
    first = c.post("/api/v1/setup-help/catalogue").json()
    second = c.post("/api/v1/setup-help/catalogue").json()
    assert len(db.rows("setup_help_requests")) == 1
    assert first["requested_at"] == second["requested_at"]


def test_needs_settings_manage(db):
    assert _client(["settings.view"]).post("/api/v1/setup-help/catalogue").status_code == 403
    assert db.rows("setup_help_requests") == []


def test_missing_table_answers_plainly(db, monkeypatch):
    def not_ready(*a, **k):
        raise routes.setup_help.SetupHelpNotReady()
    monkeypatch.setattr(routes.setup_help, "open_request", not_ready)
    c = _client(["settings.manage"])
    assert c.get("/api/v1/setup-help/catalogue").json()["requested"] is False
    assert c.post("/api/v1/setup-help/catalogue").status_code == 503


def test_operator_sees_open_requests_with_business_name_and_can_close(db):
    db.add("tenants", id="t-1", name="Sri Sweets")
    _client(["settings.manage"]).post("/api/v1/setup-help/catalogue")
    op = _client([], admin=True)
    items = op.get("/api/v1/operator/setup-help-requests").json()["items"]
    assert len(items) == 1 and items[0]["tenant_name"] == "Sri Sweets" and items[0]["tenant_id"] == "t-1"
    done = op.post(f"/api/v1/operator/setup-help-requests/{items[0]['id']}/done", json={"status": "done"})
    assert done.status_code == 200
    assert op.get("/api/v1/operator/setup-help-requests").json()["items"] == []
    # closed: the business can ask again
    again = _client(["settings.manage"]).post("/api/v1/setup-help/catalogue")
    assert again.status_code == 200 and len(db.rows("setup_help_requests")) == 2


def test_operator_routes_need_a_system_admin(db):
    # no override for get_system_admin -> the real dependency runs and refuses a normal user
    app = FastAPI()
    app.include_router(routes.operator_router, prefix="/api/v1/operator")
    assert TestClient(app).get("/api/v1/operator/setup-help-requests").status_code in (401, 403)


def test_operator_list_is_empty_when_the_table_is_missing():
    from app.services import setup_help

    class NoTable:
        def table(self, *_):
            raise RuntimeError('relation "setup_help_requests" does not exist')
    assert setup_help.list_open(NoTable()) == []
