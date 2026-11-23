"""Settings > Alerts is enforced where alerts are sent: off means no bell/push, "who gets it" filters people,
the always-on alerts cannot be switched off, a disconnected number alerts the owner once per status change,
and the AI-reply thumbs-down marks come back for the caller only."""
import asyncio
import json
from unittest.mock import patch

import pytest

from app.services import alert_catalog, notification_config as nc, notify, number_sync


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload = db, name, [], "select", None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.filters.append(("eq", k, v)); return self
    def in_(self, k, v): self.filters.append(("in", k, list(v))); return self
    def limit(self, *_a): return self
    def maybe_single(self): self.single = True; return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, row): self.op, self.payload = "update", row; return self
    def upsert(self, row, **_k): self.op, self.payload = "upsert", row; return self

    def execute(self):
        class R: pass
        r = R()
        rows = self.db.rows.get(self.name, [])
        if self.op in ("insert", "upsert", "update"):
            self.db.writes.append((self.name, self.op, self.payload))
            if self.op == "upsert" and self.name == "app_settings":
                rows = [x for x in rows if x["key"] != self.payload["key"]]
                self.db.rows["app_settings"] = rows + [self.payload]
            r.data = [self.payload]
            return r
        out = []
        for row in rows:
            ok = True
            for kind, k, v in self.filters:
                if kind == "eq" and row.get(k) != v: ok = False
                if kind == "in" and row.get(k) not in v: ok = False
            if ok:
                out.append(row)
        r.data = (out[0] if out else None) if getattr(self, "single", False) else out
        return r


class FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.writes = []

    def table(self, name): return _Q(self, name)

    def bells(self):
        return [(w[2]["user_id"], w[2]["type"]) for w in self.writes if w[0] == "app_notifications" and w[1] == "insert"]


def _db(events=None, recipients=None):
    settings = []
    if events is not None:
        settings.append({"tenant_id": "t1", "key": "notification_config", "value": json.dumps({"events": events})})
    if recipients is not None:
        settings.append({"tenant_id": "t1", "key": "alert_recipients", "value": json.dumps(recipients)})
    return FakeDB({
        "app_settings": settings,
        "tenant_users": [
            {"tenant_id": "t1", "user_id": "owner", "role": "owner", "role_id": None},
            {"tenant_id": "t1", "user_id": "caller", "role": "caller", "role_id": "r-caller"},
            {"tenant_id": "t1", "user_id": "manager", "role": "caller", "role_id": "r-mgr"},
        ],
        "tenant_roles": [
            {"id": "r-caller", "tenant_id": "t1", "permissions": ["leads.view"]},
            {"id": "r-mgr", "tenant_id": "t1", "permissions": ["numbers.manage"]},
        ],
        "callers": [],
    })


@pytest.fixture(autouse=True)
def _fresh_cache():
    nc.invalidate_policy_cache()
    yield
    nc.invalidate_policy_cache()


def _send(db, user, typ):
    with patch("app.services.web_push.send_user_push"):
        notify.notify_user("t1", user, typ, "T", "M", db=db)


def test_unconfigured_alert_reaches_everyone_as_before():
    db = _db()
    _send(db, "owner", "lead_assigned")
    _send(db, "caller", "lead_assigned")
    assert db.bells() == [("owner", "lead_assigned"), ("caller", "lead_assigned")]


def test_unknown_type_behaves_as_today():
    db = _db(events={"something_else": False}, recipients={"something_else": ["owner"]})
    _send(db, "caller", "brand_new_type")
    assert db.bells() == [("caller", "brand_new_type")]


def test_off_alert_has_no_bell_and_no_push():
    db = _db(events={"callback_due": False})
    with patch("app.services.web_push.send_user_push") as push:
        notify.notify_user("t1", "owner", "callback_due", "T", "M", db=db)
    assert db.bells() == []
    push.assert_not_called()


@pytest.mark.parametrize("typ", ["intake_paid", "payment_received", "handover_new", "number_disconnected"])
def test_always_on_alerts_pass_even_when_an_old_save_says_off(typ):
    db = _db(events={typ: False})
    _send(db, "owner", typ)
    assert db.bells() == [("owner", typ)]


