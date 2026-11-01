"""scheduler_runs keeps only failures (the queue's own tables hold every run), and the nightly
scheduler-runs-prune task drops those older than 7 days."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import app.main


@pytest.mark.asyncio
async def test_the_nightly_prune_drops_rows_older_than_7_days():
    db = MagicMock()
    with patch("app.db.supabase.get_supabase", return_value=db):
        await app.main._prune_scheduler_runs()
    db.table.assert_called_once_with("scheduler_runs")
    col, cutoff = db.table.return_value.delete.return_value.lt.call_args.args
    assert col == "ran_at"
    age = datetime.now(timezone.utc) - datetime.fromisoformat(cutoff)
    assert timedelta(days=7) - timedelta(minutes=1) < age < timedelta(days=7) + timedelta(minutes=1)
