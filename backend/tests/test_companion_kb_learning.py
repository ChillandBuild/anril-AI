"""T27 learning rules: pure functions, made-up vectors, no database."""
import math
from datetime import datetime, timedelta, timezone

from app.companion.kb import learning as L

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
A = [1.0, 0.0, 0.0]


def vec(sim: float) -> list[float]:
    """A vector whose cosine with A is sim."""
    return [sim, math.sqrt(1 - sim * sim), 0.0]


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def passage(doc="d1", pf=10, pt=11, score=3):
    return {"document_id": doc, "page_from": pf, "page_to": pt, "score": score}


def q(id, embedding=A, *, cid="c1", model="m1", basis="book", best=None, days_ago=1, topic=None):
    return {
        "id": id, "companion_id": cid, "topic": topic or f"topic {id}", "embedding": embedding,
        "embedding_model": model, "basis": basis,
        "best": [passage()] if best is None else best, "created_at": iso(days_ago),
    }


def shortcut(id="s1", embedding=A, *, cid="c1", model="m1", status="active", uses=0, misses=0):
    return {"id": id, "companion_id": cid, "topic": "t", "embedding": embedding, "embedding_model": model,
            "document_id": "d1", "pages": [{"page_from": 10, "page_to": 11}],
            "uses": uses, "misses_in_row": misses, "status": status}


def gap(id="g1", embedding=A, *, cid="c1", model="m1", status="open", ask_count=5, last=2):
    return {"id": id, "companion_id": cid, "topic": "t", "embedding": embedding, "embedding_model": model,
            "ask_count": ask_count, "last_asked_at": iso(last), "status": status}


# ---- cosine ----

def test_cosine_basics():
    assert L.cosine([1, 0], [1, 0]) == 1.0
    assert L.cosine([1, 0], [0, 1]) == 0.0
    assert abs(L.cosine([1, 1], [1, 0]) - math.sqrt(0.5)) < 1e-9


def test_cosine_degenerate_is_zero():
    assert L.cosine([], [1, 0]) == 0.0
    assert L.cosine([1, 0], [1, 0, 0]) == 0.0
    assert L.cosine([0, 0], [1, 0]) == 0.0
    assert L.cosine(None, [1, 0]) == 0.0


# ---- group_questions ----

def test_group_similar_and_far():
    groups = L.group_questions([q("a", A), q("b", vec(0.95)), q("c", [0, 1, 0])])
    assert [[r["id"] for r in g] for g in groups] == [["a", "b"], ["c"]]


def test_group_threshold_just_below_and_at():
    assert len(L.group_questions([q("a", A, days_ago=2), q("b", vec(0.87), days_ago=1)])) == 2
    assert len(L.group_questions([q("a", A, days_ago=2), q("b", vec(0.89), days_ago=1)])) == 1
    b = vec(0.9)
    at = L.cosine(A, b)
    assert len(L.group_questions([q("a", A, days_ago=2), q("b", b, days_ago=1)], threshold=at)) == 1
    assert len(L.group_questions([q("a", A, days_ago=2), q("b", b, days_ago=1)], threshold=at + 1e-6)) == 2


def test_group_never_crosses_companion_or_model():
    rows = [q("a", cid="c1"), q("b", cid="c2"), q("c", model="m2")]
    groups = L.group_questions(rows)
    assert len(groups) == 3


def test_group_leaves_out_rows_without_embedding():
    groups = L.group_questions([q("a", A), q("b", None), q("c", [])])
    assert [[r["id"] for r in g] for g in groups] == [["a"]]


def test_group_oldest_first_and_compares_to_first_row_only():
    # b is close to a, c is close to b but not to a: c must not chain in.
    a, b, c = A, vec(0.9), [0.62, 0.78, 0.0]
    assert L.cosine(a, c) < L.GROUP_SIMILARITY <= L.cosine(b, a)
    rows = [q("c", c, days_ago=1), q("b", b, days_ago=2), q("a", a, days_ago=3)]
    groups = L.group_questions(rows)
    assert groups[0][0]["id"] == "a"
    assert [r["id"] for r in groups[0]] == ["a", "b"]
    assert [r["id"] for r in groups[1]] == ["c"]


