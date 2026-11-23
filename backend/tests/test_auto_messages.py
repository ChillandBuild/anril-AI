"""Auto-Messages end to end against the in-memory Supabase fake: payload parsing,
every matched event sent at once (no opt-out / duplicate / quiet-hours / delay checks),
failures, template components, and the public / dashboard routes."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role
from app.routes import auto_messages as routes
from app.services import auto_messages as svc
from tests.fake_supabase import FakeSupabase

T = "tenant-1"
OTHER = "tenant-2"


def _now_stamp():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def db():
    d = FakeSupabase()
    d._stamp = _now_stamp
    # Stand-in for the SQL function auto_message_sent_events (migration 221).
    d.rpc_handlers["auto_message_sent_events"] = lambda params: sorted({
        s["event"] for s in d.rows("auto_message_sends")
        if s["tenant_id"] == params["p_tenant"] and s["status"] == "sent"
    })
    return d


@pytest.fixture(autouse=True)
def _fake_lead_creation(db):
    """create_inbound_lead does scoring/assignment/follow-ups; here it only
    has to find-or-create the lead row by (tenant, phone)."""
    def fake_create(tenant_id, phone, source, *, name=None, opt_in_source=None, db=None, **_):
        from app.routes.upload import _normalize_phone
        normalized = _normalize_phone(phone)
        if not normalized:
            return None
        for r in db.rows("leads"):
            if r["tenant_id"] == tenant_id and r["phone"] == normalized:
                return r["id"]
        return db.add("leads", tenant_id=tenant_id, phone=normalized, name=name, source=source,
                      opt_in_source=opt_in_source, opted_out=False)["id"]
    with patch("app.services.inbound_lead.create_inbound_lead", side_effect=fake_create):
        yield


@pytest.fixture
def send():
    with patch("app.services.meta_cloud.send_template_message",
               new=AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})) as m:
        yield m


def _template(db, name, tenant=T, status="APPROVED", **kw):
    return db.add("message_templates", tenant_id=tenant, name=name, language="en", status=status,
                  body_text=kw.pop("body_text", "Hi {{1}}, here are the details on {{2}}."), **kw)["id"]


def _rule(db, event, template_id, tenant=T, **kw):
    return db.add("auto_message_rules", tenant_id=tenant, event=event, template_id=template_id, delay_minutes=kw.pop("delay_minutes", 0), enabled=kw.pop("enabled", True),
                  variables=kw.pop("variables", []), button_param=kw.pop("button_param", None), **kw)["id"]


def _event(db, source="api", **data):
    data.setdefault("phone", "9876543210")
    data.setdefault("extra", {})
    data.setdefault("page_url", "")
    return asyncio.run(svc.handle_event(T, source, data, db=db))


def _sends(db):
    return db.rows("auto_message_sends")


# ---------------------------------------------------------------- parsing

def test_parse_accepts_common_field_names_and_keeps_extras():
    p = svc.parse_payload({"Mobile": "+91 98765 43210", "first_name": "Priya", "last_name": "R",
                           "Product_Name": "Konarc", "page_url": "https://x.in/konarc", "order_id": 991, "_hp": ""})
    assert p["phone"] == "+91 98765 43210" and p["name"] == "Priya R"
    assert p["page_url"] == "https://x.in/konarc"
    # a product field is just another extra field now
    assert p["extra"] == {"product_name": "Konarc", "order_id": "991"}


def test_events_normalise_and_unknown_is_rejected():
    assert svc.normalize_event("Order Placed") == "purchased"
    assert svc.normalize_event("sign-up") == "signed_up"
    assert svc.normalize_event("") == "interested"
    # a non-built-in key is only returned as a slug; the tenant lookup (resolve_event) decides if it exists
    assert svc.normalize_event("refund") == "refund"
    assert svc.normalize_event("pur chase!") is None


# ---------------------------------------------------------------- one message per event

def test_everyone_gets_the_events_message_with_their_first_name(db, send):
    _rule(db, "interested", _template(db, "thanks_for_interest", body_text="Hi {{1}}, thanks!"))
    _rule(db, "purchased", _template(db, "thank_you"))

    r1 = _event(db, phone="9876500001", name="Priya Raman", extra={"product": "Konarc"})
    r2 = _event(db, phone="9876500002", name="Arun")

    assert r1["message_status"] == r2["message_status"] == "sent"
    assert [c.args[1] for c in send.call_args_list] == ["thanks_for_interest", "thanks_for_interest"]
    body = send.call_args_list[0].kwargs["components"][-1]
    assert [p["text"] for p in body["parameters"]] == ["Priya"]
    assert db.rows("lead_notes")[0]["content"] == "Interested (via API)"


def test_other_tenants_rules_are_never_used(db, send):
    _rule(db, "interested", _template(db, "theirs", tenant=OTHER), tenant=OTHER)
    r = _event(db)
    assert r["message_status"] == "skipped" and r["reason"] == "no_rule"
    send.assert_not_called()


def test_event_without_rule_is_logged_not_sent(db, send):
    _rule(db, "purchased", _template(db, "thanks"))
    r = _event(db, event_raw="interested")
    assert (r["message_status"], r["reason"]) == ("skipped", "no_rule")
    send.assert_not_called()


def test_unknown_event_and_bad_phone_are_ignored(db, send):
    assert _event(db, event_raw="refund")["status"] == "ignored"
    assert _event(db, phone="12")["status"] == "ignored"
    assert _sends(db) == []


def test_same_person_same_event_twice_sends_twice(db, send):
    """Owner decision 2026-10-08: no duplicate check. Every matched event is sent."""
    _rule(db, "interested", _template(db, "details"))
    _rule(db, "purchased", _template(db, "thanks"))
    first = _event(db)
    second = _event(db)
    other_event = _event(db, event_raw="purchased")
    assert first["message_status"] == second["message_status"] == other_event["message_status"] == "sent"
    assert [r["reason"] for r in (first, second, other_event)] == [None, None, None]
    assert send.call_count == 3
    assert [s["status"] for s in _sends(db)] == ["sent", "sent", "sent"]


def test_a_rule_delay_is_ignored_and_the_message_goes_out_at_once(db, send):
    """auto_message_rules.delay_minutes stays in the table but is always treated as 0."""
    _rule(db, "signed_up", _template(db, "welcome"), delay_minutes=5)
    before = datetime.now(timezone.utc)
    r = _event(db, event_raw="signup")
    assert r["message_status"] == "sent"
    send.assert_called_once()
    row = _sends(db)[0]
    assert row["status"] == "sent"
    assert datetime.fromisoformat(row["send_at"]) <= datetime.now(timezone.utc)
    assert datetime.fromisoformat(row["send_at"]) >= before - timedelta(seconds=5)
    msg = db.rows("messages")[0]
    assert msg["reply_source"] == "automation" and msg["content"] == "[Auto-message: welcome]"


def test_no_new_row_ever_gets_a_future_send_at(db, send):
    _rule(db, "interested", _template(db, "offer", category="MARKETING"), delay_minutes=120)
    with patch.object(svc, "_utcnow", return_value=datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc)):  # 23:00 IST
        _event(db)
    assert datetime.fromisoformat(_sends(db)[0]["send_at"]) == datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc)


def test_scheduler_still_sends_a_stale_queued_row_as_a_retry_path(db, send):
    rule_id = _rule(db, "signed_up", _template(db, "welcome"))
    db.add("auto_message_sends", tenant_id=T, rule_id=rule_id, phone="+919876543210", event="signed_up",
           source="api", status="queued", send_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
           extra={}, template_id=db.rows("auto_message_rules")[0]["template_id"])
    with patch.object(svc, "get_supabase", return_value=db):
        assert asyncio.run(svc.process_due_sends()) == 1
        assert asyncio.run(svc.process_due_sends()) == 0          # never sent twice
    assert _sends(db)[0]["status"] == "sent" and send.call_count == 1


def test_opted_out_lead_still_gets_the_message(db, send):
    _rule(db, "interested", _template(db, "t"))
    db.add("leads", tenant_id=T, phone="+919876543210", opted_out=True)
    r = _event(db)
    assert (r["message_status"], r["reason"]) == ("sent", None)
    send.assert_called_once()


def test_rule_switched_off_while_queued_is_skipped(db, send):
    rule_id = _rule(db, "interested", _template(db, "t"))
    db.add("auto_message_sends", tenant_id=T, rule_id=rule_id, phone="+919876543210", event="interested",
           source="api", status="queued", send_at=_now_stamp(), extra={})
    next(r for r in db.rows("auto_message_rules") if r["id"] == rule_id)["enabled"] = False
    with patch.object(svc, "get_supabase", return_value=db):
        asyncio.run(svc.process_due_sends())
    assert (_sends(db)[0]["status"], _sends(db)[0]["reason"]) == ("skipped", "rule_removed_or_off")
    send.assert_not_called()


def test_unapproved_template_and_meta_error_are_failures_with_reason(db, send):
    t = _template(db, "t")
    _rule(db, "interested", t)
    next(r for r in db.rows("message_templates") if r["id"] == t)["status"] = "PAUSED"
    r = _event(db)
    assert (r["message_status"], r["reason"]) == ("failed", "template_not_approved")

    next(r for r in db.rows("message_templates") if r["id"] == t)["status"] = "APPROVED"
    send.side_effect = HTTPException(status_code=400, detail="(#131026) Message undeliverable")
    r = _event(db, phone="9876500009")
    assert r["message_status"] == "failed" and "131026" in r["reason"]


# ---------------------------------------------------------------- components

def test_components_image_header_variables_fallbacks_and_dynamic_button(db, send):
    t = _template(db, "offer_card", header_media_type="IMAGE", header_media_url="https://x/offer.jpg",
                  body_text="Hi {{1}}, you came from {{2}}. Order {{3}}.",
                  buttons=[{"type": "QUICK_REPLY", "text": "Call me"},
                           {"type": "URL", "text": "Book Test Ride", "url": "https://ather.example/{{1}}"}])
    _rule(db, "interested", t, variables=[
        {"source": "first_name", "fallback": "there"},
        {"source": "page_url", "fallback": "our site"},
        {"source": "extra", "key": "order_id", "fallback": "soon"},
    ], button_param={"source": "text", "value": "test-ride"})

    _event(db, name="", page_url="https://x.in/offer")
    comps = send.call_args.kwargs["components"]
    # the template's own approved image goes in the header
    assert comps[0] == {"type": "header", "parameters": [{"type": "image", "image": {"link": "https://x/offer.jpg"}}]}
    assert [p["text"] for p in comps[1]["parameters"]] == ["there", "https://x.in/offer", "soon"]
    assert comps[2] == {"type": "button", "sub_type": "url", "index": "1",
                        "parameters": [{"type": "text", "text": "test-ride"}]}


def test_header_text_variable_is_the_first_name(db, send):
    _rule(db, "signed_up", _template(db, "welcome", header_text="Welcome {{1}}", body_text="Glad you joined."))
    _event(db, event_raw="signup", name="Meena K")
    assert send.call_args.kwargs["components"][0] == {"type": "header", "parameters": [{"type": "text", "text": "Meena"}]}


# ---------------------------------------------------------------- routes

@pytest.fixture
def client(db):
    routes._per_ip.reset()
    routes._per_tenant.reset()
    app = FastAPI()
    app.include_router(routes.public_router, prefix="/api/v1/auto-messages")
    app.include_router(routes.router, prefix="/api/v1/auto-messages")
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "owner", "permissions": []}
    db.add("app_settings", tenant_id=T, key=routes.TOKEN_KEY, value="tok-123")
    with patch.object(routes, "get_supabase", return_value=db), patch.object(svc, "get_supabase", return_value=db):
        yield TestClient(app)


def test_ingest_rejects_unknown_token(client):
    r = client.post("/api/v1/auto-messages/in/nope", json={"phone": "9876543210"})
    assert r.status_code == 401


def test_ingest_json_from_zapier_sends_and_is_cors_readable(client, db, send):
    _rule(db, "purchased", _template(db, "thank_you"))
    r = client.post("/api/v1/auto-messages/in/tok-123", json={"mobile": "9876543210", "event": "order", "amount": "450"})
    assert r.status_code == 200 and r.json()["message_status"] == "sent"
    assert r.headers["access-control-allow-origin"] == "*"
    assert _sends(db)[0]["source"] == "api" and _sends(db)[0]["extra"] == {"amount": "450"}


def test_website_form_post_is_tagged_website_and_honeypot_drops_bots(client, db, send):
    _rule(db, "interested", _template(db, "t"))
    bot = client.post("/api/v1/auto-messages/in/tok-123", data={"phone": "9876543210", "_hp": "spam", "_src": "form"})
    assert bot.status_code == 200 and _sends(db) == []
    ok = client.post("/api/v1/auto-messages/in/tok-123", data={"phone": "9876543210", "_hp": "", "_src": "form"})
    assert ok.status_code == 200 and _sends(db)[0]["source"] == "website"
    assert db.rows("leads")[0]["opt_in_source"] == "website_form"


def test_ingest_bad_input_and_rate_limit(client):
    assert client.post("/api/v1/auto-messages/in/tok-123", json={"phone": "1"}).status_code == 422
    assert client.post("/api/v1/auto-messages/in/tok-123", content="not json",
                       headers={"content-type": "application/json"}).status_code == 400
    form = [client.post("/api/v1/auto-messages/in/tok-123", data={"phone": "1", "_src": "form"}).status_code for _ in range(11)]
    assert form[-1] == 429


def test_app_server_sending_many_customers_from_one_ip_is_not_throttled(client, db, send):
    """An app/billing backend posts every customer from the same IP; only the
    website form is limited per IP."""
    _rule(db, "signed_up", _template(db, "welcome"))
    codes = [
        client.post("/api/v1/auto-messages/in/tok-123", json={"phone": f"98765{i:05d}", "event": "signup"}).status_code
        for i in range(30)
    ]
    assert codes == [200] * 30 and send.call_count == 30


def test_form_script_embeds_endpoint_and_has_no_product_picker(client, db):
    js = client.get("/api/v1/auto-messages/in/tok-123/form.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert '/api/v1/auto-messages/in/tok-123";' in js.text
    assert "product" not in js.text.lower()
    assert "no longer valid" in client.get("/api/v1/auto-messages/in/bad/form.js").text


def test_form_script_names_the_anril_style_id_and_both_form_prefixes(client, db):
    js = client.get("/api/v1/auto-messages/in/tok-123/form.js").text
    assert "anril-f-css" in js and '"anril", "aira"' in js and "aira-f-css" not in js


_FAKE_DOM_RUNNER = r"""
const fs = require("fs");
function node(tag) {
  const n = { tag, attrs: {}, children: [], listeners: {}, textContent: "", id: undefined,
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(e, f) { this.listeners[e] = f; },
    querySelector() { return node("input"); } };
  return n;
}
const head = node("head");
const hosts = [];
function host(attr) { const h = node("div"); h.attrs[attr] = ""; hosts.push(h); return h; }
const oldHost = host("data-aira-form"), newHost = host("data-anril-form");
global.location = { href: "https://example.com/" };
global.URLSearchParams = URLSearchParams;
global.document = {
  readyState: "complete", head,
  createElement: node,
  getElementById(id) { return head.children.find(c => c.id === id) || null; },
  querySelectorAll(sel) {
    const wanted = sel.split(",").map(s => s.trim().replace(/^\[|\]$/g, ""));
    return hosts.filter(h => wanted.some(w => w in h.attrs));
  },
  addEventListener() {},
};
eval(fs.readFileSync(process.argv[2], "utf8"));
const formClass = h => (h.children[0] || {attrs: {}}).attrs["class"];
console.log(JSON.stringify({
  old_class: formClass(oldHost), new_class: formClass(newHost),
  old_ready: oldHost.attrs["data-aira-ready"] || null, new_ready: newHost.attrs["data-anril-ready"] || null,
  styles: head.children.map(c => c.id),
  css: head.children.map(c => c.textContent).join(""),
}));
"""


def test_form_script_runs_and_renders_into_both_old_and_new_hosts(client, db, tmp_path):
    import json
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = client.get("/api/v1/auto-messages/in/tok-123/form.js").text
    (tmp_path / "form.js").write_text(js)
    (tmp_path / "run.js").write_text(_FAKE_DOM_RUNNER)
    out = subprocess.run(["node", str(tmp_path / "run.js"), str(tmp_path / "form.js")],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["new_class"] == "anril-f" and got["new_ready"] == "1"
    assert got["old_class"] == "aira-f" and got["old_ready"] == "1"
    assert got["styles"] == ["anril-f-css"]
    for cls in ("f", "n", "e", "ok", "hp"):
        assert f".anril-{cls}" in got["css"], cls
        assert f".aira-{cls}" in got["css"], cls


def test_rules_crud_validates_template_and_one_rule_per_event(client, db):
    approved, pending = _template(db, "ok"), _template(db, "pending", status="PENDING")
    base = "/api/v1/auto-messages/rules"
    assert client.post(base, json={"event": "interested", "template_id": pending}).status_code == 400
    assert client.post(base, json={"event": "interested", "template_id": _template(db, "x", tenant=OTHER)}).status_code == 404
    assert client.post(base, json={"event": "nope", "template_id": approved}).status_code == 422
    assert client.post(base, json={"event": "interested", "template_id": approved,
                                   "variables": [{"source": "price"}]}).status_code == 422
    created = client.post(base, json={"event": "interested", "template_id": approved,
                                      "delay_minutes": 5, "variables": [{"source": "first_name", "fallback": "there"}]})
    assert created.status_code == 200
    # an old client may still send delay_minutes: it is ignored, never stored, never 422
    assert not created.json().get("delay_minutes")
    assert "delay_minutes" not in db.rows("auto_message_rules")[0]
    assert client.post(base, json={"event": "interested", "template_id": approved}).status_code == 409
    assert client.post(base, json={"event": "purchased", "template_id": approved}).status_code == 200
    rid = created.json()["id"]
    assert client.patch(f"{base}/{rid}", json={"enabled": False}).json()["enabled"] is False
    assert client.patch(f"{base}/{rid}", json={"delay_minutes": 30}).status_code == 400  # nothing left to change
    assert "delay_minutes" not in db.rows("auto_message_rules")[0]
    assert client.delete(f"{base}/{rid}").status_code == 200
    assert len(client.get(base).json()["rules"]) == 1


def test_send_log_names_the_template(client, db, send):
    _rule(db, "interested", _template(db, "details"))
    client.post("/api/v1/auto-messages/in/tok-123", json={"phone": "9876543210"})
    log = client.get("/api/v1/auto-messages/sends").json()["sends"]
    assert log[0]["template_name"] == "details" and log[0]["status"] == "sent"


def test_templates_endpoint_lists_only_approved_with_variable_info(client, db):
    _template(db, "pending", status="PENDING")
    _template(db, "card", body_text="Hi {{1}} {{2}} {{1}}",
              buttons=[{"type": "URL", "text": "Book", "url": "https://x/{{1}}"}, {"type": "QUICK_REPLY", "text": "Stop"}])
    out = client.get("/api/v1/auto-messages/templates").json()["templates"]
    assert [t["name"] for t in out] == ["card"]
    assert out[0]["variable_count"] == 2 and out[0]["has_dynamic_button"] is True and out[0]["buttons"] == ["Book", "Stop"]


# ---------------------------------------------------------------- review fixes

def test_links_from_customers_never_reach_the_template_and_whitespace_is_flattened(db, send):
    _rule(db, "interested", _template(db, "t", body_text="Hi {{1}}, about {{2}}: {{3}}"), variables=[
        {"source": "first_name", "fallback": "there"},
        {"source": "extra", "key": "topic", "fallback": "our offers"},
        {"source": "extra", "key": "note", "fallback": "see you"},
    ])
    _event(db, name="win.com prize", extra={"topic": "free at https://evil.example", "note": "line1\n\tline2   end"})
    params = [p["text"] for p in send.call_args.kwargs["components"][-1]["parameters"]]
    assert params == ["there", "our offers", "line1 line2 end"]


def test_button_suffix_is_url_encoded(db, send):
    t = _template(db, "t", body_text="Hi", buttons=[{"type": "URL", "text": "Book", "url": "https://x.example/{{1}}"}])
    _rule(db, "interested", t, button_param={"source": "extra", "key": "model"})
    _event(db, extra={"model": "Konarc S"})
    assert send.call_args.kwargs["components"][-1]["parameters"][0]["text"] == "Konarc%20S"


def test_send_interrupted_mid_flight_is_marked_failed_not_resent(db, send):
    _rule(db, "interested", _template(db, "t"))
    _event(db)
    send.reset_mock()
    row = _sends(db)[0]
    row.update(status="sending", send_at=(datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat())
    with patch.object(svc, "get_supabase", return_value=db):
        assert asyncio.run(svc.process_due_sends()) == 0
    assert (row["status"], row["reason"]) == ("failed", "interrupted")
    send.assert_not_called()


def test_lead_schema_accepts_the_new_sources():
    from app.models.schemas import LeadBase
    for source in ("website", "api", "store"):
        assert LeadBase(source=source).source == source


def _auto_messages_client(perms):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/auto-messages")
    app.dependency_overrides[get_tenant_and_role] = lambda: {"tenant_id": T, "role": "telecaller", "permissions": perms}
    return TestClient(app)


def test_auto_messages_view_can_read_but_not_edit(db, send):
    with patch.object(routes, "get_supabase", return_value=db), patch.object(svc, "get_supabase", return_value=db):
        c = _auto_messages_client(["auto_messages.view"])
        assert c.get("/api/v1/auto-messages/sends").status_code == 200
        assert c.get("/api/v1/auto-messages/events").status_code == 200
        assert c.post("/api/v1/auto-messages/rules", json={}).status_code == 403
        assert c.post("/api/v1/auto-messages/events", json={"label": "Kundli ready"}).status_code == 403


def test_old_settings_and_leads_keys_no_longer_open_auto_messages(db, send):
    with patch.object(routes, "get_supabase", return_value=db), patch.object(svc, "get_supabase", return_value=db):
        c = _auto_messages_client(["settings.manage", "leads.manage"])
        assert c.get("/api/v1/auto-messages/sends").status_code == 403
        assert c.get("/api/v1/auto-messages/summary").status_code == 403


def test_rate_limit_key_ignores_client_supplied_forwarded_for():
    from starlette.requests import Request as StarletteRequest

    def req(headers):
        return StarletteRequest({"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()], "client": ("10.0.0.1", 1)})
    assert routes._client_ip(req({"x-forwarded-for": "1.2.3.4, 203.0.113.9"})) == "10.0.0.1"
    assert routes._client_ip(req({"cf-connecting-ip": "198.51.100.7", "x-forwarded-for": "1.2.3.4"})) == "198.51.100.7"
    assert routes._client_ip(req({})) == "10.0.0.1"
