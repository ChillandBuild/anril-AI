"""GET /api/v1/templates/usage: where each template is used, in one call."""
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from fake_supabase import FakeSupabase

T1, T2 = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
WABA = "waba-1"


def tpl(db, tenant, name, category="UTILITY", language="en", status="APPROVED"):
    return db.add(
        "message_templates", tenant_id=tenant, name=name, category=category, language=language,
        status=status, body_text="Hi", meta_template_id=f"m-{name}", meta_waba_id=WABA,
    )


@pytest.fixture(autouse=True)
def _settings():
    with patch("app.config_dynamic.get_setting", lambda key, fallback=None, tenant_id=None: fallback):
        yield


def usage(db, tenant=T1):
    from app.services.template_usage import build_usage

    rows = [r for r in db.rows("message_templates") if r["tenant_id"] == tenant]
    return build_usage(db, tenant, rows)


def labels(result, tid):
    return [e["label"] for e in result.get(tid, [])]


def test_every_source_is_mapped():
    db = FakeSupabase()
    a = tpl(db, T1, "welcome_msg")
    b = tpl(db, T1, "instant_hi")
    c = tpl(db, T1, "one_time")
    d = tpl(db, T1, "festival_offer", category="MARKETING")
    e = tpl(db, T1, "nudge_day3")
    f = tpl(db, T1, "otp_code", category="AUTHENTICATION")
    g = tpl(db, T1, "forms_cast")
    h = tpl(db, T1, "staff_alert_tpl", category="MARKETING")
    i = tpl(db, T1, "market_welcome")
    j = tpl(db, T1, "unused_one")
    db.add("auto_message_rules", tenant_id=T1, template_id=a["id"], event="purchased", enabled=True)
    db.add("meta_lead_forms", tenant_id=T1, template_id=b["id"])
    db.add("scheduled_template_sends", tenant_id=T1, template_id=c["id"], template_name="one_time", status="scheduled")
    db.add("scheduled_template_sends", tenant_id=T1, template_id=j["id"], template_name="unused_one", status="sent")  # done: not "used"
    db.add("scheduled_broadcasts", tenant_id=T1, template_name="festival_offer", status="pending")
    db.add("scheduled_broadcasts", tenant_id=T1, template_name="festival_offer", status="running")
    db.add("reengagement_steps", tenant_id=T1, template_name="nudge_day3", fallback_template_name=None)
    db.add("reengagement_steps", tenant_id=T1, template_name="x", fallback_template_name="forms_cast")
    db.add("otp_settings", tenant_id=T1, wa_template_name="otp_code")
    db.add("whatsapp_form_designs", tenant_id=T1, archived=False,
           triggers={"broadcasts": {"enabled": True, "templates": ["forms_cast"]}})
    db.add("app_settings", tenant_id=T1, key="notification_config", value=json.dumps(
        {"whatsapp_notifications": {"enabled": True, "template_id": h["id"]},
         "whatsapp_escalation_notifications": {"enabled": False, "template_id": None}}))
    db.add("app_settings", tenant_id=T1, key="marketplace_welcome_template", value=i["id"])

    r = usage(db)
    assert labels(r, a["id"]) == ["Auto-Messages · Purchased"]
    assert labels(r, b["id"]) == ["Instant forms"]
    assert labels(r, c["id"]) == ["One-time sends"]
    assert labels(r, d["id"]) == ["Reach · 2 campaigns"]
    assert labels(r, e["id"]) == ["Follow-ups"]
    assert labels(r, f["id"]) == ["OTP & SMS"]
    assert sorted(labels(r, g["id"])) == ["Follow-ups", "WhatsApp Forms"]
    assert [x["area"] for x in r[h["id"]]] == ["staff_alert"]
    assert labels(r, i["id"]) == ["Marketplace welcome"]
    assert j["id"] not in r
    assert r[d["id"]][0]["href"] == "/dashboard/outbound-leads"


def test_finished_reach_campaigns_are_marked_ended():
    db = FakeSupabase()
    t = tpl(db, T1, "old_offer", category="MARKETING")
    db.add("scheduled_broadcasts", tenant_id=T1, template_name="old_offer", status="done")
    entry = usage(db)[t["id"]][0]
    assert entry["label"] == "was in Reach · ended" and entry["ended"] is True


def test_fixed_name_templates_are_mapped():
    db = FakeSupabase()
    bill = tpl(db, T1, "anril_order_bill")
    po = tpl(db, T1, "anril_purchase_order")
    stock = tpl(db, T1, "anril_back_in_stock")
    astro = tpl(db, T1, "astro_reply_ready")
    r = usage(db)
    assert labels(r, bill["id"]) == ["Commerce · bills & orders"]
    assert labels(r, po["id"]) == ["Purchases"]
    assert labels(r, stock["id"]) == ["Back in stock"]
    assert labels(r, astro["id"]) == ["Reply ready"]


def test_other_tenants_rows_never_leak():
    db = FakeSupabase()
    mine = tpl(db, T1, "shared_name")
    theirs = tpl(db, T2, "shared_name")
    db.add("reengagement_steps", tenant_id=T2, template_name="shared_name")
    db.add("auto_message_rules", tenant_id=T2, template_id=theirs["id"], event="signed_up", enabled=True)
    r = usage(db, T1)
    assert mine["id"] not in r and theirs["id"] not in r


def test_a_failing_source_is_left_out_not_fatal():
    db = FakeSupabase()
    t = tpl(db, T1, "nudge_day3")
    db.add("reengagement_steps", tenant_id=T1, template_name="nudge_day3")
    from app.services import template_usage

    def boom(db, tenant_id):
        raise RuntimeError("table missing")

    with patch.object(template_usage, "_SOURCES", (boom, template_usage._follow_ups)):
        r = usage(db)
    assert labels(r, t["id"]) == ["Follow-ups"]


def test_route_is_tenant_scoped_and_filters_by_waba():
    from app.dependencies.auth import get_current_user
    from app.dependencies.tenant import get_tenant_and_role, get_tenant_id
    from app.main import app

    db = FakeSupabase()
    mine = tpl(db, T1, "nudge_day3")
    other_account = db.add(
        "message_templates", tenant_id=T1, name="old_acct", category="UTILITY", language="en", status="APPROVED",
        body_text="Hi", meta_template_id="m-old", meta_waba_id="waba-other",
    )
    db.add("reengagement_steps", tenant_id=T1, template_name="nudge_day3")
    db.add("reengagement_steps", tenant_id=T1, template_name="old_acct")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
    app.dependency_overrides[get_tenant_id] = lambda: T1
    app.dependency_overrides[get_tenant_and_role] = lambda: {
        "tenant_id": T1, "role": "caller", "permissions": ["templates.view"], "user_id": "u",
    }
    try:
        with patch("app.routes.templates.get_supabase", return_value=db), \
             patch("app.routes.templates.get_setting", lambda k, **kw: WABA if k == "meta_waba_id" else None):
            res = TestClient(app).get("/api/v1/templates/usage")
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200
    data = res.json()["data"]
    assert list(data) == [mine["id"]] and other_account["id"] not in data


def test_route_needs_templates_view():
    from app.dependencies.auth import get_current_user
    from app.dependencies.tenant import get_tenant_and_role
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u"}
    app.dependency_overrides[get_tenant_and_role] = lambda: {
        "tenant_id": T1, "role": "caller", "permissions": ["leads.view"], "user_id": "u",
    }
    try:
        assert TestClient(app).get("/api/v1/templates/usage").status_code == 403
    finally:
        app.dependency_overrides.clear()
