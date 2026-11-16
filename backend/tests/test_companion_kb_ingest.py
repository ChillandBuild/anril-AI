"""kb-ingest T8/T9: reading a book page by page into passages, against the fake database and storage.

OCR, embeddings and the signpost LLM are patched (no network). PDFs are built in the test.
"""
import asyncio
import copy
import json
import logging

import httpx
import pytest

from app.companion.kb import filetypes, ingest, ocr, store
from tests.fake_supabase import FakeStorage, FakeSupabase

A, B = "tenant-a", "tenant-b"
SECRET = "Saturn"          # a word of the page text that must never reach a log line
P1 = "Saturn in the seventh house delays marriage and asks for patience from the native."
P2 = "Jupiter in the ninth house brings teachers, long journeys and good fortune to the native."
P3 = "Remedies for Saturn are fasting on Saturday and lighting a sesame oil lamp at dusk."
SCAN = "Scanned Saturn page read by OCR: the verse about Rahu and Ketu in the twelfth house."
TABLES = ("companion_kb_documents", "companion_kb_pages", "companion_kb_chunks", "companion_kb_chunk_questions")


def run(coro):
    return asyncio.run(coro)


def make_pdf(page_texts: list) -> bytes:
    """One Helvetica line per page; None = a page with no text layer (a scan)."""
    n = len(page_texts)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(n)) + b"] /Count %d >>" % n,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(page_texts):
        stream = f"BT /F1 10 Tf 40 700 Td ({text}) Tj ET".encode() if text else b""
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                    b"/Resources << /Font << /F1 3 0 R >> >> >>" % (5 + 2 * i))
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref_at)


class World:
    """The patched outside world: which pages OCR fails on, and what was called."""

    def __init__(self):
        self.ocr_calls: list[int] = []
        self.ocr_fail: set[int] = set()
        self.ocr_error = "Gemini error 503"
        self.ocr_text = lambda page_no: f"{SCAN} (page {page_no})"
        self.embed_calls: list[list[str]] = []
        self.embed_ok = True
        self.llm_calls = 0
        self.llm_ok = True
        self.has_key = True
        self.clock = 0.0
        self.ocr_seconds = 0.0


