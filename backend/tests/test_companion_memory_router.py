"""Memory gap M10: one shared rewrite call per reply, the small-talk rule, the joint size ceiling,
and the person's own today. No network: the LLM, the embeddings and the database are fakes.

People: Priya chats with Guru (AstroTamil). "amma operation epdi pochu" is Tanglish for
"how did mother's surgery go"; the saved fact line is English."""
import asyncio
import json
import logging
import time
from datetime import date, datetime, timezone

import pytest

from app.companion import engine, memory, memory_card as card, memory_forget, memory_search, playground, store
from app.companion.kb import rewrite as rw
from app.companion.kb.rewrite import Rewrite
from app.companion.kb.types import KbResult
from tests.test_companion_memory_recap_diary import NOW, TODAY, at, env, run  # noqa: F401  (env is a fixture)

REAL_SHARED_REWRITE = engine._shared_rewrite   # conftest switches it off for every other test file
TANGLISH = "amma operation epdi pochu"
# The test embedding only knows shared words, so the English version repeats the fact line's words.
SURGERY = Rewrite(needs_docs=False, english_query="Was mother's surgery on Friday ok",
                  tamil_query="அம்மாவின் அறுவை சிகிச்சை எப்படி நடந்தது?", topic_query=None, key_terms=[])
SMALL_TALK = Rewrite(needs_docs=False, english_query="", tamil_query="", topic_query=None, key_terms=[],
                     needs_memory=False)


async def ready(value):
    return value


def task_of(value):
    """Inside a running loop: a finished rewrite task, as the engine hands it to both searches."""
    return asyncio.ensure_future(ready(value))


# ---- the rewrite's answer -------------------------------------------------------------------------

def test_the_prompt_asks_for_needs_memory_and_shows_all_three_cases():
    assert '"needs_memory": true or false' in rw.REWRITE_PROMPT
    assert '{"needs_docs": false, "needs_memory": true,' in rw.REWRITE_PROMPT    # own life, no book
    assert '{"needs_docs": false, "needs_memory": false,' in rw.REWRITE_PROMPT   # good morning guru


@pytest.mark.parametrize("answer, expected", [
    ({"needs_docs": False, "needs_memory": False, "english_query": "", "tamil_query": ""}, False),
    ({"needs_docs": False, "needs_memory": True, "english_query": "q", "tamil_query": "q"}, True),
    ({"needs_docs": True, "english_query": "q", "tamil_query": "q"}, True),                       # left out
    ({"needs_docs": True, "needs_memory": "no", "english_query": "q", "tamil_query": "q"}, True),  # not a boolean
])
def test_needs_memory_is_false_only_when_the_model_says_false(answer, expected):
    assert rw.parse_rewrite(json.dumps(answer)).needs_memory is expected


def test_a_failed_rewrite_and_an_old_style_rewrite_still_search_memory():
    assert rw.fallback_rewrite("hi").needs_memory is True
    assert Rewrite(True, "q", "q", None, []).needs_memory is True
    assert run(rw.rewrite("t1", "   ")).needs_memory is False   # nothing typed, nothing to look up


# ---- waiting for the shared call ------------------------------------------------------------------

def test_settled_gives_the_answer_when_it_is_ready_and_none_when_there_is_no_call():
    async def go():
        return await rw.settled(task_of(SURGERY)), await rw.settled(None)
    assert run(go()) == (SURGERY, None)


def test_a_slow_rewrite_is_not_waited_for_and_keeps_running_for_the_file_search(caplog):
    async def go():
        slow = asyncio.ensure_future(asyncio.sleep(0.2, result=SURGERY))
        early = await rw.settled(slow, seconds=0.01)
        return early, slow.cancelled(), await slow
    assert run(go()) == (None, False, SURGERY)
    assert "memory search uses the message as typed" in caplog.text


def test_a_broken_rewrite_task_gives_none_not_an_error():
    async def boom():
        raise RuntimeError("gemini down")
    async def go():
        return await rw.settled(asyncio.ensure_future(boom()))
    assert run(go()) is None


# ---- memory search uses the English and Tamil-script versions --------------------------------------

