"""Regression: a STOP reply must show on the campaign in Broadcast history.

2026-11-25: a lead replied STOP to "kelir_host_registration_invitation"; the lead was put on
Said stop, but the campaign never counted it. The webhook's write to broadcast_recipients
included fail_reason, a column missing in prod, and its fallback ALSO included fail_reason, so
both writes failed and opted_out_at (what history counts) was never set.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes import webhook


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload = db, table, None, None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload, **_k):
        self.op, self.payload = "upsert", payload
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def __getattr__(self, _name):  # eq / order / limit / in_ ... are no-ops
        return lambda *a, **k: self

    def execute(self):
        if self.table == "broadcast_recipients" and self.op == "select":
            return _Res([{"id": "r1", "broadcast_id": "b1", "tag_id": None, "created_at": "2026-11-24T07:55:56+00:00"}])
        if self.table == "broadcast_recipients" and self.op == "update":
            if "fail_reason" in self.payload:  # column missing, like prod before the fix
                raise Exception("column broadcast_recipients.fail_reason does not exist")
            self.db.recipient_updates.append(self.payload)
        return _Res([])


class _DB:
    def __init__(self):
        self.recipient_updates: list[dict] = []

    def table(self, name):
        return _Q(self, name)


def test_stop_reply_still_stamps_campaign_row_when_fail_reason_column_missing(monkeypatch):
    import app.services.said_stop as said_stop
    monkeypatch.setattr(said_stop, "record_source", lambda *a, **k: None)
    db = _DB()
    asyncio.run(webhook._record_per_broadcast_opt_out("lead1", "+916382546876", "t1", db))
    assert len(db.recipient_updates) == 1
    row = db.recipient_updates[0]
    assert row["opted_out_at"]
    # The message really went out: the row stays 'sent' so sent/delivered/opened don't drop.
    assert "send_status" not in row


def test_said_stop_keeps_sent_delivered_opened():
    """A person who read the campaign and then said stop is counted as opened AND said stop."""
    from app.routes import upload

    recipients = [
        {"phone": "+911", "name": "A", "send_status": "sent", "lead_id": "L1",
         "created_at": "2026-11-24T07:55:00+00:00", "opted_out_at": "2026-11-24T10:15:00+00:00"},
        {"phone": "+912", "name": "B", "send_status": "sent", "lead_id": "L2",
         "created_at": "2026-11-24T07:55:00+00:00", "opted_out_at": None},
        # On Said stop before this campaign: never sent, stays out of sent.
        {"phone": "+913", "name": "C", "send_status": "opted_out_skip", "lead_id": "L3",
         "created_at": "2026-11-24T07:55:00+00:00", "opted_out_at": None, "fail_reason": "opted_out"},
    ]
    msgs = [{"lead_id": "L1", "delivery_status": "read", "created_at": "2026-11-24T07:55:01+00:00"},
            {"lead_id": "L2", "delivery_status": "delivered", "created_at": "2026-11-24T07:55:01+00:00"}]

    class Q:
        def __init__(self, t):
            self.t = t

        def __getattr__(self, _n):
            return lambda *a, **k: self

        def execute(self):
            if self.t == "broadcast_recipients":
                return _Res(recipients)
            if self.t == "messages":
                return _Res(msgs)
            return _Res([])

    class DB:
        def table(self, t):
            return Q(t)

    out = upload._classify_broadcast_outcomes(DB(), "t1", "b1", "2026-11-24T07:55:00+00:00")
    c = out["counts"]
    assert (c["sent"], c["delivered"], c["opened"], c["opted_out"], c["failed"]) == (2, 2, 1, 2, 0)
    # The Delivered / Opened CSVs come from the same pass, so they match the cards.
    reached = {r["phone"]: r for r in out["reached"]}
    assert set(reached) == {"+911", "+912"}  # delivered card = 2
    assert [p for p, r in reached.items() if r["status"] == "opened"] == ["+911"]  # opened card = 1
    assert reached["+911"]["said_stop_at"] and not reached["+912"]["said_stop_at"]
