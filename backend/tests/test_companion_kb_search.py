"""kb/search.py (T13 + T28): rewrite -> embed -> step A -> shortcut -> step B, with fake LLM calls.

The database is the fake; rewrite, judge and embed are patched, so no test here talks to a model.
"""
import asyncio

import pytest

from app.companion import memory_embed
from app.companion.kb import judge as kb_judge
from app.companion.kb import rewrite as kb_rewrite
from app.companion.kb import search, store_search
from app.companion.kb.rewrite import Rewrite
from app.companion.kb.types import KbResult
from tests.fake_supabase import FakeSupabase

A, B = "tenant-a", "tenant-b"
VEC = [1.0, 0.0, 0.0]
SATURN = Rewrite(True, "Does Saturn in the 7th house delay marriage?", "ஏழாம் வீட்டில் சனி இருந்தால் திருமணம் தாமதமாகுமா?",
                 "Saturn in the seventh house and marriage delay", ["saturn", "sani", "சனி"])
SADE_SATI = Rewrite(True, "How long does Sade Sati last?", "சடே சதி எவ்வளவு காலம்?", "How long does Sade Sati last?",
                    ["sade sati", "sani"])
ASHTAMA = Rewrite(True, "What is ashtama sani?", "அஷ்டம சனி என்றால் என்ன?", "What is ashtama sani?", ["sani", "rahu"])
SMALL_TALK = Rewrite(False, "", "", None, [])


def run(coro):
    return asyncio.run(coro)


class Fakes:
    """What the patched calls saw: every embed call, every judge call (as passage ids), every tier searched."""

    def __init__(self):
        self.rewrite_result, self.rewrite_calls = SATURN, []
        self.embed_calls, self.embed_fails = [], False
        self.scores, self.judge_calls, self.judge_fails_on = {}, [], None
        self.tiers = []


@pytest.fixture
def fx(monkeypatch):
    db, fakes = FakeSupabase(), Fakes()
    monkeypatch.setattr(store_search, "get_supabase", lambda: db)

    async def fake_rewrite(tenant_id, message, history=None):
        fakes.rewrite_calls.append((message, history))
        return fakes.rewrite_result

    async def fake_embed(texts, kind, tenant_id, model=None, retries=True):
        fakes.embed_calls.append((list(texts), kind, retries))
        return [None if fakes.embed_fails else VEC for _ in texts]

    async def fake_judge(tenant_id, question, passages):
        fakes.judge_calls.append([p["id"] for p in passages])
        if fakes.judge_fails_on == len(fakes.judge_calls):
            return None
        return [fakes.scores.get(p["id"], 0) for p in passages]

    monkeypatch.setattr(kb_rewrite, "rewrite", fake_rewrite)
    monkeypatch.setattr(memory_embed, "embed", fake_embed)
    monkeypatch.setattr(kb_judge, "judge", fake_judge)

    real = db.rpc_handlers["match_companion_kb_chunks"]

    def counted(params):
        fakes.tiers.append(params["p_tier"])
        return real(params)

    db.rpc_handlers["match_companion_kb_chunks"] = counted

    db.add("companion_kb_collections", id="c1", tenant_id=A, name="Astrology books")
    db.add("companion_kb_documents", id="main", tenant_id=A, collection_id="c1", title="Main resource", tier=1)
    db.add("companion_kb_documents", id="book3", tenant_id=A, collection_id="c1", title="Book 3", tier=2)
    db.add("companion_kb_chunks", id="m12", tenant_id=A, document_id="main", collection_id="c1", tier=1, seq=0,
           heading_path="Seventh House", text="Saturn (sani) in the seventh house delays marriage",
           page_from=12, page_to=12)
    for seq, (cid, start, end, text) in enumerate([("b87", 87, 88, "Sade Sati begins when sani enters the twelfth"),
                                                   ("b88", 88, 89, "Sade Sati lasts seven and a half years"),
                                                   ("b90", 90, 91, "Rahu in the eighth house; marriage delay notes")]):
        db.add("companion_kb_chunks", id=cid, tenant_id=A, document_id="book3", collection_id="c1", tier=2, seq=seq,
               heading_path="", text=text, page_from=start, page_to=end)
    db.add("companions", id="guru", tenant_id=A, name="Guru", knowledge_collection_id="c1")
    fakes.db = db
    return fakes


