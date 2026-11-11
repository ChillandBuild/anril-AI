"""kb/store_search.py against the fake: the search call, the question log, shortcuts and gaps.

The point of most tests here: tenant B, holding tenant A's ids, gets nothing and changes nothing.
"""
import asyncio
import copy

import pytest

from app.companion.kb import store_search as ss
from tests.fake_supabase import FakeSupabase

A, B = "tenant-a", "tenant-b"
VEC = [1.0, 0.0, 0.0]
TABLES = ("companion_kb_question_log", "companion_kb_shortcuts", "companion_kb_gaps")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(ss, "get_supabase", lambda: fake)
    return fake


@pytest.fixture
def world(db):
    """Tenant A: collection c1 with the Main resource (tier 1) and Book 3 (tier 2); Guru reads it.
    Tenant B: its own collection, book and character."""
    db.add("companion_kb_collections", id="c1", tenant_id=A, name="Astrology books")
    db.add("companion_kb_documents", id="main", tenant_id=A, collection_id="c1", title="Main resource", tier=1)
    db.add("companion_kb_documents", id="book3", tenant_id=A, collection_id="c1", title="Book 3", tier=2)
    db.add("companion_kb_chunks", id="m12", tenant_id=A, document_id="main", collection_id="c1", tier=1, seq=0,
           heading_path="Seventh House", text="Saturn in the seventh house delays marriage", page_from=12, page_to=12)
    for seq, (cid, start, end, text) in enumerate([("b87", 87, 88, "Sade Sati begins when sani enters the twelfth"),
                                                   ("b88", 88, 89, "Sade Sati lasts seven and a half years"),
                                                   ("b90", 90, 91, "Rahu and Ketu")]):
        db.add("companion_kb_chunks", id=cid, tenant_id=A, document_id="book3", collection_id="c1", tier=2, seq=seq,
               heading_path="", text=text, page_from=start, page_to=end)
    db.add("companions", id="guru", tenant_id=A, name="Guru", knowledge_collection_id="c1")
    db.add("companions", id="other-a", tenant_id=A, name="Maya", knowledge_collection_id=None)
    db.add("companion_kb_collections", id="c9", tenant_id=B, name="B books")
    db.add("companion_kb_documents", id="bdoc", tenant_id=B, collection_id="c9", title="B book", tier=2)
    db.add("companions", id="bbot", tenant_id=B, name="Bbot", knowledge_collection_id="c9")
    return db


def shortcut_row(**over):
    return {"companion_id": "guru", "topic": "How long does Sade Sati last?", "embedding": VEC,
            "embedding_model": "gemini", "document_id": "book3", "pages": [{"page_from": 88, "page_to": 88}], **over}


def gap_row(**over):
    return {"companion_id": "guru", "topic": "Saturn and Rahu together in the seventh house", "embedding": VEC,
            "embedding_model": "gemini", "ask_count": 5, "last_asked_at": "2026-11-10T10:00:00+00:00", **over}


def match(tenant, collection="c1", tier=2, terms=("sani",)):
    return run(ss.match_chunks(tenant, collection, tier, model="gemini", embedding_en=None, embedding_ta=None,
                               query_en="How long does Sade Sati last?", query_ta="", terms=list(terms), count=20))


def snapshot(db):
    return copy.deepcopy({t: db.rows(t) for t in TABLES})


# --- search -------------------------------------------------------------------------------------------

def test_match_chunks_finds_the_passage_with_its_title_and_list_name(world):
    rows = match(A)
    assert {r["id"] for r in rows} == {"b87", "b88"}
    assert {r["source"] for r in rows} == {"words", "trigram"}
    assert all(r["document_title"] == "Book 3" and r["tier"] == 2 for r in rows)


def test_match_chunks_is_scoped_to_tier_collection_and_tenant(world):
    assert {r["id"] for r in match(A, tier=1, terms=("saturn",))} == {"m12"}
    assert match(B) == []                      # tenant B asks with tenant A's collection id
    assert match(A, collection="c9") == []     # tenant A asks with tenant B's collection id


