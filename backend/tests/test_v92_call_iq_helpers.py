"""v9.2 items 233, 234, 135: kept-on-time, rows taken out of an upload, Call IQ Live lists."""
import uuid
from datetime import datetime, timedelta, timezone

from app.services import call_iq_reports as svc
from app.services import callback_stats as cs
from app.services import upload_taken_out as uto
from fake_supabase import FakeSupabase

T1, T2 = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
NOW = datetime(2026, 11, 22, 7, 0, tzinfo=timezone.utc)  # 12:30 PM IST
TODAY = "2026-11-22T05:00:00+00:00"


def iso(dt):
    return dt.isoformat()


# ── 234: taken-out helpers ───────────────────────────────────────────────────

def test_reason_for_existing_order():
    assert uto.reason_for_existing({"do_not_call": True}, is_new=False) == "said_stop"
    assert uto.reason_for_existing({"opted_out": True}, is_new=True) == "said_stop"
    assert uto.reason_for_existing({"converted_at": "x"}, is_new=False) == "already_customer"
    assert uto.reason_for_existing({"call_status": "wrong_number"}, is_new=False) == "closed"
    assert uto.reason_for_existing({"assigned_to": "c1"}, is_new=False) == "already_with_caller"
    assert uto.reason_for_existing({"assigned_to": "c1"}, is_new=True) is None
    assert uto.reason_for_existing({}, is_new=False) is None


def test_summarize_caps_rows_but_counts_everything():
    rows = [{"row": i, "reason": "duplicate"} for i in range(uto.MAX_STORED_ROWS + 5)]
    kept, counts = uto.summarize(rows)
    assert len(kept) == uto.MAX_STORED_ROWS and counts == {"duplicate": uto.MAX_STORED_ROWS + 5}


def test_csv_text_masks_phones_and_defuses_formulas():
    text = uto.csv_text([{"row": 2, "phone": "+919876543210", "name": "=cmd()", "reason": "bad_number"}],
                        mask=lambda p: "98•••••210")
    assert "98•••••210" in text and "9876543210" not in text
    assert "'=cmd()" in text and "Bad number" in text


def test_results_for_counts_each_person_once_after_the_upload():
    calls = [
        {"lead_id": "a", "created_at": "2026-11-21T10:00:00+00:00", "manual_status": "connected", "outcome": "converted"},
        {"lead_id": "a", "created_at": "2026-11-21T11:00:00+00:00", "manual_status": "connected"},
        {"lead_id": "b", "created_at": "2026-11-21T10:00:00+00:00", "manual_status": "not_picked"},
        {"lead_id": "c", "created_at": "2026-11-19T10:00:00+00:00", "manual_status": "connected"},   # before the upload
        {"lead_id": "z", "created_at": "2026-11-21T10:00:00+00:00", "manual_status": "connected"},   # not in the upload
    ]
    out = uto.results_for({"a", "b", "c"}, calls, "2026-11-20T00:00:00+00:00")
    assert out == {"called": 2, "reached": 1, "converted": 1}


# ── 233: kept on time ────────────────────────────────────────────────────────

def test_on_time_counts_window_is_15_minutes_either_side():
    when = "2026-11-20T10:00:00+00:00"
    jobs = [{"id": "j1", "scheduled_for": when}, {"id": "j2", "scheduled_for": when}, {"id": "j3", "scheduled_for": when}]
    calls = [
        {"follow_up_job_id": "j1", "created_at": "2026-11-20T10:14:00+00:00"},
        {"follow_up_job_id": "j2", "created_at": "2026-11-20T10:16:00+00:00"},
    ]
    assert cs.on_time_counts(jobs, calls) == (1, 3)


def _job(db, tenant, lead, at, status="pending"):
    return db.add("follow_up_jobs", tenant_id=tenant, lead_id=lead, cadence="callback", status=status, scheduled_for=iso(at))