@pytest.fixture
def db(monkeypatch, tmp_path):
    fake = FakeSupabase()
    fake.storage = FakeStorage()
    monkeypatch.setattr(store, "get_supabase", lambda: fake)
    monkeypatch.setattr(store, "_http_client", fake.storage.http_client)
    monkeypatch.setattr(ingest, "get_supabase", lambda: fake)
    monkeypatch.setattr(ingest, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(ingest, "_released", {})
    monkeypatch.setattr(ingest, "_deferred", set())
    monkeypatch.setattr(ingest, "_last_fill", None)
    return fake


@pytest.fixture
def world(monkeypatch, db):
    w = World()

    async def ocr_pdf_page(tenant_id, path, page_no):
        w.ocr_calls.append(page_no)
        w.clock += w.ocr_seconds
        if not w.has_key:
            return None, ocr.NO_KEY_ERROR
        return (None, w.ocr_error) if page_no in w.ocr_fail else (w.ocr_text(page_no), None)

    async def ocr_image(tenant_id, image, mime_type="image/png"):
        w.ocr_calls.append(1)
        return (w.ocr_text(1), None) if w.has_key else (None, ocr.NO_KEY_ERROR)

    async def embed(texts, kind, tenant_id, model=None, retries=True):
        w.embed_calls.append(list(texts))
        return [[0.1, 0.2] if w.embed_ok else None for _ in texts]

    async def llm(messages, max_tokens=300, tenant_id=None, *, purpose="ai_reply", temperature=0.4, model=None):
        w.llm_calls += 1
        assert purpose == "companion_kb_signposts"
        if not w.llm_ok:
            raise RuntimeError("gemini down")
        return "```json\n" + json.dumps([{"en": f"Question {i}?", "ta": f"கேள்வி {i}?"} for i in range(4)]) + "\n```"

    def key(name, tenant_id):
        if not w.has_key:
            raise RuntimeError("no key")
        return "k"

    monkeypatch.setattr(ingest.ocr, "ocr_pdf_page", ocr_pdf_page)
    monkeypatch.setattr(ingest.ocr, "ocr_image", ocr_image)
    monkeypatch.setattr(ingest.memory_embed, "embed", embed)
    monkeypatch.setattr(ingest.ai_reply, "_llm_chat", llm)
    monkeypatch.setattr(ingest, "require_tenant_setting", key)
    monkeypatch.setattr(ingest, "_clock", lambda: w.clock)
    return w


def add_book(data: bytes, file_type: str = "pdf", *, tenant: str = A, tier: int = 2, title: str = "Book 7",
             collection: dict | None = None) -> dict:
    collection = collection or run(store.create_collection(tenant, f"Books {title} {tier}"))
    doc_id = f"doc-{tenant}-{title}-{tier}".replace(" ", "")
    path = store.storage_path(tenant, doc_id, file_type)
    run(store.upload_file(path, data, "application/octet-stream"))
    return run(store.create_document(tenant, collection["id"], title=title, file_type=file_type,
                                     size_bytes=len(data), tier=tier, storage_path=path, document_id=doc_id))


def pages_of(doc, tenant=A):
    return {p["page_no"]: p for p in run(store.list_pages(tenant, doc["id"], with_text=True))}


def chunk_text(db, doc):
    return "\n".join(c["text"] for c in db.rows("companion_kb_chunks") if c["document_id"] == doc["id"])


def snapshot(db):
    return copy.deepcopy({t: db.rows(t) for t in TABLES})


# --- a typed book, a scanned page, a page that never reads --------------------------------------------

def test_typed_pdf_ends_ready_with_embedded_passages_and_no_ocr(db, world, tmp_path):
    doc = add_book(make_pdf([P1, P2, P3]))
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    saved = run(store.get_document(A, doc["id"]))
    assert (saved["status"], saved["page_count"], saved["error"]) == ("ready", 3, None)
    assert world.ocr_calls == []
    assert {n: (p["status"], p["method"]) for n, p in pages_of(doc).items()} == {
        n: ("ok", "text_layer") for n in (1, 2, 3)}
    chunks = [c for c in db.rows("companion_kb_chunks") if c["document_id"] == doc["id"]]
    assert chunks and all(c["embedding"] and c["embedding_model"] for c in chunks)
    assert "seventh house" in chunk_text(db, doc) and "sesame oil" in chunk_text(db, doc)
    assert world.embed_calls[0][0].startswith("Book 7\n")           # the heading path leads the embedded text
    assert world.llm_calls == 0 and db.rows("companion_kb_chunk_questions") == []   # tier 2: no signposts
    assert not (tmp_path / "cache").exists() or list((tmp_path / "cache").iterdir()) == []


def test_a_scanned_page_goes_through_ocr(db, world):
    doc = add_book(make_pdf([P1, None, P3]))
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert world.ocr_calls == [2]
    ledger = pages_of(doc)
    assert (ledger[1]["method"], ledger[2]["method"], ledger[3]["method"]) == ("text_layer", "ocr", "text_layer")
    assert "Rahu and Ketu" in chunk_text(db, doc)


def test_a_page_that_never_reads_is_marked_failed_and_the_book_has_gaps(db, world, caplog):
    caplog.set_level(logging.DEBUG, logger="app")     # our own loggers (pdfminer's DEBUG output is not ours)
    world.ocr_fail = {2}
    doc = add_book(make_pdf([P1, None, P3]))
    assert run(ingest.run_document(A, doc["id"])) == "processing"
    assert run(ingest.run_document(A, doc["id"])) == "processing"
    assert pages_of(doc)[2]["status"] == "pending" and pages_of(doc)[2]["error"] == "Gemini error 503"
    assert run(ingest.run_document(A, doc["id"])) == "ready_with_gaps"
    page = pages_of(doc)[2]
    assert (page["status"], page["attempts"], page["error"]) == ("failed", 3, "Gemini error 503")
    assert world.ocr_calls == [2, 2, 2]
    listed = run(store.list_documents(A))[0]
    assert (listed["status"], listed["failed_pages"], listed["pages_ok"]) == ("ready_with_gaps", [2], 2)
    text = chunk_text(db, doc)
    assert "seventh house" in text and "sesame oil" in text          # the other pages are searchable
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app."))
    assert "companion kb" in ours or ours == ""
    assert SECRET not in ours and "seventh house" not in ours and "sesame" not in ours and "Rahu" not in ours


def test_a_second_run_on_a_finished_book_does_nothing(db, world):
    doc = add_book(make_pdf([P1, None, P3]), tier=1)
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    before, calls = snapshot(db), (len(world.ocr_calls), len(world.embed_calls), world.llm_calls)
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert snapshot(db) == before
    assert (len(world.ocr_calls), len(world.embed_calls), world.llm_calls) == calls


def test_the_budget_stops_a_pass_and_the_next_one_carries_on(db, world, tmp_path):
    world.ocr_seconds = 30.0                                          # 4 pages at once = 120 "seconds"
    doc = add_book(make_pdf([None] * 6))
    assert run(ingest.run_document(A, doc["id"], budget_seconds=45.0)) == "processing"
    assert sorted(world.ocr_calls) == [1, 2, 3, 4]
    assert [n for n, p in pages_of(doc).items() if p["status"] == "pending"] == [5, 6]
    assert len(list((tmp_path / "cache").iterdir())) == 1            # the file is kept between passes
    assert db.rows("companion_kb_chunks") == []
    world.ocr_seconds = 0.0
    assert run(ingest.run_document(A, doc["id"], budget_seconds=45.0)) == "ready"
    assert sorted(world.ocr_calls[4:]) == [5, 6]                      # nothing is read twice
    assert list((tmp_path / "cache").iterdir()) == []                 # removed when the book is finished


def test_retry_rereads_only_the_failed_page_and_recuts_the_passages(db, world):
    world.ocr_fail = {2}
    doc = add_book(make_pdf([P1, None, P3]))
    for _ in range(3):
        status = run(ingest.run_document(A, doc["id"]))
    assert status == "ready_with_gaps" and "Rahu" not in chunk_text(db, doc)
    world.ocr_fail, world.ocr_calls = set(), []
    assert run(store.requeue_failed_pages(A, doc["id"])) == 1
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert world.ocr_calls == [2]
    text = chunk_text(db, doc)
    assert "Rahu and Ketu" in text and "seventh house" in text
    assert all(c["embedding"] for c in db.rows("companion_kb_chunks"))


# --- signposts, the Gemini key, other file types ------------------------------------------------------

def test_a_main_resource_gets_signpost_questions(db, world):
    doc = add_book(make_pdf([P1, P2, P3]), tier=1, title="Main resource")
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    chunks = [c for c in db.rows("companion_kb_chunks") if c["document_id"] == doc["id"]]
    questions = db.rows("companion_kb_chunk_questions")
    assert world.llm_calls == len(chunks) and len(questions) == 3 * len(chunks)      # 4 offered, 3 kept
    assert all(c["signposts_at"] for c in chunks)
    assert questions[0]["question_en"] == "Question 0?" and questions[0]["question_ta"] == "கேள்வி 0?"
    assert all(q["tenant_id"] == A and q["embedding"] for q in questions)


def test_signposts_that_fail_do_not_block_the_book_and_are_filled_in_later(db, world):
    world.llm_ok = False
    doc = add_book(make_pdf([P1, P2, P3]), tier=1)
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert db.rows("companion_kb_chunk_questions") == []
    world.llm_ok = True
    assert run(ingest.run_pending())["filled"] == 1
    assert len(db.rows("companion_kb_chunk_questions")) == 3


def test_no_gemini_key_fails_a_scanned_book_with_text_the_owner_can_read(db, world):
    world.has_key = False
    doc = add_book(make_pdf([P1, None]))
    assert run(ingest.run_document(A, doc["id"])) == "failed"
    saved = run(store.get_document(A, doc["id"]))
    assert saved["status"] == "failed" and saved["error"] == ingest.NO_KEY_ERROR
    assert saved["error"].startswith(ocr.NO_KEY_ERROR)
    world.has_key = True                                              # the key is added, the owner presses Retry
    assert run(store.requeue_failed_pages(A, doc["id"])) == 1
    assert run(ingest.run_document(A, doc["id"])) == "ready"


def test_no_gemini_key_still_reads_a_typed_file_as_far_as_it_can(db, world):
    world.has_key = False
    doc = add_book(P1.encode(), "txt")
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    chunks = db.rows("companion_kb_chunks")
    assert chunks and all(not c.get("embedding") for c in chunks) and world.embed_calls == []
    world.has_key = True                                              # vectors arrive once the key does
    assert run(ingest.run_pending())["filled"] == 1
    assert all(c["embedding"] for c in db.rows("companion_kb_chunks"))


def test_a_text_file_goes_through_virtual_pages(db, world):
    lines = [f"Line {i}: " + "remedy words " * 6 for i in range(80)]          # about 7,000 characters
    doc = add_book("\n".join(lines).encode(), "txt", title="Notes")
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    ledger = pages_of(doc)
    assert len(ledger) == 3 and all(p["status"] == "ok" and p["char_count"] <= filetypes.PAGE_CHARS
                                    for p in ledger.values())
    assert world.ocr_calls == [] and "Line 79:" in chunk_text(db, doc)


def test_a_word_file_keeps_its_headings(db, world, tmp_path):
    import docx
    document = docx.Document()
    document.add_heading("Saturn", level=1)
    document.add_paragraph(P1)
    path = tmp_path / "remedies.docx"
    document.save(str(path))
    doc = add_book(path.read_bytes(), "docx", title="Remedies")
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    chunk = db.rows("companion_kb_chunks")[0]
    assert chunk["heading_path"] == "Remedies > Saturn" and "seventh house" in chunk["text"]


def test_an_image_is_one_page_read_by_ocr(db, world):
    doc = add_book(b"\x89PNG fake", "png", title="Chart")
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert world.ocr_calls == [1] and pages_of(doc)[1]["method"] == "ocr"


def test_a_file_that_cannot_be_opened_or_found_fails_the_book(db, world):
    broken = add_book(b"this is not a pdf", "pdf", title="Broken")
    assert run(ingest.run_document(A, broken["id"])) == "failed"
    assert run(store.get_document(A, broken["id"]))["error"] == ingest.BAD_FILE_ERROR
    gone = add_book(make_pdf([P1]), title="Gone")
    db.storage.files.clear()
    assert run(ingest.run_document(A, gone["id"])) == "failed"
    assert run(store.get_document(A, gone["id"]))["error"] == ingest.NO_FILE_ERROR
    assert run(ingest.run_document(A, "no-such-book")) == "not_found"
    assert run(ingest.run_document(B, broken["id"])) == "not_found"    # another business's id


def test_a_database_error_never_reaches_the_caller(db, world, monkeypatch):
    doc = add_book(make_pdf([P1]))

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "pending_pages", boom)
    assert run(ingest.run_document(A, doc["id"])) == "processing"


