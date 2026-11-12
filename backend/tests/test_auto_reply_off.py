"""Settings > Auto-Reply: two master switches (AI Replies, Instant Templates) and a switch
per source (owner, 2026-11-12). Off = nothing automatic of that kind reaches a customer.
See services/automation_guards.py."""
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routes import webhook
from app.services import auto_messages, marketplace_leads
from app.services import automation_guards as guards
from app.services import meta_lead_forms as forms
from tests.fake_supabase import FakeSupabase

TENANT = "tenant-1"


def settings(sources: dict | None = None, **values: str):
    """Stand-in for the tenant's app_settings as the guards read them."""
    stored = dict(values)
    if sources is not None:
        stored[guards.SOURCES_KEY] = json.dumps(sources)
    return patch.object(guards, "get_setting",
                        side_effect=lambda key, fallback=None, tenant_id=None: stored.get(key, fallback))


AI_OFF = settings(ai_auto_reply_enabled="false")
TEMPLATES_OFF = settings(instant_templates_enabled="false")
ALL_ON = settings()


# ── The rules themselves ─────────────────────────────────────────────────────────


def test_everything_is_on_when_nothing_is_saved():
    with ALL_ON:
        assert all(guards.ai_replies_allowed(TENANT, s.key) for s in guards.SOURCES if s.ai)
        assert all(guards.instant_template_allowed(TENANT, s.key) for s in guards.SOURCES if s.template)


def test_ai_master_off_stops_every_ai_reply_but_not_templates():
    with AI_OFF:
        assert not guards.ai_replies_allowed(TENANT, "whatsapp", "indiamart")
        assert not guards.ai_replies_allowed(TENANT, "telegram")
        assert guards.instant_template_allowed(TENANT, "indiamart")


def test_template_master_off_stops_every_template_but_not_ai():
    with TEMPLATES_OFF:
        assert not any(guards.instant_template_allowed(TENANT, s.key) for s in guards.SOURCES if s.template)
        assert guards.ai_replies_allowed(TENANT, "whatsapp")


def test_channel_row_off_stops_ai_on_that_channel_only():
    with settings({"instagram": {"ai": False}}):
        assert not guards.ai_replies_allowed(TENANT, "instagram")
        assert guards.ai_replies_allowed(TENANT, "whatsapp")


def test_lead_source_row_off_stops_ai_for_those_leads_on_any_channel():
    # Ravi came from IndiaMART and now chats on WhatsApp: the IndiaMART row decides too.
    with settings({"indiamart": {"ai": False}}):
        assert not guards.ai_replies_allowed(TENANT, "whatsapp", "indiamart")
        assert guards.ai_replies_allowed(TENANT, "whatsapp", "whatsapp")
        assert guards.instant_template_allowed(TENANT, "indiamart")


def test_instant_forms_and_website_rows_match_their_lead_sources():
    with settings({"instant_forms": {"ai": False}, "website": {"ai": False}}):
        assert not guards.ai_replies_allowed(TENANT, "whatsapp", "meta_form")
        assert not guards.ai_replies_allowed(TENANT, "whatsapp", "api")


def test_unknown_or_new_lead_source_is_on():
    with settings({"indiamart": {"ai": False}}):
        assert guards.ai_replies_allowed(TENANT, "whatsapp", "upload")
        assert guards.ai_replies_allowed(TENANT, "whatsapp", "some_future_connector")


def test_broken_stored_json_reads_as_all_on():
    with patch.object(guards, "get_setting", side_effect=lambda key, fallback=None, tenant_id=None:
                      "{not json" if key == guards.SOURCES_KEY else fallback):
        assert guards.instant_template_allowed(TENANT, "indiamart")


def test_validate_rejects_unknown_sources_and_switches():
    assert json.loads(guards.validate_source_flags('{"indiamart": {"template": false}}')) == {
        "indiamart": {"template": False}}
    for bad in ('{"nope": {"ai": false}}', '{"whatsapp": {"template": false}}',
                '{"partner": {"ai": false}}', '{"indiamart": {"ai": "off"}}', "[]", "x"):
        with pytest.raises(ValueError):
            guards.validate_source_flags(bad)


def test_block_reason_names_the_switch_that_stops_the_reply():
    with AI_OFF:
        assert guards.ai_reply_block_reason(TENANT, "whatsapp", "indiamart") == \
            "AI Replies is switched off for the whole business"
    with settings({"telegram": {"ai": False}, "indiamart": {"ai": False}}):
        assert guards.ai_reply_block_reason(TENANT, "telegram", None) == "AI replies are switched off for Telegram"
        assert guards.ai_reply_block_reason(TENANT, "whatsapp", "indiamart") == \
            "AI replies are switched off for IndiaMART leads"
        assert guards.ai_reply_block_reason(TENANT, "whatsapp", "justdial") is None


def test_normalize_accepts_operator_booleans_and_rejects_junk():
    updates = {"ai_auto_reply_enabled": False, "instant_templates_enabled": "true",
               "auto_reply_sources": '{"partner": {"template": false}}'}
    guards.normalize_auto_reply_updates(updates)
    assert updates == {"ai_auto_reply_enabled": "false", "instant_templates_enabled": "true",
                       "auto_reply_sources": '{"partner": {"template": false}}'}
    with pytest.raises(ValueError):
        guards.normalize_auto_reply_updates({"instant_templates_enabled": "maybe"})