def test_chunks_for_pages_returns_every_passage_touching_the_range(world):
    rows = run(ss.chunks_for_pages(A, "book3", [{"page_from": 88, "page_to": 88}]))
    assert [r["id"] for r in rows] == ["b87", "b88"]
    assert rows[0]["document_title"] == "Book 3" and rows[0]["tier"] == 2 and rows[0]["collection_id"] == "c1"


def test_chunks_for_pages_refuses_another_tenant_and_junk_ranges(world):
    assert run(ss.chunks_for_pages(B, "book3", [{"page_from": 88, "page_to": 88}])) == []
    assert run(ss.chunks_for_pages(A, "book3", [{"page_from": "88"}, "x"])) == []
    assert run(ss.chunks_for_pages(A, "book3", [])) == []


# --- question log ---------------------------------------------------------------------------------------

def test_add_question_writes_topic_and_where_the_answer_was_and_no_person(world):
    row = run(ss.add_question(A, "guru", topic="  How long does Sade Sati last?  ", embedding=VEC,
                              embedding_model="gemini", basis="book",
                              best=[{"document_id": "book3", "page_from": 88, "page_to": 88, "score": 3,
                                     "text": "must not be stored"}, "junk"]))
    saved = world.rows("companion_kb_question_log")[0]
    assert row["id"] == saved["id"] and saved["topic"] == "How long does Sade Sati last?"
    assert saved["best"] == [{"document_id": "book3", "page_from": 88, "page_to": 88, "score": 3}]
    assert set(saved) == {"id", "created_at", "tenant_id", "companion_id", "topic", "embedding",
                          "embedding_model", "basis", "best"}       # no person, no message, no answer


def test_add_question_refuses_another_tenants_character_chat_and_empty_topic(world):
    args = dict(embedding=VEC, embedding_model="gemini", best=[])
    assert run(ss.add_question(B, "guru", topic="x", basis="own", **args)) is None
    assert run(ss.add_question(A, "guru", topic="x", basis="chat", **args)) is None
    assert run(ss.add_question(A, "guru", topic="   ", basis="own", **args)) is None
    assert world.rows("companion_kb_question_log") == []


def test_list_questions_parses_the_vector_filters_by_time_and_tenant(world):
    run(ss.add_question(A, "guru", topic="old", embedding=VEC, embedding_model="gemini", basis="own", best=[]))
    run(ss.add_question(A, "guru", topic="new", embedding=VEC, embedding_model="gemini", basis="book",
                        best=[{"document_id": "gone-book", "page_from": 1, "page_to": 1, "score": 3}]))
    run(ss.add_question(B, "bbot", topic="b's", embedding=None, embedding_model=None, basis="own", best=[]))
    old, new, theirs = world.rows("companion_kb_question_log")
    old["created_at"], new["created_at"], theirs["created_at"] = "2026-10-01T00:00:00+00:00", "2026-11-10T00:00:00+00:00", "2026-11-10T00:00:00+00:00"
    rows = run(ss.list_questions(A, "2026-10-12T00:00:00+00:00"))
    assert [r["topic"] for r in rows] == ["new"] and rows[0]["embedding"] == VEC
    assert rows[0]["best"][0]["document_id"] == "gone-book"         # a deleted book's entry is still returned
    assert [r["topic"] for r in run(ss.list_questions(B, "2026-01-01T00:00:00+00:00"))] == ["b's"]
    assert run(ss.list_questions(B, "2026-01-01T00:00:00+00:00"))[0]["embedding"] is None


def test_cleanup_and_tenant_list_look_across_all_businesses(world):
    for tenant, companion in ((A, "guru"), (A, "guru"), (B, "bbot")):
        run(ss.add_question(tenant, companion, topic="t", embedding=None, embedding_model=None, basis="own", best=[]))
    rows = world.rows("companion_kb_question_log")
    rows[0]["created_at"], rows[1]["created_at"], rows[2]["created_at"] = "2026-07-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00", "2026-07-02T00:00:00+00:00"
    assert run(ss.tenants_with_questions()) == [A, B]
    assert run(ss.delete_questions_before("2026-08-13T00:00:00+00:00")) == 2
    assert [r["tenant_id"] for r in world.rows("companion_kb_question_log")] == [A]