def test_kept_on_time_scope_tenant_and_not_yet_due():
    db = FakeSupabase()
    db.add("leads", id="l1", tenant_id=T1, assigned_to="c1")
    db.add("leads", id="l2", tenant_id=T1, assigned_to="c2")
    db.add("leads", id="l3", tenant_id=T2, assigned_to="c1")
    at = NOW - timedelta(days=2)
    j1, j2, j3 = _job(db, T1, "l1", at, "sent"), _job(db, T1, "l2", at), _job(db, T2, "l3", at)
    _job(db, T1, "l1", NOW - timedelta(minutes=5))              # window still open: not counted
    _job(db, T1, "l1", NOW - timedelta(days=40))                # older than 30 days: not counted
    db.add("call_logs", tenant_id=T1, follow_up_job_id=j1["id"], created_at=iso(at + timedelta(minutes=3)))
    everyone = cs.kept_on_time(db, T1, None, NOW)
    assert (everyone["kept"], everyone["due"], everyone["percent"]) == (1, 2, 50)
    mine = cs.kept_on_time(db, T1, {"c2"}, NOW)
    assert (mine["kept"], mine["due"], mine["percent"]) == (0, 1, 0)
    assert cs.kept_on_time(db, T1, set(), NOW)["percent"] is None
    assert j2 and j3


# ── 135: Live lists ──────────────────────────────────────────────────────────

def _ctx(role="owner", caller_id=None, perms=()):
    return {"tenant_id": T1, "role": role, "user_id": "u", "caller_id": caller_id, "permissions": list(perms)}


def _setup():
    db = FakeSupabase()
    a = db.add("callers", tenant_id=T1, name="Anitha", active=True, status="active")["id"]
    b = db.add("callers", tenant_id=T1, name="Bala", active=True, status="active")["id"]
    return db, a, b


def test_live_callbacks_due_window_and_scope():
    db, a, b = _setup()
    la = db.add("leads", tenant_id=T1, name="Priya", phone="+919876543210", assigned_to=a)["id"]
    lb = db.add("leads", tenant_id=T1, name="Kumar", phone="+919876543211", assigned_to=b)["id"]
    ld = db.add("leads", tenant_id=T1, name="Stopped", phone="+919876543212", assigned_to=a, do_not_call=True)["id"]
    for lead, minutes, status in [(la, -20, "pending"), (lb, 10, "pending"), (la, -45, "pending"), (la, 30, "pending"),
                                  (la, -5, "sent"), (ld, -5, "pending")]:
        db.add("follow_up_jobs", tenant_id=T1, lead_id=lead, cadence="callback", status=status,
               scheduled_for=iso(NOW + timedelta(minutes=minutes)), message_preview="asked for price")
    out = svc.live(db, _ctx(), NOW)
    assert [r["name"] for r in out["callbacks_due"]] == ["Priya", "Kumar"]
    assert out["callbacks_due"][0]["why"] == "asked for price" and out["callbacks_due"][0]["caller_name"] == "Anitha"
    mine = svc.live(db, _ctx("caller", a, ["telecalling.view"]), NOW)
    assert [r["name"] for r in mine["callbacks_due"]] == ["Priya"]


def test_live_waiting_hot_leads_not_called_today():
    db, a, b = _setup()
    db.add("leads", id="h1", tenant_id=T1, name="Hot one", phone="+919800000001", assigned_to=a, call_status="hot", score=70)
    db.add("leads", id="h2", tenant_id=T1, name="Hot called", phone="+919800000002", assigned_to=a, call_status="hot", score=90)
    db.add("leads", id="h3", tenant_id=T1, name="Warm", phone="+919800000003", assigned_to=a, call_status="warm")
    db.add("leads", id="h4", tenant_id=T1, name="Hot theirs", phone="+919800000004", assigned_to=b, call_status="hot")
    db.add("leads", id="h5", tenant_id=T2, name="Other client", phone="+919800000005", assigned_to=a, call_status="hot")
    db.add("call_logs", tenant_id=T1, caller_id=a, lead_id="h2", status="completed", created_at=TODAY)
    out = svc.live(db, _ctx(), NOW)
    assert [r["name"] for r in out["waiting"]["rows"]] == ["Hot one", "Hot theirs"] and out["waiting"]["total"] == 2
    mine = svc.live(db, _ctx("caller", a, ["telecalling.view"]), NOW)
    assert [r["name"] for r in mine["waiting"]["rows"]] == ["Hot one"]


def test_live_lists_empty_when_nobody_visible():
    out = svc.live(FakeSupabase(), _ctx("caller", None, ["telecalling.view"]), NOW)
    assert out["callbacks_due"] == [] and out["waiting"] == {"total": 0, "rows": []}
