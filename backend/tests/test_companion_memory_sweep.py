"""companion-memory T4: the every-minute sweep that turns new messages into facts."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.companion import memory_card, memory_sweep, store
from tests.fake_supabase import FakeSupabase

NOW = datetime(2026, 11, 9, 10, 10, tzinfo=timezone.utc)
SECRET = "Zoho la interview 20th"


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    memory_sweep._failures.clear()
    state = {"calls": [], "answers": []}

    async def llm(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4):
        state["calls"].append({"tenant_id": tenant_id, "user": messages[1]["content"], "purpose": purpose})
        nxt = state["answers"].pop(0) if state["answers"] else "[]"
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    monkeypatch.setattr(memory_card.ai_reply, "_llm_chat", llm)

    def character(tenant, name, level=2):
        return fake.add("companions", tenant_id=tenant, name=name, language="ta-en",
                        memory_level=level, memory_engine="card")

    def chat(companion, user, *turns):
        """turns: (role, text, minutes_ago). Writes messages and the conversation's last_message_at."""
        conv = next((c for c in fake.rows("companion_conversations")
                     if c["companion_id"] == companion["id"] and c["end_user_id"] == user), None)
        if not conv:
            added = fake.add("companion_conversations", tenant_id=companion["tenant_id"],
                             companion_id=companion["id"], end_user_id=user, last_message_at=at(9000))
            conv = next(c for c in fake.rows("companion_conversations") if c["id"] == added["id"])
        for role, text, ago in turns:
            fake.add("companion_messages", tenant_id=companion["tenant_id"], companion_id=companion["id"],
                     conversation_id=conv["id"], end_user_id=user, role=role, content=text, created_at=at(ago))
            conv["last_message_at"] = max(conv["last_message_at"], at(ago))

    return type("Env", (), {"db": fake, "state": state, "character": staticmethod(character),
                            "chat": staticmethod(chat)})


def sweep():
    return asyncio.run(memory_sweep.run_memory_sweep(NOW))


def facts(env):
    return [f["text"] for f in env.db.rows("companion_memory_facts")]


def mark(env, companion, user):
    return asyncio.run(store.get_watermark(companion["tenant_id"], companion["id"], user))


def test_day1_example_one_call_four_facts_and_watermark_moves(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", "Job poiduchu. En paiyan ku 10th exam March la. " + SECRET, 8),
             ("assistant", "Kavalaipadaathinga Karthik.", 8))
    env.state["answers"].append('''[{"op":"add","section":"life","text":"lost job","valid_from":"2026-10"},
      {"op":"add","section":"people","text":"son, in 10th standard"},
      {"op":"add","section":"threads","text":"son's 10th exam","valid_from":"2027-03"},
      {"op":"add","section":"threads","text":"Zoho interview","valid_from":"2026-11-20"}]''')
    assert sweep() == {"ok": 1}
    assert len(env.state["calls"]) == 1 and env.state["calls"][0]["purpose"] == "companion_memory"
    assert len(facts(env)) == 4
    assert mark(env, jothidar, "karthik") == at(8)
    assert sweep() == {} and len(env.state["calls"]) == 1  # nothing new: no AI call


