"""Playground test customers, the memory line and "Save now" (app/companion/playground_people.py).

The dashboard login in the fixture is "u1" of tenant "t1": "You" = "owner-test:u1".
"""
import pytest

from app.companion import memory_refresh, playground_people
from tests.test_companion_chat_api import DASH, PUB, bearer, env  # noqa: F401  (env is a fixture)

YOU = "owner-test:u1"


def _people(env):
    return env.client.get(f"{DASH}/test-people").json()


def _add(env, name="Meena"):
    return env.client.post(f"{DASH}/test-people", json={"name": name})


def _level2(env, history=10):
    row = next(r for r in env.db.rows("companions") if r["id"] == env.live["id"])
    row.update(memory_level=2, history_messages=history)


# --- the list --------------------------------------------------------------------------------

def test_you_is_always_first_and_test_customers_follow(env):  # noqa: F811
    assert _people(env) == {"people": [{"external_user_id": YOU, "name": "You", "is_you": True}], "max": 10}
    r = _add(env, "  மீனா   அக்கா ")
    assert r.status_code == 201
    made = r.json()
    assert made["name"] == "மீனா அக்கா" and not made["is_you"]
    assert made["external_user_id"].startswith(YOU + ":t") and len(made["external_user_id"]) == len(YOU) + 8
    assert [p["name"] for p in _people(env)["people"]] == ["You", "மீனா அக்கா"]


def test_names_must_be_1_to_40_characters(env):  # noqa: F811
    assert _add(env, "   ").status_code == 422
    assert _add(env, "x" * 41).status_code == 422


def test_the_eleventh_test_customer_is_refused(env):  # noqa: F811
    for i in range(10):
        assert _add(env, f"Test {i}").status_code == 201
    r = _add(env, "One more")
    assert r.status_code == 409 and "Delete one" in r.json()["detail"]


def test_another_logins_test_customers_are_not_listed(env):  # noqa: F811
    env.db.add("companion_end_users", tenant_id="t1", external_user_id="owner-test:u2:tabc123", display_name="Other")
    env.db.add("companion_end_users", tenant_id="t1", external_user_id="48213", display_name="Real customer")
    assert [p["name"] for p in _people(env)["people"]] == ["You"]


# --- chatting as one ---------------------------------------------------------------------------

def test_test_chat_as_a_test_customer_saves_under_that_person(env):  # noqa: F811
    pid = _add(env).json()["external_user_id"]
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "Vanakkam", "test_person": pid})
    assert r.status_code == 200
    person = next(p for p in env.db.rows("companion_end_users") if p["external_user_id"] == pid)
    assert {m["end_user_id"] for m in env.db.rows("companion_messages")} == {person["id"]}
    assert r.json()["memory"] == {"level": 1, "unread": 0, "saves_at": 8}


@pytest.mark.parametrize("pid", ["owner-test:u2:tabc123", "48213", "owner-test:u2", "owner-test:u1x"])
def test_test_chat_refuses_someone_elses_person(env, pid):  # noqa: F811
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "hi", "test_person": pid})
    assert r.status_code == 404 and env.db.rows("companion_messages") == []


def test_public_api_still_refuses_test_ids(env):  # noqa: F811
    body = {"companion_id": env.live["id"], "user_id": YOU + ":tabc123", "message": "hi"}
    assert env.client.post(f"{PUB}/chat", headers=bearer(env.key), json=body).status_code == 422


# --- delete and start over -----------------------------------------------------------------------

def test_delete_wipes_the_chat_and_leaves_the_list(env):  # noqa: F811
    pid = _add(env).json()["external_user_id"]
    env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "Vanakkam", "test_person": pid})
    r = env.client.delete(f"{DASH}/test-people/{pid}")
    assert r.status_code == 204
    assert env.db.rows("companion_messages") == []
    assert [p["name"] for p in _people(env)["people"]] == ["You"]
    assert env.state["audit"][-1]["metadata"] == {"test_person": True}
    # A deleted test customer can't be chatted as again.
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "hi", "test_person": pid})
    assert r.status_code == 404


def test_you_cant_be_deleted_and_others_are_404(env):  # noqa: F811
    assert env.client.delete(f"{DASH}/test-people/{YOU}").status_code == 400
    env.db.add("companion_end_users", tenant_id="t1", external_user_id="48213", display_name="Real customer")
    assert env.client.delete(f"{DASH}/test-people/48213").status_code == 404
    assert env.client.delete(f"{DASH}/test-people/owner-test:u2:tabc123").status_code == 404