def test_rewritten_queries_are_only_what_the_typed_message_does_not_already_say():
    assert memory_search.rewritten_queries(SURGERY, TANGLISH) == [SURGERY.english_query, SURGERY.tamil_query]
    assert memory_search.rewritten_queries(None, TANGLISH) == []
    assert memory_search.rewritten_queries(rw.fallback_rewrite(TANGLISH), TANGLISH) == []      # failed: as typed
    same = Rewrite(False, "How is  Amma?", "how is amma?", None, [])
    assert memory_search.rewritten_queries(same, "how is amma?") == []                          # English message
    assert memory_search.rewritten_queries(Rewrite(False, "Is amma ok?", "Is amma ok?", None, []), "amma ok va") \
        == ["Is amma ok?"]                                                                      # Tamil == English


def test_a_piece_found_by_two_versions_of_the_question_is_ranked_once():
    rows = [{"id": "a", "source": "vector", "score": 0.72}, {"id": "a", "source": "vector", "score": 0.91},
            {"id": "a", "source": "trigram", "score": 0.5}, {"id": "b", "source": "vector", "score": 0.8}]
    best = {(r["id"], r["source"]): r["score"] for r in memory_search.best_rows(rows)}
    assert best == {("a", "vector"): 0.91, ("a", "trigram"): 0.5, ("b", "vector"): 0.8}


def surgery_fact(env):
    cid = env.companion["id"]
    fact = run(store.add_fact("t1", cid, "karthik", "people", "Mother's surgery is on Friday", None))
    run(memory_search.index_facts("t1", cid, "karthik", [fact], date(2026, 11, 10)))
    return cid


def test_the_english_version_finds_the_fact_the_tanglish_message_misses(env):
    cid = surgery_fact(env)
    assert run(memory_search.search("t1", cid, "karthik", TANGLISH)) == []
    hits = run(memory_search.search("t1", cid, "karthik", TANGLISH, rewrite=SURGERY))
    assert [h["text"] for h in hits] == ["Mother's surgery is on Friday"]


def test_one_embedding_call_carries_every_version_and_the_typed_message_is_always_searched(env, monkeypatch):
    cid = surgery_fact(env)
    embedded, asked = [], []
    real_embed, real_match = memory_search.memory_embed.embed, store.match_chunks

    async def embed(texts, kind, tenant_id, model=None, retries=True):
        embedded.append(list(texts))
        return await real_embed(texts, kind, tenant_id)

    async def match(tenant_id, companions, end_user_id, vector, words, count):
        asked.append(words)
        return await real_match(tenant_id, companions, end_user_id, vector, words, count)
    monkeypatch.setattr(memory_search.memory_embed, "embed", embed)
    monkeypatch.setattr(store, "match_chunks", match)
    run(memory_search.search("t1", cid, "karthik", TANGLISH, rewrite=SURGERY))
    assert embedded == [[TANGLISH, SURGERY.english_query, SURGERY.tamil_query]]
    assert asked == [TANGLISH, SURGERY.english_query, SURGERY.tamil_query]
    embedded.clear(), asked.clear()
    run(memory_search.search("t1", cid, "karthik", TANGLISH))     # no rewrite: exactly one search, as before
    assert embedded == [[TANGLISH]] and asked == [TANGLISH]


# ---- the card: small talk, and what the rewrite adds ------------------------------------------------

def priya_has_history(env):
    cid = surgery_fact(env)
    run(store.add_fact("t1", cid, "karthik", "profile", "works at TCS", None))
    run(store.upsert_diary("t1", cid, "karthik", "2026-11-09", "nervous about the Zoho interview"))
    run(store.set_recap("t1", cid, "karthik", "- Interview at Infosys 3 pm", TODAY, at(30)))
    return cid


def context(cid, message, rewrite):
    async def go():
        return await card.MemoryCard().context_for("t1", cid, "karthik", message,
                                                   rewrite=None if rewrite is None else task_of(rewrite))
    return run(go())


def test_small_talk_gets_the_card_and_todays_note_but_no_search_and_no_recent_days(env, monkeypatch):
    cid = priya_has_history(env)
    searched = []

    async def search(*a, **k):
        searched.append(a)
        return []
    monkeypatch.setattr(memory_search, "search", search)
    ctx = context(cid, "hi guru", SMALL_TALK)
    assert "works at TCS" in ctx and "Earlier today:\n- Interview at Infosys 3 pm" in ctx
    assert "Recent days" not in ctx and "From earlier conversations" not in ctx and searched == []


