"""Anril AI (client connector) setup tools: numbers, calling, scripts, call review, website, SMS, OTP.

Each tool is proven to: show the signed-in client's data, never another client's row, never return
a secret, and never write (a guard database records every write / RPC attempt and the test asserts
there were none). The database is fake; nothing here touches the live one."""
import json
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import app.routes.call_review  # noqa: F401  (imported lazily by the tool; patched below)
from app.client_mcp import tools_read_setup as tools
from app.client_mcp import wrapper
from app.db import supabase as supabase_db
from app.services import otp_overview as otp_overview_svc
from tests.fake_supabase import FakeSupabase
from tests.test_client_mcp_core import A, B

REAL_GET_SUPABASE = supabase_db.get_supabase
WRITES = ("insert", "update", "upsert", "delete")

NOW = datetime.now(timezone.utc)
RECENT = (NOW - timedelta(hours=2)).isoformat()
OLD = (NOW - timedelta(days=60)).isoformat()

LEAD_A = "11111111-1111-1111-1111-111111111111"
LEAD_B = "22222222-2222-2222-2222-222222222222"
SCRIPT_A = "33333333-3333-3333-3333-333333333333"
SCRIPT_B = "44444444-4444-4444-4444-444444444444"
OTP_A = "55555555-5555-5555-5555-555555555555"
OTP_B = "66666666-6666-6666-6666-666666666666"

# Every one of these is planted in the database and must never appear in an answer.
SECRETS = [
    "SECRET-WA-TOKEN-A", "SECRET-API-KEY-A", "SECRET-VOICE-KEY", "SECRET-TELECMI-A", "SECRET-BULK9-A",
    "SECRET-WEBHOOK-A", "SECRET-OTP-HASH", "SECRET-OTP-ENC", "SECRET-RECORDING", "anr_otp_live_AAAA",
    "SECRET-FB-TOKEN", "123456", "https://hooks.example/status",
]
OTHER_CLIENT = ["SECRET-B", "B-ONLY"]  # anything of client B's contains one of these


class _GuardTable:
    def __init__(self, guard, inner, name):
        self._guard, self._inner, self._name = guard, inner, name

    def __getattr__(self, attr):
        if attr in WRITES:
            self._guard.attempts.append((attr, self._name))
            raise supabase_db.ReadOnlyViolation(f"{attr} on {self._name}")
        return getattr(self._inner, attr)


class Guard:
    """The fake database as the connector sees it: reads pass, every write or RPC is recorded."""

    def __init__(self, db):
        self._db, self.attempts = db, []

    def table(self, name):
        return _GuardTable(self, self._db.table(name), name)

    from_ = table

    def rpc(self, fn, *args, **kwargs):
        self.attempts.append(("rpc", fn))
        raise supabase_db.ReadOnlyViolation(f"rpc {fn}")

    def __getattr__(self, attr):
        self.attempts.append(("client", attr))
        raise supabase_db.ReadOnlyViolation(f"client.{attr}")


def run(fn, db, tenant=A, **kwargs):
    """Run a tool's plain function as `tenant`'s owner; fail if it tried to write."""
    guard = Guard(db)
    otp_overview_svc._cache.clear()
    with ExitStack() as stack:
        for name, module in list(sys.modules.items()):
            if name.startswith("app.") and getattr(module, "get_supabase", None) is REAL_GET_SUPABASE:
                stack.enter_context(patch.object(module, "get_supabase", return_value=guard))
        stack.enter_context(wrapper.acting_as(tenant))
        out = fn(**kwargs)
    assert guard.attempts == [], f"{fn.__name__} tried to write: {guard.attempts}"
    return out


def text(answer) -> str:
    return json.dumps(answer, default=str)


def assert_no_secrets(answer):
    blob = text(answer)
    for secret in SECRETS:
        assert secret not in blob, f"{secret!r} leaked"


def assert_only_a(answer):
    blob = text(answer)
    for marker in OTHER_CLIENT:
        assert marker not in blob, f"client B's {marker!r} leaked"


