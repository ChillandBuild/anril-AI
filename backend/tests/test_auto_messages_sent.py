"""GET /api/v1/auto-messages/sent: four logs merged, plain reasons, delivery via an exact message link."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role
from app.routes import auto_messages_sent as routes
from app.services.send_reasons import explain, plain_reason
from tests.fake_supabase import FakeSupabase

T, OTHER = "t1", "t2"
NOW = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)  # Monday 13:30 IST


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


@pytest.fixture
def db():
    d = FakeSupabase()
    d._stamp = lambda: NOW.isoformat()  # rows created "now" unless a test sets created_at
    return d


def _client(db, permissions=(), role="owner"):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/auto-messages")
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": role, "permissions": list(permissions)}
    return TestClient(app)


@pytest.fixture
def client(db):
    with patch.object(routes, "get_supabase", return_value=db), patch.object(routes, "_utcnow", return_value=NOW):
        yield _client(db)


def _lead(db, name="Asha", phone="9199", tenant=T):
    return db.add("leads", tenant_id=tenant, name=name, phone=phone)["id"]


def _get(client, **params):
    r = client.get("/api/v1/auto-messages/sent", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_merges_four_sources_newest_first(client, db):
    lead = _lead(db)
    tpl = db.add("message_templates", tenant_id=T, name="booking_ok", status="APPROVED")["id"]
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", name="Asha", event="purchased",
           template_id=tpl, status="sent", sent_at=_ago(hours=1), send_at=_ago(hours=1))
    db.add("scheduled_template_sends", tenant_id=T, lead_id=lead, template_name="diwali", content="Hi", status="sent",
           send_at=_ago(hours=2), sent_at=_ago(hours=2))
    db.add("silence_nudge_jobs", tenant_id=T, lead_id=lead, anchor_message_id="a", status="sent",
           fire_at=_ago(hours=3), sent_at=_ago(hours=3), message_preview="Anything else?")
    step = db.add("reengagement_steps", tenant_id=T, type="inbound", delay_hours=72, target_segments=["Hot"],
                  message_type="template", template_name="promo")["id"]
    step2 = db.add("reengagement_steps", tenant_id=T, type="inbound", delay_hours=2, target_segments=["Hot"],
                   message_type="freeform", message_content="Hello")["id"]
    db.add("reengagement_logs", tenant_id=T, lead_id=lead, step_id=step, status="sent", sent_at=_ago(hours=4))
    db.add("reengagement_logs", tenant_id=T, lead_id=lead, step_id=step2, status="sent", sent_at=_ago(hours=5))
    body = _get(client)
    assert [r["label"] for r in body["rows"]] == [
        "Purchased", "One-time send · diwali", "Quick nudge", "Follow-up · Day 3", "Follow-up · 2 hrs"]
    assert body["total"] == 5
    assert {r["source"] for r in body["rows"]} == {"auto_message", "scheduled_template", "silence_nudge", "follow_up"}
    assert all(r["name"] == "Asha" and r["phone"] == "9199" for r in body["rows"])


def test_only_not_sent_filter_and_banner_count(client, db):
    lead = _lead(db)
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="sent", sent_at=_ago(hours=1))
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="failed",
           reason="opted_out", send_at=_ago(hours=2), created_at=_ago(hours=2))
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="queued",
           send_at=_ago(minutes=5), created_at=_ago(minutes=5))
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="failed",
           reason="opted_out", send_at=_ago(days=3), created_at=_ago(days=3))
    everything = _get(client)
    assert everything["total"] == 4 and everything["today_not_sent"] == 1
    assert sorted(r["status"] for r in everything["rows"]) == ["not_sent", "not_sent", "sent", "will_retry"]
    only = _get(client, only_not_sent="true")
    assert only["total"] == 2 and all(r["status"] == "not_sent" for r in only["rows"])
    assert only["today_not_sent"] == 1


def test_range_chips(client, db):
    lead = _lead(db)
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="sent",
           sent_at=_ago(days=20), created_at=_ago(days=20))
    assert _get(client, days=7)["total"] == 0
    assert _get(client, days=30)["total"] == 1


def test_tenant_scoped(client, db):
    mine, theirs = _lead(db), _lead(db, "Bob", "9200", tenant=OTHER)
    db.add("auto_message_sends", tenant_id=OTHER, lead_id=theirs, phone="9200", event="interested", status="sent", sent_at=_ago(hours=1))
    db.add("scheduled_template_sends", tenant_id=OTHER, lead_id=theirs, template_name="x", content="c", status="sent", send_at=_ago(hours=1), sent_at=_ago(hours=1))
    db.add("silence_nudge_jobs", tenant_id=OTHER, lead_id=theirs, anchor_message_id="a", status="sent", fire_at=_ago(hours=1), sent_at=_ago(hours=1))
    step = db.add("reengagement_steps", tenant_id=OTHER, type="inbound", delay_hours=48, target_segments=[], message_type="template")["id"]
    db.add("reengagement_logs", tenant_id=OTHER, lead_id=theirs, step_id=step, status="sent", sent_at=_ago(hours=1))
    assert _get(client)["rows"] == []
    db.add("auto_message_sends", tenant_id=T, lead_id=mine, phone="9199", event="interested", status="sent", sent_at=_ago(hours=1))
    assert _get(client)["total"] == 1


def test_permission_enforced(db):
    with patch.object(routes, "get_supabase", return_value=db):
        assert _client(db, ["leads.view"], role="staff").get("/api/v1/auto-messages/sent").status_code == 403
        assert _client(db, ["auto_messages.view"], role="staff").get("/api/v1/auto-messages/sent").status_code == 200
        assert _client(db, ["auto_messages.manage"], role="staff").get("/api/v1/auto-messages/sent").status_code == 200


def test_plain_words_and_actions(client, db):
    lead = _lead(db)
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="failed",
           reason='{"error": {"code": 131026, "message": "Message undeliverable"}}', send_at=_ago(hours=1), created_at=_ago(hours=1))
    db.add("scheduled_template_sends", tenant_id=T, lead_id=lead, template_name="t", content="c", status="failed",
           reason='{"error": {"code": 131047}}', send_at=_ago(hours=2))
    db.add("silence_nudge_jobs", tenant_id=T, lead_id=lead, anchor_message_id="a", status="skipped",
           fire_at=_ago(hours=3), skip_reason="opted out")
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="failed",
           reason="template_not_approved", send_at=_ago(hours=4), created_at=_ago(hours=4))
    rows = {r["label"] + str(i): r for i, r in enumerate(_get(client)["rows"])}
    r = list(rows.values())
    assert r[0]["why"] == "WhatsApp couldn't deliver to this number. Check that it is on WhatsApp."
    assert r[0]["action"]["kind"] == "open_lead" and r[0]["action"]["href"] == f"/dashboard/leads/{lead}"
    assert r[1]["why"] == "More than 24 hours since their last message, so WhatsApp needs an approved template"
    assert r[1]["action"] == {"kind": "use_template", "label": "Use a template",
                              "href": f"/dashboard/conversations?lead={lead}"}
    assert r[2]["action"]["label"] == "No action needed" and "stop" in r[2]["why"]
    assert r[3]["action"] == {"kind": "see_template", "label": "See template", "href": "/dashboard/templates"}


def _msg(db, lead, content, reply_source, at, **kw):
    return db.add("messages", tenant_id=T, lead_id=lead, direction="outbound", content=content,
                  reply_source=reply_source, created_at=at, **kw)["id"]


def test_delivered_read_and_async_failure_via_exact_message_link(client, db):
    lead = _lead(db)
    tpl = db.add("message_templates", tenant_id=T, name="thanks", status="APPROVED")["id"]
    for ts, ds, extra in ((_ago(hours=1), "delivered", {}), (_ago(hours=2), "read", {}),
                          (_ago(hours=3), "failed", {"delivery_error_code": 131049, "delivery_error_title": "x"})):
        db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="purchased", template_id=tpl,
               status="sent", sent_at=ts, send_at=ts)
        _msg(db, lead, "[Auto-message: thanks]", "automation", ts, delivery_status=ds, **extra)
    rows = _get(client)["rows"]
    assert [r["status"] for r in rows] == ["delivered", "read", "not_sent"]
    assert rows[2]["why"].startswith("Meta held it back so this person doesn't get too many marketing messages")
    assert rows[2]["action"]["label"] == "Nothing to do"
    assert _get(client, only_not_sent="true")["total"] == 1


def test_no_exact_link_stays_sent(client, db):
    lead = _lead(db)
    tpl = db.add("message_templates", tenant_id=T, name="thanks", status="APPROVED")["id"]
    ts = _ago(hours=1)
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="purchased", template_id=tpl,
           status="sent", sent_at=ts, send_at=ts)
    # two identical messages at the same moment: ambiguous, so never guessed
    _msg(db, lead, "[Auto-message: thanks]", "automation", ts, delivery_status="failed", delivery_error_code=131026)
    _msg(db, lead, "[Auto-message: thanks]", "automation", ts, delivery_status="read")
    assert _get(client)["rows"][0]["status"] == "sent"
    # a message that is different text / another person's chat never matches
    db.tables["messages"].clear()
    other = _lead(db, "Bob", "9200")
    _msg(db, other, "[Auto-message: thanks]", "automation", ts, delivery_status="read")
    _msg(db, lead, "something else", "automation", ts, delivery_status="read")
    assert _get(client)["rows"][0]["status"] == "sent"


def test_scheduled_nudge_and_follow_up_links(client, db):
    lead = _lead(db)
    ts = _ago(hours=1)
    db.add("scheduled_template_sends", tenant_id=T, lead_id=lead, template_name="t", content="Offer text", status="sent", send_at=ts, sent_at=ts)
    _msg(db, lead, "Offer text", None, ts, delivery_status="delivered")
    ts2 = _ago(hours=2)
    db.add("silence_nudge_jobs", tenant_id=T, lead_id=lead, anchor_message_id="a", status="sent", fire_at=ts2, sent_at=ts2, message_preview="Need help?")
    _msg(db, lead, "Need help?", "silence_nudge", ts2, delivery_status="read")
    ts3 = _ago(hours=3)
    step = db.add("reengagement_steps", tenant_id=T, type="inbound", delay_hours=48, target_segments=[], message_type="template", template_name="promo")["id"]
    db.add("reengagement_logs", tenant_id=T, lead_id=lead, step_id=step, status="sent", sent_at=ts3)
    _msg(db, lead, "[Template Broadcast: promo]", "reengagement", ts3, delivery_status="failed", delivery_error_code=131047)
    rows = _get(client)["rows"]
    assert [r["status"] for r in rows] == ["delivered", "read", "not_sent"]
    assert rows[2]["why"].startswith("More than 24 hours")


def test_failing_source_is_left_out_not_a_500(client, db):
    lead = _lead(db)
    db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="sent", sent_at=_ago(hours=1))
    real = db.table

    def table(name):
        if name == "silence_nudge_jobs":
            raise Exception("relation does not exist")
        return real(name)
    with patch.object(db, "table", side_effect=table):
        assert _get(client)["total"] == 1


def test_pagination(client, db):
    lead = _lead(db)
    for i in range(5):
        db.add("auto_message_sends", tenant_id=T, lead_id=lead, phone="9199", event="interested", status="sent", sent_at=_ago(hours=i + 1))
    page = _get(client, limit=2, offset=0)
    assert page["total"] == 5 and len(page["rows"]) == 2 and page["has_more"] is True
    last = _get(client, limit=2, offset=4)
    assert len(last["rows"]) == 1 and last["has_more"] is False


def test_send_reasons_words():
    assert plain_reason('{"error": {"code": 131047}}').startswith("More than 24 hours since their last message")
    assert plain_reason("(#131049) blah").startswith("Meta held it back")
    assert plain_reason(131048) == "Too many messages were reported as spam; Meta slowed sending"
    assert plain_reason(131050) == "They turned off marketing messages from businesses"
    assert plain_reason(131042) == "A payment problem on your Meta account"
    assert plain_reason("undeliverable") == plain_reason(131026)
    assert plain_reason('{"error": {"code": 999999}}') == "WhatsApp didn't send it (code 999999)"
    assert plain_reason(None) == "WhatsApp didn't send it"
    assert plain_reason("The customer opted out.") == "The customer opted out."
    assert explain("opted_out")["kind"] == "stopped"
