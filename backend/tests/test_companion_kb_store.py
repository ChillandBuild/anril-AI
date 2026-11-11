"""kb/store.py: the Anril Agents knowledge base tables + bucket (migration 257), against the fake.

T2: collections, tenant filter on every function, clear duplicate-name error.
T3: page ledger (320 pages -> 320 pending rows), delete leaves nothing, counts with list_documents.
"""
import asyncio
import copy

import pytest

from app.companion.kb import store
from tests.fake_supabase import FakeStorage, FakeSupabase

A, B = "tenant-a", "tenant-b"
KB_TABLES = ("companion_kb_collections", "companion_kb_documents", "companion_kb_pages",
             "companion_kb_chunks", "companion_kb_chunk_questions", "companions")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    fake.storage = FakeStorage()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    return fake


@pytest.fixture
def book(db):
    """Tenant A: collection "Astrology books", Book 7 with 3 pages (1 ok, 2 failed, 3 pending),
    2 passages, a stored file, and Guru reading the collection."""
    collection = run(store.create_collection(A, "Astrology books"))
    doc_id = "doc-7"
    path = store.storage_path(A, doc_id, "pdf")
    run(store.upload_file(path, b"%PDF-book7", "application/pdf"))
    document = run(store.create_document(A, collection["id"], title="Book 7", file_type="pdf",
                                         size_bytes=10, tier=1, storage_path=path, document_id=doc_id))
    run(store.set_page_count(A, doc_id, 3))
    run(store.save_page(A, doc_id, 1, status="ok", method="text_layer", text="Saturn in the 7th house"))
    run(store.save_page(A, doc_id, 2, status="failed", method="ocr", error="OCR timed out"))
    chunks = run(store.replace_chunks(A, doc_id, [
        {"heading_path": "Chapter 1", "text": "Saturn delays marriage", "page_from": 1, "page_to": 1},
        {"heading_path": "Chapter 1", "text": "Remedies", "page_from": 1, "page_to": 2},
    ]))
    db.add("companions", tenant_id=A, name="Guru", knowledge_collection_id=collection["id"])
    return {"collection": collection, "document": document, "doc_id": doc_id, "path": path, "chunks": chunks}


def snapshot(db):
    return copy.deepcopy({t: db.rows(t) for t in KB_TABLES}), dict(db.storage.files)


# --- T2: collections ---------------------------------------------------------------------------------

def test_create_collection_trims_and_returns_row(db):
    row = run(store.create_collection(A, "  Astrology books  "))
    assert row["name"] == "Astrology books" and row["tenant_id"] == A
    assert run(store.get_collection(A, row["id"]))["id"] == row["id"]


def test_duplicate_collection_name_gives_a_clear_error(db):
    run(store.create_collection(A, "Astrology books"))
    with pytest.raises(store.CollectionNameTaken, match="Astrology books"):
        run(store.create_collection(A, "Astrology books "))
    assert len(db.rows("companion_kb_collections")) == 1


def test_database_unique_violation_also_maps_to_name_taken(db, monkeypatch):
    async def never_taken(*_a, **_k):
        return False

    async def boom(_build):
        raise Exception('duplicate key value violates unique constraint (23505)')

    monkeypatch.setattr(store, "_name_taken", never_taken)
    monkeypatch.setattr(store, "_run", boom)
    with pytest.raises(store.CollectionNameTaken):
        run(store.create_collection(A, "Astrology books"))


def test_same_name_is_fine_for_another_business(db):
    a = run(store.create_collection(A, "Books"))
    b = run(store.create_collection(B, "Books"))
    assert a["id"] != b["id"] and b["tenant_id"] == B


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_bad_collection_name_is_refused(db, name):
    with pytest.raises(ValueError):
        run(store.create_collection(A, name))


def test_list_collections_carries_counts_and_readers(db, book):
    run(store.create_collection(A, "Empty shelf"))
    listed = run(store.list_collections(A))
    assert [c["name"] for c in listed] == ["Astrology books", "Empty shelf"]
    first, empty = listed
    assert (first["book_count"], first["page_count"], first["pages_ok"]) == (1, 3, 1)
    assert [r["name"] for r in first["read_by"]] == ["Guru"] and set(first["read_by"][0]) == {"id", "name"}
    assert (empty["book_count"], empty["page_count"], empty["pages_ok"], empty["read_by"]) == (0, 0, 0, [])


