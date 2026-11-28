"""An audit row must survive a dropped connection without being written twice.

A dropped insert may already have been saved (seen 2026-11-27: the Claude connector withheld
an answer for a row that was in the table). So the row carries an id chosen here, and the
retry says "save this id unless it is already there".
"""
import uuid
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import audit_log


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(audit_log, "_RETRY_WAIT_SECONDS", 0)


def _write(db):
    audit_log.write_audit_event(
        db, tenant_id="t1", actor_user_id="u1", actor_role="owner",
        action="claude.read", target_type="claude_tool", target_id="leads_overview",
        metadata={"stage": "done"},
    )


def _dropped():
    return httpx.RemoteProtocolError("Server disconnected")


def test_the_row_carries_an_id_chosen_by_anril():
    db = MagicMock()
    _write(db)
    row = db.table.return_value.insert.call_args.args[0]
    assert uuid.UUID(row["id"])
    db.table.return_value.upsert.assert_not_called()


def test_a_dropped_write_is_repeated_with_the_same_id_and_cannot_duplicate():
    db = MagicMock()
    table = db.table.return_value
    table.insert.return_value.execute.side_effect = _dropped()

    _write(db)  # does not raise

    first = table.insert.call_args.args[0]
    again = table.upsert.call_args
    assert again.args[0] == first
    assert again.kwargs == {"on_conflict": "id", "ignore_duplicates": True}
    assert table.upsert.return_value.execute.call_count == 1


def test_it_gives_up_when_the_connection_keeps_dropping():
    db = MagicMock()
    table = db.table.return_value
    table.insert.return_value.execute.side_effect = _dropped()
    table.upsert.return_value.execute.side_effect = _dropped()

    with pytest.raises(httpx.RemoteProtocolError):
        _write(db)
    assert table.upsert.return_value.execute.call_count == audit_log._RETRIES


def test_a_real_database_error_is_not_retried():
    db = MagicMock()
    table = db.table.return_value
    table.insert.return_value.execute.side_effect = RuntimeError("column does not exist")

    with pytest.raises(RuntimeError):
        _write(db)
    table.upsert.assert_not_called()
