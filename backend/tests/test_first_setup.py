"""v9.2 #27 First setup progress (GET/PUT /api/v1/first-setup/progress, settings.manage)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role
from app.routes import first_setup
from tests.fake_supabase import FakeSupabase


def _client(perms, tenant="t-1", role="caller", db=None):
    app = FastAPI()
    app.include_router(first_setup.router, prefix="/api/v1/first-setup")
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": tenant, "role": role, "permissions": perms}
    return TestClient(app)


@pytest.fixture()
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(first_setup, "get_supabase", lambda: fake)
    return fake


def test_not_started_looks_empty(db):
    res = _client(["settings.manage"]).get("/api/v1/first-setup/progress")
    assert res.status_code == 200
    assert res.json() == {"step": "business", "done_steps": []}


def test_save_then_read_back(db):
    c = _client(["settings.manage"])
    put = c.put("/api/v1/first-setup/progress", json={"step": "connect", "done_steps": ["items", "business"]})
    assert put.json() == {"step": "connect", "done_steps": ["business", "items"]}
    assert c.get("/api/v1/first-setup/progress").json() == put.json()


def test_unknown_steps_are_dropped_and_duplicates_collapse():
    assert first_setup.clean_progress("nope", ["ai", "ai", "x", 5]) == {"step": "business", "done_steps": ["ai"]}
    assert first_setup.clean_progress(None, "junk") == {"step": "business", "done_steps": []}


def test_progress_is_per_business(db):
    _client(["settings.manage"], tenant="t-1").put("/api/v1/first-setup/progress", json={"step": "ai", "done_steps": ["business"]})
    assert _client(["settings.manage"], tenant="t-2").get("/api/v1/first-setup/progress").json()["done_steps"] == []


def test_needs_settings_manage(db):
    c = _client(["settings.view"])
    assert c.get("/api/v1/first-setup/progress").status_code == 403
    assert c.put("/api/v1/first-setup/progress", json={"step": "ai", "done_steps": []}).status_code == 403


def test_unreadable_progress_looks_not_started(db):
    db.add("app_settings", tenant_id="t-1", key=first_setup.SETTING_KEY, value="{not json")
    assert _client(["settings.manage"]).get("/api/v1/first-setup/progress").json() == {"step": "business", "done_steps": []}


def test_main_registers_the_routes():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/first-setup/progress" in paths and "/api/v1/password-help/request" in paths


def test_operator_made_login_asks_for_a_new_password_on_first_sign_in(monkeypatch):
    from unittest.mock import MagicMock
    from app.routes import operator

    db = MagicMock()
    db.auth.admin.create_user.return_value.user.id = "u-1"
    db.table.return_value.insert.return_value.execute.return_value.data = [{"id": "t-9"}]
    monkeypatch.setattr(operator, "get_supabase", lambda: db)
    payload = operator.CreateClientPayload(
        company_name="Sri Stores", business_type="retail", contact_name="Ravi",
        contact_phone="9876543210", email="ravi@sri.example", password="first-pass-1",
    )
    try:
        operator.create_client(payload, _admin={"user_id": "a"})
    except Exception:
        pass  # only the sign-in details matter here
    sent = db.auth.admin.create_user.call_args.args[0]
    assert sent["user_metadata"] == {"must_change_password": True}
    assert sent["email_confirm"] is True
