"""The character's own model, the Playground model picker and "Compare without memory".

Every character replies with its own model (companions.model), with the usual one-retry fallback.
The Playground can try another model, with no fallback. ai_reply is shared with the live WhatsApp
reply path, so these tests prove that generate_reply never passes a model, that the public API can't
choose one, and that a picked model must be one the tenant has an API key for."""
import ast
import json
from pathlib import Path

import pytest

from app.companion import engine, models
from app.services import ai_reply
from tests.test_companion_chat_api import DASH, PUB, bearer, env  # noqa: F401  (env is a fixture)
from tests.test_companion_tools import CHART, GET_CHART, call

APP = Path(__file__).resolve().parents[1] / "app"
LLM_FUNCS = {"_llm_chat", "_llm_chat_with_tools"}


def _calls(path: Path, names: set[str]):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in names:
                yield node


def _passes(node: ast.Call, keyword: str) -> bool:
    """True if the call passes `keyword`, or **kwargs that could carry it."""
    return any(k.arg == keyword or k.arg is None for k in node.keywords)


# --- static: who may pass a model -------------------------------------------------------------

def test_only_the_companion_engine_passes_a_model_to_the_llm():
    offenders = []
    for path in APP.rglob("*.py"):
        for node in _calls(path, LLM_FUNCS):
            # engine.py: the Playground's model picker. memory_card.py: the note-writer's fixed model
            # (NOTE_MODEL, never a value from a request).
            if _passes(node, "model") and path.relative_to(APP).as_posix() not in (
                    "companion/engine.py", "companion/memory_card.py"):
                offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert offenders == [], f"model passed to the LLM outside the Playground path: {offenders}"


def test_generate_reply_path_never_passes_a_model():
    calls = list(_calls(APP / "services" / "ai_reply.py", LLM_FUNCS))
    assert calls, "expected ai_reply.py to call _llm_chat"
    assert not [n.lineno for n in calls if _passes(n, "model")]


def test_public_companion_routes_never_pass_model_or_use_memory():
    calls = list(_calls(APP / "routes" / "companion_public.py", {"reply", "continue_reply"}))
    assert len(calls) == 4
    for node in calls:
        assert not _passes(node, "model") and not _passes(node, "use_memory"), node.lineno


# --- runtime ----------------------------------------------------------------------------------

def _save_model(env, model: str) -> None:
    """Writes a model straight onto the live character's row (also stale ones the API would refuse)."""
    next(r for r in env.db.rows("companions") if r["id"] == env.live["id"])["model"] = model


@pytest.fixture
def spy(env, monkeypatch):  # noqa: F811
    """Records the kwargs of every LLM call. The Gemini key is set; the tenant runs 3.1 Flash Lite."""
    seen = []

    async def plain(messages, max_tokens=300, tenant_id=None, **kw):
        seen.append({"kind": "plain", "messages": messages, **kw})
        return "[mood: warm] Vanakkam Karthik!"

    async def with_tools(messages, tools, max_tokens=300, tenant_id=None, **kw):
        seen.append({"kind": "tools", "messages": messages, **kw})
        return env.state["script"].pop(0)

    monkeypatch.setattr(engine.ai_reply, "_llm_chat", plain)
    monkeypatch.setattr(engine.ai_reply, "_llm_chat_with_tools", with_tools)
    keys_set = {"gemini_api_key", "ai_reply_model"}
    monkeypatch.setattr(ai_reply, "get_setting", lambda key, fallback=None, tenant_id=None:
                        ("google/gemini-3.1-flash-lite" if key == "ai_reply_model" else "k") if key in keys_set else None)
    monkeypatch.setattr(ai_reply, "require_tenant_setting", lambda key, tenant_id:
                        ai_reply.get_setting(key, tenant_id=tenant_id) or (_ for _ in ()).throw(RuntimeError(key)))
    return seen