def test_owner_only_reaches_only_the_owner():
    db = _db(recipients={"booking_new": ["owner"]})
    _send(db, "owner", "booking_new")
    _send(db, "caller", "booking_new")
    assert db.bells() == [("owner", "booking_new")]


def test_team_reaches_everyone_and_assigned_reaches_the_person_addressed():
    db = _db(recipients={"booking_new": ["team"], "lead_replied": ["assigned"]})
    _send(db, "caller", "booking_new")
    _send(db, "caller", "lead_replied")
    assert db.bells() == [("caller", "booking_new"), ("caller", "lead_replied")]


def test_unknown_person_is_not_dropped():
    db = _db(recipients={"booking_new": ["owner"]})
    _send(db, "someone-new", "booking_new")
    assert db.bells() == [("someone-new", "booking_new")]


def test_pool_alert_respects_who_gets_it():
    db = _db(recipients={"handover_new": ["owner"]})
    db.rows["callers"] = [{"tenant_id": "t1", "user_id": "caller", "active": True, "status": "active"}]
    notify.notify_pool("t1", "handover_new", "T", "M", db=db)
    assert db.bells() == [("owner", "handover_new")]


def test_policy_is_cached_for_a_minute_and_saving_clears_it():
    db = _db()
    _send(db, "caller", "booking_new")
    db.rows["app_settings"].append({"tenant_id": "t1", "key": "alert_recipients", "value": json.dumps({"booking_new": ["owner"]})})
    _send(db, "caller", "booking_new")  # still the cached policy
    assert len(db.bells()) == 2
    nc.invalidate_policy_cache("t1")
    _send(db, "caller", "booking_new")
    assert len(db.bells()) == 2


def test_set_alert_applies_at_once():
    db = _db()
    _send(db, "caller", "booking_new")
    alert_catalog.set_alert(db, "t1", "booking_new", True, ["owner"])
    _send(db, "caller", "booking_new")
    assert len(db.bells()) == 1


def test_locked_alerts_cannot_be_switched_off():
    db = _db()
    with pytest.raises(ValueError):
        alert_catalog.set_alert(db, "t1", "handover_new", False)
    view = alert_catalog.list_alerts(db, "t1")["alerts"]
    locked = {a["key"] for a in view if a["locked"]}
    assert {"intake_paid", "handover_new", "number_disconnected"} <= locked
    assert "lead_replied" not in locked
    # locked still lists as on even if an older save said off
    db2 = _db(events={"intake_paid": False})
    assert next(a for a in alert_catalog.list_alerts(db2, "t1")["alerts"] if a["key"] == "intake_paid")["on"] is True


def test_push_allowed_ignores_off_for_always_on_only():
    cfg = {**nc._NOTIFICATION_CONFIG_DEFAULT, "events": {"intake_paid": False, "callback_due": False}}
    with patch.object(nc, "get_notification_config", return_value=cfg):
        assert nc.push_allowed("t1", "intake_paid") is True
        assert nc.push_allowed("t1", "callback_due") is False


# ── number disconnected ──

def test_disconnect_alerts_owner_and_number_managers_once_per_change():
    db = _db()
    row = {"id": "n1", "display_name": "Shop line", "meta_status": "CONNECTED"}
    with patch("app.services.web_push.send_user_push"):
        told = number_sync.alert_if_number_disconnected(db, "t1", row, "DISCONNECTED")
        again = number_sync.alert_if_number_disconnected(db, "t1", {**row, "meta_status": "DISCONNECTED"}, "DISCONNECTED")
    assert told == 2 and again == 0
    assert sorted(db.bells()) == [("manager", "number_disconnected"), ("owner", "number_disconnected")]


def test_connected_or_pending_status_does_not_alert():
    db = _db()
    for status in ("CONNECTED", "PENDING", None):
        assert number_sync.alert_if_number_disconnected(db, "t1", {"id": "n1", "meta_status": "CONNECTED"}, status) == 0
    assert db.bells() == []