# --- the spot-check -----------------------------------------------------------------------------------

def test_spot_check_trusts_a_text_layer_that_matches_ocr(db, world):
    texts = [P1, P2, P3, P1 + " More."]
    world.ocr_text = lambda page_no: texts[page_no - 1]
    doc = add_book(make_pdf(texts))
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert sorted(world.ocr_calls) == [1, 2, 4]                       # the 3 checked pages, nothing else
    assert run(store.get_document(A, doc["id"]))["text_layer_trusted"] is True
    assert {p["method"] for p in pages_of(doc).values()} == {"text_layer"}


def test_spot_check_sends_every_page_to_ocr_when_the_text_layer_is_garbage(db, world):
    world.ocr_text = lambda page_no: f"முற்றிலும் வேறுபட்ட தமிழ் உரை பக்கம் {page_no} " * 3
    doc = add_book(make_pdf([P1, P2, P3, P1]))
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert run(store.get_document(A, doc["id"]))["text_layer_trusted"] is False
    assert {p["method"] for p in pages_of(doc).values()} == {"ocr"}
    assert sorted(world.ocr_calls) == [1, 2, 3, 4]                    # the checked pages are not read twice
    assert "seventh house" not in chunk_text(db, doc)


# --- the every-minute job and the background start ----------------------------------------------------

