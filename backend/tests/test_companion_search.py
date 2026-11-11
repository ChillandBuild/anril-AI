"""companion-dashboard T9 + kb-reply T18 + Playground settings: the Playground "Search" tab. Knowledge
returns the passages the character's collection gives (book, pages, the judge's score, kept or
dropped); memories with a person run the live meaning + word search, without one they are word-matched
facts (privacy mode A only). Tenant-filtered, limit capped at 20, query text never logged."""
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import memory_embed, memory_search, store
from app.companion.kb import search as kb_search, store as kb_store
from app.companion.kb.types import KbResult, Passage
from app.routes import companions
from tests.fake_supabase import FakeSupabase

BASE = "/api/v1/companions"
SECRET_Q = "Zoho interview Meena"


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(kb_store, "get_supabase", lambda: fake)
    app = FastAPI()
    app.include_router(companions.router, prefix=BASE)
    app.dependency_overrides[companions.require_companions_manage] = lambda: {
        "tenant_id": "t1", "user_id": "u1", "role": "owner"}
    j = fake.add("companions", tenant_id="t1", name="Jothidar AI", status="live", privacy_mode="A",
                 knowledge_tag_id="tag-astro", knowledge_collection_id="col-astro")
    private = fake.add("companions", tenant_id="t1", name="Diary", status="live", privacy_mode="B",
                       knowledge_collection_id="col-astro")
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
    assert body["memory_mode"] == "words"
    texts = [x["text"] for x in body["memories"]]
    # "Interview at Zoho" matches 2 words, then the 1-word matches newest first. No forgotten
    # person, no other character's facts, no other tenant's.
    assert texts == ["Interview at Zoho on 20 Nov", "New job at Zoho", "Sister Meena studies in Chennai"]
    assert body["memories"][0]["external_user_id"] == "48213"
    assert body["memories"][0]["display_name"] == "Karthik"
    assert body["memories"][0]["kind"] == "fact" and body["memories"][0]["day"] == "2026-11-05"
    assert SECRET_Q not in caplog.text and "Zoho" not in caplog.text


def _chunks(monkeypatch, rows):
    """match_memory_chunks returns these rows; the query embedding is a dummy vector."""
    seen = {}

    async def match(tenant_id, companions, end_user_id, embedding, query, count):
        seen.update(tenant_id=tenant_id, end_user_id=end_user_id, query=query)
        return rows

    async def embed(texts, kind, tenant_id, **k):
        seen["embedded"] = list(texts)
        return [[0.1] * 4 for _ in texts]
    monkeypatch.setattr(store, "match_chunks", match)
    monkeypatch.setattr(memory_embed, "embed", embed)
    return seen


ROWS = [
    {"id": "m1", "kind": "fact", "day": "2026-11-02", "text": "Bought running shoes size 9", "source": "vector", "score": 0.83},
    {"id": "m2", "kind": "messages", "day": "2026-11-09", "text": "Person: the shoes hurt\nCharacter: sorry!",
     "source": "vector", "score": 0.76},
    {"id": "m3", "kind": "fact", "day": "2026-10-12", "text": "Lives in Coimbatore", "source": "vector", "score": 0.55},
]


def test_memories_for_one_person_use_the_live_meaning_search(env, monkeypatch):
    seen = _chunks(monkeypatch, ROWS)
    r = _post(env, env.j["id"], **{"in": "memories", "q": "shoe return", "external_user_id": "48213"})
    body = r.json()
    assert body["memory_mode"] == "meaning"
    assert seen["embedded"] == ["shoe return"]                 # the typed text alone, no recent chat
    assert [(m["text"], m["kept"]) for m in body["memories"]] == [
        ("Bought running shoes size 9", True), ("the shoes hurt", True),   # only what the person said
        ("Lives in Coimbatore", False)]                                    # below the live 0.70 floor
    assert body["memories"][0]["meaning"] == 0.83 and body["memories"][1]["kind"] == "messages"


def test_strictness_setting_moves_the_floor_for_this_request_only(env, monkeypatch):
    _chunks(monkeypatch, ROWS)
    body = {"in": "memories", "q": "shoes", "external_user_id": "48213"}
    loose = _post(env, env.j["id"], **body, settings={"memory_floor": 0.5}).json()
    assert [m["kept"] for m in loose["memories"]] == [True, True, True]
    strict = _post(env, env.j["id"], **body, settings={"memory_floor": 0.8}).json()
    assert [m["kept"] for m in strict["memories"]] == [True, False, False]
    again = _post(env, env.j["id"], **body).json()             # no settings: the live floor again
    assert [m["kept"] for m in again["memories"]] == [True, True, False]
    assert memory_search.VECTOR_FLOOR == 0.70