def seed() -> FakeSupabase:
    db = FakeSupabase()
    db.add("tenants", id=A, name="AstroTamil", status="active", enabled_features=["whatsapp", "sms"])
    db.add("tenants", id=B, name="Other Shop", status="active", enabled_features=["whatsapp", "sms"])

    # numbers
    db.add("phone_numbers", id="num-a", tenant_id=A, number="+919000000001", display_name="A Shop", role="primary",
           status="active", provider="meta_cloud", quality_rating="green", messaging_tier=1000, meta_status="CONNECTED",
           paused_outbound=False, warm_up_started_at=OLD, access_token="SECRET-WA-TOKEN-A", api_key="SECRET-API-KEY-A")
    db.add("phone_numbers", id="num-b", tenant_id=B, number="+918888888888", display_name="SECRET-B shop", role="primary",
           status="active", quality_rating="green", messaging_tier=1000, meta_status="CONNECTED")
    db.add("voice_numbers", id="vn-a", tenant_id=A, number="044-1111", display_name="A line", provider="telecmi",
           status="active", pickup_rate=80, calls_today=3, spam_score=1, is_primary=True, secret_key="SECRET-VOICE-KEY")
    db.add("voice_numbers", id="vn-b", tenant_id=B, number="044-9999", display_name="SECRET-B line", status="active",
           spam_score=0)
    db.add("tenant_subscription_items", tenant_id=A, feature_key="inbound_messaging", quantity=1)

    # calling
    db.add("app_settings", tenant_id=A, key="telecalling_config", is_secret=False, value=json.dumps(
        {"enabled": True, "calling_provider": "sim_basic", "telecmi_secret": "SECRET-TELECMI-A",
         "targets": {"daily_calls": 40}}))
    db.add("app_settings", tenant_id=B, key="telecalling_config", is_secret=False, value=json.dumps(
        {"enabled": True, "calling_provider": "telecmi", "targets": {"daily_calls": 999}}))
    db.add("callers", id="caller-a", tenant_id=A, name="Karthik R", active=True, user_id="u-a", team_id="team-a",
           last_sync_at=RECENT, app_version=3)
    db.add("callers", id="caller-b", tenant_id=B, name="B-ONLY caller", active=True, user_id="u-b")
    db.add("call_teams", id="team-a", tenant_id=A, name="Morning team")
    db.add("call_teams", id="team-b", tenant_id=B, name="B-ONLY team")
    db.add("call_scripts", id=SCRIPT_A, tenant_id=A, name="Welcome script", segment="A", is_default=True, active=True,
           steps=[{"order": 1, "text": "Say hello"}, {"order": 2, "text": "Ask budget"}])
    db.add("call_scripts", id=SCRIPT_B, tenant_id=B, name="B-ONLY script", segment="A", is_default=True, active=True,
           steps=[{"order": 1, "text": "B-ONLY"}])

    # call review
    db.add("leads", id=LEAD_A, tenant_id=A, name="Priya", phone="919000000002", segment="B", source="whatsapp",
           assigned_to="caller-a", deleted_at=None, created_at=RECENT)
    db.add("leads", id=LEAD_B, tenant_id=B, name="SECRET-B lead", phone="919999999999", segment="A", source="whatsapp",
           deleted_at=None, created_at=RECENT)
    db.add("call_logs", id="call-a", tenant_id=A, lead_id=LEAD_A, caller_id="caller-a", created_at=RECENT,
           status="completed", duration_seconds=90, score=72, score_status="scored", provider="sim_basic",
           recording_url="https://store.example/rec.mp3?token=SECRET-RECORDING",
           ai_summary="Asked for a quote", transcript="Hello\nbudget?\nthanks")
    db.add("call_logs", id="call-b", tenant_id=B, lead_id=LEAD_B, caller_id="caller-b", created_at=RECENT,
           status="completed", duration_seconds=50, score=50, score_status="scored", provider="telecmi",
           ai_summary="B-ONLY summary")

    # website, forms, setup
    db.add("qr_links", id="qr-a", tenant_id=A, code="ABC123", name="Shop door", first_message="Hi from the door",
           archived=False, created_at=RECENT)
    db.add("qr_links", id="qr-b", tenant_id=B, code="BBB999", name="B-ONLY door", first_message="x", archived=False,
           created_at=RECENT)
    db.add("app_settings", tenant_id=A, key="intake_config", is_secret=False, value=json.dumps(
        {"enabled": True, "offer_message": "Book a call", "packages": [{"key": "p1", "name": "Basic"}]}))
    db.add("app_settings", tenant_id=B, key="intake_config", is_secret=False, value=json.dumps(
        {"enabled": True, "offer_message": "B-ONLY offer"}))
    db.add("app_settings", tenant_id=A, key="facebook_page_id", value="page-a", is_secret=False)
    db.add("app_settings", tenant_id=A, key="facebook_access_token", value="SECRET-FB-TOKEN", is_secret=True)
    db.add("app_settings", tenant_id=A, key="meta_access_token", value="SECRET-WA-TOKEN-A", is_secret=True)
    db.add("app_settings", tenant_id=A, key="meta_phone_number_id", value="123", is_secret=False)
    db.add("app_settings", tenant_id=B, key="instagram_access_token", value="SECRET-B-IG", is_secret=True)
    db.add("meta_lead_forms", tenant_id=A, form_id="form-a", name="Quote form", status="ACTIVE",
           meta_created_at=RECENT, questions=[{}, {}])
    db.add("meta_lead_forms", tenant_id=B, form_id="form-b", name="B-ONLY form", status="ACTIVE",
           meta_created_at=RECENT, questions=[])
    db.add("meta_form_leads", tenant_id=A, form_id="form-a", meta_created_at=RECENT)
    db.add("meta_form_leads", tenant_id=A, form_id="form-a", meta_created_at=RECENT)
    db.add("meta_form_leads", tenant_id=B, form_id="form-b", meta_created_at=RECENT)
    db.add("messages", tenant_id=A, channel="whatsapp", direction="inbound", created_at=RECENT)
    db.add("messages", tenant_id=B, channel="instagram", direction="inbound", created_at=RECENT)
    db.add("incidents", tenant_id=A, type="token_invalid", created_at=RECENT,
           detail={"channel": "facebook", "error": "Session has expired"})
    db.add("incidents", tenant_id=B, type="token_invalid", created_at=RECENT,
           detail={"channel": "instagram", "error": "B-ONLY expired"})

    # SMS
    db.add("app_settings", tenant_id=A, key="bulk9_api_key", value="SECRET-BULK9-A", is_secret=True)
    db.add("app_settings", tenant_id=A, key="sms_support_contact", value="support@a.example", is_secret=False)
    db.add("sms_templates", id="st-a", tenant_id=A, sender_id="ANRIL", entity_id="1101", entity_name="A Ltd",
           message_id=77, dlt_template_id="d-77", message="Your code is {#var#}", var_count=1, template_type="otp",
           status="ready", last_synced_at=RECENT, created_at=RECENT)
    db.add("sms_templates", id="st-b", tenant_id=B, sender_id="BSEC", entity_id="9", entity_name="SECRET-B Ltd",
           message_id=1, message="SECRET-B tpl", var_count=1, status="ready", created_at=RECENT)
    db.add("sms_wallet", tenant_id=A, sms_count=1234, checked_at=RECENT)
    db.add("sms_wallet", tenant_id=B, sms_count=99, checked_at=RECENT)
    db.add("sms_dlt_submissions", tenant_id=A, kind="entity", entity_id="2202", entity_name="A Two", created_at=RECENT)
    db.add("sms_campaigns", id="camp-a", tenant_id=A, name="Diwali SMS", template_text="Offer {#var#}", sender_id="ANRIL",
           template_type="promo", status="completed", deleted_at=None, created_at=RECENT)
    db.add("sms_campaigns", id="camp-b", tenant_id=B, name="B-ONLY camp", template_text="x", sender_id="BSEC",
           template_type="promo", status="completed", deleted_at=None, created_at=RECENT)
    db.add("sms_messages", id="sm-1", tenant_id=A, campaign_id="camp-a", phone="919000000003", content="Diwali offer",
           status="delivered", sms_count=1, created_at=RECENT, submitted_at=RECENT)
    db.add("sms_messages", id="sm-2", tenant_id=A, phone="919000000004", content="Your OTP is 123456 for login",
           status="delivered", sms_count=1, created_at=RECENT, submitted_at=RECENT)
    db.add("sms_messages", id="sm-3", tenant_id=B, phone="919999999998", content="SECRET-B message", status="failed",
           sms_count=1, created_at=RECENT)

    # OTP
    db.add("otp_requests", id=OTP_A, tenant_id=A, phone="919000000005", mode="sms", source="anril", origin="api",
           status="verified", attempts=1, sms_status="delivered", whatsapp_status="none", code_masked="12****",
           code_hash="SECRET-OTP-HASH", code_enc="SECRET-OTP-ENC", ref="order-1", created_at=RECENT,
           expires_at=RECENT, api_key_id="otk-a")
    db.add("otp_requests", id=OTP_B, tenant_id=B, phone="919999999997", mode="sms", source="anril", origin="api",
           status="pending", attempts=0, sms_status="sent", whatsapp_status="none", ref="SECRET-B-ref",
           created_at=RECENT, expires_at=RECENT)
    db.add("otp_api_keys", id="otk-a", tenant_id=A, key_prefix="anr_otp_live_AAAA", key_hash="SECRET-OTP-HASH",
           status="active", created_at=RECENT)
    db.add("otp_api_keys", id="otk-b", tenant_id=B, key_prefix="anr_otp_live_BBBB", key_hash="x", status="active",
           created_at=RECENT)
    db.add("otp_settings", tenant_id=A, default_mode="sms", sms_sender_id="ANRIL", sms_message_id="77",
           wa_template_name="otp_auth", wa_template_language="en",
           status_webhook_url="https://hooks.example/status", status_webhook_secret="SECRET-WEBHOOK-A")
    db.add("message_templates", id="mt-a", tenant_id=A, name="otp_auth", language="en", status="APPROVED",
           category="AUTHENTICATION", body_text="{{1}} is your code")
    db.add("message_templates", id="mt-a2", tenant_id=A, name="diwali", language="en", status="APPROVED",
           category="MARKETING", body_text="Promo")
    db.add("message_templates", id="mt-b", tenant_id=B, name="B-ONLY auth", language="en", status="APPROVED",
           category="AUTHENTICATION", body_text="B-ONLY")
    return db


