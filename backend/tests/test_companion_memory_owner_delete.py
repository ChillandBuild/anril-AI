"""Memory gaps M4 and M5 of COMPANION_GAP_REVIEW.md (2026-11-11).

M4: the owner deletes a fact on the dashboard. The person's exact words leave their saved messages (no
marker), every character stops reading the chat from before the delete, and the fact cannot come back
from an old message. A NEW message from the person saves it again (Prem's decision).
M5: nothing is thrown away to make room (ceiling 500 facts), and the operator bell hears when memory
could not be saved or cleaned: one alert per business per problem per day.

Example: AstroTamil, character Aira, person Karthik ("k1"). He once wrote "amma ku sugar problem".
"""
import asyncio
import json

import pytest

from app.companion import alerts, memory, memory_card as card, memory_forget, memory_search, memory_sweep, store
from tests.test_companion_memory_recap_diary import NOW, YDAY_NOON, YESTERDAY, at, env, run  # noqa: F401

QUOTE = "amma ku sugar problem"
EMPTY = '{"ops": []}'


def person_row(env):
    return env.db.add("companion_end_users", id="karthik", tenant_id="t1", external_user_id="k1")


def sugar_fact(env, **more):
    return env.db.add("companion_memory_facts", tenant_id="t1", companion_id=env.companion["id"],
                      end_user_id="karthik", section="people", status="active", text="Mother has diabetes",
                      quote=QUOTE, updated_at=at(5), **more)


def contents(env, role=None):
    return [m["content"] for m in env.db.rows("companion_messages") if role in (None, m["role"])]


def bell(env):
    return [(i["tenant_id"], i["type"]) for i in env.db.rows("incidents")]


@pytest.fixture
def no_cleanup(monkeypatch):
    """The background AI cleanup (diary, recap, reworded pieces) has its own tests; here it does nothing."""
    async def nothing(tenant_id, end_user_id, items, today=None):
        return {}
    monkeypatch.setattr(memory_forget, "forget_things", nothing)


def delete_fact(env, fact):
    async def main():
        ok = await memory.forget_fact("t1", env.companion["id"], "k1", str(fact["id"]))
        await asyncio.gather(*memory._cleanups)
        return ok
    return run(main())


# --- M4: the person's words leave the saved chat ---------------------------------------------------

@pytest.mark.parametrize("content,left", [
    ("amma ku sugar problem. Naalaiku interview irukku", "Naalaiku interview irukku"),
    ("Naalaiku interview irukku, amma ku sugar problem", "Naalaiku interview irukku,"),
    ("Amma Ku Sugar Problem", ""),                       # any letter case; nothing left
    ("amma ku sugar problem!!", ""),                     # only punctuation left
    ("enakku velai kidaikkuma?", "enakku velai kidaikkuma?"),
])
def test_cut_words_removes_only_the_quote(content, left):
    assert store.cut_words(content, QUOTE) == left


def test_erasing_cuts_the_words_from_her_messages_and_drops_the_search_pieces(env):
    env.chat(("user", "amma ku sugar problem. Naalaiku interview irukku", 50),
             ("assistant", "Amma ku sugar problem ah? Kavalai padatha", 49),
             ("user", "Amma ku sugar problem", 48), ("user", "interview nalla pochu", 47))
    env.db.add("companion_messages", tenant_id="t2", companion_id="vasu", end_user_id="ravi", role="user",
               content="amma ku sugar problem")   # another business: never touched
    for i, text in enumerate(["Person: amma ku sugar problem\nAira: Kavalai padatha", "Person: interview nalla pochu"]):
        env.db.add("companion_memory_chunks", tenant_id="t1", companion_id=env.companion["id"],
                   end_user_id="karthik", kind="messages", source_key=f"m{i}", day=YESTERDAY, text=text)
    env.db.add("companion_memory_chunks", tenant_id="t1", companion_id=env.companion["id"], end_user_id="karthik",
               kind="diary", source_key=YESTERDAY, day=YESTERDAY, text="amma ku sugar problem, worried")

    assert run(store.erase_words("t1", "karthik", QUOTE)) == {"messages": 2, "pieces": 1, "capped": False}
    mine = [m for m in env.db.rows("companion_messages") if m["tenant_id"] == "t1"]
    assert [(m["role"], m["content"]) for m in mine] == [
        ("user", "Naalaiku interview irukku"),                       # the words are cut, no marker
        ("assistant", "Amma ku sugar problem ah? Kavalai padatha"),  # Aira's line: not read again (cutoff)
        ("user", "interview nalla pochu")]                           # the message that was only the words is gone
    assert not any("[" in m["content"] or "deleted" in m["content"].lower() for m in mine)
    assert contents(env)[-1] == "amma ku sugar problem"              # the other business's row
    kinds = [(c["kind"], c["text"][:20]) for c in env.db.rows("companion_memory_chunks")]
    assert kinds == [("messages", "Person: interview na"), ("diary", "amma ku sugar proble")]  # diary: the AI cleanup's