def add_shortcut(fx, **over):
    row = {"tenant_id": A, "companion_id": "guru", "topic": "How long does Sade Sati last?", "embedding": VEC,
           "embedding_model": memory_embed.MODEL, "document_id": "book3",
           "pages": [{"page_from": 88, "page_to": 88}], "uses": 0, "misses_in_row": 0, "status": "active", **over}
    return fx.db.add("companion_kb_shortcuts", **row)["id"]


def ask(message="7th house la sani irundha kalyanam late aaguma?", tenant=A, collection="c1", **kw):
    return run(search.search(tenant, collection, message, **kw))


# --- the three steps ------------------------------------------------------------------------------------

def test_small_talk_makes_no_embed_no_sql_and_no_judge_call(fx):
    fx.rewrite_result = SMALL_TALK
    assert ask("good morning guru") == KbResult(needs_docs=False)
    assert fx.embed_calls == [] and fx.tiers == [] and fx.judge_calls == []


def test_step_a_hit_returns_the_main_resource_and_skips_step_b(fx):
    fx.scores = {"m12": 3, "b90": 3}
    kb = ask()
    assert [(p.id, p.document_title, p.tier, p.page_from, p.score) for p in kb.passages] == [
        ("m12", "Main resource", 1, 12, 3)]
    assert kb.needs_docs and not kb.failed and kb.topic == SATURN.topic_query
    assert fx.tiers == [1] and fx.judge_calls == [["m12"]]


def test_step_a_miss_runs_step_b_and_keeps_the_best_scores_first(fx):
    fx.rewrite_result = SADE_SATI
    fx.scores = {"m12": 1, "b87": 2, "b88": 3}
    kb = ask("sadesati evlo naal?")
    assert [(p.id, p.score) for p in kb.passages] == [("b88", 3), ("b87", 2)]
    assert all(p.tier == 2 and p.document_title == "Book 3" for p in kb.passages)
    assert fx.tiers == [1, 2] and len(fx.judge_calls) == 2


def test_nothing_passes_gives_no_passages_but_still_a_documents_question(fx):
    fx.scores = {"m12": 1, "b90": 1}
    kb = ask()
    assert kb.passages == () and kb.needs_docs is True and kb.failed is False
    assert kb.topic == SATURN.topic_query and fx.tiers == [1, 2]


def test_step_limits_keep_3_from_the_main_resource_and_4_from_books(fx):
    for n in range(6):
        fx.db.add("companion_kb_chunks", id=f"m{n}", tenant_id=A, document_id="main", collection_id="c1", tier=1,
                  seq=n + 1, heading_path="", text=f"Saturn note {n}", page_from=20 + n, page_to=20 + n)
        fx.db.add("companion_kb_chunks", id=f"x{n}", tenant_id=A, document_id="book3", collection_id="c1", tier=2,
                  seq=n + 10, heading_path="", text=f"sani note {n}", page_from=100 + n, page_to=100 + n)
    fx.scores = {f"m{n}": 2 for n in range(6)}
    assert len(ask().passages) == search.STEP_A_KEEP
    fx.scores = {f"x{n}": 2 for n in range(6)}
    assert len(ask().passages) == search.STEP_B_KEEP


