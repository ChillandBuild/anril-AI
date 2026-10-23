"""Partner door, event mode: a signed call names an Auto Messages event instead of a template
code. Uses the tenant's rule for that event, sends at once, never creates a lead, and logs every
partner send (both modes) as one auto_message_sends row with source 'partner'."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routes.intake import public_router
from tests.fake_supabase import FakeSupabase

app = FastAPI()
app.include_router(public_router, prefix="/api/v1/intake")
legacy_app = FastAPI()
legacy_app.include_router(public_router, prefix="/api/v1/expert-handoff")
client = TestClient(app)

TENANT = "0f897915-2d34-4b67-8d69-f83f52e4fb6c"
OTHER = "11111111-2d34-4b67-8d69-f83f52e4fb6c"
SECRET = "bridge-secret"
URL = "/api/v1/intake/partner/send-template"
PNID = "pnid-primary"


def _signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-astro-signature": f"sha256={sig}", "content-type": "application/json"}


@pytest.fixture
def db():
    d = FakeSupabase()
    d.add("phone_numbers", tenant_id=TENANT, role="primary", meta_phone_number_id=PNID)
    # Event calls are only accepted on an account switched to event mode (Developer page);
    # tests/test_partner_send_mode.py covers the default and the switch itself.
    d.add("app_settings", tenant_id=TENANT, key="partner_send_mode", value="event", is_secret=False)
    return d


def _template(db, name="order_shipped", tenant=TENANT, status="APPROVED", **kw):
    kw.setdefault("body_text", "Hi {{1}}, order {{2}} has shipped.")
    kw.setdefault("short_code", "407940")
    return db.add("message_templates", tenant_id=tenant, name=name, language="en", status=status, **kw)["id"]


def _rule(db, event, template_id, tenant=TENANT, **kw):
    return db.add("auto_message_rules", tenant_id=tenant, event=event, template_id=template_id,
                  enabled=kw.pop("enabled", True), delay_minutes=kw.pop("delay_minutes", 0),
                  variables=kw.pop("variables", []), button_param=kw.pop("button_param", None))["id"]


def _event_body(**over):
    body = {"tenant_id": TENANT, "phone": "919876543210", "event": "purchased", "name": "Priya Raman",
            "extra": {"order_id": "A-77"}, "reference": "order:77"}
    body.update(over)
    return body


def _post(body, db, send=None, url=URL, the_app=None):
    raw, headers = _signed(body)
    send = send or AsyncMock(return_value={"messages": [{"id": "wamid.E1"}]})
    with patch("app.routes.intake.astro_bridge.get_bridge_secret", return_value=SECRET), \
         patch("app.db.supabase.get_supabase", return_value=db), \
         patch("app.services.meta_cloud.send_template_message", send):
        res = (TestClient(the_app) if the_app else client).post(url, content=raw, headers=headers)
    return res, send


def _sends(db):
    return db.rows("auto_message_sends")


def _order_rule(db, **kw):
    t = _template(db)
    return t, _rule(db, "purchased", t, variables=[
        {"source": "first_name", "fallback": "there"}, {"source": "extra", "key": "order_id"}], **kw)


# ------------------------------------------------------------------ event mode: happy path

def test_event_mode_sends_the_events_template_and_returns_the_event_shape(db):
    t, _ = _order_rule(db)
    res, send = _post(_event_body(), db)
    assert res.status_code == 200
    assert res.json() == {
        "ok": True, "message_id": "wamid.E1", "event": "purchased",
        "template": {"code": "407940", "name": "order_shipped", "language": "en"},
    }
    send.assert_awaited_once_with(
        to_number="+919876543210", template_name="order_shipped", lang_code="en",
        components=[{"type": "body", "parameters": [{"type": "text", "text": "Priya"}, {"type": "text", "text": "A-77"}]}],
        tenant_id=TENANT, phone_number_id=PNID,
    )


def test_event_aliases_resolve(db):
    _order_rule(db)
    res, _ = _post(_event_body(event="Order Placed"), db)
    assert res.status_code == 200 and res.json()["event"] == "purchased"


def test_a_custom_event_key_works(db):
    db.add("auto_message_events", tenant_id=TENANT, key="kundli_ready", label="Kundli ready", description=None)
    _rule(db, "kundli_ready", _template(db, "kundli_msg", body_text="Your kundli is ready."))
    res, send = _post(_event_body(event=" Kundli_Ready ", extra=None, name=None), db)
    assert res.status_code == 200 and res.json()["event"] == "kundli_ready"
    assert send.await_args.kwargs["components"] is None


def test_the_legacy_prefix_serves_event_mode_too(db):
    _order_rule(db)
    res, _ = _post(_event_body(), db, url="/api/v1/expert-handoff/partner/send-template", the_app=legacy_app)
    assert res.status_code == 200 and res.json()["event"] == "purchased"


def test_event_mode_supports_header_variable_and_dynamic_button(db):
    t = _template(db, header_text="Hello {{1}}", body_text="Order shipped.",
                  buttons=[{"type": "URL", "text": "Track", "url": "https://x.in/t/{{1}}"}])
    _rule(db, "purchased", t, button_param={"source": "extra", "key": "order_id"})
    res, send = _post(_event_body(), db)
    assert res.status_code == 200
    comps = send.await_args.kwargs["components"]
    assert comps[0] == {"type": "header", "parameters": [{"type": "text", "text": "Priya"}]}
    assert comps[1]["parameters"] == [{"type": "text", "text": "A-77"}]


def test_event_mode_never_creates_a_lead_but_logs_into_an_existing_leads_chat(db):
    _order_rule(db)
    res, _ = _post(_event_body(), db)
    assert res.status_code == 200 and db.rows("leads") == [] and db.rows("messages") == []
    lead = db.add("leads", tenant_id=TENANT, phone="+919876543210", name="Priya")
    _post(_event_body(), db)
    [msg] = db.rows("messages")
    assert msg["lead_id"] == lead["id"] and msg["content"] == "Hi Priya, order A-77 has shipped."
    assert msg["meta_message_id"] == "wamid.E1" and len(db.rows("leads")) == 1


def test_event_mode_has_no_dedupe_no_opt_out_no_quiet_hours_no_delay(db):
    t, _ = _order_rule(db, delay_minutes=60)
    db.add("leads", tenant_id=TENANT, phone="+919876543210", opted_out=True)
    first, send = _post(_event_body(), db)
    second, _ = _post(_event_body(), db, send=send)
    assert first.status_code == second.status_code == 200
    assert send.await_count == 2


# ------------------------------------------------------------------ event mode: errors

def test_both_template_code_and_event_is_400_wrong_mode_on_an_event_account(db):
    _order_rule(db)
    res, send = _post(_event_body(template_code="407940", variables=["a", "b"]), db)
    assert res.status_code == 400 and res.json()["code"] == "wrong_mode" and res.json()["ok"] is False
    send.assert_not_awaited()
    assert _sends(db) == []


def test_neither_template_code_nor_event_is_400_invalid_request(db):
    body = _event_body()
    del body["event"]
    res, send = _post(body, db)
    assert res.status_code == 400 and res.json()["code"] == "invalid_request"
    send.assert_not_awaited()


@pytest.mark.parametrize("bad", [
    {"extra": ["order_id"]}, {"extra": "order_id=1"}, {"extra": {"order_id": 77}}, {"extra": {"order_id": {"a": 1}}},
    {"extra": {"": "x"}}, {"extra": {f"k{i}": "v" for i in range(21)}},
    {"name": 5}, {"name": ["x"]}, {"event": 5}, {"event": ["purchased"]},
])
def test_bad_event_fields_are_400_invalid_request(db, bad):
    _order_rule(db)
    res, send = _post(_event_body(**bad), db)
    assert res.status_code == 400 and res.json()["code"] == "invalid_request", res.text
    send.assert_not_awaited()


def test_event_mode_invalid_phone_is_400(db):
    _order_rule(db)
    res, send = _post(_event_body(phone="12345"), db)
    assert res.status_code == 400 and res.json()["code"] == "invalid_phone"
    send.assert_not_awaited()


def test_event_mode_sends_to_a_foreign_number_without_plus(db):
    _order_rule(db)
    res, send = _post(_event_body(phone="60123456789"), db)
    assert res.status_code == 200, res.text
    assert send.await_args.kwargs["to_number"] == "+60123456789"


def test_unknown_event_is_400_unknown_event_and_sends_nothing(db):
    _order_rule(db)
    db.add("auto_message_events", tenant_id=OTHER, key="kundli_ready", label="x", description=None)
    res, send = _post(_event_body(event="kundli_ready"), db)
    assert res.status_code == 400 and res.json() == {
        "ok": False, "code": "unknown_event", "error": "This account has no event called kundli_ready"}
    send.assert_not_awaited()


def test_event_without_a_rule_is_409_no_rule(db):
    res, send = _post(_event_body(event="signed_up"), db)
    assert res.status_code == 409
    assert res.json() == {"ok": False, "code": "no_rule", "error": "No message is set for this event"}
    send.assert_not_awaited()


def test_a_disabled_rule_or_another_tenants_rule_is_no_rule(db):
    _rule(db, "purchased", _template(db), enabled=False)
    _rule(db, "signed_up", _template(db, "t2", tenant=OTHER), tenant=OTHER)
    assert _post(_event_body(), db)[0].json()["code"] == "no_rule"
    assert _post(_event_body(event="signed_up"), db)[0].json()["code"] == "no_rule"


def test_unapproved_template_is_409_template_not_approved_and_logged_failed(db):
    t, _ = _order_rule(db)
    next(x for x in db.rows("message_templates") if x["id"] == t)["status"] = "PAUSED"
    res, send = _post(_event_body(), db)
    assert res.status_code == 409
    assert res.json() == {"ok": False, "code": "template_not_approved", "error": "Template status is PAUSED"}
    send.assert_not_awaited()
    [row] = _sends(db)
    assert (row["status"], row["reason"], row["template_id"]) == ("failed", "template_not_approved", t)


def test_private_send_key_blocks_event_mode_with_409(db):
    _order_rule(db)
    db.add("private_send_keys", tenant_id=TENANT, key_prefix="aps_live_abcd", key_hash="h", status="active")
    res, send = _post(_event_body(), db)
    assert res.status_code == 409
    assert res.json() == {"ok": False, "code": "private_send_on", "error": "This account sends from its own server"}
    send.assert_not_awaited()
    assert _sends(db) == []


def test_a_revoked_or_other_tenants_private_send_key_does_not_block(db):
    _order_rule(db)
    db.add("private_send_keys", tenant_id=TENANT, key_prefix="a", key_hash="h", status="revoked")
    db.add("private_send_keys", tenant_id=OTHER, key_prefix="b", key_hash="h", status="active")
    assert _post(_event_body(), db)[0].status_code == 200


def test_meta_rejection_is_502_meta_error_and_logged_failed(db):
    _order_rule(db)
    send = AsyncMock(side_effect=HTTPException(status_code=400, detail='{"error":{"code":131026}}'))
    res, _ = _post(_event_body(), db, send=send)
    assert res.status_code == 502
    assert res.json() == {"ok": False, "code": "meta_error", "error": '{"error":{"code":131026}}'}
    [row] = _sends(db)
    assert (row["status"], row["event"], row["source"]) == ("failed", "purchased", "partner")
    assert "131026" in row["reason"]


def test_unexpected_error_and_missing_message_id_are_502(db):
    _order_rule(db)
    assert _post(_event_body(), db, send=AsyncMock(side_effect=RuntimeError("timeout")))[0].json()["error"] == "timeout"
    res, _ = _post(_event_body(), db, send=AsyncMock(return_value={"messages": []}))
    assert res.status_code == 502 and res.json()["error"] == "no message id"
    assert [r["status"] for r in _sends(db)] == ["failed", "failed"]


# ------------------------------------------------------------------ logging: event mode

def test_event_send_is_logged_as_one_partner_row(db):
    t, rule = _order_rule(db)
    _post(_event_body(), db)
    [row] = _sends(db)
    assert row["source"] == "partner" and row["event"] == "purchased"
    assert row["tenant_id"] == TENANT and row["phone"] == "+919876543210" and row["name"] == "Priya Raman"
    assert row["template_id"] == t and row["rule_id"] == rule
    assert row["status"] == "sent" and row["reason"] is None and row["sent_at"]
    assert row["lead_id"] is None
    assert row["extra"] == {"order_id": "A-77", "reference": "order:77"}


def test_extra_keys_are_lowercased_and_values_trimmed_to_200(db):
    _order_rule(db)
    _post(_event_body(extra={"Order_ID": "A-77", "note": "x" * 300}), db)
    [row] = _sends(db)
    assert row["extra"]["order_id"] == "A-77" and len(row["extra"]["note"]) == 200


def test_a_link_in_extra_never_reaches_the_template(db):
    _order_rule(db)
    _, send = _post(_event_body(extra={"order_id": "see https://evil.example"}), db)
    assert send.await_args.kwargs["components"][0]["parameters"][1]["text"] == "-"


def test_a_failing_log_never_blocks_or_fails_the_send(db, caplog):
    _order_rule(db)
    real_table = db.table

    def table(name):
        if name == "auto_message_sends":
            raise RuntimeError("23514 check violation")
        return real_table(name)

    import logging
    with patch.object(db, "table", side_effect=table), caplog.at_level(logging.WARNING):
        res, send = _post(_event_body(), db)
    assert res.status_code == 200 and res.json()["message_id"] == "wamid.E1"
    send.assert_awaited_once()
    assert any("auto_message_sends" in r.getMessage() or "partner" in r.getMessage().lower() for r in caplog.records)


def test_a_failing_log_never_hides_a_meta_error_either(db):
    _order_rule(db)
    real_table = db.table

    def table(name):
        if name == "auto_message_sends":
            raise RuntimeError("db down")
        return real_table(name)

    send = AsyncMock(side_effect=HTTPException(status_code=400, detail="nope"))
    with patch.object(db, "table", side_effect=table):
        res, _ = _post(_event_body(), db, send=send)
    assert res.status_code == 502 and res.json()["code"] == "meta_error"


# ------------------------------------------------------------------ template_code mode: unchanged + logged

APPROVED = {"name": "question_received", "language": "ta", "status": "APPROVED", "body_text": "Hi {{1}}, your question {{2}} was received.",
            "header_text": None, "buttons": [], "short_code": "407940"}


def _code_body(**over):
    body = {"tenant_id": TENANT, "template_code": "407940", "phone": "919876543210",
            "variables": ["Rajan", "#5412"], "reference": "question:5412"}
    body.update(over)
    return body


def _code_db(status="APPROVED"):
    d = FakeSupabase()
    d.add("phone_numbers", tenant_id=TENANT, role="primary", meta_phone_number_id=PNID)
    d.add("message_templates", tenant_id=TENANT, **{**APPROVED, "status": status})
    return d


def test_template_code_mode_response_is_unchanged_and_ignores_every_auto_messages_rule(db):
    d = _code_db()
    d.add("private_send_keys", tenant_id=TENANT, key_prefix="aps_live_abcd", key_hash="h", status="active")  # AstroTamil has a key
    res, send = _post(_code_body(), d)
    assert res.status_code == 200
    assert res.json() == {"ok": True, "message_id": "wamid.E1",
                          "template": {"code": "407940", "name": "question_received", "language": "ta"}}
    assert d.rows("leads") == []


def test_template_code_mode_logs_a_partner_row_with_a_null_event(db):
    d = _code_db()
    res, _ = _post(_code_body(name="Rajan"), d)
    assert res.status_code == 200
    [row] = _sends(d)
    assert row["source"] == "partner" and row["event"] is None and row["lead_id"] is None
    assert row["status"] == "sent" and row["phone"] == "+919876543210" and row["name"] == "Rajan"
    assert row["template_id"] == d.rows("message_templates")[0]["id"] and row["rule_id"] is None


def test_template_code_mode_logs_meta_failures(db):
    d = _code_db()
    res, _ = _post(_code_body(), d, send=AsyncMock(side_effect=HTTPException(status_code=400, detail="131026 undeliverable")))
    assert res.status_code == 502
    [row] = _sends(d)
    assert (row["status"], row["event"], row["source"]) == ("failed", None, "partner")
    assert "131026" in row["reason"]


def test_template_code_mode_does_not_log_request_errors():
    d = _code_db()
    assert _post(_code_body(variables=["only-one"]), d)[0].status_code == 400
    assert _post(_code_body(template_code="999999"), d)[0].status_code == 404
    assert _post(_code_body(phone="12"), d)[0].status_code == 400
    assert _sends(d) == []


def test_template_code_mode_still_works_when_the_log_table_is_broken():
    d = _code_db()
    real_table = d.table

    def table(name):
        if name == "auto_message_sends":
            raise RuntimeError("relation does not exist")
        return real_table(name)

    with patch.object(d, "table", side_effect=table):
        res, _ = _post(_code_body(), d)
    assert res.status_code == 200 and res.json()["message_id"] == "wamid.E1"


def test_template_code_mode_error_precedence_is_unchanged_neither_given():
    body = _code_body()
    del body["template_code"]
    res, send = _post(body, _code_db())
    assert res.status_code == 400
    assert res.json() == {"ok": False, "code": "invalid_request",
                          "error": "template_code is required and variables must be a list"}


def test_send_text_is_not_logged():
    d = _code_db()
    send_text = AsyncMock(return_value="wamid.X1")
    raw, headers = _signed({"tenant_id": TENANT, "phone": "9876543210", "text": "hi"})
    with patch("app.routes.intake.astro_bridge.get_bridge_secret", return_value=SECRET), \
         patch("app.db.supabase.get_supabase", return_value=d), \
         patch("app.services.ai_reply.send_whatsapp", send_text):
        res = client.post("/api/v1/intake/partner/send-text", content=raw, headers=headers)
    assert res.status_code == 200 and _sends(d) == []


# ------------------------------------------------------------------ migration 222

def _migration_221() -> str:
    return (Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "222_partner_sends_log.sql").read_text()


def test_migration_222_is_idempotent_and_widens_only():
    sql = _migration_221()
    assert "SET LOCAL lock_timeout = '5s'" in sql
    assert "DROP CONSTRAINT IF EXISTS auto_message_sends_source_check" in sql
    assert "CHECK (source IN ('website', 'api', 'store', 'partner'))" in sql
    assert "ALTER COLUMN event DROP NOT NULL" in sql
    assert "CREATE OR REPLACE FUNCTION auto_message_sent_events" in sql and "s.event IS NOT NULL" in sql
    for risky in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE"):
        assert risky not in sql