@pytest.fixture
def db():
    return seed()


def check(answer, *, own=()):
    """The three standing promises for every tool: A's data, nobody else's, no secrets."""
    blob = text(answer)
    for needle in own:
        assert needle in blob, f"{needle!r} missing from the answer"
    assert_only_a(answer)
    assert_no_secrets(answer)


def test_phone_numbers(db):
    out = run(tools.phone_numbers, db)
    check(out, own=["+919000000001", "A line"])
    assert [n["id"] for n in out["whatsapp_numbers"]] == ["num-a"]
    assert [n["id"] for n in out["calling_numbers"]] == ["vn-a"]
    assert "health" in out["whatsapp_numbers"][0]


def test_phone_numbers_other_tenant_sees_only_theirs(db):
    out = run(tools.phone_numbers, db, tenant=B)
    assert "+919000000001" not in text(out) and "A line" not in text(out)
    assert "+918888888888" in text(out)


def test_calling_setup(db):
    out = run(tools.calling_setup, db)
    check(out, own=["Morning team", "sim_basic"])
    assert "999" not in text(out["telecalling"])


def test_call_scripts_list_and_one(db):
    out = run(tools.call_scripts, db)
    check(out, own=["Welcome script"])
    assert [s["id"] for s in out["scripts"]] == [SCRIPT_A] and out["scripts"][0]["steps"] == 2
    one = run(tools.call_scripts, db, script_id=SCRIPT_A)
    check(one, own=["Ask budget"])