def test_a_failed_judge_uses_no_passages_and_marks_the_result_failed(fx):
    fx.scores, fx.judge_fails_on = {"m12": 3}, 1
    assert ask() == KbResult(failed=True)
    assert fx.tiers == [1]                                   # an unchecked step A does not fall through to books
    fx.tiers.clear(), fx.judge_calls.clear()
    fx.scores, fx.judge_fails_on = {"b90": 3}, 2             # step A judged fine, step B's judge broke
    assert ask() == KbResult(failed=True) and fx.tiers == [1, 2]


def test_another_tenants_collection_returns_nothing(fx):
    fx.scores = {"m12": 3, "b88": 3, "b87": 3, "b90": 3}
    kb = ask(tenant=B)
    assert kb.passages == () and all(call == [] for call in fx.judge_calls)
    add_shortcut(fx)
    fx.rewrite_result = SADE_SATI
    kb = ask(tenant=B, companion_id="guru")                  # B with A's character id: A's shortcut stays unseen
    assert kb.passages == () and kb.shortcut_id is None


def test_a_search_slower_than_the_time_limit_fails_instead_of_holding_the_reply(fx, monkeypatch):
    async def slow_rewrite(tenant_id, message, history=None):
        await asyncio.sleep(0.5)
        return fx.rewrite_result          # without the limit the search would carry on from here

    monkeypatch.setattr(kb_rewrite, "rewrite", slow_rewrite)
    monkeypatch.setattr(search, "SEARCH_TIMEOUT_SECONDS", 0.05)
    assert run(search.search("tenant-a", "col-a", "sani 7th house?")) == KbResult(failed=True)
    assert fx.embed_calls == [] and fx.judge_calls == []


def test_embed_failure_marks_the_result_failed_and_searches_nothing(fx):
    fx.embed_fails = True
    assert ask() == KbResult(failed=True)
    assert fx.tiers == [] and fx.judge_calls == []


def test_search_never_raises(fx):
    def boom(params):
        raise RuntimeError("database down")
    fx.db.rpc_handlers["match_companion_kb_chunks"] = boom
    assert ask() == KbResult(failed=True)


def test_a_failed_rewrite_still_searches_with_the_message_as_typed(fx):
    fx.rewrite_result = kb_rewrite.fallback_rewrite("saturn seventh house")
    fx.scores = {"m12": 2}
    kb = ask("saturn seventh house")
    assert [p.id for p in kb.passages] == ["m12"] and kb.topic is None and kb.topic_embedding is None
    assert fx.embed_calls == [(["saturn seventh house"], "query", False)]      # same text: embedded once


def test_queries_and_topic_are_embedded_in_one_call_and_history_goes_to_the_rewrite(fx):
    fx.scores = {"m12": 3}
    history = [{"role": "user", "content": "vanakkam"}]
    kb = ask(history=history)
    assert fx.embed_calls == [([SATURN.english_query, SATURN.tamil_query, SATURN.topic_query], "query", False)]
    assert fx.rewrite_calls[0][1] == history
    assert kb.topic_embedding == tuple(VEC) and "topic_embedding" not in kb.to_json()
    assert KbResult.from_json(kb.to_json()) == kb


# --- T28: learned shortcuts ----------------------------------------------------------------------------

def test_a_shortcut_hit_is_judged_with_step_a_and_skips_step_b(fx):
    sid = add_shortcut(fx)
    fx.rewrite_result = SADE_SATI
    fx.scores = {"m12": 0, "b87": 1, "b88": 3}
    kb = ask("sadesati epo mudiyum?", companion_id="guru")
    assert [(p.id, p.page_from, p.score) for p in kb.passages] == [("b88", 88, 3)]
    assert kb.shortcut_id == sid and kb.shortcut_hit is True
    assert fx.tiers == [1] and fx.judge_calls == [["m12", "b87", "b88"]]         # one judge call, no extra


