"""Companion memory against a REAL Postgres: tenant links, one live fact per slot, the alert kinds, and
the three SQL functions the reply path and the nightly job depend on (match_memory_chunks,
claim_memory_pair, companion_day_context). The fake database has no foreign keys, no unique indexes and
no SQL functions, so these are the only tests that can check them.

Skipped unless COMPANION_MEMORY_TEST_DATABASE_URL is set. Two kinds of database work:
- an EMPTY throwaway Postgres (GitHub CI starts one with pgvector): tests/pg_schema.py builds the schema
  from the real migration files 248-263 on the first test;
- a database that already has the migrations (a Supabase branch). Never production.
Every test inserts inside one transaction that is rolled back, so the rows never stay.

    COMPANION_MEMORY_TEST_DATABASE_URL=postgresql://... .venv/bin/python -m pytest tests/test_companion_memory_pg.py

Two businesses: AstroTamil (characters Guru and Jothi, people Priya and Kumar) and Vastu House
(character Vasu, person Ravi).
"""
import os
import uuid

import pytest

URL = os.environ.get("COMPANION_MEMORY_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="COMPANION_MEMORY_TEST_DATABASE_URL is not set")

SLOT_FN = "companion_set_slot_fact(uuid, uuid, uuid, text, text, text, date, date, text, uuid)"
# How to insert one row into each memory table: (sql, extra values after tenant, companion, person).
INSERTS = {
    "companion_memory_facts": ("INSERT INTO companion_memory_facts (tenant_id, companion_id, end_user_id, section, "
                               "text) VALUES (%s, %s, %s, 'profile', 'Lives in Chennai')"),
    "companion_memory_state": ("INSERT INTO companion_memory_state (tenant_id, companion_id, end_user_id) "
                               "VALUES (%s, %s, %s)"),
    "companion_memory_diary": ("INSERT INTO companion_memory_diary (tenant_id, companion_id, end_user_id, day, text) "
                               "VALUES (%s, %s, %s, '2026-11-10', 'Spoke about the Zoho interview.')"),
    "companion_memory_chunks": ("INSERT INTO companion_memory_chunks (tenant_id, companion_id, end_user_id, kind, "
                                "source_key, day, text) VALUES (%s, %s, %s, 'diary', '2026-11-10', '2026-11-10', "
                                "'Spoke about the Zoho interview.')"),
}


@pytest.fixture(scope="module")
def schema():
    """Builds the schema in an empty test database (once); {"vector": bool} says if pgvector is there."""
    psycopg = pytest.importorskip("psycopg")
    from tests import pg_schema
    with psycopg.connect(URL) as conn:
        found = pg_schema.ensure(conn)
    if not found["ready"]:
        pytest.skip("this database has tenants but no companion tables: not an empty test database")
    return found


@pytest.fixture
def pg(schema):
    import psycopg
    conn = psycopg.connect(URL)
    try:
        cur = conn.cursor()
        cur.execute("SELECT to_regprocedure(%s)", (SLOT_FN,))
        if cur.fetchone()[0] is None:
            pytest.skip("migration 262 is not applied in this database")
        ids = {k: str(uuid.uuid4()) for k in ("astro", "vastu", "guru", "jothi", "vasu", "priya", "kumar", "ravi")}
        for key in ("astro", "vastu"):
            cur.execute("INSERT INTO tenants (id, name) VALUES (%s, %s)", (ids[key], f"memory-pg-test-{key}"))
        for key, tenant, name in (("guru", "astro", "Guru"), ("jothi", "astro", "Jothi"), ("vasu", "vastu", "Vasu")):
            cur.execute("INSERT INTO companions (id, tenant_id, name) VALUES (%s, %s, %s)", (ids[key], ids[tenant], name))
        for key, tenant in (("priya", "astro"), ("kumar", "astro"), ("ravi", "vastu")):
            cur.execute("INSERT INTO companion_end_users (id, tenant_id, external_user_id) VALUES (%s, %s, %s)",
                        (ids[key], ids[tenant], key))
        yield conn, cur, ids
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("table", list(INSERTS))
def test_a_memory_row_of_the_same_business_is_saved(pg, table):
    _conn, cur, ids = pg
    cur.execute(INSERTS[table], (ids["astro"], ids["guru"], ids["priya"]))
    assert cur.rowcount == 1


@pytest.mark.parametrize("table", list(INSERTS))
@pytest.mark.parametrize("companion,person", [("guru", "ravi"),      # another business's person
                                              ("vasu", "priya"),     # another business's character
                                              ("vasu", "ravi")])     # both belong to the other business
def test_a_memory_row_cannot_point_at_another_business(pg, table, companion, person):
    import psycopg
    conn, cur, ids = pg
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():      # a savepoint, so the outer transaction survives the error
            cur.execute(INSERTS[table], (ids["astro"], ids[companion], ids[person]))


def test_a_pair_cannot_hold_two_live_facts_in_one_slot(pg):
    import psycopg
    conn, cur, ids = pg
    add = ("INSERT INTO companion_memory_facts (tenant_id, companion_id, end_user_id, section, text, slot) "
           "VALUES (%s, %s, %s, 'profile', %s, 'home_city')")
    cur.execute(add, (ids["astro"], ids["guru"], ids["priya"], "Lives in Chennai"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            cur.execute(add, (ids["astro"], ids["guru"], ids["priya"], "Lives in Bengaluru"))


def test_set_slot_fact_closes_the_old_fact_and_adds_the_new_one(pg):
    _conn, cur, ids = pg
    pair = (ids["astro"], ids["guru"], ids["priya"])
    call = "SELECT companion_set_slot_fact(%s, %s, %s, 'home_city', 'profile', %s, %s, %s, %s, NULL)"
    cur.execute(call, pair + ("Lives in Chennai", "2024-01-01", "2024-01-01", "naan Chennai la irukken"))
    assert cur.fetchone()[0]["closed"] == []
    cur.execute(call, pair + ("Lives in Bengaluru", "2026-11-10", "2026-11-10", "Bengaluru ku shift aaiten"))
    out = cur.fetchone()[0]
    assert [f["text"] for f in out["closed"]] == ["Lives in Chennai"]
    assert (out["fact"]["text"], out["fact"]["slot"], out["fact"]["status"]) == \
        ("Lives in Bengaluru", "home_city", "active")
    cur.execute("SELECT text, status, valid_to::text FROM companion_memory_facts WHERE tenant_id = %s "
                "AND end_user_id = %s ORDER BY created_at, status DESC", (ids["astro"], ids["priya"]))
    assert sorted(cur.fetchall()) == [("Lives in Bengaluru", "active", None),
                                      ("Lives in Chennai", "closed", "2026-11-10")]


# --- migration 263: the delete cutoff and the alert kinds -----------------------------------------

def needs_263(cur):
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'companion_end_users' "
                "AND column_name = 'chat_read_after'")
    if not cur.fetchone():
        pytest.skip("migration 263 is not applied in this database")


def test_a_person_can_carry_the_delete_cutoff(pg):
    _conn, cur, ids = pg
    needs_263(cur)
    cur.execute("SELECT chat_read_after FROM companion_end_users WHERE id = %s", (ids["priya"],))
    assert cur.fetchone()[0] is None                       # nothing was ever deleted: everything is read
    cur.execute("UPDATE companion_end_users SET chat_read_after = now() WHERE tenant_id = %s AND id = %s "
                "RETURNING chat_read_after", (ids["astro"], ids["priya"]))
    assert cur.fetchone()[0] is not None


@pytest.mark.parametrize("kind", ["companion_memory_parked", "companion_memory_parked_dead",
                                  "companion_memory_cleanup_gave_up", "companion_memory_delete_incomplete",
                                  "companion_memory_fact_ceiling", "token_invalid", "sms_credit_request"])
def test_the_alerts_table_accepts_the_memory_alerts_and_the_old_ones(pg, kind):
    _conn, cur, ids = pg
    needs_263(cur)
    cur.execute("INSERT INTO incidents (tenant_id, type, detail) VALUES (%s, %s, %s::jsonb)",
                (ids["astro"], kind, '{"message": "Guru could not save memories"}'))
    assert cur.rowcount == 1


def test_the_alerts_table_still_rejects_an_unknown_kind(pg):
    import psycopg
    conn, cur, ids = pg
    needs_263(cur)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            cur.execute("INSERT INTO incidents (tenant_id, type) VALUES (%s, 'companion_memory_typo')", (ids["astro"],))


# --- claim_memory_pair: one memory run per (character, person) at a time ---------------------------

CLAIM = "SELECT claim_memory_pair(%s, %s, %s, %s)"


def test_the_first_claim_wins_and_the_second_waits(pg):
    _conn, cur, ids = pg
    pair = (ids["astro"], ids["guru"], ids["priya"])
    cur.execute(CLAIM, pair + (120,))
    assert cur.fetchone()[0] is True                       # no state row yet: it is created and held
    cur.execute(CLAIM, pair + (120,))
    assert cur.fetchone()[0] is False                      # the nightly job and a same-day refresh never overlap
    cur.execute("SELECT count(*), bool_and(busy_until > now()) FROM companion_memory_state "
                "WHERE companion_id = %s AND end_user_id = %s", pair[1:])
    assert cur.fetchone() == (1, True)
    cur.execute(CLAIM, (ids["astro"], ids["guru"], ids["kumar"], 120))
    assert cur.fetchone()[0] is True                       # another person with Guru is a different pair


def test_a_claim_that_ran_out_or_was_released_can_be_taken_again(pg):
    _conn, cur, ids = pg
    pair = (ids["astro"], ids["guru"], ids["priya"])
    cur.execute(CLAIM, pair + (120,))
    cur.execute("UPDATE companion_memory_state SET busy_until = now() - interval '1 second' "
                "WHERE companion_id = %s AND end_user_id = %s", pair[1:])   # the run crashed; time ran out
    cur.execute(CLAIM, pair + (120,))
    assert cur.fetchone()[0] is True
    cur.execute("UPDATE companion_memory_state SET busy_until = NULL WHERE companion_id = %s AND end_user_id = %s",
                pair[1:])                                                    # released
    cur.execute(CLAIM, pair + (120,))
    assert cur.fetchone()[0] is True


def test_another_business_can_never_take_or_create_a_pairs_claim(pg):
    import psycopg
    conn, cur, ids = pg
    cur.execute(CLAIM, (ids["astro"], ids["guru"], ids["priya"], 120))
    cur.execute("UPDATE companion_memory_state SET busy_until = NULL WHERE companion_id = %s", (ids["guru"],))
    cur.execute(CLAIM, (ids["vastu"], ids["guru"], ids["priya"], 120))      # Vastu House names AstroTamil's pair
    assert cur.fetchone()[0] is False
    cur.execute("SELECT tenant_id::text, busy_until FROM companion_memory_state WHERE companion_id = %s", (ids["guru"],))
    assert cur.fetchone() == (ids["astro"], None)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):                 # no row yet: it cannot make one either
        with conn.transaction():
            cur.execute(CLAIM, (ids["vastu"], ids["jothi"], ids["priya"], 120))


# --- companion_day_context: "earlier today" + recent diary lines in one trip -----------------------

DAY = "SELECT companion_day_context(%s, %s, %s, %s, %s)"
DIARY = ("INSERT INTO companion_memory_diary (tenant_id, companion_id, end_user_id, day, text) "
         "VALUES (%s, %s, %s, %s, %s)")


def test_day_context_of_a_pair_with_nothing_saved(pg):
    _conn, cur, ids = pg
    cur.execute(DAY, (ids["astro"], ids["guru"], ids["priya"], "2026-11-11", 5))
    assert cur.fetchone()[0] == {"recap": None, "recap_day": None, "cleaning": False, "diary": []}


def test_day_context_says_cleaning_while_any_cleanup_waits_for_this_person_in_this_business(pg):
    # Migration 263: the owner deleted a fact of Priya on Jothi; until the cleanup has run, Guru's replies
    # to Priya get the card only. Kumar is not held, and Vastu House asking for Priya is told nothing.
    _conn, cur, ids = pg
    cur.execute("INSERT INTO companion_memory_state (tenant_id, companion_id, end_user_id, forget_pending) "
                "VALUES (%s, %s, %s, %s)", (ids["astro"], ids["jothi"], ids["priya"], '{"items": ["x"], "tries": 0}'))
    cur.execute(DAY, (ids["astro"], ids["guru"], ids["priya"], "2026-11-11", 5))
    assert cur.fetchone()[0]["cleaning"] is True
    cur.execute(DAY, (ids["astro"], ids["guru"], ids["kumar"], "2026-11-11", 5))
    assert cur.fetchone()[0]["cleaning"] is False
    cur.execute(DAY, (ids["vastu"], ids["guru"], ids["priya"], "2026-11-11", 5))
    assert cur.fetchone()[0]["cleaning"] is False
    cur.execute("UPDATE companion_memory_state SET forget_pending = NULL WHERE end_user_id = %s", (ids["priya"],))
    cur.execute(DAY, (ids["astro"], ids["guru"], ids["priya"], "2026-11-11", 5))
    assert cur.fetchone()[0]["cleaning"] is False


def test_day_context_gives_the_recap_and_the_newest_days_before_today_only(pg):
    _conn, cur, ids = pg
    pair = (ids["astro"], ids["guru"], ids["priya"])
    cur.execute("INSERT INTO companion_memory_state (tenant_id, companion_id, end_user_id, today_recap, recap_day) "
                "VALUES (%s, %s, %s, '- Zoho interview at 3 pm', '2026-11-11')", pair)
    for day in ("2026-11-05", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"):
        cur.execute(DIARY, pair + (day, f"line of {day}"))
    cur.execute(DIARY, (ids["astro"], ids["jothi"], ids["priya"], "2026-11-10", "Jothi's line about Priya"))
    cur.execute(DIARY, (ids["astro"], ids["guru"], ids["kumar"], "2026-11-10", "Guru's line about Kumar"))
    cur.execute(DIARY, (ids["vastu"], ids["vasu"], ids["ravi"], "2026-11-10", "Vasu's line about Ravi"))

    cur.execute(DAY, pair + ("2026-11-11", 3))
    out = cur.fetchone()[0]
    assert (out["recap"], out["recap_day"]) == ("- Zoho interview at 3 pm", "2026-11-11")
    assert out["diary"] == [{"day": "2026-11-10", "text": "line of 2026-11-10"},     # newest first,
                            {"day": "2026-11-09", "text": "line of 2026-11-09"},     # today's own line left out,
                            {"day": "2026-11-08", "text": "line of 2026-11-08"}]     # only 3 days asked for
    cur.execute(DAY, (ids["vastu"], ids["guru"], ids["priya"], "2026-11-11", 3))     # another business asks
    assert cur.fetchone()[0] == {"recap": None, "recap_day": None, "cleaning": False, "diary": []}


# --- match_memory_chunks: long-term search (needs pgvector) ----------------------------------------

MATCH = ("SELECT text, source, round(score::numeric, 3)::float FROM match_memory_chunks("
         "%s, %s::uuid[], %s, %s::vector, %s, %s)")
CHUNK = ("INSERT INTO companion_memory_chunks (tenant_id, companion_id, end_user_id, kind, source_key, day, text, "
         "embedding) VALUES (%s, %s, %s, %s, %s, '2026-11-10', %s, %s::vector)")


def axis(i: int) -> str:
    """A 768-number vector pointing along axis i: same axis = similarity 1, another axis = 0."""
    return "[" + ",".join("1" if n == i else "0" for n in range(768)) + "]"


@pytest.fixture
def chunks(pg, schema):
    if not schema["vector"]:
        pytest.skip("pgvector is not installed in this database")
    _conn, cur, ids = pg
    rows = [("astro", "guru", "priya", "messages", "m1", "Person: Zoho interview on 20 Nov", axis(0)),
            ("astro", "guru", "priya", "diary", "d1", "Watched Leo with Arun", axis(1)),
            ("astro", "guru", "priya", "fact", "f1", "Amma lives in Madurai", None),          # embedding failed
            ("astro", "jothi", "priya", "messages", "m2", "Person: Zoho offer letter came", axis(0)),
            ("astro", "guru", "kumar", "messages", "m3", "Kumar: Zoho interview, Madurai", axis(0)),
            ("vastu", "vasu", "ravi", "messages", "m4", "Ravi: Zoho interview, Madurai", axis(0))]
    for tenant, companion, person, kind, key, text, vector in rows:
        cur.execute(CHUNK, (ids[tenant], ids[companion], ids[person], kind, key, text, vector))
    return cur, ids


def test_search_returns_the_nearest_pieces_by_meaning_and_by_words(chunks):
    cur, ids = chunks
    cur.execute(MATCH, (ids["astro"], [ids["guru"]], ids["priya"], axis(0), "Madurai", 5))
    rows = cur.fetchall()
    by_vector = [(t, s) for t, source, s in rows if source == "vector"]
    by_words = [(t, s) for t, source, s in rows if source == "trigram"]
    assert by_vector == [("Person: Zoho interview on 20 Nov", 1.0), ("Watched Leo with Arun", 0.0)]
    assert by_words[0] == ("Amma lives in Madurai", 1.0)      # found by its words though it has no vector
    assert all(score > 0 for _t, score in by_words)


def test_search_never_crosses_to_another_person_character_or_business(chunks):
    cur, ids = chunks
    cur.execute(MATCH, (ids["astro"], [ids["guru"]], ids["priya"], axis(0), "Zoho interview Madurai", 50))
    texts = {t for t, _source, _s in cur.fetchall()}
    assert texts == {"Person: Zoho interview on 20 Nov", "Watched Leo with Arun", "Amma lives in Madurai"}
    # business scope: Jothi's pieces about Priya join in, still nobody else's
    cur.execute(MATCH, (ids["astro"], [ids["guru"], ids["jothi"]], ids["priya"], axis(0), "", 50))
    assert {t for t, _source, _s in cur.fetchall()} == {
        "Person: Zoho interview on 20 Nov", "Watched Leo with Arun", "Person: Zoho offer letter came"}
    # Vastu House asking for AstroTamil's character and person gets nothing
    cur.execute(MATCH, (ids["vastu"], [ids["guru"]], ids["priya"], axis(0), "Zoho", 50))
    assert cur.fetchall() == []


def test_search_works_with_only_words_or_only_a_vector_and_respects_the_count(chunks):
    cur, ids = chunks
    args = (ids["astro"], [ids["guru"]], ids["priya"])
    cur.execute(MATCH, args + (None, "Leo", 5))                # the embedding call timed out
    assert [(t, source) for t, source, _s in cur.fetchall()] == [("Watched Leo with Arun", "trigram")]
    cur.execute(MATCH, args + (axis(1), "", 5))                # nothing to match by words
    assert [(t, source, s) for t, source, s in cur.fetchall()] == [
        ("Watched Leo with Arun", "vector", 1.0), ("Person: Zoho interview on 20 Nov", "vector", 0.0)]
    cur.execute(MATCH, args + (axis(0), "Madurai", 1))         # 1 per half
    assert [(t, source) for t, source, _s in cur.fetchall()] == [
        ("Person: Zoho interview on 20 Nov", "vector"), ("Amma lives in Madurai", "trigram")]


def test_only_the_backend_may_call_the_memory_functions(pg, schema):
    _conn, cur, _ids = pg
    embedding = "vector" if schema["vector"] else "text"
    for fn in ("claim_memory_pair(uuid, uuid, uuid, integer)", "companion_day_context(uuid, uuid, uuid, date, integer)",
               f"match_memory_chunks(uuid, uuid[], uuid, {embedding}, text, integer)", SLOT_FN):
        cur.execute("SELECT has_function_privilege('anon', %s, 'EXECUTE'), "
                    "has_function_privilege('authenticated', %s, 'EXECUTE'), "
                    "has_function_privilege('service_role', %s, 'EXECUTE')", (fn, fn, fn))
        assert cur.fetchone() == (False, False, True), fn
