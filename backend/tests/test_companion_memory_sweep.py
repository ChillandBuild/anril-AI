"""companion-memory T4/T10: the nightly sweep (02:00 IST) that turns the day's messages into facts."""
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
    state = {"calls": [], "answers": []}

    async def llm(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4, model=None):
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
    env.state["answers"].append('''[{"op":"add","section":"life","text":"lost job","valid_from":"2026-10","quote":"Job poiduchu"},
      {"op":"add","section":"people","text":"son, in 10th standard","quote":"En paiyan ku 10th exam"},
      {"op":"add","section":"threads","text":"son's 10th exam","valid_from":"2027-03","quote":"10th exam March la"},
      {"op":"add","section":"threads","text":"Zoho interview","valid_from":"2026-11-20","quote":"Zoho la interview 20th"}]''')
    assert sweep() == {"ok": 1}
    assert len(env.state["calls"]) == 1 and env.state["calls"][0]["purpose"] == "companion_memory"
    assert len(facts(env)) == 4
    assert mark(env, jothidar, "karthik") == at(8)
    assert sweep() == {} and len(env.state["calls"]) == 1  # nothing new: no AI call


def test_a_whole_day_becomes_one_call_and_only_new_messages_are_sent(env):
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
    env.state["answers"].append('[{"op":"add","section":"profile","text":"lives in Pune","quote":"I moved to Pune"}]')
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


def test_a_failed_night_keeps_the_watermark_and_the_third_moves_it_on(env, caplog):
    caplog.set_level(logging.DEBUG)
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", SECRET, 5), ("assistant", "Super!", 5))
    env.state["answers"] += [RuntimeError("groq down"), "not json", RuntimeError("groq down")]

    def state():
        return env.db.rows("companion_memory_state")[0]

    assert sweep() == {"failed": 1} and mark(env, jothidar, "karthik") is None and state()["failures"] == 1
    assert sweep() == {"failed": 1} and state()["failures"] == 2       # night 2: still retried
    assert sweep() == {"parked": 1} and mark(env, jothidar, "karthik") == at(5)  # night 3: move on, keep a record
    assert state()["failures"] == 0 and len(env.state["calls"]) == 3     # no second try on the parking night
    [parked] = state()["skipped"]
    assert (parked["through"], parked["count"], parked["tries"]) == (at(5), 2, 0) and parked["after"] < at(5)
    # the parked messages are searchable at once, even though the card never read them
    assert [c["kind"] for c in env.db.rows("companion_memory_chunks")] == ["messages"]
    assert facts(env) == []
    assert SECRET not in caplog.text and "Super!" not in caplog.text

    # night 4: the AI is still down. One more try is counted and the record stays.
    env.state["answers"].append(RuntimeError("groq down"))
    assert sweep() == {"parked_failed": 1} and state()["skipped"][0]["tries"] == 1
    # night 5: the AI is back. The parked messages reach the card and the record is cleared.
    env.state["answers"].append('[{"op":"add","section":"threads","text":"Zoho interview","quote":"Zoho la interview 20th"}]')
    assert sweep() == {"parked_recovered": 1} and state()["skipped"] is None
    assert facts(env) == ["Zoho interview"] and mark(env, jothidar, "karthik") == at(5)
    assert sweep() == {} and len(env.state["calls"]) == 5
    assert SECRET not in caplog.text


def test_parked_messages_are_read_late_and_only_add(env):
    """Priya's old chat was parked; she has since said she moved. The late read must not undo that."""
    guru = env.character("t1", "Guru")
    env.chat(guru, "priya", ("user", "Naan Chennai la irukken", 600), ("assistant", "Super!", 600))
    env.state["answers"] += [RuntimeError("down")] * 3
    assert [sweep(), sweep(), sweep()] == [{"failed": 1}, {"failed": 1}, {"parked": 1}]
    env.chat(guru, "priya", ("user", "Bangalore ku maathiten", 30), ("assistant", "Oh nice", 30))
    env.state["answers"] += [
        '[{"op":"add","section":"profile","text":"Lives in Bangalore","quote":"Bangalore ku maathiten"}]',
        '[{"op":"close","ref":"f1"},{"op":"add","section":"people","text":"From Chennai","quote":"Naan Chennai la irukken"}]',
    ]
    assert sweep() == {"ok": 1, "parked_recovered": 1}
    late_prompt = env.state["calls"][-1]["user"]
    assert "Naan Chennai la irukken" in late_prompt and "Bangalore ku maathiten" not in late_prompt
    rows = {r["text"]: r["status"] for r in env.db.rows("companion_memory_facts")}
    assert rows == {"Lives in Bangalore": "active", "From Chennai": "active"}
    assert mark(env, guru, "priya") == at(30)


def test_a_parked_range_that_keeps_failing_is_marked_dead_but_never_erased(env, monkeypatch):
    monkeypatch.setattr(memory_sweep, "PARKED_TRIES", 2)
    guru = env.character("t1", "Guru")
    env.chat(guru, "priya", ("user", SECRET, 5), ("assistant", "Super!", 5))
    env.state["answers"] += [RuntimeError("down")] * 5
    outcomes = [sweep() for _ in range(6)]
    assert outcomes == [{"failed": 1}, {"failed": 1}, {"parked": 1}, {"parked_failed": 1}, {"parked_dead": 1}, {}]
    [parked] = env.db.rows("companion_memory_state")[0]["skipped"]
    assert parked["dead"] is True and parked["tries"] == 2 and parked["count"] == 2
    assert len(env.state["calls"]) == 5  # a dead range costs no more AI calls
    # the operator bell hears about it: once when the chat is parked, once when it is given up
    assert [(i["tenant_id"], i["type"]) for i in env.db.rows("incidents")] == [
        ("t1", "companion_memory_parked"), ("t1", "companion_memory_parked_dead")]
    assert SECRET not in str(env.db.rows("incidents"))


