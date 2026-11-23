"""Follow-up steps in days (reengagement_steps with delay_hours >= 24): validation, send window,
one-a-day rule, converted skip, and the plain reason written on failed rows."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role
from app.routes import reengagement as routes
from app.services import reengagement_service as svc
from tests.fake_supabase import FakeSupabase

T, OTHER = "t1", "t2"
# 2026-11-22 is a Sunday. IST = UTC + 5:30.
MON_NOON_IST = datetime(2026, 11, 23, 6, 30, tzinfo=timezone.utc)
MON_9AM_IST = datetime(2026, 11, 23, 3, 30, tzinfo=timezone.utc)
MON_9PM_IST = datetime(2026, 11, 23, 15, 30, tzinfo=timezone.utc)
SUN_NOON_IST = datetime(2026, 11, 22, 6, 30, tzinfo=timezone.utc)
SAT_NOON_IST = datetime(2026, 11, 21, 6, 30, tzinfo=timezone.utc)


@pytest.fixture
def db():
    return FakeSupabase()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/reengagement")
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "owner", "permissions": []}
    with patch.object(routes, "get_supabase", return_value=db):
        yield TestClient(app)


def _tpl(db, name, status="APPROVED", tenant=T):
    return db.add("message_templates", tenant_id=tenant, name=name, language="en", status=status, body_text="Hi")


def _body(delay, message_type="template", template="promo", **kw):
    return {"type": "inbound", "delay_hours": delay, "target_segments": ["Hot"], "message_type": message_type,
            "message_content": kw.pop("message_content", None), "template_name": template, **kw}


# ---------------------------------------------------------------- validation

def test_day_step_with_free_text_is_refused(client, db):
    r = client.post("/api/v1/reengagement/steps", json=_body(48, "freeform", None, message_content="hi"))
    assert r.status_code == 400
    assert r.json()["detail"] == "After 24 hours WhatsApp only allows an approved template. Pick one."


def test_day_step_with_unapproved_template_is_refused(client, db):
    _tpl(db, "promo", status="PENDING")
    r = client.post("/api/v1/reengagement/steps", json=_body(72))
    assert r.status_code == 400
    assert "approved template" in r.json()["detail"]


def test_day_step_with_other_tenants_template_is_refused(client, db):
    _tpl(db, "promo", tenant=OTHER)
    assert client.post("/api/v1/reengagement/steps", json=_body(72)).status_code == 400


def test_day_step_with_approved_template_is_saved(client, db):
    _tpl(db, "promo")
    r = client.post("/api/v1/reengagement/steps", json=_body(72))
    assert r.status_code == 200
    assert db.rows("reengagement_steps")[0]["delay_hours"] == 72


def test_exactly_24_hours_counts_as_a_day_step(client, db):
    assert client.post("/api/v1/reengagement/steps", json=_body(24, "freeform", None, message_content="hi")).status_code == 400


def test_longest_wait_is_30_days(client, db):
    _tpl(db, "promo")
    assert client.post("/api/v1/reengagement/steps", json=_body(720)).status_code == 200
    assert client.post("/api/v1/reengagement/steps", json=_body(721)).status_code == 400
    assert client.post("/api/v1/reengagement/steps", json=_body(0)).status_code == 400


def test_under_24_hours_is_unchanged(client, db):
    # free text, no template needed, nothing looked up
    r = client.post("/api/v1/reengagement/steps", json=_body(2, "freeform", None, message_content="hi"))
    assert r.status_code == 200
    # a template step under 24h need not even be approved (today's rule)
    assert client.post("/api/v1/reengagement/steps", json=_body(23, "template", "whatever")).status_code == 200


def test_update_applies_the_same_rule(client, db):
    _tpl(db, "promo")
    sid = client.post("/api/v1/reengagement/steps", json=_body(2, "freeform", None, message_content="hi")).json()["id"]
    patch_body = {k: v for k, v in _body(48, "freeform", None, message_content="hi").items() if k not in ("type",)}
    assert client.patch(f"/api/v1/reengagement/steps/{sid}", json=patch_body).status_code == 400
    ok = {k: v for k, v in _body(48).items() if k != "type"}
    assert client.patch(f"/api/v1/reengagement/steps/{sid}", json=ok).status_code == 200


def test_view_only_person_cannot_create(db):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/reengagement")
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "staff", "permissions": ["leads.view"]}
    with patch.object(routes, "get_supabase", return_value=db):
        c = TestClient(app)
        assert c.post("/api/v1/reengagement/steps", json=_body(2, "freeform", None, message_content="hi")).status_code == 403
        assert c.get("/api/v1/reengagement/steps").status_code == 200


# ---------------------------------------------------------------- runtime

@pytest.fixture
def engine(db):
    class Picker:
        def __init__(self, _t): ...
        def next(self, prefer_meta_id=None):
            return {"id": "n1", "meta_phone_number_id": "p1"}
    send = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})
    with patch.object(svc, "SenderPicker", Picker), patch.object(svc, "template_status", return_value="APPROVED"), \
         patch.object(svc, "send_template_message", new=send), patch.object(svc, "ai_replies_allowed", return_value=True):
        svc._NO_SENDER_UNTIL.clear()
        yield send


def _step(db, hours=48, **kw):
    return db.add("reengagement_steps", tenant_id=T, type="inbound", delay_hours=hours, target_segments=["Hot"],
                  message_type="template", template_name="promo", **kw)


def _lead(db, **kw):
    return db.add("leads", tenant_id=T, name="Asha", phone="9199", segment="Hot", **kw)


async def _run(step, lead, db, now):
    with patch.object(svc, "utcnow", return_value=now):
        return await svc._send_reengagement(db, T, lead, step)


@pytest.mark.asyncio
async def test_day_step_sends_inside_window(db, engine):
    ok = await _run(_step(db), _lead(db), db, MON_NOON_IST)
    assert ok is True and engine.await_count == 1
    assert db.rows("reengagement_logs")[0]["status"] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("now", [SUN_NOON_IST, MON_9PM_IST, MON_9AM_IST])
async def test_day_step_waits_outside_window_without_a_log_row(db, engine, now):
    ok = await _run(_step(db), _lead(db), db, now)
    assert ok is False
    engine.assert_not_awaited()
    assert db.rows("reengagement_logs") == []


@pytest.mark.asyncio
async def test_saturday_is_allowed(db, engine):
    assert await _run(_step(db), _lead(db), db, SAT_NOON_IST) is True


@pytest.mark.asyncio
async def test_under_24h_step_ignores_the_window(db, engine):
    ok = await _run(_step(db, hours=2), _lead(db, last_inbound_at=SUN_NOON_IST.isoformat()), db, SUN_NOON_IST)
    assert ok is True  # a Sunday: only day-steps are held back


@pytest.mark.asyncio
async def test_one_day_step_per_lead_per_ist_day(db, engine):
    lead = _lead(db)
    first, second = _step(db, 48), _step(db, 72)
    assert await _run(first, lead, db, MON_NOON_IST) is True
    db.rows("reengagement_logs")[0]["sent_at"] = MON_NOON_IST.isoformat()
    assert await _run(second, lead, db, MON_NOON_IST) is False
    assert engine.await_count == 1 and len(db.rows("reengagement_logs")) == 1  # waits, no log row
    # next day it goes
    tuesday = datetime(2026, 11, 24, 6, 30, tzinfo=timezone.utc)
    assert await _run(second, lead, db, tuesday) is True


@pytest.mark.asyncio
async def test_short_step_sent_today_does_not_block_a_day_step(db, engine):
    lead = _lead(db, last_inbound_at=MON_NOON_IST.isoformat())
    short = _step(db, 2)
    db.add("reengagement_logs", tenant_id=T, lead_id=lead["id"], step_id=short["id"], status="sent",
           sent_at=MON_NOON_IST.isoformat())
    assert await _run(_step(db, 48), lead, db, MON_NOON_IST) is True


@pytest.mark.asyncio
async def test_converted_lead_is_skipped_without_a_log_row(db, engine):
    ok = await _run(_step(db), _lead(db, converted_at="2026-11-01T00:00:00+00:00"), db, MON_NOON_IST)
    assert ok is False
    engine.assert_not_awaited()
    assert db.rows("reengagement_logs") == []


@pytest.mark.asyncio
async def test_failed_send_writes_plain_reason(db, engine):
    engine.side_effect = Exception('Meta error {"error": {"code": 131047, "message": "Re-engagement message"}}')
    ok = await _run(_step(db), _lead(db), db, MON_NOON_IST)
    assert ok is False
    log = db.rows("reengagement_logs")[0]
    assert log["status"] == "failed"
    assert log["reason"].startswith("More than 24 hours since their last message")


@pytest.mark.asyncio
async def test_skipped_window_row_has_a_reason(db, engine):
    step = db.add("reengagement_steps", tenant_id=T, type="inbound", delay_hours=2, target_segments=["Hot"],
                  message_type="freeform", message_content="hi")
    lead = _lead(db, last_inbound_at="2026-01-01T00:00:00+00:00")
    assert await _run(step, lead, db, MON_NOON_IST) is False
    log = db.rows("reengagement_logs")[0]
    assert log["status"] == "skipped_window" and "24 hours" in log["reason"]


@pytest.mark.asyncio
async def test_log_is_written_even_if_reason_column_is_missing(db, engine):
    engine.side_effect = Exception("boom")
    real_table = db.table

    def table(name):
        q = real_table(name)
        if name == "reengagement_logs":
            orig = q.insert

            def insert(payload):
                if "reason" in payload:
                    raise Exception("column reengagement_logs.reason does not exist")
                return orig(payload)
            q.insert = insert
        return q

    with patch.object(db, "table", side_effect=table):
        await _run(_step(db), _lead(db), db, MON_NOON_IST)
    assert db.rows("reengagement_logs")[0]["status"] == "failed"


# ---------------------------------------------------------------- every page of leads (bug: 1000-row cap)

@pytest.mark.asyncio
async def test_inbound_step_reaches_people_past_the_first_1000(db):
    """A business with more than 1000 quiet leads used to have everyone past row 1000 skipped silently."""
    db.max_rows = 1000
    db.add("reengagement_steps", tenant_id=T, type="inbound", delay_hours=2, target_segments=["Hot"],
           message_type="template", template_name="promo")
    old = "2026-11-20T00:00:00+00:00"
    for i in range(1205):
        db.add("leads", tenant_id=T, name=f"L{i}", phone=f"91{i:08d}", segment="Hot", last_inbound_at=old)
    db.add("leads", tenant_id=T, name="Cold", phone="9100", segment="Cold", last_inbound_at=old)
    db.add("leads", tenant_id=T, name="Fresh", phone="9101", segment="Hot", last_inbound_at="2026-11-23T06:00:00+00:00")
    seen = []

    async def fake_send(_db, _t, lead, _step):
        seen.append(lead["name"])
        return True

    with patch.object(svc, "get_supabase", return_value=db), patch.object(svc, "utcnow", return_value=MON_NOON_IST), \
         patch.object(svc, "_send_reengagement", new=fake_send), \
         patch.object(svc, "_already_processed_lead_ids", return_value=set(), create=True):
        await svc.process_due_reengagements()
    assert len(seen) == 1205
    assert "Cold" not in seen and "Fresh" not in seen


def test_campaign_reply_before_the_migration_is_a_plain_503(client, db):
    _tpl(db, "promo")
    real = db.table

    def table(name):
        t = real(name)
        if name == "reengagement_steps":
            class Boom:
                def insert(self, *_a, **_k):
                    raise RuntimeError('new row violates check constraint "reengagement_steps_type_check" (23514)')
            return Boom()
        return t

    body = _body(48)
    body["type"] = "campaign_reply"
    with patch.object(db, "table", table):
        r = client.post("/api/v1/reengagement/steps", json=body)
    assert r.status_code == 503
    assert "isn't switched on" in r.json()["detail"]
