"""Builds the companion memory schema in an EMPTY Postgres from the REAL migration files, so the memory
SQL (foreign keys, unique indexes, functions) is tested on a real database and not on the fake one.

Used by tests/test_companion_memory_pg.py. GitHub CI starts a throwaway Postgres with pgvector and points
COMPANION_MEMORY_TEST_DATABASE_URL at it; the first test builds the schema here.

What is NOT from a migration file: the three things Supabase or older migrations provide, as the smallest
stand-ins the memory files need (Supabase's roles; `tenants`, `broadcast_tags`, `incidents` with only the
columns the memory files touch).

No pgvector on the machine (a bare Homebrew Postgres): the `embedding` column becomes text and the tests
that search by vector are skipped. Everything else (tenant links, slots, the claim, the day context)
still runs. CI has pgvector, so there the files are applied unchanged.

A database that already has the tables (a Supabase branch) is left alone. A database that has `tenants`
but no `companions` is not an empty test database: nothing is built.
"""
import re
from pathlib import Path

MIGRATIONS = Path(__file__).parent.parent / "supabase" / "migrations"
FILES = ["248_companion_core.sql", "249_companion_memory.sql", "255_companion_memory_recap_diary.sql",
         "256_companion_memory_v2.sql", "261_companion_memory_receipts.sql",
         "262_companion_memory_slots_threads_links.sql", "263_companion_chat_read_after.sql"]

STAND_INS = """
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END $$;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE tenants (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL);
CREATE TABLE broadcast_tags (id uuid PRIMARY KEY DEFAULT gen_random_uuid());
CREATE TABLE incidents (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
                        type text NOT NULL, detail jsonb NOT NULL DEFAULT '{}'::jsonb,
                        created_at timestamptz NOT NULL DEFAULT now());
"""


def _exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
    return cur.fetchone()[0]


def _has_vector_column(cur) -> bool:
    cur.execute("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attname = 'embedding' "
                "AND attrelid = to_regclass('public.companion_memory_chunks')")
    row = cur.fetchone()
    return bool(row) and row[0].startswith("vector")


def ensure(conn) -> dict:
    """{"ready": bool, "vector": bool, "built": bool}. Builds the schema only in an empty database."""
    cur = conn.cursor()
    if _exists(cur, "companions"):
        out = {"ready": True, "vector": _has_vector_column(cur), "built": False}
        conn.rollback()
        return out
    if _exists(cur, "tenants"):
        conn.rollback()
        return {"ready": False, "vector": False, "built": False}
    cur.execute("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
    vector = cur.fetchone()[0]
    cur.execute(STAND_INS)
    if vector:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    else:
        cur.execute("SET LOCAL check_function_bodies = off")   # match_memory_chunks is created but not callable
    for name in FILES:
        sql = (MIGRATIONS / name).read_text()
        if not vector:
            sql = re.sub(r"\bvector\(768\)", "text", sql).replace(", vector, text, integer)", ", text, text, integer)")
        cur.execute(sql)
    conn.commit()
    return {"ready": True, "vector": vector, "built": True}


if __name__ == "__main__":   # python -m tests.pg_schema postgresql://...   (an empty test database)
    import sys

    import psycopg

    with psycopg.connect(sys.argv[1]) as connection:
        print(ensure(connection))