def test_a_failed_park_leaves_the_watermark_so_nothing_is_lost(env, monkeypatch):
    guru = env.character("t1", "Guru")
    env.chat(guru, "priya", ("user", SECRET, 5), ("assistant", "Super!", 5))
    asyncio.run(store.record_failure("t1", guru["id"], "priya", 2))
    env.state["answers"].append(RuntimeError("down"))

    async def broken(*args, **kwargs):
        raise RuntimeError("database down")
    monkeypatch.setattr(store, "park_messages", broken)
    assert sweep() == {"failed": 1} and mark(env, guru, "priya") is None


def test_a_good_night_clears_the_failure_count(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", SECRET, 5), ("assistant", "Super!", 5))
    env.state["answers"] += [RuntimeError("groq down"), "[]"]
    assert sweep() == {"failed": 1}
    assert sweep() == {"ok": 1}
    row = env.db.rows("companion_memory_state")[0]
    assert row["failures"] == 0 and row["last_message_at"] == at(5)


def test_a_long_day_goes_in_chunks_of_forty_with_the_watermark_after_each(env):
    jothidar = env.character("t1", "Jothidar AI")
    asyncio.run(store.set_watermark("t1", jothidar["id"], "chatty", at(200)))
    env.chat(jothidar, "chatty", *[("user", f"line {i}", 150 - i) for i in range(90)])
    assert sweep() == {"ok": 1}
    assert [c["user"].count("Person: line") for c in env.state["calls"]] == [40, 40, 10]
    assert mark(env, jothidar, "chatty") == at(150 - 89)


def test_at_most_five_chunks_per_pair_a_night_then_the_rest_next_night(env):
    jothidar = env.character("t1", "Jothidar AI")
    asyncio.run(store.set_watermark("t1", jothidar["id"], "chatty", at(500)))
    env.chat(jothidar, "chatty", *[("user", f"line {i}", 400 - i) for i in range(210)])
    sweep()
    assert len(env.state["calls"]) == 5 and mark(env, jothidar, "chatty") == at(400 - 199)
    sweep()
    assert len(env.state["calls"]) == 6 and env.state["calls"][-1]["user"].count("Person: line") == 10


def test_a_failed_chunk_keeps_the_good_chunks_before_it(env):
    jothidar = env.character("t1", "Jothidar AI")
    asyncio.run(store.set_watermark("t1", jothidar["id"], "chatty", at(200)))
    env.chat(jothidar, "chatty", *[("user", f"line {i}", 150 - i) for i in range(50)])
    env.state["answers"] += ["[]", RuntimeError("groq down")]
    assert sweep() == {"failed": 1}
    assert mark(env, jothidar, "chatty") == at(150 - 39)  # chunk 1 kept
    assert env.db.rows("companion_memory_state")[0]["failures"] == 1


def test_at_most_max_pairs_a_night_oldest_first(env, monkeypatch):
    monkeypatch.setattr(memory_sweep, "MAX_PAIRS", 20)
    jothidar = env.character("t1", "Jothidar AI")
    for i in range(25):
        env.chat(jothidar, f"user{i}", ("user", f"hello {i}", 5), ("assistant", "hi", 5))
    assert sweep() == {"ok": 20}
    assert sweep() == {"ok": 5}


def test_a_new_level2_pair_learns_from_its_latest_forty_messages(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", *[("user", f"msg {i}", 100 - i) for i in range(45)])
    sweep()
    sent = env.state["calls"][0]["user"]
    assert len(env.state["calls"]) == 1
    assert "msg 4\n" not in sent and "msg 5" in sent and "msg 44" in sent


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


def test_oldest_activity_goes_first_across_characters(env, monkeypatch):
    monkeypatch.setattr(memory_sweep, "MAX_PAIRS", 20)
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

    async def llm_while_forgetting(messages, max_tokens=300, tenant_id=None, *, purpose="", temperature=0.4, model=None):
        env.db.tables["companion_messages"].clear()  # forget_end_user ran meanwhile
        return '[{"op":"add","section":"life","text":"interview at Zoho","quote":"Zoho la interview"}]'
    monkeypatch.setattr(memory_card.ai_reply, "_llm_chat", llm_while_forgetting)
    assert sweep() == {"forgotten": 1}
    assert facts(env) == [] and all(r.get("last_message_at") is None for r in env.db.rows("companion_memory_state"))


def test_a_retried_batch_does_not_duplicate_facts(env):
    jothidar = env.character("t1", "Jothidar AI")
    env.chat(jothidar, "karthik", ("user", SECRET, 5), ("assistant", "Super!", 5))
    asyncio.run(store.add_fact("t1", jothidar["id"], "karthik", "threads", "Zoho interview on 20th"))
    env.state["answers"].append('[{"op":"add","section":"threads","text":"zoho interview on 20th","quote":"Zoho la interview 20th"},'
                                '{"op":"add","section":"life","text":"job hunting","quote":"interview"},'
                                '{"op":"add","section":"life","text":"Job hunting","quote":"interview"}]')
    assert sweep() == {"ok": 1}
    assert sorted(facts(env)) == ["Zoho interview on 20th", "job hunting"]
