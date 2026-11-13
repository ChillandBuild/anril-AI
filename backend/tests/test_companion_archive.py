"""Characters page: Archive, Restore and Delete permanently.

Example: Jothidar AI is Live. Archive → hidden from the list, shown under Archived, status paused
(stops answering at once). Restore → back in the list as Draft. Delete permanently → gone, with its
chats and memory (the database cascades). Another business's character is 404 for all three.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store
from app.routes import companions
from app.services import ai_reply
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(companions, "get_supabase", lambda: fake)
    # The overview also asks which AI model is set: keep that off the real database.
    monkeypatch.setattr(ai_reply, "_resolve_reply_model", lambda tenant_id: "gemini/gemini-3.1-flash")
    monkeypatch.setattr(ai_reply, "_resolve_provider", lambda tenant_id: ("gemini", "gemini-3.1-flash"))
    ctx = {"tenant_id": "t1", "user_id": "u1", "role": "owner"}
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[companions.require_companions_manage] = lambda: ctx
    return type("Env", (), {"client": TestClient(app), "db": fake})


def _live(env, name="Jothidar AI"):
    cid = env.client.post(BASE, json={"name": name}).json()["id"]
    assert env.client.patch(f"{BASE}/{cid}", json={"status": "live"}).status_code == 200
    return cid


def _names(env, **params):
    return [c["name"] for c in env.client.get(BASE, params=params).json()["companions"]]


def test_archive_hides_it_pauses_it_and_lists_it_under_archived(env):
    cid = _live(env)
    _live(env, "Vastu Guru")
    r = env.client.post(f"{BASE}/{cid}/archive")
    assert r.status_code == 200
    assert r.json()["status"] == "paused" and r.json()["archived_at"]
    assert _names(env) == ["Vastu Guru"]
    assert _names(env, archived="true") == ["Jothidar AI"]


def test_restore_brings_it_back_as_draft(env):
    cid = _live(env)
    env.client.post(f"{BASE}/{cid}/archive")
    r = env.client.post(f"{BASE}/{cid}/restore")
    assert r.status_code == 200
    assert r.json()["status"] == "draft" and r.json()["archived_at"] is None
    assert _names(env) == ["Jothidar AI"] and _names(env, archived="true") == []


def test_an_archived_character_cannot_be_set_live_without_restoring(env):
    cid = _live(env)
    env.client.post(f"{BASE}/{cid}/archive")
    r = env.client.patch(f"{BASE}/{cid}", json={"status": "live"})
    assert r.status_code == 409
    assert env.client.get(f"{BASE}/{cid}").json()["status"] == "paused"


def test_delete_permanently_removes_the_character(env):
    cid = _live(env)
    assert env.client.delete(f"{BASE}/{cid}").status_code == 204
    assert env.client.get(f"{BASE}/{cid}").status_code == 404
    assert _names(env) == [] and _names(env, archived="true") == []


def test_restore_or_archive_twice_is_harmless(env):
    cid = _live(env)
    assert env.client.post(f"{BASE}/{cid}/restore").status_code == 200   # already active
    assert env.client.post(f"{BASE}/{cid}/archive").status_code == 200
    first = env.client.get(f"{BASE}/{cid}").json()["archived_at"]
    assert env.client.post(f"{BASE}/{cid}/archive").status_code == 200
    assert env.client.get(f"{BASE}/{cid}").json()["archived_at"] == first   # date kept


def test_another_businesss_character_is_404_and_untouched(env):
    other = env.db.add("companions", tenant_id="t2", name="Their bot", status="live")
    for method, path in (("post", "archive"), ("post", "restore"), ("delete", "")):
        url = f"{BASE}/{other['id']}" + (f"/{path}" if path else "")
        assert getattr(env.client, method)(url).status_code == 404
    row = [r for r in env.db.tables["companions"] if r["id"] == other["id"]]
    assert row and row[0]["status"] == "live" and not row[0].get("archived_at")


def test_overview_does_not_count_archived_characters(env):
    cid = _live(env)
    _live(env, "Vastu Guru")
    env.client.post(f"{BASE}/{cid}/archive")
    counts = env.client.get(f"{BASE}/overview").json()
    assert counts["live_characters"] == 1 and counts["characters"] == 1


def test_reusing_an_archived_characters_name_says_so(env, monkeypatch):
    cid = _live(env)
    env.client.post(f"{BASE}/{cid}/archive")

    async def clash(tenant_id, settings):   # the fake has no unique index; the real one does
        raise store.DuplicateCompanionName(settings.name)
    monkeypatch.setattr(store, "create_companion", clash)
    r = env.client.post(BASE, json={"name": "Jothidar AI"})
    assert r.status_code == 409 and "archived character" in r.json()["detail"]


def test_memory_privacy_and_forget_still_see_archived_characters(env):
    # A private (mode B) character that is archived must stay private, and "forget this person"
    # must still reach its memory: internal callers get every character.
    import asyncio
    cid = _live(env)
    env.client.post(f"{BASE}/{cid}/archive")
    every = asyncio.run(store.list_companions("t1"))
    assert [c["id"] for c in every] == [cid]


def test_an_archived_character_never_answers_even_if_status_says_live(env):
    # Defence in depth: a PATCH racing an archive could leave status "live" with archived_at set.
    import asyncio
    from app.companion import engine
    cid = _live(env)
    env.client.post(f"{BASE}/{cid}/archive")
    row = [r for r in env.db.tables["companions"] if r["id"] == cid][0]
    row["status"] = "live"
    with pytest.raises(engine.CompanionPaused):
        asyncio.run(engine._live_companion("t1", cid, require_live=True))
