"""kb-dashboard T19-T21 + T29: the /api/v1/companion-kb routes, against the fake database and storage.

The reading job (kb/ingest.py) is stubbed: these tests check what the routes ask it to do, not the
reading itself. Tenant t1 is the caller; t2 is another business whose ids must all answer 404.
"""
import logging
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.companion import store as companion_store
from app.companion.kb import filetypes, store as kb_store, store_search
from app.routes import companion_kb
from tests.fake_supabase import FakeStorage, FakeSupabase

BASE = "/api/v1/companion-kb"
SECRET_TITLE = "Brihat Parasara Hora"
SECRET_ANSWER = "Rahu in the fifth house delays children"
MB = 1024 * 1024


def _uid() -> str:
    return str(uuid4())


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupabase()
    fake.storage = FakeStorage()
    for module in (kb_store, store_search, companion_store):
        monkeypatch.setattr(module, "get_supabase", lambda: fake)

    companion_kb._retry_limiter.reset()
    calls = {"schedule": [], "answers": [], "copies": []}
    sales = [{"id": _uid(), "name": "Price list.pdf", "file_type": "pdf", "created_at": "2026-11-01T00:00:00Z",
              "tenant_id": "t1", "storage_path": "t1/secret/price.pdf"}]

    async def list_sales_documents(tenant_id):
        return sales if tenant_id == "t1" else []

    async def copy_from_sales(tenant_id, sales_document_id, collection_id, tier):
        calls["copies"].append((tenant_id, sales_document_id, collection_id, tier))
        if sales_document_id != sales[0]["id"]:
            raise LookupError("no such sales document")
        return await kb_store.create_document(tenant_id, collection_id, title="Price list", file_type="pdf",
                                              tier=tier, source="sales_copy", source_document_id=sales_document_id)

    async def add_owner_answer(tenant_id, collection_id, topic, answer):
        calls["answers"].append((tenant_id, collection_id, topic, answer))

    monkeypatch.setattr(companion_kb.ingest, "schedule", lambda t, d: calls["schedule"].append((t, d)),
                        raising=False)
    monkeypatch.setattr(companion_kb.ingest, "list_sales_documents", list_sales_documents, raising=False)
    monkeypatch.setattr(companion_kb.ingest, "copy_from_sales", copy_from_sales, raising=False)
    monkeypatch.setattr(companion_kb.ingest, "add_owner_answer", add_owner_answer, raising=False)

    app = FastAPI()
    app.include_router(companion_kb.router, prefix=BASE)
    app.dependency_overrides[companion_kb.require_companions_manage] = lambda: {
        "tenant_id": "t1", "user_id": "u1", "role": "owner"}

    def seed(tenant, name="Astrology books"):
        """A collection with one 3-page book (page 1 ok, 2 failed, 3 pending), 1 passage, a stored
        file, a character reading it, one shortcut and one open gap."""
        col = fake.add("companion_kb_collections", id=_uid(), tenant_id=tenant, name=name)
        doc_id = _uid()
        path = kb_store.storage_path(tenant, doc_id, "pdf")
        fake.storage.files[(kb_store.BUCKET, path)] = b"%PDF-book7"
        doc = fake.add("companion_kb_documents", id=doc_id, tenant_id=tenant, collection_id=col["id"],
                       title=SECRET_TITLE, file_type="pdf", size_bytes=10, tier=2, storage_path=path,
                       source="upload", status="ready_with_gaps", page_count=3, error=None)
        for no, status, text in ((1, "ok", "Saturn in the 7th house"), (2, "failed", None), (3, "pending", None)):
            fake.add("companion_kb_pages", id=_uid(), tenant_id=tenant, document_id=doc_id, page_no=no,
                     status=status, method="text_layer" if text else None, attempts=1, text=text,
                     char_count=len(text or ""), error="OCR timed out" if status == "failed" else None)
        fake.add("companion_kb_chunks", id=_uid(), tenant_id=tenant, document_id=doc_id, collection_id=col["id"],
                 tier=2, seq=0, heading_path="Chapter 1", text="Saturn delays marriage", page_from=1, page_to=1,
                 embedding="[0.1,0.2]", tsv="x")
        guru = fake.add("companions", id=_uid(), tenant_id=tenant, name="Guru", status="live",
                        knowledge_collection_id=col["id"])
        shortcut = fake.add("companion_kb_shortcuts", id=_uid(), tenant_id=tenant, companion_id=guru["id"],
                            topic="Saturn in the seventh house", document_id=doc_id,
                            pages=[{"page_from": 1, "page_to": 1}], uses=4, misses_in_row=0, status="active")
        gap = fake.add("companion_kb_gaps", id=_uid(), tenant_id=tenant, companion_id=guru["id"],
                       topic="Rahu in the fifth house", ask_count=6, last_asked_at="2026-11-10T00:00:00Z",
                       status="open")
        return type("Seed", (), dict(col=col, doc=doc, path=path, guru=guru, shortcut=shortcut, gap=gap))

    return type("Env", (), {"client": TestClient(app), "db": fake, "app": app, "calls": calls, "sales": sales,
                            "mine": seed("t1"), "theirs": seed("t2", "Their books")})


