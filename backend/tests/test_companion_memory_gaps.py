"""Memory gaps M6-M10 of COMPANION_GAP_REVIEW.md (2026-11-11): privacy filter and secret masking,
one live fact per slot, threads with a due date / ask-once / expiry, the honesty rule, and card overflow."""
import asyncio
import json

import pytest

from app.companion import memory_card as card
from app.companion import store
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    return fake


@pytest.fixture
def llm(monkeypatch):
    state = {"calls": [], "answers": []}

    async def fake(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4, model=None):
        state["calls"].append({"messages": messages, "purpose": purpose, "tenant_id": tenant_id, "model": model})
        nxt = state["answers"].pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    monkeypatch.setattr(card.ai_reply, "_llm_chat", fake)
    return state


def run(coro):
    return asyncio.run(coro)


GURU = {"id": "guru", "language": "ta-en"}


def chat(db, *lines):
    """Rows in companion_messages for Priya and Guru: ("user", "naan Chennai la irukken"), ..."""
    rows = [{"id": f"m{i}", "role": role, "content": content, "created_at": f"2026-11-1{i}T04:00:00+00:00"}
            for i, (role, content) in enumerate(lines, 1)]
    for m in rows:
        db.add("companion_messages", tenant_id="t1", companion_id="guru", end_user_id="priya", **m)
    return rows


# --- M9: privacy ----------------------------------------------------------------------------------

@pytest.mark.parametrize("typed,saved", [
    ("my OTP is 482913", "my OTP is [hidden]"),
    ("482913 is my otp", "[hidden] is my otp"),
    ("ATM pin 4821", "ATM pin [hidden]"),
    ("card 4111 1111 1111 1111", "card [hidden]"),
    ("aadhaar 2345 6789 0123", "aadhaar [hidden]"),
    ("PAN ABCDE1234F", "PAN [hidden]"),
    ("IFSC HDFC0001234", "IFSC [hidden]"),
    ("account number 123456789", "account number [hidden]"),
    ("password is amma123", "password is [hidden]"),
])
def test_a_secret_is_hidden_before_the_chat_message_is_saved(typed, saved):
    assert card.mask_secrets(typed) == saved


@pytest.mark.parametrize("typed", [
    "call me on 9876543210", "+91 98765 43210 ku call pannu", "919876543210", "en mail priya@gmail.com",
    "born 15-08-1990 at 10:30", "15-08-1990 9876543210", "pin code 600001", "paid 4500 rent in 2026",
    "salary 1200000 nu sonnanga", "password marandhuten", "naan Chennai la irukken", "",
])
def test_phone_email_dates_and_plain_numbers_are_saved_as_typed(typed):
    assert card.mask_secrets(typed) == typed


@pytest.mark.parametrize("text", [
    "Email is priya@gmail.com", "PAN is ABCDE1234F", "ATM pin 4821", "4821 is my pin", "Lives at door no 14",
    "Flat number 12B, Adyar",
])
def test_email_pan_pin_and_door_numbers_never_become_a_fact(text):
    assert card._clean_text(text) is None


@pytest.mark.parametrize("text", ["Bought a new flat", "Pin code area is Adyar", "Lives in Chennai", "Born 15-08-1990"])
def test_ordinary_facts_still_pass_the_filter(text):
    assert card._clean_text(text) == text


def test_recap_and_diary_mask_an_email_and_drop_a_pin_line():
    assert card.redact("write to priya@gmail.com, PAN ABCDE1234F") == "write to [email], PAN [number]"
    assert card.clean_recap("- Shared her mail priya@gmail.com\n- ATM pin 4821\n- Interview Friday") == \
        "- Shared her mail [email]\n- Interview Friday"
    assert card.clean_diary("Told Guru her ATM pin 4821") is None


def test_a_quote_never_stores_an_email_or_a_pin():
    said = [{"id": "m1", "role": "user", "content": "en mail priya@gmail.com, ATM pin 4821 nu vechirukken"}]
    assert card._receipt({"quote": "en mail priya@gmail.com"}, said) == ("en mail [email]", "m1")
    assert card._receipt({"quote": "ATM pin 4821"}, said) is None


# --- M6: one live fact per slot -------------------------------------------------------------------

def fact(db, text, section="profile", companion="guru", **more):
    return db.add("companion_memory_facts", tenant_id="t1", companion_id=companion, end_user_id="priya",
                  section=section, text=text, **{"status": "active", "valid_from": None, "valid_to": None, **more})


def ops(*items):
    return json.dumps({"ops": list(items)})


MOVED = {"op": "add", "section": "profile", "text": "Lives in Bengaluru", "quote": "Bengaluru ku shift aaiten",
         "valid_from": "2026-11-10", "slot": "home_city"}
TODAY = card.date(2026, 11, 11)