def test_a_fact_with_no_saved_quote_erases_nothing(env):
    env.chat(("user", "ok", 5))
    assert run(store.erase_words("t1", "karthik", "")) == {"messages": 0, "pieces": 0, "capped": False}
    assert run(store.erase_words("t1", "karthik", "ok")) == {"messages": 0, "pieces": 0, "capped": False}  # too short to be safe
    assert contents(env) == ["ok"]


def test_the_owner_deleting_a_fact_cleans_the_chat_and_starts_a_fresh_reading_window(env, no_cleanup):
    person_row(env)
    env.chat(("user", "amma ku sugar problem. Naalaiku interview irukku", 50), ("assistant", "Kavalai padatha", 49))
    fact = sugar_fact(env)
    assert delete_fact(env, fact)
    assert env.db.rows("companion_memory_facts") == []
    assert contents(env, "user") == ["Naalaiku interview irukku"]
    # The cutoff is her newest saved message's own time (the database's clock), so every message that
    # exists now is "before" and the next one is "after", whatever the app server's clock says.
    assert env.db.rows("companion_end_users")[0]["chat_read_after"] == at(49)
    assert env.db.rows("companion_memory_state")[0]["forget_pending"] is None   # cleanup done: hold lifted
    assert bell(env) == []


def test_the_reply_window_holds_nothing_from_before_the_delete(env):
    person_row(env)
    env.chat(("user", "amma ku sugar problem", 50), ("assistant", "Amma sugar pathi kavalai padatha", 49),
             ("user", "innaiku enna panra", 3), ("assistant", "Summa dhan", 2))
    cid = env.companion["id"]
    assert len(run(store.recent_messages("t1", cid, "karthik"))) == 4
    after = [m["content"] for m in run(store.recent_messages("t1", cid, "karthik", after=at(10)))]
    assert after == ["innaiku enna panra", "Summa dhan"]
    assert run(store.recent_messages("t1", cid, "karthik", after=at(0))) == []


def test_the_engine_reads_the_chat_from_after_the_delete_only(monkeypatch):
    from tests import test_companion_engine as eng
    fixture = eng.env.__wrapped__(monkeypatch)
    fixture.state["replies"] = ["[mood: calm] one", "[mood: calm] two"]
    eng.reply(fixture.jothidar["id"], "amma ku sugar problem")
    person = fixture.db.rows("companion_end_users")[0]
    run(store.set_read_after("t1", person["id"]))
    eng.reply(fixture.jothidar["id"], "vanakkam")
    assert [m["content"] for m in fixture.state["llm"][-1]["messages"][1:]] == ["vanakkam"]


def test_the_search_index_never_takes_the_characters_lines_from_before_the_delete(env):
    person_row(env)
    env.chat(("user", "Naalaiku interview irukku", 50), ("assistant", "Amma sugar pathi kavalai padatha", 49),
             ("user", "interview nalla pochu", 3), ("assistant", "Super da", 2))
    env.db.rows("companion_end_users")[0]["chat_read_after"] = at(10)
    messages = sorted(env.db.rows("companion_messages"), key=lambda m: m["created_at"])
    assert run(memory_search.index_messages("t1", env.companion["id"], "karthik", messages, card.IST)) >= 1
    indexed = "\n".join(c["text"] for c in env.db.rows("companion_memory_chunks"))
    assert "Amma sugar" not in indexed
    assert "Naalaiku interview irukku" in indexed and "Super da" in indexed  # her (cleaned) words and newer lines stay


def test_the_diary_never_reads_the_characters_lines_from_before_the_delete(env):
    person_row(env)
    env.chat(*[("user", f"interview prep {i}", 30 - i) for i in range(3)],
             ("assistant", "Amma sugar pathi kavalai padatha", 20), base=YDAY_NOON)
    env.db.rows("companion_end_users")[0]["chat_read_after"] = at(0)
    env.state["answers"].append('{"diary": "Prepared for the interview"}')
    assert run(memory_sweep.run_diary_job(NOW)) == {"diary": 1}
    seen = env.state["calls"][-1]["user"]
    assert "Amma sugar" not in seen and "interview prep 2" in seen


