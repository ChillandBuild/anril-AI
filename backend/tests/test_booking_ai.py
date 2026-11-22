"""The AI's booking block: only when the link is on and a service is active; never raises."""
from unittest.mock import MagicMock

from app.services import booking_ai


def _db(settings_rows, service_rows):
    db = MagicMock()

    def table(name):
        q = MagicMock()
        for m in ("select", "eq", "order", "limit"):
            getattr(q, m).return_value = q
        q.execute.return_value = MagicMock(data=settings_rows if name == "booking_settings" else service_rows)
        return q

    db.table.side_effect = table
    return db


def setup_function():
    booking_ai.clear_cache()


def test_block_has_link_and_services(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com/")
    text = booking_ai.prompt_block(_db([{"link_token": "tok123", "link_on": True}], [{"name": "Reading"}, {"name": "Match"}]), "t1")
    assert "https://app.example.com/book/tok123" in text
    assert "Reading, Match" in text
    assert "never say a time is free" in text


def test_no_block_when_link_off_or_no_services():
    assert booking_ai.prompt_block(_db([{"link_token": "tok", "link_on": False}], [{"name": "A"}]), "t2") == ""
    assert booking_ai.prompt_block(_db([{"link_token": "tok", "link_on": True}], []), "t3") == ""
    assert booking_ai.prompt_block(_db([], [{"name": "A"}]), "t4") == ""


def test_missing_tables_never_raise():
    db = MagicMock()
    db.table.side_effect = RuntimeError("relation booking_settings does not exist")
    assert booking_ai.prompt_block(db, "t5") == ""


def test_cached_per_tenant():
    db = _db([{"link_token": "tok", "link_on": True}], [{"name": "A"}])
    first = booking_ai.prompt_block(db, "t6")
    db.table.side_effect = RuntimeError("should not be called")
    assert booking_ai.prompt_block(db, "t6") == first