def _live(env, table: str, row: dict) -> dict:
    """The stored row (db.add hands back a copy)."""
    return next(r for r in env.db.rows(table) if r["id"] == row["id"])


def _no_private_fields(payload) -> None:
    text = str(payload)
    for word in ("tenant_id", "storage_path", "embedding", "tsv", "t1/"):
        assert word not in text, word


# --- collections --------------------------------------------------------------------------------------

def test_collections_create_list_rename_delete(env):
    c = env.client
    made = c.post(f"{BASE}/collections", json={"name": "  Vastu  "})
    assert made.status_code == 201
    assert made.json() == {"id": made.json()["id"], "name": "Vastu", "book_count": 0, "page_count": 0,
                           "pages_ok": 0, "read_by": [], "created_at": made.json()["created_at"],
                           "updated_at": made.json().get("updated_at")}
    assert c.post(f"{BASE}/collections", json={"name": "Vastu"}).status_code == 409

    listed = c.get(f"{BASE}/collections").json()
    assert [x["name"] for x in listed] == ["Astrology books", "Vastu"]        # never "Their books"
    assert listed[0]["book_count"] == 1 and listed[0]["page_count"] == 3 and listed[0]["pages_ok"] == 1
    assert listed[0]["read_by"] == [{"id": env.mine.guru["id"], "name": "Guru"}]
    _no_private_fields(listed)

    cid = made.json()["id"]
    renamed = c.patch(f"{BASE}/collections/{cid}", json={"name": "Vastu books"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Vastu books"
    assert c.patch(f"{BASE}/collections/{cid}", json={"name": "Astrology books"}).status_code == 409
    assert c.delete(f"{BASE}/collections/{cid}").status_code == 204
    assert c.delete(f"{BASE}/collections/{cid}").status_code == 404


def test_a_collection_with_books_is_not_deleted(env):
    r = env.client.delete(f"{BASE}/collections/{env.mine.col['id']}")
    assert r.status_code == 409
    assert r.json()["detail"] == '"Astrology books" still has 1 book. Delete them first.'
    assert len(env.db.rows("companion_kb_collections")) == 2


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "   "}, {"name": "x" * 81}, {},
                                  {"name": "X", "tenant_id": "t2"}])
def test_collection_input_is_validated(env, body):
    assert env.client.post(f"{BASE}/collections", json=body).status_code == 422
    assert env.client.patch(f"{BASE}/collections/{env.mine.col['id']}", json=body).status_code == 422


# --- another business's ids ---------------------------------------------------------------------------

