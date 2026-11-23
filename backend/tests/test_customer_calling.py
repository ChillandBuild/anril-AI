"""services/customer_calling.py: "Send to calling" cleans the list like the calling queue does."""
from unittest.mock import MagicMock

from app.services import assignment
from app.services import customer_calling as cc


def _db(rows):
    db = MagicMock()
    q = db.table.return_value
    for name in ("select", "eq", "in_"):
        getattr(q, name).return_value = q
    q.execute.return_value = MagicMock(data=rows)
    return db


ROWS = [
    {"id": "a", "assigned_to": None},                       # open -> sent
    {"id": "b", "assigned_to": None, "opted_out": True},    # said stop
    {"id": "c", "assigned_to": None, "do_not_call": True},  # don't call = said stop for calls
    {"id": "d", "assigned_to": None, "converted_at": "2026-11-01"},  # bought
    {"id": "e", "assigned_to": "caller-x"},                 # already with a caller
    {"id": "f", "assigned_to": None, "blocked_at": "2026-11-02"},    # blocked
    {"id": "g", "assigned_to": None},                       # open -> sent
]


def _fake(rows):
    from tests.fake_supabase import FakeSupabase
    db = FakeSupabase()
    for r in rows:
        db.add("leads", **{"tenant_id": "t1", "segment": "B", "opted_out": None, "do_not_call": None,
                           "converted_at": None, "deleted_at": None, "blocked_at": None, "call_status": None, **r})
    return db


def test_cleans_like_the_queue_and_takes_turns(monkeypatch):
    callers = [{"id": "c1", "user_id": "u1", "name": "Kavi"}, {"id": "c2", "user_id": None, "name": "Ravi"}]
    monkeypatch.setattr(assignment, "eligible_callers", lambda db, t: callers)
    saved = {}
    monkeypatch.setattr(assignment, "_setting_json", lambda db, t, k, d: {"last_caller_id": "c2"})
    monkeypatch.setattr(assignment, "_save_setting_json", lambda db, t, k, v: saved.update(v))
    bells = []
    import app.services.notify as notify
    monkeypatch.setattr(notify, "notify_user", lambda *a, **k: bells.append(a))

    db = _fake(ROWS)
    out = cc.send_to_calling(db, "t1", [r["id"] for r in ROWS] + ["a", "missing"], reason="customers_bulk")
    leads = {r["id"]: r for r in db.rows("leads")}
    # Last turn was c2, so c1 goes first, then c2.
    assert (leads["a"]["assigned_to"], leads["g"]["assigned_to"]) == ("c1", "c2")
    assert leads["b"]["assigned_to"] is None and leads["e"]["assigned_to"] == "caller-x"
    assert saved == {"last_caller_id": "c2"}
    assert (out["added"], out["said_stop"], out["bought"], out["already"], out["closed"], out["not_found"]) == (2, 2, 1, 1, 1, 1)
    assert sorted(out["added_ids"]) == ["a", "g"]
    log = db.rows("lead_stage_events")
    assert sorted((e["lead_id"], e["metadata"]["caller_id"], e["metadata"]["reason"]) for e in log) == [
        ("a", "c1", "customers_bulk"), ("g", "c2", "customers_bulk")]
    assert {e["to_segment"] for e in log} == {"B"}
    assert len(bells) == 1 and bells[0][1] == "u1"  # one bell per caller with a login, none for c2


def test_a_person_taken_a_moment_ago_counts_as_already(monkeypatch):
    callers = [{"id": "c1", "user_id": None}]
    monkeypatch.setattr(assignment, "eligible_callers", lambda db, t: callers)
    monkeypatch.setattr(assignment, "_setting_json", lambda db, t, k, d: {})
    monkeypatch.setattr(assignment, "_save_setting_json", lambda *a: None)
    db = _fake([{"id": "a", "assigned_to": None}])
    real_classify = cc.classify

    def classify_then_race(lead):  # someone else assigns the lead between our read and our write
        kind = real_classify(lead)
        db.rows("leads")[0]["assigned_to"] = "other"
        return kind

    monkeypatch.setattr(cc, "classify", classify_then_race)
    out = cc.send_to_calling(db, "t1", ["a"], reason="group")
    assert (out["added"], out["already"]) == (0, 1)
    assert db.rows("lead_stage_events") == []


def test_no_callers_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(assignment, "eligible_callers", lambda db, t: [])
    out = cc.send_to_calling(_db([{"id": "a", "assigned_to": None}]), "t1", ["a"], reason="group")
    assert out["no_callers"] is True and out["added"] == 0


def test_empty_list_touches_nothing():
    db = MagicMock()
    assert cc.send_to_calling(db, "t1", [], reason="group")["added"] == 0
    db.table.assert_not_called()
