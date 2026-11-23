"""v9.2 #168 Knowledge base: add a website link, and "Undo last change"."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.routes import knowledge
from app.routes import knowledge_extras as ke
from app.services import knowledge_versions as kv
from app.services import web_fetch
from app.routes.auto_messages import _SlidingWindow
from knowledge_sort_helpers import T, add_doc, env  # noqa: F401  (env is a fixture)


def _client(env, monkeypatch, role="owner", permissions=None, tenant=T):
    monkeypatch.setattr(ke, "get_supabase", lambda: env.db)
    monkeypatch.setattr(knowledge, "get_supabase", lambda: env.db)
    monkeypatch.setattr(knowledge, "_queue_rubric", lambda *a, **k: None)
    monkeypatch.setattr(knowledge, "_recheck", lambda *a, **k: None)
    monkeypatch.setattr(ke, "_link_limiter", _SlidingWindow(20, 3600))
    app = FastAPI()
    app.include_router(ke.router, prefix="/api/v1/knowledge")
    ctx = {"tenant_id": tenant, "role": role, "user_id": "u1", "permissions": permissions or []}
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    app.dependency_overrides[get_tenant_id] = lambda: tenant
    return TestClient(app)


@pytest.fixture
def processed(monkeypatch):
    calls = []

    async def fake_process(**kw):
        calls.append(kw)
    monkeypatch.setattr(ke, "process_document", fake_process)
    return calls


def _page(monkeypatch, url="https://shop.example/about", title="Sri Sweets", text="We sell sweets."):
    seen = []

    async def fake_fetch(u):
        seen.append(u)
        return url, title, text
    monkeypatch.setattr(web_fetch, "fetch_page_text", fake_fetch)
    return seen


def test_add_website_creates_a_document_and_starts_processing(env, monkeypatch, processed):
    client = _client(env, monkeypatch)
    _page(monkeypatch)
    res = client.post("/api/v1/knowledge/add-website", json={"url": "shop.example/about"})
    assert res.status_code == 200
    doc = res.json()
    assert doc["name"] == "shop.example/about" and doc["status"] == "processing" and doc["tenant_id"] == T
    assert doc["file_type"] == "text/plain" and doc["storage_path"] is None
    assert len(processed) == 1
    job = processed[0]
    assert job["document_id"] == doc["id"] and job["tenant_id"] == T and job["mime_type"] == "text/plain"
    body = job["file_content"].decode()
    assert "Source: https://shop.example/about" in body and "Page title: Sri Sweets" in body and "We sell sweets." in body


def test_a_refused_address_is_a_plain_422_and_nothing_is_saved(env, monkeypatch, processed):
    client = _client(env, monkeypatch)

    async def refuse(u):
        raise web_fetch.WebFetchError("That address can't be read. Use your public website address.")
    monkeypatch.setattr(web_fetch, "fetch_page_text", refuse)
    res = client.post("/api/v1/knowledge/add-website", json={"url": "http://169.254.169.254/"})
    assert res.status_code == 422 and "can't be read" in res.json()["detail"]
    assert env.db.rows("knowledge_documents") == [] and processed == []


def test_add_website_needs_knowledge_manage(env, monkeypatch, processed):
    client = _client(env, monkeypatch, role="agent", permissions=["knowledge.view"])
    _page(monkeypatch)
    assert client.post("/api/v1/knowledge/add-website", json={"url": "shop.example"}).status_code == 403
    assert client.get("/api/v1/knowledge/undo-last").status_code == 403
    assert client.post("/api/v1/knowledge/undo-last").status_code == 403
    assert env.db.rows("knowledge_documents") == []


def test_a_team_member_with_knowledge_manage_can_add_a_link(env, monkeypatch, processed):
    client = _client(env, monkeypatch, role="manager", permissions=["knowledge.manage"])
    _page(monkeypatch)
    assert client.post("/api/v1/knowledge/add-website", json={"url": "shop.example"}).status_code == 200


def test_links_are_rate_limited_per_business(env, monkeypatch, processed):
    client = _client(env, monkeypatch)
    _page(monkeypatch)
    monkeypatch.setattr(ke, "_link_limiter", _SlidingWindow(2, 3600))
    codes = [client.post("/api/v1/knowledge/add-website", json={"url": "shop.example"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# ---------------------------------------------------------------- undo last change

def _two_description_changes(env):
    env.set_description("First")
    kv.save_description(env.db, T, "Second", "edit", None)
    kv.save_description(env.db, T, "Third", "edit", None)


def test_nothing_to_undo_on_a_fresh_business(env, monkeypatch):
    client = _client(env, monkeypatch)
    assert client.get("/api/v1/knowledge/undo-last").json() == {"available": False}
    assert client.post("/api/v1/knowledge/undo-last").status_code == 404


def test_a_single_baseline_is_not_an_undoable_change(env, monkeypatch):
    env.set_description("First")
    kv.current_description_version(env.db, T)  # only the baseline exists
    client = _client(env, monkeypatch)
    assert client.get("/api/v1/knowledge/undo-last").json() == {"available": False}


def test_preview_then_undo_puts_back_the_text_before_the_last_change(env, monkeypatch):
    _two_description_changes(env)
    client = _client(env, monkeypatch)
    preview = client.get("/api/v1/knowledge/undo-last").json()
    assert preview["available"] is True and preview["kind"] == "description" and preview["label"] == "Description"

    res = client.post("/api/v1/knowledge/undo-last")
    assert res.status_code == 200 and res.json()["success"] is True
    assert env.description() == "Second"
    # the undo is itself a new "restore" version, so it can be undone again
    assert [v["reason"] for v in kv.list_versions(env.db, T, "description")][0] == "restore"


def test_undo_guard_refuses_when_something_changed_since_the_screen_loaded(env, monkeypatch):
    _two_description_changes(env)
    client = _client(env, monkeypatch)
    stale = client.get("/api/v1/knowledge/undo-last")
    wanted = stale.json()["version_id"]  # what the screen showed
    kv.save_description(env.db, T, "Fourth", "edit", None)  # someone else edits meanwhile
    res = client.post("/api/v1/knowledge/undo-last", json={"version_id": wanted})
    assert stale.status_code == 200
    assert res.status_code == 409
    assert env.description() == "Fourth"


def test_undo_guard_accepts_the_current_version(env, monkeypatch):
    _two_description_changes(env)
    client = _client(env, monkeypatch)
    wanted = client.get("/api/v1/knowledge/undo-last").json()["version_id"]
    assert client.post("/api/v1/knowledge/undo-last", json={"version_id": wanted}).status_code == 200
    assert env.description() == "Second"


def test_a_malformed_guard_id_is_refused_without_touching_anything(env, monkeypatch):
    _two_description_changes(env)
    client = _client(env, monkeypatch)
    assert client.post("/api/v1/knowledge/undo-last", json={"version_id": "nope"}).status_code == 422
    assert env.description() == "Third"


def test_description_undo_is_owner_only(env, monkeypatch):
    _two_description_changes(env)
    client = _client(env, monkeypatch, role="manager", permissions=["knowledge.manage"])
    assert client.post("/api/v1/knowledge/undo-last").status_code == 403
    assert env.description() == "Third"


def test_another_business_history_is_never_used(env, monkeypatch):
    kv.save_description(env.db, "tenant-2", "Other one", "edit", None)
    kv.save_description(env.db, "tenant-2", "Other two", "edit", None)
    client = _client(env, monkeypatch)
    assert client.get("/api/v1/knowledge/undo-last").json() == {"available": False}