# ---- shortcut_for_group ----

def test_shortcut_needs_three_questions():
    assert L.shortcut_for_group([q("a"), q("b")]) is None
    out = L.shortcut_for_group([q("a", days_ago=3), q("b", days_ago=2), q("c", days_ago=1)])
    assert out == {
        "companion_id": "c1", "topic": "topic a", "embedding": A, "embedding_model": "m1",
        "document_id": "d1", "pages": [{"page_from": 10, "page_to": 11}],
    }


def test_shortcut_ignores_own_basis_and_low_scores():
    rows = [q("a"), q("b"), q("c", basis="own")]
    assert L.shortcut_for_group(rows) is None
    rows = [q("a"), q("b"), q("c", best=[passage(score=2)])]
    assert L.shortcut_for_group(rows) is None
    rows = [q("a"), q("b"), q("c", basis="primary")]
    assert L.shortcut_for_group(rows) is not None


def test_shortcut_different_page_range_is_not_the_same_passage():
    rows = [q("a"), q("b"), q("c", best=[passage(pf=10, pt=12)])]
    assert L.shortcut_for_group(rows) is None
    rows = [q("a"), q("b"), q("c", best=[passage(doc="d2")])]
    assert L.shortcut_for_group(rows) is None


def test_shortcut_same_passage_twice_in_one_row_counts_once():
    rows = [q("a", best=[passage(), passage()]), q("b"), ]
    assert L.shortcut_for_group(rows) is None


def test_shortcut_extra_ranges_same_document_only_and_capped():
    p2, p3, p4 = passage(pf=20, pt=21), passage(pf=30, pt=31), passage(pf=40, pt=41)
    other_doc = passage(doc="d2", pf=50, pt=51)
    rows = [q(str(i), best=[passage(), p2, p3, p4, other_doc]) for i in range(3)]
    out = L.shortcut_for_group(rows)
    assert out["document_id"] == "d1"
    assert len(out["pages"]) == L.MAX_SHORTCUT_RANGES == 3
    assert out["pages"][0] == {"page_from": 10, "page_to": 11}
    assert {"page_from": 50, "page_to": 51} not in out["pages"]
    assert len({(p["page_from"], p["page_to"]) for p in out["pages"]}) == 3


def test_shortcut_extra_range_needs_three_questions_too():
    rows = [q("a", best=[passage(), passage(pf=20, pt=21)]), q("b"), q("c")]
    assert L.shortcut_for_group(rows)["pages"] == [{"page_from": 10, "page_to": 11}]


def test_shortcut_malformed_best_is_ignored():
    junk = [None, "x", 5, {}, {"document_id": "d1"}, {"document_id": "d1", "page_from": "a", "page_to": 1, "score": 3},
            {"document_id": "d1", "page_from": 10, "page_to": 11}, {"document_id": "d1", "page_from": 10, "page_to": 11, "score": "high"}]
    rows = [q("a", best=junk), q("b", best="oops"), q("c", best=None), q("d", best={"x": 1})]
    rows[2]["best"] = None
    rows.append({"id": "e", "companion_id": "c1", "embedding": A, "embedding_model": "m1", "basis": "book",
                 "created_at": iso(1), "topic": "t"})
    assert L.shortcut_for_group(rows) is None
    good = [q("g1"), q("g2"), q("g3")]
    assert L.shortcut_for_group(rows + good) is not None


# ---- is_known_topic ----

def test_known_topic_any_status_and_model():
    for status in ("active", "retired", "removed_by_owner"):
        assert L.is_known_topic(A, "m1", [shortcut(status=status)])
    for status in ("open", "dismissed", "covered"):
        assert L.is_known_topic(A, "m1", [gap(status=status)])


