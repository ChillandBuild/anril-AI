"""Anril OTP (services/otp.py + routes/otp.py). The real service code runs against the
in-memory FakeSupabase; Bulk9 and Meta sends are mocked. otp_try_code (a SQL function) is
mirrored in python below, rule for rule."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role
from app.routes import otp as routes
from app.services import bulk9_client, meta_cloud, sms_delivery
from app.services import otp as svc
from fake_supabase import FakeSupabase

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
PHONE = "+91 98765 43210"


def _try_code(db, p):
    rows = [r for r in db.rows("otp_requests") if r["id"] == p["p_id"] and r["tenant_id"] == p["p_tenant"]]
    if not rows:
        return "not_found"
    r = rows[0]
    if r.get("code_hash") is None:
        return "not_checkable"
    if r["status"] == "verified":
        return "already_verified"
    if r["status"] != "pending":
        return r["status"]
    if datetime.fromisoformat(r["expires_at"]) <= datetime.now(timezone.utc):
        r.update(status="expired", fallback_due_at=None, pending_code_enc=None)
        return "expired"
    if r["code_hash"] == p["p_hash"]:
        r.update(status="verified", attempts=r.get("attempts", 0) + 1, fallback_due_at=None, pending_code_enc=None)
        return "verified"
    if r.get("attempts", 0) + 1 >= p["p_max_attempts"]:
        r.update(status="locked", attempts=r.get("attempts", 0) + 1, fallback_due_at=None, pending_code_enc=None)
        return "locked"
    r["attempts"] = r.get("attempts", 0) + 1
    return "wrong_code"


_ROW_DEFAULTS = {"status": "pending", "attempts": 0, "sms_status": "none", "whatsapp_status": "none",
                 "fallback_due_at": None, "fallback_sent_at": None, "pending_code_enc": None,
                 "not_requested_at": None, "verified_at": None, "whatsapp_message_id": None}


@pytest.fixture
def env(monkeypatch):
    db = FakeSupabase()
    db.rpc_handlers["otp_try_code"] = lambda p: _try_code(db, p)
    orig_insert = db.table

    def table(name):
        q = orig_insert(name)
        if name == "otp_requests":
            real_insert = q.insert

            def insert(payload):
                return real_insert({**_ROW_DEFAULTS, **payload})
            q.insert = insert
        if name == "otp_status_events":
            real_insert = q.insert

            def insert(payload):
                return real_insert({"status": "pending", "attempts": 0, "created_at": svc._iso(svc._now()),
                                    "next_attempt_at": svc._iso(svc._now() - timedelta(seconds=1)), **payload})
            q.insert = insert
        return q
    db.table = table

    db.rows("tenants").extend([{"id": TENANT, "enabled_features": ["sms"]}, {"id": OTHER, "enabled_features": ["sms"]}])
    settings = {}
    for t in (TENANT, OTHER):
        settings.update({(t, "bulk9_api_key"): "b9key", (t, "meta_phone_number_id"): "pid",
                         (t, "meta_access_token"): "tok", (t, "meta_waba_id"): "waba"})
        db.rows("otp_settings").append({"tenant_id": t, "sms_sender_id": "ASTTML", "sms_message_id": "14892",
                                        "wa_template_name": "anril_login_code", "wa_template_language": "en"})

    def get_setting(key, fallback=None, tenant_id=None):
        return settings.get((tenant_id, key), fallback)

    monkeypatch.setattr(svc, "get_setting", get_setting)
    monkeypatch.setattr(routes, "get_setting", get_setting)
    monkeypatch.setattr(svc, "get_supabase", lambda: db)
    monkeypatch.setattr(routes, "get_supabase", lambda: db)
    spawned = []
    monkeypatch.setattr(svc, "_spawn", lambda coro: spawned.append(coro))
    sms = AsyncMock(return_value={"return": True, "request_id": "REQ1"})
    monkeypatch.setattr(bulk9_client, "send_dlt", sms)
    wa = AsyncMock(return_value={"messages": [{"id": "wamid.ABC"}]})
    monkeypatch.setattr(meta_cloud, "send_template_message", wa)
    for name in ("_ip_limiter", "_key_limiter", "_verify_limiter", "_key_change_limiter", "_console_send_limiter"):
        monkeypatch.setattr(routes, name, routes._SlidingWindow(1000, 60))
    monkeypatch.setattr(routes, "record_audit_event", lambda *_a, **_k: None)
    yield SimpleNamespace(db=db, sms=sms, wa=wa, spawned=spawned, settings=settings)
    for coro in spawned:
        coro.close()


def _row(env, otp_id):
    return next(r for r in env.db.rows("otp_requests") if r["id"] == otp_id)


def _sent_code(mock) -> str:
    kwargs = mock.call_args.kwargs
    if "variables" in kwargs:
        return kwargs["variables"][0]
    return kwargs["components"][0]["parameters"][0]["text"]


# ---------------------------------------------------------------- helpers

@pytest.mark.parametrize("raw,want", [
    ("9876543210", "919876543210"), ("+91 98765 43210", "919876543210"), ("09876543210", "919876543210"),
    ("919876543210", "919876543210"), ("+14155550123", "14155550123"), ("0014155550123", "14155550123"),
])
def test_normalize_phone(raw, want):
    assert svc.normalize_phone(raw) == want


@pytest.mark.parametrize("raw", ["", "12345", "abc", "+0123456789"])
def test_normalize_phone_rejects(raw):
    with pytest.raises(svc.OtpError):
        svc.normalize_phone(raw)


def test_mask_never_reveals_the_middle():
    assert svc.mask_code("009010") == "00••10"
    assert svc.mask_code("4829") == "4••9"


@pytest.mark.parametrize("url", ["http://example.com/h", "https://localhost/h", "https://127.0.0.1/h",
                                 "https://10.0.0.5/h", "https://169.254.169.254/latest", "https://u:p@example.com/h",
                                 "https://[::1]/h", "https://svc.internal/h"])
def test_status_url_must_be_public_https(url):
    with pytest.raises(svc.OtpError):
        svc.check_webhook_url(url)


def test_signature_is_hmac_of_timestamp_dot_body():
    import hashlib
    import hmac
    sig = svc.sign_payload("whsec_x", 1700000000, b'{"a":1}')
    assert sig == "v1=" + hmac.new(b"whsec_x", b'1700000000.{"a":1}', hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- Anril makes the code

@pytest.mark.asyncio
async def test_anril_code_sms_stores_only_a_hash_and_verifies(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    code = _sent_code(env.sms)
    kwargs = env.sms.call_args.kwargs
    assert kwargs["numbers"] == ["9876543210"] and kwargs["udf1"] == f"otp:{view['otp_id']}"
    assert kwargs["sender_id"] == "ASTTML" and kwargs["message_id"] == "14892"
    row = _row(env, view["otp_id"])
    # hex hashes / uuids may contain digit runs by chance, so check every other column
    assert code not in repr({k: v for k, v in row.items() if k not in ("code_hash", "id", "created_at", "expires_at")})
    assert row["code_hash"] == svc.hash_code(row["id"], code) and row["pending_code_enc"] is None
    assert view["sms"]["status"] == "sent" and len(code) == 6

    res = svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=code)
    assert res["verified"] is True
    again = svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=code)
    assert again["verified"] is False and again["reason"] == "already_verified"


@pytest.mark.asyncio
async def test_five_wrong_tries_lock_the_code(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    code = _sent_code(env.sms)
    wrong = "000000" if code != "000000" else "111111"
    results = [svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=wrong)["reason"] for _ in range(5)]
    assert results == ["wrong_code"] * 4 + ["locked"]
    assert svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=code)["reason"] == "locked"


@pytest.mark.asyncio
async def test_expired_code_is_refused(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    code = _sent_code(env.sms)
    _row(env, view["otp_id"])["expires_at"] = svc._iso(svc._now() - timedelta(seconds=1))
    assert svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=code)["reason"] == "expired"


@pytest.mark.asyncio
async def test_verify_by_phone_and_new_code_replaces_old(env):
    first = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    old = _sent_code(env.sms)
    await svc.send_code(env.db, TENANT, phone="9876543210", mode="sms")
    new = _sent_code(env.sms)
    assert _row(env, first["otp_id"])["status"] == "expired"
    assert svc.verify(env.db, TENANT, phone=PHONE, code=new)["verified"] is True
    if old != new:
        assert svc.verify(env.db, TENANT, otp_id=first["otp_id"], code=old)["verified"] is False


@pytest.mark.asyncio
async def test_other_tenant_cannot_verify_or_read(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    with pytest.raises(svc.OtpError) as e:
        svc.verify(env.db, OTHER, otp_id=view["otp_id"], code=_sent_code(env.sms))
    assert e.value.code == "not_found"
    assert svc.get_request(env.db, OTHER, view["otp_id"]) is None


@pytest.mark.asyncio
async def test_per_number_hourly_limit(env):
    env.db.rows("otp_settings")[0]["max_per_hour"] = 2
    await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    with pytest.raises(svc.OtpError) as e:
        await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    assert e.value.status_code == 429 and e.value.code == "too_many_codes"


@pytest.mark.asyncio
async def test_sms_mode_refuses_non_indian_number(env):
    with pytest.raises(svc.OtpError) as e:
        await svc.send_code(env.db, TENANT, phone="+14155550123", mode="sms")
    assert e.value.code == "sms_india_only"


@pytest.mark.asyncio
async def test_mode_not_ready_is_refused(env):
    env.db.rows("otp_settings")[0]["wa_template_name"] = None
    with pytest.raises(svc.OtpError) as e:
        await svc.send_code(env.db, TENANT, phone=PHONE, mode="whatsapp")
    assert e.value.code == "channel_not_ready"
    env.sms.assert_not_called()
    env.wa.assert_not_called()


# ---------------------------------------------------------------- client's server makes the code

@pytest.mark.asyncio
async def test_client_code_is_delivered_masked_and_not_checkable(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="both", code="009010", ref="order-1")
    assert _sent_code(env.sms) == "009010" and _sent_code(env.wa) == "009010"
    row = _row(env, view["otp_id"])
    assert row["code_hash"] is None and row["code_masked"] == "00••10" and row["pending_code_enc"] is None
    assert "009010" not in repr(row)
    assert view["source"] == "client" and view["ref"] == "order-1"
    assert view["sms"]["status"] == "sent" and view["whatsapp"]["status"] == "sent"
    with pytest.raises(svc.OtpError) as e:
        svc.verify(env.db, TENANT, otp_id=view["otp_id"], code="009010")
    assert e.value.code == "not_checkable"


@pytest.mark.asyncio
async def test_whatsapp_template_carries_code_in_body_and_button(env):
    await svc.send_code(env.db, TENANT, phone=PHONE, mode="whatsapp", code="482913")
    kwargs = env.wa.call_args.kwargs
    assert env.wa.call_args.args[:3] == ("919876543210", "anril_login_code", "en")
    assert kwargs["components"][1] == {"type": "button", "sub_type": "url", "index": "0",
                                       "parameters": [{"type": "text", "text": "482913"}]}


# ---------------------------------------------------------------- SMS, then WhatsApp

@pytest.mark.asyncio
async def test_sms_rejected_sends_whatsapp_backup_at_once_with_same_code(env):
    env.sms.side_effect = bulk9_client.Bulk9Error("Insufficient balance")
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms_then_whatsapp")
    row = _row(env, view["otp_id"])
    assert row["sms_status"] == "failed" and row["whatsapp_status"] == "sent"
    assert row["fallback_sent_at"] and row["pending_code_enc"] is None
    code = _sent_code(env.wa)
    assert svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=code)["verified"] is True


@pytest.mark.asyncio
async def test_timer_sends_backup_when_no_delivery_report(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms_then_whatsapp")
    sms_code = _sent_code(env.sms)
    row = _row(env, view["otp_id"])
    assert row["fallback_due_at"] and row["pending_code_enc"] and sms_code not in row["pending_code_enc"]
    env.wa.assert_not_called()
    assert await svc._fallback_now(env.db, TENANT, view["otp_id"]) is True
    assert _sent_code(env.wa) == sms_code
    assert _row(env, view["otp_id"])["pending_code_enc"] is None
    assert await svc._fallback_now(env.db, TENANT, view["otp_id"]) is False  # only once
    assert env.wa.call_count == 1


@pytest.mark.asyncio
async def test_delivered_sms_cancels_backup(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms_then_whatsapp")
    assert svc.apply_sms_report(env.db, TENANT, view["otp_id"], "delivered") is True
    row = _row(env, view["otp_id"])
    assert row["sms_status"] == "delivered" and row["pending_code_enc"] is None and row["fallback_due_at"] is None
    assert await svc._fallback_now(env.db, TENANT, view["otp_id"]) is False
    env.wa.assert_not_called()


@pytest.mark.asyncio
async def test_failed_sms_report_makes_backup_due_now(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms_then_whatsapp")
    for coro in env.spawned:
        coro.close()
    env.spawned.clear()
    svc.apply_sms_report(env.db, TENANT, view["otp_id"], "failed", "DND")
    row = _row(env, view["otp_id"])
    assert row["sms_status"] == "failed" and row["sms_error"] == "DND"
    assert datetime.fromisoformat(row["fallback_due_at"]) <= svc._now()
    assert env.spawned  # backup handed to the loop straight away
    stats = await svc.sweep(env.db)
    assert stats["backups"] == 1 and env.wa.call_count == 1


def test_bulk9_callback_with_otp_tag_is_routed_to_otp(env, monkeypatch):
    seen = []
    monkeypatch.setattr(svc, "apply_sms_report", lambda db, t, otp_id, status, reason=None: seen.append((t, otp_id, status)) or True)
    out = sms_delivery._apply_event(env.db, TENANT, None, {"udf1": "otp:abc", "status": "Delivered"})
    assert out == {"status": "ok"} and seen == [(TENANT, "abc", "delivered")]


# ---------------------------------------------------------------- WhatsApp receipts + "I didn't request a code"

@pytest.mark.asyncio
async def test_whatsapp_receipts_only_move_forward(env):
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="whatsapp")
    svc.apply_whatsapp_statuses(env.db, TENANT, [{"id": "wamid.ABC", "status": "read"}])
    svc.apply_whatsapp_statuses(env.db, TENANT, [{"id": "wamid.ABC", "status": "delivered"}])
    assert _row(env, view["otp_id"])["whatsapp_status"] == "read"
    svc.apply_whatsapp_statuses(env.db, OTHER, [{"id": "wamid.ABC", "status": "failed"}])
    assert _row(env, view["otp_id"])["whatsapp_status"] == "read"


@pytest.mark.asyncio
async def test_not_requested_cancels_code_and_tells_client(env):
    env.db.rows("otp_settings")[0]["status_webhook_url"] = "https://client.example.com/otp"
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="whatsapp")
    code = _sent_code(env.wa)
    assert svc.handle_not_requested(env.db, TENANT, phone="919876543210", context_wamid="wamid.ABC") is True
    row = _row(env, view["otp_id"])
    assert row["status"] == "not_requested" and row["not_requested_at"]
    assert svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=code)["reason"] == "not_requested"
    events = [e["event"] for e in env.db.rows("otp_status_events")]
    assert "not_requested" in events
    assert all(code not in repr(e["payload"]) for e in env.db.rows("otp_status_events"))
    assert svc.not_requested_count(env.db, TENANT) == 1


# ---------------------------------------------------------------- status updates delivery

@pytest.mark.asyncio
async def test_status_updates_retry_then_give_up(env, monkeypatch):
    env.db.rows("otp_settings")[0].update(status_webhook_url="https://client.example.com/otp",
                                          status_webhook_secret="whsec_s")
    calls = []

    async def failing(url, secret, event):
        calls.append((url, secret, event["event"]))
        return "Status URL answered HTTP 500"
    monkeypatch.setattr(svc, "_post_event", failing)
    await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    ev = env.db.rows("otp_status_events")[0]
    for attempt in range(svc.WEBHOOK_MAX_ATTEMPTS):
        ev["next_attempt_at"] = svc._iso(svc._now() - timedelta(seconds=1))
        await svc.deliver_due_events(env.db)
        assert ev["attempts"] == attempt + 1
    assert ev["status"] == "failed" and calls[0] == ("https://client.example.com/otp", "whsec_s", "sms_sent")
    assert svc.failed_webhook_count(env.db, TENANT) == 1


@pytest.mark.asyncio
async def test_no_status_url_means_no_events(env):
    await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    assert env.db.rows("otp_status_events") == []


# ---------------------------------------------------------------- public API

def _client(env, ctx=None):
    app = FastAPI()
    app.include_router(routes.public_router, prefix="/api/v1/otp")
    app.include_router(routes.router, prefix="/api/v1/otp-console")
    holder = {"ctx": ctx or {"tenant_id": TENANT, "role": "owner", "user_id": "u1", "permissions": []}}
    app.dependency_overrides[get_tenant_and_role] = lambda: holder["ctx"]
    return TestClient(app), holder


def test_api_rejects_missing_wrong_and_revoked_keys(env):
    client, _ = _client(env)
    assert client.post("/api/v1/otp/send", json={"phone": PHONE}).status_code == 401
    bad = client.post("/api/v1/otp/send", json={"phone": PHONE}, headers={"Authorization": "Bearer anr_otp_live_nope"})
    assert bad.status_code == 401 and bad.json()["code"] == "invalid_key"
    key = svc.create_key(env.db, TENANT, None)
    svc.revoke_key(env.db, TENANT, key["id"])
    r = client.post("/api/v1/otp/send", json={"phone": PHONE}, headers={"Authorization": f"Bearer {key['key']}"})
    assert r.status_code == 401 and r.json()["code"] == "revoked_key"


def test_api_send_verify_status_and_tenant_isolation(env):
    client, _ = _client(env)
    key = svc.create_key(env.db, TENANT, None)
    other = svc.create_key(env.db, OTHER, None)
    h = {"Authorization": f"Bearer {key['key']}"}
    stored = env.db.rows("otp_api_keys")
    assert all(key["key"] not in repr(r) for r in stored)  # only the hash is kept

    sent = client.post("/api/v1/otp/send", json={"phone": PHONE, "mode": "sms", "ref": "o1"}, headers=h)
    assert sent.status_code == 200, sent.text
    otp_id = sent.json()["otp_id"]
    code = _sent_code(env.sms)
    assert client.get(f"/api/v1/otp/{otp_id}", headers={"Authorization": f"Bearer {other['key']}"}).status_code == 404
    wrong = client.post("/api/v1/otp/verify", json={"otp_id": otp_id, "code": "000000" if code != "000000" else "111111"}, headers=h)
    assert wrong.status_code == 200 and wrong.json()["verified"] is False and wrong.json()["attempts_left"] == 4
    ok = client.post("/api/v1/otp/verify", json={"otp_id": otp_id, "code": code}, headers=h)
    assert ok.json()["verified"] is True
    assert client.get(f"/api/v1/otp/{otp_id}", headers=h).json()["status"] == "verified"


def test_api_body_cannot_carry_tenant_or_unknown_fields(env):
    client, _ = _client(env)
    key = svc.create_key(env.db, TENANT, None)
    r = client.post("/api/v1/otp/send", json={"phone": PHONE, "tenant_id": OTHER},
                    headers={"Authorization": f"Bearer {key['key']}"})
    assert r.status_code == 422


# ---------------------------------------------------------------- dashboard

def test_keys_are_owner_only_and_shown_once(env):
    client, holder = _client(env)
    created = client.post("/api/v1/otp-console/keys")
    assert created.status_code == 200 and created.json()["key"].startswith(svc.KEY_PREFIX)
    listed = client.get("/api/v1/otp-console/keys").json()["keys"]
    assert listed and "key" not in listed[0] and "key_hash" not in listed[0]
    client.post("/api/v1/otp-console/keys")
    assert client.post("/api/v1/otp-console/keys").json()["code"] == "too_many_keys"
    holder["ctx"] = {"tenant_id": TENANT, "role": "admin", "user_id": "u2", "permissions": ["settings.manage", "sms.manage"]}
    assert client.post("/api/v1/otp-console/keys").status_code == 403
    assert client.post("/api/v1/otp-console/webhook-secret").status_code == 403


def test_settings_validate_and_refuse_unready_mode(env):
    client, _ = _client(env)
    assert client.put("/api/v1/otp-console/settings", json={"expiry_minutes": 99}).status_code == 400
    assert client.put("/api/v1/otp-console/settings", json={"status_webhook_url": "http://x.com"}).status_code == 400
    env.settings.pop((TENANT, "meta_access_token"))
    r = client.put("/api/v1/otp-console/settings", json={"default_mode": "whatsapp"})
    assert r.status_code == 409 and r.json()["code"] == "mode_not_ready"
    ok = client.put("/api/v1/otp-console/settings", json={"default_mode": "sms", "expiry_minutes": 5})
    assert ok.status_code == 200 and ok.json()["settings"]["expiry_minutes"] == 5
    assert "status_webhook_secret" not in ok.json()["settings"]


@pytest.mark.asyncio
async def test_delivery_report_before_send_returns_is_not_overwritten(env):
    """Regression: Bulk9 delivered the test SMS in 1 s; a report landing before Anril saved
    'sent' was overwritten back to 'sent' and fired a needless WhatsApp backup."""
    async def deliver_first(*_a, **kw):
        otp_id = kw["udf1"][4:]
        svc.apply_sms_report(env.db, TENANT, otp_id, "delivered")
        return {"return": True, "request_id": "REQ1"}
    env.sms.side_effect = deliver_first
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms_then_whatsapp")
    assert view["sms"]["status"] == "delivered"
    assert await svc._fallback_now(env.db, TENANT, view["otp_id"]) is False
    env.wa.assert_not_called()


def test_new_account_can_save_sms_template_before_whatsapp(env):
    env.settings.pop((TENANT, "meta_access_token"))
    saved = svc.save_settings(env.db, TENANT, {"sms_message_id": "999"})
    assert saved["sms_message_id"] == "999" and saved["default_mode"] == "sms_then_whatsapp"


@pytest.mark.asyncio
async def test_wrong_tries_limit_is_the_clients_setting(env):
    env.db.rows("otp_settings")[0]["max_attempts"] = 2
    view = await svc.send_code(env.db, TENANT, phone=PHONE, mode="sms")
    code = _sent_code(env.sms)
    wrong = "000000" if code != "000000" else "111111"
    first = svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=wrong)
    assert first["reason"] == "wrong_code" and first["attempts_left"] == 1
    assert svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=wrong)["reason"] == "locked"
    assert svc.verify(env.db, TENANT, otp_id=view["otp_id"], code=code)["reason"] == "locked"


def test_wrong_tries_setting_is_range_checked(env):
    for bad in (0, 11):
        with pytest.raises(svc.OtpError):
            svc.save_settings(env.db, TENANT, {"max_attempts": bad})
    assert svc.save_settings(env.db, TENANT, {"max_attempts": 3})["max_attempts"] == 3


def test_settings_access_alone_reaches_otp_but_not_keys(env):
    """WhatsApp-only clients: a member with settings access (no SMS permission) can use OTP."""
    client, holder = _client(env)
    holder["ctx"] = {"tenant_id": TENANT, "role": "admin", "user_id": "u3", "permissions": ["settings.manage"]}
    assert client.get("/api/v1/otp-console/overview").status_code == 200
    assert client.post("/api/v1/otp-console/send", json={"phone": PHONE, "mode": "sms"}).status_code == 200
    assert client.get("/api/v1/otp-console/keys").status_code == 403
    holder["ctx"] = {"tenant_id": TENANT, "role": "member", "user_id": "u4", "permissions": ["leads.view"]}
    assert client.get("/api/v1/otp-console/overview").status_code == 403
