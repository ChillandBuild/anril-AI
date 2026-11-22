"""GET /api/v1/operator/me: "is this login an Anril system admin?"

The Claude consent screen relies on the 403 to show "Only an Anril system admin can allow
this". Regression (2026-11-22): a client owner connecting Anril Admin got "Internal server
error", because the real database library answers a no-row `maybe_single()` with None (not an
object whose .data is None, which is what FakeSupabase gives), and the route read `.data` off it.
"""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.main import app
from app.routes import operator


class _AdminsTable:
    """system_admins as postgrest 2.x answers it: None when no row matches."""

    def __init__(self, admin_ids):
        self._admin_ids = set(admin_ids)
        self._wanted = None

    def table(self, name):
        assert name == "system_admins"
        return self

    def select(self, _columns):
        return self

    def eq(self, column, value):
        assert column == "user_id"
        self._wanted = value
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._wanted in self._admin_ids:
            return SimpleNamespace(data={"user_id": self._wanted})
        return None


def _me(user_id, admin_ids=("admin-1",)):
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "email": "x@example.com"}
    try:
        with patch.object(operator, "get_supabase", return_value=_AdminsTable(admin_ids)):
            return TestClient(app, raise_server_exceptions=False).get("/api/v1/operator/me")
    finally:
        app.dependency_overrides.clear()


def test_a_login_that_is_not_a_system_admin_is_told_no_instead_of_crashing():
    response = _me("owner-of-a-client")
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied."


def test_a_system_admin_is_confirmed():
    response = _me("admin-1")
    assert response.status_code == 200
    assert response.json() == {"is_system_admin": True, "user_id": "admin-1"}