def _foreign_requests(seed, sales_id):
    col, doc, shortcut, gap = seed.col["id"], seed.doc["id"], seed.shortcut["id"], seed.gap["id"]
    mine = None
    return [
        ("patch", f"/collections/{col}", {"name": "Mine now"}),
        ("delete", f"/collections/{col}", mine),
        ("get", f"/documents?collection_id={col}", mine),
        ("get", f"/documents/{doc}", mine),
        ("get", f"/documents/{doc}/pages", mine),
        ("get", f"/documents/{doc}/pages/1", mine),
        ("get", f"/documents/{doc}/passages", mine),
        ("post", "/documents", {"draft_id": _uid(), "collection_id": col, "tier": 2}),
        ("patch", f"/documents/{doc}", {"tier": 1, "title": "Mine now"}),
        ("delete", f"/documents/{doc}", mine),
        ("post", f"/documents/{doc}/retry", mine),
        ("post", "/documents/from-sales", {"sales_document_id": sales_id, "collection_id": col, "tier": 2}),
        ("get", f"/collections/{col}/shortcuts", mine),
        ("delete", f"/shortcuts/{shortcut}", mine),
        ("get", f"/collections/{col}/gaps", mine),
        ("post", f"/gaps/{gap}/answer", {"answer": "Mine now"}),
        ("post", f"/gaps/{gap}/dismiss", mine),
    ]


def test_another_business_ids_are_404_and_nothing_changes(env):
    import copy
    before = copy.deepcopy(env.db.tables)
    files = dict(env.db.storage.files)
    for method, path, body in _foreign_requests(env.theirs, env.sales[0]["id"]):
        r = env.client.request(method, BASE + path, json=body)
        assert r.status_code == 404, (method, path, r.status_code)
        _no_private_fields(r.text)
    assert env.db.tables == before and env.db.storage.files == files
    assert env.calls == {"schedule": [], "answers": [], "copies": []}


def test_an_id_that_does_not_exist_answers_the_same_as_another_business(env):
    ghost = type("Seed", (), dict(col={"id": _uid()}, doc={"id": _uid()}, shortcut={"id": _uid()},
                                  gap={"id": _uid()}))
    theirs = _foreign_requests(env.theirs, env.sales[0]["id"])
    for (method, path, body), (_, their_path, their_body) in zip(_foreign_requests(ghost, env.sales[0]["id"]), theirs):
        missing = env.client.request(method, BASE + path, json=body)
        foreign = env.client.request(method, BASE + their_path, json=their_body)
        assert (missing.status_code, missing.json()) == (foreign.status_code, foreign.json()), path


def test_ids_must_be_uuids(env):
    assert env.client.get(f"{BASE}/documents/not-a-uuid").status_code == 422
    assert env.client.delete(f"{BASE}/shortcuts/1 or 1=1").status_code == 422
    assert env.client.get(f"{BASE}/documents/{env.mine.doc['id']}/pages/0").status_code == 422


# --- limits and the upload ticket ---------------------------------------------------------------------

def test_limits(env):
    assert env.client.get(f"{BASE}/limits").json() == {
        "max_bytes": 50 * MB, "accepted_types": sorted(filetypes.ACCEPTED_TYPES)}


def test_upload_ticket_points_into_the_callers_own_folder_and_writes_nothing(env):
    documents = len(env.db.rows("companion_kb_documents"))
    r = env.client.post(f"{BASE}/uploads", json={"name": "Book 7.PDF", "size_bytes": 40 * MB})
    assert r.status_code == 200
    ticket = r.json()
    assert set(ticket) == {"draft_id", "upload_url", "token", "path", "file_type"}
    assert ticket["file_type"] == "pdf" and ticket["path"] == f"t1/{ticket['draft_id']}/original.pdf"
    assert ticket["upload_url"].startswith("https://") and ticket["path"] in ticket["upload_url"]
    assert len(env.db.rows("companion_kb_documents")) == documents


@pytest.mark.parametrize("name,size,status,says", [
    ("Book 7.pdf", 62 * MB, 413, "Book 7.pdf is 62 MB. The limit is 50 MB."),
    ("Book 7.pdf", 50 * MB + 1, 413, "Book 7.pdf is 50.1 MB. The limit is 50 MB."),
    ("clip.mp4", MB, 400, "Video files are not supported yet. We accept: .csv, .docx,"),
    ("notes.doc", MB, 400, "Save the file as .docx and upload it again."),
    ("run.exe", MB, 400, "This file type (.exe) is not supported."),
    ("noextension", MB, 400, "This file has no extension"),
])
def test_upload_refuses_wrong_type_and_too_large_with_a_plain_sentence(env, name, size, status, says):
    r = env.client.post(f"{BASE}/uploads", json={"name": name, "size_bytes": size})
    assert r.status_code == status and says in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"name": "a.pdf"}, {"size_bytes": 5}, {"name": "a.pdf", "size_bytes": 0}, {"name": "a.pdf", "size_bytes": -1},
    {"name": "a.pdf", "size_bytes": 5, "tenant_id": "t2"}, {"name": "a.pdf", "size_bytes": 5, "path": "t2/x/y.pdf"},
])
def test_upload_input_is_validated(env, body):
    assert env.client.post(f"{BASE}/uploads", json=body).status_code == 422