def test_disconnect_alert_never_raises():
    class Broken:
        def table(self, *_a): raise RuntimeError("db down")
    assert number_sync.alert_if_number_disconnected(Broken(), "t1", {"id": "n1"}, "DISCONNECTED") == 0


def test_apply_snapshot_alerts_on_status_change():
    from app.services import number_sync as ns
    db = _db()
    db.rows["phone_numbers"] = []
    row = {"id": "n1", "number": "9199", "status": "active", "meta_status": "CONNECTED", "quality_rating": "green", "role": "primary"}
    with patch("app.services.web_push.send_user_push"):
        asyncio.run(ns.apply_meta_snapshot(db, "t1", row, {"status": "DISCONNECTED", "quality_rating": "GREEN"}, set(), "test"))
    assert ("owner", "number_disconnected") in db.bells()


# ── reply-feedback/mine ──

def test_my_feedback_returns_only_the_callers_marks():
    from app.services import ai_setup_report as rep
    db = FakeDB({"ai_reply_feedback": [
        {"tenant_id": "t1", "message_id": "11111111-1111-1111-1111-111111111111", "created_by": "u1", "reason": "rude", "note": "x"},
        {"tenant_id": "t1", "message_id": "11111111-1111-1111-1111-111111111111", "created_by": "u2", "reason": "wrong", "note": None},
        {"tenant_id": "t2", "message_id": "22222222-2222-2222-2222-222222222222", "created_by": "u1", "reason": "wrong", "note": None},
        {"tenant_id": "t1", "message_id": "33333333-3333-3333-3333-333333333333", "created_by": "u1", "reason": "too_long", "note": None},
    ]})
    ctx = {"tenant_id": "t1", "user_id": "u1"}
    assert rep.my_feedback(db, ctx, ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "99999999-9999-9999-9999-999999999999", "", "not-a-uuid"]) == {"11111111-1111-1111-1111-111111111111": {"reason": "rude", "note": "x"}}
    assert rep.my_feedback(db, ctx, []) == {}


def test_my_feedback_missing_table_is_empty():
    from app.services import ai_setup_report as rep

    class NoTable:
        def table(self, *_a): raise RuntimeError('relation "ai_reply_feedback" does not exist')
    assert rep.my_feedback(NoTable(), {"tenant_id": "t1", "user_id": "u1"}, ["m1"]) == {}


def test_mine_route_passes_ids_and_returns_marks():
    from app.routes import ai_setup
    from app.services import ai_setup_report as rep
    ctx = {"tenant_id": "t1", "user_id": "u1"}
    with patch.object(rep, "my_feedback", return_value={"a": {"reason": "wrong", "note": None}}) as f:
        out = asyncio.run(ai_setup.my_thumbs_down(message_ids="a, b,,c", ctx=ctx))
    assert out == {"marks": {"a": {"reason": "wrong", "note": None}}}
    assert f.call_args.args[2] == ["a", " b", "c"]


def test_per_person_alerts_always_reach_their_person():
    # "Who gets it" cannot drop the person a customer belongs to (an old "owner" save is ignored).
    db = _db(recipients={"lead_assigned": ["owner"], "lead_replied": ["owner"]})
    _send(db, "caller", "lead_assigned")
    _send(db, "caller", "lead_replied")
    assert db.bells() == [("caller", "lead_assigned"), ("caller", "lead_replied")]


def test_fixed_rows_ignore_a_who_change_and_say_so():
    db = _db()
    row = alert_catalog.set_alert(db, "t1", "callback_due", True, ["owner"])
    assert row["who_fixed"] is True and row["who"] == ["assigned"]
    rows = {a["key"]: a for a in alert_catalog.list_alerts(db, "t1")["alerts"]}
    assert rows["number_disconnected"]["who_fixed"] is True
    assert rows["booking_new"]["who_fixed"] is False


def test_a_failed_settings_read_is_not_cached_as_all_on():
    from app.services import notification_config as nc
    nc.invalidate_policy_cache()

    class Broken:
        def table(self, name):
            raise RuntimeError("blip")

    assert nc.delivery_allowed("t1", "owner", "booking_new", db=Broken()) is True  # fail open for this one call
    assert "t1" not in nc._policy_cache
