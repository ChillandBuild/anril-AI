"""companion-core T4: people, conversations, history and the memory slot."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.companion import memory, store
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def _ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


@pytest.fixture
def world(db):
    jothidar = db.add("companions", tenant_id="t1", name="Jothidar AI")
    vastu = db.add("companions", tenant_id="t1", name="Vastu Guru")
    karthik = run(store.find_or_create_end_user("t1", "48213", "Karthik"))
    return db, jothidar, vastu, karthik


def _say(conv, role, text, **kw):
    return run(store.save_message("t1", conv, role, text, **kw))


# 1. people
def test_same_person_is_one_row_across_characters_and_keeps_first_seen(db):
    # The fake has no DB defaults, so seed the timestamps the real table would stamp on first insert.
    first = db.add("companion_end_users", tenant_id="t1", external_user_id="48213", display_name="Karthik",
                   first_seen_at="2026-01-01T00:00:00+00:00", last_seen_at="2026-01-01T00:00:00+00:00")
    again = run(store.find_or_create_end_user("t1", "48213", "  Karthik R  "))
    assert len(db.rows("companion_end_users")) == 1
    assert again["id"] == first["id"]
    assert again["display_name"] == "Karthik R"
    assert again["first_seen_at"] == "2026-01-01T00:00:00+00:00"
    assert again["last_seen_at"] > first["last_seen_at"]

    no_name = run(store.find_or_create_end_user("t1", "48213"))
    assert no_name["display_name"] == "Karthik R"
    blank = run(store.find_or_create_end_user("t1", "48213", "   "))
    assert blank["display_name"] == "Karthik R"


def test_other_tenant_gets_a_separate_person_row(db):
    a = run(store.find_or_create_end_user("t1", "48213", "Karthik"))
    b = run(store.find_or_create_end_user("t2", "48213", "Karthik"))
    assert a["id"] != b["id"] and len(db.rows("companion_end_users")) == 2


def test_display_name_is_capped_at_100_chars(db):
    row = run(store.find_or_create_end_user("t1", "48213", "k" * 150))
    assert len(row["display_name"]) == 100


# 2. separate conversations, histories, moods per character
def test_characters_have_separate_conversations_histories_and_moods(world):
    db, jothidar, vastu, karthik = world
    cj = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    cv = run(store.open_conversation("t1", vastu["id"], karthik["id"], "calm"))
    assert cj["id"] != cv["id"]
    _say(cj, "user", "Enna dasha nadakkuthu?")
    _say(cj, "assistant", "Guru dasha, nalla time.", mood="warm")

    assert run(store.recent_messages("t1", vastu["id"], karthik["id"])) == []
    assert [m["content"] for m in run(store.recent_messages("t1", jothidar["id"], karthik["id"]))] == [
        "Enna dasha nadakkuthu?", "Guru dasha, nalla time."]

    run(store.set_conversation_mood("t1", cj["id"], "concerned"))
    moods = {r["id"]: r["mood"] for r in db.rows("companion_conversations")}
    assert moods[cj["id"]] == "concerned" and moods[cv["id"]] == "calm"


# 3. 24 h rule and mood carry-over
def test_conversation_reused_within_24h_then_new_one_inherits_mood(world):
    db, jothidar, _, karthik = world
    first = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    assert first["mood"] == "warm" and first["message_count"] == 0
    run(store.set_conversation_mood("t1", first["id"], "concerned"))

    same = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    assert same["id"] == first["id"]

    next(r for r in db.rows("companion_conversations") if r["id"] == first["id"])["last_message_at"] = _ago(25)
    fresh = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    assert fresh["id"] != first["id"]
    assert fresh["mood"] == "concerned"
    assert fresh["message_count"] == 0
    assert len(db.rows("companion_conversations")) == 2


def test_z_suffix_and_naive_timestamps_are_understood(world):
    db, jothidar, _, karthik = world
    conv = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    row = next(r for r in db.rows("companion_conversations") if r["id"] == conv["id"])
    row["last_message_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    assert run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))["id"] == conv["id"]
    row["last_message_at"] = (datetime.now(timezone.utc) - timedelta(hours=30)).replace(tzinfo=None).isoformat()
    assert run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))["id"] != conv["id"]


# 4. last 10 only, oldest first, one character, across conversations
def test_recent_messages_last_ten_oldest_first_across_conversations(world):
    db, jothidar, vastu, karthik = world
    old = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    for i in range(1, 7):
        _say(old, "user", f"jothidar {i}")
    next(r for r in db.rows("companion_conversations") if r["id"] == old["id"])["last_message_at"] = _ago(30)
    new = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    assert new["id"] != old["id"]
    for i in range(7, 13):
        _say(new, "assistant", f"jothidar {i}")
    other = run(store.open_conversation("t1", vastu["id"], karthik["id"], "calm"))
    _say(other, "user", "vastu only")

    got = [m["content"] for m in run(store.recent_messages("t1", jothidar["id"], karthik["id"]))]
    assert got == [f"jothidar {i}" for i in range(3, 13)]
    assert len(run(store.recent_messages("t1", jothidar["id"], karthik["id"], limit=2))) == 2


# 5. content cap and counters
def test_content_is_cut_and_counters_update(world):
    db, jothidar, _, karthik = world
    conv = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    opened_at = conv["last_message_at"]
    saved = _say(conv, "user", "x" * 9000, tool_calls=[{"name": "get_horoscope", "args": {"dob": "1999-04-02"}}])
    assert len(saved["content"]) == 8000
    assert saved["tool_calls"] == [{"name": "get_horoscope", "args": {"dob": "1999-04-02"}}]
    assert conv["message_count"] == 1
    _say(conv, "assistant", "ok", mood="warm")
    assert conv["message_count"] == 2
    stored = db.rows("companion_conversations")[0]
    assert stored["message_count"] == 2
    assert stored["last_message_at"] > opened_at and stored["last_message_at"] == conv["last_message_at"]
    assert [m["conversation_id"] for m in db.rows("companion_messages")] == [conv["id"]] * 2


# 6. wrong tenant
def test_wrong_tenant_never_sees_rows(world):
    db, jothidar, _, karthik = world
    conv = run(store.open_conversation("t1", jothidar["id"], karthik["id"], "warm"))
    _say(conv, "user", "private question")
    assert run(store.recent_messages("t2", jothidar["id"], karthik["id"])) == []
    theirs = run(store.open_conversation("t2", jothidar["id"], karthik["id"], "serious"))
    assert theirs["id"] != conv["id"] and theirs["tenant_id"] == "t2" and theirs["mood"] == "serious"
    run(store.set_conversation_mood("t2", conv["id"], "happy"))
    assert next(r for r in db.rows("companion_conversations") if r["id"] == conv["id"])["mood"] == "warm"


# 7. memory slot
def test_level1_hooks_do_nothing_and_level2_uses_the_card():
    from app.companion.memory_card import MemoryCard
    p = memory.Level1History()
    assert run(p.context_for("t1", "c1", "u1", "hi")) == ""
    assert run(p.record_turn("t1", "c1", "u1", "hi", "hello")) is None
    assert run(p.forget("t1", "u1")) is None
    assert isinstance(memory.provider_for(1), memory.Level1History)
    assert isinstance(memory.provider_for(1, "mem0"), memory.Level1History)
    assert isinstance(memory.provider_for(2), MemoryCard)
    assert isinstance(memory.provider_for(2, "mem0"), MemoryCard)  # mem0 not built yet: card fallback
