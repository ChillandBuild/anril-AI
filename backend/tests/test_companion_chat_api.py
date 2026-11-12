"""companion-chat-api: secret keys, signed user ids, the public chat API and the Install tab."""
import json
import logging
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import engine, keys, store
from app.routes import companion_public, companions
from tests.fake_supabase import FakeSupabase
from tests.test_companion_tools import ARGS, CHART, GET_CHART, call

SECRET_TEXT = "my birth time is 4:35 am in Madurai"
PUB = "/api/v1/companion"
DASH = "/api/v1/companions"


# --- signing (pure) ---------------------------------------------------------------------------

def test_signature_round_trip_and_every_way_to_break_it():
    h = keys.hash_key("acs_live_abc")
    exp = int(time.time()) + 3600
    sig = keys.sign_user(h, "48213", exp)
    assert keys.check_signature([("k1", h)], "48213", exp, sig) == "k1"
    assert keys.check_signature([("k1", h)], "48214", exp, sig) is None                 # other user
    assert keys.check_signature([("k1", h)], "48213", exp + 1, sig) is None             # exp changed
    assert keys.check_signature([("k2", keys.hash_key("acs_live_other"))], "48213", exp, sig) is None
    past = int(time.time()) - 1
    assert keys.check_signature([("k1", h)], "48213", past, keys.sign_user(h, "48213", past)) is None
    far = int(time.time()) + keys.MAX_SIGNATURE_LIFETIME + 60
    assert keys.check_signature([("k1", h)], "48213", far, keys.sign_user(h, "48213", far)) is None
    assert keys.check_signature([("k1", h)], "48213", exp, "zz" * 32) is None
    assert keys.check_signature([("old", keys.hash_key("x")), ("new", h)], "48213", exp, sig.upper()) == "new"


def test_owner_test_people_and_odd_ids_are_not_valid_user_ids():
    assert keys.valid_user_id("48213") and keys.valid_user_id("karthik@astrotamil.com")
    for bad in ["owner-test:u1", "", " 48213", "48213\n", "a/b", "x" * 129, "தமிழ்"]:
        assert not keys.valid_user_id(bad)
    h = keys.hash_key("acs_live_abc")
    exp = int(time.time()) + 60
    assert keys.check_signature([("k1", h)], "owner-test:u1", exp, keys.sign_user(h, "owner-test:u1", exp)) is None


def test_generated_keys_have_the_prefix_and_hash():
    raw, prefix, h = keys.generate_key()
    assert raw.startswith("acs_live_") and prefix == raw[:13] and h == keys.hash_key(raw) and len(h) == 64
    assert keys.looks_like_key(raw) and not keys.looks_like_key("aps_live_x") and not keys.looks_like_key("")


# --- fixtures ---------------------------------------------------------------------------------

@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(companions, "get_supabase", lambda: fake)
    state = {"script": [], "audit": []}
    monkeypatch.setattr(engine.ai_reply, "_resolve_provider", lambda t: ("groq", "m"))

    async def with_tools(messages, tools, max_tokens=300, tenant_id=None, *, purpose="ai_reply"):
        return state["script"].pop(0)

    async def plain(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4):
        return "[mood: warm] Vanakkam Karthik!"

    async def kb(tenant_id, collection_id, message, history=None, *, companion_id=None, rewrite=None):
        return None
    monkeypatch.setattr(engine.ai_reply, "_llm_chat_with_tools", with_tools)
    monkeypatch.setattr(engine.ai_reply, "_llm_chat", plain)
    monkeypatch.setattr(engine.kb_search, "search", kb)
    monkeypatch.setattr(companions, "record_audit_event", lambda db, **kw: state["audit"].append(kw))
    for limiter in (companion_public._ip_limiter, companion_public._tenant_limiter,
                    companion_public._person_limiter, companions._key_limiter):
        limiter._hits.clear()
    companion_public._last_touch.clear()

    card = dict(default_mood="calm", language="ta-en", memory_level=1, knowledge_tag_id=None,
                sample_lines=[], goals=[], rules=[], industry="astrology")
    live = fake.add("companions", tenant_id="t1", name="Jothidar AI", status="live", **card)
    draft = fake.add("companions", tenant_id="t1", name="Vastu Guru", status="draft", **card)
    other = fake.add("companions", tenant_id="t2", name="Rival AI", status="live", **card)

    def make_key(tenant):
        raw, prefix, h = keys.generate_key()
        row = fake.add("companion_api_keys", tenant_id=tenant, key_prefix=prefix, key_hash=h, status="active")
        return raw, h, row

    t1_key, t1_hash, t1_row = make_key("t1")
    t2_key, t2_hash, _ = make_key("t2")

    app = FastAPI()
    app.include_router(companion_public.public_router, prefix=PUB)
    app.include_router(companions.router, prefix=DASH)
    app.dependency_overrides[companions.require_companions_manage] = \
        lambda: {"tenant_id": "t1", "user_id": "u1", "role": "owner"}
    return type("Env", (), dict(db=fake, state=state, live=live, draft=draft, other=other, key=t1_key,
                                hash=t1_hash, key_row=t1_row, t2_key=t2_key, t2_hash=t2_hash,
                                client=TestClient(app)))


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def signed(env, user="48213", key_hash=None, cid=None, exp=None):
    exp = exp or int(time.time()) + 3600
    return {"companion_id": cid or env.live["id"], "user_id": user, "exp": exp,
            "signature": keys.sign_user(key_hash or env.hash, user, exp)}


