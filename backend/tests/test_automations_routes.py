"""v9.2 #26: /api/v1/automations endpoints (permissions, shapes, tenant scope)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient
from fake_supabase import FakeSupabase

from app.dependencies.auth import get_current_user
from app.dependencies.tenant import get_tenant_and_role
from app.main import app

T = "t1"


@pytest.fixture
def env():
    db = FakeSupabase()
    db.add("tenants", id=T, name="Sri Stores", contact_phone="9876543210")
    db.add("message_templates", id="tpl-a", tenant_id=T, name="thanks_order", status="APPROVED", meta_waba_id="w1",
           language="en", body_text="Hi {{1}}")
    db.add("auto_message_rules", id="r1", tenant_id=T, event="purchased", template_id="tpl-a", enabled=True)
    role = {"tenant_id": T, "role": "owner", "permissions": []}
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    app.dependency_overrides[get_tenant_and_role] = lambda: role
    with patch("app.routes.automations.get_supabase", return_value=db), \
            patch("app.services.call_details_share.get_setting", return_value="w1"):
        yield TestClient(app), db, role
    app.dependency_overrides.clear()


def test_alerts_list_and_toggle(env):
    c, db, _ = env
    r = c.get("/api/v1/automations/alerts")
    assert r.status_code == 200
    body = r.json()
    assert body["quiet_time"]["on"] is True and body["quiet_time"]["start_hour"] == 21 and body["quiet_time"]["end_hour"] == 9
    keys = {a["key"] for a in body["alerts"]}
    assert "handover_new" in keys
    r = c.put("/api/v1/automations/alerts/batch_expiry", json={"on": False, "who": ["owner"]})
    assert r.status_code == 200 and r.json()["on"] is False and r.json()["who"] == ["owner"]
    assert c.put("/api/v1/automations/alerts/nope", json={"on": False}).status_code == 404
    assert c.put("/api/v1/automations/alerts/batch_expiry", json={"on": True, "who": ["x"]}).status_code == 422


def test_quiet_time_route(env):
    c, *_ = env
    r = c.put("/api/v1/automations/quiet-time", json={"on": True, "start_hour": 22, "end_hour": 7})
    assert r.status_code == 200 and r.json()["start_hour"] == 22 and r.json()["is_default"] is False
    assert c.put("/api/v1/automations/quiet-time", json={"on": True, "start_hour": 5, "end_hour": 5}).status_code == 422
    assert c.put("/api/v1/automations/quiet-time", json={"on": True, "start_hour": 30, "end_hour": 5}).status_code == 422


def test_permissions(env):
    c, _, role = env
    role.update(role="staff", permissions=["templates.view"])
    assert c.get("/api/v1/automations/alerts").status_code == 403            # needs settings.view
    assert c.get("/api/v1/automations/list").status_code == 200              # settings.view OR templates.view
    assert c.put("/api/v1/automations/toggle", json={"key": "auto_message:r1", "on": False}).status_code == 403
    role.update(permissions=["settings.view"])
    assert c.get("/api/v1/automations/alerts").status_code == 200
    assert c.put("/api/v1/automations/alerts/batch_expiry", json={"on": False}).status_code == 403
    assert c.put("/api/v1/automations/quiet-time", json={"on": False}).status_code == 403
    assert c.put("/api/v1/automations/evening-summary", json={"on": True}).status_code == 403
    role.update(permissions=[])
    assert c.get("/api/v1/automations/list").status_code == 403


def test_list_and_toggle(env):
    c, db, _ = env
    body = c.get("/api/v1/automations/list").json()
    assert body["paused_count"] == 0
    assert {a["key"] for a in body["automations"]} >= {"auto_message:r1", "feedback_ask", "evening_summary", "comeback_offer"}
    assert c.put("/api/v1/automations/toggle", json={"key": "auto_message:r1", "on": False}).json()["on"] is False
    assert db.rows("auto_message_rules")[0]["enabled"] is False
    assert c.put("/api/v1/automations/toggle", json={"key": "scheduled_templates", "on": False}).status_code == 422
    assert c.put("/api/v1/automations/toggle", json={"key": "auto_message:zzz", "on": False}).status_code == 404
    db.rows("message_templates")[0]["status"] = "REJECTED"
    assert c.put("/api/v1/automations/toggle", json={"key": "auto_message:r1", "on": True}).status_code == 409
    assert c.get("/api/v1/automations/list").json()["paused_count"] >= 1      # shown as paused, red banner


def test_evening_summary_routes(env):
    c, db, _ = env
    s = c.get("/api/v1/automations/evening-summary").json()
    assert s["on"] is False and s["note"] == "Waiting for WhatsApp to approve"
    assert c.put("/api/v1/automations/evening-summary", json={"on": True}).json()["on"] is True


def test_comeback_routes(env):
    c, db, _ = env
    s = c.get("/api/v1/automations/comeback-offer").json()
    assert s["on"] is False and "0.86" in s["cost_note"] and [t["name"] for t in s["approved_templates"]] == ["thanks_order"]
    r = c.put("/api/v1/automations/comeback-offer", json={"on": True, "template_name": "thanks_order", "offer": ""})
    assert r.status_code == 422
    r = c.put("/api/v1/automations/comeback-offer",
              json={"on": True, "template_name": "thanks_order", "offer": "10% off", "code": "BACK10", "ends_on": "2099-01-01"})
    assert r.status_code == 200 and r.json()["on"] is True and r.json()["code"] == "BACK10"
    r = c.put("/api/v1/automations/comeback-offer", json={"on": True, "template_name": "missing", "offer": "x"})
    assert r.status_code == 422