def test_a_real_question_gets_recent_days_and_the_search_gets_the_rewrite(env, monkeypatch):
    cid = priya_has_history(env)
    seen = {}
    real = memory_search.search

    async def search(*a, **k):
        seen.update(k)
        return await real(*a, **k)
    monkeypatch.setattr(memory_search, "search", search)
    ctx = context(cid, TANGLISH, SURGERY)
    assert seen["rewrite"] is SURGERY and "Recent days:\n- 9 Nov: nervous about the Zoho interview" in ctx


def test_without_a_rewrite_the_context_is_what_it_was_before(env):
    cid = priya_has_history(env)
    ctx = context(cid, "hi", None)
    assert ctx.index("works at TCS") < ctx.index("Earlier today:") < ctx.index("Recent days:")


# ---- one ceiling for everything memory adds ---------------------------------------------------------

def block(header, count, size):
    return "\n".join([header] + [f"- {i} " + "x" * size for i in range(count)])


def hit(i, size=300, kind="diary", day="2026-08-01"):
    return {"id": f"h{i}", "kind": kind, "day": day, "text": f"old {i} " + "y" * size, "rrf": 1.0 / (i + 1)}


def test_the_card_and_todays_note_always_fit_whole_under_the_ceiling():
    assert card.CONTEXT_CAP + len("Earlier today:\n") + card.RECAP_CAP + 2 < card.JOINT_CAP
    assert card.JOINT_CAP < card.CONTEXT_CAP + card.RECAP_CAP + card.DIARY_CAP + memory_search.BLOCK_CAP


def test_everything_is_kept_when_it_fits():
    recap, diary = block("Earlier today:", 3, 40), block("Recent days:", 3, 40)
    kept_recap, kept_diary, found, dropped = card.fit_memory("card", recap, diary, [hit(0, 50)], date(2026, 11, 10))
    assert (kept_recap, kept_diary, dropped) == (recap, diary, {}) and "old 0" in found


def test_over_the_ceiling_recent_days_give_way_first_then_old_chats_never_the_card_or_today():
    cardtext = block("About them:", 19, 95)                # about 1,900
    recap = block("Earlier today:", 14, 95)                # about 1,400
    diary = block("Recent days:", 5, 300)                  # five long days
    hits = [hit(i) for i in range(4)]                      # about 1,200 once rendered
    kept_recap, kept_diary, found, dropped = card.fit_memory(cardtext, recap, diary, hits, date(2026, 11, 10))
    total = "\n".join(p for p in (cardtext, kept_recap, kept_diary, found) if p)
    assert len(total) <= card.JOINT_CAP
    assert kept_recap == recap and kept_diary == ""                        # today whole, recent days gone
    assert "old 0" in found and "old 3" not in found                       # best-ranked old chats stay
    assert dropped["recent days"] == 5 and dropped["old chats"] >= 1 and "earlier today" not in dropped
    for line in found.splitlines()[1:]:
        assert line.endswith("y") or line.endswith("…")                    # whole lines only


def test_a_hit_hidden_as_already_in_recent_days_comes_back_when_recent_days_are_dropped():
    cardtext, recap = block("About them:", 19, 95), block("Earlier today:", 14, 95)
    line = "nervous about the Zoho interview " + "z" * 700
    diary = "Recent days:\n- 9 Nov: " + line
    same = {"id": "d9", "kind": "diary", "day": "2026-11-09", "text": line, "rrf": 1.0}
    _, kept_diary, found, dropped = card.fit_memory(cardtext, recap, diary, [same], date(2026, 11, 10))
    assert kept_diary == "" and "nervous about the Zoho interview" in found and dropped == {"recent days": 1}
    roomy = card.fit_memory("card", "", diary, [same], date(2026, 11, 10))
    assert roomy[1] == diary and roomy[2] == ""                            # room for both: printed once