def test_known_topic_threshold_and_model():
    assert not L.is_known_topic(vec(0.87), "m1", [shortcut(embedding=A)])
    assert L.is_known_topic(vec(0.89), "m1", [shortcut(embedding=A)])
    assert not L.is_known_topic(A, "m2", [shortcut()])
    assert not L.is_known_topic(A, "m1", [shortcut(embedding=None)])
    assert not L.is_known_topic(A, "m1", [])


# ---- gap_for_group ----

def own(id, days_ago, **kw):
    return q(id, basis="own", best=[], days_ago=days_ago, **kw)


def test_gap_four_vs_five_asks():
    assert L.gap_for_group([own(str(i), i + 1) for i in range(4)], NOW) is None
    rows = [own(str(i), i + 1) for i in range(5)]
    out = L.gap_for_group(rows, NOW)
    assert out == {"companion_id": "c1", "topic": "topic 4", "embedding": A, "embedding_model": "m1",
                   "ask_count": 5, "last_asked_at": iso(1)}


def test_gap_window_day_30_vs_31():
    rows = [own(str(i), 30) for i in range(5)]
    assert L.gap_for_group(rows, NOW)["ask_count"] == 5
    rows = [own(str(i), 31) for i in range(4)] + [own("x", 30)]
    assert L.gap_for_group(rows, NOW) is None
    rows = [own(str(i), 31) for i in range(5)]
    assert L.gap_for_group(rows, NOW) is None


def test_gap_counts_only_own_basis():
    rows = [own(str(i), 1) for i in range(4)] + [q("b", basis="book")]
    assert L.gap_for_group(rows, NOW) is None


def test_gap_handles_z_suffix_and_naive_times():
    rows = [own(str(i), 1) for i in range(5)]
    rows[0]["created_at"] = "2026-11-10T12:00:00Z"
    rows[1]["created_at"] = "2026-11-10T12:00:00"
    assert L.gap_for_group(rows, NOW)["ask_count"] == 5


# ---- nearest_shortcut ----

def test_nearest_shortcut_active_only_and_most_similar():
    rows = [shortcut("far", vec(0.9)), shortcut("near", vec(0.99)), shortcut("old", A, status="retired")]
    assert L.nearest_shortcut(A, "m1", rows)["id"] == "near"
    assert L.nearest_shortcut(A, "m1", [shortcut(status="retired"), shortcut(status="removed_by_owner")]) is None


def test_nearest_shortcut_threshold_model_and_missing_embedding():
    assert L.nearest_shortcut(vec(0.87), "m1", [shortcut()]) is None
    assert L.nearest_shortcut(vec(0.89), "m1", [shortcut()]) is not None
    assert L.nearest_shortcut(A, "m2", [shortcut()]) is None
    assert L.nearest_shortcut(None, "m1", [shortcut()]) is None


# ---- after_use ----

def test_after_use_hit_resets_misses():
    assert L.after_use(shortcut(uses=4, misses=2), True) == {"uses": 5, "misses_in_row": 0}


def test_after_use_retires_on_third_miss():
    assert L.after_use(shortcut(misses=0), False) == {"misses_in_row": 1}
    assert L.after_use(shortcut(misses=1), False) == {"misses_in_row": 2}
    assert L.after_use(shortcut(misses=2), False) == {"misses_in_row": 3, "status": "retired"}


def test_after_use_missing_counts_default_to_zero():
    assert L.after_use({}, True) == {"uses": 1, "misses_in_row": 0}
    assert L.after_use({"uses": None, "misses_in_row": None}, False) == {"misses_in_row": 1}


# ---- log_cutoff ----

def test_log_cutoff_is_90_days_back():
    assert L.log_cutoff(NOW) == (NOW - timedelta(days=90)).isoformat()


# ---- plan_nightly ----