def test_source_rows_report_current_state_and_missing_switches():
    with settings({"indiamart": {"template": False}}):
        rows = {r["key"]: r for r in guards.source_rows(TENANT)}
    assert rows["indiamart"]["template"] is False and rows["indiamart"]["ai"] is True
    assert rows["whatsapp"]["template"] is None and rows["partner"]["ai"] is None


def test_every_source_has_at_least_one_switch_and_a_unique_key():
    keys = [s.key for s in guards.SOURCES]
    assert len(keys) == len(set(keys))
    assert all(s.ai or s.template for s in guards.SOURCES)


# ── WhatsApp media with no caption: no canned ack, no typing indicator ───────────


def _no_recent_ack_db() -> MagicMock:
    """The media-ack dedupe lookup finds nothing, so only the switch can stop the ack."""
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value \
        .gte.return_value.limit.return_value.execute.return_value.data = []
    return db


async def _inbound(msg_type: str, body: str, send: AsyncMock, typing: AsyncMock) -> None:
    with patch("app.db.supabase.get_supabase", return_value=_no_recent_ack_db()), \
         patch("app.services.conversation_state.get_or_create_state", return_value={"message_count": 0}), \
         patch("app.services.intake.note_lead_message"), \
         patch("app.services.ai_reply.send_whatsapp", send), \
         patch("app.services.meta_cloud.send_typing_indicator", typing), \
         patch("app.services.context_builder.build_scorer_context", return_value=""), \
         patch("app.services.ai_reply.record_tamil_lock_request"), \
         patch("app.services.ai_reply.generate_reply", new=AsyncMock()):
        await webhook._process_inbound_message_background(
            lead_id="lead-1", tenant_id=TENANT, phone="+919999999999", body=body, msg_type=msg_type,
            meta_phone_number_id="pn-1", meta_message_id="wamid.1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("msg_type", ["image", "video", "document", "sticker"])
async def test_uncaptioned_media_gets_no_ack_when_ai_off(msg_type):
    send, typing = AsyncMock(return_value="wamid.out"), AsyncMock()
    with AI_OFF:
        await _inbound(msg_type, "", send, typing)
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncaptioned_media_gets_no_ack_when_whatsapp_row_off():
    send, typing = AsyncMock(return_value="wamid.out"), AsyncMock()
    with settings({"whatsapp": {"ai": False}}):
        await _inbound("image", "", send, typing)
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncaptioned_media_still_gets_ack_when_on():
    send, typing = AsyncMock(return_value="wamid.out"), AsyncMock()
    with ALL_ON:
        await _inbound("image", "", send, typing)
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_typing_indicator_when_ai_off():
    send, typing = AsyncMock(), AsyncMock()
    with AI_OFF:
        await _inbound("text", "hello", send, typing)
    typing.assert_not_awaited()


# ── Website/API Auto-Messages ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("switches", [TEMPLATES_OFF, settings({"website": {"template": False}})])
async def test_auto_message_is_skipped_when_switched_off(switches):
    db = FakeSupabase()
    row = db.add("auto_message_sends", tenant_id=TENANT, phone="+919999999999", status="queued",
                 rule_id="r1", source="website")
    send = AsyncMock()
    with switches, patch("app.services.meta_cloud.send_template_message", send):
        assert await auto_messages.send_one(db, row) is False
    send.assert_not_awaited()
    saved = db.rows("auto_message_sends")[0]
    assert (saved["status"], saved["reason"]) == ("skipped", "ai_auto_reply_off")


# ── IndiaMART / JustDial ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("provider,switches,expect_sent", [
    ("indiamart", ALL_ON, True),
    ("indiamart", TEMPLATES_OFF, False),
    ("indiamart", settings({"indiamart": {"template": False}}), False),
    ("justdial", settings({"indiamart": {"template": False}}), True),
    ("indiamart", AI_OFF, True),  # the AI switch does not touch templates
])
@pytest.mark.asyncio
async def test_marketplace_welcome_follows_its_switches(provider, switches, expect_sent):
    db = FakeSupabase()
    db.add("message_templates", id="tpl-1", tenant_id=TENANT, name="welcome", language="en",
           body_text="Hi {{1}}", status="APPROVED", header_media_type=None)
    send = AsyncMock()
    with switches, patch("app.config_dynamic.get_setting", return_value="tpl-1"), \
         patch("app.services.meta_cloud.send_template_message", send):
        sent = await marketplace_leads.send_welcome_template(db, TENANT, "+919999999999", {"name": "Priya"}, provider)
    assert sent is expect_sent
    assert send.await_count == (1 if expect_sent else 0)


# ── Facebook/Instagram Instant forms ─────────────────────────────────────────────