def test_cleanup_and_tenant_list_bring_no_log_rows_back(world, monkeypatch):
    """The nightly job must not download log rows (each carries a 768-number vector)."""
    for age in ("2026-07-01T00:00:00+00:00", "2026-07-02T00:00:00+00:00"):
        run(ss.add_question(A, "guru", topic="t", embedding=VEC, embedding_model="m", basis="own", best=[]))
        world.rows("companion_kb_question_log")[-1]["created_at"] = age
    payloads, real_table, real_rpc = [], world.table, world.rpc

    def spy(query):
        execute = query.execute

        def run_it():
            result = execute()
            payloads.append(result.data)
            return result
        query.execute = run_it
        return query

    monkeypatch.setattr(world, "table", lambda name: spy(real_table(name)))
    monkeypatch.setattr(world, "rpc", lambda name, params: spy(real_rpc(name, params)))
    assert run(ss.tenants_with_questions()) == [A]
    assert run(ss.delete_questions_before("2026-08-13T00:00:00+00:00")) == 2
    assert payloads == [[{"tenant_id": A}], []]
    assert world.rows("companion_kb_question_log") == []


# --- shortcuts ------------------------------------------------------------------------------------------

def test_add_shortcut_and_read_it_back(world):
    row = run(ss.add_shortcut(A, shortcut_row()))
    assert row["status"] == "active" and row["uses"] == 0 and row["embedding"] == VEC
    assert run(ss.get_shortcut(A, row["id"]))["pages"] == [{"page_from": 88, "page_to": 88}]
    assert [s["id"] for s in run(ss.active_shortcuts(A, "guru"))] == [row["id"]]
    assert run(ss.active_shortcuts(A, "other-a")) == []


def test_add_shortcut_refuses_foreign_or_malformed_rows(world):
    assert run(ss.add_shortcut(B, shortcut_row())) is None                           # A's character and book
    assert run(ss.add_shortcut(A, shortcut_row(document_id="bdoc"))) is None         # B's book
    assert run(ss.add_shortcut(A, shortcut_row(companion_id="bbot"))) is None        # B's character
    assert run(ss.add_shortcut(A, shortcut_row(pages=[]))) is None
    assert run(ss.add_shortcut(A, shortcut_row(topic=" "))) is None
    assert world.rows("companion_kb_shortcuts") == []


def test_update_shortcut_only_changes_the_allowed_fields(world):
    sid = run(ss.add_shortcut(A, shortcut_row()))["id"]
    row = run(ss.update_shortcut(A, sid, {"uses": 4, "misses_in_row": 0, "tenant_id": B, "topic": "hacked"}))
    assert row["uses"] == 4 and row["tenant_id"] == A and row["topic"] == "How long does Sade Sati last?"
    assert run(ss.update_shortcut(A, sid, {"status": "deleted"})) is None
    assert run(ss.update_shortcut(A, sid, {"status": "removed_by_owner"}))["status"] == "removed_by_owner"
    assert run(ss.list_shortcuts(A, statuses=["active"])) == []
    assert len(run(ss.list_shortcuts(A, companion_id="guru"))) == 1


def test_shortcuts_refuse_another_tenant(world):
    sid = run(ss.add_shortcut(A, shortcut_row()))["id"]
    before = snapshot(world)
    assert run(ss.get_shortcut(B, sid)) is None
    assert run(ss.update_shortcut(B, sid, {"status": "removed_by_owner"})) is None
    assert run(ss.list_shortcuts(B)) == [] and run(ss.active_shortcuts(B, "guru")) == []
    assert run(ss.shortcuts_for_collection(B, "c1")) == []
    assert snapshot(world) == before