def three(prefix="a", **kw):
    return [q(f"{prefix}{i}", days_ago=3 - i, **kw) for i in range(3)]


def five_own(prefix="o", **kw):
    return [own(f"{prefix}{i}", i + 1, **kw) for i in range(5)]


def test_plan_creates_shortcut_and_gap():
    plan = L.plan_nightly(three() + five_own(embedding=[0, 1, 0]), [], [], NOW)
    assert len(plan["new_shortcuts"]) == 1 and plan["new_shortcuts"][0]["document_id"] == "d1"
    assert len(plan["new_gaps"]) == 1 and plan["new_gaps"][0]["ask_count"] == 5
    assert plan["gap_updates"] == [] and plan["covered_gap_ids"] == []


def test_plan_below_thresholds_creates_nothing():
    plan = L.plan_nightly([q("a"), q("b")] + [own(str(i), 1, embedding=[0, 1, 0]) for i in range(4)], [], [], NOW)
    assert plan == {"new_shortcuts": [], "new_gaps": [], "gap_updates": [], "covered_gap_ids": []}


def test_plan_owner_removed_shortcut_is_never_relearned():
    for status in ("removed_by_owner", "retired", "active"):
        plan = L.plan_nightly(three(), [shortcut(status=status)], [], NOW)
        assert plan["new_shortcuts"] == []


def test_plan_existing_shortcut_of_other_companion_does_not_block():
    plan = L.plan_nightly(three(), [shortcut(cid="c2")], [], NOW)
    assert len(plan["new_shortcuts"]) == 1


def test_plan_one_shortcut_and_gap_per_group():
    rows = three() + three("b") + five_own() + five_own("p")
    plan = L.plan_nightly(rows, [], [], NOW)
    assert len(plan["new_shortcuts"]) == 1
    assert len(plan["new_gaps"]) == 1


def test_plan_companions_are_planned_separately():
    plan = L.plan_nightly(three(cid="c1") + three(cid="c2"), [], [], NOW)
    assert sorted(s["companion_id"] for s in plan["new_shortcuts"]) == ["c1", "c2"]


def test_plan_open_gap_is_updated_not_duplicated():
    plan = L.plan_nightly(five_own() + [own("x", 0.5)], [], [gap(ask_count=5, last=2)], NOW)
    assert plan["new_gaps"] == []
    assert plan["gap_updates"] == [{"id": "g1", "ask_count": 6, "last_asked_at": iso(0.5)}]


def test_plan_open_gap_unchanged_is_not_rewritten():
    rows = five_own()
    g = gap(ask_count=5, last=1)
    plan = L.plan_nightly(rows, [], [g], NOW)
    assert plan["gap_updates"] == []


def test_plan_dismissed_or_covered_gap_is_not_reopened():
    for status in ("dismissed", "covered"):
        plan = L.plan_nightly(five_own(), [], [gap(status=status)], NOW)
        assert plan["new_gaps"] == [] and plan["gap_updates"] == []


def test_plan_gap_of_other_companion_does_not_block():
    plan = L.plan_nightly(five_own(), [], [gap(cid="c2")], NOW)
    assert len(plan["new_gaps"]) == 1


def test_plan_open_gap_covered_by_later_book_answer():
    later = q("late", basis="book", days_ago=0.5)
    plan = L.plan_nightly([later], [], [gap(last=2)], NOW)
    assert plan["covered_gap_ids"] == ["g1"]
    primary = q("late2", basis="primary", days_ago=0.5)
    assert L.plan_nightly([primary], [], [gap(last=2)], NOW)["covered_gap_ids"] == ["g1"]