# --- dashboard: keys and install --------------------------------------------------------------

def test_create_key_shows_it_once_stores_only_the_hash_and_audits_the_prefix(env):
    r = env.client.post(f"{DASH}/keys")
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    body = r.json()
    raw = body["key"]
    assert raw.startswith("acs_live_") and body["key_prefix"] == raw[:13]
    row = next(k for k in env.db.rows("companion_api_keys") if k["id"] == body["id"])
    assert row["key_hash"] == keys.hash_key(raw) and raw not in json.dumps(row)
    assert env.state["audit"][-1]["action"] == "tenant.companion_key_created"
    assert raw not in json.dumps(env.state["audit"]) and row["key_hash"] not in json.dumps(env.state["audit"])

    listed = env.client.get(f"{DASH}/keys").json()["keys"]
    assert {k["id"] for k in listed} == {body["id"], env.key_row["id"]}
    assert "key_hash" not in json.dumps(listed) and raw not in json.dumps(listed)


def test_third_active_key_is_refused_and_revoke_frees_a_slot(env):
    assert env.client.post(f"{DASH}/keys").status_code == 201
    assert env.client.post(f"{DASH}/keys").status_code == 409
    assert env.client.delete(f"{DASH}/keys/{env.key_row['id']}").status_code == 204
    assert env.client.delete(f"{DASH}/keys/{env.key_row['id']}").status_code == 404      # already revoked
    assert env.client.post(f"{DASH}/keys").status_code == 201


def test_cannot_revoke_another_businesss_key(env):
    t2_row = next(k for k in env.db.rows("companion_api_keys") if k["tenant_id"] == "t2")
    assert env.client.delete(f"{DASH}/keys/{t2_row['id']}").status_code == 404
    assert t2_row["status"] == "active"


def test_key_changes_are_rate_limited_per_business(env):
    codes = [env.client.delete(f"{DASH}/keys/00000000-0000-0000-0000-000000000000").status_code
             for _ in range(6)]
    assert codes[:5] == [404] * 5 and codes[5] == 429


def test_revoked_key_stops_the_api_and_its_widgets_at_once(env):
    env.client.delete(f"{DASH}/keys/{env.key_row['id']}")
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "hi"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_key"
    r = env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": "hi"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_signature"


def test_install_gives_snippets_with_the_character_id_and_no_secret(env):
    r = env.client.get(f"{DASH}/{env.live['id']}/install")
    assert r.status_code == 200
    info = r.json()
    assert info["has_active_key"] is True and info["widget_script_url"].endswith("/companion-widget.js")
    assert set(info["snippets"]) == {"html", "python", "node", "curl"}
    assert env.live["id"] in info["snippets"]["html"] and env.live["id"] in info["snippets"]["curl"]
    assert "acs_live_" in info["snippets"]["python"] and env.key not in json.dumps(info)
    assert env.client.get(f"{DASH}/{env.other['id']}/install").status_code == 404


def test_install_snippet_signature_matches_what_the_api_checks(env):
    """Run the Python snippet exactly as a client would paste it."""
    snippet = env.client.get(f"{DASH}/{env.live['id']}/install").json()["snippets"]["python"]
    ns: dict = {}
    import os
    os.environ["ANRIL_COMPANION_KEY"] = env.key
    try:
        exec(snippet, ns)
        out = ns["companion_signature"]("48213")
    finally:
        del os.environ["ANRIL_COMPANION_KEY"]
    r = env.client.post(f"{PUB}/widget/session", json={"companion_id": env.live["id"], "user_id": out["userId"],
                                                        "exp": out["exp"], "signature": out["signature"]})
    assert r.status_code == 200