def test_a_drop_is_logged_with_what_and_how_much(env, caplog, monkeypatch):
    cid = env.companion["id"]
    for i in range(24):
        run(store.add_fact("t1", cid, "karthik", "life", f"fact {i} " + "f" * 70, None))
    run(store.set_recap("t1", cid, "karthik", "\n".join("- " + "r" * 90 for _ in range(15)), TODAY, at(30)))
    for d in range(4, 10):
        run(store.upsert_diary("t1", cid, "karthik", f"2026-11-{d:02d}", "d" * 150))
    caplog.set_level(logging.INFO)
    ctx = context(cid, "hi", None)
    assert len(ctx) <= card.JOINT_CAP and "Earlier today:" in ctx
    assert f"memory over {card.JOINT_CAP} characters, left out" in caplog.text and "recent days" in caplog.text


# ---- the engine starts ONE call and both searches read it -------------------------------------------

@pytest.fixture
def shared(monkeypatch):
    """The engine test fixture with the real shared rewrite switched back on and counted."""
    from tests import test_companion_engine as eng
    fx = eng.env.__wrapped__(monkeypatch)
    monkeypatch.setattr(engine, "_shared_rewrite", REAL_SHARED_REWRITE)
    fx.calls, fx.answer, fx.delay, fx.kb_got, fx.memory_got = [], SURGERY, 0.0, [], []

    async def rewrite(tenant_id, message, history=None):
        fx.calls.append(message)
        await asyncio.sleep(fx.delay)
        return fx.answer

    async def kb(tenant_id, collection_id, message, history=None, *, companion_id=None, rewrite=None):
        fx.kb_got.append(await rewrite if rewrite is not None else None)
        return KbResult(needs_docs=False)

    real_search = memory_search.search

    async def search(*a, **k):
        fx.memory_got.append(k.get("rewrite"))
        return await real_search(*a, **k)
    monkeypatch.setattr(rw, "rewrite", rewrite)
    monkeypatch.setattr(engine.kb_search, "search", kb)
    monkeypatch.setattr(memory_search, "search", search)
    fx.reply = eng.reply
    return fx


def level2(fx, row):
    stored = next(c for c in fx.db.rows("companions") if c["id"] == row["id"])
    stored["memory_level"], stored["memory_engine"] = 2, "card"
    return row["id"]


def test_a_character_with_files_and_memory_makes_one_rewrite_call_for_both_searches(shared):
    shared.reply(level2(shared, shared.jothidar), TANGLISH)
    assert shared.calls == [TANGLISH]
    assert shared.kb_got == [SURGERY] and shared.memory_got == [SURGERY]


def test_a_memory_only_character_makes_the_call_too(shared):
    shared.reply(level2(shared, shared.vastu), TANGLISH)
    assert shared.calls == [TANGLISH] and shared.kb_got == [] and shared.memory_got == [SURGERY]


def test_a_level1_character_with_no_files_makes_no_rewrite_call(shared):
    shared.reply(shared.vastu["id"], TANGLISH)
    assert shared.calls == [] and shared.memory_got == []


def test_small_talk_to_a_memory_character_searches_nothing(shared):
    shared.answer = SMALL_TALK
    shared.reply(level2(shared, shared.vastu), "hi guru")
    assert shared.calls == ["hi guru"] and shared.memory_got == []


def test_a_slow_rewrite_costs_a_memory_only_reply_the_wait_and_no_more(shared, monkeypatch):
    monkeypatch.setattr(rw, "ROUTE_SECONDS", 0.05)
    shared.delay = 5.0
    started = time.monotonic()
    r = shared.reply(level2(shared, shared.vastu), TANGLISH)
    assert r.status == "done" and time.monotonic() - started < 2.0
    assert shared.memory_got == [None]            # searched with the message as typed


def test_the_playground_rewrite_switch_turns_the_shared_call_off(shared):
    with playground.use(playground.Overrides(rewrite=False)):
        shared.reply(level2(shared, shared.vastu), TANGLISH)
    assert shared.calls == [] and shared.memory_got == [None]


def test_no_rewrite_call_when_the_model_searches_memory_by_itself(shared):
    with playground.use(playground.Overrides(mode="agentic")):       # Playground agentic: nobody reads a rewrite
        shared.reply(level2(shared, shared.vastu), TANGLISH)
    assert shared.calls == []