def test_the_note_writer_never_reads_the_characters_lines_from_before_the_delete(env):
    person_row(env)
    env.chat(("user", "Naalaiku interview irukku", 50), ("assistant", "Amma sugar pathi kavalai padatha", 49),
             ("user", "interview nalla pochu", 3), ("assistant", "Super da", 2))
    env.db.rows("companion_end_users")[0]["chat_read_after"] = at(10)
    env.state["answers"].append(EMPTY)
    messages = sorted(env.db.rows("companion_messages"), key=lambda m: m["created_at"])
    run(card.extract("t1", env.companion, "karthik", messages, None))
    seen = env.state["calls"][-1]["user"]
    assert "Amma sugar" not in seen and "Naalaiku interview irukku" in seen and "Super da" in seen


def test_an_old_message_cannot_bring_the_fact_back_but_a_new_one_saves_it_again(env, no_cleanup):
    person_row(env)
    env.chat(("user", "amma ku sugar problem. Naalaiku interview irukku", 50), ("assistant", "Kavalai padatha", 49))
    assert delete_fact(env, sugar_fact(env))
    add = {"op": "add", "section": "people", "text": "Mother has diabetes", "quote": QUOTE}
    # The note-writer re-reads the old chat and tries to save it again: no receipt in her words now.
    env.state["answers"].append(json.dumps({"ops": [add]}))
    old = sorted(env.db.rows("companion_messages"), key=lambda m: m["created_at"])
    assert run(card.extract("t1", env.companion, "karthik", old, None)).done["add"] == 0
    assert env.db.rows("companion_memory_facts") == []
    # She says it again tomorrow: it is hers to tell, so it is saved again.
    new = env.db.add("companion_messages", tenant_id="t1", companion_id=env.companion["id"], end_user_id="karthik",
                     role="user", content="amma ku sugar problem innum irukku", created_at=at(-5))
    env.state["answers"].append(json.dumps({"ops": [add]}))
    assert run(card.extract("t1", env.companion, "karthik", [new], None)).done["add"] == 1