def test_plan_gap_not_covered_by_earlier_own_or_dissimilar_questions():
    gaps = [gap(last=2)]
    assert L.plan_nightly([q("early", days_ago=5)], [], gaps, NOW)["covered_gap_ids"] == []
    assert L.plan_nightly([own("o", 0.5)], [], gaps, NOW)["covered_gap_ids"] == []
    assert L.plan_nightly([q("far", [0, 1, 0], days_ago=0.5)], [], gaps, NOW)["covered_gap_ids"] == []
    assert L.plan_nightly([q("m", model="m2", days_ago=0.5)], [], gaps, NOW)["covered_gap_ids"] == []
    assert L.plan_nightly([q("c", cid="c2", days_ago=0.5)], [], gaps, NOW)["covered_gap_ids"] == []
    assert L.plan_nightly([q("late", days_ago=0.5)], [], [gap(status="dismissed")], NOW)["covered_gap_ids"] == []


def test_plan_covered_gap_gets_no_update():
    rows = five_own() + [q("late", basis="book", days_ago=0.1)]
    plan = L.plan_nightly(rows, [], [gap(last=1.5)], NOW)
    assert plan["covered_gap_ids"] == ["g1"]
    assert plan["gap_updates"] == []


def test_plan_does_not_mutate_inputs():
    rows = three()
    before = [dict(r) for r in rows]
    L.plan_nightly(rows, [], [], NOW)
    assert rows == before


# ---- the database-facing half: schedule_log, log_question, run_nightly (fake database) ----

import asyncio  # noqa: E402

import pytest  # noqa: E402

from app.companion import memory_embed  # noqa: E402
from app.companion.kb import store_search  # noqa: E402
from app.companion.kb.types import KbResult, Passage  # noqa: E402
from app.services.embeddings import to_pgvector  # noqa: E402
from tests.fake_supabase import FakeSupabase  # noqa: E402

T1, T2 = "tenant-1", "tenant-2"
P88 = Passage(id="b88", document_id="book3", document_title="Book 3", tier=2, heading_path="",
              text="Sade Sati lasts seven and a half years", page_from=88, page_to=89, score=3)
SRC88 = [{"document": "Book 3", "page_from": 88, "page_to": 89, "chunk_id": "b88", "document_id": "book3"}]
TOPIC = "How long does Sade Sati last?"


@pytest.fixture
def ldb(monkeypatch):
    db = FakeSupabase()
    db.embed_calls = []

    async def fake_embed(texts, kind, tenant_id, model=None, retries=True):
        db.embed_calls.append(list(texts))
        return [A for _ in texts]

    monkeypatch.setattr(store_search, "get_supabase", lambda: db)
    monkeypatch.setattr(memory_embed, "embed", fake_embed)
    db.add("companion_kb_collections", id="c1", tenant_id=T1, name="Astrology books")
    db.add("companion_kb_documents", id="book3", tenant_id=T1, collection_id="c1", title="Book 3", tier=2)
    db.add("companions", id="guru", tenant_id=T1, name="Guru", knowledge_collection_id="c1")
    db.add("companions", id="bot2", tenant_id=T2, name="Bot", knowledge_collection_id=None)
    return db


def kb_result(**over):
    return KbResult(**{"passages": (P88,), "topic": TOPIC, "topic_embedding": tuple(A), **over})


def log_rows(db):
    return db.rows("companion_kb_question_log")


def seed_question(db, *, tenant=T1, companion="guru", basis="book", best=None, days_ago=1.0, embedding=A,
                  topic=TOPIC):
    best = [{"document_id": "book3", "page_from": 88, "page_to": 89, "score": 3}] if best is None else best
    db.add("companion_kb_question_log", tenant_id=tenant, companion_id=companion, topic=topic,
           embedding=to_pgvector(embedding), embedding_model="gemini", basis=basis,
           best=best if basis != "own" else [], created_at=iso(days_ago))


def seed_shortcut(db, **over):
    return db.add("companion_kb_shortcuts", **{
        "tenant_id": T1, "companion_id": "guru", "topic": TOPIC, "embedding": to_pgvector(A),
        "embedding_model": "gemini", "document_id": "book3", "pages": [{"page_from": 88, "page_to": 89}],
        "uses": 0, "misses_in_row": 0, "status": "active", **over})["id"]