def test_a_new_home_city_closes_the_old_one_and_the_card_shows_one(db, llm):
    old = fact(db, "Lives in Chennai", slot="home_city", valid_from="2024-01-01")
    said = chat(db, ("user", "naan ippo Bengaluru ku shift aaiten"))
    llm["answers"].append(ops(MOVED))
    result = run(card.extract("t1", GURU, "priya", said, None, today=TODAY))
    rows = {r["text"]: r for r in db.rows("companion_memory_facts")}
    assert (rows["Lives in Chennai"]["status"], rows["Lives in Chennai"]["valid_to"]) == ("closed", "2026-11-10")
    assert (rows["Lives in Bengaluru"]["status"], rows["Lives in Bengaluru"]["slot"]) == ("active", "home_city")
    assert result.done["add"] == 1
    assert [(f["id"], f["status"]) for f in result.closed] == [(old["id"], "closed")]   # goes to search
    assert [f["text"] for f in result.written] == ["Lives in Bengaluru"]
    assert card.render(db.rows("companion_memory_facts")) == \
        "Profile: Lives in Bengaluru (since 10 Nov 2026) · Lives in Chennai (until 10 Nov 2026)"


def test_a_slot_change_with_no_date_closes_the_old_fact_on_the_persons_today(db, llm):
    fact(db, "Works at TCS", slot="job")
    said = chat(db, ("user", "Zoho la join panniten"))
    llm["answers"].append(ops({"op": "add", "section": "profile", "text": "Works at Zoho",
                               "quote": "Zoho la join panniten", "slot": "job"}))
    run(card.extract("t1", GURU, "priya", said, None, today=TODAY))
    assert next(r for r in db.rows("companion_memory_facts") if r["text"] == "Works at TCS")["valid_to"] == "2026-11-11"


def test_a_close_sent_with_the_slot_add_does_not_wipe_the_closing_date(db, llm):
    fact(db, "Lives in Chennai", slot="home_city")
    said = chat(db, ("user", "naan ippo Bengaluru ku shift aaiten"))
    llm["answers"].append(ops(MOVED, {"op": "close", "ref": "f1", "valid_to": None}))
    result = run(card.extract("t1", GURU, "priya", said, None, today=TODAY))
    old = next(r for r in db.rows("companion_memory_facts") if r["text"] == "Lives in Chennai")
    assert old["valid_to"] == "2026-11-10" and result.done["close"] == 0 and len(result.closed) == 1


@pytest.mark.parametrize("op", [
    {**MOVED, "slot": "favourite_city"},                    # not a slot we keep
    {**MOVED, "section": "life"},                           # slots are for profile facts only
])
def test_an_unknown_slot_is_saved_as_a_plain_fact_and_replaces_nothing(db, llm, op):
    fact(db, "Lives in Chennai", slot="home_city")
    said = chat(db, ("user", "naan ippo Bengaluru ku shift aaiten"))
    llm["answers"].append(ops(op))
    run(card.extract("t1", GURU, "priya", said, None, today=TODAY))
    rows = {r["text"]: r for r in db.rows("companion_memory_facts")}
    assert rows["Lives in Chennai"]["status"] == "active" and not rows["Lives in Bengaluru"].get("slot")


def test_old_parked_messages_never_replace_a_newer_slot(db, llm):
    fact(db, "Lives in Bengaluru", slot="home_city")
    said = chat(db, ("user", "naan Chennai la irukken"), ("user", "Ravi nu oru friend irukkan"))
    llm["answers"].append(ops(
        {"op": "add", "section": "profile", "text": "Lives in Chennai", "quote": "naan Chennai la irukken",
         "slot": "home_city"},
        {"op": "add", "section": "people", "text": "Friend Ravi", "quote": "Ravi nu oru friend irukkan"}))
    run(card.extract("t1", GURU, "priya", said, None, today=card.date(2026, 3, 1), late=True))
    assert sorted((r["text"], r["status"]) for r in db.rows("companion_memory_facts")) == \
        [("Friend Ravi", "active"), ("Lives in Bengaluru", "active")]


def test_the_note_writer_sees_each_slot_and_the_slot_list(db, llm):
    fact(db, "Lives in Chennai", slot="home_city")
    fact(db, "Likes filter coffee", section="preferences")
    prompt, _refs = card.build_extraction_prompt("ta-en", db.rows("companion_memory_facts"), [])
    assert "f1 [profile:home_city] Lives in Chennai" in prompt[1]["content"]
    assert "f2 [preferences] Likes filter coffee" in prompt[1]["content"]
    assert "home_city, job, studies, marital_status" in prompt[0]["content"]
    assert "{slots}" not in prompt[0]["content"]