def test_exactly_the_limit_is_accepted(env):
    assert env.client.post(f"{BASE}/uploads", json={"name": "a.pdf", "size_bytes": 50 * MB}).status_code == 200


# --- registering a book -------------------------------------------------------------------------------

def _upload(env, data=b"%PDF-new-book", name="Book 9.pdf"):
    """What the browser does: ask for a ticket, then put the file at the ticket's path."""
    ticket = env.client.post(f"{BASE}/uploads", json={"name": name, "size_bytes": len(data)}).json()
    env.db.storage.files[(kb_store.BUCKET, ticket["path"])] = data
    return ticket


def test_register_makes_the_book_with_the_real_size_and_schedules_reading(env, caplog):
    caplog.set_level(logging.DEBUG)
    ticket = _upload(env)
    r = env.client.post(f"{BASE}/documents", json={"draft_id": ticket["draft_id"], "tier": 1,
                                                   "collection_id": env.mine.col["id"], "title": SECRET_TITLE})
    assert r.status_code == 201
    book = r.json()
    assert book["id"] == ticket["draft_id"] and book["status"] == "processing" and book["tier"] == 1
    assert book["title"] == SECRET_TITLE and book["file_type"] == "pdf" and book["source"] == "upload"
    assert book["size_bytes"] == len(b"%PDF-new-book") and book["collection_name"] == "Astrology books"
    assert (book["pages_ok"], book["pages_failed"], book["pages_pending"], book["failed_pages"]) == (0, 0, 0, [])
    _no_private_fields(book)
    row = next(d for d in env.db.rows("companion_kb_documents") if d["id"] == book["id"])
    assert row["tenant_id"] == "t1" and row["storage_path"] == ticket["path"]
    assert env.calls["schedule"] == [("t1", book["id"])]
    assert SECRET_TITLE not in caplog.text

    again = env.client.post(f"{BASE}/documents", json={"draft_id": ticket["draft_id"], "tier": 2,
                                                       "collection_id": env.mine.col["id"]})
    assert again.status_code == 409 and len(env.calls["schedule"]) == 1


def test_register_without_a_file_is_refused(env):
    r = env.client.post(f"{BASE}/documents", json={"draft_id": _uid(), "tier": 2,
                                                   "collection_id": env.mine.col["id"]})
    assert r.status_code == 400 and "did not arrive" in r.json()["detail"]
    assert env.calls["schedule"] == []


def test_register_cannot_claim_a_file_in_another_business_folder(env):
    draft = _uid()
    env.db.storage.files[(kb_store.BUCKET, f"t2/{draft}/original.pdf")] = b"theirs"
    r = env.client.post(f"{BASE}/documents", json={"draft_id": draft, "tier": 2,
                                                   "collection_id": env.mine.col["id"]})
    assert r.status_code == 400
    assert (kb_store.BUCKET, f"t2/{draft}/original.pdf") in env.db.storage.files


def test_register_checks_the_real_size_and_removes_a_file_that_is_too_big(env, monkeypatch):
    ticket = _upload(env, data=b"x" * 2048)          # the browser said 2 KB at ticket time...
    monkeypatch.setattr(companion_kb, "MAX_BYTES", 1024)   # ...but the limit is 1 KB
    documents = len(env.db.rows("companion_kb_documents"))
    r = env.client.post(f"{BASE}/documents", json={"draft_id": ticket["draft_id"], "tier": 2,
                                                   "collection_id": env.mine.col["id"]})
    assert r.status_code == 400 and "The limit is" in r.json()["detail"]
    assert (kb_store.BUCKET, ticket["path"]) not in env.db.storage.files
    assert len(env.db.rows("companion_kb_documents")) == documents and env.calls["schedule"] == []