# ---- found by the code review of 2026-11-11 ---------------------------------------------------------

def test_one_failed_search_keeps_the_hits_of_the_other_versions(env, monkeypatch, caplog):
    cid = surgery_fact(env)
    real = store.match_chunks

    async def match(tenant_id, companions, end_user_id, vector, words, count):
        if words == TANGLISH:
            raise RuntimeError("timeout")
        return await real(tenant_id, companions, end_user_id, vector, words, count)
    monkeypatch.setattr(store, "match_chunks", match)
    with caplog.at_level(logging.WARNING):
        hits = run(memory_search.search("t1", cid, "karthik", TANGLISH, rewrite=SURGERY))
    assert [h["text"] for h in hits] == ["Mother's surgery is on Friday"]
    assert "1 of 3 memory searches failed" in caplog.text


def test_until_an_owner_delete_is_cleaned_up_the_reply_gets_the_card_only(env, monkeypatch):
    cid = priya_has_history(env)
    given = []
    real_fit = card.fit_memory

    def fit(card_text, recap, diary, hits, today=None, cap=card.JOINT_CAP):
        given.append(len(hits))
        return real_fit(card_text, recap, diary, hits, today, cap)

    async def one_hit(*a, **k):
        return [{"id": "x", "kind": "diary", "day": "2026-11-01", "text": "worried about amma's sugar", "score": 0.9}]
    monkeypatch.setattr(card, "fit_memory", fit)
    monkeypatch.setattr(memory_search, "search", one_hit)
    full = context(cid, TANGLISH, None)
    assert "Earlier today" in full and "Recent days" in full and given == [1]

    run(memory_forget.hold("t1", cid, "karthik", "Mother has diabetes"))      # the owner just deleted a fact
    held = context(cid, TANGLISH, SURGERY)
    assert "works at TCS" in held                                              # the card stays
    assert "Earlier today" not in held and "Recent days" not in held and given == [1, 0]
    assert run(store.get_recap("t1", cid, "karthik"))["text"] == "- Interview at Infosys 3 pm"   # hidden, not lost

    async def cleaned(tenant_id, end_user_id, items, today=None):
        return {}
    monkeypatch.setattr(memory_forget, "forget_things", cleaned)
    run(memory_forget.forget_or_queue("t1", cid, "karthik", ["Mother has diabetes"]))
    again = context(cid, TANGLISH, None)
    assert "Earlier today" in again and "Recent days" in again and given == [1, 0, 1]


def test_the_hold_is_per_person_whichever_character_the_delete_was_made_on(env):
    cid = priya_has_history(env)
    run(memory_forget.hold("t1", cid, "someone-else", "x"))                    # another person: no hold on Karthik
    assert "Recent days" in context(cid, TANGLISH, None)
    run(memory_forget.hold("t1", "another-character", "karthik", "x"))         # same person, another character
    assert "Recent days" not in context(cid, TANGLISH, None)


# ---- the person's own today -------------------------------------------------------------------------

def test_person_today_is_the_persons_day_not_the_servers(env, monkeypatch):
    late = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)      # 01:30 on 11 Nov in India, 15:00 on 10 Nov in Toronto
    monkeypatch.setattr(card, "local_today", lambda now, zone: (now or late).astimezone(zone).date())
    env.db.add("companion_end_users", id="kumar", tenant_id="t1", external_user_id="kumar", timezone="America/Toronto")
    env.db.add("companion_end_users", id="priya", tenant_id="t1", external_user_id="priya", timezone=None)
    assert run(card.person_today("t1", "kumar")) == date(2026, 11, 10)
    assert run(card.person_today("t1", "priya")) == date(2026, 11, 11)


def test_the_owner_diary_tab_and_the_cleanup_ask_for_the_persons_today(env, monkeypatch):
    asked = []

    async def person_today(tenant_id, end_user_id, companion=None):
        asked.append(end_user_id)
        return date(2026, 11, 10)
    monkeypatch.setattr(card, "person_today", person_today)
    person = env.db.add("companion_end_users", tenant_id="t1", external_user_id="priya-app", timezone="America/Toronto")
    run(memory.list_diary("t1", env.companion["id"], "priya-app"))
    assert asked == [person["id"]]