def test_rename_collection(db, book):
    other = run(store.create_collection(A, "Other"))
    assert run(store.rename_collection(A, other["id"], "Vastu books"))["name"] == "Vastu books"
    assert run(store.rename_collection(A, other["id"], "Vastu books"))["name"] == "Vastu books"  # same name, same row
    with pytest.raises(store.CollectionNameTaken):
        run(store.rename_collection(A, other["id"], "Astrology books"))


def test_delete_collection_refused_while_it_has_books(db, book):
    assert run(store.delete_collection(A, book["collection"]["id"])) is False
    assert len(db.rows("companion_kb_collections")) == 1


def test_delete_empty_collection_unpoints_the_character(db, book):
    run(store.delete_document(A, book["doc_id"]))
    assert run(store.delete_collection(A, book["collection"]["id"])) is True
    assert db.rows("companion_kb_collections") == []
    assert db.rows("companions")[0]["knowledge_collection_id"] is None


def test_collection_belongs_to_tenant(db, book):
    assert run(store.collection_belongs_to_tenant(A, book["collection"]["id"])) is True
    assert run(store.collection_belongs_to_tenant(A, "no-such-id")) is False


# --- T3: documents and the page ledger -----------------------------------------------------------------

def test_create_document_defaults_and_chosen_id(db, book):
    document = book["document"]
    assert document["id"] == "doc-7" and document["status"] == "processing"
    assert document["tier"] == 1 and document["storage_path"] == f"{A}/doc-7/original.pdf"
    assert run(store.get_document(A, "doc-7"))["title"] == "Book 7"


def test_create_document_refuses_a_bad_tier(db, book):
    with pytest.raises(ValueError):
        run(store.create_document(A, book["collection"]["id"], title="x", file_type="pdf", tier=3))


def test_page_count_320_gives_exactly_320_pending_rows(db, book):
    document = run(store.create_document(A, book["collection"]["id"], title="Big", file_type="pdf"))
    assert run(store.set_page_count(A, document["id"], 320)) == 320
    pages = [p for p in db.rows("companion_kb_pages") if p["document_id"] == document["id"]]
    assert sorted(p["page_no"] for p in pages) == list(range(1, 321))
    assert {p["status"] for p in pages} == {"pending"} and {p["tenant_id"] for p in pages} == {A}
    assert run(store.get_document(A, document["id"]))["page_count"] == 320


def test_set_page_count_twice_adds_nothing_and_keeps_read_pages(db, book):
    assert run(store.set_page_count(A, book["doc_id"], 3)) == 0
    assert len(db.rows("companion_kb_pages")) == 3
    assert run(store.get_page(A, book["doc_id"], 1))["status"] == "ok"


def test_list_documents_carries_page_counts(db, book):
    (document,) = run(store.list_documents(A))
    assert (document["pages_ok"], document["pages_failed"], document["pages_pending"]) == (1, 1, 1)
    assert document["failed_pages"] == [2] and document["collection_name"] == "Astrology books"
    assert run(store.list_documents(A, book["collection"]["id"]))[0]["id"] == book["doc_id"]
    assert run(store.list_documents(A, "another-collection")) == []


def test_failed_pages_come_back_sorted(db, book):
    document = run(store.create_document(A, book["collection"]["id"], title="Gaps", file_type="pdf"))
    run(store.set_page_count(A, document["id"], 12))
    for page_no in (11, 3, 7):
        run(store.save_page(A, document["id"], page_no, status="failed", error="blank"))
    listed = {d["id"]: d for d in run(store.list_documents(A))}[document["id"]]
    assert listed["failed_pages"] == [3, 7, 11]
    assert (listed["pages_ok"], listed["pages_failed"], listed["pages_pending"]) == (0, 3, 9)


def test_save_page_counts_every_attempt(db, book):
    doc_id = book["doc_id"]
    run(store.save_page(A, doc_id, 3, status="pending", error="rate limited"))
    page = run(store.save_page(A, doc_id, 3, status="ok", method="ocr", text="abc"))
    assert (page["attempts"], page["status"], page["method"], page["char_count"]) == (2, "ok", "ocr", 3)
    assert page["error"] is None
    assert run(store.save_page(A, doc_id, 99, status="ok", text="x")) is None
    with pytest.raises(ValueError):
        run(store.save_page(A, doc_id, 3, status="done"))


def test_save_page_trims_a_long_error(db, book):
    page = run(store.save_page(A, book["doc_id"], 3, status="failed", error="e" * 900))
    assert len(page["error"]) == 500


