"""full_main_resource: the main resource goes in whole with every real question, plus the other books'
best pieces (migration 292). AstroTamil's 29-page Rule Book holds the steps for every topic; 3 judged
pieces of it left those steps out and replies said "own reasoning, 0 pages"."""
from app.companion.kb import search
from app.companion.kb.types import KbResult
from tests.test_companion_kb_search import A, SMALL_TALK, ask, fx, run  # noqa: F401  (fx is a fixture)


def _add_main_pages(fx):
    fx.db.add("companion_kb_chunks", id="m13", tenant_id=A, document_id="main", collection_id="c1", tier=1, seq=1,
              heading_path="", text="marriage until the Saturn dasa ends. Job: check the 10th lord first.",
              page_from=12, page_to=13)


def test_join_writes_the_overlap_once():
    assert search.join_chunks(["Saturn in the 7th house delays marriage",
                               "in the 7th house delays marriage until the dasa ends"]) == \
        "Saturn in the 7th house delays marriage until the dasa ends"


def test_join_keeps_both_when_they_do_not_overlap():
    assert search.join_chunks(["Page one ends here.", "Page two starts here."]) == "Page one ends here.\nPage two starts here."


def test_whole_main_comes_first_unjudged_with_the_other_books_judged(fx):  # noqa: F811
    _add_main_pages(fx)
    fx.scores = {"b90": 3}
    kb = ask(full_main=True)
    whole, *books = kb.passages
    assert whole.id == "whole:main" and whole.document_title == "Main resource" and whole.tier == 1
    assert (whole.page_from, whole.page_to) == (12, 13)
    assert whole.text.startswith("Saturn (sani) in the seventh house delays marriage")
    assert "Job: check the 10th lord first." in whole.text
    assert [p.id for p in books] == ["b90"]
    assert fx.tiers == [2] and all("m12" not in call for call in fx.judge_calls)   # the main book is not judged


def test_a_question_where_no_other_book_passes_still_has_the_rule_book(fx):  # noqa: F811
    kb = ask(full_main=True)
    assert [p.id for p in kb.passages] == ["whole:main"]


def test_small_talk_still_sends_nothing(fx):  # noqa: F811
    fx.rewrite_result = SMALL_TALK
    assert ask("vanakkam", full_main=True) == KbResult(needs_docs=False)


def test_a_main_resource_over_the_limit_falls_back_to_the_normal_search(fx, monkeypatch):  # noqa: F811
    monkeypatch.setattr(search, "MAX_WHOLE_MAIN_CHARS", 10)
    fx.scores = {"m12": 3}
    kb = ask(full_main=True)
    assert [p.id for p in kb.passages] == ["m12"] and len(fx.judge_calls) == 1


def test_off_by_default(fx):  # noqa: F811
    fx.scores = {"m12": 3}
    assert [p.id for p in ask().passages] == ["m12"]


def test_whole_main_is_this_tenants_and_collections_only(fx):  # noqa: F811
    fx.db.add("companion_kb_documents", id="other", tenant_id="tenant-b", collection_id="c9", title="B's book", tier=1)
    fx.db.add("companion_kb_chunks", id="x1", tenant_id="tenant-b", document_id="other", collection_id="c9", tier=1,
              seq=0, heading_path="", text="tenant B text", page_from=1, page_to=1)
    whole = run(search.whole_main(A, "c1"))
    assert [p.id for p in whole] == ["whole:main"] and "tenant B" not in whole[0].text


def test_the_engine_passes_the_characters_switch(monkeypatch):
    from app.companion import engine
    seen = {}

    async def fake_search(*a, **kw):
        seen.update(kw)
        return KbResult()
    monkeypatch.setattr(engine.kb_search, "search", fake_search)
    run(engine._knowledge("t", {"id": "j", "knowledge_collection_id": "c1", "full_main_resource": True}, "q", []))
    assert seen["full_main"] is True
    seen.clear()
    run(engine._knowledge("t", {"id": "j", "knowledge_collection_id": "c1"}, "q", []))
    assert "full_main" not in seen


def test_a_slow_search_still_sends_the_whole_main_resource(fx, monkeypatch):  # noqa: F811
    """Live eval 2026-11-18: under load the other books' judge step ran past the 20 s limit and the reply
    went out with no Rule Book at all."""
    async def slow(*a, **kw):
        raise TimeoutError
    monkeypatch.setattr(search, "_search", slow)
    kb = ask(full_main=True)
    assert kb.failed and [p.id for p in kb.passages] == ["whole:main"]
    assert ask().passages == ()   # off: a failed search still sends nothing, as before