@pytest.mark.parametrize("change", [
    {"draft_id": "../../t2/x"}, {"tier": 3}, {"tier": "1"}, {"title": "x" * 201}, {"tenant_id": "t2"},
    {"storage_path": "t2/x/original.pdf"}, {"path": "t2/x/original.pdf"}, {"collection_id": "nope"},
])
def test_register_input_is_validated(env, change):
    body = {"draft_id": _uid(), "tier": 2, "collection_id": env.mine.col["id"], **change}
    assert env.client.post(f"{BASE}/documents", json=body).status_code == 422


# --- reading books back -------------------------------------------------------------------------------

def test_documents_are_listed_newest_first_with_page_counts(env):
    second = _upload(env)
    env.client.post(f"{BASE}/documents", json={"draft_id": second["draft_id"], "tier": 2, "title": "Book 9",
                                               "collection_id": env.mine.col["id"]})
    listed = env.client.get(f"{BASE}/documents").json()
    assert [d["title"] for d in listed] == ["Book 9", SECRET_TITLE]      # none of t2's
    old = listed[1]
    assert (old["pages_ok"], old["pages_failed"], old["pages_pending"], old["failed_pages"]) == (1, 1, 1, [2])
    assert old["status"] == "ready_with_gaps" and old["collection_name"] == "Astrology books"
    _no_private_fields(listed)
    assert len(env.client.get(f"{BASE}/documents?limit=1").json()) == 1
    assert len(env.client.get(f"{BASE}/documents?collection_id={env.mine.col['id']}").json()) == 2
    assert env.client.get(f"{BASE}/documents?limit=0").status_code == 422
    assert env.client.get(f"{BASE}/documents?limit=201").status_code == 422
    one = env.client.get(f"{BASE}/documents/{env.mine.doc['id']}")
    assert one.status_code == 200 and one.json() == old


def test_pages_come_without_text_in_the_list_and_with_text_one_by_one(env):
    doc = env.mine.doc["id"]
    pages = env.client.get(f"{BASE}/documents/{doc}/pages").json()
    assert [(p["page_no"], p["status"]) for p in pages] == [(1, "ok"), (2, "failed"), (3, "pending")]
    assert all("text" not in p for p in pages) and pages[1]["error"] == "OCR timed out"
    assert set(pages[0]) == {"page_no", "status", "method", "attempts", "char_count", "error", "updated_at"}
    one = env.client.get(f"{BASE}/documents/{doc}/pages/1").json()
    assert one["text"] == "Saturn in the 7th house" and one["method"] == "text_layer"
    assert env.client.get(f"{BASE}/documents/{doc}/pages/9").status_code == 404


def test_passages_carry_no_embedding(env):
    passages = env.client.get(f"{BASE}/documents/{env.mine.doc['id']}/passages").json()
    assert passages == [{"id": passages[0]["id"], "seq": 0, "heading_path": "Chapter 1",
                         "text": "Saturn delays marriage", "page_from": 1, "page_to": 1, "tier": 2}]


# --- changing, retrying, deleting ---------------------------------------------------------------------

def test_patch_changes_title_and_tier_and_rereads_only_on_a_tier_change(env):
    doc = env.mine.doc["id"]
    r = env.client.patch(f"{BASE}/documents/{doc}", json={"title": "  Book 7  "})
    assert r.status_code == 200 and r.json()["title"] == "Book 7" and env.calls["schedule"] == []
    assert env.client.patch(f"{BASE}/documents/{doc}", json={"tier": 2}).status_code == 200   # already 2
    assert env.calls["schedule"] == []
    r = env.client.patch(f"{BASE}/documents/{doc}", json={"tier": 1})
    assert r.json()["tier"] == 1 and env.calls["schedule"] == [("t1", doc)]
    assert {c["tier"] for c in env.db.rows("companion_kb_chunks") if c["document_id"] == doc} == {1}


@pytest.mark.parametrize("body", [{}, {"tier": 3}, {"title": ""}, {"title": "x" * 201}, {"status": "ready"},
                                  {"collection_id": "c"}, {"tenant_id": "t2"}, {"storage_path": "t2/a/b.pdf"}])