def test_pending_pages_and_ok_text_and_ledger(db, book):
    doc_id = book["doc_id"]
    assert run(store.pending_pages(A, doc_id)) == [3]
    assert run(store.ok_pages_text(A, doc_id)) == [(1, "Saturn in the 7th house")]
    ledger = run(store.list_pages(A, doc_id))
    assert [p["page_no"] for p in ledger] == [1, 2, 3] and all("text" not in p for p in ledger)
    assert run(store.list_pages(A, doc_id, with_text=True))[0]["text"] == "Saturn in the 7th house"


def test_requeue_failed_pages(db, book):
    doc_id = book["doc_id"]
    run(store.update_document(A, doc_id, status="ready_with_gaps"))
    assert run(store.requeue_failed_pages(A, doc_id)) == 1
    page = run(store.get_page(A, doc_id, 2))
    assert (page["status"], page["attempts"], page["error"]) == ("pending", 0, "OCR timed out")
    assert run(store.get_document(A, doc_id))["status"] == "processing"
    assert run(store.requeue_failed_pages(A, doc_id)) == 0


def test_update_document_only_takes_known_fields(db, book):
    updated = run(store.update_document(A, book["doc_id"], status="ready", text_layer_trusted=True))
    assert updated["status"] == "ready" and updated["text_layer_trusted"] is True
    with pytest.raises(ValueError, match="tier"):
        run(store.update_document(A, book["doc_id"], tier=2))
    with pytest.raises(ValueError):
        run(store.update_document(A, book["doc_id"], collection_id="elsewhere"))


def test_list_processing_documents_is_longest_untouched_first_across_businesses(db, book):
    theirs = run(store.create_collection(B, "B shelf"))
    b_doc = run(store.create_document(B, theirs["id"], title="B book", file_type="pdf"))
    done = run(store.create_document(A, book["collection"]["id"], title="Done", file_type="pdf"))
    run(store.update_document(A, done["id"], status="ready"))
    rows = run(store.list_processing_documents(10))
    assert [r["id"] for r in rows] == [book["doc_id"], b_doc["id"]]
    assert [r["tenant_id"] for r in rows] == [A, B]
    assert len(run(store.list_processing_documents(1))) == 1
    # Book 7 was just worked on: the book nobody touched comes first, whichever was uploaded first.
    # (So 20 old books that keep failing cannot hide a new one behind the limit.)
    run(store.update_document(A, book["doc_id"], status="processing"))
    assert [r["id"] for r in run(store.list_processing_documents(10))] == [b_doc["id"], book["doc_id"]]
    assert [r["id"] for r in run(store.list_processing_documents(1))] == [b_doc["id"]]


def test_a_new_book_starts_with_no_crashed_passes_and_retry_clears_the_count(db, book):
    assert book["document"]["crashed_passes"] == 0
    run(store.update_document(A, book["doc_id"], crashed_passes=2, status="failed"))
    assert run(store.get_document(A, book["doc_id"]))["crashed_passes"] == 2
    assert run(store.requeue_failed_pages(A, book["doc_id"])) == 1
    document = run(store.get_document(A, book["doc_id"]))
    assert (document["status"], document["crashed_passes"]) == ("processing", 0)


def test_nul_characters_never_reach_the_database(db, book):
    # Postgres refuses a text value with a NUL in it: one such page would fail every pass forever.
    run(store.save_page(A, book["doc_id"], 3, status="ok", method="ocr", text="Sat\x00urn"))
    assert run(store.get_page(A, book["doc_id"], 3))["text"] == "Saturn"
    assert run(store.get_page(A, book["doc_id"], 3))["char_count"] == 6
    rows = run(store.replace_chunks(A, book["doc_id"], [
        {"heading_path": "Chap\x00ter", "text": "Rem\x00edies", "page_from": 1, "page_to": 1}]))
    assert (rows[0]["heading_path"], rows[0]["text"]) == ("Chapter", "Remedies")
    added = run(store.add_chunk(A, book["doc_id"], heading_path="To\x00pic", text="An\x00swer"))
    assert (added["heading_path"], added["text"]) == ("Topic", "Answer")


def test_a_book_id_used_twice_is_a_typed_error(db, book, monkeypatch):
    real = store._run

    async def clash(build):
        query = build()
        if getattr(query, "op", "") == "insert" and query.name == "companion_kb_documents":
            raise Exception('duplicate key value violates unique constraint "companion_kb_documents_pkey" (23505)')
        return await real(lambda: query)

    monkeypatch.setattr(store, "_run", clash)
    with pytest.raises(store.DocumentExists):
        run(store.create_document(A, book["collection"]["id"], title="Again", file_type="pdf",
                                  document_id=book["doc_id"]))
    assert not issubclass(store.DocumentExists, LookupError)


