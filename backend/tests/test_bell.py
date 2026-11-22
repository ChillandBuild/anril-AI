"""Batch F bell: alert links, include_read window, hot-lead bell row."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import notify


class FakeQuery:
    """Records the chained calls and returns canned rows from execute()."""

    def __init__(self, db, table):
        self.db, self.table, self.ops, self.payload = db, table, [], None

    def _chain(self, name):
        def f(*a, **k):
            self.ops.append((name, a, k))
            return self
        return f

    def __getattr__(self, name):
        if name == "not_":
            self.ops.append(("not_", (), {}))
            return self
        if name in {"select", "eq", "in_", "gte", "lte", "like", "or_", "order", "limit", "is_", "update"}:
            return self._chain(name)
        raise AttributeError(name)

    def insert(self, row):
        self.payload = row
        self.ops.append(("insert", (row,), {}))
        return self

    def execute(self):
        self.db.log.append((self.table, list(self.ops)))
        if self.payload is not None:
            if self.table == "app_notifications" and self.db.insert_error:
                err = self.db.insert_error(self.payload)
                if err:
                    raise err
            self.db.inserted.append((self.table, self.payload))
            return SimpleNamespace(data=[self.payload])
        return SimpleNamespace(data=self.db.rows.get(self.table, []))


class FakeDB:
    def __init__(self, rows=None, insert_error=None):
        self.rows, self.insert_error = rows or {}, insert_error
        self.log, self.inserted = [], []

    def table(self, name):
        return FakeQuery(self, name)

    def notif_inserts(self):
        return [r for t, r in self.inserted if t == "app_notifications"]


def _no_push():
    return patch("app.services.notification_config.push_allowed", return_value=False)


# ---------- url stored + retry ----------

def test_notify_user_stores_push_url_as_link():
    db = FakeDB()
    with _no_push():
        notify.notify_user("t-1", "u-1", "lead_replied", "Reply", "Asha replied", db=db,
                           push_url="/dashboard/conversations?lead=L1")
    row = db.notif_inserts()[0]
    assert row["url"] == "/dashboard/conversations?lead=L1"


def test_notify_user_without_url_has_no_url_key():
    db = FakeDB()
    with _no_push():
        notify.notify_user("t-1", "u-1", "lead_assigned", "New", "Call Asha", db=db)
    assert "url" not in db.notif_inserts()[0]


def test_notify_user_retries_without_url_when_column_missing(caplog):
    notify._url_column_warned = False

    def err(row):
        if "url" in row:
            return Exception('column "url" of relation "app_notifications" does not exist')
        return None

    db = FakeDB(insert_error=err)
    with _no_push():
        notify.notify_user("t-1", "u-1", "lead_replied", "Reply", "x", db=db, push_url="/dashboard/x")
        notify.notify_user("t-1", "u-2", "lead_replied", "Reply", "x", db=db, push_url="/dashboard/x")
    rows = db.notif_inserts()
    assert [r["user_id"] for r in rows] == ["u-1", "u-2"]
    assert all("url" not in r for r in rows)
    assert sum("migration 315" in r.message for r in caplog.records) == 1  # warns once


def test_notify_user_other_errors_are_not_retried_and_never_raise():
    calls = []

    def err(row):
        calls.append(row)
        return Exception("connection reset")

    db = FakeDB(insert_error=err)
    notify.notify_user("t-1", "u-1", "lead_replied", "Reply", "x", db=db, push_url="/dashboard/x")
    assert len(calls) == 1


def test_notify_user_push_false_skips_push():
    db = FakeDB()
    with patch("app.services.notification_config.push_allowed", return_value=True) as allowed, \
            patch("app.services.web_push.send_user_push") as send:
        notify.notify_user("t-1", "u-1", "lead_hot", "Arun is Hot", "m", db=db, push=False)
    assert db.notif_inserts()
    allowed.assert_not_called()
    send.assert_not_called()


def test_notify_user_push_still_sent_by_default():
    db = FakeDB()
    with patch("app.services.notification_config.push_allowed", return_value=True), \
            patch("app.services.web_push.send_user_push") as send:
        notify.notify_user("t-1", "u-1", "lead_replied", "Reply", "m", db=db, push_url="/dashboard/x")
    send.assert_called_once()
    assert send.call_args.kwargs["url"] == "/dashboard/x"


def test_notify_pool_stores_url_and_handover_falls_back_to_lead_tag():
    rows = {"callers": [{"user_id": "u-c"}], "tenant_users": [{"user_id": "u-o"}]}
    db = FakeDB(rows)
    notify.notify_pool("t-1", "handover_new", "Handover", "Ravi needs a person [lead_id:L9]", db=db)
    got = db.notif_inserts()
    assert {r["user_id"] for r in got} == {"u-c", "u-o"}
    assert all(r["url"] == "/dashboard/conversations?lead=L9" for r in got)


def test_notify_pool_explicit_url_wins_and_other_types_get_none():
    rows = {"callers": [], "tenant_users": [{"user_id": "u-o"}]}
    db = FakeDB(rows)
    notify.notify_pool("t-1", "deal_double_payment", "Double", "m [lead_id:L1]", db=db, url="/dashboard/deals/orders/D1")
    notify.notify_pool("t-1", "intake_paid", "Paid", "m [lead_id:L1]", db=db)
    a, b = db.notif_inserts()
    assert a["url"] == "/dashboard/deals/orders/D1"
    assert "url" not in b


def test_notify_pool_retries_without_url_and_never_raises():
    def err(row):
        return Exception("Could not find the 'url' column of 'app_notifications' in the schema cache") if "url" in row else None

    db = FakeDB({"callers": [], "tenant_users": [{"user_id": "u-o"}]}, insert_error=err)
    notify.notify_pool("t-1", "handover_new", "H", "m [lead_id:L2]", db=db)
    assert len(db.notif_inserts()) == 1 and "url" not in db.notif_inserts()[0]
    notify.notify_pool("t-1", "x", "H", "m", db=MagicMock(table=MagicMock(side_effect=RuntimeError("down"))))


# ---------- include_read ----------

OWNER = {"tenant_id": "t-1", "role": "owner", "permissions": []}


def _list(include_read, rows, ctx=OWNER):
    from app.routes import notifications as routes
    db = FakeDB({"app_notifications": rows})
    with patch.object(routes, "get_supabase", return_value=db):
        res = asyncio.run(routes.list_notifications(
            include_read=include_read, ctx=ctx, user={"user_id": "u-1"}))
    return res, db.log[-1][1]


def _money_filtered(ops):
    return any(ops[i][0] == "not_" and ops[i + 1][0] == "in_" and ops[i + 1][1][0] == "type" for i in range(len(ops) - 1))


def test_list_default_is_unread_only_max_50():
    res, ops = _list(False, [{"id": "n1"}])
    assert res == {"data": [{"id": "n1"}]}
    names = [o[0] for o in ops]
    assert ("eq", ("is_read", False), {}) in ops
    assert ("limit", (50,), {}) in ops
    assert "or_" not in names
    assert ("eq", ("user_id", "u-1"), {}) in ops and ("eq", ("tenant_id", "t-1"), {}) in ops


def test_list_include_read_uses_7_day_window_newest_first_max_100():
    res, ops = _list(True, [{"id": "a"}, {"id": "b"}])
    assert len(res["data"]) == 2
    or_op = next(o for o in ops if o[0] == "or_")
    assert or_op[1][0].startswith("is_read.eq.false,created_at.gte.")
    assert ("limit", (100,), {}) in ops
    assert ("order", ("created_at",), {"desc": True}) in ops
    assert ("eq", ("is_read", False), {}) not in ops
    # still scoped to this user only
    assert ("eq", ("user_id", "u-1"), {}) in ops and ("eq", ("tenant_id", "t-1"), {}) in ops


def test_include_read_cutoff_is_about_seven_days_ago():
    from datetime import datetime, timedelta, timezone
    _, ops = _list(True, [])
    cutoff_txt = next(o for o in ops if o[0] == "or_")[1][0].split("created_at.gte.")[1]
    cutoff = datetime.strptime(cutoff_txt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - cutoff
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)


# ---------- hot lead bell row ----------

def test_hot_lead_adds_bell_row_for_each_owner_without_push():
    from app.services import whatsapp_notify as wn
    db = FakeDB({"tenant_users": [{"user_id": "o1"}, {"user_id": "o2"}], "app_notifications": []})
    with patch("app.services.notification_config.push_allowed", return_value=True), \
            patch("app.services.web_push.send_user_push") as send:
        wn.notify_owners_lead_hot(db, "t-1", {"id": "L1", "name": "Arun"})
    rows = db.notif_inserts()
    assert [r["user_id"] for r in rows] == ["o1", "o2"]
    assert rows[0]["type"] == "lead_hot" and rows[0]["title"] == "Arun is Hot"
    assert rows[0]["url"] == "/dashboard/conversations?lead=L1"
    assert "[lead_id:L1]" in rows[0]["message"]
    send.assert_not_called()


def test_hot_lead_dedupes_within_an_hour_per_owner():
    from app.services import whatsapp_notify as wn
    db = FakeDB({"tenant_users": [{"user_id": "o1"}, {"user_id": "o2"}],
                 "app_notifications": [{"user_id": "o1"}]})
    wn.notify_owners_lead_hot(db, "t-1", {"id": "L1", "name": "Arun"})
    assert [r["user_id"] for r in db.notif_inserts()] == ["o2"]
    # the dedupe lookup is time-boxed to the last hour and per lead
    ops = next(ops for t, ops in db.log if t == "app_notifications" and not any(o[0] == "insert" for o in ops))
    gte = next(o for o in ops if o[0] == "gte")
    assert gte[1][0] == "created_at"
    assert ("like", ("message", "%[lead_id:L1]%"), {}) in ops
    assert ("eq", ("type", "lead_hot"), {}) in ops


def test_hot_lead_without_name_and_without_owner():
    from app.services import whatsapp_notify as wn
    db = FakeDB({"tenant_users": [{"user_id": "o1"}], "app_notifications": []})
    with _no_push():
        wn.notify_owners_lead_hot(db, "t-1", {"id": "L2", "name": None})
    assert db.notif_inserts()[0]["title"] == "A lead is Hot"
    db2 = FakeDB({"tenant_users": []})
    wn.notify_owners_lead_hot(db2, "t-1", {"id": "L2", "name": "x"})
    assert db2.notif_inserts() == []


def test_hot_lead_never_raises():
    from app.services import whatsapp_notify as wn
    wn.notify_owners_lead_hot(MagicMock(table=MagicMock(side_effect=RuntimeError("db down"))), "t-1", {"id": "L1"})
    wn.notify_owners_lead_hot(FakeDB(), "t-1", {})
    wn.notify_owners_lead_hot(FakeDB(), "t-1", {"id": "L1"})


def test_process_due_alert_for_hot_lead_calls_bell_row_but_warm_does_not():
    from app.services import whatsapp_notify as wn
    for segment, expect in (("A", True), ("B", False)):
        db = MagicMock()
        alert = {"id": "a1", "tenant_id": "t-1", "lead_id": "L1", "to_segment": segment}
        lead = {"id": "L1", "name": "Arun", "phone": "+911", "segment": segment}
        template = {"id": "tp", "name": "hot", "language": "en", "body_text": "{{1}}"}

        def table(name, _lead=lead, _alert=alert, _tpl=template):
            t = MagicMock()
            if name == "pending_whatsapp_alerts":
                t.select.return_value.eq.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value.data = [_alert]
            elif name == "leads":
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [_lead]
            elif name == "lead_stage_events":
                t.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"to_segment": _lead["segment"]}]
            elif name == "message_templates":
                t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [_tpl]
            return t

        db.table.side_effect = table
        cfg = {"whatsapp_notifications": {"enabled": True, "template_id": "tp", "recipient_phones": ["+919"]}}
        with patch.object(wn, "get_supabase", return_value=db), \
                patch.object(wn, "get_notification_config", return_value=cfg), \
                patch("app.services.blocked_guard.lead_is_blocked_sync", return_value=False), \
                patch.object(wn, "_build_components", return_value=[{"type": "body"}]), \
                patch.object(wn, "_dispatch_alerts", new=MagicMock(side_effect=lambda *a, **k: _done())), \
                patch.object(wn, "notify_owners_lead_hot") as hot:
            asyncio.run(wn.process_due_whatsapp_alerts())
        assert hot.called is expect


async def _done():
    return None


# ---------- money alerts need deals.view ----------

def test_money_alerts_dropped_for_people_without_deals_view():
    from app.routes.notifications import MONEY_ALERT_TYPES
    for include_read in (False, True):
        caller = {"tenant_id": "t-1", "role": "caller", "permissions": ["leads.view"]}
        _, ops = _list(include_read, [], ctx=caller)
        assert _money_filtered(ops)
        in_op = next(o for i, o in enumerate(ops) if o[0] == "in_")
        assert set(in_op[1][1]) == set(MONEY_ALERT_TYPES)


def test_money_alerts_kept_for_owner_and_deals_view():
    for ctx in (OWNER,
                {"tenant_id": "t-1", "role": "caller", "permissions": ["deals.view"]},
                {"tenant_id": "t-1", "role": "caller", "permissions": ["deals.manage"]}):
        for include_read in (False, True):
            _, ops = _list(include_read, [], ctx=ctx)
            assert not _money_filtered(ops)


def test_money_type_list_matches_the_frontend_money_category():
    import re
    from pathlib import Path
    from app.routes.notifications import MONEY_ALERT_TYPES
    src = (Path(__file__).resolve().parents[2] / "frontend/components/bell/alertKinds.ts").read_text()
    front = set(re.findall(r'^\s{2}(\w+): \{ category: "money"', src, re.M))
    assert front == set(MONEY_ALERT_TYPES)
