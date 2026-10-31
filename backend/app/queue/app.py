"""The Procrastinate app: scheduled jobs as rows in Postgres (SPEC.md). Nothing connects until
the worker opens it, so importing this is safe on laptops and in tests."""
import procrastinate

from app.config import settings


async def _set_search_path(conn) -> None:
    """Point every new connection (pool and LISTEN) at the private procrastinate schema."""
    # Procrastinate's SQL is unqualified; the pool discards a connection left mid-transaction.
    await conn.execute("SELECT set_config('search_path', 'procrastinate', false)")
    await conn.commit()


queue_app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=settings.database_url or "",
        min_size=1,
        max_size=4,
        configure=_set_search_path,
    ),
    periodic_defaults={"max_delay": 6 * 3600},
    worker_defaults={"concurrency": 4},
)