def test_find_document_by_source_can_ask_for_one_copied_sales_document(db, book):
    shelf = book["collection"]["id"]
    copy_1 = run(store.create_document(A, shelf, title="Price list", file_type="pdf", source="sales_copy",
                                       source_document_id="sales-1"))
    run(store.create_document(A, shelf, title="FAQ", file_type="pdf", source="sales_copy",
                              source_document_id="sales-2"))
    assert run(store.find_document_by_source(A, shelf, "sales_copy", source_document_id="sales-1"))["id"] == copy_1["id"]
    assert run(store.find_document_by_source(A, shelf, "sales_copy", source_document_id="sales-9")) is None
    assert run(store.find_document_by_source(B, shelf, "sales_copy", source_document_id="sales-1")) is None


def test_unfinished_books_can_leave_out_businesses_that_cannot_be_filled(db, book):
    theirs = run(store.create_collection(B, "B shelf"))
    b_doc = run(store.create_document(B, theirs["id"], title="B book", file_type="pdf"))
    run(store.replace_chunks(B, b_doc["id"], [{"heading_path": "", "text": "x", "page_from": 1, "page_to": 1}]))
    both = run(store.documents_with_unfinished_chunks())
    assert both == [{"tenant_id": A, "document_id": book["doc_id"]}, {"tenant_id": B, "document_id": b_doc["id"]}]
    # Tenant A has no AI key: asked again without it, tenant B's book is found even at limit 1.
    assert run(store.documents_with_unfinished_chunks(limit=1, exclude_tenants=[A])) == [
        {"tenant_id": B, "document_id": b_doc["id"]}]


# --- passages --------------------------------------------------------------------------------------

def test_replace_chunks_adds_scope_and_order(db, book):
    first, second = book["chunks"]
    assert (first["seq"], second["seq"]) == (0, 1)
    assert first["tier"] == 1 and first["collection_id"] == book["collection"]["id"]
    assert first["tenant_id"] == A and first["document_id"] == book["doc_id"]
    assert "embedding" not in first
    assert [c["id"] for c in run(store.list_chunks(A, book["doc_id"]))] == [first["id"], second["id"]]


def test_replace_chunks_swaps_the_old_set_and_its_questions(db, book):
    run(store.add_chunk_questions(A, book["chunks"][0], [
        {"question_en": "Does Saturn delay marriage?", "question_ta": "", "embedding": [0.1, 0.2],
         "embedding_model": "m1"}]))
    new = run(store.replace_chunks(A, book["doc_id"], [
        {"heading_path": "h" * 900, "text": "Only passage", "page_from": 2, "page_to": 3}]))
    assert len(db.rows("companion_kb_chunks")) == 1 and db.rows("companion_kb_chunk_questions") == []
    assert new[0]["seq"] == 0 and len(new[0]["heading_path"]) == 500
    assert run(store.replace_chunks(A, book["doc_id"], [])) == [] and db.rows("companion_kb_chunks") == []


def test_set_tier_moves_the_passages_too(db, book):
    assert run(store.set_tier(A, book["doc_id"], 2))["tier"] == 2
    assert {c["tier"] for c in db.rows("companion_kb_chunks")} == {2}
    with pytest.raises(ValueError):
        run(store.set_tier(A, book["doc_id"], 5))


def test_embedding_is_written_as_a_pgvector_string(db, book):
    first, second = book["chunks"]
    assert [c["id"] for c in run(store.chunks_missing_embedding(A, book["doc_id"], 10))] == [first["id"], second["id"]]
    run(store.set_chunk_embedding(A, first["id"], [0.5, 0.25], "gemini-embedding-001"))
    row = next(r for r in db.rows("companion_kb_chunks") if r["id"] == first["id"])
    assert row["embedding"] == store.to_pgvector([0.5, 0.25]) and row["embedding_model"] == "gemini-embedding-001"
    assert [c["id"] for c in run(store.chunks_missing_embedding(A, book["doc_id"], 10))] == [second["id"]]


