"""The app data each live reply was given, kept KEEP_DAYS days (AstroTamil, 27 Nov 2026).

So "why did Jothidar say Budhan bhukti is in 2028?" can be checked against what the app really sent with that
message. Example: Manjari asks "Velai eppo?"; after the reply is saved, schedule(...) writes
    (tenant, Jothidar AI, Manjari, <reply message id>, '{"lagnam": "சிம்மம்", "dasa": ...}')
to companion_app_data_log (migration 351). Birth date, time and place are removed first (strip_app_data),
whether or not the character has the chart guard on. The nightly companion-app-data-prune job calls prune().

Live replies only (engine._finish skips Playground tests). Nothing here raises: a broken log must not
break a chat.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.companion import store
from app.companion.birth_guard import strip_app_data
from app.companion.models import MAX_APP_DATA_CHARS

logger = logging.getLogger(__name__)

KEEP_DAYS = 7
_tasks: set[asyncio.Task] = set()


def schedule(tenant_id: str, companion_id: str, end_user_id: str, message_id: str, app_data: str | None) -> None:
    """Starts the write in the background; no app data -> nothing. Never raises."""
    try:
        text = (strip_app_data(app_data) or "").strip()[:MAX_APP_DATA_CHARS]
        if not text:
            return
        row = {"tenant_id": tenant_id, "companion_id": companion_id, "end_user_id": end_user_id,
               "message_id": message_id, "app_data": text}
        task = asyncio.get_running_loop().create_task(_save(row))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception as exc:
        logger.warning("companion app data log: could not schedule (%s)", type(exc).__name__)


async def _save(row: dict) -> None:
    try:
        await store.save_app_data_log(row)
    except Exception as exc:
        logger.warning("companion app data log: insert failed (%s)", type(exc).__name__)


async def prune(now: datetime | None = None) -> None:
    """Deletes the rows older than KEEP_DAYS (queue task companion-app-data-prune). Raises on a DB error,
    so the Scheduler page shows the job failed."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)
    await store.prune_app_data_log(cutoff.isoformat())