def test_call_scripts_never_another_clients_script(db):
    with pytest.raises(ToolError):
        run(tools.call_scripts, db, script_id=SCRIPT_B)


def test_call_review_list(db):
    out = run(tools.call_review, db)
    check(out, own=["Priya"])
    assert len(out["leads"]) == 1 and out["more"] is False


def test_call_review_one_lead(db):
    out = run(tools.call_review, db, lead_id=LEAD_A)
    check(out, own=["Asked for a quote"])
    assert out["calls"][0]["has_recording"] is True
    assert "recording_url" not in out["calls"][0]


def test_call_review_other_clients_lead_is_not_found(db):
    with pytest.raises(ToolError):
        run(tools.call_review, db, lead_id=LEAD_B)


def test_call_review_limit_checked(db):
    with pytest.raises(ToolError):
        run(tools.call_review, db, limit=51)
    with pytest.raises(ToolError):
        run(tools.call_review, db, days=0)


def test_connect_website(db):
    out = run(tools.connect_website, db)
    check(out, own=["Shop door", "Quote form"])
    form = out["instant_forms"]["forms"][0]
    assert form["leads_last_30_days"] == 2
    assert out["instant_forms"]["facebook_page_connected"] is True


def test_setup_status(db):
    out = run(tools.setup_status, db)
    check(out)
    assert out["channels_connected"]["whatsapp"] is True
    assert out["channels_connected"]["instagram"] is False  # only B has an instagram token
    assert out["channels_connected"]["sms"] is True