def test_patch_input_is_validated(env, body):
    assert env.client.patch(f"{BASE}/documents/{env.mine.doc['id']}", json=body).status_code == 422


def test_retry_requeues_only_the_failed_pages(env):
    doc = env.mine.doc["id"]
    r = env.client.post(f"{BASE}/documents/{doc}/retry")
    assert r.status_code == 200 and r.json() == {"requeued": 1}
    pages = {p["page_no"]: p for p in env.db.rows("companion_kb_pages") if p["document_id"] == doc}
    assert pages[2]["status"] == "pending" and pages[2]["attempts"] == 0
    assert pages[1]["status"] == "ok" and pages[1]["text"] == "Saturn in the 7th house" and pages[1]["attempts"] == 1
    assert env.client.get(f"{BASE}/documents/{doc}").json()["status"] == "processing"
    assert env.calls["schedule"] == [("t1", doc)]
    assert env.client.post(f"{BASE}/documents/{doc}/retry").json() == {"requeued": 0}    # nothing left
    assert len(env.calls["schedule"]) == 1


def test_retry_restarts_a_book_that_failed_before_any_page(env):
    doc = env.db.add("companion_kb_documents", id=_uid(), tenant_id="t1", collection_id=env.mine.col["id"],
                     title="Broken", file_type="pdf", tier=2, status="failed", error="Could not open the file",
                     page_count=0, source="upload")
    assert env.client.post(f"{BASE}/documents/{doc['id']}/retry").json() == {"requeued": 0}
    doc = _live(env, "companion_kb_documents", doc)
    assert (doc["status"], doc["error"]) == ("processing", None)
    assert env.calls["schedule"] == [("t1", doc["id"])]


def test_delete_removes_the_book_and_its_file(env):
    doc = env.mine.doc["id"]
    assert env.client.delete(f"{BASE}/documents/{doc}").status_code == 204
    assert [d["tenant_id"] for d in env.db.rows("companion_kb_documents")] == ["t2"]
    assert (kb_store.BUCKET, env.mine.path) not in env.db.storage.files
    assert (kb_store.BUCKET, env.theirs.path) in env.db.storage.files
    assert env.client.delete(f"{BASE}/documents/{doc}").status_code == 404


# --- Anril Sales documents ----------------------------------------------------------------------------

def test_sales_documents_are_listed_without_private_fields(env):
    assert env.client.get(f"{BASE}/sales-documents").json() == [
        {"id": env.sales[0]["id"], "name": "Price list.pdf", "file_type": "pdf",
         "created_at": "2026-11-01T00:00:00Z"}]


def test_copy_from_sales(env, monkeypatch):
    body = {"sales_document_id": env.sales[0]["id"], "collection_id": env.mine.col["id"], "tier": 2}
    r = env.client.post(f"{BASE}/documents/from-sales", json=body)
    assert r.status_code == 201 and r.json()["source"] == "sales_copy" and r.json()["status"] == "processing"
    assert env.calls["copies"] == [("t1", env.sales[0]["id"], env.mine.col["id"], 2)]
    _no_private_fields(r.json())

    missing = env.client.post(f"{BASE}/documents/from-sales", json={**body, "sales_document_id": _uid()})
    assert missing.status_code == 404 and "Anril Sales" in missing.json()["detail"]

    async def old_word(*a):
        raise filetypes.UnsupportedFileType("Old Word files (.doc) are not supported.")
    monkeypatch.setattr(companion_kb.ingest, "copy_from_sales", old_word)
    refused = env.client.post(f"{BASE}/documents/from-sales", json=body)
    assert refused.status_code == 400 and refused.json()["detail"] == "Old Word files (.doc) are not supported."
    assert env.client.post(f"{BASE}/documents/from-sales", json={**body, "tenant_id": "t2"}).status_code == 422


# --- shortcuts and gaps -------------------------------------------------------------------------------

