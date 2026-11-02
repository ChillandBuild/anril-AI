"""Regressions for the adversarial-review fixes on the astro bridge reply path:
ref parsing (follow-up suffix + non-uuid guard), monotonic reply dedupe,
claim rollback + staff alert on total send failure, and push reconciliation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.intake import (
    deliver_astro_reply,
    get_session_tenant_id,
    reconcile_pending_astro_pushes,
    session_ref_to_id,
)

SID = "11111111-2222-3333-4444-555555555555"
TENANT = "0f897915-2d34-4b67-8d69-f83f52e4fb6c"


class _Chain:
    def __init__(self, result, log, table):
        self._result = result
        self._log = log
        self._table = table

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            if name in ("update", "insert"):
                self._log.append((self._table, name, args[0] if args else None))
            return self

        return _record

    def execute(self):
        return self._result


class _SeqDb:
    """Routes each .table(name) call to the next preset result for that table,
    recording every update/insert payload for assertions."""

    def __init__(self, results_by_table):
        self._results = {k: list(v) for k, v in results_by_table.items()}
        self.writes = []

    def table(self, name):
        return _Chain(self._results[name].pop(0), self.writes, name)


def _res(data):
    m = MagicMock()
    m.data = data
    return m


def test_session_ref_to_id_accepts_bare_uuid_and_followup_suffix():
    assert session_ref_to_id(SID) == SID
    assert session_ref_to_id(f"{SID}::f1") == SID
    assert session_ref_to_id(f"{SID}::f12") == SID


def test_session_ref_to_id_rejects_garbage():
    assert session_ref_to_id("not-a-uuid") is None
    assert session_ref_to_id("not-a-uuid::f1") is None
    assert session_ref_to_id("") is None
    assert session_ref_to_id(None) is None
    assert session_ref_to_id(f"{SID}::g1") is None


def test_get_session_tenant_id_returns_none_for_garbage_without_touching_db():
    db = MagicMock()
    assert get_session_tenant_id("definitely-not-a-uuid", db=db) is None
    db.table.assert_not_called()


def test_get_session_tenant_id_resolves_followup_suffix():
    db = _SeqDb({"intake_sessions": [_res({"tenant_id": TENANT})]})
    assert get_session_tenant_id(f"{SID}::f2", db=db) == TENANT


def test_get_session_tenant_id_swallows_db_errors_to_none():
    db = MagicMock()
    db.table.side_effect = RuntimeError("connection reset")
    assert get_session_tenant_id(SID, db=db) is None


@pytest.mark.asyncio
async def test_nudge_send_failure_rolls_back_the_claim():
    """The claim is what stops a redelivery. If the nudge never went out, the
    customer does not know an answer exists, so a re-push must be able to try
    again rather than be dropped as a duplicate."""
    db = _SeqDb({
        "intake_sessions": [
            _res({"id": SID, "lead_id": "L1", "tenant_id": TENANT, "astro_last_reply_id": 7}),
            _res([{"id": SID}]),   # claim succeeds
            _res([{"id": SID}]),   # archive the answer text
            _res([{"id": SID}]),   # rollback
        ],
        "leads": [_res({"id": "L1", "phone": "+919345679286", "last_inbound_at": datetime.now(timezone.utc).isoformat()})],
    })
    with patch("app.services.ai_reply.send_whatsapp", new=AsyncMock(return_value=None)), \
         patch("app.services.intake._send_reply_ready_template",
               new=AsyncMock(side_effect=RuntimeError("template refused"))), \
         patch("app.services.intake._log_astro_message"), \
         patch("app.services.intake.notify_pool"), \
         patch("app.services.intake._astro_phone_number_id", return_value="pn1"), \
         patch("app.services.intake._compose_reply_nudge", new=AsyncMock(return_value="ready")):
        out = await deliver_astro_reply(
            {"external_ref": SID, "reply_id": 9, "reply_text": "your chart says..."},
            TENANT,
            db=db,
        )

    assert out["nudged"] is False
    updates = [p for t, op, p in db.writes if op == "update"]
    assert {"astro_last_reply_id": 9} in updates
    assert updates[-1] == {"astro_last_reply_id": 7}, "claim must roll back to the prior reply id"


@pytest.mark.asyncio
async def test_a_delivered_nudge_keeps_the_claim():
    db = _SeqDb({
        "intake_sessions": [
            _res({"id": SID, "lead_id": "L1", "tenant_id": TENANT, "astro_last_reply_id": None}),
            _res([{"id": SID}]),
            _res([{"id": SID}]),
            _res([{"id": SID}]),  # resolve_intake_session's status transition
        ],
        "leads": [_res({"id": "L1", "phone": "+919345679286", "last_inbound_at": datetime.now(timezone.utc).isoformat()})],
        "messages": [_res([{"id": "m1"}])],
    })
    with patch("app.services.ai_reply.send_whatsapp", new=AsyncMock(return_value="wamid.1")), \
         patch("app.services.intake._astro_phone_number_id", return_value="pn1"), \
         patch("app.services.intake._log_astro_message"), \
         patch("app.services.intake._compose_reply_nudge", new=AsyncMock(return_value="ready")):
        out = await deliver_astro_reply(
            {"external_ref": SID, "reply_id": 9, "reply_text": "hello"},
            TENANT,
            db=db,
        )

    assert out["nudged"] is True
    rollbacks = [p for t, op, p in db.writes if op == "update" and p == {"astro_last_reply_id": None}]
    assert not rollbacks, "a delivered nudge must keep the claim"
    assert any(
        op == "update" and p.get("status") == "resolved"
        for t, op, p in db.writes if t == "intake_sessions"
    ), "a delivered nudge must resolve the paid session"


@pytest.mark.asyncio
async def test_followup_suffix_ref_resolves_to_the_session():
    db = _SeqDb({
        "intake_sessions": [_res(None)],
    })
    out = await deliver_astro_reply(
        {"external_ref": f"{SID}::f1", "reply_id": 3, "reply_text": "x"}, TENANT, db=db
    )
    assert out["reason"] == "unknown_session"  # looked up (and missed) — did NOT crash on the suffix


@pytest.mark.asyncio
async def test_malformed_ref_is_a_clean_miss_not_an_exception():
    db = MagicMock()
    out = await deliver_astro_reply(
        {"external_ref": "zzz", "reply_id": 3, "reply_text": "x"}, TENANT, db=db
    )
    assert out["reason"] == "unknown_session"
    db.table.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_re_drives_unpushed_paid_sessions():
    session_row = {
        "id": SID, "tenant_id": TENANT, "lead_id": "L1",
        "collected_data": {}, "trigger_reason": "want consult", "amount_paise": 19900,
    }
    db = _SeqDb({
        "intake_sessions": [
            _res([session_row]),
            _res([{"id": SID}]),  # record_astro_bridge_ids update
        ],
        "leads": [_res({"id": "L1", "name": "Meena", "phone": "+919345679286"})],
    })
    bridge_response = {"question_id": 501, "horoscope_id": "HOR-AB12CD34", "astro_user_id": 9}
    with patch("app.services.astro_bridge.push_consultation", new=AsyncMock(return_value=bridge_response)) as push:
        pushed = await reconcile_pending_astro_pushes(db=db)

    assert pushed == 1
    assert push.await_count == 1
    updates = [p for t, op, p in db.writes if op == "update"]
    assert updates and updates[0]["astro_question_id"] == 501


@pytest.mark.asyncio
async def test_reconcile_survives_a_failing_session_and_continues():
    rows = [
        {"id": SID, "tenant_id": TENANT, "lead_id": "L1",
         "collected_data": {}, "trigger_reason": "a", "amount_paise": 100},
        {"id": "22222222-2222-3333-4444-555555555555", "tenant_id": TENANT, "lead_id": "L2",
         "collected_data": {}, "trigger_reason": "b", "amount_paise": 100},
    ]
    db = _SeqDb({
        "intake_sessions": [_res(rows), _res([{"id": rows[1]["id"]}])],
        "leads": [_res({"id": "L1", "phone": "+911111111111"}),
                  _res({"id": "L2", "phone": "+912222222222"})],
    })
    ok = {"question_id": 7}
    with patch(
        "app.services.astro_bridge.push_consultation",
        new=AsyncMock(side_effect=[RuntimeError("django down"), ok]),
    ):
        pushed = await reconcile_pending_astro_pushes(db=db)
    assert pushed == 1


def test_reconcile_job_is_registered_in_the_scheduler():
    import app.queue.tasks  # noqa: F401  (registers the periodic tasks)
    from app.queue.app import queue_app

    assert "astro-push-reconcile" in queue_app.tasks