def test_run_pending_reads_books_of_every_business_inside_one_budget(db, world):
    a = add_book(make_pdf([P1]), tenant=A)
    b = add_book(make_pdf([P2]), tenant=B)
    db.rows("companion_kb_documents")[0]["updated_at"] = db.rows("companion_kb_documents")[1]["updated_at"] = \
        "2026-01-01T00:00:00+00:00"                                   # registered long ago, nobody is on them
    out = run(ingest.run_pending())
    assert (out["waiting"], out["skipped"], out["run"], out["finished"]) == (2, 0, 2, 2)
    assert run(store.get_document(A, a["id"]))["status"] == "ready"
    assert run(store.get_document(B, b["id"]))["status"] == "ready"
    assert {c["tenant_id"] for c in db.rows("companion_kb_chunks")} == {A, B}
    assert run(ingest.run_pending())["waiting"] == 0


def test_run_pending_lets_the_helper_exit_after_every_pass(db, world, monkeypatch):
    # The helper process holds the memory of the pages it read until it exits.
    closed = []
    monkeypatch.setattr(ingest.helper, "close", lambda: closed.append(1))
    add_book(make_pdf([P1]))
    run(ingest.run_pending())
    run(ingest.run_pending())          # nothing waiting: still closed
    assert closed == [1, 1]


def test_run_pending_leaves_a_book_another_worker_is_reading(db, world):
    doc = add_book(make_pdf([None] * 6))                              # just registered: its upload request reads it
    assert run(ingest.run_pending())["skipped"] == 1
    assert world.ocr_calls == []
    world.ocr_seconds = 30.0
    assert run(ingest.run_document(A, doc["id"])) == "processing"     # a pass of THIS process ended
    world.ocr_seconds = 0.0
    out = run(ingest.run_pending())                                   # ... so the next minute carries straight on
    assert (out["skipped"], out["finished"]) == (0, 1)
    assert run(store.get_document(A, doc["id"]))["status"] == "ready"


def test_run_pending_stops_starting_books_when_the_budget_is_used(db, world):
    for title in ("One", "Two", "Three"):
        add_book(make_pdf([None]), title=title)
    for row in db.rows("companion_kb_documents"):
        row["updated_at"] = "2026-01-01T00:00:00+00:00"
    world.ocr_seconds = 50.0
    out = run(ingest.run_pending(budget_seconds=45.0))
    assert out["run"] == 2                                            # two lanes started, the third book waits
    assert sorted(d["status"] for d in db.rows("companion_kb_documents")).count("processing") >= 1


def test_schedule_starts_a_background_pass(db, world):
    doc = add_book(make_pdf([P1]))

    async def go():
        ingest.schedule(A, doc["id"])
        assert len(ingest._tasks) == 1
        await asyncio.gather(*list(ingest._tasks))

    run(go())
    assert run(store.get_document(A, doc["id"]))["status"] == "ready" and not ingest._tasks
    ingest.schedule(A, doc["id"])                                     # no running loop: nothing to start, no error


# --- copy from Anril Sales (read-only) ----------------------------------------------------------------

@pytest.fixture
def sales(db, monkeypatch):
    started = []
    monkeypatch.setattr(ingest, "schedule", lambda tenant_id, document_id: started.append((tenant_id, document_id)))
    files = db.storage.files
    files[("knowledge-documents", f"{A}/u1_Remedies.pdf")] = make_pdf([P1])
    files[("knowledge-documents", f"{B}/u2_Secret.pdf")] = make_pdf([P2])
    files[("knowledge-documents", f"{A}/u3_Clip.mp4")] = b"video"
    rows = {
        "mine": db.add("knowledge_documents", tenant_id=A, name="Remedies.pdf", file_type="application/pdf",
                       storage_path=f"{A}/u1_Remedies.pdf"),
        "theirs": db.add("knowledge_documents", tenant_id=B, name="Secret.pdf", file_type="application/pdf",
                         storage_path=f"{B}/u2_Secret.pdf"),
        "video": db.add("knowledge_documents", tenant_id=A, name="Clip.mp4", file_type="video/mp4",
                        storage_path=f"{A}/u3_Clip.mp4"),
        "no_file": db.add("knowledge_documents", tenant_id=A, name="Old.pdf", file_type="application/pdf",
                          storage_path=None),
    }
    return {"rows": rows, "started": started, "collection": run(store.create_collection(A, "Astrology books"))}


def test_list_sales_documents_shows_only_this_business_and_only_stored_files(db, sales):
    listed = run(ingest.list_sales_documents(A))
    assert [(d["name"], d["file_type"]) for d in listed] == [("Clip.mp4", ""), ("Remedies.pdf", "pdf")]
    assert set(listed[0]) == {"id", "name", "file_type", "created_at"}
    assert [d["name"] for d in run(ingest.list_sales_documents(B))] == ["Secret.pdf"]