def test_log_question_writes_the_topic_and_the_used_passages_only(ldb):
    asyncio.run(L.log_question(T1, "guru", kb_result(), "book", SRC88))
    (row,) = log_rows(ldb)
    assert row["topic"] == TOPIC and row["basis"] == "book" and row["embedding_model"] == memory_embed.MODEL
    assert row["best"] == [{"document_id": "book3", "page_from": 88, "page_to": 89, "score": 3}]
    assert "end_user_id" not in row and "message" not in row and "text" not in str(row["best"])
    assert ldb.embed_calls == []                       # the search already paid for the vector


def test_log_question_own_reasoning_has_no_best_and_unused_passages_are_left_out(ldb):
    asyncio.run(L.log_question(T1, "guru", kb_result(), "own", []))
    asyncio.run(L.log_question(T1, "guru", kb_result(), "book", [{"chunk_id": "not-supplied"}]))
    assert [r["best"] for r in log_rows(ldb)] == [[], []]


def test_log_question_skips_chat_failed_search_and_missing_topic(ldb):
    asyncio.run(L.log_question(T1, "guru", kb_result(), "chat", []))
    asyncio.run(L.log_question(T1, "guru", kb_result(failed=True), "own", []))
    asyncio.run(L.log_question(T1, "guru", kb_result(topic=None), "own", []))
    asyncio.run(L.log_question(T2, "guru", kb_result(), "own", []))       # another tenant's character
    assert log_rows(ldb) == []


def test_log_question_embeds_the_topic_again_after_a_resumed_turn(ldb):
    resumed = KbResult.from_json(kb_result().to_json())                  # the vector is not saved with a paused turn
    asyncio.run(L.log_question(T1, "guru", resumed, "book", SRC88))
    assert ldb.embed_calls == [[TOPIC]] and store_search._vector(log_rows(ldb)[0]["embedding"]) == A


def test_log_question_records_the_shortcut_hit_and_retires_on_the_third_miss(ldb):
    sid = seed_shortcut(ldb, misses_in_row=1)
    asyncio.run(L.log_question(T1, "guru", kb_result(shortcut_id=sid, shortcut_hit=True), "book", SRC88))
    row = ldb.rows("companion_kb_shortcuts")[0]
    assert (row["uses"], row["misses_in_row"], row["status"]) == (1, 0, "active")
    for _ in range(3):
        asyncio.run(L.log_question(T1, "guru", kb_result(passages=(), shortcut_id=sid), "own", []))
    assert (row["uses"], row["misses_in_row"], row["status"]) == (1, 3, "retired")
    asyncio.run(L.log_question(T1, "guru", kb_result(shortcut_id=sid, shortcut_hit=True), "book", SRC88))
    assert row["status"] == "retired" and row["uses"] == 1               # a retired shortcut is left alone
    asyncio.run(L.log_question(T2, "bot2", kb_result(shortcut_id=sid, shortcut_hit=True), "book", SRC88))
    assert row["uses"] == 1                                              # another tenant cannot touch it