def test_three_quick_replies_become_one_call_and_only_new_messages_are_sent(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", "old message", 30), ("assistant", "old reply", 30))
    asyncio.run(store.set_watermark("t1", jothidar["id"], "karthik", at(30)))
    env.chat(jothidar, "karthik", *[(role, f"{role} {i}", 6 - i) for i in range(3) for role in ("user", "assistant")])
    assert sweep() == {"ok": 1}
    sent = env.state["calls"][0]["user"]
    assert "old message" not in sent and all(f"user {i}" in sent for i in range(3))


def test_level1_characters_and_other_tenants_rows_are_left_alone(env):
    bank = env.character("t1", "Bank bot", level=1)
    env.chat(bank, "karthik", ("user", "balance?", 5), ("assistant", "ok", 5))
    assert sweep() == {} and env.state["calls"] == []

    theirs = env.character("t2", "Their bot")
    env.chat(theirs, "priya", ("user", "I moved to Pune", 5), ("assistant", "nice", 5))
    env.state["answers"].append('[{"op":"add","section":"profile","text":"lives in Pune"}]')
    sweep()
    fact = env.db.rows("companion_memory_facts")[0]
    assert env.state["calls"][0]["tenant_id"] == "t2"
    assert (fact["tenant_id"], fact["companion_id"], fact["end_user_id"]) == ("t2", theirs["id"], "priya")


def test_a_lone_fresh_user_message_waits_for_the_reply(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", "hi", 0.5))
    assert sweep() == {"waiting": 1} and env.state["calls"] == []
    env.chat(jothidar, "karthik", ("user", "still there?", 3))
    # Once the newest user message is older than SETTLE, it's taken even with no reply.
    env.db.rows("companion_messages")[0]["created_at"] = at(4)
    assert sweep() == {"ok": 1}


def test_only_character_messages_move_the_watermark_without_a_call(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("assistant", "Vanakkam! Eppadi irukeenga?", 5))
    assert sweep() == {"skipped": 1} and env.state["calls"] == []
    assert mark(env, jothidar, "karthik") == at(5)


def test_errors_back_off_then_give_up_after_about_half_an_hour(env, caplog):
    caplog.set_level(logging.DEBUG)
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", SECRET, 5), ("assistant", "Super!", 5))
    env.state["answers"] += [RuntimeError("groq down"), "not json"] * 3

    def sweep_at(minutes_later):
        return asyncio.run(memory_sweep.run_memory_sweep(NOW + timedelta(minutes=minutes_later)))

    # Retries after 1, 2, 4, 8, 16 minutes; a pair backing off isn't even looked at.
    for minute, wait in [(0, 1), (1, 2), (3, 4), (7, 8), (15, 16)]:
        assert sweep_at(minute) == {"failed": 1} and mark(env, jothidar, "karthik") is None
        assert sweep_at(minute + wait - 0.5) == {}
    assert sweep_at(31) == {"gave_up": 1} and mark(env, jothidar, "karthik") == at(5)
    assert len(env.state["calls"]) == 6
    assert facts(env) == []
    assert SECRET not in caplog.text and "Super!" not in caplog.text


def test_at_most_twenty_pairs_and_twenty_messages_per_tick(env):
    jothidar = env.character("t1", "Jothidar AI")
    for i in range(25):
        env.chat(jothidar, f"user{i}", ("user", f"hello {i}", 5), ("assistant", "hi", 5))
    assert sweep() == {"ok": 20}
    assert sweep() == {"ok": 5}

    env.chat(jothidar, "chatty", *[("user", f"line {i}", 60 - i) for i in range(30)])
    asyncio.run(store.set_watermark("t1", jothidar["id"], "chatty", at(61)))  # a backlog after a watermark
    sweep()
    assert env.state["calls"][-1]["user"].count("Person: line") == 20  # first 20, rest next tick
    assert mark(env, jothidar, "chatty") == at(60 - 19)
    sweep()
    assert env.state["calls"][-1]["user"].count("Person: line") == 10


def test_a_new_level2_pair_relearns_from_its_last_twenty_messages(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", *[("user", f"msg {i}", 100 - i) for i in range(25)])
    sweep()
    sent = env.state["calls"][0]["user"]
    assert "msg 4\n" not in sent and "msg 5" in sent and "msg 24" in sent


# --- review fixes (2026-11-09) --------------------------------------------------------------------

def test_a_pair_with_nothing_newer_stops_being_due(env):
    """The conversation's app-server clock ran ahead of the database: no messages after the
    watermark, but last_message_at is newer. The watermark catches up so it isn't swept forever."""
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", SECRET, 5), ("assistant", "Super!", 5))
    assert sweep() == {"ok": 1}
    conv = env.db.rows("companion_conversations")[0]
    conv["last_message_at"] = at(4)  # ahead of the newest message (5 min ago)
    assert sweep() == {"skipped": 1} and mark(env, jothidar, "karthik") == at(4)
    assert sweep() == {}


def test_oldest_activity_goes_first_across_characters(env):
    early = env.character("t1", "Jothidar AI")
    late = env.character("t1", "Vastu Guru")
    for i in range(20):
        env.chat(early, f"user{i}", ("user", "hi", 10), ("assistant", "hello", 10))
    env.chat(late, "waiting-longest", ("user", "hi", 100), ("assistant", "hello", 100))
    sweep()
    assert mark(env, late, "waiting-longest") == at(100)


def test_forget_me_during_the_ai_call_writes_nothing(env, monkeypatch):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", SECRET, 5), ("assistant", "Super!", 5))

    async def llm_while_forgetting(messages, max_tokens=300, tenant_id=None, *, purpose="", temperature=0.4):
        env.db.tables["companion_messages"].clear()  # forget_end_user ran meanwhile
        return '[{"op":"add","section":"life","text":"interview at Zoho"}]'
    monkeypatch.setattr(memory_card.ai_reply, "_llm_chat", llm_while_forgetting)
    assert sweep() == {"forgotten": 1}
    assert facts(env) == [] and env.db.rows("companion_memory_state") == []


def test_a_retried_batch_does_not_duplicate_facts(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", SECRET, 5), ("assistant", "Super!", 5))
    asyncio.run(store.add_fact("t1", jothidar["id"], "karthik", "threads", "Zoho interview on 20th"))
    env.state["answers"].append('[{"op":"add","section":"threads","text":"zoho interview on 20th"},'
                                '{"op":"add","section":"life","text":"job hunting"},'
                                '{"op":"add","section":"life","text":"Job hunting"}]')
    assert sweep() == {"ok": 1}
    assert sorted(facts(env)) == ["Zoho interview on 20th", "job hunting"]