def test_signposts_are_saved_and_the_passage_is_marked_done(db, book):
    first, second = book["chunks"]
    assert len(run(store.chunks_missing_signposts(A, book["doc_id"], 10))) == 2
    saved = run(store.add_chunk_questions(A, first, [
        {"question_en": "Does Saturn delay marriage?", "question_ta": "சனி", "embedding": [0.1, 0.2],
         "embedding_model": "m1"},
        {"question_en": "Late marriage?", "question_ta": "", "embedding": None, "embedding_model": None}]))
    assert saved == 2
    questions = db.rows("companion_kb_chunk_questions")
    assert {q["chunk_id"] for q in questions} == {first["id"]}
    assert {q["tenant_id"] for q in questions} == {A}
    assert {q["collection_id"] for q in questions} == {book["collection"]["id"]}
    assert questions[0]["embedding"] == store.to_pgvector([0.1, 0.2]) and questions[1]["embedding"] is None
    assert run(store.add_chunk_questions(A, second, [])) == 0  # no questions: still marked done
    assert run(store.chunks_missing_signposts(A, book["doc_id"], 10)) == []


def test_books_have_no_signpost_work(db, book):
    run(store.set_tier(A, book["doc_id"], 2))
    assert run(store.chunks_missing_signposts(A, book["doc_id"], 10)) == []


def test_get_chunks_keeps_the_asked_order(db, book):
    first, second = book["chunks"]
    assert [c["id"] for c in run(store.get_chunks(A, [second["id"], "nope", first["id"]]))] == [second["id"], first["id"]]
    assert run(store.get_chunks(A, [])) == []


# --- delete + stored files -----------------------------------------------------------------------------

def test_delete_document_leaves_no_rows_and_no_file(db, book):
    run(store.add_chunk_questions(A, book["chunks"][0], [{"question_en": "q", "question_ta": ""}]))
    assert run(store.delete_document(A, book["doc_id"])) is True
    for table in ("companion_kb_documents", "companion_kb_pages", "companion_kb_chunks",
                  "companion_kb_chunk_questions"):
        assert db.rows(table) == [], table
    assert db.storage.files == {}
    assert run(store.delete_document(A, book["doc_id"])) is False


def test_delete_document_survives_a_storage_failure(db, book, caplog):
    db.storage.fail_remove = True
    assert run(store.delete_document(A, book["doc_id"])) is True
    assert db.rows("companion_kb_documents") == [] and db.rows("companion_kb_pages") == []
    assert "left in storage" in caplog.text


def test_delete_document_never_removes_outside_the_tenant_folder(db, book):
    run(store.upload_file(f"{B}/x/original.pdf", b"theirs", "application/pdf"))
    run(store.update_document(A, book["doc_id"], storage_path=f"{B}/x/original.pdf"))
    assert run(store.delete_document(A, book["doc_id"])) is True
    assert (store.BUCKET, f"{B}/x/original.pdf") in db.storage.files


def test_storage_path_is_the_tenant_folder():
    assert store.storage_path("t1", "d1", "PDF") == "t1/d1/original.pdf"
    assert store.storage_path("t1", "d1", "../x") == "t1/d1/original.x"
    assert store.storage_path("t1", "d1", "") == "t1/d1/original.bin"


def test_signed_upload_and_stored_file_and_download(db, book, tmp_path):
    link = run(store.create_signed_upload(book["path"]))
    assert set(link) == {"signed_url", "token", "path"} and link["path"] == book["path"] and link["signed_url"]
    assert run(store.stored_file(A, book["doc_id"])) == {
        "path": book["path"], "name": "original.pdf", "size_bytes": len(b"%PDF-book7")}
    assert run(store.stored_file(A, "never-uploaded")) is None
    dest = tmp_path / "book.pdf"
    assert run(store.download_file(book["path"], str(dest))) == 10 and dest.read_bytes() == b"%PDF-book7"
    assert run(store.remove_file(book["path"])) is True and db.storage.files == {}
    db.storage.fail_remove = True
    assert run(store.remove_file("anything")) is False


# --- tenant B gets nothing and changes nothing: one test per function ----------------------------------

_Q = [{"question_en": "q", "question_ta": "", "embedding": [0.1], "embedding_model": "m"}]
_CHUNK = [{"heading_path": "", "text": "theirs", "page_from": 1, "page_to": 1}]

