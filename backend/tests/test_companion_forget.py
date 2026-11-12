"""companion-core T7: "forget me" is business-wide and leaves everyone else untouched."""
import asyncio

import pytest

from app.companion import engine, store
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(engine.ai_reply, "_resolve_provider", lambda t: ("groq", "m"))
    replies = iter(["[mood: concerned] a", "[mood: happy] b", "[mood: warm] c", "[mood: warm] d", "[mood: warm] e"] * 3)

    async def llm(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4):
        return next(replies)

    async def kb(tenant_id, collection_id, message, history=None, *, companion_id=None, rewrite=None):
        return None
    monkeypatch.setattr(engine.ai_reply, "_llm_chat", llm)
    monkeypatch.setattr(engine.kb_search, "search", kb)

    def character(tenant, name):
        return fake.add("companions", tenant_id=tenant, name=name, industry="general", status="live",
                        default_mood="calm", language="en", memory_level=1, knowledge_tag_id=None,
                        sample_lines=[], goals=[], rules=[])
    chars = {"jothidar": character("t1", "Jothidar AI"), "vastu": character("t1", "Vastu Guru"),
             "other": character("t2", "Their bot")}
    return type("Env", (), {"db": fake, "chars": chars})


def say(env, char, user, tenant="t1", msg="hi", **kw):
    return asyncio.run(engine.reply(env.chars[char]["id"], tenant, user, msg, **kw))


def mine(env, table, person_id):
    return [r for r in env.db.rows(table) if r.get("end_user_id") == person_id]


def test_forget_wipes_the_person_across_every_character_only(env):
    say(env, "jothidar", "48213", display_name="Karthik")
    say(env, "vastu", "48213")
    say(env, "jothidar", "77001", display_name="Meena")          # another person, same business
    say(env, "other", "48213", tenant="t2", display_name="Karthik")  # same id, another business
    karthik = next(p for p in env.db.rows("companion_end_users")
                   if p["tenant_id"] == "t1" and p["external_user_id"] == "48213")
    conv = mine(env, "companion_conversations", karthik["id"])[0]
    env.db.add("companion_pending_turns", tenant_id="t1", companion_id=env.chars["jothidar"]["id"],
               conversation_id=conv["id"], messages={}, tools=[], round=1, expires_at="2999-01-01T00:00:00+00:00")

    assert asyncio.run(engine.forget_person("t1", "48213")) is True

    assert mine(env, "companion_messages", karthik["id"]) == []
    assert mine(env, "companion_conversations", karthik["id"]) == []
    assert env.db.rows("companion_pending_turns") == []
    person = next(p for p in env.db.rows("companion_end_users") if p["id"] == karthik["id"])
    assert person["display_name"] is None and person["forgotten_at"]

    meena = next(p for p in env.db.rows("companion_end_users") if p["external_user_id"] == "77001")
    assert len(mine(env, "companion_messages", meena["id"])) == 2 and meena["display_name"] == "Meena"
    t2_karthik = next(p for p in env.db.rows("companion_end_users") if p["tenant_id"] == "t2")
    assert len(mine(env, "companion_messages", t2_karthik["id"])) == 2 and t2_karthik["display_name"] == "Karthik"


def test_a_forgotten_person_starts_fresh(env):
    say(env, "jothidar", "48213")                                   # mood becomes concerned
    asyncio.run(engine.forget_person("t1", "48213"))
    r = say(env, "jothidar", "48213")
    person = next(p for p in env.db.rows("companion_end_users") if p["external_user_id"] == "48213")
    convs = mine(env, "companion_conversations", person["id"])
    assert len(convs) == 1 and convs[0]["message_count"] == 2
    assert [m["content"] for m in mine(env, "companion_messages", person["id"])] == ["hi", "b"]
    assert r.mood == "happy"                                        # the tag of the fresh reply


def test_fresh_start_uses_the_default_mood_in_the_prompt(env, monkeypatch):
    say(env, "jothidar", "48213")
    asyncio.run(engine.forget_person("t1", "48213"))
    prompts = []

    async def spy(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4):
        prompts.append(messages)
        return "[mood: calm] hello again"
    monkeypatch.setattr(engine.ai_reply, "_llm_chat", spy)
    say(env, "jothidar", "48213")
    assert "Your current mood with this user: calm." in prompts[0][0]["content"]
    assert len(prompts[0]) == 2                                     # system + this message, no history


def test_forgetting_someone_unknown_or_in_another_business_is_a_no_op(env):
    say(env, "other", "48213", tenant="t2")
    before = len(env.db.rows("companion_messages"))
    assert asyncio.run(engine.forget_person("t1", "48213")) is False
    assert asyncio.run(engine.forget_person("t1", "nobody")) is False
    assert len(env.db.rows("companion_messages")) == before


def test_memory_providers_are_told(env, monkeypatch):
    say(env, "jothidar", "48213")
    told = []

    class Spy:
        async def forget(self, tenant_id, end_user_id):
            told.append((tenant_id, end_user_id))
    monkeypatch.setattr(engine, "forget_providers", lambda: [Spy(), Spy()])
    asyncio.run(engine.forget_person("t1", "48213"))
    assert len(told) == 2 and {t for t, _ in told} == {"t1"}


# --- companion-memory T6: forget-me wipes Level 2 memory too --------------------------------------

def test_forget_wipes_remembered_facts_and_watermarks_across_characters(env):
    say(env, "jothidar", "48213")
    say(env, "jothidar", "77001")
    karthik, meena = (asyncio.run(store.find_end_user("t1", u)) for u in ("48213", "77001"))
    for char in ("jothidar", "vastu"):
        for person in (karthik, meena):
            asyncio.run(store.add_fact("t1", env.chars[char]["id"], person["id"], "life", f"fact {char}"))
            asyncio.run(store.set_watermark("t1", env.chars[char]["id"], person["id"], "2026-11-09T10:00:00+00:00"))

    assert asyncio.run(engine.forget_person("t1", "48213"))
    for table in ("companion_memory_facts", "companion_memory_state"):
        assert mine(env, table, karthik["id"]) == []
        assert len(mine(env, table, meena["id"])) == 2