def test_shortcuts_for_collection_has_the_owner_page_shape(world):
    first = run(ss.add_shortcut(A, shortcut_row()))
    second = run(ss.add_shortcut(A, shortcut_row(topic="Rahu and Ketu", pages=[{"page_from": 90, "page_to": 91}])))
    retired = run(ss.add_shortcut(A, shortcut_row(topic="old")))
    run(ss.update_shortcut(A, second["id"], {"uses": 7}))
    run(ss.update_shortcut(A, retired["id"], {"status": "retired"}))
    rows = run(ss.shortcuts_for_collection(A, "c1"))
    assert [r["id"] for r in rows] == [second["id"], first["id"]]                    # most used first, active only
    assert rows[0] == {"id": second["id"], "topic": "Rahu and Ketu", "document_id": "book3",
                       "document_title": "Book 3", "pages": [{"page_from": 90, "page_to": 91}], "uses": 7,
                       "companion_id": "guru", "companion_name": "Guru", "created_at": second["created_at"]}
    assert run(ss.shortcuts_for_collection(A, "c9")) == []


def test_a_shortcut_is_deleted_with_its_book(world):
    run(ss.add_shortcut(A, shortcut_row()))
    world.table("companion_kb_documents").delete().eq("id", "book3").execute()
    assert world.rows("companion_kb_shortcuts") == []


def test_document_exists_is_per_tenant(world):
    assert run(ss.document_exists(A, "book3")) is True
    assert run(ss.document_exists(B, "book3")) is False
    assert run(ss.document_exists(A, "nope")) is False


# --- gaps -----------------------------------------------------------------------------------------------

def test_add_gap_and_update_it(world):
    row = run(ss.add_gap(A, gap_row()))
    assert row["status"] == "open" and row["ask_count"] == 5 and row["embedding"] == VEC
    upd = run(ss.update_gap(A, row["id"], {"ask_count": 8, "last_asked_at": "2026-11-11T09:00:00+00:00",
                                           "topic": "hacked", "tenant_id": B}))
    assert upd["ask_count"] == 8 and upd["topic"] == gap_row()["topic"] and upd["tenant_id"] == A
    assert run(ss.update_gap(A, row["id"], {"status": "closed"})) is None
    assert run(ss.update_gap(A, row["id"], {"status": "covered"}))["status"] == "covered"
    assert run(ss.list_gaps(A, statuses=["open"])) == []
    assert [g["id"] for g in run(ss.list_gaps(A, companion_id="guru"))] == [row["id"]]


def test_gaps_refuse_another_tenant(world):
    gid = run(ss.add_gap(A, gap_row()))["id"]
    before = snapshot(world)
    assert run(ss.add_gap(B, gap_row())) is None                                     # A's character
    assert run(ss.add_gap(A, gap_row(companion_id="bbot"))) is None                  # B's character
    assert run(ss.get_gap(B, gid)) is None
    assert run(ss.update_gap(B, gid, {"status": "dismissed"})) is None
    assert run(ss.list_gaps(B)) == [] and run(ss.gaps_for_collection(B, "c1")) == []
    assert snapshot(world) == before
    assert run(ss.get_gap(A, gid))["status"] == "open"


def test_gaps_for_collection_lists_open_gaps_of_the_characters_reading_it(world):
    small = run(ss.add_gap(A, gap_row()))
    big = run(ss.add_gap(A, gap_row(topic="Kumbha lagna", ask_count=9)))
    done = run(ss.add_gap(A, gap_row(topic="answered")))
    run(ss.update_gap(A, done["id"], {"status": "dismissed"}))
    run(ss.add_gap(A, gap_row(companion_id="other-a", topic="Maya reads no collection")))
    rows = run(ss.gaps_for_collection(A, "c1"))
    assert [r["id"] for r in rows] == [big["id"], small["id"]]
    assert rows[0] == {"id": big["id"], "topic": "Kumbha lagna", "ask_count": 9,
                       "last_asked_at": "2026-11-10T10:00:00+00:00", "companion_id": "guru", "companion_name": "Guru"}
    assert run(ss.gaps_for_collection(A, "c9")) == []
