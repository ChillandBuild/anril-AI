"""Call IQ leave (v9.2 #21): a telecaller on leave today gets no new leads from the assignment pool."""
from datetime import date
from unittest.mock import patch

from app.services import assignment
from tests.fake_supabase import FakeSupabase


def _db():
    db = FakeSupabase()
    db.tables["callers"] = [
        {"id": "a", "tenant_id": "t", "name": "Asha", "active": True, "user_id": "ua", "created_at": "1"},
        {"id": "b", "tenant_id": "t", "name": "Bala", "active": True, "user_id": "ub", "created_at": "2",
         "leave_from": "2026-11-20", "leave_to": "2026-11-25"},
        {"id": "c", "tenant_id": "t", "name": "Chitra", "active": True, "user_id": "uc", "created_at": "3",
         "leave_from": "2026-12-01", "leave_to": "2026-12-03"},
    ]
    return db


def test_person_on_leave_today_is_left_out_and_future_leave_is_not():
    with patch.object(assignment, "_owner_user_id", return_value=None), \
         patch("app.services.caller_leave.today_ist", return_value=date(2026, 11, 23)):
        ids = [c["id"] for c in assignment.eligible_callers(_db(), "t")]
    assert ids == ["a", "c"]


def test_leave_read_failure_keeps_everyone():
    with patch.object(assignment, "_owner_user_id", return_value=None), \
         patch("app.services.caller_leave.on_leave", side_effect=RuntimeError("no column")):
        ids = [c["id"] for c in assignment.eligible_callers(_db(), "t")]
    assert ids == ["a", "b", "c"]
