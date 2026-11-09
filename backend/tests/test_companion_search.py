"""companion-dashboard T9: the Playground "Search" tab. Knowledge returns chunks with a score from
the character's tag; memories returns word-matched facts (privacy mode A only). Tenant-filtered,
limit capped at 20, query text never logged."""
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store
from app.routes import companions
from app.services import knowledge_service
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"
SECRET_Q = "Zoho interview Meena"


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(knowledge_service, "get_supabase", lambda: fake)
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[companions.require_companions_manage] = lambda: {
        "tenant_id": "t1", "user_id": "u1", "role": "owner"}
    j = fake.add("companions", tenant_id="t1", name="Jothidar AI", status="live", privacy_mode="A",
                 knowledge_tag_id="tag-astro")
    private = fake.add("companions", tenant_id="t1", name="Diary", status="live", privacy_mode="B")
    karthik = fake.add("companion_end_users", tenant_id="t1", external_user_id="48213", display_name="Karthik")
    priya = fake.add("companion_end_users", tenant_id="t1", external_user_id="77001", display_name="Priya")
    gone = fake.add("companion_end_users", tenant_id="t1", external_user_id="99999",
                    forgotten_at="2026-11-01T00:00:00+00:00")
    fact = lambda person, text, at, char=j: fake.add(  # noqa: E731
        "companion_memory_facts", tenant_id="t1", companion_id=char["id"], end_user_id=person["id"],
        section="life", text=text, status="active", created_at=at)
    fact(karthik, "Interview at Zoho on 20 Nov", "2026-11-05T00:00:00+00:00")
    fact(karthik, "Sister Meena studies in Chennai", "2026-11-01T00:00:00+00:00")
    fact(priya, "New job at Zoho", "2026-11-07T00:00:00+00:00")
    fact(priya, "Likes short answers", "2026-11-07T00:00:00+00:00")
    fact(gone, "Zoho interview too", "2026-11-08T00:00:00+00:00")
    fact(karthik, "Zoho in the private diary", "2026-11-08T00:00:00+00:00", char=private)
    t2 = fake.add("companions", tenant_id="t2", name="Their bot", status="live", privacy_mode="A")
    fake.add("companion_memory_facts", tenant_id="t2", companion_id=t2["id"], end_user_id=karthik["id"],
             section="life", text="Zoho other tenant", status="active", created_at="2026-11-09T00:00:00+00:00")
    fake.add("knowledge_documents", id="doc-1", tenant_id="t1", name="Rasi palan.pdf")
    fake.add("knowledge_documents", id="doc-2", tenant_id="t2", name="Not yours.pdf")
    return type("Env", (), {"client": TestClient(app), "db": fake, "j": j, "private": private, "t2": t2})


def _post(env, cid, **body):
    return env.client.post(f"{BASE}/{cid}/search", json=body)


def test_memories_word_match_best_first_and_skips_forgotten(env, caplog):
    caplog.set_level(logging.DEBUG)
    r = _post(env, env.j["id"], **{"in": "memories", "q": SECRET_Q})
    assert r.status_code == 200
    body = r.json()
    assert body["in"] == "memories"
    texts = [x["text"] for x in body["results"]]
    # "Interview at Zoho" matches 2 words, then the 1-word matches newest first. No forgotten
    # person, no other character's facts, no other tenant's.
    assert texts == ["Interview at Zoho on 20 Nov", "New job at Zoho", "Sister Meena studies in Chennai"]
    assert body["results"][0]["external_user_id"] == "48213"
    assert body["results"][0]["display_name"] == "Karthik"
    assert "similarity" not in body["results"][0]
    assert SECRET_Q not in caplog.text and "Zoho" not in caplog.text


def test_memories_for_one_person(env):
    r = _post(env, env.j["id"], **{"in": "memories", "q": "zoho", "external_user_id": "77001"})
    assert [x["text"] for x in r.json()["results"]] == ["New job at Zoho"]
    assert _post(env, env.j["id"], **{"in": "memories", "q": "zoho", "external_user_id": "nobody"}).status_code == 404
    assert _post(env, env.j["id"], **{"in": "memories", "q": "zoho", "external_user_id": "99999"}).status_code == 404


def test_memories_blocked_in_privacy_mode_b_and_other_tenant(env):
    assert _post(env, env.private["id"], **{"in": "memories", "q": "zoho"}).status_code == 403
    assert _post(env, env.t2["id"], **{"in": "memories", "q": "zoho"}).status_code == 404


def test_knowledge_uses_character_tag_and_names_documents(env, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    async def fake_semantic(db, tenant_id, query, tag, match_count):
        calls.append((tenant_id, query, tag, match_count))
        return [{"document_id": "doc-1", "content": "Kumbham rasi this week", "similarity": 0.82},
                {"document_id": "doc-2", "content": "leak?", "similarity": 0.5}]

    monkeypatch.setattr(knowledge_service, "_semantic_search", fake_semantic)
    r = _post(env, env.j["id"], **{"in": "knowledge", "q": SECRET_Q, "limit": 3})
    assert r.status_code == 200
    assert calls == [("t1", SECRET_Q, "tag-astro", 3)]
    res = r.json()["results"]
    assert res[0] == {"content": "Kumbham rasi this week", "similarity": 0.82, "document_name": "Rasi palan.pdf"}
    assert res[1]["document_name"] is None   # another tenant's document name never leaks
    assert SECRET_Q not in caplog.text


def test_knowledge_works_in_privacy_mode_b_and_404s_other_tenant(env, monkeypatch):
    async def fake_semantic(*a):
        return []
    monkeypatch.setattr(knowledge_service, "_semantic_search", fake_semantic)
    assert _post(env, env.private["id"], **{"in": "knowledge", "q": "rasi"}).json() == {"in": "knowledge", "results": []}
    assert _post(env, env.t2["id"], **{"in": "knowledge", "q": "rasi"}).status_code == 404


def test_knowledge_error_is_502_without_query_text(env, monkeypatch, caplog):
    async def boom(*a):
        raise RuntimeError(f"jina down for {SECRET_Q}")
    monkeypatch.setattr(knowledge_service, "_semantic_search", boom)
    caplog.set_level(logging.DEBUG)
    r = _post(env, env.j["id"], **{"in": "knowledge", "q": SECRET_Q})
    assert r.status_code == 502
    assert SECRET_Q not in caplog.text and SECRET_Q not in r.text


@pytest.mark.parametrize("body", [
    {"in": "memories", "q": "x", "limit": 21},
    {"in": "memories", "q": "x", "limit": 0},
    {"in": "chats", "q": "x"},
    {"in": "memories", "q": ""},
    {"in": "memories", "q": "x" * 501},
    {"in": "memories", "q": "x", "tenant_id": "t2"},
])
def test_input_is_validated(env, body):
    assert _post(env, env.j["id"], **body).status_code == 422


def test_search_words():
    assert store.search_words("Karthik's job?  a JOB") == ["karthik", "job"]
    assert store.search_words("!!") == []
    assert len(store.search_words(" ".join(f"w{i}" for i in range(20)))) == 8