# --- public: server to server -----------------------------------------------------------------

def test_server_chat_takes_the_tenant_from_the_key(env):
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "Vanakkam",
                              "display_name": "Karthik"})
    assert r.status_code == 200 and r.json()["text"] == "Vanakkam Karthik!"
    person = env.db.rows("companion_end_users")[0]
    assert person["tenant_id"] == "t1" and person["external_user_id"] == "48213"
    assert next(k for k in env.db.rows("companion_api_keys") if k["id"] == env.key_row["id"]).get("last_used_at")


@pytest.mark.parametrize("headers, code", [
    ({}, "invalid_key"),
    ({"Authorization": "Bearer acs_live_wrong"}, "invalid_key"),
    ({"Authorization": "Basic abc"}, "invalid_key"),
])
def test_server_chat_without_a_good_key_is_401(env, headers, code):
    r = env.client.post(f"{PUB}/chat", headers=headers,
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "hi"})
    assert r.status_code == 401 and r.json()["code"] == code


def test_one_businesss_key_cannot_reach_another_businesss_character(env):
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.t2_key),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "hi"})
    assert r.status_code == 404 and r.json()["code"] == "companion_not_found"
    assert env.db.rows("companion_messages") == []


def test_tenant_id_in_the_body_is_rejected_not_used(env):
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "hi", "tenant_id": "t2"})
    assert r.status_code == 422


def test_drafts_do_not_answer_end_users(env):
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.draft["id"], "user_id": "48213", "message": "hi"})
    assert r.status_code == 409 and r.json()["code"] == "companion_not_live"


def test_owner_test_user_ids_and_blank_messages_are_refused(env):
    base = {"companion_id": env.live["id"], "message": "hi"}
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key), json={**base, "user_id": "owner-test:u1"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_user_id"
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key), json={**base, "user_id": "48213", "message": "   "})
    assert r.status_code == 422 and r.json()["code"] == "empty_message"


def test_server_tool_round_trip_and_the_turn_belongs_to_its_person(env):
    env.state["script"] = [("", [call()]), ("[mood: warm] Ungal lagnam Kumbham.", [])]
    first = env.client.post(f"{PUB}/chat", headers=bearer(env.key), json={
        "companion_id": env.live["id"], "user_id": "48213", "message": "En jathagam",
        "tools": [GET_CHART.model_dump()]}).json()
    assert first["status"] == "tool_call" and first["tool_calls"][0]["args"] == ARGS

    # Another person of the same business can't finish Karthik's turn (and it is used up).
    env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                    json={"companion_id": env.live["id"], "user_id": "99999", "message": "hi"})
    stolen = env.client.post(f"{PUB}/chat/continue", headers=bearer(env.key), json={
        "user_id": "99999", "turn_id": first["turn_id"], "results": [{"id": "call_1", "output": CHART}]})
    assert stolen.status_code == 404 and stolen.json()["code"] == "turn_expired"


def test_server_continue_finishes_the_reply(env):
    env.state["script"] = [("", [call()]), ("[mood: warm] Ungal lagnam Kumbham.", [])]
    first = env.client.post(f"{PUB}/chat", headers=bearer(env.key), json={
        "companion_id": env.live["id"], "user_id": "48213", "message": "En jathagam",
        "tools": [GET_CHART.model_dump()]}).json()
    done = env.client.post(f"{PUB}/chat/continue", headers=bearer(env.key), json={
        "user_id": "48213", "turn_id": first["turn_id"], "results": [{"id": "call_1", "output": CHART}]})
    assert done.status_code == 200 and done.json()["text"] == "Ungal lagnam Kumbham."


def test_busy_engine_is_503_try_again(env, monkeypatch):
    async def busy(*a, **kw):
        raise engine.CompanionBusy("x")
    monkeypatch.setattr(engine, "reply", busy)
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                        json={"companion_id": env.live["id"], "user_id": "48213", "message": "hi"})
    assert r.status_code == 503 and r.json()["code"] == "busy" and r.headers["retry-after"] == "5"