def test_memories_for_an_unknown_or_forgotten_person_404(env):
    assert _post(env, env.j["id"], **{"in": "memories", "q": "zoho", "external_user_id": "nobody"}).status_code == 404
    assert _post(env, env.j["id"], **{"in": "memories", "q": "zoho", "external_user_id": "99999"}).status_code == 404


def test_memories_blocked_in_privacy_mode_b_and_other_tenant(env):
    assert _post(env, env.private["id"], **{"in": "memories", "q": "zoho"}).status_code == 403
    assert _post(env, env.t2["id"], **{"in": "memories", "q": "zoho"}).status_code == 404


MAIN = Passage(id="c1", document_id="d1", document_title="Main resource", tier=1,
               heading_path="Seventh House > Saturn", text="Saturn in the 7th delays marriage",
               page_from=12, page_to=12, score=3)
BOOK7 = Passage(id="c2", document_id="d7", document_title="Book 7", tier=2, heading_path="",
                text="Saturn return", page_from=212, page_to=213, score=2)


def test_knowledge_searches_the_characters_collection_and_names_book_and_pages(env, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    async def fake_search(tenant_id, collection_id, message, history=None, *, companion_id=None):
        calls.append((tenant_id, collection_id, message, history, companion_id))
        return KbResult(passages=(MAIN, BOOK7), topic="Saturn in the seventh house")

    monkeypatch.setattr(kb_search, "search", fake_search)
    r = _post(env, env.j["id"], **{"in": "knowledge", "q": SECRET_Q, "limit": 1})
    assert r.status_code == 200
    assert calls == [("t1", "col-astro", SECRET_Q, [], env.j["id"])]       # the collection, not the old tag
    body = r.json()
    assert body["in"] == "knowledge" and body["needs_docs"] is True and body["memories"] == []
    assert body["knowledge"] == [
        {"document": "Main resource", "page_from": 12, "page_to": 12, "heading_path": "Seventh House > Saturn",
         "text": "Saturn in the 7th delays marriage", "tier": 1, "step": "main", "score": 3, "meaning": None,
         "kept": True}]                                                       # limit 1: Book 7 cut
    assert len(_post(env, env.j["id"], **{"in": "knowledge", "q": SECRET_Q}).json()["knowledge"]) == 2
    assert SECRET_Q not in caplog.text


def test_knowledge_small_talk_says_the_books_were_not_needed(env, monkeypatch):
    async def small_talk(*a, **k):
        return KbResult(needs_docs=False)
    monkeypatch.setattr(kb_search, "search", small_talk)
    body = _post(env, env.j["id"], **{"in": "knowledge", "q": "vanakkam"}).json()
    assert body["knowledge"] == [] and body["needs_docs"] is False


def test_knowledge_works_in_privacy_mode_b_and_404s_other_tenant(env, monkeypatch):
    calls = []

    async def nothing(*a, **k):
        calls.append(a)
        return KbResult()
    monkeypatch.setattr(kb_search, "search", nothing)
    body = _post(env, env.private["id"], **{"in": "knowledge", "q": "rasi"}).json()
    assert body["knowledge"] == [] and body["needs_docs"] is True
    assert len(calls) == 1
    assert _post(env, env.t2["id"], **{"in": "knowledge", "q": "rasi"}).status_code == 404
    assert len(calls) == 1                                   # another business's character: never searched


def test_knowledge_for_a_character_with_no_collection_is_empty_and_not_searched(env, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("must not search")
    monkeypatch.setattr(kb_search, "search", boom)
    loner = env.db.add("companions", tenant_id="t1", name="Loner", status="live", knowledge_tag_id="tag-astro")
    body = _post(env, loner["id"], **{"in": "knowledge", "q": "rasi"}).json()
    assert body["knowledge"] == [] and body["no_collection"] is True


@pytest.mark.parametrize("broken", ["raises", "failed"])
def test_knowledge_error_is_502_without_query_text(env, monkeypatch, caplog, broken):
    async def boom(*a, **k):
        if broken == "raises":
            raise RuntimeError(f"embedder down for {SECRET_Q}")
        return KbResult(failed=True)
    monkeypatch.setattr(kb_search, "search", boom)
    caplog.set_level(logging.DEBUG)
    r = _post(env, env.j["id"], **{"in": "knowledge", "q": SECRET_Q})
    assert r.status_code == 502
    assert SECRET_Q not in caplog.text and SECRET_Q not in r.text


# --- kb-reply T18: a character may only be pointed at its own business's collection ------------------

def test_character_collection_must_belong_to_the_business(env):
    mine = env.db.add("companion_kb_collections", tenant_id="t1", name="Astrology books")
    theirs = env.db.add("companion_kb_collections", tenant_id="t2", name="Their books")
    url = f"{BASE}/{env.j['id']}"
    assert env.client.patch(url, json={"knowledge_collection_id": theirs["id"]}).status_code == 422
    assert env.client.post(BASE, json={"name": "Vastu Guru", "knowledge_collection_id": theirs["id"]}).status_code == 422
    assert [c["name"] for c in env.db.rows("companions") if c["tenant_id"] == "t1"] == ["Jothidar AI", "Diary"]
    ok = env.client.patch(url, json={"knowledge_collection_id": mine["id"]})
    assert ok.status_code == 200 and ok.json()["knowledge_collection_id"] == mine["id"]
    cleared = env.client.patch(url, json={"knowledge_collection_id": None})
    assert cleared.status_code == 200 and cleared.json()["knowledge_collection_id"] is None
    made = env.client.post(BASE, json={"name": "Vastu Guru", "knowledge_collection_id": mine["id"]})
    assert made.status_code == 201 and made.json()["knowledge_collection_id"] == mine["id"]


@pytest.mark.parametrize("body", [
    {"in": "memories", "q": "x", "limit": 21},
    {"in": "memories", "q": "x", "limit": 0},
    {"in": "chats", "q": "x"},
    {"in": "memories", "q": ""},
    {"in": "memories", "q": "x" * 501},
    {"in": "memories", "q": "x", "tenant_id": "t2"},
    {"in": "memories", "q": "x", "settings": {"memory_floor": 1.5}},
    {"in": "memories", "q": "x", "settings": {"judge_min": 4}},
    {"in": "memories", "q": "x", "settings": {"mode": "magic"}},
    {"in": "memories", "q": "x", "settings": {"unknown": 1}},
])
def test_input_is_validated(env, body):
    assert _post(env, env.j["id"], **body).status_code == 422


def test_search_words():
    assert store.search_words("Karthik's job?  a JOB") == ["karthik", "job"]
    assert store.search_words("!!") == []
    assert len(store.search_words(" ".join(f"w{i}" for i in range(20)))) == 8


def test_business_scope_never_shows_the_owner_what_a_private_character_learned(env, monkeypatch):
    rows = [dict(ROWS[0], companion_id=env.j["id"]),
            {"id": "p1", "companion_id": env.private["id"], "kind": "messages", "day": "2026-11-08",
             "text": "Person: my secret diary line", "source": "vector", "score": 0.9}]
    _chunks(monkeypatch, rows)
    body = _post(env, env.j["id"], **{"in": "memories", "q": "diary", "external_user_id": "48213"}).json()
    assert [m["text"] for m in body["memories"]] == ["Bought running shoes size 9"]


def test_default_settings_keep_the_live_passage_counts(env, monkeypatch):
    from app.companion import playground
    seen = {}

    async def fake_search(*a, **k):
        seen["results"] = playground.current().results
        return KbResult(passages=(MAIN,))
    monkeypatch.setattr(kb_search, "search", fake_search)
    _post(env, env.j["id"], **{"in": "knowledge", "q": "x", "limit": 5})
    assert seen["results"] is None                                   # live 3 / 4, not the limit
    _post(env, env.j["id"], **{"in": "knowledge", "q": "x", "settings": {"results": 2}})
    assert seen["results"] == 2


def test_all_keeps_memories_when_knowledge_fails(env, monkeypatch):
    async def broken(*a, **k):
        return KbResult(failed=True)
    monkeypatch.setattr(kb_search, "search", broken)
    r = _post(env, env.j["id"], **{"in": "all", "q": "zoho"})
    assert r.status_code == 200 and r.json()["knowledge_error"] is True and r.json()["memories"]