def test_business_scope_shows_only_the_newest_fact_of_a_slot(db):
    db.add("companion_tenant_settings", tenant_id="t1", memory_scope="business")
    fact(db, "Lives in Chennai", slot="home_city", companion="guru", created_at="2026-01-01T00:00:00+00:00")
    fact(db, "Lives in Bengaluru", slot="home_city", companion="vastu", created_at="2026-06-01T00:00:00+00:00")
    fact(db, "Has a dog Bruno", section="life", companion="guru", created_at="2026-02-01T00:00:00+00:00")
    seen = run(card.visible_facts("t1", "guru", "priya"))
    assert [f["text"] for f in seen] == ["Has a dog Bruno", "Lives in Bengaluru"]
    assert len(db.rows("companion_memory_facts")) == 3     # read-side only: nothing closed or deleted


# --- M7: threads with a due date, asked once, then dropped ----------------------------------------

def test_the_card_splits_threads_into_due_open_and_already_asked(db):
    facts = [fact(db, "Zoho interview", "threads", valid_from="2026-11-10"),
             fact(db, "CA exam", "threads", valid_from="2026-12-05"),
             fact(db, "Visa result", "threads", created_at="2026-11-05T00:00:00+00:00"),
             fact(db, "Amma surgery", "threads", valid_from="2026-11-08", asked_at="2026-11-09T04:00:00+00:00"),
             fact(db, "Bank loan", "threads", status="closed", valid_to="2026-11-01"),
             fact(db, "House hunt", "threads", status="closed", expired_at="2026-11-02T00:00:00+00:00")]
    assert card.render(facts, today=TODAY).splitlines() == [
        "Due, ask about it once, early in this chat (today is 11 Nov 2026): Zoho interview (10 Nov 2026)",
        "Open threads: CA exam (5 Dec 2026) · Visa result",
        "Already asked about, wait for them to bring it up: Amma surgery (8 Nov 2026)",
        "Finished threads: Bank loan (until Nov 2026)",
    ]


def test_a_due_thread_is_asked_once_then_moves_to_already_asked(db, monkeypatch):
    from app.companion import memory_search

    async def no_hits(*a, **k):
        return []
    monkeypatch.setattr(memory_search, "search", no_hits)
    yesterday = (card.datetime.now(card.timezone.utc).date() - card.timedelta(days=2)).isoformat()
    due = fact(db, "Zoho interview", "threads", valid_from=yesterday)
    later = fact(db, "CA exam", "threads", valid_from="2999-12-05")
    memory = card.MemoryCard()
    first = run(memory.context_for("t1", "guru", "priya", "Vanakkam", companion=GURU))
    assert first.startswith("Due, ask about it once, early in this chat") and "Zoho interview" in first
    assert not db.rows("companion_memory_facts")[0].get("asked_at")       # only after the reply is saved
    run(memory.record_turn("t1", "guru", "priya", "Vanakkam", "Interview epdi pochu?"))
    rows = {r["id"]: r for r in db.rows("companion_memory_facts")}
    assert rows[due["id"]]["asked_at"] and not rows[later["id"]].get("asked_at")
    second = run(memory.context_for("t1", "guru", "priya", "Seri", companion=GURU))
    assert "Due, ask" not in second
    assert "Already asked about, wait for them to bring it up: Zoho interview" in second
    run(memory.record_turn("t1", "guru", "priya", "Seri", "ok"))          # nothing due: no write
    assert card._due_shown == {}


def test_threads_nobody_closed_leave_the_card(db):
    for text, more in [("Old interview", {"valid_from": "2026-11-03"}),              # 8 days past
                       ("Last week exam", {"valid_from": "2026-11-05"}),             # 6 days past: stays
                       ("Visa result", {"created_at": "2026-10-01T00:00:00+00:00"}),  # no date, 41 days old
                       ("Loan result", {"created_at": "2026-11-01T00:00:00+00:00"})]:
        fact(db, text, "threads", **more)
    fact(db, "Lives in Chennai", valid_from="2020-01-01")
    count = run(store.expire_threads("t1", "guru", "priya", dated_before="2026-11-04",
                                     undated_before="2026-10-12T00:00:00+00:00"))
    assert count == 2
    assert card.render(db.rows("companion_memory_facts"), today=TODAY).splitlines() == [
        "Due, ask about it once, early in this chat (today is 11 Nov 2026): Last week exam (5 Nov 2026)",
        "Open threads: Loan result",
        "Profile: Lives in Chennai (since Jan 2020)",
    ]
    expired = [r for r in db.rows("companion_memory_facts") if r.get("expired_at")]
    assert sorted(r["text"] for r in expired) == ["Old interview", "Visa result"]
    assert all(r["status"] == "closed" for r in expired)