def test_shortcuts_are_listed_and_removed_by_marking_not_deleting(env):
    s = env.mine.shortcut
    listed = env.client.get(f"{BASE}/collections/{env.mine.col['id']}/shortcuts").json()
    assert listed == [{"id": s["id"], "topic": "Saturn in the seventh house", "document_id": env.mine.doc["id"],
                       "document_title": SECRET_TITLE, "pages": [{"page_from": 1, "page_to": 1}], "uses": 4,
                       "companion_id": env.mine.guru["id"], "companion_name": "Guru",
                       "created_at": listed[0]["created_at"]}]
    assert env.client.delete(f"{BASE}/shortcuts/{s['id']}").status_code == 204
    assert _live(env, "companion_kb_shortcuts", s)["status"] == "removed_by_owner"      # kept, not deleted
    assert env.client.get(f"{BASE}/collections/{env.mine.col['id']}/shortcuts").json() == []
    assert _live(env, "companion_kb_shortcuts", env.theirs.shortcut)["status"] == "active"


def test_gap_is_answered_into_the_characters_collection(env, caplog):
    caplog.set_level(logging.DEBUG)
    gap = env.mine.gap
    listed = env.client.get(f"{BASE}/collections/{env.mine.col['id']}/gaps").json()
    assert listed == [{"id": gap["id"], "topic": "Rahu in the fifth house", "ask_count": 6,
                       "last_asked_at": "2026-11-10T00:00:00Z", "companion_id": env.mine.guru["id"],
                       "companion_name": "Guru"}]
    r = env.client.post(f"{BASE}/gaps/{gap['id']}/answer", json={"answer": f"  {SECRET_ANSWER}  "})
    assert r.status_code == 204
    assert env.calls["answers"] == [("t1", env.mine.col["id"], "Rahu in the fifth house", SECRET_ANSWER)]
    assert _live(env, "companion_kb_gaps", gap)["status"] == "covered"
    assert _live(env, "companion_kb_gaps", env.theirs.gap)["status"] == "open"
    assert SECRET_ANSWER not in caplog.text and "Rahu" not in caplog.text
    assert env.client.post(f"{BASE}/gaps/{gap['id']}/answer", json={"answer": "again"}).status_code == 409
    assert len(env.calls["answers"]) == 1
    assert env.client.get(f"{BASE}/collections/{env.mine.col['id']}/gaps").json() == []


def test_gap_of_a_character_with_no_collection_is_409_and_saves_nothing(env):
    _live(env, "companions", env.mine.guru)["knowledge_collection_id"] = None
    r = env.client.post(f"{BASE}/gaps/{env.mine.gap['id']}/answer", json={"answer": SECRET_ANSWER})
    assert r.status_code == 409 and "no longer reads a collection" in r.json()["detail"]
    assert env.calls["answers"] == [] and _live(env, "companion_kb_gaps", env.mine.gap)["status"] == "open"


def test_gap_answer_never_lands_in_another_business_collection(env):
    _live(env, "companions", env.mine.guru)["knowledge_collection_id"] = env.theirs.col["id"]   # a corrupted pointer
    r = env.client.post(f"{BASE}/gaps/{env.mine.gap['id']}/answer", json={"answer": SECRET_ANSWER})
    assert r.status_code == 409 and env.calls["answers"] == []


def test_gap_dismiss(env):
    gap = env.mine.gap
    assert env.client.post(f"{BASE}/gaps/{gap['id']}/dismiss").status_code == 204
    assert _live(env, "companion_kb_gaps", gap)["status"] == "dismissed" and env.calls["answers"] == []
    assert env.client.post(f"{BASE}/gaps/{gap['id']}/answer", json={"answer": "late"}).status_code == 409


@pytest.mark.parametrize("body", [{}, {"answer": ""}, {"answer": "   "}, {"answer": "x" * 4001},
                                  {"answer": "ok", "collection_id": "c"}, {"answer": "ok", "tenant_id": "t2"}])
def test_gap_answer_input_is_validated(env, body):
    assert env.client.post(f"{BASE}/gaps/{env.mine.gap['id']}/answer", json=body).status_code == 422
    assert env.calls["answers"] == []


# --- who may call -------------------------------------------------------------------------------------