def _form_db():
    db = FakeSupabase()
    db.add("meta_lead_forms", tenant_id=TENANT, form_id="555", template_id="tpl-1", template_variables=[])
    row = db.add("meta_form_leads", tenant_id=TENANT, form_id="555", phone="+919876543210", name="Priya",
                 answers=[], lead_id=None, template_status="pending")
    return db, row


@pytest.mark.asyncio
@pytest.mark.parametrize("switches", [TEMPLATES_OFF, settings({"instant_forms": {"template": False}})])
async def test_instant_form_template_not_sent_automatically_when_off(switches):
    db, row = _form_db()
    send = AsyncMock()
    with switches, patch("app.services.meta_cloud.send_template_message", send):
        assert await forms.send_form_template(db, TENANT, row["id"]) == "failed"
    send.assert_not_awaited()
    assert "Instant templates were off" in db.rows("meta_form_leads")[0]["template_error"]


@pytest.mark.asyncio
async def test_instant_form_manual_resend_still_goes_when_off():
    db, row = _form_db()
    template = {"id": "tpl-1", "name": "welcome", "language": "en", "body_text": "Hi {{1}}"}
    send = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})
    with TEMPLATES_OFF, patch("app.services.meta_lead_forms.sendable_templates", return_value=[template]), \
         patch("app.services.meta_cloud.send_template_message", send):
        assert await forms.send_form_template(db, TENANT, row["id"], manual=True) == "sent"
    send.assert_awaited_once()


# ── Partner API ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("switches", [TEMPLATES_OFF, settings({"partner": {"template": False}})])
async def test_partner_sends_refused_when_off(switches):
    from app.services import intake
    send = AsyncMock()
    with switches, patch("app.services.ai_reply.send_whatsapp", send), \
         patch("app.services.meta_cloud.send_template_message", send):
        status_t, body_t = await intake.partner_send_template({"template_code": "x", "phone": "919999999999"}, TENANT, db=MagicMock())
        status_x, body_x = await intake.partner_send_text({"text": "hi", "phone": "919999999999"}, TENANT, db=MagicMock())
        astro = await intake.deliver_astro_reply({"external_ref": "s-1", "reply_id": 1}, TENANT, db=MagicMock())
    assert (status_t, body_t["code"]) == (409, "auto_reply_off")
    assert (status_x, body_x["code"]) == (409, "auto_reply_off")
    assert astro["reason"] == "auto_reply_off"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_partner_sends_ignore_the_ai_switch():
    from app.services import intake
    with AI_OFF:
        assert await intake._partner_switched_off(TENANT) is None


# ── Tripwire: a new connector / automatic sender must check the switches ─────────

APP = Path(__file__).resolve().parents[1] / "app"
_SEND = re.compile(
    r"await\s+[\w.]*\b(send_whatsapp|send_text_message|send_template_message|send_media_message|"
    r"send_interactive\w*|send_typing_indicator|send_approved_template|send_instagram\w*|"
    r"send_facebook\w*|send_telegram\w*|send_messenger\w*)\("
)
_CHECKS_SWITCH = re.compile(
    r"ai_replies_allowed|instant_template_allowed|master_switch_on|ai_auto_reply_enabled"
)

# Files that send to customers without a switch check. Each needs a reason.
# A new file NOT in this list must call automation_guards.ai_replies_allowed (AI messages)
# or instant_template_allowed (a connector's template, after adding it to SOURCES).
EXEMPT = {
    "routes/leads.py": "manual: team chat replies, new message, custom broadcast",
    "routes/upload.py": "manual: upload campaign message, bulk send, test send",
    "routes/media.py": "manual: team sends a file in chat",
    "routes/intake.py": "payment messages (owner: keep going)",
    "routes/deals.py": "manual: Send payment link",
    "routes/auto_messages.py": "manual: owner's preview send",
    "routes/lead_details_share.py": "manual: Send details",
    "routes/instant_forms.py": "manual: Resend button",
    "services/meta_cloud.py": "the low-level sender itself",
    "services/broadcast_executor.py": "manual: broadcasts",
    "services/scheduled_templates.py": "manual: a team member scheduled it",
    "services/share_product.py": "manual: Share product",
    "services/call_details_share.py": "manual: Send details on WhatsApp",
    "services/sms_campaigns.py": "manual: SMS campaigns",
    "services/whatsapp_notify.py": "alerts to the business's own staff, not customers",
    "services/growth.py": "alerts to the business's own staff, not customers",
    "services/deals.py": "payment link / payment messages (owner: keep going)",
    "services/deal_actions.py": "only runs inside generate_reply, after its switch check",
    "services/deal_turn.py": "only runs inside generate_reply, after its switch check",
    "services/partner_events.py": "only called by intake.partner_send_template, after its switch check",
}


def test_every_automatic_sender_checks_the_auto_reply_switches():
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        if _SEND.search(text) and not _CHECKS_SWITCH.search(text):
            offenders.append(rel)
    assert not offenders, (
        f"{offenders} send messages to customers without checking Settings > Auto-Reply. Call "
        "app.services.automation_guards.ai_replies_allowed / instant_template_allowed before sending "
        "(a new connector also goes in automation_guards.SOURCES), or, if it is a manual "
        "(team-triggered) send, add it to EXEMPT with the reason."
    )
