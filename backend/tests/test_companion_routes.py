"""companion-core T2: character settings routes, tenant-scoped, behind settings.manage."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store
from app.routes import companions
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    ctx = {"tenant_id": "t1", "user_id": "u1", "role": "owner"}
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[companions.require_settings_manage] = lambda: ctx
    return type("Env", (), {"client": TestClient(app), "db": fake, "ctx": ctx})


def test_owner_creates_several_characters_then_lists_reads_and_patches(env):
    c = env.client
    j = c.post(BASE, json={"name": "Jothidar AI", "industry": "astrology", "default_mood": "warm",
                           "sample_lines": ["Kavalaipadaathinga."]})
    v = c.post(BASE, json={"name": "Vastu Guru"})
    assert j.status_code == 201 and v.status_code == 201
    assert [x["name"] for x in c.get(BASE).json()["companions"]] == ["Jothidar AI", "Vastu Guru"]
    jid = j.json()["id"]
    assert c.get(f"{BASE}/{jid}").json()["default_mood"] == "warm"
    patched = c.patch(f"{BASE}/{jid}", json={"status": "live", "goals": ["Help the user feel heard"]})
    assert patched.status_code == 200
    assert patched.json()["status"] == "live" and patched.json()["name"] == "Jothidar AI"


def test_another_tenants_character_is_404_everywhere(env):
    other = env.db.add("companions", tenant_id="t2", name="Their bot", status="draft")
    assert env.client.get(f"{BASE}/{other['id']}").status_code == 404
    assert env.client.patch(f"{BASE}/{other['id']}", json={"status": "live"}).status_code == 404
    assert env.db.rows("companions")[0]["status"] == "draft"
    assert env.client.get(BASE).json()["companions"] == []


@pytest.mark.parametrize("body", [
    {"name": "X", "memory_level": 3},
    {"name": "X", "default_mood": "angry"},
    {"name": "X", "privacy_mode": "C"},
    {"name": "X", "tenant_id": "t2"},
    {"name": ""},
    {"name": "X", "backstory": "b" * 2001},
])
def test_invalid_input_is_422(env, body):
    assert env.client.post(BASE, json=body).status_code == 422


def test_a_non_uuid_id_is_422_not_a_db_error(env):
    assert env.client.get(f"{BASE}/not-a-uuid").status_code == 422


def test_patch_rejects_invalid_values(env):
    jid = env.client.post(BASE, json={"name": "Jothidar AI"}).json()["id"]
    assert env.client.patch(f"{BASE}/{jid}", json={"memory_level": 3}).status_code == 422


def test_books_tag_must_belong_to_this_tenant(env):
    mine = env.db.add("broadcast_tags", tenant_id="t1", name="astrology books")
    theirs = env.db.add("broadcast_tags", tenant_id="t2", name="their books")
    ok = env.client.post(BASE, json={"name": "Jothidar AI", "knowledge_tag_id": mine["id"]})
    assert ok.status_code == 201 and ok.json()["knowledge_tag_id"] == mine["id"]
    assert env.client.post(BASE, json={"name": "Vastu", "knowledge_tag_id": theirs["id"]}).status_code == 422
    jid = ok.json()["id"]
    assert env.client.patch(f"{BASE}/{jid}", json={"knowledge_tag_id": theirs["id"]}).status_code == 422
    cleared = env.client.patch(f"{BASE}/{jid}", json={"knowledge_tag_id": None})
    assert cleared.status_code == 200 and cleared.json()["knowledge_tag_id"] is None


def test_duplicate_name_is_409(env, monkeypatch):
    async def dup(tenant_id, settings):
        raise store.DuplicateCompanionName(settings.name)
    monkeypatch.setattr(store, "create_companion", dup)
    assert env.client.post(BASE, json={"name": "Jothidar AI"}).status_code == 409


def test_routes_need_settings_manage():
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    from app.dependencies.tenant import get_tenant_and_role
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t1", "role": "agent", "permissions": []}
    assert TestClient(app).get(BASE).status_code == 403


def test_router_is_mounted_in_the_app():
    from app.main import app
    # Without a login the real app answers 401/403 (auth runs), never 404 (route missing).
    assert TestClient(app).get(BASE).status_code in (401, 403)