def test_every_route_needs_companions_manage(env):
    from app.dependencies.tenant import get_tenant_and_role
    app = FastAPI()
    app.include_router(companion_kb.router, prefix=BASE)
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": "t1", "role": "agent", "permissions": []}
    client = TestClient(app)
    paths = [("get", "/collections"), ("get", "/limits"), ("get", "/sales-documents"), ("get", "/documents")]
    paths += [(m, p) for m, p, _ in _foreign_requests(env.mine, env.sales[0]["id"])]
    paths += [("post", "/uploads"), ("post", "/collections")]
    assert len({(m, p.split("?")[0]) for m, p in paths}) == len(companion_kb.router.routes)   # every route
    for method, path in paths:
        assert client.request(method, BASE + path, json={}).status_code == 403, (method, path)
    assert env.calls == {"schedule": [], "answers": [], "copies": []}


def test_router_is_mounted_in_the_app():
    from app.main import app
    # Without a login the real app answers 401/403 (auth runs), never 404 (route missing).
    assert TestClient(app).get(f"{BASE}/collections").status_code in (401, 403)
    assert TestClient(app).post(f"{BASE}/uploads", json={"name": "a.pdf", "size_bytes": 1}).status_code in (401, 403)


# --- hardening ----------------------------------------------------------------------------------------

def test_the_size_limit_is_the_one_in_filetypes(env):
    assert companion_kb.MAX_BYTES is filetypes.MAX_BYTES
    assert env.client.get(f"{BASE}/limits").json()["max_bytes"] == filetypes.MAX_BYTES


def test_copy_from_sales_says_too_big_and_already_added_in_plain_words(env, monkeypatch):
    body = {"sales_document_id": env.sales[0]["id"], "collection_id": env.mine.col["id"], "tier": 2}

    async def too_big(*a):
        raise companion_kb.ingest.SalesFileTooBig(65011712)
    monkeypatch.setattr(companion_kb.ingest, "copy_from_sales", too_big)
    r = env.client.post(f"{BASE}/documents/from-sales", json=body)
    assert r.status_code == 413 and r.json()["detail"] == "This file is 62 MB. The limit is 50 MB."

    async def twice(*a):
        raise companion_kb.ingest.AlreadyCopied('"Price list.pdf" is already in this collection.')
    monkeypatch.setattr(companion_kb.ingest, "copy_from_sales", twice)
    r = env.client.post(f"{BASE}/documents/from-sales", json=body)
    assert r.status_code == 409 and r.json()["detail"] == '"Price list.pdf" is already in this collection.'


def test_a_draft_registered_twice_at_the_same_moment_is_409(env, monkeypatch):
    ticket = _upload(env)

    async def clash(*a, **k):
        raise kb_store.DocumentExists("This file is already added")
    monkeypatch.setattr(kb_store, "create_document", clash)
    r = env.client.post(f"{BASE}/documents", json={"draft_id": ticket["draft_id"], "tier": 2,
                                                   "collection_id": env.mine.col["id"]})
    assert r.status_code == 409 and r.json()["detail"] == "This file is already added"
    assert env.calls["schedule"] == []


def test_a_book_can_be_retried_three_times_a_day(env):
    doc = env.db.add("companion_kb_documents", id=_uid(), tenant_id="t1", collection_id=env.mine.col["id"],
                     title="Broken", file_type="pdf", tier=2, status="failed", error="x", page_count=0,
                     source="upload", crashed_passes=3)
    for _ in range(3):
        _live(env, "companion_kb_documents", doc)["status"] = "failed"
        assert env.client.post(f"{BASE}/documents/{doc['id']}/retry").status_code == 200
    assert _live(env, "companion_kb_documents", doc)["crashed_passes"] == 0     # Retry starts the count again
    _live(env, "companion_kb_documents", doc)["status"] = "failed"
    r = env.client.post(f"{BASE}/documents/{doc['id']}/retry")
    assert r.status_code == 429 and r.json()["detail"] == companion_kb._RETRY_LIMIT_SENTENCE
    assert _live(env, "companion_kb_documents", doc)["status"] == "failed" and len(env.calls["schedule"]) == 3
    # The limit is per book, and another business's id is still a 404, not a 429.
    assert env.client.post(f"{BASE}/documents/{env.mine.doc['id']}/retry").status_code == 200
    for _ in range(4):
        assert env.client.post(f"{BASE}/documents/{env.theirs.doc['id']}/retry").status_code == 404