def test_copy_from_sales_copies_the_file_and_starts_reading(db, sales, world):
    before = copy.deepcopy(db.rows("knowledge_documents"))
    doc = run(ingest.copy_from_sales(A, sales["rows"]["mine"]["id"], sales["collection"]["id"], 1))
    assert (doc["title"], doc["file_type"], doc["tier"], doc["source"], doc["status"]) == (
        "Remedies", "pdf", 1, "sales_copy", "processing")
    assert doc["source_document_id"] == sales["rows"]["mine"]["id"]
    assert doc["storage_path"] == store.storage_path(A, doc["id"], "pdf")
    assert db.storage.files[(store.BUCKET, doc["storage_path"])] == db.storage.files[
        ("knowledge-documents", f"{A}/u1_Remedies.pdf")]              # copied, and the Sales file is still there
    assert db.rows("knowledge_documents") == before                    # the Sales row is untouched
    assert sales["started"] == [(A, doc["id"])]
    assert run(ingest.run_document(A, doc["id"])) == "ready"


def test_copy_from_sales_refuses_another_business_and_unreadable_types(db, sales):
    collection, rows = sales["collection"]["id"], sales["rows"]
    with pytest.raises(LookupError):
        run(ingest.copy_from_sales(A, rows["theirs"]["id"], collection, 2))
    with pytest.raises(LookupError):
        run(ingest.copy_from_sales(A, rows["no_file"]["id"], collection, 2))
    with pytest.raises(LookupError):
        run(ingest.copy_from_sales(A, "no-such-id", collection, 2))
    with pytest.raises(filetypes.UnsupportedFileType):
        run(ingest.copy_from_sales(A, rows["video"]["id"], collection, 2))
    with pytest.raises(store.CollectionNotFound):                      # B's document into A's collection
        run(ingest.copy_from_sales(B, rows["theirs"]["id"], collection, 2))
    assert db.rows("companion_kb_documents") == [] and sales["started"] == []
    assert not [key for key in db.storage.files if key[0] == store.BUCKET]


def test_copy_from_sales_never_reads_a_path_outside_the_business_folder(db, sales):
    row = next(r for r in db.rows("knowledge_documents") if r["id"] == sales["rows"]["mine"]["id"])
    row["storage_path"] = f"{B}/u2_Secret.pdf"                         # a tampered row
    with pytest.raises(LookupError):
        run(ingest.copy_from_sales(A, sales["rows"]["mine"]["id"], sales["collection"]["id"], 2))


# --- owner answers ------------------------------------------------------------------------------------

def test_two_owner_answers_are_both_kept_in_one_main_resource_book(db, world):
    collection = run(store.create_collection(A, "Astrology books"))
    first = run(ingest.add_owner_answer(A, collection["id"], "Saturn return age", "It comes at about 29 years."))
    second = run(ingest.add_owner_answer(A, collection["id"], "Rahu remedy", "Offer durva grass on Wednesday."))
    documents = db.rows("companion_kb_documents")
    assert len(documents) == 1
    assert (documents[0]["title"], documents[0]["tier"], documents[0]["source"], documents[0]["status"]) == (
        "Owner answers", 1, "owner_answers", "ready")
    chunks = run(store.list_chunks(A, documents[0]["id"]))
    assert [(c["seq"], c["heading_path"], c["text"]) for c in chunks] == [
        (0, "Saturn return age", "It comes at about 29 years."),
        (1, "Rahu remedy", "Offer durva grass on Wednesday.")]
    assert [first["id"], second["id"]] == [c["id"] for c in chunks]
    assert all(c["embedding"] and c["signposts_at"] for c in db.rows("companion_kb_chunks"))
    assert len(db.rows("companion_kb_chunk_questions")) == 6
    assert run(ingest.run_pending())["waiting"] == 0                   # the reading job has nothing to do with it


def test_owner_answer_is_saved_when_the_ai_is_down_and_checks_the_business(db, world):
    world.embed_ok, world.llm_ok = False, False
    collection = run(store.create_collection(A, "Astrology books"))
    saved = run(ingest.add_owner_answer(A, collection["id"], "Topic", "Answer"))
    assert saved["text"] == "Answer" and db.rows("companion_kb_chunk_questions") == []
    with pytest.raises(store.CollectionNotFound):
        run(ingest.add_owner_answer(B, collection["id"], "Topic", "Answer"))
    with pytest.raises(ValueError):
        run(ingest.add_owner_answer(A, collection["id"], "Topic", "   "))
    assert len(db.rows("companion_kb_chunks")) == 1


# --- the store functions added for ingest -------------------------------------------------------------

def test_added_store_functions_keep_the_business_filter(db, world):
    doc = add_book(make_pdf([P1]), tier=1)
    assert run(store.add_chunk(B, doc["id"], heading_path="x", text="y")) is None
    assert run(store.find_document_by_source(B, doc["collection_id"], "upload")) is None
    assert run(store.find_document_by_source(A, doc["collection_id"], "upload"))["id"] == doc["id"]
    assert run(store.documents_with_unfinished_chunks()) == []
    added = run(store.add_chunk(A, doc["id"], heading_path="h", text="t", page_from=2, page_to=3))
    assert (added["seq"], added["tier"], added["collection_id"]) == (0, 1, doc["collection_id"])
    assert "embedding" not in added
    assert run(store.documents_with_unfinished_chunks()) == [{"tenant_id": A, "document_id": doc["id"]}]


