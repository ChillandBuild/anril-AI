"""Anril Agents (companion) routes sit behind their own key, companions.manage.
settings.manage alone no longer opens them; the owner always does."""
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store
from app.dependencies.tenant import get_tenant_and_role
from app.routes import companions
from app.services.rbac import ALL_PERMISSION_KEYS, normalize_permissions
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"
ANY_ID = "00000000-0000-0000-0000-000000000001"


def _client(monkeypatch, ctx):
    monkeypatch.setattr(store, "get_supabase", lambda: FakeSupabase())
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    return app, TestClient(app)


def _calls():
    """Every companion route, with path params filled in."""
    for route in companions.router.routes:
        path = BASE + re.sub(r"\{[^}]+\}", ANY_ID, route.path)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            yield method, path


def test_key_is_in_the_catalog():
    assert "companions.manage" in ALL_PERMISSION_KEYS
    assert normalize_permissions(["companions.manage"]) == ["companions.manage"]


@pytest.mark.parametrize("perms", [[], ["settings.manage", "settings.view"], ["knowledge.manage"]])
def test_every_companion_route_is_403_without_the_key(monkeypatch, perms):
    _, client = _client(monkeypatch, {"tenant_id": "t1", "user_id": "u1", "role": "manager", "permissions": perms})
    calls = list(_calls())
    assert len(calls) >= 10
    for method, path in calls:
        res = client.request(method, path, json={})
        assert res.status_code == 403, (method, path, res.status_code)
        assert res.json()["detail"] == "Permission required: companions.manage"


def test_the_key_opens_the_routes(monkeypatch):
    _, client = _client(monkeypatch, {"tenant_id": "t1", "user_id": "u1", "role": "manager",
                                      "permissions": ["companions.manage"]})
    assert client.get(BASE).status_code == 200


def test_owner_needs_no_key(monkeypatch):
    _, client = _client(monkeypatch, {"tenant_id": "t1", "user_id": "u1", "role": "owner", "permissions": []})
    assert client.get(BASE).status_code == 200
