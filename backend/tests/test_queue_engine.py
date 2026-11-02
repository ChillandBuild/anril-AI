"""The Procrastinate queue engine: settings, the connection pool, and installing the queue into its
own `procrastinate` schema so PostgREST (which serves `public`) never exposes job rows.

The install test needs a throwaway Postgres: set QUEUE_TEST_DSN (never the live database)."""
import asyncio
import os

import pytest

from app.config import Settings


def _settings(**kw):
    return Settings(supabase_url="http://x", supabase_service_key="k", **kw)


def test_the_queue_pool_is_small_and_pins_the_search_path():
    from app.queue.app import queue_app, _set_search_path

    args = queue_app.connector._pool_args
    assert args["min_size"] == 1 and args["max_size"] == 4
    assert args["configure"] is _set_search_path
    assert queue_app.periodic_defaults["max_delay"] == 6 * 3600


def test_each_new_connection_gets_the_procrastinate_search_path_and_is_left_idle():
    from app.queue.app import _set_search_path

    class FakeConn:
        def __init__(self):
            self.sql, self.committed = [], False

        async def execute(self, sql, *a):
            self.sql.append(sql)

        async def commit(self):
            self.committed = True

    conn = FakeConn()
    asyncio.run(_set_search_path(conn))
    assert conn.sql == ["SELECT set_config('search_path', 'procrastinate', false)"]
    assert conn.committed


DSN = os.environ.get("QUEUE_TEST_DSN")
needs_pg = pytest.mark.skipif(not DSN, reason="QUEUE_TEST_DSN not set (throwaway Postgres only)")


@pytest.fixture
def fresh_db():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    name = "queue_engine_test"
    admin = make_conninfo(DSN, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name}")
        c.execute(f"CREATE DATABASE {name}")
        for role in ("anon", "authenticated"):
            c.execute(f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    yield make_conninfo(DSN, dbname=name)
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _objects_by_schema(dsn):
    import psycopg

    with psycopg.connect(dsn) as c:
        return dict(c.execute(
            "SELECT n.nspname, count(*) FROM pg_class r JOIN pg_namespace n ON n.oid = r.relnamespace "
            "WHERE r.relname LIKE 'procrastinate%' GROUP BY 1"
        ).fetchall())


@needs_pg
def test_install_puts_every_queue_table_in_the_procrastinate_schema(fresh_db):
    from app.queue.schema import install

    assert asyncio.run(install(fresh_db)) == "installed"
    by_schema = _objects_by_schema(fresh_db)
    assert by_schema.get("procrastinate", 0) > 0
    assert "public" not in by_schema


@needs_pg
def test_install_creates_the_pause_table_and_locks_out_the_api_roles(fresh_db):
    import psycopg
    from app.queue.schema import install

    asyncio.run(install(fresh_db))
    with psycopg.connect(fresh_db) as c:
        assert c.execute("SELECT to_regclass('procrastinate.task_controls')").fetchone()[0]
        for role in ("anon", "authenticated"):
            assert c.execute("SELECT has_schema_privilege(%s, 'procrastinate', 'USAGE')", (role,)).fetchone()[0] is False


@needs_pg
def test_a_second_install_changes_nothing(fresh_db):
    from app.queue.schema import install

    asyncio.run(install(fresh_db))
    before = _objects_by_schema(fresh_db)
    assert asyncio.run(install(fresh_db)) == "already installed"
    assert _objects_by_schema(fresh_db) == before


@needs_pg
def test_the_queue_app_works_through_the_search_path(fresh_db):
    """A job deferred and fetched via the pinned pool lands in procrastinate.procrastinate_jobs."""
    import psycopg
    import procrastinate
    from app.queue.app import _set_search_path
    from app.queue.schema import install

    asyncio.run(install(fresh_db))
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(
        conninfo=fresh_db, min_size=1, max_size=2, configure=_set_search_path))

    @app.task(name="probe")
    def probe():
        pass

    async def defer():
        async with app.open_async():
            return await probe.defer_async()

    job_id = asyncio.run(defer())
    with psycopg.connect(fresh_db) as c:
        assert c.execute("SELECT task_name FROM procrastinate.procrastinate_jobs WHERE id = %s", (job_id,)).fetchone()[0] == "probe"