# --- the command-line tool ----------------------------------------------------------------------------

def test_cli_dry_run_prints_each_page_and_needs_no_database(monkeypatch, tmp_path, capsys):
    from app.companion.kb import ingest_cli

    def no_database(*args, **kwargs):
        raise AssertionError("a dry run must not touch the database")

    monkeypatch.setattr(store, "get_supabase", no_database)
    monkeypatch.setattr(ingest, "get_supabase", no_database)
    monkeypatch.setattr(ocr, "require_tenant_setting", no_database)   # the key lookup fails: no key
    path = tmp_path / "Book 7.pdf"
    path.write_bytes(make_pdf([P1, None, P3]))
    assert ingest_cli.main([A, str(path), "--dry-run", "--pages", "1-2"]) == 0
    printed = capsys.readouterr().out
    assert "3 page(s), reading 2" in printed and "nothing is saved" in printed
    assert "page    1  text_layer" in printed and f"{len(P1):>6} chars" in printed
    assert "page    2  not read (ocr)" in printed and ocr.NO_KEY_ERROR in printed
    assert "page    3" not in printed and "text layer 1, OCR 0, not read 1" in printed
    assert "Gemini key" in printed.splitlines()[-1]


def test_cli_refuses_bad_input_plainly(tmp_path, capsys):
    from app.companion.kb import ingest_cli
    video, book = tmp_path / "clip.mp4", tmp_path / "book.txt"
    video.write_bytes(b"x")
    book.write_text(P1)
    assert ingest_cli.main([A, str(tmp_path / "missing.pdf"), "--dry-run"]) == 2
    assert ingest_cli.main([A, str(video), "--dry-run"]) == 2
    assert ingest_cli.main([A, str(book)]) == 2                        # no --collection, no --dry-run
    assert ingest_cli.main([A, str(book), "--dry-run", "--pages", "abc"]) == 2
    printed = capsys.readouterr().out
    assert "File not found" in printed and "Video files are not supported yet." in printed
    assert "--collection NAME" in printed and "--pages must look like" in printed
    assert ingest_cli.parse_pages("1-3, 7,99", 8) == [1, 2, 3, 7]


def test_cli_real_run_saves_the_book(db, world, tmp_path, capsys):
    from app.companion.kb import ingest_cli
    path = tmp_path / "Book 7.pdf"
    path.write_bytes(make_pdf([P1, None, P3]))
    assert ingest_cli.main([A, str(path), "--collection", "Astrology books", "--tier", "1"]) == 0
    document = db.rows("companion_kb_documents")[0]
    assert (document["title"], document["tier"], document["status"], document["tenant_id"]) == ("Book 7", 1, "ready", A)
    assert (store.BUCKET, document["storage_path"]) in db.storage.files
    printed = capsys.readouterr().out
    assert "page    2  ok      ocr" in printed and "ready:" in printed


# --- hardening: a book that keeps crashing, huge files, stuck parsers ---------------------------------

async def _db_down(*args, **kwargs):
    raise RuntimeError("db down")


def test_a_book_that_crashes_three_passes_in_a_row_is_failed_not_retried_forever(db, world, monkeypatch):
    doc = add_book(make_pdf([P1]))
    monkeypatch.setattr(store, "pending_pages", _db_down)
    assert run(ingest.run_document(A, doc["id"])) == "processing"
    row = run(store.get_document(A, doc["id"]))
    assert row["crashed_passes"] == 1
    assert not ingest._claimed_elsewhere(row)          # the crashed pass let go: next minute retries
    assert run(ingest.run_document(A, doc["id"])) == "processing"
    assert run(ingest.run_document(A, doc["id"])) == "failed"
    row = run(store.get_document(A, doc["id"]))
    assert (row["status"], row["error"]) == ("failed", ingest.CRASHED_ERROR)
    assert doc["id"] not in ingest._released
    import os
    assert not os.path.exists(ingest._cache_path(doc))  # the local copy is gone too
    assert run(ingest.run_pending())["waiting"] == 0    # the every-minute job no longer sees it


def test_a_clean_pass_clears_the_crash_count(db, world, monkeypatch):
    doc = add_book(make_pdf([None] * 6))
    with monkeypatch.context() as patch:
        patch.setattr(store, "pending_pages", _db_down)
        assert run(ingest.run_document(A, doc["id"])) == "processing"
    assert run(store.get_document(A, doc["id"]))["crashed_passes"] == 1
    world.ocr_seconds = 30.0                             # out of time, but nothing went wrong
    assert run(ingest.run_document(A, doc["id"])) == "processing"
    assert run(store.get_document(A, doc["id"]))["crashed_passes"] == 0


async def _dropped(*args, **kwargs):
    raise httpx.RemoteProtocolError("Server disconnected")


def test_a_dropped_database_connection_is_not_counted_as_a_crash(db, world, monkeypatch):
    # 12 Nov 2026: 6 books uploaded at once, Supabase dropped the shared connection 15 times in 3 minutes,
    # and 5 books were failed "tried 3 times" although every page had been read.
    doc = add_book(make_pdf([P1]))
    with monkeypatch.context() as patch:
        patch.setattr(store, "pending_pages", _dropped)
        for _ in range(4):
            assert run(ingest.run_document(A, doc["id"])) == "processing"
    row = run(store.get_document(A, doc["id"]))
    assert (row["status"], row["crashed_passes"]) == ("processing", 0)
    assert not ingest._claimed_elsewhere(row)            # let go: the next minute carries on
    assert run(ingest.run_document(A, doc["id"])) == "ready"