def test_a_delete_that_cannot_clean_the_chat_still_deletes_the_fact_and_rings_the_bell(env, no_cleanup, monkeypatch):
    person_row(env)
    env.chat(("user", "amma ku sugar problem", 50))

    async def broken(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr(store, "erase_words", broken)
    assert delete_fact(env, sugar_fact(env))
    assert env.db.rows("companion_memory_facts") == []
    assert bell(env) == [("t1", "companion_memory_delete_incomplete")]
    assert QUOTE not in str(env.db.rows("incidents"))   # the alert never carries the person's words


def test_a_cleanup_that_fails_six_times_rings_the_bell(env, monkeypatch):
    async def broken(tenant_id, end_user_id, items, today=None):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(memory_forget, "forget_things", broken)
    cid = env.companion["id"]
    run(memory_forget.forget_or_queue("t1", cid, "karthik", ["Mother has diabetes"], tries=4))
    assert bell(env) == []                               # try 5: still queued
    run(memory_forget.forget_or_queue("t1", cid, "karthik", ["Mother has diabetes"], tries=5))
    assert bell(env) == [("t1", "companion_memory_cleanup_gave_up")]
    assert "diabetes" not in str(env.db.rows("incidents"))
    # It never gives up: still queued (so the hold on her memory stays), and the bell rang once.
    run(memory_forget.forget_or_queue("t1", cid, "karthik", ["Mother has diabetes"], tries=6))
    assert len(bell(env)) == 1
    assert env.db.rows("companion_memory_state")[0]["forget_pending"] == {"items": ["Mother has diabetes"], "tries": 7}


# --- M5: alerts, and nothing thrown away ------------------------------------------------------------

def test_one_alert_per_business_per_problem_per_day(env):
    for _ in range(3):
        run(alerts.alert("t1", "companion_memory_parked", "Guru could not save memories"))
    run(alerts.alert("t1", "companion_memory_fact_ceiling", "500 facts"))
    run(alerts.alert("t2", "companion_memory_parked", "Vasu could not save memories"))
    assert bell(env) == [("t1", "companion_memory_parked"), ("t1", "companion_memory_fact_ceiling"),
                         ("t2", "companion_memory_parked")]
    assert env.db.rows("incidents")[0]["detail"] == {"message": "Guru could not save memories"}
    env.db.rows("incidents")[0]["created_at"] = at(25 * 60)          # yesterday's alert: today rings again
    run(alerts.alert("t1", "companion_memory_parked", "Guru could not save memories"))
    assert bell(env).count(("t1", "companion_memory_parked")) == 2


def test_an_alert_that_cannot_be_saved_never_breaks_the_memory_run(monkeypatch):
    def down():
        raise RuntimeError("database down")
    monkeypatch.setattr(store, "get_supabase", down)
    run(alerts.alert("t1", "companion_memory_parked", "x"))          # no exception


def test_the_alert_kinds_match_the_database_rule():
    """Migration 263 lists the kinds the incidents table accepts: a kind missing there is silently lost."""
    from pathlib import Path
    sql = (Path(__file__).parent.parent / "supabase/migrations/263_companion_chat_read_after.sql").read_text()
    for kind in ("companion_memory_parked", "companion_memory_parked_dead", "companion_memory_cleanup_gave_up",
                 "companion_memory_delete_incomplete", "companion_memory_fact_ceiling"):
        assert f"'{kind}'" in sql and kind in alerts.__doc__
    for old in ("quality_red", "token_invalid", "sms_pe_tm_proof", "sms_credit_request"):
        assert f"'{old}'" in sql                                       # the existing kinds are kept


def test_a_person_at_the_ceiling_rings_the_bell_and_loses_no_older_fact(env, monkeypatch):
    monkeypatch.setattr(store, "MAX_FACTS_PER_PAIR", 3)
    for i in range(3):
        run(store.add_fact("t1", env.companion["id"], "karthik", "preferences", f"likes film {i}"))
    msg = env.db.add("companion_messages", tenant_id="t1", companion_id=env.companion["id"], end_user_id="karthik",
                     role="user", content="enakku oru thambi irukkan", created_at=at(5))
    answer = json.dumps({"ops": [{"op": "add", "section": "people", "text": "Has a younger brother",
                                  "quote": "oru thambi irukkan"}]})
    for _ in range(2):
        env.state["answers"].append(answer)
        assert run(card.extract("t1", env.companion, "karthik", [msg], None)).done["add"] == 0
    assert [f["text"] for f in env.db.rows("companion_memory_facts")] == [f"likes film {i}" for i in range(3)]
    assert bell(env) == [("t1", "companion_memory_fact_ceiling")]    # once, not once per run
    assert "thambi" not in str(env.db.rows("incidents")) and "brother" not in str(env.db.rows("incidents"))


def test_the_note_writer_is_shown_at_most_150_facts_slots_and_threads_always():
    facts = [{"id": f"p{i}", "section": "preferences", "text": f"likes film {i}", "created_at": f"2026-01-01T00:00:{i:06d}"}
             for i in range(200)]
    facts.insert(0, {"id": "home", "section": "profile", "slot": "home_city", "text": "Lives in Chennai",
                     "created_at": "2020-01-01"})
    facts.insert(1, {"id": "zoho", "section": "threads", "text": "Zoho interview", "created_at": "2020-01-02"})
    assert card.note_writer_facts(facts[:150]) == facts[:150]        # a normal person: everything
    shown = card.note_writer_facts(facts)
    ids = [f["id"] for f in shown]
    assert len(shown) == card.NOTE_FACTS and ids[:2] == ["home", "zoho"]
    assert "p199" in ids and "p52" in ids and "p51" not in ids       # the newest 148 others, oldest left out
    assert ids == [f["id"] for f in facts if f["id"] in set(ids)]    # order kept


def test_a_fact_the_note_writer_was_not_shown_is_not_saved_twice(env, monkeypatch):
    monkeypatch.setattr(card, "NOTE_FACTS", 2)
    for i in range(4):
        run(store.add_fact("t1", env.companion["id"], "karthik", "preferences", f"likes film {i}"))
    msg = env.db.add("companion_messages", tenant_id="t1", companion_id=env.companion["id"], end_user_id="karthik",
                     role="user", content="enakku film 0 pidikkum", created_at=at(5))
    env.state["answers"].append(json.dumps({"ops": [{"op": "add", "section": "preferences", "text": "Likes film 0",
                                                     "quote": "film 0 pidikkum"}]}))
    assert run(card.extract("t1", env.companion, "karthik", [msg], None)).done["add"] == 0
    assert "likes film 0" not in env.state["calls"][-1]["user"] and "likes film 3" in env.state["calls"][-1]["user"]
    assert len(env.db.rows("companion_memory_facts")) == 4


# --- found by the code review of 2026-11-11 ---------------------------------------------------------

@pytest.mark.parametrize("content,quote,left", [
    ("Amma-ku  sugar problem irukku, naalaiku interview", "amma ku sugar problem irukku", "naalaiku interview"),
    ("AMMA KU SUGAR PROBLEM!!! seri", "amma ku sugar problem", "seri"),
    ("நான் சென்னை-ல இருக்கேன், சரி", "நான் சென்னை ல இருக்கேன்", "சரி"),
    ("my number is 98765 43210 call me", "my number is [number] call me", ""),   # the saved quote hides digits
    ("sugarcane juice kudichen", "sugar", "sugarcane juice kudichen"),            # whole words only
])
def test_the_words_are_found_the_way_the_receipt_found_them(content, quote, left):
    assert store.cut_words(content, quote) == left


def test_the_erase_reads_text_exactly_as_a_receipt_does():
    import unicodedata
    for text in ["Amma-ku  sugar problem irukku, naalaiku interview!", "நான் சென்னை-ல இருக்கேன்.",
                 "Straße ÄB c_d 12-34", "  ...hi\u200d there  ", "a_b", ""]:
        assert store._norm_map(unicodedata.normalize("NFC", text))[0] == card._norm_quote(text)


def test_a_delete_finds_words_she_typed_with_other_punctuation(env, no_cleanup):
    person_row(env)
    env.chat(("user", "Amma-ku sugar problem, naalaiku interview", 50), ("assistant", "Kavalai padatha", 49))
    env.db.add("companion_memory_chunks", tenant_id="t1", companion_id=env.companion["id"], end_user_id="karthik",
               kind="messages", source_key="m0", day=YESTERDAY, text="Person: Amma-ku sugar problem, naalaiku interview")
    assert card.find_source(QUOTE, env.db.rows("companion_messages")) is not None   # the receipt matched this
    assert delete_fact(env, sugar_fact(env))
    assert contents(env, "user") == ["naalaiku interview"]
    assert env.db.rows("companion_memory_chunks") == [] and bell(env) == []


def test_words_that_cannot_be_found_ring_the_bell(env, no_cleanup):
    person_row(env)
    env.chat(("user", "vera edho sonnen", 50))
    assert delete_fact(env, sugar_fact(env))
    assert contents(env, "user") == ["vera edho sonnen"]
    assert bell(env) == [("t1", "companion_memory_delete_incomplete")]


def test_a_failed_erase_still_moves_the_cutoff_and_every_failed_delete_rings(env, no_cleanup, monkeypatch):
    person_row(env)
    env.chat(("user", QUOTE, 50), ("assistant", "Kavalai padatha", 49))

    async def broken(*a, **k):
        raise RuntimeError("timeout")
    monkeypatch.setattr(store, "erase_words", broken)
    monkeypatch.setattr(store, "_now", lambda: "2099-01-01T00:00:00+00:00")     # an app clock that is far off
    assert delete_fact(env, sugar_fact(env)) and delete_fact(env, sugar_fact(env))
    assert env.db.rows("companion_end_users")[0]["chat_read_after"] == at(49)   # set, and on the message clock
    assert bell(env) == [("t1", "companion_memory_delete_incomplete")] * 2      # Priya's does not hide Divya's


def test_a_person_with_no_saved_chat_gets_the_cutoff_from_the_clock(env):
    person_row(env)
    assert run(store.set_read_after("t1", "karthik")) == env.db.rows("companion_end_users")[0]["chat_read_after"]


def test_a_long_chat_is_checked_past_the_first_1000_messages(env, monkeypatch):
    env.chat(("user", "Amma ku sugar problem", 5000), *[("user", f"msg {i}", 4000 - i) for i in range(1100)])
    monkeypatch.setattr(store, "ERASE_SCAN", 1000)     # more chat than is checked: said, not silent
    assert run(store.erase_words("t1", "karthik", QUOTE)) == {"messages": 0, "pieces": 0, "capped": True}
    monkeypatch.setattr(store, "ERASE_SCAN", 5000)
    assert run(store.erase_words("t1", "karthik", QUOTE)) == {"messages": 1, "pieces": 0, "capped": False}
    assert len(contents(env, "user")) == 1100


def test_while_the_cleanup_fails_the_delete_stays_queued_from_the_first_second(env, monkeypatch):
    person_row(env)
    env.chat(("user", QUOTE, 50))
    seen = []

    async def broken(tenant_id, end_user_id, items, today=None):
        seen.append(env.db.rows("companion_memory_state")[0]["forget_pending"])   # already queued when it starts
        raise RuntimeError("gemini down")
    monkeypatch.setattr(memory_forget, "forget_things", broken)
    assert delete_fact(env, sugar_fact(env))
    assert seen == [{"items": ["Mother has diabetes"], "tries": 0}]
    assert env.db.rows("companion_memory_state")[0]["forget_pending"] == {"items": ["Mother has diabetes"], "tries": 1}
