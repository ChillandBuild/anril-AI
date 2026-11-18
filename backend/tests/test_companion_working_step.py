"""working_step: the reply thinks in a hidden <working> block first (migration 293). The person and the
saved chat never see it; the Playground does."""
from types import SimpleNamespace

from app.companion import engine
from app.companion.platform_rules import WORKING_RULE
from app.companion.prompt import build_messages, split_working
from tests.test_companion_chat_api import DASH, PUB, bearer, env  # noqa: F401  (env is a fixture)

CARD = {"name": "Jothidar AI", "rules": [], "language": "ta"}
RAW = ("<working>\n12th lord Mars in 12th, own house. Mars dasa running -> abroad link.\n</working>\n"
       "[mood: calm] [used: none] Vivek, Karthik-ku velinaattu vaaippu adhigam.")


def test_split_cuts_the_working_off():
    reply, working = split_working(RAW)
    assert reply == "[mood: calm] [used: none] Vivek, Karthik-ku velinaattu vaaippu adhigam."
    assert working.startswith("12th lord Mars in 12th")


def test_split_without_working_changes_nothing():
    assert split_working("[mood: calm] hi") == ("[mood: calm] hi", None)
    assert split_working(None) == (None, None)


def test_an_unclosed_working_keeps_only_what_follows_the_mood_tag():
    assert split_working("<working>step 1… [mood: calm] Sari.") == ("[mood: calm] Sari.", "step 1…")
    reply, working = split_working("<working>step 1, step 2 and the cap hit")
    assert reply == "" and working == "step 1, step 2 and the cap hit"


def test_the_rule_is_in_the_prompt_only_when_on_and_not_for_small_talk():
    on = {**CARD, "working_step": True}
    question, hello = SimpleNamespace(needs_docs=True, passages=()), SimpleNamespace(needs_docs=False, passages=())
    assert WORKING_RULE in build_messages(on, "calm", None, "", [], "abroad?")[0]["content"]
    assert WORKING_RULE in build_messages(on, "calm", question, "", [], "abroad?")[0]["content"]
    assert WORKING_RULE not in build_messages(on, "calm", hello, "", [], "vanakkam")[0]["content"]
    assert WORKING_RULE not in build_messages(CARD, "calm", None, "", [], "abroad?")[0]["content"]


def test_the_cap_is_higher_only_for_a_working_character():
    assert engine._max_tokens({"working_step": True}) == engine.LLM_MAX_TOKENS_WORKING > engine.LLM_MAX_TOKENS
    assert engine._max_tokens({}) == engine.LLM_MAX_TOKENS


def _answer_with_working(monkeypatch):
    caps = []

    async def plain(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4, **kw):
        caps.append(max_tokens)
        return RAW
    monkeypatch.setattr(engine.ai_reply, "_llm_chat", plain)
    return caps


def test_the_person_and_the_saved_chat_never_see_the_working(env, monkeypatch):  # noqa: F811
    _answer_with_working(monkeypatch)
    r = env.client.post(f"{PUB}/chat", headers=bearer(env.key), json={
        "companion_id": env.live["id"], "user_id": "u42", "message": "velinaadu pogalama?"})
    assert r.status_code == 200 and r.json()["text"] == "Vivek, Karthik-ku velinaattu vaaippu adhigam."
    assert "working" not in r.json() and "Mars" not in r.text
    assert all("Mars" not in (m.get("content") or "") for m in env.db.rows("companion_messages"))


def test_the_playground_shows_the_working(env, monkeypatch):  # noqa: F811
    _answer_with_working(monkeypatch)
    body = env.client.post(f"{DASH}/{env.live['id']}/test-chat", json={"message": "velinaadu pogalama?"}).json()
    assert body["text"].startswith("Vivek") and body["working"].startswith("12th lord Mars")