def test_the_trap_a_shortcut_page_below_the_pass_mark_is_dropped_and_step_b_runs(fx):
    sid = add_shortcut(fx)
    fx.rewrite_result = ASHTAMA
    fx.scores = {"m12": 0, "b87": 1, "b88": 1, "b90": 2}
    kb = ask("ashtama sani na enna?", companion_id="guru")
    assert [p.id for p in kb.passages] == ["b90"]                                 # never the Sade Sati page
    assert kb.shortcut_id == sid and kb.shortcut_hit is False
    assert fx.tiers == [1, 2] and fx.judge_calls == [["m12", "b87", "b88"], ["b90"]]


def test_the_main_resource_still_wins_over_a_passing_shortcut(fx):
    add_shortcut(fx)
    fx.rewrite_result = SADE_SATI
    fx.scores = {"m12": 2, "b88": 3}
    kb = ask(companion_id="guru")
    assert [p.id for p in kb.passages] == ["m12"] and kb.shortcut_hit is True and fx.tiers == [1]


def test_shortcuts_are_off_without_a_character_and_for_retired_or_far_topics(fx):
    fx.rewrite_result = SADE_SATI
    fx.scores = {"b88": 3}
    add_shortcut(fx)
    assert ask().shortcut_id is None and fx.tiers == [1, 2]                       # no companion_id
    fx.db.rows("companion_kb_shortcuts")[0]["status"] = "retired"
    assert ask(companion_id="guru").shortcut_id is None
    fx.db.rows("companion_kb_shortcuts")[0].update(status="active", embedding=[0.0, 1.0, 0.0])
    assert ask(companion_id="guru").shortcut_id is None                           # a different topic


def test_a_shortcut_into_a_book_outside_the_collection_is_not_used(fx):
    fx.db.add("companion_kb_collections", id="c2", tenant_id=A, name="Other shelf")
    fx.db.add("companion_kb_documents", id="far", tenant_id=A, collection_id="c2", title="Far book", tier=2)
    fx.db.add("companion_kb_chunks", id="f1", tenant_id=A, document_id="far", collection_id="c2", tier=2, seq=0,
              heading_path="", text="Sade Sati elsewhere", page_from=88, page_to=88)
    add_shortcut(fx, document_id="far")
    fx.rewrite_result = SADE_SATI
    fx.scores = {"f1": 3}
    kb = ask(companion_id="guru")
    assert kb.passages == () and kb.shortcut_id is None and "f1" not in sum(fx.judge_calls, [])


# --- fusion and the eval hook ---------------------------------------------------------------------------

def row(cid, source, score):
    return {"id": cid, "document_id": "d", "document_title": "Book", "tier": 2, "heading_path": "", "text": cid,
            "page_from": 1, "page_to": 1, "source": source, "score": score}


def test_fuse_ranks_a_passage_found_by_two_lists_above_one_found_by_one():
    rows = [row("a", "words", 0.9), row("b", "words", 0.5), row("b", "trigram", 0.8), row("c", "trigram", 0.4)]
    assert [p.id for p in search.fuse(rows, 10)] == ["b", "a", "c"]
    assert [p.id for p in search.fuse(rows, 1)] == ["b"]
    assert search.fuse([], 5) == [] and search.fuse([row("z", "unknown", 1.0)], 5) == []


def test_fuse_counts_the_english_and_tamil_meaning_lists_as_one_vote():
    rows = [row("a", "vector_en", 0.9), row("a", "vector_ta", 0.8),        # one meaning vote, not two
            row("b", "vector_en", 0.7), row("b", "words", 0.3)]
    assert [p.id for p in search.fuse(rows, 10)] == ["b", "a"]


def test_candidates_returns_the_fused_list_before_the_judge(fx):
    found = run(search.candidates(A, "c1", 2, SADE_SATI, 20))
    assert {p.id for p in found} == {"b87", "b88"} and all(p.score == 0 for p in found)
    assert fx.judge_calls == [] and len(fx.embed_calls) == 1
    assert run(search.candidates(B, "c1", 2, SADE_SATI, 20)) == []