def test_log_question_never_raises(ldb, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr(store_search, "add_question", boom)
    monkeypatch.setattr(store_search, "get_shortcut", boom)
    asyncio.run(L.log_question(T1, "guru", kb_result(shortcut_id="s1"), "book", SRC88))


def test_schedule_log_runs_in_the_background_and_skips_small_talk(ldb):
    async def reply():
        L.schedule_log(T1, "guru", kb_result(needs_docs=False, topic=None), "chat", [])
        L.schedule_log(T1, "guru", kb_result(topic="  "), "own", [])
        L.schedule_log(T1, "guru", kb_result(failed=True), "own", [])
        assert not L._tasks
        L.schedule_log(T1, "guru", kb_result(), "book", SRC88)
        assert len(L._tasks) == 1
        await asyncio.gather(*L._tasks)
    asyncio.run(reply())
    assert len(log_rows(ldb)) == 1 and not L._tasks


def test_schedule_log_never_raises_without_a_running_loop(ldb):
    L.schedule_log(T1, "guru", kb_result(), "book", SRC88)               # no event loop here
    assert log_rows(ldb) == []


def test_nightly_creates_a_shortcut_from_three_similar_book_questions(ldb):
    for days in (3, 2, 1):
        seed_question(ldb, days_ago=days)
    out = asyncio.run(L.run_nightly(NOW))
    (row,) = ldb.rows("companion_kb_shortcuts")
    assert row["document_id"] == "book3" and row["pages"] == [{"page_from": 88, "page_to": 89}]
    assert row["status"] == "active" and row["tenant_id"] == T1 and row["companion_id"] == "guru"
    assert out["new_shortcuts"] == 1 and out["tenants"] == 1
    assert asyncio.run(L.run_nightly(NOW))["new_shortcuts"] == 0         # the next night does not make it again


def test_nightly_never_relearns_a_shortcut_the_owner_removed(ldb):
    seed_shortcut(ldb, status="removed_by_owner")
    for days in (3, 2, 1):
        seed_question(ldb, days_ago=days)
    assert asyncio.run(L.run_nightly(NOW))["new_shortcuts"] == 0
    assert len(ldb.rows("companion_kb_shortcuts")) == 1


def test_nightly_ignores_log_entries_of_a_deleted_book(ldb):
    for days in (3, 2, 1):
        seed_question(ldb, days_ago=days)
    ldb.table("companion_kb_documents").delete().eq("id", "book3").execute()
    assert asyncio.run(L.run_nightly(NOW))["new_shortcuts"] == 0
    assert ldb.rows("companion_kb_shortcuts") == []


def test_nightly_opens_a_gap_updates_it_and_marks_it_covered(ldb):
    for days in (5, 4, 3, 2, 1):
        seed_question(ldb, basis="own", days_ago=days)
    assert asyncio.run(L.run_nightly(NOW))["new_gaps"] == 1
    (g,) = ldb.rows("companion_kb_gaps")
    assert g["status"] == "open" and g["ask_count"] == 5 and g["topic"] == TOPIC
    seed_question(ldb, basis="own", days_ago=0.5)
    assert asyncio.run(L.run_nightly(NOW))["gap_updates"] == 1 and g["ask_count"] == 6
    seed_question(ldb, basis="book", days_ago=0.1)                       # the owner added a book that answers it
    assert asyncio.run(L.run_nightly(NOW))["covered"] == 1 and g["status"] == "covered"


def test_nightly_deletes_log_rows_older_than_90_days_for_every_tenant(ldb):
    seed_question(ldb, days_ago=91)
    seed_question(ldb, tenant=T2, companion="bot2", basis="own", days_ago=120)
    seed_question(ldb, days_ago=89)
    out = asyncio.run(L.run_nightly(NOW))
    assert out["deleted_log_rows"] == 2 and len(log_rows(ldb)) == 1


def test_nightly_one_failing_tenant_does_not_stop_the_others(ldb, monkeypatch):
    for days in (5, 4, 3, 2, 1):
        seed_question(ldb, tenant=T2, companion="bot2", basis="own", days_ago=days)
    for days in (3, 2, 1):
        seed_question(ldb, days_ago=days)
    real = store_search.list_questions

    async def flaky(tenant_id, since_iso):
        if tenant_id == T1:
            raise RuntimeError("timeout")
        return await real(tenant_id, since_iso)

    monkeypatch.setattr(store_search, "list_questions", flaky)
    out = asyncio.run(L.run_nightly(NOW))
    assert out["failed_tenants"] == 1 and out["tenants"] == 1 and out["new_gaps"] == 1
    assert [g["tenant_id"] for g in ldb.rows("companion_kb_gaps")] == [T2]
    assert ldb.rows("companion_kb_shortcuts") == []