def test_start_over_keeps_the_id_and_name_and_wipes_the_chat(env):  # noqa: F811
    made = _add(env).json()
    pid = made["external_user_id"]
    env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "Vanakkam", "test_person": pid})
    r = env.client.post(f"{DASH}/test-people/{pid}/start-over")
    assert r.status_code == 200 and r.json() == made
    assert env.db.rows("companion_messages") == []
    assert [p["name"] for p in _people(env)["people"]] == ["You", "Meena"]
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "hi", "test_person": pid})
    assert r.status_code == 200


def test_start_over_for_you_before_any_chat_is_fine(env):  # noqa: F811
    r = env.client.post(f"{DASH}/test-people/{YOU}/start-over")
    assert r.status_code == 200 and r.json()["is_you"]


# --- memory line and Save now --------------------------------------------------------------------

def test_memory_line_counts_unread_messages_for_level_2(env):  # noqa: F811
    _level2(env, history=10)
    url = f"{DASH}/{env.live['id']}/test-people/{YOU}/memory"
    assert env.client.get(url).json() == {"level": 2, "unread": 0, "saves_at": 8}
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "I live in Madurai"})
    assert r.json()["memory"] == {"level": 2, "unread": 2, "saves_at": 8}   # the message and the reply
    assert env.client.get(url).json()["unread"] == 2


def test_save_now_is_refused_for_level_1(env):  # noqa: F811
    r = env.client.post(f"{DASH}/{env.live['id']}/test-people/{YOU}/save-memory")
    assert r.status_code == 409


def test_save_now_runs_the_refresh_and_reports_facts(env, monkeypatch):  # noqa: F811
    _level2(env)
    env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "I live in Madurai"})
    seen = []

    async def save_now(companion, end_user_id):
        seen.append(end_user_id)
        env.db.add("companion_memory_facts", tenant_id="t1", companion_id=env.live["id"], end_user_id=end_user_id,
                   status="active", section="about", text="Lives in Madurai")
        return "ok"
    monkeypatch.setattr(memory_refresh, "save_now", save_now)
    r = env.client.post(f"{DASH}/{env.live['id']}/test-people/{YOU}/save-memory")
    assert r.status_code == 200 and r.json() == {"outcome": "saved", "facts": 1} and len(seen) == 1


@pytest.mark.parametrize("outcome,expected,status", [("busy", "busy", 200), ("waiting", "waiting", 200),
                                                     ("not_needed", "nothing_new", 200), ("failed", None, 502)])
def test_save_now_outcomes(env, monkeypatch, outcome, expected, status):  # noqa: F811
    _level2(env)
    env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "hi"})

    async def save_now(companion, end_user_id):
        return outcome
    monkeypatch.setattr(memory_refresh, "save_now", save_now)
    r = env.client.post(f"{DASH}/{env.live['id']}/test-people/{YOU}/save-memory")
    assert r.status_code == status
    if expected:
        assert r.json()["outcome"] == expected


def test_save_now_before_any_chat_has_nothing_new(env):  # noqa: F811
    _level2(env)
    r = env.client.post(f"{DASH}/{env.live['id']}/test-people/{YOU}/save-memory")
    assert r.json() == {"outcome": "nothing_new", "facts": 0}


def test_save_now_refuses_real_customers(env):  # noqa: F811
    _level2(env)
    assert env.client.post(f"{DASH}/{env.live['id']}/test-people/48213/save-memory").status_code == 404


def test_save_now_calls_the_refresh_with_threshold_one(monkeypatch):
    import asyncio
    calls = []

    async def run_claimed(companion, end_user_id, seconds, work):
        return await work()

    async def claimed(companion, end_user_id, threshold, now):
        calls.append(threshold)
        return "ok"
    monkeypatch.setattr(memory_refresh.memory_sweep, "run_claimed", run_claimed)
    monkeypatch.setattr(memory_refresh, "_claimed_refresh", claimed)
    assert asyncio.run(memory_refresh.save_now({"tenant_id": "t1", "id": "c1"}, "p1")) == "ok"
    assert calls == [1]


# --- Memories page -------------------------------------------------------------------------------

def test_people_list_marks_test_customers(env):  # noqa: F811
    pid = _add(env).json()["external_user_id"]
    env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "Vanakkam", "test_person": pid})
    env.client.post(f"{PUB}/chat", headers=bearer(env.key),
                    json={"companion_id": env.live["id"], "user_id": "48213", "message": "hi"})
    people = env.client.get(f"{DASH}/{env.live['id']}/people").json()["people"]
    assert {p["display_name"] or p["external_user_id"]: p["is_test"] for p in people} == {"Meena": True, "48213": False}


def test_is_own_matches_only_this_login():
    assert playground_people.is_own("owner-test:u1", "u1")
    assert playground_people.is_own("owner-test:u1:tabc123", "u1")
    assert not playground_people.is_own("owner-test:u10", "u1")
    assert not playground_people.is_own("owner-test:u2:tabc123", "u1")
    assert not playground_people.is_own("48213", "u1")