def test_public_chat_never_passes_a_model(env, spy):  # noqa: F811
    body = {"companion_id": env.live["id"], "user_id": "48213", "message": "hi"}
    for extra in ({"model": "google/gemini-3.5-flash-lite"}, {"use_memory": False}):
        assert env.client.post(f"{PUB}/chat", headers=bearer(env.key), json={**body, **extra}).status_code == 422
    assert spy == []
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key), json=body)
    assert r.status_code == 200 and r.json().get("model") is None
    # The character's own model (none saved in the fixture -> the default), with fallback on.
    assert spy and all(c["model"] == "google/gemini-3.1-flash-lite" and c["fallback"] is True for c in spy)
    assert len(env.db.rows("companion_messages")) == 2   # a normal turn: saved with memory


def test_public_chat_uses_the_characters_own_model(env, spy):  # noqa: F811
    _save_model(env, "google/gemini-3.5-flash-lite")
    body = {"companion_id": env.live["id"], "user_id": "48213", "message": "hi"}
    assert env.client.post(f"{PUB}/chat", headers=bearer(env.key), json=body).status_code == 200
    assert spy[-1]["model"] == "google/gemini-3.5-flash-lite" and spy[-1]["fallback"] is True


def test_a_stale_saved_model_falls_back_to_the_default(env, spy):  # noqa: F811
    _save_model(env, "google/gemini-1.0-retired")
    body = {"companion_id": env.live["id"], "user_id": "48213", "message": "hi"}
    assert env.client.post(f"{PUB}/chat", headers=bearer(env.key), json=body).status_code == 200
    assert spy[-1]["model"] == "google/gemini-3.1-flash-lite"


def test_models_lists_only_providers_with_keys(env, spy):  # noqa: F811
    body = env.client.get(f"{DASH}/models").json()
    ids = [m["id"] for m in body["models"]]
    assert ids == ["google/gemini-3.1-flash-lite", "google/gemini-3.5-flash-lite"]
    assert body["default"] == "google/gemini-3.1-flash-lite"


def test_models_is_empty_without_a_gemini_key(env, spy, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ai_reply, "get_setting", lambda key, fallback=None, tenant_id=None: None)
    body = env.client.get(f"{DASH}/models").json()
    assert body["models"] == [] and body["default"] == "google/gemini-3.1-flash-lite"


def test_test_chat_uses_the_picked_model(env, spy):  # noqa: F811
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat",
                        json={"message": "hi", "model": "google/gemini-3.5-flash-lite"})
    assert r.status_code == 200
    assert spy[-1]["model"] == "google/gemini-3.5-flash-lite"
    assert r.json()["model"] == "Gemini 3.5 Flash Lite"


def test_test_chat_without_a_pick_uses_the_characters_model(env, spy):  # noqa: F811
    _save_model(env, "google/gemini-3.5-flash-lite")
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "hi"})
    assert r.status_code == 200
    assert spy[-1]["model"] == "google/gemini-3.5-flash-lite" and spy[-1]["fallback"] is True
    assert r.json()["model"] == "Gemini 3.5 Flash Lite"


def test_a_picked_model_never_falls_back(env, spy):  # noqa: F811
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat",
                        json={"message": "hi", "model": "google/gemini-3.5-flash-lite"})
    assert r.status_code == 200 and "fallback" not in spy[-1]


def test_patch_saves_a_listed_model_and_refuses_others(env, spy):  # noqa: F811
    url = f"{DASH}/{env.live['id']}"
    r = env.client.patch(url, json={"model": "google/gemini-3.5-flash-lite"})
    assert r.status_code == 200 and r.json()["model"] == "google/gemini-3.5-flash-lite"
    for bad in ("deepseek/deepseek-chat", "google/gemini-3.5-flash", ""):
        assert env.client.patch(url, json={"model": bad}).status_code == 422
    assert env.db.rows("companions")[0]["model"] == "google/gemini-3.5-flash-lite"


