"""match_companion_kb_chunks (migration 258) against a REAL Postgres. The fake database cannot check
SQL, Tamil word matching or trigram spelling variants, so this is the only test that can.

Skipped unless COMPANION_KB_TEST_DATABASE_URL is set to a database that already has migrations 257
and 258 (a Supabase branch or a local stack, never production). Everything is inserted inside one
transaction that is rolled back, so the database is left as it was.

    COMPANION_KB_TEST_DATABASE_URL=postgresql://... .venv/bin/python -m pytest tests/test_companion_kb_search_pg.py
"""
import os
import uuid

import pytest

URL = os.environ.get("COMPANION_KB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="COMPANION_KB_TEST_DATABASE_URL is not set")

DIM = 768
TAMIL = "ஏழாம் வீட்டில் சனி இருந்தால் திருமணம் தாமதமாகும்"
ENGLISH = "When sani sits in the seventh house the wedding comes late"


def vector(first: float, second: float = 0.0) -> str:
    return "[" + ",".join(str(x) for x in [first, second] + [0.0] * (DIM - 2)) + "]"


@pytest.fixture
def pg():
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(URL)
    try:
        cur = conn.cursor()
        cur.execute("SELECT to_regprocedure('match_companion_kb_chunks(uuid, uuid, integer, text, vector, vector, "
                    "text, text, text[], integer)')")
        if cur.fetchone()[0] is None:
            pytest.skip("migrations 257 and 258 are not applied in this database")
        ids = {k: str(uuid.uuid4()) for k in ("tenant", "other", "collection", "main", "book", "ta", "en", "b1")}
        for key in ("tenant", "other"):
            cur.execute("INSERT INTO tenants (id, name) VALUES (%s, %s)", (ids[key], f"kb-pg-test-{key}"))
        cur.execute("INSERT INTO companion_kb_collections (id, tenant_id, name) VALUES (%s, %s, 'Astrology books')",
                    (ids["collection"], ids["tenant"]))
        for key, title, tier in (("main", "Main resource", 1), ("book", "Book 3", 2)):
            cur.execute("INSERT INTO companion_kb_documents (id, tenant_id, collection_id, title, file_type, tier) "
                        "VALUES (%s, %s, %s, %s, 'pdf', %s)", (ids[key], ids["tenant"], ids["collection"], title, tier))
        chunks = (("ta", "main", 1, TAMIL, 12, vector(1.0)), ("en", "main", 1, ENGLISH, 13, vector(0.0, 1.0)),
                  ("b1", "book", 2, "Sade Sati lasts seven and a half years", 88, None))
        for key, doc, tier, text, page, emb in chunks:
            cur.execute(
                "INSERT INTO companion_kb_chunks (id, tenant_id, document_id, collection_id, tier, text, page_from, "
                "page_to, embedding, embedding_model) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)",
                (ids[key], ids["tenant"], ids[doc], ids["collection"], tier, text, page, page, emb,
                 "gemini" if emb else None))
        yield cur, ids
    finally:
        conn.rollback()
        conn.close()


def match(cur, tenant, collection, *, tier=1, en=None, ta=None, query_en="", query_ta="", terms=(), count=8):
    cur.execute("SELECT id::text, document_title, source, score FROM match_companion_kb_chunks("
                "%s, %s, %s, 'gemini', %s::vector, %s::vector, %s, %s, %s::text[], %s)",
                (tenant, collection, tier, en, ta, query_en, query_ta, list(terms), count))
    return cur.fetchall()


def test_a_tamil_script_query_finds_the_tamil_passage_by_words(pg):
    cur, ids = pg
    rows = match(cur, ids["tenant"], ids["collection"], query_ta="சனி திருமணம்")
    assert (ids["ta"], "Main resource", "words") in [(r[0], r[1], r[2]) for r in rows]
    assert ids["en"] not in [r[0] for r in rows]


def test_a_transliterated_term_finds_the_passage_by_trigram(pg):
    cur, ids = pg
    rows = match(cur, ids["tenant"], ids["collection"], terms=["shani"])        # the book spells it "sani"
    assert [(r[0], r[2]) for r in rows] == [(ids["en"], "trigram")] and rows[0][3] >= 0.3


def test_meaning_search_ranks_the_closest_passage_first(pg):
    cur, ids = pg
    rows = [r for r in match(cur, ids["tenant"], ids["collection"], en=vector(1.0)) if r[2] == "vector_en"]
    assert rows and max(rows, key=lambda r: r[3])[0] == ids["ta"]
    assert max(r[3] for r in rows) == pytest.approx(1.0)


def test_another_tenant_gets_no_rows_and_tiers_do_not_mix(pg):
    cur, ids = pg
    everything = dict(en=vector(1.0), ta=vector(1.0), query_en="sani seventh house Sade Sati",
                      query_ta="சனி திருமணம்", terms=["shani", "sade sati"])
    assert match(cur, ids["other"], ids["collection"], **everything) == []
    assert match(cur, ids["other"], ids["collection"], tier=2, **everything) == []
    assert {r[0] for r in match(cur, ids["tenant"], ids["collection"], tier=2, **everything)} == {ids["b1"]}
    assert ids["b1"] not in {r[0] for r in match(cur, ids["tenant"], ids["collection"], tier=1, **everything)}
