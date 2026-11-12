"""Gates shared by every automated outbound path, and Settings > Auto-Reply.

Settings > Auto-Reply has two master switches and a per-source table (owner, 2026-11-12):
  - AI Replies (`ai_auto_reply_enabled`): every AI-written message: replies and their
    fallbacks, the media ack, the typing indicator, re-engagement, silence nudges.
  - Instant Templates (`instant_templates_enabled`): the template a connector sends the
    moment a new lead arrives (Instant forms, IndiaMART, JustDial, website/API
    Auto-Messages) and the partner app's sends.
  - `auto_reply_sources`: JSON {source_key: {"ai": bool, "template": bool}}, one row per
    SOURCES entry. A missing key means ON, so a source added later starts on.
A message goes out only when its master switch AND its row are on. For an AI reply both
the chat channel's row and the lead's own source row must be on (an IndiaMART lead
chatting on WhatsApp needs WhatsApp and IndiaMART on).

A NEW connector: add it to SOURCES (it appears on the settings page by itself) and call
instant_template_allowed / ai_replies_allowed before sending.
tests/test_auto_reply_off.py fails for any module that sends without a check.

Deliberately NOT gated: sends a team member triggers by hand (chat, broadcasts, scheduled
templates, Share product, previews, instant-form resend), the STOP confirmation, and
payment messages.

lead_blocks_automated_outbound is deliberately narrow: ONLY the three lead-level checks
that reengagement_service and silence_nudge genuinely share. reengagement does not check
ai_enabled/converted_at/blocked_at, so those are NOT there.
"""
import json
import logging
from dataclasses import dataclass

from app.config_dynamic import get_setting

logger = logging.getLogger(__name__)

AI_MASTER_KEY = "ai_auto_reply_enabled"
TEMPLATE_MASTER_KEY = "instant_templates_enabled"
SOURCES_KEY = "auto_reply_sources"


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    group: str  # "channel" | "lead"
    template: bool  # has an instant template to switch
    ai: bool  # has AI replies to switch
    hint: str = ""
    lead_sources: tuple[str, ...] = ()  # leads.source values that belong to this row


SOURCES: tuple[Source, ...] = (
    Source("whatsapp", "WhatsApp", "channel", template=False, ai=True),
    Source("instagram", "Instagram", "channel", template=False, ai=True),
    Source("facebook", "Facebook", "channel", template=False, ai=True),
    Source("telegram", "Telegram", "channel", template=False, ai=True),
    Source("instant_forms", "Instant forms", "lead", template=True, ai=True,
           hint="Facebook & Instagram lead ads", lead_sources=("meta_form",)),
    Source("indiamart", "IndiaMART", "lead", template=True, ai=True, lead_sources=("indiamart",)),
    Source("justdial", "JustDial", "lead", template=True, ai=True, lead_sources=("justdial",)),
    Source("website", "Website form / API", "lead", template=True, ai=True,
           hint="Auto-Messages", lead_sources=("website", "api", "store")),
    Source("partner", "Partner API", "lead", template=True, ai=False,
           hint="Templates and texts your partner app asks us to send"),
)
_BY_KEY = {s.key: s for s in SOURCES}
_ROW_FOR_LEAD_SOURCE = {ls: s.key for s in SOURCES for ls in s.lead_sources}


def parse_source_flags(raw: str | None) -> dict[str, dict[str, bool]]:
    """Stored JSON -> {key: {"ai": bool, "template": bool}}. Junk reads as 'all on'."""
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        logger.warning("auto_reply_sources is not valid JSON; treating every source as on")
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: {f: v[f] for f in ("ai", "template") if isinstance(v.get(f), bool)}
            for k, v in data.items() if isinstance(v, dict)}


def validate_source_flags(raw: str) -> str:
    """For the settings save: only known sources and switches, booleans only. Returns
    the normalised JSON; raises ValueError with a plain message."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("Auto-reply sources must be JSON")
    if not isinstance(data, dict):
        raise ValueError("Auto-reply sources must be an object")
    clean: dict[str, dict[str, bool]] = {}
    for key, flags in data.items():
        source = _BY_KEY.get(key)
        if not source or not isinstance(flags, dict):
            raise ValueError(f"Unknown auto-reply source: {key}")
        for field, value in flags.items():
            if field not in ("ai", "template") or not getattr(source, field) or not isinstance(value, bool):
                raise ValueError(f"{source.label} has no '{field}' switch")
        clean[key] = dict(flags)
    return json.dumps(clean, sort_keys=True)


def _flags(tenant_id: str) -> dict[str, dict[str, bool]]:
    return parse_source_flags(get_setting(SOURCES_KEY, tenant_id=tenant_id))


def _row_on(flags: dict, key: str | None, field: str) -> bool:
    return not key or flags.get(key, {}).get(field, True)


def master_switch_on(tenant_id: str) -> bool:
    """The AI Replies master switch. Callers decide whether an off switch consumes their
    job or leaves it queued."""
    return get_setting(AI_MASTER_KEY, fallback="true", tenant_id=tenant_id) != "false"


def template_master_on(tenant_id: str) -> bool:
    return get_setting(TEMPLATE_MASTER_KEY, fallback="true", tenant_id=tenant_id) != "false"


def ai_replies_allowed(tenant_id: str, channel: str | None, lead_source: str | None = None) -> bool:
    """AI master on, the chat channel's row on, and the lead's source row on."""
    if not master_switch_on(tenant_id):
        return False
    flags = _flags(tenant_id)
    channel_row = channel if channel in _BY_KEY else None
    return _row_on(flags, channel_row, "ai") and _row_on(flags, _ROW_FOR_LEAD_SOURCE.get(lead_source or ""), "ai")


def ai_replies_allowed_for_lead(db, tenant_id: str, channel: str, lead_id: str) -> bool:
    """Same, reading the lead's source. A failed read falls back to the channel check."""
    lead_source = None
    try:
        rows = (db.table("leads").select("source").eq("id", lead_id).eq("tenant_id", tenant_id)
                .limit(1).execute()).data or []
        lead_source = rows[0].get("source") if rows else None
    except Exception as e:
        logger.warning(f"Lead source read failed for {lead_id}: {e}")
    return ai_replies_allowed(tenant_id, channel, lead_source)


def instant_template_allowed(tenant_id: str, source_key: str) -> bool:
    """Instant Templates master on and this source's template row on."""
    return template_master_on(tenant_id) and _row_on(_flags(tenant_id), source_key, "template")


def lead_blocks_automated_outbound(lead: dict) -> str | None:
    """Return a human-readable skip reason, or None if sending is allowed."""
    if not lead.get("phone"):
        return "no phone"
    if lead.get("whatsapp_undeliverable"):
        return "whatsapp undeliverable"
    if lead.get("opted_out"):
        return "opted out"
    return None