def test_a_dropped_connection_while_saving_a_page_reads_it_again_instead_of_failing_it(db, world, monkeypatch):
    doc = add_book(make_pdf([P1, P2]))
    real, drops = store.save_page, []

    async def flaky(tenant_id, document_id, page_no, **fields):
        if page_no == 2 and fields.get("status") == "ok" and not drops:
            drops.append(page_no)
            raise httpx.RemoteProtocolError("Server disconnected")
        return await real(tenant_id, document_id, page_no, **fields)

    monkeypatch.setattr(store, "save_page", flaky)
    status = run(ingest.run_document(A, doc["id"]))
    if status == "processing":
        status = run(ingest.run_document(A, doc["id"]))
    assert drops == [2] and status == "ready"
    assert {n: p["status"] for n, p in pages_of(doc).items()} == {1: "ok", 2: "ok"}


def test_passage_vectors_are_saved_a_few_at_a_time(db, world, monkeypatch):
    # 50 saves at once per book, times 6 books, is what overloaded the shared connection.
    text = "\n\n".join(f"## Part {i}\n{P1} {P2} {P1}" for i in range(40))
    doc = add_book(text.encode(), "txt")
    real, now, peak = store.set_chunk_embedding, [0], [0]

    async def counted(*args, **kwargs):
        now[0] += 1
        peak[0] = max(peak[0], now[0])
        try:
            await asyncio.sleep(0)
            return await real(*args, **kwargs)
        finally:
            now[0] -= 1

    monkeypatch.setattr(store, "set_chunk_embedding", counted)
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    chunks = db.rows("companion_kb_chunks")
    assert len(chunks) > ingest.MAX_PARALLEL_SAVES and all(c.get("embedding") for c in chunks)
    assert 1 < peak[0] <= ingest.MAX_PARALLEL_SAVES


def test_a_book_whose_passes_died_three_times_is_failed_before_a_fourth_try(db, world):
    # The count is written BEFORE the risky work, so a pass that killed the whole server
    # (out of memory) is counted even though no error handler ever ran.
    doc = add_book(make_pdf([P1]))
    run(store.update_document(A, doc["id"], crashed_passes=3))
    assert run(ingest.run_document(A, doc["id"])) == "failed"
    assert run(store.get_document(A, doc["id"]))["error"] == ingest.CRASHED_ERROR
    assert db.rows("companion_kb_pages") == []           # the file was not opened again