def test_the_note_writer_is_told_a_threads_date_is_the_day_it_happens():
    prompt, _ = card.build_extraction_prompt("en", [], [])
    assert 'For a thread, "valid_from" is the day the thing HAPPENS' in prompt[0]["content"]


# --- M10: honesty, card overflow, the note-writer's model and day ---------------------------------

def test_the_character_is_told_to_say_not_told_yet_and_to_answer_what_she_raises_herself():
    from app.companion.platform_rules import PLATFORM_RULES
    assert "say they have not told you that yet and ask them" in PLATFORM_RULES
    assert "never say you forgot it or that it was removed" in PLATFORM_RULES
    assert "when they raise it or ask about it themselves, answer them normally" in PLATFORM_RULES
    assert "delete" not in PLATFORM_RULES.split("\n9. ")[1]     # rule 9 never hints that deleting exists


def test_the_note_writer_uses_its_own_model_for_the_card_and_the_diary(db, llm):
    said = chat(db, ("user", "naan Chennai la irukken"))
    llm["answers"] += [ops(), json.dumps({"diary": "Spoke about Chennai."})]
    run(card.extract("t1", GURU, "priya", said, None, today=TODAY))
    run(card.write_diary("t1", GURU, TODAY, messages=said))
    assert [c["model"] for c in llm["calls"]] == ["google/gemini-3.5-flash-lite"] * 2


def test_with_no_day_given_the_note_writer_uses_the_persons_own_day(db, llm):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    db.add("companion_end_users", id="priya", tenant_id="t1", timezone="Pacific/Kiritimati")   # UTC+14
    said = chat(db, ("user", "naan Chennai la irukken"))
    llm["answers"].append(ops())
    run(card.extract("t1", GURU, "priya", said, None))
    local = datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()
    assert f"Use today's date ({local})" in llm["calls"][0]["messages"][0]["content"]


def test_a_fact_the_full_card_has_no_room_for_is_still_found_by_search(db, monkeypatch, caplog):
    from app.companion import memory_search
    for i in range(40):
        fact(db, f"Friend number {i:02d} is called Nanban{i:02d} and lives far away in town {i:02d}", "people",
             created_at=f"2026-01-{i + 1:02d}T00:00:00+00:00" if i < 31 else f"2026-02-{i - 30:02d}T00:00:00+00:00")
    facts = card.newest_first(db.rows("companion_memory_facts"))
    shown, cut = card._fact_line(facts[0]), card._fact_line(facts[-1])
    assert shown in card.render(facts) and cut not in card.render(facts)

    async def hits(*a, **k):
        return [{"id": "c1", "kind": "fact", "day": "2026-01-01", "text": cut},
                {"id": "c2", "kind": "fact", "day": "2026-02-09", "text": shown}]
    monkeypatch.setattr(memory_search, "search", hits)
    with caplog.at_level("INFO", logger="app.companion.memory_card"):
        context = run(card.MemoryCard().context_for("t1", "guru", "priya", "Nanban00 epdi irukkan?", companion=GURU))
    assert context.count(cut) == 1 and context.count(shown) == 1      # found once; the shown one not repeated
    assert "memory card full" in caplog.text and "Nanban" not in caplog.text    # the drop is logged, not the text


def test_new_and_reworded_facts_are_indexed_for_search_as_the_card_shows_them(db, monkeypatch):
    from app.companion import memory_search

    async def embed(texts, kind, tenant_id, **k):
        return [None] * len(texts)
    monkeypatch.setattr(memory_search.memory_embed, "embed", embed)
    active = fact(db, "Lives in Bengaluru", slot="home_city", valid_from="2026-11-10")
    closed = fact(db, "Lives in Chennai", status="closed", valid_to="2026-11-10")
    run(memory_search.index_facts("t1", "guru", "priya", [active, closed], TODAY))
    assert sorted((c["source_key"], c["text"], c["day"]) for c in db.rows("companion_memory_chunks")) == sorted([
        (active["id"], "Lives in Bengaluru (since 10 Nov 2026)", "2026-11-10"),
        (closed["id"], "Lives in Chennai (until 10 Nov 2026)", "2026-11-10")])


def test_a_stale_thread_is_hidden_even_before_the_nightly_job_expires_it(db):
    """Priya went quiet for two months: the nightly job never visited her, so the rows are still active."""
    facts = [fact(db, "Zoho interview", "threads", valid_from="2026-09-01", created_at="2026-08-20T10:00:00+00:00"),
             fact(db, "Wants to learn Kannada", "threads", created_at="2026-09-01T10:00:00+00:00"),
             fact(db, "Visa appointment", "threads", valid_from="2026-11-08", created_at="2026-11-01T10:00:00+00:00")]
    shown = card.render(facts, today=TODAY)
    assert "Visa appointment" in shown
    assert "Zoho interview" not in shown and "Kannada" not in shown