def test_per_person_rate_limit(env):
    body = {"companion_id": env.live["id"], "user_id": "48213", "message": "hi"}
    codes = [env.client.post(f"{PUB}/chat", headers=bearer(env.key), json=body).status_code
             for _ in range(companion_public.PERSON_PER_MINUTE + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {200}
    other = env.client.post(f"{PUB}/chat", headers=bearer(env.key), json={**body, "user_id": "77"})
    assert other.status_code == 200



def test_a_person_over_their_limit_does_not_use_up_the_business_budget(env):
    body = {"companion_id": env.live["id"], "user_id": "48213", "message": "hi"}
    for _ in range(companion_public.PERSON_PER_MINUTE + 10):
        env.client.post(f"{PUB}/chat", headers=bearer(env.key), json=body)
    assert len(companion_public._tenant_limiter._hits["t1"]) == companion_public.PERSON_PER_MINUTE

# --- public: widget ---------------------------------------------------------------------------

def test_widget_session_returns_name_and_this_persons_history_only(env):
    env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": "Vanakkam"})
    env.client.post(f"{PUB}/widget/chat", json={**signed(env, user="55555"), "message": SECRET_TEXT})
    r = env.client.post(f"{PUB}/widget/session", json=signed(env))
    assert r.status_code == 200
    body = r.json()
    assert body["companion"] == {"name": "Jothidar AI", "language": "ta-en"}
    assert [m["content"] for m in body["messages"]] == ["Vanakkam", "Vanakkam Karthik!"]
    assert SECRET_TEXT not in r.text


def test_widget_first_visit_has_no_history_and_creates_nothing(env):
    r = env.client.post(f"{PUB}/widget/session", json=signed(env, user="new1"))
    assert r.status_code == 200 and r.json()["messages"] == []
    assert env.db.rows("companion_end_users") == []


def test_widget_chat_with_a_good_signature(env):
    r = env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": "Vanakkam", "display_name": "Karthik"})
    assert r.status_code == 200 and r.json()["text"] == "Vanakkam Karthik!"
    assert env.db.rows("companion_end_users")[0]["tenant_id"] == "t1"


def test_widget_forged_user_id_is_401(env):
    body = {**signed(env), "message": "hi"}
    body["user_id"] = "48214"                       # Karthik edits the page to read someone else's chat
    r = env.client.post(f"{PUB}/widget/chat", json=body)
    assert r.status_code == 401 and r.json()["code"] == "invalid_signature"
    assert env.client.post(f"{PUB}/widget/session", json={**signed(env), "user_id": "48214"}).status_code == 401


def test_widget_signed_by_another_business_cannot_use_this_character(env):
    r = env.client.post(f"{PUB}/widget/chat", json={**signed(env, key_hash=env.t2_hash), "message": "hi"})
    assert r.status_code == 401


def test_widget_unknown_character_looks_like_a_bad_signature(env):
    r = env.client.post(f"{PUB}/widget/chat",
                        json={**signed(env, cid="00000000-0000-0000-0000-000000000000"), "message": "hi"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_signature"


def test_widget_expired_signature_is_401(env):
    past = int(time.time()) - 5
    r = env.client.post(f"{PUB}/widget/chat", json={**signed(env, exp=past), "message": "hi"})
    assert r.status_code == 401


def test_widget_draft_character_is_409(env):
    r = env.client.post(f"{PUB}/widget/session", json=signed(env, cid=env.draft["id"]))
    assert r.status_code == 409


def test_widget_tool_round_trip(env):
    env.state["script"] = [("", [call()]), ("[mood: warm] Ungal lagnam Kumbham.", [])]
    first = env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": "En jathagam",
                                                        "tools": [GET_CHART.model_dump()]}).json()
    assert first["status"] == "tool_call"
    stolen = env.client.post(f"{PUB}/widget/chat/continue", json={
        **signed(env, user="99999"), "turn_id": first["turn_id"], "results": []})
    assert stolen.status_code == 404
    env.state["script"] = [("", [call()]), ("[mood: warm] Ungal lagnam Kumbham.", [])]
    first = env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": "En jathagam",
                                                        "tools": [GET_CHART.model_dump()]}).json()
    done = env.client.post(f"{PUB}/widget/chat/continue", json={
        **signed(env), "turn_id": first["turn_id"], "results": [{"id": "call_1", "output": CHART}]})
    assert done.status_code == 200 and done.json()["text"] == "Ungal lagnam Kumbham."


def test_logs_hold_no_message_text_or_keys(env, caplog):
    caplog.set_level(logging.DEBUG)
    env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                    json={"companion_id": env.live["id"], "user_id": "48213", "message": SECRET_TEXT})
    env.client.post(f"{PUB}/widget/chat", json={**signed(env), "message": SECRET_TEXT})
    created = env.client.post(f"{DASH}/keys").json()["key"]
    assert SECRET_TEXT not in caplog.text and env.key not in caplog.text and created not in caplog.text
