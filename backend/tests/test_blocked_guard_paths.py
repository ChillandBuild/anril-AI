"""Full block, send path by send path (the central guard itself is in test_blocked_guard.py)."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services import auto_messages, automation_guards, blocked_guard, deals, notify, sms_campaigns
from app.services.blocked_guard import BLOCKED_DETAIL
from tests.fake_supabase import FakeSupabase
from tests.test_blocked_guard import FakeHttp, NOW, PHONE, T1, T2, http, make_db, use_db  # noqa: F401 (http = fixture)

LEAD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def blocked_lead(**extra) -> dict:
    return {"id": LEAD, "tenant_id": T1, "phone": PHONE, "blocked_at": NOW, "source": "whatsapp", **extra}


# ---------------------------------------------------------------- staff reply / compose

@pytest.mark.asyncio
async def test_staff_reply_to_a_blocked_chat_is_refused_with_409(monkeypatch):
    from app.routes import leads
    HumanMessage = leads.HumanMessage
    db = make_db(blocked_lead())
    monkeypatch.setattr(leads, "get_supabase", lambda: db)
    sent = AsyncMock(return_value="wamid.1")
    monkeypatch.setattr(leads, "send_whatsapp", sent)
    with pytest.raises(HTTPException) as err:
        await leads.send_human_message(LEAD, HumanMessage(content="hello"), {"tenant_id": T1})
    assert err.value.status_code == 409
    assert err.value.detail == "This person is blocked. Unblock to reply."
    sent.assert_not_awaited()
    assert db.rows("messages") == []  # nothing saved as "sent"


@pytest.mark.asyncio
async def test_staff_reply_to_an_unblocked_chat_still_sends(monkeypatch):
    from app.routes import leads
    HumanMessage = leads.HumanMessage
    db = make_db(blocked_lead(blocked_at=None))
    monkeypatch.setattr(leads, "get_supabase", lambda: db)
    sent = AsyncMock(return_value="wamid.1")
    monkeypatch.setattr(leads, "send_whatsapp", sent)
    await leads.send_human_message(LEAD, HumanMessage(content="hello"), {"tenant_id": T1})
    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_blocked_lead_of_another_business_does_not_stop_this_reply(monkeypatch):
    from app.routes import leads
    HumanMessage = leads.HumanMessage
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    db = make_db(blocked_lead(), {"id": other, "tenant_id": T2, "phone": PHONE, "blocked_at": None, "source": "whatsapp"})
    monkeypatch.setattr(leads, "get_supabase", lambda: db)
    sent = AsyncMock(return_value="wamid.1")
    monkeypatch.setattr(leads, "send_whatsapp", sent)
    await leads.send_human_message(other, HumanMessage(content="hello"), {"tenant_id": T2})
    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_compose_to_a_blocked_number_is_refused_with_409(monkeypatch):
    from app.routes import leads
    use_db(monkeypatch, make_db(blocked_lead()))
    body = leads.ComposeMessage(phone=PHONE, content="hello")
    with pytest.raises(HTTPException) as err:
        await leads.compose_new_message(body, None, {"tenant_id": T1})
    assert err.value.status_code == 409


# ---------------------------------------------------------------- broadcast / Reach audience

def test_the_custom_broadcast_never_targets_a_blocked_person(monkeypatch):
    from app.routes import leads
    ok = {"id": "l1", "tenant_id": T1, "phone": "919000000001", "opt_in_source": "web", "blocked_at": None}
    bad = {"id": "l2", "tenant_id": T1, "phone": PHONE, "opt_in_source": "web", "blocked_at": NOW}
    db = make_db(ok, bad)
    monkeypatch.setattr(leads, "_filtered_leads_query", lambda db_, ctx, f, columns="*", **k: db.table("leads").select(columns))
    matching, targets, _ = leads._broadcast_targets(db, {"tenant_id": T1}, leads.LeadFilters())
    assert [t["id"] for t in targets] == ["l1"] and matching == 1


@pytest.mark.asyncio
async def test_a_template_broadcast_send_to_a_blocked_person_sends_nothing(monkeypatch, http):
    from app.services import meta_cloud
    use_db(monkeypatch, make_db(blocked_lead()))
    with pytest.raises(HTTPException) as err:
        await meta_cloud.send_template_message(PHONE, "offer", "en", tenant_id=T1)
    assert err.value.status_code == 409 and http.posts == []


# ---------------------------------------------------------------- Auto-Messages

def _auto_message_db(phone=PHONE):
    db = FakeSupabase()
    db.add("auto_message_rules", id="r1", tenant_id=T1, enabled=True, template_id="t1", variables=[])
    db.add("message_templates", id="t1", tenant_id=T1, name="welcome", language="en", status="APPROVED", body_text="Hi")
    return db, db.add("auto_message_sends", tenant_id=T1, phone=phone, status="queued", rule_id="r1", source="website")


@pytest.mark.asyncio
async def test_an_auto_message_to_a_blocked_person_is_skipped_not_sent(monkeypatch, http):
    use_db(monkeypatch, make_db(blocked_lead()))
    monkeypatch.setattr("app.services.automation_guards.instant_template_allowed", lambda *a, **k: True)
    db, row = _auto_message_db()
    assert await auto_messages.send_one(db, row) is False
    saved = db.rows("auto_message_sends")[0]
    assert (saved["status"], saved["reason"]) == ("skipped", "blocked")
    assert http.posts == []


@pytest.mark.asyncio
async def test_an_auto_message_to_an_unblocked_person_is_sent(monkeypatch, http):
    use_db(monkeypatch, make_db(blocked_lead(blocked_at=None)))
    monkeypatch.setattr("app.services.automation_guards.instant_template_allowed", lambda *a, **k: True)
    db, row = _auto_message_db()
    assert await auto_messages.send_one(db, row) is True
    assert db.rows("auto_message_sends")[0]["status"] == "sent" and len(http.posts) == 1


@pytest.mark.asyncio
async def test_an_auto_message_for_the_same_number_in_another_business_is_sent(monkeypatch, http):
    use_db(monkeypatch, make_db(blocked_lead(tenant_id=T2)))  # blocked in business 2 only
    monkeypatch.setattr("app.services.automation_guards.instant_template_allowed", lambda *a, **k: True)
    db, row = _auto_message_db()
    assert await auto_messages.send_one(db, row) is True


# ---------------------------------------------------------------- payment link, scheduled template, follow-ups

@pytest.mark.asyncio
async def test_a_payment_link_is_made_but_not_sent_to_a_blocked_person(monkeypatch):
    db = make_db(blocked_lead())
    use_db(monkeypatch, db)
    db.add("deals", id="d-1", tenant_id=T1, lead_id=LEAD, deal_number=7, stage="awaiting_payment", total_paise=129900,
           payment_link="https://rzp.io/old", razorpay_payment_link_id="plink_old",
           link_expires_at="2099-01-01T00:00:00+00:00")
    db.add("deal_items", deal_id="d-1", tenant_id=T1, name="Earbuds", qty=1, line_total_paise=129900)
    sent = AsyncMock(return_value="wamid.1")
    with patch("app.services.ai_reply.send_whatsapp", sent):
        out = await deals.send_payment_link(T1, "d-1", db=db)
    assert out["payment_link"] == "https://rzp.io/old" and out["message_sent"] is False
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_payment_link_to_an_unblocked_person_is_sent(monkeypatch):
    db = make_db(blocked_lead(blocked_at=None))
    use_db(monkeypatch, db)
    db.add("deals", id="d-1", tenant_id=T1, lead_id=LEAD, deal_number=7, stage="awaiting_payment", total_paise=129900,
           payment_link="https://rzp.io/old", razorpay_payment_link_id="plink_old",
           link_expires_at="2099-01-01T00:00:00+00:00")
    db.add("deal_items", deal_id="d-1", tenant_id=T1, name="Earbuds", qty=1, line_total_paise=129900)
    sent = AsyncMock(return_value="wamid.1")
    with patch("app.services.ai_reply.send_whatsapp", sent):
        out = await deals.send_payment_link(T1, "d-1", db=db)
    assert out["message_sent"] is True
    sent.assert_awaited_once()


def test_automated_outbound_helper_refuses_a_blocked_lead():
    assert automation_guards.lead_blocks_automated_outbound({"phone": PHONE, "blocked_at": NOW}) == "blocked"
    assert automation_guards.lead_blocks_automated_outbound({"phone": PHONE, "blocked_at": None}) is None


@pytest.mark.asyncio
async def test_a_scheduled_template_for_a_person_blocked_later_is_skipped(monkeypatch, http):
    from app.services import scheduled_templates as sched
    db = make_db(blocked_lead())
    db.add(sched.TABLE, id="s1", tenant_id=T1, lead_id=LEAD, status="scheduled", template_id="t1", variables=[],
           created_by=None)
    monkeypatch.setattr("app.services.notify.notify_user", lambda *a, **k: None)
    assert await sched.send_one(db, db.rows(sched.TABLE)[0]) is False
    saved = db.rows(sched.TABLE)[0]
    assert saved["status"] == "skipped" and saved["reason"] == BLOCKED_DETAIL
    assert http.posts == []


def test_the_call_details_share_card_is_unavailable_for_a_blocked_lead(monkeypatch):
    from app.services import call_details_share as share
    monkeypatch.setattr(share, "get_setting", lambda *a, **k: "x")
    assert share._whatsapp_ready(T1, {"phone": PHONE, "blocked_at": NOW}) is False
    assert share._whatsapp_ready(T1, {"phone": PHONE, "blocked_at": None}) is True


@pytest.mark.asyncio
async def test_call_details_share_send_is_refused_for_a_blocked_lead(monkeypatch):
    from app.services import call_details_share as share
    from datetime import datetime, timezone
    db = make_db(blocked_lead(opted_out=False, last_inbound_at=NOW, name="Asha"))
    with pytest.raises(share.ShareError) as err:
        await share.send_details(db, T1, LEAD, text="hello", template_id=None, variables=[],
                                 now=datetime.now(timezone.utc))
    assert str(err.value) == BLOCKED_DETAIL


# ---------------------------------------------------------------- SMS

def test_an_sms_to_a_blocked_number_is_skipped_whichever_list_it_came_from():
    db = make_db(blocked_lead(opted_out=False))
    use_db_fn = blocked_guard.get_supabase
    for source in ("leads", "contacts", "numbers"):
        row = {"tenant_id": T1, "phone": "+91 98765 43210", "lead_id": LEAD, "contact_id": None}
        with patch.object(blocked_guard, "get_supabase", lambda: db):
            blocked_guard.invalidate()
            assert sms_campaigns._recipient_skip(db, row, {"source": source, "template_type": "service"}) == "Blocked"
    assert use_db_fn  # (kept: the conftest stub is restored by pytest)


def test_an_sms_to_a_number_blocked_in_another_business_is_not_skipped():
    db = make_db(blocked_lead(tenant_id=T2))
    row = {"tenant_id": T1, "phone": PHONE, "lead_id": None, "contact_id": None}
    with patch.object(blocked_guard, "get_supabase", lambda: db):
        blocked_guard.invalidate()
        assert sms_campaigns._recipient_skip(db, row, {"source": "numbers", "template_type": "service"}) is None


# ---------------------------------------------------------------- inbound: no alerts, no handover

def _caller_db(blocked_at):
    db = FakeSupabase()
    db.add("leads", id=LEAD, tenant_id=T1, name="Asha", assigned_to="c1", blocked_at=blocked_at)
    db.add("callers", id="c1", tenant_id=T1, user_id="u1")
    return db


def test_a_blocked_persons_message_alerts_nobody(monkeypatch):
    alerts = []
    monkeypatch.setattr(notify, "notify_user", lambda *a, **k: alerts.append(a))
    notify.notify_assigned_caller_of_reply(LEAD, T1, db=_caller_db(NOW))
    assert alerts == []


def test_an_unblocked_persons_message_still_alerts_the_caller(monkeypatch):
    alerts = []
    monkeypatch.setattr(notify, "notify_user", lambda *a, **k: alerts.append(a))
    notify.notify_assigned_caller_of_reply(LEAD, T1, db=_caller_db(None))
    assert len(alerts) == 1


def test_a_blocked_person_raises_no_handover_and_no_pool_alert(monkeypatch):
    from app.services import ai_reply
    db = make_db(blocked_lead())
    pool = []
    monkeypatch.setattr("app.services.notify.notify_pool", lambda *a, **k: pool.append(a))
    ai_reply._trigger_chat_escalation(LEAD, "asked for a human", T1, None, db)
    assert db.rows("chat_handovers") == [] and pool == []
    assert db.rows("leads")[0].get("needs_human_attention") in (None, False)


def test_an_unblocked_person_still_raises_a_handover(monkeypatch):
    from app.services import ai_reply
    db = make_db(blocked_lead(blocked_at=None))
    monkeypatch.setattr("app.services.notify.notify_pool", lambda *a, **k: None)
    monkeypatch.setattr("app.services.whatsapp_notify.queue_escalation_whatsapp_alert", lambda *a, **k: None)
    ai_reply._trigger_chat_escalation(LEAD, "asked for a human", T1, None, db)
    assert len(db.rows("chat_handovers")) == 1


@pytest.mark.asyncio
async def test_a_queued_team_alert_about_a_blocked_person_is_cancelled_not_sent(monkeypatch):
    from app.services import whatsapp_notify as wn
    db = make_db(blocked_lead())
    db.add("pending_whatsapp_alerts", id="a1", tenant_id=T1, lead_id=LEAD, to_segment="A", from_segment="B",
           status="pending", send_at="2020-01-01T00:00:00+00:00", alert_type="segment")
    monkeypatch.setattr(wn, "get_supabase", lambda: db)
    sent = AsyncMock()
    monkeypatch.setattr(wn, "send_template_message", sent)
    await wn.process_due_whatsapp_alerts()
    assert db.rows("pending_whatsapp_alerts")[0]["status"] == "cancelled"
    sent.assert_not_awaited()


# ---------------------------------------------------------------- the block toggle

@pytest.mark.asyncio
async def test_blocking_closes_open_handovers_and_the_new_block_takes_effect_at_once(monkeypatch):
    from app.routes import leads
    db = make_db({"id": LEAD, "tenant_id": T1, "phone": PHONE, "blocked_at": None, "needs_human_attention": True})
    db.add("chat_handovers", id="h1", tenant_id=T1, lead_id=LEAD, status="pending")
    monkeypatch.setattr(leads, "get_supabase", lambda: db)
    monkeypatch.setattr(leads, "actor_name", lambda *a, **k: "Priya")
    use_db(monkeypatch, db)
    assert await blocked_guard.is_blocked(T1, PHONE) is False  # cached: nobody blocked yet
    await leads.toggle_block(LEAD, {"tenant_id": T1, "user_id": "u1"})
    assert await blocked_guard.is_blocked(T1, PHONE) is True   # no 60-second wait in this process
    assert db.rows("chat_handovers")[0]["status"] == "resolved"
    assert db.rows("leads")[0]["needs_human_attention"] is False
    await leads.toggle_block(LEAD, {"tenant_id": T1, "user_id": "u1"})
    assert await blocked_guard.is_blocked(T1, PHONE) is False  # unblock is seen at once too