def test_setup_status_other_tenant(db):
    out = run(tools.setup_status, db, tenant=B)
    assert out["channels_connected"]["instagram"] is True
    assert out["channels_connected"]["whatsapp"] is False


def test_sms_overview(db):
    out = run(tools.sms_overview, db)
    check(out, own=["Diwali SMS", "ANRIL"])
    assert out["status"]["connected"] is True
    assert out["balance"]["sms_left"] == 1234


def test_sms_overview_off_when_feature_missing(db):
    db.tables["tenants"][0]["enabled_features"] = ["whatsapp"]
    out = run(tools.sms_overview, db)
    check(out)
    assert out["status"]["enabled"] is False and "campaigns" not in out


def test_sms_messages(db):
    out = run(tools.sms_messages, db)
    check(out, own=["Diwali offer"])
    assert out["total"] == 2
    assert len(out["messages"]) == 2


def test_sms_messages_limit(db):
    assert len(run(tools.sms_messages, db, limit=1)["messages"]) == 1
    with pytest.raises(ToolError):
        run(tools.sms_messages, db, limit=51)
    with pytest.raises(ToolError):
        run(tools.sms_messages, db, limit=0)


def test_otp_overview(db):
    out = run(tools.otp_overview, db)
    check(out, own=["otp_auth"])
    assert out["website_keys"]["has_active_key"] is True
    assert out["website_status_updates_set"] is True
    row = out["recent_requests"][0]
    assert row["phone"].endswith("0005") and "9000000005" not in text(out)
    assert "code" not in row and "code_masked" not in row


def test_otp_overview_other_tenant(db):
    out = run(tools.otp_overview, db, tenant=B)
    blob = text(out)
    assert "otp_auth" not in blob and "919000000005" not in blob
    assert out["website_keys"]["active_count"] == 1
    assert "anr_otp_live_BBBB" not in blob


def test_no_tool_takes_a_client_argument():
    import inspect

    for fn in (tools.phone_numbers, tools.calling_setup, tools.call_scripts, tools.call_review,
               tools.connect_website, tools.setup_status, tools.sms_overview, tools.sms_messages,
               tools.otp_overview):
        for name in inspect.signature(fn).parameters:
            assert "tenant" not in name and "client" not in name and "user" not in name


def test_all_nine_are_approved():
    for name in ("phone_numbers", "calling_setup", "call_scripts", "call_review", "connect_website",
                 "setup_status", "sms_overview", "sms_messages", "otp_overview"):
        assert name in wrapper.APPROVED_TOOLS


def test_clean_drops_secret_looking_fields():
    cleaned = tools._clean({"a": 1, "api_key": "x", "nested": [{"token": "t", "ok": 2, "code": "9"}], "key": "k"})
    assert cleaned == {"a": 1, "nested": [{"ok": 2}]}


def test_the_harness_itself_catches_a_write_and_a_secret(db):
    """Guards against a test that can never fail: planted secrets exist, and a write is recorded."""
    planted = text(db.tables)
    for secret in SECRETS:
        assert secret in planted, f"{secret!r} was never planted"

    def sneaky():
        try:
            tools.get_supabase().table("leads").update({"name": "x"})
        except Exception:
            pass  # a tool swallowing the error must still be caught

    with pytest.raises(AssertionError, match="tried to write"):
        run(sneaky, db)
    with pytest.raises(AssertionError, match="leaked"):
        assert_no_secrets({"x": "SECRET-WA-TOKEN-A"})
