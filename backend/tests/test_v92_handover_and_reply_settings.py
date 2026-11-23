"""v9.2 #171 photo/voice rule, #157 after-hours message + stale handover alert, #23 connection status,
#24 client error reports."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
from app.routes import ai_teach as teach_routes
from app.routes import client_errors, connection_status, reply_settings
from app.routes.auto_messages import _SlidingWindow
from app.services import after_hours, ai_teach, handover_alerts, notification_config
from fake_supabase import FakeSupabase

T = "t1"
IST = after_hours.IST
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def _client(router, db, monkeypatch, *modules, role="owner", permissions=(), tenant=T):
    for m in modules:
        monkeypatch.setattr(m, "get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(router, prefix="/x")
    ctx = {"tenant_id": tenant, "role": role, "user_id": "u1", "caller_id": None, "permissions": list(permissions)}
    app.dependency_overrides[get_tenant_and_role] = lambda: ctx
    app.dependency_overrides[get_tenant_id] = lambda: tenant
    return TestClient(app)


# ------------------------------------------------------------------ #171 photo / voice note rule

@pytest.fixture(autouse=True)
def _clean_cache():
    ai_teach.clear_cache()
    yield
    ai_teach.clear_cache()


def test_media_rule_is_empty_until_set_and_shows_in_the_prompt_once_saved():
    db = FakeSupabase()
    assert ai_teach.read_media_rule(db, T) == ""
    assert "PHOTO OR VOICE NOTE" not in ai_teach.prompt_block(db, T, NOW)
    ai_teach.save_media_rule(db, T, "  Ask what they want to know   about it. ")
    assert ai_teach.read_media_rule(db, T) == "Ask what they want to know about it."
    block = ai_teach.prompt_block(db, T, NOW)
    assert "WHEN A CUSTOMER SENDS A PHOTO OR VOICE NOTE: Ask what they want to know about it." in block


def test_media_rule_over_the_limit_is_refused_and_empty_clears_it():
    db = FakeSupabase()
    with pytest.raises(ai_teach.TeachError):
        ai_teach.save_media_rule(db, T, "x" * (ai_teach.MAX_MEDIA_RULE + 1))
    ai_teach.save_media_rule(db, T, "x" * ai_teach.MAX_MEDIA_RULE)
    ai_teach.save_media_rule(db, T, "")
    assert ai_teach.read_media_rule(db, T) == ""
    assert "PHOTO OR VOICE NOTE" not in ai_teach.prompt_block(db, T, NOW)


def test_media_rule_is_per_business():
    db = FakeSupabase()
    ai_teach.save_media_rule(db, "t1", "Hand to a person.")
    assert ai_teach.read_media_rule(db, "t2") == ""


def test_media_rule_routes_and_permissions(monkeypatch):
    db = FakeSupabase()
    owner = _client(teach_routes.router, db, monkeypatch, teach_routes)
    assert owner.get("/x/media-rule").json() == {"rule": "", "max_chars": ai_teach.MAX_MEDIA_RULE}
    res = owner.put("/x/media-rule", json={"rule": "Hand to a person."})
    assert res.status_code == 200 and res.json()["rule"] == "Hand to a person."
    assert owner.get("/x/media-rule").json()["rule"] == "Hand to a person."
    assert owner.put("/x/media-rule", json={"rule": "y" * 301}).status_code in (400, 422)
    # a viewer can read, not change
    viewer = _client(teach_routes.router, db, monkeypatch, teach_routes, role="agent", permissions=["knowledge.view"])
    assert viewer.get("/x/media-rule").status_code == 200
    assert viewer.put("/x/media-rule", json={"rule": "nope"}).status_code == 403
    nobody = _client(teach_routes.router, db, monkeypatch, teach_routes, role="agent", permissions=[])
    assert nobody.get("/x/media-rule").status_code == 403


# ------------------------------------------------------------------ #157 after-hours message

def _ist(h, m=0):
    return datetime(2026, 11, 23, h, m, tzinfo=IST)


def test_clean_keeps_only_sane_values():
    assert after_hours.clean(None) == after_hours.DEFAULT
    out = after_hours.clean({"enabled": "yes", "open": "9am", "close": "22:30", "message": "  Back   soon ", "x": 1})
    assert out == {"enabled": False, "open": "09:00", "close": "22:30", "message": "Back soon"}


def test_validate_rules():
    with pytest.raises(after_hours.AfterHoursError):
        after_hours.validate({"open": "25:00", "close": "21:00", "message": "hi", "enabled": True})
    with pytest.raises(after_hours.AfterHoursError):
        after_hours.validate({"open": "09:00", "close": "21:00", "message": "", "enabled": True})
    with pytest.raises(after_hours.AfterHoursError):
        after_hours.validate({"open": "09:00", "close": "21:00", "message": "x" * 301, "enabled": False})
    assert after_hours.validate({"open": "09:00", "close": "21:00", "message": "", "enabled": False})["enabled"] is False


@pytest.mark.parametrize("cfg, when, expected", [
    ({"open": "09:00", "close": "21:00"}, _ist(8, 59), True),
    ({"open": "09:00", "close": "21:00"}, _ist(9, 0), False),
    ({"open": "09:00", "close": "21:00"}, _ist(20, 59), False),
    ({"open": "09:00", "close": "21:00"}, _ist(21, 0), True),
    ({"open": "18:00", "close": "02:00"}, _ist(23, 0), False),   # night shift, inside
    ({"open": "18:00", "close": "02:00"}, _ist(1, 0), False),
    ({"open": "18:00", "close": "02:00"}, _ist(12, 0), True),
    ({"open": "09:00", "close": "09:00"}, _ist(3, 0), False),    # open == close: always in
])
def test_is_after_hours(cfg, when, expected):
    assert after_hours.is_after_hours(cfg, when) is expected


def test_is_after_hours_converts_to_india_time():
    # 04:00 UTC is 09:30 IST: inside 09:00-21:00
    assert after_hours.is_after_hours({"open": "09:00", "close": "21:00"}, datetime(2026, 11, 23, 4, 0, tzinfo=timezone.utc)) is False


def test_prompt_line_only_when_on_and_out_of_hours():
    db = FakeSupabase()
    assert after_hours.prompt_line(db, T, _ist(23)) == ""                      # never set
    after_hours.save(db, T, {"enabled": True, "open": "09:00", "close": "21:00", "message": "We reply at 9."})
    line = after_hours.prompt_line(db, T, _ist(23))
    assert "AFTER HOURS" in line and "We reply at 9." in line and "09:00" in line
    assert after_hours.prompt_line(db, T, _ist(12)) == ""                      # team is in
    assert after_hours.prompt_line(db, "t2", _ist(23)) == ""                   # another business
    after_hours.save(db, T, {"enabled": False, "open": "09:00", "close": "21:00", "message": "We reply at 9."})
    assert after_hours.prompt_line(db, T, _ist(23)) == ""                      # switched off


def test_after_hours_routes_and_permissions(monkeypatch):
    db = FakeSupabase()
    owner = _client(reply_settings.router, db, monkeypatch, reply_settings)
    assert owner.get("/x/after-hours").json()["enabled"] is False
    body = {"enabled": True, "open": "10:00", "close": "20:00", "message": "Closed, back at 10."}
    res = owner.put("/x/after-hours", json=body)
    assert res.status_code == 200 and res.json()["open"] == "10:00" and res.json()["max_chars"] == after_hours.MAX_MESSAGE
    assert owner.get("/x/after-hours").json()["message"] == "Closed, back at 10."
    assert owner.put("/x/after-hours", json={**body, "message": ""}).status_code == 422
    viewer = _client(reply_settings.router, db, monkeypatch, reply_settings, role="agent", permissions=["settings.view"])
    assert viewer.get("/x/after-hours").status_code == 200
    assert viewer.put("/x/after-hours", json=body).status_code == 403
    nobody = _client(reply_settings.router, db, monkeypatch, reply_settings, role="agent", permissions=[])
    assert nobody.get("/x/after-hours").status_code == 403


# ------------------------------------------------------------------ #157 nobody replied after a handover

@pytest.fixture
def pushes(monkeypatch):
    sent = []
    import app.services.web_push as wp
    monkeypatch.setattr(wp, "send_user_push", lambda *a, **k: sent.append(k))
    notification_config._policy_cache.clear()
    return sent


def _setup(db, minutes_old=20, status="pending", **extra):
    db.add("tenant_users", tenant_id=T, user_id="owner1", role="owner")
    db.add("tenant_users", tenant_id=T, user_id="agent1", role="agent")
    lead = db.add("leads", tenant_id=T, name="Asha")
    opened = (NOW - timedelta(minutes=minutes_old)).isoformat()
    h = db.add("chat_handovers", tenant_id=T, lead_id=lead["id"], status=status, opened_at=opened, stale_alerted_at=None, **extra)
    return lead, h


def _alerts(db):
    return [r for r in db.rows("app_notifications") if r["type"] == "handover_unanswered"]


def test_alerts_the_owner_once_after_fifteen_minutes(pushes):
    db = FakeSupabase()
    lead, h = _setup(db)
    assert handover_alerts.sweep_stale_handovers(NOW, db) == 1
    rows = _alerts(db)
    assert len(rows) == 1 and rows[0]["user_id"] == "owner1" and "Asha" in rows[0]["message"]
    assert next(r for r in db.rows("chat_handovers") if r["id"] == h["id"])["stale_alerted_at"]
    # the next 5-minute run does nothing
    assert handover_alerts.sweep_stale_handovers(NOW + timedelta(minutes=5), db) == 0
    assert len(_alerts(db)) == 1


def test_younger_than_fifteen_minutes_is_left_alone(pushes):
    db = FakeSupabase()
    _setup(db, minutes_old=14)
    assert handover_alerts.sweep_stale_handovers(NOW, db) == 0 and _alerts(db) == []


def test_older_than_two_hours_is_left_alone(pushes):
    db = FakeSupabase()
    _setup(db, minutes_old=3 * 60)
    assert handover_alerts.sweep_stale_handovers(NOW, db) == 0 and _alerts(db) == []


def test_a_missing_column_is_logged_once_and_returns_zero(pushes, caplog):
    class Broken:
        def table(self, *_):
            raise RuntimeError("column chat_handovers.stale_alerted_at does not exist")
    handover_alerts._query_failed_logged = False
    with caplog.at_level("WARNING"):
        assert handover_alerts.sweep_stale_handovers(NOW, Broken()) == 0
        assert handover_alerts.sweep_stale_handovers(NOW, Broken()) == 0
    assert sum("migration 332" in r.message for r in caplog.records) == 1
    handover_alerts._query_failed_logged = False


def test_resolved_handover_is_left_alone(pushes):
    db = FakeSupabase()
    _setup(db, status="resolved")
    assert handover_alerts.sweep_stale_handovers(NOW, db) == 0 and _alerts(db) == []


def test_a_teammate_reply_means_no_alert(pushes):
    db = FakeSupabase()
    lead, h = _setup(db)
    db.add("messages", tenant_id=T, lead_id=lead["id"], direction="outbound", sent_by_user_id="agent1",
           created_at=(NOW - timedelta(minutes=5)).isoformat())
    assert handover_alerts.sweep_stale_handovers(NOW, db) == 0 and _alerts(db) == []


def test_an_ai_reply_or_a_reply_before_the_handover_does_not_count(pushes):
    db = FakeSupabase()
    lead, h = _setup(db)
    db.add("messages", tenant_id=T, lead_id=lead["id"], direction="outbound", sent_by_user_id=None,
           created_at=(NOW - timedelta(minutes=5)).isoformat())
    db.add("messages", tenant_id=T, lead_id=lead["id"], direction="outbound", sent_by_user_id="agent1",
           created_at=(NOW - timedelta(minutes=60)).isoformat())
    assert handover_alerts.sweep_stale_handovers(NOW, db) == 1


def test_owner_who_switched_the_alert_off_gets_nothing(pushes):
    db = FakeSupabase()
    _setup(db)
    db.add("app_settings", tenant_id=T, key="notification_config", value=json.dumps({"events": {"handover_unanswered": False}}))
    handover_alerts.sweep_stale_handovers(NOW, db)
    assert _alerts(db) == []


def test_only_owners_are_told_and_other_businesses_are_not_mixed(pushes):
    db = FakeSupabase()
    _setup(db)
    db.add("tenant_users", tenant_id="t2", user_id="other-owner", role="owner")
    handover_alerts.sweep_stale_handovers(NOW, db)
    assert {r["user_id"] for r in _alerts(db)} == {"owner1"}


def test_alert_is_in_the_catalog_and_on_by_default():
    from app.services.alert_catalog import alert_keys
    assert "handover_unanswered" in alert_keys()
    assert notification_config._NOTIFICATION_CONFIG_DEFAULT["events"]["handover_unanswered"] is True


# ------------------------------------------------------------------ #23 WhatsApp disconnected banner

def test_connection_status_lists_only_disconnected_unarchived_numbers(monkeypatch):
    db = FakeSupabase()
    db.add("phone_numbers", tenant_id=T, display_name="Main shop", phone="+911234567890", status="active", meta_status="DISCONNECTED")
    db.add("phone_numbers", tenant_id=T, display_name="Old", status="archived", meta_status="DISCONNECTED")
    db.add("phone_numbers", tenant_id=T, display_name="Fine", status="active", meta_status="CONNECTED")
    db.add("phone_numbers", tenant_id="t2", display_name="Not mine", status="active", meta_status="DISCONNECTED")
    client = _client(connection_status.router, db, monkeypatch, connection_status, role="agent")
    data = client.get("/x/whatsapp").json()
    assert data["disconnected"] is True
    assert [n["name"] for n in data["numbers"]] == ["Main shop"]
    assert "phone" not in json.dumps(data) and "1234567890" not in json.dumps(data)


def test_connection_status_all_good_and_read_failure(monkeypatch):
    db = FakeSupabase()
    db.add("phone_numbers", tenant_id=T, display_name="Fine", status="active", meta_status="CONNECTED")
    client = _client(connection_status.router, db, monkeypatch, connection_status, role="agent")
    assert client.get("/x/whatsapp").json() == {"disconnected": False, "numbers": []}

    class Broken:
        def table(self, *_):
            raise RuntimeError("db down")
    monkeypatch.setattr(connection_status, "get_supabase", lambda: Broken())
    assert client.get("/x/whatsapp").json() == {"disconnected": False, "numbers": []}


# ------------------------------------------------------------------ #24 error reports

def test_clean_path_and_digest():
    assert client_errors.clean_path("/dashboard/leads/123e4567-e89b-12d3-a456-426614174000?phone=9876543210#x") == "/dashboard/leads/:id"
    assert client_errors.clean_path("/dashboard/orders/20260001") == "/dashboard/orders/:id"
    assert client_errors.clean_path("https://evil.example/a") is None and client_errors.clean_path("") is None
    assert client_errors.clean_digest("abc123 <script>-_") == "abc123script-_"
    assert client_errors.clean_digest("   ") is None


def test_error_report_is_stored_cleaned_and_rate_limited(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(client_errors, "_limiter", _SlidingWindow(5, 3600))
    client = _client(client_errors.router, db, monkeypatch, client_errors, role="agent")
    res = client.post("/x", json={"digest": "d1g3st", "path": "/dashboard/leads/9876543210?name=Asha"})
    assert res.status_code == 200 and res.json() == {"ok": True}
    row = db.rows("client_error_reports")[0]
    assert row == {**row, "tenant_id": T, "digest": "d1g3st", "path": "/dashboard/leads/:id"}
    for _ in range(10):
        assert client.post("/x", json={"digest": "again", "path": "/dashboard"}).status_code == 200
    assert len(db.rows("client_error_reports")) == 5  # past 5 an hour the report is dropped, the page is unaffected


def test_error_report_survives_a_missing_table(monkeypatch):
    class NoTable:
        def table(self, *_):
            raise RuntimeError('relation "client_error_reports" does not exist')
    monkeypatch.setattr(client_errors, "_limiter", _SlidingWindow(5, 3600))
    client = _client(client_errors.router, FakeSupabase(), monkeypatch)
    monkeypatch.setattr(client_errors, "get_supabase", lambda: NoTable())
    assert client.post("/x", json={"digest": "x", "path": "/a"}).json() == {"ok": True}


def test_error_report_log_line_cannot_be_split_by_a_newline(monkeypatch, caplog):
    monkeypatch.setattr(client_errors, "_limiter", _SlidingWindow(5, 3600))
    client = _client(client_errors.router, FakeSupabase(), monkeypatch, client_errors, role="agent")
    with caplog.at_level("WARNING"):
        client.post("/x", json={"digest": "ok", "path": "/a\nFAKE LOG LINE"})
    line = next(r.getMessage() for r in caplog.records if "client error report:" in r.getMessage())
    assert "\n" not in line