TENANT_B_CALLS = {
    "get_collection": lambda k: store.get_collection(B, k["collection"]["id"]),
    "collection_belongs_to_tenant": lambda k: store.collection_belongs_to_tenant(B, k["collection"]["id"]),
    "list_collections": lambda k: store.list_collections(B),
    "rename_collection": lambda k: store.rename_collection(B, k["collection"]["id"], "Taken over"),
    "delete_collection": lambda k: store.delete_collection(B, k["collection"]["id"]),
    "get_document": lambda k: store.get_document(B, k["doc_id"]),
    "list_documents": lambda k: store.list_documents(B),
    "list_documents_in_their_collection": lambda k: store.list_documents(B, k["collection"]["id"]),
    "update_document": lambda k: store.update_document(B, k["doc_id"], title="Taken over", status="failed"),
    "set_tier": lambda k: store.set_tier(B, k["doc_id"], 2),
    "delete_document": lambda k: store.delete_document(B, k["doc_id"]),
    "set_page_count": lambda k: store.set_page_count(B, k["doc_id"], 50),
    "list_pages": lambda k: store.list_pages(B, k["doc_id"], with_text=True),
    "get_page": lambda k: store.get_page(B, k["doc_id"], 1),
    "pending_pages": lambda k: store.pending_pages(B, k["doc_id"]),
    "save_page": lambda k: store.save_page(B, k["doc_id"], 3, status="ok", text="theirs"),
    "ok_pages_text": lambda k: store.ok_pages_text(B, k["doc_id"]),
    "requeue_failed_pages": lambda k: store.requeue_failed_pages(B, k["doc_id"]),
    "replace_chunks": lambda k: store.replace_chunks(B, k["doc_id"], _CHUNK),
    "list_chunks": lambda k: store.list_chunks(B, k["doc_id"]),
    "get_chunks": lambda k: store.get_chunks(B, [c["id"] for c in k["chunks"]]),
    "chunks_missing_embedding": lambda k: store.chunks_missing_embedding(B, k["doc_id"], 10),
    "set_chunk_embedding": lambda k: store.set_chunk_embedding(B, k["chunks"][0]["id"], [0.9], "m"),
    "chunks_missing_signposts": lambda k: store.chunks_missing_signposts(B, k["doc_id"], 10),
    "add_chunk_questions": lambda k: store.add_chunk_questions(B, k["chunks"][0], _Q),
    "stored_file": lambda k: store.stored_file(B, k["doc_id"]),
    # added for ingest
    "add_chunk": lambda k: store.add_chunk(B, k["doc_id"], heading_path="theirs", text="theirs"),
    "find_document_by_source": lambda k: store.find_document_by_source(B, k["collection"]["id"], "upload"),
}


@pytest.mark.parametrize("name", sorted(TENANT_B_CALLS))
def test_tenant_b_gets_nothing_and_changes_nothing(db, book, name):
    before = snapshot(db)
    result = run(TENANT_B_CALLS[name](book))
    assert not result, f"{name} gave tenant B something: {result!r}"
    assert snapshot(db) == before, f"{name} changed tenant A's data"


def test_tenant_b_cannot_register_a_book_in_tenant_a_collection(db, book):
    before = snapshot(db)
    with pytest.raises(store.CollectionNotFound):
        run(store.create_document(B, book["collection"]["id"], title="Theirs", file_type="pdf"))
    assert snapshot(db) == before


def test_tenant_b_create_collection_stays_in_tenant_b(db, book):
    before_a = [r for r in db.rows("companion_kb_collections") if r["tenant_id"] == A]
    mine = run(store.create_collection(B, "Astrology books"))  # same name as A's: no clash, no leak
    assert mine["tenant_id"] == B
    assert [r for r in db.rows("companion_kb_collections") if r["tenant_id"] == A] == before_a
    assert [c["id"] for c in run(store.list_collections(B))] == [mine["id"]]
    assert run(store.list_collections(B))[0]["book_count"] == 0


def test_every_tenant_function_has_a_tenant_b_test():
    """A new public function that takes tenant_id must be added to TENANT_B_CALLS."""
    import inspect
    covered = {n.split("_in_")[0] for n in TENANT_B_CALLS} | {"create_collection", "create_document", "storage_path"}
    public = {n for n, f in vars(store).items()
              if inspect.isfunction(f) and f.__module__ == store.__name__ and not n.startswith("_")
              and "tenant_id" in inspect.signature(f).parameters}
    assert public - covered == set()


def test_tenant_b_cannot_delete_tenant_a_empty_collection(db):
    empty = run(store.create_collection(A, "Empty shelf"))  # no books: only the tenant check stops it
    assert run(store.delete_collection(B, empty["id"])) is False
    assert [r["id"] for r in db.rows("companion_kb_collections")] == [empty["id"]]
