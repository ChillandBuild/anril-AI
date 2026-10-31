"""One-off install of the task queue: `python -m app.queue.schema` (reads DATABASE_URL).
Creates the procrastinate schema (migration 238), then Procrastinate's tables inside it."""
import asyncio
from pathlib import Path

import psycopg
from procrastinate.schema import SchemaManager

MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "238_procrastinate_schema.sql"


async def install(dsn: str) -> str:
    """Install once; a second run reports "already installed" and changes nothing."""
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        found = await (await conn.execute("SELECT to_regclass('procrastinate.procrastinate_jobs')")).fetchone()
        if found[0]:
            return "already installed"
        async with conn.transaction():
            await conn.execute(MIGRATION.read_text(encoding="utf-8"))
            await conn.execute("SET LOCAL search_path TO procrastinate")
            await conn.execute(SchemaManager.get_schema())
    return "installed"


if __name__ == "__main__":
    from app.config import settings

    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set")
    print(asyncio.run(install(settings.database_url)))
