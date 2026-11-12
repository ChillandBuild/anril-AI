"""Settings > Auto-Reply OFF = nothing automatic reaches a customer, on any channel or
connector (owner, 2026-11-12). See services/automation_guards.master_switch_on."""
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routes import webhook
from app.services import auto_messages, marketplace_leads
from app.services import meta_lead_forms as forms
from tests.fake_supabase import FakeSupabase

TENANT = "tenant-1"
OFF = patch("app.services.automation_guards.master_switch_on", return_value=False)
ON = patch("app.services.automation_guards.master_switch_on", return_value=True)


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
async def test_uncaptioned_media_gets_no_ack_when_off(msg_type):
    send, typing = AsyncMock(return_value="wamid.out"), AsyncMock()
    with OFF:
        await _inbound(msg_type, "", send, typing)
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncaptioned_media_still_gets_ack_when_on():
    send, typing = AsyncMock(return_value="wamid.out"), AsyncMock()
    with ON:
        await _inbound("image", "", send, typing)
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_typing_indicator_when_off():
    send, typing = AsyncMock(), AsyncMock()
    with OFF:
        await _inbound("text", "hello", send, typing)
    typing.assert_not_awaited()


# ── Website/API Auto-Messages ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_message_is_skipped_when_off():
    db = FakeSupabase()
    row = db.add("auto_message_sends", tenant_id=TENANT, phone="+919999999999", status="queued", rule_id="r1")
    send = AsyncMock()
    with OFF, patch("app.services.meta_cloud.send_template_message", send):
        assert await auto_messages.send_one(db, row) is False
    send.assert_not_awaited()
    saved = db.rows("auto_message_sends")[0]
    assert (saved["status"], saved["reason"]) == ("skipped", "ai_auto_reply_off")


# ── IndiaMART / marketplaces ─────────────────────────────────────────────────────


@pytest.mark.parametrize("switch_on", [False, True])
@pytest.mark.asyncio
async def test_marketplace_welcome_follows_the_switch(switch_on):
    db = FakeSupabase()
    db.add("message_templates", id="tpl-1", tenant_id=TENANT, name="welcome", language="en",
           body_text="Hi {{1}}", status="APPROVED", header_media_type=None)
    send = AsyncMock()
    with patch("app.services.automation_guards.master_switch_on", return_value=switch_on), \
         patch("app.config_dynamic.get_setting", return_value="tpl-1"), \
         patch("app.services.meta_cloud.send_template_message", send):
        sent = await marketplace_leads.send_welcome_template(db, TENANT, "+919999999999", {"name": "Priya"})
    assert sent is switch_on
    assert send.await_count == (1 if switch_on else 0)


# ── Facebook/Instagram Instant forms ─────────────────────────────────────────────


def _form_db():
    db = FakeSupabase()
    db.add("meta_lead_forms", tenant_id=TENANT, form_id="555", template_id="tpl-1", template_variables=[])
    row = db.add("meta_form_leads", tenant_id=TENANT, form_id="555", phone="+919876543210", name="Priya",
                 answers=[], lead_id=None, template_status="pending")
    return db, row


@pytest.mark.asyncio
async def test_instant_form_template_not_sent_automatically_when_off():
    db, row = _form_db()
    send = AsyncMock()
    with OFF, patch("app.services.meta_cloud.send_template_message", send):
        assert await forms.send_form_template(db, TENANT, row["id"]) == "failed"
    send.assert_not_awaited()
    assert "Auto-Reply was off" in db.rows("meta_form_leads")[0]["template_error"]


@pytest.mark.asyncio
async def test_instant_form_manual_resend_still_goes_when_off():
    db, row = _form_db()
    template = {"id": "tpl-1", "name": "welcome", "language": "en", "body_text": "Hi {{1}}"}
    send = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})
    with OFF, patch("app.services.meta_lead_forms.sendable_templates", return_value=[template]), \
         patch("app.services.meta_cloud.send_template_message", send):
        assert await forms.send_form_template(db, TENANT, row["id"], manual=True) == "sent"
    send.assert_awaited_once()


# ── Tripwire: a new connector / automatic sender must check the switch ───────────

APP = Path(__file__).resolve().parents[1] / "app"
_SEND = re.compile(
    r"await\s+[\w.]*\b(send_whatsapp|send_text_message|send_template_message|send_media_message|"
    r"send_interactive\w*|send_typing_indicator|send_approved_template|send_instagram\w*|"
    r"send_facebook\w*|send_telegram\w*|send_messenger\w*)\("
)
_CHECKS_SWITCH = re.compile(r"master_switch_on|ai_auto_reply_enabled")

# Files that send to customers but are allowed to while Auto-Reply is off. Each needs a reason.
# A new file NOT in this list must call automation_guards.master_switch_on before it sends.
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
    "services/intake.py": "payment messages + partner app sends, not AI (owner: keep going)",
    "services/partner_events.py": "partner app sends, not AI (owner: keep going)",
}


def test_every_automatic_sender_checks_the_auto_reply_switch():
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
        "app.services.automation_guards.master_switch_on(tenant_id) before sending, or, if it is a "
        "manual (team-triggered) send, add it to EXEMPT with the reason."
    )