def test_a_new_character_gets_the_default_model(env, spy):  # noqa: F811
    r = env.client.post(DASH, json={"name": "Dental Desk"})
    assert r.status_code == 201 and r.json()["model"] == "google/gemini-3.1-flash-lite"
    assert models.DEFAULT_MODEL == ai_reply.DEFAULT_REPLY_MODEL


def test_llm_chat_fallback_follows_the_flag(monkeypatch):
    import asyncio
    seen = []
    monkeypatch.setattr(ai_reply, "_provider_for", lambda t, m: ("gemini", "gemini-3.5-flash-lite"))

    async def fake_call(call, native_model, *, fallback, **kw):
        seen.append(fallback)
        return "ok"
    monkeypatch.setattr(ai_reply, "_gemini_call", fake_call)
    msgs = [{"role": "user", "content": "x"}]
    asyncio.run(ai_reply._llm_chat(msgs, tenant_id="t1"))                                   # WhatsApp
    asyncio.run(ai_reply._llm_chat(msgs, tenant_id="t1", model="google/gemini-3.5-flash-lite"))  # Playground pick
    asyncio.run(ai_reply._llm_chat(msgs, tenant_id="t1", model="google/gemini-3.5-flash-lite", fallback=True))
    assert seen == [True, False, True]


@pytest.mark.parametrize("model", ["openai/gpt-5-nano-2025-08-07", "sarvam-30b", "groq/llama-3.3-70b-versatile",
                                   "google/gemini-3.5-flash", "anthropic/x", "google/../etc"])
def test_test_chat_refuses_models_off_the_list(env, spy, model):  # noqa: F811
    r = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "hi", "model": model})
    assert r.status_code == 422 and spy == []


def test_compare_without_memory_saves_nothing_and_skips_history(env, spy):  # noqa: F811
    url = f"{DASH}/{env.live['id']}/test-chat"
    assert env.client.post(url, json={"message": "My birth time is 4:35 am"}).status_code == 200
    saved = {t: len(env.db.rows(t)) for t in ("companion_messages", "companion_conversations", "companion_end_users")}
    r = env.client.post(url, json={"message": "What do you know about me?", "use_memory": False,
                                   "tools": [GET_CHART.model_dump()]})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert r.json()["text"] == "Vanakkam Karthik!" and r.json()["message_id"] is None
    assert {t: len(env.db.rows(t)) for t in saved} == saved   # nothing saved, no new conversation
    assert r.json()["conversation_id"] is None
    last = spy[-1]
    assert last["kind"] == "plain"                              # tools dropped
    prompt = json.dumps(last["messages"])
    assert "4:35" not in prompt and "Vanakkam Karthik" not in prompt   # no history


def test_a_tool_turn_keeps_the_picked_model_through_continue(env, spy):  # noqa: F811
    env.state["script"] = [("", [call()]), ("[mood: warm] Ungal lagnam Kumbham.", [])]
    first = env.client.post(f"{DASH}/{env.live['id']}/test-chat",
                            json={"message": "En jathagam", "tools": [GET_CHART.model_dump()],
                                  "model": "google/gemini-3.5-flash-lite"}).json()
    assert first["status"] == "tool_call"
    done = env.client.post(f"{DASH}/test-chat/continue",
                           json={"turn_id": first["turn_id"], "results": [{"id": "call_1", "output": CHART}]})
    assert done.status_code == 200
    assert [c.get("model") for c in spy] == ["google/gemini-3.5-flash-lite", "google/gemini-3.5-flash-lite"]


def test_llm_chat_without_model_resolves_the_tenant_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(ai_reply, "_resolve_provider", lambda t: ("gemini", "gemini-live"))

    async def gemini(**kw):
        seen.update(kw)
        return "ok"
    monkeypatch.setattr(ai_reply, "gemini_chat_completion", gemini)
    import asyncio
    assert asyncio.run(ai_reply._llm_chat([{"role": "user", "content": "x"}], tenant_id="t1")) == "ok"
    assert seen["model"] == "gemini-live"