def test_a_pdf_with_too_many_pages_fails_before_any_page_row_is_made(db, world, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_PDF_PAGES", 2)
    doc = add_book(make_pdf([P1, P2, P3]))
    assert run(ingest.run_document(A, doc["id"])) == "failed"
    assert run(store.get_document(A, doc["id"]))["error"] == (
        "This file has 3 pages. The limit is 2 pages per file. "
        "Split it into smaller files and upload them one by one.")
    assert db.rows("companion_kb_pages") == []


def test_a_text_file_with_too_much_text_fails_before_any_page_row_is_made(db, world, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_TEXT_PAGES", 2)
    doc = add_book(("line of text\n" * 700).encode(), "txt")      # 9,100 characters = 4 virtual pages
    assert run(ingest.run_document(A, doc["id"])) == "failed"
    assert run(store.get_document(A, doc["id"]))["error"] == (
        "This file has too much text to read as one book (about 12,000 characters; the limit is 6,000). "
        "Split it into smaller files and upload them one by one.")
    assert db.rows("companion_kb_pages") == []


def test_the_page_limits_are_far_above_a_real_book():
    assert (ingest.MAX_PDF_PAGES, ingest.MAX_TEXT_PAGES) == (2000, 3000)
    assert (ingest.PAGE_READ_SECONDS, ingest.FILE_READ_SECONDS) == (30, 120)


def _slow(seconds, result):
    import time

    def wait(*args, **kwargs):
        time.sleep(seconds)
        return result
    return wait


def test_a_file_whose_reader_hangs_fails_the_book_instead_of_holding_the_job(db, world, monkeypatch):
    monkeypatch.setattr(ingest, "FILE_READ_SECONDS", 0.05)
    monkeypatch.setattr(ingest.pages, "count_pages", _slow(0.4, 1))
    doc = add_book(make_pdf([P1]))
    assert run(ingest.run_document(A, doc["id"])) == "failed"
    assert run(store.get_document(A, doc["id"]))["error"] == ingest.SLOW_FILE_ERROR
    assert doc["id"] not in ingest._running
    monkeypatch.setattr(ingest, "_virtual_pages", _slow(0.4, ["text"]))
    text = add_book(b"hello", "txt", title="Notes")
    assert run(ingest.run_document(A, text["id"])) == "failed"
    assert run(store.get_document(A, text["id"]))["error"] == ingest.SLOW_FILE_ERROR


def test_a_page_whose_text_layer_hangs_goes_to_ocr(db, world, monkeypatch):
    monkeypatch.setattr(ingest, "PAGE_READ_SECONDS", 0.05)
    monkeypatch.setattr(ingest.pages, "read_page", _slow(0.3, (P1, set())))
    doc = add_book(make_pdf([P1]))
    assert run(ingest.run_document(A, doc["id"])) == "ready"
    assert pages_of(doc)[1]["method"] == "ocr" and world.ocr_calls == [1]


def test_three_hung_pages_in_one_pass_fail_the_book(db, world, monkeypatch):
    monkeypatch.setattr(ingest, "PAGE_READ_SECONDS", 0.05)
    monkeypatch.setattr(ingest.pages, "read_page", _slow(0.3, (P1, set())))
    doc = add_book(make_pdf([P1, P2, P3]))
    assert run(ingest.run_document(A, doc["id"])) == "failed"
    assert run(store.get_document(A, doc["id"]))["error"] == ingest.SLOW_FILE_ERROR


def test_an_ocr_call_that_never_returns_is_cut_off_and_counted_as_a_failed_try(db, world, monkeypatch):
    monkeypatch.setattr(ingest, "OCR_JOB_SECONDS", 0.05)

    async def stuck(tenant_id, path, page_no):
        await asyncio.sleep(5)

    monkeypatch.setattr(ingest.ocr, "ocr_pdf_page", stuck)
    doc = add_book(make_pdf([None]))
    assert run(ingest.run_document(A, doc["id"])) == "processing"
    page = pages_of(doc)[1]
    assert (page["status"], page["attempts"], page["error"]) == ("pending", 1, ingest.SLOW_PAGE_ERROR)


# --- hardening: Sales copies, the fill-in job, background passes --------------------------------------

def test_copy_from_sales_refuses_a_file_over_the_size_limit(db, sales, monkeypatch):
    monkeypatch.setattr(filetypes, "MAX_BYTES", 100)                   # the Sales PDF is a few hundred bytes
    with pytest.raises(ingest.SalesFileTooBig) as exc:
        run(ingest.copy_from_sales(A, sales["rows"]["mine"]["id"], sales["collection"]["id"], 2))
    assert exc.value.size_bytes == len(db.storage.files[("knowledge-documents", f"{A}/u1_Remedies.pdf")])
    assert not isinstance(exc.value, LookupError)
    assert db.rows("companion_kb_documents") == [] and sales["started"] == []
    assert not [key for key in db.storage.files if key[0] == store.BUCKET]


def test_copy_from_sales_refuses_the_same_document_twice_in_one_collection(db, sales):
    mine, shelf = sales["rows"]["mine"]["id"], sales["collection"]["id"]
    run(ingest.copy_from_sales(A, mine, shelf, 2))
    with pytest.raises(ingest.AlreadyCopied) as exc:
        run(ingest.copy_from_sales(A, mine, shelf, 2))
    assert not isinstance(exc.value, LookupError)
    assert str(exc.value) == '"Remedies.pdf" is already in this collection.'
    assert len(db.rows("companion_kb_documents")) == 1 and len(sales["started"]) == 1
    assert len([key for key in db.storage.files if key[0] == store.BUCKET]) == 1
    other = run(store.create_collection(A, "Second shelf"))            # another collection may have it too
    assert run(ingest.copy_from_sales(A, mine, other["id"], 2))["collection_id"] == other["id"]


def test_fill_in_is_not_starved_by_a_business_with_no_ai_key(db, world, monkeypatch):
    keyless = add_book(make_pdf([P1, P2, P3]), tenant=A)
    reachable = add_book(make_pdf([P1]), tenant=B)
    world.embed_ok = False                                             # both end ready, with no vectors
    assert run(ingest.run_document(A, keyless["id"])) == "ready"
    assert run(ingest.run_document(B, reachable["id"])) == "ready"
    world.embed_ok = True
    monkeypatch.setattr(ingest, "_has_key", lambda tenant_id: tenant_id == B)
    asked = []
    real = store.documents_with_unfinished_chunks

    async def spy(limit=20, exclude_tenants=()):
        asked.append(sorted(exclude_tenants))
        return await real(limit=limit, exclude_tenants=exclude_tenants)

    monkeypatch.setattr(store, "documents_with_unfinished_chunks", spy)
    # limit 1: tenant A's book fills the whole window on the first ask.
    assert run(ingest._fill_finished(1, world.clock + 30)) == 1
    assert asked == [[], [A]]
    assert all(c.get("embedding") for c in db.rows("companion_kb_chunks") if c["tenant_id"] == B)
    assert not any(c.get("embedding") for c in db.rows("companion_kb_chunks") if c["tenant_id"] == A)


def test_schedule_starts_at_most_two_background_passes(db, world, monkeypatch):
    docs = [add_book(make_pdf([P1]), title=title) for title in ("One", "Two", "Three")]

    async def go():
        for doc in docs:
            ingest.schedule(A, doc["id"])
        assert len(ingest._tasks) == ingest.MAX_BACKGROUND_PASSES == 2
        await asyncio.gather(*list(ingest._tasks))

    run(go())
    statuses = [run(store.get_document(A, doc["id"]))["status"] for doc in docs]
    assert statuses == ["ready", "ready", "processing"]
    # The third book was only just registered, but the every-minute job knows nobody is on it.
    waiting = run(store.get_document(A, docs[2]["id"]))
    assert not ingest._claimed_elsewhere(waiting)
    assert run(ingest.run_pending())["finished"] == 1
    assert docs[2]["id"] not in ingest._deferred
